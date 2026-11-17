# ============================================================
# 任务应用服务：
# 创建、详情、历史查询、取消、重试、worker 生命周期与 runner 注入。
#
# 依赖方向：job_service → job_store / 公共契约（纯 DTO）/ 被注入的 runner。
# 不解析 HTTP 请求、不写 socket、不 import HTTP Handler；并发模型保持「每任务独立线程、
# 独立 cancel 事件、独立日志缓冲」，不引入全局串行队列。
# ============================================================
import threading
import time
import uuid

from . import api_contract as contract
from .fallback import review_context_from_result, run_with_fallback
from .job_errors import JobServiceError
from .job_feed import apply_event, color_snapshots, fill_missing_colors, fresh_feed

JOB_MODES = ("fast", "fidelity")
DEFAULT_MODE = "fidelity"   # API 缺省语义（仅为兼容既有调用方）
DETAIL_FIELDS = ("id", "status", "live", "logs", "result", "desc", "startedAt",
                 "mode", "retryOf", "design", "progress", "stage", "views", "thinking")

__all__ = ["JOB_MODES", "DEFAULT_MODE", "JobService", "JobServiceError"]


class JobService:
    """任务应用服务。store 与 runner 都通过构造参数注入，测试可独立实例化、可注入可控 runner。"""

    def __init__(self, store, runner=None, artifacts_dir=None):
        self.store = store
        self.runner = runner or run_with_fallback
        self.artifacts_dir = artifacts_dir or getattr(store, "artifacts_dir", None)

    # ---------- 对外接口 ----------
    def create_job(self, desc, mode=DEFAULT_MODE):
        """新建任务并启动后台 worker；返回 {"id","mode"}。空描述/非法模式拒绝。"""
        mode = str(mode or "").strip() or DEFAULT_MODE
        if mode not in JOB_MODES:
            raise JobServiceError("mode 只能是 fast 或 fidelity",
                                  contract.ERROR_INVALID_MODE, 400)
        text = str(desc or "").strip()
        if not text:
            raise JobServiceError("desc 不能为空", contract.ERROR_EMPTY_DESC, 400)
        job_id = self._start_job(text, mode=mode)
        print(f"[job_service] 创建任务 {job_id} mode={mode}", flush=True)
        return contract.create_job_response(job_id, mode)

    def get_job(self, job_id):
        """单任务详情 DTO；不存在返回 None。锁内只抄顶层快照，IO 与序列化在锁外。"""
        with self.store.lock:
            job = self.store.get_locked(job_id)
            if job is None:
                return None
            snapshot = {key: job.get(key) for key in DETAIL_FIELDS}
        return contract.job_detail(snapshot, job_id)

    def query_jobs(self, params):
        """历史任务查询：无分页参数返回全量兼容结构；带参数返回分页结构。"""
        paged = contract.has_paging_params(params)
        with self.store.lock:
            jobs = self.store.values_locked()
            data = (contract.job_page(jobs, params) if paged
                    else contract.job_list(jobs))
            snapshots = color_snapshots({job.get("id"): job for job in jobs},
                                        list(data.get("jobs") or [])
                                        + list(data.get("running") or []))
        # 补色需要读已落盘的方案文件：必须在锁外完成。
        fill_missing_colors(data.get("jobs"), snapshots, self.artifacts_dir)
        fill_missing_colors(data.get("running"), snapshots, self.artifacts_dir)
        return data

    def cancel_job(self, job_id):
        """取消任务：立即标记取消（前端马上看到），worker 返回不得覆盖；未知任务返回 None。"""
        with self.store.lock:
            job = self.store.get_locked(job_id)
            if job is not None:
                event = job.get("cancel")
                if event is None:
                    event = threading.Event()
                    job["cancel"] = event
                event.set()
                if job.get("status") == "running":
                    job["status"] = "cancelled"
                    job["result"] = {"ok": False, "error": "已由用户取消",
                                     "outcome": "cancelled"}
                    job["live"] = None
        # 响应与持久化都在锁外：锁内只做内存状态变更，避免任何 IO 拖住全局锁。
        if job is None:
            return None
        self.store.save()
        print(f"[job_service] 取消任务 {job_id}", flush=True)
        return contract.cancel_response()

    def retry_job(self, job_id):
        """手动重试：按原任务模式创建新任务，高保真继承有效视觉评审意见。"""
        with self.store.lock:
            original = dict(self.store.get_locked(job_id) or {})
        if not original:
            raise JobServiceError("unknown job", contract.ERROR_UNKNOWN_JOB, 404)
        if original.get("status") == "running":
            raise JobServiceError("任务仍在进行中，结束后才能重试",
                                  contract.ERROR_JOB_RUNNING, 400)
        desc = _original_desc(original)
        if not desc:
            raise JobServiceError("原任务缺少需求描述，无法重试",
                                  contract.ERROR_MISSING_DESC, 400)
        # 手动重试必须继承原任务模式：不得把快速任务静默改成高保真。
        mode = contract.job_mode(original)
        result = original.get("result") if isinstance(original.get("result"), dict) else {}
        review_context = review_context_from_result(result)
        new_id = self._start_job(desc, mode=mode, retry_of=job_id,
                                 review_context=review_context)
        print(f"[job_service] 重试任务 {job_id} -> {new_id} mode={mode}", flush=True)
        return contract.create_job_response(new_id, mode)

    # ---------- worker 生命周期 ----------
    def _start_job(self, desc, mode=DEFAULT_MODE, retry_of=None, review_context=None):
        """创建任务记录并启动后台线程（并发生成，每任务独立线程与取消事件）。"""
        job_id = uuid.uuid4().hex[:8]
        job = {"id": job_id, "status": "running", "logs": [], "live": None, "result": None,
               "desc": desc, "mode": mode, "retryOf": retry_of,
               "reviewContext": review_context,
               "startedAt": round(time.time(), 3), "cancel": threading.Event(), **fresh_feed()}
        with self.store.lock:
            self.store.put_locked(job_id, job)
            self.store.trim_locked()
        self.store.save()
        threading.Thread(target=self.run_worker, args=(job,), daemon=True).start()
        return job_id

    def run_worker(self, job):
        """执行生成；先在持久化快照写终态，再向调用方发布终态，避免保存竞态。"""
        returned, result, error = False, None, None
        terminal_status = None
        try:
            try:
                result = self.runner(job["desc"], interactive=False, log=self._event_callback(job),
                                     cancel=job["cancel"],
                                     mode=job.get("mode") or DEFAULT_MODE,
                                     review_context=job.get("reviewContext"))
                returned = True
            except Exception as e:  # noqa: BLE001 - 内部异常转任务失败，不让线程静默死掉
                error = e
            with self.store.lock:
                # 用户已取消的任务：状态与结果都保持取消接口写入的（绝不回覆盖）。
                if job.get("status") != "cancelled":
                    if not returned:
                        job["result"] = {"ok": False, "error": f"内部异常: {error}"}
                        terminal_status = "error"
                    else:
                        job["result"] = result
                        ok, cancelled = _result_flags(result)
                        terminal_status = "done" if ok else ("cancelled" if cancelled else "error")
        finally:
            with self.store.lock:
                if terminal_status is None:
                    terminal_status = job.get("status") if job.get("status") != "running" else "error"
                job["live"] = None
                self.store.trim_locked()
            self.store.save(terminal=(job["id"], terminal_status))
            with self.store.lock:
                job["status"] = terminal_status
            print(f"[job_service] 任务 {job.get('id')} 结束：{job.get('status')}", flush=True)

    def _event_callback(self, job):
        """生成主链回调：日志、设计稿、进度、评审图分通道写入（需持锁）。"""
        def cb(kind, text, meta=None):
            with self.store.lock:
                apply_event(job, kind, text, meta)
        return cb


def _original_desc(original):
    """重试原文：优先任务顶层 desc，旧库回退 result.run_record.desc。"""
    desc = original.get("desc")
    if not desc:
        result = original.get("result") if isinstance(original.get("result"), dict) else {}
        record = result.get("run_record") if isinstance(result.get("run_record"), dict) else {}
        desc = record.get("desc")
    return str(desc or "").strip()


def _result_flags(result):
    """把生成结果映射成 (ok, cancelled)；结构异常时按失败处理，不抛二次异常。"""
    try:
        ok = isinstance(result, dict) and bool(result.get("ok"))
        cancelled = isinstance(result, dict) and (
            result.get("status") == "cancelled" or "取消" in str(result.get("error", "")))
    except Exception:  # noqa: BLE001 - 结果结构再怪也不能让 worker 线程崩掉
        return False, False
    return ok, cancelled
