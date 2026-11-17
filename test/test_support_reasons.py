# -*- coding: utf-8 -*-
"""A.3.5 support 稳定原因码测试。

覆盖：5 类原因码各用真实 find_unsupported / precheck_details 触发最小正例；
旧三元组解包兼容；不可判明时保留原始 reason、不猜测类别；revision_hints 按原因码分流。
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import revision_hints as rh  # noqa: E402
from legogod.agent import precheck_details, support_reasons_for_cells  # noqa: E402
from legogod.support_reasons import (REASON_BRICK, REASON_COLOR,  # noqa: E402
                                     REASON_GROUND, REASON_INV_PAIR,
                                     REASON_SLOPE_ROOT, REASON_UNKNOWN,
                                     SUPPORT_REASON_CODES, UnsupportedCell,
                                     issue_code, reason_buckets)
from legogod.tiler import find_unsupported  # noqa: E402


def _model(layers_rows, color_rows=None, colors=None):
    """构造 precheck_details 可用的模型（layers_rows 自下而上）。"""
    layers = []
    for y, rows in enumerate(layers_rows):
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        layers.append({
            "y": y, "rows": rows, "cells": cells, "module": ["层"],
            "color": (colors or {}).get(y),
            "colorRows": (color_rows or {}).get(y),
            "count": len(cells),
        })
    return {"grid": {"w": len(layers_rows[0][0]), "d": len(layers_rows[0])},
            "totalVoxels": sum(len(L["cells"]) for L in layers), "layers": layers}


def _codes(issues):
    return [issue.code for issue in issues]


class RealTriggerTest(unittest.TestCase):
    """5 类原因码的最小正例（真实 find_unsupported / precheck_details 触发）。"""

    def test_slope_root_support(self):
        """正斜坡段下方没有可承托面 → slope_root_support。"""
        typed = {(1, 0): "/", (2, 0): "/"}
        below = {(0, 0): "#"}
        issues = find_unsupported(typed, below)
        self.assertTrue(issues)
        self.assertEqual(set(_codes(issues)), {REASON_SLOPE_ROOT})
        detail = precheck_details(_model([["#......."], ["......./"]]))
        self.assertEqual(detail["kind"], "support")
        self.assertIn(REASON_SLOPE_ROOT, detail["support_reasons"])

    def test_brick_support(self):
        """同层有支撑但个别普通砖格无法被任何受支撑砖覆盖 → brick_support。"""
        # y=1 一行 9 格，只有 x=0 下方有实体：1x8 覆盖 x0..7，x8 无受支撑砖可覆盖。
        detail = precheck_details(_model([["#........"], ["#########"]]))
        self.assertEqual(detail["kind"], "support")
        self.assertEqual([(x, y, z) for x, y, z in detail["error_cells"]],
                         [(8, 1, 0)])
        self.assertEqual(detail["support_reasons"][REASON_BRICK]["count"], 1)
        # 不是整段浮动（同层有支撑），不得误判为 ground_reachability
        self.assertNotIn(REASON_GROUND, detail["support_reasons"])

    def test_color_fragment(self):
        """只有跨色砖能覆盖、同色砖无法铺 → color_fragment。"""
        model = _model([["#......"], ["###...."]],
                       color_rows={1: ["RRB...."]}, colors={1: "红色"})
        detail = precheck_details(model)
        self.assertEqual(detail["kind"], "support")
        self.assertIn(REASON_COLOR, detail["support_reasons"])
        self.assertEqual([tuple(c) for c in detail["support_reasons"][REASON_COLOR]["cells"]],
                         [(2, 1, 0)])
        self.assertNotIn(REASON_BRICK, detail["support_reasons"])

    def test_inverted_slope_pair(self):
        """反斜坡同字符段长度为奇数 → inverted_slope_pair。"""
        typed = {(0, 0): "b"}
        issues = find_unsupported(typed, None)
        self.assertEqual(_codes(issues), [REASON_INV_PAIR])
        detail = precheck_details(_model([["b.."]]))
        self.assertEqual(detail["kind"], "support")
        self.assertIn(REASON_INV_PAIR, detail["support_reasons"])

    def test_ground_reachability(self):
        """整段与任何支撑格都不相连的悬空碎片 → ground_reachability。"""
        model = _model([["#...", "....", "....", "...."],
                        ["....", "....", "....", "...#"]])
        detail = precheck_details(model)
        self.assertEqual(detail["kind"], "support")
        self.assertIn(REASON_GROUND, detail["support_reasons"])
        self.assertEqual([tuple(c) for c in detail["support_reasons"][REASON_GROUND]["cells"]],
                         [(3, 1, 3)])

    def test_all_five_codes_covered(self):
        """五类原因码都在导出常量里（契约：至少 5 类）。"""
        for code in (REASON_SLOPE_ROOT, REASON_BRICK, REASON_COLOR,
                     REASON_INV_PAIR, REASON_GROUND):
            self.assertIn(code, SUPPORT_REASON_CODES)


class BackwardCompatTest(unittest.TestCase):
    def test_three_tuple_unpack_still_works(self):
        """旧调用方按 (x, z, reason) 三元解包/索引/len 不炸，额外可读 .code。"""
        typed = {(3, 3): "#"}
        below = {(0, 0): "#"}
        issues = find_unsupported(typed, below)
        self.assertEqual(len(issues[0]), 3)
        x, z, reason = issues[0]
        self.assertEqual((x, z), (3, 3))
        self.assertIn("没有支撑", reason)
        self.assertEqual(issues[0][0], 3)
        self.assertEqual(list(issues[0]), [3, 3, reason])
        self.assertEqual(issues[0].code, REASON_GROUND)
        self.assertIsInstance(issues[0], tuple)

    def test_unsupported_cell_carries_code(self):
        issue = UnsupportedCell(1, 2, "原始原因", REASON_BRICK)
        self.assertEqual(tuple(issue), (1, 2, "原始原因"))
        self.assertEqual(issue.code, REASON_BRICK)
        self.assertEqual(issue_code(issue), REASON_BRICK)


class UnknownReasonTest(unittest.TestCase):
    def test_plain_tuple_is_unknown_and_reason_kept(self):
        """旧三元组/未知码：归 unknown，保留原始 reason 文本，不猜测类别。"""
        self.assertEqual(issue_code((1, 2, "原始原因")), REASON_UNKNOWN)
        self.assertEqual(issue_code(UnsupportedCell(1, 2, "x", "未知码")), REASON_UNKNOWN)
        buckets = reason_buckets([(3, (1, 2, "原始原因文本"))])
        self.assertEqual(buckets[REASON_UNKNOWN]["count"], 1)
        self.assertEqual(buckets[REASON_UNKNOWN]["cells"], [[1, 3, 2]])
        self.assertEqual(buckets[REASON_UNKNOWN]["rawReasons"], ["原始原因文本"])

    def test_precheck_details_keeps_raw_reason_when_unclassifiable(self):
        """find_unsupported 给出不可判明结果时，precheck_details 保留原始 reason。"""
        model = _model([["##"]])
        with mock.patch("legogod.agent.find_unsupported",
                        return_value=[(1, 0, "无法判明的原始原因")]):
            detail = precheck_details(model)
        self.assertEqual(detail["kind"], "support")
        self.assertEqual(detail["error_cells"], [(1, 0, 0)])
        self.assertEqual(detail["support_reasons"][REASON_UNKNOWN]["count"], 1)
        self.assertEqual(detail["support_reasons"][REASON_UNKNOWN]["rawReasons"],
                         ["无法判明的原始原因"])
        # 旧字段保持
        self.assertTrue(detail["errors"])


class PrecheckContractTest(unittest.TestCase):
    def test_support_reasons_shape_and_old_keys(self):
        """support_reasons 结构 {code: {count, cells≤64}}；kind/errors/error_cells 保留。"""
        detail = precheck_details(_model([["#........"], ["#########"]]))
        for key in ("errors", "error_cells", "kind", "support_reasons"):
            self.assertIn(key, detail)
        entry = detail["support_reasons"][REASON_BRICK]
        self.assertEqual(entry["count"], 1)
        self.assertEqual(entry["cells"], [[8, 1, 0]])
        self.assertLessEqual(len(entry["cells"]), 64)

    def test_pass_and_connectivity_have_empty_support_reasons(self):
        self.assertEqual(precheck_details(_model([["##"]]))["support_reasons"], {})
        conn = precheck_details(_model([["#.#"]]))
        self.assertEqual(conn["kind"], "connectivity")
        self.assertEqual(conn["support_reasons"], {})

    def test_support_reasons_for_cells_only_counts_given_cells(self):
        model = _model([["#........"], ["#########"]])
        reasons = support_reasons_for_cells(model, [(8, 1, 0)])
        self.assertEqual(reasons[REASON_BRICK]["count"], 1)
        self.assertEqual(support_reasons_for_cells(model, [(0, 1, 0)]), {})


class HintsGroupingTest(unittest.TestCase):
    def test_hints_grouped_by_reason_code(self):
        """提示按原因码分组输出，每类给对应修法，不把所有 reason 混成一段。"""
        failure = {"kind": "support", "cells": [(1, 1, 0), (5, 1, 0)],
                   "support_reasons": {
                       REASON_SLOPE_ROOT: {"count": 1, "cells": [[1, 1, 0]]},
                       REASON_COLOR: {"count": 1, "cells": [[5, 1, 0]]},
                   }}
        text = rh.format_for_prompt(failure)
        self.assertIn("斜坡根部无承托", text)
        self.assertIn("颜色碎片", text)
        self.assertIn("支撑柱", text)
        self.assertIn("同色", text)
        lines = [line for line in text.splitlines() if line.startswith("- ")]
        self.assertGreaterEqual(len(lines), 2, text)
        slope_line = next(line for line in lines if "斜坡根部无承托" in line)
        color_line = next(line for line in lines if "颜色碎片" in line)
        self.assertIn("托架", slope_line)
        self.assertIn("同色", color_line)

    def test_hints_unknown_keeps_raw_reason(self):
        failure = {"kind": "support", "cells": [(2, 1, 0)],
                   "support_reasons": {REASON_UNKNOWN: {
                       "count": 1, "cells": [[2, 1, 0]], "rawReasons": ["原始原因文本"]}}}
        text = rh.format_for_prompt(failure)
        self.assertIn("原因未判明", text)
        self.assertIn("原始原因文本", text)
        self.assertIn("不要猜测类别", text)

    def test_hints_recomputed_from_model_when_failure_lacks_codes(self):
        """class1 失败对象不带 support_reasons 时，按模型重跑预检归类。"""
        model = _model([["#........"], ["#########"]])
        failure = {"kind": "support", "cells": [(8, 1, 0)]}
        text = rh.format_for_prompt(failure, model)
        self.assertIn("普通砖块无支撑", text)

    def test_hints_fallback_to_layer_groups_without_model(self):
        """没有模型也没有原因码时保留旧的分层聚合提示（向后兼容）。"""
        failure = {"kind": "support", "cells": [(0, 1, 0), (2, 3, 4)]}
        text = rh.format_for_prompt(failure)
        self.assertIn("y=1", text)
        self.assertIn("y=3", text)
        self.assertIn("内缩", text)


if __name__ == "__main__":
    unittest.main()
