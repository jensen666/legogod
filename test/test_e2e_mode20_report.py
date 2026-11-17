# -*- coding: utf-8 -*-
"""tools/e2e_mode20_report.py 的双模式同题对比报告器测试（全部本地合成数据，不联网、不调 LLM）。

覆盖任务要求：
  1. 逐例并排：fast/fidelity 两臂全部字段进入 JSON 与 Markdown（含 job/run/尝试 run/
     需求哈希/模型名/状态/四态/交付来源/通用底线/需求断言/规模/耗时/请求/视觉/页面错误/证据路径）；
  2. 缺臂：如实标 missing、不崩溃、汇总计入缺失、报告完整性为 False；
  3. 快速未评审：视觉分固定 null（即使伪造 0 分记录也不得补 0），Markdown 显示“未评审”；
  4. draw 请求数：同运行内累计编号取最大值（[1,2,3]→3，不得求和）；空列表=0；跨尝试分别取
     最大值后相加并逐尝试留痕；无记录=null（不得用 0 冒充）；
  5. 耗时统计：自实现 P50/P90（偶数中位数取平均）+ 任务耗时汇总；
  6. 翻转表：交付 / 需求断言 / 交付状态翻转，两模式成功态名称不同不算翻转；
  7. 高保真双尝试分离：首次尝试结果（attempts_detail / 首次 run 记录）与含快速保底总编排结果
     分开报告，保底成功不得算作高保真成功；
  8. CLI 主流程：--json-only/--md-only/--out、参数互斥、目录不存在退出码、缺臂退出码 2。
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import e2e_mode20_report as report  # noqa: E402

MODEL = "test-model"
_UNSET = object()


# ---------------------------------------------------------------- 合成数据工具
def write_json(path, data):
    """写 UTF-8 JSON（自动建父目录）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def make_metrics(case, *, requirement_ok=True, tier_style="dict", ratio=0.7, target=100,
                 bricks=70, review_overall=None, gate_ok=True, validation_ok=True,
                 extra_errors=None):
    """构造断言器 metrics（dict 两档 C/H 风格或 list 一档 G/N 风格）。"""
    errors = list(extra_errors or [])
    if not requirement_ok:
        errors.append("部位清单缺少核心部位")
    if not gate_ok:
        errors.append("最终门禁重放未通过（受影响部位 1，错误格 2）")
    if not validation_ok:
        errors.append("统一校验未通过：['误差过大']")
    metrics = {
        "case": case, "suite": "M", "task_ok": True, "parts": 10, "solid_parts": 6,
        "voxels": 500, "ops": 12, "pieces": bricks, "bricks": bricks,
        "target_blocks": target, "bricks_ratio": ratio,
        "review_overall": review_overall, "review_flag": None,
        "final_gate_ok": gate_ok, "final_gate_source": "replay",
        "validation_ok": validation_ok,
        "assertion_ok": not errors, "assertion_errors": list(errors),
        "run_id": "r1",
    }
    if tier_style == "list":
        metrics["requirement_tier"] = [] if requirement_ok else ["部位清单缺少核心部位"]
        metrics["generic_tier"] = [e for e in errors
                                   if e.startswith(("最终门禁", "统一校验", "运行未成功"))]
    else:
        metrics["requirement_tier"] = {
            "target_blocks": target, "bricks": bricks, "bricks_ratio": ratio,
            "target_blocks_ok": ratio >= report.TARGET_RATIO_MIN,
            "require_parts": {"ok": requirement_ok,
                              "errors": [] if requirement_ok else ["部位清单缺少核心部位"]},
            "feature_checks": [{"name": "两层体量", "ok": requirement_ok,
                                "errors": [] if requirement_ok else ["特征未成型"]}],
            "complexity": {"parts": {"required": 5, "actual": 10, "ok": True}},
            "ok": not errors,
            "errors": list(errors),
        }
    return metrics


def make_run_record(run_id="r1", mode="fidelity", ok=True, review_overall=None,
                    draw_requests=(1,), timeline=None, elapsed=120.0, artifacts=True,
                    review_flag=None):
    """构造 run 记录（drawAttempts[].request 为累计编号，语义同生产记录）。"""
    record = {
        "runId": run_id, "mode": mode, "ok": ok, "revision": 1,
        "drawAttempts": [{"attempt": index + 1, "request": value, "elapsedS": 3.0}
                         for index, value in enumerate(draw_requests)],
        "timeline": timeline if timeline is not None else [
            {"phase": "init", "ended": 0.0},
            {"phase": "plan", "started": 0.0}, {"phase": "plan", "ended": 10.0},
            {"phase": "draw", "started": 10.0}, {"phase": "draw", "ended": 30.0},
            {"phase": "solve", "started": 30.0},
        ],
        "review": {"scores": {"overall": review_overall}} if review_overall is not None else {},
        "reviewFlag": review_flag,
        "artifacts": ({"model_r001": f"model_{run_id}.json",
                       "solution_r001": f"solution_{run_id}.json",
                       "md_r001": f"steps_{run_id}.md"} if artifacts else {}),
        "elapsedS": elapsed,
    }
    return record


def make_arm(case, mode, *, task_ok=True, outcome=None, metrics=None, run_record=None,
             attempts=None, elapsed_final=150.0, desc=None, desc_hash=None, job_id=None,
             run_id="r1", page_errors=None, screenshots=None, env=None, status=None,
             assert_ok=None, result_extra=None, review_overall=_UNSET):
    """构造一臂单例 JSON（结构同 tools/e2e_browser_20.finalize_case 落盘）。"""
    desc = desc or f"{case} 测试需求：目标约 100 块积木"
    if outcome is None:
        outcome = (("fast_success" if mode == "fast" else "fidelity_success")
                   if task_ok else "failed")
    if review_overall is _UNSET:
        review_overall = (8 if task_ok and mode == "fidelity"
                          and outcome != "fast_fallback" else None)
    result = {"ok": task_ok, "run_id": run_id, "mode": mode, "elapsed_s": 118.5,
              "pieces": 70, "voxels": 500}
    if review_overall is not None:
        result["review"] = {"scores": {"overall": review_overall}}
    if attempts is not None:
        result["attempts_detail"] = attempts
    if result_extra:
        result.update(result_extra)
    if metrics is None and task_ok:
        metrics = make_metrics(case)
    if assert_ok is None:
        assert_ok = bool(task_ok and metrics and metrics.get("assertion_ok"))
    if run_record is None:
        run_record = make_run_record(run_id=run_id, mode=mode, ok=task_ok,
                                     review_overall=review_overall)
    return {
        "case": case, "name": f"{case} 名称", "desc": desc,
        "descHash": desc_hash or hashlib.sha256(desc.encode("utf-8")).hexdigest(),
        "job_id": job_id or f"job-{case}-{mode}",
        "runId": run_id, "status": status or ("done" if task_ok else "error"),
        "outcome": outcome, "taskOk": task_ok, "assertOk": assert_ok,
        "elapsedFinal": elapsed_final,
        "result": result,
        "assertion": {"skipped": None if metrics else "任务未成功（无最终产物）",
                      "metrics": metrics},
        "runRecord": run_record,
        "pageErrors": page_errors if page_errors is not None
        else {"errors": [], "rejections": []},
        "console_errors": [],
        "screenshots": screenshots if screenshots is not None
        else [f"{case}/{mode}/01-workbench-result.png"],
        "env": env if env is not None else {"modelName": None, "modelConfigured": MODEL},
    }


class ReportTestBase(unittest.TestCase):
    """临时轮次目录 + 合成单例构造工具。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="mode20-report-test-")
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.round_dir = os.path.join(self.tmpdir, "round")

    def write_round(self, arms, environment=None):
        """arms: {(case, mode): record}；environment: dict 或 None（不写 environment.json）。"""
        for (case, mode), record in arms.items():
            write_json(os.path.join(self.round_dir, case, mode, f"{case}.json"), record)
        if environment is not None:
            write_json(os.path.join(self.round_dir, "environment.json"), environment)
        return self.round_dir

    def full_round(self, cases=("M01", "M02"), **arm_overrides):
        """构造完整双臂轮次（默认两模式都成功、断言通过）。"""
        arms = {}
        for case in cases:
            for mode in ("fast", "fidelity"):
                arms[(case, mode)] = make_arm(case, mode, **arm_overrides)
        return self.write_round(arms, environment={
            "label": "test-round", "modelConfigured": MODEL, "cases": ",".join(cases),
            "codeHead": "0123456789abcdef", "concurrency": 3, "timeoutS": 2100,
        })

    def read_json(self, name="mode20-comparison.json"):
        with open(os.path.join(self.round_dir, name), encoding="utf-8") as handle:
            return json.load(handle)

    def read_md(self):
        with open(os.path.join(self.round_dir, "mode20-comparison.md"), encoding="utf-8") as handle:
            return handle.read()


class TestPairedRows(ReportTestBase):
    """逐例并排与全部字段。"""

    def test_paired_arms_contain_all_required_fields(self):
        self.full_round(cases=("M01",))
        code = report.main(["--round", self.round_dir])
        self.assertEqual(code, 0)
        data = self.read_json()
        self.assertEqual(data["totalCases"], 1)
        self.assertEqual(data["pairedCases"], 1)
        self.assertTrue(data["complete"])
        case = data["cases"][0]
        self.assertEqual(case["case"], "M01")
        fast = case["arms"]["fast"]
        fidelity = case["arms"]["fidelity"]
        # 标识与状态（前半）
        self.assertEqual(fast["jobId"], "job-M01-fast")
        self.assertEqual(fidelity["jobId"], "job-M01-fidelity")
        self.assertEqual(fast["runId"], "r1")
        self.assertEqual(fast["attemptRunIds"], ["r1"])  # 单次尝试：唯一尝试即最终 run
        self.assertEqual(len(fast["descHash"]), 64)
        self.assertEqual(fast["descHash"], fidelity["descHash"])
        self.assertEqual(fast["modelName"], MODEL)
        self.assertEqual(fast["status"], "done")
        self.assertEqual(fast["outcome"], "fast_success")
        self.assertEqual(fidelity["outcome"], "fidelity_success")
        self.assertEqual(fast["deliverySource"], "fast")
        self.assertEqual(fidelity["deliverySource"], "fidelity")
        # 通用底线 / 需求断言 / 失败项
        self.assertIs(fast["generic"]["ok"], True)
        self.assertIs(fidelity["generic"]["ok"], True)
        self.assertIs(fast["requirementAssert"]["ok"], True)
        self.assertEqual(fast["requirementAssert"]["failures"], [])
        # 规模（中段）
        for arm in (fast, fidelity):
            self.assertEqual(arm["scale"]["targetBlocks"], 100)
            self.assertEqual(arm["scale"]["actualParts"], 70)
            self.assertAlmostEqual(arm["scale"]["bricksRatio"], 0.7)
            self.assertIs(arm["scale"]["targetOk"], True)
            self.assertEqual(arm["scale"]["voxels"], 500)
            self.assertEqual(arm["scale"]["parts"], 10)
            self.assertEqual(arm["scale"]["ops"], 12)
        # 耗时 / 请求 / 视觉（后半）
        self.assertEqual(fast["timings"]["totalS"], 150.0)
        self.assertEqual(fidelity["timings"]["reviewS"], 0.0)
        self.assertEqual(fast["requests"]["draw"]["total"], 1)
        self.assertEqual(fidelity["visualReview"]["status"], "scored")
        self.assertEqual(fidelity["visualReview"]["score"], 8)
        self.assertEqual(fast["visualReview"]["status"], "not_reviewed")
        self.assertIsNone(fast["visualReview"]["score"])
        # 页面错误 / 截图 / 产物
        self.assertEqual(fast["pageErrors"]["errorCount"], 0)
        self.assertEqual(fast["pageErrors"]["rejectionCount"], 0)
        self.assertEqual(len(fast["paths"]["screenshots"]), 1)
        self.assertEqual(len(fidelity["paths"]["artifacts"]), 3)
        # Markdown 逐例并排（两模式相邻）与全部小节
        md = self.read_md()
        for marker in ("二、逐例并排", "2.1 标识与状态", "2.2 断言与规模", "2.3 耗时与请求",
                       "2.4 页面错误与证据", "2.5 高保真首次尝试", "2.6 同案例结果翻转表"):
            self.assertIn(marker, md)
        self.assertIn("| M01 | fast |", md)
        self.assertIn("| M01 | fidelity |", md)
        self.assertIn("未评审", md)
        self.assertIn("高保真首次尝试结果（不含快速保底）", md)
        self.assertIn("高保真含快速保底的总编排结果", md)

    def test_case_discovery_not_hardcoded_20(self):
        self.full_round(cases=("M01", "M07", "M20"))
        code = report.main(["--round", self.round_dir])
        self.assertEqual(code, 0)
        data = self.read_json()
        self.assertEqual(data["totalCases"], 3)
        self.assertEqual([c["case"] for c in data["cases"]], ["M01", "M07", "M20"])

    def test_environment_optional_and_model_name_fallback(self):
        arms = {}
        for mode in ("fast", "fidelity"):
            arms[("M01", mode)] = make_arm(
                "M01", mode, env={"modelName": None, "modelConfigured": "arm-model"})
        self.write_round(arms)  # 不写 environment.json
        code = report.main(["--round", self.round_dir])
        self.assertEqual(code, 0)
        data = self.read_json()
        self.assertIsNone(data["environment"])
        self.assertEqual(data["cases"][0]["arms"]["fast"]["modelName"], "arm-model")


class TestMissingArm(ReportTestBase):
    """缺臂/缺例必须如实标 missing 且不崩溃。"""

    def test_missing_arm_marked_and_incomplete(self):
        arms = {("M01", "fast"): make_arm("M01", "fast")}  # 只有快速臂
        self.write_round(arms, environment={"cases": "M01-M02", "modelConfigured": MODEL})
        # M02 整例缺失（environment.cases 声明）
        data = report.build_report(self.round_dir)
        self.assertFalse(data["complete"])
        missing = {(item["case"], item["mode"]) for item in data["missing"]}
        self.assertIn(("M01", "fidelity"), missing)
        self.assertIn(("M02", "fast"), missing)
        self.assertIn(("M02", "fidelity"), missing)
        fidelity_arm = data["cases"][0]["arms"]["fidelity"]
        self.assertFalse(fidelity_arm["recorded"])
        self.assertTrue(fidelity_arm["missingReason"])
        self.assertIn("缺少", fidelity_arm["missingReason"])
        # 汇总不把缺失当 0 交付，但也不崩溃、不伪造指标
        self.assertEqual(data["summary"]["fidelity"]["recorded"], 0)
        self.assertEqual(data["summary"]["fidelity"]["missing"], 2)
        self.assertEqual(data["summary"]["fast"]["recorded"], 1)
        # Markdown 如实标注
        report.write_outputs(self.round_dir, data)
        md = self.read_md()
        self.assertIn("缺失", md)
        self.assertIn("报告完整：否", md)

    def test_empty_round_does_not_crash(self):
        os.makedirs(self.round_dir, exist_ok=True)
        data = report.build_report(self.round_dir)
        self.assertFalse(data["complete"])
        self.assertEqual(data["totalCases"], 0)
        self.assertTrue(any("未发现" in note for note in data["notes"]))

    def test_main_returns_2_for_incomplete_round(self):
        self.write_round({("M01", "fast"): make_arm("M01", "fast")})
        code = report.main(["--round", self.round_dir])
        self.assertEqual(code, 2)
        self.assertTrue(os.path.isfile(os.path.join(self.round_dir,
                                                    "mode20-comparison.json")))


class TestFastNotReviewed(ReportTestBase):
    """快速模式视觉评审必须 null 并标注未评审，不得补 0。"""

    def test_fast_visual_score_never_zero_filled(self):
        arms = {
            ("M01", "fast"): make_arm(
                "M01", "fast",
                metrics=make_metrics("M01", review_overall=0),
                run_record=make_run_record(mode="fast", review_overall=0)),
            ("M01", "fidelity"): make_arm("M01", "fidelity"),
        }
        self.write_round(arms, environment={"modelConfigured": MODEL})
        data = report.build_report(self.round_dir)
        fast = data["cases"][0]["arms"]["fast"]
        self.assertEqual(fast["visualReview"]["status"], "not_reviewed")
        self.assertIsNone(fast["visualReview"]["score"])
        self.assertIn("未评审", fast["visualReview"]["note"])
        self.assertEqual(fast["visualReview"]["unexpectedObservedScore"], 0)
        self.assertEqual(data["summary"]["fast"]["visual"]["scored"], 0)
        self.assertEqual(data["summary"]["fast"]["visual"]["notReviewed"], 1)
        report.write_outputs(self.round_dir, data)
        self.assertIn("未评审（null，不补 0）", self.read_md())

    def test_delivered_fidelity_without_reviewable_score_is_null_with_reason(self):
        metrics = make_metrics("M01", review_overall=None)
        arms = {
            ("M01", "fast"): make_arm("M01", "fast"),
            ("M01", "fidelity"): make_arm(
                "M01", "fidelity", metrics=metrics, review_overall=None,
                run_record=make_run_record(review_overall=None, review_flag="review_unavailable"),
                result_extra={"review_flag": "review_unavailable"}),
        }
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        visual = data["cases"][0]["arms"]["fidelity"]["visualReview"]
        self.assertIsNone(visual["score"])
        self.assertEqual(visual["status"], "unavailable")
        self.assertIn("评审不可用", visual["note"])


class TestDrawRequests(ReportTestBase):
    """draw 请求数：累计编号取最大值，禁止求和；空列表=0；无记录=null。"""

    def test_cumulative_request_number_uses_max_not_sum(self):
        arms = {}
        for case, requests in (("M01", (1, 2, 3)), ("M02", ())):
            arms[(case, "fast")] = make_arm(
                case, "fast", run_record=make_run_record(mode="fast",
                                                         draw_requests=requests))
        self.write_round(arms, environment={"cases": "M01-M02"})
        data = report.build_report(self.round_dir)
        by_case = {c["case"]: c for c in data["cases"]}
        self.assertEqual(by_case["M01"]["arms"]["fast"]["requests"]["draw"]["total"], 3)
        self.assertEqual(by_case["M02"]["arms"]["fast"]["requests"]["draw"]["total"], 0)
        self.assertIn("最大值", by_case["M01"]["arms"]["fast"]["requests"]["draw"]["byAttempt"][0]
                      ["source"])

    def test_cross_attempt_counts_max_per_run_then_add(self):
        """跨尝试：首次高保真 draw [1,2] 与快速保底 draw [1,2] 各取最大值后相加 = 4。"""
        attempts = [
            {"mode": "fidelity", "ok": False, "run_id": "f1", "elapsed_s": 300.0,
             "failure": {"kind": "gate", "stage": "draw_draft"}},
            {"mode": "fast", "ok": True, "run_id": "f2", "elapsed_s": 60.0, "status": "done"},
        ]
        fidelity = make_arm(
            "M03", "fidelity", outcome="fast_fallback", task_ok=True, run_id="f2",
            attempts=attempts, elapsed_final=400.0,
            run_record=make_run_record(run_id="f2", mode="fast", draw_requests=(1, 2),
                                       elapsed=60.0))
        # 首次尝试 run 记录放在臂目录 evidence 下，报告按 run_id 读取
        write_json(os.path.join(self.round_dir, "M03", "fidelity", "evidence", "run_f1.json"),
                   make_run_record(run_id="f1", mode="fidelity", ok=False,
                                   draw_requests=(1, 2), elapsed=300.0))
        self.write_round({("M03", "fast"): make_arm("M03", "fast"), ("M03", "fidelity"): fidelity})
        data = report.build_report(self.round_dir)
        draw = data["cases"][0]["arms"]["fidelity"]["requests"]["draw"]
        self.assertEqual(draw["total"], 4)
        self.assertEqual([item["count"] for item in draw["byAttempt"]], [2, 2])
        self.assertEqual([item["mode"] for item in draw["byAttempt"]], ["fidelity", "fast"])

    def test_unknown_draw_requests_is_null_not_zero(self):
        fidelity = make_arm(
            "M04", "fidelity", outcome="fast_fallback", task_ok=True, run_id="f2",
            attempts=[{"mode": "fidelity", "ok": False, "run_id": "f1", "elapsed_s": 10.0},
                      {"mode": "fast", "ok": True, "run_id": "f2", "elapsed_s": 5.0}],
            run_record=make_run_record(run_id="f2", mode="fast", draw_requests=(1, 1)),
            elapsed_final=30.0)
        # 首次尝试无 run 记录且指标缺失 → 总数未知，不得写 0
        fidelity["assertion"]["metrics"] = None
        fidelity["assertOk"] = False
        self.write_round({("M04", "fidelity"): fidelity})
        data = report.build_report(self.round_dir)
        draw = data["cases"][0]["arms"]["fidelity"]["requests"]["draw"]
        self.assertIsNone(draw["total"])
        self.assertEqual(draw["byAttempt"][0]["count"], None)

    def test_metrics_fallback_not_attributed_to_first_attempt(self):
        """保底双尝试：断言 metrics 只描述最终交付尝试，不得按到首次高保真尝试上。"""
        old_final = make_run_record(run_id="f2", mode="fast")
        old_final.pop("drawAttempts")  # 最终尝试记录缺 drawAttempts → 只能回退 metrics
        fidelity = make_arm(
            "M06", "fidelity", outcome="fast_fallback", task_ok=True, run_id="f2",
            attempts=[{"mode": "fidelity", "ok": False, "run_id": "f1", "elapsed_s": 10.0},
                      {"mode": "fast", "ok": True, "run_id": "f2", "elapsed_s": 5.0}],
            run_record=old_final, elapsed_final=30.0)
        fidelity["assertion"]["metrics"]["draw_requests"] = 4
        self.write_round({("M06", "fidelity"): fidelity})
        data = report.build_report(self.round_dir)
        draw = data["cases"][0]["arms"]["fidelity"]["requests"]["draw"]
        self.assertIsNone(draw["total"])  # 首次尝试计数未知 → 总数不得伪造
        self.assertIsNone(draw["byAttempt"][0]["count"])
        self.assertEqual(draw["byAttempt"][1]["count"], 4)
        self.assertIn("metrics.draw_requests", draw["byAttempt"][1]["source"])

    def test_metrics_draw_requests_fallback_when_old_run_record(self):
        old_record = make_run_record(mode="fast")
        old_record.pop("drawAttempts")  # 旧记录没有 drawAttempts 字段
        arms = {("M05", "fast"): make_arm(
            "M05", "fast", run_record=old_record,
            metrics=make_metrics("M05", review_overall=None))}
        arms[("M05", "fast")]["assertion"]["metrics"]["draw_requests"] = 4
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        draw = data["cases"][0]["arms"]["fast"]["requests"]["draw"]
        self.assertEqual(draw["total"], 4)
        self.assertIn("metrics.draw_requests", draw["byAttempt"][0]["source"])


class TestQuantiles(ReportTestBase):
    """自实现 P50/P90：偶数中位数取平均，忽略布尔/非数值。"""

    def test_percentile_basics(self):
        self.assertIsNone(report.percentile([], 0.5))
        self.assertEqual(report.percentile([100], 0.5), 100)
        self.assertEqual(report.percentile([100, 200, 300], 0.5), 200)
        self.assertEqual(report.percentile([100, 200, 300, 400], 0.5), 250)
        self.assertEqual(report.percentile([10, 20, 30, 40, 50], 0.9), 46)
        self.assertEqual(report.percentile([True, "x", None, 10, 30], 0.5), 20)
        self.assertIsNone(report.percentile([True, False], 0.9))

    def test_summary_elapsed_p50_p90(self):
        arms = {}
        for case, fast_elapsed, fid_elapsed in (("M01", 10, 100), ("M02", 20, 200)):
            arms[(case, "fast")] = make_arm(case, "fast", elapsed_final=fast_elapsed)
            arms[(case, "fidelity")] = make_arm(case, "fidelity", elapsed_final=fid_elapsed)
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        fast = data["summary"]["fast"]["elapsed"]
        fidelity = data["summary"]["fidelity"]["elapsed"]
        self.assertEqual((fast["n"], fast["p50"], fast["p90"]), (2, 15.0, 19.0))
        self.assertEqual((fidelity["n"], fidelity["p50"], fidelity["p90"]), (2, 150.0, 190.0))
        pairs = data["summary"]["pairs"]
        self.assertEqual(pairs["count"], 2)
        self.assertEqual(pairs["fastFaster"], 2)
        self.assertEqual(pairs["medianDeltaFastMinusFidelity"], -135.0)


class TestFlipTable(ReportTestBase):
    """同案例结果翻转表。"""

    def test_delivery_and_requirement_flips(self):
        arms = {
            # M01：快速交付、高保真失败 → 交付翻转
            ("M01", "fast"): make_arm("M01", "fast"),
            ("M01", "fidelity"): make_arm("M01", "fidelity", task_ok=False, outcome="failed",
                                          metrics=None, run_record=make_run_record(
                                              mode="fidelity", ok=False)),
            # M02：两模式都交付，但快速需求断言未通过 → 需求断言翻转
            ("M02", "fast"): make_arm("M02", "fast", metrics=make_metrics(
                "M02", requirement_ok=False, gate_ok=False)),
            ("M02", "fidelity"): make_arm("M02", "fidelity"),
            # M03：两模式完全一致 → 无翻转（成功态名称不同不算）
            ("M03", "fast"): make_arm("M03", "fast"),
            ("M03", "fidelity"): make_arm("M03", "fidelity"),
        }
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        flips = data["summary"]["flips"]
        self.assertEqual(flips["count"], 2)
        self.assertEqual(flips["byDimension"], {"delivery": 1, "requirement": 1})
        self.assertEqual(flips["fastOnlyDelivery"], ["M01"])
        self.assertEqual(flips["fidelityOnlyDelivery"], [])
        requirement_rows = [row for row in flips["rows"] if row["dimension"] == "requirement"]
        self.assertEqual(requirement_rows[0]["case"], "M02")
        self.assertEqual(requirement_rows[0]["fidelity"], True)
        self.assertEqual(requirement_rows[0]["fast"], False)
        report.write_outputs(self.round_dir, data)
        md = self.read_md()
        self.assertIn("仅快速交付", md)
        self.assertIn("仅高保真需求断言通过", md)

    def test_success_outcome_names_are_not_flips(self):
        self.full_round(cases=("M01",))
        data = report.build_report(self.round_dir)
        self.assertEqual(data["summary"]["flips"]["count"], 0)


class TestDoubleAttemptSeparation(ReportTestBase):
    """高保真首次尝试结果与含快速保底总编排结果必须分开。"""

    def _fallback_arm(self, with_first_record=False):
        attempts = [
            {"mode": "fidelity", "ok": False, "run_id": "f1", "elapsed_s": 300.0,
             "error": "生成失败", "failure": {"kind": "gate", "stage": "draw_draft"},
             "review_flag": None},
            {"mode": "fast", "ok": True, "run_id": "f2", "elapsed_s": 60.0, "status": "done"},
        ]
        arm = make_arm(
            "M04", "fidelity", outcome="fast_fallback", task_ok=True, run_id="f2",
            attempts=attempts, elapsed_final=400.0,
            metrics=make_metrics("M04", review_overall=None),
            run_record=make_run_record(run_id="f2", mode="fast", draw_requests=(1, 2),
                                       elapsed=60.0),
            result_extra={"attempts_detail": attempts})
        if with_first_record:
            write_json(os.path.join(self.round_dir, "M04", "fidelity", "evidence", "run_f1.json"),
                       make_run_record(
                           run_id="f1", mode="fidelity", ok=False, review_overall=5,
                           draw_requests=(1, 2), elapsed=300.0,
                           timeline=[{"phase": "init", "ended": 0.0},
                                     {"phase": "plan", "started": 0.0},
                                     {"phase": "plan", "ended": 10.0},
                                     {"phase": "draw", "started": 10.0},
                                     {"phase": "draw", "ended": 40.0},
                                     {"phase": "review", "started": 40.0},
                                     {"phase": "review", "ended": 70.0},
                                     {"phase": "revise", "started": 70.0},
                                     {"phase": "revise", "ended": 100.0},
                                     {"phase": "solve", "started": 100.0}]))
        return arm

    def test_first_attempt_before_fallback_separated(self):
        self.write_round({("M04", "fast"): make_arm("M04", "fast"),
                          ("M04", "fidelity"): self._fallback_arm()})
        data = report.build_report(self.round_dir)
        fidelity = data["cases"][0]["arms"]["fidelity"]
        first = fidelity["firstAttempt"]
        self.assertTrue(first["available"])
        self.assertIs(first["ok"], False)
        self.assertEqual(first["outcome"], "failed")
        self.assertEqual(first["runId"], "f1")
        self.assertEqual(first["failureKind"], "gate")
        self.assertEqual(first["elapsedS"], 300.0)
        # 总编排结果：交付成功但来源是快速保底，不是高保真成功
        self.assertIs(fidelity["taskOk"], True)
        self.assertEqual(fidelity["outcome"], "fast_fallback")
        self.assertEqual(fidelity["deliverySource"], "fast_fallback")
        self.assertIn("快速保底", fidelity["deliveryLabel"])
        timings = fidelity["timings"]
        self.assertEqual(timings["totalS"], 400.0)
        self.assertEqual(timings["firstAttemptS"], 300.0)
        self.assertEqual(timings["fallbackS"], 60.0)
        self.assertIsNone(timings["reviewS"])
        self.assertEqual(fidelity["visualReview"]["status"], "not_delivered")
        self.assertIsNone(fidelity["visualReview"]["score"])
        self.assertIn("硬失败", fidelity["visualReview"]["note"])
        orchestration = fidelity["orchestration"]
        self.assertEqual(orchestration["attemptCount"], 2)
        self.assertTrue(orchestration["fallbackUsed"])
        self.assertEqual(orchestration["fallbackRunIds"], ["f2"])
        # 汇总分离：首次尝试 0 交付 / 1 失败；总编排 1 交付 / 保底 1 例
        first_summary = data["summary"]["fidelityFirstAttempt"]
        self.assertEqual(first_summary["evaluated"], 1)
        self.assertEqual(first_summary["delivered"], 0)
        self.assertEqual(first_summary["failed"], 1)
        self.assertEqual(first_summary["outcomes"], {"failed": 1})
        self.assertEqual(first_summary["fallbackTriggered"], 1)
        fidelity_summary = data["summary"]["fidelity"]
        self.assertEqual(fidelity_summary["delivered"], 1)
        self.assertEqual(fidelity_summary["fallbackUsedIds"], ["M04"])
        self.assertEqual(fidelity_summary["deliverySourceBreakdown"]["fast_fallback"], 1)
        self.assertEqual(fidelity_summary["deliverySourceBreakdown"]["fidelity"], 0)
        report.write_outputs(self.round_dir, data)
        md = self.read_md()
        self.assertIn("首次尝试失败/取消 1 例", md)
        self.assertIn("快速保底 1 例", md)

    def test_fallback_triggered_but_failed_not_counted_as_success(self):
        """触发保底但两次尝试都失败：不得算“快速保底成功”。"""
        attempts = [{"mode": "fidelity", "ok": False, "run_id": "f1", "elapsed_s": 10.0},
                    {"mode": "fast", "ok": False, "run_id": "f2", "elapsed_s": 5.0}]
        arm = make_arm("M05", "fidelity", task_ok=False, outcome="failed", metrics=None,
                       run_id="f2", attempts=attempts, elapsed_final=30.0,
                       run_record=make_run_record(run_id="f2", mode="fast", ok=False))
        self.write_round({("M05", "fidelity"): arm})
        data = report.build_report(self.round_dir)
        fidelity = data["summary"]["fidelity"]
        self.assertEqual(fidelity["fallbackTriggered"], 1)
        self.assertEqual(fidelity["fallbackUsedIds"], ["M05"])
        self.assertEqual(fidelity["fallbackSuccess"], 0)
        self.assertEqual(fidelity["fallbackSuccessIds"], [])
        self.assertEqual(fidelity["doubleAttemptFailedIds"], ["M05"])
        self.assertEqual(fidelity["deliverySourceBreakdown"]["fast_fallback"], 0)

    def test_first_attempt_inferred_from_arm_result_when_record_minimal(self):
        """最小记录（仅有 taskOk/outcome/assertion.metrics）也要能判定首次尝试成功。"""
        arm = make_arm("M11", "fidelity")
        arm["result"] = {}
        arm["runRecord"] = None
        arm["runId"] = None
        arm["outcome"] = "fidelity_success"
        self.write_round({("M11", "fidelity"): arm})
        data = report.build_report(self.round_dir)
        first = data["cases"][0]["arms"]["fidelity"]["firstAttempt"]
        self.assertTrue(first["available"])
        self.assertIs(first["ok"], True)
        self.assertEqual(first["outcome"], "fidelity_success")
        self.assertEqual(data["summary"]["fidelityFirstAttempt"]["delivered"], 1)

    def test_first_attempt_evidence_used_when_present(self):
        self.write_round({("M04", "fast"): make_arm("M04", "fast"),
                          ("M04", "fidelity"): self._fallback_arm(with_first_record=True)})
        data = report.build_report(self.round_dir)
        fidelity = data["cases"][0]["arms"]["fidelity"]
        # 首次尝试 run 记录可核对：评审/修订耗时、评审轮次、首次视觉分都来自该记录
        self.assertEqual(fidelity["timings"]["reviewS"], 30.0)
        self.assertEqual(fidelity["timings"]["reviseS"], 30.0)
        self.assertEqual(fidelity["timings"]["reviewRounds"], 1)
        self.assertEqual(fidelity["visualReview"]["status"], "scored")
        self.assertEqual(fidelity["visualReview"]["score"], 5)
        self.assertIn("首次尝试", fidelity["visualReview"]["source"])
        self.assertEqual(fidelity["requests"]["draw"]["total"], 4)


class TestRequirementAndGeneric(ReportTestBase):
    """通用底线与需求断言结论分开提取，失败项如实保留。"""

    def test_generic_and_requirement_failures_reported_separately(self):
        metrics = make_metrics("M01", requirement_ok=False, gate_ok=True)
        arms = {
            ("M01", "fast"): make_arm("M01", "fast", metrics=metrics),
            ("M01", "fidelity"): make_arm("M01", "fidelity"),
        }
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        fast = data["cases"][0]["arms"]["fast"]
        self.assertIs(fast["generic"]["ok"], True)  # 通用底线不受需求特征失败影响
        self.assertIs(fast["requirementAssert"]["ok"], False)
        self.assertTrue(any("部位" in item for item in fast["requirementAssert"]["failures"]))
        self.assertIs(fast["taskOk"], True)
        # 整体断言不通过（assertOk=False）但任务成功，两类结论不混同
        self.assertIs(fast["assertOk"], False)

    def test_list_style_metrics_generic_tier(self):
        metrics = make_metrics("M02", tier_style="list", gate_ok=False)
        arms = {
            ("M02", "fast"): make_arm("M02", "fast", metrics=metrics),
            ("M02", "fidelity"): make_arm("M02", "fidelity"),
        }
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        fast = data["cases"][0]["arms"]["fast"]
        self.assertIs(fast["requirementAssert"]["ok"], True)  # 需求层无失败项
        self.assertIs(fast["generic"]["ok"], False)  # 通用底线失败单独报告
        self.assertIs(fast["requirementAssert"]["evaluated"], True)

    def test_timeline_unclosed_revise_gives_null_duration(self):
        timeline = [{"phase": "init", "ended": 0.0},
                    {"phase": "plan", "started": 0.0}, {"phase": "plan", "ended": 10.0},
                    {"phase": "review", "started": 10.0}, {"phase": "review", "ended": 20.0},
                    {"phase": "revise", "started": 20.0}]
        arms = {
            ("M01", "fast"): make_arm("M01", "fast"),
            ("M01", "fidelity"): make_arm(
                "M01", "fidelity", run_record=make_run_record(timeline=timeline)),
        }
        self.write_round(arms)
        data = report.build_report(self.round_dir)
        timings = data["cases"][0]["arms"]["fidelity"]["timings"]
        self.assertEqual(timings["reviewS"], 10.0)
        self.assertIsNone(timings["reviseS"])  # 未闭合不得用部分值或 0 冒充
        self.assertTrue(any("修订阶段未闭合" in note for note in timings["notes"]))


class TestRunnerFactsIntegration(ReportTestBase):
    """消费双模式运行器落盘的模式路由/模式事实证据（与 report 接口约定）。"""

    def test_runner_mode_facts_visible_and_counted(self):
        fast_rec = make_arm("M07", "fast")
        fast_rec.update({"arm": "fast", "runKey": "M07-fast",
                         "delivery": "fast", "attemptsCount": 1,
                         "modeCheck": {"expected": "fast", "seen": {}, "ok": True,
                                       "mismatches": []},
                         "modePolicy": {"ok": True, "errors": []}})
        fid_rec = make_arm("M07", "fidelity")
        fid_rec.update({
            "arm": "fidelity", "runKey": "M07-fidelity", "delivery": "fidelity",
            "attemptsCount": 2,
            "modeCheck": {"expected": "fidelity", "seen": {"api": "fast"}, "ok": False,
                          "mismatches": ["api='fast'"]},
            "modePolicy": {"ok": False, "errors": ["高保真自动保底尝试 2 次 > 1（最多一次）"]},
        })
        metrics = fid_rec["assertion"]["metrics"]
        metrics["mode_facts"] = {
            "ok": False, "errors": ["高保真自动保底尝试 2 次 > 1（最多一次）"],
            "mode": "fidelity", "outcome": "fidelity_success", "review_present": True,
            "review_flag": None, "revise_visual": 1, "fallback_count": 2,
            "attempts_detail_present": False, "attempts": [],
        }
        self.write_round({("M07", "fast"): fast_rec, ("M07", "fidelity"): fid_rec})
        data = report.build_report(self.round_dir)
        arm = data["cases"][0]["arms"]["fidelity"]
        self.assertEqual(arm["runnerFacts"]["arm"], "fidelity")
        self.assertEqual(arm["runnerFacts"]["delivery"], "fidelity")
        self.assertEqual(arm["runnerFacts"]["attemptsCount"], 2)
        self.assertIs(arm["modeFacts"]["ok"], False)
        self.assertEqual(arm["modeFacts"]["reviseVisual"], 1)
        self.assertEqual(arm["modeFacts"]["fallbackCount"], 2)
        summary = data["summary"]["fidelity"]
        self.assertEqual(summary["modeCheckFailedIds"], ["M07"])
        self.assertEqual(summary["modePolicyFailedIds"], ["M07"])
        self.assertEqual(summary["modeFactsFailedIds"], ["M07"])
        report.write_outputs(self.round_dir, data)
        md = self.read_md()
        self.assertIn("2.7 模式路由与模式事实", md)
        self.assertIn("未通过", md)

    def test_attempts_enriched_from_assertion_mode_facts(self):
        """result.attempts_detail 缺失时，用断言 metrics.mode_facts.attempts 还原双尝试。"""
        fid_rec = make_arm(
            "M08", "fidelity", outcome="fast_fallback", task_ok=True, run_id="fb",
            run_record=make_run_record(run_id="fb", mode="fast"), attempts=None)
        fid_rec.update({"arm": "fidelity", "delivery": "fast", "attemptsCount": 2})
        metrics = fid_rec["assertion"]["metrics"]
        metrics["mode_facts"] = {
            "ok": True, "errors": [], "mode": "fidelity", "outcome": "fast_fallback",
            "review_present": False, "review_flag": None, "revise_visual": 0,
            "fallback_count": 1, "attempts_detail_present": True,
            "attempts": [{"mode": "fidelity", "ok": False, "run_id": "fa",
                          "failure": {"kind": "gate", "stage": "draw_draft"}},
                         {"mode": "fast", "ok": True, "run_id": "fb"}],
        }
        self.write_round({("M08", "fidelity"): fid_rec})
        data = report.build_report(self.round_dir)
        arm = data["cases"][0]["arms"]["fidelity"]
        self.assertEqual(arm["attemptsSource"], "metrics.mode_facts.attempts")
        self.assertEqual(arm["attemptRunIds"], ["fa", "fb"])
        self.assertEqual(arm["orchestration"]["attemptCount"], 2)
        self.assertTrue(arm["orchestration"]["fallbackUsed"])
        self.assertEqual(arm["firstAttempt"]["runId"], "fa")
        self.assertEqual(arm["firstAttempt"]["outcome"], "failed")
        self.assertEqual(arm["firstAttempt"]["failureKind"], "gate")
        summary = data["summary"]["fidelityFirstAttempt"]
        self.assertEqual(summary["evaluated"], 1)
        self.assertEqual(summary["failedIds"], ["M08"])

    def test_desc_hash_and_frozen_desc_mismatch_reported(self):
        metrics = make_metrics("M09")
        metrics["desc_hash"] = "deadbeef"  # 与单例 descHash 不一致（跑中改题风险）
        metrics["desc_frozen"] = False
        arm = make_arm("M09", "fast", metrics=metrics)
        self.write_round({("M09", "fast"): arm})
        data = report.build_report(self.round_dir)
        record = data["cases"][0]["arms"]["fast"]
        self.assertIs(record["descHashConsistent"], False)
        self.assertIs(record["descFrozen"], False)
        self.assertEqual(data["summary"]["fast"]["descHashMismatchIds"], ["M09"])
        self.assertEqual(data["summary"]["fast"]["descFrozenFailedIds"], ["M09"])
        self.assertTrue(any("需求哈希" in note for note in record["notes"]))

    def test_fast_unexpected_review_present_disclosed_not_scored(self):
        metrics = make_metrics("M10", review_overall=None)
        metrics["mode_facts"] = {
            "ok": False, "errors": ["快速模式出现视觉评审结果：review 非空"],
            "mode": "fast", "outcome": "fast_success", "review_present": True,
            "review_flag": "review_failed", "revise_visual": 0, "fallback_count": 0,
            "attempts_detail_present": False, "attempts": [],
        }
        arm = make_arm("M10", "fast", metrics=metrics,
                       run_record=make_run_record(mode="fast"))
        self.write_round({("M10", "fast"): arm})
        data = report.build_report(self.round_dir)
        visual = data["cases"][0]["arms"]["fast"]["visualReview"]
        self.assertEqual(visual["status"], "not_reviewed")
        self.assertIsNone(visual["score"])
        self.assertTrue(visual.get("unexpectedReviewPresent"))
        self.assertIn("警告", visual["note"])


class TestCli(ReportTestBase):
    """CLI 主流程：默认双输出、--json-only/--md-only、--out、参数互斥、错误退出码。"""

    def test_default_writes_both_outputs(self):
        self.full_round(cases=("M01",))
        self.assertEqual(report.main(["--round", self.round_dir]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.round_dir,
                                                    "mode20-comparison.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.round_dir,
                                                    "mode20-comparison.md")))

    def test_json_only_and_md_only(self):
        self.full_round(cases=("M01",))
        self.assertEqual(report.main(["--round", self.round_dir, "--json-only"]), 0)
        self.assertTrue(os.path.isfile(os.path.join(self.round_dir,
                                                    "mode20-comparison.json")))
        self.assertFalse(os.path.isfile(os.path.join(self.round_dir,
                                                     "mode20-comparison.md")))
        out_dir = os.path.join(self.tmpdir, "out-md")
        self.assertEqual(report.main(["--round", self.round_dir, "--md-only",
                                      "--out", out_dir]), 0)
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "mode20-comparison.md")))
        self.assertFalse(os.path.isfile(os.path.join(out_dir, "mode20-comparison.json")))

    def test_out_directory(self):
        self.full_round(cases=("M01",))
        out_dir = os.path.join(self.tmpdir, "custom-out")
        self.assertEqual(report.main(["--round", self.round_dir, "--out", out_dir]), 0)
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "mode20-comparison.json")))
        with open(os.path.join(out_dir, "mode20-comparison.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertTrue(data["outDir"].endswith("custom-out"))

    def test_mutually_exclusive_flags_and_bad_round(self):
        self.full_round(cases=("M01",))
        with self.assertRaises(SystemExit) as raised:
            report.main(["--round", self.round_dir, "--json-only", "--md-only"])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(report.main(["--round", os.path.join(self.tmpdir, "nope")]), 2)


if __name__ == "__main__":
    unittest.main()
