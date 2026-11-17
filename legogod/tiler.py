# ============================================================
# 程序化精确铺砖求解器：预算编排与下层快照复用
#
# 单层铺砖算法在 tiler_layer.py，多步局部图修复在 tiler_repair.py（单文件 ≤500 行约束）。
# 本模块保留所有对外公开接口与常量导出，保持既有调用与测试补丁挂载点完全兼容。
# ============================================================
import random
import re
import time

from . import suspension
from .geometry import interior_cells, step_cells, stud_cells
from .parts_library import COLORS, PART_MAP, voxel_color_map
from .support_reasons import reason_buckets
from .tiler_layer import (BRICK_SIZES, MAX_BACKTRACK, RESTARTS, TilerCancelled,  # noqa: F401
                          find_unsupported, precheck_support, solve_layer, solve_layer_exact)
from .tiler_repair import (analyze_disconnected, components_of as _components,  # noqa: F401
                           local_repair, main_color_of as _main_color,
                           typed_cells_of_layer as _typed_cells)

ROUNDS = 4
CROSS_SEAM_ROUNDS = 4
SEARCH_LADDER = ((MAX_BACKTRACK, RESTARTS), (100_000, 8), (400_000, 16))
MAX_REPAIR_STEPS = 6


def _color_stats(placed, target_color):
    """统计单层实际使用颜色分布；无设计色旧模型返回 None。"""
    if target_color is None:
        return None
    used = {}
    for part_id, *_ in placed:
        name = PART_MAP[part_id]["colorName"]
        used[name] = used.get(name, 0) + 1
    return used


def _layer_has_design_color(layer):
    """整层色或逐体素色都算有设计色。空 colorRows 不算。"""
    if layer.get("color"):
        return True
    rows = layer.get("colorRows")
    if not isinstance(rows, list):
        return False
    return any(isinstance(row, str) and any(ch not in ". " for ch in row) for row in rows)


def _finalize(parts, layers, adj=None):
    """由零件记录生成拓扑连续排序的 steps、usage、颜色统计及索引对齐的预拼子组件列表。"""
    raw_clusters = suspension.find_hanging_clusters(parts, adj)[0] if adj is not None else []
    order, clusters = suspension.topological_part_order(parts, raw_clusters)

    old_to_step_idx = {old_i: new_i for new_i, old_i in enumerate(order)}
    steps, usage = [], {}
    for step_idx, old_i in enumerate(order):
        po = parts[old_i]
        p = PART_MAP[po["piece"]]
        w, d = (p["d"], p["w"]) if po["rot"] else (p["w"], p["d"])
        steps.append({"layer": po["layer"], "piece": po["piece"], "x": po["x"], "z": po["z"],
                      "rotate": po["rot"], "w": w, "d": d, "step": step_idx + 1})
        usage[po["piece"]] = usage.get(po["piece"], 0) + 1

    color_by_layer = {L["y"]: (L.get("color") or None) for L in layers}
    # 逐体素配色只有 colorRows、没有整层 color。这种层也要计入颜色分布，
    # 否则方案 colors 恒为 {}，历史配色条全部是空的。没有设计色的旧模型仍然跳过。
    colored_layers = {L["y"] for L in layers if _layer_has_design_color(L)}
    per_layer = {}
    for po in parts:
        name = PART_MAP[po["piece"]]["colorName"]
        row = per_layer.setdefault(po["layer"], {})
        row[name] = row.get(name, 0) + 1
    colors_total, fallbacks = {}, []
    for y, used in sorted(per_layer.items()):
        if y not in colored_layers:
            continue
        for name, cnt in used.items():
            colors_total[name] = colors_total.get(name, 0) + cnt
        target = color_by_layer.get(y)
        if not target:
            continue
        off = {name: cnt for name, cnt in used.items() if name != target}
        if off:
            fallbacks.append({"layer": y, "target": target, "used": off})

    subassemblies = []
    for i, c in enumerate(clusters):
        mapped_bricks = sorted(old_to_step_idx[pi] for pi in c["bricks"])
        mapped_hang = sorted(old_to_step_idx[pi] for pi in c["hanging"])
        mapped_anc = sorted(old_to_step_idx[pi] for pi in c["anchors"])
        subassemblies.append({
            "id": f"sub{i + 1}",
            "bricks": mapped_bricks,
            "hangingBricks": mapped_hang,
            "anchorBricks": mapped_anc,
            "steps": [bi + 1 for bi in mapped_bricks],
        })
    return steps, usage, colors_total, fallbacks, subassemblies


def _failure(kind, message, layer=None, cells=None, offer=None, window_cells=None, info=None):
    """构造结构化失败字典。window_cells 是补丁窗口的全量种子，不替代提示用的 cells。

    info 是工作包 B 的结构失败补全：support 原因码分组 / disconnected 组件界面格与两侧
    组件摘要 / suspension 锁扣与子组件坐标；只放已经算出的坐标，不编造位置。
    """
    out = {"kind": kind, "message": message, "layer": layer,
           "cells": cells or [], "offer": offer}
    if window_cells is not None:
        out["window_cells"] = window_cells
    if info:
        out["info"] = info
    return out


def public_failure(failure):
    """复制一份对外失败，去掉内部重铺快照 offer。不改求解器仍持有的原字典。

    offer 只在 solve_with_budget 循环内复用。它的 stud_owner 用坐标元组当键，
    写进任务结果后，查询和历史落盘的 json.dumps 会直接断开。
    """
    if not isinstance(failure, dict) or "offer" not in failure:
        return failure
    out = dict(failure)
    out.pop("offer", None)
    return out


def _snapshot(y, inventory, parts, adj, stud_owner):
    """保存第 y 层尚未铺砖时的求解器完整快照，供定向重铺复用下层。"""
    return {"layer": y, "inventory": dict(inventory),
            "parts": [dict(p, parents=set(p["parents"])) for p in parts],
            "adj": [set(s) for s in adj],
            "stud_owner": dict(stud_owner)}


def _report_progress(on_progress, payload):
    """层开始前上报进度。回调失败只记日志，不能把一次正常求解打成失败。"""
    if on_progress is None:
        return
    try:
        on_progress(payload)
    except Exception as exc:  # noqa: BLE001 - 进度是旁路，求解本身必须继续
        print(f"[tiler] 进度上报失败（不影响求解）：{exc}", flush=True)


def _attempt(house, layers, seed, merge_first=None, deadline=None, reuse=None,
             should_stop=None, log=print, border_first=False, on_progress=None,
             round_index=1, round_total=1):
    """执行一次逐层铺砖尝试 + 多步单调局部图修复，返回 (solution|None, failure|None)。

    on_progress 在每一层开始铺之前调用，参数是当前层序号、总层数和轮次。
    不从铺完后的日志正文反推。
    """
    if reuse:
        inventory = dict(reuse["inventory"])
        parts = [dict(p, parents=set(p["parents"])) for p in reuse["parts"]]
        adj = [set(s) for s in reuse["adj"]]
        stud_owner = dict(reuse["stud_owner"])
        start = reuse["layer"]
    else:
        inventory = {p["id"]: p["count"] for p in PART_MAP.values()}
        parts, adj, stud_owner, start = [], [], {}, 0

    snapshots = {}
    out_of_time = False
    interior = interior_cells(house)
    main_color = _main_color(layers)

    for idx in range(start, len(layers)):
        L = layers[idx]
        y = L["y"]
        if should_stop is not None and should_stop():
            raise TilerCancelled()
        if deadline is not None and time.monotonic() >= deadline:
            out_of_time = True
            break
        _report_progress(on_progress, {
            "layer": idx + 1, "y": y, "total": len(layers),
            "round": round_index, "rounds": round_total,
        })
        snapshots[y] = _snapshot(y, inventory, parts, adj, stud_owner)
        target_color = L.get("color") or None
        if target_color and target_color not in COLORS:
            return None, _failure("internal", f"y={y} 层颜色 {target_color!r} 不在颜色表中", layer=y)
        typed = _typed_cells(L)
        cell_color = None
        if L.get("colorRows"):
            cell_color = voxel_color_map(L["rows"], L["colorRows"], target_color)
            missing = [pos for pos, c in cell_color.items() if not c]
            if missing:
                return None, _failure("internal",
                                      f"y={y} 层逐体素颜色不完整（{missing[:3]} 缺颜色）", layer=y)
            for (ix, iy, iz) in interior:
                if iy == y and (ix, iz) in cell_color:
                    cell_color[(ix, iz)] = None

        below = None if idx == 0 else set(stud_owner.keys())
        owners = None if idx == 0 else dict(stud_owner)
        comps = None if idx == 0 else _components(parts, adj)
        above_solid = set(_typed_cells(layers[idx + 1])) if idx + 1 < len(layers) else set()
        hang_ok = set()
        if idx == 0 and above_solid and (set(typed) - above_solid):
            # 定理：多层模型的 y=0 砖必须至少有 1 格位于 y=1 实体下方，否则在连接图中度数为 0。
            # 当 y=0 存在外露台阶且均可伸入 y=1 锚定时，直接将 above_solid 作为 y=0 必交锚定集。
            if not find_unsupported(typed, {c: "#" for c in above_solid}, cell_color):
                below = above_solid
        elif idx > 0:
            below_solid = set(_typed_cells(layers[idx - 1]))
            hang_ok = {c for c in typed if c not in below_solid and c in above_solid}

        support_err = precheck_support(typed, below, cell_color, above=above_solid)
        if support_err:
            below_typed = None if below is None else {c: "#" for c in below}
            bad = find_unsupported(typed, below_typed, cell_color, above=above_solid)
            window = [(x, y, z) for x, z, _reason in bad]
            log(f"[tiler] y={y} 支撑不可行：无支撑 {len(window)} 格，提示格 {min(64, len(typed))}")
            return None, _failure(
                "support",
                f"y={y} 层支撑不可行：{support_err}——请在悬臂根部增设托架/支撑柱或向内侧延伸锚定",
                layer=y, cells=[(x, y, z) for x, z in sorted(typed)][:64],
                offer=snapshots[y] if y > 0 else None,
                window_cells=window,
                info={"supportReasons": reason_buckets([(y, issue) for issue in bad])},
            )

        layer_deadline = deadline
        if deadline is not None:
            rem = max(0.0, deadline - time.monotonic())
            layer_deadline = time.monotonic() + max(2.0, rem * 0.5)
        placed = None
        border_first = bool((reuse or {}).get("border_first")) or border_first
        # 不同重铺轮次翻转奇偶主轴相位，提升异形边界的搜索多样性
        primary_axis = ("z" if (y + (seed // 2)) % 2 == 0 else "x")

        def _search(bt, rst, allow_fb, seed_off, dl=None):
            nonlocal placed
            placed = solve_layer(
                typed, below, inventory, random.Random(seed * 1000 + y + seed_off),
                target_color=target_color, allow_fallback=allow_fb,
                below_owners=owners, below_components=comps, merge_first=merge_first,
                cell_color=cell_color, max_backtrack=bt, restarts=rst,
                deadline=(layer_deadline if dl is None else dl),
                border_first=border_first, should_stop=should_stop,
                hang_ok=hang_ok, primary_axis=primary_axis, default_color=main_color,
            )
            return placed is not None

        def _exact(allow_fb):
            nonlocal placed
            placed = solve_layer_exact(
                typed, below, inventory, target_color=target_color,
                allow_fallback=allow_fb, cell_color=cell_color, deadline=layer_deadline,
                below_owners=owners, below_components=comps, should_stop=should_stop,
                hang_ok=hang_ok, default_color=main_color,
            )
            if placed is None:
                return False
            for (pid, _r, _x, _z) in placed:
                inventory[pid] = inventory.get(pid, 0) - 1
            return True

        def _time_left():
            return layer_deadline is None or time.monotonic() < layer_deadline

        for allow in (False, True):
            if placed is not None or not _time_left():
                break
            dl = min(layer_deadline, time.monotonic() + 1.0) if layer_deadline is not None else None
            _search(SEARCH_LADDER[0][0], SEARCH_LADDER[0][1], allow, 0, dl=dl)
        if placed is None and _time_left():
            _exact(False)
        if placed is None and _time_left():
            _exact(True)
        for tier, (bt, rst) in enumerate(SEARCH_LADDER[1:], start=1):
            if placed is not None or not _time_left():
                break
            for allow in (False, True):
                if placed is not None:
                    break
                _search(bt, rst, allow, tier * 7919)

        if placed is None:
            kind = "coverage"
            if layer_deadline is None or time.monotonic() < layer_deadline:
                inv_inf = {pid: 10 ** 9 for pid in inventory}
                res_inf = solve_layer_exact(
                    typed, below, inv_inf, target_color=target_color,
                    allow_fallback=True, cell_color=cell_color,
                    deadline=layer_deadline, hang_ok=hang_ok, default_color=main_color,
                )
                if res_inf is not None:
                    kind = "inventory"
            slope_cnt = sum(1 for ch in typed.values() if ch != "#")
            color_txt = "，逐体素配色" if cell_color else (f"，设计色 {target_color}" if target_color else "")
            msg = f"y={y} 层无法在「支撑 + 凸点 + 库存」约束下铺满（{len(typed)} 体素，斜面 {slope_cnt}{color_txt}）"
            msg += ("——请检查无支撑悬挑或奇数长反斜坡段" if kind == "coverage"
                    else "——可用颜色库存不足，请换用库存充足颜色")
            return None, _failure(kind, msg, layer=y,
                                  cells=[(x, y, z) for x, z in sorted(typed)][:64],
                                  offer=snapshots[y] if y > 0 else None)

        layer_indices = []
        for piece, rot, x, z in placed:
            p = PART_MAP[piece]
            w, d = (p["d"], p["w"]) if rot else (p["w"], p["d"])
            cells = [(x + i, z + j) for i in range(w) for j in range(d)]
            parents = {owners[c] for c in cells if owners and c in owners}
            parts.append({"layer": y, "piece": piece, "rot": rot, "x": x, "z": z,
                          "cells": cells, "parents": parents})
            pi = len(parts) - 1
            adj.append(set(parents))
            for par in parents:
                adj[par].add(pi)
            layer_indices.append(pi)
        stud_owner = {}
        for pi in layer_indices:
            po = parts[pi]
            for cell in stud_cells(PART_MAP[po["piece"]], po["x"], po["z"], po["rot"]):
                stud_owner[cell] = pi
        n_slope = sum(1 for piece, *_ in placed if "slope" in PART_MAP[piece])
        used = _color_stats(placed, target_color)
        log(f"[tiler] y={y}: {len(placed)} 块（斜面 {n_slope}，颜色 {used or '默认'}）")

    if out_of_time:
        return None, _failure("coverage", "求解时间预算在本轮内用尽", layer=None)

    final_comps = _components(parts, adj)
    if len(set(final_comps.values())) > 1:
        local_repair(
            parts, adj, house, layers, inventory, seed,
            max_steps=MAX_REPAIR_STEPS, deadline=deadline,
            should_stop=should_stop, solve_layer_fn=solve_layer,
        )
        final_comps = _components(parts, adj)
        if len(set(final_comps.values())) > 1:
            groups = {}
            for pi, cid in final_comps.items():
                groups.setdefault(cid, []).append(pi)
            main_group = max(groups.values(), key=len)
            loose = [pi for g in groups.values() if g is not main_group for pi in g]
            samples = [
                f"y={parts[pi]['layer']} x={min(c[0] for c in parts[pi]['cells'])}..{max(c[0] for c in parts[pi]['cells'])} "
                f"z={min(c[1] for c in parts[pi]['cells'])}..{max(c[1] for c in parts[pi]['cells'])}"
                for pi in loose[:5]
            ]
            loose_cells = [(c[0], parts[pi]["layer"], c[1]) for pi in loose[:8] for c in parts[pi]["cells"]]
            window_cells = [(c[0], parts[pi]["layer"], c[1]) for pi in loose for c in parts[pi]["cells"]]
            log(f"[tiler] 断连窗口：游离零件 {len(loose)}，全量 {len(window_cells)} 格，"
                f"提示 {len(loose_cells[:64])} 格")
            min_loose_layer = min(parts[pi]["layer"] for pi in loose)
            offer_layer = min_loose_layer if min_loose_layer > 0 else 1
            offer = snapshots.get(offer_layer) if 0 < offer_layer < len(layers) else None
            if offer is not None:
                offer = dict(offer, border_first=True)
            info = analyze_disconnected(house, window_cells) or {}
            return None, _failure(
                "disconnected",
                f"零件级连接图不连通：主结构 {len(main_group)} 块之外，还有 {len(groups) - 1} 组共 "
                f"{len(loose)} 块零件没连到主体（例如 {'；'.join(samples)}）——"
                f"请用跨缝砖压住交界处或延伸与主体的上下叠合",
                layer=min_loose_layer, cells=loose_cells[:64], offer=offer,
                window_cells=window_cells, info=info,
            )

    steps, usage, colors_total, fallbacks, subassemblies = _finalize(parts, layers, adj=adj)
    solution = {
        "model": "exact-tiler (正交错缝精确覆盖 + 多格正/反斜坡 + 单调局部图修复)",
        "valid": True,
        "attempts": 1,
        "strategy": "程序化精确铺贴：奇偶层正交扫描、无参字典序错缝择优，多格正/反斜坡按真实模具铺贴，"
                    "内部骨架色通配，悬吊簇提取为完整预拼子组件，断缝执行多步单调局部拆并修复。",
        "steps": steps,
        "usage": usage,
        "colors": colors_total,
        "colorFallbacks": fallbacks,
        "residualErrors": [],
        "subassemblies": subassemblies,
    }
    return solution, None


_COORD_RE = re.compile(r"\(x=(\d+),y=(\d+),z=(\d+)\)")


def _suspension_positions(report, solution):
    """从统一校验报告与方案步骤取悬吊锁扣/子组件坐标（工作包 B）。

    锁扣只来自校验已经算过的 suspensionWindow；子组件坐标由报告里的簇成员索引到
    solution.steps 的体素，只保留与失败窗口相交的簇。没有坐标时返回空，不编造。
    """
    lock = [tuple(int(v) for v in c) for c in (report.get("suspensionWindow") or [])]
    steps = (solution or {}).get("steps") or []
    sub = []
    for cluster in report.get("subassemblies") or []:
        cells = []
        for bi in cluster.get("bricks") or []:
            if not isinstance(bi, int) or not (0 <= bi < len(steps)):
                continue
            step = steps[bi]
            for (x, z) in step_cells(step):
                cells.append((int(x), int(step.get("layer") or 0), int(z)))
        if lock and not (set(cells) & set(lock)):
            continue  # 只保留失败窗口命中的簇（窗口是该簇的锁扣或子组件坐标）
        sub.extend(cells)
        if len(sub) >= 512:
            break
    return lock, sub[:512]


def _validation_failure(report, solution=None):
    """将统一校验失败报告映射为求解器结构化失败字典（悬吊附带锁扣/子组件坐标）。"""
    errs = report.get("errors") or []
    if any("库存" in e for e in errs):
        kind = "inventory"
    elif any(k in e for e in errs for k in ("吊挂", "倾覆", "锁扣", "悬浮", "质心", "预拼")):
        kind = "suspension"
    else:
        kind = "validation"
    cells = [
        (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        for e in errs[:8] for m in _COORD_RE.finditer(e)
    ]
    # 悬吊的锁扣/子组件坐标只来自校验已经算过的 suspensionWindow 与簇成员。没有坐标时不编。
    window = report.get("suspensionWindow") if kind == "suspension" else None
    if not window:
        window = None
    info = {}
    if kind == "suspension":
        lock, sub = _suspension_positions(report, solution)
        if lock or sub:
            info = {"lockCells": [list(c) for c in lock]}
            if sub:
                info["subassemblyCells"] = [list(c) for c in sub]
    return _failure(kind, "统一校验未通过：" + "；".join(errs[:3]),
                    layer=None, cells=cells[:64], window_cells=window, info=info)


def solve_with_budget(house, layers, deadline=None, rounds=None, validate_fn=None, log=print,
                      should_stop=None, border_first=False, merge_first_all=False,
                      on_progress=None):
    """带时间与轮数预算的求解主循环：自动换铺法并通过 validate_fn 候选验收。

    border_first/merge_first_all 是 solution 空间候选（只改铺法、不改模型）用的铺法变体开关，
    默认关闭，与既有行为一致。
    """
    if rounds is None:
        rounds = ROUNDS + CROSS_SEAM_ROUNDS
    reuse = None
    last_reuse_layer = -1
    last_failure = None
    used_rounds = 0
    for r in range(rounds):
        used_rounds = r + 1
        if should_stop is not None and should_stop():
            raise TilerCancelled()
        if deadline is not None and time.monotonic() >= deadline:
            break
        solution, failure = _attempt(
            house, layers, seed=r,
            merge_first=(True if (r >= ROUNDS or merge_first_all) else None),
            deadline=deadline, reuse=reuse, should_stop=should_stop, log=log,
            border_first=border_first, on_progress=on_progress,
            round_index=r + 1, round_total=rounds,
        )
        if solution is not None:
            if validate_fn is not None:
                report = validate_fn(house, solution)
                if report.get("ok"):
                    solution["validation"] = report
                    solution["attempts"] = used_rounds
                    return solution, None
                failure = _validation_failure(report, solution)
                log(f"[tiler] 第 {r + 1}/{rounds} 轮候选未通过统一校验（{failure['kind']}）")
            else:
                solution["attempts"] = used_rounds
                return solution, None
        else:
            log(f"[tiler] 第 {r + 1}/{rounds} 轮失败（{failure['kind']}）：{failure['message'][:200]}")
        last_failure = dict(failure)
        offer = failure.get("offer")
        if offer and failure["kind"] != "internal" and offer.get("layer", 0) > last_reuse_layer:
            reuse = offer
            last_reuse_layer = offer["layer"]
        else:
            reuse = None
        if failure["kind"] == "internal":
            return None, last_failure
    if last_failure is None:
        last_failure = _failure("coverage", "求解预算内未找到有效铺法")
    last_failure = dict(last_failure, rounds=used_rounds)
    if deadline is not None and time.monotonic() >= deadline:
        last_failure["budget_exhausted"] = True
    return None, last_failure
