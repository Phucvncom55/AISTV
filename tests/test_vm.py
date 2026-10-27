# -*- coding: utf-8 -*-
"""Kiểm tra helper tạo máy ảo (aistv_vm.py)."""
import base64
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aistv_vm as vm  # noqa: E402

try:
    from nacl.public import PrivateKey, SealedBox
    HAS_NACL = True
except Exception:
    HAS_NACL = False


class InputTest(unittest.TestCase):
    def test_normalize_windows(self):
        self.assertEqual(vm.normalize_windows(""), "windows-latest")
        self.assertEqual(vm.normalize_windows("Windows-2022"), "windows-2022")
        with self.assertRaises(vm.VMError):
            vm.normalize_windows("windows-7")

    def test_clamp_minutes(self):
        self.assertEqual(vm.MAX_MINUTES, 360)
        self.assertEqual(vm.clamp_minutes(""), 360)
        self.assertEqual(vm.clamp_minutes(None), 360)
        self.assertEqual(vm.clamp_minutes("120"), 120)
        self.assertEqual(vm.clamp_minutes(10), 60)
        self.assertEqual(vm.clamp_minutes(999), 360)
        with self.assertRaises(vm.VMError):
            vm.clamp_minutes("abc")

    def test_validate_credentials(self):
        pat = "ghp_" + "a" * 36
        key = "tskey-auth-" + "k" * 20
        self.assertEqual(vm.validate_credentials(pat, key), (pat, key))
        with self.assertRaises(vm.VMError):
            vm.validate_credentials("", key)
        with self.assertRaises(vm.VMError):
            vm.validate_credentials(pat, "có dấu cách")
        with self.assertRaises(vm.VMError):
            vm.validate_credentials("short", key)

    def test_mask_value(self):
        self.assertEqual(vm.mask_value(""), "")
        self.assertEqual(vm.mask_value("abcdef"), "******")
        masked = vm.mask_value("ghp_" + "x" * 30)
        self.assertTrue(masked.startswith("ghp_"))
        self.assertNotIn("x" * 10, masked)


class SyncForkTest(unittest.TestCase):
    def _sync(self, status, body):
        with mock.patch.object(vm, "_api", return_value=(status, body)):
            return vm.sync_fork("someone", "ghp_" + "a" * 36)

    def test_updated(self):
        self.assertEqual(self._sync(200, {"merge_type": "fast-forward"}), "updated")
        self.assertEqual(self._sync(200, {"merge_type": "merge"}), "updated")

    def test_already_up_to_date(self):
        self.assertEqual(self._sync(200, {"merge_type": "none"}), "up-to-date")

    def test_diverged(self):
        self.assertEqual(self._sync(409, {"message": "Merge conflict"}), "diverged")

    def test_other_errors_do_not_block(self):
        self.assertEqual(self._sync(500, {"message": "boom"}), "skipped")
        self.assertEqual(self._sync(404, {"message": "Not a fork"}), "skipped")


@unittest.skipUnless(HAS_NACL, "chưa cài pynacl")
class SealedBoxTest(unittest.TestCase):
    def test_seal_roundtrip(self):
        sk = PrivateKey.generate()
        pk_b64 = base64.b64encode(bytes(sk.public_key)).decode("ascii")
        encrypted = vm.seal_secret(pk_b64, "mật-khẩu-36-ký-tự")
        plain = SealedBox(sk).decrypt(base64.b64decode(encrypted))
        self.assertEqual(plain.decode("utf-8"), "mật-khẩu-36-ký-tự")


if __name__ == "__main__":
    unittest.main()
