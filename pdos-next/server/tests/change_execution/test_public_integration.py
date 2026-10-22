"""No-connect actual DTO/kernel/ORM seam checks; owner IO is expressly substituted."""

import ast
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import httpx
import psycopg
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pdos_next import change_completion_adapter as completion
from pdos_next import change_order_integration as order
from pdos_next import change_order_service as owner
from pdos_next import change_public_integration as startup
from pdos_next import change_selection_integration as selection
from pdos_next import change_selection_service
from pdos_next.command_handlers import (
    LIVE_CONSUMPTION_OPERATIONS,
    PHASED_MATERIAL_OPERATIONS,
    T1_OPERATIONS,
    T2_OPERATIONS,
    handler,
)
from pdos_next.contracts import PAYLOADS, Command
from pdos_next.domain.change_execution import service as old
from pdos_next.errors import DomainError
from pdos_next.models import Base
from pdos_next.service import Context

from . import kernel_helpers as helper


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No database or HTTP is permitted in these controls")

    for cls, name in ((Engine, "connect"), (Engine, "raw_connection"), (httpx.Client, "request")):
        monkeypatch.setattr(cls, name, forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(helper, "NOW", datetime.now(UTC))


def rejected(code, callback):
    with pytest.raises(DomainError) as error:
        callback()
    assert error.value.reason == code


@pytest.mark.parametrize(
    "operation,tier,module",
    [
        ("change.order.prepare", "T1", order),
        ("change.order.approve", "T2", order),
        ("change.implementation.record", "T1", order),
        ("change.selection.decide", "T2", selection),
    ],
)
def test_closed_actual_shared_registry_and_phase_contract(operation, tier, module):
    assert handler(operation) is module
    assert operation in PHASED_MATERIAL_OPERATIONS & LIVE_CONSUMPTION_OPERATIONS
    assert operation in (T1_OPERATIONS if tier == "T1" else T2_OPERATIONS)
    assert callable(module.prepare_preview) and callable(module.preview_prepared)
    assert callable(module.prepare_write_review) and callable(module.bind_consumption)
    assert callable(module.record_consumption) and callable(module.apply_prepared_write)
    assert PAYLOADS[operation] in (*owner.PAYLOADS.values(), change_selection_service.Payload)


def test_host_policy_is_never_public_payload_or_command_handler():
    assert "change.policy.import" not in PAYLOADS
    assert "change.policy.import" not in T1_OPERATIONS | T2_OPERATIONS
    assert handler("change.policy.import") is None


def test_real_approval_mutation_preview_preserves_old_clocks_and_labels_only_new_clocks():
    h = helper.FakeHost()
    h.prepare()
    before = h.request_value
    h.actor("other-engineer", ("engineering",))
    h.run(
        "change.order.approve",
        {
            "discipline": "engineering",
            "text": "Actual named engineering approval",
            "expires_at": helper.NOW + timedelta(hours=1),
        },
    )
    after = h.request_value
    raw = owner._proposed_snapshot(after, before, "change.order.approve")
    assert raw["history"][:-1] == before.model_dump(mode="json")["history"]
    assert raw["history"][-1]["at"] == "server_on_save"
    assert raw["orders"][-1]["approvals"][-1]["at"] == "server_on_save"
    assert raw["orders"][-1]["approvals"][-1]["decision_id"] == (
        "actual_consumed_named_proof_on_save"
    )
    assert after.history[-1].at == helper.NOW  # Actual mutation is not rewritten.
    json.dumps(raw, allow_nan=False)


def test_selection_delegates_one_atom_to_real_shared_receipt_tail(monkeypatch):
    row = SimpleNamespace(visibility="category")
    seen = []
    monkeypatch.setattr(
        selection.owner,
        "apply_prepared_write",
        lambda *a, **k: seen.append(k["consumption"]) or row,
    )
    proof_pair = (object(), object())
    assert selection.apply_prepared_write(
        None, None, None, None, None, None, consumption=proof_pair
    ) == (row, "change_selection_fact", "category")
    assert seen == [proof_pair]


def test_same_semantic_replay_returns_actual_row_for_common_receipt_lookup(monkeypatch):
    identity = uuid4()
    row = SimpleNamespace(id=identity)
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=CategoryUUID(int=1000000))
    product = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(selection.owner, "replay_subject", lambda *a: identity)
    seen = []
    monkeypatch.setattr(selection, "_one", lambda *a: seen.extend(a[2:]) or row)
    assert selection.replay_subject(None, ctx, None, product, None) is row
    assert len(seen) == 3  # Exact tenant/product/id, never a bare UUID or latest row.
    assert selection.replay_subject_type(None) == "change_selection_fact"


def test_prepare_preview_checks_real_product_watermark_before_owner_io(monkeypatch):
    product = SimpleNamespace(id=uuid4(), revision=3)
    command = Command(
        command_id=uuid4(),
        idempotency_key="actual-key",
        operation="change.order.prepare",
        product_id=product.id,
        expected_revision=2,
        payload={},
        category_id=CategoryUUID(int=1000000),
    )
    monkeypatch.setattr(owner, "read_phase", lambda *a, **k: pytest.fail("Unexpected owner IO"))
    rejected("VERSION_CONFLICT", lambda: order.prepare_preview(None, None, command, product, None))


def test_default_startup_does_not_create_publisher_or_qualification(monkeypatch):
    engine = SimpleNamespace()
    assert startup.configure(engine) is None
    assert not hasattr(engine, "_pdos_professional_issuers")
    assert not hasattr(engine, "_pdos_quality_followup")
    s = Session()
    monkeypatch.setattr(s, "get_bind", lambda: SimpleNamespace())
    with s.begin():
        # Source owners are genuinely absent; configuration is not a grant.
        rejected("CHANGE_OWNER_INTEGRATION_REQUIRED", lambda: owner.runtime(s))
    s.close()


def occurrence_work():
    ctx = Context(
        helper.SCOPE.tenant_id,
        helper.uid("executor"),
        helper.uid("executor"),
        category_id=CategoryUUID(int=1000000),
    )
    binding = SimpleNamespace(
        action_id=helper.uid("action"), action_sha256="a" * 64, executor_id=ctx.requester_id
    )
    basis = SimpleNamespace(
        scope=helper.SCOPE,
        issue_id=helper.uid("issue"),
        capa_id=helper.uid("capa"),
        purpose="actual controlled change",
        nature="synthetic",
        actions=(binding,),
    )
    actual = completion.Occurrence(
        schema_version=completion.SCHEMA,
        scope=basis.scope,
        issue_id=basis.issue_id,
        capa_id=basis.capa_id,
        action_id=binding.action_id,
        action_sha256=binding.action_sha256,
        purpose=basis.purpose,
        change_id=helper.uid("change"),
        order_id=helper.uid("order"),
        implementation_id=helper.uid("implementation"),
        reconciles_id=None,
        item_id=helper.uid("item"),
        intent_id=helper.uid("intent"),
        executor_id=ctx.requester_id,
        operation="change.implementation.record",
        outcome="succeeded",
        occurred_at=helper.NOW,
        original_timezone="UTC",
        sources=(helper.SOURCE,),
        outputs=(),
        note="Actual controlled implementation",
        nature="synthetic",
    )
    done = SimpleNamespace(
        at=SimpleNamespace(occurred_at=helper.NOW + timedelta(seconds=1)), evidence=(helper.SOURCE,)
    )
    return ctx, basis, binding, actual, done


@pytest.mark.parametrize(
    "changed", ["scope", "executor_id", "action_sha256", "outcome", "occurred_at"]
)
def test_formal_completion_never_accepts_other_scope_executor_action_unknown_or_later_event(
    changed,
):
    ctx, basis, binding, actual, done = occurrence_work()
    values = dict(
        scope=helper.SCOPE.model_copy(update={"project_id": uuid4()}),
        executor_id=uuid4(),
        action_sha256="b" * 64,
        outcome="unknown",
        occurred_at=done.at.occurred_at + timedelta(microseconds=1),
    )
    wrong = actual.model_copy(update={changed: values[changed]})
    rejected(
        "ACTION_IMPLEMENTATION_MISMATCH",
        lambda: completion._matches(wrong, basis, binding, done, ctx),
    )


def test_valid_occurrence_is_only_structure_not_approved_implementation(monkeypatch):
    ctx, basis, binding, actual, done = occurrence_work()
    completion._matches(actual, basis, binding, done, ctx)
    engine = SimpleNamespace()
    assessor = completion.FormalChangeCompletionOwner(engine)
    s = Session()
    monkeypatch.setattr(s, "get_bind", lambda: engine)
    monkeypatch.setattr(
        completion.controlled,
        "_caller",
        lambda *a, **k: (("actual",), helper.NOW + timedelta(hours=1)),
    )
    monkeypatch.setattr(completion.controlled, "_project", lambda *a: (None, ("same",)))
    monkeypatch.setattr(completion.change, "_runtime_stamp", lambda *a: "runtime")
    monkeypatch.setattr(completion, "_is_occurrence", lambda *a: True)
    monkeypatch.setattr(completion, "original_occurrence", lambda *a: (actual, None))
    monkeypatch.setattr(s, "scalars", lambda *a: ())
    action = SimpleNamespace(id=binding.action_id)
    with s.begin():
        rejected(
            "IMPLEMENTATION_OWNER_REQUIRED",
            lambda: assessor(
                s,
                ctx,
                helper.SCOPE.product_id,
                basis,
                action,
                done,
                policy_snapshot={},
                observation=None,
            ),
        )
    s.close()


def test_no_classification_owner_is_explicit_missing_not_default_investigation(monkeypatch):
    ctx, basis, binding, _, done = occurrence_work()
    engine = SimpleNamespace()
    assessor = completion.FormalChangeCompletionOwner(engine)
    s = Session()
    monkeypatch.setattr(s, "get_bind", lambda: engine)
    monkeypatch.setattr(
        completion.controlled,
        "_caller",
        lambda *a, **k: (("actual",), helper.NOW + timedelta(hours=1)),
    )
    monkeypatch.setattr(completion.controlled, "_project", lambda *a: (None, ("same",)))
    monkeypatch.setattr(completion.change, "_runtime_stamp", lambda *a: "runtime")
    monkeypatch.setattr(completion, "_is_occurrence", lambda *a: False)
    with s.begin():
        rejected(
            "INTEGRATION_REQUIRED",
            lambda: assessor(
                s,
                ctx,
                helper.SCOPE.product_id,
                basis,
                SimpleNamespace(id=binding.action_id),
                done,
                policy_snapshot={},
                observation=None,
            ),
        )
    s.close()


def test_fixed_reader_keeps_actual_order_chain_but_old_preparation_boundary_remains():
    h = helper.FakeHost()
    h.prepare()
    value = h.request_value
    row = SimpleNamespace(
        tenant_id=value.scope.tenant_id,
        product_id=value.scope.product_id,
        project_id=value.scope.project_id,
        change_id=value.id,
        revision=value.revision,
        status=value.status,
        request_snapshot=value.model_dump(mode="json"),
        request_sha256=owner.digest(value),
        operation="change.order.prepare",
    )
    assert old._snapshot(row) == value
    row.operation = "change.impact.compute"
    rejected("INTEGRITY_MISMATCH", lambda: old._snapshot(row))


def test_archived_migration27_retains_frozen_eight_tables_and_old_guards():
    server = Path(__file__).resolve().parents[2]
    path = server / "migrations/archive/pre-s0/versions/0027_controlled_change_orders.py"
    source = path.read_text()
    constants = {}
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            constants[node.targets[0].id] = ast.literal_eval(node.value)
    assert constants["revision"] == "next_0027"
    assert constants["down_revision"] == constants["EXPECTED_PARENT"] == "next_0026"
    assert len(constants["TABLES"]) == 8 and len(constants["DROP_TABLES"]) == 8
    assert all(n in Base.metadata.tables for n in constants["TABLES"])
    assert "quality.issue.merge" in constants["EXTENDED_RECEIPT_HELPER"]
    assert "CapaVerificationCandidateRecorded" in constants["EXTENDED_RECEIPT_HELPER"]
    for operation in (
        "change.order.prepare",
        "change.order.approve",
        "change.implementation.record",
    ):
        assert operation in constants["EXTENDED_RECEIPT_HELPER"]
    assert "require_quality_change_atom" not in constants["CONTROLLED_GUARDS"]
    assert "CASCADE" not in constants["DOWNGRADE_PREFLIGHT"]
    assert constants["DOWNGRADE_PREFLIGHT"].startswith("LOCK TABLE ")
    for table in constants["TABLES"]:
        assert f"EXISTS(SELECT 1 FROM {table})" in constants["DOWNGRADE_PREFLIGHT"]
    for table in ("change_request_versions", "confirmations", "action_receipts"):
        assert f"EXISTS(SELECT 1 FROM {table}" in constants["DOWNGRADE_PREFLIGHT"]
    assert "retained change history prevents downgrade" in constants["DOWNGRADE_PREFLIGHT"]
    assert "FROM PUBLIC,pdos_next_app,pdos_agent" in "\n".join(constants["PERMISSIONS"])
    assert hashlib.sha256(constants["OLD_RECEIPT_HELPER"].encode()).hexdigest() in source
    tree = ast.parse(source)
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imports == ["alembic", "sqlalchemy"]  # All SQL is embedded, no live model/stage reads.
    downgrade = next(
        node for node in tree.body if getattr(node, "name", None) == "downgrade_candidate"
    )
    assert "CASCADE" not in ast.get_source_segment(source, downgrade)
    assert ast.unparse(downgrade.body[0]) == "op.execute(DOWNGRADE_PREFLIGHT)"


def test_new_professional_matrix_uses_only_actual_existing_fact_role_types():
    from typing import get_args

    from pdos_next.domain.professional_authority.schemas import FactInput
    from pdos_next.domain.professional_authority.service import OPERATION_ROLES

    available = set(get_args(FactInput.model_fields["role"].annotation))
    for name in (*owner.PAYLOADS, "change.selection.decide", "change.policy.import"):
        assert OPERATION_ROLES[name] <= available


def test_malformed_formal_claim_cannot_fall_back_to_investigation(monkeypatch):
    line = '{"schema_version":"' + completion.SCHEMA + '","scope":1,"scope":2}'
    source = helper.SOURCE.model_copy(
        update={"position": "line:1;quote_sha256:" + hashlib.sha256(line.encode()).hexdigest()}
    )
    monkeypatch.setattr(completion, "source_for", lambda *a: SimpleNamespace(content=line))
    rejected(
        "MISSING_REQUIRED_EVIDENCE", lambda: completion._is_occurrence(None, None, None, source)
    )


def test_ordinary_original_material_is_not_formal_implementation(monkeypatch):
    line = "Actual investigation memo with evidence only"
    source = helper.SOURCE.model_copy(
        update={"position": "line:1;quote_sha256:" + hashlib.sha256(line.encode()).hexdigest()}
    )
    monkeypatch.setattr(completion, "source_for", lambda *a: SimpleNamespace(content=line))
    assert completion._is_occurrence(None, None, None, source) is False
