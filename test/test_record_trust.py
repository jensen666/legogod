# -*- coding: utf-8 -*-
"""A.2/A.3 运行记录可信度与确定性 Bug 回归。

覆盖：
1) 评审哈希：最终稿与评审稿一致 → fidelity_success；终稿被修订改过 → 落盘前补一次评审，
   成功则哈希对齐仍为 fidelity_success，补评审不可用则 review_stale、outcome 降级；
2) 评审不可用/无哈希 → reviewStale=False + reviewHashMissing=True（不伪造哈希）；
3) 版本只增不减：视觉回滚后再次版本化分配新版本号，旧模型文件内容不变，
   versionOverwriteCount==0，revisionChain 记录 parentRevision/rolledBackTo；
4) class2 失败透传全量 window_cells：>64 格窗口完整进入修订上下文并展示真实总数；
5) run 记录 finalGateReplay / draftRanking / gateDegradedBaseline / quota / scaleMetrics /
   structuralCandidates / chainOrder 字段形态（含缺数据 null + 原因）。
不调用真实模型：chat_fn / review_fn / solve_fn / clock 全部注入。
"""
import json
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

from _helpers import IsolatedArtifactsTest, Script, real_solve, resp  # noqa: E402
from legogod import fallback as fb  # noqa: E402
from legogod import revision_policy as rp  # noqa: E402
from legogod import tiler, workflow  # noqa: E402
from legogod import workflow_artifacts as wa  # noqa: E402
from legogod import workflow_phases as test_wph  # noqa: E402
from legogod.fallback import (OUTCOME_FIDELITY_DEGRADED, OUTCOME_FIDELITY_SUCCESS,  # noqa: E402
                              run_with_fallback)
from legogod.workflow import run_generation  # noqa: E402
from legogod.workflow_artifacts import build_run_record, model_hash  # noqa: E402

DESC = "一座测试高塔，塔身完整不能拆，旁边有小旗杆不能删"

# 目标约 48 块、预估 60 体素/24 块：与主链 4×4×4 容量 64 一致（plan_scale 一致性检查）
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

SAVE = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "trust-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [{"module": "底", "color": "浅灰", "rows": list(SOLID_ROWS)},
               {"module": "中一", "color": "浅灰", "rows": list(SOLID_ROWS)},
               {"module": "中二", "color": "白色", "rows": list(SOLID_ROWS)},
               {"module": "顶", "color": "白色", "rows": list(SOLID_ROWS)}],
}}
SAVE_FID = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "trust-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower",
    "partPatches": [{"id": "flag", "cells": [[3, 0, 3]]}],
    "layers": [
        {"module": "底", "color": "浅灰", "rows": list(SOLID_ROWS),
         "colorPatches": [{"color": "黑色", "cells": [[1, 1]]}]},
        {"module": "中一", "color": "浅灰", "rows": list(SOLID_ROWS)},
        {"module": "中二", "color": "白色", "rows": list(SOLID_ROWS)},
        {"module": "顶", "color": "白色", "rows": list(SOLID_ROWS)},
    ],
}}
SAVE_DISCONNECTED_FID = {"thought": "", "action": "save_design", "args": {
    "name": "测试塔", "slug": "trust-tower", "notes": "", "features": ["塔身方形"],
    "defaultPart": "tower", "partPatches": [],
    "layers": [
        {"module": "底", "color": "浅灰", "rows": list(DISCONNECTED_ROWS),
         "colorPatches": [{"color": "黑色", "cells": [[0, 0]]}]},
        {"module": "中一", "color": "浅灰", "rows": list(DISCONNECTED_ROWS)},
        {"module": "中二", "color": "白色", "rows": list(DISCONNECTED_ROWS)},
        {"module": "顶", "color": "白色", "rows": list(DISCONNECTED_ROWS)},
    ],
}}
BRIDGE_EDITS = [{"x": 2, "y": y, "z": z, "voxel": "#", "color": "浅灰"}
                for y in range(4) for z in range(4)]
BRIDGE_PATCH = {"thought": "", "action": "revise_design",
                "args": {"baseRevision": "r001", "edits": BRIDGE_EDITS}}


def review_with_hash(overall=8):
    """模拟 task-3 契约：评审结果携带评审时模型哈希（do_review_once 写入 review_state）。"""
    def review_fn(desc, model, solution=None, **kw):
        return {"ok": True, "requests": 1, "sheet": "sheet.png",
                "modelHash": model_hash(model),
                "parsed": {"scores": {"overall": overall}, "worst_parts": ["塔身"],
                           "suggestions": [], "missing_features": [], "keep": []}}
    return review_fn


def review_unavailable(desc, model, solution=None, **kw):
    return {"ok": False, "requests": 1, "parsed": {}, "raw": ""}


class ReviewHashTrustTest(IsolatedArtifactsTest):
    # 2026-11-03 D.2 后默认顺序为 class1_front；本类验证「评审哈希可信度」，
    # 需要视觉先于结构修订的脚本时序，因此显式固定 legacy default 顺序（顺序语义由
    # test_workflow_order.py 单独覆盖）。
    @mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"})
    def test_matching_review_hash_keeps_fidelity_success(self):
        """评审哈希==最终哈希：仍是高保真成功，记录字段齐全。"""
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=Script(resp(PLAN), resp(SAVE_FID)),
                                   review_fn=review_with_hash(8), solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_SUCCESS)
        self.assertFalse(result["review_stale"])
        self.assertEqual(result["reviewedModelHash"], result["finalModelHash"])
        self.assertFalse(result["reviewHashMissing"])
        record = result["run_record"]
        self.assertFalse(record["reviewStale"])
        self.assertEqual(record["reviewedModelHash"], record["finalModelHash"])
        self.assertEqual(record["chainOrder"], "default")
        self.assertEqual(record["versionOverwriteCount"], 0)
        self.assertEqual(record["quotaMode"], "fixed")
        self.assertEqual(set(record["quota"]), {"class1", "class2"})
        for cls in ("class1", "class2"):
            self.assertEqual(record["quota"][cls],
                             {"limit": 2, "accepted": 0, "requests": 0})
        self.assertEqual(record["structuralCandidates"],
                         {"attempted": 0, "accepted": 0, "rejected": 0, "results": []})
        # 最终门禁重放：真实 gate_replay 已就绪，必须是结构化结果而不是过程标记
        replay = record["finalGateReplay"]
        self.assertIsNotNone(replay, record.get("finalGateReplayReason"))
        self.assertIsInstance(replay["ok"], bool)
        self.assertIsInstance(replay["affectedPartCount"], int)
        self.assertIsInstance(replay["errorCellCount"], int)
        # 规模指标：targetBlocks 来自规划，bricks/actualParts 来自求解产物
        metrics = record["scaleMetrics"]
        self.assertIsNotNone(metrics, record.get("scaleMetricsReason"))
        self.assertEqual(metrics["targetBlocks"], 48)
        self.assertEqual(metrics["bricks"], result["pieces"])
        self.assertEqual(metrics["actualParts"], result["pieces"])
        self.assertTrue(record["revisionChain"])
        self.assertEqual(record["revisionChain"][0]["revision"], 1)
        self.assertIsNone(record["revisionChain"][0]["parentRevision"])

    @mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"})
    def test_changed_final_hash_refreshes_review_before_freeze(self):
        """评审后结构修订改变了模型：落盘前补评审刷新哈希，不再 review_stale（2026-11-07）。"""
        calls = []

        def counting_review(desc, model, solution=None, **kw):
            calls.append(model_hash(model))
            return review_with_hash(8)(desc, model, solution, **kw)

        result = run_with_fallback(
            DESC, mode="fidelity",
            chat_fn=Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED_FID), resp(BRIDGE_PATCH)),
            review_fn=counting_review, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["counts"]["revise_class1"], 1)
        # 终稿与评审稿不同触发了补评审：评审调用 2 次（视觉阶段 1 次 + 终稿刷新 1 次）
        self.assertEqual(len(calls), 2, calls)
        self.assertNotEqual(calls[0], calls[1], "补评审针对的是修订后的终稿")
        self.assertFalse(result["review_stale"], "补评审后终稿哈希与评审哈希一致")
        self.assertEqual(result["reviewedModelHash"], result["finalModelHash"])
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_SUCCESS)
        record = result["run_record"]
        self.assertFalse(record["reviewStale"])
        self.assertEqual(record["reviewedModelHash"], record["finalModelHash"])
        self.assertFalse(record["reviewHashMissing"])
        # 版本只增不减：结构修订产生了 r002，旧 r001 文件仍在
        self.assertEqual(record["revision"], 2)
        self.assertEqual([e["revision"] for e in record["revisionChain"]], [1, 2])
        self.assertEqual(record["versionOverwriteCount"], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, record["artifacts"]["model_r001"])))
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, record["artifacts"]["model_r002"])))

    @mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"})
    def test_refresh_review_below_pass_degrades(self):
        """终稿补评审低于验收线：如实降级，不冒充高保真成功（2026-11-14 双模式 E2E 发现）。"""
        flips = {"n": 0}

        def first_pass_later_low(desc, model, solution=None, **kw):
            flips["n"] += 1
            return review_with_hash(8 if flips["n"] == 1 else 5)(desc, model, solution, **kw)

        result = run_with_fallback(
            DESC, mode="fidelity",
            chat_fn=Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED_FID), resp(BRIDGE_PATCH)),
            review_fn=first_pass_later_low, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(flips["n"], 2, "视觉阶段 1 次 + 终稿补评审 1 次")
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        self.assertEqual(result["review_flag"], "review_failed")
        self.assertIn("视觉评审修订后仍未达标", result["degraded_reason"])
        self.assertEqual(result["review"]["scores"]["overall"], 5)
        # 补评审确实覆盖了终稿：哈希一致、不算 review_stale，但分数不达标必须降级
        self.assertFalse(result["review_stale"])
        self.assertEqual(result["reviewedModelHash"], result["finalModelHash"])
        record = result["run_record"]
        self.assertFalse(record["reviewStale"])
        self.assertEqual(record["reviewFlag"], "review_failed")

    @mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"})
    def test_refresh_review_without_scores_keeps_previous_state(self):
        """终稿补评审无有效分数：恢复原评审状态，不得用空结果冒充达标评审。"""
        flips = {"n": 0}

        def first_pass_later_empty(desc, model, solution=None, **kw):
            flips["n"] += 1
            if flips["n"] == 1:
                return review_with_hash(8)(desc, model, solution, **kw)
            return {"ok": True, "requests": 1, "parsed": {}, "raw": ""}

        result = run_with_fallback(
            DESC, mode="fidelity",
            chat_fn=Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED_FID), resp(BRIDGE_PATCH)),
            review_fn=first_pass_later_empty, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(flips["n"], 2)
        self.assertTrue(result["review_stale"], "无分数的补评审不能刷新评审哈希")
        self.assertEqual(result["review_flag"], "review_stale")
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)

    @mock.patch.dict(os.environ, {"LEGOGOD_CHAIN_ORDER": "default"})
    def test_refresh_review_failure_keeps_stale_honestly(self):
        """终稿补评审不可用：恢复原评审状态，review_stale 如实保留并降级。"""
        flips = {"n": 0}

        def failing_later_review(desc, model, solution=None, **kw):
            flips["n"] += 1
            if flips["n"] == 1:
                return review_with_hash(8)(desc, model, solution, **kw)
            return {"ok": False, "requests": 1, "parsed": {}, "raw": ""}

        result = run_with_fallback(
            DESC, mode="fidelity",
            chat_fn=Script(resp(PLAN_ONE), resp(SAVE_DISCONNECTED_FID), resp(BRIDGE_PATCH)),
            review_fn=failing_later_review, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(flips["n"], 2)
        self.assertTrue(result["review_stale"], "补评审失败必须如实保留 review_stale")
        self.assertEqual(result["review_flag"], "review_stale")
        self.assertNotEqual(result["reviewedModelHash"], result["finalModelHash"])
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        self.assertIn("过期", result["degraded_reason"])
        record = result["run_record"]
        self.assertTrue(record["reviewStale"])
        self.assertEqual(record["reviewFlag"], "review_stale")

    def test_review_unavailable_records_missing_hash_not_stale(self):
        """评审不可用：reviewStale=False + reviewHashMissing=True，如实降级。"""
        result = run_with_fallback(DESC, mode="fidelity", chat_fn=Script(resp(PLAN), resp(SAVE_FID)),
                                   review_fn=review_unavailable, solve_fn=real_solve)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(result["review_stale"])
        self.assertTrue(result["reviewHashMissing"])
        self.assertEqual(result["outcome"], OUTCOME_FIDELITY_DEGRADED)
        record = result["run_record"]
        self.assertFalse(record["reviewStale"])
        self.assertTrue(record["reviewHashMissing"])
        self.assertIsNone(record["reviewedModelHash"])


class _FakeVersionChain:
    """版本化辅助测试用的最小链：只提供 version_design/restore_design 读取的字段。"""

    def __init__(self):
        self.run_id = "revtest"
        self.track = "ops"
        self.ops = None
        self.artifacts = {}
        self.model_hashes = {}
        self.revision_chain = []
        self.version_overwrite_count = 0
        self.revision = 0
        self.max_revision = 0
        self.rollback_pending = None
        self.reviewed_model_hash = None
        self.emit = lambda *a, **k: None
        self.model = {"name": "塔", "slug": "t", "grid": {"w": 2, "d": 2},
                      "layers": [{"y": 0, "rows": ["##", "##"]}], "totalVoxels": 4}

    def _record_parts(self):
        raise AssertionError("本测试不应重建部位")


class _AutoVersionChain(_FakeVersionChain):
    """带回滚落版能力的假链：_version_design 直接调用真实 version_design。"""

    def __init__(self):
        super().__init__()
        self.tmp_dir = None
        self.assignment = {}
        self.parts_norm = None
        self.layers = [{"module": "m", "color": "浅灰", "rows": ["##", "##"]}]
        self.default_part = "tower"
        self.design_meta = {"name": "塔", "slug": "t"}
        self.review_state = {"ok": True, "scores": {"overall": 6}}

    def _record_parts(self):
        pass

    def _version_design(self, note="", cause=None):
        return wa.version_design(self, self.tmp_dir, note=note, cause=cause)


class VersionChainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-ver-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _path(self, rev_id):
        return os.path.join(self.tmp, f"model_t_{rev_id}_revtest.json")

    def test_rollback_then_version_allocates_new_revision_without_overwrite(self):
        """回滚后再版本化：新版本号递增、旧文件内容不变、versionOverwriteCount==0。"""
        chain = _FakeVersionChain()
        self.assertEqual(wa.version_design(chain, self.tmp, note="初始"), "r001")
        with open(self._path("r001"), "rb") as f:
            original_bytes = f.read()
        chain.model = {**chain.model, "totalVoxels": 8}   # 视觉修订后的稿
        self.assertEqual(wa.version_design(chain, self.tmp, note="视觉修订"), "r002")
        # 模拟视觉回滚到 r001：revision 倒退但 max_revision 保留
        chain.model = {"name": "塔", "slug": "t", "grid": {"w": 2, "d": 2},
                       "layers": [{"y": 0, "rows": ["##", "##"]}], "totalVoxels": 4}
        chain.revision = 1
        chain.rollback_pending = {"rolledBackTo": 1, "parentRevision": 1,
                                  "cause": "visual_rollback"}
        self.assertEqual(wa.version_design(chain, self.tmp, note="class2 修订"), "r003")
        self.assertEqual(chain.revision, 3)
        self.assertEqual(chain.max_revision, 3)
        self.assertEqual(chain.version_overwrite_count, 0)
        self.assertEqual([e["revision"] for e in chain.revision_chain], [1, 2, 3])
        entry = chain.revision_chain[-1]
        self.assertEqual(entry["parentRevision"], 1)
        self.assertEqual(entry["rolledBackTo"], 1)
        self.assertEqual(entry["cause"], "visual_rollback")
        # 旧版本模型文件内容没有被覆盖/改写
        with open(self._path("r001"), "rb") as f:
            self.assertEqual(f.read(), original_bytes)
        self.assertTrue(os.path.isfile(self._path("r002")))
        self.assertTrue(os.path.isfile(self._path("r003")))
        # 新版本记录的是回滚恢复的旧稿内容（revision 字段为新号）
        with open(self._path("r003"), encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored["revision"], "r003")
        self.assertEqual(restored["totalVoxels"], 4)

    def test_restore_design_keeps_reviewed_hash_and_marks_rollback(self):
        """restore_design 恢复评审哈希，并记录 rolledBackTo；下次版本化递增。"""
        chain = _FakeVersionChain()
        chain.revision = 2
        chain.max_revision = 2
        chain.parts_norm = None
        chain.assignment = {}
        chain.layers = [{"module": "底", "color": "浅灰", "rows": ["##", "##"]}]
        chain.default_part = "tower"
        chain.design_meta = {"name": "塔", "slug": "t"}
        chain.review_state = {"ok": True, "scores": {"overall": 6}}
        snap = rp.capture_design(chain, 6, {"ok": True, "scores": {"overall": 6},
                                            "modelHash": "HASH_REVIEWED"})
        self.assertEqual(snap["reviewed_hash"], "HASH_REVIEWED")
        self.assertEqual(chain.reviewed_model_hash, "HASH_REVIEWED")
        chain.model = {**chain.model, "totalVoxels": 99}   # 后续被修订改变
        rp.restore_design(chain, snap)
        self.assertEqual(chain.model["totalVoxels"], 4)
        self.assertEqual(chain.reviewed_model_hash, "HASH_REVIEWED")
        self.assertEqual(chain.revision, 2)
        self.assertEqual(chain.rollback_pending["rolledBackTo"], 2)
        self.assertEqual(wa.version_design(chain, self.tmp, note="回滚后再次版本化"), "r003")
        self.assertEqual(chain.revision_chain[-1]["rolledBackTo"], 2)
        self.assertEqual(chain.version_overwrite_count, 0)


class RollbackVersioningTest(unittest.TestCase):
    """2026-11-03 复核：视觉回滚后最终稿必须落新单调 revision（r001..r005 → r006）。

    旧实现把 chain.revision 拨回快照版本（最终 r003 而废弃稿 r005 仍在 artifacts 里），
    最终产物读取若不按 record.revision 取就会拿到废弃补丁稿。这里验证回滚本身就不再倒退：
      - 回滚恢复内容后自动落新版本 r006，parentRevision=5、rolledBackTo=1、cause=visual_rollback；
      - 旧模型文件 r001..r005 内容不变（不覆盖）；
      - 最终版本记录的是回滚恢复的旧稿内容，版本号单调递增。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-rollback-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _path(self, rev_id):
        return os.path.join(self.tmp, f"model_t_{rev_id}_revtest.json")

    def test_restore_design_lands_new_monotonic_revision_and_keeps_old_files(self):
        chain = _AutoVersionChain()
        chain.tmp_dir = self.tmp
        self.assertEqual(wa.version_design(chain, self.tmp, note="初始"), "r001")
        best = rp.capture_design(chain, 6, {"ok": True, "scores": {"overall": 6},
                                            "modelHash": "HASH_REVIEWED"})
        snapshots = {}
        for i in range(2, 6):   # r002..r005：被放弃的补丁稿
            chain.model = {**chain.model, "totalVoxels": 4 + i}
            self.assertEqual(wa.version_design(chain, self.tmp, note=f"补丁{i}"), f"r00{i}")
            snapshots[f"r00{i}"] = open(self._path(f"r00{i}"), "rb").read()
        original_r001 = open(self._path("r001"), "rb").read()
        self.assertEqual(chain.revision, 5)

        rp.restore_design(chain, best)   # 回滚到最高分整模（r001 内容）

        self.assertEqual(chain.revision, 6, "回滚后必须落新版本 r006，不得倒退")
        self.assertEqual(chain.max_revision, 6)
        self.assertEqual(chain.version_overwrite_count, 0)
        entry = chain.revision_chain[-1]
        self.assertEqual(entry["revision"], 6)
        self.assertEqual(entry["parentRevision"], 5)
        self.assertEqual(entry["rolledBackTo"], 1)
        self.assertEqual(entry["cause"], "visual_rollback")
        # 旧文件全部未被覆盖/改写
        self.assertEqual(open(self._path("r001"), "rb").read(), original_r001)
        for rev_id, data in snapshots.items():
            self.assertEqual(open(self._path(rev_id), "rb").read(), data, f"{rev_id} 被覆盖")
        # 新版本记录的是回滚恢复的旧稿内容（版本号为新号）
        with open(self._path("r006"), encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored["revision"], "r006")
        self.assertEqual(restored["totalVoxels"], 4)
        self.assertIsNone(chain.rollback_pending, "版本化后 rollback_pending 必须清空")


class Class2WindowCellsTest(IsolatedArtifactsTest):
    def test_class2_failure_carries_full_window_not_truncated_prompt(self):
        """class2 失败透传全量 window_cells：>64 格进入修订上下文并展示真实总数。"""
        full_window = [(i % 4, i // 4 % 2, i // 8) for i in range(70)]
        prompt_cells = full_window[:2]
        solved = []
        seen_failures = []

        def solve_fn(model, layers, **kw):
            if not solved:
                solved.append(1)
                return None, {"kind": "disconnected", "message": "零件级连接图不连通（测试注入）",
                              "layer": 0, "cells": prompt_cells,
                              "window_cells": full_window, "rounds": 8, "offer": None}
            return tiler.solve_with_budget(model, layers, **kw)

        orig_apply = test_wph.apply_revision

        def spy_apply(chain, cls, failure, *args, **kwargs):
            seen_failures.append((cls, dict(failure)))
            return orig_apply(chain, cls, failure, *args, **kwargs)

        no_op = {"thought": "", "action": "revise_design", "args": {
            "baseRevision": "r001",
            "edits": [{"x": 0, "y": 0, "z": 0, "voxel": "#", "color": "浅灰"}]}}
        script = Script(resp(PLAN), resp(SAVE), resp(no_op))
        # 关闭 task-3 的结构候选救稿，验证 class2 原修订路径拿到全量窗口
        with mock.patch.object(test_wph, "apply_revision", spy_apply), \
                mock.patch.dict(os.environ, {"LEGOGOD_STRUCT_CANDIDATES": "off"}):
            result = run_generation(DESC, chat_fn=script, solve_fn=solve_fn)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(len(seen_failures), 1)
        cls, failure = seen_failures[0]
        self.assertEqual(cls, "class2")
        self.assertEqual(len(failure["window_cells"]), 70)
        self.assertEqual(len(failure["cells"]), 2)
        # 修订提示展示真实总数（展示上限 64，但总数是 70，不是截断提示格 2）
        revise_prompt = "\n".join(script.snapshots[-1])
        self.assertIn("共 70", revise_prompt)
        self.assertIn("展示 64 / 共 70", revise_prompt)
        self.assertNotIn("共 2。", revise_prompt)
        self.assertEqual(result["counts"]["revise_class2"], 1)
        # F.1 额度记录：request 是真实 HTTP 请求数（一次修订调用 = 1）
        self.assertEqual(result["quota"]["class2"],
                         {"limit": 2, "accepted": 1, "requests": 1})
        self.assertEqual(result["quota"]["class1"]["requests"], 0)


class QuotaWiringTest(unittest.TestCase):
    """F.1 接线：class1/class2 修订额度走 draw_budget.quota_limit，请求数按真实 HTTP 计数。"""

    def _capture_budgets(self, cls, env, counts=None):
        chain = workflow._Chain("一座测试高塔", mode="fast")
        chain.counts.update(counts or {})
        captured = {}

        def fake_apply(c, cls_name, failure, budgets, *args, **kwargs):
            captured.update(cls=cls_name, budgets=dict(budgets))
            raise workflow.GenerationFailure("stop", kind="protocol", stage="revise")

        with mock.patch.dict(os.environ, {"LEGOGOD_DYNAMIC_QUOTA": env}), \
                mock.patch("legogod.workflow_phases.apply_revision", fake_apply):
            with self.assertRaises(workflow.GenerationFailure):
                chain._apply_revision(cls, {"kind": "support"})
        return captured, chain

    def test_fixed_mode_uses_base_budget(self):
        """默认 fixed：class1/class2 基础额度 2，不因另一类已用而放大。"""
        captured, chain = self._capture_budgets("class1", "off", {"revise_class2": 1})
        self.assertEqual(captured["budgets"]["class1"], 2)
        self.assertEqual(captured["budgets"]["class2"], 2)
        self.assertEqual(captured["budgets"]["visual"], 2)
        self.assertEqual(chain.quota_limits["class1"], 2)

    def test_cross_mode_extends_after_other_class_accepted(self):
        """cross：另一类已接受 1 次 → 本类上限 +1（只放宽已接受次数）。"""
        captured, chain = self._capture_budgets("class1", "cross", {"revise_class2": 1})
        self.assertEqual(captured["budgets"]["class1"], 3)
        self.assertEqual(chain.quota_limits["class1"], 3)

    def test_cross_mode_without_other_accepted_stays_base(self):
        captured, chain = self._capture_budgets("class2", "cross")
        self.assertEqual(captured["budgets"]["class2"], 2)

    def test_revise_http_requests_are_counted_per_class(self):
        """requests 只累计修订阶段真实 HTTP 请求；其他阶段与另一类不串账。"""
        chain = workflow._Chain("一座测试高塔", mode="fast")
        chain.phase, chain.pending_revision = "revise", {"cls": "class2"}
        chain._count_requests(2)
        chain.phase = "solve"
        chain._count_requests(5)
        self.assertEqual(chain.quota_requests["class2"], 2)
        self.assertEqual(chain.quota_requests["class1"], 0)


class _FakeTrustChain:
    """record_trust_fields/build_run_record 读取的最小链（不含真实模型/运行状态）。"""

    def __init__(self, model=None, parts_norm=None):
        self.run_id = "trust1"
        self.model = model
        self.parts_norm = parts_norm
        self.plan = {"targetBlocks": 300, "estimatedVoxels": 600, "estimatedParts": 200}
        self.desc = "一座塔，目标约 300 块积木"
        self.draft = None
        self.best_draft = None
        self.gate_errors = []
        self.counts = {"revise_class1": 1, "revise_class2": 0, "revise_visual": 0}
        self.revision = 2
        self.revision_chain = [{"revision": 1, "modelHash": "a", "parentRevision": None,
                                "rolledBackTo": None, "cause": "初始"}]
        self.version_overwrite_count = 0
        self.review_state = None
        self.review_flag = None
        self.review_stale = False
        self.reviewed_model_hash = None
        self.quota_limits = {"class1": 3, "class2": 2}
        self.quota_requests = {"class1": 3, "class2": 0}
        self.structural_candidates = {"attempted": 2, "accepted": 1, "rejected": 1,
                                      "results": [{"cls": "class1", "outcome": "rejected"}]}
        self.draft_ranking = {"rule": "parts>cells>types", "selected": "best",
                              "candidates": [{"signature": "s1", "affectedPartCount": 1}]}
        self.gate_degraded_baseline = {"affectedPartCount": 1, "errorCellCount": 2,
                                       "errorTypes": ["support"]}
        self.chain_order = "class1_front"
        self.revision_incomplete = False
        self.revision_incomplete_reason = None
        self.revision_entries = []
        self.failures = []
        self.protocol_errors = []
        self.last_rejection = None
        self.rejections = []
        self.draw_attempts = []
        self.draw_dynamic = None
        self.timeline = []
        self.reviewed = None
        self.track = "ops"
        self.artifacts = {}
        self.logs = []

    def emit(self, kind, text, meta=None):
        self.logs.append((kind, text))


class _NoGit:
    def run(self, *args, **kwargs):
        raise OSError("测试不读 git")


class RecordFieldsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-fields-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_trust_fields_from_task7_records(self):
        """draftRanking/降级基线/额度/规模指标/结构候选按 task-7 结构写入。"""
        chain = _FakeTrustChain(model={"totalVoxels": 700, "layers": [{"y": 0}]},
                                parts_norm=[{"id": "tower", "cells": {(0, 0, 0)}}])
        with mock.patch("legogod.gate_replay.replay_final_gate",
                        return_value={"ok": False, "errors": ["门禁错误"],
                                      "affectedPartCount": 1, "errorCellCount": 2}):
            fields = wa.record_trust_fields(chain, pieces=200)
        self.assertEqual(fields["finalGateReplay"],
                         {"ok": False, "errors": ["门禁错误"],
                          "affectedPartCount": 1, "errorCellCount": 2})
        self.assertIsNone(fields["finalGateReplayReason"])
        self.assertEqual(fields["draftRanking"],
                         {"rule": "parts>cells>types",
                          "candidates": [{"signature": "s1", "affectedPartCount": 1}],
                          "selected": "best"})
        self.assertEqual(fields["gateDegradedBaseline"],
                         {"affectedPartCount": 1, "errorCellCount": 2,
                          "errorTypes": ["support"]})
        self.assertEqual(fields["quota"],
                         {"class1": {"limit": 3, "accepted": 1, "requests": 3},
                          "class2": {"limit": 2, "accepted": 0, "requests": 0}})
        self.assertEqual(fields["quotaMode"], "fixed")
        self.assertEqual(fields["chainOrder"], "class1_front")
        self.assertEqual(fields["structuralCandidates"],
                         {"attempted": 2, "accepted": 1, "rejected": 1,
                          "results": [{"cls": "class1", "outcome": "rejected"}]})
        metrics = fields["scaleMetrics"]
        self.assertEqual(metrics["targetBlocks"], 300)
        self.assertEqual(metrics["bricks"], 200)
        self.assertEqual(metrics["actualParts"], 200)
        self.assertAlmostEqual(metrics["targetBlocksRatio"], 200 / 300)
        self.assertEqual(fields["versionOverwriteCount"], 0)
        self.assertEqual(fields["revisionChain"][0]["revision"], 1)

    def test_missing_data_written_as_null_with_reason(self):
        """无最终模型/规划/排序记录：字段 null + 原因，不猜测、不伪造。"""
        chain = _FakeTrustChain(model=None, parts_norm=None)
        chain.plan = None
        chain.draft_ranking = None
        chain.gate_degraded_baseline = None
        fields = wa.record_trust_fields(chain)
        self.assertIsNone(fields["finalGateReplay"])
        self.assertIn("没有最终模型", fields["finalGateReplayReason"])
        self.assertIsNone(fields["scaleMetrics"])
        self.assertIn("没有规划", fields["scaleMetricsReason"])
        self.assertIsNone(fields["draftRanking"])
        self.assertIn("没有草稿", fields["draftRankingReason"])
        self.assertIsNone(fields["gateDegradedBaseline"])
        self.assertFalse(fields["reviewStale"])
        self.assertTrue(fields["reviewHashMissing"])

    def test_replay_unavailable_marks_null_not_fake_ok(self):
        """重放无法给出结论（ok=None）：字段 null + 原因，不得伪造通过。"""
        chain = _FakeTrustChain(model={"totalVoxels": 1}, parts_norm=[{"id": "tower"}])
        with mock.patch("legogod.gate_replay.replay_final_gate",
                        return_value={"ok": None, "error": "门禁重放不可用"}):
            fields = wa.record_trust_fields(chain)
        self.assertIsNone(fields["finalGateReplay"])
        self.assertIn("门禁重放不可用", fields["finalGateReplayReason"])

    def test_build_run_record_carries_trust_fields_top_level(self):
        """run_<id>.json 顶层携带全部可信度字段（acceptance-tools 直接读取）。"""
        chain = _FakeTrustChain(model=None, parts_norm=None)
        result = {"ok": False, "error": "断连", "run_id": "trust1",
                  "failure": {"kind": "disconnected"}}
        record = build_run_record(chain, result, DESC, "fidelity", 30, self.tmp, _NoGit())
        for key in ("finalGateReplay", "reviewedModelHash", "finalModelHash", "reviewStale",
                    "reviewHashMissing", "versionOverwriteCount", "revisionChain",
                    "draftRanking", "gateDegradedBaseline", "quotaMode", "quota",
                    "scaleMetrics", "chainOrder", "structuralCandidates"):
            self.assertIn(key, record, key)
        self.assertEqual(record["quotaMode"], "fixed")
        self.assertEqual(record["quota"]["class1"],
                         {"limit": 3, "accepted": 1, "requests": 3})
        self.assertEqual(record["gateRegressions"], 0)
        path = os.path.join(self.tmp, "run_trust1.json")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["chainOrder"], "class1_front")
        self.assertEqual(loaded["structuralCandidates"]["attempted"], 2)


class _StructuralFake:
    """structural_fallback 单测用最小链。"""

    def __init__(self):
        self.structural_candidates = {"attempted": 0, "accepted": 0, "rejected": 0,
                                      "results": []}
        self.results = []

    def emit(self, *args, **kwargs):
        pass

    def _finish_success(self, sol):
        return {"sol": sol, "finished": True}


class StructuralHookTest(unittest.TestCase):
    def test_hook_results_translated_and_not_double_counted(self):
        """hook 返回 sol → 提前成功；model_changed → retry；None → 走原修订；不重复计数。"""
        chain = _StructuralFake()
        with mock.patch("legogod.workflow_phases.try_structural_candidates",
                        return_value={"accepted": True, "sol": {"steps": []}}):
            out = fb.structural_fallback(chain, "class2", {"kind": "disconnected"})
        self.assertTrue(out["finished"])
        self.assertEqual(chain.structural_candidates["attempted"], 0,
                         "候选计数由 task-3 实现维护，本层不得重复累计")

        with mock.patch("legogod.workflow_phases.try_structural_candidates",
                        return_value={"accepted": True, "model_changed": True}):
            self.assertEqual(fb.structural_fallback(chain, "class1", {}), "retry")

        with mock.patch("legogod.workflow_phases.try_structural_candidates",
                        return_value=None):
            self.assertIsNone(fb.structural_fallback(chain, "class1", {}))

    def test_hook_exception_is_recorded_and_falls_back(self):
        """候选 hook 异常：按原修订继续，异常作为一次 rejected 结果被记录。"""
        chain = _StructuralFake()

        def boom(*args, **kwargs):
            raise RuntimeError("候选爆炸")

        with mock.patch("legogod.workflow_phases.try_structural_candidates", side_effect=boom):
            self.assertIsNone(fb.structural_fallback(chain, "class2", {"kind": "support"}))
        self.assertEqual(chain.structural_candidates["attempted"], 1)
        self.assertEqual(chain.structural_candidates["rejected"], 1)
        self.assertIn("候选爆炸", chain.structural_candidates["results"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
