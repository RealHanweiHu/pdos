"""Dedicated write-prepare seam; no-connect ORM and explicit owner substitutes.

Only pure anchor factories are copied from frozen staged tests. No staged module
or staged model imports: all production classes use the public namespace.
Source/professional/inspection reads below are controlled substitutes, not real
bytes, qualification, database enforcement or publicly complete verification.
"""

import json
from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from quality_issues.helpers import NOW, fixed_run, source, uid
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness import anchor as a
from pdos_next.domain.capa_effectiveness import candidate_anchor_restore as restoration
from pdos_next.domain.capa_effectiveness import candidate_commands as commands
from pdos_next.domain.capa_effectiveness import candidate_prepare as preparation
from pdos_next.domain.capa_effectiveness import candidate_write as writer
from pdos_next.domain.capa_effectiveness import fact_consumption as consumption
from pdos_next.domain.capa_verification import service as followup
from pdos_next.domain.capa_verification.schemas import CandidateBinding, CandidateInspect, Missing
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.quality_issues.rules import failure_ref
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Grant, Principal, Product
from pdos_next.schemas.quality_issues.contracts import (
    Capa,
    CapaAction,
    Containment,
    EffectivenessRequirement,
    History,
    Hypothesis,
    Issue,
    NamedConclusion,
)
from pdos_next.schemas.verification.contracts import EventTime
from pdos_next.service import Context, digest

SourceSafety = a.SourceSafety
IssueVersionEvidence = a.IssueVersionEvidence
OriginalFailureProof = a.OriginalFailureProof
SourceRead = a.SourceRead
VersionRef = a.VersionRef
canonical_sources = a.canonical_sources
canonical_reads = a.canonical_reads
json_value = a.json_value
build_anchor = a.build_anchor
PURPOSE = "Synthetic shared investigation; not production qualification"


def safety(ref):
    return SourceSafety(
        id=ref.id,
        revision=ref.revision,
        hash=digest(str(ref.id)),
        status="active",
        owner_id=uid("owner"),
        visibility="category",
        source_kind="registered_native_text",
        registration={
            "receipt_id": uid(str(ref.id) + "-receipt"),
            "actor_id": uid("owner"),
            "requester_id": uid("owner"),
            "run_id": None,
        },
    )


def origin_fixture():
    run = fixed_run(revision=4)
    failure = failure_ref(VerifiedRun(run=run, nature="synthetic"), run.measurements[0].id)
    root = source("root")
    complete = source("action-complete")
    issue = Issue(
        id=uid("issue"),
        revision=9,
        scope=run.scope,
        audience=(f"category:{uid('category')}",),
        title="Synthetic actual fixed failure",
        status="awaiting_verification",
        risk="high",
        failures=(failure,),
        root_cause=NamedConclusion(
            text="Named original cause",
            actor_id=uid("owner"),
            sources=(root,),
            at=NOW - timedelta(minutes=90),
        ),
        capa=Capa(
            id=uid("capa"),
            hypotheses=(Hypothesis(text="Original hypothesis", sources=(root,)),),
            actions=(
                CapaAction(
                    id=uid("action"),
                    kind="corrective",
                    text="Original complete action",
                    executor_id=uid("owner"),
                    completion=Containment(
                        id=uid("action"),
                        text="Actual completion",
                        executor_id=uid("owner"),
                        evidence=(complete,),
                        at=EventTime(occurred_at=NOW, original_timezone="UTC", source=complete),
                    ),
                ),
            ),
            requirement=EffectivenessRequirement(
                method="New independent fixed Run and actual observation",
                acceptance="All exact pairs pass",
                observation_until=NOW + timedelta(minutes=10),
                required_failure_ids=(failure.identity,),
            ),
        ),
        history=(
            History(
                command_id=uid("root-command"),
                operation="quality.issue.root_cause.decide",
                actor_id=uid("owner"),
                actor_kind="human",
                at=NOW - timedelta(minutes=90),
                note="Original cause",
            ),
            History(
                command_id=uid("complete-command"),
                operation="quality.capa.actions.complete",
                actor_id=uid("owner"),
                actor_kind="human",
                at=NOW,
                note="Original completion",
            ),
        ),
    )
    sources = canonical_sources((failure.source, failure.method, failure.criterion, root, complete))
    reads = canonical_reads(
        SourceRead(artifact_id=s.id, expected_revision=s.revision) for s in sources
    )
    basis = tuple(safety(s) for s in sources)
    row = IssueVersionEvidence(
        ref=VersionRef(id=uid("issue-v9"), revision=9, snapshot_sha256=digest(json_value(issue))),
        previous_ref=None,
        scope=issue.scope,
        category_id=uid("category"),
        issue_id=issue.id,
        purpose=PURPOSE,
        owner_id=uid("owner"),
        writer_id=uid("owner"),
        visibility="category",
        nature="synthetic",
        operation="quality.capa.actions.complete",
        domain_intent_sha256=digest("original-domain-intent"),
        created_at=NOW,
        issue=issue,
        sources=sources,
        required_source_read_set=reads,
        source_basis=basis,
        input_snapshot={"complete": "retained full original payload"},
        authority_snapshot={"original_writer": str(uid("owner"))},
        policy_snapshot={"original_policy": "retained"},
        persisted_source_basis={
            "artifact_sources": [json_value(s) for s in basis],
            "original_shared_proof": str(uid("complete-proof")),
        },
    )
    result = FixedQualityResult(
        scope=run.scope,
        purpose=PURPOSE,
        event_id=None,
        run_version_id=uid("fixed-run-v4"),
        run_revision=run.revision,
        measurement_id=failure.measurement_id,
        projection_id=uid("fixed-projection"),
        projection_revision=1,
        basis_sha256=digest("fixed-results-basis"),
        rules_version="fixed-original-rules",
        rules_sha256=digest("fixed-rules"),
        verified=VerifiedRun(run=run, nature="synthetic"),
        visibility="category",
        owner_id=uid("tester"),
        sources=sources,
        required_source_read_set=reads,
        current=True,
        source_basis={
            "evidence": [json_value(s) for s in basis],
            "original_bytes_sha256": digest("actual synthetic original bytes"),
            "runtime_stamp": digest("initial-host-runtime"),
        },
        retained={
            "current": True,
            "original_start_intent": digest("fixed-start"),
            "original_start_version_id": str(uid("start-v2")),
            "original_start_revision": 2,
            "saved_start_at": run.actual_start.received_at.isoformat(),
            "actual_start": json_value(run.actual_start),
            "plan_binding": {"complete_plan": "immutable", "checked_at": "FIXED nested data"},
            "reservation": {"id": str(uid("reservation")), "epoch": 2},
            "occupancy": [{"asset_id": str(uid("equipment")), "epoch": 4}],
            "sample_usage": [{"sample_id": str(run.samples[0].id), "epoch": 2}],
            "facts_revision": digest("all resource facts"),
            "source_basis": {"epoch": 7},
            "source_nature": "synthetic",
            "checked_at": NOW.isoformat(),
            "execution_window_elapsed": False,
        },
    )
    proof = OriginalFailureProof(failure=failure, result=result)
    return build_anchor(row, (proof,), source_basis=basis)


@pytest.fixture
def world(monkeypatch):
    original = origin_fixture()
    origin = original.origin
    clock = SimpleNamespace(at=NOW + timedelta(hours=1))
    bind = create_engine("sqlite://")
    event.listen(bind, "do_connect", lambda *_: pytest.fail("Owned pure must not connect"))
    s = Session(bind=bind)
    s.begin()
    ctx = Context(
        origin.scope.tenant_id,
        uid("separate-shared-writer"),
        uid("separate-shared-writer"),
        category_id=origin.category_id,
    )
    product = Product(
        id=origin.scope.product_id,
        tenant_id=ctx.tenant_id,
        category_id=origin.category_id,
        revision=400,
    )
    principal = Principal(
        id=ctx.actor_id, tenant_id=ctx.tenant_id, kind="human", active=True, access_epoch=1
    )
    grant = Grant(
        id=uid("write-grant"),
        tenant_id=ctx.tenant_id,
        category_id=origin.category_id,
        principal_id=ctx.actor_id,
        can_write=True,
        access_epoch=1,
        expires_at=clock.at + timedelta(hours=2),
    )
    row = QualityIssueVersion(
        id=origin.ref.id,
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=origin.scope.project_id,
        issue_id=origin.issue_id,
        revision=origin.ref.revision,
        purpose=origin.purpose,
        owner_id=origin.owner_id,
        visibility=origin.visibility,
        snapshot_sha256=origin.ref.snapshot_sha256,
        issue_snapshot=origin.issue.model_dump(mode="json"),
    )
    rows = {Product: product, Principal: principal, Grant: grant}

    def one(session, model, *where):
        assert session is s and model in rows
        value = rows[model]
        for clause in where:
            wanted = (
                origin.category_id
                if clause.left.key == "category_id"
                and getattr(clause.right, "name", None) == "category_for_product"
                else clause.right.value
            )
            assert getattr(value, clause.left.key) == wanted
        return value

    monkeypatch.setattr(preparation.guards, "_one", one)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.at if tz is not None else clock.at.replace(tzinfo=None)

    monkeypatch.setattr(preparation.guards, "datetime", Clock)
    monkeypatch.setattr(consumption, "datetime", Clock)
    monkeypatch.setattr(preparation, "_clock", lambda: clock.at)
    monkeypatch.setattr(restoration, "_clock", lambda: clock.at)
    project = preparation.anchor_storage.StoredProjectScope(
        scope=origin.scope,
        owner_id=uid("different-project-owner"),
        visibility="category",
        declared_scope="Actual shared project synthetic fixture",
    )
    pointer = preparation.anchor_storage.StoredIssueCurrent(
        pointer_id=uid("current-issue"),
        pointer_created_at=NOW,
        ref=origin.ref,
        epoch=1,
        operation=origin.operation,
        created_at=NOW,
    )

    def version(session, context, pid, issue_id, ref, project_id=None):
        assert (session, context, pid, issue_id, ref, project_id) == (
            s,
            ctx,
            product.id,
            origin.issue_id,
            origin.ref,
            origin.scope.project_id,
        )
        return row, origin.issue

    monkeypatch.setattr(preparation.anchor_storage, "_version", version)
    monkeypatch.setattr(preparation.anchor_storage, "_current", lambda *_: pointer)
    monkeypatch.setattr(preparation.anchor_storage, "_project", lambda *_: project)
    raw = [
        {k: v for k, v in a.json_value(safe).items() if v is not None}
        for safe in origin.source_basis
    ]
    monkeypatch.setattr(preparation.evidence, "source_basis", lambda *_: (deepcopy(raw), False))
    monkeypatch.setattr(preparation.evidence, "refs_from_exact", lambda *_: ())
    basis = followup.basis_from_issue(
        row,
        origin.issue,
        sources=origin.sources,
        reads=origin.required_source_read_set,
        source_basis=raw,
    )
    binding = CandidateBinding(basis=basis)
    inspection = CandidateInspect(
        binding=binding,
        current=True,
        required_source_read_set=origin.required_source_read_set,
        source_basis_sha256=digest(raw),
        inspection_sha256="0" * 64,
        missing=(
            Missing(
                dimension="observation",
                code="INTEGRATION_REQUIRED",
                detail="Real observation owner remains unconnected",
            ),
        ),
    )
    inspection = inspection.model_copy(
        update={
            "inspection_sha256": digest(
                inspection.model_dump(mode="json", exclude={"inspection_sha256", "candidate_ref"})
            )
        }
    )
    authority = {
        "facts_revision": digest("synthetic fixed professional test return"),
        "authorized": True,
        "qualified": True,
        "valid_until": None,
        "operation": commands.OPERATION,
        "purpose": origin.purpose,
        "roles": ["quality"],
        "synthetic": True,
        "fact_refs": [
            {
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": [commands.OPERATION],
                "purposes": [origin.purpose],
                "valid_from": NOW.isoformat(),
                "valid_until": (clock.at + timedelta(hours=1)).isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
    }
    policy = {
        "facts_revision": digest("synthetic policy return"),
        "valid_until": None,
        "id": str(uid("policy")),
        "revision": 1,
        "source_basis": [
            {
                "id": str(uid("policy")),
                "revision": 1,
                "state": "active",
                "valid_from": NOW.isoformat(),
                "valid_until": (clock.at + timedelta(hours=1)).isoformat(),
            }
        ],
    }
    state = SimpleNamespace(current_calls=0, owner_calls=0, hook=None, sql_calls=0, sql_hook=None)

    def fresh_anchor():
        failures = []
        for old in original.failures:
            result = old.result.model_copy(deep=True)
            result.retained["checked_at"] = clock.at.isoformat()
            failures.append(a.OriginalFailureProof(failure=old.failure, result=result))
        return a.build_anchor(origin, tuple(failures), source_basis=origin.source_basis)

    def actual_owner(session, context, pid, issue_id, ref):
        assert (session, context, pid, issue_id, ref) == (
            s,
            ctx,
            product.id,
            origin.issue_id,
            origin.ref,
        )
        state.owner_calls += 1
        return SimpleNamespace(
            anchor=fresh_anchor(),
            checked_at=clock.at,
            needs_lineage_owner=False,
            origin_descriptor=SimpleNamespace(
                current=pointer, project=project, needs_lineage_owner=False
            ),
        )

    monkeypatch.setattr(preparation.anchor_owner, "read_anchor_from_actual_owner", actual_owner)
    payload = commands.CandidateRecordPayload(
        issue_id=origin.issue_id,
        expected_issue_revision=origin.ref.revision,
        capa_id=origin.issue.capa.id,
        reason="New incomplete verification candidate",
        visibility="category",
        confirmation_token="real-persistent-fixture-proof-token",
    )

    def read(session, context, pid, current_payload, ref):
        assert (session, context, pid, ref) == (s, ctx, product.id, origin.ref)
        assert commands.semantic(current_payload) == commands.semantic(payload)
        state.current_calls += 1
        if state.hook:
            state.hook(state.current_calls)
        return preparation.PreparedCandidate(
            commands.semantic(payload),
            fresh_anchor(),
            binding,
            inspection,
            deepcopy(raw),
            origin.required_source_read_set,
            origin.sources,
            deepcopy(authority),
            deepcopy(policy),
            origin.owner_id,
            origin.visibility,
            origin.ref.revision,
            s,
            preparation.guards._uow(s),
            preparation._runtime(s),
            clock.at,
            None,
            caller_expires_at=grant.expires_at,
        )

    monkeypatch.setattr(preparation, "_read", read)
    initial = preparation.prepare_candidate(s, ctx, product.id, payload, origin_ref=origin.ref)
    command = Command(
        command_id=uid("candidate-write-command"),
        idempotency_key="candidate-write-key",
        operation=commands.OPERATION,
        category_id=ctx.category_id,
        product_id=product.id,
        expected_revision=product.revision,
        source_read_set=[r.model_dump(mode="json") for r in initial.required_source_read_set],
        payload=payload.model_dump(mode="json"),
    )
    proof = Confirmation(
        id=uid("candidate-write-proof"),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        subject_type="product",
        product_id=product.id,
        actor_id=ctx.actor_id,
        subject_id=product.id,
        operation=commands.OPERATION,
        revision=product.revision,
        token_hash=digest(payload.confirmation_token),
        payload_digest=common.material_digest(ctx, command, payload, commands),
        snapshot=writer.reviewed_prepared_candidate(initial),
        consumed=False,
        created_at=Clock.fromisoformat((clock.at - timedelta(seconds=1)).isoformat()),
        expires_at=Clock.fromisoformat((clock.at + timedelta(minutes=10)).isoformat()),
    )
    make_transient_to_detached(proof)
    s.add(proof)
    database = {k: deepcopy(getattr(proof, k)) for k in restoration.PROOF_COLUMNS}

    def execute(query):
        assert query.is_select and query._limit_clause.value == 2
        assert query.get_execution_options().get("autoflush") is False
        assert {c.key for c in query.selected_columns} == set(restoration.PROOF_COLUMNS)
        assert len(query._where_criteria) == 3
        state.sql_calls += 1
        if state.sql_hook:
            state.sql_hook(state.sql_calls)
        assert all(database[c.left.key] == c.right.value for c in query._where_criteria)
        return SimpleNamespace(mappings=lambda: [deepcopy(database)])

    monkeypatch.setattr(s, "execute", execute)
    host = restoration.CandidateAnchorRestoreHost(commands)
    world = SimpleNamespace(
        s=s,
        ctx=ctx,
        clock=clock,
        product=product,
        principal=principal,
        grant=grant,
        row=row,
        pointer=pointer,
        project=project,
        original=original,
        authority=authority,
        policy=policy,
        state=state,
        payload=payload,
        command=command,
        proof=proof,
        database=database,
        host=host,
        raw=raw,
    )
    yield world
    s.rollback()
    s.close()


def prepare(f, **override):
    return preparation.prepare_candidate_write(
        f.s,
        f.ctx,
        override.get("command", f.command),
        override.get("payload", f.payload),
        override.get("proof", f.proof),
        override.get("host", f.host),
    )


def reject(code, fn):
    with pytest.raises(DomainError) as caught:
        fn()
    assert caught.value.reason == code
    return caught.value


def test_write_prepare_restores_true_first_anchor_and_keeps_incomplete_nulls(world):
    f = world
    old = deepcopy(f.database["snapshot"])
    f.clock.at += timedelta(seconds=3)
    phase = prepare(f)
    assert phase.anchor.model_dump(mode="json") == old["stable_anchor"]
    assert phase.anchor.anchor_sha256 == old["stable_anchor"]["anchor_sha256"]
    assert phase.anchor.failures[0].result.retained["checked_at"] != f.clock.at.isoformat()
    assert writer.reviewed_prepared_candidate(phase) == old
    assert phase.valid_until == f.proof.expires_at
    assert phase.inspection.result == "indeterminate"
    assert (
        phase.inspection.applicable
        is phase.inspection.independently_verified
        is phase.inspection.observation_complete
        is None
    )
    assert phase.owner_id != f.ctx.actor_id and phase.visibility == "category"
    assert f.state.current_calls == 2 and f.state.owner_calls == 2
    assert f.proof.consumed is False and not f.s.new and not f.s.dirty


def test_unbounded_member_grant_keeps_actual_t1_proof_deadline(world):
    world.grant.expires_at = None
    phase = prepare(world)
    assert phase.valid_until == world.proof.expires_at
    assert phase.caller_expires_at is None
    assert world.proof.consumed is False


def test_actual_consumption_then_independent_refresh_preserves_original_snapshot(world):
    f = world
    f.clock.at += timedelta(seconds=2)
    phase = prepare(f)
    host = consumption.ConsumptionHost({commands.OPERATION: commands})
    binding = host.bind_before_transition(
        f.s, f.ctx, f.command, f.payload, commands, f.proof, reviewed_snapshot=f.proof.snapshot
    )
    f.proof.consumed = True
    marker = host.capture_after_transition(
        f.s, f.ctx, f.command, f.payload, commands, f.proof, binding=binding
    )
    assert marker.consumed_at == f.clock.at
    f.clock.at += timedelta(seconds=2)
    assert (
        preparation.require_prepared_candidate(f.s, f.ctx, f.product.id, f.payload, phase) is phase
    )
    assert (
        host.require_live(
            f.s, f.ctx, f.command, f.payload, commands, f.proof, binding=binding, marker=marker
        )
        is marker
    )
    assert writer.reviewed_prepared_candidate(phase) == f.database["snapshot"]
    assert f.database["consumed"] is False and f.proof.consumed is True
    assert f.state.current_calls == 3


def test_real_review_and_written_jsonb_use_ordered_json_refs_without_string_fallback(
    world, monkeypatch
):
    f = world
    f.product.lifecycle_epoch = 1
    make_transient_to_detached(f.product)
    f.s.add(f.product)  # Actual persistent ORM state; the fixture forbids connections.
    phase = prepare(f)
    review = writer.reviewed_prepared_candidate(phase)
    expected_sources = [v.model_dump(mode="json") for v in phase.sources]
    expected_reads = [v.model_dump(mode="json") for v in phase.required_source_read_set]
    decoded = json.loads(json.dumps(review, allow_nan=False))
    assert decoded == review == f.proof.snapshot
    assert decoded["sources"] == expected_sources
    assert decoded["required_source_read_set"] == expected_reads
    assert all(type(v["expected_revision"]) is int for v in decoded["required_source_read_set"])
    with pytest.raises(ValidationError):
        SourceRead.model_validate({**expected_reads[0], "expected_revision": True})

    host = consumption.ConsumptionHost({commands.OPERATION: commands})
    binding = host.bind_before_transition(
        f.s, f.ctx, f.command, f.payload, commands, f.proof, reviewed_snapshot=review
    )
    f.proof.consumed = True
    marker = host.capture_after_transition(
        f.s, f.ctx, f.command, f.payload, commands, f.proof, binding=binding
    )
    monkeypatch.setattr(writer, "datetime", type(f.proof.created_at))
    row, subject, visibility = writer.apply_prepared_candidate(
        f.s,
        f.ctx,
        f.command,
        f.product,
        f.payload,
        phase,
        consumption_host=host,
        module=commands,
        proof=f.proof,
        consumption_binding=binding,
        consumption_marker=marker,
    )
    jsonb = {
        column.key: getattr(row, column.key, None)
        for column in row.__table__.columns
        if isinstance(column.type, JSONB)
    }
    assert json.loads(json.dumps(jsonb, allow_nan=False)) == jsonb
    assert jsonb["sources"] == expected_sources
    assert jsonb["required_source_read_set"] == expected_reads
    assert jsonb["candidate_snapshot"]["required_source_read_set"] == expected_reads
    assert jsonb["input_snapshot"]["stable_anchor"] == decoded["stable_anchor"]
    assert subject == "capa_verification_candidate" and visibility == "category"
    receipt_result = {
        "id": str(row.id),
        "revision": row.revision,
        "status": row.status,
        **row.action_result,
    }
    assert json.loads(json.dumps(receipt_result, allow_nan=False)) == receipt_result
    assert set(receipt_result) == {
        "id",
        "revision",
        "status",
        "candidate_binding_sha256",
        "inspection_sha256",
    }


@pytest.mark.parametrize("kind", ["authority", "policy"])
def test_current_material_change_does_not_reuse_old_review_permission(world, kind):
    getattr(world, kind)["facts_revision"] = digest("new or revoked current fact")
    reject("CANDIDATE_REVIEW_MATERIAL_CHANGED", lambda: prepare(world))
    assert not world.s.new and world.proof.consumed is False


def test_current_owner_port_failure_is_not_turned_into_saved_authority(world):
    world.state.hook = lambda _: (_ for _ in ()).throw(
        DomainError("QUALIFICATION_REQUIRED", "current duty revoked", 403)
    )
    reject("QUALIFICATION_REQUIRED", lambda: prepare(world))


def test_proof_expiry_during_current_owner_io_rejects_before_registration(world):
    world.state.hook = lambda _: setattr(world.clock, "at", world.proof.expires_at)
    reject("SOURCE_STALE", lambda: prepare(world))
    assert not world.s.new and world.proof.consumed is False


def test_actual_qualification_expiry_during_owner_io_blocks_new_confirmation(world):
    boundary = world.clock.at + timedelta(seconds=2)
    world.authority["fact_refs"][1]["valid_until"] = boundary.isoformat()
    world.database["snapshot"]["authority_snapshot"] = deepcopy(world.authority)
    from sqlalchemy.orm import attributes

    attributes.set_committed_value(world.proof, "snapshot", deepcopy(world.database["snapshot"]))
    world.state.hook = lambda _: setattr(world.clock, "at", boundary)
    reject("SOURCE_STALE", lambda: prepare(world))


def test_raw_proof_changes_after_all_current_reads_are_rejected(world):
    world.state.hook = lambda _: world.database["snapshot"].update(
        policy_snapshot={"changed": True}
    )
    reject("CANDIDATE_PERSISTED_PROOF_CHANGED", lambda: prepare(world))


def test_last_proof_sql_can_neither_change_runtime_nor_outlive_original_expiry(world):
    def advance(_):
        if world.state.current_calls == 2:
            world.clock.at = world.proof.expires_at

    world.state.sql_hook = advance
    reject("SOURCE_STALE", lambda: prepare(world))
    assert world.proof.consumed is False and not world.s.new


def test_last_proof_sql_runtime_epoch_change_is_rejected(world):
    def revoke(_):
        if world.state.current_calls == 2:
            world.s.get_bind()._pdos_quality_policy_epochs = {"issuer": 3}

    world.state.sql_hook = revoke
    reject("SOURCE_STALE", lambda: prepare(world))
    assert world.proof.consumed is False and not world.s.new


def test_registered_refresh_rejects_current_pointer_epoch_change(world, monkeypatch):
    phase = prepare(world)
    changed = world.pointer.model_copy(update={"epoch": world.pointer.epoch + 1})
    monkeypatch.setattr(preparation.anchor_storage, "_current", lambda *_: changed)
    reject(
        "SOURCE_STALE",
        lambda: preparation.require_prepared_candidate(
            world.s, world.ctx, world.product.id, world.payload, phase
        ),
    )


def test_registered_refresh_rejects_deep_mutated_proof_snapshot(world):
    phase = prepare(world)
    world.proof.snapshot["policy_snapshot"]["facts_revision"] = digest("in-memory substitution")
    reject(
        "CANDIDATE_PERSISTED_PROOF_CHANGED",
        lambda: preparation.require_prepared_candidate(
            world.s, world.ctx, world.product.id, world.payload, phase
        ),
    )


def test_missing_restore_host_and_copied_phase_never_issue_write_qualification(world):
    reject("CANDIDATE_ANCHOR_RESTORE_REQUIRED", lambda: prepare(world, host=None))
    phase = prepare(world)
    for copied in (copy(phase), replace(phase)):
        reject(
            "CANDIDATE_PREPARED_OWNER_REQUIRED",
            lambda copied=copied: preparation.require_prepared_candidate(
                world.s, world.ctx, world.product.id, world.payload, copied
            ),
        )


def test_private_requested_audience_is_not_promoted_by_old_product_confirmation(world):
    payload = world.payload.model_copy(update={"visibility": "private"})
    command = world.command.model_copy(update={"payload": payload.model_dump(mode="json")})
    reject(
        "CANDIDATE_PROOF_BINDING_MISMATCH", lambda: prepare(world, command=command, payload=payload)
    )


def test_later_registered_refresh_rechecks_sources_and_current_permissions(world):
    phase = prepare(world)
    world.grant.can_write = False
    reject(
        "FORBIDDEN_SCOPE",
        lambda: preparation.require_prepared_candidate(
            world.s, world.ctx, world.product.id, world.payload, phase
        ),
    )


def test_saved_clock_does_not_extend_original_proof_expiry(world):
    phase = prepare(world)
    world.clock.at = world.proof.expires_at
    reject(
        "SOURCE_STALE",
        lambda: preparation.require_prepared_candidate_clock(
            world.s, world.ctx, world.product.id, world.payload, phase, world.clock.at
        ),
    )


def test_registered_phase_is_single_use_and_no_current_or_receipt_is_written(world):
    phase = prepare(world)
    preparation.invalidate_prepared_candidate(phase)
    reject("CANDIDATE_PREPARED_OWNER_REQUIRED", lambda: preparation.reviewed_candidate(phase))
    assert not world.s.new and not world.s.deleted and world.proof.consumed is False
