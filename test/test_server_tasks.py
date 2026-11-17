# -*- coding: utf-8 -*-
"""Web 任务编排回归：双模式（快速/高保真）、保底编排、手动重试模式继承、并发与独立取消。

覆盖快速与高保真双模式的验收口径 5/6/8：
1) POST /api/build 缺省 mode=fidelity（仅 API 兼容语义），显式 fast 原样透传并回显 mode；
2) POST /api/retry：按原任务模式创建新任务（持久化 mode 优先，旧记录从 result/run 记录补取，
   完全缺失回退 fidelity），高保真继续继承有效评审意见，快速不编造评审意见；
3) 两个任务并发推进、分别查看与完成，取消其一另一个不受影响；
4) mode/retryOf/reviewContext/startedAt 持久化与恢复（重启不丢）。

架构升级后本文件不再读写模块级
`JOBS`/`JOBS_STORE`、不再 patch 模块级 `run_with_fallback`：改为进程内独立 JobStore/
JobService 夹具、真实 HTTP 连接、可控 runner 注入。行为断言与改造前逐条对应。
"""
import json
import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402


class ServerTasksTest(unittest.TestCase):
    """任务 API 行为回归（真实 HTTP，runner 可注入，不调用真实模型）。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture().start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def setUp(self):
        self.fixture.store.clear()
        self.fixture.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success",
                                                    "name": desc})

    @property
    def base(self):
        return self.fixture.base

    def _wait_status(self, jid, statuses, timeout=5.0):
        return self.fixture.wait_status(jid, statuses, timeout=timeout)

    # ---------- 创建任务与模式 ----------
    def test_build_defaults_to_fidelity_flow(self):
        """API 兼容：省略 mode 仍按高保真优先编排。"""
        captured = {}

        def fake_run(desc, interactive=False, log=None, cancel=None, mode="fidelity",
                     review_context=None, **kw):
            captured.update({"desc": desc, "mode": mode, "review_context": review_context})
            return {"ok": True, "outcome": "fidelity_success", "name": "塔", "pieces": 3}

        self.fixture.set_runner(fake_run)
        code, body, _ = self.fixture.post_json("/api/build", {"desc": "一座小塔"})
        self.assertEqual(code, 200)
        self.assertEqual(body.get("mode"), "fidelity", "响应必须回显实际模式")
        job = self._wait_status(body["id"], ("done",))
        self.assertEqual(captured["mode"], "fidelity")
        self.assertIsNone(captured["review_context"])
        self.assertEqual(captured["desc"], "一座小塔")
        self.assertEqual(job["result"]["outcome"], "fidelity_success")
        self.assertEqual(job["mode"], "fidelity")

    def test_build_explicit_fast_passthrough(self):
        captured = {}

        def fake_run(desc, **kw):
            captured["mode"] = kw.get("mode") or "fidelity"
            return {"ok": False, "error": "x", "outcome": "failed"}

        self.fixture.set_runner(fake_run)
        _, body, _ = self.fixture.post_json("/api/build", {"desc": "x", "mode": "fast"})
        self.assertEqual(body.get("mode"), "fast")
        job = self._wait_status(body["id"], ("error",))
        self.assertEqual(captured["mode"], "fast")
        self.assertEqual(job["mode"], "fast")

    def test_build_rejects_unknown_mode(self):
        code, _, _ = self.fixture.post_json("/api/build", {"desc": "x", "mode": "bogus"})
        self.assertEqual(code, 400)

    def test_invalid_inputs_do_not_start_generation(self):
        """非法输入：空描述不启动任务；非法 mode 返回 400，不调用 LLM。"""
        calls = []

        def fake_run(*a, **kw):
            calls.append(1)
            return {"ok": True, "outcome": "fast_success"}

        self.fixture.set_runner(fake_run)
        self.assertEqual(self.fixture.post_json(
            "/api/build", {"desc": "", "mode": "fast"})[0], 400)
        self.assertEqual(self.fixture.post_json(
            "/api/build", {"desc": "   ", "mode": "fidelity"})[0], 400)
        self.assertEqual(self.fixture.post_json(
            "/api/build", {"desc": "x", "mode": "bogus"})[0], 400)
        self.assertEqual(calls, [], "非法输入不得启动任何生成调用")
        self.assertEqual(len(self.fixture.store), 0)

    # ---------- 双模式恢复：手动重试继承原任务模式 ----------
    def _add_job(self, jid, *, mode="__absent__", result=None, status="done"):
        fields = {"status": status, "desc": "原始需求",
                  "result": result if result is not None else {"ok": True,
                                                              "outcome": "fast_success"}}
        if mode != "__absent__":
            fields["mode"] = mode
        return self.fixture.add_job(jid, **fields)

    def _retry_capture(self, jid):
        captured = {}

        def fake_run(desc, **kw):
            captured.update({"desc": desc, "mode": kw.get("mode"),
                             "review_context": kw.get("review_context")})
            return {"ok": True, "outcome": "fast_success", "name": "结果", "pieces": 2}

        self.fixture.set_runner(fake_run)
        code, body, _ = self.fixture.post_json("/api/retry", {"jobId": jid})
        self.assertEqual(code, 200)
        self.assertEqual(body.get("mode"), captured.get("mode"),
                         "响应必须回显新任务实际模式")
        job = self._wait_status(body["id"], ("done",))
        return captured, job

    def test_retry_inherits_fast_mode(self):
        self._add_job("fast1", mode="fast")
        captured, job = self._retry_capture("fast1")
        self.assertEqual(captured["mode"], "fast", "快速任务重试不得静默改成高保真")
        self.assertIsNone(captured["review_context"], "快速成功任务没有可继承的评审意见")
        self.assertEqual(captured["desc"], "原始需求")
        self.assertEqual(job["retryOf"], "fast1")

    def test_retry_legacy_mode_from_result(self):
        """旧记录没有任务级 mode：依次从 result.mode 补取。"""
        self._add_job("legacy1", mode="__absent__",
                      result={"ok": True, "mode": "fast", "outcome": "fast_success"})
        captured, _ = self._retry_capture("legacy1")
        self.assertEqual(captured["mode"], "fast")

    def test_retry_legacy_mode_from_run_record(self):
        """旧记录任务与结果都没有 mode：从 result.run_record.mode 补取。"""
        self._add_job("legacy2", mode="__absent__",
                      result={"ok": True, "run_record": {"mode": "fast"}})
        captured, _ = self._retry_capture("legacy2")
        self.assertEqual(captured["mode"], "fast")

    def test_retry_missing_mode_defaults_fidelity(self):
        """完全缺失 mode 的历史记录按约定回退 fidelity，不崩溃。"""
        self._add_job("legacy3", mode="__absent__", result={"ok": True})
        captured, job = self._retry_capture("legacy3")
        self.assertEqual(captured["mode"], "fidelity")
        self.assertEqual(job["mode"], "fidelity")

    def test_retry_fast_failure_keeps_clean_failure_summary(self):
        """快速失败重试只用清洗后的真实失败摘要，不编造评审评分。"""
        self._add_job("fastfail", mode="fast",
                      result={"ok": False, "error": "生成失败：求解未通过",
                              "failure": {"kind": "gate", "stage": "solve"}})
        captured, _ = self._retry_capture("fastfail")
        ctx = captured["review_context"]
        self.assertEqual(captured["mode"], "fast")
        self.assertIsInstance(ctx, dict)
        self.assertFalse(ctx["reviewAvailable"], "不得伪造评审可用")
        self.assertNotIn("scores", ctx, "快速任务不得编造评分")
        self.assertEqual(ctx["failureKind"], "gate")
        self.assertIn("失败类别 gate", ctx["failureSummary"])

    def test_retry_inherits_review_context(self):
        """手动重试必须携带原任务的有效视觉评审意见（评分/建议/保留部位）。"""
        self.fixture.add_job("orig", status="error", desc="一辆红色小车：车灯、黑鼻子",
                             result={"ok": False, "error": "生成失败：…",
                                     "review": {"scores": {"overall": 5, "color": 4},
                                                "missing_features": ["车灯缺失"],
                                                "worst_parts": ["车头比例偏短"],
                                                "suggestions": ["车头前伸 1 格"],
                                                "keep": ["黑鼻子"]},
                                     "review_flag": "review_failed",
                                     "failure": {"kind": "class2", "stage": "revise"}})
        captured = {}

        def fake_run(desc, interactive=False, log=None, cancel=None, mode="fidelity",
                     review_context=None, **kw):
            captured.update({"desc": desc, "mode": mode, "review_context": review_context})
            return {"ok": True, "outcome": "fidelity_success", "name": "车", "pieces": 5}

        self.fixture.set_runner(fake_run)
        code, body, _ = self.fixture.post_json("/api/retry", {"jobId": "orig"})
        self.assertEqual(code, 200)
        new_id = body["id"]
        job = self._wait_status(new_id, ("done",))
        self.assertIsNot(new_id, "orig")
        ctx = captured["review_context"]
        self.assertTrue(ctx["reviewAvailable"])
        self.assertEqual(ctx["scores"]["overall"], 5)
        self.assertEqual(ctx["missingFeatures"], ["车灯缺失"])
        self.assertEqual(ctx["keepParts"], ["黑鼻子"])
        self.assertEqual(captured["desc"], "一辆红色小车：车灯、黑鼻子", "原始需求保持不变")
        self.assertEqual(captured["mode"], "fidelity")
        self.assertEqual(job.get("retryOf"), "orig")

    def test_retry_uses_merged_fallback_context_when_present(self):
        """极速保底结果已合并高保真尝试的评审意见：重试原样透传（最新有效意见）。"""
        merged = {"reviewAvailable": True, "scores": {"overall": 6},
                  "missingFeatures": ["桅杆缺失"], "worstParts": [], "suggestions": [],
                  "keepParts": ["船身"], "flag": "review_failed", "failureSummary": None}
        self.fixture.add_job("fb", desc="帆船",
                             result={"ok": True, "outcome": "fast_fallback",
                                     "review_context": merged})
        captured = {}

        def fake_run(desc, **kw):
            captured["review_context"] = kw.get("review_context")
            return {"ok": True, "outcome": "fidelity_success", "name": "船"}

        self.fixture.set_runner(fake_run)
        _, body, _ = self.fixture.post_json("/api/retry", {"jobId": "fb"})
        self._wait_status(body["id"], ("done",))
        self.assertEqual(captured["review_context"], merged)

    def test_retry_running_job_rejected(self):
        self.fixture.add_job("run1", status="running", result=None, desc="x")
        code, _, _ = self.fixture.post_json("/api/retry", {"jobId": "run1"})
        self.assertEqual(code, 400)

    def test_retry_unknown_job_404(self):
        code, _, _ = self.fixture.post_json("/api/retry", {"jobId": "nope"})
        self.assertEqual(code, 404)

    def test_concurrent_jobs_run_and_cancel_independently(self):
        """两个任务并发推进；取消其一，另一个不受影响并照常完成。"""
        release = {"a": threading.Event(), "b": threading.Event()}

        def fake_run(desc, interactive=False, log=None, cancel=None, **kw):
            gate = release["a" if desc.startswith("甲") else "b"]
            while not gate.is_set() and not (cancel and cancel.is_set()):
                time.sleep(0.02)
            if log:
                log("info", f"{desc} 结束（cancel={bool(cancel and cancel.is_set())}）")
            if cancel and cancel.is_set():
                return {"ok": False, "error": "任务已取消", "status": "cancelled",
                        "failure": {"kind": "cancelled"}}
            return {"ok": True, "outcome": "fidelity_success", "name": desc, "pieces": 2}

        self.fixture.set_runner(fake_run)
        _, body_a, _ = self.fixture.post_json("/api/build", {"desc": "甲任务"})
        _, body_b, _ = self.fixture.post_json("/api/build", {"desc": "乙任务"})
        a, b = body_a["id"], body_b["id"]
        # 两个任务同时 running，互不阻塞
        _, jobs, _ = self.fixture.get_json("/api/jobs")
        statuses = {j["id"]: j["status"] for j in jobs["jobs"]}
        self.assertEqual(statuses[a], "running")
        self.assertEqual(statuses[b], "running")
        # 取消甲：立即 cancelled；乙不受影响仍在运行
        self.assertEqual(self.fixture.delete_json(f"/api/job/{a}")[0], 200)
        job_a = self._wait_status(a, ("cancelled",))
        _, jobs, _ = self.fixture.get_json("/api/jobs")
        statuses = {j["id"]: j["status"] for j in jobs["jobs"]}
        self.assertEqual(statuses[a], "cancelled")
        self.assertEqual(statuses[b], "running")
        # 释放乙：正常完成，结果独立
        release["b"].set()
        job_b = self._wait_status(b, ("done",))
        self.assertEqual(job_a["result"]["error"], "已由用户取消")
        self.assertEqual(job_b["result"]["outcome"], "fidelity_success")
        self.assertEqual(job_b["result"]["name"], "乙任务")
        self.assertNotIn("attempts_detail", job_b["result"])

    def test_jobs_summary_recovers_legacy_mode(self):
        """历史列表模式展示：旧记录从 result/run 记录补取，完全缺失按约定回退 fidelity。"""
        self._add_job("sum-fast", mode="__absent__",
                      result={"ok": True, "mode": "fast"}, status="done")
        self._add_job("sum-record", mode="__absent__",
                      result={"ok": True, "run_record": {"mode": "fidelity"}}, status="done")
        self._add_job("sum-none", mode="__absent__", result={"ok": True}, status="done")
        code, data, _ = self.fixture.get_json("/api/jobs")
        self.assertEqual(code, 200)
        rows = {j["id"]: j for j in data["jobs"]}
        self.assertEqual(rows["sum-fast"]["mode"], "fast")
        self.assertEqual(rows["sum-record"]["mode"], "fidelity")
        self.assertEqual(rows["sum-none"]["mode"], "fidelity")

    def test_restored_job_retry_keeps_mode(self):
        """重启恢复后手动重试仍继承原模式（持久化不丢）。"""
        self.fixture.add_job("restore-fast", desc="重启前的快速任务", mode="fast",
                             result={"ok": True, "outcome": "fast_success"})
        self.fixture.store.save()
        self.fixture.store.clear()
        self.fixture.store.load()
        self.assertEqual(self.fixture.store.get("restore-fast")["mode"], "fast")
        captured = {}

        def fake_run(desc, **kw):
            captured.update({"mode": kw.get("mode")})
            return {"ok": True, "outcome": "fast_success"}

        self.fixture.set_runner(fake_run)
        _, body, _ = self.fixture.post_json("/api/retry", {"jobId": "restore-fast"})
        job = self._wait_status(body["id"], ("done",))
        self.assertEqual(captured["mode"], "fast")
        self.assertEqual(job["mode"], "fast")
        self.assertEqual(job["retryOf"], "restore-fast")

    def test_job_fields_persist_and_restore(self):
        """mode/retryOf/reviewContext/startedAt 持久化 + 重启恢复（cancel/live 补齐）。"""
        ctx = {"reviewAvailable": False, "failureSummary": "失败类别 protocol"}
        self.fixture.add_job("t1", status="error", desc="石桥", mode="fidelity",
                             retryOf="orig9", reviewContext=ctx, startedAt=1.5,
                             result={"ok": False, "error": "x"})
        self.fixture.store.save()
        self.fixture.store.clear()
        self.fixture.store.load()
        job = self.fixture.store.get("t1")
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["mode"], "fidelity")
        self.assertEqual(job["retryOf"], "orig9")
        self.assertEqual(job["reviewContext"], ctx)
        self.assertEqual(job["startedAt"], 1.5)
        self.assertIsNotNone(job["cancel"])


if __name__ == "__main__":
    unittest.main()
