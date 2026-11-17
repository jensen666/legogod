# -*- coding: utf-8 -*-
"""40 例真实 E2E 轮次分析器：旧 20 例 + 新增 N01–N20 分组汇总。

用法：
    python -m tools.e2e_analyze_40 --round artifacts/e2e-20/20261104-old20
    python -m tools.e2e_analyze_40 --round <本轮目录> \
        --compare-round artifacts/e2e-20/20261103-0703-frozen2-full30

只读取运行目录里的单例 JSON 与 environment.json，不发起任何模型/网络请求。
输出 analysis40.json 与 analysis40.md（分组指标 + 逐例表 + 与对照轮的逐例对比），
供验收报告引用。旧 20 说明书：H01–H10 + C02,C03,C05,C06,C07,C10,C11,C13,C14,C16。
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.e2e_analyze_full import (  # noqa: E402
    _fmt_ratio, _load_case, describe, summarize,
)

OLD20 = ["H01", "H02", "H03", "H04", "H05", "H06", "H07", "H08", "H09", "H10",
         "C02", "C03", "C05", "C06", "C07", "C10", "C11", "C13", "C14", "C16"]
NEW20 = [f"N{i:02d}" for i in range(1, 21)]
TOTAL40 = OLD20 + NEW20


def _load_stress():
    """读取新案例集的压力类别（stress）；模块不存在时返回空，不阻塞旧轮分析。"""
    try:
        from tools.e2e_cases_new20 import all_n_cases
    except Exception:  # noqa: BLE001 - 旧轮次分析不依赖新案例模块
        return {}
    stress = {}
    for case in all_n_cases():
        values = case.get("stress") or []
        if isinstance(values, str):
            values = [values]
        stress[case["id"]] = list(values)
    return stress


def _assertion_error_category(error):
    """把断言错误文本压成可统计的类别（只做粗分类，不改原错误）。"""
    text = str(error)
    for key, words in (
        ("部位缺失", ("部位", "缺失", "未找到")),
        ("几何/特征", ("几何", "特征", "跨度", "悬挑", "环", "弧", "倾斜", "相邻", "接触")),
        ("复杂度下限", ("复杂度", "设计下限")),
        ("目标块数", ("目标", "块数", "零件")),
        ("通用底线", ("通用", "任务", "门禁", "校验", "产物", "评审")),
    ):
        if any(w in text for w in words):
            return key
    return "其它"


def _failure_stats(rows):
    """统计失败 attempts 的 kind/stage 与断言错误粗分类。"""
    kinds = {}
    stages = {}
    assertion_categories = {}
    for row in rows:
        for attempt in row.get("attempts") or []:
            if attempt.get("ok"):
                continue
            kind = attempt.get("kind") or "unknown"
            stage = attempt.get("stage") or "unknown"
            kinds[kind] = kinds.get(kind, 0) + 1
            stages[stage] = stages.get(stage, 0) + 1
        for err in row.get("assertionErrors") or []:
            key = _assertion_error_category(err)
            assertion_categories[key] = assertion_categories.get(key, 0) + 1
    return {
        "attemptKinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "attemptStages": dict(sorted(stages.items(), key=lambda kv: -kv[1])),
        "assertionCategories": dict(sorted(assertion_categories.items(), key=lambda kv: -kv[1])),
    }


def _stress_groups(rows, stress_map):
    """按压力类别汇总新 20 例（一例可属多类）。"""
    by_case = {row["case"]: row for row in rows}
    groups = {}
    for cid in NEW20:
        for tag in stress_map.get(cid) or ["未标注"]:
            groups.setdefault(tag, []).append(cid)
    out = {}
    for tag, ids in sorted(groups.items()):
        members = [by_case[c] for c in ids if by_case.get(c)]
        if not members:
            continue
        summary = summarize(members)
        summary["caseIds"] = ids
        out[tag] = summary
    return out


def _compare_rows(compare_dir, case_ids):
    """读取对照轮单例，返回 {case: describe 行}；目录不存在返回空。"""
    if not compare_dir or not os.path.isdir(compare_dir):
        return {}
    result = {}
    for cid in case_ids:
        rec = _load_case(compare_dir, cid)
        if rec is not None:
            result[cid] = describe(rec)
    return result


def _fmt_cell(value):
    return "—" if value is None else str(value)


def write_markdown(path, data):
    env = data.get("environment") or {}
    lines = ["# 40 例真实 E2E 轮次分析（旧 20 + 新 20）", "",
             f"- 轮次：{env.get('label')}；目录：`{data['roundDir']}`",
             f"- 时间：{env.get('startedAt')} → {env.get('finishedAt')}",
             f"- 代码 HEAD：`{env.get('codeHead')}`；工作区未提交：{env.get('worktreeDirty')}；"
             f"实际模型配置：`{env.get('modelConfigured')}`（env 覆盖：{env.get('modelEnvVar') or '无'}）",
             f"- 并发：{env.get('concurrency')}；单例墙钟上限：{env.get('timeoutS')}s；服务：{env.get('baseUrl')}", ""]
    for key, title in (("old20", "旧 20 例"), ("new20", "新 20 例（N01–N20）"),
                       ("total40", "合计 40 例")):
        s = data["groups"][key]
        lines += [f"## {title}", "",
                  f"- 记录 {s['recorded']}/{s['total']}；任务完成 {s['delivered']}/{s['total']}；"
                  f"断言通过 {s['asserted']}/{s['total']}",
                  f"- 四态：{json.dumps(s['outcomes'], ensure_ascii=False)}",
                  f"- 双尝试失败 {s['doubleAttemptFailed']}：{s['doubleAttemptFailedIds']}",
                  f"- 高保真成功 {s['fidelitySuccess']}：{s['fidelitySuccessIds']}",
                  f"- 实际/目标零件数中位：{_fmt_ratio(s['medianBricksRatio'])}；"
                  f"体素中位：{s['medianVoxels']}",
                  f"- 交付统一校验失败：{s['validationFailedIds']}；门禁降级：{s['gateDegradedIds']}",
                  f"- 过期高保真成功：{s['reviewStaleIds']}；版本覆盖数：{s['versionOverwrites']}",
                  f"- 页面 JS 错误：{s['pageJsErrors']}；unhandledrejection：{s['pageRejections']}",
                  f"- internal 失败：{s['internalErrorIds']}；deadline 失败：{s['deadlineFailureIds']}",
                  f"- 耗时中位/最大：{s['quantiles']['elapsedMedian'] or '—'}s / "
                  f"{s['quantiles']['elapsedMax'] or '—'}s", ""]
        fs = s.get("failureStats") or {}
        lines += [f"- 失败 attempts kind：{json.dumps(fs.get('attemptKinds') or {}, ensure_ascii=False)}",
                  f"- 失败 attempts stage：{json.dumps(fs.get('attemptStages') or {}, ensure_ascii=False)}",
                  f"- 断言错误粗分类：{json.dumps(fs.get('assertionCategories') or {}, ensure_ascii=False)}", ""]
    if data.get("stressGroups"):
        lines += ["## 新 20 例按压力类别（stress）", "",
                  "| 压力类别 | 例数 | 交付 | 断言 | 双尝试失败 | 目标比中位 | 体素中位 |",
                  "|---|---|---|---|---|---|---|"]
        for tag, s in data["stressGroups"].items():
            lines.append(f"| {tag} | {s['total']} | {s['delivered']}/{s['total']} | "
                         f"{s['asserted']}/{s['total']} | {s['doubleAttemptFailed']} | "
                         f"{_fmt_ratio(s['medianBricksRatio'])} | {s['medianVoxels']} |")
        lines.append("")
    lines += ["## 逐例结果", "",
              "| 案例 | 名称 | 四态 | 任务 | 断言 | 耗时(s) | 部位 | 体素 | 零件/目标 | 目标比 | 视觉 | 页面JS | 失败类别 | 断言错误摘要 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in data["rows"]:
        kinds = "、".join(f"{a.get('mode')}:{a.get('kind') or 'ok'}"
                          for a in r.get("attempts") or []) or "—"
        errs = "；".join(r.get("assertionErrors") or [])[:180] or "—"
        lines.append(f"| {r.get('case')} | {r.get('name')} | {r.get('outcome')} | {r.get('taskOk')} | "
                     f"{r.get('assertOk')} | {r.get('elapsedS')} | {r.get('parts')} | {r.get('voxels')} | "
                     f"{r.get('bricks')}/{r.get('targetBlocks')} | {_fmt_ratio(r.get('bricksRatio'))} | "
                     f"{r.get('reviewOverall')} | {r.get('pageJsErrors')} | {kinds} | {errs} |")
    lines += ["", "## 与对照轮逐例对比（旧 20 例）", ""]
    cmp = data.get("compare") or {}
    if cmp.get("rows"):
        lines += ["| 案例 | 对照四态/任务/断言 | 本轮四态/任务/断言 | 对照体素 | 本轮体素 | 对照目标比 | 本轮目标比 | 对照视觉 | 本轮视觉 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for item in cmp["rows"]:
            before, after = item.get("before") or {}, item.get("after") or {}
            lines.append(
                f"| {item.get('case')} | {before.get('outcome')}/{before.get('taskOk')}/"
                f"{before.get('assertOk')} | {after.get('outcome')}/{after.get('taskOk')}/"
                f"{after.get('assertOk')} | {_fmt_cell(before.get('voxels'))} | "
                f"{_fmt_cell(after.get('voxels'))} | {_fmt_ratio(before.get('bricksRatio'))} | "
                f"{_fmt_ratio(after.get('bricksRatio'))} | {_fmt_cell(before.get('reviewOverall'))} | "
                f"{_fmt_cell(after.get('reviewOverall'))} |")
        lines += ["", f"对照轮目录：`{cmp.get('roundDir')}`"]
    else:
        lines += ["（未提供 `--compare-round` 或对照轮缺失）"]
    lines += ["", "## 证据路径", "",
              "- 每例单例 JSON（任务快照/四 Tab/页面错误/断言）：`<CASE>.json`",
              "- 每例 run JSON、模型、方案、拼装步骤：`<CASE>/evidence/`",
              "- 每例工作台/工作室/步骤/运行记录截图：`<CASE>/*.png`",
              "- 服务日志：`server.log`；环境快照：`environment.json`；浏览器汇总：`summary.json`/`summary.md`"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="40 例真实 E2E 轮次分析（旧20 + 新 N01–N20）")
    ap.add_argument("--round", required=True)
    ap.add_argument("--compare-round", default=None)
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
    for cid in TOTAL40:
        rec = _load_case(round_dir, cid)
        if rec is None:
            missing.append(cid)
            rows.append({"case": cid, "recorded": False})
            continue
        rows.append(describe(rec))
    by_case = {r["case"]: r for r in rows}
    groups = {
        "old20": summarize([by_case[c] for c in OLD20]),
        "new20": summarize([by_case[c] for c in NEW20]),
        "total40": summarize(rows),
    }
    for key, ids in (("old20", OLD20), ("new20", NEW20), ("total40", TOTAL40)):
        groups[key]["failureStats"] = _failure_stats([by_case[c] for c in ids])
    stress_map = _load_stress()
    stress_groups = _stress_groups(rows, stress_map)
    compare = {}
    if args.compare_round:
        before = _compare_rows(os.path.abspath(args.compare_round), OLD20)
        compare = {
            "roundDir": os.path.abspath(args.compare_round),
            "rows": [{
                "case": cid,
                "before": before.get(cid),
                "after": by_case.get(cid),
                "changed": bool(before.get(cid)) and bool(by_case.get(cid)) and (
                    before[cid].get("taskOk") != by_case[cid].get("taskOk")
                    or before[cid].get("assertOk") != by_case[cid].get("assertOk")),
            } for cid in OLD20],
            "deliveredBefore": sum(1 for cid in OLD20 if (before.get(cid) or {}).get("taskOk")),
            "deliveredAfter": sum(1 for cid in OLD20 if (by_case.get(cid) or {}).get("taskOk")),
            "assertedBefore": sum(1 for cid in OLD20 if (before.get(cid) or {}).get("assertOk")),
            "assertedAfter": sum(1 for cid in OLD20 if (by_case.get(cid) or {}).get("assertOk")),
        }
    data = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "roundDir": round_dir,
        "environment": environment,
        "missing": missing,
        "groups": groups,
        "stressGroups": stress_groups,
        "compare": compare,
        "rows": rows,
    }
    out_dir = args.out or round_dir
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "analysis40.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    write_markdown(os.path.join(out_dir, "analysis40.md"), data)
    print(f"[analyze40] 记录 {groups['total40']['recorded']}/40，缺结果：{missing}")
    for key in ("old20", "new20", "total40"):
        s = groups[key]
        print(f"[analyze40] {key}: 交付 {s['delivered']}/{s['total']}，"
              f"断言 {s['asserted']}/{s['total']}，"
              f"四态 {json.dumps(s['outcomes'], ensure_ascii=False)}，"
              f"目标比中位 {_fmt_ratio(s['medianBricksRatio'])}")
    if compare:
        print(f"[analyze40] 对照轮旧20：交付 {compare['deliveredBefore']} → "
              f"{compare['deliveredAfter']}，断言 {compare['assertedBefore']} → "
              f"{compare['assertedAfter']}")
    return 0 if not missing else 2


if __name__ == "__main__":
    sys.exit(main())
