# -*- coding: utf-8 -*-
"""历史任务搜索/筛选/分页 与 前端多页面路由壳回归。

覆盖：无参数 /api/jobs 兼容行为不变；带分页参数时 0/1/20/21/50 条切片不重不漏、
搜索（名称/需求/任务 ID）、状态与交付结果筛选、running 数组不占页、非法参数 400；
/history、/jobs/<id>、/parts 与 / 返回同一应用壳；未知路径仍 404。

架构升级后改用独立 JobStore 夹具（不再清空模块级 JOBS），断言口径与改造前逐条一致。
"""
import json
import os
import sys
import threading
import unittest
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402


def _job(jid, status="done", desc=None, name=None, outcome=None, startedAt=1.0, pieces=None):
    result = {"ok": status == "done"}
    if name is not None:
        result["name"] = name
    if outcome is not None:
        result["outcome"] = outcome
    if pieces is not None:
        result["pieces"] = pieces
    if status == "error":
        result["error"] = "生成失败"
    return {"status": status, "result": result, "desc": desc,
            "startedAt": startedAt, "cancel": threading.Event()}


class ServerHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture().start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def setUp(self):
        self.fixture.store.clear()

    def _get_json(self, path):
        status, body, headers = self.fixture.get_json(path)
        if isinstance(body, dict) and "_raw" in body:
            return status, body["_raw"].decode("utf-8", "replace")
        return status, body

    def _get_raw(self, path):
        status, headers, raw = self.fixture.request(path)
        return status, raw, headers.get("Content-Type")

    def seed(self, n, prefix="t"):
        for i in range(n):
            jid = f"{prefix}{i:02d}"
            self.fixture.add_job(jid, **_job(jid, desc=f"需求 {jid}", name=f"模型{jid}",
                                             startedAt=1000.0 + i, pieces=i + 1))

    # ---------- 无参数兼容行为 ----------

    def test_jobs_no_params_keeps_compat(self):
        """无参数 /api/jobs：返回全量列表（不分页，按最新在前）。"""
        self.seed(25)
        self.fixture.add_job("run1", **_job("run1", status="running", desc="进行中",
                                            startedAt=9999))
        code, data = self._get_json("/api/jobs")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["jobs"]), 26)
        self.assertNotIn("total", data)
        self.assertNotIn("running", data)
        by_id = {j["id"]: j for j in data["jobs"]}
        self.assertEqual(by_id["t00"]["name"], "模型t00")
        self.assertEqual(by_id["run1"]["status"], "running")
        starts = [j["startedAt"] for j in data["jobs"]]
        self.assertEqual(starts, sorted(starts, reverse=True), "无参数响应同样最新在前")

    # ---------- 分页切片 ----------

    def test_pagination_slices_0_1_20_21_50(self):
        """0、1、20、21、50 条的分页切片不重不漏。"""
        for n in (0, 1, 20, 21, 50):
            with self.subTest(n=n):
                self.fixture.store.clear()
                self.seed(n)
                code, data = self._get_json("/api/jobs?page=1&pageSize=20")
                self.assertEqual(code, 200)
                self.assertEqual(data["total"], n)
                self.assertEqual(data["pages"], max(1, -(-n // 20)))
                expect = min(20, n)
                self.assertEqual(len(data["jobs"]), expect)
                # 最新在前：startedAt 降序
                starts = [j["startedAt"] for j in data["jobs"]]
                self.assertEqual(starts, sorted(starts, reverse=True))
                if n > 20:
                    seen = {j["id"] for j in data["jobs"]}
                    page = 2
                    while True:
                        _, dp = self._get_json(f"/api/jobs?page={page}&pageSize=20")
                        ids_p = {j["id"] for j in dp["jobs"]}
                        self.assertFalse(seen & ids_p, f"第 {page} 页与之前页面重复")
                        seen |= ids_p
                        if not ids_p or len(seen) >= n:
                            break
                        page += 1
                    self.assertEqual(len(seen), n, "翻完所有页不漏")
                code3, d3 = self._get_json("/api/jobs?page=99&pageSize=20")
                self.assertEqual(d3["jobs"], [])

    def test_page_beyond_total_returns_empty_not_error(self):
        self.seed(3)
        code, data = self._get_json("/api/jobs?page=2&pageSize=20")
        self.assertEqual(code, 200)
        self.assertEqual(data["jobs"], [])
        self.assertEqual(data["total"], 3)

    # ---------- 搜索 ----------

    def test_search_by_id_desc_name_case_insensitive(self):
        self.seed(3)
        self.fixture.add_job("ab12cd34", **_job("ab12cd34", desc="中世纪城堡，四座角楼",
                                                name="Castle", startedAt=2000))
        for q, expect in (("ab12", {"ab12cd34"}),          # 任务 ID
                          ("城堡", {"ab12cd34"}),           # 需求
                          ("castle", {"ab12cd34"}),         # 名称（大小写不敏感）
                          ("CASTLE", {"ab12cd34"}),
                          ("需求 t01", {"t01"}),            # 需求前缀
                          ("不存在", set())):
            with self.subTest(q=q):
                code, data = self._get_json(
                    f"/api/jobs?page=1&pageSize=20&q={urllib.parse.quote(q)}")
                self.assertEqual(code, 200)
                self.assertEqual({j["id"] for j in data["jobs"]}, expect)

    def test_long_desc_searchable_and_intact(self):
        """长文本需求（5000 字）可搜索、不截断崩坏。"""
        long_desc = "中世纪" + "很长的需求描述" * 600
        self.fixture.add_job("long1", **_job("long1", desc=long_desc, startedAt=3000))
        code, data = self._get_json(
            "/api/jobs?page=1&pageSize=20&q=" + urllib.parse.quote("很长的需求描述"))
        self.assertEqual([j["id"] for j in data["jobs"]], ["long1"])
        self.assertEqual(data["jobs"][0]["desc"], long_desc)

    # ---------- 筛选 ----------

    def test_status_filter_and_default_excludes_running(self):
        """主列表默认不含 running（进行中专区单独展示）；显式 status 可筛 running。"""
        self.seed(5)
        self.fixture.add_job("r1", **_job("r1", status="running", desc="进行中",
                                          startedAt=5000))
        code, data = self._get_json("/api/jobs?page=1&pageSize=20")
        self.assertEqual(data["total"], 5)
        self.assertEqual([j["id"] for j in data["running"]], ["r1"])
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&status=running")
        self.assertEqual([j["id"] for j in data["jobs"]], ["r1"])
        self.assertEqual(data["total"], 1)
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&status=error,cancelled")
        self.assertEqual(data["jobs"], [])

    def test_outcome_filter_and_cancelled_derivation(self):
        """交付结果筛选；DELETE 直取的取消任务（result 无 outcome）按 cancelled 归类。"""
        self.fixture.add_job("ok1", **_job("ok1", outcome="fidelity_success", startedAt=1))
        self.fixture.add_job("dg1", **_job("dg1", outcome="fidelity_degraded", startedAt=2))
        self.fixture.add_job("fb1", **_job("fb1", outcome="fast_fallback", startedAt=3))
        self.fixture.add_job("bad1", **_job("bad1", outcome="failed", startedAt=4))
        # 无 outcome 字段的取消任务
        self.fixture.add_job("cx1", **_job("cx1", status="cancelled", startedAt=5))
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&outcome=fidelity_success,fast_fallback")
        self.assertEqual({j["id"] for j in data["jobs"]}, {"ok1", "fb1"})
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&outcome=cancelled")
        self.assertEqual({j["id"] for j in data["jobs"]}, {"cx1"})

    def test_legacy_jobs_derive_outcome(self):
        """存量任务（outcome 字段引入前）也要推导 outcome：入口与交付结果筛选覆盖旧历史。"""
        self.fixture.add_job("old_ok", **_job("old_ok", desc="旧石桥", name="旧石桥", startedAt=1))
        self.fixture.add_job("old_dg", **_job("old_dg", desc="x", name="x", startedAt=2))
        with self.fixture.store.lock:
            self.fixture.store.get_locked("old_dg")["result"]["review_failed"] = True
        self.fixture.add_job("old_err", **_job("old_err", status="error", desc="y", startedAt=3))
        # 摘要推导
        code, data = self._get_json("/api/jobs")
        by_id = {j["id"]: j for j in data["jobs"]}
        self.assertEqual(by_id["old_ok"]["outcome"], "fast_success")
        self.assertEqual(by_id["old_dg"]["outcome"], "fidelity_degraded")
        self.assertEqual(by_id["old_err"]["outcome"], "failed")
        # 筛选覆盖存量任务
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&outcome=fast_success")
        self.assertIn("old_ok", {j["id"] for j in data["jobs"]})
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&outcome=fidelity_degraded")
        self.assertIn("old_dg", {j["id"] for j in data["jobs"]})
        code, data = self._get_json("/api/jobs?page=1&pageSize=20&outcome=failed")
        self.assertIn("old_err", {j["id"] for j in data["jobs"]})

    def test_combined_search_and_filters(self):
        for i in range(30):
            self.fixture.add_job(f"s{i:02d}", **_job(
                f"s{i:02d}", outcome="fidelity_success" if i % 2 else "failed",
                desc="帆船" if i % 3 == 0 else "别的需求", startedAt=100 + i))
        code, data = self._get_json(
            "/api/jobs?page=1&pageSize=20&q=" + urllib.parse.quote("帆船") +
            "&outcome=fidelity_success")
        self.assertEqual(code, 200)
        self.assertEqual({j["id"] for j in data["jobs"]},
                         {f"s{i:02d}" for i in range(30) if i % 3 == 0 and i % 2})

    # ---------- 非法参数 ----------

    def test_invalid_params_400(self):
        self.seed(2)
        for qs in ("page=0", "page=-1", "pageSize=0", "pageSize=101", "page=abc",
                   "status=bogus", "outcome=bogus"):
            with self.subTest(qs=qs):
                code, data = self._get_json(f"/api/jobs?{qs}")
                self.assertEqual(code, 400, qs)
                self.assertIn("error", data)

    # ---------- 前端路由壳 ----------

    def test_frontend_routes_serve_same_shell(self):
        """/history、/jobs/<id>、/parts 与 / 返回同一 HTML 应用壳。"""
        base_code, base_body, base_ct = self._get_raw("/")
        self.assertEqual(base_code, 200)
        self.assertIn("text/html", base_ct)
        for route in ("/index.html", "/history", "/history?q=x&page=2", "/jobs/ab12cd34",
                      "/jobs/", "/parts"):
            code, body, ct = self._get_raw(route)
            with self.subTest(route=route):
                self.assertEqual(code, 200, route)
                self.assertIn("text/html", ct or "", route)
                self.assertEqual(body, base_body, route)

    def test_unknown_path_still_404(self):
        code, _, _ = self._get_raw("/definitely-not-a-route")
        self.assertEqual(code, 404)

    def test_api_routes_not_shadowed_by_shell(self):
        """/api/jobs、/api/parts 仍是 JSON，不被前端路由壳吞掉。"""
        code, data = self._get_json("/api/jobs")
        self.assertEqual(code, 200)
        self.assertIn("jobs", data)
        code, data = self._get_json("/api/parts")
        self.assertEqual(code, 200)
        self.assertIn("parts", data)


if __name__ == "__main__":
    unittest.main()
