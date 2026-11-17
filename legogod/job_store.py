# ============================================================
# 任务存储：
# 任务字典与锁、原子持久化、重启恢复、历史保留上限、线程安全快照。
#
# 锁红线：锁内只做内存读写与最小快照；文件 IO 一律在锁外完成。
# 2026-10-30 现场：Windows ACL 下 tempfile.mkstemp 误判可写并在持锁期间重试数小时，
# 全局锁被占用，/api/build 与 /api/job/* 全部无响应。因此：
#   1) 原子写用显式 O_CREAT|O_EXCL 临时文件 + os.replace，不用 tempfile；
#   2) save() 先在锁内抄快照，锁外写盘，失败只打日志、不影响任务运行。
#
# 本模块不调用 LLM、不知道 HTTP 状态码，也不 import 生成主链。
# ============================================================
import json
import os
import threading
import time
import uuid

from .job_feed import persist_record, restore_record
from .jsonutil import to_jsonable

STORE_FILENAME = "jobs_store.json"
MAX_JOBS_KEPT = 50          # 本地任务历史上限（防 jobs_store 无界增长）
TRIMMABLE_STATUSES = ("done", "error", "interrupted")  # 超限时只丢已完成任务


def atomic_write_json(path, data):
    """JSON 原子写：显式 O_CREAT|O_EXCL 建临时文件，失败立即抛错（不用 tempfile.mkstemp）。

    2026-10-30 现场：Windows ACL 下 mkstemp 误判可写并陷入数十亿次重试，save_jobs 持锁
    4 小时；os.open 失败会立刻抛 PermissionError，让上层快速失败。

    例外（只限最后一步 os.replace）：多个请求线程可能并发保存同一任务历史，Windows 上
    并发替换同一目标偶尔出现共享冲突（PermissionError）；这里做固定 3 次、每次 5ms 的
    有界重试，仍保持「不做无界重试」的红线。创建临时文件失败不重试。
    """
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.005)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class JobStore:
    """任务字典 + 持久化。实例隔离：测试用临时目录构造独立 store，不再改模块全局状态。

    命名约定：带 `_locked` 后缀的方法要求调用方已持有 `self.lock`（复合内存操作要在一个
    锁区间内完成）；不带后缀的方法自己加锁。任务对象本身是可变的，`get_locked` 返回的是
    实时引用，锁外只允许读已完成替换的字段或把它整份序列化。
    """

    def __init__(self, artifacts_dir, store_path=None, max_jobs=MAX_JOBS_KEPT):
        self.artifacts_dir = artifacts_dir
        self.store_path = store_path or os.path.join(artifacts_dir, STORE_FILENAME)
        self.max_jobs = max_jobs
        self.lock = threading.Lock()
        self._jobs = {}

    # ---------- 锁内访问（调用方持锁） ----------
    def get_locked(self, job_id):
        """取任务对象引用（不存在返回 None）。调用方必须已持有 self.lock。"""
        return self._jobs.get(job_id)

    def put_locked(self, job_id, job):
        """写入/替换任务对象。调用方必须已持有 self.lock。"""
        self._jobs[job_id] = job

    def values_locked(self):
        """全部任务对象列表快照。调用方必须已持有 self.lock。"""
        return list(self._jobs.values())

    def items_locked(self):
        """(job_id, job) 列表快照。调用方必须已持有 self.lock。"""
        return list(self._jobs.items())

    def remove_locked(self, job_id):
        """删除任务。调用方必须已持有 self.lock。"""
        self._jobs.pop(job_id, None)

    def trim_locked(self):
        """历史条数上限：超限时丢弃最旧的已完成任务（running/cancelled 保留）。"""
        if len(self._jobs) <= self.max_jobs:
            return
        done = [jid for jid, job in self._jobs.items()
                if job.get("status") in TRIMMABLE_STATUSES]
        done.sort(key=lambda jid: (self._jobs[jid].get("startedAt") or 0))
        for jid in done[:len(self._jobs) - self.max_jobs]:
            self._jobs.pop(jid, None)

    # ---------- 自带锁的便捷方法 ----------
    def __len__(self):
        with self.lock:
            return len(self._jobs)

    def __contains__(self, job_id):
        with self.lock:
            return job_id in self._jobs

    def get(self, job_id):
        """取任务对象引用（加锁访问字典，返回后锁外不再做复合修改）。"""
        with self.lock:
            return self._jobs.get(job_id)

    def clear(self):
        with self.lock:
            self._jobs.clear()

    def count_locked(self):
        """任务数量（调用方持锁时用，避免重入锁）。"""
        return len(self._jobs)

    # ---------- 持久化 ----------
    def _snapshot(self):
        """锁内抄出落盘快照（内存操作，不碰文件）。"""
        with self.lock:
            return {jid: persist_record(job) for jid, job in self._jobs.items()}

    def save(self, terminal=None):
        """任务历史持久化；terminal 可只在快照中预写终态，避免内存状态早于落盘发布。"""
        try:
            data = self._snapshot()
            if terminal is not None:
                job_id, status = terminal
                if job_id in data:
                    data[job_id]["status"] = status
            atomic_write_json(self.store_path, to_jsonable(data))
        except Exception as e:  # noqa: BLE001 - 持久化失败不应影响任务运行
            print(f"[job_store] 任务历史持久化失败（不影响当前任务）：{e}", flush=True)
            return False
        return True

    def load(self):
        """恢复历史任务：补齐 cancel/live；重启前遗留的 running 标记为 interrupted。

        文件不存在/损坏时静默跳过（首启动场景）。返回恢复条数。
        """
        try:
            with open(self.store_path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
            return 0
        if not isinstance(data, dict):
            return 0
        restored = 0
        with self.lock:
            for jid, raw in data.items():
                if not isinstance(raw, dict):
                    continue
                job = restore_record(jid, raw)
                # 重启前没跑完的任务不能继续冒充进行中。
                if job.get("status") == "running":
                    job["status"] = "interrupted"
                job["cancel"] = threading.Event()
                self._jobs[jid] = job
                restored += 1
        return restored
