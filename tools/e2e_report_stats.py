# -*- coding: utf-8 -*-
"""40 例两轮真实 E2E 的合并统计（旧 20 例轮 + 新 20 例轮；只读本地证据）。

用途：验收报告需要跨两轮合并的数字（交付/断言/四态/目标比/视觉分/失败尝试分类/
断言错误分类/每例翻转），e2e_analyze_40 只分析单轮目录；本工具把两轮读成一份
report-data.json，并打印可直接引用的汇总。

用法：
    python -m tools.e2e_report_stats \
        --old-round artifacts/e2e-20/20261104-old20 \
        --new-round artifacts/e2e-20/20261104-new20 \
        --compare-round artifacts/e2e-20/20261103-0703-frozen2-full30 \
        --out artifacts/e2e-20/20261104-report

只读取各轮 `<CASE>.json` 与 environment.json，不发起任何模型/网络请求。
"""
import argparse
import json
import os
import sys
import statistics
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.e2e_analyze_full import describe  # noqa: E402
from tools.e2e_analyze_40 import OLD20, NEW20, _failure_stats  # noqa: E402

DELIVERED = ("fidelity_success", "fidelity_degraded", "fast_fallback", "fast_success")


def _load_case(round_dir, case_id):
    path = os.path.join(round_dir, f"{case_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _median(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(statistics.median(vals), 2) if vals else None


def _review_score(rec, row):
    """视觉总分：优先断言 metrics，其次 job result.review.scores.overall。"""
    score = (row or {}).get("reviewOverall")
    if isinstance(score, (int, float)):
        return score
    result = (rec or {}).get("result") or {}
    review = result.get("review") if isinstance(result.get("review"), dict) else {}
    scores = review.get("scores") if isinstance(review.get("scores"), dict) else {}
    value = scores.get("overall")
    return value if isinstance(value, (int, float)) else None


def _classify_assertion_error(error):
    """报告用精确分类（与 analysis40 的粗分类分开，数字可逐项对账）。"""
    text = str(error)
    if "最终门禁重放" in text:
        return "门禁重放失败"
    if "评审已过期" in text:
        return "评审过期(reviewStale)"
    if "目标块数未达标" in text or "需求达标档" in text:
        return "目标块数比<50%"
    if "未达设计下限：体素数" in text:
        return "体素数<设计下限"
    if "未达设计下限：部位数" in text:
        return "部位数<设计下限"
    if "未达设计下限：立体部位数" in text:
        return "立体部位数<设计下限"
    if "未达设计下限：算子数" in text:
        return "算子数<设计下限"
    if "缺少" in text or "不足" in text or "被删除" in text or "退化" in text:
        return "部位缺失/体量不足"
    return "其它特征/几何"


def collect(round_dir, case_ids):
    """读取一轮中指定案例，返回 {case: 行} 与缺例列表。"""
    rows = {}
    missing = []
    for cid in case_ids:
        rec = _load_case(round_dir, cid)
        if rec is None:
            missing.append(cid)
            continue
        row = describe(rec)
        row["reviewOverall"] = _review_score(rec, row)
        row["stress"] = None
        rows[cid] = row
    return rows, missing


def summarize(rows, case_ids):
    cases = [rows[c] for c in case_ids if c in rows]
    delivered = [r for r in cases if r.get("taskOk")]
    asserted = [r for r in cases if r.get("assertOk")]
    outcomes = {}
    for r in cases:
        key = r.get("outcome") or "failed"
        outcomes[key] = outcomes.get(key, 0) + 1
    ratio_met = [r for r in delivered
                 if isinstance(r.get("bricksRatio"), (int, float)) and r["bricksRatio"] >= 0.5]
    fail_stats = _failure_stats([{"attempts": r.get("attempts") or [],
                                  "assertionErrors": r.get("assertionErrors") or []}
                                 for r in cases])
    assertion_categories = {}
    for r in delivered:
        for err in r.get("assertionErrors") or []:
            key = _classify_assertion_error(err)
            assertion_categories[key] = assertion_categories.get(key, 0) + 1
    return {
        "total": len(case_ids),
        "recorded": len(cases),
        "delivered": len(delivered),
        "asserted": len(asserted),
        "outcomes": dict(sorted(outcomes.items(), key=lambda kv: -kv[1])),
        "deliveredIds": [r.get("case") for r in delivered],
        "assertedIds": [r.get("case") for r in asserted],
        "targetRatioMet": len(ratio_met),
        "targetRatioMetIds": [r.get("case") for r in ratio_met],
        "medianBricksRatio": _median([r.get("bricksRatio") for r in delivered]),
        "medianVoxels": _median([r.get("voxels") for r in delivered]),
        "medianParts": _median([r.get("parts") for r in delivered]),
        "medianReview": _median([r.get("reviewOverall") for r in delivered]),
        "reviewScored": sum(1 for r in delivered if isinstance(r.get("reviewOverall"), (int, float))),
        "about7Review": sum(1 for r in delivered
                            if isinstance(r.get("reviewOverall"), (int, float))
                            and r["reviewOverall"] >= 7),
        "gateDegradedIds": [r.get("case") for r in delivered if r.get("gateDegraded")],
        "finalGateFailedIds": [r.get("case") for r in delivered if r.get("finalGateOk") is False],
        "reviewStaleIds": [r.get("case") for r in delivered if r.get("reviewStale") is True],
        "validationFailedIds": [r.get("case") for r in delivered if r.get("validationOk") is False],
        "pageJsErrors": sum(int(r.get("pageJsErrors") or 0) for r in cases),
        "pageRejections": sum(int(r.get("pageRejections") or 0) for r in cases),
        "internalIds": [r.get("case") for r in cases
                        if "内部" in str(r.get("error") or "")],
        "deadlineIds": [r.get("case") for r in cases
                        if any(a.get("kind") == "deadline" for a in r.get("attempts") or [])],
        "doubleAttemptFailedIds": [r.get("case") for r in cases
                                   if not r.get("taskOk") and r.get("attemptCount", 0) >= 2],
        "elapsedMedian": _median([r.get("elapsedS") for r in cases]),
        "elapsedMax": max([r["elapsedS"] for r in cases
                           if isinstance(r.get("elapsedS"), (int, float))], default=None),
        "attemptFailureKinds": fail_stats["attemptKinds"],
        "attemptFailureStages": fail_stats["attemptStages"],
        "assertionErrorCategories": dict(sorted(assertion_categories.items(),
                                                key=lambda kv: -kv[1])),
        "assertionErrorTotal": sum(assertion_categories.values()),
    }


def _flips(current, compare, case_ids):
    out = []
    for cid in case_ids:
        before, after = compare.get(cid) or {}, current.get(cid) or {}
        if not before or not after:
            continue
        if before.get("taskOk") != after.get("taskOk"):
            out.append({"case": cid, "change": "delivered→failed"
                        if before.get("taskOk") and not after.get("taskOk")
                        else "failed→delivered"})
    return out


def _new_stress_groups(rows):
    try:
        from tools.e2e_cases_new20 import all_n_cases
    except ImportError:
        return {}
    by_case = {c["id"]: c for c in all_n_cases()}
    groups = {}
    for cid, case in by_case.items():
        if cid not in rows:
            continue
        for tag in case.get("stress") or []:
            groups.setdefault(tag, []).append(cid)
    result = {}
    for tag, ids in sorted(groups.items()):
        result[tag] = summarize(rows, ids)
        result[tag]["caseIds"] = ids
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="40 例两轮真实 E2E 合并统计")
    ap.add_argument("--old-round", required=True)
    ap.add_argument("--new-round", required=True)
    ap.add_argument("--compare-round", default=None,
                    help="旧 20 例对照轮（2026-11-03 最终冻结确认轮）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    old_dir = os.path.abspath(args.old_round)
    new_dir = os.path.abspath(args.new_round)
    old_rows, old_missing = collect(old_dir, OLD20)
    new_rows, new_missing = collect(new_dir, NEW20)
    data = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "oldRound": old_dir,
        "newRound": new_dir,
        "missing": {"old": old_missing, "new": new_missing},
        "old20": summarize(old_rows, OLD20),
        "new20": summarize(new_rows, NEW20),
        "total40": summarize({**old_rows, **new_rows}, OLD20 + NEW20),
        "stressGroups": _new_stress_groups(new_rows),
        "cases": {"old20": list(old_rows.values()), "new20": list(new_rows.values())},
    }
    if args.compare_round:
        compare_dir = os.path.abspath(args.compare_round)
        compare_rows, _ = collect(compare_dir, OLD20)
        data["compareOld20"] = summarize(compare_rows, OLD20)
        data["deliveryFlips"] = _flips(old_rows, compare_rows, OLD20)
        data["compareRound"] = compare_dir
    out_dir = args.out or os.path.join(ROOT, "artifacts", "e2e-20")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "report-data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for label in ("old20", "new20", "total40"):
        s = data[label]
        print(f"[report] {label}: 记录 {s['recorded']}/{s['total']}，交付 {s['delivered']}，"
              f"断言 {s['asserted']}，四态 {json.dumps(s['outcomes'], ensure_ascii=False)}，"
              f"目标比中位 {s['medianBricksRatio']}，体素中位 {s['medianVoxels']}，"
              f"视觉中位 {s['medianReview']}（有分 {s['reviewScored']}）")
        print(f"[report]   {label}: 失败尝试 {json.dumps(s['attemptFailureKinds'], ensure_ascii=False)}；"
              f"断言错误 {s['assertionErrorTotal']} 条 "
              f"{json.dumps(s['assertionErrorCategories'], ensure_ascii=False)}")
    if "compareOld20" in data:
        c = data["compareOld20"]
        print(f"[report] 对照轮旧20: 交付 {c['delivered']}，断言 {c['asserted']}，"
              f"目标比中位 {c['medianBricksRatio']}，体素中位 {c['medianVoxels']}")
        print(f"[report] 交付翻转：{json.dumps(data['deliveryFlips'], ensure_ascii=False)}")
    print(f"[report] 写出 {path}")
    return 0 if not old_missing and not new_missing else 2


if __name__ == "__main__":
    sys.exit(main())
