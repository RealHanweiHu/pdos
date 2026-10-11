"""Explicit host-only synthetic risk publications. Production publication unconnected."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.domain.professional_authority.schemas import ApprovalBasis
from pdos_next.domain.professional_authority.service import _project
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.request_proof import batch_read, snapshot_rows
from pdos_next.service import digest, source_for

from .evidence import merge_reads, refs_from_exact, source_basis
from .models import QualityPolicyCurrent, QualityPolicyFact
from .schemas import PolicyInput

_CAPABILITY = object()


class PolicyIssuer:
    __slots__ = ("key", "version", "tenant_id", "product_id", "project_id", "epoch", "_token")

    def __init__(self, token, **values):
        if token is not _CAPABILITY:
            raise ValueError("Policy issuer must be provisioned by the trusted host")
        object.__setattr__(self, "_token", token)
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, key, value):
        raise AttributeError("Policy issuer is immutable")


def configure_local_synthetic(
    engine,
    *,
    tenant_id,
    product_id,
    project_id,
    enabled=False,
    test_marker_verified=False,
    key="local-synthetic-quality-policy",
    version="v1",
):
    if enabled is not True or test_marker_verified is not True:
        raise ValueError("Host must verify its exact test marker before enabling synthetic policy")
    if any(not isinstance(v, UUID) for v in (tenant_id, product_id, project_id)):
        raise ValueError("Policy issuer needs exact server scope UUIDs")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in (key, version)):
        raise ValueError("Policy issuer needs a stable name and version")
    epochs = dict(getattr(engine, "_pdos_quality_policy_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    issuer = PolicyIssuer(
        _CAPABILITY,
        key=key,
        version=version,
        tenant_id=tenant_id,
        product_id=product_id,
        project_id=project_id,
        epoch=epochs[key],
    )
    registry = dict(getattr(engine, "_pdos_quality_policy_issuers", {}))
    registry[key] = issuer
    engine._pdos_quality_policy_issuers, engine._pdos_quality_policy_epochs = registry, epochs
    return issuer


def disable_issuer(engine, key):
    registry = dict(getattr(engine, "_pdos_quality_policy_issuers", {}))
    registry.pop(key, None)
    epochs = dict(getattr(engine, "_pdos_quality_policy_epochs", {}))
    epochs[key] = epochs.get(key, 0) + 1
    engine._pdos_quality_policy_issuers, engine._pdos_quality_policy_epochs = registry, epochs


def _issuer(engine, issuer, tenant_id, pid, project_id):
    if (
        not isinstance(issuer, PolicyIssuer)
        or issuer._token is not _CAPABILITY
        or getattr(engine, "_pdos_quality_policy_issuers", {}).get(issuer.key) is not issuer
        or (issuer.tenant_id, issuer.product_id, issuer.project_id) != (tenant_id, pid, project_id)
    ):
        raise DomainError("TRUSTED_ISSUER_REQUIRED", "政策发布可信入口未配置或已撤销。", 403)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate publication field")
        result[key] = value
    return result


def _publication(s, ctx, data):
    expected = {
        "external_id": data.external_id,
        "purpose": data.purpose,
        "risk": data.risk,
        "independent_verification": data.independent_verification,
        "state": data.state,
        "valid_from": data.valid_from.isoformat(),
        "valid_until": data.valid_until.isoformat(),
        "approval": data.approval.model_dump(mode="json"),
    }
    for source in data.sources:
        row = source_for(s, ctx, data.product_id, source.artifact_id, source.expected_revision)
        lines = row.content.splitlines()
        if source.line > len(lines):
            continue
        try:
            actual = json.loads(lines[source.line - 1], object_pairs_hook=_pairs)
            if not isinstance(actual, dict) or set(actual) != set(expected):
                continue
            if type(actual["independent_verification"]) is not bool:
                continue
            for key in ("valid_from", "valid_until"):
                at = datetime.fromisoformat(actual[key].replace("Z", "+00:00"))
                if at.tzinfo is None:
                    raise ValueError("Policy timestamp must be aware")
                actual[key] = at.astimezone(data.valid_from.tzinfo).isoformat()
            actual["approval"] = ApprovalBasis.model_validate(actual["approval"]).model_dump(
                mode="json"
            )
            if actual == expected:
                return
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    raise DomainError("MISSING_REQUIRED_EVIDENCE", "政策风险与独立性须有逐字固定发布出处。", 422)


def _material(row):
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "tenant_id",
            "product_id",
            "project_id",
            "purpose",
            "series_id",
            "revision",
            "previous_id",
            "previous_revision",
            "owner_id",
            "visibility",
            "status",
            "risk",
            "independent_verification",
            "valid_from",
            "valid_until",
            "issuer_key",
            "issuer_version",
            "issuer_epoch",
            "nature",
            "external_id",
            "data",
            "sources",
            "required_source_read_set",
            "source_basis",
            "reason",
        )
    }


def trusted_import(s, ctx, issuer, payload):
    data = payload if isinstance(payload, PolicyInput) else PolicyInput.model_validate(payload)
    _issuer(s.get_bind(), issuer, ctx.tenant_id, data.product_id, data.project_id)
    _, project = _project(s, ctx, data.product_id, data.project_id, write=True)
    if data.approval.issued_at > now():
        raise DomainError("INVALID_EVENT_TIME", "政策发布事实不能早于未来签发时点。", 422)
    sources = refs_from_exact(s, ctx, data.product_id, data.sources)
    _publication(s, ctx, data)
    reads = merge_reads(
        [{"artifact_id": str(r.id), "expected_revision": r.revision} for r in sources]
    )
    basis, private = source_basis(s, ctx, data.product_id, reads)
    _issuer(s.get_bind(), issuer, ctx.tenant_id, data.product_id, data.project_id)
    query = select(QualityPolicyCurrent).where(
        QualityPolicyCurrent.tenant_id == ctx.tenant_id,
        QualityPolicyCurrent.product_id == data.product_id,
        QualityPolicyCurrent.project_id == data.project_id,
        QualityPolicyCurrent.purpose == data.purpose,
        QualityPolicyCurrent.issuer_key == issuer.key,
        QualityPolicyCurrent.external_id == data.external_id,
    )
    pointer = s.scalar(query.with_for_update())
    raw = data.model_dump(mode="json")
    previous = s.get(QualityPolicyFact, pointer.fact_id) if pointer else None
    # Exact historical import never rewinds Current. Current source/issuer remains required.
    replay = s.scalar(
        select(QualityPolicyFact).where(
            QualityPolicyFact.tenant_id == ctx.tenant_id,
            QualityPolicyFact.product_id == data.product_id,
            QualityPolicyFact.project_id == data.project_id,
            QualityPolicyFact.issuer_key == issuer.key,
            QualityPolicyFact.issuer_version == issuer.version,
            QualityPolicyFact.issuer_epoch == issuer.epoch,
            QualityPolicyFact.data == raw,
        )
    )
    if replay:
        if replay.source_basis != {"sources": basis, "approval": raw["approval"]}:
            raise DomainError("SOURCE_STALE", "旧政策导入出处已改变，不能假装原事实。")
        return replay
    if (previous.id if previous else None) != data.previous_id or (
        previous.revision if previous else 0
    ) != data.expected_previous_revision:
        raise DomainError("VERSION_CONFLICT", "政策前版与当前指针不一致。")
    identity = uuid4()
    row = QualityPolicyFact(
        id=identity,
        tenant_id=ctx.tenant_id,
        product_id=data.product_id,
        project_id=data.project_id,
        purpose=data.purpose,
        series_id=previous.series_id if previous else identity,
        revision=data.expected_previous_revision + 1,
        previous_id=data.previous_id,
        previous_revision=data.expected_previous_revision or None,
        owner_id=ctx.requester_id,
        visibility="private" if private or project.visibility == "private" else project.visibility,
        status=data.state,
        risk=data.risk,
        independent_verification=data.independent_verification,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
        issuer_key=issuer.key,
        issuer_version=issuer.version,
        issuer_epoch=issuer.epoch,
        nature="synthetic",
        external_id=data.external_id,
        data=raw,
        sources=[r.model_dump(mode="json") for r in sources],
        required_source_read_set=reads,
        source_basis={"sources": basis, "approval": raw["approval"]},
        fact_sha256="",
        reason=data.reason,
    )
    row.fact_sha256 = digest(_material(row))
    s.add(row)
    s.flush()
    if pointer:
        pointer.fact_id, pointer.fact_revision, pointer.epoch = (
            row.id,
            row.revision,
            pointer.epoch + 1,
        )
    else:
        s.add(
            QualityPolicyCurrent(
                tenant_id=ctx.tenant_id,
                product_id=data.product_id,
                project_id=data.project_id,
                purpose=data.purpose,
                series_id=row.series_id,
                fact_id=row.id,
                fact_revision=row.revision,
                issuer_key=issuer.key,
                external_id=data.external_id,
                epoch=1,
            )
        )
    s.flush()
    return row


def assess(s, ctx, pid, project_id, purpose):
    pointers = snapshot_rows(
        s,
        ("quality-policy-current", ctx.tenant_id, project_id, purpose),
        select(QualityPolicyCurrent)
        .where(
            QualityPolicyCurrent.tenant_id == ctx.tenant_id,
            QualityPolicyCurrent.product_id == pid,
            QualityPolicyCurrent.project_id == project_id,
            QualityPolicyCurrent.purpose == purpose,
        )
        .order_by(QualityPolicyCurrent.id),
        scope_id=pid,
    )
    if not pointers:
        raise DomainError("INTEGRATION_REQUIRED", "当前完整风险政策发布接口待接入。", 503)
    rows = (
        batch_read(s, QualityPolicyFact, (v.fact_id for v in pointers))
        if isinstance(s, Session)
        else {v.fact_id: s.get(QualityPolicyFact, v.fact_id) for v in pointers}
    )
    checked, refs, basis, reads, private = [], [], [], [], False
    for pointer in pointers:
        row = rows[pointer.fact_id]
        if (
            row is None
            or row.fact_sha256 != digest(_material(row))
            or (
                row.tenant_id,
                row.product_id,
                row.project_id,
                row.purpose,
                row.series_id,
                row.revision,
            )
            != (ctx.tenant_id, pid, project_id, purpose, pointer.series_id, pointer.fact_revision)
        ):
            raise DomainError("INTEGRITY_MISMATCH", "政策指针或完整版本摘要不一致。")
        if row.visibility == "private" and row.owner_id != ctx.requester_id:
            raise DomainError("FORBIDDEN_SCOPE", "政策私有来源不在当前办理范围。", 403)
        issuer = getattr(s.get_bind(), "_pdos_quality_policy_issuers", {}).get(row.issuer_key)
        _issuer(s.get_bind(), issuer, ctx.tenant_id, pid, project_id)
        if issuer.version != row.issuer_version or issuer.epoch != row.issuer_epoch:
            raise DomainError("RECHECK_REQUIRED", "政策签发入口版本或撤回epoch已变化。")
        if pointer.issuer_key != row.issuer_key or pointer.external_id != row.external_id:
            raise DomainError("INTEGRITY_MISMATCH", "政策指针的发布系列绑定不一致。")
        actual, is_private = source_basis(s, ctx, pid, row.required_source_read_set)
        if actual != row.source_basis["sources"]:
            raise DomainError("RECHECK_REQUIRED", "政策原文或原件安全状态已变化。")
        private |= is_private or row.visibility == "private"
        refs.extend(row.sources)
        reads.extend(row.required_source_read_set)
        basis.append(
            {
                "id": str(row.id),
                "revision": row.revision,
                "epoch": pointer.epoch,
                "sha256": row.fact_sha256,
                "issuer_epoch": issuer.epoch,
                "state": row.status,
                "valid_from": row.valid_from.isoformat(),
                "valid_until": row.valid_until.isoformat(),
            }
        )
        checked.append((row, issuer))
    # Source checks may advance the clock or revoke an in-memory issuer. Assess
    # the complete scope at one final server time, never a per-row early clock.
    at = now()
    for _row, issuer in checked:
        _issuer(s.get_bind(), issuer, ctx.tenant_id, pid, project_id)
    candidates = [
        row
        for row, _ in checked
        if row.status == "active" and row.valid_from <= at < row.valid_until
    ]
    if len(candidates) != 1:
        raise DomainError("RECHECK_REQUIRED", "风险政策未知、到期或存在冲突，不能默认低风险。")
    row = candidates[0]
    return {
        "id": str(row.id),
        "revision": row.revision,
        "risk": row.risk,
        "independent_verification": row.independent_verification,
        "nature": row.nature,
        "valid_until": None,
        "facts_revision": digest(basis),
        "sources": refs,
        "required_source_read_set": merge_reads(reads),
        "source_basis": basis,
        "private": private,
    }


def policy_time_current(value, at):
    """Check actual policy intervals without turning the capture into a TTL."""
    try:
        if not isinstance(at, datetime) or at.utcoffset() is None:
            return False
        facts = value["source_basis"]
        if not isinstance(facts, list) or not facts:
            return False
        active = []
        for fact in facts:
            start = datetime.fromisoformat(fact["valid_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(fact["valid_until"].replace("Z", "+00:00"))
            if start.utcoffset() is None or end.utcoffset() is None or end <= start:
                return False
            if fact["state"] == "active" and start <= at.astimezone(UTC) < end:
                active.append(fact)
        return len(active) == 1 and (active[0]["id"], active[0]["revision"]) == (
            value["id"],
            value["revision"],
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
