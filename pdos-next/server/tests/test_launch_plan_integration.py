"""Actual common preview + persistent ORM protocol, with explicit no-SQL rows.

Only the proposed common function is AST-loaded.  Scalar reads return real
persistent SQLAlchemy rows; the delivered owner loader/CAS substitutes from the
count tests remain explicit.  No connection or actual qualification is claimed.
"""

import copy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached
from test_launch_plan_preview import no_io, work  # noqa: F401

from pdos_next import launch_plan_preview as seam
from pdos_next import service as common
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Category, Confirmation, Grant, Principal, Product


def proposed_preview():
    """Exercise the actual candidate common function, with explicit no-SQL owners."""
    return common.preview_command


@pytest.fixture
def common_rows(request, monkeypatch):
    w = request.getfixturevalue("work")
    principal = Principal(
        id=w.ctx.actor_id,
        tenant_id=w.ctx.tenant_id,
        created_at=w.clock[0],
        name="Explicit no-I/O actor",
        kind="human",
        active=True,
        access_epoch=1,
    )
    grant = Grant(
        id=uuid4(),
        tenant_id=w.ctx.tenant_id,
        created_at=w.clock[0],
        category_id=w.ctx.category_id,
        principal_id=w.ctx.actor_id,
        can_write=True,
        expires_at=w.clock[0] + timedelta(hours=1),
        access_epoch=1,
    )
    artifacts = [
        Artifact(
            id=ref.artifact_id,
            tenant_id=w.ctx.tenant_id,
            created_at=w.clock[0],
            product_id=w.product.id,
            category_id=w.ctx.category_id,
            owner_id=w.ctx.actor_id,
            title="No-I/O fixed original",
            source_label="Explicit scalar-read substitute",
            content=f"Fixed native material {n}",
            content_hash="a" * 64,
            visibility="category",
            revision=ref.expected_revision,
            original_id=None,
            status="active",
        )
        for n, ref in enumerate(w.command.source_read_set)
    ]
    category = Category(
        id=w.ctx.category_id,
        tenant_id=w.ctx.tenant_id,
        created_at=w.clock[0],
        name="No-I/O category root",
        purpose="Explicit synthetic category protocol",
        owner_id=w.ctx.actor_id,
        revision=1,
        lifecycle_epoch=1,
    )
    for row in [category, principal, grant, *artifacts]:
        make_transient_to_detached(row)
        w.s.add(row)
    selected = []

    def scalar(query):
        entity = query.column_descriptions[0]["entity"]
        selected.append(entity)
        if entity is Product:
            return w.product
        if entity is Artifact:
            # All ten fixture originals belong to this model, not the category-only branch.
            assert query.column_descriptions[0]["name"] in {"id", "Artifact"}
            return None
        pytest.fail(f"Unexpected common scalar read {entity}")

    def execute(query):
        assert [column["entity"] for column in query.column_descriptions] == [Principal, Grant]
        selected.extend((Principal, Grant))
        return SimpleNamespace(all=lambda: [(principal, grant)])

    def scalars(query):
        assert query.column_descriptions[0]["entity"] is Artifact
        selected.append((Artifact, "batch"))
        # Explicit RLS substitute in a no-I/O protocol check. Actual privacy is tested in PG.
        return iter(
            row
            for row in artifacts
            if row.visibility == "category" or row.owner_id == w.ctx.actor_id
        )

    monkeypatch.setattr(w.s, "scalar", scalar)
    monkeypatch.setattr(w.s, "execute", execute)
    monkeypatch.setattr(w.s, "scalars", scalars)
    w.s.info["scope"] = (w.ctx.tenant_id, w.ctx.actor_id, w.ctx.requester_id, w.ctx.category_id)
    monkeypatch.setattr(common, "now", lambda: w.clock[0])
    w.category, w.principal, w.grant, w.artifacts, w.selected = (
        category,
        principal,
        grant,
        artifacts,
        selected,
    )
    return w


def test_normal_common_locks_and_persistent_rows_are_not_pending_writes(common_rows, monkeypatch):
    w = common_rows
    original = copy.deepcopy(w.command.model_dump(mode="json"))
    actual_preview = seam.preview_once
    entry_states = []

    def counted(*args):
        entry_states.append((len(w.s.identity_map), len(w.s.new), len(w.s.dirty), len(w.s.deleted)))
        return actual_preview(*args)

    monkeypatch.setattr(seam, "preview_once", counted)
    result = proposed_preview()(w.s, w.ctx, w.command)
    assert entry_states == [(14, 0, 0, 0)]
    assert w.selected.count(Product) == 1
    assert w.selected.count(Principal) == 1 and w.selected.count(Grant) == 1
    assert w.selected.count((Artifact, "batch")) == 1
    assert w.counts == {"load": 1, "guards": 1, "cas": 1}
    pending = list(w.s.new)
    assert len(pending) == 1 and type(pending[0]) is Confirmation
    assert pending[0].snapshot == result["review"]
    assert pending[0].payload_digest == common.material_digest(
        w.ctx, w.command, w.payload, common.handler(w.command.operation)
    )
    assert result["review"]["after"]["occupancy_effect"] == "none"
    assert w.command.model_dump(mode="json") == original


@pytest.mark.parametrize("failure", ["private_source", "source_revision", "expired_grant"])
def test_actual_common_rejection_occurs_before_owner_and_confirmation(common_rows, failure):
    w = common_rows
    # Establish loaded committed values without manufacturing a dirty-UOW failure.
    from sqlalchemy.orm.attributes import set_committed_value

    if failure == "private_source":
        set_committed_value(w.artifacts[0], "visibility", "private")
        set_committed_value(w.artifacts[0], "owner_id", uuid4())
        expected = "SOURCE_UNAVAILABLE"
    elif failure == "source_revision":
        set_committed_value(w.artifacts[0], "revision", 2)
        expected = "SOURCE_STALE"
    else:
        set_committed_value(w.grant, "expires_at", w.clock[0])
        expected = "FORBIDDEN_SCOPE"
    with pytest.raises(DomainError) as error:
        proposed_preview()(w.s, w.ctx, w.command)
    assert error.value.code == expected
    assert w.counts == {"load": 0, "guards": 0, "cas": 0}
    assert not w.s.new and not w.s.dirty and not w.s.deleted
