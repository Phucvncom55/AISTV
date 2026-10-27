# -*- coding: utf-8 -*-
"""Kiểm tra chế độ khách: phân loại yêu cầu, giới hạn chống spam, tách dữ liệu."""
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("STV_SKIP_SETUP", "1")
os.environ.setdefault("AISTV_CLOUD", "0")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAH" + "x" * 32)

import aistv_bot as bot  # noqa: E402
import aistv_image as image  # noqa: E402
import aistv_web2api as web2api  # noqa: E402


class GuestIntentTest(unittest.TestCase):
    def test_media_kinds(self):
        self.assertEqual(bot.guest_intent("vẽ sơ đồ tư duy về Python"), "mindmap")
        self.assertEqual(bot.guest_intent("mindmap: học tiếng Anh"), "mindmap")
        self.assertEqual(bot.guest_intent("infographic về biến đổi khí hậu"), "infographic")
        self.assertEqual(bot.guest_intent("vẽ biểu đồ doanh thu 2025"), "chart")

    def test_image_and_code(self):
        self.assertEqual(bot.guest_intent("vẽ cho tôi một con mèo"), "image")
        self.assertEqual(bot.guest_intent("tạo ảnh phong cảnh biển"), "image")
        self.assertEqual(bot.guest_intent("viết code python đọc file csv"), "code")
        self.assertEqual(bot.guest_intent("sửa lỗi hàm này giúp mình"), "code")

    def test_plain_chat(self):
        self.assertEqual(bot.guest_intent("giải thích định lý Pytago"), "chat")
        self.assertEqual(bot.guest_intent(""), "chat")

    def test_subject_is_cleaned(self):
        self.assertEqual(bot._guest_subject("vẽ cho tôi một con mèo"), "con mèo")
        self.assertEqual(bot._guest_subject("vẽ sơ đồ tư duy về Python"), "Python")
        self.assertEqual(bot._guest_subject("mindmap: học tiếng Anh"), "học tiếng Anh")
        self.assertEqual(bot._guest_subject("vẽ biểu đồ doanh thu 2025"), "doanh thu 2025")


class GuestLimitTest(unittest.TestCase):
    def test_sliding_window(self):
        limit = bot._WindowLimit(2, 10)
        self.assertEqual(limit.check("u", now=100), 0.0)
        self.assertEqual(limit.check("u", now=101), 0.0)
        self.assertAlmostEqual(limit.check("u", now=102), 8.0)
        self.assertEqual(limit.check("u", now=111), 0.0)

    def test_keys_are_independent(self):
        limit = bot._WindowLimit(1, 60)
        self.assertEqual(limit.check(("chat", 1), now=5), 0.0)
        self.assertGreater(limit.check(("chat", 1), now=6), 0)
        self.assertEqual(limit.check(("chat", 2), now=6), 0.0)

    def test_notice_is_throttled(self):
        bot.GUEST_NOTICE_AT.clear()
        self.assertTrue(bot._guest_notice(("x", 1), gap=30))
        self.assertFalse(bot._guest_notice(("x", 1), gap=30))
        self.assertTrue(bot._guest_notice(("x", 2), gap=30))


class GuestIsolationTest(unittest.TestCase):
    def test_key_separates_user_and_chat(self):
        chat_a = type("Chat", (), {"id": -100})()
        chat_b = type("Chat", (), {"id": -200})()
        user_a = type("User", (), {"id": 1})()
        user_b = type("User", (), {"id": 2})()
        self.assertEqual(bot._guest_key(chat_a, user_a), (-100, 1))
        self.assertNotEqual(bot._guest_key(chat_a, user_a), bot._guest_key(chat_a, user_b))
        self.assertNotEqual(bot._guest_key(chat_a, user_a), bot._guest_key(chat_b, user_a))

    def test_history_is_bounded_and_separate(self):
        old_limit, old_hist = bot.GUEST_HIST_USERS, bot.GUEST_HIST
        bot.GUEST_HIST_USERS, bot.GUEST_HIST = 2, {}
        try:
            for i in range(4):
                bot._guest_hist((-100, i)).append({"role": "user", "content": str(i)})
            self.assertLessEqual(len(bot.GUEST_HIST), 2)
            bot._guest_hist((-100, 9)).append({"role": "user", "content": "riêng"})
            self.assertEqual(bot._guest_hist((-100, 9))[-1]["content"], "riêng")
        finally:
            bot.GUEST_HIST_USERS, bot.GUEST_HIST = old_limit, old_hist

    def test_model_is_per_user(self):
        bot.GUEST_MODEL_BY_USER.clear()
        default = bot._guest_model(1)
        bot.GUEST_MODEL_BY_USER[1] = "gemini-3.6-flash"
        self.assertEqual(bot._guest_model(1), "gemini-3.6-flash")
        self.assertEqual(bot._guest_model(2), default)
        bot.GUEST_MODEL_BY_USER.clear()

    def test_bans(self):
        bot.GUEST_BANS.clear()
        bot.GUEST_BANS[7] = time.time() + 600
        self.assertTrue(bot._guest_banned(7))
        bot.GUEST_BANS[8] = 0.0
        self.assertTrue(bot._guest_banned(8))
        bot.GUEST_BANS[9] = time.time() - 1
        self.assertFalse(bot._guest_banned(9))
        self.assertNotIn(9, bot.GUEST_BANS)
        bot.GUEST_BANS.clear()

    def test_topic_kw_only_for_topics(self):
        plain = type("M", (), {"is_topic_message": False, "message_thread_id": 5})()
        topic = type("M", (), {"is_topic_message": True, "message_thread_id": 5})()
        self.assertEqual(bot._thread_kw(plain), {})
        self.assertEqual(bot._thread_kw(topic), {"message_thread_id": 5})


class GuestImageLinkTest(unittest.TestCase):
    def test_normalize_and_detect(self):
        self.assertEqual(web2api.normalize_image_url("http://googleusercontent.com/a.png"),
                         "https://googleusercontent.com/a.png")
        self.assertTrue(web2api._is_image_url("https://lh3.googleusercontent.com/gg/a.png"))
        self.assertTrue(web2api._is_image_url(
            "https://googleusercontent.com/image_generation_content/0_852"))
        self.assertFalse(web2api._is_image_url("https://example.com/a.png"))
        self.assertFalse(web2api._is_image_url("https://127.0.0.1/a.png"))

    def test_extract_and_strip(self):
        answer = ("Ảnh đây: ![x](https://lh3.googleusercontent.com/gg/a.png) "
                  "và http://googleusercontent.com/image_generation_content/0_852")
        urls = web2api.extract_image_urls(answer)
        self.assertEqual(urls, ["https://lh3.googleusercontent.com/gg/a.png",
                                "https://googleusercontent.com/image_generation_content/0_852"])
        clean = bot._strip_image_links(answer, urls)
        self.assertNotIn("googleusercontent", clean)
        self.assertIn("Ảnh đây:", clean)

    def test_download_rejects_other_hosts_without_network(self):
        raw, mime, err = web2api.download_image("https://example.com/a.png")
        self.assertIsNone(raw)
        self.assertTrue(err)

    def test_guest_provider_order_never_uses_owner_keys(self):
        order = image.provider_order("guest")
        self.assertTrue(set(order) <= {"web2api", "pollinations"})
        self.assertIn("pollinations", order)


class DisplayNameTest(unittest.TestCase):
    def test_provider_labels_are_friendly(self):
        self.assertEqual(bot._provider_label("web2api"), "Gemini")
        self.assertEqual(bot._provider_label("pollinations"), "Miễn phí")
        self.assertEqual(bot._provider_label("ai+pil"), "AI STV")
        self.assertEqual(bot._provider_label("cloudflare"), "Cloudflare")
        self.assertEqual(bot._provider_label("unknown"), "unknown")

    def test_menu_uses_gemini_not_web2api(self):
        names = [name for name, _ in bot.COMMANDS]
        self.assertIn("gemini", names)
        self.assertNotIn("web2api", names)


if __name__ == "__main__":
    unittest.main()
