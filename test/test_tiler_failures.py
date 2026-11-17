# -*- coding: utf-8 -*-
"""tiler 结构化失败与预算测试。

覆盖：不连通 / 支撑 / 库存 / 统一校验 / 内部错误分别进入规定路径；
重铺期间体素不变；时间预算与下层复用。
"""
import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler  # noqa: E402
from legogod.parts_library import PART_MAP  # noqa: E402


def _model(layers_rows, colors=None):
    """layers_rows: [ [row, ...], ... ] 自下而上。"""
    layers = []
    for y, rows in enumerate(layers_rows):
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["层"],
                       "color": (colors or {}).get(y), "colorRows": None,
                       "count": len(cells)})
    grid_d = len(layers_rows[0])
    grid_w = len(layers_rows[0][0])
    return {"grid": {"w": grid_w, "d": grid_d},
            "totalVoxels": sum(len(L["cells"]) for L in layers), "layers": layers}


def _dump(model):
    return json.dumps(model, ensure_ascii=False, sort_keys=True)


class FailureKindTest(unittest.TestCase):
    def test_disconnected_single_layer_two_bricks(self):
        """单层两块互不相连的 1x1：零件图不连通 → disconnected，重铺 8 轮仍失败。"""
        model = _model([["#..#"]])
        sol, failure = tiler.solve_with_budget(model, model["layers"])
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "disconnected")
        self.assertIn("offer", failure)
        self.assertEqual(failure.get("rounds"), tiler.ROUNDS + tiler.CROSS_SEAM_ROUNDS)

    def test_disconnected_window_is_all_loose_voxels(self):
        """10 个互不相连的 1×1：提示 cells 只含最多 8 块，window_cells 含全部分游离体素，且不删体素。"""
        row = "#." * 10
        row = row[:19]  # 10 个 #，两两隔一格
        model = _model([row])
        before = _dump(model)
        sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=1, deadline=time.time() + 20)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "disconnected")
        self.assertEqual(_dump(model), before, "断连失败不得改体素")
        window = [tuple(c) for c in failure["window_cells"]]
        hinted = [tuple(c) for c in failure["cells"]]
        self.assertEqual(len(window), 9, "10 块里 1 块算主体，其余 9 块都应进窗口")
        self.assertEqual(len(hinted), 8)
        self.assertTrue(set(hinted) < set(window))

    def test_support_precheck_failure(self):
        """8×8 平板只压在中心 1×1 柱上：四角无论如何铺砖都无支撑 → support。"""
        base = [["." for _ in range(8)] for _ in range(8)]
        base[3][3] = "#"
        rows0 = ["".join(r) for r in base]
        model = _model([rows0, ["########"] * 8])
        before = _dump(model)
        sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=2)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "support")
        self.assertTrue(failure["cells"], "支撑失败要给出错误格")
        self.assertEqual(_dump(model), before, "支撑失败不得改体素")
        window = failure.get("window_cells") or []
        self.assertTrue(window, "支撑失败要给出全量无支撑格")
        self.assertLess(len(window), len(failure["cells"]), "window_cells 不能是整层截断")
        self.assertNotIn((3, 1, 3), window, "压在柱上的格不是无支撑格")
        self.assertIn((0, 1, 0), [tuple(c) for c in window])

    def test_inventory_exhaustion_detected(self):
        """全零件库存为 0：无限库存复跑可铺满 → inventory（不是 coverage）。"""
        model = _model([["####", "####"]])
        saved = {pid: p["count"] for pid, p in PART_MAP.items()}
        try:
            for p in PART_MAP.values():
                p["count"] = 0
            sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=1)
        finally:
            for pid, n in saved.items():
                PART_MAP[pid]["count"] = n
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "inventory")

    def test_internal_error_unknown_color(self):
        """层颜色不在颜色表中：internal，直接停止不重试。"""
        model = _model([["##"]], colors={0: "紫色"})
        sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=8)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "internal")

    def test_successful_model_returns_solution(self):
        model = _model([["####", "####"], ["####", "####"]])

        def vfn(m, s):
            return {"ok": True, "errors": []}

        sol, failure = tiler.solve_with_budget(model, model["layers"], validate_fn=vfn)
        self.assertIsNone(failure)
        self.assertTrue(sol["valid"])
        self.assertTrue(sol["steps"])
        self.assertEqual(sol["validation"], {"ok": True, "errors": []})

    def test_model_not_mutated_by_retiles(self):
        """重铺期间体素不变：solve_with_budget 不得修改模型数据。"""
        model = _model([["####", "####"], ["####", "####"]])
        before = _dump(model)
        tiler.solve_with_budget(model, model["layers"], rounds=3)
        self.assertEqual(_dump(model), before)


class ValidationMappingTest(unittest.TestCase):
    def test_stock_error_maps_to_inventory(self):
        failure = tiler._validation_failure({"ok": False, "errors": ["零件 B1x1 用了 2 块，库存只有 1"]})
        self.assertEqual(failure["kind"], "inventory")

    def test_geometry_error_maps_to_validation_and_parses_cells(self):
        failure = tiler._validation_failure(
            {"ok": False, "errors": ["体素 (x=1,y=0,z=2) 未被任何零件覆盖"]})
        self.assertEqual(failure["kind"], "validation")
        self.assertIn((1, 0, 2), failure["cells"])

    def test_suspension_window_is_copied_and_not_invented(self):
        """校验已经给出的锁扣坐标写入 window_cells；没有这份坐标时不编。"""
        with_window = tiler._validation_failure({
            "ok": False,
            "errors": ["（预拼子组件 1，y=1 层附近）吊挂子组件只有 1 个锁扣凸点"],
            "suspensionWindow": [(3, 1, 0)],
        })
        self.assertEqual(with_window["kind"], "suspension")
        self.assertEqual([tuple(c) for c in with_window["window_cells"]], [(3, 1, 0)])
        self.assertEqual(with_window["cells"], [])
        missing = tiler._validation_failure({
            "ok": False,
            "errors": ["（预拼子组件 1，y=4 层附近）吊挂子组件只有 1 个锁扣凸点"],
        })
        self.assertEqual(missing["kind"], "suspension")
        self.assertNotIn("window_cells", missing)


class BudgetTest(unittest.TestCase):
    def test_past_deadline_returns_budget_failure(self):
        model = _model([["####", "####"]])
        sol, failure = tiler.solve_with_budget(model, model["layers"],
                                               deadline=time.monotonic() - 1)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "coverage")
        self.assertTrue(failure.get("budget_exhausted"))
        self.assertIn("预算", failure["message"])

    def test_attempt_stops_at_deadline_without_tiling(self):
        """_attempt 在层循环开始处检查绝对截止：截止已过立即返回，不再铺砖。"""
        model = _model([["#" * 20] * 20])
        t0 = time.monotonic()
        sol, failure = tiler._attempt(model, model["layers"], seed=0,
                                      deadline=time.monotonic() - 1)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertIsNone(sol)
        self.assertIn("预算", failure["message"])

    def test_budget_exhaustion_message_not_claiming_unsolvable(self):
        """预算内未找到铺法不是造型无解：失败信息不得使用「无解/不可能」措辞。"""
        model = _model([["#..#"]])
        sol, failure = tiler.solve_with_budget(model, model["layers"],
                                               deadline=time.monotonic() - 1)
        self.assertIsNone(sol)
        self.assertNotIn("无解", failure["message"])
        self.assertNotIn("不可能", failure["message"])


class ReuseTest(unittest.TestCase):
    def test_reuse_prefix_rebuilds_upper_layer(self):
        """给定可恢复的库存/父件图/stud_owner 快照：保留下层铺法并只重铺上层。"""
        inventory = {p["id"]: p["count"] for p in PART_MAP.values()}
        prefix = [{"layer": 0, "piece": "B2x2", "rot": False, "x": 0, "z": 0,
                   "cells": [(0, 0), (1, 0), (0, 1), (1, 1)], "parents": set()}]
        reuse = {"layer": 1, "inventory": dict(inventory), "parts": prefix,
                 "adj": [set()], "stud_owner": {(0, 0): 0, (1, 0): 0, (0, 1): 0, (1, 1): 0}}
        model = _model([["##", "##"], ["##", "##"]])
        sol, failure = tiler._attempt(model, model["layers"], seed=1, reuse=reuse)
        self.assertIsNone(failure)
        self.assertEqual(len(sol["steps"]), 2)
        self.assertEqual(sol["steps"][0]["piece"], "B2x2")
        y1 = [s for s in sol["steps"] if s["layer"] == 1]
        self.assertEqual(len(y1), 1, "上层应只铺 1 块（下层来自复用前缀）")


class StructureFailureInfoTest(unittest.TestCase):
    """工作包 B：结构失败信息补全（原因码/组件界面/悬吊坐标）与铺法变体开关。"""

    def test_support_failure_carries_reason_codes(self):
        """支撑失败 info.supportReasons 给出稳定原因码与坐标。"""
        base = [["." for _ in range(8)] for _ in range(8)]
        base[3][3] = "#"
        rows0 = ["".join(r) for r in base]
        model = _model([rows0, ["########"] * 8])
        sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=1,
                                               log=lambda s: None)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "support")
        reasons = (failure.get("info") or {}).get("supportReasons") or {}
        self.assertTrue(reasons, failure)
        self.assertTrue(all("count" in entry and "cells" in entry
                            for entry in reasons.values()), reasons)
        self.assertIn("brick_support", reasons)

    def test_disconnected_failure_carries_component_info(self):
        """断连失败 info 给出两侧组件摘要与界面格，window_cells 仍是全量窗口。"""
        plan = {"name": "断连", "slug": "dc-info", "features": ["测试"],
                "layers": [{"module": "底", "color": "红色", "rows": ["##"],
                            "colorRows": ["RB"]}]}
        from legogod.agent import validate_design_syntax
        errs, model, _w = validate_design_syntax(plan)
        self.assertEqual(errs, [])
        sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=1,
                                               log=lambda s: None)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "disconnected")
        info = failure.get("info") or {}
        self.assertEqual(len(info.get("components") or []), 2)
        self.assertTrue(info.get("interfaceCells"))
        self.assertTrue(failure.get("window_cells"))

    def test_suspension_failure_copies_lock_and_subassembly_positions(self):
        """悬吊失败 info 带锁扣与子组件坐标；没有坐标时不写 info、不编位置。"""
        report = {"ok": False, "errors": ["吊挂子组件只有 1 个锁扣凸点"],
                  "suspensionWindow": [(3, 1, 0)],
                  "subassemblies": [{"bricks": [0], "hangingBricks": [0],
                                     "anchorBricks": []}]}
        solution = {"steps": [{"layer": 1, "piece": "B1x1", "x": 3, "z": 0,
                               "rotate": False}]}
        failure = tiler._validation_failure(report, solution)
        self.assertEqual(failure["kind"], "suspension")
        self.assertEqual([tuple(c) for c in failure["info"]["lockCells"]], [(3, 1, 0)])
        self.assertIn((3, 1, 0), [tuple(c) for c in failure["info"]["subassemblyCells"]])
        no_pos = tiler._validation_failure({"ok": False,
                                            "errors": ["吊挂子组件只有 1 个锁扣凸点"]})
        self.assertNotIn("info", no_pos)
        self.assertNotIn("window_cells", no_pos)

    def test_solver_variant_switches_keep_default_behavior(self):
        """border_first/merge_first_all 是候选专用铺法变体，默认不传仍按原逻辑成功。"""
        model = _model([["####", "####"], ["####", "####"]])
        sol, failure = tiler.solve_with_budget(model, model["layers"],
                                               validate_fn=lambda m, s: {"ok": True},
                                               border_first=True, merge_first_all=True)
        self.assertIsNotNone(sol, failure)
        self.assertTrue(sol["steps"])

    def test_should_stop_raises_tiler_cancelled(self):
        """取消语义：should_stop 为真时求解立即抛 TilerCancelled。"""
        model = _model([["####", "####"]])
        with self.assertRaises(tiler.TilerCancelled):
            tiler.solve_with_budget(model, model["layers"], should_stop=lambda: True)


if __name__ == "__main__":
    unittest.main()
