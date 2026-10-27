# -*- coding: utf-8 -*-
"""Kiểm tra đọc/ghi cấu hình dùng chung (aistv_config.py)."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aistv_config as cfg  # noqa: E402

GOOD_TOKEN = "123456789:AAH" + "x" * 32


class EnvTextTest(unittest.TestCase):
    def test_parse_env_text(self):
        text = (
            "\ufeff# ghi chú\n"
            "export GEMINI_API_KEY=AIza123\n"
            'QUOTED="giá trị có dấu cách"\n'
            "SINGLE='abc'\n"
            "WITH_EQUALS=a=b=c\n"
            "1BAD=x\n"
            "KHONGCODAU\n"
            "\n"
        )
        values = cfg.parse_env_text(text)
        self.assertEqual(values["GEMINI_API_KEY"], "AIza123")
        self.assertEqual(values["QUOTED"], "giá trị có dấu cách")
        self.assertEqual(values["SINGLE"], "abc")
        self.assertEqual(values["WITH_EQUALS"], "a=b=c")
        self.assertNotIn("1BAD", values)
        self.assertNotIn("KHONGCODAU", values)

    def test_valid_bot_token(self):
        self.assertTrue(cfg.valid_bot_token(GOOD_TOKEN))
        self.assertTrue(cfg.valid_bot_token("  " + GOOD_TOKEN + "  "))
        self.assertFalse(cfg.valid_bot_token(""))
        self.assertFalse(cfg.valid_bot_token("123:abc"))
        self.assertFalse(cfg.valid_bot_token("rm -rf /"))

    def test_format_value(self):
        self.assertEqual(cfg.format_value("abc"), "abc")
        self.assertEqual(cfg.format_value(""), '""')
        self.assertEqual(cfg.format_value("a b"), '"a b"')
        self.assertEqual(cfg.format_value('a"b'), '"a\\"b"')
        self.assertEqual(cfg.format_value("a#b"), '"a#b"')

    def test_normalize_repo(self):
        cases = {
            "https://github.com/owner/repo": "owner/repo",
            "git@github.com:owner/repo.git": "owner/repo",
            "owner/repo/": "owner/repo",
            "": "",
        }
        for raw, want in cases.items():
            self.assertEqual(cfg.normalize_repo(raw), want, raw)


class EnvFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_write_env_var_keeps_comments_and_replaces_once(self):
        path = self.tmp / "config.env"
        path.write_text("# giữ dòng này\nGEMINI_API_KEY=old\nOTHER=1\n", "utf-8")
        self.assertTrue(cfg.write_env_var(path, "GEMINI_API_KEY", "new value"))
        text = path.read_text("utf-8")
        self.assertIn("# giữ dòng này", text)
        self.assertIn('GEMINI_API_KEY="new value"', text)
        self.assertEqual(text.count("GEMINI_API_KEY="), 1)
        self.assertIn("OTHER=1", text)

    def test_write_env_var_appends_new_key(self):
        path = self.tmp / "config.env"
        self.assertTrue(cfg.write_env_var(path, "NEW_KEY", "v"))
        self.assertIn("NEW_KEY=v", path.read_text("utf-8"))

    def test_read_files_repo_env_wins_over_shared(self):
        repo = self.tmp / "repo"
        shared = self.tmp / "shared"
        (repo / ".env").parent.mkdir(parents=True)
        shared.mkdir()
        (repo / ".env").write_text("AISTV_TEST_ONLY_KEY=repo\n", "utf-8")
        (shared / "config.env").write_text(
            "AISTV_TEST_ONLY_KEY=shared\nSHARED_ONLY=1\n", "utf-8")
        with mock.patch.dict(os.environ, {"AISTV_CONFIG_DIR": str(shared)}), \
                mock.patch("pathlib.Path.home", return_value=self.tmp / "home"):
            values, sources = cfg.read_files(repo)
        self.assertEqual(values["AISTV_TEST_ONLY_KEY"], "repo")
        self.assertEqual(values["SHARED_ONLY"], "1")
        self.assertEqual(sources["AISTV_TEST_ONLY_KEY"], repo / ".env")

    def test_save_values_writes_both_files_and_skips_protected(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        with mock.patch.dict(os.environ, {"AISTV_CONFIG_DIR": str(self.tmp / "cfg")}), \
                mock.patch("pathlib.Path.home", return_value=self.tmp / "home"):
            changed = cfg.save_values(
                {"GEMINI_API_KEY": "AIza123", "TELEGRAM_BOT_TOKEN": GOOD_TOKEN},
                repo=repo, protected=set())
            self.assertEqual(changed, 2)
            repo_env = (repo / ".env").read_text("utf-8")
            shared_env = (self.tmp / "cfg" / "config.env").read_text("utf-8")
            for text in (repo_env, shared_env):
                self.assertIn("GEMINI_API_KEY=AIza123", text)
                self.assertIn("TELEGRAM_BOT_TOKEN=" + GOOD_TOKEN, text)

            again = cfg.save_values(
                {"GEMINI_API_KEY": "AIza-khac"}, repo=repo,
                protected={"GEMINI_API_KEY"})
            self.assertEqual(again, 0)
            self.assertNotIn("AIza-khac", (repo / ".env").read_text("utf-8"))

    def test_save_values_rejects_bad_bot_token(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        with mock.patch.dict(os.environ, {"AISTV_CONFIG_DIR": str(self.tmp / "cfg")}), \
                mock.patch("pathlib.Path.home", return_value=self.tmp / "home"):
            changed = cfg.save_values(
                {"TELEGRAM_BOT_TOKEN": "khong-phai-token"}, repo=repo, protected=set())
        self.assertEqual(changed, 0)
        self.assertFalse((repo / ".env").exists())

    def test_remember_config_token_persists_for_next_run(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        stv = self.tmp / "stv"
        env = {"AISTV_CONFIG_DIR": str(self.tmp / "cfg"), "STV_HOME": str(stv)}
        with mock.patch.dict(os.environ, env), \
                mock.patch("pathlib.Path.home", return_value=self.tmp / "home"), \
                mock.patch.object(cfg, "repo_dir", return_value=repo):
            saved = cfg._remember_config_token("gho_TEST_TOKEN", {})
            values, _ = cfg.read_files(repo)
        self.assertEqual(values.get("AISTV_CONFIG_TOKEN"), "gho_TEST_TOKEN")
        self.assertIn(str(self.tmp / "cfg" / "config.env"), [str(p) for p in saved])
        self.assertEqual((stv / ".secrets" / "github_token").read_text("utf-8").strip(),
                         "gho_TEST_TOKEN")
        self.assertEqual((repo / ".secrets" / "github_token").read_text("utf-8").strip(),
                         "gho_TEST_TOKEN")


if __name__ == "__main__":
    unittest.main()
