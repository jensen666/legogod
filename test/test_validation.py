# -*- coding: utf-8 -*-
"""统一方案校验器的负向/正向回归测试。

覆盖审计中点名的错误类型：
- 普通砖叠在无顶凸点的斜坡砖上（凸点连接非法）
- 分离结构（零件级不连通）
- 悬挑（上层没有已就位的凸点支撑）
- 断库存
- 非法装配顺序
- 合法方案通过
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import validate_plan  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402


def _model(grid_w, grid_d, layer_cells, rows_by_y=None):
    """layer_cells: {y: [(x,z), ...]}；rows_by_y 可选（设计校验用）。"""
    layers = []
    for y in sorted(layer_cells):
        layers.append({
            "y": y,
            "cells": [list(c) for c in layer_cells[y]],
            "rows": (rows_by_y or {}).get(y) or [],
        })
    return {"grid": {"w": grid_w, "d": grid_d}, "totalVoxels": sum(len(v) for v in layer_cells.values()),
            "layers": layers}


def _step(layer, piece, x, z, w, d, rotate=False, step=1):
    return {"layer": layer, "piece": piece, "x": x, "z": z, "w": w, "d": d,
            "rotate": rotate, "step": step}


class ValidationNegativeTest(unittest.TestCase):
    def test_brick_on_slope_has_no_stud_connection(self):
        """斜坡砖顶面无凸点 → 上层砖不能靠它连接。"""
        model = _model(2, 1, {0: [(0, 0), (1, 0)], 1: [(0, 0)], 2: [(0, 0)]})
        solution = {"steps": [
            _step(0, "B1x2", 0, 0, 2, 1, rotate=True, step=1),
            _step(1, "SLOPE_ZP", 0, 0, 1, 1, step=2),
            _step(2, "B1x1", 0, 0, 1, 1, step=3),
        ]}
        report = validate_solution(model, solution)
        self.assertFalse(report["ok"])
        self.assertTrue(any("凸点" in e for e in report["errors"]), report["errors"])

    def test_separate_parts_are_rejected(self):
        """两块互不相接的零件：零件级连接图不连通。"""
        model = _model(4, 1, {0: [(0, 0), (3, 0)]})
        solution = {"steps": [_step(0, "B1x1", 0, 0, 1, 1, step=1),
                              _step(0, "B1x1", 3, 0, 1, 1, step=2)]}
        report = validate_solution(model, solution)
        self.assertFalse(report["ok"])
        self.assertTrue(any("分离组件" in e for e in report["errors"]), report["errors"])

    def test_separate_design_is_rejected_by_validate_design(self):
        """设计阶段就应拒绝分离模型（以前只记录 components 不拒绝）。"""
        plan = {
            "name": "分离测试", "slug": "separate", "features": ["测试"],
            "layers": [{"module": "层", "color": "白色", "rows": ["#..#"]}],
        }
        errs, model, _warns = validate_plan(plan)
        self.assertIsNone(model)
        self.assertTrue(any("互不相连" in e for e in errs), errs)

    def test_overhang_without_support_is_rejected(self):
        """上层零件下方没有已就位零件 → 悬空。"""
        model = _model(2, 1, {0: [(0, 0)], 1: [(1, 0)]})
        solution = {"steps": [_step(0, "B1x1", 0, 0, 1, 1, step=1),
                              _step(1, "B1x1", 1, 0, 1, 1, step=2)]}
        report = validate_solution(model, solution)
        self.assertFalse(report["ok"])
        self.assertTrue(any("连接" in e or "支撑" in e for e in report["errors"]), report["errors"])

    def test_stock_shortage_is_rejected(self):
        """用量超过库存。"""
        model = _model(2, 1, {0: [(0, 0), (1, 0)]})
        solution = {"steps": [_step(0, "B1x1", 0, 0, 1, 1, step=1),
                              _step(0, "B1x1", 1, 0, 1, 1, step=2)]}
        report = validate_solution(model, solution, inventory={"B1x1": 1})
        self.assertFalse(report["ok"])
        self.assertTrue(any("库存" in e for e in report["errors"]), report["errors"])

    def test_illegal_assembly_order_is_rejected(self):
        """结构合法但步骤顺序颠倒：上层先放、下层未就位 → 装配重放失败。"""
        model = _model(1, 1, {0: [(0, 0)], 1: [(0, 0)]})
        solution = {"steps": [
            _step(1, "B1x1", 0, 0, 1, 1, step=1),   # 上层先放
            _step(0, "B1x1", 0, 0, 1, 1, step=2),
        ]}
        report = validate_solution(model, solution)
        self.assertFalse(report["ok"])
        self.assertTrue(any("装配" in e or "顺序" in e for e in report["errors"]), report["errors"])


class ValidationPositiveTest(unittest.TestCase):
    def test_legal_two_layer_tower_passes(self):
        model = _model(1, 1, {0: [(0, 0)], 1: [(0, 0)]})
        solution = {"steps": [_step(0, "B1x1", 0, 0, 1, 1, step=1),
                              _step(1, "B1x1", 0, 0, 1, 1, step=2)]}
        report = validate_solution(model, solution)
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(report["checks"]["stud_connection"]["ok"])
        self.assertTrue(report["checks"]["part_graph"]["ok"])
        self.assertTrue(report["checks"]["assembly_order"]["ok"])
        # 稳定性只能标为简化检查，不能声称完整验证
        self.assertTrue(report["stability"]["checked"])
        self.assertEqual(report["stability"]["level"], "basic")

    def test_slope_under_slope_is_legal_when_supported(self):
        """斜坡砖本身可以放在普通砖上（底面有连接），只是不能作为上方支撑。"""
        model = _model(1, 1, {0: [(0, 0)], 1: [(0, 0)]})
        solution = {"steps": [_step(0, "B1x1", 0, 0, 1, 1, step=1),
                              _step(1, "SLOPE_XP", 0, 0, 1, 1, step=2)]}
        report = validate_solution(model, solution)
        self.assertTrue(report["ok"], report["errors"])


if __name__ == "__main__":
    unittest.main()
