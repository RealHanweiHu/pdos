"""Profile a real marked-database pytest path; record shapes/counts, never parameters."""

import hashlib
import itertools
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict
from contextvars import ContextVar
from pathlib import Path

from local_environment import SERVER, environment, read_state, verified
from s0_performance import (
    LOAD_POLICY,
    PROFILE_CALLS,
    finish_sample_load,
    record_profile_call,
    start_sample_load,
)
from s0_source_manifest import snapshot


def main():
    destination = Path(sys.argv[1]).resolve()
    if destination.exists():
        raise RuntimeError("Preserve completed checkpoint evidence")
    initial_sources = snapshot()
    PROFILE_CALLS.clear()
    if os.environ.get("S0_B8_TARGET") == "1":
        import s0_b8_environment as checkpoint

        checkpoint.state()
    state = verified(read_state())
    os.environ.update(environment(state))
    sys.path.insert(0, str(SERVER))
    sys.path.insert(0, str(SERVER / "tests"))
    os.chdir(SERVER)
    import pytest
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from starlette.testclient import TestClient

    request_scope = ContextVar("profile_request", default=("fixture", "", "", 0))
    request_ids = itertools.count(1)
    lock = threading.Lock()
    sql = defaultdict(lambda: {"count": 0, "seconds": 0.0, "shapes": set()})
    calls = []
    read_callers = []
    phase = ContextVar("profile_pytest_phase", default=("fixture", ""))
    original = TestClient.request

    class PhasePlugin:
        failed = False
        pending = False

        def pytest_runtest_logreport(self, report):
            self.failed = self.failed or report.failed
            if report.skipped and "Performance replacement slots unused" not in str(
                report.longrepr
            ):
                self.pending = True

        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_setup(self, item):
            phase.set(("setup", item.nodeid))

        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_call(self, item):
            phase.set(("call", item.nodeid))

        @pytest.hookimpl(tryfirst=True)
        def pytest_runtest_teardown(self, item):
            phase.set(("teardown", item.nodeid))

    def request(client, method, url, *args, **kwargs):
        path = str(url).split("?")[0]
        path = re.sub(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", "{id}", path)
        operation = (kwargs.get("json") or {}).get("operation", "")
        if not isinstance(operation, str) or not re.fullmatch(r"[a-z0-9_.-]{0,100}", operation):
            operation = ""
        request_id = next(request_ids)
        key = (method, path, operation, request_id)
        test_phase, test_node = phase.get()
        token = request_scope.set(key)
        load_start = start_sample_load()
        started = time.perf_counter()
        status = None
        try:
            response = original(client, method, url, *args, **kwargs)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - started
            load_record = finish_sample_load(load_start)
            with lock:
                call = {
                    "method": method,
                    "path": path,
                    "operation": operation,
                    "seconds": elapsed,
                    "status": status,
                    "request_id": request_id,
                    "phase": test_phase,
                    "test_node": test_node,
                    **load_record,
                }
                calls.append(call)
                record_profile_call(call)
            request_scope.reset(token)

    def before(_conn, _cursor, statement, _params, context, _many):
        context._s0_started = time.perf_counter()
        context._s0_scope = request_scope.get()
        match = re.search(
            r"\b(?:FROM|UPDATE|INTO)\s+(?:public\.)?([a-z_][a-z0-9_]*)", statement, re.I
        )
        routine = re.match(r"\s*SELECT\s+([a-z_][a-z0-9_]*)\s*\(", statement, re.I)
        context._s0_table = (
            match.group(1).lower()
            if match
            else "routine:" + routine.group(1).lower()
            if routine
            else "routine"
        )
        context._s0_shape = hashlib.sha256(statement.encode()).hexdigest()
        if os.environ.get("S0_TRACE_READ_CALLERS") == "1" and (
            context._s0_scope[1].endswith("/verification-launch")
            or context._s0_scope[1].endswith("/verification-launch/inputs")
        ):
            frames, frame = [], sys._getframe()
            while frame is not None:
                name = frame.f_code.co_filename
                if "/pdos_next/" in name:
                    frames.append(
                        (name.split("/pdos_next/", 1)[1], frame.f_lineno, frame.f_code.co_name)
                    )
                frame = frame.f_back
            del frame
            read_callers.append(
                {"request_id": context._s0_scope[3], "table": context._s0_table, "frames": frames}
            )

    def after(_conn, _cursor, _statement, _params, context, _many):
        key = (*context._s0_scope, context._s0_table)
        with lock:
            record = sql[key]
            record["count"] += 1
            record["seconds"] += time.perf_counter() - context._s0_started
            record["shapes"].add(context._s0_shape)

    TestClient.request = request
    event.listen(Engine, "before_cursor_execute", before)
    event.listen(Engine, "after_cursor_execute", after)
    code = 2
    phases = PhasePlugin()
    try:
        code = pytest.main(sys.argv[2:], plugins=[phases])
    finally:
        TestClient.request = original
        event.remove(Engine, "before_cursor_execute", before)
        event.remove(Engine, "after_cursor_execute", after)
        rows = [
            {
                "method": key[0],
                "path": key[1],
                "operation": key[2],
                "request_id": key[3],
                "table": key[4],
                "count": value["count"],
                "seconds": value["seconds"],
                "shape_count": len(value["shapes"]),
            }
            for key, value in sql.items()
        ]
        for call in calls:
            selected = [row for row in rows if row["request_id"] == call["request_id"]]
            call["sql_count"] = sum(row["count"] for row in selected)
            call["sql_seconds"] = sum(row["seconds"] for row in selected)
        destination.write_text(
            json.dumps(
                {
                    "test_exit": int(code),
                    "outcome": (
                        "failed"
                        if phases.failed
                        else "pending"
                        if phases.pending or code
                        else "passed"
                    ),
                    "load_policy": LOAD_POLICY,
                    "source_sha256": initial_sources,
                    "source_unchanged": snapshot() == initial_sources,
                    "http": calls,
                    "sql": rows,
                    "read_callers": read_callers,
                },
                indent=2,
            )
            + "\n"
        )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
