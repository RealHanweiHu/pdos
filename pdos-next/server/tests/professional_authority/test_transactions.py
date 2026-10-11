"""Real PostgreSQL contracts; only the main thread runs these in its guarded target.

All credential sources below are synthetic. These cases do not grant real quality
qualification, receive samples, reserve a resource or start a TestRun.
"""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import cmd, post

from pdos_next.contracts import PAYLOADS
from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority import service as authority
from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Grant, Outbox, Receipt, RequestKey, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.service import Context
from tests.g0_fixture import create_g0_project

OP = "verification.request.create"
PURPOSE = "Synthetic authority verification only"
SOURCE_TEXT = "Synthetic named duty and personnel qualification; no production authority"


@pytest.fixture
def authority_work(setup):
    scope = create_g0_project(
        setup, visibility="category", name="Synthetic authority scope", purpose=PURPOSE
    )
    project = {"subject_id": str(scope.project_id)}
    source = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic credential source",
                "content": SOURCE_TEXT,
                "source_label": "Synthetic issuer source",
                "visibility": "category",
            },
        ),
    )
    assert source.status_code == 200, source.text
    source_id = source.json()["subject_id"]
    reference = {"artifact_id": source_id, "expected_revision": 1, "line": 1, "quote": SOURCE_TEXT}
    issuer = authority.configure_local_synthetic(
        setup.engine,
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=UUID(project["subject_id"]),
        key=f"synthetic:{setup.tenant}",
        enabled=True,
    )
    yield {
        "project": project["subject_id"],
        "source": source_id,
        "reference": reference,
        "issuer": issuer,
        "at": now(),
    }
    authority.disable_issuer(setup.engine, issuer.key)
    setup.engine._pdos_professional_synthetic = False


def fact_payload(setup, work, kind="duty", **changes):
    return {
        "product_id": str(setup.product),
        "project_id": work["project"],
        "subject_id": str(setup.human),
        "external_id": f"synthetic-{kind}",
        "kind": kind,
        "role": "quality",
        "operations": [OP],
        "purposes": [PURPOSE],
        "state": "active",
        "valid_from": (work["at"] - timedelta(hours=1)).isoformat(),
        "valid_until": (work["at"] + timedelta(hours=1)).isoformat(),
        "approval": {
            "system": "Synthetic fixed issuer",
            "external_id": f"approval-{kind}",
            "version": "synthetic-v1",
            "approved_by": "Synthetic named issuer",
            "issued_at": (work["at"] - timedelta(minutes=2)).isoformat(),
        },
        "sources": [work["reference"]],
        "reason": "Synthetic professional authority exercise",
        **changes,
    }


def imported(setup, work, payload, *, request_key=None, ctx=None, issuer=None):
    caller = ctx or setup.ctx
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=caller.actor_id,
        requester_id=caller.requester_id,
        category_id=setup.category,
    ) as session:
        return import_professional_fact(
            session,
            ctx or setup.ctx,
            issuer or work["issuer"],
            payload,
            request_key=request_key or str(uuid4()),
            command_id=uuid4(),
        )


def assessment(setup, work, *, ctx=None, operation=OP, purpose=PURPOSE, at=None):
    caller = ctx or setup.ctx
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=caller.actor_id,
        requester_id=caller.requester_id,
        category_id=setup.category,
    ) as session:
        return authority.assess(
            session,
            ctx or setup.ctx,
            setup.product,
            UUID(work["project"]),
            operation,
            purpose,
            at or now(),
        )


def pair(setup, work, **changes):
    return [
        imported(setup, work, fact_payload(setup, work, kind, **changes))
        for kind in ("duty", "qualification")
    ]


def successor(setup, work, previous, kind="qualification", **changes):
    return fact_payload(
        setup,
        work,
        kind,
        previous_id=previous["subject_id"],
        expected_previous_revision=previous["subject_revision"],
        **changes,
    )


def count(setup, model):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_product_owner_and_write_grant_cannot_self_grant_professional_authority(
    setup, authority_work
):
    before = assessment(setup, authority_work)
    assert before["authorized"] is False and before["roles"] == []
    assert before["qualified"] is None
    assert "professional.authority.import" not in PAYLOADS
    response = post(
        setup, cmd(setup, "professional.authority.import", fact_payload(setup, authority_work))
    )
    assert response.status_code == 403 and count(setup, ProfessionalFact) == 0


def test_trusted_pair_writes_same_transaction_receipt_audit_outbox_and_exact_sources(
    setup, authority_work
):
    records = pair(setup, authority_work)
    viewed = assessment(setup, authority_work)
    assert viewed["authorized"] is True and viewed["qualified"] is True
    assert viewed["roles"] == ["quality"] and viewed["synthetic"] is True
    assert viewed["required_source_read_set"] == [
        {"artifact_id": authority_work["source"], "expected_revision": 1}
    ]
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        for record in records:
            for model in (Audit, Outbox):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.receipt_id == UUID(record["id"]))
                    )
                    == 1
                )
            fact = session.get(ProfessionalFact, UUID(record["subject_id"]))
            assert fact.nature == "synthetic"
            assert fact.source_basis["approval"]["version"] == "synthetic-v1"
            assert fact.fact_sha256 == authority.digest(authority._material(fact))


def test_fake_issuer_object_is_rejected_even_with_owner_write_grant(setup, authority_work):
    issuer = authority_work["issuer"]
    fake = SimpleNamespace(key=issuer.key, version=issuer.version, nature=issuer.nature)
    with pytest.raises(DomainError) as caught:
        imported(setup, authority_work, fact_payload(setup, authority_work), issuer=fake)
    assert caught.value.reason == "TRUSTED_ISSUER_REQUIRED"
    assert count(setup, ProfessionalFact) == 0


@pytest.mark.parametrize("field", ["product_id", "project_id"])
def test_trusted_issuer_scope_cannot_be_rebound_by_payload(setup, authority_work, field):
    with pytest.raises(DomainError) as caught:
        imported(
            setup, authority_work, fact_payload(setup, authority_work, **{field: str(uuid4())})
        )
    assert caught.value.reason == (
        "FORBIDDEN_SCOPE" if field == "product_id" else "FORBIDDEN_ISSUER_SCOPE"
    )
    assert count(setup, ProfessionalFact) == 0


@pytest.mark.parametrize("changes", [{"approved": True}, {"nature": "real"}, {"synthetic": False}])
def test_model_policy_assertions_are_not_importable_facts(setup, authority_work, changes):
    with pytest.raises(ValidationError):
        imported(setup, authority_work, fact_payload(setup, authority_work, **changes))
    assert count(setup, ProfessionalFact) == 0


def test_subject_and_operation_and_purpose_are_exact(setup, authority_work):
    pair(setup, authority_work)
    assert assessment(setup, authority_work)["authorized"] is True
    peer = Context(setup.tenant, setup.peer, setup.peer)
    assert assessment(setup, authority_work, ctx=peer)["authorized"] is False
    assert assessment(setup, authority_work, purpose=PURPOSE + " another")["authorized"] is False
    assert assessment(setup, authority_work, operation="test.run.start")["authorized"] is False


def test_qualification_does_not_substitute_for_matching_duty(setup, authority_work):
    imported(setup, authority_work, fact_payload(setup, authority_work, role="engineering"))
    imported(setup, authority_work, fact_payload(setup, authority_work, "qualification"))
    viewed = assessment(setup, authority_work)
    assert viewed["roles"] == ["engineering"] and viewed["qualified"] is False
    assert viewed["authorized"] is False


def test_true_profile_never_accepts_synthetic_facts(setup, authority_work):
    pair(setup, authority_work)
    setup.engine._pdos_professional_synthetic = False
    viewed = assessment(setup, authority_work)
    assert viewed["authorized"] is False and viewed["qualified"] is None
    assert "SYNTHETIC_AUTHORITY_NOT_ALLOWED" in viewed["reason_codes"]


def test_revoke_restore_monotonic_epoch_invalidates_saved_review(setup, authority_work):
    duty, initial = pair(setup, authority_work)
    original = assessment(setup, authority_work)
    revoked = imported(
        setup, authority_work, successor(setup, authority_work, initial, state="revoked")
    )
    negative = assessment(setup, authority_work)
    restored = imported(setup, authority_work, successor(setup, authority_work, revoked))
    current = assessment(setup, authority_work)
    assert negative["qualified"] is False and negative["authorized"] is False
    assert current["authorized"] is True
    assert len({v["facts_revision"] for v in (original, negative, current)}) == 3
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        check = authority.recheck_snapshot(
            session, setup.ctx, setup.product, UUID(authority_work["project"]), original, now()
        )
        assert check["current"] is False
        pointer = session.scalar(
            select(ProfessionalCurrent).where(ProfessionalCurrent.kind == "qualification")
        )
        assert pointer.fact_id == UUID(restored["subject_id"])
        assert pointer.epoch == pointer.fact_revision == 3
    assert duty["subject_revision"] == 1


def test_historical_import_replay_returns_original_receipt_without_rewinding_pointer(
    setup, authority_work
):
    payload = fact_payload(setup, authority_work, "qualification")
    key = str(uuid4())
    original = imported(setup, authority_work, payload, request_key=key)
    revoked = imported(
        setup, authority_work, successor(setup, authority_work, original, state="revoked")
    )
    latest = imported(setup, authority_work, successor(setup, authority_work, revoked))
    replay = imported(setup, authority_work, deepcopy(payload), request_key=key)
    semantic = imported(setup, authority_work, deepcopy(payload))
    assert replay["id"] == semantic["id"] == original["id"]
    assert count(setup, ProfessionalFact) == 3
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "professional.authority.import")
            )
            == 3
        )
        pointer = session.scalar(select(ProfessionalCurrent))
        assert pointer.fact_id == UUID(latest["subject_id"]) and pointer.epoch == 3


def test_revoked_qualification_replay_is_history_and_does_not_restore_authority(
    setup, authority_work
):
    imported(setup, authority_work, fact_payload(setup, authority_work))
    payload = fact_payload(setup, authority_work, "qualification")
    key = str(uuid4())
    original = imported(setup, authority_work, payload, request_key=key)
    revoked = imported(
        setup, authority_work, successor(setup, authority_work, original, state="revoked")
    )
    before = assessment(setup, authority_work)
    replay = imported(setup, authority_work, deepcopy(payload), request_key=key)
    after = assessment(setup, authority_work)
    assert replay["id"] == original["id"]
    assert after == before and after["authorized"] is False and after["qualified"] is False
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        pointer = session.scalar(
            select(ProfessionalCurrent).where(ProfessionalCurrent.kind == "qualification")
        )
        assert pointer.fact_id == UUID(revoked["subject_id"]) and pointer.epoch == 2


def test_disabled_issuer_preserves_receipt_replay_and_blocks_new_import(setup, authority_work):
    payload = fact_payload(setup, authority_work)
    key = str(uuid4())
    original = imported(setup, authority_work, payload, request_key=key)
    before = {
        model: count(setup, model)
        for model in (ProfessionalFact, ProfessionalCurrent, Receipt, Audit, Outbox, RequestKey)
    }
    authority.disable_issuer(setup.engine, authority_work["issuer"].key)
    assert imported(setup, authority_work, payload, request_key=key) == original
    with pytest.raises(DomainError) as caught:
        imported(setup, authority_work, {**payload, "reason": "New signing intent"})
    assert caught.value.reason == "TRUSTED_ISSUER_REQUIRED"
    assert {model: count(setup, model) for model in before} == before


def test_idempotency_key_conflict_cannot_create_another_fact(setup, authority_work):
    key = str(uuid4())
    payload = fact_payload(setup, authority_work)
    imported(setup, authority_work, payload, request_key=key)
    with pytest.raises(DomainError) as caught:
        imported(
            setup, authority_work, {**payload, "reason": "Different import reason"}, request_key=key
        )
    assert caught.value.reason == "DUPLICATE_INTENT_CONFLICT"
    assert count(setup, ProfessionalFact) == 1


def test_expired_known_facts_and_unknown_qualification_are_distinct(setup, authority_work):
    imported(setup, authority_work, fact_payload(setup, authority_work))
    assert assessment(setup, authority_work)["qualified"] is None
    expired = fact_payload(
        setup,
        authority_work,
        "qualification",
        valid_from=(authority_work["at"] - timedelta(hours=2)).isoformat(),
        valid_until=(authority_work["at"] - timedelta(seconds=1)).isoformat(),
    )
    imported(setup, authority_work, expired)
    viewed = assessment(setup, authority_work)
    assert viewed["qualified"] is False and "PROFESSIONAL_FACT_EXPIRED" in viewed["reason_codes"]


def test_source_withdrawal_blocks_new_authority_and_preserves_receipt_replay(setup, authority_work):
    key = str(uuid4())
    payload = fact_payload(setup, authority_work)
    original = imported(setup, authority_work, payload, request_key=key)
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Artifact)
            .where(Artifact.id == UUID(authority_work["source"]))
            .values(status="withdrawn")
        )
    viewed = assessment(setup, authority_work)
    assert viewed["authorized"] is False and viewed["fact_refs"] == []
    assert imported(setup, authority_work, payload, request_key=key) == original
    with pytest.raises(DomainError):
        imported(setup, authority_work, {**payload, "reason": "New signing intent"})


def test_private_evidence_does_not_grant_authority_to_another_subject(setup, authority_work):
    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Private synthetic credential",
                "content": SOURCE_TEXT,
                "source_label": "Synthetic private source",
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    private = {
        "artifact_id": response.json()["subject_id"],
        "expected_revision": 1,
        "line": 1,
        "quote": SOURCE_TEXT,
    }
    pair(setup, authority_work, subject_id=str(setup.peer), sources=[private])
    peer = Context(setup.tenant, setup.peer, setup.peer)
    viewed = assessment(setup, authority_work, ctx=peer)
    assert viewed["authorized"] is False and viewed["required_source_read_set"] == []


def test_write_loss_keeps_readable_receipt_but_read_access_loss_blocks_it(setup, authority_work):
    key = str(uuid4())
    payload = fact_payload(setup, authority_work)
    original = imported(setup, authority_work, payload, request_key=key)
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(Grant.principal_id == setup.human, Grant.category_id == setup.category)
            .values(can_write=False)
        )
    assert assessment(setup, authority_work)["authorized"] is False
    assert imported(setup, authority_work, payload, request_key=key) == original
    with pytest.raises(DomainError):
        imported(setup, authority_work, {**payload, "reason": "New signing intent"})
    with Session(setup.admin) as session, session.begin():
        session.execute(update(Grant).where(
            Grant.principal_id == setup.human, Grant.category_id == setup.category,
        ).values(expires_at=now() - timedelta(seconds=1)))
    with pytest.raises(DomainError):
        imported(setup, authority_work, payload, request_key=key)


def test_wrapper_rollback_removes_fact_pointer_receipt_audit_outbox_and_requestkey(
    setup, authority_work
):
    models = (ProfessionalFact, ProfessionalCurrent, Receipt, Audit, Outbox, RequestKey)
    before = {model: count(setup, model) for model in models}
    with pytest.raises(RuntimeError, match="Synthetic after flush"):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            import_professional_fact(
                session,
                setup.ctx,
                authority_work["issuer"],
                fact_payload(setup, authority_work),
                request_key=str(uuid4()),
                command_id=uuid4(),
            )
            session.flush()
            raise RuntimeError("Synthetic after flush")
    assert {model: count(setup, model) for model in models} == before


@pytest.mark.parametrize("action", ["rollback", "issuer", "delete"])
def test_current_pointer_cannot_rewind_change_issuer_or_delete(setup, authority_work, action):
    imported(setup, authority_work, fact_payload(setup, authority_work))
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            row = session.scalar(select(ProfessionalCurrent))
            if action == "delete":
                session.delete(row)
            elif action == "issuer":
                row.issuer_key = "unconfigured-other-issuer"
            else:
                row.epoch = 0
            session.flush()


@pytest.mark.parametrize("action", ["update", "delete"])
def test_fact_is_physically_immutable(setup, authority_work, action):
    saved = imported(setup, authority_work, fact_payload(setup, authority_work))
    with pytest.raises(DBAPIError):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            row = session.get(ProfessionalFact, UUID(saved["subject_id"]))
            if action == "delete":
                session.delete(row)
            else:
                row.state = "withdrawn"
            session.flush()


def test_tenant_rls_and_agent_zero_direct_table_write(setup, authority_work):
    imported(setup, authority_work, fact_payload(setup, authority_work))
    with tenant_session(setup.engine, uuid4()) as session:
        assert session.scalar(select(func.count()).select_from(ProfessionalFact)) == 0
        assert session.scalar(select(func.count()).select_from(ProfessionalCurrent)) == 0
    with Session(setup.admin) as session:
        for model in (ProfessionalFact, ProfessionalCurrent):
            assert (
                session.scalar(
                    text("SELECT has_table_privilege('pdos_agent', :name, 'INSERT,UPDATE,DELETE')"),
                    {"name": model.__tablename__},
                )
                is False
            )
    agent = Context(setup.tenant, setup.agent, setup.agent)
    with pytest.raises(DomainError):
        imported(setup, authority_work, fact_payload(setup, authority_work), ctx=agent)
