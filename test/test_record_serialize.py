# -*- coding: utf-8 -*-
"""记账失败不得吞掉任务结果。

覆盖：
set 收成 list；收不掉或落盘失败只记 recordError；worker 只在生成调用没返回时写短错误。
不调用真实模型。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import tiler  # noqa: E402
from legogod.job_service import JobService  # noqa: E402
from legogod.job_store import JobStore  # noqa: E402
from legogod.workflow_artifacts import build_run_record, to_jsonable  # noqa: E402


class _Chain:
    """只提供 build_run_record 读到的字段。"""

    def __init__(self, run_id="rid-keep"):
        self.run_id = run_id
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

    def emit(self, kind, text):
        self.logs.append((kind, text))


class _NoGit:
    def run(self, *args, **kwargs):
        raise OSError("测试不读 git")


class _Odd:
    """json 不能序列化，也不是 set。"""


def _result(run_id):
    return {
        "ok": False,
        "error": "求解失败",
        "failure": {"kind": "disconnected", "cells": {2, 1}},
        "run_id": run_id,
    }


class PublicFailureTest(unittest.TestCase):
    def test_copy_drops_offer_and_leaves_solver_dict(self):
        """对外副本去掉 offer；求解器原字典和没有 offer 的失败都保持原对象。"""
        offer = {"stud_owner": {(1, 2): 0}}
        failure = {"kind": "disconnected", "cells": [(0, 0, 0)], "offer": offer}
        out = tiler.public_failure(failure)
        self.assertNotIn("offer", out)
        self.assertEqual(out["kind"], "disconnected")
        self.assertIs(failure["offer"], offer)
        self.assertEqual(failure["cells"], [(0, 0, 0)])
        plain = {"kind": "coverage"}
        self.assertIs(tiler.public_failure(plain), plain)
        self.assertIs(tiler.public_failure(None), None)


class RecordSerializeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-record-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _build(self, chain, result):
        return build_run_record(chain, result, "一座塔", "fidelity", 30, self.tmp, _NoGit())

    def test_set_becomes_list_and_ids_stay(self):
        """记录和结果里的 set 收成 list，落盘 JSON 不再有 set，run_id / failure 不动。"""
        chain = _Chain("rid-set")
        chain.timeline = [{"tags": {"b", "a"}}]
        result = _result("rid-set")
        original_error = result["error"]
        record = self._build(chain, result)
        self.assertNotIn("recordError", result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["error"], original_error)
        self.assertEqual(result["run_id"], "rid-set")
        self.assertEqual(result["failure"]["kind"], "disconnected")
        self.assertEqual(result["failure"]["cells"], [1, 2])
        self.assertEqual(result["run_record"]["timeline"][0]["tags"], ["a", "b"])
        self.assertEqual(record["runId"], "rid-set")
        self.assertEqual(record["failure"]["kind"], "disconnected")
        path = os.path.join(self.tmp, "run_rid-set.json")
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["timeline"][0]["tags"], ["a", "b"])
        self.assertEqual(loaded["failure"]["cells"], [1, 2])
        self.assertEqual(loaded["runId"], "rid-set")
        self.assertEqual(loaded["error"], "求解失败")
        self.assertTrue(any("set" in text for _kind, text in chain.logs))

    def test_leftover_unserializable_keeps_result(self):
        """set 收完后仍有不能序列化的值：记 recordError，不抛，不把结果换成短错误。"""
        chain = _Chain("rid-odd")
        odd = _Odd()
        chain.timeline = [{"bad": odd}]
        result = {
            "ok": False, "error": "求解失败",
            "failure": {"kind": "disconnected"}, "run_id": "rid-odd", "extra": odd,
        }
        record = self._build(chain, result)
        self.assertEqual(result["recordError"]["type"], "TypeError")
        self.assertIn("serializable", result["recordError"]["message"].lower())
        self.assertIs(result["ok"], False)
        self.assertEqual(result["error"], "求解失败")
        self.assertEqual(result["run_id"], "rid-odd")
        self.assertEqual(result["failure"]["kind"], "disconnected")
        self.assertIs(result["extra"], odd)
        self.assertIs(result["run_record"], record)
        self.assertEqual(record["runId"], "rid-odd")
        self.assertNotEqual(set(result), {"ok", "error"})
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "run_rid-odd.json")))
        self.assertTrue(any(_kind == "error" for _kind, _text in chain.logs))

    def test_tuple_key_writes_without_touching_original(self):
        """坐标元组键收成 JSON 文本后能落盘；原字典仍用元组键，ok/error/run_id 不动。"""
        chain = _Chain("rid-key")
        raw = {"stud_owner": {(1, 2): 3}, "cells": [(0, 1, 2)]}
        result = {
            "ok": False, "error": "求解失败",
            "failure": {"kind": "disconnected", "detail": raw},
            "run_id": "rid-key",
        }
        record = self._build(chain, result)
        self.assertNotIn("recordError", result)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["error"], "求解失败")
        self.assertEqual(result["run_id"], "rid-key")
        self.assertEqual(result["failure"]["kind"], "disconnected")
        self.assertIn((1, 2), raw["stud_owner"])
        self.assertEqual(raw["cells"], [(0, 1, 2)])
        self.assertEqual(result["failure"]["detail"]["stud_owner"]["[1, 2]"], 3)
        self.assertEqual(result["failure"]["detail"]["cells"], [[0, 1, 2]])
        self.assertEqual(record["failure"]["detail"]["stud_owner"]["[1, 2]"], 3)
        path = os.path.join(self.tmp, "run_rid-key.json")
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["failure"]["detail"]["stud_owner"]["[1, 2]"], 3)
        self.assertEqual(loaded["runId"], "rid-key")
        self.assertEqual(loaded["error"], "求解失败")
        self.assertTrue(any("元组键" in text for _kind, text in chain.logs))

    def test_odd_object_still_record_error_beside_tuple_key(self):
        """元组键能收，旁边的自定义对象仍不能序列化：只记 recordError，不改结果身份。"""
        chain = _Chain("rid-mix")
        odd = _Odd()
        chain.timeline = [{"bad": odd}]
        result = {
            "ok": False, "error": "求解失败",
            "failure": {"kind": "disconnected", "stud_owner": {(0, 1): 2}},
            "run_id": "rid-mix", "extra": odd,
        }
        self._build(chain, result)
        self.assertEqual(result["recordError"]["type"], "TypeError")
        self.assertIs(result["extra"], odd)
        self.assertEqual(result["run_id"], "rid-mix")
        self.assertEqual(result["error"], "求解失败")
        self.assertIs(result["ok"], False)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "run_rid-mix.json")))

    def test_oserror_keeps_result(self):
        """落盘 OSError 同样只旁路记录，原来的 ok / error / failure / run_id 还在。"""
        chain = _Chain("rid-disk")
        result = _result("rid-disk")
        real_open = open

        def boom(*args, **kwargs):
            raise OSError("disk full")

        with mock.patch("builtins.open", side_effect=boom):
            record = self._build(chain, result)
        self.assertEqual(result["recordError"]["type"], "OSError")
        self.assertIn("disk full", result["recordError"]["message"])
        self.assertEqual(result["run_id"], "rid-disk")
        self.assertEqual(result["failure"]["kind"], "disconnected")
        self.assertEqual(result["error"], "求解失败")
        self.assertIs(result["ok"], False)
        self.assertEqual(record["runId"], "rid-disk")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "run_rid-disk.json")))
        # 确认补丁没有把 open 留在失败状态
        self.assertIs(open, real_open)


class RunRecordReviewTest(unittest.TestCase):
    """run 记录必须落盘最终评审 review.parsed。

    旧记录没有该字段，导致 E2E 断言拿不到视觉分；新记录必须自带，
    浏览器断言才有真实评审可读（旧记录由断言侧用任务 result.review 补入）。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-review-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _build(self, chain, result):
        return build_run_record(chain, result, "一座塔", "fidelity", 30, self.tmp, _NoGit())

    def test_review_parsed_is_saved(self):
        chain = _Chain("rid-review")
        chain.review_state = {"ok": True, "modelHash": "m" * 64,
                              "parsed": {"scores": {"overall": 4, "proportion": 5},
                                         "missing_features": ["旗杆"]},
                              "sheet": "sheet.png"}
        result = {"ok": True, "run_id": "rid-review", "pieces": 12}
        record = self._build(chain, result)
        self.assertEqual(record["review"]["scores"]["overall"], 4)
        self.assertEqual(record["review"]["missing_features"], ["旗杆"])
        with open(os.path.join(self.tmp, "run_rid-review.json"), encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["review"]["scores"]["overall"], 4)
        self.assertNotIn("sheet", loaded["review"])   # 只落结构化评审，不落大字段

    def test_review_unavailable_is_empty_dict(self):
        """评审不可用/未评审：写入空对象而不是缺字段或伪造分数。"""
        for state in (None, {}, {"ok": False, "error": "多视角渲染不可用"}):
            chain = _Chain("rid-noreview")
            chain.review_state = state
            record = self._build(chain, {"ok": False, "error": "生成失败",
                                         "run_id": "rid-noreview"})
            self.assertIn("review", record)
            self.assertEqual(record["review"], {})

    def test_chain_without_review_state_attr_does_not_raise(self):
        """最小 fake chain 没有 review_state：按无评审处理，不得抛异常。"""
        record = self._build(_Chain("rid-min"), {"ok": False, "run_id": "rid-min"})
        self.assertEqual(record["review"], {})


class _BadDict(dict):
    def get(self, *args, **kwargs):
        raise RuntimeError("get 失败")


class WorkerResultTest(unittest.TestCase):
    """worker 终态与落盘（架构升级后针对独立 JobStore/JobService 重写，断言口径不变）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legogod-worker-")
        self.store = JobStore(self.tmp)
        self.runner = lambda desc, **kw: {"ok": True}
        self.service = JobService(self.store, runner=self._runner, artifacts_dir=self.tmp)

    def _runner(self, *args, **kwargs):
        return self.runner(*args, **kwargs)

    def tearDown(self):
        deadline = time.time() + 3
        while time.time() < deadline:
            with self.store.lock:
                running = any(job.get("status") == "running"
                              for _, job in self.store.items_locked())
            if not running:
                break
            time.sleep(0.01)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self, jid):
        with self.store.lock:
            return self.store.get_locked(jid)

    def _wait(self, jid, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self._job(jid)
            if job is not None and job["status"] != "running":
                return job
            time.sleep(0.01)
        self.fail(f"任务 {jid} 未在 {timeout}s 内结束")

    def test_returned_result_is_not_replaced(self):
        """生成调用已经返回整份结果时，worker 不得改成只有 ok 和 error 的字典。"""
        full = {
            "ok": False, "error": "求解失败", "failure": {"kind": "disconnected"},
            "run_id": "keep-1", "model_path": "model.json",
        }
        self.runner = lambda desc, **kw: full
        jid = self.service.create_job("一座塔")["id"]
        job = self._wait(jid)
        self.assertIs(job["result"], full)
        self.assertEqual(job["status"], "error")
        self.assertEqual(job["result"]["run_id"], "keep-1")
        self.assertIn("failure", job["result"])
        self.assertNotEqual(set(job["result"]), {"ok", "error"})

    def test_no_return_writes_short_internal_error(self):
        """生成调用自己抛出时，才允许短的内部异常，并且没有 run_id。"""
        def raise_error(desc, **kw):
            raise RuntimeError("boom")

        self.runner = raise_error
        jid = self.service.create_job("一座塔")["id"]
        job = self._wait(jid)
        self.assertEqual(job["status"], "error")
        self.assertEqual(set(job["result"]), {"ok", "error"})
        self.assertIs(job["result"]["ok"], False)
        self.assertIn("内部异常", job["result"]["error"])
        self.assertIn("boom", job["result"]["error"])
        self.assertNotIn("run_id", job["result"])

    def test_tuple_key_job_saves_and_dumps_without_mutating(self):
        """历史落盘和查询序列化都能写元组键；内存里的原字典键不变。"""
        raw = {(0, 1): "a"}
        job = {
            "id": "jid-key", "status": "error",
            "logs": [{"kind": "solver", "text": "失败"}], "live": None,
            "result": {"ok": False, "error": "求解失败", "failure": {"stud_owner": raw}},
            "desc": "一座塔", "mode": "fidelity", "retryOf": None,
            "reviewContext": None, "startedAt": 1.0,
        }
        with self.store.lock:
            self.store.put_locked("jid-key", job)
        self.assertTrue(self.store.save())
        self.assertIn((0, 1), raw)
        self.assertIn((0, 1), job["result"]["failure"]["stud_owner"])
        with open(self.store.store_path, encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["jid-key"]["result"]["failure"]["stud_owner"]["[0, 1]"], "a")
        body = json.dumps(to_jsonable({
            "logs": job["logs"], "result": job["result"],
        }), ensure_ascii=False)
        self.assertIn('"[0, 1]"', body)
        self.assertIn((0, 1), raw)

    def test_status_read_failure_keeps_returned_object(self):
        """读 ok / error 再抛异常时，已经返回的对象仍留在任务上，不换成短错误。"""
        bad = _BadDict(ok=True, run_id="stay", error=None, failure={"kind": "x"})
        self.runner = lambda desc, **kw: bad
        jid = self.service.create_job("一座塔")["id"]
        job = self._wait(jid)
        self.assertIs(job["result"], bad)
        self.assertEqual(job["status"], "error")
        self.assertEqual(bad["run_id"], "stay")
        self.assertIn("failure", bad)


if __name__ == "__main__":
    unittest.main()
