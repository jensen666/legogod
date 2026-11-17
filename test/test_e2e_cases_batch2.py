# -*- coding: utf-8 -*-
"""第二批 20 例 E2E 案例的注册纪律测试（不调用真实模型）。

覆盖：
  1. 10 个全新主题（H01–H10）字段齐全、检查已注册、不进入 20 例注册表；
  2. 10 个历史失败重跑直接引用 20 例原定义，不复制描述；
  3. 运行器 parse_cases 的区间解析按前缀隔离（C01-C05 不会误配 H01–H05）；
  4. 撞题审计由公开历史语料 fixture 驱动；缺语料时不得静默通过（--audit exit 2，
     --allow-empty 仅本地显式放行）。
"""
import contextlib
import io
import unittest
from unittest import mock

from tools.e2e_assert_20 import _CHECKS
from tools.e2e_cases_20 import CASES, all_cases, find_case
from tools.e2e_cases_batch2 import (HIST_FAILED_IDS, NEW_CASES, audit_history_corpus,
                                    batch_cases, hist_failed_cases)
from tools.e2e_cases_batch2 import main as batch2_main
from tools.e2e_browser_20 import parse_cases


class BatchRegistryTest(unittest.TestCase):
    def test_ten_new_themes_have_unique_ids_and_descriptions(self):
        self.assertEqual([c["id"] for c in NEW_CASES], [f"H{i:02d}" for i in range(1, 11)])
        self.assertEqual(len({c["desc"] for c in NEW_CASES}), 10)
        self.assertEqual(len({c["subject"] for c in NEW_CASES}), 10)

    def test_new_cases_follow_the_same_assertion_discipline(self):
        for c in NEW_CASES:
            self.assertGreaterEqual(len(c["desc"]), 60, c["id"])
            self.assertGreaterEqual(c["min_parts"], 7, c["id"])
            self.assertGreaterEqual(c["min_voxels"], 900, c["id"])
            self.assertTrue(c["require_parts"], c["id"])
            self.assertTrue(c["checks"], c["id"])
            for spec in c["checks"]:
                self.assertIn(spec[0], _CHECKS, f"{c['id']} 未注册检查 {spec[0]}")

    def test_new_themes_are_not_inside_the_twenty_registry(self):
        twenty = {c["desc"] for c in CASES}
        for c in NEW_CASES:
            self.assertNotIn(c["desc"], twenty, c["id"])
        self.assertEqual(len(CASES), 20)

    def test_historical_failures_reuse_the_original_definitions(self):
        self.assertEqual(len(HIST_FAILED_IDS), 10)
        by_id = {c["id"]: c for c in CASES}
        for case in hist_failed_cases():
            self.assertIs(case, by_id[case["id"]],
                          f"{case['id']} 必须是 20 例注册表的同一个对象，不能复制描述")

    def test_batch_is_ten_new_plus_ten_historical(self):
        cases = batch_cases()
        self.assertEqual(len(cases), 20)
        self.assertEqual([c["id"] for c in cases[:10]], [f"H{i:02d}" for i in range(1, 11)])
        self.assertEqual([c["id"] for c in cases[10:]], HIST_FAILED_IDS)

    # ---- 验收语义修正：案例定义冻结值 ----
    def test_h02_part_minimum_and_cylinder_replaced(self):
        """H02 min_parts 8→7（需求点名 7 组特征）；圆柱算子改为弧形屋顶结果几何。"""
        case = find_case("H02")
        self.assertEqual(case["min_parts"], 7)
        self.assertEqual(case["min_solid_parts"], 6)
        names = [spec[0] for spec in case["checks"]]
        self.assertNotIn("cylinder_ops_min", names)
        self.assertIn("curved_roof_profile", names)

    def test_h03_torch_uses_raised_pose_check(self):
        """火炬「高举」用姿态几何检查，替代无意义的轴向跨度。"""
        case = find_case("H03")
        self.assertIn("part_raised_above", [spec[0] for spec in case["checks"]])

    def test_h04_fore_leg_ball_adjacency_feature(self):
        """H04 不再要求独立「前爪」部位；前腿与绣球用体素 6-邻接判定。"""
        case = find_case("H04")
        names = [spec[0] for spec in case["checks"]]
        self.assertIn("parts_adjacent_min", names)
        self.assertNotIn("前爪", [name for name, _p in case["require_parts"]])
        # 需求点名的前爪允许并入前腿部位，故关键词必须同时覆盖两者。
        leg_patterns = next(p for name, p in case["require_parts"] if "前腿" in name)
        self.assertIn("前爪", leg_patterns)
        self.assertIn("前腿", leg_patterns)

    def test_h05_h08_cylinder_replaced_by_result_geometry(self):
        """H05 S 形长颈 / H08 大圆环改为结果几何检查，不再强制 cylinder 算子。"""
        for case_id, checker in (("H05", "s_curve_min"), ("H08", "circular_ring_min")):
            names = [spec[0] for spec in find_case(case_id)["checks"]]
            self.assertIn(checker, names, case_id)
            self.assertNotIn("cylinder_ops_min", names, case_id)

    def test_h10_orbiter_is_combination_assertion(self):
        """H10 轨道器：并集纵向跨度（显式 y 轴、排除储箱/助推器）+ 本体体量 + 子件邻接。"""
        case = find_case("H10")
        names = [spec[0] for spec in case["checks"]]
        self.assertNotIn("part_span_min", names)
        for checker in ("part_union_span_min", "part_min_volume", "parts_adjacent_min"):
            self.assertIn(checker, names)
        union_spec = next(spec for spec in case["checks"] if spec[0] == "part_union_span_min")
        include, exclude, axis, length = union_spec[1], union_spec[2], union_spec[3], union_spec[4]
        self.assertTrue(any("轨道器" in p or "orbiter" in p for p in include))
        self.assertTrue(any("外储箱" in p or "tank" in p for p in exclude))
        self.assertTrue(any("助推器" in p or "booster" in p for p in exclude))
        self.assertEqual(axis, "y")
        self.assertGreaterEqual(length, 8)

    def test_new_cases_target_blocks_parsable(self):
        from tools.e2e_assert_20 import _target_blocks
        for case in NEW_CASES:
            target = _target_blocks(case["desc"])
            self.assertIsNotNone(target, case["id"])
            # 目标块数与案例规模同一量级（260~440），防止解析到别的数字。
            self.assertGreaterEqual(target, 100, case["id"])
            self.assertLessEqual(target, 1000, case["id"])

    def test_all_cases_exposes_batch_for_lookup(self):
        pool = {c["id"] for c in all_cases()}
        for case in NEW_CASES:
            self.assertIn(case["id"], pool)
            self.assertEqual(find_case(case["id"].lower())["id"], case["id"])
            self.assertEqual(find_case(desc=case["desc"])["id"], case["id"])


class ParseCasesTest(unittest.TestCase):
    def test_range_does_not_cross_prefix(self):
        """C01-C05 只挑 C 案例，H01-H10 只挑 H 案例，编号相同也不串。"""
        self.assertEqual([c["id"] for c in parse_cases("C01-C05")],
                         ["C01", "C02", "C03", "C04", "C05"])
        self.assertEqual([c["id"] for c in parse_cases("H01-H03")],
                         ["H01", "H02", "H03"])
        self.assertEqual([c["id"] for c in parse_cases("H09-H10")],
                         ["H09", "H10"])

    def test_mixed_spec_keeps_requested_order(self):
        self.assertEqual([c["id"] for c in parse_cases("H01,C02,H10")],
                         ["H01", "C02", "H10"])

    def test_all_still_means_the_original_twenty(self):
        self.assertEqual([c["id"] for c in parse_cases("all")],
                         [f"C{i:02d}" for i in range(1, 21)])


class AuditTest(unittest.TestCase):
    def test_audit_uses_public_corpus_fixture(self):
        """公开历史语料 fixture 驱动：10 例全新主题与已发布案例 0 冲突。"""
        from tools.e2e_cases_20 import _load_public_history_corpus
        corpus = _load_public_history_corpus(exclude_groups=("B",))
        self.assertIsNotNone(
            corpus, "公开审计语料缺失：test/fixtures/public/history-corpus.json")
        report = audit_history_corpus(corpus=corpus)
        self.assertIsNotNone(report, "注入公开语料后审计不得返回 None")
        self.assertEqual(len(report), 10)
        new_desc = {c["desc"] for c in NEW_CASES}
        for case, conflicts in report:
            self.assertIn(case["desc"], new_desc)
            self.assertIsInstance(conflicts, list)
        self.assertEqual(sum(1 for _case, conflicts in report if conflicts), 0, report)

    def test_empty_corpus_fails_cli(self):
        """缺语料不得静默通过：--audit exit 2，只有 --allow-empty 显式放行。"""
        with mock.patch("tools.e2e_cases_batch2.audit_history_corpus", return_value=None):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = batch2_main(["--audit"])
            self.assertEqual(code, 2)
            self.assertIn("未执行完整撞题审计", buf.getvalue())
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(batch2_main(["--audit", "--allow-empty"]), 0)


if __name__ == "__main__":
    unittest.main()
