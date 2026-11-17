# -*- coding: utf-8 -*-
"""revise_design 补丁测试。

覆盖：版本过期、越界、重复、超出 allowedCells、32/33 格边界、网格尺寸变化、
冻结核心与小必需部位保护、新增实体的部位归属、换色落到 colorRows。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import design_contract as dc  # noqa: E402
from legogod.workflow import _Chain  # noqa: E402


def _layers(w=6, d=4, n=2, ch="#"):
    return [{"module": "层%d" % y, "color": "浅灰",
             "rows": ["".join(ch for _ in range(w)) for _ in range(d)]}
            for y in range(n)]


def _solid(layers):
    solid = set()
    for y, L in enumerate(layers):
        for z, row in enumerate(L["rows"]):
            for x, c in enumerate(row):
                if c != ".":
                    solid.add((x, y, z))
    return solid


def _ctx(layers, allowed=None, frozen=None, base="r001"):
    return {"base_revision": base, "layers": layers,
            "allowed_cells": allowed if allowed is not None else
            {(x, y, z) for y in range(len(layers))
             for x in range(len(layers[0]["rows"][0])) for z in range(len(layers[0]["rows"]))},
            "frozen_cells": frozen or set()}


def _edits(cells, voxel="/", color=None):
    out = []
    for (x, y, z) in cells:
        e = {"x": x, "y": y, "z": z, "voxel": voxel}
        if color:
            e["color"] = color
        out.append(e)
    return out


class PatchPolicyTest(unittest.TestCase):
    def test_valid_patch_passes(self):
        layers = _layers()
        errs, meta = dc.patch_errors({"baseRevision": "r001", "edits": _edits([(0, 0, 0)])},
                                     _ctx(layers))
        self.assertEqual(errs, [])
        self.assertEqual(meta["geo_changes"], 1)

    def test_stale_base_revision_rejected(self):
        errs, _ = dc.patch_errors({"baseRevision": "r002", "edits": _edits([(0, 0, 0)])},
                                  _ctx(_layers(), base="r001"))
        self.assertTrue(any("版本过期" in e for e in errs))

    def test_out_of_bounds_rejected(self):
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": [{"x": 99, "y": 0, "z": 0, "voxel": "#"}]},
                                  _ctx(_layers()))
        self.assertTrue(any("越界" in e for e in errs))

    def test_negative_coords_rejected(self):
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": [{"x": -1, "y": 0, "z": 0, "voxel": "#"}]},
                                  _ctx(_layers()))
        self.assertTrue(any("越界" in e for e in errs))

    def test_duplicate_cell_rejected(self):
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": _edits([(0, 0, 0), (0, 0, 0)])},
                                  _ctx(_layers()))
        self.assertTrue(any("同一格" in e for e in errs))

    def test_edit_outside_allowed_cells_rejected(self):
        layers = _layers()
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": _edits([(0, 0, 0)])},
                                  _ctx(layers, allowed={(1, 0, 0)}))
        self.assertTrue(any("allowedCells" in e for e in errs))

    def test_frozen_cell_rejected(self):
        """防删核心格不可删除（换色允许；见 test_design_contract 的补丁规则用例）。"""
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": _edits([(0, 0, 0)], voxel=".")},
                                  _ctx(_layers(), frozen={(0, 0, 0)}, allowed={(0, 0, 0)}))
        self.assertTrue(any("核心格不可删除" in e for e in errs))

    def test_32_geo_changes_ok_33_rejected(self):
        layers = _layers(w=6, d=6, n=2)  # 72 个实体格
        cells = sorted(_solid(layers))[:33]
        errs, meta = dc.patch_errors({"baseRevision": "r001", "edits": _edits(cells[:32])},
                                     _ctx(layers))
        self.assertEqual(errs, [], errs)
        self.assertEqual(meta["geo_changes"], 32)
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": _edits(cells[:33])},
                                  _ctx(layers))
        self.assertTrue(any("超过每稿上限" in e for e in errs))

    def test_same_voxel_edit_is_not_geometric(self):
        """voxel 与现状相同的编辑不算几何改动（纯换色由 color_changes 计数）。"""
        layers = _layers()
        errs, meta = dc.patch_errors(
            {"baseRevision": "r001", "edits": _edits([(0, 0, 0)], voxel="#", color="棕色")},
            _ctx(layers))
        self.assertEqual(errs, [])
        self.assertEqual(meta["geo_changes"], 0)
        self.assertEqual(meta["color_changes"], 1)

    def test_illegal_voxel_char_rejected(self):
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "X"}]},
                                  _ctx(_layers()))
        self.assertTrue(any("voxel" in e for e in errs))

    def test_illegal_color_rejected(self):
        errs, _ = dc.patch_errors(
            {"baseRevision": "r001", "edits": _edits([(0, 0, 0)], voxel="#", color="紫色")},
            _ctx(_layers()))
        self.assertTrue(any("颜色" in e for e in errs))

    def test_parts_region_update_rejected(self):
        """修订不再接受 parts 区域更新：区域由程序按实体与标注推导。"""
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": [],
                                   "parts": [{"id": "hull", "boxes": []}]},
                                  _ctx(_layers()))
        self.assertTrue(any("不能携带" in e for e in errs), errs)

    def test_empty_patch_rejected(self):
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": []}, _ctx(_layers()))
        self.assertTrue(any("缺少 edits" in e for e in errs))


class ReviseSchemaTest(unittest.TestCase):
    """补丁不能整模重画：禁止携带 layers/grid/rows。"""

    def setUp(self):
        self.chain = _Chain("测试")

    def test_layers_key_rejected(self):
        errs = self.chain._check_revise_schema({"baseRevision": "r001", "edits": [], "layers": []})
        self.assertTrue(any("layers" in e for e in errs))

    def test_grid_key_rejected(self):
        errs = self.chain._check_revise_schema({"baseRevision": "r001", "edits": [], "grid": {"w": 4}})
        self.assertTrue(any("grid" in e for e in errs))

    def test_missing_base_revision_rejected(self):
        errs = self.chain._check_revise_schema({"edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#"}]})
        self.assertTrue(any("baseRevision" in e for e in errs))

    def test_valid_patch_schema_ok(self):
        errs = self.chain._check_revise_schema(
            {"baseRevision": "r001", "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#"}]})
        self.assertEqual(errs, [])


class ApplyEditsTest(unittest.TestCase):
    def test_voxel_edit_applied(self):
        layers = _layers()
        errs, new_layers = dc.apply_edits(layers, _edits([(2, 1, 3)], voxel="."))
        self.assertEqual(errs, [])
        self.assertEqual(new_layers[1]["rows"][3][2], ".")
        self.assertEqual(layers[1]["rows"][3][2], "#", "原 layers 不应被修改")

    def test_color_edit_expands_color_rows(self):
        layers = _layers()
        self.assertIsNone(layers[0].get("colorRows"))
        errs, new_layers = dc.apply_edits(layers, _edits([(1, 0, 0)], voxel="#", color="棕色"))
        self.assertEqual(errs, [])
        cr = new_layers[0]["colorRows"]
        self.assertEqual(len(cr), 4)
        self.assertEqual(cr[0][1], "T")   # 棕色
        self.assertEqual(cr[0][0], "L")   # 其余补默认层色浅灰
        self.assertEqual(cr[1][1], "L")

    def test_color_edit_on_existing_color_rows(self):
        layers = _layers()
        layers[0]["colorRows"] = ["LLLL", "LLLL", "LLLL", "LLLL"]
        errs, new_layers = dc.apply_edits(layers, _edits([(0, 0, 0)], voxel="#", color="米白"))
        self.assertEqual(errs, [])
        self.assertEqual(new_layers[0]["colorRows"][0][0], "M")

    def test_layers_key_cannot_change_grid_size(self):
        """edits 无法改变网格尺寸：坐标受网格约束，尺寸字段被 schema 拒绝（见 ReviseSchemaTest）。"""
        layers = _layers(w=3, d=3)
        errs, _ = dc.patch_errors({"baseRevision": "r001",
                                   "edits": [{"x": 5, "y": 0, "z": 5, "voxel": "#"}]},
                                  _ctx(layers))
        self.assertTrue(any("越界" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
