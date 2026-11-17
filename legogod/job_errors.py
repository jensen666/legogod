"""任务服务的可预期业务错误（轻量模块，不依赖生成主链）。

单独成文件的理由（2026-11-15 复核）：传输层 `api_server` 需要捕获 `JobServiceError`，
若从 `job_service` 导入，会顺着 `job_service → fallback → workflow` 把生成编排带入
Web-only 静态进程，违背“静态前端不加载生成主链”的架构目标。异常类型放在这里后，
`api_server` 与 `server` 的静态部署分支都只依赖轻量契约。
"""


class JobServiceError(Exception):
    """服务层可预期的业务错误：携带 HTTP 状态与机器可读错误码，由传输层统一转响应。"""

    def __init__(self, message, code=None, status=400):
        super().__init__(message)
        self.message = str(message)
        self.code = code
        self.status = int(status)
