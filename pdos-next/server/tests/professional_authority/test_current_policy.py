"""Actual app-role Current reads retain the exact Fact's live RLS audience.

The main session runs these on its verified isolated PostgreSQL target. These
raw reads establish visibility only; they never establish professional eligibility.
"""

# ruff: noqa: F401,F811 -- register the existing real credential fixture
import json
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import cmd, post

from pdos_next.database import tenant_session
from pdos_next.domain.projects.models import Project
from pdos_next.models import Grant, ObjectAudience, Product, now
from professional_authority.test_transactions import (
    SOURCE_TEXT,
    authority_work,
    fact_payload,
    imported,
)


def _parameters(setup, work, identity):
    return {
        "tenant": setup.tenant,
        "category": setup.category,
        "product": setup.product,
        "project": UUID(work["project"]),
        "subject": setup.human,
        "fact": identity,
    }


def _visible_rows(setup, work, identity, reader):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=reader,
        requester_id=reader,
        category_id=setup.category,
        read_snapshot=True,
    ) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        parameters = _parameters(setup, work, identity)
        facts = list(
            session.scalars(
                text(
                    "SELECT id FROM professional_authority_facts WHERE tenant_id=:tenant "
                    "AND category_id=:category AND product_id=:product AND project_id=:project "
                    "AND subject_id=:subject AND id=:fact"
                ),
                parameters,
            )
        )
        currents = list(
            session.scalars(
                text(
                    "SELECT fact_id FROM professional_authority_current WHERE tenant_id=:tenant "
                    "AND category_id=:category AND product_id=:product AND project_id=:project "
                    "AND subject_id=:subject AND fact_id=:fact"
                ),
                parameters,
            )
        )
        return facts, currents


def _grant(setup, kind, identity):
    with Session(setup.admin) as session, session.begin():
        session.add(
            ObjectAudience(
                tenant_id=setup.tenant,
                category_id=setup.category,
                object_type=kind,
                subject_id=identity,
                owner_id=setup.human,
                principal_id=setup.peer,
            )
        )


def _revoke(setup, *kinds):
    """Start an invisibility check from no audience at all for the reader.

    G0 materialisation and the authority import now add product/project audience
    rows for the named reviewer (setup.peer), so turning an object private is no
    longer enough on its own; the reader keeps its own audience row.
    """
    with Session(setup.admin) as session, session.begin():
        session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.category_id == setup.category,
                ObjectAudience.principal_id == setup.peer,
                ObjectAudience.object_type.in_(kinds),
            )
        )


@pytest.mark.parametrize("revoked", ["source", "fact", "project"])
def test_current_and_fact_sql_share_live_audience_revocation(setup, authority_work, revoked):
    response = post(
        setup,
        cmd(
            setup,
            "evidence.artifact.register",
            {
                "title": "Private synthetic Current-policy credential",
                "content": SOURCE_TEXT,
                "source_label": "Synthetic exact private credential",
                "visibility": "private",
            },
        ),
    )
    assert response.status_code == 200, response.text
    source = UUID(response.json()["subject_id"])
    record = imported(
        setup,
        authority_work,
        fact_payload(
            setup,
            authority_work,
            sources=[
                {
                    "artifact_id": str(source),
                    "expected_revision": 1,
                    "line": 1,
                    "quote": SOURCE_TEXT,
                }
            ],
        ),
    )
    identity = UUID(record["subject_id"])
    project = UUID(authority_work["project"])
    # Project audience is mutable; Fact and Artifact originals remain immutable.
    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Project)
            .where(Project.tenant_id == setup.tenant, Project.id == project)
            .values(visibility="private")
        )
        actual = session.execute(
            text(
                "SELECT visibility,audience_dependencies FROM professional_authority_facts "
                "WHERE tenant_id=:tenant AND id=:fact"
            ),
            {"tenant": setup.tenant, "fact": identity},
        ).one()
        assert actual.visibility == "private"
        assert {"type": "projects", "id": str(project), "product_id": str(setup.product)} in (
            actual.audience_dependencies
        )
    targets = {
        "source": ("artifact_versions", source),
        "fact": ("professional_authority_facts", identity),
        "project": ("projects", project),
    }
    _revoke(setup, "products", "projects", "artifact_versions", "professional_authority_facts")
    assert _visible_rows(setup, authority_work, identity, setup.peer) == ([], [])
    for kind, target in targets.values():
        _grant(setup, kind, target)
    expected = ([identity], [identity])
    assert _visible_rows(setup, authority_work, identity, setup.peer) == expected
    kind, target = targets[revoked]
    with Session(setup.admin) as session, session.begin():
        removed = session.execute(
            delete(ObjectAudience)
            .where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.category_id == setup.category,
                ObjectAudience.object_type == kind,
                ObjectAudience.subject_id == target,
                ObjectAudience.owner_id == setup.human,
                ObjectAudience.principal_id == setup.peer,
            )
            .returning(ObjectAudience.id)
        ).all()
        assert len(removed) == 1
    assert _visible_rows(setup, authority_work, identity, setup.peer) == ([], [])
    assert _visible_rows(setup, authority_work, identity, setup.human) == expected
    _grant(setup, kind, target)
    assert _visible_rows(setup, authority_work, identity, setup.peer) == expected


def _summary(setup, work, identity):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as session:
        return session.execute(
            text(
                "SELECT summary FROM professional_authority_current WHERE tenant_id=:tenant "
                "AND category_id=:category AND product_id=:product AND project_id=:project "
                "AND subject_id=:subject AND fact_id=:fact"
            ),
            _parameters(setup, work, identity),
        ).scalar_one()


def test_current_summary_injection_cannot_bypass_exact_fact_successor(setup, authority_work):
    record = imported(setup, authority_work, fact_payload(setup, authority_work))
    identity = UUID(record["subject_id"])
    original = _summary(setup, authority_work, identity)
    assert original["id"] == str(identity) and original["kind"] == "duty"
    forged = {
        **original,
        "subject_id": str(setup.peer),
        "role": "manufacturing",
        "visibility": "category",
        "fact_sha256": "0" * 64,
        "required_source_read_set": [],
    }
    with pytest.raises(DBAPIError, match="Authority pointer and epoch must advance"):
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            session.execute(
                text(
                    "UPDATE professional_authority_current SET summary=CAST(:forged AS jsonb) "
                    "WHERE tenant_id=:tenant AND category_id=:category AND product_id=:product "
                    "AND project_id=:project AND subject_id=:subject AND fact_id=:fact"
                ),
                {**_parameters(setup, authority_work, identity), "forged": json.dumps(forged)},
            )
    assert _summary(setup, authority_work, identity) == original
    assert _visible_rows(setup, authority_work, identity, setup.human) == ([identity], [identity])


@pytest.mark.parametrize("root_guard", ["category", "product"])
def test_current_and_fact_sql_keep_category_and_exact_product_audience(
    setup, authority_work, root_guard
):
    record = imported(setup, authority_work, fact_payload(setup, authority_work))
    identity = UUID(record["subject_id"])
    expected = ([identity], [identity])
    assert _visible_rows(setup, authority_work, identity, setup.peer) == expected
    if root_guard == "category":
        with Session(setup.admin) as session, session.begin():
            changed = session.execute(
                update(Grant)
                .where(
                    Grant.tenant_id == setup.tenant,
                    Grant.category_id == setup.category,
                    Grant.principal_id == setup.peer,
                )
                .values(expires_at=now() - timedelta(seconds=1))
                .returning(Grant.id)
            ).all()
            assert len(changed) == 1
        assert _visible_rows(setup, authority_work, identity, setup.peer) == ([], [])
        assert _visible_rows(setup, authority_work, identity, setup.human) == expected
        with Session(setup.admin) as session, session.begin():
            session.execute(
                update(Grant)
                .where(
                    Grant.tenant_id == setup.tenant,
                    Grant.category_id == setup.category,
                    Grant.principal_id == setup.peer,
                )
                .values(expires_at=now() + timedelta(hours=1))
            )
    else:
        with Session(setup.admin) as session, session.begin():
            session.execute(
                update(Product)
                .where(
                    Product.tenant_id == setup.tenant,
                    Product.category_id == setup.category,
                    Product.id == setup.product,
                )
                .values(visibility="private")
            )
        _revoke(setup, "products")
        assert _visible_rows(setup, authority_work, identity, setup.peer) == ([], [])
        _grant(setup, "products", setup.product)
        assert _visible_rows(setup, authority_work, identity, setup.peer) == expected
        with Session(setup.admin) as session, session.begin():
            removed = session.execute(
                delete(ObjectAudience)
                .where(
                    ObjectAudience.tenant_id == setup.tenant,
                    ObjectAudience.category_id == setup.category,
                    ObjectAudience.object_type == "products",
                    ObjectAudience.subject_id == setup.product,
                    ObjectAudience.owner_id == setup.human,
                    ObjectAudience.principal_id == setup.peer,
                )
                .returning(ObjectAudience.id)
            ).all()
            assert len(removed) == 1
        assert _visible_rows(setup, authority_work, identity, setup.peer) == ([], [])
        assert _visible_rows(setup, authority_work, identity, setup.human) == expected
        _grant(setup, "products", setup.product)
    assert _visible_rows(setup, authority_work, identity, setup.peer) == expected
