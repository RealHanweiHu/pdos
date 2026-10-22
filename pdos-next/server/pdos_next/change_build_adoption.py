"""Read actual, limited successor-Build adoption; never infer production switching.

The caller supplies its persisted, approved Change aggregate and successful
implementation. This reader adds native execution evidence; the caller retains
the common selection, authority, proof and atomic command guards.
"""

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pdos_next.domain.build_execution import service as physical
from pdos_next.domain.build_start import service as execution
from pdos_next.domain.builds import service as builds
from pdos_next.domain.change_control.rules import digest
from pdos_next.domain.change_execution import field_bridge
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import EffectivityFact, Ref
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import source_for

DEVELOPMENT_BUILD_ADOPTION_CONDITION = (
    "仅在明确前轮的继任开发 Build 中实际采用；不代表库存、在制、其他 Build 或 ERP/MES 的切换。"
)


@dataclass(frozen=True)
class AdoptionRead:
    fact: EffectivityFact
    sources: tuple[SourceRef, ...]
    required_source_read_set: list[dict]
    source_basis: dict
    actual_refs: tuple[Ref, ...]
    verified_domain_sources: tuple[SourceRef, ...] = ()


def _require(value, code="EFFECTIVITY_OUTPUT_MISMATCH", status=409):
    if not value:
        raise DomainError(
            code, "继任开发 Build 的批准范围、实际配置或产出采用事实无法核对。", status
        )


def _scope(row, ctx, pid, request):
    _require(
        (row.tenant_id, row.product_id, row.project_id)
        == (ctx.tenant_id, pid, request.scope.project_id),
        "FORBIDDEN_SCOPE",
        403,
    )
    if row.visibility == "private":
        _require(
            row.owner_id == ctx.requester_id and request.audience == (f"private:{row.owner_id}",),
            "AUDIENCE_USE_FORBIDDEN",
            403,
        )


def _current(view):
    _require(view.get("source_status") == "current", "RECHECK_REQUIRED")


def _reads(*groups):
    result = {}
    for group in groups:
        for raw in group:
            value = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
            key, revision = str(value["artifact_id"]), value["expected_revision"]
            _require(type(revision) is int and revision > 0, "SOURCE_STALE")
            _require(key not in result or result[key] == revision, "SOURCE_STALE")
            result[key] = revision
    return [{"artifact_id": key, "expected_revision": result[key]} for key in sorted(result)]


def _artifact_sources(s, ctx, pid, references, cache):
    result = []
    for raw in references:
        value = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
        identity = UUID(str(value["artifact_id"]))
        revision, number = value["expected_revision"], value["line"]
        _require(type(revision) is int and type(number) is int and number > 0, "SOURCE_STALE")
        key = identity, revision
        if key not in cache:
            cache[key] = source_for(s, ctx, pid, identity, revision)
        lines = cache[key].content.splitlines()
        _require(number <= len(lines), "SOURCE_STALE")
        line = lines[number - 1]
        _require(value["quote"] and value["quote"] in line, "SOURCE_STALE")
        result.append(
            SourceRef(
                id=identity,
                revision=revision,
                kind="artifact",
                position=f"line:{number};quote_sha256:{hashlib.sha256(line.encode()).hexdigest()}",
            )
        )
    return result


def _fixed_row(row, view, fields):
    """Retain fixed owner material, excluding changing list counts/capabilities."""
    return {
        "id": str(row.id),
        "revision": row.revision,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        **{key: deepcopy(view[key]) for key in fields},
    }


def read_adoption(
    s,
    ctx,
    pid,
    request,
    order,
    item,
    implementation,
    *,
    fact_id: UUID,
    lot_id: UUID,
    lot_revision: int,
    sample_refs: tuple[Ref, ...],
    received_at: datetime | None = None,
) -> AdoptionRead:
    """Read one native occurrence without writes, new approvals or new expiry.

    ``received_at`` is fixed by the saved command, or the native Lot reception.
    It is never regenerated on a re-read. Native domain identities stay in
    provenance/actual_refs; only exact current artifacts become fact sources.
    """
    _require(request.scope.tenant_id == ctx.tenant_id and request.scope.product_id == pid)
    _require(order in request.orders and item in order.plan.items)
    _require(
        implementation in order.implementations
        and implementation.item_id == item.id
        and implementation.intent_id == item.intent.id
        and implementation.outcome == "succeeded",
        "IMPLEMENTATION_INCOMPLETE",
    )
    kind = {
        "new_engineering_configuration": "engineering_configuration",
        "new_manufacturing_configuration": "manufacturing_configuration",
    }.get(item.intent.kind)
    _require(kind is not None, "EFFECTIVITY_SCOPE_MISMATCH", 422)
    _require(
        item.selection.conditions == (DEVELOPMENT_BUILD_ADOPTION_CONDITION,),
        "EFFECTIVITY_SCOPE_MISMATCH",
        422,
    )
    _require(
        len(item.selection.objects) == len(implementation.outputs) == 1
        and item.selection.objects[0].kind == implementation.outputs[0].kind == kind,
        "EFFECTIVITY_SCOPE_MISMATCH",
        422,
    )
    old_config, output = item.selection.objects[0], implementation.outputs[0]
    _require(
        old_config.key is None
        and output.key is None
        and old_config.id != output.id
        and old_config in item.intent.basis
        and item.selection.units == (f"object:{old_config.identity}",),
        "EFFECTIVITY_SCOPE_MISMATCH",
        422,
    )
    old_refs = [ref for ref in item.intent.basis if ref.kind == "build"]
    _require(len(old_refs) == 1 and old_refs[0].key is None, "EFFECTIVITY_SCOPE_MISMATCH", 422)
    _require(
        sample_refs
        and all(ref.kind == "sample" and ref.key is None for ref in sample_refs)
        and len(set(sample_refs)) == len(sample_refs)
        and type(lot_revision) is int
        and lot_revision > 0,
        "EFFECTIVITY_SCOPE_MISMATCH",
        422,
    )

    feedbacks = [r for r in (*request.roots, *request.references) if r.kind == "field_feedback"]
    _require(feedbacks, "ACTION_INTENT_SCOPE_MISMATCH", 422)
    field_reads, field_sources, purposes = [], [], set()
    for ref in feedbacks:
        row, view, scope, purpose = field_bridge.get(s, ctx, pid, ref)
        _scope(row, ctx, pid, request)
        _require(scope == request.scope, "FORBIDDEN_SCOPE", 403)
        field_reads.extend(view["required_source_read_set"])
        field_sources.extend(SourceRef.model_validate(value) for value in view["sources"])
        purposes.add(purpose)
    _require(len(purposes) == 1, "FORBIDDEN_SCOPE", 403)
    purpose = next(iter(purposes))

    old_ref = old_refs[0]
    previous = builds._build(s, ctx, pid, old_ref.id)
    _scope(previous, ctx, pid, request)
    _require(previous.revision == old_ref.revision, "FIXED_REFERENCE_MISMATCH")
    _, old_engineering, old_manufacturing, old_reads = builds._linked(s, ctx, pid, previous)
    old_view = old_engineering if kind == "engineering_configuration" else old_manufacturing
    for view in (old_engineering, old_manufacturing):
        _current(view)
    _require(
        (str(old_config.id), old_config.revision) == (old_view["id"], old_view["revision"]),
        "FIXED_REFERENCE_MISMATCH",
    )
    lot, lot_view = physical.get_lot(s, ctx, pid, lot_id)
    _scope(lot, ctx, pid, request)
    _current(lot_view)
    _require(lot.id == lot_id and lot.revision == lot_revision, "FIXED_REFERENCE_MISMATCH")
    successor = builds._build(s, ctx, pid, lot.build_id)
    _scope(successor, ctx, pid, request)
    _require(
        successor.id != previous.id
        and successor.previous_build_id == previous.id
        and previous.purpose == successor.purpose == purpose,
        "EFFECTIVITY_SCOPE_MISMATCH",
        422,
    )
    _, engineering, manufacturing, new_reads = builds._linked(s, ctx, pid, successor)
    for view in (engineering, manufacturing):
        _current(view)
    new_view = engineering if kind == "engineering_configuration" else manufacturing
    _require(
        (str(output.id), output.revision) == (new_view["id"], new_view["revision"]),
        "EFFECTIVITY_OUTPUT_MISMATCH",
    )
    actual, actual_view = physical.get_actual_configuration(
        s, ctx, pid, lot.actual_configuration_id
    )
    _scope(actual, ctx, pid, request)
    _current(actual_view)
    _require(
        actual.id == lot.actual_configuration_id
        and actual.revision == lot.actual_configuration_revision
        and actual.build_id == successor.id
        and lot.build_id == successor.id
        and actual.build_revision == lot.build_revision == successor.revision
        and actual.actual_engineering_configuration_id == successor.engineering_configuration_id
        and actual.actual_manufacturing_configuration_id == successor.manufacturing_configuration_id
        and (str(actual.actual_engineering_configuration_id), actual.actual_engineering_revision)
        == (engineering["id"], engineering["revision"])
        and (
            str(actual.actual_manufacturing_configuration_id),
            actual.actual_manufacturing_revision,
        )
        == (manufacturing["id"], manufacturing["revision"])
        and not actual.differences,
        "EFFECTIVITY_OUTPUT_MISMATCH",
    )
    projection = execution.execution_projection(s, ctx, pid, successor.id)
    _require(
        isinstance(projection, dict)
        and projection.get("stop_required") is False
        and projection.get("execution_qualification") == "limited_current"
        and projection.get("execution_status") == "executing",
        "BUILD_OPERATIONAL_NOT_READY",
    )
    start = execution._start(s, ctx, pid, successor.id)
    _require(start is not None, "BUILD_OPERATIONAL_NOT_READY")
    start_view = execution._view(s, ctx, pid, start)
    _scope(start, ctx, pid, request)
    _current(start_view)
    _require(
        start.build_id == successor.id
        and start.build_revision == successor.revision
        and start.engineering_configuration_id == actual.actual_engineering_configuration_id
        and start.manufacturing_configuration_id == actual.actual_manufacturing_configuration_id,
        "EFFECTIVITY_OUTPUT_MISMATCH",
    )
    received = lot.created_at if received_at is None else received_at
    _require(
        received.tzinfo is not None
        and received.utcoffset() is not None
        and max(start.occurred_at, actual.observed_at, implementation.occurred_at)
        <= lot.occurred_at
        and lot.occurred_at <= lot.received_at <= received,
        "INVALID_EVENT_TIME",
        422,
    )
    nature = lot.observation_nature
    _require(
        nature == implementation.nature
        and isinstance(projection.get("current_result"), dict)
        and projection["current_result"].get("nature") == nature,
        "FACT_NATURE_MISMATCH",
    )
    _require(
        lot.observed_unit_count > 0 and lot.unit == successor.unit, "EFFECTIVITY_OUTPUT_MISMATCH"
    )

    samples, sample_views = [], []
    for ref in sample_refs:
        row, view = physical.get_sample(s, ctx, pid, ref.id)
        _scope(row, ctx, pid, request)
        _current(view)
        _require(
            (row.id, row.revision) == (ref.id, ref.revision)
            and row.build_id == successor.id
            and row.build_revision == successor.revision
            and row.lot_id == lot.id
            and row.actual_configuration_id == actual.id
            and view["actual_configuration_revision"] == actual.revision
            and view["observation_nature"] == nature,
            "EFFECTIVITY_OUTPUT_MISMATCH",
        )
        samples.append(row)
        sample_views.append(view)
    _require(len(samples) <= lot.observed_unit_count, "OUTPUT_QUANTITY_EXCEEDED")

    reads = _reads(
        field_reads,
        old_reads,
        new_reads,
        actual_view["required_source_read_set"],
        lot_view["required_source_read_set"],
        start_view["required_source_read_set"],
        projection["required_source_read_set"],
        *(view["required_source_read_set"] for view in sample_views),
    )
    cache = {}
    sources = []
    for view in (actual_view, lot_view, start_view, *sample_views):
        sources.extend(_artifact_sources(s, ctx, pid, view["sources"], cache))
    sources.extend(
        source
        for source in (*field_sources, *item.selection.sources, *implementation.sources)
        if source.kind == "artifact"
    )
    sources = tuple(dict.fromkeys(sources))
    _require(sources, "MISSING_REQUIRED_EVIDENCE", 422)
    reads = _reads(
        reads,
        ({"artifact_id": str(v.id), "expected_revision": v.revision} for v in sources),
    )
    for value in reads:
        artifact = source_for(s, ctx, pid, UUID(value["artifact_id"]), value["expected_revision"])
        if artifact.visibility == "private":
            _require(
                request.audience == (f"private:{artifact.owner_id}",),
                "AUDIENCE_USE_FORBIDDEN",
                403,
            )
    actual_refs = tuple(
        dict.fromkeys(
            (
                old_ref,
                Ref(kind="build", id=successor.id, revision=successor.revision),
                old_config,
                output,
                *sample_refs,
            )
        )
    )
    basis = {
        "schema_version": "pdos-native-build-adoption-read-v1",
        "scope": request.scope.model_dump(mode="json"),
        "purpose": purpose,
        "change_id": str(request.id),
        "order_id": str(order.id),
        "item_id": str(item.id),
        "selection_sha256": digest(item.selection),
        "intent_sha256": digest(item.intent),
        "implementation_id": str(implementation.id),
        "implementation_sha256": digest(implementation),
        "previous_build": old_ref.model_dump(mode="json"),
        "successor_build": actual_refs[1].model_dump(mode="json"),
        "actual_configuration": _fixed_row(
            actual,
            actual_view,
            (
                "build_id",
                "actual_engineering_configuration_id",
                "actual_engineering_revision",
                "actual_manufacturing_configuration_id",
                "actual_manufacturing_revision",
                "observed_at",
                "differences",
                "sources",
                "required_source_read_set",
            ),
        ),
        "lot": _fixed_row(
            lot,
            lot_view,
            (
                "build_id",
                "actual_configuration_id",
                "actual_configuration_revision",
                "lot_label",
                "observed_unit_count",
                "unit",
                "observation",
                "sources",
                "required_source_read_set",
            ),
        ),
        "samples": [
            _fixed_row(
                row,
                view,
                (
                    "build_id",
                    "lot_id",
                    "allocation_id",
                    "label",
                    "actual_configuration_id",
                    "actual_configuration_revision",
                    "observation_nature",
                    "sources",
                    "required_source_read_set",
                ),
            )
            for row, view in zip(samples, sample_views, strict=True)
        ],
        "start": deepcopy(start_view),
        "execution_result": deepcopy(projection["current_result"]),
    }
    fact = EffectivityFact(
        id=fact_id,
        item_id=item.id,
        intent_id=item.intent.id,
        stage="effective",
        outcome="succeeded",
        covered_units=item.selection.units,
        conditions_digest=digest(item.selection),
        occurred_at=lot.occurred_at,
        received_at=received,
        sources=sources,
        output_refs=implementation.outputs,
        system="pdos-native-build-adoption",
        external_id=f"build-lot:{lot.id}:{lot.revision}:item:{item.id}",
        nature=nature,
    )
    return AdoptionRead(fact, sources, reads, basis, actual_refs)
