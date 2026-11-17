# ============================================================
# 公共 API 契约单源：
# 对外 DTO、字段兼容、机器可读错误码与 API 版本口径。
#
# 铁律：
#   1) 现有 /api 视为契约版本 1：路径不加 /v1，不重命名、不删除、不改义现有字段；
#   2) 所有 /api 响应体只在本模块组装，内部运行字段不会自动进入公开 DTO；
#   3) error 保持字符串（可附 code/requestId），不得改成对象；
#   4) 新增字段只能追加，调用方不得被迫依赖新字段才能维持原功能。
# 本模块无 HTTP、无 IO、无任务执行逻辑，可被传输层与服务层共同引用。
# ============================================================
from .job_feed import color_distribution, public_view

API_VERSION = 1
API_VERSION_HEADER = "X-LEGOGOD-API-Version"
REQUEST_ID_HEADER = "X-Request-ID"

JOB_STATUSES = ("running", "done", "error", "cancelled", "interrupted")
JOB_OUTCOMES = ("fidelity_success", "fidelity_degraded", "fast_fallback",
                "fast_success", "failed", "cancelled")
HISTORY_PAGE_SIZE = 20
HISTORY_MAX_PAGE_SIZE = 100

# 机器可读错误码：与中文 error 文案并存，只用于调用方分支，不替换既有文案。
ERROR_UNKNOWN_JOB = "unknown_job"
ERROR_EMPTY_DESC = "empty_desc"
ERROR_INVALID_MODE = "invalid_mode"
ERROR_MISSING_DESC = "missing_desc"
ERROR_JOB_RUNNING = "job_running"
ERROR_INVALID_PARAMS = "invalid_params"
ERROR_UNAUTHORIZED = "unauthorized"
ERROR_CROSS_ORIGIN = "cross_origin"
ERROR_CONTENT_TYPE = "content_type"
ERROR_BODY_TOO_LARGE = "body_too_large"
ERROR_BODY_UNCONSUMABLE = "body_unconsumable"
ERROR_BAD_CONTENT_LENGTH = "bad_content_length"
ERROR_BAD_ORIGIN = "bad_origin"
ERROR_NOT_FOUND = "not_found"
ERROR_METHOD_NOT_ALLOWED = "method_not_allowed"


def error_payload(message, code=None, request_id=None):
    """错误响应体：字符串 error 必填，code/requestId 可选追加。"""
    body = {"error": str(message)}
    if code:
        body["code"] = code
    if request_id:
        body["requestId"] = request_id
    return body


# 合法任务模式：与 job_service.JOB_MODES 同一契约口径。本模块是底层契约，
# 不能反向 import 服务层，因此在这里保留一份只读常量。
_MODE_VALUES = ("fast", "fidelity")


def _mode_origin(job):
    """解析有效模式及其来源（job_mode / job_mode_source 共用的唯一口径）。

    优先级：job.mode → result.mode → result.run_record.mode，只认合法值 fast/fidelity；
    全部缺失或非法时回退 ("fidelity", "default")。返回 (mode, source)。
    """
    job = job if isinstance(job, dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    record = result.get("run_record") if isinstance(result.get("run_record"), dict) else {}
    for value, source in ((job.get("mode"), "job"), (result.get("mode"), "result"),
                          (record.get("mode"), "run_record")):
        mode = str(value or "").strip()
        if mode in _MODE_VALUES:
            return mode, source
    return "fidelity", "default"


def job_mode(job):
    """任务真实生成模式：优先任务持久化的 mode，旧记录依次从结果与 run 记录补取。

    两者都缺失时按 API 缺省语义回退 fidelity。
    只用于展示与重试继承，不反写任务字段，避免篡改历史记录。
    """
    return _mode_origin(job)[0]


def job_mode_source(job):
    """模式来源：job|result|run_record|default，与 job_mode 同一优先级和合法值口径。

    default 仅表示“没有可追溯记录”，调用方必须显示“未记录（重试按高保真处理）”，
    不得把回退值冒充原始记录。
    """
    return _mode_origin(job)[1]


def job_outcome(job):
    """历史列表用的交付结果：存量任务没有 outcome 时按状态与评审标记推导。"""
    job = job if isinstance(job, dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    outcome = result.get("outcome")
    if outcome:
        return outcome
    status = job.get("status")
    if status == "cancelled":
        return "cancelled"
    if status == "done":
        flag = result.get("review_flag") or (
            "review_failed" if result.get("review_failed")
            else "review_unavailable" if result.get("review_unavailable") else None)
        return "fidelity_degraded" if flag in (
            "review_failed", "review_unavailable", "review_stale") else "fast_success"
    if status == "error":
        return "failed"
    return None


def job_outcome_source(job):
    """交付结果来源：result|derived|none，与 job_outcome 的取值口径完全一致。

    result：result.outcome 显式非空（真值判定与 job_outcome 相同，空字符串视为未记录）；
    derived：旧记录由 status 与评审标记推导出值（job_outcome 非 None）；
    none：两者都没有（例如 running 状态），调用方必须明确显示“无记录”，
    不得把推导值冒充当次显式交付结论。
    """
    job = job if isinstance(job, dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if result.get("outcome"):
        return "result"
    return "derived" if job_outcome(job) is not None else "none"


def job_summary(job):
    """历史列表/切换器共用的任务摘要（desc 在旧库/重启丢失时回退 run_record 输入快照）。"""
    job = job if isinstance(job, dict) else {}
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    grid = result.get("grid") if isinstance(result.get("grid"), dict) else None
    layers = result.get("layers") if isinstance(result.get("layers"), int) else None
    record = result.get("run_record") if isinstance(result.get("run_record"), dict) else {}
    return {"id": job.get("id"), "status": job.get("status"), "name": result.get("name"),
            "slug": result.get("slug"), "pieces": result.get("pieces"),
            "desc": job.get("desc") or record.get("desc"),
            "error": result.get("error"), "mode": job_mode(job),
            "modeSource": job_mode_source(job), "retryOf": job.get("retryOf"),
            "outcome": job_outcome(job), "outcomeSource": job_outcome_source(job),
            "startedAt": job.get("startedAt"),
            "grid": grid, "layers": layers, "colors": color_distribution(result)}


def job_summaries(jobs):
    """把任务对象列表排成最新在前的摘要列表（内存操作，只读）。"""
    rows = [job_summary(job) for job in jobs or []]
    return sorted(rows, key=lambda x: (x.get("startedAt") or 0, x.get("id")), reverse=True)


def job_list(jobs):
    """无参数 /api/jobs 兼容响应：只有 jobs，没有分页字段。"""
    return {"jobs": job_summaries(jobs)}


PAGING_PARAM_KEYS = ("page", "pageSize", "q", "status", "outcome")


def has_paging_params(params):
    """判断请求是否带分页/筛选参数：决定走兼容全量响应还是分页响应。"""
    return any(key in (params or {}) for key in PAGING_PARAM_KEYS)


def job_detail(job, job_id=None):
    """单任务详情 DTO：现有字段集合冻结，只追加移动端事实来源字段。

    id 优先取 URL 里的任务 ID（与改造前 `{"id": jid, ...}` 行为一致），
    只有未传 job_id 时才回退任务记录自身的 id。
    mode/outcome 及其来源标志与摘要同源，保证两个端点口径一致；
    来源标志只是附加字段，不改变 mode/outcome 既有值，也不引入内部运行字段。
    """
    job = job if isinstance(job, dict) else {}
    body = {"id": job_id or job.get("id"), "status": job.get("status"),
            "live": job.get("live"), "logs": job.get("logs"), "result": job.get("result"),
            "desc": job.get("desc"), "startedAt": job.get("startedAt"),
            "mode": job_mode(job), "modeSource": job_mode_source(job),
            "outcome": job_outcome(job), "outcomeSource": job_outcome_source(job),
            "retryOf": job.get("retryOf")}
    body.update(public_view(job))
    return body


def _one_param(params, key):
    vals = params.get(key) if params else None
    return vals[0].strip() if vals else ""


def _csv_param(params, key, allowed):
    raw = _one_param(params, key)
    if not raw:
        return ()
    vals = tuple(v.strip() for v in raw.split(",") if v.strip())
    bad = next((v for v in vals if v not in allowed), None)
    if bad:
        raise ValueError(f"{key} 含非法值：{bad}")
    return vals


def job_page(jobs, params):
    """带分页参数的 /api/jobs：搜索 + 状态/交付结果筛选 + 服务端分页（running 不占页）。

    非法参数抛 ValueError，由传输层统一转 400。排序与切片语义与改造前逐项一致。
    """
    q = _one_param(params, "q").lower()
    statuses = _csv_param(params, "status", JOB_STATUSES)
    outcomes = _csv_param(params, "outcome", JOB_OUTCOMES)
    try:
        page = int(_one_param(params, "page") or 1)
        size = int(_one_param(params, "pageSize") or HISTORY_PAGE_SIZE)
    except ValueError:
        raise ValueError("page/pageSize 必须是整数")
    if page < 1 or not 1 <= size <= HISTORY_MAX_PAGE_SIZE:
        raise ValueError(f"page 必须 ≥1，pageSize 取 1..{HISTORY_MAX_PAGE_SIZE}")
    # 主列表默认不含 running（进行中专区单独展示），显式 status 时按筛选执行。
    statuses_eff = statuses or tuple(s for s in JOB_STATUSES if s != "running")
    rows = job_summaries(jobs)
    running = [row for row in rows if row["status"] == "running"]
    filtered = [row for row in rows if _row_matches(row, q, statuses_eff, outcomes)]
    total = len(filtered)
    pages = max(1, -(-total // size))
    start = (page - 1) * size
    return {"jobs": filtered[start:start + size], "total": total, "page": page,
            "pageSize": size, "pages": pages, "running": running}


def _row_matches(row, q, statuses, outcomes):
    if statuses and row.get("status") not in statuses:
        return False
    if outcomes and (row.get("outcome") or "") not in outcomes:
        return False
    if q:
        hay = " ".join(x for x in (row.get("id"), row.get("desc"), row.get("name")) if x).lower()
        if q not in hay:
            return False
    return True


def create_job_response(job_id, mode):
    """POST /api/build 与 /api/retry 的成功响应。"""
    return {"id": job_id, "mode": mode}


def cancel_response():
    """DELETE /api/job/<id> 成功响应：取消请求已受理。"""
    return {"cancelling": True}


def parts_payload(parts):
    """GET /api/parts：零件目录唯一数据源。"""
    return {"parts": parts}


def health_payload(status="ok", role=None):
    """GET /api/health：最小健康信息，不含密钥、绝对路径与任务内容。"""
    body = {"ok": status == "ok", "apiVersion": API_VERSION, "status": status}
    if role:
        body["role"] = role
    return body


def error_code_for_status(status):
    """HTTP 状态码 → 通用机器码（具体端点错误优先用显式 code）。"""
    return {400: ERROR_INVALID_PARAMS, 401: ERROR_UNAUTHORIZED, 403: ERROR_CROSS_ORIGIN,
            404: ERROR_NOT_FOUND, 405: ERROR_METHOD_NOT_ALLOWED,
            413: ERROR_BODY_TOO_LARGE}.get(status, "http_error")
