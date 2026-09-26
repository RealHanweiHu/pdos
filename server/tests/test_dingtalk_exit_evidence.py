from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, update

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.integrations.dingtalk_exit_evidence import (
    DingTalkExitEvidenceError,
    capture_dingtalk_exit_baseline,
    parse_dingtalk_exit_baseline,
    serialize_dingtalk_exit_baseline,
    verify_dingtalk_exit_evidence,
)
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
RELEASE_SHA = "8e58e7a0657bfd2a29ba916eb8e25ba07da63d93"


@pytest.fixture(autouse=True)
def isolated_database() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _seed_scope(database_url: str) -> dict[str, UUID]:
    ids = {
        "tenant": uuid4(),
        "owner": uuid4(),
        "approver": uuid4(),
        "workflow": uuid4(),
        "stage": uuid4(),
        "project": uuid4(),
        "gate": uuid4(),
    }
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.tenants.insert().values(
                    id=ids["tenant"], slug="exit-evidence", name="Exit Evidence"
                )
            )
            connection.execute(
                tables.users.insert(),
                [
                    {
                        "id": ids["owner"],
                        "tenant_id": ids["tenant"],
                        "username": "owner",
                        "display_name": "Owner",
                        "role": "owner",
                    },
                    {
                        "id": ids["approver"],
                        "tenant_id": ids["tenant"],
                        "username": "approver",
                        "display_name": "Approver",
                        "role": "quality",
                    },
                ],
            )
            connection.execute(
                tables.workflows.insert().values(
                    id=ids["workflow"],
                    tenant_id=ids["tenant"],
                    code="npd",
                    name="NPD",
                )
            )
            connection.execute(
                tables.stages.insert().values(
                    id=ids["stage"],
                    tenant_id=ids["tenant"],
                    workflow_id=ids["workflow"],
                    code="concept",
                    name="Concept",
                    sequence=1,
                )
            )
            connection.execute(
                tables.projects.insert().values(
                    id=ids["project"],
                    tenant_id=ids["tenant"],
                    workflow_id=ids["workflow"],
                    current_stage_id=ids["stage"],
                    owner_user_id=ids["owner"],
                    code="S5-PILOT",
                    name="Sprint 5 Pilot",
                    status="active",
                )
            )
            connection.execute(
                tables.gates.insert().values(
                    id=ids["gate"],
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    stage_id=ids["stage"],
                    code="G-CONCEPT",
                    name="Concept Gate",
                    status="reviewing",
                )
            )
            connection.execute(
                tables.dingtalk_tenant_bindings.insert().values(
                    tenant_id=ids["tenant"],
                    corp_id="exit-corp",
                    client_id="exit-client",
                    agent_id="12345",
                    robot_code="robot-code",
                    oauth_redirect_uri="https://pdos.example/dingtalk/callback",
                    callback_route_key="exit-event-callback",
                    approval_process_code="approval-process",
                    card_template_id="card-template",
                    card_callback_route_key="exit-card-callback",
                    status="active",
                    configured_by_user_id=ids["owner"],
                )
            )
            connection.execute(
                tables.dingtalk_user_bindings.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": ids["tenant"],
                        "user_id": ids["owner"],
                        "corp_id": "exit-corp",
                        "open_id": "open-owner",
                        "staff_id": "staff-owner",
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": ids["tenant"],
                        "user_id": ids["approver"],
                        "corp_id": "exit-corp",
                        "open_id": "open-approver",
                        "staff_id": "staff-approver",
                    },
                ],
            )
    finally:
        engine.dispose()
    return ids


def _counts(database_url: str) -> tuple[int, int, int, int]:
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.connect() as connection:
            return tuple(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
                for table in (
                    tables.events,
                    tables.audit_log,
                    tables.integration_receipts,
                    tables.integration_outbox,
                )
            )  # type: ignore[return-value]
    finally:
        engine.dispose()


def _record_post_smoke_evidence(
    database_url: str,
    *,
    ids: dict[str, UUID],
    captured_at: datetime,
) -> None:
    now = captured_at.astimezone(UTC) + timedelta(seconds=1)
    group_outbox = uuid4()
    approval_outbox = uuid4()
    card_outbox = uuid4()
    approval_id = uuid4()
    card_id = uuid4()
    approval_event_id = f"exit-approval-{uuid4()}"
    card_event_id = f"exit-card-{uuid4()}"
    engine = create_engine(psycopg_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                tables.events.insert(),
                [
                    {
                        "tenant_id": ids["tenant"],
                        "project_id": None,
                        "actor_user_id": None,
                        "event_id": "exit-login",
                        "event_type": "USER_SIGNED_IN",
                        "schema_version": 1,
                        "source": "auth_service",
                        "entity": "user",
                        "entity_id": ids["owner"],
                        "payload": {"authentication_method": "dingtalk_oauth"},
                        "timestamp": now,
                    },
                    *[
                        {
                            "tenant_id": ids["tenant"],
                            "project_id": ids["project"],
                            "actor_user_id": None,
                            "event_id": f"exit-delivery-{outbox_id}",
                            "event_type": "DINGTALK_NOTIFICATION_DELIVERED",
                            "schema_version": 1,
                            "source": "dingtalk_connector_service",
                            "entity": "integration_outbox",
                            "entity_id": outbox_id,
                            "payload": {
                                "outbox_id": str(outbox_id),
                                "operation": operation,
                            },
                            "timestamp": now,
                        }
                        for outbox_id, operation in (
                            (group_outbox, "group_markdown"),
                            (approval_outbox, "gate_approval_create"),
                            (card_outbox, "interactive_card_create"),
                        )
                    ],
                ],
            )
            connection.execute(
                tables.integration_outbox.insert(),
                [
                    {
                        "id": group_outbox,
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "operation": "group_markdown",
                        "idempotency_key": "exit-group",
                        "payload": {},
                        "status": "succeeded",
                        "attempt_count": 1,
                        "remote_reference": "group-reference",
                        "created_at": now,
                        "updated_at": now,
                        "completed_at": now,
                    },
                    {
                        "id": approval_outbox,
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "operation": "gate_approval_create",
                        "idempotency_key": "exit-approval",
                        "payload": {"approval_id": str(approval_id)},
                        "status": "succeeded",
                        "attempt_count": 1,
                        "remote_reference": "approval-reference",
                        "created_at": now,
                        "updated_at": now,
                        "completed_at": now,
                    },
                    {
                        "id": card_outbox,
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "operation": "interactive_card_create",
                        "idempotency_key": "exit-card",
                        "payload": {"card_id": str(card_id)},
                        "status": "succeeded",
                        "attempt_count": 1,
                        "remote_reference": "card-reference",
                        "created_at": now,
                        "updated_at": now,
                        "completed_at": now,
                    },
                ],
            )
            connection.execute(
                tables.dingtalk_approval_instances.insert().values(
                    id=approval_id,
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    gate_id=ids["gate"],
                    outbox_id=approval_outbox,
                    requested_by_user_id=ids["owner"],
                    originator_user_id=ids["owner"],
                    approver_user_id=ids["approver"],
                    request_id="exit-approval-request",
                    remote_instance_id="approval-reference",
                    status="approved",
                    remote_result="agree",
                    created_at=now,
                    updated_at=now,
                    completed_at=now,
                )
            )
            connection.execute(
                tables.integration_receipts.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": ids["tenant"],
                        "channel": "event_aes",
                        "external_id": "approval-event",
                        "deduplication_key": "approval-event",
                        "payload_digest": "a" * 64,
                        "status": "processed",
                        "result_code": "approval_sync_requested",
                        "received_at": now,
                        "processed_at": now,
                    },
                    {
                        "id": uuid4(),
                        "tenant_id": ids["tenant"],
                        "channel": "card_hmac",
                        "external_id": "card-track",
                        "deduplication_key": "card-track:acknowledge",
                        "payload_digest": "b" * 64,
                        "status": "processed",
                        "result_code": "acknowledged",
                        "received_at": now,
                        "processed_at": now,
                    },
                ],
            )
            connection.execute(
                tables.dingtalk_interactive_cards.insert().values(
                    id=card_id,
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    outbox_id=card_outbox,
                    recipient_user_id=ids["approver"],
                    out_track_id="card-track",
                    card_template_id="card-template",
                    action_key="acknowledge",
                    remote_instance_id="card-reference",
                    status="acknowledged",
                    acknowledged_by_user_id=ids["approver"],
                    acknowledged_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                tables.events.insert(),
                [
                    {
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "actor_user_id": None,
                        "event_id": approval_event_id,
                        "event_type": "DINGTALK_APPROVAL_UPDATED",
                        "schema_version": 1,
                        "source": "dingtalk_connector_service",
                        "entity": "dingtalk_approval",
                        "entity_id": approval_id,
                        "payload": {"approval_id": str(approval_id), "status": "approved"},
                        "timestamp": now,
                    },
                    {
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "actor_user_id": None,
                        "event_id": card_event_id,
                        "event_type": "DINGTALK_CARD_ACTION_RECEIVED",
                        "schema_version": 1,
                        "source": "dingtalk_connector_service",
                        "entity": "dingtalk_card",
                        "entity_id": card_id,
                        "payload": {"card_id": str(card_id), "action": "acknowledge"},
                        "timestamp": now,
                    },
                ],
            )
            connection.execute(
                tables.audit_log.insert().values(
                    tenant_id=ids["tenant"],
                    project_id=ids["project"],
                    actor_user_id=ids["approver"],
                    event_id=card_event_id,
                    action="dingtalk.card.acknowledge",
                    entity="dingtalk_card",
                    entity_id=card_id,
                    before_snapshot={"status": "sent"},
                    after_snapshot={"status": "acknowledged"},
                    timestamp=now,
                )
            )
            connection.execute(
                tables.audit_log.insert(),
                [
                    {
                        "tenant_id": ids["tenant"],
                        "project_id": None,
                        "actor_user_id": ids["owner"],
                        "event_id": "exit-login",
                        "action": "user.sign_in",
                        "entity": "user",
                        "entity_id": ids["owner"],
                        "before_snapshot": {"last_signed_in_at": None},
                        "after_snapshot": {"last_signed_in_at": now.isoformat()},
                        "context": {"authentication_method": "dingtalk_oauth"},
                        "timestamp": now,
                    },
                    *[
                        {
                            "tenant_id": ids["tenant"],
                            "project_id": ids["project"],
                            "actor_user_id": None,
                            "event_id": f"exit-delivery-{outbox_id}",
                            "action": "dingtalk.outbox.delivered",
                            "entity": "integration_outbox",
                            "entity_id": outbox_id,
                            "before_snapshot": {},
                            "after_snapshot": {
                                "status": "succeeded",
                                "operation": operation,
                            },
                            "context": {},
                            "timestamp": now,
                        }
                        for outbox_id, operation in (
                            (group_outbox, "group_markdown"),
                            (approval_outbox, "gate_approval_create"),
                            (card_outbox, "interactive_card_create"),
                        )
                    ],
                    {
                        "tenant_id": ids["tenant"],
                        "project_id": ids["project"],
                        "actor_user_id": None,
                        "event_id": approval_event_id,
                        "action": "dingtalk.approval.sync",
                        "entity": "dingtalk_approval",
                        "entity_id": approval_id,
                        "before_snapshot": {"status": "pending"},
                        "after_snapshot": {"status": "approved"},
                        "context": {"system_of_record": "external_evidence_only"},
                        "timestamp": now,
                    },
                ],
            )
    finally:
        engine.dispose()


def test_exit_evidence_is_read_only_fails_before_smoke_and_passes_complete_chain(
    isolated_database: str,
) -> None:
    ids = _seed_scope(isolated_database)
    engine = create_engine(psycopg_database_url(isolated_database))
    before_capture = _counts(isolated_database)
    baseline = capture_dingtalk_exit_baseline(
        engine=engine,
        tenant_slug="exit-evidence",
        project_code="S5-PILOT",
        release_sha=RELEASE_SHA,
    )
    assert _counts(isolated_database) == before_capture
    initial = verify_dingtalk_exit_evidence(
        engine=engine,
        baseline=baseline,
        release_sha=RELEASE_SHA,
    )
    assert initial.automated_ready is False
    assert {check.name for check in initial.checks if not check.passed} >= {
        "password_free_login",
        "group_notification",
        "approval_mirror_gate_truth",
        "approval_callback",
        "card_acknowledgement",
    }
    assert _counts(isolated_database) == before_capture

    _record_post_smoke_evidence(
        isolated_database,
        ids=ids,
        captured_at=baseline.captured_at,
    )
    before_verify = _counts(isolated_database)
    completed = verify_dingtalk_exit_evidence(
        engine=engine,
        baseline=baseline,
        release_sha=RELEASE_SHA,
    )
    engine.dispose()

    assert completed.automated_ready is True
    assert all(check.passed for check in completed.checks)
    assert len(completed.human_attestations_required) == 4
    assert _counts(isolated_database) == before_verify
    serialized = completed.model_dump_json()
    for external_value in (
        "exit-corp",
        "open-owner",
        "staff-owner",
        "group-reference",
        "approval-reference",
        "card-reference",
        "card-track",
    ):
        assert external_value not in serialized


def test_exit_evidence_fails_closed_for_release_gate_drift_and_baseline_tampering(
    isolated_database: str,
) -> None:
    ids = _seed_scope(isolated_database)
    engine = create_engine(psycopg_database_url(isolated_database))
    baseline = capture_dingtalk_exit_baseline(
        engine=engine,
        tenant_slug="exit-evidence",
        project_code="S5-PILOT",
        release_sha=RELEASE_SHA,
    )
    serialized = serialize_dingtalk_exit_baseline(baseline)
    assert parse_dingtalk_exit_baseline(serialized) == baseline

    with pytest.raises(DingTalkExitEvidenceError, match="BASELINE_DIGEST_INVALID"):
        parse_dingtalk_exit_baseline(serialized.replace("S5-PILOT", "S5-OTHER"))
    release_mismatch = verify_dingtalk_exit_evidence(
        engine=engine,
        baseline=baseline,
        release_sha="0" * 40,
    )
    assert release_mismatch.automated_ready is False
    assert release_mismatch.checks[0].name == "release_identity"
    assert release_mismatch.checks[0].passed is False

    _record_post_smoke_evidence(
        isolated_database,
        ids=ids,
        captured_at=baseline.captured_at,
    )
    with engine.begin() as connection:
        connection.execute(
            update(tables.gates)
            .where(tables.gates.c.id == ids["gate"])
            .values(status="approved", updated_at=baseline.captured_at + timedelta(seconds=2))
        )
    drifted = verify_dingtalk_exit_evidence(
        engine=engine,
        baseline=baseline,
        release_sha=RELEASE_SHA,
    )
    engine.dispose()
    approval_check = next(
        check for check in drifted.checks if check.name == "approval_mirror_gate_truth"
    )
    gate_truth_check = next(
        check for check in drifted.checks if check.name == "gate_truth_unchanged"
    )
    assert approval_check.passed is False
    assert gate_truth_check.passed is False
    assert drifted.automated_ready is False
