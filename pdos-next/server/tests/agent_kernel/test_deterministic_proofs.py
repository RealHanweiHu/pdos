from copy import deepcopy
from decimal import Decimal, localcontext
from types import SimpleNamespace as NS
from uuid import UUID

import pytest

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.deterministic_proofs import (
    ComputeEngine,
    canonical_hash,
    resolve_compute_proof,
)
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.domain.preproject.models import Proposal
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Principal
from pdos_next.service import digest


class MemorySession:
    def __init__(self, rows):
        self.rows = {(model, row.id): row for model, row in rows}

    def get(self, model, identity):
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

    def scalars(self, query):
        from pdos_next.clock import now
        rows = [row for (model, _), row in self.rows.items() if model is Grant
                and (row.expires_at is None or row.expires_at > now())]
        return NS(all=lambda: rows)


def fixture():
    run = NS(
        id=UUID(int=1),
        tenant_id=UUID(int=2),
        category_id=UUID(int=3),
        requester_id=UUID(int=4),
        writer_id=UUID(int=8),
        session_id=UUID(int=9),
        private_context=False,
        data_categories=["public"],
        customer_identities=[],
        trigger="conversation",
        product_id=None,
        proposal_id=UUID(int=5),
        cancel_epoch=0,
        state="running",
        reverted_at=None,
        versions={
            "model_version": "test",
            "model_route_digest": "a" * 64,
            "tool_definitions": {"main": "b" * 64},
            "prompt_prefixes": {"main": "c" * 64},
        },
    )
    args = {"amount": "1.234567890123456789012345678901"}
    result = {"claim": {"value": args["amount"], "unit": "USD"}}
    model = NS(
        id=UUID(int=6),
        tenant_id=run.tenant_id,
        run_id=run.id,
        tool="model",
        state="completed",
        error_code=None,
        receipt_id=None,
        execution_binding={
            "kind": "model",
            "model_version": "test",
            "model_route_digest": "a" * 64,
            "tool_definitions_digest": "b" * 64,
            "prompt_digest": "c" * 64,
            "isolation": "main",
            "cancel_epoch": 0,
            "loaded_skills": [],
        },
        result={"calls": [{"name": "calc.cost_subtotal", "arguments": args}]},
    )
    call = NS(
        id=UUID(int=7),
        tenant_id=run.tenant_id,
        run_id=run.id,
        tool="calc.cost_subtotal",
        state="completed",
        error_code=None,
        receipt_id=None,
        input_digest=digest(["calc.cost_subtotal", args]),
        call_key=execution_key(run.id, model.id, 0),
        result=result,
        execution_binding=None,
    )
    call.execution_binding = ReadBinding(
        read_kind="compute/v1", isolation="main", run_id=run.id,
        **{field: getattr(run, field) for field in (
            "tenant_id", "category_id", "session_id", "requester_id", "writer_id",
            "product_id", "proposal_id", "cancel_epoch", "private_context",
            "data_categories", "customer_identities",
        )},
        tool=call.tool, call_key=call.call_key, model_call_id=model.id, response_index=0,
        engine_version="test-only-v1", result_digest=canonical_hash(result),
        **{key: getattr(ModelBinding.model_validate(model.execution_binding), key) for key in (
            "model_version", "model_route_digest", "tool_definitions_digest", "prompt_digest",
        )},
    ).model_dump(mode="json")
    rows = [(AgentRun, run), (AgentToolCall, model), (AgentToolCall, call),
            (Category, NS(id=run.category_id)),
            (Proposal, NS(id=run.proposal_id, tenant_id=run.tenant_id,
                          category_id=run.category_id))]
    for identity in (run.writer_id, run.requester_id):
        rows.append((Principal, NS(id=identity, tenant_id=run.tenant_id, active=True)))
        rows.append((Grant, NS(id=UUID(int=identity.int + 100), principal_id=identity,
                              expires_at=None)))
    return NS(
        run=run,
        model=model,
        call=call,
        session=MemorySession(rows),
        ctx=NS(
            tenant_id=run.tenant_id,
            category_id=run.category_id,
            actor_id=run.requester_id,
            requester_id=run.requester_id,
            run_id=None,
            agent_run_id=None,
            cancel_epoch=None,
        ),
        reference={"call_id": str(call.id), "result_path": ["claim"]},
        content=deepcopy(result["claim"]),
        engines={
            call.tool: ComputeEngine(
                "test-only-v1",
                lambda a: {"claim": {"value": a["amount"], "unit": "USD"}},
                (("claim",),),
            )
        },
    )


def verify(f, **kwargs):
    return resolve_compute_proof(
        f.session, f.ctx, f.run, f.reference, f.content, engines=kwargs.get("engines", f.engines)
    )


def test_actual_calculation_with_matching_content():
    f = fixture()
    proof = verify(f)
    assert proof["call_id"] == str(f.call.id)
    assert proof["input_digest"] == f.call.input_digest
    assert proof["result_digest"] == canonical_hash(f.call.result)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("call", "run_id", UUID(int=99)),
        ("call", "state", "started"),
        ("call", "tool", "model"),
        ("call", "tenant_id", UUID(int=99)),
        ("call", "input_digest", "f" * 64),
        ("call", "call_key", "forged-step"),
        ("model", "state", "started"),
        ("model", "run_id", UUID(int=99)),
        ("run", "state", "cancelled"),
        ("run", "reverted_at", "now"),
        ("ctx", "category_id", UUID(int=99)),
        ("ctx", "requester_id", UUID(int=99)),
    ],
)
def test_rejects_wrong_run_scope_step_or_terminal_state(target, field, value):
    f = fixture()
    setattr(getattr(f, target), field, value)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "unbound"),
        ("graph", "other"),
        ("step", "model"),
        ("isolation", "research"),
        ("cancel_epoch", 1),
        ("engine_version", "forged"),
        ("model_call_id", str(UUID(int=99))),
        ("response_index", True),
        ("result_digest", "f" * 64),
    ],
)
def test_rejects_untrusted_binding(field, value):
    f = fixture()
    f.call.execution_binding[field] = value
    with pytest.raises(DomainError):
        verify(f)


def test_default_engine_ports_are_closed():
    with pytest.raises(DomainError) as error:
        verify(fixture(), engines={})
    assert error.value.detail["reason"] == "deterministic_proof_required"


def test_model_cannot_forge_result_even_with_updated_hash():
    f = fixture()
    f.call.result["claim"]["value"] = "999"
    f.content["value"] = "999"
    f.call.execution_binding["result_digest"] = canonical_hash(f.call.result)
    with pytest.raises(DomainError) as error:
        verify(f)
    assert error.value.detail["reason"] == "compute_output_mismatch"


def test_claim_must_match_whole_engine_declared_content_path():
    f = fixture()
    f.content["unit"] = "EUR"
    with pytest.raises(DomainError):
        verify(f)
    f = fixture()
    f.reference["result_path"] = ["claim", "value"]
    with pytest.raises(DomainError):
        verify(f)


def test_exact_hash_is_independent_of_decimal_context_and_rejects_float():
    number = Decimal("12345678901234567890.12345678901234567890")
    expected = canonical_hash({"value": number})
    with localcontext() as context:
        context.prec = 2
        assert canonical_hash({"value": number}) == expected
    with pytest.raises(ValueError):
        canonical_hash({"value": 0.1})


@pytest.mark.parametrize("state", ["completed", "partial"])
def test_completed_run_remains_consumable_by_human_without_reopening(state):
    f = fixture()
    f.run.state = state
    assert verify(f)["run_id"] == str(f.run.id)
    assert f.run.state == state


@pytest.mark.parametrize("field", ["writer_id", "session_id", "requester_id", "proposal_id",
                                   "product_id", "category_id", "tenant_id"])
def test_complete_binding_scope_cannot_be_replaced(field):
    f = fixture()
    f.call.execution_binding[field] = str(UUID(int=99))
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("target", ["call", "model"])
def test_business_receipt_is_not_read_proof(target):
    f = fixture()
    getattr(f, target).receipt_id = UUID(int=99)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("principal", ["writer_id", "requester_id"])
@pytest.mark.parametrize("change", ["inactive", "grant_missing", "grant_expired"])
def test_current_authority_is_rechecked_for_historical_computation(principal, change):
    from datetime import timedelta

    from pdos_next.clock import now

    f = fixture()
    f.run.state = "completed"
    identity = getattr(f.run, principal)
    if change == "inactive":
        f.session.get(Principal, identity).active = False
    else:
        key = (Grant, UUID(int=identity.int + 100))
        if change == "grant_missing":
            del f.session.rows[key]
        else:
            f.session.rows[key].expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("field", ["read_kind", "proof_version", "graph", "step",
                                   "private_context", "data_categories", "customer_identities"])
def test_partial_legacy_or_defaulted_binding_is_not_trusted(field):
    f = fixture()
    del f.call.execution_binding[field]
    with pytest.raises(DomainError):
        verify(f)


def test_entire_claim_content_is_compared_including_extra_fields():
    f = fixture()
    f.content["text"] = "Unsupported extra assertion"
    with pytest.raises(DomainError) as error:
        verify(f)
    assert error.value.detail["reason"] == "compute_content_mismatch"


def test_plain_completed_result_with_forged_hash_still_requires_actual_engine():
    f = fixture()
    f.engines[f.call.tool] = ComputeEngine(
        "changed-version", lambda _: f.call.result, (("claim",),)
    )
    with pytest.raises(DomainError) as error:
        verify(f)
    assert error.value.detail["reason"] == "compute_binding_invalid"


def test_stale_epoch_rejects_even_if_caller_run_epoch_was_also_updated():
    f = fixture()
    f.run.cancel_epoch = 1
    with pytest.raises(DomainError):
        verify(f)
