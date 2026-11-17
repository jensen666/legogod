# -*- coding: utf-8 -*-
"""测试共享装置。

本文件只放"测试侧"的公共帮助函数/基类，不引入生产行为：
- validate_plan：生产已删除 `agent.validate_design` 这个仅测试使用的兼容入口，
  测试侧用 `validate_design_syntax` + `precheck_details` 等价复现（语义逐行对齐，
  校验口径不变），避免把测试专用死路径留在生产包里。
- resp / Script / PhaseChat / real_solve：脚本化模型响应、按尝试阶段切换脚本与真实
  求解器注入的公共装置。原先在 test_cancel.py 等 9 个测试文件中各存一份，逐份对比
  （AST 归一化后）确认可等价收敛于此：Script 统一记录 calls(kwargs) 与 snapshots
  （消息文本快照），PhaseChat 统一记录 all_messages（完整消息列表）。
- IsolatedArtifactsTest：把产物目录与 3D 可视化目录隔离到临时目录的测试基类，
  原先在 8 个测试文件中各存一份；额外提供 `_art()` 拼临时产物绝对路径。
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from legogod import tiler, workflow  # noqa: E402
from legogod.agent import precheck_details, validate_design_syntax  # noqa: E402


def validate_plan(plan):
    """语法/尺寸校验 + 设计预检两段合一（等价于已删除的 agent.validate_design）。

    返回 (errs, model, warns)：
    - 语法/尺寸错误：model=None，errs 为语法错误；
    - 预检错误：model=None，errs 为预检错误（与旧实现一致，不回填 unsupportedVoxels）；
    - 通过：errs=[]，model 回填 unsupportedVoxels 后返回。
    """
    errs, model, warns = validate_design_syntax(plan)
    if errs:
        return errs, None, warns
    detail = precheck_details(model)
    model["unsupportedVoxels"] = len(detail["error_cells"])
    if detail["errors"]:
        return detail["errors"], None, warns
    return [], model, warns


def resp(obj, requests=1):
    """把模型回复对象包成 chat_fn 期望的响应 dict（requests=本次请求计费次数）。"""
    return {"content": json.dumps(obj, ensure_ascii=False), "reasoning_content": "",
            "finish": "stop", "requests": requests}


class Script:
    """按脚本回放模型响应；记录每次调用的 kwargs 与消息内容快照。"""

    def __init__(self, *responses):
        self.items = list(responses)
        self.calls = []
        self.snapshots = []

    def __call__(self, messages, **kw):
        self.calls.append(kw)
        self.snapshots.append([str(m.get("content") or "") for m in messages])
        if not self.items:
            raise AssertionError("发生了脚本之外的模型调用")
        return self.items.pop(0)


class PhaseChat:
    """按尝试阶段切换脚本：上一个脚本的响应耗尽后自动进入下一个（模拟两次 run_generation）。

    all_messages 记录每次调用时的完整消息列表，用于断言评审意见注入与原始需求不变。
    """

    def __init__(self, *scripts):
        self.scripts = [s if isinstance(s, Script) else Script(*s) for s in scripts]
        self.i = 0
        self.all_messages = []

    def __call__(self, messages, **kw):
        while self.i < len(self.scripts) and not self.scripts[self.i].items:
            self.i += 1
        if self.i >= len(self.scripts):
            raise AssertionError("发生了脚本之外的模型调用（保底次数失控）")
        self.all_messages.append([dict(m) for m in messages])
        return self.scripts[self.i](messages, **kw)


def real_solve(model, layers, **kw):
    """真实求解器 tiler.solve_with_budget：注入 solve_fn 时保证求解走真实链路。"""
    return tiler.solve_with_budget(model, layers, **kw)


class IsolatedArtifactsTest(unittest.TestCase):
    """把产物与运行记录隔离到临时目录，不污染真实 artifacts/。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-test-")
        self.viz_tmp = tempfile.mkdtemp(prefix="legogod-test-viz-")
        patcher_a = mock.patch.object(workflow, "ARTIFACTS_DIR", self.tmp)
        patcher_v = mock.patch.object(workflow, "VIZ_DIR", self.viz_tmp)
        patcher_a.start()
        patcher_v.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_v.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.viz_tmp, ignore_errors=True))

    def _art(self, name):
        """临时产物目录下的绝对路径（供各测试读取产物文件）。"""
        return os.path.join(self.tmp, name)


class ApiFixture:
    """进程内真实 HTTP 夹具：独立 JobStore/JobService + 可注入 runner + 真连接。

    架构升级后测试不再清空模块级全局状态，而是每个夹具一份独立 store/service：
    - role="combo"：Web 静态 + API（缺省，等于现有组合部署）；
    - role="api"：只有 API，不读取 Web 应用壳；
    - role="web"：只有静态资源，不持有任务状态（需要 api_base_url）。
    runner 默认注入「立即返回成功」的可控实现，需要捕获调用时用 set_runner 替换。
    """

    def __init__(self, *, role="combo", runner=None, token="", allowed_origins=(),
                 api_base_url="", artifacts_dir=None, viz_dir=None, web_dir=None,
                 store_path=None):
        self.tmp = tempfile.mkdtemp(prefix="legogod-api-")
        self.viz_tmp = tempfile.mkdtemp(prefix="legogod-api-viz-")
        self.artifacts_dir = artifacts_dir or self.tmp
        self.viz_dir = viz_dir or self.viz_tmp
        self.web_dir = web_dir
        self.store_path = store_path or os.path.join(self.tmp, "jobs_store.json")
        self.role = role
        self.token = token
        self.allowed_origins = tuple(allowed_origins)
        self.api_base_url = api_base_url
        self.runner = runner if runner is not None else _ok_runner
        self.app = None
        self.base = ""

    # ---------- 生命周期 ----------
    def start(self):
        from legogod.server import AppConfig, create_application
        config = AppConfig(role=self.role, host="127.0.0.1", port=0,
                           api_base_url=self.api_base_url, api_token=self.token,
                           allowed_origins=self.allowed_origins,
                           artifacts_dir=self.artifacts_dir, viz_dir=self.viz_dir,
                           store_path=self.store_path)
        if self.web_dir is not None:
            config.web_dir = self.web_dir
        self.app = create_application(config)
        if self.app.service is not None:
            self.app.service.runner = self.runner
        thread = __import__("threading").Thread(target=self.app.serve_forever, daemon=True)
        thread.start()
        self.base = f"http://127.0.0.1:{self.app.httpd.server_address[1]}"
        return self

    def stop(self):
        if self.app is not None:
            self.app.shutdown()
            self.app = None
        for path in (self.tmp, self.viz_tmp):
            shutil.rmtree(path, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False

    # ---------- 装置访问 ----------
    @property
    def store(self):
        return self.app.store

    @property
    def service(self):
        return self.app.service

    @property
    def port(self):
        return self.app.httpd.server_address[1]

    def set_runner(self, runner):
        """替换生成 runner（测试用可控实现，生产始终是真实 run_with_fallback）。"""
        self.app.service.runner = runner
        self.runner = runner

    def add_job(self, job_id, **fields):
        """直接写入任务记录（模拟历史库/旧记录），返回任务对象。"""
        job = {"id": job_id, "status": "done", "logs": [], "live": None, "result": None,
               "desc": None, "startedAt": 1.0,
               "cancel": __import__("threading").Event()}
        job.update(fields)
        with self.store.lock:
            self.store.put_locked(job_id, job)
        return job

    # ---------- HTTP ----------
    def request(self, path, method="GET", payload=None, headers=None, body=None,
                timeout=10):
        """发一个真实 HTTP 请求，返回 (status, headers(dict), body bytes)。"""
        import urllib.error
        import urllib.request
        data = body
        hdrs = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.base + path, method=method, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def get(self, path, headers=None):
        return self.request(path, headers=headers)

    def get_json(self, path, headers=None):
        status, headers, body = self.request(path, headers=headers)
        try:
            return status, json.loads(body.decode("utf-8")), headers
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, {"_raw": body}, headers

    def post_json(self, path, payload, headers=None):
        status, headers, body = self.request(path, method="POST", payload=payload,
                                             headers=headers)
        try:
            return status, json.loads(body.decode("utf-8")), headers
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, {"_raw": body}, headers

    def delete_json(self, path, headers=None):
        status, headers, body = self.request(path, method="DELETE", headers=headers)
        try:
            return status, json.loads(body.decode("utf-8")), headers
        except (UnicodeDecodeError, json.JSONDecodeError):
            return status, {"_raw": body}, headers

    def wait_status(self, job_id, statuses, timeout=5.0, headers=None):
        """等任务进入给定状态之一；超时抛 AssertionError。"""
        import time
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            status, job, _ = self.get_json(f"/api/job/{job_id}", headers=headers)
            last = job
            if status == 200 and job.get("status") in statuses:
                return job
            time.sleep(0.03)
        raise AssertionError(f"任务 {job_id} 未在 {timeout}s 内进入 {statuses}：{last}")


def _ok_runner(desc, interactive=False, log=None, cancel=None, mode="fidelity",
               review_context=None, **kw):
    """夹具默认 runner：不调用真实模型，立即返回一次成功结果。"""
    return {"ok": True, "outcome": "fidelity_success", "name": desc,
            "pieces": 1, "mode": mode}

