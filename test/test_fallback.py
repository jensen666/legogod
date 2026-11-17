# -*- coding: utf-8 -*-
"""高保真优先 + 快速保底编排 与 评审意见继承回归测试。

覆盖验收口径：
1) 高保真一次成功 → 不发生极速重试，结果标记 fidelity_success；
2) 高保真有可拼产物但视觉不达标 / 评审不可用 → 降级交付并标注，不重跑极速；
3) 高保真无有效产物 → 自动极速恰好一次，成功后标记 fast_fallback；
4) 手动重试继承的评审意见注入本次高保真尝试输入，原始需求不变；自动快速保底是全新轻量
   运行，不注入任何历史评审意见与失败原因；合并结果仍带 review_context 供
   后续手动重试继承；
5) 评审不可用时如实记录真实失败原因，不编造评审反馈；注入的失败原因必须清洗：
   剥离面向模型的几何改法指令，门禁类失败补充可行替代路径；
6) 两种尝试都失败 → 如实失败，两类失败原因分别保留；
7) 取消 / 总时限耗尽 / 剩余时间不足 → 不再启动保底尝试。

不调用真实模型：chat_fn / review_fn / solve_fn / clock 全部注入。
"""
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, PhaseChat, Script, real_solve, resp  # noqa: E402
from legogod.fallback import (  # noqa: E402
    MIN_FALLBACK_S, OUTCOME_CANCELLED, OUTCOME_FAILED, OUTCOME_FAST_FALLBACK,
    OUTCOME_FAST_SUCCESS, OUTCOME_FIDELITY_DEGRADED, OUTCOME_FIDELITY_SUCCESS,
    format_review_message, review_context_from_result, run_with_fallback,
)
from legogod.workflow import run_generation  # noqa: E402  （保持与主链测试同一入口）

DESC = "一座测试高塔，塔身完整不能拆，旁边有小旗杆不能删"

PLAN = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
    "parts": [
        {"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"},
        {"id": "flag", "name": "旗杆", "required": True, "source": "小旗杆"},
    ],
}}

# 极速（基础）模式画稿：无需逐体素配色
SAVE_FAST = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "fallback-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [{"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"]},
               {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]}],
}}

# 高保真画稿：必须带逐体素配色（colorPatches），否则被打回
SAVE_FID = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "fallback-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [
        {"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"],
         "colorPatches": [{"color": "黑色", "cells": [[1, 1]]}]},
        {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]},
    ],
}}

REVIEW_OK = {"ok": True, "requests": 1, "sheet": "sheet.png",
             "parsed": {"scores": {"overall": 8, "features": 8},
                        "missing_features": [], "worst_parts": ["顶面配色"],
                        "suggestions": ["把 (1,1) 改色"], "keep": ["旗杆"]}}

REVIEW_BAD = {"ok": True, "requests": 1, "sheet": "sheet.png",
              "parsed": {"scores": {"overall": 4, "features": 3},
                         "missing_features": ["小旗杆缺失"], "worst_parts": ["顶面配色"],
                         "suggestions": ["把 (3,3) 改色"], "keep": ["塔身"]}}

REVIEW_UNAVAILABLE = {"ok": False, "requests": 1, "raw": "", "finish": None,
                      "parsed": {}, "views": {}, "sheet": None,
                      "stopped_by_deadline": False, "stopped_by_cancel": False}

# 手动重试继承的结构化评审意见（server 层 review_context_from_result 的产物）
INHERITED_CTX = {
    "reviewAvailable": True,
    "scores": {"overall": 6, "features": 5},
    "missingFeatures": ["小旗杆缺失"],
    "worstParts": ["塔顶"],
    "suggestions": ["补上旗杆"],
    "keepParts": ["塔身"],
    "flag": "review_failed",
    "failureSummary": "失败类别 protocol（阶段 draw）：上次任务画稿阶段失败",
}


def empty_resp():
    return {"content": "", "reasoning_content": "", "finish": "stop", "requests": 1}


def no_op(rev):
    return {"thought": "", "action": "revise_design", "args": {
        "baseRevision": rev,
        "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "浅灰"}]}}


def always_fail_solve(model, layers, **kw):
    return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                  "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": None}


class FidelityFirstTest(IsolatedArtifactsTest):
    """高保真成功或降级交付时绝不触发快速保底。"""

    def test_fidelity_success_no_fallback(self):
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID)], [resp(PLAN), resp(SAVE_FAST)])
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_OK),
                                   solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_SUCCESS)
        self.assertEqual(len(chat.scripts[1].items), 2, "高保真成功不得触发快速保底")
        self.assertEqual(chat.i, 0, "只消耗了高保真尝试的脚本")
        self.assertNotIn("attempts_detail", result)

    def test_review_failed_degraded_delivery_without_fallback(self):
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID), resp(no_op("r001")), resp(no_op("r002"))],
                         [resp(PLAN), resp(SAVE_FAST)])
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_BAD),
                                   solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        self.assertEqual(result["degraded_reason"], "视觉评审修订后仍未达标（整体分低于验收线）")
        self.assertTrue(result["review_failed"])
        self.assertEqual(len(chat.scripts[1].items), 2, "有可拼产物时不得重跑极速")

    def test_review_unavailable_degraded_delivery_without_fallback(self):
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID)], [resp(PLAN), resp(SAVE_FAST)])
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_UNAVAILABLE),
                                   solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        self.assertTrue(result["review_unavailable"])
        self.assertEqual(len(chat.scripts[1].items), 2)


class FastFallbackTest(IsolatedArtifactsTest):
    """硬失败时自动极速恰好一次；保底全新轻量运行不注入历史意见。"""

    def test_hard_failure_triggers_fast_fallback_exactly_once(self):
        chat = PhaseChat([empty_resp(), empty_resp()], [resp(PLAN), resp(SAVE_FAST)])
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FAST_FALLBACK)
        self.assertEqual(result["fallback_note"], "高保真生成失败，已提供快速保底方案")
        self.assertEqual(len(result["attempts_detail"]), 2)
        self.assertFalse(result["attempts_detail"][0]["ok"])
        self.assertEqual(result["attempts_detail"][0]["failure"]["kind"], "protocol")
        self.assertTrue(result["attempts_detail"][1]["ok"])
        self.assertTrue(result["fidelity_attempt_error"], "保底成功时必须保留高保真失败原因")
        # 交付产物来自极速尝试
        self.assertEqual(result["run_id"], result["attempts_detail"][1]["run_id"])
        self.assertEqual(result["status"], "done")

    def assert_not_injected(self, chat, fast_start, msg="快速保底为全新运行：不得注入评审意见消息"):
        """极速尝试的首个 plan 调用消息必须是 [system, 原始需求, 阶段指令]，无注入消息。"""
        first_fast = chat.all_messages[fast_start]
        self.assertEqual(len(first_fast), 3, msg)
        self.assertEqual(first_fast[1]["content"], DESC, "原始需求消息必须原样保留")
        self.assertTrue(all("评审反馈" not in m["content"] for m in first_fast), msg)

    def test_fallback_runs_clean_without_injection(self):
        """自动快速保底不注入历史评审意见与失败原因；合并结果仍带 review_context。"""
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID), resp(no_op("r001")), resp(no_op("r002"))],
                         [resp(PLAN), resp(SAVE_FAST)])
        # 高保真尝试注入的求解器必然失败（触发 class2 耗尽）；极速尝试用真实求解器
        solve_fn = lambda model, layers, **kw: (always_fail_solve(model, layers, **kw)
                                                if chat.i == 0 else real_solve(model, layers, **kw))
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_OK),
                                   solve_fn=solve_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FAST_FALLBACK)
        self.assert_not_injected(chat, 4)  # 第 5 次调用起为极速尝试
        ctx = result["review_context"]     # 意见只沉淀，供用户后续手动重试继承
        self.assertTrue(ctx["reviewAvailable"])
        self.assertEqual(ctx["scores"]["overall"], 8)
        self.assertEqual(ctx["keepParts"], ["旗杆"])

    def test_review_unavailable_records_failure_honestly(self):
        """评审不可用时合并结果不得编造反馈，只沉淀真实失败原因；保底不注入。"""
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID), resp(no_op("r001")), resp(no_op("r002"))],
                         [resp(PLAN), resp(SAVE_FAST)])
        solve_fn = lambda model, layers, **kw: (always_fail_solve(model, layers, **kw)
                                                if chat.i == 0 else real_solve(model, layers, **kw))
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_UNAVAILABLE),
                                   solve_fn=solve_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assert_not_injected(chat, 4)
        ctx = result["review_context"]
        self.assertFalse(ctx["reviewAvailable"])
        self.assertIn("disconnected", ctx["failureSummary"])
        self.assertNotIn("class2", ctx["failureSummary"])

    def test_manual_retry_context_injected_into_fidelity_attempt(self):
        """手动重试继承的评审意见必须注入本次高保真尝试，原始需求不变。"""
        chat = PhaseChat([empty_resp(), empty_resp()], [resp(PLAN), resp(SAVE_FAST)])
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat, solve_fn=real_solve,
                                   review_context=dict(INHERITED_CTX))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FAST_FALLBACK)
        fid_messages = chat.all_messages[0]
        self.assertEqual(fid_messages[1]["content"], DESC, "原始需求消息必须原样保留")
        injected = fid_messages[2]["content"]
        self.assertIn("上一次尝试的真实评审反馈", injected)
        self.assertIn("小旗杆缺失", injected)
        self.assertIn("塔身", injected)
        self.assertIn("不是新需求", injected)

    def test_inherited_context_falls_back_when_fidelity_review_unavailable(self):
        """本次尝试评审不可用时，合并结果的意见回退到继承的有效意见，
        失败原因保留本次真实原因；保底本身仍不注入。"""
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID), resp(no_op("r001")), resp(no_op("r002"))],
                         [resp(PLAN), resp(SAVE_FAST)])
        solve_fn = lambda model, layers, **kw: (always_fail_solve(model, layers, **kw)
                                                if chat.i == 0 else real_solve(model, layers, **kw))
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_UNAVAILABLE),
                                   solve_fn=solve_fn, review_context=dict(INHERITED_CTX))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FAST_FALLBACK)
        self.assert_not_injected(chat, 4)
        ctx = result["review_context"]
        self.assertTrue(ctx["reviewAvailable"], "回退后的有效意见应留给下一次重试")
        self.assertEqual(ctx["keepParts"], ["塔身"])
        self.assertIn("disconnected", ctx["failureSummary"])
        self.assertNotIn("class2", ctx["failureSummary"])

    def test_fidelity_own_valid_review_wins_over_inherited(self):
        """本次尝试有自己的有效评审时合并结果携带最新意见，历史问题不再回传。"""
        chat = PhaseChat([resp(PLAN), resp(SAVE_FID), resp(no_op("r001")), resp(no_op("r002"))],
                         [resp(PLAN), resp(SAVE_FAST)])
        solve_fn = lambda model, layers, **kw: (always_fail_solve(model, layers, **kw)
                                                if chat.i == 0 else real_solve(model, layers, **kw))
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat,
                                   review_fn=lambda *a, **k: dict(REVIEW_OK),
                                   solve_fn=solve_fn,
                                   review_context=dict(INHERITED_CTX, missingFeatures=["历史缺失问题"]))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FAST_FALLBACK)
        self.assert_not_injected(chat, 4)
        ctx = result["review_context"]
        self.assertEqual(ctx["scores"]["overall"], 8)
        self.assertEqual(ctx["keepParts"], ["旗杆"])
        self.assertNotIn("历史缺失问题", ctx["missingFeatures"])

    def test_both_attempts_fail_keeps_both_reasons(self):
        """双失败如实失败，两类失败原因分别保留。"""
        chat = PhaseChat([empty_resp(), empty_resp()], [empty_resp(), empty_resp()])
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat, solve_fn=real_solve)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], OUTCOME_FAILED)
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["attempts_detail"]), 2)
        self.assertIn("高保真尝试失败", result["error"])
        self.assertIn("快速保底失败", result["error"])
        for att in result["attempts_detail"]:
            self.assertFalse(att["ok"])
            self.assertEqual(att["failure"]["kind"], "protocol")


class NoFallbackGuardTest(IsolatedArtifactsTest):
    """取消、总时限耗尽、剩余时间不足时不启动保底。"""

    def test_cancel_stops_without_fallback(self):
        cancel = threading.Event()
        chat = PhaseChat([resp(PLAN)], [resp(PLAN), resp(SAVE_FAST)])

        def chat_with_cancel(messages, **kw):
            cancel.set()  # 第一次模型调用期间用户取消
            return chat(messages, **kw)

        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat_with_cancel,
                                   solve_fn=real_solve, cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["outcome"], OUTCOME_CANCELLED)
        self.assertEqual(len(chat.scripts[1].items), 2, "取消后不得触发快速保底")

    def test_deadline_exhaustion_no_fallback(self):
        now = [0.0]
        chat = PhaseChat([resp(PLAN)], [resp(PLAN), resp(SAVE_FAST)])

        def chat_jump_clock(messages, **kw):
            out = chat(messages, **kw)
            now[0] = 10 ** 9  # 第一次调用后直接跳到硬截止之后
            return out

        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat_jump_clock,
                                   solve_fn=real_solve, clock=lambda: now[0])
        self.assertFalse(result["ok"])
        self.assertEqual((result.get("failure") or {}).get("kind"), "deadline")
        self.assertEqual(result["outcome"], OUTCOME_FAILED)
        self.assertEqual(len(chat.scripts[1].items), 2, "总时限耗尽后不得发起保底")

    def test_insufficient_remaining_time_no_fallback(self):
        now = [0.0]
        inner = Script(empty_resp(), empty_resp())
        chat = PhaseChat(inner, Script(resp(PLAN), resp(SAVE_FAST)))

        def chat_burn_budget(messages, **kw):
            out = inner(messages, **kw)
            if not inner.items:  # 高保真尝试的最后一次调用结束后，时间几乎耗尽（剩 100s）
                now[0] = 1800.0 - 100.0
            return out

        result = run_with_fallback(DESC, mode="fidelity", chat_fn=chat_burn_budget,
                                   solve_fn=real_solve, clock=lambda: now[0])
        self.assertFalse(result["ok"])
        self.assertEqual((result.get("failure") or {}).get("kind"), "protocol")
        self.assertEqual(result["outcome"], OUTCOME_FAILED)
        self.assertEqual(len(chat.scripts[1].items), 2, "剩余时间不足不得发起保底")
        self.assertGreater(MIN_FALLBACK_S, 100, "保底最少剩余时间必须大于测试烧掉的 100s")


class ExplicitFastPassthroughTest(IsolatedArtifactsTest):
    """显式快速请求：单次执行、不调用视觉评审、不保底。"""

    def test_fast_mode_single_attempt(self):
        chat = PhaseChat([resp(PLAN), resp(SAVE_FAST)], [resp(PLAN)])
        result = run_with_fallback(DESC, mode="fast", chat_fn=chat, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FAST_SUCCESS)
        self.assertEqual(chat.i, 0)

    def test_fast_mode_does_not_call_review(self):
        """快速不执行视觉评审：评审函数一次都不许被调用，结果不带评审字段。"""
        calls = []

        def review_fn(*a, **k):
            calls.append(1)
            return dict(REVIEW_OK)

        chat = PhaseChat([resp(PLAN), resp(SAVE_FAST)], [resp(PLAN)])
        result = run_with_fallback(DESC, mode="fast", chat_fn=chat, review_fn=review_fn,
                                   solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(calls, [], "快速模式不得调用视觉评审")
        self.assertNotIn("attempts_detail", result)
        self.assertIsNone(result.get("review_flag"))

    def test_fast_mode_failure_stays_failed(self):
        chat = PhaseChat([empty_resp(), empty_resp()], [resp(PLAN)])
        result = run_with_fallback(DESC, mode="fast", chat_fn=chat, solve_fn=real_solve)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], OUTCOME_FAILED)
        self.assertNotIn("attempts_detail", result)


class ReviewContextUnitTest(unittest.TestCase):
    """评审意见提取与格式化的单元级断言。"""

    # 任务 8e873799 真实失败文本：门禁打回原文携带对嵌入部位不可达的改法指令
    GATE_ERROR = ("生成失败（protocol，阶段 revise）：阶段 revise 的实际请求已达 3 次上限"
                  "（最近打回原因：立体部位「spring_barrel」不满足任何几何独立判据（空气面 11 vs 贴合面 19，"
                  "属于实心块侧面局部抠格或无阶跃墙皮贴花）——即使换了颜色也不免检几何："
                  "请将其画成真实脱离主体轮廓凸出、串联截面阶跃或独立薄壁/斜面的结构）")
    COMPILE_ERROR = ("算子编译失败（不保存、不推进状态）：必需部位「enamel_dial」被后续算子完全覆盖"
                     "——请调整算子顺序或给它保留独立体素。请立即修正上述算子并重新输出完整 save_design3。")

    def test_extract_from_degraded_result(self):
        res = {"ok": True, "review_failed": True,
               "review": {"scores": {"overall": 5, "color": 4},
                          "missing_features": ["车灯缺失"], "worst_parts": ["车头"],
                          "suggestions": ["车头前伸 1 格"], "keep": ["车顶"]}}
        ctx = review_context_from_result(res)
        self.assertTrue(ctx["reviewAvailable"])
        self.assertEqual(ctx["flag"], "review_failed")
        self.assertEqual(ctx["missingFeatures"], ["车灯缺失"])
        self.assertEqual(ctx["keepParts"], ["车顶"])

    def test_extract_from_failed_result_without_review(self):
        res = {"ok": False, "error": "阶段 draw 的实际请求已达 3 次上限",
               "failure": {"kind": "protocol", "stage": "draw"}, "review": {}}
        ctx = review_context_from_result(res)
        self.assertFalse(ctx["reviewAvailable"])
        self.assertEqual(ctx["failureKind"], "protocol")
        self.assertIn("protocol", ctx["failureSummary"])
        msg = format_review_message(ctx)
        self.assertIn("没有可用的视觉评审意见", msg)
        self.assertIn("3 次上限", msg)

    def test_no_info_returns_none(self):
        self.assertIsNone(review_context_from_result(None))
        self.assertIsNone(review_context_from_result({"ok": True}))

    def test_message_respects_original_requirement(self):
        msg = format_review_message(review_context_from_result({
            "ok": False, "error": "求解失败", "failure": {"kind": "class2"},
            "review": {"scores": {"overall": 5}, "keep": ["桅杆"]}}))
        self.assertIn("不是新需求", msg)
        self.assertIn("桅杆", msg)
        self.assertIn("不放宽", msg)
        self.assertNotIn("表面涂装", msg, "非门禁类失败不必附加替代路径提示")

    def test_failure_summary_strips_model_instructions(self):
        """注入的失败原因只保留事实，剥离「请将其画成……」等几何改法指令。"""
        ctx = review_context_from_result({"ok": False, "error": self.GATE_ERROR,
                                          "failure": {"kind": "protocol", "stage": "revise"},
                                          "review": {}})
        summary = ctx["failureSummary"]
        self.assertIn("spring_barrel", summary, "被打回部位名是事实，必须保留")
        self.assertIn("几何独立判据", summary)
        self.assertNotIn("请将其画成", summary)
        self.assertNotIn("请立即修正", summary)
        self.assertNotIn("请调整算子顺序", summary)

    def test_compile_failure_summary_strips_instructions(self):
        ctx = review_context_from_result({"ok": False, "error": self.COMPILE_ERROR,
                                          "failure": {"kind": "protocol", "stage": "draw"},
                                          "review": {}})
        summary = ctx["failureSummary"]
        self.assertIn("enamel_dial", summary)
        self.assertNotIn("请立即修正", summary)
        self.assertNotIn("save_design3", summary)

    def test_gate_failure_message_adds_feasible_alternatives(self):
        """门禁类失败在注入时补充可行替代路径，不再让重试追不可达目标。"""
        msg = format_review_message(review_context_from_result({
            "ok": False, "error": self.GATE_ERROR,
            "failure": {"kind": "protocol", "stage": "revise"}, "review": {}}))
        self.assertIn("表面涂装", msg)
        self.assertIn("不是必须照搬的改法", msg)
        self.assertNotIn("请将其画成", msg)

    def test_legacy_context_without_failure_kind_still_guided(self):
        """历史任务存量的意见没有 failureKind 字段：凭失败文本识别门禁类并补提示。"""
        msg = format_review_message({"reviewAvailable": False,
                                     "failureSummary": "失败类别 gate（阶段 draw）：「x」不满足任何几何独立判据"})
        self.assertIn("表面涂装", msg)


class WorkflowReviewContextInjectionTest(IsolatedArtifactsTest):
    """主链级：review_context 作为独立用户消息注入，缺省时行为与既往一致。"""

    def test_run_generation_appends_review_context_after_desc(self):
        seen = []

        def chat(messages, **kw):
            seen.append([dict(m) for m in messages])
            return resp(PLAN if len(seen) == 1 else SAVE_FAST)

        result = run_generation(DESC, chat_fn=chat, solve_fn=real_solve,
                                review_context="上次评审：保留旗杆")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(seen[0][1]["content"], DESC)
        self.assertEqual(seen[0][2]["content"], "上次评审：保留旗杆")

    def test_run_generation_without_context_unchanged(self):
        seen = []

        def chat(messages, **kw):
            seen.append([dict(m) for m in messages])
            return resp(PLAN if len(seen) == 1 else SAVE_FAST)

        result = run_generation(DESC, chat_fn=chat, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        # 首次调用时消息为 [system, 原始需求, plan 阶段指令]：没有注入的评审消息
        self.assertEqual(len(seen[0]), 3, "无继承意见时消息列表保持原样")
        self.assertEqual(seen[0][1]["content"], DESC)


if __name__ == "__main__":
    unittest.main()
