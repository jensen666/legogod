# -*- coding: utf-8 -*-
"""``tools.recompute_caliber`` 口径重算的纯离线测试。

覆盖（不联网、不起服务、不调用任何真实 LLM）：

1. draw 请求数：求和 vs 取最大值的差异识别、空列表为 0、跳号序列取最大值；
2. 视觉分：run 记录缺失时从任务 ``result.review`` 补入后恢复，无评审保持 None；
3. 断言结论对比：只有口径字段变化、断言结论不变时 ``conclusion_changed=False``；
4. 证据加载：单例记录扫描、产物加载与缺失原因；
5. 分组聚合：案例数 / 纠正数 / 恢复数正确。

合成数据全部写在 ``tmp_path`` 内，``recompute_record`` 用 ``run_assertions=False``
（断言器需要真实交付产物与案例契约，合成模型不冒充真实结果；结论对比逻辑由
``compare_assertions`` 纯函数单独覆盖）。
"""
import json
import os

import pytest

from tools.recompute_caliber import (
    aggregate,
    compare_assertions,
    draw_request_stats,
    load_case_assets,
    load_records,
    recompute_record,
    review_overall,
    review_sources,
)

# ---------------------------------------------------------------- 构造合成证据


def _write_json(path, payload):
    """写 UTF-8 JSON（自动建父目录）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _make_record(case, run_id, requests, review=None, ok=True, target=300, bricks=150,
                 case_dir=None, with_assets=True):
    """构造一条合成单例记录（含 run 记录、任务结果、可选产物文件）。

    ``requests`` 是 drawAttempts 的 request 累计编号序列；``review`` 是任务
    ``result.review``（run 记录故意不写 review，复现旧记录缺字段的历史事实）。
    """
    attempts = [{"attempt": index + 1, "request": value}
                for index, value in enumerate(requests)]
    run_record = {
        "runId": run_id,
        "ok": ok,
        "error": None if ok else "合成失败",
        "revision": 1,
        "desc": "合成需求：一座测试塔，目标 300 块",
        "drawAttempts": attempts,
        "scaleMetrics": {"targetBlocks": target, "bricks": bricks,
                         "targetBlocksRatio": bricks / target if target else None},
        "finalGateReplay": {"ok": True, "errors": []},
        "artifacts": {"model_r001": f"model_synth_r001_{run_id}.json",
                      "solution_r001": f"solution_synth_r001_{run_id}.json"},
        "elapsedS": 12.5,
    }
    record = {
        "case": case,
        "runId": run_id,
        "status": "done" if ok else "error",
        "outcome": "fidelity" if ok else "failed",
        "runRecord": run_record,
        "result": {"ok": ok, "review": review or {}, "validation": {"ok": True}},
        "assertion": {"skipped": None,
                      "metrics": {"assertion_ok": True, "assertion_errors": []}},
        "assertOk": True,
        "screenshots": [f"{case}-01.png", f"{case}-02.png"],
        "pageErrors": {"errors": [], "rejections": []},
        "caseDir": case_dir,
    }
    if with_assets and case_dir:
        model_name = run_record["artifacts"]["model_r001"]
        solution_name = run_record["artifacts"]["solution_r001"]
        _write_json(os.path.join(case_dir, "evidence", model_name),
                    {"revision": 1, "totalVoxels": 300, "layers": [], "ops": []})
        _write_json(os.path.join(case_dir, "evidence", solution_name),
                    {"revision": 1, "validation": {"ok": True}, "steps": []})
    return record


@pytest.fixture()
def evidence_tree(tmp_path):
    """造 3 条有效单例 + 1 条非单例 + environment.json，返回 (root, entries)。"""
    root = tmp_path / "e2e"
    specs = [
        # 三条连续编号：旧口径 1+2+3=6，新口径 3
        ("C07", "runaaa1", [1, 2, 3], {"scores": {"overall": 6}}),
        # 跳号：旧口径 1+2+5=8，新口径 5
        ("C10", "runaaa2", [1, 2, 5], {"scores": {"overall": 4.5}}),
        # 空列表：0/0，无任务评审
        ("N13", "runaaa3", [], {}),
    ]
    for case, run_id, requests, review in specs:
        case_dir = root / "roundA" / case
        record = _make_record(case, run_id, requests, review=review,
                             case_dir=str(case_dir))
        # 单例记录放在轮次目录下：<root>/roundA/<CASE>.json（产物在 <CASE>/evidence/）
        _write_json(root / "roundA" / f"{case}.json", record)
    # 干扰项：非单例记录与环境文件应被跳过
    _write_json(root / "roundA" / "environment.json", {"note": "干扰项"})
    _write_json(root / "roundA" / "summary.json", {"note": "干扰项"})
    _write_json(root / "roundA" / "extra.json", {"case": "X01"})
    return str(root)


# ---------------------------------------------------------------- 1. draw 请求数


def test_draw_request_stats_sum_vs_max():
    """连续累计编号：旧求和 6 vs 新取最大 3，识别为被纠正。"""
    stats = draw_request_stats([{"request": 1}, {"request": 2}, {"request": 3}])
    assert stats["old_sum"] == 6
    assert stats["new_max"] == 3
    assert stats["corrected"] is True
    assert stats["delta"] == 3
    assert stats["sequence"] == [1, 2, 3]
    assert stats["attempts"] == 3


def test_draw_request_stats_empty_and_single():
    """空列表为 0 且不纠正；单次请求两口径相同。"""
    empty = draw_request_stats([])
    assert (empty["old_sum"], empty["new_max"], empty["corrected"]) == (0, 0, False)
    single = draw_request_stats([{"request": 1}])
    assert (single["old_sum"], single["new_max"], single["corrected"]) == (1, 1, False)
    assert draw_request_stats(None)["new_max"] == 0


def test_draw_request_stats_skip_sequence():
    """跳号序列（1,2,5）旧求和 8，新取最大 5，仍判为被纠正。"""
    stats = draw_request_stats([{"request": 1}, {"request": 2}, {"request": 5}])
    assert stats["old_sum"] == 8
    assert stats["new_max"] == 5
    assert stats["corrected"] is True


def test_draw_request_stats_invalid_values():
    """缺字段/非法值按 0 计，不抛异常。"""
    stats = draw_request_stats([{"request": None}, {}, {"request": "x"}, {"request": 2}])
    assert stats["sequence"] == [0, 0, 0, 2]
    assert stats["old_sum"] == 2
    assert stats["new_max"] == 2


# ---------------------------------------------------------------- 2. 视觉分恢复


def test_review_recovered_from_result_fallback():
    """run 记录无 review 时用任务 result 补入，标记恢复并保留小数。"""
    sources = review_sources({}, {"review": {"scores": {"overall": 4.5}}})
    assert sources["review_from_run_record"] is None
    assert sources["review_fallback_from_result"] == 4.5
    assert sources["effective_review"] == 4.5
    assert sources["review_source"] == "result_fallback"
    assert sources["recovered"] is True


def test_review_prefers_run_record():
    """run 记录已有 review 时以其为准，不标记恢复。"""
    sources = review_sources({"review": {"scores": {"overall": 7}}},
                             {"review": {"scores": {"overall": 3}}})
    assert sources["effective_review"] == 7
    assert sources["review_source"] == "run_record"
    assert sources["recovered"] is False


def test_review_missing_stays_none():
    """两边都没有评审时保持 None（不猜测、不补默认分）。"""
    sources = review_sources({}, {})
    assert sources["effective_review"] is None
    assert sources["review_source"] == "none"
    assert sources["recovered"] is False
    assert review_overall({"scores": {}}) is None
    assert review_overall(None) is None
    assert review_overall({"scores": {"overall": True}}) is None


# ---------------------------------------------------------------- 3. 断言结论对比


def test_compare_assertions_only_caliber_changed():
    """只有口径字段（draw_requests/review）变化、结论不变 → conclusion_changed=False。"""
    old = {"assertion_ok": False, "assertion_errors": ["缺少部位 plaque"],
           "draw_requests": 6, "review_overall": None}
    new = {"assertion_ok": False, "assertion_errors": ["缺少部位 plaque"],
           "draw_requests": 3, "review_overall": 6}
    result = compare_assertions(old, new)
    assert result["available"] is True
    assert result["conclusion_changed"] is False
    assert result["conclusion_ok_changed"] is False
    assert result["added_errors"] == []
    assert result["removed_errors"] == []


def test_compare_assertions_detects_change():
    """错误项变化或通过性翻转必须判为结论改变并列出差异。"""
    changed = compare_assertions(
        {"assertion_ok": True, "assertion_errors": []},
        {"assertion_ok": False, "assertion_errors": ["复杂度未达设计下限"]})
    assert changed["conclusion_changed"] is True
    assert changed["conclusion_ok_changed"] is True
    assert changed["added_errors"] == ["复杂度未达设计下限"]

    removed = compare_assertions(
        {"assertion_ok": False, "assertion_errors": ["A", "B"]},
        {"assertion_ok": False, "assertion_errors": ["B"]})
    assert removed["conclusion_changed"] is True
    assert removed["removed_errors"] == ["A"]
    assert removed["conclusion_ok_changed"] is False


def test_compare_assertions_unavailable():
    """缺少断言结果时不伪造结论。"""
    assert compare_assertions(None, {})["available"] is False
    assert compare_assertions({"assertion_ok": None}, {"assertion_ok": True})["available"] is False


# ---------------------------------------------------------------- 4. 证据加载


def test_load_records_scans_singletons(evidence_tree):
    """只加载含 runRecord 的单例 JSON，跳过 environment/summary/非单例。"""
    warnings = []
    entries = load_records(evidence_tree, warnings=warnings)
    assert [entry["case"] for entry in entries] == ["C07", "C10", "N13"]
    assert all(entry["dir"] == "roundA" for entry in entries)
    assert any("缺少 runRecord" in item["error"] for item in warnings)


def test_load_case_assets_found_and_missing(evidence_tree):
    """产物从 <案例目录>/evidence/ 加载；缺失时给出原因。"""
    entries = load_records(evidence_tree)
    entry = entries[0]
    entry["record"]["caseDir"] = os.path.join(evidence_tree, "roundA", "C07")
    model, solution, missing = load_case_assets(entry, entry["record"]["runRecord"], [])
    assert model is not None and solution is not None
    assert missing == []

    broken = entries[2]
    broken["record"]["caseDir"] = os.path.join(evidence_tree, "roundA", "C10")
    warnings = []
    model, solution, missing = load_case_assets(
        broken, {"revision": 9, "artifacts": {}}, warnings)
    assert model is None and solution is None
    assert len(missing) == 2 and all("未在 run 记录 artifacts 中登记" in m for m in missing)
    assert len(warnings) == 2


# ---------------------------------------------------------------- 5. 重算与聚合


def test_recompute_record_fields(evidence_tree):
    """单条重算：draw 双口径、评审恢复、目标块数、任务态、留存断言。"""
    entries = load_records(evidence_tree)
    for seq, entry in enumerate(entries, 1):
        entry["seq"] = seq
    first = recompute_record(entries[0], run_assertions=False)
    assert first["draw_requests_old"] == 6
    assert first["draw_requests_new"] == 3
    assert first["draw_request_corrected"] is True
    assert first["review_from_run_record"] is None
    assert first["effective_review"] == 6
    assert first["review_recovered"] is True
    assert first["target_blocks"] == 300
    assert first["task_state"] == "delivered"
    assert first["assertion"]["available"] is False
    assert first["saved_assertion"]["assert_ok_top"] is True

    empty = recompute_record(entries[2], run_assertions=False)
    assert (empty["draw_requests_old"], empty["draw_requests_new"]) == (0, 0)
    assert empty["effective_review"] is None
    assert empty["review_recovered"] is False


def test_recompute_target_blocks_fallback(evidence_tree):
    """run 记录没有 scaleMetrics 时用 plan_scale.parse_target_blocks 从需求原文补出。"""
    entries = load_records(evidence_tree)
    entry = entries[0]
    entry["record"]["runRecord"].pop("scaleMetrics")
    row = recompute_record(entry, run_assertions=False)
    assert row["target_blocks"] == 300
    assert row["target_blocks_source"] == "parse_target_blocks"


def test_aggregate_group_numbers(evidence_tree):
    """分组聚合：案例数 / 旧新合计 / 纠正数 / 视觉分恢复数正确。"""
    entries = load_records(evidence_tree)
    for seq, entry in enumerate(entries, 1):
        entry["seq"] = seq
    rows = [recompute_record(entry, run_assertions=False) for entry in entries]
    summaries = aggregate(rows, {"roundA": None, "empty_group": ["no-such-dir"]})
    group = summaries[0]
    assert group["group"] == "roundA"
    assert group["cases"] == 3
    assert group["draw_requests_old_total"] == 6 + 8 + 0
    assert group["draw_requests_new_total"] == 3 + 5 + 0
    assert group["draw_corrected_cases"] == 2
    assert group["review_fallback_cases"] == 2
    assert group["review_recovered_cases"] == 2
    assert group["assertion_compared_cases"] == 0
    assert group["assertion_conclusion_changed_cases"] == 0
    empty = summaries[1]
    assert empty["cases"] == 0
    assert empty["draw_requests_old_total"] == 0
    assert empty["assertion_conclusion_changed_cases"] == 0


def test_aggregate_recent12_group_by_dir(tmp_path):
    """默认分组按目录名精确匹配（gc6-on/cleanup 归入 recent12）。"""
    entries, rows = [], []
    for dir_name, run_id in (("20261108-gc6-on", "r1"), ("20261109-cleanup-r0", "r2"),
                             ("20261108-gc6-off", "r3")):
        case_dir = tmp_path / dir_name / "C07"
        record = _make_record("C07", run_id, [1, 2], {"scores": {"overall": 5}},
                              case_dir=str(case_dir))
        _write_json(case_dir / "C07.json", record)
        entries.append({"record": record, "dir": dir_name, "case": "C07",
                        "path": str(case_dir / "C07.json"), "seq": len(entries) + 1})
    rows = [recompute_record(entry, run_assertions=False) for entry in entries]
    groups = {g["group"]: g for g in aggregate(rows)}
    assert groups["gc6"]["cases"] == 2
    assert groups["recent12"]["cases"] == 2
    assert groups["all"]["cases"] == 3
    assert groups["recent12"]["draw_requests_old_total"] == 6
    assert groups["recent12"]["draw_requests_new_total"] == 4
    assert groups["recent12"]["review_recovered_cases"] == 2
