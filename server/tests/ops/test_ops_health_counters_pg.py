"""ops_health_counters: numbers only, one tenant, technical dispatch role only (D213).

Model call rows are planted with triggers and foreign keys off (replica role) in the
isolated test database: the test is about what the function counts, not about how
the kernel writes calls. They are removed again before the test ends.
"""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from projects.test_project_first_plan import cmd, post
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from pdos_next.core.database import tenant_session
from pdos_next.core.models import now

BINDING = {
    "kind": "model",
    "model_version": "synthetic-offline-v1",
    "model_route_digest": "a" * 64,
    "tool_definitions_digest": "b" * 64,
    "cancel_epoch": 0,
    "prompt_digest": "c" * 64,
    "loaded_skills": [],
    "isolation": "main",
}


def _counters(engine, tenant, window=900, session_tenant=None):
    with tenant_session(engine, session_tenant or tenant) as session:
        return (
            session.execute(
                text("SELECT * FROM ops_health_counters(:t,:w)"), {"t": tenant, "w": window}
            )
            .mappings()
            .all()
        )


def _plant_calls(admin, tenant, states):
    ids = []
    with admin.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for state, age in states:
            identity = uuid4()
            ids.append(identity)
            connection.execute(
                text(
                    "INSERT INTO agent_tool_calls(id,tenant_id,created_at,run_id,call_key,tool,"
                    "input_digest,state,reserved_tokens,charged_tokens,cost_pricing,cost_state,"
                    "cost_reserved_micro_usd,cost_charged_micro_usd,input_token_reservation,"
                    "output_token_reservation,actual_input_tokens,actual_output_tokens,"
                    "execution_binding) VALUES (:id,:t,:at,:run,:key,'model',:digest,:state,"
                    "0,0,'{}'::jsonb,'unmetered',0,0,0,0,0,0,CAST(:binding AS jsonb))"
                ),
                {
                    "id": identity,
                    "t": tenant,
                    "at": now() - age,
                    "run": uuid4(),
                    "key": f"ops-{identity}",
                    "digest": "d" * 64,
                    "state": state,
                    "binding": json.dumps(BINDING),
                },
            )
    return ids


def _remove(admin, ids):
    with admin.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(text("DELETE FROM agent_tool_calls WHERE id = ANY(:ids)"), {"ids": ids})


def test_counts_pending_events_and_model_outcomes_for_one_tenant(setup):
    before = _counters(setup.dispatch, setup.tenant)
    assert len(before) == 1 and before[0]["outbox_pending"] == 0
    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "ops counter",
                "content": "synthetic",
                "source_label": "ops test",
                "visibility": "category",
            },
        ),
    )
    assert response.status_code == 200, response.text
    minutes = timedelta(minutes=1)
    ids = _plant_calls(
        setup.admin,
        setup.tenant,
        [
            ("completed", minutes),
            ("completed", minutes),
            ("failed", minutes),
            ("unknown", minutes),
            ("reconciled", minutes),
            ("failed", timedelta(hours=2)),  # outside the 15-minute window
            ("started", timedelta(minutes=20)),  # open too long
            ("started", minutes),  # still normal
        ],
    )
    try:
        [row] = _counters(setup.dispatch, setup.tenant)
        assert row["outbox_pending"] >= 1 and row["outbox_retrying"] == 0
        assert row["outbox_oldest_seconds"] >= 0
        assert (row["model_calls_finished"], row["model_calls_failed"]) == (5, 2)
        assert row["model_calls_open_long"] == 1
        assert set(row) == {
            "outbox_pending",
            "outbox_retrying",
            "outbox_oldest_seconds",
            "model_calls_finished",
            "model_calls_failed",
            "model_calls_open_long",
        }
        # A wider window includes the old failure; the window is bounded to one day.
        [wide] = _counters(setup.dispatch, setup.tenant, window=10 * 86400)
        assert (wide["model_calls_finished"], wide["model_calls_failed"]) == (6, 3)
        # Another tenant's session cannot read this tenant's counters.
        assert _counters(setup.dispatch, setup.tenant, session_tenant=uuid4()) == []
    finally:
        _remove(setup.admin, ids)


@pytest.mark.parametrize("role", ["engine", "auth"])
def test_only_the_dispatch_role_may_execute(setup, role):
    with pytest.raises(ProgrammingError, match="permission denied"):
        _counters(getattr(setup, role), setup.tenant)
