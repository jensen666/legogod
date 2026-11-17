# -*- coding: utf-8 -*-
"""LLM 输出解析的鲁棒性测试（推理模型会出现「长思考截断 / 多个 JSON 连写」）。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod.llm import parse_json  # noqa: E402


class ParseJsonTest(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(parse_json('{"a": 1}'), {"a": 1})

    def test_markdown_fence_and_noise(self):
        text = '好的，输出如下：\n```json\n{"action": "save_design", "args": {}}\n```\n以上。'
        self.assertEqual(parse_json(text)["action"], "save_design")

    def test_multiple_json_objects_takes_first(self):
        """推理模型把两个动作连在一起输出时，应取第一个完整 JSON。"""
        text = '{"action": "save_design", "args": {"x": 1}} {"action": "run_solver", "args": {}}'
        self.assertEqual(parse_json(text), {"action": "save_design", "args": {"x": 1}})

    def test_braces_inside_strings(self):
        text = '{"thought": "用 { } 画轮廓", "action": "plan_design", "args": {"features": ["含 } 的说明"]}}'
        parsed = parse_json(text)
        self.assertEqual(parsed["action"], "plan_design")
        self.assertEqual(parsed["args"]["features"], ["含 } 的说明"])

    def test_invalid_raises(self):
        with self.assertRaises(Exception):
            parse_json("完全没有 JSON")


if __name__ == "__main__":
    unittest.main()
