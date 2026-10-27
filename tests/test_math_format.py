# -*- coding: utf-8 -*-
"""Kiểm tra quy tắc trình bày Toán/Lý/Hoá/Sinh và đổi LaTeX → Unicode."""
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


class LatexToUnicodeTest(unittest.TestCase):
    def test_geometry_symbols(self):
        out = bot.latex_to_unicode(r"\triangle ABC,\ AB \parallel CD,\ AB \perp BC")
        self.assertIn("△ABC", out)
        self.assertIn("AB ∥ CD", out)
        self.assertIn("AB ⊥ BC", out)

    def test_angles_and_degrees(self):
        self.assertEqual(bot.latex_to_unicode(r"\angle A = 90^\circ"), "∠A = 90°")
        self.assertEqual(bot.latex_to_unicode(r"\widehat{A} = 90^\circ"), "Â = 90°")

    def test_logic_and_relations(self):
        out = bot.latex_to_unicode(r"a \equiv b \Rightarrow c \Leftrightarrow d \neq e")
        self.assertEqual(out, "a ≡ b ⇒ c ⇔ d ≠ e")

    def test_fractions(self):
        self.assertEqual(bot.latex_to_unicode(r"\frac{1}{2}AB"), "½AB")
        self.assertEqual(bot.latex_to_unicode(r"\frac{a+b}{2}"), "(a+b)/2")
        self.assertEqual(bot.latex_to_unicode(r"\dfrac{x}{y}"), "x/y")

    def test_powers_roots_and_sets(self):
        self.assertEqual(bot.latex_to_unicode(r"x^2 + y_1 \le \sqrt{2}"), "x² + y₁ ≤ √2")
        self.assertEqual(bot.latex_to_unicode(r"\sqrt[3]{8}"), "³√(8)")
        self.assertEqual(bot.latex_to_unicode(r"\mathbb{R} \subset \mathbb{C}"), "ℝ ⊂ ℂ")

    def test_escaped_braces_stay_literal(self):
        self.assertEqual(bot.latex_to_unicode(r"\{1,2\}"), "{1,2}")

    def test_chemistry_and_greek(self):
        out = bot.latex_to_unicode(r"2H_2 + O_2 \to 2H_2O")
        self.assertIn("H₂", out)
        self.assertIn("→", out)
        self.assertEqual(bot.latex_to_unicode(r"\alpha + \Delta"), "α + Δ")


class TelegramRenderTest(unittest.TestCase):
    def test_inline_math_converted(self):
        self.assertEqual(bot.md_to_tg_html(r"$\triangle ABC$ có $\angle A = 90^\circ$"),
                         "△ABC có ∠A = 90°")

    def test_display_math_converted(self):
        self.assertEqual(bot.md_to_tg_html(r"$$\frac{a+b}{2}$$"), "(a+b)/2")
        self.assertEqual(bot.md_to_tg_html(r"\[y \perp z\]"), "y ⊥ z")

    def test_math_is_html_escaped(self):
        self.assertEqual(bot.md_to_tg_html(r"$a < b$"), "a &lt; b")

    def test_math_markup_is_not_italic(self):
        self.assertEqual(bot.md_to_tg_html(r"$a_1 * b$"), "a₁ * b")

    def test_code_is_untouched(self):
        out = bot.md_to_tg_html("`$a_1$`\n\n```python\nx = $a_1$\n```")
        self.assertIn('<code>$a_1$</code>', out)
        self.assertIn('x = $a_1$', out)

    def test_currency_is_not_math(self):
        self.assertEqual(bot.md_to_tg_html("Giá $5 và $7 hôm nay"), "Giá $5 và $7 hôm nay")


class PromptRuleTest(unittest.TestCase):
    def test_math_rules_always_in_prompt(self):
        prompt = bot.build_prompt(1, "giải giúp bài hình học này")
        self.assertIn(bot.MATH_STYLE_MD, prompt)
        for phrase in ("Câu a", "Xét / Ta có", "Suy ra", "Kết luận", "∥", "⊥", "△"):
            self.assertIn(phrase, prompt)

    def test_example_solution_renders_without_latex(self):
        sample = (r"**Câu a — Tứ giác ADFE là hình gì?**" "\n"
                  r"* **Xét** tứ giác $ADFE$, ta có $AE \parallel DF$ và "
                  r"$AE = DF = \frac{1}{2}AB = a$." "\n"
                  r"* **Kết luận:** $ADFE$ là **hình vuông**.")
        out = bot.md_to_tg_html(sample)
        self.assertNotIn("\\", out)
        self.assertNotIn("$", out)
        self.assertIn("AE ∥ DF", out)
        self.assertIn("AE = DF = ½AB = a", out)
        self.assertIn("<b>hình vuông</b>", out)


if __name__ == "__main__":
    unittest.main()
