import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from session_manager import cli, core  # noqa: E402
from session_manager.backends.herdr import HerdrBackend, state_from_title  # noqa: E402
from session_manager.interface import SessionError  # noqa: E402


class FakeRunner:
    """Records Herdr commands and answers each by its first two words."""

    def __init__(self, answers=None, fail=()):
        self.calls = []
        self.answers = answers or {}
        self.fail = set(fail)

    def __call__(self, cmd, want_json=True):
        self.calls.append(cmd)
        key = " ".join(cmd[:3]) if cmd[0] == "herdr-app" else " ".join(cmd[:2])
        if key in self.fail:
            raise SessionError(f"{key} failed")
        return self.answers.get(key, {} if want_json else "")


START_ANSWERS = {
    "hc ls": {"terminals": [{"name": "feat-reviewer", "address": "t1"}]},
    "hc run": {"address": "t9", "first_message": None},
    "herdr-app do terminal.keep": {"pane": "p42"},
}


class NamingTest(unittest.TestCase):
    def test_takes_the_base_name_when_free(self):
        self.assertEqual(core.helper_name("feat", "helper", set()), "feat-helper")

    def test_takes_the_next_number_when_taken(self):
        self.assertEqual(core.helper_name("feat", "reviewer", {"feat-reviewer", "feat-reviewer-2"}), "feat-reviewer-3")

    def test_rejects_names_herdr_refuses(self):
        with self.assertRaises(SessionError):
            core.helper_name("Feature With Spaces", "helper", set())
        with self.assertRaises(SessionError):
            core.helper_name("a" * 30, "reviewer", set())


class AgentsTest(unittest.TestCase):
    def test_claude_launch_details_come_from_agents_toml(self):
        spec = core.agent_spec("claude")
        self.assertEqual(spec["argv"], ["claude", "--dangerously-skip-permissions"])
        self.assertEqual(spec["t3_provider"], "claudeAgent")

    def test_unknown_agent_names_the_known_ones(self):
        with self.assertRaisesRegex(SessionError, "claude, codex"):
            core.agent_spec("gemini")


class EnvelopeTest(unittest.TestCase):
    def test_carries_the_report_command_and_the_result_path(self):
        text = core.envelope("feat", "reviewer", "review-1", "Review the diff", "the patch",
                             "Findings only.", "hc send t38")
        self.assertIn("Role: reviewer. Findings only.", text)
        self.assertIn("~/.agent-sessions/feat/review-1.md", text)
        self.assertIn('Then run: hc send t38 "review-1 done:', text)
        self.assertIn("Do not start other agents.", text)


class HerdrStartTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t38"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_runs_labels_then_shows_the_pane_by_address(self):
        runner = FakeRunner(START_ANSWERS)
        out = HerdrBackend(runner).start("feat-helper", "/repo", {"argv": ["claude"]}, "go",
                                         {"pair.feature": "feat", "pair.role": "helper"})
        run_cmd, focus, keep = runner.calls
        self.assertEqual(run_cmd[:7], ["hc", "run", "--bg", "--name", "feat-helper", "--cwd", "/repo"])
        self.assertIn("pair.feature=feat", run_cmd)
        self.assertEqual(run_cmd[-2:], ["claude", "go"])
        self.assertEqual(focus[-1], "t38")
        self.assertEqual(keep[4], "t9")
        self.assertEqual(out, {"name": "feat-helper", "address": "t9", "delivered": None, "pane": "p42", "worktree": None})

    def test_hidden_helpers_get_no_pane(self):
        runner = FakeRunner(START_ANSWERS)
        out = HerdrBackend(runner).start("feat-reviewer", "/repo", {"argv": ["claude"]}, "go", {}, visible=False)
        self.assertEqual(len(runner.calls), 1)
        self.assertIsNone(out["pane"])

    def test_adds_no_daemon_for_codex(self):
        runner = FakeRunner(START_ANSWERS)
        HerdrBackend(runner).start("feat-helper", "/repo", {"argv": ["codex", "--x"]}, "go", {})
        self.assertEqual(runner.calls[0][-4:], ["codex", "--no-daemon", "--x", "go"])

    def test_fails_loudly_without_an_address(self):
        runner = FakeRunner({"hc run": {}})
        with self.assertRaisesRegex(SessionError, "no address"):
            HerdrBackend(runner).start("feat-helper", "/repo", {"argv": ["claude"]}, "go", {})

    def test_reports_delivery_when_hc_says_so(self):
        runner = FakeRunner({**START_ANSWERS, "hc run": {"address": "t9", "first_message": {"sent": False}}})
        out = HerdrBackend(runner).start("feat-helper", "/repo", {"argv": ["claude"]}, "go", {})
        self.assertIs(out["delivered"], False)


class FakeGit:
    """Records git commands; the repo's common dir is a bare clone."""

    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return "/code/acme-app\n" if "--git-common-dir" in args else ""


class WorktreeTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t38"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_path_sits_beside_the_repo(self):
        self.assertEqual(core.worktree_path("/code/acme-app-main", "feat-helper", FakeGit()),
                         "/code/acme-app-feat-helper")

    def test_a_normal_clone_names_the_repo_not_dot_git(self):
        git = lambda args: "/code/app/.git\n"
        self.assertEqual(core.worktree_path("/code/app", "feat-helper", git), "/code/app-feat-helper")

    def test_herdr_creates_it_runs_there_and_records_it(self):
        git, runner = FakeGit(), FakeRunner(START_ANSWERS)
        out = HerdrBackend(runner, git).start("feat-reviewer", "/code/acme-app-main", {"argv": ["claude"]},
                                              "go", {}, visible=False, worktree={"ref": "abc123", "branch": None})
        self.assertEqual(git.calls[1], ["-C", "/code/acme-app-main", "worktree", "add", "--detach",
                                        "/code/acme-app-feat-reviewer", "abc123"])
        self.assertIn("/code/acme-app-feat-reviewer", runner.calls[0])
        self.assertIn("pair.worktree=/code/acme-app-feat-reviewer", runner.calls[0])
        self.assertEqual(out["worktree"], "/code/acme-app-feat-reviewer")

    def test_a_branch_is_created_when_asked(self):
        git = FakeGit()
        HerdrBackend(FakeRunner(START_ANSWERS), git).start("feat-helper", "/code/r", {"argv": ["claude"]}, "go", {},
                                                           visible=False, worktree={"ref": "HEAD", "branch": "x-helper"})
        self.assertEqual(git.calls[1][4:6], ["-b", "x-helper"])

    def test_stop_removes_only_the_worktree_sm_created(self):
        git = FakeGit()
        runner = FakeRunner({"hc get": {"labels": {"pair.worktree": "/code/acme-app-feat-reviewer"}}})
        out = HerdrBackend(runner, git).stop("feat-reviewer")
        self.assertEqual(git.calls, [["worktree", "remove", "--force", "/code/acme-app-feat-reviewer"]])
        self.assertEqual(out["removed_worktree"], "/code/acme-app-feat-reviewer")


class KeepRetryTest(unittest.TestCase):
    def test_waits_until_herdr_app_sees_the_new_helper(self):
        runner = FakeRunner()
        calls = {"n": 0}

        def flaky(cmd, want_json=True):
            if cmd[:3] == ["herdr-app", "do", "terminal.keep"]:
                calls["n"] += 1
                if calls["n"] < 3:
                    raise SessionError('terminal.keep failed: no running terminal "t9"')
                return {"pane": "p1"}
            return runner(cmd, want_json)

        with mock.patch("session_manager.backends.herdr.time.sleep"):
            self.assertEqual(HerdrBackend(flaky).keep("t9"), {"pane": "p1"})
        self.assertEqual(calls["n"], 3)

    def test_other_keep_errors_are_not_retried(self):
        runner = FakeRunner(fail={"herdr-app do terminal.keep"})
        with self.assertRaises(SessionError):
            HerdrBackend(runner).keep("t9")
        self.assertEqual(len(runner.calls), 1)


class HerdrOtherOpsTest(unittest.TestCase):
    def test_stop_tolerates_an_already_removed_helper(self):
        runner = FakeRunner(fail={"hc rm"})
        self.assertEqual(HerdrBackend(runner).stop("feat-helper"),
                         {"helper": "feat-helper", "stopped": True, "removed_worktree": None})

    def test_state_from_title(self):
        self.assertEqual(state_from_title("✳ Research", None), "idle")
        self.assertEqual(state_from_title("◐ Research", None), "working")
        self.assertEqual(state_from_title(None, "blocked"), "blocked")
        self.assertEqual(state_from_title(None, None), "unknown")

    def test_self_address_needs_herdr(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(SessionError, "not inside Herdr"):
                HerdrBackend(FakeRunner()).self_address()


class CliTest(unittest.TestCase):
    def test_start_picks_a_free_name_and_tags_the_helper(self):
        runner = FakeRunner(START_ANSWERS)
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t38"}):
            out = cli.dispatch(cli.parse_args(["start", "--feature", "feat", "--role", "reviewer",
                                               "--cwd", "/repo", "--message", "go"]), HerdrBackend(runner))
        self.assertEqual(out["name"], "feat-reviewer-2")
        self.assertIn("pair.role=reviewer", runner.calls[1])

    def test_errors_exit_non_zero_with_json(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code = cli.main(["self"], backend=HerdrBackend(FakeRunner()))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
