# -*- coding: utf-8 -*-
"""Smoke test cho scripts/code_map.py và aistv_planner.py."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aistv_planner as planner          # noqa: E402
from scripts import code_map             # noqa: E402

GIT = shutil.which("git")


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com"] + list(args),
        cwd=str(repo), check=True, capture_output=True, text=True)


class CodeMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_outline_has_line_numbers_and_docs(self):
        (self.tmp / "demo.py").write_text(
            '"""Demo module."""\n\n\nclass Box:\n    """A box."""\n\n'
            '    def put(self, x):\n        """Put x."""\n\n\n'
            'def run(a, b=2):\n    """Run it."""\n', "utf-8")
        info = code_map._outline(self.tmp / "demo.py")
        self.assertEqual(info["doc"], "Demo module.")
        names = [i["name"] for i in info["items"]]
        self.assertIn("Box", names)
        self.assertIn("run(a, b=2)", names)
        box = next(i for i in info["items"] if i["kind"] == "class")
        self.assertEqual(box["line"], 4)
        self.assertEqual(box["methods"][0]["name"], "put(self, x)")

    def test_build_and_check(self):
        (self.tmp / "a.py").write_text('"""A."""\n\ndef f():\n    pass\n', "utf-8")
        out = self.tmp / "docs" / "CODEMAP.md"
        content = code_map.build(self.tmp)
        out.parent.mkdir(parents=True)
        out.write_text(content, "utf-8")
        self.assertIn("## a.py", content)
        self.assertIn("L3 ", content)
        self.assertEqual(content, code_map.build(self.tmp))


class PlanParseTest(unittest.TestCase):
    def test_parse_fenced_json(self):
        text = """Đây là kế hoạch:
```json
{"title": "Sửa lỗi", "steps": [
  {"title": "Đọc code", "detail": "mở a.py", "verify": "hiểu luồng"},
  "Sửa hàm",
  {"title": "Kiểm chứng", "verify": "verify.py PASS"}
]}
```"""
        obj, err = planner.parse_plan(text)
        self.assertEqual(err, "")
        self.assertEqual(obj["title"], "Sửa lỗi")
        self.assertEqual(len(obj["steps"]), 3)
        self.assertEqual(obj["steps"][1]["title"], "Sửa hàm")

    def test_parse_rejects_garbage(self):
        for bad in ("", "không có json", '{"steps": []}', '{"title": "x", "steps": ["  "]}'):
            obj, err = planner.parse_plan(bad)
            self.assertIsNone(obj, bad)
            self.assertTrue(err, bad)

    def test_prompt_mentions_repo_and_no_push(self):
        prompt = planner.plan_prompt("Làm X", repo="/repo", workspace="/ws")
        self.assertIn("/repo", prompt)
        self.assertIn("JSON", prompt)
        step = planner.step_prompt({"title": "T", "steps": [{"n": 1, "title": "a",
                                                            "status": "pending"}]},
                                   {"n": 1, "title": "a", "detail": "d"},
                                   repo="/repo", workspace="/ws")
        self.assertIn("KHÔNG push", step)
        self.assertIn("verify.py", step)


class PlanStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_load_and_progress(self):
        plan = planner.new_plan(self.tmp, 42, "Kế hoạch A", "yêu cầu",
                                [{"title": "b1"}, {"title": "b2"}])
        loaded = planner.load_plan(self.tmp, plan["id"])
        self.assertEqual(loaded["title"], "Kế hoạch A")
        self.assertEqual(planner.progress(loaded), (0, 2))
        planner.set_step(loaded, 1, status="done", result="ok")
        planner.save_plan(self.tmp, loaded)
        self.assertEqual(planner.progress(planner.load_plan(self.tmp, plan["id"])), (1, 2))
        self.assertEqual(planner.next_pending(loaded)["n"], 2)
        self.assertEqual(planner.latest_plan(self.tmp, 42)["id"], plan["id"])
        self.assertIsNone(planner.latest_plan(self.tmp, 99))

    def test_render_escapes_html(self):
        plan = planner.new_plan(self.tmp, 1, "<b>x</b>", "a & b", ["bước <i>"])
        text = planner.render_plan(plan)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", text)
        self.assertIn("&amp;", text)


@unittest.skipUnless(GIT, "cần git")
class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.home = self.tmp / "home"
        _git(self.repo, "init", "-q")
        (self.repo / "a.txt").write_text("one\n", "utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_checkpoint_restores_worktree(self):
        meta, err = planner.create_checkpoint(self.home, self.repo, "trước khi sửa")
        self.assertEqual(err, "")
        self.assertFalse(meta["dirty"])
        (self.repo / "a.txt").write_text("agent\n", "utf-8")
        (self.repo / "new.txt").write_text("tmp\n", "utf-8")
        ok, detail = planner.restore_checkpoint(self.home, self.repo, meta["id"])
        self.assertTrue(ok, detail)
        self.assertEqual((self.repo / "a.txt").read_text("utf-8"), "one\n")
        self.assertFalse((self.repo / "new.txt").exists())

    def test_dirty_checkpoint_keeps_user_work(self):
        (self.repo / "a.txt").write_text("user work\n", "utf-8")
        (self.repo / "user.txt").write_text("mine\n", "utf-8")
        meta, err = planner.create_checkpoint(self.home, self.repo, "đang dở")
        self.assertEqual(err, "")
        self.assertTrue(meta["dirty"])
        (self.repo / "a.txt").write_text("agent work\n", "utf-8")
        (self.repo / "agent.txt").write_text("tmp\n", "utf-8")
        ok, detail = planner.restore_checkpoint(self.home, self.repo, meta["id"])
        self.assertTrue(ok, detail)
        self.assertEqual((self.repo / "a.txt").read_text("utf-8"), "user work\n")
        self.assertTrue((self.repo / "user.txt").exists())
        self.assertFalse((self.repo / "agent.txt").exists())

    def test_refuses_after_new_commit(self):
        meta, _ = planner.create_checkpoint(self.home, self.repo)
        (self.repo / "a.txt").write_text("two\n", "utf-8")
        _git(self.repo, "commit", "-qam", "second")
        ok, detail = planner.restore_checkpoint(self.home, self.repo, meta["id"])
        self.assertFalse(ok)
        self.assertIn("commit mới", detail)

    def test_diff_stat_counts(self):
        (self.repo / "a.txt").write_text("one\ntwo\n", "utf-8")
        (self.repo / "b.txt").write_text("new\n", "utf-8")
        stat = planner.diff_stat(self.repo)
        self.assertEqual(stat["files"], 1)
        self.assertEqual(stat["untracked"], 1)
        self.assertIn("+1", stat["text"])

    def test_list_prunes_oldest(self):
        old = planner.CHECKPOINT_KEEP
        planner.CHECKPOINT_KEEP = 2
        try:
            for _ in range(3):
                planner.create_checkpoint(self.home, self.repo)
            self.assertEqual(len(planner.list_checkpoints(self.home, 10)), 2)
        finally:
            planner.CHECKPOINT_KEEP = old


class VerifyTest(unittest.TestCase):
    def test_verify_missing_script_is_ok(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            res = planner.verify_repo(tmp)
            self.assertTrue(res["ok"])
            self.assertIn("không có", res["summary"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
