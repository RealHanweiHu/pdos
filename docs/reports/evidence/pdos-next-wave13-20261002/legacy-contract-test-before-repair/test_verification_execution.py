"""Human preparation records never certify quality, handoff or TestRun execution.

Root alone runs the PostgreSQL cases in the guarded isolated candidate. Sources,
physical observations and samples here are explicitly synthetic and unqualified.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_build_execution import (  # noqa: F401 - imported fixture dependencies
    actual,
    allocation_command,
    assert_plan_unchanged,
    execution_view,
    lot,
    planned,
)
from test_builds import build_command, configuration, definition, project  # noqa: F401
from test_project_first_plan import accepted, cmd, post
from test_supply_execution import confirmation_consumed, count, expire_grant, withdraw

from pdos_next.command_handlers import T1_OPERATIONS, handler
from pdos_next.contracts import PAYLOADS, Command
from pdos_next.database import tenant_session
from pdos_next.domain.verification_execution.models import (
    VerificationCurrent,
    VerificationPreparation,
)
from pdos_next.domain.verification_execution.schemas import PreparationRecordPayload
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Grant, Outbox, Product, Receipt, RequestKey, now
from pdos_next.service import Context, digest, execute

RECORD = "verification.preparation.record"
TEXT = (
    "Synthetic drawing for preparation only\n"
    "Synthetic numeric limits 9.5 to 10.5; method not approved\n"
    "Synthetic attachment for dimension; no professional approval"
)
FORMAL_OPERATIONS = {
    "verification.request.create",
    "verification.method.prepare",
    "verification.handoff.offer",
    "verification.handoff.accept",
    "verification.handoff.return",
    "verification.schedule.propose",
    "verification.schedule.promise",
    "test.run.plan",
    "test.run.start",
    "test.results.import",
    "test.run.review",
    "test.disposition.decide",
}


@pytest.fixture
def verification_work(setup, planned, lot):  # noqa: F811 - imported fixtures
    allocated, _ = accepted(
        setup,
        allocation_command(
            setup,
            planned,
            lot["receipt"],
            samples=[
                {"label": "SYN-W7-A", "cavity": "A", "availability": "unknown"},
                {"label": "SYN-W7-B", "cavity": "B", "availability": "hold"},
            ],
        ),
    )
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic preparation material",
                "source_label": "Synthetic draft without quality qualification",
                "visibility": "private",
                "content": TEXT,
            },
        ),
    )
    assert source.status_code == 200, source.text
    samples = [
        row
        for row in execution_view(setup)["samples"]
        if row["allocation_id"] == allocated["subject_id"]
    ]
    assert {row["availability"] for row in samples} == {"unknown", "hold"}
    return {**planned, "preparation_source": source.json()["subject_id"], "samples": samples}


def reference(work, line=1):
    return {
        "artifact_id": work["preparation_source"],
        "expected_revision": 1,
        "line": line,
        "quote": TEXT.splitlines()[line - 1],
    }


def payload(work, **changes):
    return {
        "request_id": str(uuid4()),
        "expected_request_revision": 0,
        "build_id": work["build"]["subject_id"],
        "expected_build_revision": 1,
        "title": "Synthetic dimensional verification preparation",
        "purpose": "Record requirements and unknowns without formal reception",
        "return_form": "Raw readings and separately named professional conclusions",
        "items": [
            {
                "id": "dimension",
                "feature": "Synthetic dimension",
                "drawing": reference(work),
                "method": None,
                "criterion": None,
                "unit": "mm",
                "conditions": "23 C, dry",
                "material": "Synthetic polymer",
                "sample_count": 3,
                "cavities": ["A", "B", "C"],
            }
        ],
        "documents": [
            {
                "id": "raw-report",
                "title": "Raw report",
                "item_ids": ["dimension"],
                "required": True,
                "source": None,
            }
        ],
        "expected_at": None,
        "expected_timezone": None,
        "tentative_at": None,
        "tentative_timezone": None,
        "sources": [reference(work)],
        "reason": "Named human records a draft, not a professional approval",
        **changes,
    }


def command(setup, work, value=None, *, reads=None):
    request = cmd(setup, RECORD, deepcopy(value or payload(work)))
    request["source_read_set"] = reads or [
        {"artifact_id": identity, "expected_revision": 1}
        for identity in sorted({work["source"], work["preparation_source"]})
    ]
    return request


def listed(setup, *, headers=None):
    response = setup.client.get(
        f"/v1/products/{setup.product}/verification", headers=headers or setup.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def row_for(setup, receipt):
    return next(row for row in listed(setup)["preparations"] if row["id"] == receipt["subject_id"])


def saved(setup, work, value=None):
    receipt, prepared = accepted(setup, command(setup, work, value))
    return receipt, prepared, row_for(setup, receipt)


def successor(work, first, **changes):
    return payload(
        work,
        request_id=first["request_id"],
        expected_request_revision=first["revision"],
        **changes,
    )


def assert_draft_only(row):
    assert row["status"] == "prepared" and row["request_state"] == "draft"
    snapshot = row["request_snapshot"]
    assert snapshot["status"] == "draft"
    for key in ("samples", "offered_coverage", "acceptances", "returns"):
        assert snapshot[key] == []
    timeline = snapshot["timeline"]
    assert timeline["request_created"]["actor_id"] == row["owner_id"]
    for key in (
        "sample_ready",
        "documents_complete",
        "offered",
        "accepted",
        "promised_start",
        "actual_start",
        "preliminary_result",
        "final_result",
        "disposed",
    ):
        assert timeline[key] is None


def test_t1_records_unknowns_and_real_reference_samples_without_quality_authority(
    setup, verification_work
):
    work = verification_work
    request = command(setup, work)
    refused = post(setup, request)
    assert refused.json()["code"] == "CONFIRMATION_REQUIRED", refused.text
    reviewed = post(setup, request, True)
    assert reviewed.status_code == 200, reviewed.text
    assert count(setup, VerificationPreparation) == count(setup, VerificationCurrent) == 0
    prepared = reviewed.json()["command"]
    receipt = post(setup, prepared)
    assert receipt.status_code == 200, receipt.text
    value = receipt.json()
    assert value["subject_type"] == "verification_preparation" and value["subject_revision"] == 1
    row = row_for(setup, value)
    assert_draft_only(row)
    item = row["items"][0]
    assert item["method"] is item["criterion"] is None
    assert row["documents"][0]["source"] is None
    assert {gap["code"] for gap in row["document_gaps"]} == {"DOCUMENT_MISSING"}
    details = " ".join(gap["detail"] for gap in row["document_gaps"])
    assert "method" in details and "criterion" in details and "Raw report" in details
    gaps = row["coverage_gaps"]
    assert any(gap["code"] == "PARTIAL_SAMPLE_COUNT" and "0/3" in gap["detail"] for gap in gaps)
    assert sum(gap["code"] == "UNCOVERED_CAVITY" for gap in gaps) == 3
    view = listed(setup)
    assert view["runs"] == []
    assert view["capabilities"]["preparation_record"] is True
    assert all(
        enabled is False
        for key, enabled in view["capabilities"].items()
        if key != "preparation_record"
    )
    assert {blocker["code"] for blocker in view["blockers"]} >= {
        "BUILD_NOT_EXECUTING",
        "SAMPLE_AVAILABILITY_UNKNOWN",
        "SAMPLE_ON_HOLD",
        "PROFESSIONAL_QUALIFICATION_UNCONNECTED",
        "RESOURCE_QUALIFICATION_UNCONNECTED",
        "SAMPLE_CONSUMPTION_UNCONNECTED",
    }
    assert {sample["id"] for sample in view["reference_samples"]} == {
        sample["id"] for sample in work["samples"]
    }
    assert {sample["availability"] for sample in view["reference_samples"]} == {"unknown", "hold"}
    assert all(
        sample["reservation"] is sample["consumption"] is None
        for sample in view["reference_samples"]
    )
    assert confirmation_consumed(setup, prepared) is True
    assert count(setup, VerificationPreparation) == count(setup, VerificationCurrent) == 1
    with tenant_session(setup.engine, setup.tenant) as session:
        for model in (Audit, Outbox):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.receipt_id == UUID(value["id"]))
                )
                == 1
            )
    assert_plan_unchanged(setup, work)


def test_nested_exact_refs_are_inherited_and_quotes_cannot_be_forged(setup, verification_work):
    work = verification_work
    value = payload(work)
    item = value["items"][0]
    item["method"] = reference(work, 2)
    item["criterion"] = {"lower": "9.5", "upper": "10.5", "source": reference(work, 2)}
    value["documents"][0]["source"] = reference(work, 3)
    receipt, _, row = saved(setup, work, value)
    assert row["document_gaps"] == []
    assert row["items"][0]["criterion"]["lower"] == "9.5"
    assert {ref["artifact_id"] for ref in row["required_source_read_set"]} == {
        work["source"],
        work["preparation_source"],
    }
    assert row["items"][0]["method"] == reference(work, 2)
    assert_draft_only(row)
    forged = successor(work, row)
    forged["items"][0]["criterion"] = {
        "lower": "9.5",
        "upper": "10.5",
        "source": {**reference(work, 2), "quote": "Forged limit"},
    }
    refused = post(setup, command(setup, work, forged), True)
    assert refused.status_code == 422, refused.text
    omitted = command(
        setup,
        work,
        successor(work, row),
        reads=[{"artifact_id": work["preparation_source"], "expected_revision": 1}],
    )
    refused = post(setup, omitted, True)
    assert refused.status_code in {409, 422}, refused.text
    assert count(setup, Receipt, operation=RECORD) == count(setup, VerificationPreparation) == 1
    assert receipt["subject_id"] == row["id"]


@pytest.mark.parametrize("field", ["expected", "tentative"])
def test_original_timezones_are_retained_but_tentative_never_becomes_a_commitment(
    setup, verification_work, field
):
    value = payload(verification_work)
    value[f"{field}_at"] = "2026-10-20T09:00:00+08:00"
    value[f"{field}_timezone"] = "Asia/Shanghai"
    _, _, row = saved(setup, verification_work, value)
    assert datetime.fromisoformat(row[f"{field}_at"]).isoformat() == "2026-10-20T01:00:00+00:00"
    assert row[f"{field}_timezone"] == "Asia/Shanghai"
    assert_draft_only(row)
    created = row["request_snapshot"]["timeline"]["request_created"]
    assert created["occurred_at"] == created["received_at"]
    assert created["original_timezone"] == "UTC"
    assert_plan_unchanged(setup, verification_work)


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_at": "2026-10-20T01:00:00Z"},
        {"expected_timezone": "UTC"},
        {"tentative_at": "2026-10-20T01:00:00Z"},
        {"tentative_timezone": "UTC"},
        {"tentative_at": "2026-10-20T01:00:00", "tentative_timezone": "UTC"},
        {"expected_at": "2026-10-20T01:00:00Z", "expected_timezone": "Unknown/Region"},
        {"expected_request_revision": True},
        {"tenant_id": str(uuid4())},
        {"roles": ["quality"]},
        {"qualified": True},
        {"received_at": "2026-10-02T00:00:00Z"},
    ],
)
def test_payload_does_not_accept_unpaired_clocks_or_trusted_authority(changes):
    value = {
        "request_id": str(uuid4()),
        "expected_request_revision": 0,
        "build_id": str(uuid4()),
        "expected_build_revision": 1,
        "title": "Synthetic",
        "purpose": "Draft",
        "return_form": "Readings",
        "items": [{"id": "dimension", "feature": "Synthetic", "sample_count": 1}],
        "sources": [
            {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1, "quote": "Synthetic"}
        ],
        "reason": "Record preparation",
        **changes,
    }
    with pytest.raises(ValidationError):
        PreparationRecordPayload.model_validate(value)


def test_successor_keeps_first_clock_history_and_saved_old_intent_replays(setup, verification_work):
    work = verification_work
    first, original, before = saved(setup, work)
    value = successor(work, before, title="Revised synthetic preparation")
    second, _, after = saved(setup, work, value)
    assert second["subject_revision"] == 2 and second["subject_id"] != first["subject_id"]
    assert after["previous_preparation_id"] == first["subject_id"]
    assert after["previous_revision"] == 1
    assert after["first_prepared_at"] == before["first_prepared_at"]
    assert (
        after["request_snapshot"]["timeline"]["request_created"]
        == (before["request_snapshot"]["timeline"]["request_created"])
    )
    assert datetime.fromisoformat(after["created_at"]) >= datetime.fromisoformat(
        before["created_at"]
    )
    old = row_for(setup, first)
    assert old["is_current"] is False and old["freshness"] == "historical"
    assert old["input_snapshot"] == before["input_snapshot"]
    assert after["is_current"] is True
    assert listed(setup)["current_by_request"][before["request_id"]] == {
        "preparation_id": second["subject_id"],
        "revision": 2,
    }
    replay = {**original, "command_id": str(uuid4()), "idempotency_key": str(uuid4())}
    assert post(setup, replay).json()["id"] == first["id"]
    with Session(setup.admin) as session, session.begin():
        session.execute(update(Product).where(Product.id == setup.product).values(revision=2))
    assert post(setup, original).json()["id"] == first["id"]
    assert count(setup, VerificationPreparation) == count(setup, Receipt, operation=RECORD) == 2
    assert count(setup, VerificationCurrent) == 1


def test_competing_successors_are_cas_bound_and_cannot_overwrite_current(setup, verification_work):
    work = verification_work
    first, _, row = saved(setup, work)
    prepared = []
    for title in ("Synthetic revision A", "Synthetic revision B"):
        review = post(setup, command(setup, work, successor(work, row, title=title)), True)
        assert review.status_code == 200, review.text
        prepared.append(review.json()["command"])
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda value: post(setup, value), prepared))
    assert sorted(response.status_code for response in outcomes) == [200, 409]
    assert sum(confirmation_consumed(setup, value) for value in prepared) == 1
    winner = next(response.json() for response in outcomes if response.status_code == 200)
    assert winner["subject_revision"] == 2
    assert count(setup, VerificationPreparation) == count(setup, Receipt, operation=RECORD) == 2
    assert count(setup, VerificationCurrent) == 1
    assert row_for(setup, first)["input_snapshot"] == row["input_snapshot"]


def test_concurrent_same_intent_commits_once_and_same_key_changed_body_is_refused(
    setup, verification_work
):
    request = command(setup, verification_work)
    reviewed = post(setup, request, True)
    assert reviewed.status_code == 200, reviewed.text
    prepared = reviewed.json()["command"]
    with ThreadPoolExecutor(max_workers=2) as workers:
        outcomes = list(workers.map(lambda _: post(setup, prepared), range(2)))
    assert all(response.status_code == 200 for response in outcomes), [r.text for r in outcomes]
    assert len({response.json()["id"] for response in outcomes}) == 1
    changed = deepcopy(prepared)
    changed["payload"]["title"] = "Different body under the same retry key"
    refused = post(setup, changed)
    assert refused.status_code == 409 and refused.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    assert count(setup, VerificationPreparation) == count(setup, VerificationCurrent) == 1
    assert count(setup, Receipt, operation=RECORD) == 1
    assert confirmation_consumed(setup, prepared) is True


@pytest.mark.parametrize("change", ["reason", "items", "readset"])
def test_confirmation_is_bound_to_actual_draft_and_complete_fixed_sources(
    setup, verification_work, change
):
    request = command(setup, verification_work)
    response = post(setup, request, True)
    assert response.status_code == 200, response.text
    prepared = response.json()["command"]
    changed = deepcopy(prepared)
    if change == "readset":
        changed["source_read_set"] = changed["source_read_set"][:1]
    elif change == "items":
        changed["payload"]["items"][0]["sample_count"] = 5
    else:
        changed["payload"]["reason"] = "Changed confirmation scope"
    denied = post(setup, changed)
    assert denied.status_code in {409, 422}, denied.text
    assert confirmation_consumed(setup, prepared) is False
    assert count(setup, VerificationPreparation) == count(setup, Receipt, operation=RECORD) == 0


@pytest.mark.parametrize("change", ["source", "inherited_source", "revision", "grant"])
def test_current_sources_and_authority_are_checked_before_saved_receipt_replay(
    setup, verification_work, change
):
    work = verification_work
    _, prepared, _ = saved(setup, work)
    if change == "grant":
        expire_grant(setup)
    elif change == "revision":
        with Session(setup.admin) as session, session.begin():
            session.execute(
                update(Artifact)
                .where(Artifact.id == UUID(work["preparation_source"]))
                .values(revision=2)
            )
    else:
        withdraw(setup, work["source" if change == "inherited_source" else "preparation_source"])
    refused = post(setup, prepared)
    assert refused.status_code in {403, 409}, refused.text
    assert count(setup, VerificationPreparation) == count(setup, Receipt, operation=RECORD) == 1


def test_final_receipt_failure_rolls_back_version_pointer_confirmation_and_outbox(
    setup, verification_work, monkeypatch
):
    from pdos_next import service

    request = command(setup, verification_work)
    preview = post(setup, request, True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    models = (VerificationPreparation, VerificationCurrent, Receipt, Audit, Outbox, RequestKey)
    before = {model: count(setup, model) for model in models}
    original = service.append_receipt

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[2].operation == RECORD:
            raise DomainError("SYNTHETIC_PREPARATION_RECEIPT_FAILURE", "Synthetic rollback")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(service, "append_receipt", fail)
        refused = post(setup, prepared)
    assert refused.json()["code"] == "SYNTHETIC_PREPARATION_RECEIPT_FAILURE", refused.text
    assert {model: count(setup, model) for model in models} == before
    assert confirmation_consumed(setup, prepared) is False
    assert post(setup, prepared).status_code == 200
    assert count(setup, Receipt, operation=RECORD) == 1


def test_read_permission_does_not_keep_preparation_write_or_replay_authority(
    setup, verification_work
):
    receipt, prepared, row = saved(setup, verification_work)
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(Grant.product_id == setup.product, Grant.principal_id == setup.human)
            .values(can_write=False)
        )
    view = listed(setup)
    assert any(value["id"] == row["id"] for value in view["preparations"])
    assert view["capabilities"]["preparation_record"] is False
    refused = post(setup, prepared)
    assert refused.status_code == 403, refused.text
    assert count(setup, Receipt, operation=RECORD) == 1
    assert receipt["subject_id"] == row["id"]


def test_private_preparation_and_sources_are_hidden_from_peer_and_other_tenant(
    setup, verification_work
):
    work = verification_work
    _, prepared, _ = saved(setup, work)
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    data = listed(setup, headers=peer)
    assert data["preparations"] == [] and data["current_by_request"] == {}
    assert data["reference_samples"] == [] and data["runs"] == []
    replay = setup.client.post("/v1/commands", headers=peer, json=prepared)
    assert replay.status_code == 403, replay.text
    outsider = setup.client.get(
        f"/v1/products/{setup.product}/verification",
        headers={"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert outsider.status_code == 403
    private_source = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Artifact(
                id=private_source,
                tenant_id=setup.tenant,
                product_id=setup.product,
                owner_id=setup.peer,
                title="Peer private original",
                source_label="Synthetic",
                content="Peer private planning material",
                content_hash=digest("Peer private planning material"),
                visibility="private",
            )
        )
    value = payload(work)
    value["items"][0]["method"] = {
        "artifact_id": str(private_source),
        "expected_revision": 1,
        "line": 1,
        "quote": "Peer private planning material",
    }
    request = command(setup, work, value)
    request["source_read_set"].append({"artifact_id": str(private_source), "expected_revision": 1})
    refused = post(setup, request, True)
    assert refused.status_code == 403, refused.text
    assert count(setup, VerificationPreparation) == 1


def test_request_series_cannot_switch_build_or_use_another_product(setup, verification_work):
    work = verification_work
    _, _, first = saved(setup, work)
    another, _ = accepted(setup, build_command(setup, work, name="Another synthetic Build"))
    moved = successor(work, first, build_id=another["subject_id"])
    refused = post(setup, command(setup, work, moved), True)
    assert refused.status_code in {403, 409}, refused.text
    foreign = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Product(
                id=foreign,
                tenant_id=setup.tenant,
                name="Other product",
                purpose="Synthetic scope",
                owner_id=setup.human,
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                product_id=foreign,
                principal_id=setup.human,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
    request = command(setup, work)
    request["product_id"] = str(foreign)
    refused = post(setup, request, True)
    assert refused.status_code == 403, refused.text
    assert count(setup, VerificationPreparation) == count(setup, VerificationCurrent) == 1


def test_preparation_does_not_grant_professional_or_physical_authority(setup, verification_work):
    assert RECORD in PAYLOADS and RECORD in T1_OPERATIONS
    front = {
        "verification.request.create",
        "verification.method.prepare",
        "verification.schedule.propose",
        "verification.handoff.offer",
        "verification.handoff.accept",
        "verification.handoff.return",
    }
    assert not (FORMAL_OPERATIONS - front).intersection(PAYLOADS)
    assert all(handler(operation) is None for operation in FORMAL_OPERATIONS - front)
    _, _, row = saved(setup, verification_work)
    request = cmd(
        setup,
        "verification.request.create",
        {
            "request_id": str(uuid4()),
            "preparation_id": row["id"],
            "expected_preparation_revision": row["revision"],
            "preparation_sha256": row["sha256"],
            "reason": "Preparation and ProductGrant do not grant a professional role",
        },
    )
    request["source_read_set"] = row["required_source_read_set"]
    denied = post(setup, request)
    assert denied.status_code == 403 and denied.json()["code"] == "FORBIDDEN_OPERATION"
    refused = post(setup, cmd(setup, "verification.handoff.accept", {"qualified": True}))
    assert refused.status_code == 422 and refused.json()["code"] == "INVALID_PAYLOAD"
    assert listed(setup)["runs"] == []
    assert_plan_unchanged(setup, verification_work)


def test_database_history_rls_pointer_sequence_and_agent_zero_write(setup, verification_work):
    work = verification_work
    first, prepared, row = saved(setup, work)
    saved(setup, work, successor(work, row, title="Second immutable version"))
    with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
        session.execute(
            update(VerificationPreparation)
            .where(VerificationPreparation.id == UUID(first["subject_id"]))
            .values(reason="Forbidden overwrite")
        )
    with Session(setup.engine) as session:
        for model in (VerificationPreparation, VerificationCurrent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with Session(setup.admin) as session:
        for model in (VerificationPreparation, VerificationCurrent):
            assert session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = CAST(:name AS regclass)"
                ),
                {"name": model.__tablename__},
            ).one() == (True, True)
            assert (
                session.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                    {"name": model.__tablename__},
                )
                is False
            )
    with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
        session.execute(
            update(VerificationCurrent)
            .where(VerificationCurrent.request_id == UUID(row["request_id"]))
            .values(preparation_id=UUID(first["subject_id"]), preparation_revision=1)
        )
    with (
        tenant_session(setup.engine, setup.tenant) as session,
        pytest.raises(DomainError) as refused,
    ):
        execute(
            session,
            Context(setup.tenant, setup.agent, setup.human),
            Command.model_validate(prepared),
        )
    assert refused.value.code == "FORBIDDEN_SCOPE"
    assert count(setup, VerificationPreparation) == count(setup, Receipt, operation=RECORD) == 2


def test_pointer_first_insert_cannot_skip_a_real_persisted_first_version(setup, verification_work):
    _, _, first = saved(setup, verification_work)
    # Negative ledger fixture: both snapshots exist with valid scoped FKs but
    # this separate synthetic series has no current pointer yet. Thus rejection
    # cannot be explained by a duplicate pointer or a missing snapshot FK.
    request_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    with Session(setup.admin) as session, session.begin():
        original = session.get(VerificationPreparation, UUID(first["id"]))
        common = {
            column.name: deepcopy(getattr(original, column.name))
            for column in VerificationPreparation.__table__.columns
            if column.name
            not in {
                "id",
                "request_id",
                "revision",
                "previous_preparation_id",
                "previous_revision",
                "request_snapshot",
                "snapshot_sha256",
            }
        }
        for identity, revision, previous in ((first_id, 1, None), (second_id, 2, first_id)):
            snapshot = deepcopy(original.request_snapshot)
            snapshot.update(id=str(request_id), revision=revision)
            session.add(
                VerificationPreparation(
                    **common,
                    id=identity,
                    request_id=request_id,
                    revision=revision,
                    previous_preparation_id=previous,
                    previous_revision=1 if previous else None,
                    request_snapshot=snapshot,
                    snapshot_sha256=digest(snapshot),
                )
            )
            session.flush()
    with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
        # Both target request/version FKs below are valid and there is no pointer
        # for the target series. Immutable request identity must still refuse it.
        session.execute(
            update(VerificationCurrent)
            .where(VerificationCurrent.request_id == UUID(first["request_id"]))
            .values(request_id=request_id, preparation_id=second_id, preparation_revision=2)
        )
    with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
        session.add(
            VerificationCurrent(
                tenant_id=setup.tenant,
                product_id=setup.product,
                request_id=request_id,
                preparation_id=second_id,
                preparation_revision=2,
            )
        )
        session.flush()
    with Session(setup.admin) as session, session.begin():
        pointer = VerificationCurrent(
            tenant_id=setup.tenant,
            product_id=setup.product,
            request_id=request_id,
            preparation_id=first_id,
            preparation_revision=1,
        )
        session.add(pointer)
        session.flush()
        pointer.preparation_id, pointer.preparation_revision = second_id, 2
        session.flush()
    with Session(setup.admin) as session, session.begin(), pytest.raises(DBAPIError):
        pointer = session.scalar(
            select(VerificationCurrent).where(VerificationCurrent.request_id == request_id)
        )
        session.delete(pointer)
        session.flush()
    with tenant_session(setup.engine, setup.tenant) as session:
        pointer = session.scalar(
            select(VerificationCurrent).where(VerificationCurrent.request_id == request_id)
        )
        assert pointer.preparation_id == second_id and pointer.preparation_revision == 2
