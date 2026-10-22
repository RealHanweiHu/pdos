"""The new inherited-source policy exposes only a scoped boolean, never a body."""

import json
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionSource
from pdos_next.models import Artifact
from tests.products.test_definition_inherit_pg import inherit
from tests.products.test_definition_item_commands_pg import draft
from tests.products.test_definition_transactions import post


def copied(setup):
    parent_id, _ = draft(setup)
    saved = post(setup, inherit(setup, parent_id))
    assert saved.status_code == 200, saved.text
    with Session(setup.admin) as session:
        source = session.scalar(
            select(DefinitionSource).where(
                DefinitionSource.definition_id == UUID(saved.json()["subject_id"]),
            )
        )
        return {
            "t": setup.tenant,
            "c": setup.category,
            "p": setup.product,
            "d": source.definition_id,
            "sid": source.artifact_id,
            "ver": source.source_revision,
            "line": source.line,
            "quote": source.quote,
            "keys": json.dumps(source.spec_keys),
        }


QUERY = text(
    "SELECT m3_definition_inherited_source_insert_visible("
    ":t,:c,:p,:d,:sid,:ver,:line,:quote,CAST(:keys AS jsonb))"
)


@pytest.mark.parametrize("changed", ["quote", "keys", "ver", "actor", "withdrawn"])
def test_inherited_source_boolean_requires_exact_live_copy_and_owner(setup, changed):
    values = copied(setup)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        assert session.scalar(QUERY, values) is True
    actor = setup.human
    if changed == "quote":
        values["quote"] += " altered"
    elif changed == "keys":
        values["keys"] = '["forged"]'
    elif changed == "ver":
        values["ver"] += 1
    elif changed == "actor":
        actor = setup.peer
    else:
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, values["sid"]).status = "withdrawn"
    with tenant_session(
        setup.engine, setup.tenant, actor_id=actor, category_id=setup.category
    ) as session:
        assert session.scalar(QUERY, values) is False


def test_agent_cannot_execute_inherited_source_insert_policy_helper(setup):
    values = copied(setup)
    with (
        pytest.raises(DBAPIError) as rejected,
        tenant_session(
            setup.admin,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        session.execute(text("SET LOCAL ROLE pdos_agent"))
        session.scalar(QUERY, values)
    assert rejected.value.orig.sqlstate == "42501"
