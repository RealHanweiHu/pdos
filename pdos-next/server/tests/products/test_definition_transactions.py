from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.products.definitions import validate
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource, DefinitionSpecRow
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Outbox, Product, Receipt
from pdos_next.schemas.products.definitions import DefinitionDraftPayload
from pdos_next.service import Context


def command(setup, operation, payload, artifact=None):
    return {
        "category_id": str(setup.category),
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": operation,
        "product_id": str(setup.product),
        "expected_revision": 1,
        "source_read_set": [{"artifact_id": artifact, "expected_revision": 1}] if artifact else [],
        "payload": payload,
    }


def post(setup, cmd):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=cmd
    )


def source(setup, visibility="private"):
    result = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic specification source",
                "source_label": "Synthetic fixture only",
                "content": "Synthetic only\nPressure: 150 PSI\nTest conditions unknown",
                "visibility": visibility,
            },
        ),
    )
    assert result.status_code == 200, result.text
    return result.json()["subject_id"]


def payload(artifact, **overrides):
    reference = {
        "artifact_id": artifact,
        "expected_revision": 1,
        "line": 2,
        "quote": "Pressure: 150 PSI",
    }
    return {
        "title": "Synthetic definition",
        "purpose": "Synthetic product verification only",
        "visibility": "private",
        "use_cases": ["Synthetic evaluation"],
        "unknowns": ["Test condition not confirmed"],
        "change_reason": "Save first synthetic draft",
        "sources": [reference],
        "specs": [
            {
                "key": "pressure",
                "parameter": "Pressure under declared conditions",
                "value_type": "number",
                "availability": "unknown",
                "reason": "Cannot infer conditions",
                "sources": [reference],
            }
        ],
        **overrides,
    }


def definitions(setup, headers=None):
    return setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/definitions",
        headers=headers or setup.headers,
    )


def test_draft_group_receipt_and_exact_unknown_source(setup):
    artifact = source(setup)
    result = post(setup, command(setup, "product.definition.draft", payload(artifact), artifact))
    assert result.status_code == 200, result.text
    receipt = result.json()
    listed = definitions(setup)
    assert listed.status_code == 200, listed.text
    item = listed.json()["items"][0]
    assert item["status"] == "draft" and item["revision"] == 1
    assert item["specs"][0]["value"] is None
    assert item["sources"][0]["quote"] == "Pressure: 150 PSI"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        assert s.scalar(select(Audit.id).where(Audit.receipt_id == UUID(receipt["id"])))
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "definition.draft_created"
        )
        assert s.scalar(select(func.count()).select_from(DefinitionSource)) == 1
        assert s.scalar(select(func.count()).select_from(DefinitionSpecRow)) == 1


def test_private_source_cannot_expand_and_private_definition_is_hidden(setup):
    artifact = source(setup)
    bad = post(
        setup,
        command(
            setup, "product.definition.draft", payload(artifact, visibility="category"), artifact
        ),
    )
    assert bad.status_code == 403 and bad.json()["code"] == "FORBIDDEN_SCOPE"
    saved = post(setup, command(setup, "product.definition.draft", payload(artifact), artifact))
    assert saved.status_code == 200, saved.text
    peer = definitions(setup, {"Authorization": f"Bearer {setup.tokens[setup.peer]}"})
    assert peer.status_code == 200 and peer.json()["items"] == []


def test_wrong_quote_rolls_back_all_definition_members(setup):
    artifact = source(setup)
    body = payload(artifact)
    body["sources"][0]["quote"] = "Pressure: 200 PSI"
    result = post(setup, command(setup, "product.definition.draft", body, artifact))
    assert result.status_code == 409 and result.json()["code"] == "MISSING_REQUIRED_EVIDENCE"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        for model in (DefinitionRevision, DefinitionSource, DefinitionSpecRow):
            assert s.scalar(select(func.count()).select_from(model)) == 0


def test_same_request_replays_but_stale_parent_cannot_branch(setup):
    artifact = source(setup)
    initial = command(setup, "product.definition.draft", payload(artifact), artifact)
    first = post(setup, initial)
    assert first.status_code == 200, first.text
    first_id = first.json()["subject_id"]
    child_payload = payload(
        artifact,
        parent_definition_id=first_id,
        expected_parent_revision=1,
        title="Second synthetic version",
        change_reason="Clarify current unknowns",
    )
    child = post(setup, command(setup, "product.definition.draft", child_payload, artifact))
    assert child.status_code == 200, child.text
    replay = post(setup, initial)
    assert replay.status_code == 200 and replay.json()["id"] == first.json()["id"]
    stale = post(
        setup,
        command(
            setup, "product.definition.draft", {**child_payload, "title": "Stale branch"}, artifact
        ),
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    items = definitions(setup).json()["items"]
    assert [item["revision"] for item in items] == [2, 1]
    assert items[1]["title"] == "Synthetic definition"
    assert items[0]["parent_definition_id"] == first_id
    assert {change["path"] for change in items[0]["differences"]} == {"title"}


def test_definition_and_members_are_database_immutable(setup):
    artifact = source(setup)
    result = post(setup, command(setup, "product.definition.draft", payload(artifact), artifact))
    assert result.status_code == 200, result.text
    for model, changes in [
        (DefinitionRevision, {"title": "Changed"}),
        (DefinitionSpecRow, {"reason": "Changed"}),
        (DefinitionSource, {"quote": "Changed"}),
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


def test_withdrawn_source_blocks_continuation_but_preserves_saved_history(setup):
    artifact = source(setup)
    first = post(setup, command(setup, "product.definition.draft", payload(artifact), artifact))
    assert first.status_code == 200, first.text
    with Session(setup.admin) as s, s.begin():
        s.get(Artifact, UUID(artifact)).status = "withdrawn"
    result = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(
                artifact,
                parent_definition_id=first.json()["subject_id"],
                expected_parent_revision=1,
                title="Cannot continue",
            ),
            artifact,
        ),
    )
    assert result.status_code == 409 and result.json()["code"] == "SOURCE_UNAVAILABLE"
    item = definitions(setup).json()["items"][0]
    assert item["source_status"] == "needs_recheck" and item["sources"][0]["status"] == "withdrawn"
    assert item["title"] == "Synthetic definition"


def test_agent_cannot_bypass_manual_definition_handler(setup):
    artifact = source(setup)
    cmd = Command.model_validate(
        command(setup, "product.definition.draft", payload(artifact), artifact)
    )
    ctx = Context(setup.tenant, setup.agent, setup.human, category_id=setup.category)
    with (
        pytest.raises(DomainError) as failed,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as s,
    ):
        validate(
            s,
            ctx,
            cmd,
            s.get(Product, setup.product),
            DefinitionDraftPayload.model_validate(cmd.payload),
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"


def test_receipt_failure_does_not_leave_half_definition(setup, monkeypatch):
    artifact = source(setup)

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic receipt failure")

    monkeypatch.setattr("pdos_next.service.append_receipt", fail)
    with pytest.raises(RuntimeError, match="Synthetic receipt failure"):
        post(setup, command(setup, "product.definition.draft", payload(artifact), artifact))
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as s:
        for model in (DefinitionRevision, DefinitionSpecRow, DefinitionSource):
            assert s.scalar(select(func.count()).select_from(model)) == 0
        assert (
            s.scalar(
                select(func.count())
                .select_from(Receipt)
                .where(Receipt.operation == "product.definition.draft")
            )
            == 0
        )


def test_competing_initial_versions_serialize_without_silent_branch(setup):
    artifact = source(setup)
    candidates = [
        command(setup, "product.definition.draft", payload(artifact, title=title), artifact)
        for title in ["First contender", "Second contender"]
    ]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda cmd: post(setup, cmd), candidates))
    assert sorted(result.status_code for result in results) == [200, 409]
    assert (
        next(result for result in results if result.status_code == 409).json()["code"]
        == "VERSION_CONFLICT"
    )
    assert len(definitions(setup).json()["items"]) == 1
