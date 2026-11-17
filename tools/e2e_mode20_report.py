# -*- coding: utf-8 -*-
"""快速/高保真双模式同题恢复对比分析器与汇总报告器。

只读取本地证据，不发起任何模型/网络请求：
    <round>/<CASE>/<fast|fidelity>/<CASE>.json   每臂单例记录（tools/e2e_browser_20.py finalize_case 落盘）
    <round>/environment.json                    可选环境快照（tools/e2e_round.py 落盘）
输出：
    <round>/mode20-comparison.json   机器可读全量对比数据（逐例并排 + 汇总 + 翻转表）
    <round>/mode20-comparison.md     逐例并排表 + 分组汇总 + 高保真首次/总编排分离 + 缺失说明

用法：
    python -m tools.e2e_mode20_report --round artifacts/e2e-20/<stamp>-mode20-paired
    python -m tools.e2e_mode20_report --round <dir> --out <dir> [--json-only|--md-only]

口径（冻结，测试可复现）：
  - 案例不硬编码：按 <round>/<CASE>/<fast|fidelity>/ 目录发现；environment.json.cases 声明的
    缺失案例也如实记为 missing。缺臂不崩溃。
  - 快速模式的视觉评审固定记为「未评审」（score=null，不得补 0 或虚构分数）；若快速记录里
    出现视觉分，只作为模式路由异常单独披露，不进入主指标。
  - 高保真视觉分只认 run 记录 review / 任务 result.review / 断言 metrics.review_overall；
    走快速保底时高保真首次尝试的分数只来自首次尝试 run 记录（无则 null）。
  - draw 请求数 = 同一次运行内 drawAttempts[].request 累计编号的**最大值**（累计编号禁止求和，
    空列表=0）。跨尝试（首次高保真 + 快速保底）按各尝试分别取最大值后相加，并逐尝试留痕。
  - 评审/修订请求数：优先取记录里的显式计数；缺失时按 run 记录 timeline 的 review/revise
    阶段开始事件数近似并标注来源，无法提取写 null 不编造。
  - 通用底线 = 任务成功 + 最终门禁 + 统一校验（+断言里的通用底线失败项）；需求断言结论与
    失败项单独提取，两类结论分开报告。
  - 目标规模达标 = bricks/targetBlocks ≥ 0.5（冻结容差，同 tools/e2e_assert_20.TARGET_RATIO_MIN）。
  - 缺失/未知一律 null 并在 notes 注明原因，不得用 0 冒充。

退出码：0 = 报告完整写出；2 = 参数/目录错误或样本不完整（缺案例/缺臂）。
"""
import argparse
import glob
import json
import math
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MODES = ("fast", "fidelity")
STATE_ORDER = ("fidelity_success", "fidelity_degraded", "fast_fallback", "fast_success",
               "failed", "cancelled")
STATE_LABELS = {
    "fidelity_success": "高保真成功", "fidelity_degraded": "高保真降级",
    "fast_fallback": "快速保底", "fast_success": "快速成功",
    "failed": "失败", "cancelled": "取消",
}
# 目标块数比冻结容差（与 tools/e2e_assert_20.TARGET_RATIO_MIN 同一口径）。
TARGET_RATIO_MIN = 0.5
# 通用底线失败项前缀（同 tools/e2e_assert.assert_generic 的失败文案）。
GENERIC_ERROR_PREFIXES = (
    "运行未成功", "最终门禁重放未通过", "突显门禁带记录降级", "统一校验未通过",
    "最终版本产物缺失", "规模指标不同源", "最终产物评审已过期",
)
_CASE_ID_RE = re.compile(r"^([A-Za-z]{1,4})(\d{1,3})$")
_TARGET_DESC_RE = re.compile(r"目标约\s*(\d+)\s*块")
_SKIP_JSON = {"summary.json", "environment.json", "mode20-comparison.json"}
_NO_VALUE = object()


# ---------------------------------------------------------------- 基础小工具
def log(msg):
    """控制台日志（流水线工具风格）。"""
    print(f"[mode20-report] {msg}", flush=True)


def _load_json(path):
    """读取 JSON；失败返回 (None, 错误文本)，绝不抛异常。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _rel(path):
    """工作区内路径转相对路径，便于报告引用。"""
    try:
        return os.path.relpath(path, ROOT).replace(os.sep, "/")
    except ValueError:
        return str(path)


def _first(*values):
    for value in values:
        if value is not None and value is not _NO_VALUE:
            return value
    return None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _num(value):
    """转 float；布尔/非法值返回 None（禁止把 True 当 1）。"""
    if not _is_number(value):
        return None
    return float(value)


def _as_int(value):
    value = _num(value)
    return None if value is None else int(value)


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def percentile(values, ratio):
    """线性插值分位数（P50 对偶数个取中间两数平均）；忽略布尔/非数值；空集 None。"""
    ratio = min(max(float(ratio), 0.0), 1.0)
    vals = sorted(float(v) for v in (values or []) if _is_number(v))
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 2)
    rank = (len(vals) - 1) * ratio
    lo, hi = int(math.floor(rank)), int(math.ceil(rank))
    return round(vals[lo] + (vals[hi] - vals[lo]) * (rank - lo), 2)


def _quantiles(values):
    """耗时/请求数分布：返回 {n, p50, p90}。"""
    clean = [v for v in (values or []) if _is_number(v)]
    return {"n": len(clean), "p50": percentile(clean, 0.5), "p90": percentile(clean, 0.9)}


def _median(values):
    return percentile(values, 0.5)


def _is_generic_error(text):
    """通用底线失败项判定（与断言器失败文案前缀一致）。"""
    return str(text).startswith(GENERIC_ERROR_PREFIXES)


def _sha256(text):
    import hashlib
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _case_sort_key(case_id):
    match = _CASE_ID_RE.match(str(case_id))
    if match:
        return (match.group(1).upper(), int(match.group(2)), str(case_id))
    return (str(case_id), -1, str(case_id))


def _parse_cases_spec(spec):
    """解析 environment.json.cases（如 M01-M20、M01,M02 或列表）；无法解析返回 []。"""
    if isinstance(spec, (list, tuple)):
        return [str(item).strip() for item in spec
                if _CASE_ID_RE.match(str(item).strip())]
    if not isinstance(spec, str) or not spec.strip() or spec.strip().lower() == "all":
        return []
    out, seen = [], set()
    for part in re.split(r"[,，]", spec):
        part = part.strip()
        if not part:
            continue
        candidates = [part]
        if "-" in part:
            lo, hi = [x.strip() for x in part.split("-", 1)]
            m_lo, m_hi = _CASE_ID_RE.match(lo), _CASE_ID_RE.match(hi)
            if m_lo and m_hi and m_lo.group(1).upper() == m_hi.group(1).upper():
                width = len(m_lo.group(2))
                candidates = [f"{m_lo.group(1).upper()}{i:0{width}d}"
                              for i in range(int(m_lo.group(2)), int(m_hi.group(2)) + 1)]
        for cid in candidates:
            if _CASE_ID_RE.match(cid) and cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


# ---------------------------------------------------------------- 输入发现与读取
def _locate_arm_record(arm_dir, case_id):
    """定位一臂单例记录：优先 <CASE>.json；失败时仅在目录内唯一 JSON 时兜底。"""
    exact = os.path.join(arm_dir, f"{case_id}.json")
    if os.path.isfile(exact):
        return exact, None
    candidates = [p for p in sorted(glob.glob(os.path.join(arm_dir, "*.json")))
                  if os.path.basename(p).lower() not in _SKIP_JSON]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, f"缺少单例记录 {case_id}.json（臂目录无 JSON）"
    return None, f"缺少单例记录 {case_id}.json（目录内有 {len(candidates)} 个候选 JSON，无法判定）"


def discover_round(round_dir):
    """按目录发现案例与两臂记录路径，返回 (case_ids, arm_specs, environment, notes)。"""
    environment, notes = {}, []
    env_path = os.path.join(round_dir, "environment.json")
    if os.path.isfile(env_path):
        env_data, env_error = _load_json(env_path)
        if isinstance(env_data, dict):
            environment = env_data
        else:
            notes.append(f"environment.json 读取失败：{env_error}（环境/模型证据缺失）")
    arm_specs, case_ids = {}, []
    try:
        entries = sorted(os.listdir(round_dir))
    except OSError as exc:
        notes.append(f"轮次目录不可读：{type(exc).__name__}: {exc}")
        entries = []
    for name in entries:
        case_dir = os.path.join(round_dir, name)
        if not os.path.isdir(case_dir):
            continue
        arms = {}
        for mode in MODES:
            arm_dir = os.path.join(case_dir, mode)
            if not os.path.isdir(arm_dir):
                continue
            path, reason = _locate_arm_record(arm_dir, name)
            arms[mode] = {"path": path, "missingReason": reason}
        if arms:
            case_ids.append(name)
            arm_specs[name] = arms
    # environment.json 声明的案例：缺目录时也纳入并如实标 missing（样本完整性）。
    for cid in _parse_cases_spec(environment.get("cases")):
        if cid not in arm_specs:
            case_ids.append(cid)
            arm_specs[cid] = {}
    return sorted(dict.fromkeys(case_ids), key=_case_sort_key), arm_specs, environment, notes


def _load_run_record_file(run_id, arm_dir):
    """按 run_id 从证据目录或工作区 artifacts 读取 run 记录；返回 (record, source)。"""
    if not run_id:
        return None, None
    for path, label in ((os.path.join(arm_dir, "evidence", f"run_{run_id}.json"), "arm evidence"),
                        (os.path.join(ROOT, "artifacts", f"run_{run_id}.json"), "artifacts/")):
        if os.path.isfile(path):
            data, error = _load_json(path)
            if isinstance(data, dict) and not error:
                return data, f"run_{run_id}.json（{label}）"
    return None, None


def _final_run_record(raw, result, run_id, arm_dir):
    """最终尝试的 run 记录：单例内嵌快照优先，其次按 run_id 读取证据文件。"""
    embedded = raw.get("runRecord")
    if isinstance(embedded, dict) and embedded:
        return embedded, "case.runRecord"
    inline = result.get("run_record")
    if isinstance(inline, dict) and inline:
        return inline, "result.run_record"
    return _load_run_record_file(run_id, arm_dir)


def _attempts_state(result, raw):
    """提取各次尝试（result.attempts_detail 或单例 attempts），逐条保留可核对字段。"""
    items, source = result.get("attempts_detail"), "result.attempts_detail"
    if not isinstance(items, list):
        items, source = raw.get("attempts"), "case.attempts"
    if not isinstance(items, list):
        return [], None
    attempts = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        failure = item.get("failure") if isinstance(item.get("failure"), dict) else {}
        attempts.append({
            "index": index,
            "mode": item.get("mode"),
            "runId": _first(item.get("run_id"), item.get("runId")),
            "ok": _as_bool(item.get("ok")),
            "status": item.get("status"),
            "elapsedS": _num(_first(item.get("elapsed_s"), item.get("elapsedS"))),
            "error": item.get("error"),
            "failureKind": failure.get("kind"),
            "failureStage": failure.get("stage"),
            "reviewFlag": _first(item.get("review_flag"), item.get("reviewFlag")),
        })
    return attempts, source


# ---------------------------------------------------------------- 单臂字段提取
def _attempts_from_mode_facts(items):
    """从断言 metrics.mode_facts.attempts 还原各次尝试（attempts_detail 缺失时的可核对回退）。"""
    attempts = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        failure = item.get("failure") if isinstance(item.get("failure"), dict) else {}
        attempts.append({
            "index": index, "mode": item.get("mode"),
            "runId": _first(item.get("run_id"), item.get("runId")),
            "ok": _as_bool(item.get("ok")), "status": item.get("status"),
            "elapsedS": _num(_first(item.get("elapsed_s"), item.get("elapsedS"))),
            "error": item.get("error"),
            "failureKind": failure.get("kind"), "failureStage": failure.get("stage"),
            "reviewFlag": _first(item.get("review_flag"), item.get("reviewFlag")),
        })
    return attempts


def _mode_facts_view(facts):
    """断言模块 mode_facts 的报告视图（模式/评审/保底事实，供逐例并排核对）。"""
    if not isinstance(facts, dict) or not facts:
        return None
    return {
        "ok": _as_bool(facts.get("ok")),
        "errors": [str(x) for x in (facts.get("errors") or [])],
        "mode": facts.get("mode"), "outcome": facts.get("outcome"),
        "reviewPresent": bool(facts.get("review_present")),
        "reviewFlag": facts.get("review_flag"),
        "reviseVisual": _as_int(facts.get("revise_visual")),
        "fallbackCount": _as_int(facts.get("fallback_count")),
        "attemptsDetailPresent": facts.get("attempts_detail_present"),
        "source": "assertion_metrics.mode_facts",
    }


def _final_gate_fallback(run_record, result):
    """最终门禁兼容口径（同 tools/e2e_assert.final_gate_state）：重放优先，旧记录退回过程标记。"""
    if isinstance(run_record, dict) and run_record:
        if "finalGateReplay" in run_record:
            replay = run_record.get("finalGateReplay")
            return _as_bool(replay.get("ok")) if isinstance(replay, dict) else None
        return False if (run_record.get("gateFailed") or run_record.get("gate_failed")) else True
    if isinstance(result.get("finalGateReplay"), dict):
        return _as_bool(result["finalGateReplay"].get("ok"))
    if result.get("gate_failed") is not None:
        return not bool(result.get("gate_failed"))
    return None


def _generic_state(task_ok, metrics, run_record, result):
    """通用可信底线结论：任务成功 + 最终门禁 + 统一校验（+断言通用失败项），分开留痕。"""
    errors = metrics.get("assertion_errors")
    errors = [str(x) for x in errors] if isinstance(errors, list) else []
    generic_tier = metrics.get("generic_tier")
    if isinstance(generic_tier, list) and generic_tier:
        failures = [str(x) for x in generic_tier]
    else:
        failures = [e for e in errors if _is_generic_error(e)]
    gate_ok = _as_bool(metrics.get("final_gate_ok"))
    if gate_ok is None:
        gate_ok = _final_gate_fallback(run_record, result)
    validation_ok = _as_bool(metrics.get("validation_ok"))
    if validation_ok is None and isinstance(result.get("validation"), dict):
        validation_ok = _as_bool(result["validation"].get("ok"))
    if task_ok is not True:
        return {"ok": False, "failures": [], "gateOk": gate_ok, "validationOk": validation_ok,
                "conclusion": "未通过：任务未成功（无最终交付）"}
    problems = list(failures)
    if gate_ok is False:
        problems.append("最终门禁未通过")
    if validation_ok is False:
        problems.append("统一校验未通过")
    if problems:
        return {"ok": False, "failures": problems, "gateOk": gate_ok,
                "validationOk": validation_ok, "conclusion": "未通过"}
    missing = []
    if gate_ok is None:
        missing.append("最终门禁结论缺失")
    if validation_ok is None:
        missing.append("统一校验结论缺失")
    if missing:
        return {"ok": None, "failures": [], "gateOk": None, "validationOk": None,
                "conclusion": "无法判定（" + "；".join(missing) + "）"}
    return {"ok": True, "failures": [], "gateOk": True, "validationOk": True, "conclusion": "通过"}


def _requirement_state(metrics, task_ok):
    """需求断言结论与失败项（与通用底线分离）；形态兼容 dict/list 两种 metrics。"""
    if task_ok is not True:
        return {"ok": None, "evaluated": False, "failures": [], "source": None,
                "reason": "任务未成功，需求断言未执行"}
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
                                f"{tier.get('target_blocks')}（< {TARGET_RATIO_MIN:.0%}）")
            if not failures and tier.get("ok") is False:
                failures = [str(x) for x in (tier.get("errors") or [])
                            if not _is_generic_error(x)]
                if not failures:
                    return {"ok": None, "evaluated": True, "failures": [],
                            "source": "requirement_tier(dict)",
                            "reason": "需求达标档判失败但无法定位需求层失败项"}
            return {"ok": not failures, "evaluated": True, "failures": failures,
                    "source": "requirement_tier(dict)"}
        if "errors" in tier:
            failures = [str(x) for x in (tier.get("errors") or [])
                        if not _is_generic_error(x)]
            return {"ok": not failures, "evaluated": True, "failures": failures,
                    "source": "requirement_tier.errors(旧结构)"}
    assertion_ok = _as_bool(metrics.get("assertion_ok"))
    if assertion_ok is not None:
        return {"ok": assertion_ok, "evaluated": True, "failures": [],
                "source": "assertion_ok 回退（旧记录无法拆分需求层）"}
    return {"ok": None, "evaluated": False, "failures": [], "source": None,
            "reason": "缺少 requirement_tier/assertion_ok，需求断言结论无法判定"}


def _scale_state(metrics, result, run_record, desc):
    """规模指标：目标块数/实际零件/目标比/体素/部位/算子；每个值都记录来源。"""
    tier = metrics.get("requirement_tier")
    tier = tier if isinstance(tier, dict) else {}
    rr = run_record if isinstance(run_record, dict) else {}
    rscale = rr.get("scaleMetrics") if isinstance(rr.get("scaleMetrics"), dict) else {}
    res_scale = result.get("scaleMetrics") if isinstance(result.get("scaleMetrics"), dict) else {}
    sources = {}

    def pick(key, *candidates):
        for label, value in candidates:
            if value is not None:
                sources[key] = label
                return value
        sources[key] = None
        return None

    target = _as_int(pick("targetBlocks", ("metrics.target_blocks", metrics.get("target_blocks")),
                          ("requirement_tier.target_blocks", tier.get("target_blocks")),
                          ("runRecord.scaleMetrics.targetBlocks", rscale.get("targetBlocks")),
                          ("result.scaleMetrics.targetBlocks", res_scale.get("targetBlocks"))))
    if target is None and isinstance(desc, str):
        match = _TARGET_DESC_RE.search(desc)
        if match:
            target = int(match.group(1))
            sources["targetBlocks"] = "desc 目标约 N 块（需求原文解析）"
    bricks = _as_int(pick("actualParts", ("metrics.pieces", metrics.get("pieces")),
                          ("metrics.bricks", metrics.get("bricks")),
                          ("requirement_tier.bricks", tier.get("bricks")),
                          ("result.pieces", result.get("pieces")),
                          ("runRecord.scaleMetrics.actualParts", rscale.get("actualParts"))))
    ratio = _num(pick("bricksRatio", ("metrics.bricks_ratio", metrics.get("bricks_ratio")),
                      ("requirement_tier.bricks_ratio", tier.get("bricks_ratio")),
                      ("runRecord.scaleMetrics.targetBlocksRatio",
                       rscale.get("targetBlocksRatio")),
                      ("result.scaleMetrics.targetBlocksRatio",
                       res_scale.get("targetBlocksRatio"))))
    if ratio is None and target and bricks is not None:
        ratio = round(bricks / float(target), 4)
        sources["bricksRatio"] = "bricks / targetBlocks（由前两项计算）"
    target_ok = _as_bool(_first(metrics.get("target_blocks_ok"), tier.get("target_blocks_ok")))
    if target_ok is None and ratio is not None:
        target_ok = ratio >= TARGET_RATIO_MIN
        sources["targetOk"] = f"bricksRatio >= {TARGET_RATIO_MIN}（由比例计算）"
    elif target_ok is not None:
        sources["targetOk"] = "断言 metrics.target_blocks_ok"
    voxels = _as_int(pick("voxels", ("metrics.voxels", metrics.get("voxels")),
                          ("result.voxels", result.get("voxels")),
                          ("runRecord.scaleMetrics.actualVoxels", rscale.get("actualVoxels"))))
    parts = _as_int(pick("parts", ("metrics.parts", metrics.get("parts")),
                         ("result.counts.parts",
                          (result.get("counts") or {}).get("parts")
                          if isinstance(result.get("counts"), dict) else None)))
    ops = _as_int(pick("ops", ("metrics.ops", metrics.get("ops"))))
    notes = [f"{key} 缺失" for key in ("targetBlocks", "actualParts", "bricksRatio",
                                       "voxels", "parts", "ops") if sources.get(key) is None]
    return {"targetBlocks": target, "actualParts": bricks, "bricksRatio": ratio,
            "targetOk": target_ok, "voxels": voxels, "parts": parts, "ops": ops,
            "sources": sources, "notes": notes}


def _phase_timing(run_record, phases):
    """从 run 记录 timeline 取指定阶段累计耗时与轮次；无法完整计算时 seconds=None。"""
    state = {"seconds": None, "rounds": None, "complete": None}
    timeline = (run_record or {}).get("timeline") if isinstance(run_record, dict) else None
    if not isinstance(timeline, list):
        return state
    started, total, rounds, complete = {}, 0.0, 0, True
    for event in timeline:
        if not isinstance(event, dict) or event.get("phase") not in phases:
            continue
        phase = event["phase"]
        if "ended" in event and "started" not in event:
            begin = started.pop(phase, None)
            if begin is None or not _is_number(event.get("ended")):
                complete = False
                continue
            total += float(event["ended"]) - float(begin)
        elif "started" in event:
            started[phase] = event["started"]
            rounds += 1
    if started:
        complete = False  # 阶段仍未闭合（记录在阶段中途落盘）：不得用部分值或 0 冒充
    state["rounds"] = rounds
    state["complete"] = complete
    if complete:
        state["seconds"] = round(total, 1)
    return state


def _draw_requests(run_record):
    """draw 请求数 = 同一运行内 drawAttempts[].request 累计编号最大值（空列表=0）。"""
    if not isinstance(run_record, dict) or "drawAttempts" not in run_record:
        return None, None
    attempts = run_record.get("drawAttempts")
    if not isinstance(attempts, list):
        return None, None
    best = 0
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        value = _as_int(attempt.get("request"))
        if value is not None and value > best:
            best = value
    return best, "runRecord.drawAttempts.request 最大值"


def _explicit_request_count(record, keys, prefix="runRecord"):
    """记录里的显式请求计数（如 review_requests/reviewRounds），缺失返回 (None, None)。"""
    if not isinstance(record, dict):
        return None, None
    for key in keys:
        value = _as_int(record.get(key))
        if value is not None:
            return value, f"{prefix}.{key}（显式字段）"
    return None, None


def _attempt_record(attempt_records, run_id):
    return (attempt_records or {}).get(run_id) or (None, None)


def _timings_state(mode, outcome, raw, result, attempts, attempt_records, run_record,
                   run_source, notes):
    """任务总耗时 / 高保真首次尝试 / 快速保底 / 视觉评审 / 视觉修订（缺失 null 并注明）。"""
    total = _num(_first(raw.get("elapsedFinal"), raw.get("elapsedS")))
    first = fallback = None
    if mode == "fidelity":
        if attempts:
            first = attempts[0].get("elapsedS")
            if len(attempts) > 1 and attempts[1].get("mode") == "fast":
                fallback = attempts[1].get("elapsedS")
        elif outcome in ("fidelity_success", "fidelity_degraded"):
            first = _num(result.get("elapsed_s"))
        elif outcome in ("failed", "cancelled"):
            first = _num(result.get("elapsed_s"))
    timings = {"totalS": total, "firstAttemptS": first, "fallbackS": fallback,
               "reviewS": None, "reviseS": None, "reviewRounds": None,
               "reviseRounds": None, "source": None, "notes": []}
    # 视觉评审/修订耗时来自"高保真首次尝试"的 run 记录：有 attempts_detail 时取首次尝试，
    # 单次尝试（成功/降级）时最终 run 记录就是这次高保真尝试。
    fallback_used = mode == "fidelity" and (
        outcome == "fast_fallback" or any(a.get("mode") == "fast" for a in attempts))
    if mode == "fast":
        target_record = run_record
        source = f"快速最终 run 记录（{run_source or '来源未知'}）"
    elif attempts and len(attempts) > 1:
        target_record, record_source = (_attempt_record(attempt_records, attempts[0].get("runId"))
                                        if attempts[0].get("runId") else (None, None))
        source = (f"高保真首次尝试 run 记录（{record_source}）" if record_source
                  else "高保真首次尝试 run 记录（缺失）")
    else:
        target_record = run_record
        source = f"高保真最终 run 记录（{run_source or '来源未知'}）"
    if isinstance(target_record, dict):
        if mode == "fidelity" and first is None:
            # 高保真尝试的 run 记录自带该次尝试耗时（单次尝试或首次尝试均可核对）
            first = _num(target_record.get("elapsedS"))
            timings["firstAttemptS"] = first
        review = _phase_timing(target_record, ("review",))
        revise = _phase_timing(target_record, ("revise",))
        timings.update({"reviewS": review["seconds"], "reviseS": revise["seconds"],
                        "reviewRounds": review["rounds"], "reviseRounds": revise["rounds"],
                        "source": source})
        if review["complete"] is False:
            timings["notes"].append("视觉评审阶段未闭合（timeline 缺 ended），评审耗时未知")
        if revise["complete"] is False:
            timings["notes"].append("修订阶段未闭合（timeline 缺 ended），修订耗时未知")
    else:
        timings["source"] = None
        if fallback_used:
            timings["notes"].append("高保真首次尝试 run 记录未随单例保存：视觉评审/修订耗时未知")
        else:
            timings["notes"].append("缺少 run 记录：视觉评审/修订耗时未知")
    for key, label in (("totalS", "任务总耗时"), ("reviewS", "视觉评审耗时"),
                       ("reviseS", "视觉修订耗时")):
        if timings.get(key) is None:
            timings["notes"].append(f"{label}缺失/未知")
    if mode == "fidelity" and timings.get("notes") and timings.get("source"):
        timings["notes"] = list(dict.fromkeys(timings["notes"]))
    return timings


def _requests_state(mode, attempts, attempt_records, run_record, run_id, metrics, notes):
    """draw/评审/修订请求数：同运行内取累计最大值，跨尝试分别取最大值后相加。"""
    def by_attempt_list():
        rows = []
        if attempts:
            for attempt in attempts:
                rid = attempt.get("runId")
                record, source = _attempt_record(attempt_records, rid) if rid else (None, None)
                rows.append({"mode": attempt.get("mode"), "runId": rid,
                             "record": record, "source": source})
        else:
            rows.append({"mode": mode, "runId": run_id, "record": run_record,
                         "source": "最终 run 记录" if isinstance(run_record, dict) else None})
        return rows

    rows = by_attempt_list()
    state = {}
    for key, phases, explicit_keys in (
            ("draw", None, ("draw_requests", "drawRequests")),
            ("review", ("review",), ("review_requests", "reviewRequests", "reviewRounds")),
            ("revise", ("revise",), ("revise_requests", "reviseRequests", "reviseRounds"))):
        detail, known, total, note = [], 0, 0, None
        for index, row in enumerate(rows):
            record, source = row["record"], row["source"]
            # 断言 metrics 只描述最终交付尝试：仅在单次尝试或最后一条尝试缺记录时回退，
            # 不得把最终尝试的计数按到首次高保真尝试头上（否则跨尝试会重复计数）。
            metrics_fallback_ok = len(rows) == 1 or index == len(rows) - 1
            if key == "draw":
                count, count_source = _draw_requests(record)
                if count is None and metrics_fallback_ok:
                    count, count_source = _explicit_request_count(metrics, explicit_keys,
                                                                  prefix="metrics")
            else:
                count, count_source = _explicit_request_count(record, explicit_keys,
                                                              prefix="runRecord")
                if count is None:
                    timing = _phase_timing(record, phases)
                    if timing["rounds"] is not None:
                        count = timing["rounds"]
                        count_source = ("runRecord.timeline 阶段轮次（近似）"
                                        if timing["rounds"] else "runRecord.timeline 无该阶段（0）")
            detail.append({"mode": row.get("mode"), "runId": row.get("runId"),
                           "count": count, "source": count_source})
            if count is None:
                note = note or "部分尝试缺少可核对的请求计数"
            else:
                known += 1
                total += count
        if known == len(rows):
            state[key] = {"total": total, "byAttempt": detail,
                          "source": ("各尝试累计最大值相加（同一运行内不求和）" if key == "draw"
                                     else "各尝试 timeline 阶段轮次相加（近似请求数，已标注）")}
        else:
            state[key] = {"total": None, "byAttempt": detail, "source": None,
                          "note": note or "请求计数未知"}
            notes.append(f"{'draw' if key == 'draw' else '评审' if key == 'review' else '修订'}"
                         "请求数未知（记录缺失，不用 0 冒充）")
    return state


def _visual_state(mode, outcome, task_ok, metrics, result, run_record, attempt_records,
                  attempts, mode_facts, notes):
    """视觉评审结论：快速固定未评审（null，不补 0）；高保真取真实分并区分未交付原因。"""
    fallback_used = mode == "fidelity" and (
        outcome == "fast_fallback" or any(a.get("mode") == "fast" for a in attempts))
    first_record = None
    if mode == "fidelity" and attempts and attempts[0].get("runId"):
        first_record, _source = _attempt_record(attempt_records, attempts[0]["runId"])

    def score_of(record):
        review = (record or {}).get("review") if isinstance(record, dict) else None
        scores = review.get("scores") if isinstance(review, dict) else None
        return _num(scores.get("overall")) if isinstance(scores, dict) else None

    observed = _first(score_of(first_record), score_of(run_record),
                      score_of({"review": result.get("review")}),
                      _num(metrics.get("review_overall")))
    if mode == "fast":
        state = {"status": "not_reviewed", "score": None, "source": None,
                 "note": "快速模式未触发视觉评审：未评审（null，不得补 0）"}
        if observed is not None:
            state["unexpectedObservedScore"] = observed
            state["note"] += "；警告：快速记录中出现视觉分，模式路由需人工核查，仍按未评审展示"
            notes.append("快速记录中出现视觉分（模式路由异常，已单独披露，不进入主指标）")
        if (mode_facts or {}).get("reviewPresent") and observed is None:
            state["unexpectedReviewPresent"] = True
            state["note"] += "；警告：快速记录 review 非空（快速视觉评审调用应为 0）"
            notes.append("快速记录 review 非空（模式事实异常，需人工核查）")
        revise_visual = (mode_facts or {}).get("reviseVisual")
        if _as_int(revise_visual):
            state["unexpectedVisualReviseCount"] = _as_int(revise_visual)
            notes.append(f"快速记录视觉修订 {_as_int(revise_visual)} 次（快速不评审、不修订）")
        return state
    if observed is not None:
        source = ("高保真首次尝试 run 记录" if score_of(first_record) is not None else
                  "run 记录 review" if score_of(run_record) is not None else
                  "任务 result.review" if score_of({"review": result.get("review")}) is not None
                  else "断言 metrics.review_overall")
        note = None
        if fallback_used and not task_ok:
            note = "高保真首次尝试未交付，分数来自该尝试 run 记录（非最终交付产物）"
        return {"status": "scored", "score": observed, "source": source, "note": note}
    flag = _first(result.get("review_flag"), result.get("reviewFlag"),
                  metrics.get("review_flag"), (run_record or {}).get("reviewFlag")
                  if isinstance(run_record, dict) else None)
    if fallback_used and task_ok and any(a.get("ok") is False for a in attempts):
        note = "高保真首次尝试硬失败，未产出最终稿，无视觉分（不得补 0）"
        notes.append(note)
        return {"status": "not_delivered", "score": None, "source": None, "note": note}
    if flag == "review_unavailable":
        note = "视觉评审不可用（review_unavailable），无分数（不编造）"
    elif flag == "review_failed":
        note = "视觉评审未达标（review_failed）但分数未落盘"
    elif flag == "review_stale":
        note = "评审已过期（review_stale），最终稿无有效复审分"
    elif task_ok is not True:
        note = "任务未成功，无高保真视觉分"
    else:
        note = "交付例缺少视觉分且无不可用说明（记录不完整）"
    if (mode_facts or {}).get("reviewPresent"):
        note += "；评审记录存在但无可核对分数"
    notes.append("高保真视觉分缺失：" + note)
    return {"status": "unavailable" if flag == "review_unavailable" else "missing",
            "score": None, "source": None, "note": note}


def _delivery_source(mode, outcome, attempts):
    """实际交付来源：按最后一次成功尝试的模式判定（与四态互相印证）。"""
    if outcome == "fast_fallback":
        return {"source": "fast_fallback", "label": "快速保底（高保真硬失败后）"}
    last_ok = None
    for attempt in attempts:
        if attempt.get("ok") is True:
            last_ok = attempt
    if last_ok is not None:
        last_mode = last_ok.get("mode")
        if last_mode in MODES:
            return {"source": last_mode,
                    "label": "高保真" if last_mode == "fidelity" else "快速"}
    mapping = {"fidelity_success": ("fidelity", "高保真"),
               "fidelity_degraded": ("fidelity", "高保真（降级交付）"),
               "fast_success": ("fast", "快速")}
    if outcome in mapping:
        source, label = mapping[outcome]
        return {"source": source, "label": label}
    return {"source": None, "label": None}


def _first_attempt_state(mode, outcome, attempts, result, run_id, task_ok, notes):
    """高保真首次尝试结果（从 attempts_detail 或最终结果提取），与总编排结果分离。"""
    if mode != "fidelity":
        return None
    if attempts:
        first = attempts[0]
        if first.get("mode") not in (None, "fidelity"):
            notes.append(f"首次尝试 mode={first.get('mode')!r}，不是高保真（模式路由需核查）")
        if first.get("ok") is True:
            flag = first.get("reviewFlag")
            if len(attempts) == 1 and outcome in ("fidelity_success", "fidelity_degraded"):
                first_outcome, source = outcome, "arm_result"
            elif flag in ("review_failed", "review_unavailable", "review_stale"):
                first_outcome, source = "fidelity_degraded", "attempts_detail（按评审标记推断）"
            else:
                first_outcome, source = "fidelity_success", "attempts_detail"
        elif first.get("status") == "cancelled" or first.get("failureKind") == "cancelled":
            first_outcome, source = "cancelled", "attempts_detail"
        else:
            first_outcome, source = "failed", "attempts_detail"
        return {"available": True, "runId": first.get("runId"), "ok": first.get("ok"),
                "outcome": first_outcome, "outcomeSource": source,
                "elapsedS": first.get("elapsedS"), "status": first.get("status"),
                "error": first.get("error"), "failureKind": first.get("failureKind"),
                "failureStage": first.get("failureStage"), "reviewFlag": first.get("reviewFlag")}
    ok = _as_bool(result.get("ok"))
    if ok is None and outcome in ("fidelity_success", "fidelity_degraded"):
        ok = task_ok  # 单次尝试且四态为成功/降级：首次尝试即该次成功尝试
    if ok is None and outcome in ("failed", "cancelled"):
        ok = False
    if outcome in ("fidelity_success", "fidelity_degraded", "failed"):
        return {"available": True, "runId": run_id, "ok": ok, "outcome": outcome,
                "outcomeSource": "arm_result", "elapsedS": _num(result.get("elapsed_s")),
                "status": result.get("status"), "error": result.get("error"),
                "failureKind": (result.get("failure") or {}).get("kind")
                if isinstance(result.get("failure"), dict) else None,
                "failureStage": (result.get("failure") or {}).get("stage")
                if isinstance(result.get("failure"), dict) else None,
                "reviewFlag": result.get("review_flag")}
    notes.append("缺少 attempts_detail，无法拆分高保真首次尝试结果")
    return {"available": False, "runId": None, "ok": None, "outcome": None,
            "outcomeSource": None, "elapsedS": None, "status": None, "error": None,
            "failureKind": None, "failureStage": None, "reviewFlag": None}


def extract_arm(case_id, mode, record_path, round_env):
    """读取一臂单例记录并提取对比所需全部字段；缺字段一律 null 并写入 notes。"""
    arm = {"case": case_id, "mode": mode, "recorded": False,
           "recordPath": _rel(record_path), "notes": []}
    raw, error = _load_json(record_path)
    if not isinstance(raw, dict):
        arm["notes"].append(f"单例记录读取失败：{error}")
        return arm
    arm["recorded"] = True
    notes = arm["notes"]
    if raw.get("case") and str(raw.get("case")) != case_id:
        notes.append(f"单例记录 case={raw.get('case')!r} 与目录名 {case_id} 不一致")
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    assertion = raw.get("assertion") if isinstance(raw.get("assertion"), dict) else {}
    metrics = assertion.get("metrics") if isinstance(assertion.get("metrics"), dict) else {}
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    arm_dir = os.path.dirname(record_path)
    attempts, attempts_source = _attempts_state(result, raw)
    mode_facts_raw = (metrics.get("mode_facts")
                      if isinstance(metrics.get("mode_facts"), dict) else {})
    if attempts_source is None and isinstance(mode_facts_raw.get("attempts"), list) \
            and mode_facts_raw["attempts"]:
        # 断言 metrics 的 mode_facts 已从记录提取过尝试明细：作为可核对回退来源
        attempts = _attempts_from_mode_facts(mode_facts_raw["attempts"])
        attempts_source = "metrics.mode_facts.attempts"
    run_id = _first(raw.get("runId"), result.get("run_id"), metrics.get("run_id"))
    attempt_run_ids = [a.get("runId") for a in attempts if a.get("runId")]
    if run_id is None and attempt_run_ids:
        run_id = attempt_run_ids[-1]
    run_record, run_source = _final_run_record(raw, result, run_id, arm_dir)
    attempt_records = {}
    if run_id and run_record:
        attempt_records[run_id] = (run_record, run_source)
    for attempt in attempts:
        rid = attempt.get("runId")
        if rid and rid not in attempt_records:
            attempt_records[rid] = _load_run_record_file(rid, arm_dir)
    desc = _first(raw.get("desc"), (result.get("run_record") or {}).get("desc")
                  if isinstance(result.get("run_record"), dict) else None,
                  (run_record or {}).get("desc") if isinstance(run_record, dict) else None)
    desc_hash = raw.get("descHash") if isinstance(raw.get("descHash"), str) else None
    if not desc_hash and desc:
        desc_hash = _sha256(desc)
        notes.append("descHash 缺失，按单例 desc 现算（应与运行器冻结哈希一致）")
    model_name = _first(env.get("modelName") or None, env.get("modelConfigured") or None,
                        round_env.get("modelConfigured") or None)
    model_source = ("单例 env.modelName" if env.get("modelName") else
                    "单例 env.modelConfigured" if env.get("modelConfigured") else
                    "environment.json.modelConfigured" if round_env.get("modelConfigured") else None)
    if model_name is None:
        notes.append("实际模型名缺失（单例 env 与 environment.json 均未记录）")
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
    status = _first(raw.get("status"), result.get("status"))
    outcome = _first(raw.get("outcome"), result.get("outcome"))
    record_mode = result.get("mode")
    if record_mode in MODES and record_mode != mode:
        notes.append(f"结果记录 mode={record_mode!r} 与臂目录 mode={mode!r} 不一致（模式路由需核查）")
    # 运行器（双模式 E2E 封装）额外落盘的模式路由/模式事实/交付来源证据
    runner_arm = raw.get("arm")
    runner_attempts_count = _as_int(raw.get("attemptsCount"))
    runner_delivery = raw.get("delivery")
    mode_check = raw.get("modeCheck") if isinstance(raw.get("modeCheck"), dict) else None
    mode_policy = raw.get("modePolicy") if isinstance(raw.get("modePolicy"), dict) else None
    mode_facts = _mode_facts_view(mode_facts_raw)
    if runner_arm and runner_arm != mode:
        notes.append(f"运行器记录 arm={runner_arm!r} 与臂目录 mode={mode!r} 不一致"
                     "（模式路由需核查）")
    if mode_check and mode_check.get("ok") is False:
        notes.append("模式路由检查未通过：" + "，".join(
            str(x) for x in (mode_check.get("mismatches") or ["见 runnerFacts.modeCheck"])))
    if mode_policy and mode_policy.get("ok") is False:
        notes.append("任务结果级模式事实断言未通过：" + "；".join(
            str(x) for x in (mode_policy.get("errors") or [])[:3]))
    if mode_facts and mode_facts.get("ok") is False:
        notes.append("断言模式事实未通过：" + "；".join(mode_facts.get("errors") or [])[:3])
    desc_frozen = _as_bool(metrics.get("desc_frozen"))
    if desc_frozen is None:
        tier_metrics = metrics.get("requirement_tier")
        if isinstance(tier_metrics, dict):
            desc_frozen = _as_bool(tier_metrics.get("desc_frozen"))
    desc_hash_record = metrics.get("desc_hash")
    desc_hash_ok = None
    if isinstance(desc_hash_record, str) and desc_hash and isinstance(desc_hash, str):
        desc_hash_ok = desc_hash_record == desc_hash
        if not desc_hash_ok:
            notes.append("需求哈希与断言记录不一致（跑中改题风险，需核查）")
    elif desc_frozen is False:
        notes.append("运行需求原文与冻结案例不一致（跑中改题风险，需核查）")
    generic = _generic_state(task_ok, metrics, run_record, result)
    requirement = _requirement_state(metrics, task_ok)
    scale = _scale_state(metrics, result, run_record, desc)
    attempt_record_sources = {rid: src for rid, (rec, src) in attempt_records.items()
                              if rec is not None}
    timings = _timings_state(mode, outcome, raw, result, attempts, attempt_records,
                             run_record, run_source, notes)
    requests = _requests_state(mode, attempts, attempt_records, run_record, run_id, metrics,
                               notes)
    visual = _visual_state(mode, outcome, task_ok, metrics, result, run_record,
                           attempt_records, attempts, mode_facts, notes)
    delivery = _delivery_source(mode, outcome, attempts)
    if runner_delivery in MODES and delivery["source"] in MODES \
            and runner_delivery != delivery["source"]:
        notes.append(f"交付来源与运行器记录不一致：report={delivery['source']!r} "
                     f"runner={runner_delivery!r}")
    first_attempt = _first_attempt_state(mode, outcome, attempts, result, run_id, task_ok, notes)
    page_errors = raw.get("pageErrors")
    if isinstance(page_errors, dict):
        errors = [str(x) for x in (page_errors.get("errors") or [])]
        rejections = [str(x) for x in (page_errors.get("rejections") or [])]
        page_state = {"available": True, "errors": errors[:20], "rejections": rejections[:20],
                      "errorCount": len(errors), "rejectionCount": len(rejections)}
    else:
        page_state = {"available": False, "errors": None, "rejections": None,
                      "errorCount": None, "rejectionCount": None}
        notes.append("pageErrors 缺失：页面 JS 错误/unhandledrejection 未知")
    console = raw.get("console_errors") if isinstance(raw.get("console_errors"), list) else None
    page_state["consoleErrors"] = [str(x) for x in console][:20] if console is not None else None
    page_state["consoleErrorCount"] = len(console) if console is not None else None
    if page_state["errorCount"]:
        notes.append("页面 JS 错误非 0（页面可信性需核查）")
    shots = raw.get("screenshots") if isinstance(raw.get("screenshots"), list) else None
    artifacts = None
    if isinstance(run_record, dict) and isinstance(run_record.get("artifacts"), dict):
        artifacts = sorted(str(v) for v in run_record["artifacts"].values())
    elif isinstance(result.get("artifacts"), dict):
        artifacts = sorted(str(v) for v in result["artifacts"].values())
    evidence_dir = os.path.join(arm_dir, "evidence")
    single_attempt_outcomes = ("fidelity_success", "fidelity_degraded", "fast_success")
    facts_fallback_count = (mode_facts or {}).get("fallbackCount")
    if not attempt_run_ids:
        if run_id and (outcome in single_attempt_outcomes
                       or runner_attempts_count == 1
                       or (mode == "fidelity" and facts_fallback_count == 0)):
            attempt_run_ids = [run_id]  # 已确认只有一次尝试：唯一尝试就是最终 run
        else:
            attempt_run_ids = None
            notes.append("各次尝试 run_id 未知（缺少 attempts_detail，不用最终 run 冒充）")
    if attempts_source is None and outcome == "fast_fallback":
        notes.append("缺少 attempts_detail：保底任务的双尝试 run_id/耗时未知")
    if attempts_source:
        attempt_count = len(attempts) if attempts else None
    elif runner_attempts_count is not None:
        attempt_count = runner_attempts_count  # 运行器已按 result.attempts_detail 记录尝试数
    elif facts_fallback_count is not None:
        attempt_count = 1 + facts_fallback_count
    elif outcome in single_attempt_outcomes:
        attempt_count = 1
    elif outcome == "fast_fallback":
        attempt_count = 2
    else:
        attempt_count = None
    if (attempts_source and runner_attempts_count is not None
            and len(attempts) != runner_attempts_count):
        notes.append(f"尝试次数与运行器记录不一致：明细 {len(attempts)} 次，"
                     f"attemptsCount={runner_attempts_count}")
    fallback_used = bool(mode == "fidelity" and (
        outcome == "fast_fallback"
        or any(a.get("mode") == "fast" for a in attempts)
        or bool(result.get("fidelity_attempt_error"))
        or (facts_fallback_count or 0) > 0))
    arm.update({
        "name": _first(raw.get("name"), result.get("name")),
        "jobId": _first(raw.get("job_id"), raw.get("jobId"), result.get("job_id")),
        "runId": run_id, "attemptRunIds": attempt_run_ids,
        "attempts": attempts, "attemptsSource": attempts_source,
        "runRecordSource": run_source,
        "attemptRecordSources": attempt_record_sources,
        "descHash": desc_hash, "descHashConsistent": desc_hash_ok,
        "descFrozen": desc_frozen,
        "modelName": model_name, "modelNameSource": model_source,
        "status": status, "outcome": outcome,
        "taskOk": task_ok, "assertOk": assert_ok,
        "deliverySource": delivery["source"], "deliveryLabel": delivery["label"],
        "generic": generic, "requirementAssert": requirement, "scale": scale,
        "timings": timings, "requests": requests, "visualReview": visual,
        "pageErrors": page_state,
        "modeFacts": mode_facts,
        "runnerFacts": {"arm": runner_arm, "delivery": runner_delivery,
                        "attemptsCount": runner_attempts_count,
                        "modeCheck": mode_check, "modePolicy": mode_policy},
        "paths": {"record": _rel(record_path),
                  "evidenceDir": _rel(evidence_dir) if os.path.isdir(evidence_dir) else None,
                  "screenshots": [str(s) for s in shots] if shots is not None else None,
                  "artifacts": artifacts},
        "firstAttempt": first_attempt,
        "orchestration": {
            "attemptCount": attempt_count,
            "fallbackUsed": fallback_used,
            "fallbackRunIds": [a.get("runId") for a in attempts
                               if a.get("mode") == "fast" and a.get("runId")],
            "source": attempts_source,
        },
    })
    if timings.get("totalS") is None:
        notes.append("任务总耗时缺失（elapsedFinal/elapsedS 均为空）")
    if scale["notes"]:
        notes.append("规模字段缺失：" + "、".join(scale["notes"]))
    return arm


def _missing_arm(case_id, mode, reason):
    """缺臂占位：如实标 missing，不生成任何猜测数字。"""
    return {"case": case_id, "mode": mode, "recorded": False,
            "missingReason": reason, "notes": [f"缺失：{reason}"]}


# ---------------------------------------------------------------- 汇总统计
def summarize_mode(case_ids, arms, mode):
    """单模式汇总：交付/断言/四态/目标规模/耗时分位/请求中位/视觉/页面错误。"""
    rows = [arms[cid] for cid in case_ids if cid in arms and arms[cid].get("recorded")]
    missing_ids = [cid for cid in case_ids
                   if cid not in arms or not arms[cid].get("recorded")]
    delivered = [r for r in rows if r.get("taskOk") is True]
    asserted = [r for r in rows if r.get("assertOk") is True]
    outcomes = {}
    for row in rows:
        key = row.get("outcome") or "unknown"
        outcomes[key] = outcomes.get(key, 0) + 1
    four_state = {key: outcomes.get(key, 0) for key in STATE_ORDER}
    four_state["未记录/未知"] = outcomes.get("unknown", 0)
    target_evaluated = [r for r in delivered
                        if (r.get("scale") or {}).get("targetOk") is not None]
    target_met = [r for r in target_evaluated if r["scale"]["targetOk"] is True]
    elapsed_values = [(r.get("timings") or {}).get("totalS") for r in rows]
    draw_values = [((r.get("requests") or {}).get("draw") or {}).get("total") for r in rows]
    review_rounds = [((r.get("timings") or {}).get("reviewRounds")) for r in rows]
    revise_rounds = [((r.get("timings") or {}).get("reviseRounds")) for r in rows]
    visual_status, visual_scores = {}, []
    for row in rows:
        visual = row.get("visualReview") or {}
        status = visual.get("status") or "missing"
        visual_status[status] = visual_status.get(status, 0) + 1
        if _is_number(visual.get("score")):
            visual_scores.append(visual["score"])
    page_js = [r["pageErrors"]["errorCount"] for r in rows
               if (r.get("pageErrors") or {}).get("errorCount") is not None]
    page_rej = [r["pageErrors"]["rejectionCount"] for r in rows
                if (r.get("pageErrors") or {}).get("rejectionCount") is not None]
    return {
        "mode": mode, "total": len(case_ids), "recorded": len(rows),
        "missing": len(missing_ids), "missingIds": missing_ids,
        "delivered": len(delivered), "deliveredIds": [r["case"] for r in delivered],
        "asserted": len(asserted), "assertedIds": [r["case"] for r in asserted],
        "requirementEvaluated": sum(1 for r in rows
                                    if (r.get("requirementAssert") or {}).get("evaluated")),
        "requirementFailedIds": [r["case"] for r in rows
                                 if (r.get("requirementAssert") or {}).get("ok") is False],
        "outcomes": outcomes, "fourState": four_state,
        "targetScaleEvaluated": len(target_evaluated),
        "targetScaleMet": len(target_met),
        "targetScaleMetIds": [r["case"] for r in target_met],
        "elapsed": _quantiles(elapsed_values),
        "drawKnownCases": len([v for v in draw_values if _is_number(v)]),
        "drawMedian": _median(draw_values),
        "reviewRoundsMedian": _median(review_rounds),
        "reviseRoundsMedian": _median(revise_rounds),
        "visual": {"statuses": visual_status, "scored": len(visual_scores),
                   "median": _median(visual_scores),
                   "notReviewed": visual_status.get("not_reviewed", 0)},
        "pageJsErrors": sum(page_js) if len(page_js) == len(rows) else None,
        "pageRejections": sum(page_rej) if len(page_rej) == len(rows) else None,
        "pageErrorCases": [r["case"] for r in rows
                           if (r.get("pageErrors") or {}).get("errorCount")],
        "modeCheckFailedIds": [r["case"] for r in rows
                               if (((r.get("runnerFacts") or {}).get("modeCheck") or {})
                                   .get("ok") is False)],
        "modePolicyFailedIds": [r["case"] for r in rows
                                if (((r.get("runnerFacts") or {}).get("modePolicy") or {})
                                    .get("ok") is False)],
        "modeFactsFailedIds": [r["case"] for r in rows
                               if (r.get("modeFacts") or {}).get("ok") is False],
        "descHashMismatchIds": [r["case"] for r in rows
                                if r.get("descHashConsistent") is False],
        "descFrozenFailedIds": [r["case"] for r in rows if r.get("descFrozen") is False],
        "attemptCounts": {"single": sum(1 for r in rows
                                        if (r.get("orchestration") or {}).get("attemptCount") == 1),
                          "double": sum(1 for r in rows
                                        if (r.get("orchestration") or {}).get("attemptCount") == 2),
                          "unknown": sum(1 for r in rows
                                         if (r.get("orchestration") or {}).get("attemptCount")
                                         not in (1, 2))},
        "fallbackUsedIds": [r["case"] for r in rows
                            if (r.get("orchestration") or {}).get("fallbackUsed")],
        "doubleAttemptFailedIds": [r["case"] for r in rows
                                   if r.get("taskOk") is not True
                                   and (r.get("orchestration") or {}).get("attemptCount") == 2],
    }


def summarize_first_attempt(case_ids, fidelity_arms):
    """高保真首次尝试结果汇总（不含快速保底），与总编排结果分开统计。"""
    rows = [fidelity_arms[cid] for cid in case_ids
            if cid in fidelity_arms and fidelity_arms[cid].get("recorded")]
    first = [r for r in rows if (r.get("firstAttempt") or {}).get("available")]
    outcomes = {}
    for row in first:
        key = (row.get("firstAttempt") or {}).get("outcome") or "unknown"
        outcomes[key] = outcomes.get(key, 0) + 1
    delivered = [r for r in first if (r["firstAttempt"].get("ok") is True)]
    failed = [r for r in first if r["firstAttempt"].get("outcome") in ("failed", "cancelled")]
    return {
        "evaluated": len(first), "recorded": len(rows), "missing": len(case_ids) - len(rows),
        "outcomes": outcomes,
        "delivered": len(delivered), "deliveredIds": [r["case"] for r in delivered],
        "failed": len(failed), "failedIds": [r["case"] for r in failed],
        "elapsed": _quantiles([r["firstAttempt"].get("elapsedS") for r in first]),
        "fallbackTriggered": len([r for r in rows
                                  if (r.get("orchestration") or {}).get("fallbackUsed")]),
        "fallbackTriggeredIds": [r["case"] for r in rows
                                 if (r.get("orchestration") or {}).get("fallbackUsed")],
        "note": "首次尝试结果不含快速保底；走保底时总编排结果见 summary.fidelity",
    }


def pair_elapsed(case_ids, fast_arms, fidelity_arms):
    """同题耗时配对：逐例 fast 与 fidelity 总耗时差及中位数。"""
    rows = []
    for cid in case_ids:
        fast = (fast_arms.get(cid) or {}).get("timings") or {}
        fid = (fidelity_arms.get(cid) or {}).get("timings") or {}
        fast_s, fid_s = fast.get("totalS"), fid.get("totalS")
        if not (_is_number(fast_s) and _is_number(fid_s)):
            continue
        rows.append({"case": cid, "fastS": fast_s, "fidelityS": fid_s,
                     "deltaFastMinusFidelity": round(fast_s - fid_s, 2)})
    deltas = [r["deltaFastMinusFidelity"] for r in rows]
    return {"count": len(rows),
            "fastFaster": sum(1 for d in deltas if d < 0),
            "fidelityFaster": sum(1 for d in deltas if d > 0),
            "ties": sum(1 for d in deltas if d == 0),
            "medianDeltaFastMinusFidelity": _median(deltas),
            "rows": rows,
            "note": "本轮只有一轮，逐例差值与中位数只作本轮观察，不宣称统计显著"}


def _outcome_group(outcome):
    """四态归一为交付/失败/取消三组（fast_success 与 fidelity_success 不等价翻转）。"""
    if outcome in ("fidelity_success", "fidelity_degraded", "fast_fallback", "fast_success"):
        return "delivered"
    if outcome == "cancelled":
        return "cancelled"
    return "failed"


def build_flips(case_ids, fast_arms, fidelity_arms):
    """同案例结果翻转表：交付、需求断言（两侧均已评估）、交付状态不同的逐例留痕。"""
    rows = []
    for cid in case_ids:
        fast = fast_arms.get(cid) or {}
        fid = fidelity_arms.get(cid) or {}
        if not (fast.get("recorded") and fid.get("recorded")):
            continue
        fast_ok = fast.get("taskOk") is True
        fid_ok = fid.get("taskOk") is True
        dimensions = [("delivery", "交付", fast_ok, fid_ok)]
        fast_group = _outcome_group(fast.get("outcome"))
        fid_group = _outcome_group(fid.get("outcome"))
        # 四态按“交付/失败/取消”归一比较：两模式成功态名称天然不同，不算翻转。
        if fast_group != fid_group and fast_ok == fid_ok:
            dimensions.append(("outcome", "交付状态", fast_group, fid_group))
        fast_req = fast.get("requirementAssert") or {}
        fid_req = fid.get("requirementAssert") or {}
        if fast_req.get("evaluated") and fid_req.get("evaluated"):
            dimensions.append(("requirement", "需求断言",
                               fast_req.get("ok") is True, fid_req.get("ok") is True))
        for dimension, label, fast_value, fid_value in dimensions:
            if fast_value == fid_value:
                continue
            if dimension == "delivery":
                description = "仅快速交付" if fast_value else "仅高保真交付"
            elif dimension == "requirement":
                description = ("仅快速需求断言通过" if fast_value
                               else "仅高保真需求断言通过")
            else:
                description = (f"交付状态不同：快速 {fast.get('outcome')}（{fast_value}） vs "
                               f"高保真 {fid.get('outcome')}（{fid_value}）")
            rows.append({"case": cid, "dimension": dimension, "label": label,
                         "fast": fast_value, "fidelity": fid_value,
                         "description": description})
    by_dimension = {}
    for row in rows:
        by_dimension[row["dimension"]] = by_dimension.get(row["dimension"], 0) + 1
    return {
        "count": len(rows), "byDimension": by_dimension, "rows": rows,
        "fastOnlyDelivery": [r["case"] for r in rows
                             if r["dimension"] == "delivery" and r["fast"] is True],
        "fidelityOnlyDelivery": [r["case"] for r in rows
                                 if r["dimension"] == "delivery" and r["fidelity"] is True],
        "note": "未知/未评估的一侧不单独计为翻转（缺臂与未知字段见缺失明细）",
    }


def build_report(round_dir):
    """读取整轮目录并组装对比报告数据（不写盘）。"""
    case_ids, arm_specs, environment, notes = discover_round(round_dir)
    arms = {mode: {} for mode in MODES}
    missing = []
    for case_id in case_ids:
        specs = arm_specs.get(case_id) or {}
        for mode in MODES:
            spec = specs.get(mode)
            if spec is None:
                reason = ("案例目录缺失（environment.json cases 声明但无该目录）"
                          if not specs else f"缺少 {mode} 臂目录")
                arm = _missing_arm(case_id, mode, reason)
            elif not spec.get("path"):
                arm = _missing_arm(case_id, mode, spec.get("missingReason") or "单例记录缺失")
            else:
                arm = extract_arm(case_id, mode, spec["path"], environment)
                if not arm.get("recorded"):
                    arm["missingReason"] = "单例记录读取失败"
            arms[mode][case_id] = arm
            if not arm.get("recorded"):
                missing.append({"case": case_id, "mode": mode,
                                "reason": arm.get("missingReason") or "未记录",
                                "expectedPath": arm.get("recordPath")})
    cases = []
    for case_id in case_ids:
        fast, fid = arms["fast"].get(case_id) or {}, arms["fidelity"].get(case_id) or {}
        cases.append({"case": case_id,
                      "name": _first(fast.get("name"), fid.get("name"), case_id),
                      "arms": {"fast": fast, "fidelity": fid}})
    paired = sum(1 for row in cases
                 if row["arms"]["fast"].get("recorded")
                 and row["arms"]["fidelity"].get("recorded"))
    summary = {
        "fast": summarize_mode(case_ids, arms["fast"], "fast"),
        "fidelity": summarize_mode(case_ids, arms["fidelity"], "fidelity"),
        "fidelityFirstAttempt": summarize_first_attempt(case_ids, arms["fidelity"]),
        "pairs": pair_elapsed(case_ids, arms["fast"], arms["fidelity"]),
        "flips": build_flips(case_ids, arms["fast"], arms["fidelity"]),
    }
    fidelity_total = summary["fidelity"]
    fidelity_total["deliverySourceBreakdown"] = {
        "fidelity": len([c for c in fidelity_total["deliveredIds"]
                         if (arms["fidelity"].get(c) or {}).get("deliverySource") == "fidelity"]),
        "fast_fallback": len([c for c in fidelity_total["deliveredIds"]
                              if (arms["fidelity"].get(c) or {}).get("deliverySource")
                              == "fast_fallback"]),
    }
    # 保底“触发”与“成功交付”分开：触发保底但双尝试失败不算保底成功。
    fidelity_total["fallbackTriggered"] = len(fidelity_total["fallbackUsedIds"])
    fidelity_total["fallbackSuccessIds"] = [
        c for c in fidelity_total["deliveredIds"]
        if (arms["fidelity"].get(c) or {}).get("deliverySource") == "fast_fallback"]
    fidelity_total["fallbackSuccess"] = len(fidelity_total["fallbackSuccessIds"])
    complete = bool(case_ids) and not missing and not notes
    if not case_ids:
        notes.append("轮次目录内未发现 <CASE>/<fast|fidelity>/ 结构")
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "tool": "e2e_mode20_report",
        "roundDir": _rel(round_dir), "environment": environment or None,
        "targetRatioRule": f"bricks/targetBlocks >= {TARGET_RATIO_MIN}",
        "caseIds": case_ids, "pairedCases": paired, "totalCases": len(case_ids),
        "cases": cases, "summary": summary, "missing": missing, "notes": notes,
        "complete": complete,
        "evidenceLayout": {
            "record": "<round>/<CASE>/<fast|fidelity>/<CASE>.json",
            "runRecord": "单例 runRecord / result.run_record / 臂目录 evidence/run_<id>.json",
            "environment": "<round>/environment.json（可选）",
        },
    }


# ---------------------------------------------------------------- Markdown 报告
def _fmt(value):
    """表格单元格：None 统一写“未知”（缺失不用 0 冒充）。"""
    if value is None:
        return "未知"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _fmt_q(quantiles):
    quantiles = quantiles or {}
    return (f"P50 {_fmt(quantiles.get('p50'))} / P90 {_fmt(quantiles.get('p90'))}"
            f"（n={quantiles.get('n')}）")


def _fmt_ratio(ratio):
    return f"{ratio:.1%}" if _is_number(ratio) else "未知"


def _short(text, limit=120):
    text = str(text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _failures_cell(failures, limit=2):
    items = [str(x) for x in failures or []]
    if not items:
        return "—"
    text = "；".join(_short(x, 70) for x in items[:limit])
    return text + (f"（等 {len(items)} 项）" if len(items) > limit else "")


def _state_cell(state):
    """三态结论单元格（True/False/None → 通过/未通过+失败项/未知）。"""
    state = state or {}
    ok = state.get("ok")
    if ok is True:
        return "通过"
    if ok is False:
        return "未通过：" + _failures_cell(state.get("errors"))
    return "未知"


def _ids_cell(ids):
    """案例 id 列表单元格：无异常写“无”，否则写例数与 id。"""
    values = [str(item) for item in (ids or [])]
    return "无" if not values else f"{len(values)} 例：{', '.join(values)}"


def _request_cell(request):
    request = request or {}
    total = request.get("total")
    if total is None:
        return "未知"
    detail = [str(item.get("count")) if item.get("count") is not None else "?"
              for item in request.get("byAttempt") or []]
    if len(detail) > 1:
        return f"{total}（各尝试 {'/'.join(detail)}）"
    return str(total)


def _visual_cell(visual):
    visual = visual or {}
    score = visual.get("score")
    if _is_number(score):
        return f"{_fmt(score)}（{visual.get('source') or '未知来源'}）"
    if visual.get("status") == "not_reviewed":
        return "未评审（null，不补 0）"
    return f"未知（{visual.get('note') or '无说明'}）"


def _missing_row(case_id, mode, arm, columns):
    reason = (arm or {}).get("missingReason") or "缺失"
    return (f"| {case_id} | {mode} | 缺失：{_short(reason, 80)} |"
            + " — |" * (columns - 2))


def write_markdown(path, report):
    """生成 mode20-comparison.md：逐例并排全部字段 + 汇总 + 翻转表 + 缺失说明。"""
    env = report.get("environment") or {}
    summary = report.get("summary") or {}
    fast, fid = summary.get("fast") or {}, summary.get("fidelity") or {}
    first = summary.get("fidelityFirstAttempt") or {}
    pairs = summary.get("pairs") or {}
    flips = summary.get("flips") or {}
    lines = [
        "# 快速 / 高保真双模式同题对比报告", "",
        f"- 轮次目录：`{report.get('roundDir')}`",
        f"- 生成时间：{report.get('generatedAt')}；工具：`tools/e2e_mode20_report.py`",
        f"- 环境：标签 {_fmt(env.get('label'))}；{_fmt(env.get('startedAt'))} → "
        f"{_fmt(env.get('finishedAt'))}",
        f"- 代码 HEAD：`{_fmt(env.get('codeHead'))}`；工作区未提交：{_fmt(env.get('worktreeDirty'))}；"
        f"实际模型配置：`{_fmt(env.get('modelConfigured'))}`"
        f"（env 覆盖：{_fmt(env.get('modelEnvVar'))}）",
        f"- 并发：{_fmt(env.get('concurrency'))}；单例墙钟上限：{_fmt(env.get('timeoutS'))}s；"
        f"服务：{_fmt(env.get('baseUrl'))}",
        f"- 样本：发现案例 {report.get('totalCases')} 个；双臂齐全 {report.get('pairedCases')}；"
        f"缺臂/缺例 {len(report.get('missing') or [])} 项；报告完整：{_fmt(report.get('complete'))}",
        "- 口径：目标规模达标 = bricks/targetBlocks ≥ 0.5（冻结容差）；draw 请求数 = 同一运行内"
        " drawAttempts[].request 累计编号最大值（禁止求和；跨尝试分别取最大值后相加并标注）；"
        "快速视觉评审固定“未评审”（null，不补 0）；缺失/未知一律 null/“未知”。",
        "- 结论纪律：本轮只有一轮，以下均为“本轮观察”，不宣称统计显著或稳定规律。", "",
        "## 一、汇总对比（本轮观察）", "",
        "| 指标 | 快速 fast | 高保真 fidelity |", "|---|---|---|",
    ]
    table_rows = [
        ("记录数", f"{fast.get('recorded')}/{fast.get('total')}",
         f"{fid.get('recorded')}/{fid.get('total')}"),
        ("任务交付数（taskOk）", f"{fast.get('delivered')}/{fast.get('total')}",
         f"{fid.get('delivered')}/{fid.get('total')}"),
        ("需求断言通过数", f"{fast.get('asserted')}/{fast.get('total')}",
         f"{fid.get('asserted')}/{fid.get('total')}"),
        ("需求断言已评估数", fast.get("requirementEvaluated"),
         fid.get("requirementEvaluated")),
    ]
    for state in STATE_ORDER:
        table_rows.append((f"四态·{STATE_LABELS[state]}",
                           (fast.get("fourState") or {}).get(state, 0),
                           (fid.get("fourState") or {}).get(state, 0)))
    unknown_state = "未记录/未知"
    if (((fast.get("fourState") or {}).get(unknown_state, 0))
            or ((fid.get("fourState") or {}).get(unknown_state, 0))):
        table_rows.append((f"四态·{unknown_state}",
                           (fast.get("fourState") or {}).get(unknown_state, 0),
                           (fid.get("fourState") or {}).get(unknown_state, 0)))
    table_rows += [
        (f"目标规模达标数（≥{TARGET_RATIO_MIN:.0%}，已评估 n）",
         f"{fast.get('targetScaleMet')}/{fast.get('targetScaleEvaluated')}",
         f"{fid.get('targetScaleMet')}/{fid.get('targetScaleEvaluated')}"),
        ("任务耗时 P50 / P90（s，含失败任务，n=有耗时记录的终态任务）",
         _fmt_q(fast.get("elapsed")), _fmt_q(fid.get("elapsed"))),
        ("draw 请求数中位数", _fmt(fast.get("drawMedian")), _fmt(fid.get("drawMedian"))),
        ("视觉评审轮次中位数", _fmt(fast.get("reviewRoundsMedian")),
         _fmt(fid.get("reviewRoundsMedian"))),
        ("修订轮次中位数", _fmt(fast.get("reviseRoundsMedian")),
         _fmt(fid.get("reviseRoundsMedian"))),
        ("视觉评审", "未评审（全部，不补 0）",
         f"有分 {fid.get('visual', {}).get('scored')} 例，中位 "
         f"{_fmt(fid.get('visual', {}).get('median'))}"),
        ("页面 JS 错误 / unhandledrejection",
         f"{_fmt(fast.get('pageJsErrors'))} / {_fmt(fast.get('pageRejections'))}",
         f"{_fmt(fid.get('pageJsErrors'))} / {_fmt(fid.get('pageRejections'))}"),
        ("含快速保底例数", "—", len(fid.get("fallbackUsedIds") or [])),
        ("模式路由检查未过（modeCheck）",
         _ids_cell(fast.get("modeCheckFailedIds")), _ids_cell(fid.get("modeCheckFailedIds"))),
        ("任务结果级模式事实未过（modePolicy）",
         _ids_cell(fast.get("modePolicyFailedIds")),
         _ids_cell(fid.get("modePolicyFailedIds"))),
        ("断言模式事实未过（mode_facts）",
         _ids_cell(fast.get("modeFactsFailedIds")), _ids_cell(fid.get("modeFactsFailedIds"))),
        ("需求哈希/冻结原文不一致",
         _ids_cell([r for r in (fast.get("descHashMismatchIds") or [])
                    + (fast.get("descFrozenFailedIds") or [])]),
         _ids_cell([r for r in (fid.get("descHashMismatchIds") or [])
                    + (fid.get("descFrozenFailedIds") or [])])),
    ]
    lines += [f"| {label} | {fast_cell} | {fid_cell} |" for label, fast_cell, fid_cell in table_rows]
    lines += ["", "### 高保真首次尝试结果（不含快速保底）", "",
              f"- 可评估 {first.get('evaluated')}/{first.get('recorded')} 例；"
              f"结果分布：{json.dumps(first.get('outcomes') or {}, ensure_ascii=False)}",
              f"- 首次尝试成功/降级交付 {first.get('delivered')} 例：{first.get('deliveredIds') or []}",
              f"- 首次尝试失败/取消 {first.get('failed')} 例：{first.get('failedIds') or []}",
              f"- 首次尝试耗时 P50 / P90（s）：{_fmt_q(first.get('elapsed'))}",
              f"- 触发快速保底 {first.get('fallbackTriggered')} 例："
              f"{first.get('fallbackTriggeredIds') or []}", "",
              "### 高保真含快速保底的总编排结果", "",
              f"- 交付（taskOk）{fid.get('delivered')}/{fid.get('total')}；"
              f"需求断言通过 {fid.get('asserted')}/{fid.get('total')}；"
              f"需求断言已评估 {fid.get('requirementEvaluated')} 例",
              f"- 四态分布：{json.dumps(fid.get('outcomes') or {}, ensure_ascii=False)}",
              f"- 交付来源：高保真 {fid.get('deliverySourceBreakdown', {}).get('fidelity')} 例、"
              f"快速保底成功交付 "
              f"{fid.get('deliverySourceBreakdown', {}).get('fast_fallback')} 例",
              f"- 触发快速保底 {fid.get('fallbackTriggered', len(fid.get('fallbackUsedIds') or []))} 例："
              f"{fid.get('fallbackUsedIds') or []}",
              f"- 快速保底成功交付 {fid.get('fallbackSuccess', 0)} 例："
              f"{fid.get('fallbackSuccessIds') or []}",
              f"- 双尝试失败 {len(fid.get('doubleAttemptFailedIds') or [])} 例："
              f"{fid.get('doubleAttemptFailedIds') or []}",
              "- 说明：高保真臂走快速保底时，需求断言与视觉分针对最终交付产物；"
              "首次尝试结果单列于上节，二者不得混同。", "",
              "### 同题耗时配对（本轮观察）", "",
              f"- 可配对 {pairs.get('count')} 例；快速更快 {pairs.get('fastFaster')} 例、"
              f"高保真更快 {pairs.get('fidelityFaster')} 例、持平 {pairs.get('ties')} 例；"
              f"逐例（快速-高保真）差值中位 "
              f"{_fmt(pairs.get('medianDeltaFastMinusFidelity'))}s",
              f"- {pairs.get('note')}", "",
              "## 二、逐例并排（§6.6 全部字段）", "",
              "### 2.1 标识与状态", "",
              "| 案例 | 模式 | job_id | 最终 run_id | 各次尝试 run_id | 需求哈希 | 实际模型 | "
              "任务状态 | 四态 | 交付来源 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for case in report.get("cases") or []:
        for mode in MODES:
            arm = case["arms"].get(mode) or {}
            if not arm.get("recorded"):
                lines.append(_missing_row(case["case"], mode, arm, 10))
                continue
            attempts = ",".join(arm.get("attemptRunIds") or []) or "—"
            desc_hash = arm.get("descHash")
            desc_hash = (desc_hash[:16] + "…") if isinstance(desc_hash, str) else "未知"
            lines.append(
                f"| {case['case']} | {mode} | {_fmt(arm.get('jobId'))} | "
                f"{_fmt(arm.get('runId'))} | {attempts} | {desc_hash} | "
                f"{_fmt(arm.get('modelName'))} | {_fmt(arm.get('status'))} | "
                f"{_fmt(arm.get('outcome'))} | {_fmt(arm.get('deliveryLabel'))} |")
    lines += ["", "（需求哈希完整值见 JSON `cases[].arms[].descHash`；各次尝试 run 记录来源见 JSON。）", "",
              "### 2.2 断言与规模", "",
              "| 案例 | 模式 | 任务成功 | 通用底线 | 需求断言 | 需求失败项 | 目标块数 | 实际零件 | "
              "目标块数比 | 规模达标 | 体素 | 部位 | 算子 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for case in report.get("cases") or []:
        for mode in MODES:
            arm = case["arms"].get(mode) or {}
            if not arm.get("recorded"):
                lines.append(_missing_row(case["case"], mode, arm, 13))
                continue
            generic = arm.get("generic") or {}
            requirement = arm.get("requirementAssert") or {}
            scale = arm.get("scale") or {}
            requirement_text = ("通过" if requirement.get("ok") is True else
                                "未通过" if requirement.get("ok") is False else
                                "未知（" + (requirement.get("reason") or "未评估") + "）")
            lines.append(
                f"| {case['case']} | {mode} | {_fmt(arm.get('taskOk'))} | "
                f"{_fmt(generic.get('conclusion'))} | {requirement_text} | "
                f"{_failures_cell(requirement.get('failures'))} | "
                f"{_fmt(scale.get('targetBlocks'))} | {_fmt(scale.get('actualParts'))} | "
                f"{_fmt_ratio(scale.get('bricksRatio'))} | {_fmt(scale.get('targetOk'))} | "
                f"{_fmt(scale.get('voxels'))} | {_fmt(scale.get('parts'))} | "
                f"{_fmt(scale.get('ops'))} |")
    lines += ["", "### 2.3 耗时与请求", "",
              "| 案例 | 模式 | 总耗时(s) | 高保真首次尝试(s) | 快速保底(s) | 视觉评审(s) | "
              "视觉修订(s) | draw 请求 | 评审轮次 | 修订轮次 | 视觉评审分 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for case in report.get("cases") or []:
        for mode in MODES:
            arm = case["arms"].get(mode) or {}
            if not arm.get("recorded"):
                lines.append(_missing_row(case["case"], mode, arm, 11))
                continue
            timings = arm.get("timings") or {}
            requests = arm.get("requests") or {}
            lines.append(
                f"| {case['case']} | {mode} | {_fmt(timings.get('totalS'))} | "
                f"{_fmt(timings.get('firstAttemptS'))} | {_fmt(timings.get('fallbackS'))} | "
                f"{_fmt(timings.get('reviewS'))} | {_fmt(timings.get('reviseS'))} | "
                f"{_request_cell(requests.get('draw'))} | "
                f"{_fmt(timings.get('reviewRounds'))} | {_fmt(timings.get('reviseRounds'))} | "
                f"{_visual_cell(arm.get('visualReview'))} |")
    lines += ["", "（draw 请求按同一运行内累计编号最大值统计；括号内为各尝试分别计数。"
              "评审/修订轮次来自 run 记录 timeline 阶段事件，缺失时写“未知”；"
              "高保真首次尝试/快速保底耗时为各尝试 result.elapsed_s，总耗时为浏览器任务墙钟"
              "（elapsedFinal）；各尝试 run 记录来源见 JSON `attemptRecordSources`。）", "",
              "### 2.4 页面错误与证据", "",
              "| 案例 | 模式 | JS 错误 | unhandledrejection | console.error | 截图数 | 最终产物 |",
              "|---|---|---|---|---|---|---|"]
    for case in report.get("cases") or []:
        for mode in MODES:
            arm = case["arms"].get(mode) or {}
            if not arm.get("recorded"):
                lines.append(_missing_row(case["case"], mode, arm, 7))
                continue
            page = arm.get("pageErrors") or {}
            paths = arm.get("paths") or {}
            shots = paths.get("screenshots")
            artifacts = paths.get("artifacts")
            lines.append(
                f"| {case['case']} | {mode} | {_fmt(page.get('errorCount'))} | "
                f"{_fmt(page.get('rejectionCount'))} | {_fmt(page.get('consoleErrorCount'))} | "
                f"{_fmt(len(shots) if isinstance(shots, list) else None)} | "
                f"{_fmt(len(artifacts) if isinstance(artifacts, list) else None)} |")
    lines += ["", "（截图与最终产物完整路径见 JSON `cases[].arms[].paths`；最终/各次 run 记录来源见 "
              "`cases[].arms[].runRecordSource` 与 `attemptRecordSources`。）", "",
              "### 2.5 高保真首次尝试 vs 含快速保底总编排", "",
              "| 案例 | 首次 run_id | 首次结果 | 首次耗时(s) | 首次失败类别 | 首次评审标记 | "
              "总编排四态 | 交付来源 | 是否触发保底 | 保底 run_id |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for case in report.get("cases") or []:
        arm = case["arms"].get("fidelity") or {}
        if not arm.get("recorded"):
            lines.append(_missing_row(case["case"], "fidelity", arm, 10))
            continue
        first_state = arm.get("firstAttempt") or {}
        orchestration = arm.get("orchestration") or {}
        failure_kind = first_state.get("failureKind") or "—"
        if first_state.get("failureStage"):
            failure_kind = f"{failure_kind}/{first_state.get('failureStage')}"
        fallback_ids = orchestration.get("fallbackRunIds") or []
        lines.append(
            f"| {case['case']} | {_fmt(first_state.get('runId'))} | "
            f"{_fmt(first_state.get('outcome'))} | {_fmt(first_state.get('elapsedS'))} | "
            f"{failure_kind} | {_fmt(first_state.get('reviewFlag'))} | "
            f"{_fmt(arm.get('outcome'))} | {_fmt(arm.get('deliveryLabel'))} | "
            f"{'是' if orchestration.get('fallbackUsed') else '否'} | "
            f"{','.join(fallback_ids) if fallback_ids else '—'} |")
    lines += ["", "### 2.6 同案例结果翻转表", "",
              "| 案例 | 维度 | 快速 | 高保真 | 说明 |", "|---|---|---|---|---|"]
    if flips.get("rows"):
        for row in flips["rows"]:
            lines.append(f"| {row.get('case')} | {row.get('label')} | "
                         f"{_fmt(row.get('fast'))} | {_fmt(row.get('fidelity'))} | "
                         f"{row.get('description')} |")
    else:
        lines.append("| — | — | — | — | 本轮两模式在交付 / 需求断言 / 四态上无翻转 |")
    lines += ["", f"翻转统计：共 {flips.get('count')} 项（按维度："
              f"{json.dumps(flips.get('byDimension') or {}, ensure_ascii=False)}）；"
              f"仅快速交付 {flips.get('fastOnlyDelivery') or []}；"
              f"仅高保真交付 {flips.get('fidelityOnlyDelivery') or []}。", "",
              "### 2.7 模式路由与模式事实（§6.7）", "",
              "| 案例 | 模式 | 运行器 arm | 路由检查 modeCheck | 结果级模式事实 modePolicy | "
              "断言模式事实 mode_facts | 交付来源（运行器） | 运行器尝试数 |",
              "|---|---|---|---|---|---|---|---|"]
    for case in report.get("cases") or []:
        for mode in MODES:
            arm = case["arms"].get(mode) or {}
            if not arm.get("recorded"):
                lines.append(_missing_row(case["case"], mode, arm, 8))
                continue
            runner = arm.get("runnerFacts") or {}
            lines.append(
                f"| {case['case']} | {mode} | {_fmt(runner.get('arm'))} | "
                f"{_state_cell(runner.get('modeCheck'))} | "
                f"{_state_cell(runner.get('modePolicy'))} | "
                f"{_state_cell(arm.get('modeFacts'))} | "
                f"{_fmt(runner.get('delivery'))} | {_fmt(runner.get('attemptsCount'))} |")
    lines += ["", "（modeCheck/modePolicy 由运行器落盘；mode_facts 由 tools/e2e_assert_mode20.py "
              "写入断言 metrics；均缺失时如实写“未知”，不推断通过。）", "",
              "## 三、缺失与未知（不得用 0 冒充）", ""]
    missing = report.get("missing") or []
    if missing:
        lines += ["| 案例 | 模式 | 原因 | 期望路径 |", "|---|---|---|---|"]
        for item in missing:
            lines.append(f"| {item.get('case')} | {item.get('mode')} | "
                         f"{_short(item.get('reason'), 100)} | "
                         f"{_short(item.get('expectedPath'), 120)} |")
    else:
        lines.append("- 缺臂/缺例：无（双臂记录齐全）。")
    if report.get("notes"):
        lines += ["", "轮次级说明："] + [f"- {note}" for note in report["notes"]]
    unknown_notes = []
    for case in report.get("cases") or []:
        for mode in MODES:
            arm = case["arms"].get(mode) or {}
            for note in arm.get("notes") or []:
                unknown_notes.append(f"- {case['case']} / {mode}：{note}")
    lines += ["", "逐例 null/未知字段说明："] + (unknown_notes or ["- 无。"])
    lines += ["", "## 四、口径与未覆盖边界", "",
              "- 快速视觉评审：按需求冻结口径固定记为“未评审”（score=null），绝不与 0 分混同。",
              "- 高保真首次尝试与含快速保底的总编排结果分开报告；保底成功的最终交付视为快速产物，"
              "不得计入高保真成功。",
              "- 评审/修订请求数优先取显式记录；缺失时按 run 记录 timeline 阶段轮次近似并标注来源；"
              "draw 请求数按同一运行内累计编号最大值统计（禁止求和）。",
              "- 本轮只有一轮真实 E2E；多轮统计稳定性、更多并发、移动端浏览器不在本轮覆盖范围。",
              "- 本报告只读本地证据，不发起模型/网络请求；证据路径见 JSON `cases[].arms[].paths`。"]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


# ---------------------------------------------------------------- 落盘与主流程
def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def write_outputs(out_dir, report, json_only=False, md_only=False):
    """按 --json-only/--md-only 写出报告，返回实际写出的路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    if not md_only:
        path = os.path.join(out_dir, "mode20-comparison.json")
        report["outDir"] = _rel(out_dir)
        _atomic_write(path, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
        written.append(path)
    if not json_only:
        path = os.path.join(out_dir, "mode20-comparison.md")
        write_markdown(path, report)
        written.append(path)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="快速/高保真双模式同题对比分析器与汇总报告器（需求 §6.6/§6.7）")
    ap.add_argument("--round", required=True, help="双模式轮次目录（含 <CASE>/<fast|fidelity>/）")
    ap.add_argument("--out", default=None, help="输出目录（默认写回轮次目录）")
    mode_group = ap.add_mutually_exclusive_group()
    mode_group.add_argument("--json-only", action="store_true", help="只写 mode20-comparison.json")
    mode_group.add_argument("--md-only", action="store_true", help="只写 mode20-comparison.md")
    args = ap.parse_args(argv)
    round_dir = os.path.abspath(args.round)
    if not os.path.isdir(round_dir):
        log(f"❌ 轮次目录不存在：{round_dir}")
        return 2
    report = build_report(round_dir)
    out_dir = os.path.abspath(args.out) if args.out else round_dir
    try:
        written = write_outputs(out_dir, report, json_only=args.json_only, md_only=args.md_only)
    except OSError as exc:
        log(f"❌ 报告写出失败：{type(exc).__name__}: {exc}")
        return 2
    summary = report["summary"]
    fast, fid = summary["fast"], summary["fidelity"]
    log(f"案例 {report['totalCases']} 个（双臂齐全 {report['pairedCases']}），"
        f"缺臂/缺例 {len(report['missing'])} 项")
    log(f"快速：交付 {fast['delivered']}/{fast['total']}，断言 {fast['asserted']}/{fast['total']}，"
        f"耗时 P50/P90 {fast['elapsed']['p50']}/{fast['elapsed']['p90']}s")
    log(f"高保真：交付 {fid['delivered']}/{fid['total']}，断言 {fid['asserted']}/{fid['total']}，"
        f"首次尝试交付 {summary['fidelityFirstAttempt']['delivered']} 例，"
        f"保底 {len(fid['fallbackUsedIds'])} 例")
    log(f"翻转 {summary['flips']['count']} 项；报告完整={report['complete']}")
    for path in written:
        log(f"写出 {_rel(path)}")
    if not report["complete"]:
        log("⚠ 样本不完整或环境证据缺失：报告已如实标注 missing，退出码 2")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
