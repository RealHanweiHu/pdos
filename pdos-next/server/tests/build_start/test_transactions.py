"""Real API/PG execution contracts. Only root runs these in its verified target."""

# ruff: noqa: F811 - imported pytest fixtures are intentional

from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from build_operational_facts.fixtures import (  # noqa: F401 - required imported fixtures
    configuration,
    definition,
    imported,
    known_configuration,
    operational_work,
    project,
)
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, cmd, post

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import (
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from pdos_next.domain.build_start.models import (
    BuildAssessmentCurrent,
    BuildAuthorizationDecision,
    BuildExecutionAssessment,
    BuildStart,
)
from pdos_next.domain.build_start.rules import CONTROLS, PROFESSIONAL_RULES
from pdos_next.domain.build_start.schemas import BuildAssessmentPayload
from pdos_next.domain.build_start.service import assessment_inputs
from pdos_next.domain.builds.models import Build
from pdos_next.domain.professional_authority import service as authority
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import Context, execute
from tests.g0_fixture import create_g0_project


def scope_payload(work):
    return {
        "purpose": work.scope.purpose,
        "quantity": str(work.scope.quantity),
        "unit": work.scope.unit,
        "site": work.scope.site,
        "window_start": work.scope.window.start.isoformat(),
        "window_end": work.scope.window.finish.isoformat(),
        "window_timezone": work.scope.window.original_timezone,
    }


def reference(work):
    return {
        "artifact_id": work.config["source"],
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic requirement is unverified",
    }


def assessment_command(work, previous=None):
    payload = {
        "build_id": work.build_id,
        "expected_build_revision": 1,
        "execution_scope": scope_payload(work),
        "reason": "Synthetic current execution assessment",
        "previous_assessment_id": previous["id"] if previous else None,
        "expected_previous_revision": previous["revision"] if previous else 0,
    }
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        inputs = assessment_inputs(
            session,
            work.setup.ctx,
            work.setup.product,
            BuildAssessmentPayload.model_validate(payload),
        )
    command = cmd(work.setup, "build.readiness.compute", payload)
    command["source_read_set"] = inputs["required_source_read_set"]
    return command


def view(work):
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/build-start",
        headers=work.setup.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def authority_fact(work, role, kind, **changes):
    operations = [f"build.{role}.authorize"]
    if role == "manufacturing":
        operations.append("build.start")
    return {
        "product_id": str(work.setup.product),
        "project_id": work.config["project"],
        "subject_id": str(work.setup.human),
        "external_id": f"synthetic-{role}-{kind}",
        "kind": kind,
        "role": role,
        "operations": operations,
        "purposes": [work.scope.purpose],
        "state": "active",
        "valid_from": (work.at - timedelta(minutes=10)).isoformat(),
        "valid_until": (
            getattr(work.setup, "test_authorization_until", None)
            or work.at + timedelta(minutes=40)
        ).isoformat(),
        "approval": {
            "system": "Synthetic named authority",
            "external_id": f"SYN-{role}-{kind}",
            "version": "local-synthetic-v1",
            "approved_by": "Synthetic named issuer",
            "issued_at": (work.at - timedelta(minutes=1)).isoformat(),
        },
        "sources": [reference(work)],
        "reason": "Explicit local synthetic qualification only",
        **changes,
    }


def import_authority(work, role, kind, **changes):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return import_professional_fact(
            session,
            work.setup.ctx,
            work.professional_issuer,
            authority_fact(work, role, kind, **changes),
            request_key=str(uuid4()),
            command_id=uuid4(),
        )


@pytest.fixture
def ready_work(operational_work):
    work = operational_work
    imported(work)
    receipt = post(work.setup, assessment_command(work))
    assert receipt.status_code == 200, receipt.text
    work.assessment = next(
        item for item in view(work)["assessments"] if item["id"] == receipt.json()["subject_id"]
    )
    work.professional_issuer = authority.configure_local_synthetic(
        work.setup.engine,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
        key=f"synthetic-professional-{work.setup.product}",
        enabled=True,
    )
    work.credentials = {
        (role, kind): import_authority(work, role, kind)
        for role in ("engineering", "manufacturing")
        for kind in ("duty", "qualification")
    }
    yield work
    authority.disable_issuer(work.setup.engine, work.professional_issuer.key)
    work.setup.engine._pdos_professional_synthetic = False


def authorization_command(work, role, *, previous=None, action="approve", **changes):
    fixed = work.assessment
    if action == "revoke" and previous:
        fixed = next(
            item for item in view(work)["assessments"] if item["id"] == previous["assessment_id"]
        )
    payload = {
        "assessment_id": fixed["id"],
        "expected_assessment_revision": fixed["revision"],
        "expected_assessment_sha256": fixed["snapshot_sha256"],
        "action": action,
        "previous_decision_id": previous["id"] if previous else None,
        "expected_previous_revision": previous["revision"] if previous else 0,
        "valid_until": (getattr(work.setup, "test_authorization_until", None)
                        or work.at + timedelta(minutes=25)).isoformat(),
        "sources": [reference(work)],
        "reason": "Synthetic named fixed-purpose decision",
        "accepted_controls": sorted(CONTROLS) if action == "approve" else [],
        "professional_assessments": [
            {
                "rule_id": rule,
                "status": "applicable",
                "sources": [reference(work)],
                "valid_until": (getattr(work.setup, "test_authorization_until", None)
                        or work.at + timedelta(minutes=25)).isoformat(),
                "reason": "Explicit named synthetic applicability",
            }
            for rule in PROFESSIONAL_RULES[role]
        ]
        if action == "approve"
        else [],
        **changes,
    }
    command = cmd(work.setup, f"build.{role}.authorize", payload, work.config["source"])
    return command


def approved(work, role, **changes):
    receipt, command = accepted(work.setup, authorization_command(work, role, **changes))
    row = next(item for item in view(work)["authorizations"] if item["id"] == receipt["subject_id"])
    return row, command


def start_command(work, engineering, manufacturing):
    at = now()
    event = {
        "build_id": work.build_id,
        "occurred_at": at.isoformat(),
        "purpose": work.scope.purpose,
        "engineering_configuration_id": work.config["engineering"]["subject_id"],
        "manufacturing_configuration_id": work.config["process"]["subject_id"],
    }
    import json

    content = json.dumps(event, ensure_ascii=False)
    source = post(
        work.setup,
        cmd(
            work.setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic actual start event",
                "content": content,
                "source_label": "Synthetic local actual observation",
                "visibility": "private",
            },
        ),
    )
    assert source.status_code == 200, source.text
    source_id = source.json()["subject_id"]
    fixed = work.assessment
    command = cmd(
        work.setup,
        "build.start",
        {
            "assessment_id": fixed["id"],
            "expected_assessment_revision": fixed["revision"],
            "expected_assessment_sha256": fixed["snapshot_sha256"],
            "engineering_authorization_id": engineering["id"],
            "expected_engineering_authorization_revision": engineering["revision"],
            "manufacturing_authorization_id": manufacturing["id"],
            "expected_manufacturing_authorization_revision": manufacturing["revision"],
            "occurred_at": at.isoformat(),
            "occurred_timezone": "UTC",
            "event_source": {
                "artifact_id": source_id,
                "expected_revision": 1,
                "line": 1,
                "quote": content,
            },
            "reason": "Synthetic atomic fixed-purpose start",
        },
    )
    command["source_read_set"] = [
        {"artifact_id": work.config["source"], "expected_revision": 1},
        {"artifact_id": source_id, "expected_revision": 1},
    ]
    return command


def started(work):
    engineering, _ = approved(work, "engineering")
    manufacturing, _ = approved(work, "manufacturing")
    receipt, command = accepted(work.setup, start_command(work, engineering, manufacturing))
    return receipt, command


def counts(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        result = {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in (
                BuildStart,
                MaterialHold,
                ResourceOccupancy,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
            )
        }
        result["asset_epochs"] = sorted(
            session.scalars(
                select(OperationalAsset.occupancy_epoch).where(
                    OperationalAsset.tenant_id == work.setup.tenant
                )
            )
        )
        return result


def test_assessment_unknown_professional_but_reviewable_uses_exact_same_persisted_demand(
    ready_work,
):
    fixed = ready_work.assessment
    assert fixed["status"] == "UNKNOWN" and fixed["result"]["operational_state"] == "READY"
    assert fixed["result"]["candidate_ready"] is True and fixed["result"]["nature"] == "synthetic"
    assert fixed["result"]["binding"]["demand"]["lines"] == ready_work.config["result"]["demands"]
    caps = view(ready_work)["capabilities_by_build"][ready_work.build_id]
    assert caps["engineering_approve"] and caps["manufacturing_approve"] and not caps["start"]


def test_t2_preview_named_one_confirmation_and_approve_not_t1(ready_work):
    command = authorization_command(ready_work, "engineering")
    response = post(ready_work.setup, command, True)
    assert response.status_code == 200, response.text
    prepared = response.json()
    assert prepared["write_tier"] == "T2" and prepared["named_decision"] is True
    assert (
        "approval_token" in prepared["command"]["payload"]
        and "confirmation_token" not in prepared["command"]["payload"]
    )
    assert prepared["review"]["after"]["fact_binding"]["accepted_controls"] == sorted(CONTROLS)
    saved = post(ready_work.setup, prepared["command"])
    assert saved.status_code == 200, saved.text
    with tenant_session(
        ready_work.setup.engine,
        ready_work.setup.tenant,
        actor_id=ready_work.setup.human,
        category_id=ready_work.setup.category,
    ) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Confirmation)
                .where(
                    Confirmation.tenant_id == ready_work.setup.tenant,
                    Confirmation.operation == command["operation"],
                )
            )
            == 1
        )


def test_ordinary_named_decisions_have_no_expiry_and_still_start_atomically(ready_work):
    work = ready_work
    decisions = []
    for role in ("engineering", "manufacturing"):
        value = authorization_command(work, role)
        value["payload"].pop("valid_until")
        for review in value["payload"]["professional_assessments"]:
            review.pop("valid_until")
        receipt, _ = accepted(work.setup, value)
        row = next(
            item for item in view(work)["authorizations"] if item["id"] == receipt["subject_id"]
        )
        assert row["valid_until"] is None and row["expired"] is False
        assert all(item["valid_until"] is None for item in row["professional_assessments"])
        decisions.append(row)
    receipt, prepared = accepted(work.setup, start_command(work, *decisions))
    saved = next(row for row in view(work)["starts"] if row["id"] == receipt["subject_id"])
    assert (
        saved["status"] == "executing"
        and saved["execution_result"]["state"] == "READY_WITH_CONDITIONS"
    )
    replay = post(work.setup, prepared)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]


def test_atomic_start_holds_receipt_and_read_projection_do_not_modify_original_plan(ready_work):
    with tenant_session(
        ready_work.setup.engine,
        ready_work.setup.tenant,
        actor_id=ready_work.setup.human,
        category_id=ready_work.setup.category,
    ) as session:
        build = session.get(Build, UUID(ready_work.build_id))
        before = {
            key: deepcopy(getattr(build, key))
            for key in (
                "status",
                "revision",
                "planned_quantity",
                "planned_start",
                "planned_end",
                "engineering_configuration_id",
                "manufacturing_configuration_id",
            )
        }
    receipt, _ = started(ready_work)
    assert receipt["subject_type"] == "build_start"
    data = view(ready_work)
    fixed = next(row for row in data["starts"] if row["id"] == receipt["subject_id"])
    assert (
        fixed["status"] == "executing"
        and fixed["execution_result"]["state"] == "READY_WITH_CONDITIONS"
    )
    assert fixed["execution_result"]["controls"] == sorted(CONTROLS)
    assert (
        data["capabilities_by_build"][ready_work.build_id]["execution_qualification"]
        == "limited_current"
    )
    with tenant_session(
        ready_work.setup.engine,
        ready_work.setup.tenant,
        actor_id=ready_work.setup.human,
        category_id=ready_work.setup.category,
    ) as session:
        saved = session.get(Build, UUID(ready_work.build_id))
        assert before == {key: getattr(saved, key) for key in before}
        holds = session.scalars(
            select(MaterialHold).where(
                MaterialHold.owner_execution_id == UUID(receipt["subject_id"])
            )
        ).all()
        occupied = session.scalars(
            select(ResourceOccupancy).where(
                ResourceOccupancy.owner_execution_id == UUID(receipt["subject_id"])
            )
        ).all()
        assert (
            len(holds) == len(occupied) == 1
            and str(holds[0].quantity).rstrip("0").rstrip(".") == "22"
        )
        assert holds[0].intent_digest == occupied[0].intent_digest
        assert (
            session.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.subject_id == UUID(receipt["subject_id"]))
            )
            == 1
        )


def test_start_same_key_and_new_key_semantic_replay_has_no_double_holds(ready_work):
    receipt, command = started(ready_work)
    before = counts(ready_work)
    same = post(ready_work.setup, command)
    assert same.status_code == 200 and same.json()["id"] == receipt["id"]
    alias = deepcopy(command)
    alias["command_id"], alias["idempotency_key"] = str(uuid4()), str(uuid4())
    replay = post(ready_work.setup, alias)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == receipt["id"]
    after = counts(ready_work)
    assert {k: v for k, v in before.items() if k != "request_keys"} == {
        k: v for k, v in after.items() if k != "request_keys"
    }


def test_changed_start_semantic_cannot_reuse_own_reservation(ready_work):
    _, command = started(ready_work)
    command["command_id"], command["idempotency_key"] = str(uuid4()), str(uuid4())
    command["payload"]["reason"] = "Different purported start intent"
    response = post(ready_work.setup, command)
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "BUILD_ALREADY_STARTED"
    )


def test_source_withdrawal_blocks_new_intent_and_preserves_readable_start_replay(ready_work):
    receipt, command = started(ready_work)
    source_id = UUID(command["payload"]["event_source"]["artifact_id"])
    with Session(ready_work.setup.admin) as session, session.begin():
        session.execute(update(Artifact).where(Artifact.id == source_id).values(status="withdrawn"))
    response = post(ready_work.setup, command)
    assert response.status_code == 200 and response.json()["id"] == receipt["id"]
    changed = deepcopy(command)
    changed["command_id"], changed["idempotency_key"] = str(uuid4()), str(uuid4())
    changed["payload"]["reason"] = "Synthetic new intent after withdrawal"
    rejected = post(ready_work.setup, changed)
    assert (
        rejected.status_code == 409 and rejected.json()["detail"]["reason"] == "SOURCE_UNAVAILABLE"
    )
    data = view(ready_work)
    assert data["starts"][0]["source_status"] == "needs_recheck"
    assert data["capabilities_by_build"][ready_work.build_id]["stop_required"] is True


def test_original_approver_qualification_revoke_restore_aba_invalidates_old_t1(ready_work):
    engineering, _ = approved(ready_work, "engineering")
    manufacturing, _ = approved(ready_work, "manufacturing")
    reviewed = post(ready_work.setup, start_command(ready_work, engineering, manufacturing), True)
    assert reviewed.status_code == 200, reviewed.text
    old = ready_work.credentials[("engineering", "qualification")]
    revoked = import_authority(
        ready_work,
        "engineering",
        "qualification",
        state="revoked",
        previous_id=old["subject_id"],
        expected_previous_revision=old["subject_revision"],
    )
    import_authority(
        ready_work,
        "engineering",
        "qualification",
        state="active",
        previous_id=revoked["subject_id"],
        expected_previous_revision=revoked["subject_revision"],
    )
    response = post(ready_work.setup, reviewed.json()["command"])
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "PROFESSIONAL_AUTHORITY_CHANGED"
    )
    assert counts(ready_work)["build_starts"] == 0


def test_authorization_revoke_cas_blocks_old_start_and_does_not_erase_old_approval(ready_work):
    engineering, _ = approved(ready_work, "engineering")
    manufacturing, _ = approved(ready_work, "manufacturing")
    start = start_command(ready_work, engineering, manufacturing)
    revoked, _ = approved(ready_work, "engineering", action="revoke", previous=engineering)
    assert revoked["status"] == "revoked"
    response = post(ready_work.setup, start, True)
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "AUTHORIZATION_NOT_CURRENT"
    )
    history = view(ready_work)["authorizations"]
    assert len(history) == 3 and any(
        row["id"] == engineering["id"] and row["status"] == "approved" for row in history
    )


def test_reassessment_cas_invalidates_old_fixed_approval_start(ready_work):
    engineering, _ = approved(ready_work, "engineering")
    manufacturing, _ = approved(ready_work, "manufacturing")
    command = start_command(ready_work, engineering, manufacturing)
    response = post(ready_work.setup, assessment_command(ready_work, ready_work.assessment))
    assert response.status_code == 200, response.text
    start = post(ready_work.setup, command, True)
    assert (
        start.status_code == 409
        and start.json()["detail"]["reason"] == "ASSESSMENT_VERSION_CONFLICT"
    )
    current = view(ready_work)["current_assessment_by_build"][ready_work.build_id]
    assert current == {"assessment_id": response.json()["subject_id"], "revision": 2}
    with tenant_session(
        ready_work.setup.engine,
        ready_work.setup.tenant,
        actor_id=ready_work.setup.human,
        category_id=ready_work.setup.category,
    ) as session:
        original_receipt = session.scalar(
            select(Receipt.id).where(
                Receipt.subject_id == UUID(ready_work.assessment["id"]),
                Receipt.operation == "build.readiness.compute",
            )
        )
    replay = post(ready_work.setup, assessment_command(ready_work))
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == str(original_receipt)
    assert replay.json()["subject_id"] == ready_work.assessment["id"]
    assert view(ready_work)["current_assessment_by_build"][ready_work.build_id] == current
    new_intent = assessment_command(ready_work)
    new_intent["payload"]["reason"] = "Synthetic stale new assessment intent"
    stale = post(ready_work.setup, new_intent)
    assert (
        stale.status_code == 409
        and stale.json()["detail"]["reason"] == "ASSESSMENT_VERSION_CONFLICT"
    )
    assert view(ready_work)["current_assessment_by_build"][ready_work.build_id] == current


def test_missing_professional_controls_or_no_exact_readset_blocks_before_confirmation(ready_work):
    command = authorization_command(ready_work, "engineering", accepted_controls=[])
    response = post(ready_work.setup, command, True)
    assert (
        response.status_code == 422
        and response.json()["detail"]["reason"] == "EXECUTION_CONTROLS_REQUIRED"
    )
    command = authorization_command(ready_work, "engineering")
    command["source_read_set"] = []
    response = post(ready_work.setup, command, True)
    assert (
        response.status_code == 409
        and response.json()["detail"]["reason"] == "MISSING_REQUIRED_EVIDENCE"
    )


def test_product_writer_without_trusted_professional_fact_cannot_self_authorize(operational_work):
    imported(operational_work)
    response = post(operational_work.setup, assessment_command(operational_work))
    assert response.status_code == 200, response.text
    operational_work.assessment = view(operational_work)["assessments"][0]
    rejected = post(
        operational_work.setup, authorization_command(operational_work, "engineering"), True
    )
    assert (
        rejected.status_code == 403
        and rejected.json()["detail"]["reason"] == "PROFESSIONAL_AUTHORITY_REQUIRED"
    )


def test_agent_or_run_never_performs_t2_or_start(ready_work):
    request = Command.model_validate(authorization_command(ready_work, "engineering"))
    for context in (
        Context(ready_work.setup.tenant, ready_work.setup.agent, ready_work.setup.human),
        Context(
            ready_work.setup.tenant, ready_work.setup.human, ready_work.setup.human, run_id=uuid4()
        ),
    ):
        with (
            tenant_session(
                ready_work.setup.engine,
                ready_work.setup.tenant,
                actor_id=ready_work.setup.human,
                category_id=ready_work.setup.category,
            ) as session,
            pytest.raises(DomainError),
        ):
            execute(session, context, request)
    assert counts(ready_work)["build_starts"] == 0


def test_end_of_outbox_rollback_leaves_no_start_holds_epoch_or_confirmation_consumption(
    ready_work, monkeypatch
):
    engineering, _ = approved(ready_work, "engineering")
    manufacturing, _ = approved(ready_work, "manufacturing")
    review = post(ready_work.setup, start_command(ready_work, engineering, manufacturing), True)
    assert review.status_code == 200, review.text
    before = counts(ready_work)
    import pdos_next.service as common

    original = common.append_receipt

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic failure after common audit/outbox")

    monkeypatch.setattr(common, "append_receipt", fail)
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        post(ready_work.setup, review.json()["command"])
    assert counts(ready_work) == before
    monkeypatch.setattr(common, "append_receipt", original)
    saved = post(ready_work.setup, review.json()["command"])
    assert saved.status_code == 200, saved.text


def test_execution_facts_immutable_and_pointer_cannot_delete_or_backtrack(ready_work):
    engineering, _ = approved(ready_work, "engineering")
    old = ready_work.assessment
    second = post(ready_work.setup, assessment_command(ready_work, old))
    assert second.status_code == 200, second.text
    with Session(ready_work.setup.admin) as session, pytest.raises(DBAPIError), session.begin():
        session.execute(
            update(BuildExecutionAssessment)
            .where(BuildExecutionAssessment.id == UUID(old["id"]))
            .values(status="READY")
        )
    with Session(ready_work.setup.admin) as session, pytest.raises(DBAPIError), session.begin():
        session.execute(
            update(BuildAssessmentCurrent)
            .where(BuildAssessmentCurrent.build_id == UUID(ready_work.build_id))
            .values(assessment_id=UUID(old["id"]), assessment_revision=1)
        )
    with Session(ready_work.setup.admin) as session, pytest.raises(DBAPIError), session.begin():
        session.execute(
            update(BuildAuthorizationDecision)
            .where(BuildAuthorizationDecision.id == UUID(engineering["id"]))
            .values(status="revoked")
        )


def record_deviation(work, configuration):
    response = work.setup.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/build-execution/compare",
        headers=work.setup.headers,
        params={
            "build_id": work.build_id,
            "engineering_configuration_id": configuration["engineering"]["subject_id"],
            "manufacturing_configuration_id": configuration["process"]["subject_id"],
        },
    )
    assert response.status_code == 200, response.text
    differences = response.json()["differences"]
    assert differences
    return accepted(
        work.setup,
        cmd(
            work.setup,
            "build.configuration.actual.record",
            {
                "build_id": work.build_id,
                "expected_build_revision": 1,
                "actual_engineering_configuration_id": configuration["engineering"]["subject_id"],
                "expected_actual_engineering_revision": 1,
                "actual_manufacturing_configuration_id": configuration["process"]["subject_id"],
                "expected_actual_manufacturing_revision": 1,
                "observed_at": now().isoformat(),
                "differences": [
                    {
                        "path": row["path"],
                        "reason": "Synthetic actual configuration deviation",
                        "sources": [reference(work)],
                    }
                    for row in differences
                ],
                "sources": [reference(work)],
                "reason": "Record actual deviation without concealing facts",
            },
            work.config["source"],
        ),
    )


def test_preexisting_actual_deviation_is_nonwaivable_start_blocker(ready_work, configuration):
    record_deviation(ready_work, configuration)
    response = post(ready_work.setup, authorization_command(ready_work, "engineering"), True)
    assert response.status_code == 409 and response.json()["detail"]["reason"] == "BUILD_NOT_READY"
    caps = view(ready_work)["capabilities_by_build"][ready_work.build_id]
    assert not caps["engineering_approve"] and not caps["start"]
    assert any(item["code"] == "ACTUAL_CONFIGURATION_DEVIATION" for item in caps["blockers"])


def test_poststart_deviation_remains_recordable_but_requires_stop_recheck(
    ready_work, configuration
):
    receipt, command = started(ready_work)
    actual, _ = record_deviation(ready_work, configuration)
    assert actual["subject_type"] == "actual_configuration"
    data = view(ready_work)
    assert data["starts"][0]["id"] == receipt["subject_id"]
    assert data["starts"][0]["status"] == "executing"
    caps = data["capabilities_by_build"][ready_work.build_id]
    assert caps["stop_required"] and caps["execution_qualification"] == "needs_recheck"
    assert any(item["code"] == "ACTUAL_CONFIGURATION_DEVIATION" for item in caps["blockers"])
    replay = post(ready_work.setup, command)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]


def shared_configuration(setup):
    scope = create_g0_project(
        setup, visibility="category", name="Shared synthetic project", purpose="Verify preparation"
    )
    project = {"subject_id": str(scope.project_id)}
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Shared synthetic scope source",
                "content": "Synthetic requirement is unverified",
                "source_label": "Explicit shared synthetic source",
                "visibility": "category",
            },
        ),
    )
    assert source.status_code == 200, source.text
    sid = source.json()["subject_id"]
    ref = {
        "artifact_id": sid,
        "expected_revision": 1,
        "line": 1,
        "quote": "Synthetic requirement is unverified",
    }
    common = {
        "visibility": "category",
        "reason": "Shared synthetic fixed configuration",
        "sources": [ref],
    }
    bom, _ = accepted(
        setup,
        cmd(
            setup,
            "engineering.bom.revise",
            {
                **common,
                "name": "Shared known BOM",
                "lines": [
                    {
                        "key": "motor",
                        "part": {
                            "name": "Shared synthetic motor",
                            "internal_number": f"SYN-{setup.product}",
                        },
                        "quantity": "2",
                        "unit": "ea",
                        "loss_rate": "0.1",
                        "critical": True,
                    }
                ],
            },
            sid,
        ),
    )
    eng, _ = accepted(
        setup,
        cmd(
            setup,
            "engineering.configuration.create",
            {
                **common,
                "name": "Shared engineering fixed draft",
                "definition_id": str(scope.definition_id),
                "expected_definition_revision": 1,
                "bom_id": bom["subject_id"],
                "expected_bom_revision": 1,
            },
            sid,
        ),
    )
    mfg, _ = accepted(
        setup,
        cmd(
            setup,
            "npi.process.revise",
            {
                **common,
                "name": "Shared manufacturing fixed draft",
                "engineering_configuration_id": eng["subject_id"],
                "expected_engineering_revision": 1,
                "site": "SYN-INTERNAL-LAB",
                "line": "SYN-LINE",
                "operations": [
                    {"key": "assembly", "name": "Synthetic assembly", "kind": "assembly"}
                ],
            },
            sid,
        ),
    )
    return {"source": sid, "project": project["subject_id"], "engineering": eng, "process": mfg}


def test_shared_build_three_named_people_and_distinct_grant_expiries(setup):
    import json
    import secrets
    from types import SimpleNamespace

    from build_operational_facts.fixtures import fact_payload
    from test_build_demand import compute

    from pdos_next.domain.build_operational_facts import service as operational
    from pdos_next.domain.build_operational_facts.schemas import DecisionProof, OperationalScope
    from pdos_next.models import Grant, LoginSession, Principal
    from pdos_next.service import digest

    at, manufacturer, token = now(), uuid4(), secrets.token_urlsafe(32)
    with Session(setup.admin) as session, session.begin():
        session.add(
            Principal(
                id=manufacturer, tenant_id=setup.tenant, name="Synthetic manufacturer", kind="human"
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=setup.category,
                principal_id=manufacturer,
                can_write=True,
                expires_at=at + timedelta(minutes=50),
            )
        )
        session.execute(
            update(Grant)
            .where(Grant.tenant_id == setup.tenant, Grant.principal_id == setup.peer)
            .values(expires_at=at + timedelta(minutes=45))
        )
        session.add(
            LoginSession(
                token_hash=digest(token),
                tenant_id=setup.tenant,
                principal_id=manufacturer,
                expires_at=at + timedelta(minutes=50),
            )
        )
    engineer_setup = SimpleNamespace(
        **{
            **vars(setup),
            "human": setup.peer,
            "ctx": Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category),
            "headers": {"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
        }
    )
    manufacturer_setup = SimpleNamespace(
        **{
            **vars(setup),
            "human": manufacturer,
            "ctx": Context(setup.tenant, manufacturer, manufacturer, category_id=setup.category),
            "headers": {"Authorization": f"Bearer {token}"},
        }
    )
    config = compute(setup, shared_configuration(setup))
    engineer_setup.product = manufacturer_setup.product = setup.product
    work = SimpleNamespace(
        setup=setup,
        config=config,
        at=at,
        build_id=config["build_id"],
        resource_id=uuid4(),
        decision_ids={"acceptance": uuid4(), "calibration": uuid4()},
        named_current=True,
        scope=OperationalScope(
            purpose="Verify preparation",
            quantity="10",
            unit="ea",
            site="SYN-INTERNAL-LAB",
            window={
                "start": at - timedelta(minutes=5),
                "finish": at + timedelta(minutes=20),
                "original_timezone": "UTC",
            },
        ),
    )

    def verifier(session, context, binding, resource, decision, checked_at):
        current = (
            decision.named_decision_id in work.decision_ids.values()
            and decision.actor_id == setup.human
        )
        return DecisionProof(
            current=current,
            facts_revision=digest(
                {"decision": decision.model_dump(mode="json"), "current": current}
            ),
            valid_until=decision.valid_until,
        )

    work.issuer = operational.configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=UUID(config["project"]),
        key=f"shared-operational-{setup.product}",
        enabled=True,
        test_marker_verified=True,
        verify_named_decision=verifier,
    )
    work.professional_issuer = authority.configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=UUID(config["project"]),
        key=f"shared-professional-{setup.product}",
        enabled=True,
    )
    try:
        work.payload = fact_payload(work)
        imported(work)
        receipt = post(setup, assessment_command(work))
        assert receipt.status_code == 200, receipt.text
        work.assessment = view(work)["assessments"][0]
        for role, person in (("engineering", setup.peer), ("manufacturing", manufacturer)):
            for kind in ("duty", "qualification"):
                import_authority(work, role, kind, subject_id=str(person))
        engineer_work = SimpleNamespace(**{**vars(work), "setup": engineer_setup})
        manufacturer_work = SimpleNamespace(**{**vars(work), "setup": manufacturer_setup})
        engineering, _ = approved(engineer_work, "engineering")
        manufacturing, _ = approved(manufacturer_work, "manufacturing")
        event_at = now()
        event = json.dumps(
            {
                "build_id": work.build_id,
                "occurred_at": event_at.isoformat(),
                "purpose": work.scope.purpose,
                "engineering_configuration_id": config["engineering"]["subject_id"],
                "manufacturing_configuration_id": config["process"]["subject_id"],
            }
        )
        source = post(
            manufacturer_setup,
            cmd(
                manufacturer_setup,
                "evidence.artifact.register",
                {
                    "title": "Shared synthetic actual event",
                    "content": event,
                    "source_label": "Shared synthetic observation",
                    "visibility": "category",
                },
            ),
        )
        assert source.status_code == 200, source.text
        payload = {
            "assessment_id": work.assessment["id"],
            "expected_assessment_revision": 1,
            "expected_assessment_sha256": work.assessment["snapshot_sha256"],
            "engineering_authorization_id": engineering["id"],
            "expected_engineering_authorization_revision": 1,
            "manufacturing_authorization_id": manufacturing["id"],
            "expected_manufacturing_authorization_revision": 1,
            "occurred_at": event_at.isoformat(),
            "occurred_timezone": "UTC",
            "event_source": {
                "artifact_id": source.json()["subject_id"],
                "expected_revision": 1,
                "line": 1,
                "quote": event,
            },
            "reason": "Synthetic three-person atomic start",
        }
        command = cmd(manufacturer_setup, "build.start", payload, config["source"])
        command["source_read_set"].append(
            {"artifact_id": source.json()["subject_id"], "expected_revision": 1}
        )
        started_receipt, prepared = accepted(manufacturer_setup, command)
        assert started_receipt["writer_id"] == str(manufacturer)
        assert engineering["owner_id"] == str(setup.peer) and manufacturing["owner_id"] == str(
            manufacturer
        )
        assert work.assessment["owner_id"] == str(setup.human)
        replay = post(manufacturer_setup, prepared)
        assert replay.status_code == 200 and replay.json()["id"] == started_receipt["id"]
        data = view(manufacturer_work)
        assert (
            data["capabilities_by_build"][work.build_id]["execution_qualification"]
            == "limited_current"
        )
    finally:
        operational.disable_issuer(setup.engine, work.issuer.key)
        authority.disable_issuer(setup.engine, work.professional_issuer.key)
        setup.engine._pdos_professional_synthetic = False
