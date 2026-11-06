import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fleet  # noqa: E402

CFG = {"FLEET_MAX_ATTEMPTS": "1", "FLEET_PICK_LABEL": ""}
PROJECTS = {"p1": {"repo": "/r"}, "<tracker-project-id>": {"repo": "/x"}}


def ticket(key, status="to-do", priority=None, created="2026-01-01"):
    return {"id": f"id-{key}", "key": key, "title": key, "status": status, "priority": priority,
            "created_at": created}


class Backend:
    def __init__(self, tickets, labels=None):
        self.tickets, self.label_map, self.asked = tickets, labels or {}, []

    def list(self, project_id, status):
        self.asked.append((project_id, status))
        return self.tickets

    def labels(self, ticket_id):
        return self.label_map.get(ticket_id, [])


class PickableTest(unittest.TestCase):
    def keys(self, backend, runs=(), cfg=CFG):
        return [t["key"] for t in fleet.pickable(backend, cfg, list(runs), PROJECTS)]

    def test_reads_the_pick_column_of_mapped_projects_only(self):
        b = Backend([ticket("A-1")])
        out = fleet.pickable(b, CFG, [], PROJECTS)
        self.assertEqual(b.asked, [("p1", "to-do")])
        self.assertEqual((out[0]["repo"], out[0]["project_id"]), ("/r", "p1"))

    def test_skips_other_statuses(self):
        self.assertEqual(self.keys(Backend([ticket("A-1", status="in-review")])), [])

    def test_priority_first_then_oldest(self):
        b = Backend([ticket("A-1", "to-do", None, "2026-01-01"), ticket("A-2", "to-do", "low", "2026-03-01"),
                     ticket("A-3", "to-do", "urgent", "2026-04-01"), ticket("A-4", "to-do", "low", "2026-02-01")])
        self.assertEqual(self.keys(b), ["A-3", "A-4", "A-2", "A-1"])

    def test_active_runs_are_matched_by_key(self):
        self.assertEqual(self.keys(Backend([ticket("A-1")]), [{"ticket_id": "A-1", "state": "running"}]), [])

    def test_out_of_attempts_until_a_retry_clears_them(self):
        b = Backend([ticket("A-1")])
        self.assertEqual(self.keys(b, [{"ticket_id": "A-1", "state": "failed"}]), [])
        self.assertEqual(self.keys(b, [{"ticket_id": "A-1", "state": "failed", "retry_cleared": True}]), ["A-1"])

    def test_pick_label_ignores_case(self):
        b = Backend([ticket("A-1"), ticket("A-2")], {"id-A-1": ["Agent"]})
        self.assertEqual(self.keys(b, cfg={**CFG, "FLEET_PICK_LABEL": "agent"}), ["A-1"])


if __name__ == "__main__":
    unittest.main()
