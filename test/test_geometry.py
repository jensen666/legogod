# -*- coding: utf-8 -*-
"""几何契约单源测试。

覆盖：BRICK_SIZES 由 SHAPES 派生、多格斜坡凸点掩码（仅高端）、反斜坡根部承托位、
内部通配骨架格（六面被满实心格包裹）、斜坡连续段与高端支撑判定、楔形半体积质量。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import geometry as geo  # noqa: E402
from legogod.parts_library import PART_MAP, SHAPE_MAP  # noqa: E402


def _model_from_layers(rows_by_layer):
    """rows_by_layer: [ [z 行, ...], ... ] 自下而上（每行宽度 = w）。"""
    layers = []
    for y, rows in enumerate(rows_by_layer):
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["层"],
                       "color": None, "colorRows": None, "count": len(cells)})
    return {"grid": {"w": len(rows_by_layer[0][0]), "d": len(rows_by_layer[0])},
            "layers": layers}


class BrickSizeTest(unittest.TestCase):
    def test_brick_sizes_derived_from_shapes(self):
        sizes = geo.brick_sizes()
        for sid in ("B1x1", "B2x4", "B2x8", "B1x6", "B2x3"):
            s = SHAPE_MAP[sid]
            self.assertIn((s["w"], s["d"]), sizes)
            self.assertIn((s["d"], s["w"]), sizes)
        import legogod.tiler as tiler
        self.assertEqual(tiler.BRICK_SIZES, sizes, "tiler.BRICK_SIZES 必须由单源派生")


class StudMaskTest(unittest.TestCase):
    def test_regular_multi_slope_studs_only_high_end(self):
        p = PART_MAP["SLOPE2_XL"]  # 2x1 正斜坡，高端在西（i=0）
        self.assertEqual(geo.stud_cells(p, 3, 5, False), [(3, 5)])
        p2 = PART_MAP["SLOPE22_XR"]  # 2x2 正斜坡，高端在东
        self.assertEqual(sorted(geo.stud_cells(p2, 0, 0, False)), [(1, 0), (1, 1)])

    def test_inverted_slope_full_studs_and_root_mask(self):
        p = PART_MAP["ISLOPE_XL"]  # 2x1 反斜坡，根部在西
        self.assertEqual(sorted(geo.stud_cells(p, 2, 2, False)), [(2, 2), (3, 2)])
        self.assertEqual(geo.root_cells(p, 2, 2, False), [(2, 2)])
        self.assertEqual(geo.root_cells(PART_MAP["B2x4"], 0, 0, False), None)

    def test_slope_mass_factor(self):
        self.assertEqual(PART_MAP["SLOPE_XP"]["massFactor"], 0.5)
        self.assertEqual(PART_MAP["SLOPE2_XL"]["massFactor"], 0.75)
        self.assertEqual(PART_MAP["ISLOPE22_XL"]["massFactor"], 0.75)
        self.assertEqual(PART_MAP["B2x4"].get("massFactor", 1.0), 1.0)


class InteriorCellsTest(unittest.TestCase):
    def test_only_fully_enclosed_solid_cells_are_interior(self):
        m = _model_from_layers([
            ["####", "####", "####"],
            ["####", "####", "####"],
        ])
        # 3 宽 × 3 深 × 2 层：所有格都贴边（w=d=3 无内部）→ 无内部格
        self.assertEqual(geo.interior_cells(m), set())
        m2 = _model_from_layers([
            ["......", "......", "......", "......"],
            [".####.", ".####.", ".####.", ".####."],
            [".####.", ".####.", ".####.", ".####."],
            [".####.", ".####.", ".####.", ".####."],
            ["......", "......", "......", "......"],
        ])
        interior2 = geo.interior_cells(m2)
        self.assertIn((2, 2, 1), interior2)      # 4x3 实心块的内部格
        self.assertNotIn((1, 1, 1), interior2)   # 贴边格不算
        self.assertNotIn((2, 1, 1), interior2)   # 底面贴空气层不算

    def test_neighbor_slope_breaks_seal(self):
        m = _model_from_layers([
            ["######", "######", "######"],
            ["######", "######", "####/#"],
            ["######", "######", "######"],
            ["######", "######", "######"],
        ])
        # (3, y=1, z=2) 的 x+1 邻居是斜面格 → 不密封；(2,1,1) 六面全是 '#' → 密封
        self.assertNotIn((3, 1, 2), geo.interior_cells(m))
        self.assertIn((2, 1, 1), geo.interior_cells(m))


class SlopeRunTest(unittest.TestCase):
    def test_run_along_slope_axis_only(self):
        typed = {(0, 0): "/", (1, 0): "/", (2, 0): "#", (0, 1): "/", (1, 1): "/"}
        self.assertEqual(geo.slope_run(typed, 0, 0, "/"), [(0, 0), (1, 0)])
        self.assertEqual(geo.slope_run(typed, 1, 1, "/"), [(0, 1), (1, 1)])

    def test_can_support_above(self):
        typed = {(0, 0): "\\", (1, 0): "\\", (5, 0): "/", (6, 0): "/"}
        self.assertTrue(geo.can_support_above("#"))
        self.assertTrue(geo.can_support_above("b"))                  # 反斜坡顶面满凸点
        self.assertTrue(geo.can_support_above("\\", typed, 0, 0))    # '\\' 段高端（西）
        self.assertFalse(geo.can_support_above("\\", typed, 1, 0))   # '\\' 段低端
        self.assertTrue(geo.can_support_above("/", typed, 6, 0))     # '/' 段高端（东）
        self.assertFalse(geo.can_support_above("/", typed, 5, 0))
        self.assertFalse(geo.can_support_above("/", {(9, 9): "/"}, 9, 9))  # 孤立 1x1 斜坡


if __name__ == "__main__":
    unittest.main()
