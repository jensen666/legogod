# -*- coding: utf-8 -*-
"""公共 API 契约回归。

锁死四件事：
1) 公开字段集合冻结：摘要/详情/分页/无参列表的字段不增不减（新增只能显式追加）；
2) 每个 /api 响应带 X-LEGOGOD-API-Version: 1 与 X-Request-ID，错误体附 requestId；
3) 错误兼容：error 仍是字符串、既有文案与状态码不变，code/requestId 只是附加字段；
4) 旧记录回退：desc 从 run_record 取、mode 从 result/run 记录取、outcome 由状态与评审推导；
5) 移动端事实来源：摘要与详情追加
   modeSource=job|result|run_record|default、outcomeSource=result|derived|none，
   只追加字段、不改变 mode/outcome 既有值，也不进入筛选/分页语义。
"""
import json
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402
from legogod import api_contract as contract  # noqa: E402

SUMMARY_FIELDS = {"id", "status", "name", "slug", "pieces", "desc", "error", "mode",
                  "modeSource", "retryOf", "outcome", "outcomeSource", "startedAt",
                  "grid", "layers", "colors"}
DETAIL_FIELDS = {"id", "status", "live", "logs", "result", "desc", "startedAt", "mode",
                 "modeSource", "outcome", "outcomeSource", "retryOf",
                 "design", "progress", "stage", "views", "thinking"}
PAGE_FIELDS = {"jobs", "total", "page", "pageSize", "pages", "running"}
COMPAT_LIST_FIELDS = {"jobs"}


class ApiContractTest(unittest.TestCase):
    """字段集合、版本头、请求标识与错误兼容。"""

    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture().start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    def setUp(self):
        self.fixture.store.clear()

    # ---------- 字段集合冻结 ----------
    def test_summary_and_detail_field_sets_frozen(self):
        """公开 DTO 字段集合与改造前一致：不擅自新增内部运行字段。"""
        self.fixture.add_job("j1", desc="石桥", mode="fast", startedAt=5.0,
                             result={"ok": True, "name": "石桥", "slug": "stone-bridge",
                                     "pieces": 12, "grid": {"w": 3, "d": 2}, "layers": 2,
                                     "colors": {"红色": 12}, "outcome": "fast_success"})
        _, detail, _ = self.fixture.get_json("/api/job/j1")
        self.assertEqual(set(detail), DETAIL_FIELDS, "详情字段集合被改动")
        _, listing, _ = self.fixture.get_json("/api/jobs")
        row = listing["jobs"][0]
        self.assertEqual(set(row), SUMMARY_FIELDS, "摘要字段集合被改动")
        # 内部运行字段不得进入公开 DTO
        for leaked in ("cancel", "reviewContext", "live"):
            self.assertNotIn(leaked, row)
        self.assertNotIn("cancel", detail)
        self.assertNotIn("reviewContext", detail)
        self.assertEqual(detail["result"]["pieces"], 12)
        # 移动端事实来源字段：显式追加的只增字段，不属于内部运行字段
        self.assertEqual((row["modeSource"], row["outcomeSource"]), ("job", "result"))
        self.assertEqual((detail["modeSource"], detail["outcomeSource"]), ("job", "result"))

    def test_paged_and_compat_list_field_sets(self):
        """无参兼容响应只有 jobs；带分页参数才出现分页字段。"""
        self.fixture.add_job("a1", result={"ok": True, "outcome": "fast_success"})
        _, compat, _ = self.fixture.get_json("/api/jobs")
        self.assertEqual(set(compat), COMPAT_LIST_FIELDS)
        _, page, _ = self.fixture.get_json("/api/jobs?page=1&pageSize=20")
        self.assertEqual(set(page), PAGE_FIELDS)

    def test_create_response_fields(self):
        """创建/重试成功响应只有 id 与 mode。"""
        self.fixture.set_runner(lambda desc, **kw: {"ok": True, "outcome": "fast_success"})
        _, body, _ = self.fixture.post_json("/api/build", {"desc": "塔"})
        self.assertEqual(set(body), {"id", "mode"})
        self.assertEqual(body["mode"], "fidelity")
        self.fixture.add_job("r1", mode="fast", desc="原需求",
                             result={"ok": True, "outcome": "fast_success"})
        _, retried, _ = self.fixture.post_json("/api/retry", {"jobId": "r1"})
        self.assertEqual(set(retried), {"id", "mode"})
        self.assertEqual(retried["mode"], "fast")

    # ---------- 版本头与请求标识 ----------
    def test_api_version_header_on_every_api_response(self):
        """每个 /api 响应（成功与错误）都带契约版本头。"""
        targets = [("/api/health", "GET", None), ("/api/parts", "GET", None),
                   ("/api/jobs", "GET", None), ("/api/job/nope", "GET", None),
                   ("/api/build", "POST", {"desc": ""}), ("/api/nope", "GET", None)]
        for path, method, payload in targets:
            with self.subTest(path=path, method=method):
                status, headers, _ = self.fixture.request(path, method=method, payload=payload)
                self.assertEqual(headers.get("X-LEGOGOD-API-Version"),
                                 str(contract.API_VERSION), path)
                self.assertTrue(headers.get("X-Request-ID"), path)

    def test_request_id_passthrough_and_generation(self):
        """合法 X-Request-ID 被透传；非法值被替换为服务端生成值。"""
        status, headers, _ = self.fixture.request("/api/health",
                                                  headers={"X-Request-ID": "trace-abc_123"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Request-ID"), "trace-abc_123")
        status, headers, body = self.fixture.request(
            "/api/job/missing", headers={"X-Request-ID": "bad id with spaces"})
        self.assertEqual(status, 404)
        rid = headers.get("X-Request-ID")
        self.assertTrue(rid and " " not in rid, f"非法请求标识未被替换：{rid}")
        self.assertEqual(json.loads(body)["requestId"], rid, "错误体 requestId 必须与响应头一致")

    def test_success_response_has_request_id_header(self):
        status, headers, _ = self.fixture.request("/api/parts",
                                                  headers={"X-Request-ID": "rid-success"})
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Request-ID"), "rid-success")

    # ---------- 错误兼容 ----------
    def test_error_shape_keeps_string_error_and_adds_code(self):
        """错误响应保留字符串 error；code/requestId 只是附加字段，不把 error 改成对象。"""
        cases = [
            ("/api/job/nope", "GET", None, 404, "unknown job", contract.ERROR_UNKNOWN_JOB),
            ("/api/build", "POST", {"desc": ""}, 400, "desc 不能为空",
             contract.ERROR_EMPTY_DESC),
            ("/api/build", "POST", {"desc": "x", "mode": "bogus"}, 400,
             "mode 只能是 fast 或 fidelity", contract.ERROR_INVALID_MODE),
            ("/api/retry", "POST", {"jobId": "nope"}, 404, "unknown job",
             contract.ERROR_UNKNOWN_JOB),
            ("/api/jobs?page=abc", "GET", None, 400, None, contract.ERROR_INVALID_PARAMS),
        ]
        for path, method, payload, status_expected, message, code in cases:
            with self.subTest(path=path, method=method):
                status, body, headers = self._json_request(path, method, payload)
                self.assertEqual(status, status_expected)
                self.assertIsInstance(body["error"], str, "error 必须保持字符串")
                if message:
                    self.assertEqual(body["error"], message)
                self.assertEqual(body.get("code"), code)
                self.assertEqual(body.get("requestId"), headers.get("X-Request-ID"))

    def _json_request(self, path, method, payload):
        status, headers, raw = self.fixture.request(path, method=method, payload=payload)
        return status, json.loads(raw.decode("utf-8")), headers

    def test_invalid_jobs_params_400_with_error_text(self):
        """历史查询非法参数：400 + 可读 error 文案（与改造前口径一致）。"""
        for qs, token in (("page=0", "page"), ("pageSize=101", "pageSize"),
                          ("status=bogus", "status"), ("outcome=bogus", "outcome")):
            with self.subTest(qs=qs):
                status, body = self._json_request(f"/api/jobs?{qs}", "GET", None)[:2]
                self.assertEqual(status, 400)
                self.assertIn(token, body["error"])

    # ---------- 旧记录回退 ----------
    def test_legacy_records_fall_back_fields(self):
        """旧库字段回退：desc/mode/outcome/colors/grid/layers 均按既有口径推导。"""
        self.fixture.add_job("old1", status="error", desc=None, startedAt=2.0,
                             result={"ok": False, "error": "失败",
                                     "run_record": {"desc": "主战坦克", "mode": "fast",
                                                    "colors": {"蓝色": 3}}})
        self.fixture.add_job("old2", desc="x", startedAt=1.0,
                             result={"ok": True, "review_failed": True})
        self.fixture.add_job("old3", desc="y", startedAt=3.0, result={"ok": True})
        _, listing, _ = self.fixture.get_json("/api/jobs")
        rows = {row["id"]: row for row in listing["jobs"]}
        self.assertEqual(rows["old1"]["desc"], "主战坦克")
        self.assertEqual(rows["old1"]["mode"], "fast")
        self.assertEqual(rows["old1"]["outcome"], "failed")
        self.assertEqual(rows["old2"]["outcome"], "fidelity_degraded")
        self.assertEqual(rows["old2"]["mode"], "fidelity")
        self.assertEqual(rows["old3"]["outcome"], "fast_success")
        # 来源标志：old1 模式来自 run 记录、结果由状态推导；old2/old3 模式无记录
        self.assertEqual(rows["old1"]["modeSource"], "run_record")
        self.assertEqual(rows["old1"]["outcomeSource"], "derived")
        self.assertEqual(rows["old2"]["modeSource"], "default")
        self.assertEqual(rows["old2"]["outcomeSource"], "derived")
        self.assertEqual(rows["old3"]["modeSource"], "default")
        self.assertEqual(rows["old3"]["outcomeSource"], "derived")
        # 详情同样回退 mode/outcome，且字段集合不变
        _, detail, _ = self.fixture.get_json("/api/job/old1")
        self.assertEqual(detail["mode"], "fast")
        self.assertEqual(detail["modeSource"], "run_record")
        self.assertEqual(detail["outcome"], "failed")
        self.assertEqual(detail["outcomeSource"], "derived")
        self.assertEqual(set(detail), DETAIL_FIELDS)

    def test_job_mode_contract_function(self):
        """job_mode 单源：任务字段 → result.mode → run_record.mode → fidelity。"""
        self.assertEqual(contract.job_mode({"mode": "fast"}), "fast")
        self.assertEqual(contract.job_mode({"result": {"mode": "fast"}}), "fast")
        self.assertEqual(contract.job_mode({"result": {"run_record": {"mode": "fast"}}}),
                         "fast")
        self.assertEqual(contract.job_mode({}), "fidelity")
        self.assertEqual(contract.job_mode({"mode": "bogus"}), "fidelity")
        self.assertEqual(contract.job_mode(None), "fidelity")

    # ---------- 移动端事实来源 ----------
    def test_job_mode_source_contract_function(self):
        """job_mode_source 与 job_mode 同口径：job → result → run_record → default。"""
        cases = [
            # 四种来源
            ({"mode": "fast"}, "job", "fast"),
            ({"result": {"mode": "fidelity"}}, "result", "fidelity"),
            ({"result": {"run_record": {"mode": "fast"}}}, "run_record", "fast"),
            ({}, "default", "fidelity"),
            # 优先级：顶层合法值优先，mode 首尾空白按 job_mode 口径裁剪
            ({"mode": " fast ", "result": {"mode": "fidelity"}}, "job", "fast"),
            ({"mode": "fast", "result": {"run_record": {"mode": "fidelity"}}},
             "job", "fast"),
            # 非法值跳过并继续向后取（与 job_mode 完全一致）
            ({"mode": "bogus", "result": {"mode": "fast"}}, "result", "fast"),
            ({"result": {"mode": "bogus", "run_record": {"mode": "fidelity"}}},
             "run_record", "fidelity"),
            # 非法/空/坏结构一律回退 fidelity 且来源 default
            ({"mode": "bogus"}, "default", "fidelity"),
            ({"mode": ""}, "default", "fidelity"),
            ({"mode": "FAST"}, "default", "fidelity"),
            ({"result": "坏结构"}, "default", "fidelity"),
            ({"result": {"run_record": []}}, "default", "fidelity"),
            (None, "default", "fidelity"),
        ]
        for job, source, mode in cases:
            with self.subTest(job=job):
                self.assertEqual(contract.job_mode_source(job), source)
                # 来源标志不得改变既有 mode 值
                self.assertEqual(contract.job_mode(job), mode)

    def test_job_outcome_source_contract_function(self):
        """job_outcome_source 与 job_outcome 同口径：result → derived → none。"""
        cases = [
            # 显式 outcome：来源 result，即使与状态推导结论相反也不被覆盖
            ({"status": "done", "result": {"outcome": "fast_fallback"}},
             "result", "fast_fallback"),
            ({"status": "error", "result": {"outcome": "fast_success"}},
             "result", "fast_success"),
            ({"status": "cancelled", "result": {"outcome": "fidelity_success"}},
             "result", "fidelity_success"),
            # 旧记录按状态与评审标记推导：来源 derived
            ({"status": "done", "result": {"ok": True}}, "derived", "fast_success"),
            ({"status": "done", "result": {"review_failed": True}},
             "derived", "fidelity_degraded"),
            ({"status": "done", "result": {"review_unavailable": True}},
             "derived", "fidelity_degraded"),
            ({"status": "done", "result": {"review_flag": "review_stale"}},
             "derived", "fidelity_degraded"),
            ({"status": "error", "result": {"ok": False}}, "derived", "failed"),
            ({"status": "cancelled"}, "derived", "cancelled"),
            # 空字符串 outcome 视为未记录，继续按状态推导
            ({"status": "error", "result": {"outcome": ""}}, "derived", "failed"),
            # 无可推导值：来源 none（running/中断/空记录都不伪造交付结论）
            ({"status": "running", "result": None}, "none", None),
            ({"status": "running"}, "none", None),
            ({"status": "interrupted"}, "none", None),
            ({}, "none", None),
            (None, "none", None),
        ]
        for job, source, outcome in cases:
            with self.subTest(job=job):
                self.assertEqual(contract.job_outcome_source(job), source)
                # 来源标志只解释来源，不改变既有 outcome 值（含 None）
                self.assertEqual(contract.job_outcome(job), outcome)
                # 两种口径必须严格对齐：none ⇔ job_outcome 为 None
                self.assertEqual(source == "none", contract.job_outcome(job) is None)

    def test_source_fields_on_summary_and_detail(self):
        """摘要与详情同时下发来源字段，detail 补齐 mode/outcome 且两端口径一致。"""
        self.fixture.add_job("mj", desc="显式", mode="fast", status="done",
                             result={"ok": True, "outcome": "fast_success",
                                     "name": "显式", "pieces": 3})
        self.fixture.add_job("rd", desc="推导", status="done",
                             result={"ok": True, "mode": "fidelity"})
        self.fixture.add_job("rn", desc="运行中", status="running", result=None)
        _, listing, _ = self.fixture.get_json("/api/jobs")
        rows = {row["id"]: row for row in listing["jobs"]}
        self.assertEqual((rows["mj"]["modeSource"], rows["mj"]["outcomeSource"]),
                         ("job", "result"))
        self.assertEqual((rows["rd"]["mode"], rows["rd"]["modeSource"]),
                         ("fidelity", "result"))
        self.assertEqual((rows["rd"]["outcome"], rows["rd"]["outcomeSource"]),
                         ("fast_success", "derived"))
        # 运行中任务：没有交付结论，来源 none，不伪造 outcome
        _, detail_rn, _ = self.fixture.get_json("/api/job/rn")
        self.assertIsNone(detail_rn["outcome"])
        self.assertEqual(detail_rn["outcomeSource"], "none")
        self.assertEqual(detail_rn["modeSource"], "default")
        # 详情与摘要同源：mode/outcome 及其来源逐项一致，既有字段值不变
        _, detail_mj, _ = self.fixture.get_json("/api/job/mj")
        for key in ("id", "mode", "modeSource", "outcome", "outcomeSource"):
            self.assertEqual(detail_mj[key], rows["mj"][key], key)
        self.assertEqual(detail_mj["result"]["pieces"], 3)
        self.assertEqual(detail_mj["desc"], "显式")
        # 所有公开 DTO 都带这两个来源字段
        for body in (rows["mj"], detail_mj):
            self.assertIn("modeSource", body)
            self.assertIn("outcomeSource", body)

    def test_source_flags_for_legacy_and_invalid_records(self):
        """旧记录缺字段/非法枚举/空 outcome：来源标志如实解释，不冒充原始记录。"""
        # 顶层无 mode，result.mode 合法 → result；空字符串 outcome 不算显式记录
        self.fixture.add_job("lg1", desc="旧一", status="done",
                             result={"ok": True, "mode": "fast", "outcome": ""})
        # 顶层非法 mode 被跳过，run 记录合法 → run_record
        self.fixture.add_job("lg2", mode="bogus", desc="旧二", status="error",
                             result={"ok": False, "run_record": {"mode": "fidelity"}})
        # 全部缺失：模式 default（回退 fidelity），outcome 由 cancelled 推导
        self.fixture.add_job("lg3", desc="旧三", status="cancelled")
        # 只有非法 mode 且无其它记录：回退 fidelity 且来源 default
        self.fixture.add_job("lg4", mode="bogus", desc="旧四", status="done",
                             result={"ok": True})
        _, listing, _ = self.fixture.get_json("/api/jobs")
        rows = {row["id"]: row for row in listing["jobs"]}
        self.assertEqual((rows["lg1"]["mode"], rows["lg1"]["modeSource"]),
                         ("fast", "result"))
        # 空字符串 outcome 不算显式记录：done → 推导 fast_success
        self.assertEqual((rows["lg1"]["outcome"], rows["lg1"]["outcomeSource"]),
                         ("fast_success", "derived"))
        self.assertEqual((rows["lg2"]["mode"], rows["lg2"]["modeSource"]),
                         ("fidelity", "run_record"))
        self.assertEqual((rows["lg2"]["outcome"], rows["lg2"]["outcomeSource"]),
                         ("failed", "derived"))
        self.assertEqual((rows["lg3"]["mode"], rows["lg3"]["modeSource"]),
                         ("fidelity", "default"))
        self.assertEqual((rows["lg3"]["outcome"], rows["lg3"]["outcomeSource"]),
                         ("cancelled", "derived"))
        # 非法 mode 回退 fidelity 且来源 default：不把回退值冒充原始记录
        self.assertEqual((rows["lg4"]["mode"], rows["lg4"]["modeSource"]),
                         ("fidelity", "default"))
        # 详情与摘要一致
        _, detail_lg2, _ = self.fixture.get_json("/api/job/lg2")
        self.assertEqual((detail_lg2["mode"], detail_lg2["modeSource"]),
                         ("fidelity", "run_record"))
        self.assertEqual(detail_lg2["outcomeSource"], "derived")
        # 来源标志只做事实解释，不改变筛选语义：推导值仍照常参与 outcome 筛选
        _, page, _ = self.fixture.get_json(
            "/api/jobs?page=1&pageSize=50&outcome=fast_success")
        ids = {row["id"] for row in page["jobs"]}
        self.assertIn("lg1", ids)
        self.assertIn("lg4", ids)
        self.assertNotIn("lg3", ids)

    def test_source_fields_json_serializable(self):
        """来源字段为纯字符串/None：摘要与详情保持 JSON 可序列化。"""
        jobs = [{"id": "s1", "status": "done", "mode": "fast",
                 "result": {"ok": True, "outcome": "fast_success"}},
                {"id": "s2", "status": "running", "result": None},
                {"id": "s3", "status": "done",
                 "result": {"ok": True, "run_record": {"mode": "fast"}}}]
        for job in jobs:
            summary = contract.job_summary(job)
            detail = contract.job_detail(job, job["id"])
            self.assertEqual(json.loads(json.dumps(summary, ensure_ascii=False)), summary)
            self.assertEqual(json.loads(json.dumps(detail, ensure_ascii=False)), detail)
            self.assertIn(summary["modeSource"], ("job", "result", "run_record", "default"))
            self.assertIn(summary["outcomeSource"], ("result", "derived", "none"))
            for key in ("mode", "modeSource", "outcome", "outcomeSource"):
                self.assertEqual(detail[key], summary[key], key)

    def test_parts_payload_matches_library(self):
        """GET /api/parts 与零件库一致（唯一数据源）。"""
        from legogod.parts_library import PARTS
        _, body, _ = self.fixture.get_json("/api/parts")
        self.assertEqual({p["id"] for p in body["parts"]}, {p["id"] for p in PARTS})


if __name__ == "__main__":
    unittest.main()
