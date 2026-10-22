"""Actual human definition continuation; run only on the root's isolated PG target.

All definitions, item edits, references and receipts use the real command path.
Administrative writes are limited to fixture membership and source withdrawal.
"""

from copy import copy
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject.schemas import Reference
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource, DefinitionSpecRow
from pdos_next.models import Artifact, Grant, Receipt
from tests.preproject.test_evidence_commands_pg import artifact as category_artifact
from tests.preproject.test_g0 import create, decide_request, request, save, submit
from tests.preproject.test_g0 import payload as proposal_payload
from tests.preproject.test_g0 import read as read_proposal
from tests.preproject.test_material_commands_pg import parameter
from tests.products.test_definition_item_commands_pg import (
    confirmed,
    current_items,
    draft,
    patch,
    upsert,
)
from tests.products.test_definition_transactions import command, payload, post, source


def inherit(setup, parent_id, revision=1):
    return command(
        setup,
        "product.definition.draft",
        {
            "mode": "inherit_parent",
            "parent_definition_id": str(parent_id),
            "expected_parent_revision": revision,
            "change_reason": "从实际固定父版继续编辑合成草稿",
        },
    )


def copied_values(row):
    # Enumerate the actual stored fields so new schema fields cannot silently
    # disappear in the copy while this test still reports success.
    identity = {
        "id",
        "tenant_id",
        "category_id",
        "product_id",
        "definition_id",
        "created_at",
        "item_id",
        "item_version",
        "removed",
        "receipt_id",
    }
    return {
        column.name: getattr(row, column.name)
        for column in DefinitionSpecRow.__table__.columns
        if column.name not in identity
    }


def test_inherit_copies_only_current_complete_typed_items_and_new_receipt(setup):
    definition_id, _ = draft(setup)
    original = current_items(setup, definition_id)["pressure"]
    dictionary, _ = save(
        setup,
        request(
            setup,
            "category.parameter.publish",
            parameter(key="pressure"),
        ),
    )
    human_ref = {
        "type": "human",
        "id": str(setup.human),
        "version": 1,
        "statement": "本人确认的合成目标，不是测试实测值",
    }
    zero = upsert(
        original,
        parameter_id=dictionary["result"]["parameter_id"],
        parameter_version=1,
        value="0",
        unit="dB",
        tolerance="0",
        availability="known",
        item_status="confirmed",
        condition_note="固定条件",
        test_conditions=["常温"],
        verification_method="合成测试",
        acceptance_criterion="精确零目标",
        owner_id=str(setup.human),
        reason="人工目标",
        modality="must",
        exceptions=[{"text": "仅室内", "applies_to": "台架"}],
        applicable_variants=[{"key": "base"}],
    )
    boolean = upsert(
        key="display",
        value_type="boolean",
        text_value="false",
        availability="known",
        item_status="confirmed",
    )
    enum = upsert(
        key="finish",
        value_type="enum",
        text_value="matte",
        availability="known",
        item_status="confirmed",
    )
    obsolete = upsert(key="obsolete")
    for op in (zero, boolean, enum):
        op["source_refs"] = [human_ref]
    edited = post(setup, patch(setup, definition_id, zero, boolean, enum, obsolete))
    assert edited.status_code == 200, edited.text
    old = current_items(setup, definition_id)["obsolete"]
    confirmed(
        setup,
        patch(
            setup,
            definition_id,
            {
                "op": "remove",
                "item_id": str(old.item_id),
                "base_version": old.item_version,
            },
        ),
    )
    parents = current_items(setup, definition_id)
    saved = post(setup, inherit(setup, definition_id))
    assert saved.status_code == 200, saved.text
    child_id = UUID(saved.json()["subject_id"])
    children = current_items(setup, child_id)
    assert set(children) == {"pressure", "display", "finish"}
    assert children["pressure"].value == children["pressure"].tolerance == Decimal(0)
    assert children["display"].text == "false" and children["finish"].text == "matte"
    assert children["pressure"].parameter_id == UUID(dictionary["result"]["parameter_id"])
    for key, child in children.items():
        parent = parents[key]
        assert copied_values(child) == copied_values(parent)
        assert child.id == child.item_id and child.id != parent.id
        assert child.item_version == 1 and not child.removed
        assert child.prepared_candidate_id == parent.prepared_candidate_id
        assert str(child.receipt_id) == saved.json()["id"] and child.receipt_id != parent.receipt_id
    with Session(setup.admin) as session:
        header = session.get(DefinitionRevision, child_id)
        assert header.parent_definition_id == definition_id and header.revision == 2
        assert header.status == "draft" and not header.sealed
        assert session.get(DefinitionSpecRow, original.id).value is None
        receipt = session.get(Receipt, UUID(saved.json()["id"]))
        assert receipt.actor_id == receipt.requester_id == setup.human
        assert receipt.run_id is None and receipt.agent_run_id is None
        assert receipt.result["inherited_from"] == str(definition_id)
        assert {item["parent_row_id"] for item in receipt.result["item_copies"]} == {
            str(parents[key].id) for key in children
        }


def test_inherit_same_request_replays_and_stale_parent_cannot_branch(setup):
    definition_id, _ = draft(setup)
    wrong = post(setup, inherit(setup, definition_id, revision=2))
    assert wrong.status_code == 409 and wrong.json()["code"] == "VERSION_CONFLICT"
    cmd = inherit(setup, definition_id)
    saved = post(setup, cmd)
    assert saved.status_code == 200, saved.text
    replay = post(setup, cmd)
    assert replay.status_code == 200 and replay.json()["id"] == saved.json()["id"]
    same_intent = post(setup, inherit(setup, definition_id))
    assert same_intent.status_code == 200 and same_intent.json()["id"] == saved.json()["id"]
    stale_command = inherit(setup, definition_id)
    stale_command["payload"]["change_reason"] = "另一个实际新增意图，仍错误固定在旧父版"
    stale = post(setup, stale_command)
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(DefinitionRevision)
                .where(
                    DefinitionRevision.product_id == setup.product,
                )
            )
            == 2
        )


@pytest.mark.parametrize("actor", ["peer", "other_human"])
def test_private_or_cross_tenant_parent_is_not_a_copy_capability(setup, actor):
    definition_id, _ = draft(setup)
    forbidden = copy(setup)
    forbidden.headers = {"Authorization": f"Bearer {setup.tokens[getattr(setup, actor)]}"}
    response = post(forbidden, inherit(forbidden, definition_id))
    assert response.status_code in {403, 404}, response.text
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(DefinitionRevision)
                .where(
                    DefinitionRevision.product_id == setup.product,
                )
            )
            == 1
        )


def test_inherit_checks_typed_source_not_present_in_legacy_definition_sources(setup):
    definition_id, _ = draft(setup)
    with Session(setup.admin) as session:
        legacy_sources = set(
            session.scalars(
                select(DefinitionSource.artifact_id).where(
                    DefinitionSource.definition_id == definition_id,
                )
            )
        )
        assert legacy_sources
    registered = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Distinct synthetic typed-only source",
                "source_label": "Synthetic typed reference fixture only",
                "content": "Synthetic only\nPressure: 150 PSI\nTest conditions unknown",
                "visibility": "private",
            },
        ),
    )
    assert registered.status_code == 200, registered.text
    typed_artifact = registered.json()["subject_id"]
    assert UUID(typed_artifact) not in legacy_sources
    op = upsert(key="typed_only", reason="固定独立原文")
    op["source_refs"] = [
        {
            "type": "artifact",
            "id": typed_artifact,
            "version": 1,
            "line": 2,
            "quote": "Pressure: 150 PSI",
        }
    ]
    changed = post(setup, patch(setup, definition_id, op))
    assert changed.status_code == 200, changed.text
    with Session(setup.admin) as session, session.begin():
        assert (
            set(
                session.scalars(
                    select(DefinitionSource.artifact_id).where(
                        DefinitionSource.definition_id == definition_id,
                    )
                )
            )
            == legacy_sources
        )
        assert UUID(typed_artifact) not in legacy_sources
        assert all(
            session.get(Artifact, identity).status == "active" for identity in legacy_sources
        )
        session.get(Artifact, UUID(typed_artifact)).status = "withdrawn"
    response = post(setup, inherit(setup, definition_id))
    assert response.status_code in {403, 409}, response.text
    assert response.json()["code"] in {"SOURCE_UNAVAILABLE", "SOURCE_STALE"}
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(DefinitionRevision)
                .where(
                    DefinitionRevision.product_id == setup.product,
                )
            )
            == 1
        )


def test_referenced_parent_stays_fixed_while_inherited_draft_can_be_edited(setup):
    artifact_id = source(setup, visibility="category")
    created = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(artifact_id, visibility="category"),
            artifact_id,
        ),
    )
    assert created.status_code == 200, created.text
    definition_id = UUID(created.json()["subject_id"])
    old = current_items(setup, definition_id)["pressure"]
    peer = copy(setup)
    peer.human = setup.peer
    peer.headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    proposal = proposal_payload(peer)
    proposal["source_refs"] = [{"type": "definition", "id": str(definition_id), "version": 1}]
    proposal_id, _ = create(peer, proposal)
    assert read_proposal(setup, proposal_id).status_code in {403, 404}
    blocked = post(setup, patch(setup, definition_id, upsert(old, reason="不得修改被引用父版")))
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["reason"] == "definition_consumed"
    child = post(setup, inherit(setup, definition_id))
    assert child.status_code == 200, child.text
    child_id = UUID(child.json()["subject_id"])
    changed = post(
        setup,
        patch(
            setup,
            child_id,
            upsert(
                current_items(setup, child_id)["pressure"],
                reason="仅修改新的独立草稿",
            ),
        ),
    )
    assert changed.status_code == 200, changed.text
    assert current_items(setup, definition_id)["pressure"].id == old.id
    assert current_items(setup, child_id)["pressure"].item_version == 2
    assert read_proposal(peer, proposal_id).json()["source_refs"] == [
        Reference.model_validate(ref).model_dump(mode="json") for ref in proposal["source_refs"]
    ]


def test_g0_new_product_continuation_copies_category_source_without_decision_credentials(setup):
    category_source_id = category_artifact(
        setup,
        body="Synthetic only\nPressure: 150 PSI\nTest conditions unknown",
        visibility="category",
    )
    with Session(setup.admin) as session, session.begin():
        assert session.get(Artifact, category_source_id).product_id is None
        reviewer = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category,
                Grant.principal_id == setup.peer,
            )
        )
        reviewer.product_manager = True
    setup.expert = setup.peer
    proposal = proposal_payload(setup)
    display = next(
        item
        for item in proposal["groups"]["items"]
        if item["kind"] == "spec" and item["content"]["key"] == "display"
    )
    display["source_refs"] = [
        {
            "type": "artifact",
            "id": str(category_source_id),
            "version": 1,
            "line": 2,
            "quote": "Pressure: 150 PSI",
        }
    ]
    proposal_id, _ = create(setup, proposal)
    submit(setup, proposal_id)
    decision, _ = save(setup, decide_request(setup, proposal_id), actor=setup.peer)
    target = copy(setup)
    target.product = UUID(decision["result"]["product_id"])
    parent_id = UUID(decision["result"]["definition_id"])
    assert target.product != setup.product
    crossed = post(setup, inherit(setup, parent_id))
    assert crossed.status_code in {403, 404}, crossed.text
    before = current_items(target, parent_id)
    result = post(target, inherit(target, parent_id))
    assert result.status_code == 200, result.text
    child_id = UUID(result.json()["subject_id"])
    copied = current_items(target, child_id)
    assert {key: copied_values(row) for key, row in copied.items()} == {
        key: copied_values(row) for key, row in before.items()
    }
    with Session(setup.admin) as session:
        parent = session.get(DefinitionRevision, parent_id)
        child = session.get(DefinitionRevision, child_id)
        assert parent.sealed and str(parent.g0_decision_id) == decision["result"]["decision_id"]
        assert not child.sealed and child.status == "draft" and child.revision == 2
        assert child.parent_definition_id == parent.id
        for field in (
            "g0_decision_id",
            "source_proposal_id",
            "source_submission_id",
            "source_proposal_revision",
            "publication_receipt_id",
            "derived_from_definition_id",
            "derived_from_definition_revision",
        ):
            assert getattr(child, field) is None
        source_row = session.scalar(
            select(DefinitionSource).where(
                DefinitionSource.definition_id == child_id,
            )
        )
        assert source_row.artifact_id == category_source_id
        assert source_row.source_revision == 1 and source_row.line == 2
        assert source_row.quote == "Pressure: 150 PSI" and source_row.spec_keys == ["display"]
    modified = post(
        target,
        patch(
            target,
            child_id,
            upsert(
                copied["noise"],
                key="noise",
                reason="继续新草稿，父版仍固定",
            ),
        ),
    )
    assert modified.status_code == 200, modified.text
    assert current_items(target, parent_id)["noise"].id == before["noise"].id
