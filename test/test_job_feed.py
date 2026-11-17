# -*- coding: utf-8 -*-
"""日志分桶、设计稿覆盖、求解进度与落盘语义。"""
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import api_contract as contract  # noqa: E402
from legogod import job_store as lego_store  # noqa: E402
from legogod import tiler  # noqa: E402
from legogod.job_feed import (KEY_KINDS, NOISE_CAP, THINKING_KEEP,  # noqa: E402
                              apply_event, color_distribution, compact_design,
                              fill_missing_colors, fresh_feed, persist_record, public_view,
                              restore_record, truncate_thinking)
from legogod.parts_library import part_for  # noqa: E402


def _house(layer_rows):
    layers = [{"y": y, "rows": list(rows), "color": "红色"} for y, rows in enumerate(layer_rows)]
    solid = sum(r.count("#") for rows in layer_rows for r in rows)
    return {"grid": {"w": len(layer_rows[0][0]), "d": len(layer_rows[0])},
            "layers": layers, "totalVoxels": solid, "name": "块"}


class ThinkingFeedTest(unittest.TestCase):
    """思考通道：实时覆盖 → 完成落盘 → 独立条数上限。"""

    def _job(self):
        return {**fresh_feed(), "logs": [], "live": None}

    def test_live_overwrites_then_done_appends_and_clears(self):
        job = self._job()
        apply_event(job, "thinking", "", {"phase": "plan", "text": "第一段", "elapsed": 1,
                                         "done": False}, now=1)
        apply_event(job, "thinking", "", {"phase": "plan", "text": "第一段第二段", "elapsed": 2,
                                         "done": False}, now=2)
        self.assertEqual(job["thinking"]["text"], "第一段第二段")
        self.assertEqual(job["logs"], [], "未完成的实时思考不进日志")
        apply_event(job, "thinking", "", {"phase": "plan", "text": "第一段第二段", "elapsed": 3,
                                         "done": True}, now=3)
        self.assertIsNone(job["thinking"], "完成后必须清空实时通道，避免轮询搬重复内容")
        self.assertEqual(len(job["logs"]), 1)
        entry = job["logs"][0]
        self.assertEqual(entry["kind"], "thinking")
        self.assertEqual(entry["text"], "第一段第二段")
        self.assertEqual(entry["chars"], 6)
        self.assertFalse(entry["truncated"])
        self.assertFalse(entry["partial"])

    def test_live_channel_keeps_only_tail(self):
        job = self._job()
        text = "头" + "中" * 5000 + "尾"
        apply_event(job, "thinking", "", {"phase": "draw", "text": text, "done": False}, now=1)
        self.assertLessEqual(len(job["thinking"]["text"]), 4000)
        self.assertTrue(job["thinking"]["text"].endswith("尾"))
        self.assertEqual(job["thinking"]["chars"], len(text), "原始字数仍要如实上报")

    def test_partial_flag_survives_cancel(self):
        job = self._job()
        apply_event(job, "thinking", "", {"phase": "solve", "text": "半截推理",
                                         "done": True, "partial": True}, now=1)
        self.assertTrue(job["logs"][0]["partial"])
        self.assertIsNone(job["thinking"])

    def test_tail_cap_does_not_evict_key_events_or_noise(self):
        """思考只受自己的 60 条上限约束：solver 刷满噪音也不挤掉思考，思考也不挤掉关键事件。"""
        job = self._job()
        apply_event(job, "phase", "阶段：plan", {"phase": "plan"}, now=0)
        for i in range(THINKING_KEEP + 5):
            apply_event(job, "thinking", "", {"phase": "plan", "text": f"第 {i} 轮",
                                             "done": True}, now=i + 1)
        for i in range(NOISE_CAP + 20):
            apply_event(job, "solver", f"y={i % 9}", {"phase": "solve"}, now=100 + i)
        kinds = [row["kind"] for row in job["logs"]]
        self.assertEqual(kinds.count("thinking"), THINKING_KEEP,
                         f"思考条数应为 {THINKING_KEEP}，实得 {kinds.count('thinking')}")
        think_texts = [row["text"] for row in job["logs"] if row["kind"] == "thinking"]
        self.assertEqual(think_texts[0], "第 5 轮", "淘汰的是最旧思考")
        self.assertEqual(think_texts[-1], f"第 {THINKING_KEEP + 4} 轮")
        self.assertIn("phase", kinds, "关键事件不得被思考或噪音挤掉")
        self.assertLessEqual(kinds.count("solver"), NOISE_CAP, "噪音仍按自己的配额淘汰")

    def test_long_thinking_truncated_head_and_tail(self):
        body, truncated = truncate_thinking("A" * 9000 + "B" * 9000)
        self.assertTrue(truncated)
        self.assertTrue(body.startswith("A" * 100))
        self.assertTrue(body.endswith("B" * 100))
        self.assertIn("已截断，原文 18000 字", body)
        self.assertLessEqual(len(body), 12000 + 40)
        short, not_trunc = truncate_thinking("短推理")
        self.assertEqual((short, not_trunc), ("短推理", False))

    def test_persist_restore_and_public_view_carry_thinking(self):
        job = self._job()
        apply_event(job, "thinking", "", {"phase": "plan", "text": "已完成的推理",
                                         "done": True}, now=1)
        apply_event(job, "thinking", "", {"phase": "draw", "text": "正在推理",
                                         "done": False}, now=2)
        self.assertIsNotNone(job["thinking"])
        saved = persist_record(job)
        self.assertEqual(saved["thinking"]["text"], "正在推理")
        restored = restore_record("x", saved)
        self.assertIsNone(restored["thinking"], "重启后不存在正在流式的现场")
        self.assertEqual([r["kind"] for r in restored["logs"]], ["thinking"],
                         "已落盘的思考条目照常显示")
        self.assertEqual(public_view(job)["thinking"]["text"], "正在推理")

    def test_empty_thinking_keeps_interface_hidden(self):
        job = self._job()
        apply_event(job, "thinking", "", {"phase": "plan", "text": "", "done": False}, now=1)
        self.assertIsNone(job["thinking"])
        self.assertEqual(job["logs"], [], "空推理不落盘")
        self.assertEqual(public_view(job)["thinking"], None)


class FeedBucketTest(unittest.TestCase):
    def _job(self):
        return {"logs": [], "live": None, "design": None, "progress": None,
                "stage": {"current": None, "seen": [], "revise": 0}, "views": None}

    def test_key_events_survive_noise_flood_in_memory_disk_and_reload(self):
        job = self._job()
        apply_event(job, "phase", "—— 阶段：plan ——", {"phase": "plan"}, now=1)
        apply_event(job, "review", "视觉评审：{}", {"phase": "review", "scores": {"overall": 8}}, now=2)
        apply_event(job, "phase", "—— 阶段：solve ——", {"phase": "solve"}, now=3)
        apply_event(job, "error", "生成失败（support，阶段 solve）：悬空", {"phase": "solve"}, now=4)
        apply_event(job, "result", "完成：块，4 块零件", {"phase": "solve"}, now=5)
        for i in range(800):
            apply_event(job, "solver", f"[tiler] y={i % 9}: 1 块", {"phase": "solve"}, now=10 + i)
        kinds = [row["kind"] for row in job["logs"]]
        for kind in ("phase", "review", "error", "result"):
            self.assertIn(kind, kinds, kind)
        self.assertLess(sum(1 for k in kinds if k == "solver"), 800)
        self.assertTrue(all(row["kind"] in KEY_KINDS or row["kind"] == "solver" for row in job["logs"]))

        saved = persist_record(job)
        self.assertEqual(saved["logs"], job["logs"])  # 落盘不得再截一刀
        restored = restore_record("abc", saved)
        self.assertEqual([row["kind"] for row in restored["logs"]], kinds)
        self.assertEqual(restored["stage"]["current"], "solve")
        self.assertIn("plan", restored["stage"]["seen"])

    def test_design_overwrites_and_stays_out_of_logs(self):
        job = self._job()
        first = _house([["##", "##"]])
        second = _house([["##", "##"], ["#.", ".#"]])
        apply_event(job, "design", "第一稿", {"design": first}, now=1)
        apply_event(job, "design", "第二稿", {"design": second, "revision": 2}, now=2)
        self.assertEqual(job["logs"], [])
        self.assertEqual(len(job["design"]["layers"]), 2)
        self.assertEqual(job["design"]["revision"], 2)
        self.assertNotEqual(compact_design(first)["stamp"], job["design"]["stamp"])
        self.assertIn("红色", job["design"]["palette"])
        self.assertIn("R", job["design"]["chars"])

    def test_progress_overwrites_and_rejects_incomplete(self):
        job = self._job()
        apply_event(job, "progress", "", {"layer": 2, "total": 9, "round": 1, "y": 1}, now=1)
        apply_event(job, "progress", "", {"layer": 3, "total": 9, "round": 1, "y": 2}, now=2)
        apply_event(job, "progress", "", {"layer": "x"}, now=3)
        self.assertEqual(job["progress"], {"layer": 3, "total": 9, "round": 1, "y": 2})
        self.assertEqual(job["logs"], [])

    def test_revise_count_comes_from_phase_events(self):
        job = self._job()
        apply_event(job, "phase", "—— 阶段：revise ——", {"phase": "revise"}, now=1)
        apply_event(job, "info", "修订计数", {"phase": "revise"}, now=2)
        apply_event(job, "phase", "—— 阶段：revise ——", {"phase": "revise"}, now=3)
        self.assertEqual(job["stage"]["revise"], 2)
        self.assertEqual(job["stage"]["seen"].count("revise"), 1)

    def test_color_distribution_empty_when_unsolved(self):
        self.assertIsNone(color_distribution({}))
        self.assertIsNone(color_distribution({"colors": {}}))
        dist = color_distribution({"colors": {"红色": 3, "白色": 1}})
        self.assertEqual(dist[0]["name"], "红色")
        self.assertAlmostEqual(sum(item["share"] for item in dist), 1.0, places=3)
        self.assertTrue(dist[0]["hex"].startswith("#"))

    def test_views_only_when_png_exists(self):
        job = self._job()
        missing = os.path.join(tempfile.gettempdir(), "no-such-sheet.png")
        apply_event(job, "views", "", {"sheet": missing, "views": {"front": missing}}, now=1)
        self.assertIsNone(job["views"])
        folder = tempfile.mkdtemp(prefix="legogod-views-")
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        front = os.path.join(folder, "run_r001_front.png")
        sheet = os.path.join(folder, "run_r001_sheet.png")
        for path in (front, sheet):
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n")
        apply_event(job, "views", "", {"sheet": sheet, "views": {"front": front}}, now=2)
        self.assertEqual(job["views"]["front"], "/views/run_r001_front.png")
        self.assertEqual(job["views"]["sheet"], "/views/run_r001_sheet.png")
        side = os.path.join(folder, "run_r001_side.png")
        with open(side, "wb") as f:
            f.write(b"\x89PNG\r\n")
        again = public_view({"result": {"review_sheet": sheet}, "views": None})
        self.assertEqual(again["views"]["side"], "/views/run_r001_side.png")


class SolutionColorBackfillTest(unittest.TestCase):
    def test_empty_colors_field_uses_explicit_piece_colors(self):
        folder = tempfile.mkdtemp(prefix="legogod-sol-")
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        red = part_for("B2x4", "蓝色")
        self.assertNotEqual(red["id"], red["shape"])
        with open(os.path.join(folder, "solution_demo.json"), "w", encoding="utf-8") as f:
            __import__("json").dump({"colors": {}, "steps": [{"piece": red["id"]}] * 3}, f)
        items = [{"id": "j1", "colors": None}]
        fill_missing_colors(items, {"j1": {"colors": {}, "solution_path": "solution_demo.json"}}, folder)
        self.assertEqual(items[0]["colors"][0]["name"], "蓝色")
        self.assertEqual(items[0]["colors"][0]["count"], 3)

    def test_legacy_default_ids_stay_empty(self):
        folder = tempfile.mkdtemp(prefix="legogod-sol-")
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        legacy = part_for("B1x1", "绿色")
        self.assertEqual(legacy["id"], legacy["shape"])
        with open(os.path.join(folder, "solution_old.json"), "w", encoding="utf-8") as f:
            __import__("json").dump({"colors": {}, "steps": [{"piece": legacy["id"]}]}, f)
        items = [{"id": "old", "colors": None}]
        fill_missing_colors(items, {"old": {"colors": {}, "solution_path": "solution_old.json"}}, folder)
        self.assertIsNone(items[0]["colors"])


class SolverProgressTest(unittest.TestCase):
    def test_progress_is_reported_before_layer_log(self):
        events = []
        house = {"grid": {"w": 2, "d": 2}, "layers": [{"y": 0, "rows": ["##", "##"]}],
                 "totalVoxels": 4, "name": "块"}
        sol, fail = tiler.solve_with_budget(
            house, house["layers"], rounds=1,
            log=lambda text: events.append(("log", text)),
            on_progress=lambda info: events.append(("progress", info)),
        )
        self.assertIsNotNone(sol, fail)
        self.assertEqual(events[0][0], "progress")
        info = events[0][1]
        self.assertEqual(info["layer"], 1)
        self.assertEqual(info["total"], 1)
        self.assertEqual(info["round"], 1)
        self.assertLess(0, next(i for i, item in enumerate(events) if item[0] == "log"))


class FeedHttpTest(unittest.TestCase):
    """馈送字段的落盘/恢复与历史摘要（架构升级后针对独立 JobStore 实例重写）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-feed-")
        self.store = lego_store.JobStore(self.tmp)

    def tearDown(self):
        __import__("shutil").rmtree(self.tmp, ignore_errors=True)

    def test_summary_and_reload_keep_colors_and_logs(self):
        job = {"id": "c1", "status": "done", "logs": [], "live": None, "result": {
            "ok": True, "name": "小屋", "pieces": 4, "layers": 1,
            "grid": {"w": 2, "d": 2}, "colors": {"红色": 4},
        }, "desc": "小屋", "startedAt": 3.0, "cancel": threading.Event()}
        apply_event(job, "result", "完成", {"phase": "solve"}, now=4)
        with self.store.lock:
            self.store.put_locked("c1", job)
        self.assertTrue(self.store.save())
        self.store.clear()
        self.assertEqual(self.store.load(), 1)
        loaded = self.store.get("c1")
        self.assertEqual(loaded["logs"][0]["kind"], "result")
        summary = contract.job_summary(loaded)
        self.assertEqual(summary["colors"][0]["name"], "红色")
        self.assertEqual(summary["grid"]["w"], 2)
        self.assertEqual(summary["layers"], 1)
        self.assertIsNotNone(loaded["cancel"])


if __name__ == "__main__":
    unittest.main()
