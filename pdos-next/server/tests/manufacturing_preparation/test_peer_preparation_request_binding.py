"""Actual retained-group checks with no-connect ORM SELECT substitutes.

The helper's scalar is explicit lower-level IO, not PG/RLS evidence. Real stored
command/body/material normalization and group guards execute unmodified. The
professional reader is an explicit boundary substitute, never a qualification.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators

from pdos_next.contracts import Command
from pdos_next.domain.manufacturing_baseline import models, rules, service
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey
from pdos_next.service import Context, digest, material_digest

from .test_preparation import material


class SelectSession(Session):
    """Only actual retained-group SELECT shapes; every connection is forbidden."""

    def __init__(self, engine):
        super().__init__(engine)
        self.rows, self.proof, self.queries = {}, None, []
        self.bound, self.binding_calls = True, []

    def get(self, model, identity, **kwargs):
        assert model is Confirmation
        return self.proof if self.proof is not None and self.proof.id == identity else None

    def scalars(self, statement, *args, **kwargs):
        assert statement.is_select
        self.queries.append(statement)
        model = statement.column_descriptions[0]["entity"]
        assert model in {Receipt, Audit, Outbox, RequestKey}
        rows = self.rows[model]
        for expression in statement._where_criteria:
            assert expression.operator is operators.eq and hasattr(expression.right, "value")
            rows = [
                row for row in rows if getattr(row, expression.left.key) == expression.right.value
            ]
        return rows

    def scalar(self, statement, *args, **kwargs):
        function = list(statement.selected_columns)[0].element
        assert function.name == "change_receipt_key_bound"
        assert function.packagenames == ("public",)
        assert statement.get_execution_options()["autoflush"] is False
        actual = tuple(value.value for value in function.clauses)
        self.binding_calls.append(actual)
        assert actual == (self.info["scope"][0], self.expected_product, self.expected_receipt)
        if isinstance(self.bound, Exception):
            raise self.bound
        return self.bound

    def flush(self, *args, **kwargs):
        raise AssertionError("Retained reading must not flush")


@pytest.fixture
def work(monkeypatch):
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connection(*_args):
        raise AssertionError("Pure retained-group tests must not connect")

    s = SelectSession(engine)
    s.begin()
    tenant, category, author, peer, pid = (uuid4() for _ in range(5))
    ctx = Context(tenant, peer, peer, category_id=category)
    payload = material(visibility="category")
    command = Command(
        command_id=uuid4(),
        idempotency_key="the original request key",
        operation="npi.work_instruction.record",
        category_id=category,
        product_id=pid,
        expected_revision=4,
        payload=payload.model_dump(mode="json"),
        source_read_set=rules.source_reads(payload),
    )
    at = datetime.now(UTC) - timedelta(seconds=1)
    review = {"actual": "explicit stored review IO substitute"}
    body = {
        "schema_version": service.SCHEMA_VERSION,
        "scope": {"project_id": str(payload.project_id), "purpose": "fixed project purpose"},
        "kind": "work_instruction",
        "status": "draft",
        "input": rules.semantic(payload),
    }
    row = models.PreparationVersion(
        id=uuid4(),
        tenant_id=tenant,
        product_id=pid,
        project_id=payload.project_id,
        kind="work_instruction",
        revision=1,
        owner_id=author,
        visibility="category",
        title=payload.title,
        process_id=payload.process.id,
        process_revision=payload.process.revision,
        operation_key=payload.operation_key,
        previous_id=None,
        previous_revision=None,
        purpose="fixed project purpose",
        purpose_sha256=digest("fixed project purpose"),
        operation=command.operation,
        intent_digest=digest("original common intent"),
        body=body,
        body_sha256=digest(body),
        input_snapshot={
            "command": service._saved_command(command),
            "semantic": rules.semantic(payload),
            "request_digest": service._request_digest(command, payload),
        },
        sources=rules.exact_sources(payload),
        required_source_read_set=rules.source_reads(payload),
        review=review,
        shared_proof_id=uuid4(),
        shared_proof_revision=4,
        proof_consumed_at=at - timedelta(microseconds=1),
        proof_expires_at=at + timedelta(minutes=1),
        token_sha256=digest("original shared T1 token"),
        material_sha256=material_digest(Context(tenant, author, author), command, payload, service),
        read_set_sha256=digest(
            [service.json_value(v) for v in service.canonical_reads(command.source_read_set)]
        ),
        authority_snapshot={"original_subject": str(author)},
        created_at=at,
    )
    s.proof = Confirmation(
        id=row.shared_proof_id,
        tenant_id=tenant,
        product_id=pid,
        actor_id=author,
        subject_id=pid,
        operation=command.operation,
        revision=4,
        consumed=True,
        token_hash=row.token_sha256,
        payload_digest=row.material_sha256,
        snapshot=review,
        created_at=at - timedelta(seconds=1),
        expires_at=row.proof_expires_at,
    )
    receipt = Receipt(
        id=uuid4(),
        tenant_id=tenant,
        product_id=pid,
        command_id=command.command_id,
        actor_id=author,
        requester_id=author,
        operation=row.operation,
        subject_type=row.kind,
        subject_id=row.id,
        subject_revision=1,
        visibility=row.visibility,
        intent_digest=row.intent_digest,
        request_digest=row.input_snapshot["request_digest"],
        run_id=None,
        result={"id": str(row.id), "revision": 1, "status": "draft"},
    )
    audit = Audit(
        id=uuid4(),
        tenant_id=tenant,
        receipt_id=receipt.id,
        actor_id=author,
        operation=row.operation,
    )
    outbox = Outbox(
        id=uuid4(),
        tenant_id=tenant,
        receipt_id=receipt.id,
        type=service.EVENTS[row.operation],
        actor_id=author,
        subject_id=row.id,
        subject_revision=1,
        correlation_id=command.command_id,
    )
    key = RequestKey(
        id=uuid4(),
        tenant_id=tenant,
        receipt_id=receipt.id,
        actor_id=author,
        key=command.idempotency_key,
        digest=receipt.request_digest,
    )
    s.rows = {Receipt: [receipt], Audit: [audit], Outbox: [outbox], RequestKey: [key]}
    s.expected_product, s.expected_receipt = pid, receipt.id
    value = SimpleNamespace(
        s=s,
        ctx=ctx,
        pid=pid,
        row=row,
        receipt=receipt,
        key=key,
        author=author,
        rechecks=[],
        current=True,
    )

    def recheck(session, caller, product, project, saved, *, at):
        assert session is s and caller is value.ctx
        assert (product, project, saved, at) == (
            pid,
            row.project_id,
            row.authority_snapshot,
            row.created_at,
        )
        assert s.info["scope"] == (
            caller.tenant_id,
            caller.actor_id,
            caller.requester_id,
            caller.category_id,
        )
        value.rechecks.append(caller)
        return {"current": value.current}

    monkeypatch.setattr(service, "_recheck", recheck)

    def read():
        s.info["scope"] = (
            value.ctx.tenant_id,
            value.ctx.actor_id,
            value.ctx.requester_id,
            value.ctx.category_id,
        )
        return service._retained_group(s, value.ctx, pid, row)

    value.read = read
    yield value
    s.close()
    engine.dispose()


def rejected(work, reason="STORED_ATOM_INCOMPLETE"):
    with pytest.raises(DomainError) as error:
        work.read()
    assert error.value.reason == reason
    assert not work.rechecks


@pytest.mark.parametrize("caller", ("author", "peer"))
def test_visible_exact_original_key_keeps_original_read_path(work, caller):
    if caller == "author":
        work.ctx = replace(work.ctx, actor_id=work.author, requester_id=work.author)
    work.s.bound = RuntimeError("No fallback allowed for visible keys")
    receipt, current = work.read()
    assert receipt is work.receipt and current is True
    assert work.s.binding_calls == []
    assert work.rechecks == [work.ctx]


def test_shared_hidden_key_uses_actual_helper_under_same_caller_uow(work):
    work.s.rows[RequestKey] = []
    transaction, caller = work.s.get_transaction(), work.ctx
    assert work.read() == (work.receipt, True)
    assert work.s.binding_calls == [(caller.tenant_id, work.pid, work.receipt.id)]
    assert work.s.get_transaction() is transaction and work.ctx is caller
    assert work.rechecks == [caller]


@pytest.mark.parametrize("bound", (False, None, 1, "true"))
def test_missing_or_nonboolean_shared_association_fails_closed(work, bound):
    work.s.rows[RequestKey] = []
    work.s.bound = bound
    rejected(work)
    assert len(work.s.binding_calls) == 1


def test_shared_association_error_propagates_without_a_retained_result(work):
    work.s.rows[RequestKey] = []
    original = RuntimeError("actual association owner unavailable")
    work.s.bound = original
    with pytest.raises(RuntimeError) as error:
        work.read()
    assert error.value is original
    assert len(work.s.binding_calls) == 1 and not work.rechecks


def test_original_author_with_missing_key_cannot_use_peer_fallback(work):
    work.s.rows[RequestKey] = []
    work.ctx = replace(work.ctx, actor_id=work.author, requester_id=work.author)
    rejected(work)
    assert work.s.binding_calls == []


@pytest.mark.parametrize("fault", ("wrong_digest", "duplicate"))
def test_visible_invalid_keys_cannot_switch_to_boolean_path(work, fault):
    if fault == "wrong_digest":
        work.key.digest = digest("different request")
    else:
        work.s.rows[RequestKey].append(work.key)
    rejected(work)
    assert work.s.binding_calls == []


@pytest.mark.parametrize("missing", (Receipt, Audit, Outbox, Confirmation))
def test_boolean_does_not_replace_any_missing_common_group_member(work, missing):
    work.s.rows[RequestKey] = []
    if missing is Confirmation:
        work.s.proof = None
    else:
        work.s.rows[missing] = []
    rejected(work, "STORED_ATOM_MISMATCH" if missing is Confirmation else "STORED_ATOM_INCOMPLETE")
    assert len(work.s.binding_calls) == (1 if missing in {Audit, Outbox} else 0)


@pytest.mark.parametrize("fault", ("actor", "operation", "product", "digest", "material"))
def test_shared_path_preserves_actual_receipt_and_material_binding(work, fault):
    work.s.rows[RequestKey] = []
    if fault == "actor":
        work.receipt.actor_id = uuid4()
    elif fault == "operation":
        work.receipt.operation = "npi.control_plan.record"
    elif fault == "product":
        work.receipt.product_id = uuid4()
    elif fault == "digest":
        work.receipt.request_digest = digest("different request digest")
    else:
        work.s.proof.payload_digest = digest("different material")
    rejected(work, "STORED_ATOM_INCOMPLETE" if fault == "product" else "STORED_ATOM_MISMATCH")
    assert work.s.binding_calls == []


def test_shared_provenance_does_not_make_retained_authority_current(work):
    work.s.rows[RequestKey] = []
    work.current = False
    assert work.read() == (work.receipt, False)
    assert work.rechecks == [work.ctx] and len(work.s.binding_calls) == 1
