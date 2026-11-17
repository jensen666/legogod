# -*- coding: utf-8 -*-
"""双部署形态验收。

硬判据：
1) 临时让 Web 应用壳路径不存在，API-only 仍能启动并完成健康、零件、任务和产物接口；
2) 给静态进程一个不可写的 artifacts 配置，Web-only 仍能启动并提供页面，且本身没有任务存储；
3) 独立 Web 的 API Base URL 配错时显示真实连接错误，不静默请求静态服务同源 API；
4) 组合与独立部署对相同任务记录返回一致的状态码、字段集合与字段值；
5) 真实 CLI 进程（python -m legogod api / web --api-url）可分别启动并各自提供服务。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402
from legogod import server as lego_server  # noqa: E402


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _get(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read()


def _wait_http(url, timeout=30):
    """等 URL 可访问（返回首次状态码），超时抛 AssertionError。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return _get(url)[0]
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:  # noqa: BLE001 - 启动期连接被拒是预期的
            last = e
            time.sleep(0.2)
    raise AssertionError(f"{url} 在 {timeout}s 内不可访问：{last}")


class ApiOnlyDeploymentTest(unittest.TestCase):
    """API-only：不读取 Web 应用壳也能提供完整接口。"""

    @classmethod
    def setUpClass(cls):
        # 故意指向不存在的 Web 目录：API-only 启动不得依赖 Web 应用壳
        cls.missing_web = os.path.join(tempfile.mkdtemp(prefix="legogod-nodew-"), "absent")
        cls.fixture = ApiFixture(role="api", web_dir=cls.missing_web).start()
        cls.fixture.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success",
                                                  "name": desc})

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()
        import shutil
        shutil.rmtree(os.path.dirname(cls.missing_web), ignore_errors=True)

    def test_web_routes_absent(self):
        for path in ("/", "/index.html", "/history", "/jobs/abc", "/parts",
                     "/web/app.js", "/runtime-config.js"):
            with self.subTest(path=path):
                self.assertEqual(self.fixture.get(path)[0], 404, path)

    def test_api_endpoints_work(self):
        self.assertEqual(self.fixture.get_json("/api/health")[0], 200)
        self.assertIn("parts", self.fixture.get_json("/api/parts")[1])
        code, body, _ = self.fixture.post_json("/api/build", {"desc": "独立 API 任务"})
        self.assertEqual(code, 200)
        job = self.fixture.wait_status(body["id"], ("done",))
        self.assertEqual(job["result"]["name"], "独立 API 任务")
        self.assertIn("jobs", self.fixture.get_json("/api/jobs")[1])

    def test_artifact_routes_work(self):
        artifacts = self.fixture.artifacts_dir
        with open(os.path.join(artifacts, "model_api_r001_x.json"), "w", encoding="utf-8") as f:
            f.write('{"name": "api"}')
        views = os.path.join(artifacts, "views")
        os.makedirs(views, exist_ok=True)
        with open(os.path.join(views, "sheet.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        viz = self.fixture.viz_dir
        with open(os.path.join(viz, "lego_x.html"), "w", encoding="utf-8") as f:
            f.write("<html>3d</html>")
        self.assertEqual(self.fixture.get("/files/model_api_r001_x.json")[0], 200)
        self.assertEqual(self.fixture.get("/views/sheet.png")[0], 200)
        self.assertEqual(self.fixture.get("/viz/lego_x.html")[0], 200)


class WebOnlyDeploymentTest(unittest.TestCase):
    """Web-only：无任务存储、无 artifacts 依赖，只提供静态资源。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="legogod-webonly-")
        # artifacts/viz 指向不存在且不会被创建的路径：静态服务不得依赖它们可写
        self.artifacts = os.path.join(self.root, "no-artifacts")
        self.viz = os.path.join(self.root, "no-viz")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)

    def _start(self, api_base_url):
        fixture = ApiFixture(role="web", api_base_url=api_base_url,
                             artifacts_dir=self.artifacts, viz_dir=self.viz)
        return fixture.start()

    def test_serves_pages_without_artifacts_or_store(self):
        fixture = self._start("http://127.0.0.1:8600")
        try:
            self.assertIsNone(fixture.app.store, "Web-only 不得持有任务存储")
            self.assertIsNone(fixture.app.service)
            self.assertFalse(os.path.exists(self.artifacts), "Web-only 不得创建 artifacts 目录")
            code, headers, body = fixture.request("/")
            self.assertEqual(code, 200)
            self.assertIn("text/html", headers.get("Content-Type", ""))
            self.assertIn(b"LEGOGOD", body)
            self.assertEqual(fixture.get("/web/app.js")[0], 200)
            self.assertEqual(fixture.get("/web/api.js")[0], 200)
            self.assertEqual(fixture.get("/history")[0], 200)
        finally:
            fixture.stop()

    def test_api_paths_are_not_served(self):
        """独立 Web 不提供 /api：Base URL 配错时必须得到真实错误而不是本地空数据。"""
        fixture = self._start("http://127.0.0.1:8600")
        try:
            for path in ("/api/health", "/api/parts", "/api/jobs", "/api/job/x"):
                with self.subTest(path=path):
                    status, body, _ = fixture.get_json(path)
                    self.assertEqual(status, 404, path)
                    self.assertEqual(body["code"], "not_found")
            self.assertEqual(fixture.post_json("/api/build", {"desc": "x"})[0], 404)
            self.assertEqual(fixture.delete_json("/api/job/x")[0], 404)
            self.assertEqual(fixture.get("/files/model.json")[0], 404)
        finally:
            fixture.stop()

    def test_runtime_config_points_to_configured_api(self):
        fixture = self._start("http://127.0.0.1:8600/")
        try:
            code, headers, body = fixture.request("/runtime-config.js")
            self.assertEqual(code, 200)
            self.assertIn("javascript", headers.get("Content-Type", ""))
            text = body.decode("utf-8")
            self.assertIn('"apiBaseUrl": "http://127.0.0.1:8600"', text)
            self.assertNotIn("token", text.lower())
        finally:
            fixture.stop()

    def test_missing_shell_refuses_to_start(self):
        config = lego_server.AppConfig(role="web", host="127.0.0.1", port=0,
                                       api_base_url="http://127.0.0.1:8600",
                                       web_dir=os.path.join(self.root, "no-web"),
                                       artifacts_dir=self.artifacts, viz_dir=self.viz)
        with self.assertRaises(SystemExit) as ctx:
            lego_server.create_application(config)
        self.assertIn("index.html", str(ctx.exception))


class ComboVsApiContractTest(unittest.TestCase):
    """组合与独立部署：相同任务记录返回一致的状态码、字段集合与字段值。"""

    @classmethod
    def setUpClass(cls):
        cls.combo = ApiFixture(role="combo").start()
        cls.api = ApiFixture(role="api").start()
        cls._seed(cls.combo)
        cls._seed(cls.api)

    @classmethod
    def tearDownClass(cls):
        cls.combo.stop()
        cls.api.stop()

    @staticmethod
    def _seed(fixture):
        fixture.add_job("c1", desc="石桥", mode="fast", startedAt=10.0,
                        result={"ok": True, "name": "石桥", "pieces": 8,
                                "grid": {"w": 2, "d": 2}, "layers": 1,
                                "colors": {"红色": 8}, "outcome": "fast_success"})
        fixture.add_job("c2", desc="主战坦克", startedAt=11.0,
                        result={"ok": True, "review_failed": True,
                                "run_record": {"desc": "主战坦克"}})
        fixture.add_job("c3", status="error", desc=None, startedAt=12.0,
                        result={"ok": False, "error": "阶段 revise 请求超限",
                                "run_record": {"mode": "fast",
                                               "desc": "帆船"}})
        fixture.add_job("c4", status="running", desc="进行中", startedAt=13.0,
                        result=None, live="生成中",
                        logs=[{"kind": "phase", "text": "plan", "ts": 1.5,
                               "phase": "plan"}],
                        stage={"current": "plan", "seen": ["plan"], "revise": 0})
        for name in ("model_eq_r001_x.json", "jobs_store.json", "run_abcd.json"):
            with open(os.path.join(fixture.artifacts_dir, name), "w", encoding="utf-8") as f:
                f.write("{}")
        os.makedirs(os.path.join(fixture.artifacts_dir, "views"), exist_ok=True)
        with open(os.path.join(fixture.artifacts_dir, "views", "eq.png"), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        with open(os.path.join(fixture.viz_dir, "lego_eq.html"), "w", encoding="utf-8") as f:
            f.write("<html>eq</html>")

    def _pair(self, path):
        combo_status, combo_body, combo_headers = self.combo.get_json(path)
        api_status, api_body, api_headers = self.api.get_json(path)
        return ((combo_status, combo_body, combo_headers),
                (api_status, api_body, api_headers))

    def test_health_equal_except_role(self):
        (combo_status, combo_body, _), (api_status, api_body, _) = self._pair("/api/health")
        self.assertEqual(combo_status, api_status)
        combo_body = dict(combo_body)
        api_body = dict(api_body)
        combo_body.pop("role", None)
        api_body.pop("role", None)
        self.assertEqual(combo_body, api_body)

    def test_parts_equal(self):
        (combo_status, combo_body, _), (api_status, api_body, _) = self._pair("/api/parts")
        self.assertEqual((combo_status, combo_body), (api_status, api_body))

    def test_jobs_list_and_page_equal(self):
        for path in ("/api/jobs", "/api/jobs?page=1&pageSize=2",
                     "/api/jobs?q=" + urllib.request.quote("石桥"),
                     "/api/jobs?page=1&pageSize=20&outcome=fidelity_degraded"):
            with self.subTest(path=path):
                (c_status, c_body, _), (a_status, a_body, _) = self._pair(path)
                self.assertEqual(c_status, a_status)
                self.assertEqual(c_body, a_body)

    def test_job_detail_equal(self):
        for job_id in ("c1", "c2", "c3", "c4"):
            with self.subTest(job_id=job_id):
                (c_status, c_body, _), (a_status, a_body, _) = self._pair(f"/api/job/{job_id}")
                self.assertEqual(c_status, a_status)
                self.assertEqual(c_body, a_body)
        (c_status, c_body, _), (a_status, a_body, _) = self._pair("/api/job/missing")
        self.assertEqual(c_status, a_status)
        self.assertEqual(c_body["error"], a_body["error"])
        self.assertEqual(c_body["code"], a_body["code"])

    def test_artifact_security_equal(self):
        for path in ("/files/model_eq_r001_x.json", "/files/jobs_store.json",
                     "/files/run_abcd.json", "/files/../jobs_store.json",
                     "/views/eq.png", "/views/missing.png",
                     "/viz/lego_eq.html", "/viz/../secret"):
            with self.subTest(path=path):
                combo_status, _, combo_body = self.combo.request(path)
                api_status, _, api_body = self.api.request(path)
                self.assertEqual(combo_status, api_status, path)
                self.assertEqual(combo_body, api_body, path)

    def test_error_status_codes_equal(self):
        for method, path, payload in (
                ("GET", "/api/jobs?page=0", None),
                ("POST", "/api/build", {"desc": ""}),
                ("POST", "/api/build", {"desc": "x", "mode": "bogus"}),
                ("POST", "/api/retry", {"jobId": "nope"}),
                ("DELETE", "/api/job/nope", None)):
            with self.subTest(path=path, method=method):
                combo_status, combo_body, _ = self._as_json(self.combo, method, path, payload)
                api_status, api_body, _ = self._as_json(self.api, method, path, payload)
                self.assertEqual(combo_status, api_status)
                self.assertEqual(combo_body.get("error"), api_body.get("error"))
                self.assertEqual(combo_body.get("code"), api_body.get("code"))
                self.assertEqual(set(combo_body) - {"requestId"},
                                 set(api_body) - {"requestId"})

    @staticmethod
    def _as_json(fixture, method, path, payload):
        status, headers, raw = fixture.request(path, method=method, payload=payload)
        return status, json.loads(raw.decode("utf-8")), headers


class RealProcessDeployTest(unittest.TestCase):
    """真实 CLI 进程：组合/独立 API/独立 Web 三种启动方式。"""

    def setUp(self):
        self.processes = []

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

    def _spawn(self, args):
        process = subprocess.Popen([sys.executable, "-m", "legogod", *args], cwd=ROOT,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(process)
        return process

    def test_api_and_web_processes_run_independently(self):
        api_port = _free_port()
        web_port = _free_port()
        api_url = f"http://127.0.0.1:{api_port}"
        self._spawn(["api", "--host", "127.0.0.1", "--port", str(api_port)])
        self.assertEqual(_wait_http(api_url + "/api/health"), 200)
        self._spawn(["web", "--host", "127.0.0.1", "--port", str(web_port),
                     "--api-url", api_url])
        self.assertEqual(_wait_http(f"http://127.0.0.1:{web_port}/"), 200)
        # 静态服务：页面与运行时配置指向独立 API，且不提供 /api
        status, body = _get(f"http://127.0.0.1:{web_port}/runtime-config.js")
        self.assertEqual(status, 200)
        self.assertIn(api_url.encode(), body)
        try:
            _get(f"http://127.0.0.1:{web_port}/api/health")
            self.fail("独立 Web 不应提供 /api/health")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)
        # API 服务：不提供页面，只提供接口
        self.assertEqual(_get(api_url + "/api/parts")[0], 200)
        try:
            _get(api_url + "/")
            self.fail("独立 API 不应提供 Web 应用壳")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_combo_command_keeps_legacy_port_form(self):
        port = _free_port()
        self._spawn([str(port)])
        base = f"http://127.0.0.1:{port}"
        self.assertEqual(_wait_http(base + "/api/health"), 200)
        self.assertIn(b"LEGOGOD", _get(base + "/")[1])


class WebOnlyImportIsolationTest(unittest.TestCase):
    """Web-only 静态进程不得加载生成编排模块（2026-11-15 复核）。

    回归点：`server.py` 曾顶层导入 job_service、`api_server` 又经 job_service 间接导入
    fallback，导致 `python -m legogod web` 即使没有任务存储也会加载 fallback/workflow。
    """

    def test_importing_server_does_not_load_generation_chain(self):
        probe = ("import sys, legogod.server; bad=[m for m in "
                 "('legogod.fallback','legogod.workflow','legogod.tiler','legogod.llm') "
                 "if m in sys.modules]; print('loaded:', bad); "
                 "raise SystemExit(0 if not bad else 1)")
        proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_api_server_module_does_not_load_generation_chain(self):
        probe = ("import sys, legogod.api_server; bad=[m for m in "
                 "('legogod.fallback','legogod.workflow') if m in sys.modules]; "
                 "print('loaded:', bad); raise SystemExit(0 if not bad else 1)")
        proc = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class ConfigParsingTest(unittest.TestCase):
    """启动参数与配置优先级。"""

    def test_legacy_forms_stay_combo(self):
        self.assertEqual(lego_server.parse_config([]).role, "combo")
        self.assertEqual(lego_server.parse_config([]).port, 8600)
        self.assertEqual(lego_server.parse_config(["8600"]).role, "combo")
        self.assertEqual(lego_server.parse_config(["8600"]).port, 8600)
        self.assertEqual(lego_server.parse_config(["web", "8600"]).role, "combo")
        self.assertEqual(lego_server.parse_config(["web"]).role, "combo")

    def test_api_role_and_web_only_role(self):
        api = lego_server.parse_config(["api", "--port", "8600", "--host", "127.0.0.1"])
        self.assertEqual((api.role, api.port, api.host), ("api", 8600, "127.0.0.1"))
        web = lego_server.parse_config(["web", "--port", "8601",
                                        "--api-url", "http://127.0.0.1:8600/"])
        self.assertEqual((web.role, web.port, web.api_base_url),
                         ("web", 8601, "http://127.0.0.1:8600"))

    def test_token_and_origins_from_env_with_cli_precedence(self):
        env_backup = {key: os.environ.get(key) for key in
                      ("LEGOGOD_API_TOKEN", "LEGOGOD_ALLOWED_ORIGINS")}
        try:
            os.environ["LEGOGOD_API_TOKEN"] = "env-token"
            os.environ["LEGOGOD_ALLOWED_ORIGINS"] = "http://127.0.0.1:8601"
            config = lego_server.parse_config(["api"])
            self.assertEqual(config.api_token, "env-token")
            self.assertEqual(config.allowed_origins, ("http://127.0.0.1:8601",))
            config = lego_server.parse_config(
                ["api", "--api-token", "cli-token",
                 "--allowed-origins", "http://127.0.0.1:8602"])
            self.assertEqual(config.api_token, "cli-token")
            self.assertEqual(config.allowed_origins, ("http://127.0.0.1:8602",))
        finally:
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_invalid_ports_rejected(self):
        for argv in (["api", "--port", "0"], ["api", "--port", "70000"],
                     ["api", "--port", "8600", "8601"], ["abc"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    lego_server.parse_config(argv)

    def test_invalid_api_url_rejected(self):
        for url in ("127.0.0.1:8600", "ftp://x", "http://user:pw@host:1",
                    "http://127.0.0.1:8600?x=1"):
            with self.subTest(url=url):
                with self.assertRaises(SystemExit):
                    lego_server.parse_config(["web", "--api-url", url])

    def test_combo_ignores_static_only_env(self):
        """组合部署永远同源：LEGOGOD_API_BASE_URL 只服务 web 子命令的独立静态模式。"""
        backup = os.environ.get("LEGOGOD_API_BASE_URL")
        try:
            os.environ["LEGOGOD_API_BASE_URL"] = "http://127.0.0.1:9999"
            self.assertEqual(lego_server.parse_config([]).api_base_url, "")
            self.assertEqual(lego_server.parse_config(["8600"]).api_base_url, "")
            # web 子命令 + 该变量 → 独立 Web 静态模式（CLI 显式 --api-url 优先）
            legacy = lego_server.parse_config(["web", "8600"])
            self.assertEqual(legacy.role, "web")
            self.assertEqual(legacy.api_base_url, "http://127.0.0.1:9999")
            explicit = lego_server.parse_config(["web", "--api-url", "http://127.0.0.1:8601"])
            self.assertEqual(explicit.api_base_url, "http://127.0.0.1:8601")
        finally:
            if backup is None:
                os.environ.pop("LEGOGOD_API_BASE_URL", None)
            else:
                os.environ["LEGOGOD_API_BASE_URL"] = backup


if __name__ == "__main__":
    unittest.main()
