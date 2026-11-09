"""D268: guard cost by session length, on an isolated pdos_test with an offline provider.

Copy into server/tests/agent/enterprise_search/ and run it like a PG test, for example
    D268_OUT=/path/out.json D268_ROUNDS=12 pytest -q test_d268_guard_profile.py
with TEST_DATABASE_URL from tools/local_environment.py. Each round is one continued
Run (search + one extract). Before each round runs, it measures adapter.guard and
check_conversation on that round's frozen scope: best-of-3 time, SQL statements,
and at the last round the statements grouped by text with their time.
"""

import json
import os
import re
import time

from sqlalchemy import event
from tests.agent.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.agent.enterprise_search.test_retrieval_pg import index, register


class Statements:
    def __init__(self, engine):
        self.engine, self.count, self.by_text, self.times = engine, 0, {}, {}

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self.before)
        event.listen(self.engine, "after_cursor_execute", self.after)
        return self

    def before(self, connection, _cursor, statement, *_args):
        self.count += 1
        key = re.sub(r"\s+", " ", statement)[:150]
        self.by_text[key] = self.by_text.get(key, 0) + 1
        connection.info["d268_started"] = time.perf_counter()

    def after(self, connection, _cursor, statement, *_args):
        key = re.sub(r"\s+", " ", statement)[:150]
        started = connection.info.pop("d268_started", None)
        if started is not None:
            self.times[key] = self.times.get(key, 0) + time.perf_counter() - started

    def __exit__(self, *_):
        event.remove(self.engine, "before_cursor_execute", self.before)
        event.remove(self.engine, "after_cursor_execute", self.after)


def measure(engine, call, repeat=3):
    best = count = None
    for _ in range(repeat):
        with Statements(engine) as statements:
            started = time.perf_counter()
            call()
            elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
        count = statements.count
    return round(best * 1000, 1), count


def test_guard_cost_by_session_length(setup):
    rounds = int(os.environ.get("D268_ROUNDS", "12"))
    for number in range(3):
        identity = register(setup, f"漏气记录 {number}", f"接口漏气。措施：更换密封圈{number}。")
        index(setup, identity)
    rows, previous, session_id = [], None, None
    for n in range(rounds + 1):
        owner, scope, host, adapter = fixture(
            setup, SyntheticClient(), session_id=session_id, continued_from_id=previous)
        owner.project_context(scope, "继续核对")
        guard_ms, guard_sql = measure(
            setup.engine, lambda adapter=adapter, scope=scope: adapter.guard(scope))
        conversation_ms, conversation_sql = measure(
            setup.engine, lambda owner=owner, scope=scope: owner.check_conversation(scope))
        row = {"prior_rounds": n, "carried": len(adapter._carried(scope)[0]),
               "guard_ms": guard_ms, "guard_sql": guard_sql,
               "conversation_ms": conversation_ms, "conversation_sql": conversation_sql}
        if n == rounds:
            with Statements(setup.engine) as statements:
                adapter.guard(scope)
            row["guard_statements"] = sorted(
                ((text, count, round(statements.times.get(text, 0) * 1000, 1))
                 for text, count in statements.by_text.items()), key=lambda item: -item[2])[:12]
        rows.append(row)
        assert execute(owner, scope, host)["status"] == "completed"
        with owner.store.transaction(scope) as (_session, run):
            session_id = run.session_id
        previous = scope.run_id
    with open(os.environ.get("D268_OUT", "d268.json"), "w") as stream:
        json.dump(rows, stream, ensure_ascii=False, indent=1)
