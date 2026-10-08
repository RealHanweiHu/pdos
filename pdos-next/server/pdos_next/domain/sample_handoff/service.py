"""Physical ready/hold history in the host command transaction.

No second sample identity, reservation, test consumption, quality acceptance or commit.
Current readers are checked independently of the original qualified fact recorder.
"""

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

# Bootstrap the host's registered metadata before importing individual child models.
# isort: off
from pdos_next.models import Artifact, OriginalSecurity, now
# isort: on

from pdos_next.domain.build_execution.models import SampleUnit
from pdos_next.domain.build_execution.service import _lot_context, sample_view
from pdos_next.domain.build_start.models import BuildStart
from pdos_next.domain.build_start.service import _row as execution_row
from pdos_next.domain.build_start.service import execution_projection
from pdos_next.domain.configurations.service import _merge_reads
from pdos_next.domain.professional_authority.service import assess, recheck_snapshot
from pdos_next.domain.supply_execution.service import (
    _build,
    _human,
    _read_evidence,
    _sources,
)
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest

from .models import SampleReadinessCurrent, SampleReadinessFact
from .rules import availability, require_manufacturing, validate_event, validate_time
from .schemas import SampleReadinessPayload, SampleRef

OPERATION = "build.sample.readiness.record"
EFFECT = (
    "记录具名实物可交样或hold事实及发生/接收时钟；"
    "不改样件身份，不替代品质接收、方法认可、预约或测试消耗。"
)


def _json(value):
    return json.loads(
        json.dumps(
            value,
            ensure_ascii=False,
            default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v),
        )
    )


def semantic(payload):
    raw = payload.model_dump(mode="json")
    raw.pop("confirmation_token", None)
    raw["sources"].sort(
        key=lambda ref: (ref["artifact_id"], ref["expected_revision"], ref["line"], ref["quote"])
    )
    return raw


def _visible(row, ctx):
    return row.visibility == "product" or row.owner_id == ctx.requester_id


class ReadContext:
    """Explicit one-GET memo; commands and other sessions/transactions cannot reuse it."""

    def __init__(self, s, ctx, product_id):
        self.session = s
        self.transaction = s.get_transaction()
        self.scope = self._scope(ctx, product_id)
        self.projections = {}
        if self.transaction is None:
            raise DomainError("INVALID_READ_CONTEXT", "读取上下文须限于当前GET事务。")

    @staticmethod
    def _scope(ctx, product_id):
        return (ctx.tenant_id, product_id, ctx.actor_id, ctx.requester_id, ctx.run_id)

    def check(self, s, ctx, product_id, *, write=False):
        if (
            write
            or s is not self.session
            or s.get_transaction() is not self.transaction
            or self._scope(ctx, product_id) != self.scope
            or s.new
            or s.dirty
            or s.deleted
        ):
            raise DomainError("INVALID_READ_CONTEXT", "读取缓存不能跨事务、身份、产品或写入流程。")

    @staticmethod
    def _runtime(s):
        engine = s.get_bind()
        values = []
        for name in ("_pdos_professional_issuers", "_pdos_operational_issuers"):
            values.append(
                tuple(
                    sorted(
                        (
                            key,
                            id(issuer),
                            getattr(issuer, "epoch", None),
                            getattr(issuer, "version", None),
                        )
                        for key, issuer in getattr(engine, name, {}).items()
                    )
                )
            )
        epochs = tuple(
            tuple(sorted(getattr(engine, name, {}).items()))
            for name in ("_pdos_professional_issuer_epochs", "_pdos_operational_issuer_epochs")
        )
        return (
            getattr(engine, "_pdos_professional_synthetic", False),
            getattr(engine, "_pdos_operational_synthetic", False),
            epochs,
            *values,
        )

    @staticmethod
    def _deadline(value, at):
        boundaries = []
        expired = False

        def visit(item):
            nonlocal expired
            if isinstance(item, dict):
                for key, child in item.items():
                    if key in {
                        "valid_from",
                        "valid_until",
                        "expires_at",
                        "window_start",
                        "window_end",
                        "start",
                        "finish",
                    } and isinstance(child, str):
                        try:
                            bound = datetime.fromisoformat(child.replace("Z", "+00:00"))
                            if bound.tzinfo:
                                if (
                                    key in {"valid_until", "expires_at", "window_end", "finish"}
                                    and bound <= at
                                ):
                                    expired = True
                                elif bound > at:
                                    boundaries.append(bound)
                        except ValueError:
                            pass
                    visit(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)

        visit(value)
        return at if expired or not boundaries else min(boundaries)

    def projection(self, s, ctx, product_id, start, build_id):
        self.check(s, ctx, product_id)
        key = (build_id, start.id, start.snapshot_sha256, start.owner_id)
        stamp, at = self._runtime(s), now()
        saved = self.projections.get(key)
        if saved and saved[0] == stamp and at < saved[1]:
            if isinstance(saved[2], tuple):
                raise DomainError(*saved[2])
            return deepcopy(saved[2])
        maker = Context(ctx.tenant_id, start.owner_id, start.owner_id)
        try:
            value = execution_projection(s, maker, product_id, build_id)
        except DomainError as error:
            # Reusing a failure cannot grant access; its memo lives only in this GET.
            from datetime import timedelta

            self.projections[key] = (
                stamp,
                at + timedelta(seconds=1),
                (error.code, error.message, error.status),
            )
            raise
        self.projections[key] = (stamp, self._deadline(value, now()), deepcopy(value))
        return value


def _chain(s, ctx, product_id, sample_id, *, write=False):
    _human(s, ctx, product_id, write=write)
    identity = s.scalar(
        select(SampleUnit).where(
            SampleUnit.tenant_id == ctx.tenant_id,
            SampleUnit.product_id == product_id,
            SampleUnit.id == sample_id,
        )
    )
    if identity is None or not _visible(identity, ctx):
        raise DomainError("FORBIDDEN_SCOPE", "样件不在当前可见产品范围。", 403)
    # Product is the common serialization gate. Immutable Build/Sample rows have
    # no UPDATE privilege and must never be SELECT FOR UPDATE'd as mutable rows.
    # One complete existing authority chain replaces three identical getter passes.
    sample = identity
    value = _lot_context(s, ctx, product_id, sample.lot_id)
    lot, actual, build = value["lot"], value["actual_row"], value["build"]
    if (
        sample.actual_configuration_id != lot.actual_configuration_id
        or lot.actual_configuration_id != actual.id
        or (sample.project_id, lot.project_id, actual.project_id) != (build.project_id,) * 3
        or (sample.build_id, lot.build_id, actual.build_id) != (build.id,) * 3
        or lot.actual_configuration_revision != actual.revision
        or sample.build_revision != build.revision
    ):
        raise DomainError(
            "SAMPLE_CHAIN_MISMATCH", "样件、实际批次、实际配置和轮次的固定范围不能一致核对。"
        )
    reads = _merge_reads(
        sample.required_source_read_set,
        lot.required_source_read_set,
        actual.required_source_read_set,
        value["reads"],
    )
    source_status = _read_evidence(
        s,
        ctx,
        product_id,
        SimpleNamespace(required_source_read_set=reads, visibility=sample.visibility),
    )
    view = sample_view(s, ctx, product_id, sample, value)
    view["source_status"] = source_status
    return {
        "sample": sample,
        "lot": lot,
        "actual": actual,
        "build": build,
        "sample_view": view,
        "reads": reads,
    }


def _physical(chain):
    sample, lot, actual, build = (chain[key] for key in ("sample", "lot", "actual", "build"))
    return {
        "sample": {
            "id": str(sample.id),
            "revision": sample.revision,
            "label": sample.label,
            "lot_id": str(sample.lot_id),
            "actual_configuration_id": str(sample.actual_configuration_id),
            **{
                key: _json(getattr(sample, key))
                for key in (
                    "operation_key",
                    "cavity",
                    "custodian_id",
                    "custodian_label",
                    "location",
                    "destination",
                )
            },
        },
        "lot": {
            "id": str(lot.id),
            "revision": lot.revision,
            "occurred_at": lot.occurred_at.isoformat(),
            "received_at": lot.received_at.isoformat(),
            "nature": lot.observation_nature,
        },
        "actual_configuration": {
            "id": str(actual.id),
            "revision": actual.revision,
            "actual_engineering_configuration_id": str(actual.actual_engineering_configuration_id),
            "actual_engineering_revision": actual.actual_engineering_revision,
            "actual_manufacturing_configuration_id": str(
                actual.actual_manufacturing_configuration_id
            ),
            "actual_manufacturing_revision": actual.actual_manufacturing_revision,
            "observed_at": actual.observed_at.isoformat(),
        },
        "build": {
            "id": str(build.id),
            "revision": build.revision,
            "project_id": str(build.project_id),
        },
    }


def _start_context(s, ctx, product_id, chain, *, read_context=None, retained_at=None):
    build = chain["build"]
    start = s.scalar(
        select(BuildStart).where(
            BuildStart.tenant_id == ctx.tenant_id,
            BuildStart.product_id == product_id,
            BuildStart.build_id == build.id,
        )
    )
    if start is None:
        raise DomainError("BUILD_NOT_STARTED", "该轮次尚无真实开工事实，不能记录可交样。")
    if not _visible(start, ctx):
        raise DomainError("SOURCE_UNAVAILABLE", "当前开工事实不在可见范围。", 403)
    start = execution_row(s, ctx, product_id, BuildStart, start.id)
    # The original Start signer's authority determines execution qualification.
    # A quality reader does not have to impersonate a current manufacturing actor.
    if read_context is None:
        maker = Context(ctx.tenant_id, start.owner_id, start.owner_id)
        projection = execution_projection(s, maker, product_id, build.id, retained_at=retained_at)
    else:
        projection = read_context.projection(s, ctx, product_id, start, build.id)
    if (
        not projection
        or projection.get("execution_status") != "executing"
        or projection.get("execution_qualification") != "limited_current"
        or projection.get("stop_required") is True
    ):
        raise DomainError(
            "BUILD_EXECUTION_NOT_CURRENT",
            "开工范围、操作事实或具名批准已失效，须停工重核，不能记录可交样。",
        )
    projection = deepcopy(projection)
    projection["required_source_read_set"] = _merge_reads(
        start.required_source_read_set, projection.get("required_source_read_set", [])
    )
    _sources(s, ctx, product_id, projection["required_source_read_set"])
    return start, projection


def _evidence(s, ctx, product_id, reads, references=()):
    refs, private = _sources(s, ctx, product_id, reads, references)
    # A consumer's Grant timeout controls access, not the physical fact identity.
    source_refs = []
    for key in sorted(refs):
        value = refs[key].model_dump(mode="json")
        value.pop("valid_until", None)
        source_refs.append(value)
    security = []
    for read in reads:
        source = s.get(Artifact, UUID(read["artifact_id"]))
        security.append(
            {
                "artifact_id": str(source.id),
                "revision": source.revision,
                "visibility": source.visibility,
                "owner_id": str(source.owner_id),
                "original_id": str(source.original_id) if source.original_id else None,
            }
        )
        if source.original_id is not None:
            guard = s.scalar(
                select(OriginalSecurity).where(
                    OriginalSecurity.tenant_id == ctx.tenant_id,
                    OriginalSecurity.product_id == product_id,
                    OriginalSecurity.original_id == source.original_id,
                )
            )
            security.append(
                {
                    "original_id": str(source.original_id),
                    "security_epoch": guard.epoch if guard else None,
                    "source_state": guard.source_state if guard else None,
                    "disposition": guard.disposition if guard else None,
                }
            )
    return {"refs": source_refs, "security": security}, private


def _current(s, ctx, product_id, sample_id, *, lock=False):
    query = select(SampleReadinessCurrent).where(
        SampleReadinessCurrent.tenant_id == ctx.tenant_id,
        SampleReadinessCurrent.product_id == product_id,
        SampleReadinessCurrent.sample_id == sample_id,
    )
    pointer = s.scalar(query.with_for_update() if lock else query)
    if pointer is None:
        return None, None
    row = s.get(SampleReadinessFact, pointer.readiness_id)
    if row is None or (
        row.tenant_id,
        row.product_id,
        row.project_id,
        row.build_id,
        row.sample_id,
        row.revision,
    ) != (
        ctx.tenant_id,
        product_id,
        pointer.project_id,
        pointer.build_id,
        sample_id,
        pointer.readiness_revision,
    ):
        raise DomainError(
            "SAMPLE_READINESS_INTEGRITY_UNKNOWN", "实物状态当前指针与固定范围不一致。"
        )
    _integrity(row)
    return pointer, row


def _material(row):
    return {
        key: _json(getattr(row, key))
        for key in (
            "id",
            "product_id",
            "project_id",
            "build_id",
            "build_revision",
            "sample_id",
            "sample_revision",
            "lot_id",
            "lot_revision",
            "actual_configuration_id",
            "actual_configuration_revision",
            "revision",
            "previous_readiness_id",
            "previous_revision",
            "owner_id",
            "visibility",
            "status",
            "purpose",
            "occurred_at",
            "occurred_timezone",
            "received_at",
            "nature",
            "event_source",
            "sources",
            "required_source_read_set",
            "fixed_snapshot",
            "authority_snapshot",
            "source_basis",
            "intent_digest",
            "reason",
        )
    }


def _integrity(row):
    if row.snapshot_sha256 != digest(_material(row)):
        raise DomainError("SAMPLE_READINESS_INTEGRITY_UNKNOWN", "固定实物事实摘要不能核对。")


def _fact(s, ctx, product_id, identity):
    row = s.scalar(
        select(SampleReadinessFact).where(
            SampleReadinessFact.id == identity,
            SampleReadinessFact.tenant_id == ctx.tenant_id,
            SampleReadinessFact.product_id == product_id,
        )
    )
    if row is None or not _visible(row, ctx):
        raise DomainError("FORBIDDEN_SCOPE", "实物状态前版不在当前可见范围。", 403)
    _integrity(row)
    _read_evidence(s, ctx, product_id, row)
    return row


def _authority(s, ctx, product_id, chain, purpose, at, *, write=False):
    return assess(
        s, ctx, product_id, chain["build"].project_id, OPERATION, purpose, at, write=write
    )


def _inputs(s, ctx, command, product, payload, at):
    chain = _chain(s, ctx, product.id, payload.sample_id, write=True)
    if command.product_id != product.id or product.tenant_id != ctx.tenant_id:
        raise DomainError("FORBIDDEN_SCOPE", "实物状态不属于本产品。", 403)
    sample, lot, actual = (chain[key] for key in ("sample", "lot", "actual"))
    if sample.revision != payload.expected_sample_revision:
        raise DomainError("SAMPLE_VERSION_CONFLICT", "样件固定版本不一致。")
    authority = _authority(s, ctx, product.id, chain, payload.purpose, at, write=True)
    require_manufacturing(authority)
    previous = (
        _fact(s, ctx, product.id, payload.previous_readiness_id)
        if payload.previous_readiness_id
        else None
    )
    if previous and (
        previous.sample_id != sample.id or previous.revision != payload.expected_previous_revision
    ):
        raise DomainError("SAMPLE_READINESS_VERSION_CONFLICT", "前版不是本样件的固定实物状态。")
    start, execution_reads = None, []
    if payload.state == "ready":
        start, projection = _start_context(s, ctx, product.id, chain)
        execution_reads = projection["required_source_read_set"]
    validate_time(
        payload.occurred_at,
        at=at,
        actual_at=actual.observed_at,
        lot_at=lot.occurred_at,
        start_at=start.occurred_at if start else None,
    )
    references = [ref.model_dump(mode="json") for ref in payload.sources]
    event = payload.event_source.model_dump(mode="json")
    if event not in references:
        references.append(event)
    reads = _merge_reads(
        chain["reads"],
        references,
        authority["required_source_read_set"],
        execution_reads,
    )
    supplied = {str(ref.artifact_id): ref.expected_revision for ref in command.source_read_set}
    if any(supplied.get(ref["artifact_id"]) != ref["expected_revision"] for ref in reads):
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "需固定样件链、事件、具名资格及开工事实的完整来源读集。"
        )
    try:
        basis, private = _evidence(s, ctx, product.id, reads, references)
    except DomainError as error:
        if error.code == "MISSING_REQUIRED_EVIDENCE":
            raise DomainError(error.code, "实物依据必须在指定原文行精确定位。", 422) from None
        raise
    source = s.get(Artifact, payload.event_source.artifact_id)
    lines = source.content.splitlines()
    line = lines[payload.event_source.line - 1] if payload.event_source.line <= len(lines) else ""
    validate_event(
        payload,
        lot_id=lot.id,
        actual_configuration_id=actual.id,
        build_id=chain["build"].id,
        line=line,
    )
    fixed = _physical(chain)
    if start:
        fixed["build"]["start_id"] = str(start.id)
        fixed["start"] = {
            "id": str(start.id),
            "revision": start.revision,
            "sha256": start.snapshot_sha256,
            "occurred_at": start.occurred_at.isoformat(),
        }
    visibility = (
        "private"
        if private
        or any(chain[key].visibility == "private" for key in ("sample", "lot", "actual", "build"))
        or (previous and previous.visibility == "private")
        else "product"
    )
    return {
        "chain": chain,
        "previous": previous,
        "start": start,
        "authority": authority,
        "reads": reads,
        "references": references,
        "basis": basis,
        "fixed": fixed,
        "visibility": visibility,
    }


def validate(s, ctx, command, product, payload: SampleReadinessPayload, replay=None):
    # Current human, professional/source scope and clocks precede receipt replay.
    # Product and current-pointer CAS intentionally remain after common dedup.
    _inputs(s, ctx, command, product, payload, now())


def _new_write(s, ctx, command, product, payload, value):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "产品当前版本已变化，请重新读取。")
    pointer, current = _current(s, ctx, product.id, payload.sample_id, lock=True)
    if (str(current.id) if current else None, current.revision if current else 0) != (
        str(payload.previous_readiness_id) if payload.previous_readiness_id else None,
        payload.expected_previous_revision,
    ):
        raise DomainError(
            "SAMPLE_READINESS_VERSION_CONFLICT", "样件当前实物状态已变化，须基于当前固定事实续版。"
        )
    if current and not _visible(current, ctx):
        raise DomainError("FORBIDDEN_SCOPE", "当前实物状态不在可见范围。", 403)
    validate_time(
        payload.occurred_at,
        at=now(),
        actual_at=value["chain"]["actual"].observed_at,
        lot_at=value["chain"]["lot"].occurred_at,
        start_at=value["start"].occurred_at if value["start"] else None,
        previous_at=current.occurred_at if current else None,
    )
    return pointer


def _candidate(ctx, command, product, payload, value, at):
    chain, previous = value["chain"], value["previous"]
    sample, lot, actual, build = (chain[key] for key in ("sample", "lot", "actual", "build"))
    return SampleReadinessFact(
        id=uuid5(NAMESPACE_URL, f"pdos-sample-readiness:{command.command_id}"),
        tenant_id=ctx.tenant_id,
        product_id=product.id,
        project_id=build.project_id,
        build_id=build.id,
        build_revision=build.revision,
        sample_id=sample.id,
        sample_revision=sample.revision,
        lot_id=lot.id,
        lot_revision=lot.revision,
        actual_configuration_id=actual.id,
        actual_configuration_revision=actual.revision,
        revision=payload.expected_previous_revision + 1,
        previous_readiness_id=previous.id if previous else None,
        previous_revision=previous.revision if previous else None,
        owner_id=ctx.requester_id,
        visibility=value["visibility"],
        status=payload.state,
        purpose=payload.purpose,
        occurred_at=payload.occurred_at,
        occurred_timezone=payload.occurred_timezone,
        created_at=at,
        received_at=at,
        nature="synthetic"
        if value["authority"]["synthetic"] or lot.observation_nature == "synthetic"
        else "real",
        event_source=payload.event_source.model_dump(mode="json"),
        sources=value["references"],
        required_source_read_set=value["reads"],
        fixed_snapshot=value["fixed"],
        authority_snapshot=value["authority"],
        source_basis=value["basis"],
        intent_digest=digest(semantic(payload)),
        reason=payload.reason,
    )


def _view(row, *, source_status, is_current):
    value = _material(row)
    value.update(
        state=row.status,
        created_at=row.created_at.isoformat() if row.created_at else None,
        source_status=source_status,
        is_current=is_current,
        sha256=row.snapshot_sha256,
        clocks={
            "occurred_at": row.occurred_at.isoformat(),
            "received_at": row.received_at.isoformat() if row.received_at else None,
            "original_timezone": row.occurred_timezone,
        },
        sample_label=row.fixed_snapshot["sample"]["label"],
        source_ref={
            "kind": "domain",
            "id": str(row.id),
            "revision": row.revision,
            "position": "sample-readiness",
        },
        reservation=None,
        consumption=None,
        quality_accepted=False,
    )
    return value


def preview_view(s, ctx, command, product, payload):
    value = _inputs(s, ctx, command, product, payload, now())
    _new_write(s, ctx, command, product, payload, value)
    previous = value["previous"]
    row = _candidate(ctx, command, product, payload, value, None)
    after = _view(row, source_status="current", is_current=True)
    after["time_policy"] = "server_on_save"
    return {
        "operation": command.operation,
        "name": value["chain"]["sample"].label,
        "effect": EFFECT,
        "reason": payload.reason,
        "before": _view(
            previous, source_status=_read_evidence(s, ctx, product.id, previous), is_current=True
        )
        if previous
        else None,
        "after": after,
        "impact": {
            "purpose_limited": payload.state == "ready",
            "hold_blocks_all_purposes": payload.state == "hold",
            "quality_acceptance": False,
            "test_reservation": False,
            "test_consumption": False,
        },
    }


def apply(s, ctx, command, product, payload):
    at = now()
    value = _inputs(s, ctx, command, product, payload, at)
    pointer = _new_write(s, ctx, command, product, payload, value)
    row = _candidate(ctx, command, product, payload, value, at)
    row.snapshot_sha256 = digest(_material(row))
    s.add(row)
    s.flush()
    if pointer is None:
        s.add(
            SampleReadinessCurrent(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                project_id=row.project_id,
                build_id=row.build_id,
                sample_id=row.sample_id,
                readiness_id=row.id,
                readiness_revision=row.revision,
            )
        )
    else:
        pointer.readiness_id, pointer.readiness_revision = row.id, row.revision
    s.flush()
    return row, "sample_readiness_fact", row.visibility


def _aware(value):
    value = now() if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DomainError(
            "INVALID_SAMPLE_OBSERVATION_TIME", "样件可用性检查须带时区的当前时点。", 422
        )
    return value.astimezone(UTC)


def _inspect(
    s,
    ctx,
    product_id,
    sample_ref,
    purpose,
    *,
    at,
    write=False,
    chain=None,
    read_context=None,
    retained_at=None,
):
    if read_context is not None:
        read_context.check(s, ctx, product_id, write=write)
    if not isinstance(purpose, str) or not purpose.strip() or purpose != purpose.strip():
        raise DomainError("INVALID_SAMPLE_PURPOSE", "样件可用性须明确精确用途。", 422)
    reference = (
        sample_ref
        if isinstance(sample_ref, SampleRef)
        else SampleRef.model_validate(
            sample_ref.model_dump(mode="json") if hasattr(sample_ref, "model_dump") else sample_ref
        )
    )
    chain = chain or _chain(s, ctx, product_id, reference.id, write=write)
    if chain["sample"].revision != reference.revision:
        raise DomainError("SAMPLE_VERSION_CONFLICT", "样件固定版本不一致。")
    physical = _physical(chain)
    base = {
        **deepcopy(physical),
        "availability": "unknown",
        "purpose": purpose,
        "current_readiness": None,
        "reason_codes": [],
        "required_source_read_set": deepcopy(chain["reads"]),
        "source_refs": [],
        "valid_until": None,
        "synthetic": chain["lot"].observation_nature == "synthetic",
        "clocks": None,
    }
    objective = {"physical": physical, "requested_purpose": purpose}
    pointer, row = _current(s, ctx, product_id, reference.id, lock=write)
    if row is None:
        base["reason_codes"].append("SAMPLE_READINESS_UNKNOWN")
        base["facts_revision"] = digest(objective)
        return base
    if not _visible(row, ctx):
        # A private current fact cannot leak its identity/readset through public Sample.
        base["reason_codes"].append("SAMPLE_READINESS_SCOPE_UNAVAILABLE")
        base["facts_revision"] = digest({**objective, "unavailable": True})
        return base
    try:
        _read_evidence(s, ctx, product_id, row)
    except DomainError as error:
        if error.status == 403:
            base["reason_codes"].append("SAMPLE_READINESS_SCOPE_UNAVAILABLE")
            base["facts_revision"] = digest({**objective, "unavailable": True})
            return base
        raise
    base["required_source_read_set"] = _merge_reads(chain["reads"], row.required_source_read_set)
    base["source_refs"] = deepcopy(row.sources)
    base["clocks"] = {
        "occurred_at": row.occurred_at.isoformat(),
        "received_at": row.received_at.isoformat(),
        "original_timezone": row.occurred_timezone,
    }
    base["current_readiness"] = {
        "id": str(row.id),
        "revision": row.revision,
        "state": row.status,
        "purpose": row.purpose,
        "clocks": base["clocks"],
        "source_ref": {
            "kind": "domain",
            "id": str(row.id),
            "revision": row.revision,
            "position": "sample-readiness",
        },
    }
    base["synthetic"] |= row.nature == "synthetic"
    if row.fixed_snapshot.get("build", {}).get("start_id"):
        # This is the historical fixed Start identity, not a current authorization.
        base["build"]["start_id"] = row.fixed_snapshot["build"]["start_id"]
    objective.update(
        pointer={"id": str(pointer.id), "revision": pointer.readiness_revision},
        fact={"id": str(row.id), "revision": row.revision, "sha256": row.snapshot_sha256},
    )
    current, deadlines = True, []
    try:
        expected = deepcopy(row.fixed_snapshot)
        expected.pop("start", None)
        expected["build"].pop("start_id", None)
        if expected != physical:
            raise DomainError("SAMPLE_CHAIN_MISMATCH", "固定样件实物链发生变化。")
        basis, _ = _evidence(s, ctx, product_id, row.required_source_read_set, row.sources)
        objective["sources"] = basis
        if basis != row.source_basis:
            raise DomainError("SAMPLE_SOURCE_CHANGED", "实物依据的固定版本或安全epoch变化。")
        maker = Context(ctx.tenant_id, row.owner_id, row.owner_id)
        proof = recheck_snapshot(
            s,
            maker,
            product_id,
            row.project_id,
            row.authority_snapshot,
            at,
            retained=retained_at is not None,
        )
        objective["authority"] = (
            proof["assessment"]["facts_revision"] if proof.get("assessment") else None
        )
        if not proof["current"]:
            raise DomainError("SAMPLE_AUTHORITY_CHANGED", "实物签发人的当前制造资格或授权已变化。")
        require_manufacturing(proof["assessment"])
        if proof["assessment"]["valid_until"]:
            deadlines.append(datetime.fromisoformat(proof["assessment"]["valid_until"]))
        if row.status == "ready":
            start, projection = _start_context(
                s, ctx, product_id, chain, read_context=read_context, retained_at=retained_at
            )
            base["required_source_read_set"] = _merge_reads(
                base["required_source_read_set"], projection["required_source_read_set"]
            )
            execution_basis, _ = _evidence(
                s, ctx, product_id, projection["required_source_read_set"]
            )
            objective["execution"] = {
                "id": str(start.id),
                "sha256": start.snapshot_sha256,
                "qualification": projection["execution_qualification"],
                "stop_required": projection["stop_required"],
                "source_basis": execution_basis,
            }
            if row.fixed_snapshot.get("start") != {
                "id": str(start.id),
                "revision": start.revision,
                "sha256": start.snapshot_sha256,
                "occurred_at": start.occurred_at.isoformat(),
            }:
                raise DomainError("SAMPLE_START_CHANGED", "可交样事实不是本轮固定开工之后的实物。")
            validate_time(
                row.occurred_at,
                at=at,
                actual_at=chain["actual"].observed_at,
                lot_at=chain["lot"].occurred_at,
                start_at=start.occurred_at,
            )
        if row.status == "ready" and row.purpose != purpose:
            base["reason_codes"].append("SAMPLE_PURPOSE_NOT_READY")
    except DomainError as error:
        current = False
        base["reason_codes"].append(error.code)
        objective["invalid"] = error.code
    base["availability"] = availability(row.status, row.purpose, purpose, current=current)
    base["valid_until"] = min(deadlines).isoformat() if deadlines else None
    base["facts_revision"] = digest(objective)
    return base


def inspect_sample(
    s,
    ctx,
    product_id,
    sample_ref,
    purpose,
    *,
    at=None,
    write=False,
    read_context=None,
    retained_at=None,
):
    """Readonly availability port. write only takes caller-UOW locks; no reservation."""
    return _inspect(
        s,
        ctx,
        product_id,
        sample_ref,
        purpose,
        at=_aware(at),
        write=write,
        read_context=read_context,
        retained_at=retained_at,
    )


def inspect_execution(s, ctx, product_id, build_id, *, read_context=None):
    """Current consumer-visible Start proof; it never approves or mutates execution."""
    if read_context is not None:
        read_context.check(s, ctx, product_id)
    _human(s, ctx, product_id)
    build = _build(s, ctx, product_id, build_id)
    _, projection = _start_context(s, ctx, product_id, {"build": build}, read_context=read_context)
    return projection


def _caps(s, ctx, product_id, chain, purpose, current, *, read_context=None):
    at, blockers = now(), []
    authority = _authority(s, ctx, product_id, chain, purpose, at)
    cap = {
        "ready": False,
        "hold": False,
        "purpose": purpose,
        "authority": authority,
        "blockers": blockers,
        "required_source_read_set": deepcopy(chain["reads"]),
        "previous_readiness_id": None,
        "expected_previous_revision": 0,
    }
    if current is not None:
        if not _visible(current, ctx):
            blockers.append(
                {
                    "code": "SAMPLE_READINESS_SCOPE_UNAVAILABLE",
                    "detail": "当前实物状态不在可见范围。",
                }
            )
            return cap
        try:
            _read_evidence(s, ctx, product_id, current)
            cap["previous_readiness_id"], cap["expected_previous_revision"] = (
                str(current.id),
                current.revision,
            )
        except DomainError as error:
            blockers.append({"code": error.code, "detail": "当前实物事实不在可见范围。"})
            return cap
    try:
        from pdos_next.service import require_access

        require_access(s, ctx, product_id, write=True)
        require_manufacturing(authority)
        cap["required_source_read_set"] = _merge_reads(
            chain["reads"], authority["required_source_read_set"]
        )
        _sources(s, ctx, product_id, cap["required_source_read_set"])
        cap["hold"] = True
        _, projection = _start_context(s, ctx, product_id, chain, read_context=read_context)
        cap["required_source_read_set"] = _merge_reads(
            cap["required_source_read_set"], projection["required_source_read_set"]
        )
        cap["ready"] = True
    except DomainError as error:
        blockers.append({"code": error.code, "detail": error.message})
    return cap


def list_sample_handoff(s, ctx, product_id, purpose=None, build_id=None):
    _human(s, ctx, product_id)
    read_context = ReadContext(s, ctx, product_id)
    if purpose is not None and (
        not isinstance(purpose, str) or not purpose.strip() or purpose != purpose.strip()
    ):
        raise DomainError("INVALID_SAMPLE_PURPOSE", "请选择精确交样用途。", 422)
    if build_id is not None:
        build_id = UUID(str(build_id))
        _build(s, ctx, product_id, build_id)
    result = {
        "samples": [],
        "readiness_facts": [],
        "current_by_sample": {},
        "availability_by_sample": {},
        "capabilities_by_sample": {},
        "capabilities": {
            "quality_accept": False,
            "test_reservation": False,
            "test_consumption": False,
        },
    }
    query = select(SampleUnit).where(
        SampleUnit.tenant_id == ctx.tenant_id, SampleUnit.product_id == product_id
    )
    if build_id is not None:
        query = query.where(SampleUnit.build_id == build_id)
    samples = s.scalars(query.order_by(SampleUnit.created_at, SampleUnit.id)).all()
    for sample in samples:
        try:
            chain = _chain(s, ctx, product_id, sample.id)
            _, current = _current(s, ctx, product_id, sample.id)
            adopted_purpose = purpose or (
                current.purpose if current and _visible(current, ctx) else chain["build"].purpose
            )
            view = _inspect(
                s,
                ctx,
                product_id,
                {"id": sample.id, "revision": sample.revision},
                adopted_purpose,
                at=now(),
                chain=chain,
                read_context=read_context,
            )
            result["samples"].append(chain["sample_view"])
            result["availability_by_sample"][str(sample.id)] = view
            result["capabilities_by_sample"][str(sample.id)] = _caps(
                s, ctx, product_id, chain, adopted_purpose, current, read_context=read_context
            )
            if view["current_readiness"] is not None:
                result["current_by_sample"][str(sample.id)] = {
                    "readiness_id": view["current_readiness"]["id"],
                    "revision": view["current_readiness"]["revision"],
                }
            history = s.scalars(
                select(SampleReadinessFact)
                .where(
                    SampleReadinessFact.tenant_id == ctx.tenant_id,
                    SampleReadinessFact.product_id == product_id,
                    SampleReadinessFact.sample_id == sample.id,
                )
                .order_by(SampleReadinessFact.revision)
            ).all()
            for row in history:
                if _visible(row, ctx):
                    try:
                        _integrity(row)
                        source_status = _read_evidence(s, ctx, product_id, row)
                        result["readiness_facts"].append(
                            _view(
                                row,
                                source_status=source_status,
                                is_current=current is not None and current.id == row.id,
                            )
                        )
                    except DomainError as error:
                        if error.status != 403:
                            raise
        except DomainError as error:
            if error.status != 403:
                raise
    return result
