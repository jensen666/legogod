# -*- coding: utf-8 -*-
"""D.2 主链顺序开关（LEGOGOD_CHAIN_ORDER）回归：default / class1_front。

冻结语义：
1) 两种模式都不得提前冻结核心：视觉评审必须先于 _freeze_cores；
2) class1_front：draw 后先跑 class1 修订（不冻结核心）再进视觉；修订后仍失败时不得进入视觉，如实失败；
3) default 保持现有顺序（视觉 → 冻结 → 预检/求解循环），行为不回归；
4) chainOrder 写入 run 记录与 job result。
（原 `s0_readonly_front` 取值与 class1_front 走完全相同的分支，属惰性等价，已从合法值列表移除。）
不调用真实模型：chat_fn / review_fn / solve_fn / clock 全部注入。
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import Script, real_solve, resp  # noqa: E402
from legogod import part_binding as pb, workflow  # noqa: E402
from legogod.workflow import run_generation  # noqa: E402

DESC = "一座测试高塔，塔身完整不能拆，旁边有小旗杆不能删"

# 目标约 48 块、预估 60 体素/24 块：与 4×4×4 容量一致（plan_scale 一致性检查）
PLAN = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 4, "estimatedVoxels": 60, "targetBlocks": 48, "estimatedParts": 24,
    "parts": [
        {"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"},
        {"id": "flag", "name": "旗杆", "required": True, "source": "小旗杆"},
    ],
}}
PLAN_ONE = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 4, "estimatedVoxels": 60, "targetBlocks": 48, "estimatedParts": 24,
    "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
}}
SOLID_ROWS = ["####", "####", "####", "####"]
DISCONNECTED_ROWS = ["##.#", "##.#", "##.#", "##.#"]

SAVE_OK = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "order-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [{"module": "底", "color": "浅灰", "rows": list(SOLID_ROWS),
                "colorPatches": [{"color": "黑色", "cells": [[1, 1]]}]},
               {"module": "中一", "color": "浅灰", "rows": list(SOLID_ROWS)},
               {"module": "中二", "color": "白色", "rows": list(SOLID_ROWS)},
               {"module": "顶", "color": "白色", "rows": list(SOLID_ROWS)}],
}}
SAVE_DISCONNECTED = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "order-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower", "partPatches": [],
    "layers": [{"module": "底", "color": "浅灰", "rows": list(DISCONNECTED_ROWS),
                "colorPatches": [{"color": "黑色", "cells": [[0, 0]]}]},
               {"module": "中一", "color": "浅灰", "rows": list(DISCONNECTED_ROWS)},
               {"module": "中二", "color": "白色", "rows": list(DISCONNECTED_ROWS)},
               {"module": "顶", "color": "白色", "rows": list(DISCONNECTED_ROWS)}],
}}
BRIDGE_EDITS = [{"x": 2, "y": y, "z": z, "voxel": "#", "color": "浅灰"}
                for y in range(4) for z in range(4)]
BRIDGE_PATCH = {"thought": "", "action": "revise_design",
                "args": {"baseRevision": "r001", "edits": BRIDGE_EDITS}}


def color_patch(rev, color="白色"):
    return {"thought": "", "action": "revise_design", "args": {
        "baseRevision": rev,
        "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": color}]}}


class ReviewRecorder:
    """记录每次评审时的修订号与事件顺序（评审必须早于核心冻结）。"""

    def __init__(self, events, chain_ref, overall=8):
        self.events = events
        self.chain_ref = chain_ref
        self.overall = overall
        self.calls = 0

    def __call__(self, desc, model, solution=None, **kw):
        self.calls += 1
        chain = self.chain_ref.get("chain")
        self.events.append(("review", chain.revision if chain else None))
        return {"ok": True, "requests": 1, "sheet": "sheet.png",
                "parsed": {"scores": {"overall": self.overall}, "worst_parts": ["塔身"],
                           "suggestions": [], "missing_features": [], "keep": []}}


class OrderTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-order-")
        self.viz_tmp = tempfile.mkdtemp(prefix="legogod-order-viz-")
        patcher_a = mock.patch.object(workflow, "ARTIFACTS_DIR", self.tmp)
        patcher_v = mock.patch.object(workflow, "VIZ_DIR", self.viz_tmp)
        patcher_a.start()
        patcher_v.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_v.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.viz_tmp, ignore_errors=True))

    def _run(self, order, script, review_fn=None, solve_fn=None):
        """按指定顺序跑主链：捕获 chain 对象并记录「评审/冻结」的先后。"""
        events = []
        chain_ref = {}
        frozen_core_cells = pb.frozen_core_cells

        def freeze_spy(parts_norm):
            chain = chain_ref.get("chain")
            events.append(("freeze", chain.revision if chain else None))
            return frozen_core_cells(parts_norm)

        recorder = ReviewRecorder(events, chain_ref)
        if review_fn is None:
            review_fn = recorder
        orig_run = workflow._Chain.run

        def run_spy(chain_self):
            chain_ref["chain"] = chain_self
            return orig_run(chain_self)

        env = {"LEGOGOD_CHAIN_ORDER": order}
        with mock.patch.object(workflow._Chain, "run", run_spy), \
                mock.patch.object(pb, "frozen_core_cells", freeze_spy), \
                mock.patch.dict(os.environ, env):
            result = run_generation(DESC, mode="fidelity", chat_fn=script,
                                    review_fn=review_fn,
                                    solve_fn=solve_fn or real_solve)
        return result, chain_ref.get("chain"), events, recorder

    def _art(self, name):
        return os.path.join(self.tmp, name)


class DefaultOrderTest(OrderTestBase):
    def test_default_visual_before_freeze_and_no_front_gate(self):
        """default：现有顺序（视觉 → 冻结 → 预检/求解），不产生前置门禁事件。"""
        result, chain, events, recorder = self._run(
            "default", Script(resp(PLAN), resp(SAVE_OK)))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(chain.chain_order, "default")
        self.assertEqual(chain.order_events, [])
        self.assertEqual(result["chainOrder"], "default")
        self.assertEqual(result["run_record"]["chainOrder"], "default")
        self.assertEqual(events, [("review", 1), ("freeze", 1)],
                         "视觉评审必须先于核心冻结")
        self.assertEqual(recorder.calls, 1)

    def test_default_failed_structure_still_enters_visual_first(self):
        """default：预检修复用尽时，视觉已在冻结前发生过（与前置顺序形成对照）。"""
        script = Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED),
                        resp(color_patch("r001")), resp(color_patch("r002")))
        result, chain, events, recorder = self._run("default", script)
        self.assertFalse(result["ok"])
        self.assertEqual(recorder.calls, 1, "default 视觉在前，必须已评审")
        self.assertEqual(chain.order_events, [])
        self.assertEqual(events[0][0], "review")


class Class1FrontOrderTest(OrderTestBase):
    def test_class1_front_revises_before_visual_without_freezing(self):
        """class1_front：draw 后先跑 class1 修订，评审在修订后、冻结在评审后。"""
        result, chain, events, _recorder = self._run(
            "class1_front",
            Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED), resp(BRIDGE_PATCH)))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(chain.chain_order, "class1_front")
        self.assertEqual(result["counts"]["revise_class1"], 1)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(chain.order_events[0]["order"], "class1_front")
        self.assertEqual(events, [("review", 2), ("freeze", 2)])

    def test_class1_front_failed_revision_never_enters_visual(self):
        """class1_front：修订后仍失败 → 如实失败，不进入视觉、不冻结核心。"""
        script = Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED),
                        resp(color_patch("r001")), resp(color_patch("r002")))
        result, chain, events, recorder = self._run("class1_front", script)
        self.assertFalse(result["ok"])
        self.assertEqual(recorder.calls, 0)
        self.assertEqual(events, [])
        self.assertIn(result["failure"]["kind"], ("connectivity", "disconnected"))


class OrderEnvFallbackTest(unittest.TestCase):
    def test_unset_or_invalid_order_uses_adopted_default(self):
        """未设置/非法 LEGOGOD_CHAIN_ORDER → 采用 D.2 单变量实验后切换的默认 class1_front。

        D.2 结论（旧 20 例单变量真实 E2E）：交付 12→16、硬失败 8→4、耗时 -20.5%、
        视觉核心拒绝 0、必需外观损伤 0 → 默认切换为 class1_front；显式 "default" 仍保留旧顺序。
        """
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEGOGOD_CHAIN_ORDER", None)
            chain = workflow._Chain("一座塔", mode="fast")
        self.assertEqual(chain.chain_order, "class1_front")
        with mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "no_such_order"}):
            chain2 = workflow._Chain("一座塔", mode="fast")
        self.assertEqual(chain2.chain_order, "class1_front")

    def test_removed_s0_value_falls_back_to_class1_front(self):
        """已移除的惰性等价值 s0_readonly_front 按非法值回退 class1_front（旧脚本行为不漂移）。"""
        with mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "s0_readonly_front"}):
            chain = workflow._Chain("一座塔", mode="fast")
        self.assertEqual(chain.chain_order, "class1_front")

    def test_explicit_default_order_still_available(self):
        """显式 default 仍可回到旧顺序（对照组/回归用）。"""
        with mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"}):
            chain = workflow._Chain("一座塔", mode="fast")
        self.assertEqual(chain.chain_order, "default")


if __name__ == "__main__":
    unittest.main()
