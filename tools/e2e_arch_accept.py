# -*- coding: utf-8 -*-
"""前后端架构升级真实链路验收工具。

两个 arm（均写证据到 --out 目录）：

1) ``split``：独立部署（API 进程 + Web 静态进程）+ 真实浏览器 + 真实 LLM
   - 静态页上的所有 /api、/files、/views、/viz 请求必须只发往配置的 API 源（逐条记录并断言）；
   - 静态进程不提供任何 /api 路由；API 进程不提供 Web 应用壳；
   - 真实生成：一批快速/高保真任务经 UI 提交至终态，产物可经 API 读取，四 Tab 可见；
   - 并发与取消（取消后不被 worker 覆盖）、原模式重试（模式/原文/retryOf）、
     运行中重启 API 的恢复语义（running → interrupted，静态页仍可用）；
   - 任务记录用 M 组冻结案例（tools/e2e_cases_mode20.py），并复用 M 组断言器评定结果正确性。

2) ``security``：部署安全用例（不需要 LLM / 浏览器）
   - Bearer：无令牌/错令牌 401、正确令牌可用、query token 不接受、健康检查开放；
   - Origin：同源可写、非法 Origin 403、显式 allowlist 可跨源并回 ACAO、预检只允许必要方法头；
   - 请求体：超大 body 413 + Connection: close、错误 Content-Type 415；
   - 非回环监听无令牌拒绝启动；令牌不进入响应体/服务日志。

用法（在项目根目录执行）：
    python -m tools.e2e_arch_accept split --out artifacts/e2e-architecture/<stamp>-split
    python -m tools.e2e_arch_accept security --out artifacts/e2e-architecture/<stamp>-security
"""
import argparse
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.e2e_cases_mode20 import find_m_case  # noqa: E402

DEFAULT_CASES = "M01,M02,M04,M05,M06"
MODE_ERRORS = {
    "fast": ("fast_success", "failed", "cancelled"),
    "fidelity": ("fidelity_success", "fidelity_degraded", "fast_fallback", "failed", "cancelled"),
}


# ---------------------------------------------------------------- 通用工具
def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(message):
    print(f"[{now_iso()}] {message}", flush=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Steps:
    """操作步骤记录器：每步记录用户视角操作、预期、实际与断言结论。

    group 区分两类断言，报告分开陈述（方案要求「功能验收与生成质量分开报告」）：
    - ``arch``：架构升级本身的判据（部署隔离、API 契约、网络来源、取消/重试/恢复、产物可读）；
    - ``gen``：生成结果质量/完整性（受真实模型波动影响，不作为架构验收通过门槛）。

    counted=False 的条目只是过程记录（如“任务提交成功”“3D 画布数”），不参与通过率统计，
    避免把“记录事实”当成“断言通过”而虚高结论（2026-11-15 复核发现）。
    """

    def __init__(self, path):
        self.path = path
        self.items = []

    def check(self, step, expected, ok, actual, fatal=True, group="arch", counted=True):
        entry = {"at": now_iso(), "group": group, "step": step, "expected": expected,
                 "actual": str(actual)[:2000], "ok": bool(ok), "counted": bool(counted)}
        self.items.append(entry)
        flag = "✅" if ok else "❌"
        log(f"{flag}[{group}] {step}｜预期：{expected}｜实际：{entry['actual'][:300]}")
        if not ok and fatal and group == "arch":
            raise AssertionError(f"{step}：预期 {expected}，实际 {actual}")
        return ok

    def require(self, step, expected, condition, actual):
        return self.check(step, expected, condition, actual, fatal=True, group="arch")

    def verify(self, step, expected, condition, actual):
        """架构判据但不中断本轮：失败计入架构失败数（用于逐任务产物/页面断言，避免一处异常丢掉后续证据）。"""
        return self.check(step, expected, condition, actual, fatal=False, group="arch")

    def assert_result(self, step, expected, condition, actual, group="gen"):
        """记录一条真实断言（计入通过/失败统计）；失败只记录、不中断本轮。"""
        return self.check(step, expected, condition, actual, fatal=False, group=group)

    def note(self, step, expected, actual, group="arch"):
        """仅记录过程事实，不计入断言通过率。"""
        return self.check(step, expected, True, actual, fatal=False, group=group,
                          counted=False)

    def counted_items(self, group=None):
        """参与统计的断言条目（排除过程记录）。"""
        return [item for item in self.items
                if item.get("counted", True) and (group is None or item["group"] == group)]

    def failed(self, group=None):
        return [item for item in self.counted_items(group) if not item["ok"]]

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=1)


def http(url, method="GET", headers=None, body=None, timeout=30, raw=False):
    """发 HTTP 请求；返回 (status, headers dict, body bytes)；网络错误抛异常。"""
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def http_json(url, method="GET", headers=None, body=None, timeout=30):
    status, response_headers, payload = http(url, method=method, headers=headers,
                                             body=body, timeout=timeout)
    try:
        return status, json.loads(payload.decode("utf-8")), response_headers
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, {"_raw": payload.decode("utf-8", "replace")}, response_headers


def wait_service(url, timeout=180, interval=0.4):
    """等 HTTP 服务就绪（任意状态码都算就绪）。"""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            http(url, timeout=3)
            return True
        except Exception as exc:  # noqa: BLE001 - 启动期连接失败是预期的
            last_error = exc
            time.sleep(interval)
    raise RuntimeError(f"服务 {url} 未在 {timeout}s 内就绪：{last_error}")


def terminate_process(process, label):
    """终止子进程并回收，避免残留监听端口。"""
    if process is None or process.poll() is not None:
        return
    log(f"停止 {label}（pid={process.pid}）")
    try:
        process.terminate()
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def spawn_server(args, log_path):
    """启动真实 CLI 服务进程，stdout/stderr 落盘。"""
    handle = open(log_path, "w", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "legogod"] + args, cwd=ROOT, env=env,
                               stdout=handle, stderr=subprocess.STDOUT)
    process._log_handle = handle  # noqa: SLF001 - 便于统一关闭
    return process


def close_process_log(process):
    handle = getattr(process, "_log_handle", None)
    if handle is not None:
        try:
            handle.close()
        except Exception:  # noqa: BLE001
            pass


def environment_snapshot(arm, extra=None):
    """环境快照：HEAD、工作区状态、模型、启动命令与端口（令牌等秘密不进快照）。"""

    def git(*args):
        try:
            return subprocess.check_output(["git"] + list(args), cwd=ROOT,
                                           stderr=subprocess.DEVNULL).decode("utf-8").strip()
        except Exception:  # noqa: BLE001
            return "unknown"

    snapshot = {
        "arm": arm,
        "startedAt": now_iso(),
        "head": git("rev-parse", "HEAD"),
        "worktree": [line for line in git("status", "--short").splitlines() if line],
        "python": sys.version.split()[0],
        "model": os.environ.get("LEGOGOD_MODEL") or "（未配置 LEGOGOD_MODEL）",
        "platform": sys.platform,
    }
    snapshot.update(extra or {})
    return snapshot


# ---------------------------------------------------------------- 任务轮询
TERMINAL = ("done", "error", "cancelled", "interrupted")


def fetch_job(api_base, job_id, headers=None):
    status, body, _ = http_json(f"{api_base}/api/job/{job_id}", headers=headers)
    if status != 200:
        raise RuntimeError(f"读取任务 {job_id} 失败：HTTP {status} {body}")
    return body


def wait_job(api_base, job_id, timeout=2700, headers=None, on_tick=None):
    """轮询任务直到终态；返回最终任务快照。"""
    deadline = time.time() + timeout
    tick = 0
    while time.time() < deadline:
        job = fetch_job(api_base, job_id, headers=headers)
        if job.get("status") in TERMINAL:
            return job
        tick += 1
        if on_tick and tick % 20 == 0:
            on_tick(job, int(time.time() - (deadline - timeout)))
        time.sleep(1.5)
    raise RuntimeError(f"任务 {job_id} 未在 {timeout}s 内进入终态")


def submit_job_via_ui(page, web_base, case_id, mode, steps):
    """经真实浏览器 UI 提交任务：填需求 → 选模式 → 点开始 → 等 URL 带任务 ID。"""
    case = find_m_case(case_id)
    if case is None:
        raise SystemExit(f"找不到 M 组案例 {case_id}")
    page.goto(web_base + "/", wait_until="load")
    page.wait_for_selector("#desc", state="visible")
    page.click(f'[data-mode-option="{mode}"]')
    selected = page.eval_on_selector('[data-mode-group] input[name="mode"]:checked',
                                     "el => el.value")
    steps.require(f"{case_id}/{mode} UI 模式选择回读", mode, selected == mode, selected)
    page.fill("#desc", case["desc"])
    steps.require(f"{case_id}/{mode} 需求原文回读", case["desc"],
                  page.input_value("#desc") == case["desc"], page.input_value("#desc")[:80])
    page.click("#go")
    page.wait_for_url(re.compile(r"/\?job=[0-9a-f]{6,}"), timeout=60000)
    match = re.search(r"job=([0-9a-f]{6,})", page.url)
    steps.require(f"{case_id}/{mode} 提交后进入工作台", "URL 带任务 ID",
                  bool(match), page.url)
    return match.group(1)


def assert_mode_facts(job, mode, case_id, steps):
    """任务结果层模式事实：模式持久化、四态合法；快速任务不得出现评审评分/保底。"""
    result = job.get("result") or {}
    outcome = result.get("outcome")
    if not outcome and job.get("status") == "error":
        outcome = "failed"          # 内部异常任务没有 outcome，按失败归
    steps.require(f"{case_id}/{mode} 任务模式持久化", mode, job.get("mode") == mode,
                  job.get("mode"))
    steps.check(f"{case_id}/{mode} 终态结果四态合法", str(MODE_ERRORS[mode]),
                outcome in MODE_ERRORS[mode], outcome, fatal=True, group="arch")
    if mode == "fast":
        steps.check(f"{case_id}/{mode} 快速任务无视觉评审评分", "无 review.scores",
                    not ((result.get("review") or {}).get("scores")),
                    (result.get("review") or {}).get("scores"), fatal=False, group="gen")
        steps.check(f"{case_id}/{mode} 快速任务无快速保底",
                    "无 attempts_detail 且 outcome != fast_fallback",
                    outcome != "fast_fallback" and not result.get("attempts_detail"),
                    {"outcome": outcome, "attempts": bool(result.get("attempts_detail"))},
                    fatal=False, group="gen")


def read_console_errors(page):
    try:
        return page.evaluate("window.__e2e ? {errors: window.__e2e.errors, "
                             "rejections: window.__e2e.rejections} : null")
    except Exception:  # noqa: BLE001 - 页面已经崩溃
        return None


ERROR_COLLECTOR_JS = """
window.__e2e = {errors: [], rejections: []};
window.addEventListener('error', e => window.__e2e.errors.push(String(e.message)));
window.addEventListener('unhandledrejection',
  e => window.__e2e.rejections.push(String(e.reason && e.reason.message || e.reason)));
"""


# ---------------------------------------------------------------- split arm
class SplitArm:
    """独立部署（api + web 两进程）真实浏览器 + 真实 LLM 验收。"""

    def __init__(self, args):
        self.args = args
        self.out = os.path.abspath(args.out)
        self.steps = Steps(os.path.join(self.out, "steps.json"))
        self.api_port = args.api_port or free_port()
        self.web_port = args.web_port or free_port()
        self.api_base = f"http://127.0.0.1:{self.api_port}"
        self.web_base = f"http://127.0.0.1:{self.web_port}"
        self.api_proc = None
        self.web_proc = None
        self.requests = []
        self.results = {"jobs": [], "network": {}, "ui": {}, "checks": {}}

    # ---------- 服务 ----------
    def start_web(self):
        self.web_proc = spawn_server(
            ["web", "--host", "127.0.0.1", "--port", str(self.web_port),
             "--api-url", self.api_base],
            os.path.join(self.out, "server-web.log"))
        wait_service(self.web_base + "/")
        log(f"独立 Web 静态服务就绪：{self.web_base} -> API {self.api_base}")

    def start_api(self, first=False):
        self.api_proc = spawn_server(
            ["api", "--host", "127.0.0.1", "--port", str(self.api_port),
             "--allowed-origins", self.web_base],
            os.path.join(self.out, "server-api.log" if first else "server-api-restart.log"))
        wait_service(self.api_base + "/api/health")
        log(f"独立 API 服务{'重启完成' if not first else '就绪'}：{self.api_base}")

    # ---------- 部署隔离 ----------
    def assert_deployment_isolation(self):
        steps = self.steps
        status, _, _ = http(self.web_base + "/")
        steps.require("独立 Web 提供应用壳", "GET / → 200", status == 200, status)
        status, _, runtime_js = http(self.web_base + "/runtime-config.js")
        runtime_text = runtime_js.decode("utf-8", "replace")
        steps.require("运行时配置指向配置的 API Base URL", self.api_base,
                      status == 200 and self.api_base in runtime_text, runtime_text.strip())
        for path in ("/api/health", "/api/parts", "/api/jobs"):
            status, body, _ = http_json(self.web_base + path)
            steps.require(f"独立 Web 不提供 {path}", "404",
                          status == 404 and body.get("code") == "not_found",
                          {"status": status, "body": body})
        status, _, _ = http(self.web_base + "/files/model_x.json")
        steps.require("独立 Web 不提供产物目录", "404", status == 404, status)
        status, _, _ = http(self.api_base + "/")
        steps.require("独立 API 不提供 Web 应用壳", "404", status == 404, status)
        status, _, _ = http(self.web_base + "/web/api.js")
        steps.require("独立 Web 提供统一 API 客户端脚本", "200", status == 200, status)
        status, body, _ = http_json(self.api_base + "/api/health")
        steps.require("独立 API 健康检查", "200 + ok",
                      status == 200 and body.get("ok") is True, body)
        status, body, _ = http_json(self.api_base + "/api/jobs")
        steps.require("独立 API 历史任务可查", "200 + jobs 数组",
                      status == 200 and isinstance(body.get("jobs"), list),
                      {"status": status, "count": len(body.get("jobs") or [])})

    # ---------- 网络取证 ----------
    def attach_network_log(self, page):
        def on_request(request):
            self.requests.append({"method": request.method, "url": request.url,
                                  "resourceType": request.resource_type,
                                  "at": now_iso()})

        page.on("request", on_request)

    def classify_requests(self):
        """按来源归类请求，并断言 API/产物请求只到配置的 API 源。"""
        api_hits, web_hits, other_hits = [], [], []
        for item in self.requests:
            url = item["url"]
            if url.startswith(self.api_base):
                api_hits.append(item)
            elif url.startswith(self.web_base):
                web_hits.append(item)
            else:
                other_hits.append(item)
        api_paths = ("/api/", "/files/", "/views/", "/viz/")
        wrong_origin = [item for item in web_hits
                        if any(path in item["url"] for path in api_paths)]
        self.results["network"] = {
            "total": len(self.requests),
            "apiRequests": len(api_hits),
            "webRequests": len(web_hits),
            "otherRequests": len(other_hits),
            "apiPathsOnWebOrigin": wrong_origin[:20],
            "sampleApi": [item["url"] for item in api_hits[:15]],
            "sampleWeb": [item["url"] for item in web_hits[:15]],
            "sampleOther": [item["url"] for item in other_hits[:15]],
        }
        self.steps.require("静态页的 API/产物请求只发往配置的 API 源",
                           "web 源上没有 /api、/files、/views、/viz 请求",
                           not wrong_origin, wrong_origin[:5])
        self.steps.require("API 请求确实发往独立 API 进程", "api 请求数 > 0",
                           len(api_hits) > 0, len(api_hits))
        return api_hits, web_hits, other_hits

    # ---------- UI 检查 ----------
    # 页面结构（web/pages/job.js + web/stage.js）：tab=work 是 3D 工作室、tab=steps 是拼装步骤、
    # tab=review 是结果卡（产物下载链接、评审图、运行日志）。跨源部署时这三处都要经 API 取产物，
    # 因此分别断言，避免在错误 Tab 上找元素得出假结论。
    def check_ui_job(self, page, job_id, case_id, mode):
        """工作台状态 + 作品(3D) / 拼装步骤 / 复盘(结果卡) 三个 Tab + 产物链接指向 API 源。"""
        steps = self.steps
        page.goto(f"{self.web_base}/?job={job_id}", wait_until="load")
        page.wait_for_selector(".wb-status", timeout=30000)
        tag_text = page.locator(".wb-status [data-tag]").inner_text().strip()
        steps.verify(f"{case_id}/{mode} 工作台状态标签", "含终态中文标签",
                     any(word in tag_text for word in
                         ("成功", "失败", "降级", "保底", "取消", "中断")), tag_text)
        result_strip = page.locator(".wb-result").count()
        steps.verify(f"{case_id}/{mode} 工作台结果条出现", "结果条可见",
                     result_strip > 0, result_strip)

        # --- 作品 Tab：3D 工作室（依赖跨源读取 model/solution 产物）---
        page.goto(f"{self.web_base}/jobs/{job_id}?tab=work", wait_until="load")
        page.wait_for_selector("[data-pane]", timeout=30000)
        try:
            page.wait_for_function(
                """() => {
                    const pane = document.querySelector('[data-pane]');
                    if (!pane) return false;
                    const text = pane.textContent || '';
                    return pane.querySelectorAll('canvas').length > 0
                        || text.includes('拼装模拟') || text.includes('零件库')
                        || text.includes('产物统计加载失败') || text.includes('加载失败');
                }""", timeout=40000)
        except Exception:  # noqa: BLE001 - 超时后按实际快照断言
            pass
        studio = page.evaluate("""() => {
            const pane = document.querySelector('[data-pane]');
            return {canvases: pane.querySelectorAll('canvas').length,
                    text: (pane.textContent || '').replace(/\\s+/g, ' ').slice(0, 300)};
        }""")
        steps.verify(f"{case_id}/{mode} 作品页 3D 工作室已加载（跨源产物可读）",
                     "画布 > 0 或出现拼装模拟/零件库",
                     studio["canvases"] > 0 or any(
                         word in studio["text"] for word in ("拼装模拟", "零件库")),
                     {"canvases": studio["canvases"], "text": studio["text"][:120]})

        # --- 拼装步骤 Tab ---
        page.goto(f"{self.web_base}/jobs/{job_id}?tab=steps", wait_until="load")
        page.wait_for_selector("[data-pane]", timeout=30000)
        try:
            page.wait_for_function(
                """() => {
                    const pane = document.querySelector('[data-pane]');
                    if (!pane) return false;
                    return pane.querySelectorAll('li[data-piece]').length > 0
                        || (pane.textContent || '').includes('拼装步骤.md')
                        || (pane.textContent || '').includes('下载拼装步骤');
                }""", timeout=40000)
        except Exception:  # noqa: BLE001
            pass
        pieces = page.locator("[data-pane] li[data-piece]").count()
        has_md = page.locator('[data-pane] a[href*="/files/"]').count() > 0
        steps.verify(f"{case_id}/{mode} 拼装步骤可见", "零件行 > 0 或步骤文档链接存在",
                     pieces > 0 or has_md, {"pieces": pieces, "mdLink": has_md})

        # --- 复盘 Tab：结果卡（产物下载链接 / 评审图 / 产物统计 / 运行日志）---
        page.goto(f"{self.web_base}/jobs/{job_id}?tab=review", wait_until="load")
        page.wait_for_selector("[data-pane]", timeout=30000)
        try:
            page.wait_for_function(
                """() => {
                    const pane = document.querySelector('[data-pane]');
                    if (!pane) return false;
                    const files = pane.querySelector('[data-files]');
                    return (files && files.querySelectorAll('a[href]').length > 0)
                        || (pane.textContent || '').includes('无产物');
                }""", timeout=40000)
        except Exception:  # noqa: BLE001
            pass
        try:
            page.wait_for_function(
                """() => {
                    const pane = document.querySelector('[data-pane]');
                    const facts = pane ? pane.querySelector('[data-facts]') : null;
                    return facts && facts.querySelectorAll('.badge').length > 0;
                }""", timeout=30000)
        except Exception:  # noqa: BLE001
            pass
        review = page.evaluate("""() => {
            const pane = document.querySelector('[data-pane]');
            const filesEl = pane.querySelector('[data-files]');
            return {
                title: (document.querySelector('[data-title]') || {}).textContent || '',
                links: filesEl ? [...filesEl.querySelectorAll('a[href]')]
                    .map(a => a.getAttribute('href')) : [],
                facts: pane.querySelectorAll('[data-facts] .badge').length,
                imgs: [...pane.querySelectorAll('[data-viewstrip] img')]
                    .map(img => img.src),
                logLines: pane.querySelectorAll('[data-log] > *').length,
            };
        }""")
        steps.verify(f"{case_id}/{mode} 详情页标题非空", "标题非空",
                     bool(review["title"].strip()), review["title"])
        steps.verify(f"{case_id}/{mode} 产物下载链接已渲染", "至少 1 个链接",
                     len(review["links"]) >= 1, len(review["links"]))
        bad_links = [link for link in review["links"]
                     if not link.startswith(self.api_base)]
        steps.verify(f"{case_id}/{mode} 产物下载链接指向 API 源", "全部以 API 源开头",
                     not bad_links, bad_links[:5])
        steps.verify(f"{case_id}/{mode} 产物统计经 API 加载", "统计徽章 > 0",
                     review["facts"] > 0, review["facts"])
        bad_imgs = [src for src in review["imgs"] if not src.startswith(self.api_base)]
        steps.verify(f"{case_id}/{mode} 评审图链接指向 API 源", "全部以 API 源开头",
                     not bad_imgs, bad_imgs[:5])
        steps.verify(f"{case_id}/{mode} 复盘运行记录可见", "日志行 > 0",
                     review["logLines"] > 0, review["logLines"])
        return review

    def check_history_and_parts(self, page, job_ids):
        steps = self.steps
        page.goto(self.web_base + "/history", wait_until="load")
        page.wait_for_selector("[data-list], .empty", timeout=30000)
        try:
            page.wait_for_function(
                "() => { const list = document.querySelector('[data-list]');"
                " return list && list.children.length > 0; }", timeout=25000)
        except Exception:  # noqa: BLE001 - 超时后按实际快照断言
            pass
        ids_on_page = page.evaluate("""() => {
            const text = document.body.innerText || '';
            return [...new Set((text.match(/[0-9a-f]{8}/g) || []))];
        }""")
        found = [job_id for job_id in job_ids if job_id in ids_on_page]
        steps.verify("历史任务页展示本次任务", "至少一个本次任务 ID 可见",
                      bool(found), {"want": job_ids, "found": found})
        page.goto(self.web_base + "/parts", wait_until="load")
        page.wait_for_selector(".cat-shape, .empty", timeout=30000)
        page.wait_for_timeout(800)
        variants = page.evaluate("""() => ({
            shapes: document.querySelectorAll('.cat-shape').length,
            variants: document.querySelectorAll('.cat-variant').length,
            text: (document.querySelector('#catalog') || {}).innerText || ''})""")
        steps.verify("零件目录经独立 API 加载", "形状与色变体均 > 0",
                      variants["shapes"] > 0 and variants["variants"] > 0,
                      {"shapes": variants["shapes"], "variants": variants["variants"]})
        self.results["ui"]["historyFound"] = found
        self.results["ui"]["parts"] = {"shapes": variants["shapes"],
                                       "variants": variants["variants"]}

    # ---------- 主流程 ----------
    def run(self):
        os.makedirs(self.out, exist_ok=True)
        os.makedirs(os.path.join(self.out, "screenshots"), exist_ok=True)
        case_ids = [item.strip() for item in self.args.cases.split(",") if item.strip()]
        self.results["environment"] = environment_snapshot("split", {
            "apiBase": self.api_base, "webBase": self.web_base,
            "apiCommand": f"python -m legogod api --host 127.0.0.1 --port {self.api_port} "
                          f"--allowed-origins {self.web_base}",
            "webCommand": f"python -m legogod web --host 127.0.0.1 --port {self.web_port} "
                          f"--api-url {self.api_base}",
            "cases": case_ids,
        })
        from playwright.sync_api import sync_playwright
        console_events = []
        failure = None
        try:
            self.start_api(first=True)
            self.start_web()
            self.assert_deployment_isolation()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_default_timeout(60000)
                page.add_init_script(ERROR_COLLECTOR_JS)
                page.on("console", lambda message: console_events.append(
                    {"type": message.type, "text": message.text[:500]}) if message.type == "error"
                    else None)
                self.attach_network_log(page)
                self.run_cases(page, case_ids, browser)
                browser.close()
        except AssertionError as exc:
            failure = str(exc)
            log(f"❌ 验收断言失败：{failure}")
        finally:
            terminate_process(self.api_proc, "API 服务")
            if self.api_proc:
                close_process_log(self.api_proc)
            terminate_process(self.web_proc, "Web 静态服务")
            if self.web_proc:
                close_process_log(self.web_proc)
            try:
                self.classify_requests()
            except AssertionError as exc:
                failure = failure or str(exc)
                log(f"❌ 网络取证断言失败：{exc}")
            self.results["browserConsole"] = console_events
            self.results["failed"] = failure
            self.results["finishedAt"] = now_iso()
            self.steps.save()
            with open(os.path.join(self.out, "network.json"), "w", encoding="utf-8") as f:
                json.dump(self.requests, f, ensure_ascii=False, indent=1)
            with open(os.path.join(self.out, "console.json"), "w", encoding="utf-8") as f:
                json.dump(console_events, f, ensure_ascii=False, indent=1)
            with open(os.path.join(self.out, "environment.json"), "w", encoding="utf-8") as f:
                json.dump(self.results["environment"], f, ensure_ascii=False, indent=1)
            with open(os.path.join(self.out, "results.json"), "w", encoding="utf-8") as f:
                json.dump(self.results, f, ensure_ascii=False, indent=1)
            self.write_summary()
        arch_failed = int(self.results.get("archFailed") or 0)
        return 0 if (failure is None and arch_failed == 0) else 1

    def settle(self, items, steps):
        """把一批已提交任务等到终态，并断言模式事实。"""
        for item in items:
            if item.get("status") == "cancelled":
                continue
            job_id = item["jobId"]

            def on_tick(job, elapsed):
                log(f"… {item['case']}/{item['mode']} {job_id} 运行中 {elapsed}s"
                    f"（阶段 {(job.get('stage') or {}).get('current')}）")

            job = wait_job(self.api_base, job_id, timeout=self.args.timeout, on_tick=on_tick)
            item["status"] = job["status"]
            item["outcome"] = (job.get("result") or {}).get("outcome")
            item["resultSummary"] = summarize_result(job)
            result_entry = {"case": item["case"], "mode": item["mode"],
                            "jobId": job_id, "status": item["status"],
                            "outcome": item["outcome"],
                            "result": item["resultSummary"]}
            item["resultEntry"] = result_entry
            self.results["jobs"].append(result_entry)
            assert_mode_facts(job, item["mode"], item["case"], steps)
        return items

    def run_cases(self, page, case_ids, browser):
        """分两波提交真实任务 → 轮询终态 → UI 与产物断言 → 取消/重试/恢复用例。

        每波并发不超过 3 个真实任务（与既有 E2E 轮口径一致，避免模型侧限流把架构验收搅成质量问题）。
        """
        steps = self.steps
        wave_one = [("M01", "fidelity"), ("M05", "fidelity"), ("M02", "fast")]
        wave_two = [("M01", "fast"), ("M04", "fast"), ("M06", "fast")]

        def submit_wave(wave, label):
            items = []
            for case_id, mode in wave:
                if case_id not in case_ids:
                    continue
                job_id = submit_job_via_ui(page, self.web_base, case_id, mode, steps)
                items.append({"case": case_id, "mode": mode, "jobId": job_id})
                steps.note(f"{label} {case_id}/{mode} 提交成功", "任务 ID 已分配", job_id)
            steps.require(f"{label}真实任务提交", "至少 1 个任务提交成功",
                          len(items) > 0, len(items))
            page.screenshot(path=os.path.join(self.out, "screenshots",
                                              f"{label}-submitted.png"))
            return items

        # 第一波：高保真优先（耗时最长，先跑）
        first = self.settle(submit_wave(wave_one, "第一波"), steps)

        # 第二波：快速任务 + 取消用例（提交后立即取消 M06）
        second = submit_wave(wave_two, "第二波")
        cancel_target = next((item for item in second
                              if item["case"] == "M06" and item["mode"] == "fast"), None)
        if cancel_target:
            page.goto(f"{self.web_base}/?job={cancel_target['jobId']}", wait_until="load")
            page.wait_for_selector(".wb-status [data-tag]", timeout=30000)
            cancel_button = page.locator("[data-cancel]")
            steps.require("工作台提供取消按钮", "取消按钮可见",
                          cancel_button.count() > 0, cancel_button.count())
            cancel_button.first.click()
            cancelled = wait_job(self.api_base, cancel_target["jobId"], timeout=300)
            steps.require("取消后任务立即标记 cancelled", "cancelled",
                          cancelled["status"] == "cancelled", cancelled["status"])
            steps.require("取消结果不被 worker 覆盖", "已由用户取消",
                          (cancelled.get("result") or {}).get("error") == "已由用户取消",
                          (cancelled.get("result") or {}).get("error"))
            page.wait_for_timeout(2500)
            tag_text = page.locator(".wb-status [data-tag]").inner_text().strip()
            steps.require("取消后页面显示已取消", "含取消", "取消" in tag_text, tag_text)
            page.screenshot(path=os.path.join(self.out, "screenshots", "02-cancelled.png"))
            cancel_target["status"] = "cancelled"
            self.results["jobs"].append({"case": cancel_target["case"],
                                         "mode": cancel_target["mode"],
                                         "jobId": cancel_target["jobId"],
                                         "status": "cancelled", "outcome": "cancelled",
                                         "result": summarize_result(cancelled)})
        second = self.settle(second, steps)

        # 产物与 UI 断言（只对成功终态任务；非成功终态如实记录，不阻断架构验收）
        done_items = [item for item in first + second if item["status"] == "done"]
        for item in first + second:
            if item["status"] != "done":
                steps.note(f"{item['case']}/{item['mode']} 非成功终态跳过详情页断言",
                           "状态已记录", {"status": item["status"],
                                          "outcome": item.get("outcome"),
                                          "error": (item.get("resultSummary") or {})
                                          .get("error")})
                continue
            job = fetch_job(self.api_base, item["jobId"])
            assert_artifacts(job, self.api_base, item["case"], item["mode"], steps)
            self.check_ui_job(page, item["jobId"], item["case"], item["mode"])
            page.screenshot(path=os.path.join(
                self.out, "screenshots", f"job-{item['jobId']}-{item['mode']}.png"))
            attach_assertion(item, steps, self.results)
        steps.require("真实任务有成功终态可供产物/页面验收", "至少 1 个任务 done",
                      len(done_items) > 0, len(done_items))

        # 历史页与零件页（数据来自独立 API）
        self.check_history_and_parts(page, [item["jobId"] for item in first + second])

        # 原模式重试：重试已完成的快速任务，验证模式/原文/retryOf
        retry_source = next((item for item in first + second
                             if item["case"] == "M02" and item["mode"] == "fast"
                             and item["status"] == "done"), None)
        if retry_source:
            page.goto(f"{self.web_base}/jobs/{retry_source['jobId']}?tab=work",
                      wait_until="load")
            page.wait_for_selector("[data-pane]", timeout=30000)
            retry_selector = "[data-pane] [data-retry], [data-actions] [data-retry]"
            try:
                page.wait_for_selector(retry_selector, timeout=20000)
            except Exception:  # noqa: BLE001 - 超时后按实际快照断言
                pass
            retry_button = page.locator(retry_selector)
            steps.require("详情页提供重试按钮（按原模式）", "重试按钮可见",
                          retry_button.count() > 0, retry_button.count())
            retry_button.first.click()
            page.wait_for_url(re.compile(r"/\?job=[0-9a-f]{6,}"), timeout=60000)
            new_id = re.search(r"job=([0-9a-f]{6,})", page.url).group(1)
            original = fetch_job(self.api_base, retry_source["jobId"])
            retried = wait_job(self.api_base, new_id, timeout=self.args.timeout)
            steps.require("原模式重试新建任务", "新任务 ID 不同",
                          new_id != retry_source["jobId"], new_id)
            steps.require("原模式重试继承快速模式", "fast",
                          retried.get("mode") == "fast", retried.get("mode"))
            steps.require("原模式重试记录 retryOf", retry_source["jobId"],
                          retried.get("retryOf") == retry_source["jobId"],
                          retried.get("retryOf"))
            steps.require("原模式重试保留原文", original.get("desc"),
                          retried.get("desc") == original.get("desc"),
                          (retried.get("desc") or "")[:60])
            self.results["jobs"].append({"case": "retry-M02", "mode": "fast",
                                         "jobId": new_id, "status": retried.get("status"),
                                         "outcome": (retried.get("result") or {}).get("outcome"),
                                         "result": summarize_result(retried)})
            page.screenshot(path=os.path.join(self.out, "screenshots", "03-retried.png"))
        else:
            steps.check("原模式重试用例前提", "存在已完成的快速任务", False,
                        "本轮无成功快速任务", fatal=False, group="gen")

        # 服务恢复：运行中重启 API → interrupted；静态页仍可加载
        recovery_id = submit_job_via_ui(page, self.web_base, "M02", "fast", steps)
        running = wait_until_running(self.api_base, recovery_id, timeout=180)
        steps.require("恢复用例任务进入运行中", "running", running == "running", running)
        terminate_process(self.api_proc, "API 服务（模拟重启）")
        if self.api_proc:
            close_process_log(self.api_proc)
        self.api_proc = None
        self.start_api(first=False)
        recovered = wait_job(self.api_base, recovery_id, timeout=300)
        steps.require("重启后遗留 running 标记 interrupted", "interrupted",
                      recovered["status"] == "interrupted", recovered["status"])
        status, _, _ = http(self.web_base + "/")
        steps.require("API 重启期间静态页仍可加载", "200", status == 200, status)
        page.goto(f"{self.web_base}/?job={recovery_id}", wait_until="load")
        page.wait_for_selector(".wb-status [data-tag]", timeout=30000)
        tag_text = page.locator(".wb-status [data-tag]").inner_text().strip()
        steps.require("页面显示已中断", "含中断", "中断" in tag_text, tag_text)
        page.screenshot(path=os.path.join(self.out, "screenshots", "04-recovered.png"))
        # 中断任务再发起新任务，证明服务恢复后链路仍可用（不等待结果）
        retry_status, retry_body, _ = http_json(
            f"{self.api_base}/api/retry", method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"jobId": recovery_id}).encode())
        steps.require("恢复后可对中断任务发起重试", "200 + id/mode",
                      retry_status == 200 and retry_body.get("mode") == "fast",
                      {"status": retry_status, "body": {k: retry_body.get(k)
                                                        for k in ("id", "mode")}})
        if retry_status == 200:
            # 立刻取消，避免多跑一次真实生成（模式/原文/retryOf 已在上一步验证过）
            http(f"{self.api_base}/api/job/{retry_body['id']}", method="DELETE")
            steps.note("恢复后的重试任务已立即取消", "避免额外真实生成", retry_body["id"])

    def write_summary(self):
        arch = self.steps.counted_items("arch")
        gen = self.steps.counted_items("gen")
        notes = [item for item in self.steps.items if not item.get("counted", True)]
        arch_failed = [item for item in arch if not item["ok"]]
        gen_failed = [item for item in gen if not item["ok"]]
        self.results["archFailed"] = len(arch_failed)
        self.results["genFailed"] = len(gen_failed)
        lines = [f"# 独立部署真实链路验收（{self.results['environment']['startedAt']}）", "",
                 f"- HEAD：`{self.results['environment']['head']}`",
                 f"- 模型：{self.results['environment']['model']}",
                 f"- API：`{self.api_base}`；Web：`{self.web_base}`",
                 f"- 架构断言：{len(arch) - len(arch_failed)}/{len(arch)} 通过",
                 f"- 结果正确性断言（M 组）：{len(gen) - len(gen_failed)}/{len(gen)} 通过"
                 f"（生成质量，不作为架构验收门槛）",
                 f"- 过程记录项（不计入通过率）：{len(notes)}", "",
                 "| 用例 | 模式 | 任务 | 状态 | 四态 | 结果正确性断言 |",
                 "|---|---|---|---|---|---|"]
        for item in self.results["jobs"]:
            assertion = item.get("assertion")
            if assertion is None:
                assertion_text = "未执行"
            elif assertion.get("skipped"):
                assertion_text = f"跳过（{assertion['skipped']}）"
            elif assertion.get("errors"):
                assertion_text = f"{len(assertion['errors'])} 项失败"
            else:
                assertion_text = "通过"
            lines.append(f"| {item['case']} | {item['mode']} | `{item['jobId']}` | "
                         f"{item['status']} | {item.get('outcome') or '-'} | {assertion_text} |")
        network = self.results.get("network") or {}
        lines += ["", "## 网络取证", "",
                  f"- 请求总数：{network.get('total')}（API 源 {network.get('apiRequests')}，"
                  f"静态源 {network.get('webRequests')}，三方 {network.get('otherRequests')}）",
                  f"- 静态源上的 API/产物请求：{len(network.get('apiPathsOnWebOrigin') or [])} 条"]
        if arch_failed:
            lines += ["", "## 架构失败步骤"] + [
                f"- {item['step']}：预期 {item['expected']}；实际 {item['actual'][:300]}"
                for item in arch_failed]
        if gen_failed:
            lines += ["", "## 结果正确性断言失败（生成质量，非架构判据）"] + [
                f"- {item['step']}：预期 {item['expected']}；实际 {item['actual'][:500]}"
                for item in gen_failed]
        with open(os.path.join(self.out, "summary.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log(f"独立部署验收汇总：{os.path.join(self.out, 'summary.md')}")
        log(f"架构断言 {len(arch) - len(arch_failed)}/{len(arch)} 通过；"
            f"结果正确性断言 {len(gen) - len(gen_failed)}/{len(gen)} 通过")


def wait_until_running(api_base, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = fetch_job(api_base, job_id)
        if job.get("status") == "running":
            return "running"
        if job.get("status") in TERMINAL:
            return job.get("status")
        time.sleep(0.4)
    return "timeout"


def summarize_result(job):
    """结果摘要：只保留架构验收需要的字段（不做生成质量判断）。"""
    result = job.get("result") or {}
    review = result.get("review") if isinstance(result.get("review"), dict) else {}
    return {
        "ok": result.get("ok"),
        "outcome": result.get("outcome"),
        "name": result.get("name"),
        "pieces": result.get("pieces"),
        "runId": result.get("run_id"),
        "error": (str(result.get("error"))[:200] if result.get("error") else None),
        "reviewScores": review.get("scores"),
        "attempts": len(result.get("attempts_detail") or []),
        "modelPath": result.get("model_path"),
        "solutionPath": result.get("solution_path"),
        "mdPath": result.get("md_path"),
        "vizFile": result.get("viz_file"),
    }


def url_path(name):
    """URL 编码产物文件名（步骤文档等含中文，urllib 不接受非 ASCII URL）。"""
    return urllib.parse.quote(str(name), safe="")


def assert_artifacts(job, api_base, case_id, mode, steps):
    """产物经独立 API 可读：模型/方案 JSON、步骤文档、3D 页、评审图。

    路径缺失属于生成结果问题（记 gen 组）；路径存在但 API 读不到属于架构问题（arch 组）。
    """
    result = job.get("result") or {}
    for key, path in (("模型", result.get("model_path")),
                      ("方案", result.get("solution_path"))):
        if not path:
            steps.check(f"{case_id}/{mode} {key}产物路径存在", "非空", False, path,
                        fatal=False, group="gen")
            continue
        status, _, raw = http(f"{api_base}/files/{url_path(path)}")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        steps.verify(f"{case_id}/{mode} {key}产物可经 API 读取", "200 + JSON 对象",
                     status == 200 and isinstance(parsed, dict),
                     {"status": status, "jsonObject": isinstance(parsed, dict)})
    md_path = result.get("md_path")
    if not md_path:
        steps.check(f"{case_id}/{mode} 拼装步骤文档路径存在", "非空", False, md_path,
                    fatal=False, group="gen")
    else:
        status, _, _ = http(f"{api_base}/files/{url_path(md_path)}")
        steps.verify(f"{case_id}/{mode} 拼装步骤文档可经 API 读取", "200", status == 200,
                      status)
    viz_file = result.get("viz_file")
    if not viz_file:
        steps.check(f"{case_id}/{mode} 独立 3D 页路径存在", "非空", False, viz_file,
                    fatal=False, group="gen")
    else:
        status, _, _ = http(f"{api_base}/viz/{url_path(viz_file)}")
        steps.verify(f"{case_id}/{mode} 独立 3D 页可经 API 读取", "200", status == 200,
                      status)
    views = job.get("views") or {}
    front = views.get("front")
    if front:
        name = front.rsplit("/", 1)[-1]
        status, _, _ = http(f"{api_base}/views/{url_path(name)}")
        steps.verify(f"{case_id}/{mode} 评审图可经 API 读取", "200", status == 200, status)


ASSERT_METRIC_KEYS = ("bricks", "target_blocks", "target_blocks_ok",
                      "final_gate_ok", "review_stale", "mode_facts_ok")


def assertion_errors_of(metrics):
    """从 M 组断言器 metrics 取错误列表。

    2026-11-15 复核发现：`tools/e2e_assert_mode20.py` 返回的键是 ``assertion_errors``，
    本工具曾误读 ``errors``，导致真实失败被当成空数组、全部显示“通过”。这里以
    ``assertion_errors`` 为准，同时保留 ``errors`` 兼容旧版本。
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    if isinstance(metrics.get("assertion_errors"), list):
        return list(metrics["assertion_errors"])
    if isinstance(metrics.get("errors"), list):
        return list(metrics["errors"])
    return []


def attach_assertion(item, steps, results):
    """复用 M 组断言器做结果正确性评定（生成质量证据，不计入架构验收门槛）。

    结果同时写回 `item` 与本轮 `results["jobs"]` 里对应的条目，避免汇总表显示“跳过”。
    """
    try:
        from tools.e2e_assert_mode20 import check_run_m
    except ImportError as exc:  # pragma: no cover - 断言器缺失时不阻断架构验收
        steps.assert_result(f"{item['case']}/{item['mode']} 结果正确性断言",
                            "断言器可用", False, f"M 组断言器不可用：{exc}")
        return
    summary = item.get("resultSummary") or {}
    entry = item.get("resultEntry")
    run_id = summary.get("runId")
    case_id = item["case"]
    if not run_id:
        record = {"skipped": "任务终态但没有 run_id（失败任务无最终产物）"}
        item["assertion"] = record
        if entry is not None:
            entry["assertion"] = record
        steps.assert_result(f"{case_id}/{item['mode']} 结果正确性断言", "可断言的 run",
                            False, record["skipped"])
        return
    try:
        metrics = check_run_m(run_id, case_id=case_id)
    except SystemExit as exc:
        record = {"errors": [str(exc)], "metrics": None}
        item["assertion"] = record
        if entry is not None:
            entry["assertion"] = record
        steps.assert_result(f"{case_id}/{item['mode']} 结果正确性断言", "断言器可读取 run",
                            False, f"断言器拒绝：{exc}")
        return
    errors = assertion_errors_of(metrics)
    record = {"errors": errors,
              "metrics": {key: metrics.get(key) for key in ASSERT_METRIC_KEYS}}
    item["assertion"] = record
    if entry is not None:
        entry["assertion"] = record
    steps.assert_result(f"{case_id}/{item['mode']} 结果正确性断言", "无断言错误",
                        not errors, errors or "通过")


# ---------------------------------------------------------------- security arm
class SecurityArm:
    """部署安全用例（不需要 LLM/浏览器）：令牌、Origin、请求体、启动门槛、秘密不泄露。"""

    TOKEN = "arch-accept-token-do-not-log"
    ALLOWED = None

    def __init__(self, args):
        self.args = args
        self.out = os.path.abspath(args.out)
        self.steps = Steps(os.path.join(self.out, "steps.json"))
        self.port = args.api_port or free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = None
        self.results = {}
        self.default_headers = {"Content-Type": "application/json",
                                "Authorization": f"Bearer {self.TOKEN}"}

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        self.results["environment"] = environment_snapshot("security", {
            "apiBase": self.base,
            "command": f"python -m legogod api --host 127.0.0.1 --port {self.port} "
                       f"--api-token <redacted> --allowed-origins {self.allowed_origin()}",
        })
        try:
            self.start()
            self.check_startup_gate()
            self.check_bearer()
            self.check_origin()
            self.check_body_limits()
            self.check_secret_leak()
        finally:
            terminate_process(self.proc, "安全验收 API")
            close_process_log(self.proc) if self.proc else None
            self.steps.save()
            with open(os.path.join(self.out, "environment.json"), "w",
                      encoding="utf-8") as f:
                json.dump(self.results["environment"], f, ensure_ascii=False, indent=1)
            with open(os.path.join(self.out, "results.json"), "w", encoding="utf-8") as f:
                json.dump(self.results, f, ensure_ascii=False, indent=1)
            self.write_summary()
        return 0

    def allowed_origin(self):
        return f"http://127.0.0.1:{self.port + 1}"

    def start(self):
        self.proc = spawn_server(
            ["api", "--host", "127.0.0.1", "--port", str(self.port),
             "--api-token", self.TOKEN, "--allowed-origins", self.allowed_origin()],
            os.path.join(self.out, "server-api.log"))
        wait_service(self.base + "/api/health")
        log(f"安全验收 API 就绪：{self.base}")

    # ---------- 用例 ----------
    def check_startup_gate(self):
        """非回环监听且无令牌：启动即失败并给出明确原因（不起真实服务）。"""
        port = free_port()
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        env.pop("LEGOGOD_API_TOKEN", None)
        completed = subprocess.run(
            [sys.executable, "-m", "legogod", "api", "--host", "0.0.0.0",
             "--port", str(port)], cwd=ROOT, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
        output = (completed.stdout or "") + (completed.stderr or "")
        self.steps.require("非回环监听无令牌拒绝启动", "非 0 退出且提示配置令牌",
                           completed.returncode != 0 and "拒绝启动" in output
                           and "LEGOGOD_API_TOKEN" in output,
                           {"code": completed.returncode, "output": output[-400:]})
        self.results["startupGate"] = {"returncode": completed.returncode,
                                       "message": output.strip().splitlines()[:3]}

    def check_bearer(self):
        steps = self.steps
        status, body, _ = http_json(self.base + "/api/jobs")
        steps.require("无令牌读历史任务被拒", "401",
                      status == 401 and body.get("code") == "unauthorized",
                      {"status": status, "body": body})
        status, body, _ = http_json(self.base + "/api/build", method="POST",
                                    headers={"Content-Type": "application/json"},
                                    body=json.dumps({"desc": "x"}).encode())
        steps.require("无令牌创建任务被拒", "401", status == 401, status)
        status, _, _ = http_json(self.base + "/api/jobs",
                                 headers={"Authorization": "Bearer wrong-token"})
        steps.require("错误令牌被拒", "401", status == 401, status)
        status, _, _ = http_json(f"{self.base}/api/jobs?token={self.TOKEN}")
        steps.require("query token 不被接受", "401", status == 401, status)
        status, body, _ = http_json(self.base + "/api/jobs", headers=self.default_headers)
        steps.require("正确令牌可读历史", "200 + jobs",
                      status == 200 and isinstance(body.get("jobs"), list), status)
        status, _, _ = http_json(self.base + "/api/health")
        steps.require("健康检查保持开放", "200", status == 200, status)
        status, _, _ = http_json(self.base + "/api/parts")
        steps.require("零件目录保持开放", "200", status == 200, status)
        status, _, _ = http_json(self.base + "/api/job/nonexistent",
                                 headers=self.default_headers)
        steps.require("正确令牌下未知任务仍是 404", "404", status == 404, status)

    def check_origin(self):
        steps = self.steps
        # 用未知任务的重试端点验证 Origin 门槛：不创建真实生成任务，但 Origin 校验先于业务校验执行。
        payload = json.dumps({"jobId": "nonexistent"}).encode()
        status, body, _ = http_json(self.base + "/api/retry", method="POST",
                                    headers={**self.default_headers,
                                             "Origin": "http://evil.example.com"},
                                    body=payload)
        steps.require("非法 Origin 写操作被拒", "403 + cross_origin",
                      status == 403 and body.get("code") == "cross_origin",
                      {"status": status, "body": body})
        status, body, headers = http_json(self.base + "/api/retry", method="POST",
                                          headers={**self.default_headers,
                                                   "Origin": self.allowed_origin()},
                                          body=payload)
        steps.require("allowlist 来源通过 Origin 校验（随后按未知任务 404）", "404",
                      status == 404, {"status": status, "body": body})
        steps.require("allowlist 来源回精确 ACAO", self.allowed_origin(),
                      headers.get("Access-Control-Allow-Origin") == self.allowed_origin(),
                      headers.get("Access-Control-Allow-Origin"))
        status, _, headers = http_json(self.base + "/api/parts",
                                       headers={"Origin": "http://other.example.com"})
        steps.require("非 allowlist 来源不下发 CORS 头", "无 ACAO",
                      "Access-Control-Allow-Origin" not in headers,
                      headers.get("Access-Control-Allow-Origin"))
        status, headers, _ = http(self.base + "/api/parts", method="OPTIONS",
                                  headers={"Origin": self.allowed_origin()})
        steps.require("预检允许必要方法与请求头", "GET, POST, DELETE, OPTIONS / 含 Authorization",
                      status == 200
                      and headers.get("Access-Control-Allow-Methods")
                      == "GET, POST, DELETE, OPTIONS"
                      and "Authorization" in (headers.get("Access-Control-Allow-Headers") or ""),
                      {"status": status,
                       "methods": headers.get("Access-Control-Allow-Methods"),
                       "headers": headers.get("Access-Control-Allow-Headers")})
        status, _, _ = http(self.base + "/api/parts", method="OPTIONS",
                            headers={"Origin": "http://evil.example.com"})
        steps.require("非 allowlist 来源预检被拒", "403", status == 403, status)

    def check_body_limits(self):
        steps = self.steps
        status, body, _ = http_json(self.base + "/api/build", method="POST",
                                    headers={"Content-Type": "text/plain",
                                             "Authorization": f"Bearer {self.TOKEN}"},
                                    body=b'{"desc": "x"}')
        steps.require("非 JSON Content-Type 被拒", "415", status == 415, status)
        big = b'{"desc": "' + b"a" * (64 * 1024) + b'"}'
        status, headers, _ = http(self.base + "/api/build", method="POST",
                                  headers={"Content-Type": "application/json",
                                           "Authorization": f"Bearer {self.TOKEN}"},
                                  body=big)
        steps.require("超大请求体被拒并关闭连接", "413 + Connection: close",
                      status == 413
                      and (headers.get("Connection") or "").lower() == "close",
                      {"status": status, "connection": headers.get("Connection")})

    def check_secret_leak(self):
        """令牌不得出现在响应体与服务日志里。"""
        log_path = os.path.join(self.out, "server-api.log")
        leaked_in_log = False
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                leaked_in_log = self.TOKEN in f.read()
        except OSError:
            leaked_in_log = None
        status, headers, raw = http(self.base + "/api/jobs", headers=self.default_headers)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        leaked_in_body = self.TOKEN in json.dumps(body, ensure_ascii=False)
        leaked_in_headers = any(self.TOKEN in str(value) for value in headers.values())
        self.steps.require("令牌不进入响应体与响应头", "未出现令牌",
                           not leaked_in_body and not leaked_in_headers,
                           {"body": leaked_in_body, "headers": leaked_in_headers})
        self.steps.require("令牌不进入服务日志", "未出现令牌", leaked_in_log is False,
                           {"leaked": leaked_in_log})

    def write_summary(self):
        passed = sum(1 for item in self.steps.items if item["ok"])
        total = len(self.steps.items)
        lines = [f"# 部署安全验收（{self.results['environment']['startedAt']}）", "",
                 f"- HEAD：`{self.results['environment']['head']}`",
                 f"- API：`{self.base}`（Bearer + 精确 Origin allowlist）",
                 f"- 断言：{passed}/{total} 通过", "", "## 步骤", ""]
        for item in self.steps.items:
            mark = "✅" if item["ok"] else "❌"
            lines.append(f"- {mark} {item['step']}：预期 {item['expected']}；"
                         f"实际 {item['actual'][:200]}")
        with open(os.path.join(self.out, "summary.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log(f"安全验收汇总：{os.path.join(self.out, 'summary.md')}（{passed}/{total}）")


# ---------------------------------------------------------------- compare arm
class CompareArm:
    """组合部署 vs 独立 API 的契约等价验收：同一批真实任务记录逐项对比。

    两个服务只读同一份任务历史（不创建/取消任务，避免并发写 jobs_store），
    对比状态码、字段集合与字段值；差异必须逐项解释（本 arm 只允许 requestId/role 这类
    文档中明确的新增字段差异）。
    """

    def __init__(self, args):
        self.args = args
        self.out = os.path.abspath(args.out)
        self.steps = Steps(os.path.join(self.out, "steps.json"))
        self.combo_port = args.api_port or free_port()
        self.api_port = args.web_port or free_port()
        self.combo_base = f"http://127.0.0.1:{self.combo_port}"
        self.api_base = f"http://127.0.0.1:{self.api_port}"
        self.combo_proc = None
        self.api_proc = None
        self.diffs = []
        self.compared = []

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        self.results_environment = environment_snapshot("compare", {
            "comboBase": self.combo_base, "apiBase": self.api_base,
            "comboCommand": f"python -m legogod {self.combo_port}",
            "apiCommand": f"python -m legogod api --port {self.api_port}",
        })
        try:
            self.combo_proc = spawn_server([str(self.combo_port)],
                                           os.path.join(self.out, "server-combo.log"))
            wait_service(self.combo_base + "/api/health")
            self.api_proc = spawn_server(["api", "--port", str(self.api_port)],
                                         os.path.join(self.out, "server-api.log"))
            wait_service(self.api_base + "/api/health")
            self.compare_all()
        finally:
            terminate_process(self.combo_proc, "组合部署服务")
            if self.combo_proc:
                close_process_log(self.combo_proc)
            terminate_process(self.api_proc, "独立 API 服务")
            if self.api_proc:
                close_process_log(self.api_proc)
            self.steps.save()
            with open(os.path.join(self.out, "contract-compare.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"environment": self.results_environment,
                           "compared": self.compared, "diffs": self.diffs},
                          f, ensure_ascii=False, indent=1)
            with open(os.path.join(self.out, "environment.json"), "w",
                      encoding="utf-8") as f:
                json.dump(self.results_environment, f, ensure_ascii=False, indent=1)
            self.write_summary()
        return 0 if not self.diffs else 1

    # ---------- 对比工具 ----------
    def _get(self, base, path, method="GET", payload=None):
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        body = json.dumps(payload).encode() if payload is not None else None
        status, response_headers, raw = http(base + path, method=method, headers=headers,
                                             body=body)
        return status, response_headers, raw

    def compare_json(self, label, path, payload=None, method="GET", ignore=("requestId",
                                                                           "role")):
        """对比两个部署对同一请求的状态码与 JSON 体（忽略明确允许的新增字段）。"""
        combo = self._get(self.combo_base, path, method=method, payload=payload)
        api = self._get(self.api_base, path, method=method, payload=payload)

        def parsed(item):
            try:
                body = json.loads(item[2].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = item[2].decode("utf-8", "replace")
            if isinstance(body, dict):
                body = {key: value for key, value in body.items() if key not in ignore}
            return body

        combo_status, api_status = combo[0], api[0]
        combo_body, api_body = parsed(combo), parsed(api)
        ok = combo_status == api_status and combo_body == api_body
        entry = {"label": label, "path": path, "method": method,
                 "comboStatus": combo_status, "apiStatus": api_status, "ok": ok}
        if not ok:
            entry["comboBody"] = str(combo_body)[:1500]
            entry["apiBody"] = str(api_body)[:1500]
            self.diffs.append(entry)
        self.compared.append(entry)
        self.steps.check(f"契约等价：{label}", f"状态 {combo_status} 与响应体一致", ok,
                         {"combo": combo_status, "api": api_status,
                          "diff": None if ok else entry.get("apiBody")},
                         fatal=False, group="arch")
        return combo_status, combo_body

    def compare_artifact(self, label, path):
        """对比产物路由：状态码 + 内容完全一致（避免只比长度）。"""
        combo = self._get(self.combo_base, path)
        api = self._get(self.api_base, path)
        ok = combo[0] == api[0] and combo[2] == api[2]
        entry = {"label": label, "path": path, "comboStatus": combo[0],
                 "apiStatus": api[0], "bytes": len(combo[2]), "ok": ok}
        if not ok:
            self.diffs.append(entry)
        self.compared.append(entry)
        self.steps.check(f"产物等价：{label}", "状态码与内容一致", ok,
                         {"combo": combo[0], "api": api[0], "bytes": len(combo[2])},
                         fatal=False, group="arch")

    # ---------- 全量对比 ----------
    def compare_all(self):
        # 基础接口
        self.compare_json("健康检查", "/api/health")
        self.compare_json("零件目录", "/api/parts")
        # 历史列表：无参兼容 + 分页 + 搜索 + 状态/交付结果筛选
        self.compare_json("历史列表（无参兼容）", "/api/jobs")
        self.compare_json("历史列表（分页）", "/api/jobs?page=1&pageSize=20")
        self.compare_json("历史列表（筛选）",
                          "/api/jobs?page=1&pageSize=20&status=done,error&outcome=fast_success")
        self.compare_json("历史列表（搜索）",
                          "/api/jobs?page=1&pageSize=20&q=" + urllib.parse.quote("目标"))
        # 每个真实任务详情（历史记录样本，最多 30 条）
        _, listing = self.compare_json("历史列表快照", "/api/jobs")
        job_ids = [row.get("id") for row in (listing.get("jobs") or [])][:30]
        self.steps.require("存在真实任务记录可供逐条对比", "任务数 > 0", bool(job_ids),
                           len(job_ids))
        for job_id in job_ids:
            self.compare_json(f"任务详情 {job_id}", f"/api/job/{job_id}")
        # 错误路径
        self.compare_json("未知任务 404", "/api/job/nonexistent")
        self.compare_json("非法分页参数 400", "/api/jobs?page=0")
        self.compare_json("空描述 400", "/api/build", payload={"desc": ""}, method="POST")
        self.compare_json("非法模式 400", "/api/build", payload={"desc": "x", "mode": "bogus"},
                          method="POST")
        self.compare_json("未知重试 404", "/api/retry", payload={"jobId": "nope"},
                          method="POST")
        self.compare_json("未知取消失败 404", "/api/job/nope", method="DELETE")
        # 产物白名单与真实产物
        self.compare_artifact("产物白名单拒绝任务历史", "/files/jobs_store.json")
        self.compare_artifact("产物白名单拒绝运行记录", "/files/run_deadbeef.json")
        self.compare_artifact("产物白名单拒绝路径穿越", "/files/../jobs_store.json")
        example = self.find_example_artifacts(job_ids)
        for label, url in example:
            self.compare_artifact(f"真实产物 {label}", url)
        if not example:
            self.steps.check("存在真实产物可供对比", "至少一个产物文件",
                             False, "历史任务均无产物路径", fatal=False, group="gen")
        # 部署形态差异（这些差异是设计要求的，不是回归）
        combo_status, _, combo_body = self._get(self.combo_base, "/")
        api_status, _, _ = self._get(self.api_base, "/")
        self.steps.check("应用壳只在组合部署提供", "组合 200 / 独立 API 404",
                         combo_status == 200 and api_status == 404,
                         {"combo": combo_status, "api": api_status})
        self.steps.check("组合部署应用壳含前端入口", "HTML 含 LEGOGOD",
                         b"LEGOGOD" in combo_body, combo_body[:80])
        status, _, body = self._get(self.combo_base, "/runtime-config.js")
        self.steps.check("组合部署运行时配置为同源", 'apiBaseUrl 为空串',
                         status == 200 and b'"apiBaseUrl": ""' in body, body[:120])
        status, _, _ = self._get(self.api_base, "/runtime-config.js")
        self.steps.check("独立 API 不提供运行时配置", "404", status == 404, status)

    def find_example_artifacts(self, job_ids):
        """从真实任务记录里找模型/方案/步骤/3D/评审图样本。"""
        wanted = []
        for job_id in job_ids:
            status, _, raw = self._get(self.combo_base, f"/api/job/{job_id}")
            if status != 200:
                continue
            job = json.loads(raw.decode("utf-8"))
            result = job.get("result") or {}
            for key, path in (("model_path", result.get("model_path")),
                              ("solution_path", result.get("solution_path")),
                              ("md_path", result.get("md_path"))):
                if path:
                    wanted.append((f"{key} {job_id}", f"/files/{url_path(path)}"))
            viz_file = result.get("viz_file")
            if viz_file:
                wanted.append((f"viz {job_id}", f"/viz/{url_path(viz_file)}"))
            views = (job.get("views") or {}).get("front")
            if views:
                wanted.append((f"view {job_id}", f"/views/{url_path(views.rsplit('/', 1)[-1])}"))
            if len(wanted) >= 6:
                break
        return wanted[:6]

    def write_summary(self):
        matched = sum(1 for item in self.compared if item["ok"])
        lines = [f"# 组合部署 vs 独立 API 契约等价验收（{self.results_environment['startedAt']}）",
                 "",
                 f"- HEAD：`{self.results_environment['head']}`",
                 f"- 组合部署：`{self.combo_base}`；独立 API：`{self.api_base}`",
                 f"- 对比项：{len(self.compared)}；一致：{matched}；差异：{len(self.diffs)}",
                 "", "## 对比明细", "",
                 "| 项目 | 路径 | 组合状态 | 独立状态 | 一致 |",
                 "|---|---|---|---|---|"]
        for item in self.compared:
            lines.append(f"| {item['label']} | `{item['path']}` | "
                         f"{item.get('comboStatus')} | {item.get('apiStatus')} | "
                         f"{'✅' if item['ok'] else '❌'} |")
        if self.diffs:
            lines += ["", "## 差异明细"] + [
                f"- {item['label']}：组合 {item.get('comboBody')}；"
                f"独立 {item.get('apiBody')}" for item in self.diffs]
        lines += ["", "> 允许的差异只有本方案明确新增的字段（`requestId`、健康检查的 `role`）"
                      "与部署形态差异（组合部署提供应用壳/运行时配置，独立 API 不提供）。"]
        with open(os.path.join(self.out, "summary.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log(f"契约等价验收汇总：{os.path.join(self.out, 'summary.md')}"
            f"（{matched}/{len(self.compared)} 一致）")


# ---------------------------------------------------------------- verify-round arm
class VerifyRoundArm:
    """对已有浏览器 E2E 轮次补齐 M 组结果正确性断言。

    tools/e2e_browser_20 的通用断言器只认 C/H/G/N/R 案例池，M 组（双模式）案例会被标为
    skipped；本 arm 按案例编号调用 tools/e2e_assert_mode20 补齐断言并汇总模式事实，
    供架构验收报告引用「真实 job/result/run、产物与统一校验结果」证据。
    """

    MODE_OUTCOMES = {
        "fast": ("fast_success", "failed", "cancelled"),
        "fidelity": ("fidelity_success", "fidelity_degraded", "fast_fallback", "failed",
                     "cancelled"),
    }

    def __init__(self, args):
        self.args = args
        self.round = os.path.abspath(args.round or args.out)
        self.out = os.path.abspath(args.out)

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        from tools.e2e_assert_mode20 import check_run_m
        rows = self._rows_from_browser_round(check_run_m)
        rows += self._rows_from_split_results(check_run_m)
        assertable = [row for row in rows if row.get("runId") and not row.get("skipped")]
        passed = [row for row in assertable if not row["errors"]]
        task_ok = sum(1 for row in rows if row.get("taskOk"))
        cancelled = sum(1 for row in rows if row.get("status") == "cancelled")
        arch_ok = all(row.get("taskOk") or row.get("status") == "cancelled" for row in rows)
        summary = {
            "round": self.round,
            "finishedAt": now_iso(),
            "total": len(rows),
            "taskOk": task_ok,
            "cancelled": cancelled,
            "assertable": len(assertable),
            "assertPassed": len(passed),
            "assertFailed": len(assertable) - len(passed),
            "rows": rows,
        }
        with open(os.path.join(self.out, "mode20-assert.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)
        lines = [f"# 真实 E2E 轮次结果正确性断言（{now_iso()}）", "",
                 f"- 轮次目录：`{os.path.relpath(self.round, ROOT)}`",
                 f"- 用例数：{summary['total']}；任务成功：{summary['taskOk']}；"
                 f"取消：{summary['cancelled']}",
                 f"- 可断言 run：{summary['assertable']}；断言通过：{summary['assertPassed']}；"
                 f"断言失败：{summary['assertFailed']}", "",
                 "| 用例 | 模式 | 任务 | 状态 | 四态 | 耗时(s) | run_id | 结果正确性断言 |",
                 "|---|---|---|---|---|---|---|---|"]
        for row in rows:
            verdict = row.get("skipped") or (f"{len(row['errors'])} 项失败"
                                             if row["errors"] else "通过")
            lines.append(f"| {row['case']} | {row['mode']} | `{row.get('jobId')}` | "
                         f"{row.get('status')} | {row.get('outcome') or '-'} | "
                         f"{row.get('elapsedS') if row.get('elapsedS') is not None else '-'} | "
                         f"`{row.get('runId')}` | {verdict} |")
        failed = [row for row in rows if row["errors"]]
        if failed:
            lines += ["", "## 断言失败明细"] + [
                f"- {row['case']}/{row['mode']}（run `{row.get('runId')}`）："
                f"{'；'.join(row['errors'])[:800]}"
                for row in failed]
        lines += ["", "> 结果正确性断言沿用 M 组冻结案例与其断言语义（"
                      "`tools/e2e_cases_mode20.py` / `tools/e2e_assert_mode20.py`），"
                      "从断言器 `assertion_errors` 读取失败项；"
                      "生成质量结论与架构升级结论分开陈述。"]
        with open(os.path.join(self.out, "mode20-assert.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log(f"轮次断言汇总：{os.path.join(self.out, 'mode20-assert.md')}"
            f"（{summary['taskOk']}/{summary['total']} 任务成功，"
            f"可断言 {summary['assertable']}，通过 {summary['assertPassed']}，"
            f"失败 {summary['assertFailed']}）")
        return 0 if arch_ok else 1

    # ---------- 数据来源 ----------
    def _rows_from_browser_round(self, check_run_m):
        """浏览器轮次：<round>/<CASE>/<arm>/<CASE>.json。"""
        rows = []
        if not os.path.isdir(self.round):
            return rows
        for case_dir in sorted(os.listdir(self.round)):
            case_path = os.path.join(self.round, case_dir)
            if not os.path.isdir(case_path):
                continue
            for arm in sorted(os.listdir(case_path)):
                record_path = os.path.join(case_path, arm, f"{case_dir}.json")
                if not os.path.isfile(record_path):
                    continue
                with open(record_path, encoding="utf-8") as f:
                    record = json.load(f)
                row = self._row_from_record(record, case_dir, arm,
                                            check_run_m, source="browser")
                rows.append(row)
        return rows

    def _rows_from_split_results(self, check_run_m):
        """独立部署轮次：<round>/results.json 的 jobs（真实任务 + run_id）。"""
        results_path = os.path.join(self.round, "results.json")
        if not os.path.isfile(results_path):
            return []
        with open(results_path, encoding="utf-8") as f:
            results = json.load(f)
        rows = []
        for job in results.get("jobs") or []:
            case = str(job.get("case") or "")
            case_id = case[6:] if case.startswith("retry-") else case
            result = job.get("result") or {}
            record = {"job_id": job.get("jobId"), "status": job.get("status"),
                      "outcome": job.get("outcome"),
                      "taskOk": job.get("status") == "done",
                      "elapsedS": None, "runId": result.get("runId"),
                      "modePolicy": None, "result": result,
                      "error": result.get("error")}
            row = self._row_from_record(record, case_id or case, job.get("mode") or "",
                                        check_run_m, source="split", case_label=case)
            rows.append(row)
        return rows

    def _row_from_record(self, record, case_id, mode, check_run_m, source, case_label=None):
        """单条记录 → 断言结果行；失败项来自断言器 `assertion_errors`。"""
        result = record.get("result") or {}
        row = {"case": case_label or case_id, "caseId": case_id, "mode": mode,
               "jobId": record.get("job_id"), "status": record.get("status"),
               "outcome": record.get("outcome"),
               "taskOk": bool(record.get("taskOk")),
               "elapsedS": record.get("elapsedS"),
               "runId": record.get("runId"), "source": source,
               "modePolicy": record.get("modePolicy"), "errors": [], "metrics": None}
        if record.get("status") == "cancelled":
            row["skipped"] = "任务取消，无最终产物"
        elif not row["taskOk"]:
            row["errors"].append(f"任务未成功：{record.get('outcome')}"
                                 f"（{(result.get('error') or record.get('error') or '')[:160]}）")
        elif not row["runId"]:
            row["skipped"] = "任务成功但没有 run_id"
        else:
            try:
                metrics = check_run_m(row["runId"],
                                      case_id=row["caseId"] or None,
                                      review_fallback=(result.get("review") or None))
                row["metrics"] = {key: metrics.get(key) for key in ASSERT_METRIC_KEYS}
                row["errors"] += assertion_errors_of(metrics)
            except SystemExit as exc:
                row["errors"].append(f"断言器拒绝：{exc}")
        policy = row.get("modePolicy")
        if isinstance(policy, dict) and policy.get("errors"):
            row["errors"] += list(policy["errors"])
        return row


# ---------------------------------------------------------------- CLI
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="前后端架构升级真实链路验收（split / security / compare / verify-round）")
    parser.add_argument("arm", choices=("split", "security", "compare", "verify-round"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--round", default=None,
                        help="verify-round：已有浏览器 E2E 轮次目录（<CASE>/<arm>/<CASE>.json）")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--api-port", type=int, default=0)
    parser.add_argument("--web-port", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=2700,
                        help="单任务等终态超时（秒），默认 45 分钟")
    args = parser.parse_args(argv)
    if args.arm == "split":
        return SplitArm(args).run()
    if args.arm == "compare":
        return CompareArm(args).run()
    if args.arm == "verify-round":
        return VerifyRoundArm(args).run()
    return SecurityArm(args).run()


if __name__ == "__main__":
    sys.exit(main())
