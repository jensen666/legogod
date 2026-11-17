# -*- coding: utf-8 -*-
"""R 组（R01–R10）冻结新例 / 断言模块的确定性回归测试（不调用真实模型/浏览器/求解）。

覆盖：
  1. 案例注册纪律：10 例、编号 R01–R10、id/原文/主题唯一、字段完整、目标块数
     与需求原文逐字一致（含两种写法）、desc_sha256 与原文一致（冻结）、min_voxels
     口径 = 2×目标块数、target_blocks 180–440 且互不相同；
  2. 规模句写法：至少 2 例 desc 不含「约」但含「目标 N 块」，其余例含「目标约」；
     两种写法都能被 legogod.plan_scale.parse_target_blocks 解析；
  3. 断言配置：require_parts/checks 非空、所有检查名都能被 resolve_check 解析；
  4. 主题新颖性审计：公开审计语料 fixture + C/H/G/N 案例池 0 冲突；注入历史需求/
     主题词/案例池撞题必须报错；本组自己跑过的需求被排除（防自我撞题）；缺语料
     --audit 必须 exit 2（--allow-empty 仅本地显式放行）；
  5. draw_requests 语义：取 drawAttempts[].request 的最大值（[1,2,3]→3、[]→0、跳号
     [1,3]→3），不得求和；
  6. check_objects_r 两层断言：正例通过；目标块数比不达标、部位缺失两类失败；
     generic_tier 的评审过期/版本覆盖/最终门禁重放；review_fallback 补入生效。
"""
import contextlib
import hashlib
import io
import json
import os
import unittest
from unittest import mock

from legogod.plan_scale import parse_target_blocks as plan_parse_target_blocks
from tools.e2e_assert import _colored_cells
from tools.e2e_assert_20 import _part_counts
from tools.e2e_assert_g import _solid_cells
from tools.e2e_assert_new20 import resolve_check
from tools.e2e_assert_r import check_objects_r
from tools.e2e_cases_20 import all_cases as all_ch_cases
from tools.e2e_cases_g import G_CASES
from tools.e2e_cases_new20 import N_CASES
from tools.e2e_cases_r import (R_CASES, R_TARGET_TOLERANCE, all_r_cases, audit_r_cases,
                                find_r_case, parse_target_blocks, _desc_sha256,
                                _is_no_yue_case, _verify_frozen_cases)
from tools.e2e_cases_r import main as r_cases_main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需求原文里必须至少出现两类结构特征（与 N 组测试同口径）
STRUCTURE_MARKERS = ("中空", "斜面", "悬挑", "成对", "多层", "收分", "递收", "曲面", "弧",
                     "扇形", "卷", "螺旋", "镂空", "贯通", "张开", "展开", "鼓起", "圆鼓",
                     "倾斜", "分节", "斜撑", "平展", "错落", "垂下", "悬挂", "弯垂", "条纹")
FORBIDDEN_DESC_WORDS = ("透明", "水印", "文字", "标签", "logo", "Logo", "二维码")

EXPECTED_IDS = [f"R{i:02d}" for i in range(1, 11)]
EXPECTED_TARGETS = {
    "R01": 320, "R02": 280, "R03": 260, "R04": 240, "R05": 360,
    "R06": 220, "R07": 400, "R08": 200, "R09": 180, "R10": 300,
}
# 方案要求至少 2 例使用不带「约」的「目标 N 块」写法
NO_YUE_IDS = {"R09", "R10"}


# ---------------------------------------------------------------- 合成模型工具
def cells_to_boxes(cells):
    """把 3D 格集合按 (y,z) 的 x 连续段合成 boxes，保几何精确且可从 boxes 还原。"""
    groups = {}
    for (x, y, z) in cells:
        groups.setdefault((y, z), []).append(x)
    boxes = []
    for (y, z), xs in groups.items():
        xs.sort()
        run_start = prev = xs[0]
        for v in xs[1:]:
            if v == prev + 1:
                prev = v
                continue
            boxes.append({"x1": run_start, "x2": prev, "z1": z, "z2": z, "y1": y, "y2": y})
            run_start = prev = v
        boxes.append({"x1": run_start, "x2": prev, "z1": z, "z2": z, "y1": y, "y2": y})
    return boxes


def make_part(pid, name, role="solid", cells=None, boxes=None):
    """由格子或 boxes 构造部位；voxels 与 boxes 几何一致。"""
    if boxes is None:
        boxes = cells_to_boxes(cells or [])
    n = set(cells or [])
    if not n and boxes:
        for b in boxes:
            for y in range(b["y1"], b["y2"] + 1):
                for x in range(b["x1"], b["x2"] + 1):
                    for z in range(b["z1"], b["z2"] + 1):
                        n.add((x, y, z))
    return {"id": pid, "name": name, "role": role, "voxels": len(n), "boxes": boxes}


def model_from_cells(cells, w, d, h=None, parts=None, default_color=None):
    """由 3D 实体格生成 model（layers/rows/cells/colorRows 全齐）。"""
    cells = set(cells)
    ys = sorted({c[1] for c in cells}) or [0]
    h = h or (max(ys) + 1)
    layers = []
    for y in range(h):
        plane = {(x, z) for (x, yy, z) in cells if yy == y}
        rows = ["".join("#" if (x, z) in plane else "." for x in range(w)) for z in range(d)]
        color_rows = None
        if default_color is not None:
            color_rows = ["".join(default_color if (x, z) in plane else "."
                                  for x in range(w)) for z in range(d)]
        layers.append({"y": y, "rows": rows,
                       "cells": [[x, z] for z in range(d) for x in range(w) if (x, z) in plane],
                       "module": ["m"], "color": None, "colorRows": color_rows,
                       "count": len(plane)})
    return {"name": "测试R", "grid": {"w": w, "d": d}, "totalVoxels": len(cells),
            "slopeVoxels": 0, "layers": layers, "parts": parts or [],
            "ops": [], "track": "ops"}


def _steps(n):
    return [{"piece": "B1x1", "x": 0, "z": 0, "layer": 0, "rotate": False, "step": i + 1}
            for i in range(n)]


def _fake_case(**over):
    case = {"id": "RXX", "name": "测试案例", "desc": "测试需求：目标约 10 块积木",
            "target_blocks": 10, "stress": ["scale"],
            "historical_failure_hint": "测试用历史失败提示",
            "min_parts": 1, "min_solid_parts": 1, "min_voxels": 1, "min_ops": 0,
            "require_parts": [], "checks": [["layers_min", 1]]}
    case.update(over)
    return case


def _fake_record(**over):
    record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {},
              "finalGateReplay": {"ok": True, "errors": []}}
    record.update(over)
    return record


def _fake_model(part_name="身体"):
    cells = {(0, 0, 0), (1, 0, 0)}
    return model_from_cells(cells, 2, 1, 1,
                            [make_part("body", part_name, cells=cells)],
                            default_color="L")


def _fake_solution(n_steps=5):
    return {"validation": {"ok": True}, "steps": _steps(n_steps)}


# ---------------------------------------------------------------- 1. 案例注册纪律
class CaseRegistryTest(unittest.TestCase):
    def test_ten_unique_cases_in_order(self):
        self.assertEqual(len(R_CASES), 10)
        self.assertEqual([c["id"] for c in R_CASES], EXPECTED_IDS)
        self.assertEqual(len(all_r_cases()), 10)
        self.assertIsNot(all_r_cases(), R_CASES)  # 返回副本，防止外部改单源
        self.assertEqual(len({c["desc"] for c in R_CASES}), 10)
        self.assertEqual(len({c["subject"] for c in R_CASES}), 10)
        self.assertEqual(len({c["name"] for c in R_CASES}), 10)
        self.assertEqual({c["id"]: c["target_blocks"] for c in R_CASES}, EXPECTED_TARGETS)

    def test_every_case_has_required_fields(self):
        for case in R_CASES:
            for key in ("id", "name", "subject", "desc", "complexity", "stress",
                        "historical_failure_hint", "target_blocks", "min_parts",
                        "min_solid_parts", "min_voxels", "min_ops",
                        "require_parts", "checks", "desc_sha256"):
                self.assertIn(key, case, case["id"])
            self.assertTrue(case["complexity"], case["id"])
            self.assertTrue(case["historical_failure_hint"], case["id"])
            self.assertIn("历史", case["historical_failure_hint"], case["id"])
            # 1–3 个压力类别，只能取允许集合
            self.assertGreaterEqual(len(case["stress"]), 1, case["id"])
            self.assertLessEqual(len(case["stress"]), 3, case["id"])
            self.assertEqual(len(set(case["stress"])), len(case["stress"]), case["id"])
            # 部位/立体部位/体素/算子设计下限
            self.assertEqual(case["min_parts"], len(case["require_parts"]), case["id"])
            self.assertGreaterEqual(case["min_parts"], 7, case["id"])
            self.assertLessEqual(case["min_parts"], 12, case["id"])
            self.assertGreaterEqual(case["min_solid_parts"], 4, case["id"])
            self.assertLessEqual(case["min_solid_parts"], case["min_parts"], case["id"])
            self.assertGreaterEqual(case["min_ops"], 8, case["id"])
            # 体素回归参考口径 = (target/2) × 4 = 2 × target
            self.assertEqual(case["min_voxels"], 2 * case["target_blocks"], case["id"])
            self.assertLessEqual(case["min_voxels"], 880, case["id"])

    def test_target_blocks_match_frozen_original_text(self):
        seen = set()
        for case in R_CASES:
            expected = EXPECTED_TARGETS[case["id"]]
            self.assertEqual(case["target_blocks"], expected, case["id"])
            self.assertEqual(parse_target_blocks(case["desc"]), expected, case["id"])
            self.assertEqual(plan_parse_target_blocks(case["desc"]), expected, case["id"])
            self.assertTrue(180 <= expected <= 440, case["id"])
            seen.add(expected)
        self.assertEqual(len(seen), 10, "10 例目标块数必须各不相同")
        self.assertEqual(R_TARGET_TOLERANCE, 0.5)

    def test_scale_sentence_writing_styles(self):
        """至少 2 例不带「约」；其余例写「目标约 N 块积木」；两种写法都解析一致。"""
        no_yue = [c for c in R_CASES if _is_no_yue_case(c)]
        self.assertGreaterEqual(len(no_yue), 2, "至少 2 例必须使用不带「约」的写法")
        self.assertEqual({c["id"] for c in no_yue}, NO_YUE_IDS)
        for case in R_CASES:
            desc = case["desc"].rstrip()
            target = case["target_blocks"]
            if _is_no_yue_case(case):
                sentence = f"目标 {target} 块积木"
                self.assertNotIn("约", case["desc"], case["id"])
            else:
                sentence = f"目标约 {target} 块积木"
            self.assertTrue(desc.endswith(sentence), f"{case['id']} 规模句不是结尾：{desc[-20:]}")
            self.assertIn(sentence, case["desc"], case["id"])
        # 两种写法都必须被生产单源解析（测试显式覆盖无「约」写法）
        self.assertEqual(plan_parse_target_blocks("目标 300 块积木"), 300)
        self.assertEqual(plan_parse_target_blocks("目标约 200 块积木"), 200)
        self.assertEqual(plan_parse_target_blocks("目标 180 块"), 180)
        self.assertEqual(plan_parse_target_blocks("目标约180块"), 180)
        self.assertIsNone(plan_parse_target_blocks("拼一只小鸟"))

    def test_desc_sha256_is_frozen(self):
        for case in R_CASES:
            digest = hashlib.sha256(case["desc"].encode("utf-8")).hexdigest()
            self.assertEqual(case["desc_sha256"], digest, case["id"])
            self.assertEqual(case["desc_sha256"], _desc_sha256(case["desc"]), case["id"])
            self.assertEqual(len(case["desc_sha256"]), 64, case["id"])
        # 冻结原文自检：哈希与目标块数逐例一致，且不允许占位符残留
        self.assertEqual(_verify_frozen_cases(), [])
        for case in R_CASES:
            self.assertNotIn("__SHA256_", case["desc_sha256"], case["id"])

    def test_desc_are_real_user_inputs(self):
        for case in R_CASES:
            desc = case["desc"]
            self.assertGreaterEqual(len(desc), 40, case["id"])
            self.assertLessEqual(len(desc), 240, case["id"])
            self.assertTrue(desc.startswith("拼"), case["id"])
            markers = sum(1 for m in STRUCTURE_MARKERS if m in desc)
            self.assertGreaterEqual(markers, 2, f"{case['id']} 缺少两类结构特征：{desc}")
            for word in FORBIDDEN_DESC_WORDS:
                self.assertNotIn(word, desc, f"{case['id']} 含禁止词 {word}")

    def test_subjects_are_distinct_from_existing_case_pools(self):
        ch_subjects = {c.get("subject") for c in all_ch_cases()}
        g_subjects = {c.get("subject") for c in G_CASES}
        n_subjects = {c.get("subject") for c in N_CASES}
        for case in R_CASES:
            self.assertNotIn(case["subject"], ch_subjects, case["id"])
            self.assertNotIn(case["subject"], g_subjects, case["id"])
            self.assertNotIn(case["subject"], n_subjects, case["id"])
        r_ids = {c["id"] for c in R_CASES}
        self.assertEqual(r_ids & {c["id"] for c in all_ch_cases()}, set())
        self.assertEqual(r_ids & {c["id"] for c in G_CASES}, set())
        self.assertEqual(r_ids & {c["id"] for c in N_CASES}, set())

    def test_require_parts_and_checks_are_assertable(self):
        for case in R_CASES:
            self.assertTrue(case["require_parts"], case["id"])
            self.assertTrue(case["checks"], case["id"])
            for name, patterns in case["require_parts"]:
                self.assertIsInstance(name, str, case["id"])
                self.assertTrue(name, case["id"])
                self.assertIsInstance(patterns, tuple, f"{case['id']} {name}")
                self.assertTrue(patterns, f"{case['id']} {name}")
                for pattern in patterns:
                    self.assertIsInstance(pattern, str, f"{case['id']} {name}")
                    self.assertTrue(pattern, f"{case['id']} {name}")
            for spec in case["checks"]:
                self.assertIsInstance(spec, list, case["id"])
                self.assertTrue(spec and isinstance(spec[0], str), case["id"])
                self.assertIsNotNone(resolve_check(spec[0]),
                                     f"{case['id']} 未注册检查 {spec[0]}")
            # checks 参数必须能落盘到轮次 JSON（tuple/list/str/int/float 均可）
            json.dumps(case["checks"], ensure_ascii=False)

    def test_find_r_case_semantics(self):
        self.assertEqual(find_r_case("r01")["id"], "R01")
        self.assertEqual(find_r_case(" R10 ")["id"], "R10")
        self.assertEqual(find_r_case(desc=R_CASES[4]["desc"])["id"], "R05")
        self.assertIsNone(find_r_case("R11"))
        self.assertIsNone(find_r_case("C01"))
        self.assertIsNone(find_r_case("N01"))
        self.assertIsNone(find_r_case(desc="不存在的需求"))
        self.assertIsNone(find_r_case(desc=R_CASES[0]["desc"] + "（改）"))


# ---------------------------------------------------------------- 2. 主题新颖性审计
class AuditTest(unittest.TestCase):
    def test_real_corpus_audit_has_no_conflicts(self):
        """公开审计语料 fixture 驱动：R 组 10 例与 C/X/G/N 已发布案例 0 冲突。"""
        from tools.e2e_cases_20 import _load_public_history_corpus
        corpus = _load_public_history_corpus(exclude_groups=("R",))
        self.assertIsNotNone(
            corpus, "公开审计语料缺失：test/fixtures/public/history-corpus.json")
        report = audit_r_cases(corpus=corpus)
        self.assertTrue(report["ok"], report["conflicts"])
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(len(report["cases"]), 10)
        for row in report["cases"]:
            self.assertEqual(row["conflicts"], [], row["id"])
        # 基准语料非空（需求原文 + 主题词 + C/H/G/N 案例池），不是空审计假通过
        self.assertGreater(report["corpus"]["descs"], 0)
        self.assertGreater(report["corpus"]["names"], 0)
        self.assertGreater(report["pools"]["count"], 0)
        self.assertFalse(report["used_clean_baseline"])
        self.assertEqual(sum(1 for row in report["cases"] if row["no_yue"]), 2)

    def test_injected_duplicate_desc_is_reported(self):
        corpus = ([R_CASES[0]["desc"]], [])
        report = audit_r_cases(corpus=corpus, check_case_pools=False)
        self.assertFalse(report["ok"])
        self.assertEqual([c["id"] for c in report["conflicts"]], ["R01"])
        self.assertTrue(any("需求原文与历史任务完全相同" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_subject_in_history_desc_is_reported(self):
        corpus = (["用户想拼一个放在客厅的蜗牛摆件，目标约 320 块积木"], [])
        report = audit_r_cases(corpus=corpus, check_case_pools=False)
        self.assertFalse(report["ok"])
        self.assertEqual(report["conflicts"][0]["id"], "R01")
        self.assertTrue(any("主题词「蜗牛」出现在历史需求" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_subject_in_model_name_is_reported(self):
        corpus = ([], ["蜗牛摆件"])
        report = audit_r_cases(corpus=corpus, check_case_pools=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("主题词「蜗牛」出现在历史模型名称/特征" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_case_pool_conflict_is_reported(self):
        """C/H/G/N 既有案例池也算撞题基线：主题与池内案例相同必须报错。"""
        pools = [{"source": "N案例池", "id": "NXX", "subject": "风铃",
                  "desc": "一个测试需求，目标约 200 块积木"}]
        fake = {"id": "RX1", "name": "撞池测试", "subject": "风铃",
                "desc": "一个测试需求，目标约 200 块积木"}
        report = audit_r_cases(cases=[fake], corpus=([], []), pools=pools)
        self.assertFalse(report["ok"])
        reasons = report["conflicts"][0]["reasons"]
        self.assertTrue(any("案例池" in r for r in reasons), reasons)

    def test_own_campaign_desc_is_excluded_from_baseline(self):
        """R 组自己跑过的需求/run 必须从基准中排除，否则二次审计会自我撞题。"""
        import tools.e2e_cases_20 as cases_20
        import tools.e2e_cases_r as cases_r
        with mock.patch.object(cases_20, "_load_history_corpus",
                               return_value=(["一只蜗牛"], [])):
            with mock.patch.object(cases_r, "_r_campaign_scope",
                                   return_value=({"一只蜗牛"}, set())):
                report = audit_r_cases(check_case_pools=False)
        self.assertTrue(report["ok"], report["conflicts"])
        # 只排除本组自己的：历史里其他需求仍照常参与审计
        with mock.patch.object(cases_20, "_load_history_corpus",
                               return_value=([R_CASES[4]["desc"]], [])):
            with mock.patch.object(cases_r, "_r_campaign_scope",
                                   return_value=({"一只蜗牛"}, set())):
                report2 = audit_r_cases(check_case_pools=False)
        self.assertFalse(report2["ok"])
        self.assertEqual([c["id"] for c in report2["conflicts"]], ["R05"])

    def test_clean_baseline_marks_used_clean_baseline(self):
        report = audit_r_cases(corpus=([], []), check_case_pools=False)
        self.assertTrue(report["ok"])
        self.assertTrue(report["used_clean_baseline"])
        self.assertEqual(len(report["cases"]), 10)


# ---------------------------------------------------------------- 3. CLI 可跑
class CliTest(unittest.TestCase):
    def _run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = r_cases_main(argv)
        return code, buf.getvalue()

    def test_list_cli(self):
        code, out = self._run_main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("共 10 例", out)
        self.assertIn("无「约」2 例", out)
        for case_id in EXPECTED_IDS:
            self.assertIn(case_id, out)

    def test_audit_cli(self):
        code, out = self._run_main(["--audit"])
        self.assertEqual(code, 0)
        self.assertIn("冲突 0 例", out)
        self.assertIn("R01", out)
        self.assertIn("R10", out)

    def test_audit_cli_empty_corpus_fails(self):
        """缺语料不得静默通过：--audit exit 2，只有 --allow-empty 显式放行。"""
        import tools.e2e_cases_r as cases_r
        with mock.patch.object(cases_r, "_load_r_history_corpus", return_value=([], [])):
            code, out = self._run_main(["--audit"])
            self.assertEqual(code, 2, out)
            self.assertIn("未执行完整新颖性审计", out)
            code2, _out2 = self._run_main(["--audit", "--allow-empty"])
            self.assertEqual(code2, 0)

    def test_default_dumps_json(self):
        code, out = self._run_main([])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 10)
        self.assertEqual([d["id"] for d in data], EXPECTED_IDS)
        self.assertEqual(data[0]["target_blocks"], 320)
        self.assertEqual(data[0]["desc_sha256"], R_CASES[0]["desc_sha256"])


# ---------------------------------------------------------------- 4. check_objects_r
class CheckObjectsRTest(unittest.TestCase):
    def setUp(self):
        """统一校验按同一模型重算；本类合成模型/方案只需校验桩放行。"""
        patcher = mock.patch("tools.e2e_assert.validate_solution",
                             return_value={"ok": True, "errors": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_positive_path_passes_and_metrics_complete(self):
        record = _fake_record()
        errors, metrics = check_objects_r(
            record, _fake_model(), _fake_solution(5),
            _fake_case(require_parts=[("身体", ("身体", "body"))]))
        self.assertEqual(errors, [], errors)
        self.assertTrue(metrics["assertion_ok"])
        self.assertEqual(metrics["suite"], "R")
        self.assertEqual(metrics["target_blocks"], 10)
        self.assertEqual(metrics["bricks"], 5)
        self.assertEqual(metrics["pieces"], 5)
        self.assertEqual(metrics["bricks_ratio"], 0.5)
        self.assertTrue(metrics["target_blocks_ok"])
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertEqual(metrics["generic_tier"], [])
        self.assertFalse(metrics["gate_failed"])
        self.assertEqual(metrics["final_gate_source"], "replay")
        self.assertTrue(metrics["final_gate_ok"])
        self.assertEqual(metrics["final_gate_replay"], {"ok": True, "errors": []})
        self.assertEqual(metrics["validation_ok"], True)
        self.assertEqual(metrics["review_overall"], None)
        self.assertEqual(metrics["review"], {})
        self.assertIsNone(metrics["review_source"])
        self.assertIsNone(metrics["review_stale"])
        self.assertIsNone(metrics["version_overwrites"])
        self.assertIn("feature_checks", metrics)
        self.assertEqual(metrics["feature_checks"][0]["name"], "layers_min")
        self.assertTrue(metrics["feature_checks"][0]["ok"])
        for key in ("case", "name", "run_id", "task_ok", "mode", "track", "parts",
                    "solid_parts", "surface_parts", "voxels", "ops", "layers", "grid",
                    "colors", "draw_attempts", "draw_requests", "assertion_errors"):
            self.assertIn(key, metrics)

    def test_target_ratio_below_50_percent_fails(self):
        """目标块数比不达标：bricks/target = 0.3 < 0.5 必须进 requirement_tier。"""
        errors, metrics = check_objects_r(
            _fake_record(), _fake_model(), _fake_solution(3), _fake_case())
        self.assertFalse(metrics["target_blocks_ok"])
        self.assertEqual(metrics["bricks_ratio"], 0.3)
        self.assertTrue(any("目标块数未达标" in e for e in errors), errors)
        self.assertTrue(any("目标块数未达标" in e for e in metrics["requirement_tier"]))
        self.assertEqual(metrics["generic_tier"], [])
        self.assertFalse(metrics["assertion_ok"])

    def test_missing_required_part_fails(self):
        """部位缺失：require_parts 命中不到时必须硬失败。"""
        cells = {(0, 0, 0), (1, 0, 0)}
        model_without_body = model_from_cells(cells, 2, 1, 1, [], default_color="L")
        errors, metrics = check_objects_r(
            _fake_record(), model_without_body, _fake_solution(5),
            _fake_case(require_parts=[("身体", ("身体", "body"))]))
        self.assertTrue(any("部位清单缺少身体" in e for e in errors), errors)
        self.assertTrue(metrics["requirement_tier"])
        self.assertFalse(metrics["assertion_ok"])

    def test_draw_requests_is_max_not_sum(self):
        """draw_requests 取 drawAttempts[].request 最大值：连续/空/跳号三种语义。"""
        cases = [
            ([{"request": 1}, {"request": 2}, {"request": 3}], 3),
            ([], 0),
            ([{"request": 1}, {"request": 3}], 3),
            ([{"request": None}, {"request": 2}], 2),
        ]
        for attempts, expected in cases:
            _errors, metrics = check_objects_r(
                _fake_record(drawAttempts=attempts), _fake_model(), _fake_solution(5),
                _fake_case())
            self.assertEqual(metrics["draw_requests"], expected, attempts)
            self.assertEqual(metrics["draw_attempts"], len(attempts))

    def test_generic_tier_version_and_review_baselines(self):
        """可信底线：评审过期/版本覆盖/最终门禁重放未通过都必须计入 generic_tier。"""
        errors, metrics = check_objects_r(
            _fake_record(reviewStale=True, versionOverwriteCount=2),
            _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("评审已过期" in e for e in errors), errors)
        self.assertTrue(any("版本覆盖" in e for e in errors), errors)
        self.assertEqual(metrics["review_stale"], True)
        self.assertEqual(metrics["version_overwrites"], 2)
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertFalse(metrics["assertion_ok"])

        errors2, metrics2 = check_objects_r(
            _fake_record(finalGateReplay={"ok": False, "errors": ["伪部位未修复"]}),
            _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("最终门禁重放未通过" in e for e in errors2), errors2)
        self.assertEqual(metrics2["final_gate_source"], "replay")
        self.assertFalse(metrics2["final_gate_ok"])

    def test_review_fallback_restores_old_record_score(self):
        """旧 run 记录 review 为空 + 任务 result.review 有分 → review_overall 恢复。"""
        fallback = {"scores": {"overall": 8.5}, "parsed": {"summary": "结构清晰"}}
        # 旧记录：没有 review 字段
        record = _fake_record()
        self.assertNotIn("review", record)
        _errors, metrics = check_objects_r(
            record, _fake_model(), _fake_solution(5), _fake_case(),
            review_fallback=fallback)
        self.assertEqual(metrics["review_overall"], 8.5)
        self.assertEqual(metrics["review"], fallback)
        self.assertEqual(metrics["review_source"], "task_result")
        # 旧记录：review 落成空 dict 时同样补入
        _errors, metrics = check_objects_r(
            _fake_record(review={}), _fake_model(), _fake_solution(5), _fake_case(),
            review_fallback=fallback)
        self.assertEqual(metrics["review_overall"], 8.5)
        # run 记录已有 review 时优先 run 记录，不被任务结果覆盖
        own = {"scores": {"overall": 6.0}}
        _errors, metrics = check_objects_r(
            _fake_record(review=own), _fake_model(), _fake_solution(5), _fake_case(),
            review_fallback=fallback)
        self.assertEqual(metrics["review_overall"], 6.0)
        self.assertEqual(metrics["review_source"], "run_record")
        # 两者都空：保持空 dict、review_overall=None（不得伪造分数）
        _errors, metrics = check_objects_r(
            _fake_record(), _fake_model(), _fake_solution(5), _fake_case(),
            review_fallback=None)
        self.assertEqual(metrics["review"], {})
        self.assertIsNone(metrics["review_overall"])

    def test_frozen_desc_mismatch_is_requirement_failure(self):
        """冻结口径守卫：运行记录需求原文被改动时必须硬失败（desc_sha256 冻结）。"""
        errors, metrics = check_objects_r(
            _fake_record(desc="被改过的需求原文"), _fake_model(), _fake_solution(5),
            _fake_case())
        self.assertTrue(any("冻结原文不一致" in e for e in errors), errors)
        self.assertFalse(metrics["assertion_ok"])

    def test_unknown_check_is_config_error(self):
        errors, metrics = check_objects_r(
            _fake_record(), _fake_model(), _fake_solution(5),
            _fake_case(checks=[["不存在的检查", 1]]))
        self.assertTrue(any("未知检查" in e for e in errors), errors)
        self.assertFalse(metrics["assertion_ok"])

    def test_task_failure_is_readable_not_raised(self):
        errors, metrics = check_objects_r(
            {"ok": False, "runId": "x", "error": "生成失败", "revision": 1, "artifacts": {}},
            {}, {}, _fake_case())
        self.assertTrue(any("运行未成功" in e for e in errors), errors)
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertFalse(metrics["assertion_ok"])


if __name__ == "__main__":
    unittest.main()
