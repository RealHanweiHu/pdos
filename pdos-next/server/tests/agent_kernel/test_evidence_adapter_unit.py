"""Trusted evidence adapter inputs, source bindings and dispatch; no database or model."""

from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import domain_adapter as module
from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.domain_adapter import DomainCommands
from pdos_next.agent_kernel.models import AgentRun, AgentToolCall, PublicWebSnapshot
from pdos_next.agent_kernel.registry import PREPARE_ONLY
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import RunScope
from pdos_next.errors import DomainError
from pdos_next.models import Receipt


class MemorySession:
    def __init__(self, rows):
        self.rows = {(model, row.id): row for model, row in rows}
        self.info = {}

    def get(self, model, identity):
        return self.rows.get((model, identity))

    def scalars(self, query):
        assert query.column_descriptions[0]["entity"] is AgentToolCall
        # This adapter fixture contains no read Call: another Run's registration
        # cannot provide current-Run page authority.
        assert not any(model is AgentToolCall for model, _ in self.rows)
        return SimpleNamespace(all=lambda: [])


@pytest.fixture
def bound(monkeypatch):
    scope = RunScope(*(uuid4() for _ in range(6)), proposal_id=uuid4())
    fields = asdict(scope)
    fields["id"] = fields.pop("run_id")
    run = SimpleNamespace(**fields, state="running", reverted_at=None, read_sources=[])
    session = MemorySession([(AgentRun, run)])
    adapter = DomainCommands(None, catalog=None, registry=default_registry(), route=None)
    monkeypatch.setattr(module, "require_access", lambda *_a, **_k: SimpleNamespace(revision=3))
    return SimpleNamespace(scope=scope, run=run, session=session, adapter=adapter)


def canonical(identity, *, kind="artifact", version=1):
    return {
        "source": {
            "kind": kind,
            "id": str(identity),
            "version": version,
            "locator": "line:1",
            "quote": "exact text",
        },
        "nature": "extracted",
        "availability": "known",
        "content": {"text": "supported fact"},
    }


def command(f, arguments, operation="evidence.claim.record"):
    return f.adapter.command(f.session, f.scope, operation, arguments, "synthetic-command-key")


def snapshot(f):
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=f.run.tenant_id,
        category_id=f.run.category_id,
        status="ok",
        registered_by_run_id=f.run.id,
        receipt_id=uuid4(),
    )
    receipt = SimpleNamespace(
        id=row.receipt_id,
        tenant_id=f.run.tenant_id,
        category_id=f.run.category_id,
        requester_id=f.run.requester_id,
        operation="research.snapshot.register",
        subject_type="public_web_snapshot",
        subject_id=row.id,
        subject_revision=1,
        agent_run_id=f.run.id,
    )
    f.session.rows[(PublicWebSnapshot, row.id)] = row
    f.session.rows[(Receipt, receipt.id)] = receipt
    return row, receipt


def assert_reason(error, code, reason):
    assert error.value.code == code and error.value.detail["reason"] == reason


@pytest.mark.parametrize("legacy", [False, True])
def test_artifact_claim_keeps_real_read_version_and_server_proposal_binding(bound, legacy):
    identity = uuid4()
    bound.run.read_sources = [
        {"artifact_id": str(identity), "expected_revision": 2, "product_id": None}
    ]
    args = canonical(identity, version=2)
    if legacy:
        args = {
            "artifact_id": str(identity),
            "line": 1,
            "quote": "exact text",
            "statement": "supported fact",
            "visibility": "private",
        }
    actual = command(bound, args)
    assert actual.category_id == bound.run.category_id
    assert actual.product_id is None and actual.expected_revision == 3
    assert actual.payload["proposal_id"] == str(bound.run.proposal_id)
    assert [(read.artifact_id, read.expected_revision) for read in actual.source_read_set] == [
        (identity, 2)
    ]
    assert "proposal_id" not in args


def test_snapshot_claim_does_not_treat_legacy_artifact_none_as_a_missing_read(bound):
    source, _ = snapshot(bound)
    actual = command(bound, canonical(source.id, kind="snapshot"))
    assert actual.source_read_set == []
    assert actual.payload["source"]["id"] == str(source.id)
    assert "artifact_id" not in actual.payload


@pytest.mark.parametrize("version", [1, 3])
def test_canonical_artifact_version_must_equal_actual_run_read(bound, version):
    identity = uuid4()
    bound.run.read_sources = [{"artifact_id": str(identity), "expected_revision": 2}]
    with pytest.raises(DomainError) as error:
        command(bound, canonical(identity, version=version))
    assert_reason(error, "MISSING_REQUIRED_EVIDENCE", "source_read_not_bound")


def test_unread_artifact_cannot_be_claimed_merely_because_the_model_supplies_a_version(bound):
    with pytest.raises(DomainError) as error:
        command(bound, canonical(uuid4()))
    assert_reason(error, "MISSING_REQUIRED_EVIDENCE", "source_read_not_bound")


@pytest.mark.parametrize(
    "bad_reads",
    [
        [{}],
        [{"artifact_id": "not-a-uuid", "expected_revision": 1}],
        [{"artifact_id": str(uuid4()), "expected_revision": 1, "product_id": "not-a-uuid"}],
    ],
)
def test_malformed_or_out_of_scope_read_ledger_fails_closed(bound, bad_reads):
    bound.run.read_sources = bad_reads
    with pytest.raises(DomainError) as error:
        command(bound, canonical(uuid4()))
    assert_reason(error, "SOURCE_UNAVAILABLE", "run_source_binding_invalid")


def test_category_run_keeps_source_product_while_product_run_rejects_another(bound):
    from dataclasses import replace

    identity, product = uuid4(), uuid4()
    bound.run.read_sources = [
        {"artifact_id": str(identity), "expected_revision": 1, "product_id": str(product)}
    ]
    actual = command(bound, canonical(identity))
    assert actual.product_id is None and actual.source_read_set[0].artifact_id == identity
    bound.scope = replace(bound.scope, product_id=uuid4())
    bound.run.product_id = bound.scope.product_id
    with pytest.raises(DomainError) as error:
        command(bound, canonical(identity))
    assert_reason(error, "SOURCE_UNAVAILABLE", "run_source_binding_invalid")


def test_conflicting_read_versions_cannot_be_collapsed_to_last_value(bound):
    identity = uuid4()
    bound.run.read_sources = [
        {"artifact_id": str(identity), "expected_revision": 1},
        {"artifact_id": str(identity), "expected_revision": 2},
    ]
    with pytest.raises(DomainError) as error:
        command(bound, canonical(identity, version=2))
    assert_reason(error, "SOURCE_UNAVAILABLE", "run_source_binding_invalid")


@pytest.mark.parametrize(
    "field", ["tenant_id", "category_id", "requester_id", "writer_id", "proposal_id", "session_id"]
)
def test_caller_scope_cannot_replace_real_run_facts(bound, field):
    setattr(bound.run, field, uuid4())
    with pytest.raises(DomainError) as error:
        command(bound, canonical(uuid4()))
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert "服务器实际运行" in str(error.value)


def test_model_cannot_select_another_proposal_even_with_a_readable_source(bound):
    source, _ = snapshot(bound)
    args = canonical(source.id, kind="snapshot")
    args["proposal_id"] = str(uuid4())
    with pytest.raises(DomainError) as error:
        command(bound, args)
    assert_reason(error, "FORBIDDEN_SCOPE", "proposal_run_mismatch")


@pytest.mark.parametrize(
    "field,value",
    [
        ("privacy", "shared"),
        ("origin", "human"),
        ("writer_id", str(uuid4())),
        ("run_id", str(uuid4())),
        ("confirmed_by", str(uuid4())),
    ],
)
def test_model_cannot_supply_privacy_or_provenance_fields(bound, field, value):
    source, _ = snapshot(bound)
    args = canonical(source.id, kind="snapshot")
    args[field] = value
    with pytest.raises(ValidationError):
        command(bound, args)


@pytest.mark.parametrize(
    "mutation",
    [
        "tenant",
        "category",
        "version",
        "status",
        "other_run",
        "receipt_missing",
        "receipt_subject",
        "receipt_run",
    ],
)
def test_snapshot_requires_same_run_registration_scope_and_actual_receipt(bound, mutation):
    source, receipt = snapshot(bound)
    args = canonical(source.id, kind="snapshot")
    reason = "snapshot_unavailable"
    if mutation in {"tenant", "category"}:
        setattr(source, f"{mutation}_id", uuid4())
    elif mutation == "version":
        args["source"]["version"] = 2
    elif mutation == "status":
        source.status = "failed"
    elif mutation == "other_run":
        source.registered_by_run_id = uuid4()
        reason = "snapshot_read_not_bound"
    else:
        reason = "snapshot_registration_invalid"
        if mutation == "receipt_missing":
            del bound.session.rows[(Receipt, receipt.id)]
        elif mutation == "receipt_subject":
            receipt.subject_id = uuid4()
        else:
            receipt.agent_run_id = uuid4()
    with pytest.raises(DomainError) as error:
        command(bound, args)
    assert_reason(error, "SOURCE_UNAVAILABLE", reason)


def test_registered_human_snapshot_receipt_is_bound_by_snapshot_actual_run(bound):
    source, receipt = snapshot(bound)
    receipt.agent_run_id = None
    assert command(bound, canonical(source.id, kind="snapshot")).payload["source"]["id"] == str(
        source.id
    )


def test_link_artifact_reference_uses_real_run_read_ledger(bound):
    evidence_id = uuid4()
    args = {
        "evidence": {"type": "artifact", "id": str(evidence_id), "version": 1},
        "target": {"type": "proposal_item", "id": str(uuid4()), "version": 1},
        "relation": "supports",
    }
    with pytest.raises(DomainError) as error:
        command(bound, args, "evidence.link.create")
    assert_reason(error, "MISSING_REQUIRED_EVIDENCE", "source_read_not_bound")
    bound.run.read_sources = [{"artifact_id": str(evidence_id), "expected_revision": 1}]
    assert command(bound, args, "evidence.link.create").operation == "evidence.link.create"


@pytest.mark.parametrize("operation", ["evidence.claim.withdraw", "proposal.share"])
def test_t1_withdraw_and_prepare_only_share_never_dispatch_as_ai_t0(bound, operation, monkeypatch):
    monkeypatch.setattr(bound.adapter, "recover", lambda *_a, **_k: pytest.fail("No AI execution"))
    with pytest.raises(DomainError) as error:
        bound.adapter.execute(bound.scope, operation, {}, "synthetic", source=None)
    assert error.value.code == "NAMED_DECISION_REQUIRED"
    assert "proposal.share" in PREPARE_ONLY
    assert bound.adapter.registry.get("proposal.share").operation_key is None
    assert bound.adapter.registry.get("evidence.claim.withdraw").tier == "T1"


def test_link_t0_dispatch_passes_server_run_and_completed_call_to_common_owner(bound, monkeypatch):
    args = {
        "evidence": {"type": "claim", "id": str(uuid4()), "version": 1},
        "target": {"type": "proposal_item", "id": str(uuid4()), "version": 1},
        "relation": "supports",
    }
    call = SimpleNamespace(id=uuid4())
    receipt_id = uuid4()
    seen = []
    monkeypatch.setattr(bound.adapter, "recover", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "command_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "category_transaction", lambda _engine, _ctx, fn: fn(bound.session))
    monkeypatch.setattr(module, "prepare_domain_call", lambda *_a, **_k: (call, None))

    def common_owner(session, ctx, cmd):
        seen.append(ctx)
        assert session.info["domain_command_owner"] is bound.adapter
        assert ctx.actor_id == bound.run.writer_id and ctx.requester_id == bound.run.requester_id
        assert ctx.agent_run_id == bound.run.id and ctx.agent_call_id == call.id
        receipt = SimpleNamespace(
            id=receipt_id,
            agent_run_id=ctx.agent_run_id,
            command_id=cmd.command_id,
            request_digest=module.command_digest(cmd),
        )
        session.rows[(Receipt, receipt_id)] = receipt
        return {"id": str(receipt_id)}

    def complete(_session, scope, call_id, identity):
        assert scope is bound.scope and call_id == call.id and identity == receipt_id
        return {"id": str(identity), "agent_call_id": str(call_id)}

    monkeypatch.setattr(module, "execute", common_owner)
    monkeypatch.setattr(module, "finish_domain_call", complete)
    result = bound.adapter.execute(
        bound.scope,
        "evidence.link.create",
        args,
        execution_key(bound.run.id, uuid4(), 0),
        source=None,
    )
    assert result["agent_call_id"] == str(call.id) and len(seen) == 1
