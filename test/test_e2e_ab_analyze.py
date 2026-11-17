# -*- coding: utf-8 -*-
"""tools/e2e_ab_analyze.py 的配对分析器测试（全部本地合成数据，不联网、不调用 LLM）。

覆盖（任务要求的逐项验收点）：
  1. 两臂逐例配对正确（行对齐、缺例标注）；
  2. draw_requests 取 drawAttempts[].request 最大值（[1,2,3]→3；空→0；旧求和口径不采信）；
  3. run 记录没有 review 时从任务 result.review 补入并标注来源；
  4. support 类失败尝试计数口径可复现（rejections/failures/gateErrors 三种来源与去重规则）；
  5. 分组汇总中位数、契约拦截率/拦截后修复率、六项门槛的 PASS/FAIL 判定（构造能过与不过两组数据）；
  6. 缺字段/旧记录：不崩溃、字段标「无法判定」、并在报告/JSON 中留证据；
  7. 多轮追加目录：逐例取多轮中位、标注非单轮；
  8. write_outputs/main 真实落盘 ab-analyze.json 与 ab-report.md（CLI 退出码 0/1）。
"""
import json
import os
import tempfile
import unittest

from tools import e2e_ab_analyze as ab

CODE_HEAD = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------- 合成数据工具
def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def make_metrics(case_id, *, requirement_ok=True, tier_style="dict", validation_ok=True,
                 gate_ok=True, requests=None, review_stale=False, version_overwrites=0,
                 parts=12, voxels=800, bricks=120, target=200):
    """构造 C/H 风格（dict 两档）或 G/N 风格（requirement_tier 列表）的断言 metrics。"""
    requests = [1] if requests is None else list(requests)
    failure_text = "部位清单缺少核心部位"
    if tier_style == "list":
        requirement_tier = [] if requirement_ok else [failure_text]
        metrics = {
            "case": case_id, "suite": "R", "task_ok": True, "parts": parts,
            "voxels": voxels, "pieces": bricks, "target_blocks": target,
            "bricks_ratio": round(bricks / float(target), 4), "validation_ok": validation_ok,
            "draw_attempts": len(requests), "draw_requests": sum(requests),
            "review_overall": None, "final_gate_replay": {"ok": gate_ok},
            "requirement_tier": requirement_tier,
            "generic_tier": [] if validation_ok and gate_ok else ["最终门禁重放未通过"],
            "assertion_ok": requirement_ok and validation_ok and gate_ok,
            "assertion_errors": [] if requirement_ok else [failure_text],
        }
    else:
        requirement_tier = {
            "target_blocks": target, "bricks": bricks,
            "bricks_ratio": round(bricks / float(target), 4), "target_blocks_ok": True,
            "require_parts": {"ok": requirement_ok,
                              "errors": [] if requirement_ok else [failure_text]},
            "feature_checks": [{"name": "测试特征", "ok": requirement_ok,
                                "errors": [] if requirement_ok else ["特征未成型"]}],
            "complexity": {"parts": {"required": 5, "actual": parts, "ok": True},
                           "solid_parts": {"required": 1, "actual": 2, "ok": True},
                           "voxels": {"required": 100, "actual": voxels, "ok": True},
                           "ops": {"required": 1, "actual": 1, "ok": None}},
            "ok": requirement_ok, "errors": [] if requirement_ok else [failure_text],
        }
        metrics = {
            "case": case_id, "suite": "P", "task_ok": True, "parts": parts,
            "voxels": voxels, "pieces": bricks, "target_blocks": target,
            "bricks_ratio": round(bricks / float(target), 4), "validation_ok": validation_ok,
            "draw_attempts": len(requests), "draw_requests": sum(requests),
            "review_overall": None, "final_gate_source": "replay", "final_gate_ok": gate_ok,
            "version_overwrites": version_overwrites, "review_stale": review_stale,
            "requirement_tier": requirement_tier,
            "assertion_errors": [] if requirement_ok else [failure_text],
            "assertion_ok": requirement_ok and validation_ok and gate_ok,
        }
    return metrics


def make_case(case_id, *, name="测试案例", task_ok=True, requirement_ok=True,
              tier_style="dict", requests=None, review_overall=None,
              result_review_overall=None, rejections=None, failures=None,
              contract_checks=None, validation_ok=True, gate_ok=True,
              review_stale=False, version_overwrites=0, elapsed=100.0,
              page_errors=0, console_errors=0, screenshots=2, internal=False,
              metrics_present=None, artifacts=True, outcome=None):
    """构造一例 e2e_browser_20 风格的 `<CASE>.json`（含 runRecord / result / metrics）。"""
    requests = [1] if requests is None else list(requests)
    run_id = f"run-{case_id}"
    metrics_present = (task_ok if metrics_present is None else metrics_present)
    metrics = None
    if metrics_present and task_ok:
        metrics = make_metrics(case_id, requirement_ok=requirement_ok,
                               tier_style=tier_style, validation_ok=validation_ok,
                               gate_ok=gate_ok, requests=requests,
                               review_stale=review_stale,
                               version_overwrites=version_overwrites)
    assertion_ok = bool(task_ok and metrics and metrics.get("assertion_ok"))
    default_failures = []
    if not task_ok:
        default_failures = [{"kind": "internal", "stage": "draw"} if internal
                            else {"kind": "gate", "stage": "draw_draft"}]
    run_record = {
        "runId": run_id, "ok": task_ok, "revision": 1, "mode": "fidelity",
        "desc": f"{case_id} 测试需求", "failures": failures if failures is not None
        else default_failures,
        "rejections": rejections if rejections is not None else [],
        "drawAttempts": [{"attempt": i + 1, "request": request, "outcome": "draft"}
                         for i, request in enumerate(requests if task_ok else [])],
        "contractChecks": contract_checks if contract_checks is not None else [],
        "gateErrors": [], "finalGateReplay": ({"ok": gate_ok, "errors": []}
                                             if gate_ok is not None and task_ok else None),
        "review": {"scores": {"overall": review_overall}}
        if review_overall is not None else None,
        "versionOverwriteCount": version_overwrites, "reviewStale": review_stale,
        "reviewHashMissing": review_overall is None,
        "artifacts": {"model_r001": "m.json", "solution_r001": "s.json",
                      "md_r001": "md.md"} if artifacts and task_ok else {},
        "elapsedS": elapsed,
    }
    review_result = ({"scores": {"overall": result_review_overall}}
                     if result_review_overall is not None else {})
    result = {"ok": task_ok, "run_id": run_id,
              "outcome": outcome or ("fidelity_degraded" if task_ok else "failed"),
              "review": review_result, "validation": {"ok": validation_ok},
              "review_flag": None, "review_unavailable": False,
              "review_failed": False, "gate_failed": not gate_ok}
    return {
        "case": case_id, "name": name, "desc": f"{case_id} 测试需求",
        "status": "done" if task_ok else "error",
        "outcome": outcome or ("fidelity_degraded" if task_ok else "failed"),
        "taskOk": task_ok, "assertOk": assertion_ok, "runId": run_id,
        "elapsedFinal": elapsed,
        "console_errors": ["console error"] * console_errors,
        "pageErrors": {"errors": ["page error"] * page_errors, "rejections": []},
        "screenshots": [f"{i:02d}.png" for i in range(screenshots)],
        "assertion": {"skipped": None if metrics else "任务未成功（无最终产物）",
                      "metrics": metrics},
        "result": result,
        "runRecord": run_record,
    }


def write_round(base, arm, cases, env_overrides=None, write_env=True):
    """写一个完整合成轮次目录（environment.json + 每例 JSON），返回目录路径。"""
    root = os.path.join(base, f"{arm}-round")
    os.makedirs(root, exist_ok=True)
    env = {
        "label": f"ab-{arm}", "startedAt": "2026-11-14T10:00:00",
        "finishedAt": "2026-11-14T12:00:00",
        "outdir": root, "cases": ",".join(c["case"] for c in cases),
        "concurrency": 2, "timeoutS": 2100, "python": "3.11",
        "modelEnvVar": None, "modelConfigured": "test-model",
        "codeHead": CODE_HEAD, "codeBranch": "master", "worktreeDirty": False,
        "frozenNote": "",
        "experimentEnv": {"LEGOGOD_GEOMETRY_CONTRACT": arm},
    }
    env.update(env_overrides or {})
    if write_env:
        write_json(os.path.join(root, "environment.json"), env)
    for case in cases:
        write_json(os.path.join(root, f"{case['case']}.json"), case)
    return root


def make_pass_dataset(base):
    """能通过全部六项门槛的配对数据（OFF/ON 各 4 例）。"""
    off_cases = [
        # 交付 + 断言失败（需求未过），单次 draw；review 来自 run 记录
        make_case("P01", requirement_ok=False, requests=[1], review_overall=4),
        # 交付 + 断言失败；draw 请求累计 [1,2,3]（旧 metrics 求和=6，必须取 max=3）；
        # review 缺失 → 从 result 补入；support：gate 文本 + 求解失败各 1
        make_case("P02", requirement_ok=False, requests=[1, 2, 3],
                  result_review_overall=5,
                  rejections=[{"kind": "gate", "phase": "draw", "request": 1,
                               "summary": "有 2 个体素无论怎么铺砖都得不到支撑或连接"}],
                  failures=[{"kind": "disconnected", "stage": "solve"}]),
        # R 组；support：gate 文本命中 1 次
        make_case("R01", requirement_ok=False, requests=[2], review_overall=4,
                  tier_style="list",
                  rejections=[{"kind": "gate", "phase": "draw", "request": 1,
                               "summary": "立体部位悬空 3 格，无支撑"}]),
        # 任务失败：无 metrics，internal 1 例（用于验证「无新增 internal」的相对比较）
        make_case("R02", task_ok=False, metrics_present=False, internal=True),
    ]
    on_cases = [
        make_case("P01", requirement_ok=True, requests=[1], review_overall=7,
                  contract_checks=[{"phase": "draw", "revision": 0, "kinds": [],
                                    "violationCount": 0}]),
        # 需求通过；review 缺失 → result 补入；契约拦截 1 次后修复成功
        make_case("P02", requirement_ok=True, requests=[1, 2], result_review_overall=6,
                  contract_checks=[
                      {"phase": "draw", "revision": 0, "kinds": ["support"],
                       "violationCount": 2},
                      {"phase": "draw", "revision": 0, "kinds": [], "violationCount": 0}],
                  rejections=[{"kind": "contract", "phase": "draw", "request": 1,
                               "summary": "有 2 个体素无论怎么铺砖都得不到支撑或连接"}]),
        make_case("R01", requirement_ok=True, requests=[1], review_overall=6,
                  tier_style="list",
                  contract_checks=[{"phase": "draw", "revision": 0, "kinds": [],
                                    "violationCount": 0}]),
        make_case("R02", requirement_ok=False, requests=[1, 2], review_overall=4,
                  tier_style="list"),
    ]
    return (write_round(base, "off", off_cases), write_round(base, "on", on_cases))


def make_fail_dataset(base):
    """六项门槛全部 FAIL 的配对数据（OFF 全交付，ON 交付/正确性/成本/机制全面退化）。"""
    off_cases = [
        make_case("P01", requests=[1], review_overall=6),
        make_case("P02", requests=[1], review_overall=6),
        make_case("R01", requests=[1], review_overall=6, tier_style="list"),
        make_case("R02", requests=[1], review_overall=6, tier_style="list",
                  rejections=[{"kind": "gate", "phase": "draw", "request": 1,
                               "summary": "悬空 2 格"}]),
    ]
    on_cases = [
        # 交付退化：OFF 交付 4 例 → ON 只有 3 例
        make_case("P01", task_ok=False, metrics_present=False),
        # 需求失败 + 可信底线退化（统一校验/最终门禁/版本覆盖/页面错误/视觉分缺失）
        make_case("P02", requirement_ok=False, requests=[5], elapsed=200.0,
                  validation_ok=False, gate_ok=False, version_overwrites=1,
                  page_errors=3,
                  rejections=[{"kind": "gate", "phase": "draw", "request": 1,
                               "summary": "支撑不足，悬空"}],
                  failures=[{"kind": "support", "stage": "solve"}]),
        make_case("R01", requests=[5], elapsed=200.0, review_overall=6,
                  tier_style="list"),
        make_case("R02", requests=[5], elapsed=200.0, review_overall=6,
                  tier_style="list", internal=True,
                  rejections=[{"kind": "gate", "phase": "draw", "request": 1,
                               "summary": "悬空 1 格"}]),
    ]
    off = write_round(base, "off", off_cases)
    # ON 臂开关被错误地置成 off：机制证据不成立（同时破坏单变量一致性）
    on = write_round(base, "on", on_cases,
                     env_overrides={"experimentEnv": {"LEGOGOD_GEOMETRY_CONTRACT": "off"}})
    return off, on


# ---------------------------------------------------------------- 测试
class DrawRequestTest(unittest.TestCase):
    """draw 请求数口径：累计编号取最大值，空/缺失为 0，不采信旧求和。"""

    def test_max_value_and_empty(self):
        self.assertEqual(ab.draw_request_count([{"request": 1}, {"request": 2},
                                                {"request": 3}]), 3)
        self.assertEqual(ab.draw_request_count([]), 0)
        self.assertEqual(ab.draw_request_count(None), 0)
        self.assertEqual(ab.draw_request_count([{}, {"request": "bad"}, {"request": "2"}]), 2)

    def test_case_extract_uses_max_and_marks_source(self):
        with tempfile.TemporaryDirectory() as base:
            case = make_case("P02", requirement_ok=False, requests=[1, 2, 3])
            path = os.path.join(base, "P02.json")
            write_json(path, case)
            record = ab.extract_case(path, {"codeHead": CODE_HEAD}, {"P01", "P02"})
            self.assertEqual(record["draw_requests"], 3)  # 不是 1+2+3=6
            self.assertEqual(record["draw_requests_source"], "runRecord.drawAttempts.max")
            self.assertEqual(record["draw_attempts"], 3)


class PairingTest(unittest.TestCase):
    """逐例配对：行按 case id 对齐；缺例标注；组别按 P 集合划分。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        off_cases = [make_case("P01"), make_case("P02"), make_case("R01")]
        on_cases = [make_case("P01"), make_case("P02"), make_case("R02")]
        self.off = write_round(self.base, "off", off_cases)
        self.on = write_round(self.base, "on", on_cases)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pair_rows_missing_marked(self):
        analysis = ab.build_analysis([self.off], [self.on], ["P01", "P02"])
        rows = {row["case"]: row for row in analysis["cases"]}
        self.assertEqual(set(rows), {"P01", "P02", "R01", "R02"})
        self.assertTrue(rows["P01"]["paired"])
        self.assertTrue(rows["P02"]["paired"])
        self.assertFalse(rows["R01"]["paired"])
        self.assertTrue(rows["R01"]["missingOn"])
        self.assertFalse(rows["R02"]["paired"])
        self.assertTrue(rows["R02"]["missingOff"])
        self.assertEqual(analysis["caseIds"]["offOnly"], ["R01"])
        self.assertEqual(analysis["caseIds"]["onOnly"], ["R02"])
        self.assertEqual(rows["P01"]["suite"], "P")
        self.assertEqual(rows["R01"]["suite"], "R")
        # 缺例在报告里有明确标注，且配对比较只用 2 例
        report = ab.render_report(analysis)
        self.assertIn("OFF 臂缺少该例记录", report)
        self.assertIn("ON 臂缺少该例记录", report)
        self.assertEqual(analysis["groups"]["off"]["PAIRED"]["ALL"]["cases"], 2)


class ReviewFallbackTest(unittest.TestCase):
    """run 记录 review 缺失时从任务 result.review 补入，并标注来源。"""

    def test_review_from_result_with_evidence(self):
        with tempfile.TemporaryDirectory() as base:
            case = make_case("P01", result_review_overall=5, review_overall=None)
            path = os.path.join(base, "P01.json")
            write_json(path, case)
            record = ab.extract_case(path, {"codeHead": CODE_HEAD}, {"P01"})
            self.assertEqual(record["review_overall"], 5)
            self.assertEqual(record["review_source"], "task_result")
            # 报告第 8 节列补入证据路径
            off = write_round(base, "off", [case])
            on = write_round(base, "on", [make_case("P01", review_overall=6)])
            analysis = ab.build_analysis([off], [on], ["P01"])
            report = ab.render_report(analysis)
            self.assertIn("result.review.scores.overall=5", report)

    def test_review_from_run_record_preferred(self):
        with tempfile.TemporaryDirectory() as base:
            case = make_case("P01", review_overall=7, result_review_overall=3)
            path = os.path.join(base, "P01.json")
            write_json(path, case)
            record = ab.extract_case(path, {"codeHead": CODE_HEAD}, {"P01"})
            self.assertEqual(record["review_overall"], 7)
            self.assertEqual(record["review_source"], "run_record")


class SupportAttemptsTest(unittest.TestCase):
    """support 类失败尝试口径可复现：三类来源、revise_* 排除、旧记录回退、去重。"""

    def test_definition(self):
        run_record = {
            "rejections": [
                {"kind": "gate", "summary": "有 3 个体素无论怎么铺砖都得不到支撑或连接"},
                {"kind": "ops_policy", "summary": "视觉修订改到了未点名部位"},
                {"kind": "contract", "summary": "模型有 2 个互不相连的部分"},
            ],
            "failures": [
                {"kind": "disconnected", "stage": "solve"},
                {"kind": "support", "stage": "revise_class1"},  # 已接受修订触发记录，不计
                {"kind": "gate", "stage": "draw_draft"},        # 门禁，非 support 类 kind
            ],
            "gateErrors": [],
            "contractChecks": [{"kinds": ["support"], "violationCount": 1}],
        }
        state = ab._support_attempts(run_record)
        # gate 文本 1 + contract 文本 1 + solve disconnected 1 = 3
        self.assertEqual(state["total"], 3)
        self.assertEqual(state["rejections"], 2)
        self.assertEqual(state["solveFailures"], 1)
        self.assertEqual(state["nonContractTotal"], 2)  # 排除 1 次 contract 拦截
        self.assertEqual(state["contractChecksSupport"], 1)  # 只作佐证
        self.assertTrue(any("rejections[0]" in item for item in state["evidence"]))

    def test_old_record_gate_errors_fallback(self):
        state = ab._support_attempts({"gateErrors": ["有 1 个体素悬空，得不到支撑"]})
        self.assertEqual(state["total"], 1)
        self.assertEqual(state["gateErrorsFallback"], 1)
        # 有 rejections/failures 字段（哪怕是空列表）时不再回退，避免重复统计
        state2 = ab._support_attempts({"rejections": [], "failures": [],
                                       "gateErrors": ["悬空，得不到支撑"]})
        self.assertEqual(state2["total"], 0)

    def test_missing_run_record_not_crash(self):
        self.assertIsNone(ab._support_attempts(None)["total"])
        self.assertIsNone(ab._support_attempts({})["total"])


class GroupAggregateTest(unittest.TestCase):
    """分组汇总：中位数、契约拦截率/修复率、误伤清单。"""

    def test_medians_and_contract_rates(self):
        with tempfile.TemporaryDirectory() as base:
            off = write_round(base, "off", [
                make_case("P01", requests=[1], review_overall=5),
                make_case("P02", requests=[3], review_overall=5),
                make_case("R01", requests=[5], review_overall=5, tier_style="list"),
            ])
            on = write_round(base, "on", [
                make_case("P01", requests=[1], review_overall=5,
                          contract_checks=[{"phase": "draw", "kinds": ["support"],
                                            "violationCount": 1},
                                           {"phase": "draw", "kinds": [],
                                            "violationCount": 0}],
                          rejections=[{"kind": "contract", "phase": "draw",
                                       "request": 1, "summary": "得不到支撑"}]),
                make_case("P02", requests=[2], review_overall=5),
                make_case("R01", requests=[1], requirement_ok=False,
                          review_overall=5, tier_style="list",
                          contract_checks=[{"phase": "draw", "kinds": ["support"],
                                            "violationCount": 1},
                                           {"phase": "draw", "kinds": ["support"],
                                            "violationCount": 1}],
                          rejections=[{"kind": "contract", "phase": "draw",
                                       "request": 1, "summary": "得不到支撑"}]),
            ])
            analysis = ab.build_analysis([off], [on], ["P01", "P02"])
            go = analysis["groups"]["off"]["ALL"]
            gn = analysis["groups"]["on"]["ALL"]
            self.assertEqual(go["drawMedian"], 3)      # [1,3,5] 中位
            self.assertEqual(gn["drawMedian"], 1)      # [1,2,1] 中位
            self.assertEqual(gn["contractChecksTotal"], 4)
            self.assertEqual(gn["contractFlaggedChecks"], 3)
            self.assertAlmostEqual(gn["contractInterceptRate"], 0.75)
            self.assertEqual(gn["interceptedCases"], ["P01", "R01"])
            self.assertEqual(gn["repairedCases"], ["P01"])  # R01 末次检查仍有违规
            self.assertAlmostEqual(gn["contractRepairRate"], 0.5)
            # 误伤可疑：P01 拦截后最终全断言通过
            self.assertEqual([s["case"] for s in gn["suspects"]], ["P01"])

    def test_multi_round_median(self):
        with tempfile.TemporaryDirectory() as base:
            r1 = write_round(os.path.join(base, "a"), "off", [
                make_case("P01", requests=[1], review_overall=5)])
            r2 = write_round(os.path.join(base, "b"), "off", [
                make_case("P01", requests=[3], review_overall=5,
                          rejections=[{"kind": "gate", "summary": "悬空"},
                                      {"kind": "gate", "summary": "悬空"}])])
            on = write_round(base, "on", [make_case("P01", requests=[2],
                                                    review_overall=5)])
            analysis = ab.build_analysis([r1, r2], [on], ["P01"])
            self.assertFalse(analysis["arms"]["off"]["singleRound"])
            self.assertTrue(analysis["arms"]["on"]["singleRound"])
            merged = {row["case"]: row for row in analysis["cases"]}["P01"]["off"]
            self.assertEqual(merged["draw_requests"], 2)  # [1,3] 中位
            self.assertEqual(merged["support"]["total"], 1)  # [0,2] 中位
            self.assertIn("多轮中位", ab.render_report(analysis))


class GatePassTest(unittest.TestCase):
    """构造能过全部门槛的数据：六项必须 PASS，主入口退出码 0。"""

    def test_all_gates_pass(self):
        with tempfile.TemporaryDirectory() as base:
            off, on = make_pass_dataset(base)
            analysis = ab.build_analysis([off], [on], ["P01", "P02"])
            statuses = {gate["id"]: gate["status"] for gate in analysis["gates"]}
            self.assertEqual(statuses, {"trust": "PASS", "delivery": "PASS",
                                        "requirement": "PASS", "structure": "PASS",
                                        "cost": "PASS", "mechanism": "PASS"})
            self.assertEqual(analysis["verdict"]["status"], "全部通过（可评估默认开启）")
            # 关键数字符合构造：交付 OF/OFF、需求和 support 收益、成本
            go = analysis["groups"]["off"]["PAIRED"]["ALL"]
            gn = analysis["groups"]["on"]["PAIRED"]["ALL"]
            self.assertEqual((go["delivered"], gn["delivered"]), (3, 4))
            self.assertEqual((go["requirementPass"], gn["requirementPass"]), (0, 3))
            self.assertEqual((go["supportTotal"], gn["supportTotal"]), (3, 1))
            self.assertEqual(go["drawMedian"], 2)
            self.assertEqual(gn["drawMedian"], 1.5)
            self.assertTrue(all(gate["provisional"] for gate in analysis["gates"]))  # 单轮初筛
            out = os.path.join(base, "out")
            json_path, md_path = ab.write_outputs(analysis, out)
            self.assertTrue(os.path.isfile(json_path))
            self.assertTrue(os.path.isfile(md_path))
            data = json.load(open(json_path, encoding="utf-8"))
            self.assertEqual(data["definitionVersion"], "ab-analyze-v1")
            self.assertIn("ab-support-v1", data["supportDefinition"])
            report = open(md_path, encoding="utf-8").read()
            for token in ("门槛判定", "support 类失败尝试", "逐例对比", "无法判定项清单",
                          "单轮初筛"):
                self.assertIn(token, report)
            # CLI 退出码 0（无 FAIL）
            code = ab.main(["--off", off, "--on", on, "--out", os.path.join(base, "cli")])
            self.assertEqual(code, 0)


class GateFailTest(unittest.TestCase):
    """构造全面退化的数据：六项门槛必须 FAIL，主入口退出码 1。"""

    def test_all_gates_fail(self):
        with tempfile.TemporaryDirectory() as base:
            off, on = make_fail_dataset(base)
            analysis = ab.build_analysis([off], [on], ["P01", "P02"])
            gates = {gate["id"]: gate for gate in analysis["gates"]}
            for gate_id in ("trust", "delivery", "requirement", "structure",
                            "cost", "mechanism"):
                self.assertEqual(gates[gate_id]["status"], "FAIL",
                                 f"{gate_id} 门槛应 FAIL：{gates[gate_id]['detail']}")
            self.assertTrue(analysis["verdict"]["status"].startswith("否决"))
            self.assertIn("trust", analysis["verdict"]["failed"])
            report = ab.render_report(analysis)
            self.assertIn("❌ FAIL", report)
            code = ab.main(["--off", off, "--on", on, "--out", os.path.join(base, "cli")])
            self.assertEqual(code, 1)


class MissingFieldsTest(unittest.TestCase):
    """缺字段/旧记录/损坏 JSON：不崩溃、标注无法判定、保留证据。"""

    def test_missing_fields_undetermined(self):
        with tempfile.TemporaryDirectory() as base:
            off = os.path.join(base, "off-broken")
            on = os.path.join(base, "on-broken")
            os.makedirs(off)
            os.makedirs(on)
            # OFF：完全没有 environment.json；一例只有最基本字段
            write_json(os.path.join(off, "P01.json"), {"case": "P01", "taskOk": True})
            # ON：environment 只有标签；一例基本字段，一例 JSON 损坏
            write_json(os.path.join(on, "environment.json"), {"label": "ab-on"})
            write_json(os.path.join(on, "P01.json"),
                       {"case": "P01", "taskOk": True, "pageErrors": None})
            with open(os.path.join(on, "P02.json"), "w", encoding="utf-8") as f:
                f.write("{broken json")
            analysis = ab.build_analysis([off], [on], ["P01"])
            # 不崩溃且记录了读取问题
            self.assertEqual(analysis["arms"]["off"]["caseCount"], 1)
            self.assertTrue(analysis["arms"]["off"]["errors"])       # environment 缺失
            report = ab.render_report(analysis)                       # 渲染不崩溃
            self.assertIn("无法判定", report)
            # 断言关键结论未被编造：交付但缺少 metrics 的案例列入无法判定清单
            self.assertTrue(analysis["undetermined"])
            self.assertTrue(any("无法判定" in str(item.get("item"))
                                or "无法" in str(item.get("reason"))
                                or "缺失" in str(item.get("reason"))
                                for item in analysis["undetermined"]))
            # 损坏 JSON 不进入有效案例，但在无法判定清单/字段缺失中留痕
            damaged = [item for item in analysis["undetermined"]
                       if "case JSON" in str(item.get("item"))]
            self.assertTrue(damaged)
            # 至少一个门槛必须是「无法判定」（没有证据就不能编结论）
            self.assertTrue(any(gate["status"] == "无法判定"
                                for gate in analysis["gates"]))

    def test_old_record_without_new_fields(self):
        """旧记录：run 记录无 contractChecks/review/drawAttempts，用 metrics 回退不崩溃。"""
        with tempfile.TemporaryDirectory() as base:
            case = make_case("P01", requests=[1, 2], review_overall=None)
            # 模拟旧记录：删掉新口径字段
            for key in ("contractChecks", "review", "drawAttempts"):
                case["runRecord"].pop(key, None)
            off = write_round(base, "off", [case])
            on = write_round(base, "on", [make_case("P01", requests=[1, 2],
                                                    review_overall=5)])
            analysis = ab.build_analysis([off], [on], ["P01"])
            off_rec = {row["case"]: row for row in analysis["cases"]}["P01"]["off"]
            # drawAttempts 缺失时回退 metrics.draw_requests（旧求和口径）并标注
            self.assertEqual(off_rec["draw_requests"], 3)
            self.assertIn("metrics.draw_requests", off_rec["draw_requests_source"])
            self.assertIsNone(off_rec["contract"]["checks"])  # 契约记录缺失→未知
            ab.render_report(analysis)


if __name__ == "__main__":
    unittest.main()
