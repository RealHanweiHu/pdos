"""Read actual retained exception decisions; no approval or historical requalification."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from pdos_next.change_implementation_owner import common_group
from pdos_next.database import require_context
from pdos_next.domain.manufacturing_trials import native_material_owner as direct
from pdos_next.domain.professional_authority.signature_watermarks import signature_current
from pdos_next.domain.release import rules as release_rules
from pdos_next.domain.release.schemas import ExceptionBasis
from pdos_next.errors import DomainError
from pdos_next.models import Receipt, now
from pdos_next.request_proof import snapshot_get, snapshot_scalar
from pdos_next.service import require_access

from .constants import DECIDE, WITHDRAW
from .models import ReleaseExceptionCurrent as Current
from .models import ReleaseExceptionDecision as Decision
from .schemas import ExceptionPlan


def _require(test, message, code="INTEGRITY_MISMATCH", status=503):
    if not test:
        raise DomainError(code, message, status)


def pointer(s, ctx, pid, series_id, *, lock=False):
    query = select(Current).where(
        Current.tenant_id == ctx.tenant_id,
        Current.category_id == ctx.category_id,
        Current.product_id == pid,
        Current.series_id == series_id,
    )
    if lock:
        return s.scalar(query.with_for_update().execution_options(populate_existing=True))
    return snapshot_scalar(s, (Current, series_id), query, scope_id=pid)


def pointer_value(value):
    return (
        None
        if value is None
        else {
            "decision": {"id": str(value.decision_id), "revision": value.decision_revision},
            "epoch": value.epoch,
            "action": value.action,
        }
    )


def retained(s, ctx, pid, identity, revision=None):
    """Fixed row plus complete original common group, in the caller's RLS scope."""
    require_access(s, ctx, pid)
    row = snapshot_get(s, Decision, identity, scope_id=pid)
    _require(
        row is not None
        and (row.tenant_id, row.category_id, row.product_id)
        == (ctx.tenant_id, ctx.category_id, pid)
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "所选例外决定不可读取。",
        "FORBIDDEN_SCOPE",
        403,
    )
    _require(
        revision is None or row.revision == revision,
        "例外决定版本已变化。",
        "VERSION_CONFLICT",
        409,
    )
    plan = ExceptionPlan.model_validate(row.body)
    _require(
        release_rules.digest(plan) == row.body_sha256
        and plan.scope.model_dump(mode="json")
        == {
            "tenant_id": str(ctx.tenant_id),
            "product_id": str(pid),
            "project_id": str(row.project_id),
        }
        and plan.category_id == row.category_id
        and plan.owner_id == row.owner_id
        and plan.visibility == row.visibility
        and plan.action == row.action
        and plan.policy_fact is not None
        and (plan.basis_package.id, plan.basis_package.revision)
        == (row.basis_package_id, row.basis_package_revision)
        and (plan.policy_fact.id, plan.policy_fact.revision)
        == (row.policy_fact_id, row.policy_fact_revision)
        and plan.discipline == row.discipline
        and plan.purpose == row.purpose
        and plan.signers == (row.actor_id,)
        and row.writer_id == row.actor_id == row.requester_id
        and plan.state == "READY"
        and row.write_tier == "T2"
        and row.shared_proof_revision > 0
        and row.proof_consumed_at <= row.created_at
        and (row.proof_expires_at is None or row.created_at < row.proof_expires_at),
        "例外决定的固定内容或原具名消费证明不完整。",
    )
    group = common_group(
        s,
        ctx,
        pid,
        row,
        operation=row.operation,
        event="release.exception_decided"
        if row.operation == DECIDE
        else "release.exception_withdrawn",
        actor=row.actor_id,
    )["receipt"]
    _require(
        group["id"] == row.receipt_id
        and group["subject_type"] == "release_exception"
        and group["command_id"] == row.command_id
        and group["request_digest"] == row.request_digest
        and group["intent_digest"] == row.intent_digest
        and row.operation in {DECIDE, WITHDRAW},
        "例外决定缺原事务共同回执。",
    )
    receipt = snapshot_get(s, Receipt, row.receipt_id, scope_id=pid)
    _require(
        receipt is not None and receipt.confirmation_id == row.shared_proof_id,
        "例外决定缺原共同确认的实际关联。",
    )
    return row, plan


def _mark(row):
    return {
        "id": str(row.id),
        "revision": row.revision,
        "sha256": row.body_sha256,
        "project_id": str(row.project_id),
        "series_id": str(row.series_id),
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "action": row.action,
    }


class ActualReleaseExceptionOwner:
    """Only actual DB rows and their current direct dependencies are consumable."""

    def __init__(self, engine):
        self.engine = engine

    def _scope(self, s, ctx, pid):
        require_context(s, ctx)
        _require(s.get_bind() is self.engine, "例外读取须使用实际owner的存储。")
        require_access(s, ctx, pid)

    def read(
        self, s, ctx, pid, refs, *, scope, config, purpose, policy_version, policy_fact, visibility
    ):
        self._scope(s, ctx, pid)
        values, objects, bases, sources, reads = [], [], [], [], []
        from pdos_next.domain.release.schemas import FixedObject, ObjectRef

        for selected in refs:
            row, plan = retained(s, ctx, pid, selected.id, selected.revision)
            _require(
                row.action == "approved",
                "发布包只能选择独立批准原决定，不能选择撤回记录。",
                "SOURCE_STALE",
                409,
            )
            _require(
                plan.scope == scope and plan.subject_config == config and plan.purpose == purpose,
                "例外不属于所选真实项目、配置和用途。",
                "FORBIDDEN_SCOPE",
                403,
            )
            _require(
                visibility == "private" or row.visibility != "private",
                "私人例外不能扩大为共享发布。",
                "FORBIDDEN_SCOPE",
                403,
            )
            actual = pointer(s, ctx, pid, row.series_id)
            _require(actual is not None, "例外Current缺失。")
            marks = direct._source_watermarks(s, ctx, pid, row.source_basis["artifact_sources"])
            current = True
            try:
                direct._watermarks_current(s, ctx, pid, marks)
            except DomainError as error:
                if error.status in {401, 403}:
                    raise
                if error.code not in {"SOURCE_STALE", "RECHECK_REQUIRED", "SOURCE_UNAVAILABLE"}:
                    raise
                current = False
            current = current and signature_current(
                s, ctx, pid, row.project_id, row.authority_snapshot
            )
            state = (
                "withdrawn"
                if actual.action == "withdrawn"
                else "current"
                if (
                    current
                    and actual.decision_id == row.id
                    and policy_version is not None
                    and plan.policy_version == policy_version
                    and plan.policy_fact == policy_fact
                    and (plan.expiry is None or now() < plan.expiry)
                )
                else "unknown"
            )
            values.append(
                ExceptionBasis(
                    decision=selected,
                    scope=plan.scope,
                    subject_config=plan.subject_config,
                    release_scope=plan.release_scope,
                    purpose=plan.purpose,
                    policy_version=plan.policy_version,
                    discipline=plan.discipline,
                    check_keys=plan.check_keys,
                    state=state,
                    limits=(*plan.limits, *plan.risk_controls),
                    sources=plan.sources,
                    expiry=plan.expiry,
                )
            )
            objects.append(
                FixedObject(
                    ref=ObjectRef(kind="exception", **selected.model_dump()),
                    product_id=pid,
                    project_id=row.project_id,
                    sha256=row.body_sha256,
                )
            )
            bases.append(
                {
                    "row": _mark(row),
                    "pointer": pointer_value(actual),
                    "watermarks": marks,
                    "signature": deepcopy(row.authority_snapshot),
                    "expiry": plan.expiry.isoformat() if plan.expiry else None,
                    "state": state,
                }
            )
            sources.extend(plan.sources)
            reads.extend(plan.required_source_read_set)
        return tuple(values), tuple(objects), tuple(bases), tuple(sources), tuple(reads)

    def current(self, s, ctx, pid, bases):
        self._scope(s, ctx, pid)
        for basis in bases:
            identity = UUID(basis["row"]["id"])
            row = snapshot_get(s, Decision, identity, scope_id=pid)
            _require(
                row is not None and _mark(row) == basis["row"],
                "固定例外已变化。",
                "SOURCE_STALE",
                409,
            )
            _require(
                row.visibility != "private" or row.owner_id == ctx.requester_id,
                "固定例外当前不可读取。",
                "FORBIDDEN_SCOPE",
                403,
            )
            _require(
                pointer_value(pointer(s, ctx, pid, row.series_id)) == basis["pointer"],
                "例外已撤回或当前水位变化。",
                "RECHECK_REQUIRED",
                409,
            )
            direct._watermarks_current(s, ctx, pid, basis["watermarks"])
            _require(
                signature_current(s, ctx, pid, row.project_id, basis["signature"]),
                "例外已保存签署水位需复核。",
                "RECHECK_REQUIRED",
                409,
            )
            if basis["expiry"] is not None and basis["state"] == "current":
                from datetime import datetime

                _require(
                    now() < datetime.fromisoformat(basis["expiry"]),
                    "例外已过期。",
                    "RECHECK_REQUIRED",
                    409,
                )
        return True
