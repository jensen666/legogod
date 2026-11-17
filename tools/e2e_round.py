# -*- coding: utf-8 -*-
"""真实 E2E 全量轮运行器（工作包验收协议的命令封装）。

职责（只做编排与取证，不改动被测代码）：
1. 记录环境快照：代码 HEAD、工作区差异、实际模型名、Python 版本、启动时间、并发、案例清单；
2. 启动真实 `python -m legogod <port>` 服务（使用 .env 真实配置，不注入 mock），等待就绪；
3. 调 `python -m tools.e2e_browser_20` 跑真实浏览器流程（真实 UI 提交 / 轮询 /api/job / 四 Tab）；
4. 停服并把每例的 run JSON、模型、方案、拼装步骤复制到 <out>/<CASE>/evidence/，便于离线复核；
5. 写出 environment.json 与 round-summary.md（含各例结果与证据路径）。

用法：
    python -m tools.e2e_round --label dev \
        --cases "H01-H10,C02,C03,C05,C06,C07,C10,C11,C13,C14,C16,G01-G10" \
        --concurrency 3 --out artifacts/e2e-20/<stamp>-full30
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def log(msg):
    """控制台可能是 GBK：打印失败不得把已经运行的任务打成崩溃。"""
    line = f"[e2e-round] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)


def _git(args):
    try:
        out = subprocess.check_output(["git"] + args, cwd=ROOT, stderr=subprocess.STDOUT)
        return out.decode("utf-8", "replace").strip()
    except Exception as exc:  # noqa: BLE001
        return f"(git 失败：{exc})"


def environment_snapshot(args, started_at):
    """记录可审计的环境事实（绝不记录 API Key）。"""
    env_model = os.environ.get("LEGOGOD_MODEL")
    model_file = ""
    try:
        from legogod.llm import config  # 延迟导入：避免未配置时启动失败
        cfg = config()
        model_file = cfg.get("model")
    except Exception as exc:  # noqa: BLE001
        model_file = f"(配置读取失败：{exc})"
    snap = {
        "label": args.label,
        "startedAt": started_at,
        "outdir": os.path.abspath(args.out),
        "cases": args.cases,
        "concurrency": args.concurrency,
        "timeoutS": args.timeout,
        "port": args.port,
        "baseUrl": f"http://127.0.0.1:{args.port}",
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "modelEnvVar": env_model,
        "modelConfigured": model_file,
        "codeHead": _git(["rev-parse", "HEAD"]),
        "codeBranch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "worktreeDirty": bool(_git(["status", "--porcelain"]).strip()),
        "worktreeStatus": _git(["status", "--porcelain"])[:4000],
        "frozenNote": args.frozen_note or "",
        # 单变量实验的环境开关（值空表示未设置，使用默认行为）
        # 2026-11-14 几何契约 A/B：LEGOGOD_GEOMETRY_CONTRACT 是唯一实验变量，必须逐轮留证。
        "experimentEnv": {name: os.environ.get(name)
                          for name in ("LEGOGOD_CHAIN_ORDER", "LEGOGOD_DYNAMIC_QUOTA",
                                       "LEGOGOD_STRUCT_CANDIDATES", "LEGOGOD_DYNAMIC_DRAW_BUDGET",
                                       "LEGOGOD_GEOMETRY_CONTRACT")},
    }
    return snap


def _wait_service(base_url, timeout_s=120):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/api/parts", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1)
    log(f"服务未就绪：{last}")
    return False


def _copy_evidence(outdir, case_id, record, arm=None):
    """把该例的 run/模型/方案/步骤文件复制进 <out>/<CASE>[/<arm>]/evidence/。"""
    dest = os.path.join(outdir, case_id, arm, "evidence") if arm else os.path.join(
        outdir, case_id, "evidence")
    os.makedirs(dest, exist_ok=True)
    copied = []
    run_id = record.get("runId") or (record.get("result") or {}).get("run_id")
    run_path = os.path.join(ROOT, "artifacts", f"run_{run_id}.json") if run_id else None
    if run_path and os.path.isfile(run_path):
        shutil.copy2(run_path, dest)
        copied.append(os.path.basename(run_path))
        try:
            with open(run_path, encoding="utf-8") as f:
                run = json.load(f)
        except (OSError, ValueError):
            run = {}
        for key, name in (run.get("artifacts") or {}).items():
            src = os.path.join(ROOT, "artifacts", name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dest, os.path.basename(name)))
                copied.append(os.path.basename(name))
    # 拼装步骤文档按 run_id 后 8 位匹配
    if run_id:
        for src in glob.glob(os.path.join(ROOT, "artifacts", f"拼装步骤_*_{run_id}.md")):
            shutil.copy2(src, dest)
            copied.append(os.path.basename(src))
    return copied


def _read_case_record(outdir, case_id, arm=None):
    path = (os.path.join(outdir, case_id, arm, f"{case_id}.json") if arm
            else os.path.join(outdir, f"{case_id}.json"))
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _summary_markdown(env, case_ids, records, outdir, modes=None):
    dual = bool(modes)
    lines = ["# 真实 E2E 轮次汇总", "",
             f"- 轮次标签：{env['label']}",
             f"- 开始时间：{env['startedAt']}；结束时间：{env['finishedAt']}",
             f"- 代码 HEAD：`{env['codeHead']}`；工作区有未提交改动：{env['worktreeDirty']}",
             f"- 实际模型配置：`{env['modelConfigured']}`（环境变量覆盖：{env['modelEnvVar'] or '无'}）",
             f"- 并发：{env['concurrency']}；单例墙钟上限：{env['timeoutS']}s；服务：{env['baseUrl']}",
             f"- 案例：{env['cases']}"]
    if dual:
        lines.append(f"- 双模式臂：{', '.join(modes)}（同一案例两臂相邻提交，奇偶案例交换先后）")
    lines += ["",
              "| 案例 | 模式 | 名称 | job | run | 状态 | 四态 | 任务成功 | 断言通过 | 耗时(s) | 体素 | 部位 | 视觉分 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    keys = [(cid, arm) for cid in case_ids for arm in (modes or [None])] if dual \
        else [(cid, None) for cid in case_ids]
    total = delivered = asserted = 0
    for cid, arm in keys:
        rec = (records.get((cid, arm)) if dual else records.get(cid)) or {}
        metrics = (rec.get("assertion") or {}).get("metrics") or {}
        result = rec.get("result") or {}
        ok = bool(rec.get("taskOk"))
        asserted_ok = bool(rec.get("assertOk"))
        delivered += 1 if ok else 0
        asserted += 1 if asserted_ok else 0
        total += 1
        review = metrics.get("review_overall")
        if review is None:
            review = (result.get("review") or {}).get("scores", {}).get("overall")
        review_text = "未评审" if (dual and arm == "fast") else review
        lines.append(f"| {cid} | {arm or '—'} | {rec.get('name')} | `{rec.get('job_id')}` | "
                     f"`{rec.get('runId')}` | {rec.get('status')} | {rec.get('outcome')} | "
                     f"{ok} | {asserted_ok} | "
                     f"{rec.get('elapsedFinal') or rec.get('elapsedS')} | {metrics.get('voxels')} | "
                     f"{metrics.get('parts')} | {review_text} |")
    lines += ["", f"任务完成 {delivered}/{total}；结果断言通过 {asserted}/{total}。", "",
              "原始证据：各例 `<CASE>.json`（任务快照/四 Tab/页面错误/断言）与 "
              "`<CASE>/evidence/`（run JSON、模型、方案、拼装步骤）、`<CASE>/*.png`（截图）。"]
    if dual:
        lines += ["", "双模式逐例对比与耗时/请求数统计见 `mode20-comparison.md`（由 "
                      "`python -m tools.e2e_mode20_report --round <本轮目录>` 生成）。"]
    path = os.path.join(outdir, "round-summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="真实 E2E 全量轮运行器（启动真实服务 + 真实浏览器 E2E + 取证）")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="dev")
    ap.add_argument("--port", type=int, default=8611)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=2100)
    ap.add_argument("--frozen-note", default="", help="冻结确认轮填写冻结说明（代码/断言冻结口径）")
    ap.add_argument("--modes", default=None,
                    help="双模式轮（如 fast,fidelity）：转发给浏览器执行器，按 <CASE>/<arm>/ 取证")
    ap.add_argument("--skip-boundaries", action="store_true")
    ap.add_argument("--no-server", action="store_true", help="复用外部已启动的服务（调试用）")
    ap.add_argument("--skip-run", action="store_true", help="只做取证/汇总（复用已有单例 JSON）")
    args = ap.parse_args(argv)

    outdir = os.path.abspath(args.out)
    os.makedirs(outdir, exist_ok=True)
    modes = [x.strip() for x in args.modes.split(",") if x.strip()] if args.modes else None
    case_ids = []
    for part in args.cases.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            prefix, lo_i, hi_i = lo[0].upper(), int(lo[1:]), int(hi[1:])
            case_ids += [f"{prefix}{i:02d}" for i in range(lo_i, hi_i + 1)]
        else:
            case_ids.append(part)
    started_at = datetime.now().isoformat(timespec="seconds")
    env = environment_snapshot(args, started_at)
    base_url = f"http://127.0.0.1:{args.port}"

    proc = None
    try:
        if not args.skip_run:
            if not args.no_server:
                log(f"启动真实服务（{base_url}）…")
                envlog = os.path.join(outdir, "server.log")
                handle = open(envlog, "w", encoding="utf-8")
                child_env = dict(os.environ)
                child_env["PYTHONIOENCODING"] = "utf-8"
                proc = subprocess.Popen([sys.executable, "-m", "legogod", str(args.port)],
                                        cwd=ROOT, env=child_env,
                                        stdout=handle, stderr=subprocess.STDOUT)
                proc._log_handle = handle  # noqa: SLF001
                if not _wait_service(base_url):
                    log("❌ 服务未就绪，终止本轮")
                    return 2
            cmd = [sys.executable, "-m", "tools.e2e_browser_20", "--base-url", base_url,
                   "--cases", args.cases, "--concurrency", str(args.concurrency),
                   "--timeout", str(args.timeout), "--out", outdir, "--allow-failures"]
            if modes:
                cmd += ["--modes", ",".join(modes)]
            if args.skip_boundaries:
                cmd.append("--skip-boundaries")
            log("运行：" + " ".join(cmd))
            code = subprocess.call(cmd, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            log(f"浏览器执行器退出码 {code}（--allow-failures：退出码 0 不代表验收通过）")
    finally:
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=20)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            handle = getattr(proc, "_log_handle", None)
            if handle is not None:
                try:
                    handle.close()
                except Exception:  # noqa: BLE001
                    pass
            log("服务已停止")

    env["finishedAt"] = datetime.now().isoformat(timespec="seconds")
    env["modes"] = modes
    records = {}
    keys = [(cid, arm) for cid in case_ids for arm in (modes or [None])] if modes \
        else [(cid, None) for cid in case_ids]
    for cid, arm in keys:
        rec = _read_case_record(outdir, cid, arm)
        if rec is None:
            records[(cid, arm) if modes else cid] = {}
            continue
        records[(cid, arm) if modes else cid] = rec
        if rec.get("runId"):
            copied = _copy_evidence(outdir, cid, rec, arm)
            rec["evidenceCopied"] = copied
    with open(os.path.join(outdir, "environment.json"), "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=1)
    path = _summary_markdown(env, case_ids, records, outdir, modes=modes)
    try:
        shown = os.path.relpath(path, ROOT)
    except ValueError:  # 跨盘符（如临时目录在 C:、项目在 D:）时 relpath 不可用
        shown = path
    log(f"轮次汇总：{shown}")
    recorded = sum(1 for k in keys if records.get(k))
    log(f"记录 {recorded}/{len(keys)} 例")
    missing = [f"{cid}-{arm}" if modes else cid for cid, arm in keys if not records.get((cid, arm) if modes else cid)]
    if missing:
        log(f"⚠ 缺结果：{missing}")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
