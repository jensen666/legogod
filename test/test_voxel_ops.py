# -*- coding: utf-8 -*-
"""声明式三维算子编译器测试。

覆盖：四类基础体元（box/cylinder/wedge 正反/loft 矩形椭圆）、三类操作（hollow/mirror/paint）、
四条编译硬规则（顺序覆盖/越界即报错/必需部位防吞没/核心体素保护）、部位自动绑定。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.voxel_ops import compile_ops, validate_ops_schema  # noqa: E402
from legogod.geometry import solid_cells_of_model  # noqa: E402

PARTS = ["hull", "mast", "roof", "arm"]


def _compile(ops, w=8, d=8, layers=6, **kw):
    kw.setdefault("part_ids", PARTS)
    return compile_ops(ops, w, d, layers, **kw)


class BasicOpsTest(unittest.TestCase):
    def test_box_and_sequential_override(self):
        errs, res = _compile([
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "hull"},
            {"op": "box", "x": 0, "y": 1, "z": 0, "w": 2, "d": 2, "h": 1, "part": "mast"},
        ], required_ids=["hull", "mast"])
        self.assertEqual(errs, [])
        m = res["model"]
        self.assertEqual(m["totalVoxels"], 32)  # 顺序覆盖：mast 完全落在 hull 的 y=1 层内
        # 顺序覆盖：后写算子的格归 mast
        self.assertEqual(res["assign"][(0, 1, 0)], "mast")
        self.assertEqual(res["assign"][(3, 1, 3)], "hull")
        self.assertEqual(res["assign"][(0, 0, 0)], "hull")

    def test_cylinder_and_frustum(self):
        errs, res = _compile([
            {"op": "cylinder", "cx": 3.5, "cz": 3.5, "y": 0, "h": 3, "r": 1.5, "part": "mast"},
        ], required_ids=["mast"])
        self.assertEqual(errs, [])
        solid = solid_cells_of_model(res["model"])
        self.assertEqual(len(solid), 27)  # r=1.5 → 3x3 圆内 9 格 × 3 层
        self.assertEqual({res["assign"][c] for c in solid}, {"mast"})

    def test_regular_wedge_staircase(self):
        errs, res = _compile([
            {"op": "wedge", "dir": "+x", "x": 0, "y": 0, "z": 0, "len": 3, "d": 1, "h": 3,
             "part": "roof"},
        ], required_ids=["roof"])
        self.assertEqual(errs, [])
        rows = res["model"]["layers"][0]["rows"]
        self.assertEqual(rows[0][:3], "##\\")  # y=0：x0/x1 满格，x2 顶格坡面（45° 楼梯）
        # 剖面：x=0 三层、x=1 两层、x=2 一层（顶格为斜面字符 \）
        solid = solid_cells_of_model(res["model"])
        col0 = [c for c in solid if c[0] == 0]
        col1 = [c for c in solid if c[0] == 1]
        col2 = [c for c in solid if c[0] == 2]
        self.assertEqual(len(col0), 3)
        self.assertEqual(len(col1), 2)
        self.assertEqual(len(col2), 1)

    def test_inverted_wedge_root_toward_high_side(self):
        errs, res = _compile([
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 2, "d": 1, "h": 1, "part": "hull"},
            {"op": "wedge", "dir": "+x", "x": 2, "y": 1, "z": 0, "len": 2, "d": 1, "h": 1,
             "kind": "inverted", "part": "eave"},
        ], part_ids=PARTS + ["eave"], required_ids=["hull", "eave"])
        self.assertEqual(errs, [])
        rows1 = res["model"]["layers"][1]["rows"]
        # 反斜坡：根部（高端，西侧 x=2）贴墙，尖端（x=3）外挑；底层阶梯字符 b（根在西）
        self.assertEqual(rows1[0], "..bb....")  # 反斜坡一砖两格：根在西的 b 连续段

    def test_loft_rect_and_ellipse(self):
        errs, res = _compile([
            {"op": "loft", "part": "hull", "shape": "rect",
             "sections": [{"y": 0, "w": 4, "d": 6}, {"y": 2, "w": 2, "d": 4}]},
        ], required_ids=["hull"])
        self.assertEqual(errs, [])
        # 线性放样：y=1 层 w=3,d=5
        y1 = res["model"]["layers"][1]["cells"]
        self.assertEqual(len(y1), 15)
        errs, res2 = _compile([
            {"op": "loft", "part": "hull", "shape": "ellipse",
             "sections": [{"y": 0, "w": 3.6, "d": 3.6}, {"y": 1, "w": 3.6, "d": 3.6}]},
        ])
        self.assertEqual(errs, [])
        self.assertEqual(len(res2["model"]["layers"][0]["cells"]), 9)  # r=1.8 圆 ≈ 9 格

    def test_hollow_and_paint(self):
        errs, res = _compile([
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "hull"},
            {"op": "hollow", "x": 1, "y": 0, "z": 1, "w": 2, "d": 2, "h": 1},
            {"op": "paint", "color": "黑色", "cells": [[0, 0, 0]]},
        ], required_ids=["hull"])
        self.assertEqual(errs, [])
        solid = solid_cells_of_model(res["model"])
        self.assertNotIn((1, 0, 1), solid)
        self.assertNotIn((2, 0, 2), solid)
        self.assertIn((0, 0, 0), solid)
        self.assertEqual(res["model"]["layers"][0]["colorRows"][0][0], "K")

    def test_mirror_flips_slope_chars_and_keeps_part(self):
        errs, res = _compile([
            {"op": "mirror", "axis": "x", "ops": [
                {"op": "box", "x": 1, "y": 0, "z": 0, "w": 1, "d": 2, "h": 1, "part": "arm"},
            ]},
        ], w=4, d=2, layers=2, required_ids=["arm"])
        self.assertEqual(errs, [])
        solid = solid_cells_of_model(res["model"])
        # 镜像只写入镜像像（源格在临时网格里），x=1 关于 4 宽网格的像 = x=2
        self.assertEqual(solid, {(2, 0, 0), (2, 0, 1)})
        self.assertEqual({res["assign"][c] for c in solid}, {"arm"})


class CompileRulesTest(unittest.TestCase):
    def test_out_of_bounds_is_error_not_silent_clip(self):
        errs, res = _compile([
            {"op": "box", "x": 6, "y": 0, "z": 0, "w": 4, "d": 2, "h": 1, "part": "hull"},
        ], w=8, d=8, layers=2)
        self.assertTrue(any("越界" in e for e in errs), errs)
        self.assertIsNone(res)

    def test_mirror_out_of_bounds_rejected(self):
        errs, _ = _compile([
            {"op": "mirror", "axis": "x", "ops": [
                {"op": "box", "x": 6, "y": 0, "z": 0, "w": 5, "d": 1, "h": 1, "part": "hull"},
            ]},
        ], w=8, d=8, layers=2)
        self.assertTrue(any("越界" in e for e in errs), errs)

    def test_required_part_swallowed_reports_culprit(self):
        errs, _ = _compile([
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 1, "part": "mast"},
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 1, "part": "hull"},
        ], required_ids=["mast"])
        self.assertTrue(any("mast" in e and "吞没" in e.replace("覆盖/挖空至零体素", "吞没")
                            or "mast" in e for e in errs), errs)

    def test_bottom_must_land(self):
        errs, _ = _compile([
            {"op": "box", "x": 0, "y": 1, "z": 0, "w": 2, "d": 2, "h": 1, "part": "hull"},
        ], layers=3)
        self.assertTrue(any("y=0" in e for e in errs), errs)

    def test_frozen_core_survives_recompile(self):
        ops = [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 2, "d": 2, "h": 2, "part": "hull"}]
        errs, res = _compile(ops, layers=3)
        core = {(0, 0, 0), (1, 1, 1)}
        errs2, _ = _compile([
            {"op": "box", "x": 1, "y": 0, "z": 0, "w": 2, "d": 2, "h": 2, "part": "hull"},
        ], layers=3, frozen_cells=core)
        self.assertTrue(any("核心" in e for e in errs2), errs2)

    def test_unknown_op_rejected(self):
        errs, _ = _compile([{"op": "sphere", "x": 0, "y": 0, "z": 0}])
        self.assertTrue(any("算子闭集" in e for e in errs), errs)

    def test_part_must_be_declared(self):
        errs, _ = _compile([{"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 1, "h": 1,
                             "part": "ghost"}])
        self.assertTrue(any("ghost" in e for e in errs), errs)

    def test_wedge_z_direction_preserves_w_and_d(self):
        """wedge 在 ±z 方向必须严格遵守 w(len) 为 X 宽度、d 为 Z 深度，不得宽高颠倒。"""
        errs, res = _compile([
            {"op": "wedge", "dir": "-z", "x": 2, "y": 0, "z": 1, "len": 4, "d": 2, "h": 2,
             "part": "roof"},
        ], w=8, d=6, layers=3, required_ids=["roof"])
        self.assertEqual(errs, [])
        solid = solid_cells_of_model(res["model"])
        xs = sorted({c[0] for c in solid})
        zs = sorted({c[2] for c in solid})
        self.assertEqual(xs, [2, 3, 4, 5], "X 宽度必须严格等于 len=4 (x=2..5)")
        self.assertEqual(zs, [1, 2], "Z 深度必须严格等于 d=2 (z=1..2)")

    def test_wedge_shallow_slope_generates_3040_3039_runs(self):
        """缓坡屋顶盖在底座上：wedge(w=4, d=2, h=2) 自动生成 2 格正斜坡段并由 3039/3040 铺贴连通。"""
        from legogod import tiler
        from legogod.parts_library import PART_MAP
        errs, res = _compile([
            {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 2, "h": 1,
             "part": "hull", "color": "浅灰"},
            {"op": "wedge", "dir": "+x", "x": 0, "y": 1, "z": 0, "w": 4, "d": 2, "h": 2,
             "part": "roof", "color": "红色"},
        ], w=4, d=2, layers=3, required_ids=["hull", "roof"])
        self.assertEqual(errs, [])
        sol, fail = tiler.solve_with_budget(res["model"], res["model"]["layers"], log=lambda s: None)
        self.assertIsNotNone(sol, fail)
        shapes = {PART_MAP[s["piece"]]["shape"] for s in sol["steps"]}
        self.assertTrue(shapes & {"SLOPE2_XL", "SLOPE22_XL"},
                        f"应选用 3040/3039 多格正斜坡，实际 {shapes}")

    def test_inverted_wedge_odd_span_rejected(self):
        """反斜坡沿坡向跨度为奇数（如 w=1 或 w=3）必须在编译期直接报错拒收。"""
        errs, res = _compile([
            {"op": "wedge", "dir": "+x", "x": 0, "y": 0, "z": 0, "w": 1, "d": 2, "h": 1,
             "kind": "inverted", "part": "roof"},
        ])
        self.assertTrue(any("偶数" in e for e in errs), errs)
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
