# -*- coding: utf-8 -*-
"""固定主链三维算子轨道机制测试。

不调用真实模型：chat_fn / review_fn / solve_fn / clock 全部注入。
覆盖：save_design3 主链闭环（编译→部位自动绑定→门禁→预检→求解→产物）、
门禁不过触发有界造型重绘、revise_ops 算子级修订（核心保护）、
算子协议失败时降级二维画稿（save_design 兼容路径）。
"""
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 测试侧共享装置：test/ 目录也加入导入路径（test 是 stdlib 包名，不能写成 from test.xxx）
sys.path.insert(0, os.path.join(ROOT, "test"))

from _helpers import IsolatedArtifactsTest, Script, real_solve, resp  # noqa: E402
from legogod.workflow import run_generation  # noqa: E402

DESC = "一座测试高塔，塔身完整不能拆"

PLAN3 = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身方形"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
    "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
    "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
}}

OPS = [
    {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "tower", "color": "浅灰"},
]

SAVE3 = {"thought": "", "action": "save_design3", "args": {
    "name": "测试塔", "slug": "chain-ops-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower", "ops": OPS,
}}

# 整模单部件（塔身）通过门禁①（空气面 > 与其它部位的贴合面）；
# 「旗幡」贴花（嵌在塔身外表面内的 1x1x2 格）被门禁判为伪部位 → 触发重绘。
PLAN_BANNER = {"thought": "", "action": "plan_design", "args": {
    "features": ["塔身与旗幡"], "structure": "实心塔", "grid": {"w": 4, "d": 6},
    "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
    "parts": [
        {"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"},
        {"id": "banner", "name": "旗幡", "required": True, "source": "旗幡"},
    ],
}}

SAVE3_DECAL = {"thought": "", "action": "save_design3", "args": {
    "name": "测试塔", "slug": "chain-ops-tower", "notes": "", "features": ["塔身与旗幡"],
    "defaultPart": "tower",
    "ops": [
        {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "tower"},
        # 贴花：嵌在塔身外表面（z=3 面层内）的 1x1x2 格，唯一空气面朝外
        {"op": "box", "x": 2, "y": 0, "z": 3, "w": 1, "d": 1, "h": 2, "part": "banner", "color": "红色"},
    ],
}}

SAVE3_PROTRUDING = {"thought": "", "action": "save_design3", "args": {
    "name": "测试塔", "slug": "chain-ops-tower", "notes": "", "features": ["塔身与旗幡"],
    "defaultPart": "tower",
    "ops": [
        {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "tower"},
        # 真实悬伸旗板：探出塔身外 2 格（z=4..5），空气面远超贴合面
        {"op": "box", "x": 2, "y": 1, "z": 4, "w": 1, "d": 2, "h": 1, "part": "banner", "color": "红色"},
    ],
}}

SAVE2D = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "chain-ascii-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower", "partPatches": [],
    "layers": [{"module": "底", "color": "浅灰", "rows": ["####", "####", "####", "####"]},
               {"module": "顶", "color": "白色", "rows": ["####", "####", "####", "####"]}],
}}


class OpsChainTest(IsolatedArtifactsTest):
    def _run(self, script, desc=None, **kw):
        kw.setdefault("solve_fn", real_solve)
        return run_generation(desc or DESC, chat_fn=script, **kw)

    def test_save3_happy_path(self):
        """save_design3 → 编译/自动绑定/门禁/求解/产物 全链闭环（不再手数坐标）。"""
        script = Script(resp(PLAN3), resp(SAVE3))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["track"], "ops")
        self.assertEqual(result["revision"], 1)
        self.assertEqual(len(script.calls), 2)
        with open(self._art(result["model_path"]), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["schemaVersion"], 2)
        self.assertEqual(record["track"], "ops")
        self.assertTrue(record["ops"], "算子列表随模型存档（算子级修订依据）")
        self.assertEqual(record["parts"][0]["role"], "solid")
        with open(self._art(result["solution_path"]), encoding="utf-8") as f:
            sol = json.load(f)
        self.assertEqual(sol["schemaVersion"], 2)

    def test_single_part_model_passes_gate(self):
        """整模单部件：贴合面按「其它部位」计，独立实体不被门禁误杀。"""
        script = Script(resp(PLAN3), resp(SAVE3))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(result["gate_failed"])

    def test_gate_failure_triggers_bounded_redraw_then_passes(self):
        """门禁拦截贴花伪部位 → 造型重绘为真实悬伸结构 → 通过（错误落盘）。"""
        script = Script(resp(PLAN_BANNER), resp(SAVE3_DECAL), resp(SAVE3_PROTRUDING))
        result = self._run(script, desc="一座测试高塔，塔身完整不能拆，挂着旗幡")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(result["gate_failed"])
        kinds = [f["kind"] for f in result["failures"]]
        self.assertIn("gate", kinds)

    def test_gate_exhausted_degrades_with_record(self):
        """门禁重绘用尽、draw 预算耗尽仍不过：带门禁记录降级继续求解（gate_failed=True）。"""
        script = Script(resp(PLAN_BANNER), resp(SAVE3_DECAL), resp(SAVE3_DECAL), resp(SAVE3_DECAL))
        result = self._run(script, desc="一座测试高塔，塔身完整不能拆，挂着旗幡")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["gate_failed"])
        self.assertTrue(result["gate_errors"])

    def test_fallback_to_ascii_when_ops_protocol_fails(self):
        """算子协议连续失败 → 降级为 save_design 二维画稿（兼容回退路径）。"""
        bad = {"thought": "", "action": "save_design3", "args": {"ops": [{"op": "sphere"}]}}
        script = Script(resp(PLAN3), resp(bad), resp(SAVE2D))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["track"], "ascii")

    def test_fidelity_visual_revision_via_cell_patch_keeps_ops_layers(self):
        """高保真视觉修订走逐格补丁（revise_design）时不得 KeyError 'y'。

        回归（2026-11-03 真实 E2E 冒烟暴露）：ops 轨道的 chain.layers 是主链层的
        紧凑副本（不含 y 键），视觉修订分支曾按 L["y"] 建映射导致内部异常；
        edits 的 y 是层序号（dc.apply_edits 同样按序号索引），颜色编辑必须先按序号
        找到目标层再决定是否保留 color。
        """
        calls = {"n": 0}

        def review_fn(desc, model, solution=None, **kw):
            calls["n"] += 1
            overall = 5 if calls["n"] == 1 else 8
            return {"ok": True, "requests": 1, "sheet": "sheet.png",
                    "parsed": {"scores": {"overall": overall}, "worst_parts": ["塔身"],
                               "suggestions": ["顶层换白色"]}}

        patch = {"thought": "", "action": "revise_design", "args": {
            "baseRevision": "r001",
            "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "白色"}]}}
        script = Script(resp(PLAN3), resp(SAVE3), resp(patch))
        result = self._run(script, mode="fidelity", review_fn=review_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["revision"], 2, "视觉修订应接受为 r002")
        self.assertEqual(calls["n"], 2)
        self.assertNotEqual(result.get("failure", {}).get("kind"), "internal")

    def test_revise_ops_keeps_frozen_core(self):
        """预检失败 → revise_ops 算子级修订（断连补桥）→ 求解成功。"""
        broken = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "chain-ops-tower", "notes": "", "features": ["双柱"],
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
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class1"], 1)
        self.assertEqual(result["revision"], 2)

    @mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"})
    def test_revise_ops_cannot_delete_frozen_core(self):
        """核心冻结后的 revise_ops 若丢失核心体素 → 拒收并按协议重试，不删核心的新稿通过。

        2026-11-03 D.2 后默认顺序为 class1_front（视觉前只读预检/class1 修订）；
        本用例验证「冻结核心后的算子修订保护」，脚本时序按 legacy default 顺序编排，
        因此显式固定 default（顺序语义由 test_workflow_order.py 覆盖）。
        """
        broken = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "chain-ops-core", "notes": "", "features": ["双柱"],
            "defaultPart": "tower",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
            ],
        }}
        # 恶意补丁：试图把原主体完全移走（删光冻结核心）
        delete_core = {"thought": "", "action": "revise_ops", "args": {
            "baseRevision": "r001",
            "ops": [
                {"op": "box", "x": 2, "y": 0, "z": 2, "w": 2, "d": 2, "h": 2, "part": "tower"},
            ],
        }}
        # 合法补丁：保留原核心并在中间补桥
        valid_fix = {"thought": "", "action": "revise_ops", "args": {
            "baseRevision": "r001",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 1, "y": 0, "z": 0, "w": 2, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
            ],
        }}
        script = Script(resp(PLAN3), resp(broken), resp(delete_core), resp(valid_fix))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class1"], 1)
        self.assertTrue(any("核心" in e["summary"] for e in result["protocol_errors"]))

    def test_revise_ops_separates_geo_and_color_caps(self):
        """算子修订拆分几何(≤8)与纯换色(≤16)两档：5 个算子纯换色不触发几何超限。"""
        ops6 = [
            {"op": "box", "x": i, "y": 0, "z": 0, "w": 1, "d": 2, "h": 1,
             "part": "tower", "color": "浅灰"}
            for i in range(4)
        ] + [
            {"op": "box", "x": 0, "y": 1, "z": 0, "w": 2, "d": 2, "h": 1,
             "part": "tower", "color": "浅灰"},
            {"op": "box", "x": 3, "y": 1, "z": 2, "w": 1, "d": 2, "h": 1,
             "part": "tower", "color": "浅灰"},  # 制造悬空触发一次 class1 修订
        ]
        plan6 = {"thought": "", "action": "plan_design", "args": {
            "features": ["塔"], "structure": "塔", "grid": {"w": 4, "d": 4},
            "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
            "parts": [{"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"}],
        }}
        save6 = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "chain-color-cap", "notes": "", "features": ["塔"],
            "defaultPart": "tower", "ops": ops6,
        }}
        # 5 个算子纯换色 + 仅 1 个算子调整几何位置（geo=1 ≤ 8, color=5 ≤ 16）
        revised_ops = [
            {**ops6[i], "color": "深灰"} for i in range(5)
        ] + [
            {"op": "box", "x": 2, "y": 1, "z": 0, "w": 2, "d": 2, "h": 1,
             "part": "tower", "color": "深灰"},
        ]
        rev = {"thought": "", "action": "revise_ops",
               "args": {"baseRevision": "r001", "ops": revised_ops}}
        script = Script(resp(plan6), resp(save6), resp(rev))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))

    def test_protocol_errors_persisted_on_failure(self):
        """阶段请求耗尽失败时，run_record.protocolErrors 必须落盘记录具体打回原因。"""
        bad1 = {"thought": "", "action": "wrong_tool", "args": {}}
        bad2 = {"thought": "", "action": "save_design3", "args": {"ops": []}}
        script = Script(resp(PLAN3), resp(bad1), resp(bad2))
        result = self._run(script)
        self.assertFalse(result["ok"])
        perrs = result["run_record"]["protocolErrors"]
        self.assertEqual(len(perrs), 2)
        self.assertEqual(perrs[0]["kind"], "wrong_action")
        self.assertEqual(perrs[1]["kind"], "schema_error")

    def test_revise_allows_third_call_after_two_protocol_rejects(self):
        """结构修订前两次协议拒绝不结束任务，第三次 revise_ops 可被接受。"""
        broken = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "chain-ops-retry", "notes": "", "features": ["双柱"],
            "defaultPart": "tower",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
            ],
        }}
        bad = {"thought": "", "action": "save_design3", "args": {}}
        valid_fix = {"thought": "", "action": "revise_ops", "args": {
            "baseRevision": "r001",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 1, "y": 0, "z": 0, "w": 2, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
            ],
        }}
        script = Script(resp(PLAN3), resp(broken), resp(bad), resp(bad), resp(valid_fix))
        result = self._run(script)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class1"], 1)
        self.assertEqual(len(script.calls), 5)

    def test_revise_ends_after_third_protocol_reject(self):
        """同一次修订第三次仍是协议拒绝：不再改稿。当前双柱稿预检不连通则失败，不把原因写成请求打满。"""
        broken = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "chain-ops-retry-fail", "notes": "", "features": ["双柱"],
            "defaultPart": "tower",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
                {"op": "box", "x": 3, "y": 0, "z": 0, "w": 1, "d": 2, "h": 2, "part": "tower"},
            ],
        }}
        bad = {"thought": "", "action": "save_design3", "args": {}}
        script = Script(resp(PLAN3), resp(broken), resp(bad), resp(bad), resp(bad))
        result = self._run(script)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure"]["kind"], "connectivity")
        self.assertIn("互不相连", result["error"])
        self.assertNotIn("3 次上限", result["error"])
        self.assertTrue(result["revisionIncomplete"])
        self.assertEqual(result["revisionIncompleteReason"], "结构修订请求打满")
        self.assertEqual(result["counts"]["revise_class1"], 0)
        self.assertEqual(len(script.calls), 5)


class OpsRoleOverrideTest(IsolatedArtifactsTest):
    def test_op_level_role_refines_plan_decl(self):
        """算子带 role=surface 修正规划层默认角色：单格眼睛作为表面涂装部位通过门禁。"""
        plan = {"thought": "", "action": "plan_design", "args": {
            "features": ["塔身与眼睛"], "structure": "实心塔", "grid": {"w": 4, "d": 4},
            "layers": 2, "estimatedVoxels": 60, "targetBlocks": 20, "estimatedParts": 20,
            "parts": [
                {"id": "tower", "name": "塔身", "required": True, "source": "塔身完整"},
                {"id": "eye", "name": "眼睛", "required": True, "source": "眼睛"},
            ],
        }}
        save = {"thought": "", "action": "save_design3", "args": {
            "name": "测试塔", "slug": "chain-ops-role", "notes": "", "features": ["塔身与眼睛"],
            "defaultPart": "tower",
            "ops": [
                {"op": "box", "x": 0, "y": 0, "z": 0, "w": 4, "d": 4, "h": 2, "part": "tower",
                 "color": "浅灰"},
                # 单格眼睛嵌在墙面（z=3 面层）：几何上是单格，按表面涂装角色表达
                {"op": "box", "x": 2, "y": 1, "z": 3, "w": 1, "d": 1, "h": 1, "part": "eye",
                 "color": "黑色", "role": "surface"},
            ],
        }}
        script = Script(resp(plan), resp(save))
        result = run_generation("一座测试高塔，塔身完整不能拆，有眼睛", chat_fn=script,
                                solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(result["gate_failed"])
        self.assertTrue(result["track"] == "ops")


if __name__ == "__main__":
    unittest.main()
