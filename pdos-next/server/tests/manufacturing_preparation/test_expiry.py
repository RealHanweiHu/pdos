"""No-connect post-owner timing regressions; owner IO is an explicit substitute."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import make_transient_to_detached
from sqlalchemy.orm.attributes import set_committed_value

from pdos_next.domain.manufacturing_baseline import service
from pdos_next.errors import DomainError
from pdos_next.models import Product

from .test_preparation import frame


def phase_frame(monkeypatch):
    f = frame()
    product = Product(
        id=f.pid, tenant_id=f.tenant, owner_id=f.actor, name="no-connect substitute", revision=4
    )
    make_transient_to_detached(product)
    f.s.add(product)
    service.configure(f.engine)
    bound = service.Bound(
        SimpleNamespace(purpose="precise source-bound purpose"),
        None,
        None,
        {"status": "draft"},
        [],
        {"explicit_owner_substitute": True},
        {"valid_until": (datetime.now(UTC) + timedelta(minutes=2)).isoformat()},
        None,
        {},
        "test-runtime",
    )
    monkeypatch.setattr(service, "_runtime", lambda s: "test-runtime")
    monkeypatch.setattr(service, "_load", lambda *a, **k: bound)
    monkeypatch.setattr(service, "_cas", lambda *a: None)
    monkeypatch.setattr(service, "_refresh", lambda *a: bound)
    return f, product, bound


def authority_result(f, project, at):
    return {
        "scope": {
            "tenant_id": str(f.tenant),
            "product_id": str(f.pid),
            "project_id": str(project.id),
        },
        "subject_id": str(f.actor),
        "operation": f.command.operation,
        "purpose": project.purpose,
        "authorized": True,
        "qualified": True,
        "roles": ["manufacturing"],
        "reason_codes": [],
        "valid_until": (at + timedelta(hours=1)).isoformat(),
        "required_source_read_set": [],
        "facts_revision": "unchanged actual owner material",
    }


@pytest.mark.parametrize("boundary", ["valid_from", "valid_until"])
def test_future_scope_boundary_is_retained_without_rewriting_actual_assessment(
    monkeypatch, boundary
):
    f = frame()
    project = SimpleNamespace(id=f.payload.project_id, purpose="actual purpose")
    at = datetime.now(UTC)
    expected = at + timedelta(seconds=2)
    value = authority_result(f, project, at)
    fact = SimpleNamespace(
        valid_from=at - timedelta(minutes=1), valid_until=at + timedelta(hours=2)
    )
    setattr(fact, boundary, expected)
    monkeypatch.setattr(service, "now", lambda: at)
    monkeypatch.setattr(service.professional, "assess", lambda *a, **k: value)
    queries = []

    def rows(query):
        queries.append(str(query.compile(dialect=postgresql.dialect())))
        return [fact]

    f.s.scalars = rows  # No database; explicit complete scope owner substitute.
    result, deadline = service._authority(f.s, f.ctx, f.command, project)
    assert result is value and result["valid_until"] == (at + timedelta(hours=1)).isoformat()
    assert deadline == expected
    assert (
        "subject_id" in queries[0] and "project_id IS NULL" in queries[0] and "LIMIT" in queries[0]
    )
    with pytest.raises(DomainError) as error:
        service._deadline(result, expected, deadline)
    assert error.value.code == "SOURCE_STALE"


def test_future_negative_activation_crossed_during_actual_scope_query_is_rejected(monkeypatch):
    f = frame()
    project = SimpleNamespace(id=f.payload.project_id, purpose="actual purpose")
    clock = [datetime.now(UTC)]
    initial = clock[0]
    value = authority_result(f, project, initial)
    fact = SimpleNamespace(
        valid_from=initial + timedelta(seconds=1), valid_until=initial + timedelta(hours=2)
    )
    monkeypatch.setattr(service, "now", lambda: clock[0])
    monkeypatch.setattr(service.professional, "assess", lambda *a, **k: value)

    def owner_io(query):
        clock[0] = initial + timedelta(seconds=2)
        return [fact]

    f.s.scalars = owner_io
    with pytest.raises(DomainError) as error:
        service._authority(f.s, f.ctx, f.command, project)
    assert error.value.code == "SOURCE_STALE"


@pytest.mark.parametrize("fault", ["limit", "naive"])
def test_scope_deadline_cannot_be_unbounded_or_naive(monkeypatch, fault):
    f = frame()
    project = SimpleNamespace(id=f.payload.project_id, purpose="actual purpose")
    at = datetime.now(UTC)
    monkeypatch.setattr(service, "now", lambda: at)
    monkeypatch.setattr(
        service.professional, "assess", lambda *a, **k: authority_result(f, project, at)
    )
    fact = SimpleNamespace(
        valid_from=at.replace(tzinfo=None) if fault == "naive" else at,
        valid_until=at + timedelta(hours=2),
    )
    f.s.scalars = lambda q: [fact] * (1001 if fault == "limit" else 1)
    with pytest.raises(DomainError) as error:
        service._authority(f.s, f.ctx, f.command, project)
    assert error.value.code == (
        "PROFESSIONAL_SCOPE_LIMIT" if fault == "limit" else "INTEGRITY_MISMATCH"
    )


def test_source_io_cannot_pass_previously_active_authority_after_future_boundary(monkeypatch):
    f, product, _ = phase_frame(monkeypatch)
    clock = [datetime.now(UTC)]
    deadline = clock[0] + timedelta(seconds=1)
    project = SimpleNamespace(
        id=f.payload.project_id, purpose="actual purpose", visibility="private"
    )
    link = SimpleNamespace(definition_id=uuid4(), definition_revision=1)
    definition = {
        "visibility": "private",
        "source_status": "current",
        "sources": [{**f.payload.sources[0].model_dump(mode="json"), "status": "active"}],
    }
    process = SimpleNamespace(
        revision=1,
        engineering_configuration_id=uuid4(),
        required_source_read_set=[],
        visibility="private",
    )
    engineering = SimpleNamespace(
        definition_id=link.definition_id,
        definition_revision=1,
        required_source_read_set=[],
        visibility="private",
    )
    authority = authority_result(f, project, clock[0])
    monkeypatch.setattr(service, "now", lambda: clock[0])
    monkeypatch.setattr(service.configurations, "_human", lambda *a: None)
    monkeypatch.setattr(service.projects, "_project", lambda *a: (project, link, definition))
    monkeypatch.setattr(
        service.configurations, "get_process", lambda *a: (process, {"source_status": "current"})
    )
    monkeypatch.setattr(service.configurations, "_row", lambda *a: engineering)
    monkeypatch.setattr(service, "check_material", lambda *a: [])
    monkeypatch.setattr(service, "_authority", lambda *a, **k: (authority, deadline))
    monkeypatch.setattr(service, "require_access", lambda *a, **k: None)

    def source_io(*args):
        clock[0] = deadline
        return {}, False, None

    monkeypatch.setattr(service.evidence, "_evidence", source_io)
    with pytest.raises(DomainError) as error:
        service._load_fixed(f.s, f.ctx, f.command, product, f.payload)
    assert error.value.code == "SOURCE_STALE"
    assert not any(isinstance(v, service.PreparationVersion) for v in f.s.new)


@pytest.mark.parametrize("fault", ["confirmation", "authority", "current", "uow"])
def test_previous_current_io_precedes_last_live_clock_and_no_write_on_drift(monkeypatch, fault):
    f, product, original = phase_frame(monkeypatch)
    clock = [datetime.now(UTC)]
    until = (
        clock[0] + timedelta(hours=1)
        if fault == "confirmation"
        else clock[0] + timedelta(seconds=10)
    )
    previous = SimpleNamespace(id=uuid4(), series_id=uuid4(), revision=1)
    bound = replace(
        original,
        previous=previous,
        authority={"valid_until": (clock[0] + timedelta(hours=2)).isoformat()},
        authority_deadline=until,
    )
    monkeypatch.setattr(service, "_refresh", lambda *a: bound)
    monkeypatch.setattr(service, "now", lambda: clock[0])
    phase = service.Prepared(service._CAPABILITY, f.s, f.ctx, f.command, product, f.payload, bound)
    set_committed_value(f.proof, "snapshot", phase.review)
    binding = service.bind_consumption(f.s, f.ctx, f.command, product, f.payload, phase, f.proof)
    f.proof.consumed = True
    marker = service.record_consumption(
        f.s, f.ctx, f.command, product, f.payload, phase, f.proof, binding
    )
    events = []

    def pointer_io(*args, **kwargs):
        events.append("pointer_io")
        if fault == "confirmation":
            clock[0] = marker.expires_at
        elif fault == "authority":
            clock[0] = until
        elif fault == "uow":
            f.s.flush = lambda *a, **k: None  # Actual SAVEPOINT object, explicit no-SQL flush.
            f.s.begin_nested()
        return SimpleNamespace(
            version_id=uuid4() if fault == "current" else previous.id, revision=1
        )

    monkeypatch.setattr(service, "_pointer", pointer_io)
    original_live = service._host(f.s).require_live

    def live(*args, **kwargs):
        events.append("require_live")
        return original_live(*args, **kwargs)

    monkeypatch.setattr(service._host(f.s), "require_live", live)
    with pytest.raises(DomainError) as error:
        service.apply_prepared_write(
            f.s, f.ctx, f.command, product, f.payload, phase, consumption=(binding, marker)
        )
    assert events[0] == "pointer_io"
    assert (
        error.value.code
        == {
            "confirmation": "CONFIRMATION_REQUIRED",
            "authority": "SOURCE_STALE",
            "current": "VERSION_CONFLICT",
            "uow": "FACT_CALLER_UOW_CHANGED",
        }[fault]
    )
    assert not any(isinstance(v, service.PreparationVersion) for v in f.s.new)


def test_actual_first_consumption_clock_precedes_phase_hashing_and_repeat_never_renews(monkeypatch):
    f, product, _ = phase_frame(monkeypatch)
    phase, review = service.prepare_write_review(f.s, f.ctx, f.command, product, f.payload)
    set_committed_value(f.proof, "snapshot", review)
    binding = service.bind_consumption(f.s, f.ctx, f.command, product, f.payload, phase, f.proof)
    f.proof.consumed = True
    events = []
    capture = service._host(f.s).capture_after_transition
    actual_phase = service._phase

    def capture_first(*args, **kwargs):
        result = capture(*args, **kwargs)
        events.append(("capture", result.consumed_at))
        return result

    def later_phase(*args):
        events.append(("phase", datetime.now(UTC)))
        return actual_phase(*args)

    monkeypatch.setattr(service._host(f.s), "capture_after_transition", capture_first)
    monkeypatch.setattr(service, "_phase", later_phase)
    first = service.record_consumption(
        f.s, f.ctx, f.command, product, f.payload, phase, f.proof, binding
    )
    again = service.record_consumption(
        f.s, f.ctx, f.command, product, f.payload, phase, f.proof, binding
    )
    assert [v[0] for v in events] == ["capture", "phase", "capture", "phase"]
    assert first is again and first.consumed_at == events[0][1] <= events[1][1]


def test_previous_pointer_is_loaded_once_before_saved_clock_then_only_updated(monkeypatch):
    f, product, original = phase_frame(monkeypatch)
    clock = [datetime.now(UTC)]
    previous = SimpleNamespace(id=uuid4(), series_id=uuid4(), revision=1)
    bound = replace(original, previous=previous, authority_deadline=clock[0] + timedelta(minutes=1))
    monkeypatch.setattr(service, "_refresh", lambda *a: bound)
    monkeypatch.setattr(service, "now", lambda: clock[0])
    phase = service.Prepared(service._CAPABILITY, f.s, f.ctx, f.command, product, f.payload, bound)
    set_committed_value(f.proof, "snapshot", phase.review)
    binding = service.bind_consumption(f.s, f.ctx, f.command, product, f.payload, phase, f.proof)
    f.proof.consumed = True
    marker = service.record_consumption(
        f.s, f.ctx, f.command, product, f.payload, phase, f.proof, binding
    )
    pointer = SimpleNamespace(version_id=previous.id, revision=1)
    io_clocks = []

    def current_io(*a, **k):
        clock[0] += timedelta(seconds=1)
        io_clocks.append(clock[0])
        return pointer

    monkeypatch.setattr(service, "_pointer", current_io)
    f.s.flush = lambda *a, **k: None  # Row staging only; no SQL/constraint attestation.
    row, family, _ = service.apply_prepared_write(
        f.s, f.ctx, f.command, product, f.payload, phase, consumption=(binding, marker)
    )
    assert len(io_clocks) == 1 and row.created_at == io_clocks[0]
    assert (row.previous_id, row.previous_revision, row.revision) == (previous.id, 1, 2)
    assert (pointer.version_id, pointer.revision) == (row.id, 2)
    assert family == "work_instruction" and row.status == "draft"
