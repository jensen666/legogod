"""方案合法性统一校验器。

对 model（逐层体素设计）+ solution（零件摆放方案）做与真实搭建一致的七项检查：
  1) 覆盖：每个体素恰好被一个零件覆盖、不越界、不重叠、不占空位；
  2) 库存：每种零件用量不超过库存；
  3) 凸点连接与反斜坡防干涉：矩形砖全格、多格正斜坡仅高端、反斜坡顶面满凸点但仅根部承托且尖端下方无凸点；
     无下层直托的零件允许由上方跨接大砖吊挂；
  4) 零件级连通：所有零件通过凸点连接构成唯一连通分量；
  5) 悬吊物理：吊挂子组件 ≥2 个不重合锁扣凸点（消旋下界）+ 偏心倾覆静力平衡；
  6) 装配重放：常规砖逐块放置；完整预拼子组件（含悬吊砖+上方跨接锁扣砖）在跨接砖外部支撑已就位时
     整组一次扣入，且竖直落位路径无上方已就位零件阻挡（无装配卡口）；
  7) 稳定性：重心投影检查，启用悬吊或反斜坡的模型强制要求质心落在底层支撑凸包内。
"""
from . import suspension
from .geometry import root_cells, step_cells, stud_cells
from .parts_library import PART_MAP

_EPS = 1e-9


def _step_cells(step):
    """返回单个步骤零件覆盖的 (x, z) 体素列表。"""
    return step_cells(step)


def _step_stud_cells(step):
    """返回该零件顶面输出凸点的 (x, z) 体素集合。"""
    part = PART_MAP.get(step.get("piece"))
    if part is None:
        return set()
    return set(stud_cells(part, step["x"], step["z"], bool(step.get("rotate"))))


def _step_bottom_recess_cells(step):
    """返回该零件底面可接收下方凸点承托的 (x, z) 体素集合（反斜坡仅根部可承托）。"""
    part = PART_MAP.get(step.get("piece"))
    if part is None:
        return set()
    roots = root_cells(part, step["x"], step["z"], bool(step.get("rotate")))
    if roots is not None:
        return set(roots)
    return set(_step_cells(step))


def _brick_mass(step):
    """返回单块零件的相对质量（楔形斜坡按形状质损系数折减）。"""
    part = PART_MAP.get(step.get("piece"))
    cells = _step_cells(step)
    if not cells:
        return 0.0
    factor = part.get("massFactor", 1.0) if part is not None else 1.0
    return len(cells) * factor


def _convex_hull(points):
    """计算二维点集凸包（monotone chain），返回逆时针顶点列表。"""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _point_in_polygon(pt, poly):
    """判断点是否位于凸多边形内（含边界；退化线段/单点按共线区间判定）。"""
    x, z = pt
    if len(poly) == 1:
        return abs(x - poly[0][0]) < _EPS and abs(z - poly[0][1]) < _EPS
    if len(poly) == 2:
        (x1, z1), (x2, z2) = poly
        cross = (x2 - x1) * (z - z1) - (z2 - z1) * (x - x1)
        if abs(cross) > 1e-6:
            return False
        return min(x1, x2) - _EPS <= x <= max(x1, x2) + _EPS and min(z1, z2) - _EPS <= z <= max(z1, z2) + _EPS
    sign = 0
    n = len(poly)
    for i in range(n):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % n]
        v = (x2 - x1) * (z - z1) - (z2 - z1) * (x - x1)
        if abs(v) < _EPS:
            continue
        if sign == 0:
            sign = 1 if v > 0 else -1
        elif (v > 0) != (sign > 0):
            return False
    return True


def _stability_check(steps, checks, warnings):
    """简化稳定性检查：计算加权质心水平投影是否落在底层落地零件凸包内。"""
    if not steps:
        checks["stability"] = {"ok": False, "detail": "没有零件，无法计算重心"}
        return {"checked": False, "level": "none", "detail": "没有零件"}
    total_mass = 0.0
    cx = cz = 0.0
    for s in steps:
        cells = _step_cells(s)
        if not cells:
            continue
        m = _brick_mass(s)
        total_mass += m
        cx += m * (sum(c[0] for c in cells) / len(cells) + 0.5)
        cz += m * (sum(c[1] for c in cells) / len(cells) + 0.5)
    if total_mass <= 0:
        checks["stability"] = {"ok": False, "detail": "零件体积为 0，无法计算重心"}
        return {"checked": False, "level": "none", "detail": "零件体积为 0"}
    cx /= total_mass
    cz /= total_mass

    base_cells = set()
    for s in steps:
        if s.get("layer") == 0:
            base_cells.update(_step_cells(s))
    if not base_cells:
        checks["stability"] = {"ok": False, "detail": "没有落地零件"}
        return {"checked": False, "level": "none", "detail": "没有落地零件"}

    # 用落地格四角顶点构造真实支撑底面凸包（单块 2x2 也有真实面积，不会误判为 0 面积点）
    corners = [(x + dx, z + dz) for (x, z) in base_cells for dx in (0.0, 1.0) for dz in (0.0, 1.0)]
    hull = _convex_hull(corners)
    inside = _point_in_polygon((cx, cz), hull)
    detail = (f"重心投影 ({cx:.2f}, {cz:.2f}) {'落在' if inside else '超出'}底层支撑范围内"
              f"（简化重心检查，未做完整抗倾覆/摩擦分析）")
    checks["stability"] = {"ok": bool(inside), "detail": detail}
    if not inside:
        warnings.append("重心投影超出底层支撑范围，模型可能倾倒：" + detail)
    return {"checked": True, "level": "basic", "detail": detail,
            "center": [round(cx, 3), round(cz, 3)]}


def _replay_assembly(steps, step_of, occ, clusters, placed_errors):
    """按步骤重放拼装：普通砖逐块下托就位；预拼子组件在其最后一步整体扣入并检查无遮挡。"""
    ordered = sorted(range(len(steps)), key=lambda i: (steps[i].get("step") or i + 1))
    order_pos = {idx: pos for pos, idx in enumerate(ordered)}
    cluster_of_brick = {}
    cluster_trigger = {}
    cluster_cells_3d = {}
    for ci, cluster in enumerate(clusters):
        bset = cluster["bricks"]
        for bi in bset:
            cluster_of_brick[bi] = ci
        # 在子组件全部成员均到达其步骤号（即上方跨接砖就位时刻）执行整体扣入
        last_brick = max(bset, key=lambda b: order_pos[b])
        cluster_trigger[last_brick] = ci
        cluster_cells_3d[ci] = {
            (x, steps[bi].get("layer", 0), z)
            for bi in bset for (x, z) in _step_cells(step_of[bi])
        }

    placed = set()

    def _has_placed_support(idx):
        s = step_of[idx]
        y = s.get("layer", 0)
        if y == 0:
            return True
        for (x, z) in _step_bottom_recess_cells(s):
            pidx = occ.get((x, y - 1, z))
            if pidx is not None and pidx in placed and (x, z) in _step_stud_cells(step_of[pidx]):
                return True
        return False

    def _insert_subassembly(ci):
        c_bricks = set(clusters[ci]["bricks"])
        anchors = clusters[ci].get("anchors") or []
        if not anchors:
            placed_errors.append(f"预拼子组件 {ci + 1} 缺少连回主干的上方跨接锁扣砖")
            return False
        # 1) 跨接砖必须至少有一块已在主结构 placed 上获得下方凸点承托（扣入锚点就位）
        if not any(_has_placed_support(ai) for ai in anchors):
            placed_errors.append(
                f"预拼子组件 {ci + 1} 扣入时，其上方跨接砖在主结构上尚无已就位凸点支撑")
            return False
        # 2) 子组件内部连通性：桌面预拼时所有成员通过子组件内部凸点边连成一体
        sub_adj = {b: set() for b in c_bricks}
        for b in c_bricks:
            by = steps[b].get("layer", 0)
            for (x, z) in _step_bottom_recess_cells(step_of[b]):
                pidx = occ.get((x, by - 1, z))
                if pidx in c_bricks and (x, z) in _step_stud_cells(step_of[pidx]):
                    sub_adj[b].add(pidx)
                    sub_adj[pidx].add(b)
        start = next(iter(c_bricks))
        vis, st = {start}, [start]
        while st:
            cur = st.pop()
            for nb in sub_adj[cur]:
                if nb not in vis:
                    vis.add(nb)
                    st.append(nb)
        if len(vis) != len(c_bricks):
            placed_errors.append(f"预拼子组件 {ci + 1} 内部零件未互锁成一体，无法桌面预拼")
            return False
        # 3) 竖直插入无卡口（Sweep Clearance）：已就位主干零件不得位于子组件任一体素正上方
        for pidx in placed:
            py = step_of[pidx].get("layer", 0)
            for (x, z) in _step_cells(step_of[pidx]):
                for (cx, cy, cz) in cluster_cells_3d[ci]:
                    if x == cx and z == cz and py > cy:
                        placed_errors.append(
                            f"预拼子组件 {ci + 1} 从上方落位时路径被第 {pidx} 个零件"
                            f"（y={py} 层 x={x} z={z}）阻挡（装配卡口）")
                        return False
        return True

    for idx in ordered:
        ci = cluster_of_brick.get(idx)
        if ci is not None:
            # 属于预拼子组件的砖在桌面上预拼，直到到达子组件最后一步时整组扣入主结构
            if cluster_trigger.get(idx) == ci:
                if _insert_subassembly(ci):
                    placed.update(clusters[ci]["bricks"])
            continue
        if not _has_placed_support(idx):
            s = step_of[idx]
            placed_errors.append(
                f"第 {idx} 个零件（{s.get('piece')}，y={s.get('layer', 0)}）放置时下方没有已就位的凸点支撑"
                f"（装配顺序非法或该处悬空）")
            continue
        placed.add(idx)


def validate_solution(model, solution, inventory=None):
    """校验 model + solution 的完整搭建合法性，返回结构化报告 dict。"""
    errors, warnings, checks = [], [], {}
    layers = model.get("layers") or []
    layer_cells = {L["y"]: set(map(tuple, L["cells"])) for L in layers}
    grid_w = model.get("grid", {}).get("w", 0)
    grid_d = model.get("grid", {}).get("d", 0)
    steps = solution.get("steps") or []
    step_of = {i: s for i, s in enumerate(steps)}

    if not steps:
        return {"ok": False, "errors": ["方案没有任何零件"], "warnings": [],
                "checks": {"coverage": {"ok": False, "detail": "没有零件"}},
                "stability": {"checked": False, "level": "none", "detail": "没有零件"}}

    # ---------- 1) 覆盖 / 越界 / 重叠 / 空位 ----------
    occ, out_of_range, overlaps, on_empty = {}, [], [], []
    for idx, s in enumerate(steps):
        if s.get("piece") not in PART_MAP:
            errors.append(f"第 {idx} 个零件使用了未知零件 id：{s.get('piece')!r}")
            continue
        y = s.get("layer")
        if y not in layer_cells:
            out_of_range.append(f"第 {idx} 个零件的层 y={y} 不存在")
            continue
        cells = _step_cells(s)
        if not cells:
            errors.append(f"第 {idx} 个零件没有覆盖任何体素")
            continue
        for (x, z) in cells:
            if not (0 <= x < grid_w and 0 <= z < grid_d):
                out_of_range.append(f"第 {idx} 个零件覆盖了越界体素 (x={x},z={z})")
                continue
            key = (x, y, z)
            if key in occ:
                overlaps.append(f"体素 (x={x},y={y},z={z}) 被第 {occ[key]} 与第 {idx} 个零件同时覆盖")
            else:
                occ[key] = idx
            if (x, z) not in layer_cells[y]:
                on_empty.append(f"第 {idx} 个零件覆盖了 y={y} 的空位 (x={x},z={z})")
    errors += out_of_range[:10] + overlaps[:10] + on_empty[:10]

    missing = [f"体素 (x={x},y={y},z={z}) 未被任何零件覆盖"
               for y, cs in layer_cells.items() for (x, z) in cs if (x, y, z) not in occ]
    errors += missing[:10]
    coverage_ok = not (out_of_range or overlaps or on_empty or missing)
    checks["coverage"] = {
        "ok": coverage_ok,
        "detail": (f"覆盖 {len(occ)}/{sum(len(c) for c in layer_cells.values())} 体素，"
                   f"越界 {len(out_of_range)}、重叠 {len(overlaps)}、占空位 {len(on_empty)}、漏覆盖 {len(missing)}"),
    }

    # ---------- 2) 库存 ----------
    usage = {}
    for s in steps:
        pid = s.get("piece")
        if pid in PART_MAP:
            usage[pid] = usage.get(pid, 0) + 1
    stock_errors = [
        f"零件 {pid} 用了 {used} 块，库存只有 {cap}"
        for pid, used in usage.items()
        for cap in [inventory[pid] if inventory is not None and pid in inventory else PART_MAP[pid]["count"]]
        if used > cap
    ]
    errors += stock_errors
    checks["inventory"] = {
        "ok": not stock_errors,
        "detail": f"{len(usage)} 种零件共 {sum(usage.values())} 块"
                  + (f"，超库存 {len(stock_errors)} 种" if stock_errors else "，库存充足"),
    }

    # ---------- 3) 凸点连接与反斜坡防干涉 ----------
    interference = []

    def stud_parents(idx, step):
        y = step.get("layer")
        parents = set()
        if y is None or y == 0:
            return parents
        recess = _step_bottom_recess_cells(step)
        for (x, z) in _step_cells(step):
            parent_idx = occ.get((x, y - 1, z))
            if parent_idx is None:
                continue
            has_stud_below = (x, z) in _step_stud_cells(step_of[parent_idx])
            if (x, z) in recess:
                if has_stud_below:
                    parents.add(parent_idx)
            elif has_stud_below:
                interference.append(
                    f"第 {idx} 个反斜坡零件（{step.get('piece')}，y={y}）悬挑斜面正下方 "
                    f"(x={x},z={z}) 存在向上凸点（模具物理干涉）")
        return parents

    all_parents = {idx: stud_parents(idx, s) for idx, s in enumerate(steps)}
    has_child = {p for ps in all_parents.values() for p in ps}
    no_stud = []
    for idx, s in enumerate(steps):
        if s.get("layer", 0) == 0 or all_parents[idx] or idx in has_child:
            continue
        no_stud.append(
            f"第 {idx} 个零件（{s.get('piece')}，y={s.get('layer')}）既没有下层凸点支撑，"
            f"也没有上方零件压住它（悬浮孤岛）")
    errors += interference[:10] + no_stud[:10]
    checks["stud_connection"] = {
        "ok": not (no_stud or interference),
        "detail": ("所有上层零件都有合法凸点连接或吊挂且无斜面干涉" if not (no_stud or interference)
                   else f"无连接 {len(no_stud)} 处、反斜坡干涉 {len(interference)} 处"),
    }

    # ---------- 4) 零件级连通图 ----------
    adj = {i: set() for i in range(len(steps))}
    for idx, ps in all_parents.items():
        for parent in ps:
            adj[idx].add(parent)
            adj[parent].add(idx)
    seen, components = set(), 0
    for node in range(len(steps)):
        if node in seen:
            continue
        components += 1
        stack = [node]
        seen.add(node)
        while stack:
            cur = stack.pop()
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
    if components > 1:
        errors.append(f"零件级连接图不连通：{components} 个分离组件（整体不是一体）")
    checks["part_graph"] = {
        "ok": components == 1,
        "detail": f"零件连接图 {components} 个组件（节点 {len(steps)}，连接边 {sum(len(v) for v in adj.values()) // 2}）",
    }

    # ---------- 5) 悬吊物理校核 ----------
    parts_records = [{
        "layer": s.get("layer", 0), "piece": s.get("piece"), "rot": bool(s.get("rotate")),
        "x": s.get("x", 0), "z": s.get("z", 0), "cells": _step_cells(s),
        "parents": all_parents.get(idx) or set(),
    } for idx, s in enumerate(steps)]
    clusters, susp_errors = suspension.check_all(parts_records, adj)
    has_hanging = bool(clusters)
    errors += susp_errors[:10]
    # 只有没通过的簇才带 failureCells。通过的校核不编窗口。
    suspension_window = []
    if susp_errors:
        for cluster in clusters:
            suspension_window.extend(cluster.get("failureCells") or [])
    checks["suspension"] = {
        "ok": not susp_errors,
        "detail": (f"{len(clusters)} 个预拼子组件全部通过双凸点与抗倾覆校核" if clusters
                   else "无吊挂子组件"),
    }

    # ---------- 6) 装配重放 ----------
    bad_order = []
    _replay_assembly(steps, step_of, occ, clusters, bad_order)
    errors += bad_order[:10]
    checks["assembly_order"] = {
        "ok": not bad_order,
        "detail": ("按步骤顺序可逐块放置（含预拼子组件整体扣入）" if not bad_order
                   else f"{len(bad_order)} 处装配顺序/卡口非法"),
    }

    # ---------- 7) 稳定性 ----------
    stability = _stability_check(steps, checks, warnings)
    has_inverted = any((PART_MAP.get(s.get("piece")) or {}).get("rootMask") for s in steps)
    if (has_hanging or has_inverted) and stability.get("checked") \
            and not checks.get("stability", {}).get("ok"):
        errors.append("启用悬吊或反斜坡的模型整体质心投影超出底层支撑凸包："
                      + str(checks.get("stability", {}).get("detail", "")))
    checks["stability"] = {**checks.get("stability", {}), "enforced": bool(has_hanging or has_inverted)}

    subassemblies = [{
        "id": f"sub{i + 1}",
        "bricks": sorted(cluster["bricks"]),
        "hangingBricks": sorted(cluster["hanging"]),
        "anchorBricks": sorted(cluster["anchors"]),
        "steps": sorted(step_of[bi].get("step") or (bi + 1) for bi in cluster["bricks"]),
    } for i, cluster in enumerate(clusters)]

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "stability": stability,
        "subassemblies": subassemblies,
        "suspensionWindow": suspension_window,
        "summary": _summary(checks, stability),
    }


def _summary(checks, stability):
    """生成校验结果一句话摘要。"""
    items = []
    for key, label in (("coverage", "覆盖"), ("inventory", "库存"),
                       ("stud_connection", "凸点连接"), ("part_graph", "零件级连通"),
                       ("assembly_order", "装配顺序")):
        c = checks.get(key)
        if c:
            items.append(f"{label}{'通过' if c['ok'] else '未通过'}")
    if stability and stability.get("checked"):
        items.append("重心简化检查" + ("通过" if checks.get("stability", {}).get("ok") else "未通过"))
    else:
        items.append("稳定性未验证")
    return "、".join(items)
