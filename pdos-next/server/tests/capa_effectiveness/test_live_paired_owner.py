"""No-connect bridge boundary tests with actual ORM/structural writer shapes.

Frozen structural fixture functions supply saved DTOs and SQL SELECT substitutes.
Professional/bytes/retained owners are explicit substitutes here; these tests do
not certify real material, current qualification, independent people or PG atoms.
"""

import importlib.util
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators

from pdos_next import paired_output_bridge as bridge
from pdos_next.domain.capa_effectiveness import paired, paired_storage
from pdos_next.domain.verification_launch.models import (
    VerificationLaunchFact,
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.domain.verification_results.models import TestResultActionFact as ResultActionORM
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal


def load_fixture_module(name, filename, aliases):
    saved = {key: sys.modules.get(key) for key in aliases}
    try:
        sys.modules.update(aliases)
        path = Path(__file__).resolve().parents[3] / "staging" / "wave17" / filename
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


SOURCE_READ = bridge._source_read

# These frozen fixtures import only existing public models, not staged new tables.
structural = load_fixture_module(
    "live_pair_structural_samples", "test_paired.py", {"paired": paired}
)
storage_samples = load_fixture_module(
    "live_pair_storage_samples",
    "test_paired_storage.py",
    {"paired": paired, "paired_storage": paired_storage, "test_paired": structural},
)


class NumericalRead:
    def __init__(self, read):
        self.scope = read.binding.scope
        self.current = True
        self.verified = SimpleNamespace(run=read.material.run_after.snapshot)
        self.run_version_id = read.material.run_after.ref.id
        self.run_revision = read.material.run_after.ref.revision
        self.projection_id = read.material.projection.ref.id
        self.projection_revision = read.material.projection.ref.revision
        self.basis_sha256 = read.material.projection.basis_sha256
        self.rules_version = read.material.projection.rules_version
        self.rules_sha256 = read.material.projection.rules_sha256
        self.required_source_read_set = read.material.projection.reads

    def model_dump(self, *, mode):
        assert mode == "json"
        return {
            "run": self.verified.run.model_dump(mode="json"),
            "basis_sha256": self.basis_sha256,
            "rules_sha256": self.rules_sha256,
            "retained": {
                "checked_at": "display clock",
                "execution_window_elapsed": True,
                "reservation_id": str(structural.uid("reservation")),
                "epoch": 3,
            },
        }


def frame(monkeypatch, operation="test.run.start"):
    work = storage_samples.frame(monkeypatch, operation)
    memory = work.memory
    original_select = memory.selected

    def selected(statement):
        if not statement._setup_joins:
            return original_select(statement)
        model = statement.column_descriptions[0]["entity"]
        assert model in {VerificationLaunchFact, ResultActionORM}
        assert len(statement._setup_joins) == 1
        target, onclause, _, _ = statement._setup_joins[0]
        assert target.name == VerificationRunCurrent.__tablename__
        assert onclause.operator is operators.and_
        expected_version = (
            ("run_version_id", "run_revision")
            if model is VerificationLaunchFact
            else ("next_run_version_id", "next_run_revision")
        )
        assert {(clause.left.key, clause.right.key) for clause in onclause.clauses} == {
            ("tenant_id", "tenant_id"),
            ("product_id", "product_id"),
            ("request_id", "request_id"),
            ("run_id", "run_id"),
            ("run_version_id", expected_version[0]),
            ("run_revision", expected_version[1]),
        }
        memory.queries.append(statement)
        if memory.hook:
            memory.hook(model, statement)
        matches = []
        for fact in memory.rows[model]:
            if not all(memory._matches(fact, clause) for clause in statement._where_criteria):
                continue
            for pointer in memory.rows[VerificationRunCurrent]:
                assert all(clause.operator is operators.eq for clause in onclause.clauses)
                assert all(
                    clause.left.table.name == VerificationRunCurrent.__tablename__
                    and clause.right.table.name == model.__tablename__
                    for clause in onclause.clauses
                )
                if all(
                    getattr(pointer, clause.left.key) == getattr(fact, clause.right.key)
                    for clause in onclause.clauses
                ):
                    matches.append(fact)
        assert statement._limit_clause.value == 2
        return matches[:2]

    monkeypatch.setattr(memory, "selected", selected)
    clock = [structural.AT]
    monkeypatch.setattr(bridge, "_now", lambda: clock[0])
    owner = bridge.LivePairedOwner()
    calls = []
    for rows in work.memory.rows.values():
        for row in rows:
            if not hasattr(row, "authority_snapshot"):
                continue
            actor = (
                row.writer_id
                if isinstance(row, VerificationRunVersion)
                else row.actor_id
                if hasattr(row, "actor_id")
                else row.owner_id
                if isinstance(row, VerificationLaunchFact)
                else UUID(row.authority_snapshot["subject_id"])
            )
            if not hasattr(row, "operation"):
                continue
            row.authority_snapshot = {
                "scope": work.binding.scope.model_dump(mode="json"),
                "subject_id": str(actor),
                "operation": row.operation,
                "purpose": work.binding.purpose,
                "authorized": True,
                "qualified": True,
            }
            work.memory.add(
                Principal(
                    id=actor,
                    tenant_id=work.ctx.tenant_id,
                    kind="human",
                    active=True,
                    access_epoch=1,
                )
            )
            work.memory.add(
                Grant(
                    id=structural.uid(f"grant:{actor}"),
                    tenant_id=work.ctx.tenant_id,
                    category_id=work.ctx.category_id,
                    principal_id=actor,
                    can_write=True,
                    access_epoch=1,
                    expires_at=structural.AT + timedelta(days=1),
                )
            )

    def authority(s, ctx, pid, project_id, snapshot, *, at):
        calls.append(("authority", snapshot["subject_id"], at))
        assert at == clock[0]  # Saved signature remains history; Current is checked now.
        return {
            "current": True,
            "assessment": {
                **deepcopy(snapshot),
                "required_source_read_set": [
                    r.model_dump(mode="json") for r in work.material.fact.reads
                ],
            },
        }

    monkeypatch.setattr(bridge.front, "_recheck", authority)
    project = SimpleNamespace(
        model_dump=lambda **_: {"scope": work.binding.scope.model_dump(mode="json")}
    )
    monkeypatch.setattr(bridge.anchor_storage, "_project", lambda *args: project)
    retained = {
        "current": True,
        "checked_at": "display clock",
        "execution_window_elapsed": True,
        "required_source_read_set": [r.model_dump(mode="json") for r in work.material.fact.reads],
        "reservation": {"id": str(structural.uid("reservation")), "epoch": 3},
        "sample_usage": [{"state": "reserved", "epoch": 2}],
    }

    def execution(s, ctx, pid, row, *, write):
        calls.append(("retained", row.id))
        assert write is False and row.run_id == work.binding.run_id
        return deepcopy(retained)

    monkeypatch.setattr(bridge, "inspect_retained_execution", execution)
    sources = SimpleNamespace(
        sources=(),
        source_basis=[{"id": "actual source basis substitute"}],
        required_source_read_set=work.material.fact.reads,
        byte_material=({"original_id": str(structural.uid("report")), "sha256": "a" * 64},),
        valid_until=structural.AT + timedelta(hours=1),
        time_constraints=(structural.AT + timedelta(hours=1),),
    )
    monkeypatch.setattr(bridge, "_source_read", lambda *args: sources)
    monkeypatch.setattr(bridge, "_fixed_source_basis", lambda *args: None)
    monkeypatch.setattr(
        bridge.evidence, "source_basis", lambda *args: (deepcopy(sources.source_basis), False)
    )
    work.owner, work.calls, work.clock = owner, calls, clock
    work.retained, work.sources = retained, sources
    work.read = lambda: owner.read(
        work.s, work.ctx, work.binding.scope.product_id, work.binding.output_ref, at=structural.AT
    )

    def attest(read=None):
        read = read or work.read()
        structure = paired.verify_paired_material(
            read.binding, read.material, at=structural.AT
        ).proof
        return owner.attest(
            work.s, work.ctx, work.binding.scope.product_id, read, structure, at=structural.AT
        )

    work.attest = attest
    return work


def code(call, expected):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == expected


def without_artifact_read(material, source):
    updates = {}
    for name in (
        "request_before",
        "request_after",
        "origin_request",
        "run_before",
        "run_after",
        "fact",
        "projection",
        "projection_run",
    ):
        row = getattr(material, name)
        if row is not None:
            updates[name] = row.model_copy(
                update={
                    "reads": tuple(
                        r
                        for r in row.reads
                        if (r.artifact_id, r.expected_revision) != (source.id, source.revision)
                    )
                }
            )
    return material.model_copy(update=updates)


@pytest.mark.parametrize(
    "operation",
    ("test.run.start", "test.results.import", "test.run.review", "test.disposition.decide"),
)
def test_historical_promise_original_is_not_a_later_read_but_clock_remains_immutable(operation):
    binding, material = structural.saved(operation)
    clock = material.request_after.snapshot.timeline.promised_start
    narrowed = without_artifact_read(material, clock.source)
    proof = paired.verify_paired_material(binding, narrowed, at=structural.AT).proof
    assert proof is not None
    assert (clock.source.id, clock.source.revision) not in {
        (r.artifact_id, r.expected_revision) for r in proof.required_source_read_set
    }
    changed_clock = clock.model_copy(
        update={"source": clock.source.model_copy(update={"id": structural.uid("changed-promise")})}
    )
    snapshot = narrowed.request_after.snapshot.model_copy(
        update={
            "timeline": narrowed.request_after.snapshot.timeline.model_copy(
                update={"promised_start": changed_clock}
            )
        }
    )
    changed = narrowed.model_copy(
        update={
            "request_after": narrowed.request_after.model_copy(
                update={
                    "snapshot": snapshot,
                    "snapshot_sha256": paired.digest(snapshot.model_dump(mode="json")),
                }
            )
        }
    )
    code(
        lambda: paired.verify_paired_material(binding, changed, at=structural.AT),
        "PAIR_TRANSITION_MISMATCH"
        if operation == "test.run.review"
        else "PAIR_FIXED_SCOPE_CHANGED",
    )


@pytest.mark.parametrize("operation", ("verification.schedule.promise", "test.run.start"))
def test_current_pair_event_original_remains_required(operation):
    binding, material = structural.saved(operation)
    narrowed = without_artifact_read(material, material.fact.kernel_event.at.source)
    code(
        lambda: paired.verify_paired_material(binding, narrowed, at=structural.AT),
        "MISSING_REQUIRED_EVIDENCE",
    )


@pytest.mark.parametrize("change", (None, "changed_basis", "detached_fact"))
def test_direct_start_basis_keeps_saved_contract_and_exact_launch_binding(monkeypatch, change):
    from pdos_next import source_current

    source = structural.exact("actual-start")
    direct_basis = [{"id": str(source.artifact_id), "revision": 1}]
    legacy_basis = {"refs": [], "security": []}
    shared = {
        "operation": "test.run.start",
        "visibility": "category",
        "sources": [source.model_dump(mode="json")],
        "required_source_read_set": [
            {"artifact_id": str(source.artifact_id), "expected_revision": 1}
        ],
        "source_basis": deepcopy(direct_basis),
    }
    run = VerificationRunVersion(
        id=structural.uid("direct-start-row"),
        input_snapshot={"execution_proof_contract": "s0-direct-v1"},
        **shared,
    )
    fact = VerificationLaunchFact(
        id=structural.uid("direct-start-fact"), run_version_id=run.id, **shared
    )
    # Result versions may inherit the execution marker while saving their own
    # complete legacy source basis. The marker alone cannot change its contract.
    result = VerificationRunVersion(
        id=structural.uid("later-result-row"),
        operation="test.results.import",
        input_snapshot=deepcopy(run.input_snapshot),
        visibility="category",
        sources=[],
        required_source_read_set=deepcopy(run.required_source_read_set),
        source_basis=deepcopy(legacy_basis),
    )
    calls = []
    monkeypatch.setattr(bridge.launch, "_read_evidence", lambda *args: "current")
    monkeypatch.setattr(bridge.evidence, "refs_from_exact", lambda *args: args[-1])

    def current(*args):
        calls.append("direct")
        return ([{"id": "changed"}] if change == "changed_basis" else direct_basis), False

    def legacy(*args):
        calls.append("legacy")
        return legacy_basis, False

    monkeypatch.setattr(source_current, "direct_source_basis", current)
    monkeypatch.setattr(bridge.physical, "_basis", legacy)
    if change == "detached_fact":
        fact.run_version_id = structural.uid("other-start-row")
    rows = {row.id: row for row in (run, fact, result)}
    if change is None:
        bridge._fixed_source_basis(None, None, structural.uid("product"), rows)
        assert calls == ["direct", "direct", "legacy"]
    else:
        code(
            lambda: bridge._fixed_source_basis(None, None, structural.uid("product"), rows),
            "SOURCE_STALE",
        )


def test_actual_storage_shape_attests_separate_saved_signers_and_caller_without_mutation(
    monkeypatch,
):
    work = frame(monkeypatch)
    read = work.read()
    gate = work.attest(read)
    assert gate.issued_by is work.owner and gate.session is work.s
    assert gate.transaction is work.s.get_transaction()
    assert gate.caller_id == work.ctx.requester_id
    assert {v.kind for v in gate.stamps} == {
        "acl",
        "sources",
        "professional",
        "original_bytes",
        "retained",
        "semantic",
        "runtime",
    }
    assert gate.valid_until is None
    assert work.sources.time_constraints[0] in gate.time_constraints
    assert work.material.fact.actor_id != work.ctx.requester_id
    assert len([v for v in work.calls if v[0] == "authority"]) >= 2
    assert not work.s.new and not work.s.dirty and not work.s.deleted
    assert all(query.is_select for query in work.memory.queries)


def test_whole_result_query_uses_own_run_version_and_measurement_not_original_failure(monkeypatch):
    work = frame(monkeypatch, "test.run.review")
    read = work.read()
    actual = NumericalRead(read)
    queries = []

    def result(s, ctx, pid, **kwargs):
        queries.append(kwargs)
        return actual

    monkeypatch.setattr(bridge.result_owner, "fixed_failure_result", result)
    monkeypatch.setattr(bridge.result_owner, "recheck_fixed_failure_result", lambda *args: actual)
    gate = work.attest(read)
    assert "numerical_rules" in {v.kind for v in gate.stamps}
    assert queries == [
        {
            "run_id": read.material.run_after.snapshot.id,
            "run_revision": read.material.run_after.ref.revision,
            "measurement_id": read.material.run_after.snapshot.measurements[0].id,
            "write": False,
        }
    ]
    assert "event_id" not in queries[0] and "failure_ref" not in queries[0]


@pytest.mark.parametrize("mutation", ["projection", "run", "rules"])
def test_numerical_owner_cannot_substitute_projection_run_or_rules(monkeypatch, mutation):
    work = frame(monkeypatch, "test.run.review")
    read = work.read()
    actual = NumericalRead(read)
    if mutation == "projection":
        actual.projection_id = structural.uid("wrong-projection")
    elif mutation == "run":
        actual.run_version_id = structural.uid("old-failure-run")
    else:
        actual.rules_sha256 = "f" * 64
    monkeypatch.setattr(bridge.result_owner, "fixed_failure_result", lambda *args, **kwargs: actual)
    code(lambda: work.attest(read), "PAIR_NUMERICAL_BASIS_MISMATCH")


def test_retained_ledger_change_after_last_source_io_does_not_issue_gate(monkeypatch):
    work = frame(monkeypatch)

    def source(*args):
        work.retained["sample_usage"][0]["epoch"] += 1
        return work.sources

    monkeypatch.setattr(bridge, "_source_read", source)
    code(work.attest, "SOURCE_STALE")


def test_professional_revoke_after_bytes_blocks_gate(monkeypatch):
    work = frame(monkeypatch)
    original = bridge.front._recheck
    withdrawn = [False]
    monkeypatch.setattr(
        bridge.front,
        "_recheck",
        lambda *args, **kwargs: {"current": False} if withdrawn[0] else original(*args, **kwargs),
    )
    monkeypatch.setattr(
        bridge, "_source_read", lambda *args: (withdrawn.__setitem__(0, True), work.sources)[1]
    )
    code(work.attest, "PAIR_PROFESSIONAL_STALE")


def test_disabled_original_signer_preserves_history_and_marks_review(monkeypatch):
    work = frame(monkeypatch)
    actor = work.material.fact.actor_id

    row = next(v for v in work.memory.rows[Principal] if v.id == actor)
    row.active = False
    work.memory.rows[Grant] = [
        value for value in work.memory.rows[Grant] if value.principal_id != actor
    ]
    original = bridge.front._recheck

    def authority(*args, **kwargs):
        value = original(*args, **kwargs)
        value["needs_review"] = args[4]["subject_id"] == str(actor)
        return value

    monkeypatch.setattr(bridge.front, "_recheck", authority)
    gate = work.attest()
    assert gate.needs_review is True
    assert gate.caller_id == work.ctx.requester_id


def test_runtime_issuer_epoch_change_after_bytes_blocks_gate(monkeypatch):
    work = frame(monkeypatch)

    def source(*args):
        work.s.get_bind()._pdos_professional_issuer_epochs = {"actual-host": 2}
        return work.sources

    monkeypatch.setattr(bridge, "_source_read", source)
    code(work.attest, "SOURCE_STALE")


def test_current_pointer_change_after_bytes_blocks_gate(monkeypatch):
    work = frame(monkeypatch)
    from pdos_next.domain.verification_front.models import FormalVerificationCurrent

    def source(*args):
        row = work.memory.first(FormalVerificationCurrent)
        row.request_revision += 1
        return work.sources

    monkeypatch.setattr(bridge, "_source_read", source)
    code(work.attest, "PAIR_CURRENT_MISMATCH")


def test_last_caller_sql_crossing_deadline_uses_post_io_clock(monkeypatch):
    work = frame(monkeypatch)
    original, count = bridge._caller, [0]

    def caller(*args):
        value = original(*args)
        count[0] += 1
        if count[0] == 2:
            work.clock[0] = work.sources.valid_until
        return value

    monkeypatch.setattr(bridge, "_caller", caller)
    code(work.attest, "PAIR_LIVE_PROOF_EXPIRED")


def test_active_savepoint_created_during_source_callback_is_not_same_uow(monkeypatch):
    work = frame(monkeypatch)

    def source(*args):
        work.s.begin_nested()
        return work.sources

    monkeypatch.setattr(bridge, "_source_read", source)
    code(work.attest, "CALLER_UOW_CHANGED")


def test_cloned_read_and_different_product_cannot_attest(monkeypatch):
    work = frame(monkeypatch)
    read = work.read()
    code(lambda: work.attest(replace(read)), "PAIR_HOST_READ_UNBOUND")
    structure = paired.verify_paired_material(read.binding, read.material, at=structural.AT).proof
    code(
        lambda: work.owner.attest(
            work.s, work.ctx, structural.uid("other-product"), read, structure, at=structural.AT
        ),
        "PAIR_SCOPE_MISMATCH",
    )


def test_read_cannot_cross_commit_or_inactive_actual_transaction(monkeypatch):
    work = frame(monkeypatch)
    read = work.read()
    work.s.rollback()
    code(lambda: work.attest(read), "CALLER_UOW_REQUIRED")


def test_structural_proof_is_recomputed_not_accepted_by_hash(monkeypatch):
    work = frame(monkeypatch)
    read = work.read()
    structure = paired.verify_paired_material(read.binding, read.material, at=structural.AT).proof
    changed = structure.model_copy(update={"meaning": "planned"})
    code(
        lambda: work.owner.attest(
            work.s, work.ctx, work.binding.scope.product_id, read, changed, at=structural.AT
        ),
        "PAIR_STRUCTURE_UNBOUND",
    )


def test_raw_full_row_and_source_json_preserve_models_offsets_and_no_repr(monkeypatch):
    work = frame(monkeypatch)
    rows = bridge._rows(work.s, work.ctx, work.binding.scope.product_id, work.read())
    raw = bridge._wire(
        {"read": work.material.fact.reads, "instant": structural.AT, "actor": work.ctx.actor_id}
    )
    import json

    assert json.loads(json.dumps(raw))["read"][0] == work.material.fact.reads[0].model_dump(
        mode="json"
    )
    run = rows[(VerificationRunVersion.__tablename__, work.material.run_after.ref.id)]
    before = bridge._stored_digest(rows)
    run.authority_snapshot["additional_negative_fact"] = {"epoch": 2, "qualified": False}
    assert bridge._stored_digest(rows) != before


def test_actual_scope_sql_is_bounded_and_does_not_flush(monkeypatch):
    work = frame(monkeypatch)
    monkeypatch.setattr(work.s, "flush", lambda *args: pytest.fail("owner must never flush"))
    gate = work.attest()
    assert gate.valid_until is None
    assert all(value > gate.checked_at for value in gate.time_constraints)
    assert all(
        query.get_execution_options().get("populate_existing")
        for query in work.memory.queries
        if query.get_execution_options().get("autoflush") is False
    )


def test_requires_actual_session_not_transaction_shaped_duck(monkeypatch):
    fake = SimpleNamespace(is_active=True, get_transaction=lambda: object())
    code(lambda: paired_storage._uow(fake), "CALLER_UOW_REQUIRED")
    s = Session(bind=SimpleNamespace())
    code(lambda: paired_storage._uow(s), "CALLER_UOW_REQUIRED")


def test_actual_definition_reference_is_typed_before_real_full_line_hash_owner(monkeypatch):
    from hashlib import sha256

    from pdos_next.domain.configurations.schemas import DefinitionReference

    work = frame(monkeypatch)
    read = work.read()
    quote = "  exact binding, µs and original material  "
    reference = DefinitionReference(
        artifact_id=structural.uid("source-line"),
        expected_revision=2,
        line=1,
        quote="exact binding",
    )
    artifact = SimpleNamespace(
        content=quote, id=reference.artifact_id, revision=reference.expected_revision
    )
    seen = []
    original = bridge.evidence.refs_from_exact

    def actual_refs(s, ctx, pid, references):
        assert all(hasattr(v, "artifact_id") for v in references)
        seen.extend(references)
        return original(s, ctx, pid, references)

    monkeypatch.setattr(bridge.evidence, "source_for", lambda *args: artifact)
    monkeypatch.setattr(bridge.evidence, "refs_from_exact", actual_refs)
    monkeypatch.setattr(
        bridge,
        "_refs_reads",
        lambda *args: ([reference.model_dump(mode="json")], work.material.fact.reads),
    )
    closure = []
    monkeypatch.setattr(
        bridge,
        "read_source_closure",
        lambda *args, **kwargs: (closure.append(kwargs), SimpleNamespace(missing=()))[1],
    )
    # frame replaced this entry point only for owner-orchestration tests above;
    # here exercise the actual immutable raw-reference -> source owner boundary.
    SOURCE_READ(work.s, work.ctx, work.binding.scope.product_id, read, {})
    assert seen[0].model_dump(mode="json") == reference.model_dump(mode="json")
    assert (
        closure[0]["sources"][0].position
        == f"line:1;quote_sha256:{sha256(quote.encode()).hexdigest()}"
    )
    assert closure[0]["sources"][0].revision == 2


def test_full_source_closure_over_twenty_is_complete_and_conflicting_versions_reject():
    rows = {
        "row": SimpleNamespace(
            sources=[],
            required_source_read_set=[
                {"artifact_id": str(structural.uid(f"source-{i}")), "expected_revision": 1}
                for i in range(21)
            ],
        )
    }
    assert len(bridge._refs_reads(rows)[1]) == 21
    rows["row"].required_source_read_set = [
        {"artifact_id": str(structural.uid("same-source")), "expected_revision": v} for v in (1, 2)
    ]
    code(lambda: bridge._refs_reads(rows), "RECHECK_REQUIRED")


def test_actual_paired_wrapper_requires_two_independent_live_owner_rounds(monkeypatch):
    work = frame(monkeypatch)
    calls = [0]
    original = bridge._source_read

    def source(*args):
        calls[0] += 1
        return original(*args)

    monkeypatch.setattr(bridge, "_source_read", source)
    outcome = paired.read_paired_formal_output(
        work.s,
        work.ctx,
        work.binding.scope.product_id,
        work.binding.output_ref,
        at=structural.AT,
        reader=work.owner,
        clock=lambda: work.clock[0],
    )
    assert not outcome.missing and outcome.host_gate.issued_by is work.owner
    assert calls[0] == 2


def test_drift_between_actual_wrapper_rounds_cannot_reuse_first_live_gate(monkeypatch):
    work = frame(monkeypatch)
    calls = [0]
    original = work.owner.refresh

    def refresh(*args, **kwargs):
        calls[0] += 1
        work.s.get_bind()._pdos_professional_issuer_epochs = {"revoked-after-first": 2}
        return original(*args, **kwargs)

    monkeypatch.setattr(work.owner, "refresh", refresh)
    code(
        lambda: paired.read_paired_formal_output(
            work.s,
            work.ctx,
            work.binding.scope.product_id,
            work.binding.output_ref,
            at=structural.AT,
            reader=work.owner,
            clock=lambda: work.clock[0],
        ),
        "SOURCE_STALE",
    )
    assert calls[0] == 1


def test_planned_read_does_not_create_capture_deadline_from_unrelated_fact(monkeypatch):
    work = frame(monkeypatch)
    next_at = structural.AT + timedelta(microseconds=3)
    plan = SimpleNamespace(
        facts_revision="a" * 64,
        required_source_read_set=work.material.fact.reads,
        valid_until=None,
        expiry_boundaries=(),
    )
    monkeypatch.setattr(bridge, "_execution", lambda *args: (None, plan))
    monkeypatch.setattr(bridge.resources, "expired", lambda value, at: False)
    gate = work.attest()
    assert gate.valid_until is None and next_at not in gate.time_constraints
    assert not any("professional_authority_current" in str(query) for query in work.memory.queries)


def test_planned_actual_resource_condition_crossed_during_final_io_denies_gate(monkeypatch):
    work = frame(monkeypatch)
    boundary = structural.AT + timedelta(microseconds=1)
    plan = SimpleNamespace(
        facts_revision="a" * 64,
        required_source_read_set=work.material.fact.reads,
        valid_until=work.sources.valid_until,
        expiry_boundaries=(boundary,),
    )
    monkeypatch.setattr(bridge, "_execution", lambda *args: (None, plan))
    monkeypatch.setattr(bridge.resources, "expired", lambda value, at: at >= boundary)
    caller = bridge._caller
    calls = [0]

    def final(*args):
        value = caller(*args)
        calls[0] += 1
        if calls[0] == 2:
            work.clock[0] = boundary
        return value

    monkeypatch.setattr(bridge, "_caller", final)
    code(work.attest, "PAIR_LIVE_PROOF_EXPIRED")
