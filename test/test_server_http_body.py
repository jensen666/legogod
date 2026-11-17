# -*- coding: utf-8 -*-
"""HTTP 请求体消费与连接复用回归（方案 4.3.2 / 12.1：同连接 415→400，超大 body 不无界读取）。

基线证据：错误 Content-Type 请求未消费 body，同一 TCP 连接稳定复现 415→501；
新连接空描述正常返回 400。本测试用进程内真实 HTTP 服务 + http.client/裸 socket
验证真实网络行为，不启动真实外部服务、不触发真实生成任务（第二请求用空描述，端点只回 400）。
"""
import json
import os
import socket
import sys
import time
import unittest
from http.client import HTTPConnection

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import ApiFixture  # noqa: E402


class HttpBodyConsumeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = ApiFixture().start()

    @classmethod
    def tearDownClass(cls):
        cls.fixture.stop()

    @property
    def port(self):
        return self.fixture.port

    def _connection(self, timeout=5):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        self.addCleanup(conn.close)
        return conn

    def _post(self, conn, path, body, ctype="application/json", headers=None):
        hdrs = {"Content-Type": ctype}
        hdrs.update(headers or {})
        conn.request("POST", path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        return resp, data

    def _raw(self, request_bytes, timeout=5):
        """裸 socket 请求，返回 (响应原文, 耗时秒)。用于断言「不无界读取」。"""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        self.addCleanup(sock.close)
        t0 = time.monotonic()
        sock.sendall(request_bytes)
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in b"".join(chunks):
                head = b"".join(chunks).split(b"\r\n\r\n", 1)[0]
                if b"content-length:" not in head.lower():
                    break
                # 头部已齐：按 Content-Length 收满（关闭连接的响应会自然读到 EOF）
                text = b"".join(chunks)
                sep = text.find(b"\r\n\r\n")
                try:
                    need = int(dict(
                        (k.strip().lower(), v.strip())
                        for k, v in (line.split(b":", 1) for line in head.split(b"\r\n")[1:])
                    )[b"content-length"])
                except (KeyError, ValueError):
                    break
                if len(text) - sep - 4 >= need:
                    break
        return b"".join(chunks), time.monotonic() - t0

    @staticmethod
    def _status(raw):
        return int(raw.split(b" ", 2)[1])

    def test_same_connection_415_then_empty_desc_400_not_501(self):
        """同一 TCP 连接：错误 Content-Type（带 body）→ 415；再发空描述 JSON → 400，绝无 501。"""
        conn = self._connection()
        resp, _ = self._post(conn, "/api/build", b'{"desc": "x"}', ctype="text/plain")
        self.assertEqual(resp.status, 415)
        self.assertNotEqual((resp.getheader("Connection") or "").lower(), "close",
                            "合法长度 body 已消费，应保持连接可用")
        # 复用同一 HTTPConnection（同一 socket）：body 若未被消费，这里会被解析成下一请求并 501
        resp2, data2 = self._post(conn, "/api/build", b'{"desc": ""}')
        self.assertEqual(resp2.status, 400, data2)
        self.assertIn("desc", json.loads(data2)["error"])

    def test_same_connection_403_then_400(self):
        """同一连接：跨源 Origin（带 body）→ 403；再发空描述 JSON → 400。"""
        conn = self._connection()
        resp, _ = self._post(conn, "/api/build", b'{"desc": "x"}',
                             headers={"Origin": "http://evil.example.com"})
        self.assertEqual(resp.status, 403)
        resp2, data2 = self._post(conn, "/api/build", b'{"desc": ""}')
        self.assertEqual(resp2.status, 400, data2)

    def test_new_connection_empty_desc_is_400(self):
        """新连接空描述仍返回 400（不因请求体消费逻辑改变业务校验）。"""
        conn = self._connection()
        resp, data = self._post(conn, "/api/build", b'{"desc": ""}')
        self.assertEqual(resp.status, 400)
        self.assertIn("不能为空", json.loads(data)["error"])

    def test_oversized_body_rejected_without_reading(self):
        """超大 Content-Length：立即 413 + Connection: close，不读取/不等待请求体。"""
        raw, elapsed = self._raw(
            b"POST /api/build HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 10485760\r\n\r\n"
        )
        self.assertEqual(self._status(raw), 413, raw[:200])
        lowered = raw.lower()
        self.assertIn(b"connection: close", lowered)
        self.assertLess(elapsed, 3.0, "超大 body 被无界读取/阻塞")
        body = raw.split(b"\r\n\r\n", 1)[1]
        self.assertIn("上限", json.loads(body)["error"])

    def test_invalid_content_length_closes_connection(self):
        """Content-Length 非法（无法安全消费）：400 + Connection: close。"""
        raw, _ = self._raw(
            b"POST /api/build HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\nContent-Length: abc\r\n\r\n"
        )
        self.assertEqual(self._status(raw), 400, raw[:200])
        self.assertIn(b"connection: close", raw.lower())

    def test_chunked_body_cannot_be_consumed_returns_close(self):
        """Transfer-Encoding: chunked 无法安全消费：400 + Connection: close，不无界读取。"""
        raw, elapsed = self._raw(
            b"POST /api/build HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: text/plain\r\nTransfer-Encoding: chunked\r\n\r\n"
        )
        self.assertEqual(self._status(raw), 400, raw[:200])
        self.assertIn(b"connection: close", raw.lower())
        self.assertLess(elapsed, 3.0)

    def test_unknown_post_path_drains_body_and_keeps_connection(self):
        """未匹配 POST 路由也消费 body：404 后同连接请求仍正常解析。"""
        conn = self._connection()
        resp, _ = self._post(conn, "/api/nope", b'{"desc": "x"}')
        self.assertEqual(resp.status, 404)
        resp2, data2 = self._post(conn, "/api/build", b'{"desc": ""}')
        self.assertEqual(resp2.status, 400, data2)

    def test_oversized_json_body_413_before_parse(self):
        """合法 Content-Type 但 body 超过 64KB：413 + 关闭连接，不被当成 JSON 解析。"""
        payload = b'{"desc": "' + b"a" * (64 * 1024) + b'"}'
        raw, elapsed = self._raw(
            b"POST /api/build HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
        )
        self.assertEqual(self._status(raw), 413, raw[:200])
        self.assertIn(b"connection: close", raw.lower())
        self.assertLess(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
