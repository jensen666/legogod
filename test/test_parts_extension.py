# -*- coding: utf-8 -*-
"""零件扩展与斜坡渲染测试。

覆盖：1×6/1×8/2×3/2×6/2×8 矩形、米白/深棕/藏蓝候选颜色的色值、同色铺砖、
库存回退、颜色碎片；四种现有斜坡在评审 PNG 中按坡向渲染（像素级检查），
普通体素不回归。
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import validate_plan  # noqa: E402
from legogod import tiler  # noqa: E402
from legogod.parts_library import (  # noqa: E402
    COLOR_CHARS, COLORS, PARTS, PART_MAP, SHAPES, part_for,
)
from legogod.render import render_views  # noqa: E402

from PIL import Image  # noqa: E402

BG = (250, 250, 250)


class NewRectShapesTest(unittest.TestCase):
    def test_new_rectangles_exist_with_correct_dims(self):
        for sid, (w, d) in (("B1x6", (1, 6)), ("B1x8", (1, 8)), ("B2x3", (2, 3)),
                            ("B2x6", (2, 6)), ("B2x8", (2, 8))):
            sh = next(s for s in SHAPES if s["id"] == sid)
            self.assertEqual((sh["w"], sh["d"]), (w, d), sid)
            self.assertEqual(part_for(sid, sh["defaultColor"])["id"], sid,
                             "默认色零件沿用旧 id")

    def test_new_rectangles_in_every_color(self):
        for sid in ("B1x6", "B1x8", "B2x3", "B2x6", "B2x8"):
            for name in COLORS:
                self.assertIsNotNone(part_for(sid, name), f"{sid} 缺少颜色 {name}")

    def test_brick_sizes_cover_new_shapes(self):
        for size in ((1, 6), (6, 1), (1, 8), (8, 1), (2, 3), (3, 2),
                     (2, 6), (6, 2), (2, 8), (8, 2)):
            self.assertIn(size, tiler.BRICK_SIZES)

    def test_tiler_uses_long_bricks(self):
        """1×8 条带应被 1x8 砖覆盖（大砖优先）。"""
        typed = {(x, 0): "#" for x in range(8)}
        inv = {p["id"]: p["count"] for p in PARTS}
        placed = tiler.solve_layer(typed, None, inv, __import__("random").Random(1),
                                   target_color="白色")
        self.assertIsNotNone(placed)
        self.assertIn("B1x8", {pid for pid, *_ in placed})


class CandidateColorsTest(unittest.TestCase):
    def test_candidate_color_values(self):
        self.assertEqual(COLORS["米白"]["hex"], "#E4CD9E")
        self.assertEqual(COLORS["深棕"]["hex"], "#352100")
        self.assertEqual(COLORS["藏蓝"]["hex"], "#0A3463")

    def test_candidate_color_chars(self):
        self.assertEqual(COLOR_CHARS["米白"], "M")
        self.assertEqual(COLOR_CHARS["深棕"], "U")
        self.assertEqual(COLOR_CHARS["藏蓝"], "I")

    def test_same_color_tiling_with_new_color(self):
        """藏蓝 2×4 面板按设计色同色铺砖。"""
        typed = {(x, z): "#" for x in range(4) for z in range(2)}
        inv = {p["id"]: p["count"] for p in PARTS}
        placed = tiler.solve_layer(typed, None, inv, __import__("random").Random(2),
                                   target_color="藏蓝")
        self.assertIsNotNone(placed)
        self.assertEqual({PART_MAP[pid]["colorName"] for pid, *_ in placed}, {"藏蓝"})

    def test_stock_fallback_for_new_color(self):
        """深棕库存为 0：回退到其它颜色而不是失败。"""
        inv = {p["id"]: p["count"] for p in PARTS}
        for p in PARTS:
            if p["colorName"] == "深棕":
                inv[p["id"]] = 0
        placed = tiler.solve_layer({(x, z): "#" for x in range(4) for z in range(2)},
                                   None, inv, __import__("random").Random(3),
                                   target_color="深棕", allow_fallback=True)
        self.assertIsNotNone(placed)
        self.assertNotIn("深棕", {PART_MAP[pid]["colorName"] for pid, *_ in placed})

    def test_color_fragmentation_with_new_color_rejected(self):
        """米白孤立单格悬在空位上方且无法同色搭接：设计预检拒绝。"""
        plan = {
            "name": "碎片", "slug": "frag-tan", "features": ["测试"],
            "layers": [
                {"module": "底", "color": "红色", "rows": ["#.#"]},
                {"module": "面", "color": "红色", "rows": ["###"],
                 "colorPatches": [{"color": "米白", "cells": [[1, 0]]}]},
            ],
        }
        errs, model, _ = validate_plan(plan)
        self.assertIsNone(model)
        self.assertTrue(any("得不到支撑" in e or "同色" in e for e in errs), errs)


class SlopeRenderingTest(unittest.TestCase):
    """四种斜坡按坡向渲染：正视图中 '/' 与 '\\' 是方向相反的三角，'^'/'v' 为整面。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-slope-")
        self.model = {
            "grid": {"w": 4, "d": 1}, "totalVoxels": 4,
            "layers": [{"y": 0, "rows": ["/\\^v"],
                        "cells": [[0, 0], [1, 0], [2, 0], [3, 0]],
                        "module": ["坡"], "color": "浅灰", "colorRows": None, "count": 4}],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _front(self):
        paths = render_views(self.model, None, self.tmp, scale=20)
        return Image.open(paths["front"]).convert("RGB"), paths

    def test_all_views_rendered(self):
        _, paths = self._front()
        for key in ("front", "side", "top", "iso"):
            self.assertGreater(os.path.getsize(paths[key]), 100, key)

    def test_slope_up_right_triangle(self):
        """'/'（左低右高）：右上实、左上空。"""
        img, _ = self._front()
        self.assertEqual(img.getpixel((3, 3)), BG, "高端在右，左上应为背景")
        self.assertNotEqual(img.getpixel((18, 6)), BG, "右上是斜面实体")
        self.assertNotEqual(img.getpixel((10, 17)), BG, "底部应填充")

    def test_slope_up_left_triangle(self):
        """'\\'（左高右低，第 2 格）：左上实、右上空。"""
        img, _ = self._front()
        self.assertNotEqual(img.getpixel((25, 15)), BG, "左上是斜面实体")
        self.assertEqual(img.getpixel((37, 3)), BG, "高端在左，右上应为背景")

    def test_z_slopes_full_face_in_front_view(self):
        """'^'/'v' 坡向沿视线：正视为整面（不再画成三角）。"""
        img, _ = self._front()
        for px in (43, 57, 63, 77):
            self.assertNotEqual(img.getpixel((px, 3)), BG, f"('^'/'v') 整面 ({px},3)")
            self.assertNotEqual(img.getpixel((px, 17)), BG)

    def test_plain_voxel_still_full_square(self):
        """普通 '#' 体素不回归：仍是整面方块。"""
        model = {"grid": {"w": 1, "d": 1}, "totalVoxels": 1,
                 "layers": [{"y": 0, "rows": ["#"], "cells": [[0, 0]],
                             "module": ["层"], "color": "浅灰", "colorRows": None, "count": 1}]}
        paths = render_views(model, None, self.tmp, scale=20)
        img = Image.open(paths["front"]).convert("RGB")
        self.assertNotEqual(img.getpixel((5, 5)), BG)
        self.assertNotEqual(img.getpixel((15, 15)), BG)

    def test_top_view_shows_gradient_direction(self):
        """顶视沿坡向明暗分段：'/' 低端（x 小）更暗、高端更亮。"""
        paths = render_views(self.model, None, self.tmp, scale=30)
        img = Image.open(paths["top"]).convert("RGB")

        def brightness(px):
            r, g, b = img.getpixel(px)
            return r + g + b

        low = brightness((5, 15))    # '/' 低端（x=0 段，像素 1..10）
        high = brightness((25, 15))  # '/' 高端（x=0+2/3 段，像素 21..30）
        self.assertLess(low, high, "顶视应能看出坡向（低端更暗）")

    def test_iso_renders_slope_wedge(self):
        """等轴测对斜面体素画斜面楔体（与方块渲染结果不同）。"""
        paths = render_views(self.model, None, self.tmp, scale=20)
        plain = {"grid": {"w": 4, "d": 1}, "totalVoxels": 4,
                 "layers": [{"y": 0, "rows": ["####"], "cells": [[x, 0] for x in range(4)],
                             "module": ["坡"], "color": "浅灰", "colorRows": None, "count": 4}]}
        plain_paths = render_views(plain, None, self.tmp, scale=20, name_prefix="plain")
        with open(paths["iso"], "rb") as f1, open(plain_paths["iso"], "rb") as f2:
            self.assertNotEqual(f1.read(), f2.read(), "斜坡楔体与方块渲染应不同")


if __name__ == "__main__":
    unittest.main()
