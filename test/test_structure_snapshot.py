# -*- coding: utf-8 -*-
"""结构失败快照：全量窗口才可评估，截断格子不补齐。

对应方案在历史快照不足时只补运行记录、不猜测缺失输入。
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.workflow_artifacts import build_run_record, structure_snapshot  # noqa: E402


class _Chain:
    def __init__(self):
        self.run_id = "snap1"
        self.draft = None
        self.best_draft = None
        self.gate_errors = []
        self.counts = {}
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
        self.revision = 1
        self.review_flag = None
        self.track = "ops"
        self.artifacts = {}
        self.logs = []
        self.cores_frozen = True
        self.frozen_cells = {(0, 0, 0)}
        self.ops = [{"op": "box", "x": 0, "y": 0, "z": 0, "w": 2, "d": 2, "h": 1}]
        self.model = {
            "grid": {"w": 4, "d": 4}, "name": "塔",
            "layers": [
                {"y": 0, "rows": ["##..", "....", "....", "...."],
                 "cells": [[0, 0], [1, 0]]},
                {"y": 1, "rows": ["....", "....", "....", "...."], "cells": []},
            ],
        }
        self.parts_norm = [{
            "id": "tower", "cells": {(0, 0, 0), (1, 0, 0)},
            "core_cells": {(0, 0, 0)},
        }]

    def emit(self, kind, text):
        self.logs.append((kind, text))


class _NoGit:
    def run(self, *args, **kwargs):
        raise OSError("测试不读 git")


class StructureSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-snap-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_full_window_is_evaluable_and_allowed_not_guessed_from_prompt_cells(self):
        """有 window_cells、算子、冻结核心和部位时，allowedCells 非空且可评估。"""
        chain = _Chain()
        result = {
            "ok": False, "error": "断连", "run_id": "snap1",
            "failure": {"kind": "disconnected", "stage": "solve", "failure": {
                "kind": "disconnected", "message": "不连通", "layer": 0,
                "cells": [(0, 0, 0)],
                "window_cells": [(0, 0, 0), (0, 0, 1)],
            }},
        }
        record = build_run_record(chain, result, "一座塔", "fidelity", 30, self.tmp, _NoGit())
        snap = record["structureSnapshot"]
        self.assertTrue(snap["evaluable"])
        self.assertFalse(snap["cellsTruncated"])
        self.assertEqual(snap["windowCells"], [[0, 0, 0], [0, 0, 1]])
        self.assertGreater(len(snap["allowedCells"]), 0)
        self.assertIn([0, 0, 0], snap["frozenCells"])
        self.assertEqual(snap["opCount"], 1)
        self.assertEqual(snap["parts"][0]["id"], "tower")
        self.assertTrue(snap["modelHash"])

    def test_truncated_prompt_without_window_is_not_evaluable(self):
        """只有被截断的提示格、没有 window_cells 时，不计算 allowedCells。"""
        chain = _Chain()
        cells = [(i % 4, 0, i // 4) for i in range(64)]
        result = {
            "ok": False, "error": "支撑不足", "run_id": "snap1",
            "failure": {"kind": "support", "failure": {
                "kind": "support", "message": "支撑不足", "layer": 0, "cells": cells,
            }},
        }
        snap = structure_snapshot(chain, result)
        self.assertFalse(snap["evaluable"])
        self.assertTrue(snap["cellsTruncated"])
        self.assertIsNone(snap["allowedCells"])
        self.assertIsNone(snap["windowCells"])
        self.assertIn("没有全量窗口", snap["unevaluableReason"])
        self.assertTrue(any("不可评估" in text for _k, text in chain.logs))

    def test_precheck_window_is_the_full_error_cells(self):
        """预检把全量 error_cells 写成 window_cells 后，快照可评估，且不用另一份截断提示。"""
        chain = _Chain()
        full = [(0, 0, 0), (1, 0, 0), (2, 1, 0)]
        result = {
            "ok": False, "error": "支撑不足", "run_id": "snap1",
            "failure": {"kind": "support", "stage": "revise", "failure": {
                "kind": "support", "message": "支撑不足", "layer": None,
                "cells": full, "window_cells": full,
            }},
        }
        snap = structure_snapshot(chain, result)
        self.assertTrue(snap["evaluable"])
        self.assertEqual(snap["windowCells"], [[0, 0, 0], [1, 0, 0], [2, 1, 0]])
        self.assertIsNone(snap["unevaluableReason"])
        self.assertIn([2, 1, 0], snap["allowedCells"])

    def test_coverage_layer_uses_whole_layer_not_prompt_cells(self):
        """有层号的覆盖失败：窗口是该层全部实体格，允许范围是整层，64 个提示格不算窗口。"""
        chain = _Chain()
        prompt = [(i % 4, 0, i // 4) for i in range(64)]
        result = {
            "ok": False, "error": "铺不满", "run_id": "snap1",
            "failure": {"kind": "coverage", "failure": {
                "kind": "coverage", "message": "72 格铺不满", "layer": 0, "cells": prompt,
            }},
        }
        snap = structure_snapshot(chain, result)
        self.assertTrue(snap["evaluable"])
        self.assertFalse(snap["cellsTruncated"])
        self.assertEqual(snap["windowCells"], [[0, 0, 0], [1, 0, 0]])
        self.assertEqual(len(snap["promptCells"]), 64)
        self.assertEqual(len(snap["allowedCells"]), 4 * 4)
        self.assertTrue(all(cell[1] == 0 for cell in snap["allowedCells"]))
        self.assertNotEqual(snap["windowCells"], snap["promptCells"])

    def test_coverage_without_layer_is_not_evaluable(self):
        """覆盖失败没有层号时，截断提示格不能当成整层。"""
        chain = _Chain()
        cells = [(i % 4, 0, min(i // 4, 3)) for i in range(64)]
        result = {
            "ok": False, "error": "预算用尽", "run_id": "snap1",
            "failure": {"kind": "coverage", "failure": {
                "kind": "coverage", "message": "求解时间预算在本轮内用尽",
                "layer": None, "cells": cells,
            }},
        }
        snap = structure_snapshot(chain, result)
        self.assertFalse(snap["evaluable"])
        self.assertIsNone(snap["windowCells"])
        self.assertIsNone(snap["allowedCells"])
        self.assertIn("没有层号", snap["unevaluableReason"])

    def test_suspension_lock_cells_are_not_expanded_to_the_model(self):
        """悬吊只把已记录的锁扣坐标当作窗口，不扩成整模。"""
        chain = _Chain()
        result = {
            "ok": False, "error": "锁扣不足", "run_id": "snap1",
            "failure": {"kind": "suspension", "failure": {
                "kind": "suspension", "message": "只有 1 个锁扣凸点", "layer": None,
                "cells": [], "window_cells": [(3, 1, 0)],
            }},
        }
        snap = structure_snapshot(chain, result)
        self.assertTrue(snap["evaluable"])
        self.assertEqual(snap["windowCells"], [[3, 1, 0]])
        self.assertEqual(snap["allowedCells"], [[3, 1, 0]])

    def test_suspension_without_positions_states_why(self):
        """悬吊失败没有坐标时不可评估，原因写在快照里。"""
        chain = _Chain()
        result = {
            "ok": False, "error": "锁扣不足", "run_id": "snap1",
            "failure": {"kind": "suspension", "failure": {
                "kind": "suspension", "message": "y=4 层附近只有 1 个锁扣凸点",
                "layer": None, "cells": [],
            }},
        }
        snap = structure_snapshot(chain, result)
        self.assertFalse(snap["evaluable"])
        self.assertIsNone(snap["windowCells"])
        self.assertIn("不猜测补齐", snap["unevaluableReason"])

    def test_non_structural_failure_has_no_snapshot(self):
        chain = _Chain()
        self.assertIsNone(structure_snapshot(chain, {"failure": {"kind": "protocol"}}))

    def test_precheck_exhaustion_records_full_window(self):
        """修订停在预检时，失败对象带上全量 error_cells，不把格子丢掉。"""
        from legogod.revision_policy import RevisionBudgetExhausted, solve_after_revision_exhausted
        from legogod.workflow import GenerationFailure

        chain = _Chain()
        chain.parts_norm = None
        chain.model = {
            "grid": {"w": 4, "d": 4}, "name": "悬",
            "layers": [
                {"y": 0, "rows": ["#...", "....", "....", "...."]},
                {"y": 1, "rows": ["..#.", "....", "....", "...."]},
            ],
        }
        exhausted = RevisionBudgetExhausted("class1", {}, "结构修订请求打满")
        with self.assertRaises(GenerationFailure) as caught:
            solve_after_revision_exhausted(chain, exhausted, GenerationFailure)
        info = caught.exception.info
        self.assertEqual(info["stoppedBecause"], "precheck")
        window = [tuple(c) for c in info["failure"]["window_cells"]]
        self.assertIn((2, 1, 0), window)
        self.assertEqual(info["failure"]["cells"], info["failure"]["window_cells"])
