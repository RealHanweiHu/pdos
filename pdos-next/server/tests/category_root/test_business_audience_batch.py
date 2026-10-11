"""Exact batch identities and full source audiences through the application role."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.domain.configurations.models import BomRevision
from pdos_next.models import Artifact, ObjectAudience
from pdos_next.service import digest


def scoped(setup, actor):
    return tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=actor,
        requester_id=actor,
        category_id=setup.category,
        read_snapshot=True,
    )


def visible(session, setup, dependencies):
    return session.scalar(
        text(
            "SELECT business_audience_summary_visible(:tenant,:category,:product,"
            "CAST(:dependencies AS jsonb))"
        ),
        {
            "tenant": setup.tenant,
            "category": setup.category,
            "product": setup.product,
            "dependencies": json.dumps(dependencies),
        },
    )


def audience(setup, kind, identity, owner, principal):
    return ObjectAudience(
        tenant_id=setup.tenant,
        category_id=setup.category,
        object_type=kind,
        subject_id=identity,
        owner_id=owner,
        principal_id=principal,
    )


@pytest.fixture
def batch(setup):
    source_ids = [uuid4() for _ in range(21)]
    bom_ids = [uuid4(), uuid4()]
    reads = [
        {"artifact_id": str(identity), "expected_revision": 1}
        for identity in source_ids
    ]
    with Session(setup.admin) as s, s.begin():
        for index, identity in enumerate(source_ids):
            s.add(
                Artifact(
                    id=identity,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=setup.product,
                    owner_id=setup.peer if index == 20 else setup.human,
                    title=f"Synthetic batch source {index}",
                    source_label="Synthetic only",
                    content="Synthetic batch evidence",
                    content_hash=digest("Synthetic batch evidence"),
                    visibility="private" if index == 20 else "category",
                )
            )
        s.flush()
        s.add(audience(setup, "artifact_versions", source_ids[-1], setup.peer, setup.human))
        s.flush()
        for identity in bom_ids:
            s.add(
                BomRevision(
                    id=identity,
                    series_id=identity,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=setup.product,
                    owner_id=setup.human,
                    name="Synthetic batch BOM",
                    visibility="private",
                    revision=1,
                    reason="Synthetic full source audience check",
                    sources=reads,
                    required_source_read_set=reads,
                )
            )
    dependencies = [
        {"type": "bom_revisions", "id": str(identity), "product_id": str(setup.product)}
        for identity in bom_ids
    ]
    return bom_ids, source_ids[-1], dependencies


def test_complete_batch_sources_and_private_audiences_survive_no_truncation(setup, batch):
    identities, last_source, dependencies = batch
    with scoped(setup, setup.human) as s:
        assert visible(s, setup, dependencies + dependencies) is True
        assert set(s.scalars(select(BomRevision.id).where(BomRevision.id.in_(identities)))) == set(
            identities
        )
    with scoped(setup, setup.peer) as s:
        assert visible(s, setup, dependencies) is False
    with Session(setup.admin) as s, s.begin():
        s.add_all(
            audience(setup, "bom_revisions", identity, setup.human, setup.peer)
            for identity in identities
        )
    with scoped(setup, setup.peer) as s:
        assert visible(s, setup, dependencies) is True
    # The only inaccessible source is beyond the previous arbitrary 20-item cap.
    with Session(setup.admin) as s, s.begin():
        s.execute(
            delete(ObjectAudience).where(
                ObjectAudience.subject_id == last_source,
                ObjectAudience.principal_id == setup.human,
            )
        )
    with scoped(setup, setup.human) as s:
        assert visible(s, setup, dependencies + dependencies) is False
        assert not list(s.scalars(select(BomRevision.id).where(BomRevision.id.in_(identities))))
    # A different current reader still owns that source; no saved ACL is reused.
    with scoped(setup, setup.peer) as s:
        assert visible(s, setup, dependencies) is True


def test_batch_rejects_missing_or_forged_dependencies_before_scope_widening(setup, batch):
    _, _, dependencies = batch
    original = dependencies[0]
    invalid_sets = [
        {},
        [None],
        ["not an identity"],
        [{key: value for key, value in original.items() if key != "type"}],
        [{**original, "extra": True}],
        [{**original, "type": None}],
        [{**original, "type": "artifact_versions"}],
        [{**original, "type": "bom_revisions;SELECT 1"}],
        [{**original, "id": "not a UUID"}],
        [{**original, "id": str(uuid4())}],
        [{**original, "product_id": None}],
        [{**original, "product_id": []}],
        [{**original, "product_id": "not a UUID"}],
        [original, {**original, "product_id": str(uuid4())}],
    ]
    with scoped(setup, setup.human) as s:
        assert visible(s, setup, dependencies) is True
        for dependencies_to_reject in invalid_sets:
            assert visible(s, setup, dependencies_to_reject) is False
