"""Actual common preview + persistent ORM protocol, with explicit no-SQL rows.

Only the proposed common function is AST-loaded.  Scalar reads return real
persistent SQLAlchemy rows; the delivered owner loader/CAS substitutes from the
count tests remain explicit.  No connection or actual qualification is claimed.
"""

import copy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import make_transient_to_detached
from test_launch_plan_preview import no_io, work  # noqa: F401

from pdos_next import launch_plan_preview as seam
from pdos_next import service as common
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Confirmation, Grant, Principal, Product


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
        product_id=w.product.id,
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
            owner_id=w.ctx.actor_id,
            title="No-I/O fixed original",
            source_label="Explicit scalar-read substitute",
            content=f"Fixed native material {n}",
            content_hash="a" * 64,
            visibility="product",
            revision=ref.expected_revision,
            original_id=None,
            status="active",
        )
        for n, ref in enumerate(w.command.source_read_set)
    ]
    for row in [principal, grant, *artifacts]:
        make_transient_to_detached(row)
        w.s.add(row)
    selected = []
    artifact_reads = iter(artifacts)

    def scalar(query):
        entity = query.column_descriptions[0]["entity"]
        selected.append(entity)
        if entity is Product:
            return w.product
        if entity is Principal:
            return principal
        if entity is Grant:
            return grant
        if entity is Artifact:
            return next(artifact_reads)
        pytest.fail(f"Unexpected common scalar read {entity}")

    monkeypatch.setattr(w.s, "scalar", scalar)
    monkeypatch.setattr(common, "now", lambda: w.clock[0])
    w.principal, w.grant, w.artifacts, w.selected = principal, grant, artifacts, selected
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
    assert entry_states == [(13, 0, 0, 0)]
    assert w.selected.count(Product) == 12
    assert w.selected.count(Principal) == 1 and w.selected.count(Grant) == 1
    assert w.selected.count(Artifact) == 10
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
