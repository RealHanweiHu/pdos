"""Actual G0 variant continuation and native derivation in separate lineages.

Only the already-published, empty historic parent uses the labelled owner
fixture. Both variants, G0 approval and the continuation use public commands.
This does not grant real publication or model qualification.
"""
# ruff: noqa: F811 -- pytest injects the explicitly imported fixture.

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.domain.products.models import DefinitionRevision
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_derivation_transactions import derivative_payload, synthetic_parent
from tests.preproject.test_g0 import create, decide_request, save, submit
from tests.preproject.test_g0 import work as work
from tests.products.test_definition_inherit_pg import inherit
from tests.products.test_definition_item_commands_pg import current_items, patch, upsert
from tests.products.test_definition_transactions import post
from tests.products.test_variants_transactions import derive, source


def test_native_derivation_uses_latest_parent_in_its_actual_variant_lineage(work):
    artifact_id = source(work)
    historical = synthetic_parent(work, spec_values=[])
    response = work.client.get(
        f"/v1/categories/{work.category}/products/{work.product}/definitions",
        headers=work.headers,
    )
    assert response.status_code == 200, response.text
    parent = next(row for row in response.json()["items"] if row["id"] == str(historical.id))
    native, _, _ = derive(work, parent, artifact_id)
    proposal_id, _ = create(work, derivative_payload(work, historical, "new_variant"))
    submit(work, proposal_id)
    decision, _ = save(work, decide_request(work, proposal_id), actor=work.peer)
    fixed_id = UUID(decision["result"]["definition_id"])
    # The ordinary application role cannot fabricate even an empty continuation
    # with copied header metadata but no actual creation receipt.
    with pytest.raises(DBAPIError) as forged:
        with human_session(work) as session:
            fixed = session.get(DefinitionRevision, fixed_id)
            session.add(DefinitionRevision(
                id=uuid4(), tenant_id=work.tenant, category_id=work.category,
                product_id=work.product, owner_id=work.human, revision=2,
                variant_id=fixed.variant_id, parent_definition_id=fixed.id,
                status="draft", sealed=False, change_reason="Forged continuation without receipt",
                **{name: getattr(fixed, name) for name in (
                    "title", "purpose", "visibility", "use_cases", "requirements",
                    "constraints", "unknowns", "exclusions",
                )},
            ))
    assert forged.value.orig.sqlstate == "23514"
    continued = post(work, inherit(work, fixed_id))
    assert continued.status_code == 200, continued.text
    with Session(work.admin) as session:
        fixed = session.get(DefinitionRevision, fixed_id)
        child = session.get(DefinitionRevision, UUID(continued.json()["subject_id"]))
        assert fixed.sealed and fixed.g0_decision_id is not None
        assert child.variant_id == fixed.variant_id and child.parent_definition_id == fixed.id
        assert child.revision == 2 and child.status == "draft" and not child.sealed
        assert child.g0_decision_id is child.publication_receipt_id is None
        assert child.source_proposal_id is child.source_submission_id is None
    rows = current_items(work, child.id)
    original = rows['display']
    op = upsert(original, key='display', parameter='Synthetic inherited display',
                value_type='boolean', text_value='false', availability='known',
                item_status='confirmed', reason='本人的独立续版合成目标')
    op['source_refs'] = [{'type':'human','id':str(work.human),'version':1,
                         'statement':'本人的合成目标，不代表测量结果'}]
    edited = post(work, patch(work, child.id, op))
    assert edited.status_code == 200, edited.text
    assert current_items(work, fixed_id)['display'].item_version == 1
    assert current_items(work, child.id)['display'].item_version == 2
    # A further continuation remains a draft after an ordinary human revision.
    next_draft = post(work, inherit(work, child.id, revision=2))
    assert next_draft.status_code == 200, next_draft.text
    with Session(work.admin) as session:
        third = session.get(DefinitionRevision, UUID(next_draft.json()["subject_id"]))
        assert third.revision == 3 and third.variant_id == child.variant_id
        assert third.parent_definition_id == child.id and not third.sealed
        assert third.g0_decision_id is third.publication_receipt_id is None
    second, _, receipt = derive(
        work, parent, artifact_id, name="Synthetic second regional configuration"
    )
    assert second["id"] != native["id"]
    assert receipt["subject_id"] == second["revisions"][0]["id"]
    assert second["revisions"][0]["parent_definition_id"] == parent["id"]
    # An actual independent continuation must not lose its accepted guard on DOWN.
    from migrations.schema_s0_0756 import DOWNGRADE_SQL

    definition_sql = "SELECT pg_get_functiondef('m3_derivation_scope_atom()'::regprocedure)"
    with Session(work.admin) as session:
        guard = session.scalar(text(definition_sql))
    with pytest.raises(DBAPIError) as downgrade:
        with Session(work.admin) as session, session.begin():
            session.execute(text("SET LOCAL ROLE pdos_next_owner"))
            for statement in DOWNGRADE_SQL:
                session.connection().exec_driver_sql(
                    statement, execution_options={"no_parameters": True}
                )
    assert downgrade.value.orig.sqlstate == "23514"
    with Session(work.admin) as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "s0_0756"
        assert session.scalar(text(definition_sql)) == guard
