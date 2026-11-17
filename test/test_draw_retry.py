# -*- coding: utf-8 -*-
"""画图重试预算、候选草稿局部纠错与失败归因测试。

不调用真实模型：chat_fn / review_fn / solve_fn / clock 全部注入。
覆盖十项必补测试与边界清单：
  1. 编译失败→门禁失败→第三次修正成功（发出第三次请求）；
  2. 第三次仍门禁失败：按规则降级且最新拒绝指向门禁（不回显旧编译错误）；
  3. 连续两次编译失败后第三次合法；
  5. 流式转普通计数不绕过画图请求上限；
  6. 截止/取消不触发额外请求；
  7. 无草稿 revise_ops(r000) 被拒、有草稿只能基于当前草稿修订；
  8. 纯涂装局部修订不动无关算子、正式 revision 不提前增长；
  9. 动态第 4 次请求：无进展不放行、有实质进展按策略放行；
  10. 最终错误/运行记录/日志一致指向最新拒绝原因。

另覆盖结构化选稿排序（draft_ranking）、降级门禁基线冻结与
已降级候选的回归拒绝（gate_regression）。
"""
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, Script, real_solve, resp  # noqa: E402
from legogod import draw_budget, gate_replay, tiler, workflow, workflow_ops as wops  # noqa: E402
from legogod.workflow import MAX_DRAW_REQUESTS, run_generation  # noqa: E402

DESC_SHIP = "一艘测试大船，带桅杆、船帆、旗杆、船尾舵，船舷有灯、舷窗和水线涂装"

PLAN_SHIP = {"thought": "", "action": "plan_design", "args": {
    "features": ["船体", "桅杆", "船帆", "旗杆", "船尾舵", "灯", "舷窗", "水线"],
    "structure": "测试船", "grid": {"w": 8, "d": 4}, "layers": 4,
    "targetBlocks": 20, "estimatedVoxels": 61, "estimatedParts": 12,
    "parts": [
        {"id": "hull", "name": "船体", "required": True, "source": "测试大船"},
        {"id": "mast", "name": "桅杆", "required": True, "source": "桅杆"},
        {"id": "sail", "name": "船帆", "required": True, "source": "船帆"},
        {"id": "flag_pole", "name": "旗杆", "required": True, "source": "旗杆"},
        {"id": "rudder", "name": "船尾舵", "required": True, "source": "船尾舵"},
        {"id": "lantern", "name": "灯", "required": True, "source": "灯", "role": "surface"},
        {"id": "porthole", "name": "舷窗", "required": True, "source": "舷窗", "role": "surface"},
        {"id": "stripe", "name": "水线", "required": True, "source": "水线", "role": "surface"},
    ],
}}


def _ops(lantern="黄色", porthole="黑色", stripe="红色"):
    """8 部位测试船：5 个立体部位自甲板真实凸出 + 3 个表面涂装部位外露异色。

    结构部位与船体同色、表面细节都落在甲板层，保证铺砖求解器的零件级连通
    （本文件只测画图阶段机制，不让求解成为干扰变量）。
    """
    return [
        {"op": "box", "x": 0, "y": 0, "z": 0, "w": 6, "d": 4, "h": 2, "part": "hull", "color": "浅灰"},
        {"op": "box", "x": 1, "y": 2, "z": 1, "w": 1, "d": 1, "h": 2, "part": "mast", "color": "浅灰"},
        {"op": "box", "x": 3, "y": 2, "z": 1, "w": 1, "d": 1, "h": 2, "part": "sail", "color": "浅灰"},
        {"op": "box", "x": 5, "y": 2, "z": 1, "w": 1, "d": 1, "h": 2, "part": "rudder", "color": "浅灰"},
        {"op": "box", "x": 5, "y": 2, "z": 3, "w": 1, "d": 1, "h": 2, "part": "flag_pole", "color": "浅灰"},
        {"op": "box", "x": 0, "y": 2, "z": 0, "w": 2, "d": 1, "h": 1, "part": "stripe", "color": stripe},
        {"op": "box", "x": 3, "y": 2, "z": 0, "w": 1, "d": 1, "h": 1, "part": "lantern", "color": lantern},
        {"op": "box", "x": 5, "y": 2, "z": 2, "w": 1, "d": 1, "h": 1, "part": "porthole", "color": porthole},
    ]


def _save3(ops, slug="draw-retry-ship"):
    return {"thought": "", "action": "save_design3", "args": {
        "name": "测试船", "slug": slug, "notes": "", "features": PLAN_SHIP["args"]["features"],
        "defaultPart": "hull", "ops": ops,
    }}


def _revise(ops):
    return {"thought": "", "action": "revise_ops", "args": {
        "baseRevision": "r000", "ops": ops,
    }}


# 编译失败：paint 涂到非实体格（复现 25e7265d 第一次失败）
BAD_PAINT = {"thought": "", "action": "save_design3", "args": {
    "name": "测试船", "slug": "draw-retry-ship", "notes": "",
    "features": PLAN_SHIP["args"]["features"], "defaultPart": "hull",
    "ops": _ops() + [{"op": "paint", "color": "黑色", "cells": [[7, 2, 2]]}],
}}

SAVE_GOOD = _save3(_ops())
# 门禁失败 1 项：灯与船体同色
SAVE_GATE1 = _save3(_ops(lantern="浅灰"))
# 门禁失败 3 项：灯/舷窗/水线全部与船体同色
SAVE_GATE3 = _save3(_ops(lantern="浅灰", porthole="浅灰", stripe="浅灰"))
# 部分修正：修好舷窗与水线，灯仍同色（门禁错误数 3→1，构成实质进展）
REVISE_PARTIAL = _revise(_ops(lantern="浅灰", porthole="黑色", stripe="红色"))
REVISE_FIX_LANTERN = _revise(_ops())

PLAN_TOWER = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 4, "targetBlocks": 12, "estimatedVoxels": 50, "estimatedParts": 8,
    "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
}}
DESC_TOWER = "一座测试高塔，塔身完整不能拆"
# 三种互不相同的编译失败（验证最终错误指向最新一次）
BAD_PAINT_TOWER = {"thought": "", "action": "save_design3", "args": {
    "name": "测试塔", "slug": "draw-retry-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "ops": [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "tower"},
            {"op": "paint", "color": "黑色", "cells": [[7, 2, 2]]}],
}}
BAD_OOB = {"thought": "", "action": "save_design3", "args": {
    "name": "测试塔", "slug": "draw-retry-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "ops": [{"op": "box", "x": 9, "y": 0, "z": 0, "w": 2, "d": 2, "h": 1, "part": "tower"}],
}}
BAD_ZERO = {"thought": "", "action": "save_design3", "args": {
    "name": "测试塔", "slug": "draw-retry-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "ops": [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 0, "d": 4, "h": 2, "part": "tower"}],
}}


def passing_review(desc, model, solution=None, **kw):
    return {"ok": True, "requests": 1, "sheet": "sheet.png",
            "parsed": {"scores": {"overall": 8}, "worst_parts": [], "suggestions": []}}


class DrawRetryTestBase(IsolatedArtifactsTest):
    """本文件公共入口：默认注入真实求解器与「测试大船」需求。"""

    def _run(self, script, desc=DESC_SHIP, **kw):
        kw.setdefault("solve_fn", real_solve)
        return run_generation(desc, chat_fn=script, **kw)


class DrawBudgetBasicsTest(DrawRetryTestBase):
    """拆分预算与测试 1/3/5。"""

    def test_draw_budget_constant(self):
        self.assertEqual(MAX_DRAW_REQUESTS, 3)
        self.assertEqual(workflow.MAX_REDRAWS, 1)

    def test_compile_fail_gate_fail_third_request_fixes(self):
        """测试 1：编译失败→门禁失败→第三次局部修正成功（发出第三次请求）。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE1), resp(REVISE_FIX_LANTERN))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 4, "PLAN + 3 次 draw 请求")
        self.assertEqual(result["track"], "ops")
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["counts"], {"revise_class1": 0, "revise_class2": 0, "revise_visual": 0})
        outcomes = [a["outcome"] for a in result["run_record"]["drawAttempts"]]
        self.assertEqual(outcomes, ["compile_retry", "draft", "accepted"])

    def test_two_compile_fails_then_third_valid(self):
        """测试 3：连续两次编译失败后第三次合法，可进入后续主链。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(BAD_PAINT), resp(SAVE_GOOD))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 4)
        self.assertEqual(result["run_record"]["drawAttempts"][-1]["outcome"], "accepted")

    def test_draw_exhaustion_reports_budget_and_latest_rejection(self):
        """测试 10：三次全编译失败 → 协议失败，reason=request_budget、lastRejection 指向最新错误。"""
        script = Script(resp(PLAN_TOWER), resp(BAD_PAINT_TOWER), resp(BAD_OOB), resp(BAD_ZERO))
        result = self._run(script, desc=DESC_TOWER)
        self.assertFalse(result["ok"])
        failure = result["failure"]
        self.assertEqual(failure["kind"], "protocol")
        self.assertEqual(failure["stage"], "draw")
        self.assertEqual(failure["reason"], "request_budget")
        self.assertEqual(failure["lastRejection"]["kind"], "compile_ops")
        self.assertIn("w/d/h 必须 ≥1", failure["lastRejection"]["summary"])
        self.assertIn("3 次上限", result["error"])
        self.assertIn("w/d/h 必须 ≥1", result["error"], "最终错误必须是最新一次打回原因")
        self.assertNotIn("不是实体格", result["error"], "不得回显第一次的旧编译错误")
        self.assertFalse(result["run_record"]["gateFailed"])


class DraftCorrectionTest(DrawRetryTestBase):
    """候选草稿与测试 2/4/7/8。"""

    def test_third_gate_fail_degrades_with_latest_reason(self):
        """测试 2：第三次仍门禁失败 → 带记录降级，最新拒绝指向门禁而非旧编译错误。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE1),
                        resp(_revise(_ops(lantern="浅灰"))))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"])
        self.assertTrue(result["gate_errors"])
        record = result["run_record"]
        self.assertEqual(record["lastRejection"]["kind"], "gate")
        self.assertIn("同层相邻主体同色", record["lastRejection"]["summary"])
        self.assertEqual([a["outcome"] for a in record["drawAttempts"]],
                         ["compile_retry", "draft", "draft"])
        self.assertTrue(record["gateFailed"])

    def test_gate_fail_then_paint_only_revision_keeps_unrelated_ops(self):
        """测试 8：纯涂装局部修订只动目标算子；正式 revision 不因草稿修订提前增长。"""
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(REVISE_FIX_LANTERN))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["revision"], 1, "草稿修订不递增正式版本")
        self.assertNotIn("model_r000", result["artifacts"], "草稿不落盘正式产物")
        with open(self._art(result["model_path"]), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["ops"], _ops(), "无关算子必须与通过门禁的候选逐字节一致")
        self.assertEqual(result["counts"]["revise_class1"], 0)

    def test_no_draft_rejects_revise_ops(self):
        """测试 7a：无候选草稿时 revise_ops(r000) 被拒（wrong_action），任务继续。"""
        script = Script(resp(PLAN_SHIP), resp(_revise(_ops())), resp(SAVE_GOOD))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["run_record"]["protocolErrors"][0]["kind"], "wrong_action")

    def test_draft_revision_requires_r000_base(self):
        """测试 7b：有草稿时只能基于当前草稿（r000）修订，r001 被拒后可纠正。"""
        stale = {"thought": "", "action": "revise_ops", "args": {
            "baseRevision": "r001", "ops": _ops()}}
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(stale), resp(REVISE_FIX_LANTERN))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        kinds = [e["kind"] for e in result["run_record"]["protocolErrors"]]
        self.assertIn("schema_error", kinds)

    def test_draft_revision_cannot_swallow_required_part(self):
        """草稿修订吞没必需部位 → 重编译拒绝（草稿不变），随后正常修正通过。"""
        swallow = _revise([op for op in _ops(lantern="浅灰") if op.get("part") != "mast"])
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(swallow), resp(REVISE_FIX_LANTERN))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        summaries = [e["summary"] for e in result["run_record"]["protocolErrors"]]
        self.assertTrue(any("必需部位" in s and "mast" in s for s in summaries),
                        f"必须记录必需部位被吞没的拒绝：{summaries}")

    def test_draw_fallback_rejected_while_draft_exists(self):
        """有草稿时不接受降级二维画稿（allowed 收窄为 save_design3/revise_ops）。"""
        save_2d = {"thought": "", "action": "save_design", "args": {"layers": []}}
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(save_2d), resp(REVISE_FIX_LANTERN))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["track"], "ops", "不得借草稿降级二维画稿")
        kinds = [e["kind"] for e in result["run_record"]["protocolErrors"]]
        self.assertIn("wrong_action", kinds)


class StopConditionTest(DrawRetryTestBase):
    """测试 6：截止与取消不得触发额外请求。"""

    def test_deadline_stops_extra_draw_requests(self):
        t0 = time.monotonic()
        base = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE1))

        def clock():
            return t0 + (10 ** 9 if len(base.calls) >= 3 else 0.0)

        result = self._run(base, clock=clock)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "deadline")
        self.assertEqual(len(base.calls), 3, "截止后不得发出第三次 draw 请求")

    def test_cancel_stops_extra_draw_requests(self):
        cancel = threading.Event()
        base = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE1))

        def chat(messages, **kw):
            out = base(messages, **kw)
            if len(base.calls) >= 3:
                cancel.set()
            return out

        result = self._run(chat, cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(len(base.calls), 3)


class DynamicFourthRequestTest(DrawRetryTestBase):
    """动态第 4 次请求与测试 9。"""

    def test_no_progress_repeats_denied_fourth_request(self):
        """测试 9a：相同失败签名无进展 → 不放行第 4 次，预算耗尽按规则降级。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE3),
                        resp(_revise(_ops(lantern="浅灰", porthole="浅灰", stripe="浅灰"))))
        result = self._run(script, mode="fidelity", review_fn=passing_review)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"], "无进展不放行第 4 次：草稿带门禁记录降级")
        self.assertEqual(len(script.calls), 4, "PLAN + 3 次 draw，没有第 4 次")
        self.assertEqual(len(result["run_record"]["drawAttempts"]), 3)

    def test_progress_earns_fourth_request(self):
        """测试 9b：编译转成功 + 门禁错误数下降 → 复杂任务放行第 4 次并修正成功。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE3), resp(REVISE_PARTIAL),
                        resp(REVISE_FIX_LANTERN))
        result = self._run(script, mode="fidelity", review_fn=passing_review)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(result["gate_failed"])
        self.assertEqual(len(script.calls), 5, "PLAN + 4 次 draw（动态第 4 次被放行）")
        outcomes = [a["outcome"] for a in result["run_record"]["drawAttempts"]]
        self.assertEqual(outcomes, ["compile_retry", "draft", "draft", "accepted"])
        self.assertEqual(result["counts"]["revise_visual"], 0)

    def test_env_switch_disables_dynamic_request(self):
        """LEGOGOD_DYNAMIC_DRAW_BUDGET=0：固定 3 次策略（同输入对照验收用）。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE3), resp(REVISE_PARTIAL))
        with mock.patch.dict(os.environ, {draw_budget.ENV_DYNAMIC_DRAW: "0"}):
            result = self._run(script, mode="fidelity", review_fn=passing_review)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"], "固定 3 次策略下部分修正后耗尽 → 降级")
        self.assertEqual(len(script.calls), 4)

    def test_regression_compiled_to_failed_is_not_progress(self):
        """评审 P1-1 回归：从编译成功退回编译失败不是实质进展，复杂任务也不放行第 4 次。"""
        bad_revise = _revise(_ops() + [{"op": "paint", "color": "黑色", "cells": [[7, 2, 2]]}])
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(bad_revise), resp(bad_revise))
        result = self._run(script, mode="fidelity", review_fn=passing_review)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"], "无实质进展不放行第 4 次：按规则降级")
        self.assertEqual(len(script.calls), 4, "PLAN + 3 次 draw，第 4 次未放行")
        outcomes = [a["outcome"] for a in result["run_record"]["drawAttempts"]]
        self.assertEqual(outcomes, ["draft", "compile_retry", "compile_retry"])

    def test_degrade_uses_best_not_latest_draft(self):
        """评审 P2：候选稿退化后预算耗尽，降级使用历史最佳草稿而非最新（可能更差的）。"""
        worse = _revise(_ops(lantern="浅灰", porthole="浅灰", stripe="浅灰"))  # 门禁 3 项（比 R1 的 1 项更差）
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(worse), resp(BAD_PAINT))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"])
        # R1 草稿 1 项门禁错误；R2 退化到 3 项；R3 编译失败 → 降级必须用 R1 的最佳草稿
        self.assertEqual(len(result["gate_errors"]), 1,
                         f"降级应使用最佳草稿（1 项门禁错误），实际：{result['gate_errors']}")
        outcomes = [a["outcome"] for a in result["run_record"]["drawAttempts"]]
        self.assertEqual(outcomes, ["draft", "draft", "compile_retry"])

    def test_simple_task_never_gets_fourth_request(self):
        """非复杂任务（1 部位 fast）第 4 次不放行：三次编译失败即协议失败。"""
        script = Script(resp(PLAN_TOWER), resp(BAD_PAINT_TOWER), resp(BAD_OOB), resp(BAD_ZERO))
        result = self._run(script, desc=DESC_TOWER)
        self.assertFalse(result["ok"])
        self.assertEqual(len(script.calls), 4)


class FailureAttributionTest(DrawRetryTestBase):
    """失败归因与可观测性（测试 10 + 边界）。"""

    def test_deadline_with_draft_marks_gate_failed_and_saves_diagnostic(self):
        """门禁拒绝后截止失败：gateFailed 如实为 true，草稿诊断哈希落盘。"""
        t0 = time.monotonic()
        base = Script(resp(PLAN_SHIP), resp(SAVE_GATE1))

        def clock():
            return t0 + (10 ** 9 if len(base.calls) >= 2 else 0.0)

        result = self._run(base, clock=clock)
        self.assertFalse(result["ok"])
        record = result["run_record"]
        self.assertTrue(record["gateFailed"], "最后候选稿确实因门禁被拒")
        self.assertEqual(record["lastRejection"]["kind"], "gate")
        diag = record.get("draftDiagnostic") or {}
        self.assertEqual(diag.get("opCount"), len(_ops(lantern="浅灰")))
        self.assertTrue(diag.get("opsHash"))
        self.assertTrue(diag.get("gateErrors"))

    def test_run_record_draw_attempts_metrics(self):
        """运行记录保存每次 draw 的算子数/编译结果/门禁错误数/耗时。"""
        script = Script(resp(PLAN_SHIP), resp(BAD_PAINT), resp(SAVE_GATE1), resp(REVISE_FIX_LANTERN))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        attempts = result["run_record"]["drawAttempts"]
        self.assertEqual(len(attempts), 3)
        for a in attempts:
            for key in ("attempt", "request", "elapsedS", "outcome", "compiled", "opCount",
                        "voxels", "gateErrorCount", "failedPartCount", "invalidOpCount", "signature"):
                self.assertIn(key, a)
        self.assertEqual(attempts[0]["invalidOpCount"], 1)
        self.assertEqual(attempts[1]["gateErrorCount"], 1)
        self.assertEqual(attempts[2]["outcome"], "accepted")
        self.assertTrue(all(a["attempt"] == i + 1 for i, a in enumerate(attempts)))
        self.assertTrue(all(a["request"] == i + 1 for i, a in enumerate(attempts)))


class DrawSchemaDispatchTest(unittest.TestCase):
    """评审 P2：check_draw_schema 必须按 action 分派，不被 args 杂散键误导。"""

    class _Chain:
        draft = None
        plan = {"grid": {"w": 8, "d": 4}, "layers": 4}
        mode = "fast"
        parts_norm = [{"id": "hull", "required": True}]

    def test_save3_with_stray_base_revision_uses_save_schema(self):
        chain = self._Chain()
        args = {"baseRevision": "r000", "slug": "s", "features": ["f"],
                "ops": [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 1, "h": 1, "part": "hull"}]}
        errs = wops.check_draw_schema(chain, args, "save_design3")
        self.assertFalse(any("revise_ops" in e or "草稿" in e for e in errs),
                        f"save_design3 不得被路由进草稿 Schema：{errs}")

    def test_revise_ops_without_base_revision_hits_draft_schema(self):
        chain = self._Chain()
        chain.draft = {"ops": [], "model": {"totalVoxels": 1}, "default_part": "hull",
                       "gate_errors": [], "gate_cells": [], "bad_part_ids": [],
                       "args": {}, "parts_norm": [], "assign": {}, "signature": "x"}
        errs = wops.check_draw_schema(chain, {"ops": [{"op": "box", "x": 0, "y": 0, "z": 0,
                                                       "w": 1, "d": 1, "h": 1, "part": "hull"}]},
                                      "revise_ops")
        self.assertTrue(any("baseRevision" in e for e in errs), f"缺 baseRevision 应按草稿 Schema 报错：{errs}")

    def test_revise_ops_without_draft_rejected(self):
        errs = wops.check_draw_schema(self._Chain(), {"baseRevision": "r000", "ops": []}, "revise_ops")
        self.assertTrue(any("没有已编译的候选草稿" in e for e in errs))


class GBKConsoleLogTest(unittest.TestCase):
    """评审 P2：默认日志在 GBK 控制台打印 ⚠ 不得抛 UnicodeEncodeError。"""

    def test_default_log_survives_restricted_encoding(self):
        import io
        buf = io.BytesIO()
        fake = io.TextIOWrapper(buf, encoding="gbk", errors="strict")
        with mock.patch.object(sys, "stdout", fake):
            workflow._console_log("error", "⚠ 门禁重绘次数用尽仍不达标，带门禁记录继续")
            workflow._console_log("info", "普通中文与 ASCII 123")
        fake.flush()
        text = buf.getvalue().decode("gbk")
        self.assertIn("门禁重绘次数用尽", text)
        self.assertIn("普通中文", text)
        self.assertNotIn("⚠", text, "GBK 无法编码的字符应被替换，不得抛异常")


class DrawBudgetUnitTest(unittest.TestCase):
    """失败签名、进展判定与动态四条件（纯单元，不跑主链）。"""

    @staticmethod
    def _attempt(sig=None, *, compiled=False, gate=0, failed=0, invalid=0):
        return {"signature": sig, "compiled": compiled, "gateErrorCount": gate,
                "failedPartCount": failed, "invalidOpCount": invalid}

    class _FakeChain:
        def __init__(self, attempts, draft=None, mode="fast", parts=(),
                     remaining_model=100.0, remaining_hard=1000.0):
            self.draw_attempts = attempts
            self.draft = draft
            self.mode = mode
            self.parts_norm = list(parts)
            self._rm = remaining_model
            self._rh = remaining_hard

        def remaining_model(self):
            return self._rm

        def remaining_hard(self):
            return self._rh

    def test_fingerprint_normalizes_coordinates_but_keeps_error_sets(self):
        a = draw_budget.fingerprint("compile", ["算子#27（paint）坐标 (x=7,y=2,z=1) 不是实体格"])
        b = draw_budget.fingerprint("compile", ["算子#27（paint）坐标 (x=9,y=1,z=0) 不是实体格"])
        c = draw_budget.fingerprint("compile", ["算子#27（paint）坐标 (x=7,y=2,z=1) 不是实体格",
                                                "算子#28（paint）坐标 (x=1,y=1,z=1) 不是实体格"])
        self.assertEqual(a["digest"], b["digest"], "坐标不同、错误类型相同 → 同一签名")
        self.assertNotEqual(a["digest"], c["digest"], "完整错误集合不同 → 不同签名")
        self.assertEqual(a["ops"], ["27"])

    def test_progress_between_matrix(self):
        prev = self._attempt("x", compiled=False, invalid=3)
        self.assertEqual(draw_budget.progress_between(prev, self._attempt("y", compiled=True)),
                         "compile_fixed")
        prev = self._attempt("x", compiled=True, gate=3, failed=2, invalid=2)
        self.assertEqual(draw_budget.progress_between(prev, self._attempt("y", compiled=True, gate=1)),
                         "gate_errors_down")
        self.assertEqual(draw_budget.progress_between(
            prev, self._attempt("y", compiled=True, gate=3, failed=1)), "failed_parts_down")
        self.assertEqual(draw_budget.progress_between(
            prev, self._attempt("y", compiled=True, gate=3, failed=2, invalid=1)), "invalid_ops_down")
        self.assertIsNone(draw_budget.progress_between(
            prev, self._attempt("y", compiled=True, gate=4, failed=3, invalid=3)))
        # 评审 P1-1 回归：编译成功退回编译失败（门禁指标清零）不是进展
        self.assertIsNone(draw_budget.progress_between(
            self._attempt("x", compiled=True, gate=3, failed=2), self._attempt("y", compiled=False)))
        self.assertIsNone(draw_budget.progress_between(
            self._attempt("x", compiled=False, invalid=2), self._attempt("y", compiled=False, invalid=2)))

    def test_complexity_votes(self):
        votes = draw_budget.complexity_votes(13, 3, 40, 2400, True)
        self.assertEqual(votes, ["required_parts", "surface_parts", "ops", "voxels", "fidelity"])
        self.assertEqual(draw_budget.complexity_votes(4, 0, 8, 700, False), [])
        self.assertEqual(draw_budget.complexity_votes(0, 0, 0, 0, True), ["fidelity"])

    def _dynamic(self, attempts, parts=(), mode="fast", draft=None):
        return draw_budget.dynamic_request_state(self._FakeChain(attempts, draft=draft, mode=mode,
                                                                 parts=parts))

    def test_dynamic_state_conditions(self):
        surface_part = {"id": "eye", "required": True, "role": "surface"}
        complex_parts = [surface_part] * 3
        draft = {"ops": [{}] * 2, "model": {"totalVoxels": 100}}
        allowed, detail = self._dynamic(
            [self._attempt("c1", invalid=2), self._attempt("g1", compiled=True, gate=3, failed=2)],
            parts=complex_parts, mode="fidelity", draft=draft)
        self.assertTrue(allowed, "编译转成功是实质进展 → 放行")
        self.assertEqual(detail["reason"], "allowed")

        cases = [
            ("not_complex", [self._attempt("c1"), self._attempt("c2")], [], "fast", None),
            ("no_candidate", [], complex_parts, "fidelity", draft),
            ("repeat_of_previous",
             [self._attempt("c1"), self._attempt("g1", compiled=True, gate=2),
              self._attempt("g1", compiled=True, gate=2)],
             complex_parts, "fidelity", draft),
            ("resend_of_earlier",
             [self._attempt("c1"), self._attempt("g1", compiled=True, gate=2),
              self._attempt("c1", invalid=2)],
             complex_parts, "fidelity", draft),
        ]
        for want_reason, attempts, parts, mode, d in cases:
            allowed, detail = self._dynamic(attempts, parts=parts, mode=mode, draft=d)
            self.assertFalse(allowed, want_reason)
            self.assertEqual(detail["reason"], want_reason)

        no_progress = [self._attempt("c1", invalid=4), self._attempt("c2", invalid=4)]
        allowed, detail = self._dynamic(no_progress, parts=complex_parts, mode="fidelity", draft=draft)
        self.assertFalse(allowed)
        self.assertEqual(detail["reason"], "no_progress")

    def test_dynamic_blocked_when_no_time_budget(self):
        """条件 1：剩余模型时间或硬墙钟余量不足时，复杂任务也不放行第 4 次。"""
        parts = [{"id": "eye", "required": True, "role": "surface"}] * 3
        draft = {"ops": [{}] * 2, "model": {"totalVoxels": 100}}
        attempts = [self._attempt("c1", invalid=2), self._attempt("g1", compiled=True, gate=2)]
        for label, kw in (("model_deadline", dict(remaining_model=0.0)),
                          ("hard_reserve", dict(remaining_hard=30.0))):
            chain = self._FakeChain(attempts, parts=parts, mode="fidelity", draft=draft, **kw)
            allowed, detail = draw_budget.dynamic_request_state(chain)
            self.assertFalse(allowed, label)
            self.assertEqual(detail["reason"], "no_time_budget", label)

    def test_dynamic_disabled_by_env(self):
        chain = self._FakeChain([self._attempt("c1"), self._attempt("g1", compiled=True, gate=2)],
                                parts=[{"id": "eye", "required": True, "role": "surface"}] * 3,
                                mode="fidelity",
                                draft={"ops": [{}] * 2, "model": {"totalVoxels": 100}})
        with mock.patch.dict(os.environ, {draw_budget.ENV_DYNAMIC_DRAW: "0"}):
            allowed, detail = draw_budget.dynamic_request_state(chain)
        self.assertFalse(allowed)
        self.assertEqual(detail["reason"], "dynamic_disabled")


def _revise_at(rev, ops):
    """指定正式版本的 revise_ops 补丁（降级后 class1/class2 修订用）。"""
    return {"thought": "", "action": "revise_ops", "args": {"baseRevision": rev, "ops": ops}}


class DraftRankingAndDegradedBaselineTest(unittest.TestCase):
    """结构化选稿排序与降级门禁基线冻结（纯单元，不跑主链）。"""

    class _Chain:
        """只提供 save_draw_draft / promote_candidate 需要的最小状态桩。"""

        def __init__(self):
            self.parts_norm = [{"id": "p1", "required": True, "cells": {(0, 0, 0)}},
                               {"id": "p2", "required": True, "cells": {(1, 0, 0)}}]
            self.draft = None
            self.best_draft = None
            self.draft_ranking = None
            self.gate_errors = None
            self.gate_degraded_baseline = None
            self.gate_regressions = 0
            self.failures = []
            self.protocol_errors = []
            self.track = None
            self.ops = None
            self.default_part = None
            self.assignment = None
            self.design_meta = None
            self.layers = None
            self.model = None

        def emit(self, kind, text, meta=None):
            pass

        def observe(self, text):
            pass

        def record_protocol_error(self, kind, summary):
            self.protocol_errors.append({"kind": kind, "summary": str(summary)})

    @staticmethod
    def _bundle(errors, cells, bad_ids, part_cells=None):
        """构造 save_draw_draft 需要的最小候选 bundle（part_cells 缺省把错误格归首个失败部位）。"""
        cells_by_part = part_cells or ({bad_ids[0]: set(cells)} if bad_ids else {})
        parts = [{"id": pid, "required": True,
                  "cells": set(cells_by_part.get(pid) or ())} for pid in bad_ids]
        return {
            "ops": [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 1, "h": 1}],
            "model": {"name": "测试", "slug": "rank-test", "notes": "", "features": [],
                      "grid": {"w": 4, "d": 4},
                      "layers": [{"y": 0, "rows": ["####"], "module": ["层"], "color": "浅灰"}],
                      "totalVoxels": 4, "slopeVoxels": 0},
            "assign": {}, "bound": {"parts": parts},
            "gate_errs": list(errors), "gate_cells": list(cells), "bad_part_ids": list(bad_ids),
        }

    def test_best_draft_selected_by_structured_rank_not_error_count(self):
        """结构化排序优先受影响部位数与错误格数，而不是错误字符串条数。"""
        chain = self._Chain()
        err_type_a = "立体部位「p1」不满足任何几何独立判据（空气面 1 vs 贴合面 5）"
        err_type_b = "立体部位「p1」有 2 格完全内埋（(x=1,y=0,z=0)）"
        err_type_c = "表面涂装部位「p2」有 1 格与同层相邻主体同色（(x=0,y=0,z=1)）"
        # 候选 A：1 个部位、1 个错误格、2 条错误；候选 B：1 个部位、2 个错误格、1 条错误
        bundle_a = self._bundle([err_type_a, err_type_b], [(0, 0, 0)], ["p1"])
        bundle_b = self._bundle([err_type_c], [(1, 0, 0), (1, 0, 1)], ["p2"])
        draft_a = wops.save_draw_draft(chain, {"defaultPart": "p1"}, bundle_a)
        self.assertIs(chain.best_draft, draft_a)
        self.assertEqual(chain.draft_ranking["selected"], "latest")
        draft_b = wops.save_draw_draft(chain, {"defaultPart": "p2"}, bundle_b)
        # B 的错误条数更少（1 < 2），但错误格更多（2 > 1）→ 结构化排序仍保留 A 为最佳
        self.assertIs(chain.draft, draft_b)
        self.assertIs(chain.best_draft, draft_a, "最佳草稿必须按结构化排序，而不是错误条数")
        self.assertEqual(chain.draft_ranking["selected"], "best")
        self.assertEqual(chain.draft_ranking["rule"], "parts>cells>types")
        candidates = chain.draft_ranking["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(set(candidates[0]),
                         {"signature", "gateErrorCount", "affectedPartCount",
                          "errorCellCount", "errorTypes"})
        self.assertEqual(candidates[0]["gateErrorCount"], 2)
        self.assertEqual(candidates[0]["affectedPartCount"], 1)
        self.assertEqual(candidates[0]["errorCellCount"], 1)
        self.assertEqual(candidates[1]["gateErrorCount"], 1)
        self.assertEqual(candidates[1]["errorCellCount"], 2)

    def test_draft_ranking_caps_candidates(self):
        """draft_ranking 只保留最近 8 个候选，仍记录 rule/selected。"""
        chain = self._Chain()
        err = "立体部位「p1」只有 1 格（最小体量 2）"
        for idx in range(10):
            wops.save_draw_draft(chain, {"defaultPart": "p1"},
                                 self._bundle([err], [(0, 0, 0), (idx + 2, 0, 0)], ["p1"]))
        self.assertEqual(len(chain.draft_ranking["candidates"]), gate_replay.MAX_RANKED_DRAFTS)
        self.assertEqual(chain.draft_ranking["rule"], "parts>cells>types")

    def test_promote_candidate_freezes_degraded_baseline_from_best_draft(self):
        """降级时冻结门禁基线：取最佳草稿的真实错误格/失败部位/完整错误。"""
        chain = self._Chain()
        best_errors = ["立体部位「p1」只有 1 格（最小体量 2）"]
        best_bundle = self._bundle(best_errors, [(0, 0, 0)], ["p1"])
        wops.save_draw_draft(chain, {"defaultPart": "p1"}, best_bundle)
        # 再来一个更差的候选，确认降级仍取最佳草稿的错误作为基线
        wops.save_draw_draft(chain, {"defaultPart": "p2"},
                             self._bundle(["表面涂装部位「p2」有 1 格完全内埋（(x=1,y=0,z=0)）"],
                                          [(1, 0, 0), (1, 0, 1)], ["p2"]))
        best = chain.best_draft
        wops.promote_candidate(chain, best["model"],
                               {"assign": best["assign"], "parts": best["parts_norm"]},
                               best["ops"], best["default_part"],
                               degraded_gate_errs=best["gate_errors"])
        self.assertIsNone(chain.draft)
        self.assertIsNone(chain.best_draft)
        self.assertTrue(chain.gate_errors)
        baseline = chain.gate_degraded_baseline
        self.assertEqual(set(baseline), {"affectedPartCount", "errorCellCount", "errorTypes"})
        self.assertEqual(baseline["affectedPartCount"], 1)
        self.assertEqual(baseline["errorCellCount"], 1)
        self.assertEqual(len(baseline["errorTypes"]), 1)


class DegradedRegressionIntegrationTest(DrawRetryTestBase):
    """集成：已降级候选的修订若恶化门禁必须被拒绝，不恶化候选可继续。"""

    def test_regressed_ops_revision_rejected_then_fixed_accepted(self):
        worse = _ops(lantern="浅灰", porthole="浅灰", stripe="浅灰")  # 门禁 3 项（基线只有 1 项）
        script = Script(resp(PLAN_SHIP), resp(SAVE_GATE1), resp(_revise(worse)), resp(BAD_PAINT),
                        resp(_revise_at("r001", worse)), resp(_revise_at("r001", _ops())))
        solve_calls = []

        def solve_fn(model, layers, **kw):
            solve_calls.append(1)
            if len(solve_calls) == 1:
                return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                              "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": None}
            return tiler.solve_with_budget(model, layers, **kw)

        # 本用例只验证 gate_regression 拒绝：关闭结构候选救稿，保证失败后进入 class2 模型修订
        with mock.patch.dict(os.environ, {"LEGOGOD_STRUCT_CANDIDATES": "off"}):
            result = self._run(script, solve_fn=solve_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"], "本次运行确实是带门禁记录降级")
        self.assertEqual(len(script.calls), 6, "PLAN + 3 次 draw + 2 次 class2 修订")
        self.assertEqual(result["counts"]["revise_class2"], 1, "被拒的回归候选不消耗修订次数")
        self.assertEqual(len(result["gate_errors"]), 1, "降级稿门禁错误保持 1 项（未被更差候选污染）")
        kinds = [e["kind"] for e in result["run_record"]["protocolErrors"]]
        self.assertIn("gate_regression", kinds)
        regression = [e for e in result["run_record"]["protocolErrors"]
                      if e["kind"] == "gate_regression"][0]
        self.assertIn("受影响部位数 3 > 降级基线 1", regression["summary"])
        self.assertEqual([a["outcome"] for a in result["run_record"]["drawAttempts"]],
                         ["draft", "draft", "compile_retry"])
        self.assertEqual(result["revision"], 2)


if __name__ == "__main__":
    unittest.main()
