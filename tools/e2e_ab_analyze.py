# -*- coding: utf-8 -*-
"""配对 A/B 分析器：OFF/ON 两臂真实轮次目录 → 逐例对比 + 分组汇总 + 门槛判定。

用途：
    读取同模型、同案例的一批 `artifacts/e2e-20/<stamp>-ab-off` 与 `...-ab-on` 轮次目录，
    配对同一 case id，输出 `ab-analyze.json`（机器可读全量数据）与 `ab-report.md`
    （结论逐条带数字与证据路径），并逐项判定 通过/否决/无法判定。

用法：
    python -m tools.e2e_ab_analyze --off artifacts/e2e-20/xxx-ab-off \
        --on artifacts/e2e-20/xxx-ab-on [--out <dir>]
    python -m tools.e2e_ab_analyze --off <主轮>,[<追加轮>] --on <主轮>,[<追加轮>] ...
    python -m tools.e2e_ab_analyze --off d1 --on d2 --off-extra d3,d4 --on-extra d5

口径（冻结，测试可复现；报告内复述）：
  - `draw_requests` = `runRecord.drawAttempts[].request` 的**最大值**，无记录为 0
    （`request` 是累计编号而非增量，禁止求和）。
  - `review_overall` = run 记录 `review.scores.overall` 优先；旧记录没有该字段时用任务
    `result.review` 补入（补入情况逐例列证据路径）；两处都没有则保持空。
  - `final_gate` 以 run 记录 `finalGateReplay` 对最终模型的重放为准（旧记录后退
    `gateFailed` 过程标记）；`validation_ok` 取断言 metrics / 任务结果统一校验结论。
  - **support 类失败尝试**（每例计数，口径 `ab-support-v1`）：
      attempt = 一次“被拒绝的候选提交”或“一次求解失败”，按下列来源逐条计数：
        (1) `runRecord.rejections[]`：`kind` ∈ {support, connectivity, disconnected}
            或 `summary` 命中支撑正则 SUPPORT_KEYWORDS（支撑/悬空/unsupported/连成一体/
            不连通/互不相连/支撑或连接）→ 每条计 1；
        (2) `runRecord.failures[]`：`stage == "solve"` 且 `kind` ∈ {support, connectivity,
            disconnected} → 每条计 1；`stage` 以 `revise_` 开头的条目是“已接受修订”的触发
            记录而非失败尝试，不计；
        (3) 旧记录兼容：`rejections` 与 `failures` 字段都缺失时才看 `gateErrors` 文本，
            命中支撑正则整例计 1（报告标注来源）。
      `drawAttempts[].gateErrorCount/contractErrorCount` 与 `contractChecks[]` 只作佐证，
      不重复计入总数（避免同一次拒绝被两处字段重复统计）。两臂使用完全相同口径。
  - 契约拦截：`rejections[].kind == "contract"` 计事件数（缺失时退回
    `contractChecks[].violationCount > 0` 的检查条数）；拦截率 = 有违规检查条数 / 检查条数。
    拦截后修复成功 = 拦截后最终交付且最后一次契约检查无违规（无后续检查时按最终交付判定）。
    误伤可疑 = 契约自身异常（contract_error）或“被拦后最终交付且全部断言通过”或
    “规模契约预判不达标但最终目标块数达标”，逐例列原因，仅供人工复核，不自动否决。
  - 门槛判定见 evaluate_gates()；单轮目录照常输出，全文标注「单轮初筛」；同臂多轮目录时
    逐例先取多轮中位（布尔取多数、并列取主轮），再汇总。

退出码：0 = 分析完成且无门槛 FAIL；1 = 分析完成但存在门槛 FAIL；2 = 参数/目录错误。
"""
import argparse
import glob
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 冻结的 P 组 10 例（其余参与案例归 R 组；可用 --p-cases 覆盖）。
DEFAULT_P_CASES = ("H01", "C02", "C03", "C14", "N04", "N07", "N12", "N14", "N15", "N16")

SUPPORT_KEYWORDS = re.compile(
    r"支撑|悬空|unsupported|连成一体|不连通|互不相连|支撑或连接", re.IGNORECASE)
SUPPORT_KINDS = {"support", "connectivity", "disconnected"}
CONTRACT_KINDS_OF_INTEREST = {"support", "connectivity", "scale", "contract_error"}
GENERIC_ERROR_PREFIXES = (
    "运行未成功", "最终门禁重放未通过", "突显门禁带记录降级", "统一校验未通过",
    "最终版本产物缺失", "规模指标不同源", "最终产物评审已过期",
)
GATE_IDS = ("trust", "delivery", "requirement", "structure", "cost", "mechanism")
GATE_TITLES = {
    "trust": "可信底线", "delivery": "任务交付", "requirement": "需求正确性",
    "structure": "结构收益", "cost": "成本", "mechanism": "机制证据",
}
SUPPORT_DEFINITION = (
    "attempt=被拒绝候选提交或求解失败；来源与判定：(1) rejections[] 的 kind∈"
    "{support,connectivity,disconnected} 或 summary 命中支撑正则 SUPPORT_KEYWORDS；"
    "(2) failures[] 中 stage=='solve' 且 kind∈{support,connectivity,disconnected}；"
    "stage 以 revise_ 开头的条目是已接受修订的触发记录，不计；(3) rejections 与 failures "
    "字段都缺失时退回 gateErrors 文本整例计 1。drawAttempts[].gateErrorCount/"
    "contractErrorCount 与 contractChecks[] 只作佐证不重复计。两臂同一口径（ab-support-v1）。"
)


# ---------------------------------------------------------------- 通用小工具
def _load_json(path):
    """读取 JSON；失败返回 (None, 错误文本)，绝不抛异常（缺字段/旧记录不崩溃）。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _rel(path):
    """工作区内路径转相对路径，便于报告引用；失败退回原文。"""
    try:
        return os.path.relpath(path, ROOT).replace(os.sep, "/")
    except ValueError:
        return str(path)


def _median(values):
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return statistics.median(vals) if vals else None


def _mean(values):
    vals = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return round(sum(vals) / len(vals), 2) if vals else None


def _ratio(num, den):
    if num is None or not den:
        return None
    return round(num / float(den), 4)


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _first(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _fmt(value):
    """报告单元格格式化：空值统一写 —（未知），禁止用猜测数字填充。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 100 else f"{value:.1f}"
    return str(value)


def _pct(value):
    if value is None:
        return "无法判定"
    return f"{value * 100:.1f}%"


def _short_head(head):
    return (head[:8] + "…") if isinstance(head, str) and len(head) > 8 else (head or "—")


# ---------------------------------------------------------------- 单例字段提取
def draw_request_count(attempts):
    """draw 请求数 = drawAttempts[].request 累计编号的最大值（空/非法为 0）。"""
    best = 0
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        value = _as_int(attempt.get("request"))
        if value is not None and value > best:
            best = value
    return best


def _draw_requests(run_record, metrics):
    """返回 (draw_requests, 来源说明)；run 记录优先，旧记录缺字段时回退 metrics 并标注。"""
    if isinstance(run_record, dict) and "drawAttempts" in run_record:
        attempts = run_record.get("drawAttempts")
        if isinstance(attempts, list):
            return draw_request_count(attempts), "runRecord.drawAttempts.max"
        return None, None
    fallback = (metrics or {}).get("draw_requests")
    value = _as_int(fallback)
    if value is not None:
        return value, "metrics.draw_requests（旧求和口径回退，需复核）"
    return None, None


def _review_state(run_record, result, metrics):
    """评审来源：run 记录优先 → result.review 补入 → 断言 metrics；返回 (review, source)。"""
    if isinstance(run_record, dict):
        review = run_record.get("review")
        if isinstance(review, dict) and review:
            return review, "run_record"
    result = result or {}
    review = result.get("review")
    if isinstance(review, dict) and review:
        return review, "task_result"
    metrics = metrics or {}
    review = metrics.get("review")
    if isinstance(review, dict) and review:
        return review, "assertion_metrics"
    return {}, None


def _review_overall(review, metrics):
    scores = (review or {}).get("scores")
    scores = scores if isinstance(scores, dict) else {}
    value = scores.get("overall")
    if value is not None:
        return value
    return (metrics or {}).get("review_overall")


def _review_absence_reason(result, metrics):
    """交付但无评审时的可解释原因；没有可核对原因返回 None（判为记录缺失）。"""
    result = result or {}
    metrics = metrics or {}
    flag = _first(result.get("review_flag"), result.get("reviewFlag"),
                  metrics.get("review_flag"))
    if flag == "review_unavailable" or result.get("review_unavailable") is True:
        return "视觉评审不可用（review_unavailable）"
    if result.get("review_failed") is True or flag == "review_failed":
        return "视觉评审失败（review_failed）"
    outcome = str(_first(result.get("outcome"), result.get("status"), "") or "")
    if outcome.startswith("fast_"):
        return f"快路径交付（outcome={outcome}），未触发视觉评审"
    return None


def _final_gate_state(run_record, result, metrics):
    """最终门禁：返回 (source, ok, replay 字段是否存在, replay dict)。

    口径同 tools/e2e_assert.final_gate_state：有 finalGateReplay 只认重放，
    旧记录退回 gateFailed 过程标记；任何字段缺失都如实返回 None（不猜测）。
    """
    if isinstance(run_record, dict):
        if "finalGateReplay" in run_record:
            replay = run_record.get("finalGateReplay")
            if isinstance(replay, dict):
                return "replay", replay.get("ok"), True, replay
            return "replay", None, True, None
        if run_record.get("gateFailed") or run_record.get("gate_failed"):
            return "legacy", False, False, None
        return "legacy", True, False, None
    metrics = metrics or {}
    source = metrics.get("final_gate_source")
    if source:
        replay = metrics.get("final_gate_replay")
        return (source, metrics.get("final_gate_ok"),
                bool(metrics.get("final_gate_replay_field_present")),
                replay if isinstance(replay, dict) else None)
    replay = metrics.get("final_gate_replay")
    if isinstance(replay, dict):
        return "replay", replay.get("ok"), True, replay
    if "final_gate_replay" in metrics:
        return "replay", None, True, None
    result = result or {}
    if "finalGateReplay" in result:
        replay = result.get("finalGateReplay")
        if isinstance(replay, dict):
            return "replay", replay.get("ok"), True, replay
        return "replay", None, True, None
    gate_failed = result.get("gate_failed")
    if gate_failed is not None:
        return "legacy", not bool(gate_failed), False, None
    return None, None, False, None


def _is_generic_error(text):
    return str(text).startswith(GENERIC_ERROR_PREFIXES)


def _requirement_state(metrics, task_ok):
    """需求达标档结论（与通用底线分离）；返回 dict(ok/evaluated/failures/source)。

    C/H 的 requirement_tier 是 dict（含结构化子项，errors 里混有通用底线失败，故只取
    require_parts/feature_checks/complexity/target_blocks_ok 这些需求层子项）；
    G/N 的 requirement_tier 是失败项列表；缺失时退回 assertion_ok 并标注“无法拆分”。
    """
    metrics = metrics if isinstance(metrics, dict) else {}
    if task_ok is not True:
        return {"ok": None, "evaluated": False, "failures": [],
                "source": None, "reason": "任务未成功，需求断言未执行"}
    tier = metrics.get("requirement_tier")
    if isinstance(tier, list):
        failures = [str(x) for x in tier]
        return {"ok": not failures, "evaluated": True, "failures": failures,
                "source": "requirement_tier(list)"}
    if isinstance(tier, dict):
        structured = any(key in tier for key in
                         ("require_parts", "feature_checks", "complexity", "target_blocks_ok"))
        if structured:
            failures = []
            parts = tier.get("require_parts") or {}
            failures.extend(str(x) for x in (parts.get("errors") or []))
            for check in tier.get("feature_checks") or []:
                if isinstance(check, dict) and check.get("ok") is False:
                    failures.extend(str(x) for x in (check.get("errors") or []))
            complexity = tier.get("complexity") or {}
            for key, label in (("parts", "部位数"), ("solid_parts", "立体部位数"),
                               ("voxels", "体素数"), ("ops", "算子数")):
                item = complexity.get(key) or {}
                if item.get("ok") is False:
                    failures.append(f"复杂度未达设计下限：{label} "
                                    f"{item.get('actual')} < {item.get('required')}")
            if tier.get("target_blocks_ok") is False:
                failures.append(f"目标块数未达标：{tier.get('bricks')} / "
                                f"{tier.get('target_blocks')}（bricks/targetBlocks < 0.5）")
            if not failures and tier.get("ok") is False:
                failures = [str(x) for x in (tier.get("errors") or [])
                            if not _is_generic_error(x)]
                if not failures:
                    return {"ok": None, "evaluated": True, "failures": [],
                            "source": "requirement_tier(dict)",
                            "reason": "需求达标档判失败但无法定位需求层失败项"}
            return {"ok": not failures, "evaluated": True, "failures": failures,
                    "source": "requirement_tier(dict)"}
        errors = [str(x) for x in (tier.get("errors") or []) if not _is_generic_error(x)]
        if "errors" in tier:
            return {"ok": not errors, "evaluated": True, "failures": errors,
                    "source": "requirement_tier.errors(旧结构)"}
    assertion_ok = _as_bool(metrics.get("assertion_ok"))
    if assertion_ok is not None:
        return {"ok": assertion_ok, "evaluated": True, "failures": [],
                "source": "assertion_ok 回退（旧记录无法拆分需求层）"}
    return {"ok": None, "evaluated": False, "failures": [], "source": None,
            "reason": "缺少 requirement_tier/assertion_ok，需求断言结论无法判定"}


def _support_attempts(run_record):
    """support 类失败尝试计数（口径 ab-support-v1，见模块文档与 SUPPORT_DEFINITION）。"""
    state = {"total": None, "rejections": None, "solveFailures": None,
             "gateErrorsFallback": None, "evidence": [],
             "contractChecksSupport": None, "drawGateErrorAttempts": None,
             "drawContractErrorAttempts": None, "basis": None, "nonContractTotal": None}
    if not isinstance(run_record, dict) or not run_record:
        return state
    rejections = run_record.get("rejections")
    failures = run_record.get("failures")
    gate_errors = _first(run_record.get("gateErrors"), run_record.get("gate_errors"))
    has_rejections = isinstance(rejections, list)
    has_failures = isinstance(failures, list)
    total, evidence = 0, []
    contract_rejections = 0
    if has_rejections:
        for idx, item in enumerate(rejections):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            summary = str(item.get("summary") or "")
            if kind == "contract":
                contract_rejections += 1
            hit = kind in SUPPORT_KINDS or bool(SUPPORT_KEYWORDS.search(summary))
            if hit:
                total += 1
                evidence.append(f"rejections[{idx}] kind={kind or '?'} "
                                f"{(SUPPORT_KEYWORDS.search(summary).group(0) if SUPPORT_KEYWORDS.search(summary) else '')}"
                                f" phase={item.get('phase')} request={item.get('request')}")
        state["rejections"] = total
    if has_failures:
        solve_hits = 0
        for idx, item in enumerate(failures):
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            stage = str(item.get("stage") or "")
            if kind not in SUPPORT_KINDS:
                continue
            if stage.startswith("revise_"):
                continue  # 已接受修订的触发记录，不是失败尝试
            solve_hits += 1
            evidence.append(f"failures[{idx}] kind={kind} stage={stage or '?'}")
        state["solveFailures"] = solve_hits
        total += solve_hits
    fallback = 0
    if not has_rejections and not has_failures and gate_errors:
        if any(SUPPORT_KEYWORDS.search(str(e)) for e in gate_errors):
            fallback = 1
            evidence.append("gateErrors[] 文本命中支撑正则（旧记录兼容回退整例计 1）")
    state["gateErrorsFallback"] = fallback
    total += fallback
    checks = run_record.get("contractChecks")
    if isinstance(checks, list):
        state["contractChecksSupport"] = sum(
            1 for c in checks if isinstance(c, dict)
            and set(c.get("kinds") or []) & {"support", "connectivity"})
    attempts = run_record.get("drawAttempts")
    if isinstance(attempts, list):
        state["drawGateErrorAttempts"] = sum(
            1 for a in attempts if isinstance(a, dict) and (_as_int(a.get("gateErrorCount")) or 0) > 0)
        state["drawContractErrorAttempts"] = sum(
            1 for a in attempts if isinstance(a, dict) and (_as_int(a.get("contractErrorCount")) or 0) > 0)
    state["total"] = total
    state["nonContractTotal"] = max(0, total - contract_rejections)
    state["evidence"] = evidence[:8]
    state["basis"] = "ab-support-v1"
    return state


def _contract_state(run_record, metrics, task_ok, assert_ok, bricks_ratio):
    """契约机制逐例证据：检查次数/违规次数/类型/拦截次数/修复/误伤可疑。"""
    state = {"checks": None, "flaggedChecks": None, "violations": None, "kinds": [],
             "intercepts": None, "interceptBasis": None, "rejectedRequests": [],
             "intercepted": None, "repaired": None, "repairBasis": None,
             "suspect": False, "suspectReasons": [], "contractErrorEvents": None,
             "drawContractErrorAttempts": None, "drawGateErrorAttempts": None}
    if not isinstance(run_record, dict) or not run_record:
        return state
    checks = run_record.get("contractChecks")
    if isinstance(checks, list):
        state["checks"] = len(checks)
        flagged = [c for c in checks
                   if isinstance(c, dict) and (_as_int(c.get("violationCount")) or 0) > 0]
        state["flaggedChecks"] = len(flagged)
        state["violations"] = sum((_as_int(c.get("violationCount")) or 0) for c in checks
                                  if isinstance(c, dict))
        kinds = set()
        contract_errors = 0
        for c in checks:
            if not isinstance(c, dict):
                continue
            for kind in c.get("kinds") or []:
                kinds.add(str(kind))
            if "contract_error" in (c.get("kinds") or []):
                contract_errors += 1
        state["kinds"] = sorted(kinds)
        state["contractErrorEvents"] = contract_errors
        intercepts, basis = None, None
        rejections = run_record.get("rejections")
        if isinstance(rejections, list):
            contract_rejections = [r for r in rejections
                                   if isinstance(r, dict) and str(r.get("kind")) == "contract"]
            intercepts = len(contract_rejections)
            basis = "runRecord.rejections(kind=contract)"
            state["rejectedRequests"] = [
                f"{r.get('phase')}#{r.get('request')}" for r in contract_rejections]
        elif state["flaggedChecks"] is not None:
            intercepts = state["flaggedChecks"]
            basis = "contractChecks(violationCount>0)（rejections 缺失回退）"
        state["intercepts"] = intercepts
        state["interceptBasis"] = basis
        state["intercepted"] = None if intercepts is None else intercepts > 0
        if state["intercepted"]:
            last_idx = max(i for i, c in enumerate(checks)
                           if isinstance(c, dict)
                           and (_as_int(c.get("violationCount")) or 0) > 0)
            delivered = task_ok is True
            last_check = checks[-1] if isinstance(checks[-1], dict) else {}
            final_clean = (_as_int(last_check.get("violationCount")) or 0) == 0
            if not delivered:
                state["repaired"] = False
                state["repairBasis"] = "拦截后任务未交付（无最终产物可判修复）"
            elif final_clean:
                state["repaired"] = True
                state["repairBasis"] = (f"拦截后最终契约检查无违规"
                                        f"（后续检查 {len(checks) - 1 - last_idx} 次）")
            else:
                state["repaired"] = False
                state["repairBasis"] = "最终一次契约检查仍有违规（未修复）"
    attempts = run_record.get("drawAttempts")
    if isinstance(attempts, list):
        state["drawContractErrorAttempts"] = sum(
            1 for a in attempts if isinstance(a, dict)
            and (_as_int(a.get("contractErrorCount")) or 0) > 0)
        state["drawGateErrorAttempts"] = sum(
            1 for a in attempts if isinstance(a, dict)
            and (_as_int(a.get("gateErrorCount")) or 0) > 0)
    reasons = []
    if (state["contractErrorEvents"] or 0) > 0:
        reasons.append("契约检查自身异常（fail-open 后按通过处理）")
    if state["intercepted"] and task_ok is True and assert_ok is True:
        reasons.append("拦截后仍全断言通过：被拦草稿缺陷无法离线复核，需人工看草稿")
    if "scale" in state["kinds"] and bricks_ratio is not None and bricks_ratio >= 0.5:
        reasons.append("规模契约预判不达标但最终目标块数达标")
    state["suspectReasons"] = reasons
    state["suspect"] = bool(reasons)
    return state


def _artifact_state(run_record, result, metrics):
    """产物一致性：最终版本 model/solution/md 齐全 + 规模指标同源；返回 (ok, 说明)。"""
    result = result or {}
    metrics = metrics or {}
    if isinstance(run_record, dict) and run_record:
        revision = run_record.get("revision")
        artifacts = run_record.get("artifacts")
        if isinstance(revision, int) and isinstance(artifacts, dict) and artifacts:
            rev = f"r{revision:03d}"
            missing = [f"{prefix}{rev}" for prefix in ("model_", "solution_", "md_")
                       if f"{prefix}{rev}" not in artifacts]
            if missing:
                return False, f"最终版本产物缺失 {missing}"
            tier = metrics.get("requirement_tier")
            tier = tier if isinstance(tier, dict) else {}
            consistency = tier.get("scale_metrics_consistent")
            if isinstance(consistency, dict) and consistency.get("ok") is False:
                return False, "规模指标不同源：" + "；".join(consistency.get("problems") or [])
            return True, "产物齐全且规模指标同源"
        return None, "run 记录缺少 revision/artifacts，无法核对产物"
    validation = result.get("validation")
    if isinstance(validation, dict):
        return (bool(validation.get("ok")), "按任务结果统一校验回退核对（无 run 记录）")
    return None, "缺少 run 记录与任务结果，产物一致性无法判定"


def extract_case(case_path, round_env, p_cases):
    """读取单例 `<CASE>.json` 并提取对比所需全部字段（缺字段记录到 fieldsMissing）。"""
    raw, load_error = _load_json(case_path)
    case_id = os.path.splitext(os.path.basename(case_path))[0]
    record = {"case": case_id, "caseJson": _rel(case_path), "present": raw is not None,
              "loadError": load_error, "roundDir": _rel(os.path.dirname(case_path)),
              "fieldsMissing": [], "runRecordSource": None, "runRecordPath": None}
    if not isinstance(raw, dict):
        record["fieldsMissing"].append("case JSON 读取失败")
        return record
    case_id = str(raw.get("case") or case_id)
    record["case"] = case_id
    record["suite"] = "P" if case_id.upper() in p_cases else "R"
    record["name"] = raw.get("name")
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    metrics = (raw.get("assertion") or {}).get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    run_record = raw.get("runRecord") if isinstance(raw.get("runRecord"), dict) else None
    run_record_source = "case.runRecord" if run_record else None
    run_id = str(_first(raw.get("runId"), result.get("run_id"), metrics.get("run_id")) or "") or None
    if not run_record and run_id:
        for candidate in (os.path.join(os.path.dirname(case_path), "evidence",
                                       f"run_{run_id}.json"),
                          os.path.join(ROOT, "artifacts", f"run_{run_id}.json")):
            if os.path.isfile(candidate):
                run_record, err = _load_json(candidate)
                if isinstance(run_record, dict):
                    run_record_source = _rel(candidate)
                    record["runRecordPath"] = _rel(candidate)
                    break
                run_record = None
    record["runRecordSource"] = run_record_source
    if run_record is None and run_id:
        record["fieldsMissing"].append("run 记录缺失（drawAttempts/rejections/contractChecks 无法核对）")

    task_ok = _as_bool(raw.get("taskOk"))
    if task_ok is None:
        task_ok = _as_bool(result.get("ok"))
    if task_ok is None:
        task_ok = _as_bool(metrics.get("task_ok"))
    assert_ok = _as_bool(raw.get("assertOk"))
    if assert_ok is None:
        assert_ok = _as_bool(metrics.get("assertion_ok"))
    if task_ok is False:
        assert_ok = False
    status = _first(raw.get("status"), result.get("status"), metrics.get("status"))
    outcome = _first(raw.get("outcome"), result.get("outcome"), metrics.get("outcome"))

    requirement = _requirement_state(metrics, task_ok)
    assertion_errors = metrics.get("assertion_errors")
    assertion_errors = [str(x) for x in assertion_errors] if isinstance(assertion_errors, list) else []
    draw_requests, draw_source = _draw_requests(run_record, metrics)
    attempts = (run_record or {}).get("drawAttempts")
    draw_attempts = len(attempts) if isinstance(attempts, list) else _as_int(metrics.get("draw_attempts"))

    review, review_source = _review_state(run_record, result, metrics)
    review_overall = _review_overall(review, metrics)
    review_absent_reason = None
    if review_overall is None and task_ok is True:
        review_absent_reason = _review_absence_reason(result, metrics)
        if review_absent_reason is None:
            record["fieldsMissing"].append("交付例缺少视觉分且无不可用说明（记录不完整）")
    gate_source, gate_ok, replay_present, replay = _final_gate_state(run_record, result, metrics)
    if gate_source is None and task_ok is True:
        record["fieldsMissing"].append("最终门禁结论缺失")

    tier = metrics.get("requirement_tier")
    tier = tier if isinstance(tier, dict) else {}
    target_blocks = _first(metrics.get("target_blocks"), tier.get("target_blocks"),
                           ((run_record or {}).get("scaleMetrics") or {}).get("targetBlocks")
                           if isinstance((run_record or {}).get("scaleMetrics"), dict) else None,
                           ((result.get("scaleMetrics") or {}).get("targetBlocks")
                            if isinstance(result.get("scaleMetrics"), dict) else None))
    bricks = _first(metrics.get("pieces"), metrics.get("bricks"), result.get("pieces"),
                    tier.get("bricks"))
    bricks_ratio = _first(metrics.get("bricks_ratio"), tier.get("bricks_ratio"))
    target_blocks, bricks = _as_int(target_blocks), _as_int(bricks)
    if bricks_ratio is None and target_blocks and bricks is not None:
        bricks_ratio = round(bricks / float(target_blocks), 4)

    validation = _first(metrics.get("validation_ok"),
                        (result.get("validation") or {}).get("ok")
                        if isinstance(result.get("validation"), dict) else None)
    version_overwrites = _first((run_record or {}).get("versionOverwriteCount"),
                                metrics.get("version_overwrites"),
                                result.get("versionOverwriteCount"))
    review_stale = _first((run_record or {}).get("reviewStale"), metrics.get("review_stale"),
                          result.get("reviewStale"), result.get("review_stale"))
    review_hash_missing = _first((run_record or {}).get("reviewHashMissing"),
                                 metrics.get("review_hash_missing"),
                                 result.get("reviewHashMissing"))
    artifact_ok, artifact_note = _artifact_state(run_record, result, metrics)
    page_errors = raw.get("pageErrors")
    if isinstance(page_errors, dict):
        page_errors_count = sum(len(page_errors.get(key) or [])
                                for key in ("errors", "rejections"))
    else:
        page_errors_count = None
    console = raw.get("console_errors")
    console_errors_count = len(console) if isinstance(console, list) else None
    screenshots = raw.get("screenshots")
    screenshot_count = (len([s for s in screenshots if isinstance(s, str)
                             and not s.startswith("screenshot failed")])
                        if isinstance(screenshots, list) else None)
    failures = (run_record or {}).get("failures") or []
    internal = (any(isinstance(f, dict) and str(f.get("kind")) == "internal"
                    for f in failures if isinstance(failures, list))
                or str(status) == "internal" or str(outcome) == "internal"
                or str((result.get("failure") or {}).get("kind")) == "internal")

    contract = _contract_state(run_record, metrics, task_ok, assert_ok, bricks_ratio)
    support = _support_attempts(run_record)
    elapsed = _first(raw.get("elapsedFinal"), raw.get("elapsedS"),
                     (run_record or {}).get("elapsedS"))
    if elapsed is not None:
        try:
            elapsed = round(float(elapsed), 1)
        except (TypeError, ValueError):
            elapsed = None
    env = {"codeHead": round_env.get("codeHead"),
           "codeHeadShort": _short_head(round_env.get("codeHead")),
           "label": round_env.get("label"), "switch": round_env.get("switch")}
    record.update({
        "runId": run_id, "status": status, "outcome": outcome,
        "taskOk": task_ok, "assertOk": assert_ok,
        "assertionExecuted": bool(metrics),
        "requirement_ok": requirement.get("ok"),
        "requirement_evaluated": requirement.get("evaluated"),
        "requirement_source": requirement.get("source"),
        "requirement_failures": requirement.get("failures") or [],
        "requirement_reason": requirement.get("reason"),
        "assertion_errors_count": len(assertion_errors),
        "assertion_error_samples": assertion_errors[:3],
        "draw_requests": draw_requests, "draw_requests_source": draw_source,
        "draw_attempts": draw_attempts,
        "elapsed": elapsed,
        "voxels": _first(metrics.get("voxels"), result.get("voxels")),
        "parts": _first(metrics.get("parts"),
                        (result.get("counts") or {}).get("parts")
                        if isinstance(result.get("counts"), dict) else None),
        "bricks": bricks, "target_blocks": target_blocks, "bricks_ratio": bricks_ratio,
        "review_overall": review_overall, "review_source": review_source,
        "review_absent_reason": review_absent_reason,
        "final_gate_source": gate_source, "final_gate_ok": gate_ok,
        "final_gate_replay_present": replay_present,
        "final_gate_replay_errors": [str(e) for e in (replay or {}).get("errors") or []][:2],
        "validation_ok": validation,
        "versionOverwrites": _as_int(version_overwrites),
        "reviewStale": _as_bool(review_stale),
        "reviewHashMissing": _as_bool(review_hash_missing),
        "artifact_ok": artifact_ok, "artifact_note": artifact_note,
        "page_errors": page_errors_count, "console_errors": console_errors_count,
        "screenshots": screenshot_count, "internal": bool(internal),
        "contract": contract, "support": support, "env": env,
    })
    # 数值字段缺失时列入无法核对清单（只在交付例上强制要求规模/视觉字段）
    for key, label in (("voxels", "体素数"), ("parts", "部位数"), ("bricks", "零件数")):
        if record.get(key) is None and task_ok is True:
            record["fieldsMissing"].append(f"交付例缺少{label}")
    return record


# ---------------------------------------------------------------- 轮次与多轮聚合
def parse_case_ids(spec):
    """解析环境/CLI 的案例清单：支持 `H01,C02` 与区间 `C02-C14`（同前缀）。"""
    out, seen = [], set()
    for part in str(spec or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and len(part.split("-")[0]) >= 2:
            lo, hi = [x.strip() for x in part.split("-", 1)]
            prefix = lo[0].upper()
            try:
                lo_i, hi_i = int(lo[1:]), int(hi[1:])
            except ValueError:
                continue
            for i in range(lo_i, hi_i + 1):
                cid = f"{prefix}{i:02d}"
                if cid not in seen:
                    seen.add(cid)
                    out.append(cid)
        elif part not in seen:
            seen.add(part)
            out.append(part)
    return out


def infer_switch(env, arm):
    """推断实验开关 LEGOGOD_GEOMETRY_CONTRACT 的取值与来源（环境记录优先）。"""
    experiment = env.get("experimentEnv") if isinstance(env.get("experimentEnv"), dict) else {}
    raw = experiment.get("LEGOGOD_GEOMETRY_CONTRACT")
    if raw is None:
        raw = env.get("LEGOGOD_GEOMETRY_CONTRACT")
    if raw is not None:
        return {"value": str(raw).strip().lower(), "source": "environment.json.experimentEnv",
                "confidence": "记录值"}
    text = f"{env.get('label') or ''} {os.path.basename(str(env.get('outdir') or ''))}"
    match = (re.search(r"(?:^|[-_])ab[-_](off|on)(?:$|[-_])", text, re.IGNORECASE)
             or re.search(r"(?:^|[-_])(off|on)(?:$|[-_])", text, re.IGNORECASE))
    if match:
        return {"value": match.group(1).lower(), "source": "目录/标签名推断",
                "confidence": "推断（环境未记录开关值）"}
    return {"value": None, "source": None,
            "confidence": "无法判定（环境未记录开关值且目录名不可识别）",
            "expectedArm": arm}


def load_round(directory, p_cases):
    """读取一个轮次目录：environment.json + 逐例 `<CASE>.json`。"""
    path = os.path.abspath(directory)
    round_data = {"directory": _rel(path), "absDirectory": path, "errors": [],
                  "environment": {}, "switch": None, "cases": {}, "caseIds": [],
                  "expected": [], "missingFiles": []}
    if not os.path.isdir(path):
        round_data["errors"].append(f"目录不存在：{directory}")
        return round_data
    env, err = _load_json(os.path.join(path, "environment.json"))
    round_data["environment"] = env if isinstance(env, dict) else {}
    if err:
        round_data["errors"].append(f"environment.json 读取失败：{err}（环境证据缺失）")
    # 开关先按环境记录/目录标签推断，随逐例环境一并落进单例证据
    round_data["switch"] = infer_switch(round_data["environment"], "")
    case_env = dict(round_data["environment"], switch=round_data["switch"])
    round_data["expected"] = parse_case_ids(round_data["environment"].get("cases"))
    for case_path in sorted(glob.glob(os.path.join(path, "*.json"))):
        basename = os.path.basename(case_path)
        if basename in ("summary.json", "environment.json"):
            continue
        rec = extract_case(case_path, case_env, p_cases)
        if rec["case"] in round_data["cases"]:
            round_data["errors"].append(f"案例文件重名：{rec['case']}（{basename}）")
        round_data["cases"][rec["case"]] = rec
    round_data["caseIds"] = sorted(round_data["cases"],
                                   key=lambda cid: (cid[:1], int(re.sub(r"\D", "", cid) or 0), cid))
    round_data["missingFiles"] = [cid for cid in round_data["expected"]
                                  if cid not in round_data["cases"]]
    if not round_data["cases"]:
        round_data["errors"].append("目录内没有任何逐例 JSON")
    return round_data


def _merge_case_records(case_id, records):
    """同一案例多轮记录合并：数值取中位、布尔取多数（并列取主轮）、列表/证据取并集。"""
    primary = records[0]
    merged = {key: primary.get(key) for key in
              ("case", "suite", "name", "caseJson", "roundDir", "runRecordSource",
               "runRecordPath", "runId", "status", "outcome", "env", "artifact_note")}
    bool_fields = ("taskOk", "assertOk", "requirement_ok", "reviewStale", "reviewHashMissing",
                   "internal", "artifact_ok", "assertionExecuted", "validation_ok",
                   "final_gate_ok", "final_gate_replay_present")
    num_fields = ("draw_requests", "draw_attempts", "elapsed", "voxels", "parts", "bricks",
                  "target_blocks", "bricks_ratio", "review_overall",
                  "versionOverwrites", "page_errors", "console_errors", "screenshots",
                  "assertion_errors_count")
    for key in bool_fields:
        values = [r.get(key) for r in records if r.get(key) is not None]
        if not values:
            merged[key] = None
            continue
        trues = sum(1 for v in values if v is True)
        falses = len(values) - trues
        merged[key] = (trues > falses) if trues != falses else primary.get(key)
    for key in num_fields:
        values = [r.get(key) for r in records]
        med = _median(values)
        merged[key] = med if med is None else (int(med) if isinstance(med, float)
                                               and float(med).is_integer() else med)
    for key in ("requirement_source", "requirement_reason", "review_source",
                "review_absent_reason", "final_gate_source", "draw_requests_source"):
        merged[key] = primary.get(key)
    merged["requirement_failures"] = sorted({str(f) for r in records
                                             for f in (r.get("requirement_failures") or [])})
    merged["assertion_error_samples"] = sorted({str(e) for r in records
                                                for e in (r.get("assertion_error_samples") or [])})[:3]
    merged["final_gate_replay_errors"] = sorted(
        {str(e) for r in records for e in (r.get("final_gate_replay_errors") or [])})[:2]
    merged["fieldsMissing"] = sorted({m for r in records for m in (r.get("fieldsMissing") or [])})
    merged["final_gate_replay_present"] = any(r.get("final_gate_replay_present")
                                              for r in records)
    # 契约/支撑子结构：计数取中位、拦截/修复布尔取多数、列表取并集、文本取主轮非空值
    def merge_sub(key, sub_bool=(), sub_list=(), sub_num=()):
        cores = [r.get(key) or {} for r in records]
        fields = set()
        for core in cores:
            fields.update(core)
        out = {}
        for field in fields:
            vals = [c.get(field) for c in cores if c.get(field) is not None]
            if field in sub_bool:
                out[field] = (sum(1 for v in vals if v is True) > len(vals) / 2.0
                              if vals else None)
            elif field in sub_list:
                items = sorted({json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
                                for c in cores for v in (c.get(field) or [])})
                out[field] = [json.loads(v) if v.startswith(("[", "{")) else v for v in items]
            elif field in sub_num:
                out[field] = _median(vals)
            else:
                # 文本字段（interceptBasis/repairBasis/basis 等）：取主轮非空值
                out[field] = next((c.get(field) for c in cores if c.get(field) is not None), None)
        return out
    merged["contract"] = merge_sub(
        "contract", sub_bool=("intercepted", "repaired", "suspect"),
        sub_list=("kinds", "rejectedRequests", "suspectReasons"),
        sub_num=("checks", "flaggedChecks", "violations", "intercepts",
                 "contractErrorEvents", "drawContractErrorAttempts", "drawGateErrorAttempts"))
    support = merge_sub("support", sub_num=("total", "rejections", "solveFailures",
                                            "gateErrorsFallback", "contractChecksSupport",
                                            "drawGateErrorAttempts",
                                            "drawContractErrorAttempts", "nonContractTotal"),
                        sub_list=("evidence",))
    merged["support"] = support
    merged["rounds"] = [{"caseJson": r.get("caseJson"), "runId": r.get("runId"),
                         "taskOk": r.get("taskOk"), "assertOk": r.get("assertOk"),
                         "requirement_ok": r.get("requirement_ok"),
                         "draw_requests": r.get("draw_requests"),
                         "elapsed": r.get("elapsed"),
                         "support": (r.get("support") or {}).get("total")}
                        for r in records]
    return merged


def load_arm(directories, p_cases, expected_switch):
    """读取一臂（主轮 + 追加轮），逐例按 case id 合并多轮中位。"""
    rounds = [load_round(d, p_cases) for d in directories]
    arm = {"directories": [r["directory"] for r in rounds], "rounds": rounds,
           "errors": [e for r in rounds for e in r["errors"]],
           "singleRound": len(rounds) == 1, "expectedSwitch": expected_switch,
           "environment": rounds[0]["environment"] if rounds else {},
           "switch": None, "cases": {}, "extraEnvironmentMismatch": []}
    env = arm["environment"]
    arm["switch"] = infer_switch(env, expected_switch)
    # 追加轮的环境一致性（HEAD/模型/并发/开关）
    for extra in rounds[1:]:
        extra_env = extra["environment"]
        for key in ("codeHead", "modelConfigured", "concurrency"):
            if extra_env.get(key) != env.get(key):
                arm["extraEnvironmentMismatch"].append(
                    f"{extra['directory']} 的 {key}={extra_env.get(key)!r} 与主轮 "
                    f"{env.get(key)!r} 不一致")
    case_ids = sorted({cid for r in rounds for cid in r["cases"]},
                      key=lambda cid: (cid[:1], int(re.sub(r"\D", "", cid) or 0), cid))
    for cid in case_ids:
        records = [r["cases"][cid] for r in rounds if cid in r["cases"]]
        arm["cases"][cid] = _merge_case_records(cid, records)
    # 契约记录可反证开关状态：ON 臂有 contractChecks 记录但环境未记录时按记录推断
    if arm["switch"].get("value") is None:
        checked = sum(1 for c in arm["cases"].values()
                      if (c.get("contract") or {}).get("checks"))
        if checked:
            arm["switch"] = {"value": "on", "source": "run 记录 contractChecks（有检查记录）",
                             "confidence": "推断（环境未记录开关值）"}
    return arm


# ---------------------------------------------------------------- 分组汇总
def _elapsed_ok(rec):
    return rec.get("elapsed") is not None


def aggregate_group(cases, case_ids):
    """对给定案例集合汇总 OFF/ON 单臂的交付/断言/成本/契约/support 指标。"""
    rows = [cases[cid] for cid in case_ids if cid in cases]
    delivered = [r for r in rows if r.get("taskOk") is True]
    group = {
        "cases": len(rows), "delivered": len(delivered),
        "assertPass": sum(1 for r in rows if r.get("assertOk") is True),
        "requirementPass": sum(1 for r in rows if r.get("requirement_ok") is True),
        "requirementEvaluated": sum(1 for r in rows if r.get("requirement_ok") is not None),
        "deliveryRate": _ratio(len(delivered), len(rows)),
        "supportTotal": None, "supportKnownCases": 0,
        "contractChecksTotal": None, "contractFlaggedChecks": None,
        "contractViolations": None, "contractIntercepts": None,
        "contractCheckedCases": 0, "contractInterceptRate": None,
        "contractCaseInterceptRate": None, "interceptedCases": [], "repairedCases": [],
        "contractRepairRate": None, "suspects": [],
        "validationBad": [], "finalGateBad": [], "finalGateUnknown": [],
        "validationUnknown": [], "assertionUnknown": [],
        "versionHashBad": [], "versionHashUnknown": [], "artifactBad": [],
        "artifactUnknown": [], "internalCases": [], "reviewHashMissingCases": [],
        "pageErrorCases": [], "pageErrorTotal": None, "consoleErrorTotal": None,
        "reviewFallbackCases": [], "reviewAbsentDocumented": [], "reviewMissing": [],
        "requestIncomplete": [], "requestFallback": [], "requestUnknown": [],
        "rounds": [r.get("rounds") for r in rows],
        "requirementFailures": {r["case"]: r.get("requirement_failures") or []
                                for r in rows if r.get("requirement_failures")},
        "caseIds": [r["case"] for r in rows],
    }
    support_values = [r["support"].get("total") for r in rows
                      if (r.get("support") or {}).get("total") is not None]
    if support_values:
        group["supportTotal"] = sum(support_values)
        group["supportKnownCases"] = len(support_values)
    # 契约四类计数：只在“有 run 记录/有字段”的案例上求和；全都没有记录时保持 None（未知）
    def _sum_field(field):
        values = [(r.get("contract") or {}).get(field) for r in rows]
        known = [v for v in values if v is not None]
        return sum(known) if known else None
    group["contractChecksTotal"] = _sum_field("checks")
    group["contractFlaggedChecks"] = _sum_field("flaggedChecks")
    group["contractViolations"] = _sum_field("violations")
    group["contractIntercepts"] = _sum_field("intercepts")
    group["contractCheckedCases"] = sum(
        1 for r in rows if (r.get("contract") or {}).get("checks") is not None)
    if group["contractChecksTotal"]:
        group["contractInterceptRate"] = _ratio(group["contractFlaggedChecks"],
                                                group["contractChecksTotal"])
    for r in rows:
        contract = r.get("contract") or {}
        if contract.get("intercepted") is True:
            group["interceptedCases"].append(r["case"])
            if contract.get("repaired") is True:
                group["repairedCases"].append(r["case"])
        if contract.get("suspect") is True:
            group["suspects"].append({"case": r["case"],
                                      "reasons": contract.get("suspectReasons") or [],
                                      "evidence": r.get("caseJson")})
        if r.get("taskOk") is not True:
            continue  # 底线指标只统计交付例
        if r.get("validation_ok") is False:
            group["validationBad"].append(r["case"])
        elif r.get("validation_ok") is None:
            group["validationUnknown"].append(r["case"])
        if r.get("final_gate_ok") is False:
            group["finalGateBad"].append(r["case"])
        elif r.get("final_gate_ok") is None:
            group["finalGateUnknown"].append(r["case"])
        if (r.get("versionOverwrites") or 0) > 0 or r.get("reviewStale") is True:
            group["versionHashBad"].append(r["case"])
        elif r.get("versionOverwrites") is None and r.get("reviewStale") is None:
            group["versionHashUnknown"].append(r["case"])
        if r.get("reviewHashMissing") is True:
            # 仅作观察证据：无评审的记录天然缺评审哈希，不单独判定版本/哈希退化
            group["reviewHashMissingCases"].append(r["case"])
        if r.get("artifact_ok") is False:
            group["artifactBad"].append(r["case"])
        elif r.get("artifact_ok") is None:
            group["artifactUnknown"].append(r["case"])
        if r.get("internal"):
            group["internalCases"].append(r["case"])
        if not r.get("assertionExecuted"):
            # 交付但没有断言 metrics：请求/视觉分记录是否完整无法核对（不伪造结论）
            group["assertionUnknown"].append(r["case"])
            continue
        source = r.get("draw_requests_source") or ""
        if source.startswith("runRecord"):
            pass
        elif "metrics" in source:
            group["requestFallback"].append(r["case"])
            group["requestIncomplete"].append(r["case"])
        else:
            group["requestUnknown"].append(r["case"])
            group["requestIncomplete"].append(r["case"])
        if r.get("review_source") == "task_result":
            group["reviewFallbackCases"].append(r["case"])
        elif r.get("review_overall") is None:
            if r.get("review_absent_reason"):
                group["reviewAbsentDocumented"].append(
                    {"case": r["case"], "reason": r.get("review_absent_reason")})
            else:
                group["reviewMissing"].append(r["case"])
    if group["interceptedCases"]:
        group["contractCaseInterceptRate"] = _ratio(
            len(group["interceptedCases"]),
            max(1, group["contractCheckedCases"]))
        group["contractRepairRate"] = _ratio(len(group["repairedCases"]),
                                             len(group["interceptedCases"]))
    page_known = [r for r in rows if r.get("page_errors") is not None]
    if page_known:
        group["pageErrorTotal"] = sum(r["page_errors"] for r in page_known)
        group["pageErrorCases"] = [r["case"] for r in page_known if r["page_errors"] > 0]
    console_known = [r for r in rows if r.get("console_errors") is not None]
    if console_known:
        group["consoleErrorTotal"] = sum(r["console_errors"] for r in console_known)
    draw_cases = [r for r in rows if r.get("draw_requests") is not None
                  and (r.get("draw_attempts") or 0) > 0]
    draw_values = [r["draw_requests"] for r in draw_cases]
    group["drawMedian"] = _median(draw_values)
    group["drawMean"] = _mean(draw_values)
    group["drawCases"] = len(draw_values)
    elapsed_values = [r["elapsed"] for r in rows if _elapsed_ok(r)]
    group["elapsedMedian"] = _median(elapsed_values)
    group["elapsedCases"] = len(elapsed_values)
    return group


def build_analysis(off_dirs, on_dirs, p_cases):
    """主入口：读取两臂、配对逐例、分组汇总、门槛判定，返回完整分析 dict。"""
    off_arm = load_arm(off_dirs, p_cases, "off")
    on_arm = load_arm(on_dirs, p_cases, "on")
    off_ids = set(off_arm["cases"])
    on_ids = set(on_arm["cases"])
    pair_ids = sorted(off_ids & on_ids,
                      key=lambda cid: (cid[:1], int(re.sub(r"\D", "", cid) or 0), cid))
    all_ids = pair_ids + sorted(off_ids - on_ids) + sorted(on_ids - off_ids)
    case_rows = []
    for cid in all_ids:
        off_rec, on_rec = off_arm["cases"].get(cid), on_arm["cases"].get(cid)
        case_rows.append({
            "case": cid, "suite": (off_rec or on_rec or {}).get("suite", "R"),
            "name": (off_rec or on_rec or {}).get("name"),
            "paired": off_rec is not None and on_rec is not None,
            "missingOff": off_rec is None, "missingOn": on_rec is None,
            "off": off_rec, "on": on_rec,
        })
    suites = {"P": [row["case"] for row in case_rows if row["suite"] == "P"],
              "R": [row["case"] for row in case_rows if row["suite"] == "R"],
              "ALL": [row["case"] for row in case_rows]}
    pair_suites = {
        key: [cid for cid in pair_ids
              if (off_arm["cases"][cid].get("suite") == key if key != "ALL" else True)]
        for key in ("P", "R", "ALL")}
    groups = {}
    for arm_name, arm in (("off", off_arm), ("on", on_arm)):
        groups[arm_name] = {}
        for key, ids in suites.items():
            groups[arm_name][key] = aggregate_group(arm["cases"], ids)
        # 配对子集汇总（gate 的公平口径：只在两臂都有记录的案例上比较）
        groups[arm_name]["PAIRED"] = {}
        for key, ids in pair_suites.items():
            groups[arm_name]["PAIRED"][key] = aggregate_group(arm["cases"], ids)
    analysis = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "tool": "tools/e2e_ab_analyze.py", "definitionVersion": "ab-analyze-v1",
        "supportDefinition": SUPPORT_DEFINITION,
        "pCases": list(p_cases),
        "arms": {"off": _arm_public(off_arm), "on": _arm_public(on_arm)},
        "caseIds": {**{key: suites[key] for key in ("P", "R", "ALL")},
                    "pairs": pair_ids,
                    "offOnly": sorted(off_ids - on_ids),
                    "onOnly": sorted(on_ids - off_ids)},
        "cases": case_rows,
        "groups": groups,
        "warnings": _collect_warnings(off_arm, on_arm, case_rows),
    }
    analysis["gates"] = evaluate_gates(analysis)
    analysis["undetermined"] = _collect_undetermined(analysis)
    analysis["verdict"] = _overall_verdict(analysis["gates"])
    return analysis


def _arm_public(arm):
    return {"directories": arm["directories"], "singleRound": arm["singleRound"],
            "environment": arm["environment"], "switch": arm["switch"],
            "errors": arm["errors"], "extraEnvironmentMismatch": arm["extraEnvironmentMismatch"],
            "caseCount": len(arm["cases"]), "caseIds": sorted(arm["cases"])}


def _collect_warnings(off_arm, on_arm, case_rows):
    warnings = []
    for arm_name, arm in (("OFF", off_arm), ("ON", on_arm)):
        if arm["errors"]:
            warnings.append(f"{arm_name} 臂读取问题：{'；'.join(arm['errors'][:5])}")
        if arm["extraEnvironmentMismatch"]:
            warnings.append(f"{arm_name} 臂追加轮环境不一致："
                            + "；".join(arm["extraEnvironmentMismatch"][:4]))
        if arm["singleRound"]:
            warnings.append(f"{arm_name} 臂只有单轮（单轮初筛，正式结论需追加轮次中位）")
    missing_off = [row["case"] for row in case_rows if row["missingOff"]]
    missing_on = [row["case"] for row in case_rows if row["missingOn"]]
    if missing_off:
        warnings.append(f"OFF 臂缺例：{missing_off}")
    if missing_on:
        warnings.append(f"ON 臂缺例：{missing_on}")
    env_off, env_on = off_arm["environment"], on_arm["environment"]
    for key, label in (("codeHead", "代码 HEAD"), ("modelConfigured", "实际模型名"),
                       ("concurrency", "并发")):
        if env_off.get(key) != env_on.get(key):
            warnings.append(f"两臂 {label} 不一致：OFF={env_off.get(key)!r} "
                            f"ON={env_on.get(key)!r}（单变量对照前提被破坏）")
    if env_off.get("worktreeDirty") or env_on.get("worktreeDirty"):
        warnings.append("两臂工作区均有未提交改动（worktreeDirty=true），"
                        "须确认两轮之间代码未变，环境快照只记录当时状态")
    for arm_name, arm, expected in (("OFF", off_arm, "off"), ("ON", on_arm, "on")):
        switch = arm["switch"] or {}
        if switch.get("value") is None:
            warnings.append(f"{arm_name} 臂实验开关无法判定：{switch.get('confidence')}")
        elif str(switch.get("value")) not in (expected, "1" if expected == "on" else "0"):
            warnings.append(f"{arm_name} 臂开关值与臂标签不符："
                            f"value={switch.get('value')!r}（期望 {expected}，来源 "
                            f"{switch.get('source')}）")
    missing_metrics = [row["case"] for row in case_rows
                       if row["off"] and row["off"].get("assertionExecuted") is False
                       and row["off"].get("taskOk") is True]
    if missing_metrics:
        warnings.append(f"OFF 臂交付例缺少断言 metrics：{missing_metrics}")
    return warnings


# ---------------------------------------------------------------- 门槛判定
def _gate(gate_id, status, rule, evidence, detail, provisional=False):
    return {"id": gate_id, "title": GATE_TITLES[gate_id], "status": status, "rule": rule,
            "evidence": evidence, "detail": detail, "provisional": provisional}


def _subcheck(status, title, evidence, detail=""):
    return {"title": title, "status": status, "evidence": evidence, "detail": detail}


def _combine(subchecks):
    statuses = [s["status"] for s in subchecks]
    if any(s == "FAIL" for s in statuses):
        return "FAIL"
    if any(s == "无法判定" for s in statuses):
        return "无法判定"
    return "PASS"


def _trust_gates(analysis):
    up = analysis["groups"]["off"]["ALL"]
    op = analysis["groups"]["on"]["ALL"]
    subs = []
    validation_status = ("FAIL" if len(op["validationBad"]) > len(up["validationBad"])
                         else ("无法判定" if op["validationUnknown"] else "PASS"))
    subs.append(_subcheck(
        validation_status,
        "统一校验零退化",
        {"offBad": up["validationBad"], "onBad": op["validationBad"],
         "onUnknown": op["validationUnknown"]},
        f"OFF 交付例统一校验未过 {len(up['validationBad'])} 例；"
        f"ON {len(op['validationBad'])} 例（ON 不得多于 OFF），"
        f"ON 记录缺失 {len(op['validationUnknown'])} 例"))
    final_known = bool(op["finalGateBad"] or op["finalGateUnknown"]) or \
        bool(up["finalGateBad"] or up["finalGateUnknown"])
    if not final_known and not (op["delivered"] or up["delivered"]):
        subs.append(_subcheck("无法判定", "最终门禁零退化", {}, "两臂均无交付例，无法核对"))
    elif not op["delivered"]:
        subs.append(_subcheck("无法判定", "最终门禁零退化",
                              {"offBad": up["finalGateBad"], "onBad": []},
                              "ON 臂无交付例，无法核对最终门禁"))
    else:
        unknown = op["finalGateUnknown"]
        subs.append(_subcheck(
            "FAIL" if len(op["finalGateBad"]) > len(up["finalGateBad"]) else
            ("无法判定" if unknown else "PASS"),
            "最终门禁零退化",
            {"offBad": up["finalGateBad"], "onBad": op["finalGateBad"],
             "onUnknown": unknown},
            f"OFF 交付例最终门禁未过 {len(up['finalGateBad'])} 例；"
            f"ON {len(op['finalGateBad'])} 例，记录缺失 {len(unknown)} 例"))
    version_status = ("FAIL" if len(op["versionHashBad"]) > len(up["versionHashBad"])
                      else ("无法判定" if op["versionHashUnknown"] else "PASS"))
    subs.append(_subcheck(
        version_status,
        "版本/哈希一致零退化",
        {"offBad": up["versionHashBad"], "onBad": op["versionHashBad"],
         "onUnknown": op["versionHashUnknown"],
         "offReviewHashMissing": up["reviewHashMissingCases"],
         "onReviewHashMissing": op["reviewHashMissingCases"]},
        f"OFF 版本覆盖/评审过期 {len(up['versionHashBad'])} 例；"
        f"ON {len(op['versionHashBad'])} 例（无评审记录的评审哈希缺失只作观察，不计退化）"))
    artifact_status = ("FAIL" if len(op["artifactBad"]) > len(up["artifactBad"])
                       else ("无法判定" if op["artifactUnknown"] else "PASS"))
    subs.append(_subcheck(
        artifact_status,
        "产物一致性零退化",
        {"offBad": up["artifactBad"], "onBad": op["artifactBad"],
         "onUnknown": op["artifactUnknown"]},
        f"OFF 产物缺失/规模指标不同源 {len(up['artifactBad'])} 例；"
        f"ON {len(op['artifactBad'])} 例，记录缺失 {len(op['artifactUnknown'])} 例"))
    subs.append(_subcheck(
        "PASS" if len(op["internalCases"]) <= len(up["internalCases"]) else "FAIL",
        "无新增 internal",
        {"off": up["internalCases"], "on": op["internalCases"]},
        f"OFF internal {len(up['internalCases'])} 例；ON {len(op['internalCases'])} 例"))
    js_ok = None
    if op["pageErrorTotal"] is not None and up["pageErrorTotal"] is not None:
        js_ok = op["pageErrorTotal"] <= up["pageErrorTotal"]
    subs.append(_subcheck("无法判定" if js_ok is None else ("PASS" if js_ok else "FAIL"),
                          "无新增页面 JS 错误",
                          {"offPageErrors": up["pageErrorTotal"],
                           "onPageErrors": op["pageErrorTotal"],
                           "offConsole": up["consoleErrorTotal"],
                           "onConsole": op["consoleErrorTotal"],
                           "onCases": op["pageErrorCases"]},
                          f"OFF 页面错误 {up['pageErrorTotal']} 条 / 控制台错误 "
                          f"{up['consoleErrorTotal']} 条；ON 页面错误 {op['pageErrorTotal']} 条 / "
                          f"控制台 {op['consoleErrorTotal']} 条"))
    req_bad = op["requestIncomplete"]
    review_bad = op["reviewMissing"]
    record_unknown = op["assertionUnknown"] or op["requestUnknown"]
    if op["requestFallback"] or review_bad:
        record_status = "FAIL"
    elif record_unknown:
        record_status = "无法判定"
    else:
        record_status = "PASS"
    subs.append(_subcheck(
        record_status, "请求数与视觉分完整落盘",
        {"onRequestIncomplete": req_bad,
         "onRequestFallback": op["requestFallback"],
         "onRequestUnknown": op["requestUnknown"],
         "onAssertionUnknown": op["assertionUnknown"],
         "onReviewFallback": op["reviewFallbackCases"],
         "onReviewAbsentDocumented": op["reviewAbsentDocumented"],
         "onReviewMissing": review_bad,
         "offRequestFallback": up["requestFallback"],
         "offReviewFallback": up["reviewFallbackCases"]},
        "draw_requests 必须由 run 记录 drawAttempts 最大请求号可得；视觉分须有 run 记录或"
        "可核对的任务 result.review 补入路径（无评审须有不可用/快路径说明）；"
        "metrics 缺失时无法核对（标注无法判定）"))
    env_off, env_on = analysis["arms"]["off"], analysis["arms"]["on"]
    env_ok = True
    env_reasons = []
    for key, label in (("codeHead", "代码HEAD"), ("modelConfigured", "实际模型"),
                       ("concurrency", "并发")):
        a = env_off["environment"].get(key)
        b = env_on["environment"].get(key)
        if a is None or b is None:
            env_ok = None
            env_reasons.append(f"{label} 环境记录缺失")
        elif a != b:
            env_ok = False
            env_reasons.append(f"{label} OFF={a!r} ON={b!r}")
    switch_ok = True
    for arm_name, arm, expected in (("off", env_off, "off"), ("on", env_on, "on")):
        value = str((arm.get("switch") or {}).get("value") or "")
        if not value:
            switch_ok = None
            env_reasons.append(f"{arm_name} 臂开关无法判定")
        elif value not in (expected, "1" if expected == "on" else "0"):
            switch_ok = False
            env_reasons.append(f"{arm_name} 臂开关 {value!r} 与臂不符")
    env_status = ("FAIL" if (env_ok is False or switch_ok is False)
                  else ("无法判定" if (env_ok is None or switch_ok is None) else "PASS"))
    subs.append(_subcheck(
        env_status,
        "单变量环境一致",
        {"offEnv": {k: env_off["environment"].get(k) for k in
                    ("codeHead", "modelConfigured", "concurrency", "worktreeDirty")},
         "onEnv": {k: env_on["environment"].get(k) for k in
                   ("codeHead", "modelConfigured", "concurrency", "worktreeDirty")},
         "offSwitch": env_off.get("switch"), "onSwitch": env_on.get("switch")},
        "；".join(env_reasons) or "代码 HEAD/模型/并发一致，开关与臂标签一致"))
    evidence = {s["title"]: s["evidence"] for s in subs}
    detail = "；".join(f"{s['title']}={s['status']}" for s in subs)
    return _gate("trust", _combine(subs),
                 "统一校验、最终门禁、版本/哈希一致、产物一致性零退化；无新增 internal、"
                 "无新增页面 JS 错误；请求数与视觉分按新口径完整落盘（旧记录补入有证据）；"
                 "且两臂单变量环境一致", evidence, detail,
                 provisional=bool(analysis["arms"]["off"]["singleRound"]
                                  or analysis["arms"]["on"]["singleRound"]))


def _delivery_gates(analysis):
    up_pair, op_pair = (analysis["groups"]["off"]["PAIRED"],
                        analysis["groups"]["on"]["PAIRED"])
    pairs = analysis["caseIds"]["pairs"]
    provisional = bool(analysis["arms"]["off"]["singleRound"]
                       or analysis["arms"]["on"]["singleRound"])
    if not pairs:
        return _gate("delivery", "无法判定", "配对案例为空", {}, "两臂没有可配对案例",
                     provisional)
    all_ok = op_pair["ALL"]["delivered"] >= up_pair["ALL"]["delivered"]
    r_up, r_op = up_pair["R"], op_pair["R"]
    if r_op["cases"] == 0:
        r_status, r_detail = "无法判定", "R 组没有配对案例，无法核对 R 组不退化"
    else:
        r_ok = r_op["delivered"] >= r_up["delivered"]
        r_status = "PASS" if r_ok else "FAIL"
        r_detail = (f"R 组交付 OFF {r_up['delivered']}/{r_up['cases']} → "
                    f"ON {r_op['delivered']}/{r_op['cases']}")
    subs = [
        _subcheck("PASS" if all_ok else "FAIL", "多轮中位不低于配对 OFF 基线",
                  {"off": up_pair["ALL"]["delivered"], "on": op_pair["ALL"]["delivered"],
                   "pairs": len(pairs),
                   "offRate": up_pair["ALL"]["deliveryRate"],
                   "onRate": op_pair["ALL"]["deliveryRate"]},
                  f"配对案例 {len(pairs)} 例交付：OFF {up_pair['ALL']['delivered']} → "
                  f"ON {op_pair['ALL']['delivered']}"),
        _subcheck(r_status, "R 组不得退化",
                  {"off": {k: r_up[k] for k in ("cases", "delivered", "deliveryRate")},
                   "on": {k: r_op[k] for k in ("cases", "delivered", "deliveryRate")}},
                  r_detail),
    ]
    evidence = {s["title"]: s["evidence"] for s in subs}
    evidence.update({"offDelivered": up_pair["ALL"]["delivered"],
                     "onDelivered": op_pair["ALL"]["delivered"],
                     "pairs": len(pairs),
                     "offRate": up_pair["ALL"]["deliveryRate"],
                     "onRate": op_pair["ALL"]["deliveryRate"],
                     "rOffDelivered": r_up["delivered"], "rOnDelivered": r_op["delivered"],
                     "rCases": r_op["cases"]})
    return _gate("delivery", _combine(subs),
                 "配对案例交付数（多轮中位）不低于 OFF，且 R 组不退化",
                 evidence,
                 "；".join(f"{s['title']}={s['status']}" for s in subs), provisional)


def _requirement_gates(analysis):
    up_pair, op_pair = (analysis["groups"]["off"]["PAIRED"],
                        analysis["groups"]["on"]["PAIRED"])
    pairs = analysis["caseIds"]["pairs"]
    provisional = bool(analysis["arms"]["off"]["singleRound"]
                       or analysis["arms"]["on"]["singleRound"])
    if not pairs:
        return _gate("requirement", "无法判定", "配对案例为空", {}, "两臂没有可配对案例",
                     provisional)
    deltas = {}
    for key in ("ALL", "P", "R"):
        off_pass = up_pair[key]["requirementPass"]
        on_pass = op_pair[key]["requirementPass"]
        deltas[key] = {"off": off_pass, "on": on_pass,
                       "delta": on_pass - off_pass,
                       "cases": up_pair[key]["cases"]}
    n = max(1, deltas["ALL"]["cases"])
    threshold = max(1, int(math.ceil(0.10 * n)))  # 方案 +2/20 = +10 个百分点
    all_delta = deltas["ALL"]["delta"]
    r_delta = deltas["R"]["delta"]
    evaluated = (up_pair["ALL"]["requirementEvaluated"]
                 + op_pair["ALL"]["requirementEvaluated"])
    if evaluated == 0:
        return _gate("requirement", "无法判定",
                     "需求断言通过数较 OFF 至少 +2/20（+10pp），且不是只靠 P 组改善",
                     {"P": deltas["P"], "R": deltas["R"], "ALL": deltas["ALL"],
                      "evaluated": 0},
                     "两臂都没有任何需求断言结论（缺少 metrics/requirement_tier），"
                     "无法比较通过数", provisional)
    if deltas["R"]["cases"] == 0:
        status = "无法判定"
        detail = "R 组没有配对案例，无法确认“不是只靠 P 组改善”"
    elif all_delta >= threshold and r_delta >= 1:
        status = "PASS"
        detail = (f"需求断言通过数 +{all_delta}（门槛 +{threshold}/{n}，即 +10pp），"
                  f"且 R 组 +{r_delta}（非只靠 P 组改善）")
    elif all_delta >= threshold and r_delta < 1:
        status = "FAIL"
        detail = (f"需求断言通过数 +{all_delta} 达标，但 R 组仅 +{r_delta}，"
                  "改善只来自 P 组，不满足“不是只靠 P 组改善”")
    else:
        status = "FAIL"
        detail = (f"需求断言通过数 +{all_delta} < 门槛 +{threshold}/{n}"
                  f"（方案要求至少 +2/20 = +10pp）；P {deltas['P']['delta']:+d}，"
                  f"R {r_delta:+d}")
    evidence = {"threshold": f"+{threshold}/{n}（+10pp，方案 +2/20）",
                "P": deltas["P"], "R": deltas["R"], "ALL": deltas["ALL"],
                "offFailures": up_pair["ALL"]["requirementFailures"],
                "onFailures": op_pair["ALL"]["requirementFailures"]}
    return _gate("requirement", status, "需求断言通过数较 OFF 至少 +2/20（+10pp），"
                 "且不是只靠 P 组改善（R 组须 >0 改善）", evidence, detail, provisional)


def _structure_gates(analysis):
    up_pair, op_pair = (analysis["groups"]["off"]["PAIRED"],
                        analysis["groups"]["on"]["PAIRED"])
    provisional = bool(analysis["arms"]["off"]["singleRound"]
                       or analysis["arms"]["on"]["singleRound"])
    off_total = up_pair["ALL"]["supportTotal"]
    on_total = op_pair["ALL"]["supportTotal"]
    paired_rows = [row for row in analysis["cases"] if row.get("paired")]
    evidence = {"offPaired": {"total": off_total,
                              "knownCases": up_pair["ALL"]["supportKnownCases"]},
                "onPaired": {"total": on_total,
                             "knownCases": op_pair["ALL"]["supportKnownCases"]},
                "perCase": {row["case"]: {
                    "off": (row["off"] or {}).get("support", {}).get("total"),
                    "on": (row["on"] or {}).get("support", {}).get("total")}
                    for row in paired_rows},
                # 辅助口径：排除契约打回后的 support 失败尝试（只作机制解读，不参与门槛）
                "nonContractAux": {
                    "off": sum((row["off"] or {}).get("support", {}).get("nonContractTotal") or 0
                               for row in paired_rows),
                    "on": sum((row["on"] or {}).get("support", {}).get("nonContractTotal") or 0
                              for row in paired_rows)}}
    if off_total is None or on_total is None:
        return _gate("structure", "无法判定", "support 类失败尝试较 OFF 下降 ≥30%",
                     evidence, "至少一臂缺少 run 记录，support 类失败尝试无法统一计数",
                     provisional)
    if off_total == 0:
        return _gate("structure", "无法判定", "support 类失败尝试较 OFF 下降 ≥30%",
                     evidence, "OFF 臂 support 类失败尝试为 0，下降 30% 无定义"
                     "（无基线失败尝试可下降）", provisional)
    reduction = (off_total - on_total) / float(off_total)
    status = "PASS" if reduction >= 0.30 - 1e-9 else "FAIL"
    detail = (f"support 类失败尝试配对合计 OFF {off_total:g} → ON {on_total:g}，"
              f"下降 {reduction:.1%}（门槛 ≥30%）")
    return _gate("structure", status, "support 类失败尝试较 OFF 下降至少 30%",
                 evidence, detail, provisional)


def _cost_gates(analysis):
    up_pair, op_pair = (analysis["groups"]["off"]["PAIRED"],
                        analysis["groups"]["on"]["PAIRED"])
    provisional = bool(analysis["arms"]["off"]["singleRound"]
                       or analysis["arms"]["on"]["singleRound"])
    pairs = [row for row in analysis["cases"] if row.get("paired")]
    draw_pairs = [row for row in pairs
                  if (row["off"] or {}).get("draw_requests") is not None
                  and (row["off"] or {}).get("draw_attempts")
                  and (row["on"] or {}).get("draw_requests") is not None
                  and (row["on"] or {}).get("draw_attempts")]
    off_draw = _median([row["off"]["draw_requests"] for row in draw_pairs])
    on_draw = _median([row["on"]["draw_requests"] for row in draw_pairs])
    elapsed_pairs = [row for row in pairs
                     if (row["off"] or {}).get("elapsed") is not None
                     and (row["on"] or {}).get("elapsed") is not None]
    off_elapsed = _median([row["off"]["elapsed"] for row in elapsed_pairs])
    on_elapsed = _median([row["on"]["elapsed"] for row in elapsed_pairs])
    subs = []
    if off_draw is None or on_draw is None:
        subs.append(_subcheck("无法判定", "draw 请求数中位增幅 ≤1",
                              {"off": off_draw, "on": on_draw}, "缺少 draw 请求证据"))
        draw_delta = None
    else:
        draw_delta = on_draw - off_draw
        subs.append(_subcheck("PASS" if draw_delta <= 1 + 1e-9 else "FAIL",
                              "draw 请求数中位增幅 ≤1",
                              {"offMedian": off_draw, "onMedian": on_draw,
                               "delta": draw_delta, "pairedCases": len(draw_pairs)},
                              f"配对 draw 请求中位 OFF {off_draw:g} → ON {on_draw:g}，"
                              f"增幅 {draw_delta:+g}（门槛 ≤1）"))
    if off_elapsed is None or on_elapsed is None:
        elapsed_ratio = None
        subs.append(_subcheck("无法判定", "单例耗时中位增幅 ≤10%",
                              {"off": off_elapsed, "on": on_elapsed}, "缺少耗时证据"))
    elif off_elapsed <= 0:
        elapsed_ratio = None
        subs.append(_subcheck("无法判定", "单例耗时中位增幅 ≤10%",
                              {"offMedian": off_elapsed, "onMedian": on_elapsed},
                              "OFF 耗时中位为 0，无法计算增幅"))
    else:
        elapsed_ratio = (on_elapsed - off_elapsed) / float(off_elapsed)
        subs.append(_subcheck("PASS" if elapsed_ratio <= 0.10 + 1e-9 else "FAIL",
                              "单例耗时中位增幅 ≤10%",
                              {"offMedian": off_elapsed, "onMedian": on_elapsed,
                               "ratio": round(elapsed_ratio, 4),
                               "pairedCases": len(elapsed_pairs)},
                              f"配对单例耗时中位 OFF {off_elapsed:g}s → ON {on_elapsed:g}s，"
                              f"增幅 {elapsed_ratio:+.1%}（门槛 ≤10%）"))
    evidence = {s["title"]: s["evidence"] for s in subs}
    evidence.update({
        "drawOffMedian": off_draw, "drawOnMedian": on_draw,
        "drawDelta": (None if off_draw is None or on_draw is None else on_draw - off_draw),
        "pairedDrawCases": len(draw_pairs),
        "elapsedOffMedian": off_elapsed, "elapsedOnMedian": on_elapsed,
        "elapsedRatio": elapsed_ratio, "pairedElapsedCases": len(elapsed_pairs),
    })
    return _gate("cost", _combine(subs),
                 "draw 请求数中位增幅 ≤1；单例耗时中位增幅 ≤10%",
                 evidence,
                 "；".join(f"{s['title']}={s['status']}" for s in subs), provisional)


def _mechanism_gates(analysis):
    arm_on = analysis["arms"]["on"]
    group_on = analysis["groups"]["on"]["ALL"]
    provisional = bool(arm_on["singleRound"])
    switch = arm_on.get("switch") or {}
    switch_value = str(switch.get("value") or "")
    intercepted = group_on["interceptedCases"]
    suspects = group_on["suspects"]
    evidence = {"switch": switch, "contractCheckedCases": group_on["contractCheckedCases"],
                "contractChecks": group_on["contractChecksTotal"],
                "contractFlaggedChecks": group_on["contractFlaggedChecks"],
                "contractViolations": group_on["contractViolations"],
                "contractIntercepts": group_on["contractIntercepts"],
                "contractKinds": sorted({kind for row in analysis["cases"]
                                         for kind in ((row["on"] or {}).get("contract") or {})
                                         .get("kinds") or []}),
                "interceptedCases": intercepted, "repairedCases": group_on["repairedCases"],
                "interceptRate": group_on["contractInterceptRate"],
                "caseInterceptRate": group_on["contractCaseInterceptRate"],
                "repairRate": group_on["contractRepairRate"],
                "suspects": suspects,
                "perCase": {row["case"]: (row["on"] or {}).get("contract")
                            for row in analysis["cases"] if row.get("on")}}
    if switch_value in ("off", "0", "false", "no"):
        return _gate("mechanism", "FAIL", "契约拦截率、拦截后修复率及误伤逐例可查",
                     evidence, f"ON 臂开关证据为 {switch_value!r}（来源 {switch.get('source')}），"
                     "几何契约未实际启用，机制证据不成立", provisional)
    switch_on = switch_value in ("on", "1", "true", "yes")
    if group_on["contractCheckedCases"] == 0:
        if switch_on and group_on["delivered"] > 0:
            return _gate("mechanism", "FAIL", "契约拦截率、拦截后修复率及误伤逐例可查",
                         evidence, "ON 臂环境记录开关为 on，但所有 run 记录都没有 "
                         "contractChecks 字段：契约检查未落盘/未接线，机制证据不成立",
                         provisional)
        return _gate("mechanism", "无法判定", "契约拦截率、拦截后修复率及误伤逐例可查",
                     evidence, "ON 臂没有任何 contractChecks 记录（run 记录缺字段或契约未接线），"
                     "且开关值无法判定，拦截率/修复率无法计算", provisional)
    if group_on["contractChecksTotal"] == 0:
        if group_on["delivered"] > 0:
            return _gate("mechanism", "FAIL", "契约拦截率、拦截后修复率及误伤逐例可查",
                         evidence, f"ON 臂有 {group_on['delivered']} 例交付但全部 contractChecks "
                         "为空：开关/接线未生效或检查未落盘，机制证据不成立", provisional)
        return _gate("mechanism", "无法判定", "契约拦截率、拦截后修复率及误伤逐例可查",
                     evidence, "ON 臂无交付例且无契约检查记录，机制证据无法核对", provisional)
    # 有检查记录：拦截率可计算（无违规时为 0%，属有效证据）；修复率仅在有拦截时有定义
    if intercepted:
        rate_txt = (f"拦截率 {_pct(group_on['contractInterceptRate'])}"
                    f"（{group_on['contractFlaggedChecks']}/{group_on['contractChecksTotal']} 次检查），"
                    f"拦截后修复率 {_pct(group_on['contractRepairRate'])}"
                    f"（{len(group_on['repairedCases'])}/{len(intercepted)} 例）")
        status = "PASS"
    else:
        rate_txt = (f"本轮 ON 臂无契约违规（拦截率 0%，"
                    f"{group_on['contractChecksTotal']} 次检查），修复率不适用（无拦截）")
        status = "PASS"
    detail = rate_txt + f"；误伤可疑 {len(suspects)} 例，逐例证据见 report 与 JSON。"
    return _gate("mechanism", status, "契约拦截率、拦截后修复率及误伤情况逐例可查；"
                 "不得只凭交付差异归因于契约", evidence, detail, provisional)


def evaluate_gates(analysis):
    """逐项判定 PASS/FAIL/无法判定（每项附证据数字）。"""
    return [_trust_gates(analysis), _delivery_gates(analysis),
            _requirement_gates(analysis), _structure_gates(analysis),
            _cost_gates(analysis), _mechanism_gates(analysis)]


def _overall_verdict(gates):
    failed = [g for g in gates if g["status"] == "FAIL"]
    unknown = [g for g in gates if g["status"] == "无法判定"]
    if failed:
        return {"status": "否决/保持关闭", "failed": [g["id"] for g in failed],
                "unknown": [g["id"] for g in unknown],
                "reason": "存在 FAIL 门槛：" + "、".join(g["title"] for g in failed)}
    if unknown:
        return {"status": "证据不足（无法判定）", "failed": [],
                "unknown": [g["id"] for g in unknown],
                "reason": "无 FAIL，但有无法判定门槛：" + "、".join(g["title"] for g in unknown)}
    return {"status": "全部通过（可评估默认开启）", "failed": [], "unknown": [],
            "reason": "六项门槛全部 PASS"}


def _collect_undetermined(analysis):
    """汇总所有「无法判定」项与数据缺口（报告第 7 节）。"""
    items = []
    for gate in analysis["gates"]:
        if gate["status"] == "无法判定":
            items.append({"scope": "门槛判定", "item": gate["title"],
                          "reason": gate["detail"],
                          "evidence": gate["evidence"]})
    for row in analysis["cases"]:
        for side, name in (("off", "OFF"), ("on", "ON")):
            rec = row.get(side)
            if not rec:
                continue
            for missing in rec.get("fieldsMissing") or []:
                items.append({"scope": f"{name} {row['case']}", "item": missing,
                              "reason": "字段缺失，按空值处理（不猜测）",
                              "evidence": rec.get("caseJson")})
    for arm_name, arm in (("OFF", analysis["arms"]["off"]), ("ON", analysis["arms"]["on"])):
        switch = arm.get("switch") or {}
        if switch.get("value") is None:
            items.append({"scope": f"{arm_name} 环境", "item": "实验开关值",
                          "reason": switch.get("confidence"),
                          "evidence": f"{arm['directories'][0]}/environment.json"})
        for err in arm.get("errors") or []:
            items.append({"scope": f"{arm_name} 轮次", "item": "读取问题",
                          "reason": err, "evidence": arm["directories"][0]})
    # 去重（同 scope/item/reason）
    seen, out = set(), []
    for item in items:
        key = (item["scope"], item["item"], str(item["reason"])[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# ---------------------------------------------------------------- 报告渲染
def _cell(value, unit=""):
    return _fmt(value) + (unit if value is not None else "")


def _gate_icon(status):
    return {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "无法判定": "⚠️ 无法判定"}.get(status, status)


def _gate_evidence_text(gate):
    """把门槛证据 dict 压成一行关键数字（报告门槛表用）。"""
    evidence = gate["evidence"]
    try:
        if gate["id"] == "trust":
            parts = []
            for title, data in evidence.items():
                if not isinstance(data, dict):
                    parts.append(f"{title}: {data}")
                    continue
                if "onBad" in data or "onUnknown" in data:
                    parts.append(f"{title}=ON {len(data.get('onBad') or [])} 例坏/"
                                 f"{len(data.get('onUnknown') or [])} 例未知")
                elif "on" in data and "off" in data:
                    parts.append(f"{title}=OFF {len(data.get('off') or [])}/"
                                 f"ON {len(data.get('on') or [])}")
                else:
                    parts.append(title)
            return "；".join(parts)
        if gate["id"] == "delivery":
            return (f"配对交付 OFF {evidence.get('offDelivered')} → ON "
                    f"{evidence.get('onDelivered')}（{evidence.get('pairs')} 例）；"
                    f"R 组 OFF {evidence.get('rOffDelivered')} → "
                    f"ON {evidence.get('rOnDelivered')}")
        if gate["id"] == "requirement":
            return (f"需求断言 P {evidence['P']['delta']:+d} / R {evidence['R']['delta']:+d} / "
                    f"全体 {evidence['ALL']['delta']:+d}，门槛 {evidence['threshold']}")
        if gate["id"] == "structure":
            off_total = evidence["offPaired"]["total"]
            on_total = evidence["onPaired"]["total"]
            tg = "N/A" if not off_total else f"{(off_total - on_total) / float(off_total):.1%}"
            return f"support 失败尝试 OFF {_fmt(off_total)} → ON {_fmt(on_total)}（下降 {tg}）"
        if gate["id"] == "cost":
            ratio = evidence.get("elapsedRatio")
            ratio_text = f"{ratio:+.1%}" if isinstance(ratio, (int, float)) else "无法判定"
            return (f"draw 中位 OFF {_fmt(evidence.get('drawOffMedian'))} → ON "
                    f"{_fmt(evidence.get('drawOnMedian'))}（Δ "
                    f"{_fmt(evidence.get('drawDelta'))}）；耗时中位 OFF "
                    f"{_fmt(evidence.get('elapsedOffMedian'))}s → ON "
                    f"{_fmt(evidence.get('elapsedOnMedian'))}s（{ratio_text}）")
        if gate["id"] == "mechanism":
            return (f"检查 {_fmt(evidence.get('contractChecks'))} 次，拦截 "
                    f"{_fmt(evidence.get('contractIntercepts'))} 次（拦截率 "
                    f"{_pct(evidence.get('interceptRate'))}），修复 "
                    f"{len(evidence.get('repairedCases') or [])}/"
                    f"{len(evidence.get('interceptedCases') or [])} 例，"
                    f"误伤可疑 {len(evidence.get('suspects') or [])} 例")
    except (KeyError, TypeError):
        pass
    return "证据见 §6 与 ab-analyze.json"


def render_report(analysis):
    """渲染 ab-report.md：所有结论带数字与证据路径；无法判定项明确列原因。"""
    off, on = analysis["arms"]["off"], analysis["arms"]["on"]
    go, gn = analysis["groups"]["off"], analysis["groups"]["on"]
    single_round = off["singleRound"] or on["singleRound"]
    lines = [
        "# 几何契约配对 A/B 分析报告", "",
        f"- 生成时间：{analysis['generatedAt']}",
        f"- 分析口径版本：`{analysis['definitionVersion']}`；support 口径：`ab-support-v1`",
        f"- 模式：{'**单轮初筛**（未满足方案多轮中位要求）' if single_round else '多轮中位'}",
        f"- P 组（方案冻结）：{', '.join(analysis['pCases'])}",
        f"- 配对案例：{len(analysis['caseIds']['pairs'])} 例；"
        f"OFF 独有：{analysis['caseIds']['offOnly'] or '无'}；"
        f"ON 独有：{analysis['caseIds']['onOnly'] or '无'}",
        f"- 总体结论：**{analysis['verdict']['status']}** —— {analysis['verdict']['reason']}",
        "",
        "## 1. 轮次与环境", "",
        "| 臂 | 轮次目录 | 标签 | 时间 | HEAD | 工作区脏 | 开关（来源） | 模型 | 并发 | 案例数 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, arm in (("OFF", off), ("ON", on)):
        env = arm["environment"]
        switch = arm["switch"]
        switch_text = f"{switch.get('value') or '—'}（{switch.get('source') or switch.get('confidence')}）"
        lines.append(
            f"| {name} | {'<br>'.join(arm['directories'])} | {env.get('label') or '—'} | "
            f"{env.get('startedAt') or '—'} ~ {env.get('finishedAt') or '—'} | "
            f"`{_short_head(env.get('codeHead'))}` | {_fmt(env.get('worktreeDirty'))} | "
            f"{switch_text} | {env.get('modelConfigured') or '—'} | "
            f"{_fmt(env.get('concurrency'))} | {arm['caseCount']} |")
    lines += [
        "",
        "### 1.1 环境一致性", "",
        "| 检查项 | OFF | ON | 结论 |", "|---|---|---|---|",
    ]
    for key, label in (("codeHead", "代码 HEAD"), ("modelConfigured", "实际模型"),
                       ("concurrency", "并发"), ("worktreeDirty", "工作区脏")):
        a, b = off["environment"].get(key), on["environment"].get(key)
        lines.append(f"| {label} | `{a}` | `{b}` | {'一致' if a == b else '**不一致（对照前提被破坏）**'} |")
    for warning in analysis["warnings"]:
        lines.append(f"- ⚠️ {warning}")
    lines += [
        "",
        "## 2. 门槛判定（方案 §4.3）", "",
        "| 门槛 | 结论 | 规则 | 证据数字 | 备注 |", "|---|---|---|---|---|",
    ]
    for gate in analysis["gates"]:
        evidence_text = _gate_evidence_text(gate)
        note = "初筛（单轮）" if gate.get("provisional") else ""
        lines.append(f"| {gate['title']} | {_gate_icon(gate['status'])} | {gate['rule']} | "
                     f"{evidence_text} | {gate['detail']}{('；' + note) if note else ''} |")
    lines += ["", "## 3. 分组汇总（OFF vs ON）", "",
              "| 分组 | 指标 | OFF | ON | 差值 |", "|---|---|---|---|---|"]
    metrics = (
        ("有交付例数", lambda g: g["delivered"], True),
        ("全断言通过数", lambda g: g["assertPass"], True),
        ("需求断言通过数", lambda g: g["requirementPass"], True),
        ("support 类失败尝试总数", lambda g: g["supportTotal"], False),
        ("draw 请求数中位", lambda g: g["drawMedian"], False),
        ("draw 请求数均值", lambda g: g["drawMean"], False),
        ("单例耗时中位(s)", lambda g: g["elapsedMedian"], False),
        ("契约拦截率", lambda g: g["contractInterceptRate"], False),
        ("拦截后修复率", lambda g: g["contractRepairRate"], False),
    )
    for key, label in (("P", "P 组"), ("R", "R 组"), ("ALL", "全体")):
        for name, getter, integer in metrics:
            a, b = getter(go[key]), getter(gn[key])
            if name in ("契约拦截率", "拦截后修复率"):
                a_txt, b_txt = _pct(a), _pct(b)
                delta_txt = "—"
            else:
                a_txt = _fmt(a) if not integer else (str(a) if a is not None else "—")
                b_txt = _fmt(b) if not integer else (str(b) if b is not None else "—")
                delta_txt = (f"{b - a:+g}" if isinstance(a, (int, float))
                             and isinstance(b, (int, float)) else "—")
            lines.append(f"| {label} | {name} | {a_txt} | {b_txt} | {delta_txt} |")
    lines += [
        "",
        "**误伤可疑例清单**（逐例原因见 §6，仅供人工复核，不自动否决）：", "",
    ]
    suspects_off = go["ALL"]["suspects"]
    suspects_on = gn["ALL"]["suspects"]
    lines.append(f"- OFF：{', '.join(s['case'] + '（' + '；'.join(s['reasons']) + '）' for s in suspects_off) or '无'}")
    lines.append(f"- ON：{', '.join(s['case'] + '（' + '；'.join(s['reasons']) + '）' for s in suspects_on) or '无'}")
    lines += [
        "",
        "## 4. 逐例对比（OFF / ON 并列）", "",
        "> 口径：draw 请求 = drawAttempts 最大 request；需求断言 = requirement_tier；"
        "最终门禁 = finalGateReplay；review 优先 run 记录，缺失时标注 result 补入；"
        "— 表示字段缺失（不猜测）。",
        "",
        "| 案例 | 组 | 任务成功 O/N | outcome O/N | 断言通过 O/N | 需求断言 O/N | 需求失败摘要(ON) | "
        "draw 请求 O/N | 尝试数 O/N | 耗时(s) O/N | 体素 O/N | 零件 O/N | 目标 O/N | 目标比 O/N | "
        "视觉分 O/N | 最终门禁源/结论 O/N | 统一校验 O/N | 版本覆盖 O/N | 评审过期 O/N | 页面/控制台错误 O/N | "
        "截图 O/N | 契约检查/拦截 O/N | support 失败 O/N | runId O/N | 环境 HEAD/开关 O/N |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in analysis["cases"]:
        off_rec, on_rec = row.get("off") or {}, row.get("on") or {}
        def pair_text(key, formatter=_fmt):
            if not row.get("off") or not row.get("on"):
                return f"{formatter(off_rec.get(key))} / {formatter(on_rec.get(key))}"
            return (f"{formatter(off_rec.get(key))} / {formatter(on_rec.get(key))}")
        requirement_on = "；".join((on_rec.get("requirement_failures") or [])[:2]) or (
            "通过" if on_rec.get("requirement_ok") is True else "—")
        off_contract = off_rec.get("contract") or {}
        on_contract = on_rec.get("contract") or {}
        contract_pair = (f"O {_fmt(off_contract.get('checks'))}检/{_fmt(off_contract.get('intercepts'))}拦 ↔ "
                         f"N {_fmt(on_contract.get('checks'))}检/{_fmt(on_contract.get('intercepts'))}拦")
        env_pair = (f"O {((off_rec.get('env') or {}).get('codeHeadShort'))}/{_switch_value(off_rec)} ↔ "
                    f"N {((on_rec.get('env') or {}).get('codeHeadShort'))}/{_switch_value(on_rec)}")
        lines.append(
            f"| {row['case']} | {row['suite']} | "
            f"{pair_text('taskOk')} | {pair_text('outcome', str)} | {pair_text('assertOk')} | "
            f"{pair_text('requirement_ok')} | {requirement_on} | "
            f"{pair_text('draw_requests', _fmt)} | {pair_text('draw_attempts', _fmt)} | "
            f"{pair_text('elapsed', _fmt)} | {pair_text('voxels', _fmt)} | "
            f"{pair_text('bricks', _fmt)} | {pair_text('target_blocks', _fmt)} | "
            f"{_fmt_ratio(off_rec.get('bricks_ratio'))}/{_fmt_ratio(on_rec.get('bricks_ratio'))} | "
            f"{pair_text('review_overall', _fmt)} | "
            f"O {_gate_cell(off_rec)} ↔ N {_gate_cell(on_rec)} | "
            f"{pair_text('validation_ok')} | {pair_text('versionOverwrites', _fmt)} | "
            f"{pair_text('reviewStale')} | "
            f"{_fmt(off_rec.get('page_errors'))}/{_fmt(off_rec.get('console_errors'))} / "
            f"{_fmt(on_rec.get('page_errors'))}/{_fmt(on_rec.get('console_errors'))} | "
            f"{pair_text('screenshots', _fmt)} | {contract_pair} | "
            f"{_fmt((off_rec.get('support') or {}).get('total'))}/"
            f"{_fmt((on_rec.get('support') or {}).get('total'))} | "
            f"{pair_text('runId', str)} | {env_pair} |")
    if any(not row["paired"] for row in analysis["cases"]):
        lines += ["", "**缺例标注**："]
        for row in analysis["cases"]:
            if not row["paired"]:
                side = "OFF" if row["missingOff"] else "ON"
                lines.append(f"- {row['case']}（{row['suite']} 组）：{side} 臂缺少该例记录"
                             f"（不计入配对门槛比较）")
    lines += [
        "",
        "## 5. support 类失败尝试口径与逐例计数", "",
        f"口径定义（`ab-support-v1`）：{SUPPORT_DEFINITION}", "",
        "| 案例 | 组 | OFF 总数 | OFF 来源明细 | ON 总数 | ON 来源明细 |",
        "|---|---|---|---|---|---|",
    ]
    for row in analysis["cases"]:
        off_support = (row.get("off") or {}).get("support") or {}
        on_support = (row.get("on") or {}).get("support") or {}
        lines.append(
            f"| {row['case']} | {row['suite']} | {_fmt(off_support.get('total'))} | "
            f"{_support_breakdown(off_support)} | {_fmt(on_support.get('total'))} | "
            f"{_support_breakdown(on_support)} |")
    lines.append("")
    lines.append(_group_support_line(go, gn))
    lines += [
        "",
        "## 6. 契约机制证据（逐例）", "",
        "| 案例 | ON 契约检查次数 | 违规次数/类型 | 拦截次数（依据） | 拦截请求 | "
        "拦截后修复 | 修复依据 | 误伤可疑 | 可疑原因 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in analysis["cases"]:
        contract = ((row.get("on") or {}).get("contract") or {})
        if not contract:
            continue
        lines.append(
            f"| {row['case']} | {_fmt(contract.get('checks'))} | "
            f"{_fmt(contract.get('violations'))} / "
            f"{', '.join(contract.get('kinds') or []) or '—'} | "
            f"{_fmt(contract.get('intercepts'))}（{contract.get('interceptBasis') or '—'}） | "
            f"{', '.join(contract.get('rejectedRequests') or []) or '—'} | "
            f"{_tri_state(contract.get('repaired'))} | {contract.get('repairBasis') or '—'} | "
            f"{'是' if contract.get('suspect') else '否'} | "
            f"{'；'.join(contract.get('suspectReasons') or []) or '—'} |")
    if not any(((row.get("on") or {}).get("contract") or {}).get("checks") for row in analysis["cases"]):
        lines.append("| — | — | — | — | — | — | — | — | ON 臂无任何 contractChecks 记录（见 §7） |")
    lines += [
        "",
        "> 归因提示：契约机制证据只说明拦截/修复过程，**不得只凭交付差异归因于契约**；"
        "结构收益以 §2「结构收益」门槛的 support 类失败尝试配对数字为准。",
        "",
        "## 7. 无法判定项清单", "",
    ]
    if analysis["undetermined"]:
        lines += ["| 范围 | 项目 | 原因 | 证据 |", "|---|---|---|---|"]
        for item in analysis["undetermined"]:
            lines.append(f"| {item['scope']} | {item['item']} | {item['reason']} | "
                         f"{item.get('evidence') or '—'} |")
    else:
        lines.append("无。")
    lines += [
        "",
        "## 8. 证据路径", "",
        "- 逐例证据（任务四态/断言/页面错误/截图清单/run 记录快照）：",
    ]
    for row in analysis["cases"]:
        off_path = (row.get("off") or {}).get("caseJson") or "—"
        on_path = (row.get("on") or {}).get("caseJson") or "—"
        lines.append(f"  - {row['case']}：OFF `{off_path}`；ON `{on_path}`")
    lines += [
        "- 轮次环境：`<轮次目录>/environment.json`；轮次汇总：`<轮次目录>/summary.json`。",
        "- 视觉分补入证据（run 记录 review 缺失、由任务 result.review 补入）：",
    ]
    fallback_rows = []
    for row in analysis["cases"]:
        for side, name in (("off", "OFF"), ("on", "ON")):
            rec = row.get(side) or {}
            if rec.get("review_source") == "task_result":
                fallback_rows.append(f"  - {row['case']}（{name}）：`{rec.get('caseJson')}` → "
                                     f"`result.review.scores.overall={rec.get('review_overall')}`")
    lines += fallback_rows or ["  - 无（两臂视觉分均来自 run 记录或无需评审）"]
    lines += [
        "",
        "> 本报告由 `tools/e2e_ab_analyze.py` 自动生成；所有「无法判定」项均列出原因，"
        "未用猜测或编造数字填充。",
        "",
    ]
    return "\n".join(lines)


def _gate_cell(rec):
    """逐例最终门禁单元格：`来源/结论`（replay|legacy / 是|否|—）。"""
    if not rec:
        return "—"
    source = rec.get("final_gate_source") or "—"
    return f"{source}/{_fmt(rec.get('final_gate_ok'))}"


def _fmt_ratio(value):
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _tri_state(value):
    if value is None:
        return "—"
    return "成功" if value else "失败"


def _switch_value(rec):
    switch = (rec.get("env") or {}).get("switch") or {}
    return switch.get("value") or "—"


def _support_breakdown(support):
    if not support or support.get("total") is None:
        return "—"
    parts = []
    if support.get("rejections"):
        parts.append(f"拒绝 {support['rejections']}")
    if support.get("solveFailures"):
        parts.append(f"求解失败 {support['solveFailures']}")
    if support.get("gateErrorsFallback"):
        parts.append("gateErrors 兼容回退 1")
    if not parts:
        parts.append("无")
    return " + ".join(parts)


def _group_support_line(go, gn):
    """分组 support 失败尝试对照行。"""
    parts = []
    for key, label in (("P", "P 组"), ("R", "R 组"), ("ALL", "全体")):
        parts.append(f"{label} OFF {_fmt(go[key]['supportTotal'])} vs "
                     f"ON {_fmt(gn[key]['supportTotal'])}")
    return "分组合计：" + "；".join(parts) + "。"


# ---------------------------------------------------------------- CLI
def _split_dirs(value):
    return [part.strip() for part in str(value or "").replace("，", ",").split(",")
            if part.strip()]


def _default_out(off_dirs, on_dirs):
    try:
        common = os.path.commonpath([os.path.abspath(off_dirs[0]),
                                     os.path.abspath(on_dirs[0])])
        if os.path.isfile(common) or common == os.path.abspath(off_dirs[0]):
            common = os.path.dirname(common)
    except (ValueError, IndexError):
        common = os.getcwd()
    return os.path.join(common, datetime.now().strftime("%Y%m%d-%H%M%S") + "-ab-analyze")


def write_outputs(analysis, out_dir):
    """写出 ab-analyze.json 与 ab-report.md，返回两个路径。"""
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "ab-analyze.json")
    md_path = os.path.join(out_dir, "ab-report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_report(analysis))
    return json_path, md_path


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 非文本 stdout
        pass
    parser = argparse.ArgumentParser(
        description="配对 A/B 分析器（OFF/ON 轮次目录 → 逐例对比 + 分组汇总 + 门槛判定）")
    parser.add_argument("--off", required=True,
                        help="OFF 臂主轮目录（逗号分隔可给多轮，如 d1,d2）")
    parser.add_argument("--on", required=True,
                        help="ON 臂主轮目录（逗号分隔可给多轮）")
    parser.add_argument("--off-extra", default="",
                        help="OFF 臂追加轮次目录（逗号分隔，取多轮中位）")
    parser.add_argument("--on-extra", default="",
                        help="ON 臂追加轮次目录（逗号分隔，取多轮中位）")
    parser.add_argument("--p-cases", default=",".join(DEFAULT_P_CASES),
                        help="P 组案例 id（逗号分隔；其余为 R 组）")
    parser.add_argument("--out", default=None, help="输出目录（默认：两臂公共父目录下新建时间戳目录）")
    args = parser.parse_args(argv)
    off_dirs = _split_dirs(args.off) + _split_dirs(args.off_extra)
    on_dirs = _split_dirs(args.on) + _split_dirs(args.on_extra)
    missing = [d for d in off_dirs + on_dirs if not os.path.isdir(d)]
    if missing:
        print("目录不存在：" + "；".join(missing))
        return 2
    p_cases = {cid.strip().upper() for cid in _split_dirs(args.p_cases) if cid.strip()}
    if not p_cases:
        p_cases = set(DEFAULT_P_CASES)
    analysis = build_analysis(off_dirs, on_dirs, sorted(p_cases))
    out_dir = os.path.abspath(args.out) if args.out else _default_out(off_dirs, on_dirs)
    json_path, md_path = write_outputs(analysis, out_dir)
    mode = "单轮初筛" if (analysis["arms"]["off"]["singleRound"]
                         or analysis["arms"]["on"]["singleRound"]) else "多轮中位"
    print(f"[ab-analyze] 模式：{mode}；配对 {len(analysis['caseIds']['pairs'])} 例")
    for name in ("off", "on"):
        arm = analysis["arms"][name]
        group = analysis["groups"][name]["ALL"]
        print(f"[ab-analyze] {name.upper():3s} 目录 {len(arm['directories'])} 轮："
              f"交付 {group['delivered']}/{group['cases']}，断言通过 {group['assertPass']}，"
              f"需求断言通过 {group['requirementPass']}，support 失败 {_fmt(group['supportTotal'])}，"
              f"draw 中位 {_fmt(group['drawMedian'])}，耗时中位 {_fmt(group['elapsedMedian'])}s，"
              f"契约检查 {_fmt(group['contractChecksTotal'])} 次/拦截 {_fmt(group['contractIntercepts'])} 次")
    print(f"[ab-analyze] 总体结论：{analysis['verdict']['status']} —— "
          f"{analysis['verdict']['reason']}")
    for gate in analysis["gates"]:
        print(f"[ab-analyze]   门槛 {gate['title']}：{gate['status']}"
              f"{'（初筛）' if gate.get('provisional') else ''} —— {gate['detail']}")
    if analysis["undetermined"]:
        print(f"[ab-analyze] 无法判定项 {len(analysis['undetermined'])} 条（详见报告 §7）")
    print(f"[ab-analyze] 输出：{_rel(json_path)}；{_rel(md_path)}")
    return 1 if any(gate["status"] == "FAIL" for gate in analysis["gates"]) else 0


if __name__ == "__main__":
    sys.exit(main())
