# ============================================================
# API 传输层：
# HTTP 方法、路由分发、有界请求体消费、响应与 CORS、静态与产物路由委托。
#
# 依赖边界：本模块只调用公共契约、安全策略、任务服务与产物服务；
# 不创建 worker、不直接读写任务字典、不调用生成主链。
#
# 连接语义：
#   - 合法长度 body 在 401/415/403 前有界消费 → 保持连接可用，避免残留 body 变成下一请求；
#   - 超大/非法 Content-Length/分块 body → 400/413 + Connection: close，绝不无界读取；
#   - 未匹配路由的 POST 也消费 body。
#
# 每个 /api 响应带 X-LEGOGOD-API-Version: 1 与 X-Request-ID；错误体附 requestId。
# ============================================================
import dataclasses
import json
import re
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api_contract as contract
from .api_contract import API_VERSION, API_VERSION_HEADER, REQUEST_ID_HEADER
from .artifact_service import DEFAULT_MIME, read_bytes, read_static
from .job_errors import JobServiceError
from .jsonutil import to_jsonable
from .parts_library import PARTS

MAX_BODY_BYTES = 64 * 1024  # POST 请求体上限：拒绝前可有界消费，超过则关闭连接（不无界读取）
SHELL_PATHS = ("/", "/index.html", "/history", "/parts")
SHELL_PREFIXES = ("/jobs/",)
RUNTIME_CONFIG_PATH = "/runtime-config.js"
POST_API_PATHS = ("/api/build", "/api/retry")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
JSON_CTYPE = "application/json; charset=utf-8"
TEXT_CTYPE = "text/plain; charset=utf-8"


@dataclasses.dataclass(frozen=True)
class WebBundle:
    """组合/静态部署时的 Web 资源：应用壳、静态资源目录、运行时配置脚本。"""

    index_path: str
    web_dir: str
    runtime_config_js: str


def build_runtime_config_js(api_base_url=""):
    """生成运行时配置脚本：只含 API Base URL，绝不含令牌或本机绝对路径。"""
    payload = json.dumps({"apiBaseUrl": str(api_base_url or "")}, ensure_ascii=False)
    return ("// 由 LEGOGOD 静态服务生成：只含 API Base URL，不含任何秘密。\n"
            f"window.LEGOGOD_CONFIG = {payload};\n")


class ApiHandler(BaseHTTPRequestHandler):
    """API/组合服务的请求处理器基类。

    依赖通过类属性注入（`dependencies()` 返回的字典），保证传输层不持有模块级全局状态：
    测试可以独立实例化 JobStore/JobService 并注入可控 runner。
    """

    protocol_version = "HTTP/1.1"
    SERVICE = None        # JobService（API/组合模式）
    SECURITY = None       # SecurityPolicy
    ARTIFACTS = None      # ArtifactService（API/组合模式）
    WEB = None            # WebBundle（组合/静态 Web 模式）
    ROLE = "api"

    def log_message(self, *args):  # noqa: D401 - 关闭默认逐请求日志，关键事件由各层打印
        pass

    # ---------- 请求上下文 ----------
    def _request_id(self):
        """请求标识：透传合法 X-Request-ID，否则生成；只用于关联故障，不含敏感内容。"""
        cached = getattr(self, "_rid", None)
        if cached:
            return cached
        raw = (self.headers.get("X-Request-ID") or "").strip() if self.headers else ""
        self._rid = raw if REQUEST_ID_PATTERN.match(raw) else uuid.uuid4().hex[:16]
        return self._rid

    def _origin(self):
        return (self.headers.get("Origin") or "").strip() if self.headers else ""

    def _host(self):
        return (self.headers.get("Host") or "").strip() if self.headers else ""

    # ---------- 响应写出 ----------
    def _send(self, code, body, ctype=DEFAULT_MIME, close=False, api=False, extra=None):
        """写响应；close=True 时显式 Connection: close 并关闭本请求后的连接。

        请求体无法安全消费时必须关闭连接：残留 body 会被当成下一个请求并触发 501。
        CORS 头对所有响应（含产物 /files、/views、/viz）下发：独立 Web 部署时页面会用
        fetch 读取产物 JSON，缺 ACAO 会被浏览器拦截读取（跨源 allowlist）。
        """
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if self.SECURITY:
            for name, value in self.SECURITY.cors_headers(self._origin(), self._host()).items():
                self.send_header(name, value)
        if api:
            self.send_header(API_VERSION_HEADER, str(API_VERSION))
            self.send_header(REQUEST_ID_HEADER, self._request_id())
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, close=False):
        """JSON 响应（带 API 版本与请求标识头）。"""
        body = json.dumps(to_jsonable(obj), ensure_ascii=False).encode("utf-8")
        self._send(code, body, JSON_CTYPE, close=close, api=True)

    def _error(self, code, message, machine_code=None, close=False):
        """错误响应：字符串 error 保持兼容，附加机器码与 requestId。"""
        self._json(contract.error_payload(
            message, machine_code or contract.error_code_for_status(code),
            self._request_id()), code, close=close)

    def _plain(self, code, message, close=False):
        self._send(code, message.encode("utf-8") if isinstance(message, str) else message,
                   TEXT_CTYPE, close=close)

    def _static_pair(self, pair):
        """产物/静态资源统一写出：解析失败一律 404，不泄露目录结构。"""
        if pair is None:
            self._plain(404, "not found")
            return
        body, ctype = pair
        self._send(200, body, ctype)

    # ---------- 路由 ----------
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path in SHELL_PATHS or path.startswith(SHELL_PREFIXES):
            self._serve_shell()
        elif path == RUNTIME_CONFIG_PATH:
            self._serve_runtime_config()
        elif path.startswith("/api/"):
            self._get_api(path)
        elif path.startswith("/views/"):
            self._static_pair(self.ARTIFACTS.read_views(path[len("/views/"):])
                              if self.ARTIFACTS else None)
        elif path.startswith("/viz/"):
            self._static_pair(self.ARTIFACTS.read_viz(path[len("/viz/"):])
                              if self.ARTIFACTS else None)
        elif path.startswith("/files/"):
            self._static_pair(self.ARTIFACTS.read_files(path[len("/files/"):])
                              if self.ARTIFACTS else None)
        elif path.startswith("/web/"):
            self._static_pair(read_static(self.WEB.web_dir, path[len("/web/"):])
                              if self.WEB else None)
        else:
            self._plain(404, "not found")

    def _get_api(self, path):
        """GET API 路由：任务详情、零件目录、历史列表、健康检查。

        没有任务服务的部署（独立 Web 静态服务）不提供任何 /api 路由：否则 API Base URL
        配错时前端会静默命中静态服务同源地址，把“连不上 API”伪装成本地空数据。
        """
        if self.SERVICE is None:
            self._error(404, "not found", contract.ERROR_NOT_FOUND)
            return
        if self._task_route_protected(path) and not self._authorized():
            return
        if path.startswith("/api/job/"):
            detail = self.SERVICE.get_job(path[len("/api/job/"):])
            if detail is None:
                self._error(404, "unknown job", contract.ERROR_UNKNOWN_JOB)
            else:
                self._json(detail)
            return
        if path == "/api/parts":
            # 零件目录唯一数据源：前端不再硬编码（曾导致斜坡砖缺色崩溃）
            self._json(contract.parts_payload(PARTS))
            return
        if path == "/api/jobs":
            query = urllib.parse.urlsplit(self.path).query
            params = urllib.parse.parse_qs(query)
            try:
                data = self.SERVICE.query_jobs(params)
            except ValueError as e:
                self._error(400, str(e), contract.ERROR_INVALID_PARAMS)
                return
            self._json(data)
            return
        if path == "/api/health":
            self._json(contract.health_payload(role=self.ROLE))
            return
        self._error(404, "not found", contract.ERROR_NOT_FOUND)

    def do_DELETE(self):
        path = urllib.parse.urlsplit(self.path).path
        if not path.startswith("/api/job/") or self.SERVICE is None:
            self._plain(404, "not found")
            return
        if not self._authorized():
            return
        result = self.SERVICE.cancel_job(path[len("/api/job/"):])
        if result is None:
            self._error(404, "unknown job", contract.ERROR_UNKNOWN_JOB)
        else:
            self._json(result)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path not in POST_API_PATHS or self.SERVICE is None:
            # 未匹配路由也要消费 body：否则残留 body 会让复用连接的下一请求错乱
            close = not self._drain_body()
            self._error(404, "not found", contract.ERROR_NOT_FOUND, close=close)
            return
        payload = self._prepare_post()
        if payload is None:
            return
        if path == "/api/build":
            self._post_build(payload)
            return
        self._post_retry(payload)

    def do_OPTIONS(self):
        """CORS 预检：只允许 allowlist 来源与必要的方法/请求头。

        产物路由（/files、/views、/viz）同样可能需要预检（页面 fetch 产物 JSON 会带
        X-Request-ID 头），因此对所有路径统一应答。
        """
        headers = (self.SECURITY.preflight_headers(self._origin(), self._host())
                   if self.SECURITY else None)
        if headers is None:
            self._plain(403, "origin not allowed")
            return
        self._send(200, b"", TEXT_CTYPE, extra=headers)

    # ---------- 任务端点 ----------
    def _post_build(self, payload):
        """POST /api/build：缺省 mode 仍是 fidelity（只为兼容既有调用方）。"""
        desc = payload.get("desc", "")
        mode = str(payload.get("mode", "fidelity"))
        try:
            self._json(self.SERVICE.create_job(desc, mode))
        except JobServiceError as e:
            self._error(e.status, e.message, e.code)

    def _post_retry(self, payload):
        """POST /api/retry：按原任务模式创建新任务，运行中拒绝。"""
        job_id = str(payload.get("jobId", "")).strip()
        try:
            self._json(self.SERVICE.retry_job(job_id))
        except JobServiceError as e:
            self._error(e.status, e.message, e.code)

    # ---------- Web 资源 ----------
    def _serve_shell(self):
        """前端应用壳：/、/history、/jobs/<id>、/parts 返回同一入口，路由由前端接管。"""
        if self.WEB is None:
            self._plain(404, "not found")
            return
        try:
            body = read_bytes(self.WEB.index_path)
        except OSError:
            self._plain(500, "web/index.html missing")
            return
        self._send(200, body, "text/html; charset=utf-8")

    def _serve_runtime_config(self):
        """运行时配置脚本：独立 Web 部署按 --api-url 生成，组合部署为空（同源）。"""
        if self.WEB is None:
            self._plain(404, "not found")
            return
        self._send(200, self.WEB.runtime_config_js.encode("utf-8"),
                   "text/javascript; charset=utf-8")

    # ---------- 请求体与鉴权 ----------
    def _task_route_protected(self, path):
        """受令牌保护的路由：任务读写与会话历史（健康检查/零件目录保持开放）。"""
        if self.SECURITY is None or not self.SECURITY.auth_required:
            return False
        return path.startswith("/api/job/") or path == "/api/jobs"

    def _authorized(self):
        """校验 Bearer 令牌；失败已写出 401 响应（GET/DELETE 无 body，连接保持可用）。"""
        if self.SECURITY is None or self.SECURITY.authorize(self.headers):
            return True
        self._error(401, "缺少或非法访问令牌", contract.ERROR_UNAUTHORIZED)
        return False

    def _drain_body(self):
        """有界消费请求体；返回 False 表示无法安全消费（调用方必须关闭连接，不得无界读取）。"""
        raw = self.headers.get("Content-Length")
        if (self.headers.get("Transfer-Encoding") or "").strip():
            return False
        if raw is None:
            return True
        try:
            length = int(raw)
        except (TypeError, ValueError):
            return False
        if not (0 <= length <= MAX_BODY_BYTES):
            return False
        try:
            return not length or len(self.rfile.read(length)) == length
        except OSError:
            return False

    def _reject_after_drain(self, code, message, machine_code):
        """拒绝前先有界消费 body（保持连接可用）；消费不了改为 400 并关闭连接。"""
        if self._drain_body():
            self._error(code, message, machine_code)
        else:
            self._error(400, "无法安全消费请求体", contract.ERROR_BODY_UNCONSUMABLE, close=True)
        return None

    def _prepare_post(self):
        """POST 前置校验：body 上限 → Bearer → Content-Type → Origin → JSON 解析。

        返回 None 表示响应已写出（调用方直接返回）；{} 表示 JSON 解析失败，交由端点字段
        校验统一 400；其余为解析后的 dict。
        """
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            self._error(400, "Content-Length 非法", contract.ERROR_BAD_CONTENT_LENGTH, close=True)
            return None
        if not (0 <= length <= MAX_BODY_BYTES):
            self._error(413, f"请求体超过 {MAX_BODY_BYTES // 1024}KB 上限",
                        contract.ERROR_BODY_TOO_LARGE, close=True)
            return None
        if not (self.SECURITY is None or self.SECURITY.authorize(self.headers)):
            # body 还没消费：先有界消费再回 401，否则残留 body 会被当成下一请求
            return self._reject_after_drain(401, "缺少或非法访问令牌",
                                            contract.ERROR_UNAUTHORIZED)
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._reject_after_drain(415, "Content-Type 必须是 application/json",
                                            contract.ERROR_CONTENT_TYPE)
        origin = self.headers.get("Origin")
        if origin:
            try:
                urllib.parse.urlsplit(origin)
            except ValueError:
                self._error(400, "bad Origin", contract.ERROR_BAD_ORIGIN, close=True)
                return None
            if not (self.SECURITY is None or self.SECURITY.origin_allowed(origin, self._host())):
                return self._reject_after_drain(403, "cross-origin request rejected",
                                                contract.ERROR_CROSS_ORIGIN)
        try:
            if not length:
                raise ValueError
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:  # noqa: BLE001 - 解析失败统一走端点字段校验（400）
            return {}
        return payload


def make_handler(*, service=None, security=None, artifacts=None, web=None, role="api"):
    """构造绑定到一次部署依赖的 Handler 类（组合根注入，不依赖模块级全局状态）。"""
    return type("LegogodHandler", (ApiHandler,), {
        "SERVICE": service, "SECURITY": security,
        "ARTIFACTS": artifacts, "WEB": web, "ROLE": role,
    })


def serve_forever(*, host, port, handler):
    """起线程化 HTTP 服务（阻塞运行）；返回 server 实例供调用方持有/关闭。"""
    httpd = ThreadingHTTPServer((host, int(port)), handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return httpd
