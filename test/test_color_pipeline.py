# -*- coding: utf-8 -*-
"""配色机制回归测试：形状×颜色零件库、按层设计色铺贴、库存不足回退、旧模型兼容。"""
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler  # noqa: E402
from legogod.parts_library import (  # noqa: E402
    COLORS, COLOR_NAMES, PARTS, PART_MAP, SHAPES, part_for,
)


class PartsLibraryColorTest(unittest.TestCase):
    def test_every_shape_has_default_part_with_legacy_id(self):
        """默认色零件必须沿用旧 id，历史模型/历史方案才能原样渲染。"""
        for sh in SHAPES:
            p = part_for(sh["id"], sh["defaultColor"])
            self.assertIsNotNone(p, "%s 缺少默认色零件" % sh["id"])
            self.assertEqual(p["id"], sh["id"])

    def test_every_shape_available_in_every_color(self):
        """每个形状都要有全部颜色的变体，且颜色值与名称一致、库存为正。"""
        for name in COLOR_NAMES:
            for sh in SHAPES:
                self.assertIsNotNone(part_for(sh["id"], name), "%s 缺少颜色 %s" % (sh["id"], name))
        for p in PARTS:
            self.assertGreater(p["count"], 0)
            self.assertEqual(COLORS[p["colorName"]]["hex"], p["color"])


class TilerColorTest(unittest.TestCase):
    def _inventory(self):
        return {p["id"]: p["count"] for p in PARTS}

    def test_rect_layer_uses_design_color(self):
        """方块层必须按设计色选砖，不混入其它颜色。"""
        typed = {(x, z): "#" for x in range(4) for z in range(2)}
        placed = tiler.solve_layer(typed, None, self._inventory(), random.Random(1), target_color="绿色")
        self.assertIsNotNone(placed)
        colors = {PART_MAP[pid]["colorName"] for pid, *_ in placed}
        self.assertEqual(colors, {"绿色"})

    def test_slope_layer_uses_design_color(self):
        """斜面体素必须换成本层设计色的同向斜坡砖。"""
        typed = {(x, 0): "/" for x in range(3)}
        placed = tiler.solve_layer(typed, None, self._inventory(), random.Random(1), target_color="深绿")
        self.assertIsNotNone(placed)
        for pid, *_ in placed:
            self.assertEqual(PART_MAP[pid]["colorName"], "深绿")
            self.assertEqual(PART_MAP[pid]["slope"], "/")

    def test_color_fallback_when_target_stock_empty(self):
        """设计色库存为 0 时应回退到其它颜色而不是失败，且不再出现目标色零件。"""
        inv = self._inventory()
        for p in PARTS:
            if p["colorName"] == "黄色":
                inv[p["id"]] = 0
        placed = tiler.solve_layer({(x, z): "#" for x in range(4) for z in range(2)},
                                   None, inv, random.Random(1), target_color="黄色",
                                   allow_fallback=True)
        self.assertIsNotNone(placed)
        colors = {PART_MAP[pid]["colorName"] for pid, *_ in placed}
        self.assertNotIn("黄色", colors)
        self.assertTrue(colors)

    def test_voxel_colors_counted_without_layer_color(self):
        """只有 colorRows、没有整层 color 时，方案 colors 也不能是空的。"""
        house = {"grid": {"w": 2, "d": 2}, "totalVoxels": 4, "layers": [{
            "y": 0, "rows": ["##", "##"], "color": None, "colorRows": ["RR", "RR"],
        }]}
        sol, fail = tiler.solve_with_budget(house, house["layers"], rounds=1, log=lambda *_: None)
        self.assertIsNotNone(sol, fail)
        self.assertGreater(sol["colors"].get("红色", 0), 0)

    def test_old_model_without_any_design_color_has_empty_distribution(self):
        """没有设计色的旧模型不编造配色分布。"""
        house = {"grid": {"w": 2, "d": 2}, "totalVoxels": 4, "layers": [{
            "y": 0, "rows": ["##", "##"],
        }]}
        sol, fail = tiler.solve_with_budget(house, house["layers"], rounds=1, log=lambda *_: None)
        self.assertIsNotNone(sol, fail)
        self.assertEqual(sol["colors"], {})

    def test_old_model_without_color_uses_legacy_ids(self):
        """旧模型没有 color 字段时，按默认色旧 id 铺贴（历史行为不变）。"""
        placed = tiler.solve_layer({(x, z): "#" for x in range(4) for z in range(2)},
                                   None, self._inventory(), random.Random(1), target_color=None)
        self.assertIsNotNone(placed)
        for pid, *_ in placed:
            self.assertEqual(pid, PART_MAP[pid]["shape"])


if __name__ == "__main__":
    unittest.main()
