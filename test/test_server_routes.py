# -*- coding: utf-8 -*-
"""Web 服务路由与安全回归（P0 安全项）。

进程内起真实 HTTP 服务（独立 JobStore/JobService 夹具），覆盖：415 Content-Type 校验、
跨源 Origin 拒绝、/files 白名单（不暴露任务历史与运行记录）、历史任务 DELETE 不崩溃、
详情下发思考通道而列表保持轻量、原子持久化与重启 running→interrupted。
"""
import json
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402
from legogod.artifact_service import files_allowed, is_blocked_name  # noqa: E402


class ArtifactNamePolicyTest(unittest.TestCase):
    """产物名策略纯函数：大小写/短名黑名单（不依赖 HTTP）。"""

    def test_blocked_names_are_case_insensitive(self):
        for name in ("jobs_store.json", "JOBS_STORE.json", "Jobs_Store.JSON",
                     "run_abcd.json", "RUN_ABCD.JSON", "Run_x.json"):
            with self.subTest(name=name):
                self.assertTrue(is_blocked_name(name))
                self.assertIsNone(files_allowed(name))

    def test_normal_artifacts_still_allowed(self):
        for name in ("model_a_r001_x.json", "solution_a_r001_x.json",
                     "拼装步骤_a_r001_x.md"):
            with self.subTest(name=name):
                self.assertFalse(is_blocked_name(name))
                self.assertIsNotNone(files_allowed(name))

    def test_runtime_prefix_not_over_blocked(self):
        """`running_*`/`runtime_*` 不是黑名单前缀，避免误伤合法产物名。"""
        for name in ("runtime_model.json", "running_notes.md"):
            with self.subTest(name=name):
                self.assertIsNotNone(files_allowed(name))


class ServerRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture().start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def setUp(self):
        self.fixture.store.clear()

    def _request(self, path, method="GET", body=None, headers=None):
        status, _, raw = self.fixture.request(path, method=method, body=body,
                                              headers=headers or {})
        return status, raw

    def test_build_requires_json_content_type(self):
        """POST /api/build 用非 JSON Content-Type → 415（CSRF 防线）。"""
        code, _ = self._request("/api/build", method="POST",
                                body=json.dumps({"desc": "x"}).encode(),
                                headers={"Content-Type": "text/plain"})
        self.assertEqual(code, 415)

    def test_build_rejects_cross_origin(self):
        """跨源 Origin（与 Host 不一致）→ 403。"""
        code, _ = self._request("/api/build", method="POST",
                                body=json.dumps({"desc": "x"}).encode(),
                                headers={"Content-Type": "application/json",
                                         "Origin": "http://evil.example.com"})
        self.assertEqual(code, 403)

    def test_files_whitelist_blocks_job_store_and_run_records(self):
        """/files 不暴露 jobs_store 与 run_*.json（本地任务历史不外泄）。"""
        for name in ("jobs_store.json", "run_abcd1234.json"):
            with open(os.path.join(self.fixture.artifacts_dir, name), "w",
                      encoding="utf-8") as f:
                f.write("{}")
            code, _ = self._request(f"/files/{name}")
            self.assertEqual(code, 404, name)

    def test_files_whitelist_is_case_insensitive(self):
        """大写/混合大小写文件名不得绕过 jobs_store / run_ 黑名单。

        回归点（2026-11-15 复核）：Windows 文件系统不区分大小写，原实现按大小写敏感
        startswith 判断，`/files/JOBS_STORE.json` 会解析到同一个 `jobs_store.json`，
        从而读到完整任务历史；`RUN_*.json` 同类。
        """
        history_marker = '{"marker": "case-bypass"}'
        with open(os.path.join(self.fixture.artifacts_dir, "jobs_store.json"), "w",
                  encoding="utf-8") as f:
            f.write(history_marker)
        with open(os.path.join(self.fixture.artifacts_dir, "run_abcd1234.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"marker": "run"}')
        attempts = ("/files/JOBS_STORE.json", "/files/Jobs_Store.JSON",
                    "/files/jobs_store.JSON", "/files/JOBS_STORE.JSON",
                    "/files/RUN_abcd1234.json", "/files/Run_AbCd1234.JSON",
                    "/files/%4aOBS_STORE.json")
        for path in attempts:
            with self.subTest(path=path):
                code, raw = self._request(path)
                self.assertEqual(code, 404, path)
                self.assertNotIn(history_marker.encode("utf-8"), raw, path)
        # 正常产物不被误伤（大写扩展名在大小写不敏感文件系统上仍指向同一产物）
        with open(os.path.join(self.fixture.artifacts_dir, "model_case_r001_x.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"name": "case"}')
        code, raw = self._request("/files/model_case_r001_x.json")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["name"], "case")

    def test_files_serves_model_artifacts(self):
        """/files 放行拼装产物（model_*.json）。"""
        with open(os.path.join(self.fixture.artifacts_dir, "model_demo_r001_x.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"name": "demo"}')
        code, body = self._request("/files/model_demo_r001_x.json")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["name"], "demo")

    def test_delete_unknown_job_is_404_not_crash(self):
        """DELETE 历史/未知任务：404 或正常取消，绝不让服务端崩溃。"""
        code, _ = self._request("/api/job/nonexistent", method="DELETE")
        self.assertEqual(code, 404)

    def test_jobs_list_includes_error_jobs_with_desc_and_error(self):
        """/api/jobs 包含失败任务；desc 顶层缺失时回退 run_record 的输入快照（旧库兼容）。"""
        self.fixture.add_job("ok1", desc="石桥",
                             result={"ok": True, "name": "石桥", "pieces": 123})
        # 旧库形态：无顶层 desc，只能从 result.run_record.desc 拿输入快照
        self.fixture.add_job("bad1", status="error", desc=None, startedAt=2.0,
                             result={"ok": False, "error": "阶段 revise 请求超限",
                                     "run_record": {"desc": "主战坦克", "mode": "fast"}})
        # 顶层 desc 优先于 run_record 快照
        self.fixture.add_job("bad2", status="error", desc="塔楼", startedAt=3.0,
                             result={"ok": False, "error": "x",
                                     "run_record": {"desc": "快照描述"}})
        code, body, _ = self.fixture.get_json("/api/jobs")
        self.assertEqual(code, 200)
        jobs = {j["id"]: j for j in body["jobs"]}
        self.assertEqual(jobs["bad1"]["status"], "error")
        self.assertEqual(jobs["bad1"]["desc"], "主战坦克")
        self.assertEqual(jobs["bad1"]["error"], "阶段 revise 请求超限")
        self.assertEqual(jobs["bad2"]["desc"], "塔楼")
        self.assertEqual(jobs["ok1"]["name"], "石桥")
        self.assertEqual(jobs["ok1"]["pieces"], 123)

    def test_job_detail_returns_thinking_but_list_does_not(self):
        """/api/job 带思考通道与会话；/api/jobs 列表项不带思考内容（列表保持轻量）。"""
        thinking_text = "这一轮推理原文"
        self.fixture.add_job(
            "th1", status="running", startedAt=1.0, desc="石桥", result=None,
            logs=[{"kind": "thinking", "text": thinking_text, "ts": 2.0,
                   "phase": "plan", "done": True, "chars": len(thinking_text),
                   "truncated": False, "partial": False, "elapsed": 3}],
            thinking={"phase": "draw", "text": "正在推理", "elapsed": 1,
                      "done": False, "partial": False, "chars": 4})
        code, body, _ = self.fixture.get_json("/api/job/th1")
        self.assertEqual(code, 200)
        self.assertEqual(body["thinking"]["text"], "正在推理")
        self.assertEqual(body["logs"][0]["text"], thinking_text)
        code, body, _ = self.fixture.get_json("/api/jobs")
        self.assertEqual(code, 200)
        row = next(j for j in body["jobs"] if j["id"] == "th1")
        for key in ("thinking", "logs"):
            self.assertNotIn(key, row, f"/api/jobs 不得下发 {key}")
        self.assertNotIn(thinking_text, json.dumps(body, ensure_ascii=False))

    def test_jobs_store_atomic_and_restore_marks_interrupted(self):
        """持久化原子写 + 恢复时遗留 running 标记为 interrupted，cancel 字段补齐。"""
        self.fixture.add_job("t1", status="running", desc="石桥", result=None,
                             cancel=threading.Event(), startedAt=1.0)
        self.assertTrue(self.fixture.store.save())
        self.assertTrue(os.path.isfile(self.fixture.store.store_path))
        self.fixture.store.clear()
        self.assertEqual(self.fixture.store.load(), 1)
        job = self.fixture.store.get("t1")
        self.assertEqual(job["status"], "interrupted")
        self.assertEqual(job["desc"], "石桥")
        self.assertIsNotNone(job["cancel"])
        code, _ = self._request("/api/job/t1", method="DELETE")
        self.assertEqual(code, 200)


if __name__ == "__main__":
    unittest.main()
