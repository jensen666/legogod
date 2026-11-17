# -*- coding: utf-8 -*-
"""修订失败留稿、改动计数与视觉最高分回滚。

不调用真实模型：chat_fn / review_fn / solve_fn 全部注入。
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, PhaseChat, Script, real_solve, resp  # noqa: E402
from legogod import revision_policy as rp  # noqa: E402
from legogod import workflow_ops as wops  # noqa: E402
from legogod.fallback import (  # noqa: E402
    OUTCOME_FIDELITY_DEGRADED, run_with_fallback,
)
from legogod.workflow import run_generation  # noqa: E402

DESC = "一座测试高塔，塔身完整不能拆，旁边有小旗杆不能删"

PLAN = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
    "parts": [
        {"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"},
        {"id": "flag", "name": "旗杆", "required": True, "source": "小旗杆"},
    ],
}}

SAVE_FID = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "keep-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [
        {"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"],
         "colorPatches": [{"color": "黑色", "cells": [[1, 1]]}]},
        {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]},
    ],
}}

REVIEW_OK = {"ok": True, "requests": 1, "sheet": "sheet.png",
             "parsed": {"scores": {"overall": 8}, "worst_parts": ["塔身"],
                        "suggestions": [], "missing_features": [], "keep": ["旗杆"]}}

PLAN3 = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
    "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
}}


def bad_resp():
    return {"content": "不是json", "reasoning_content": "", "finish": "stop", "requests": 1}


def color_patch(rev, color):
    return {"thought": "", "action": "revise_design", "args": {
        "baseRevision": rev,
        "edits": [{"x": 3, "y": 1, "z": 3, "voxel": "#", "color": color}]}}


def no_op(rev):
    return {"thought": "", "action": "revise_design", "args": {
        "baseRevision": rev,
        "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "浅灰"}]}}


def disconnected_failure():
    return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                  "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": None}


class VisualKeepTest(IsolatedArtifactsTest):
    def test_lower_scores_roll_back_to_best_model(self):
        """6 分之后连续降到 3、2：最终稿是 6 分那一版，后两次换色不留在稿里。"""
        states = iter([6, 3, 2])

        def review_fn(desc, model, solution=None, **kw):
            return {"ok": True, "requests": 1, "sheet": "sheet.png",
                    "parsed": {"scores": {"overall": next(states)},
                               "worst_parts": ["塔身"], "suggestions": ["改顶色"]}}

        script = Script(resp(PLAN), resp(SAVE_FID),
                        resp(color_patch("r001", "米白")), resp(color_patch("r002", "红色")))
        result = run_generation(DESC, mode="fidelity", chat_fn=script, review_fn=review_fn,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["review_failed"])
        self.assertEqual(result["counts"]["revise_visual"], 2)
        # 2026-11-03 复核修正：回滚不得把 revision 拨回旧号；最佳稿(6 分, r001)以新单调版本落盘
        # → r004 为最终版（r002/r003 是被放弃的换色补丁，保留不覆盖）。
        self.assertEqual(result["revision"], 4, "回滚后最佳稿必须落新单调版本，不得倒退")
        self.assertEqual(result["revisionChain"][-1]["rolledBackTo"], 1)
        self.assertEqual(result["revisionChain"][-1]["parentRevision"], 3)
        self.assertEqual(result["revisionChain"][-1]["cause"], "visual_rollback")
        self.assertTrue(os.path.basename(result["model_path"]).endswith("_r004_%s.json" % result["run_id"]))
        self.assertTrue(result["revisionIncomplete"])
        self.assertIn("连续两次", result["revisionIncompleteReason"])
        self.assertIn("6", result["revisionIncompleteReason"])
        with open(os.path.join(self.tmp, result["model_path"]), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("米白", text)
        self.assertNotIn("红色", text)

    def test_visual_request_budget_keeps_best_and_solves(self):
        """视觉修订三次请求都无效：不整单失败，留当时最高分，也不跑极速保底。"""
        chat = PhaseChat(
            [resp(PLAN), resp(SAVE_FID), bad_resp(), bad_resp(), bad_resp()],
            [resp(PLAN), resp(SAVE_FID)],
        )

        def review_fn(desc, model, solution=None, **kw):
            return {"ok": True, "requests": 1, "sheet": "sheet.png",
                    "parsed": {"scores": {"overall": 4}, "worst_parts": ["塔身"],
                               "suggestions": ["改顶色"]}}

        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat, review_fn=review_fn,
                                   solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        self.assertTrue(result["review_failed"])
        self.assertEqual(result["counts"]["revise_visual"], 0)
        self.assertIn("视觉修订请求打满", result["revisionIncompleteReason"])
        self.assertEqual(len(chat.scripts[1].items), 2, "有可拼产物时不得重跑极速")

    def test_review_unavailable_after_revision_restores_best(self):
        """已有 6 分稿并换色后，下一次评审不可用：滚回 6 分稿，不标修订未完成。"""
        calls = {"n": 0}

        def review_fn(desc, model, solution=None, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": True, "requests": 1, "sheet": "sheet.png",
                        "parsed": {"scores": {"overall": 6},
                                   "worst_parts": ["塔身"], "suggestions": ["改顶色"]}}
            return {"ok": False, "requests": 1, "parsed": {}, "raw": ""}

        script = Script(resp(PLAN), resp(SAVE_FID), resp(color_patch("r001", "米白")))
        result = run_generation(DESC, mode="fidelity", chat_fn=script, review_fn=review_fn,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["review_unavailable"])
        self.assertFalse(result["review_failed"])
        self.assertFalse(result["revisionIncomplete"])
        self.assertEqual(result["revision"], 3, "回滚后最佳稿(r001)必须落新单调版本 r003")
        self.assertEqual(result["revisionChain"][-1]["rolledBackTo"], 1)
        self.assertEqual(result["revisionChain"][-1]["parentRevision"], 2)
        self.assertEqual((result.get("review") or {}).get("scores", {}).get("overall"), 6)
        with open(os.path.join(self.tmp, result["model_path"]), encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("米白", text)


class StructuralKeepTest(IsolatedArtifactsTest):
    @mock.patch.dict(os.environ, {"LEGOGOD_STRUCT_CANDIDATES": "off"})
    def test_class2_exhausted_then_solve_succeeds_degrades_without_fallback(self):
        """第 2 类两次用尽后，下一次求解成功：降级交付，不跑极速。

        确定性结构候选默认开启时会先尝试救回（属工作包 B 的新行为），本用例验证
        「模型类 2 修订耗尽后的降级语义」，因此显式关闭候选。
        """
        calls = []

        def solve_fn(model, layers, **kw):
            calls.append(1)
            if len(calls) == 4:
                return real_solve(model, layers, **kw)
            return disconnected_failure()

        chat = PhaseChat(
            [resp(PLAN), resp(SAVE_FID), resp(no_op("r001")), resp(no_op("r002"))],
            [resp(PLAN), resp(SAVE_FID)],
        )
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_OK),
                                   solve_fn=solve_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        self.assertTrue(result["revisionIncomplete"])
        self.assertIn("第 2 类修订次数已用尽", result["degraded_reason"])
        self.assertFalse(result["review_failed"])
        self.assertEqual(result["counts"]["revise_class2"], 2)
        self.assertEqual(len(calls), 4, "用尽后只再求解一次，成功就停")
        self.assertEqual(len(chat.scripts[1].items), 2, "求解成功不得触发极速保底")


def _box(x, part="tower", **extra):
    op = {"op": "box", "x": x, "y": 0, "z": 0, "w": 1, "d": 1, "h": 1, "part": part}
    op.update(extra)
    return op


class _Fake:
    """只满足 apply_ops_revision 在策略拒绝之前读到的字段。"""

    def __init__(self, kind="disconnected", cls="class2"):
        self.revision = 1
        self.track = "ops"
        self.default_part = "tower"
        self.model = {"grid": {"w": 16, "d": 4}, "layers": [{}, {}]}
        self.assignment = {}
        self.parts_norm = [
            {"id": "tower", "name": "塔身"},
            {"id": "arm", "name": "手臂"},
        ]
        self.pending_revision = {"cls": cls, "kind": kind, "failure": {
            "message": "塔身断了",
            "info": {"review": {"worst_parts": ["塔身"], "suggestions": [],
                                "missing_features": [], "keep": []}},
        }}
        self.ops = [_box(0)]
        self.revision_skip_geo_cap = False
        self.revision_entries = []
        self.notes = []

    def record_protocol_error(self, kind, summary):
        self.notes.append((kind, summary))

    def observe(self, text):
        self.notes.append(("observe", text))

    def emit(self, *args, **kwargs):
        pass


class OpsPolicyTest(unittest.TestCase):
    def test_structural_rejects_leave_ops_unchanged(self):
        chain = _Fake()
        original = list(chain.ops)
        too_many = original + [_box(i, color="浅灰") for i in range(1, 18)]
        self.assertFalse(wops.apply_ops_revision(chain, {
            "baseRevision": "r001", "ops": too_many}, 8, 16))
        self.assertEqual(chain.ops, original)
        self.assertTrue(any("17" in text or "超过" in text for _k, text in chain.notes))

        chain = _Fake()
        original = list(chain.ops)
        cylinder = {"op": "cylinder", "cx": 4, "cz": 1, "y": 0, "h": 1, "r": 1,
                    "part": "tower"}
        self.assertFalse(wops.apply_ops_revision(chain, {
            "baseRevision": "r001", "ops": original + [cylinder]}, 8, 16))
        self.assertEqual(chain.ops, original)
        self.assertTrue(any("倒置楔" in text for _k, text in chain.notes))

        chain = _Fake()
        chain.assignment = {(0, 0, 0): "tower"}
        original = list(chain.ops)
        cover = original + [_box(0, part="arm")]
        self.assertFalse(wops.apply_ops_revision(chain, {
            "baseRevision": "r001", "ops": cover}, 8, 16))
        self.assertEqual(chain.ops, original)
        self.assertTrue(any("盖住" in text for _k, text in chain.notes))

        chain = _Fake()
        original = [_box(i) for i in range(13)]
        chain.ops = list(original)
        rewritten = [_box(i, y=1) for i in range(13)]
        self.assertFalse(wops.apply_ops_revision(chain, {
            "baseRevision": "r001", "ops": rewritten}, 8, 16))
        self.assertEqual(chain.ops, original)
        self.assertTrue(any("12" in text for _k, text in chain.notes))

    def test_structural_append_of_box_and_inverted_wedge_is_counted(self):
        chain = _Fake()
        old = [_box(0)]
        new = old + [
            _box(2),
            {"op": "wedge", "dir": "+x", "x": 4, "y": 0, "z": 0, "w": 2, "d": 2, "h": 1,
             "kind": "inverted", "part": "tower"},
        ]
        err = rp.enforce_ops_policy(chain, old, new)
        self.assertIsNone(err, err)
        self.assertTrue(chain.revision_skip_geo_cap)
        rp.remember_revision(chain)
        accounted = rp.accounting(chain)
        self.assertEqual(accounted["append"], 2)
        self.assertEqual(accounted["rewrite"], 0)
        self.assertEqual(accounted["entries"][0]["scope"]["parts"], ["tower"])

    def test_visual_scope_uses_named_parts_and_paint_cells(self):
        chain = _Fake(kind="visual", cls="visual")
        tower, arm = _box(0, color="浅灰"), _box(2, part="arm", color="浅灰")
        old = [tower, arm]
        chain.assignment = {(2, 0, 0): "arm", (0, 0, 0): "tower"}

        foreign = [tower, {**arm, "color": "红色"}]
        err = rp.enforce_ops_policy(chain, old, foreign)
        self.assertIn("未点名", err)

        named = [{**tower, "color": "深灰"}, arm]
        self.assertIsNone(rp.enforce_ops_policy(chain, old, named))

        paint_arm = old + [{"op": "paint", "color": "黑色", "cells": [[2, 0, 0]]}]
        err = rp.enforce_ops_policy(chain, old, paint_arm)
        self.assertIn("未点名", err)

        paint_tower = old + [{"op": "paint", "color": "黑色", "cells": [[0, 0, 0]]}]
        self.assertIsNone(rp.enforce_ops_policy(chain, old, paint_tower))


class OpsAccountingChainTest(IsolatedArtifactsTest):
    def test_accepted_bridge_is_recorded_as_append(self):
        broken = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "keep-ops", "notes": "", "features": ["双柱"],
            "defaultPart": "tower",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 4, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 4, "h": 2, "part": "tower"},
            ],
        }}
        fixed = {"thought": "", "action": "revise_ops", "args": {
            "baseRevision": "r001",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 4, "h": 2, "part": "tower"},
                {"op": "box", "x": 1, "y": 0, "z": 0, "w": 2, "d": 4, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 4, "h": 2, "part": "tower"},
            ],
        }}
        script = Script(resp(PLAN3), resp(broken), resp(fixed))
        result = run_generation("一座测试高塔，塔身完整不能拆", chat_fn=script, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["revisionAccounting"]["append"], 1)
        self.assertEqual(result["revisionAccounting"]["rewrite"], 0)
        self.assertFalse(result["revisionIncomplete"])
        self.assertEqual(result["run_record"]["revisionAccounting"]["append"], 1)


class CountSplitTest(unittest.TestCase):
    """视觉几何变更数和结构 12/16 分开判。rewrite 大于 12 单独不能算视觉突破上限。"""

    def _visual(self, n=20):
        chain = _Fake(kind="visual", cls="visual")
        chain.cores_frozen = False
        chain.gate_errors = []
        chain._record_parts = lambda: None
        chain.model = {"name": "塔", "slug": "t", "notes": "", "features": [],
                       "grid": {"w": 24, "d": 4}, "layers": [{}, {}]}
        chain.ops = [_box(i) for i in range(n)]
        return chain

    def _accept(self, chain, new_ops, max_geo):
        layer = {"module": ["底"], "color": "浅灰", "rows": ["#"], "colorRows": None}
        bundle = {"model": {"layers": [layer], "name": "塔", "slug": "t",
                            "notes": "", "features": []},
                  "assign": {}, "bound": {"parts": chain.parts_norm}, "gate_errs": []}
        with mock.patch.object(wops, "validate_ops_candidate", return_value=([], "validated", bundle)):
            return wops.apply_ops_revision(chain, {"baseRevision": "r001", "ops": new_ops}, max_geo, 16)

    def test_visual_rewrite_over_12_stays_under_geo_cap(self):
        """顺序颠倒会把 rewrite 数大，几何变更数仍是 0，不超过 max(8, 算子个数)。"""
        chain = self._visual()
        old = list(chain.ops)
        new = list(reversed(old))
        diff = rp.classify_ops(old, new, chain.default_part)
        rewrite = len(diff["rewrites"]) + len(diff["deletes"])
        geo, _color = wops.count_ops_changes(old, new)
        self.assertGreater(rewrite, 12)
        self.assertGreater(rewrite, geo)
        self.assertLessEqual(geo, max(8, len(old)))
        self.assertTrue(self._accept(chain, new, max(8, len(old))), chain.notes)
        entry = chain.revision_entries[-1]
        self.assertEqual(entry["rewrite"], rewrite)
        self.assertEqual(entry["geoChanges"], geo)
        self.assertEqual(entry["opCount"], len(old))
        self.assertLessEqual(entry["geoChanges"], max(8, entry["opCount"]))

    def test_visual_geo_cap_follows_op_count_not_flat_8(self):
        """9 处几何变更：算子有 20 个时不超过上限；把上限收成 8 则必须拒绝，原稿不动。"""
        chain = self._visual()
        old = list(chain.ops)
        changed = [_box(i, y=(1 if i < 9 else 0)) for i in range(20)]
        geo, _color = wops.count_ops_changes(old, changed)
        self.assertEqual(geo, 9)
        self.assertFalse(wops.apply_ops_revision(
            chain, {"baseRevision": "r001", "ops": changed}, 8, 16))
        self.assertEqual(chain.ops, old)
        self.assertFalse(chain.revision_entries)
        chain = self._visual()
        self.assertTrue(self._accept(chain, changed, max(8, 20)), chain.notes)
        entry = chain.revision_entries[-1]
        self.assertEqual(entry["geoChanges"], 9)
        self.assertEqual(entry["opCount"], 20)
        self.assertLessEqual(entry["geoChanges"], max(8, entry["opCount"]))
        self.assertGreater(entry["rewrite"], entry["geoChanges"] - 1)

    def test_structural_17th_append_and_13th_rewrite_still_rejected(self):
        chain = _Fake()
        err = rp.enforce_ops_policy(chain, [_box(0)], [_box(0)] + [_box(i) for i in range(1, 18)])
        self.assertIsNotNone(err)
        self.assertIn("16", err)
        chain = _Fake()
        old = [_box(i) for i in range(13)]
        err = rp.enforce_ops_policy(chain, old, [_box(i, y=1) for i in range(13)])
        self.assertIsNotNone(err)
        self.assertIn("12", err)

    def test_old_visual_rewrite_33_is_not_rejudged(self):
        """没有几何变更数的旧记录保持原样。C11 的 rewrite 33 不按本方案判失败。"""
        chain = _Fake(kind="visual", cls="visual")
        chain.revision_entries = [{
            "cls": "visual", "kind": "visual", "append": 0, "rewrite": 33,
            "scope": {"rewritten": list(range(33))},
        }]
        accounted = rp.accounting(chain)
        entry = accounted["entries"][0]
        self.assertEqual(accounted["rewrite"], 33)
        self.assertEqual(entry["rewrite"], 33)
        self.assertNotIn("geoChanges", entry)
        self.assertNotIn("opCount", entry)
        self.assertNotIn("capBreached", entry)
        self.assertNotIn("capBreached", accounted)


if __name__ == "__main__":
    unittest.main()
