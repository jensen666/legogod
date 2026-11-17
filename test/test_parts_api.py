# -*- coding: utf-8 -*-
"""回归测试：/api/parts 零件目录接口。

背景：工坊前端曾硬编码一份缺少斜坡砖的零件目录，导致含斜坡砖的方案（圣诞树/钢琴）
在 3D 视图里 partOf(piece) 取到 undefined 后读 color 崩溃，连带拼装步骤卡在“加载中”。
现在目录由服务端统一提供，这里守住两条不变量：
1) 接口返回与 parts_library.PARTS 完全一致，且斜坡砖带 slope 字段；
2) 公开夹具方案（登记在 test/fixtures/public-fixtures.json）用到的零件都能在目录里
   查到，防止再次出现目录外零件。

方案语料只经公开夹具清单读取（不 glob artifacts/）。清单缺失、条目缺失、文件数不符、
JSON 非法、valid 不为 true 或步骤为空一律硬失败，不允许静默跳过。
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))

from _public_fixtures import fixture_entries, read_json, public_path  # noqa: E402
from legogod.parts_library import PARTS  # noqa: E402

CONSUMER = "test/test_parts_api.py"
EXPECTED_SOLUTION_FILES = 10
EXPECTED_TOTAL_STEPS = 1999
EXPECTED_MIN_DISTINCT_PIECES = 60


def _free_port():
    """取一个当前空闲的本地端口，避免与开发中的服务冲突。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


class PartsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "legogod", "web", str(cls.port)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls.base = "http://127.0.0.1:%d" % cls.port
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                _get_json(cls.base + "/api/parts")
                return
            except Exception:
                time.sleep(0.2)
        cls.proc.terminate()
        raise RuntimeError("测试服务器启动超时")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def test_parts_endpoint_matches_library(self):
        """接口目录必须与 parts_library.PARTS 完全一致，斜坡砖必须带 slope 字段。"""
        api = _get_json(self.base + "/api/parts")
        self.assertEqual({p["id"] for p in api["parts"]}, {p["id"] for p in PARTS})
        for p in api["parts"]:
            if p["id"].startswith("SLOPE_"):
                self.assertIn(p.get("slope"), {"/", "\\", "^", "v"}, "%s 缺少 slope 字段" % p["id"])

    def test_all_solution_pieces_are_in_catalog(self):
        """公开夹具方案里出现的每个零件 id 都必须在目录中，否则前端取不到颜色。"""
        catalog = {p["id"] for p in _get_json(self.base + "/api/parts")["parts"]}
        entries = fixture_entries(type="solution", required_only=True, consumer=CONSUMER)
        # 清单条目数必须与目录中的实际文件数一致，且不得为空集通过。
        self.assertGreaterEqual(len(entries), EXPECTED_SOLUTION_FILES,
                                "公开清单登记的方案夹具不足：%r"
                                % [e["id"] for e in entries])
        solution_dir = os.path.dirname(public_path(entries[0]["path"]))
        actual_files = sorted(name for name in os.listdir(solution_dir)
                              if name.endswith(".json"))
        expected_files = sorted(os.path.basename(e["path"]) for e in entries)
        self.assertEqual(actual_files, expected_files,
                         "方案目录实际文件与公开清单不一致（缺失或清单外文件）")

        missing = {}
        total_steps = 0
        distinct_pieces = set()
        for entry in entries:
            sol = read_json(entry)
            self.assertIs(sol.get("valid"), True, "%s 必须是 valid=true 的有效方案" % entry["id"])
            steps = sol.get("steps") or []
            self.assertGreater(len(steps), 0, "%s 的 steps 不能为空" % entry["id"])
            total_steps += len(steps)
            for step in steps:
                piece = step.get("piece")
                if piece:
                    distinct_pieces.add(piece)
                    if piece not in catalog:
                        missing.setdefault(piece, []).append(os.path.basename(entry["path"]))
        self.assertEqual(total_steps, EXPECTED_TOTAL_STEPS,
                         "公开方案总步数与清单快照不一致（覆盖被削弱）")
        self.assertGreaterEqual(len(distinct_pieces), EXPECTED_MIN_DISTINCT_PIECES,
                                "公开方案覆盖的零件种类过少")
        self.assertEqual(missing, {}, "方案出现目录外零件（3D 视图会缺色）：%r" % missing)


if __name__ == "__main__":
    unittest.main()
