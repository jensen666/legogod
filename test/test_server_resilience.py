# -*- coding: utf-8 -*-
"""服务端健壮性回归：产物目录不可写时，任务历史持久化必须快速失败且不占用存储锁。

2026-10-30 现场事故：artifacts 目录对服务进程不可写，save 在持有全局锁时调用
tempfile.mkstemp；Windows 上 os.access(目录, W_OK) 不检查 ACL、TMP_MAX 取
os.TMP_MAX = 2**31-1，于是陷入数十亿次 PermissionError 重试，锁被占用 4 小时以上，
/api/build 与 /api/job/* 全部无响应（用户看到「点击开始拼装后卡住」）。

本测试锁死四个回归点（架构升级后针对新的 JobStore/组合根重写，断言口径不变）：
1) 写盘失败必须快速返回（save 不抛、不长时间阻塞）；
2) 文件 IO 期间不得持有存储锁；
3) 持久化不使用 tempfile.mkstemp（避免 Windows ACL 重试循环）；
4) 写盘失败后，走锁的 HTTP 路由（/api/jobs、DELETE）仍能秒回。
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402
from legogod import job_store as lego_store  # noqa: E402
from legogod import server as lego_server  # noqa: E402


class SaveJobsResilienceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-save-")
        self.store = lego_store.JobStore(self.tmp)
        self.store.put_locked("t1", {"id": "t1", "status": "running", "logs": [],
                                    "live": None, "result": None,
                                    "cancel": threading.Event(), "startedAt": 1.0})

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_jobs_fails_fast_and_does_not_hold_lock(self):
        """写盘抛 PermissionError：store.save 不抛、不阻塞，且写盘时存储锁必须空闲。"""
        observed = {}

        def fake_write(path, data):
            # 关键回归：文件 IO 发生时存储锁必须已经释放，否则磁盘/权限异常会占死锁
            acquired = self.store.lock.acquire(blocking=False)
            observed["lock_free_during_io"] = acquired
            if acquired:
                self.store.lock.release()
            raise PermissionError("模拟 artifacts 目录不可写")

        with mock.patch.object(lego_store, "atomic_write_json", fake_write):
            t0 = time.monotonic()
            self.assertFalse(self.store.save())  # 不应抛异常
            elapsed = time.monotonic() - t0
        self.assertTrue(observed.get("lock_free_during_io"), "文件 IO 期间存储锁被占用")
        self.assertLess(elapsed, 1.0, "save 写盘失败时不应长时间阻塞")
        self.assertTrue(self.store.lock.acquire(blocking=False), "save 后存储锁不可用")
        self.store.lock.release()

    def test_save_jobs_no_longer_uses_mkstemp(self):
        """回归 tempfile.mkstemp 的 Windows ACL 无限重试陷阱：持久化不应再调用它。"""
        import tempfile as tf
        called = []

        def fake_mkstemp(*a, **kw):
            called.append(1)
            raise AssertionError("save 不应再使用 tempfile.mkstemp")

        with mock.patch.object(tf, "mkstemp", fake_mkstemp):
            t0 = time.monotonic()
            self.assertTrue(self.store.save())
            elapsed = time.monotonic() - t0
        self.assertEqual(called, [])
        self.assertLess(elapsed, 1.0)
        self.assertTrue(os.path.isfile(self.store.store_path))
        with open(self.store.store_path, encoding="utf-8") as f:
            self.assertIn("t1", json.load(f))

    def test_atomic_write_fails_fast_on_missing_parent(self):
        """目标父目录不存在时立即失败（os.open 直接抛错），不进入重试循环。"""
        bad = os.path.join(self.tmp, "no_such_dir", "x.json")
        t0 = time.monotonic()
        with self.assertRaises(OSError):
            lego_store.atomic_write_json(bad, {"a": 1})
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_ensure_writable_dir_fail_fast(self):
        """启动自检：目录不可写必须 SystemExit（fail-fast），而不是启动后在点击时卡死。"""
        with mock.patch("legogod.server.os.makedirs", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(SystemExit) as ctx:
                lego_server.ensure_writable_dir(os.path.join(self.tmp, "x"), "运行产物")
        self.assertIn("不可写", str(ctx.exception))


class LockRoutesResilienceTest(unittest.TestCase):
    """持久化失败后，走存储锁的路由仍必须可用（不被 IO 拖死）。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture().start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def test_lock_routes_fast_after_save_failure(self):
        """save 写入失败（模拟目录不可写）后，/api/jobs 与 DELETE 必须秒回。"""
        def deny(path, data):
            raise PermissionError("模拟 artifacts 目录不可写")

        with mock.patch.object(lego_store, "atomic_write_json", deny):
            self.assertFalse(self.fixture.store.save())
            t0 = time.monotonic()
            self.assertEqual(self.fixture.get_json("/api/jobs")[0], 200)
            jobs_elapsed = time.monotonic() - t0
            t0 = time.monotonic()
            self.assertEqual(self.fixture.delete_json("/api/job/nonexistent")[0], 404)
            delete_elapsed = time.monotonic() - t0
        self.assertLess(jobs_elapsed, 2.0, "持久化失败后 /api/jobs 被拖慢")
        self.assertLess(delete_elapsed, 2.0, "持久化失败后 DELETE 被拖慢")


if __name__ == "__main__":
    unittest.main()
