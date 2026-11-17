# ============================================================
# 铺砖求解器：零件级连通图与多步严格单调局部图修复
# ============================================================
import random
import time

from .design_contract import solid_cells_of
from .geometry import interior_cells, stud_cells
from .parts_library import PART_MAP, voxel_color_map
from .tiler_layer import solve_layer


def components_of(parts, adj):
    """计算零件级无向连接图的连通分量标签 {part_idx: comp_id}。"""
    comp_of = {}
    cid = 0
    for node in range(len(parts)):
        if node in comp_of:
            continue
        stack = [node]
        comp_of[node] = cid
        while stack:
            cur = stack.pop()
            for nb in adj[cur]:
                if nb not in comp_of:
                    comp_of[nb] = cid
                    stack.append(nb)
        cid += 1
    return comp_of


def stud_owner_at_layer(parts, target_layer):
    """提取指定层 target_layer 上所有输出顶面凸点的位置 -> 零件索引映射。"""
    owner = {}
    for pi, po in enumerate(parts):
        if po["layer"] != target_layer:
            continue
        for cell in stud_cells(PART_MAP[po["piece"]], po["x"], po["z"], po["rot"]):
            owner[cell] = pi
    return owner


def typed_cells_of_layer(layer_dict):
    """将模型单层 rows 解析为非空体素字符映射 {(x, z): ch}。"""
    return {
        (x, z): ch
        for z, row in enumerate(layer_dict["rows"])
        for x, ch in enumerate(row)
        if ch != "."
    }


def main_color_of(layers):
    """统计逐体素配色层中出现频次最高的主色（供内部通配骨架砖优先选用）。"""
    cnt = {}
    for L in layers:
        if not L.get("colorRows"):
            continue
        m = voxel_color_map(L["rows"], L["colorRows"], L.get("color"))
        for name in m.values():
            if name:
                cnt[name] = cnt.get(name, 0) + 1
    return max(cnt, key=lambda k: cnt[k]) if cnt else None


def _try_repair_group(group_bricks, parts, adj, layers, layer_by_y, interior,
                      main_color, inventory, seed, step_i, deadline, should_stop,
                      solve_layer_fn):
    """针对单个游离组件交界处构建闭合局部窗口并尝试跨缝重铺；返回 (new_parts, new_adj, new_inv) 或 None。"""
    g_cells_by_y = {}
    for pi in group_bricks:
        g_cells_by_y.setdefault(parts[pi]["layer"], set()).update(parts[pi]["cells"])

    # 选取游离组件及其上下相邻层 xz 距离 ≤1 的邻域砖作为局部拆并窗口（允许跨层压缝桥接）
    window = set(group_bricks)
    for pi, po in enumerate(parts):
        if pi in window:
            continue
        y = po["layer"]
        near_ys = (y - 1, y, y + 1)
        ref_cells = set().union(*(g_cells_by_y.get(ny, set()) for ny in near_ys))
        if not ref_cells:
            continue
        if any((c[0] + dx, c[1] + dz) in ref_cells
               for c in po["cells"] for dx in (-1, 0, 1) for dz in (-1, 0, 1)):
            window.add(pi)

    # 向上支撑闭合：窗口内砖支撑的上方子件一并纳入重铺窗口，避免破坏窗口外零件支撑
    changed = True
    while changed:
        changed = False
        for pi in list(window):
            for nb in adj[pi]:
                if parts[nb]["layer"] > parts[pi]["layer"] and nb not in window:
                    window.add(nb)
                    changed = True

    inv_work = dict(inventory)
    for pi in window:
        inv_work[parts[pi]["piece"]] = inv_work.get(parts[pi]["piece"], 0) + 1

    freed = {}
    for pi in window:
        po = parts[pi]
        l_typed = typed_cells_of_layer(layer_by_y[po["layer"]])
        freed.setdefault(po["layer"], {}).update({c: l_typed.get(c, "#") for c in po["cells"]})

    keep_idx = sorted(set(range(len(parts))) - window)
    index_map = {old: new for new, old in enumerate(keep_idx)}
    parts2 = [dict(parts[i],
                   parents={index_map[p] for p in parts[i]["parents"] if p in index_map})
              for i in keep_idx]
    adj2 = [set() for _ in parts2]
    for old_i, new_i in index_map.items():
        for nb in adj[old_i]:
            if nb in index_map:
                adj2[new_i].add(index_map[nb])
                adj2[index_map[nb]].add(new_i)

    layer_order = [L["y"] for L in layers]
    pos_of_y = {y: i for i, y in enumerate(layer_order)}

    for y in sorted(freed):
        L = layer_by_y[y]
        typed = freed[y]
        owners = {} if y == 0 else stud_owner_at_layer(parts2, y - 1)
        below = None if y == 0 else set(owners.keys())
        comps_below = None if y == 0 else components_of(parts2, adj2)
        idx = pos_of_y[y]
        above_solid = set(typed_cells_of_layer(layers[idx + 1])) if idx + 1 < len(layers) else set()
        hang_ok = set()
        if y > 0:
            below_solid = set(typed_cells_of_layer(layers[idx - 1]))
            hang_ok = {c for c in typed if c not in below_solid and c in above_solid}

        # 保留逐体素颜色与内部通配骨架语义，防止局部修复抹掉模型外壳颜色
        cell_color = None
        if L.get("colorRows"):
            cell_color = voxel_color_map(L["rows"], L["colorRows"], L.get("color"))
            for (ix, iy, iz) in interior:
                if iy == y and (ix, iz) in cell_color:
                    cell_color[(ix, iz)] = None

        # 交替尝试两个正交主轴，提高窗口内跨缝桥接命中率
        placed = None
        for axis in (("x", "z") if (y + step_i) % 2 == 1 else ("z", "x")):
            inv_try = dict(inv_work)
            placed = solve_layer_fn(
                typed, below, inv_try, random.Random(seed * 977 + step_i * 31 + y),
                target_color=L.get("color") or None, allow_fallback=not bool(cell_color),
                below_owners=owners, below_components=comps_below,
                cell_color=cell_color, merge_first=True, border_first=True,
                deadline=deadline, should_stop=should_stop, hang_ok=hang_ok,
                primary_axis=axis, default_color=main_color,
            )
            if placed is not None:
                inv_work = inv_try
                break
        if placed is None:
            return None

        for piece, rot, x, z in placed:
            p = PART_MAP[piece]
            w, d = (p["d"], p["w"]) if rot else (p["w"], p["d"])
            cells = [(x + i, z + j) for i in range(w) for j in range(d)]
            parents = {owners[c] for c in cells if c in owners} if y > 0 else set()
            po = {"layer": y, "piece": piece, "rot": rot, "x": x, "z": z,
                  "cells": cells, "parents": parents}
            pi = len(parts2)
            parts2.append(po)
            adj2.append(set(parents))
            for par in parents:
                adj2[par].add(pi)

    # 重建窗口顶层与上方保留砖之间的父子连接边（窗口内新砖顶凸点承托上方未拆砖）
    by_layer_cell = {}
    for pi, po in enumerate(parts2):
        for cell in stud_cells(PART_MAP[po["piece"]], po["x"], po["z"], po["rot"]):
            by_layer_cell[(po["layer"], cell)] = pi
    for pi, po in enumerate(parts2):
        if po["layer"] == 0:
            continue
        new_parents = set()
        for c in po["cells"]:
            par = by_layer_cell.get((po["layer"] - 1, c))
            if par is not None:
                new_parents.add(par)
        po["parents"] = new_parents
    adj_rebuilt = [set() for _ in parts2]
    for pi, po in enumerate(parts2):
        for par in po["parents"]:
            adj_rebuilt[pi].add(par)
            adj_rebuilt[par].add(pi)

    if any(v < 0 for v in inv_work.values()):
        return None
    floating = [pi for pi, po in enumerate(parts2) if not adj_rebuilt[pi] and po["layer"] > 0]
    if floating:
        return None
    return parts2, adj_rebuilt, inv_work


def local_repair(parts, adj, house, layers, inventory, seed, max_steps=6,
                 deadline=None, should_stop=None, solve_layer_fn=None):
    """多步严格单调局部图修复：每步要求 (连通分量数, 游离体素数) 字典序严格下降才提交。"""
    solve_fn = solve_layer_fn or solve_layer
    interior = interior_cells(house)
    main_color = main_color_of(layers)
    layer_by_y = {L["y"]: L for L in layers}

    def _metric(ps, ad):
        comps = components_of(ps, ad)
        groups = {}
        for pi, cid in comps.items():
            groups.setdefault(cid, []).append(pi)
        if len(groups) <= 1:
            return 1, 0, []
        main = max(groups.values(), key=len)
        loose_groups = sorted([g for g in groups.values() if g is not main], key=len)
        loose_vox = sum(len(ps[pi]["cells"]) for g in loose_groups for pi in g)
        return len(groups), loose_vox, loose_groups

    cur_k, cur_vox, loose_groups = _metric(parts, adj)
    if cur_k <= 1:
        return True

    for step_i in range(max_steps):
        if should_stop is not None and should_stop():
            return False
        if deadline is not None and time.monotonic() >= deadline:
            return False
        if cur_k <= 1:
            return True
        progressed = False
        for grp in loose_groups:
            cand = _try_repair_group(
                grp, parts, adj, layers, layer_by_y, interior, main_color,
                inventory, seed, step_i, deadline, should_stop, solve_fn,
            )
            if cand is None:
                continue
            parts2, adj2, inv2 = cand
            nk, nvox, next_groups = _metric(parts2, adj2)
            if (nk, nvox) < (cur_k, cur_vox):
                parts[:] = parts2
                adj[:] = [set(s) for s in adj2]
                inventory.clear()
                inventory.update(inv2)
                cur_k, cur_vox, loose_groups = nk, nvox, next_groups
                progressed = True
                break
        if not progressed:
            break
    return cur_k == 1


# ---------------- 结构失败组件分析（工作包 B：disconnected 失败信息补全） ----------------

_NB6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def part_cells_from_model(model):
    """从模型存档的 parts.boxes/coreCells 还原每个部位的实体格（存档没有 cells 字段）。

    boxes 是 region_boxes 生成的矩形覆盖（含端点），与实体求交即为该部位体素；
    coreCells 是防删核心，作为兜底并入。用于离线快照重算与失败信息摘要。
    """
    solid = solid_cells_of(model)
    out = {}
    for p in model.get("parts") or []:
        pid = str(p.get("id"))
        cells = set()
        for box in p.get("boxes") or []:
            try:
                for x in range(int(box["x1"]), int(box["x2"]) + 1):
                    for y in range(int(box["y1"]), int(box["y2"]) + 1):
                        for z in range(int(box["z1"]), int(box["z2"]) + 1):
                            if (x, y, z) in solid:
                                cells.add((x, y, z))
            except (KeyError, TypeError, ValueError):
                continue
        for raw in p.get("coreCells") or []:
            if isinstance(raw, (list, tuple)) and len(raw) == 3:
                cell = (int(raw[0]), int(raw[1]), int(raw[2]))
                if cell in solid:
                    cells.add(cell)
        out[pid] = cells
    return out


def _voxel_groups(cells):
    """6-连通体素分组，按最小格排序保证可复现。"""
    seen, groups = set(), []
    for start in sorted(cells):
        if start in seen:
            continue
        group, stack = set(), [start]
        seen.add(start)
        while stack:
            c = stack.pop()
            group.add(c)
            for d in _NB6:
                nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                if nb in cells and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        groups.append(group)
    return groups


def _bbox(cells):
    """体素集合包围盒 [minx, maxx, miny, maxy, minz, maxz]。"""
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    zs = [c[2] for c in cells]
    return [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]


def analyze_disconnected(model, window_cells, max_cells=512):
    """disconnected/connectivity 失败信息补全（可复现，不编造组件）。

    游离侧 = window_cells 与模型实体的交集（求解器给出的游离零件体素，或预检少数分量）；
    主体侧 = 其余实体。界面格 = 两侧 6-相邻的体素对（乐高侧面不连接，必须上方跨缝砖压住）；
    可连接邻域 = 界面格正上方 y+1 的空位（跨缝砖可同时压住两侧凸点），受网格与上限约束。
    没有游离侧或没有主体侧时返回 None。
    """
    solid = solid_cells_of(model)
    loose = {tuple(c) for c in (window_cells or []) if tuple(c) in solid}
    main = solid - loose
    if not loose or not main:
        return None
    groups = _voxel_groups(loose)
    side_of = {}
    for gi, group in enumerate(groups, 1):
        for c in group:
            side_of[c] = f"loose{gi}"
    for c in main:
        side_of[c] = "main"
    part_of = {}
    for pid, cells in part_cells_from_model(model).items():
        for c in cells:
            part_of[c] = pid

    def summary(side, cells):
        parts = sorted({part_of[c] for c in cells if c in part_of})
        return {"id": side, "voxels": len(cells), "bbox": _bbox(cells), "parts": parts[:8]}

    components = [summary("main", main)] + [
        summary(f"loose{gi}", group) for gi, group in enumerate(groups, 1)]
    interfaces = []
    for c in sorted(loose):
        for d in _NB6:
            nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
            if nb in solid and side_of.get(nb) != side_of.get(c):
                interfaces.append({"a": list(c), "b": list(nb),
                                   "sides": [side_of.get(c), side_of.get(nb)]})
    grid = model.get("grid") or {}
    width, depth = int(grid.get("w") or 0), int(grid.get("d") or 0)
    n_layers = len(model.get("layers") or [])
    connectable, seen = [], set()
    for item in interfaces:
        for cell in (item["a"], item["b"]):
            cand = (cell[0], cell[1] + 1, cell[2])
            if (0 <= cand[0] < width and 0 <= cand[2] < depth
                    and 0 <= cand[1] < n_layers and cand not in solid and cand not in seen):
                seen.add(cand)
                connectable.append(list(cand))
    return {"components": components,
            "interfaceCells": interfaces[:max_cells],
            "connectableCells": connectable[:max_cells]}
