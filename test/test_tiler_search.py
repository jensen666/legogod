# -*- coding: utf-8 -*-
"""求解层通用改造 A′：层内搜索容量自适应。

验证三件事（与具体造型无关）：
1. solve_layer 接受 max_backtrack / restarts / deadline 参数并按预算工作；
2. _attempt 在同一层失败后按 SEARCH_LADDER 逐级加大预算重试，而不是直接整模重来；
3. 上层比下层外扩的合成几何（通用形状）在默认配置下可求解。
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler  # noqa: E402
from legogod.parts_library import PART_MAP  # noqa: E402


def _house(layer_rows):
    """layer_rows: [["####", ...], ...]（y=0 起）→ 最小 house（无颜色，走默认色零件）。"""
    layers = [{"y": y, "rows": list(rows), "color": None} for y, rows in enumerate(layer_rows)]
    solid = sum(r.count("#") for rows in layer_rows for r in rows)
    return {"grid": {"w": len(layer_rows[0][0]), "d": len(layer_rows[0])},
            "layers": layers, "totalVoxels": solid}


def _two_by_two_piece():
    for pid, p in PART_MAP.items():
        if p.get("w") == 2 and p.get("d") == 2:
            return pid
    raise AssertionError("零件库里没有 2x2")


class LayerBudgetTest(unittest.TestCase):
    def test_budget_parameter_limits_search(self):
        """同一层：极小预算失败、足够预算成功——证明预算参数真实生效。"""
        typed = {(x, z): "#" for z in range(4) for x in range(4)}
        below = dict(typed)   # 全部有支撑，唯一约束是精确覆盖本身
        inventory = {pid: 999 for pid in PART_MAP}
        tight = tiler.solve_layer(typed, below, dict(inventory), __import__("random").Random(0),
                                  max_backtrack=1, restarts=1)
        enough = tiler.solve_layer(typed, below, dict(inventory), __import__("random").Random(0),
                                   max_backtrack=100000, restarts=8)
        self.assertIsNone(tight, "预算 1 步不应搜到完整覆盖")
        self.assertIsNotNone(enough, "足够预算应能铺满该层")

    def test_deadline_stops_before_search(self):
        """已到截止：不再搜索，立即返回 None。"""
        typed = {(x, 0): "#" for x in range(3)}
        inventory = {pid: 999 for pid in PART_MAP}
        t0 = time.monotonic()
        out = tiler.solve_layer(typed, None, dict(inventory),
                                __import__("random").Random(0), deadline=t0 - 1)
        self.assertIsNone(out)
        self.assertLess(time.monotonic() - t0, 1.0)


class AttemptLadderTest(unittest.TestCase):
    def test_attempt_uses_exact_cover_after_fast_heuristic(self):
        """第一档启发式（含 allow=False/True）失败后，先进入精确覆盖而不是直接加大预算。"""
        house = _house([["##", "##"]])
        good = [(_two_by_two_piece(), False, 0, 0)]
        with mock.patch.object(tiler, "solve_layer", return_value=None) as m, \
                mock.patch.object(tiler, "solve_layer_exact", return_value=good) as me:
            sol, fail = tiler._attempt(house, house["layers"], seed=0, merge_first=False)
        self.assertIsNotNone(sol, fail)
        self.assertIsNone(fail)
        self.assertEqual(m.call_count, 2, "第一档 allow=False/True 各一次")
        self.assertEqual(me.call_count, 1, "第一档失败后进入精确覆盖（设计色优先）")

    def test_attempt_escalates_budget_after_exact_fails(self):
        """精确覆盖也失败后，才按 SEARCH_LADDER 加大启发式预算兜底。"""
        house = _house([["##", "##"]])
        good = [(_two_by_two_piece(), False, 0, 0)]
        calls = []

        def fake_layer(*a, **kw):
            calls.append(kw.get("max_backtrack"))
            return good if len(calls) == 3 else None

        with mock.patch.object(tiler, "solve_layer", side_effect=fake_layer), \
                mock.patch.object(tiler, "solve_layer_exact", return_value=None):
            sol, fail = tiler._attempt(house, house["layers"], seed=0, merge_first=False)
        self.assertIsNotNone(sol, fail)
        self.assertEqual(calls[0], tiler.SEARCH_LADDER[0][0])
        self.assertEqual(calls[2], tiler.SEARCH_LADDER[1][0], "第三次调用应是升级后的预算")

    def test_ladder_levels_are_increasing(self):
        budgets = [bt for bt, _ in tiler.SEARCH_LADDER]
        self.assertEqual(budgets, sorted(budgets))
        self.assertEqual(budgets[0], tiler.MAX_BACKTRACK)


class ConnectivityReplayTest(unittest.TestCase):
    """B′：零件级断开时的定向重铺（与具体造型无关的合成几何）。"""

    def test_two_layer_same_outline_solvable_10x10(self):
        """两层同轮廓 10x10：默认铺法靠组件交界优先重铺后能连通成一体。"""
        rows = ["##########"] * 10
        house = _house([rows, rows])
        sol, fail = tiler.solve_with_budget(
            house, house["layers"], deadline=time.monotonic() + 30, log=lambda s: None)
        self.assertIsNotNone(sol, fail)
        self.assertEqual(len(sol["steps"]), 20)

    def test_disconnected_offer_requests_border_replay(self):
        """断开失败必须给出「从断裂层上方重铺 + 组件交界优先」的定向重铺 offer。

        （原夹具为 8×8 菱形双层同轮廓——正交奇偶扫描 + 字典序错缝落地后该模型
        已能真正连通求解，故改用物理上不可能连通的双 1x1 独塔夹具，验证意图不变。）
        """
        rows = ["#..#", "#..#", "#..#", "#..#"]
        house = _house([rows, rows])
        sol, fail = tiler._attempt(house, house["layers"], seed=0, merge_first=False)
        self.assertIsNone(sol)
        self.assertEqual(fail["kind"], "disconnected")
        offer = fail.get("offer") or {}
        self.assertTrue(offer.get("border_first"), "定向重铺应开启组件交界优先")
        self.assertEqual(offer.get("layer"), 1, "底层断开应从 y=1 起重铺，保留 y=0")


class ExactCoverTest(unittest.TestCase):
    """精确覆盖铺层：贪心搜索不到的层也能确定性求解，且满足库存约束。"""

    def test_exact_cover_solves_widened_layer(self):
        typed = {(x, z): "#" for z in range(8) for x in range(8)}
        below = {(x, z) for x in range(1, 7) for z in range(1, 7)}   # 每边外扩 1 格
        inv = {pid: 999 for pid in PART_MAP}
        exact = tiler.solve_layer_exact(typed, below, dict(inv),
                                        deadline=time.monotonic() + 10)
        self.assertIsNotNone(exact)
        covered = set()
        for pid, rot, x, z in exact:
            p = PART_MAP[pid]
            w, d = (p["d"], p["w"]) if rot else (p["w"], p["d"])
            for i in range(w):
                for j in range(d):
                    cell = (x + i, z + j)
                    self.assertNotIn(cell, covered, "格子重复覆盖")
                    covered.add(cell)
        self.assertEqual(covered, set(typed), "必须精确覆盖每个体素")

    def test_exact_cover_respects_inventory(self):
        typed = {(x, 0): "#" for x in range(4)}
        below = set(typed)
        empty = {pid: 0 for pid in PART_MAP}
        self.assertIsNone(tiler.solve_layer_exact(typed, below, empty,
                                                  deadline=time.monotonic() + 5))


if __name__ == "__main__":
    unittest.main()
