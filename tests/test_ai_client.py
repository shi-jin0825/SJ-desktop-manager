# -*- coding: utf-8 -*-
"""ai_client 单元测试：验证不崩、兜底文案、请求体构造、响应解析。

运行：
    python -m unittest tests.test_ai_client -v
"""
import json
import os
import unittest

from core import ai_client


class TestApiKey(unittest.TestCase):
    def test_missing_key_returns_friendly(self):
        os.environ.pop("ZHIPU_API_KEY", None)
        r = ai_client.ask_ai("你好")
        self.assertIn("API Key", r)   # 返回友好提示而非崩溃

    def test_env_key_is_read(self):
        os.environ["ZHIPU_API_KEY"] = "test-key"
        self.assertEqual(ai_client._api_key(), "test-key")


class TestBody(unittest.TestCase):
    def test_build_body_shape(self):
        body = ai_client._build_body("问题", "系统提示")
        self.assertEqual(body["model"], "glm-4-flash")
        msgs = body["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": "系统提示"})
        self.assertEqual(msgs[1], {"role": "user", "content": "问题"})


class TestExtract(unittest.TestCase):
    def test_extract_answer(self):
        payload = {"choices": [{"message": {"content": "答案"}}]}
        self.assertEqual(ai_client._extract_answer(payload), "答案")

    def test_extract_empty(self):
        self.assertEqual(ai_client._extract_answer({"choices": []}), "")


class TestNetworkFallback(unittest.TestCase):
    def test_fake_key_returns_auth_hint(self):
        os.environ["ZHIPU_API_KEY"] = "fake-key"
        # 假 Key 会触发 401，走 HTTPError 分支返回鉴权提示，不抛异常
        r = ai_client.ask_ai("你好")
        self.assertIn("Key", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
