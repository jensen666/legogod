# -*- coding: utf-8 -*-
"""规划规模一致性/指标测试（工作包 C）。

覆盖以下方面：
- 一致性正反例：目标块数与预估矛盾、容量超限、需求「目标约 N 块」与 targetBlocks 不一致；
- 非法输入不抛异常；
- metrics 有/无 targetBlocks、有/无 pieces 的 actualVoxels/actualParts 计算；
- 「3.5–4 体素/块」只作待标定提示，不得成为硬失败（回归断言）；
- 结构 class1/class2 不因圆形初稿无条件放开 cylinder（读取 revision_policy 边界契约）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import plan_scale as ps  # noqa: E402
from legogod import prompts as prompts_mod  # noqa: E402
from legogod import revision_policy as rp  # noqa: E402

DESC_400 = "一座多层石塔：方形塔身逐层收分，四面有拱门，塔顶有尖顶，目标约 400 块积木"


def _plan(**kw):
    """合法规划基线：网格 24×24×14、目标 400 块、预估 3000 体素 / 400 零件。"""
    plan = {"grid": {"w": 24, "d": 24}, "layers": 14, "estimatedVoxels": 3000,
            "targetBlocks": 400, "estimatedParts": 400}
    plan.update(kw)
    return plan


class ConsistencyPositiveTest(unittest.TestCase):
    def test_valid_plan_no_errors(self):
        errs = ps.consistency_errors(_plan(), DESC_400)
        self.assertEqual(errs, [], errs)

    def test_valid_plan_without_desc_target(self):
        errs = ps.consistency_errors(_plan(), "一座小房子，没有写目标块数")
        self.assertEqual(errs, [], errs)

    def test_baseline_like_ratio_accepted(self):
        """基线实际体素/零件比中位约 7.98：预估按该比例（体素/零件）合法。"""
        errs = ps.consistency_errors(
            _plan(estimatedVoxels=3192, estimatedParts=400), DESC_400)
        self.assertEqual(errs, [], errs)


class ConsistencyNegativeTest(unittest.TestCase):
    def test_target_blocks_optional_after_strategy_revert(self):
        """C 组初稿规模策略效果未达标已回退：targetBlocks 缺失不再拒绝规划。

        回退依据：「旧集总交付 <15 或内容 <4 → 对应生成策略判为效果未达标并回退」，
        开发轮实测交付 12/20、内容 1/20。字段仍可给出并参与一致性检查与规模指标。
        """
        plan = _plan()
        plan.pop("targetBlocks")
        self.assertEqual(ps.consistency_errors(plan, DESC_400), [])
        self.assertIsNone(ps.metrics(plan, None)["targetBlocks"])

    def test_estimated_parts_optional_after_strategy_revert(self):
        plan = _plan()
        plan.pop("estimatedParts")
        self.assertEqual(ps.consistency_errors(plan, DESC_400), [])

    def test_desc_target_mismatch_rejected(self):
        """需求写「目标约 400 块」而规划写 200：超出容差必须报错。"""
        errs = ps.consistency_errors(_plan(targetBlocks=200), DESC_400)
        self.assertTrue(any("400" in e and "不一致" in e for e in errs), errs)

    def test_desc_target_within_tolerance_accepted(self):
        """「目标约」允许容差：N=400、targetBlocks=420 在 ±10% 内不报错。"""
        errs = ps.consistency_errors(_plan(targetBlocks=420), DESC_400)
        self.assertEqual(errs, [], errs)

    def test_estimated_parts_vs_target_conflict(self):
        """estimatedParts 落在 [0.5N, 2.5N] 之外：标定前提示级不一致报错。"""
        errs = ps.consistency_errors(_plan(estimatedParts=100), DESC_400)
        self.assertTrue(any("明显矛盾" in e for e in errs), errs)
        self.assertTrue(any("标定前" in e for e in errs), errs)
        errs = ps.consistency_errors(_plan(estimatedParts=1200), DESC_400)
        self.assertTrue(any("明显矛盾" in e for e in errs), errs)

    def test_estimated_parts_edge_of_tolerance_accepted(self):
        """[0.5N, 2.5N] 边界内不报错：200 与 1000 是边界值。"""
        for n in (200, 1000):
            errs = ps.consistency_errors(_plan(estimatedParts=n), DESC_400)
            self.assertEqual(errs, [], (n, errs))

    def test_estimated_voxels_over_grid_capacity_is_hint_not_error(self):
        """冻结解释（2026-11-03）：体素估值超网格容量只作提示，不拒绝规划。

        容量硬约束由 targetBlocks（见 test_target_blocks_over_capacity）与实际落位承担；
        估值噪声（模型按 3.5–8 体素/块估算）不得把合法规划打成协议失败。
        """
        obs = []
        errs = ps.consistency_errors(
            _plan(grid={"w": 8, "d": 8}, layers=4, estimatedVoxels=300,
                  targetBlocks=100, estimatedParts=100), "小塔，目标约 100 块积木",
            observations=obs)
        self.assertEqual(errs, [], errs)
        self.assertTrue(any("超过网格容量" in o for o in obs), obs)

    def test_estimated_voxels_over_global_cap(self):
        errs = ps.consistency_errors(_plan(estimatedVoxels=6000), DESC_400)
        self.assertTrue(any("全局体素上限" in e for e in errs), errs)

    def test_voxel_part_ratio_impossible(self):
        """每块 1..16 体素：预估体素/零件比 0.5 或 20 都几何不可能。"""
        for vox in (200, 9000):
            errs = ps.consistency_errors(_plan(estimatedVoxels=vox), DESC_400)
            self.assertTrue(any("几何可行区间" in e for e in errs), (vox, errs))

    def test_estimated_voxels_below_target_blocks(self):
        """预估体素少于目标块数：每块至少 1 体素，实际零件数不可能达标。"""
        errs = ps.consistency_errors(
            _plan(grid={"w": 8, "d": 8}, layers=4, estimatedVoxels=100,
                  targetBlocks=400, estimatedParts=100), DESC_400)
        self.assertTrue(any("不可能达到目标" in e for e in errs), errs)

    def test_target_blocks_over_capacity(self):
        errs = ps.consistency_errors(
            _plan(grid={"w": 8, "d": 8}, layers=4, estimatedVoxels=200,
                  targetBlocks=400, estimatedParts=400), DESC_400)
        self.assertTrue(any("超过网格容量" in e for e in errs), errs)

    def test_invalid_grid_reported(self):
        errs = ps.consistency_errors(
            _plan(grid={"w": 99, "d": 4}, layers=14, estimatedVoxels=100,
                  targetBlocks=40, estimatedParts=40), DESC_400)
        self.assertTrue(any("超出上限" in e for e in errs), errs)


class ConsistencyNeverRaisesTest(unittest.TestCase):
    def test_invalid_inputs_return_error_strings(self):
        for plan, desc in ((None, None), ([], "x"), ("x", 123), ({}, ""),
                           ({"targetBlocks": "abc", "estimatedVoxels": [], "estimatedParts": {}},
                            DESC_400)):
            errs = ps.consistency_errors(plan, desc)
            self.assertIsInstance(errs, list)
            self.assertTrue(errs, (plan, desc))

    def test_bool_fields_not_treated_as_int(self):
        """布尔值不算整数：estimatedVoxels 缺失报错；targetBlocks 可选，非法值按未给出处理。"""
        errs = ps.consistency_errors(
            _plan(targetBlocks=True, estimatedVoxels=True, estimatedParts=True), DESC_400)
        self.assertTrue(any("estimatedVoxels" in e for e in errs), errs)
        self.assertFalse(any("targetBlocks" in e for e in errs), errs)
        self.assertIsNone(ps.metrics(_plan(targetBlocks=True), None)["targetBlocks"])


class HintNotHardFailureTest(unittest.TestCase):
    """3.5–4 体素/块是待标定提示：只进观测，不进入硬失败。"""

    def test_ratio_near_3_5_4_is_not_error(self):
        for vox in (1440, 1600):  # 400 块 × 3.6 / 4.0 体素
            errs = ps.consistency_errors(
                _plan(estimatedVoxels=vox, estimatedParts=400), DESC_400)
            self.assertEqual(errs, [], (vox, errs))

    def test_observations_mention_hint_and_reference(self):
        obs = ps.scale_observations(_plan(estimatedVoxels=1440, estimatedParts=400), DESC_400)
        blob = "\n".join(obs)
        self.assertIn("3.5", blob)
        self.assertIn("4.0", blob)
        self.assertIn("不是硬指标", blob)
        self.assertIn("7.98", blob)

    def test_observations_appended_to_consistency_call(self):
        obs = []
        ps.consistency_errors(_plan(), DESC_400, observations=obs)
        self.assertTrue(obs, "observations 传入时应追加待标定提示")
        self.assertTrue(any("参考" in o or "提示" in o for o in obs), obs)

    def test_hint_never_appears_in_errors(self):
        errs = ps.consistency_errors(_plan(estimatedVoxels=1600, estimatedParts=400), DESC_400)
        self.assertFalse(any("3.5" in e or "4 体素/块" in e for e in errs), errs)


class ParseTargetBlocksTest(unittest.TestCase):
    def test_parse_standard_suffix(self):
        self.assertEqual(ps.parse_target_blocks("...，目标约 420 块积木"), 420)
        self.assertEqual(ps.parse_target_blocks("目标约180块"), 180)

    def test_parse_without_about_word(self):
        """省略「约」的「目标 N 块」也必须进入规模指标。"""
        self.assertEqual(ps.parse_target_blocks("一座塔，目标 300 块积木"), 300)
        self.assertEqual(ps.parse_target_blocks("目标200块积木"), 200)
        self.assertEqual(ps.parse_target_blocks("目标 380 块"), 380)
        self.assertEqual(ps.parse_target_blocks("...，目标约 300 块"), 300)

    def test_parse_absent(self):
        self.assertIsNone(ps.parse_target_blocks("一只小鸟"))
        self.assertIsNone(ps.parse_target_blocks("目标是 300 块"))  # 「目标是」不是目标块数句
        self.assertIsNone(ps.parse_target_blocks(None))
        self.assertIsNone(ps.parse_target_blocks(123))

    def test_parse_non_positive_yields_none(self):
        self.assertIsNone(ps.parse_target_blocks("目标 0 块"))
        self.assertIsNone(ps.parse_target_blocks("目标约 0 块积木"))

    def test_parse_takes_first_explicit_target(self):
        self.assertEqual(ps.parse_target_blocks("目标 300 块，主塔目标 120 块"), 300)

    def test_metrics_fallback_reads_both_write_styles(self):
        """metrics 从需求原文补目标块数：两种写法同源，比例与 pieces 一致。"""
        plan = _plan()
        plan.pop("targetBlocks")
        for desc, expected in (("一座塔，目标 200 块", 200),
                               ("一座塔，目标约 400 块积木", 400)):
            m = ps.metrics(plan, None, pieces=100, desc=desc)
            self.assertEqual(m["targetBlocks"], expected, desc)
            self.assertAlmostEqual(m["targetBlocksRatio"], 100 / expected)

    def test_consistency_checks_both_write_styles(self):
        """一致性检查对两种写法同样生效：targetBlocks 偏离必须报错、一致不报错。"""
        errs = ps.consistency_errors(_plan(targetBlocks=400), "一座塔，目标 300 块")
        self.assertTrue(any("不一致" in e for e in errs), errs)
        errs = ps.consistency_errors(_plan(targetBlocks=300), "一座塔，目标 300 块")
        self.assertEqual(errs, [], errs)


class MetricsTest(unittest.TestCase):
    def _model(self, voxels=650):
        return {"grid": {"w": 20, "d": 20}, "totalVoxels": voxels, "layers": []}

    def test_full_metrics(self):
        m = ps.metrics(_plan(estimatedVoxels=650, estimatedParts=90), self._model(650), pieces=80)
        self.assertEqual(m["targetBlocks"], 400)
        self.assertEqual(m["estimatedVoxels"], 650)
        self.assertEqual(m["estimatedParts"], 90)
        self.assertEqual(m["actualVoxels"], 650)
        self.assertEqual(m["actualParts"], 80)
        self.assertEqual(m["bricks"], 80)
        self.assertAlmostEqual(m["targetBlocksRatio"], 0.2)
        self.assertAlmostEqual(m["voxelsPerPiece"], 650 / 80)
        self.assertAlmostEqual(m["partRatio"], 80 / 90)

    def test_without_target_blocks(self):
        plan = _plan()
        plan.pop("targetBlocks")
        m = ps.metrics(plan, self._model(), pieces=80)
        self.assertIsNone(m["targetBlocks"])
        self.assertIsNone(m["targetBlocksRatio"])
        self.assertEqual(m["actualParts"], 80)

    def test_target_blocks_from_desc_when_plan_missing(self):
        """C 策略回退后规划可缺 targetBlocks：从需求原文「目标约 N 块」补出并按同一 pieces 重算比例。"""
        plan = _plan()
        plan.pop("targetBlocks")
        m = ps.metrics(plan, self._model(650), pieces=80, desc="一座塔，目标约 200 块积木")
        self.assertEqual(m["targetBlocks"], 200)
        self.assertAlmostEqual(m["targetBlocksRatio"], 0.4)

    def test_plan_target_wins_over_desc(self):
        """规划给了 targetBlocks 时以规划为准（需求原文只作缺失兜底）。"""
        m = ps.metrics(_plan(targetBlocks=400), self._model(650), pieces=80,
                       desc="一座塔，目标约 200 块积木")
        self.assertEqual(m["targetBlocks"], 400)
        self.assertAlmostEqual(m["targetBlocksRatio"], 0.2)

    def test_workflow_artifacts_scale_metrics_uses_desc_fallback(self):
        """run/job 记录装配走同一兜底：scaleMetrics 必须带 targetBlocks 与重算后的比例。"""
        from legogod import workflow_artifacts as wa

        class _Chain:
            plan = None
            model = None
            desc = "一座塔，目标约 200 块积木"

        chain = _Chain()
        chain.plan = _plan()
        chain.plan.pop("targetBlocks")
        chain.model = self._model(650)
        metrics, reason = wa.scale_metrics(chain, pieces=80)
        self.assertIsNone(reason)
        self.assertEqual(metrics["targetBlocks"], 200)
        self.assertEqual(metrics["actualParts"], 80)
        self.assertAlmostEqual(metrics["targetBlocksRatio"], 0.4)

    def test_without_pieces(self):
        m = ps.metrics(_plan(), self._model(), pieces=None)
        self.assertEqual(m["actualVoxels"], 650)
        self.assertIsNone(m["actualParts"])
        self.assertIsNone(m["bricks"])
        self.assertIsNone(m["targetBlocksRatio"])
        self.assertIsNone(m["voxelsPerPiece"])
        self.assertIsNone(m["partRatio"])

    def test_actual_voxels_recomputed_from_layers(self):
        model = {"layers": [
            {"y": 0, "rows": ["##..", "...."]},
            {"y": 1, "rows": ["#...", "...."]},
        ]}
        m = ps.metrics(_plan(), model, pieces=2)
        self.assertEqual(m["actualVoxels"], 3)
        self.assertAlmostEqual(m["voxelsPerPiece"], 1.5)

    def test_invalid_inputs_never_raise(self):
        for plan, model, pieces in ((None, None, None), ("x", "y", "z"),
                                    ({}, [], "bad"), ({"targetBlocks": "abc"}, {}, -1)):
            m = ps.metrics(plan, model, pieces)
            self.assertEqual(set(m), set(ps._METRIC_KEYS))
            self.assertIsNone(m["actualParts"])

    def test_zero_voxels_is_none(self):
        m = ps.metrics(_plan(), {"totalVoxels": 0, "layers": []}, pieces=1)
        self.assertIsNone(m["actualVoxels"])


class StructureBoundaryRegressionTest(unittest.TestCase):
    """工作包 C 第 5 条：结构 class1/class2 不因圆形初稿无条件放开 cylinder。

    边界契约（不改他人文件，只读 revision_policy 常量/函数 + prompts 文案）：
    结构性追加仍只允许 box 或 kind="inverted" 的 wedge，cylinder/loft 不在其中。
    """

    def test_structural_append_allows_only_box_or_inverted_wedge(self):
        self.assertTrue(rp._is_append_op({"op": "box", "x": 0, "y": 0, "z": 0,
                                         "w": 1, "d": 1, "h": 1, "part": "p"}))
        self.assertTrue(rp._is_append_op({"op": "wedge", "kind": "inverted",
                                         "dir": "+x", "x": 0, "y": 0, "z": 0,
                                         "w": 2, "d": 1, "h": 1, "part": "p"}))
        self.assertFalse(rp._is_append_op({"op": "wedge", "kind": "regular",
                                           "dir": "+x", "x": 0, "y": 0, "z": 0,
                                           "w": 2, "d": 1, "h": 1, "part": "p"}))
        self.assertFalse(rp._is_append_op({"op": "cylinder", "cx": 3, "cz": 3, "y": 0,
                                           "h": 2, "r": 1, "part": "p"}))
        self.assertFalse(rp._is_append_op({"op": "loft", "part": "p",
                                           "sections": [{"y": 0, "w": 2, "d": 2},
                                                        {"y": 1, "w": 4, "d": 4}]}))
        self.assertFalse(rp._is_append_op({"op": "mirror", "axis": "x", "ops": []}))

    def test_structural_kinds_and_caps_frozen(self):
        self.assertEqual(set(rp.STRUCTURAL_KINDS),
                         {"connectivity", "disconnected", "support", "coverage"})
        self.assertEqual(rp.MAX_STRUCT_APPEND, 16)
        self.assertEqual(rp.MAX_STRUCT_REWRITE, 12)

    def test_prompt_documents_structural_boundary(self):
        """回退后提示词仍保留结构修订边界：追加只许 box / inverted wedge。"""
        doc = prompts_mod.OPS_REVISE_DOC
        self.assertIn("只许 `box` 或 `wedge`", doc)
        self.assertIn("inverted", doc)

    def test_scale_strategy_prompts_reverted(self):
        """C 组初稿规模策略回退处理：提示词不再强制 targetBlocks/estimatedParts。

        保留的规模能力在下游（plan_scale 一致性检查只在字段给出时生效、scaleMetrics 记录、
        断言按 targetBlocksRatio 判定需求达标档）；这里锁定回退事实，避免悄悄恢复。
        """
        sys_prompt = prompts_mod.AGENT_SYSTEM
        self.assertNotIn("targetBlocks", sys_prompt)
        self.assertNotIn("estimatedParts", sys_prompt)


if __name__ == "__main__":
    unittest.main()
