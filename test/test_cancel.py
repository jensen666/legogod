# -*- coding: utf-8 -*-
"""运行中任务取消功能回归测试。

覆盖取消链路的所有阶段（Web 工坊按钮 → DELETE /api/job/<id> 已由
test_server_routes.py 覆盖，本文件补齐其余环节）：
1) 模型阶段：chat_fn 里置取消位 → 主链下一检查点抛 CancelledError，结果如实标记
   cancelled 且运行记录照常落盘（不是 traceback 杀进程）；
2) 评审阶段（review_design 单元级）：流式进度回调识别 should_stop → 打断 in-flight
   请求并返回 stopped_by_cancel；请求发起前已取消则零请求直接返回；
3) 评审阶段（主链级）：stopped_by_cancel 由 do_review_once 转为 CancelledError，
   不得被降级成 review_unavailable 继续烧请求；
4) 求解阶段：should_stop 触发 TilerCancelled → 主链 CancelledError；
5) CLI：Ctrl+C（SIGINT）→ 取消事件 → 返回「任务已取消」、退出码 1。

不调用真实模型：chat_fn / review_fn / solve_fn 全部注入。
"""
import io
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, Script, resp  # noqa: E402
from legogod import cli, review, tiler  # noqa: E402
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

SAVE = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "chain-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [{"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"]},
               {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]}],
}}


class ModelStageCancelTest(IsolatedArtifactsTest):
    """模型阶段取消：chat_fn 返回途中置取消位，主链在下一检查点如实取消。"""

    def test_cancel_during_model_stage(self):
        cancel = threading.Event()

        def chat_fn(messages, **kw):
            cancel.set()  # 模拟用户在第一次模型调用期间点击取消
            return resp(PLAN)

        result = run_generation(DESC, chat_fn=chat_fn, cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error"], "任务已取消")
        self.assertEqual((result.get("failure") or {}).get("kind"), "cancelled")
        # 取消不是崩溃：运行记录照常落盘，供历史栏回看
        record_path = os.path.join(self.tmp, f"run_{result['run_id']}.json")
        self.assertTrue(os.path.isfile(record_path), "取消任务的运行记录必须落盘")
        with open(record_path, encoding="utf-8") as f:
            self.assertFalse(json.load(f)["ok"])


class SolveStageCancelTest(IsolatedArtifactsTest):
    """求解阶段取消：should_stop 触发 TilerCancelled，主链转为任务取消。"""

    def test_cancel_during_solve_stage(self):
        cancel = threading.Event()
        seen = {}

        def cancelling_solve(model, layers, **kw):
            seen["should_stop"] = kw.get("should_stop")
            cancel.set()
            raise tiler.TilerCancelled()

        result = run_generation(DESC, chat_fn=Script(resp(PLAN), resp(SAVE)),
                                solve_fn=cancelling_solve, cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error"], "任务已取消")
        self.assertTrue(callable(seen["should_stop"]), "求解器必须收到取消检查回调")


class ReviewUnitCancelTest(unittest.TestCase):
    """review_design 单元级：取消信号打断 in-flight 评审请求 / 请求发起前短路。"""

    def _review_with_fake_llm(self, stop_event):
        """渲染与图片编码全部打桩，fake llm.chat 走真实 on_progress 取消接线。"""
        seen = {}

        def fake_chat(messages, **kw):
            seen["on_progress"] = kw.get("on_progress")
            cb = kw.get("on_progress")
            if cb:
                cb("", 1.0)  # 第一次回调：尚未取消，正常
                stop_event.set()  # 模拟用户在评审输出途中点击取消
                cb("", 2.0)  # 第二次回调：review 的 on_progress 应抛 LLMCancelled
            raise AssertionError("LLMCancelled 未被 on_progress 抛出")

        patches = [
            mock.patch.object(review.llm, "chat", fake_chat),
            mock.patch("legogod.render.render_views", return_value={"front": "f.png"}),
            mock.patch("legogod.render.compose_sheet", return_value="sheet.png"),
            mock.patch.object(review, "_image_b64", return_value=("QUJD", "image/png")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        out = review.review_design(DESC, {"name": "x"}, out_dir=tempfile.mkdtemp(),
                                   verbose=False, should_stop=stop_event.is_set)
        return out, seen

    def test_progress_callback_aborts_inflight_review(self):
        stop = threading.Event()
        out, seen = self._review_with_fake_llm(stop)
        self.assertIsNotNone(seen["on_progress"], "取消接入必须给 llm.chat 传 on_progress")
        self.assertTrue(out["stopped_by_cancel"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["requests"], 0)

    def test_precancelled_review_sends_no_request(self):
        stop = threading.Event()
        stop.set()  # 发起评审请求之前已取消
        out, _ = self._review_with_fake_llm(stop)
        self.assertTrue(out["stopped_by_cancel"])
        self.assertEqual(out["requests"], 0, "已取消时不得再发评审请求烧额度")


class ReviewChainCancelTest(IsolatedArtifactsTest):
    """主链级：stopped_by_cancel 由 do_review_once 转为 CancelledError（不得降级继续跑）。"""

    # 高保真模式要求逐体素配色（colorRows 或 colorPatches），否则画稿会被打回
    SAVE_FIDELITY = {"thought": "", "action": "save_design", "args": {
        "name": "测试塔", "slug": "chain-fidelity", "notes": "", "features": ["塔身方形"],
        "defaultPart": "tower",
        "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
        "layers": [
            {"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"],
             "colorPatches": [{"color": "黑色", "cells": [[1, 1]]}]},
            {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]},
        ],
    }}

    def test_cancel_during_visual_review(self):
        cancel = threading.Event()
        seen = {}

        def review_fn(desc, model, solution=None, **kw):
            seen["should_stop"] = kw.get("should_stop")
            cancel.set()  # 评审请求途中用户点击取消
            return {"ok": False, "requests": 1, "raw": "", "finish": None, "parsed": {},
                    "views": {}, "sheet": None, "stopped_by_deadline": False,
                    "stopped_by_cancel": True}

        result = run_generation(DESC, mode="fidelity", chat_fn=Script(resp(PLAN), resp(self.SAVE_FIDELITY)),
                                review_fn=review_fn, cancel=cancel)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["error"], "任务已取消")
        # 取消绝不能被吞成 review_unavailable 后继续求解（cancelled 分支在 freeze/solve 之前）
        self.assertNotEqual(result["status"], "done")
        self.assertTrue(callable(seen["should_stop"]), "评审必须收到取消检查回调")


class CliCancelTest(unittest.TestCase):
    """CLI：Ctrl+C（SIGINT）→ 取消事件 → 温和退出并如实报告，而不是 traceback。"""

    def test_ctrl_c_cancels_running_build(self):
        started = threading.Event()

        def fake_run(desc, cancel=None, **kw):
            started.set()
            cancel.wait(10)
            return {"ok": False, "error": "任务已取消", "status": "cancelled",
                    "failure": {"kind": "cancelled"}}

        def trigger_sigint():
            started.wait(5)
            time.sleep(0.1)
            signal.raise_signal(signal.SIGINT)

        buf = io.StringIO()
        with mock.patch.object(cli, "run_generation", fake_run):
            t = threading.Thread(target=trigger_sigint)
            t.start()
            with redirect_stdout(buf):
                rc = cli.main(["--desc", "测试塔", "--yes"])
            t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(rc, 1)
        self.assertIn("任务已取消", buf.getvalue())

    def test_normal_build_unchanged(self):
        """未按 Ctrl+C 时结果原样透传（取消改造不影响正常路径）。"""
        ok = {"ok": True, "name": "塔", "grid": {"w": 4, "d": 4}, "layers": 2,
              "voxels": 32, "pieces": 6, "attempts": 1, "run_id": "abc",
              "revision": 1, "status": "done"}
        with mock.patch.object(cli, "run_generation", lambda desc, **kw: ok):
            with redirect_stdout(io.StringIO()):
                rc = cli.main(["--desc", "测试塔", "--yes"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
