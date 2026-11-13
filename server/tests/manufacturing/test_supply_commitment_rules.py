"""Supplier-commitment transitions as pure rules (D47, F25); no DB, model or network."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.manufacturing.supply_commitments import rules
from pdos_next.domain.manufacturing.supply_commitments.schemas import Payload
from pdos_next.errors import DomainError

AT = datetime(2026, 11, 8, 2, tzinfo=UTC)
OWNER, PEER, LEAD = uuid4(), uuid4(), uuid4()
SOURCE = {
    "kind": "artifact",
    "id": str(uuid4()),
    "revision": 1,
    "position": "line:1;quote_sha256:" + "a" * 64,
}


def build():
    return SimpleNamespace(id=uuid4(), revision=1, project_id=uuid4())


def create_payload(**values):
    record = {
        "action": "create",
        "build_id": str(uuid4()),
        "expected_build_revision": 1,
        "material_id": str(uuid4()),
        "supplier_ref": "ACME-01",
        "quantity": "30",
        "unit": "ea",
        "promised_at": "2026-11-20T09:00:00+08:00",
        "original_timezone": "Asia/Shanghai",
        "text": "Synthetic promise",
    }
    return {"statement": "Synthetic own statement", "record": record, **values}


def created(*, human=True, **values):
    return rules.transition(
        create_payload(**values),
        commitment_id=uuid4(),
        build=build(),
        actor_id=OWNER,
        requester_id=OWNER,
        maintainers={LEAD},
        at=AT,
        human_actor=human,
    )


def step(snapshot, record, *, requester=OWNER, human=True, **values):
    payload = {
        "commitment": {"id": str(snapshot.commitment_id), "revision": snapshot.revision},
        "statement": "Synthetic follow-up",
        "record": record,
        **values,
    }
    return rules.transition(
        payload,
        current=snapshot.model_dump(mode="json"),
        actor_id=requester,
        requester_id=requester,
        maintainers={LEAD},
        at=AT,
        human_actor=human,
    )


def test_check_is_one_day_after_the_promise_and_unknown_dates_have_none():
    snapshot = created()
    assert snapshot.check_at == snapshot.promised_at + timedelta(days=1)
    assert snapshot.time_basis == "human_recorded" and snapshot.responsible_id == OWNER
    undated = rules.transition(
        {**create_payload(), "record": {**create_payload()["record"], "promised_at": None}},
        commitment_id=uuid4(),
        build=build(),
        actor_id=OWNER,
        requester_id=OWNER,
        maintainers=set(),
        at=AT,
        human_actor=True,
    )
    assert undated.check_at is None
    assert rules.follow_up(undated, at=AT)["status"] == "date_unknown"
    assert rules.follow_up(snapshot, at=snapshot.check_at)["status"] == "check_due"
    assert rules.follow_up(snapshot, at=AT)["status"] == "pending"


def test_ai_must_cite_originals_and_never_uses_a_personal_statement():
    with pytest.raises(DomainError) as failure:
        created(human=False)
    assert failure.value.code == "MISSING_REQUIRED_EVIDENCE"
    snapshot = created(human=False, statement=None, sources=[SOURCE])
    assert snapshot.time_basis == "source_claim" and len(snapshot.sources) == 1


def test_only_the_recorder_or_build_and_project_owners_maintain_it():
    snapshot = created()
    revise = {
        "action": "revise",
        "promised_at": "2026-11-25T09:00:00+08:00",
        "original_timezone": "Asia/Shanghai",
        "text": "Synthetic new date",
    }
    with pytest.raises(DomainError) as failure:
        step(snapshot, revise, requester=PEER)
    assert failure.value.code == "FORBIDDEN_SCOPE"
    by_lead = step(snapshot, revise, requester=LEAD)
    assert by_lead.revision == 2 and by_lead.responsible_id == OWNER
    assert by_lead.quantity is None and by_lead.unit is None


def test_closed_commitments_reopen_explicitly_before_any_change():
    closed = step(created(), {"action": "close", "result": "Synthetic arrival recorded"})
    assert closed.state == "closed" and closed.last_closure.result
    with pytest.raises(DomainError):
        step(closed, {"action": "close", "result": "again"})
    with pytest.raises(ValidationError):
        Payload.model_validate(
            {
                "commitment": {"id": str(uuid4()), "revision": 2},
                "statement": "x",
                "record": {"action": "reopen"},
            }
        )
    reopened = step(closed, {"action": "reopen"}, reason="Synthetic remainder outstanding")
    assert reopened.state == "open" and reopened.revision == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"record": create_payload()["record"]},  # neither sources nor statement
        {**create_payload(), "record": {**create_payload()["record"], "unit": None}},
        {**create_payload(), "commitment": {"id": str(uuid4()), "revision": 1}},
        {**create_payload(), "sources": [{**SOURCE, "kind": "domain"}]},
    ],
)
def test_malformed_declarations_are_refused(payload):
    with pytest.raises(ValidationError):
        Payload.model_validate(payload)
