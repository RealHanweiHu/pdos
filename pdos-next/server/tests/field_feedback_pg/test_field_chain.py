"""Real native Field/Change PG + HTTP chain, executed only by the root checkpoint.

The imported fixture requires the explicit guarded TEST_DATABASE_URL. This file
never opens a replacement target, mocks an owner, or manufactures an Issue/Run.
Source withdrawal is a fixture fault injection, not a supported withdrawal UI.
"""

# ruff: noqa: F811 -- imported pytest fixtures are used through test parameters.

from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from knowledge_pg.test_publication import (
    command,
    configuration,  # noqa: F401 -- explicit fixture dependency
    definition,  # noqa: F401 -- explicit fixture dependency
    knowledge_work,  # noqa: F401 -- explicit fixture dependency
    project,  # noqa: F401 -- explicit fixture dependency
    register,
    scoped,
    send,
)
from knowledge_pg.test_publication import (
    snapshot as native_snapshot,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.domain.change_execution.models import (
    ChangeCurrent,
    ChangeGraphCapture,
    ChangeRequestVersion,
)
from pdos_next.domain.field_feedback.models import (
    EVENTS,
    FieldFeedbackCurrent,
    FieldFeedbackVersion,
    FieldResponseRecord,
)
from pdos_next.domain.field_feedback.schemas import ACTION, CREATE, LINK, LOCATE
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import digest

PURPOSE = "Investigate one synthetic customer feedback against its actual fixed configuration"
AUTHORITY = "Synthetic engineering responsibility and qualification for Field change preparation."
REPORT = "Synthetic customer vibration report; the received batch and configuration are unknown."
MODELS = (
    FieldFeedbackVersion,
    FieldFeedbackCurrent,
    FieldResponseRecord,
    ChangeRequestVersion,
    ChangeCurrent,
    ChangeGraphCapture,
    Receipt,
    Audit,
    Outbox,
    Confirmation,
    RequestKey,
)


def endpoint(work, *, category_only=False, change=False):
    root = f"/v1/categories/{work.setup.category}"
    if not category_only:
        root += f"/products/{work.setup.product}"
    return root + ("/change-execution" if change else "/field-feedback")


def state(work, models=MODELS):
    return native_snapshot(work, models)


def prepare(work, value, *, change=False, expected=200, headers=None):
    before = state(work)
    response = work.setup.client.post(
        endpoint(work, category_only=value["product_id"] is None, change=change) + "/inputs",
        headers=headers or work.setup.headers,
        json=value,
    )
    assert response.status_code == expected, response.text
    assert state(work) == before  # Inputs do not create facts or consume confirmation.
    if expected != 200:
        return response
    result = response.json()
    assert result["required_source_read_set"]
    if change:
        assert result["allowed"] is True, result
    prepared = deepcopy(value)
    prepared["source_read_set"] = result["required_source_read_set"]
    if not change:
        prepared["payload"] = result["payload"]
    return prepared, result


def confirmed(work, value):
    preview = send(work, value, preview=True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    assert prepared["command_id"] == value["command_id"]
    assert prepared["idempotency_key"] == value["idempotency_key"]
    assert prepared["payload"]["confirmation_token"]
    response = send(work, prepared)
    assert response.status_code == 200, response.text
    return prepared, response.json()


def reading(work, *, category_only=False, headers=None):
    before = state(work)
    response = work.setup.client.get(
        endpoint(work, category_only=category_only), headers=headers or work.setup.headers
    )
    assert response.status_code == 200, response.text
    assert state(work) == before
    return response.json()


def common_group(work, value, receipt, model, event):
    """Read the actual native subject and one same-UOW Receipt/Audit/Outbox/key."""
    with scoped(work) as session:
        row = session.get(model, UUID(receipt["subject_id"]))
        original = session.get(Receipt, UUID(receipt["id"]))
        assert row is not None and original is not None
        assert original.command_id == UUID(value["command_id"])
        assert original.operation == value["operation"]
        assert original.actor_id == original.requester_id == work.setup.human
        assert (original.subject_id, original.subject_revision) == (row.id, row.revision)
        group = [row, original]
        for kind in (Audit, Outbox, RequestKey):
            linked = list(session.scalars(select(kind).where(kind.receipt_id == original.id)))
            assert len(linked) == 1 and linked[0].actor_id == work.setup.human
            group.append(linked[0])
            if kind is Outbox:
                assert (linked[0].type, linked[0].subject_id, linked[0].subject_revision) == (
                    event,
                    row.id,
                    row.revision,
                )
                assert linked[0].correlation_id == original.command_id
        if model in (FieldFeedbackVersion, FieldResponseRecord):
            assert row.receipt_id == original.id and row.body_sha256 == digest(row.body)
            assert row.writer_id == row.actor_id == row.requester_id == work.setup.human
            if model is FieldFeedbackVersion:
                pointer = session.scalar(
                    select(FieldFeedbackCurrent).where(
                        FieldFeedbackCurrent.feedback_id == row.feedback_id
                    )
                )
                assert (pointer.version_id, pointer.revision) == (row.id, row.revision)
                group.append(pointer)
            if value["operation"] == CREATE:
                assert original.confirmation_id is row.confirmation_id is None
            else:
                proof = session.get(Confirmation, row.confirmation_id)
                assert proof.consumed is True and proof.actor_id == work.setup.human
                assert (proof.subject_type, proof.subject_id) == ("product", work.setup.product)
                assert proof.snapshot == row.command["review"]
                group.append(proof)
        else:
            assert row.request_sha256 == digest(row.request_snapshot)
            assert row.authority_snapshot["roles"] == ["engineering"]
            assert row.authority_snapshot["synthetic"] is True
            pointer = session.scalar(
                select(ChangeCurrent).where(ChangeCurrent.change_id == row.change_id)
            )
            assert (pointer.version_id, pointer.revision) == (row.id, row.revision)
            group.append(pointer)
        xids = {
            session.scalar(
                text(f'SELECT xmin::text FROM public."{item.__tablename__}" WHERE id=:id'),
                {"id": item.id},
            )
            for item in group
        }
        assert len(xids) == 1 and None not in xids
        return deepcopy(row.body if hasattr(row, "body") else row.request_snapshot)


def authorize_change(work):
    source = register(work, "Synthetic Field change authority", AUTHORITY)
    for kind in ("duty", "qualification"):
        with scoped(work) as session:
            import_professional_fact(
                session,
                work.setup.ctx,
                work.issuer,
                {
                    "product_id": str(work.setup.product),
                    "project_id": str(work.project_id),
                    "subject_id": str(work.setup.human),
                    "external_id": f"synthetic-field-engineering-{kind}",
                    "kind": kind,
                    "role": "engineering",
                    "operations": ["change.request.create", "change.impact.compute"],
                    "purposes": [PURPOSE],
                    "state": "active",
                    "valid_from": (work.at - timedelta(minutes=2)).isoformat(),
                    "valid_until": (work.at + timedelta(hours=1)).isoformat(),
                    "approval": {
                        "system": "Controlled synthetic Field engineering authority",
                        "external_id": str(uuid4()),
                        "version": "synthetic-v1",
                        "approved_by": "Explicit local synthetic issuer",
                        "issued_at": (work.at - timedelta(minutes=1)).isoformat(),
                    },
                    "sources": [
                        {
                            "artifact_id": source["id"],
                            "expected_revision": 1,
                            "line": 1,
                            "quote": AUTHORITY,
                        }
                    ],
                    "reason": "Register independent synthetic change duty and qualification",
                },
                request_key=str(uuid4()),
                command_id=uuid4(),
            )
    with scoped(work) as session:
        for operation in ("change.request.create", "change.impact.compute"):
            authority = professional.assess(
                session,
                work.setup.ctx,
                work.setup.product,
                work.project_id,
                operation,
                PURPOSE,
                now(),
            )
            assert authority["authorized"] is True and authority["qualified"] is True
            assert authority["roles"] == ["engineering"] and authority["synthetic"] is True
        assert {
            row.kind
            for row in session.scalars(
                select(ProfessionalFact).where(ProfessionalFact.role == "engineering")
            )
        } == {"duty", "qualification"}


def change_payload(feedback, source, *, title="Synthetic located Field change"):
    return {
        "title": title,
        "reason": "Prepare a real change and conservative impact; no implementation is asserted.",
        "roots": [{"kind": "field_feedback", **deepcopy(feedback), "key": None}],
        "references": [],
        "sources": [deepcopy(source)],
        "visibility": "private",
    }


def test_unknown_field_to_real_change_impact_and_retained_response(knowledge_work):
    work = knowledge_work
    authorize_change(work)
    with Session(work.setup.admin) as session:
        projects_before = session.scalar(
            select(func.count()).select_from(Project).where(Project.tenant_id == work.setup.tenant)
        )
    no_fabricated_failure = state(work, (QualityIssueVersion, VerificationRunVersion))
    source = register(
        work,
        "Synthetic private unlocated customer report",
        REPORT,
        category_only=True,
        visibility="private",
    )
    intake, _ = prepare(
        work,
        command(
            work,
            CREATE,
            {
                "visibility": "private",
                "title": "Synthetic customer vibration",
                "description": "Customer reported vibration; investigate actual identity.",
                "channel": "customer",
                "feedback_kind": "opinion",
                "received_at": work.at.isoformat(),
                "reported": {
                    "product_label": "Unverified model label",
                    "batch_label": None,
                    "configuration_label": None,
                },
                "purpose": PURPOSE,
                "sources": [source],
                "reason": "Keep unknown identity unknown.",
            },
            category_only=True,
        ),
    )
    response = send(work, intake)
    assert response.status_code == 200, response.text
    receipt = response.json()
    original_body = common_group(work, intake, receipt, FieldFeedbackVersion, EVENTS[CREATE])
    feedback_id = original_body["feedback_id"]
    unknown_ref = {"id": feedback_id, "revision": 1}
    unknown = next(
        row for row in reading(work, category_only=True)["feedbacks"] if row["id"] == feedback_id
    )
    assert unknown["location"] is None and unknown["product_id"] is unknown["project_id"] is None
    assert len(unknown["history"]) == 1
    # Fault injection is limited to this synthetic fixture and rolled back: the
    # generic lifecycle fence must independently reject arbitrary scope movement.
    with Session(work.setup.admin) as session:
        try:
            session.execute(text(
                "ALTER TABLE public.field_feedback_currents DISABLE TRIGGER field_current_guard"
            ))
            with pytest.raises(DBAPIError, match="Reference scope cannot be reassigned"):
                session.execute(
                    update(FieldFeedbackCurrent)
                    .where(
                        FieldFeedbackCurrent.tenant_id == work.setup.tenant,
                        FieldFeedbackCurrent.feedback_id == UUID(feedback_id),
                    )
                    .values(product_id=work.setup.product, project_id=work.project_id)
                )
        finally:
            session.rollback()
    with Session(work.setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.tenant_id == work.setup.tenant)
            )
            == projects_before
        )
    refused = prepare(
        work,
        command(work, "change.request.create", change_payload(unknown_ref, source)),
        change=True,
        expected=422,
    )
    assert refused.json()["code"] == "MISSING_REQUIRED_EVIDENCE"

    locate, _ = prepare(
        work,
        command(
            work,
            LOCATE,
            {
                "feedback": unknown_ref,
                "project_id": str(work.project_id),
                "engineering_configuration": {
                    "id": work.config["engineering"]["subject_id"],
                    "revision": 1,
                },
                "manufacturing_configuration": {
                    "id": work.config["process"]["subject_id"],
                    "revision": 1,
                },
                "batch": None,
                "sources": [source],
                "reason": "Confirm the actual fixed configuration and project.",
            },
        ),
    )
    before_confirmation = state(work)
    unconfirmed = send(work, locate)
    assert unconfirmed.status_code == 409 and unconfirmed.json()["code"] == "CONFIRMATION_REQUIRED"
    assert state(work) == before_confirmation
    signed, located_receipt = confirmed(work, locate)
    located_body = common_group(work, signed, located_receipt, FieldFeedbackVersion, EVENTS[LOCATE])
    fixed = {"id": feedback_id, "revision": 2}
    assert located_body["feedback_id"] == feedback_id and located_body["revision"] == 2
    assert located_body["location"]["state"] == "known"
    assert located_body["location"]["project_id"] == str(work.project_id)
    assert (
        located_body["location"]["engineering_configuration"]["id"]
        == work.config["engineering"]["subject_id"]
    )
    assert located_body["location"]["batch"] is None  # An unreported physical batch stays unknown.
    with scoped(work) as session:
        original = session.get(FieldFeedbackVersion, UUID(receipt["subject_id"]))
        located_row = session.get(FieldFeedbackVersion, UUID(located_receipt["subject_id"]))
        assert original.body == original_body and original.product_id is None
        assert (located_row.previous_id, located_row.previous_revision) == (original.id, 1)
        assert (located_row.product_id, located_row.project_id) == (
            work.setup.product,
            work.project_id,
        )

    fresh = register(
        work,
        "Synthetic containment action original",
        "Synthetic isolation and inspection performed on the reported units.",
    )
    parents = state(work, (FieldFeedbackVersion, FieldFeedbackCurrent))
    action, _ = prepare(
        work,
        command(
            work,
            ACTION,
            {
                "feedback": fixed,
                "action_kind": "containment",
                "description": "Recorded isolation; formal quality closure stays separate.",
                "occurred_at": work.at.isoformat(),
                "visibility": "private",
                "sources": [fresh],
                "reason": "Record an actual synthetic containment fact independently of location.",
            },
        ),
    )
    action_command, action_receipt = confirmed(work, action)
    action_body = common_group(
        work, action_command, action_receipt, FieldResponseRecord, EVENTS[ACTION]
    )
    assert action_body["feedback"] == fixed and action_body["response_kind"] == "containment"
    assert state(work, (FieldFeedbackVersion, FieldFeedbackCurrent)) == parents

    selected = work.setup.client.get(
        endpoint(work, change=True),
        headers=work.setup.headers,
        params={"field_feedback_id": feedback_id},
    )
    assert selected.status_code == 200, selected.text
    options = selected.json()
    assert options["capabilities"]["change.request.create"] is True, options
    assert {"kind": "field_feedback", **fixed, "key": None} in [
        option["ref"] for option in options["reference_options"]
    ]
    change, inputs = prepare(
        work, command(work, "change.request.create", change_payload(fixed, source)), change=True
    )
    created = send(work, change)
    assert created.status_code == 200, created.text
    common_group(work, change, created.json(), ChangeRequestVersion, "change.requested")
    change_id = inputs["change_id"]
    captured = work.setup.client.post(
        endpoint(work, change=True) + "/captures",
        headers=work.setup.headers,
        json={
            "capture_key": str(uuid4()),
            "change_id": change_id,
            "expected_change_revision": 1,
            "reason": "Capture actual Field and configuration owners; preserve unknown coverage.",
        },
    )
    assert captured.status_code == 200, captured.text
    impact, _ = prepare(
        work, command(work, "change.impact.compute", captured.json()["impact_payload"]), change=True
    )
    result = send(work, impact)
    assert result.status_code == 200, result.text
    impact_body = common_group(
        work, impact, result.json(), ChangeRequestVersion, "change.impact_created"
    )
    assessment = impact_body["assessments"][-1]
    assert {row["node"]["ref"]["kind"] for row in assessment["known"]} >= {
        "field_feedback",
        "engineering_configuration",
        "manufacturing_configuration",
    }
    assert any("engineering" in row["lanes"] and row["path"] for row in assessment["known"])
    assert any("manufacturing" in row["lanes"] and row["path"] for row in assessment["known"])
    assert assessment["unknown"] and impact_body["orders"] == []
    assert state(work, (QualityIssueVersion, VerificationRunVersion)) == no_fabricated_failure
    actual_changes = work.setup.client.get(
        endpoint(work, change=True),
        headers=work.setup.headers,
        params={"field_feedback_id": feedback_id},
    )
    assert actual_changes.status_code == 200, actual_changes.text
    current_change = next(row for row in actual_changes.json()["changes"] if row["current"])
    assert current_change["revision"] == 2
    assert current_change["capabilities"]["order_approve"] is False
    assert current_change["capabilities"]["implementation_record"] is False
    assert not any(
        blocker["code"] == "INTEGRATION_REQUIRED" for blocker in current_change["blockers"]
    )

    link, _ = prepare(
        work,
        command(
            work,
            LINK,
            {
                "feedback": fixed,
                "description": "Link actual impact; no implementation or retest is asserted.",
                "occurred_at": work.at.isoformat(),
                "visibility": "private",
                "sources": [fresh],
                "reason": "Retain the real native result rather than a textual completion claim.",
                "result_receipts": [{"receipt_id": result.json()["id"]}],
            },
        ),
    )
    link_command, link_receipt = confirmed(work, link)
    linked = common_group(work, link_command, link_receipt, FieldResponseRecord, EVENTS[LINK])
    assert linked["result_receipts"] == [{"receipt_id": result.json()["id"]}]
    assert state(work, (FieldFeedbackVersion, FieldFeedbackCurrent)) == parents
    with scoped(work) as session:
        linked_row = session.get(FieldResponseRecord, UUID(link_receipt["subject_id"]))
        native_result = linked_row.source_basis["result_receipts"]
        assert len(native_result) == 1
        assert native_result[0]["receipt_id"] == result.json()["id"]
        assert native_result[0]["subject_id"] == result.json()["subject_id"]
        assert native_result[0]["subject_revision"] == 2
        assert native_result[0]["operation"] == "change.impact.compute"
        assert native_result[0]["project_id"] == str(work.project_id)

    peer_headers = {"Authorization": f"Bearer {work.setup.tokens[work.setup.peer]}"}
    assert not any(
        row["id"] == feedback_id for row in reading(work, headers=peer_headers)["feedbacks"]
    )
    peer = work.setup.client.get(
        endpoint(work, change=True), headers=peer_headers, params={"field_feedback_id": feedback_id}
    )
    assert peer.status_code == 403, peer.text
    before_replay = state(work)
    replay = send(work, link_command)
    assert replay.status_code == 200 and replay.json()["id"] == link_receipt["id"]
    assert state(work) == before_replay

    # Fixture fault injection withdraws only the report; actual configuration,
    # professional responsibility and fresh performed-action evidence stay active.
    before_withdrawal = state(work)
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(Artifact.tenant_id == work.setup.tenant, Artifact.id == UUID(source["id"]))
            .values(status="withdrawn")
        )
    assert state(work) == before_withdrawal
    retained = next(row for row in reading(work)["feedbacks"] if row["id"] == feedback_id)
    assert retained["source_status"] == "needs_recheck" and len(retained["history"]) == 2
    assert {row["id"] for row in retained["responses"]} == {
        action_receipt["subject_id"],
        link_receipt["subject_id"],
    }
    assert retained["location"] == located_body["location"]
    rejected = prepare(
        work,
        command(
            work,
            "change.request.create",
            change_payload(
                fixed, fresh, title="A new intent cannot silently reuse a withdrawn report"
            ),
        ),
        change=True,
        expected=409,
    )
    assert rejected.json()["code"] in {"SOURCE_STALE", "SOURCE_UNAVAILABLE"}
    after, _ = prepare(
        work,
        command(
            work,
            ACTION,
            {
                "feedback": fixed,
                "action_kind": "improvement",
                "description": "Record a later sourced investigation; the old report stays stale.",
                "occurred_at": now().isoformat(),
                "visibility": "private",
                "sources": [fresh],
                "reason": "Source withdrawal retains history and permits truthful new work.",
            },
        ),
    )
    after_command, after_receipt = confirmed(work, after)
    common_group(work, after_command, after_receipt, FieldResponseRecord, EVENTS[ACTION])
    assert state(work, (FieldFeedbackVersion, FieldFeedbackCurrent)) == parents
    assert state(work, (QualityIssueVersion, VerificationRunVersion)) == no_fabricated_failure
    final = next(row for row in reading(work)["feedbacks"] if row["id"] == feedback_id)
    assert final["source_status"] == "needs_recheck" and len(final["responses"]) == 3
