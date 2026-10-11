"""Actual model consumers may use their category's pre-project evidence."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_trusted_source_work import claim_cmd, command, post

from pdos_next.database import tenant_session
from pdos_next.models import Artifact, Category, Claim, Outbox, Product, Receipt
from pdos_next.service import digest


def test_category_source_model_consumer_and_foreign_scope_rejection(setup):
    registered = post(
        setup,
        {
            **command(
                setup,
                "evidence.artifact.register",
                {
                    "title": "Synthetic category research",
                    "source_label": "pre-project",
                    "content": "\nSynthetic data only\nPressure: 150 PSI\n",
                    "visibility": "category",
                },
            ),
            "product_id": None,
        },
    )
    assert registered.status_code == 200, registered.text
    artifact = registered.json()["subject_id"]
    with Session(setup.admin) as s:
        actual = s.get(Artifact, UUID(artifact))
        assert actual.product_id is None and actual.category_id == setup.category
    adopted = post(setup, claim_cmd(setup, artifact, visibility="category"))
    assert adopted.status_code == 200, adopted.text

    other_product, other_category, foreign_model, foreign_category = (uuid4() for _ in range(4))
    with Session(setup.admin) as s, s.begin():
        s.add(
            Category(
                id=other_category,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                name="Other synthetic category",
                purpose="scope isolation",
            )
        )
        s.flush()
        s.add(
            Product(
                id=other_product,
                tenant_id=setup.tenant,
                category_id=setup.category,
                owner_id=setup.human,
                name="Other synthetic model",
                purpose="scope isolation",
            )
        )
        s.flush()
        for identity, category, product in (
            (foreign_model, setup.category, other_product),
            (foreign_category, other_category, None),
        ):
            content = "\nSynthetic data only\nPressure: 150 PSI\n"
            s.add(
                Artifact(
                    id=identity,
                    tenant_id=setup.tenant,
                    category_id=category,
                    product_id=product,
                    owner_id=setup.human,
                    visibility="category",
                    title="Foreign synthetic scope",
                    source_label="scope fixture",
                    content=content,
                    content_hash=digest(content),
                )
            )
    for identity in (foreign_model, foreign_category):
        rejected = post(setup, claim_cmd(setup, str(identity), visibility="category"))
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["code"] == "SOURCE_UNAVAILABLE"
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            with pytest.raises(IntegrityError) as error:
                session.execute(
                    insert(Claim).values(
                        id=uuid4(),
                        tenant_id=setup.tenant,
                        category_id=setup.category,
                        product_id=setup.product,
                        artifact_id=identity,
                        source_revision=1,
                        line=3,
                        quote="Pressure: 150 PSI",
                        statement="Foreign scope attempt",
                        nature="extracted",
                        availability="known",
                        visibility="category",
                        human_owner_id=setup.human,
                        writer_id=setup.human,
                    )
                )
            assert error.value.orig.sqlstate == "23514"
            session.rollback()


def test_member_category_evidence_maintains_only_derived_clock_and_rolls_back(setup):
    value = {
        **command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Member synthetic category research",
                "source_label": "pre-project",
                "content": "Synthetic member evidence",
                "visibility": "category",
            },
        ),
        "product_id": None,
    }
    headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    path = f"/v1/categories/{setup.category}/commands"
    with Session(setup.admin) as session:
        row = session.get(Category, setup.category)
        old = row.lifecycle_epoch
        name, purpose, owner = row.name, row.purpose, row.owner_id
    response = setup.client.post(path, headers=headers, json=value)
    assert response.status_code == 200, response.text
    with Session(setup.admin) as session:
        row = session.get(Category, setup.category)
        assert row.lifecycle_epoch > old
        assert (row.name, row.purpose, row.owner_id) == (name, purpose, owner)
        committed_epoch = row.lifecycle_epoch

    def fail(*_):
        raise RuntimeError("category member outbox failure")

    value = {
        **value,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "payload": {**value["payload"], "title": "Rolled back member evidence"},
    }
    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="member outbox failure"):
            setup.client.post(path, headers=headers, json=value)
    finally:
        event.remove(Outbox, "before_insert", fail)
    with Session(setup.admin) as session:
        assert session.get(Category, setup.category).lifecycle_epoch == committed_epoch
        assert (
            session.scalar(
                select(Receipt.id).where(Receipt.command_id == UUID(value["command_id"]))
            )
            is None
        )
