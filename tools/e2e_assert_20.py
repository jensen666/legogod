# -*- coding: utf-8 -*-
"""20 个全新复杂案例的「结果正确性」硬断言（tools/e2e_cases_20.py 的检查器实现）。

用法：
    python -m tools.e2e_assert_20 <run_id>              # 按运行记录 desc 自动匹配案例
    python -m tools.e2e_assert_20 <run_id> --case C01
    python -m tools.e2e_assert_20 <run_id> --json out.json

口径：
  - 通用底线：任务成功、最终门禁通过、统一物理校验通过、最终版本产物齐全；
    最终门禁以 run 记录的 finalGateReplay（对最终模型重放）为准，gateDegraded/gateFailed
    过程标记只记录；旧记录没有重放字段时退回 gateFailed 过程标记（兼容降级，不因缺失误判）。
  - 复杂度分两层（只写进 metrics，失败项只来自需求达标档）：
      requirement_tier 需求达标档：目标块数比（bricks/targetBlocks ≥ 0.5 冻结容差）、
        特征/几何断言结果、部位/立体部位/体素/算子设计下限；
      regression_tier 当前能力回归档：与 2026-11-02 基线（交付体素中位 650、规划预估中位
        705、体素/零件比 7.98）的对比，只记录不判失败。
  - 结果专项：描述里点名的部位必须真实存在且未被删空；C05 红环带/C07 门洞与飞檐/
    C10 轮毂/H04 前腿搭绣球等「实现方式歧义」特征改为结果几何/空间关系检查，
    不再要求 LLM 恰好用某个部位名或算子名（原名称断言存在误报）。
  - part_span_min 的 axis 显式化：竖向结构用 y、横向长跨用 x/z 或 "xz"；
    组合体纵向长度用 part_union_span_min（显式纵向轴 + 排除不参与的子结构），
    禁止拿别的部位横向宽度冒充机身/纵向长度。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.e2e_assert import (  # noqa: E402
    _2d_components, _enclosed_or_walled_interior, _layer_solid, _part_cells_from_boxes,
    _spans_both_sides, _colored_cells, assert_generic, draw_request_count, final_gate_state,
    load_run, review_with_source,
)
from tools.e2e_cases_20 import find_case  # noqa: E402
from legogod.geometry import solid_cells_of_model  # noqa: E402
from legogod.plan_scale import parse_target_blocks  # noqa: E402

SLOPE_CHARS = set("\\/^vbdpq")

# 需求达标档冻结容差（Lead 冻结 2026-11-03）：bricks/targetBlocks ≥ 0.5 才算目标块数达标。
TARGET_RATIO_MIN = 0.5

# 当前能力回归档参考（2026-11-02 batch2 基线，只记录不判失败）：
# 交付体素中位 650、规划预估体素中位 705、体素/零件比中位 7.98（范围 3.90–9.19）。
BASELINE_VOXELS_MEDIAN = 650
BASELINE_PLANNED_VOXELS_MEDIAN = 705
BASELINE_VOXELS_PER_PIECE = 7.98
BASELINE_VOXELS_PER_PIECE_RANGE = [3.90, 9.19]
BASELINE_BRICKS_RATIO_MEDIAN = 0.29

# 模型空间 6 邻接：用于「子件是否真正搭在主体上」的空间邻接判定。
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


# ---------------------------------------------------------------- 通用小工具
def _parts(model):
    return model.get("parts") or []


def _cells_of_part(part):
    """部位占用体素：优先 boxes；只有 voxels 计数时返回空集（几何检查会跳过并给提示）。"""
    return _part_cells_from_boxes(part)


def _hit_parts(model, patterns):
    """按 id/名称关键词命中部位列表。"""
    return [p for p in _parts(model)
            if any(k in str(p.get("id", "")).lower() or k in str(p.get("name", ""))
                   for k in patterns)]


def _part_cells_by_pattern(model, patterns):
    hits = _hit_parts(model, patterns)
    cells = set()
    for p in hits:
        cells |= _cells_of_part(p)
    return hits, cells


def _solid(model):
    return solid_cells_of_model(model)


def _neighbors6(cell):
    x, y, z = cell
    return ((x + 1, y, z), (x - 1, y, z), (x, y + 1, z),
            (x, y - 1, z), (x, y, z + 1), (x, y, z - 1))


def _span_on_axes(cells, axis):
    """显式轴跨度：axis 是 x/y/z 的任意组合（"xyz" 取三轴最大、"y" 只算竖向、"xz" 取水平最大）。

    返回 None 表示 axis 参数非法（只允许 x/y/z 字符）。
    """
    text = str(axis or "").lower()
    if not text or any(ch not in _AXIS_INDEX for ch in text):
        return None
    best = 0
    for ch in dict.fromkeys(text):
        idx = _AXIS_INDEX[ch]
        vals = [c[idx] for c in cells]
        best = max(best, max(vals) - min(vals) + 1)
    return best


def _target_blocks(desc):
    """从用户需求原文解析目标块数 N（冻结口径）；解析不到返回 None。

    单源：直接复用 legogod.plan_scale.parse_target_blocks，同时接受
    「目标 N 块」与「目标约 N 块」，杜绝 E2E 断言与生产口径分叉。
    """
    return parse_target_blocks(desc)


def _layer_cells(model):
    """{y: {(x, z): 设计字符}}（只用 layers rows，不看配色：涂黑/贴图不算几何）。"""
    out = {}
    for layer in model.get("layers") or []:
        y = layer.get("y")
        plane = {}
        for z, row in enumerate(layer.get("rows") or []):
            for x, ch in enumerate(row):
                if ch != ".":
                    plane[(x, z)] = ch
        out[y] = plane
    return out


def _solid_parts(model):
    return [p for p in _parts(model) if (p.get("role") or "solid") != "surface"]


def _slope_count(model):
    """斜面体素计数：以设计行里的坡字符为准（模型字段仅作后备）。"""
    n = 0
    for layer in model.get("layers") or []:
        for row in layer.get("rows") or []:
            n += sum(1 for ch in row if ch in SLOPE_CHARS)
    return n


def _layer_component_max(model):
    best = 0
    for layer in model.get("layers") or []:
        if layer.get("count"):
            comps = _2d_components(_layer_solid(model, layer["y"]))
            best = max(best, comps)
    return best


def _ground_envelope(model):
    y0 = _layer_solid(model, 0)
    if not y0:
        return None
    xs = [x for x, _ in y0]
    zs = [z for _, z in y0]
    return min(xs), max(xs), min(zs), max(zs)


def _part_counts(model):
    parts = _parts(model)
    solid = _solid_parts(model)
    return len(parts), len(solid), len(parts) - len(solid)


def _require_parts(model, errors, label, wanted, min_solid_cells=2):
    """部位存在性断言：命中部位必须非空（solid ≥2 格、surface ≥1 格，与门禁量级一致）。"""
    for want_name, patterns in wanted:
        hits = _hit_parts(model, patterns)
        if not hits:
            errors.append(f"{label}：部位清单缺少{want_name}")
            continue
        ok = False
        for p in hits:
            cells = int(p.get("voxels") or 0) if p.get("voxels") else len(_cells_of_part(p))
            need = 1 if (p.get("role") or "solid") == "surface" else min_solid_cells
            if cells >= need:
                ok = True
                break
        if not ok:
            errors.append(f"{label}：{want_name}部位体量不足或没有实体（特征被删除/退化为贴花）")


# ---------------------------------------------------------------- 几何/配色检查
_CHECKS = {}


def _check(name):
    def deco(fn):
        _CHECKS[name] = fn
        return fn
    return deco


@_check("layers_min")
def _c_layers_min(ctx, n):
    got = len(ctx["model"].get("layers") or [])
    return [] if got >= n else [f"层数不足：{got} < {n}（结构过于扁平）"]


@_check("slope_min")
def _c_slope_min(ctx, n):
    """斜面体素下限。案例 checks 已不再引用；函数留下，供单测证明达到阈值能通过、不足会失败。"""
    got = _slope_count(ctx["model"])
    return [] if got >= n else [f"斜面体素不足：{got} < {n}（收尖/坡屋顶/飞檐未真实成型）"]


@_check("surface_parts_min")
def _c_surface_parts_min(ctx, n):
    _total, _solid, surface = ctx["counts"]
    return [] if surface >= n else [f"表面涂装部位不足：{surface} < {n}"]


@_check("colors_distinct_min")
def _c_colors_distinct(ctx, n):
    chars = set(ctx["colored"].values())
    return [] if len(chars) >= n else [f"配色种类不足：{len(chars)} < {n}（颜色分区未成型）"]


@_check("color_ratio_min")
def _c_color_ratio_min(ctx, chars, ratio):
    colored = ctx["colored"]
    if not colored:
        return ["没有逐体素配色（colorRows 为空）"]
    hit = sum(1 for ch in colored.values() if ch in chars)
    got = hit / len(colored)
    return [] if got >= ratio else [
        f"指定色系占比不足：{hit}/{len(colored)} = {got:.2f} < {ratio:.2f}（涂装分区未成型）"]


def _ops_unrecorded(model):
    """算子数是否不可判定：ops 轨道但模型存档没有可用的 ops 列表。

    逐格补丁（revise_design）修订后主链不再持有算子列表，存档只剩 track="ops"
    与层数据（ops 丢键或为 null）——此时把「算子 0 个」当成复杂度不足是测量伪影，
    按未知处理（不判失败），由部位/体素/目标块数等可判定指标承担复杂度判定。
    """
    return model.get("track") == "ops" and model.get("ops") is None


@_check("cylinder_ops_min")
def _c_cylinder_ops_min(ctx, n):
    """圆柱体元算子下限（仅余案例保留；圆形类案例已改为结果几何检查）。"""
    if ctx["model"].get("track") != "ops" or _ops_unrecorded(ctx["model"]):
        return []  # 非算子轨道/算子未存档：按未知处理，不用 0 个算子冒充真实缺项

    def walk(ops):
        for op in ops or []:
            yield op
            if op.get("op") == "mirror":
                yield from walk(op.get("ops"))
    got = sum(1 for op in walk(ctx["model"].get("ops") or []) if op.get("op") == "cylinder")
    return [] if got >= n else [f"圆柱体元算子不足：{got} < {n}（圆形结构未用圆柱成型）"]


@_check("op_count_min")
def _c_op_count_min(ctx, n):
    track = ctx["model"].get("track")
    if track != "ops":
        return []  # 二维画稿兼容轨道没有算子，复杂度由部位/体素下限保证
    if _ops_unrecorded(ctx["model"]):
        return []  # 算子未存档（逐格补丁后）：按未知处理，不判失败
    got = len(ctx["model"].get("ops") or [])
    return [] if got >= n else [f"三维算子数不足：{got} < {n}（结构细节不足）"]


@_check("ground_components_min")
def _c_ground_components_min(ctx, n):
    if not ctx["model"].get("layers"):
        return ["模型没有层数据"]
    got = _2d_components(_layer_solid(ctx["model"], 0))
    return [] if got >= n else [f"y=0 底层连通块不足：{got} < {n}（接地部位未分立）"]


@_check("layer_components_min")
def _c_layer_components_min(ctx, n):
    got = _layer_component_max(ctx["model"])
    return [] if got >= n else [f"单层最大连通块不足：{got} < {n}（立柱/开间未真实分离）"]


@_check("part_span_min")
def _c_part_span_min(ctx, patterns, n, axis="xz"):
    """部位实体在显式轴向上的跨度下限。

    axis 可写 x/y/z 的任意组合，调用点必须按语义显式声明：
      竖向结构（长颈、塔身）用 "y"；横向长跨（机身、气囊、尾梁）用 "x"/"z"/"xz"；
      组合体纵向长度另用 part_union_span_min，不能用机翼横向宽度冒充。
    默认 "xz" 保留旧的「水平最大跨度」口径，仅为未迁移的调用点（C21/C22/G 组）兼容；
    新写的 C/H 案例必须显式给 axis。
    """
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证长跨特征）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据（boxes 为空）"]
    span = _span_on_axes(cells, axis)
    if span is None:
        return [f"part_span_min 轴参数非法：{axis!r}（只能是 x/y/z 的组合）"]
    return [] if span >= n else [
        f"部位 {patterns} 在轴 {axis} 上跨度 {span} < {n}（长跨结构未成型）"]


@_check("part_union_span_min")
def _c_part_union_span_min(ctx, include, exclude, axis, n):
    """组合体：include 部位并集减去 exclude 部位后，在显式纵向轴上的跨度下限。

    与 part_span_min 的区别：并集可以跨多个真实子件（如轨道器+机头+机翼），但必须显式
    排除不参与该纵向长度的子结构（如外储箱/助推器），且 axis 显式声明为纵向轴，
    防止用机翼横向宽度或整机高度冒充组合体纵向长度。
    """
    inc_hits, inc_cells = _part_cells_by_pattern(ctx["model"], include)
    _exc_hits, exc_cells = _part_cells_by_pattern(ctx["model"], exclude)
    if not inc_hits:
        return [f"未找到组合体组成部位 {include}（无法验证纵向长度）"]
    if not inc_cells:
        return [f"组合体组成部位 {include} 缺少几何体素数据"]
    union = inc_cells - exc_cells
    if not union:
        return [f"组合体并集为空：include {include} 的体素全部被 exclude {exclude} 覆盖"]
    span = _span_on_axes(union, axis)
    if span is None:
        return [f"part_union_span_min 轴参数非法：{axis!r}（只能是 x/y/z 的组合）"]
    return [] if span >= n else [
        f"组合体（{include}，排除 {exclude}）在轴 {axis} 的纵向跨度 {span} < {n}"
        f"（不能用横向宽度或排除件冒充纵向长度）"]


@_check("part_min_volume")
def _c_part_min_volume(ctx, patterns, min_cells, member_patterns=None, min_share=None):
    """本体最小体量 + 本体占「本体∪附属子件」的体量比例下限。

    阈值依据（H10 轨道器）：≥40 体素 = 组合体目标 400 块的 1/10（轨道器是需求点名的
    四个主结构之一，不能是贴片）；本体占比 ≥50% = 本体体量必须大于附属细节合计，
    防止「小球挂大翼」的主次颠倒。
    """
    body_hits = _hit_parts(ctx["model"], patterns)
    if not body_hits:
        return [f"未找到本体部位 {patterns}（无法验证本体体量）"]
    body_cells, body = max(((_cells_of_part(p), p) for p in body_hits),
                           key=lambda item: len(item[0]))
    if not body_cells:
        return [f"本体部位 {body.get('id')} 缺少几何体素数据"]
    errs = []
    if len(body_cells) < min_cells:
        errs.append(f"本体 {body.get('id')} 体量 {len(body_cells)} < {min_cells}"
                    f"（本体过小，不足以承载点名的子特征）")
    if member_patterns and min_share is not None:
        _mh, members = _part_cells_by_pattern(ctx["model"], member_patterns)
        union = len(body_cells | members)
        share = (len(body_cells) / union) if union else 0.0
        if share < min_share:
            errs.append(f"本体占组合体体量 {share:.0%} < {min_share:.0%}"
                        f"（附属子件比本体还大，主次颠倒）")
    return errs


@_check("parts_adjacent_min")
def _c_parts_adjacent_min(ctx, patterns_a, patterns_b, min_contacts=1):
    """两组部位的体素 6-邻接接触面对数下限。

    用于「前腿搭着绣球」「机头/机翼搭在轨道器本体上」这类空间关系：名称存在但几何上
    悬空/分离不算，涂装贴图更不算。
    """
    hits_a, cells_a = _part_cells_by_pattern(ctx["model"], patterns_a)
    hits_b, cells_b = _part_cells_by_pattern(ctx["model"], patterns_b)
    if not hits_a:
        return [f"未找到部位 {patterns_a}（无法验证空间邻接）"]
    if not hits_b:
        return [f"未找到部位 {patterns_b}（无法验证空间邻接）"]
    if not cells_a or not cells_b:
        return [f"部位 {patterns_a}/{patterns_b} 缺少几何体素数据"]
    contacts = sum(1 for cell in cells_a for nb in _neighbors6(cell) if nb in cells_b)
    return [] if contacts >= min_contacts else [
        f"部位 {patterns_a} 与 {patterns_b} 的体素 6-邻接接触面 {contacts} < {min_contacts}"
        f"（空间上未真实搭接）"]


@_check("part_raised_above")
def _c_part_raised_above(ctx, patterns, ref_patterns, min_gap=1):
    """部件整体位于参照部件上方（高举/顶部姿态），用于替代无意义的轴向跨度。

    例：自由女神像「右臂高举火炬」——火炬最低层必须高于手臂最高层，否则就是平举/放低。
    """
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    ref_hits, ref_cells = _part_cells_by_pattern(ctx["model"], ref_patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证高举姿态）"]
    if not ref_hits:
        return [f"未找到参照部位 {ref_patterns}（无法验证高举姿态）"]
    if not cells or not ref_cells:
        return [f"部位 {patterns}/{ref_patterns} 缺少几何体素数据"]
    low = min(c[1] for c in cells)
    ref_high = max(c[1] for c in ref_cells)
    gap = low - ref_high
    return [] if gap >= min_gap else [
        f"部位 {patterns} 最低层 y={low} 未高于参照部位 {ref_patterns} 最高层 y={ref_high}"
        f"（差 {gap} < {min_gap}，未高举）"]


@_check("red_band_alternating")
def _c_red_band_alternating(ctx, patterns, red_chars="R", white_chars="W",
                            min_bands=2, min_ring_ratio=0.8):
    """红色连续环带 + 红白沿高度交替（C05 灯塔）。

    判据（结果几何，不统计红格总数、不要求部位名叫「环带」）：
      1) 命中部位中体量最大者作为塔身宿主；
      2) 某层宿主截面的外表面边界格中红格占比 ≥min_ring_ratio 且层内红格 4-连通为 1 块
         → 该层红色环带沿环向连续；零散红格/单侧涂装不算；
      3) 连续环带层组成 ≥min_bands 条红带，相邻红带之间至少隔 1 个宿主层且该间隔层有白色格
         → 红白沿高度交替。
    """
    model = ctx["model"]
    colors = ctx["colored"]
    hits = _hit_parts(model, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证红色环带）"]
    host = max(hits, key=lambda p: len(_cells_of_part(p)))
    host_cells = _cells_of_part(host)
    if not host_cells:
        return [f"部位 {host.get('id')} 缺少几何体素数据"]
    red = set(red_chars or "")
    white = set(white_chars or "")
    if not red:
        return ["red_band_alternating 未给出红色字符"]
    ys = sorted({c[1] for c in host_cells})
    band_y = []
    layer_notes = {}
    for y in ys:
        plane = {(x, z) for (x, yy, z) in host_cells if yy == y}
        boundary = {(x, z) for (x, z) in plane
                    if any(nb not in plane for nb in ((x + 1, z), (x - 1, z),
                                                      (x, z + 1), (x, z - 1)))}
        reds = {(x, z) for (x, z) in plane if colors.get((x, y, z)) in red}
        if not reds or not boundary:
            continue
        comps = _2d_components(reds)
        ratio = len(reds & boundary) / len(boundary)
        if comps == 1 and ratio >= min_ring_ratio and len(reds) >= 3:
            band_y.append(y)
        else:
            layer_notes[y] = (len(reds), comps, ratio)
    if not band_y:
        detail = "；".join(f"y={y} 红 {n} 格 {comps} 块 边界占比 {r:.0%}"
                          for y, (n, comps, r) in sorted(layer_notes.items())[:4])
        return [f"没有形成红色连续环带：塔身外表面红格未沿环向连通成带"
                f"（红格总数不做数；{detail or '无红格'}）"]
    groups = [[band_y[0]]]
    for y in band_y[1:]:
        if y == groups[-1][-1] + 1:
            groups[-1].append(y)
        else:
            groups.append([y])
    if len(groups) < min_bands:
        return [f"红色环带 {len(groups)} 条 < {min_bands}（环带不足，未沿高度交替）"]
    for prev, cur in zip(groups, groups[1:]):
        gap = [y for y in ys if prev[-1] < y < cur[0]]
        if not gap:
            return [f"红色环带 y={prev[-1]}→{cur[0]} 相邻粘连（之间没有白色带，未红白交替）"]
        has_white = any(colors.get((x, y, z)) in white
                        for y in gap for (x, yy, z) in host_cells if yy == y)
        if not has_white:
            return [f"红色环带之间 y={gap} 没有白色带（未红白交替）"]
    return []


@_check("negative_space_passage")
def _c_negative_space_passage(ctx, patterns, axis, min_height=3, min_lintel=1,
                              center_division=3):
    """门洞负空间贯通（C07 牌坊明间门洞）。

    判据（用 layers rows 的负空间，涂黑/贴图不算）：
      1) 命中部位定义结构包络；沿 axis（"x"/"z"；"xz" 表示两个水平方向任一即可）
         存在从结构一侧贯通到另一侧的连续空腔（逐层负空间 6-连通/直通判定，不用颜色）；
      2) 贯通位置落在结构中间 1/center_division 宽度内（明间中轴，侧间开洞不算）；
      3) 贯通高度连续 ≥min_height 层；
      4) 贯通段上方中间明间有实体（门楣/额枋），不是整段缺墙。
    """
    axis = str(axis).lower()
    axes = [axis] if axis in ("x", "z") else (["x", "z"] if axis in ("xz", "auto", "both") else [])
    if not axes:
        return [f"negative_space_passage 轴参数非法：{axis!r}（只能是 x/z/xz）"]
    errors = []
    for single in axes:
        errs = _passage_errors(ctx, patterns, single, min_height, min_lintel,
                               center_division)
        if not errs:
            return []
        errors.extend(f"[{single} 方向] {e}" for e in errs)
    return errors


def _passage_errors(ctx, patterns, axis, min_height, min_lintel, center_division):
    """单一通行方向的门洞负空间贯通判定（供 negative_space_passage 复用）。"""
    model = ctx["model"]
    solid = ctx["solid"]
    hits, struct = _part_cells_by_pattern(model, patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证门洞）"]
    if not struct:
        return [f"部位 {patterns} 缺少几何体素数据"]
    xs = [c[0] for c in struct]
    ys = [c[1] for c in struct]
    zs = [c[2] for c in struct]
    x0, x1, y0, y1, z0, z1 = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    grid = model.get("grid") or {}
    if axis == "x":
        across_lo, across_hi = z0, z1
        pass_lo, pass_hi = x0, x1
        pass_limit = int(grid.get("w") or (x1 + 2))

        def cell_of(p, y, a):
            return (p, y, a)
    else:
        across_lo, across_hi = x0, x1
        pass_lo, pass_hi = z0, z1
        pass_limit = int(grid.get("d") or (z1 + 2))

        def cell_of(p, y, a):
            return (a, y, p)
    p_min, p_max = max(0, pass_lo - 1), min(pass_limit - 1, pass_hi + 1)
    span = across_hi - across_lo
    if span < center_division:
        return [f"结构横向宽度 {span + 1} 格不足以区分明间（按 {center_division} 等分）"]
    lo = across_lo + span / center_division
    hi = across_hi - span / center_division
    through = {}
    for y in range(y0, y1 + 1):
        cols = [a for a in range(across_lo, across_hi + 1)
                if lo - 1e-9 <= a <= hi + 1e-9
                and all(cell_of(p, y, a) not in solid for p in range(p_min, p_max + 1))]
        if cols:
            through[y] = cols
    if not through:
        return [f"门洞负空间未贯通：结构中间明间沿 {axis} 方向不存在从一侧到另一侧的空腔"
                f"（涂黑/实心填充不算）"]
    run_ys = sorted(through)
    best_start = best_end = cur_start = prev = run_ys[0]
    for y in run_ys[1:]:
        if y == prev + 1:
            prev = y
            continue
        if prev - cur_start > best_end - best_start:
            best_start, best_end = cur_start, prev
        cur_start = prev = y
    if prev - cur_start > best_end - best_start:
        best_start, best_end = cur_start, prev
    height = best_end - best_start + 1
    if height < min_height:
        return [f"门洞负空间贯通高度 {height} < {min_height}（门洞太矮或仅单层开洞）"]
    lintel = sum(1 for a in range(across_lo, across_hi + 1)
                 if lo - 1e-9 <= a <= hi + 1e-9
                 for p in range(pass_lo, pass_hi + 1)
                 if cell_of(p, best_end + 1, a) in solid)
    if lintel < min_lintel:
        return [f"门洞上沿缺失：贯通段顶 y={best_end} 上方中间明间没有实体"
                f"（无门楣/额枋，等于整段缺墙）"]
    return []


@_check("eave_slope_overhang")
def _c_eave_slope_overhang(ctx, roof_patterns, support_patterns, min_overhang=1,
                           min_slope_cells=8, min_edge_slopes=2):
    """飞檐：屋顶斜面 + 真实出挑 + 外缘向外下坡方向证据（C07）。

    判据：
      1) 屋顶部位相对支承部位（柱等）在水平方向有 ≥min_overhang 格出挑；
      2) 屋顶部位范围内的斜面体素 ≥min_slope_cells（飞檐斜面真实成型，非平屋顶）；
      3) 出挑方向的屋顶外缘存在朝外下坡的斜面格（与 wedge 栅格化方向一致：
         -x→'/'、+x→'\\'、-z→'v'、+z→'^'），数量 ≥min_edge_slopes（翘角/出挑方向可辨）。
    """
    model = ctx["model"]
    roof_hits, roof = _part_cells_by_pattern(model, roof_patterns)
    sup_hits, support = _part_cells_by_pattern(model, support_patterns)
    if not roof_hits:
        return [f"未找到屋顶部位 {roof_patterns}（无法验证飞檐）"]
    if not roof:
        return [f"屋顶部位 {roof_patterns} 缺少几何体素数据"]
    if not sup_hits or not support:
        return [f"未找到支承部位 {support_patterns}（无法验证出挑）"]
    rx0, rx1 = min(c[0] for c in roof), max(c[0] for c in roof)
    rz0, rz1 = min(c[2] for c in roof), max(c[2] for c in roof)
    sx0, sx1 = min(c[0] for c in support), max(c[0] for c in support)
    sz0, sz1 = min(c[2] for c in support), max(c[2] for c in support)
    overhang = {"-x": sx0 - rx0, "+x": rx1 - sx1, "-z": sz0 - rz0, "+z": rz1 - sz1}
    errs = []
    if max(overhang.values()) < min_overhang:
        errs.append(f"屋顶相对支承没有出挑（最大出挑 {max(overhang.values())} < {min_overhang}）："
                    f"飞檐未真实挑出")
    slope_chars = {}
    for layer in model.get("layers") or []:
        y = layer.get("y")
        for z, row in enumerate(layer.get("rows") or []):
            for x, ch in enumerate(row):
                if ch in SLOPE_CHARS and (x, y, z) in roof:
                    slope_chars[(x, y, z)] = ch
    if len(slope_chars) < min_slope_cells:
        errs.append(f"屋顶区域斜面体素 {len(slope_chars)} < {min_slope_cells}（飞檐斜面未成型）")
    edge_evidence = 0
    if overhang["-x"] >= min_overhang:
        edge_evidence += sum(1 for (x, y, z), ch in slope_chars.items()
                             if x == rx0 and ch == "/")
    if overhang["+x"] >= min_overhang:
        edge_evidence += sum(1 for (x, y, z), ch in slope_chars.items()
                             if x == rx1 and ch == "\\")
    if overhang["-z"] >= min_overhang:
        edge_evidence += sum(1 for (x, y, z), ch in slope_chars.items()
                             if z == rz0 and ch == "v")
    if overhang["+z"] >= min_overhang:
        edge_evidence += sum(1 for (x, y, z), ch in slope_chars.items()
                             if z == rz1 and ch == "^")
    if edge_evidence < min_edge_slopes:
        errs.append(f"出挑边缘缺少向外下坡的斜面方向证据（外缘斜面格 {edge_evidence}"
                    f" < {min_edge_slopes}）：翘角方向不可辨")
    return errs


@_check("hub_contrast_adjacent")
def _c_hub_contrast_adjacent(ctx, wheel_patterns, tire_chars, hub_chars,
                             min_hub_per_part=1, min_adjacent=1):
    """轮毂：必须与轮胎异色、有外露面、且与轮胎体素相邻（C10）。

    逐轮组检查（前轮/后轮等命中部位各自都要有轮毂），拒绝「轮毂与轮胎同色」的涂装冒充
    和「轮毂内埋」的不可见细节；仅统计异色格总数不足以证明。
    """
    model = ctx["model"]
    colors = ctx["colored"]
    solid = ctx["solid"]
    tire = set(tire_chars or "")
    hub = set(hub_chars or "")
    hits = _hit_parts(model, wheel_patterns)
    if not hits:
        return [f"未找到部位 {wheel_patterns}（无法验证轮毂）"]
    if not tire or not hub:
        return ["hub_contrast_adjacent 未给出轮胎/轮毂颜色字符"]
    errs = []
    total_hub = 0
    for part in hits:
        cells = _cells_of_part(part)
        if not cells:
            errs.append(f"部位 {part.get('id')} 缺少几何体素数据（无法验证轮毂）")
            continue
        hub_cells = {c for c in cells if colors.get(c) in hub}
        tire_cells = {c for c in cells if colors.get(c) in tire}
        total_hub += len(hub_cells)
        label = f"部位 {part.get('id')}"
        if not tire_cells:
            errs.append(f"{label} 缺少轮胎主体色 {sorted(tire)}")
        if len(hub_cells) < min_hub_per_part:
            errs.append(f"{label} 轮毂异色格 {len(hub_cells)} < {min_hub_per_part}"
                        f"（轮毂与轮胎同色或缺失，涂装冒充不算）")
            continue
        adjacent = sum(1 for c in hub_cells if any(nb in tire_cells for nb in _neighbors6(c)))
        if adjacent < min_adjacent:
            errs.append(f"{label} 轮毂与轮胎体素不相邻（接触 {adjacent} < {min_adjacent}）")
        exposed = sum(1 for c in hub_cells if any(nb not in solid for nb in _neighbors6(c)))
        if exposed < 1:
            errs.append(f"{label} 轮毂全部内埋（外露面 0，不可见）")
    if total_hub < min_hub_per_part * len([p for p in hits if _cells_of_part(p)]):
        return errs or [f"轮毂异色格总数 {total_hub} 不足"]
    return errs


@_check("circular_ring_min")
def _c_circular_ring_min(ctx, patterns, min_sectors=8, max_radial_cv=0.35,
                         max_inner_ratio=0.2):
    """大圆环结果几何检查（H08 摩天轮）。

    判据：环类部位在最大两个跨度张成的平面上的投影，1) 8 个 45° 扇区全周覆盖；
    2) 格点半径变异系数 ≤max_radial_cv（近似同一圆周）；3) 中心不填实
    （半径 < 0.5 均值的格占比 ≤max_inner_ratio，圆盘不是圆环）。
    """
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证圆环）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据"]
    spans = sorted(((max(c[idx] for c in cells) - min(c[idx] for c in cells) + 1, idx)
                    for idx in (0, 1, 2)), reverse=True)
    if spans[0][0] <= 0 or spans[1][0] <= 0:
        return [f"部位 {patterns} 投影尺寸为 0，无法验证圆环"]
    if spans[0][0] < spans[1][0] * 0.5:
        return [f"部位 {patterns} 投影两轴跨度 {spans[0][0]}×{spans[1][0]} 差距过大"
                f"（不是圆环平面）"]
    a1, a2 = spans[0][1], spans[1][1]
    pts = [(c[a1], c[a2]) for c in cells]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    radii = []
    sectors = set()
    for x, y in pts:
        dx, dy = x - cx, y - cy
        radii.append(math.hypot(dx, dy))
        sectors.add(int(((math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0) // 45))
    errs = []
    if len(sectors) < min_sectors:
        errs.append(f"圆环全周覆盖扇区 {len(sectors)}/8 < {min_sectors}（轮廓不完整）")
    mean_r = sum(radii) / len(radii)
    if mean_r <= 0:
        return errs + [f"部位 {patterns} 投影退化为一点，不是圆环"]
    cv = (sum((r - mean_r) ** 2 for r in radii) / len(radii)) ** 0.5 / mean_r
    if cv > max_radial_cv:
        errs.append(f"格点半径变异系数 {cv:.2f} > {max_radial_cv:.2f}"
                    f"（不在近似同一圆周上，不是圆环）")
    inner = sum(1 for r in radii if r < 0.5 * mean_r)
    if inner / len(radii) > max_inner_ratio:
        errs.append(f"中心被填实（内圈格 {inner}/{len(radii)} = {inner / len(radii):.0%}"
                    f" > {max_inner_ratio:.0%}，是圆盘不是圆环）")
    return errs


@_check("curved_roof_profile")
def _c_curved_roof_profile(ctx, patterns, min_slope_cells=8, min_tiers=3):
    """弧形/层叠收分屋顶轮廓（H02 贝壳屋顶）。

    判据：1) 屋顶部位范围内斜面体素 ≥min_slope_cells（弧形轮廓用斜面砖收出）；
    2) 屋顶各层截面尺寸（x/z 跨度组合）档位 ≥min_tiers（层叠/收分，不是单层平箱体）。
    """
    model = ctx["model"]
    hits, roof = _part_cells_by_pattern(model, patterns)
    if not hits:
        return [f"未找到屋顶部位 {patterns}（无法验证弧形轮廓）"]
    if not roof:
        return [f"屋顶部位 {patterns} 缺少几何体素数据"]
    slope = 0
    for layer in model.get("layers") or []:
        y = layer.get("y")
        for z, row in enumerate(layer.get("rows") or []):
            for x, ch in enumerate(row):
                if ch in SLOPE_CHARS and (x, y, z) in roof:
                    slope += 1
    sizes = set()
    for y in {c[1] for c in roof}:
        xs = [c[0] for c in roof if c[1] == y]
        zs = [c[2] for c in roof if c[1] == y]
        sizes.add((max(xs) - min(xs) + 1, max(zs) - min(zs) + 1))
    errs = []
    if slope < min_slope_cells:
        errs.append(f"屋顶区域斜面体素 {slope} < {min_slope_cells}"
                    f"（弧形轮廓未用斜面砖收出）")
    if len(sizes) < min_tiers:
        errs.append(f"屋顶各层截面尺寸档位 {len(sizes)} < {min_tiers}"
                    f"（没有层叠/弧形收分轮廓）")
    return errs


@_check("cigar_taper_min")
def _c_cigar_taper_min(ctx, patterns, min_length=10, min_elongation=2.0,
                       max_end_ratio=0.6):
    """雪茄形/圆端长条结果几何（C11 飞艇气囊）。

    判据：1) 长轴跨度 ≥min_length；2) 长轴/次轴跨度比 ≥min_elongation（细长而非方块）；
    3) 两端端面体素 ≤ 最大截面 ×max_end_ratio（两端收分，圆头/雪茄形）。
    """
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证雪茄形）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据"]
    spans = sorted(((max(c[idx] for c in cells) - min(c[idx] for c in cells) + 1, idx)
                    for idx in (0, 1, 2)), reverse=True)
    long_span, long_idx = spans[0]
    second = spans[1][0]
    slices = {}
    for c in cells:
        slices.setdefault(c[long_idx], []).append(c)
    counts = [len(v) for _k, v in sorted(slices.items())]
    mid = max(counts)
    first, last = counts[0], counts[-1]
    errs = []
    if long_span < min_length:
        errs.append(f"长轴跨度 {long_span} < {min_length}（长度不足）")
    if second and long_span < min_elongation * second:
        errs.append(f"长轴/次轴跨度比 {long_span / second:.2f} < {min_elongation}"
                    f"（不是细长雪茄形）")
    if mid and max(first, last) / mid > max_end_ratio:
        errs.append(f"两端未收分（端面体素 {first}/{last} vs 最大截面 {mid}，"
                    f"比值 {max(first, last) / mid:.2f} > {max_end_ratio}）：不是雪茄形圆端")
    return errs


@_check("s_curve_min")
def _c_s_curve_min(ctx, patterns, min_vertical_span=4, min_lateral_drift=1.0,
                   min_turns=1):
    """S 形弯曲结果几何（H05 天鹅长颈）。

    判据：1) 竖向跨度 ≥min_vertical_span（长颈）；2) 逐层质心的侧向偏移 ≥min_lateral_drift；
    3) 偏移方向反转 ≥min_turns 次（S 形至少一次反向）。直柱形只有偏移不反转时拒绝。
    """
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证 S 形长颈）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据"]
    ys = sorted({c[1] for c in cells})
    if not ys:
        return [f"部位 {patterns} 没有体素"]
    vertical_span = ys[-1] - ys[0] + 1
    best = None
    for idx, label in ((0, "x"), (2, "z")):
        centroids = []
        for y in ys:
            pts = [c for c in cells if c[1] == y]
            centroids.append(sum(c[idx] for c in pts) / len(pts))
        drift = max(centroids) - min(centroids)
        diffs = [centroids[i + 1] - centroids[i] for i in range(len(centroids) - 1)]
        signs = [d for d in diffs if abs(d) > 1e-9]
        turns = sum(1 for i in range(len(signs) - 1) if signs[i] * signs[i + 1] < 0)
        if best is None or drift > best[0]:
            best = (drift, turns, label)
    errs = []
    if vertical_span < min_vertical_span:
        errs.append(f"竖向跨度 {vertical_span} < {min_vertical_span}（不够长颈）")
    drift, turns, label = best if best else (0.0, 0, "-")
    if drift < min_lateral_drift:
        errs.append(f"侧向最大偏移 {drift:.2f} < {min_lateral_drift}（直柱形，不是 S 形弯曲）")
    if turns < min_turns:
        errs.append(f"偏移方向反转 {turns} 次 < {min_turns}（只有单向弯，不是 S 形）")
    return errs


@_check("part_spans_two_axes")
def _c_part_spans_two_axes(ctx, patterns, n):
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据"]
    span_x = max(c[0] for c in cells) - min(c[0] for c in cells) + 1
    span_z = max(c[2] for c in cells) - min(c[2] for c in cells) + 1
    if span_x >= n and span_z >= n:
        return []
    return [f"部位 {patterns} 未在 x/z 两个轴向展开（{span_x}×{span_z}，需各 ≥{n}；十字风叶未成型）"]


@_check("part_overhang_min")
def _c_part_overhang_min(ctx, patterns, n):
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证悬挑）"]
    if not cells:
        return [f"部位 {patterns} 缺少几何体素数据"]
    env = _ground_envelope(ctx["model"])
    if env is None:
        return ["y=0 底层为空，无法计算悬挑"]
    bx0, bx1, bz0, bz1 = env
    overhang = max(bx0 - min(c[0] for c in cells), max(c[0] for c in cells) - bx1,
                   bz0 - min(c[2] for c in cells), max(c[2] for c in cells) - bz1)
    return [] if overhang >= n else [
        f"部位 {patterns} 超出底层包络仅 {overhang} 格 < {n}（悬挑/工作装置未真实伸出）"]


@_check("part_box_count_min")
def _c_part_box_count_min(ctx, patterns, n):
    """成组独立几何块下限（多轮/多履带/双滑橇等）。

    车辆/机械案例里车轮常压在底层车架/铁轨上，y=0 连通块不必然分立；
    改用「部位几何块数量」验证成组结构真实成型（一个整块车身不算 4 个轮子）。
    """
    hits = _hit_parts(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（无法验证成组部件）"]
    boxes = sum(len(p.get("boxes") or []) for p in hits)
    return [] if boxes >= n else [
        f"部位 {patterns} 独立几何块仅 {boxes} < {n}（多轮/多履带等成组结构未成型）"]


@_check("paired_or_span")
def _c_paired_or_span(ctx, patterns):
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（成对结构缺失）"]
    if len(hits) >= 2 or _spans_both_sides(ctx["model"], cells):
        return []
    return [f"部位 {patterns} 只有 1 个且未横跨中轴（左右对称结构未成型）"]


@_check("both_sides")
def _c_both_sides(ctx, patterns):
    hits, cells = _part_cells_by_pattern(ctx["model"], patterns)
    if not hits:
        return [f"未找到部位 {patterns}（成对结构缺失）"]
    if len(hits) >= 2 or _spans_both_sides(ctx["model"], cells):
        return []
    return [f"部位 {patterns} 只有单侧（左右成对结构未成型）"]


@_check("enclosed_interior_min")
def _c_enclosed_interior_min(ctx, n):
    got = _enclosed_or_walled_interior(ctx["model"])
    return [] if got >= n else [f"围合内部空腔 {got} < {n}（内部未中空/被填成实心块）"]


@_check("parts_min")
def _c_parts_min(ctx, n):
    total, _solid, _surface = ctx["counts"]
    return [] if total >= n else [f"部位总数不足：{total} < {n}"]


@_check("tiered_min")
def _c_tiered_min(ctx, n):
    counts = {L["count"] for L in ctx["model"].get("layers") or [] if L.get("count")}
    return [] if len(counts) >= n else [
        f"各层截面尺寸变化档位不足：{len(counts)} < {n}（没有逐层收分/出檐的塔身形制）"]


@_check("subassemblies_min")
def _c_subassemblies_min(ctx, n):
    got = len(ctx["solution"].get("subassemblies") or [])
    return [] if got >= n else [f"预拼子组件不足：{got} < {n}（悬吊特征未成型）"]


# ---------------------------------------------------------------- 断言入口
def _complexity_detail(case, model, counts):
    """需求达标档的复杂度明细（部位/立体部位/体素/算子）。"""
    total, solid, _surface = counts
    track = model.get("track")
    voxels = int(model.get("totalVoxels") or 0)
    ops = len(model.get("ops") or [])
    return {
        "parts": {"required": case.get("min_parts"), "actual": total,
                  "ok": total >= int(case.get("min_parts") or 0)},
        "solid_parts": {"required": case.get("min_solid_parts"), "actual": solid,
                        "ok": solid >= int(case.get("min_solid_parts") or 0)},
        "voxels": {"required": case.get("min_voxels"), "actual": voxels,
                   "ok": voxels >= int(case.get("min_voxels") or 0)},
        "ops": {"required": case.get("min_ops"), "actual": ops,
                "ok": ((ops >= int(case.get("min_ops") or 0)) if track == "ops"
                       and not _ops_unrecorded(model) else None)},
    }


def _complexity_errors(case, detail):
    """把复杂度明细转成需求达标档失败项（rows 轨道不强制算子数）。"""
    errs = []
    for key, label in (("parts", "部位数"), ("solid_parts", "立体部位数"),
                       ("voxels", "体素数")):
        item = detail[key]
        if item["ok"] is False:
            errs.append(f"复杂度未达设计下限：{label} {item['actual']} < {item['required']}")
    if detail["ops"]["ok"] is False:
        errs.append(f"复杂度未达设计下限：算子数 {detail['ops']['actual']} "
                    f"< {detail['ops']['required']}")
    return errs


def check_objects(record, model, solution, case, review_fallback=None):
    """对给定运行记录 + 模型/方案执行通用与案例专项断言，返回 (errors, metrics)。

    失败项全部来自需求达标档（requirement_tier）：通用底线（任务/最终门禁/统一校验/
    产物）、部位与特征几何断言、复杂度设计下限、目标块数比；
    当前能力回归档（regression_tier）只记录基线对照，不参与失败判定。

    review_fallback：旧 run 记录没有 review 时，从任务结果 result.review 补入，
    metrics.review_source 记录真实来源。
    """
    errors = []
    assert_generic(record, model, solution, errors)
    ctx = {"model": model, "solution": solution or {},
           "counts": _part_counts(model), "colored": _colored_cells(model),
           "solid": _solid(model)}
    label = f"{case['id']} {case['name']}"

    require_errors = []
    feature_checks = []
    complexity = _complexity_detail(case, model, ctx["counts"])
    target = _target_blocks(case.get("desc") or record.get("desc") or "")
    bricks = len((solution or {}).get("steps") or [])
    if record.get("ok"):
        _require_parts(model, require_errors, label, case.get("require_parts") or [])
        errors.extend(require_errors)
        for spec in case.get("checks") or []:
            name, args = spec[0], spec[1:]
            fn = _CHECKS.get(name)
            if fn is None:
                check_errors = [f"断言配置错误：未知检查 {name}"]
            else:
                try:
                    check_errors = list(fn(ctx, *args) or [])
                except (KeyError, TypeError, ValueError) as exc:  # 产物异常时给可读失败
                    check_errors = [f"检查 {name} 执行失败：{exc}"]
            feature_checks.append({"name": name, "ok": not check_errors,
                                   "errors": check_errors})
            errors.extend(check_errors)
        errors.extend(_complexity_errors(case, complexity))
        # 需求达标档：目标块数比（冻结容差 ≥50%）。
        if target:
            ratio = bricks / target
            if ratio < TARGET_RATIO_MIN:
                errors.append(f"需求达标档：实际零件 {bricks} / 目标 {target} = {ratio:.1%}"
                              f" < {TARGET_RATIO_MIN:.0%}（目标块数未达标）")
        # 过期高保真成功：最终模型哈希与评审哈希不同时不得判成功。
        # reviewStale=true 的定义保证「存在有效评审且最终稿与评审稿哈希不同」，
        # 因此任何成功记录只要该标记为真都不再是可信的最终成功（旧记录无该字段 → 未知，不误判）。
        outcome = record.get("outcome")
        review_stale = record.get("reviewStale") if "reviewStale" in record else None
        if review_stale is True:
            errors.append("最终产物评审已过期（reviewStale=true，评审稿与最终模型哈希不一致）："
                          "不得判成功")
    else:
        review_stale = record.get("reviewStale") if "reviewStale" in record else None
    outcome = record.get("outcome")

    review, review_source = review_with_source(record, review_fallback)
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    attempts = record.get("drawAttempts") or []
    voxels = int(model.get("totalVoxels") or 0)
    voxels_per_piece = (voxels / bricks) if bricks else None
    target_ratio = (bricks / target) if (target and record.get("ok")) else None
    # 规模指标同源核对：run/job 的 scaleMetrics 与 E2E 计算必须一致（同一比例、同一体素数）。
    # 旧记录 scaleMetrics 为空/缺失 → 只记 None，不误判；新记录不一致属于数据异常，判失败。
    server_scale = record.get("scaleMetrics") if isinstance(record.get("scaleMetrics"), dict) else None
    scale_consistency = None
    if server_scale:
        problems = []
        sm_target = server_scale.get("targetBlocks")
        if target and sm_target is not None and int(sm_target) != int(target):
            problems.append(f"targetBlocks={sm_target} != 需求目标 {target}")
        if record.get("ok"):
            sm_parts = server_scale.get("actualParts")
            sm_vox = server_scale.get("actualVoxels")
            sm_ratio = server_scale.get("targetBlocksRatio")
            if sm_parts is not None and int(sm_parts) != bricks:
                problems.append(f"actualParts={sm_parts} != 方案零件数 {bricks}")
            if sm_vox is not None and int(sm_vox) != voxels:
                problems.append(f"actualVoxels={sm_vox} != 模型体素数 {voxels}")
            if sm_ratio is not None and target_ratio is not None \
                    and abs(float(sm_ratio) - target_ratio) > 1e-9:
                problems.append(f"targetBlocksRatio={float(sm_ratio):.4f} != E2E 计算 {target_ratio:.4f}")
        scale_consistency = {"ok": not problems, "problems": problems}
        errors.extend([f"规模指标不同源（run/job 与 E2E 不一致）：{p}" for p in problems])
    gate_source, gate_ok, gate_errors = final_gate_state(record)
    replay_present = "finalGateReplay" in record
    replay = record.get("finalGateReplay") if replay_present else None

    requirement_tier = {
        "target_blocks": target, "bricks": bricks, "bricks_ratio": target_ratio,
        "target_blocks_ok": (target_ratio >= TARGET_RATIO_MIN) if target_ratio is not None else None,
        "require_parts": {"ok": not require_errors, "errors": require_errors},
        "feature_checks": feature_checks,
        "complexity": complexity,
        "final_gate_ok": gate_ok,
        "final_gate_source": gate_source,
        "review_stale_ok": (None if review_stale is None else not review_stale),
        "server_scale_metrics": server_scale,
        "server_scale_metrics_reason": record.get("scaleMetricsReason")
        if "scaleMetricsReason" in record else None,
        "scale_metrics_consistent": scale_consistency,
        "ok": not errors,
        "errors": list(errors),
    }
    regression_tier = {
        "baseline_voxels_median": BASELINE_VOXELS_MEDIAN,
        "baseline_planned_voxels_median": BASELINE_PLANNED_VOXELS_MEDIAN,
        "baseline_voxels_per_piece_median": BASELINE_VOXELS_PER_PIECE,
        "baseline_voxels_per_piece_range": list(BASELINE_VOXELS_PER_PIECE_RANGE),
        "baseline_bricks_ratio_median": BASELINE_BRICKS_RATIO_MEDIAN,
        "actual_voxels": voxels,
        "actual_bricks": bricks,
        "actual_voxels_per_piece": round(voxels_per_piece, 2) if voxels_per_piece else None,
        "voxels_vs_baseline_median": round(voxels / BASELINE_VOXELS_MEDIAN, 2),
        "voxels_per_piece_vs_baseline": (round(voxels_per_piece / BASELINE_VOXELS_PER_PIECE, 2)
                                         if voxels_per_piece else None),
        "note": "当前能力回归档只记录与 2026-11-02 基线的对比，不参与失败判定；"
                "失败项只来自 requirement_tier",
    }
    metrics = {
        "case": case["id"], "name": case["name"], "run_id": record.get("runId"),
        "task_ok": bool(record.get("ok")), "error": record.get("error"),
        "mode": record.get("mode"), "outcome": outcome, "track": model.get("track"),
        "parts": ctx["counts"][0], "solid_parts": ctx["counts"][1],
        "surface_parts": ctx["counts"][2],
        "voxels": voxels,
        "ops": len(model.get("ops") or []),
        "ops_recorded": not _ops_unrecorded(model),
        "slope_voxels": _slope_count(model),
        "layers": len(model.get("layers") or []),
        "grid": model.get("grid"),
        "pieces": bricks,
        "colors": len(set(ctx["colored"].values())),
        "gate_failed": bool(record.get("gateFailed") or record.get("gate_failed")),
        "gate_errors": record.get("gateErrors") or record.get("gate_errors") or [],
        "validation_ok": (solution or {}).get("validation", {}).get("ok")
        if isinstance((solution or {}).get("validation"), dict) else None,
        "review_overall": scores.get("overall"),
        "review_flag": record.get("reviewFlag"),
        "draw_attempts": len(attempts),
        "draw_requests": draw_request_count(attempts),
        "review": review,
        "review_source": review_source,
        # ---- 复杂度两层（失败项只来自需求达标档） ----
        "requirement_tier": requirement_tier,
        "regression_tier": regression_tier,
        # ---- 最终门禁重放、版本覆盖与评审可信度（缺失记未知） ----
        "final_gate_replay": replay,
        "final_gate_replay_reason": record.get("finalGateReplayReason")
        if "finalGateReplayReason" in record else None,
        "final_gate_source": gate_source,
        "final_gate_ok": gate_ok,
        "final_gate_replay_field_present": replay_present,
        "version_overwrites": record.get("versionOverwriteCount")
        if "versionOverwriteCount" in record else None,
        "review_stale": review_stale,
        "review_hash_missing": record.get("reviewHashMissing")
        if "reviewHashMissing" in record else None,
        # cylinder 计数只作观察：圆形/曲面类案例已改由结果几何检查判定。
        "observations": {
            "cylinder_ops": _cylinder_count(model),
            "note": "cylinder 算子数仅观察；圆形/曲面成型由 curved_roof_profile/"
                    "circular_ring_min/cigar_taper_min/s_curve_min 等结果几何检查判定",
        },
        "assertion_errors": errors,
        "assertion_ok": not errors,
    }
    return errors, metrics


def _cylinder_count(model):
    """观察指标：圆柱算子数（含 mirror 子算子）。"""
    def walk(ops):
        for op in ops or []:
            yield op
            if op.get("op") == "mirror":
                yield from walk(op.get("ops"))
    return sum(1 for op in walk(model.get("ops") or []) if op.get("op") == "cylinder")


def check_run(run_id, case_id=None, review_fallback=None):
    """读取 run 记录与最终产物并执行断言，返回 metrics dict。

    G 组（G01–G10 独立确认集）单源在 tools/e2e_cases_g.py，检查器在
    tools/e2e_assert_g.py：本入口按案例编号前缀分发，C/H 语义不变。
    review_fallback：任务结果 result.review（旧 run 记录没有 review 时补入）。
    """
    record, model, solution = load_run(run_id)
    case = find_case(case_id, desc=record.get("desc"))
    if case is None:
        try:
            from tools.e2e_cases_g import find_g_case
        except ImportError:
            find_g_case = None
        if find_g_case is not None:
            case = find_g_case(case_id, desc=record.get("desc"))
    if case is None:
        # 新增第三批 N01–N20：单源在 tools/e2e_cases_new20.py，断言口径沿用 G 组两档。
        try:
            from tools.e2e_cases_new20 import find_n_case
        except ImportError:
            find_n_case = None
        if find_n_case is not None:
            case = find_n_case(case_id, desc=record.get("desc"))
    if case is None:
        # R01–R10：2026-11-14 几何契约 A/B 的未参与开发新例，单源 tools/e2e_cases_r.py。
        try:
            from tools.e2e_cases_r import find_r_case
        except ImportError:
            find_r_case = None
        if find_r_case is not None:
            case = find_r_case(case_id, desc=record.get("desc"))
    if case is None:
        # M01–M20：快速/高保真双模式同题案例，单源 tools/e2e_cases_mode20.py。
        try:
            from tools.e2e_cases_mode20 import find_m_case
        except ImportError:
            find_m_case = None
        if find_m_case is not None:
            case = find_m_case(case_id, desc=record.get("desc"))
    if case is None:
        raise SystemExit(f"无法匹配案例：case_id={case_id!r} desc={str(record.get('desc'))[:60]!r}"
                         "（请显式给 --case，或确认需求原文与 tools/e2e_cases_20.py 一致）")
    case_id_upper = str(case.get("id", "")).upper()
    if case_id_upper.startswith("G"):
        from tools.e2e_assert_g import check_objects_g
        errors, metrics = check_objects_g(record, model, solution, case,
                                          review_fallback=review_fallback)
    elif case_id_upper.startswith("N"):
        from tools.e2e_assert_new20 import check_objects_n
        errors, metrics = check_objects_n(record, model, solution, case,
                                          review_fallback=review_fallback)
    elif case_id_upper.startswith("R"):
        from tools.e2e_assert_r import check_objects_r
        errors, metrics = check_objects_r(record, model, solution, case,
                                          review_fallback=review_fallback)
    elif case_id_upper.startswith("M"):
        # M01–M20：快速/高保真双模式同题案例，
        # 断言器复用本模块通用底线与检查原语，另加模式事实断言。
        from tools.e2e_assert_mode20 import check_objects_m
        errors, metrics = check_objects_m(record, model, solution, case,
                                          review_fallback=review_fallback)
    else:
        errors, metrics = check_objects(record, model, solution, case,
                                        review_fallback=review_fallback)
    metrics["desc"] = record.get("desc")
    return metrics


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_out = None
    case_id = None
    positional = []
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
        print("用法: python -m tools.e2e_assert_20 <run_id> [--case C01] [--json out.json]")
        return 2
    metrics = check_run(positional[0], case_id)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"案例 {metrics['case']} {metrics['name']} · run {metrics['run_id']} · "
          f"{'✅ 断言通过' if metrics['assertion_ok'] else '❌ 断言未通过'}")
    print(f"  任务成功={metrics['task_ok']} 轨道={metrics['track']} 部位={metrics['parts']}"
          f"(立体{metrics['solid_parts']}/涂装{metrics['surface_parts']}) "
          f"体素={metrics['voxels']} 算子={metrics['ops']} 斜面={metrics['slope_voxels']} "
          f"层={metrics['layers']} 零件={metrics['pieces']}")
    print(f"  门禁降级={metrics['gate_failed']} 最终门禁={metrics['final_gate_source']}"
          f"/{metrics['final_gate_ok']} 统一校验={metrics['validation_ok']} "
          f"评审={metrics['review_overall']} 评审标记={metrics['review_flag']} "
          f"draw 请求={metrics['draw_requests']}")
    # 需求达标档形态兼容：C/H 是 dict；G/N/R 是失败项列表（规模字段在 metrics 顶层）。
    tier = metrics.get("requirement_tier")
    tier = tier if isinstance(tier, dict) else {}
    if tier.get("target_blocks"):
        print(f"  需求达标档：目标块数 {tier['target_blocks']} 实际零件 {tier['bricks']} "
              f"比 {tier['bricks_ratio']:.1%}（≥{TARGET_RATIO_MIN:.0%} 为达标）")
    elif metrics.get("target_blocks") is not None:
        ratio = metrics.get("bricks_ratio")
        ratio_text = f"{ratio:.1%}" if isinstance(ratio, (int, float)) else "未知"
        print(f"  需求达标档：目标块数 {metrics['target_blocks']} 实际零件 {metrics.get('bricks')} "
              f"比 {ratio_text}（≥{TARGET_RATIO_MIN:.0%} 为达标；G/N/R 组形态）")
    reg = metrics.get("regression_tier") or {}
    print(f"  能力回归档（只记录）：体素/零件 {reg.get('actual_voxels_per_piece')} "
          f"vs 基线 {reg.get('baseline_voxels_per_piece_median')}；"
          f"体素 {reg.get('actual_voxels')} vs 基线中位 {reg.get('baseline_voxels_median')}")
    if metrics["assertion_errors"]:
        print("断言未通过项：")
        for e in metrics["assertion_errors"]:
            print(" -", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
