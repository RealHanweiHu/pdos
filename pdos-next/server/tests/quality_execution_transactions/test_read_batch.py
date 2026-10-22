"""Whole-reading terminal guards; PostgreSQL checks run only on root's explicit target."""

# ruff: noqa: F401,F811 -- explicit fixture tree for the actual PG case

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from quality_execution.fixtures import (
    accepted_work,
    command,
    counts,
    create_issue,
    known_configuration,
    launch_work,
    listing,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import event
from test_project_first_plan import post
from test_resource_dependency_execution import engines

from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_execution import service
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.request_proof import request_proof, scope_is_held


def test_quality_reading_terminal_error_prevents_returning_built_current_view(monkeypatch):
    events = []
    ctx, pid = object(), object()

    @contextmanager
    def boundary(session, actual_ctx, actual_pid):
        assert actual_ctx is ctx and actual_pid is pid
        events.append("enter")
        yield
        events.append("terminal")
        raise DomainError("SOURCE_STALE", "Terminal revocation after all failure IO")

    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(_pdos_quality_result_read_batch=boundary)
    )

    def reading(*args, **kwargs):
        events.append("all_views_built")
        return {"source_status": "current"}

    monkeypatch.setattr(service, "_list_quality", reading)
    with pytest.raises(DomainError) as error:
        service.list_quality(session, ctx, pid, run_id=object())
    assert error.value.reason == "SOURCE_STALE"
    assert events == ["enter", "all_views_built", "terminal"]


def test_quality_reading_optional_port_preserves_original_scope_and_value(monkeypatch):
    session = SimpleNamespace(get_bind=lambda: SimpleNamespace())
    ctx, pid, issue, run, build = [object() for _ in range(5)]
    value = {"issues": []}

    def reading(actual_session, actual_ctx, actual_pid, **binding):
        assert (actual_session, actual_ctx, actual_pid) == (session, ctx, pid)
        assert binding == {"issue_id": issue, "run_id": run, "build_id": build}
        return value

    monkeypatch.setattr(service, "_list_quality", reading)
    assert (
        service.list_quality(session, ctx, pid, issue_id=issue, run_id=run, build_id=build) is value
    )
    with pytest.raises(TypeError):
        service.configure_result_bridge(SimpleNamespace(), None, read_batch=True)


def test_actual_multi_failure_reading_shares_retained_and_rejects_late_byte_revocation(
    quality_work, monkeypatch
):
    from uuid import UUID

    from pdos_next import quality_result_bridge as bridge
    from pdos_next.domain.quality_execution import evidence, policy
    from pdos_next.models import Artifact

    work = quality_work
    publish_policy(work)
    create_issue(work, 0)
    # Keep one failure unadmitted: its initial reading still requires the
    # genuine retained terminal. The saved failure uses direct watermarks.
    baseline = counts(work)
    retained, reads = [], []
    actual_retained = bridge.inspect_retained_execution
    actual_read = work.report_store.read_original

    def observed_retained(*args, **kwargs):
        retained.append(args[3].id)
        return actual_retained(*args, **kwargs)

    def observed_read(reference):
        reads.append(reference.id)
        return actual_read(reference)

    monkeypatch.setattr(bridge, "inspect_retained_execution", observed_retained)
    monkeypatch.setattr(work.report_store, "read_original", observed_read)
    version_queries, source_calls, active_sources, active_batches = [], [], [], []
    actual_basis, actual_batch = evidence.source_basis, evidence._batch_artifact_rows
    assert service.source_basis is actual_basis
    assert policy.source_basis is actual_basis
    observing_sources = True

    def observed_basis(session, ctx, pid, source_reads):
        if not observing_sources:
            return actual_basis(session, ctx, pid, source_reads)
        complete = evidence.merge_reads(source_reads)
        call = {"ids": {UUID(value["artifact_id"]) for value in complete}, "batch": None}
        source_calls.append(call)
        active_sources.append(call)
        try:
            value = actual_basis(session, ctx, pid, source_reads)
            assert {UUID(row["id"]) for row in value[0]} == call["ids"]
            assert call["batch"] is not None and call["batch"]["ids"] == call["ids"]
            return value
        finally:
            assert active_sources.pop() is call

    def observed_batch(session, ctx, pid, source_reads, proof):
        if not observing_sources:
            return actual_batch(session, ctx, pid, source_reads, proof)
        assert session.info.get("read_snapshot") is True
        assert session.is_active and session.in_transaction()
        assert not (session.new or session.dirty or session.deleted)
        assert session.info["scope"] == (
            ctx.tenant_id,
            ctx.actor_id,
            ctx.requester_id,
            ctx.category_id,
        )
        identities = {UUID(value["artifact_id"]) for value in evidence.merge_reads(source_reads)}
        assert active_sources and identities == active_sources[-1]["ids"]
        already_raw = set()
        for identity in identities:
            key = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id, pid, identity)
            if (
                proof.read_rows.get((Artifact, identity)) is not None
                or proof.sources.get(key) is not None
                or proof.source_rows.get(key) is not None
            ):
                already_raw.add(identity)
        batch = {
            "ids": identities,
            "missing": identities - already_raw,
            "scope": (ctx.tenant_id, ctx.category_id, pid),
            "queries": [],
        }
        active_sources[-1]["batch"] = batch
        active_batches.append(batch)
        try:
            value = actual_batch(session, ctx, pid, source_reads, proof)
            assert len(batch["queries"]) == bool(batch["missing"])
            return value
        finally:
            assert active_batches.pop() is batch

    monkeypatch.setattr(service, "source_basis", observed_basis)
    monkeypatch.setattr(policy, "source_basis", observed_basis)
    monkeypatch.setattr(evidence, "source_basis", observed_basis)
    monkeypatch.setattr(evidence, "_batch_artifact_rows", observed_batch)

    def observe_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("SELECT") and "FROM quality_issue_versions" in statement:
            version_queries.append(statement)
        if (
            active_batches
            and statement.lstrip().startswith("SELECT")
            and "FROM artifact_versions" in statement
        ):
            batch = active_batches[-1]
            assert not executemany and isinstance(parameters, dict)
            assert "artifact_versions.tenant_id =" in statement
            assert "artifact_versions.category_id =" in statement
            assert (
                "artifact_versions.product_id IS NULL OR artifact_versions.product_id ="
                in statement
            )
            assert "artifact_versions.id IN (" in statement and "LIMIT" not in statement
            tenant, category, pid = batch["scope"]
            assert parameters["tenant_id_1"] == tenant
            assert parameters["category_id_1"] == category
            assert parameters["product_id_1"] == pid
            actual_ids = {
                UUID(str(value)) for key, value in parameters.items() if key.startswith("id_1_")
            }
            assert actual_ids == batch["missing"]
            batch["queries"].append(actual_ids)

    event.listen(work.setup.engine, "before_cursor_execute", observe_query)
    try:
        view = listing(work)
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", observe_query)
        observing_sources = False
    assert source_calls and not active_sources and not active_batches
    # Direct references can be checked individually from the request's raw
    # bank. Require complete coverage of the saved failure's exact sources;
    # the observer still checks one query for each actual missing set.
    required_direct = {
        UUID(failure[name]["id"])
        for row in view["issues"]
        for failure in row["issue"]["failures"]
        for name in ("criterion", "method", "source")
    }
    observed_direct = set().union(*(call["ids"] for call in source_calls))
    assert len(required_direct) > 1 and required_direct <= observed_direct
    # The real list reads every selected Issue snapshot in one query. Stored
    # writer/proof snapshots must neither be transferred nor lazily fetched.
    assert len(version_queries) == 1
    projection = version_queries[0].split("FROM", 1)[0]
    assert "issue_snapshot" in projection
    assert "quality_issue_versions.source_basis" in projection
    assert all(
        f"quality_issue_versions.{column}" not in projection
        for column in ("input_snapshot", "authority_snapshot", "policy_snapshot")
    )
    assert len(view["current_by_issue"]) == 1
    assert len(view["failures"]) == 2 and all(row["available"] for row in view["failures"])
    assert all(row["source_status"] == "current" for row in view["issues"] if row["is_current"])
    assert len(retained) == 2 and retained[0] == retained[1]
    # Only the unadmitted failure reads these actual report bytes, once.
    # The saved failure uses its direct Current/result/source watermarks.
    assert len(reads) == 1
    assert counts(work) == baseline

    # Revoke after the last successful byte read from the positive candidate.
    # The whole-reading boundary must refuse a response, even when earlier
    # current Issue DTOs have already been constructed.
    expected_reads = len(reads)
    reads.clear()
    retained.clear()

    def revoke_late(reference):
        content = actual_read(reference)
        reads.append(reference.id)
        if len(reads) == expected_reads:
            professional.disable_issuer(work.setup.engine, work.professional_issuer.key)
        return content

    monkeypatch.setattr(work.report_store, "read_original", revoke_late)
    refused = work.quality.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution",
        headers=work.quality.headers,
        params={"run_id": str(work.failure_run.id), "build_id": work.build_id},
    )
    assert len(reads) == expected_reads
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "SOURCE_STALE"
    assert counts(work) == baseline


def test_actual_writer_preparation_keeps_record_fresh_and_seals_qualification_after_terminal_io(
    quality_work, monkeypatch
):
    import re
    from uuid import UUID, uuid4

    from pdos_next import quality_result_bridge as bridge
    from pdos_next.domain.quality_execution import evidence
    from pdos_next.models import Artifact, Receipt

    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work, 0)
    second, _ = create_issue(work, 1)
    # This genuine T1 merge keeps the complete retained writer boundary.
    value = command(
        work,
        "quality.issue.merge",
        {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "sources": [{"id": second["result"]["issue_id"], "revision": 1}],
            "reason": "Actual held writer preparation and independently fresh record",
        },
    )
    retained, late_clock = [], []
    original_retained = bridge.inspect_retained_execution
    advance_clock = False
    future = now() + timedelta(hours=3)
    actual_now = service.now
    writer_batches, active_writer_batches = [], []
    observing_writer = {"phase": None}
    actual_writer_batch = evidence._batch_writer_native_registrations

    def observe_writer_batch(session, ctx, pid, source_reads):
        if observing_writer["phase"] is None:
            return actual_writer_batch(session, ctx, pid, source_reads)
        complete = evidence.merge_reads(source_reads)
        proof = request_proof(session)
        rows = []
        for read in complete:
            identity = UUID(read["artifact_id"])
            key = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id, pid, identity)
            rows.append(
                proof.sources.get(key)
                or proof.source_rows.get(key)
                or proof.read_rows.get((Artifact, identity))
            )
        observed = {
            "phase": observing_writer["phase"],
            "epoch": proof.mutation_epoch,
            "session": session,
            "ctx": ctx,
            "pid": pid,
            "proof": proof,
            "rows": rows,
            "queries": [],
            "expected": {
                (row.id, read["expected_revision"])
                for row, read in zip(rows, complete, strict=True)
                if row is not None
                and not row.original_id
                and ("scope-scalar", pid, (Receipt, "artifact-registration", row.id, row.revision))
                not in proof.scalar_rows
            },
        }
        writer_batches.append(observed)
        active_writer_batches.append(observed)
        try:
            return actual_writer_batch(session, ctx, pid, source_reads)
        finally:
            assert active_writer_batches.pop() is observed

    def observe_writer_query(connection, cursor, statement, parameters, context, executemany):
        if not (
            active_writer_batches
            and statement.lstrip().startswith("SELECT")
            and "FROM action_receipts" in statement
        ):
            return
        observed = active_writer_batches[-1]
        session, ctx, pid, proof = (
            observed["session"],
            observed["ctx"],
            observed["pid"],
            observed["proof"],
        )
        assert session.info.get("read_snapshot") is not True
        assert session.is_active and not (session.new or session.dirty or session.deleted)
        assert session.info["scope"] == (
            ctx.tenant_id,
            ctx.actor_id,
            ctx.requester_id,
            ctx.category_id,
        )
        assert scope_is_held(session, pid) and pid in proof.scope_locks
        assert request_proof(session) is proof and proof.mutation_epoch == observed["epoch"]
        assert all(
            isinstance(row, Artifact) and proof.read_rows[(Artifact, ("locked", row.id))] is True
            for row in observed["rows"]
        )
        assert not executemany and isinstance(parameters, dict)
        assert "action_receipts.tenant_id =" in statement
        assert "action_receipts.category_id =" in statement
        assert "action_receipts.product_id IS NOT DISTINCT FROM" in statement
        assert "(action_receipts.subject_id, action_receipts.subject_revision) IN (" in statement
        assert "LIMIT" not in statement
        assert parameters["tenant_id_1"] == ctx.tenant_id
        assert parameters["category_id_1"] == ctx.category_id
        assert parameters["operation_1"] == "evidence.artifact.register"
        assert parameters["subject_type_1"] == "artifact"
        pairs = {
            (UUID(str(value)), parameters[key[:-1] + "2"])
            for key, value in parameters.items()
            if re.fullmatch(r"param_[0-9]+_[0-9]+_1", key)
        }
        assert pairs == observed["expected"]
        observed["queries"].append(pairs)

    @contextmanager
    def observe_writer_sql(phase):
        observing_writer["phase"] = phase
        event.listen(work.setup.engine, "before_cursor_execute", observe_writer_query)
        try:
            yield
        finally:
            event.remove(work.setup.engine, "before_cursor_execute", observe_writer_query)
            observing_writer["phase"] = None
            assert not active_writer_batches

    def observed_retained(session, ctx, pid, row, *, write, **kwargs):
        batch = session.info.get(bridge._READ_BATCH)
        preparation = batch is not None and batch.preparation
        if preparation:
            assert session.info.get("read_snapshot") is not True
            assert scope_is_held(session, pid)
            assert request_proof(session).mutation_epoch == 0
            assert not (session.new or session.dirty or session.deleted)
        retained.append((preparation, write))
        proof = original_retained(session, ctx, pid, row, write=write, **kwargs)
        if advance_clock and preparation and not write:
            assert proof["current"] is True
            # The genuine retained terminal has completed. Its IO crosses the
            # current quality actor's natural qualification end; professional
            # assess/time guards must still execute afterward, outside reuse.
            late_clock.append(True)
            monkeypatch.setattr(service, "now", lambda: future)
        return proof

    monkeypatch.setattr(bridge, "inspect_retained_execution", observed_retained)
    # This one owner hook observes service/policy's imported source_basis alike;
    # it forwards all real source/receipt guards and never replaces source_for.
    monkeypatch.setattr(evidence, "_batch_writer_native_registrations", observe_writer_batch)
    with observe_writer_sql("preview"):
        preview = post(work.quality, value, True)
    assert preview.status_code == 200, preview.text
    assert retained == [(True, True), (True, False)]
    assert any(
        len(pairs) > 1
        for observed in writer_batches
        if observed["phase"] == "preview"
        for pairs in observed["queries"]
    )
    # Probe expiry before the valid merge changes either Issue Current. The
    # refused preview leaves the original reviewed confirmation usable.
    refused_command = {
        **value,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
    }
    baseline = counts(work)
    retained.clear()
    advance_clock = True
    try:
        with observe_writer_sql("late_preview"):
            refused = post(work.quality, refused_command, True)
    finally:
        advance_clock = False
        monkeypatch.setattr(service, "now", actual_now)
    assert late_clock == [True]
    assert retained == [(True, True), (True, False)]
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "SOURCE_STALE"
    assert counts(work) == baseline

    retained.clear()
    with observe_writer_sql("commit"):
        committed = post(work.quality, preview.json()["command"])
    assert committed.status_code == 200, committed.text
    # Each of the merge's two failures gets an independently fresh record
    # check after confirmation consumption invalidates the prepared raw bank.
    assert retained == [(True, True), (True, False), (False, True), (False, True)]
    prepared_pairs, fresh_pairs = set(), set()
    for observed in writer_batches:
        if observed["phase"] == "commit":
            for pairs in observed["queries"]:
                (prepared_pairs if observed["epoch"] == 0 else fresh_pairs).update(pairs)
    # Confirmation consumption discarded the first epoch's raw bank. These are
    # actual new SQL reads under the still-held gate, not a borrowed positive proof.
    assert len(prepared_pairs) > 1 and fresh_pairs == prepared_pairs


def test_actual_writer_late_access_io_cannot_revoke_original_run_issuer_and_return_preview(
    quality_work, monkeypatch
):
    from pdos_next import quality_result_bridge as bridge
    from pdos_next.domain.test_resources import service as resources

    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work, 0)
    second, _ = create_issue(work, 1)
    value = command(
        work,
        "quality.issue.merge",
        {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "sources": [{"id": second["result"]["issue_id"], "revision": 1}],
            "reason": "Actual last quality source IO must retain the T1 merge boundary",
        },
    )
    baseline = counts(work)
    retained, revoked, sessions = [], [], []
    actual_retained, actual_basis = bridge.inspect_retained_execution, service.source_basis
    terminal_completed = False

    def observed_retained(session, ctx, pid, row, *, write, **kwargs):
        nonlocal terminal_completed
        batch = session.info.get(bridge._READ_BATCH)
        assert batch is not None and batch.preparation
        assert scope_is_held(session, pid) and request_proof(session).mutation_epoch == 0
        retained.append(write)
        proof = actual_retained(session, ctx, pid, row, write=write, **kwargs)
        assert proof["current"] is True
        if not write:
            terminal_completed = True
        return proof

    def revoke_after_actual_source_io(session, ctx, pid, reads):
        value = actual_basis(session, ctx, pid, reads)
        batch = session.info.get(bridge._READ_BATCH)
        if terminal_completed and batch is not None and batch.preparation and not revoked:
            assert batch.closing and scope_is_held(session, pid)
            sessions.append(session)
            resources.disable_issuer(work.setup.engine, work.test_issuer.key)
            revoked.append(True)
        return value

    monkeypatch.setattr(bridge, "inspect_retained_execution", observed_retained)
    monkeypatch.setattr(service, "source_basis", revoke_after_actual_source_io)
    refused = post(work.quality, value, True)
    assert retained == [True, False] and revoked == [True]
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "SOURCE_STALE"
    assert all(bridge._READ_BATCH not in session.info for session in sessions)
    assert counts(work) == baseline
