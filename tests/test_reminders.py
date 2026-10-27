# -*- coding: utf-8 -*-
"""Kiểm tra phân loại nhắc việc: tới hạn, quá hạn, quá cũ, định kỳ."""
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

NOW = 1_700_000_000
DAY = 86400


def _rec(when, **extra):
    rec = {"when": when, "chat": 1, "text": "việc thử"}
    rec.update(extra)
    return rec


class PruneRemindersTest(unittest.TestCase):
    def test_future_record_kept(self):
        out = bot._prune_reminders({"a": _rec(NOW + 3600)}, NOW)
        self.assertIn("a", out)
        self.assertNotIn("expired", out["a"])

    def test_recently_due_record_runs_not_expired(self):
        out = bot._prune_reminders({"a": _rec(NOW - 3600)}, NOW)
        self.assertIn("a", out)
        self.assertNotIn("expired", out["a"])

    def test_missed_three_days_is_marked_expired(self):
        out = bot._prune_reminders({"a": _rec(NOW - 3 * DAY)}, NOW)
        self.assertIn("a", out)
        self.assertTrue(out["a"]["expired"])

    def test_older_than_30_days_dropped(self):
        out = bot._prune_reminders({"a": _rec(NOW - 31 * DAY)}, NOW)
        self.assertEqual(out, {})

    def test_daily_never_expires(self):
        out = bot._prune_reminders({"a": _rec(NOW - 40 * DAY, repeat="daily")}, NOW)
        self.assertIn("a", out)
        self.assertNotIn("expired", out["a"])
        self.assertEqual(out["a"]["when"], NOW - 40 * DAY)

    def test_invalid_records_dropped(self):
        records = {
            "a": {"when": "không-phải-số", "chat": 1},
            "b": {"chat": 1},
            "c": "rác",
            "ok": _rec(NOW + 60),
        }
        self.assertEqual(set(bot._prune_reminders(records, NOW)), {"ok"})

    def test_empty_input(self):
        self.assertEqual(bot._prune_reminders({}, NOW), {})
        self.assertEqual(bot._prune_reminders(None, NOW), {})


if __name__ == "__main__":
    unittest.main()
