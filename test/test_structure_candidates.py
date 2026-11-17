# -*- coding: utf-8 -*-
"""工作包 B：结构候选完整验收的离线机制测试与快照证据。

覆盖（不依赖 LLM）：
  - disconnected 组件界面格/两侧组件摘要/可连接邻域生成；
  - suspension 锁扣与子组件坐标只搬运校验已算出的坐标；
  - 模型空间候选在副本执行，编译/绑定/核心/门禁/预检不得退化；
  - class1 候选立即重跑 precheck；class2 候选必须真实求解并通过统一校验；
  - 候选恶化（新预检错误/未通过统一校验）必须拒绝；
  - 取消/超时生效；LEGOGOD_STRUCT_CANDIDATES=off 与原行为一致。
快照证据（8 份可评估快照）由 LEGOGOD_STRUCT_CANDIDATES_EVIDENCE=1 开启，写入 artifacts/。
"""
import json
import os
import sys
import threading
import time
import unittest
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import part_binding as pb  # noqa: E402
from legogod import tiler_repair as tr  # noqa: E402
from legogod import structure_candidates as sc  # noqa: E402
from legogod import tiler, workflow_phases as wph  # noqa: E402
from legogod.agent import (precheck_details, support_reasons_for_cells,  # noqa: E402
                           validate_design_syntax)
from legogod.geometry import solid_cells_of_model  # noqa: E402
from legogod.parts_library import PART_MAP  # noqa: E402
from legogod.support_reasons import REASON_BRICK, REASON_COLOR  # noqa: E402
from legogod.validate import validate_solution  # noqa: E402

ARTIFACTS = os.path.join(ROOT, "artifacts")
EVIDENCE_PATH = os.path.join(ARTIFACTS, "structure_candidates_evidence_20261103.json")


class _Cancelled(Exception):
    """测试用取消异常（真实主链是 workflow.CancelledError）。"""


class _Chain:
    """最小链替身：只提供结构候选需要的状态与钩子。"""

    def __init__(self, model, parts, assignment, default_part="body",
                 frozen_cells=None, cores_frozen=True, solve_fn=None, track="ops"):
        self.model = model
        self.layers = [{"module": L["module"][0] if isinstance(L["module"], (list, tuple))
                        else (L["module"] or "层"),
                        "color": L.get("color"), "rows": list(L["rows"]),
                        "colorRows": list(L["colorRows"]) if L.get("colorRows") else None}
                       for L in model["layers"]]
        self.parts_norm = parts
        self.assignment = assignment
        self.default_part = default_part
        self.frozen_cells = set(frozen_cells or [])
        self.cores_frozen = cores_frozen
        self.track = track
        self.ops = [] if track == "ops" else None
        self.revision = 0
        self.revision_note = None
        self.artifacts = {}
        self.logs = []
        self.cancel = threading.Event()
        self.hard_deadline = time.monotonic() + 600.0
        self.solve_fn = solve_fn or tiler.solve_with_budget
        self.solve_calls = 0

    def emit(self, kind, text, meta=None):
        self.logs.append((kind, text))

    def check_cancel(self):
        if self.cancel.is_set():
            raise _Cancelled()

    def _record_parts(self):
        pass

    def _version_design(self, note=""):
        self.revision += 1
        self.revision_note = note


def _state(rows_by_layer, part_id="body"):
    """由逐层 rows 编译模型并完成部位绑定，返回 (model, parts_norm, assignment, frozen)。"""
    plan = {"name": "测试", "slug": "struct-test", "features": ["测试"],
            "layers": [{"module": f"层{y}", "color": "浅灰", "rows": list(rows)}
                       for y, rows in enumerate(rows_by_layer)]}
    errs, model, _warns = validate_design_syntax(plan)
    assert not errs, errs
    assign = {tuple(c): part_id for c in solid_cells_of_model(model)}
    decl = [{"id": part_id, "name": "主体", "required": True, "source": "测试"}]
    errs, bound = pb.rebuild_parts(decl, assign, model)
    assert not errs, errs
    frozen = set()
    for part in bound["parts"]:
        frozen |= set(part.get("core_cells") or set())
    # 模型存档里的部位区域（boxes/coreCells）供失败信息摘要还原部位归属
    model["parts"] = [{"id": p["id"], "name": p["name"], "required": p["required"],
                       "role": p.get("role") or "solid", "voxels": len(p["cells"]),
                       "boxes": p.get("boxes") or [],
                       "coreCells": [list(c) for c in sorted(p.get("core_cells") or set())]}
                      for p in bound["parts"]]
    return model, bound["parts"], bound["assign"], frozen


def _overhang_state():
    """10 宽单行出檐：y=1 的 x=8/x=9 无受支撑砖可覆盖 → support 预检失败。"""
    return _state([["#........."], ["##########"]])


class DisconnectedInfoTest(unittest.TestCase):
    def test_interface_cells_and_component_summaries(self):
        """两侧 6-相邻的体素对成为界面格，组件摘要含体素数/包围盒/部位。"""
        model, parts, _assign, _frozen = _state([["###"], ["..."]])
        info = tr.analyze_disconnected(model, [[1, 0, 0]])
        self.assertEqual(len(info["components"]), 2)
        main = next(c for c in info["components"] if c["id"] == "main")
        self.assertEqual(main["voxels"], 2)
        self.assertEqual(main["parts"], ["body"])
        loose = next(c for c in info["components"] if c["id"] != "main")
        self.assertEqual(loose["voxels"], 1)
        self.assertEqual(len(info["interfaceCells"]), 2, info["interfaceCells"])
        self.assertEqual(len(info["connectableCells"]), 3, info["connectableCells"])
        self.assertTrue(all(c[1] == 1 for c in info["connectableCells"]))

    def test_no_loose_side_returns_none(self):
        """游离侧为空或全模都是游离侧时不编组件。"""
        model, _p, _a, _f = _state([["###"]])
        self.assertIsNone(tr.analyze_disconnected(model, []))
        self.assertIsNone(tr.analyze_disconnected(model, [[0, 0, 0], [1, 0, 0], [2, 0, 0]]))

    def test_tiler_disconnected_failure_carries_info(self):
        """真实求解断连失败：失败对象带组件摘要与界面格，提示 cells 仍保留。"""
        # 同一层两个异色 1x1：只能铺两块独立 1x1 → 零件图不连通。
        plan = {"name": "断连", "slug": "dc", "features": ["测试"],
                "layers": [{"module": "底", "color": "红色", "rows": ["##"],
                            "colorRows": ["RB"]}]}
        errs, model, _w = validate_design_syntax(plan)
        self.assertEqual(errs, [])
        sol, failure = tiler.solve_with_budget(model, model["layers"], rounds=1,
                                               log=lambda s: None)
        self.assertIsNone(sol)
        self.assertEqual(failure["kind"], "disconnected")
        info = failure.get("info") or {}
        self.assertEqual(len(info.get("components") or []), 2, info)
        self.assertTrue(info.get("interfaceCells"), "断连失败必须给出组件界面格")
        self.assertTrue(failure.get("window_cells"))


class SuspensionInfoTest(unittest.TestCase):
    def _single_stud_cluster(self):
        """单锁扣吊挂：吊挂砖 (3,1,0) 只被上方跨接砖压住 1 个凸点。"""
        parts = [
            {"layer": 0, "piece": "B2x4", "rot": False, "x": 0, "z": 0,
             "cells": [(0, 0), (1, 0), (0, 1), (1, 1)], "parents": set()},
            {"layer": 1, "piece": "B1x1", "rot": False, "x": 3, "z": 0,
             "cells": [(3, 0)], "parents": set()},
            {"layer": 2, "piece": "B2x4", "rot": False, "x": 0, "z": 0,
             "cells": [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)],
             "parents": {0}},
        ]
        adj = {0: {2}, 1: {2}, 2: {0, 1}}
        return parts, adj

    def test_check_all_records_lock_and_subassembly_cells(self):
        """suspension.check_all 记录校验已算出的锁扣与子组件坐标。"""
        from legogod import suspension
        parts, adj = self._single_stud_cluster()
        clusters, errs = suspension.check_all(parts, adj)
        self.assertTrue(errs)
        cluster = clusters[0]
        self.assertIn((3, 1, 0), [tuple(c) for c in cluster["lockCells"]])
        self.assertIn((3, 1, 0), [tuple(c) for c in cluster["subassemblyCells"]])

    def test_validation_failure_copies_positions_without_inventing(self):
        """统一校验失败映射：锁扣来自 suspensionWindow，子组件来自簇成员索引到 steps。"""
        report = {"ok": False, "errors": ["（预拼子组件 1，y=1 层附近）吊挂子组件只有 1 个锁扣凸点"],
                  "suspensionWindow": [(3, 1, 0)],
                  "subassemblies": [{"bricks": [0, 1], "hangingBricks": [0],
                                     "anchorBricks": [1]}]}
        solution = {"steps": [
            {"layer": 1, "piece": "B1x1", "x": 3, "z": 0, "rotate": False},
            {"layer": 2, "piece": "B2x4", "x": 0, "z": 0, "rotate": False},
        ]}
        failure = tiler._validation_failure(report, solution)
        self.assertEqual(failure["kind"], "suspension")
        self.assertEqual(failure["window_cells"], [(3, 1, 0)])
        self.assertEqual([tuple(c) for c in failure["info"]["lockCells"]], [(3, 1, 0)])
        self.assertIn((3, 1, 0), [tuple(c) for c in failure["info"]["subassemblyCells"]])
        # 没有坐标时不编造
        no_pos = tiler._validation_failure({"ok": False,
                                            "errors": ["吊挂子组件只有 1 个锁扣凸点"]})
        self.assertNotIn("info", no_pos)
        self.assertNotIn("window_cells", no_pos)

    def test_suspension_candidate_widens_lock_studs(self):
        """suspension 模型空间候选只在锁扣凸点上方空位加宽咬合面。"""
        model, parts, assign, frozen = _state([["###"], ["###"], ["..."]])
        failure = {"kind": "suspension", "cells": [], "window_cells": [[1, 1, 0]],
                   "info": {"lockCells": [[1, 1, 0]], "subassemblyCells": []}}
        candidates = sc.generate_model_candidates(model, failure, parts, assign, "body")
        self.assertEqual([c["family"] for c in candidates], ["lock_widen"])
        cells = [item["cell"] for item in candidates[0]["adds"]]
        self.assertTrue(cells)
        self.assertTrue(all(c[1] == 2 for c in cells), cells)
        solid = solid_cells_of_model(model)
        self.assertTrue(all(c not in solid for c in cells), "不得重复新增已有实体格")


class ModelCandidatePipelineTest(unittest.TestCase):
    def test_support_column_candidate_passes_checks_on_copy(self):
        """模型空间候选在副本执行：编译/绑定/核心/门禁不退化、预检重跑通过，原模型不变。"""
        model, parts, assign, frozen = _overhang_state()
        before = json.dumps(model, ensure_ascii=False, sort_keys=True)
        detail = precheck_details(model)
        failure = {"kind": "support", "cells": detail["error_cells"],
                   "window_cells": detail["error_cells"],
                   "info": {"supportReasons": detail["support_reasons"]}}
        base = sc.baseline_checks(model, parts)
        candidates = sc.generate_model_candidates(model, failure, parts, assign, "body")
        self.assertEqual([c["family"] for c in candidates], ["support_column"])
        built, reasons = sc.evaluate_model_candidate(model, parts, assign, "body",
                                                     frozen, candidates[0], base)
        self.assertIsNotNone(built, reasons)
        self.assertEqual(built["precheck"]["errors"], [])
        self.assertEqual(json.dumps(model, ensure_ascii=False, sort_keys=True), before,
                         "候选必须在副本上执行，原模型不得被改")
        self.assertEqual(sc._regressions(base, built), [])

    def test_candidate_creating_new_precheck_errors_is_rejected(self):
        """已通过的检查重新失败（新增预检错误格）必须拒绝。"""
        model, parts, assign, frozen = _state([["##...."], ["##...."]])
        self.assertEqual(precheck_details(model)["errors"], [])
        base = sc.baseline_checks(model, parts)
        bad = {"space": "model", "family": "manual",
               "adds": [{"cell": (5, 1, 0), "part": "body"}]}
        built, reasons = sc.evaluate_model_candidate(model, parts, assign, "body",
                                                     frozen, bad, base)
        self.assertIsNone(built)
        self.assertTrue(any(r.startswith("precheck_new_cells") for r in reasons), reasons)

    def test_regressions_detect_binding_and_gate(self):
        """绑定/门禁出现基线没有的新错误 → 拒绝（回归判定单测）。"""
        base = {"bindingErrors": [], "gateErrors": [], "precheck": {"error_cells": []}}
        built = {"bindingErrors": ["部位丢失"], "gateErrors": ["伪部位"],
                 "precheck": {"error_cells": []}}
        reasons = sc._regressions(base, built)
        self.assertIn("binding_regressed", reasons)
        self.assertIn("gate_regressed", reasons)
        # 基线已有相同门禁错误不算新增
        base2 = {"bindingErrors": [], "gateErrors": ["伪部位"], "precheck": {"error_cells": []}}
        self.assertEqual(sc._regressions(base2, built), ["binding_regressed"])

    def test_color_fragment_does_not_generate_geometry_candidate(self):
        """候选按原因码分流：颜色碎片不生成几何补丁候选（需要换色，交给模型修订）。"""
        model, parts, assign, _frozen = _state([["#......"], ["###...."]])
        # 手工构造颜色碎片失败（模型本身没有 colorRows，用原因码分流接口验证）
        failure = {"kind": "support", "cells": [(2, 1, 0)],
                   "window_cells": [(2, 1, 0)],
                   "info": {"supportReasons": {
                       REASON_COLOR: {"count": 1, "cells": [[2, 1, 0]]}}}}
        self.assertEqual(sc.generate_model_candidates(model, failure, parts, assign, "body"), [])


class TryCandidatesContractTest(unittest.TestCase):
    def _class1_chain(self):
        model, parts, assign, frozen = _overhang_state()
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        detail = precheck_details(model)
        failure = {"kind": "support", "message": detail["errors"][0],
                   "cells": detail["error_cells"], "window_cells": detail["error_cells"],
                   "layer": None}
        return chain, failure

    def test_class1_candidate_applied_and_precheck_rerun(self):
        """class1：模型空间候选应用后返回 model_changed，预检已重跑通过，版本递增。"""
        chain, failure = self._class1_chain()
        out = wph.try_structural_candidates(chain, "class1", failure)
        self.assertEqual(out, {"accepted": True, "model_changed": True})
        self.assertEqual(precheck_details(chain.model)["errors"], [])
        self.assertEqual(chain.revision, 1)
        state = chain.structural_candidates
        self.assertEqual(state["attempted"], 1)
        self.assertEqual(state["accepted"], 1)
        self.assertEqual(state["rejected"], 0)
        self.assertEqual(state["results"][0]["space"], "model")
        self.assertEqual(state["results"][0]["family"], "support_column")
        self.assertTrue(any("结构候选接受" in text for _k, text in chain.logs))

    def test_class2_model_candidate_must_really_solve(self):
        """class2：模型空间候选必须真实调用求解器并通过统一校验才算救回。"""
        # 2 层满 + 第 3 层空：锁扣加宽候选在 y=2 补出可铺格，随后必须真实求解。
        model, parts, assign, frozen = _state([["##", "##"], ["##", "##"], ["..", ".."]])
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        calls = {"n": 0}

        def solve_fn(model, layers, **kw):
            calls["n"] += 1
            return tiler.solve_with_budget(model, layers, **kw)

        chain.solve_fn = solve_fn
        failure = {"kind": "suspension", "message": "吊挂锁扣不足",
                   "cells": [], "window_cells": [[0, 1, 0]],
                   "info": {"lockCells": [[0, 1, 0]], "subassemblyCells": []}}
        out = wph.try_structural_candidates(chain, "class2", failure)
        self.assertTrue(out and out.get("accepted"), out)
        self.assertIn("sol", out)
        self.assertEqual(calls["n"], 1, "class2 候选必须真实调用求解器")
        self.assertTrue((out["sol"].get("validation") or {}).get("ok"))
        self.assertEqual(chain.structural_candidates["results"][0]["outcome"], "accepted")
        self.assertEqual(chain.structural_candidates["results"][0]["space"], "model")
        self.assertGreater(len(solid_cells_of_model(chain.model)),
                           len(solid_cells_of_model(model)), "模型空间候选应已写入链状态")

    def test_class2_solution_space_candidate_rescued_by_real_solve(self):
        """solution 空间候选只改铺法：真实求解 + 统一校验通过后返回 sol，模型不变。"""
        model, parts, assign, frozen = _state([["##", "##"]])
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        before = json.dumps(model, ensure_ascii=False, sort_keys=True)
        failure = {"kind": "disconnected", "message": "注入的断连失败",
                   "cells": [], "window_cells": [], "layer": 0}
        out = wph.try_structural_candidates(chain, "class2", failure)
        self.assertTrue(out and out.get("accepted"), out)
        self.assertIn("sol", out)
        self.assertTrue((out["sol"].get("validation") or {}).get("ok"))
        self.assertEqual(json.dumps(chain.model, ensure_ascii=False, sort_keys=True), before,
                         "solution 空间候选不得改模型")
        self.assertEqual(chain.revision, 0, "solution 空间候选不产生新模型版本")
        results = chain.structural_candidates["results"]
        self.assertTrue(any(r["space"] == "solution" and r["outcome"] == "accepted"
                            for r in results), results)

    def test_class2_unified_validation_failure_is_rejected(self):
        """候选方案未通过统一校验（validation 缺失/ok=false）必须拒绝。"""
        model, parts, assign, frozen = _state([["##", "##"]])
        chain = _Chain(model, parts, assign, frozen_cells=frozen)

        def bad_solve(model, layers, **kw):
            return {"steps": [{"layer": 0, "piece": "B1x1", "x": 0, "z": 0}],
                    "validation": {"ok": False, "errors": ["注入失败"]}}, None

        chain.solve_fn = bad_solve
        failure = {"kind": "disconnected", "cells": [], "window_cells": [], "layer": 0}
        out = wph.try_structural_candidates(chain, "class2", failure)
        self.assertIsNone(out)
        reasons = [r["reason"] for r in chain.structural_candidates["results"]]
        self.assertIn("solution_unvalidated", reasons)

    def test_class2_solver_still_failing_is_rejected(self):
        """候选无法在预算内真实救回时拒绝并记录原因，不改模型。"""
        # 两层异色：零件图必然断连且没有可用界面桥（上层已满）。
        plan = {"name": "断连", "slug": "dc2", "features": ["测试"],
                "layers": [{"module": "底", "color": "红色", "rows": ["##"],
                            "colorRows": ["RB"]},
                           {"module": "顶", "color": "红色", "rows": ["##"],
                            "colorRows": ["RB"]}]}
        errs, model, _w = validate_design_syntax(plan)
        self.assertEqual(errs, [])
        assign = {tuple(c): "body" for c in solid_cells_of_model(model)}
        decl = [{"id": "body", "name": "主体", "required": True, "source": "测试"}]
        _e, bound = pb.rebuild_parts(decl, assign, model)
        frozen = set()
        for part in bound["parts"]:
            frozen |= set(part.get("core_cells") or set())
        chain = _Chain(model, bound["parts"], bound["assign"], frozen_cells=frozen)
        before = json.dumps(model, ensure_ascii=False, sort_keys=True)
        failure = {"kind": "disconnected", "cells": [[0, 0, 0]], "window_cells": [[0, 0, 0]],
                   "layer": 0}
        out = wph.try_structural_candidates(chain, "class2", failure)
        self.assertIsNone(out)
        self.assertEqual(json.dumps(chain.model, ensure_ascii=False, sort_keys=True), before)
        self.assertGreaterEqual(chain.structural_candidates["rejected"], 1)

    def test_cancel_aborts_candidates(self):
        """取消生效：取消信号下候选立即中止并抛取消异常，不接受任何候选。"""
        model, parts, assign, frozen = _state([["##", "##"]])
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        chain.cancel.set()
        failure = {"kind": "disconnected", "cells": [], "window_cells": [], "layer": 0}
        with self.assertRaises(_Cancelled):
            wph.try_structural_candidates(chain, "class2", failure)
        state = chain.structural_candidates
        self.assertEqual(state["accepted"], 0)

    def test_no_time_rejects_without_side_effects(self):
        """总候选时间上限：没有剩余时间时直接拒绝，不求解、不改模型。"""
        model, parts, assign, frozen = _state([["##", "##"]])
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        chain.hard_deadline = time.monotonic() - 100.0
        failure = {"kind": "disconnected", "cells": [], "window_cells": [], "layer": 0}
        self.assertIsNone(wph.try_structural_candidates(chain, "class2", failure))
        self.assertEqual(chain.structural_candidates["results"][0]["reason"], "no_time")

    def test_env_off_restores_original_behavior(self):
        """LEGOGOD_STRUCT_CANDIDATES=off：不生成候选、不求解、不写累计器。"""
        model, parts, assign, frozen = _overhang_state()
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        detail = precheck_details(model)
        failure = {"kind": "support", "cells": detail["error_cells"],
                   "window_cells": detail["error_cells"], "layer": None}
        old = os.environ.get("LEGOGOD_STRUCT_CANDIDATES")
        os.environ["LEGOGOD_STRUCT_CANDIDATES"] = "off"
        try:
            self.assertIsNone(wph.try_structural_candidates(chain, "class1", failure))
        finally:
            if old is None:
                os.environ.pop("LEGOGOD_STRUCT_CANDIDATES", None)
            else:
                os.environ["LEGOGOD_STRUCT_CANDIDATES"] = old
        self.assertFalse(hasattr(chain, "structural_candidates"))
        self.assertEqual(chain.revision, 0)

    def test_unknown_kind_is_not_attempted(self):
        """非结构失败不进入候选框架（保留原修订路径）。"""
        model, parts, assign, frozen = _state([["##", "##"]])
        chain = _Chain(model, parts, assign, frozen_cells=frozen)
        self.assertIsNone(wph.try_structural_candidates(chain, "class2",
                                                        {"kind": "inventory", "cells": []}))
        self.assertEqual(chain.structural_candidates["results"][0]["reason"], "unsupported_kind")


# ============================================================
# 8 份可评估快照的离线机制验证（证据落盘；默认跳过，显式开启才跑真实求解）
# ============================================================

SNAPSHOT_CASES = [
    ("C02", "run_51dcc9de.json"),
    ("C03", "run_5a57e924.json"),
    ("C06", "run_7d52955e.json"),
    ("C13", "run_53460ab2.json"),
    ("H01", "run_399623bd.json"),
    ("H07", "run_31df0965.json"),
    ("C16", "run_81f6784e.json"),
    ("C14", "run_fe3aafff.json"),
]


def _load_snapshot(case, run_name):
    """读取 run 快照与对应模型文件，校验 modelHash，重建 model/parts/assignment。"""
    from legogod.workflow_artifacts import model_hash
    with open(os.path.join(ARTIFACTS, run_name), encoding="utf-8") as f:
        run = json.load(f)
    snap = run.get("structureSnapshot") or {}
    revision = run.get("revision")
    model_name = (run.get("artifacts") or {}).get(f"model_r{int(revision):03d}")
    with open(os.path.join(ARTIFACTS, model_name), encoding="utf-8") as f:
        record = json.load(f)
    # 快照 modelHash 是对「当时内存 chain.model」求的哈希；模型存档 = chain.model +
    # schemaVersion/revision/runId/revisionNote/ops（track 属于 chain.model 本身，保留）。
    in_memory = {k: v for k, v in record.items()
                 if k not in ("schemaVersion", "revision", "runId", "revisionNote", "ops")}
    if model_hash(in_memory) != snap.get("modelHash"):
        raise AssertionError(f"{case} 模型哈希与快照不一致：{model_name}")
    errs, model, _warns = validate_design_syntax(
        {"name": record.get("name"), "slug": record.get("slug"),
         "notes": record.get("notes") or "", "features": record.get("features") or [],
         "layers": record.get("layers") or []}, require_layer_color=False)
    if errs:
        raise AssertionError(f"{case} 快照模型无法编译：{errs[:2]}")
    part_cells = tr.part_cells_from_model(record)
    parts = []
    for p in record.get("parts") or []:
        pid = str(p.get("id"))
        parts.append({"id": pid, "name": p.get("name") or pid,
                      "required": bool(p.get("required", True)),
                      "source": p.get("source") or "", "role": p.get("role") or "solid",
                      "cells": part_cells.get(pid) or set(),
                      "core_cells": {tuple(c) for c in p.get("coreCells") or []},
                      "boxes": p.get("boxes") or []})
    assignment = {}
    for p in parts:
        for c in p["cells"]:
            assignment[c] = p["id"]
    default_part = max(parts, key=lambda p: len(p["cells"]))["id"] if parts else None
    frozen = {tuple(c) for c in snap.get("frozenCells") or []}
    kind = snap.get("kind")
    failure = {"kind": kind, "layer": snap.get("layer"),
               "cells": [tuple(c) for c in snap.get("promptCells") or []],
               "window_cells": [tuple(c) for c in snap.get("windowCells") or []]}
    if kind in ("disconnected", "connectivity"):
        failure["info"] = tr.analyze_disconnected(model, failure["window_cells"]) or {}
    elif kind == "support":
        failure["info"] = {"supportReasons": support_reasons_for_cells(
            model, failure["window_cells"])}
    elif kind == "suspension":
        failure["info"] = {"lockCells": failure["window_cells"], "subassemblyCells": []}
    return {"case": case, "run": run_name, "snapshot": snap, "model": model,
            "parts": parts, "assignment": assignment, "default_part": default_part,
            "frozen": frozen, "failure": failure,
            "bindingErrors": pb.parts_binding_errors(parts, model)}


def _short_cells(cells, cap=6):
    return [list(c) for c in (cells or [])[:cap]]


def run_snapshot_audit(total_budget_s=90.0, solve_budget_s=6.0):
    """8 份快照候选生成/验收/拒绝机制验证，返回机器可读统计与逐例明细。"""
    stats = {"snapshots": 0, "evaluable": 0, "modelCandidates": 0,
             "modelCheckPass": 0, "solutionAttempts": 0, "accepted": 0,
             "rejected": Counter()}
    details = []
    deadline = time.monotonic() + total_budget_s
    for case, run_name in SNAPSHOT_CASES:
        item = {"case": case, "run": run_name, "evaluable": False}
        try:
            state = _load_snapshot(case, run_name)
        except (OSError, KeyError, ValueError, AssertionError) as exc:
            item["unevaluableReason"] = f"{type(exc).__name__}: {exc}"
            details.append(item)
            continue
        stats["snapshots"] += 1
        item.update({"kind": state["failure"]["kind"],
                     "modelHash": state["snapshot"].get("modelHash"),
                     "windowCells": len(state["failure"].get("window_cells") or []),
                     "bindingOk": not state["bindingErrors"]})
        info = state["failure"].get("info") or {}
        item["info"] = {
            "components": len(info.get("components") or []),
            "interfaceCells": len(info.get("interfaceCells") or []),
            "connectableCells": len(info.get("connectableCells") or []),
            "lockCells": len(info.get("lockCells") or []),
            "subassemblyCells": len(info.get("subassemblyCells") or []),
            "supportReasons": {k: v.get("count") for k, v in
                               (info.get("supportReasons") or {}).items()},
        }
        item["evaluable"] = not state["bindingErrors"]
        if not item["evaluable"]:
            item["unevaluableReason"] = "部位绑定自洽检查未通过"
            details.append(item)
            continue
        stats["evaluable"] += 1
        base = sc.baseline_checks(state["model"], state["parts"])
        item["baseline"] = {"gateErrors": len(base["gateErrors"]),
                            "precheckErrors": len(base["precheck"].get("error_cells") or []),
                            "precheckKind": base["precheck"].get("kind")}
        candidates = sc.generate_model_candidates(
            state["model"], state["failure"], state["parts"],
            state["assignment"], state["default_part"])
        item["candidates"] = []
        for candidate in candidates:
            stats["modelCandidates"] += 1
            built, reasons = sc.evaluate_model_candidate(
                state["model"], state["parts"], state["assignment"],
                state["default_part"], state["frozen"], candidate, base)
            entry = {"family": candidate["family"], "space": candidate["space"],
                     "adds": len(candidate.get("adds") or []),
                     "checksPass": built is not None,
                     "reasons": list(reasons)}
            item["candidates"].append(entry)
            if built is None:
                for reason in reasons:
                    stats["rejected"][reason] += 1
                continue
            stats["modelCheckPass"] += 1
            # class2 语义：通过检查的模型空间候选必须真实求解 + 统一校验才算救回。
            if time.monotonic() >= deadline:
                entry["solve"] = "skipped_budget"
                stats["rejected"]["audit_budget_exhausted"] += 1
                continue
            stats["solutionAttempts"] += 1
            end = min(deadline, time.monotonic() + solve_budget_s)
            sol, failure = tiler.solve_with_budget(
                built["model"], sorted(built["model"]["layers"], key=lambda L: L["y"]),
                deadline=end, validate_fn=validate_solution, log=lambda s: None)
            if sol is not None and (sol.get("validation") or {}).get("ok"):
                entry["solve"] = "accepted"
                stats["accepted"] += 1
            else:
                reason = "solve_failed:" + str((failure or {}).get("kind") or "unknown")
                if (failure or {}).get("budget_exhausted"):
                    reason = "solve_timeout"
                entry["solve"] = reason
                stats["rejected"][reason] += 1
        # solution 空间候选：同一模型只改铺法，真实求解 + 统一校验。
        if time.monotonic() >= deadline:
            item["solutionSpace"] = "skipped_budget"
            stats["rejected"]["audit_budget_exhausted"] += 1
        else:
            stats["solutionAttempts"] += 1
            end = min(deadline, time.monotonic() + solve_budget_s)
            sol, failure = tiler.solve_with_budget(
                state["model"], sorted(state["model"]["layers"], key=lambda L: L["y"]),
                deadline=end, validate_fn=validate_solution, log=lambda s: None,
                border_first=True, merge_first_all=True)
            if sol is not None and (sol.get("validation") or {}).get("ok"):
                item["solutionSpace"] = "accepted"
                stats["accepted"] += 1
            else:
                reason = "solve_failed:" + str((failure or {}).get("kind") or "unknown")
                if (failure or {}).get("budget_exhausted"):
                    reason = "solve_timeout"
                item["solutionSpace"] = reason
                stats["rejected"][reason] += 1
        item["rejectedDetail"] = _short_cells(
            [c for cand in item["candidates"] for c in []])
        details.append(item)
    return {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "budget": {"totalS": total_budget_s, "solvePerAttemptS": solve_budget_s},
            "stats": {**stats, "rejected": dict(stats["rejected"])},
            "snapshots": details}


# ============================================================
# 预检试验：颜色感知接地可达性 + 锚点计数（证据用，不接入预检）
#
# 可复现定义（本函数即定义，逐格明细落盘）：
#   逐层自下而上计算可达集 R_y：
#     R_0 = 第 0 层全部实体格（地面直接承托；1x1 单色砖总能铺）；
#     R_y = {c ∈ 第 y 层实体格 : ∃ 矩形砖摆放 P（零件库形状×0/90° 旋转）使
#            c∈P、P 全部格是实体 '#'、P 内逐体素颜色至多 1 种（内部通配格不约束颜色）、
#            且 P 内至少一格 p 满足 (p, y-1) ∈ R_{y-1}（压在上一层接地可达格上）}。
#   不可达格 = 实体格 − R_y；原因分类 no_placement / color_mixed / no_grounded_below。
#   锚点计数 anchors(y) = #{(x,z) : (x,y,z) 实体且 (x,y+1,z) 实体}
#     （相邻两层之间实际咬合的承托凸点数；可承托面凸点按体素格计）。
# 本试验只产出证据，不改变 precheck_details / find_unsupported 的任何判定。
# ============================================================

REACHABILITY_EVIDENCE_PATH = os.path.join(
    ARTIFACTS, "color_aware_reachability_evidence_20261103.json")
_COLOR_EVIDENCE_ENV = "LEGOGOD_STRUCT_CANDIDATES_EVIDENCE"


def _reach_shapes():
    """矩形砖候选尺寸（含 90° 旋转）：[(w, d)]，与求解器零件库一致。"""
    from legogod.parts_library import RECT_SHAPES, SHAPE_MAP
    out = []
    for sid in RECT_SHAPES:
        shape = SHAPE_MAP[sid]
        out.append((shape["w"], shape["d"]))
        if shape["w"] != shape["d"]:
            out.append((shape["d"], shape["w"]))
    return sorted(set(out))


def color_aware_grounded_reachability(model):
    """按模块注释里的可复现定义计算逐层接地可达性、不可达明细与锚点计数。"""
    from legogod.geometry import interior_cells
    from legogod.parts_library import voxel_color_map
    layers = model.get("layers") or []
    solid, color_of = {}, {}
    interior = interior_cells(model)
    for L in layers:
        y = L["y"]
        cmap = voxel_color_map(L.get("rows") or [], L.get("colorRows"), L.get("color")) or {}
        for z, row in enumerate(L.get("rows") or []):
            for x, ch in enumerate(row):
                if ch == ".":
                    continue
                solid[(x, y, z)] = ch
                color_of[(x, y, z)] = None if (x, y, z) in interior else cmap.get((x, z))
    shapes = _reach_shapes()
    reachable = {}          # y -> {(x, z)}
    details = []
    prev_reach = None
    for L in layers:
        y = L["y"]
        cells = [(x, z) for (x, yy, z) in solid if yy == y]
        cur_reach = set()
        unreachable = []
        for (x, z) in sorted(cells):
            any_shape = any_grounded = any_ok = False
            for (w, d) in shapes:
                for ox in range(w):
                    for oz in range(d):
                        x0, z0 = x - ox, z - oz
                        pcs = [(x0 + i, z0 + j) for i in range(w) for j in range(d)]
                        if not all((px, y, pz) in solid and solid[(px, y, pz)] == "#"
                                   for (px, pz) in pcs):
                            continue
                        any_shape = True
                        grounded = (y == 0) or any((px, pz) in prev_reach
                                                   for (px, pz) in pcs)
                        if not grounded:
                            continue
                        any_grounded = True
                        colors = {color_of.get((px, y, pz)) for (px, pz) in pcs}
                        colors.discard(None)
                        if len(colors) <= 1:
                            any_ok = True
                            break
                if any_ok:
                    break
            if any_ok:
                cur_reach.add((x, z))
            else:
                if not any_shape:
                    reason = "no_placement"
                elif not any_grounded:
                    reason = "no_grounded_below"
                else:
                    reason = "color_mixed"
                unreachable.append({"cell": [x, y, z], "reason": reason})
        reachable[y] = cur_reach
        prev_reach = cur_reach
        next_cells = {(x, z) for (x, yy, z) in solid if yy == y + 1}
        anchors = sum(1 for (x, z) in cur_reach if (x, z) in next_cells)
        details.append({"y": y, "solid": len(cells), "reachable": len(cur_reach),
                        "unreachable": len(unreachable), "anchors": anchors,
                        "unreachableCells": unreachable})
    total_solid = len(solid)
    total_unreachable = sum(d["unreachable"] for d in details)
    return {"totalSolid": total_solid, "totalUnreachable": total_unreachable,
            "anchors": {d["y"]: d["anchors"] for d in details}, "layers": details}


def run_reachability_evidence():
    """在 8 份可评估快照上重算颜色感知接地可达性，并保存逐格明细。"""
    out = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "definition": "见 test_structure_candidates.py 模块注释（逐层 R_y 递归定义）",
           "snapshots": []}
    for case, run_name in SNAPSHOT_CASES:
        try:
            state = _load_snapshot(case, run_name)
        except (OSError, KeyError, ValueError, AssertionError) as exc:
            out["snapshots"].append({"case": case, "evaluable": False,
                                     "reason": f"{type(exc).__name__}: {exc}"})
            continue
        result = color_aware_grounded_reachability(state["model"])
        window = {tuple(c) for c in state["failure"].get("window_cells") or []}
        unreachable = {tuple(c["cell"]) for layer in result["layers"]
                       for c in layer["unreachableCells"]}
        out["snapshots"].append({
            "case": case, "kind": state["failure"]["kind"], "evaluable": True,
            "totalSolid": result["totalSolid"],
            "totalUnreachable": result["totalUnreachable"],
            "failureWindowCells": len(window),
            "windowHitByReachability": len(window & unreachable),
            "windowMissedByReachability": sorted(window - unreachable)[:64],
            "reachabilityOnlyCells": sorted(unreachable - window)[:64],
            "anchors": result["anchors"],
            "layers": result["layers"],
        })
    with open(REACHABILITY_EVIDENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


class ReachabilityExperimentTest(unittest.TestCase):
    """颜色感知接地可达性 + 锚点计数的定义正反例（不接入预检）。"""

    def test_floating_fragment_is_unreachable(self):
        """悬空碎片（下方无接地可达格）判为不可达，原因 no_grounded_below。"""
        model, _p, _a, _f = _state([["#...", "....", "....", "...."],
                                    ["....", "....", "....", "...#"]])
        result = color_aware_grounded_reachability(model)
        unreachable = [c for layer in result["layers"] for c in layer["unreachableCells"]]
        self.assertEqual([tuple(c["cell"]) for c in unreachable], [(3, 1, 3)])
        self.assertEqual(unreachable[0]["reason"], "no_grounded_below")

    def test_color_mixed_cell_is_unreachable(self):
        """只有跨色砖能覆盖的格判为不可达，原因 color_mixed。"""
        model, _p, _a, _f = _state([["#......"], ["###...."]])
        for L in model["layers"]:
            if L["y"] == 1:
                L["colorRows"] = ["RRB...."]
        result = color_aware_grounded_reachability(model)
        unreachable = {tuple(c["cell"]): c["reason"] for layer in result["layers"]
                       for c in layer["unreachableCells"]}
        self.assertEqual(unreachable.get((2, 1, 0)), "color_mixed")

    def test_anchors_count_vertical_contacts(self):
        """锚点计数 = 上下相邻层同时有实体的格数（承托凸点咬合数）。"""
        model, _p, _a, _f = _state([["##", "##"], ["##", ".."]])
        result = color_aware_grounded_reachability(model)
        self.assertEqual(result["anchors"][0], 2, result["anchors"])
        self.assertEqual(result["anchors"][1], 0, result["anchors"])


class _LoopChain(_Chain):
    """带主链求解/成功/修订钩子的链替身，用于验证 fallback.py 的真实接线。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failures = []
        self.revisions_applied = []

    def _solve_current(self):
        sol, failure = self.solve_fn(
            self.model, sorted(self.model["layers"], key=lambda L: L["y"]),
            deadline=time.monotonic() + 30, validate_fn=validate_solution,
            log=lambda s: None, should_stop=self.cancel.is_set)
        return sol, failure

    def _finish_success(self, sol):
        return {"sol": sol, "artifacts": {}}

    def _apply_revision(self, cls, failure):
        self.revisions_applied.append(cls)
        raise AssertionError("接线后结构候选应生效，不应进入 LLM 修订")


class FallbackWiringTest(unittest.TestCase):
    """验证 chain-records 在 fallback.py 的真实接线（class1 / class2 两个入口）。"""

    def test_precheck_class1_hook_applies_model_candidate(self):
        """class1 入口：候选修复预检后返回 None（继续主链），不调用 LLM 修订。"""
        from legogod import fallback
        model, parts, assign, frozen = _overhang_state()
        chain = _LoopChain(model, parts, assign, frozen_cells=frozen)
        out = fallback.precheck_class1(chain)
        self.assertIsNone(out)
        self.assertEqual(precheck_details(chain.model)["errors"], [])
        self.assertEqual(chain.revision, 1, "模型空间候选应产生新版本")
        self.assertEqual(chain.structural_candidates["accepted"], 1)
        self.assertEqual(chain.structural_candidates["results"][0]["space"], "model")
        self.assertEqual(chain.revisions_applied, [], "不得进入 LLM 修订")
        record = fallback.structural_candidate_record(chain)
        self.assertEqual(record["accepted"], 1)
        self.assertEqual(record["attempted"], 1)

    def test_structure_loop_class2_solution_rescue(self):
        """class2 入口：solution 空间候选真实求解救回后直接返回成功产物。"""
        from legogod import fallback
        model, parts, assign, frozen = _state([["##", "##"]])
        chain = _LoopChain(model, parts, assign, frozen_cells=frozen)
        calls = {"n": 0}

        def solve_fn(model, layers, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                return None, {"kind": "disconnected", "message": "注入断连失败",
                              "cells": [(0, 0, 0)], "window_cells": [(0, 0, 0)], "layer": 0}
            return tiler.solve_with_budget(model, layers, **kw)

        chain.solve_fn = solve_fn
        out = fallback.structure_loop(chain)
        self.assertIsInstance(out, dict)
        self.assertIn("sol", out)
        self.assertTrue((out["sol"].get("validation") or {}).get("ok"))
        self.assertEqual(calls["n"], 2, "首次失败 + 候选真实求解各一次")
        self.assertEqual(chain.revision, 0, "solution 空间候选不产生新模型版本")
        self.assertEqual(chain.structural_candidates["accepted"], 1)
        self.assertEqual(chain.structural_candidates["results"][0]["space"], "solution")
        self.assertEqual(chain.revisions_applied, [], "不得进入 LLM 修订")

    def test_env_off_keeps_original_revision_path(self):
        """LEGOGOD_STRUCT_CANDIDATES=off 时 fallback 入口走原修订（行为不变）。"""
        from legogod import fallback
        model, parts, assign, frozen = _overhang_state()
        chain = _LoopChain(model, parts, assign, frozen_cells=frozen)
        old = os.environ.get("LEGOGOD_STRUCT_CANDIDATES")
        os.environ["LEGOGOD_STRUCT_CANDIDATES"] = "off"
        try:
            with self.assertRaises(AssertionError):
                fallback.precheck_class1(chain)  # 走 _apply_revision 占位抛错
        finally:
            if old is None:
                os.environ.pop("LEGOGOD_STRUCT_CANDIDATES", None)
            else:
                os.environ["LEGOGOD_STRUCT_CANDIDATES"] = old
        self.assertEqual(chain.revisions_applied, ["class1"])



if __name__ == "__main__":
    unittest.main()
