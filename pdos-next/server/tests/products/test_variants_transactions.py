from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.products.variant_models import Variant, VariantRevision
from pdos_next.domain.products.variants import validate
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Confirmation, Grant, Outbox, Product, Receipt, now
from pdos_next.schemas.products.variants import VariantDerivePayload
from pdos_next.service import Context, digest


def command(setup, operation, payload, artifact):
    return {
        "category_id": str(setup.category),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": str(setup.product),
        "expected_revision": 1,
        "source_read_set": [{"artifact_id": artifact, "expected_revision": 1}],
        "payload": payload,
    }


def post(setup, body, *, preview=False):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview"
        if preview
        else f"/v1/categories/{setup.category}/commands",
        headers=setup.headers,
        json=body,
    )


def reference(artifact):
    return {
        "artifact_id": artifact,
        "expected_revision": 1,
        "line": 2,
        "quote": "Pressure: 150 PSI",
    }


def source(setup, visibility="category"):
    body = command(
        setup,
        "evidence.artifact.register",
        {
            "title": "Synthetic variant source",
            "source_label": "Synthetic fixture only",
            "content": "Synthetic only\nPressure: 150 PSI\nConditions require confirmation",
            "visibility": visibility,
        },
        str(uuid4()),
    )
    body["source_read_set"] = []
    result = post(setup, body)
    assert result.status_code == 200, result.text
    return result.json()["subject_id"]


def definition(setup, artifact, *, parent=None, **changes):
    body = {
        "title": "Synthetic parent definition",
        "purpose": "Synthetic product verification only",
        "visibility": "category",
        "use_cases": ["Synthetic evaluation"],
        "requirements": ["Baseline requirement"],
        "constraints": ["Baseline constraint"],
        "unknowns": ["Test condition not confirmed"],
        "exclusions": [],
        "change_reason": "Record synthetic parent version",
        "sources": [reference(artifact)],
        "specs": [
            {
                "key": "pressure",
                "parameter": "Pressure under declared conditions",
                "value_type": "number",
                "availability": "unknown",
                "reason": "Cannot infer conditions",
                "sources": [reference(artifact)],
            }
        ],
        **changes,
    }
    if parent:
        body.update(
            parent_definition_id=parent["id"],
            expected_parent_revision=parent["revision"],
        )
    result = post(setup, command(setup, "product.definition.draft", body, artifact))
    assert result.status_code == 200, result.text
    listed = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/definitions",
        headers=setup.headers,
    )
    assert listed.status_code == 200, listed.text
    return next(
        item for item in listed.json()["items"] if item["id"] == result.json()["subject_id"]
    )


def derive_payload(parent, artifact, **changes):
    return {
        "name": "Synthetic regional configuration",
        "kind": "region",
        "applicability": ["Synthetic region only"],
        "parent_definition_id": parent["id"],
        "expected_parent_revision": parent["revision"],
        "visibility": "category",
        "overrides": {"purpose": "Synthetic region-specific purpose"},
        "sources": [reference(artifact)],
        "reason": "Record explicit regional scope",
        **changes,
    }


def preview(setup, body):
    result = post(setup, body, preview=True)
    assert result.status_code == 200, result.text
    prepared = result.json()
    assert prepared["command"]["command_id"] == body["command_id"]
    assert prepared["command"]["idempotency_key"] == body["idempotency_key"]
    assert prepared["command"]["payload"]["confirmation_token"] == prepared["confirmation_token"]
    assert (
        prepared["review"]["after"]["parent_definition_id"]
        == body["payload"]["parent_definition_id"]
    )
    return prepared


def variants(setup, headers=None):
    result = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/variants",
        headers=headers or setup.headers,
    )
    assert result.status_code == 200, result.text
    return result.json()["items"]


def derive(setup, parent, artifact, **changes):
    body = command(
        setup, "product.variant.derive", derive_payload(parent, artifact, **changes), artifact
    )
    prepared = preview(setup, body)
    result = post(setup, prepared["command"])
    assert result.status_code == 200, result.text
    item = variants(setup)[0]
    assert item["revisions"][0]["id"] == result.json()["subject_id"]
    return item, prepared, result.json()


def assert_no_variants(setup):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(Variant)) == 0
        assert s.scalar(select(func.count()).select_from(VariantRevision)) == 0


def test_real_preview_returned_command_round_trip_and_receipt_group(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    item, prepared, receipt = derive(setup, parent, artifact)
    revision = item["revisions"][0]
    assert revision["status"] == "draft"
    assert revision["revision"] == 1 and revision["previous_revision_id"] is None
    assert revision["parent_definition_id"] == parent["id"]
    assert revision["applicability"] == ["Synthetic region only"]
    assert revision["overrides"] == {"purpose": "Synthetic region-specific purpose"}
    spec = revision["effective_definition"]["specs"][0]
    assert spec["availability"] == "unknown" and spec["value"] is None
    assert spec["owner_id"] is None and spec["state"] == "needs_confirmation"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.get(Variant, UUID(item["id"])).status == "draft"
        assert s.get(DefinitionRevision, UUID(parent["id"])).purpose == parent["purpose"]
        assert s.scalar(select(Audit.id).where(Audit.receipt_id == UUID(receipt["id"])))
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "variant.derived"
        )
        confirmation = s.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["confirmation_token"])
            )
        )
        assert confirmation.consumed


def test_confirmation_required_and_bound_to_actual_payload_and_read_set(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    body = command(setup, "product.variant.derive", derive_payload(parent, artifact), artifact)
    unconfirmed = post(setup, body)
    assert unconfirmed.status_code == 409 and unconfirmed.json()["code"] == "CONFIRMATION_REQUIRED"
    prepared = preview(setup, body)
    changed = deepcopy(prepared["command"])
    changed["payload"]["applicability"] = ["Different synthetic scope"]
    rejected = post(setup, changed)
    assert rejected.status_code == 409 and rejected.json()["code"] == "CONFIRMATION_REQUIRED"
    assert_no_variants(setup)
    accepted = post(setup, prepared["command"])
    assert accepted.status_code == 200, accepted.text


def test_original_and_new_key_semantic_replays_do_not_consume_twice(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    _, prepared, receipt = derive(setup, parent, artifact)
    original = post(setup, prepared["command"])
    assert original.status_code == 200 and original.json()["id"] == receipt["id"]
    new_key = deepcopy(prepared["command"])
    new_key.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    new_key["payload"].pop("confirmation_token")
    semantic_replay = post(setup, new_key)
    assert semantic_replay.status_code == 200 and semantic_replay.json()["id"] == receipt["id"]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(VariantRevision)) == 1


def test_private_parent_and_private_source_never_expand_audience(setup):
    artifact = source(setup, "private")
    parent = definition(setup, artifact, visibility="private")
    rejected = post(
        setup,
        command(setup, "product.variant.derive", derive_payload(parent, artifact), artifact),
        preview=True,
    )
    assert rejected.status_code == 403 and rejected.json()["code"] == "FORBIDDEN_SCOPE"
    item, _, _ = derive(setup, parent, artifact, visibility="private")
    assert item["visibility"] == "private"
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert variants(setup, peer) == []


def test_foreign_product_parent_is_rejected_even_for_same_owner(setup):
    created = setup.client.post(
        f"/v1/categories/{setup.category}/products",
        headers=setup.headers,
        json={
            "name": "Synthetic separate product",
            "purpose": "Independent synthetic scope",
            "idempotency_key": str(uuid4()),
        },
    )
    assert created.status_code == 201, created.text
    foreign = SimpleNamespace(**{**vars(setup), "product": UUID(created.json()["subject_id"])})
    foreign_source = source(foreign)
    foreign_parent = definition(foreign, foreign_source)
    artifact = source(setup)
    result = post(
        setup,
        command(
            setup, "product.variant.derive", derive_payload(foreign_parent, artifact), artifact
        ),
        preview=True,
    )
    assert result.status_code == 403 and result.json()["code"] == "FORBIDDEN_SCOPE"
    assert_no_variants(setup)


def test_parent_advance_after_preview_blocks_silent_historical_derivation(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    prepared = preview(
        setup, command(setup, "product.variant.derive", derive_payload(parent, artifact), artifact)
    )
    definition(setup, artifact, parent=parent, title="Newer synthetic parent")
    result = post(setup, prepared["command"])
    assert result.status_code == 409 and result.json()["code"] == "VERSION_CONFLICT"
    assert_no_variants(setup)


def test_compare_never_writes_and_rebase_requires_each_conflict_choice(setup):
    artifact = source(setup)
    old = definition(setup, artifact)
    item, _, _ = derive(
        setup,
        old,
        artifact,
        overrides={"title": "Synthetic child title", "constraints": ["Child constraint"]},
    )
    new = definition(
        setup,
        artifact,
        parent=old,
        title="Synthetic parent title revision two",
        requirements=["New parent requirement"],
    )
    compare = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/variants/{item['id']}/compare",
        params={"parent_definition_id": new["id"]},
        headers=setup.headers,
    )
    assert compare.status_code == 200, compare.text
    categories = {change["path"]: change["category"] for change in compare.json()["changes"]}
    assert categories == {
        "constraints": "child_only",
        "requirements": "parent_only",
        "title": "conflict",
    }
    assert compare.json()["conflict_count"] == 1
    assert len(variants(setup)[0]["revisions"]) == 1
    body = command(
        setup,
        "product.variant.rebase",
        {
            "variant_id": item["id"],
            "expected_variant_revision": 1,
            "parent_definition_id": new["id"],
            "expected_parent_revision": 2,
            "sources": [reference(artifact)],
            "reason": "Recheck scope against the new parent",
        },
        artifact,
    )
    missing = post(setup, body, preview=True)
    assert missing.status_code == 409 and missing.json()["code"] == "CONFIRMATION_REQUIRED"
    body["payload"]["choices"] = [
        {"path": "title", "selection": "child", "reason": "Regional title remains applicable"}
    ]
    prepared = preview(setup, body)
    saved = post(setup, prepared["command"])
    assert saved.status_code == 200, saved.text
    current, historical = variants(setup)[0]["revisions"]
    assert current["revision"] == 2 and historical["revision"] == 1
    assert current["previous_revision_id"] == historical["id"]
    assert current["parent_definition_id"] == new["id"]
    assert historical["parent_definition_id"] == old["id"]
    assert current["effective_definition"]["title"] == "Synthetic child title"
    assert current["effective_definition"]["requirements"] == ["New parent requirement"]
    assert current["effective_definition"]["constraints"] == ["Child constraint"]
    assert current["choices"] == body["payload"]["choices"]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.get(DefinitionRevision, UUID(new["id"])).title == new["title"]
        assert s.get(DefinitionRevision, UUID(old["id"])).title == old["title"]


def test_two_confirmed_rebases_cannot_overwrite_each_other(setup):
    artifact = source(setup)
    old = definition(setup, artifact)
    item, _, _ = derive(setup, old, artifact)
    new = definition(setup, artifact, parent=old, title="Parent revision two")
    base = {
        "variant_id": item["id"],
        "expected_variant_revision": 1,
        "parent_definition_id": new["id"],
        "expected_parent_revision": 2,
        "sources": [reference(artifact)],
        "reason": "First explicit rebase review",
    }
    first = preview(setup, command(setup, "product.variant.rebase", base, artifact))
    second = preview(
        setup,
        command(
            setup,
            "product.variant.rebase",
            {**base, "reason": "Second distinct rebase review"},
            artifact,
        ),
    )
    assert post(setup, first["command"]).status_code == 200
    stale = post(setup, second["command"])
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    assert [row["revision"] for row in variants(setup)[0]["revisions"]] == [2, 1]


@pytest.mark.parametrize("revocation", ["source", "grant", "confirmation"])
def test_current_guards_are_checked_again_before_confirmed_commit(setup, revocation):
    artifact = source(setup)
    parent = definition(setup, artifact)
    prepared = preview(
        setup, command(setup, "product.variant.derive", derive_payload(parent, artifact), artifact)
    )
    with Session(setup.admin) as s, s.begin():
        if revocation == "source":
            s.get(Artifact, UUID(artifact)).status = "withdrawn"
        elif revocation == "grant":
            grant = s.scalar(
                select(Grant).where(
                    Grant.category_id == setup.category, Grant.principal_id == setup.human
                )
            )
            grant.expires_at = now() - timedelta(seconds=1)
        else:
            confirmation = s.scalar(
                select(Confirmation).where(
                    Confirmation.token_hash == digest(prepared["confirmation_token"])
                )
            )
            confirmation.expires_at = now() - timedelta(seconds=1)
    result = post(setup, prepared["command"])
    expected = {
        "source": (409, "SOURCE_UNAVAILABLE"),
        "grant": (403, "FORBIDDEN_SCOPE"),
        "confirmation": (409, "CONFIRMATION_REQUIRED"),
    }
    assert (result.status_code, result.json()["code"]) == expected[revocation]
    assert_no_variants(setup)


def test_receipt_failure_rolls_back_variant_revision_and_confirmation(setup, monkeypatch):
    artifact = source(setup)
    parent = definition(setup, artifact)
    prepared = preview(
        setup, command(setup, "product.variant.derive", derive_payload(parent, artifact), artifact)
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic variant receipt failure")

    monkeypatch.setattr("pdos_next.service.append_receipt", fail)
    with pytest.raises(RuntimeError, match="Synthetic variant receipt failure"):
        post(setup, prepared["command"])
    assert_no_variants(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        confirmation = s.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["confirmation_token"])
            )
        )
        assert not confirmation.consumed
        assert (
            s.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "product.variant.derive")
            )
            == 0
        )


def test_saved_variant_and_revision_are_database_immutable(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    derive(setup, parent, artifact)
    for model, changes in [
        (Variant, {"name": "Changed"}),
        (VariantRevision, {"reason": "Changed"}),
    ]:
        with (
            pytest.raises(DBAPIError),
            tenant_session(
                setup.engine,
                setup.tenant,
                actor_id=setup.human,
                requester_id=setup.human,
                category_id=setup.category,
            ) as s,
        ):
            s.execute(update(model).values(**changes))


def test_agent_cannot_bypass_human_only_variant_validation(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    body = Command.model_validate(
        command(setup, "product.variant.derive", derive_payload(parent, artifact), artifact)
    )
    with (
        pytest.raises(DomainError) as failed,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=setup.human,
            category_id=setup.category,
        ) as s,
    ):
        validate(
            s,
            Context(setup.tenant, setup.agent, setup.human, category_id=setup.category),
            body,
            s.get(Product, setup.product),
            VariantDerivePayload.model_validate(body.payload),
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    assert_no_variants(setup)


def test_source_withdrawal_preserves_replay_and_blocks_a_new_derivation(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    _, prepared, _ = derive(setup, parent, artifact)
    with Session(setup.admin) as s, s.begin():
        s.get(Artifact, UUID(artifact)).status = "withdrawn"
    history = variants(setup)[0]["revisions"][0]
    assert history["source_status"] == "needs_recheck"
    assert history["effective_definition"]["purpose"] == "Synthetic region-specific purpose"
    replay = post(setup, prepared["command"])
    assert replay.status_code == 200
    fresh = command(
        setup,
        "product.variant.derive",
        derive_payload(parent, artifact, name="Another fresh derivation"),
        artifact,
    )
    refused = post(setup, fresh, preview=True)
    assert refused.status_code == 409 and refused.json()["code"] == "SOURCE_UNAVAILABLE"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(VariantRevision)) == 1


def test_expired_category_read_grant_denies_entire_derived_history(setup):
    artifact = source(setup)
    parent = definition(setup, artifact)
    derive(setup, parent, artifact)
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    listed = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/variants", headers=setup.headers
    )
    assert listed.status_code == 403 and listed.json()["code"] == "FORBIDDEN_SCOPE"
    assert "items" not in listed.json()
    assert "Synthetic region-specific purpose" not in listed.text
    assert "Pressure: 150 PSI" not in listed.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(func.count()).select_from(VariantRevision)) == 0
    with Session(setup.admin) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(VariantRevision)
                .where(VariantRevision.tenant_id == setup.tenant)
            )
            == 1
        )
