# -*- coding: utf-8 -*-
"""LLM 调用协议测试。

只验机制，不调用真实模型：
- chat() 统一返回 {content, reasoning_content, finish, requests}；
- 流式未收到数据时失败才允许回退普通请求（requests=2）；已收到部分流数据后不重发；
- 截止（绝对时刻）后不发起新请求，截止/取消不回退重发；
- 推理 JSON 恢复：恰好一个完整 JSON 且 action 匹配当前阶段才恢复；
- 每阶段实际请求上限 2 次（首次、流式转普通和重试合并计数）。
"""
import json
import sys
import os
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import llm  # noqa: E402


def _block_resp(content='{"ok": true}', reasoning="", finish="stop"):
    return content, reasoning, finish, 1


class IterJsonObjectsTest(unittest.TestCase):
    def test_multiple_objects_in_order(self):
        text = '{"a": 1} 中间杂质 {"b": 2}'
        objs = list(llm.iter_json_objects(text))
        self.assertEqual(objs, [{"a": 1}, {"b": 2}])

    def test_braces_inside_strings(self):
        text = '{"thought": "用 { } 画轮廓", "action": "plan_design"}'
        self.assertEqual(list(llm.iter_json_objects(text))[0]["action"], "plan_design")

    def test_incomplete_object_skipped(self):
        text = '{"a": 1, "b": [1, 2'
        self.assertEqual(list(llm.iter_json_objects(text)), [])

    def test_parse_json_takes_first_complete(self):
        text = '```json\n{"action": "save_design"}\n``` {"action": "run_solver"}'
        self.assertEqual(llm.parse_json(text)["action"], "save_design")


class ChatContractTest(unittest.TestCase):
    """chat() 的返回结构与请求计数（mock 底层 HTTP 函数，不发真实请求）。"""

    def test_block_returns_unified_dict(self):
        with mock.patch.object(llm, "_chat_block", return_value=_block_resp("正文", "思考", "stop")):
            out = llm.chat([{"role": "user", "content": "hi"}], on_progress=None)
        self.assertEqual(out, {"content": "正文", "reasoning_content": "思考",
                               "finish": "stop", "requests": 1})

    def test_stream_used_when_progress_given(self):
        with mock.patch.object(llm, "_chat_stream", return_value=("正文", "思考", "stop", 1)) as st, \
             mock.patch.object(llm, "_chat_block") as blk:
            out = llm.chat([{"role": "user", "content": "hi"}], on_progress=lambda t, e: None)
        st.assert_called_once()
        blk.assert_not_called()
        self.assertEqual(out["requests"], 1)

    def test_stream_fallback_counts_two_requests(self):
        """流式在未收到任何数据时失败 → 回退普通请求；首次 + 回退合并计数 = 2。"""
        with mock.patch.object(llm, "_chat_stream", side_effect=ValueError("连接被拒")), \
             mock.patch.object(llm, "_chat_block", return_value=_block_resp("正文")) as blk:
            out = llm.chat([{"role": "user", "content": "hi"}], on_progress=lambda t, e: None)
        blk.assert_called_once()
        self.assertEqual(out["requests"], 2)

    def test_partial_stream_data_never_resent(self):
        """已收到部分流数据后中断（LLMStreamBroken）→ 不得回退重发。"""
        with mock.patch.object(llm, "_chat_stream", side_effect=llm.LLMStreamBroken("中断")), \
             mock.patch.object(llm, "_chat_block") as blk:
            with self.assertRaises(llm.LLMStreamBroken):
                llm.chat([{"role": "user", "content": "hi"}], on_progress=lambda t, e: None)
        blk.assert_not_called()

    def test_deadline_in_past_raises_without_request(self):
        """截止已过 → 立即抛 LLMDeadline，不发任何 HTTP 请求。"""
        with mock.patch.object(llm, "_request") as req:
            with self.assertRaises(llm.LLMDeadline):
                llm.chat([{"role": "user", "content": "hi"}], deadline=time.monotonic() - 1)
            with self.assertRaises(llm.LLMDeadline):
                llm.chat([{"role": "user", "content": "hi"}], deadline=time.monotonic() - 1,
                         on_progress=lambda t, e: None)
        req.assert_not_called()

    def test_deadline_blocks_stream_fallback(self):
        """流式失败且已过截止 → 直接抛 LLMDeadline，不回退重发。"""
        with mock.patch.object(llm, "_chat_stream", side_effect=ValueError("断流")), \
             mock.patch.object(llm, "_chat_block") as blk:
            with self.assertRaises(llm.LLMDeadline):
                llm.chat([{"role": "user", "content": "hi"}],
                         deadline=time.monotonic() - 1, on_progress=lambda t, e: None)
        blk.assert_not_called()

    def test_reasoning_effort_forwarded(self):
        body_seen = {}

        def fake_block(body, timeout, verbose):
            body_seen.update(body)
            return _block_resp("x")

        with mock.patch.object(llm, "_chat_block", side_effect=fake_block):
            llm.chat([{"role": "user", "content": "hi"}], reasoning_effort="low")
        self.assertEqual(body_seen.get("reasoning_effort"), "low")

    def test_no_reasoning_effort_by_default(self):
        body_seen = {}

        def fake_block(body, timeout, verbose):
            body_seen.update(body)
            return _block_resp("x")

        with mock.patch.object(llm, "_chat_block", side_effect=fake_block):
            llm.chat([{"role": "user", "content": "hi"}])
        self.assertNotIn("reasoning_effort", body_seen)


class ReasoningCallbackTest(unittest.TestCase):
    """推理原文回调：独立节流、与正文分离、可取消、非流式补发。"""

    def _fake_request(self, deltas):
        """把 _request 换成逐行吐 SSE 的假响应，deltas 为 delta 字典列表。"""
        lines = []
        for d in deltas:
            lines.append(("data: " + json.dumps({"choices": [{"delta": d}]}) + "\n").encode())
        lines.append(b"data: [DONE]\n")

        class _Resp:
            def __enter__(self_inner):
                return iter(lines)

            def __exit__(self_inner, *a):
                return False

        return mock.patch.object(llm, "_request", return_value=_Resp())

    def test_reasoning_only_reaches_on_reasoning(self):
        """推理增量只交给 on_reasoning，正文只交给 on_progress，互不混入。"""
        seen_prog, seen_rz = [], []
        deltas = [{"reasoning_content": "想"}, {"reasoning_content": "一"}, {"content": "正文"}]
        with self._fake_request(deltas), mock.patch.object(llm, "REASONING_MIN_INTERVAL", 0):
            out = llm.chat([{"role": "user", "content": "hi"}], verbose=False,
                           on_progress=lambda t, e: seen_prog.append(t),
                           on_reasoning=lambda t, e: seen_rz.append(t))
        self.assertEqual(out["content"], "正文")
        self.assertEqual(out["reasoning_content"], "想一")
        self.assertTrue(seen_rz, "推理回调必须被调用")
        self.assertEqual(seen_rz[-1], "想一", "最后一次回调必须是完整推理")
        self.assertTrue(all("正文" not in t for t in seen_rz), "正文不得混进推理回调")
        self.assertEqual(seen_prog[-1], "正文", "正文回调只拿正文")

    def test_reasoning_throttled_independently(self):
        """两个回调各自节流：间隔阈值互不影响。"""
        seen_rz, seen_prog = [], []
        deltas = [{"reasoning_content": "a"}] * 5 + [{"content": "b"}] * 5
        with self._fake_request(deltas), \
                mock.patch.object(llm, "REASONING_MIN_INTERVAL", 9999), \
                mock.patch.object(llm.time, "time", side_effect=[i * 0.01 for i in range(200)]):
            llm.chat([{"role": "user", "content": "hi"}], verbose=False,
                     on_progress=lambda t, e: seen_prog.append(t),
                     on_reasoning=lambda t, e: seen_rz.append(t))
        # 推理回调被自己的阈值压住：流式期间一次都不发，只有结束时的补发一次
        self.assertEqual(len(seen_rz), 1, f"推理回调应只补发一次，实得 {seen_rz}")

    def test_reasoning_callback_can_cancel(self):
        """on_reasoning 抛 LLMCancelled 必须穿透 _safe_cb 中止请求。"""
        calls = []

        def cb(text, elapsed):
            calls.append(text)
            raise llm.LLMCancelled()

        deltas = [{"reasoning_content": "想"}, {"reasoning_content": "二"}]
        with self._fake_request(deltas), mock.patch.object(llm, "REASONING_MIN_INTERVAL", 0):
            with self.assertRaises(llm.LLMCancelled):
                llm.chat([{"role": "user", "content": "hi"}], verbose=False,
                         on_reasoning=cb)
        self.assertEqual(len(calls), 1, "取消后不得继续回调")

    def test_reasoning_only_enables_stream(self):
        """只传 on_reasoning 也要走流式（推理只有逐 delta 才有意义）。"""
        with mock.patch.object(llm, "_chat_stream", return_value=("正文", "思考", "stop", 1)) as st, \
                mock.patch.object(llm, "_chat_block") as blk:
            llm.chat([{"role": "user", "content": "hi"}], on_reasoning=lambda t, e: None)
        st.assert_called_once()
        blk.assert_not_called()

    def test_no_callbacks_uses_block(self):
        """两个回调都不传时仍走普通请求（不因新参数改变既有语义）。"""
        with mock.patch.object(llm, "_chat_block", return_value=_block_resp("正文")) as blk, \
                mock.patch.object(llm, "_chat_stream") as st:
            llm.chat([{"role": "user", "content": "hi"}])
        blk.assert_called_once()
        st.assert_not_called()

    def test_stream_path_without_reasoning_emits_nothing(self):
        """服务商不返回推理时一个事件都不发（界面完全隐藏该区域）。"""
        seen = []
        with mock.patch.object(llm, "_chat_stream",
                               return_value=("正文", "", "stop", 1)) as st, \
                mock.patch.object(llm, "_chat_block") as blk:
            llm.chat([{"role": "user", "content": "hi"}], on_reasoning=lambda t, e: seen.append(t))
        st.assert_called_once()
        blk.assert_not_called()
        self.assertEqual(seen, [])

    def test_stream_end_emits_full_reasoning_once(self):
        """流式结束补发一次完整推理：首个增量立即展示，末尾再补一次全量。"""
        seen = []
        deltas = [{"reasoning_content": "整"}, {"reasoning_content": "段"}, {"content": "正文"}]
        with self._fake_request(deltas), mock.patch.object(llm, "REASONING_MIN_INTERVAL", 9999):
            llm.chat([{"role": "user", "content": "hi"}], verbose=False,
                     on_reasoning=lambda t, e: seen.append(t))
        self.assertEqual(seen[-1], "整段", "末尾必须补发完整推理")
        self.assertEqual(seen.count("整段"), 1, f"全量推理只补发一次：{seen}")

    def test_stream_fallback_emits_block_reasoning(self):
        """流式未收到数据就失败 → 回退普通请求，推理仍要在返回后补发一次。"""
        seen = []
        with mock.patch.object(llm, "_chat_stream", side_effect=ValueError("连接被拒")), \
                mock.patch.object(llm, "_chat_block", return_value=_block_resp("正文", "回退推理", "stop")):
            out = llm.chat([{"role": "user", "content": "hi"}], on_progress=lambda t, e: None,
                           on_reasoning=lambda t, e: seen.append(t))
        self.assertEqual(out["requests"], 2)
        self.assertEqual(seen, ["回退推理"])


if __name__ == "__main__":
    unittest.main()
