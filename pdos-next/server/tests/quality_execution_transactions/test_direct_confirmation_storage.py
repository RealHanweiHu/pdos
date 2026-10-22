"""Actual app-role immutable preview material, consumption and rollback guards."""

# ruff: noqa: F401,F811 -- register the existing real quality/launch fixture tree

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from quality_execution.fixtures import (
    accepted_work,
    command,
    create_issue,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from test_project_first_plan import cmd, post
from test_resource_dependency_execution import engines
from verification_launch import fixtures as launch

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import ResourceOccupancy
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.test_resources.models import SampleRunUsage, TestResourceReservation
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.service import digest

OPERATIONS = (
    "quality.issue.triage",
    "quality.issue.containment.record",
    "test.run.start",
)


def _session(work, *, owner=False):
    return tenant_session(
        work.setup.admin if owner else work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    )


def _ordinary_owner(session):
    # The verified TEST_DATABASE_URL is a bootstrap connection, not the table
    # owner. This transaction-local role switch keeps the tenant scope intact.
    session.execute(text("SET LOCAL ROLE pdos_next_owner"))
    assert session.execute(
        text("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
    ).one() == ("pdos_next_owner", False, False)
    assert session.execute(
        text(
            "SELECT pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity "
            "FROM pg_class WHERE oid='public.confirmations'::regclass"
        )
    ).one() == ("pdos_next_owner", True, True)


def _material(session, token):
    return session.scalar(
        text("SELECT to_jsonb(c) FROM public.confirmations c WHERE token_hash=:token"),
        {"token": digest(token)},
    )


def _effects(work):
    with _session(work) as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (
                QualityIssueVersion,
                QualityIssueCurrent,
                FormalVerificationRequest,
                VerificationRunVersion,
                VerificationRunCurrent,
                TestResourceReservation,
                ResourceOccupancy,
                SampleRunUsage,
                Confirmation,
                Receipt,
                RequestKey,
                Audit,
                Outbox,
            )
        }


def _refused(session, statement, *, sqlstate="23514"):
    with pytest.raises(DBAPIError) as raised, session.begin_nested():
        session.execute(statement)
    assert raised.value.orig.sqlstate == sqlstate
    if sqlstate == "23514":
        assert "Direct confirmation" in str(raised.value.orig)


def _owner_delete_refused(work, token, expected):
    with _session(work, owner=True) as session:
        _ordinary_owner(session)
        assert _material(session, token) == expected
        _refused(
            session,
            delete(Confirmation).where(
                Confirmation.tenant_id == work.setup.tenant,
                Confirmation.category_id == work.setup.category,
                Confirmation.actor_id == work.quality.ctx.actor_id,
                Confirmation.token_hash == digest(token),
            ),
        )
        assert _material(session, token) == expected


def _preview(request, monkeypatch, operation):
    if operation == "test.run.start":
        work = request.getfixturevalue("launch_work")
        launch.promised(work)
        launch.advance_clock(work, monkeypatch)
        value = launch.command(work, operation)
    else:
        work = request.getfixturevalue("quality_work")
        publish_policy(work)
        created, _ = create_issue(work)
        issue_id = created["result"]["issue_id"]
        triage = command(
            work,
            "quality.issue.triage",
            {
                "issue_id": issue_id,
                "expected_issue_revision": 1,
                "reason": "Named direct confirmation storage probe",
            },
        )
        if operation == "quality.issue.triage":
            value = triage
        else:
            preview = post(work.quality, triage, True)
            assert preview.status_code == 200, preview.text
            committed = post(work.quality, preview.json()["command"])
            assert committed.status_code == 200, committed.text
            value = command(
                work,
                operation,
                {
                    "issue_id": issue_id,
                    "expected_issue_revision": 2,
                    "action": {
                        "id": str(uuid4()),
                        "text": "Synthetic containment observed by the named person.",
                        "executor_id": str(work.quality.human),
                        "evidence": [work.containment_source.model_dump(mode="json")],
                        "at": {
                            "occurred_at": now().isoformat(),
                            "original_timezone": "UTC",
                            "source": work.containment_source.model_dump(mode="json"),
                        },
                    },
                },
            )
    response = post(work.quality, value, True)
    assert response.status_code == 200, response.text
    confirmed = response.json()["command"]
    assert confirmed["operation"] == operation
    return work, confirmed


@pytest.mark.parametrize("operation", OPERATIONS)
def test_direct_preview_storage_is_immutable_and_normal_consumption_is_monotonic(
    request, monkeypatch, operation
):
    work, confirmed = _preview(request, monkeypatch, operation)
    token = confirmed["payload"]["confirmation_token"]
    before_effects = _effects(work)
    with _session(work) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        original = _material(session, token)
        assert original and original["consumed"] is False
        changed_snapshot = deepcopy(original["snapshot"])
        changed_snapshot["unreviewed_effect"] = "Never persist this altered preview"
        query = update(Confirmation).where(Confirmation.token_hash == digest(token))
        for values in (
            {"snapshot": changed_snapshot},
            {"payload_digest": digest(uuid4())},
            {"token_hash": digest(uuid4())},
            {"expires_at": now() + timedelta(hours=1)},
            {"operation": "evidence.claim.record"},
            {"operation": next(op for op in OPERATIONS if op != operation)},
            {"revision": original["revision"] + 1},
        ):
            _refused(session, query.values(**values))
            assert _material(session, token) == original
        _refused(
            session,
            delete(Confirmation).where(Confirmation.token_hash == digest(token)),
            sqlstate="42501",
        )
        assert _material(session, token) == original
        # An unchanged consumption flag is a legal no-op, not a new business effect.
        assert session.execute(query.values(consumed=False)).rowcount == 1
        assert _material(session, token) == original
    _owner_delete_refused(work, token, original)
    assert _effects(work) == before_effects

    committed = post(work.quality, confirmed)
    assert committed.status_code == 200, committed.text
    committed_effects = _effects(work)
    with _session(work) as session:
        consumed = _material(session, token)
        assert consumed == {**original, "consumed": True}
        query = update(Confirmation).where(Confirmation.token_hash == digest(token))
        _refused(session, query.values(consumed=False))
        _refused(session, query.values(snapshot=changed_snapshot))
        _refused(
            session,
            delete(Confirmation).where(Confirmation.token_hash == digest(token)),
            sqlstate="42501",
        )
        assert session.execute(query.values(consumed=True)).rowcount == 1
        assert _material(session, token) == consumed
    _owner_delete_refused(work, token, consumed)
    assert _effects(work) == committed_effects
    replayed = post(work.quality, confirmed)
    assert replayed.status_code == 200 and replayed.json()["id"] == committed.json()["id"]
    assert _effects(work) == committed_effects


def test_other_actual_preview_cannot_be_relabelled_as_any_direct_operation(quality_work):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work, 0)
    second, _ = create_issue(work, 1)
    value = command(
        work,
        "quality.issue.merge",
        {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "sources": [{"id": second["result"]["issue_id"], "revision": 1}],
            "reason": "Synthetic actual non-direct T1 proof for operation-binding checks",
        },
    )
    response = post(work.quality, value, True)
    assert response.status_code == 200, response.text
    token = response.json()["command"]["payload"]["confirmation_token"]
    before = _effects(work)
    with _session(work) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        original = _material(session, token)
        assert original["operation"] == "quality.issue.merge" and original["consumed"] is False
        for operation in OPERATIONS:
            _refused(
                session,
                update(Confirmation)
                .where(Confirmation.token_hash == digest(token))
                .values(operation=operation),
            )
            assert _material(session, token) == original
        _refused(
            session,
            delete(Confirmation).where(Confirmation.token_hash == digest(token)),
            sqlstate="42501",
        )
        # Unrelated operations keep their existing update behavior.
        savepoint = session.begin_nested()
        try:
            changed = session.execute(
                update(Confirmation)
                .where(Confirmation.token_hash == digest(token))
                .values(expires_at=now() + timedelta(hours=1))
            )
            assert changed.rowcount == 1
            assert _material(session, token) != original
        finally:
            savepoint.rollback()
        assert _material(session, token) == original
    # The ordinary table owner has DELETE permission while remaining subject to
    # the same forced RLS and scope. Unrelated deletion keeps its old behavior.
    with _session(work, owner=True) as session:
        _ordinary_owner(session)
        assert _material(session, token) == original
        savepoint = session.begin_nested()
        try:
            removed = session.execute(
                delete(Confirmation).where(
                    Confirmation.tenant_id == work.setup.tenant,
                    Confirmation.category_id == work.setup.category,
                    Confirmation.actor_id == work.quality.ctx.actor_id,
                    Confirmation.token_hash == digest(token),
                )
            )
            assert removed.rowcount == 1
            assert _material(session, token) is None
        finally:
            savepoint.rollback()
        assert _material(session, token) == original
    assert _effects(work) == before
