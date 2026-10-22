"""Real ordinary-role read proof rows; synthetic provider responses, zero model calls."""

from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import WriteSource, execution_key
from pdos_next.agent_kernel.deterministic_proofs import resolve_compute_proof
from pdos_next.agent_kernel.host import BoundHost, KernelAdapters
from pdos_next.agent_kernel.m3_calculators import ENGINES, handlers
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.persistence import KernelStore, cancel_run
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.errors import DomainError
from tests.agent_kernel.test_domain_adapter_transactions import fixture
from tests.agent_kernel.test_transactions import human_session


def read_fixture(
    setup, *, tool="calc.cost_subtotal", arguments=None, proposal_id=None,
    skill_key="public_research",
):
    f = fixture(setup, proposal_id=proposal_id, skill_key=skill_key)
    if arguments is None:
        arguments = {"lines": [{
            "label": "合成零件", "qty": "2", "unit_cost": "3.125", "currency": "CNY",
            "as_of": "2026-10-10", "source_ref": {
                "type": "artifact", "id": f.arguments["artifact_id"], "version": 1,
                "line": 1, "quote": "Synthetic exact source",
            },
        }]}
    store = KernelStore(setup.engine)
    model_id, _ = store.claim(
        f.scope, "synthetic-read-model:" + str(uuid4()), "model", {"fixture": True},
        execution_binding=f.model.execution_binding,
    )
    store.settle(f.scope, model_id, result={"calls": [{"name": tool, "arguments": arguments}]})
    f.read_arguments, f.store = arguments, store
    f.read_spec = f.registry.get(tool)
    f.read_source = ReadSource(model_call_id=model_id, response_index=0)
    f.read_key = execution_key(f.scope.run_id, model_id, 0)
    f.host = BoundHost(store, KernelAdapters(
        route_for=lambda *_: f.route, project_context=lambda *_: {},
        verify_result=lambda *a: a[1], prepare_candidate=lambda *_: None,
        execute_command=lambda *_: None, read_tools=handlers, compute_engines=ENGINES,
        tool_registry=f.registry,
    ))
    return f


def read(f):
    return f.host.read(
        f.scope, f.read_spec, f.read_arguments, f.read_key, source=f.read_source,
    )


def test_real_compute_call_retains_complete_digest_and_exact_replay(setup):
    f = read_fixture(setup)
    result = read(f)
    assert result["proof_claims"]["single_currency_subtotal"]["value"] == "6.250"
    assert read(f) == result
    identity = UUID(result["execution_ref"]["call_id"])
    with f.store.transaction(f.scope) as (session, run):
        row = session.get(AgentToolCall, identity)
        assert row.state == "completed" and row.receipt_id is None and row.error_code is None
        assert row.result == {k: v for k, v in result.items() if k != "execution_ref"}
        proof = resolve_compute_proof(
            session, setup.ctx, run,
            {"call_id": str(identity), "result_path": ["proof_claims", "single_currency_subtotal"]},
            row.result["proof_claims"]["single_currency_subtotal"], engines=ENGINES,
        )
        assert proof["call_id"] == str(identity)


@pytest.mark.parametrize("field,value", [
    ("writer_id", str(uuid4())), ("category_id", str(uuid4())), ("cancel_epoch", 1),
    ("isolation", "research"), ("private_context", True), ("model_call_id", str(uuid4())),
    ("tool_definitions_digest", "a" * 64),
])
def test_sql_cannot_accept_forged_read_binding(setup, field, value):
    f = read_fixture(setup)
    from pdos_next.agent_kernel.bindings import ModelBinding
    from pdos_next.agent_kernel.deterministic_proofs import canonical_hash
    from pdos_next.agent_kernel.read_execution import build_read_binding

    computed = ENGINES[f.read_spec.name].calculate(f.read_arguments)
    with f.store.transaction(f.scope) as (_, run):
        bound = build_read_binding(
            f.scope, run, f.read_spec, f.read_source,
            ModelBinding.model_validate(f.model.execution_binding),
            read_kind="compute/v1", server_metadata={
                "engine_version": ENGINES[f.read_spec.name].version,
                "result_digest": canonical_hash(computed),
            },
        ).model_dump(mode="json")
    bound[field] = value
    with pytest.raises(DBAPIError):
        f.store.claim(
            f.scope, f.read_key, f.read_spec.name, f.read_arguments, execution_binding=bound,
        )


def test_real_read_proof_content_mismatch_and_cancelled_replay_refused(setup):
    f = read_fixture(setup)
    result = read(f)
    identity = UUID(result["execution_ref"]["call_id"])
    content = deepcopy(result["proof_claims"]["single_currency_subtotal"])
    content["value"] = "999"
    with f.store.transaction(f.scope) as (session, run):
        with pytest.raises(DomainError) as rejected:
            resolve_compute_proof(
                session, setup.ctx, run,
                {"call_id": str(identity),
                 "result_path": ["proof_claims", "single_currency_subtotal"]},
                content, engines=ENGINES,
            )
        assert rejected.value.detail["reason"] == "compute_content_mismatch"
    with human_session(setup) as session:
        cancel_run(session, setup.ctx, f.scope.run_id)
    with pytest.raises(DomainError):
        read(f)


def test_real_completed_read_result_and_binding_cannot_be_rewritten(setup):
    f = read_fixture(setup)
    identity = UUID(read(f)["execution_ref"]["call_id"])
    for field in ("result", "execution_binding"):
        with pytest.raises(DBAPIError):
            with f.store.transaction(f.scope) as (session, _):
                row = session.get(AgentToolCall, identity)
                setattr(row, field, {"forged": True})
                session.flush()


def test_original_agent_authority_is_rechecked_when_human_consumes_compute_proof(setup):
    f = read_fixture(setup)
    result = read(f)
    with Session(setup.admin) as session, session.begin():
        # Revocation uses actual Grant removal, never a forged scope flag.
        session.execute(text("DELETE FROM grants WHERE tenant_id=:tenant AND principal_id=:agent"),
                        {"tenant": setup.tenant, "agent": setup.agent})
    with human_session(setup) as session:
        from pdos_next.agent_kernel.models import AgentRun

        run = session.get(AgentRun, f.scope.run_id)
        with pytest.raises(DomainError):
            resolve_compute_proof(
                session, replace(setup.ctx, agent_run_id=run.id), run,
                {"call_id": result["execution_ref"]["call_id"],
                 "result_path": ["proof_claims", "single_currency_subtotal"]},
                result["proof_claims"]["single_currency_subtotal"], engines=ENGINES,
            )


def computed_candidate(setup):
    f = read_fixture(setup)
    result = read(f)
    f.arguments = {
        **f.arguments, "nature": "computed", "availability": "known",
        "content": result["proof_claims"]["single_currency_subtotal"],
        "extraction_ref": {
            "call_id": result["execution_ref"]["call_id"],
            "result_path": ["proof_claims", "single_currency_subtotal"],
        },
    }
    model_id, _ = f.store.claim(
        f.scope, "synthetic-computed-write:" + str(uuid4()), "model", {"fixture": True},
        execution_binding=f.model.execution_binding,
    )
    f.store.settle(f.scope, model_id, result={"calls": [{
        "name": f.spec.name, "arguments": f.arguments,
    }]})
    f.source = WriteSource(skill=f.source.skill, model_call_id=model_id, response_index=0)
    f.write_key = execution_key(f.scope.run_id, model_id, 0)
    return f


def test_actual_domain_computed_claim_uses_complete_server_result(setup):
    f = computed_candidate(setup)
    saved = f.adapter.execute(
        f.scope, f.spec.name, f.arguments, f.write_key, source=f.source,
    )
    from pdos_next.models import Claim, Receipt

    with Session(setup.admin) as session:
        receipt = session.get(Receipt, UUID(saved["id"]))
        claim = session.get(Claim, receipt.subject_id)
        assert claim.origin == "ai_draft" and claim.nature == "computed"
        assert claim.content == f.arguments["content"]
        assert claim.writer_id == setup.agent and claim.run_id == f.scope.run_id
        assert claim.extraction_ref == f.arguments["extraction_ref"]
    assert f.adapter.execute(
        f.scope, f.spec.name, f.arguments, f.write_key, source=f.source,
    ) == saved


def test_actual_computed_candidate_can_be_adopted_once_without_t0_qualification(setup):
    f = computed_candidate(setup)
    from pdos_next.agent_kernel.bootstrap import Bootstrap
    from pdos_next.agent_kernel.models import TenantSkillEnablement
    from pdos_next.models import Claim, Receipt

    with Session(setup.admin) as session, session.begin():
        session.get(TenantSkillEnablement, f.qualification.id).qualification_revoked = True
    bootstrap = Bootstrap(setup.engine)
    bootstrap.route = lambda *_: f.route
    prepared = bootstrap.prepare_candidate(f.scope, f.spec, f.arguments, f.write_key)
    path = f"/v1/categories/{setup.category}/commands"
    preview = setup.client.post(path + "/preview", headers=setup.headers, json=prepared["command"])
    assert preview.status_code == 200, preview.text
    saved = setup.client.post(path, headers=setup.headers, json=preview.json()["command"])
    assert saved.status_code == 200, saved.text
    with Session(setup.admin) as session:
        receipt = session.get(Receipt, UUID(saved.json()["id"]))
        claim = session.get(Claim, receipt.subject_id)
        assert claim.origin == "ai_draft" and claim.confirmed_by == setup.human
        assert claim.content == f.arguments["content"] and claim.writer_id == setup.agent
    replay = setup.client.post(path, headers=setup.headers, json=preview.json()["command"])
    assert replay.status_code == 200 and replay.json() == saved.json()


@pytest.mark.parametrize("value", [
    {"é": "中😀", "control": "\b\f\n\r\t\"\\\u0001\u001f\u2028", "null": None},
    {"中": [], "😀": {}, "é": True, "int": -(10 ** 70), "other": 10 ** 90},
])
def test_actual_postgres_canonical_json_matches_server_digest(setup, value):
    import json

    from pdos_next.service import digest

    with setup.admin.connect() as connection:
        actual = connection.scalar(text(
            "SELECT encode(sha256(convert_to(kernel_read_canonical_json(CAST(:value AS jsonb)),"
            "'UTF8')),'hex')"
        ), {"value": json.dumps(value, ensure_ascii=False)})
    assert actual == digest(value)
