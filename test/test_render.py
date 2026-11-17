# -*- coding: utf-8 -*-
"""高保真模式基础测试：逐体素配色、多视角渲染、评审 JSON 解析。"""
import json
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
from legogod.parts_library import CHAR_COLORS, voxel_color_map  # noqa: E402
from legogod.render import compose_sheet, render_views, voxel_colors  # noqa: E402
from legogod.review import _parse_json  # noqa: E402


def _plan(rows, color_rows):
    return {
        "name": "配色测试", "slug": "color-test", "features": ["测试"],
        "layers": [{"module": "层", "rows": rows, "colorRows": color_rows}],
    }


class VoxelColorDesignTest(unittest.TestCase):
    def test_color_rows_are_accepted_and_saved(self):
        errs, model, _warns = validate_plan(_plan(["##", "##"], ["RW", "YK"]))
        self.assertEqual(errs, [])
        layer = model["layers"][0]
        self.assertEqual(layer["colorRows"], ["RW", "YK"])
        self.assertTrue(model["hasVoxelColors"])
        cmap = voxel_color_map(layer["rows"], layer["colorRows"], layer["color"])
        self.assertEqual(cmap[(0, 0)], "红色")
        self.assertEqual(cmap[(1, 0)], "白色")
        self.assertEqual(cmap[(1, 1)], "黑色")

    def test_missing_color_char_is_rejected(self):
        errs, model, _warns = validate_plan(_plan(["##", "##"], ["W.", ".."]))
        self.assertIsNone(model)
        self.assertTrue(any("缺少颜色字符" in e for e in errs), errs)

    def test_illegal_color_char_is_rejected(self):
        errs, model, _warns = validate_plan(_plan(["##", "##"], ["W!", "Y."]))
        self.assertIsNone(model)
        self.assertTrue(any("非法颜色字符" in e for e in errs), errs)

    def test_layer_color_still_works_without_color_rows(self):
        plan = {
            "name": "层色", "slug": "layer-color", "features": ["测试"],
            "layers": [{"module": "层", "color": "红色", "rows": ["##", "##"]}],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertEqual(errs, [])
        self.assertFalse(model["hasVoxelColors"])

    def test_color_fragmentation_is_rejected(self):
        """颜色碎片导致某格没有任何同色砖能跨接支撑：设计阶段就应拒绝。"""
        plan = {
            "name": "碎片", "slug": "frag", "features": ["测试"],
            "layers": [
                {"module": "底", "rows": ["#.#"], "colorRows": ["RRR"]},
                {"module": "面", "rows": ["###"], "colorRows": ["RWB"]},
            ],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertIsNone(model)
        self.assertTrue(any("同色" in e or "得不到支撑" in e for e in errs), errs)

    def test_sparse_color_patches_expand(self):
        """稀疏颜色覆盖：只写特殊格，程序展开成完整 colorRows。"""
        plan = {
            "name": "补丁", "slug": "patch", "features": ["测试"],
            "layers": [{
                "module": "层", "color": "白色", "rows": ["####"],
                "colorPatches": [
                    {"color": "黑色", "cells": [[1, 0]]},
                    {"color": "红色", "cells": [[2, 0]]},
                ],
            }],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertEqual(errs, [])
        self.assertEqual(model["layers"][0]["colorRows"], ["WKRW"])
        self.assertTrue(model["hasVoxelColors"])

    def test_sparse_patch_invalid_cell_is_rejected(self):
        plan = {
            "name": "补丁", "slug": "patch2", "features": ["测试"],
            "layers": [{
                "module": "层", "color": "白色", "rows": ["####"],
                "colorPatches": [{"color": "黑色", "cells": [[9, 0]]}],
            }],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertIsNone(model)
        self.assertTrue(any("不是实体体素" in e for e in errs), errs)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-render-")
        rows = ["######", "######", "######"]
        color_rows = ["RRRRRR", "BBBBBB", "WWWWWW"]
        self.model = {
            "grid": {"w": 6, "d": 3}, "totalVoxels": 18,
            "layers": [{"y": 0, "rows": rows, "colorRows": color_rows, "color": None,
                        "cells": [[x, z] for z in range(3) for x in range(6)]}],
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_views_produces_four_pngs(self):
        paths = render_views(self.model, None, self.tmp, scale=8)
        self.assertEqual(set(paths), {"front", "side", "top", "iso"})
        for path in paths.values():
            self.assertTrue(os.path.isfile(path), path)
            self.assertGreater(os.path.getsize(path), 100, path)

    def test_voxel_colors_use_color_rows(self):
        colors = voxel_colors(self.model)
        self.assertEqual(colors[(0, 0, 0)], "#C4281B")  # 红色
        self.assertEqual(colors[(0, 0, 1)], "#0055BF")  # 蓝色
        self.assertEqual(colors[(0, 0, 2)], "#F2F3F2")  # 白色

    def test_compose_sheet(self):
        paths = render_views(self.model, None, self.tmp, scale=8)
        sheet = compose_sheet(list(paths.values()), os.path.join(self.tmp, "sheet.png"))
        self.assertTrue(os.path.isfile(sheet))
        self.assertGreater(os.path.getsize(sheet), 500)


class ReviewParseTest(unittest.TestCase):
    def test_parse_json_with_noise(self):
        text = '好的，评审如下：\n{"scores": {"overall": 8}, "suggestions": ["加高车顶"]}\n谢谢'
        parsed = _parse_json(text)
        self.assertEqual(parsed["scores"]["overall"], 8)
        self.assertEqual(parsed["suggestions"], ["加高车顶"])

    def test_parse_invalid_returns_none(self):
        self.assertIsNone(_parse_json("没有 JSON"))
        self.assertIsNone(_parse_json(""))


if __name__ == "__main__":
    unittest.main()
