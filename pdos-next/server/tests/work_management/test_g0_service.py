"""Native G0 declarations reuse task transitions without implying acceptance."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.contracts import Command
from pdos_next.domain.work_management import rules, service
from pdos_next.domain.work_management.constants import ACCEPT, COMMIT, CREATE, STATUS
from pdos_next.domain.work_management.schemas import PAYLOADS, TaskSnapshot
from pdos_next.errors import DomainError
from pdos_next.service import Context


def declaration(**overrides):
    return dict(
        project_id=uuid4(),
        sources=[],
        reason="Continue the original G0 arrangement",
        title="Investigate the actual open item",
        goal="Provide evidence of the result",
        outcomes=[dict(key="result", text="Evidence of the investigation", required=True)],
        g0_open_item=dict(id=uuid4(), decision_id=uuid4()),
        **overrides,
    )


def test_native_g0_is_an_exact_typed_source_not_a_fabricated_artifact():
    p = PAYLOADS[CREATE](**declaration())
    value = rules.transition(CREATE, p, actor_id=uuid4(), at=datetime.now(UTC), task_id=uuid4())
    assert value.g0_open_item == p.g0_open_item
    assert value.state == "proposed" and value.assignee_id is value.recipient_id is None
    with pytest.raises(ValidationError):
        PAYLOADS[CREATE](**{**declaration(), "g0_open_item": None})
    with pytest.raises(ValidationError):
        PAYLOADS[CREATE](**{**declaration(), "g0_open_item": dict(id=uuid4(), revision=1)})


def test_native_basis_does_not_loosen_result_or_non_task_evidence():
    from pdos_next.domain.work_management.schemas import Result

    for op, extra in [
        (STATUS, dict(fact_summary="A fact", next_steps="Read the original")),
        (
            COMMIT,
            dict(
                task=dict(id=uuid4(), revision=1),
                recipient_id=uuid4(),
                outcome_keys=["result"],
                promised_at=None,
                original_timezone="UTC",
            ),
        ),
    ]:
        with pytest.raises(ValidationError):
            PAYLOADS[op](
                project_id=uuid4(),
                sources=[],
                reason="Native basis is not original result evidence",
                **extra,
            )
    with pytest.raises(ValidationError):
        Result(key="result", text="Actual result", status="present", sources=[])


def test_legacy_task_snapshot_continues_with_an_explicit_nullable_native_origin():
    actor = uuid4()
    v = TaskSnapshot(
        task_id=uuid4(),
        revision=2,
        state="assigned",
        title="Legacy work",
        goal="Actual result",
        outcomes=[dict(key="result", text="Result", required=True)],
        assignee_id=actor,
        recipient_id=actor,
    ).model_dump()
    del v["g0_open_item"]
    p = PAYLOADS[ACCEPT](
        project_id=uuid4(),
        sources=[],
        reason="Legacy task is validated by service",
        task=dict(id=v["task_id"], revision=2),
    )
    result = rules.transition(ACCEPT, p, current=v, actor_id=actor, at=datetime.now(UTC))
    assert result.g0_open_item is None and result.state == "accepted"


def test_empty_task_sources_require_the_actual_existing_native_basis(monkeypatch):
    actor, tenant, category, pid, project_id, tid = (uuid4() for _ in range(6))
    ctx = Context(tenant, actor, actor, category_id=category)
    task = TaskSnapshot(
        task_id=tid,
        revision=2,
        state="assigned",
        title="Work",
        goal="Evidence",
        outcomes=[dict(key="result", text="Result", required=True)],
        assignee_id=actor,
        recipient_id=actor,
    )
    row = SimpleNamespace(project_id=project_id, source_basis={"artifacts": []})
    monkeypatch.setattr(
        service.owner,
        "project",
        lambda *a, **kw: SimpleNamespace(
            id=project_id, owner_id=actor, revision=1, name="Project", visibility="private"
        ),
    )
    monkeypatch.setattr(service.owner, "task", lambda *a, **kw: (row, task, object()))
    monkeypatch.setattr(service.owner, "sources_current", lambda *a, **kw: True)
    monkeypatch.setattr(service, "human", lambda *a, **kw: None)
    p = PAYLOADS[ACCEPT](
        project_id=project_id,
        sources=[],
        reason="Actual native basis required",
        task=dict(id=tid, revision=2),
    )
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=ACCEPT,
        category_id=category,
        product_id=pid,
        expected_revision=1,
        payload=p.model_dump(mode="json"),
    )

    class Uow:
        info = {}

        def get_transaction(self):
            return self

    with pytest.raises(DomainError) as error:
        service.validate(Uow(), ctx, command, SimpleNamespace(id=pid, revision=1), p)
    assert error.value.code == "MISSING_REQUIRED_EVIDENCE"
