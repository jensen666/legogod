# -*- coding: utf-8 -*-
"""部位契约测试。

覆盖：规划只收语义（boxes/coreBoxes 属协议错误）、稀疏标注生成区域和核心、
必需部位漏标、一格两属、标到空格/出网格、可选部位空掉删除、
小部位整块冻结与大部位只冻中心、修订删除保护。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import design_contract as dc  # noqa: E402
from legogod import part_binding as pb  # noqa: E402

DESC = "一艘三桅帆船，有船体、三根桅杆和船帆"


def _part(pid="hull", name="船体", required=True, source="船体"):
    return {"id": pid, "name": name, "required": required, "source": source}


def _model_from_cells(cells, w=8, d=8, n_layers=3):
    """cells: {(x,y,z)} → 构造 validate_design_syntax 产物的最小 model。"""
    layers = []
    for y in range(n_layers):
        rows = []
        for z in range(d):
            rows.append("".join("#" if (x, y, z) in cells else "." for x in range(w)))
        layer_cells = [[x, z] for (x, yy, z) in cells if yy == y]
        layers.append({"y": y, "rows": rows, "cells": layer_cells, "module": ["层"],
                       "color": None, "colorRows": None, "count": len(layer_cells)})
    return {"grid": {"w": w, "d": d}, "layers": layers,
            "totalVoxels": len(cells)}


def _hull_mast_scene():
    """hull：y=0 整层 64 格（大部位）；mast：x=z=3 的 y=1、y=2 两格（小部位）。"""
    hull = {(x, 0, z) for x in range(8) for z in range(8)}
    mast = {(3, 1, 3), (3, 2, 3)}
    model = _model_from_cells(hull | mast, w=8, d=8, n_layers=3)
    parts = [_part(), _part(pid="foremast", name="前桅杆", source="三根桅杆")]
    labels = {"defaultPart": "hull", "partPatches": [
        {"id": "foremast", "cells": [[3, 1, 3], [3, 2, 3]]}]}
    return parts, labels, model, hull, mast


class ParsePartsDeclTest(unittest.TestCase):
    def test_valid_semantic_plan_accepted(self):
        errs, parts = dc.parse_parts_decl([_part(), _part(pid="sail", name="帆", source="船帆")], DESC)
        self.assertEqual(errs, [])
        self.assertEqual([p["id"] for p in parts], ["hull", "sail"])
        self.assertEqual(set(parts[0]), set(dc.PART_KEYS))

    def test_missing_parts_is_error(self):
        errs, _ = dc.parse_parts_decl(None, DESC)
        self.assertTrue(any("缺失" in e for e in errs))
        errs, _ = dc.parse_parts_decl([], DESC)
        self.assertTrue(errs)

    def test_duplicate_id_rejected(self):
        errs, _ = dc.parse_parts_decl([_part(), _part()], DESC)
        self.assertTrue(any("重复" in e for e in errs))

    def test_required_part_missing_name_or_source(self):
        errs, _ = dc.parse_parts_decl([_part(name="", source="")], DESC)
        self.assertTrue(any("名称" in e for e in errs))
        self.assertTrue(any("来源" in e for e in errs))

    def test_source_must_appear_verbatim(self):
        errs, _ = dc.parse_parts_decl([_part(source="不存在的说法")], DESC)
        self.assertTrue(any("逐字" in e for e in errs))

    def test_boxes_in_plan_rejected(self):
        raw = {**_part(), "boxes": [{"x1": 0, "x2": 1, "y1": 0, "y2": 0, "z1": 0, "z2": 1}]}
        errs, _ = dc.parse_parts_decl([raw], DESC)
        self.assertTrue(any("boxes" in e for e in errs), errs)
        self.assertTrue(any("程序" in e for e in errs), errs)

    def test_core_boxes_in_plan_rejected(self):
        raw = {**_part(), "coreBoxes": [{"x1": 0, "x2": 0, "y1": 0, "y2": 0, "z1": 0, "z2": 0}]}
        errs, _ = dc.parse_parts_decl([raw], DESC)
        self.assertTrue(any("coreBoxes" in e for e in errs), errs)

    def test_optional_part_allows_empty_name_source(self):
        errs, parts = dc.parse_parts_decl([_part(pid="decor", required=False, name="", source="")], DESC)
        self.assertEqual(errs, [])
        self.assertFalse(parts[0]["required"])

    def test_role_defaults_to_solid(self):
        """role 已由 schema 支持：不写默认 solid，不需要新增字段。"""
        errs, parts = dc.parse_parts_decl([_part()], DESC)
        self.assertEqual(errs, [])
        self.assertEqual(parts[0]["role"], "solid")

    def test_surface_role_preserved(self):
        errs, parts = dc.parse_parts_decl(
            [{**_part(pid="eye", name="眼睛", source="船体"), "role": "surface"}], DESC)
        self.assertEqual(errs, [])
        self.assertEqual(parts[0]["role"], "surface")

    def test_invalid_role_rejected_with_examples(self):
        errs, _ = dc.parse_parts_decl(
            [{**_part(), "role": "decal"}], DESC)
        self.assertTrue(any("solid" in e and "surface" in e for e in errs), errs)
        self.assertTrue(any("眼睛" in e or "车灯" in e for e in errs), errs)


class ParsePartLabelsTest(unittest.TestCase):
    def test_default_part_and_patches_bind_cells(self):
        parts, labels, model, hull, mast = _hull_mast_scene()
        errs, assign, _warns = pb.parse_part_labels(labels, parts, model)
        self.assertEqual(errs, [])
        self.assertEqual(assign[(3, 1, 3)], "foremast")
        self.assertEqual(assign[(0, 0, 0)], "hull")
        self.assertEqual(set(assign), hull | mast)

    def test_missing_default_part_rejected(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        errs, _, _ = pb.parse_part_labels({"partPatches": []}, parts, model)
        self.assertTrue(any("defaultPart" in e for e in errs))

    def test_unknown_default_part_rejected(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        errs, _, _ = pb.parse_part_labels({"defaultPart": "deck", "partPatches": []}, parts, model)
        self.assertTrue(any("不是规划里的部位" in e for e in errs))

    def test_unknown_patch_id_rejected(self):
        """标注不能新增部位。"""
        parts, labels, model, _h, _m = _hull_mast_scene()
        errs, _, _ = pb.parse_part_labels(
            {"defaultPart": "hull", "partPatches": [{"id": "deck", "cells": [[0, 0, 0]]}]},
            parts, model)
        self.assertTrue(any("不能新增部位" in e for e in errs))

    def test_patch_on_empty_cell_ignored_with_warning(self):
        """标到空格只记警告并忽略该格，不整稿打回（画稿保留，进只标注阶段补救）。"""
        parts, labels, model, hull, mast = _hull_mast_scene()
        errs, assign, warns = pb.parse_part_labels(
            {"defaultPart": "hull", "partPatches": [{"id": "foremast", "cells": [[5, 1, 5]]}]},
            parts, model)
        self.assertEqual(errs, [])
        self.assertTrue(any("标到空格" in w for w in warns), warns)
        self.assertNotIn((5, 1, 5), assign, "空格不属于任何部位（无效标注被忽略）")

    def test_patch_out_of_grid_ignored_with_warning(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        errs, assign, warns = pb.parse_part_labels(
            {"defaultPart": "hull", "partPatches": [{"id": "foremast", "cells": [[9, 0, 0]]}]},
            parts, model)
        self.assertEqual(errs, [])
        self.assertTrue(any("标出网格" in w for w in warns), warns)

    def test_two_parts_same_cell_rejected(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        parts = parts + [_part(pid="sail", name="帆", source="船帆")]
        errs, _, _ = pb.parse_part_labels(
            {"defaultPart": "hull", "partPatches": [
                {"id": "foremast", "cells": [[0, 0, 0]]},
                {"id": "sail", "cells": [[0, 0, 0]]}]},
            parts, model)
        self.assertTrue(any("一格只能属于一个部位" in e for e in errs))

    def test_bad_cell_shape_ignored_with_warning(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        errs, _, warns = pb.parse_part_labels(
            {"defaultPart": "hull", "partPatches": [{"id": "foremast", "cells": [[0, 0]]}]},
            parts, model)
        self.assertEqual(errs, [])
        self.assertTrue(any("三个整数" in w for w in warns), warns)


class BindPartsTest(unittest.TestCase):
    def test_bind_generates_cells_boxes_and_cores(self):
        parts, labels, model, hull, mast = _hull_mast_scene()
        errs, bound, _ = pb.bind_parts(parts, labels, model)
        self.assertEqual(errs, [])
        by_id = {p["id"]: p for p in bound["parts"]}
        self.assertEqual(by_id["hull"]["cells"], hull)
        self.assertEqual(by_id["foremast"]["cells"], mast)
        self.assertTrue(by_id["hull"]["boxes"])
        self.assertEqual(by_id["foremast"]["core_cells"], {(3, 1, 3)},
                         "核心取连接格：桅杆底部与主体相邻的那格")
        self.assertEqual(by_id["hull"]["core_cells"], {(3, 0, 3)},
                         "主体核心取与其它部位的连接处")
        self.assertEqual(bound["removed"], [])

    def test_required_part_without_entity_is_error(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        parts = parts + [_part(pid="sail", name="帆", source="船帆")]
        errs, bound, _ = pb.bind_parts(parts, labels, model)
        self.assertIsNone(bound)
        self.assertTrue(any("sail" in e and "没有实体" in e for e in errs), errs)

    def test_invalid_label_cell_falls_into_label_gap(self):
        """标注标到空格被忽略后必需部位没有实体 → 绑定报错（主链进入只标注阶段）。"""
        parts, _labels, model, _h, _m = _hull_mast_scene()
        labels = {"defaultPart": "hull", "partPatches": [{"id": "foremast", "cells": [[5, 1, 5]]}]}
        errs, bound, warns = pb.bind_parts(parts, labels, model)
        self.assertIsNone(bound)
        self.assertTrue(any("foremast" in e and "没有实体" in e for e in errs), errs)
        self.assertTrue(warns)

    def test_invalid_label_cell_ignored_when_required_ok(self):
        """无效标注格被忽略、必需部位仍有实体：绑定成功并返回警告。"""
        parts, _labels, model, _h, mast = _hull_mast_scene()
        labels = {"defaultPart": "hull", "partPatches": [
            {"id": "foremast", "cells": [[3, 1, 3], [3, 2, 3], [5, 1, 5]]}]}
        errs, bound, warns = pb.bind_parts(parts, labels, model)
        self.assertEqual(errs, [], errs)
        self.assertTrue(any("标到空格" in w for w in warns), warns)
        by_id = {p["id"]: p for p in bound["parts"]}
        self.assertEqual(by_id["foremast"]["cells"], mast)

    def test_optional_part_without_entity_removed(self):
        parts, _labels, model, _h, _m = _hull_mast_scene()
        parts = parts + [_part(pid="decor", name="装饰", required=False, source="")]
        labels = {"defaultPart": "hull", "partPatches": [
            {"id": "foremast", "cells": [[3, 1, 3], [3, 2, 3]]}]}
        errs, bound, _ = pb.bind_parts(parts, labels, model)
        self.assertEqual(errs, [])
        self.assertEqual(bound["removed"], ["decor"])
        self.assertEqual([p["id"] for p in bound["parts"]], ["hull", "foremast"])

    def test_core_prefers_connected_cells(self):
        """核心优先取「与部位外实体相邻的连接格」，而不是几何中心。"""
        parts, labels, model, _h, _m = _hull_mast_scene()
        _, bound, _ = pb.bind_parts(parts, labels, model)
        by_id = {p["id"]: p for p in bound["parts"]}
        self.assertEqual(by_id["hull"]["core_cells"], {(3, 0, 3)})
        self.assertEqual(by_id["foremast"]["core_cells"], {(3, 1, 3)})
        self.assertLessEqual(len(by_id["hull"]["core_cells"]), pb.CONNECT_CORE_LIMIT)

    def test_isolated_part_core_near_center(self):
        """没有连接格（孤岛）时，核心从全部实体里取离中心最近的 min(8, n//2) 格。"""
        hull = {(x, 0, z) for x in range(3) for z in range(3)}
        island = {(x, 2, z) for x in range(6, 8) for z in range(6, 8)}
        model = _model_from_cells(hull | island, w=8, d=8, n_layers=3)
        parts = [_part(), _part(pid="flag", name="旗杆", source="小旗杆")]
        labels = {"defaultPart": "hull", "partPatches": [
            {"id": "flag", "cells": [[x, 2, z] for x in range(6, 8) for z in range(6, 8)]}]}
        _, bound, _ = pb.bind_parts(parts, labels, model)
        core = {p["id"]: p for p in bound["parts"]}["flag"]["core_cells"]
        self.assertEqual(len(core), 2, "孤岛核心 = min(8, 4//2)")
        self.assertTrue(core <= island)

    def test_two_required_parts_have_different_cores(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        _, bound, _ = pb.bind_parts(parts, labels, model)
        by_id = {p["id"]: p for p in bound["parts"]}
        self.assertNotEqual(by_id["hull"]["core_cells"], by_id["foremast"]["core_cells"])

    def test_frozen_cores_kept_on_rebind(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        _, bound, _ = pb.bind_parts(parts, labels, model)
        frozen = {p["id"]: p["core_cells"] for p in bound["parts"] if p["required"]}
        _, again = pb.rebuild_parts(parts, bound["assign"], model, frozen=frozen)
        by_id = {p["id"]: p for p in again["parts"]}
        self.assertEqual(by_id["hull"]["core_cells"], frozen["hull"])
        self.assertEqual(by_id["foremast"]["core_cells"], frozen["foremast"])

    def test_frozen_core_lost_is_error(self):
        parts, labels, model, _h, _m = _hull_mast_scene()
        frozen = {"hull": {(7, 7, 0)}, "foremast": {(3, 1, 3)}}
        errs, _, _ = pb.bind_parts(parts, labels, model, frozen=frozen)
        self.assertTrue(any("冻结核心" in e for e in errs), errs)


class RegionBoxesTest(unittest.TestCase):
    def _cells_of_boxes(self, boxes):
        out = set()
        for b in boxes:
            for x in range(b["x1"], b["x2"] + 1):
                for y in range(b["y1"], b["y2"] + 1):
                    for z in range(b["z1"], b["z2"] + 1):
                        out.add((x, y, z))
        return out

    def test_rect_cover_matches_cells(self):
        cells = {(0, 0, 0), (1, 0, 0), (0, 0, 1), (3, 0, 3)}
        boxes = pb.region_boxes(cells)
        self.assertEqual(self._cells_of_boxes(boxes), cells)

    def test_same_outline_layers_merged(self):
        cells = {(x, y, z) for x in range(4) for z in range(2) for y in (0, 1)}
        boxes = pb.region_boxes(cells)
        self.assertEqual(len(boxes), 1, boxes)
        self.assertEqual((boxes[0]["y1"], boxes[0]["y2"]), (0, 1))

    def test_different_outline_layers_not_merged(self):
        cells = {(x, 0, z) for x in range(4) for z in range(2)}
        cells |= {(x, 1, z) for x in range(2) for z in range(1)}
        boxes = pb.region_boxes(cells)
        self.assertGreaterEqual(len(boxes), 2)
        self.assertEqual(self._cells_of_boxes(boxes), cells)


def _layers(w=6, d=4, n=2, solid_rows=None):
    return [{"module": "层%d" % y, "color": "浅灰",
             "rows": list(solid_rows or ["#" * w for _ in range(d)])}
            for y in range(n)]


def _solid(layers):
    out = set()
    for y, L in enumerate(layers):
        for z, row in enumerate(L["rows"]):
            for x, c in enumerate(row):
                if c != ".":
                    out.add((x, y, z))
    return out


class PatchPartRulesTest(unittest.TestCase):
    """修订补丁：删除受保护格、新增实体归属、不再接受 parts 区域更新。"""

    def _ctx(self, layers, assign=None, frozen=None, default="hull", part_ids=None):
        solid = _solid(layers)
        return {
            "base_revision": "r001", "layers": layers,
            "allowed_cells": {(x, y, z) for y in range(len(layers))
                              for x in range(len(layers[0]["rows"][0]))
                              for z in range(len(layers[0]["rows"]))},
            "frozen_cells": frozen or set(),
            "assignment": assign if assign is not None else {c: "hull" for c in solid},
            "part_ids": part_ids if part_ids is not None else ["hull"],
            "default_part": default,
        }

    def test_delete_more_than_half_of_part_rejected(self):
        """单部位单稿最多删当前实体的一半（通用规则，不按部位大小分档）。"""
        layers = _layers(w=2, d=2, n=1)  # 4 个实体格，cap = 2
        edits = [{"x": x, "y": 0, "z": z, "voxel": "."} for x in range(2) for z in range(2)]
        errs, _ = dc.patch_errors({"baseRevision": "r001", "edits": edits},
                                  self._ctx(layers))
        self.assertTrue(any("1/2" in e for e in errs), errs)

    def test_delete_up_to_half_of_part_allowed(self):
        layers = _layers(w=2, d=2, n=1)  # 4 格，删 2 格正好一半
        edits = [{"x": 0, "y": 0, "z": 0, "voxel": "."}, {"x": 1, "y": 0, "z": 0, "voxel": "."}]
        errs, meta = dc.patch_errors({"baseRevision": "r001", "edits": edits},
                                     self._ctx(layers))
        self.assertEqual(errs, [], errs)
        self.assertEqual(meta["geo_changes"], 2)

    def test_delete_noncore_cell_of_large_part_allowed(self):
        layers = _layers()  # 48 个实体格 > 32
        errs, meta = dc.patch_errors(
            {"baseRevision": "r001", "edits": [{"x": 0, "y": 0, "z": 1, "voxel": "."}]},
            self._ctx(layers))
        self.assertEqual(errs, [])
        self.assertEqual(meta["geo_changes"], 1)

    def test_delete_frozen_core_rejected(self):
        layers = _layers()
        errs, _ = dc.patch_errors(
            {"baseRevision": "r001", "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "."}]},
            self._ctx(layers, frozen={(0, 0, 0)}))
        self.assertTrue(any("核心格不可删除" in e for e in errs), errs)

    def test_color_edit_on_frozen_core_allowed(self):
        """核心格只禁止删除：换色/实体字符变化不改变部位身份，允许。"""
        layers = _layers()
        errs, meta = dc.patch_errors(
            {"baseRevision": "r001",
             "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "棕色"}]},
            self._ctx(layers, frozen={(0, 0, 0)}))
        self.assertEqual(errs, [], errs)
        self.assertEqual(meta["geo_changes"], 0)
        self.assertEqual(meta["color_changes"], 1)

    def test_new_solid_without_part_goes_to_default(self):
        layers = _layers(w=4, d=2, solid_rows=["##.#", "####"])
        errs, meta = dc.patch_errors(
            {"baseRevision": "r001", "edits": [{"x": 2, "y": 0, "z": 0, "voxel": "#"}]},
            self._ctx(layers))
        self.assertEqual(errs, [])
        self.assertEqual(meta["new_part_assign"], {(2, 0, 0): "hull"})

    def test_new_solid_with_part_recorded(self):
        layers = _layers(w=4, d=2, solid_rows=["##.#", "####"])
        errs, meta = dc.patch_errors(
            {"baseRevision": "r001",
             "edits": [{"x": 2, "y": 0, "z": 0, "voxel": "#", "part": "mast"}]},
            self._ctx(layers, part_ids=["hull", "mast"]))
        self.assertEqual(errs, [])
        self.assertEqual(meta["new_part_assign"], {(2, 0, 0): "mast"})

    def test_new_solid_unknown_part_rejected(self):
        layers = _layers(w=4, d=2, solid_rows=["##.#", "####"])
        errs, _ = dc.patch_errors(
            {"baseRevision": "r001",
             "edits": [{"x": 2, "y": 0, "z": 0, "voxel": "#", "part": "deck"}]},
            self._ctx(layers, part_ids=["hull"]))
        self.assertTrue(any("不能新增部位" in e for e in errs))

    def test_parts_region_update_rejected(self):
        layers = _layers()
        errs, _ = dc.patch_errors(
            {"baseRevision": "r001", "edits": [], "parts": [{"id": "hull"}]},
            self._ctx(layers))
        self.assertTrue(any("不能携带" in e for e in errs))

    def test_boxes_in_patch_rejected(self):
        layers = _layers()
        errs, _ = dc.patch_errors(
            {"baseRevision": "r001", "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#"}],
             "boxes": []},
            self._ctx(layers))
        self.assertTrue(any("不能携带" in e for e in errs))


class CellHelpersTest(unittest.TestCase):
    def test_cells_to_lists_sorted_and_capped(self):
        cells = {(x, 0, 0) for x in range(10)}
        lists = dc.cells_to_lists(cells, cap=5)
        self.assertEqual(len(lists), 5)
        self.assertEqual(lists[0], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
