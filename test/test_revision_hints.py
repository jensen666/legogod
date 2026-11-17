# -*- coding: utf-8 -*-
"""修订上下文结构化测试。

验证：support / coverage / disconnected 失败被聚合成按层摘要与可执行建议，
覆盖计算悬挑格时使用当前模型；输出与具体造型无关（合成失败数据即可）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import revision_hints as rh  # noqa: E402


def _model(rows_by_layer):
    layers = []
    for y, rows in enumerate(rows_by_layer):
        layers.append({"y": y, "rows": list(rows),
                       "cells": [[x, z] for z, r in enumerate(rows)
                                 for x, ch in enumerate(r) if ch != "."]})
    return {"grid": {"w": len(rows_by_layer[0][0]) if rows_by_layer else 0,
                     "d": len(rows_by_layer[0]) if rows_by_layer else 0},
            "layers": layers}


class SupportHintsTest(unittest.TestCase):
    def test_support_groups_by_layer(self):
        failure = {"kind": "support", "layer": 2,
                   "cells": [(0, 1, 0), (1, 1, 0), (5, 2, 5)]}
        info = rh.summarize(failure)
        self.assertEqual([g["layer"] for g in info["groups"]], [1, 2])
        self.assertEqual(info["groups"][0]["count"], 2)
        self.assertEqual(info["groups"][0]["bbox"], (0, 1, 0, 0))
        self.assertTrue(any("内缩" in a or "支撑柱" in a for a in info["advice"]), info["advice"])

    def test_support_text_mentions_each_layer(self):
        failure = {"kind": "support", "cells": [(0, 1, 0), (2, 3, 4)]}
        text = rh.format_for_prompt(failure)
        self.assertIn("y=1", text)
        self.assertIn("y=3", text)


class CoverageHintsTest(unittest.TestCase):
    def test_coverage_lists_dangling_cells(self):
        rows0 = ["..##..", "######", "######"]
        rows1 = ["######", "######", "######"]   # y=1 左右各外扩 2 格
        model = _model([rows0, rows1, rows1])
        failure = {"kind": "coverage", "layer": 1, "cells": [(0, 1, 0)]}
        info = rh.summarize(failure, model)
        self.assertTrue(any("悬挑" in a for a in info["advice"]), info["advice"])
        self.assertTrue(any("y=1" in a for a in info["advice"]))

    def test_coverage_without_model_still_advises(self):
        info = rh.summarize({"kind": "coverage", "layer": 2, "cells": []}, None)
        self.assertTrue(info["advice"])
        self.assertIn("铺满", info["headline"])


class DisconnectedHintsTest(unittest.TestCase):
    def test_disconnected_groups_and_cross_layer_advice(self):
        failure = {"kind": "disconnected", "layer": 0,
                   "cells": [(0, 0, 0), (0, 1, 0), (0, 2, 0), (7, 0, 7)]}
        info = rh.summarize(failure)
        self.assertEqual([g["layer"] for g in info["groups"]], [0, 1, 2])
        text = rh.format_for_prompt(failure)
        self.assertIn("跨缝", text)
        self.assertIn("侧面", text)

    def test_unknown_kind_has_generic_advice(self):
        info = rh.summarize({"kind": "internal"})
        self.assertTrue(info["advice"])
        self.assertTrue(info["headline"])


class StructureInfoHintsTest(unittest.TestCase):
    """工作包 B：结构失败补全信息进入修订提示。"""

    def test_disconnected_interface_cells_and_components_in_hints(self):
        """disconnected 提示带两侧组件摘要、界面格与可连接邻域。"""
        rows0 = ["###"]
        rows1 = ["..."]
        model = _model([rows0, rows1])
        failure = {"kind": "disconnected", "layer": 0, "cells": [(1, 0, 0)],
                   "window_cells": [(1, 0, 0)],
                   "info": {
                       "components": [
                           {"id": "main", "voxels": 2, "bbox": [0, 2, 0, 0, 0, 0],
                            "parts": ["body"]},
                           {"id": "loose1", "voxels": 1, "bbox": [1, 1, 0, 0, 0, 0],
                            "parts": ["body"]},
                       ],
                       "interfaceCells": [{"a": [1, 0, 0], "b": [0, 0, 0],
                                           "sides": ["loose1", "main"]}],
                       "connectableCells": [[0, 1, 0], [1, 1, 0], [2, 1, 0]],
                   }}
        text = rh.format_for_prompt(failure, model)
        self.assertIn("两侧组件摘要", text)
        self.assertIn("组件 main", text)
        self.assertIn("组件界面格", text)
        self.assertIn("可连接邻域", text)
        self.assertIn("(0,1,0)", text)

    def test_disconnected_info_recomputed_from_model_when_missing(self):
        """失败对象没有 info 时按模型与全量窗口重算界面信息，不要求调用方补。"""
        model = _model([["###"], ["..."]])
        failure = {"kind": "disconnected", "cells": [(1, 0, 0)],
                   "window_cells": [(1, 0, 0)]}
        text = rh.format_for_prompt(failure, model)
        self.assertIn("组件界面格", text)

    def test_suspension_hints_include_lock_and_subassembly_cells(self):
        """suspension 提示带校验已算出的锁扣与子组件坐标。"""
        failure = {"kind": "suspension", "cells": [],
                   "info": {"lockCells": [[3, 1, 0]],
                            "subassemblyCells": [[3, 1, 0], [3, 2, 0]]}}
        text = rh.format_for_prompt(failure)
        self.assertIn("锁扣凸点", text)
        self.assertIn("(3,1,0)", text)
        self.assertIn("吊挂子组件体素", text)
        self.assertIn("(3,2,0)", text)

    def test_suspension_hints_do_not_invent_positions(self):
        """没有坐标时不编造：只给通用修法。"""
        text = rh.format_for_prompt({"kind": "suspension", "cells": []})
        self.assertIn("双凸点", text)
        self.assertNotIn("锁扣凸点（校验已算出的真实坐标）", text)


if __name__ == "__main__":
    unittest.main()
