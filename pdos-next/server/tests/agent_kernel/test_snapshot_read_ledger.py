"""Completed server read ledger validation; synthetic rows, no database or model."""

from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, PublicWebSnapshot
from pdos_next.agent_kernel.snapshot_read_ledger import (
    TOOL,
    SnapshotReadBinding,
    page_result,
    validate_snapshot_read,
)
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.preproject.models import Proposal
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Principal, Receipt
from pdos_next.service import digest


class MemorySession:
    def __init__(self, rows):
        self.rows = {(model, row.id): row for model, row in rows}
        self.reads = []

    def scalars(self, query):
        from pdos_next.clock import now
        rows = [row for (model, _), row in self.rows.items() if model is Grant
                and (row.expires_at is None or row.expires_at > now())]
        self.reads.extend((Grant, row.id) for row in rows)
        return SimpleNamespace(all=lambda: rows)

    def get(self, model, identity):
        self.reads.append((model, identity))
        return self.rows.get((model, identity))

    def scalar(self, query):
        if str(query) == "SELECT to_regclass('public.proposals') IS NOT NULL":
            return True
        assert query.column_descriptions[0]["entity"] is Proposal
        params = query.compile().params
        assert set(params) == {"tenant_id_1", "category_id_1", "id_1"}
        row = self.get(Proposal, params["id_1"])
        return row if row and (row.tenant_id, row.category_id) == (
            params["tenant_id_1"], params["category_id_1"],
        ) else None


@pytest.fixture
def ledger():
    scope = RunScope(*(uuid4() for _ in range(6)), proposal_id=uuid4())
    data = asdict(scope)
    data["id"] = data.pop("run_id")
    run = SimpleNamespace(
        **data,
        state="running",
        reverted_at=None,
        versions={
            "model_version": "synthetic-model",
            "model_route_digest": "a" * 64,
            "tool_definitions": {"research": "b" * 64},
            "prompt_prefixes": {"research": "c" * 64},
        },
    )
    body = "First unseen line\nSecond exact quoted fact 第二行\nThird unseen fact\n"
    snapshot = SimpleNamespace(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        category_id=scope.category_id,
        owner_id=uuid4(),
        registered_by_run_id=uuid4(),
        receipt_id=uuid4(),
        visibility="category",
        status="ok",
        url="https://synthetic.test/original",
        final_url="https://synthetic.test/final",
        markdown=body,
        content_hash=sha256(body.encode()).hexdigest(),
    )
    receipt = SimpleNamespace(
        id=snapshot.receipt_id,
        tenant_id=scope.tenant_id,
        category_id=scope.category_id,
        requester_id=snapshot.owner_id,
        actor_id=uuid4(),
        run_id=None,
        product_id=None,
        result={
            "proof_version": 1,
            "registered_by_run_id": str(snapshot.registered_by_run_id),
            "snapshot_id": str(snapshot.id), "content_hash": snapshot.content_hash,
        },
        agent_run_id=snapshot.registered_by_run_id,
        operation="research.snapshot.register",
        subject_type="public_web_snapshot",
        subject_id=snapshot.id,
        subject_revision=1,
    )
    cursor = len(body.splitlines(keepends=True)[0])
    page_chars = len(body.splitlines(keepends=True)[1])
    args = {"url": snapshot.final_url, "cursor": cursor}
    model = SimpleNamespace(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        run_id=run.id,
        tool="model",
        state="completed",
        error_code=None,
        receipt_id=None,
        execution_binding={
            "kind": "model",
            "model_version": "synthetic-model",
            "model_route_digest": "a" * 64,
            "tool_definitions_digest": "b" * 64,
            "prompt_digest": "c" * 64,
            "isolation": "research",
            "cancel_epoch": 0,
            "loaded_skills": [],
        },
        result={"calls": [{"name": TOOL, "arguments": args}]},
    )
    binding = SnapshotReadBinding(
        kind="read",
        read_kind="registered_snapshot/v1",
        proof_version=1,
        isolation="research",
        page_chars=page_chars,
        private_context=scope.private_context,
        data_categories=tuple(sorted(scope.data_categories)),
        customer_identities=scope.customer_identities,
        tool=TOOL,
        call_key=execution_key(run.id, model.id, 0),
        model_version="synthetic-model", model_route_digest="a" * 64, prompt_digest="c" * 64,
        **{
            field: getattr(scope, field)
            for field in (
                "tenant_id",
                "category_id",
                "run_id",
                "session_id",
                "requester_id",
                "writer_id",
                "product_id",
                "proposal_id",
                "cancel_epoch",
            )
        },
        model_call_id=model.id,
        response_index=0,
        tool_definitions_digest="b" * 64,
    )
    call = SimpleNamespace(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        run_id=run.id,
        tool=TOOL,
        state="completed",
        error_code=None,
        receipt_id=None,
        call_key=execution_key(run.id, model.id, 0),
        input_digest=digest([TOOL, args]),
        execution_binding=binding.model_dump(mode="json"),
        result=page_result(snapshot, cursor=cursor, page_chars=page_chars),
    )
    session = MemorySession(
        [
            (AgentRun, run),
            (AgentToolCall, call),
            (AgentToolCall, model),
            (PublicWebSnapshot, snapshot),
            (Receipt, receipt),
            (Category, SimpleNamespace(id=scope.category_id)),
            (Proposal, SimpleNamespace(id=scope.proposal_id, tenant_id=scope.tenant_id,
                                       category_id=scope.category_id)),
            *[(Principal, SimpleNamespace(id=identity, tenant_id=scope.tenant_id, active=True,
                                          kind="agent" if identity != scope.requester_id
                                          else "human"))
              for identity in (scope.writer_id, scope.requester_id, receipt.actor_id)],
            *[(Grant, SimpleNamespace(id=uuid4(), principal_id=identity, expires_at=None))
              for identity in (scope.writer_id, scope.requester_id)],
        ]
    )
    return SimpleNamespace(
        scope=scope,
        run=run,
        model=model,
        call=call,
        snapshot=snapshot,
        receipt=receipt,
        args=args,
        session=session,
    )


def validate(f, *, line=2, quote="exact quoted fact", version=1):
    return validate_snapshot_read(
        f.session, f.scope, f.snapshot.id, version, line, quote, call_id=f.call.id
    )


def denied(f, reason, **kwargs):
    with pytest.raises(DomainError) as error:
        validate(f, **kwargs)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert error.value.detail["reason"] == reason


def test_cross_run_cross_requester_read_is_proved_by_current_completed_research_page(ledger):
    assert ledger.snapshot.registered_by_run_id != ledger.run.id
    assert ledger.snapshot.owner_id != ledger.run.requester_id
    proof = validate(ledger)
    assert proof.call_id == ledger.call.id and proof.snapshot_id == ledger.snapshot.id
    assert proof.registration_receipt_id == ledger.receipt.id
    assert proof.line == 2 and proof.quote == "exact quoted fact"
    assert set(ledger.session.reads) == set(ledger.session.rows)


@pytest.mark.parametrize("status", ["ok", "partial"])
def test_usable_source_status_and_verbatim_unicode_are_retained(ledger, status):
    ledger.snapshot.status = status
    ledger.call.result["source_status"] = status
    assert validate(ledger, quote="第二行").quote == "第二行"


@pytest.mark.parametrize("field", ["tenant_id", "category_id", "proposal_id", "requester_id"])
def test_caller_cannot_replace_actual_run_scope(ledger, field):
    ledger.scope = replace(ledger.scope, **{field: uuid4()})
    with pytest.raises(DomainError) as error:
        validate(ledger)
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "category_id",
        "proposal_id",
        "requester_id",
        "writer_id",
        "session_id",
        "product_id",
        "run_id",
    ],
)
def test_read_binding_cannot_borrow_other_context(ledger, field):
    ledger.call.execution_binding[field] = str(uuid4())
    denied(ledger, "snapshot_read_not_bound" if field == "run_id"
           else "snapshot_read_scope_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "started"),
        ("state", "failed"),
        ("state", "reconciled"),
        ("tool", "research.search"),
        ("tool", "model"),
        ("tool", "evidence.artifact.read"),
        ("run_id", uuid4()),
        ("tenant_id", uuid4()),
        ("error_code", "SOURCE_UNAVAILABLE"),
        ("receipt_id", uuid4()),
    ],
)
def test_only_successful_current_snapshot_read_call_is_eligible(ledger, field, value):
    setattr(ledger.call, field, value)
    denied(ledger, "snapshot_read_not_bound")


@pytest.mark.parametrize("kind", ["unbound", "model", "domain_t0"])
def test_legacy_or_model_generated_results_never_become_read_proof(ledger, kind):
    ledger.call.execution_binding = {"kind": kind}
    denied(ledger, "snapshot_read_not_bound")


@pytest.mark.parametrize("field", ["read_kind", "proof_version", "isolation"])
def test_explicit_server_port_protocol_is_required(ledger, field):
    del ledger.call.execution_binding[field]
    denied(ledger, "snapshot_read_not_bound")


@pytest.mark.parametrize(
    "change",
    [
        "root_model",
        "wrong_epoch",
        "tools",
        "prompt",
        "route",
        "uncompleted",
        "other_run",
        "index",
        "call_key",
        "digest",
    ],
)
def test_registered_research_graph_and_actual_native_result_are_verified(ledger, change):
    if change == "root_model":
        ledger.model.execution_binding["isolation"] = "main"
    elif change == "wrong_epoch":
        ledger.model.execution_binding["cancel_epoch"] = 1
    elif change in {"tools", "prompt", "route"}:
        field = {
            "tools": "tool_definitions_digest",
            "prompt": "prompt_digest",
            "route": "model_route_digest",
        }[change]
        ledger.model.execution_binding[field] = "d" * 64
    elif change == "uncompleted":
        ledger.model.state = "started"
    elif change == "other_run":
        ledger.model.run_id = uuid4()
    elif change == "index":
        ledger.call.execution_binding["response_index"] = 9
    elif change == "call_key":
        ledger.call.call_key = "model-controlled-native-id"
    else:
        ledger.call.input_digest = "d" * 64
    denied(ledger, "snapshot_read_not_bound" if change in {"index", "call_key"}
           else "snapshot_read_graph_mismatch")


def test_model_arguments_cannot_supply_a_read_proof(ledger):
    ledger.args["read_proof"] = deepcopy(ledger.call.result)
    ledger.call.input_digest = digest([TOOL, ledger.args])
    denied(ledger, "snapshot_read_graph_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", uuid4()),
        ("category_id", uuid4()),
        ("status", "failed"),
    ],
)
def test_actual_snapshot_scope_and_current_status_are_required(ledger, field, value):
    setattr(ledger.snapshot, field, value)
    denied(ledger, "snapshot_unavailable")


@pytest.mark.parametrize("model_name", ["snapshot", "receipt", "call", "model"])
def test_rls_hidden_or_missing_proof_rows_are_unavailable(ledger, model_name):
    row = getattr(ledger, model_name)
    model = {
        "snapshot": PublicWebSnapshot,
        "receipt": Receipt,
        "call": AgentToolCall,
        "model": AgentToolCall,
    }[model_name]
    del ledger.session.rows[(model, row.id)]
    reason = {
        "snapshot": "snapshot_unavailable",
        "receipt": "snapshot_registration_mismatch",
        "call": "snapshot_read_not_bound",
        "model": "snapshot_read_graph_mismatch",
    }
    denied(ledger, reason[model_name])


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", uuid4()),
        ("category_id", uuid4()),
        ("requester_id", uuid4()),
        ("agent_run_id", uuid4()),
        ("operation", "category.create"),
        ("subject_type", "category"),
        ("subject_id", uuid4()),
        ("subject_revision", 2),
    ],
)
def test_registration_receipt_must_name_actual_source_and_registrar(ledger, field, value):
    setattr(ledger.receipt, field, value)
    denied(ledger, "snapshot_registration_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("markdown", "forged content"),
        ("content_hash", "0" * 64),
        ("snapshot_id", str(uuid4())),
        ("registration_receipt_id", str(uuid4())),
        ("page_hash", "f" * 64),
        ("cursor", 0),
        ("end", 999),
        ("next_cursor", None),
        ("locator", "chars:0:999"),
    ],
)
def test_page_identity_hash_and_actual_returned_range_cannot_be_substituted(ledger, field, value):
    ledger.call.result[field] = value
    denied(ledger, "snapshot_page_mismatch")


def test_actual_source_body_hash_is_recomputed(ledger):
    ledger.snapshot.markdown += "unexpected mutation"
    denied(ledger, "snapshot_content_mismatch")


@pytest.mark.parametrize(
    "line,quote",
    [(1, "First"), (3, "Third"), (2, "unseen"), (True, "exact"), (2, ""), (2, "EXACT")],
)
def test_only_verbatim_quote_on_the_actual_read_line_is_covered(ledger, line, quote):
    denied(ledger, "snapshot_quote_not_read", line=line, quote=quote)


def test_page_cutting_a_quote_does_not_prove_the_unread_remainder(ledger):
    ledger.call.execution_binding["page_chars"] = len("Second exact")
    ledger.call.result = page_result(
        ledger.snapshot, cursor=ledger.args["cursor"], page_chars=len("Second exact")
    )
    denied(ledger, "snapshot_quote_not_read")
    assert validate(ledger, quote="exact").quote == "exact"


def test_private_rls_readability_does_not_invent_outbound_authority(ledger):
    ledger.snapshot.visibility = "private"
    denied(ledger, "snapshot_private_outbound_unbound")


def test_cancelled_run_cannot_reuse_a_completed_read(ledger):
    ledger.run.cancel_epoch += 1
    with pytest.raises(DomainError) as error:
        validate(ledger)
    assert error.value.code == "CANCELLED_RUN"


def category_registration(f):
    f.receipt.operation = "category.create"
    f.receipt.subject_type = "category"
    f.receipt.subject_id = f.snapshot.category_id
    f.receipt.agent_run_id = None
    f.receipt.actor_id = f.receipt.requester_id
    f.receipt.result = {
        "proof_version": 1,
        "category_id": str(f.snapshot.category_id),
        "prepared_by_run_id": str(f.snapshot.registered_by_run_id),
        "registered_by_run_id": str(f.snapshot.registered_by_run_id),
        "snapshot_refs": [{"snapshot_id": str(f.snapshot.id),
                           "content_hash": f.snapshot.content_hash, "call_id": str(uuid4())}],
    }
    f.session.rows[(Principal, f.receipt.actor_id)] = SimpleNamespace(
        id=f.receipt.actor_id, tenant_id=f.snapshot.tenant_id, kind="human", active=True,
    )


def test_category_create_registration_uses_named_human_receipt_and_exact_snapshot_result(ledger):
    category_registration(ledger)
    # No original personal Run is visible: it belongs to the other requester.
    assert (AgentRun, ledger.snapshot.registered_by_run_id) not in ledger.session.rows
    assert validate(ledger).registration_receipt_id == ledger.receipt.id


@pytest.mark.parametrize("field", ["prepared_by_run_id", "registered_by_run_id", "category_id"])
def test_category_create_receipt_result_must_bind_actual_registration(ledger, field):
    category_registration(ledger)
    ledger.receipt.result[field] = str(uuid4())
    denied(ledger, "snapshot_registration_mismatch")


@pytest.mark.parametrize("change", ["empty", "missing", "wrong_id", "wrong_hash", "bad_call",
                                    "duplicate", "extra_field", "wrong_actor", "agent_actor"])
def test_category_create_receipt_does_not_accept_unproved_or_substituted_snapshot(ledger, change):
    category_registration(ledger)
    refs = ledger.receipt.result["snapshot_refs"]
    if change == "empty":
        ledger.receipt.result = {}
    elif change == "missing":
        refs.clear()
    elif change == "wrong_id":
        refs[0]["snapshot_id"] = str(uuid4())
    elif change == "wrong_hash":
        refs[0]["content_hash"] = "f" * 64
    elif change == "bad_call":
        refs[0]["call_id"] = "provider-native-label"
    elif change == "duplicate":
        refs.append(deepcopy(refs[0]))
    elif change == "extra_field":
        refs[0]["approved"] = True
    elif change == "wrong_actor":
        ledger.receipt.actor_id = ledger.scope.writer_id
    else:
        ledger.session.get(Principal, ledger.receipt.actor_id).kind = "agent"
    denied(ledger, "snapshot_registration_mismatch")


@pytest.mark.parametrize("state", ["completed", "partial"])
def test_completed_consuming_run_keeps_historical_read_valid(ledger, state):
    ledger.run.state = state
    assert validate(ledger).call_id == ledger.call.id
    assert ledger.run.state == state


@pytest.mark.parametrize("change", ["writer_inactive", "requester_inactive", "writer_grant",
                                    "requester_grant", "grant_expired", "product_hidden"])
def test_historical_read_rechecks_current_authority(ledger, change):
    from datetime import timedelta

    from pdos_next.clock import now

    ledger.run.state = "completed"
    if change.endswith("inactive"):
        identity = (ledger.scope.writer_id if change.startswith("writer")
                    else ledger.scope.requester_id)
        ledger.session.get(Principal, identity).active = False
    elif change in {"writer_grant", "requester_grant", "grant_expired"}:
        identity = (ledger.scope.writer_id if change.startswith("writer")
                    else ledger.scope.requester_id)
        key = next(key for key, row in ledger.session.rows.items()
                   if key[0] is Grant and row.principal_id == identity)
        if change == "grant_expired":
            ledger.session.rows[key].expires_at = now() - timedelta(seconds=1)
        else:
            del ledger.session.rows[key]
    else:
        identity = uuid4()
        ledger.scope = replace(ledger.scope, product_id=identity)
        ledger.run.product_id = identity
        ledger.call.execution_binding["product_id"] = str(identity)
    with pytest.raises(DomainError):
        validate(ledger)


@pytest.mark.parametrize("field,value", [
    ("private_context", True), ("data_categories", ["customer"]),
    ("customer_identities", ["Unrelated customer"]), ("cancel_epoch", 1),
])
def test_read_binding_includes_complete_private_run_scope(ledger, field, value):
    ledger.call.execution_binding[field] = value
    denied(ledger, "snapshot_read_scope_mismatch")


def test_crlf_unicode_offsets_and_repeated_quote_use_wholly_returned_occurrence(ledger):
    body = "Unseen 前行\r\nrepeat 隐藏 repeat 可见\r\nUnseen end\r\n"
    ledger.snapshot.markdown = body
    ledger.snapshot.content_hash = sha256(body.encode()).hexdigest()
    ledger.receipt.result["content_hash"] = ledger.snapshot.content_hash
    cursor = body.index("repeat 可见")
    ledger.args["cursor"] = cursor
    ledger.call.input_digest = digest([TOOL, ledger.args])
    ledger.call.execution_binding["page_chars"] = len("repeat 可见")
    ledger.call.result = page_result(ledger.snapshot, cursor=cursor, page_chars=len("repeat 可见"))
    assert validate(ledger, line=2, quote="repeat").quote == "repeat"
    denied(ledger, "snapshot_quote_not_read", line=2, quote="隐藏 repeat")
    denied(ledger, "snapshot_quote_not_read", line=2, quote="可见\r\nUnseen")


def test_snapshot_proof_refuses_old_partial_binding_shape(ledger):
    for field in ("graph", "step", "tool", "call_key", "model_version", "model_route_digest",
                  "prompt_digest", "private_context", "data_categories", "customer_identities"):
        ledger.call.execution_binding.pop(field, None)
    denied(ledger, "snapshot_read_not_bound")
