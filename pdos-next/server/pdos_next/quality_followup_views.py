"""Single-Issue public read adapter. The host mounts it after schema integration.

This module has no command, transaction, candidate writer or positive defaults.
An optional host option callback supplies fixed refs only; owner readers and exact
saved common Receipts still verify every returned option in this same Session.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from pdos_next.database import category_for_product
from pdos_next.domain.capa_verification import service as owners
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.domain.capa_verification.schemas import (
    FixedRef,
    FollowupBasis,
    OutputRef,
    RemediationLink,
    ResolvedOutputs,
)
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution.evidence import merge_reads, source_basis, union_sources
from pdos_next.domain.quality_execution.models import QualityIssueCurrent
from pdos_next.domain.quality_followup import service as followup
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Receipt, Run, now
from pdos_next.service import digest

LINK = "quality.capa.followup.link"
OPERATIONS = (followup.ROOT_CAUSE, followup.COMPLETE, LINK)
LIMIT = 20
SUBJECTS = {
    "definition": "definition_revision",
    "bom": "bom_revision",
    "engineering_configuration": "engineering_configuration",
    "manufacturing_configuration": "process_revision",
    "build": "build",
    "actual_configuration": "actual_configuration",
    "build_lot": "build_lot",
    "sample": "sample_allocation",
    "verification_preparation": "verification_preparation",
    "verification_request": "verification_request",
    "verification_run": "test_run",
}


@dataclass(frozen=True)
class ViewRuntime:
    # (session, current reader Context, product UUID, FollowupBasis) -> fixed OutputRefs
    output_options: object
    missing: tuple[tuple[str, str], ...] = ()


def configure_output_options(engine, callback, *, missing=()):
    if not callable(callback):
        raise TypeError("output_options must be an explicit server-owned callable")
    if not isinstance(missing, tuple) or any(
        not isinstance(item, tuple)
        or len(item) != 2
        or any(not isinstance(value, str) or not value.strip() for value in item)
        for item in missing
    ):
        raise TypeError("missing integration capabilities require explicit code/detail pairs")
    engine._pdos_quality_followup_views = ViewRuntime(callback, missing)


def _missing(code, detail):
    return {"code": code, "detail": detail}


def _writable(s, ctx, pid):
    grant = s.execute(
        select(Grant.can_write, Grant.expires_at).where(
            Grant.tenant_id == ctx.tenant_id,
            Grant.category_id == category_for_product(pid),
            Grant.principal_id == ctx.requester_id,
        )
    ).one_or_none()
    return (
        grant is not None
        and grant.can_write is True
        and (grant.expires_at is None or grant.expires_at > now())
    )


def _unexpired(value):
    if not value:
        return False
    if "operation" in value and "fact_refs" in value:
        return professional.authority_time_current(value, now())
    return policy.policy_time_current(value, now())


def _current(s, ctx, pid, issue_id):
    pointer = s.scalar(
        select(QualityIssueCurrent).where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == pid,
            QualityIssueCurrent.issue_id == issue_id,
        )
    )
    if pointer is None:
        raise DomainError("FORBIDDEN_SCOPE", "指定问题不可读取。", 403)
    row = followup._row(s, ctx, pid, issue_id, pointer.issue_revision)
    if row.id != pointer.issue_version_id or row.project_id != pointer.project_id:
        raise DomainError("INTEGRITY_MISMATCH", "当前问题指针与固定版本范围不一致。")
    # A visible old version does not imply that its current pointer/source is visible.
    source_basis(s, ctx, pid, row.required_source_read_set)
    return row, {"version_id": str(row.id), "revision": row.revision}


def _receipt(
    s,
    ctx,
    pid,
    *,
    kind,
    identity,
    revision,
    owner_id,
    visibility,
    sample_id=None,
    writer_id=None,
):
    receipt = s.scalar(
        select(Receipt).where(
            Receipt.tenant_id == ctx.tenant_id,
            Receipt.product_id == pid,
            Receipt.subject_type == kind,
            Receipt.subject_id == identity,
            Receipt.subject_revision == revision,
        )
    )
    if (
        receipt is None
        or receipt.requester_id != owner_id
        or receipt.visibility != visibility
        or receipt.result.get("id") != str(identity)
        or receipt.result.get("revision") != revision
        or (writer_id is not None and receipt.actor_id != writer_id)
        or (sample_id is not None and str(sample_id) not in receipt.result.get("sample_ids", ()))
    ):
        raise DomainError("INTEGRATION_REQUIRED", "固定输出缺少精确共同保存回执。", 503)
    if receipt.run_id is None:
        if receipt.actor_id != receipt.requester_id:
            raise DomainError("INTEGRITY_MISMATCH", "保存回执的具名本人归属不一致。")
    else:
        origin = s.get(Run, receipt.run_id)
        if origin is None or (
            origin.tenant_id,
            origin.product_id,
            origin.requester_id,
            origin.writer_id,
        ) != (ctx.tenant_id, pid, receipt.requester_id, receipt.actor_id):
            raise DomainError("INTEGRITY_MISMATCH", "输出原保存运行归属不一致。")
    return receipt


def _option(s, ctx, pid, basis, ref, *, paired_reads=None):
    reading, paired = owners._read_output(s, ctx, pid, basis, ref)
    if paired is not None:
        if paired.output != reading or paired.receipt_id != paired.pair_read.material.receipt.id:
            raise DomainError("INTEGRITY_MISMATCH", "配对输出与实际原子回执不能精确核对。")
        if paired_reads is not None:
            paired_reads.append(paired)
        return {
            "label": reading.title,
            "ref": ref.model_dump(mode="json"),
            "status": reading.status,
            "source_status": reading.source_status,
            "required_source_read_set": merge_reads(reading.required_source_read_set),
            "receipt_id": str(paired.receipt_id),
            "logical_id": str(reading.logical_id),
        }, reading
    identity, revision = ref.id, ref.revision
    requester, writer = reading.owner_id, None
    if ref.kind in {"verification_request", "verification_run"}:
        # These series retain their original owner; this immutable version may
        # have been saved by another authorized named quality professional.
        from pdos_next.domain.verification_front.models import FormalVerificationRequest
        from pdos_next.domain.verification_launch.models import VerificationRunVersion

        model = (
            FormalVerificationRequest
            if ref.kind == "verification_request"
            else VerificationRunVersion
        )
        row = owners._fixed_row(s, ctx, pid, model, ref)
        try:
            requester = UUID(row.authority_snapshot["subject_id"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise DomainError(
                "INTEGRATION_REQUIRED", "固定版本缺少本次保存人的真实专业依据。", 503
            ) from None
        writer = getattr(row, "writer_id", None)
    if ref.kind == "sample":
        # SampleUnits are children of the real allocation Receipt, not Receipt subjects.
        identity = UUID(reading.snapshot["allocation_id"])
        revision = 1
    receipt = _receipt(
        s,
        ctx,
        pid,
        kind=SUBJECTS[ref.kind],
        identity=identity,
        revision=revision,
        owner_id=requester,
        visibility=reading.visibility,
        sample_id=ref.id if ref.kind == "sample" else None,
        writer_id=writer,
    )
    value = {
        "label": reading.title,
        "ref": ref.model_dump(mode="json"),
        "status": reading.status,
        "source_status": reading.source_status,
        "required_source_read_set": merge_reads(reading.required_source_read_set),
        "receipt_id": str(receipt.id),
    }
    if reading.logical_id is not None:
        value["logical_id"] = str(reading.logical_id)
    return value, reading


def _options(s, ctx, pid, basis, runtime, *, paired_reads=None):
    refs = tuple(runtime.output_options(s, ctx, pid, basis))
    refs = tuple(OutputRef.model_validate(ref) for ref in refs)
    if len({(r.kind, r.id, r.revision, r.key) for r in refs}) != len(refs):
        raise DomainError("INTEGRITY_MISMATCH", "输出候选重复，不能猜测去重。")
    values, readings = [], []
    for ref in refs:
        option, reading = _option(s, ctx, pid, basis, ref, paired_reads=paired_reads)
        values.append(option)
        readings.append(reading)
    return values, tuple(readings)


def _saved_link(row, ctx, pid, selected):
    if (
        row.tenant_id != ctx.tenant_id
        or row.product_id != pid
        or row.issue_id != UUID(selected["issue_id"])
        or row.project_id != UUID(selected["project_id"])
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "整改回链不在指定问题可读范围。", 403)
    basis = FollowupBasis.model_validate(row.basis_snapshot)
    resolved = ResolvedOutputs.model_validate(row.output_snapshot)
    if (
        basis.basis_sha256 != owners._basis_digest(basis)
        or basis.basis_sha256 != row.basis_sha256
        or (
            basis.issue_id,
            basis.issue_version_id,
            basis.issue_revision,
            basis.capa_id,
            basis.scope.project_id,
            basis.scope.product_id,
            basis.scope.tenant_id,
        )
        != (
            row.issue_id,
            row.issue_version_id,
            row.issue_revision,
            row.capa_id,
            row.project_id,
            row.product_id,
            row.tenant_id,
        )
        or resolved.basis != basis
        or resolved.action_id != row.action_id
        or resolved.resolution_sha256 != row.resolution_sha256
        or digest(resolved.model_dump(mode="json", exclude={"resolution_sha256"}))
        != row.resolution_sha256
    ):
        raise DomainError("INTEGRITY_MISMATCH", "整改回链不可变依据或输出摘要不一致。")
    saved = RemediationLink(
        id=row.id,
        revision=row.revision,
        basis=basis,
        action_id=row.action_id,
        output_refs=tuple(o.ref for o in resolved.outputs),
        resolution_sha256=row.resolution_sha256,
        owner_id=row.owner_id,
        visibility=row.visibility,
        received_at=row.created_at,
        sources=union_sources(row.sources),
        required_source_read_set=row.required_source_read_set,
        reason=row.reason,
    )
    return saved


def _links(s, ctx, pid, selected):
    query = (
        select(RemediationLinkRecord)
        .where(
            RemediationLinkRecord.tenant_id == ctx.tenant_id,
            RemediationLinkRecord.product_id == pid,
            RemediationLinkRecord.project_id == UUID(selected["project_id"]),
            RemediationLinkRecord.issue_id == UUID(selected["issue_id"]),
            RemediationLinkRecord.issue_revision <= selected["revision"],
        )
        .order_by(RemediationLinkRecord.created_at.desc(), RemediationLinkRecord.id)
        .limit(LIMIT + 1)
    )
    rows = list(s.scalars(query))
    values, proofs, hidden = [], [], 0
    for row in rows[:LIMIT]:
        try:
            saved = _saved_link(row, ctx, pid, selected)
            receipt = _receipt(
                s,
                ctx,
                pid,
                kind="capa_remediation_link",
                identity=row.id,
                revision=row.revision,
                owner_id=row.owner_id,
                visibility=row.visibility,
            )
            if receipt.operation != LINK or receipt.actor_id != row.writer_id:
                raise DomainError("INTEGRITY_MISMATCH", "回链回执的操作或实际写入人不一致。")
            state, reasons, resolution = "current", [], None
            try:
                resolution = owners._link(
                    s, ctx, pid, saved.basis, FixedRef(id=saved.id, revision=saved.revision)
                )
            except DomainError as exc:
                if exc.status == 403:
                    raise
                state, reasons = "needs_recheck", [exc.reason]
            value = saved.model_dump(mode="json")
            value.update(source_status=state, reason_codes=reasons, receipt_id=str(receipt.id))
            values.append(value)
            if resolution is not None:
                proofs.append((saved, resolution))
        except DomainError as exc:
            if exc.status == 403:
                hidden += 1
            else:
                raise
    return values, proofs, {"has_more": len(rows) > LIMIT, "unavailable_count": hidden}


def _actions(selected, current, *, can_prepare=True):
    values = []
    for action in selected["actions"]:
        codes = [b["code"] for b in action.get("blockers", ())]
        if not current:
            codes.append("HISTORICAL_READ_ONLY")
        values.append(
            {
                "action_id": action["action_id"],
                "executor_id": action["executor_id"],
                "label": action["text"],
                "completion": deepcopy(action["completion"]),
                "can_prepare_completion": bool(
                    current and can_prepare and action["can_prepare_completion"] is True
                ),
                "can_complete": False,
                "completion_verified": None,
                "reason_codes": list(dict.fromkeys(codes)),
                "blockers": deepcopy(action.get("blockers", [])),
            }
        )
    return values


def _source_options(selected):
    return [
        {"title": option["title"], "source": deepcopy(option["source"]), "quote": option["quote"]}
        for option in selected.get("source_options", ())
    ]


def list_quality_followup(s, ctx, pid, *, issue_id, revision=None):
    """Return the frozen FollowupData envelope for exactly one readable logical Issue.

    History is read-only. Missing options/candidate bridges are explicit; no output,
    proof, completion or current pointer is generated, and no Session is committed.
    """
    if not isinstance(issue_id, UUID) or (
        revision is not None and (type(revision) is not int or revision < 1)
    ):
        raise DomainError("INVALID_PAYLOAD", "须明确一个问题UUID及可选严格正整数版本。", 422)
    followup._human(s, ctx, pid)
    current_row, pointer = _current(s, ctx, pid, issue_id)
    wanted = pointer["revision"] if revision is None else revision
    internal = followup.list_quality_followup(s, ctx, pid, issue_id=issue_id, revision=wanted)
    if len(internal["issues"]) != 1:
        raise DomainError("FORBIDDEN_SCOPE", "指定问题版本不可完整读取。", 403)
    selected = deepcopy(internal["issues"][0])
    if selected["issue_id"] != str(issue_id) or selected["revision"] != wanted:
        raise DomainError("INTEGRITY_MISMATCH", "单问题读取返回其他身份或版本。")
    current = (
        selected["id"] == pointer["version_id"] and selected["revision"] == pointer["revision"]
    )
    if selected["is_current"] is not current:
        raise DomainError("SOURCE_STALE", "读取期间问题指针已变化。")
    if selected["project_id"] != str(current_row.project_id):
        raise DomainError("INTEGRITY_MISMATCH", "同一问题系列不能切换项目范围。")
    basis = (
        FollowupBasis.model_validate(selected["followup_basis"])
        if current and selected["followup_basis"]
        else None
    )
    missing = [
        _missing("CANDIDATE_PERSISTENCE_NOT_ENABLED", "尚无受控候选保存及专业独立验证接口。")
    ]
    runtime = getattr(s.get_bind(), "_pdos_quality_followup_views", None)
    if isinstance(runtime, ViewRuntime):
        missing.extend(_missing(code, detail) for code, detail in runtime.missing)
    issue_runtime = getattr(s.get_bind(), "_pdos_quality_followup", None)
    paired_runtime = getattr(s.get_bind(), "_pdos_paired_followup_owner", None)
    paired_stamp = deepcopy(getattr(paired_runtime, "runtime", None))
    paired_reads = []
    options, readings = [], ()
    if (
        basis is not None
        and selected["source_status"] == "current"
        and isinstance(runtime, ViewRuntime)
    ):
        options, readings = _options(s, ctx, pid, basis, runtime, paired_reads=paired_reads)
    else:
        missing.append(
            _missing(
                "OUTPUT_OPTIONS_NOT_CONFIGURED"
                if not isinstance(runtime, ViewRuntime)
                else "FIXED_CAPA_BASIS_REQUIRED",
                "真实输出候选入口或当前固定CAPA依据不可用。",
            )
        )
    links, link_proofs, link_scope = _links(s, ctx, pid, selected)
    authority = None
    link_reasons = []
    reads = merge_reads(
        selected["required_source_read_set"],
        *(r.required_source_read_set for r in readings),
        *(r["required_source_read_set"] for r in links),
    )
    if basis is not None and selected["source_status"] == "current":
        authority = professional.assess(
            s, ctx, pid, basis.scope.project_id, LINK, basis.purpose, now(), write=False
        )
        reads = merge_reads(reads, authority["required_source_read_set"])
        link_reasons.extend(authority.get("reason_codes", ()))
    elif not current:
        link_reasons.append("HISTORICAL_READ_ONLY")
    else:
        link_reasons.append("FIXED_CAPA_BASIS_REQUIRED")
    callback = getattr(s.get_bind(), "_pdos_capa_link_consumed_proof", None)
    if not callable(callback):
        link_reasons.append("INTEGRATION_REQUIRED")
    if not options:
        link_reasons.append("NO_VERIFIED_OUTPUT_OPTIONS")
    evidence, _ = source_basis(s, ctx, pid, reads)
    if readings or link_proofs:
        # Fresh checks after ALL owner IO, not reuse of a previous option/link proof.
        for reading in readings:
            fresh, actual = _option(s, ctx, pid, basis, reading.ref, paired_reads=paired_reads)
            if actual != reading or fresh not in options:
                raise DomainError("SOURCE_STALE", "输出候选读取期间固定owner依据已变化。")
        for saved, proof in link_proofs:
            if (
                owners._link(
                    s, ctx, pid, saved.basis, FixedRef(id=saved.id, revision=saved.revision)
                )
                != proof
            ):
                raise DomainError("SOURCE_STALE", "回链读取期间真实输出证明已变化。")
        row = followup._row(s, ctx, pid, issue_id, wanted)
        fresh = followup._read_row(s, ctx, pid, row, current=current)
        for key in (
            "source_status",
            "followup_basis",
            "policy",
            "authority",
            "capabilities",
            "required_source_read_set",
        ):
            if fresh[key] != selected[key]:
                raise DomainError("SOURCE_STALE", "输出读取期间原失败、政策或专业依据已变化。")
    if authority is not None:
        if (
            professional.assess(
                s, ctx, pid, basis.scope.project_id, LINK, basis.purpose, now(), write=False
            )
            != authority
            or policy.assess(s, ctx, pid, basis.scope.project_id, basis.purpose)
            != selected["policy"]
        ):
            raise DomainError("SOURCE_STALE", "回链专业或风险政策读取期间已变化。")
    if current:
        for op, value in selected["authority"].items():
            if (
                op in OPERATIONS
                and professional.assess(
                    s, ctx, pid, current_row.project_id, op, selected["purpose"], now(), write=False
                )
                != value
            ):
                raise DomainError("SOURCE_STALE", "当前问题专业依据读取期间已变化。")
        if (
            selected["policy"] is not None
            and policy.assess(s, ctx, pid, current_row.project_id, selected["purpose"])
            != selected["policy"]
        ):
            raise DomainError("SOURCE_STALE", "当前问题风险政策读取期间已变化。")
    if source_basis(s, ctx, pid, reads)[0] != evidence:
        raise DomainError("SOURCE_STALE", "完整来源读取期间已变化。")
    if (
        getattr(s.get_bind(), "_pdos_quality_followup_views", None) is not runtime
        or getattr(s.get_bind(), "_pdos_capa_link_consumed_proof", None) is not callback
        or getattr(s.get_bind(), "_pdos_quality_followup", None) is not issue_runtime
        or getattr(s.get_bind(), "_pdos_paired_followup_owner", None) is not paired_runtime
        or getattr(paired_runtime, "runtime", None) != paired_stamp
    ):
        raise DomainError("SOURCE_STALE", "输出或共同证明宿主入口读取期间已变化。")
    followup._human(s, ctx, pid)
    final_row, final_pointer = _current(s, ctx, pid, issue_id)
    if final_pointer != pointer or final_row.id != current_row.id:
        raise DomainError("SOURCE_STALE", "输出读取期间当前问题版已推进。")
    writable = _writable(s, ctx, pid)
    # Every live gate remains valid after the final Current and permission IO.
    if any(
        (value.host_gate.valid_until is not None and value.host_gate.valid_until <= now())
        or any(bound <= now() for bound in value.host_gate.time_constraints)
        for value in paired_reads
    ):
        raise DomainError("SOURCE_STALE", "配对输出门栓在完整读取完成前已过期。")
    if (
        getattr(s.get_bind(), "_pdos_paired_followup_owner", None) is not paired_runtime
        or getattr(paired_runtime, "runtime", None) != paired_stamp
    ):
        raise DomainError("SOURCE_STALE", "配对输出宿主在末端读取期间已撤回或替换。")
    operations = {}
    for op in (followup.ROOT_CAUSE, followup.COMPLETE):
        value = selected["authority"].get(op)
        reasons = list(selected.get("reason_codes", ())) + list(
            (value or {}).get("reason_codes", ())
        )
        if not current:
            reasons.append("HISTORICAL_READ_ONLY")
        elif not writable:
            reasons.append("PRODUCT_WRITE_REQUIRED")
        elif selected["capabilities"].get(op) is not True:
            reasons.append("ACTION_NOT_AVAILABLE")
        if current and not _unexpired(value):
            reasons.append("CURRENT_AUTHORITY_EXPIRED_OR_UNKNOWN")
        if current and not _unexpired(selected["policy"]):
            reasons.append("CURRENT_POLICY_EXPIRED_OR_UNKNOWN")
        operations[op] = {
            "allowed": bool(
                current
                and writable
                and selected["source_status"] == "current"
                and selected["capabilities"].get(op) is True
                and _unexpired(value)
                and _unexpired(selected["policy"])
            ),
            "authority": value,
            "reason_codes": list(dict.fromkeys(reasons)),
        }
    if current and not writable:
        link_reasons.append("PRODUCT_WRITE_REQUIRED")
    if current and not _unexpired(authority):
        link_reasons.append("CURRENT_AUTHORITY_EXPIRED_OR_UNKNOWN")
    if current and not _unexpired(selected["policy"]):
        link_reasons.append("CURRENT_POLICY_EXPIRED_OR_UNKNOWN")
    operations[LINK] = {
        "allowed": bool(
            current
            and basis is not None
            and selected["source_status"] == "current"
            and options
            and callable(callback)
            and writable
            and authority is not None
            and authority.get("authorized") is True
            and authority.get("qualified") is True
            and _unexpired(authority)
            and _unexpired(selected["policy"])
        ),
        "authority": authority,
        "reason_codes": list(dict.fromkeys(link_reasons)),
    }
    return {
        "issue": selected,
        "current": pointer,
        "basis": basis.model_dump(mode="json") if basis else None,
        "operations": operations,
        "actions": _actions(
            selected, current, can_prepare=operations[followup.COMPLETE]["allowed"]
        ),
        "output_options": options,
        "links": links,
        "candidates": [],
        "required_source_read_set": reads,
        "source_options": _source_options(selected),
        "integration": {
            "effectiveness": False,
            "close": False,
            "missing": missing,
            "links": link_scope,
        },
    }
