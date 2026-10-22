from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.models import (
    Artifact,
    Audit,
    Base,
    Claim,
    Consumption,
    Grant,
    Outbox,
    Receipt,
    now,
)
from pdos_next.service import digest


def command(setup, op, payload, *, key=None, revision=1, source=None):
    return {
        "command_id": str(uuid4()),
        "idempotency_key": key or str(uuid4()),
        "operation": op,
        "category_id": str(setup.category),
        "product_id": str(setup.product),
        "expected_revision": revision,
        "source_read_set": [{"artifact_id": source, "expected_revision": 1}] if source else [],
        "payload": payload,
    }


def post(setup, cmd, client=None):
    return (client or setup.client).post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=cmd
    )


def source(setup, visibility="private"):
    original = "\nSynthetic data only\nPressure: 150 PSI\nUnknown: test condition\n"
    response = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic input",
                "source_label": "Synthetic test",
                "content": original,
                "visibility": visibility,
            },
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()["subject_id"], original


def claim_cmd(setup, artifact, **overrides):
    payload = {
        "artifact_id": artifact,
        "line": 3,
        "quote": "Pressure: 150 PSI",
        "statement": "Pressure is 150 PSI; condition unknown",
        "nature": "extracted",
        "availability": "known",
        "visibility": "private",
        **overrides,
    }
    return command(setup, "evidence.claim.record", payload, source=artifact)


def workspace(setup, headers=None):
    return setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/workspace",
        headers=headers or setup.headers,
    )


def test_source_original_scope_and_same_transaction_receipts(setup):
    artifact, original = source(setup)
    response = post(setup, claim_cmd(setup, artifact))
    assert response.status_code == 200, response.text
    result = response.json()
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        a = s.get(Artifact, UUID(artifact))
        assert a.content == original and a.content_hash == digest(original)
        c = s.get(Claim, UUID(result["subject_id"]))
        assert c.writer_id == setup.human and c.human_owner_id == setup.human
        r = s.get(Receipt, UUID(result["id"]))
        assert s.scalar(select(Audit.id).where(Audit.receipt_id == r.id))
        assert s.scalar(select(Outbox.id).where(Outbox.receipt_id == r.id))
    assert (
        workspace(setup).json()["claims"][0]["statement"]
        == "Pressure is 150 PSI; condition unknown"
    )


def test_key_conflict_and_cross_key_semantic_dedup(setup):
    artifact, _ = source(setup)
    cmd = claim_cmd(setup, artifact)
    first = post(setup, cmd).json()
    assert post(setup, {**cmd, "command_id": str(uuid4())}).json()["id"] == first["id"]
    different = {**cmd, "payload": {**cmd["payload"], "statement": "Different intent"}}
    assert post(setup, different).json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    assert post(setup, {**cmd, "idempotency_key": str(uuid4())}).json()["id"] == first["id"]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(Claim)) == 1


def test_concurrent_intents_create_once(setup):
    artifact, _ = source(setup)
    cmd = claim_cmd(setup, artifact)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: post(setup, {**cmd, "idempotency_key": str(uuid4())}), range(4))
        )
    assert {r.status_code for r in results} == {200}
    assert len({r.json()["id"] for r in results}) == 1


@pytest.mark.parametrize(
    "field", ["tenant", "tenant_id", "actor", "requester", "run", "grant", "cancel_epoch"]
)
def test_client_cannot_supply_trusted_identity(setup, field):
    artifact, _ = source(setup)
    assert post(setup, {**claim_cmd(setup, artifact), field: str(uuid4())}).status_code == 422


def test_private_source_does_not_leak_or_expand_audience(setup):
    artifact, _ = source(setup)
    headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    peer = workspace(setup, headers).json()
    assert peer["sources"] == [] and peer["claims"] == []
    assert post(setup, claim_cmd(setup, artifact, visibility="category")).status_code == 403
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=headers,
        json=claim_cmd(setup, artifact),
    )
    assert response.json()["code"] == "SOURCE_UNAVAILABLE"


def test_cross_tenant_and_revoked_scope_are_denied(setup):
    artifact, _ = source(setup)
    headers = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert workspace(setup, headers).status_code == 403
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    assert post(setup, claim_cmd(setup, artifact)).json()["code"] == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize(
    "change,code",
    [
        ({"line": 99}, "VALIDATION_FAILED"),
        ({"quote": "invented quotation"}, "VALIDATION_FAILED"),
    ],
)
def test_exact_source_locator_required(setup, change, code):
    artifact, _ = source(setup)
    assert post(setup, claim_cmd(setup, artifact, **change)).json()["code"] == code


def test_version_and_source_withdrawal_guard(setup):
    artifact, _ = source(setup)
    cmd = claim_cmd(setup, artifact)
    assert post(setup, {**cmd, "expected_revision": 2}).json()["code"] == "VERSION_CONFLICT"
    with Session(setup.admin) as s, s.begin():
        s.get(Artifact, UUID(artifact)).revision = 2
    assert post(setup, cmd).json()["code"] == "SOURCE_STALE"
    with Session(setup.admin) as s, s.begin():
        s.get(Artifact, UUID(artifact)).status = "withdrawn"
    assert post(setup, cmd).json()["code"] == "SOURCE_UNAVAILABLE"


def test_failed_outbox_rolls_back_business_and_receipt(setup):
    artifact, _ = source(setup)
    from sqlalchemy import event

    def fail(_mapper, _connection, _target):
        raise RuntimeError("synthetic outbox failure")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic outbox failure"):
            post(setup, claim_cmd(setup, artifact))
    finally:
        event.remove(Outbox, "before_insert", fail)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(Claim)) == 0
        assert (
            s.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "evidence.claim.record")
            )
            == 0
        )


def test_revert_preview_confirmation_and_history(setup):
    artifact, _ = source(setup)
    r = post(setup, claim_cmd(setup, artifact)).json()
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/products/{setup.product}/receipts/{r['id']}/revert-preview",
        headers=setup.headers,
    ).json()
    cmd = command(
        setup,
        "ai.run.revert",
        {"receipt_id": r["id"], "confirmation_token": preview["confirmation_token"]},
    )
    assert post(setup, cmd).status_code == 200
    assert post(setup, cmd).status_code == 200
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.get(Claim, UUID(r["subject_id"])).status == "reverted"
        assert s.get(Receipt, UUID(r["id"])) is not None
        assert s.get(Artifact, UUID(artifact)).status == "active"


@pytest.mark.parametrize("protection", ["manual_edit", "downstream"])
def test_claim_history_rejects_manual_edit_and_consumption_blocks_revert(setup, protection):
    artifact, _ = source(setup)
    r = post(setup, claim_cmd(setup, artifact)).json()
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/products/{setup.product}/receipts/{r['id']}/revert-preview",
        headers=setup.headers,
    ).json()
    if protection == "manual_edit":
        with pytest.raises(DBAPIError, match="claim only permits named withdrawal"):
            with Session(setup.admin) as s, s.begin():
                s.get(Claim, UUID(r["subject_id"])).revision += 1
        with Session(setup.admin) as s:
            assert s.get(Claim, UUID(r["subject_id"])).revision == 1
        return
    with Session(setup.admin) as s, s.begin():
        s.add(
            Consumption(
                tenant_id=setup.tenant,
                product_id=setup.product,
                claim_id=UUID(r["subject_id"]),
                consumer_type="synthetic-verification",
                consumer_id=uuid4(),
            )
        )
    cmd = command(
        setup,
        "ai.run.revert",
        {"receipt_id": r["id"], "confirmation_token": preview["confirmation_token"]},
    )
    assert post(setup, cmd).json()["code"] == "UNDO_BLOCKED_BY_DEPENDENCY"


def test_rls_pool_reset_privileges_and_original_immutability(setup):
    artifact, _ = source(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        role = s.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert role == (False, False)
        assert s.get(Artifact, UUID(artifact))
    with setup.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM artifact_versions")).scalar_one() == 0
        assert (
            conn.execute(
                text("SELECT has_table_privilege('pdos_agent', 'claims', 'INSERT')")
            ).scalar_one()
            is False
        )
        assert (
            conn.execute(
                text("SELECT has_table_privilege(current_user, 'qualifications', 'INSERT')")
            ).scalar_one()
            is False
        )
    with (
        pytest.raises(DBAPIError, match="immutable"),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as s,
    ):
        s.get(Artifact, UUID(artifact)).content = "tampered"
        s.flush()


def test_migration_matches_orm_and_test_guard(setup, monkeypatch):
    with setup.admin.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_object": lambda obj, name, type_, reflected, compare_to: (
                    name not in {"environment_guard", "alembic_version"}
                )
            },
        )
        assert compare_metadata(context, Base.metadata) == []
    from pdos_next.safety import verify_test_target

    monkeypatch.delenv("TEST_DATABASE_URL")
    with pytest.raises(RuntimeError, match="unverified"):
        verify_test_target(setup.engine)
