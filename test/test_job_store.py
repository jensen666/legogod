# -*- coding: utf-8 -*-
"""任务存储回归。

锁死的红线：
1) 原子写：显式临时文件 + os.replace，成功后不留临时文件，失败不留残骸；
2) 锁外 IO：save 先锁内抄快照，写盘时不持有存储锁；
3) 恢复：重启前 running 标记 interrupted，live/thinking 实时通道置空，cancel 补齐；
4) 历史保留：默认 50 条上限，超限只丢最旧已完成任务，running/cancelled 保留；
5) 实例隔离：不同 store 实例互不影响（测试不再清空模块级全局状态）；
6) 损坏/缺失文件不崩溃。
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from legogod import job_store as module  # noqa: E402
from legogod.job_store import JobStore, atomic_write_json  # noqa: E402


def _job(job_id, status="done", started_at=1.0, **fields):
    job = {"id": job_id, "status": status, "logs": [], "live": None, "result": None,
           "desc": f"需求{job_id}", "startedAt": started_at,
           "cancel": threading.Event()}
    job.update(fields)
    return job


class AtomicWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-store-")
        self.path = os.path.join(self.tmp, "jobs_store.json")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_json_and_leaves_no_temp_files(self):
        atomic_write_json(self.path, {"a": 1})
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"a": 1})
        leftovers = [name for name in os.listdir(self.tmp) if name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_missing_parent_fails_fast(self):
        import time
        bad = os.path.join(self.tmp, "missing", "x.json")
        started = time.monotonic()
        with self.assertRaises(OSError):
            atomic_write_json(bad, {"a": 1})
        self.assertLess(time.monotonic() - started, 1.0, "父目录缺失时不应进入重试循环")

    def test_serializes_sets_and_tuples_via_store(self):
        """store.save 负责把 set/tuple 收成可落盘结构（原子写只接受已序列化数据）。"""
        tmp = tempfile.mkdtemp(prefix="legogod-atomic-")
        try:
            store = JobStore(tmp)
            with store.lock:
                store.put_locked("s1", _job("s1", status="done",
                                            result={"cells": {(1, 2, 3)},
                                                    "window": ((1, 2), (3, 4))}))
            self.assertTrue(store.save())
            with open(store.store_path, encoding="utf-8") as f:
                raw = f.read()
            self.assertIn("cells", raw)
            store.clear()
            self.assertEqual(store.load(), 1)
            with store.lock:
                self.assertEqual(store.get_locked("s1")["result"]["cells"], [[1, 2, 3]])
                self.assertEqual(store.get_locked("s1")["result"]["window"], [[1, 2], [3, 4]])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class SaveLoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-store-")
        self.store = JobStore(self.tmp)
        with self.store.lock:
            self.store.put_locked("a1", _job("a1", live="生成中",
                                             design={"layers": []},
                                             progress={"layer": 1, "total": 2, "round": 1}))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_snapshot_excludes_runtime_only_fields(self):
        self.assertTrue(self.store.save())
        with open(self.store.store_path, encoding="utf-8") as f:
            data = json.load(f)
        record = data["a1"]
        self.assertNotIn("cancel", record, "锁/事件对象不得落盘")
        self.assertIn("status", record)
        self.assertIn("startedAt", record)
        self.assertIn("design", record)
        self.assertIn("progress", record)

    def test_save_does_not_hold_lock_during_io(self):
        observed = {}
        original = module.atomic_write_json

        def spy(path, payload):
            observed["lock_free"] = self.store.lock.acquire(blocking=False)
            if observed["lock_free"]:
                self.store.lock.release()
            return original(path, payload)

        with mock.patch.object(module, "atomic_write_json", spy):
            self.assertTrue(self.store.save())
        self.assertTrue(observed.get("lock_free"), "文件 IO 期间持有存储锁")

    def test_save_failure_returns_false_and_keeps_memory(self):
        with mock.patch.object(module, "atomic_write_json",
                               side_effect=PermissionError("不可写")):
            self.assertFalse(self.store.save())
        with self.store.lock:
            self.assertIsNotNone(self.store.get_locked("a1"))

    def test_load_marks_running_as_interrupted_and_clears_live_channels(self):
        with self.store.lock:
            self.store.put_locked("r1", _job("r1", status="running", live="流式中",
                                            thinking={"text": "推理中", "done": False}))
        self.store.save()
        reloaded = JobStore(self.tmp)
        self.assertEqual(reloaded.load(), 2)
        with reloaded.lock:
            job = reloaded.get_locked("r1")
        self.assertEqual(job["status"], "interrupted")
        self.assertIsNone(job["live"])
        self.assertIsNone(job["thinking"])
        self.assertIsNotNone(job["cancel"])
        with reloaded.lock:
            self.assertEqual(reloaded.get_locked("a1")["status"], "done")

    def test_load_missing_or_corrupt_file_is_safe(self):
        missing = JobStore(os.path.join(self.tmp, "no_dir"))
        self.assertEqual(missing.load(), 0)
        corrupt_path = os.path.join(self.tmp, "corrupt.json")
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(JobStore(self.tmp, store_path=corrupt_path).load(), 0)
        with open(corrupt_path, "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        self.assertEqual(JobStore(self.tmp, store_path=corrupt_path).load(), 0)

    def test_round_trip_preserves_task_fields(self):
        review_context = {"reviewAvailable": False, "failureSummary": "失败类别 protocol"}
        with self.store.lock:
            self.store.put_locked("f1", _job("f1", status="error", mode="fast",
                                             retryOf="orig1",
                                             reviewContext=review_context,
                                             startedAt=9.5,
                                             stage={"current": "solve", "seen": ["plan"],
                                                    "revise": 1},
                                             views={"front": "/views/a.png"},
                                             result={"ok": False, "error": "x"}))
        self.store.save()
        reloaded = JobStore(self.tmp)
        reloaded.load()
        with reloaded.lock:
            job = reloaded.get_locked("f1")
        self.assertEqual(job["mode"], "fast")
        self.assertEqual(job["retryOf"], "orig1")
        self.assertEqual(job["reviewContext"], review_context)
        self.assertEqual(job["startedAt"], 9.5)
        self.assertEqual(job["stage"]["current"], "solve")
        self.assertEqual(job["views"], {"front": "/views/a.png"})


class TrimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-trim-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_limit_keeps_50_newest_done(self):
        store = JobStore(self.tmp)
        with store.lock:
            for index in range(60):
                store.put_locked(f"j{index:02d}",
                                 _job(f"j{index:02d}", started_at=float(index)))
            store.trim_locked()
            self.assertEqual(store.count_locked(), 50)
            kept = {jid for jid, _ in store.items_locked()}
        self.assertNotIn("j00", kept)
        self.assertNotIn("j09", kept)
        self.assertIn("j10", kept)
        self.assertIn("j59", kept)

    def test_running_and_cancelled_are_not_trimmed(self):
        store = JobStore(self.tmp, max_jobs=3)
        with store.lock:
            store.put_locked("r1", _job("r1", status="running", started_at=0.1))
            store.put_locked("c1", _job("c1", status="cancelled", started_at=0.2))
            for index in range(5):
                store.put_locked(f"d{index}", _job(f"d{index}", started_at=float(index) + 1))
            store.trim_locked()
            ids = {jid for jid, _ in store.items_locked()}
        self.assertIn("r1", ids)
        self.assertIn("c1", ids)
        self.assertEqual(len(ids), 3)
        self.assertIn("d4", ids, "最旧已完成先被裁，最新保留")

    def test_custom_limit(self):
        store = JobStore(self.tmp, max_jobs=2)
        with store.lock:
            for index in range(5):
                store.put_locked(f"x{index}", _job(f"x{index}", started_at=float(index)))
            store.trim_locked()
            self.assertEqual(store.count_locked(), 2)


class IsolationTest(unittest.TestCase):
    def test_two_stores_do_not_share_state(self):
        tmp_a = tempfile.mkdtemp(prefix="legogod-iso-a-")
        tmp_b = tempfile.mkdtemp(prefix="legogod-iso-b-")
        try:
            store_a = JobStore(tmp_a)
            store_b = JobStore(tmp_b)
            with store_a.lock:
                store_a.put_locked("a", _job("a"))
            self.assertEqual(len(store_a), 1)
            self.assertEqual(len(store_b), 0)
            self.assertIsNone(store_b.get("a"))
            self.assertNotEqual(store_a.store_path, store_b.store_path)
        finally:
            import shutil
            shutil.rmtree(tmp_a, ignore_errors=True)
            shutil.rmtree(tmp_b, ignore_errors=True)

    def test_lock_is_usable_after_operations(self):
        tmp = tempfile.mkdtemp(prefix="legogod-iso-")
        try:
            store = JobStore(tmp)
            with store.lock:
                store.put_locked("a", _job("a"))
            self.assertTrue(store.save())
            self.assertEqual(store.load(), 1, "load 返回文件中的记录数（重复恢复同 id 覆盖）")
            self.assertEqual(len(store), 1, "重复 load 不产生重复任务")
            self.assertTrue(store.lock.acquire(blocking=False))
            store.lock.release()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
