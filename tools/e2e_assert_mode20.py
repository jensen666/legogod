# -*- coding: utf-8 -*-
"""M01–M20 双模式恢复 E2E 的「结果正确性」专项断言（tools/e2e_cases_mode20.py 的检查器）。

用法：
    python -m tools.e2e_assert_mode20 <run_id>              # 按运行记录 desc 自动匹配 M 案例
    python -m tools.e2e_assert_mode20 <run_id> --case M01
    python -m tools.e2e_assert_mode20 <run_id> --json out.json

口径：
  1. 通用可信底线：直接调用 tools.e2e_assert_20.assert_generic（import 复用，不复制），
     并继承现有 C/H 断言器的评审过期判据；模型/方案版本与哈希由 load_run 强制一致。
  2. 需求正确性（requirement_tier，硬失败）：require_parts（部位存在且未删空）、逐例
     checks（覆盖「该例核心结果断言」的每个分句）、目标块数比 bricks/target >=
     TARGET_RATIO_MIN=0.5（复用 e2e_assert_20 冻结容差）；运行记录 desc 必须与冻结原文逐字一致。
  3. 模式事实（mode_facts，硬失败）：
       - fast：review 为空、reviewFlag 为空、counts.revise_visual == 0、无自动快速保底
         （outcome 不是 fast_fallback，且 attempts_detail 中无 fast 兜底尝试）；
       - fidelity：有真实评审结果，或如实标注评审不可用；自动快速保底尝试数 <= 1；
         且「高保真产物已交付（fidelity_success/fidelity_degraded）」时不得跑快速保底。
  4. 当前能力回归档（regression_tier，只记录不判失败）：体素/层数/颜色/斜面/部位等，
     结构参考 e2e_assert_20.check_objects 的 metrics，便于 tools/e2e_mode20_report.py 复用。

检查器注册表 M_CHECKS：名字 -> fn(ctx, *args) -> list[str]，不抛异常（入口兜底成可读失败）。
解析顺序 M_CHECKS -> tools.e2e_assert_g.G_CHECKS -> tools.e2e_assert_20._CHECKS：
G 组的落地/接触/成组/不成实心方块/外露异色/圆轮/拱洞等成熟原语与 C/H 组通用原语全部只读复用，
M 组只新增现有原语表达不了的几何原语（多孔贯通、垛口、坡屋顶、壳体、辐条、外张塔腿等）。
所有断言都基于最终 model（layers/rows/colorRows、parts boxes、totalVoxels/ops）与 solution
（steps/validation）真实计算，名称匹配只用于定位部位，不能只凭名称或 notes 判通过。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.e2e_assert import (  # noqa: E402
    _colored_cells, draw_request_count, final_gate_state, load_run, review_with_source,
)
from tools.e2e_assert_20 import (  # noqa: E402
    _CHECKS as GENERIC_CHECKS, SLOPE_CHARS, TARGET_RATIO_MIN, _part_cells_by_pattern,
    _part_counts, _require_parts, _slope_count, _solid, _span_on_axes, _target_blocks,
    assert_generic,
)
from tools.e2e_assert_g import G_CHECKS  # noqa: E402  成熟几何原语只读复用
from tools.e2e_cases_mode20 import case_hash, find_m_case  # noqa: E402

M_CHECKS = {}
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def _mcheck(name):
    def deco(fn):
        M_CHECKS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------- 通用几何/配色工具
def _cells(ctx, patterns):
    """按部位 id/名称关键词取命中部位与实体格（与 e2e_assert_20 同口径，只读复用）。"""
    return _part_cells_by_pattern(ctx["model"], patterns)


def _bbox(cells):
    """3D 包围盒 (x0, x1, y0, y1, z0, z1)；空集返回 None。"""
    if not cells:
        return None
    return (min(c[0] for c in cells), max(c[0] for c in cells),
            min(c[1] for c in cells), max(c[1] for c in cells),
            min(c[2] for c in cells), max(c[2] for c in cells))


def _span(cells, axis):
    """显式轴跨度；非法轴返回 None（axis 可写 x/y/z 的组合，如 "xz"、"y"）。"""
    if not cells:
        return 0
    text = str(axis or "").lower()
    if not text or any(ch not in _AXIS_INDEX for ch in text):
        return None
    return _span_on_axes(cells, text)


def _centroid(cells):
    """3D 质心；空集返回 None。"""
    if not cells:
        return None
    n = float(len(cells))
    return (sum(c[0] for c in cells) / n, sum(c[1] for c in cells) / n,
            sum(c[2] for c in cells) / n)


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
                    todo.discard(nb)
                    comp.add(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def _components_xz(cells):
    """投影到 xz 平面做 4-连通分组，返回 [set((x,z))]。"""
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
                    todo.discard(nb)
                    comp.add(nb)
                    stack.append(nb)
        comps.append(comp)
    return comps


def _sub_cells(cells, comp_xz):
    """取 xz 连通块对应的全部 3D 格。"""
    return {c for c in cells if (c[0], c[2]) in comp_xz}


def _exposed(cell, solid):
    """是否外露：6 邻域至少有一格不是实体（网格外也算外露）。"""
    x, y, z = cell
    return any(nb not in solid for nb in ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
                                          (x, y - 1, z), (x, y, z + 1), (x, y, z - 1)))


def _colored(ctx):
    """逐体素颜色 {cell: char}：优先 colorRows；旧二维轨道缺 colorRows 时按层 color 兜底。"""
    colored = ctx.get("colored") or {}
    if colored:
        return colored
    model = ctx.get("model") or {}
    try:
        from legogod.parts_library import COLOR_CHARS
    except ImportError:  # pragma: no cover - 生产依赖缺失时如实返回空
        return {}
    out = {}
    for layer in model.get("layers") or []:
        ch = COLOR_CHARS.get(layer.get("color"))
        if not ch:
            continue
        y = layer.get("y")
        for z, row in enumerate(layer.get("rows") or []):
            for x, value in enumerate(row):
                if value != ".":
                    out[(x, y, z)] = ch
    return out


def _chars_of(color_chars):
    """颜色字符集合：允许字符串 "RWM" 或字符序列。"""
    if isinstance(color_chars, str):
        return set(color_chars)
    return set(color_chars or ())


def _dominant_color(ctx, cells):
    """给定实体格中最常见的逐体素颜色字符；无配色返回 None。"""
    colored = _colored(ctx)
    counts = {}
    for cell in cells:
        ch = colored.get(cell)
        if ch:
            counts[ch] = counts.get(ch, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def _design_chars(model):
    """{(x,y,z): 设计行字符}（只含非空格，用于斜面/坡屋顶判定）。"""
    out = {}
    for layer in model.get("layers") or []:
        y = layer.get("y")
        for z, row in enumerate(layer.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    out[(x, y, z)] = ch
    return out


def _slope_cells_in(model, cells):
    """给定实体格中属于斜面/斜坡字符的格集合。"""
    chars = _design_chars(model)
    return {cell for cell in cells if chars.get(cell) in SLOPE_CHARS}


def _grid_size(model, axis):
    grid = model.get("grid") or {}
    return int(grid.get("w") if axis == "x" else grid.get("d") or 0)


# ================================================================ 新增几何原语
@_mcheck("storeys_min")
def _c_storeys_min(ctx, n, min_cells=4):
    """完整结构层数下限：实体格数 >=min_cells 的 y 层数量 >=n。

    用于「两层体量 / 两层塔身」这类分句：只数平铺层（y 层实体 ≥min_cells）而不是
    数 layers 长度（单层高结构的 layers 长度也会很大），避免把一层高墙当两层。
    """
    model = ctx["model"]
    layers = model.get("layers") or []
    if not layers:
        return ["模型没有层数据（无法验证分层体量）"]
    storeys = 0
    counts = []
    for layer in layers:
        y = layer.get("y")
        plane = {(x, z) for z, row in enumerate(layer.get("rows") or [])
                 for x, ch in enumerate(row) if ch != "."}
        counts.append((y, len(plane)))
        if len(plane) >= int(min_cells):
            storeys += 1
    if storeys < int(n):
        detail = "、".join(f"y={y}:{c}" for y, c in counts[:8])
        return [f"完整结构层数不足：实体≥{min_cells} 格的层 {storeys} < {n}"
                f"（只有矮墙/单层体量；各层实体数 {detail}）"]
    return []


@_mcheck("part_color_ratio_min")
def _c_part_color_ratio_min(ctx, patterns, color_chars, min_ratio, min_cells=1):
    """指定部位的主色占比下限：该部位真实体素中给定色系的占比 >=min_ratio。

    用于「红色坡屋顶 / 灰色塔身 / 棕色树干 / 绿色树冠 / 蓝色徽章 / 红色车身」这类配色分句：
    统计 colorRows 里该部位实体的颜色字符，不接受只写在名称/notes 里的颜色。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证配色）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空，配色无法验证）"]
    colored = _colored(ctx)
    want = _chars_of(color_chars)
    if not want:
        return ["part_color_ratio_min 未给出颜色字符"]
    # 只看外露格：内部体素会被通配骨架色覆盖，不能拿来稀释可见主色占比。
    surface = [c for c in cells if colored.get(c) and _exposed(c, ctx["solid"])]
    if not surface:
        return [f"部位 {patterns} 没有外露的逐体素配色（colorRows 为空，主色不可辨）"]
    hit = sum(1 for c in surface if colored[c] in want)
    ratio = hit / float(len(surface))
    if hit < int(min_cells) or ratio < float(min_ratio):
        return [f"部位 {patterns} 外露表面指定色系 {sorted(want)} 占比 {hit}/{len(surface)} = "
                f"{ratio:.0%} < {min_ratio:.0%}（主色/配色分区未真实成型）"]
    return []


@_mcheck("sloped_part_min")
def _c_sloped_part_min(ctx, patterns, min_slope_cells=1):
    """指定部位的斜面体素下限（坡屋顶/坡屋面必须用斜面砖真实收出坡度）。"""
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证坡屋顶）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    slope = len(_slope_cells_in(ctx["model"], cells))
    return [] if slope >= int(min_slope_cells) else [
        f"部位 {patterns} 斜面体素 {slope} < {min_slope_cells}"
        f"（坡屋顶没有真实坡度，平顶/方块不算）"]


def _opening_components(ctx, region_cells):
    """region 区域内「真实开洞」的 3D 连通块：上下有实体（门楣/窗台）且水平对侧有实体。

    只认 1 格宽、被墙体夹住的竖向洞口（上下实体、左右或前后两侧实体、中间负空间），
    用于「两扇窗为真实开洞」的 OR 分支；宽洞口/整面墙缺失不会被误当成窗。
    """
    solid = ctx["solid"]
    bbox = _bbox(region_cells)
    if bbox is None:
        return []
    x0, x1, y0, y1, z0, z1 = bbox
    x0, x1 = max(0, x0 - 2), x1 + 2
    z0, z1 = max(0, z0 - 2), z1 + 2
    candidates = set()
    for y in range(max(1, y0), y1 + 1):
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                cell = (x, y, z)
                if cell in solid:
                    continue
                if (x, y - 1, z) not in solid or (x, y + 1, z) not in solid:
                    continue
                along_x = (x - 1, y, z) in solid and (x + 1, y, z) in solid
                along_z = (x, y, z - 1) in solid and (x, y, z + 1) in solid
                if along_x or along_z:
                    candidates.add(cell)
    return _components_3d(candidates)


@_mcheck("exposed_color_min")
def _c_exposed_color_min(ctx, patterns, min_cells, color_chars=None, body_patterns=None):
    """外露异色细节下限（黑鼻/双眼/车灯/徽章）：命中部位中与宿主主色不同（或指定色系）
    且真实外露（6 邻居至少一格非实体）的体素 >=min_cells。

    与 G 组 g_exposed_contrast_color 的区别：这里按六面外露判定，侧面朝向的异色特征
    （鼻尖/前灯/胸前徽章）不会被「上方被压住」误判成内埋；给出 color_chars 时必须是对应色系。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到异色细节部位 {patterns}"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空，无法验证外露异色）"]
    colored = _colored(ctx)
    want = _chars_of(color_chars) if color_chars else set()
    body_dom = None
    if body_patterns:
        body_hits, body_cells = _cells(ctx, body_patterns)
        if body_hits and body_cells:
            body_dom = _dominant_color(ctx, body_cells)
    solid = ctx["solid"]
    exposed = []
    for cell in cells:
        ch = colored.get(cell)
        if not ch or not _exposed(cell, solid):
            continue
        if want and ch not in want:
            continue
        if not want and body_dom is not None and ch == body_dom:
            continue
        exposed.append(cell)
    if len(exposed) < int(min_cells):
        label = sorted(want) if want else "与主体异色"
        return [f"部位 {patterns} 外露异色细节不足：{len(exposed)} 格 < {min_cells}"
                f"（要求{label}且真实外露；内埋的异色不算）"]
    return []


@_mcheck("wall_opening_min")
def _c_wall_opening_min(ctx, patterns, min_height=2, max_bottom_offset=1):
    """墙体底部真实开口（门洞贯通）：围合墙体在底部若干层与外部连通、其上方又恢复围合。

    逐层用 grids 边界 flood fill 求「围合内腔」格数：门洞所在层内腔通过门洞与外部连通，
    围合内腔为 0；门洞上方墙体恢复围合后内腔格数 > 0。要求「最靠下的开口连续层」
    从墙体底部开始（max_bottom_offset）且高度 >=min_height，并且上方存在恢复围合的层。
    这样能区分「真实门洞贯通」和「整面墙缺失/整层实心/仅表面浅坑」，不依赖门洞部位命名。
    """
    hits, wall = _cells(ctx, patterns)
    if not hits:
        return [f"未找到墙体部位 {patterns}（无法验证门洞贯通）"]
    if not wall:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    model = ctx["model"]
    grid = model.get("grid") or {}
    width = int(grid.get("w") or (max(c[0] for c in wall) + 1))
    depth = int(grid.get("d") or (max(c[2] for c in wall) + 1))
    ys = sorted({c[1] for c in wall})
    if len(ys) < int(min_height):
        return [f"墙体层数 {len(ys)} < {min_height}（无法形成贯通门洞）"]
    solid = ctx["solid"]
    data = []
    for y in ys:
        # 围合判定用整模该层实体（城墙可能由独立角楼部位补上四角），部位只提供层范围。
        plane = {(x, z) for (x, yy, z) in solid if yy == y}
        empty = {(x, z) for x in range(width) for z in range(depth) if (x, z) not in plane}
        outside = {(x, z) for x in range(-1, width + 1) for z in (-1, depth)}
        outside |= {(x, z) for x in (-1, width) for z in range(depth)}
        stack = list(outside)
        while stack:
            x, z = stack.pop()
            for nb in ((x + 1, z), (x - 1, z), (x, z + 1), (x, z - 1)):
                if not (-1 <= nb[0] <= width and -1 <= nb[1] <= depth):
                    continue
                if nb in empty and nb not in outside:
                    outside.add(nb)
                    stack.append(nb)
        enclosed = sum(1 for (x, z) in empty
                       if (x, z) not in outside and 0 <= x < width and 0 <= z < depth)
        data.append((y, len(plane), enclosed))
    runs = []
    for y, plane_n, enclosed in data:
        if plane_n and enclosed == 0:
            if runs and y == runs[-1][-1] + 1:
                runs[-1].append(y)
            else:
                runs.append([y])
    if not runs:
        return [f"墙体在全部高度都保持围合：没有与外部连通的底部开口"
                f"（门洞未贯通，只是墙面涂装/浅坑）"]
    bottom = runs[0]
    if bottom[0] - ys[0] > int(max_bottom_offset):
        return [f"底部开口未从墙体底部开始（墙体 y={ys[0]}，开口最低层 y={bottom[0]}）："
                f"不像落地门洞"]
    if len(bottom) < int(min_height):
        return [f"门洞开口高度 {len(bottom)} < {min_height}（太矮或仅单层开洞）"]
    closed_above = any(enclosed > 0 for y, _plane, enclosed in data if y > bottom[-1])
    if not closed_above:
        return [f"墙体没有围合内腔（门洞两侧不成立：整面缺墙而不是墙上的门洞）"]
    return []


@_mcheck("windows_evidenced")
def _c_windows_evidenced(ctx, patterns, host_patterns, min_count=2, min_patch_cells=1):
    """窗可辨：窗部位自身「外露异色」成块，或所在区域存在真实开洞（二选一即可）。

    M01/M04 明确写「真实开洞或外露异色」：
      1) 外露异色：命中窗部位中与宿主主色不同的逐体素颜色格，按层 4-连通成块，
         块数 >=min_count 且每块 >=min_patch_cells；
      2) 真实开洞：窗区域附近上下有实体、左右/前后两侧有实体夹住的竖向空腔块数 >=min_count。
    两条路径都基于最终 model 的 layers/rows 与 colorRows 计算，不看名称/notes。
    """
    hits, wcells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到窗部位 {patterns}（无法验证窗户）"]
    host_hits, host_cells = _cells(ctx, host_patterns)
    base_cells = host_cells or ctx["solid"]
    body_dom = _dominant_color(ctx, base_cells)
    colored = _colored(ctx)
    solid = ctx["solid"]
    exposed = set()
    for cell in wcells:
        ch = colored.get(cell)
        if not ch or (body_dom is not None and ch == body_dom):
            continue
        if _exposed(cell, solid):
            exposed.add(cell)
    patches = []
    by_y = {}
    for (x, y, z) in exposed:
        by_y.setdefault(y, set()).add((x, z))
    for plane in by_y.values():
        patches.extend(comp for comp in _components_2d_xz(plane) if len(comp) >= min_patch_cells)
    openings = _opening_components(ctx, wcells) if wcells else []
    if len(patches) >= int(min_count) or len(openings) >= int(min_count):
        return []
    return [f"窗不可辨：外露异色窗块 {len(patches)} < {min_count}、真实开洞 "
            f"{len(openings)} < {min_count}（涂装在内部/同色的不算外露异色）"]


def _components_2d_xz(plane):
    """{(x,z)} 4-连通分组，返回 [{ (x,z) }]。"""
    return _components_xz({(x, 0, z) for (x, z) in plane})


@_mcheck("part_above_ref")
def _c_part_above_ref(ctx, patterns, ref_patterns, min_gap=1):
    """指定部位质心高于参照部位质心 min_gap 层（体量上下关系，不要求 bbox 完全分离）。"""
    hits, cells = _cells(ctx, patterns)
    ref_hits, ref_cells = _cells(ctx, ref_patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证上下关系）"]
    if not ref_hits:
        return [f"未找到参照部位 {ref_patterns}（无法验证上下关系）"]
    if not cells or not ref_cells:
        return [f"部位 {patterns}/{ref_patterns} 缺少几何体素数据"]
    gap = _centroid(cells)[1] - _centroid(ref_cells)[1]
    return [] if gap >= float(min_gap) else [
        f"部位 {patterns} 质心 y 未高于 {ref_patterns}：差 {gap:.1f} < {min_gap}"
        f"（体量上下关系/分体不可辨）"]


@_mcheck("part_below_ref")
def _c_part_below_ref(ctx, patterns, ref_patterns, min_gap=1):
    """指定部位质心低于参照部位质心 min_gap 层（下垂/下挂特征）。"""
    hits, cells = _cells(ctx, patterns)
    ref_hits, ref_cells = _cells(ctx, ref_patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证下垂）"]
    if not ref_hits:
        return [f"未找到参照部位 {ref_patterns}（无法验证下垂）"]
    if not cells or not ref_cells:
        return [f"部位 {patterns}/{ref_patterns} 缺少几何体素数据"]
    gap = _centroid(ref_cells)[1] - _centroid(cells)[1]
    return [] if gap >= float(min_gap) else [
        f"部位 {patterns} 质心 y 未低于 {ref_patterns}：差 {gap:.1f} < {min_gap}"
        f"（没有下垂/下挂姿态）"]


@_mcheck("tapered_parts_min")
def _c_tapered_parts_min(ctx, patterns, min_count, max_top_ratio=0.7):
    """尖形部件数量下限：独立几何块「顶面宽度 <= 底面宽度 × max_top_ratio」的块数 >=min_count。

    用于「双尖耳」这类成对尖形特征：只认逐层截面真实收尖，平顶柱/方块不算尖形。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（尖形特征缺失）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    tapered = 0
    detail = []
    for comp in _components_xz(cells):
        sub = _sub_cells(cells, comp)
        ys = sorted({c[1] for c in sub})
        if len(ys) < 2:
            detail.append("层数<2")
            continue
        widths = {y: sum(1 for c in sub if c[1] == y) for y in ys}
        bottom = max(widths[ys[0]], widths[ys[1]])
        top = widths[ys[-1]]
        ratio = top / float(bottom) if bottom else 1.0
        if bottom >= 2 and ratio <= float(max_top_ratio):
            tapered += 1
        else:
            detail.append(f"底{bottom}→顶{top}")
    if tapered < int(min_count):
        return [f"尖形部件 {tapered} < {min_count}（各块底→顶截面 {detail[:4]}，"
                f"顶部宽度需 <= 底部 ×{max_top_ratio}）"]
    return []


def _side_counts(ctx, cells, axis):
    size = _grid_size(ctx["model"], axis)
    if size <= 0:
        cov = [c[0] if axis == "x" else c[2] for c in cells]
        size = max(cov) + 1
    mid = (size - 1) / 2.0
    left = right = 0
    for comp in _components_xz(cells):
        sub = _sub_cells(cells, comp)
        center = _centroid(sub)
        pos = center[0] if axis == "x" else center[2]
        if pos <= mid - 0.5:
            left += 1
        elif pos >= mid + 0.5:
            right += 1
    return left, right


@_mcheck("pair_sides_min")
def _c_pair_sides_min(ctx, patterns, min_per_side=1, axis="auto", ref_patterns=None):
    """成对/两侧分布下限：几何块在某个水平轴中轴两侧各有 >=min_per_side 个。

    axis="x"/"z" 显式指定；axis="auto" 时按 ref_patterns（如有）的长轴或逐个水平轴尝试；
    ref_patterns 给出时（如「首尾舵」按艇身纵轴）用参照物的长轴判定前后/左右分布，
    防止拿另一组件的侧向成对冒充首尾成对。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（成对/两侧结构缺失）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    text = str(axis or "auto").lower()
    if text in ("x", "z"):
        axes = [text]
    elif text in ("auto", "xz", "zx"):
        if ref_patterns:
            ref_hits, ref_cells = _cells(ctx, ref_patterns)
            if ref_hits and ref_cells:
                axes = ["x" if _span(ref_cells, "x") >= _span(ref_cells, "z") else "z"]
            else:
                axes = ["x", "z"]
        else:
            axes = ["x", "z"]
    else:
        return [f"pair_sides_min 轴参数非法：{axis!r}（只能是 x/z/auto）"]
    problems = []
    for single in axes:
        left, right = _side_counts(ctx, cells, single)
        if left >= int(min_per_side) and right >= int(min_per_side):
            return []
        problems.append(f"轴 {single}：左/右（或前/后）几何块 {left}/{right}，"
                        f"各需 >= {min_per_side}")
    return [f"部位 {patterns} 未成对分列两侧：" + "；".join(problems)]


@_mcheck("part_extends_beyond")
def _c_part_extends_beyond(ctx, patterns, ref_patterns, axis="xz", min_overhang=1):
    """部件相对参照包络向外伸出/外凸 min_overhang 格（轴向可 x/y/z/xz）。

    用于「双耳外凸 / 象牙向前伸出 / 围壳外凸 / 云梯外伸 / 尾桨在艇尾」这类空间关系分句：
    命中部位体素必须真的超出参照部位包围盒，不能只是名字不同、中心重合。
    """
    hits, cells = _cells(ctx, patterns)
    ref_hits, ref_cells = _cells(ctx, ref_patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证外伸）"]
    if not ref_hits:
        return [f"未找到参照部位 {ref_patterns}（无法验证外伸）"]
    if not cells or not ref_cells:
        return [f"部位 {patterns}/{ref_patterns} 缺少几何体素数据"]
    text = str(axis or "xz").lower()
    if not text or any(ch not in _AXIS_INDEX for ch in text):
        return [f"part_extends_beyond 轴参数非法：{axis!r}（只能是 x/y/z 的组合）"]
    pat_bbox, ref_bbox = _bbox(cells), _bbox(ref_cells)
    overhang = 0
    for ch in dict.fromkeys(text):
        idx = _AXIS_INDEX[ch]
        lo, hi = pat_bbox[idx * 2], pat_bbox[idx * 2 + 1]
        ref_lo, ref_hi = ref_bbox[idx * 2], ref_bbox[idx * 2 + 1]
        overhang = max(overhang, hi - ref_hi, ref_lo - lo)
    return [] if overhang >= int(min_overhang) else [
        f"部位 {patterns} 相对 {ref_patterns} 在轴 {text} 上仅伸出 {overhang} 格"
        f" < {min_overhang}（没有真实外凸/外伸）"]


@_mcheck("crenellated_top_min")
def _c_crenellated_top_min(ctx, patterns, min_notches=2, min_depth=1):
    """顶部垛口：顶部沿水平方向出现 >=min_notches 组高点（垛）且高点之间有低凹（口）。

    逐列取命中部位的最高 y 得到顶部剖面：连续等高段为若干组「凸起」，剖面下降
    >=min_depth 处为「凹口」；组数与凹口都达标才算「两组凹凸垛口」，平顶不算。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证顶部垛口）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    detail = []
    for axis in ("x", "z"):
        profile = {}
        for (x, y, z) in cells:
            key = x if axis == "x" else z
            profile[key] = max(profile.get(key, -1), y)
        keys = sorted(profile)
        if len(keys) < 3:
            detail.append(f"轴 {axis} 只有 {len(keys)} 列")
            continue
        top = max(profile.values())
        values = [profile[k] for k in keys]
        runs = 0
        prev_top = False
        for value in values:
            is_top = value == top
            if is_top and not prev_top:
                runs += 1
            prev_top = is_top
        dips = sum(1 for value in values if value <= top - int(min_depth))
        if runs >= int(min_notches) and dips >= 1:
            return []
        detail.append(f"轴 {axis}：凸起 {runs} 组、低凹 {dips} 处")
    return [f"顶部垛口不足：需要 >= {min_notches} 组凹凸且至少一处低凹（{detail}）；"
            f"平顶/无垛口不算"]


def _through_runs(ctx, struct, axis, min_height, min_lintel):
    """单方向贯通检测：返回 (贯通位置连续段列表, 明细)。

    逐「横向位置」检查沿 axis 是否存在从结构一侧到另一侧的全空列，并记录该位置
    最长竖向贯通段；段高 >=min_height 且上方有实体（门楣/桥面）的位置才有效，
    有效位置按相邻聚成段，每段就是一个独立贯通孔洞。
    """
    solid = ctx["solid"]
    bbox = _bbox(struct)
    if bbox is None:
        return [], {}
    x0, x1, y0, y1, z0, z1 = bbox
    model = ctx["model"]
    grid = model.get("grid") or {}
    if axis == "x":
        across_lo, across_hi = z0, z1
        pass_lo, pass_hi = x0, x1
        limit = int(grid.get("w") or (x1 + 2))

        def cell_of(pos, y, across):
            return (pos, y, across)
    else:
        across_lo, across_hi = x0, x1
        pass_lo, pass_hi = z0, z1
        limit = int(grid.get("d") or (z1 + 2))

        def cell_of(pos, y, across):
            return (across, y, pos)
    p_min, p_max = max(0, pass_lo - 1), min(limit - 1, pass_hi + 1)
    valid = {}
    for across in range(across_lo, across_hi + 1):
        ys_ok = [y for y in range(y0, y1 + 1)
                 if all(cell_of(pos, y, across) not in solid for pos in range(p_min, p_max + 1))]
        if not ys_ok:
            continue
        best_start = best_end = cur_start = prev = ys_ok[0]
        for y in ys_ok[1:]:
            if y == prev + 1:
                prev = y
                continue
            if prev - cur_start > best_end - best_start:
                best_start, best_end = cur_start, prev
            cur_start = prev = y
        if prev - cur_start > best_end - best_start:
            best_start, best_end = cur_start, prev
        if best_end - best_start + 1 < int(min_height):
            continue
        lintel = sum(1 for pos in range(p_min, p_max + 1)
                     if cell_of(pos, best_end + 1, across) in solid)
        if lintel >= int(min_lintel):
            valid[across] = (best_start, best_end)
    runs = []
    for across in sorted(valid):
        if runs and across == runs[-1][-1] + 1:
            runs[-1].append(across)
        else:
            runs.append([across])
    return runs, valid


@_mcheck("negative_space_passages_min")
def _c_negative_space_passages_min(ctx, patterns, axis="auto", min_count=2,
                                   min_height=2, min_lintel=1):
    """多个独立贯通孔洞下限（三孔桥洞）：独立贯通位置段数 >=min_count。

    axis="auto" 表示水平两个方向都试（桥的朝向不冻结）；每段必须沿用穿越方向全空、
    竖向高度 >=min_height、上方有实体（桥面/门楣），把「没填实、彼此独立」一起验证。
    """
    hits, struct = _cells(ctx, patterns)
    if not hits:
        return [f"未找到结构部位 {patterns}（无法验证贯通孔洞）"]
    if not struct:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    text = str(axis or "auto").lower()
    if text in ("x", "z"):
        axes = [text]
    elif text in ("auto", "xz", "zx"):
        axes = ["x", "z"]
    else:
        return [f"negative_space_passages_min 轴参数非法：{axis!r}（只能是 x/z/auto）"]
    problems = []
    for single in axes:
        runs, valid = _through_runs(ctx, struct, single, min_height, min_lintel)
        if len(runs) >= int(min_count):
            return []
        problems.append(f"沿 {single} 方向独立贯通孔洞 {len(runs)} < {min_count}"
                        f"（有效贯通位置 {sorted(valid)[:6]}）")
    return [f"部位 {patterns} 的独立贯通孔洞不足：" + "；".join(problems)]


@_mcheck("thin_plate_min")
def _c_thin_plate_min(ctx, patterns, min_span=3, max_thickness=2):
    """薄面/薄帆：最大跨度 >=min_span 且最小维度 <=max_thickness（真实薄板，非厚实心块）。"""
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（薄面特征缺失）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    spans = sorted((_span(cells, axis), axis) for axis in ("x", "y", "z"))
    long_span, mid_span, thin = spans[2][0], spans[1][0], spans[0][0]
    errs = []
    if long_span < int(min_span):
        errs.append(f"部位 {patterns} 最大跨度 {long_span} < {min_span}（薄面尺寸不足）")
    if thin > int(max_thickness):
        errs.append(f"部位 {patterns} 最薄维度 {thin} > {max_thickness}"
                    f"（是厚实心块，不是可辨的薄面/薄帆）")
    if mid_span < 2 and long_span >= int(min_span):
        errs.append(f"部位 {patterns} 第二跨度 {mid_span} < 2（细条不能算薄面）")
    return errs


@_mcheck("part_levels_min")
def _c_part_levels_min(ctx, patterns, min_levels=3, min_span=2):
    """沿高度分布的独立层/平台下限：命中部位在 >=min_levels 个互不连续的 y 层带上
    有水平跨度 >=min_span 的截面（三层观景平台这类分句）。"""
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证分层平台）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    levels = []
    for y in sorted({c[1] for c in cells}):
        plane = {c for c in cells if c[1] == y}
        if max(_span(plane, "x"), _span(plane, "z")) >= int(min_span):
            levels.append(y)
    bands = []
    for y in levels:
        if bands and y == bands[-1][-1] + 1:
            bands[-1].append(y)
        else:
            bands.append([y])
    if len(bands) < int(min_levels):
        return [f"沿高度分布的层次 {len(bands)} < {min_levels}"
                f"（有效层 {levels[:8]}，互不连续才计一层；平台未分层）"]
    return []


@_mcheck("corner_towers_min")
def _c_corner_towers_min(ctx, patterns, host_patterns=None, min_count=4, tol_frac=0.35):
    """角楼：>=min_count 个独立几何块分别落在宿主包围盒的不同角上（四角楼）。

    判据：角楼几何块投影质心到宿主四个平面角点的切比雪夫距离 <= tol_frac×最大边长，
    且每个角只认最近的一块；四角各有一块才算「四座角楼」，排成一条线不算。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（角楼缺失）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    host_hits, host_cells = _cells(ctx, host_patterns) if host_patterns else ([], set())
    anchor = host_cells or ctx["solid"]
    bbox = _bbox(anchor)
    if bbox is None:
        return ["模型没有实体，无法验证角楼位置"]
    x0, x1, _y0, _y1, z0, z1 = bbox
    corners = [(x0, z0), (x0, z1), (x1, z0), (x1, z1)]
    tol = float(tol_frac) * max(x1 - x0 + 1, z1 - z0 + 1)
    comps = _components_xz(cells)
    if len(comps) < int(min_count):
        return [f"角楼独立几何块 {len(comps)} < {min_count}（角楼被合并/未分立）"]
    assigned, notes = set(), []
    for comp in comps:
        sub = _sub_cells(cells, comp)
        cx, cz = _centroid(sub)[0], _centroid(sub)[2]
        dists = [max(abs(cx - corner[0]), abs(cz - corner[1])) for corner in corners]
        idx = min(range(len(corners)), key=lambda i: dists[i])
        notes.append(round(dists[idx], 1))
        if dists[idx] <= tol:
            assigned.add(idx)
    if len(assigned) < int(min_count):
        return [f"角楼没有分布在四角：覆盖角点 {len(assigned)} < {min_count}"
                f"（各块到最近角点距离 {notes[:6]}，容差 {tol:.1f}）"]
    return []


@_mcheck("legs_splay_min")
def _c_legs_splay_min(ctx, patterns, min_drift=1.0, max_bottom_y=0):
    """塔腿外张并落地：各腿几何块「底部质心离中轴距离 - 顶部质心距离」的平均值 >=min_drift，
    且每条腿最低层 y <=max_bottom_y（落在基座/地面，不能悬空）。"""
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到塔腿部位 {patterns}（无法验证外张）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    comps = _components_xz(cells)
    if len(comps) < 2:
        return [f"塔腿几何块 {len(comps)} < 2（腿被合并成一块，无法验证外张）"]
    center = _centroid(cells)
    drifts, bottoms = [], []
    for comp in comps:
        sub = _sub_cells(cells, comp)
        ys = sorted({c[1] for c in sub})
        bottoms.append(ys[0])
        if len(ys) < 2:
            drifts.append(0.0)
            continue
        bottom = [c for c in sub if c[1] == ys[0]]
        top = [c for c in sub if c[1] == ys[-1]]
        dist_bottom = sum(math.hypot(c[0] - center[0], c[2] - center[2])
                          for c in bottom) / len(bottom)
        dist_top = sum(math.hypot(c[0] - center[0], c[2] - center[2])
                       for c in top) / len(top)
        drifts.append(dist_bottom - dist_top)
    errs = []
    average = sum(drifts) / len(drifts)
    if average < float(min_drift):
        errs.append(f"塔腿没有向外张开：底部相对顶部平均外扩 {average:.2f} < {min_drift}"
                    f"（直柱/内收不算外张）")
    if max(bottoms) > int(max_bottom_y):
        errs.append(f"塔腿没有落到地面/基座：最低层 y={max(bottoms)} > {max_bottom_y}")
    return errs


@_mcheck("center_void_min")
def _c_center_void_min(ctx, patterns, min_cells=4):
    """中央负空间：命中结构包围盒中央 1/3 区域内，各层非实体格数量 >=min_cells。

    用于「中央负空间不得填实 / 内院不得填实」：中央区域必须是真实空腔，堆成实心柱不算。
    """
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到结构部位 {patterns}（无法验证中央负空间）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    bbox = _bbox(cells)
    x0, x1, y0, y1, z0, z1 = bbox
    w, d = x1 - x0 + 1, z1 - z0 + 1
    cx_lo, cx_hi = x0 + (w + 2) // 3, x1 - (w + 2) // 3
    cz_lo, cz_hi = z0 + (d + 2) // 3, z1 - (d + 2) // 3
    if cx_lo > cx_hi or cz_lo > cz_hi:
        return [f"结构平面尺寸 {w}×{d} 太小，无法判定中央负空间"]
    solid = ctx["solid"]
    empty = sum(1 for y in range(y0, y1 + 1)
                for x in range(cx_lo, cx_hi + 1)
                for z in range(cz_lo, cz_hi + 1) if (x, y, z) not in solid)
    return [] if empty >= int(min_cells) else [
        f"中央负空间被填实：中央 1/3 区域非实体格 {empty} < {min_cells}"
        f"（实心柱/填实的塔心不算）"]


def _ring_plane(cells):
    """取部件张成的两个最大跨度轴（0=x/1=y/2=z），用于竖直轮盘等非水平平面结构。"""
    spans = sorted(((max(c[idx] for c in cells) - min(c[idx] for c in cells) + 1
                     for idx in (0, 1, 2))), reverse=True) if cells else [0, 0, 0]
    order = sorted((0, 1, 2), key=lambda idx: spans[idx] if len(spans) > idx else 0,
                   reverse=True)
    return order[0], order[1]


def _top_peak_clusters(cells):
    """顶部局部高点簇：{(x,z)} 每列最高 y 中「不低于 8 邻域」的格，按 4-连通分簇。

    用于「多片层叠壳体屋顶」：单片坡顶只有一条脊线（1 簇），多片贝壳屋顶有 >=2 个高点簇；
    平顶所有列等高会合成 1 簇。返回 [(簇格集合, 该簇最高 y)]。
    """
    top = {}
    for (x, y, z) in cells:
        key = (x, z)
        if y > top.get(key, -1):
            top[key] = y
    peaks = set()
    for (x, z), height in top.items():
        neighbors = [top.get((x + dx, z + dz), -1)
                     for dx in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dz) != (0, 0)]
        if all(height >= value for value in neighbors):
            peaks.add((x, z))
    clusters = _components_2d_xz(peaks)
    return [(comp, max(top[cell] for cell in comp)) for comp in clusters if comp]


@_mcheck("shell_roof_min")
def _c_shell_roof_min(ctx, patterns, min_shells=2, min_slope_cells=6, min_top_levels=2):
    """多片层叠壳体屋顶：屋顶不是单块方顶（>=min_shells 片/组或 >=2 个顶部高点簇）、
    有斜面曲率、各壳片顶部高度至少 min_top_levels 档（高低层叠变化）。"""
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到屋顶部位 {patterns}（壳体屋顶缺失）"]
    if not cells:
        return [f"屋顶部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    peak_clusters = _top_peak_clusters(cells)
    # 多片证据：独立部位数 / 3D 几何块数 / 顶部高点簇数，取最大（单片坡顶只有 1 簇）。
    shell_count = max(len(hits), len(_components_3d(cells)), len(peak_clusters))
    slope = len(_slope_cells_in(ctx["model"], cells))
    top_heights = {height for _comp, height in peak_clusters}
    errs = []
    if shell_count < int(min_shells):
        errs.append(f"壳体屋顶只有 {shell_count} 片/组 < {min_shells}"
                    f"（单块方顶/单坡顶不算层叠贝壳形屋顶）")
    if slope < int(min_slope_cells):
        errs.append(f"屋顶斜面体素 {slope} < {min_slope_cells}（没有曲率变化）")
    if len(top_heights) < int(min_top_levels):
        errs.append(f"壳片顶部高度档位 {len(top_heights)} < {min_top_levels}"
                    f"（壳片没有高低变化）")
    return errs


@_mcheck("perimeter_objects_min")
def _c_perimeter_objects_min(ctx, patterns, ref_patterns, min_count=8,
                             min_sectors=8, min_radius_frac=0.5):
    """沿轮周分布的对象下限（八个吊舱）：独立几何块数量 >=min_count，且这些块的质心
    落在参照环半径 >=min_radius_frac 的外圈、覆盖 >=min_sectors 个角向区段。

    轮盘平面取参照部件张成的两个最大跨度轴（摩天轮是竖直 x-y 平面，不是水平 xz），
    对象用 3D 连通块计数（吊舱可以叠在不同 y 层但仍彼此独立）。
    """
    hits, cells = _cells(ctx, patterns)
    ref_hits, ref_cells = _cells(ctx, ref_patterns)
    if not hits:
        return [f"未找到沿周分布的对象部位 {patterns}"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    if not ref_hits or not ref_cells:
        return [f"未找到参照环部位 {ref_patterns}（无法验证沿周分布）"]
    a1, a2 = _ring_plane(ref_cells)
    center = _centroid(ref_cells)
    radius = max(math.hypot(c[a1] - center[a1], c[a2] - center[a2]) for c in ref_cells)
    if radius <= 0:
        return [f"参照环 {ref_patterns} 尺寸为 0，无法验证沿周分布"]
    on_rim = []
    for comp in _components_3d(cells):
        center_c = _centroid(comp)
        dist = math.hypot(center_c[a1] - center[a1], center_c[a2] - center[a2])
        if dist >= float(min_radius_frac) * radius:
            on_rim.append(center_c)
    errs = []
    if len(on_rim) < int(min_count):
        errs.append(f"沿轮周对象 {len(on_rim)} < {min_count}"
                    f"（半径 >= {min_radius_frac:.0%} 外圈的独立块数不足）")
    sectors = set()
    divisor = 360.0 / max(1, int(min_sectors))
    for center_c in on_rim:
        angle = math.degrees(math.atan2(center_c[a2] - center[a2],
                                        center_c[a1] - center[a1])) % 360.0
        sectors.add(int(angle // divisor) % int(min_sectors))
    if len(sectors) < int(min_sectors):
        errs.append(f"沿周分布角向区段 {len(sectors)}/{min_sectors} < {min_sectors}"
                    f"（没有均匀绕轮周分布）")
    return errs


@_mcheck("parts_union_components")
def _c_parts_union_components(ctx, pattern_groups, max_components=1):
    """多个需求部位并集必须连成整体（整体连通/城墙与角楼连通/三者连接）。

    只统计给定部位组内部的空间 6-邻接连通性，不重算通用统一校验（避免复制底线断言）。
    """
    groups = pattern_groups if isinstance(pattern_groups, (list, tuple)) else []
    if not groups:
        return ["parts_union_components 未给出部位组"]
    union = set()
    missing = []
    for patterns in groups:
        hits, cells = _cells(ctx, patterns)
        if not hits or not cells:
            missing.append(str(patterns))
            continue
        union |= cells
    if missing:
        return [f"缺少组成部位 {missing}（无法验证整体连通）"]
    comps = _components_3d(union)
    if len(comps) > int(max_components):
        sizes = sorted((len(comp) for comp in comps), reverse=True)[:6]
        return [f"需求部位未连成整体：并集断开成 {len(comps)} 块 > {max_components}"
                f"（各块体素 {sizes}，存在悬空/未搭接部位）"]
    return []


@_mcheck("parts_adjacent_any")
def _c_parts_adjacent_any(ctx, patterns, pattern_groups, min_contacts=1):
    """指定部位必须与给定候选部位组之一真实接触（如引擎连接主机翼或机身）。"""
    hits, cells = _cells(ctx, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证连接）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    groups = pattern_groups if isinstance(pattern_groups, (list, tuple)) else []
    others = set()
    labels = []
    for patterns2 in groups:
        _hits2, cells2 = _cells(ctx, patterns2)
        if cells2:
            others |= cells2
            labels.append(str(patterns2))
    if not others:
        return [f"候补连接部位 {groups} 都不存在（无法验证 {patterns} 的连接）"]
    contacts = sum(1 for cell in cells
                   for nb in ((cell[0] + 1, cell[1], cell[2]), (cell[0] - 1, cell[1], cell[2]),
                              (cell[0], cell[1] + 1, cell[2]), (cell[0], cell[1] - 1, cell[2]),
                              (cell[0], cell[1], cell[2] + 1), (cell[0], cell[1], cell[2] - 1))
                   if nb in others)
    return [] if contacts >= int(min_contacts) else [
        f"部位 {patterns} 与 {'/'.join(labels)} 的体素 6-邻接接触面 {contacts} < "
        f"{min_contacts}（空间上未真实连接）"]


@_mcheck("radial_spokes_min")
def _c_radial_spokes_min(ctx, patterns, ring_patterns, min_count=4, min_reach_ratio=0.5):
    """辐条：从轮毂向轮缘辐射的真实细梁方向数 >=min_count（每个角向区段内
    辐条格最大半径 >=min_reach_ratio × 轮缘半径才计一个方向；轮盘平面取轮缘两个最大跨度轴）。"""
    hits, cells = _cells(ctx, patterns)
    ring_hits, ring_cells = _cells(ctx, ring_patterns)
    if not hits:
        return [f"未找到辐条部位 {patterns}（辐条缺失）"]
    if not ring_hits or not ring_cells:
        return [f"未找到轮缘部位 {ring_patterns}（无法验证辐条辐射）"]
    spoke_only = set(cells) - set(ring_cells)
    if not spoke_only:
        return [f"辐条体素全部与轮缘重合（没有从轮毂到轮缘的细梁）"]
    a1, a2 = _ring_plane(ring_cells)
    center = _centroid(ring_cells)
    radius = max(math.hypot(c[a1] - center[a1], c[a2] - center[a2]) for c in ring_cells)
    if radius <= 0:
        return [f"轮缘部位 {ring_patterns} 尺寸为 0，无法验证辐条"]
    reach = {}
    for cell in spoke_only:
        angle = math.degrees(math.atan2(cell[a2] - center[a2],
                                        cell[a1] - center[a1])) % 360.0
        bin_index = int(angle // 45.0) % 8
        dist = math.hypot(cell[a1] - center[a1], cell[a2] - center[a2])
        reach[bin_index] = max(reach.get(bin_index, 0.0), dist)
    directions = [idx for idx, value in reach.items()
                  if value >= float(min_reach_ratio) * radius]
    if len(directions) < int(min_count):
        return [f"辐条辐射方向 {len(directions)} < {min_count}"
                f"（各方向最大半径 {[round(reach[i], 1) for i in sorted(reach)]}，"
                f"轮缘半径 {radius:.1f}；未从轮毂伸到轮缘）"]
    return []


# ---------------------------------------------------------------- 检查解析
def resolve_check(name):
    """解析检查名：M 新原语 -> G 组注册表 -> 20 例通用检查器；找不到返回 None。"""
    if name in M_CHECKS:
        return M_CHECKS[name]
    if name in G_CHECKS:
        return G_CHECKS[name]
    return GENERIC_CHECKS.get(name)


# ---------------------------------------------------------------- 模式事实断言
def _record_sources(record):
    """记录本体 + 常见嵌套结果（job result / run_record）作为字段来源。"""
    sources = [record]
    for key in ("result", "runRecord", "run_record"):
        value = record.get(key)
        if isinstance(value, dict):
            sources.append(value)
    return sources


def _record_get(record, key, default=None):
    for source in _record_sources(record):
        if key in source and source.get(key) is not None:
            return source.get(key)
    return default


def _attempts(record):
    """各次尝试明细 attempts_detail（兼容嵌套 result/runRecord）；没有返回 None。"""
    for source in _record_sources(record):
        for key in ("attempts_detail", "attemptsDetail"):
            value = source.get(key)
            if isinstance(value, list) and any(isinstance(item, dict) for item in value):
                return value
    return None


def _mode_facts(record, review, review_source):
    """提取并断言模式事实（fast 无评审/无保底；fidelity 评审或如实不可用、保底 <=1）。"""
    errors = []
    mode = _record_get(record, "mode")
    mode = str(mode).strip().lower() if mode else None
    counts = _record_get(record, "counts")
    counts = counts if isinstance(counts, dict) else {}
    review_flag = _record_get(record, "reviewFlag") or _record_get(record, "review_flag")
    outcome = _record_get(record, "outcome")
    attempts = _attempts(record)
    fallback_attempts = []
    if attempts is not None:
        fallback_attempts = [item for item in attempts
                             if str(item.get("mode") or "").strip().lower() == "fast"]
    fallback_count = len(fallback_attempts) if attempts is not None else None
    revise_visual = counts.get("revise_visual")
    facts = {
        "mode": mode,
        "outcome": outcome,
        "review_present": bool(review),
        "review_source": review_source,
        "review_flag": review_flag,
        "review_unavailable": bool(_record_get(record, "reviewUnavailable")
                                   or review_flag == "review_unavailable"),
        "counts": dict(counts),
        "revise_visual": revise_visual,
        "attempts_detail_present": attempts is not None,
        "attempts": [{"mode": item.get("mode"), "ok": item.get("ok"),
                      "run_id": item.get("run_id"),
                      "failure": item.get("failure")} for item in (attempts or [])],
        "fallback_count": fallback_count,
        "fallback_attempts": fallback_attempts,
    }
    if mode is None:
        errors.append("模式事实缺失：记录缺少 mode（双模式 E2E 必须可核对 fast/fidelity 路由）")
    elif mode not in ("fast", "fidelity"):
        errors.append(f"模式非法：mode={mode!r}（只允许 fast/fidelity）")
    elif mode == "fast":
        if review:
            errors.append("快速模式出现视觉评审结果：review 非空（快速视觉评审调用应为 0）")
        if review_flag:
            errors.append(f"快速模式 reviewFlag={review_flag!r}（快速不评审，标记必须为空）")
        if revise_visual is None:
            errors.append("快速模式记录缺少 counts.revise_visual，无法证明未做视觉修订")
        else:
            try:
                revise_visual_int = int(revise_visual)
            except (TypeError, ValueError):
                revise_visual_int = None
            if revise_visual_int is None:
                errors.append(f"快速模式 counts.revise_visual={revise_visual!r} 不是整数，无法核对")
            elif revise_visual_int != 0:
                errors.append(f"快速模式视觉修订 {revise_visual_int} 次 != 0（快速不评审、不修订）")
        if fallback_count is not None and fallback_count > 0:
            errors.append(f"快速模式出现自动保底尝试 {fallback_count} 次（快速不得自动保底）")
        if outcome == "fast_fallback":
            errors.append("快速模式结果标记 fast_fallback（快速不得触发自动保底）")
    else:  # fidelity
        honest_unavailable = (review_flag in ("review_unavailable", "review_failed", "review_stale")
                              or facts["review_unavailable"])
        # 只有「高保真产物已交付」才强制要求评审结果或如实不可用标记；
        # 高保真硬失败 / 自动保底场景在失败前没有评审调用是正常事实，不算伪造。
        delivered = outcome in ("fidelity_success", "fidelity_degraded") \
            or (outcome is None and bool(record.get("ok")))
        if delivered and not review and not honest_unavailable:
            errors.append("高保真产物已交付但缺少视觉评审结果，且未如实标注评审不可用"
                          "（review/reviewFlag 均为空）")
        if fallback_count is not None:
            if fallback_count > 1:
                errors.append(f"高保真自动保底尝试 {fallback_count} 次 > 1（最多一次）")
            if fallback_count == 0 and outcome == "fast_fallback":
                errors.append("高保真结果标记 fast_fallback，但 attempts_detail 中没有 fast 保底尝试")
            if fallback_count > 0 and outcome in ("fidelity_success", "fidelity_degraded"):
                errors.append("高保真产物已交付却发生了快速保底"
                              "（有可拼产物且评审未过/不可用时不跑快速保底）")
        elif outcome == "fast_fallback":
            facts["fallback_count_note"] = ("记录缺少 attempts_detail，保底次数未知；"
                                            "fast_fallback 结果必须转储尝试明细")
    facts["ok"] = not errors
    facts["errors"] = errors
    return errors, facts


# ---------------------------------------------------------------- 断言入口
def check_objects_m(record, model, solution, case, review_fallback=None):
    """对 M 组单个案例执行通用底线 + 需求达标档 + 模式事实 + 回归档，返回 (errors, metrics)。

    errors = 通用可信底线失败 + 需求正确性失败 + 模式事实失败（任何一项即断言失败）；
    metrics["requirement_tier"] 参考 tools/e2e_assert_20.check_objects 的结构（含目标块数比、
    部位/特征断言、最终门禁），并额外给出 mode_facts（模式/评审/保底事实字段），
    供 tools/e2e_mode20_report.py 逐例并排展示。
    review_fallback：旧 run 记录没有 review 时从任务结果 result.review 补入。
    """
    record = record if isinstance(record, dict) else {}
    model = model if isinstance(model, dict) else {}
    solution = solution if isinstance(solution, dict) else {}
    case = case if isinstance(case, dict) else {}

    generic_errors = []
    try:
        # 通用可信底线：必须 import 复用现有 assert_generic，不得复制（任务硬要求）。
        assert_generic(record, model, solution, generic_errors)
    except SystemExit as exc:  # load_run 数据异常被以 SystemExit 抛出时也转可读失败
        generic_errors.append(f"通用底线断言数据异常：{exc}")
    except Exception as exc:  # noqa: BLE001 - 断言模块必须可读失败、不静默通过
        generic_errors.append(f"通用底线断言执行失败：{exc.__class__.__name__}: {exc}")

    ctx = {"model": model, "solution": solution, "counts": _part_counts(model),
           "colored": _colored_cells(model), "solid": _solid(model)}
    label = f"{case.get('id', 'M??')} {case.get('name', '')}".strip()
    target = _target_blocks(case.get("desc") or record.get("desc") or "")
    if target is None:
        target = case.get("target_blocks")
    bricks = len(solution.get("steps") or [])

    requirement_errors = []
    require_errors = []
    feature_checks = []
    desc = record.get("desc")
    frozen_desc = case.get("desc") or ""
    desc_ok = None
    if desc is not None:
        desc_ok = (desc == frozen_desc)
        if not desc_ok:
            requirement_errors.append(
                "运行记录需求原文与冻结案例不一致（跑中改题）："
                f"{str(desc)[:40]!r}… != {frozen_desc[:40]!r}…")
    if record.get("ok"):
        _require_parts(model, require_errors, label, case.get("require_parts") or [])
        requirement_errors.extend(require_errors)
        for spec in case.get("checks") or []:
            name, args = spec[0], spec[1:]
            fn = resolve_check(name)
            if fn is None:
                check_errors = [f"断言配置错误：未知检查 {name}"]
            else:
                try:
                    check_errors = list(fn(ctx, *args) or [])
                except Exception as exc:  # noqa: BLE001 - 产物异常时必须可读失败
                    check_errors = [f"检查 {name} 执行失败：{exc.__class__.__name__}: {exc}"]
            feature_checks.append({"name": name, "ok": not check_errors,
                                   "errors": check_errors})
            requirement_errors.extend(check_errors)
        # 需求达标档：目标块数比（冻结容差 >=50%，e2e_assert_20.TARGET_RATIO_MIN）。
        if target:
            ratio = bricks / float(target)
            if ratio < TARGET_RATIO_MIN:
                requirement_errors.append(
                    f"需求达标档：实际零件 {bricks} / 目标 {target} = {ratio:.1%}"
                    f" < {TARGET_RATIO_MIN:.0%}（目标块数未达标）")
        # 过期高保真成功：评审稿与最终模型哈希不一致时不得判成功（沿用 C/H 断言口径）。
        review_stale = _record_get(record, "reviewStale")
        if review_stale is True:
            requirement_errors.append("最终产物评审已过期（reviewStale=true，评审稿与最终模型"
                                      "哈希不一致）：不得判成功")
    else:
        review_stale = _record_get(record, "reviewStale")

    review, review_source = review_with_source(record, review_fallback)
    mode_errors, mode_facts = _mode_facts(record, review, review_source)
    errors = generic_errors + requirement_errors + mode_errors

    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    draw_attempts = _record_get(record, "drawAttempts")
    draw_attempts = draw_attempts if isinstance(draw_attempts, list) else []
    voxels = int(model.get("totalVoxels") or 0)
    ops = len(model.get("ops") or [])
    bricks_ratio = round(bricks / float(target), 4) if target else None
    gate_source, gate_ok, _gate_errors = final_gate_state(record)
    scale = _record_get(record, "scaleMetrics")
    scale = scale if isinstance(scale, dict) else None
    requirement_tier = {
        "target_blocks": target,
        "bricks": bricks,
        "bricks_ratio": bricks_ratio,
        "target_blocks_ok": (bricks_ratio >= TARGET_RATIO_MIN) if bricks_ratio is not None else None,
        "require_parts": {"ok": not require_errors, "errors": require_errors},
        "feature_checks": feature_checks,
        "final_gate_ok": gate_ok,
        "final_gate_source": gate_source,
        "desc_frozen": desc_ok,
        "review_stale_ok": (None if review_stale is None else not review_stale),
        "server_scale_metrics": scale,
        "ok": not requirement_errors,
        "errors": list(requirement_errors),
    }
    voxels_per_piece = round(voxels / bricks, 2) if bricks else None
    regression_tier = {
        "voxels": voxels,
        "actual_voxels": voxels,
        "actual_bricks": bricks,
        "voxels_per_target_block": round(voxels / float(target), 2) if target else None,
        "actual_voxels_per_piece": voxels_per_piece,
        "baseline_voxels_median": 650,
        "baseline_planned_voxels_median": 705,
        "baseline_bricks_ratio_median": 0.29,
        "voxels_vs_baseline_median": round(voxels / 650.0, 2),
        "baseline_voxels_per_piece_median": 7.98,
        "ops": ops,
        "layers": len(model.get("layers") or []),
        "colors": len(set(ctx["colored"].values())),
        "slope_voxels": _slope_count(model),
        "parts": ctx["counts"][0],
        "solid_parts": ctx["counts"][1],
        "note": "当前能力回归档只记录规模/复杂度参考，不参与失败判定",
    }
    metrics = {
        "suite": "M", "case": case.get("id"), "name": case.get("name"),
        "tier": case.get("tier"), "run_id": _record_get(record, "runId") or record.get("runId"),
        "desc_hash": case_hash(case), "desc_frozen": desc_ok,
        "task_ok": bool(record.get("ok")), "error": record.get("error"),
        "mode": mode_facts["mode"], "outcome": mode_facts["outcome"],
        "track": model.get("track"),
        "target_blocks": target, "bricks": bricks, "bricks_ratio": bricks_ratio,
        "target_blocks_ok": requirement_tier["target_blocks_ok"],
        "parts": ctx["counts"][0], "solid_parts": ctx["counts"][1],
        "surface_parts": ctx["counts"][2],
        "voxels": voxels, "ops": ops,
        "slope_voxels": _slope_count(model),
        "layers": len(model.get("layers") or []),
        "grid": model.get("grid"),
        "pieces": bricks,
        "voxels_per_piece": voxels_per_piece,
        "colors": len(set(ctx["colored"].values())),
        "gate_failed": bool(record.get("gateFailed") or record.get("gate_failed")),
        "gate_errors": record.get("gateErrors") or record.get("gate_errors") or [],
        "final_gate_replay": _record_get(record, "finalGateReplay"),
        "final_gate_source": gate_source,
        "final_gate_ok": gate_ok,
        "validation_ok": solution.get("validation", {}).get("ok")
        if isinstance(solution.get("validation"), dict) else None,
        "review_overall": scores.get("overall"),
        "review_flag": mode_facts["review_flag"],
        "draw_attempts": len(draw_attempts),
        "draw_requests": draw_request_count(draw_attempts),
        "review": review, "review_source": review_source,
        "review_stale": review_stale,
        "version_overwrites": _record_get(record, "versionOverwriteCount"),
        "feature_checks": feature_checks,
        "requirement_tier": requirement_tier,
        "regression_tier": regression_tier,
        "generic_tier": generic_errors,
        # ---- 模式事实（任务硬要求：写入 metrics，报告逐例并排使用） ----
        "mode_facts": mode_facts,
        "mode_facts_ok": mode_facts["ok"],
        "mode_review_present": mode_facts["review_present"],
        "mode_review_flag": mode_facts["review_flag"],
        "mode_revise_visual": mode_facts["revise_visual"],
        "mode_fallback_count": mode_facts["fallback_count"],
        "assertion_errors": errors,
        "assertion_ok": not errors,
    }
    return errors, metrics


def check_run_m(run_id, case_id=None, review_fallback=None):
    """读取 run 记录与最终产物执行 M 组断言，返回 metrics dict（CLI 用）。"""
    try:
        record, model, solution = load_run(run_id)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"读取 run {run_id} 失败：{exc}") from exc
    case = find_m_case(case_id, desc=record.get("desc"))
    if case is None:
        raise SystemExit(f"无法匹配 M 组案例：case_id={case_id!r} "
                         f"desc={str(record.get('desc'))[:60]!r}"
                         "（请显式给 --case，或确认需求原文与 tools/e2e_cases_mode20.py 一致）")
    _errors, metrics = check_objects_m(record, model, solution, case,
                                       review_fallback=review_fallback)
    metrics["desc"] = record.get("desc")
    return metrics


def main(argv=None):
    try:  # Windows GBK 控制台兼容：CLI 打印不能因编码崩溃
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
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
        print("用法: python -m tools.e2e_assert_mode20 <run_id> [--case M01] [--json out.json]")
        return 2
    metrics = check_run_m(positional[0], case_id)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"案例 {metrics['case']} {metrics['name']}（{metrics['tier']}）· "
          f"run {metrics['run_id']} · 模式 {metrics['mode']} · "
          f"{'✅ 断言通过' if metrics['assertion_ok'] else '❌ 断言未通过'}")
    print(f"  目标块数={metrics['target_blocks']} 实际零件={metrics['bricks']} "
          f"比值={metrics['bricks_ratio']} 达标={metrics['target_blocks_ok']}")
    print(f"  任务成功={metrics['task_ok']} 部位={metrics['parts']}"
          f"(立体{metrics['solid_parts']}/涂装{metrics['surface_parts']}) "
          f"体素={metrics['voxels']} 算子={metrics['ops']} 层={metrics['layers']} "
          f"颜色={metrics['colors']} 评审标记={metrics['review_flag']} "
          f"保底尝试={metrics['mode_fallback_count']}")
    if metrics["assertion_errors"]:
        print("断言未通过项：")
        for error in metrics["assertion_errors"]:
            print(" -", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
