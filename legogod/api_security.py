# ============================================================
# 访问安全：
# Bearer 令牌校验、Origin/CORS allowlist、非回环监听启动门槛。
#
# 边界说明：
#   - CORS 不是鉴权：只决定浏览器能不能读响应；Bearer 才是 API 凭据。
#   - 令牌使用常量时间比较，不接受 query token，不进日志、不进 requestId。
#   - 默认监听 127.0.0.1；非回环地址必须显式配置令牌，否则拒绝启动。
# ============================================================
import hmac
import ipaddress
import urllib.parse

from .api_contract import API_VERSION_HEADER, REQUEST_ID_HEADER

LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost"})
ORIGIN_SCHEMES = ("http", "https")
PREFLIGHT_METHODS = "GET, POST, DELETE, OPTIONS"
PREFLIGHT_HEADERS = "Content-Type, Authorization, X-Request-ID"


def is_loopback_host(host):
    """判断监听地址是否回环：127.0.0.0/8、::1、localhost。无法解析的一律按非回环处理。"""
    raw = str(host or "").strip().lower()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if raw in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(raw).is_loopback
    except ValueError:
        return False


def normalize_origin(value):
    """规范化一个精确 Origin：只允许 http(s)://host[:port]，不接受路径/查询/凭据/通配。

    非法值抛 ValueError，由启动解析统一转成明确的启动错误（不静默回退）。
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Origin 不能为空")
    if raw == "*":
        raise ValueError("不接受通配 Origin（*），必须显式列出精确来源")
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme.lower() not in ORIGIN_SCHEMES:
        raise ValueError(f"Origin 必须是 http/https：{raw}")
    if not parts.netloc:
        raise ValueError(f"Origin 缺少主机：{raw}")
    if "@" in parts.netloc:
        raise ValueError(f"Origin 不得包含用户凭据：{raw}")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"Origin 只能是 scheme://host[:port]：{raw}")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def parse_allowed_origins(raw):
    """解析 Origin allowlist：逗号分隔字符串或序列，返回规范化元组；拒绝 `*`。"""
    if not raw:
        return ()
    items = raw if isinstance(raw, (list, tuple)) else str(raw).split(",")
    origins = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        origins.append(normalize_origin(text))
    return tuple(origins)


def parse_bearer(headers):
    """从 Authorization 头取 Bearer 值；格式不合规返回 None（不接受 query token）。"""
    raw = (headers.get("Authorization") or "").strip() if headers else ""
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[len("bearer "):].strip()
    return token or None


class SecurityPolicy:
    """一次部署的访问策略：令牌 + 精确 Origin allowlist。

    空令牌表示不要求鉴权（仅限回环监听，启动门槛由 assert_bindable 保证）。
    """

    def __init__(self, token="", allowed_origins=()):
        self.token = str(token or "").strip()
        self.allowed_origins = parse_allowed_origins(allowed_origins)

    # ---------- 启动门槛 ----------
    def assert_bindable(self, host):
        """非回环监听且没有令牌时拒绝启动，打印明确原因。"""
        if self.token or is_loopback_host(host):
            return
        raise SystemExit(
            f"[legogod] 拒绝启动：监听地址 {host} 不是回环地址，但未配置 API 令牌。\n"
            f"  原因：非回环监听会把生成接口暴露到局域网/公网，任何人都能消耗模型额度。\n"
            f"  处理：设置 LEGOGOD_API_TOKEN 或传给 --api-token（不要写进仓库/静态文件）；\n"
            f"        公网部署还应由 HTTPS 反向代理终止 TLS（本服务不伪装成公网安全服务器）。")

    # ---------- 鉴权 ----------
    @property
    def auth_required(self):
        return bool(self.token)

    def authorize(self, headers):
        """Bearer 校验：未配置令牌时放行；配置后必须精确匹配（常量时间比较）。"""
        if not self.token:
            return True
        given = parse_bearer(headers)
        if not given:
            return False
        return hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8"))

    # ---------- Origin / CORS ----------
    def origin_allowed(self, origin, host_header):
        """Origin 是否被允许：空 Origin 放行；allowlist 精确命中或与 Host 同源才放行。"""
        text = str(origin or "").strip()
        if not text:
            return True
        try:
            normalized = normalize_origin(text)
        except ValueError:
            return False
        if normalized in self.allowed_origins:
            return True
        try:
            same_origin = urllib.parse.urlsplit(text).netloc.lower()
        except ValueError:
            return False
        return bool(same_origin) and same_origin == str(host_header or "").strip().lower()

    def cors_headers(self, origin, host_header):
        """允许的来源才回 ACAO；不允许时不下发任何 CORS 头（浏览器自然拦截读取）。"""
        text = str(origin or "").strip()
        if not text or not self.origin_allowed(text, host_header):
            return {}
        return {"Access-Control-Allow-Origin": text,
                "Vary": "Origin",
                "Access-Control-Expose-Headers": f"{API_VERSION_HEADER}, {REQUEST_ID_HEADER}"}

    def preflight_headers(self, origin, host_header):
        """预检响应里的方法/请求头白名单；来源不被允许时返回 None（传输层回 403）。

        ACAO/Vary 由传输层对所有响应统一下发（含产物路由），这里不重复添加，
        否则响应会出现两个 Access-Control-Allow-Origin，浏览器会直接拒绝。
        """
        basics = {"Access-Control-Allow-Methods": PREFLIGHT_METHODS,
                  "Access-Control-Allow-Headers": PREFLIGHT_HEADERS,
                  "Access-Control-Max-Age": "600"}
        text = str(origin or "").strip()
        if not text:
            return basics
        if not self.origin_allowed(text, host_header):
            return None
        return basics


def describe_policy(policy):
    """启动日志用的脱敏描述：只说明是否鉴权与 allowlist 数量，绝不打印令牌。"""
    return {"auth": "bearer" if policy.auth_required else "none",
            "allowedOrigins": len(policy.allowed_origins)}
