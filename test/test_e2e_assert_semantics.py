# -*- coding: utf-8 -*-
"""验收断言语义正反例测试（工作包 A.1）。

覆盖：
  1. part_span_min 三轴显式化：横向宽度不能冒充纵向长度；
  2. 组合体并集纵向跨度：排除外储箱/助推器后，仅机翼横向宽、纵向短的组合必须被拒；
  3. 负空间门洞：正例贯通通过，涂黑/填实/无门楣反例被拒；
  4. 红色连续环带 + 红白交替：断开、只有零散红格但总数够被拒；
  5. 轮毂异色/外露/与轮胎相邻：同色、内埋反例被拒；
  6. 前腿与绣球 6-邻接：空间不相邻被拒；
  7. 其他新增结果几何检查（S 形、圆环、弧形屋顶、雪茄收分、高举姿态）正反例；
  8. 最终门禁重放口径：重放为准、过程降级不单独判失败、旧记录兼容、缺失不误判；
  9. 过期评审、版本覆盖、两层复杂度 metrics（目标块数比 ≥50% 冻结容差）。
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tools import e2e_assert as e2e_assert_mod
from tools.e2e_assert_20 import _CHECKS, _target_blocks, check_objects
from tools.e2e_cases_20 import CASES, find_case
from tools.e2e_cases_batch2 import NEW_CASES
from tools.e2e_cases_extra import EXTRA_CASES

SLOPE = "\\"


# ---------------------------------------------------------------- 合成模型工具
def make_model(layers_rows, parts=None, ops=None, track="ops", color_rows=None):
    """由 rows 字符串列表构造最小模型；color_rows 为与层同形的颜色字符行列表。"""
    layers = []
    for y, rows in enumerate(layers_rows):
        d = len(rows)
        w = len(rows[0]) if d else 0
        cells = [[x, z] for z, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["m"], "color": None,
                       "colorRows": (color_rows or [None] * len(layers_rows))[y],
                       "count": len(cells)})
    return {"name": "测试模型", "grid": {"w": w, "d": d},
            "totalVoxels": sum(L["count"] for L in layers),
            "slopeVoxels": sum(sum(1 for ch in row if ch in "\\/^vbdpq")
                               for rows in layers_rows for row in rows),
            "layers": layers, "parts": parts or [], "ops": ops or [], "track": track}


def make_part(pid, name, role="solid", boxes=(), voxels=None):
    if not boxes:
        boxes = [{"x1": 0, "x2": 0, "z1": 0, "z2": 0, "y1": 0, "y2": 0}]
    total = voxels if voxels is not None else sum(
        (b["x2"] - b["x1"] + 1) * (b["z2"] - b["z1"] + 1) * (b["y2"] - b["y1"] + 1)
        for b in boxes)
    return {"id": pid, "name": name, "role": role, "voxels": total, "boxes": list(boxes)}


def box(x1, x2, z1, z2, y1=0, y2=0):
    return {"x1": x1, "x2": x2, "z1": z1, "z2": z2, "y1": y1, "y2": y2}


def ctx(model, solution=None):
    from tools.e2e_assert_20 import _colored_cells, _part_counts, _solid
    return {"model": model, "solution": solution or {"validation": {"ok": True}},
            "counts": _part_counts(model), "colored": _colored_cells(model),
            "solid": _solid(model)}


def run_check(name, model, *args):
    return _CHECKS[name](ctx(model), *args)


def make_case(case_id="T01", desc="测试需求：目标约 100 块积木", **overrides):
    case = {"id": case_id, "name": "测试案例", "desc": desc,
            "min_parts": 1, "min_solid_parts": 0, "min_voxels": 1, "min_ops": 0,
            "require_parts": [], "checks": []}
    case.update(overrides)
    return case


def steps(n):
    return [{"i": i} for i in range(n)]


def record(**overrides):
    base = {"ok": True, "runId": "test-run", "revision": 1, "artifacts": {},
            "outcome": "fidelity_degraded"}
    base.update(overrides)
    return base


def model_for_check_objects():
    """check_objects 用最小可过模型：1 层 2×2 实体 + 1 个立体部位。"""
    return make_model([["##", "##"]], parts=[make_part("body", "主体", boxes=[box(0, 1, 0, 1)])])


# ---------------------------------------------------------------- 1. 三轴跨度
class PartSpanAxisTest(unittest.TestCase):
    def test_each_axis_is_independent(self):
        # 实体 2(x) × 1(y) × 9(z)
        model = make_model([["#" * 9, "#" * 9]],
                           parts=[make_part("h", "艇体", boxes=[box(0, 1, 0, 8)])])
        self.assertEqual(run_check("part_span_min", model, ("艇体",), 9, "z"), [])
        self.assertTrue(run_check("part_span_min", model, ("艇体",), 9, "x"))
        self.assertTrue(run_check("part_span_min", model, ("艇体",), 3, "y"))
        # 单层实体的 y 跨度只有 1：y 轴断言 2 必须失败、1 才通过。
        self.assertTrue(run_check("part_span_min", model, ("艇体",), 2, "y"))
        self.assertEqual(run_check("part_span_min", model, ("艇体",), 1, "y"), [])
        # 组合轴取最大：xz 通过、y 不通过。
        self.assertEqual(run_check("part_span_min", model, ("艇体",), 9, "xz"), [])
        # 非法轴参数报配置错误（不静默通过）。
        self.assertTrue(run_check("part_span_min", model, ("艇体",), 1, "q"))

    def test_wing_width_cannot_fake_fuselage_length(self):
        """只有横向宽、纵向短的机翼：x 轴能过，纵向 y 必须不能过。"""
        model = make_model([["#" * 10]], parts=[make_part("w", "机翼", boxes=[box(0, 9, 0, 0)])])
        self.assertEqual(run_check("part_span_min", model, ("机翼",), 10, "x"), [])
        self.assertTrue(run_check("part_span_min", model, ("机翼",), 6, "y"))

    def test_default_axis_stays_legacy_horizontal(self):
        """未显式给 axis 时保留旧的水平最大跨度口径（C21/C22/G 组兼容）。"""
        vertical = make_model([["##"] for _ in range(5)],
                              parts=[make_part("v", "长颈", boxes=[box(0, 1, 0, 0, 0, 4)])])
        self.assertTrue(run_check("part_span_min", vertical, ("长颈",), 4))
        self.assertEqual(run_check("part_span_min", vertical, ("长颈",), 4, "y"), [])


# ---------------------------------------------------------------- 2. 组合体纵向跨度
class UnionSpanTest(unittest.TestCase):
    def _assembly(self, orbiter_y=(0, 3), tank_y=(0, 11)):
        parts = [
            make_part("orbiter", "轨道器", boxes=[box(4, 5, 4, 5, *orbiter_y)]),
            make_part("nose_cone", "圆钝机头", boxes=[box(4, 5, 4, 5, orbiter_y[1] + 1,
                                                        orbiter_y[1] + 1)]),
            make_part("wings", "三角机翼", boxes=[box(0, 9, 4, 4)]),
            # 外储箱/助推器与轨道器在空间上不重叠（z 不同），减少/排除它们才真实有效。
            make_part("external_tank", "外储箱", boxes=[box(4, 5, 6, 7, *tank_y)]),
            make_part("boosters", "固体助推器", boxes=[box(0, 1, 6, 7, *tank_y)]),
        ]
        return make_model([["#" * 12 for _ in range(12)] for _ in range(max(tank_y) + 1)],
                          parts=parts)

    def test_union_uses_longitudinal_axis_and_excludes_tank(self):
        model = self._assembly()
        include = ("轨道器", "orbiter", "机头", "nose", "机翼", "wing")
        exclude = ("外储箱", "储箱", "tank", "助推器", "booster")
        # 并集纵向（y）跨度 = 机头 y=4 到本体 y=3 → 5；外储箱虽高 12 但被排除。
        self.assertEqual(run_check("part_union_span_min", model, include, exclude, "y", 5), [])
        self.assertTrue(run_check("part_union_span_min", model, include, exclude, "y", 12))

    def test_short_longitudinal_but_wide_wings_rejected(self):
        """仅机翼横向宽（x=10）、纵向短（y=3+机头=4）→ 必须拒绝纵向断言。"""
        model = self._assembly(orbiter_y=(0, 2))
        include = ("轨道器", "orbiter", "机头", "nose", "机翼", "wing")
        exclude = ("外储箱", "储箱", "tank", "助推器", "booster")
        errors = run_check("part_union_span_min", model, include, exclude, "y", 8)
        self.assertTrue(any("纵向跨度" in e for e in errors), errors)
        # 若把外储箱也纳入 include 且不排除（伪组合体）：高度会造假通过，
        # 证明「排除外储箱/助推器」参数是必要的（否则整机高度冒充轨道器长度）。
        include_with_tank = include + ("外储箱", "储箱", "tank")
        self.assertEqual(run_check("part_union_span_min", model, include_with_tank,
                                   ("不存在",), "y", 12), [])

    def test_body_min_volume_and_share(self):
        model = self._assembly()
        # 本体 2×2×4 = 16 格，机头 2 + 机翼 10 → 本体占比 16/28 ≈ 57%。
        self.assertEqual(run_check("part_min_volume", model, ("轨道器", "orbiter"), 16,
                                   ("机头", "nose", "机翼", "wing"), 0.5), [])
        self.assertTrue(run_check("part_min_volume", model, ("轨道器", "orbiter"), 40,
                                  ("机头", "nose", "机翼", "wing"), 0.5))
        # 主次颠倒：机翼比本体大得多 → 占比不足必须拒绝。
        tiny = make_model([["#" * 12] for _ in range(12)], parts=[
            make_part("orbiter", "轨道器", boxes=[box(4, 5, 4, 5, 0, 1)]),
            make_part("wings", "三角机翼", boxes=[box(0, 11, 4, 4)]),
        ])
        self.assertTrue(run_check("part_min_volume", tiny, ("轨道器", "orbiter"), 4,
                                  ("机翼", "wing"), 0.5))


# ---------------------------------------------------------------- 3. 负空间门洞
class NegativeSpacePassageTest(unittest.TestCase):
    def _model(self, fill_middle=False, lintel=True):
        """两墩 + 中间贯通门洞；fill_middle=True 用实体填死门洞（涂黑在语义上同样不算空腔）。"""
        door_row = "##.###.##" if fill_middle else "##.....##"
        layers = [["#" * 9] * 7 if y == 0 else [door_row] * 7 for y in range(5)]
        if lintel:
            layers.append(["#########"] * 7)  # y=5 门楣/额枋
        else:
            layers.append([door_row] * 7)  # 整段缺墙：门洞上方没有门楣
        colors = [["K" * 9] * 7 for _ in layers] if fill_middle else None
        parts = [
            make_part("pier", "石柱", boxes=[box(0, 1, 0, 6, 0, 4),
                                              box(7, 8, 0, 6, 0, 4)]),
            make_part("base", "石基座", boxes=[box(0, 8, 0, 6, 0, 0)]),
        ]
        if lintel:
            parts.append(make_part("beam", "额枋", boxes=[box(0, 8, 0, 6, 5, 5)]))
        return make_model(layers, parts=parts, color_rows=colors)

    def test_real_opening_passes(self):
        model = self._model()
        self.assertEqual(run_check("negative_space_passage", model,
                                   ("柱", "基座", "column", "base"), "z", 3, 1, 3), [])

    def test_painted_or_filled_opening_rejected(self):
        model = self._model(fill_middle=True)
        errors = run_check("negative_space_passage", model,
                           ("柱", "基座", "column", "base"), "z", 3, 1, 3)
        self.assertTrue(errors, "把门洞涂黑/填实后必须判失败")
        self.assertTrue(any("未贯通" in e for e in errors), errors)

    def test_no_lintel_rejected(self):
        model = self._model(lintel=False)
        errors = run_check("negative_space_passage", model,
                           ("柱", "基座", "column", "base"), "z", 3, 1, 3)
        self.assertTrue(errors, "门洞上方缺门楣必须判失败")

    def test_rotated_passage_passes_with_auto_axis(self):
        """结构旋转 90°（通行方向沿 x）时，"xz" 自动选择轴也必须通过。"""
        rows = []
        for _y in range(6):
            layer_rows = []
            for z in range(9):
                if _y == 0 or _y == 5:
                    layer_rows.append("#########")
                elif z in (0, 1, 7, 8):
                    layer_rows.append("#########")
                else:
                    layer_rows.append(".........")
            rows.append(layer_rows)
        parts = [
            make_part("pier", "石柱", boxes=[box(0, 8, 0, 1, 0, 4),
                                              box(0, 8, 7, 8, 0, 4)]),
            make_part("base", "石基座", boxes=[box(0, 8, 0, 8, 0, 0)]),
        ]
        model = make_model(rows, parts=parts)
        self.assertEqual(run_check("negative_space_passage", model,
                                   ("柱", "基座", "column", "base"), "xz", 3, 1, 3), [])


# ---------------------------------------------------------------- 4. 红色环带
def _tower_model(red_layers, boundary_red="all", interior_red=False, white_layers=()):
    """3×3~5×5 方塔：按层设置红色环带（boundary_red="all" 整圈红）。"""
    size = 5
    layers, colors = [], []
    for y in range(5):
        layer_rows = ["#" * size for _ in range(size)]
        crow = [["W"] * size for _ in range(size)]
        if y in red_layers:
            if boundary_red == "all":
                for z in range(size):
                    for x in range(size):
                        if x in (0, size - 1) or z in (0, size - 1):
                            crow[z][x] = "R"
            elif boundary_red == "half":
                for z in range(size):
                    for x in range(size):
                        if x in (0, size - 1) or z in (0, size - 1):
                            if (x + z) % 2 == 0:
                                crow[z][x] = "R"
        if interior_red and y in red_layers:
            for z in range(1, size - 1):
                for x in range(1, size - 1):
                    crow[z][x] = "R"
        layers.append(layer_rows)
        colors.append(["".join(r) for r in crow])
    part = make_part("tower_body", "圆形塔身", boxes=[box(0, 4, 0, 4, 0, 4)])
    return make_model(layers, parts=[part], color_rows=colors)


class RedBandAlternatingTest(unittest.TestCase):
    def test_continuous_alternating_bands_pass(self):
        model = _tower_model(red_layers={0, 2})
        self.assertEqual(run_check("red_band_alternating", model, ("塔身",), "R", "W", 2, 0.8), [])

    def test_broken_ring_rejected(self):
        model = _tower_model(red_layers={0, 2}, boundary_red="half")
        errors = run_check("red_band_alternating", model, ("塔身",), "R", "W", 2, 0.8)
        self.assertTrue(errors, "红环带断开（边界占比不足）必须判失败")

    def test_scattered_red_cells_with_high_total_rejected(self):
        """红格总数够（内圈全红）但不在外表面成环 → 拒绝。"""
        model = _tower_model(red_layers={0, 2}, boundary_red="none", interior_red=True)
        errors = run_check("red_band_alternating", model, ("塔身",), "R", "W", 2, 0.8)
        self.assertTrue(errors, "红格总数够但不成带必须判失败")

    def test_single_band_rejected(self):
        model = _tower_model(red_layers={0})
        errors = run_check("red_band_alternating", model, ("塔身",), "R", "W", 2, 0.8)
        self.assertTrue(any("环带" in e for e in errors), errors)


# ---------------------------------------------------------------- 5. 轮毂
class HubContrastTest(unittest.TestCase):
    def _wheel_model(self, hub_color="D"):
        layers = [["###", "###", "###"], ["...", ".#.", "..."]]
        # hub 在 y=1 的 (x=1,z=1)，轮胎在 y=0 全黑；hub 与轮胎上下相邻且有外露面。
        color_rows = [["KKK", "KKK", "KKK"],
                      ["...", "." + hub_color + ".", "..."]]
        part = make_part("front_wheels", "两个前轮",
                         boxes=[box(0, 2, 0, 2, 0, 0), box(1, 1, 1, 1, 1, 1)])
        return make_model(layers, parts=[part], color_rows=color_rows)

    def test_contrast_exposed_adjacent_passes(self):
        model = self._wheel_model()
        self.assertEqual(run_check("hub_contrast_adjacent", model, ("前轮", "轮", "wheel"),
                                   "K", "D", 1), [])

    def test_same_color_as_tire_rejected(self):
        model = self._wheel_model(hub_color="K")
        errors = run_check("hub_contrast_adjacent", model, ("前轮", "轮", "wheel"), "K", "D", 1)
        self.assertTrue(any("轮毂" in e for e in errors), errors)

    def test_buried_hub_rejected(self):
        layers = [["#####"] * 5 for _ in range(3)]
        colors = []
        for y in range(3):
            crow = []
            for z in range(5):
                crow.append("".join("D" if (y, z, x) == (1, 2, 2) else "K"
                                    for x in range(5)))
            colors.append(crow)
        model = make_model(layers, parts=[
            make_part("front_wheels", "两个前轮", boxes=[box(0, 4, 0, 4, 0, 2)])],
            color_rows=colors)
        errors = run_check("hub_contrast_adjacent", model, ("前轮", "轮", "wheel"), "K", "D", 1)
        self.assertTrue(any("内埋" in e or "外露" in e for e in errors), errors)


# ---------------------------------------------------------------- 6. 前腿与绣球邻接
class PartsAdjacentTest(unittest.TestCase):
    def test_adjacent_parts_pass(self):
        model = make_model([["####"]], parts=[
            make_part("fore_legs", "前腿", boxes=[box(0, 1, 0, 0)]),
            make_part("ribbon_ball", "绣球", boxes=[box(2, 2, 0, 0)]),
        ])
        self.assertEqual(run_check("parts_adjacent_min", model, ("前腿", "leg"),
                                   ("绣球", "ball"), 1), [])

    def test_separated_parts_rejected(self):
        model = make_model([["######"]], parts=[
            make_part("fore_legs", "前腿", boxes=[box(0, 1, 0, 0)]),
            make_part("ribbon_ball", "绣球", boxes=[box(4, 4, 0, 0)]),
        ])
        errors = run_check("parts_adjacent_min", model, ("前腿", "leg"), ("绣球", "ball"), 1)
        self.assertTrue(errors, "前腿与绣球空间不相邻必须判失败")
        self.assertTrue(any("6-邻接" in e for e in errors), errors)


# ---------------------------------------------------------------- 7. 其他结果几何检查
class ResultGeometryTest(unittest.TestCase):
    def test_s_curve(self):
        layers = [["##"] for _ in range(5)]
        part = make_part("swan_neck", "S形长颈", boxes=[
            box(0, 1, 0, 1, 0, 0), box(0, 1, 1, 2, 1, 1), box(0, 1, 2, 3, 2, 2),
            box(0, 1, 1, 2, 3, 3), box(0, 1, 0, 1, 4, 4)])
        model = make_model(layers, parts=[part])
        self.assertEqual(run_check("s_curve_min", model, ("长颈",), 4, 1.0, 1), [])
        straight = make_model(layers, parts=[
            make_part("swan_neck", "S形长颈", boxes=[box(0, 1, 0, 1, 0, 4)])])
        errors = run_check("s_curve_min", straight, ("长颈",), 4, 1.0, 1)
        self.assertTrue(any("S 形" in e or "偏移" in e for e in errors), errors)

    def test_circular_ring(self):
        ring_boxes = [box(x, x, z, z) for x in range(8) for z in range(8)
                      if x in (0, 7) or z in (0, 7)]
        ring = make_model([["########"]], parts=[make_part("rim", "大圆环轮辐", boxes=ring_boxes)])
        self.assertEqual(run_check("circular_ring_min", ring, ("圆环", "rim"), 8, 0.35), [])
        disc = make_model([["########"]], parts=[
            make_part("rim", "大圆环轮辐", boxes=[box(0, 7, 0, 7)])])
        self.assertTrue(run_check("circular_ring_min", disc, ("圆环", "rim"), 8, 0.35))

    def test_curved_roof_profile(self):
        roof = make_part("shell_roofs", "贝壳形屋顶", boxes=[
            box(0, 5, 0, 5, 0, 0), box(0, 4, 0, 5, 1, 1), box(1, 3, 1, 4, 2, 2)])
        rows = ["/\\vv^^", "//\\\\^^", "######"]
        model = make_model(rows, parts=[roof])
        self.assertEqual(run_check("curved_roof_profile", model, ("屋顶", "roof"), 8, 3), [])
        flat = make_model([["######"]], parts=[
            make_part("shell_roofs", "贝壳形屋顶", boxes=[box(0, 5, 0, 5, 0, 0)])])
        errors = run_check("curved_roof_profile", flat, ("屋顶", "roof"), 8, 3)
        self.assertTrue(errors, "平屋顶没有斜面/收分必须判失败")

    def test_cigar_taper(self):
        bag = make_part("gasbag", "银色气囊", boxes=[
            box(2, 3, 0, 0), box(0, 5, 1, 10), box(2, 3, 11, 11)])
        model = make_model([["#" * 12, "#" * 12]], parts=[bag])
        self.assertEqual(run_check("cigar_taper_min", model, ("气囊",), 10, 2.0, 0.6), [])
        uniform = make_model([["#" * 12, "#" * 12]], parts=[
            make_part("gasbag", "银色气囊", boxes=[box(0, 5, 0, 11)])])
        errors = run_check("cigar_taper_min", uniform, ("气囊",), 10, 2.0, 0.6)
        self.assertTrue(any("收分" in e for e in errors), errors)

    def test_eave_slope_overhang(self):
        support = make_part("four_columns", "四根石柱", boxes=[box(2, 6, 0, 4, 0, 2)])
        roof = make_part("triple_roofs", "三重歇山顶", boxes=[box(0, 8, 0, 4, 3, 3)])
        # 第 4 层（y=3）屋顶外缘：x=0 处 '/'、x=8 处 '\\'（朝外下坡，翘角方向证据）。
        roof_rows = ["/########", "#########", "#########", "#########", "########\\"]
        layers = [["#########"], ["#########"], ["#########"], roof_rows]
        model = make_model(layers, parts=[support, roof])
        self.assertEqual(run_check("eave_slope_overhang", model, ("屋顶", "roof"),
                                   ("柱", "column"), 1, 2, 2), [])
        no_overhang = make_model(layers, parts=[
            make_part("four_columns", "四根石柱", boxes=[box(0, 8, 0, 4, 0, 2)]), roof])
        self.assertTrue(run_check("eave_slope_overhang", no_overhang, ("屋顶", "roof"),
                                  ("柱", "column"), 1, 2, 2))
        flat_rows = [["#########"]] * 4
        flat_roof = make_model(flat_rows, parts=[support, roof])
        self.assertTrue(run_check("eave_slope_overhang", flat_roof, ("屋顶", "roof"),
                                  ("柱", "column"), 1, 2, 2))

    def test_part_raised_above(self):
        model = make_model([["##"] for _ in range(6)], parts=[
            make_part("arm", "右臂", boxes=[box(0, 1, 0, 1, 0, 3)]),
            make_part("torch", "火炬", boxes=[box(0, 0, 0, 0, 5, 5)])])
        self.assertEqual(run_check("part_raised_above", model, ("火炬",), ("手臂", "arm"), 1), [])
        low = make_model([["##"] for _ in range(6)], parts=[
            make_part("arm", "右臂", boxes=[box(0, 1, 0, 1, 0, 3)]),
            make_part("torch", "火炬", boxes=[box(0, 0, 0, 0, 3, 3)])])
        errors = run_check("part_raised_above", low, ("火炬",), ("手臂", "arm"), 1)
        self.assertTrue(any("未高举" in e for e in errors), errors)


# ---------------------------------------------------------------- 8. 最终门禁/评审/版本
class FinalGateSemanticsTest(unittest.TestCase):
    def _check(self, rec, case=None):
        return check_objects(rec, model_for_check_objects(),
                             {"validation": {"ok": True}, "steps": steps(60)},
                             case or make_case())

    def test_replay_ok_overrides_degraded_process_flag(self):
        """过程曾降级但最终重放 ok → 最终门禁通过，不因过程标记判失败。"""
        rec = record(gateFailed=True, gateDegraded=True,
                     finalGateReplay={"ok": True, "errors": [], "affectedPartCount": 0,
                                      "errorCellCount": 0})
        errors, metrics = self._check(rec)
        self.assertFalse(any("门禁" in e for e in errors), errors)
        self.assertEqual(metrics["final_gate_source"], "replay")
        self.assertTrue(metrics["final_gate_ok"])

    def test_replay_failure_is_a_failure(self):
        rec = record(finalGateReplay={"ok": False, "errors": ["立体部位「vane」伪部位"],
                                      "affectedPartCount": 1, "errorCellCount": 3})
        errors, metrics = self._check(rec)
        self.assertTrue(any("最终门禁重放未通过" in e for e in errors), errors)
        self.assertFalse(metrics["assertion_ok"])

    def test_old_record_without_replay_falls_back_to_gate_flag(self):
        """旧记录缺 finalGateReplay：兼容退回 gateFailed 过程标记，不因缺失误判。"""
        errors, metrics = self._check(record(gateFailed=True, gateErrors=["伪部位"]))
        self.assertTrue(any("门禁" in e for e in errors), errors)
        self.assertEqual(metrics["final_gate_source"], "legacy")

    def test_missing_replay_on_clean_record_does_not_fail(self):
        errors, metrics = self._check(record())
        self.assertFalse(any("门禁" in e for e in errors), errors)
        self.assertEqual(metrics["final_gate_source"], "legacy")
        self.assertIsNone(metrics["version_overwrites"], "缺失的版本覆盖数必须记未知")
        self.assertIsNone(metrics["review_stale"], "缺失的评审过期标记必须记未知")

    def test_explicit_null_replay_is_unknown_not_failure(self):
        rec = record(gateFailed=True, finalGateReplay=None)
        errors, _metrics = self._check(rec)
        self.assertFalse(any("门禁" in e for e in errors), errors)

    def test_stale_review_blocks_fidelity_success(self):
        rec = record(outcome="fidelity_success", reviewStale=True)
        errors, metrics = self._check(rec)
        self.assertTrue(any("评审已过期" in e for e in errors), errors)
        self.assertFalse(metrics["assertion_ok"])

    def test_stale_review_flag_without_outcome_still_blocks_success(self):
        """run 记录即使没有 outcome 字段，reviewStale=true 也不得判成功（记录可信度）。"""
        rec = record(outcome=None, reviewStale=True)
        errors, _metrics = self._check(rec)
        self.assertTrue(any("评审已过期" in e for e in errors), errors)

    def test_stale_review_absent_is_not_failure(self):
        rec = record(outcome="fidelity_success")
        errors, _metrics = self._check(rec)
        self.assertFalse(any("评审" in e for e in errors), errors)

    def test_stale_review_false_is_not_failure(self):
        rec = record(outcome="fidelity_success", reviewStale=False)
        errors, _metrics = self._check(rec)
        self.assertFalse(any("评审" in e for e in errors), errors)

    def test_version_overwrite_is_recorded(self):
        _errors, metrics = self._check(record(versionOverwriteCount=0))
        self.assertEqual(metrics["version_overwrites"], 0)


# ---------------------------------------------------------------- 9. 两层复杂度
class ComplexityTierTest(unittest.TestCase):
    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_requirement_and_regression_tiers(self, _mock_validate):
        rec = record()
        case = make_case(desc="测试需求：目标约 100 块积木", min_voxels=1)
        errors, metrics = check_objects(
            rec, model_for_check_objects(),
            {"validation": {"ok": True}, "steps": steps(60)}, case)
        self.assertTrue(metrics["assertion_ok"], errors)
        requirement = metrics["requirement_tier"]
        self.assertEqual(requirement["target_blocks"], 100)
        self.assertEqual(requirement["bricks"], 60)
        self.assertAlmostEqual(requirement["bricks_ratio"], 0.6)
        self.assertTrue(requirement["target_blocks_ok"])
        regression = metrics["regression_tier"]
        self.assertEqual(regression["baseline_voxels_median"], 650)
        self.assertEqual(regression["baseline_planned_voxels_median"], 705)
        self.assertEqual(regression["baseline_voxels_per_piece_median"], 7.98)
        self.assertIn("不参与失败判定", regression["note"])

    def test_target_block_ratio_below_floor_fails(self):
        case = make_case(desc="测试需求：目标约 100 块积木")
        errors, metrics = check_objects(
            record(), model_for_check_objects(),
            {"validation": {"ok": True}, "steps": steps(30)}, case)
        self.assertTrue(any("目标块数未达标" in e for e in errors), errors)
        self.assertFalse(metrics["requirement_tier"]["target_blocks_ok"])
        # 失败项必须来自需求达标档。
        self.assertTrue(any("目标块数未达标" in e
                            for e in metrics["requirement_tier"]["errors"]))

    def test_target_block_ratio_boundary(self):
        case = make_case(desc="测试需求：目标约 100 块积木")
        # 恰好 50%：容差为 >=，必须算达标。
        _errors, metrics = check_objects(
            record(), model_for_check_objects(),
            {"validation": {"ok": True}, "steps": steps(50)}, case)
        self.assertTrue(metrics["requirement_tier"]["target_blocks_ok"])

    def test_target_blocks_parsing(self):
        self.assertEqual(_target_blocks("一座塔，目标约 380 块积木"), 380)
        self.assertEqual(_target_blocks("目标约 300 块"), 300)
        self.assertIsNone(_target_blocks("没有目标块数"))


class ScaleMetricsConsistencyTest(unittest.TestCase):
    """规模指标同源核对：run/job 的 scaleMetrics 与 E2E 计算必须一致（2026-11-03 复核）。"""

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_mismatched_server_scale_metrics_fail(self, _mock_validate):
        model = model_for_check_objects()
        rec = record()
        rec["scaleMetrics"] = {"targetBlocks": 100, "actualParts": 60,
                               "actualVoxels": int(model.get("totalVoxels") or 0) + 1,
                               "targetBlocksRatio": 0.6}
        case = make_case(desc="测试需求：目标约 100 块积木", min_voxels=1)
        errors, metrics = check_objects(
            rec, model, {"validation": {"ok": True}, "steps": steps(60)}, case)
        self.assertTrue(any("实际体素数" in e or "actualVoxels" in e for e in errors), errors)
        self.assertFalse(metrics["requirement_tier"]["scale_metrics_consistent"]["ok"])

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_consistent_server_scale_metrics_pass(self, _mock_validate):
        model = model_for_check_objects()
        rec = record()
        rec["scaleMetrics"] = {"targetBlocks": 100, "actualParts": 60,
                               "actualVoxels": int(model.get("totalVoxels") or 0),
                               "targetBlocksRatio": 0.6}
        case = make_case(desc="测试需求：目标约 100 块积木", min_voxels=1)
        errors, metrics = check_objects(
            rec, model, {"validation": {"ok": True}, "steps": steps(60)}, case)
        self.assertEqual(errors, [])
        self.assertTrue(metrics["requirement_tier"]["scale_metrics_consistent"]["ok"])


# ---------------------------------------------------------------- 10. 案例注册与检查器接线
class CheckerWiringTest(unittest.TestCase):
    NEW_CHECKERS = (
        "part_union_span_min", "part_min_volume", "parts_adjacent_min", "part_raised_above",
        "red_band_alternating", "negative_space_passage", "eave_slope_overhang",
        "hub_contrast_adjacent", "circular_ring_min", "curved_roof_profile",
        "cigar_taper_min", "s_curve_min",
    )

    def test_new_checkers_registered(self):
        for name in self.NEW_CHECKERS:
            self.assertIn(name, _CHECKS)

    def test_every_registered_checker_is_used_with_parameters(self):
        """方向性保证：新检查器必须被案例真实引用且带参数，不能只注册不用。"""
        used = {}
        for case in list(CASES) + list(NEW_CASES) + list(EXTRA_CASES):
            for spec in case["checks"]:
                used.setdefault(spec[0], []).append((case["id"], len(spec) - 1, spec[1:]))
        for name in self.NEW_CHECKERS:
            self.assertIn(name, used, f"{name} 没有被任何案例引用")
            for case_id, param_count, params in used[name]:
                self.assertGreater(param_count, 0, f"{name} @{case_id} 没有参数")
                self.assertTrue(params, f"{name} @{case_id} 参数为空")

    def test_h10_and_c05_c07_targeting(self):
        h10 = find_case("H10")
        self.assertIn("part_union_span_min", [s[0] for s in h10["checks"]])
        c05 = find_case("C05")
        self.assertIn("red_band_alternating", [s[0] for s in c05["checks"]])
        c07 = find_case("C07")
        self.assertIn("negative_space_passage", [s[0] for s in c07["checks"]])
        self.assertIn("eave_slope_overhang", [s[0] for s in c07["checks"]])
        c10 = find_case("C10")
        self.assertIn("hub_contrast_adjacent", [s[0] for s in c10["checks"]])
        h04 = find_case("H04")
        self.assertIn("parts_adjacent_min", [s[0] for s in h04["checks"]])


# ---------------------------------------------------------------- 11. 算子未存档的测量伪影
class OpsUnrecordedTest(unittest.TestCase):
    """ops 轨道但模型存档缺少 ops（逐格补丁后）时，算子类检查按未知处理。"""

    def _model(self, with_ops=True):
        model = make_model([["##", "##"]],
                           parts=[make_part("body", "主体", boxes=[box(0, 1, 0, 1)])],
                           ops=[{"op": "box"}] if with_ops else None)
        if not with_ops:
            model.pop("ops")  # 模拟存档缺 ops 字段
        return model

    def test_missing_ops_is_unknown_not_failure(self):
        for model in (self._model(with_ops=False),):
            self.assertEqual(run_check("op_count_min", model, 16), [])
            self.assertEqual(run_check("cylinder_ops_min", model, 2), [])
        # 真实存档形态：track=ops 且 ops 键为 null（逐格补丁后）
        null_ops = make_model([["##", "##"]],
                              parts=[make_part("body", "主体", boxes=[box(0, 1, 0, 1)])])
        null_ops["ops"] = None
        self.assertEqual(run_check("op_count_min", null_ops, 16), [])
        self.assertEqual(run_check("cylinder_ops_min", null_ops, 2), [])

    def test_recorded_but_insufficient_ops_still_fails(self):
        """有 ops 存档时不够仍然必须失败：不得把「缺失」与「不足」混为一谈。"""
        model = self._model(with_ops=True)
        self.assertTrue(run_check("op_count_min", model, 16))
        self.assertTrue(run_check("cylinder_ops_min", model, 2))

    def test_ascii_track_skips_ops_checks(self):
        model = make_model([["##", "##"]], parts=[make_part("body", "主体", boxes=[box(0, 1, 0, 1)])],
                           track="ascii")
        model.pop("ops")
        self.assertEqual(run_check("op_count_min", model, 16), [])
        self.assertEqual(run_check("cylinder_ops_min", model, 2), [])


class LoadRunFinalRevisionTest(unittest.TestCase):
    """最终产物读取（2026-11-03 复核）：按 record.revision 取，且模型/方案/哈希必须一致。

    视觉回滚后 artifacts 里会留下被废弃的更高版本补丁（r004/r005）；旧 load_run 取排序最后一版，
    把废弃稿当最终稿（真实 E2E 的 H02/H04/G03/G05 曾因此版本错配）。这里用临时 artifacts 目录
    覆盖三种情况：正确取 r003、版本不一致判数据异常、哈希不一致判数据异常。
    """

    RUN_ID = "loadrun1"
    PASS_ID = "loadrun2"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-loadrun-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.art = os.path.join(self.tmp, "artifacts")
        os.makedirs(self.art)
        patcher = mock.patch.object(e2e_assert_mod, "ROOT", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _model(self, run_id, rid):
        return {"name": "测试塔", "slug": "t", "grid": {"w": 2, "d": 2},
                "layers": [{"y": 0, "rows": ["##", "##"]}], "totalVoxels": 4,
                "revision": rid, "runId": run_id}

    def _write(self, run_id, record_revision, key_revisions, solution_revision,
               hash_override=None, final_model_override=None):
        from legogod.workflow_artifacts import model_hash
        arts = {}
        for rid in key_revisions:
            model = self._model(run_id, rid)
            if final_model_override is not None and rid == f"r{record_revision:03d}":
                model.update(final_model_override)
            mpath = f"model_t_{rid}_{run_id}.json"
            with open(os.path.join(self.art, mpath), "w", encoding="utf-8") as f:
                json.dump(model, f, ensure_ascii=False)
            arts[f"model_{rid}"] = mpath
        # 只为 record.revision 及更早版本写方案（废弃的高版本补丁只有模型、没有方案）
        stable = [rid for rid in key_revisions if int(rid[1:]) <= record_revision]
        for rid in stable:
            with open(os.path.join(self.art, arts[f"model_{rid}"]), encoding="utf-8") as f:
                model = json.load(f)
            sol = {"revision": f"r{solution_revision:03d}" if rid == f"r{record_revision:03d}" else rid,
                   "modelHash": hash_override if (
                       hash_override and rid == f"r{record_revision:03d}") else model_hash(model),
                   "steps": [], "validation": {"ok": True}}
            spath = f"solution_t_{rid}_{run_id}.json"
            with open(os.path.join(self.art, spath), "w", encoding="utf-8") as f:
                json.dump(sol, f, ensure_ascii=False)
            arts[f"solution_{rid}"] = spath
        record = {"runId": run_id, "revision": record_revision, "artifacts": arts}
        with open(os.path.join(self.art, f"run_{run_id}.json"), "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)

    def test_picks_record_revision_not_last_artifact(self):
        """r001..r005 中 r004/r005 是被废弃的补丁：最终版必须是 record.revision=r003。"""
        self._write(self.RUN_ID, 3, ["r001", "r002", "r003", "r004", "r005"],
                    solution_revision=3)
        record, model, solution = e2e_assert_mod.load_run(self.RUN_ID)
        self.assertEqual(record["revision"], 3)
        self.assertEqual(model["revision"], "r003")
        self.assertEqual(solution["revision"], "r003")
        self.assertNotIn(model["revision"], ("r004", "r005"))

    def test_solution_revision_mismatch_is_data_error(self):
        """模型 r003 配方案 r002：不得混用，直接判数据异常。"""
        self._write(self.RUN_ID, 3, ["r001", "r002", "r003"], solution_revision=2)
        with self.assertRaises(SystemExit) as ctx:
            e2e_assert_mod.load_run(self.RUN_ID)
        self.assertIn("方案版本", str(ctx.exception))

    def test_model_hash_mismatch_is_data_error(self):
        """方案 modelHash 与模型内容不一致：判数据异常，不允许用旧校验结论冒充。"""
        self._write(self.RUN_ID, 3, ["r001", "r002", "r003"], solution_revision=3,
                    hash_override="f" * 64)
        with self.assertRaises(SystemExit) as ctx:
            e2e_assert_mod.load_run(self.RUN_ID)
        self.assertIn("modelHash", str(ctx.exception))

    def test_missing_final_revision_pair_is_data_error(self):
        """record.revision 指向的 model/solution 对缺失：判数据异常（不退回最后版本）。"""
        self._write(self.RUN_ID, 3, ["r001", "r002"], solution_revision=2)
        with self.assertRaises(SystemExit) as ctx:
            e2e_assert_mod.load_run(self.RUN_ID)
        self.assertIn("缺少最终版本", str(ctx.exception))


class ValidationRecomputeTest(unittest.TestCase):
    """统一校验必须按同一模型重算，不得直接信任 solution 里缓存的 validation 结论。"""

    def test_cached_validation_ok_is_ignored_when_recompute_fails(self):
        model = make_model([["##", "##"]], parts=[make_part("body", "主体", boxes=[box(0, 1, 0, 1)])])
        solution = {"validation": {"ok": True}, "steps": []}   # 缓存通过，但方案没有任何零件
        errors = []
        e2e_assert_mod.assert_generic(
            {"ok": True, "finalGateReplay": {"ok": True, "errors": []}}, model, solution, errors)
        self.assertTrue(any("统一校验未通过" in e for e in errors), errors)


# ---------------------------------------------------------------- 12. 请求数与评审口径
class DrawRequestCaliberTest(unittest.TestCase):
    """drawAttempts[].request 是累计请求编号：draw_requests 取最大值，不得求和。"""

    def test_helper_max_not_sum(self):
        count = e2e_assert_mod.draw_request_count
        self.assertEqual(count([{"request": 1}, {"request": 2}, {"request": 3}]), 3)
        self.assertEqual(count([]), 0)
        self.assertEqual(count(None), 0)
        self.assertEqual(count([{"request": 1}, {"request": 3}]), 3)   # 跳号仍取最大值
        self.assertEqual(count([{"request": 1}, {}]), 1)               # 缺字段按 0
        self.assertEqual(count([{"request": "2"}, {"request": None}]), 2)
        self.assertEqual(count([None, {"request": 2}, "bad"]), 2)      # 非对象条目忽略

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_check_objects_uses_max(self, _mock_validate):
        rec = record(drawAttempts=[{"attempt": 1, "request": 1, "outcome": "draft"},
                                   {"attempt": 2, "request": 2, "outcome": "draft"},
                                   {"attempt": 3, "request": 3, "outcome": "accepted"}])
        case = make_case(desc="测试需求：目标约 100 块积木")
        _errors, metrics = check_objects(
            rec, model_for_check_objects(), {"validation": {"ok": True}, "steps": steps(60)}, case)
        self.assertEqual(metrics["draw_attempts"], 3)
        self.assertEqual(metrics["draw_requests"], 3)   # 旧口径会算成 6
        self.assertNotEqual(metrics["draw_requests"], 6)


class ReviewFallbackTest(unittest.TestCase):
    """新 run 记录自带 review；旧记录用任务 result.review 补入；都没有保持空。"""

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_run_record_review_wins(self, _mock_validate):
        rec = record(review={"scores": {"overall": 4}})
        case = make_case(desc="测试需求：目标约 100 块积木")
        _errors, metrics = check_objects(
            rec, model_for_check_objects(), {"validation": {"ok": True}, "steps": steps(60)},
            case, review_fallback={"scores": {"overall": 9}})
        self.assertEqual(metrics["review_overall"], 4)
        self.assertEqual(metrics["review_source"], "run_record")

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_old_record_falls_back_to_task_result(self, _mock_validate):
        """旧 run 记录没有 review 字段：任务 result.review 补入，恢复真实视觉分。"""
        rec = record()
        self.assertNotIn("review", rec)
        case = make_case(desc="测试需求：目标约 100 块积木")
        _errors, metrics = check_objects(
            rec, model_for_check_objects(), {"validation": {"ok": True}, "steps": steps(60)},
            case, review_fallback={"scores": {"overall": 5, "proportion": 5}})
        self.assertEqual(metrics["review_overall"], 5)
        self.assertEqual(metrics["review_source"], "task_result")
        self.assertEqual(metrics["review"]["scores"]["proportion"], 5)

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_no_review_anywhere_stays_empty(self, _mock_validate):
        rec = record()
        case = make_case(desc="测试需求：目标约 100 块积木")
        _errors, metrics = check_objects(
            rec, model_for_check_objects(), {"validation": {"ok": True}, "steps": steps(60)}, case)
        self.assertIsNone(metrics["review_overall"])
        self.assertIsNone(metrics["review_source"])
        self.assertEqual(metrics["review"], {})

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_empty_run_record_review_uses_fallback(self, _mock_validate):
        """新记录但评审不可用（review={}）：仍允许任务 result.review 补入。"""
        rec = record(review={})
        case = make_case(desc="测试需求：目标约 100 块积木")
        _errors, metrics = check_objects(
            rec, model_for_check_objects(), {"validation": {"ok": True}, "steps": steps(60)},
            case, review_fallback={"scores": {"overall": 3}})
        self.assertEqual(metrics["review_overall"], 3)
        self.assertEqual(metrics["review_source"], "task_result")


class TargetBlocksSingleSourceTest(unittest.TestCase):
    """E2E 断言的目标块数解析与生产单源一致：两种写法都认。"""

    def test_both_write_styles(self):
        self.assertEqual(_target_blocks("一座塔，目标约 380 块积木"), 380)
        self.assertEqual(_target_blocks("一座塔，目标 300 块"), 300)
        self.assertEqual(_target_blocks("目标200块积木"), 200)
        self.assertIsNone(_target_blocks("没有目标块数"))

    def test_e2e_parser_is_production_parser(self):
        from legogod import plan_scale
        self.assertIs(e2e_assert_20_parse_target_blocks(), plan_scale.parse_target_blocks)


def e2e_assert_20_parse_target_blocks():
    """取 E2E 断言实际使用的解析函数对象（防止有人再写一份本地正则）。"""
    from tools import e2e_assert_20
    return e2e_assert_20.parse_target_blocks


if __name__ == "__main__":
    unittest.main()
