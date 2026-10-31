# -*- coding: utf-8 -*-
"""Kiểm tra blob khởi động Firebase (aistv_boot.py) + bootstrap.sh đi kèm."""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aistv_boot as boot  # noqa: E402

BOOT_SH = ROOT / "bootstrap.sh"
BOT = "123456789:AAH" + "x" * 32


class CryptoTest(unittest.TestCase):
    def test_roundtrip(self):
        blob = boot.boot_encrypt({"TELEGRAM_BOT_TOKEN": BOT})
        self.assertNotIn(BOT, blob)
        self.assertEqual(boot.boot_decrypt(blob)["TELEGRAM_BOT_TOKEN"], BOT)

    def test_wrong_key_fails(self):
        blob = boot.boot_encrypt({"TELEGRAM_BOT_TOKEN": BOT})
        with mock.patch.object(boot, "boot_key", return_value="aistv-boot|khác"):
            with self.assertRaises(Exception):
                boot.boot_decrypt(blob)

    def test_tampered_fails(self):
        blob = boot.boot_encrypt({"TELEGRAM_BOT_TOKEN": BOT})
        raw = list(blob)
        raw[10] = "A" if raw[10] != "A" else "B"
        with self.assertRaises(Exception):
            boot.boot_decrypt("".join(raw))

    def test_nonce_is_random(self):
        self.assertNotEqual(boot.boot_encrypt({"A": "1"}), boot.boot_encrypt({"A": "1"}))


class EndpointTest(unittest.TestCase):
    def test_default_endpoint(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            url = boot.boot_endpoint({})
        self.assertTrue(url.endswith("/aistv/boot.json"))
        self.assertNotIn("//aistv", url)

    def test_boot_url_override(self):
        with mock.patch.dict("os.environ", {"AISTV_BOOT_URL": "https://x.test/"}, clear=True):
            self.assertEqual(boot.boot_endpoint({}), "https://x.test/aistv/boot.json")

    def test_read_swallows_network_error(self):
        with mock.patch.object(boot, "_get", side_effect=OSError("mất mạng")):
            self.assertEqual(boot.boot_read(), {})

    def test_read_swallows_bad_blob(self):
        with mock.patch.object(boot, "_get", return_value={"blob": "zzz"}):
            self.assertEqual(boot.boot_read(), {})

    def test_read_returns_values(self):
        blob = boot.boot_encrypt({"TELEGRAM_BOT_TOKEN": BOT})
        with mock.patch.object(boot, "_get", return_value={"blob": blob}):
            self.assertEqual(boot.boot_read()["TELEGRAM_BOT_TOKEN"], BOT)


class BootstrapScriptTest(unittest.TestCase):
    """bootstrap.sh phải dùng đúng khoá/endpoint và không chứa token trần."""

    @classmethod
    def setUpClass(cls):
        cls.text = BOOT_SH.read_text("utf-8")

    def test_uses_same_key(self):
        self.assertIn(boot.BOOT_KEY_PART, self.text)
        self.assertIn(boot.BOOT_KEY_PREFIX, self.text)

    def test_uses_boot_endpoint(self):
        self.assertIn("aistv/boot.json", self.text)
        self.assertIn("aistv/secrets.json", self.text)

    def test_no_plaintext_tokens(self):
        self.assertIsNone(re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", self.text))
        self.assertIsNone(re.search(r"github_pat_[A-Za-z0-9_]{20,}", self.text))
        self.assertIsNone(re.search(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", self.text))

    def test_bootstrap_only_guard(self):
        self.assertIn("AISTV_BOOTSTRAP_ONLY", self.text)

    def test_bash_syntax_if_available(self):
        import shutil
        import subprocess
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("không có bash")
        proc = subprocess.run([bash, "-n", str(BOOT_SH)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class PushFilterTest(unittest.TestCase):
    def test_push_needs_bot_token(self):
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": ""}), \
             mock.patch.object(boot.cfg, "read_files", return_value=({}, {})), \
             mock.patch.object(boot.cfg, "vault_token", return_value=""), \
             mock.patch.object(boot.cfg, "github_tokens", return_value=[]), \
             mock.patch.object(boot, "boot_endpoint", return_value="https://x/y.json"), \
             mock.patch.object(boot, "boot_encrypt") as enc, \
             mock.patch("urllib.request.urlopen") as urlopen:
            ok = boot.boot_push({}, bot_token="", log=None)
        self.assertFalse(ok)
        enc.assert_not_called()
        urlopen.assert_not_called()

    def test_push_writes_encrypted_payload(self):
        captured = {}

        class Resp:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=0):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return Resp()

        with mock.patch.object(boot, "boot_endpoint", return_value="https://x/y.json"), \
             mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = boot.boot_push({}, bot_token=BOT, log=None)
        self.assertTrue(ok)
        self.assertEqual(captured["body"]["v"], 1)
        data = boot.boot_decrypt(captured["body"]["blob"])
        self.assertEqual(data, {"TELEGRAM_BOT_TOKEN": BOT})
        self.assertNotIn("GITHUB_TOKEN", captured["body"]["blob"])


if __name__ == "__main__":
    unittest.main()
