"""Substituted owner IO checks only; no real qualification/PG positive is claimed."""

import socket
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import get_args
from uuid import uuid4

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pdos_next import change_graph_closure as closure
from pdos_next import change_order_service as formal
from pdos_next.domain.change_coverage_owner import owner
from pdos_next.domain.change_execution import service as candidate
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Coverage, Facet, GraphSnapshot, Node, Ref
from pdos_next.schemas.verification.contracts import Scope, SourceRef


@pytest.fixture(autouse=True)
def prohibit_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Staged pure checks forbid database/network IO")

    for cls, method in (
        (Engine, "connect"),
        (Engine, "raw_connection"),
        (Session, "execute"),
        (Session, "connection"),
        (Session, "commit"),
        (Session, "flush"),
        (httpx.Client, "request"),
        (httpx.AsyncClient, "request"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ):
        monkeypatch.setattr(cls, method, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def boundary(monkeypatch):
    at = datetime(2026, 10, 5, 12, tzinfo=UTC)
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    ctx = SimpleNamespace(tenant_id=scope.tenant_id, requester_id=uuid4(), actor_id=uuid4())
    ref = Ref(id=uuid4(), revision=1, kind="issue")
    source = SourceRef(id=uuid4(), revision=1, kind="artifact", position="pure-substituted-io")
    reads = [{"artifact_id": str(source.id), "expected_revision": 1}]
    request = SimpleNamespace(
        id=uuid4(), scope=scope, roots=(ref,), references=(), sources=(source,), audience=("probe",)
    )
    row = SimpleNamespace(
        id=uuid4(),
        change_id=request.id,
        revision=1,
        visibility="private",
        owner_id=ctx.requester_id,
    )
    state = SimpleNamespace(
        at=at,
        until=at + timedelta(minutes=4),
        trace=[],
        read_graphs=[],
        owner_returns=[],
        access_fault=None,
        flush_fault=None,
        version=row,
        runtime="fixed-runtime",
        clock_stamp={"epoch": 7},
        responded=0,
    )

    class SubstitutedSession:
        """No real Session/UOW, SQL, transaction, authority or rollback evidence."""

        old = None
        rows = []
        scalar_count = 0

        def scalar(self, query):
            self.scalar_count += 1
            return SimpleNamespace() if self.scalar_count % 2 else self.old

        def add(self, value):
            state.trace.append("stage_capture")
            self.rows.append(value)

        def flush(self):
            state.trace.append("full_flush")
            if state.flush_fault is not None:
                state.flush_fault()

    session = SubstitutedSession()
    reader = SimpleNamespace(
        objects={ref.identity: SimpleNamespace(reads=reads, source_basis={"fixed": "probe"})},
        resolve=lambda value: SimpleNamespace(current=True),
    )
    authority = {
        "operation": "change.impact.compute",
        "purpose": "pure-purpose",
        "roles": ["quality"],
        "fact_refs": [
            {
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": ["change.impact.compute"],
                "purposes": ["pure-purpose"],
                "valid_from": (at - timedelta(hours=1)).isoformat(),
                "valid_until": (at + timedelta(minutes=30)).isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
        "valid_until": (at + timedelta(minutes=30)).isoformat(),
        "synthetic": True,
        "required_source_read_set": reads,
    }

    def graph_builder(_reader, *, identity, roots, captured_at, expires_at, nature, sources):
        return GraphSnapshot(
            id=identity,
            revision=1,
            scope=scope,
            audience=request.audience,
            roots=roots,
            nodes=(
                Node(ref=ref, scope=scope, audience=request.audience, source=source, label="Probe"),
            ),
            edges=(),
            coverage=tuple(
                Coverage(node=ref, facet=facet, status="unknown", reason="Substituted IO only")
                for facet in get_args(Facet)
            ),
            sources=sources,
            captured_at=captured_at,
            expires_at=expires_at,
            nature=nature,
        )

    def substitute_owner_read(s, caller, pid, *, change_id, purpose, graph):
        assert s is session and caller is ctx and pid == scope.product_id
        state.trace.append("owner_read")
        state.read_graphs.append(graph)
        basis = {
            "graph": {
                "id": str(graph.id),
                "revision": graph.revision,
                "captured_at": graph.captured_at.isoformat(),
                "expires_at": graph.expires_at.isoformat() if graph.expires_at else None,
            },
            "binding": {
                "current_id": "fixed-current",
                "version_id": str(row.id),
                "revision": row.revision,
                "origin_version_id": str(row.id),
                "origin_revision": 1,
                "fixed_request": {"roots": [ref.model_dump(mode="json")]},
            },
            "material_sha256": "a" * 64,
            "dependency_epoch": 7,
            "sources": [source.model_dump(mode="json")],
            "publisher_access_sha256": "b" * 64,
        }
        # Deliberately no real CoverageRead/token: this is an explicit IO substitute.
        value = SimpleNamespace(
            source_basis=basis,
            valid_until=min(state.until, graph.expires_at) if graph.expires_at else state.until,
            coverage=tuple(
                Coverage(node=ref, facet=facet, status="complete", source=source)
                for facet in get_args(Facet)
            ),
            sources=(source,),
            required_source_read_set=tuple(reads),
        )
        state.owner_returns.append(value)
        return value

    def substitute_refresh(s, caller, pid, operation, bound):
        state.trace.append("full_owner_refresh")
        if bound.coverage is not None:
            assert (
                bound.graph.expires_at.isoformat() if bound.graph.expires_at else None
            ) == bound.coverage.source_basis["graph"]["expires_at"]
            assert bound.coverage is state.owner_returns[-1]
        candidate._valid_at(bound, state.at)

    def final_current(*args, **kwargs):
        state.trace.append("fresh_current")
        return SimpleNamespace(), state.version

    def late_access(*args, **kwargs):
        state.trace.append("late_access")
        assert "full_flush" in state.trace
        if state.access_fault is not None:
            state.access_fault()
        return state.until

    real_response = candidate._capture_response

    def response(*args, **kwargs):
        state.responded += 1
        state.trace.append("return_capture")
        return real_response(*args, **kwargs)

    for name, value in {
        "now": lambda: state.at,
        "_human": lambda *args, **kwargs: None,
        "_version": lambda *args: row,
        "_snapshot": lambda value: request,
        "_scope_seed": lambda *args: (scope, "pure-purpose"),
        "_authority": lambda *args, **kwargs: deepcopy(authority),
        "_runtime_stamp": lambda *args: state.runtime,
        "OwnerReader": lambda *args: reader,
        "_issue_loader": lambda *args: None,
        "capture_graph": graph_builder,
        "_evidence": lambda *args, **kwargs: ({}, False, set()),
        "_refresh": substitute_refresh,
        "_current": lambda *args, **kwargs: (SimpleNamespace(), row),
        "_capture_response": response,
    }.items():
        monkeypatch.setattr(candidate, name, value)
    monkeypatch.setattr(closure, "lock_dependency_clock", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        closure, "closure_stamp", lambda *args, **kwargs: deepcopy(state.clock_stamp)
    )
    monkeypatch.setattr(formal, "current_fixed", final_current)
    monkeypatch.setattr(owner, "_fresh_selects", lambda *args: nullcontext())
    monkeypatch.setattr(owner, "_people_fence", lambda *args: nullcontext())
    monkeypatch.setattr(owner, "quiet", lambda *args: None)
    monkeypatch.setattr(owner, "pointer", lambda *args: (SimpleNamespace(), SimpleNamespace()))
    monkeypatch.setattr(owner, "read", substitute_owner_read)
    monkeypatch.setattr(owner, "recheck_access", late_access)
    payload = candidate.GraphCaptureInput(
        capture_key="pure-capture-original-key",
        change_id=request.id,
        expected_change_revision=1,
        reason="Pure candidate control flow only",
    )
    state.s, state.ctx, state.pid, state.payload = session, ctx, scope.product_id, payload
    state.row = row
    state.call = lambda: candidate.prepare_capture(session, ctx, scope.product_id, payload)
    return state


def test_new_capture_reads_owner_once_and_keeps_fact_interval_separate(boundary):
    value = boundary.call()["capture"]
    assert len(boundary.read_graphs) == 1
    final = boundary.read_graphs[0]
    assert final.expires_at is None
    assert boundary.owner_returns[0].valid_until == boundary.until
    saved = boundary.s.rows[-1]
    assert saved.expires_at == final.expires_at
    assert value["graph"]["expires_at"] == final.model_dump(mode="json")["expires_at"]
    assert saved.source_basis["coverage"] == boundary.owner_returns[-1].source_basis
    assert saved.source_basis["coverage"]["graph"]["expires_at"] is None
    assert boundary.trace.index("full_flush") < boundary.trace.index("late_access")
    assert boundary.trace.index("late_access") < boundary.trace.index("fresh_current")
    assert boundary.trace[-1] == "return_capture"


@pytest.mark.parametrize("drift", ["current", "clock", "coverage_interval"])
def test_final_access_sql_cannot_hide_changed_current_watermark_or_fact_interval(boundary, drift):
    def mutate():
        if drift == "current":
            boundary.version = SimpleNamespace(id=uuid4(), revision=2)
        elif drift == "clock":
            boundary.clock_stamp["epoch"] += 1
        else:
            boundary.at = boundary.until

    boundary.access_fault = mutate
    with pytest.raises(DomainError) as failure:
        boundary.call()
    assert (
        failure.value.reason
        == {
            "current": "VERSION_CONFLICT",
            "clock": "RECHECK_REQUIRED",
            "coverage_interval": "COVERAGE_OWNER_STALE",
        }[drift]
    )
    assert "full_flush" in boundary.trace and "late_access" in boundary.trace
    assert boundary.responded == 0
    # This no-I/O adapter cannot demonstrate rollback; real PG tests cover it.


def test_longer_material_does_not_add_an_unnecessary_preliminary_graph_read(boundary):
    boundary.until = boundary.at + timedelta(minutes=20)
    value = boundary.call()["capture"]
    assert len(boundary.read_graphs) == 1
    assert (
        value["graph"]["expires_at"]
        == boundary.read_graphs[0].model_dump(mode="json")["expires_at"]
    )
    assert boundary.s.rows[-1].expires_at is None
    assert boundary.trace.index("full_flush") < boundary.trace.index("late_access")


def test_absent_owner_keeps_new_unknown_capture_window(boundary, monkeypatch):
    monkeypatch.setattr(owner, "pointer", lambda *args: (None, None))
    value = boundary.call()["capture"]
    assert not boundary.read_graphs and "late_access" not in boundary.trace
    assert all(row["status"] == "unknown" for row in value["graph"]["coverage"])
    assert boundary.s.rows[-1].expires_at is None
    assert "coverage" not in boundary.s.rows[-1].source_basis


def test_existing_complete_key_keeps_original_graph_and_window(boundary):
    original = boundary.call()
    boundary.s.old = boundary.s.rows[-1]
    saved = deepcopy({k: v for k, v in boundary.s.old.__dict__.items() if not k.startswith("_sa_")})
    boundary.trace.clear()
    boundary.read_graphs.clear()
    boundary.owner_returns.clear()
    boundary.at += timedelta(seconds=1)
    replay = boundary.call()
    assert replay == original
    assert len(boundary.read_graphs) == 1 and "full_flush" not in boundary.trace
    assert {k: v for k, v in boundary.s.old.__dict__.items() if not k.startswith("_sa_")} == saved


def test_old_unknown_is_never_overwritten_by_new_complete_owner(boundary):
    boundary.call()
    old = boundary.s.rows[-1]
    graph = boundary.read_graphs[-1]
    old.graph_snapshot = graph.model_dump(mode="json")
    old.graph_sha256 = candidate.digest(graph)
    old.source_basis.pop("coverage")
    boundary.s.old = old
    saved = deepcopy({k: v for k, v in old.__dict__.items() if not k.startswith("_sa_")})
    count = len(boundary.s.rows)
    boundary.trace.clear()
    boundary.read_graphs.clear()
    boundary.owner_returns.clear()
    with pytest.raises(DomainError) as failure:
        boundary.call()
    assert failure.value.code == "SOURCE_STALE"
    assert {k: v for k, v in old.__dict__.items() if not k.startswith("_sa_")} == saved
    assert len(boundary.s.rows) == count
    assert "full_flush" not in boundary.trace


@pytest.mark.parametrize("failure_mode", ["publisher", "current", "clock", "runtime", "expiry"])
def test_post_full_flush_failure_cannot_return_a_capture(boundary, monkeypatch, failure_mode):
    def fail_access(*args, **kwargs):
        boundary.trace.append("late_access")
        assert "full_flush" in boundary.trace
        raise DomainError("COVERAGE_OWNER_STALE", "Pure substituted late publisher revocation", 403)

    if failure_mode == "publisher":
        monkeypatch.setattr(owner, "recheck_access", fail_access)
    else:

        def flush_fault():
            if failure_mode == "current":
                boundary.version = SimpleNamespace(id=uuid4(), revision=2)
            elif failure_mode == "clock":
                boundary.clock_stamp["epoch"] += 1
            elif failure_mode == "runtime":
                boundary.runtime = "changed-after-real-full-flush-substitute"
            else:
                boundary.at = boundary.until

        boundary.flush_fault = flush_fault
    with pytest.raises(DomainError):
        boundary.call()
    assert "full_flush" in boundary.trace and boundary.responded == 0
    assert "return_capture" not in boundary.trace
    # No fake rollback claim: Root must verify whole real tenant_session rollback.


def test_final_source_read_rejection_occurs_before_staging(boundary, monkeypatch):
    def stale_read(*args, **kwargs):
        raise DomainError("COVERAGE_OWNER_STALE", "Pure source withdrawal during owner read")

    monkeypatch.setattr(owner, "read", stale_read)
    with pytest.raises(DomainError):
        boundary.call()
    assert not boundary.s.rows and "full_flush" not in boundary.trace and boundary.responded == 0
