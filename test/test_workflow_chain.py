# -*- coding: utf-8 -*-
"""固定主链端到端机制测试。

不调用真实模型：chat_fn / review_fn / solve_fn / clock 全部注入。
求解用真实 tiler（小型夹具），验证「每版有效设计都真正经过求解与统一校验」。
"""
import json
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, Script, real_solve, resp  # noqa: E402
from legogod import tiler, workflow  # noqa: E402
from legogod.workflow_artifacts import model_hash  # noqa: E402
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

# 漏标旗杆的画稿：defaultPart 把全部实体归塔身，旗杆必需部位没有实体
SAVE_NO_FLAG = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "chain-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower", "partPatches": [],
    "layers": [{"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"]},
               {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]}],
}}

# 标注坐标标错（网格外）：该格被忽略并警告，画稿保留 → 进入只标注阶段补救
SAVE_BAD_LABEL = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "chain-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[9, 9, 9]]}],
    "layers": [{"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"]},
               {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]}],
}}

# 只标注阶段：补标旗杆（合法）/ 仍然漏标（绑定失败）
LABEL_PATCH = {"thought": "", "action": "label_parts", "args": {
    "defaultPart": "tower", "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}]}}
LABEL_MISSING = {"thought": "", "action": "label_parts", "args": {
    "defaultPart": "tower", "partPatches": []}}

# 断连设计：左块 x0..1 + 右柱 x=3，x=2 为空 → 预检报「互不相连」
DISCONNECTED_ROWS = ["##.#", "##.#", "##.#", "##.#"]
PLAN_NARROW = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
    "parts": [
        {"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"},
    ],
}}
SAVE_DISCONNECTED = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "chain-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower", "partPatches": [],
    "layers": [{"module": "底", "color": "浅灰", "rows": list(DISCONNECTED_ROWS)},
               {"module": "顶", "color": "白色", "rows": list(DISCONNECTED_ROWS)}],
}}
# 搭桥补丁：把 x=2 列填上（y0..1 × z0..3，共 8 格）；新增实体没带 part，归 defaultPart=tower
BRIDGE_EDITS = [{"x": 2, "y": y, "z": z, "voxel": "#"} for y in (0, 1) for z in range(4)]
BRIDGE_PATCH = {"thought": "", "action": "revise_design",
                "args": {"baseRevision": "r001", "edits": BRIDGE_EDITS}}


class WorkflowChainTest(IsolatedArtifactsTest):
    def _run(self, script, **kw):
        kw.setdefault("solve_fn", real_solve)
        return run_generation(DESC, chat_fn=script, **kw)

    def test_happy_path_solves_and_generates_artifacts(self):
        """plan → save → 部位检查 → 预检 → 求解+统一校验 → 自动产物（不再询问模型）。"""
        script = Script(resp(PLAN), resp(SAVE))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["revision"], 1)
        self.assertEqual(len(script.calls), 2, "求解与产物生成不得再调用模型")
        self.assertTrue(script.calls[0].get("deadline"), "模型调用必须带绝对截止")
        self.assertEqual(script.calls[1].get("reasoning_effort"), "low", "画图用低推理预算")
        # 产物存在且带 run_id/revision
        for key in ("model_path", "solution_path", "md_path"):
            self.assertTrue(result.get(key), key)
            path = self._art(result[key])
            self.assertTrue(os.path.isfile(path), path)
        self.assertTrue(result.get("viz_file"), "viz_file")
        self.assertTrue(os.path.isfile(os.path.join(self.viz_tmp, result["viz_file"])))
        self.assertIn("_r001_", result["solution_path"])
        self.assertIn(result["run_id"], result["solution_path"])
        with open(self._art(result["solution_path"]), encoding="utf-8") as f:
            sol = json.load(f)
        self.assertTrue(sol["validation"]["ok"])
        self.assertEqual(sol["revision"], "r001")
        self.assertEqual(sol["runId"], result["run_id"])
        # 方案记录模型内容哈希
        with open(self._art(result["model_path"]), encoding="utf-8") as f:
            model_record = json.load(f)
        self.assertEqual(sol["modelHash"], model_hash(model_record))
        # 方案里必须有部位绑定存档（语义 + 程序生成的区域与核心）
        self.assertEqual(model_record["parts"][0]["id"], "tower")
        self.assertGreater(model_record["parts"][0]["voxels"], 0)
        self.assertTrue(model_record["parts"][0]["coreCells"])
        self.assertNotIn("coreBoxes", model_record["parts"][0])
        # 一次成功，无任何修订
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(result["counts"], {"revise_class1": 0, "revise_class2": 0,
                                            "revise_visual": 0})

    def test_historical_versions_not_overwritten(self):
        """两次运行同 slug：run_id 不同，产物互不覆盖。"""
        r1 = self._run(Script(resp(PLAN), resp(SAVE)))
        r2 = self._run(Script(resp(PLAN), resp(SAVE)))
        self.assertTrue(r1["ok"] and r2["ok"])
        self.assertNotEqual(r1["run_id"], r2["run_id"])
        self.assertNotEqual(r1["solution_path"], r2["solution_path"])
        for r in (r1, r2):
            self.assertTrue(os.path.isfile(self._art(r["solution_path"])))

    def test_missing_required_label_enters_label_phase_without_redraw(self):
        """初次画稿漏标必需部位：只补标注（label_parts），不重新 save_design。"""
        script = Script(resp(PLAN), resp(SAVE_NO_FLAG), resp(LABEL_PATCH))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 3, "PLAN + save_design + 1 次 label_parts")
        self.assertEqual(result["revision"], 1)
        with open(self._art(result["model_path"]), encoding="utf-8") as f:
            model_record = json.load(f)
        self.assertEqual([p["id"] for p in model_record["parts"]], ["tower", "flag"])
        self.assertEqual(model_record["parts"][1]["voxels"], 1)

    def test_label_phase_twice_still_missing_fails_parts(self):
        """补标注两次仍缺必需部位：如实失败 kind=parts、stage=label，且没有第二次 save_design。"""
        script = Script(resp(PLAN), resp(SAVE_NO_FLAG), resp(LABEL_MISSING), resp(LABEL_MISSING))
        result = self._run(script)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "parts")
        self.assertEqual(result["failure"]["stage"], "label")
        self.assertEqual(len(script.calls), 4,
                         "PLAN + save_design + 2 次 label_parts，不得再 save_design")

    def test_label_phase_rejects_redraw(self):
        """标注阶段只接受 label_parts：输出 save_design 会被拒绝并重试。"""
        script = Script(resp(PLAN), resp(SAVE_NO_FLAG), resp(SAVE), resp(LABEL_PATCH))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 4, "被拒绝的 save_design 不推进状态")

    def test_invalid_label_cell_does_not_bounce_drawing(self):
        """初次标注坐标标到空格/网格外：不整稿打回，画稿保留并进入只标注阶段补齐。"""
        script = Script(resp(PLAN), resp(SAVE_BAD_LABEL), resp(LABEL_PATCH))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 3, "PLAN + save_design + 1 次 label_parts（未重画）")
        self.assertEqual(result["revision"], 1)

    def test_class1_revision_via_patch(self):
        """预检失败（断连）→ revise_design 补丁搭桥 → 求解成功；计数 1、版本 2。"""
        script = Script(resp(PLAN_NARROW), resp(SAVE_DISCONNECTED), resp(BRIDGE_PATCH))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class1"], 1)
        self.assertEqual(result["revision"], 2)
        self.assertIn("_r001_", result["artifacts"]["model_r001"])
        self.assertIn("_r002_", result["artifacts"]["model_r002"])

    def test_invalid_patch_is_protocol_retry_not_revision(self):
        """baseRevision 过期的补丁被拒收：保留上一版本，同阶段重试成功后只计 1 次修订。"""
        stale_patch = {"thought": "", "action": "revise_design", "args": {
            "baseRevision": "r000",
            "edits": [{"x": 2, "y": 0, "z": 0, "voxel": "#"}]}}
        script = Script(resp(PLAN_NARROW), resp(SAVE_DISCONNECTED), resp(stale_patch), resp(BRIDGE_PATCH))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class1"], 1, "无效补丁不消耗修订次数")
        self.assertEqual(result["revision"], 2)

    @mock.patch.dict(os.environ, {"LEGOGOD_STRUCT_CANDIDATES": "off"})
    def test_class2_revision_when_first_solve_fails(self):
        """求解失败（结构化 failureKind）→ 第 2 类补丁修订 → 再求解成功。

        确定性结构候选默认开启时，solution 空间候选可能先于模型类 2 修订救回；
        本用例验证的是「模型类 2 修订」机制本身，因此显式关闭候选
        （候选开启时的行为由 test_structure_candidates.py 覆盖）。
        """
        calls = []

        def solve_fn(model, layers, **kw):
            calls.append(kw.get("deadline"))
            if len(calls) == 1:
                return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                              "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": None}
            return tiler.solve_with_budget(model, layers, **kw)

        no_op_patch = {"thought": "", "action": "revise_design", "args": {
            "baseRevision": "r001",
            "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "浅灰"}]}}
        script = Script(resp(PLAN), resp(SAVE), resp(no_op_patch))
        result = self._run(script, solve_fn=solve_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class2"], 1)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(len(calls), 2)

    def test_class2_revisions_exhausted_is_fatal(self):
        """第 2 类修订 2 次用尽后如实失败，失败类别可追溯。"""
        def always_fail(model, layers, **kw):
            return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                          "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": None}

        def no_op(rev):
            return {"thought": "", "action": "revise_design", "args": {
                "baseRevision": rev,
                "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "浅灰"}]}}

        script = Script(resp(PLAN), resp(SAVE), resp(no_op("r001")), resp(no_op("r002")))
        result = self._run(script, solve_fn=always_fail)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "disconnected")
        self.assertIn("最终求解未通过", result["error"])
        self.assertNotIn("class2", result["failure"]["kind"])
        self.assertTrue(result["revisionIncomplete"])
        self.assertEqual(result["counts"]["revise_class2"], 2)
        self.assertEqual(result["revision"], 3)

    def test_solver_offer_is_not_shipped(self):
        """求解失败带出的重铺快照不进入任务结果，求解器手里的元组键字典保持原样。"""
        offer = {"layer": 1, "stud_owner": {(1, 2): 0, (3, 4): 1}}

        def fail_internal(model, layers, **kw):
            return None, {"kind": "internal", "message": "求解器内部错误（测试注入）",
                          "layer": 1, "cells": [(0, 1, 2)], "offer": offer}

        result = self._run(Script(resp(PLAN), resp(SAVE)), solve_fn=fail_internal)
        self.assertFalse(result["ok"])
        nested = result["failure"].get("failure") or {}
        self.assertNotIn("offer", nested)
        self.assertEqual(nested.get("kind"), "internal")
        json.dumps(result)
        self.assertEqual(offer["stud_owner"][(1, 2)], 0)

        def fail_final(model, layers, **kw):
            return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                          "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": offer}

        def no_op(rev):
            return {"thought": "", "action": "revise_design", "args": {
                "baseRevision": rev,
                "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "浅灰"}]}}

        script = Script(resp(PLAN), resp(SAVE), resp(no_op("r001")), resp(no_op("r002")))
        result = self._run(script, solve_fn=fail_final)
        self.assertFalse(result["ok"])
        self.assertIn("最终求解未通过", result["error"])
        nested = result["failure"].get("failure") or {}
        self.assertNotIn("offer", nested)
        self.assertEqual(nested.get("cells"), [[0, 0, 0]])
        json.dumps(result)
        self.assertEqual(offer["stud_owner"][(3, 4)], 1)

    def test_last_90s_stops_model_calls_and_runs_final_solve(self):
        """模型截止后：不再调用模型；部位检查通过的设计走预检 + 最终求解 + 产物。"""
        t0 = time.monotonic()
        base = Script(resp(PLAN), resp(SAVE))
        calls = []

        def chat(messages, **kw):
            out = base(messages, **kw)
            return out

        def clock():
            # 画完图后跳到模型截止之后（最后 90 秒内），但仍在硬截止之前；
            # 偏移基于真实 monotonic，保证注入到 tiler 的截止与真实时钟一致
            return t0 + (1760.0 if len(base.calls) >= 2 else 0.0)

        def solve_fn(model, layers, **kw):
            calls.append(1)
            if len(calls) == 1:
                return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                              "layer": 0, "cells": [(0, 0, 0)], "rounds": 8, "offer": None}
            return tiler.solve_with_budget(model, layers, **kw)

        result = run_generation(DESC, chat_fn=chat, solve_fn=solve_fn, clock=clock)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(base.calls), 2, "截止后不得再调用模型")
        self.assertEqual(len(calls), 2, "首次求解失败后应在最终阶段再求解一次")

    def test_no_valid_design_at_deadline_fails_honestly(self):
        """截止时还没有有效设计：如实失败，不宽限。"""
        now = [0.0]
        base = Script(resp(PLAN))

        def chat(messages, **kw):
            out = base(messages, **kw)
            now[0] = 10 ** 9
            return out

        result = run_generation(DESC, chat_fn=chat, clock=lambda: now[0])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "deadline")

    def test_unexpected_action_not_accepted(self):
        """画图阶段输出 plan_design（非预期 action）→ 反馈重试，不推进状态。"""
        wrong = {"action": "plan_design", "args": {}}
        script = Script(resp(PLAN), resp(wrong), resp(SAVE))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 3)

    def test_empty_output_recovered_from_reasoning(self):
        """正文为空且 finish=length：推理文本中恰好一个匹配 action 的 JSON 才恢复。"""
        reasoning = json.dumps(SAVE, ensure_ascii=False)
        script = Script(resp(PLAN),
                        {"content": "", "reasoning_content": reasoning, "finish": "length", "requests": 1})
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 2, "恢复不需要额外请求")

    def test_multiple_json_candidates_not_recovered(self):
        """推理文本里有多个 JSON 候选：不恢复，按协议重试。"""
        reasoning = json.dumps(SAVE, ensure_ascii=False) + " " + json.dumps(PLAN, ensure_ascii=False)
        script = Script(resp(PLAN),
                        {"content": "", "reasoning_content": reasoning, "finish": "length", "requests": 1},
                        resp(SAVE))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 3, "重试后成功")

    def test_recovery_with_wrong_action_retries(self):
        """推理 JSON 的 action 不符当前阶段：不恢复，重试。"""
        reasoning = json.dumps(PLAN, ensure_ascii=False)
        script = Script(resp(PLAN),
                        {"content": "", "reasoning_content": reasoning, "finish": "length", "requests": 1},
                        resp(SAVE))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 3)

    def test_empty_output_without_length_not_recovered(self):
        """finish=stop 的空输出不满足恢复条件，重试。"""
        script = Script(resp(PLAN),
                        {"content": "", "reasoning_content": json.dumps(SAVE, ensure_ascii=False),
                         "finish": "stop", "requests": 1},
                        resp(SAVE))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(script.calls), 3)

    def test_phase_request_cap_is_two(self):
        """plan 阶段最多 2 次实际请求；空输出两次 → 协议失败并带 request_budget 归因。"""
        script = Script({"content": "", "reasoning_content": "", "finish": "stop", "requests": 1},
                        {"content": "", "reasoning_content": "", "finish": "stop", "requests": 1})
        result = self._run(script)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "protocol")
        self.assertEqual(result["failure"]["stage"], "plan")
        self.assertEqual(result["failure"]["reason"], "request_budget")

    def test_stream_fallback_counts_into_phase_budget(self):
        """流式转普通（requests=2）算 2 次；最后 1 个槽位走普通请求，实际 HTTP 不超上限。"""
        script = Script(resp(PLAN),
                        {"content": "", "reasoning_content": "", "finish": "stop", "requests": 2},
                        {"content": "", "reasoning_content": "", "finish": "stop", "requests": 1})
        result = self._run(script)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "protocol")
        self.assertEqual(result["failure"]["stage"], "draw")
        self.assertIn("3 次上限", result["error"])
        # 不变量：draw 实际 HTTP = 2（流式回退）+ 1（最后槽位普通请求）= 3，恰等于上限
        self.assertEqual(len(script.calls), 3, "PLAN + 2 次 draw，无第 4 次 HTTP")
        self.assertIsNotNone(script.calls[1].get("on_progress"), "非最后槽位保持流式进度")
        self.assertIsNone(script.calls[2].get("on_progress"),
                          "最后 1 个槽位必须走普通请求（防止回退突破上限）")

    def test_artifact_failure_is_reported_not_masked(self):
        """产物生成失败：如实失败（产物错误），不算完整成功。"""
        with mock.patch.object(workflow.subprocess, "run",
                               side_effect=_fake_proc_factory(2)):
            result = self._run(Script(resp(PLAN), resp(SAVE)))
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "artifact")


def _fake_proc_factory(code):
    class _P:
        returncode = code
        stdout = ""
        stderr = "make_steps failed"
    return lambda *a, **kw: _P()


class ThinkingTurnTest(IsolatedArtifactsTest):
    """模型回合的思考通道：实时/落盘/截断/半截/零事件。"""

    def _run(self, chat_fn, **kw):
        kw.setdefault("solve_fn", real_solve)
        events = []

        def log(kind, text, meta=None):
            events.append((kind, text, dict(meta or {})))

        result = run_generation(DESC, chat_fn=chat_fn, log=log, **kw)
        return result, events

    @staticmethod
    def _thinking(events):
        return [meta for kind, _, meta in events if kind == "thinking"]

    def test_normal_turn_logs_live_then_one_full_entry(self):
        """正常回合：流式期间发实时事件，结束后落一条完整记录。

        截断由 job_feed 在落盘/下发时统一做（test_job_feed 覆盖），workflow 只负责
        如实把整套推理交出去，不在业务层丢内容。
        """
        long_reasoning = "开头" + "中" * 12000 + "结尾"
        script = Script(resp(PLAN), resp(SAVE))

        def chat(messages, **kw):
            cb = kw.get("on_reasoning")
            if cb and len(script.items) == 2:      # 只在 plan 回合推流
                cb(long_reasoning[:100], 0.4)
                cb(long_reasoning, 5.0)
            return script(messages, **kw)

        result, events = self._run(chat)
        self.assertTrue(result["ok"], result.get("error"))
        thinks = self._thinking(events)
        live = [m for m in thinks if not m.get("done")]
        done = [m for m in thinks if m.get("done")]
        self.assertTrue(live, "流式期间必须有实时事件")
        self.assertFalse(any(m["partial"] for m in live))
        # 第二个回合（draw）由 resp() 给出空推理，按约定零事件；只有 plan 回合落一条
        self.assertEqual(len(done), 1, "有推理的回合各落一条完成记录")
        first = done[0]
        self.assertFalse(first["partial"])
        self.assertEqual(first["text"], long_reasoning, "业务层不得截断推理原文")
        self.assertEqual(live[-1]["text"], long_reasoning, "最后一个实时事件是完整文本")

    def test_empty_reasoning_emits_zero_events(self):
        """服务商不返回推理：一个 thinking 事件都不发，界面完全隐藏。"""
        result, events = self._run(Script(resp(PLAN), resp(SAVE)))
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(self._thinking(events), [])

    def test_cancel_keeps_partial_thinking(self):
        """取消时把已收到的半截推理以 partial=True 落一条。"""
        import threading
        cancel = threading.Event()

        def chat(messages, **kw):
            cb = kw.get("on_reasoning")
            if cb:
                cb("已经想了一半", 1.0)
                cancel.set()            # 下一个回调点抛取消
                cb("已经想了一半", 1.1)
            return resp(PLAN)(messages, **kw)

        result, events = self._run(chat, cancel=cancel)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "cancelled")
        done = [m for m in self._thinking(events) if m.get("done")]
        self.assertTrue(done, "取消时必须保留已收到的思考")
        self.assertTrue(done[-1]["partial"])
        self.assertIn("已经想了一半", done[-1]["text"])

    def test_stream_broken_keeps_partial_thinking_and_error(self):
        """流式中断：思考照常落半截，并保留 stream_broken 错误条目。"""
        import legogod.llm as llm_mod
        script = Script(resp(SAVE))

        def chat(messages, **kw):
            cb = kw.get("on_reasoning")
            if cb:
                cb("断流前的推理", 2.0)
            if len(script.items) == 1:      # 第一次调用就中断
                raise llm_mod.LLMStreamBroken("流式已收到部分数据后中断")
            return script(messages, **kw)

        result, events = self._run(chat)
        self.assertFalse(result["ok"])
        done = [m for m in self._thinking(events) if m.get("done")]
        self.assertTrue(done and done[-1]["partial"])
        self.assertIn("断流前的推理", done[-1]["text"])
        self.assertTrue(any(k == "error" and "流式输出中断" in t for k, t, _ in events),
                        "现有 stream_broken 错误条目不得丢")

    def test_last_slot_non_stream_still_logs_full_thinking(self):
        """最后一个非流式槽位：没有实时回调，返回后仍落一条完整思考。"""
        empty = {"content": "", "reasoning_content": "", "finish": "stop", "requests": 1}
        script = Script(empty, resp(PLAN), resp(SAVE))

        def chat(messages, **kw):
            out = script(messages, **kw)
            # 第二次 plan 调用（phase_requests 打满 → 最后槽位）走普通请求，带回整段推理
            if out is not None and kw.get("on_reasoning") is None and out.get("content"):
                out["reasoning_content"] = "非流式整段推理"
            return out

        result, events = self._run(chat)
        self.assertTrue(result["ok"], result.get("error"))
        done = [m for m in self._thinking(events) if m.get("done")]
        self.assertTrue(done, "非流式槽位也要落思考")
        self.assertIn("非流式整段推理", done[-1]["text"])
        self.assertFalse(done[-1]["partial"])


class FidelityChainTest(IsolatedArtifactsTest):
    """高保真：评审在部位检查后、预检前；视觉修订走 revise_design；不可用如实标记。"""

    def setUp(self):
        super().setUp()  # 先启动产物目录隔离
        self.plan = json.loads(json.dumps(PLAN, ensure_ascii=False))
        self.plan["args"]["parts"] = self.plan["args"]["parts"][:1]  # 只留塔身
        self.save = {"thought": "", "action": "save_design", "args": {
            "name": "测试塔", "slug": "chain-fidelity", "notes": "", "features": ["塔身方形"],
            "defaultPart": "tower", "partPatches": [],
            "layers": [
                {"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"],
                 "colorPatches": [{"color": "黑色", "cells": [[1, 1]]}]},
                {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]},
            ],
        }}

    def _review(self, overall):
        def review_fn(desc, model, solution=None, **kw):
            return {"ok": True, "requests": 1, "sheet": "sheet.png",
                    "parsed": {"scores": {"overall": overall},
                               "worst_parts": ["顶面配色"], "suggestions": ["把 (1,1) 改色"]}}
        return review_fn

    def test_visual_pass_then_solve(self):
        review = self._review(8)
        script = Script(resp(self.plan), resp(self.save))
        result = run_generation(DESC, mode="fidelity", chat_fn=script, review_fn=review,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(result["review_unavailable"])
        self.assertFalse(result["review_failed"])
        self.assertEqual(len(script.calls), 2, "评审由程序发起，不消耗对话轮次")

    def test_visual_revision_then_pass(self):
        states = iter([5, 8])

        def review_fn(desc, model, solution=None, **kw):
            return {"ok": True, "requests": 1, "sheet": "sheet.png",
                    "parsed": {"scores": {"overall": next(states)},
                               "worst_parts": ["顶面配色"], "suggestions": ["把 (3,3) 改色"]}}

        color_patch = {"thought": "", "action": "revise_design", "args": {
            "baseRevision": "r001",
            "edits": [{"x": 3, "y": 1, "z": 3, "voxel": "#", "color": "米白"}]}}
        script = Script(resp(self.plan), resp(self.save), resp(color_patch))
        result = run_generation(DESC, mode="fidelity", chat_fn=script, review_fn=review_fn,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_visual"], 1)
        self.assertEqual(result["revision"], 2)

    def test_review_unavailable_marked_and_still_solves(self):
        def review_fn(desc, model, solution=None, **kw):
            return {"ok": False, "requests": 1, "parsed": {}, "raw": ""}
        script = Script(resp(self.plan), resp(self.save))
        result = run_generation(DESC, mode="fidelity", chat_fn=script, review_fn=review_fn,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["review_unavailable"])
        self.assertFalse(result["review_failed"])

    def test_review_failed_after_two_visual_revisions(self):
        states = iter([4, 5, 6])

        def review_fn(desc, model, solution=None, **kw):
            return {"ok": True, "requests": 1, "sheet": "sheet.png",
                    "parsed": {"scores": {"overall": next(states)},
                               "worst_parts": ["顶面配色"], "suggestions": ["把 (3,3) 改色"]}}

        def no_op(rev):
            return {"thought": "", "action": "revise_design", "args": {
                "baseRevision": rev,
                "edits": [{"x": 3, "y": 1, "z": 3, "voxel": "#", "color": "米白"}]}}

        script = Script(resp(self.plan), resp(self.save), resp(no_op("r001")), resp(no_op("r002")))
        result = run_generation(DESC, mode="fidelity", chat_fn=script, review_fn=review_fn,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["review_failed"])
        self.assertFalse(result["review_unavailable"])
        self.assertEqual(result["counts"]["revise_visual"], 2)


if __name__ == "__main__":
    unittest.main()
