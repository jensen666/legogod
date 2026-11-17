# -*- coding: utf-8 -*-
"""首页目标块数解析的真实浏览器 + 真实 LLM 探针。

验证「目标 300 块」「目标 200 块」（不带「约」）在首页需求输入 → 真实任务 →
任务结果/run 记录里的 ``scaleMetrics.targetBlocks`` 分别解析为 300、200。

复用 ``tools/e2e_browser_20.py`` 的交互范式：Playwright Chromium 打开首页 →
``#desc`` 逐字填入需求 → ``#go`` 点击开始拼装 → URL 带 ``?job=<id>`` →
浏览器内轮询 ``/api/job/<id>`` 直到非 running → 截图 → 读取任务结论。

**禁止 mock LLM**：只提交真实需求、等待真实任务终态；任务业务失败（未交付）
也如实记录，但解析断言只要求 ``targetBlocks`` 正确。

退出码：
- 0：两条需求的 ``targetBlocks`` 断言都通过；
- 1：解析断言失败（含任务未终态/读不到 targetBlocks）；
- 2：基础设施错误（服务不可用、浏览器启动/页面加载/提交失败）。

用法::

    python -m tools.e2e_scale_probe --base-url http://127.0.0.1:8611 \
        --out artifacts/e2e-20/<stamp>-scale-probe
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 两条需求：不带「约」，正是方案要求兼容的写法。
PROBE_REQUESTS = (
    ("300", "目标 300 块"),
    ("200", "目标 200 块"),
)

ERROR_COLLECTOR_JS = """
window.__e2e = { errors: [], rejections: [] };
window.addEventListener('error', e => {
  window.__e2e.errors.push(String((e && e.message) || (e && e.error) || 'error'));
});
window.addEventListener('unhandledrejection', e => {
  window.__e2e.rejections.push(String((e && e.reason && e.reason.message) || (e && e.reason) || 'rejection'));
});
"""


def log(message):
    """控制台可能是 GBK：打印失败不得把已提交的任务打成崩溃。"""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)


def atomic_write_json(path, data):
    """原子写 JSON（先写 .tmp 再 replace，避免中断留下半截文件）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def fetch_job(page, job_id):
    """浏览器内真实 fetch（同源 /api/job），返回任务快照 dict。"""
    return page.evaluate(
        """async (id) => {
            const r = await fetch('/api/job/' + encodeURIComponent(id), {cache: 'no-store'});
            return await r.json();
        }""", job_id)


def collect_page_errors(page):
    """读取页面注入的 JS 错误采集器（页面崩溃时返回 None）。"""
    try:
        return page.evaluate(
            "window.__e2e ? {errors: window.__e2e.errors, rejections: window.__e2e.rejections} : null")
    except Exception:  # noqa: BLE001 - 页面已关闭时取不到
        return None


def screenshot(page, path):
    """截图；失败返回原因字符串而不中断整例。"""
    try:
        page.screenshot(path=path, full_page=False)
        return path
    except Exception as exc:  # noqa: BLE001 - 截图失败不应中断探针
        return f"screenshot failed: {exc}"


def _run_record_target_blocks(run_id):
    """回退：从本机 run 记录读 targetBlocks（与页面同机，不 mock、不造数）。

    返回 (targetBlocks, 来源说明)；文件不存在/无该字段返回 (None, 原因)。
    """
    if not run_id:
        return None, "runId 为空，无法读取 run 记录"
    path = os.path.join(ROOT, "artifacts", f"run_{run_id}.json")
    if not os.path.isfile(path):
        return None, f"run 记录不存在：{path}"
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError) as exc:
        return None, f"run 记录读取失败：{exc}"
    scale = record.get("scaleMetrics")
    if isinstance(scale, dict) and scale.get("targetBlocks") is not None:
        return scale.get("targetBlocks"), f"artifacts/run_{run_id}.json scaleMetrics.targetBlocks"
    return None, f"run 记录无 scaleMetrics.targetBlocks（runId={run_id}）"


def resolve_target_blocks(job, run_id):
    """从任务结果/run 记录解析 targetBlocks，返回 (值, 来源)。"""
    result = (job or {}).get("result") or {}
    scale = result.get("scaleMetrics")
    if isinstance(scale, dict) and scale.get("targetBlocks") is not None:
        return scale.get("targetBlocks"), "job.result.scaleMetrics.targetBlocks"
    from_record, reason = _run_record_target_blocks(run_id)
    if from_record is not None:
        return from_record, reason
    return None, reason


def submit_probe(ctx, base_url, outdir, label, desc):
    """打开首页 → 填需求 → 点击开始拼装，返回记录 dict（含 page/job_id）。

    任何提交阶段异常抛给调用方按基础设施错误处理（退出码 2）。
    """
    page = ctx.new_page()
    page.set_default_timeout(60000)
    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.add_init_script(ERROR_COLLECTOR_JS)
    record = {"label": label, "desc": desc, "baseUrl": base_url,
              "startedAt": datetime.now().isoformat(timespec="seconds"),
              "started": time.time(), "consoleErrors": console_errors, "page": page}
    page.goto(base_url + "/", wait_until="load")
    page.wait_for_selector("#desc", state="visible")
    page.fill("#desc", desc)
    filled = page.input_value("#desc")
    if filled != desc:
        raise RuntimeError(f"需求输入框内容与探针原文不一致：{filled!r} != {desc!r}")
    page.click("#go")
    page.wait_for_url(re.compile(r"/\?job=[0-9a-f]{6,}"), timeout=60000)
    matched = re.search(r"job=([0-9a-f]{6,})", page.url)
    if not matched:
        raise RuntimeError(f"提交后 URL 未携带任务 ID：{page.url}")
    record["job_id"] = matched.group(1)
    record["urlAfterSubmit"] = page.url
    return record


def wait_terminal(record, timeout_s, poll_s):
    """轮询 /api/job/<id> 直到非 running；返回最终 job 快照（超时返回 None）。"""
    page = record["page"]
    deadline = record["started"] + timeout_s
    polls = errors = 0
    while time.time() < deadline:
        polls += 1
        record["polls"] = polls
        try:
            job = fetch_job(page, record["job_id"])
        except Exception as exc:  # noqa: BLE001 - 轮询异常计数，连续 5 次放弃
            errors += 1
            record["lastPollError"] = str(exc)[:200]
            if errors >= 5:
                record["pollFatal"] = record["lastPollError"]
                return None
            time.sleep(poll_s)
            continue
        record["lastStatus"] = job.get("status")
        record["elapsedS"] = round(time.time() - record["started"], 1)
        if job.get("status") != "running":
            return job
        time.sleep(poll_s)
    record["timeout"] = True
    return None


def finalize_probe(ctx, record, job, outdir, expected):
    """收尾单条探针：解析 targetBlocks、断言、截图、落盘 JSON。"""
    page = record.pop("page")
    result = (job or {}).get("result") or {}
    run_id = result.get("run_id") or result.get("runId")
    target_blocks, source = resolve_target_blocks(job, run_id)
    parse_ok = (target_blocks is not None and int(target_blocks) == int(expected))
    shot_path = screenshot(page, os.path.join(outdir, f"scale-probe-{record['label']}.png"))
    payload = {
        "probe": "scale-probe",
        "label": record["label"],
        "desc": record["desc"],
        "expectedTargetBlocks": int(expected),
        "targetBlocks": target_blocks,
        "targetBlocksSource": source,
        "parseOk": parse_ok,
        "parseError": (None if parse_ok
                       else f"目标解析不符：期望 {expected}，实测 {target_blocks}（{source}）"),
        "jobId": record.get("job_id"),
        "runId": run_id,
        "status": (job or {}).get("status"),
        "taskOk": bool(result.get("ok")),
        "outcome": result.get("outcome") or result.get("status"),
        "error": result.get("error"),
        "degradedReason": result.get("degraded_reason"),
        "uiAfterSubmit": record.get("urlAfterSubmit"),
        "polls": record.get("polls"),
        "elapsedS": record.get("elapsedS") or round(time.time() - record["started"], 1),
        "timeout": record.get("timeout", False),
        "pollFatal": record.get("pollFatal"),
        "lastPollError": record.get("lastPollError"),
        "consoleErrors": record.get("consoleErrors") or [],
        "pageErrors": collect_page_errors(page),
        "screenshots": [shot_path],
        "startedAt": record.get("startedAt"),
        "baseUrl": record.get("baseUrl"),
    }
    atomic_write_json(os.path.join(outdir, f"scale-probe-{record['label']}.json"), payload)
    try:
        page.close()
    except Exception:  # noqa: BLE001 - 关闭失败不影响结论
        pass
    return payload


def check_service(base_url):
    """真实 HTTP 自检（不含 LLM）：服务不可用属基础设施错误。"""
    with urllib.request.urlopen(base_url + "/api/parts", timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"/api/parts HTTP {response.status}")


def run(args):
    """跑两条探针需求，返回退出码（0 解析全通过 / 1 解析失败 / 2 基础设施错误）。"""
    outdir = os.path.abspath(args.out or os.path.join(
        ROOT, "artifacts", "e2e-20",
        datetime.now().strftime("%Y%m%d-%H%M%S") + "-scale-probe"))
    os.makedirs(outdir, exist_ok=True)
    try:
        check_service(args.base_url)
    except Exception as exc:  # noqa: BLE001 - 服务不可用即基础设施错误
        log(f"❌ 服务不可用 {args.base_url}：{exc}")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        log(f"❌ Playwright 不可用：{exc}")
        return 2

    results, infra_error = [], None
    with sync_playwright() as p:
        launch_kwargs = {"headless": not args.headed}
        if args.browser_path:
            launch_kwargs["executable_path"] = args.browser_path
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001 - 浏览器起不来即基础设施错误
            log(f"❌ 浏览器启动失败：{exc}")
            return 2
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  locale="zh-CN", timezone_id="Asia/Shanghai")
        for label, desc in PROBE_REQUESTS:
            log(f"▶ 探针 {label}：提交真实需求「{desc}」")
            try:
                record = submit_probe(ctx, args.base_url, outdir, label, desc)
            except Exception as exc:  # noqa: BLE001 - 提交失败属基础设施错误
                infra_error = f"探针 {label} 提交失败：{exc}"
                log(f"❌ {infra_error}\n{traceback.format_exc()[:800]}")
                atomic_write_json(os.path.join(outdir, f"scale-probe-{label}.json"), {
                    "probe": "scale-probe", "label": label, "desc": desc,
                    "expectedTargetBlocks": int(label), "targetBlocks": None,
                    "parseOk": False, "parseError": infra_error,
                    "status": "submit_failed", "infraError": infra_error,
                    "pageErrors": None, "screenshots": [],
                })
                break
            log(f"  已提交 job={record['job_id']}，等待终态（上限 {args.timeout}s）")
            job = wait_terminal(record, args.timeout, args.poll)
            payload = finalize_probe(ctx, record, job, outdir, label)
            results.append(payload)
            log(f"  终态 status={payload['status']} taskOk={payload['taskOk']} "
                f"targetBlocks={payload['targetBlocks']}（{payload['targetBlocksSource']}）"
                f" 解析断言={'✅ 通过' if payload['parseOk'] else '❌ 未通过'}")
        ctx.close()
        browser.close()

    summary = {
        "probe": "scale-probe",
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "baseUrl": args.base_url,
        "outDir": outdir,
        "requests": [{"label": label, "desc": desc} for label, desc in PROBE_REQUESTS],
        "results": results,
        "infraError": infra_error,
        "allParseOk": bool(results) and len(results) == len(PROBE_REQUESTS)
        and all(item.get("parseOk") for item in results),
    }
    atomic_write_json(os.path.join(outdir, "scale-probe-summary.json"), summary)
    if infra_error:
        log(f"❌ 基础设施错误：{infra_error}")
        return 2
    if summary["allParseOk"]:
        log("✅ 两条目标块数解析断言全部通过")
        return 0
    log("❌ 目标块数解析断言未通过，详见 scale-probe-300/200.json")
    return 1


def main(argv=None):
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="首页目标块数解析真实浏览器 + 真实 LLM 探针")
    parser.add_argument("--base-url", default="http://127.0.0.1:8611")
    parser.add_argument("--out", default=None,
                        help="输出目录（默认 artifacts/e2e-20/<stamp>-scale-probe）")
    parser.add_argument("--timeout", type=int, default=2100, help="单例墙钟上限（秒）")
    parser.add_argument("--poll", type=float, default=5.0, help="轮询间隔（秒）")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口（调试用）")
    parser.add_argument("--browser-path", default=None, help="指定 Chromium 可执行文件")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
