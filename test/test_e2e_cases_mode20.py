# -*- coding: utf-8 -*-
"""M01–M20 双模式 E2E 案例单源与断言器的确定性回归测试（不调用真实模型/浏览器/求解）。

覆盖：
  1. 案例注册纪律：20 例、ID 顺序 M01–M20、tier 简单/复杂各 10、名称/原文唯一、字段完整、
     target_blocks 与需求原文解析一致、每条 checks/require_parts 非空且检查名可解析；
  2. 需求原文冻结：frozen_hashes() 与 FROZEN_DESC_SHA256 一致、与需求原文表格逐字一致、
     --hash/--list/--audit CLI 可跑、篡改原文/档位/数量时 audit 必须报错；
  3. 新增几何原语：storeys_min / part_color_ratio_min / sloped_part_min / exposed_color_min /
     windows_evidenced / part_above_ref / part_below_ref / tapered_parts_min / pair_sides_min /
     part_extends_beyond / crenellated_top_min / negative_space_passages_min / thin_plate_min /
     part_levels_min / corner_towers_min / legs_splay_min / center_void_min / shell_roof_min /
     perimeter_objects_min / parts_union_components / parts_adjacent_any / radial_spokes_min /
     wall_opening_min 的正反例（合成 model，断言基于真实几何/配色）；
  4. check_objects_m：通用底线（mock 统一校验）+ 目标块数比 + 冻结原文守卫 + 模式事实
     （fast 无评审/无保底、fidelity 评审或如实不可用、保底 <=1）+ 指标字段完整 + 可读失败；
  5. draw_requests 语义：取 drawAttempts[].request 的最大值，不得求和。
"""
import contextlib
import hashlib
import io
import json
import os
import unittest
from unittest import mock

from tools.e2e_assert_mode20 import M_CHECKS, check_objects_m, resolve_check
from tools.e2e_cases_mode20 import (
    FROZEN_DESC_SHA256, M_CASES, M_EXPECTED_IDS, M_TARGET_TOLERANCE, M_TIER_COUNTS,
    all_m_cases, audit_m_cases, case_hash, desc_sha256, find_m_case, frozen_hashes,
    parse_target_blocks,
)
from tools.e2e_cases_mode20 import main as cases_main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_TARGETS = {
    "M01": 100, "M02": 80, "M03": 100, "M04": 80, "M05": 100,
    "M06": 60, "M07": 80, "M08": 80, "M09": 100, "M10": 100,
    "M11": 300, "M12": 260, "M13": 260, "M14": 240, "M15": 220,
    "M16": 320, "M17": 260, "M18": 280, "M19": 220, "M20": 320,
}
FAKE_DESC = "测试需求：目标约 10 块积木"


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
        for value in xs[1:]:
            if value == prev + 1:
                prev = value
                continue
            boxes.append({"x1": run_start, "x2": prev, "z1": z, "z2": z,
                          "y1": y, "y2": y})
            run_start = prev = value
        boxes.append({"x1": run_start, "x2": prev, "z1": z, "z2": z, "y1": y, "y2": y})
    return boxes


def make_part(pid, name, cells, role="solid"):
    cells = set(cells)
    return {"id": pid, "name": name, "role": role, "voxels": len(cells),
            "boxes": cells_to_boxes(cells)}


def model_from_cells(cells, w, d, h=None, parts=None, chars=None, colors=None):
    """由 3D 格集合生成 model（layers/rows/cells/colorRows 与 totalVoxels 一致）。

    chars: {(x,y,z): 设计字符}（默认 "#"），用于斜面/坡屋顶；colors: {(x,y,z): 颜色字符}。
    """
    cells = set(cells)
    chars = chars or {}
    colors = colors or {}
    ys = sorted({c[1] for c in cells}) or [0]
    h = h or (max(ys) + 1)
    layers = []
    for y in range(h):
        plane = {(x, z) for (x, yy, z) in cells if yy == y}
        rows = ["".join(chars.get((x, y, z), "#") if (x, z) in plane else "."
                        for x in range(w)) for z in range(d)]
        color_rows = None
        if colors:
            color_rows = ["".join(colors.get((x, y, z), "W") if (x, z) in plane else "."
                                  for x in range(w)) for z in range(d)]
        layers.append({"y": y, "rows": rows,
                       "cells": [[x, z] for z in range(d) for x in range(w) if (x, z) in plane],
                       "module": ["m"], "color": None, "colorRows": color_rows,
                       "count": len(plane)})
    return {"name": "测试M", "grid": {"w": w, "d": d}, "totalVoxels": len(cells),
            "slopeVoxels": 0, "layers": layers, "parts": parts or [],
            "ops": [], "track": "ops"}


def ctx_of(model):
    from tools.e2e_assert_20 import _part_counts, _solid
    from tools.e2e_assert import _colored_cells
    return {"model": model, "solution": {}, "counts": _part_counts(model),
            "colored": _colored_cells(model), "solid": _solid(model)}


def check(name, ctx, *args):
    return list(resolve_check(name)(ctx, *args) or [])


def _steps(n):
    return [{"piece": "B1x1", "x": 0, "z": 0, "layer": 0, "rotate": False, "step": i + 1}
            for i in range(n)]


def _fake_case(**over):
    case = {"id": "MXX", "name": "测试案例", "tier": "简单", "desc": FAKE_DESC,
            "target_blocks": 10, "require_parts": [], "checks": [["layers_min", 1]]}
    case.update(over)
    return case


def _fast_counts(**over):
    counts = {"revise_class1": 0, "revise_class2": 0, "revise_visual": 0}
    counts.update(over)
    return counts


def _fake_record(**over):
    record = {"ok": True, "runId": "x", "revision": 1, "artifacts": {},
              "finalGateReplay": {"ok": True, "errors": []},
              "desc": FAKE_DESC, "mode": "fast", "counts": _fast_counts()}
    record.update(over)
    return record


def _fake_model(part_name="身体", color="L"):
    cells = {(0, 0, 0), (1, 0, 0)}
    return model_from_cells(cells, 2, 1, 1, [make_part("body", part_name, cells)],
                            colors={cell: color for cell in cells})


def _fake_solution(n_steps=5):
    return {"validation": {"ok": True}, "steps": _steps(n_steps)}


# ---------------------------------------------------------------- 1. 案例注册纪律
class CaseRegistryTest(unittest.TestCase):
    def test_twenty_cases_in_order(self):
        self.assertEqual(len(M_CASES), 20)
        self.assertEqual([c["id"] for c in M_CASES], M_EXPECTED_IDS)
        self.assertEqual(len(all_m_cases()), 20)
        self.assertIsNot(all_m_cases(), M_CASES)  # 返回副本，防止外部改单源
        self.assertEqual(len({c["desc"] for c in M_CASES}), 20)
        self.assertEqual(len({c["name"] for c in M_CASES}), 20)
        self.assertEqual({c["id"]: c["target_blocks"] for c in M_CASES}, EXPECTED_TARGETS)

    def test_tier_counts(self):
        counts = {}
        for case in M_CASES:
            counts[case["tier"]] = counts.get(case["tier"], 0) + 1
        self.assertEqual(counts, M_TIER_COUNTS)
        self.assertEqual(M_TIER_COUNTS, {"简单": 10, "复杂": 10})

    def test_every_case_has_required_fields(self):
        for case in M_CASES:
            for key in ("id", "name", "tier", "desc", "target_blocks",
                        "require_parts", "checks", "notes"):
                self.assertIn(key, case, case["id"])
            self.assertTrue(case["desc"].strip(), case["id"])
            self.assertTrue(case["desc"].endswith("块积木"), case["id"])
            self.assertIn("目标约", case["desc"], case["id"])
            self.assertIn(case["tier"], M_TIER_COUNTS, case["id"])
            for name, patterns in case["require_parts"]:
                self.assertTrue(name and patterns, case["id"])
            self.assertTrue(case["checks"], case["id"])

    def test_all_check_names_resolve(self):
        for case in M_CASES:
            for spec in case["checks"]:
                self.assertIsNotNone(resolve_check(spec[0]),
                                     f"{case['id']} 未知检查 {spec[0]}")
        for name in M_CHECKS:
            self.assertIsNotNone(resolve_check(name), name)

    def test_target_blocks_match_frozen_desc(self):
        for case in M_CASES:
            self.assertEqual(parse_target_blocks(case["desc"]), case["target_blocks"],
                             case["id"])
        self.assertEqual(parse_target_blocks("示例：目标约 100 块积木"), 100)
        self.assertIsNone(parse_target_blocks("没有规模句"))

    def test_find_by_id_and_desc(self):
        self.assertEqual(find_m_case("m01")["id"], "M01")
        self.assertEqual(find_m_case(" M20 ")["id"], "M20")
        self.assertEqual(find_m_case(desc=M_CASES[11]["desc"])["id"], "M12")
        self.assertIsNone(find_m_case("M99"))
        self.assertIsNone(find_m_case(desc="不存在原文"))
        self.assertIsNone(find_m_case())


# ---------------------------------------------------------------- 2. 需求原文冻结
class FrozenHashTest(unittest.TestCase):
    def test_hashes_frozen_and_stable(self):
        hashes = frozen_hashes()
        self.assertEqual(list(hashes), M_EXPECTED_IDS)
        self.assertEqual(hashes, FROZEN_DESC_SHA256)
        for case in M_CASES:
            digest = hashlib.sha256(case["desc"].encode("utf-8")).hexdigest()
            self.assertEqual(hashes[case["id"]], digest, case["id"])
            self.assertEqual(case_hash(case), digest, case["id"])
            self.assertEqual(len(digest), 64)

    def test_audit_passes(self):
        report = audit_m_cases()
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["count"], 20)
        self.assertEqual(report["ids"], M_EXPECTED_IDS)
        self.assertEqual(report["tier_counts"], M_TIER_COUNTS)
        self.assertIn(report["doc_matches"], (True, None))

    def test_audit_detects_changed_desc(self):
        cases = [dict(case) for case in M_CASES]
        cases[0]["desc"] = cases[0]["desc"].replace("100", "999")
        report = audit_m_cases(cases, check_doc=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("冻结哈希" in p for p in report["problems"]), report["problems"])

    def test_audit_detects_bad_tier_and_count(self):
        cases = [dict(case) for case in M_CASES]
        cases[1]["tier"] = "超难"
        report = audit_m_cases(cases, check_doc=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("档位" in p for p in report["problems"]), report["problems"])
        report2 = audit_m_cases(M_CASES[:-1], check_doc=False)
        self.assertFalse(report2["ok"])
        self.assertTrue(any("数量" in p for p in report2["problems"]), report2["problems"])


class CaseCliTest(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cases_main(argv)
        return code, buf.getvalue()

    def test_list(self):
        code, out = self._run(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("共 20 例", out)
        for case_id in M_EXPECTED_IDS:
            self.assertIn(case_id, out)

    def test_hash(self):
        code, out = self._run(["--hash"])
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(lines), 20)
        for line, case_id in zip(lines, M_EXPECTED_IDS):
            self.assertIn(case_id, line)
            self.assertIn(FROZEN_DESC_SHA256[case_id], line)

    def test_audit(self):
        code, out = self._run(["--audit"])
        self.assertEqual(code, 0)
        self.assertIn("审计通过", out)

    def test_default_json(self):
        code, out = self._run([])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 20)
        self.assertEqual([item["id"] for item in data], M_EXPECTED_IDS)


# ---------------------------------------------------------------- 3. 新增几何原语
class PrimitiveTest(unittest.TestCase):
    def test_storeys_min(self):
        tall = {(x, y, 0) for y in range(3) for x in range(4)}
        model = model_from_cells(tall, 5, 1)
        self.assertEqual(check("storeys_min", ctx_of(model), 2, 4), [])
        self.assertTrue(check("storeys_min", ctx_of(model), 4, 4))
        flat = {(x, 0, 0) for x in range(4)}
        model2 = model_from_cells(flat, 5, 1)
        self.assertTrue(check("storeys_min", ctx_of(model2), 2, 4))

    def test_part_color_ratio_min(self):
        cells = {(x, 2, 0) for x in range(4)}
        colors = {cell: "R" for cell in cells}
        model = model_from_cells(cells, 6, 1, parts=[make_part("roof", "屋顶", cells)],
                                 colors=colors)
        self.assertEqual(check("part_color_ratio_min", ctx_of(model),
                               ("屋顶",), "R", 0.5), [])
        model2 = model_from_cells(cells, 6, 1,
                                  parts=[make_part("roof", "屋顶", cells)],
                                  colors={cell: "L" for cell in cells})
        self.assertTrue(check("part_color_ratio_min", ctx_of(model2),
                              ("屋顶",), "R", 0.5))

    def test_sloped_part_min(self):
        cells = {(0, 2, 0), (1, 2, 0), (2, 2, 0)}
        chars = {(0, 2, 0): "/", (2, 2, 0): "\\"}
        model = model_from_cells(cells, 3, 1, parts=[make_part("roof", "屋顶", cells)],
                                 chars=chars)
        self.assertEqual(check("sloped_part_min", ctx_of(model), ("屋顶",), 2), [])
        flat = model_from_cells(cells, 3, 1, parts=[make_part("roof", "屋顶", cells)])
        self.assertTrue(check("sloped_part_min", ctx_of(flat), ("屋顶",), 2))

    def test_exposed_color_min(self):
        nose_cells = {(2, 3, 0)}
        body_cells = {(x, y, 0) for x in range(5) for y in range(3)}
        colors = {cell: "L" for cell in body_cells}
        colors.update({cell: "K" for cell in nose_cells})
        model = model_from_cells(body_cells | nose_cells, 5, 1,
                                 parts=[make_part("body", "身体", body_cells),
                                        make_part("nose", "鼻子", nose_cells, "surface")],
                                 colors=colors)
        self.assertEqual(check("exposed_color_min", ctx_of(model),
                               ("鼻子",), 1, "K", ("身体",)), [])
        # 同色（与主体无对比）不算异色；指定色系不符也不算
        same = model_from_cells(body_cells | nose_cells, 5, 1,
                                parts=[make_part("body", "身体", body_cells),
                                       make_part("nose", "鼻子", nose_cells, "surface")],
                                colors={cell: "L" for cell in body_cells | nose_cells})
        self.assertTrue(check("exposed_color_min", ctx_of(same),
                              ("鼻子",), 1, "K", ("身体",)))

    def test_windows_evidenced_color_patches(self):
        wall = {(x, 2, 0) for x in range(6)}
        windows = {(0, 2, 0), (5, 2, 0)}
        colors = {cell: "L" for cell in wall}
        colors.update({cell: "B" for cell in windows})
        shape = model_from_cells(wall, 6, 1,
                                 parts=[make_part("wall", "墙体", wall),
                                        make_part("win", "窗户", windows, "surface")],
                                 colors=colors)
        self.assertEqual(check("windows_evidenced", ctx_of(shape), ("窗户",), ("墙体",), 2), [])
        # 窗与墙体同色 → 外露异色路径失败
        same = model_from_cells(wall, 6, 1,
                                parts=[make_part("wall", "墙体", wall),
                                       make_part("win", "窗户", windows, "surface")],
                                colors={cell: "L" for cell in wall})
        self.assertTrue(check("windows_evidenced", ctx_of(same), ("窗户",), ("墙体",), 2))

    def test_windows_evidenced_real_openings(self):
        need = [(2, 1, 0), (4, 1, 0)]  # 两处 1 格宽真实开洞
        cells = {(x, y, 0) for x in range(7) for y in range(3)} - set(need)
        win_ring = {(1, 1, 0), (3, 1, 0), (5, 1, 0)}
        model = model_from_cells(cells, 7, 1,
                                 parts=[make_part("wall", "墙体", cells - win_ring),
                                        make_part("win", "窗户", win_ring, "surface")])
        self.assertEqual(check("windows_evidenced", ctx_of(model), ("窗户",), ("墙体",), 2), [])
        one_hole = [(2, 1, 0)]
        cells2 = {(x, y, 0) for x in range(7) for y in range(3)} - set(one_hole)
        model2 = model_from_cells(cells2, 7, 1,
                                  parts=[make_part("wall", "墙体", cells2),
                                         make_part("win", "窗户", {(1, 1, 0)}, "surface")])
        self.assertTrue(check("windows_evidenced", ctx_of(model2), ("窗户",), ("墙体",), 2))

    def test_part_above_below_ref(self):
        body = {(x, 0, 0) for x in range(3)}
        head = {(x, 4, 0) for x in range(2)}
        model = model_from_cells(body | head, 4, 1,
                                 parts=[make_part("body", "身体", body),
                                        make_part("head", "头部", head)])
        self.assertEqual(check("part_above_ref", ctx_of(model), ("头部",), ("身体",), 1), [])
        self.assertTrue(check("part_above_ref", ctx_of(model), ("身体",), ("头部",), 1))
        self.assertTrue(check("part_below_ref", ctx_of(model), ("头部",), ("身体",), 1))

    def test_tapered_parts_min(self):
        ear_a = {(0, 0, 0), (1, 0, 0), (2, 0, 0), (1, 1, 0)}
        ear_b = {(5, 0, 0), (6, 0, 0), (7, 0, 0), (6, 1, 0)}
        cells = ear_a | ear_b
        model = model_from_cells(cells, 8, 1, parts=[make_part("ear", "耳朵", cells)])
        self.assertEqual(check("tapered_parts_min", ctx_of(model), ("耳朵",), 2, 0.7), [])
        block = {(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0),
                 (4, 0, 0), (5, 0, 0), (4, 1, 0), (5, 1, 0)}
        model2 = model_from_cells(block, 6, 1, parts=[make_part("ear", "耳朵", block)])
        self.assertTrue(check("tapered_parts_min", ctx_of(model2), ("耳朵",), 2, 0.7))

    def test_pair_sides_min(self):
        cells = {(0, 0, 0), (4, 0, 0)}
        model = model_from_cells(cells, 5, 1, parts=[make_part("arm", "手臂", cells)])
        self.assertEqual(check("pair_sides_min", ctx_of(model), ("手臂",), 1, "x"), [])
        same_side = {(0, 0, 0), (1, 0, 0)}
        model2 = model_from_cells(same_side, 5, 1, parts=[make_part("arm", "手臂", same_side)])
        self.assertTrue(check("pair_sides_min", ctx_of(model2), ("手臂",), 1, "x"))

    def test_pair_sides_min_ref_axis(self):
        """给出参照物时按参照长轴分首尾（纵向）：前后各一块通过，全在尾部失败。"""
        hull = {(x, 0, 0) for x in range(2, 5)}
        rudders = {(0, 0, 0), (5, 0, 0)}
        model = model_from_cells(hull | rudders, 6, 1,
                                 parts=[make_part("hull", "艇身", hull),
                                        make_part("rud", "舵", rudders)])
        self.assertEqual(check("pair_sides_min", ctx_of(model), ("舵",), 1, "auto",
                               ("艇身",)), [])
        tail_only = {(4, 0, 0), (5, 0, 0)}
        model2 = model_from_cells(hull | tail_only, 6, 1,
                                  parts=[make_part("hull", "艇身", hull),
                                         make_part("rud", "舵", tail_only)])
        self.assertTrue(check("pair_sides_min", ctx_of(model2), ("舵",), 1, "auto",
                              ("艇身",)))

    def test_part_extends_beyond(self):
        head = {(x, 2, 0) for x in range(2, 5)}
        ears = {(0, 2, 0), (6, 2, 0)}
        model = model_from_cells(head | ears, 7, 1,
                                 parts=[make_part("head", "头部", head),
                                        make_part("ear", "耳朵", ears)])
        self.assertEqual(check("part_extends_beyond", ctx_of(model), ("耳朵",), ("头部",),
                               "x", 1), [])
        inside = {(2, 2, 0), (4, 2, 0)}
        model2 = model_from_cells(head | inside, 7, 1,
                                  parts=[make_part("head", "头部", head),
                                         make_part("ear", "耳朵", inside)])
        self.assertTrue(check("part_extends_beyond", ctx_of(model2), ("耳朵",), ("头部",),
                              "x", 1))

    def test_crenellated_top_min(self):
        body = {(x, y, 0) for x in range(5) for y in range(2)}
        merlons = {(0, 2, 0), (2, 2, 0), (4, 2, 0)}
        cells = body | merlons
        model = model_from_cells(cells, 5, 1, parts=[make_part("wall", "城墙", cells)])
        self.assertEqual(check("crenellated_top_min", ctx_of(model), ("城墙",), 2), [])
        flat = {(x, y, 0) for x in range(5) for y in range(3)}
        model2 = model_from_cells(flat, 5, 1, parts=[make_part("wall", "城墙", flat)])
        self.assertTrue(check("crenellated_top_min", ctx_of(model2), ("城墙",), 2))

    def _bridge_model(self, gap_starts):
        deck = {(x, 3, z) for x in range(14) for z in range(3)}
        piers = set()
        for start in gap_starts:
            piers |= {(x, y, z) for x in range(start, start + 2)
                      for y in range(3) for z in range(3)}
        piers |= {(0, y, z) for y in range(3) for z in range(3)}
        piers |= {(13, y, z) for y in range(3) for z in range(3)}
        return model_from_cells(deck | piers, 14, 3,
                                parts=[make_part("deck", "桥面", deck),
                                       make_part("piers", "桥墩", piers)])

    def test_negative_space_passages_min(self):
        model = self._bridge_model([4, 8])  # 两个桥墩 + 两端桥台 → 3 个独立拱洞
        self.assertEqual(check("negative_space_passages_min", ctx_of(model),
                               ("桥墩",), "auto", 3, 2, 1), [])
        model2 = self._bridge_model([6])  # 中间一个桥墩 → 2 个拱洞
        self.assertTrue(check("negative_space_passages_min", ctx_of(model2),
                              ("桥墩",), "auto", 3, 2, 1))

    def test_thin_plate_min(self):
        sail = {(x, 0, z) for x in range(4) for z in range(2)}
        model = model_from_cells(sail, 5, 2, parts=[make_part("sail", "船帆", sail)])
        self.assertEqual(check("thin_plate_min", ctx_of(model), ("船帆",), 3, 2), [])
        block = {(x, y, z) for x in range(4) for y in range(3) for z in range(3)}
        model2 = model_from_cells(block, 4, 3, parts=[make_part("sail", "船帆", block)])
        self.assertTrue(check("thin_plate_min", ctx_of(model2), ("船帆",), 3, 2))

    def test_part_levels_min(self):
        platforms = set()
        for y in (1, 5, 9):
            platforms |= {(x, y, 0) for x in range(4)}
        model = model_from_cells(platforms, 5, 1,
                                 parts=[make_part("plat", "平台", platforms)])
        self.assertEqual(check("part_levels_min", ctx_of(model), ("平台",), 3, 2), [])
        single = {(x, 1, 0) for x in range(4)}
        model2 = model_from_cells(single, 5, 1, parts=[make_part("plat", "平台", single)])
        self.assertTrue(check("part_levels_min", ctx_of(model2), ("平台",), 3, 2))

    def test_corner_towers_min(self):
        walls = {(x, 0, 0) for x in range(8)} | {(x, 0, 7) for x in range(8)}
        walls |= {(0, 0, z) for z in range(8)} | {(7, 0, z) for z in range(8)}
        towers = {(0, 2, 0), (0, 2, 7), (7, 2, 0), (7, 2, 7)}
        model = model_from_cells(walls | towers, 8, 8,
                                 parts=[make_part("wall", "城墙", walls),
                                        make_part("tower", "角楼", towers)])
        self.assertEqual(check("corner_towers_min", ctx_of(model), ("角楼",), ("城墙",), 4), [])
        row = {(0, 2, 0), (2, 2, 0), (4, 2, 0), (6, 2, 0)}
        model2 = model_from_cells(walls | row, 8, 8,
                                  parts=[make_part("wall", "城墙", walls),
                                         make_part("tower", "角楼", row)])
        self.assertTrue(check("corner_towers_min", ctx_of(model2), ("角楼",), ("城墙",), 4))

    def test_legs_splay_min(self):
        left = {(0, 0, 0), (1, 0, 0), (2, 0, 0), (2, 2, 0), (3, 2, 0)}
        right = {(7, 0, 0), (8, 0, 0), (9, 0, 0), (6, 2, 0), (7, 2, 0)}
        cells = left | right
        model = model_from_cells(cells, 6, 1, parts=[make_part("leg", "塔腿", cells)])
        self.assertEqual(check("legs_splay_min", ctx_of(model), ("塔腿",), 1.0, 0), [])
        straight = {(0, 0, 0), (0, 1, 0), (5, 0, 0), (5, 1, 0)}
        model2 = model_from_cells(straight, 6, 1, parts=[make_part("leg", "塔腿", straight)])
        self.assertTrue(check("legs_splay_min", ctx_of(model2), ("塔腿",), 1.0, 0))

    def test_center_void_min(self):
        ring = {(x, y, z) for y in range(3) for x in (0, 7) for z in range(8)}
        ring |= {(x, y, z) for y in range(3) for x in range(1, 7) for z in (0, 7)}
        model = model_from_cells(ring, 8, 8, parts=[make_part("tower", "塔身", ring)])
        self.assertEqual(check("center_void_min", ctx_of(model), ("塔身",), 4), [])
        solid = {(x, y, z) for x in range(8) for y in range(3) for z in range(8)}
        model2 = model_from_cells(solid, 8, 8, parts=[make_part("tower", "塔身", solid)])
        self.assertTrue(check("center_void_min", ctx_of(model2), ("塔身",), 4))

    def test_shell_roof_min(self):
        shell_a = {(0, 1, 0), (1, 1, 0), (2, 1, 0), (1, 2, 0)}
        shell_b = {(4, 1, 0), (5, 1, 0), (6, 1, 0), (5, 2, 0), (5, 3, 0)}
        cells = shell_a | shell_b
        chars = {(1, 2, 0): "/", (5, 3, 0): "\\"}
        model = model_from_cells(cells, 7, 1, parts=[make_part("roof", "屋顶", cells)],
                                 chars=chars)
        self.assertEqual(check("shell_roof_min", ctx_of(model), ("屋顶",), 2, 2, 2), [])
        flat = {(x, 1, 0) for x in range(6)}
        model2 = model_from_cells(flat, 6, 1, parts=[make_part("roof", "屋顶", flat)])
        self.assertTrue(check("shell_roof_min", ctx_of(model2), ("屋顶",), 2, 2, 2))

    def test_perimeter_objects_min(self):
        ring = {(x, 0, 0) for x in range(10)} | {(x, 9, 0) for x in range(10)}
        ring |= {(0, y, 0) for y in range(10)} | {(9, y, 0) for y in range(10)}
        cabins = {(9, 2, 1), (9, 7, 1), (0, 2, 1), (0, 7, 1),
                  (2, 0, 1), (7, 0, 1), (2, 9, 1), (7, 9, 1)}
        model = model_from_cells(ring | cabins, 10, 2,
                                 parts=[make_part("rim", "轮缘", ring),
                                        make_part("cab", "吊舱", cabins)])
        self.assertEqual(check("perimeter_objects_min", ctx_of(model), ("吊舱",), ("轮缘",),
                               8, 8, 0.5), [])
        few = {(9, 2, 1), (9, 7, 1), (0, 2, 1)}
        model2 = model_from_cells(ring | few, 10, 2,
                                  parts=[make_part("rim", "轮缘", ring),
                                         make_part("cab", "吊舱", few)])
        self.assertTrue(check("perimeter_objects_min", ctx_of(model2), ("吊舱",), ("轮缘",),
                              8, 8, 0.5))

    def test_parts_union_components_and_adjacent_any(self):
        a = {(0, 0, 0), (1, 0, 0)}
        b = {(2, 0, 0), (3, 0, 0)}
        model = model_from_cells(a | b, 4, 1,
                                 parts=[make_part("wall", "城墙", a),
                                        make_part("roof", "屋顶", b)])
        self.assertEqual(check("parts_union_components", ctx_of(model),
                               [("城墙",), ("屋顶",)], 1), [])
        gap = {(2, 2, 0)}
        model2 = model_from_cells(a | gap, 4, 1,
                                  parts=[make_part("wall", "城墙", a),
                                         make_part("roof", "屋顶", gap)])
        self.assertTrue(check("parts_union_components", ctx_of(model2),
                              [("城墙",), ("屋顶",)], 1))
        body = {(0, 0, 0)}
        wing = {(1, 0, 0)}
        engine = {(0, 1, 0)}
        model3 = model_from_cells(body | wing | engine, 2, 1,
                                  parts=[make_part("body", "机身", body),
                                         make_part("wing", "机翼", wing),
                                         make_part("eng", "引擎", engine)])
        self.assertEqual(check("parts_adjacent_any", ctx_of(model3), ("引擎",),
                               [("机翼",), ("机身",)], 1), [])
        far = {(5, 1, 0)}
        model4 = model_from_cells(body | wing | far, 6, 1,
                                  parts=[make_part("body", "机身", body),
                                         make_part("wing", "机翼", wing),
                                         make_part("eng", "引擎", far)])
        self.assertTrue(check("parts_adjacent_any", ctx_of(model4), ("引擎",),
                              [("机翼",), ("机身",)], 1))

    def test_radial_spokes_min(self):
        ring = {(x, 0, 0) for x in range(10)} | {(x, 9, 0) for x in range(10)}
        ring |= {(0, y, 0) for y in range(10)} | {(9, y, 0) for y in range(10)}
        spokes = {(x, 4, 0) for x in range(1, 9)} | {(4, y, 0) for y in range(1, 9)}
        model = model_from_cells(ring | spokes, 10, 1,
                                 parts=[make_part("rim", "轮缘", ring),
                                        make_part("spoke", "辐条", spokes)])
        self.assertEqual(check("radial_spokes_min", ctx_of(model), ("辐条",), ("轮缘",),
                               4, 0.5), [])
        model2 = model_from_cells(ring, 10, 1,
                                  parts=[make_part("rim", "轮缘", ring)])
        self.assertTrue(check("radial_spokes_min", ctx_of(model2), ("辐条",), ("轮缘",),
                              4, 0.5))

    def test_wall_opening_min(self):
        w = d = 8
        solid = set()
        for y in range(5):
            for x in range(w):
                for z in range(d):
                    if x in (0, w - 1) or z in (0, d - 1):
                        solid.add((x, y, z))
        door = {(x, y, z) for y in range(3) for x in (3, 4) for z in (0, 1)}
        house = solid - door
        model = model_from_cells(house, w, d,
                                 parts=[make_part("wall", "墙体", house)])
        self.assertEqual(check("wall_opening_min", ctx_of(model), ("墙体",), 2, 1), [])
        closed = model_from_cells(solid, w, d,
                                  parts=[make_part("wall", "墙体", solid)])
        self.assertTrue(check("wall_opening_min", ctx_of(closed), ("墙体",), 2, 1))
        # 开口只在顶部（窗洞，不落地）不算门洞
        window = {(x, y, z) for y in (3, 4) for x in (3, 4) for z in (0, 1)}
        windowed = solid - window
        model3 = model_from_cells(windowed, w, d,
                                  parts=[make_part("wall", "墙体", windowed)])
        self.assertTrue(check("wall_opening_min", ctx_of(model3), ("墙体",), 2, 1))


# ---------------------------------------------------------------- 4. check_objects_m
class CheckObjectsMTest(unittest.TestCase):
    def setUp(self):
        """统一校验按同一模型重算；合成模型/方案只需校验桩放行。"""
        patcher = mock.patch("tools.e2e_assert.validate_solution",
                             return_value={"ok": True, "errors": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fast_positive_path_and_metrics(self):
        errors, metrics = check_objects_m(
            _fake_record(), _fake_model(), _fake_solution(5), _fake_case())
        self.assertEqual(errors, [], errors)
        self.assertTrue(metrics["assertion_ok"])
        self.assertEqual(metrics["suite"], "M")
        self.assertEqual(metrics["tier"], "简单")
        self.assertEqual(metrics["target_blocks"], 10)
        self.assertEqual(metrics["bricks"], 5)
        self.assertEqual(metrics["bricks_ratio"], 0.5)
        self.assertTrue(metrics["target_blocks_ok"])
        self.assertTrue(metrics["mode_facts_ok"])
        self.assertEqual(metrics["mode"], "fast")
        self.assertFalse(metrics["mode_review_present"])
        self.assertIsNone(metrics["mode_review_flag"])
        self.assertEqual(metrics["mode_revise_visual"], 0)
        self.assertIsNone(metrics["mode_fallback_count"])
        self.assertEqual(metrics["generic_tier"], [])
        self.assertIsInstance(metrics["requirement_tier"], dict)
        self.assertEqual(metrics["requirement_tier"]["feature_checks"][0]["name"],
                         "layers_min")
        self.assertEqual(metrics["desc_hash"], case_hash(_fake_case()))
        self.assertIsNone(metrics["review_overall"])
        self.assertEqual(metrics["review"], {})
        for key in ("case", "name", "run_id", "task_ok", "mode", "parts", "solid_parts",
                    "surface_parts", "voxels", "ops", "layers", "grid", "colors",
                    "draw_attempts", "draw_requests", "assertion_errors", "mode_facts"):
            self.assertIn(key, metrics, key)

    def test_target_ratio_below_50_percent_fails(self):
        errors, metrics = check_objects_m(
            _fake_record(), _fake_model(), _fake_solution(3), _fake_case())
        self.assertTrue(any("目标块数未达标" in e for e in errors), errors)
        self.assertFalse(metrics["target_blocks_ok"])
        self.assertEqual(metrics["requirement_tier"]["target_blocks_ok"], False)

    def test_fast_mode_fact_violations(self):
        review = {"scores": {"overall": 8.0}}
        errors, _ = check_objects_m(
            _fake_record(review=review), _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("视觉评审结果" in e for e in errors), errors)
        errors, _ = check_objects_m(
            _fake_record(counts=_fast_counts(revise_visual=2)), _fake_model(),
            _fake_solution(5), _fake_case())
        self.assertTrue(any("视觉修订 2 次" in e for e in errors), errors)
        errors, _ = check_objects_m(
            _fake_record(counts={}), _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("revise_visual" in e for e in errors), errors)
        errors, _ = check_objects_m(
            _fake_record(outcome="fast_fallback"), _fake_model(), _fake_solution(5),
            _fake_case())
        self.assertTrue(any("快速不得触发自动保底" in e for e in errors), errors)
        errors, _ = check_objects_m(
            _fake_record(attempts_detail=[{"mode": "fast", "ok": True}]),
            _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("自动保底尝试 1 次" in e for e in errors), errors)

    def test_fast_review_fallback_is_violation(self):
        """旧记录从任务结果补入 review 时，快速模式同样不得出现评审。"""
        errors, metrics = check_objects_m(
            _fake_record(), _fake_model(), _fake_solution(5), _fake_case(),
            review_fallback={"scores": {"overall": 7.0}})
        self.assertTrue(any("视觉评审结果" in e for e in errors), errors)
        self.assertEqual(metrics["review_source"], "task_result")

    def test_fidelity_mode_facts(self):
        good = _fake_record(mode="fidelity",
                            counts=_fast_counts(revise_visual=2),
                            review={"scores": {"overall": 8.5}})
        errors, metrics = check_objects_m(good, _fake_model(), _fake_solution(5),
                                          _fake_case())
        self.assertEqual(errors, [])
        self.assertEqual(metrics["review_overall"], 8.5)
        self.assertEqual(metrics["mode_review_flag"], None)
        # 如实不可用标记（无 review、reviewFlag=review_unavailable）允许
        unavailable = _fake_record(mode="fidelity", reviewFlag="review_unavailable")
        errors, metrics = check_objects_m(unavailable, _fake_model(), _fake_solution(5),
                                          _fake_case())
        self.assertEqual(errors, [], errors)
        self.assertTrue(metrics["mode_facts"]["review_unavailable"])
        # 既无评审也无不可用标记 → 失败
        missing = _fake_record(mode="fidelity")
        errors, _ = check_objects_m(missing, _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("缺少视觉评审结果" in e for e in errors), errors)
        # 旧记录 review 缺失 + review_fallback 补入 → 视为有评审
        errors, metrics = check_objects_m(
            _fake_record(mode="fidelity"), _fake_model(), _fake_solution(5),
            _fake_case(), review_fallback={"scores": {"overall": 9.0}})
        self.assertEqual(errors, [])
        self.assertEqual(metrics["review_overall"], 9.0)

    def test_fidelity_fallback_count_rules(self):
        fallback_ok = _fake_record(
            mode="fidelity", outcome="fast_fallback",
            attempts_detail=[{"mode": "fidelity", "ok": False},
                             {"mode": "fast", "ok": True}])
        errors, metrics = check_objects_m(fallback_ok, _fake_model(), _fake_solution(5),
                                          _fake_case())
        self.assertEqual(errors, [], errors)
        self.assertEqual(metrics["mode_fallback_count"], 1)
        two = _fake_record(
            mode="fidelity", outcome="fast_fallback",
            attempts_detail=[{"mode": "fast", "ok": True}, {"mode": "fast", "ok": True}])
        errors, _ = check_objects_m(two, _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("> 1" in e for e in errors), errors)
        delivered = _fake_record(
            mode="fidelity", outcome="fidelity_degraded",
            reviewFlag="review_unavailable",
            attempts_detail=[{"mode": "fidelity", "ok": True},
                             {"mode": "fast", "ok": True}])
        errors, _ = check_objects_m(delivered, _fake_model(), _fake_solution(5),
                                    _fake_case())
        self.assertTrue(any("已交付却发生" in e for e in errors), errors)

    def test_desc_frozen_guard(self):
        record = _fake_record(desc="被改过的需求原文")
        errors, metrics = check_objects_m(record, _fake_model(), _fake_solution(5),
                                          _fake_case())
        self.assertTrue(any("跑中改题" in e for e in errors), errors)
        self.assertFalse(metrics["desc_frozen"])

    def test_unknown_check_is_config_error(self):
        errors, _ = check_objects_m(
            _fake_record(), _fake_model(), _fake_solution(5),
            _fake_case(checks=[["不存在的检查", 1]]))
        self.assertTrue(any("未知检查" in e for e in errors), errors)

    def test_review_stale_and_task_failure(self):
        errors, _ = check_objects_m(
            _fake_record(reviewStale=True), _fake_model(), _fake_solution(5), _fake_case())
        self.assertTrue(any("评审已过期" in e for e in errors), errors)
        errors, _ = check_objects_m(
            {"ok": False, "runId": "x", "error": "生成失败", "revision": 1,
             "artifacts": {}, "mode": "fast", "counts": _fast_counts(),
             "desc": FAKE_DESC},
            {}, {}, _fake_case())
        self.assertTrue(any("运行未成功" in e for e in errors), errors)

    def test_draw_requests_is_max_not_sum(self):
        cases = [
            ([{"request": 1}, {"request": 2}, {"request": 3}], 3),
            ([], 0),
            ([{"request": 1}, {"request": 3}], 3),
            ([{"request": None}, {"request": 2}], 2),
        ]
        for attempts, expected in cases:
            _errors, metrics = check_objects_m(
                _fake_record(drawAttempts=attempts), _fake_model(), _fake_solution(5),
                _fake_case())
            self.assertEqual(metrics["draw_requests"], expected, attempts)
            self.assertEqual(metrics["draw_attempts"], len(attempts))

    def test_required_parts_missing_fails(self):
        cells = {(0, 0, 0), (1, 0, 0)}
        model = model_from_cells(cells, 2, 1, 1, [])
        errors, metrics = check_objects_m(
            _fake_record(), model, _fake_solution(5),
            _fake_case(require_parts=[("身体", ("身体", "body"))]))
        self.assertTrue(any("部位清单缺少身体" in e for e in errors), errors)
        self.assertFalse(metrics["assertion_ok"])


if __name__ == "__main__":
    unittest.main()
