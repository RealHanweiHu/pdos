"""Synthetic provenance rows only: no database, network, model, or qualification."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.computed_claim import verify_computed_claim
from pdos_next.agent_kernel.deterministic_proofs import canonical_hash
from pdos_next.agent_kernel.m3_calculators import VERSION, cost_subtotal
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, PublicWebSnapshot
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.agent_kernel.snapshot_read_ledger import page_result
from pdos_next.domain.preproject.evidence_schemas import ClaimRecord
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Category,
    Claim,
    Grant,
    Principal,
    Product,
    Receipt,
    UploadedOriginal,
)
from pdos_next.service import digest


class MemorySession:
    def __init__(self):
        self.rows, self.info = {}, {}
        self.transaction = object()

    def put(self, model, row):
        self.rows[model, row.id] = row
        return row

    def get(self, model, identity):
        return self.rows.get((model, identity))

    def get_transaction(self):
        return self.transaction

    def execute(self, query, params=None):
        return []

    def scalar(self, query, params=None):
        if not hasattr(query, "column_descriptions"):
            assert "m3_definition_root_private" in str(query)
            return self.definition_private
        model = query.column_descriptions[0]["entity"]
        ids = query.compile().params.values()
        return next((row for (kind, identity), row in self.rows.items()
                     if kind is model and identity in ids), None)

    def scalars(self, query):
        model = query.column_descriptions[0]["entity"]
        return NS(all=lambda: [row for (kind, _), row in self.rows.items() if kind is model])


def add_call(f, tool, args, result, kind="compute/v1", **metadata):
    isolation = "research" if kind == "registered_snapshot/v1" else "main"
    model_binding = dict(
        kind="model", isolation=isolation, cancel_epoch=f.run.cancel_epoch, loaded_skills=[],
        model_version="synthetic", model_route_digest="a" * 64,
        tool_definitions_digest="b" * 64, prompt_digest="c" * 64,
    )
    model = f.session.put(AgentToolCall, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, run_id=f.run.id, tool="model",
        state="completed", error_code=None, receipt_id=None, execution_binding=model_binding,
        result={"calls": [{"name": tool, "arguments": args}]},
    ))
    key = execution_key(f.run.id, model.id, 0)
    binding = ReadBinding(
        read_kind=kind, isolation=isolation, run_id=f.run.id,
        **{field: getattr(f.run, field) for field in (
            "tenant_id", "category_id", "session_id", "requester_id", "writer_id",
            "product_id", "proposal_id", "cancel_epoch", "private_context",
            "data_categories", "customer_identities",
        )},
        tool=tool, call_key=key, model_call_id=model.id, response_index=0,
        model_version="synthetic", model_route_digest="a" * 64,
        tool_definitions_digest="b" * 64, prompt_digest="c" * 64, **metadata,
    )
    call = f.session.put(AgentToolCall, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, run_id=f.run.id, tool=tool,
        state="completed", error_code=None, receipt_id=None, call_key=key,
        execution_binding=binding.model_dump(mode="json"), result=result,
        input_digest=digest([tool, args]),
    ))
    return call, model


def artifact(f, *, product_id=None):
    row = f.session.put(Artifact, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        product_id=product_id, visibility="category", revision=1, original_id=None,
        content="Unit cost 12.50 USD; quantity 2", status="active",
    ))
    f.run.read_sources.append(dict(
        artifact_id=str(row.id), expected_revision=1,
        product_id=str(product_id) if product_id else None,
    ))
    return row


def reference(row, kind="artifact"):
    return dict(type=kind, id=str(row.id), version=1, line=1,
                quote="Unit cost 12.50 USD; quantity 2")


def recalculate(f, *, primary=None):
    f.call, f.model = add_call(
        f, "calc.cost_subtotal", f.args, cost_subtotal(f.args),
        engine_version=VERSION, result_digest=canonical_hash(cost_subtotal(f.args)),
    )
    primary = primary or f.args["lines"][0]["source_ref"]
    f.payload = ClaimRecord(
        source={"kind": primary["type"], **{k: primary[k] for k in (
            "id", "version", "line", "quote",
        )}},
        nature="computed", availability="known", vendor_claimed=False,
        content=f.call.result["proof_claims"]["single_currency_subtotal"],
        extraction_ref={"call_id": str(f.call.id),
                        "result_path": ["proof_claims", "single_currency_subtotal"]},
    )


@pytest.fixture
def sample():
    f = NS(session=MemorySession())
    f.run = f.session.put(AgentRun, NS(
        id=uuid4(), tenant_id=uuid4(), category_id=uuid4(), requester_id=uuid4(),
        writer_id=uuid4(), session_id=uuid4(), product_id=None, proposal_id=None,
        private_context=False, data_categories=["public"], customer_identities=[],
        trigger="conversation", cancel_epoch=0, state="running", reverted_at=None,
        read_sources=[], versions={
            "model_version": "synthetic", "model_route_digest": "a" * 64,
            "tool_definitions": {"main": "b" * 64, "research": "b" * 64},
            "prompt_prefixes": {"main": "c" * 64, "research": "c" * 64},
        },
    ))
    f.ctx = NS(
        tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        requester_id=f.run.requester_id, actor_id=f.run.requester_id,
        run_id=None, agent_run_id=None, cancel_epoch=None,
    )
    f.session.put(Category, NS(id=f.run.category_id))
    for identity in (f.run.requester_id, f.run.writer_id):
        f.session.put(Principal, NS(id=identity, tenant_id=f.run.tenant_id, active=True))
        f.session.put(Grant, NS(id=uuid4(), principal_id=identity, expires_at=None))
    f.artifact = artifact(f)
    f.args = {"lines": [dict(label="Part", qty="2", unit_cost="12.50", currency="USD",
                             as_of="2026-10-11", source_ref=reference(f.artifact))]}
    recalculate(f)
    return f


def verify(f):
    return verify_computed_claim(f.session, f.ctx, f.run, f.payload)


def test_real_engine_complete_result_is_accepted_without_mutating_inputs(sample):
    f = sample
    before = deepcopy((f.payload.model_dump(mode="json"), f.args, vars(f.run)))
    proof = verify(f)
    assert proof["engine_version"] == VERSION
    assert proof["call_id"] == str(f.call.id)
    assert f.payload.content["value"] == "25.00"
    assert before == (f.payload.model_dump(mode="json"), f.args, vars(f.run))


def test_plain_human_cannot_supply_computed_provenance_without_run(sample):
    with pytest.raises(DomainError):
        verify_computed_claim(sample.session, sample.ctx, None, sample.payload)


@pytest.mark.parametrize("field,value", [
    ("nature", "observed"), ("nature", "decided"), ("nature", "inferred"),
    ("availability", "unknown"), ("availability", "conflicted"), ("vendor_claimed", True),
    ("extraction_ref", "looks like a math receipt"),
])
def test_computation_cannot_promote_other_nature_or_missing_proof(sample, field, value):
    setattr(sample.payload, field, value)
    with pytest.raises(DomainError):
        verify(sample)


@pytest.mark.parametrize("change", ["extra_content", "wrong_value", "missing_field",
                                    "extra_ref_field", "wrong_path", "forged_hash"])
def test_proof_is_exact_and_must_recompute(sample, change):
    f = sample
    if change == "extra_content":
        f.payload.content["text"] = "Independently verified market price"
    elif change == "wrong_value":
        f.payload.content["value"] = "999"
    elif change == "missing_field":
        del f.payload.content["condition_note"]
    elif change == "extra_ref_field":
        f.payload.extraction_ref["qualified"] = True
    elif change == "wrong_path":
        f.payload.extraction_ref["result_path"] = ["subtotal"]
    else:
        f.call.result["proof_claims"]["single_currency_subtotal"]["value"] = "999"
        f.payload.content["value"] = "999"
        f.call.execution_binding["result_digest"] = canonical_hash(f.call.result)
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("field,value", [
    ("state", "started"), ("tool", "model"), ("run_id", uuid4()),
    ("input_digest", "f" * 64), ("receipt_id", uuid4()),
])
def test_actual_completed_compute_call_is_required(sample, field, value):
    setattr(sample.call, field, value)
    with pytest.raises(DomainError):
        verify(sample)


@pytest.mark.parametrize("change", ["unreadable", "withdrawn", "version", "line", "quote",
                                    "not_read", "read_version", "read_product",
                                    "missing_product", "product", "private", "original_private"])
def test_each_source_must_remain_current_read_and_public(sample, change):
    f = sample
    second = artifact(f)
    f.args["lines"].append({**f.args["lines"][0], "source_ref": reference(second)})
    recalculate(f)
    if change == "unreadable":
        del f.session.rows[Artifact, second.id]
    elif change == "withdrawn":
        second.status = "withdrawn"
    elif change == "version":
        second.revision = 2
    elif change in {"line", "quote"}:
        f.args["lines"][1]["source_ref"][change] = 9 if change == "line" else "invented quote"
        recalculate(f)
    elif change == "not_read":
        f.run.read_sources.pop()
    elif change == "read_version":
        f.run.read_sources[-1]["expected_revision"] = 2
    elif change == "read_product":
        f.run.read_sources[-1]["product_id"] = str(uuid4())
    elif change == "missing_product":
        del f.run.read_sources[-1]["product_id"]
    elif change == "product":
        second.product_id = uuid4()
    elif change == "private":
        second.visibility = "private"
    else:
        second.original_id = uuid4()
        f.session.put(UploadedOriginal, NS(
            id=second.original_id, tenant_id=f.run.tenant_id, category_id=f.run.category_id,
            product_id=None, visibility="private", status="parsed", scan_status="clean",
        ))
    with pytest.raises(DomainError):
        verify(f)


def test_primary_source_cannot_be_an_unrelated_readable_artifact(sample):
    unrelated = artifact(sample)
    sample.payload.source.id = unrelated.id
    with pytest.raises(DomainError, match="计算事实") as error:
        verify(sample)
    assert error.value.detail["reason"] == "compute_primary_source_mismatch"


def test_legacy_primary_uses_actual_input_version_and_read_binding(sample):
    f = sample
    f.payload = ClaimRecord(
        artifact_id=f.artifact.id, line=1, quote=f.artifact.content, statement="subtotal",
        nature="computed", content=f.payload.content, extraction_ref=f.payload.extraction_ref,
    )
    assert verify(f)["call_id"] == str(f.call.id)
    f.run.read_sources[0]["expected_revision"] = 2
    with pytest.raises(DomainError):
        verify(f)


def test_unused_fx_source_is_still_validated(sample):
    f = sample
    fx = artifact(f)
    f.args["fx"] = [dict(pair="EUR/USD", rate="1.1", as_of="2026-10-11",
                         source_ref=reference(fx))]
    recalculate(f)
    assert verify(f)
    del f.session.rows[Artifact, fx.id]
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("field,value", [("private_context", True),
    ("customer_identities", ["Actual customer"]), ("data_categories", ["customer"])])
def test_actual_private_or_customer_context_has_no_outbound_bypass(sample, field, value):
    setattr(sample.run, field, value)
    recalculate(sample)
    with pytest.raises(DomainError) as error:
        verify(sample)
    assert error.value.detail["reason"] == "private_material_context_binding_required"


def test_current_source_product_is_pinned_and_private_parent_denies(sample):
    f = sample
    product = f.session.put(Product, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        visibility="category",
    ))
    f.run.product_id = product.id
    f.artifact.product_id = product.id
    f.run.read_sources[0]["product_id"] = str(product.id)
    recalculate(f)
    assert verify(f)
    product.visibility = "private"
    with pytest.raises(DomainError):
        verify(f)


def add_snapshot(f):
    body = "Unit cost 12.50 USD; quantity 2\nUnseen source line"
    snapshot = f.session.put(PublicWebSnapshot, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        owner_id=uuid4(), registered_by_run_id=uuid4(), receipt_id=uuid4(),
        visibility="category", status="ok", url="https://synthetic.test/source",
        final_url="https://synthetic.test/source", markdown=body,
        content_hash=sha256(body.encode()).hexdigest(),
    ))
    actor = f.session.put(Principal, NS(id=uuid4(), tenant_id=f.run.tenant_id, kind="agent"))
    f.session.put(Receipt, NS(
        id=snapshot.receipt_id, tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        requester_id=snapshot.owner_id, actor_id=actor.id, subject_revision=1,
        run_id=None, agent_run_id=snapshot.registered_by_run_id,
        operation="research.snapshot.register", subject_type="public_web_snapshot",
        subject_id=snapshot.id, result={
            "proof_version": 1,
            "registered_by_run_id": str(snapshot.registered_by_run_id),
            "snapshot_id": str(snapshot.id), "content_hash": snapshot.content_hash,
        },
    ))
    call, _ = add_call(
        f, "research.read", {"url": snapshot.url, "cursor": 0},
        page_result(snapshot, cursor=0, page_chars=31), "registered_snapshot/v1", page_chars=31,
    )
    f.args["lines"][0]["source_ref"] = reference(snapshot, "snapshot")
    recalculate(f)
    return snapshot, call


def test_cross_run_snapshot_requires_actual_registered_page_read(sample):
    snapshot, call = add_snapshot(sample)
    assert snapshot.registered_by_run_id != sample.run.id
    assert verify(sample)
    del sample.session.rows[AgentToolCall, call.id]
    with pytest.raises(DomainError) as error:
        verify(sample)
    assert error.value.detail["reason"] == "snapshot_read_not_bound"


@pytest.mark.parametrize("change", ["registration_only", "ordinary", "wrong_run", "unseen",
                                    "partial_binding", "private", "withdrawn", "changed_body"])
def test_snapshot_registration_or_model_labels_cannot_replace_read_proof(sample, change):
    f = sample
    snapshot, call = add_snapshot(f)
    if change == "registration_only":
        snapshot.registered_by_run_id = f.run.id
        del f.session.rows[AgentToolCall, call.id]
    elif change == "ordinary":
        call.execution_binding["read_kind"] = "ordinary/v1"
    elif change == "wrong_run":
        call.run_id = uuid4()
    elif change == "unseen":
        f.args["lines"][0]["source_ref"].update(line=2, quote="Unseen source line")
        recalculate(f)
    elif change == "partial_binding":
        del call.execution_binding["customer_identities"]
    elif change == "private":
        snapshot.visibility = "private"
    elif change == "withdrawn":
        snapshot.status = "withdrawn"
    else:
        snapshot.markdown += " tampered"
    with pytest.raises(DomainError):
        verify(f)


def test_claim_input_revalidates_root_read_and_current_claim_state(sample):
    f = sample
    root = artifact(f)
    claim = f.session.put(Claim, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        product_id=None, proposal_id=None, status="active", revision=1,
        privacy="shared", visibility="category", source_kind="artifact",
        artifact_id=root.id, source_revision=1, line=1, quote=root.content,
    ))
    f.args["lines"].append({**f.args["lines"][0], "source_ref": reference(claim, "claim")})
    recalculate(f)
    assert verify(f)
    f.run.read_sources.pop()
    with pytest.raises(DomainError) as error:
        verify(f)
    assert error.value.detail["reason"] == "source_read_not_bound"
    claim.status = "withdrawn"
    with pytest.raises(DomainError) as error:
        verify(f)
    assert error.value.detail["reason"] == "claim_withdrawn"


@pytest.mark.parametrize("change", ["private_claim", "private_root", "stale_root"])
def test_claim_input_cannot_hide_private_or_stale_roots(sample, change):
    f = sample
    root = artifact(f)
    claim = f.session.put(Claim, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        product_id=None, proposal_id=None, status="active", revision=1,
        privacy="shared", visibility="category", source_kind="artifact",
        artifact_id=root.id, source_revision=1, line=1, quote=root.content,
    ))
    f.args["lines"].append({**f.args["lines"][0], "source_ref": reference(claim, "claim")})
    recalculate(f)
    if change == "private_claim":
        claim.privacy = "private"
    elif change == "private_root":
        root.visibility = "private"
    else:
        root.revision = 2
    with pytest.raises(DomainError):
        verify(f)


@pytest.mark.parametrize("change", ["private_root", "stale_root", "withdrawn", "version"])
def test_knowledge_input_reuses_current_access_and_recursive_root_privacy(sample, change):
    from pdos_next.domain.preproject.category_models import KnowledgeCurrent, KnowledgeEntry

    f = sample
    root = artifact(f)
    knowledge = f.session.put(KnowledgeEntry, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id,
        lineage_id=uuid4(), version=1, action="publish", source_refs=[reference(root)],
    ))
    current = NS(status="active", current_entry_id=knowledge.id, current_version=1)
    f.session.rows[KnowledgeCurrent, (f.run.tenant_id, knowledge.lineage_id)] = current
    f.args["lines"].append({**f.args["lines"][0],
                          "source_ref": reference(knowledge, "knowledge")})
    recalculate(f)
    assert verify(f)
    if change == "private_root":
        root.visibility = "private"
    elif change == "stale_root":
        root.revision = 2
    elif change == "withdrawn":
        current.status = "withdrawn"
    else:
        knowledge.version = 2
    with pytest.raises(DomainError):
        verify(f)


def test_definition_input_requires_authoritative_private_root_check(sample):
    from pdos_next.domain.products.models import DefinitionRevision

    f = sample
    definition = f.session.put(DefinitionRevision, NS(
        id=uuid4(), tenant_id=f.run.tenant_id, category_id=f.run.category_id, revision=1,
    ))
    f.session.definition_private = False
    f.args["lines"].append({**f.args["lines"][0],
                          "source_ref": reference(definition, "definition")})
    recalculate(f)
    assert verify(f)
    f.session.definition_private = True
    with pytest.raises(DomainError):
        verify(f)
