"""Real preparation control flow; owner/SQL results are explicit substitutes.

Actual SQLAlchemy Session/UOW and actual immutable DTO validation are used.
No connection, original bytes, qualification or database atom is attested.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from quality_issues.helpers import NOW, fixed_run, source, uid
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from pdos_next.domain.capa_effectiveness import anchor as a
from pdos_next.domain.capa_effectiveness import candidate_commands as commands
from pdos_next.domain.capa_effectiveness import candidate_prepare as preparation
from pdos_next.domain.capa_effectiveness import candidate_storage as storage
from pdos_next.domain.capa_effectiveness.facts import FactRef
from pdos_next.domain.capa_verification import service as followup
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.capa_verification.schemas import (
    CandidateBinding,
    CandidateInspect,
    FailurePairMapping,
    Missing,
)
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.quality_issues.rules import failure_ref
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
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
    engine = create_engine("sqlite://")
    event.listen(engine, "do_connect", lambda *_: pytest.fail("Owned pure must never connect"))
    s = Session(engine)
    s.begin()
    ctx = Context(
        origin.scope.tenant_id,
        uid("shared-reader"),
        uid("shared-reader"),
        category_id=origin.category_id,
    )
    product = Product(
        id=origin.scope.product_id,
        tenant_id=ctx.tenant_id,
        category_id=origin.category_id,
        revision=10,
    )
    principal = Principal(
        id=ctx.actor_id, tenant_id=ctx.tenant_id, kind="human", active=True, access_epoch=1
    )
    grant = Grant(
        id=uid("reader-grant"),
        tenant_id=ctx.tenant_id,
        category_id=origin.category_id,
        principal_id=ctx.actor_id,
        can_write=True,
        access_epoch=1,
        expires_at=clock.at + timedelta(hours=2),
    )
    fact = ProfessionalFact(
        id=uid("reader-professional"),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=origin.scope.project_id,
        subject_id=ctx.requester_id,
        revision=1,
        state="active",
        valid_from=NOW,
        valid_until=clock.at + timedelta(hours=2),
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
    rows = {Product: product, Principal: principal, Grant: grant, ProfessionalFact: fact}

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
    monkeypatch.setattr(preparation, "_clock", lambda: clock.at)
    project = preparation.anchor_storage.StoredProjectScope(
        scope=origin.scope,
        owner_id=uid("project-owner"),
        visibility="category",
        declared_scope="Explicit shared test project",
    )
    pointer = preparation.anchor_storage.StoredIssueCurrent(
        pointer_id=uid("issue-current"),
        pointer_created_at=NOW,
        ref=origin.ref,
        epoch=1,
        operation=origin.operation,
        created_at=NOW,
    )
    raw = [
        {k: v for k, v in a.json_value(safe).items() if v is not None}
        for safe in origin.source_basis
    ]
    basis = followup.basis_from_issue(
        row,
        origin.issue,
        sources=origin.sources,
        reads=origin.required_source_read_set,
        source_basis=raw,
    )
    state = SimpleNamespace(
        owner_calls=0,
        saved_calls=0,
        query_calls=0,
        source_calls=0,
        authority_calls=0,
        policy_calls=0,
        owner_hook=None,
        saved_hook=None,
        source_hook=None,
        authority_hook=None,
        policy_hook=None,
        exists=True,
        count=1,
        saved=original,
        group={"actual_common_group_substitute": "immutable"},
        queries=[],
    )
    selected_row = CapaVerificationEvidence(
        id=uid("earliest-candidate"),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        issue_id=origin.issue_id,
        issue_version_id=origin.ref.id,
        issue_revision=origin.ref.revision,
        created_at=NOW + timedelta(minutes=1),
    )
    payload = commands.CandidateRecordPayload(
        issue_id=origin.issue_id,
        expected_issue_revision=origin.ref.revision,
        capa_id=origin.issue.capa.id,
        reason="Later full candidate selection",
        visibility="category",
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
    monkeypatch.setattr(
        preparation.followup, "load_followup_basis", lambda *_args, **_kwargs: basis
    )
    monkeypatch.setattr(preparation.evidence, "refs_from_exact", lambda *_: ())

    def source_basis(*_args):
        state.source_calls += 1
        if state.source_hook:
            state.source_hook(state.source_calls)
        return deepcopy(raw), False

    monkeypatch.setattr(preparation.evidence, "source_basis", source_basis)

    def inspection(_s, _ctx, _pid, actual_binding, **kwargs):
        assert (_s, _ctx, _pid) == (s, ctx, product.id) and kwargs["write"] is False
        inspected = CandidateInspect(
            binding=actual_binding,
            current=True,
            required_source_read_set=origin.required_source_read_set,
            source_basis_sha256=digest(raw),
            inspection_sha256="0" * 64,
            missing=(
                Missing(
                    dimension="observation",
                    code="INTEGRATION_REQUIRED",
                    detail="Explicit test owner missing; never positive",
                ),
            ),
        )
        return inspected.model_copy(
            update={
                "inspection_sha256": digest(
                    inspected.model_dump(
                        mode="json", exclude={"inspection_sha256", "candidate_ref"}
                    )
                )
            }
        )

    monkeypatch.setattr(preparation.followup, "inspect_candidate", inspection)

    def fresh():
        result = original.failures[0].result.model_copy(deep=True)
        result.retained["checked_at"] = clock.at.isoformat()
        result.retained["execution_window_elapsed"] = True
        result.source_basis["runtime_stamp"] = digest(clock.at)
        return a.build_anchor(
            origin,
            (a.OriginalFailureProof(failure=original.failures[0].failure, result=result),),
            source_basis=origin.source_basis,
        )

    def actual_owner(_s, _ctx, _pid, issue_id, ref):
        assert (_s, _ctx, _pid, issue_id, ref) == (s, ctx, product.id, origin.issue_id, origin.ref)
        state.owner_calls += 1
        anchor = fresh()
        if state.owner_hook:
            anchor = state.owner_hook(anchor, state.owner_calls)
        return SimpleNamespace(
            anchor=anchor,
            checked_at=clock.at,
            needs_lineage_owner=False,
            origin_descriptor=SimpleNamespace(
                current=pointer, project=project, needs_lineage_owner=False
            ),
        )

    monkeypatch.setattr(preparation.anchor_owner, "read_anchor_from_actual_owner", actual_owner)

    def scalars(query):
        assert (
            query.is_select and query.column_descriptions[0]["entity"] is CapaVerificationEvidence
        )
        state.query_calls += 1
        state.queries.append(query)
        predicates = {clause.left.key: clause.right.value for clause in query._where_criteria}
        assert predicates == {
            "tenant_id": ctx.tenant_id,
            "product_id": product.id,
            "issue_id": origin.issue_id,
            "issue_version_id": origin.ref.id,
            "issue_revision": origin.ref.revision,
        }
        assert query._limit_clause.value == 1
        assert [clause.key for clause in query._order_by_clauses] == ["created_at", "id"]
        assert query.get_execution_options() == {"populate_existing": True, "autoflush": False}
        return [selected_row] * state.count if state.exists else []

    monkeypatch.setattr(s, "scalars", scalars)

    def stored(_s, _ctx, _pid, candidate_id, **kwargs):
        assert (_s, _ctx, _pid, candidate_id) == (s, ctx, product.id, selected_row.id)
        kwargs["semantic_owner"].check()
        state.saved_calls += 1
        if state.saved_hook:
            state.saved_hook(state.saved_calls)
        selected = state.saved
        body = storage.CandidateInput(
            semantic=commands.semantic(payload),
            shared_proof={"id": uid("actual-proof-substitute"), "tier": "T1"},
            proof_consumed_at=NOW + timedelta(minutes=1),
            stable_anchor=selected,
        )
        binding = CandidateBinding(basis=basis)
        ref = FactRef(
            id=selected_row.id,
            revision=1,
            sha256=digest({"body": body.model_dump(mode="json"), "group": state.group}),
        )
        return storage.StoredCandidateRead(
            ref=ref,
            candidate={"id": str(selected_row.id)},
            body=body,
            binding=binding,
            inspection=inspection(s, ctx, product.id, binding, write=False),
            group=deepcopy(state.group),
            origin=SimpleNamespace(),
            registry=None,
            registry_observed_at=clock.at,
            missing=("actual original IO substituted",),
        )

    monkeypatch.setattr(storage, "read_candidate", stored)
    authority = {
        "scope": origin.scope.model_dump(mode="json"),
        "subject_id": str(ctx.requester_id),
        "operation": commands.OPERATION,
        "purpose": origin.purpose,
        "authorized": True,
        "qualified": True,
        "facts_revision": digest("test profession"),
        "roles": ["quality"],
        "fact_refs": [
            {
                "id": str(fact.id),
                "revision": 1,
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": [commands.OPERATION],
                "purposes": [origin.purpose],
                "valid_from": NOW.isoformat(),
                "valid_until": fact.valid_until.isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
        "valid_until": None,
        "synthetic": True,
        "required_source_read_set": [],
    }
    policy = {
        "id": str(uid("policy")),
        "revision": 1,
        "nature": "synthetic",
        "facts_revision": digest("test policy"),
        "valid_until": None,
        "source_basis": [
            {
                "id": str(uid("policy")),
                "revision": 1,
                "state": "active",
                "valid_from": NOW.isoformat(),
                "valid_until": fact.valid_until.isoformat(),
            }
        ],
        "private": False,
        "required_source_read_set": [],
        "sources": [],
    }

    def assess(*args, **kwargs):
        assert args[:6] == (
            s,
            ctx,
            product.id,
            origin.scope.project_id,
            commands.OPERATION,
            origin.purpose,
        )
        state.authority_calls += 1
        value = deepcopy(authority)
        return state.authority_hook(value, state.authority_calls) if state.authority_hook else value

    def policy_assess(*args):
        assert args == (s, ctx, product.id, origin.scope.project_id, origin.purpose)
        state.policy_calls += 1
        value = deepcopy(policy)
        return state.policy_hook(value, state.policy_calls) if state.policy_hook else value

    monkeypatch.setitem(
        preparation.professional.OPERATION_ROLES, commands.OPERATION, frozenset({"quality"})
    )
    monkeypatch.setattr(preparation.professional, "assess", assess)
    monkeypatch.setattr(preparation.policy, "assess", policy_assess)
    work = SimpleNamespace(
        s=s,
        ctx=ctx,
        pid=product.id,
        payload=payload,
        original=original,
        state=state,
        clock=clock,
        grant=grant,
        principal=principal,
        pointer=pointer,
        raw=raw,
        fresh=fresh,
        authority=authority,
        policy=policy,
        selected_row=selected_row,
        stored=stored,
    )
    yield work
    s.rollback()
    s.close()
    engine.dispose()


def run(work, payload=None):
    return preparation.prepare_candidate(
        work.s, work.ctx, work.pid, payload or work.payload, origin_ref=work.original.origin.ref
    )


def reject(code, call):
    with pytest.raises(DomainError) as caught:
        call()
    assert caught.value.reason == code
    return caught.value


def test_later_candidate_preserves_earliest_full_anchor_and_original_clocks(world):
    fresh = world.fresh()
    assert fresh.anchor_sha256 != world.original.anchor_sha256
    assert fresh.full_failure_proofs_sha256 != world.original.full_failure_proofs_sha256
    assert preparation._anchor_material(fresh) == preparation._anchor_material(world.original)
    out = run(world)
    assert out.anchor == world.original
    assert out.anchor.model_dump(mode="json") == world.original.model_dump(mode="json")
    assert out.anchor.anchor_sha256 == world.original.anchor_sha256
    assert out.anchor.failures[0].result.retained["checked_at"] == NOW.isoformat()
    assert out.anchor.failures[0].result.retained["execution_window_elapsed"] is False
    assert out.anchor.failures[0].result.source_basis["runtime_stamp"] == digest(
        "initial-host-runtime"
    )
    assert out.checked_at == world.clock.at
    assert world.state.owner_calls == world.state.saved_calls == world.state.query_calls == 2
    assert world.state.authority_calls == world.state.policy_calls == 2
    assert not world.s.new and not world.s.dirty and not world.s.deleted
    assert out.inspection.result == "indeterminate"
    assert (
        out.inspection.applicable
        is out.inspection.independently_verified
        is out.inspection.observation_complete
        is None
    )


def test_initial_candidate_has_no_stored_root_and_keeps_actual_full_proof(world):
    world.state.exists = False
    out = run(world)
    assert out.anchor == world.fresh() and out.anchor != world.original
    assert world.state.saved_calls == 0 and world.state.owner_calls == world.state.query_calls == 2


def test_complete_later_selection_uses_same_root_without_changing_business_mapping(world):
    failure = world.original.failures[0].failure
    sample = world.original.failures[0].result.verified.run.samples[0]
    mapping = FailurePairMapping(
        failure_id=failure.identity,
        run={"kind": "verification_run", "id": uid("new-run-current"), "revision": 5},
        sample_id=uid("new-sample"),
        sample_revision=sample.revision,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=sample.actual_configuration.revision,
        item_id=sample.id.hex,
        measurement_id=uid("new-real-measurement"),
    )
    payload = world.payload.model_copy(
        update={
            "mappings": (mapping,),
            "remediation_link_refs": (
                preparation.commands.FixedRef(id=uid("actual-link"), revision=1),
            ),
        }
    )
    out = run(world, payload)
    assert out.anchor == world.original
    assert (
        out.binding.mappings == payload.mappings
        and out.binding.remediation_link_refs == payload.remediation_link_refs
    )
    assert preparation.reviewed_candidate(out)["stable_anchor"] == world.original.model_dump(
        mode="json"
    )


def test_same_session_next_phase_re_reads_actual_owners_and_saved_group(world):
    first = run(world)
    world.clock.at += timedelta(minutes=10)
    second = run(world)
    assert first.anchor == second.anchor == world.original
    assert first.checked_at != second.checked_at
    assert world.state.owner_calls == world.state.saved_calls == 4


@pytest.mark.parametrize(
    "path",
    [
        "plan_binding",
        "occupancy",
        "sample_usage",
        "facts_revision",
        "source_basis",
        "original_bytes",
    ],
)
def test_changed_business_proof_cannot_reuse_saved_anchor(world, path):
    def change(value, _call):
        result = value.failures[0].result.model_copy(deep=True)
        if path == "plan_binding":
            result.retained[path]["checked_at"] = "CHANGED real fixed data"
        elif path in {"occupancy", "sample_usage"}:
            result.retained[path][0]["epoch"] += 2
        elif path == "facts_revision":
            result.retained[path] = digest("new resource issuer epoch")
        elif path == "source_basis":
            result.retained[path]["epoch"] += 2
        else:
            result.source_basis["original_bytes_sha256"] = digest("changed original bytes")
        return a.build_anchor(
            value.origin,
            (a.OriginalFailureProof(failure=value.failures[0].failure, result=result),),
            source_basis=value.origin_source_basis,
        )

    world.state.owner_hook = change
    reject("SOURCE_STALE", lambda: run(world))


def test_changed_original_measurement_is_not_hidden_by_clock_exclusions(world):
    def change(value, _call):
        result = value.failures[0].result.model_copy(deep=True)
        run = result.verified.run
        measurements = tuple(
            m.model_copy(update={"raw_value": "12.0000"}) for m in run.measurements
        )
        result = result.model_copy(
            update={
                "verified": result.verified.model_copy(
                    update={"run": run.model_copy(update={"measurements": measurements})}
                )
            }
        )
        changed = a.OriginalFailureProof(
            failure=failure_ref(result.verified, result.measurement_id), result=result
        )
        return a.build_anchor(value.origin, (changed,), source_basis=value.origin_source_basis)

    world.state.owner_hook = change
    reject("SOURCE_STALE", lambda: run(world))


def test_original_source_security_epoch_change_blocks_root_reuse(world):
    # A bridge-only uploaded source extends the row's original source closure.
    # Its epoch can change without changing the immutable Issue snapshot.
    original = world.original
    reference = source("additional-actual-report")
    read = SourceRead(artifact_id=reference.id, expected_revision=reference.revision)
    safe = SourceSafety(
        id=reference.id,
        revision=1,
        hash=digest("real original bytes test substitute"),
        status="active",
        owner_id=uid("report-owner"),
        visibility="category",
        source_kind="uploaded_original",
        original=a.OriginalSafety(
            id=uid("original"), epoch=1, source_state="active", disposition="active"
        ),
    )
    result = original.failures[0].result.model_copy(
        update={
            "sources": (*original.failures[0].result.sources, reference),
            "required_source_read_set": (
                *original.failures[0].result.required_source_read_set,
                read,
            ),
        }
    )
    failures = (a.OriginalFailureProof(failure=original.failures[0].failure, result=result),)
    old = a.build_anchor(
        original.origin, failures, source_basis=(*original.origin_source_basis, safe)
    )
    changed = safe.model_copy(update={"original": safe.original.model_copy(update={"epoch": 3})})
    fresh = a.build_anchor(
        original.origin, failures, source_basis=(*original.origin_source_basis, changed)
    )
    world.state.saved = old
    actual = SimpleNamespace(anchor=fresh)
    reject(
        "SOURCE_STALE",
        lambda: preparation._saved_origin_anchor(
            world.s, world.ctx, world.pid, world.payload, actual
        ),
    )


@pytest.mark.parametrize(
    "code,status", [("SOURCE_UNAVAILABLE", 409), ("FORBIDDEN_SCOPE", 403), ("SOURCE_STALE", 409)]
)
def test_real_owner_withdrawal_acl_or_issuer_failure_is_not_replaced_by_saved_proof(
    world, code, status
):
    def fail(*_):
        raise DomainError(code, "explicit original-owner rejection", status)

    world.state.owner_hook = fail
    assert reject(code, lambda: run(world)).status == status
    assert world.state.saved_calls == 0


def test_broken_actual_saved_group_never_falls_back_to_fresh_anchor(world):
    def fail(_):
        raise DomainError("CANDIDATE_POST_IO_CHANGED", "actual group missing", 503)

    world.state.saved_hook = fail
    reject("CANDIDATE_POST_IO_CHANGED", lambda: run(world))


@pytest.mark.parametrize("mutation", ["group", "root", "root_gone", "earlier_new_root"])
def test_post_owner_root_group_or_selection_change_rejects(world, mutation):
    def change(call):
        if call != 2:
            return
        if mutation == "group":
            world.state.group["actual_common_group_substitute"] = "changed receipt"
        elif mutation == "root":
            world.state.saved = world.fresh()
        elif mutation == "earlier_new_root":
            world.selected_row.id = uid("different-root")

    world.state.saved_hook = change
    if mutation == "root_gone":
        world.state.source_hook = lambda call: (
            setattr(world.state, "exists", False) if call == 2 else None
        )
    reject("SOURCE_STALE", lambda: run(world))


def test_root_appearing_during_initial_read_cannot_switch_original_full_anchor(world):
    world.state.exists = False
    world.state.source_hook = lambda call: (
        setattr(world.state, "exists", True) if call == 2 else None
    )
    reject("SOURCE_STALE", lambda: run(world))


def test_current_source_after_saved_read_keeps_independent_final_rejection(world):
    def change(call):
        if call == 3:
            world.raw[0]["hash"] = digest("source withdrawn or restored with different proof")

    world.state.source_hook = change
    reject("SOURCE_STALE", lambda: run(world))


@pytest.mark.parametrize("dimension", ["authority", "policy"])
def test_professional_or_policy_epoch_change_after_io_is_still_rejected(world, dimension):
    def change(value, call):
        if call == 2:
            value["facts_revision"] = digest("actual epoch ABA")
        return value

    setattr(world.state, dimension + "_hook", change)
    reject("SOURCE_STALE", lambda: run(world))


def test_current_cas_is_not_relaxed_by_an_existing_saved_anchor(world):
    payload = world.payload.model_copy(
        update={"expected_issue_revision": world.payload.expected_issue_revision - 1}
    )
    reject("VERSION_CONFLICT", lambda: run(world, payload))
    assert world.state.saved_calls == 0


def test_current_lineage_owner_stays_required(world):
    read = preparation.anchor_owner.read_anchor_from_actual_owner

    def successor(*args):
        value = read(*args)
        value.origin_descriptor.needs_lineage_owner = True
        value.needs_lineage_owner = True
        return value

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(preparation.anchor_owner, "read_anchor_from_actual_owner", successor)
    try:
        reject("CANDIDATE_LINEAGE_OWNER_REQUIRED", lambda: run(world))
    finally:
        monkeypatch.undo()


def test_unknown_professional_does_not_gain_authority_from_saved_anchor(world):
    world.authority["qualified"] = None
    reject("QUALIFICATION_REQUIRED", lambda: run(world))


def test_final_actual_clock_rejects_expiry_after_saved_group_io(world):
    world.state.saved_hook = lambda call: (
        setattr(world.clock, "at", world.grant.expires_at) if call == 2 else None
    )
    reject("SOURCE_STALE", lambda: run(world))


def test_runtime_port_replacement_during_saved_group_read_rejects(world, monkeypatch):
    world.state.saved_hook = lambda call: (
        monkeypatch.setattr(storage, "read_candidate", lambda *_args, **_kw: None)
        if call == 2
        else None
    )
    reject("SOURCE_STALE", lambda: run(world))


def test_real_select_is_exact_bounded_ordered_without_autoflush(world):
    run(world)
    query = world.state.queries[0]
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert (
        sql.startswith("SELECT ")
        and "ORDER BY capa_verification_evidence.created_at, capa_verification_evidence.id" in sql
    )
    assert query.compile(dialect=postgresql.dialect()).params["param_1"] == 1


def test_more_than_100_candidates_keep_the_actual_earliest_saved_anchor(world):
    world.state.count = 101
    phase = run(world)
    assert phase.anchor.material_sha256 == world.original.material_sha256
    assert world.state.saved_calls > 0


def write_binding(world, phase, original_anchor):
    project = preparation.anchor_storage._project(
        world.s, world.ctx, world.pid, phase.binding.basis.scope.project_id
    )
    return SimpleNamespace(
        restored=SimpleNamespace(anchor=original_anchor, expires_at=world.grant.expires_at),
        proof=object(),
        proof_immutable_sha256=digest("real immutable proof test substitute"),
        reviewed_snapshot=preparation._write_review(phase, original_anchor),
        current_snapshot=world.pointer,
        project_snapshot=project,
        caller_watermark=preparation._caller(world.s, world.ctx, world.pid)[0],
    )


def write_command(world):
    return preparation.Command(
        command_id=uid("exact-write-command"),
        idempotency_key="original-preview-key",
        operation=commands.OPERATION,
        category_id=world.ctx.category_id,
        product_id=world.pid,
        expected_revision=10,
        source_read_set=[
            r.model_dump(mode="json") for r in world.original.origin_required_source_read_set
        ],
        payload=world.payload.model_dump(mode="json"),
    )


def test_restore_cannot_replace_persisted_root_by_an_older_pre_root_preview(world):
    phase = run(world)
    older_preview = world.fresh()
    assert older_preview != phase.anchor
    binding = write_binding(world, phase, older_preview)
    reject(
        "SOURCE_STALE",
        lambda: preparation._finish_write(
            world.s, world.ctx, write_command(world), world.payload, phase, binding
        ),
    )


@pytest.mark.parametrize("has_root", [True, False])
def test_real_confirmation_anchor_restoration_keeps_root_or_first_preview(
    world, monkeypatch, has_root
):
    world.state.exists = has_root
    phase = run(world)
    binding = write_binding(world, phase, world.original)
    monkeypatch.setattr(preparation, "_immutable_proof", lambda *_: binding.proof_immutable_sha256)
    out = preparation._finish_write(
        world.s, world.ctx, write_command(world), world.payload, phase, binding
    )
    assert out.anchor == world.original
    assert (out.persistent_origin_ref is not None) == has_root


def test_new_root_after_phase_creation_requires_a_new_real_preview(world):
    world.state.exists = False
    phase = run(world)
    world.state.exists = True
    reject(
        "SOURCE_STALE",
        lambda: preparation.require_prepared_candidate(
            world.s, world.ctx, world.pid, world.payload, phase
        ),
    )


def test_persistent_root_ref_is_internal_sealed_metadata_not_a_new_review_field(world):
    phase = run(world)
    review = preparation.reviewed_candidate(phase)
    assert len(review) == 12 and "persistent_origin_ref" not in review
    assert phase.persistent_origin_ref is not None
    changed = replace(phase, persistent_origin_ref=None)
    assert preparation._seal(changed) != preparation._seal(phase)
    reject(
        "CANDIDATE_PREPARED_OWNER_REQUIRED",
        lambda: preparation.require_prepared_candidate(
            world.s, world.ctx, world.pid, world.payload, changed
        ),
    )


def test_source_change_inside_terminal_saved_group_io_is_rechecked(world):
    def drift(call):
        if call == 2:
            world.raw[0]["hash"] = digest("source changed during saved-group SELECT")

    world.state.saved_hook = drift
    reject("SOURCE_STALE", lambda: run(world))
