# -*- coding: utf-8 -*-
"""访问安全回归。

覆盖：
1) Bearer 认证：配置令牌后任务读写必须带正确令牌；健康检查/零件目录保持开放；
   query token 不被接受；错误令牌拿不到任何任务数据。
2) Origin/CORS：同源可写；非法 Origin 继续 403；显式 allowlist 可跨源写并回 ACAO；
   非 allowlist 来源不下发 CORS 头；预检只允许必要方法与请求头。
3) 非回环监听门槛：无令牌拒绝启动；配置了令牌可以启动。
4) 令牌不泄露：响应体、启动日志、策略描述都不含令牌原文。
5) 配置纪律：`*` 通配 Origin 与非法 Origin 在启动时明确报错。
"""
import contextlib
import io
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402
from legogod import api_security as security  # noqa: E402
from legogod import server as lego_server  # noqa: E402

TOKEN = "test-token-please-ignore"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ALLOWED = "http://127.0.0.1:8601"


class BearerAuthTest(unittest.TestCase):
    """令牌门槛：写操作与敏感读接口要求 Bearer。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture(token=TOKEN).start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def setUp(self):
        self.fixture.store.clear()
        self.fixture.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success"})

    def test_task_endpoints_require_token(self):
        """无令牌/错误令牌：任务读写 401；且不会创建或读取任何数据。"""
        for headers in ({}, {"Authorization": "Bearer wrong"},
                        {"Authorization": "Basic xyz"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.fixture.get_json("/api/jobs", headers=headers)[0], 401)
                self.assertEqual(self.fixture.get_json("/api/job/x", headers=headers)[0], 401)
                self.assertEqual(self.fixture.post_json(
                    "/api/build", {"desc": "x"}, headers=headers)[0], 401)
                self.assertEqual(self.fixture.post_json(
                    "/api/retry", {"jobId": "x"}, headers=headers)[0], 401)
                self.assertEqual(self.fixture.delete_json(
                    "/api/job/x", headers=headers)[0], 401)
        self.assertEqual(len(self.fixture.store), 0, "未认证请求不得创建任务")

    def test_correct_token_grants_access(self):
        status, body, _ = self.fixture.post_json("/api/build", {"desc": "塔"}, headers=AUTH)
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "fidelity")
        job = self.fixture.wait_status(body["id"], ("done",), headers=AUTH)
        self.assertEqual(job["status"], "done")
        self.assertEqual(self.fixture.get_json("/api/jobs", headers=AUTH)[0], 200)
        self.assertEqual(self.fixture.delete_json(
            f"/api/job/{body['id']}", headers=AUTH)[0], 200)

    def test_open_endpoints_stay_open(self):
        """健康检查与零件目录不因令牌门槛失效（不含任务内容）。"""
        self.assertEqual(self.fixture.get_json("/api/health")[0], 200)
        self.assertEqual(self.fixture.get_json("/api/parts")[0], 200)

    def test_query_token_is_not_accepted(self):
        """令牌不接受 query 参数（避免进入日志/浏览器历史）。"""
        status, _, _ = self.fixture.request(f"/api/jobs?token={TOKEN}")
        self.assertEqual(status, 401)
        status, _, _ = self.fixture.request(f"/api/jobs?access_token={TOKEN}")
        self.assertEqual(status, 401)

    def test_token_not_leaked_in_responses_or_logs(self):
        """令牌不得出现在任何响应体与启动日志中。"""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            status, body, _ = self.fixture.post_json("/api/build", {"desc": "泄漏检查"},
                                                    headers=AUTH)
            self.fixture.wait_status(body["id"], ("done",), headers=AUTH)
            self.fixture.get_json("/api/jobs", headers=AUTH)
            self.fixture.get_json("/api/jobs")
        output = buffer.getvalue()
        self.assertNotIn(TOKEN, output, "启动/运行日志泄露令牌")
        self.assertNotIn(TOKEN, str(body))
        self.assertNotIn(TOKEN, security.describe_policy(self.fixture.app.security).__str__())


class OriginAndCorsTest(unittest.TestCase):
    """Origin 防线与 CORS：allowlist 精确匹配，CORS 不作为鉴权。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture(allowed_origins=(ALLOWED,)).start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def setUp(self):
        self.fixture.store.clear()
        self.fixture.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success"})

    def test_same_origin_post_allowed(self):
        """与 Host 同源的 Origin 允许写操作。"""
        status, _, _ = self.fixture.post_json(
            "/api/build", {"desc": "塔"}, headers={"Origin": self.fixture.base})
        self.assertEqual(status, 200)

    def test_cross_origin_post_rejected_403(self):
        for origin in ("http://evil.example.com", "null", "http://127.0.0.1:9999"):
            with self.subTest(origin=origin):
                status, body, _ = self.fixture.post_json("/api/build", {"desc": "塔"},
                                                         headers={"Origin": origin})
                self.assertEqual(status, 403, origin)
                self.assertEqual(body["error"], "cross-origin request rejected")
                self.assertEqual(body["code"], "cross_origin")

    def test_allowlisted_origin_gets_cors_headers(self):
        """显式 allowlist 的来源可跨源写入，并回精确 ACAO 与暴露头。"""
        status, headers, _ = self.fixture.request(
            "/api/parts", headers={"Origin": ALLOWED})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), ALLOWED)
        self.assertIn("X-LEGOGOD-API-Version", headers.get("Access-Control-Expose-Headers", ""))
        self.assertEqual(headers.get("Vary"), "Origin")

    def test_non_allowlisted_origin_gets_no_cors_headers(self):
        """非 allowlist 来源的只读请求不下发 CORS 头（浏览器自然拦截读取）。"""
        status, headers, _ = self.fixture.request(
            "/api/parts", headers={"Origin": "http://other.example.com"})
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_cross_origin_artifact_read_gets_cors_headers(self):
        """产物路由也要回 ACAO：独立 Web 部署下页面会用 fetch 读取 /files 产物 JSON。

        回归点：2026-11-15 独立部署真实链路验收发现产物响应缺 CORS 头，浏览器拦截读取，
        导致详情页 3D/拼装步骤永远加载不出来（同源部署看不到这个问题）。
        """
        with open(os.path.join(self.fixture.artifacts_dir, "model_cors_r001_x.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"name": "cors"}')
        for path in ("/files/model_cors_r001_x.json", "/files/jobs_store.json"):
            with self.subTest(path=path):
                status, headers, _ = self.fixture.request(path, headers={"Origin": ALLOWED})
                self.assertEqual(headers.get("Access-Control-Allow-Origin"), ALLOWED, path)
        # 非 allowlist 来源不带 CORS 头（也不泄露任何内容给跨源脚本读取）
        status, headers, _ = self.fixture.request(
            "/files/model_cors_r001_x.json", headers={"Origin": "http://evil.example.com"})
        self.assertEqual(status, 200)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_preflight_allows_only_necessary_methods_and_headers(self):
        status, headers, _ = self.fixture.request("/api/build", method="OPTIONS",
                                                  headers={"Origin": ALLOWED})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Access-Control-Allow-Methods"),
                         "GET, POST, DELETE, OPTIONS")
        self.assertEqual(headers.get("Access-Control-Allow-Headers"),
                         "Content-Type, Authorization, X-Request-ID")
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), ALLOWED)

    def test_preflight_from_unknown_origin_rejected(self):
        status, _, _ = self.fixture.request("/api/build", method="OPTIONS",
                                            headers={"Origin": "http://evil.example.com"})
        self.assertEqual(status, 403)


class StartupGateTest(unittest.TestCase):
    """启动门槛：非回环必须有令牌；配置错误立即报错。"""

    def _config(self, **kwargs):
        return lego_server.AppConfig(**{"artifacts_dir": self.tmp,
                                        "viz_dir": self.tmp, **kwargs})

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="legogod-sec-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_non_loopback_without_token_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            lego_server.create_application(self._config(role="api", host="0.0.0.0", port=0))
        message = str(ctx.exception)
        self.assertIn("拒绝启动", message)
        self.assertIn("LEGOGOD_API_TOKEN", message)
        self.assertNotIn("api-token=", message)

    def test_non_loopback_with_token_starts(self):
        app = lego_server.create_application(
            self._config(role="api", host="0.0.0.0", port=0, api_token=TOKEN))
        try:
            self.assertTrue(app.security.auth_required)
        finally:
            app.shutdown()

    def test_loopback_without_token_starts(self):
        app = lego_server.create_application(self._config(role="api", host="127.0.0.1", port=0))
        try:
            self.assertFalse(app.security.auth_required)
        finally:
            app.shutdown()

    def test_wildcard_origin_rejected_at_parse(self):
        with self.assertRaises(SystemExit) as ctx:
            lego_server.parse_config(["api", "--allowed-origins", "*"])
        self.assertIn("*", str(ctx.exception))

    def test_invalid_origin_rejected_at_parse(self):
        for bad in ("127.0.0.1:8601", "http://evil.example.com/path",
                    "http://user:pw@evil.example.com", "ftp://x"):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    lego_server.parse_config(["api", "--allowed-origins", bad])

    def test_api_url_conflicts_reported(self):
        with self.assertRaises(SystemExit):
            lego_server.parse_config(["api", "--api-url", "http://127.0.0.1:8600"])
        with self.assertRaises(SystemExit):
            lego_server.parse_config(["--api-url", "http://127.0.0.1:8600"])


class SecurityPolicyUnitTest(unittest.TestCase):
    """策略纯函数：常量时间比较、Origin 规范化、无令牌时放行。"""

    def test_authorize_matrix(self):
        policy = security.SecurityPolicy(TOKEN)
        self.assertTrue(policy.authorize({"Authorization": f"Bearer {TOKEN}"}))
        self.assertFalse(policy.authorize({"Authorization": "Bearer nope"}))
        self.assertFalse(policy.authorize({}))
        self.assertFalse(policy.authorize({"Authorization": TOKEN}))
        self.assertTrue(security.SecurityPolicy().authorize({}))

    def test_origin_allowlist_exact_match_only(self):
        policy = security.SecurityPolicy(allowed_origins=(ALLOWED,))
        self.assertTrue(policy.origin_allowed(ALLOWED, "127.0.0.1:8600"))
        self.assertTrue(policy.origin_allowed("http://127.0.0.1:8600", "127.0.0.1:8600"))
        self.assertFalse(policy.origin_allowed("http://127.0.0.1:8602", "127.0.0.1:8600"))
        self.assertFalse(policy.origin_allowed("null", "127.0.0.1:8600"))
        self.assertTrue(policy.origin_allowed("", "127.0.0.1:8600"))

    def test_loopback_detection(self):
        for host in ("127.0.0.1", "127.0.1.5", "::1", "[::1]", "localhost"):
            self.assertTrue(security.is_loopback_host(host), host)
        for host in ("0.0.0.0", "192.168.0.2", "::", "example.com", ""):
            self.assertFalse(security.is_loopback_host(host), host)


if __name__ == "__main__":
    unittest.main()
