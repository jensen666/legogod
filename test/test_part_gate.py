# -*- coding: utf-8 -*-
"""双角色部位突显门禁测试。

覆盖：贴花画圈（同色/异色）拦截、单格突起拦截、真实凸出/截面环/薄壁通过、
表面涂装部位的内埋/同色/占比拦截与合法涂装通过。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.part_gate import check_parts  # noqa: E402
from legogod import part_binding as pb  # noqa: E402


def _model_from_layers(rows_by_layer, color_rows=None):
    layers = []
    for y, rows in enumerate(rows_by_layer):
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        cr = (color_rows or {}).get(y)
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["层"],
                       "color": "浅灰", "colorRows": cr, "count": len(cells)})
    return {"grid": {"w": len(rows_by_layer[0][0]), "d": len(rows_by_layer[0])},
            "totalVoxels": sum(len(L["cells"]) for L in layers), "layers": layers}


def _model_with_colors(rows_by_layer, paint):
    """paint: {(x,y,z): 颜色名} → colorRows（'K'=黑 'L'=浅灰，见 parts_library.COLOR_CHARS）。"""
    color_rows = {}
    for y, rows in enumerate(rows_by_layer):
        color_rows[y] = ["".join({"黑色": "K", "浅灰": "L"}.get(paint.get((x, y, z)), "L")
                                 if c != "." else "."
                                 for x, c in enumerate(row))
                         for z, row in enumerate(rows)]
    return _model_from_layers(rows_by_layer, color_rows)


def _parts(model, assign):
    errs, bound = pb.rebuild_parts(
        [{"id": "body", "name": "主体", "required": True, "source": "主体", "role": "solid"}],
        assign, model)
    assert not errs, errs
    return bound["parts"]


class SolidGateTest(unittest.TestCase):
    def test_four_cell_face_decal_rejected(self):
        """墙面 2×2 贴花两侧并不都露空，不能按薄壁通过。"""
        rows = ["######", "######", "######", "######"]
        model = _model_from_layers([rows, rows])
        badge = {(2, 0, 3), (3, 0, 3), (2, 1, 3), (3, 1, 3)}
        body = {(x, y, z) for x in range(6) for y in range(2) for z in range(4)} - badge
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": body},
                 {"id": "badge", "name": "贴花", "required": True, "source": "贴花",
                  "role": "solid", "cells": badge}]
        errs, _cells = check_parts(model, parts)
        self.assertTrue(any("badge" in e for e in errs), errs)

    def test_decal_on_flat_wall_rejected_even_recolored(self):
        """同轮廓实心块侧面抠格子的贴花：换色也不免检几何。"""
        rows = ["######", "######", "######", "######"]
        model = _model_from_layers([rows, rows, rows])
        # 「徽章」= 墙面中间 2 格（x=2..3, y=1, z=3），唯一空气面是前表面
        assign = {(x, y, z): ("badge" if (y == 1 and z == 3 and x in (2, 3)) else "body")
                  for x in range(6) for y in range(3) for z in range(4)}
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": {c for c, p in assign.items() if p == "body"}},
                 {"id": "badge", "name": "徽章", "required": True, "source": "徽章",
                  "role": "solid", "cells": {c for c, p in assign.items() if p == "badge"}}]
        errs, _cells = check_parts(model, parts)
        self.assertTrue(any("badge" in e for e in errs), errs)

    def test_single_cell_bump_rejected(self):
        rows = ["####", "####", "####"]
        model = _model_from_layers([rows])
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": {(0, 0, 0), (1, 0, 0), (2, 0, 0)}},
                 {"id": "bump", "name": "突起", "required": True, "source": "突起",
                  "role": "solid", "cells": {(3, 0, 0)}}]
        errs, _cells = check_parts(model, parts)
        self.assertTrue(any("bump" in e for e in errs), errs)

    def test_outward_extension_passes(self):
        """悬臂手臂：空气面 > 贴合面 → ① 通过。"""
        rows = ["###...", "###...", "###...", "###..."]
        model = _model_from_layers([rows])
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": {(x, 0, z) for x in (0, 1, 2) for z in range(4)}},
                 {"id": "arm", "name": "手臂", "required": True, "source": "手臂",
                  "role": "solid", "cells": {(3, 0, 1), (4, 0, 1)}}]
        errs, _cells = check_parts(model, parts)
        self.assertEqual([e for e in errs if "arm" in e], [], errs)

    def test_ring_with_step_passes(self):
        """上下串联承载型：某层占满截面环 + 轮廓阶跃 → ② 通过。"""
        y0 = ["#####", "#...#", "#...#", "#####"]
        y1 = ["#####", "#...#", "#...#", "#####"]
        y2 = ["#####", "#####", "#####", "#####"]
        model = _model_from_layers([y0, y1, y2])
        wall = {(x, y, z) for y in (0, 1, 2)
                for x in range(5) for z in range(4)
                if x in (0, 4) or z in (0, 3) or y == 2}
        parts = [{"id": "tower", "name": "塔身", "required": True, "source": "塔身",
                  "role": "solid", "cells": wall}]
        errs, _cells = check_parts(model, parts)
        self.assertEqual(errs, [], errs)

    def test_thin_sheet_passes(self):
        """薄壁/斜面型：某层一轴 ≥4 且另一轴 ≤2 → ③ 通过。"""
        rows = ["..##..", "..##..", "..##..", "..##..", "..##..", "..##.."]
        model = _model_from_layers([rows])
        cells = {(2, 0, z) for z in range(6)} | {(3, 0, z) for z in range(6)}
        parts = [{"id": "sail", "name": "风帆", "required": True, "source": "风帆",
                  "role": "solid", "cells": cells}]
        errs, _cells = check_parts(model, parts)
        self.assertEqual(errs, [], errs)

    def test_two_thick_buried_core_passes(self):
        """空气面不多于贴合面，但接触方向厚度为 2 的内核是宿主，不再当贴花拒绝。"""
        rows = ["#####"] * 5
        model = _model_from_layers([rows, rows, rows, rows])
        core = {(x, y, z) for x in range(1, 4) for y in (1, 2) for z in range(1, 4)}
        body = {(x, y, z) for x in range(5) for y in range(4) for z in range(5)} - core
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": body},
                 {"id": "core", "name": "内核", "required": True, "source": "内核",
                  "role": "solid", "cells": core}]
        errs, _cells = check_parts(model, parts)
        self.assertEqual([e for e in errs if "core" in e], [], errs)

    def test_one_thick_inset_still_rejected(self):
        """同样埋在主体里、但接触方向只有 1 格厚的夹层仍然拒绝。"""
        rows = ["#####"] * 5
        model = _model_from_layers([rows, rows, rows])
        core = {(x, 1, z) for x in range(1, 4) for z in range(1, 4)}
        body = {(x, y, z) for x in range(5) for y in range(3) for z in range(5)} - core
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": body},
                 {"id": "skin", "name": "夹层", "required": True, "source": "夹层",
                  "role": "solid", "cells": core}]
        errs, _cells = check_parts(model, parts)
        self.assertTrue(any("skin" in e for e in errs), errs)

    def test_tapered_full_floor_passes(self):
        """占满整层、上下足迹不同的楼层：空气面少于贴合面也按承载楼层通过，不当墙皮。"""
        full = ["#####"] * 5
        mid = [".....", ".###.", ".###.", ".###.", "....."]
        model = _model_from_layers([full, mid, full])
        floor = {(x, 1, z) for x in range(1, 4) for z in range(1, 4)}
        solid = {(x, y, z) for y, rows in enumerate([full, mid, full])
                 for z, row in enumerate(rows) for x, c in enumerate(row) if c != "."}
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": solid - floor},
                 {"id": "floor", "name": "楼层", "required": True, "source": "楼层",
                  "role": "solid", "cells": floor}]
        errs, _cells = check_parts(model, parts)
        self.assertEqual([e for e in errs if "floor" in e], [], errs)

    def test_flush_skin_with_child_still_rejected(self):
        """墙皮上再贴一个小块，也不能把 1 格厚、与宿主截面重合的墙皮放行。"""
        rows = ["######", "######", "######", "######"]
        front = ["......", "......", "......", "..#..."]
        model = _model_from_layers([rows, front])
        skin = {(x, 0, 3) for x in range(6)}
        child = {(2, 1, 3)}
        body = {(x, 0, z) for x in range(6) for z in range(3)}
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": body},
                 {"id": "skin", "name": "墙皮", "required": True, "source": "墙皮",
                  "role": "solid", "cells": skin},
                 {"id": "knob", "name": "凸点", "required": True, "source": "凸点",
                  "role": "solid", "cells": child}]
        errs, _cells = check_parts(model, parts)
        self.assertTrue(any("skin" in e for e in errs), errs)


class SurfaceGateTest(unittest.TestCase):
    def _eye_parts(self, model, eye_cells, colors):
        return [{"id": "body", "name": "主体", "required": True, "source": "主体",
                 "role": "solid", "cells": set(colors) - set(eye_cells)},
                {"id": "eye", "name": "眼睛", "required": True, "source": "眼睛",
                 "role": "surface", "cells": set(eye_cells)}]

    def _eye_case(self, eye_color, rows=("#" * 6,) * 4):
        """eyes 在 y=0 层正面 z=0（外表面）；eye_color 与主体同色 → 同色拒绝。"""
        eye = {(1, 0, 0), (2, 0, 0)}
        colors = {(x, y, z): (eye_color if (x, y, z) in eye else "浅灰")
                  for x in range(6) for y in range(2) for z in range(4)}
        model = _model_with_colors([list(rows), list(rows)], colors)
        return model, eye

    def test_surface_buried_cell_rejected(self):
        """有一格完全内埋（六面无空气）→ 拒绝。"""
        rows = ["######", "######", "######", "######"]
        eye = {(1, 0, 0), (2, 0, 0), (1, 1, 1)}   # (1,1,1) 在 6x4x3 块内不外露
        colors = {(x, y, z): ("黑色" if (x, y, z) in eye else "浅灰")
                  for x in range(6) for y in range(3) for z in range(4)}
        model = _model_with_colors([rows, rows, rows], colors)
        errs, _cells = check_parts(model, self._eye_parts(model, eye, colors))
        self.assertTrue(any("内埋" in e for e in errs), errs)

    def test_surface_same_color_neighbor_rejected(self):
        """外露但与相邻主体同色 → 拒绝（异色才可辨识）。"""
        model, eye = self._eye_case("浅灰")
        errs, _cells = check_parts(model, self._eye_parts(model, eye,
                                                          {c: ("浅灰" if c not in eye else "浅灰")
                                                           for c in [(x, y, z) for x in range(6)
                                                                     for y in range(2) for z in range(4)]}))
        self.assertTrue(any("同色" in e for e in errs), errs)

    def test_legal_eye_passes(self):
        """全外露 + 与相邻主体异色 → 通过。"""
        model, eye = self._eye_case("黑色")
        errs, _cells = check_parts(model, self._eye_parts(model, eye,
                                                          {c: ("黑色" if c in eye else "浅灰")
                                                           for c in [(x, y, z) for x in range(6)
                                                                     for y in range(2) for z in range(4)]}))
        self.assertEqual([e for e in errs if "eye" in e], [], errs)

    def test_surface_volume_cap(self):
        rows = ["####", "####", "####", "####"]
        model = _model_from_layers([rows])
        cells = {(x, 0, z) for x in (1, 2) for z in (1, 2)}   # 4/64 = 6.25% … 用更明显的 16/64
        cells = {(x, 0, z) for x in range(4) for z in range(4)} - {(0, 0, 0)}
        colors = {c: "浅灰" for c in cells}
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": {(0, 0, 0)}},
                 {"id": "patch", "name": "大涂装", "required": True, "source": "大涂装",
                  "role": "surface", "cells": cells}]
        errs, _cells = check_parts(model, parts)
        self.assertTrue(any("上限" in e and "patch" in e for e in errs), errs)

    def test_full_wall_skin_decal_rejected_as_solid(self):
        """整面 1 格厚无阶跃墙皮贴花（6×2 紧贴 6×3×2 实心块侧面）必须被门禁拦截。"""
        wall = ["######", "######", "######", "######"]
        model = _model_from_layers([wall, wall])
        skin = {(x, y, 3) for x in range(6) for y in range(2)}
        all_c = {(x, y, z) for x in range(6) for y in range(2) for z in range(4)}
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": all_c - skin},
                 {"id": "skin", "name": "整面贴花", "required": True, "source": "贴花",
                  "role": "solid", "cells": skin}]
        errs, _ = check_parts(model, parts)
        self.assertTrue(any("skin" in e for e in errs), errs)


class CheckPartsContractTest(unittest.TestCase):
    """check_parts 返回 (errors, error_cells) 契约（gate_replay.replay_final_gate 依赖）。"""

    def test_clean_model_returns_empty_errors_and_cells(self):
        """全部部位合法时返回空错误列表与空错误格。"""
        rows = ["###..."] * 4
        model = _model_from_layers([rows])
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": {(x, 0, z) for x in (0, 1, 2) for z in range(4)}},
                 {"id": "arm", "name": "手臂", "required": True, "source": "手臂",
                  "role": "solid", "cells": {(3, 0, 1), (4, 0, 1)}}]
        errs, cells = check_parts(model, parts)
        self.assertEqual(errs, [])
        self.assertEqual(cells, [])

    def test_failed_part_reports_exactly_its_own_cells(self):
        """反例：被拒部位的错误格恰为该部位全部体素，且不牵连合法部位。"""
        rows = ["######"] * 4
        model = _model_from_layers([rows, rows, rows])
        badge = {(2, 1, 3), (3, 1, 3)}
        body = {(x, y, z) for x in range(6) for y in range(3) for z in range(4)} - badge
        parts = [{"id": "body", "name": "主体", "required": True, "source": "主体",
                  "role": "solid", "cells": body},
                 {"id": "badge", "name": "徽章", "required": True, "source": "徽章",
                  "role": "solid", "cells": badge}]
        errs, cells = check_parts(model, parts)
        self.assertTrue(any("badge" in e for e in errs), errs)
        self.assertFalse(any("body" in e for e in errs), errs)
        self.assertEqual(set(cells), badge, "错误格必须是失败部位自己的体素，供重放归属计数")


if __name__ == "__main__":
    unittest.main()
