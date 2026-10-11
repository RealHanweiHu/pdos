"""Explicit B4 checkpoint: thirty eligible independent real commits per path.

Invoke through s0_profile_checkpoint.py after the shared regression finishes.
This file is outside default test discovery. All facts and qualifications are
synthetic in the explicitly verified independent PostgreSQL target.
"""

# ruff: noqa: F401,F811 -- pytest's imported fixture dependency tree is intentional
from collections import defaultdict

import pytest
from conftest import setup
from s0_b8_performance_summary import b4_case_groups
from s0_performance import MAX_ATTEMPTS, SAMPLES, eligible_rows, profile_case_calls
from test_resource_dependency_execution import (
    engines,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
)
from verification_launch import fixtures as launch

ROWS = defaultdict(list)


def complete():
    return len(ROWS) == 12 and all(len(eligible_rows(rows)) >= SAMPLES for rows in ROWS.values())


@pytest.fixture
def performance_launch_work(request, monkeypatch):
    # Skip unused replacement slots before the expensive real launch preparation.
    if request.node.callspec.indices["performance_launch_work"] == 0:
        ROWS.clear()
    if complete():
        pytest.skip("Performance replacement slots unused")
    fixture = launch_work.__wrapped__(
        ready_work=request.getfixturevalue("ready_work"),
        monkeypatch=monkeypatch,
        request=request,
    )
    try:
        yield next(fixture)
    finally:
        fixture.close()


@pytest.mark.parametrize(
    "performance_launch_work",
    [{"window_minutes": 45, "fact_minutes": 60} for _ in range(MAX_ATTEMPTS)],
    indirect=True,
    ids=[f"sample-{i + 1}" for i in range(MAX_ATTEMPTS)],
)
def test_actual_read_preview_start_and_original_recovery(
    performance_launch_work, monkeypatch, request
):
    work = performance_launch_work
    before = launch.listing(work)
    assert launch.current(work, before)["status"] == "accepted"
    require_current_resource(work, before)
    launch.promised(work)
    launch.advance_clock(work, monkeypatch)
    value = launch.command(work, "test.run.start")
    root = f"/v1/categories/{work.setup.category}/commands"
    preview = work.quality.client.post(root + "/preview", json=value, headers=work.quality.headers)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    started = work.quality.client.post(root, json=prepared, headers=work.quality.headers)
    assert started.status_code == 200, started.text
    assert started.json()["operation"] == "test.run.start"
    recovered = work.quality.client.post(root, json=prepared, headers=work.quality.headers)
    assert recovered.status_code == 200 and recovered.json()["id"] == started.json()["id"]
    after = launch.listing(work)
    assert launch.fixed_run(work, after)["status"] == "running"
    require_current_resource(work, after)
    calls = profile_case_calls(request.node.nodeid)
    for label, rows in b4_case_groups(calls).items():
        ROWS[label].extend(rows)
    if (
        request.node.callspec.indices["performance_launch_work"] == MAX_ATTEMPTS - 1
        and not complete()
    ):
        pytest.skip("Performance sampling pending: replacement budget exhausted")


def require_current_resource(work, view):
    assert any(
        row["id"] == str(work.test_fact_id)
        and row["current"] is True
        and row["source_status"] == "current"
        for row in view["resource_facts"]
    )
