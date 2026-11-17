# ============================================================
# 铺砖求解器：单层支撑预检、奇偶正交错缝启发式与 MRV 精确覆盖
# ============================================================
import time

from .geometry import (ALL_SLOPE_CHARS, SOLID_CHAR,
                       brick_sizes, root_cells, stud_cells)
from .parts_library import (COLORS, COLOR_NAMES, PART_MAP, RECT_SHAPES,
                            SLOPE_PARTS_BY_CHAR, part_for)

MAX_BACKTRACK = 20_000
RESTARTS = 4
BRICK_SIZES = brick_sizes()


class TilerCancelled(Exception):
    """外部取消信号（should_stop 返回 True）触发立即中止搜索。"""


def find_unsupported(typed, below_typed, cell_color=None, above=None):
    """返回本层无论如何铺砖都无法满足支撑或模具配对的体素列表。

    元素是 (x, z, reason) 三元组，额外带 A.3.5 稳定原因码 .code；旧的三元解包完全兼容。
    判定与旧实现逐条一致，实现在 support_reasons.py（带码版本）。
    """
    from .support_reasons import find_unsupported_coded
    return find_unsupported_coded(typed, below_typed, cell_color, above)


def precheck_support(typed, below, cell_color=None, above=None):
    """铺砖前单层支撑预检：返回首条不可行原因字符串，全部可行时返回 None。"""
    below_typed = None if below is None else {c: SOLID_CHAR for c in below}
    bad = find_unsupported(typed, below_typed, cell_color, above=above)
    if not bad:
        return None
    x, z, reason = bad[0]
    return f"(x={x},z={z}) {reason}（悬挑过大、该处过于孤立，或颜色碎片导致无法同色铺砖）"


def color_order(target_color, allow_fallback):
    """按优先级返回候选颜色序列：目标色 → 同色系 → 其它色。"""
    if target_color is None:
        return [None]
    if not allow_fallback:
        return [target_color]
    fam = COLORS[target_color]["family"]
    same = [c for c in COLOR_NAMES if c != target_color and COLORS[c]["family"] == fam]
    other = [c for c in COLOR_NAMES if c != target_color and COLORS[c]["family"] != fam]
    return [target_color] + same + other


def _candidate_parts(target_color, allow_fallback):
    """构造矩形砖候选零件列表（按颜色优先级排列）。"""
    out = []
    for color in color_order(target_color, allow_fallback):
        for shape_id in RECT_SHAPES:
            part = part_for(shape_id, color) if color else PART_MAP[shape_id]
            if part:
                out.append(part)
    return out


def _slope_cells_match(part, px, pz, cs, typed, ch):
    """检查斜坡零件覆盖格是否匹配体素类型：多格正斜坡高端位（studMask）允许为同向斜面或 '#'。"""
    if part.get("studMask"):
        highs = set(stud_cells(part, px, pz, False))
        return all(
            typed.get(c) in (ch, SOLID_CHAR) if c in highs else typed.get(c) == ch
            for c in cs
        )
    return all(typed.get(c) == ch for c in cs)


def _slope_parts_for(ch, target_color, allow_fallback, cache):
    """取某坡向字符可用的全部斜坡零件（1x1 / 2x1 / 2x2 正反斜坡）。"""
    key = (ch, target_color, allow_fallback)
    if key not in cache:
        by_color = SLOPE_PARTS_BY_CHAR.get(ch) or {}
        parts = []
        for color in color_order(target_color, allow_fallback):
            for part in (by_color.get(color) or []):
                parts.append(part)
        if not parts and target_color is None:
            for plist in by_color.values():
                parts.extend(plist)
        cache[key] = parts
    return cache[key]


def solve_layer(typed, below, inventory, rng, target_color=None, allow_fallback=False,
                below_owners=None, below_components=None, merge_first=None, cell_color=None,
                max_backtrack=None, restarts=None, deadline=None, border_first=False,
                should_stop=None, hang_ok=None, primary_axis="z", default_color=None):
    """启发式回溯铺单层：奇偶层正交主轴扫描 + 无参字典序错缝择优。"""
    if max_backtrack is None:
        max_backtrack = MAX_BACKTRACK
    if restarts is None:
        restarts = RESTARTS
    hang_ok = hang_ok or set()
    cellset = set(typed.keys())
    rect_parts = _candidate_parts(target_color, allow_fallback)
    color_rank = {p["id"]: i for i, p in enumerate(rect_parts)}
    slope_cache = {}

    def merge_score(cells):
        if not below_owners or not below_components:
            return 0
        comps = {below_components.get(below_owners[c]) for c in cells if c in below_owners}
        comps.discard(None)
        return len(comps)

    def seam_stats(cells, cset):
        if not below_owners:
            return 0, False
        cross = 0
        for (x, z) in cells:
            o = below_owners.get((x, z))
            if o is None:
                continue
            for nb in ((x + 1, z), (x, z + 1)):
                if nb in cset:
                    onb = below_owners.get(nb)
                    if onb is not None and onb != o:
                        cross += 1
        return cross, cross == 0

    def _below_cid(cell):
        owner = below_owners.get(cell) if below_owners else None
        return below_components.get(owner) if (below_components and owner is not None) else None

    def is_border(cell):
        own = _below_cid(cell)
        x, z = cell
        for nb in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
            cid = _below_cid(nb)
            if cid is not None and cid != own:
                return True
        return False

    if border_first and below_components:
        target = sorted(cellset, key=lambda c: (0 if typed[c] != SOLID_CHAR else 1,
                                                0 if is_border(c) else 1,
                                                c[0] if primary_axis == "x" else c[1],
                                                c[1] if primary_axis == "x" else c[0]))
    elif primary_axis == "x":
        target = sorted(cellset, key=lambda c: (0 if typed[c] != SOLID_CHAR else 1, c[0], c[1]))
    else:
        target = sorted(cellset, key=lambda c: (0 if typed[c] != SOLID_CHAR else 1, c[1], c[0]))
    n = len(target)

    def leaves_singleton(cset, occupied):
        """判断放置 cset 后是否将紧邻的某个未覆盖格切成了无同层邻居的 1x1 孤立碎格。"""
        for (cx, cz) in cset:
            for nx, nz in ((cx + 1, cz), (cx - 1, cz), (cx, cz + 1), (cx, cz - 1)):
                nb = (nx, nz)
                if nb in cset or nb in occupied or typed.get(nb) != SOLID_CHAR:
                    continue
                if not any((nx + dx, nz + dz) not in cset
                           and (nx + dx, nz + dz) not in occupied
                           and typed.get((nx + dx, nz + dz)) == SOLID_CHAR
                           for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    return 1
        return 0

    def order_key(merge, cs, rot, part, occupied):
        cset = set(cs)
        cross, coplanar = seam_stats(cs, cset)
        w, d = (part["d"], part["w"]) if rot else (part["w"], part["d"])
        long_axis = "x" if w > d else ("z" if d > w else None)
        aligned = 0 if (long_axis is None or long_axis == primary_axis) else 1
        return (-merge, -cross, 1 if coplanar else 0, leaves_singleton(cset, occupied), -(w * d), aligned)

    def _exposed_color(cells):
        if not cell_color:
            return set()
        return {cell_color.get(c) for c in cells if cell_color.get(c)}

    def _slope_candidates(x, z, ch, res, occupied):
        for part in _slope_parts_for(ch, target_color, allow_fallback, slope_cache):
            w, d = part["w"], part["d"]
            for i in range(w):
                for j in range(d):
                    px, pz = x - i, z - j
                    cs = [(px + a, pz + b) for a in range(w) for b in range(d)]
                    if any(c in occupied for c in cs) or not _slope_cells_match(part, px, pz, cs, typed, ch):
                        continue
                    if part.get("rootMask"):
                        roots = root_cells(part, px, pz, False) or []
                        tips = [c for c in cs if c not in roots]
                        if below is not None and not any(c in below or c in hang_ok for c in roots):
                            continue
                        if below is not None and any(c in below for c in tips):
                            continue
                    elif below is not None and not any(c in below or c in hang_ok for c in cs):
                        continue
                    if cell_color:
                        exposed = _exposed_color(cs)
                        if len(exposed) > 1:
                            continue
                        color_here = next(iter(exposed)) if exposed else (default_color or target_color)
                        p = part_for(part["shape"], color_here) if color_here else part
                        if p is None or inventory[p["id"]] <= 0:
                            continue
                        res.append((p, False, px, pz, cs))
                    elif inventory[part["id"]] > 0:
                        res.append((part, False, px, pz, cs))

    def _rank(res, occupied):
        ranked = []
        for part, rot, px, pz, cs in res:
            m = merge_score(cs)
            k = order_key(m, cs, rot, part, occupied)
            ranked.append((k, rng.random(), color_rank.get(part["id"], 10 ** 6),
                           part, rot, px, pz, cs, m))
        if merge_first is False:
            ranked.sort(key=lambda t: (t[0][4], -t[8], t[2], t[1]))
        else:
            ranked.sort(key=lambda t: (t[0], t[1], t[2]))
        return [(p, r, xx, zz, c) for _, _, _, p, r, xx, zz, c, _m in ranked]

    def try_once():
        occupied = set()
        out = []
        budget = [max_backtrack]

        def supported(cs):
            return below is None or any(c in below or c in hang_ok for c in cs)

        def cands(x, z):
            if should_stop is not None and should_stop():
                raise TilerCancelled()
            res = []
            ch = typed[(x, z)]
            if ch in ALL_SLOPE_CHARS:
                _slope_candidates(x, z, ch, res, occupied)
                return _rank(res, occupied)
            if cell_color:
                for shape_id in RECT_SHAPES:
                    shape = PART_MAP[shape_id]
                    for rot in (False, True):
                        w, d = (shape["d"], shape["w"]) if rot else (shape["w"], shape["d"])
                        cs = [(x + i, z + j) for i in range(w) for j in range(d)]
                        if not all(typed.get(c) == "#" and c not in occupied for c in cs):
                            continue
                        if not supported(cs):
                            continue
                        exposed = _exposed_color(cs)
                        if len(exposed) > 1:
                            continue
                        color_here = next(iter(exposed)) if exposed else default_color
                        part = part_for(shape_id, color_here) if color_here else None
                        if part is not None and inventory[part["id"]] > 0:
                            res.append((part, rot, x, z, cs))
            else:
                for part in rect_parts:
                    if inventory[part["id"]] <= 0:
                        continue
                    for rot in (False, True):
                        w, d = (part["d"], part["w"]) if rot else (part["w"], part["d"])
                        cs = [(x + i, z + j) for i in range(w) for j in range(d)]
                        if all(typed.get(c) == "#" and c not in occupied for c in cs) and supported(cs):
                            res.append((part, rot, x, z, cs))
            return _rank(res, occupied)

        def backtrack(idx):
            if budget[0] <= 0:
                return False
            if deadline is not None and time.monotonic() >= deadline:
                budget[0] = 0
                return False
            while idx < n and target[idx] in occupied:
                idx += 1
            if idx == n:
                return True
            x, z = target[idx]
            for part, rot, px, pz, cs in cands(x, z):
                budget[0] -= 1
                inventory[part["id"]] -= 1
                occupied.update(cs)
                out.append((part["id"], rot, px, pz))
                if backtrack(idx):
                    return True
                out.pop()
                occupied.difference_update(cs)
                inventory[part["id"]] += 1
            return False

        return out if backtrack(0) else None

    for _ in range(restarts):
        if should_stop is not None and should_stop():
            raise TilerCancelled()
        if deadline is not None and time.monotonic() >= deadline:
            break
        res = try_once()
        if res is not None:
            return res
    return None


def solve_layer_exact(typed, below, inventory, target_color=None, allow_fallback=False,
                      cell_color=None, node_limit=300_000, deadline=None,
                      below_owners=None, below_components=None, should_stop=None,
                      hang_ok=None, default_color=None):
    """用 MRV 精确覆盖铺单层，带库存剪枝、正反斜坡约束与跨缝合并优先排序。"""
    if not typed:
        return []
    hang_ok = hang_ok or set()
    cells = frozenset(typed)
    c_order = color_order(target_color, allow_fallback)

    def _merge(cs):
        if not below_owners or not below_components:
            return 0
        comps = {below_components.get(below_owners.get(c)) for c in cs}
        comps.discard(None)
        return len(comps)

    def _supported(cs):
        return below is None or any(c in below or c in hang_ok for c in cs)

    cands_by_cell = {c: [] for c in cells}
    seen = set()

    def _add_candidate(cs, part, rot, x0, z0):
        key = (cs, part["id"])
        if key in seen:
            return
        seen.add(key)
        item = (cs, part["id"], rot, x0, z0, _merge(cs), len(cs))
        for c in cs:
            cands_by_cell[c].append(item)

    for (x0, z0) in cells:
        ch = typed[(x0, z0)]
        if ch in ALL_SLOPE_CHARS:
            by_color = SLOPE_PARTS_BY_CHAR.get(ch) or {}
            for plist in by_color.values():
                for part in plist:
                    w, d = part["w"], part["d"]
                    for i in range(w):
                        for j in range(d):
                            px, pz = x0 - i, z0 - j
                            cs = frozenset((px + a, pz + b) for a in range(w) for b in range(d))
                            if not cs <= cells or not _slope_cells_match(part, px, pz, cs, typed, ch):
                                continue
                            if part.get("rootMask"):
                                roots = set(root_cells(part, px, pz, False) or [])
                                tips = cs - roots
                                if below is not None:
                                    if not any(c in below or c in hang_ok for c in roots):
                                        continue
                                    if any(c in below for c in tips):
                                        continue
                            elif not _supported(cs):
                                continue
                            colors = ({cell_color.get(c) for c in cs if cell_color.get(c)}
                                      if cell_color else c_order)
                            if cell_color and len(colors) > 1:
                                continue
                            colors = sorted(colors) if cell_color else list(c_order)
                            if cell_color and not colors:
                                colors = [default_color] if default_color else []
                            for color in colors:
                                p = part_for(part["shape"], color) if color else part
                                if p is not None:
                                    _add_candidate(cs, p, False, px, pz)
            continue
        for shape_id in RECT_SHAPES:
            shape = PART_MAP[shape_id]
            for rot in (False, True):
                w, d = (shape["d"], shape["w"]) if rot else (shape["w"], shape["d"])
                cs = frozenset((x0 + i, z0 + j) for i in range(w) for j in range(d))
                if not cs <= cells or not all(typed[c] == "#" for c in cs) or not _supported(cs):
                    continue
                if cell_color:
                    colors = {cell_color.get(c) for c in cs if cell_color.get(c)}
                    if len(colors) > 1:
                        continue
                    colors = sorted(colors) or ([default_color] if default_color else [])
                else:
                    colors = c_order
                for color in colors:
                    part = part_for(shape_id, color) if color else PART_MAP[shape_id]
                    if part is not None:
                        _add_candidate(cs, part, rot, x0, z0)

    for c in cands_by_cell:
        cands_by_cell[c].sort(key=lambda t: (-t[5], -t[6]))

    inv = dict(inventory)
    out = []
    nodes = [0]

    def _rec(remaining):
        nodes[0] += 1
        if nodes[0] > node_limit:
            raise TimeoutError
        if should_stop is not None and nodes[0] % 512 == 0 and should_stop():
            raise TilerCancelled()
        if deadline is not None and nodes[0] % 512 == 0 and time.monotonic() > deadline:
            raise TimeoutError
        if not remaining:
            return True
        # 动态 MRV + 死格即时零分支剪枝：挑选当前剩余格集中合法候选最少的格子
        best_cands = None
        for c in remaining:
            valid = [it for it in cands_by_cell[c]
                     if it[0] <= remaining and inv.get(it[1], 0) > 0]
            if not valid:
                return False
            if best_cands is None or len(valid) < len(best_cands):
                best_cands = valid
                if len(best_cands) == 1:
                    break
        for (cs, pid, rot, px, pz, _m, _area) in best_cands:
            inv[pid] -= 1
            out.append((pid, rot, px, pz))
            if _rec(remaining - cs):
                return True
            out.pop()
            inv[pid] += 1
        return False

    try:
        return list(out) if _rec(cells) else None
    except TimeoutError:
        return None
