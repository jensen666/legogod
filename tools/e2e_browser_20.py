# -*- coding: utf-8 -*-
"""20 例复杂造型 · 浏览器真实 LLM 端到端运行器（Playwright Chromium）。

真实链路（无 mock、无夹具注入）：
  浏览器打开 Web 工坊 → 逐字填入案例需求 → 点击「开始拼装」→ 浏览器轮询 /api/job/<id>
  → 等待真实 LLM 规划/画图/评审/修订与 tiler 求解 → 工作台结果条 → 任务详情四 Tab
  （总览横幅 / 3D 工作室 canvas / 拼装步骤 / 运行记录）→ 截图取证 →
  用 tools/e2e_assert_20.py 对 run 记录与最终产物做结果正确性硬断言。

用法：
    python -m tools.e2e_browser_20 --base-url http://127.0.0.1:8600 \
        --out artifacts/e2e-20/20261101-0220 --concurrency 3
    python -m tools.e2e_browser_20 --cases C01 --out artifacts/e2e-20/smoke   # 单例冒烟
    python -m tools.e2e_browser_20 --cases C02-C20 --resume --out <同一目录>

退出码：所有案例任务成功且断言通过 = 0；有失败/断言不通过 = 1（--allow-failures 时仍返回 0，
用于如实记录探索性批量运行）；基础设施错误（服务不可用/浏览器启动失败）= 2。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools import e2e_assert_20  # noqa: E402
from tools.e2e_cases_20 import CASES, all_cases, find_case  # noqa: E402
from tools.e2e_cases_g import all_g_cases, find_g_case  # noqa: E402  G 组独立确认集接线

_ENV_CACHE = {}


def case_env_snapshot():
    """单例证据环境快照：实际模型名、HEAD/工作区、几何契约开关（每例必存）。

    只读本地配置与 git 状态，绝不记录 API Key；进程内只计算一次（20 例共享同一快照，
    避免每例重复调用 git）。读取失败时字段记 None 并在 note 里写原因，不抛异常。
    """
    if _ENV_CACHE:
        return dict(_ENV_CACHE)
    snap = {"modelName": os.environ.get("LEGOGOD_MODEL"), "modelConfigured": None,
            "codeHead": None, "codeHeadShort": None, "worktreeDirty": None,
            "geometryContract": None, "python": sys.version.split()[0],
            "note": None}
    notes = []
    try:
        from legogod.llm import config  # 延迟导入：缺 .env 时不让取证失败
        snap["modelConfigured"] = (config() or {}).get("model")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"模型配置读取失败：{type(exc).__name__}: {exc}")
    for key, args in (("codeHead", ["rev-parse", "HEAD"]),
                      ("codeHeadShort", ["rev-parse", "--short", "HEAD"])):
        try:
            out = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=10)
            snap[key] = out.stdout.strip() if out.returncode == 0 else None
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{key} 读取失败：{type(exc).__name__}: {exc}")
    try:
        # 工作区可能含中文文件名：显式 UTF-8，避免 Windows 默认 GBK 解码在 reader 线程报错
        out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=15)
        snap["worktreeDirty"] = bool(out.stdout.strip()) if out.returncode == 0 else None
    except Exception as exc:  # noqa: BLE001
        notes.append(f"工作区状态读取失败：{type(exc).__name__}: {exc}")
    try:
        from legogod.geometry_contract import contract_enabled
        snap["geometryContract"] = "on" if contract_enabled() else "off"
    except Exception as exc:  # noqa: BLE001
        notes.append(f"几何契约开关读取失败：{type(exc).__name__}: {exc}")
    snap["note"] = "；".join(notes) or None
    _ENV_CACHE.update(snap)
    return dict(snap)

ERROR_COLLECTOR_JS = """
window.__e2e = { errors: [], rejections: [] };
window.addEventListener('error', e => {
  window.__e2e.errors.push(String((e && e.message) || (e && e.error) || 'error'));
});
window.addEventListener('unhandledrejection', e => {
  window.__e2e.rejections.push(String((e && e.reason && e.reason.message) || (e && e.reason) || 'rejection'));
});
"""


def _now():
    return datetime.now().strftime("%H:%M:%S")


def log(msg):
    """控制台可能是 GBK。打印失败不得把已经提交的任务打成崩溃。"""
    line = f"[{_now()}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)


def atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _ratio_text(ratio):
    """目标块数比的展示文本（None 记为未知）。"""
    return f"{ratio:.1%}" if isinstance(ratio, (int, float)) else "未知"


def _tier_fields(result):
    """从单例断言 metrics 取两层复杂度字段（需求达标档/能力回归档/最终门禁）。

    C/H 组的 requirement_tier 是 dict；G 组（tools/e2e_assert_g.py）的
    requirement_tier 是失败项列表，规模字段放在 metrics 顶层，这里做形态兼容。
    """
    metrics = (result.get("assertion") or {}).get("metrics") or {}
    requirement = metrics.get("requirement_tier")
    requirement = requirement if isinstance(requirement, dict) else {}
    regression = metrics.get("regression_tier") or {}
    regression = regression if isinstance(regression, dict) else {}

    def pick(key, flat_key):
        value = requirement.get(key)
        return metrics.get(flat_key) if value is None else value

    requirement_ok = requirement.get("ok")
    if requirement_ok is None and metrics.get("assertion_ok") is not None:
        requirement_ok = metrics.get("assertion_ok")
    return {
        "targetBlocks": pick("target_blocks", "target_blocks"),
        "bricks": pick("bricks", "bricks"),
        "bricksRatio": pick("bricks_ratio", "bricks_ratio"),
        "targetBlocksOk": pick("target_blocks_ok", "target_blocks_ok"),
        "requirementOk": requirement_ok,
        "voxelsPerPiece": regression.get("actual_voxels_per_piece")
        if regression else metrics.get("voxels_per_piece"),
        "baselineVoxelsPerPiece": regression.get("baseline_voxels_per_piece_median"),
        "finalGateSource": metrics.get("final_gate_source"),
        "finalGateOk": metrics.get("final_gate_ok"),
        "versionOverwrites": metrics.get("version_overwrites"),
        "reviewStale": metrics.get("review_stale"),
    }


def fetch_job(page, job_id):
    """浏览器内真实 fetch（同源 /api/job），返回任务快照 dict。"""
    return page.evaluate(
        """async (id) => {
            const r = await fetch('/api/job/' + encodeURIComponent(id), {cache: 'no-store'});
            return await r.json();
        }""", job_id)


def ui_snapshot(page):
    """读取工作台可见状态（标签/耗时/日志行数/实时条/结果条）。"""
    return page.evaluate("""() => {
        const q = s => document.querySelector(s);
        const tag = q('.wb-status [data-tag]');
        const elapsed = q('.wb-status [data-elapsed]');
        const name = q('.wb-status .wb-name');
        const logLines = document.querySelectorAll('.wb-log [data-log] > *').length;
        const live = q('.wb-log .livebar, .wb-log [data-live]');
        const strip = q('.wb-result');
        const stripLink = strip ? strip.querySelector('a') : null;
        return {
            name: name ? name.textContent.trim() : '',
            tag: tag ? tag.textContent.trim() : '',
            elapsed: elapsed ? elapsed.textContent.trim() : '',
            logLines,
            live: live ? (live.textContent || '').trim().slice(0, 120) : '',
            resultStrip: strip ? (strip.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200) : '',
            resultLink: stripLink ? stripLink.getAttribute('href') : null,
        };
    }""")


def page_errors(page):
    try:
        return page.evaluate("window.__e2e ? {errors: window.__e2e.errors, rejections: window.__e2e.rejections} : null")
    except Exception:  # noqa: BLE001 - 页面崩溃时取不到错误采集器
        return None


def shot(page, path):
    try:
        page.screenshot(path=path, full_page=False)
        return path
    except Exception as exc:  # noqa: BLE001 - 截图失败不应中断整例
        return f"screenshot failed: {exc}"


def parse_cases(spec, modes=None):
    """支持 C01,C02 / C01-C05 / C21 / H01-H10 / G01-G10 / N01-N20 / R01-R10 / M01-M20 / all。

    all 仍只含原来的 20 例。区间必须同前缀：`C01-C05` 只挑 C 案例、`H01-H10` 只挑 H 案例，
    否则 C01-C05 的编号会被误配到同数字的 H 案例。G01–G10 是独立确认集
    （tools/e2e_cases_g.py 单源），N01–N20 在 tools/e2e_cases_new20.py，
    R01–R10 是 2026-11-14 几何契约 A/B 的未参与开发新例（tools/e2e_cases_r.py），
    M01–M20 是快速/高保真双模式恢复的同题案例（tools/e2e_cases_mode20.py）。

    modes：M 组双模式臂（如 ("fast","fidelity")）。给出时每个 M 案例展开成两个 arm 条目，
    并按冻结口径做奇偶交换（同一案例两臂相邻提交）。
    """
    if not spec or spec.strip().lower() == "all":
        return list(CASES)
    # 新 20 例（N01–N20）单源在 tools/e2e_cases_new20.py：导入失败时不影响
    # 既有 C/H/G 案例解析（该模块由本轮验收新增，旧轮次环境可能没有）。
    try:
        from tools.e2e_cases_new20 import all_n_cases, find_n_case
    except ImportError:
        all_n_cases = find_n_case = None
    # R 组（R01–R10）单源在 tools/e2e_cases_r.py，同样容错导入。
    try:
        from tools.e2e_cases_r import all_r_cases, find_r_case
    except ImportError:
        all_r_cases = find_r_case = None
    # M 组（M01–M20）双模式案例单源，容错导入。
    try:
        from tools.e2e_cases_mode20 import all_m_cases, find_m_case
    except ImportError:
        all_m_cases = find_m_case = None
    pool = list(all_cases()) + list(all_g_cases())
    if all_n_cases is not None:
        pool += list(all_n_cases())
    if all_r_cases is not None:
        pool += list(all_r_cases())
    if all_m_cases is not None:
        pool += list(all_m_cases())
    picked = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and not part.startswith("C-"):
            lo, hi = [x.strip() for x in part.split("-", 1)]
            if len(lo) < 2 or len(hi) < 2:
                raise SystemExit(f"区间格式不对：{part}（示例 C01-C05 / H01-H10 / G01-G10 / R01-R10 / M01-M20）")
            prefix = lo[0].upper()
            if hi[0].upper() != prefix:
                raise SystemExit(f"区间前后缀不一致：{part}")
            lo_i, hi_i = int(lo[1:]), int(hi[1:])
            picked.extend(c for c in pool
                          if c["id"][0].upper() == prefix and lo_i <= int(c["id"][1:]) <= hi_i)
        else:
            case = find_case(part) or find_g_case(part)
            if not case and find_n_case is not None:
                case = find_n_case(part)
            if not case and find_r_case is not None:
                case = find_r_case(part)
            if not case and find_m_case is not None:
                case = find_m_case(part)
            if not case:
                raise SystemExit(f"未知案例：{part}")
            picked.append(case)
    seen = set()
    out = []
    for c in picked:
        if c["id"] not in seen:
            seen.add(c["id"])
            out.append(c)
    has_m = any(c["id"].upper().startswith("M") for c in out)
    if has_m and modes is None:
        # 只给 M 案例时默认跑两臂，避免忘记 --modes 却只跑一半
        modes = ("fast", "fidelity")
    if modes:
        if not has_m:
            raise SystemExit("--modes 只适用于 M 组双模式案例")
        out = _expand_mode_arms(out, modes)
    return out


MODE_ARMS = ("fast", "fidelity")


def _expand_mode_arms(cases, modes):
    """把每个 M 案例展开成 arm 条目：同一案例两臂相邻，奇偶案例交换先后。"""
    arms = [m for m in (modes or ()) if m in MODE_ARMS]
    if not arms:
        raise SystemExit(f"--modes 只能取 {MODE_ARMS} 中的值")
    expanded = []
    for idx, case in enumerate(cases):
        if not case["id"].upper().startswith("M"):
            raise SystemExit("--modes 只适用于 M 组双模式案例")
        order = list(arms) if idx % 2 == 0 else list(reversed(arms))
        for arm in order:
            item = dict(case)
            item["arm"] = arm
            item["runKey"] = f"{case['id']}-{arm}"
            expanded.append(item)
    return expanded


def record_path(outdir, case):
    """单例记录落盘路径：M 组按 <out>/<CASE>/<arm>/<CASE>.json，旧案例保持扁平路径。"""
    if case.get("arm"):
        return os.path.join(outdir, case["id"], case["arm"], f"{case['id']}.json")
    return os.path.join(outdir, f"{case['id']}.json")


def case_dir_for(outdir, case):
    """单例证据目录：M 组分模式子目录，禁止两臂覆盖同一案例文件。"""
    if case.get("arm"):
        return os.path.join(outdir, case["id"], case["arm"])
    return os.path.join(outdir, case["id"])


# ---------------------------------------------------------------- 提交与轮询
def _mode_policy_errors(result, arm):
    """任务结果层面的模式事实断言（快速无评审/无保底，高保真保底≤1 次）。

    run 记录层面的模式事实由 tools/e2e_assert_mode20.py 断言；这里补 job result 级检查：
    快速任务不得出现视觉评审结果或自动保底尝试；高保真交付不得混入保底、
    保底成功必须恰好两次尝试且第一次为高保真；高保真成功必须有有效评审分数。
    """
    errors = []
    result = result or {}
    outcome = result.get("outcome")
    attempts = result.get("attempts_detail") or []
    if arm == "fast":
        if attempts:
            errors.append("模式事实：快速任务不得出现自动保底尝试（attempts_detail 必须为空）")
        if outcome not in ("fast_success", "failed", "cancelled"):
            errors.append(f"模式事实：快速任务四态只能是 fast_success/failed/cancelled，"
                          f"实际 {outcome!r}")
        if result.get("review") or result.get("review_flag"):
            errors.append("模式事实：快速任务不得产生视觉评审结果或评审标记")
    elif arm == "fidelity":
        if len(attempts) > 2:
            errors.append(f"模式事实：高保真自动保底最多一次，实际 {len(attempts)} 次尝试")
        if outcome == "fast_fallback":
            if len(attempts) != 2:
                errors.append(f"模式事实：快速保底成功必须保留两次尝试明细，实际 {len(attempts)} 次")
            elif [a.get("mode") for a in attempts] != ["fidelity", "fast"]:
                errors.append("模式事实：保底任务两次尝试顺序必须是高保真→快速，"
                              f"实际 {[a.get('mode') for a in attempts]}")
        elif outcome in ("fidelity_success", "fidelity_degraded") and attempts:
            errors.append("模式事实：高保真成功/降级交付不得包含自动保底尝试")
        if outcome == "fidelity_success":
            scores = (result.get("review") or {}).get("scores") or {}
            if not scores:
                errors.append("模式事实：高保真成功必须具有有效视觉评审分数（不得凭空成功）")
    return errors


def start_case(ctx, base_url, case, outdir, timeout_s):
    """打开创作台 → 选择模式（M 组）→ 填写需求 → 点击开始拼装 → 记录 job id（全部真实 UI 交互）。"""
    page = ctx.new_page()
    # 注意：Playwright 的超时单位是毫秒；单例墙钟上限（秒）只用于轮询判定，不在这里设。
    page.set_default_timeout(60000)
    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.add_init_script(ERROR_COLLECTOR_JS)
    arm = case.get("arm")
    rec = {"case": case["id"], "name": case["name"], "desc": case["desc"],
           # 需求哈希：逐例冻结证据（每例必存需求哈希）。
           "descHash": hashlib.sha256(case["desc"].encode("utf-8")).hexdigest(),
           "started": time.time(), "startedAt": datetime.now().isoformat(timespec="seconds"),
           "page": page, "console_errors": console_errors,
           "ui": {}, "status": "submitted"}
    if arm:
        rec["arm"] = arm
        rec["runKey"] = case.get("runKey") or f"{case['id']}-{arm}"
        rec["mode"] = arm
    page.goto(base_url + "/", wait_until="load")
    page.wait_for_selector("#desc", state="visible")
    # 创作台空态 + 3 个示例 + 主按钮（真实可见性检查）
    rec["ui"]["chips"] = page.locator("#chips .chip").count()
    rec["ui"]["emptyText"] = page.locator(".wb-empty").inner_text() if page.locator(".wb-empty").count() else ""
    if arm:
        # 选择指定模式并回读选中态（默认档位也一并留证）
        rec["ui"]["modeDefault"] = page.eval_on_selector(
            '[data-mode-group] input[name="mode"]:checked', "el => el.value")
        page.click(f'[data-mode-option="{arm}"]')
        selected = page.eval_on_selector(
            '[data-mode-group] input[name="mode"]:checked', "el => el.value")
        rec["ui"]["modeSelected"] = selected
        if selected != arm:
            raise RuntimeError(f"UI 模式回读不一致：期望 {arm}，实际 {selected}")
    page.fill("#desc", case["desc"])
    filled = page.input_value("#desc")
    if filled != case["desc"]:
        raise RuntimeError("需求输入框内容与案例原文不一致")
    page.click("#go")
    page.wait_for_url(re.compile(r"/\?job=[0-9a-f]{6,}"), timeout=60000)
    m = re.search(r"job=([0-9a-f]{6,})", page.url)
    if not m:
        raise RuntimeError(f"提交后 URL 未携带任务 ID：{page.url}")
    rec["job_id"] = rec["jobId"] = m.group(1)
    rec["urlAfterSubmit"] = page.url
    page.wait_for_selector(".wb-status", state="visible", timeout=30000)
    rec["ui"]["submitSnapshot"] = ui_snapshot(page)
    if arm:
        # 从 API 核对 job.mode，确认实际路由与 UI 选择一致
        try:
            job_now = fetch_job(page, rec["job_id"])
        except Exception as exc:  # noqa: BLE001
            job_now = {"error": f"提交后快照读取失败：{exc}"}
        rec["jobModeAtSubmit"] = job_now.get("mode")
        rec["ui"]["jobModeAtSubmit"] = job_now.get("mode")
        if job_now.get("mode") != arm:
            raise RuntimeError(
                f"任务实际 mode={job_now.get('mode')!r} 与 UI 选择 {arm!r} 不一致")
    return rec


def poll_case(rec, timeout_s, sample_every=3):
    """轮询一次：返回 True 表示任务已结束（需要 finalize）。"""
    page = rec["page"]
    rec["polls"] = rec.get("polls", 0) + 1
    elapsed = time.time() - rec["started"]
    rec["elapsedS"] = round(elapsed, 1)
    if elapsed > timeout_s:
        rec["timeout"] = True
        return True
    try:
        job = fetch_job(page, rec["job_id"])
    except Exception as exc:  # noqa: BLE001 - 页面/服务异常计数后继续
        rec["poll_errors"] = rec.get("poll_errors", 0) + 1
        rec["last_poll_error"] = str(exc)[:200]
        return rec["poll_errors"] >= 5
    rec["lastJob"] = {"status": job.get("status"), "live": job.get("live")}
    if rec["polls"] % sample_every == 0:
        try:
            rec["ui"].setdefault("samples", []).append({"t": round(elapsed, 1), **ui_snapshot(page)})
        except Exception:  # noqa: BLE001 - 采样失败不影响主流程
            pass
    return job.get("status") != "running"


def finalize_case(rec, outdir, case_dir):
    """任务结束后：抓最终状态、四 Tab 浏览、截图、运行硬断言，落盘单例 JSON。"""
    page = rec.pop("page")
    rec["env"] = case_env_snapshot()
    finalize = {"job": rec.get("lastJob")}
    try:
        job = fetch_job(page, rec["job_id"])
    except Exception as exc:  # noqa: BLE001
        job = {"error": f"最终快照读取失败：{exc}"}
    rec["job"] = job
    rec["status"] = job.get("status")
    result = job.get("result") or {}
    rec["result"] = result
    rec["outcome"] = result.get("outcome") or ("fast_success" if result.get("ok") else "failed")
    rec["taskOk"] = bool(result.get("ok"))
    rec["runId"] = result.get("run_id")
    rec["elapsedFinal"] = round(time.time() - rec["started"], 1)

    # ---------- 工作台结果态 ----------
    shots = []
    try:
        page.goto(f"{rec['baseUrl']}/?job={rec['job_id']}", wait_until="load")
        page.wait_for_selector(".wb-status", timeout=30000)
        page.wait_for_selector(".wb-result", timeout=15000)
        rec["ui"]["finalSnapshot"] = ui_snapshot(page)
        rec["ui"]["resultStripPresent"] = True
        shots.append(shot(page, os.path.join(case_dir, "01-workbench-result.png")))
    except Exception as exc:  # noqa: BLE001
        rec["ui"]["resultStripPresent"] = False
        rec["ui"]["workbenchError"] = str(exc)[:300]
        shots.append(shot(page, os.path.join(case_dir, "01-workbench-result.png")))

    # ---------- 任务详情四 Tab ----------
    tabs = {}
    try:
        page.goto(f"{rec['baseUrl']}/jobs/{rec['job_id']}?tab=overview", wait_until="load")
        page.wait_for_selector("[data-pane]", timeout=30000)
        page.wait_for_timeout(600)
        tabs["overview"] = page.evaluate("""() => {
            const pane = document.querySelector('[data-pane]');
            const banners = [...document.querySelectorAll('[data-pane] .banner')].map(e => e.className + '|' + e.textContent.trim());
            const facts = document.querySelector('[data-pane] [data-facts]');
            const files = document.querySelector('[data-pane] [data-files]');
            const review = document.querySelector('[data-pane] [data-review]');
            const title = document.querySelector('[data-title]');
            const tag = document.querySelector('[data-tag]');
            const actions = document.querySelector('[data-actions]');
            return {
                title: title ? title.textContent.trim() : '',
                tag: tag ? tag.textContent.trim() : '',
                banners,
                facts: facts ? (facts.textContent || '').replace(/\\s+/g, ' ').trim() : '',
                files: files ? (files.textContent || '').replace(/\\s+/g, ' ').trim() : '',
                review: review ? (review.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 300) : '',
                actions: actions ? (actions.textContent || '').replace(/\\s+/g, ' ').trim() : '',
                retryButton: !!document.querySelector('[data-pane] [data-retry], [data-actions] [data-retry]'),
            };
        }""")
        shots.append(shot(page, os.path.join(case_dir, "02-overview.png")))
        # 作品 / 拼装步骤仍只在成功时打开；复盘（旧链接 logs）失败时也要能看到原因。
        tab_plan = [("logs", "05-logs.png")]
        if rec["taskOk"]:
            tab_plan = [("studio", "03-studio.png"), ("steps", "04-steps.png"), ("logs", "05-logs.png")]
        for tab, fname in tab_plan:
                try:
                    page.goto(f"{rec['baseUrl']}/jobs/{rec['job_id']}?tab={tab}", wait_until="load")
                    page.wait_for_selector("[data-pane]", timeout=30000)
                    if tab == "studio":
                        page.wait_for_function(
                            "() => document.querySelectorAll('[data-pane] canvas').length > 0 "
                            "|| document.querySelector('[data-pane]').textContent.includes('零件库')",
                            timeout=25000)
                        page.wait_for_timeout(1200)
                        tabs["studio"] = page.evaluate("""() => ({
                            canvases: document.querySelectorAll('[data-pane] canvas').length,
                            tables: document.querySelectorAll('[data-pane] table').length,
                            text: (document.querySelector('[data-pane]').textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 240),
                        })""")
                        shots.append(shot(page, os.path.join(case_dir, fname)))
                    elif tab == "steps":
                        page.wait_for_function(
                            "() => document.querySelectorAll('[data-pane] li[data-piece]').length > 0 "
                            "|| document.querySelector('[data-pane]').textContent.includes('拼装步骤.md')",
                            timeout=20000)
                        page.wait_for_timeout(400)
                        tabs["steps"] = page.evaluate("""() => ({
                            pieces: document.querySelectorAll('[data-pane] li[data-piece]').length,
                            download: document.querySelector('[data-pane] a[href*="/files/"]') ?
                                document.querySelector('[data-pane] a[href*="/files/"]').getAttribute('href') : null,
                            text: (document.querySelector('[data-pane]').textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
                        })""")
                        shots.append(shot(page, os.path.join(case_dir, fname)))
                    else:
                        page.wait_for_function(
                            "() => document.querySelectorAll('[data-pane] [data-log] > *').length > 0",
                            timeout=20000)
                        tabs["logs"] = page.evaluate("""() => ({
                            lines: document.querySelectorAll('[data-pane] [data-log] > *').length,
                            logcount: (document.querySelector('[data-pane] [data-logcount]') || {}).textContent || '',
                            milestones: document.querySelectorAll('[data-pane] [data-miles] .rv, [data-pane] [data-review] .rv').length,
                            livebar: !!document.querySelector('[data-pane] .livebar'),
                        })""")
                        shots.append(shot(page, os.path.join(case_dir, fname)))
                except Exception as exc:  # noqa: BLE001 - 单 Tab 失败记录后继续
                    tabs[tab] = {"error": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001
        rec["ui"]["detailError"] = str(exc)[:300]
    rec["tabs"] = tabs
    rec["screenshots"] = shots

    # ---------- 页面错误采集器 ----------
    try:
        page.goto(f"{rec['baseUrl']}/?job={rec['job_id']}", wait_until="load")
    except Exception:  # noqa: BLE001
        pass
    rec["pageErrors"] = page_errors(page)

    # ---------- 结果正确性硬断言 ----------
    assertion = {"skipped": None, "metrics": None}
    if rec["taskOk"] and rec["runId"]:
        try:
            # 旧 run 记录没有 review 字段时用任务 result.review 补入；
            # 新记录由主链直接落盘 review.parsed，两者都在 metrics.review_source 留痕。
            assertion["metrics"] = e2e_assert_20.check_run(
                rec["runId"], rec["case"], review_fallback=(result.get("review") or None))
        except SystemExit as exc:
            assertion["skipped"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            assertion["skipped"] = f"断言执行异常：{exc}\n{traceback.format_exc()[:600]}"
    else:
        assertion["skipped"] = "任务未成功（无最终产物）" if not rec["taskOk"] else "缺少 runId"
    rec["assertion"] = assertion
    rec["assertOk"] = bool(assertion["metrics"] and assertion["metrics"].get("assertion_ok"))
    if assertion["skipped"]:
        rec["assertOk"] = False

    # ---------- run 记录快照（本地运行产物；证据只拷 run 记录） ----------
    try:
        src = os.path.join(ROOT, "artifacts", f"run_{rec['runId']}.json")
        if rec["runId"] and os.path.isfile(src):
            with open(src, encoding="utf-8") as f:
                rec["runRecord"] = json.load(f)
    except Exception:  # noqa: BLE001
        pass

    # ---------- 模式路由一致性：UI 选择、API job、result、run 必须同源 ----------
    if rec.get("arm"):
        run_mode = (rec.get("runRecord") or {}).get("mode")
        seen = {"ui": rec["ui"].get("modeSelected"), "api": job.get("mode"),
                "result": result.get("mode"), "run": run_mode}
        mismatches = [f"{k}={seen[k]!r}" for k in ("api", "result", "run")
                      if seen[k] is not None and seen[k] != rec["arm"]]
        rec["modeCheck"] = {"expected": rec["arm"], "seen": seen,
                            "ok": not mismatches, "mismatches": mismatches}
        if mismatches:
            rec["assertOk"] = False
            rec["modeCheckError"] = "模式路由不一致：" + "，".join(mismatches)

    # ---------- 任务结果级模式事实断言（快速无评审/无保底，高保真保底≤1 次） ----------
    if rec.get("arm"):
        policy_errors = _mode_policy_errors(result, rec["arm"])
        rec["modePolicy"] = {"ok": not policy_errors, "errors": policy_errors}
        metrics = (rec.get("assertion") or {}).get("metrics")
        if isinstance(metrics, dict):
            metrics.setdefault("assertion_errors", []).extend(policy_errors)
            metrics["assertion_ok"] = not policy_errors and bool(metrics.get("assertion_ok"))
            metrics["mode_policy"] = rec["modePolicy"]
        if policy_errors:
            rec["assertOk"] = False

    # ---------- 实际交付来源（追溯最终产物来自哪次尝试） ----------
    outcome = result.get("outcome")
    if rec.get("arm"):
        if outcome in ("fidelity_success", "fidelity_degraded"):
            rec["delivery"] = "fidelity"
        elif outcome in ("fast_fallback", "fast_success"):
            rec["delivery"] = "fast"
        else:
            rec["delivery"] = None
        rec["attemptsCount"] = len(result.get("attempts_detail") or []) or 1

    try:
        page.close()
    except Exception:  # noqa: BLE001
        pass

    # 逐例落盘（大字段分离：job 只留摘要，避免把整份日志塞进结果文件）。
    # M 组写入自己的臂目录 <CASE>/<arm>/<CASE>.json，禁止两臂覆盖同一案例文件；
    # 旧案例保持 <out>/<CASE>.json 的扁平路径，不破坏既有轮次目录。
    slim = dict(rec)
    job = slim.get("job") or {}
    slim["job"] = {"id": job.get("id"), "status": job.get("status"),
                   "live": job.get("live"), "desc": (job.get("desc") or "")[:120],
                   "logs": len(job.get("logs") or [])}
    record_dir = case_dir if rec.get("arm") else outdir
    os.makedirs(record_dir, exist_ok=True)
    with open(os.path.join(record_dir, f"{rec['case']}.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=2)
    return rec


# ---------------------------------------------------------------- 边界探针（零 LLM）
def run_boundaries(ctx, base_url, outdir):
    """真实浏览器边界探针：空需求/错误 Content-Type/空 desc/非法 mode/未知任务。"""
    out = {}
    page = ctx.new_page()
    try:
        page.goto(base_url + "/", wait_until="load")
        page.wait_for_selector("#desc")
        # 双模式：默认选中快速、切换后高保真、可回读当前档位
        out["mode_default"] = {
            "groupPresent": page.locator("[data-mode-group]").count() == 1,
            "checked": page.eval_on_selector(
                '[data-mode-group] input[name="mode"]:checked', "el => el ? el.value : null"),
        }
        page.click('[data-mode-option="fidelity"]')
        out["mode_switch"] = {
            "checked": page.eval_on_selector(
                '[data-mode-group] input[name="mode"]:checked', "el => el ? el.value : null"),
            "selectedClass": page.eval_on_selector(
                '[data-mode-option="fidelity"]', "el => el.className"),
        }
        page.click('[data-mode-option="fast"]')
        pages_before = page.evaluate("document.body.innerText.length")
        page.click("#go")  # 空需求：前端应直接忽略，不发起任务，不改变视图
        page.wait_for_timeout(800)
        out["empty_desc_submit"] = {
            "url": page.url,
            "noJob": "/?job=" not in page.url,
            "bodyUnchanged": abs(page.evaluate("document.body.innerText.length") - pages_before) < 50,
        }
        out["wrong_content_type"] = page.evaluate("""async () => {
            const r = await fetch('/api/build', {method: 'POST',
                headers: {'Content-Type': 'text/plain'}, body: '{"desc":"x"}'});
            return {status: r.status, body: (await r.text()).slice(0, 120)};
        }""")
        out["empty_desc_api"] = page.evaluate("""async () => {
            const r = await fetch('/api/build', {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({desc: '', mode: 'fidelity'})});
            return {status: r.status, body: (await r.text()).slice(0, 120)};
        }""")
        out["invalid_mode_api"] = page.evaluate("""async () => {
            const r = await fetch('/api/build', {method: 'POST',
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({desc: 'x', mode: 'nope'})});
            return {status: r.status, body: (await r.text()).slice(0, 120)};
        }""")
        out["unknown_job"] = page.evaluate("""async () => {
            const r = await fetch('/api/job/zzzzzzzz');
            return {status: r.status, body: (await r.text()).slice(0, 120)};
        }""")
        page.goto(base_url + "/jobs/zzzzzzzz?tab=overview", wait_until="load")
        page.wait_for_selector(".empty", timeout=15000)
        out["unknown_job_page"] = page.evaluate("""() => {
            const e = document.querySelector('.empty');
            return {text: (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
                    hasHistoryLink: !!e.querySelector('a[href="/history"]')};
        }""")
        out["unknown_job_screenshot"] = shot(page, os.path.join(outdir, "boundary-unknown-job.png"))
        page.goto(base_url + "/", wait_until="load")
        out["page_errors"] = page_errors(page)
    finally:
        page.close()
    return out


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="20 例复杂造型浏览器真实 LLM E2E 运行器")
    ap.add_argument("--base-url", default="http://127.0.0.1:8600")
    ap.add_argument("--cases", default="all", help="C01,C02 或 C01-C05 或 M01-M20 或 all")
    ap.add_argument("--modes", default=None,
                    help="M 组双模式臂（如 fast,fidelity）：每个 M 案例按奇偶交换顺序各跑一臂")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=2100, help="单例墙钟上限（秒）")
    ap.add_argument("--poll", type=float, default=5.0, help="轮询间隔（秒）")
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true", help="跳过 out 目录中已完成的案例")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--skip-boundaries", action="store_true")
    ap.add_argument("--allow-failures", action="store_true")
    ap.add_argument("--browser-path", default=None)
    args = ap.parse_args(argv)

    modes = None
    if args.modes:
        modes = tuple(x.strip() for x in args.modes.split(",") if x.strip())
    cases = parse_cases(args.cases, modes)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.abspath(args.out or os.path.join(ROOT, "artifacts", "e2e-20", stamp))
    os.makedirs(outdir, exist_ok=True)

    # 服务可用性自检（真实 HTTP，不含 LLM）
    import urllib.request

    try:
        with urllib.request.urlopen(args.base_url + "/api/parts", timeout=10) as r:
            if r.status != 200:
                raise RuntimeError(f"/api/parts HTTP {r.status}")
    except Exception as exc:  # noqa: BLE001
        log(f"❌ 服务不可用 {args.base_url}：{exc}")
        return 2

    from playwright.sync_api import sync_playwright

    def run_key(case):
        return case.get("runKey") or case["id"]

    results = {}
    if args.resume:
        for c in cases:
            p = record_path(outdir, c)
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        prior = json.load(f)
                except (OSError, ValueError):
                    continue
                # 只跳过“已真正跑完”的案例；提交失败/收尾异常没有任务结论，必须重跑。
                if prior.get("status") in ("done", "error", "cancelled", "interrupted"):
                    results[run_key(c)] = prior
                    log(f"↩ 跳过已完成 {run_key(c)}（resume）")
    todo = [c for c in cases if run_key(c) not in results]

    log(f"浏览器 E2E：{len(todo)}/{len(cases)} 例待跑，并发 {args.concurrency}，输出 {outdir}")
    launch_kwargs = {"headless": not args.headed}
    if args.browser_path:
        launch_kwargs["executable_path"] = args.browser_path
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN",
                                  timezone_id="Asia/Shanghai")
        active, pending = [], list(todo)
        while pending or active:
            while pending and len(active) < args.concurrency:
                case = pending.pop(0)
                case_dir = case_dir_for(outdir, case)
                os.makedirs(case_dir, exist_ok=True)
                key = run_key(case)
                try:
                    rec = start_case(ctx, args.base_url, case, outdir, args.timeout)
                    rec["baseUrl"] = args.base_url
                    rec["caseDir"] = case_dir
                    rec["runKey"] = key
                    active.append(rec)
                    mode_note = f" mode={case['arm']}" if case.get("arm") else ""
                    log(f"▶ {key} {case['name']}{mode_note} 已提交 job={rec['job_id']}")
                except Exception as exc:  # noqa: BLE001
                    log(f"❌ {key} 提交失败：{exc}")
                    results[key] = {
                        "case": case["id"], "runKey": key, "mode": case.get("arm"),
                        "name": case["name"], "status": "submit_failed",
                        "error": f"{exc}\n{traceback.format_exc()[:800]}",
                        "elapsedS": 0, "taskOk": False, "assertOk": False,
                    }
                    atomic_write_json(record_path(outdir, case), results[key])
            for rec in list(active):
                try:
                    finished = poll_case(rec, args.timeout)
                except Exception as exc:  # noqa: BLE001
                    log(f"❌ {rec.get('runKey') or rec['case']} 轮询异常，按失败收尾：{exc}")
                    rec["poll_fatal"] = str(exc)
                    finished = True
                if not finished:
                    continue
                active.remove(rec)
                key = rec.get("runKey") or rec["case"]
                try:
                    final_rec = finalize_case(rec, outdir, rec["caseDir"])
                    results[key] = final_rec
                except Exception as exc:  # noqa: BLE001
                    log(f"❌ {key} 收尾异常：{exc}")
                    final_rec = {k: rec.get(k) for k in ("case", "name", "job_id", "status",
                                                         "elapsedS", "timeout", "taskOk", "runId",
                                                         "runKey", "mode", "arm")}
                    final_rec.update({"finalizeError": f"{exc}\n{traceback.format_exc()[:800]}",
                                      "taskOk": False, "assertOk": False})
                    results[key] = final_rec
                    atomic_write_json(os.path.join(rec["caseDir"], f"{rec['case']}.json"), final_rec)
                m = final_rec.get("assertion", {}).get("metrics") or {}
                # 需求达标档形态兼容：C/H 是 dict；G 组 metrics 的 requirement_tier 是失败项列表，
                # 规模字段在 metrics 顶层（target_blocks/bricks/bricks_ratio）。
                tier = m.get("requirement_tier")
                tier = tier if isinstance(tier, dict) else {}
                bricks = m.get("pieces") if m.get("pieces") is not None else m.get("bricks")
                ratio = tier.get("bricks_ratio")
                if ratio is None:
                    ratio = m.get("bricks_ratio")
                log(f"✔ {key} 结束 status={final_rec.get('status')} "
                    f"outcome={final_rec.get('outcome')} taskOk={final_rec.get('taskOk')} "
                    f"assertOk={final_rec.get('assertOk')} "
                    f"部位={m.get('parts')} 体素={m.get('voxels')} "
                    f"零件={bricks} 目标比={_ratio_text(ratio)} "
                    f"耗时={(final_rec.get('elapsedFinal') or final_rec.get('elapsedS'))}s")
            if active:
                time.sleep(args.poll)

        boundaries = None
        if not args.skip_boundaries:
            try:
                boundaries = run_boundaries(ctx, args.base_url, outdir)
                log(f"边界探针：{json.dumps(boundaries, ensure_ascii=False)[:160]}…")
            except Exception as exc:  # noqa: BLE001
                boundaries = {"error": f"{exc}\n{traceback.format_exc()[:600]}"}
        browser.close()

    # ---------- 汇总 ----------
    all_results = []
    for c in cases:
        key = run_key(c)
        r = results.get(key)
        if r is None:
            p = record_path(outdir, c)
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        r = json.load(f)
                except (OSError, ValueError):
                    r = None
        if r is not None:
            all_results.append(r)

    def _rid(r):
        return r.get("runKey") or r.get("case")

    passed = [r for r in all_results if r.get("taskOk") and r.get("assertOk")]
    task_failed = [r for r in all_results if not r.get("taskOk")]
    assert_failed = [r for r in all_results if r.get("taskOk") and not r.get("assertOk")]
    case_tiers = [dict({"case": r.get("case"), "runKey": _rid(r),
                        "mode": r.get("mode") or None, "name": r.get("name")},
                       **_tier_fields(r)) for r in all_results]
    delivered = [t for t in case_tiers if t.get("bricks") is not None]
    target_met = [t for t in delivered if t.get("targetBlocksOk") is True]
    feature_met = [t for t in delivered if t.get("requirementOk")]
    summary = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "baseUrl": args.base_url,
        "outdir": outdir,
        "total": len(cases),
        "recorded": len(all_results),
        "passed": len(passed),
        "taskFailed": len(task_failed),
        "assertFailed": len(assert_failed),
        "failedIds": [_rid(r) for r in task_failed],
        "assertFailedIds": [_rid(r) for r in assert_failed],
        "modes": list(modes) if modes else None,
        # 复杂度分两层展示：需求达标档判失败；能力回归档只记录对比。
        "requirementTier": {
            "delivered": len(delivered),
            "targetBlocksMet": len(target_met),
            "requirementMet": len(feature_met),
            "targetRatioRule": "bricks/targetBlocks >= 0.5（冻结容差）",
            "baselineBricksRatioMedian": 0.29,
            "cases": case_tiers,
        },
        "regressionTier": {
            "note": "当前能力回归档只记录与 2026-11-02 基线（体素中位 650、预估 705、"
                    "体素/零件比 7.98）的对比，不参与失败判定",
            "baselineVoxelsMedian": 650,
            "baselinePlannedVoxelsMedian": 705,
            "baselineVoxelsPerPieceMedian": 7.98,
            "cases": case_tiers,
        },
        "boundaries": boundaries,
        "cases": [{
            "case": r.get("case"), "runKey": _rid(r), "mode": r.get("mode") or None,
            "name": r.get("name"), "jobId": r.get("job_id"),
            "runId": r.get("runId"), "status": r.get("status"), "outcome": r.get("outcome"),
            "taskOk": r.get("taskOk"), "assertOk": r.get("assertOk"),
            "elapsedS": r.get("elapsedFinal") or r.get("elapsedS"),
            "modeCheck": r.get("modeCheck"),
            "requirement": _tier_fields(r),
            "paths": {
                "json": os.path.relpath(record_path(outdir, {
                    "id": r.get("case"), "arm": r.get("mode") or r.get("arm")}), ROOT),
            },
        } for r in all_results],
    }
    atomic_write_json(os.path.join(outdir, "summary.json"), summary)
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# 浏览器真实 LLM E2E 汇总\n\n生成时间：{summary['generatedAt']}\n\n")
        f.write("| 案例 | 模式 | 名称 | job | run | 状态 | 结果 | 任务成功 | 断言通过 | 目标块数比 | 耗时(s) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in all_results:
            tier = _tier_fields(r)
            f.write(f"| {r.get('case')} | {r.get('mode') or '—'} | {r.get('name')} | `{r.get('job_id')}` | `{r.get('runId')}` | "
                    f"{r.get('status')} | {r.get('outcome')} | {r.get('taskOk')} | {r.get('assertOk')} | "
                    f"{_ratio_text(tier.get('bricksRatio'))} | "
                    f"{r.get('elapsedFinal') or r.get('elapsedS')} |\n")
        f.write(f"\n通过 {len(passed)}/{len(cases)}；任务失败 {summary['failedIds']}；"
                f"任务成功但断言未过 {summary['assertFailedIds']}\n")
        f.write("\n## 需求达标档（判失败）\n\n")
        f.write(f"目标块数比规则：{summary['requirementTier']['targetRatioRule']}；"
                f"有交付 {len(delivered)} 例中目标块数达标 {len(target_met)} 例，"
                f"断言全部达标 {len(feature_met)} 例。\n\n")
        f.write("| 案例 | 目标块数 | 实际零件 | 目标块数比 | 达标 |\n|---|---|---|---|---|\n")
        for t in case_tiers:
            f.write(f"| {t.get('case')} | {t.get('targetBlocks') if t.get('targetBlocks') else '—'} | "
                    f"{t.get('bricks') if t.get('bricks') is not None else '—'} | "
                    f"{_ratio_text(t.get('bricksRatio'))} | {t.get('targetBlocksOk')} |\n")
        f.write("\n## 当前能力回归档（只记录，不判失败）\n\n")
        f.write(f"基线：交付体素中位 650、规划预估中位 705、体素/零件比中位 7.98、"
                f"目标块数比中位 29%。\n\n")
        f.write("| 案例 | 体素/零件 | 基线体素/零件 | 最终门禁来源 | 最终门禁 | 版本覆盖 | 评审过期 |\n"
                "|---|---|---|---|---|---|---|\n")
        for t in case_tiers:
            f.write(f"| {t.get('case')} | {t.get('voxelsPerPiece') if t.get('voxelsPerPiece') is not None else '—'} | "
                    f"{t.get('baselineVoxelsPerPiece')} | {t.get('finalGateSource')} | "
                    f"{t.get('finalGateOk')} | {t.get('versionOverwrites')} | {t.get('reviewStale')} |\n")
    log(f"汇总：通过 {len(passed)}/{len(cases)}，任务失败 {summary['failedIds']}，"
        f"断言未过 {summary['assertFailedIds']}；输出 {outdir}")
    if summary["recorded"] < len(cases):
        log("⚠ 有案例未记录结果（运行中断？），汇总不完整")
        return 2
    ok = len(passed) == len(cases)
    return 0 if (ok or args.allow_failures) else 1


if __name__ == "__main__":
    sys.exit(main())
