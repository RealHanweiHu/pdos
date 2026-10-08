"""SELECT substitutes exercise rejection; no DB, grants, bytes or true UOW proof."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import fact_atom_storage as storage
import facts
import pytest
from fact_storage_codec import SCHEMA_VERSION, assemble_fact, decode_fact_body
from pdos_next.errors import DomainError
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.service import Context, digest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators
from test_facts import material_fixture
from test_paired import AT, uid


class Memory:
    def __init__(self, rows):
        self.rows, self.queries, self.hook = rows, [], None

    def selected(self, query):
        assert query.is_select
        # Compilable real PostgreSQL SELECTs, bounded and with no autoflush.
        query.compile(dialect=postgresql.dialect())
        assert query._limit_clause.value in {1, 2}
        assert query.get_execution_options().get("autoflush") is False
        model = query.column_descriptions[0].get("entity")
        key = model if model is not None else query.get_final_froms()[0].name
        self.queries.append(query)
        if self.hook:
            self.hook(key)

        def matches(row, expression):
            assert expression.operator is operators.eq
            assert hasattr(expression.right, "value")
            value = (
                row[expression.left.key]
                if isinstance(row, dict)
                else getattr(row, expression.left.key)
            )
            return value == expression.right.value

        return [
            v for v in self.rows.get(key, []) if all(matches(v, e) for e in query._where_criteria)
        ][: query._limit_clause.value]

    def scalars(self, query):
        return self.selected(query)

    def execute(self, query):
        result = self.selected(query)
        return SimpleNamespace(mappings=lambda: result)


def frame(monkeypatch, kind="observation"):
    material = material_fixture()
    fact = (
        material.rule
        if kind == "rule"
        else material.observations[0]
        if kind == "observation"
        else material.review
    )
    raw = fact.model_dump(mode="json")
    raw.pop("provenance")
    raw["ref"].pop("sha256")
    document = decode_fact_body({"schema_version": SCHEMA_VERSION, "body": raw})
    body = document.body
    _, operation, tier, subject, event_name, status = storage.SPECS[kind]
    owner = body.owner_id
    writer = fact.provenance.actor_id
    scope = body.scope
    proof_id = None if tier == "host_import" else uid(f"{kind}-real-proof-row")
    row = dict(
        id=body.ref.id,
        revision=body.ref.revision,
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        issue_id=body.issue_id,
        capa_id=body.capa_id,
        owner_id=owner,
        writer_id=writer,
        actor_id=writer,
        requester_id=writer,
        visibility=body.visibility,
        purpose=body.purpose,
        nature=body.nature,
        operation=operation,
        tier=tier,
        status=status,
        command_id=uid(f"{kind}-command"),
        created_at=body.created_at,
        fact_body=document.model_dump(mode="json"),
        payload_sha256=facts.fact_payload_sha256(body.model_dump(mode="json")),
        read_set_sha256=digest(
            [facts.json_value(v) for v in facts.canonical_reads(body.required_source_read_set)]
        ),
        intent_digest=digest(f"{kind}-common-intent"),
        shared_proof_id=proof_id,
        shared_proof_revision=18 if proof_id else None,
        proof_consumed_at=body.created_at - timedelta(microseconds=17) if proof_id else None,
        proof_expires_at=body.created_at + timedelta(seconds=1) if proof_id else None,
        token_sha256=digest("redacted-preimage") if proof_id else None,
        material_sha256=digest("saved-common-material") if proof_id else None,
    )
    receipt = Receipt(
        id=uid(f"{kind}-receipt"),
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        command_id=row["command_id"],
        actor_id=writer,
        requester_id=writer,
        operation=operation,
        subject_type=subject,
        subject_id=body.ref.id,
        subject_revision=body.ref.revision,
        visibility=body.visibility,
        request_digest=digest(f"{kind}-original-request"),
        intent_digest=row["intent_digest"],
        run_id=None,
        created_at=body.created_at + timedelta(microseconds=19),
        result=dict(
            id=str(body.ref.id),
            revision=body.ref.revision,
            status=status,
            fact_kind=kind,
            payload_sha256=row["payload_sha256"],
        ),
    )
    principal = Principal(id=owner, tenant_id=scope.tenant_id, kind="human", active=True)
    writer_row = (
        principal
        if owner == writer
        else Principal(id=writer, tenant_id=scope.tenant_id, kind="human", active=True)
    )
    rows = {
        storage.SPECS[kind][0]: [row],
        Product: [Product(id=scope.product_id, tenant_id=scope.tenant_id)],
        Principal: [principal] if writer_row is principal else [principal, writer_row],
        Grant: [
            Grant(
                id=uid("grant"),
                tenant_id=scope.tenant_id,
                product_id=scope.product_id,
                principal_id=owner,
                expires_at=AT + timedelta(days=2),
                can_write=False,
            )
        ],
        Receipt: [receipt],
        RequestKey: [
            RequestKey(
                id=uid("original-key"),
                tenant_id=scope.tenant_id,
                actor_id=writer,
                receipt_id=receipt.id,
                digest=receipt.request_digest,
                key="synthetic-original-key",
            )
        ],
        Audit: [
            Audit(
                id=uid("audit"),
                tenant_id=scope.tenant_id,
                receipt_id=receipt.id,
                actor_id=writer,
                operation=operation,
            )
        ],
        Outbox: [
            Outbox(
                id=uid("outbox"),
                tenant_id=scope.tenant_id,
                receipt_id=receipt.id,
                actor_id=writer,
                type=event_name,
                subject_id=body.ref.id,
                subject_revision=body.ref.revision,
                schema_version=1,
                correlation_id=receipt.command_id,
            )
        ],
        Confirmation: []
        if proof_id is None
        else [
            Confirmation(
                id=proof_id,
                tenant_id=scope.tenant_id,
                product_id=scope.product_id,
                subject_id=scope.product_id,
                actor_id=writer,
                operation=operation,
                revision=18,
                consumed=True,
                token_hash=row["token_sha256"],
                payload_digest=row["material_sha256"],
                snapshot={"actual": "synthetic SELECT substitute"},
                created_at=body.created_at - timedelta(seconds=5),
                expires_at=row["proof_expires_at"],
            )
        ],
    }
    memory = Memory(rows)
    s = Session(bind=SimpleNamespace())
    s.begin()
    monkeypatch.setattr(s, "scalars", memory.scalars)
    monkeypatch.setattr(s, "execute", memory.execute)

    # Explicit synthetic clock to check historical proof vs current grant;
    # cannot represent real elapsed observation or production proof.
    class Clock(storage.datetime):
        @classmethod
        def now(cls, tz=None):
            return AT + timedelta(days=1)

    monkeypatch.setattr(storage, "datetime", Clock)
    ctx = Context(scope.tenant_id, owner, owner)

    def read():
        return storage.read_fact_atom(
            s, ctx, scope.product_id, kind=kind, fact_id=body.ref.id, revision=body.ref.revision
        )

    return SimpleNamespace(
        s=s,
        ctx=ctx,
        read=read,
        rows=rows,
        row=row,
        receipt=receipt,
        memory=memory,
        document=document,
        body=body,
    )


@pytest.mark.parametrize("kind", ("rule", "observation", "review"))
def test_exact_stored_group_assembles_fact_but_never_attests_current_or_consumption(
    monkeypatch, kind
):
    w = frame(monkeypatch, kind)
    read = w.read()
    fact = assemble_fact(w.document, read.atom, expected_payload_sha256=w.row["payload_sha256"])
    assert fact.kind == kind and fact.ref.id == w.body.ref.id
    assert read.current_evidence_authorized is False and read.same_uow_consumption_attested is False
    assert read.atom.received_at == w.body.created_at
    assert read.atom.actor_id == w.row["writer_id"]
    assert len(w.memory.queries) <= 20


def test_legitimate_aliases_do_not_replace_original_request_provenance(monkeypatch):
    w = frame(monkeypatch)
    alias = deepcopy(w.rows[RequestKey][0])
    alias.id = uid("alias-key")
    alias.key = "alias"
    alias.digest = digest("different lawful payload token")
    w.rows[RequestKey].append(alias)
    assert w.read().atom.receipt_id == w.receipt.id
    w.rows[RequestKey].pop(0)
    with pytest.raises(DomainError, match="事实") as error:
        w.read()
    assert error.value.code == "FACT_ORIGINAL_REQUEST_KEY_MISSING"


@pytest.mark.parametrize(
    "case",
    (
        "unused_proof",
        "wrong_token",
        "wrong_watermark",
        "changed_expiry",
        "consumed_late",
        "wrong_outbox",
        "duplicate_audit",
        "wrong_receipt_subject",
        "boolean_result_revision",
        "body_changed",
        "wrong_writer_kind",
    ),
)
def test_unverifiable_saved_group_cannot_return_atom(monkeypatch, case):
    w = frame(monkeypatch)
    proof, event = w.rows[Confirmation][0], w.rows[Outbox][0]
    if case == "unused_proof":
        proof.consumed = False
    elif case == "wrong_token":
        proof.token_hash = digest("other")
    elif case == "wrong_watermark":
        proof.revision += 1
    elif case == "changed_expiry":
        proof.expires_at += timedelta(microseconds=1)
    elif case == "consumed_late":
        w.row["proof_consumed_at"] = w.row["created_at"] + timedelta(microseconds=1)
    elif case == "wrong_outbox":
        event.correlation_id = uid("other-command")
    elif case == "duplicate_audit":
        w.rows[Audit].append(deepcopy(w.rows[Audit][0]))
    elif case == "wrong_receipt_subject":
        w.receipt.subject_id = uid("other-fact")
    elif case == "boolean_result_revision":
        assert w.row["revision"] == 1
        w.receipt.result["revision"] = True
    elif case == "body_changed":
        w.row["fact_body"]["body"]["purpose"] = "changed purpose"
    elif case == "wrong_writer_kind":
        next(p for p in w.rows[Principal] if p.id == w.row["writer_id"]).kind = "ai"
    with pytest.raises(DomainError):
        w.read()


def test_final_current_caller_revocation_is_not_hidden_by_identity_map(monkeypatch):
    w = frame(monkeypatch)

    def hook(key):
        if key is Confirmation:
            next(p for p in w.rows[Principal] if p.id == w.ctx.actor_id).active = False

    w.memory.hook = hook
    with pytest.raises(DomainError) as error:
        w.read()
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_grant_expiring_during_final_acl_sql_is_rechecked_after_that_io(monkeypatch):
    w = frame(monkeypatch)
    tick = {"now": AT + timedelta(days=1), "grants": 0}

    class Clock(storage.datetime):
        @classmethod
        def now(cls, tz=None):
            return tick["now"]

    def hook(key):
        if key is Grant:
            tick["grants"] += 1
            if tick["grants"] == 2:
                tick["now"] = AT + timedelta(days=3)

    monkeypatch.setattr(storage, "datetime", Clock)
    w.memory.hook = hook
    with pytest.raises(DomainError) as error:
        w.read()
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_private_fact_cannot_borrow_writer_or_owner_context(monkeypatch):
    w = frame(monkeypatch)
    other = uid("peer-with-product-grant")
    w.rows[Principal].append(
        Principal(id=other, tenant_id=w.ctx.tenant_id, kind="human", active=True)
    )
    grant = deepcopy(w.rows[Grant][0])
    grant.id = uid("peer-grant")
    grant.principal_id = other
    w.rows[Grant].append(grant)
    peer = Context(w.ctx.tenant_id, other, other)
    w.row["visibility"] = "private"
    w.row["fact_body"]["body"]["visibility"] = "private"
    with pytest.raises(DomainError) as error:
        storage.read_fact_atom(
            w.s,
            peer,
            w.body.scope.product_id,
            kind="observation",
            fact_id=w.body.ref.id,
            revision=w.body.ref.revision,
        )
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_rolled_back_nested_transaction_cannot_supply_saved_atom(monkeypatch):
    w = frame(monkeypatch)
    nested = w.s.begin_nested()
    nested.rollback()
    # A ended SAVEPOINT object cannot be injected as the current caller UOW.
    monkeypatch.setattr(w.s, "get_nested_transaction", lambda: nested)
    with pytest.raises(DomainError) as error:
        w.read()
    assert error.value.code == "FACT_TRANSACTION_ROOT_MISMATCH"


def test_mid_read_transaction_replacement_does_not_escape_uow_guard(monkeypatch):
    w = frame(monkeypatch)

    def hook(key):
        if key is Confirmation:
            w.s.rollback()
            w.s.begin()

    w.memory.hook = hook
    with pytest.raises(DomainError) as error:
        w.read()
    assert error.value.code == "FACT_CALLER_UOW_CHANGED"
