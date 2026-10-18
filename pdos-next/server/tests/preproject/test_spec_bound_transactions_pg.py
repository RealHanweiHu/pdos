"""Actual seed identity, source Claim, G0 and lossless draft continuation."""
# ruff: noqa: F811 -- pytest injects the explicitly imported isolated PG fixture

from copy import copy
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from migrations.schema_s0_0757 import DOWNGRADE_SQL
from pdos_next.database import tenant_session
from pdos_next.domain.preproject.category_models import ParameterVersion
from pdos_next.domain.products.definitions import definition_view
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSpecRow
from pdos_next.domain.products.variants import compare_snapshots, snapshot_from_definition
from pdos_next.models import Claim
from pdos_next.schemas.products.derivation import DerivationRequest
from pdos_next.service import Context
from tests.preproject.test_evidence_commands_pg import artifact, claim_body, evidence_request
from tests.preproject.test_g0 import create, decide_request, payload, post, request, save, submit
from tests.preproject.test_g0 import work as work
from tests.preproject.test_material_commands_pg import parameter
from tests.preproject.test_seed_import import preview
from tests.products.test_definition_inherit_pg import copied_values, inherit
from tests.products.test_definition_item_commands_pg import (
    confirmed,
    current_items,
    draft,
    patch,
    upsert,
)
from tests.products.test_definition_transactions import command
from tests.products.test_definition_transactions import post as product_post

QUOTE = "噪声不得超过75 dB(A)，启动后前三秒除外。"
EXCEPTION = {"text": "启动后前三秒除外", "applies_to": "启动后前三秒"}


def assert_upper_bound(row):
    assert row.value_type == "number" and row.availability == "known"
    assert row.value is None and row.lower is None and row.upper == Decimal(75)
    assert row.unit == "dB(A)" and row.exceptions == [EXCEPTION]
    assert row.modality == "must" and row.test_conditions == []
    assert row.condition_note is None and row.method is None and row.acceptance_criterion is None


def assert_downgrade_blocked(work):
    with work.admin.connect() as connection:
        before = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid='definition_specs'::regclass "
                "AND conname='m3_spec_known_shape'"
            )
        )
        # A refused downgrade must leave the stamp alone, whatever revision this
        # environment is on; pinning one revision only ages.
        stamp = connection.scalar(text("SELECT version_num FROM alembic_version"))
    with pytest.raises(DBAPIError) as caught:
        with work.admin.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE pdos_next_owner")
            for statement in DOWNGRADE_SQL:
                connection.exec_driver_sql(statement)
    assert caught.value.orig.sqlstate == "23514"
    assert "Single-bound specification history" in str(caught.value.orig)
    with work.admin.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == stamp
        assert (
            connection.scalar(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='definition_specs'::regclass "
                    "AND conname='m3_spec_known_shape'"
                )
            )
            == before
        )


def test_actual_noise_seed_claim_g0_inherit_and_fixed_snapshot_keep_single_upper(work):
    seed = next(
        row for row in preview("bicycle-pump").categories[0].parameters if row.key == "noise_level"
    )
    assert seed.value_type == "number" and seed.unit == "dB(A)"
    published, _ = save(
        work,
        request(
            work,
            "category.parameter.publish",
            parameter(
                key=seed.key,
                name=seed.name,
                value_type=seed.value_type,
                unit=seed.unit,
                direction=seed.direction,
                standard_condition=seed.standard_condition,
                method=seed.method,
                acceptance_criterion=seed.acceptance_criterion,
            ),
        ),
    )
    identity = UUID(published["result"]["parameter_id"])
    source = artifact(work, body=QUOTE)
    claim_input = claim_body(source, quote=QUOTE)
    claim_input["content"] = {
        "parameter_id": str(identity),
        "parameter_version": 1,
        "upper": "75",
        "unit": seed.unit,
        "modality": "must",
        "exceptions": [EXCEPTION],
        "text": QUOTE,
    }
    claim_response = post(work, evidence_request(work, "evidence.claim.record", claim_input))
    assert claim_response.status_code == 200, claim_response.text
    claim_id = UUID(claim_response.json()["subject_id"])
    with Session(work.admin) as session:
        saved_claim = session.get(Claim, claim_id)
        assert saved_claim.content["upper"] == "75" and saved_claim.content.get("lower") is None
        assert saved_claim.content.get("value") is None and saved_claim.content["exceptions"] == [
            EXCEPTION
        ]
        actual_parameter = session.scalar(
            select(ParameterVersion).where(
                ParameterVersion.tenant_id == work.tenant,
                ParameterVersion.parameter_id == identity,
                ParameterVersion.version == 1,
            )
        )
        assert actual_parameter.value_type == "number" and actual_parameter.unit == seed.unit
    document = payload(work)
    noise = next(
        row
        for row in document["groups"]["items"]
        if row["kind"] == "spec" and row["content"]["key"] == "noise"
    )
    noise["content"].update(
        key=seed.key,
        parameter=seed.name,
        parameter_id=str(identity),
        parameter_version=1,
        value_type=seed.value_type,
        unit=seed.unit,
        upper="75",
        availability="known",
        item_status="ai_draft",
        nature="extracted",
        modality="must",
        exceptions=[EXCEPTION],
    )
    noise["source_refs"] = [
        {"type": "artifact", "id": str(source), "version": 1, "line": 1, "quote": QUOTE},
        {"type": "claim", "id": str(claim_id), "version": 1},
    ]
    proposal_id, _ = create(work, document)
    submit(work, proposal_id)
    decision, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    target = copy(work)
    target.product = UUID(decision["result"]["product_id"])
    parent_id = UUID(decision["result"]["definition_id"])
    parent = current_items(target, parent_id)[seed.key]
    assert_upper_bound(parent)
    assert parent.parameter_id == identity and parent.parameter_version == 1
    continued = product_post(target, inherit(target, parent_id))
    assert continued.status_code == 200, continued.text
    child_id = UUID(continued.json()["subject_id"])
    child = current_items(target, child_id)[seed.key]
    assert_upper_bound(child)
    assert copied_values(child) == copied_values(parent)
    native_request = command(
        target,
        "product.variant.derive",
        {
            "name": "合成地域变体",
            "kind": "region",
            "applicability": ["合成台架"],
            "parent_definition_id": str(child_id),
            "expected_parent_revision": 2,
            "visibility": "private",
            "overrides": {},
            "reason": "核对单边约束完整派生",
            "sources": [
                {"artifact_id": str(source), "expected_revision": 1, "line": 1, "quote": QUOTE}
            ],
        },
        str(source),
    )
    native_preview = post(target, native_request, preview=True)
    assert native_preview.status_code == 422
    assert native_preview.json()["detail"]["reason"] == "m3_definition_requires_proposal"
    ctx = Context(work.tenant, work.human, work.human, category_id=work.category)
    with tenant_session(
        work.engine, work.tenant, actor_id=work.human, category_id=work.category
    ) as session:
        parent_snapshot = snapshot_from_definition(
            definition_view(session, ctx, session.get(DefinitionRevision, parent_id))
        )
        child_snapshot = snapshot_from_definition(
            definition_view(session, ctx, session.get(DefinitionRevision, child_id))
        )
    copied_noise = next(row for row in child_snapshot.content.specs if row.key == seed.key)
    assert copied_noise.value is None and copied_noise.lower is None
    assert copied_noise.upper == Decimal(75) and copied_noise.value_type == "number"
    assert copied_noise.exceptions == (EXCEPTION,)
    comparison = compare_snapshots(
        DerivationRequest(
            old_parent=parent_snapshot,
            new_parent=parent_snapshot,
            child=child_snapshot,
            pinned_parent=parent_snapshot.ref,
        ),
        allow_same_parent=True,
    )
    assert all(change.classification == "unchanged" for change in comparison.differences)
    with Session(work.admin) as session:
        assert session.get(DefinitionRevision, parent_id).sealed
        assert not session.get(DefinitionRevision, child_id).sealed
    assert_downgrade_blocked(work)


def test_removed_single_bound_history_still_blocks_destructive_downgrade(work):
    definition_id, _ = draft(work)
    row = current_items(work, definition_id)["pressure"]
    op = upsert(
        row,
        upper="0",
        availability="known",
        item_status="confirmed",
        unit="PSI",
        reason="合成上限为零",
    )
    op["source_refs"] = [
        {"type": "human", "id": str(work.human), "version": 1, "statement": "本人合成上限为零"}
    ]
    saved = product_post(work, patch(work, definition_id, op))
    assert saved.status_code == 200, saved.text
    bounded = current_items(work, definition_id)["pressure"]
    confirmed(
        work,
        patch(
            work,
            definition_id,
            {
                "op": "remove",
                "item_id": str(bounded.item_id),
                "base_version": bounded.item_version,
            },
        ),
    )
    assert current_items(work, definition_id)["pressure"].removed
    assert_downgrade_blocked(work)


@pytest.mark.parametrize("shape", [(None, None, None), ("0", None, "75"), ("0", "0", None)])
def test_app_cannot_insert_empty_or_mixed_numeric_shape(work, shape):
    definition_id, _ = draft(work)
    row = current_items(work, definition_id)["pressure"]
    columns = [column.name for column in DefinitionSpecRow.__table__.columns]
    replaced = {
        "id": ":new_id",
        "item_version": "item_version+1",
        "availability": "'known'",
        "value": ":value",
        "lower": ":lower",
        "upper": ":upper",
    }
    expressions = [replaced.get(name, f'"{name}"') for name in columns]
    sql = (
        "INSERT INTO definition_specs ("
        + ",".join(f'"{name}"' for name in columns)
        + ") SELECT "
        + ",".join(expressions)
        + " FROM definition_specs WHERE id=:old_id"
    )
    with pytest.raises(DBAPIError) as caught:
        with tenant_session(
            work.engine, work.tenant, actor_id=work.human, category_id=work.category
        ) as session:
            session.execute(
                text(sql),
                {
                    "new_id": uuid4(),
                    "old_id": row.id,
                    "value": shape[0],
                    "lower": shape[1],
                    "upper": shape[2],
                },
            )
    assert caught.value.orig.sqlstate == "23514"
    assert caught.value.orig.diag.constraint_name == "m3_spec_known_shape"
