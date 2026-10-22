"""Real app-role SQL ACL checks; these rows do not prove scanner or domain qualification."""

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.models import (
    Artifact,
    Category,
    Grant,
    ObjectAudience,
    Product,
    UploadedOriginal,
    now,
)
from pdos_next.service import digest


@dataclass(frozen=True)
class SourceIDs:
    tenant: UUID
    category: UUID
    product: UUID | None
    artifact: UUID
    original: UUID | None
    owner: UUID


def _original(identity, tenant, category, product, owner):
    content = "Synthetic SQL ACL original"
    return UploadedOriginal(
        id=identity,
        tenant_id=tenant,
        category_id=category,
        product_id=product,
        owner_id=owner,
        title="Synthetic SQL ACL original",
        filename="synthetic-acl.txt",
        source_label="SQL ACL fixture only",
        visibility="private",
        media_type="text/plain",
        byte_count=len(content.encode()),
        content_hash=digest(content),
        storage_key=f"acl-fixture/{identity.hex}/{digest(content)}",
    )


def _source(setup, product, *, original=False, visibility="private", scope=None):
    tenant, category, owner = scope or (setup.tenant, setup.category, setup.human)
    artifact_id, original_id = uuid4(), uuid4() if original else None
    with Session(setup.admin) as session, session.begin():
        if original_id is not None:
            session.add(_original(original_id, tenant, category, product, owner))
            session.flush()
        session.add(
            Artifact(
                id=artifact_id,
                tenant_id=tenant,
                category_id=category,
                product_id=product,
                original_id=original_id,
                owner_id=owner,
                title="Synthetic SQL ACL artifact",
                source_label="SQL ACL fixture only",
                content="Synthetic SQL ACL source",
                content_hash=digest("Synthetic SQL ACL source"),
                visibility=visibility,
            )
        )
    return SourceIDs(tenant, category, product, artifact_id, original_id, owner)


def _private_chain(setup):
    product = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Product(
                id=product,
                tenant_id=setup.tenant,
                category_id=setup.category,
                owner_id=setup.human,
                name="Synthetic private SQL ACL product",
                purpose="Independent product, artifact and original audiences",
                visibility="private",
            )
        )
    return _source(setup, product, original=True)


def _visible(setup, product, identities, *, actor=None, requester=None, scope=None):
    tenant, category = scope or (setup.tenant, setup.category)
    actor = actor or setup.human
    requester = requester or actor
    with tenant_session(
        setup.engine,
        tenant,
        actor_id=actor,
        requester_id=requester,
        category_id=category,
        read_snapshot=True,
    ) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        return session.scalar(
            text(
                "SELECT direct_source_set_visible(CAST(:tenant AS uuid),"
                "CAST(:category AS uuid),CAST(:product AS uuid),CAST(:refs AS jsonb))"
            ),
            {
                "tenant": tenant,
                "category": category,
                "product": product,
                "refs": json.dumps(
                    [
                        {"artifact_id": str(identity), "expected_revision": 1}
                        for identity in identities
                    ]
                ),
            },
        )


def _audience(source, kind, identity, principal):
    return {
        "tenant_id": source.tenant,
        "category_id": source.category,
        "object_type": kind,
        "subject_id": identity,
        "owner_id": source.owner,
        "principal_id": principal,
    }


def _grant_audience(setup, audience):
    with Session(setup.admin) as session, session.begin():
        session.add(ObjectAudience(**audience))


def _remove_audience(setup, audience):
    with Session(setup.admin) as session, session.begin():
        removed = session.execute(
            delete(ObjectAudience)
            .where(*(getattr(ObjectAudience, key) == value for key, value in audience.items()))
            .returning(ObjectAudience.id)
        ).all()
        assert len(removed) == 1


def _chain_audiences(source, principal):
    targets = [("artifact_versions", source.artifact)]
    if source.product is not None:
        targets.append(("products", source.product))
    if source.original is not None:
        targets.append(("uploaded_originals", source.original))
    return [_audience(source, kind, identity, principal) for kind, identity in targets]


def _category(setup, tenant, owner):
    category = uuid4()
    with Session(setup.admin) as session, session.begin():
        session.add(
            Category(
                id=category,
                tenant_id=tenant,
                owner_id=owner,
                name="Synthetic independent SQL ACL category",
                purpose="Exact tenant and category source joins",
            )
        )
        session.flush()
        session.add(
            Grant(
                tenant_id=tenant,
                category_id=category,
                principal_id=owner,
                can_write=False,
                expires_at=None,
            )
        )
    return category


@pytest.mark.parametrize("category_consumer", [False, True])
def test_private_product_artifact_and_original_audiences_are_independent_and_live(
    setup, category_consumer,
):
    source = _private_chain(setup)
    target = None if category_consumer else source.product
    refs = [source.artifact]
    assert _visible(setup, target, refs) is True
    assert _visible(setup, target, refs, actor=setup.peer) is False
    audiences = _chain_audiences(source, setup.peer)
    for audience in audiences:
        _grant_audience(setup, audience)
    assert _visible(setup, target, refs, actor=setup.peer) is True
    for audience in audiences:
        _remove_audience(setup, audience)
        assert _visible(setup, target, refs, actor=setup.peer) is False, audience[
            "object_type"
        ]
        assert _visible(setup, target, refs) is True
        _grant_audience(setup, audience)
        assert _visible(setup, target, refs, actor=setup.peer) is True


def test_nullable_scope_exact_joins_and_complete_reference_set(setup):
    native = _source(setup, None, visibility="category")
    category_source = _source(setup, None, original=True)
    assert _visible(setup, None, [native.artifact], actor=setup.peer) is True
    assert _visible(setup, None, [category_source.artifact]) is True
    assert _visible(setup, None, [category_source.artifact], actor=setup.peer) is False
    for audience in _chain_audiences(category_source, setup.peer):
        _grant_audience(setup, audience)
    assert (
        _visible(setup, None, [native.artifact, category_source.artifact], actor=setup.peer) is True
    )
    for artifact in (native.artifact, category_source.artifact):
        # Category-native sources are valid for an authorized product consumer.
        assert _visible(setup, setup.product, [artifact]) is True

    source = _private_chain(setup)
    for audience in _chain_audiences(source, setup.peer):
        _grant_audience(setup, audience)
    assert _visible(setup, None, [source.artifact]) is True
    assert _visible(setup, setup.product, [source.artifact]) is False
    shared = [_source(setup, source.product, visibility="category").artifact for _ in range(20)]
    refs = [*shared, source.artifact]
    assert _visible(setup, source.product, refs + refs, actor=setup.peer) is True
    assert _visible(setup, source.product, []) is True
    for missing_refs in ([*refs, uuid4()], [uuid4(), *refs]):
        assert _visible(setup, source.product, missing_refs, actor=setup.peer) is False
    _remove_audience(setup, _audience(source, "artifact_versions", source.artifact, setup.peer))
    assert _visible(setup, source.product, refs, actor=setup.peer) is False
    assert _visible(setup, source.product, [source.artifact, *shared], actor=setup.peer) is False
    assert _visible(setup, source.product, refs) is True

    for tenant, owner in ((setup.tenant, setup.human), (setup.other_tenant, setup.other_human)):
        category = _category(setup, tenant, owner)
        foreign = _source(setup, None, visibility="category", scope=(tenant, category, owner))
        assert _visible(setup, None, [foreign.artifact]) is False
        assert (
            _visible(setup, None, [foreign.artifact], actor=owner, scope=(tenant, category)) is True
        )
        assert (
            _visible(setup, None, [native.artifact], actor=owner, scope=(tenant, category)) is False
        )


def test_audience_requires_each_exact_tuple_field_or_database_rejects_forgery(setup):
    source = _source(setup, None)
    other = _source(setup, None)
    exact = _audience(source, "artifact_versions", source.artifact, setup.peer)
    assert _visible(setup, None, [source.artifact], actor=setup.peer) is False
    _grant_audience(setup, exact)
    assert _visible(setup, None, [source.artifact], actor=setup.peer) is True
    _remove_audience(setup, exact)

    # An independently valid original with the same UUID isolates object_type.
    # No triggers or constraints are bypassed to manufacture an invalid audience.
    with Session(setup.admin) as session, session.begin():
        session.add(_original(source.artifact, source.tenant, source.category, None, source.owner))
    wrong_category = _category(setup, setup.tenant, setup.human)
    changes = (
        ("tenant_id", setup.other_tenant, True),
        ("category_id", wrong_category, True),
        ("object_type", "uploaded_originals", False),
        ("subject_id", other.artifact, False),
        ("owner_id", setup.peer, True),
        ("principal_id", setup.agent, False),
    )
    for key, value, rejected in changes:
        audience = {**exact, key: value}
        if rejected:
            with pytest.raises(IntegrityError) as failure:
                _grant_audience(setup, audience)
            assert failure.value.orig.sqlstate == "23514", key
        else:
            _grant_audience(setup, audience)
        assert _visible(setup, None, [source.artifact], actor=setup.peer) is False, key
        assert _visible(setup, None, [source.artifact]) is True
        if not rejected:
            _remove_audience(setup, audience)
    _grant_audience(setup, exact)
    assert _visible(setup, None, [source.artifact], actor=setup.peer) is True


def test_distinct_actor_requester_require_both_live_grants_and_requester_audience(setup):
    source = _private_chain(setup)
    with Session(setup.admin) as session, session.begin():
        changed = session.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id.in_([setup.human, setup.peer]),
            )
            .values(expires_at=None, can_write=False)
            .returning(Grant.id)
        ).all()
        assert len(changed) == 2
    refs = [source.artifact]
    assert _visible(setup, source.product, refs, actor=setup.peer, requester=setup.human) is True
    assert _visible(setup, source.product, refs, actor=setup.human, requester=setup.peer) is False
    for audience in _chain_audiences(source, setup.peer):
        _grant_audience(setup, audience)
    assert _visible(setup, source.product, refs, actor=setup.human, requester=setup.peer) is True
    for principal in (setup.human, setup.peer):
        for expiry in (now() - timedelta(seconds=1), None):
            with Session(setup.admin) as session, session.begin():
                changed = session.execute(
                    update(Grant)
                    .where(
                        Grant.tenant_id == setup.tenant,
                        Grant.category_id == setup.category,
                        Grant.principal_id == principal,
                    )
                    .values(expires_at=expiry)
                    .returning(Grant.id)
                ).all()
                assert len(changed) == 1
            expected = expiry is None
            assert (
                _visible(setup, source.product, refs, actor=setup.human, requester=setup.peer)
                is expected
            )
            assert (
                _visible(setup, source.product, [], actor=setup.human, requester=setup.peer)
                is expected
            )
