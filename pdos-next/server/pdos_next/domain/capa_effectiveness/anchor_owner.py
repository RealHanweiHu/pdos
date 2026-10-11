"""Actual configured original-failure/source entrance; no current authorization.

Business read-only, with the existing SELECT FOR UPDATE source gates retained.
It is not suitable for a PostgreSQL READ ONLY transaction. Nothing here begins,
flushes, commits, consumes a proof, configures an issuer or opens a connection.
"""

from pdos_next.database import category_for_product


# Initialize the actual registry before staged domain imports.
# ruff: noqa: I001
from copy import deepcopy
from datetime import UTC
from typing import Literal
from uuid import UUID

from pdos_next.service import Context, digest

from . import anchor as a
from . import anchor_storage as storage
from . import fact_atom_storage as guards
from pdos_next.domain.quality_execution import evidence
from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal
from pdos_next.quality_result_bridge import _runtime_stamp
from pdos_next.schemas.verification.contracts import DTO
from pydantic import AwareDatetime, ValidationError


class ActualAnchorRead(DTO):
    anchor: a.StableCapaAnchor
    origin_descriptor: storage.StoredOriginRead
    checked_at: AwareDatetime
    needs_lineage_owner: bool
    missing_owners: tuple[str, ...]
    # These describe which actual configured ports ran, not a HostGate.
    original_failure_bytes_verified: Literal[True] = True
    current_source_security_checked: Literal[True] = True
    current_evidence_authorized: Literal[False] = False
    same_uow_consumption_attested: Literal[False] = False


def _require(condition, code="SOURCE_STALE", message="原完成锚的当前真实出处无法完整核对。"):
    if not condition:
        raise DomainError(code, message, 503 if code == "INTEGRATION_REQUIRED" else 409)


def _phase(s, ctx, uow, caller, stamp, bridge, refresh):
    guards._same_uow(s, uow, ctx, caller)
    engine = s.get_bind()
    _require(
        getattr(engine, "_pdos_quality_result_bridge", None) is bridge
        and getattr(engine, "_pdos_quality_result_refresh", None) is refresh
        and _runtime_stamp(s) == stamp,
        message="本次原件读取期间运行配置、签发入口或 epoch 已改变。",
    )


def _proof(ctx, product_id, origin, failure, value, stamp):
    try:
        value = FixedQualityResult.model_validate(a.json_value(value))
        proof = a.OriginalFailureProof(failure=failure, result=value)
    except (ValidationError, TypeError, ValueError):
        raise DomainError(
            "INTEGRATION_REQUIRED", "真实失败端口缺少完整固定原值/执行证明。", 503
        ) from None
    _require(
        value.scope == origin.scope
        and value.scope.tenant_id == ctx.tenant_id
        and value.scope.product_id == product_id
        and value.purpose == origin.purpose
        and value.verified.run.id == failure.run.id
        and value.run_revision == failure.run.revision
        and value.measurement_id == failure.measurement_id
        and value.event_id is None
        and value.verified.nature == origin.nature
        and value.source_basis.get("runtime_stamp") == stamp,
        message="原失败必须绑定精确逻辑运行/版本/测量、用途、性质和真实运行配置。",
    )
    if value.visibility == "private" and value.owner_id != ctx.requester_id:
        raise DomainError("FORBIDDEN_SCOPE", "不能借原作者身份读取私有原失败。", 403)
    if origin.visibility == "category" and value.visibility == "private":
        raise DomainError("FORBIDDEN_SCOPE", "私有原失败不能扩大原调查受众。", 403)
    # Keep an independent complete byte-read proof before subsequent owner IO.
    return a.OriginalFailureProof.model_validate(proof.model_dump(mode="json"))


def _manual_sources(origin, failures):
    known = a.canonical_sources(s for f in failures for s in f.result.sources)
    # Named root/containment/hypothesis/completion references always need their
    # own exact full-line check, even when also declared by a failure bridge.
    # The old requirement has no SourceRef field; its complete text/clock/scope
    # remains in the origin. No method applicability is inferred from that text.
    return a.canonical_sources(
        (*a.issue_sources(origin.issue), *(s for s in origin.sources if s not in known))
    )


def _sources(s, ctx, product_id, origin, failures):
    reads = a.canonical_reads(
        (
            *origin.required_source_read_set,
            *(r for f in failures for r in f.result.required_source_read_set),
        )
    )
    for ref in _manual_sources(origin, failures):
        extra, _, private = evidence.check_source(s, ctx, product_id, ref)
        _require(
            a.canonical_reads((*reads, *extra)) == reads,
            "MISSING_REQUIRED_EVIDENCE",
            "人工判断出处不能缺少原完整读集中的固定版本。",
        )
        if private and origin.visibility == "category":
            raise DomainError("FORBIDDEN_SCOPE", "人工判断私有出处不能扩大调查受众。", 403)
    raw, private = evidence.source_basis(s, ctx, product_id, reads)
    raw = deepcopy(raw)  # Sparse actual JSON is never padded with typed nulls.
    basis = a.canonical_basis(raw, reads)
    if private and origin.visibility == "category":
        raise DomainError("FORBIDDEN_SCOPE", "完整原锚来源不能扩大私有受众。", 403)
    mapped = {b.id: b for b in basis}
    _require(
        all(mapped.get(b.id) == b for b in origin.source_basis),
        message="原保存来源 hash/ACL/登记/安全 epoch 已改变。",
    )
    return reads, raw, basis


def read_anchor_from_actual_owner(
    s, ctx: Context, product_id: UUID, issue_id: UUID, origin_ref: a.VersionRef
) -> ActualAnchorRead:
    """Explicit completed origin + actual configured bytes/source owners.

    The configured bridge/refresh are host dependencies, never request arguments.
    The result is not a current-professional/limited-lineage/consumption grant.
    All old raw metadata and full failure proofs are retained unchanged.
    """
    uow = guards._uow(s)
    if (
        not isinstance(ctx, Context)
        or not isinstance(product_id, UUID)
        or not isinstance(issue_id, UUID)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "原完成锚须绑定真实当前 Context 与固定身份。", 403)
    caller = digest(vars(ctx))
    engine = s.get_bind()
    bridge = getattr(engine, "_pdos_quality_result_bridge", None)
    refresh = getattr(engine, "_pdos_quality_result_refresh", None)
    _require(
        callable(bridge) and callable(refresh),
        "INTEGRATION_REQUIRED",
        "真实原失败原件与全部 IO 后重核端口尚未配置。",
    )
    stamp = _runtime_stamp(s)
    with s.no_autoflush:
        descriptor = storage.read_origin_descriptor(s, ctx, product_id, issue_id, origin_ref)
        _phase(s, ctx, uow, caller, stamp, bridge, refresh)
        origin = descriptor.origin
        proofs = []
        for failure in origin.issue.failures:
            value = bridge(
                s,
                ctx,
                product_id,
                run_id=failure.run.id,
                run_revision=failure.run.revision,
                measurement_id=failure.measurement_id,
                event_id=None,
                write=False,
            )
            proofs.append(_proof(ctx, product_id, origin, failure, value, stamp))
            _phase(s, ctx, uow, caller, stamp, bridge, refresh)
        proofs = tuple(proofs)
        reads, raw_basis, basis = _sources(s, ctx, product_id, origin, proofs)
        _phase(s, ctx, uow, caller, stamp, bridge, refresh)
        # ALL original-byte reads have finished. Every saved proof is refreshed
        # now; the later failure cannot silently revoke an earlier one via issuer
        # registry changes. Keep the original full proof instead of re-sealing it
        # with a later observational checked_at or elapsed-window field.
        for saved in proofs:
            value = refresh(s, ctx, product_id, saved.result.model_copy(deep=True), write=False)
            fresh = _proof(ctx, product_id, origin, saved.failure, value, stamp)
            _require(
                a.stable_failure_material(fresh) == a.stable_failure_material(saved),
                message="全部原件 IO 后原失败值/专业 epoch/固定执行或消费事实已变化。",
            )
            _phase(s, ctx, uow, caller, stamp, bridge, refresh)
        final_raw, private = evidence.source_basis(s, ctx, product_id, reads)
        _require(
            final_raw == raw_basis,
            message="全部失败重核后原来源闭包或安全 epoch 已变化。",
        )
        if private and origin.visibility == "category":
            raise DomainError("FORBIDDEN_SCOPE", "末端来源受众不能扩大。", 403)
        _phase(s, ctx, uow, caller, stamp, bridge, refresh)
        # Finish the pure anchor work before the final caller/source IO/clock.
        anchor = a.build_anchor(origin, proofs, source_basis=basis)
        # Independent actual origin/Current/Project/caller reads AFTER owner IO.
        # That reader samples the final Grant clock after its final DB queries.
        final_descriptor = storage.read_origin_descriptor(s, ctx, product_id, issue_id, origin_ref)
        _require(
            final_descriptor == descriptor,
            message="原完成版、Current、Project 或原共同保存组在 IO 后已改变。",
        )
        # A same-Session configured reader could alter a source after the first
        # refresh. Read the complete sparse closure once more after that reader.
        final_raw, private = evidence.source_basis(s, ctx, product_id, reads)
        _require(final_raw == raw_basis, message="末端实际来源/安全闭包已经变化。")
        if private and origin.visibility == "category":
            raise DomainError("FORBIDDEN_SCOPE", "末端来源受众不能扩大。", 403)
        final_row, final_issue = storage._version(
            s, ctx, product_id, issue_id, origin.ref, origin.scope.project_id
        )
        _require(final_issue == origin.issue, message="最后来源 IO 后原 Issue 已变化。")
        _require(
            storage._current(s, ctx, product_id, final_row) == descriptor.current
            and storage._project(s, ctx, product_id, origin.scope.project_id) == descriptor.project,
            message="最后来源 IO 后 Current/Project scope、身份或 epoch 已变化。",
        )
        person = guards._one(
            s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id
        )
        grant = guards._one(
            s,
            Grant,
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_for_product(product_id),
            Grant.principal_id == ctx.actor_id,
        )
        _phase(s, ctx, uow, caller, stamp, bridge, refresh)
        checked_at = guards.datetime.now(UTC)
        if (
            person.kind != "human"
            or person.active is not True
            or (grant.expires_at is not None and grant.expires_at <= checked_at)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "全部 IO/构造完成时本人读取授权已到期。", 403)
        _require(checked_at >= origin.created_at, message="最终实际读取时钟早于原保存事实。")
    return ActualAnchorRead(
        anchor=anchor,
        origin_descriptor=descriptor,
        checked_at=checked_at,
        needs_lineage_owner=descriptor.needs_lineage_owner,
        missing_owners=(
            "current_professional_policy_owner",
            *(("limited_issue_lineage_owner",) if descriptor.needs_lineage_owner else ()),
        ),
    )
