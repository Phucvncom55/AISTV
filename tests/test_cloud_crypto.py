# -*- coding: utf-8 -*-
"""Kiểm tra mã hoá dữ liệu cloud (envelope) trong aistv_bot."""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("STV_SKIP_SETUP", "1")
os.environ.setdefault("AISTV_CLOUD", "0")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAH" + "x" * 32)

import aistv_bot as bot  # noqa: E402

TOKEN = "123456789:AAH" + "x" * 32
HISTORY = [
    {"role": "user", "content": "xin chào"},
    {"role": "assistant", "content": "chào bạn"},
]


class CloudCryptoTest(unittest.TestCase):
    def setUp(self):
        self._old_token = bot.BOT_TOKEN
        bot.BOT_TOKEN = TOKEN

    def tearDown(self):
        bot.BOT_TOKEN = self._old_token

    def test_history_round_trip_and_hides_content(self):
        node = bot._seal_node(HISTORY)
        self.assertTrue(bot._is_sealed(node))
        self.assertNotIn("xin chào", json.dumps(node, ensure_ascii=False))
        self.assertEqual(bot._open_node(node), HISTORY)

    def test_parent_map_decrypts_children_and_keeps_legacy(self):
        legacy = [{"role": "user", "content": "dữ liệu cũ"}]
        raw = {"111": bot._seal_node(HISTORY), "222": legacy}
        out = bot._open_node(raw)
        self.assertEqual(out["111"], HISTORY)
        self.assertEqual(out["222"], legacy)       # node thô kiểu cũ giữ nguyên

    def test_wrong_bot_token_cannot_decrypt(self):
        node = bot._seal_node({"a": 1})
        bot.BOT_TOKEN = "987654321:ZZZ" + "y" * 32
        self.assertIsNone(bot._open_node(node))

    def test_tampered_blob_is_rejected(self):
        node = bot._seal_node(HISTORY)
        blob = node["blob"]
        node["blob"] = blob[:-4] + ("AAAA" if blob[-4:] != "AAAA" else "BBBB")
        self.assertIsNone(bot._open_node(node))

    def test_personal_paths(self):
        for path in ("hist/123", "mem/items", "summary/42", "rem", "watch", "/rem/"):
            self.assertTrue(bot._personal_path(path), path)
        for path in ("secrets", "config", "history", ""):
            self.assertFalse(bot._personal_path(path), path)

    def test_seal_none_stays_none(self):
        self.assertIsNone(bot._seal_node(None))

    def test_secrets_round_trip(self):
        data = {"TELEGRAM_BOT_TOKEN": TOKEN, "GEMINI_API_KEY": "AIza-khong-duoc-lo"}
        blob = bot.encrypt_secrets(data)
        self.assertNotIn("AIza-khong-duoc-lo", blob)
        self.assertEqual(bot.decrypt_secrets(blob), data)


if __name__ == "__main__":
    unittest.main()
