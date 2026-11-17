# -*- coding: utf-8 -*-
"""真实 E2E 轮次分析器：旧 20 例 / 新增 G01–G10 / 合计 30 例分组汇总。

用法：
    python -m tools.e2e_analyze_full --round artifacts/e2e-20/20261103-0223-dev-full30

只读取运行目录里的单例 JSON 与 environment.json，不发起任何模型/网络请求。
输出 analysis.json 与 analysis.md（分组指标 + 逐例表 + 硬指标判定），供验收报告引用。
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OLD20 = ["H01", "H02", "H03", "H04", "H05", "H06", "H07", "H08", "H09", "H10",
         "C02", "C03", "C05", "C06", "C07", "C10", "C11", "C13", "C14", "C16"]
G10 = [f"G{i:02d}" for i in range(1, 11)]
DELIVERED_OUTCOMES = ("fidelity_success", "fidelity_degraded", "fast_fallback", "fast_success")


def _load_case(round_dir, case_id):
    path = os.path.join(round_dir, f"{case_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _page_errors(rec):
    """页面 JS 错误与 unhandledrejection 数量（真实浏览器取证）。"""
    ui = rec.get("console_errors") or []
    perr = rec.get("pageErrors") or {}
    n_err = len(ui) + len(perr.get("errors") or [])
    n_rej = len(perr.get("rejections") or [])
    return n_err, n_rej


def describe(rec):
    """把单例 JSON 压成分析用行（缺字段一律 None，不猜）。"""
    if rec is None:
        return {"recorded": False}
    result = rec.get("result") or {}
    metrics = (rec.get("assertion") or {}).get("metrics") or {}
    tier = metrics.get("requirement_tier")
    tier = tier if isinstance(tier, dict) else {}
    attempts = result.get("attempts_detail") or rec.get("attempts") or []
    reasons = []
    for a in attempts:
        failure = a.get("failure") or {}
        reasons.append({
            "mode": a.get("mode"), "ok": a.get("ok"),
            "kind": failure.get("kind"), "stage": failure.get("stage"),
            "error": str(a.get("error") or "")[:200],
        })
    n_err, n_rej = _page_errors(rec)
    bricks = metrics.get("pieces")
    if bricks is None:
        bricks = tier.get("bricks", metrics.get("bricks"))
    target = tier.get("target_blocks", metrics.get("target_blocks"))
    ratio = tier.get("bricks_ratio", metrics.get("bricks_ratio"))
    review = metrics.get("review_overall")
    if review is None:
        review = (result.get("review") or {}).get("scores", {}).get("overall")
    final_gate_ok = metrics.get("final_gate_ok")
    if final_gate_ok is None:
        fg = result.get("finalGateReplay")
        final_gate_ok = fg.get("ok") if isinstance(fg, dict) else None
    return {
        "recorded": True,
        "case": rec.get("case"),
        "name": rec.get("name"),
        "jobId": rec.get("job_id"),
        "runId": rec.get("runId"),
        "status": rec.get("status"),
        "outcome": rec.get("outcome") or result.get("outcome"),
        "taskOk": bool(rec.get("taskOk")),
        "assertOk": bool(rec.get("assertOk")),
        "elapsedS": rec.get("elapsedFinal") or rec.get("elapsedS"),
        "track": metrics.get("track") or result.get("track"),
        "parts": metrics.get("parts"),
        "solidParts": metrics.get("solid_parts"),
        "voxels": metrics.get("voxels"),
        "ops": metrics.get("ops"),
        "opsRecorded": metrics.get("ops_recorded"),
        "layers": metrics.get("layers"),
        "bricks": bricks,
        "targetBlocks": target,
        "bricksRatio": ratio,
        "reviewOverall": review,
        "reviewFlag": metrics.get("review_flag") or result.get("review_flag"),
        "gateDegraded": result.get("gate_failed"),
        "finalGateOk": final_gate_ok,
        "finalGateSource": metrics.get("final_gate_source"),
        "validationOk": metrics.get("validation_ok")
        if metrics.get("validation_ok") is not None else (result.get("validation") or {}).get("ok"),
        "versionOverwrites": metrics.get("version_overwrites"),
        "reviewStale": metrics.get("review_stale"),
        "scaleMetrics": result.get("scaleMetrics"),
        "chainOrder": result.get("chainOrder"),
        "quotaMode": result.get("quotaMode"),
        "structuralCandidates": result.get("structuralCandidates"),
        "quota": result.get("quota"),
        "attempts": reasons,
        "attemptCount": len(reasons),
        "mode": result.get("mode"),
        "error": result.get("error"),
        "pageJsErrors": n_err,
        "pageRejections": n_rej,
        "assertionErrors": (metrics.get("assertion_errors") or [])[:12],
        "evidence": {
            "single": f"{rec.get('case')}.json",
            "run": f"run_{rec.get('runId')}.json" if rec.get("runId") else None,
        },
    }


def _median(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(vals), 2) if vals else None


def summarize(rows):
    """按统一口径汇总一组案例。"""
    delivered = [r for r in rows if r.get("taskOk")]
    asserted = [r for r in rows if r.get("assertOk")]
    outcomes = {}
    for r in rows:
        key = r.get("outcome") or "failed"
        outcomes[key] = outcomes.get(key, 0) + 1
    quality = [r for r in rows if r.get("outcome") == "fidelity_success"]
    double_failed = [r for r in rows if not r.get("taskOk") and r.get("attemptCount", 0) >= 2]
    val_failed = [r for r in delivered if r.get("validationOk") is False]
    gate_degraded = [r for r in delivered if r.get("gateDegraded")]
    stale = [r for r in quality if r.get("reviewStale")]
    internal = [r for r in rows if str(r.get("error") or "").find("内部异常") >= 0]
    deadline = [r for r in rows if any((a.get("kind") == "deadline") for a in r.get("attempts") or [])]
    return {
        "total": len(rows),
        "recorded": sum(1 for r in rows if r.get("recorded")),
        "delivered": len(delivered),
        "asserted": len(asserted),
        "failed": len(rows) - len(delivered),
        "doubleAttemptFailed": len(double_failed),
        "doubleAttemptFailedIds": [r.get("case") for r in double_failed],
        "fidelitySuccess": len(quality),
        "fidelitySuccessIds": [r.get("case") for r in quality],
        "outcomes": outcomes,
        "medianBricksRatio": _median([r.get("bricksRatio") for r in delivered]),
        "medianVoxels": _median([r.get("voxels") for r in delivered]),
        "minBricksRatio": min([r["bricksRatio"] for r in delivered
                               if isinstance(r.get("bricksRatio"), (int, float))], default=None),
        "validationFailedIds": [r.get("case") for r in val_failed],
        "gateDegradedIds": [r.get("case") for r in gate_degraded],
        "reviewStaleIds": [r.get("case") for r in stale],
        "pageJsErrors": sum(int(r.get("pageJsErrors") or 0) for r in rows),
        "pageRejections": sum(int(r.get("pageRejections") or 0) for r in rows),
        "internalErrorIds": [r.get("case") for r in internal],
        "deadlineFailureIds": [r.get("case") for r in deadline],
        "versionOverwrites": sum(int(r.get("versionOverwrites") or 0) for r in rows),
        "finalGateMismatchIds": [r.get("case") for r in rows
                                 if r.get("finalGateOk") is False and r.get("assertOk")],
        "quantiles": {
            "elapsedMedian": _median([r.get("elapsedS") for r in rows]),
            "elapsedMax": max([r.get("elapsedS") for r in rows if isinstance(r.get("elapsedS"), (int, float))],
                              default=None),
        },
    }


def _fmt_ratio(value):
    return "—" if not isinstance(value, (int, float)) else f"{value:.1%}"


def write_markdown(path, data):
    env = data.get("environment") or {}
    lines = ["# 真实 E2E 轮次分析", "",
             f"- 轮次：{env.get('label')}；目录：`{data['roundDir']}`",
             f"- 时间：{env.get('startedAt')} → {env.get('finishedAt')}",
             f"- 代码 HEAD：`{env.get('codeHead')}`；工作区未提交：{env.get('worktreeDirty')}；"
             f"实际模型配置：`{env.get('modelConfigured')}`（env 覆盖：{env.get('modelEnvVar') or '无'}）",
             f"- 并发：{env.get('concurrency')}；单例墙钟上限：{env.get('timeoutS')}s；服务：{env.get('baseUrl')}", ""]
    for group_key, title in (("old20", "旧 20 例"), ("g10", "新增 G01–G10"), ("total30", "合计 30 例")):
        s = data["groups"][group_key]
        lines += [f"## {title}", "",
                  f"- 记录 {s['recorded']}/{s['total']}；任务完成 {s['delivered']}/{s['total']}；"
                  f"断言通过 {s['asserted']}/{s['total']}",
                  f"- 四态：{json.dumps(s['outcomes'], ensure_ascii=False)}",
                  f"- 双尝试失败 {s['doubleAttemptFailed']} / 目标"
                  + (" ≤5" if group_key == "old20" else "") + f"：{s['doubleAttemptFailedIds']}",
                  f"- 高保真成功 {s['fidelitySuccess']}：{s['fidelitySuccessIds']}",
                  f"- 实际/目标零件数中位：{_fmt_ratio(s['medianBricksRatio'])}；"
                  f"体素中位：{s['medianVoxels']}",
                  f"- 交付统一校验失败：{s['validationFailedIds']}；门禁降级：{s['gateDegradedIds']}",
                  f"- 过期高保真成功：{s['reviewStaleIds']}；版本覆盖数：{s['versionOverwrites']}",
                  f"- 页面 JS 错误：{s['pageJsErrors']}；unhandledrejection：{s['pageRejections']}",
                  f"- internal 失败：{s['internalErrorIds']}；deadline 失败：{s['deadlineFailureIds']}", ""]
    lines += ["## 逐例结果", "",
              "| 案例 | 名称 | 四态 | 任务 | 断言 | 耗时(s) | 部位 | 体素 | 零件/目标 | 目标比 | 视觉 | 页面JS | 失败类别 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in data["rows"]:
        kinds = "、".join(f"{a.get('mode')}:{a.get('kind') or 'ok'}" for a in r.get("attempts") or []) or "—"
        lines.append(f"| {r.get('case')} | {r.get('name')} | {r.get('outcome')} | {r.get('taskOk')} | "
                     f"{r.get('assertOk')} | {r.get('elapsedS')} | {r.get('parts')} | {r.get('voxels')} | "
                     f"{r.get('bricks')}/{r.get('targetBlocks')} | {_fmt_ratio(r.get('bricksRatio'))} | "
                     f"{r.get('reviewOverall')} | {r.get('pageJsErrors')} | {kinds} |")
    lines += ["", "## 证据路径", "",
              "- 每例单例 JSON（任务快照/四 Tab/页面错误/断言）：`<CASE>.json`",
              "- 每例 run JSON、模型、方案、拼装步骤：`<CASE>/evidence/`",
              "- 每例工作台/工作室/步骤/运行记录截图：`<CASE>/*.png`",
              "- 服务日志：`server.log`；环境快照：`environment.json`；浏览器汇总：`summary.json`/`summary.md`"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="真实 E2E 轮次分析（旧20/新增G/合计30 分组）")
    ap.add_argument("--round", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    round_dir = os.path.abspath(args.round)
    environment = {}
    env_path = os.path.join(round_dir, "environment.json")
    if os.path.isfile(env_path):
        try:
            with open(env_path, encoding="utf-8") as f:
                environment = json.load(f)
        except (OSError, ValueError):
            environment = {}
    rows = []
    missing = []
    for cid in OLD20 + G10:
        rec = _load_case(round_dir, cid)
        if rec is None:
            missing.append(cid)
            rows.append({"case": cid, "recorded": False})
            continue
        rows.append(describe(rec))
    by_case = {r["case"]: r for r in rows}
    groups = {
        "old20": summarize([by_case[c] for c in OLD20]),
        "g10": summarize([by_case[c] for c in G10]),
        "total30": summarize(rows),
    }
    data = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "roundDir": round_dir,
        "environment": environment,
        "missing": missing,
        "groups": groups,
        "rows": rows,
    }
    out_dir = args.out or round_dir
    with open(os.path.join(out_dir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    write_markdown(os.path.join(out_dir, "analysis.md"), data)
    print(f"[analyze] 记录 {groups['total30']['recorded']}/30，缺结果：{missing}")
    for key in ("old20", "g10", "total30"):
        s = groups[key]
        print(f"[analyze] {key}: 交付 {s['delivered']}/{s['total']}，断言 {s['asserted']}/{s['total']}，"
              f"四态 {json.dumps(s['outcomes'], ensure_ascii=False)}，"
              f"目标比中位 {_fmt_ratio(s['medianBricksRatio'])}")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
