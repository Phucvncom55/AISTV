# -*- coding: utf-8 -*-
"""Kiểm tra dựng lời giải dài thành ảnh A4 nhiều trang."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("STV_SKIP_SETUP", "1")
os.environ.setdefault("AISTV_CLOUD", "0")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAH" + "x" * 32)

try:
    import aistv_image as image
except Exception:  # thiếu Pillow → bỏ qua phần dựng ảnh
    image = None

import aistv_bot as bot  # noqa: E402


class PagesPlainTextTest(unittest.TestCase):
    def test_inline_math_becomes_unicode(self):
        out = bot.pages_plain_text(r"Ta có $\frac{a+b}{2}$ và $\angle A = 90^\circ$.")
        self.assertEqual(out, "Ta có (a+b)/2 và ∠A = 90°.")
        self.assertNotIn("$", out)
        self.assertNotIn("\\", out)

    def test_display_math_and_geometry(self):
        out = bot.pages_plain_text(r"$$\triangle ABC,\ AB \parallel CD$$")
        self.assertIn("△ABC", out)
        self.assertIn("AB ∥ CD", out)
        self.assertNotIn("$$", out)

    def test_currency_is_not_math(self):
        out = bot.pages_plain_text("Giá $5 và $7, không phải công thức.")
        self.assertEqual(out, "Giá $5 và $7, không phải công thức.")

    def test_code_blocks_keep_dollar_and_backslash(self):
        src = "```python\nx = \"$5\"\n# \\frac{a}{b}\n```"
        self.assertEqual(bot.pages_plain_text(src), src)

    def test_markdown_bold_and_bullets_survive(self):
        src = "* **Xét** tam giác $ABC$ vuông tại $A$."
        out = bot.pages_plain_text(src)
        self.assertIn("**Xét**", out)
        self.assertTrue(out.startswith("* "))


class RenderPagesTest(unittest.TestCase):
    def setUp(self):
        if image is None:
            self.skipTest("chưa cài Pillow")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_empty_text_is_rejected(self):
        with self.assertRaises(image.ImageError):
            image.render_text_pages("   ")

    def test_single_page_file_and_size(self):
        res = image.render_text_pages("# Câu a\n\nXét tứ giác ADFE, ta có AE = DF = ½AB.",
                                      title="Hình học 9 — Câu 3", out_dir=self.tmp.name)
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["title"], "Hình học 9 — Câu 3")
        self.assertEqual((res["width"], res["height"]), (image.PAGE_W, image.PAGE_H))
        path = Path(res["pages"][0])
        self.assertEqual(path.name, "page-01.png")
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

    def test_title_falls_back_to_first_line(self):
        res = image.render_text_pages("## Câu b — Chứng minh\n\nNội dung ngắn.",
                                      out_dir=self.tmp.name)
        self.assertEqual(res["title"], "Câu b — Chứng minh")

    def test_long_text_paginates_in_order(self):
        body = "\n\n".join(f"**Ý {i}:** Ta có AE ∥ DF nên ADFE là hình bình hành, "
                           f"suy ra AE = DF = ½AB = a với mọi i = {i}." for i in range(1, 90))
        res = image.render_text_pages(body, title="Bài dài", out_dir=self.tmp.name)
        self.assertGreater(res["count"], 1)
        self.assertEqual(len(res["pages"]), res["count"])
        for i, p in enumerate(res["pages"], 1):
            self.assertEqual(Path(p).name, f"page-{i:02d}.png")

    def test_paginate_keeps_heading_with_body(self):
        blocks = image._page_blocks("## Tiêu đề\n\nMột đoạn ngắn.")
        pages = image._page_paginate(image._page_visual(blocks))
        self.assertEqual(len(pages), 1)

    def test_too_many_pages_raise(self):
        old = image.PAGE_MAX
        image.PAGE_MAX = 1
        try:
            body = "\n\n".join(f"Đoạn số {i} " + "chữ " * 80 for i in range(1, 30))
            with self.assertRaises(image.ImageError):
                image.render_text_pages(body, title="Quá dài", out_dir=self.tmp.name)
        finally:
            image.PAGE_MAX = old


if __name__ == "__main__":
    unittest.main()
