# ============================================================
# 组合根与统一服务入口。
#
# 这里只做装配：创建任务存储与服务、安全策略、产物服务、HTTP Handler，并按部署形态
# 决定启动哪些部分；业务语义在 job_service / api_contract / api_server 中，不回到本文件。
#
# 用法（在项目根目录执行）：
#   python -m legogod                        # 组合部署：Web 页面 + API，默认 127.0.0.1:8600
#   python -m legogod 8600                   # 组合部署，指定端口（旧用法保持可用）
#   python -m legogod web 8600               # 组合部署（同上）
#   python -m legogod api --host 127.0.0.1 --port 8600
#                                            # 独立 API：不读取 Web 应用壳，完整任务/零件/产物接口
#   python -m legogod web --host 127.0.0.1 --port 8601 --api-url http://127.0.0.1:8600
#                                            # 独立 Web 静态服务：不恢复任务、不启动 worker、
#                                            # 不要求 artifacts 可写，运行时配置指向真实 API
#
# 配置优先级：CLI 参数 > 环境变量（LEGOGOD_API_TOKEN / LEGOGOD_ALLOWED_ORIGINS /
# LEGOGOD_API_BASE_URL）> 缺省值。示例配置只写变量名，真实令牌不进文档/静态 JS/仓库。
# ============================================================
import argparse
import dataclasses
import os
import sys
import urllib.parse

from .api_security import SecurityPolicy, describe_policy, is_loopback_host, parse_allowed_origins
from .api_server import WebBundle, build_runtime_config_js, make_handler
from .artifact_service import ArtifactService
from .paths import ARTIFACTS_DIR, VIZ_DIR, WEB_DIR

ROLE_COMBO = "combo"   # 一个进程同时提供 Web 静态与 API（现有用户不受影响）
ROLE_API = "api"       # 只提供 API（无 Web 应用壳依赖）
ROLE_WEB = "web"       # 只提供 Web 静态资源（不持有任务状态）
ROLES = (ROLE_COMBO, ROLE_API, ROLE_WEB)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8600
ENV_API_TOKEN = "LEGOGOD_API_TOKEN"
ENV_ALLOWED_ORIGINS = "LEGOGOD_ALLOWED_ORIGINS"
ENV_API_BASE_URL = "LEGOGOD_API_BASE_URL"


@dataclasses.dataclass
class AppConfig:
    """一次启动的完整配置（不含秘密实体：令牌只在这里作为运行期值存在，不写盘）。"""

    role: str = ROLE_COMBO
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    api_base_url: str = ""
    api_token: str = ""
    allowed_origins: tuple = ()
    artifacts_dir: str = ARTIFACTS_DIR
    viz_dir: str = VIZ_DIR
    web_dir: str = WEB_DIR
    store_path: str = ""

    @property
    def needs_api(self):
        return self.role in (ROLE_API, ROLE_COMBO)

    @property
    def needs_web(self):
        return self.role in (ROLE_COMBO, ROLE_WEB)


def ensure_writable_dir(path, label):
    """启动自检：产物目录必须可写，否则点击“开始拼装”注定失败（fail-fast 而非事后卡死）。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".write_probe_{os.getpid()}")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        raise SystemExit(
            f"[legogod] {label}目录不可写：{path}\n  原因：{e}\n"
            f"  请用有写权限的账户/方式启动服务，或修复该目录权限后重试。\n"
            f"  （服务需要写入设计/方案/拼装步骤/3D 产物，目录不可写时“开始拼装”会失败）")


class Application:
    """装配完成的一次部署：持有 store/service/security/artifacts/handler 与 httpd。"""

    def __init__(self, config):
        self.config = config
        self.security = SecurityPolicy(config.api_token, config.allowed_origins)
        self.store = None
        self.service = None
        self.artifacts = None
        self.web = None
        self.handler = None
        self.httpd = None
        self._serving = False

    @property
    def base_url(self):
        return f"http://{self.config.host}:{self.httpd.server_address[1]}"

    def announce(self):
        """启动日志：说明部署形态、监听地址、历史条数与安全策略（绝不打印令牌）。"""
        address = self.base_url
        if self.config.role == ROLE_API:
            head = (f"乐高 Agent API 服务: {address}（独立部署，不依赖 Web 应用壳；"
                    f"历史任务 {len(self.store)} 个）")
        elif self.config.role == ROLE_WEB:
            target = self.config.api_base_url or "同源（同源反向代理）"
            head = f"乐高 Agent 静态前端: {address} -> API {target}（不持有任务状态）"
        else:
            head = f"乐高 Agent 服务: {address}（Web + API 组合部署，历史任务 {len(self.store)} 个）"
        policy = describe_policy(self.security)
        print(head, flush=True)
        print(f"[legogod] 认证: {policy['auth']}；Origin allowlist: "
              f"{policy['allowedOrigins']} 项；监听: {'回环' if is_loopback_host(self.config.host) else '非回环'}",
              flush=True)

    def serve_forever(self):
        """阻塞运行直到进程退出。"""
        self._serving = True
        try:
            self.httpd.serve_forever()
        except OSError:
            pass   # 端口已被 shutdown 关闭：正常退出路径
        finally:
            self._serving = False

    def shutdown(self):
        """停止 HTTP 服务并释放监听端口（测试与优雅退出用）。

        注意：ThreadingHTTPServer.shutdown() 在 serve_forever 未运行时不会返回，
        因此只有确认正在服务时才调用它，否则直接关闭监听套接字。
        """
        httpd = self.httpd
        if httpd is None:
            return
        if getattr(self, "_serving", False):
            try:
                httpd.shutdown()
            except Exception:  # noqa: BLE001 - 退出路径不因关闭异常再抛
                pass
        try:
            httpd.server_close()
        except Exception:  # noqa: BLE001
            pass


def create_application(config):
    """组合根：按配置装配 store/service/安全策略/Handler 并绑定监听端口。

    - 只有 API/组合模式才执行 artifacts 与 viz 可写自检、恢复任务历史；
    - 只有 Web/组合模式才读取 Web 应用壳和静态资源；
    - runner 显式注入任务服务（生产始终是真实 run_with_fallback，测试可注入可控实现）。

    生成主链（fallback/workflow/tiler）与任务服务只在 `needs_api` 分支内延迟导入：
    Web-only 静态进程不需要它们，导入它们会白白加载整套编排模块（2026-11-15 复核）。
    """
    if config.role not in ROLES:
        raise SystemExit(f"[legogod] 未知部署形态：{config.role}")
    app = Application(config)
    app.security.assert_bindable(config.host)
    if config.needs_api:
        from .fallback import run_with_fallback  # 延迟导入：Web-only 模式不加载生成主链
        from .job_service import JobService
        from .job_store import JobStore
        ensure_writable_dir(config.artifacts_dir, "运行产物")
        ensure_writable_dir(config.viz_dir, "3D 可视化")
        store = JobStore(config.artifacts_dir, store_path=config.store_path or None)
        restored = store.load()
        app.store = store
        app.service = JobService(store, runner=run_with_fallback,
                                 artifacts_dir=config.artifacts_dir)
        app.artifacts = ArtifactService(config.artifacts_dir, config.viz_dir)
        if restored:
            print(f"[legogod] 已恢复历史任务 {restored} 个（遗留 running 标记为 interrupted）",
                  flush=True)
    if config.needs_web:
        index_path = os.path.join(config.web_dir, "index.html")
        if not os.path.isfile(index_path):
            raise SystemExit(f"[legogod] 拒绝启动：找不到 Web 应用壳 {index_path}\n"
                             f"  独立 API 部署请用：python -m legogod api --port <端口>")
        # 组合部署永远同源；只有独立 Web 静态服务才注入真实 API Base URL。
        api_base_url = "" if config.role == ROLE_COMBO else normalize_api_base_url(
            config.api_base_url)
        app.web = WebBundle(index_path=index_path, web_dir=config.web_dir,
                            runtime_config_js=build_runtime_config_js(api_base_url))
    app.handler = make_handler(service=app.service, security=app.security,
                               artifacts=app.artifacts, web=app.web, role=config.role)
    from http.server import ThreadingHTTPServer
    try:
        app.httpd = ThreadingHTTPServer((config.host, config.port), app.handler)
    except OSError as e:
        raise SystemExit(f"[legogod] 无法监听 {config.host}:{config.port}：{e}")
    return app


# ---------- 命令行解析 ----------
def _parser(prog="python -m legogod"):
    """命令行参数：位置端口保持旧用法，其余为新增部署参数。"""
    parser = argparse.ArgumentParser(
        prog=prog, add_help=True,
        description="LEGOGOD 服务入口：组合部署（默认）/ 独立 API / 独立 Web 静态服务")
    parser.add_argument("port", nargs="?", default=None, help="端口（兼容 python -m legogod 8600）")
    parser.add_argument("--host", default=None, help=f"监听地址，缺省 {DEFAULT_HOST}")
    parser.add_argument("--port", dest="port_option", default=None, type=int,
                        help=f"监听端口，缺省 {DEFAULT_PORT}")
    parser.add_argument("--api-url", default=None,
                        help="独立 Web 静态服务要指向的 API Base URL（web 模式）")
    parser.add_argument("--api-token", default=None,
                        help=f"API Bearer 令牌；也可用环境变量 {ENV_API_TOKEN}")
    parser.add_argument("--allowed-origins", default=None,
                        help=f"逗号分隔的精确 Origin allowlist；也可用 {ENV_ALLOWED_ORIGINS}")
    return parser


def _env(name):
    return os.environ.get(name, "")


def _resolve_port(args):
    """端口优先级：--port > 位置参数 > 缺省 8600；冲突或越界立即报错。"""
    option = args.port_option
    positional = None
    if args.port not in (None, ""):
        try:
            positional = int(str(args.port).strip())
        except ValueError:
            raise SystemExit(f"[legogod] 端口必须是整数：{args.port}")
    if option is not None and positional is not None and option != positional:
        raise SystemExit(f"[legogod] 端口参数冲突：位置参数 {positional} 与 --port {option} 不一致")
    port = option if option is not None else (positional if positional is not None else DEFAULT_PORT)
    if not 1 <= int(port) <= 65535:
        raise SystemExit(f"[legogod] 端口必须在 1..65535：{port}")
    return int(port)


def normalize_api_base_url(raw):
    """校验并规范化 API Base URL：只接受 http(s)://host[:port][/prefix]，不得含凭据/查询。"""
    text = str(raw or "").strip()
    if not text:
        return ""
    parts = urllib.parse.urlsplit(text)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise SystemExit(f"[legogod] 非法 --api-url：{text}（必须形如 http://127.0.0.1:8600）")
    if "@" in parts.netloc:
        raise SystemExit(f"[legogod] --api-url 不得包含用户凭据：{text}")
    if parts.query or parts.fragment:
        raise SystemExit(f"[legogod] --api-url 不得包含查询串或片段：{text}")
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def _split_role(argv):
    """识别 web / api 子命令前缀；其余（端口或参数）交给 argparse。"""
    if argv and argv[0] in ("web", "api"):
        return (ROLE_WEB if argv[0] == "web" else ROLE_API), list(argv[1:])
    return ROLE_COMBO, list(argv)


def parse_config(argv=None):
    """把命令行 + 环境变量解析成 AppConfig；非法组合立即 SystemExit（不静默回退）。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    role_hint, rest = _split_role(argv)
    args = _parser().parse_args(rest)
    port = _resolve_port(args)
    host = (args.host if args.host is not None else _env("LEGOGOD_HOST")).strip() or DEFAULT_HOST
    token = args.api_token if args.api_token is not None else _env(ENV_API_TOKEN)
    origins_raw = (args.allowed_origins if args.allowed_origins is not None
                   else _env(ENV_ALLOWED_ORIGINS))
    try:
        origins = parse_allowed_origins(origins_raw)
    except ValueError as e:
        raise SystemExit(f"[legogod] Origin allowlist 配置错误：{e}")
    # --api-url 只属于独立 Web 静态服务；显式传入却不在 web 模式时立即报错。
    if args.api_url is not None and role_hint != ROLE_WEB:
        raise SystemExit("[legogod] 参数冲突：--api-url 只能用于 web 子命令（独立 Web 静态服务）")
    if role_hint == ROLE_API and args.api_url is not None:
        raise SystemExit("[legogod] 参数冲突：api 模式不接受 --api-url")
    api_base_url = normalize_api_base_url(
        args.api_url if args.api_url is not None else _env(ENV_API_BASE_URL))
    if role_hint == ROLE_COMBO and not args.api_url:
        api_base_url = ""   # 组合部署永远同源，忽略仅供静态服务使用的环境变量
    # web 不带 --api-url 时保持组合兼容行为（旧命令 python -m legogod web 8600 仍可用）
    role = ROLE_COMBO if (role_hint == ROLE_WEB and not api_base_url) else role_hint
    if role == ROLE_API:
        api_base_url = ""
    return AppConfig(role=role, host=host, port=port, api_base_url=api_base_url,
                     api_token=token, allowed_origins=origins)


def main(argv=None):
    """启动服务：组合部署 / 独立 API / 独立 Web 静态服务，阻塞运行直到进程退出。"""
    config = parse_config(argv)
    app = create_application(config)
    app.announce()
    try:
        app.serve_forever()
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
