# -*- coding: utf-8 -*-
"""新 20 例（N01–N20）案例库 / 断言模块的确定性回归测试（不调用真实模型/浏览器/求解）。

覆盖：
  1. 案例注册纪律：20 例、编号 N01–N20 顺序、id/原文/主题唯一、字段完整、目标块数
     与需求原文逐字一致、min_voxels 口径 = 2×目标块数、stress/历史失败提示合法；
  2. 断言配置：require_parts/checks 非空、所有检查名都能解析（N 新检查器 → G 组 →
     20 例通用检查器）、本轮 6 个新检查器全部被案例真实引用且带参数；
  3. 主题新颖性审计：公开审计语料 fixture + C/H/G 案例池 0 冲突；注入历史需求/主题词/
     模型名/案例池撞题必须报错；本组自己跑过的需求被排除（防自我撞题）；缺语料
     --audit 必须 exit 2（--allow-empty 仅本地显式放行）；
  4. CLI：`--list` / `--audit` 可跑且输出 20 例、冲突 0；默认输出 JSON；
     GBK(cp936) 控制台下 --list/--audit 必须直接跑通（不因 emoji/编码崩溃）；
  5. check_objects_n：任务成功/目标块数 50% 容差边界/部位下限/回归档不判失败/
     最终门禁 finalGateReplay 重放口径（ok=False 判失败、ok=True 不误报）/
     未知检查与检查异常可读失败；任务失败与无产物不抛未捕获异常；
  6. 新检查器并入 G_CHECKS 后 check_objects_g 可执行（只读复用接线）；
  7. 6 个新检查器（扇形尾屏/触手方位/悬索垂度/倾斜塔/轮径比/气囊-吊篮关系）
     每个至少 1 个正例 + 1 个反例，并有覆盖统计兜底。
"""
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import unittest
from unittest import mock

from tools.e2e_assert import _colored_cells
from tools.e2e_assert_20 import _part_counts
from tools.e2e_assert_g import G_CHECKS, _solid_cells, check_objects_g
from tools.e2e_assert_new20 import (N_CHECKS, N_NEW_CHECK_NAMES, check_objects_n,
                                     resolve_check)
from tools.e2e_cases_20 import all_cases as all_ch_cases
from tools.e2e_cases_g import G_CASES
from tools.e2e_cases_new20 import (N_CASES, N_TARGET_TOLERANCE, STRESS_CATEGORIES,
                                     all_n_cases, audit_n_cases, find_n_case,
                                     parse_target_blocks)
from tools.e2e_cases_new20 import main as new20_main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需求原文里必须至少出现两类结构特征（设计口径：中空/斜面/悬挑/成对/多层收分/曲面）
STRUCTURE_MARKERS = ("中空", "斜面", "悬挑", "成对", "多层", "收分", "递收", "曲面", "弧",
                     "扇形", "卷", "螺旋", "镂空", "贯通", "张开", "展开", "鼓起", "圆鼓",
                     "倾斜", "分节", "斜撑", "平展", "错落", "垂下", "悬挂", "弯垂", "条纹")
FORBIDDEN_DESC_WORDS = ("透明", "水印", "文字", "标签", "logo", "Logo", "二维码")


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
    return {"name": "测试N", "grid": {"w": w, "d": d}, "totalVoxels": len(cells),
            "slopeVoxels": 0, "layers": layers, "parts": parts or [],
            "ops": ops or [], "track": track}


def ctx(model, solution=None):
    return {"model": model, "solution": solution or {"validation": {"ok": True}},
            "counts": _part_counts(model), "colored": _colored_cells(model),
            "solid": _solid_cells(model)}


# 正/反例覆盖统计：N_CHECKS 里每个新检查器都必须有正例与反例各 ≥1 次
COVERAGE = {}


def run_check(name, model, *args, solution=None):
    errors = N_CHECKS[name](ctx(model, solution), *args)
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


# ---------------------------------------------------------------- 1. 案例注册纪律
EXPECTED_IDS = [f"N{i:02d}" for i in range(1, 21)]
EXPECTED_TARGETS = {
    "N01": 400, "N02": 260, "N03": 340, "N04": 300, "N05": 280, "N06": 250,
    "N07": 320, "N08": 380, "N09": 440, "N10": 430, "N11": 420, "N12": 410,
    "N13": 390, "N14": 360, "N15": 350, "N16": 330, "N17": 310, "N18": 290,
    "N19": 270, "N20": 240,
}
EXPECTED_SUBJECTS = {
    "N01": "孔雀", "N02": "蝴蝶", "N03": "章鱼", "N04": "螃蟹", "N05": "鹦鹉",
    "N06": "海马", "N07": "蝎子", "N08": "飞马", "N09": "帕特农神庙", "N10": "泰姬陵",
    "N11": "圣瓦西里大教堂", "N12": "悬索桥", "N13": "比萨斜塔", "N14": "旋转木马",
    "N15": "双翼飞机", "N16": "农场拖拉机", "N17": "塔式起重机", "N18": "月球车",
    "N19": "管风琴", "N20": "热气球",
}


class CaseRegistryTest(unittest.TestCase):
    def test_twenty_unique_cases_in_order(self):
        self.assertEqual(len(N_CASES), 20)
        self.assertEqual([c["id"] for c in N_CASES], EXPECTED_IDS)
        self.assertEqual(len(all_n_cases()), 20)
        self.assertIsNot(all_n_cases(), N_CASES)  # 返回副本，防止外部改单源
        self.assertEqual(len({c["desc"] for c in N_CASES}), 20)
        self.assertEqual(len({c["subject"] for c in N_CASES}), 20)
        self.assertEqual(len({c["name"] for c in N_CASES}), 20)
        self.assertEqual({c["id"]: c["subject"] for c in N_CASES}, EXPECTED_SUBJECTS)

    def test_every_case_has_required_fields(self):
        for case in N_CASES:
            for key in ("id", "name", "subject", "desc", "complexity", "stress",
                        "historical_failure_hint", "target_blocks", "min_parts",
                        "min_solid_parts", "min_voxels", "min_ops",
                        "require_parts", "checks"):
                self.assertIn(key, case, case["id"])
            self.assertTrue(case["complexity"], case["id"])
            self.assertTrue(case["historical_failure_hint"], case["id"])
            self.assertIn("历史", case["historical_failure_hint"], case["id"])
            # 两档复杂度与历史失败针对性：1–3 个压力类别，只能取允许集合
            self.assertGreaterEqual(len(case["stress"]), 1, case["id"])
            self.assertLessEqual(len(case["stress"]), 3, case["id"])
            self.assertEqual(len(set(case["stress"])), len(case["stress"]), case["id"])
            for stress in case["stress"]:
                self.assertIn(stress, STRESS_CATEGORIES, case["id"])
            # 部位/立体部位/算子设计下限
            self.assertGreaterEqual(case["min_parts"], 7, case["id"])
            self.assertLessEqual(case["min_parts"], 12, case["id"])
            self.assertGreaterEqual(case["min_solid_parts"], 4, case["id"])
            self.assertLessEqual(case["min_solid_parts"], case["min_parts"], case["id"])
            self.assertGreaterEqual(case["min_ops"], 8, case["id"])

    def test_target_blocks_match_frozen_original_text(self):
        seen = set()
        for case in N_CASES:
            expected = EXPECTED_TARGETS[case["id"]]
            self.assertEqual(case["target_blocks"], expected, case["id"])
            self.assertEqual(parse_target_blocks(case["desc"]), expected, case["id"])
            # 需求原文结尾必须逐字是「目标约 N 块积木」
            sentence = f"目标约 {expected} 块积木"
            self.assertTrue(case["desc"].rstrip().endswith(sentence), case["id"])
            self.assertIn(sentence, case["desc"], case["id"])
            seen.add(expected)
        self.assertEqual(len(seen), 20, "20 例目标块数必须各不相同")
        self.assertTrue(all(240 <= t <= 440 for t in seen), sorted(seen))
        self.assertEqual(N_TARGET_TOLERANCE, 0.5)

    def test_min_voxels_follows_g_group_standard(self):
        for case in N_CASES:
            # G 组口径：体素下限 = (target/2) 块 × 4 体素/块 = 2 × target
            self.assertEqual(case["min_voxels"], 2 * case["target_blocks"], case["id"])
            # 目标网格容量上限内（24×24×14=8064，MAX_VOX=5800）
            self.assertLessEqual(case["min_voxels"], 880, case["id"])

    def test_desc_are_real_user_inputs(self):
        for case in N_CASES:
            desc = case["desc"]
            self.assertGreaterEqual(len(desc), 40, case["id"])
            self.assertLessEqual(len(desc), 220, case["id"])
            self.assertTrue(desc.startswith("拼"), case["id"])
            markers = sum(1 for m in STRUCTURE_MARKERS if m in desc)
            self.assertGreaterEqual(markers, 2, f"{case['id']} 缺少两类结构特征：{desc}")
            for word in FORBIDDEN_DESC_WORDS:
                self.assertNotIn(word, desc, f"{case['id']} 含禁止词 {word}")

    def test_require_parts_and_checks_are_assertable(self):
        self.assertEqual(set(N_NEW_CHECK_NAMES), set(N_CHECKS))
        used = set()
        for case in N_CASES:
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
                used.add(spec[0])
        # 本轮 6 个新检查器必须被案例真实引用（不能只注册不用）
        for name in N_NEW_CHECK_NAMES:
            self.assertIn(name, used, f"{name} 没有被任何 N 案例引用")
        # 复用面：至少用到 G 组专项检查 + 20 例通用检查器
        self.assertTrue(any(n.startswith("g_") for n in used - set(N_NEW_CHECK_NAMES)),
                        "没有复用 G 组专项检查器")
        self.assertTrue(any(n in ("both_sides", "part_span_min", "tiered_min",
                                  "negative_space_passage", "s_curve_min",
                                  "layer_components_min") for n in used),
                        "没有复用通用检查器")

    def test_checker_parameters_are_serializable_in_case_specs(self):
        """checks 参数必须能落盘到轮次 JSON：tuple/list/str/int/float 均可。"""
        for case in N_CASES:
            json.dumps(case["checks"], ensure_ascii=False)

    def test_find_n_case_semantics(self):
        self.assertEqual(find_n_case("n01")["id"], "N01")
        self.assertEqual(find_n_case(" N20 ")["id"], "N20")
        self.assertEqual(find_n_case(desc=N_CASES[4]["desc"])["id"], "N05")
        self.assertIsNone(find_n_case("N21"))
        self.assertIsNone(find_n_case("C01"))
        self.assertIsNone(find_n_case("H01"))
        self.assertIsNone(find_n_case("G01"))
        self.assertIsNone(find_n_case(desc="不存在的需求"))
        self.assertIsNone(find_n_case(desc=N_CASES[0]["desc"] + "（改）"))

    def test_n_ids_never_cross_with_c_h_g_pools(self):
        ch_ids = {c["id"] for c in all_ch_cases()}
        g_ids = {c["id"] for c in G_CASES}
        n_ids = {c["id"] for c in N_CASES}
        self.assertEqual(n_ids & ch_ids, set())
        self.assertEqual(n_ids & g_ids, set())
        # 区间解析只按编号前缀匹配：C/H/G 区间不会误配 N 组，N 组也不会混入 C/H/G
        combined = list(all_ch_cases()) + [c for c in G_CASES if c["id"] not in ch_ids] \
            + list(N_CASES)
        def pick(prefix, lo, hi):
            return [c["id"] for c in combined
                    if c["id"][:1].upper() == prefix and lo <= int(c["id"][1:]) <= hi]
        self.assertEqual(pick("N", 1, 20), EXPECTED_IDS)
        self.assertEqual(pick("N", 1, 5), [f"N{i:02d}" for i in range(1, 6)])
        self.assertFalse([i for i in pick("C", 1, 20) if i.startswith("N")])
        self.assertFalse([i for i in pick("G", 1, 10) if i.startswith("N")])
        self.assertFalse([i for i in pick("N", 1, 20) if not i.startswith("N")])


# ---------------------------------------------------------------- 2. 主题新颖性审计
class AuditTest(unittest.TestCase):
    def test_real_corpus_audit_has_no_conflicts(self):
        """公开审计语料 fixture 驱动：N 组 20 例与 C/X/G/R 已发布案例 0 冲突。"""
        from tools.e2e_cases_20 import _load_public_history_corpus
        corpus = _load_public_history_corpus(exclude_groups=("N",))
        self.assertIsNotNone(
            corpus, "公开审计语料缺失：test/fixtures/public/history-corpus.json")
        report = audit_n_cases(corpus=corpus)
        self.assertTrue(report["ok"], report["conflicts"])
        self.assertEqual(report["conflicts"], [])
        self.assertEqual(len(report["cases"]), 20)
        for row in report["cases"]:
            self.assertEqual(row["conflicts"], [], row["id"])
        # 基准语料非空，不是空审计假通过
        self.assertGreater(report["corpus"]["descs"], 0)
        self.assertGreater(report["corpus"]["names"], 0)
        self.assertGreater(report["pools"]["count"], 0)
        self.assertFalse(report["used_clean_baseline"])

    def test_injected_duplicate_desc_is_reported(self):
        corpus = ([N_CASES[0]["desc"]], [])
        report = audit_n_cases(corpus=corpus, check_case_pools=False)
        self.assertFalse(report["ok"])
        self.assertEqual([c["id"] for c in report["conflicts"]], ["N01"])
        self.assertTrue(any("需求原文与历史任务完全相同" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_subject_in_history_desc_is_reported(self):
        corpus = (["用户想拼一个放在客厅的孔雀摆件，目标约 300 块积木"], [])
        report = audit_n_cases(corpus=corpus, check_case_pools=False)
        self.assertFalse(report["ok"])
        self.assertEqual(report["conflicts"][0]["id"], "N01")
        self.assertTrue(any("主题词「孔雀」出现在历史需求" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_subject_in_model_name_is_reported(self):
        corpus = ([], ["孔雀开屏摆件"])
        report = audit_n_cases(corpus=corpus, check_case_pools=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("主题词「孔雀」出现在历史模型名称/特征" in r
                            for r in report["conflicts"][0]["reasons"]))

    def test_injected_case_pool_conflict_is_reported(self):
        """C/H/G 既有案例池也算撞题基线：主题与池内案例相同必须报错。"""
        from tools.e2e_cases_new20 import _case_pool_entries
        pools = [e for e in _case_pool_entries() if e["subject"]]
        self.assertTrue(pools, "案例池为空，无法验证池内撞题")
        fake = {"id": "NX1", "name": "撞池测试", "subject": pools[0]["subject"],
                "desc": "一个测试需求，目标约 240 块积木"}
        report = audit_n_cases(cases=[fake], corpus=([], []), pools=pools)
        self.assertFalse(report["ok"])
        reasons = report["conflicts"][0]["reasons"]
        self.assertTrue(any("案例" in r and "需求" in r or "主题与" in r for r in reasons),
                        reasons)

    def test_own_campaign_desc_is_excluded_from_baseline(self):
        """N 组自己跑过的需求/run 必须从基准中排除，否则二次审计会自我撞题。"""
        import tools.e2e_cases_20 as cases_20
        import tools.e2e_cases_new20 as cases_n
        with mock.patch.object(cases_20, "_load_history_corpus",
                               return_value=(["一只小鸟"], [])):
            with mock.patch.object(cases_n, "_n_campaign_scope",
                                   return_value=({"一只小鸟"}, set())):
                report = audit_n_cases(check_case_pools=False)
        self.assertTrue(report["ok"], report["conflicts"])
        self.assertEqual(report["conflicts"], [])
        # 只排除本组自己的：历史里其他需求仍照常参与审计
        with mock.patch.object(cases_20, "_load_history_corpus",
                               return_value=([N_CASES[4]["desc"]], [])):
            with mock.patch.object(cases_n, "_n_campaign_scope",
                                   return_value=({"一只小鸟"}, set())):
                report2 = audit_n_cases(check_case_pools=False)
        self.assertFalse(report2["ok"])
        self.assertEqual([c["id"] for c in report2["conflicts"]], ["N05"])

    def test_clean_baseline_marks_used_clean_baseline(self):
        report = audit_n_cases(corpus=([], []), check_case_pools=False)
        self.assertTrue(report["ok"])
        self.assertTrue(report["used_clean_baseline"])
        self.assertEqual(len(report["cases"]), 20)


# ---------------------------------------------------------------- 3. CLI 可跑
class CliTest(unittest.TestCase):
    def _run_main(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = new20_main(argv)
        return code, buf.getvalue()

    def test_list_cli(self):
        code, out = self._run_main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("共 20 例", out)
        for case_id in EXPECTED_IDS:
            self.assertIn(case_id, out)
        self.assertIn("压力=", out)

    def test_audit_cli_empty_corpus_fails(self):
        """缺语料不得静默通过：--audit exit 2，只有 --allow-empty 显式放行。"""
        import tools.e2e_cases_new20 as cases_n
        with mock.patch.object(cases_n, "_load_n_history_corpus", return_value=([], [])):
            code, out = self._run_main(["--audit"])
            self.assertEqual(code, 2, out)
            self.assertIn("未执行完整新颖性审计", out)
            code2, _out2 = self._run_main(["--audit", "--allow-empty"])
            self.assertEqual(code2, 0)

    def test_audit_cli(self):
        code, out = self._run_main(["--audit"])
        self.assertEqual(code, 0)
        self.assertIn("冲突 0 例", out)
        self.assertIn("N01", out)
        self.assertIn("N20", out)

    def test_default_dumps_json(self):
        code, out = self._run_main([])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 20)
        self.assertEqual([d["id"] for d in data], EXPECTED_IDS)
        self.assertEqual(data[0]["target_blocks"], 400)

    def test_module_cli_in_subprocess(self):
        """按真实命令行方式跑 `python -m tools.e2e_cases_new20 --list`。"""
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run([sys.executable, "-m", "tools.e2e_cases_new20", "--list"],
                              cwd=ROOT, env=env, capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace")[-800:])
        out = proc.stdout.decode("utf-8", "replace")
        self.assertIn("共 20 例", out)
        self.assertIn("N20", out)

    def _run_module_gbk(self, argv):
        """模拟 Windows cp936(GBK) 控制台/管道：python 进程 stdout 编码为 gbk。"""
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "gbk"
        return subprocess.run([sys.executable, "-m", "tools.e2e_cases_new20"] + argv,
                              cwd=ROOT, env=env, capture_output=True, timeout=180)

    def test_audit_cli_survives_gbk_console(self):
        """本机 GBK 控制台下 --audit 必须直接跑通（曾因 ✅ 触发 UnicodeEncodeError）。"""
        proc = self._run_module_gbk(["--audit"])
        self.assertEqual(proc.returncode, 0,
                         proc.stderr.decode("utf-8", "replace")[-800:])
        self.assertNotIn(b"UnicodeEncodeError", proc.stderr)

    def test_list_cli_survives_gbk_console(self):
        proc = self._run_module_gbk(["--list"])
        self.assertEqual(proc.returncode, 0,
                         proc.stderr.decode("utf-8", "replace")[-800:])
        self.assertNotIn(b"UnicodeEncodeError", proc.stderr)


# ---------------------------------------------------------------- 4. check_objects_n
def _fake_case(**over):
    case = {"id": "NXX", "name": "测试案例", "desc": "测试需求：目标约 10 块积木",
            "target_blocks": 10, "stress": ["scale"],
            "historical_failure_hint": "测试用历史失败提示",
            "min_parts": 1, "min_solid_parts": 1, "min_voxels": 1, "min_ops": 0,
            "require_parts": [], "checks": [["layers_min", 1]]}
    case.update(over)
    return case


def _steps(n):
    return [{"piece": "B1x1", "x": 0, "z": 0, "layer": 0, "rotate": False, "step": i + 1}
            for i in range(n)]


class MetricsTest(unittest.TestCase):
    def setUp(self):
        """统一校验按同一模型重算；本类合成模型/方案只需校验桩放行。"""
        patcher = mock.patch("tools.e2e_assert.validate_solution",
                             return_value={"ok": True, "errors": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _model(self):
        cells = {(0, 0, 0), (1, 0, 0)}
        return model_from_cells(cells, 2, 1, 1,
                                [make_part("tail", "尾屏", cells=cells)], default_color="L")

    def test_metrics_include_target_and_tiers(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_n(record, self._model(),
                                          {"validation": {"ok": True}, "steps": _steps(5)},
                                          _fake_case())
        self.assertEqual(errors, [])
        self.assertEqual(metrics["suite"], "N")
        self.assertEqual(metrics["target_blocks"], 10)
        self.assertEqual(metrics["bricks"], 5)
        self.assertEqual(metrics["bricks_ratio"], 0.5)
        self.assertTrue(metrics["target_blocks_ok"])
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertEqual(metrics["stress"], ["scale"])
        self.assertTrue(metrics["historical_failure_hint"])
        self.assertIn("regression_tier", metrics)
        for key in ("voxels", "layers", "colors", "ops", "voxels_per_target_block"):
            self.assertIn(key, metrics["regression_tier"])
        self.assertTrue(metrics["assertion_ok"])

    def test_target_tolerance_boundary_50_percent(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        case = _fake_case()
        _e, metrics = check_objects_n(record, self._model(),
                                      {"validation": {"ok": True}, "steps": _steps(5)}, case)
        self.assertTrue(metrics["target_blocks_ok"])
        errors, metrics = check_objects_n(record, self._model(),
                                          {"validation": {"ok": True}, "steps": _steps(4)}, case)
        self.assertFalse(metrics["target_blocks_ok"])
        self.assertEqual(metrics["bricks_ratio"], 0.4)
        self.assertTrue(any("目标块数未达标" in e for e in errors))
        self.assertTrue(any("目标块数未达标" in e for e in metrics["requirement_tier"]))
        self.assertFalse(metrics["assertion_ok"])

    def test_task_failure_short_circuits_case_checks(self):
        record = {"ok": False, "runId": "x", "error": "生成失败", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_n(
            record, self._model(), {"validation": {"ok": True}, "steps": _steps(0)},
            _fake_case())
        self.assertTrue(any("运行未成功" in e for e in errors))
        self.assertEqual(metrics["requirement_tier"], [])
        self.assertTrue(metrics["generic_tier"])
        self.assertFalse(metrics["assertion_ok"])

    def test_missing_artifacts_do_not_raise(self):
        """无产物/空模型不得抛未捕获异常，必须给可读失败。"""
        errors, metrics = check_objects_n(
            {"ok": False, "runId": "x", "error": "无产物", "revision": 1, "artifacts": {}},
            {}, {}, _fake_case())
        self.assertTrue(errors)
        self.assertFalse(metrics["assertion_ok"])
        # 任务标记成功但模型为空：断言同样只能可读失败，不能崩
        errors2, metrics2 = check_objects_n(
            {"ok": True, "runId": "x", "revision": 1, "artifacts": {}},
            None, None, _fake_case())
        self.assertTrue(errors2)
        self.assertFalse(metrics2["assertion_ok"])

    def test_empty_model_with_real_validation_does_not_raise(self):
        """不 mock 统一校验：空模型下 validate_solution 的异常必须转成可读失败。"""
        with mock.patch("tools.e2e_assert.validate_solution",
                        side_effect=KeyError("layers")):
            errors, metrics = check_objects_n(
                {"ok": True, "runId": "x", "revision": 1, "artifacts": {}},
                {}, {}, _fake_case())
        self.assertTrue(any("统一校验" in e or "通用底线断言" in e for e in errors), errors)
        self.assertFalse(metrics["assertion_ok"])

    def test_unknown_check_is_config_error(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, _m = check_objects_n(record, self._model(),
                                     {"validation": {"ok": True}, "steps": _steps(5)},
                                     _fake_case(checks=[["不存在的检查", 1]]))
        self.assertTrue(any("未知检查" in e for e in errors))

    def test_check_exception_becomes_readable_error(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, _m = check_objects_n(record, self._model(),
                                     {"validation": {"ok": True}, "steps": _steps(5)},
                                     _fake_case(checks=[["layers_min"]]))
        self.assertTrue(any("执行失败" in e for e in errors))

    def test_draw_requests_takes_cumulative_max(self):
        """drawAttempts[].request 是累计编号，请求数取最大值。

        连续（1,2,3）与跳号（1,3）都取最大值；空列表为 0；旧口径求和会高估。
        """
        for attempts, expected in (([{"request": 1}, {"request": 2}, {"request": 3}], 3),
                                   ([{"request": 1}, {"request": 3}], 3),
                                   ([], 0)):
            record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {},
                      "drawAttempts": attempts}
            _e, metrics = check_objects_n(
                record, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
                _fake_case())
            self.assertEqual(metrics["draw_attempts"], len(attempts))
            self.assertEqual(metrics["draw_requests"], expected, attempts)

    def test_review_fallback_from_task_result(self):
        """旧 run 记录没有 review：用任务 result.review 补入并留痕来源。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_n(
            record, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
            _fake_case(), review_fallback={"scores": {"overall": 6}})
        self.assertEqual(errors, [])
        self.assertEqual(metrics["review_overall"], 6)
        self.assertEqual(metrics["review_source"], "task_result")
        _e2, own = check_objects_n(
            dict(record, review={"scores": {"overall": 2}}), self._model(),
            {"validation": {"ok": True}, "steps": _steps(5)}, _fake_case(),
            review_fallback={"scores": {"overall": 6}})
        self.assertEqual(own["review_overall"], 2)
        self.assertEqual(own["review_source"], "run_record")
        _e3, none = check_objects_n(
            record, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
            _fake_case())
        self.assertIsNone(none["review_overall"])
        self.assertIsNone(none["review_source"])

    def test_min_part_floor_is_requirement_failure(self):
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_n(record, self._model(),
                                          {"validation": {"ok": True}, "steps": _steps(5)},
                                          _fake_case(min_parts=5, min_solid_parts=4))
        self.assertTrue(any("部位数" in e for e in errors))
        self.assertFalse(metrics["assertion_ok"])

    def test_regression_metrics_never_fail_the_case(self):
        """体素/算子低于设计参考下限只进回归档，不判失败。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {}}
        errors, metrics = check_objects_n(
            record, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
            _fake_case(min_voxels=1000, min_ops=99))
        self.assertEqual(errors, [])
        regression = metrics["regression_tier"]
        self.assertTrue(regression["voxels_below_design_floor"])
        self.assertTrue(regression["ops_below_design_floor"])
        self.assertTrue(metrics["assertion_ok"])

    def test_check_run_n_missing_record_is_readable(self):
        """运行记录缺失/损坏时 check_run_n 给可读 SystemExit，不抛裸 traceback。"""
        import tools.e2e_assert_new20 as assert_n
        with mock.patch.object(assert_n, "load_run",
                               side_effect=FileNotFoundError("run_nope.json")):
            with self.assertRaises(SystemExit) as ctx:
                assert_n.check_run_n("nope")
        self.assertIn("读取 run nope 失败", str(ctx.exception))

    def test_final_gate_replay_is_read_compatibly(self):
        """方案 4.2：最终门禁以 record["finalGateReplay"] 重放为准（与 G 组同一口径）。"""
        record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {},
                  "finalGateReplay": {"ok": False, "errors": ["墙皮部位过小"]}}
        errors, metrics = check_objects_n(
            record, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
            _fake_case())
        self.assertTrue(any("最终门禁重放未通过" in e for e in errors), errors)
        self.assertIn("最终门禁重放未通过", " ".join(metrics["generic_tier"]))
        self.assertFalse(metrics["assertion_ok"])
        # 最终模型重放通过时不产生门禁失败（过程标记不单独判失败）
        passed = dict(record, finalGateReplay={"ok": True, "errors": []})
        errors2, metrics2 = check_objects_n(
            passed, self._model(), {"validation": {"ok": True}, "steps": _steps(5)},
            _fake_case())
        self.assertFalse(any("最终门禁重放" in e for e in errors2), errors2)
        self.assertTrue(metrics2["assertion_ok"], errors2)

    def test_new_checkers_are_merged_into_g_registry(self):
        """新检查器导入后并入 G_CHECKS，check_objects_g 能直接执行（只读复用接线）。"""
        self.assertTrue(set(N_CHECKS) <= set(G_CHECKS))
        model = fan_tail_model()
        case = _fake_case(target_blocks=None, min_parts=1, min_solid_parts=1,
                          checks=[["g_fan_tail", ("尾屏",), 90, 5]])
        errors, metrics = check_objects_g(
            {"ok": True, "runId": "x", "revision": 1, "artifacts": {}},
            model, {"validation": {"ok": True}, "steps": _steps(5)}, case)
        self.assertFalse(any("未知检查" in e for e in errors), errors)
        self.assertTrue(metrics["assertion_ok"], errors)


# ---------------------------------------------------------------- 5. 新检查器正反例
def fan_tail_model(narrow=False, flat=False, missing=False):
    """扇形尾屏：正例为向上张开的扇形；反例为竖条/单层平板/缺部位。"""
    w = h = 24
    u0 = 11
    tail = set()
    if not missing:
        tail |= {(u0 - 1, 0, 0), (u0, 0, 0), (u0 + 1, 0, 0),
                 (u0 - 1, 0, 1), (u0, 0, 1), (u0 + 1, 0, 1)}
        if flat:
            tail = {(u, 1, 0) for u in range(7, 17)} | {(u, 1, 1) for u in range(7, 17)}
        else:
            for y in range(1, 7):
                half = 1 if narrow else (3 * y) // 2
                for du in range(-half, half + 1):
                    tail.add((u0 + du, y, 0))
                    tail.add((u0 + du, y, 1))
    parts = [make_part("tail", "尾屏", cells=tail)] if not missing else []
    return model_from_cells(tail, w, h, 8, parts, default_color="B")


class FanTailCheckerTest(unittest.TestCase):
    def test_positive_fan_tail(self):
        assert_pass(self, "g_fan_tail", fan_tail_model(), ("尾屏", "尾羽", "尾", "fan", "tail"),
                    90, 5)

    def test_narrow_vertical_tail_is_rejected(self):
        assert_fail(self, "g_fan_tail", fan_tail_model(narrow=True),
                    ("尾屏",), 90, 5, contains="扇形")

    def test_flat_tail_is_rejected(self):
        assert_fail(self, "g_fan_tail", fan_tail_model(flat=True),
                    ("尾屏",), 90, 5, contains="层数不足")

    def test_missing_tail_is_rejected(self):
        assert_fail(self, "g_fan_tail", fan_tail_model(missing=True),
                    ("尾屏",), 90, 5, contains="未找到尾屏部位")


def tentacle_model(bundled=False, flat=False, missing=False):
    """触手方位：正例八方位垂落；反例同向挤成一束/单层贴片/缺部位。"""
    w = h = 24
    cx, cz, top_y = 11, 11, 7
    cells = set()
    if not missing:
        if bundled:
            # 四根触手全部朝同一斜向并排垂下：有足够体量，但方位覆盖只有 1 个
            for k in range(4):
                for t in range(5):
                    cells.add((cx + 1 + k, top_y - t, cz + 1 + k))
        else:
            for k in range(8):
                ang = 2 * math.pi * k / 8
                for t in range(5):
                    r = 1 + t
                    x = int(round(cx + r * math.cos(ang)))
                    z = int(round(cz + r * math.sin(ang)))
                    cells.add((x, top_y - t, z))
        if flat:
            cells = {(x, top_y, z) for (x, _y, z) in cells}
    parts = [make_part("tentacles", "触手", cells=cells)] if not missing else []
    return model_from_cells(cells, w, h, 12, parts, default_color="O")


class TentacleCheckerTest(unittest.TestCase):
    def test_positive_tentacles(self):
        assert_pass(self, "g_tentacle_directions", tentacle_model(),
                    ("触手", "腕", "tentacle"), 4, 2)

    def test_bundled_tentacles_are_rejected(self):
        errors = assert_fail(self, "g_tentacle_directions", tentacle_model(bundled=True),
                             ("触手",), 4, 2, contains="触手方位不足")
        self.assertTrue(errors)

    def test_flat_tentacles_are_rejected(self):
        assert_fail(self, "g_tentacle_directions", tentacle_model(flat=True),
                    ("触手",), 4, 2, contains="竖向跨度不足")

    def test_missing_tentacles_are_rejected(self):
        assert_fail(self, "g_tentacle_directions", tentacle_model(missing=True),
                    ("触手",), 4, 2, contains="未找到触手部位")


def bridge_model(flat_cable=False, no_hanger=False, missing_cable=False):
    """悬索桥：正例主缆跨中下垂 + 吊索；反例水平直缆/无吊索/缺主缆。"""
    w, d, h = 18, 8, 10
    tower = {(x, y, z) for x in (2, 14) for y in range(7) for z in (0, 1)}
    cable = set()
    if not missing_cable:
        for x in range(2, 15):
            y = 6 if flat_cable else 3 + int(round(3 * ((x - 8) / 6.0) ** 2))
            cable.add((x, y, 0))
            cable.add((x, y, 1))
    cable_top = {x: max(c[1] for c in cable if c[0] == x) for x in {c[0] for c in cable}}
    hanger = set()
    if not no_hanger:
        for x in range(5, 12):
            top = cable_top.get(x)
            if top is None:
                continue
            for y in range(2, top):
                hanger.add((x, y, 0))
                hanger.add((x, y, 1))
    deck = {(x, y, z) for x in range(0, 18) for y in (0, 1) for z in range(3, 7)}
    parts = [make_part("towers", "桥塔", cells=tower)]
    if not missing_cable:
        parts.append(make_part("cable", "主缆", cells=cable))
    parts += [make_part("hangers", "吊索", cells=hanger), make_part("deck", "桥面", cells=deck)]
    cells = tower | cable | hanger | deck
    return model_from_cells(cells, w, d, h, parts, default_color="L")


class SuspensionSagCheckerTest(unittest.TestCase):
    def test_positive_suspension_sag(self):
        assert_pass(self, "g_suspension_sag", bridge_model(),
                    ("主缆", "悬索", "缆", "cable"), 2,
                    ("吊索", "吊杆", "hanger", "suspender"), 2)

    def test_straight_cable_is_rejected(self):
        assert_fail(self, "g_suspension_sag", bridge_model(flat_cable=True),
                    ("主缆",), 2, ("吊索",), 2, contains="垂度")

    def test_missing_hangers_are_rejected(self):
        assert_fail(self, "g_suspension_sag", bridge_model(no_hanger=True),
                    ("主缆",), 2, ("吊索",), 2, contains="吊索")

    def test_missing_cable_is_rejected(self):
        assert_fail(self, "g_suspension_sag", bridge_model(missing_cable=True),
                    ("主缆",), 2, ("吊索",), 2, contains="未找到主缆部位")


def leaning_tower_model(straight=False, zigzag=False, short=False):
    """倾斜塔：正例逐层同向偏移；反例垂直塔/左右来回摆/层数不足。"""
    w = d = 24
    cells = set()
    layers = 3 if short else 8
    for y in range(layers):
        if straight:
            shift = 0
        elif zigzag:
            shift = 2 if y % 2 == 0 else -2
        else:
            shift = y // 2 + (1 if y % 2 else 0)
        for dx in range(3):
            for dz in range(3):
                cells.add((11 + shift + dx, y, 11 + dz))
    parts = [make_part("tower", "塔身", cells=cells)]
    return model_from_cells(cells, w, d, 12, parts, default_color="M")


class LeaningTowerCheckerTest(unittest.TestCase):
    def test_positive_leaning_tower(self):
        assert_pass(self, "g_leaning_tower", leaning_tower_model(),
                    ("塔身", "塔体", "塔", "tower"), 3, 5, 0.6)

    def test_straight_tower_is_rejected(self):
        assert_fail(self, "g_leaning_tower", leaning_tower_model(straight=True),
                    ("塔身",), 3, 5, 0.6, contains="没有明显倾斜")

    def test_zigzag_tower_is_rejected(self):
        assert_fail(self, "g_leaning_tower", leaning_tower_model(zigzag=True),
                    ("塔身",), 3, 5, 0.6, contains="不连贯")

    def test_short_tower_is_rejected(self):
        assert_fail(self, "g_leaning_tower", leaning_tower_model(short=True),
                    ("塔身",), 3, 5, 0.6, contains="层数不足")


def tractor_model(same_size=False, missing_small=False):
    """轮径比：正例后轮直径 7 / 前轮 4；反例前后一样大/缺前轮。"""
    w, d, h = 24, 8, 10
    big = {(x, y, 0) for x in range(4, 18) for y in range(7)
           if (x - 11) ** 2 + (y - 3) ** 2 <= 3.5 ** 2}
    small = set()
    if not missing_small:
        if same_size:
            small = {(x, y, 0) for x in range(16, 23) for y in range(7)
                     if (x - 19) ** 2 + (y - 3) ** 2 <= 3.5 ** 2}
        else:
            small = {(x, y, 0) for x in range(16, 23) for y in range(4)
                     if (x - 19) ** 2 + (y - 1.5) ** 2 <= 2.0 ** 2}
    parts = [make_part("rear_wheel", "后轮", cells=big)]
    if not missing_small:
        parts.append(make_part("front_wheel", "前轮", cells=small))
    cells = big | small
    return model_from_cells(cells, w, d, h, parts, default_color="D")


class WheelSizeRatioCheckerTest(unittest.TestCase):
    def test_positive_wheel_size_ratio(self):
        assert_pass(self, "g_wheel_size_ratio", tractor_model(),
                    ("后轮", "大轮", "rear"), ("前轮", "小轮", "front"), 1.4)

    def test_same_size_wheels_are_rejected(self):
        assert_fail(self, "g_wheel_size_ratio", tractor_model(same_size=True),
                    ("后轮",), ("前轮",), 1.4, contains="轮径比不足")

    def test_missing_front_wheel_is_rejected(self):
        assert_fail(self, "g_wheel_size_ratio", tractor_model(missing_small=True),
                    ("后轮",), ("前轮",), 1.4, contains="未找到小轮部位")


def balloon_model(dropped_envelope=False, small_envelope=False, no_rope=False,
                  missing_envelope=False):
    """气囊-吊篮：正例气囊在上、吊绳连接、吊篮落地；反例气囊下沉/等大/无吊绳/缺气囊。"""
    w = d = 24
    h = 14
    basket = {(x, y, z) for y in (0, 1) for x in range(9, 13) for z in range(9, 13)}
    envelope = set()
    if not missing_envelope:
        shift = -5 if dropped_envelope else 0
        if small_envelope:
            radii = {5 + shift + k: 1 for k in range(8)}
        else:
            radii = {5 + shift: 1, 6 + shift: 2, 7 + shift: 3, 8 + shift: 4,
                     9 + shift: 4, 10 + shift: 3, 11 + shift: 2, 12 + shift: 1}
        for y, r in radii.items():
            if y < 0:
                continue
            for x in range(11 - r, 11 + r + 1):
                for z in range(11 - r, 11 + r + 1):
                    if (x - 11) ** 2 + (z - 11) ** 2 <= r * r:
                        envelope.add((x, y, z))
    ropes = set()
    if not no_rope:
        for (x, z) in ((9, 9), (9, 12), (12, 9), (12, 12)):
            for y in range(2, 5):
                ropes.add((x, y, z))
    parts = [make_part("basket", "吊篮", cells=basket)]
    if not missing_envelope:
        parts.insert(0, make_part("envelope", "气囊", cells=envelope))
    if not no_rope:
        parts.append(make_part("ropes", "吊绳", cells=ropes))
    cells = envelope | basket | ropes
    return model_from_cells(cells, w, d, h, parts, default_color="R")


class BalloonBasketCheckerTest(unittest.TestCase):
    def test_positive_balloon_basket(self):
        assert_pass(self, "g_balloon_basket", balloon_model(),
                    ("气囊", "球囊", "envelope"), ("吊篮", "篮子", "basket"),
                    ("吊绳", "绳索", "rope"), 1)

    def test_envelope_below_basket_is_rejected(self):
        assert_fail(self, "g_balloon_basket", balloon_model(dropped_envelope=True),
                    ("气囊",), ("吊篮",), ("吊绳",), 1, contains="气囊没有位于吊篮上方")

    def test_tiny_envelope_is_rejected(self):
        assert_fail(self, "g_balloon_basket", balloon_model(small_envelope=True),
                    ("气囊",), ("吊篮",), ("吊绳",), 1, contains="气囊体量不足")

    def test_missing_ropes_are_rejected(self):
        assert_fail(self, "g_balloon_basket", balloon_model(no_rope=True),
                    ("气囊",), ("吊篮",), ("吊绳",), 1, contains="未找到吊绳部位")

    def test_missing_envelope_is_rejected(self):
        assert_fail(self, "g_balloon_basket", balloon_model(missing_envelope=True),
                    ("气囊",), ("吊篮",), ("吊绳",), 1, contains="未找到气囊部位")


# ---------------------------------------------------------------- 6. 覆盖统计（最后执行）
class ZCoverageTest(unittest.TestCase):
    def test_every_new_checker_has_positive_and_negative(self):
        expected = set(N_CHECKS)
        missing_pass = [n for n in expected if COVERAGE.get(n, {}).get("pass", 0) < 1]
        missing_fail = [n for n in expected if COVERAGE.get(n, {}).get("fail", 0) < 1]
        self.assertEqual(missing_pass, [], f"以下新检查器缺正例：{missing_pass}")
        self.assertEqual(missing_fail, [], f"以下新检查器缺反例：{missing_fail}")
        self.assertEqual(len(expected), 6, "本轮新增检查器应为 6 个")

    def test_every_case_has_checks_and_requires(self):
        for case in N_CASES:
            self.assertTrue(case["checks"], case["id"])
            self.assertTrue(case["require_parts"], case["id"])


if __name__ == "__main__":
    unittest.main()
