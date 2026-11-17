# -*- coding: utf-8 -*-
"""最终门禁重放、结构化选稿排序与降级候选回归检测测试。

覆盖：
  1. rank_key_gate 排序稳定性（相同错误不同顺序/不同坐标 → 同键）、部位数/错误格数/
     错误类型增加判更差、减少判更优、无错误最优、文本兜底归属；
  2. replay_final_gate 真实复用 part_gate.check_parts 的正反例（含多部位失败归属计数）；
  3. degraded_regression 正反例（原错误不变 → None；新增部位 → 拒绝；去掉部位但错误格
     增加 → 按冻结规则拒绝；服务端异常/无模型 → ok=None 不抛异常）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import gate_replay, part_gate  # noqa: E402


def _model_from_layers(rows_by_layer, color_rows=None):
    """按层字符画构造最小可校验模型（与 test/test_part_gate.py 同一夹具风格）。"""
    layers = []
    for y, rows in enumerate(rows_by_layer):
        cells = [[x, z] for z, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["层"],
                       "color": "浅灰", "colorRows": (color_rows or {}).get(y),
                       "count": len(cells)})
    return {"grid": {"w": len(rows_by_layer[0][0]), "d": len(rows_by_layer[0])},
            "totalVoxels": sum(len(L["cells"]) for L in layers), "layers": layers}


def _outward_model_and_parts():
    """真实凸出型：主体 + 悬臂手臂，两个 solid 部位都满足门禁（正例）。"""
    rows = ["###..."] * 4
    model = _model_from_layers([rows])
    parts = [{"id": "body", "name": "主体", "required": True, "source": "主体", "role": "solid",
              "cells": {(x, 0, z) for x in (0, 1, 2) for z in range(4)}},
             {"id": "arm", "name": "手臂", "required": True, "source": "手臂", "role": "solid",
              "cells": {(3, 0, 1), (4, 0, 1)}}]
    return model, parts


def _decal_model_and_parts():
    """反例：实心块侧面 2 格平齐贴花（badge）必被门禁拒绝，主体本身合法。"""
    rows = ["######"] * 4
    model = _model_from_layers([rows, rows, rows])
    badge = {(2, 1, 3), (3, 1, 3)}
    body = {(x, y, z) for x in range(6) for y in range(3) for z in range(4)} - badge
    parts = [{"id": "body", "name": "主体", "required": True, "source": "主体", "role": "solid",
              "cells": body},
             {"id": "badge", "name": "徽章", "required": True, "source": "徽章", "role": "solid",
              "cells": badge}]
    return model, parts


def _two_bump_model_and_parts():
    """反例：单格突起 ×2（两个独立失败部位），用于验证错误格→部位归属计数。"""
    model = _model_from_layers([["####"]])
    parts = [{"id": "body", "name": "主体", "required": True, "source": "主体", "role": "solid",
              "cells": {(0, 0, 0), (1, 0, 0)}},
             {"id": "bump_a", "name": "突起A", "required": True, "source": "突起A",
              "role": "solid", "cells": {(2, 0, 0)}},
             {"id": "bump_b", "name": "突起B", "required": True, "source": "突起B",
              "role": "solid", "cells": {(3, 0, 0)}}]
    return model, parts


ERR_A = "立体部位「p1」只有 1 格（最小体量 2）：单格突起属于伪部位"
ERR_B = "表面涂装部位「p2」有 3 格与同层相邻主体同色（(x=1,y=0,z=2)）——涂装细节必须异色"


class RankKeyTest(unittest.TestCase):
    """冻结结构化排序键。"""

    def test_same_errors_different_order_same_key(self):
        """相同错误不同顺序、坐标数值不同 → 同键（排序稳定）。"""
        cells_a = [(1, 0, 0), (2, 0, 0)]
        cells_b = [(2, 0, 0), (1, 0, 0)]
        k1 = gate_replay.rank_key_gate([ERR_B, ERR_A], cells_a)
        k2 = gate_replay.rank_key_gate([ERR_A, ERR_B], cells_b)
        self.assertEqual(k1, k2)
        # 坐标数值不同但数量与类型相同 → 仍是同键（类型已抹除坐标）
        err_c = "表面涂装部位「p2」有 3 格与同层相邻主体同色（(x=9,y=8,z=7)）——涂装细节必须异色"
        self.assertEqual(gate_replay.rank_key_gate([ERR_A, err_c], [(9, 8, 7), (1, 0, 0)]),
                         gate_replay.rank_key_gate([ERR_A, ERR_B], cells_a))

    def test_clean_gate_is_best(self):
        """无门禁错误 → 排序键恒为最优 (0,0,0,())。"""
        clean = gate_replay.rank_key_gate([], [])
        self.assertEqual(clean, (0, 0, 0, ()))
        self.assertLess(clean, gate_replay.rank_key_gate([ERR_A], [(1, 0, 0)]))

    def test_more_affected_parts_worse(self):
        """受影响部位数增加判更差（第一维优先）。"""
        one = gate_replay.rank_key_gate([ERR_A], [(1, 0, 0)])
        two = gate_replay.rank_key_gate([ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)])
        self.assertLess(one[0], two[0])
        self.assertLess(one, two)
        # 单部位更多错误格 vs 两部位更少错误格：仍按第一维判两部位更差
        one_many_cells = gate_replay.rank_key_gate([ERR_A, ERR_A], [(1, 0, 0), (2, 0, 0)])
        self.assertLess(one_many_cells, two)

    def test_more_error_cells_worse(self):
        """同部位数下，错误格总数增加判更差（第二维）。"""
        few = gate_replay.rank_key_gate([ERR_A], [(1, 0, 0)])
        more = gate_replay.rank_key_gate([ERR_A], [(1, 0, 0), (2, 0, 0), (3, 0, 0)])
        self.assertEqual(few[0], more[0])
        self.assertLess(few, more)

    def test_more_error_types_worse_and_fewer_better(self):
        """错误类型/错误条数增加判更差，减少判更优（第三维严重度）。"""
        one = gate_replay.rank_key_gate([ERR_A], [(1, 0, 0)])
        two = gate_replay.rank_key_gate([ERR_A, ERR_B], [(1, 0, 0)])
        self.assertLess(one, two, "错误条数增加必须判更差")
        three = gate_replay.rank_key_gate([ERR_A, ERR_B, "覆盖不足：部位「p3」未覆盖"], [(1, 0, 0)])
        self.assertLess(two, three)
        # 减少：三项错误 → 一项错误判更优
        self.assertLess(one, three)

    def test_same_count_different_type_is_ordered_by_type(self):
        """错误条数相同时按规范化错误类型字典序比较（固定规则，可复现）。"""
        k_small = gate_replay.rank_key_gate(["AAA 类型"], [(1, 0, 0)])
        k_big = gate_replay.rank_key_gate(["ZZZ 类型"], [(1, 0, 0)])
        self.assertLess(k_small, k_big)
        self.assertGreater(k_big, k_small)

    def test_cells_to_part_mapping_attribution(self):
        """错误格优先按 cells→part 映射归属：同部位多格只算 1 个受影响部位。"""
        mapping = {(0, 0, 0): "p1", (1, 0, 0): "p1", (2, 0, 0): "p2"}
        key_one = gate_replay.rank_key_gate([ERR_A], [(0, 0, 0), (1, 0, 0)], mapping)
        key_two = gate_replay.rank_key_gate([ERR_A], [(0, 0, 0), (2, 0, 0)], mapping)
        self.assertEqual(key_one[0], 1)
        self.assertEqual(key_two[0], 2)
        self.assertLess(key_one, key_two)

    def test_text_fallback_part_count_and_coordinate_cells(self):
        """无映射时退回错误文本部位名数量；无错误格时退回错误文本不同坐标数。"""
        key = gate_replay.rank_key_gate([ERR_A, ERR_B])
        self.assertEqual(key[0], 2, "两条错误各点名一个部位 → 2 个受影响部位")
        self.assertEqual(key[1], 1, "错误文本里只有 1 个不同坐标")
        self.assertEqual(key[2], 2, "错误条数 2")
        # part_ids 收窄：只统计已知部位
        narrowed = gate_replay.rank_key_gate([ERR_A, ERR_B], None, ["p1"])
        self.assertEqual(narrowed[0], 1)
        # 错误格为 [] 视为真实 0 格，不回退坐标计数
        self.assertEqual(gate_replay.rank_key_gate([ERR_A], [])[1], 0)

    def test_rank_detail_matches_rank_key(self):
        """rank_detail 明细与排序键同源（用于 run 记录 draftRanking）。"""
        detail = gate_replay.rank_detail([ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)])
        key = gate_replay.rank_key_gate([ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)])
        self.assertEqual(detail["affectedPartCount"], key[0])
        self.assertEqual(detail["errorCellCount"], key[1])
        self.assertEqual(len(detail["errorTypes"]), key[2])
        self.assertEqual(tuple(detail["errorTypes"]), key[3])
        self.assertEqual(gate_replay.rank_detail([], [])["affectedPartCount"], 0)


class NormalizeErrorTypeTest(unittest.TestCase):
    """错误类型规范化：坐标/部位名/数字抹除后稳定。"""

    def test_normalization_removes_coords_parts_and_numbers(self):
        a = gate_replay.normalize_error_type(
            "表面涂装部位「eye」有 12 格完全内埋（(x=1,y=2,z=3)）——严禁内埋充数")
        b = gate_replay.normalize_error_type(
            "表面涂装部位「nose」有 7 格完全内埋（(x=9,y=8,z=7)）——严禁内埋充数")
        self.assertEqual(a, b)
        self.assertIn("「部位」", a)
        self.assertNotIn("eye", a)
        self.assertNotIn("12", a)

    def test_error_types_keeps_multiset_order_invariant(self):
        types = gate_replay.error_types([ERR_A, ERR_B])
        self.assertEqual(sorted(types),
                         sorted(gate_replay.error_types([ERR_B, ERR_A])))


class ReplayFinalGateTest(unittest.TestCase):
    """对最终模型真实重放门禁。"""

    def test_clean_model_replay_ok(self):
        model, parts = _outward_model_and_parts()
        replay = gate_replay.replay_final_gate(model, parts)
        self.assertTrue(replay["ok"], replay)
        self.assertEqual(replay["errors"], [])
        self.assertEqual(replay["affectedPartCount"], 0)
        self.assertEqual(replay["errorCellCount"], 0)
        # 与 part_gate 单源判据一致
        self.assertEqual(part_gate.check_parts(model, parts)[0], [])

    def test_failed_model_replay_reports_real_gate(self):
        """最终模型仍有门禁错误：ok=False，计数来自真实 check_parts 结果。"""
        model, parts = _decal_model_and_parts()
        replay = gate_replay.replay_final_gate(model, parts)
        gate_errs, gate_cells = part_gate.check_parts(model, parts)
        self.assertTrue(gate_errs)
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["errors"], [str(e) for e in gate_errs])
        self.assertEqual(replay["affectedPartCount"], 1)
        self.assertEqual(replay["errorCellCount"], len(gate_cells))
        self.assertTrue(any("badge" in e for e in replay["errors"]))

    def test_two_failed_parts_counted_by_cells_attribution(self):
        model, parts = _two_bump_model_and_parts()
        replay = gate_replay.replay_final_gate(model, parts)
        self.assertFalse(replay["ok"])
        self.assertEqual(replay["affectedPartCount"], 2)
        self.assertEqual(replay["errorCellCount"], 2)
        self.assertTrue(any("bump_a" in e for e in replay["errors"]))
        self.assertTrue(any("bump_b" in e for e in replay["errors"]))

    def test_missing_model_returns_none_without_raising(self):
        for bad_model in (None, {}, {"layers": []}):
            replay = gate_replay.replay_final_gate(bad_model, [])
            self.assertIsNone(replay["ok"])
            self.assertTrue(replay.get("error"))
            self.assertEqual(replay["errors"], [])

    def test_replay_exception_returns_none_without_raising(self):
        """check_parts 抛异常（缺 y 等畸形模型）→ ok=None 且带原因，绝不外抛。"""
        replay = gate_replay.replay_final_gate({"layers": [{"rows": ["#"]}]}, None)
        self.assertIsNone(replay["ok"])
        self.assertIn("重放异常", replay["error"])

    def test_empty_parts_norm_replays_trivially_clean(self):
        model, _parts = _outward_model_and_parts()
        replay = gate_replay.replay_final_gate(model, [])
        self.assertTrue(replay["ok"])


class DegradedBaselineTest(unittest.TestCase):
    """降级基线冻结格式（供 promote_candidate / run 记录）。"""

    def test_baseline_shape_and_values(self):
        baseline = gate_replay.degraded_baseline([ERR_A], [(1, 0, 0)], ["p1"])
        self.assertEqual(set(baseline), {"affectedPartCount", "errorCellCount", "errorTypes"})
        self.assertEqual(baseline["affectedPartCount"], 1)
        self.assertEqual(baseline["errorCellCount"], 1)
        self.assertIsInstance(baseline["errorTypes"], list)
        self.assertEqual(len(baseline["errorTypes"]), 1)
        self.assertEqual(gate_replay.normalize_error_type(ERR_A), baseline["errorTypes"][0])

    def test_baseline_without_cells_marks_cells_unknown(self):
        baseline = gate_replay.degraded_baseline([ERR_A], None, ["p1"])
        self.assertIsNone(baseline["errorCellCount"])


class DegradedRegressionTest(unittest.TestCase):
    """已降级候选回归检测（冻结判定规则）。"""

    def _baseline(self, errors=None, cells=None, bad_ids=None):
        return gate_replay.degraded_baseline(
            [ERR_A] if errors is None else errors,
            [(1, 0, 0)] if cells is None else cells,
            ["p1"] if bad_ids is None else bad_ids)

    def test_unchanged_errors_allowed(self):
        """原门禁错误完全不变（含仅顺序不同）→ 允许继续（返回 None）。"""
        baseline = self._baseline()
        self.assertIsNone(gate_replay.degraded_regression(
            baseline, [ERR_A], [(1, 0, 0)], ["p1"]))
        self.assertIsNone(gate_replay.degraded_regression(
            baseline, [ERR_A], [(1, 0, 0)], ["p1"]))

    def test_reordered_errors_allowed(self):
        baseline = self._baseline([ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)], ["p1", "p2"])
        self.assertIsNone(gate_replay.degraded_regression(
            baseline, [ERR_B, ERR_A], [(2, 0, 0), (1, 0, 0)], ["p2", "p1"]))

    def test_fewer_errors_allowed(self):
        baseline = self._baseline([ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)], ["p1", "p2"])
        self.assertIsNone(gate_replay.degraded_regression(
            baseline, [ERR_A], [(1, 0, 0)], ["p1"]))

    def test_clean_candidate_allowed(self):
        """候选门禁完全干净 → 严格优于基线，允许继续。"""
        baseline = self._baseline()
        self.assertIsNone(gate_replay.degraded_regression(baseline, [], [], []))

    def test_new_affected_part_rejected(self):
        baseline = self._baseline()
        reason = gate_replay.degraded_regression(
            baseline, [ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)], ["p1", "p2"])
        self.assertIsNotNone(reason)
        self.assertIn("门禁回归", reason)
        self.assertIn("受影响部位数 2 > 降级基线 1", reason)

    def test_more_error_cells_rejected(self):
        baseline = self._baseline()
        reason = gate_replay.degraded_regression(
            baseline, [ERR_A], [(1, 0, 0), (2, 0, 0), (3, 0, 0)], ["p1"])
        self.assertIn("错误格总数 3 > 降级基线 1", reason)

    def test_part_removed_but_cells_increased_rejected_by_fixed_rule(self):
        """去掉一个部位但错误格增加：按冻结规则判恶化（错误格维度拒绝），不因部位减少放行。"""
        baseline = self._baseline([ERR_A, ERR_B], [(1, 0, 0), (2, 0, 0)], ["p1", "p2"])
        reason = gate_replay.degraded_regression(
            baseline, [ERR_A], [(1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)], ["p1"])
        self.assertIsNotNone(reason)
        self.assertIn("错误格总数 4 > 降级基线 2", reason)
        self.assertNotIn("受影响部位数", reason, "部位数实际减少，不得误报该维度")

    def test_more_error_types_rejected(self):
        """部位数与错误格都不变、错误类型/条数增加 → 按严重度判恶化。"""
        baseline = self._baseline([ERR_A], [(1, 0, 0)], ["p1"])
        reason = gate_replay.degraded_regression(
            baseline, [ERR_A, ERR_B], [(1, 0, 0)], ["p1"])
        self.assertIsNotNone(reason)
        self.assertIn("错误条数 1 → 2", reason)

    def test_missing_baseline_or_unknown_dimensions_do_not_raise(self):
        self.assertIsNone(gate_replay.degraded_regression(None, [ERR_A], [(1, 0, 0)], ["p1"]))
        self.assertIsNone(gate_replay.degraded_regression({}, [ERR_A], [(1, 0, 0)], ["p1"]))
        baseline = {"affectedPartCount": 1, "errorCellCount": None, "errorTypes": None}
        self.assertIsNone(gate_replay.degraded_regression(baseline, [ERR_A], [(1, 0, 0)], ["p1"]))


if __name__ == "__main__":
    unittest.main()
