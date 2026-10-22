"""No-connect owner checks; the single helper SQL result is an explicit substitute."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_participants_owner import RawSession, reader, saved_group
from test_participants_owner import work as work

from pdos_next import request_proof
from pdos_next import service as common
from pdos_next.domain.capa_effectiveness import participants_owner as owner
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Grant, Outbox, Principal, RequestKey


def peer_group(work, *, readable_key=False):
    subject, receipt, audit, outbox = saved_group(work)
    peer = uuid4()
    hidden_key = deepcopy(work.s.rows[RequestKey.__tablename__][0])
    for row in (receipt, audit, outbox):
        row["actor_id"] = peer
    receipt["requester_id"] = peer
    if readable_key:
        work.s.rows[RequestKey.__tablename__][0]["actor_id"] = peer
    else:
        work.s.rows[RequestKey.__tablename__].clear()
    return SimpleNamespace(
        subject=subject,
        receipt=receipt,
        audit=audit,
        outbox=outbox,
        peer=peer,
        hidden_key=hidden_key,
        event=common.EVENTS[subject["operation"]],
    )


@pytest.fixture
def binding(work, monkeypatch):
    """Only replace the scalar-function query; all old Core/ACL reads stay real."""
    assert isinstance(work.s, RawSession)
    original = request_proof.snapshot_mappings
    probe = SimpleNamespace(rows=[{"bound": True}], calls=[])
    caller = deepcopy(vars(work.ctx))

    def mappings(session, statement, *, scope_id=None):
        if tuple(statement.selected_columns.keys()) != ("bound",):
            return original(session, statement, scope_id=scope_id)
        assert session is work.s and scope_id == work.pid
        assert vars(work.ctx) == caller
        assert statement.get_execution_options()["autoflush"] is False
        assert statement.get_execution_options()["populate_existing"] is True
        values = {str(value) for value in statement.compile().params.values()}
        assert str(work.ctx.tenant_id) in values and str(work.pid) in values
        probe.calls.append(statement)
        return deepcopy(probe.rows)

    monkeypatch.setattr(request_proof, "snapshot_mappings", mappings)
    return probe


def read_group(work, group):
    raw = reader(work)
    ref = raw.group(group.subject, "quality_issue", group.peer, group.event)
    return raw, ref


def test_peer_hidden_key_uses_only_actual_boolean_binding_without_key_or_caller_leak(work, binding):
    group = peer_group(work)
    original_caller = deepcopy(vars(work.ctx))
    original_transaction = work.s.get_transaction()
    raw, ref = read_group(work, group)
    assert ref.id == group.receipt["id"] and ref.kind == "domain"
    assert len(binding.calls) == 1
    statement = binding.calls[0]
    assert str(group.receipt["id"]) in {str(value) for value in statement.compile().params.values()}
    assert [(query, old) for query, old in raw.tracked if query is statement] == [
        (statement, {"bound": True})
    ]
    marks = [row["receipt_request_binding"] for row in raw.rows if "receipt_request_binding" in row]
    assert len(marks) == 1 and set(marks[0]) == {"receipt_id", "bound"}
    assert str(marks[0]["receipt_id"]) == str(group.receipt["id"])
    assert marks[0]["bound"] is True
    assert not any(row.get("table") == RequestKey.__tablename__ for row in raw.rows)
    serialized = json.dumps(raw.rows, default=str)
    assert str(group.hidden_key["id"]) not in serialized
    assert group.hidden_key["key"] not in serialized
    raw.finish()
    assert binding.calls == [statement, statement]
    assert raw.ctx is work.ctx and vars(work.ctx) == original_caller
    assert work.ctx.actor_id == work.ctx.requester_id == work.actor != group.peer
    assert work.s.get_transaction() is original_transaction and not work.s.new
    assert work.s.rows[RequestKey.__tablename__] == []


def test_own_actor_missing_key_is_rejected_without_boolean_fallback(work, binding):
    subject, receipt, _audit, _outbox = saved_group(work)
    work.s.rows[RequestKey.__tablename__].clear()
    raw = reader(work)
    with pytest.raises(DomainError) as error:
        raw.group(subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]])
    assert error.value.reason == "PARTICIPANT_REQUEST_ASSOCIATION_MISSING"
    assert receipt["actor_id"] == work.ctx.actor_id and not binding.calls


@pytest.mark.parametrize(
    "rows",
    [
        [{"bound": False}],
        [{"bound": None}],
        [{"bound": 1}],
        [],
        [{"bound": True, "key": "must-not-be-exported"}],
        [{"bound": True}, {"bound": True}],
    ],
    ids=["false", "none", "integer-one", "missing", "extra-private-field", "duplicate"],
)
def test_peer_requires_one_exact_true_binding_not_truthiness_or_extra_fields(work, binding, rows):
    group = peer_group(work)
    binding.rows = rows
    raw = reader(work)
    with pytest.raises(DomainError) as error:
        raw.group(group.subject, "quality_issue", group.peer, group.event)
    assert error.value.reason == "PARTICIPANT_REQUEST_ASSOCIATION_MISSING"
    assert len(binding.calls) == 1
    assert not any("receipt_request_binding" in row for row in raw.rows)


@pytest.mark.parametrize("peer", [False, True], ids=["own-actor", "peer-readable-key"])
def test_a_real_readable_request_key_keeps_the_existing_tracked_path(work, binding, peer):
    if peer:
        group = peer_group(work, readable_key=True)
        raw, _ref = read_group(work, group)
    else:
        subject, _receipt, _audit, _outbox = saved_group(work)
        raw = reader(work)
        raw.group(subject, "quality_issue", work.actor, common.EVENTS[subject["operation"]])
    actual = work.s.rows[RequestKey.__tablename__][0]
    assert [row["value"] for row in raw.rows if row.get("table") == RequestKey.__tablename__] == [
        actual
    ]
    assert not any("receipt_request_binding" in row for row in raw.rows)
    raw.finish()
    assert binding.calls == []


@pytest.mark.parametrize(
    "fault", ["audit_actor", "audit_operation", "outbox_event", "outbox_command"]
)
def test_peer_true_binding_does_not_replace_actual_audit_and_outbox_checks(work, binding, fault):
    group = peer_group(work)
    if fault == "audit_actor":
        group.audit["actor_id"] = work.actor
    elif fault == "audit_operation":
        group.audit["operation"] = "quality.issue.create"
    elif fault == "outbox_event":
        group.outbox["type"] = "other.saved"
    else:
        group.outbox["correlation_id"] = uuid4()
    with pytest.raises(DomainError) as error:
        read_group(work, group)
    assert error.value.reason == "PARTICIPANT_ATOMIC_GROUP_MISMATCH"
    assert len(binding.calls) == 1


@pytest.mark.parametrize(
    "rows",
    [[{"bound": False}], [{"bound": None}], [{"bound": 1}], []],
    ids=["false", "none", "integer-one", "missing"],
)
def test_finish_independently_requires_the_same_boolean_statement_to_remain_exact_true(
    work, binding, rows
):
    group = peer_group(work)
    raw, _ref = read_group(work, group)
    first = binding.calls[0]
    binding.rows = rows
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "PARTICIPANT_OWNER_CHANGED"
    assert binding.calls == [first, first]


def test_finish_still_rereads_every_earlier_actual_group_row(work, binding):
    group = peer_group(work)
    raw, _ref = read_group(work, group)
    group.audit["actor_id"] = uuid4()
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "PARTICIPANT_OWNER_CHANGED"
    assert len(binding.calls) == 2


def test_finish_rechecks_real_caller_acl_after_peer_binding(work, binding):
    group = peer_group(work)
    raw, _ref = read_group(work, group)
    work.grant["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        raw.finish()
    assert error.value.reason == "FORBIDDEN_SCOPE" and error.value.status == 403
    assert len(binding.calls) == 2


def test_finish_keeps_the_original_uow_and_never_borrows_the_peer_context(work, binding):
    group = peer_group(work)
    raw, _ref = read_group(work, group)
    # A peer can have a real grant; that must not replace the captured caller/UOW.
    work.s.seed(Principal, id=group.peer, tenant_id=work.ctx.tenant_id, kind="human", active=True)
    work.s.seed(
        Grant,
        id=uuid4(),
        tenant_id=work.ctx.tenant_id,
        category_id=work.ctx.category_id,
        principal_id=group.peer,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    work.s.rollback()
    with pytest.raises(DomainError):
        raw.finish()
    assert raw.ctx is work.ctx and work.ctx.actor_id == work.actor
    assert work.ctx.actor_id != group.peer


def test_direct_companions_retains_the_same_peer_request_binding_contract(work, binding):
    group = peer_group(work)
    raw = owner._Read(work.s, work.ctx, work.pid, work.origin)
    raw.companions(group.receipt, group.event)
    assert len(binding.calls) == 1
    raw.finish()
    assert len(binding.calls) == 2
    assert any(row.get("table") == Audit.__tablename__ for row in raw.rows)
    assert any(row.get("table") == Outbox.__tablename__ for row in raw.rows)
