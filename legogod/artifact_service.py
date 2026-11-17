# ============================================================
# 产物文件服务：
# /files、/views、/viz 的白名单、路径规范化、MIME 判定与读取。
#
# 安全红线：
#   1) /files 只放行白名单扩展名，拒绝 jobs_store、run_*.json、隐藏文件与路径穿越；
#   2) /views 只放行真实存在的 PNG 文件名；/viz 继续限制在指定的 3D 产物目录；
#   3) 只返回相对产物名，绝不把本机绝对路径送给调用方。
# 本模块不暴露 jobs_store、不调用 LLM、不知道 HTTP 状态码。
# ============================================================
import os
import urllib.parse

# /files/<name> 白名单：只暴露拼装产物，不暴露任务历史与运行记录
FILES_EXT_WHITELIST = frozenset({".json", ".md", ".html", ".png"})
FILES_NAME_BLOCKLIST = ("jobs_store", "run_")

MIME = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".md": "text/markdown; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".png": "image/png"}
DEFAULT_MIME = "application/octet-stream"


def is_blocked_name(name):
    """黑名单判定：大小写与 Windows 文件名归一化后比较。

    2026-11-15 复核发现：Windows 文件系统不区分大小写，原实现用
    ``name.startswith(("jobs_store", "run_"))`` 判断，请求 ``/files/JOBS_STORE.json``
    会被当作合法产物名、再经 os.path.join 命中同一个 ``jobs_store.json``，从而读到完整任务历史。
    这里统一用 ``os.path.normcase``（Windows 下转小写、正斜杠转反斜杠）后比较，
    大写、混合大小写与短文件名（由 ``files_path`` 解析真实路径后再判一次）都被拦截。
    """
    folded = os.path.normcase(str(name or ""))
    return any(folded.startswith(os.path.normcase(prefix)) for prefix in FILES_NAME_BLOCKLIST)


def files_allowed(name):
    """/files 白名单：只放行拼装产物扩展名，且不暴露任务历史/运行记录。返回可用名或 None。"""
    name = urllib.parse.unquote(str(name or ""))
    if not name or is_blocked_name(name):
        return None
    ext = os.path.splitext(name)[1].lower()
    if ext not in FILES_EXT_WHITELIST:
        return None
    if "/" in name or "\\" in name or name.startswith("."):
        return None
    return name


def views_allowed(name):
    """/views 白名单：只允许单层 PNG 文件名，挡住路径穿越与隐藏文件。"""
    name = urllib.parse.unquote(str(name or ""))
    if not name.lower().endswith(".png"):
        return None
    if name.startswith(".") or "/" in name or "\\" in name:
        return None
    return name


def resolve_under(base, rel):
    """把相对路径解析到 base 目录内并校验真实存在；越界/不存在返回 None。

    只做一次 unquote（调用方传入的是仍带百分号编码的路径片段），避免二次解码绕过；
    返回真实路径（realpath），同时挡掉符号链接越界。
    """
    rel = urllib.parse.unquote(str(rel or ""))
    if not rel:
        return None
    base_abs = os.path.abspath(base)
    target = os.path.abspath(os.path.join(base_abs, rel))
    if not target.startswith(base_abs + os.sep):
        return None
    if not os.path.isfile(target):
        return None
    real = os.path.realpath(target)
    real_base = os.path.realpath(base_abs)
    if not real.startswith(real_base + os.sep):
        return None
    return real


def mime_for(path):
    """按扩展名判定响应 Content-Type；未知类型按二进制流出。"""
    return MIME.get(os.path.splitext(path)[1].lower(), DEFAULT_MIME)


def read_bytes(path):
    """读取文件内容（一次性）。文件缺失时抛 OSError，由传输层转 404。"""
    with open(path, "rb") as f:
        return f.read()


def read_static(base, rel):
    """通用静态资源读取：路径必须落在 base 内且真实存在，返回 (内容, MIME) 或 None。

    Web 静态资源与页面壳走同一套路径校验（不区分部署形态），因此 Web-only 部署
    在没有任何 artifacts 服务时也能正常提供页面与脚本。
    """
    target = resolve_under(base, rel)
    if target is None:
        return None
    try:
        return read_bytes(target), mime_for(target)
    except OSError:
        return None


class ArtifactService:
    """一个部署实例的产物目录视图：任务产物、评审图、独立 3D 页面。"""

    def __init__(self, artifacts_dir, viz_dir=None):
        self.artifacts_dir = artifacts_dir
        self.views_dir = os.path.join(artifacts_dir, "views")
        self.viz_dir = viz_dir or os.path.join(artifacts_dir, "viz")

    # ---------- 路径解析 ----------
    def files_path(self, name):
        """/files/<name>：白名单通过且真实存在时返回绝对路径，否则 None。

        除 `files_allowed` 的名字级校验外，这里再按**真实路径**复核一次：
        Windows 不区分大小写、也支持 8.3 短文件名，请求 `JOBS_STORE.json` / `JOBS_ST~1.JSON`
        都可能解析到同一个 `jobs_store.json`；用 realpath 取回真实文件名后重新判黑名单，
        并校验真实路径仍在产物目录内（挡符号链接越界）。
        """
        allowed = files_allowed(name)
        if allowed is None:
            return None
        target = os.path.join(self.artifacts_dir, allowed)
        if not os.path.isfile(target):
            return None
        real = os.path.realpath(target)
        real_base = os.path.realpath(self.artifacts_dir)
        if not real.startswith(real_base + os.sep):
            return None
        if is_blocked_name(os.path.basename(real)):
            return None
        return real

    def views_path(self, name):
        """/views/<name>：单层 PNG 且真实存在时返回绝对路径。"""
        allowed = views_allowed(name)
        if allowed is None:
            return None
        target = os.path.join(self.views_dir, allowed)
        if not os.path.isfile(target):
            return None
        real = os.path.realpath(target)
        real_base = os.path.realpath(self.views_dir)
        if not real.startswith(real_base + os.sep):
            return None
        return real

    def viz_path(self, rel):
        """/viz/<rel>：限制在 3D 产物目录内且真实存在。"""
        return resolve_under(self.viz_dir, rel)

    # ---------- 读取 ----------
    def _read_pair(self, path):
        if not path:
            return None
        try:
            return read_bytes(path), mime_for(path)
        except OSError:
            return None

    def read_files(self, name):
        return self._read_pair(self.files_path(name))

    def read_views(self, name):
        return self._read_pair(self.views_path(name))

    def read_viz(self, rel):
        return self._read_pair(self.viz_path(rel))

    def read_static(self, base, rel):
        """通用静态资源读取（Web 静态资源与页面壳用同一套路径校验）。"""
        return self._read_pair(resolve_under(base, rel))
