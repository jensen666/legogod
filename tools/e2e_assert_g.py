# -*- coding: utf-8 -*-
"""G01–G10 新增确认集的「结果正确性」专项断言（tools/e2e_cases_g.py 的检查器实现）。

用法：
    python -m tools.e2e_assert_g <run_id>                 # 按运行记录 desc 自动匹配 G 案例
    python -m tools.e2e_assert_g <run_id> --case G01
    python -m tools.e2e_assert_g <run_id> --json out.json

口径：
  - 通用硬底线：任务成功、门禁未降级、统一校验全绿、最终版本产物齐全、最终门禁重放
    （record["finalGateReplay"]，新版记录才有；旧记录缺字段时兼容跳过）；
  - 需求达标档（硬失败）：require_parts 部位存在且未删空、10.2 表专项几何断言、
    部位数/立体部位数下限、目标块数统一容差 bricks/目标 >= 0.5（±50%，对应 12.4 中位 ≥50%）；
  - 当前能力回归档（只记录不判失败）：体素、层数、颜色数、斜面体素、算子数与
    case.min_voxels/min_ops 设计参考下限的比较（10.1 不设强制算子数量、复杂度不是堆体素）；
  - 检查器一律 fn(ctx, *args) -> list[str]，不抛异常；错误给中文可读原因；参数全部来自
    case.checks，不按案例名写生产特判。名称匹配只作为定位手段，几何断言以
    model（layers/rows/colorRows、parts boxes）与 solution（steps/subassemblies/validation）
    的真实数据为准。
"""
import collections
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.e2e_assert import (  # noqa: E402
    _colored_cells, _part_cells_from_boxes, assert_generic, draw_request_count, load_run,
    review_with_source,
)
from tools.e2e_assert_20 import (  # noqa: E402
    _CHECKS as _GENERIC_CHECKS, _ground_envelope, _part_counts, _require_parts, _slope_count,
)
from tools.e2e_cases_g import G_TARGET_TOLERANCE, find_g_case  # noqa: E402

# 专项检查注册表：名字 -> fn(ctx, *args) -> list[str]；通用检查直接复用 20 例实现
G_CHECKS = {}
_GENERIC_REUSE = (
    "layers_min", "tiered_min", "part_span_min", "both_sides", "colors_distinct_min",
    "part_box_count_min", "ground_components_min", "part_overhang_min", "surface_parts_min",
    "color_ratio_min", "enclosed_interior_min", "parts_min",
)
for _name in _GENERIC_REUSE:
    if _name in _GENERIC_CHECKS:
        G_CHECKS[_name] = _GENERIC_CHECKS[_name]


def _check(name):
    def deco(fn):
        G_CHECKS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------- 通用几何工具
def _parts(model):
    return model.get("parts") or []


def _cells_of_part(part):
    return _part_cells_from_boxes(part)


def _part_cells(model, patterns):
    """按部位 id/name 关键词取部位及其实体格（与 e2e_assert_20 同口径）。"""
    hits = [p for p in _parts(model)
            if any(k in str(p.get("id", "")).lower() or k in str(p.get("name", ""))
                   for k in patterns)]
    cells = set()
    for p in hits:
        cells |= _cells_of_part(p)
    return hits, cells


def _solid_cells(model):
    """模型全部实体格 {(x,y,z)}；layers.cells 缺失时从 rows 兜底重建。"""
    out = set()
    for L in model.get("layers") or []:
        y = int(L.get("y"))
        if L.get("cells"):
            for c in L["cells"]:
                out.add((int(c[0]), y, int(c[1])))
        else:
            for z, row in enumerate(L.get("rows") or []):
                for x, ch in enumerate(row):
                    if ch != ".":
                        out.add((x, y, z))
    return out


def _char_map(model):
    """{y: {(x,z): ch}} 逐层字符，用于判断斜面/斜坡；仅在需要时构建。"""
    out = {}
    for L in model.get("layers") or []:
        chars = {}
        for z, row in enumerate(L.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    chars[(int(x), z)] = ch
        out[int(L.get("y"))] = chars
    return out


def _bbox(cells):
    if not cells:
        return None
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    zs = [c[2] for c in cells]
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def _span(cells, axis):
    if not cells:
        return 0
    vals = [c[axis] for c in cells]
    return max(vals) - min(vals) + 1


def _xz_components(cells):
    """把 {(x,y,z)} 投影到 xz 平面做 4-连通分组，返回 [set((x,z))]。"""
    todo = {(x, z) for (x, _y, z) in cells}
    comps = []
    while todo:
        start = todo.pop()
        comp = {start}
        stack = [start]
        while stack:
            x, z = stack.pop()
            for nb in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
                if nb in todo:
                    todo.remove(nb)
                    comp.add(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def _components_3d(cells):
    """{(x,y,z)} 6-连通分组，返回 [set]。"""
    todo = set(cells)
    comps = []
    while todo:
        start = todo.pop()
        comp = {start}
        stack = [start]
        while stack:
            x, y, z = stack.pop()
            for nb in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                       (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)):
                if nb in todo:
                    todo.remove(nb)
                    comp.add(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def _adjacent(a, b, radius=1):
    """两组 3D 格是否在切比雪夫距离 radius 内接触（面/棱/角接触都算）。"""
    if not a or not b:
        return False
    if len(a) > len(b):
        a, b = b, a
    for (x, y, z) in a:
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if (x + dx, y + dy, z + dz) in b:
                        return True
    return False


def _centroid(cells):
    n = len(cells)
    return (sum(c[0] for c in cells) / n, sum(c[1] for c in cells) / n,
            sum(c[2] for c in cells) / n)


def _enclosed_empty_area(mask, w, h):
    """二维 mask（占用格）内部被围合的空格数量：从边界 flood fill 空格的补集。"""
    empty = {(x, y) for x in range(w) for y in range(h)} - mask
    outside = set()
    stack = [c for c in empty if c[0] in (0, w - 1) or c[1] in (0, h - 1)]
    outside.update(stack)
    while stack:
        x, y = stack.pop()
        for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nb in empty and nb not in outside:
                outside.add(nb)
                stack.append(nb)
    return len(empty - outside)


def _slope_cells(cells, char_map):
    """给定 3D 格中属于斜坡/斜面字符的格数。"""
    return sum(1 for (x, y, z) in cells
               if (char_map.get(y) or {}).get((x, z), "#") not in ("#",))

def _dominant_color(model, cells):
    """给定实体格中最常见的颜色字符；无逐体素颜色返回 None。"""
    colored = _colored_cells(model)
    counts = {}
    for c in cells:
        ch = colored.get(c)
        if ch:
            counts[ch] = counts.get(ch, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _exposed_cells(solid, cells):
    """没有被上方实体压住的格（外露表面）。"""
    return {c for c in cells if (c[0], c[1] + 1, c[2]) not in solid}


def _rebuild_parts_records(solution):
    """按 validate_solution 的同一口径从 solution.steps 重建悬吊物理输入。

    返回 (parts, adj)：parts[i] = {layer, piece, rot, x, z, cells(二维), parents}，
    adj 只含竖直凸点承托边（与 legogod.validate 完全一致），供 legogod.suspension 复用。
    """
    from legogod.geometry import root_cells, step_cells, stud_cells
    from legogod.parts_library import PART_MAP

    steps = solution.get("steps") or []
    if not steps:
        return None, None
    occ, cells_list = {}, []
    for i, step in enumerate(steps):
        cs = step_cells(step)
        if not cs:
            return None, None
        cells_list.append(cs)
        y = step.get("layer")
        for (x, z) in cs:
            occ.setdefault((x, y, z), i)
    parts = []
    adj = {i: set() for i in range(len(steps))}
    for i, step in enumerate(steps):
        y = step.get("layer") or 0
        parents = set()
        part = PART_MAP.get(step.get("piece"))
        if y > 0 and part is not None:
            roots = root_cells(part, step.get("x", 0), step.get("z", 0), bool(step.get("rotate")))
            recess = set(roots) if roots is not None else set(cells_list[i])
            for (x, z) in cells_list[i]:
                pidx = occ.get((x, y - 1, z))
                if pidx is None:
                    continue
                pstep = steps[pidx]
                ppart = PART_MAP.get(pstep.get("piece"))
                if ppart is None:
                    continue
                studs = set(stud_cells(ppart, pstep.get("x", 0), pstep.get("z", 0),
                                       bool(pstep.get("rotate"))))
                if (x, z) in recess and (x, z) in studs:
                    parents.add(pidx)
        parts.append({"layer": y, "piece": step.get("piece"), "rot": bool(step.get("rotate")),
                      "x": step.get("x", 0), "z": step.get("z", 0),
                      "cells": list(cells_list[i]), "parents": parents})
        for p in parents:
            adj[i].add(p)
            adj[p].add(i)
    return parts, adj


# ---------------------------------------------------------------- 墙体负空间工具
WALL_DIRS = 72  # 绕墙中心的角向分箱数（5°/箱）


def _wall_coverage(cells):
    """把墙体格按绕墙质心的角度覆盖到 (层, 角向箱) 上。

    返回 (covered: {y: set(bin)}, y_lo, y_hi, bins)；用格的角向半宽近似覆盖，
    半径越小半宽越大，保证 1 格厚的连续墙体在角向不漏缝（避免把离散化误判成缺口）。
    """
    if not cells:
        return {}, 0, 0, 0
    cx = sum(c[0] for c in cells) / len(cells) + 0.5
    cz = sum(c[2] for c in cells) / len(cells) + 0.5
    y_lo = min(c[1] for c in cells)
    y_hi = max(c[1] for c in cells)
    covered = {}
    for (x, y, z) in cells:
        r = math.hypot(x + 0.5 - cx, z + 0.5 - cz)
        half = math.atan2(0.75, max(r, 0.6)) / (2 * math.pi)
        center = (math.atan2(z + 0.5 - cz, x + 0.5 - cx) / (2 * math.pi)) % 1.0
        bins = set()
        for frac in (center - half, center + half, center):
            bins.add(int(frac * WALL_DIRS) % WALL_DIRS)
        # 半宽可能跨多个箱：补齐区间内所有箱
        lo = int((center - half) * WALL_DIRS)
        hi = int((center + half) * WALL_DIRS)
        for b in range(lo, hi + 1):
            bins.add(b % WALL_DIRS)
        covered.setdefault(y, set()).update(bins)
    return covered, y_lo, y_hi, WALL_DIRS


def _arch_hole_count(cells):
    """在墙体角向覆盖矩阵上数「真实贯通拱洞」：某角度某段高度没有墙体、上方有拱顶。"""
    covered, y_lo, y_hi, n = _wall_coverage(cells)
    if not covered:
        return 0, 0
    ys = list(range(y_lo, y_hi + 1))
    runs = []  # (bin, y_start, y_end, covered_above, covered_below)
    for b in range(n):
        open_y = [y for y in ys if b not in covered.get(y, ())]
        i = 0
        while i < len(open_y):
            j = i
            while j + 1 < len(open_y) and open_y[j + 1] == open_y[j] + 1:
                j += 1
            y0, y1 = open_y[i], open_y[j]
            above = any(b in covered.get(y, ()) for y in (y1 + 1, y1 + 2) if y <= y_hi)
            below = any(b in covered.get(y, ()) for y in (y0 - 1, y0 - 2) if y >= y_lo)
            runs.append((b, y0, y1, above, below))
            i = j + 1
    # 仅保留有拱顶（上侧有墙体）的竖直缺口：全高缺口属于残墙，不是拱洞
    arch_runs = [r for r in runs if r[3] and (r[1] == y_lo or r[4])]
    # 相邻角向箱、竖直范围重叠的缺口属于同一个拱洞
    parent = list(range(len(arch_runs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i, (b1, s1, e1, _a, _b) in enumerate(arch_runs):
        for j in range(i + 1, len(arch_runs)):
            b2, s2, e2, _a2, _b2 = arch_runs[j]
            gap = min(abs(b1 - b2), n - abs(b1 - b2))
            if gap <= 1 and not (e1 < s2 - 1 or e2 < s1 - 1):
                union(i, j)
    groups = {find(i) for i in range(len(arch_runs))}
    ruined = 0
    never = [b for b in range(n) if not any(b in cov for cov in covered.values())]
    if never and len(never) < n:
        runs_bins, i = [], 0
        flags = [b in never for b in range(n)] * 2
        while i < n:
            if not flags[i]:
                i += 1
                continue
            j = i
            while j < n and flags[j]:
                j += 1
            if j - i >= 2:
                runs_bins.append((i, j - i))
            i = j
        ruined = len(runs_bins)
    return len(groups), ruined


# ================================================================ G01 罗马斗兽场
@_check("g_ellipse_ring")
def _c_ellipse_ring(ctx, patterns):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not cells:
        return [f"未找到外墙部位 {patterns} 的几何体素（无法验证椭圆环形轮廓）"]
    x0, x1, _y0, _y1, z0, z1 = _bbox(cells)
    w, d = x1 - x0 + 1, z1 - z0 + 1
    errors = []
    ratio = max(w, d) / max(1, min(w, d))
    if not (1.15 <= ratio <= 2.6):
        errors.append(f"椭圆环形轮廓未成型：平面长宽比 {ratio:.2f} 不在 1.15~2.6（轮廓不是椭圆）")
    layers = {}
    for (x, y, z) in cells:
        layers.setdefault(y, set()).add((x, z))
    # 角向连续性：至少一层外墙覆盖 ≥85% 角向区段（允许一处残墙缺口）
    cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
    best = 0
    for plane in layers.values():
        bins = set()
        for (x, z) in plane:
            theta = math.atan2(z + 0.5 - cz, x + 0.5 - cx) % (2 * math.pi)
            bins.add(int(theta / (2 * math.pi) * 36) % 36)
        best = max(best, len(bins))
    if best < int(36 * 0.85):
        errors.append(f"椭圆环形轮廓未成型：外墙只覆盖 {best}/36 个角向区段"
                      "（不足 85%，没有形成连续的椭圆环）")
    center = ((x0 + x1) // 2, (z0 + z1) // 2)
    empty_layers = sum(1 for plane in layers.values() if center not in plane)
    if empty_layers < 2:
        errors.append(f"椭圆环形轮廓未成型：外墙中心在 {len(layers) - empty_layers} 层被填实"
                      "（没有环形中空，内部座位/场地无法成立）")
    corners = [(x0, z0), (x0, z1), (x1, z0), (x1, z1)]
    corner_hits = sum(1 for c in corners if any(c in plane for plane in layers.values()))
    if corner_hits >= 3:
        errors.append("椭圆环形轮廓未成型：平面四角都被外墙填满（矩形轮廓，未做出椭圆收角）")
    return errors


@_check("g_arch_holes_min")
def _c_arch_holes_min(ctx, n):
    model = ctx["model"]
    _hits, cells = _part_cells(model, ("外墙", "墙", "wall"))
    if not cells:
        return ["未找到外墙几何（无法验证贯通拱洞）"]
    arches, _ruined = _arch_hole_count(cells)
    if arches < n:
        return [f"真实贯通拱洞仅 {arches} 个 < {n}（拱洞必须是可穿透的负空间且上方有拱顶；"
                "实心墙或表面涂黑不算）"]
    return []


@_check("g_ruined_gap")
def _c_ruined_gap(ctx):
    model = ctx["model"]
    _hits, cells = _part_cells(model, ("外墙", "墙", "wall"))
    if not cells:
        return ["未找到外墙几何（无法验证残墙缺口）"]
    _arches, ruined = _arch_hole_count(cells)
    if ruined <= 0:
        return ["未发现真实残墙缺口（外墙各角度在各层都有实体，没有自底向上断开的一段）"]
    if ruined > 1:
        return [f"残墙缺口不唯一：发现 {ruined} 处全高断开 > 1（方案要求一处真实残墙缺口）"]
    return []


@_check("g_seating_arena")
def _c_seating_arena(ctx, patterns):
    model = ctx["model"]
    solid = _solid_cells(model)
    _wall_hits, wall_cells = _part_cells(model, ("外墙", "墙", "wall"))
    anchor = wall_cells or solid
    bbox = _bbox(anchor)
    if not bbox:
        return ["模型没有实体，无法验证环形座位与中央空地"]
    x0, x1, y0, y1, z0, z1 = bbox
    cx, cz = (x0 + x1) / 2.0, (z0 + z1) / 2.0
    r_out = max(math.hypot(x + 0.5 - cx, z + 0.5 - cz) for (x, _y, z) in anchor) or 1.0
    errors = []
    _hits, seat_cells = _part_cells(model, patterns)
    if not seat_cells:
        return [f"未找到环形座位部位 {patterns} 的真实几何（座位不得省略）"]
    radial = [math.hypot(x + 0.5 - cx, z + 0.5 - cz) for (x, _y, z) in seat_cells]
    inner_ok = sum(1 for r in radial if 0.15 * r_out <= r <= 0.9 * r_out)
    if inner_ok < max(6, len(radial) * 0.7):
        errors.append(f"环形座位未沿内圈成型：{len(radial) - inner_ok} 格座位落在墙体或场地中心"
                      f"（应在半径 15%~90% 的环带上）")
    bins = set()
    for (x, _y, z) in seat_cells:
        theta = math.atan2(z + 0.5 - cz, x + 0.5 - cx) % (2 * math.pi)
        bins.add(int(theta / (2 * math.pi) * 12) % 12)
    if len(bins) < 8:
        errors.append(f"环形座位未成环：只覆盖 {len(bins)}/12 个角向区段（需要 ≥8 段成环）")
    blocked = [(x, y, z) for (x, y, z) in solid
               if int(x) == int(cx) and int(z) == int(cz) and y0 + 1 <= y <= (y0 + y1) // 2]
    if blocked:
        errors.append(f"中央表演场地被占据：中心 {len(blocked)} 层有实体（中央应留空）")
    return errors


# ================================================================ G02 港口龙门吊
@_check("g_legs_separate_min")
def _c_legs_separate_min(ctx, patterns, n):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到腿部部位 {patterns}（分立足缺失）"]
    if not cells:
        return [f"腿部部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    comps = _xz_components(cells)
    grounded = {(x, z) for (x, y, z) in cells if y == 0}
    errors = []
    if len(comps) < n:
        errors.append(f"分立足不足：{len(comps)} < {n}（腿被合并/贴成整块，未真实分立）")
    ungrounded = [comp for comp in comps if not (comp & grounded)]
    if ungrounded:
        errors.append(f"{len(ungrounded)} 条腿没有落到 y=0 地面（腿部悬空或未对齐）")
    return errors


@_check("g_double_beam")
def _c_double_beam(ctx, patterns, min_boxes, min_span, min_overhang):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到主梁部位 {patterns}（双梁缺失）"]
    if not cells:
        return [f"主梁部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    errors = []
    boxes = sum(len(p.get("boxes") or []) for p in hits)
    if len(hits) < 2 and boxes < min_boxes:
        errors.append(f"双梁未成型：{len(hits)} 个主梁部位 / {boxes} 个独立几何块 < {min_boxes}")
    span = max(_span(cells, 0), _span(cells, 2))
    if span < min_span:
        errors.append(f"主梁长跨不足：最大跨度 {span} < {min_span}（龙门跨距不够）")
    env = _ground_envelope(model)
    if env is None:
        errors.append("y=0 底层为空，无法验证主梁悬挑")
    else:
        bx0, bx1 = min(c[0] for c in cells), max(c[0] for c in cells)
        bz0, bz1 = min(c[2] for c in cells), max(c[2] for c in cells)
        overhang = max(env[0] - bx0, bx1 - env[1], env[2] - bz0, bz1 - env[3])
        if overhang < min_overhang:
            errors.append(f"主梁没有真实悬挑：超出底层包络仅 {overhang} 格 < {min_overhang}"
                          "（一端必须外伸出支腿之外）")
    return errors


@_check("g_parts_contact")
def _c_parts_contact(ctx, patterns_a, patterns_b):
    model = ctx["model"]
    hits_a, cells_a = _part_cells(model, patterns_a)
    hits_b, cells_b = _part_cells(model, patterns_b)
    errors = []
    if not hits_a or not cells_a:
        errors.append(f"未找到部位 {patterns_a} 的真实几何（无法验证接触）")
    if not hits_b or not cells_b:
        errors.append(f"未找到部位 {patterns_b} 的真实几何（无法验证接触）")
    if errors:
        return errors
    if not _adjacent(cells_a, cells_b):
        errors.append(f"部位 {patterns_a} 与 {patterns_b} 未接触（存在悬空间隙，结构未连接）")
    return errors


def _suspension_state(model, solution, hook_cells):
    """优先用 solution.steps 重建悬吊物理状态并返回命中情况；无 steps 返回 None。"""
    from legogod import suspension

    parts, adj = _rebuild_parts_records(solution or {})
    if parts is None:
        return None
    steps = solution.get("steps") or []
    order = sorted(range(len(steps)), key=lambda i: steps[i].get("step") or i + 1)
    pos = {idx: p for p, idx in enumerate(order)}
    cell_step = {}
    for i, p in enumerate(parts):
        for (x, z) in p["cells"]:
            cell_step[(x, p["layer"], z)] = i
    hook_idx = {cell_step.get((x, y, z)) for (x, y, z) in hook_cells}
    hook_idx.discard(None)
    clusters, _grounded = suspension.find_hanging_clusters(parts, adj)
    matched = []
    for cluster in clusters:
        bricks = set(cluster["bricks"])
        hanging = set(cluster["hanging"])
        if not (hook_idx and (hook_idx & bricks)):
            continue
        locks = suspension.lock_cells(cluster["hanging"], parts, adj)
        errs = suspension.check_cluster(cluster, parts, adj)
        # 竖直插入路径卡口：触发前已就位的非子组件零件若位于子组件体素正上方即卡住
        jam = None
        trigger = max(pos[b] for b in bricks)
        cluster_cells = {(x, parts[b]["layer"], z) for b in bricks for (x, z) in parts[b]["cells"]}
        for bi in range(len(steps)):
            if bi in bricks or pos[bi] >= trigger:
                continue
            by = parts[bi]["layer"]
            for (x, z) in parts[bi]["cells"]:
                if any(x == cx and z == cz and by > cy for (cx, cy, cz) in cluster_cells):
                    jam = (x, by, z)
                    break
            if jam:
                break
        matched.append({"in_hanging": hook_idx <= hanging,
                        "locks": len(locks), "errors": errs, "jam": jam})
    return {"clusters": len(clusters), "matched": matched}


@_check("g_suspension_hanging")
def _c_suspension_hanging(ctx, hook_patterns, sling_patterns, min_lock):
    model, solution = ctx["model"], ctx["solution"] or {}
    hook_hits, hook_cells = _part_cells(model, hook_patterns)
    sling_hits, sling_cells = _part_cells(model, sling_patterns)
    errors = []
    if not hook_hits:
        errors.append(f"未找到吊钩部位 {hook_patterns}（不得用实心方块代替吊钩悬空）")
    if not sling_hits:
        errors.append(f"未找到吊索部位 {sling_patterns}（吊钩不能直接贴在主梁上）")
    if errors:
        return errors
    state = _suspension_state(model, solution, hook_cells)
    if state is not None:
        if not state["matched"]:
            errors.append("吊钩未形成合法悬吊子组件：solution 里没有任何吊挂簇包含吊钩"
                          "（吊钩贴梁、落座或与主梁刚性相连都不算悬吊）")
        else:
            best = max(state["matched"], key=lambda m: m["locks"])
            if not best["in_hanging"]:
                errors.append("吊钩只是上方跨接砖，没有落在吊挂侧（不是被吊着的吊钩）")
            if best["locks"] < min_lock:
                errors.append(f"吊挂子组件只有 {best['locks']} 个锁扣凸点 < {min_lock}"
                              "（物理下界：单凸点存在水平旋转自由度）")
            for e in best["errors"]:
                errors.append(f"悬吊物理校核未通过：{e}")
            if best["jam"]:
                errors.append(f"预拼子组件竖直插入路径被上方已就位零件阻挡（装配卡口）："
                              f"(x={best['jam'][0]}, y={best['jam'][1]}, z={best['jam'][2]})")
        return errors
    # ---- solution 缺失时的模型几何判据（按凸点承托语义近似）----
    solid = _solid_cells(model)
    supported = [c for c in hook_cells if (c[0], c[1] - 1, c[2]) in solid]
    if supported:
        errors.append(f"吊钩由下方实体支撑（{len(supported)} 格），未形成真实悬空吊挂"
                      "（用实心方块/贴梁代替吊钩）")
    if len(hook_cells) > 16:
        errors.append(f"吊钩体量 {len(hook_cells)} 格 > 16，疑似用实心大方块代替吊钩")
    if not _adjacent(hook_cells, sling_cells):
        errors.append("吊钩与吊索不接触（悬吊子组件未连成一体）")
    cluster_cells = hook_cells | sling_cells
    engaged = {(x, z) for (x, y, z) in cluster_cells
               if (x, y + 1, z) in solid and (x, y + 1, z) not in cluster_cells}
    if len(engaged) < min_lock:
        errors.append(f"吊挂子组件只有 {len(engaged)} 个锁扣凸点 < {min_lock}"
                      "（上方跨接砖的咬合点不足，悬吊不合法）")
    if sling_cells and hook_cells \
            and max(c[1] for c in sling_cells) <= max(c[1] for c in hook_cells):
        errors.append("吊索没有位于吊钩上方（不是竖直吊挂关系）")
    return errors


@_check("g_opposite_side")
def _c_opposite_side(ctx, patterns_a, patterns_b, min_offset):
    model = ctx["model"]
    hits_a, cells_a = _part_cells(model, patterns_a)
    hits_b, cells_b = _part_cells(model, patterns_b)
    errors = []
    if not hits_a or not cells_a:
        errors.append(f"未找到部位 {patterns_a} 的真实几何")
    if not hits_b or not cells_b:
        errors.append(f"未找到部位 {patterns_b} 的真实几何")
    if errors:
        return errors
    axis = 0 if _span(cells_b, 0) >= _span(cells_b, 2) else 2
    beam_c = _centroid(cells_b)[axis]
    cw_c = _centroid(cells_a)[axis]
    env = _ground_envelope(model)
    if env is None:
        return ["y=0 底层为空，无法判断主梁外伸方向与配重位置"]
    beam_lo = min(c[axis] for c in cells_b)
    beam_hi = max(c[axis] for c in cells_b)
    env_lo, env_hi = (env[0], env[1]) if axis == 0 else (env[2], env[3])
    overhang_dir = 1 if (beam_hi - env_hi) >= (env_lo - beam_lo) else -1
    offset = cw_c - beam_c
    if offset * overhang_dir >= 0:
        errors.append(f"配重未位于主梁另一侧：配重偏移 {offset:+.1f} 与外伸方向 {overhang_dir:+d} 同侧")
    elif abs(offset) < min_offset:
        errors.append(f"配重距主梁中心 {abs(offset):.1f} < {min_offset}（配重贴梁，未形成反向力矩）")
    return errors


@_check("g_ladder_rungs")
def _c_ladder_rungs(ctx, patterns, n):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到爬梯部位 {patterns}（爬梯缺失）"]
    if not cells:
        return [f"爬梯部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    by_y = {}
    for (x, y, z) in cells:
        by_y.setdefault(y, set()).add((x, z))
    rung_layers = set()
    for y, plane in by_y.items():
        longest = 0
        for axis in (0, 1):
            groups = {}
            for (x, z) in plane:
                groups.setdefault(z if axis == 0 else x, []).append(x if axis == 0 else z)
            for vals in groups.values():
                vals.sort()
                run = 1
                for a, b in zip(vals, vals[1:]):
                    run = run + 1 if b == a + 1 else 1
                    longest = max(longest, run)
        if longest >= 2:
            rung_layers.add(y)
    if len(rung_layers) < n:
        return [f"爬梯没有梯级：只有 {len(rung_layers)} 层存在横向连续梯级 < {n}"
                "（只有两侧立轨、中间空心不算爬梯）"]
    return []


# ================================================================ G03 落地竖琴
@_check("g_triangle_frame")
def _c_triangle_frame(ctx, patterns, max_fill):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到三角框架部位 {patterns}（框架缺失）"]
    if not cells:
        return [f"三角框架部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    spans = [_span(cells, 0), _span(cells, 1), _span(cells, 2)]
    plane_axes = sorted(range(3), key=lambda i: spans[i], reverse=True)[:2]
    a_vals = sorted({c[plane_axes[0]] for c in cells})
    b_vals = sorted({c[plane_axes[1]] for c in cells})
    mask = {(c[plane_axes[0]] - a_vals[0], c[plane_axes[1]] - b_vals[0]) for c in cells}
    w, h = len(a_vals), len(b_vals)
    errors = []
    if w < 3 or h < 3:
        return [f"三角框架尺寸过小（{w}×{h}），无法形成可辨识三角中空"]
    fill = len(mask) / float(w * h)
    enclosed = _enclosed_empty_area(mask, w, h)
    if fill > max_fill:
        errors.append(f"三角框架被填实：投影填充率 {fill:.2f} > {max_fill}（实心三角块不是框架）")
    if enclosed < 2:
        errors.append(f"三角框架没有可辨识中空区域（围合空格 {enclosed} < 2；框架未成环形）")
    return errors


@_check("g_strings_vertical_min")
def _c_strings_vertical_min(ctx, patterns, n):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到琴弦部位 {patterns}（竖琴必须有琴弦）"]
    if not cells:
        return [f"琴弦部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    columns = {}
    for (x, y, z) in cells:
        columns.setdefault((x, z), []).append(y)
    valid = 0
    for ys in columns.values():
        ys.sort()
        run = best = 1
        for a, b in zip(ys, ys[1:]):
            run = run + 1 if b == a + 1 else 1
            best = max(best, run)
        if best >= 3:
            valid += 1
    if valid < n:
        return [f"竖向琴弦不足：{valid} 根 < {n}（琴弦必须是每列 ≥3 层连续竖直细长结构；"
                "横向/散点色块不算）"]
    return []


@_check("g_curved_taper_body")
def _c_curved_taper_body(ctx, patterns):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（弧形/收分结构缺失）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    axis = 0 if _span(cells, 0) >= _span(cells, 2) else 2
    widths = {}
    for (x, y, z) in cells:
        widths.setdefault(y, set()).add(x if axis == 0 else z)
    ys = sorted(widths)
    if len(ys) < 2:
        return [f"部位 {patterns} 只有 1 层，无法形成弧形收分"]
    per_y = [len(widths[y]) for y in ys]
    errors = []
    if len(set(per_y)) < 2:
        errors.append(f"部位 {patterns} 各层宽度完全一致（{len(set(per_y))} 档），没有收分/弧形变化")
    third = max(1, len(per_y) // 3)
    bottom = sum(per_y[:third]) / float(third)
    top = sum(per_y[-third:]) / float(third)
    slope_n = _slope_cells(cells, _char_map(model))
    if (bottom - top) < 1 and slope_n < 2:
        errors.append(f"部位 {patterns} 没有弧形/收分几何：首尾平均宽度差 {bottom - top:.1f} < 1"
                      f"、斜面格 {slope_n} < 2（直筒件不算弧形琴柱）")
    return errors


@_check("g_grounded_min")
def _c_grounded_min(ctx, patterns):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到落地部位 {patterns}"]
    if not cells:
        return [f"落地部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    low = min(c[1] for c in cells)
    return [] if low == 0 else [f"部位 {patterns} 未落地：最低层 y={low} > 0（整体悬空）"]


# ================================================================ G04 蜻蜓
@_check("g_wings_four_paired")
def _c_wings_four_paired(ctx, patterns, min_per_side, min_area):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到翅膀部位 {patterns}（不得用涂装在身体上的色块代替翅膀）"]
    if not cells:
        return [f"翅膀部位 {patterns} 缺少几何体素数据（boxes 为空，涂装不算翅膀）"]
    comps = [c for c in _xz_components(cells) if len(c) >= min_area]
    if len(comps) < 2 * min_per_side:
        return [f"四片翅膀未真实成型：面积 ≥{min_area} 格的独立翅膀只有 {len(comps)} 片"
                f" < {2 * min_per_side}（涂装色块不算翅膀）"]
    mid = (int(model.get("grid", {}).get("w") or 0) - 1) / 2.0
    mids = [sum(x for x, _z in comp) / len(comp) for comp in comps]
    left = sum(1 for m in mids if m <= mid - 0.5)
    right = sum(1 for m in mids if m >= mid + 0.5)
    if left < min_per_side or right < min_per_side:
        return [f"翅膀未左右成对：左侧 {left} 片 / 右侧 {right} 片（各需 ≥{min_per_side}）"]
    return []


@_check("g_part_clusters_min")
def _c_part_clusters_min(ctx, patterns, n):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到部位 {patterns}"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    got = len(_xz_components(cells))
    return [] if got >= n else [f"部位 {patterns} 可分组独立块 {got} < {n}（成组细腿未分立）"]


@_check("g_part_ratio_diff")
def _c_part_ratio_diff(ctx, patterns_long, patterns_short, min_ratio):
    model = ctx["model"]
    hits_a, cells_a = _part_cells(model, patterns_long)
    hits_b, cells_b = _part_cells(model, patterns_short)
    errors = []
    if not hits_a or not cells_a:
        errors.append(f"未找到部位 {patterns_long} 的真实几何")
    if not hits_b or not cells_b:
        errors.append(f"未找到部位 {patterns_short} 的真实几何")
    if errors:
        return errors
    span_a = max(_span(cells_a, 0), _span(cells_a, 2))
    span_b = max(_span(cells_b, 0), _span(cells_b, 2))
    ratio = span_a / float(max(1, span_b))
    if ratio < min_ratio:
        errors.append(f"比例未区分：{patterns_long} 跨度 {span_a} 与 {patterns_short} 跨度 {span_b} "
                      f"比值 {ratio:.2f} < {min_ratio}（胸腹/大小比例差异未成型）")
    return errors


@_check("g_exposed_contrast_color")
def _c_exposed_contrast_color(ctx, patterns, min_cells, body_patterns=None, allow_slope=False):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（异色特征缺失）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空，无法验证外露异色）"]
    solid = _solid_cells(model)
    char_map = _char_map(model)
    sloped = _slope_cells(cells, char_map) if allow_slope else 0
    exposed = _exposed_cells(solid, cells)
    colored = _colored_cells(model)
    if not colored:
        return [] if sloped else [f"部位 {patterns} 没有逐体素配色（colorRows 为空，异色细节不可辨）"]
    body_cells = _solid_cells(model) if body_patterns is None else _part_cells(model, body_patterns)[1]
    body_dominant = _dominant_color(model, body_cells) if body_cells else None
    contrast = 0
    for c in exposed:
        ch = colored.get(c)
        if ch and body_dominant and ch != body_dominant:
            contrast += 1
    if contrast >= min_cells:
        return []
    if sloped:
        return []
    if body_dominant is None:
        return [f"部位 {patterns} 无法判定主体配色（缺少逐体素颜色），异色不可辨"]
    return [f"部位 {patterns} 外露异色细节不足：{contrast} 格 < {min_cells}"
            f"（或被埋进内部看不见；异色小色点必须外露）"]


# ================================================================ G05 双峰骆驼
@_check("g_twin_peaks")
def _c_twin_peaks(ctx, patterns, min_gap_layers, min_sep):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到驼峰部位 {patterns}（双峰缺失）"]
    if not cells:
        return [f"驼峰部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    axis = 0 if _span(cells, 0) >= _span(cells, 2) else 2
    raw = {}
    for (x, y, z) in cells:
        key = x if axis == 0 else z
        raw[key] = max(raw.get(key, -1), y)
    lo_key, hi_key = min(raw), max(raw)
    keys = list(range(lo_key, hi_key + 1))
    heights = [raw.get(k) for k in keys]
    known = [h for h in heights if h is not None]
    if len(known) < 2:
        return [f"驼峰沿纵向只有 {len(known)} 个截面，无法形成两个分开的峰"]
    if len(keys) < 2 * min_sep + 1:
        return [f"驼峰沿纵向总跨度只有 {len(keys)} 格，无法形成两个分开的峰"]
    i = max(range(len(heights)), key=lambda idx: heights[idx] if heights[idx] is not None else -1)
    candidates = [j for j in range(len(heights))
                  if abs(j - i) >= min_sep and heights[j] is not None]
    if not candidates:
        return [f"驼峰只在一个位置成型，无法形成两个分开的峰（需要相距 ≥{min_sep} 格）"]
    j = max(candidates, key=lambda idx: heights[idx])
    errors = []
    if heights[j] < heights[i] - 1:
        errors.append(f"只有一个驼峰：第二峰高度 {heights[j]} 明显低于主峰 {heights[i]}"
                      "（两个驼峰高度应接近）")
    lo, hi = min(i, j), max(i, j)
    between = heights[lo:hi + 1]
    if any(h is None for h in between):
        # 两峰之间没有驼峰实体 = 中间低凹到驼峰下方（身体顶面），低凹深度按峰高差判
        valley = min(min(c[1] for c in cells) - 1,
                     min(h for h in between if h is not None))
    else:
        valley = min(between)
    gap = min(heights[i], heights[j]) - valley
    if gap < min_gap_layers:
        errors.append(f"两个驼峰之间没有低凹：峰谷差 {gap} < {min_gap_layers} 层"
                      "（驼峰合并成一个大方块）")
    return errors


@_check("g_neck_raise")
def _c_neck_raise(ctx, patterns_neck, patterns_body, min_span, min_raise):
    model = ctx["model"]
    hits_n, neck = _part_cells(model, patterns_neck)
    hits_b, body = _part_cells(model, patterns_body)
    errors = []
    if not hits_n or not neck:
        errors.append(f"未找到长颈部位 {patterns_neck} 的真实几何")
    if not hits_b or not body:
        errors.append(f"未找到身体部位 {patterns_body} 的真实几何")
    if errors:
        return errors
    span = max(_span(neck, 0), _span(neck, 1), _span(neck, 2))
    if span < min_span:
        errors.append(f"长颈长度不足：最大跨度 {span} < {min_span}（长颈未真实成型）")
    body_top = max(c[1] for c in body)
    neck_top = max(c[1] for c in neck)
    if neck_top < body_top + min_raise:
        errors.append(f"长颈没有抬头：颈顶 y={neck_top} 未高出身体顶部 y={body_top} "
                      f"{min_raise} 层以上")
    return errors


# ================================================================ G06 土星展示模型
@_check("g_sphere_profile")
def _c_sphere_profile(ctx, patterns):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到球体部位 {patterns}（球形轮廓缺失）"]
    if not cells:
        return [f"球体部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    errors = []
    counts = {}
    for (_x, y, _z) in cells:
        counts[y] = counts.get(y, 0) + 1
    ys = sorted(counts)
    if len(ys) < 4:
        return [f"球形截面层数不足：{len(ys)} < 4（多截面球形轮廓未成型）"]
    vals = [counts[y] for y in ys]
    if len(set(vals)) < 3:
        errors.append(f"球形截面缺乏收放：只有 {len(set(vals))} 种截面尺寸（应逐层收分）")
    mid_idx = max(range(len(vals)), key=lambda i: vals[i])
    if not (0.15 * len(vals) <= mid_idx <= 0.85 * len(vals)):
        errors.append(f"球形轮廓最大截面在 y={ys[mid_idx]}（不在中段），球体不对称")
    if vals[0] >= vals[mid_idx] or vals[-1] >= vals[mid_idx]:
        errors.append(f"球形轮廓未收尖：首/末层截面 {vals[0]}/{vals[-1]} 未小于中段 {vals[mid_idx]}")
    w_span, d_span = _span(cells, 0), _span(cells, 2)
    ratio = max(w_span, d_span) / float(max(1, min(w_span, d_span)))
    if ratio > 1.4:
        errors.append(f"球形平面轮廓不圆：x/z 跨度比 {ratio:.2f} > 1.4")
    return errors


@_check("g_ring_geometry")
def _c_ring_geometry(ctx, patterns_ring, patterns_sphere):
    model = ctx["model"]
    hits_r, ring = _part_cells(model, patterns_ring)
    hits_s, sphere = _part_cells(model, patterns_sphere)
    mistakes = []
    if not hits_r or not ring:
        mistakes.append(f"未找到环带部位 {patterns_ring} 的真实几何")
    if not hits_s or not sphere:
        mistakes.append(f"未找到球体部位 {patterns_sphere} 的真实几何")
    if mistakes:
        return mistakes
    errors = []
    if len(_components_3d(ring)) != 1:
        errors.append(f"环带几何不连续：断开成 {len(_components_3d(ring))} 段（必须是一圈连续的宽环）")
    center = _centroid(ring)
    spans = [(_span(ring, 0), 0), (_span(ring, 2), 2), (_span(ring, 1), 1)]
    spans.sort(reverse=True)
    ax_a, ax_b = spans[0][1], spans[1][1]
    central = [c for c in ring
               if abs(c[ax_a] - center[ax_a]) <= 1.5 and abs(c[ax_b] - center[ax_b]) <= 1.5]
    if central:
        errors.append(f"环带中央未留空：中心 {len(central)} 格属于环带（实心圆盘/环缝被填满）")
    a_vals = sorted({c[ax_a] for c in ring})
    b_vals = sorted({c[ax_b] for c in ring})
    mask = {(c[ax_a] - a_vals[0], c[ax_b] - b_vals[0]) for c in ring}
    enclosed = _enclosed_empty_area(mask, len(a_vals), len(b_vals))
    if enclosed < 2:
        errors.append(f"环带中央未留空：投影围合空格 {enclosed} < 2（环缝被填实成圆盘）")
    sphere_diameter = max(_span(sphere, ax_a), _span(sphere, ax_b))
    radial = {}
    for c in ring:
        r = math.hypot(c[ax_a] - center[ax_a], c[ax_b] - center[ax_b])
        theta = math.atan2(c[ax_b] - center[ax_b], c[ax_a] - center[ax_a])
        bin_i = int((theta + math.pi) / (2 * math.pi) * 24) % 24
        lo, hi = radial.get(bin_i, (r, r))
        radial[bin_i] = (min(lo, r), max(hi, r))
    widths = sorted(hi - lo for (lo, hi) in radial.values())
    ring_width = widths[len(widths) // 2] if widths else 0
    if ring_width <= sphere_diameter:
        errors.append(f"环宽不足：环带径向宽度 {ring_width:.1f} <= 球体直径 {sphere_diameter}"
                      "（需求是「宽环」，环宽必须大于球体直径）")
    if len({c[1] for c in ring}) < 2:
        errors.append("环带没有倾角：环带完全平置在同一层（需求是倾斜的宽环）")
    min_dist = 99
    for (ax_, ay_, az_) in ring:
        for (bx_, by_, bz_) in sphere:
            d = max(abs(ax_ - bx_), abs(ay_ - by_), abs(az_ - bz_))
            min_dist = min(min_dist, d)
    if min_dist < 2:
        errors.append(f"环与球体没有空隙：最近格距 {min_dist} < 2（环缝被实体填满）")
    return errors


# ================================================================ G07 雪地摩托
@_check("g_skis_two_extend")
def _c_skis_two_extend(ctx, patterns_ski, patterns_body, min_overhang):
    model = ctx["model"]
    hits, skis = _part_cells(model, patterns_ski)
    if not hits:
        return [f"未找到滑雪板部位 {patterns_ski}（不得用两个固定车轮代替滑雪板）"]
    if not skis:
        return [f"滑雪板部位 {patterns_ski} 缺少几何体素数据（boxes 为空）"]
    errors = []
    comps = _xz_components(skis)
    if len(comps) < 2:
        errors.append(f"滑雪板未分开：只有 {len(comps)} 块滑雪板（需求是前部两块分开的滑雪板）")
    for comp in comps:
        if not any((x, 0, z) in skis for (x, z) in comp):
            errors.append("有滑雪板没有落地（最低层不在 y=0）")
            break
    _bh, body = _part_cells(model, patterns_body)
    if not body:
        errors.append(f"未找到车身部位 {patterns_body} 的真实几何（无法验证滑雪板前伸）")
        return errors
    axis = 0 if _span(body, 0) >= _span(body, 2) else 2
    body_lo = min(c[axis] for c in body)
    body_hi = max(c[axis] for c in body)
    ski_lo = min(c[axis] for c in skis)
    ski_hi = max(c[axis] for c in skis)
    overhang = max(body_lo - ski_lo, ski_hi - body_hi, 0)
    if overhang < min_overhang:
        errors.append(f"滑雪板没有超出车身前缘：超出 {overhang} 格 < {min_overhang}")
    return errors


@_check("g_track_long_distinct")
def _c_track_long_distinct(ctx, patterns_track, patterns_wheel, min_span):
    model = ctx["model"]
    hits_t, track = _part_cells(model, patterns_track)
    if not hits_t:
        return [f"未找到履带部位 {patterns_track}（后部宽履带缺失）"]
    if not track:
        return [f"履带部位 {patterns_track} 缺少几何体素数据（boxes 为空）"]
    errors = []
    span = max(_span(track, 0), _span(track, 2))
    if span < min_span:
        errors.append(f"履带长跨不足：最大跨度 {span} < {min_span}（后部履带未真实成型）")
    _wh, wheels = _part_cells(model, patterns_wheel)
    if wheels:
        if track & wheels:
            errors.append("履带与车轮共用同一批体素（未区分履带与车轮）")
        wheel_span = max(_span(wheels, 0), _span(wheels, 2))
        if span < wheel_span + 2:
            errors.append(f"履带与车轮未区分：履带跨度 {span} 未明显长于车轮跨度 {wheel_span}")
    return errors


# ================================================================ G08 老式手推独轮车
@_check("g_round_wheels")
def _c_round_wheels(ctx, patterns, min_count, max_count=None):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到车轮部位 {patterns}（圆形车轮缺失）"]
    if not cells:
        return [f"车轮部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    comps = _xz_components(cells)
    errors = []
    if len(comps) < min_count:
        errors.append(f"车轮数量不足：{len(comps)} < {min_count}")
    if max_count is not None and len(comps) > max_count:
        errors.append(f"车轮数量 {len(comps)} > {max_count}（需求只允许单个圆形车轮）")
    for comp in comps:
        sub = {c for c in cells if (c[0], c[2]) in comp}
        spans = sorted((_span(sub, 0), _span(sub, 1), _span(sub, 2)), reverse=True)
        if spans[1] <= 0 or spans[0] / float(spans[1]) > 1.5:
            errors.append(f"车轮截面不近似圆形：两个最大跨度 {spans[0]}/{spans[1]} 比 > 1.5")
            break
        axes = sorted(range(3), key=lambda i: _span(sub, i), reverse=True)[:2]
        a_vals = sorted({c[axes[0]] for c in sub})
        b_vals = sorted({c[axes[1]] for c in sub})
        mask = {(c[axes[0]] - a_vals[0], c[axes[1]] - b_vals[0]) for c in sub}
        w, h = len(a_vals), len(b_vals)
        corners = [(0, 0), (0, h - 1), (w - 1, 0), (w - 1, h - 1)]
        filled = sum(1 for c in corners if c in mask)
        fill = len(mask) / float(max(1, w * h))
        if filled >= 3 or fill > 0.92:
            errors.append(f"车轮截面不近似圆形：直径平面四角填了 {filled}/4、填充率 {fill:.2f}"
                          "（方形车轮/实心方块不算圆形车轮）")
            break
    return errors


@_check("g_paired_across_axis")
def _c_paired_across_axis(ctx, patterns, axis):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到成对部位 {patterns}"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    comps = _xz_components(cells)
    if len(comps) < 2:
        return [f"成对结构缺失：只有 {len(comps)} 个独立几何块（需要左右成对两根）"]
    if axis != "x":
        return [f"不支持的成对轴 {axis!r}（只支持 x）"]
    w = int((model.get("grid") or {}).get("w") or (max(c[0] for c in cells) + 1))
    mid = (w - 1) / 2.0
    left, right = [], []
    for comp in comps:
        xs = [x for x, _z in comp]
        if max(xs) < mid:
            left.append((min(xs), max(xs)))
        elif min(xs) > mid:
            right.append((min(xs), max(xs)))
    if not left or not right:
        return [f"部位 {patterns} 未左右成对：左侧 {len(left)} 个 / 右侧 {len(right)} 个"]
    l_lo, l_hi = min(v[0] for v in left), max(v[1] for v in left)
    r_lo, r_hi = min(v[0] for v in right), max(v[1] for v in right)
    diff = max(abs(l_lo - (w - 1 - r_hi)), abs(l_hi - (w - 1 - r_lo)))
    if diff > 1:
        return [f"部位 {patterns} 左右不对称：镜像位置差 {diff} > 1 格（把手未成对）"]
    return []


# ================================================================ G09 极简笔筒
@_check("g_cup_open_top")
def _c_cup_open_top(ctx, patterns):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到杯体部位 {patterns}（空心杯体缺失）"]
    if not cells:
        return [f"杯体部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    solid = _solid_cells(model)
    x0, x1, y0, y1, z0, z1 = _bbox(cells)
    cx, cz = (x0 + x1) // 2, (z0 + z1) // 2
    errors = []
    top = {c for c in cells if c[1] == y1}
    if (cx, y1, cz) in top:
        errors.append("杯体顶部封死：顶面中心被填实（「顶部封死但侧面有洞」不算顶部敞开）")
    for y in range(y0 + 1, y1):
        if (cx, y, cz) in solid:
            errors.append(f"顶部负空间不贯通：中心列 y={y} 被填实（内腔被封顶/填实）")
            break
    plane = {(c[0], c[2]) for c in cells if c[1] == (y0 + y1) // 2}
    sides = {"左侧": any((x, cz) in plane for x in range(x0, cx)),
             "右侧": any((x, cz) in plane for x in range(cx + 1, x1 + 1)),
             "前侧": any((cx, z) in plane for z in range(z0, cz)),
             "后侧": any((cx, z) in plane for z in range(cz + 1, z1 + 1))}
    missing = [k for k, v in sides.items() if not v]
    if missing:
        errors.append(f"杯壁不完整：中层{'、'.join(missing)}没有壁（四面围合才有厚杯壁）")
    return errors


@_check("g_cup_bottom_closed")
def _c_cup_bottom_closed(ctx, patterns):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到杯体部位 {patterns}"]
    if not cells:
        return [f"杯体部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    x0, x1, y0, _y1, z0, z1 = _bbox(cells)
    cx, cz = (x0 + x1) // 2, (z0 + z1) // 2
    bottom = {(c[0], c[2]) for c in cells if c[1] == y0}
    missing = [(x, z) for x in range(max(x0, cx - 1), min(x1, cx + 1) + 1)
               for z in range(max(z0, cz - 1), min(z1, cz + 1) + 1)
               if (x, z) not in bottom]
    if (cx, cz) not in bottom or missing:
        return [f"杯底未封闭：底层中心区域缺失 {len(missing) + ((cx, cz) not in bottom)} 格"
                "（底部必须封口，不能漏空）"]
    return []


@_check("g_cup_cavity_min")
def _c_cup_cavity_min(ctx, patterns, n):
    model = ctx["model"]
    hits, cells = _part_cells(model, patterns)
    if not hits:
        return [f"未找到杯体部位 {patterns}（内部空腔缺失）"]
    if not cells:
        return [f"杯体部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    solid = _solid_cells(model)
    x0, x1, y0, y1, z0, z1 = _bbox(cells)
    cavity = 0
    for y in range(y0 + 1, y1):
        for x in range(x0 + 1, x1):
            for z in range(z0 + 1, z1):
                if (x, y, z) not in solid:
                    cavity += 1
    if cavity < n:
        return [f"内部空腔被填实：内腔空格 {cavity} < {n}（笔筒必须是空心杯体）"]
    return []


_PEN_HOST_KEYWORDS = ("筒", "杯", "桶", "底座", "底", "座", "盘", "托", "架", "槽")


def _is_pen_host(name):
    """笔的宿主部位（笔筒/杯身/底座/托盘等）：名称含宿主关键词，不算作笔。"""
    return any(k in str(name or "") for k in _PEN_HOST_KEYWORDS)


def _pen_shape_ok(comp):
    """独立笔形：竖直细长（高度 ≥3 且高度大于水平最大跨度），排除整块/扁平补丁。"""
    ys = [c[1] for c in comp]
    xs = [c[0] for c in comp]
    zs = [c[2] for c in comp]
    height = max(ys) - min(ys) + 1
    width = max(xs) - min(xs) + 1
    depth = max(zs) - min(zs) + 1
    return height >= 3 and height > max(width, depth)


@_check("g_pens_three_distinct")
def _c_pens_three_distinct(ctx, patterns, min_count, min_heights):
    """三支笔：排除笔筒/杯身/底座等宿主部位，按独立笔形 + 颜色 + 高度计数。

    2026-11-03 复核修正：旧实现把名称含「笔」的宿主（如「笔筒底座」）也算作笔，笔插在
    筒里与筒底接触 → 所有命中格合并成一个 3D 连通块，误报「笔的数量不足 1 < 3」。
    现在先按宿主关键词排除，再对每个笔部位拆连通块、只保留竖直细长的笔形，按主导颜色与
    顶端高度去重计数；缺笔/同色/同高反例仍然必须失败。
    """
    model = ctx["model"]
    hits, _cells = _part_cells(model, patterns)
    pen_parts = [p for p in hits if not _is_pen_host(p.get("name"))]
    if not pen_parts:
        return [f"未找到独立笔部位 {patterns}（宿主部位不算笔，三支笔缺失）"]
    colored = _colored_cells(model)
    pens = []
    for part in pen_parts:
        for comp in _components_3d(_cells_of_part(part)):
            if not _pen_shape_ok(comp):
                continue
            counter = collections.Counter(colored[c] for c in comp if colored.get(c))
            pens.append({"part": part.get("name"), "cells": comp,
                         "color": counter.most_common(1)[0][0] if counter else None,
                         "top": max(c[1] for c in comp)})
    if len(pens) < min_count:
        return [f"笔的数量不足：{len(pens)} < {min_count}（需要三支可区分的笔；宿主部位已排除）"]
    errors = []
    colors = {p["color"] for p in pens if p["color"]}
    tops = {p["top"] for p in pens}
    if len(colors) < min_count:
        errors.append(f"三支笔颜色不可区分：只有 {len(colors)} 种颜色 < {min_count}")
    if len(tops) < min_heights:
        errors.append(f"三支笔高度不可区分：只有 {len(tops)} 种高度 < {min_heights}")
    return errors


@_check("g_not_solid_block")
def _c_not_solid_block(ctx, patterns, max_fill):
    model = ctx["model"]
    if patterns:
        hits, cells = _part_cells(model, patterns)
        label = f"部位 {patterns}"
    else:
        hits, cells = _parts(model), _solid_cells(model)
        label = "模型"
    if not hits:
        return [f"未找到{label}（无法验证是否被堆成实心方块）"]
    if not cells:
        return [f"{label}缺少几何体素数据（boxes 为空）"]
    x0, x1, y0, y1, z0, z1 = _bbox(cells)
    volume = (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)
    fill = len(cells) / float(max(1, volume))
    if fill > max_fill:
        return [f"{label}被堆成实心方块：包围盒填充率 {fill:.2f} > {max_fill}"
                "（为凑复杂度堆实心体，不是需求造型）"]
    return []


# ================================================================ G10 模糊需求小鸟
@_check("g_bird_geometry")
def _c_bird_geometry(ctx):
    """模糊需求小鸟的兜底特征：不能是无特征方块，且必须有落地部件。"""
    solid = _solid_cells(ctx["model"])
    if not solid:
        return ["模型没有实体（小鸟未生成）"]
    errors = []
    x0, x1, y0, y1, z0, z1 = _bbox(solid)
    volume = (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)
    fill = len(solid) / float(max(1, volume))
    if fill > 0.9:
        errors.append(f"小鸟生成为无特征方块：实心填充率 {fill:.2f} > 0.90")
    if not [c for c in solid if c[1] == 0]:
        errors.append("小鸟没有任何落地部件（y=0 为空）")
    return errors


# ================================================================ 断言入口
def _final_gate_replay_errors(record):
    """兼容读取新记录的最终门禁重放结果（record["finalGateReplay"]）。

    最终产物必须真实重放 part_gate.check_parts，不能只看过程 gateFailed。
    旧记录/其它执行器没有该字段时返回空（不误报，由通用门禁字段兜底）。
    """
    replay = record.get("finalGateReplay") or record.get("final_gate_replay")
    if not isinstance(replay, dict):
        return []
    if replay.get("ok") is False or replay.get("ok") == 0:
        errs = replay.get("errors") or replay.get("gateErrors") or []
        return [f"最终门禁重放未通过：{json.dumps(errs[:3], ensure_ascii=False)[:240]}"]
    return []


def check_objects_g(record, model, solution, case, review_fallback=None):
    """对 G 组单个案例执行通用底线 + 需求达标档 + 回归档，返回 (errors, metrics)。

    errors = 通用底线失败 + 需求达标档失败（任何一项即断言失败）；
    metrics["requirement_tier"] 只列需求达标档失败项；metrics["regression_tier"]
    只记录回归指标（体素/层数/颜色/算子等），不参与判定。
    review_fallback：旧 run 记录没有 review 时用任务 result.review 补入。
    """
    solution = solution or {}
    generic_errors = []
    assert_generic(record, model, solution, generic_errors)
    generic_errors.extend(_final_gate_replay_errors(record))

    ctx = {"model": model, "solution": solution,
           "counts": _part_counts(model), "colored": _colored_cells(model)}
    label = f"{case['id']} {case['name']}"
    requirement_errors = []
    bricks = len(solution.get("steps") or [])
    target = case.get("target_blocks")
    if record.get("ok"):
        _require_parts(model, requirement_errors, label, case.get("require_parts") or [])
        for spec in case.get("checks") or []:
            name, args = spec[0], spec[1:]
            fn = G_CHECKS.get(name)
            if fn is None:
                requirement_errors.append(f"断言配置错误：未知检查 {name}")
                continue
            try:
                requirement_errors.extend(fn(ctx, *args))
            except (KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError) as exc:
                requirement_errors.append(f"检查 {name} 执行失败：{exc}")
        total, solid_count, _surface = ctx["counts"]
        if total < int(case.get("min_parts") or 0):
            requirement_errors.append(
                f"复杂度未达设计下限：部位数 {total} < {case['min_parts']}")
        if solid_count < int(case.get("min_solid_parts") or 0):
            requirement_errors.append(
                f"复杂度未达设计下限：立体部位数 {solid_count} < {case['min_solid_parts']}")
        if target:
            ratio = bricks / float(target)
            if ratio < G_TARGET_TOLERANCE:
                requirement_errors.append(
                    f"目标块数未达标：实际零件 {bricks}/{target} = {ratio:.2%} < "
                    f"{G_TARGET_TOLERANCE:.0%}（方案 12.4 统一容差 ±50%）")
    errors = generic_errors + requirement_errors

    review, review_source = review_with_source(record, review_fallback)
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    attempts = record.get("drawAttempts") or []
    voxels = int(model.get("totalVoxels") or 0)
    ops = len(model.get("ops") or [])
    min_voxels = int(case.get("min_voxels") or 0)
    min_ops = int(case.get("min_ops") or 0)
    bricks_ratio = round(bricks / float(target), 4) if target else None
    metrics = {
        "case": case["id"], "name": case["name"], "run_id": record.get("runId"),
        "task_ok": bool(record.get("ok")), "error": record.get("error"),
        "mode": record.get("mode"), "track": model.get("track"),
        "target_blocks": target,
        "bricks": bricks,
        "bricks_ratio": bricks_ratio,
        "target_blocks_ok": (bricks_ratio is not None
                             and bricks_ratio >= G_TARGET_TOLERANCE),
        "parts": ctx["counts"][0], "solid_parts": ctx["counts"][1],
        "surface_parts": ctx["counts"][2],
        "voxels": voxels, "ops": ops,
        "slope_voxels": _slope_count(model),
        "layers": len(model.get("layers") or []),
        "grid": model.get("grid"),
        "pieces": bricks,
        "colors": len(set(ctx["colored"].values())),
        "gate_failed": bool(record.get("gateFailed") or record.get("gate_failed")),
        "gate_errors": record.get("gateErrors") or record.get("gate_errors") or [],
        "final_gate_replay": record.get("finalGateReplay") or record.get("final_gate_replay"),
        "validation_ok": solution.get("validation", {}).get("ok")
        if isinstance(solution.get("validation"), dict) else None,
        "review_overall": scores.get("overall"),
        "review_flag": record.get("reviewFlag"),
        "draw_attempts": len(attempts),
        "draw_requests": draw_request_count(attempts),
        "review": review,
        "review_source": review_source,
        "requirement_tier": requirement_errors,
        "generic_tier": generic_errors,
        "regression_tier": {
            "voxels": voxels,
            "voxels_per_target_block": round(voxels / float(target), 2) if target else None,
            "design_min_voxels": min_voxels,
            "voxels_below_design_floor": voxels < min_voxels if min_voxels else None,
            "ops": ops,
            "design_min_ops": min_ops,
            "ops_below_design_floor": ops < min_ops if min_ops else None,
            "layers": len(model.get("layers") or []),
            "colors": len(set(ctx["colored"].values())),
            "slope_voxels": _slope_count(model),
            "parts": ctx["counts"][0],
        },
        "assertion_errors": errors,
        "assertion_ok": not errors,
    }
    return errors, metrics


def check_run_g(run_id, case_id=None, review_fallback=None):
    """读取 run 记录与最终产物执行 G 组断言，返回 metrics dict。

    review_fallback：任务结果 result.review（旧 run 记录没有 review 时补入）。
    """
    record, model, solution = load_run(run_id)
    case = find_g_case(case_id, desc=record.get("desc"))
    if case is None:
        raise SystemExit(f"无法匹配 G 组案例：case_id={case_id!r} "
                         f"desc={str(record.get('desc'))[:60]!r}"
                         "（请显式给 --case，或确认需求原文与 tools/e2e_cases_g.py 一致）")
    _errors, metrics = check_objects_g(record, model, solution, case,
                                       review_fallback=review_fallback)
    metrics["desc"] = record.get("desc")
    return metrics


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out, case_id, positional = None, None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--case":
            i += 1
            case_id = argv[i] if i < len(argv) else None
        elif a == "--json":
            i += 1
            json_out = argv[i] if i < len(argv) else None
        else:
            positional.append(a)
        i += 1
    if len(positional) != 1:
        print("用法: python -m tools.e2e_assert_g <run_id> [--case G01] [--json out.json]")
        return 2
    metrics = check_run_g(positional[0], case_id)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"案例 {metrics['case']} {metrics['name']} · run {metrics['run_id']} · "
          f"{'✅ 断言通过' if metrics['assertion_ok'] else '❌ 断言未通过'}")
    print(f"  目标块数={metrics['target_blocks']} 实际零件={metrics['bricks']} "
          f"比值={metrics['bricks_ratio']} 达标={metrics['target_blocks_ok']}")
    print(f"  任务成功={metrics['task_ok']} 轨道={metrics['track']} 部位={metrics['parts']}"
          f"(立体{metrics['solid_parts']}/涂装{metrics['surface_parts']}) "
          f"体素={metrics['voxels']} 算子={metrics['ops']} 层={metrics['layers']} "
          f"颜色={metrics['colors']}")
    print(f"  门禁降级={metrics['gate_failed']} 统一校验={metrics['validation_ok']} "
          f"最终门禁重放={metrics['final_gate_replay']} 评审={metrics['review_overall']}")
    if metrics["assertion_errors"]:
        print("断言未通过项：")
        for e in metrics["assertion_errors"]:
            print(" -", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
