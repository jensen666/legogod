# -*- coding: utf-8 -*-
"""真实斜坡几何与悬吊连接的求解/校验测试。

覆盖：多格正斜坡（底面全长可承托、坡尖出檐）、反斜坡（根部承托、尖端无干涉）、
吊挂连接（tiler 吊挂豁免 + validate 预拼子组件三项物理校核 + 质心凸包强制）、
颜色解耦（内部通配骨架 + 表面细节锚定）。
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler, suspension  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402
from legogod.parts_library import PART_MAP  # noqa: E402


def _model(w, d, layers_rows):
    layers = []
    for y, rows in enumerate(layers_rows):
        cells = [[x, z] for z, r in enumerate(rows) for x, c in enumerate(r) if c != "."]
        layers.append({"y": y, "rows": rows, "cells": cells, "module": ["层"],
                       "color": None, "colorRows": None, "count": len(cells)})
    return {"grid": {"w": w, "d": d}, "totalVoxels": sum(len(L["cells"]) for L in layers),
            "layers": layers}


def _quiet_solve(model, rounds=8):
    return tiler.solve_with_budget(model, model["layers"], rounds=rounds, log=lambda s: None)


class MultiSlopeTilingTest(unittest.TestCase):
    def test_two_cell_regular_slope_run_uses_3040_with_tip_overhang(self):
        """2 格 '\\' 段由 2x1 正斜坡覆盖：高端受托、坡尖出檐（下方悬空）。"""
        m = _model(4, 1, [
            ["#..."],
            ["\\\\.."],   # 两个 '\' 字符的段 x0..1：高端 x0 压在 (0,0) 上，坡尖 x1 下方悬空
        ])
        sol, fail = _quiet_solve(m)
        self.assertIsNotNone(sol, fail)
        pieces = {PART_MAP[s["piece"]]["shape"] for s in sol["steps"] if s["layer"] == 1}
        self.assertIn("SLOPE2_XL", pieces, "2 格 '\\' 段应由 3040 模具覆盖")

    def test_isolated_slope_without_support_is_rejected(self):
        """孤立的 1x1 斜坡、下方无支撑且无段可跨 → support 预检拒绝。"""
        m = _model(4, 1, [
            ["#..."],
            ["./.."],   # '/' 孤立段，下方 (1,0) 为空、上方无实体
        ])
        sol, fail = _quiet_solve(m, rounds=2)
        self.assertIsNone(sol)
        self.assertEqual(fail["kind"], "support")

    def test_inverted_slope_root_support_and_tip_clearance(self):
        """反斜坡：根（x1，'b' 段西端）压在墙顶凸点上，尖端 x2 外挑下方无凸点。"""
        m = _model(4, 1, [
            ["##.."],
            ["#bb."],   # 'b' 段 x1..x2：根在 x1（下方 '#'），尖端 x2（下方空）
        ])
        sol, fail = _quiet_solve(m)
        self.assertIsNotNone(sol, fail)
        pieces = {PART_MAP[s["piece"]]["shape"] for s in sol["steps"] if s["layer"] == 1}
        self.assertIn("ISLOPE_XL", pieces)

    def test_inverted_tip_over_stud_is_rejected(self):
        """反斜坡尖端压在 '#' 上方 = 凸点干涉 → 预检拒绝。"""
        m = _model(4, 1, [
            ["####"],
            ["#dd."],   # 'd' 段 x1..x2：根在东端 x2（下方 '#'），尖端 x1 下方也是 '#' → 干涉
        ])
        sol, fail = _quiet_solve(m, rounds=2)
        self.assertIsNone(sol)
        self.assertEqual(fail["kind"], "support")


class SuspensionValidationTest(unittest.TestCase):
    def _hanging_ear_model(self):
        """垂耳小狗拓扑：耳 x0..1 悬于 y1..2（下方悬空），柱 x3..4 落地，头层压住耳顶双凸点。"""
        def L(y, xs):
            rows = ["".join("#" if x in xs else "." for x in range(5)) for _ in range(2)]
            return {"y": y, "rows": rows, "cells": [[x, z] for x in xs for z in range(2)],
                    "module": ["层"], "color": None, "colorRows": None, "count": len(xs) * 2}
        return _model(5, 2, None) if False else {
            "grid": {"w": 5, "d": 2},
            "totalVoxels": 30,
            "layers": [L(0, [2, 3, 4]), L(1, [0, 1, 3, 4]), L(2, [0, 1, 3, 4]), L(3, [0, 1, 2, 3, 4])],
        }

    def test_hanging_cluster_solves_with_subassembly(self):
        m = self._hanging_ear_model()
        sol, fail = _quiet_solve(m)
        self.assertIsNotNone(sol, fail)
        self.assertTrue(sol.get("subassemblies"), "吊挂簇必须输出为预拼子组件")
        report = validate_solution(m, sol)
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(report["checks"]["suspension"]["ok"])

    def test_single_stud_engagement_rejected(self):
        """吊挂簇只有 1 个锁扣凸点 → 违反消旋下界，必须拒绝。"""
        parts = [
            {"layer": 0, "piece": "B2x4", "rot": False, "x": 0, "z": 0,
             "cells": [(0, 0), (1, 0), (0, 1), (1, 1)], "parents": set()},
            {"layer": 1, "piece": "B1x1", "rot": False, "x": 3, "z": 0,
             "cells": [(3, 0)], "parents": set()},          # 吊挂砖
            {"layer": 2, "piece": "B2x4", "rot": False, "x": 0, "z": 0,
             "cells": [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)],
             "parents": {0}},                                # 只压住吊挂砖 1 个凸点 (3,0)
        ]
        adj = {0: {2}, 1: {2}, 2: {0, 1}}
        clusters, errs = suspension.check_all(parts, adj)
        self.assertTrue(clusters)
        self.assertTrue(any("锁扣凸点" in e for e in errs), errs)
        cells = [tuple(c) for cluster in clusters for c in (cluster.get("failureCells") or [])]
        self.assertIn((3, 1, 0), cells)

    def test_com_enforcement_for_suspension_models(self):
        """启用悬吊的模型：质心超出底层支撑凸包 → 错误（不只是警告）。"""
        m = self._hanging_ear_model()
        sol, fail = _quiet_solve(m)
        self.assertIsNotNone(sol, fail)
        # 砍掉底层一半支撑：人为把 y0 的支撑格缩到 x=4 一列，制造质心出界
        m2 = {**m, "layers": [
            {**m["layers"][0], "cells": [[4, 0], [4, 1]],
             "rows": ["....#", "....#"], "count": 2},
            m["layers"][1], m["layers"][2], m["layers"][3],
        ], "totalVoxels": 26}
        sol2, fail2 = _quiet_solve(m2, rounds=2)
        if sol2 is not None:
            report = validate_solution(m2, sol2)
            self.assertFalse(report["ok"], "质心出界的悬吊模型不应通过")
            self.assertTrue(any("质心" in e for e in report["errors"]), report["errors"])


class InteriorWildcardColorTest(unittest.TestCase):
    def test_interior_wildcard_allows_cross_color_anchor(self):
        """表面单格异色细节可由长砖向内部通配区纵深锚定（砖可跨 内部+表面同色）。"""
        # 6x4x3 实心块，正面 z=0 的黑色单点 (2, y=1)，其余浅灰
        rows = ["######"] * 4
        m = _model(6, 4, [rows] * 3)
        for L in m["layers"]:
            cr = [["L"] * 6 for _ in range(4)]   # 4 行(z) × 6 列(x)
            if L["y"] == 1:
                cr[0][2] = "K"                    # (x=2, z=0) 黑
            L["colorRows"] = ["".join(r) for r in cr]
        sol, fail = _quiet_solve(m)
        self.assertIsNotNone(sol, fail)
        report = validate_solution(m, sol)
        self.assertTrue(report["ok"], report["errors"])
        # 覆盖 (2,1,0) 的砖必须同时覆盖内部格（锚定）——即不可能是孤立的 1x1
        y1_steps = [s for s in sol["steps"] if s["layer"] == 1]
        covered_by = None
        for s in y1_steps:
            from legogod.geometry import step_cells
            if (2, 0) in set(step_cells(s)):
                covered_by = s
        self.assertIsNotNone(covered_by)
        self.assertGreater(len(step_cells(covered_by)), 1, "黑色细节砖应向内部纵深锚定")


class SubassemblyAndRepairIntegrityTest(unittest.TestCase):
    def test_subassembly_includes_anchor_and_matches_validate_indices(self):
        """完整预拼子组件必须包含悬吊砖 + 上方跨接锁扣砖（≥2 块），且 tiler 与 validate 索引一致。"""
        m = SuspensionValidationTest()._hanging_ear_model()
        sol, fail = _quiet_solve(m)
        self.assertIsNotNone(sol, fail)
        report = validate_solution(m, sol)
        self.assertTrue(report["ok"], report["errors"])
        for t_sub, v_sub in zip(sol["subassemblies"], report["subassemblies"]):
            self.assertGreaterEqual(len(t_sub["bricks"]), 2, "预拼子组件不得只有孤立 1 块悬空砖")
            self.assertTrue(t_sub.get("anchorBricks"), "预拼子组件必须包含上方跨接锁扣砖")
            self.assertEqual(t_sub["bricks"], v_sub["bricks"])
            self.assertEqual(t_sub["steps"], v_sub["steps"])

    def test_multi_step_local_repair_preserves_voxel_colors(self):
        """多步单调局部图修复能连续合并多个顺缝分离岛，且严格保留 colorRows 外壳颜色。"""
        from legogod.tiler_repair import components_of, local_repair
        w, d = 6, 4
        rows = ["#" * w for _ in range(d)]
        # 左半红色 'R'，右半蓝色 'B'
        crows = ["RRRBBB" for _ in range(d)]
        model = {
            "grid": {"w": w, "d": d}, "totalVoxels": w * d * 2,
            "layers": [
                {"y": 0, "rows": list(rows), "cells": [[x, z] for z in range(d) for x in range(w)],
                 "module": ["底"], "color": None, "colorRows": list(crows), "count": w * d},
                {"y": 1, "rows": list(rows), "cells": [[x, z] for z in range(d) for x in range(w)],
                 "module": ["顶"], "color": None, "colorRows": list(crows), "count": w * d},
            ],
        }
        # 构造 3 个初始分离柱（x=0..1 红, x=2..3 跨色非法? 不：让左 4 列红分两柱，右 2 列红分一柱）
        crows_red = ["RRRRBB" for _ in range(d)]
        for L in model["layers"]:
            L["colorRows"] = list(crows_red)
        parts, adj = [], []
        inv = {pid: p["count"] for pid, p in PART_MAP.items()}
        for col, pid in ((0, "B2x4"), (2, "B2x4"), (4, "B2x4_BLUE")):
            cs = [(col + i, z) for i in range(2) for z in range(d)]
            i0 = len(parts)
            parts.append({"layer": 0, "piece": pid, "rot": False, "x": col, "z": 0, "cells": cs, "parents": set()})
            adj.append(set())
            inv[pid] -= 1
            i1 = len(parts)
            parts.append({"layer": 1, "piece": pid, "rot": False, "x": col, "z": 0, "cells": cs, "parents": {i0}})
            adj.append({i0})
            adj[i0].add(i1)
            inv[pid] -= 1
        # 左两柱同为红色，局部修复应合并它们（组件数从 3 严格下降到 2），且绝不破坏右两列蓝色！
        local_repair(parts, adj, model, model["layers"], inv, seed=0, max_steps=4)
        self.assertLess(len(set(components_of(parts, adj).values())), 3)
        for po in parts:
            for (cx, _cz) in po["cells"]:
                expected = "蓝色" if cx >= 4 else "红色"
                self.assertEqual(PART_MAP[po["piece"]]["colorName"], expected,
                                 "局部图修复不得抹掉或串改外壳逐体素颜色")


if __name__ == "__main__":
    unittest.main()
