"""Heartbeat failure isolation and fixed approved renewal policy; no database."""

import re
from importlib import import_module
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest

from app.ai.budget_adoption import approved_budget_profile
from app.ai.lease_heartbeat import RENEW_SECONDS, AgentLeaseLostError, LeaseHeartbeat


def test_heartbeat_failure_stops_renewal_and_fences_the_caller() -> None:
    called = Event()
    calls: list[int] = []

    def renew() -> NoReturn:
        calls.append(1)
        called.set()
        raise OSError("synthetic database outage")

    heartbeat = LeaseHeartbeat(renew, interval=0.01)
    heartbeat.start()
    assert called.wait(2)
    heartbeat.close()
    with pytest.raises(AgentLeaseLostError, match="AGENT_RUN_LEASE_LOST"):
        heartbeat.require_current()
    assert calls == [1]


def test_closing_scope_does_not_schedule_another_renewal() -> None:
    calls: list[int] = []
    heartbeat = LeaseHeartbeat(lambda: calls.append(1), interval=60)
    heartbeat.start()
    heartbeat.close()
    assert calls == []


def test_all_approved_profiles_match_database_lease_and_heartbeat_interval() -> None:
    for key in ("short", "work_package", "research_discussion"):
        profile = approved_budget_profile(key)
        assert profile.renew_seconds == RENEW_SECONDS == 20
        assert profile.lease_seconds == 60


def test_dba_template_matches_immutable_migration_expiry_functions() -> None:
    migration = import_module("migrations.versions.0071_agent_lease_expiry")
    dispatch = import_module("migrations.versions.0075_event_trigger_scheduling")
    authorization = import_module("migrations.versions.0079_event_authorization")
    pauses = import_module("migrations.versions.0096_event_run_pauses")
    source = (
        Path(__file__).resolve().parents[2] / "infra/postgres/security/agent-runtime.sql"
    ).read_text()

    def definition(sql: str, name: str) -> str:
        start = sql.index("CREATE OR REPLACE FUNCTION " + name + "(")
        opening = re.search(r"AS\s+(\$\w*\$)", sql[start:])
        assert opening is not None
        terminator = opening.group(1) + ";"
        end = sql.index(terminator, start + opening.end()) + len(terminator)
        return sql[start:end]

    for signature, old, new in migration.FUNCTIONS:
        name = signature.split("(")[0]
        expected = pauses.CLAIM if name == "cehub_ai.claim_agent_run" else new
        assert definition(source, name) == definition(expected, name)
        assert old != new
    for name, expected in (
        ("agent_lease_is_current", authorization.LEASE),
        ("renew_agent_run_lease", dispatch.HELPERS),
    ):
        assert definition(source, "cehub_ai." + name) == definition(expected, "cehub_ai." + name)
