# -*- coding: utf-8 -*-
"""双模式 E2E 运行器编排单元测试。

覆盖不依赖浏览器的编排逻辑：
- M 案例双模式展开：同一案例两臂相邻、奇偶案例交换先后；
- 分模式证据路径 <out>/<CASE>/<arm>/，禁止两臂覆盖同一案例文件；
- 轮次汇总同时列出两臂、快速臂视觉分写“未评审”。

不启动浏览器、不调用 LLM。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import e2e_browser_20, e2e_round  # noqa: E402


def _fake_m_cases(n=4):
    return [{"id": f"M{i:02d}", "name": f"案例{i}", "desc": f"需求{i}"} for i in range(1, n + 1)]


class ModeArmsTest(unittest.TestCase):
    def test_expand_arms_odd_even_order(self):
        """两臂相邻；M01（奇数）fast→fidelity，M02（偶数）fidelity→fast。"""
        out = e2e_browser_20._expand_mode_arms(_fake_m_cases(4), ("fast", "fidelity"))
        self.assertEqual(len(out), 8)
        self.assertEqual([c["arm"] for c in out[:2]], ["fast", "fidelity"])
        self.assertEqual([c["arm"] for c in out[2:4]], ["fidelity", "fast"])
        self.assertEqual([c["arm"] for c in out[4:6]], ["fast", "fidelity"])
        self.assertEqual([c["arm"] for c in out[6:8]], ["fidelity", "fast"])
        self.assertEqual(out[0]["runKey"], "M01-fast")
        self.assertEqual(out[3]["runKey"], "M02-fast")
        # 同一案例两臂必须相邻（降低时段/排队偏差）
        for i in range(0, len(out), 2):
            self.assertEqual(out[i]["id"], out[i + 1]["id"])

    def test_expand_arms_rejects_non_m_case(self):
        with self.assertRaises(SystemExit):
            e2e_browser_20._expand_mode_arms([{"id": "C01", "name": "x", "desc": "d"}],
                                             ("fast", "fidelity"))

    def test_expand_arms_rejects_unknown_mode(self):
        with self.assertRaises(SystemExit):
            e2e_browser_20._expand_mode_arms(_fake_m_cases(1), ("bogus",))


class ModePolicyTest(unittest.TestCase):
    """任务结果级模式事实断言：快速无评审/无保底；高保真保底恰一次。"""

    def test_fast_success_without_review_or_fallback_ok(self):
        res = {"ok": True, "outcome": "fast_success", "review": {}}
        self.assertEqual(e2e_browser_20._mode_policy_errors(res, "fast"), [])

    def test_fast_with_fallback_attempts_rejected(self):
        res = {"ok": True, "outcome": "fast_fallback",
               "attempts_detail": [{"mode": "fidelity", "ok": False},
                                   {"mode": "fast", "ok": True}]}
        errors = e2e_browser_20._mode_policy_errors(res, "fast")
        self.assertTrue(any("不得出现自动保底" in e for e in errors), errors)

    def test_fast_with_review_rejected(self):
        res = {"ok": True, "outcome": "fast_success",
               "review": {"scores": {"overall": 8}}}
        errors = e2e_browser_20._mode_policy_errors(res, "fast")
        self.assertTrue(any("不得产生视觉评审" in e for e in errors), errors)

    def test_fidelity_fallback_exactly_two_attempts_ok(self):
        res = {"ok": True, "outcome": "fast_fallback",
               "attempts_detail": [{"mode": "fidelity", "ok": False, "run_id": "a"},
                                   {"mode": "fast", "ok": True, "run_id": "b"}]}
        self.assertEqual(e2e_browser_20._mode_policy_errors(res, "fidelity"), [])

    def test_fidelity_fallback_order_rejected(self):
        res = {"ok": True, "outcome": "fast_fallback",
               "attempts_detail": [{"mode": "fast", "ok": False},
                                   {"mode": "fidelity", "ok": True}]}
        errors = e2e_browser_20._mode_policy_errors(res, "fidelity")
        self.assertTrue(any("顺序必须是高保真→快速" in e for e in errors), errors)

    def test_fidelity_success_requires_real_scores(self):
        res = {"ok": True, "outcome": "fidelity_success", "review": {}}
        errors = e2e_browser_20._mode_policy_errors(res, "fidelity")
        self.assertTrue(any("有效视觉评审分数" in e for e in errors), errors)
        res_ok = {"ok": True, "outcome": "fidelity_success",
                  "review": {"scores": {"overall": 8}}}
        self.assertEqual(e2e_browser_20._mode_policy_errors(res_ok, "fidelity"), [])

    def test_fidelity_success_with_fallback_attempts_rejected(self):
        res = {"ok": True, "outcome": "fidelity_success",
               "review": {"scores": {"overall": 8}},
               "attempts_detail": [{"mode": "fidelity", "ok": True}]}
        errors = e2e_browser_20._mode_policy_errors(res, "fidelity")
        self.assertTrue(any("不得包含自动保底" in e for e in errors), errors)


class EvidencePathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-mode20-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_dual_mode_paths_never_collide(self):
        """两种模式证据不得覆盖同一案例文件。"""
        case_fast = {"id": "M01", "arm": "fast"}
        case_fid = {"id": "M01", "arm": "fidelity"}
        p_fast = e2e_browser_20.record_path(self.tmp, case_fast)
        p_fid = e2e_browser_20.record_path(self.tmp, case_fid)
        self.assertNotEqual(p_fast, p_fid)
        self.assertTrue(p_fast.endswith(os.path.join("M01", "fast", "M01.json")), p_fast)
        self.assertTrue(p_fid.endswith(os.path.join("M01", "fidelity", "M01.json")), p_fid)
        d_fast = e2e_browser_20.case_dir_for(self.tmp, case_fast)
        d_fid = e2e_browser_20.case_dir_for(self.tmp, case_fid)
        self.assertNotEqual(d_fast, d_fid)
        self.assertTrue(d_fast.endswith(os.path.join("M01", "fast")), d_fast)

    def test_legacy_single_mode_paths_unchanged(self):
        """旧案例（无 arm）路径保持扁平结构，不破坏既有轮次目录。"""
        case = {"id": "C01"}
        self.assertTrue(e2e_browser_20.record_path(self.tmp, case).endswith("C01.json"))
        self.assertTrue(e2e_browser_20.case_dir_for(self.tmp, case).endswith("C01"))


class RoundSummaryTest(unittest.TestCase):
    def test_dual_mode_summary_lists_both_arms_and_marks_fast_unreviewed(self):
        env = {"label": "mode20", "startedAt": "t0", "finishedAt": "t1", "codeHead": "abc",
               "worktreeDirty": False, "modelConfigured": "m", "modelEnvVar": None,
               "concurrency": 3, "timeoutS": 2100, "baseUrl": "http://127.0.0.1:8611",
               "cases": "M01-M02"}
        metrics_fast = {"voxels": 12, "parts": 3, "review_overall": None}
        metrics_fid = {"voxels": 20, "parts": 5, "review_overall": 7}
        records = {
            ("M01", "fast"): {"name": "小房", "job_id": "j1", "runId": "r1", "status": "done",
                              "outcome": "fast_success", "taskOk": True, "assertOk": True,
                              "elapsedFinal": 10.0, "assertion": {"metrics": metrics_fast}},
            ("M01", "fidelity"): {"name": "小房", "job_id": "j2", "runId": "r2", "status": "done",
                                  "outcome": "fidelity_success", "taskOk": True, "assertOk": True,
                                  "elapsedFinal": 20.0, "assertion": {"metrics": metrics_fid}},
            ("M02", "fast"): {},
            ("M02", "fidelity"): {},
        }
        with tempfile.TemporaryDirectory(prefix="legogod-mode20-r1-") as tmp:
            path = e2e_round._summary_markdown(env, ["M01", "M02"], records, tmp,
                                               modes=["fast", "fidelity"])
            text = open(path, encoding="utf-8").read()
        self.assertIn("| M01 | fast |", text)
        self.assertIn("| M01 | fidelity |", text)
        self.assertIn("| M02 | fast |", text)
        self.assertIn("| M02 | fidelity |", text)
        self.assertIn("未评审", text)
        # 汇总按臂计数：8 个臂位中 2 个有交付、2 个断言通过
        self.assertIn("任务完成 2/4", text)
        self.assertIn("结果断言通过 2/4", text)
        self.assertIn("两臂相邻提交", text)


class RoundSkipRunTest(unittest.TestCase):
    """e2e_round 双模式封装：--skip-run 汇总读取 <CASE>/<arm>/ 记录并写两臂汇总。"""

    def test_skip_run_reads_dual_mode_records(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory(prefix="legogod-mode20-round-") as tmp:
            records = {
                ("M01", "fast"): {"case": "M01", "name": "小房", "job_id": "j1", "runId": None,
                                  "status": "done", "outcome": "fast_success", "taskOk": True,
                                  "assertOk": False, "elapsedFinal": 12.0,
                                  "assertion": {"metrics": {"voxels": 10, "parts": 2}}},
                ("M01", "fidelity"): {"case": "M01", "name": "小房", "job_id": "j2", "runId": None,
                                      "status": "done", "outcome": "fidelity_success",
                                      "taskOk": True, "assertOk": True, "elapsedFinal": 30.0,
                                      "assertion": {"metrics": {"voxels": 20, "parts": 5,
                                                                "review_overall": 8}}},
                ("M02", "fast"): {"case": "M02", "name": "小狗", "job_id": "j3", "runId": None,
                                  "status": "error", "outcome": "failed", "taskOk": False,
                                  "assertOk": False, "elapsedFinal": 5.0},
                ("M02", "fidelity"): {"case": "M02", "name": "小狗", "job_id": "j4", "runId": None,
                                      "status": "error", "outcome": "failed", "taskOk": False,
                                      "assertOk": False, "elapsedFinal": 9.0},
            }
            for (cid, arm), rec in records.items():
                d = os.path.join(tmp, cid, arm)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, f"{cid}.json"), "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False)
            code = e2e_round.main(["--cases", "M01-M02", "--modes", "fast,fidelity",
                                   "--out", tmp, "--skip-run", "--label", "unit-mode20"])
            self.assertEqual(code, 0)
            with open(os.path.join(tmp, "round-summary.md"), encoding="utf-8") as f:
                text = f.read()
            self.assertIn("| M01 | fast |", text)
            self.assertIn("| M01 | fidelity |", text)
            self.assertIn("| M02 | fast |", text)
            self.assertIn("| M02 | fidelity |", text)
            self.assertIn("任务完成 2/4", text)
            with open(os.path.join(tmp, "environment.json"), encoding="utf-8") as f:
                env = json.load(f)
            self.assertEqual(env["modes"], ["fast", "fidelity"])


if __name__ == "__main__":
    unittest.main()
