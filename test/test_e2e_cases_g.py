# -*- coding: utf-8 -*-
"""工作包 G 新增确认集 G01–G10 的确定性回归测试（不调用真实模型/浏览器/求解）。

覆盖：
  1. 案例注册纪律：编号唯一、原文逐字冻结、target_blocks 与原文一致、检查器全部注册、
     C/H/G 前缀不串配、G03/G08 换题记录；
  2. 主题新颖性审计：真实语料全绿、注入撞题必须报错（需求原文/主题词/模型名三类）、
     审计不能靠改名掩盖旧题；
  3. check_objects_g 的通用底线 + 需求达标档 + 回归档：目标块数 50% 容差边界、
     最终门禁重放兼容读取、回归指标不判失败；
  4. 10.2 表每个专项断言都有「应通过」与「应失败」合成模型（防断言写反/空断言）；
  5. 10.3 全部反例必须被拒（拱洞涂黑、吊钩贴梁、竖琴实心三角块/琴弦缺失、翅膀涂装、
     单峰骆驼、环缝填实、滑雪板换车轮、独轮车斗体填实/把手单侧/车轮换方块、笔筒填实、
     小鸟缺翼），以及 G02 悬吊的单锁扣/双锁扣/倾覆/插入卡口、G09「顶部封死但侧面有洞」、
     G10 无追问继续/最多一次默认决策/取消/空描述不误提交。
"""
import json
import unittest
from unittest import mock

import contextlib
import io

from tools.e2e_assert_g import G_CHECKS, check_objects_g
from tools.e2e_cases_20 import all_cases as all_ch_cases
from tools.e2e_cases_g import (G_CASES, G_TARGET_TOLERANCE, all_g_cases, audit_g_cases,
                               find_g_case, parse_target_blocks)
from tools.e2e_assert_20 import _part_counts
from tools.e2e_assert import _colored_cells

SLOPE = "\\"


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
    cells = set(cells or [])
    if not cells and boxes:
        for b in boxes:
            for y in range(b["y1"], b["y2"] + 1):
                for x in range(b["x1"], b["x2"] + 1):
                    for z in range(b["z1"], b["z2"] + 1):
                        cells.add((x, y, z))
    return {"id": pid, "name": name, "role": role, "voxels": len(cells), "boxes": boxes}


def box(x1, x2, z1, z2, y1=0, y2=0):
    return {"x1": x1, "x2": x2, "z1": z1, "z2": z2, "y1": y1, "y2": y2}


def model_from_cells(cells, w, d, h=None, parts=None, colors=None, default_color=None,
                     ops=None, track="ops"):
    """由 3D 实体格生成 model（layers/rows/cells/colorRows 全齐）。"""
    cells = set(cells)
    ys = sorted({c[1] for c in cells}) or [0]
    h = h or (max(ys) + 1)
    layers = []
    for y in range(h):
        plane = {(x, z) for (x, yy, z) in cells if yy == y}
        rows = ["".join("#" if (x, z) in plane else "." for x in range(w)) for z in range(d)]
        if colors is None and default_color is None:
            color_rows = None
        else:
            color_rows = []
            for z in range(d):
                line = []
                for x in range(w):
                    if (x, z) not in plane:
                        line.append(".")
                    else:
                        line.append((colors or {}).get((x, y, z)) or default_color or ".")
                color_rows.append("".join(line))
        layers.append({"y": y, "rows": rows,
                       "cells": [[x, z] for z in range(d) for x in range(w) if (x, z) in plane],
                       "module": ["m"], "color": None, "colorRows": color_rows,
                       "count": len(plane)})
    return {"name": "测试G", "grid": {"w": w, "d": d}, "totalVoxels": len(cells),
            "slopeVoxels": 0, "layers": layers, "parts": parts or [],
            "ops": ops or [], "track": track}


def make_model(layers_rows, parts=None, ops=None, track="ops", color_rows=None):
    """与 test/test_e2e_cases20.py 同形的极简模型构造器（按 rows 字符串）。"""
    layers = []
    for y, rows in enumerate(layers_rows):
        d = len(rows)
        w = len(rows[0]) if d else 0
        cells = [[x, z] for z, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["m"], "color": None,
                       "colorRows": (color_rows or [None] * len(layers_rows))[y],
                       "count": len(cells)})
    return {"name": "测试模型", "grid": {"w": w, "d": d},
            "totalVoxels": sum(L["count"] for L in layers),
            "slopeVoxels": sum(sum(1 for ch in row if ch in "\\/^vbdpq")
                               for rows in layers_rows for row in rows),
            "layers": layers, "parts": parts or [], "ops": ops or [], "track": track}


def ctx(model, solution=None):
    return {"model": model, "solution": solution or {"validation": {"ok": True}},
            "counts": _part_counts(model), "colored": _colored_cells(model)}


# 正/反例覆盖统计：所有以 g_ 开头的专项检查器都必须在测试里出现正反例各 ≥1 次
COVERAGE = {}
COUNTEREXAMPLE_COVERED = set()


def run_check(name, model, *args, solution=None):
    errors = G_CHECKS[name](ctx(model, solution), *args)
    ent = COVERAGE.setdefault(name, {"pass": 0, "fail": 0})
    ent["pass" if not errors else "fail"] += 1
    return errors


def assert_pass(testcase, name, model, *args, solution=None):
    errors = run_check(name, model, *args, solution=solution)
    testcase.assertEqual(errors, [], f"{name} 正例不应报错：{errors}")
    return errors


def assert_fail(testcase, name, model, *args, solution=None, contains=None):
    errors = run_check(name, model, *args, solution=solution)
    testcase.assertTrue(errors, f"{name} 反例必须被拒绝（不得空断言）")
    if contains is not None:
        testcase.assertTrue(any(contains in e for e in errors),
                            f"{name} 反例错误原因应含「{contains}」：{errors}")
    return errors


# ---------------------------------------------------------------- 案例注册纪律
EXPECTED_DESCS = {
    "G01": "一座罗马斗兽场：椭圆形多层石质外墙，逐层排列贯通拱洞，部分外墙残缺，"
           "内部有环形座位和中央表演场地，底部有石台基，目标约 420 块积木",
    "G02": "一座港口龙门吊：四根支腿支撑双根主梁，主梁一端外伸，上方有行走小车和驾驶室，"
           "下方用吊索悬挂吊钩，带配重、爬梯和货物平台，目标约 400 块积木",
    "G03": "一台落地竖琴：金色与木色的三角框架立在地面上，前侧弧形琴柱向上收分，"
           "三角框架内张着不少于 8 根竖向琴弦，底部有底座与踏板，整体落地摆放，目标约 320 块积木",
    "G04": "一只蜻蜓：细长腹部、明显胸部和头部，四片轻薄翅膀向两侧展开，六条细腿，"
           "复眼用异色小色点，目标约 280 块积木",
    "G05": "一头双峰骆驼：棕色身体上有两个分开的驼峰，长颈抬头，四条长腿落地，"
           "带尾巴和耳朵，目标约 320 块积木",
    "G06": "一个土星展示模型：米黄色球形土星，外侧一圈倾斜的宽环，环与球体之间留有空隙，"
           "下方有支架和深色展示底座，目标约 300 块积木",
    "G07": "一辆雪地摩托：前部两块分开的滑雪板，后部宽履带，车身有座椅、挡风玻璃、车把和前灯，"
           "目标约 320 块积木",
    "G08": "一辆老式手推独轮车：只有单个圆形车轮架在木制轮轴上，左右成对两根长把手向后伸出，"
           "上方斗体有内腔、顶部敞开，底部两根支脚分立落地，车轮与车架轮轴相连，目标约 300 块积木",
    "G09": "一个极简笔筒：圆角方形空心杯体，顶部完全敞开，底部封闭，"
           "里面插三支不同颜色和不同高度的笔，目标约 180 块积木",
    "G10": "一只小鸟",
}
EXPECTED_TARGETS = {"G01": 420, "G02": 400, "G03": 320, "G04": 280, "G05": 320,
                    "G06": 300, "G07": 320, "G08": 300, "G09": 180, "G10": None}
EXPECTED_NAMES = {"G01": "罗马斗兽场", "G02": "港口龙门吊", "G03": "落地竖琴", "G04": "蜻蜓",
                  "G05": "双峰骆驼", "G06": "土星展示模型", "G07": "雪地摩托",
                  "G08": "老式手推独轮车", "G09": "极简笔筒", "G10": "模糊需求小鸟"}


class CaseRegistryTest(unittest.TestCase):
    def test_ten_unique_cases_in_order(self):
        self.assertEqual(len(G_CASES), 10)
        self.assertEqual([c["id"] for c in G_CASES], [f"G{i:02d}" for i in range(1, 11)])
        self.assertEqual(len(all_g_cases()), 10)
        self.assertEqual(len({c["desc"] for c in G_CASES}), 10)
        self.assertEqual(len({c["subject"] for c in G_CASES}), 10)
        self.assertEqual(len({c["name"] for c in G_CASES}), 10)

    def test_descriptions_are_frozen_verbatim(self):
        """与方案 10.2 冻结原文逐字一致；G03/G08 为 Lead 决策 B 换题后重新冻结的新原文。"""
        for case in G_CASES:
            self.assertEqual(case["desc"], EXPECTED_DESCS[case["id"]], case["id"])
        self.assertEqual({c["id"]: c["name"] for c in G_CASES}, EXPECTED_NAMES)

    def test_target_blocks_match_frozen_original_text(self):
        for case in G_CASES:
            expected = EXPECTED_TARGETS[case["id"]]
            self.assertEqual(case["target_blocks"], expected, case["id"])
            self.assertEqual(parse_target_blocks(case["desc"]), expected, case["id"])
            if expected is None:
                self.assertNotIn("目标约", case["desc"], case["id"])
            else:
                self.assertIn(f"目标约 {expected} 块积木", case["desc"], case["id"])

    def test_case_fields_are_assertable(self):
        for case in G_CASES:
            self.assertTrue(case["complexity"], case["id"])
            self.assertGreaterEqual(case["min_parts"], 5, case["id"])
            self.assertGreaterEqual(case["min_solid_parts"], 4, case["id"])
            self.assertLessEqual(case["min_solid_parts"], case["min_parts"], case["id"])
            self.assertGreaterEqual(case["min_voxels"], 200, case["id"])
            self.assertGreaterEqual(case["min_ops"], 8, case["id"])
            self.assertTrue(case["require_parts"], case["id"])
            for name, patterns in case["require_parts"]:
                self.assertIsInstance(patterns, tuple, f"{case['id']} {name}")
                self.assertTrue(patterns, f"{case['id']} {name}")
            self.assertTrue(case["checks"], case["id"])
            for spec in case["checks"]:
                self.assertIn(spec[0], G_CHECKS, f"{case['id']} 未注册检查 {spec[0]}")
            if case["target_blocks"]:
                # 规模下限口径：N/2 块 × 4 体素/块 = 2N（回归档参考）
                self.assertEqual(case["min_voxels"], 2 * case["target_blocks"], case["id"])

    def test_old_themes_are_not_used_in_cases(self):
        """当前案例不得再使用已替换的旧主题（只校验案例本身，不依赖内部过程记录）。"""
        for case in G_CASES:
            self.assertNotIn("三角钢琴", case["desc"], case["id"])
            self.assertNotIn("三角钢琴", case["subject"], case["id"])
            self.assertNotIn("自行车", case["subject"], case["id"])
            self.assertNotIn("自行车", case["desc"], case["id"])

    def test_find_g_case_semantics(self):
        self.assertEqual(find_g_case("g01")["id"], "G01")
        self.assertEqual(find_g_case(" G10 ")["id"], "G10")
        self.assertEqual(find_g_case(desc=EXPECTED_DESCS["G05"])["id"], "G05")
        self.assertIsNone(find_g_case("G99"))
        self.assertIsNone(find_g_case("C01"))
        self.assertIsNone(find_g_case("H01"))
        self.assertIsNone(find_g_case(desc="不存在的需求"))
        self.assertIsNone(find_g_case(desc=EXPECTED_DESCS["G01"] + "（改）"))

    def test_c_h_g_prefix_never_cross(self):
        """区间解析只按编号前缀匹配：C01-C05 / H01-H05 不得误配 G01-G05。"""
        ch_pool = list(all_ch_cases())
        ch_ids = {c["id"] for c in ch_pool}
        combined = ch_pool + [c for c in all_g_cases() if c["id"] not in ch_ids]
        self.assertEqual([c["id"] for c in G_CASES if c["id"] not in ch_ids],
                         [f"G{i:02d}" for i in range(1, 11)])

        def pick(prefix, lo, hi):
            return [c["id"] for c in combined
                    if c["id"][:1].upper() == prefix and lo <= int(c["id"][1:]) <= hi]

        self.assertEqual(pick("G", 1, 10), [f"G{i:02d}" for i in range(1, 11)])
        self.assertEqual(pick("G", 1, 5), [f"G{i:02d}" for i in range(1, 6)])
        self.assertFalse([i for i in pick("C", 1, 5) if i.startswith("G")])
        self.assertFalse([i for i in pick("H", 1, 5) if i.startswith("G")])
        self.assertFalse([i for i in pick("G", 1, 10) if i[0] != "G"])
        # 编号全局唯一：G 组不会与 C/H 撞号（同号不同前缀是设计允许的）
        self.assertEqual(len({(c["id"][0], int(c["id"][1:])) for c in combined}),
                         len(combined))


# ---------------------------------------------------------------- 主题新颖性审计
class AuditTest(unittest.TestCase):
    def test_real_corpus_audit_has_no_conflicts(self):
        """公开审计语料 fixture 驱动：G 组 10 例与 C/X/N/R 已发布案例 0 冲突。"""
        from tools.e2e_cases_20 import _load_public_history_corpus
        corpus = _load_public_history_corpus(exclude_groups=("G",))
        self.assertIsNotNone(
            corpus, "公开审计语料缺失：test/fixtures/public/history-corpus.json")
        report = audit_g_cases(corpus=corpus)
        self.assertTrue(report["ok"], report["conflicts"])
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(len(report["cases"]), 10)
        for row in report["cases"]:
            self.assertEqual(row["conflicts"], [], row["id"])
        # 基准语料非空，不是空审计假通过
        self.assertGreater(report["corpus"]["descs"], 0)
        self.assertGreater(report["corpus"]["names"], 0)
        self.assertFalse(report["used_clean_baseline"])

    def test_injected_duplicate_desc_is_reported(self):
        corpus = ([EXPECTED_DESCS["G01"]], [])
        report = audit_g_cases(corpus=corpus)
        self.assertFalse(report["ok"])
        self.assertEqual([c["id"] for c in report["conflicts"]], ["G01"])
        self.assertTrue(any("需求原文与历史任务完全相同" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_subject_in_history_desc_is_reported(self):
        corpus = (["用户想拼一个放在客厅的罗马斗兽场摆件"], [])
        report = audit_g_cases(corpus=corpus)
        self.assertFalse(report["ok"])
        reasons = report["conflicts"][0]["reasons"]
        self.assertTrue(any("主题词「罗马斗兽场」出现在历史需求" in r for r in reasons))

    def test_injected_subject_in_model_name_is_reported(self):
        corpus = ([], ["罗马斗兽场"])
        report = audit_g_cases(corpus=corpus)
        self.assertFalse(report["ok"])
        self.assertTrue(any("主题词「罗马斗兽场」出现在历史模型名称/特征" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_renamed_old_theme_cannot_hide_conflict(self):
        """把旧题改名不算新颖：即使旧题原文在语料里，新题原文若撞题也必须报错。"""
        corpus = (["一架黑色三角钢琴：黑白琴键、打开的琴盖、三条琴腿和踏板"], [])
        report = audit_g_cases(corpus=corpus)
        # 换题后的 G03 竖琴与钢琴无关 → 不撞；但只要新原文被历史收录就必须报错
        self.assertTrue(report["ok"], report["conflicts"])
        report2 = audit_g_cases(corpus=([EXPECTED_DESCS["G03"]], []))
        self.assertFalse(report2["ok"])
        self.assertEqual(report2["conflicts"][0]["id"], "G03")

    def test_clean_baseline_marks_used_clean_baseline(self):
        report = audit_g_cases(corpus=([], []))
        self.assertTrue(report["ok"])
        self.assertTrue(report["used_clean_baseline"])
        self.assertEqual(len(report["cases"]), 10)

    def test_own_campaign_desc_is_excluded_from_baseline(self):
        """G 组自己跑过的需求/run 必须从基准中排除，否则二次审计会自我撞题。"""
        import tools.e2e_cases_20 as cases_20
        import tools.e2e_cases_g as cases_g
        with mock.patch.object(cases_20, "_load_history_corpus",
                               return_value=(["一只小鸟"], [])):
            with mock.patch.object(cases_g, "_g_campaign_scope",
                                   return_value=({"一只小鸟"}, set())):
                report = audit_g_cases()
        self.assertTrue(report["ok"], report["conflicts"])
        self.assertEqual(report["conflicts"], [])
        # 只排除本组自己的：历史里其他需求仍照常参与审计
        with mock.patch.object(cases_20, "_load_history_corpus",
                               return_value=([EXPECTED_DESCS["G05"]], [])):
            with mock.patch.object(cases_g, "_g_campaign_scope",
                                   return_value=({"一只小鸟"}, set())):
                report2 = audit_g_cases()
        self.assertFalse(report2["ok"])
        self.assertEqual([c["id"] for c in report2["conflicts"]], ["G05"])


class AuditCliEmptyCorpusTest(unittest.TestCase):
    """缺语料不得静默通过：--audit 必须 exit 2，只有 --allow-empty 才显式放行。"""

    def _run(self, argv):
        import tools.e2e_cases_g as cases_g
        with mock.patch.object(cases_g, "_load_g_history_corpus", return_value=([], [])):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cases_g.main(argv)
        return code, buf.getvalue()

    def test_empty_corpus_fails(self):
        code, out = self._run(["--audit"])
        self.assertEqual(code, 2, out)
        self.assertIn("未执行完整新颖性审计", out)

    def test_allow_empty_is_explicit_local_escape(self):
        code, out = self._run(["--audit", "--allow-empty"])
        self.assertEqual(code, 0, out)


# ---------------------------------------------------------------- check_objects_g / metrics
def _fake_case(**over):
    case = {"id": "GXX", "name": "测试案例", "target_blocks": 10,
            "min_parts": 1, "min_solid_parts": 1, "min_voxels": 1, "min_ops": 0,
            "require_parts": [], "checks": [["layers_min", 1]]}
    case.update(over)
    return case


def _steps(n, layer=0):
    return [{"piece": "B1x1", "x": 0, "z": 0, "layer": layer, "rotate": False, "step": i + 1}
            for i in range(n)]


class MetricsTest(unittest.TestCase):
    def setUp(self):
        """统一校验按同一模型重算（2026-11-03 复核修正）；本类合成模型/方案只需校验桩放行。"""
        patcher = mock.patch("tools.e2e_assert.validate_solution",
                             return_value={"ok": True, "errors": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _model(self):
        cells = {(0, 0, 0), (1, 0, 0)}
        return model_from_cells(cells, 2, 1, 1,
                                [make_part("body", "主体", cells=cells)], default_color="L")

    def test_metrics_include_target_and_tiers(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        model = self._model()
        solution = {"validation": {"ok": True}, "steps": _steps(5)}
        errors, metrics = check_objects_g(record, model, solution, _fake_case())
        self.assertEqual(errors, [])
        self.assertEqual(metrics["target_blocks"], 10)
        self.assertEqual(metrics["bricks"], 5)
        self.assertEqual(metrics["bricks_ratio"], 0.5)
        self.assertTrue(metrics["target_blocks_ok"])
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertIn("regression_tier", metrics)
        regression = metrics["regression_tier"]
        for key in ("voxels", "layers", "colors", "ops", "voxels_per_target_block"):
            self.assertIn(key, regression)
        self.assertTrue(metrics["assertion_ok"])

    def test_target_tolerance_boundary_50_percent(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        model = self._model()
        case = _fake_case()
        ok = {"validation": {"ok": True}, "steps": _steps(5)}
        _e, metrics = check_objects_g(record, model, ok, case)
        self.assertTrue(metrics["target_blocks_ok"])
        below = {"validation": {"ok": True}, "steps": _steps(4)}
        errors, metrics = check_objects_g(record, model, below, case)
        self.assertFalse(metrics["target_blocks_ok"])
        self.assertEqual(metrics["bricks_ratio"], 0.4)
        self.assertTrue(any("目标块数未达标" in e for e in errors))
        self.assertTrue(any("目标块数未达标" in e for e in metrics["requirement_tier"]))
        self.assertFalse(metrics["assertion_ok"])

    def test_no_target_blocks_skips_scale_gate(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        model = self._model()
        solution = {"validation": {"ok": True}, "steps": _steps(0)}
        errors, metrics = check_objects_g(record, model, solution,
                                          _fake_case(target_blocks=None, id="G10"))
        self.assertIsNone(metrics["target_blocks"])
        self.assertIsNone(metrics["bricks_ratio"])
        self.assertFalse(metrics["target_blocks_ok"])
        self.assertEqual(errors, [])

    def test_final_gate_replay_is_read_compatibly(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {},
                  "finalGateReplay": {"ok": False, "errors": ["墙皮部位过小"]}}
        model = self._model()
        solution = {"validation": {"ok": True}, "steps": _steps(5)}
        errors, metrics = check_objects_g(record, model, solution, _fake_case())
        self.assertTrue(any("最终门禁重放未通过" in e for e in errors))
        self.assertIn("最终门禁重放未通过", " ".join(metrics["generic_tier"]))
        self.assertFalse(metrics["assertion_ok"])
        passed = dict(record, finalGateReplay={"ok": True, "errors": []})
        errors2, _m = check_objects_g(passed, model, solution, _fake_case())
        self.assertFalse(any("最终门禁重放" in e for e in errors2))

    def test_task_failure_short_circuits_case_checks(self):
        record = {"ok": False, "runId": "x", "error": "生成失败", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_g(record, self._model(),
                                          {"validation": {"ok": True}, "steps": _steps(0)},
                                          _fake_case())
        self.assertTrue(any("运行未成功" in e for e in errors))
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertTrue(metrics["generic_tier"])

    def test_min_part_floor_is_requirement_failure(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        model = self._model()
        solution = {"validation": {"ok": True}, "steps": _steps(5)}
        errors, metrics = check_objects_g(record, model, solution,
                                          _fake_case(min_parts=5, min_solid_parts=4))
        self.assertTrue(any("部位数" in e for e in errors))
        self.assertFalse(metrics["assertion_ok"])

    def test_regression_metrics_never_fail_the_case(self):
        """体素/算子低于设计参考下限只进回归档，不判失败（方案 10.1）。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        model = self._model()
        solution = {"validation": {"ok": True}, "steps": _steps(5)}
        errors, metrics = check_objects_g(
            record, model, solution,
            _fake_case(min_voxels=1000, min_ops=99, checks=[["layers_min", 1]]))
        self.assertEqual(errors, [])
        regression = metrics["regression_tier"]
        self.assertTrue(regression["voxels_below_design_floor"])
        self.assertTrue(regression["ops_below_design_floor"])
        self.assertTrue(metrics["assertion_ok"])

    def test_unknown_check_is_config_error(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, _m = check_objects_g(record, self._model(),
                                     {"validation": {"ok": True}, "steps": _steps(5)},
                                     _fake_case(checks=[["不存在的检查", 1]]))
        self.assertTrue(any("未知检查" in e for e in errors))

    def test_check_exception_becomes_readable_error(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, _m = check_objects_g(record, self._model(),
                                     {"validation": {"ok": True}, "steps": _steps(5)},
                                     _fake_case(checks=[["layers_min"]]))
        self.assertTrue(any("执行失败" in e for e in errors))

    def test_draw_requests_takes_cumulative_max(self):
        """drawAttempts[].request 是累计编号，请求数取最大值。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {},
                  "drawAttempts": [{"attempt": 1, "request": 1},
                                   {"attempt": 2, "request": 2},
                                   {"attempt": 3, "request": 3}]}
        _e, metrics = check_objects_g(record, self._model(),
                                      {"validation": {"ok": True}, "steps": _steps(5)},
                                      _fake_case())
        self.assertEqual(metrics["draw_attempts"], 3)
        self.assertEqual(metrics["draw_requests"], 3)   # 不是 1+2+3=6
        _e2, empty = check_objects_g(
            {"ok": True, "runId": "x", "revision": 1, "artifacts": {}, "drawAttempts": []},
            self._model(), {"validation": {"ok": True}, "steps": _steps(5)}, _fake_case())
        self.assertEqual(empty["draw_requests"], 0)

    def test_review_fallback_from_task_result(self):
        """旧 run 记录没有 review：用任务 result.review 补入并留痕来源。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_g(
            record, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
            _fake_case(), review_fallback={"scores": {"overall": 5}})
        self.assertEqual(errors, [])
        self.assertEqual(metrics["review_overall"], 5)
        self.assertEqual(metrics["review_source"], "task_result")
        # run 记录自带 review 时优先且不覆盖
        _e2, own = check_objects_g(
            dict(record, review={"scores": {"overall": 3}}), self._model(),
            {"validation": {"ok": True}, "steps": _steps(5)}, _fake_case(),
            review_fallback={"scores": {"overall": 5}})
        self.assertEqual(own["review_overall"], 3)
        self.assertEqual(own["review_source"], "run_record")


# ================================================================ G01 罗马斗兽场
W1, D1, H1 = 22, 14, 6
A1, B1 = W1 / 2.0, D1 / 2.0


def g01_t(x, z):
    return ((x + 0.5 - A1) / A1) ** 2 + ((z + 0.5 - B1) / B1) ** 2


def g01_ang(cell):
    import math
    return math.degrees(math.atan2(cell[2] + 0.5 - B1, cell[0] + 0.5 - A1)) % 360


def g01_near(a, b, tol):
    diff = abs(a - b) % 360
    return min(diff, 360 - diff) <= tol


def g01_model(arches=True, ruined=True, seats=True, tiered=True, black=False, arch_tol=14):
    ring = set()
    tmin = {0: 0.5, 1: 0.5, 2: 0.5, 3: 0.55, 4: 0.65, 5: 0.8} if tiered \
        else {y: 0.5 for y in range(H1)}
    for y in range(H1):
        for x in range(W1):
            for z in range(D1):
                if tmin[y] <= g01_t(x, z) <= 1.0:
                    ring.add((x, y, z))
    arch_removed = set()
    if arches:
        for cell in list(ring):
            if cell[1] in (1, 2) and any(g01_near(g01_ang(cell), a, arch_tol)
                                         for a in range(0, 360, 60)):
                arch_removed.add(cell)
                ring.discard(cell)
    if ruined:
        for cell in list(ring):
            if g01_near(g01_ang(cell), 30, 11):
                ring.discard(cell)
    seat = set()
    if seats:
        for y in (0, 1):
            for x in range(W1):
                for z in range(D1):
                    if 0.18 <= g01_t(x, z) <= 0.34:
                        seat.add((x, y, z))
    base = {(c[0], 0, c[2]) for c in ring if c[1] == 0}
    floor = {((W1 - 1) // 2, 0, (D1 - 1) // 2)}
    cells = ring | seat | base | floor
    if black:
        cells = cells | arch_removed
        parts = [make_part("wall", "石质外墙", cells=cells),
                 make_part("seats", "环形座位", cells=seat),
                 make_part("base", "石台基", cells=base),
                 make_part("arena", "中央表演场地", cells=floor, role="surface")]
        return model_from_cells(cells, W1, D1, H1, parts,
                                {c: "K" for c in arch_removed}, default_color="L")
    parts = [make_part("wall", "石质外墙", cells=ring),
             make_part("arch", "贯通拱洞", cells=arch_removed),
             make_part("seats", "环形座位", cells=seat),
             make_part("base", "石台基", cells=base),
             make_part("arena", "中央表演场地", cells=floor, role="surface")]
    return model_from_cells(cells, W1, D1, H1, parts)


class G01CheckerTest(unittest.TestCase):
    def test_positive_model_passes_all_special_assertions(self):
        model = g01_model()
        assert_pass(self, "g_ellipse_ring", model, ("外墙", "墙", "wall"))
        assert_pass(self, "g_arch_holes_min", model, 6)
        assert_pass(self, "tiered_min", model, 3)
        assert_pass(self, "g_seating_arena", model, ("座位", "看台", "seat"))
        assert_pass(self, "g_ruined_gap", model)

    def test_blacked_out_arches_are_rejected(self):
        """10.3 反例：拱洞涂黑（墙体填实 + 表面涂黑）不算真实贯通拱洞。"""
        errors = assert_fail(self, "g_arch_holes_min",
                             g01_model(arches=False, ruined=False, black=True), 6)
        self.assertTrue(any("负空间" in e for e in errors))
        COUNTEREXAMPLE_COVERED.add("拱洞涂黑")

    def test_solid_wall_without_arches_is_rejected(self):
        assert_fail(self, "g_arch_holes_min", g01_model(arches=False, ruined=False), 6)

    def test_solid_ellipse_disk_is_rejected(self):
        disk = {(x, y, z) for y in range(4) for x in range(W1) for z in range(D1)
                if g01_t(x, z) <= 1.0}
        model = model_from_cells(disk, W1, D1, 4,
                                 [make_part("wall", "石质外墙", cells=disk)])
        assert_fail(self, "g_ellipse_ring", model, ("外墙",), contains="环形中空")

    def test_rectangular_wall_is_rejected(self):
        rect = {(x, y, z) for y in range(4) for x in range(W1) for z in range(D1)
                if x in (0, W1 - 1) or z in (0, D1 - 1)}
        model = model_from_cells(rect, W1, D1, 4,
                                 [make_part("wall", "石质外墙", cells=rect)])
        assert_fail(self, "g_ellipse_ring", model, ("外墙",), contains="椭圆收角")

    def test_missing_ruined_gap_is_rejected(self):
        assert_fail(self, "g_ruined_gap", g01_model(ruined=False), contains="残墙缺口")

    def test_missing_ring_seats_is_rejected(self):
        assert_fail(self, "g_seating_arena", g01_model(seats=False),
                    ("座位",), contains="未找到环形座位")

    def test_seats_filled_into_center_is_rejected(self):
        model = g01_model()
        wall = {c for c in _solid_cells(model)}
        center = ((W1 - 1) // 2, 0, (D1 - 1) // 2)
        wall.discard(center)
        parts = [make_part("wall", "石质外墙", cells=wall),
                 make_part("seats", "环形座位", cells={(center[0], y, center[2])
                                                        for y in range(3)})]
        model = model_from_cells(wall | {(center[0], y, center[2]) for y in range(3)},
                                 W1, D1, H1, parts)
        assert_fail(self, "g_seating_arena", model, ("座位",), contains="中央表演场地")

    def test_flat_ring_without_tier_changes_is_rejected(self):
        """至少 3 层高度/退台变化：各层截面完全相同的模型必须被拒。"""
        flat = {(x, y, 0) for x in range(6) for y in range(3)}
        model = model_from_cells(flat, 6, 1, 3, [make_part("body", "主体", cells=flat)])
        assert_fail(self, "tiered_min", model, 3, contains="档位不足")


def _solid_cells(model):
    out = set()
    for L in model.get("layers") or []:
        for c in L["cells"]:
            out.add((c[0], L["y"], c[1]))
    return out


# ================================================================ G02 港口龙门吊
def crane_model(merged_legs=False, single_beam=False, trolley_gap=False,
                cw_same_side=False, rungs=3, use_suspension_solution=False):
    """龙门吊正/反例模型；use_suspension_solution 时吊钩走 solution 物理路径。"""
    W, D, H = 14, 8, 8
    cells, parts = set(), []
    leg_cells = set()
    if merged_legs:
        leg_cells = {(x, y, z) for y in range(4) for x in (1, 2, 3) for z in range(1, 7)}
    else:
        for (lx, lz) in ((1, 1), (11, 1), (1, 6), (11, 6)):
            leg_cells |= {(lx, y, lz) for y in range(4)}
    parts.append(make_part("legs", "支腿", cells=leg_cells))
    cells |= leg_cells
    if single_beam:
        beam = {(x, y, 1) for y in (4, 5) for x in range(0, 14)}
        parts.append(make_part("beam", "主梁", cells=beam,
                               boxes=[{"x1": 0, "x2": 13, "z1": 1, "z2": 1, "y1": 4, "y2": 5}]))
    else:
        beam = {(x, y, z) for y in (4, 5) for z in (1, 6) for x in range(0, 14)}
        parts.append(make_part("beam", "主梁", cells=beam, boxes=[
            {"x1": 0, "x2": 13, "z1": 1, "z2": 1, "y1": 4, "y2": 5},
            {"x1": 0, "x2": 13, "z1": 6, "z2": 6, "y1": 4, "y2": 5}]))
    cells |= beam
    ty = 7 if trolley_gap else 6
    trolley = {(x, ty, z) for x in range(5, 9) for z in range(2, 5)}
    parts.append(make_part("trolley", "行走小车", cells=trolley))
    cells |= trolley
    cab = {(x, y, z) for y in (4, 5) for x in range(2, 5) for z in range(2, 5)}
    parts.append(make_part("cab", "驾驶室", cells=cab))
    cells |= cab
    sling = {(6, 3, 1), (7, 3, 1)}
    hook = {(6, 2, 1), (7, 2, 1)}
    parts.append(make_part("sling", "吊索", cells=sling))
    parts.append(make_part("hook", "吊钩", cells=hook))
    cells |= sling | hook
    cw = {(x, 6, z) for x in ((12, 13) if cw_same_side else (0, 1)) for z in range(1, 7)}
    parts.append(make_part("cw", "配重", cells=cw))
    cells |= cw
    ladder = ({(1, y, 0) for y in range(4)} | {(4, y, 0) for y in range(4)}
              | {(x, y, 0) for y in range(1, rungs + 1) for x in range(2, 4)})
    parts.append(make_part("ladder", "爬梯", cells=ladder))
    cells |= ladder
    platform = {(x, 4, z) for x in range(9, 13) for z in range(2, 5)}
    parts.append(make_part("platform", "货物平台", cells=platform))
    cells |= platform
    return model_from_cells(cells, W, D, H, parts)


class G02CheckerTest(unittest.TestCase):
    def test_positive_crane_structure(self):
        model = crane_model()
        assert_pass(self, "g_legs_separate_min", model, ("支腿", "腿", "leg"), 4)
        assert_pass(self, "g_double_beam", model, ("主梁", "梁", "beam"), 2, 10, 2)
        assert_pass(self, "g_parts_contact", model, ("小车", "trolley", "cart"),
                    ("主梁", "梁", "beam"))
        assert_pass(self, "g_opposite_side", model, ("配重", "counterweight"),
                    ("主梁", "梁", "beam"), 1)
        assert_pass(self, "g_ladder_rungs", model, ("爬梯", "梯", "ladder"), 3)
        assert_pass(self, "g_suspension_hanging", model, ("吊钩", "钩", "hook"),
                    ("吊索", "吊绳", "sling", "cable"), 2)

    def test_merged_legs_are_rejected(self):
        assert_fail(self, "g_legs_separate_min", crane_model(merged_legs=True),
                    ("支腿",), 4, contains="分立足不足")

    def test_single_beam_is_rejected(self):
        assert_fail(self, "g_double_beam", crane_model(single_beam=True),
                    ("主梁",), 2, 10, 2, contains="双梁未成型")

    def test_trolley_gap_is_rejected(self):
        assert_fail(self, "g_parts_contact", crane_model(trolley_gap=True),
                    ("小车",), ("主梁",), contains="未接触")

    def test_counterweight_on_wrong_side_is_rejected(self):
        assert_fail(self, "g_opposite_side", crane_model(cw_same_side=True),
                    ("配重",), ("主梁",), 1, contains="另一侧")

    def test_ladder_without_rungs_is_rejected(self):
        assert_fail(self, "g_ladder_rungs", crane_model(rungs=1),
                    ("爬梯",), 3, contains="梯级")

    # ---- 悬吊物理：单锁扣/双锁扣/倾覆/插入卡口 ----
    def _double_lock_solution(self):
        steps = []

        def add(piece, x, z, layer, rotate=False):
            steps.append({"piece": piece, "x": x, "z": z, "layer": layer,
                          "rotate": rotate, "step": len(steps) + 1})

        add("B1x2", 0, 0, 0)
        add("B1x2", 7, 0, 0)
        add("B1x2", 0, 0, 1)
        add("B1x2", 7, 0, 1)
        add("B2x4", 1, 0, 2, rotate=True)
        add("B1x2", 0, 0, 2)
        add("B1x2", 7, 0, 2)
        add("B1x2", 3, 0, 3)
        add("B1x2", 0, 0, 3)
        add("B1x2", 7, 0, 3)
        add("B2x4", 0, 0, 4, rotate=True)
        return steps

    @staticmethod
    def _suspension_model(steps, hook_cells=None, sling_cells=None):
        from legogod.geometry import step_cells
        solid = set()
        for step in steps:
            for (x, z) in step_cells(step):
                solid.add((x, step["layer"], z))
        hook_cells = hook_cells or {(x, 2, z) for x in range(1, 5) for z in range(2)}
        sling_cells = sling_cells or {(3, 3, z) for z in range(2)}
        parts = [
            make_part("hook", "吊钩", cells=hook_cells),
            make_part("sling", "吊索", cells=sling_cells),
            make_part("beam", "主梁", cells={(x, 4, z) for x in range(4) for z in range(2)}),
            make_part("legs", "支腿", cells={(x, y, z) for x in (0, 7) for y in range(4)
                                            for z in range(2)}),
        ]
        return model_from_cells(solid, 8, 2, 5, parts)

    def test_double_lock_solution_passes_physics(self):
        """双锁扣：合法悬吊子组件（复用 legogod.suspension 的锁扣与抗倾覆判据）。"""
        steps = self._double_lock_solution()
        model = self._suspension_model(steps)
        assert_pass(self, "g_suspension_hanging", model, ("吊钩",), ("吊索",), 2,
                    solution={"steps": steps})

    def test_single_lock_solution_is_rejected(self):
        """10.3 边界：单锁扣违反消旋下界。"""
        steps = self._double_lock_solution()
        for step in steps:
            if step["piece"] == "B1x2" and step["layer"] == 3 and step["x"] == 3:
                step["piece"] = "B1x1"
        model = self._suspension_model(steps, sling_cells={(3, 3, 0)})
        errors = assert_fail(self, "g_suspension_hanging", model, ("吊钩",), ("吊索",), 2,
                             solution={"steps": steps}, contains="锁扣凸点")
        self.assertTrue(any("物理下界" in e for e in errors))
        COUNTEREXAMPLE_COVERED.add("G02 单锁扣被拒")

    def test_tipping_is_rejected_through_physics_check(self):
        """10.3 边界：倾覆。构造吊钩重心偏出锁扣接触面外侧的子组件，并调低单凸点
        抗拔力以验证断言确实接入了 legogod.suspension 的偏心倾覆校核（不改生产逻辑）。"""
        steps = self._double_lock_solution()
        # 吊钩 x1..4 挂在 x1 处的吊索上：重心 x≈3 落在锁扣接触面 (x1..2) 之外
        for step in steps:
            if step["piece"] == "B1x2" and step["layer"] == 3 and step["x"] == 3:
                step["x"] = 1
        model = self._suspension_model(steps, sling_cells={(1, 3, 0), (1, 3, 1)})
        with mock.patch("legogod.suspension.F_CLUTCH_N", 1e-4):
            errors = assert_fail(self, "g_suspension_hanging", model, ("吊钩",), ("吊索",), 2,
                                 solution={"steps": steps})
        self.assertTrue(any("悬吊物理校核未通过" in e for e in errors), errors)
        self.assertTrue(any("倾覆" in e for e in errors), errors)
        COUNTEREXAMPLE_COVERED.add("G02 倾覆被拒")

    def test_insertion_jam_is_rejected(self):
        """10.3 边界：插入卡口（子组件竖直落位路径被已就位零件阻挡）。"""
        steps = self._double_lock_solution()
        for step in steps:
            step["step"] += 1
        steps.insert(0, {"piece": "B1x1", "x": 3, "z": 0, "layer": 5,
                         "rotate": False, "step": 1})
        model = self._suspension_model(steps)
        assert_fail(self, "g_suspension_hanging", model, ("吊钩",), ("吊索",), 2,
                    solution={"steps": steps}, contains="装配卡口")
        COUNTEREXAMPLE_COVERED.add("G02 插入卡口被拒")

    def test_hook_glued_to_beam_without_sling_is_rejected(self):
        """10.3 反例：吊钩贴梁（没有吊索/没有悬空）。"""
        no_sling = model_from_cells(
            {(3, 4, 0), (4, 5, 0)}, 8, 2, 6,
            [make_part("hook", "吊钩", cells={(3, 4, 0)}),
             make_part("beam", "主梁", cells={(x, 5, z) for x in range(4) for z in range(2)})])
        assert_fail(self, "g_suspension_hanging", no_sling, ("吊钩",), ("吊索",), 2,
                    contains="吊索")
        COUNTEREXAMPLE_COVERED.add("吊钩贴梁")

    def test_solid_block_hook_is_rejected(self):
        """10.3 反例：不得用实心方块代替悬空吊钩。"""
        block = {(x, y, z) for y in (0, 1) for x in range(4) for z in range(4)}
        sling = {(x, 2, z) for x in range(4) for z in range(4)}
        model = model_from_cells(block | sling, 6, 6, 3,
                                 [make_part("hook", "吊钩", cells=block),
                                  make_part("sling", "吊索", cells=sling)])
        errors = assert_fail(self, "g_suspension_hanging", model, ("吊钩",), ("吊索",), 2)
        self.assertTrue(any("实心" in e for e in errors), errors)


# ================================================================ G03 落地竖琴
def harp_model(solid_frame=False, strings=8, horizontal_strings=False,
               straight_column=False, lifted_base=False):
    W, D, H = 12, 6, 10
    frame = set()
    for x in range(W):
        frame.add((x, 0, 2))
        frame.add((x, 0, 3))
    for y in range(H):
        frame.add((0, y, 2))
        frame.add((0, y, 3))
    for x in range(W):
        y = round(9 * (W - 1 - x) / (W - 1))
        frame.add((x, y, 2))
        frame.add((x, y, 3))
    if solid_frame:
        frame = {(x, y, z) for x in range(W) for y in range(H) for z in (2, 3)
                 if y <= 9 * (W - 1 - x) / (W - 1)}
    column = set()
    widths = {0: 3, 1: 3, 2: 3, 3: 3, 4: 2, 5: 2, 6: 2, 7: 1, 8: 1, 9: 1}
    if straight_column:
        widths = {y: 3 for y in range(H)}
    for y, wd in widths.items():
        for x in range(wd):
            column.add((x, y, 1))
    if horizontal_strings:
        string_cells = {(x, 4, 4) for x in range(2, 2 + strings)}
    else:
        string_cells = {(x, y, 4) for x in range(2, 2 + strings) for y in range(1, 8)}
    base_y = 4 if lifted_base else 0
    base = {(x, base_y, z) for x in range(W) for z in range(D)}
    soundbox = {(x, y, z) for y in (0, 1) for x in range(1, 10) for z in (2, 3)}
    pedal = {(4, 1, 0), (5, 1, 0)}
    parts = [make_part("frame", "三角框架", cells=frame),
             make_part("column", "琴柱", cells=column),
             make_part("strings", "琴弦", cells=string_cells),
             make_part("soundbox", "共鸣箱", cells=soundbox),
             make_part("base", "底座", cells=base),
             make_part("pedal", "踏板", cells=pedal)]
    cells = frame | column | string_cells | soundbox | base | pedal
    return model_from_cells(cells, W, D, H, parts)


class G03CheckerTest(unittest.TestCase):
    def test_positive_harp(self):
        model = harp_model()
        assert_pass(self, "g_triangle_frame", model, ("三角框架",), 0.6)
        assert_pass(self, "g_strings_vertical_min", model, ("琴弦",), 8)
        assert_pass(self, "g_curved_taper_body", model, ("琴柱",))
        assert_pass(self, "g_grounded_min", model, ("底座",))

    def test_solid_triangle_block_is_rejected(self):
        """10.3 反例（替换原「琴盖平放」）：竖琴三角框架被填成实心三角块（无中空框架）。"""
        assert_fail(self, "g_triangle_frame", harp_model(solid_frame=True),
                    ("三角框架",), 0.6, contains="中空")
        COUNTEREXAMPLE_COVERED.add("竖琴实心三角块")

    def test_missing_strings_are_rejected(self):
        """10.3 反例（替换原「琴盖平放」）：琴弦缺失/数量不足。"""
        assert_fail(self, "g_strings_vertical_min", harp_model(strings=5),
                    ("琴弦",), 8, contains="竖向琴弦不足")
        COUNTEREXAMPLE_COVERED.add("竖琴琴弦缺失")

    def test_horizontal_strings_are_rejected(self):
        assert_fail(self, "g_strings_vertical_min", harp_model(horizontal_strings=True),
                    ("琴弦",), 8)

    def test_straight_column_is_rejected(self):
        assert_fail(self, "g_curved_taper_body", harp_model(straight_column=True),
                    ("琴柱",), contains="弧形")

    def test_lifted_base_is_rejected(self):
        assert_fail(self, "g_grounded_min", harp_model(lifted_base=True), ("底座",),
                    contains="未落地")


# ================================================================ G04 蜻蜓
def dragonfly_model(no_wings=False, one_wing=False, legs=6, thorax_equal=False,
                    eye_color="R"):
    W, D, H = 16, 10, 8
    abdomen = {(x, 3, z) for x in range(10, 16) for z in (4, 5)}
    thorax = {(x, 3, z) for x in range(7, 10) for z in (4, 5)}
    if thorax_equal:
        thorax = {(x, 3, z) for x in range(10, 16) for z in (4, 5)}
    head = {(x, 3, z) for x in range(5, 7) for z in (4, 5)}
    wings = ({(x, 4, z) for x in range(4, 7) for z in (1, 2)}
             | {(x, 4, z) for x in range(4, 7) for z in (7, 8)}
             | {(x, 4, z) for x in range(12, 15) for z in (1, 2)}
             | {(x, 4, z) for x in range(12, 15) for z in (7, 8)})
    if no_wings:
        wings = set()
    if one_wing:
        wings = {(x, 4, z) for x in range(0, 4) for z in range(0, 9)}
    positions = [(5, 2), (7, 2), (9, 2), (5, 6), (7, 6), (9, 6)]
    leg_cells = {(x, 2, z) for (x, z) in positions[:legs]}
    eyes = {(6, 4, 4), (6, 4, 5)}
    parts = [make_part("abdomen", "腹部", cells=abdomen),
             make_part("thorax", "胸部", cells=thorax),
             make_part("head", "头部", cells=head),
             make_part("wings", "翅膀", cells=wings),
             make_part("legs", "腿", cells=leg_cells),
             make_part("eyes", "复眼", cells=eyes, role="surface")]
    cells = abdomen | thorax | head | wings | leg_cells | eyes
    colors = {c: eye_color for c in eyes}
    return model_from_cells(cells, W, D, H, parts, colors, default_color="E")


class G04CheckerTest(unittest.TestCase):
    def test_positive_dragonfly(self):
        model = dragonfly_model()
        assert_pass(self, "part_span_min", model, ("腹部",), 6)
        assert_pass(self, "g_wings_four_paired", model, ("翅膀",), 2, 3)
        assert_pass(self, "g_part_clusters_min", model, ("腿",), 6)
        assert_pass(self, "g_part_ratio_diff", model, ("腹部",), ("胸部",), 1.3)
        assert_pass(self, "g_exposed_contrast_color", model, ("复眼",), 2)

    def test_painted_wings_without_geometry_are_rejected(self):
        """10.3 反例：翅膀涂装（身体上的色块）不算真实翅膀几何。"""
        assert_fail(self, "g_wings_four_paired", dragonfly_model(no_wings=True),
                    ("翅膀",), 2, 3, contains="涂装")
        COUNTEREXAMPLE_COVERED.add("翅膀涂装")

    def test_single_wing_is_rejected(self):
        assert_fail(self, "g_wings_four_paired", dragonfly_model(one_wing=True),
                    ("翅膀",), 2, 3)

    def test_three_legs_are_rejected(self):
        assert_fail(self, "g_part_clusters_min", dragonfly_model(legs=3),
                    ("腿",), 6, contains="成组细腿")

    def test_equal_thorax_abdomen_ratio_is_rejected(self):
        assert_fail(self, "g_part_ratio_diff", dragonfly_model(thorax_equal=True),
                    ("腹部",), ("胸部",), 1.3, contains="比例未区分")

    def test_eye_same_color_as_body_is_rejected(self):
        assert_fail(self, "g_exposed_contrast_color", dragonfly_model(eye_color="E"),
                    ("复眼",), 2, contains="异色")

    def test_short_abdomen_is_rejected(self):
        """腹部纵向长跨：细长腹部被压缩成胸部长度的短块必须被拒。"""
        short = {(x, 3, z) for x in range(12, 15) for z in (4, 5)}
        model = model_from_cells(short, 16, 10, 8,
                                 [make_part("abdomen", "腹部", cells=short)])
        assert_fail(self, "part_span_min", model, ("腹部",), 6, contains="长跨结构未成型")


# ================================================================ G05 双峰骆驼
def camel_model(merged_humps=False, single_hump=False, short_neck=False, legs=4):
    W, D, H = 16, 8, 8
    body = {(x, y, z) for y in (1, 2) for x in range(3, 13) for z in range(2, 6)}
    if merged_humps:
        humps = {(x, y, z) for x in range(4, 11) for y in range(3, 7) for z in (3, 4)}
    elif single_hump:
        humps = {(x, y, z) for x in range(4, 7)
                 for y in range(3, 3 + 6 - (x - 4)) for z in (3, 4)}
    else:
        humps = ({(x, y, z) for x in range(4, 6) for y in range(3, 7) for z in (3, 4)}
                 | {(x, y, z) for x in range(9, 11) for y in range(3, 7) for z in (3, 4)})
    neck = {(13, 2, 3), (13, 3, 3), (14, 4, 3), (14, 5, 3), (14, 6, 3), (14, 7, 3)}
    if short_neck:
        neck = {(13, 2, 3), (13, 3, 3)}
    positions = [(4, 2), (7, 2), (4, 5), (7, 5)][:legs]
    leg_cells = {(x, y, z) for (x, z) in positions for y in (0, 1)}
    tail = {(2, 2, 3)}
    ears = {(13, 7, 4), (14, 7, 4)}
    parts = [make_part("body", "身体", cells=body), make_part("hump", "驼峰", cells=humps),
             make_part("neck", "长颈", cells=neck), make_part("legs", "腿", cells=leg_cells),
             make_part("tail", "尾巴", cells=tail), make_part("ears", "耳朵", cells=ears)]
    cells = body | humps | neck | leg_cells | tail | ears
    return model_from_cells(cells, W, D, H, parts)


class G05CheckerTest(unittest.TestCase):
    def test_positive_camel(self):
        model = camel_model()
        assert_pass(self, "g_twin_peaks", model, ("驼峰",), 2, 2)
        assert_pass(self, "g_neck_raise", model, ("长颈",), ("身体",), 4, 2)
        assert_pass(self, "g_legs_separate_min", model, ("腿",), 4)

    def test_single_hump_is_rejected(self):
        """10.3 反例：单峰骆驼。"""
        assert_fail(self, "g_twin_peaks", camel_model(single_hump=True),
                    ("驼峰",), 2, 2)
        COUNTEREXAMPLE_COVERED.add("单峰骆驼")

    def test_merged_humps_are_rejected(self):
        assert_fail(self, "g_twin_peaks", camel_model(merged_humps=True),
                    ("驼峰",), 2, 2, contains="低凹")

    def test_short_neck_is_rejected(self):
        assert_fail(self, "g_neck_raise", camel_model(short_neck=True),
                    ("长颈",), ("身体",), 4, 2)

    def test_three_legs_are_rejected(self):
        assert_fail(self, "g_legs_separate_min", camel_model(legs=3), ("腿",), 4)


# ================================================================ G06 土星展示模型
def saturn_model(fill_ring=False, flat_ring=False, narrow_ring=False):
    import math
    W = D = 32
    H = 10
    sphere = set()
    for y, r in {3: 1, 4: 2, 5: 3, 6: 2}.items():
        for x in range(W):
            for z in range(D):
                if (x - 16) ** 2 + (z - 16) ** 2 <= r * r:
                    sphere.add((x, y, z))
    ring = set()
    inner, outer = (0.0, 15.0) if fill_ring else (5.0, 15.0)
    if narrow_ring:
        inner, outer = 5.0, 7.0
    for x in range(W):
        for z in range(D):
            rr = math.hypot(x - 16, z - 16)
            if inner <= rr <= outer:
                y0 = 6 if flat_ring else 6 + int(round((x - 16) / 6.0))
                ring.add((x, y0, z))
                if not flat_ring:
                    ring.add((x, y0 + 1, z))
    support = {(x, y, z) for y in (1, 2) for x in (15, 16, 17) for z in (15, 16, 17)}
    base = {(x, 0, z) for x in range(10, 23) for z in range(10, 23)}
    if fill_ring:
        ring = {(x, y, z) for x in range(W) for z in range(D) for y in (4, 5)
                if math.hypot(x - 16, z - 16) <= 15.0}
    parts = [make_part("sphere", "球体", cells=sphere), make_part("ring", "环带", cells=ring),
             make_part("support", "支架", cells=support), make_part("base", "底座", cells=base)]
    cells = sphere | ring | support | base
    return model_from_cells(cells, W, D, H, parts)


class G06CheckerTest(unittest.TestCase):
    def test_positive_saturn(self):
        model = saturn_model()
        assert_pass(self, "g_sphere_profile", model, ("球体",))
        assert_pass(self, "g_ring_geometry", model, ("环带",), ("球体",))
        assert_pass(self, "g_parts_contact", model, ("球体",), ("支架",))

    def test_box_sphere_profile_is_rejected(self):
        """球体不得是等截面方块（多截面球形轮廓要求逐层收分）。"""
        cube = {(x, y, z) for y in range(3, 7) for x in range(13, 20) for z in range(13, 20)}
        model = model_from_cells(cube, 32, 32, 10,
                                 [make_part("sphere", "球体", cells=cube)])
        assert_fail(self, "g_sphere_profile", model, ("球体",), contains="收放")

    def test_filled_ring_gap_is_rejected(self):
        """10.3 反例：环缝填实（实心圆盘同时填满球体与环缝）。"""
        errors = assert_fail(self, "g_ring_geometry", saturn_model(fill_ring=True),
                             ("环带",), ("球体",))
        self.assertTrue(any("中央未留空" in e or "空隙" in e for e in errors), errors)
        COUNTEREXAMPLE_COVERED.add("环缝填实")

    def test_flat_ring_is_rejected(self):
        assert_fail(self, "g_ring_geometry", saturn_model(flat_ring=True),
                    ("环带",), ("球体",), contains="倾角")

    def test_narrow_ring_is_rejected(self):
        assert_fail(self, "g_ring_geometry", saturn_model(narrow_ring=True),
                    ("环带",), ("球体",), contains="环宽不足")


# ================================================================ G07 雪地摩托
def snowmobile_model(no_skis=False, one_ski=False, short_track=False, buried_windshield=False):
    W, D, H = 12, 16, 8
    body = {(x, y, z) for y in range(1, 6) for x in range(2, 10) for z in range(3, 14)}
    skis = ({(x, 0, z) for x in (2, 3) for z in range(0, 12)}
            | {(x, 0, z) for x in (8, 9) for z in range(0, 12)})
    if no_skis:
        skis = set()
    if one_ski:
        skis = {(x, 0, z) for x in range(2, 10) for z in range(0, 6)}
    track = {(x, y, z) for y in (0, 1) for x in range(4, 8) for z in range(4, 16)}
    if short_track:
        track = {(x, y, z) for y in (0, 1) for x in range(4, 8) for z in range(4, 8)}
    seat = {(x, 6, z) for x in range(3, 9) for z in range(6, 11)}
    ws = {(x, 5, z) for x in range(3, 9) for z in (3, 4)}
    if buried_windshield:
        ws = {(x, 3, z) for x in range(3, 9) for z in (3, 4)}
    handle = {(2, 6, 3), (9, 6, 3)}
    light = {(3, 5, 3)}
    parts = [make_part("ski", "滑雪板", cells=skis), make_part("track", "履带", cells=track),
             make_part("body", "车身", cells=body), make_part("seat", "座椅", cells=seat),
             make_part("ws", "挡风玻璃", cells=ws), make_part("handle", "车把", cells=handle),
             make_part("light", "前灯", cells=light)]
    cells = body | skis | track | seat | ws | handle | light
    colors = {c: "B" for c in ws}
    return model_from_cells(cells, W, D, H, parts, colors, default_color="R")


class G07CheckerTest(unittest.TestCase):
    def test_positive_snowmobile(self):
        model = snowmobile_model()
        assert_pass(self, "g_skis_two_extend", model, ("滑雪板",), ("车身",), 1)
        assert_pass(self, "g_track_long_distinct", model, ("履带",), ("车轮",), 6)
        assert_pass(self, "g_exposed_contrast_color", model, ("挡风",), 3, ("车身",), True)

    def test_fixed_wheels_instead_of_skis_are_rejected(self):
        """10.3 反例：用两个固定车轮代替滑雪板（滑雪板部位缺失）。"""
        assert_fail(self, "g_skis_two_extend", snowmobile_model(no_skis=True),
                    ("滑雪板",), ("车身",), 1, contains="滑雪板")
        COUNTEREXAMPLE_COVERED.add("滑雪板换车轮")

    def test_single_merged_ski_is_rejected(self):
        assert_fail(self, "g_skis_two_extend", snowmobile_model(one_ski=True),
                    ("滑雪板",), ("车身",), 1, contains="未分开")

    def test_short_track_is_rejected(self):
        assert_fail(self, "g_track_long_distinct", snowmobile_model(short_track=True),
                    ("履带",), ("车轮",), 6, contains="长跨不足")

    def test_buried_windshield_is_rejected(self):
        assert_fail(self, "g_exposed_contrast_color", snowmobile_model(buried_windshield=True),
                    ("挡风",), 3, ("车身",), True, contains="外露异色")


# ================================================================ G08 老式手推独轮车
def wheelbarrow_model(filled_tub=False, one_handle=False, square_wheel=False,
                      extra_wheel=False):
    W, D, H = 8, 14, 8
    wheel = {(3, y, z) for y in range(5) for z in range(5)
             if (y - 2) ** 2 + (z - 2) ** 2 <= 2.2 ** 2}
    if square_wheel:
        wheel = {(3, y, z) for y in range(5) for z in range(5)}
    if extra_wheel:
        wheel |= {(5, y, z) for y in range(5) for z in range(5)
                  if (y - 2) ** 2 + (z - 2) ** 2 <= 2.2 ** 2}
    axle = {(x, 2, 2) for x in (2, 3, 4)}
    handles = ({(1, 3, z) for z in range(5, 13)}
               | (set() if one_handle else {(6, 3, z) for z in range(5, 13)}))
    if filled_tub:
        tub = {(x, y, z) for y in range(3, 6) for x in range(2, 6) for z in range(5, 10)}
    else:
        tub = ({(x, 3, z) for x in range(2, 6) for z in range(5, 10)}
               | {(x, y, z) for y in (4, 5) for x in range(2, 6) for z in range(5, 10)
                  if x in (2, 5) or z in (5, 9)})
    stand = {(2, y, 10) for y in range(4)} | {(5, y, 10) for y in range(4)}
    parts = [make_part("wheel", "车轮", cells=wheel), make_part("axle", "轮轴", cells=axle),
             make_part("handle", "把手", cells=handles), make_part("tub", "斗体", cells=tub),
             make_part("stand", "支脚", cells=stand)]
    cells = wheel | axle | handles | tub | stand
    return model_from_cells(cells, W, D, H, parts)


class G08CheckerTest(unittest.TestCase):
    def test_positive_wheelbarrow(self):
        model = wheelbarrow_model()
        assert_pass(self, "g_round_wheels", model, ("车轮",), 1, 1)
        assert_pass(self, "g_paired_across_axis", model, ("把手",), "x")
        assert_pass(self, "g_cup_open_top", model, ("斗体",))
        assert_pass(self, "g_cup_cavity_min", model, ("斗体",), 4)
        assert_pass(self, "g_legs_separate_min", model, ("支脚",), 2)
        assert_pass(self, "g_parts_contact", model, ("车轮",), ("轮轴",))

    def test_filled_tub_is_rejected(self):
        """10.3 反例（替换原「车架实心化」）：独轮车斗体填实。"""
        assert_fail(self, "g_cup_open_top", wheelbarrow_model(filled_tub=True),
                    ("斗体",), contains="顶部封死")
        assert_fail(self, "g_cup_cavity_min", wheelbarrow_model(filled_tub=True),
                    ("斗体",), 4, contains="填实")
        COUNTEREXAMPLE_COVERED.add("独轮车斗体填实")

    def test_single_handle_is_rejected(self):
        """10.3 反例（替换原「车架实心化」）：把手单侧。"""
        assert_fail(self, "g_paired_across_axis", wheelbarrow_model(one_handle=True),
                    ("把手",), "x")
        COUNTEREXAMPLE_COVERED.add("独轮车把手单侧")

    def test_square_wheel_is_rejected(self):
        """10.3 反例（替换原「车架实心化」）：圆形车轮换成方块。"""
        assert_fail(self, "g_round_wheels", wheelbarrow_model(square_wheel=True),
                    ("车轮",), 1, 1, contains="不近似圆形")
        COUNTEREXAMPLE_COVERED.add("独轮车车轮换方块")

    def test_two_wheels_are_rejected(self):
        assert_fail(self, "g_round_wheels", wheelbarrow_model(extra_wheel=True),
                    ("车轮",), 1, 1, contains="单个圆形车轮")


# ================================================================ G09 极简笔筒
def pen_cup_model(sealed_top=False, side_hole=False, bottom_hole=False, filled=False,
                  same_pens=False):
    W = D = 8
    H = 7
    if filled:
        cup = {(x, y, z) for y in range(6) for x in range(W) for z in range(D)}
    else:
        cup = {(x, 0, z) for x in range(W) for z in range(D)}
        cup |= {(x, y, z) for y in range(1, 6) for x in range(W) for z in range(D)
                if x in (0, W - 1) or z in (0, D - 1)}
    if sealed_top:
        cup |= {(x, 5, z) for x in range(W) for z in range(D)}
    if side_hole:
        cup -= {(0, 3, 0), (0, 3, 1)}
    if bottom_hole:
        cup -= {(x, 0, z) for x in range(3, 5) for z in range(3, 5)}
    if same_pens:
        pens = {(x, y, 2) for x in (2, 4, 6) for y in range(1, 4)}
        colors = {c: "R" for c in pens}
    else:
        pens = ({(2, y, 2) for y in range(1, 4)}
                | {(4, y, 2) for y in range(1, 5)}
                | {(6, y, 2) for y in range(1, 6)})
        colors = {(2, y, 2): "R" for y in range(1, 4)}
        colors.update({(4, y, 2): "B" for y in range(1, 5)})
        colors.update({(6, y, 2): "Y" for y in range(1, 6)})
    parts = [make_part("cup", "杯体", cells=cup), make_part("pen", "笔", cells=pens)]
    cells = cup | pens
    return model_from_cells(cells, W, D, H, parts, colors, default_color="W")


class G09CheckerTest(unittest.TestCase):
    def test_positive_pen_cup(self):
        model = pen_cup_model()
        assert_pass(self, "g_cup_open_top", model, ("杯体",))
        assert_pass(self, "g_cup_bottom_closed", model, ("杯体",))
        assert_pass(self, "g_cup_cavity_min", model, ("杯体",), 4)
        assert_pass(self, "g_pens_three_distinct", model, ("笔",), 3, 3)
        assert_pass(self, "g_not_solid_block", model, ("杯体",), 0.75)

    def test_sealed_top_with_side_hole_is_rejected(self):
        """10.3 边界：顶部封死但侧面有洞，不得误判为顶部敞开。"""
        errors = run_check("g_cup_open_top", pen_cup_model(sealed_top=True, side_hole=True),
                          ("杯体",))
        self.assertTrue(any("顶部封死" in e for e in errors), errors)
        self.assertTrue(any("侧面有洞" in e for e in errors), errors)
        COUNTEREXAMPLE_COVERED.add("G09 顶部封死侧面有洞不被误判")

    def test_open_top_positive_distinguishes_side_hole(self):
        """同样的侧面洞，只要顶部敞开就必须通过（证明不是按洞数量草率判定）。"""
        assert_pass(self, "g_cup_open_top", pen_cup_model(side_hole=True), ("杯体",))

    def test_bottom_hole_is_rejected(self):
        assert_fail(self, "g_cup_bottom_closed", pen_cup_model(bottom_hole=True),
                    ("杯体",), contains="杯底未封闭")
        COUNTEREXAMPLE_COVERED.add("杯底漏空")

    def test_filled_cup_is_rejected(self):
        """10.3 反例：笔筒填实（小模型堆实心方块）。"""
        assert_fail(self, "g_cup_cavity_min", pen_cup_model(filled=True),
                    ("杯体",), 4, contains="填实")
        assert_fail(self, "g_not_solid_block", pen_cup_model(filled=True),
                    ("杯体",), 0.75, contains="实心方块")
        COUNTEREXAMPLE_COVERED.add("笔筒填实")

    def test_pens_same_color_and_height_are_rejected(self):
        assert_fail(self, "g_pens_three_distinct", pen_cup_model(same_pens=True),
                    ("笔",), 3, 3, contains="颜色不可区分")


# ================================================================ G10 模糊需求小鸟
def bird_model(no_wings=False, one_leg=False, block=False, beak_color="Y",
               buried_beak=False):
    W, D, H = 10, 12, 8
    if block:
        cells = {(x, y, z) for y in range(H) for x in range(4, 8) for z in range(4, 10)}
        return model_from_cells(cells, W, D, H, [make_part("body", "身体", cells=cells)])
    body = {(x, y, z) for y in range(2, 5) for x in range(3, 7) for z in range(3, 9)}
    head = {(x, y, z) for y in (4, 5) for x in range(3, 7) for z in range(1, 3)}
    beak = {(4, 5, 0), (5, 5, 0)}
    if buried_beak:
        beak = {(4, 3, 4), (5, 3, 4)}
    wings = set()
    if not no_wings:
        wings = ({(x, 4, z) for x in range(0, 3) for z in range(3, 7)}
                 | {(x, 4, z) for x in range(7, 10) for z in range(3, 7)})
    tail = {(x, 3, z) for x in range(3, 7) for z in (9, 10)}
    legs = {(3, y, 5) for y in (0, 1)}
    if not one_leg:
        legs |= {(6, y, 5) for y in (0, 1)}
    parts = [make_part("body", "身体", cells=body), make_part("head", "头部", cells=head),
             make_part("beak", "喙", cells=beak, role="surface"),
             make_part("wings", "翅膀", cells=wings), make_part("tail", "尾巴", cells=tail),
             make_part("legs", "腿", cells=legs)]
    cells = body | head | beak | wings | tail | legs
    colors = {c: beak_color for c in beak}
    return model_from_cells(cells, W, D, H, parts, colors, default_color="E")


class G10CheckerTest(unittest.TestCase):
    def test_positive_bird_geometry(self):
        model = bird_model()
        assert_pass(self, "both_sides", model, ("翅膀",))
        assert_pass(self, "g_exposed_contrast_color", model, ("喙",), 2)
        assert_pass(self, "g_legs_separate_min", model, ("腿",), 2)
        assert_pass(self, "g_not_solid_block", model, (), 0.75)
        assert_pass(self, "g_bird_geometry", model)

    def test_missing_wings_are_rejected(self):
        """10.3 反例：小鸟缺翼。"""
        assert_fail(self, "both_sides", bird_model(no_wings=True), ("翅膀",),
                    contains="成对")
        COUNTEREXAMPLE_COVERED.add("小鸟缺翼")

    def test_single_leg_is_rejected(self):
        assert_fail(self, "g_legs_separate_min", bird_model(one_leg=True),
                    ("腿",), 2, contains="分立足不足")

    def test_featureless_block_is_rejected(self):
        """10.3 反例：不得因描述简短而生成无特征方块。"""
        assert_fail(self, "g_not_solid_block", bird_model(block=True), (), 0.75,
                    contains="实心方块")
        assert_fail(self, "g_bird_geometry", bird_model(block=True), contains="无特征方块")
        COUNTEREXAMPLE_COVERED.add("小鸟无特征方块")

    def test_beak_same_color_as_body_is_rejected(self):
        assert_fail(self, "g_exposed_contrast_color", bird_model(beak_color="E"),
                    ("喙",), 2, contains="异色")

    def test_buried_beak_is_rejected(self):
        assert_fail(self, "g_exposed_contrast_color", bird_model(buried_beak=True),
                    ("喙",), 2, contains="外露")


# ---------------------------------------------------------------- G10 模糊需求交互边界
PLAN_ARGS = {
    "features": ["身体", "头", "喙", "双翼", "尾巴", "两条腿"],
    "structure": "小型鸟类造型，单一体块+成对双翼",
    "complexity": "简单",
    "requirementSummary": "一只小鸟",
    "grid": {"w": 10, "d": 10},
    "layers": 5,
    "targetBlocks": 120,
    "estimatedVoxels": 480,
    "estimatedParts": 120,
    "parts": [
        {"id": "body", "name": "身体", "required": True, "source": "小鸟", "role": "solid"},
        {"id": "wings", "name": "双翼", "required": True, "source": "小鸟", "role": "solid"},
        {"id": "beak", "name": "喙", "required": True, "source": "小鸟", "role": "surface"},
    ],
}
PLAN_RESPONSE = {"content": json.dumps({"action": "plan_design", "args": PLAN_ARGS},
                                       ensure_ascii=False),
                 "requests": 1, "finish": "stop"}
ASK_RESPONSE = {"content": json.dumps({"action": "ask_user",
                                       "args": {"question": "小鸟要什么颜色？"}},
                                      ensure_ascii=False),
                "requests": 1, "finish": "stop"}


class FuzzyRequirementWorkflowTest(unittest.TestCase):
    """G10 模糊需求：无追问继续 / 最多一次合理默认决策 / 取消 / 空描述不误提交。

    全部使用 workflow._Chain + 注入 chat_fn（不调用真实 LLM）。
    """

    def _chain(self, chat_fn, desc="一只小鸟", cancel=None):
        from legogod.workflow import _Chain
        events = []

        def log(kind, text, meta=None):
            events.append((kind, text))

        chain = _Chain(desc, chat_fn=chat_fn, log=log, cancel=cancel)
        return chain, events

    def test_ambiguous_desc_continues_without_question(self):
        """无追问继续：模型直接给 plan 时系统不强制追问，按合理比例继续。"""
        from legogod import workflow_phases as wph
        calls = []

        def chat(messages, **kw):
            calls.append(1)
            return dict(PLAN_RESPONSE)

        chain, events = self._chain(chat)
        args = wph.run_plan_phase(chain)
        self.assertEqual(args, PLAN_ARGS)
        self.assertFalse(chain.used_ask)
        self.assertEqual(len(calls), 1)
        self.assertFalse([e for e in events if e[0] == "ask"])
        self.assertTrue(chain.parts_norm)

    def test_at_most_one_default_decision_then_continue(self):
        """最多一次合理默认决策：允许问一次并注入默认决策，随后必须继续（无用户在线）。"""
        from legogod import workflow_phases as wph
        chain, events = self._chain(lambda messages, **kw: dict(PLAN_RESPONSE))
        wph._do_ask(chain, {"question": "小鸟要什么颜色？"})
        self.assertTrue(chain.used_ask)
        answers = [e for e in events if e[0] == "answer"]
        self.assertEqual(len(answers), 1)
        self.assertIn("按常见合理比例", answers[0][1])
        # 默认决策作为用户回答注入消息，模型据此继续，不需要用户在线
        self.assertTrue(any(m.get("role") == "user" and "按常见合理比例" in str(m.get("content"))
                            for m in chain.messages))
        # 注入默认决策后仍能继续规划（不要求模糊需求必须先追问才生成）
        args = wph.run_plan_phase(chain)
        self.assertEqual(args, PLAN_ARGS)

    def test_repeated_question_gets_no_second_default_decision(self):
        """重复追问：第二次不再注入任何默认决策（只提示只能问一次），总数恒为 1。"""
        from legogod import workflow_phases as wph
        chain, events = self._chain(lambda messages, **kw: dict(PLAN_RESPONSE))
        wph._do_ask(chain, {"question": "第一个问题"})
        wph._do_ask(chain, {"question": "第二个问题"})
        answers = [e for e in events if e[0] == "answer"]
        self.assertEqual(len(answers), 1, "整个任务最多一次合理默认决策")
        self.assertTrue(any("只能使用一次" in str(m.get("content")) for m in chain.messages))
        self.assertTrue(any(e[0] == "ask" and e[1] == "第二个问题" for e in events))

    def test_cancel_before_planning_does_not_submit(self):
        import threading
        from legogod import workflow_phases as wph
        from legogod.workflow import CancelledError
        cancel = threading.Event()
        cancel.set()
        called = []

        def chat(messages, **kw):
            called.append(1)
            return dict(PLAN_RESPONSE)

        chain, _events = self._chain(chat, cancel=cancel)
        with self.assertRaises(CancelledError):
            wph.run_plan_phase(chain)
        self.assertEqual(called, [], "取消后不得再发起模型调用/提交任务")

    def test_empty_desc_is_rejected_by_build_api(self):
        """空描述不误提交：/api/build 在创建任务前 400 拒绝（不创建任务/不触发 LLM）。"""
        from _helpers import ApiFixture
        started = []
        with ApiFixture() as fixture:
            fixture.set_runner(lambda desc, **kw: started.append(desc) or
                               {"ok": True, "outcome": "fast_success"})
            code, body, _ = fixture.post_json("/api/build", {"desc": "   "})
            self.assertEqual(code, 400)
            self.assertEqual(body["error"], "desc 不能为空")
            self.assertEqual(len(fixture.store), 0, "空描述不得创建任务")
        self.assertEqual(started, [], "空描述不得启动生成调用")

    def test_non_empty_desc_is_still_submitted(self):
        from _helpers import ApiFixture
        started = []

        def runner(desc, **kw):
            started.append(desc)
            return {"ok": True, "outcome": "fast_success"}

        with ApiFixture() as fixture:
            fixture.set_runner(runner)
            code, body, _ = fixture.post_json("/api/build", {"desc": "一只小鸟"})
            self.assertEqual(code, 200)
            self.assertTrue(body["id"])
            fixture.wait_status(body["id"], ("done",))
        self.assertEqual(started, ["一只小鸟"])


# ---------------------------------------------------------------- 覆盖统计（最后执行）
class PensThreeDistinctTest(unittest.TestCase):
    """G09 三支笔（2026-11-03 复核）：宿主部位排除、独立笔形/颜色/高度计数，反例仍失败。"""

    def _model(self, pens, host=True):
        cells, colors, parts = set(), {}, []
        if host:
            host_cells = {(x, 0, z) for x in range(7) for z in range(7)
                          if x in (0, 6) or z in (0, 6)}
            cells |= host_cells
            for c in host_cells:
                colors[c] = "W"
            parts.append(make_part("cup", "笔筒底座", cells=host_cells))
        for name, (x, z), top, color in pens:
            pen_cells = {(x, y, z) for y in range(1, top + 1)}
            cells |= pen_cells
            for c in pen_cells:
                colors[c] = color
            parts.append(make_part(name, name, cells=pen_cells))
        return model_from_cells(cells, 7, 7, parts=parts, colors=colors)

    def test_three_pens_pass_while_host_excluded(self):
        """笔筒底座 + 三支不同颜色/高度的笔：宿主不算笔，应通过。"""
        model = self._model([("高笔", (1, 1), 5, "I"), ("中笔", (3, 1), 4, "R"),
                             ("矮笔", (5, 1), 3, "Y")])
        self.assertEqual(run_check("g_pens_three_distinct", model, ("笔", "pen"), 3, 3), [])

    def test_missing_pen_still_fails(self):
        model = self._model([("高笔", (1, 1), 5, "I"), ("中笔", (3, 1), 4, "R")])
        errors = run_check("g_pens_three_distinct", model, ("笔", "pen"), 3, 3)
        self.assertTrue(any("笔的数量不足" in e for e in errors), errors)

    def test_same_color_pens_still_fail(self):
        model = self._model([("高笔", (1, 1), 5, "R"), ("中笔", (3, 1), 4, "R"),
                             ("矮笔", (5, 1), 3, "R")])
        errors = run_check("g_pens_three_distinct", model, ("笔", "pen"), 3, 3)
        self.assertTrue(any("颜色不可区分" in e for e in errors), errors)

    def test_same_height_pens_still_fail(self):
        model = self._model([("高笔", (1, 1), 4, "I"), ("中笔", (3, 1), 4, "R"),
                             ("矮笔", (5, 1), 4, "Y")])
        errors = run_check("g_pens_three_distinct", model, ("笔", "pen"), 3, 3)
        self.assertTrue(any("高度不可区分" in e for e in errors), errors)

    def test_host_only_is_not_counted_as_pens(self):
        """只有笔筒/杯身/底座（名称都含「笔」或宿主词）时不得算成笔。"""
        model = self._model([])
        errors = run_check("g_pens_three_distinct", model, ("笔", "pen"), 3, 3)
        self.assertTrue(any("未找到独立笔部位" in e for e in errors), errors)


class ZCoverageTest(unittest.TestCase):
    def test_every_special_checker_has_positive_and_negative(self):
        expected = {spec[0] for case in G_CASES for spec in case["checks"]
                    if spec[0].startswith("g_")}
        missing_pass = [n for n in expected if COVERAGE.get(n, {}).get("pass", 0) < 1]
        missing_fail = [n for n in expected if COVERAGE.get(n, {}).get("fail", 0) < 1]
        self.assertEqual(missing_pass, [], f"以下专项断言缺正例：{missing_pass}")
        self.assertEqual(missing_fail, [], f"以下专项断言缺反例：{missing_fail}")
        # 方案 12.1：G 组每例专项断言均有正例和反例
        for case in G_CASES:
            self.assertTrue(case["checks"], case["id"])

    def test_10_3_counterexamples_all_rejected(self):
        required = {
            "拱洞涂黑", "吊钩贴梁", "竖琴实心三角块", "竖琴琴弦缺失", "翅膀涂装",
            "单峰骆驼", "环缝填实", "滑雪板换车轮", "独轮车斗体填实", "独轮车把手单侧",
            "独轮车车轮换方块", "笔筒填实", "小鸟缺翼",
            "G02 单锁扣被拒", "G02 倾覆被拒", "G02 插入卡口被拒",
            "G09 顶部封死侧面有洞不被误判",
        }
        self.assertEqual(required - COUNTEREXAMPLE_COVERED, set(),
                         f"10.3 反例未覆盖：{required - COUNTEREXAMPLE_COVERED}")


if __name__ == "__main__":
    unittest.main()
