# ============================================================
# 修订上下文结构化
#
# 结构化失败（support / coverage / disconnected / inventory）转成
# 「按层或按组件聚合的几何摘要 + 可执行修复建议」，供 revise_design 阶段使用。
# 只做几何聚合与文字生成，不改变任何判定；与具体造型、部位、模型无关。
# ============================================================

MAX_CELLS_PER_GROUP = 8   # 提示词里每组最多列的坐标数（其余给总数）

# A.3.5：support 原因码 → 标题与修法。提示必须按原因码分组，不得把所有 reason 混成一段。
SUPPORT_REASON_TITLES = {
    "slope_root_support": "斜坡根部无承托",
    "brick_support": "普通砖块无支撑",
    "color_fragment": "颜色碎片",
    "inverted_slope_pair": "反斜坡奇偶/配对失败",
    "ground_reachability": "接地不可达/浮动碎块",
    "slope_tip_interference": "反斜坡尖端模具干涉",
    "unknown": "原因未判明",
}
SUPPORT_REASON_FIXES = {
    "slope_root_support": "在斜坡根部正下方补托架/支撑柱（倒置楔或普通砖），或把该坡段向主体内侧平移一格；"
                          "不要削掉斜面特征",
    "brick_support": "在正下方补支撑柱/托架，或向有支撑的内侧延伸锚定一格，或把悬挑外缘整体内缩；"
                     "不要只改其中一两格",
    "color_fragment": "同色砖不能跨色铺：把这些格改成周围主色，或扩大同色连续区，"
                      "避免把需要同色砖的格切成孤立碎片；不要为凑同色改动核心特征",
    "inverted_slope_pair": "反斜坡必须 2 格一砖：把同字符连续段补成偶数长度，或改用正斜坡/普通砖",
    "ground_reachability": "该层存在与任何支撑格都不相连的悬空碎片：用跨缝砖/立柱把它接地连通，"
                           "或去掉这块碎块（先确认不是必需外观特征）",
    "slope_tip_interference": "反斜坡尖端正下方有向上凸点（模具干涉）：移开尖端下方的零件，"
                              "或把该反斜坡改成正斜坡/普通砖",
    "unknown": "修复类型无法判明：保留原始 reason 与错误格原文，不要猜测类别；按下方原文逐格核对",
}


def _reason_cells_text(entry, cap=MAX_CELLS_PER_GROUP):
    """原因码分组的坐标摘要（cells 已按 [x,y,z] 存）。"""
    cells = [tuple(c) for c in entry.get("cells") or []]
    shown = "、".join(f"(x={x},y={y},z={z})" for x, y, z in cells[:cap])
    rest = "" if len(cells) <= cap else f" 等共 {entry.get('count')} 格"
    return shown + rest


def _support_reason_groups(failure, model):
    """取 support 原因码分组：失败对象自带优先，否则按模型重跑预检归类。"""
    reasons = (failure or {}).get("support_reasons") \
        or ((failure or {}).get("info") or {}).get("supportReasons")
    if not reasons and model is not None and (failure or {}).get("cells"):
        try:
            from .agent import support_reasons_for_cells
            reasons = support_reasons_for_cells(model, failure.get("cells") or [])
        except (KeyError, TypeError, ValueError, ImportError):
            reasons = {}
    return reasons or {}


def _disconnected_info(failure, model):
    """取 disconnected 组件界面信息：失败对象自带优先，否则按模型与全量窗口重算。"""
    info = (failure or {}).get("info") or {}
    if info.get("interfaceCells") or info.get("components"):
        return info
    if model is None:
        return info
    try:
        from .tiler_repair import analyze_disconnected
        computed = analyze_disconnected(
            model, (failure or {}).get("window_cells") or (failure or {}).get("cells"))
    except (KeyError, TypeError, ValueError, ImportError):
        computed = None
    return computed or info


def _cell3(raw):
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return (int(raw[0]), int(raw[1]), int(raw[2]))
        except (TypeError, ValueError):
            return None
    return None


def _group_by_layer(cells):
    """{(x,y,z)} → [{layer, cells, count, bbox}]，按 y 升序。"""
    by_y = {}
    for c in cells:
        by_y.setdefault(c[1], []).append(c)
    groups = []
    for y in sorted(by_y):
        cs = sorted(by_y[y])
        xs = [c[0] for c in cs]
        zs = [c[2] for c in cs]
        groups.append({
            "layer": y,
            "count": len(cs),
            "bbox": (min(xs), max(xs), min(zs), max(zs)),
            "cells": cs,
        })
    return groups


def _bbox_text(bbox):
    x1, x2, z1, z2 = bbox
    return f"x={x1}..{x2}, z={z1}..{z2}"


def _fmt_cells(cells, cap=MAX_CELLS_PER_GROUP):
    shown = ", ".join(f"({x},{z})" for x, _y, z in cells[:cap])
    rest = "" if len(cells) <= cap else f" 等共 {len(cells)} 格"
    return shown + rest


def _dangling_cells(model, layer_y):
    """该层「正下方没有实体」的悬挑格（用于 coverage 的修复候选）。"""
    layers = (model or {}).get("layers") or []
    if layer_y is None or layer_y <= 0 or layer_y >= len(layers):
        return []
    rows = layers[layer_y].get("rows") or []
    below = layers[layer_y - 1].get("rows") or []
    out = []
    for z, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != "." and z < len(below) and x < len(below[z]) and below[z][x] == ".":
                out.append((x, layer_y, z))
    return out


def summarize(failure, model=None):
    """把结构化失败转成 {"headline", "groups", "advice"}。

    groups 每项：{"layer", "count", "bbox", "cells"}（cells 全量，调用方按需截断）。
    advice 是可直接拼进修订提示的中文建议列表；与具体造型无关。
    """
    failure = failure or {}
    kind = failure.get("kind")
    cells = [c for c in (_cell3(x) for x in (failure.get("cells") or [])) if c]
    groups = _group_by_layer(cells)
    advice = []

    if kind in ("support", "connectivity"):
        reason_map = _support_reason_groups(failure, model) if kind == "support" else {}
        if reason_map:
            # A.3.5：按原因码分流，每类给对应修法，不把所有 reason 混成一段
            for code in list(SUPPORT_REASON_TITLES):
                entry = reason_map.get(code)
                if not entry:
                    continue
                line = (f"【{SUPPORT_REASON_TITLES[code]}】{entry.get('count')} 格："
                        f"{_reason_cells_text(entry)}。修法：{SUPPORT_REASON_FIXES[code]}")
                if entry.get("rawReasons"):
                    line += "；原始原因（未判明类别，原样保留）：" + "；".join(entry["rawReasons"][:2])
                advice.append(line)
        else:
            if groups:
                parts = []
                for g in groups:
                    parts.append(f"y={g['layer']} 共 {g['count']} 格（{_bbox_text(g['bbox'])}）："
                                 f"{_fmt_cells(g['cells'])}")
                advice.append("无支撑格子按层聚合：" + "；".join(parts))
            advice.append("这些格下方没有可托底的凸点：优先「在悬臂根部增设反斜坡托架/支撑柱"
                          "（wedge kind=inverted）或向主体内侧延伸锚定，或把悬挑外缘整体内缩」，"
                          "不要只改其中一两格，也不要为过关削平炮管、挑檐等外观特征")
    elif kind == "coverage":
        layer = failure.get("layer")
        if layer is not None:
            dangling = _dangling_cells(model, layer)
            if dangling:
                dg = _group_by_layer([tuple(c) for c in dangling])[0]
                advice.append(f"y={layer} 层正下方没有实体的悬挑格共 {dg['count']} 格"
                              f"（{_bbox_text(dg['bbox'])}）：{_fmt_cells(dg['cells'])}")
                advice.append("保造型做法：在悬挑根部补托架/立柱（正/反斜坡或普通砖），"
                              "或让悬挑向主体内侧延伸一格锚定；不要优先把悬挑格改空——"
                              "那会把出檐、炮管等特征削平")
            else:
                advice.append(f"y={layer} 层无法铺满：检查该层是否有 1 格宽孤立条、"
                              f"颜色碎片（同色砖不能跨色）或库存不足的颜色；优先把该层轮廓改规整")
        advice.append("这是该层几何在「支撑+凸点+库存」下无精确覆盖，不是整体造型无解——"
                      "只改这一层相关的格，不要整模重画")
    elif kind == "disconnected":
        if groups:
            parts = []
            for g in groups:
                parts.append(f"y={g['layer']} 共 {g['count']} 格（{_bbox_text(g['bbox'])}）："
                             f"{_fmt_cells(g['cells'])}")
            advice.append("没连到主体的零件按层聚合：" + "；".join(parts))
            top = max(g["layer"] for g in groups)
            advice.append(f"这些零件只靠体素侧面相邻，乐高侧面不连接、必须有上下凸点："
                          f"在 y={top + 1} 层用一块砖同时压住这些零件和主体（跨缝），"
                          f"或把它们收进主体轮廓")
        info = _disconnected_info(failure, model)
        components = info.get("components") or []
        if components:
            lines = []
            for comp in components[:4]:
                bbox = comp.get("bbox") or []
                bbox_txt = (f"x={bbox[0]}..{bbox[1]}, y={bbox[2]}..{bbox[3]}, z={bbox[4]}..{bbox[5]}"
                            if len(bbox) == 6 else "?")
                lines.append(f"组件 {comp.get('id')}：{comp.get('voxels')} 体素，"
                             f"包围盒 {bbox_txt}，部位 {comp.get('parts') or '未归属'}")
            advice.append("两侧组件摘要：" + "；".join(lines))
        interfaces = info.get("interfaceCells") or []
        if interfaces:
            pairs = [f"({i['a'][0]},{i['a'][1]},{i['a'][2]})↔({i['b'][0]},{i['b'][1]},{i['b'][2]})"
                     for i in interfaces[:6]]
            advice.append(f"组件界面格（两侧侧面相邻但乐高侧面不连接）共 {len(interfaces)} 对："
                          + "；".join(pairs))
        connectable = info.get("connectableCells") or []
        if connectable:
            shown = "、".join(f"({c[0]},{c[1]},{c[2]})" for c in connectable[:8])
            advice.append(f"可连接邻域（界面格正上方空位，可放跨缝砖同时压住两侧凸点）共 "
                          f"{len(connectable)} 格：{shown}")
        advice.append("不要只删掉其中一两格：侧面贴合不算连接，删格不会让它们连上主体")
    elif kind == "suspension":
        info = (failure or {}).get("info") or {}
        lock_cells = info.get("lockCells") or []
        sub_cells = info.get("subassemblyCells") or []
        if lock_cells:
            shown = "、".join(f"({c[0]},{c[1]},{c[2]})" for c in lock_cells[:12])
            advice.append(f"锁扣凸点（校验已算出的真实坐标）共 {len(lock_cells)} 个：{shown}；"
                          f"在凸点正上方加宽跨接咬合面，使至少 2 个不共点凸点受力")
        if sub_cells:
            shown = "、".join(f"({c[0]},{c[1]},{c[2]})" for c in sub_cells[:12])
            advice.append(f"吊挂子组件体素共 {len(sub_cells)} 格：{shown}；"
                          f"减轻外挑质量或把重型部分移回底层支撑内")
        advice.append("吊挂子组件物理校核未通过：双凸点不足的请加宽上方咬合面（至少 2 个不共点凸点）；"
                      "倾覆力矩超限的请减轻外挑质量或加宽咬合跨度；质心不稳的请把重型部分移回底层支撑内")
        advice.append("保造型原则：不要为了过校验把垂耳、悬臂等特征删成贴墙薄片——"
                      "改支撑方式（托架/立柱/加宽咬合）而不是削特征")
    elif kind in ("inventory", "validation"):
        advice.append("库存不足：换用库存充足的颜色，或减少该色面积；颜色不能跨色铺砖，"
                      "同色区域不要被异色切成碎片")
    else:
        advice.append("按失败类型只改相关格，不要整模重画")

    headline = _HEADLINES.get(kind, "结构性失败")
    return {"headline": headline, "groups": groups, "advice": advice}


_HEADLINES = {
    "support": "设计预检：存在无论怎么铺砖都得不到支撑的体素",
    "connectivity": "设计预检：体素不连通",
    "coverage": "该层在「支撑 + 凸点 + 库存」约束下无法铺满",
    "disconnected": "零件级连接图不连通（有零件没连到主体）",
    "suspension": "吊挂子组件物理校核未通过（双凸点/抗倾覆/插入路径）",
    "inventory": "颜色库存不足，无法按设计色铺满",
    "validation": "方案统一校验未通过",
}


def format_for_prompt(failure, model=None, max_groups=8):
    """生成可直接拼进 revise_design 阶段说明的一段文字（空失败返回空串）。

    默认最多 8 组：support 失败按原因码分组后最多 6 类 + 组件/锁扣坐标行，不被截断。
    """
    info = summarize(failure, model)
    lines = [info["headline"] + "："]
    for adv in info["advice"][:max_groups]:
        lines.append("- " + adv)
    return "\n".join(lines)
