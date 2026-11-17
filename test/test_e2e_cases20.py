# -*- coding: utf-8 -*-
"""20 例复杂案例断言引擎的确定性回归测试（不调用真实模型）。

覆盖 tools/e2e_cases_20.py 的案例注册纪律与 tools/e2e_assert_20.py 的全部几何/配色检查：
每个检查都给「应通过」与「应失败」两组合成模型，防止断言写反、阈值算错或空断言假通过。
"""
import unittest
from unittest import mock

from tools.e2e_assert_20 import _CHECKS, _slope_count, check_objects
from tools.e2e_cases_20 import CASES, find_case
from tools.e2e_cases_extra import EXTRA_CASES

SLOPE = "\\"


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
    model = {"name": "测试模型", "grid": {"w": w, "d": d},
             "totalVoxels": sum(L["count"] for L in layers),
             "slopeVoxels": sum(sum(1 for ch in row for ch in row if ch in "\\/^vbdpq")
                                for rows in layers_rows for row in rows),
             "layers": layers, "parts": parts or [], "ops": ops or [], "track": track}
    return model


def make_part(pid, name, role="solid", boxes=(), voxels=None):
    if not boxes:
        boxes = [{"x1": 0, "x2": 0, "z1": 0, "z2": 0, "y1": 0, "y2": 0}]
    total = voxels if voxels is not None else sum(
        (b["x2"] - b["x1"] + 1) * (b["z2"] - b["z1"] + 1) * (b["y2"] - b["y1"] + 1) for b in boxes)
    return {"id": pid, "name": name, "role": role, "voxels": total, "boxes": list(boxes)}


def box(x1, x2, z1, z2, y1=0, y2=0):
    return {"x1": x1, "x2": x2, "z1": z1, "z2": z2, "y1": y1, "y2": y2}


def ctx(model, solution=None):
    from tools.e2e_assert_20 import _part_counts, _colored_cells
    return {"model": model, "solution": solution or {"validation": {"ok": True}},
            "counts": _part_counts(model), "colored": _colored_cells(model)}


def run_check(name, model, *args):
    return _CHECKS[name](ctx(model), *args)


class CaseRegistryTest(unittest.TestCase):
    def test_exactly_twenty_unique_cases(self):
        self.assertEqual(len(CASES), 20)
        ids = [c["id"] for c in CASES]
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual(ids, [f"C{i:02d}" for i in range(1, 21)])
        descs = [c["desc"] for c in CASES]
        self.assertEqual(len(set(descs)), 20)

    def test_descriptions_are_complex_and_assertable(self):
        for c in CASES:
            self.assertGreaterEqual(len(c["desc"]), 60, c["id"])
            # C07 的部位下限按需求原文重算后为 6（门洞/飞檐改为特征检查，不占部位；
            # 额枋与花板允许合并），其余案例 ≥9；具体数值由下面的专项测试保证。
            self.assertGreaterEqual(c["min_parts"], 6, c["id"])
            self.assertGreaterEqual(c["min_voxels"], 900, c["id"])
            self.assertTrue(c["require_parts"], c["id"])
            self.assertTrue(c["checks"], c["id"])
            for spec in c["checks"]:
                self.assertIn(spec[0], _CHECKS, f"{c['id']} 未注册检查 {spec[0]}")

    def test_c05_c07_part_minima_recomputed(self):
        """弱化独立部位要求后，部位下限不得靠配色/负空间特征凑数量。

        C05：需求点名 11 项，扣除「红色环带」（配色特征，red_band_alternating 检查）
             与「玻璃窗」（surface）后，合并观景平台+栏杆可为 1 部位 → 总 9/立体 8。
        C07：需求点名 7 组部位，「门洞」（负空间贯通）与「飞檐」（屋顶斜面/出挑方向）
             不是独立部位，额枋与花板可合并 → 总 6/立体 5。
        """
        c05 = find_case("C05")
        self.assertEqual((c05["min_parts"], c05["min_solid_parts"]), (9, 8))
        self.assertNotIn("红色环带", [name for name, _p in c05["require_parts"]])
        self.assertIn("red_band_alternating", [spec[0] for spec in c05["checks"]])
        c07 = find_case("C07")
        self.assertEqual((c07["min_parts"], c07["min_solid_parts"]), (6, 5))
        self.assertNotIn("飞檐", [name for name, _p in c07["require_parts"]])
        self.assertNotIn("门洞", [name for name, _p in c07["require_parts"]])
        names = [spec[0] for spec in c07["checks"]]
        self.assertIn("negative_space_passage", names)
        self.assertIn("eave_slope_overhang", names)

    def test_every_case_target_blocks_parsable(self):
        """Lead 冻结口径：desc 必须能被「目标约 N 块」解析出目标块数。"""
        from tools.e2e_assert_20 import _target_blocks
        for case in list(CASES) + list(EXTRA_CASES):
            self.assertIsNotNone(_target_blocks(case["desc"]), case["id"])

    def test_find_case(self):
        self.assertEqual(find_case("c01")["id"], "C01")
        self.assertEqual(find_case(desc=CASES[3]["desc"])["id"], "C04")
        self.assertIsNone(find_case("C99"))
        self.assertIsNone(find_case(desc="不存在的需求"))

    def test_extra_cases_stay_out_of_the_twenty(self):
        """另补四例可被编号和原文找到，但不进入 20 例注册表。"""
        self.assertEqual([c["id"] for c in EXTRA_CASES], ["C21", "C22", "C23", "C24"])
        self.assertEqual(len({c["desc"] for c in EXTRA_CASES}), 4)
        twenty = {c["desc"] for c in CASES}
        for c in EXTRA_CASES:
            self.assertNotIn(c["desc"], twenty, c["id"])
            self.assertGreaterEqual(len(c["desc"]), 60, c["id"])
            self.assertGreaterEqual(c["min_voxels"], 900, c["id"])
            self.assertTrue(c["require_parts"], c["id"])
            self.assertTrue(c["checks"], c["id"])
            for spec in c["checks"]:
                self.assertIn(spec[0], _CHECKS, f"{c['id']} 未注册检查 {spec[0]}")
            self.assertEqual(find_case(c["id"].lower())["id"], c["id"])
            self.assertEqual(find_case(desc=c["desc"])["id"], c["id"])

    def test_checks_drop_slope_min_and_keep_the_rest(self):
        """收分按松的口径：不再用 slope_min，其余检查一条不删，checks 仍非空。"""
        expected = {
            "C01": ["layers_min", "surface_parts_min", "colors_distinct_min"],
            "C02": ["layers_min", "tiered_min", "enclosed_interior_min", "op_count_min"],
            "C03": ["cylinder_ops_min", "layers_min", "colors_distinct_min", "op_count_min"],
            "C04": ["ground_components_min", "layers_min", "color_ratio_min", "op_count_min"],
            "C05": ["cylinder_ops_min", "layers_min", "color_ratio_min", "colors_distinct_min",
                    "red_band_alternating"],
            "C06": ["cylinder_ops_min", "part_spans_two_axes", "layers_min", "op_count_min"],
            "C07": ["layer_components_min", "layers_min", "op_count_min",
                    "negative_space_passage", "eave_slope_overhang"],
            "C08": ["cylinder_ops_min", "part_box_count_min", "parts_min"],
            "C09": ["layers_min", "part_box_count_min", "colors_distinct_min", "op_count_min"],
            "C10": ["part_box_count_min", "parts_min", "hub_contrast_adjacent",
                    "colors_distinct_min", "op_count_min"],
            "C11": ["cigar_taper_min", "part_span_min", "layers_min", "op_count_min"],
            "C12": ["part_overhang_min", "part_box_count_min", "parts_min", "op_count_min"],
            "C13": ["part_overhang_min", "part_box_count_min", "parts_min", "op_count_min"],
            "C14": ["part_span_min", "part_span_min", "part_box_count_min", "colors_distinct_min"],
            "C15": ["surface_parts_min", "parts_min", "colors_distinct_min"],
            "C16": ["cylinder_ops_min", "parts_min", "colors_distinct_min", "op_count_min"],
            "C17": ["colors_distinct_min", "parts_min", "surface_parts_min"],
            "C18": ["cylinder_ops_min", "layers_min", "parts_min"],
            "C19": ["part_span_min", "both_sides", "color_ratio_min", "parts_min"],
            "C20": ["paired_or_span", "layers_min", "surface_parts_min", "parts_min"],
            "C21": ["both_sides", "part_span_min", "colors_distinct_min", "op_count_min"],
            "C22": ["ground_components_min", "part_box_count_min", "part_span_min", "layers_min"],
            "C23": ["part_box_count_min", "enclosed_interior_min", "layers_min"],
            "C24": ["enclosed_interior_min", "layers_min", "colors_distinct_min"],
        }
        seen = []
        for case in list(CASES) + list(EXTRA_CASES):
            names = [spec[0] for spec in case["checks"]]
            seen.append(case["id"])
            self.assertNotIn("slope_min", names, case["id"])
            self.assertTrue(case["checks"], case["id"])
            self.assertEqual(names, expected[case["id"]], case["id"])
        self.assertEqual(seen, [f"C{i:02d}" for i in range(1, 25)])
        self.assertIn("正斜坡砖", find_case("C01")["desc"])
        self.assertIn("正斜坡砖", find_case("C02")["desc"])


class CheckEngineTest(unittest.TestCase):
    def test_layers_min(self):
        model = make_model([["##"]])
        self.assertTrue(run_check("layers_min", model, 3))
        model = make_model([["##"], ["##"], ["##"]])
        self.assertEqual(run_check("layers_min", model, 3), [])

    def test_slope_min(self):
        flat = make_model([["##", "##"]])
        sloped = make_model([["##", "##"], [SLOPE + "#", "##"]])
        self.assertEqual(_slope_count(flat), 0)
        self.assertEqual(_slope_count(sloped), 1)
        self.assertTrue(run_check("slope_min", flat, 1))
        self.assertEqual(run_check("slope_min", sloped, 1), [])

    def test_surface_parts_min(self):
        model = make_model([["##"]], parts=[make_part("a", "主体")])
        self.assertTrue(run_check("surface_parts_min", model, 1))
        model["parts"].append(make_part("eye", "眼睛", role="surface"))
        self.assertEqual(run_check("surface_parts_min", model, 1), [])

    def test_colors_distinct_and_ratio(self):
        model = make_model([["##", "##"]], color_rows=[["KR", "WW"]])
        self.assertEqual(run_check("colors_distinct_min", model, 3), [])
        self.assertTrue(run_check("colors_distinct_min", model, 4))
        self.assertEqual(run_check("color_ratio_min", model, "W", 0.5), [])
        self.assertTrue(run_check("color_ratio_min", model, "K", 0.5))
        bare = make_model([["##", "##"]])
        self.assertTrue(run_check("color_ratio_min", bare, "W", 0.1))

    def test_ground_and_layer_components(self):
        split = make_model([["##..##"]])
        self.assertEqual(run_check("ground_components_min", split, 2), [])
        self.assertTrue(run_check("ground_components_min", split, 3))
        joined = make_model([["######"]])
        self.assertTrue(run_check("ground_components_min", joined, 2))
        # 分层：底层连成一排、上层分成两处
        model = make_model([["######"], ["##..##"]])
        self.assertEqual(run_check("layer_components_min", model, 2), [])

    def test_part_span_and_two_axes(self):
        model = make_model([["##########"]], parts=[make_part("h", "气囊", boxes=[box(0, 9, 0, 0)])])
        self.assertEqual(run_check("part_span_min", model, ("气囊",), 8, "x"), [])
        self.assertEqual(run_check("part_span_min", model, ("气囊",), 8, "xz"), [])
        self.assertTrue(run_check("part_span_min", model, ("气囊",), 8, "y"))
        self.assertTrue(run_check("part_span_min", model, ("气囊",), 11, "x"))
        self.assertTrue(run_check("part_span_min", model, ("气囊",), 1, "q"))
        cross = make_model([["#########"]], parts=[make_part(
            "b", "风叶", boxes=[box(4, 4, 0, 8), box(0, 8, 4, 4)])])
        self.assertEqual(run_check("part_spans_two_axes", cross, ("风叶",), 4), [])
        self.assertTrue(run_check("part_spans_two_axes", cross, ("风叶",), 10))
        self.assertTrue(run_check("part_span_min", cross, ("不存在",), 2))

    def test_part_span_three_axes_distinguish_vertical_from_horizontal(self):
        """三轴显式化：竖向结构只能用 y，横向宽度不能冒充纵向长度。"""
        # 4×1×12 的长条：x 短、y 矮、z 长 → y 轴断言必须失败、z 轴断言通过。
        model = make_model([["#" * 12]], parts=[make_part("h", "艇体", boxes=[box(0, 3, 0, 11)])])
        self.assertEqual(run_check("part_span_min", model, ("艇体",), 12, "z"), [])
        self.assertTrue(run_check("part_span_min", model, ("艇体",), 6, "y"))
        # 只有 x 宽、y 矮的机翼：拿 x 轴能过，拿 y 轴（纵向）不能过。
        wing = make_model([["#" * 8]], parts=[make_part("w", "机翼", boxes=[box(0, 7, 0, 0)])])
        self.assertEqual(run_check("part_span_min", wing, ("机翼",), 8, "x"), [])
        self.assertTrue(run_check("part_span_min", wing, ("机翼",), 8, "y"))

    def test_part_overhang_min(self):
        model = make_model([["###"]], parts=[make_part("boom", "动臂", boxes=[box(3, 6, 0, 0)])])
        self.assertEqual(run_check("part_overhang_min", model, ("动臂",), 2), [])
        self.assertTrue(run_check("part_overhang_min", model, ("动臂",), 5))
        inside = make_model([["#####"]], parts=[make_part("boom", "动臂", boxes=[box(1, 2, 0, 0)])])
        self.assertTrue(run_check("part_overhang_min", inside, ("动臂",), 2))

    def test_paired_or_span_and_both_sides(self):
        one = make_model([["########"]], parts=[make_part("t", "钟楼", boxes=[box(0, 1, 0, 0)])])
        self.assertTrue(run_check("paired_or_span", one, ("钟楼",)))
        both = make_model([["########"]], parts=[make_part("t", "钟楼", boxes=[box(0, 1, 0, 0),
                                                                           box(6, 7, 0, 0)])])
        self.assertEqual(run_check("paired_or_span", both, ("钟楼",)), [])
        spanned = make_model([["########"]], parts=[make_part("u", "钟楼", boxes=[box(0, 7, 0, 0)])])
        self.assertEqual(run_check("paired_or_span", spanned, ("钟楼",)), [])
        self.assertEqual(run_check("both_sides", both, ("钟楼",)), [])
        self.assertTrue(run_check("both_sides", one, ("钟楼",)))

    def test_part_box_count_min(self):
        four = make_model([["######"]], parts=[make_part(
            "w", "车轮", boxes=[box(0, 0, 0, 0), box(3, 3, 0, 0), box(0, 0, 3, 3), box(3, 3, 3, 3)])])
        self.assertEqual(run_check("part_box_count_min", four, ("车轮", "wheel"), 4), [])
        self.assertTrue(run_check("part_box_count_min", four, ("车轮", "wheel"), 5))
        one = make_model([["######"]], parts=[make_part("b", "车身", boxes=[box(0, 5, 0, 0)])])
        self.assertTrue(run_check("part_box_count_min", one, ("车轮", "wheel"), 1))

    def test_enclosed_interior(self):
        ring = ["####", "#..#", "#..#", "####"]
        empty = make_model([ring])
        self.assertEqual(run_check("enclosed_interior_min", empty, 1), [])
        filled = make_model([["####", "####", "####", "####"]])
        self.assertTrue(run_check("enclosed_interior_min", filled, 1))

    def test_tiered_min(self):
        model = make_model([["####", "####"], ["###", "####"], ["##", "####"]])
        self.assertEqual(run_check("tiered_min", model, 3), [])
        self.assertTrue(run_check("tiered_min", model, 4))

    def test_cylinder_ops_counts_mirror_children(self):
        ops = [{"op": "box"}, {"op": "mirror", "ops": [{"op": "cylinder"}, {"op": "cylinder"}]},
               {"op": "cylinder"}]
        model = make_model([["##"]], ops=ops)
        self.assertEqual(run_check("cylinder_ops_min", model, 3), [])
        self.assertTrue(run_check("cylinder_ops_min", model, 4))

    def test_op_count_skips_rows_track(self):
        model = make_model([["##"]], track="rows")
        self.assertEqual(run_check("op_count_min", model, 50), [])
        model = make_model([["##"]], track="ops")
        self.assertTrue(run_check("op_count_min", model, 1))

    @mock.patch("tools.e2e_assert.validate_solution", return_value={"ok": True, "errors": []})
    def test_require_parts_volumes(self, _mock_validate):
        """合成模型的统一校验由注入桩放行（校验重算行为另在 test_e2e_assert_semantics 覆盖）。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        solution = {"validation": {"ok": True}, "steps": []}
        case = {
            "id": "C99", "name": "测试", "min_parts": 1, "min_solid_parts": 1,
            "min_voxels": 1, "min_ops": 0,
            "require_parts": [("主体", ("body",)), ("眼睛", ("eye",))],
            "checks": [],
        }
        model = make_model([["##"]], parts=[make_part("body", "主体", boxes=[box(0, 1, 0, 0)])])
        errors, metrics = check_objects(record, model, solution, case)
        self.assertFalse(metrics["assertion_ok"])
        self.assertTrue(any("眼睛" in e for e in errors))
        self.assertTrue(any("部位数" in e for e in errors) is False)
        model["parts"].append(make_part("eye", "眼睛", role="surface", boxes=[box(0, 0, 0, 0)]))
        errors, metrics = check_objects(record, model, solution, case)
        self.assertTrue(metrics["assertion_ok"], errors)

    def test_task_failure_and_generic_floor(self):
        record = {"ok": False, "runId": "x", "error": "生成失败", "revision": 1, "artifacts": {}}
        model = make_model([["##"]])
        errors, _metrics = check_objects(record, model, {"validation": {"ok": True}}, {
            "id": "C99", "name": "测试", "min_parts": 1, "min_solid_parts": 1,
            "min_voxels": 1, "min_ops": 0, "require_parts": [], "checks": []})
        self.assertTrue(any("运行未成功" in e for e in errors))

    def test_zero_slope_does_not_fail_cases_but_other_checks_still_do(self):
        """斜面体素为 0 不再因 slope_min 失败；缺部位、层数、体素、门禁、空腔仍然失败。"""
        case = find_case("C02")
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        solution = {"validation": {"ok": True}, "steps": []}
        model = make_model([["##", "##"]], parts=[make_part("body", "塔身", boxes=[box(0, 1, 0, 1)])])
        self.assertEqual(model["slopeVoxels"], 0)
        errors, metrics = check_objects(record, model, solution, case)
        self.assertFalse(metrics["assertion_ok"])
        self.assertFalse(any("斜面" in e for e in errors))
        self.assertTrue(any("拱门" in e for e in errors))
        self.assertTrue(any("层数不足" in e for e in errors))
        self.assertTrue(any("体素数" in e for e in errors))
        self.assertTrue(any("空腔" in e or "围合" in e for e in errors))
        gated = dict(record, gateFailed=True, gateErrors=["墙皮"])
        gate_errors, _metrics = check_objects(gated, model, solution, case)
        self.assertTrue(any("门禁" in e for e in gate_errors))
        self.assertFalse(any("斜面" in e for e in gate_errors))


if __name__ == "__main__":
    unittest.main()
