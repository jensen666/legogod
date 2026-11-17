# -*- coding: utf-8 -*-
"""架构验收工具回归（2026-11-15 复核缺陷）。

背景：`tools/e2e_arch_accept.py` 曾从 M 组断言器 metrics 读 `errors`，而
`tools/e2e_assert_mode20.py` 实际返回 `assertion_errors`，导致真实的 9 个失败被读成空数组、
全部显示“通过”（组合轮 10 例显示 10/10，实际 5/10；独立轮 6 例显示全通过，实际 2/6）。
同时 `Steps.note()` 永远记 ok=True，把断言结论当过程记录。本文件锁死这两条，防止再退化。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.e2e_arch_accept import (  # noqa: E402
    Steps, assertion_errors_of, attach_assertion)


class AssertionErrorsTest(unittest.TestCase):
    """从断言器 metrics 读取失败项：以 assertion_errors 为准。"""

    def test_reads_assertion_errors(self):
        metrics = {"assertion_errors": ["门洞未贯通"], "assertion_ok": False, "errors": []}
        self.assertEqual(assertion_errors_of(metrics), ["门洞未贯通"])

    def test_empty_assertion_errors_means_pass(self):
        self.assertEqual(assertion_errors_of(
            {"assertion_errors": [], "assertion_ok": True}), [])

    def test_ignores_stale_errors_key_when_assertion_errors_present(self):
        """真实形状里没有 errors 键；即使旧形状残留也不得覆盖 assertion_errors。"""
        self.assertEqual(assertion_errors_of(
            {"assertion_errors": ["真实失败"], "errors": ["旧键"]}), ["真实失败"])

    def test_compat_fallback_to_errors_key(self):
        self.assertEqual(assertion_errors_of({"errors": ["旧形状失败"]}), ["旧形状失败"])

    def test_missing_or_malformed_metrics(self):
        for value in (None, {}, {"assertion_errors": None}, {"assertion_errors": "x"}, "x"):
            with self.subTest(value=value):
                self.assertEqual(assertion_errors_of(value), [])


class StepsCountingTest(unittest.TestCase):
    """过程记录不计入通过率；真实断言失败必须计入。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-steps-")
        self.steps = Steps(os.path.join(self.tmp, "steps.json"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_note_is_not_counted(self):
        self.steps.note("第一波 M01/fast 提交成功", "任务 ID 已分配", "abc123")
        self.assertEqual(self.steps.counted_items(), [])
        self.assertEqual(self.steps.failed(), [])

    def test_assert_result_failure_is_counted(self):
        self.steps.assert_result("M01/fast 结果正确性断言", "无断言错误", False,
                                 ["门洞未贯通"], group="gen")
        self.assertEqual(len(self.steps.counted_items("gen")), 1)
        self.assertEqual(len(self.steps.failed("gen")), 1)
        self.assertEqual(self.steps.failed("arch"), [])

    def test_verify_failure_counts_as_arch(self):
        self.steps.verify("产物链接", "至少 1 个", False, 0)
        self.assertEqual(len(self.steps.failed("arch")), 1)

    def test_require_fatal_still_raises(self):
        with self.assertRaises(AssertionError):
            self.steps.require("部署隔离", "404", False, 200)


class AttachAssertionTest(unittest.TestCase):
    """失败断言必须写入结果条目，汇总表不能显示“跳过/通过”。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-attach-")
        self.steps = Steps(os.path.join(self.tmp, "steps.json"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, fake_metrics):
        item = {"case": "M01", "mode": "fast", "resultSummary": {"runId": "run1"}}
        entry = {"case": "M01", "mode": "fast", "jobId": "job1",
                 "result": {"runId": "run1"}}
        item["resultEntry"] = entry
        results = {"jobs": [entry]}
        with mock.patch("tools.e2e_assert_mode20.check_run_m",
                        return_value=fake_metrics):
            attach_assertion(item, self.steps, results)
        return item, entry

    def test_failure_recorded_and_linked_to_results_entry(self):
        item, entry = self._run({"assertion_errors": ["门洞未贯通", "屋顶无坡度"],
                                 "assertion_ok": False, "bricks": 49})
        self.assertEqual(item["assertion"]["errors"], ["门洞未贯通", "屋顶无坡度"])
        self.assertEqual(entry["assertion"]["errors"], ["门洞未贯通", "屋顶无坡度"])
        self.assertEqual(entry["assertion"]["metrics"]["bricks"], 49)
        self.assertEqual(len(self.steps.failed("gen")), 1, "真实失败未计入统计")

    def test_pass_recorded_without_errors(self):
        item, entry = self._run({"assertion_errors": [], "assertion_ok": True})
        self.assertEqual(item["assertion"]["errors"], [])
        self.assertEqual(entry["assertion"]["errors"], [])
        self.assertEqual(self.steps.failed("gen"), [])

    def test_missing_run_id_marks_failure_not_silent_skip(self):
        item = {"case": "M01", "mode": "fast", "resultSummary": {}}
        entry = {"case": "M01", "mode": "fast", "jobId": "job1", "result": {}}
        item["resultEntry"] = entry
        attach_assertion(item, self.steps, {"jobs": [entry]})
        self.assertEqual(item["assertion"]["skipped"], "任务终态但没有 run_id（失败任务无最终产物）")
        self.assertEqual(len(self.steps.failed("gen")), 1)


if __name__ == "__main__":
    unittest.main()
