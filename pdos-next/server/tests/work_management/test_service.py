"""Actual work/common functions with explicit no-IO owner/proof substitutes.

No substitute establishes DB ownership, caller qualification or a consumed SQL
transaction. The PG test owns those checks; these exercise contract boundaries.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.work_management import service
from pdos_next.domain.work_management.constants import START, SUBMIT
from pdos_next.domain.work_management.schemas import PAYLOADS, TaskSnapshot, TimeFact
from pdos_next.errors import DomainError

AT = datetime(2026, 10, 18, tzinfo=UTC)


class NoIO:
    def __init__(self):
        self.info = {}
        self.transaction = object()

    def get_transaction(self):
        return self.transaction

    def __getattr__(self, name):
        raise AssertionError(f"Pure work test must not perform Session.{name}")


@pytest.fixture
def case(monkeypatch):
    tenant, category, actor, pid, project_id, task_id, source_id = (uuid4() for _ in range(7))
    ctx = common.Context(tenant, actor, actor, category_id=category)
    product = SimpleNamespace(id=pid, revision=1)
    project = SimpleNamespace(
        id=project_id, revision=1, name="Synthetic project", owner_id=actor, visibility="category"
    )
    source = {
        "id": str(source_id),
        "revision": 1,
        "kind": "artifact",
        "position": "line:1;quote_sha256:" + "a" * 64,
    }
    metadata = {
        "id": str(source_id),
        "revision": 1,
        "hash": "b" * 64,
        "owner_id": str(actor),
        "visibility": "category",
        "status": "active",
    }
    snapshot = TaskSnapshot(
        task_id=task_id,
        revision=3,
        state="accepted",
        title="Actual accepted task",
        goal="Keep separate results",
        outcomes=[{"key": "drawing", "text": "Fixed drawing", "required": True}],
        assignee_id=actor,
        recipient_id=actor,
    )
    row = SimpleNamespace(id=uuid4(), project_id=project_id, source_basis={"artifacts": [metadata]})
    calls = []

    def actual_project(s, context, product_id, identity, *, lock):
        assert context is ctx and product_id == pid and identity == project_id and lock
        calls.append("project")
        return project

    def actual_task(s, context, product_id, identity, *, revision, lock):
        assert context is ctx and product_id == pid and identity == task_id
        assert revision == snapshot.revision and lock
        calls.append("task")
        return row, snapshot, SimpleNamespace()

    def actual_sources(s, context, actual_product, refs, reads):
        assert context is ctx and actual_product is product
        expected = {(ref.id, ref.revision) for ref in refs}
        assert expected == {(value.artifact_id, value.expected_revision) for value in reads}
        calls.append("sources")
        return [metadata], False

    monkeypatch.setattr(service.owner, "project", actual_project)
    monkeypatch.setattr(service.owner, "task", actual_task)
    monkeypatch.setattr(service.owner, "sources_current", lambda *args: True)
    monkeypatch.setattr(service, "human", lambda *args: None)
    monkeypatch.setattr(service, "direct_source_basis", actual_sources)
    clock = [AT]
    monkeypatch.setattr(service, "now", lambda: clock[0])
    payload = PAYLOADS[START](
        project_id=project_id,
        task={"id": task_id, "revision": 3},
        actual_at=AT - timedelta(seconds=1),
        original_timezone="Asia/Shanghai",
        calendar_id=None,
        sources=[source],
        reason="Actual fixed request",
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=START,
        category_id=category,
        product_id=pid,
        expected_revision=1,
        source_read_set=[{"artifact_id": source_id, "expected_revision": 1}],
        payload=payload.model_dump(mode="json"),
    )
    return SimpleNamespace(**locals())


def test_real_t1_review_is_stable_across_server_record_times_and_common_recheck(case, monkeypatch):
    first = service.validate(NoIO(), case.ctx, case.command, case.product, case.payload)
    proof = SimpleNamespace(
        id=uuid4(),
        consumed=False,
        payload_digest=common.material_digest(case.ctx, case.command, case.payload, service),
        snapshot=deepcopy(first.review),
    )
    case.clock[0] += timedelta(seconds=9)
    session = NoIO()
    second = service.validate(session, case.ctx, case.command, case.product, case.payload)
    assert first.plan.actual_start.recorded_at != second.plan.actual_start.recorded_at
    assert first.plan.actual_start.actual_at == second.plan.actual_start.actual_at
    assert first.review == second.review
    assert "recorded_at" not in second.review["after"]["actual_start"]
    # The common function really recomputes reviewed_view; only persisted-proof
    # lookup is replaced, so an accidental volatile review fails consumption.
    monkeypatch.setattr(common, "material_confirmation_for", lambda *args: proof)
    assert (
        common.consume_material_confirmation(
            session, case.ctx, case.command, case.product, case.payload, service
        )
        is proof
    )
    assert proof.consumed is True


def test_validate_reuses_only_the_same_unconsumed_uow(case):
    session = NoIO()
    first = service.validate(session, case.ctx, case.command, case.product, case.payload)
    count = len(case.calls)
    assert service.validate(session, case.ctx, case.command, case.product, case.payload) is first
    assert len(case.calls) == count
    session.transaction = object()
    assert (
        service.validate(session, case.ctx, case.command, case.product, case.payload) is not first
    )
    assert len(case.calls) > count


def test_inputs_derives_reads_from_both_declaration_and_result_sources(case, monkeypatch):
    from pdos_next.schemas.verification.contracts import SourceRef

    extra = {**case.source, "id": str(uuid4())}
    value = PAYLOADS[SUBMIT](
        project_id=case.project_id,
        task={"id": case.task_id, "revision": 4},
        actual_at=AT,
        original_timezone="Asia/Shanghai",
        calendar_id=None,
        sources=[case.source],
        reason="Two explicit direct originals",
        results=[
            {"key": "drawing", "text": "Fixed result", "status": "present", "sources": [extra]}
        ],
    )
    command = case.command.model_copy(
        update={
            "operation": SUBMIT,
            "payload": value.model_dump(mode="json"),
            "source_read_set": [],
        }
    )
    expected = sorted(
        [{"artifact_id": entry["id"], "expected_revision": 1} for entry in (case.source, extra)],
        key=lambda entry: entry["artifact_id"],
    )
    captured = []

    def sources(s, ctx, product, refs, reads):
        captured.extend(refs)
        assert [read.model_dump(mode="json") for read in reads] == expected
        return [{**case.metadata, "id": str(ref.id)} for ref in refs], False

    snapshot = case.snapshot.model_copy(
        update={
            "state": "in_progress",
            "revision": 4,
            "actual_start": TimeFact(
                actual_at=AT - timedelta(seconds=2),
                original_timezone="Asia/Shanghai",
                calendar_id=None,
                actor_id=case.actor,
                recorded_at=AT - timedelta(seconds=1),
            ),
        }
    )
    monkeypatch.setattr(
        service.owner, "task", lambda *args, **kwargs: (case.row, snapshot, SimpleNamespace())
    )
    monkeypatch.setattr(service, "direct_source_basis", sources)
    monkeypatch.setattr(common, "command_scope", lambda *args, **kwargs: case.product)
    result = service.inputs(NoIO(), case.ctx, case.pid, command)
    assert result["required_source_read_set"] == expected
    assert set(captured) == {SourceRef.model_validate(case.source), SourceRef.model_validate(extra)}
    assert command.source_read_set == []


def test_finalize_propagates_late_source_failure_before_clearing_original_phase(case, monkeypatch):
    session = NoIO()
    value = service.validate(session, case.ctx, case.command, case.product, case.payload)
    value.used = True
    body = value.plan.model_dump(mode="json")
    receipt = SimpleNamespace(id=uuid4())
    subject = SimpleNamespace(
        _work_phase=value, receipt_id=receipt.id, body=body, body_sha256=common.digest(body)
    )

    def stale(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "Explicit late source withdrawal")

    monkeypatch.setattr(service.owner, "sources_current", stale)
    with pytest.raises(DomainError) as error:
        service.finalize_receipt(
            session, case.ctx, case.command, case.product, case.payload, subject, receipt
        )
    assert error.value.reason == "SOURCE_UNAVAILABLE"
    assert subject._work_phase is value
