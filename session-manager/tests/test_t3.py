import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_manager import backends, core  # noqa: E402
from session_manager.backends.t3 import T3Backend, state_of  # noqa: E402
from session_manager.interface import SessionError  # noqa: E402

ENV = {"T3CODE_THREAD_ID": "thread:me", "T3CODE_CLI_PATH": "/bin/t3"}


class FakeT3:
    """Records t3 commands; `thread show` answers from a status script per thread."""

    def __init__(self, statuses=None):
        self.calls = []
        self.statuses = statuses or {}

    def __call__(self, args, want_json=True):
        self.calls.append(args)
        if args[:2] == ["thread", "start"]:
            return {"threadId": "thread:h1", "link": "https://app/t/h1"}
        if args[:2] == ["thread", "show"] and want_json:
            script = self.statuses.get(args[-1], ["idle"])
            status = script.pop(0) if len(script) > 1 else script[0]
            return {"thread": {"threadId": args[-1], "status": status, "pendingRequestCount": 0}}
        return {} if want_json else "messages"


class T3Test(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = Path(tempfile.mkdtemp()) / "helpers.json"

    def backend(self, fake):
        return T3Backend(fake, self.registry, sleep=lambda s: None)

    def test_start_passes_provider_model_title_and_registers(self):
        fake = FakeT3()
        out = self.backend(fake).start("feat-helper", "/repo", core.agent_spec("codex"), "go",
                                       {"pair.feature": "feat", "pair.role": "helper"})
        self.assertEqual(fake.calls[0], ["thread", "start", "--json", "--title", "feat-helper",
                                         "--provider", "codex", "--model", "gpt-6.1-sol", "/repo", "go"])
        self.assertEqual(out["address"], "thread:h1")
        self.assertEqual(self.backend(fake).names_in_use(), {"feat-helper"})

    def test_worktree_goes_inside_the_repo_and_the_thread_starts_there(self):
        common = Path(tempfile.mkdtemp()) / "acme-app"
        (common / "info").mkdir(parents=True)
        git_calls = []

        def git(args):
            git_calls.append(args)
            return f"{common}\n" if "--git-common-dir" in args else ""

        fake = FakeT3()
        out = T3Backend(fake, self.registry, sleep=lambda s: None, git=git).start(
            "feat-reviewer", str(common), core.agent_spec("claude"), "go", {}, worktree={"ref": "abc", "branch": None})
        tree = str(common / ".worktrees" / "feat-reviewer")
        self.assertIn(["-C", str(common), "worktree", "add", "--detach", tree, "abc"], git_calls)
        self.assertEqual(fake.calls[0][-2:], [tree, "go"])
        self.assertNotIn("--worktree", fake.calls[0])
        self.assertIn("/.worktrees/", (common / "info" / "exclude").read_text())
        self.assertEqual(out["worktree"], tree)

    def test_forget_removes_the_worktree_sm_made(self):
        git_calls = []
        b = T3Backend(FakeT3(), self.registry, sleep=lambda s: None, git=lambda a: git_calls.append(a) or "")
        b.save({"feat-reviewer": {"thread": "t", "caller": "thread:me", "worktree": "/r/.worktrees/feat-reviewer"}})
        self.assertEqual(b.forget("feat-reviewer")["removed_worktree"], "/r/.worktrees/feat-reviewer")
        self.assertEqual(git_calls, [["worktree", "remove", "--force", "/r/.worktrees/feat-reviewer"]])

    def test_status_lists_only_the_feature(self):
        fake = FakeT3({"thread:h1": ["running"]})
        b = self.backend(fake)
        b.start("feat-helper", "/repo", core.agent_spec("claude"), "go", {"pair.feature": "feat"})
        self.assertEqual([r["state"] for r in b.status("feat")], ["working"])
        self.assertEqual(b.status("other"), [])

    def test_collect_returns_when_a_helper_stops_working(self):
        fake = FakeT3({"thread:h1": ["running", "running", "completed"]})
        b = self.backend(fake)
        b.start("feat-helper", "/repo", core.agent_spec("claude"), "go", {})
        self.assertEqual(b.collect(60)["reason"], "idle")

    def test_collect_reports_a_helper_that_already_failed(self):
        fake = FakeT3({"thread:h1": ["failed"]})
        b = self.backend(fake)
        b.start("feat-helper", "/repo", core.agent_spec("claude"), "go", {})
        self.assertEqual(b.collect(60), {"reason": "failed", "helper": "feat-helper", "address": "thread:h1"})

    def test_stop_says_how_to_stop_it_instead(self):
        b = self.backend(FakeT3())
        b.start("feat-helper", "/repo", core.agent_spec("claude"), "go", {})
        with self.assertRaisesRegex(SessionError, "sm forget feat-helper"):
            b.stop("feat-helper")
        b.forget("feat-helper")
        self.assertEqual(b.names_in_use(), set())

    def test_report_command_uses_the_cli(self):
        self.assertEqual(self.backend(FakeT3()).report_command("thread:me"), "/bin/t3 thread send thread:me")

    def test_waiting_on_a_person_is_blocked(self):
        self.assertEqual(state_of({"status": "running", "pendingRequestCount": 1}), "blocked")


class DetectTest(unittest.TestCase):
    def test_prefers_t3_when_both_harnesses_are_present(self):
        with mock.patch.dict(os.environ, {"T3CODE_THREAD_ID": "x", "HC_TERMINAL_ID": "t1"}):
            self.assertEqual(backends.detect(), "t3")

    def test_falls_back_to_herdr(self):
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t1"}, clear=True):
            self.assertEqual(backends.detect(), "herdr")


if __name__ == "__main__":
    unittest.main()
