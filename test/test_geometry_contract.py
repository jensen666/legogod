# -*- coding: utf-8 -*-
"""几何契约测试。

不调用真实模型：chat_fn / solve_fn / clock 全部注入。覆盖：
  1. 三项检查单元语义：规模（数值反馈/缺目标跳过）、支撑与连通（生产 precheck_details
     同源判定）、桥接诊断（无垂直相邻 = 任何铺砖连不进）；
  2. 开关默认关：同一违规模型在默认环境下照常受理（零行为变化）；
  3. 画稿受理集成：契约违规 → 存草稿 r000 + 数值反馈 + revise_ops 局部修正后晋升；
     drawAttempts 记 contractErrorCount、run 记录落 contractChecks；
  4. 正式修订回归拦截：基线干净、修订引入支撑违规 → 打回不计修订次数；
     基线已违规（降级流）→ 放行，不产生死锁；
  5. 动态预算进展判定：contractErrorCount 下降构成实质进展（contract_violations_down）。
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, Script, real_solve, resp  # noqa: E402
from legogod import draw_budget, geometry_contract as gc  # noqa: E402
from legogod.workflow import run_generation  # noqa: E402
from legogod import workflow_ops as wops  # noqa: E402


PLAN_TOWER = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 4, "targetBlocks": 12, "estimatedVoxels": 50, "estimatedParts": 8,
    "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
}}
DESC_TOWER = "一座测试高塔，目标约 12 块积木，塔身完整不能拆"

# 连通测试用小目标：8 体素违规模、16 体素修正稿都落在目标 6 的合理带内，
# 保证连通测试只由连通契约拦截（不被规模契约干扰）。
PLAN_BRIDGE = {"thought": "", "action": "plan_design", "args": {
    "features": ["双塔"], "structure": "实心双塔", "grid": {"w": 4, "d": 4},
    "layers": 4, "targetBlocks": 6, "estimatedVoxels": 50, "estimatedParts": 6,
    "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
}}
DESC_BRIDGE = "一座测试双塔，目标约 6 块积木，塔身完整不能拆"


def _tower_ops(h=2, color="浅灰"):
    return [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": h, "part": "tower",
             "color": color}]


def _save3(ops, slug="gc-tower"):
    return {"thought": "", "action": "save_design3", "args": {
        "name": "测试塔", "slug": slug, "notes": "", "features": ["塔身方形"],
        "defaultPart": "tower", "ops": ops,
    }}


def _revise(ops):
    return {"thought": "", "action": "revise_ops", "args": {"baseRevision": "r000", "ops": ops}}


# 规模不足：4x4x1 = 16 体素 ≈ 4.3 块，4.3/12 = 36% < 50% → 违规。
SAVE_TOO_SMALL = _save3(_tower_ops(h=1))
SAVE_OK = _save3(_tower_ops(h=3))          # 48 体素 ≈ 13 块，108% ≥ 50%
REVISE_FIX_SCALE = _revise(_tower_ops(h=3))

# 连通违规：两块接地但互不接触的方盒（体素上互不相连，规模也低于目标 6）
SAVE_DISCONNECTED = _save3([
    {"op": "box", "x": 0, "y": 0, "z": 0, "w": 2, "d": 2, "h": 2, "part": "tower", "color": "浅灰"},
    {"op": "box", "x": 2, "y": 0, "z": 2, "w": 2, "d": 2, "h": 1, "part": "tower", "color": "浅灰"},
])
# 连通修正：第二块改为坐在第一块正上方（上下叠合，16 体素 ≥ 目标 6 的 50% 线）
REVISE_FIX_CONNECTED = _revise([
    {"op": "box", "x": 0, "y": 0, "z": 0, "w": 2, "d": 2, "h": 2, "part": "tower", "color": "浅灰"},
    {"op": "box", "x": 0, "y": 2, "z": 0, "w": 2, "d": 2, "h": 2, "part": "tower", "color": "浅灰"},
])

# 支撑违规：y=2 的孤立格（正下方 y=1 为空、正上方无实体）
SAVE_FLOATING = _save3([
    {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 1, "part": "tower", "color": "浅灰"},
    {"op": "box", "x": 1, "y": 3, "z": 1, "w": 2, "d": 2, "h": 1, "part": "tower", "color": "浅灰"},
])


class ContractEnabledTest(unittest.TestCase):
    def test_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(gc.ENV_CONTRACT, None)
            self.assertFalse(gc.contract_enabled())

    def test_enabled_by_env(self):
        with mock.patch.dict(os.environ, {gc.ENV_CONTRACT: "1"}):
            self.assertTrue(gc.contract_enabled())
        with mock.patch.dict(os.environ, {gc.ENV_CONTRACT: "0"}):
            self.assertFalse(gc.contract_enabled())


class CheckDesignUnitTest(unittest.TestCase):
    """三项检查的单元语义（模型为手工构造的最小 dict）。"""

    @staticmethod
    def _model(layers, total, parts=None):
        return {"grid": {"w": 4, "d": 4}, "totalVoxels": total,
                "parts": parts or [{"id": "tower", "name": "塔身", "role": "solid",
                                    "voxels": total, "boxes": []}],
                "layers": layers}

    def test_scale_violation_with_numbers(self):
        layers = [{"y": 0, "rows": ["####"] * 4}]
        m = self._model(layers, 16)
        vs = gc.check_design(m, target_blocks=12)
        scale = [v for v in vs if v["kind"] == "scale"]
        self.assertEqual(len(scale), 1)
        self.assertIn("16 体素", scale[0]["message"])
        self.assertIn("12 块", scale[0]["message"])
        self.assertEqual(scale[0]["detail"]["targetBlocks"], 12)

    def test_scale_passes_when_adequate(self):
        layers = [{"y": 0, "rows": ["####"] * 4}, {"y": 1, "rows": ["####"] * 4},
                  {"y": 2, "rows": ["####"] * 4}]
        m = self._model(layers, 48)
        self.assertFalse([v for v in gc.check_design(m, target_blocks=12)
                          if v["kind"] == "scale"], "48 体素 ≈ 13 块 / 12 = 108% 应通过")

    def test_scale_skipped_without_target(self):
        layers = [{"y": 0, "rows": ["####"] * 4}]
        m = self._model(layers, 16)
        self.assertFalse([v for v in gc.check_design(m, target_blocks=None)
                          if v["kind"] == "scale"], "缺目标块数时不得检查规模")

    def test_support_violation_from_production_semantics(self):
        layers = [
            {"y": 0, "rows": ["####"] * 4},
            {"y": 1, "rows": ["...."] * 4},
            {"y": 2, "rows": ["....", "..#.", "....", "...."]},  # 正下方 y=1 为空、上方无实体
        ]
        m = self._model(layers, 17)
        vs = gc.check_design(m, target_blocks=None)
        kinds = [v["kind"] for v in vs]
        self.assertIn("support", kinds)
        sup = next(v for v in vs if v["kind"] == "support")
        self.assertTrue(sup["cells"], "支撑违规必须带错误格")

    def test_connectivity_violation_with_bridge_diagnostics(self):
        layers = [
            {"y": 0, "rows": ["#...", "....", "....", "...#"]},
        ]
        m = self._model(layers, 2)
        vs = gc.check_design(m, target_blocks=None)
        kinds = [v["kind"] for v in vs]
        self.assertIn("connectivity", kinds)
        conn = next(v for v in vs if v["kind"] == "connectivity")
        detail = conn.get("detail") or {}
        self.assertIsNotNone(detail.get("bridgeable"))
        self.assertTrue(detail.get("unbridgeableParts"), "互不接触的分量必须判为不可桥接")
        self.assertIn("上下叠合", conn["message"], "不可桥接时反馈必须要求竖向重叠")

    def test_connected_components_pass(self):
        layers = [{"y": 0, "rows": ["####"] * 4}, {"y": 1, "rows": ["####"] * 4}]
        m = self._model(layers, 32)
        self.assertEqual([v for v in gc.check_design(m, target_blocks=None)], [])

    def test_never_raises_on_garbage(self):
        self.assertEqual(gc.check_design({"layers": None}), [])
        self.assertEqual(gc.check_design(None), [])


class TargetBlocksTest(unittest.TestCase):
    def test_plan_target_preferred(self):
        self.assertEqual(gc.target_blocks_for({"targetBlocks": 30}, "目标约 99 块"), 30)

    def test_desc_fallback(self):
        self.assertEqual(gc.target_blocks_for({}, "一座城堡，目标约 45 块积木"), 45)

    def test_missing_returns_none(self):
        self.assertIsNone(gc.target_blocks_for({}, "一座城堡"))


class DrawWiringTest(IsolatedArtifactsTest):
    """契约开启时的画稿受理集成。"""

    def _run(self, script, desc=DESC_TOWER, **kw):
        kw.setdefault("solve_fn", real_solve)
        return run_generation(desc, chat_fn=script, **kw)

    def setUp(self):
        super().setUp()
        pa = mock.patch.dict(os.environ, {gc.ENV_CONTRACT: "1"})
        pa.start()
        self.addCleanup(pa.stop)

    def test_scale_violation_blocks_then_revise_fixes(self):
        """规模违规 → 存草稿 + 数值反馈 → revise_ops 放大后晋升，正式版本仍为 r001。"""
        script = Script(resp(PLAN_TOWER), resp(SAVE_TOO_SMALL), resp(REVISE_FIX_SCALE))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["revision"], 1, "草稿修订不递增正式版本")
        record = result["run_record"]
        self.assertEqual(record["lastRejection"]["kind"], "contract")
        self.assertIn("规模契约", record["lastRejection"]["summary"])
        outcomes = [(a["outcome"], a.get("contractErrorCount")) for a in record["drawAttempts"]]
        self.assertEqual(outcomes, [("draft", 1), ("accepted", 0)])
        self.assertTrue(record["contractChecks"], "运行记录必须落 contractChecks")
        self.assertFalse(record["gateFailed"], "契约草稿门禁干净，不得标 gateFailed")
        self.assertTrue(record["gateRejectedDraft"] or record["contractChecks"],
                        "契约拒绝必须留痕（草稿已晋升时以 contractChecks 为准）")
        self.assertEqual([c["kinds"] for c in record["contractChecks"]], [["scale"], []])

    def test_connected_fix_after_connectivity_rejection(self):
        """连通违规 → 反馈含桥接诊断 → 修订为上下叠合后晋升。"""
        script = Script(resp(PLAN_BRIDGE), resp(SAVE_DISCONNECTED), resp(REVISE_FIX_CONNECTED))
        result = self._run(script, desc=DESC_BRIDGE)
        self.assertTrue(result["ok"], result.get("error"))
        record = result["run_record"]
        self.assertEqual(record["lastRejection"]["kind"], "contract")
        self.assertIn("互不相连", record["lastRejection"]["summary"])

    def test_contract_disabled_accepts_same_model(self):
        """默认关：同一规模违规模型照常受理（零行为变化）。"""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(gc.ENV_CONTRACT, None)
            script = Script(resp(PLAN_TOWER), resp(SAVE_TOO_SMALL))
            result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        record = result["run_record"]
        self.assertEqual([a["outcome"] for a in record["drawAttempts"]], ["accepted"])
        self.assertEqual(record["contractChecks"], [])

    def test_budget_exhaustion_with_contract_draft_degrades_without_gate_flag(self):
        """三次都是契约违规（revise_ops 原样重发）→ 预算耗尽按既有规则降级，门禁字段不被污染。"""
        script = Script(resp(PLAN_TOWER), resp(SAVE_TOO_SMALL),
                        resp(_revise(_tower_ops(h=1))), resp(_revise(_tower_ops(h=1))))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        record = result["run_record"]
        self.assertFalse(record["gateFailed"])
        self.assertEqual(record["lastRejection"]["kind"], "contract")
        self.assertTrue(record["contractChecks"], "三次契约拒绝必须全部落 contractChecks")
        self.assertEqual([c["violationCount"] for c in record["contractChecks"]], [1, 1, 1])
        self.assertTrue(all(a.get("contractErrorCount") == 1
                            for a in record["drawAttempts"] if a["outcome"] == "draft"))


class RevisionRegressionTest(unittest.TestCase):
    """正式修订的契约回归拦截（直接驱动 apply_ops_revision，模型经生产编译器构造）。"""

    HULL = {"op": "box", "x": 0, "y": 0, "z": 0, "w": 6, "d": 4, "h": 2,
            "part": "tower", "color": "浅灰"}

    @staticmethod
    def _ops(mast_x, mast_y):
        return [
            RevisionRegressionTest.HULL,
            {"op": "box", "x": mast_x, "y": mast_y, "z": 1, "w": 1, "d": 1, "h": 2,
             "part": "tower", "color": "浅灰"},
        ]

    @classmethod
    def _compiled_model(cls, ops):
        from legogod import voxel_ops as vo
        errs, result = vo.compile_ops(
            ops, 8, 4, 4, default_part="tower", part_ids=["tower"],
            required_ids=["tower"], name="测试塔", slug="gc-tower",
            features=["塔身方形"], notes="")
        assert not errs, errs
        return result["model"]

    def _chain(self, base_ops):
        chain = mock.Mock()
        chain.revision = 1
        chain.track = "ops"
        chain.default_part = "tower"
        chain.model = self._compiled_model(base_ops)
        chain.assignment = {}
        chain.parts_norm = [{"id": "tower", "name": "塔身", "required": True,
                             "source": "塔身", "role": "solid", "core_cells": []}]
        chain.ops = base_ops
        chain.frozen_cells = set()
        chain.cores_frozen = False
        chain.mode = "fast"
        chain.plan = {"grid": {"w": 8, "d": 4}, "layers": 4, "targetBlocks": 12}
        chain.desc = DESC_TOWER
        chain.gate_errors = []
        chain.gate_regressions = 0
        chain.contract_checks = []
        chain.revision_skip_geo_cap = False
        chain.revision_entries = []
        chain.notes = []
        chain.clock = lambda: 0.0
        chain.record_protocol_error.side_effect = \
            lambda kind, summary: chain.notes.append((kind, summary))
        chain.observe.side_effect = lambda text: chain.notes.append(("observe", text))
        return chain

    def test_clean_base_broken_revision_blocked(self):
        """基线干净、修订把桅杆挪到悬空位 → 契约打回，不计修订次数、ops 不变。

        挪出的桅杆自身有上方格（h=2），按生产预检语义是悬吊候选而非无支撑格，
        但与主体无任何上下叠合 → connectivity 违规（任何铺砖连不进去）。
        """
        base_ops = self._ops(1, 2)              # 桅杆坐在船体上（y=2，下方 y=1 有实体）
        broken_ops = self._ops(7, 2)            # 桅杆挪到船体之外：与主体无竖向重叠
        chain = self._chain(base_ops)
        saved_ops = list(chain.ops)
        with mock.patch.dict(os.environ, {gc.ENV_CONTRACT: "1"}):
            ok = wops.apply_ops_revision(chain, {
                "baseRevision": "r001", "ops": broken_ops}, 8, 16)
        self.assertFalse(ok, "基线干净、修订引入不可连接分量必须打回")
        self.assertEqual(chain.ops, saved_ops)
        self.assertTrue(any(k == "contract" for k, _t in chain.notes))
        kinds = [c["kinds"] for c in chain.contract_checks]
        self.assertIn(["connectivity"], kinds, "契约检查记录必须落 connectivity 违规")

    def test_violating_base_allows_degraded_flow(self):
        """基线已违规（降级流）：同几何修订放行，不因契约死锁。"""
        broken_ops = self._ops(7, 2)
        chain = self._chain(broken_ops)
        with mock.patch.dict(os.environ, {gc.ENV_CONTRACT: "1"}):
            ok = wops.apply_ops_revision(chain, {
                "baseRevision": "r001",
                "ops": self._ops(7, 2)[:-1] + [
                    {"op": "box", "x": 7, "y": 2, "z": 1, "w": 1, "d": 1, "h": 2,
                     "part": "tower", "color": "深灰"}]}, 8, 16)
        self.assertTrue(ok, "基线已违规时不得因契约死锁（纯换色修订应放行）")

    def test_disabled_env_no_block(self):
        """开关关：同样的破坏性修订不受契约拦截（回归保护）。"""
        base_ops = self._ops(1, 2)
        broken_ops = self._ops(7, 2)
        chain = self._chain(base_ops)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(gc.ENV_CONTRACT, None)
            ok = wops.apply_ops_revision(chain, {
                "baseRevision": "r001", "ops": broken_ops}, 8, 16)
        self.assertTrue(ok, "契约关闭时不得拦截")


class ProgressBetweenTest(unittest.TestCase):
    def test_contract_violations_down_is_progress(self):
        prev = {"compiled": True, "contractErrorCount": 3}
        cur = {"compiled": True, "contractErrorCount": 1}
        self.assertEqual(draw_budget.progress_between(prev, cur), "contract_violations_down")

    def test_missing_contract_keys_keep_old_behavior(self):
        prev = {"compiled": True, "gateErrorCount": 2}
        cur = {"compiled": True, "gateErrorCount": 2}
        self.assertIsNone(draw_budget.progress_between(prev, cur))


if __name__ == "__main__":
    unittest.main()
