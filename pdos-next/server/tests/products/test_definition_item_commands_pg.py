"""Definition item commands on the explicit isolated PostgreSQL fixture."""

from concurrent.futures import ThreadPoolExecutor
from copy import copy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSpecRow
from pdos_next.models import Artifact, Category, Grant, Product, Receipt
from tests.products.test_definition_transactions import command, payload, post, source

OPERATION = "product.definition.item.patch"


def draft(setup):
    artifact_id = source(setup)
    result = post(
        setup, command(setup, "product.definition.draft", payload(artifact_id), artifact_id)
    )
    assert result.status_code == 200, result.text
    return UUID(result.json()["subject_id"]), artifact_id


def current_items(setup, definition_id):
    from pdos_next.domain.products.models import DefinitionSpecCurrent

    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        rows = session.scalars(
            select(DefinitionSpecRow)
            .join(
                DefinitionSpecCurrent,
                DefinitionSpecCurrent.current_row_id == DefinitionSpecRow.id,
            )
            .where(DefinitionSpecRow.definition_id == definition_id)
        ).all()
        session.expunge_all()
        return {row.key: row for row in rows}


def spec(key="pressure", **changes):
    return {
        "key": key,
        "parameter": "合成参数",
        "value_type": "number",
        "availability": "unknown",
        "item_status": "unknown",
        **changes,
    }


def patch(setup, definition_id, *ops, **changes):
    return command(
        setup, OPERATION, {"definition_id": str(definition_id), "ops": list(ops), **changes}
    )


def upsert(row=None, **content):
    return {
        "op": "upsert",
        "content": spec(**content),
        **({"item_id": str(row.item_id), "base_version": row.item_version} if row else {}),
    }


def confirmed(setup, cmd):
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=setup.headers, json=cmd
    )
    assert preview.status_code == 200, preview.text
    result = post(setup, preview.json()["command"])
    assert result.status_code == 200, result.text
    return result.json(), preview.json()["command"]


def test_human_append_complete_spec_and_remove_replay(setup):
    definition_id, artifact_id = draft(setup)
    first = current_items(setup, definition_id)["pressure"]
    op = upsert(
        first,
        availability="known",
        item_status="confirmed",
        value="150.123456789012",
        unit="PSI",
        test_conditions=["室温"],
        condition_note="固定台架",
        verification_method="原文逐字记录",
        acceptance_criterion="上限核对",
        modality="must",
        exceptions=[{"text": "仅常温", "applies_to": "室内"}],
        applicable_variants=[{"key": "base"}],
        nature="extracted",
    )
    op["source_refs"] = [
        {
            "type": "artifact",
            "id": artifact_id,
            "version": 1,
            "line": 2,
            "quote": "Pressure: 150 PSI",
        }
    ]
    cmd = patch(setup, definition_id, op)
    saved = post(setup, cmd)
    assert saved.status_code == 200, saved.text
    second = current_items(setup, definition_id)["pressure"]
    assert second.id != first.id and second.item_id == first.item_id and second.item_version == 2
    assert str(second.value) == "150.123456789012"
    assert second.test_conditions == ["室温"] and second.condition_note == "固定台架"
    assert second.method == "原文逐字记录" and second.acceptance_criterion == "上限核对"
    assert second.origin == "human" and second.writer_id == setup.human and second.run_id is None
    assert str(second.receipt_id) == saved.json()["id"]
    assert post(setup, cmd).json()["id"] == saved.json()["id"]
    remove = patch(
        setup, definition_id, {"op": "remove", "item_id": str(second.item_id), "base_version": 2}
    )
    removed, prepared = confirmed(setup, remove)
    assert "content" not in prepared["payload"]["ops"][0]
    assert "source_refs" not in prepared["payload"]["ops"][0]
    tombstone = current_items(setup, definition_id)["pressure"]
    assert tombstone.removed and tombstone.item_version == 3
    assert tombstone.value == second.value and tombstone.source_refs == second.source_refs
    assert post(setup, prepared).json()["id"] == removed["id"]
    with Session(setup.admin) as session:
        original = session.get(DefinitionSpecRow, first.id)
        assert original.value is None and original.item_version == 1 and not original.removed
        assert session.get(DefinitionRevision, definition_id).revision == 1
        assert session.get(Product, setup.product).revision == 1


def test_independent_item_versions_do_not_conflict_and_same_item_does(setup):
    definition_id, _ = draft(setup)
    added = post(setup, patch(setup, definition_id, upsert(key="noise")))
    assert added.status_code == 200, added.text
    before = current_items(setup, definition_id)
    requests = [
        patch(setup, definition_id, upsert(row, key=key, reason="独立人工修订"))
        for key, row in before.items()
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda cmd: post(setup, cmd), requests))
    assert [response.status_code for response in results] == [200, 200], [r.text for r in results]
    assert {row.item_version for row in current_items(setup, definition_id).values()} == {2}
    stale = post(
        setup, patch(setup, definition_id, upsert(before["pressure"], reason="旧版再次改动"))
    )
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    assert stale.json()["detail"]["reason"] == "definition_item_moved"


def test_source_withdrawn_after_preview_prevents_new_item_version(setup):
    definition_id, artifact_id = draft(setup)
    before = current_items(setup, definition_id)["pressure"]
    op = upsert(before, reason="等待原件核对")
    op["source_refs"] = [
        {
            "type": "artifact",
            "id": artifact_id,
            "version": 1,
            "line": 2,
            "quote": "Pressure: 150 PSI",
        }
    ]
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=patch(setup, definition_id, op),
    )
    assert preview.status_code == 200, preview.text
    with Session(setup.admin) as session, session.begin():
        session.get(Artifact, UUID(artifact_id)).status = "withdrawn"
    denied = post(setup, preview.json()["command"])
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] in {"SOURCE_UNAVAILABLE", "SOURCE_STALE"}
    assert current_items(setup, definition_id)["pressure"].id == before.id


def test_bad_quote_and_dictionary_scope_key_unit_reject_atomically(setup):
    from tests.preproject.test_g0 import request, save
    from tests.preproject.test_material_commands_pg import parameter

    definition_id, artifact_id = draft(setup)
    before = current_items(setup, definition_id)["pressure"]
    dictionary, _ = save(
        setup, request(setup, "category.parameter.publish", parameter(key="pressure"))
    )
    parameter_id = dictionary["result"]["parameter_id"]
    other = copy(setup)
    other.category = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=other.category,
                tenant_id=setup.tenant,
                name="另一个品类",
                purpose="合成范围验证",
                owner_id=setup.human,
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=other.category,
                principal_id=setup.human,
                can_write=True,
            )
        )
    foreign, _ = save(
        other, request(other, "category.parameter.publish", parameter(key="pressure"))
    )
    for content, reason in [
        (
            dict(parameter_id=parameter_id, parameter_version=1, unit="Pa"),
            "parameter_unit_mismatch",
        ),
        (
            dict(key="different", parameter_id=parameter_id, parameter_version=1, unit="dB"),
            "definition_item_key_immutable",
        ),
        (
            dict(parameter_id=foreign["result"]["parameter_id"], parameter_version=1, unit="dB"),
            "parameter_unreadable",
        ),
    ]:
        result = post(setup, patch(setup, definition_id, upsert(before, **content)))
        assert result.status_code == 409 and result.json()["detail"]["reason"] == reason, (
            result.text
        )
    mismatched_key = post(
        setup,
        patch(
            setup,
            definition_id,
            upsert(key="new-key", parameter_id=parameter_id, parameter_version=1, unit="dB"),
        ),
    )
    assert mismatched_key.status_code == 409
    assert mismatched_key.json()["detail"]["reason"] == "parameter_key_mismatch"
    invalid = upsert(before)
    invalid["source_refs"] = [
        {"type": "artifact", "id": artifact_id, "version": 1, "line": 2, "quote": "并不存在的原文"}
    ]
    result = post(setup, patch(setup, definition_id, invalid, upsert(key="untouched")))
    assert result.status_code == 409 and result.json()["detail"]["reason"] == "quote_not_in_source"
    assert set(current_items(setup, definition_id)) == {"pressure"}
    assert current_items(setup, definition_id)["pressure"].item_version == 1


def test_receipt_failure_rolls_back_rows_and_trigger_current(setup, monkeypatch):
    import pdos_next.service as common

    definition_id, _ = draft(setup)
    before = current_items(setup, definition_id)["pressure"]
    cmd = patch(setup, definition_id, upsert(before, reason="需要原子提交"), upsert(key="noise"))

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr(common, "append_receipt", fail_receipt)
    with pytest.raises(RuntimeError, match="synthetic receipt failure"):
        post(setup, cmd)
    assert set(current_items(setup, definition_id)) == {"pressure"}
    assert current_items(setup, definition_id)["pressure"].id == before.id
    with Session(setup.admin) as session:
        assert not session.scalar(
            select(Receipt.id).where(
                Receipt.tenant_id == setup.tenant, Receipt.operation == OPERATION
            )
        )


def test_g0_sealed_parent_cannot_be_patched(setup):
    from tests.preproject.test_g0 import create, decide_request, save, submit

    with Session(setup.admin) as session, session.begin():
        reviewer = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.peer
            )
        )
        reviewer.product_manager = True
    setup.expert = setup.peer
    proposal_id, _ = create(setup)
    submit(setup, proposal_id)
    receipt, _ = save(setup, decide_request(setup, proposal_id), actor=setup.peer)
    target = copy(setup)
    target.product = UUID(receipt["result"]["product_id"])
    definition_id = UUID(receipt["result"]["definition_id"])
    old = current_items(target, definition_id)["noise"]
    result = post(
        target, patch(target, definition_id, upsert(old, key="noise", reason="拒绝改封存版"))
    )
    assert result.status_code == 409 and result.json()["detail"]["reason"] == "definition_locked"
    assert current_items(target, definition_id)["noise"].id == old.id


@pytest.mark.parametrize("consumer", ["private_proposal", "variant", "definition"])
def test_actual_fixed_consumer_preserves_parent_and_allows_next_draft(setup, consumer):
    from tests.preproject.test_g0 import create
    from tests.preproject.test_g0 import payload as proposal_payload
    from tests.preproject.test_g0 import read as read_proposal
    from tests.products.test_variants_transactions import derive

    artifact_id = source(setup, visibility="category")
    body = payload(artifact_id, visibility="category")
    initial = post(setup, command(setup, "product.definition.draft", body, artifact_id))
    assert initial.status_code == 200, initial.text
    identity = UUID(initial.json()["subject_id"])
    before = current_items(setup, identity)["pressure"]
    ref = {"type": "definition", "id": str(identity), "version": 1}
    next_definition = None
    if consumer == "private_proposal":
        peer = copy(setup)
        peer.human = setup.peer
        peer.headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
        proposal = proposal_payload(peer)
        proposal["source_refs"] = [ref]
        private_id, _ = create(peer, proposal)
        assert read_proposal(setup, private_id).status_code in {403, 404}
    elif consumer == "variant":
        derive(setup, {"id": str(identity), "revision": 1}, artifact_id)
    else:
        child = post(
            setup,
            command(
                setup,
                "product.definition.draft",
                {
                    **body,
                    "parent_definition_id": str(identity),
                    "expected_parent_revision": 1,
                    "change_reason": "从固定父版续写草稿",
                },
                artifact_id,
            ),
        )
        assert child.status_code == 200, child.text
        next_definition = UUID(child.json()["subject_id"])
    denied = post(setup, patch(setup, identity, upsert(before, reason="不能漂移固定版")))
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == "VERSION_CONFLICT"
    assert denied.json()["detail"]["reason"] == "definition_consumed"
    assert current_items(setup, identity)["pressure"].id == before.id
    if next_definition is None:
        child = post(
            setup,
            command(
                setup,
                "product.definition.draft",
                {
                    **body,
                    "parent_definition_id": str(identity),
                    "expected_parent_revision": 1,
                    "change_reason": "从固定父版续写草稿",
                },
                artifact_id,
            ),
        )
        assert child.status_code == 200, child.text
        next_definition = UUID(child.json()["subject_id"])
    next_item = current_items(setup, next_definition)["pressure"]
    changed = post(setup, patch(setup, next_definition, upsert(next_item, reason="仅编辑后续草稿")))
    assert changed.status_code == 200, changed.text
    assert current_items(setup, identity)["pressure"].id == before.id
    assert current_items(setup, next_definition)["pressure"].item_version == 2


def test_unsupported_shared_knowledge_reference_does_not_freeze_definition(setup):
    from tests.preproject.test_g0 import post as category_post
    from tests.preproject.test_g0 import request
    from tests.preproject.test_material_commands_pg import knowledge

    artifact_id = source(setup, visibility="category")
    initial = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(artifact_id, visibility="category"),
            artifact_id,
        ),
    )
    assert initial.status_code == 200, initial.text
    definition_id = UUID(initial.json()["subject_id"])
    before = current_items(setup, definition_id)["pressure"]
    denied = category_post(
        setup,
        request(
            setup,
            "category.knowledge.add",
            knowledge(
                source_refs=[{"type": "definition", "id": str(definition_id), "version": 1}],
            ),
        ),
        preview=True,
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["reason"] == "private_source_in_shared"
    changed = post(
        setup, patch(setup, definition_id, upsert(before, reason="拒绝未保存知识不消费定义"))
    )
    assert changed.status_code == 200, changed.text
    assert current_items(setup, definition_id)["pressure"].item_version == 2


def test_actual_spec_reference_freezes_source_definition_and_checks_nested_privacy(setup):
    first_artifact = source(setup, visibility="category")
    first = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(first_artifact, visibility="category"),
            first_artifact,
        ),
    )
    assert first.status_code == 200, first.text
    source_id = UUID(first.json()["subject_id"])
    source_item = current_items(setup, source_id)["pressure"]
    other = copy(setup)
    other.product = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Product(
                id=other.product,
                tenant_id=setup.tenant,
                category_id=setup.category,
                owner_id=setup.human,
                name="Synthetic second product",
                purpose="Synthetic fixed-reference verification",
            )
        )
    other_artifact = source(other, visibility="category")
    second = post(
        other,
        command(
            other,
            "product.definition.draft",
            payload(other_artifact, visibility="category"),
            other_artifact,
        ),
    )
    assert second.status_code == 200, second.text
    target_id = UUID(second.json()["subject_id"])
    target_item = current_items(other, target_id)["pressure"]
    change = upsert(target_item, reason="固定引用另一个型号定义")
    change["source_refs"] = [{"type": "definition", "id": str(source_id), "version": 1}]
    saved = post(other, patch(other, target_id, change))
    assert saved.status_code == 200, saved.text
    denied = post(setup, patch(setup, source_id, upsert(source_item, reason="拒绝漂移来源")))
    assert denied.status_code == 409 and denied.json()["detail"]["reason"] == "definition_consumed"

    # A private next revision must not become a shared target's nested source.
    child = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(
                first_artifact,
                parent_definition_id=str(source_id),
                expected_parent_revision=1,
            ),
            first_artifact,
        ),
    )
    assert child.status_code == 200, child.text
    current = current_items(other, target_id)["pressure"]
    private_change = upsert(current, reason="拒绝扩大私有来源可见性")
    private_change["source_refs"] = [
        {
            "type": "definition",
            "id": child.json()["subject_id"],
            "version": 2,
        }
    ]
    denied = post(other, patch(other, target_id, private_change))
    assert denied.status_code == 403, denied.text
    assert current_items(other, target_id)["pressure"].id == current.id
