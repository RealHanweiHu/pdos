"""Staged paired-output structure checks and a live, caller-UOW reader protocol.

No ORM, writer, transaction creation, permission grant or public route lives here.
``verify_paired_material`` accepts host-read material, but proves relationships only.
Only an explicitly installed reader can provide separate, opaque live gate proof.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pdos_next.domain.quality_issues.rules import digest
from pdos_next.domain.verification.ports import DomainEvent
from pdos_next.domain.verification.rules import accepted_coverage, compute_results, pairs
from pdos_next.domain.verification_launch.schemas import (
    ExecutionPlan,
    PlanPayload,
    PromisePayload,
    StartPayload,
)
from pdos_next.domain.verification_results.schemas import (
    DispositionPayload,
    ImportPayload,
    ReviewPayload,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ComputedResult,
    EventTime,
    Scope,
    SourceRef,
    TestRun,
    VerificationRequest,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    ValidationError,
)

Revision = Annotated[StrictInt, Field(ge=1, le=2147483647)]
Sha256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(strict=True, min_length=1, max_length=2000)]
Operation = Literal[
    "test.run.plan",
    "verification.schedule.promise",
    "test.run.start",
    "test.results.import",
    "test.run.review",
    "test.disposition.decide",
]
EVENTS = {
    "test.run.plan": "test.run_planned",
    "verification.schedule.promise": "verification.start_promised",
    "test.run.start": "test.run_started",
    "test.results.import": "test.results_imported",
    "test.run.review": "test.run_reviewed",
    "test.disposition.decide": "test.disposition_decided",
}
PAYLOAD_TYPES = {
    "test.run.plan": PlanPayload,
    "verification.schedule.promise": PromisePayload,
    "test.run.start": StartPayload,
    "test.results.import": ImportPayload,
    "test.run.review": ReviewPayload,
    "test.disposition.decide": DispositionPayload,
}


class Closed(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        allow_inf_nan=False,
        revalidate_instances="always",
    )


class FixedRef(Closed):
    id: UUID
    revision: Revision


class FormalRef(FixedRef):
    kind: Literal["verification_request"] = "verification_request"


class SourceRead(Closed):
    artifact_id: UUID
    expected_revision: Revision


class PairBinding(Closed):
    """Scope/caller/purpose come from server Context and the real Issue/owner."""

    scope: Scope
    build: BuildRef
    request_id: UUID
    run_id: UUID
    purpose: Text
    caller_id: UUID
    output_ref: FormalRef


class FormalRow(Closed):
    ref: FixedRef
    previous: FixedRef | None
    owner_id: UUID
    # Derived from this row's saved authority.subject_id, not a nonexistent ORM column.
    authority_actor_id: UUID
    visibility: Literal["private", "product"]
    operation: Text
    snapshot: VerificationRequest
    snapshot_sha256: Sha256
    domain_intent: Sha256
    reads: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)
    created_at: AwareDatetime


class RunRow(Closed):
    ref: FixedRef
    previous: FixedRef | None
    origin_request: FixedRef
    owner_id: UUID
    writer_id: UUID
    visibility: Literal["private", "product"]
    operation: Text
    snapshot: TestRun
    snapshot_sha256: Sha256
    plan: ExecutionPlan
    plan_sha256: Sha256
    domain_intent: Sha256
    reads: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)
    created_at: AwareDatetime


class FactBase(Closed):
    ref: FixedRef
    scope: Scope
    build_id: UUID
    request_id: UUID
    run_id: UUID
    request_before: FixedRef
    next_request: FixedRef
    actor_id: UUID
    visibility: Literal["private", "product"]
    operation: Operation
    input_snapshot: dict[str, JsonValue]
    domain_intent: Sha256
    reads: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)
    created_at: AwareDatetime


class LaunchFact(FactBase):
    kind: Literal["launch"] = "launch"
    operation: Literal["test.run.plan", "verification.schedule.promise", "test.run.start"]
    run: FixedRef
    kernel_event: DomainEvent
    snapshot_sha256: Sha256


class ResultAction(FactBase):
    kind: Literal["result"] = "result"
    operation: Literal["test.results.import", "test.run.review", "test.disposition.decide"]
    run_before: FixedRef
    next_run: FixedRef
    projection: FixedRef
    event: EventTime


class ProjectionRow(Closed):
    ref: FixedRef
    scope: Scope
    build_id: UUID
    request_id: UUID
    run_id: UUID
    run: FixedRef
    run_sha256: Sha256
    basis_sha256: Sha256
    rules_version: Text
    rules_sha256: Sha256
    result: Literal["pass", "fail", "indeterminate"]
    computed_results: tuple[ComputedResult, ...]
    reads: tuple[SourceRead, ...] = Field(min_length=1, max_length=20)


class ReceiptResult(Closed):
    id: UUID
    revision: Revision
    status: Text


class CommonIntentMaterial(Closed):
    """Exact common material derived with the actual handler.semantic and Context.

    The real reader must obtain the original payload/semantic and verify its handler.
    Missing input cannot be guessed from a Run snapshot or domain intent string.
    """

    handler: Literal["verification_launch", "verification_results"]
    operation: Operation
    product: UUID
    payload: dict[str, JsonValue]
    named_actor: UUID
    source_revision: Revision | None
    private_owner: UUID | None


class ReceiptRow(Closed):
    id: UUID
    tenant_id: UUID
    product_id: UUID
    command_id: UUID
    actor_id: UUID
    requester_id: UUID
    operation: Operation
    subject_type: Literal["verification_request", "test_run"]
    subject: FixedRef
    visibility: Literal["private", "product"]
    request_digest: Sha256
    common_intent: Sha256
    run_id: UUID | None
    result: ReceiptResult
    created_at: AwareDatetime


class AuditRow(Closed):
    id: UUID
    tenant_id: UUID
    receipt_id: UUID
    actor_id: UUID
    operation: Operation


class OutboxRow(Closed):
    id: UUID
    tenant_id: UUID
    receipt_id: UUID
    type: Text
    subject: FixedRef
    actor_id: UUID
    correlation_id: UUID
    schema_version: Literal[1]


class PairedMaterial(Closed):
    request_before: FormalRow
    request_after: FormalRow
    origin_request: FormalRow
    run_before: RunRow | None
    run_after: RunRow
    request_current: FixedRef | None
    run_current: FixedRef | None
    fact: Annotated[LaunchFact | ResultAction, Field(discriminator="kind")] | None
    receipt: ReceiptRow | None
    audits: tuple[AuditRow, ...] = Field(max_length=10)
    outbox: tuple[OutboxRow, ...] = Field(max_length=10)
    common_material: CommonIntentMaterial | None
    projection: ProjectionRow | None = None
    projection_run: RunRow | None = None


class Missing(Closed):
    code: Text
    detail: Text


class StructuralPairProof(Closed):
    schema_version: Literal["paired-formal-v1"] = "paired-formal-v1"
    structural_only: Literal[True] = True
    binding: PairBinding
    current_formal: FixedRef
    current_run: FixedRef
    origin_formal: FixedRef
    fact: FixedRef
    fact_kind: Literal["launch", "result"]
    receipt_id: UUID
    command_id: UUID
    operation: Operation
    owner_id: UUID
    run_owner_id: UUID
    writer_id: UUID
    meaning: Literal["planned", "performed"]
    required_source_read_set: tuple[SourceRead, ...]
    material_sha256: Sha256


class PairInspection(Closed):
    proof: StructuralPairProof | None = None
    missing: tuple[Missing, ...] = ()


def _require(condition, code, detail):
    if not condition:
        raise DomainError(code, detail, 409)


def _json(value):
    return value.model_dump(mode="json")


def _instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError("INVALID_TIME", "Pair evaluation requires an aware server instant.", 422)
    return value.astimezone(UTC)


def _missing(code, detail):
    return PairInspection(missing=(Missing(code=code, detail=detail),))


def _merged_reads(groups):
    reads = {}
    for group in groups:
        for ref in group:
            if ref.artifact_id in reads and reads[ref.artifact_id] != ref.expected_revision:
                raise DomainError("SOURCE_STALE", "One source cannot bind conflicting versions.")
            reads[ref.artifact_id] = ref.expected_revision
    _require(
        len(reads) <= 20,
        "MISSING_REQUIRED_EVIDENCE",
        "Full pair sources exceed 20; never truncate.",
    )
    return tuple(
        SourceRead(artifact_id=k, expected_revision=v)
        for k, v in sorted(reads.items(), key=lambda item: item[0].bytes)
    )


def _artifact_refs(value):
    refs = []
    if isinstance(value, dict):
        if value.get("kind") == "artifact" and {"id", "revision"} <= value.keys():
            refs.append(SourceRead(artifact_id=value["id"], expected_revision=value["revision"]))
        if {"artifact_id", "expected_revision", "line", "quote"} <= value.keys():
            refs.append(
                SourceRead(
                    artifact_id=value["artifact_id"], expected_revision=value["expected_revision"]
                )
            )
        for child in value.values():
            refs.extend(_artifact_refs(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            refs.extend(_artifact_refs(child))
    return refs


def _payload(material):
    # Validate with the real closed input DTO, rather than accepting an empty
    # dictionary which merely hashes consistently. Canonical semantic itself is
    # supplied by the host's real handler and separately attested by its gate.
    raw = material.fact.input_snapshot
    if {"confirmation_token", "approval_token"} & raw.keys():
        raise DomainError(
            "PAIR_ORIGINAL_SEMANTIC_MISMATCH", "Semantic proof must not include approval secrets."
        )
    try:
        payload = PAYLOAD_TYPES[material.fact.operation].model_validate(raw)
    except ValidationError:
        return None
    keys = payload.model_dump(exclude={"confirmation_token", "approval_token"}).keys()
    return payload if raw.keys() == keys else None


def _event(time):
    return time.model_dump(mode="json", exclude={"received_at", "actor_id"})


def _source(reference):
    # Exact established DefinitionReference -> SourceRef locator convention.
    return SourceRef(
        id=reference.artifact_id,
        revision=reference.expected_revision,
        kind="artifact",
        position=f"line:{reference.line};quote_sha256:{sha256(reference.quote.encode()).hexdigest()}",
    )


def _payload_binding(binding, material, payload, at):
    f, run = material.fact, material.run_after.snapshot
    _require(
        payload.request_id == binding.request_id
        and payload.run_id == binding.run_id
        and payload.expected_request_revision == material.request_before.ref.revision,
        "PAIR_ORIGINAL_SEMANTIC_MISMATCH",
        "Actual original payload must bind its exact request predecessor.",
    )
    if f.operation == "test.run.plan":
        _require(
            payload.execution_plan == material.run_after.plan
            and pairs(payload.coverage) == pairs(run.coverage),
            "PAIR_ORIGINAL_SEMANTIC_MISMATCH",
            "Plan input must match saved execution plan and exact coverage.",
        )
        return
    _require(
        payload.expected_run_revision == material.run_before.ref.revision,
        "PAIR_ORIGINAL_SEMANTIC_MISMATCH",
        "Actual original payload must bind its exact Run predecessor.",
    )
    if isinstance(f, LaunchFact):
        clock = (
            material.request_after.snapshot.timeline.promised_start
            if f.operation == "verification.schedule.promise"
            else run.actual_start
        )
        _require(
            payload.expected_plan_sha256 == material.run_after.plan_sha256,
            "PAIR_ORIGINAL_SEMANTIC_MISMATCH",
            "Original action cannot change fixed execution-plan hash.",
        )
        _require(
            clock is not None
            and _event(clock) == _json(payload.at)
            and f.kernel_event.at == clock
            and clock.actor_id == f.actor_id
            and clock.received_at <= at,
            "PAIR_EVENT_MISMATCH",
            "Saved action clock must match exact original event and named actor.",
        )
        if f.operation == "test.run.start":
            _require(
                material.request_after.snapshot.timeline.actual_start == clock,
                "PAIR_EVENT_MISMATCH",
                "Formal and Run must bind the same Actual start fact.",
            )
            _require(
                clock.occurred_at <= clock.received_at,
                "PAIR_TIME_MISMATCH",
                "Actual start cannot be future at receipt.",
            )
        return
    _require(
        f.event == payload.at,
        "PAIR_EVENT_MISMATCH",
        "Result fact must preserve the exact original event.",
    )
    if f.operation == "test.results.import":
        added = run.measurements[len(material.run_before.snapshot.measurements) :]
        _require(
            all(
                value.observed_at is None
                or run.actual_start.occurred_at <= value.observed_at <= payload.at.occurred_at
                for value in added
            ),
            "PAIR_TIME_MISMATCH",
            "Each newly returned observation must lie between actual Start and this return.",
        )
        clock = (
            run.final_result
            if payload.final
            else run.partial_returns[-1].at
            if run.partial_returns
            else None
        )
        _require(
            clock is not None
            and _event(clock) == _json(payload.at)
            and clock.actor_id == f.actor_id
            and clock.occurred_at <= clock.received_at <= at,
            "PAIR_EVENT_MISMATCH",
            "Original return clock and partial/final state must be exact.",
        )
        if payload.final:
            _require(
                run.actual_end is not None and _event(run.actual_end) == _json(payload.actual_end),
                "PAIR_EVENT_MISMATCH",
                "Actual end cannot be reconstructed from expected time.",
            )
        _require(
            (run.status == "results_pending") == payload.final,
            "PAIR_TRANSITION_MISMATCH",
            "Partial return cannot become final status.",
        )
        if not payload.final:
            last = run.partial_returns[-1]
            present = pairs(tuple(value.coverage for value in run.measurements))
            _require(
                last.returned_coverage == tuple(value.coverage for value in added)
                and last.pending_coverage
                == tuple(c for c in run.coverage if (c.sample_id, c.item_id) not in present)
                and (last.reason, last.next_owner_id)
                == (payload.incomplete_reason, payload.next_owner_id),
                "PAIR_PARTIAL_HISTORY_CHANGED",
                "Partial return must preserve exact new coverage and responsibility.",
            )
        _require(
            material.request_after.snapshot.timeline.preliminary_result == run.preliminary_result,
            "PAIR_EVENT_MISMATCH",
            "This one-Run Formal must preserve the same first preliminary clock.",
        )
        _require(
            material.request_after.snapshot.timeline.final_result
            == (run.final_result if material.request_after.snapshot.status == "reported" else None),
            "PAIR_EVENT_MISMATCH",
            "Formal final clock requires this actual complete final return.",
        )
    else:
        conclusion = (
            run.professional_conclusion if f.operation == "test.run.review" else run.disposition
        )
        _require(
            conclusion is not None
            and conclusion.actor_id == f.actor_id
            and conclusion.text == payload.text
            and conclusion.source == payload.at.source
            and _event(conclusion.at) == _json(payload.at)
            and conclusion.at.actor_id == f.actor_id
            and conclusion.at.occurred_at <= conclusion.at.received_at <= at,
            "PAIR_EVENT_MISMATCH",
            "Named conclusion must match original text, source, actor and clock.",
        )
        _require(
            (
                payload.projection_id,
                payload.expected_projection_revision,
                payload.expected_basis_sha256,
            )
            == (
                material.projection.ref.id,
                material.projection.ref.revision,
                material.projection.basis_sha256,
            ),
            "PAIR_PROJECTION_MISMATCH",
            "Original named decision must bind its exact computed basis.",
        )
        if (
            f.operation == "test.disposition.decide"
            and material.request_after.snapshot.status == "disposed"
        ):
            _require(
                material.request_after.snapshot.timeline.disposed == conclusion.at,
                "PAIR_EVENT_MISMATCH",
                "Formal disposition must bind the actual named Run decision.",
            )


def _run_shape(row):
    run, plan = row.snapshot, row.plan
    items = {item.id for item in run.items}
    samples = {sample.id for sample in run.samples}
    _require(
        len(items) == len(run.items)
        and len(samples) == len(run.samples)
        and len(pairs(run.coverage)) == len(run.coverage)
        and all(c.item_id in items and c.sample_id in samples for c in run.coverage),
        "PAIR_FIXED_SCOPE_CHANGED",
        "Run coverage must contain exact unique samples and items.",
    )
    if run.status == "planned":
        _require(
            run.result == "pending"
            and not any(
                (
                    run.execution,
                    run.actual_start,
                    run.actual_end,
                    run.measurements,
                    run.computed_results,
                    run.partial_returns,
                    run.preliminary_result,
                    run.final_result,
                    run.professional_conclusion,
                    run.disposition,
                )
            ),
            "PAIR_EXECUTION_MISMATCH",
            "Planned output cannot contain actual execution or results.",
        )
        return
    execution = run.execution
    final = run.status in {"results_pending", "reviewed", "disposed"}
    _require(
        execution is not None
        and run.actual_start is not None
        and execution.equipment == _source(plan.equipment)
        and execution.calibration == _source(plan.calibration)
        and (execution.executor_id, execution.environment, execution.conditions)
        == (plan.executor_id, plan.environment, plan.conditions)
        and (run.actual_end is not None) == final
        and (run.final_result is not None) == final
        and (run.professional_conclusion is not None) == (run.status in {"reviewed", "disposed"})
        and (run.disposition is not None) == (run.status == "disposed"),
        "PAIR_EXECUTION_MISMATCH",
        "Execution and result clocks must match actual saved stage and fixed plan.",
    )
    _require(
        not final or pairs(tuple(v.coverage for v in run.measurements)) == pairs(run.coverage),
        "PAIR_RAW_VALUE_CHANGED",
        "Final return needs every explicit pair, including unknown raw values.",
    )
    clocks = [run.actual_start, run.actual_end, run.preliminary_result, run.final_result]
    clocks.extend(value.at for value in run.partial_returns)
    clocks.extend(value.at for value in (run.professional_conclusion, run.disposition) if value)
    _require(
        all(value.occurred_at <= value.received_at <= row.created_at for value in clocks if value),
        "PAIR_TIME_MISMATCH",
        "Actual clocks must already exist at their saved Run version.",
    )
    if final:
        _require(
            run.actual_start.occurred_at
            <= run.actual_end.occurred_at
            <= run.final_result.occurred_at,
            "PAIR_TIME_MISMATCH",
            "Final end/return must follow actual start.",
        )
    upper = (
        run.actual_end.occurred_at
        if final
        else (
            run.partial_returns[-1].at.occurred_at
            if run.partial_returns
            else run.actual_start.occurred_at
        )
    )
    _require(
        all(
            value.observed_at is None or run.actual_start.occurred_at <= value.observed_at <= upper
            for value in run.measurements
        ),
        "PAIR_TIME_MISMATCH",
        "Known observation clocks must lie within their real execution/return boundary.",
    )
    if run.professional_conclusion:
        _require(
            run.final_result.occurred_at <= run.professional_conclusion.at.occurred_at,
            "PAIR_TIME_MISMATCH",
            "Named review cannot predate final return.",
        )
    if run.disposition:
        _require(
            run.professional_conclusion.at.occurred_at <= run.disposition.at.occurred_at,
            "PAIR_TIME_MISMATCH",
            "Disposition cannot predate named review.",
        )
    if run.measurements or final:
        computed, result = compute_results(run, run.measurements, final=final)
        _require(
            run.computed_results == computed and run.result == result,
            "PAIR_PROJECTION_MISMATCH",
            "Deterministic result must match unchanged raw observations.",
        )
    else:
        _require(
            not run.computed_results and run.result == "pending",
            "PAIR_PROJECTION_MISMATCH",
            "No observation cannot become computed success.",
        )


def _request_transition(before, after, operation):
    changed = before.ref != after.ref
    expected_change = operation not in {"test.run.plan", "test.run.review"}
    if operation == "test.disposition.decide":
        expected_change = after.snapshot.status == "disposed"
    _require(
        changed == expected_change,
        "PAIR_TRANSITION_MISMATCH",
        "Unexpected Formal advance for this operation.",
    )
    if not changed:
        _require(
            before == after,
            "PAIR_TRANSITION_MISMATCH",
            "An unchanged Formal must be the same saved row.",
        )
        return False
    _require(
        after.previous == before.ref and after.ref.revision == before.ref.revision + 1,
        "PAIR_TRANSITION_MISMATCH",
        "Formal predecessor must be exact and consecutive.",
    )
    _require(
        (before.owner_id, before.visibility) == (after.owner_id, after.visibility),
        "PAIR_SCOPE_MISMATCH",
        "A successor cannot change series owner or audience.",
    )
    allowed_times = {
        "verification.schedule.promise": {"promised_start"},
        "test.run.start": {"actual_start"},
        "test.results.import": {"preliminary_result", "final_result"},
        "test.disposition.decide": {"disposed"},
    }[operation]
    a, b = _json(before.snapshot), _json(after.snapshot)
    ta, tb = a.pop("timeline"), b.pop("timeline")
    for key in allowed_times:
        _require(
            ta[key] is None or ta[key] == tb[key],
            "PAIR_EVENT_MISMATCH",
            "An already recorded Formal clock cannot be replaced.",
        )
        ta.pop(key)
        tb.pop(key)
    for key in ("revision", "status"):
        a.pop(key)
        b.pop(key)
    _require(
        a == b and ta == tb,
        "PAIR_FIXED_SCOPE_CHANGED",
        "Formal cannot rewrite accepted samples/items/configuration or other clocks.",
    )
    states = {
        "verification.schedule.promise": ({"accepted"}, {"scheduled"}),
        "test.run.start": ({"scheduled"}, {"executing"}),
        "test.results.import": ({"executing"}, {"executing", "reported"}),
        "test.disposition.decide": ({"reported"}, {"disposed"}),
    }[operation]
    _require(
        before.snapshot.status in states[0] and after.snapshot.status in states[1],
        "PAIR_TRANSITION_MISMATCH",
        "Formal status does not follow the real owner transition.",
    )
    return True


def _run_transition(material, operation):
    before, after = material.run_before, material.run_after
    if operation == "test.run.plan":
        _require(
            before is None
            and after.previous is None
            and after.ref.revision == 1
            and after.owner_id == after.writer_id
            and after.snapshot.status == "planned",
            "PAIR_TRANSITION_MISMATCH",
            "Plan must create only the initial planned Run.",
        )
        return True
    _require(
        before is not None, "PAIR_PREDECESSOR_MISSING", "Existing Run predecessor is required."
    )
    if operation == "verification.schedule.promise":
        _require(
            before == after and after.snapshot.status == "planned",
            "PAIR_TRANSITION_MISMATCH",
            "Promise leaves the planned Run unchanged.",
        )
        return False
    _require(
        after.previous == before.ref and after.ref.revision == before.ref.revision + 1,
        "PAIR_TRANSITION_MISMATCH",
        "Run predecessor must be exact and consecutive.",
    )
    _require(
        (before.owner_id, before.visibility, before.origin_request, before.plan, before.plan_sha256)
        == (after.owner_id, after.visibility, after.origin_request, after.plan, after.plan_sha256),
        "PAIR_FIXED_SCOPE_CHANGED",
        "Run origin, owner, audience and execution plan remain fixed.",
    )
    states = {
        "test.run.start": ({"planned"}, {"running"}),
        "test.results.import": ({"running"}, {"running", "results_pending"}),
        "test.run.review": ({"results_pending"}, {"reviewed"}),
        "test.disposition.decide": ({"reviewed"}, {"disposed"}),
    }[operation]
    _require(
        before.snapshot.status in states[0] and after.snapshot.status in states[1],
        "PAIR_TRANSITION_MISMATCH",
        "Run does not follow its real operation/status.",
    )
    allowed = {
        "test.run.start": {"status", "actual_start", "execution"},
        "test.results.import": {
            "status",
            "result",
            "actual_end",
            "preliminary_result",
            "final_result",
            "measurements",
            "computed_results",
            "partial_returns",
        },
        "test.run.review": {"status", "professional_conclusion"},
        "test.disposition.decide": {"status", "disposition"},
    }[operation] | {"revision"}
    _require(
        before.snapshot.model_dump(mode="json", exclude=allowed)
        == after.snapshot.model_dump(mode="json", exclude=allowed),
        "PAIR_FIXED_SCOPE_CHANGED",
        "Operation cannot rewrite fixed scope, original values or prior professional facts.",
    )
    if operation == "test.results.import":
        previous = {m.id: m for m in before.snapshot.measurements}
        present = {m.id: m for m in after.snapshot.measurements}
        _require(
            len(present) == len(after.snapshot.measurements)
            and all(present.get(k) == v for k, v in previous.items()),
            "PAIR_RAW_VALUE_CHANGED",
            "Existing raw measurements must remain exact; no duplicate IDs.",
        )
        _require(
            after.snapshot.measurements[: len(before.snapshot.measurements)]
            == before.snapshot.measurements,
            "PAIR_RAW_VALUE_CHANGED",
            "Existing raw observations must remain a complete ordered prefix.",
        )
        old_history, new_history = before.snapshot.partial_returns, after.snapshot.partial_returns
        final = after.snapshot.final_result is not None
        _require(
            (
                new_history == old_history
                if final
                else len(new_history) == len(old_history) + 1 and new_history[:-1] == old_history
            ),
            "PAIR_PARTIAL_HISTORY_CHANGED",
            "Final preserves history; partial appends exactly one unchanged-prefix return.",
        )
        _require(
            after.snapshot.preliminary_result
            == (before.snapshot.preliminary_result or (None if final else new_history[-1].at)),
            "PAIR_EVENT_MISMATCH",
            "The first preliminary Run clock cannot be replaced or backfilled.",
        )
    return True


def verify_paired_material(
    binding: PairBinding, material: PairedMaterial, *, at: datetime
) -> PairInspection:
    """Pure structure checks. Positive output is explicitly not live authorization."""
    binding = PairBinding.model_validate(
        binding.model_dump() if isinstance(binding, PairBinding) else binding
    )
    m = PairedMaterial.model_validate(
        material.model_dump() if isinstance(material, PairedMaterial) else material
    )
    at = _instant(at)
    if m.fact is None:
        return _missing("PAIR_FACT_MISSING", "Actual immutable LaunchFact/ResultAction is missing.")
    if m.receipt is None or m.common_material is None:
        return _missing(
            "PAIR_RECEIPT_MISSING",
            "Exact common receipt/original handler semantic material is missing.",
        )
    if m.request_current is None or m.run_current is None:
        return _missing("PAIR_CURRENT_MISSING", "Both real current pointers must be read.")
    payload = _payload(m)
    if payload is None:
        return _missing(
            "PAIR_ORIGINAL_SEMANTIC_MISSING",
            "Complete original semantic payload is required; snapshots cannot fill missing fields.",
        )
    f, r = m.fact, m.receipt
    _require(
        binding.build.product_id == binding.scope.product_id
        and binding.build.project_id == binding.scope.project_id,
        "PAIR_SCOPE_MISMATCH",
        "Server Build must belong to exact scope.",
    )
    _require(
        f.scope == binding.scope
        and (f.build_id, f.request_id, f.run_id)
        == (binding.build.id, binding.request_id, binding.run_id),
        "PAIR_SCOPE_MISMATCH",
        "Fact cannot cross any parent identity.",
    )
    _require(
        m.request_after.ref
        == FixedRef(id=binding.output_ref.id, revision=binding.output_ref.revision)
        and m.request_current == m.request_after.ref
        and m.run_current == m.run_after.ref,
        "PAIR_CURRENT_MISMATCH",
        "Origin/historical refs cannot impersonate actual Current.",
    )
    # Explicit local instant, never global/context-variable state or a shared cache.
    for row in (
        m.request_before,
        m.request_after,
        m.origin_request,
        m.run_after,
        m.run_before,
        m.projection_run,
    ):
        if row is not None:
            _row_identity_at(binding, row, at)
    _require(
        m.run_after.origin_request == m.origin_request.ref,
        "PAIR_ORIGIN_MISMATCH",
        "Run.request_version_id denotes its actual origin row.",
    )
    for row in (m.request_before, m.request_after):
        _require(
            row.snapshot.model_dump(mode="json", exclude={"revision", "status", "timeline"})
            == m.origin_request.snapshot.model_dump(
                mode="json", exclude={"revision", "status", "timeline"}
            )
            and (row.owner_id, row.visibility)
            == (m.origin_request.owner_id, m.origin_request.visibility),
            "PAIR_FIXED_SCOPE_CHANGED",
            "Origin and current Formal must preserve the same fixed accepted scope and audience.",
        )
    selected = {c.item_id for c in m.run_after.snapshot.coverage}
    sample_ids = {c.sample_id for c in m.run_after.snapshot.coverage}
    _require(
        m.run_after.snapshot.items
        == tuple(i for i in m.origin_request.snapshot.items if i.id in selected)
        and m.run_after.snapshot.samples
        == tuple(v for v in m.origin_request.snapshot.samples if v.id in sample_ids)
        and pairs(m.run_after.snapshot.coverage)
        == pairs(accepted_coverage(m.origin_request.snapshot))
        and len(pairs(m.run_after.snapshot.coverage)) == len(m.run_after.snapshot.coverage),
        "PAIR_FIXED_SCOPE_CHANGED",
        "One-Run version must preserve the complete accepted sample/item/configuration origin.",
    )
    if m.run_after.snapshot.status != "planned":
        execution = m.run_after.snapshot.execution
        _require(
            m.run_after.snapshot.actual_start is not None and execution is not None,
            "PAIR_EXECUTION_MISSING",
            "Performed Run needs its saved Actual start and execution.",
        )
        _require(
            (execution.executor_id, execution.environment, execution.conditions)
            == (
                m.run_after.plan.executor_id,
                m.run_after.plan.environment,
                m.run_after.plan.conditions,
            ),
            "PAIR_FIXED_SCOPE_CHANGED",
            "Actual execution cannot replace the fixed plan executor/environment/conditions.",
        )
    _require(
        f.request_before == m.request_before.ref and f.next_request == m.request_after.ref,
        "PAIR_FACT_MISMATCH",
        "Fact request before/next refs must be exact.",
    )
    request_changed = _request_transition(m.request_before, m.request_after, f.operation)
    run_changed = _run_transition(m, f.operation)
    _require(
        f.created_at <= at,
        "PAIR_TIME_MISMATCH",
        "Fact must already exist at the server check instant.",
    )
    common = m.common_material
    domain_hash = digest(
        {"operation": f.operation, "actor": str(f.actor_id), "payload": f.input_snapshot}
    )
    _require(
        domain_hash == f.domain_intent,
        "PAIR_DOMAIN_INTENT_MISMATCH",
        "Domain fact intent must match its own original semantic payload.",
    )
    _require(
        common.operation == f.operation
        and common.product == binding.scope.product_id
        and common.named_actor == f.actor_id
        and common.payload == f.input_snapshot,
        "PAIR_COMMON_MATERIAL_MISMATCH",
        "Real common semantic material must bind the same action.",
    )
    expected_handler = (
        "verification_launch" if isinstance(f, LaunchFact) else "verification_results"
    )
    _require(
        common.handler == expected_handler
        and r.common_intent == digest(common.model_dump(mode="json", exclude={"handler"})),
        "PAIR_COMMON_INTENT_MISMATCH",
        "Common intent is checked using its own exact handler material.",
    )
    if request_changed:
        _require(
            m.request_after.operation == f.operation
            and m.request_after.authority_actor_id == f.actor_id
            and m.request_after.domain_intent == domain_hash,
            "PAIR_WRITER_MISMATCH",
            "New Formal authority/intent must bind actual action writer.",
        )
    if run_changed:
        _require(
            m.run_after.operation == f.operation
            and m.run_after.writer_id == f.actor_id
            and m.run_after.domain_intent == domain_hash,
            "PAIR_WRITER_MISMATCH",
            "New Run writer/intent must bind actual action.",
        )
    if isinstance(f, LaunchFact):
        _require(
            f.run == m.run_after.ref and f.snapshot_sha256 == digest(_json(f.kernel_event)),
            "PAIR_FACT_MISMATCH",
            "Launch event and fixed Run cannot be substituted.",
        )
        logical_subject = (
            binding.request_id if f.operation == "verification.schedule.promise" else binding.run_id
        )
        _require(
            f.kernel_event.scope == binding.scope
            and f.kernel_event.name == EVENTS[f.operation]
            and f.kernel_event.subject_id == logical_subject
            and f.kernel_event.revision
            == (
                m.request_after.ref.revision
                if logical_subject == binding.request_id
                else m.run_after.ref.revision
            ),
            "PAIR_EVENT_MISMATCH",
            "Launch kernel event must bind its real logical subject.",
        )
        _require(
            f.kernel_event.at.actor_id == f.actor_id
            and f.kernel_event.at.received_at <= f.created_at
            and pairs(f.kernel_event.coverage) == pairs(m.run_after.snapshot.coverage),
            "PAIR_EVENT_MISMATCH",
            "Actual Launch event must bind actor, recorded clock and exact coverage.",
        )
    else:
        if m.projection is None or m.projection_run is None:
            return _missing(
                "PAIR_PROJECTION_MISSING",
                "Result action requires exact projection and projected Run.",
            )
        p = m.projection
        _require(
            f.run_before == m.run_before.ref
            and f.next_run == m.run_after.ref
            and f.projection == p.ref,
            "PAIR_FACT_MISMATCH",
            "Result action before/next/projection refs must be exact.",
        )
        _require(
            p.scope == binding.scope
            and (p.build_id, p.request_id, p.run_id)
            == (binding.build.id, binding.request_id, binding.run_id)
            and p.run == m.projection_run.ref
            and p.run_sha256 == m.projection_run.snapshot_sha256
            and p.result == m.run_after.snapshot.result
            and p.computed_results == m.run_after.snapshot.computed_results,
            "PAIR_PROJECTION_MISMATCH",
            "Result projection must preserve actual computed results.",
        )
        _require(
            m.projection_run.snapshot.measurements == m.run_after.snapshot.measurements
            and m.projection_run.snapshot.computed_results == p.computed_results
            and (f.operation != "test.results.import" or p.run == m.run_after.ref),
            "PAIR_RAW_VALUE_CHANGED",
            "Projection basis must bind immutable raw values, not professional text.",
        )
        _require(
            (f.operation != "test.run.review" or m.projection_run == m.run_before)
            and (
                f.operation != "test.disposition.decide"
                or (m.run_before.previous == p.run and m.run_before.operation == "test.run.review")
            ),
            "PAIR_PROJECTION_MISMATCH",
            "Projected Run must be the real final return or direct predecessor of named review.",
        )
    _payload_binding(binding, m, payload, at)
    subject = m.request_after if f.operation == "verification.schedule.promise" else m.run_after
    subject_type = (
        "verification_request" if f.operation == "verification.schedule.promise" else "test_run"
    )
    _require(
        (
            r.tenant_id,
            r.product_id,
            r.operation,
            r.subject_type,
            r.subject,
            r.actor_id,
            r.requester_id,
            r.visibility,
            r.run_id,
        )
        == (
            binding.scope.tenant_id,
            binding.scope.product_id,
            f.operation,
            subject_type,
            subject.ref,
            f.actor_id,
            f.actor_id,
            subject.visibility,
            None,
        )
        and r.result
        == ReceiptResult(
            id=subject.ref.id, revision=subject.ref.revision, status=subject.snapshot.status
        )
        and f.visibility == subject.visibility
        and r.created_at <= at,
        "PAIR_RECEIPT_MISMATCH",
        "Common receipt must belong to actual named writer and immutable subject.",
    )
    if f.operation == "test.run.plan":
        clock = f.kernel_event.at
        _require(
            clock.source
            == SourceRef(id=r.command_id, revision=1, kind="command", position="receipt")
            and clock.original_timezone == "UTC"
            and clock.effective_at is None
            and clock.actor_id == f.actor_id == r.actor_id
            and clock.occurred_at == clock.received_at,
            "PAIR_EVENT_MISMATCH",
            "Plan clock must be the exact kernel command receipt fact.",
        )
    _require(
        f.created_at <= r.created_at and subject.created_at <= r.created_at,
        "PAIR_TIME_MISMATCH",
        "Common receipt cannot predate its recorded target/fact.",
    )
    _require(
        len(m.audits) == len(m.outbox) == 1,
        "PAIR_ATOM_MISSING",
        "Exactly one audit and one outbox must accompany receipt.",
    )
    a, e = m.audits[0], m.outbox[0]
    _require(
        (a.tenant_id, a.receipt_id, a.actor_id, a.operation)
        == (r.tenant_id, r.id, r.actor_id, r.operation)
        and (
            e.tenant_id,
            e.receipt_id,
            e.actor_id,
            e.subject,
            e.type,
            e.correlation_id,
            e.schema_version,
        )
        == (r.tenant_id, r.id, r.actor_id, r.subject, EVENTS[r.operation], r.command_id, 1),
        "PAIR_ATOM_MISMATCH",
        "Receipt/audit/outbox must form the exact common atom.",
    )
    groups = [
        row.reads
        for row in (
            m.request_before,
            m.request_after,
            m.origin_request,
            m.run_after,
            m.run_before,
            m.projection,
            m.projection_run,
            f,
        )
        if row is not None
    ]
    reads = _merged_reads(groups)
    needed = _merged_reads([_artifact_refs(_json(m))])
    _require(
        set(needed) <= set(reads),
        "MISSING_REQUIRED_EVIDENCE",
        "All fixed nested Artifact and exact source versions must be in the complete read set.",
    )
    return PairInspection(
        proof=StructuralPairProof(
            binding=binding,
            current_formal=m.request_after.ref,
            current_run=m.run_after.ref,
            origin_formal=m.origin_request.ref,
            fact=f.ref,
            fact_kind=f.kind,
            receipt_id=r.id,
            command_id=r.command_id,
            operation=f.operation,
            owner_id=m.request_after.owner_id,
            run_owner_id=m.run_after.owner_id,
            writer_id=f.actor_id,
            meaning="planned" if m.run_after.snapshot.status == "planned" else "performed",
            required_source_read_set=reads,
            material_sha256=digest(_json(m)),
        )
    )


def _row_identity_at(binding, row, at):
    # Kept as an explicit parameter so concurrent verifications share no clock state.
    _require(row.created_at <= at, "PAIR_TIME_MISMATCH", "A saved row cannot be future material.")
    snap = row.snapshot
    _require(
        snap.scope == binding.scope and snap.build == binding.build,
        "PAIR_SCOPE_MISMATCH",
        "Exact scope and fixed Build must match.",
    )
    _require(
        snap.revision == row.ref.revision and digest(_json(snap)) == row.snapshot_sha256,
        "PAIR_SNAPSHOT_MISMATCH",
        "Saved snapshot/revision must match.",
    )
    if isinstance(row, FormalRow):
        _require(
            snap.id == binding.request_id and snap.purpose == binding.purpose,
            "PAIR_SCOPE_MISMATCH",
            "Formal logical identity/purpose must match.",
        )
    else:
        _run_shape(row)
        _require(
            snap.id == binding.run_id
            and snap.request_id == binding.request_id
            and snap.request_revision == row.origin_request.revision
            and digest(_json(row.plan)) == row.plan_sha256,
            "PAIR_SCOPE_MISMATCH",
            "Run origin/plan must be fixed.",
        )


@dataclass(frozen=True)
class ServerPairRead:
    binding: PairBinding
    material: PairedMaterial


GateKind = Literal[
    "acl",
    "sources",
    "professional",
    "original_bytes",
    "retained",
    "semantic",
    "numerical_rules",
    "runtime",
]


@dataclass(frozen=True)
class GateStamp:
    kind: GateKind
    basis_sha256: str


@dataclass(frozen=True)
class HostGateProof:
    """Opaque same-UOW evidence issued by the actual server reader, never JSON."""

    issued_by: object
    session: object
    transaction: object
    nested_transaction: object
    caller_id: UUID
    scope: Scope
    structural_sha256: str
    stamps: tuple[GateStamp, ...]
    checked_at: datetime
    valid_until: datetime | None


@dataclass(frozen=True)
class PairedReadOutcome:
    structure: StructuralPairProof | None
    host_gate: HostGateProof | None
    missing: tuple[Missing, ...]


class PairedOutputReader(Protocol):
    """Real host installs this object; a client cannot supply reader or gate stamps."""

    def read(self, s, ctx, product_id, output_ref, *, at, write=False) -> ServerPairRead | None: ...
    def refresh(
        self, s, ctx, product_id, previous, *, at, write=False
    ) -> ServerPairRead | None: ...
    def attest(
        self, s, ctx, product_id, read, structure, *, at, write=False
    ) -> HostGateProof | None: ...


def _validate_gate(reader, s, ctx, read, structure, gate, started_at, at):
    required = {"acl", "sources", "professional", "original_bytes", "semantic", "runtime"}
    if structure.meaning == "performed":
        required.add("retained")
    if structure.fact_kind == "result":
        required.add("numerical_rules")
    if not isinstance(gate, HostGateProof):
        return Missing(
            code="LIVE_HOST_GATE_MISSING",
            detail="Actual server gate callback is not configured or incomplete.",
        )
    if not all(isinstance(stamp, GateStamp) for stamp in gate.stamps):
        return Missing(
            code="LIVE_HOST_GATE_UNBOUND", detail="Actual server-issued gate stamps are required."
        )
    kinds = [stamp.kind for stamp in gate.stamps]
    try:
        transaction, nested = s.get_transaction(), s.get_nested_transaction()
    except AttributeError:
        return Missing(
            code="CALLER_UOW_REQUIRED", detail="Real caller-owned transaction is required."
        )
    bound = (
        gate.issued_by is reader
        and gate.session is s
        and transaction is not None
        and gate.transaction is transaction
        and gate.nested_transaction is nested
        and gate.caller_id == ctx.requester_id == read.binding.caller_id
        and gate.scope == read.binding.scope
        and gate.structural_sha256 == structure.material_sha256
    )
    allowed = {
        "acl",
        "sources",
        "professional",
        "original_bytes",
        "retained",
        "semantic",
        "numerical_rules",
        "runtime",
    }
    if (
        not bound
        or len(kinds) != len(set(kinds))
        or not required <= set(kinds)
        or not set(kinds) <= allowed
    ):
        return Missing(
            code="LIVE_HOST_GATE_UNBOUND",
            detail="Live gate must bind reader/UOW/caller/scope/material and every required owner.",
        )
    if any(
        not isinstance(stamp.basis_sha256, str)
        or len(stamp.basis_sha256) != 64
        or any(c not in "0123456789abcdef" for c in stamp.basis_sha256)
        for stamp in gate.stamps
    ):
        return Missing(
            code="LIVE_HOST_GATE_UNBOUND", detail="Actual gate fingerprints are missing."
        )
    if not started_at <= _instant(gate.checked_at) <= at or (
        gate.valid_until is not None and _instant(gate.valid_until) <= at
    ):
        return Missing(
            code="LIVE_HOST_GATE_EXPIRED",
            detail="Current qualification/source gate expired during bounded reading.",
        )
    return None


def read_paired_formal_output(
    s,
    ctx,
    product_id,
    output_ref,
    *,
    at,
    reader=None,
    write=False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PairedReadOutcome:
    """No host => missing; refresh live proofs after IO, in the exact same UOW."""
    if reader is None or not all(
        callable(getattr(reader, name, None)) for name in ("read", "refresh", "attest")
    ):
        return PairedReadOutcome(
            None,
            None,
            (
                Missing(
                    code="INTEGRATION_REQUIRED",
                    detail="Paired owner reader and live refresh are not installed.",
                ),
            ),
        )
    selected = FormalRef.model_validate(
        output_ref.model_dump() if isinstance(output_ref, FormalRef) else output_ref
    )
    at = _instant(at)
    _require(
        at <= _instant(clock()), "INVALID_TIME", "A future reading cannot assert current proof."
    )
    try:
        transaction, nested = s.get_transaction(), s.get_nested_transaction()
    except AttributeError:
        transaction, nested = None, None
    if transaction is None:
        return PairedReadOutcome(
            None,
            None,
            (
                Missing(
                    code="CALLER_UOW_REQUIRED",
                    detail="Existing caller-owned transaction is required.",
                ),
            ),
        )
    read = reader.read(s, ctx, product_id, selected, at=_instant(clock()), write=write)
    previous_stamps = None
    for phase in range(2):
        _require(
            s.get_transaction() is transaction and s.get_nested_transaction() is nested,
            "CALLER_UOW_CHANGED",
            "Reader cannot commit, replace or cross caller transaction.",
        )
        if not isinstance(read, ServerPairRead):
            return PairedReadOutcome(
                None,
                None,
                (Missing(code="INTEGRATION_REQUIRED", detail="Actual owner material is missing."),),
            )
        _require(
            read.binding.scope.tenant_id == ctx.tenant_id
            and read.binding.scope.product_id == product_id
            and read.binding.caller_id == ctx.requester_id
            and read.binding.output_ref == selected,
            "PAIR_SCOPE_MISMATCH",
            "Reader cannot substitute scope/caller/selected immutable row.",
        )
        check = verify_paired_material(read.binding, read.material, at=_instant(clock()))
        if check.proof is None:
            return PairedReadOutcome(None, None, check.missing)
        started_at = _instant(clock())
        gate = reader.attest(s, ctx, product_id, read, check.proof, at=started_at, write=write)
        _require(
            s.get_transaction() is transaction and s.get_nested_transaction() is nested,
            "CALLER_UOW_CHANGED",
            "Live gate cannot replace caller transaction.",
        )
        missing = _validate_gate(
            reader, s, ctx, read, check.proof, gate, started_at, _instant(clock())
        )
        if missing:
            return PairedReadOutcome(check.proof, None, (missing,))
        stamps = tuple(sorted((v.kind, v.basis_sha256) for v in gate.stamps))
        current = (check.proof.material_sha256, stamps, gate.valid_until)
        if phase == 1:
            _require(
                current == previous_stamps,
                "SOURCE_STALE",
                "Post-IO owner/current/source/qualification/runtime facts drifted.",
            )
            return PairedReadOutcome(check.proof, gate, ())
        previous_stamps = current
        read = reader.refresh(s, ctx, product_id, read, at=_instant(clock()), write=write)
    raise AssertionError("bounded two-phase reader")
