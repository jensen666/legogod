# -*- coding: utf-8 -*-
"""修订接口：补丁窗口种子与提示词常量。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.agent import precheck_details  # noqa: E402
from legogod.prompts import MAX_REVISE_COLOR_OPS, MAX_REVISE_OPS, OPS_REVISE_DOC  # noqa: E402
from legogod.workflow import MAX_REVISE_COLOR_OPS as WF_COLOR  # noqa: E402
from legogod.workflow import MAX_REVISE_OPS as WF_OPS  # noqa: E402
from legogod.workflow_phases import revision_ctx  # noqa: E402


def _layer_model(rows):
    """单层模型。rows 是字符串列表。"""
    return {
        "grid": {"w": len(rows[0]), "d": len(rows)},
        "layers": [{"y": 0, "rows": rows, "cells": [], "module": ["层"], "color": "浅灰"}],
    }


class PromptCapTest(unittest.TestCase):
    def test_ops_revise_doc_reads_runtime_caps(self):
        """系统提示词的几何/换色上限与执行常量相同，不再写死 4 和 12。"""
        self.assertEqual(MAX_REVISE_OPS, 8)
        self.assertEqual(MAX_REVISE_COLOR_OPS, 16)
        self.assertIs(WF_OPS, MAX_REVISE_OPS)
        self.assertIs(WF_COLOR, MAX_REVISE_COLOR_OPS)
        self.assertIn(f"≤{MAX_REVISE_OPS} 个算子", OPS_REVISE_DOC)
        self.assertIn(f"≤{MAX_REVISE_COLOR_OPS} 个算子", OPS_REVISE_DOC)
        self.assertNotIn("≤4 个算子", OPS_REVISE_DOC)
        self.assertNotIn("≤12 个算子", OPS_REVISE_DOC)


class WindowSeedTest(unittest.TestCase):
    def test_connectivity_error_cells_are_not_capped_at_64(self):
        """预检连通失败返回全部少数分量，不再截到 64。"""
        # x、z 都隔一格，避免同一列上下连成一个分量。12 行实体 × 6 个 # = 72 个孤立格。
        solid = ("#." * 6)[:11]
        blank = "." * len(solid)
        rows = []
        for _ in range(12):
            rows.append(solid)
            rows.append(blank)
        detail = precheck_details(_layer_model(rows))
        self.assertEqual(detail["kind"], "connectivity")
        self.assertEqual(len(detail["error_cells"]), 71)

    def test_revision_ctx_prefers_window_cells(self):
        """disconnected 的邻域种子是 window_cells，不是截断后的 cells。"""
        model = _layer_model(["." * 20] * 2)
        ctx = revision_ctx(model, {
            "kind": "disconnected",
            "message": "断连",
            "cells": [(0, 0, 0)],
            "window_cells": [(18, 0, 0)],
        })
        self.assertIn((18, 0, 0), ctx["allowed_cells"])
        self.assertNotIn((0, 0, 0), ctx["error_cells"])

    def test_revision_ctx_falls_back_when_window_missing(self):
        """没有 window_cells 时仍用 cells，coverage 的整层窗口不变。"""
        model = _layer_model(["##.."] * 2)
        ctx = revision_ctx(model, {
            "kind": "coverage",
            "message": "铺不满",
            "layer": 0,
            "cells": [(0, 0, 0)],
        })
        self.assertEqual(len(ctx["allowed_cells"]), 4 * 2)


if __name__ == "__main__":
    unittest.main()
