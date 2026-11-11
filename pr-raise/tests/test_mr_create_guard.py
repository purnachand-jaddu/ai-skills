import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "mr_create_guard.py"


def run(command):
    event = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                          capture_output=True, text=True)


class GuardTest(unittest.TestCase):
    def test_blocks_hand_run_creates(self):
        for cmd in ["glab mr create --title x --yes",
                    "gh pr create --base main --body-file d.md",
                    "git push -u origin b && glab mr create --yes",
                    "cd repo; GITLAB_HOST=x glab mr create"]:
            out = run(cmd)
            self.assertEqual(out.returncode, 2, cmd)
            self.assertIn("pr-raise", out.stderr)

    def test_allows_pr_raise_creates(self):
        for cmd in ["PR_RAISE=1 glab mr create --yes",
                    "PR_RAISE=1 gh pr create --base main",
                    "git push -u origin b && PR_RAISE=1 glab mr create"]:
            self.assertEqual(run(cmd).returncode, 0, cmd)

    def test_ignores_other_commands(self):
        for cmd in ["glab mr view 913", "gh pr list --head b",
                    'grep -n "gh pr create" pr-raise/SKILL.md', "echo glab mr create"]:
            self.assertEqual(run(cmd).returncode, 0, cmd)

    def test_bad_input_is_allowed(self):
        out = subprocess.run([sys.executable, str(HOOK)], input="not json",
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)


if __name__ == "__main__":
    unittest.main()
