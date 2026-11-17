# -*- coding: utf-8 -*-
"""任务应用服务回归。

JobService 通过构造参数接收 JobStore 与 runner：测试独立实例化、注入可控 runner，
不依赖模块级单例，也不清空任何全局状态。覆盖：
1) 创建：双模式、缺省 fidelity、空描述/非法模式拒绝（不启动 worker）；
2) 并发：每任务独立线程，取消其一不影响另一个；
3) 取消：立即标记，worker 返回不得覆盖，取消后不启动保底（由 runner 观测 cancel 事件）；
4) 重试：原模式继承矩阵、原文回退、评审上下文继承、运行中拒绝、未知任务 404；
5) worker：内部异常映射、结果结构异常、日志/设计稿/进度分通道写入；
6) 历史保留上限与实例隔离。
"""
import os
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from legogod.job_service import JobService, JobServiceError  # noqa: E402
from legogod.job_store import JobStore  # noqa: E402


class JobServiceTestBase(unittest.TestCase):
    """独立 store/service 夹具；runner 可替换。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-jsvc-")
        self.store = JobStore(self.tmp)
        self.runner = None
        self.service = JobService(self.store, runner=self._dispatch,
                                  artifacts_dir=self.tmp)

    def tearDown(self):
        """等所有 worker 落终态后再删临时目录，避免后台线程写已删除目录产生噪音日志。"""
        deadline = time.time() + 5
        while time.time() < deadline:
            with self.store.lock:
                running = any(job.get("status") == "running"
                              for _, job in self.store.items_locked())
            if not running:
                break
            time.sleep(0.02)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _dispatch(self, *args, **kwargs):
        if self.runner is None:
            return {"ok": True, "outcome": "fast_success"}
        return self.runner(*args, **kwargs)

    def set_runner(self, runner):
        self.runner = runner

    def wait_terminal(self, job_id, timeout=5.0):
        """等任务离开 running；返回任务记录引用。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.store.lock:
                job = self.store.get_locked(job_id)
                if job is not None and job.get("status") != "running":
                    return job
            time.sleep(0.02)
        self.fail(f"任务 {job_id} 未在 {timeout}s 内结束")

    def job(self, job_id):
        return self.service.get_job(job_id)


class CreateJobTest(JobServiceTestBase):
    def test_default_mode_is_fidelity(self):
        captured = {}

        def runner(desc, **kw):
            captured.update({"desc": desc, "mode": kw.get("mode"),
                             "review_context": kw.get("review_context")})
            return {"ok": True, "outcome": "fidelity_success"}

        self.set_runner(runner)
        response = self.service.create_job("一座小塔")
        self.assertEqual(set(response), {"id", "mode"})
        self.assertEqual(response["mode"], "fidelity")
        job = self.wait_terminal(response["id"])
        self.assertEqual(job["status"], "done")
        self.assertEqual(captured["mode"], "fidelity")
        self.assertEqual(captured["desc"], "一座小塔")
        self.assertIsNone(captured["review_context"])

    def test_explicit_fast_mode(self):
        captured = {}
        self.set_runner(lambda desc, **kw: captured.update({"mode": kw.get("mode")})
                        or {"ok": True, "outcome": "fast_success"})
        response = self.service.create_job("x", "fast")
        self.assertEqual(response["mode"], "fast")
        self.wait_terminal(response["id"])
        self.assertEqual(captured["mode"], "fast")
        self.assertEqual(self.job(response["id"])["mode"], "fast")

    def test_invalid_inputs_do_not_start_worker(self):
        calls = []
        self.set_runner(lambda *a, **kw: calls.append(1) or {"ok": True})
        for desc, mode, code, status in (("", "fast", "empty_desc", 400),
                                         ("   ", "fidelity", "empty_desc", 400),
                                         ("x", "bogus", "invalid_mode", 400)):
            with self.subTest(desc=desc, mode=mode):
                with self.assertRaises(JobServiceError) as ctx:
                    self.service.create_job(desc, mode)
                self.assertEqual(ctx.exception.code, code)
                self.assertEqual(ctx.exception.status, status)
        self.assertEqual(calls, [])
        self.assertEqual(len(self.store), 0)

    def test_mode_normalization_matches_api_contract(self):
        """空串 mode 回退 fidelity；首尾空白被裁剪；非法大小写不静默纠正。"""
        self.assertEqual(self.service.create_job("x", "")["mode"], "fidelity")
        self.assertEqual(self.service.create_job("y", "  fast  ")["mode"], "fast")
        with self.assertRaises(JobServiceError):
            self.service.create_job("z", "FAST")


class CancelJobTest(JobServiceTestBase):
    def test_cancel_running_job_marks_immediately(self):
        started = threading.Event()
        release = threading.Event()

        def runner(desc, log=None, cancel=None, **kw):
            started.set()
            release.wait(5)
            return {"ok": True, "outcome": "fidelity_success"}

        self.set_runner(runner)
        created = self.service.create_job("甲任务")
        self.assertTrue(started.wait(3))
        response = self.service.cancel_job(created["id"])
        self.assertEqual(response, {"cancelling": True})
        job = self.job(created["id"])
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["result"]["error"], "已由用户取消")
        self.assertIsNone(job["live"])
        # worker 之后返回成功也不得覆盖取消结果
        release.set()
        deadline = time.time() + 5
        while time.time() < deadline:
            job = self.job(created["id"])
            with self.store.lock:
                live = self.store.get_locked(created["id"]).get("live")
            if live is None:
                break
            time.sleep(0.02)
        time.sleep(0.1)
        job = self.job(created["id"])
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["result"]["error"], "已由用户取消")

    def test_cancel_unknown_job_returns_none(self):
        self.assertIsNone(self.service.cancel_job("nope"))

    def test_cancel_completed_job_keeps_status(self):
        self.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success"})
        created = self.service.create_job("x")
        self.wait_terminal(created["id"])
        response = self.service.cancel_job(created["id"])
        self.assertEqual(response, {"cancelling": True})
        job = self.job(created["id"])
        self.assertEqual(job["status"], "done")
        self.assertTrue(job["result"]["ok"])

    def test_concurrent_jobs_are_independent(self):
        gates = {"甲": threading.Event(), "乙": threading.Event()}

        def runner(desc, log=None, cancel=None, **kw):
            gate = gates["甲" if desc.startswith("甲") else "乙"]
            while not gate.is_set() and not (cancel and cancel.is_set()):
                time.sleep(0.01)
            if cancel and cancel.is_set():
                return {"ok": False, "error": "任务已取消", "status": "cancelled"}
            return {"ok": True, "outcome": "fidelity_success", "name": desc}

        self.set_runner(runner)
        a = self.service.create_job("甲任务")
        b = self.service.create_job("乙任务")
        self.assertEqual(self.job(a["id"])["status"], "running")
        self.assertEqual(self.job(b["id"])["status"], "running")
        self.service.cancel_job(a["id"])
        self.assertEqual(self.job(a["id"])["status"], "cancelled")
        self.assertEqual(self.job(b["id"])["status"], "running")
        gates["乙"].set()
        job_b = self.wait_terminal(b["id"])
        self.assertEqual(job_b["status"], "done")
        self.assertEqual(job_b["result"]["name"], "乙任务")


class RetryJobTest(JobServiceTestBase):
    def _add(self, job_id, **fields):
        job = {"id": job_id, "status": "done", "logs": [], "live": None, "result": None,
               "desc": None, "startedAt": 1.0, "cancel": threading.Event()}
        job.update(fields)
        with self.store.lock:
            self.store.put_locked(job_id, job)
        return job

    def _capture_retry(self, job_id):
        captured = {}

        def runner(desc, **kw):
            captured.update({"desc": desc, "mode": kw.get("mode"),
                             "review_context": kw.get("review_context")})
            return {"ok": True, "outcome": "fast_success"}

        self.set_runner(runner)
        response = self.service.retry_job(job_id)
        job = self.wait_terminal(response["id"])
        return captured, response, job

    def test_retry_inherits_mode_matrix(self):
        self._add("fast1", mode="fast", desc="需求A",
                  result={"ok": True, "outcome": "fast_success"})
        self._add("legacy_result", desc="需求B",
                  result={"ok": True, "mode": "fast", "outcome": "fast_success"})
        self._add("legacy_record", desc="需求C", result={"ok": True, "run_record": {"mode": "fast"}})
        self._add("legacy_none", desc="需求D", result={"ok": True})
        expectations = {"fast1": "fast", "legacy_result": "fast",
                        "legacy_record": "fast", "legacy_none": "fidelity"}
        for job_id, mode in expectations.items():
            with self.subTest(job_id=job_id):
                captured, response, job = self._capture_retry(job_id)
                self.assertEqual(captured["mode"], mode)
                self.assertEqual(response["mode"], mode)
                self.assertEqual(job["mode"], mode)
                self.assertEqual(job["retryOf"], job_id)

    def test_retry_desc_falls_back_to_run_record(self):
        self._add("old", mode="fast", desc=None,
                  result={"ok": True, "run_record": {"desc": "旧需求原文"}})
        captured, _, _ = self._capture_retry("old")
        self.assertEqual(captured["desc"], "旧需求原文")

    def test_retry_inherits_review_context(self):
        merged = {"reviewAvailable": True, "scores": {"overall": 6},
                  "missingFeatures": ["桅杆缺失"], "keepParts": ["船身"]}
        self._add("fb", mode="fidelity", desc="帆船",
                  result={"ok": True, "outcome": "fast_fallback", "review_context": merged})
        captured, _, _ = self._capture_retry("fb")
        self.assertEqual(captured["review_context"], merged)

    def test_retry_rejects_running_and_unknown(self):
        self._add("run1", status="running", desc="x", result=None)
        with self.assertRaises(JobServiceError) as ctx:
            self.service.retry_job("run1")
        self.assertEqual(ctx.exception.code, "job_running")
        self.assertEqual(ctx.exception.status, 400)
        with self.assertRaises(JobServiceError) as ctx:
            self.service.retry_job("nope")
        self.assertEqual(ctx.exception.code, "unknown_job")
        self.assertEqual(ctx.exception.status, 404)

    def test_retry_missing_desc_rejected(self):
        self._add("nodesc", desc=None, result={"ok": True})
        with self.assertRaises(JobServiceError) as ctx:
            self.service.retry_job("nodesc")
        self.assertEqual(ctx.exception.code, "missing_desc")
        self.assertEqual(ctx.exception.status, 400)


class WorkerTest(JobServiceTestBase):
    def test_internal_exception_maps_to_error(self):
        def runner(desc, **kw):
            raise RuntimeError("模型连接断开")

        self.set_runner(runner)
        created = self.service.create_job("x")
        job = self.wait_terminal(created["id"])
        self.assertEqual(job["status"], "error")
        self.assertIn("内部异常", job["result"]["error"])
        self.assertIn("模型连接断开", job["result"]["error"])
        self.assertIsNone(job["live"])

    def test_cancelled_result_maps_to_cancelled(self):
        self.set_runner(lambda desc, **kw: {"ok": False, "error": "任务已取消",
                                            "status": "cancelled"})
        created = self.service.create_job("x")
        job = self.wait_terminal(created["id"])
        self.assertEqual(job["status"], "cancelled")

    def test_failed_result_maps_to_error(self):
        self.set_runner(lambda desc, **kw: {"ok": False, "error": "求解未通过",
                                            "outcome": "failed"})
        created = self.service.create_job("x")
        job = self.wait_terminal(created["id"])
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["result"]["outcome"], "failed")

    def test_malformed_result_does_not_crash_worker(self):
        self.set_runner(lambda desc, **kw: "不是字典")
        created = self.service.create_job("x")
        job = self.wait_terminal(created["id"])
        self.assertEqual(job["status"], "error")

    def test_log_callback_writes_channels(self):
        seen = {}

        def runner(desc, log=None, **kw):
            log("phase", "plan", {"phase": "plan"})
            log("design", "", {"design": {"grid": {"w": 2, "d": 2},
                                          "layers": [{"y": 0, "rows": ["##", "##"]}]}})
            log("progress", "", {"layer": 1, "total": 2, "round": 1})
            log("live", "生成中")
            log("info", "普通日志")
            seen["ok"] = True
            return {"ok": True, "outcome": "fast_success"}

        self.set_runner(runner)
        created = self.service.create_job("x")
        job = self.wait_terminal(created["id"])
        self.assertTrue(seen.get("ok"))
        self.assertEqual(job["stage"]["current"], "plan")
        self.assertIn("plan", job["stage"]["seen"])
        self.assertEqual(job["progress"]["layer"], 1)
        self.assertIsNotNone(job["design"])
        self.assertEqual(job["design"]["grid"], {"w": 2, "d": 2})
        kinds = [entry["kind"] for entry in job["logs"]]
        self.assertIn("info", kinds)
        self.assertNotIn("design", kinds, "设计稿不进日志列表（独立通道）")

    def test_job_persisted_and_restorable(self):
        self.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success",
                                            "name": "结果"})
        created = self.service.create_job("x", "fast")
        self.wait_terminal(created["id"])
        # 终态现在只会在最终保存后可见；保留 Windows 瞬时共享冲突的有界重试验证。
        saved = False
        for _ in range(50):
            if self.store.save():
                saved = True
                break
            time.sleep(0.01)
        self.assertTrue(saved, "任务历史保存一直失败")
        reloaded = JobStore(self.tmp)
        self.assertEqual(reloaded.load(), 1)
        with reloaded.lock:
            job = reloaded.get_locked(created["id"])
        self.assertEqual(job["mode"], "fast")
        self.assertEqual(job["status"], "done")
        self.assertIsNotNone(job["cancel"])

    def test_terminal_status_is_published_only_after_final_save(self):
        """最终保存被阻塞时仍显示 running；保存返回后才允许发布 done。"""
        release_save = threading.Event()
        original_save = self.store.save

        def delayed_save(*args, **kwargs):
            if kwargs.get("terminal"):
                release_save.wait(1)
            return original_save(*args, **kwargs)

        self.store.save = delayed_save
        created = self.service.create_job("x", "fast")
        time.sleep(0.05)
        with self.store.lock:
            self.assertEqual(self.store.get_locked(created["id"])["status"], "running")
        release_save.set()
        job = self.wait_terminal(created["id"])
        self.assertEqual(job["status"], "done")
        reloaded = JobStore(self.tmp)
        self.assertEqual(reloaded.load(), 1)
        with reloaded.lock:
            self.assertEqual(reloaded.get_locked(created["id"])["status"], "done")


class HistoryAndTrimTest(JobServiceTestBase):
    def test_query_jobs_compat_and_paged(self):
        for index in range(3):
            with self.store.lock:
                self.store.put_locked(f"j{index}", {
                    "id": f"j{index}", "status": "done", "logs": [], "live": None,
                    "desc": f"需求{index}", "result": {"ok": True}, "startedAt": 1.0 + index,
                    "cancel": threading.Event()})
        compat = self.service.query_jobs({})
        self.assertEqual(set(compat), {"jobs"})
        self.assertEqual(len(compat["jobs"]), 3)
        page = self.service.query_jobs({"page": ["1"], "pageSize": ["2"]})
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["jobs"]), 2)
        with self.assertRaises(ValueError):
            self.service.query_jobs({"page": ["0"]})

    def test_trim_keeps_limit_and_running(self):
        small = JobStore(self.tmp, max_jobs=3)
        service = JobService(small, runner=lambda desc, **kw: {"ok": True}, artifacts_dir=self.tmp)

        def wait_done(job_id):
            deadline = time.time() + 5
            while time.time() < deadline:
                with small.lock:
                    status = small.get_locked(job_id)["status"]
                if status != "running":
                    return status
                time.sleep(0.01)
            return None

        for index in range(4):
            created = service.create_job(f"任务{index}")
            self.assertEqual(wait_done(created["id"]), "done")

        gate = threading.Event()

        def slow_runner(desc, **kw):
            gate.wait(5)
            return {"ok": True}

        service.runner = slow_runner
        running = service.create_job("进行中任务")
        gate.set()
        self.assertEqual(wait_done(running["id"]), "done")
        with small.lock:
            jobs = [job for _, job in small.items_locked()]
        self.assertLessEqual(len(jobs), 3, "历史条数上限失效")
        ids = {job.get("id") for job in jobs}
        self.assertIn(running["id"], ids, "running/最新完成任务不得被裁掉")
        self.assertNotIn("任务0", {job.get("desc") for job in jobs}, "最旧已完成任务应被裁掉")

    def test_services_are_isolated(self):
        other_tmp = tempfile.mkdtemp(prefix="legogod-jsvc-b-")
        try:
            other = JobService(JobStore(other_tmp), runner=lambda desc, **kw: {"ok": True},
                               artifacts_dir=other_tmp)
            mine = self.service.create_job("甲")
            theirs = other.create_job("乙")
            self.wait_terminal(mine["id"])
            self.assertIsNotNone(self.service.get_job(mine["id"]))
            self.assertIsNone(self.service.get_job(theirs["id"]),
                              "另一个 store 的任务不得泄漏到本实例")
            self.assertIsNotNone(other.get_job(theirs["id"]))
            deadline = time.time() + 5
            while time.time() < deadline:
                with other.store.lock:
                    status = other.store.get_locked(theirs["id"])["status"]
                if status != "running":
                    break
                time.sleep(0.02)
        finally:
            import shutil
            shutil.rmtree(other_tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
