# -*- coding: utf-8 -*-
"""Kiểm tra nhánh công việc dài (aistv_work.py) trên repo git tạm."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aistv_work as work              # noqa: E402

GIT = shutil.which("git")


def _git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com"] + list(args),
        cwd=str(repo), capture_output=True, text=True, check=True)


def _plan(pid="20260101-1200-ab"):
    return {
        "id": pid,
        "title": "Việc dài thử nghiệm",
        "request": "làm tính năng X",
        "status": "running",
        "created": 1.0,
        "steps": [
            {"n": 1, "title": "Khảo sát", "detail": "", "verify": "",
             "status": "done", "attempts": 1, "result": "xong"},
            {"n": 2, "title": "Sửa code", "detail": "", "verify": "",
             "status": "pending", "attempts": 0},
        ],
    }


@unittest.skipUnless(GIT, "cần git")
class WorkBranchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init")
        _git(self.repo, "checkout", "-b", "main")
        (self.repo / ".gitignore").write_text(".aistv/\n", "utf-8")
        (self.repo / "base.txt").write_text("base\n", "utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_branch_name_and_scrub(self):
        self.assertEqual(work.branch_for("2026/01/01 x"), "aistv/work-2026-01-01-x")
        self.assertTrue(work.branch_for("").startswith("aistv/work-"))
        text = "token ghp_" + "a" * 30 + " và mật khẩu"
        self.assertNotIn("ghp_", work.scrub(text, 200))

    def test_dirty_tree_refuses_new_branch(self):
        (self.repo / "dirty.txt").write_text("x", "utf-8")
        res = work.prepare(self.repo, _plan())
        self.assertFalse(res["ok"])
        self.assertIn("chưa push", res["error"])
        self.assertEqual(work.current_branch(self.repo), "main")

    def test_commit_state_and_resume(self):
        plan = _plan()
        res = work.prepare(self.repo, plan)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["base"], "main")
        plan.update(work_branch=res["branch"], work_base=res["base"],
                    work_base_sha=res["base_sha"])

        (self.repo / "new.txt").write_text("hello\n", "utf-8")
        out = work.commit_step(self.repo, plan, plan["steps"][0], push=False)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["sha"])
        self.assertTrue((self.repo / ".aistv/work" / f"{plan['id']}.json").is_file())
        tracked = _git(self.repo, "ls-files", ".aistv").stdout
        self.assertIn(f"{plan['id']}.json", tracked)

        self.assertEqual(work.diff_from_base(self.repo, plan), "1 file sửa (+1/−0)")
        self.assertGreaterEqual(work.commit_count(self.repo, plan), 1)

        ok, detail = work.return_to_base(self.repo, "main")
        self.assertTrue(ok, detail)
        self.assertEqual(work.current_branch(self.repo), "main")
        self.assertFalse((self.repo / "new.txt").exists())

        tasks = work.fetch_tasks(self.repo, fetch=False)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], plan["id"])
        self.assertEqual(tasks[0]["title"], plan["title"])

        loaded, err = work.checkout_task(self.repo, tasks[0])
        self.assertFalse(err, err)
        self.assertEqual(loaded["id"], plan["id"])
        self.assertEqual(loaded["work_branch"], res["branch"])
        self.assertEqual(loaded["status"], "draft")
        self.assertTrue((self.repo / "new.txt").is_file())

    def test_merge_and_drop(self):
        plan = _plan("20260101-1400-ef")
        res = work.prepare(self.repo, plan)
        plan.update(work_branch=res["branch"], work_base=res["base"],
                    work_base_sha=res["base_sha"])
        (self.repo / "new.txt").write_text("hello\n", "utf-8")
        work.commit_step(self.repo, plan, plan["steps"][0], push=False)
        work.return_to_base(self.repo, "main")

        ok, detail = work.merge_into_base(self.repo, plan)
        self.assertTrue(ok, detail)
        self.assertEqual(work.current_branch(self.repo), "main")
        self.assertTrue((self.repo / "new.txt").is_file())
        staged = _git(self.repo, "ls-files", ".aistv").stdout.strip()
        self.assertEqual(staged, "", "không được đưa state .aistv vào nhánh chính")

        _git(self.repo, "reset", "--hard", "HEAD")
        _git(self.repo, "clean", "-fd")
        ok, detail = work.drop_branch(self.repo, plan, delete_remote=False)
        self.assertTrue(ok, detail)
        self.assertFalse(work.find_task(work.fetch_tasks(self.repo, fetch=False),
                                        plan["id"]))


@unittest.skipUnless(GIT, "cần git")
class RemoteResumeTest(unittest.TestCase):
    """Máy B clone từ GitHub (ở đây là bare repo) vẫn thấy việc đang dở."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.origin = self.tmp / "origin.git"
        _git(self.tmp, "init", "--bare", str(self.origin))
        self.a = self.tmp / "may-a"
        _git(self.tmp, "clone", str(self.origin), str(self.a))
        _git(self.a, "checkout", "-b", "main")
        (self.a / "base.txt").write_text("base\n", "utf-8")
        _git(self.a, "add", "-A")
        _git(self.a, "commit", "-m", "init")
        _git(self.a, "push", "-u", "origin", "main")
        _git(self.origin, "symbolic-ref", "HEAD", "refs/heads/main")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_machine_resumes(self):
        plan = _plan("20260101-1300-cd")
        res = work.prepare(self.a, plan)
        self.assertTrue(res["ok"], res)
        plan.update(work_branch=res["branch"], work_base=res["base"],
                    work_base_sha=res["base_sha"])
        (self.a / "new.txt").write_text("hello\n", "utf-8")
        pushed = work.commit_step(self.a, plan, plan["steps"][0], push=True)
        self.assertTrue(pushed["ok"], pushed)
        self.assertTrue(pushed["pushed"], pushed)

        b = self.tmp / "may-b"
        _git(self.tmp, "clone", str(self.origin), str(b))
        _git(b, "checkout", "main")

        tasks = work.fetch_tasks(b)
        self.assertEqual(len(tasks), 1, tasks)
        self.assertEqual(tasks[0]["id"], plan["id"])
        self.assertEqual(tasks[0]["source"], "remote")

        loaded, err = work.checkout_task(b, tasks[0])
        self.assertFalse(err, err)
        self.assertEqual(loaded["work_branch"], res["branch"])
        self.assertTrue((b / "new.txt").is_file())
        self.assertEqual(work.current_branch(b), res["branch"])


if __name__ == "__main__":
    unittest.main()
