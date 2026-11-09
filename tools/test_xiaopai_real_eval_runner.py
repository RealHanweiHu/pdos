"""D256: how the runner waits for a parent Run; pure, no DB, HTTP server or model."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import xiaopai_real_eval_runner as runner

UNKNOWN = "EXTERNAL_OUTCOME_UNKNOWN"


class Response:
    def __init__(self, value, status_code=200):
        self.value, self.status_code, self.text = value, status_code, ""

    def json(self):
        return self.value


class Client:
    def __init__(self, views=()):
        self.views, self.posts = list(views), []

    def get(self, path, headers=None):
        if path.endswith("/events"):
            return Response({"items": []})
        return Response(self.views.pop(0) if len(self.views) > 1 else self.views[0])

    def post(self, path, headers=None, json=None):
        self.posts.append(path)
        if path.endswith("/agent-runs"):
            return Response({"run_id": str(uuid4()), "session_id": str(uuid4())}, 202)
        return Response({"status": "cancelled"})


class StopKindTests(unittest.TestCase):
    def test_waiting_input_is_a_question_unless_its_code_marks_reconciliation(self):
        cases = {
            ("waiting_input", None): "question",
            ("waiting_input", "SOURCE_UNAVAILABLE"): "question",
            ("waiting_input", UNKNOWN): "reconciliation",
            ("queued", None): "running",
            ("running", None): "running",
        }
        for state in runner.TERMINAL:
            cases[(state, None)] = cases[(state, UNKNOWN)] = "terminal"
        for (state, code), kind in cases.items():
            self.assertEqual(runner.stop_kind(state, code), kind, (state, code))


class SettleTests(unittest.TestCase):
    def settle(self, status, states, *, events=(), limit=1200):
        """Run settle_for_continuation over a scripted ledger; return (result, posts)."""
        person = SimpleNamespace(category="category", client=Client(), headers={})
        previous = {"run_id": str(uuid4()), "status": status, "events": list(events)}
        script = iter(states)
        clock = iter(range(0, 10_000, 5))
        with mock.patch.object(runner, "ledger_state", lambda *_: next(script)), \
                mock.patch.object(runner, "capture_run", lambda _person, run: run), \
                mock.patch.object(runner.time, "sleep", lambda _seconds: None), \
                mock.patch.object(runner.time, "monotonic", lambda: next(clock)):
            result = runner.settle_for_continuation(person, previous, limit=limit)
        return result, person.client.posts

    def test_a_question_after_the_observation_limit_is_cancelled_and_the_cell_goes_on(self):
        # CTX-01 round 25: 31 minutes of work, then a question; it used to time out.
        result, posts = self.settle("observation_timeout", [
            ("running", None), ("running", None), ("waiting_input", None),
            ("cancelled", None),
        ])
        settled, record = result
        self.assertEqual(len(posts), 1)
        self.assertTrue(posts[0].endswith("/cancel"))
        self.assertEqual(record["intervention"], "cancelled_open_question")
        self.assertEqual(record["interventions"],
                         ["awaited_unobserved_completion", "cancelled_open_question"])
        self.assertEqual(record["final_status"], "cancelled")
        self.assertEqual(settled["settled_by"], "cancelled_open_question")

    def test_pending_reconciliation_after_the_observation_limit_is_awaited_not_cancelled(self):
        result, posts = self.settle("observation_timeout", [
            ("running", None), ("waiting_input", UNKNOWN), ("waiting_input", UNKNOWN),
            ("failed", UNKNOWN),
        ])
        self.assertEqual(posts, [])
        self.assertEqual(result[1]["intervention"], "awaited_automatic_reconciliation")
        self.assertEqual(result[1]["final_status"], "failed")

    def test_waiting_input_is_told_apart_by_its_error_code_not_by_recent_events(self):
        # No reconciliation_required event in view: the code alone decides.
        result, posts = self.settle("waiting_input", [
            ("waiting_input", UNKNOWN), ("completed", None),
        ])
        self.assertEqual(posts, [])
        self.assertEqual(result[1]["intervention"], "awaited_automatic_reconciliation")
        # A question is cancelled even when an old reconciliation event is recent.
        result, posts = self.settle("waiting_input", [
            ("waiting_input", None), ("cancelled", None),
        ], events=[{"body": {"type": "reconciliation_required"}}])
        self.assertEqual(len(posts), 1)
        self.assertEqual(result[1]["intervention"], "cancelled_open_question")

    def test_an_unobserved_completion_is_only_awaited(self):
        result, posts = self.settle("observation_timeout", [
            ("running", None), ("partial", None),
        ])
        self.assertEqual(posts, [])
        self.assertEqual(result[1]["intervention"], "awaited_unobserved_completion")

    def test_a_cancel_is_sent_once_even_if_the_ledger_lags(self):
        _result, posts = self.settle("waiting_input", [
            ("waiting_input", None), ("waiting_input", None), ("cancelled", None),
        ])
        self.assertEqual(len(posts), 1)

    def test_terminal_parents_need_no_settling(self):
        for status in runner.TERMINAL:
            self.assertIsNone(self.settle(status, [])[0])

    def test_a_run_that_never_settles_raises_with_what_it_waited_for(self):
        with self.assertRaisesRegex(RuntimeError, "awaited_automatic_reconciliation"):
            self.settle("observation_timeout", [("waiting_input", UNKNOWN)] * 1000, limit=60)


class ObservationTests(unittest.TestCase):
    def test_observation_stops_at_either_kind_of_waiting_input(self):
        for code in (None, UNKNOWN):
            with tempfile.TemporaryDirectory() as folder, \
                    mock.patch.object(runner, "EVIDENCE", Path(folder)), \
                    mock.patch.object(runner, "PRIVATE", Path(folder) / "private"), \
                    mock.patch.object(runner.time, "sleep", lambda _seconds: None):
                client = Client([{"status": "running", "error_code": None},
                                 {"status": "waiting_input", "error_code": code}])
                person = SimpleNamespace(category="category", client=client, headers={})
                result = runner.run_request(person, "CTX-00", {"goal": "g"}, label=f"t-{code}")
                self.assertEqual(result["status"], "waiting_input")


if __name__ == "__main__":
    unittest.main()
