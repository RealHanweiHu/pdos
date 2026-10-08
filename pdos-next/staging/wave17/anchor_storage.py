"""Exact stored completion origin; source/failure/lineage owners remain missing.

This is not a StableCapaAnchor builder or a current-authorization host. Stored
SourceSafety fields are original declarations, never fresh byte/security proof.
"""

# Initialize the actual common registry before its domain children.
# ruff: noqa: I001
from copy import deepcopy
from datetime import UTC, datetime
import re
from typing import Literal
from uuid import UUID

from pdos_next.service import Context, digest

import anchor as a
import fact_atom_storage as guards
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_followup import service as followup
from pdos_next.domain.quality_followup.schemas import ActionsCompletePayload
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Grant, Outbox, Principal, Receipt, RequestKey
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.schemas.verification.contracts import DTO
from pydantic import AwareDatetime, ValidationError
from sqlalchemy import select

OPERATION = "quality.capa.actions.complete"
EVENT = "capa.actions_completed"


class StoredProjectScope(DTO):
    scope: a.Scope
    owner_id: UUID
    visibility: Literal["private", "product"]
    declared_scope: str


class StoredIssueCurrent(DTO):
    pointer_id: UUID
    pointer_created_at: AwareDatetime
    ref: a.VersionRef
    epoch: a.Revision
    operation: a.Text
    created_at: AwareDatetime


class StoredCompletionGroup(DTO):
    receipt_id: UUID
    command_id: UUID
    writer_id: UUID
    audit_id: UUID
    outbox_id: UUID
    proof_id: UUID
    proof_revision: a.Revision
    proof_created_at: AwareDatetime
    proof_expires_at: AwareDatetime
    receipt_created_at: AwareDatetime
    domain_intent_sha256: a.Sha256
    common_intent_sha256: a.Sha256
    original_request_digest: a.Sha256
    material_sha256: a.Sha256
    proof_snapshot_sha256: a.Sha256
    # Existing completion proof has no persisted consumed_at; do not invent one.
    same_uow_consumption_attested: Literal[False] = False


class StoredOriginRead(DTO):
    origin: a.IssueVersionEvidence
    project: StoredProjectScope
    current: StoredIssueCurrent
    completion_group: StoredCompletionGroup
    needs_lineage_owner: bool
    missing_owners: tuple[str, ...]
    current_evidence_authorized: Literal[False] = False
    source_bytes_verified: Literal[False] = False
    original_failures_verified: Literal[False] = False


def _require(value, code, detail, status=409):
    if not value:
        raise DomainError(code, detail, status)


def _now():
    # Same real clock as the version-bound fresh ACL guard, no client clock.
    return guards.datetime.now(UTC)


def _one(s, model, *where):
    return guards._one(s, model, *where)


def _project(s, ctx, pid, project_id):
    row = _one(
        s,
        Project,
        Project.tenant_id == ctx.tenant_id,
        Project.product_id == pid,
        Project.id == project_id,
    )
    _require(
        row.visibility in {"private", "product"}
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "Product Grant不能扩大实际私人Project的读取范围。",
        403,
    )
    _require(
        row.status == "active" and isinstance(row.scope, str),
        "ORIGIN_PROJECT_SCOPE_MISSING",
        "原Issue的实际Project范围声明缺失。",
        503,
    )
    return StoredProjectScope(
        scope=a.Scope(tenant_id=ctx.tenant_id, product_id=pid, project_id=project_id),
        owner_id=row.owner_id,
        visibility=row.visibility,
        declared_scope=row.scope,
    )


def _snapshot(row, ctx, pid, issue_id):
    _require(
        (row.tenant_id, row.product_id, row.issue_id) == (ctx.tenant_id, pid, issue_id),
        "FORBIDDEN_SCOPE",
        "固定Issue版本不能跨租户、产品或逻辑身份。",
        403,
    )
    _require(
        row.visibility in {"private", "product"}
        and (row.visibility != "private" or row.owner_id == ctx.requester_id),
        "FORBIDDEN_SCOPE",
        "当前本人不可读取该私有Issue版本。",
        403,
    )
    try:
        issue = Issue.model_validate(deepcopy(row.issue_snapshot))
    except (ValidationError, TypeError, ValueError):
        raise DomainError("ORIGIN_SNAPSHOT_INVALID", "保存的Issue结构无法精确核对。", 503) from None
    audience = (f"private:{row.owner_id}" if row.visibility == "private" else f"product:{pid}",)
    _require(
        (
            issue.id,
            issue.revision,
            issue.scope.tenant_id,
            issue.scope.product_id,
            issue.scope.project_id,
            issue.status,
            issue.audience,
        )
        == (issue_id, row.revision, ctx.tenant_id, pid, row.project_id, row.status, audience)
        and type(row.revision) is int
        and row.revision > 0
        and digest(issue.model_dump(mode="json")) == row.snapshot_sha256,
        "ORIGIN_SNAPSHOT_MISMATCH",
        "保存的完整Issue摘要、状态或固定范围不匹配。",
    )
    _require(
        isinstance(row.created_at, datetime)
        and row.created_at.tzinfo is not None
        and row.created_at.utcoffset() is not None
        and row.created_at <= _now(),
        "ORIGIN_CLOCK_INVALID",
        "保存的Issue时钟不能是未知、naive或未来。",
    )
    return issue


def _version(s, ctx, pid, issue_id, ref, project_id=None):
    where = [
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == pid,
        QualityIssueVersion.issue_id == issue_id,
        QualityIssueVersion.id == ref.id,
        QualityIssueVersion.revision == ref.revision,
    ]
    if project_id is not None:
        where.append(QualityIssueVersion.project_id == project_id)
    row = _one(s, QualityIssueVersion, *where)
    issue = _snapshot(row, ctx, pid, issue_id)
    _require(
        row.snapshot_sha256 == ref.snapshot_sha256,
        "ORIGIN_REF_MISMATCH",
        "显式原完成版引用未匹配完整原Issue摘要。",
    )
    return row, issue


def _previous(s, ctx, pid, row):
    _require(
        type(row.previous_revision) is int
        and row.previous_revision > 0
        and isinstance(row.previous_issue_version_id, UUID)
        and row.previous_issue_version_id != row.id
        and row.revision == row.previous_revision + 1,
        "ORIGIN_PREDECESSOR_MISSING",
        "完成版须有真实连续固定前版，不能凭空首建。",
    )
    before = _one(
        s,
        QualityIssueVersion,
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == pid,
        QualityIssueVersion.project_id == row.project_id,
        QualityIssueVersion.issue_id == row.issue_id,
        QualityIssueVersion.id == row.previous_issue_version_id,
        QualityIssueVersion.revision == row.previous_revision,
    )
    issue = _snapshot(before, ctx, pid, row.issue_id)
    _require(
        (before.owner_id, before.visibility, before.purpose)
        == (row.owner_id, row.visibility, row.purpose),
        "ORIGIN_PREDECESSOR_MISMATCH",
        "完成版不能改变固定系列责任人、范围或用途。",
    )
    return before, issue


def _complete_shape(row, issue, before, previous):
    _require(
        row.operation == OPERATION
        and issue.status == "awaiting_verification"
        and issue.merged_into is None
        and not issue.needs_recheck
        and not issue.recheck_reasons
        and issue.root_cause is not None
        and issue.capa is not None
        and all(action.completion is not None for action in issue.capa.actions)
        and issue.capa.effectiveness is None
        and not issue.capa.effectiveness_history
        and issue.closure is None
        and previous.status == "actioning"
        and previous.capa is not None
        and previous.root_cause is not None
        and not previous.merged_into
        and not previous.needs_recheck
        and not previous.recheck_reasons,
        "ORIGIN_NOT_COMPLETED",
        "原锚只接受真实无待重核、无有效性/关闭的最终措施完成版。",
    )
    raw = deepcopy(row.input_snapshot)
    _require(
        isinstance(raw, dict) and not {"confirmation_token", "approval_token"} & raw.keys(),
        "ORIGIN_SEMANTIC_MISSING",
        "不能以秘密或缺失原语义回填完成材料。",
        503,
    )
    try:
        payload = ActionsCompletePayload.model_validate(raw)
    except ValidationError:
        raise DomainError("ORIGIN_SEMANTIC_MISSING", "完成原载荷缺少精确typed语义。", 503) from None
    semantic = followup.semantic(payload)
    _require(
        semantic == raw
        and payload.issue_id == row.issue_id
        and payload.expected_issue_revision == before.revision,
        "ORIGIN_SEMANTIC_MISMATCH",
        "完成原载荷未匹配固定历史CAS。",
    )
    delta = {v.id: v for v in payload.completions}
    actions = []
    for action in previous.capa.actions:
        saved = action.model_dump(mode="json")
        if action.id in delta:
            new = delta.pop(action.id)
            _require(
                action.completion is None
                and new.executor_id == action.executor_id == row.writer_id
                and new.at.occurred_at <= row.created_at,
                "ORIGIN_COMPLETION_MISMATCH",
                "实际完成须是对应本人原未完成措施与真实发生钟。",
            )
            saved["completion"] = new.model_dump(mode="json")
        actions.append(saved)
    _require(
        not delta
        and set(issue.capa.requirement.required_failure_ids)
        == {v.identity for v in issue.failures},
        "ORIGIN_COMPLETION_MISMATCH",
        "完成措施或原失败覆盖不匹配。",
    )
    _require(
        len(issue.history) == len(previous.history) + 1 and issue.history[:-1] == previous.history,
        "ORIGIN_HISTORY_MISMATCH",
        "完成版须保留全部历史前缀并只追加本次事件。",
    )
    last = issue.history[-1]
    _require(
        last.operation == OPERATION
        and last.actor_kind == "human"
        and last.actor_id == row.writer_id
        and last.note == OPERATION
        and last.at <= row.created_at,
        "ORIGIN_HISTORY_MISMATCH",
        "实际完成历史未绑定当次具名人、原命令与时钟。",
    )
    expected = previous.model_dump(mode="json")
    expected.update(
        revision=row.revision,
        status="awaiting_verification",
        history=[*expected["history"], last.model_dump(mode="json")],
    )
    expected["capa"]["actions"] = actions
    _require(
        expected == issue.model_dump(mode="json"),
        "ORIGIN_COMPLETION_MISMATCH",
        "完成版不能暗改根因、措施、失败、要求或原历史字段。",
    )
    return payload


def _descriptor(row, issue, before):
    natures = {v.nature for v in issue.failures}
    _require(len(natures) == 1, "ORIGIN_NATURE_MISMATCH", "原失败性质不能混合或被提升。")
    try:
        value = a.IssueVersionEvidence(
            ref=a.VersionRef(id=row.id, revision=row.revision, snapshot_sha256=row.snapshot_sha256),
            previous_ref=a.VersionRef(
                id=before.id, revision=before.revision, snapshot_sha256=before.snapshot_sha256
            ),
            scope=issue.scope,
            issue_id=issue.id,
            purpose=row.purpose,
            owner_id=row.owner_id,
            writer_id=row.writer_id,
            visibility=row.visibility,
            nature=next(iter(natures)),
            operation=row.operation,
            domain_intent_sha256=row.intent_digest,
            created_at=row.created_at,
            issue=issue,
            sources=deepcopy(row.sources),
            required_source_read_set=deepcopy(row.required_source_read_set),
            source_basis=deepcopy(row.source_basis["artifact_sources"]),
            input_snapshot=deepcopy(row.input_snapshot),
            authority_snapshot=deepcopy(row.authority_snapshot),
            policy_snapshot=deepcopy(row.policy_snapshot),
            persisted_source_basis=deepcopy(row.source_basis),
        )
    except (ValidationError, KeyError, TypeError, ValueError):
        raise DomainError(
            "ORIGIN_DECLARED_BASIS_MISSING", "原完成版完整来源声明或固定元数据缺失。", 503
        ) from None
    wanted = a.canonical_sources(
        (
            *a.issue_sources(issue),
            *(s for f in issue.failures for s in (f.source, f.method, f.criterion)),
        )
    )
    _require(
        set(wanted) <= set(a.canonical_sources(value.sources)),
        "ORIGIN_DECLARED_BASIS_MISSING",
        "原根因/措施/完成/失败来源声明不能遗漏。",
        503,
    )
    return value


def _group(s, ctx, pid, row, issue, before, previous, payload):
    writer = _one(s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == row.writer_id)
    _require(writer.kind == "human", "ORIGIN_WRITER_MISMATCH", "历史完成者须是当时具名人。")
    receipt = _one(
        s,
        Receipt,
        Receipt.tenant_id == ctx.tenant_id,
        Receipt.product_id == pid,
        Receipt.operation == OPERATION,
        Receipt.subject_type == "quality_issue",
        Receipt.subject_id == row.id,
        Receipt.subject_revision == row.revision,
    )
    semantic = followup.semantic(payload)
    domain = digest(
        {
            "operation": OPERATION,
            "actor": str(row.writer_id),
            "product": str(pid),
            "payload": semantic,
        }
    )
    common = digest(
        {
            "operation": OPERATION,
            "product": pid,
            "payload": semantic,
            "named_actor": row.writer_id,
            "source_revision": None,
            "private_owner": row.writer_id,
        }
    )
    _require(
        row.intent_digest == domain and receipt.intent_digest == common,
        "ORIGIN_INTENT_MISMATCH",
        "领域与共同意图须分别对应实际原handler语义。",
    )
    _require(
        isinstance(receipt.result, dict)
        and isinstance(receipt.request_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", receipt.request_digest) is not None,
        "ORIGIN_RECEIPT_MISMATCH",
        "原回执须有真实canonical result及原请求摘要。",
    )
    _require(
        receipt.actor_id == receipt.requester_id == row.writer_id
        and receipt.run_id is None
        and receipt.command_id == issue.history[-1].command_id
        and receipt.visibility == row.visibility
        and receipt.result.get("id") == str(row.id)
        and type(receipt.result.get("revision")) is int
        and receipt.result["revision"] == row.revision
        and receipt.result.get("status") == row.status
        and row.created_at <= receipt.created_at <= _now(),
        "ORIGIN_RECEIPT_MISMATCH",
        "原完成回执未精确绑定当次人、不可变版或保存钟。",
    )
    key = list(
        s.scalars(
            select(RequestKey)
            .where(
                RequestKey.tenant_id == ctx.tenant_id,
                RequestKey.actor_id == row.writer_id,
                RequestKey.receipt_id == receipt.id,
                RequestKey.digest == receipt.request_digest,
            )
            .limit(1)
            .execution_options(populate_existing=True, autoflush=False)
        )
    )
    _require(bool(key), "ORIGIN_REQUEST_KEY_MISSING", "原共同摘要缺真实原RequestKey关联。", 503)
    audit = _one(s, Audit, Audit.tenant_id == ctx.tenant_id, Audit.receipt_id == receipt.id)
    outbox = _one(s, Outbox, Outbox.tenant_id == ctx.tenant_id, Outbox.receipt_id == receipt.id)
    _require(
        audit.actor_id == row.writer_id
        and audit.operation == OPERATION
        and outbox.actor_id == row.writer_id
        and outbox.type == EVENT
        and outbox.subject_id == row.id
        and outbox.subject_revision == row.revision
        and outbox.schema_version == 1
        and outbox.correlation_id == receipt.command_id,
        "ORIGIN_GROUP_MISMATCH",
        "原完成组缺精确审计/事件关联。",
    )
    saved = row.source_basis.get("shared_proof", {})
    _require(
        isinstance(saved, dict) and saved.get("tier") == "T1",
        "ORIGIN_PROOF_MISSING",
        "原完成版缺实际共同T1证明身份。",
        503,
    )
    try:
        proof_id = UUID(saved["id"])
    except (KeyError, ValueError, TypeError):
        raise DomainError("ORIGIN_PROOF_MISSING", "原完成证明UUID缺失。", 503) from None
    proof = _one(
        s,
        Confirmation,
        Confirmation.tenant_id == ctx.tenant_id,
        Confirmation.product_id == pid,
        Confirmation.id == proof_id,
    )
    _require(
        proof.consumed is True
        and proof.actor_id == row.writer_id
        and proof.subject_id == pid
        and proof.operation == OPERATION
        and type(proof.revision) is int
        and proof.revision > 0
        and proof.created_at <= row.created_at < proof.expires_at,
        "ORIGIN_PROOF_MISMATCH",
        "原共同证明未绑定原人/产品/操作/实际保存期限。",
    )
    snapshot = proof.snapshot or {}
    _require(isinstance(snapshot, dict), "ORIGIN_PROOF_MISMATCH", "原实质证明快照须是完整对象。")
    material = digest(
        {
            "tenant": ctx.tenant_id,
            "actor": row.writer_id,
            "requester": row.writer_id,
            "operation": OPERATION,
            "product": pid,
            "expected_revision": proof.revision,
            "read_set": sorted(
                deepcopy(row.required_source_read_set),
                key=lambda v: (v["artifact_id"], v["expected_revision"]),
            ),
            "payload": semantic,
        }
    )
    original_basis = {
        k: deepcopy(v)
        for k, v in row.source_basis.items()
        if k not in {"shared_proof", "completion_observations"}
    }
    _require(
        snapshot.get("before", {}).get(str(row.issue_id)) == previous.model_dump(mode="json")
        and snapshot.get("after", {}).get(str(row.issue_id))
        == followup._preview_issue(issue, previous)
        and snapshot.get("read_basis", {}).get("authority") == row.authority_snapshot
        and snapshot.get("read_basis", {}).get("policy") == row.policy_snapshot
        and snapshot.get("read_basis", {}).get("source_basis") == original_basis
        and a.canonical_reads(snapshot.get("read_basis", {}).get("read_set", []))
        == a.canonical_reads(row.required_source_read_set)
        and proof.payload_digest == material,
        "ORIGIN_PROOF_MISMATCH",
        "原共同实质快照未绑定精确前后Issue材料。",
    )
    return StoredCompletionGroup(
        receipt_id=receipt.id,
        command_id=receipt.command_id,
        writer_id=row.writer_id,
        audit_id=audit.id,
        outbox_id=outbox.id,
        proof_id=proof.id,
        proof_revision=proof.revision,
        proof_created_at=proof.created_at,
        proof_expires_at=proof.expires_at,
        receipt_created_at=receipt.created_at,
        domain_intent_sha256=domain,
        common_intent_sha256=common,
        original_request_digest=receipt.request_digest,
        material_sha256=material,
        proof_snapshot_sha256=digest(snapshot),
    )


def _current(s, ctx, pid, row):
    pointer = _one(
        s,
        QualityIssueCurrent,
        QualityIssueCurrent.tenant_id == ctx.tenant_id,
        QualityIssueCurrent.product_id == pid,
        QualityIssueCurrent.project_id == row.project_id,
        QualityIssueCurrent.issue_id == row.issue_id,
    )
    _require(
        type(pointer.epoch) is int
        and pointer.epoch > 0
        and type(pointer.issue_revision) is int
        and pointer.issue_revision >= row.revision,
        "ORIGIN_CURRENT_MISMATCH",
        "Current缺准确版本、单调epoch或指向原完成版之前。",
    )
    _require(
        isinstance(pointer.created_at, datetime)
        and pointer.created_at.tzinfo is not None
        and pointer.created_at.utcoffset() is not None
        and pointer.created_at <= _now(),
        "ORIGIN_CURRENT_MISMATCH",
        "Current缺实际已保存身份/时钟。",
    )
    current = _one(
        s,
        QualityIssueVersion,
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == pid,
        QualityIssueVersion.project_id == row.project_id,
        QualityIssueVersion.issue_id == row.issue_id,
        QualityIssueVersion.id == pointer.issue_version_id,
        QualityIssueVersion.revision == pointer.issue_revision,
    )
    _snapshot(current, ctx, pid, row.issue_id)
    _require(
        (current.owner_id, current.visibility, current.purpose)
        == (row.owner_id, row.visibility, row.purpose)
        and (current.revision != row.revision or current.id == row.id),
        "ORIGIN_CURRENT_MISMATCH",
        "Current不能换固定系列范围或同版身份。",
    )
    return StoredIssueCurrent(
        pointer_id=pointer.id,
        pointer_created_at=pointer.created_at,
        ref=a.VersionRef(
            id=current.id, revision=current.revision, snapshot_sha256=current.snapshot_sha256
        ),
        epoch=pointer.epoch,
        operation=current.operation,
        created_at=current.created_at,
    )


def read_origin_descriptor(
    s, ctx, product_id, issue_id, origin_ref: a.VersionRef
) -> StoredOriginRead:
    """Explicit immutable completed origin plus actual Current; never current grant."""
    _require(
        isinstance(ctx, Context) and isinstance(product_id, UUID) and isinstance(issue_id, UUID),
        "FORBIDDEN_SCOPE",
        "原完成版读取须用真实本人Context与固定产品/Issue。",
        403,
    )
    ref = a.VersionRef.model_validate(a.json_value(origin_ref))
    uow, caller = guards._uow(s), digest(vars(ctx))
    guards._acl(s, ctx, product_id)
    row, issue = _version(s, ctx, product_id, issue_id, ref)
    project = _project(s, ctx, product_id, row.project_id)
    before, previous = _previous(s, ctx, product_id, row)
    payload = _complete_shape(row, issue, before, previous)
    origin = _descriptor(row, issue, before)
    current = _current(s, ctx, product_id, row)
    group = _group(s, ctx, product_id, row, issue, before, previous, payload)
    # Actual stored declarations are copied before later IO. Never compare live
    # identity-map objects to themselves after populate_existing refreshes them.
    final_row, final_issue = _version(s, ctx, product_id, issue_id, ref, row.project_id)
    final_before, final_previous = _previous(s, ctx, product_id, final_row)
    final_payload = _complete_shape(final_row, final_issue, final_before, final_previous)
    _require(
        _descriptor(final_row, final_issue, final_before) == origin
        and _group(
            s, ctx, product_id, final_row, final_issue, final_before, final_previous, final_payload
        )
        == group,
        "SOURCE_STALE",
        "存储原完成版或原共同组在本次读取中改变。",
    )
    _require(
        _current(s, ctx, product_id, final_row) == current,
        "SOURCE_STALE",
        "本次原完成版读取期间Current/epoch已改变。",
    )
    guards._acl(s, ctx, product_id)
    # Fresh final mutable controls and Current are read in this same UOW. The
    # actual clock is sampled after the final Current/Project IO, so expiry during
    # that bounded IO is not evaluated against an earlier ACL clock.
    person = _one(s, Principal, Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id)
    grant = _one(
        s,
        Grant,
        Grant.tenant_id == ctx.tenant_id,
        Grant.product_id == product_id,
        Grant.principal_id == ctx.actor_id,
    )
    _require(
        _current(s, ctx, product_id, final_row) == current,
        "SOURCE_STALE",
        "末端Current/epoch漂移，不能返回旧存储描述。",
    )
    _require(
        _project(s, ctx, product_id, final_row.project_id) == project,
        "SOURCE_STALE",
        "末端Project实际scope/owner/visibility已改变。",
    )
    _require(
        person.kind == "human" and person.active is True and grant.expires_at > _now(),
        "FORBIDDEN_SCOPE",
        "全部存储IO结束时当前本人读取授权已失效。",
        403,
    )
    guards._same_uow(s, uow, ctx, caller)
    lineage_missing = current.ref != origin.ref
    return StoredOriginRead(
        origin=origin,
        project=project,
        current=current,
        completion_group=group,
        needs_lineage_owner=lineage_missing,
        missing_owners=(
            "original_failure_bytes_owner",
            "current_source_security_owner",
            "current_professional_policy_owner",
            *(("limited_issue_lineage_owner",) if lineage_missing else ()),
        ),
    )
