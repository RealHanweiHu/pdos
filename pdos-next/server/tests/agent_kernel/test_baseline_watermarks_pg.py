"""Bound baseline bodies use current RR metadata; no upstream source-body rebuild."""
# ruff: noqa: F811 -- explicit shared PG fixture

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pdos_next.domain.preproject import baseline
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, now
from pdos_next.original_security import security_row
from pdos_next.originals import require_original
from tests.agent_kernel.test_m3_definition_diff_pg import three_way
from tests.agent_kernel.test_m3_original_binding_pg import uploaded
from tests.agent_kernel.test_private_analysis_pg import bound, call, definition_ref
from tests.agent_kernel.test_transactions import human_session
from tests.preproject.test_derivation_transactions import (
    derivative_payload,
    synthetic_parent,
    typed_private_parent,
)
from tests.preproject.test_g0 import payload
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work


def setup_bound(work, kind):
    if kind == "published":
        parent, artifact_id, _, _ = typed_private_parent(work)
        f = bound(work, derivative_payload(work, parent))
    else:
        chain = three_way(work, visibility="private")
        parent = SimpleNamespace(id=chain.new, revision=3)
        data = payload(work)
        data["context_refs"] = [definition_ref(parent.id, 3)]
        f, artifact_id = bound(work, data), UUID(chain.artifact_id)
    return f, parent, artifact_id


def arguments(work, parent):
    return {
        "product_id": str(work.product),
        "definition_revision": parent.revision,
        "areas": ["specification"],
    }


@pytest.mark.parametrize("kind", ["published", "inherited_draft"])
def test_bound_baseline_reads_direct_body_once_without_full_source_tree(work, monkeypatch, kind):
    f, parent, _ = setup_bound(work, kind)
    views, statements = [], []
    original_view = baseline.definition_view

    def view(s, ctx, row):
        views.append(row.id)
        return original_view(s, ctx, row)

    def forbidden(*_a, **_kw):
        pytest.fail("A bound baseline already has an initial closure and current RR watermarks")

    def sql(_c, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    monkeypatch.setattr(baseline, "definition_view", view)
    monkeypatch.setattr(baseline, "validate_sources", forbidden)
    event.listen(work.engine, "before_cursor_execute", sql)
    try:
        result, replay = call(f, "product.baseline.read", arguments(work, parent))
    finally:
        event.remove(work.engine, "before_cursor_execute", sql)
    assert views == [parent.id]
    assert result["definition"]["id"] == str(parent.id)
    assert result["baseline_kind"] == ("published" if kind == "published" else "draft")
    assert result["derivation_eligible"] is (kind == "published")
    assert not any(
        "artifact_versions.content" in sql.split("FROM", 1)[0]
        or "public_web_snapshots.markdown" in sql.split("FROM", 1)[0]
        for sql in statements
    )
    bodies = [sql for sql in statements if "definition_revisions.title" in sql.split("FROM", 1)[0]]
    assert len(bodies) == 1
    assert replay() == result
    print(
        json.dumps(
            {
                "kind": kind,
                "direct_definition_body_selects": len(bodies),
                "upstream_source_body_selects": 0,
                **f.last_read,
            }
        )
    )


@pytest.mark.parametrize("change", ["withdrawn_source", "expired_membership"])
def test_source_watermarks_are_rechecked_before_restoring_baseline(work, monkeypatch, change):
    f, parent, artifact_id = setup_bound(work, "published")
    result, replay = call(f, "product.baseline.read", arguments(work, parent))
    assert result["derivation_eligible"]
    with Session(work.admin) as session, session.begin():
        if change == "withdrawn_source":
            session.get(Artifact, artifact_id).status = "withdrawn"
        else:
            session.scalar(
                select(Grant).where(
                    Grant.tenant_id == work.tenant,
                    Grant.category_id == work.category,
                    Grant.principal_id == work.human,
                )
            ).expires_at = now() - timedelta(seconds=1)
    monkeypatch.setattr(
        baseline,
        "definition_view",
        lambda *_a: pytest.fail("Stale authority must stop before baseline body"),
    )
    with pytest.raises(DomainError):
        replay()


def test_unbound_public_baseline_keeps_ordinary_source_validation(work, monkeypatch):
    parent = synthetic_parent(work)
    f = bound(work, derivative_payload(work, parent))
    newer = synthetic_parent(work, revision=2)
    assert newer.id != parent.id
    original, checks = baseline.validate_sources, []

    def validate(s, ctx, view, **options):
        checks.append(options.get("history_permissions", False))
        return original(s, ctx, view, **options)

    monkeypatch.setattr(baseline, "validate_sources", validate)
    result, _ = call(f, "product.baseline.read", arguments(work, newer))
    assert result["definition"]["id"] == str(newer.id) and result["derivation_eligible"]
    assert checks == [True, False]
    with Session(work.admin) as session:
        assert session.get(DefinitionRevision, parent.id).revision == 1


def test_actual_uploaded_source_keeps_scan_and_taint_without_loading_body(
    work,
    security_work,
    monkeypatch,
):
    original_id, artifact_id = uploaded(work, security_work)
    parent = synthetic_parent(work, private=True, artifact_source=artifact_id)
    f = bound(work, derivative_payload(work, parent))
    assert "customer_original" in f.scope.data_categories
    statements = []

    def sql(_c, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    monkeypatch.setattr(
        baseline,
        "validate_sources",
        lambda *_a, **_kw: pytest.fail(
            "Actual uploaded source must reuse the existing bound closure"
        ),
    )
    event.listen(work.engine, "before_cursor_execute", sql)
    try:
        result, replay = call(f, "product.baseline.read", arguments(work, parent))
    finally:
        event.remove(work.engine, "before_cursor_execute", sql)
    assert result["derivation_eligible"]
    assert result["definition"]["sources"][0]["artifact_id"] == str(artifact_id)
    assert not any(
        "artifact_versions.content" in statement.split("FROM", 1)[0] for statement in statements
    )
    with human_session(work) as session:
        original = require_original(session, work.ctx, None, original_id)
        epoch = security_row(session, original, lock=False).epoch
    changed = security_work.client.post(
        f"/v1/categories/{work.category}/originals/{original_id}/scan",
        headers=work.headers,
        json={"expected_epoch": epoch, "idempotency_key": str(uuid4())},
    )
    assert changed.status_code == 200, changed.text
    with pytest.raises(DomainError):
        replay()
