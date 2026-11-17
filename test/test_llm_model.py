# -*- coding: utf-8 -*-
"""对话模型必须由用户显式配置（公开版不内置任何第三方模型默认值）。"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from legogod import llm  # noqa: E402


class DefaultModelTest(unittest.TestCase):
    def test_no_builtin_model_default(self):
        """代码里不写死第三方模型名：未配置 LEGOGOD_MODEL 时 _default_model 返回空串。"""
        self.assertEqual(llm.MODEL_DEFAULT, "")
        env_without_model = {k: v for k, v in os.environ.items() if k != "LEGOGOD_MODEL"}
        llm._CONFIG = None
        try:
            with mock.patch.dict(os.environ, env_without_model, clear=True), \
                    mock.patch.object(llm, "_load_env", lambda *a, **k: None):
                self.assertEqual(llm._default_model(), "")
        finally:
            llm._CONFIG = None

    def test_configured_model_is_used(self):
        """配置 LEGOGOD_MODEL 后，请求体与 _default_model 都使用该模型名。"""
        llm._CONFIG = None
        try:
            with mock.patch.dict(os.environ, {"LEGOGOD_MODEL": "my-model"}, clear=True), \
                    mock.patch.object(llm, "_load_env", lambda *a, **k: None):
                self.assertEqual(llm._default_model(), "my-model")
        finally:
            llm._CONFIG = None

    def test_missing_model_fails_with_actionable_error(self):
        """只配了地址与密钥、没配模型时，真正发请求前给出可操作错误，不静默用错模型。"""
        llm._CONFIG = None
        try:
            env = {"LEGOGOD_BASE_URL": "https://api.example.com/v1",
                   "LEGOGOD_API_KEY": "<YOUR_API_KEY>"}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(llm, "_load_env", lambda *a, **k: None), \
                    self.assertRaises(RuntimeError) as ctx:
                llm.config()
            self.assertIn("LEGOGOD_MODEL", str(ctx.exception))
        finally:
            llm._CONFIG = None


if __name__ == "__main__":
    unittest.main()
