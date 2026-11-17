# -*- coding: utf-8 -*-
"""历史真实交付证据的「测量口径重算」工具（验收用）。

只读扫描 ``artifacts/e2e-20/*/`` 下的单例 JSON（含 ``runRecord`` / ``result`` /
``assertion``），对每条记录独立重算旧/新两套口径：

1. draw 请求数：旧 ``sum(drawAttempts[].request)`` vs 新
   ``max(drawAttempts[].request)``（空列表为 0）。``request`` 是累计编号而不是
   增量，求和会把 3 次请求算成 1+2+3=6。
2. 视觉分：run 记录 ``review.scores.overall``（旧记录为空）与任务
   ``result.review.scores.overall``（补入来源），给出生效评审与恢复标记。
3. 需求断言结论：分别用旧口径记录与新口径记录跑
   C/H→``e2e_assert_20.check_objects``、G→``e2e_assert_g.check_objects_g``、
   N→``e2e_assert_new20.check_objects_n``，比较 ``assertion_ok`` /
   ``assertion_errors`` 是否改变；不一致必须逐条列出，不得掩盖。
4. 元数据：runId、任务四态、耗时、target_blocks、bricks、bricks_ratio、
   最终门禁、统一校验、页面截图与 JS 错误。

输出 ``{out}/recompute.json`` 与 ``{out}/recompute.md``（逐例表格 + 分组汇总 +
与方案声明数字的对照），**逐例可查，不只给结论**；实测与方案 43/25 不同时如实
标出差异，绝不改数据凑数。

用法::

    python -m tools.recompute_caliber
    python -m tools.recompute_caliber --dirs 20261108-gc6-on,20261109-cleanup-r0 \
        --out artifacts/analysis-caliber-20261114

可测试纯函数 API：``load_records`` / ``recompute_record`` / ``aggregate`` /
``render_markdown`` / ``draw_request_stats`` / ``review_sources`` /
``compare_assertions``。
"""
import argparse
import glob
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_ROOT = os.path.join("artifacts", "e2e-20")
DEFAULT_OUT = os.path.join("artifacts", "analysis-caliber-20261114")
SKIP_FILES = {"environment.json", "summary.json"}

# 声明的数字（只用于对照，绝不用于改数据）。
PLAN_DECLARED = {
    "case_set": "recent12",
    "cases": 12,
    "corrected": 8,
    "old_total": 43,
    "new_total": 25,
    "review_recovered": 11,
    "note": "方案 §4.1：留存 12 个真实交付案例重算：8 个请求数误差被纠正，"
            "合计由 43 回到 25；11 个已有任务评审的案例恢复真实视觉分。",
}

# 候选集合分组（按目录名精确匹配；None 表示全部）。
DEFAULT_GROUPS = {
    "gc6": ["20261108-gc6-off", "20261108-gc6-on"],
    "recent12": ["20261108-gc6-on", "20261109-cleanup-r0", "20261109-cleanup-r1"],
    "all": None,
}

# 案例定义单源（按前缀分派；C/H 走 e2e_cases_20 + batch2，N 走 new20，G 走 g）。
_CASE_SOURCES = (
    ("tools.e2e_cases_20", "CASES"),
    ("tools.e2e_cases_batch2", "NEW_CASES"),
    ("tools.e2e_cases_new20", "N_CASES"),
    ("tools.e2e_cases_g", "G_CASES"),
    ("tools.e2e_cases_extra", "EXTRA_CASES"),
)

__all__ = ["load_records", "recompute_record", "aggregate", "render_markdown",
           "draw_request_stats", "review_overall", "review_sources",
           "compare_assertions", "build_report", "main", "load_case_assets"]


# ================================================================ 证据加载层
def iter_record_paths(root, dirs=None):
    """列出待重算的单例记录 ``[(dir_name, path)]``。

    ``dirs`` 为目录名列表（相对 ``root``）或绝对路径；None 表示自动发现
    ``root`` 下所有含 JSON 的子目录。自动跳过 environment/summary。
    """
    root_abs = root if os.path.isabs(root) else os.path.join(ROOT, root)
    if dirs:
        dir_paths = [d if os.path.isabs(d) else os.path.join(root_abs, d) for d in dirs]
    else:
        dir_paths = sorted(p for p in glob.glob(os.path.join(root_abs, "*")) if os.path.isdir(p))
    found = []
    for dir_path in dir_paths:
        for path in sorted(glob.glob(os.path.join(dir_path, "*.json"))):
            if os.path.basename(path) in SKIP_FILES:
                continue
            found.append((os.path.basename(dir_path), path))
    return found


def load_records(root=DEFAULT_ROOT, dirs=None, warnings=None):
    """扫描并加载单例记录，返回 entry 列表（含原始 record）。

    只接受含 ``runRecord`` 的 JSON（单例交付记录）；其它文件记入 warnings。
    """
    warnings = warnings if warnings is not None else []
    entries = []
    for dir_name, path in iter_record_paths(root, dirs):
        try:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError) as exc:
            warnings.append({"path": path, "error": f"读取失败：{exc}"})
            continue
        if not isinstance(record, dict) or "runRecord" not in record:
            warnings.append({"path": path, "error": "缺少 runRecord，非单例交付记录，已跳过"})
            continue
        entries.append({
            "path": path, "dir": dir_name,
            "case": str(record.get("case") or os.path.basename(path)[:-5]),
            "record": record,
        })
    return entries


def find_case_def(case_id):
    """按案例编号取案例定义（C/H/G/N 单源分派）；找不到返回 None。"""
    wanted = str(case_id or "").upper()
    for module_name, attr in _CASE_SOURCES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for case in getattr(module, attr, []) or []:
            if str(case.get("id", "")).upper() == wanted:
                return case
    return None


def load_run_record(entry, warnings):
    """取该例 run 记录：优先 artifacts/run_<runId>.json，回退单例 runRecord。

    两者应完全一致；不一致时如实记 warnings（重算仍用冻结的单例 runRecord，
    因为它是 E2E 当时的交付证据快照）。
    """
    run_record = entry["record"].get("runRecord") or {}
    run_id = entry["record"].get("runId") or run_record.get("runId")
    path = os.path.join(ROOT, "artifacts", f"run_{run_id}.json")
    if run_id and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                disk = json.load(f)
            if json.dumps(disk, sort_keys=True) != json.dumps(run_record, sort_keys=True):
                warnings.append({"case": entry["case"], "dir": entry["dir"],
                                 "error": f"单例 runRecord 与 artifacts/run_{run_id}.json 不一致，"
                                          f"重算采用单例冻结版本"})
        except (OSError, ValueError) as exc:
            warnings.append({"case": entry["case"], "dir": entry["dir"],
                             "error": f"读取 artifacts/run_{run_id}.json 失败：{exc}"})
    return run_record, run_id


def load_case_assets(entry, run_record, warnings):
    """加载最终版本的 model/solution 产物；返回 (model, solution, 缺失原因列表)。"""
    revision = run_record.get("revision")
    rid = f"r{revision:03d}" if isinstance(revision, int) else str(revision or "")
    artifacts = run_record.get("artifacts") or {}
    names = {"model": artifacts.get(f"model_{rid}"), "solution": artifacts.get(f"solution_{rid}")}
    assets, missing = {}, []
    search_dirs = [os.path.join(ROOT, "artifacts")]
    case_dir = entry["record"].get("caseDir")
    if case_dir:
        search_dirs += [case_dir, os.path.join(case_dir, "evidence")]
    for kind, name in names.items():
        if not name:
            missing.append(f"{kind} 未在 run 记录 artifacts 中登记（revision={rid or '空'}）")
            assets[kind] = None
            continue
        for base in search_dirs:
            path = os.path.join(base, name)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        assets[kind] = json.load(f)
                except (OSError, ValueError) as exc:
                    missing.append(f"{kind} 读取失败：{name}（{exc}）")
                    assets[kind] = None
                break
        else:
            missing.append(f"{kind} 产物文件不存在：{name}")
            assets[kind] = None
    for reason in missing:
        warnings.append({"case": entry["case"], "dir": entry["dir"], "error": reason})
    return assets["model"], assets["solution"], missing


def final_gate_summary(run_record):
    """最终门禁结论（与断言器同口径的自实现版，不依赖正在修改的断言模块）。"""
    if "finalGateReplay" in run_record:
        replay = run_record.get("finalGateReplay")
        if isinstance(replay, dict):
            return {"source": "replay", "ok": replay.get("ok"),
                    "errors": [str(e) for e in (replay.get("errors") or [])]}
        return {"source": "replay", "ok": None, "errors": []}
    if run_record.get("gateFailed") or run_record.get("gate_failed"):
        return {"source": "legacy", "ok": False,
                "errors": run_record.get("gateErrors") or run_record.get("gate_errors") or []}
    return {"source": "legacy", "ok": True, "errors": []}


def validation_summary(record, solution):
    """统一校验结论：任务结果 / 方案缓存 / 保存的断言指标，依次取第一个可用来源。"""
    result = record.get("result") or {}
    for source, holder in (("result.validation", result),
                           ("solution.validation", solution or {})):
        value = holder.get("validation")
        if isinstance(value, dict):
            return {"ok": value.get("ok"), "source": source}
    metrics = ((record.get("assertion") or {}).get("metrics") or {})
    if "validation_ok" in metrics:
        return {"ok": metrics.get("validation_ok"), "source": "assertion.metrics"}
    return {"ok": None, "source": "none"}


def task_state(record, run_record):
    """任务四态标签：交付 / 降级交付 / 失败 / 未知。"""
    ok = run_record.get("ok")
    status = record.get("status")
    outcome = record.get("outcome")
    if ok is False or status == "error" or outcome == "failed":
        return "failed"
    if ok is True and isinstance(outcome, str) and "degrad" in outcome:
        return "delivered_degraded"
    if ok is True:
        return "delivered"
    return "unknown"


def page_error_count(record):
    """页面 JS 错误/拒绝数（单例 pageErrors 结构）。"""
    page_errors = record.get("pageErrors") or {}
    return {"errors": len(page_errors.get("errors") or []),
            "rejections": len(page_errors.get("rejections") or [])}


def saved_assertion(record):
    """E2E 当时留存的断言结论（任务失败无产物时断言被跳过，这本身就是证据）。"""
    assertion = record.get("assertion") or {}
    metrics = assertion.get("metrics") or {}
    return {
        "skipped": assertion.get("skipped"),
        "assert_ok_top": record.get("assertOk"),
        "metrics_assertion_ok": metrics.get("assertion_ok"),
        "metrics_assertion_error_count": len(metrics.get("assertion_errors") or []),
        "metrics_assertion_errors": [str(e) for e in (metrics.get("assertion_errors") or [])],
    }


# ================================================================ 纯函数：口径
def draw_request_stats(attempts):
    """draw 请求数双口径统计（``attempts`` 为 run 记录的 drawAttempts 列表）。

    ``request`` 是累计编号（1,2,3…）不是增量：旧口径求和会高估，新口径取最大值。
    空列表 / 非法值按 0 计；跳号序列（如 1,2,5）取最大值仍然正确。
    返回 attempts / sequence / old_sum / new_max / corrected / delta。
    """
    sequence = []
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        try:
            value = int(attempt.get("request") or 0)
        except (TypeError, ValueError):
            value = 0
        sequence.append(value)
    old_sum = sum(sequence)
    new_max = max(sequence) if sequence else 0
    return {"attempts": len(attempts or []), "sequence": sequence, "old_sum": old_sum,
            "new_max": new_max, "corrected": old_sum != new_max, "delta": old_sum - new_max}


def review_overall(review):
    """从评审 JSON 取 ``scores.overall``；缺失/非法返回 None（不猜测）。"""
    if not isinstance(review, dict):
        return None
    scores = review.get("scores")
    if not isinstance(scores, dict):
        return None
    value = scores.get("overall")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def review_sources(run_record, result):
    """视觉分三来源与恢复标记。

    ``review_from_run_record``：run 记录 ``review.scores.overall``（旧记录为空）。
    ``review_fallback_from_result``：任务 ``result.review.scores.overall``。
    ``effective_review``：前者缺失时用后者；``recovered`` 表示靠任务评审补回。
    """
    run_overall = review_overall((run_record or {}).get("review"))
    fallback_overall = review_overall((result or {}).get("review"))
    if run_overall is not None:
        source, effective, recovered = "run_record", run_overall, False
    elif fallback_overall is not None:
        source, effective, recovered = "result_fallback", fallback_overall, True
    else:
        source, effective, recovered = "none", None, False
    return {"review_from_run_record": run_overall,
            "review_fallback_from_result": fallback_overall,
            "effective_review": effective, "review_source": source,
            "recovered": recovered}


def compare_assertions(old_metrics, new_metrics):
    """比较旧/新口径两次断言结果是否改变结论。

    只比较结论：``assertion_ok`` 与 ``assertion_errors`` 文本集合；任一改变即
    ``conclusion_changed=True`` 并逐条列出新增/消失错误。任一结果不可用时
    ``available=False``（不伪造结论）。
    """
    if not isinstance(old_metrics, dict) or not isinstance(new_metrics, dict) \
            or old_metrics.get("assertion_ok") is None:
        return {"available": False, "conclusion_changed": None,
                "reason": "缺少可比较的断言结果"}
    old_ok = bool(old_metrics.get("assertion_ok"))
    new_ok = bool(new_metrics.get("assertion_ok"))
    old_errors = [str(e) for e in (old_metrics.get("assertion_errors") or [])]
    new_errors = [str(e) for e in (new_metrics.get("assertion_errors") or [])]
    return {
        "available": True, "old_ok": old_ok, "new_ok": new_ok,
        "old_error_count": len(old_errors), "new_error_count": len(new_errors),
        "old_errors": old_errors, "new_errors": new_errors,
        "added_errors": [e for e in new_errors if e not in old_errors],
        "removed_errors": [e for e in old_errors if e not in new_errors],
        "conclusion_ok_changed": old_ok != new_ok,
        "conclusion_errors_changed": old_errors != new_errors,
        "conclusion_changed": (old_ok != new_ok) or (old_errors != new_errors),
    }


# ================================================================ 单条重算
def _rel_path(path):
    """相对项目根的展示路径；跨盘/异常时回退绝对路径（测试临时目录会跨盘）。"""
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def assertion_checker(case_id):
    """按案例编号前缀分派断言器：G→g，N→new20，C/H→20。"""
    prefix = str(case_id or "")[:1].upper()
    if prefix == "G":
        from tools.e2e_assert_g import check_objects_g as checker
        return checker
    if prefix == "N":
        from tools.e2e_assert_new20 import check_objects_n as checker
        return checker
    from tools.e2e_assert_20 import check_objects as checker
    return checker


def _call_checker(checker, record, model, solution, case_def, review_fallback):
    """调用断言器，兼容「有/无 review_fallback 形参」两种版本。"""
    import inspect
    if "review_fallback" in inspect.signature(checker).parameters:
        return checker(record, model, solution, case_def, review_fallback=review_fallback)
    new_record = dict(record)
    if review_fallback:
        new_record["review"] = review_fallback
    return checker(new_record, model, solution, case_def)


def _assertion_compare(entry, run_record, warnings, assets=None):
    """旧/新口径断言对比；产物缺失或异常只记录原因，不抛、不编造。

    ``assets`` 传入已加载的 (model, solution)，避免重复读取与重复告警。
    """
    record = entry["record"]
    if assets is None:
        model, solution, missing = load_case_assets(entry, run_record, warnings)
    else:
        model, solution, missing = assets[0], assets[1], []
    case_def = find_case_def(entry["case"])
    problems = list(missing)
    if case_def is None:
        problems.append(f"缺少案例定义 {entry['case']}")
    if model is None or solution is None or case_def is None:
        return {"available": False, "reason": "；".join(problems) or "产物缺失"}
    checker = assertion_checker(entry["case"])
    fallback = (record.get("result") or {}).get("review")
    try:
        old_metrics = _call_checker(checker, run_record, model, solution, case_def, None)[1]
        new_metrics = _call_checker(checker, run_record, model, solution, case_def, fallback)[1]
    except BaseException as exc:  # noqa: BLE001 - 断言失败只记录，不中断报告
        return {"available": False, "reason": f"断言执行异常：{type(exc).__name__}: {exc}"}
    result = compare_assertions(old_metrics, new_metrics)
    result.update({
        "draw_requests_old_metrics": old_metrics.get("draw_requests"),
        "draw_requests_new_metrics": new_metrics.get("draw_requests"),
        "review_overall_old": old_metrics.get("review_overall"),
        "review_overall_new": new_metrics.get("review_overall"),
    })
    return result


def recompute_record(entry, run_assertions=True, warnings=None):
    """重算一条单例记录，返回逐例行 dict（所有口径值均可复核）。

    ``entry``：``load_records`` 的条目（path/dir/case/record）。
    ``run_assertions``：是否真跑旧/新两次断言（合成数据测试可关）。
    """
    warnings = warnings if warnings is not None else []
    record = entry["record"]
    run_record, run_id = load_run_record(entry, warnings)
    draw = draw_request_stats(run_record.get("drawAttempts") or [])
    reviews = review_sources(run_record, record.get("result") or {})
    scale = run_record.get("scaleMetrics")
    scale = scale if isinstance(scale, dict) else {}
    desc = run_record.get("desc") or record.get("desc")
    target, target_source = scale.get("targetBlocks"), "scaleMetrics"
    if target is None:
        from legogod.plan_scale import parse_target_blocks
        target = parse_target_blocks(desc)
        target_source = "parse_target_blocks" if target is not None else "none"
    bricks = scale.get("bricks")
    if bricks is None:
        bricks = scale.get("actualParts")
    assets = load_case_assets(entry, run_record, warnings) if run_assertions else (None, None, [])
    return {
        "seq": entry.get("seq"), "dir": entry["dir"], "case": entry["case"],
        "path": _rel_path(entry["path"]),
        "run_id": run_id,
        "task_state": task_state(record, run_record),
        "status": record.get("status"), "outcome": record.get("outcome"),
        "ok": run_record.get("ok"), "error": run_record.get("error"),
        "elapsed_s": run_record.get("elapsedS"),
        "attempts": draw["attempts"], "request_sequence": draw["sequence"],
        "draw_requests_old": draw["old_sum"], "draw_requests_new": draw["new_max"],
        "draw_request_corrected": draw["corrected"], "draw_request_delta": draw["delta"],
        "review_from_run_record": reviews["review_from_run_record"],
        "review_fallback_from_result": reviews["review_fallback_from_result"],
        "effective_review": reviews["effective_review"],
        "review_source": reviews["review_source"],
        "review_recovered": reviews["recovered"],
        "target_blocks": target, "target_blocks_source": target_source,
        "bricks": bricks, "bricks_ratio": scale.get("targetBlocksRatio"),
        "final_gate": final_gate_summary(run_record),
        "validation": validation_summary(record, assets[1]),
        "page_errors": page_error_count(record),
        "screenshots": record.get("screenshots") or [],
        "saved_assertion": saved_assertion(record),
        "assertion": (_assertion_compare(entry, run_record, warnings, assets)
                      if run_assertions
                      else {"available": False, "reason": "未要求重算断言"}),
    }


# ================================================================ 分组聚合
def aggregate(rows, groups=None):
    """按候选集合分组汇总（默认 gc6 / recent12 / all）。

    每组给出：案例数、请求数旧合计/新合计、被纠正例数、有任务评审例数、
    视觉分恢复例数、断言结论变化数（含无法重算例数与原因）。
    """
    groups = groups or DEFAULT_GROUPS
    summaries = []
    for name, dirs in groups.items():
        subset = [r for r in rows if dirs is None or r["dir"] in dirs]
        compared = [r for r in subset if (r.get("assertion") or {}).get("available")]
        unavailable = [r for r in subset if not (r.get("assertion") or {}).get("available")]
        changed = [r for r in compared if r["assertion"].get("conclusion_changed")]
        summaries.append({
            "group": name, "dirs": sorted({r["dir"] for r in subset}),
            "cases": len(subset),
            "case_ids": [f"{r['dir']}/{r['case']}" for r in subset],
            "draw_requests_old_total": sum(r["draw_requests_old"] for r in subset),
            "draw_requests_new_total": sum(r["draw_requests_new"] for r in subset),
            "draw_corrected_cases": sum(1 for r in subset if r["draw_request_corrected"]),
            "draw_corrected_ids": [f"{r['dir']}/{r['case']}" for r in subset
                                   if r["draw_request_corrected"]],
            "review_from_run_record_cases": sum(1 for r in subset
                                                if r["review_from_run_record"] is not None),
            "review_fallback_cases": sum(1 for r in subset
                                         if r["review_fallback_from_result"] is not None),
            "review_effective_cases": sum(1 for r in subset if r["effective_review"] is not None),
            "review_recovered_cases": sum(1 for r in subset if r["review_recovered"]),
            "review_recovered_ids": [f"{r['dir']}/{r['case']}" for r in subset
                                     if r["review_recovered"]],
            "assertion_compared_cases": len(compared),
            "assertion_unavailable_cases": len(unavailable),
            "assertion_unavailable_details": [
                {"case": f"{r['dir']}/{r['case']}", "reason": r["assertion"].get("reason")}
                for r in unavailable],
            "assertion_ok_old_cases": sum(1 for r in compared if r["assertion"].get("old_ok")),
            "assertion_ok_new_cases": sum(1 for r in compared if r["assertion"].get("new_ok")),
            "assertion_conclusion_changed_cases": len(changed),
            "assertion_changed_details": [
                {"case": f"{r['dir']}/{r['case']}",
                 "old_ok": r["assertion"].get("old_ok"),
                 "new_ok": r["assertion"].get("new_ok"),
                 "added_errors": r["assertion"].get("added_errors") or [],
                 "removed_errors": r["assertion"].get("removed_errors") or []}
                for r in changed],
        })
    return summaries


def analyze_candidate_sets(group_summaries):
    """用方案声明的可判别特征核对「12 例」候选集合（gc6 vs recent12）。"""
    wanted = (("案例数", "cases"), ("纠正例数", "draw_corrected_cases"),
              ("新合计", "draw_requests_new_total"),
              ("视觉分恢复例数", "review_recovered_cases"))
    expected = {"案例数": PLAN_DECLARED["cases"], "纠正例数": PLAN_DECLARED["corrected"],
                "新合计": PLAN_DECLARED["new_total"],
                "视觉分恢复例数": PLAN_DECLARED["review_recovered"]}
    candidates = []
    for group in group_summaries:
        if group["cases"] != PLAN_DECLARED["cases"]:
            continue
        matched = [label for label, key in wanted if group[key] == expected[label]]
        candidates.append({"group": group["group"], "cases": group["cases"],
                           "draw_requests_old_total": group["draw_requests_old_total"],
                           "draw_requests_new_total": group["draw_requests_new_total"],
                           "draw_corrected_cases": group["draw_corrected_cases"],
                           "review_recovered_cases": group["review_recovered_cases"],
                           "matched_items": matched, "match_count": len(matched)})
    best_count = max((c["match_count"] for c in candidates), default=0)
    for candidate in candidates:
        candidate["is_best_match"] = (candidate["match_count"] == best_count
                                      and best_count >= 3)
    return candidates


def compare_with_plan(group_summaries):
    """把实测 recent12 与方案声明数字逐项对照（差异如实说明，不改数据）。"""
    target = next((g for g in group_summaries
                   if g["group"] == PLAN_DECLARED["case_set"]), None)
    if target is None:
        return {"available": False, "reason": f"未找到分组 {PLAN_DECLARED['case_set']}"}
    checks = (("案例数", PLAN_DECLARED["cases"], target["cases"]),
              ("请求数旧合计", PLAN_DECLARED["old_total"], target["draw_requests_old_total"]),
              ("请求数新合计", PLAN_DECLARED["new_total"], target["draw_requests_new_total"]),
              ("被纠正例数", PLAN_DECLARED["corrected"], target["draw_corrected_cases"]),
              ("视觉分恢复例数", PLAN_DECLARED["review_recovered"],
               target["review_recovered_cases"]))
    items = [{"item": label, "plan": plan, "measured": measured, "match": plan == measured}
             for label, plan, measured in checks]
    mismatches = [i for i in items if not i["match"]]
    result = {"available": True, "group": PLAN_DECLARED["case_set"],
              "items": items, "mismatches": mismatches, "all_match": not mismatches,
              "note": PLAN_DECLARED["note"]}
    if mismatches and len(mismatches) == 1 and mismatches[0]["item"] == "请求数旧合计":
        measured_delta = target["draw_requests_old_total"] - target["draw_requests_new_total"]
        plan_delta = PLAN_DECLARED["old_total"] - PLAN_DECLARED["new_total"]
        result["delta_note"] = (
            f"差异说明：新合计、被纠正例数、视觉分恢复例数与方案声明完全一致，"
            f"仅旧合计不同。纠正总量实测 = {target['draw_requests_old_total']} - "
            f"{target['draw_requests_new_total']} = {measured_delta}，方案隐含纠正量 = "
            f"{PLAN_DECLARED['old_total']} - {PLAN_DECLARED['new_total']} = {plan_delta}，"
            f"两者同差 {measured_delta - plan_delta:+d}。即方案旧合计数字与留存证据不符"
            f"（应为 {target['draw_requests_old_total']}），本报告以实测为准并保留原值，"
            f"不修改任何历史数据。")
    return result


# ================================================================ 报告渲染
def _fmt(value, digits=2):
    """报告单元格格式化：None → —，布尔 → 是/否，浮点保留位数。"""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _table(headers, rows):
    """生成 Markdown 表格。"""
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _draw_table(rows):
    """表 A：逐例 draw 请求数旧/新口径。"""
    body = []
    for row in rows:
        sequence = "/".join(str(v) for v in row["request_sequence"]) or "（空）"
        body.append([row["seq"], row["dir"], row["case"], _fmt(row["run_id"]),
                     _fmt(row["attempts"]), sequence, row["draw_requests_old"],
                     row["draw_requests_new"],
                     "是" if row["draw_request_corrected"] else "否"])
    return _table(["#", "目录", "案例", "runId", "尝试数", "request 序列（累计编号）",
                   "旧 sum", "新 max", "被纠正"], body)


def _review_table(rows):
    """表 B：逐例视觉分来源与恢复。"""
    body = [[row["seq"], row["dir"], row["case"],
             _fmt(row["review_from_run_record"], 1),
             _fmt(row["review_fallback_from_result"], 1),
             _fmt(row["effective_review"], 1),
             row["review_source"], "是" if row["review_recovered"] else "否"]
            for row in rows]
    return _table(["#", "目录", "案例", "run 记录评审（旧）", "任务 result 评审（补入）",
                   "生效评审", "来源", "恢复"], body)


def _assertion_table(rows):
    """表 C：逐例旧/新口径断言结论对比（含留存断言）。

    「断言器输出请求数」是**当前断言器**的 ``draw_requests``（Lead 已改新口径）；
    旧口径求和值见第二节，不在此重复冒充。
    """
    body = []
    for row in rows:
        assertion = row.get("assertion") or {}
        saved = row.get("saved_assertion") or {}
        saved_text = ("跳过：" + str(saved["skipped"]) if saved.get("skipped")
                      else f"{'通过' if saved.get('assert_ok_top') else '未通过'}")
        if assertion.get("available"):
            old_ok = "通过" if assertion.get("old_ok") else "未通过"
            new_ok = "通过" if assertion.get("new_ok") else "未通过"
            body.append([row["seq"], row["dir"], row["case"],
                         f"{old_ok}({assertion['old_error_count']})",
                         f"{new_ok}({assertion['new_error_count']})",
                         "一致" if not assertion.get("conclusion_changed") else "**已改变**",
                         _fmt(assertion.get("draw_requests_new_metrics")),
                         _fmt(assertion.get("review_overall_old"), 1),
                         _fmt(assertion.get("review_overall_new"), 1), saved_text])
        else:
            body.append([row["seq"], row["dir"], row["case"], "—", "—", "无法重算",
                         "—", "—", "—", saved_text])
    return _table(["#", "目录", "案例", "旧口径断言(错误数)", "新口径断言(错误数)", "结论",
                   "断言器输出请求数", "旧评审", "新评审", "留存断言"], body)


def _meta_table(rows):
    """表 D：逐例元数据（任务态 / 规模 / 门禁 / 校验 / 证据）。"""
    body = []
    for row in rows:
        gate = row["final_gate"]
        validation = row["validation"]
        body.append([row["seq"], row["dir"], row["case"], _fmt(row["run_id"]),
                     row["task_state"], _fmt(row["elapsed_s"], 1),
                     _fmt(row["target_blocks"]), _fmt(row["bricks"]),
                     _fmt(row["bricks_ratio"], 4),
                     f"{gate['source']}/{_fmt(gate['ok'])}",
                     f"{validation['source']}/{_fmt(validation['ok'])}",
                     len(row["screenshots"] or []), row["page_errors"]["errors"]])
    return _table(["#", "目录", "案例", "runId", "任务态", "耗时(s)", "目标块", "零件",
                   "比值", "最终门禁", "统一校验", "截图数", "JS 错误"], body)


def _group_table(groups):
    """分组汇总表。"""
    body = [[g["group"], g["cases"], g["draw_requests_old_total"],
             g["draw_requests_new_total"], g["draw_corrected_cases"],
             g["review_fallback_cases"], g["review_recovered_cases"],
             g["assertion_compared_cases"], g["assertion_conclusion_changed_cases"]]
            for g in groups]
    return _table(["分组", "案例数", "旧合计", "新合计", "纠正例数", "有任务评审例数",
                   "视觉分恢复例数", "可重算断言例数", "断言结论变化数"], body)


def _plan_section(report):
    """第七节：与声明数字的对照（差异如实列出）。"""
    comparison = report["plan_comparison"]
    lines = ["## 七、与方案 §4.1 声明数字的对照", ""]
    lines.append(f"方案声明：{comparison.get('note', '')}")
    lines.append("")
    if not comparison.get("available"):
        lines.append(f"无法对照：{comparison.get('reason')}")
        return lines
    lines.append(_table(["项目", "方案声明", "实测", "一致"],
                        [[i["item"], i["plan"], i["measured"], "是" if i["match"] else "**否**"]
                         for i in comparison["items"]]))
    lines.append("")
    candidates = report.get("candidate_sets") or []
    if candidates:
        lines.append("**候选集合判定**（方案称「12 个真实交付案例」，留存证据里有两个 12 例集合，"
                     "用方案给出的可判别特征核对）：")
        lines.append("")
        lines.append(_table(
            ["候选集合", "案例数", "旧合计", "新合计", "纠正例数", "视觉分恢复例数", "与方案吻合"],
            [[c["group"], c["cases"], c["draw_requests_old_total"],
              c["draw_requests_new_total"], c["draw_corrected_cases"],
              c["review_recovered_cases"],
              "、".join(c["matched_items"]) if c["matched_items"] else "无"] for c in candidates]))
        lines.append("")
        best = next((c for c in candidates if c.get("is_best_match")), None)
        if best is not None:
            lines.append(f"判定：方案所指的 12 例即 **{best['group']}** 集合"
                         f"（{best['cases']} 例，与方案吻合项：{'、'.join(best['matched_items'])}）。")
        lines.append("")
    if comparison["all_match"]:
        lines.append("**结论：实测与方案声明数字完全一致。**")
    else:
        lines.append("**结论：实测与方案声明存在差异，如实列出，未修改任何历史数据：**")
        lines.append("")
        for item in comparison["mismatches"]:
            lines.append(f"- {item['item']}：方案 {item['plan']}，实测 {item['measured']}"
                         f"（差 {item['measured'] - item['plan']:+d}）。")
        lines.append("")
        if comparison.get("delta_note"):
            lines.append(comparison["delta_note"])
    return lines


def _conclusion_section(report):
    """第八节：结论与集成建议（全部由实测数字生成）。"""
    groups = {g["group"]: g for g in report["groups"]}
    lines = ["## 八、结论与集成建议", ""]
    recent = groups.get("recent12") or {}
    lines.append("1. **请求数口径**：旧口径对累计编号求和，"
                 f"recent12 旧合计 {recent.get('draw_requests_old_total')} → "
                 f"新合计 {recent.get('draw_requests_new_total')}，"
                 f"{recent.get('draw_corrected_cases')} 例被纠正；"
                 f"all 组旧合计 {groups.get('all', {}).get('draw_requests_old_total')} → "
                 f"新合计 {groups.get('all', {}).get('draw_requests_new_total')}。")
    lines.append("2. **视觉分**：旧 run 记录无 `review` 字段，"
                 f"recent12 有任务评审 {recent.get('review_fallback_cases')} 例、"
                 f"恢复 {recent.get('review_recovered_cases')} 例；"
                 "生效评审来源见逐例表 B。")
    lines.append(f"3. **原需求断言结论**：recent12 可重算 "
                 f"{recent.get('assertion_compared_cases')} 例中结论改变 "
                 f"{recent.get('assertion_conclusion_changed_cases')} 例（必须为 0）；无法重算 "
                 f"{recent.get('assertion_unavailable_cases')} 例均为任务失败、无最终产物、"
                 "E2E 当时断言即被跳过（证据见留存断言列）。")
    lines.append("4. **集成建议**：浏览器/断言侧应把任务 `result.review` 作为 "
                 "`review_fallback` 传给 `check_objects*`，run 记录已有 `review` 时以其为准；"
                 "`draw_requests` 统一取累计编号最大值（空列表为 0），不得再对累计值求和。")
    lines.append("")
    return lines


def _warning_section(report):
    """第九节：加载与重算警告（产物缺失、记录不一致等，去重后如实列出）。"""
    warnings = report.get("warnings") or []
    seen, lines = set(), []
    for item in warnings:
        prefix = "/".join(filter(None, [item.get("dir"), item.get("case")]))
        if not prefix and item.get("path"):
            prefix = str(item["path"]).replace("\\", "/").split("/")[-1]
        text = f"{prefix + '：' if prefix else ''}{item.get('error')}"
        if text in seen:
            continue
        seen.add(text)
        lines.append(f"- {text}")
    if not lines:
        return []
    return ["## 九、加载与重算警告（如实记录，未掩盖）", ""] + lines + [""]


def render_markdown(report):
    """渲染完整重算报告（逐例表格 + 分组汇总 + 方案数字对照 + 结论）。"""
    rows = report["rows"]
    groups = report["groups"]
    lines = ["# 历史真实交付证据口径重算报告（2026-11-14 方案 §4.1）", ""]
    lines.append(f"- 生成时间：{report['generated_at']}")
    lines.append(f"- 证据根目录：`{report['root']}`")
    lines.append(f"- 单例记录数：{len(rows)}（目录：{', '.join(report['dirs'])}）")
    lines.append(f"- 生成命令：`python -m tools.recompute_caliber --out {report['out_dir']}`")
    baseline = report.get("code_baseline") or {}
    if baseline:
        lines.append(f"- 代码基线：HEAD `{baseline.get('head')}`，工作区"
                     f"{'有未提交改动' if baseline.get('dirty') else '干净'}；"
                     "相关文件 SHA1 见 recompute.json.code_baseline.files")
    lines.append("- 数据来源：只读扫描留存单例 JSON（`runRecord` / `result` / `assertion`），"
                 "产物取自 `artifacts/` 与 `<案例目录>/evidence/`；未修改任何历史数据。")
    lines.append("")
    lines.append("## 一、口径定义")
    lines.append("")
    lines.append("1. **draw 请求数**：`drawAttempts[].request` 是累计请求编号（1,2,3…），"
                 "旧口径 `sum(...)` 把 3 次请求算成 6；新口径取 `max(...)`（空列表为 0）。")
    lines.append("2. **视觉分**：旧 run 记录没有 `review` 字段（`review.scores.overall` 为空）；"
                 "新口径从任务 `result.review` 补入，仍无则保持空值。"
                 "`恢复` = 靠任务评审补回了 run 记录缺失的真实视觉分。")
    lines.append("3. **断言结论**：分别用旧口径记录（run 记录原样）与新口径记录"
                 "（补入任务评审 + 新请求数口径）跑同一断言器入口，只比较"
                 "`assertion_ok` 与 `assertion_errors` 是否改变；改变必须逐条列出。")
    lines.append("")
    lines.append("## 二、逐例重算：draw 请求数（旧 sum vs 新 max）")
    lines.append("")
    lines.append(_draw_table(rows))
    lines.append("")
    lines.append("## 三、逐例重算：视觉分恢复")
    lines.append("")
    lines.append(_review_table(rows))
    lines.append("")
    lines.append("## 四、逐例重算：需求断言结论对比（不得改变原结论）")
    lines.append("")
    lines.append(_assertion_table(rows))
    lines.append("")
    changed = [r for r in rows if (r.get("assertion") or {}).get("conclusion_changed")]
    if changed:
        lines.append("**结论改变的案例（逐条列出，不掩盖）：**")
        lines.append("")
        for row in changed:
            assertion = row["assertion"]
            lines.append(f"- `{row['dir']}/{row['case']}`：旧 `ok={assertion['old_ok']}` → "
                         f"新 `ok={assertion['new_ok']}`；新增错误：{assertion['added_errors']}；"
                         f"消失错误：{assertion['removed_errors']}")
    else:
        lines.append("**全部可重算案例的断言结论一致（`assertion_ok` 与 `assertion_errors` 均未改变）。**")
    unavailable = [r for r in rows if not (r.get("assertion") or {}).get("available")]
    if unavailable:
        lines.append("")
        lines.append("**无法重算断言的案例（产物缺失，如实记录原因）：**")
        lines.append("")
        for row in unavailable:
            lines.append(f"- `{row['dir']}/{row['case']}`（{row['task_state']}）："
                         f"{(row.get('assertion') or {}).get('reason')}；"
                         f"E2E 留存断言={_fmt((row.get('saved_assertion') or {}).get('skipped'))}")
    lines.append("")
    lines.append("## 五、逐例元数据（任务四态 / 规模 / 门禁 / 校验 / 证据）")
    lines.append("")
    lines.append(_meta_table(rows))
    lines.append("")
    lines.append("## 六、分组汇总")
    lines.append("")
    lines.append(_group_table(groups))
    lines.append("")
    for group in groups:
        lines.append(f"- **{group['group']}**（{group['cases']} 例，目录："
                     f"{', '.join(group['dirs']) or '—'}）：被纠正案例 "
                     f"{group['draw_corrected_ids'] or '无'}；视觉分恢复案例 "
                     f"{group['review_recovered_ids'] or '无'}；断言结论变化 "
                     f"{group['assertion_conclusion_changed_cases']} 例；无法重算 "
                     f"{group['assertion_unavailable_cases']} 例。")
    lines.append("")
    lines.extend(_plan_section(report))
    lines.append("")
    lines.extend(_conclusion_section(report))
    lines.extend(_warning_section(report))
    lines.append("## 复核方式")
    lines.append("")
    lines.append("```bash")
    lines.append(f"python -m tools.recompute_caliber --out {report['out_dir']}")
    lines.append("python -m pytest test/test_recompute_caliber.py -q")
    lines.append("```")
    lines.append("")
    lines.append("原始逐例数据见同目录 `recompute.json`（含每条记录完整 request 序列、"
                 "旧/新断言错误清单、产物来源与截图路径）。")
    return "\n".join(lines)


# ================================================================ 主流程
def _code_baseline():
    """采集可复核基线：HEAD、工作区状态与相关文件 SHA1。"""
    import hashlib

    def _git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True,
                                       encoding="utf-8", errors="replace").strip()

    baseline = {"head": None, "dirty": None, "files": {}}
    try:
        baseline["head"] = _git("rev-parse", "--short", "HEAD")
        baseline["dirty"] = bool(_git("status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        pass
    for rel in ("tools/e2e_assert.py", "tools/e2e_assert_20.py", "tools/e2e_assert_g.py",
                "tools/e2e_assert_new20.py", "legogod/plan_scale.py"):
        path = os.path.join(ROOT, rel)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                baseline["files"][rel] = hashlib.sha1(f.read()).hexdigest()[:16]
    return baseline


def build_report(root=DEFAULT_ROOT, dirs=None, out_dir=DEFAULT_OUT):
    """完整重算入口：加载 → 逐例重算 → 分组聚合 → 方案对照，返回报告 dict。"""
    warnings = []
    entries = load_records(root, dirs, warnings)
    for index, entry in enumerate(entries, 1):
        entry["seq"] = index
    rows = [recompute_record(entry, run_assertions=True, warnings=warnings)
            for entry in entries]
    groups = aggregate(rows)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": root, "out_dir": out_dir,
        "dirs": sorted({row["dir"] for row in rows}),
        "records_total": len(rows),
        "code_baseline": _code_baseline(),
        "plan_declared": PLAN_DECLARED,
        "plan_comparison": compare_with_plan(groups),
        "candidate_sets": analyze_candidate_sets(groups),
        "groups": groups, "rows": rows, "warnings": warnings,
    }


def main(argv=None):
    """CLI 入口：重算并写出 recompute.json / recompute.md。"""
    parser = argparse.ArgumentParser(
        description="历史真实交付证据的口径重算（draw 请求数 / 视觉分 / 断言结论）")
    parser.add_argument("--root", default=DEFAULT_ROOT,
                        help="证据根目录（默认 artifacts/e2e-20）")
    parser.add_argument("--dirs", default=None,
                        help="逗号分隔的子目录名（默认自动发现所有含单例记录的目录）")
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="输出目录（默认 artifacts/analysis-caliber-20261114）")
    args = parser.parse_args(argv)
    dirs = [d.strip() for d in args.dirs.split(",") if d.strip()] if args.dirs else None
    report = build_report(args.root, dirs, args.out)
    if not report["rows"]:
        print(f"未找到单例记录：root={args.root} dirs={dirs}", file=sys.stderr)
        return 2
    out_abs = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(out_abs, exist_ok=True)
    json_path = os.path.join(out_abs, "recompute.json")
    md_path = os.path.join(out_abs, "recompute.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    print(f"重算完成：{report['records_total']} 条单例记录")
    for group in report["groups"]:
        print(f"  [{group['group']}] {group['cases']} 例 · 旧合计 "
              f"{group['draw_requests_old_total']} → 新合计 "
              f"{group['draw_requests_new_total']} · 纠正 {group['draw_corrected_cases']} 例 · "
              f"有任务评审 {group['review_fallback_cases']} 例 · 恢复 "
              f"{group['review_recovered_cases']} 例 · 断言可重算 "
              f"{group['assertion_compared_cases']} 例 · 结论变化 "
              f"{group['assertion_conclusion_changed_cases']} 例")
    comparison = report["plan_comparison"]
    if comparison.get("available"):
        mismatches = comparison["mismatches"]
        print("与方案数字：" + ("；".join(
            f"{m['item']} 方案 {m['plan']} vs 实测 {m['measured']}" for m in mismatches)
            if mismatches else "完全一致"))
    print(f"已写出：{json_path}")
    print(f"已写出：{md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
