import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ticket_manager import backends, cli, lifecycle  # noqa: E402
from ticket_manager.backends import kaneo  # noqa: E402
from ticket_manager.backends.kaneo import KaneoBackend  # noqa: E402
from ticket_manager.interface import TicketBackend, TicketError  # noqa: E402

BOARD = [{"slug": "to-do", "name": "To Do", "is_final": False},
           {"slug": "in-progress", "name": "In Progress", "is_final": False},
           {"slug": "in-review", "name": "In Review", "is_final": False},
           {"slug": "done", "name": "Done", "is_final": True}]
STAGED_BOARD = BOARD[:3] + [{"slug": "in-staging-preview", "name": "Staging", "is_final": False},
                         {"slug": "done", "name": "Done", "is_final": True}]


class TargetTest(unittest.TestCase):
    def target(self, state, draft=False, valid=False, into=None, relation="fixes"):
        return lifecycle.target_for(state, draft, valid, into, "main", relation)

    def test_every_row_of_the_sync_table(self):
        self.assertEqual(self.target("open", draft=True), "in-progress")
        self.assertEqual(self.target("open", valid=True), "in-progress")
        self.assertEqual(self.target("open"), "in-review")
        self.assertEqual(self.target("merged", into="main"), "done")
        self.assertIsNone(self.target("merged", into="main", relation="refs"))
        self.assertIsNone(self.target("merged", into="release"))
        self.assertIsNone(self.target("closed"))


class GuardTest(unittest.TestCase):
    def test_moves_forward_through_managed_columns(self):
        self.assertEqual(lifecycle.plan_move("to-do", BOARD, "in-progress")[0], "in-progress")
        self.assertEqual(lifecycle.plan_move("in-review", BOARD, "in-progress")[0], "in-progress")

    def test_done_means_the_final_column_whatever_its_slug(self):
        cols = BOARD[:3] + [{"slug": "shipped", "name": "Shipped", "is_final": True}]
        self.assertEqual(lifecycle.plan_move("in-review", cols, "done")[0], "shipped")

    def test_never_out_of_done(self):
        move, why = lifecycle.plan_move("done", BOARD, "in-progress")
        self.assertIsNone(move)
        self.assertIn("never moved out of done", why)

    def test_leaves_a_column_a_person_chose(self):
        move, why = lifecycle.plan_move("in-staging-preview", STAGED_BOARD, "done")
        self.assertIsNone(move)
        self.assertIn("set by a person", why)

    def test_already_there_is_a_no_op(self):
        self.assertIsNone(lifecycle.plan_move("in-review", BOARD, "in-review")[0])

    def test_missing_column_is_reported_not_guessed(self):
        cols = [c for c in BOARD if c["slug"] != "in-review"]
        move, why = lifecycle.plan_move("in-progress", cols, "in-review")
        self.assertIsNone(move)
        self.assertIn("no in-review column", why)


class CommentTest(unittest.TestCase):
    def test_draft_comment_lists_the_reasons(self):
        text = lifecycle.comment_for("open", True, None, "main", "!881", "u", None, ["lint: x.go:4"])
        self.assertEqual(text, "!881 open (Draft): u\n- lint: x.go:4")

    def test_merge_comment_names_the_short_sha(self):
        text = lifecycle.comment_for("merged", False, "main", "main", "!881", "u", "1a2b3c4d5e6f", [])
        self.assertEqual(text, "Merged to main in !881 (1a2b3c4d5): u")


class FakeBackend(TicketBackend):
    name = "fake"

    def __init__(self, status="to-do", columns=BOARD):
        self.ticket = {"id": "t1", "key": "ACME-154", "title": "x", "status": status, "project_id": "p1",
                       "url": "https://t/ACME-154"}
        self.cols = columns
        self.moves, self.comments = [], []

    def get(self, key):
        return dict(self.ticket)

    def search(self, query, limit):
        return []

    def projects(self):
        return []

    def columns(self, project_id):
        return self.cols

    def move(self, ticket_id, status):
        self.moves.append(status)
        self.ticket["status"] = status

    def comment(self, ticket_id, text):
        self.comments.append(text)

    def create(self, project_id, title, description):
        raise NotImplementedError

    def list(self, project_id, status):
        return []

    def history(self, ticket_id):
        return []

    def labels(self, ticket_id):
        return []

    def relations(self, ticket_id):
        return []


def sync_args(state_file, **extra):
    argv = ["sync", "ACME-154", "--relation", "fixes", "--mr-ref", "!881",
            "--mr-url", "https://gitlab/mr/881", "--state-file", state_file]
    for flag, value in extra.items():
        argv += [f"--{flag.replace('_', '-')}"] + ([] if value is True else [value])
    return cli.parse_args(argv)


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.state = str(Path(tempfile.mkdtemp()) / "state.json")

    def test_moves_then_comments_once_per_mr_state(self):
        backend = FakeBackend("in-progress")
        first = cli.dispatch(sync_args(self.state, mr_state="open"), backend)
        again = cli.dispatch(sync_args(self.state, mr_state="open"), backend)
        self.assertEqual(first["to"], "in-review")
        self.assertTrue(first["commented"])
        self.assertIsNone(again["to"])
        self.assertFalse(again["commented"])
        self.assertEqual(backend.comments, ["!881 ready for review: https://gitlab/mr/881"])

    def test_a_new_mr_state_comments_again(self):
        backend = FakeBackend("in-progress")
        cli.dispatch(sync_args(self.state, mr_state="open"), backend)
        cli.dispatch(sync_args(self.state, mr_state="open", draft=True), backend)
        self.assertEqual(backend.moves, ["in-review", "in-progress"])
        self.assertEqual(len(backend.comments), 2)

    def test_records_the_ticket_in_the_state_file(self):
        cli.dispatch(sync_args(self.state, mr_state="merged", merged_into="main", sha="abc"), FakeBackend("in-review"))
        entry = json.loads(Path(self.state).read_text())["tickets"]["ACME-154"]
        self.assertEqual(entry["last_status"], "done")
        self.assertEqual(entry["last_mr_state"], "merged:main")

    def test_start_and_sync_report_the_link(self):
        backend = FakeBackend()
        started = cli.dispatch(cli.parse_args(["start", "ACME-154", "--branch", "fix/x"]), backend)
        synced = cli.dispatch(sync_args(self.state, mr_state="open"), backend)
        self.assertEqual({started["url"], synced["url"]}, {"https://t/ACME-154"})

    def test_start_is_idempotent(self):
        backend = FakeBackend("to-do")
        args = cli.parse_args(["start", "ACME-154", "--branch", "fix/x"])
        cli.dispatch(args, backend)
        cli.dispatch(args, backend)
        self.assertEqual(backend.moves, ["in-progress"])
        self.assertEqual(backend.comments, ["Work started on branch `fix/x`"])


class OpsTest(unittest.TestCase):
    def run_cli(self, argv, backend):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv, backend)
        return code, json.loads(out.getvalue())

    def test_comment_resolves_the_key(self):
        b = FakeBackend()
        code, out = self.run_cli(["comment", "ACME-154", "hello"], b)
        self.assertEqual((code, b.comments, out["url"]), (0, ["hello"], "https://t/ACME-154"))

    def test_move_applies_the_guards(self):
        b = FakeBackend(status="in-staging-preview", columns=STAGED_BOARD)
        _, out = self.run_cli(["move", "ACME-154", "to-do"], b)
        self.assertEqual((b.moves, out["to"]), ([], None))
        self.assertIn("set by a person", out["why"])

    def test_move_can_send_a_ticket_back(self):
        b = FakeBackend(status="in-progress")
        self.run_cli(["move", "ACME-154", "to-do"], b)
        self.assertEqual(b.moves, ["to-do"])

    def test_health_reports_the_backend(self):
        self.assertEqual(self.run_cli(["health"], FakeBackend())[1], {"ok": True, "backend": "fake"})

    def test_create_can_read_the_description_from_stdin(self):
        b = FakeBackend()
        b.create = mock.Mock(return_value={"key": "ACME-1"})
        with mock.patch("sys.stdin", io.StringIO("from stdin")):
            self.run_cli(["create", "--project", "p1", "--title", "t", "--description-file", "-"], b)
        b.create.assert_called_once_with("p1", "t", "from stdin")


class ApiKeyTest(unittest.TestCase):
    def test_no_keychain_says_to_set_the_variable(self):
        with mock.patch.dict("os.environ", {"KANEO_API_KEY": ""}), \
                mock.patch("subprocess.run", side_effect=FileNotFoundError("security")):
            with self.assertRaisesRegex(TicketError, "set KANEO_API_KEY"):
                kaneo.api_key()


class LoadBackendTest(unittest.TestCase):
    def test_a_missing_kaneo_setting_says_what_to_set(self):
        path = Path(tempfile.mkdtemp()) / "config.toml"
        path.write_text('[kaneo]\nbase_url = "https://kaneo.example/api"\n')
        with mock.patch.object(backends, "CONFIG_FILE", path):
            with self.assertRaisesRegex(TicketError, "workspace_id, workspace_slug"):
                backends.load_backend()


class KaneoTest(unittest.TestCase):
    def backend(self, responses):
        self.calls = []

        def transport(method, url, headers, body):
            self.calls.append((method, url, headers, body))
            return responses.pop(0)

        return KaneoBackend("https://kaneo.example/api", "ws1", "eng", key=lambda: "k-123", transport=transport)

    def test_get_sends_the_key_and_the_workspace(self):
        b = self.backend([(200, {}, json.dumps({"id": "t1", "title": "x", "status": "to-do", "projectId": "p1"}))])
        self.assertEqual(b.get("acme-154")["key"], "ACME-154")
        method, url, headers, _ = self.calls[0]
        self.assertEqual(url, "https://kaneo.example/api/task/by-ticket-id/acme-154?workspaceId=ws1")
        self.assertEqual(headers["Authorization"], "Bearer k-123")
        self.assertEqual(headers["User-Agent"], "ticket-manager/1.0")

    def test_search_builds_ticket_keys_from_slug_and_number(self):
        b = self.backend([(200, {}, json.dumps({"results": [
            {"id": "t1", "type": "task", "projectSlug": "acme", "taskNumber": 154, "title": "x"}]}))])
        self.assertEqual(b.search("windows", 3)[0]["key"], "ACME-154")

    def test_every_ticket_carries_its_web_link(self):
        link = "https://kaneo.example/eng/task/ACME-154"
        task = {"id": "t1", "number": 154, "title": "x", "status": "to-do", "projectId": "p1"}
        self.assertEqual(self.backend([(200, {}, json.dumps(task))]).get("acme-154")["url"], link)
        found = {"results": [{"id": "t1", "type": "task", "projectSlug": "acme", "taskNumber": 154}]}
        self.assertEqual(self.backend([(200, {}, json.dumps(found))]).search("x", 3)[0]["url"], link)
        board = {"data": {"slug": "acme", "columns": [{"tasks": [task]}]}}
        self.assertEqual(self.backend([(200, {}, json.dumps(board))]).list("p1", None)[0]["url"], link)
        created = self.backend([(200, {}, json.dumps(task)), (200, {}, json.dumps({"slug": "acme"}))])
        self.assertEqual(created.create("p1", "x", "d")["url"], link)

    def test_get_and_list_carry_the_description(self):
        task = {"id": "t1", "number": 154, "title": "x", "description": "why", "status": "to-do"}
        self.assertEqual(self.backend([(200, {}, json.dumps(task))]).get("acme-154")["description"], "why")
        board = {"data": {"slug": "acme", "columns": [{"tasks": [task]}]}}
        self.assertEqual(self.backend([(200, {}, json.dumps(board))]).list("p1", None)[0]["description"], "why")

    def test_labels_are_read_per_ticket(self):
        b = self.backend([(200, {}, json.dumps([{"id": "l1", "name": "agent"}]))])
        self.assertEqual(b.labels("t1"), ["agent"])
        self.assertEqual(self.calls[0][1], "https://kaneo.example/api/label/task/t1")

    def test_move_puts_the_status(self):
        b = self.backend([(200, {}, "{}")])
        b.move("t1", "in-review")
        method, url, _, body = self.calls[0]
        self.assertEqual((method, url, json.loads(body)), ("PUT", "https://kaneo.example/api/task/status/t1", {"status": "in-review"}))

    def test_list_follows_every_page(self):
        def page(n, total):
            return (200, {}, json.dumps({"pagination": {"totalPages": total}, "data": {"slug": "acme",
                    "columns": [{"slug": "done", "tasks": [{"id": f"t{n}", "number": n, "status": "done"}]}]}}))
        b = self.backend([page(1, 2), page(2, 2)])
        self.assertEqual([t["key"] for t in b.list("p1", None)], ["ACME-1", "ACME-2"])
        self.assertIn("page=2", self.calls[1][1])

    def test_history_merges_comments_and_activity_oldest_first(self):
        b = self.backend([(200, {}, json.dumps([{"createdAt": "2026-11-02", "content": "c", "userName": "sam"}])),
                          (200, {}, json.dumps([{"createdAt": "2026-11-01", "type": "status_changed", "content": "a"}]))])
        self.assertEqual([e["kind"] for e in b.history("t1")], ["status_changed", "comment"])

    def test_rate_limit_says_when_to_retry(self):
        b = self.backend([(429, {"Retry-After": "42"}, "{}")])
        with self.assertRaisesRegex(TicketError, "retry after 42 s"):
            b.get("X-1")

    def test_a_rejected_key_says_how_to_reset_it(self):
        b = self.backend([(401, {}, "{}")])
        with self.assertRaisesRegex(TicketError, "tm reset-key"):
            b.get("X-1")


if __name__ == "__main__":
    unittest.main()
