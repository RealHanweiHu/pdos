"""Actual quality inputs/confirmation guards; root runs the verified PG target."""

# ruff: noqa: F401,F811 -- explicit imports register the complete real fixture tree

from collections import Counter
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from quality_execution.fixtures import (
    accepted_work,
    command,
    counts,
    create_issue,
    issue_current,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
    unconsumed,
)
from quality_execution.test_pure import create, host
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from test_project_first_plan import cmd, post
from test_resource_dependency_execution import engines

from pdos_next import service as common
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_execution import direct, service
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.service import digest


def _triage(work):
    publish_policy(work)
    created, _ = create_issue(work)
    payload = {
        "issue_id": created["result"]["issue_id"],
        "expected_issue_revision": 1,
        "reason": "Actual named triage with transaction-bound preparation",
    }
    return created, payload


def test_inputs_are_rr_readonly_and_each_confirmation_request_prepares_once(
    quality_work, monkeypatch
):
    work = quality_work
    created, payload = _triage(work)
    value = cmd(work.quality, "quality.issue.triage", payload)
    baseline = counts(work)
    phase = "inputs"
    prepared = Counter()
    statements = []
    original_load, original_result = direct.load, service._result
    upstream = Counter()

    def observed_load(s, ctx, command, product, payload, **kwargs):
        prepared[phase] += 1
        assert s.info["read_snapshot"] is (phase == "inputs")
        return original_load(s, ctx, command, product, payload, **kwargs)

    def unexpected_result(*args, **kwargs):
        upstream[phase] += 1
        raise AssertionError("Direct T1 quality preparation must not reload the upstream result")

    def record_statement(_conn, _cursor, statement, _params, _context, _many):
        statements.append(" ".join(statement.upper().split()))

    monkeypatch.setattr(direct, "load", observed_load)
    monkeypatch.setattr(service, "_result", unexpected_result)
    event.listen(work.setup.engine, "before_cursor_execute", record_statement)
    try:
        response = work.quality.client.post(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}"
            "/quality-execution/inputs",
            headers=work.quality.headers,
            json=value,
        )
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", record_statement)
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] is True
    assert "SET TRANSACTION READ ONLY" in statements
    assert not any("FOR UPDATE" in q or "FOR SHARE" in q for q in statements)
    assert counts(work) == baseline
    value["source_read_set"] = response.json()["required_source_read_set"]

    phase = "preview"
    preview = post(work.quality, value, True)
    assert preview.status_code == 200, preview.text
    phase = "confirmation"
    committed = post(work.quality, preview.json()["command"])
    assert committed.status_code == 200, committed.text
    assert prepared == {"inputs": 1, "preview": 1, "confirmation": 1}
    assert not upstream
    monkeypatch.setattr(service, "_result", original_result)
    saved = issue_current(work, created["result"]["issue_id"])
    assert saved["revision"] == 2 and saved["issue"]["status"] == "triaged"
    assert committed.json()["subject_revision"] == 2


@pytest.mark.parametrize(
    "changed", ["issuer", "actor", "scope", "grant_expiry", "nested_transaction"]
)
def test_direct_preparation_rejects_late_source_io_issuer_or_context_changes(
    quality_work, monkeypatch, changed
):
    work = quality_work
    created, payload = _triage(work)
    deadline = None
    if changed == "grant_expiry":
        # Reuse the grant deadline already present when these Originals were
        # scanned. Changing it here would invalidate their signed access basis
        # before reaching the intended late consumer-authorization check.
        with Session(work.setup.admin) as session:
            deadline = session.scalar(
                select(Grant.expires_at)
                .where(
                    Grant.tenant_id == work.setup.tenant,
                    Grant.category_id == work.setup.category,
                    Grant.principal_id == work.quality.human,
                )
            )
        assert deadline is not None and deadline > now()
    value = command(work, "quality.issue.triage", payload)
    preview = post(work.quality, value, True)
    assert preview.status_code == 200, preview.text
    confirmed = preview.json()["command"]
    baseline = counts(work)
    original_basis = direct.source_basis
    fired = []
    restore = []
    nested_transactions = []

    def change_after_actual_evidence(s, ctx, *args, **kwargs):
        # This is the actor's actual source SQL, after the direct references.
        # Its returned evidence is unchanged; only the late callback is injected.
        material = original_basis(s, ctx, *args, **kwargs)
        if not fired:
            fired.append(True)
            if changed == "issuer":
                professional.disable_issuer(work.setup.engine, work.professional_issuer.key)
            elif changed == "actor":
                restore.append((ctx, ctx.actor_id))
                object.__setattr__(ctx, "actor_id", work.setup.agent)
            elif changed == "scope":
                s.info["scope"] = (*s.info["scope"][:3], work.setup.agent)
            elif changed == "nested_transaction":
                nested = s.begin_nested()
                assert nested.is_active and s.get_nested_transaction() is nested
                # Keep the actual SAVEPOINT open across the owner boundary;
                # returning to the same root transaction cannot hide the drift.
                nested_transactions.append(nested)
            else:
                late = deadline + timedelta(seconds=1)
                monkeypatch.setattr(direct, "now", lambda: late)
                monkeypatch.setattr(common, "now", lambda: late)
        return material

    monkeypatch.setattr(direct, "source_basis", change_after_actual_evidence)
    try:
        response = post(work.quality, confirmed)
    finally:
        for nested in nested_transactions:
            if nested.is_active:
                nested.rollback()
        for ctx, actor_id in restore:
            object.__setattr__(ctx, "actor_id", actor_id)
        if changed == "grant_expiry":
            monkeypatch.setattr(direct, "now", now)
            monkeypatch.setattr(common, "now", now)
    assert fired == [True]
    assert response.status_code == (403 if changed == "grant_expiry" else 409), response.text
    assert response.json()["code"] == (
        "FORBIDDEN_SCOPE" if changed == "grant_expiry" else "SOURCE_STALE"
    )
    if changed == "nested_transaction":
        assert len(nested_transactions) == 1
        assert not nested_transactions[0].is_active
        assert response.json()["detail"]["reason"] == "SOURCE_STALE"
    assert counts(work) == baseline
    unconsumed(work, confirmed["payload"]["confirmation_token"])
    assert issue_current(work, created["result"]["issue_id"])["revision"] == 1


def test_rr_quality_rows_keep_exact_versions_guards_and_transaction_boundaries(host, monkeypatch):
    """No connection: real immutable Issue DTOs, explicit synthetic query seam."""
    first = create(host)
    snapshot = Issue.model_validate(first.issue_snapshot).model_copy(
        update={"revision": 2, "status": "triaged"}
    )
    second = QualityIssueVersion(
        id=uuid4(),
        tenant_id=first.tenant_id,
        product_id=first.product_id,
        project_id=first.project_id,
        owner_id=first.owner_id,
        visibility=first.visibility,
        issue_id=first.issue_id,
        revision=2,
        status="triaged",
        issue_snapshot=snapshot.model_dump(mode="json"),
        snapshot_sha256=digest(snapshot.model_dump(mode="json")),
    )
    rows = {first.revision: first, second.revision: second}
    queries = []

    def selected(query):
        revision = query.compile().params["revision_1"]
        queries.append(revision)
        return rows[revision]

    with Session() as session:
        session.info["read_snapshot"] = True
        monkeypatch.setattr(session, "scalar", selected)
        with session.begin():
            assert service._row(session, host.ctx, host.product.id, first.issue_id, 1) is first
            assert service._row(session, host.ctx, host.product.id, first.issue_id, 1) is first
            assert service._row(session, host.ctx, host.product.id, first.issue_id, 2) is second
            assert queries == [1, 2]
            title = first.issue_snapshot["title"]
            first.issue_snapshot["title"] = "Untracked JSON must still fail the complete hash guard"
            with pytest.raises(DomainError) as failure:
                service._row(session, host.ctx, host.product.id, first.issue_id, 1)
            assert failure.value.reason == "INTEGRITY_MISMATCH"
            first.issue_snapshot["title"] = title
            changed_reader = replace(host.ctx, requester_id=second.id)
            with pytest.raises(DomainError) as failure:
                service._row(session, changed_reader, host.product.id, first.issue_id, 1)
            assert failure.value.reason == "FORBIDDEN_SCOPE"
            assert queries == [1, 2]
        with session.begin():
            assert service._row(session, host.ctx, host.product.id, first.issue_id, 1) is first
            assert queries == [1, 2, 1]


def test_non_snapshot_quality_current_writer_keeps_fresh_locked_reads(host, monkeypatch):
    """No connection: an unheld writer cannot opt into an RR query memo."""
    issue = create(host)
    queries = []
    pointer = SimpleNamespace(issue_version_id=issue.id, issue_revision=issue.revision)

    def selected(query):
        queries.append(query._for_update_arg is not None)
        return pointer

    with Session() as session, session.begin():
        monkeypatch.setattr(session, "scalar", selected)
        assert service._current(session, host.ctx, host.product.id, issue.issue_id, lock=True)
        assert service._current(session, host.ctx, host.product.id, issue.issue_id, lock=True)
        assert queries == [True, True]
