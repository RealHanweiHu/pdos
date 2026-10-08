"""Shared-command quality host. No commits, network, proofs or receipts owned here."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_issues.ports import Authority, Invocation
from pdos_next.domain.quality_issues.rules import (
    capa_draft_text_revisable,
    failure_ref,
    issue_sources,
    semantic_digest,
)
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product, RemediationLinkRecord, now
from pdos_next.schemas.quality_issues.contracts import (
    CapaDraft,
    ContainmentRecord,
    Issue,
    IssueCreate,
    IssueMerge,
    IssueTriage,
)
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import digest, require_access

from . import policy
from .adapters import TransactionCommands, kernel
from .evidence import check_source, merge_reads, source_basis, union_sources
from .models import (
    QualityEventFailureLink,
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
)
from .ports import FixedQualityResult
from .schemas import (
    CapaDraftPayload,
    ContainmentPayload,
    FailureReading,
    IssueCreatePayload,
    IssueMergePayload,
    IssueTriagePayload,
    IssueView,
    QualityReading,
)

PAYLOADS = {
    "quality.issue.create": IssueCreatePayload,
    "quality.issue.merge": IssueMergePayload,
    "quality.issue.triage": IssueTriagePayload,
    "quality.issue.containment.record": ContainmentPayload,
    "quality.capa.draft": CapaDraftPayload,
}
T1 = {"quality.issue.merge", "quality.issue.triage", "quality.issue.containment.record"}
deduplicate_subject = frozenset({"quality_issue"})
EFFECT = "保存固定失败/问题与草稿；不认定根因、有效性或关闭，不改原测试与配置。"


def configure_result_bridge(engine, bridge, *, refresh=None):
    if bridge is not None and not callable(bridge):
        raise TypeError("Trusted result bridge must be callable")
    if refresh is not None and not callable(refresh):
        raise TypeError("Trusted result refresh must be callable")
    engine._pdos_quality_result_bridge = bridge
    engine._pdos_quality_result_refresh = refresh


def _result(s, ctx, pid, **binding):
    bridge = getattr(s.get_bind(), "_pdos_quality_result_bridge", None)
    if not callable(bridge):
        raise DomainError("INTEGRATION_REQUIRED", "固定失败原值与原执行证明接口待接入。", 503)
    value = bridge(s, ctx, pid, **binding)
    value = (
        value if isinstance(value, FixedQualityResult) else FixedQualityResult.model_validate(value)
    )
    if (
        value.scope.tenant_id != ctx.tenant_id
        or value.scope.product_id != pid
        or (
            value.verified.run.id != binding["run_id"]
            or value.measurement_id != binding["measurement_id"]
            or (binding.get("event_id") is not None and value.event_id != binding["event_id"])
            or (
                binding.get("run_revision") is not None
                and value.run_revision != binding["run_revision"]
            )
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "品质桥未绑定精确原运行/测量/事件。")
    if not value.current:
        raise DomainError("RECHECK_REQUIRED", "原失败来源、配置或保存的执行证明待重核。")
    return value


def _stamp(value):
    raw = value.model_dump(mode="json")
    raw["retained"] = {
        k: v
        for k, v in raw["retained"].items()
        if k not in {"checked_at", "execution_window_elapsed"}
    }
    return digest(raw)


def _human(s, ctx, pid, *, write=False):
    product = s.scalar(select(Product).where(Product.id == pid, Product.tenant_id == ctx.tenant_id))
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "品质对象不在当前产品范围。", 403)
    require_access(s, ctx, pid, write=write, lock=write)
    actor = s.get(Principal, ctx.requester_id)
    if actor is None or actor.kind != "human" or ctx.actor_id != ctx.requester_id or ctx.run_id:
        raise DomainError("NAMED_PERSON_REQUIRED", "本切片只开放当前具名本人办理。", 403)
    return product


def _snapshot(row):
    if row.snapshot_sha256 != digest(row.issue_snapshot):
        raise DomainError("INTEGRITY_MISMATCH", "问题不可变版本摘要不一致。")
    issue = Issue.model_validate(row.issue_snapshot)
    if (
        issue.id != row.issue_id
        or issue.revision != row.revision
        or issue.status != row.status
        or (
            issue.scope
            != Scope(tenant_id=row.tenant_id, product_id=row.product_id, project_id=row.project_id)
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "问题固定范围/版本与行不一致。")
    return issue


def _row(s, ctx, pid, issue_id, revision=None):
    if revision is None:
        pointer = s.scalar(
            select(QualityIssueCurrent).where(
                QualityIssueCurrent.tenant_id == ctx.tenant_id,
                QualityIssueCurrent.product_id == pid,
                QualityIssueCurrent.issue_id == issue_id,
            )
        )
        row = s.get(QualityIssueVersion, pointer.issue_version_id) if pointer else None
        if row and row.revision != pointer.issue_revision:
            raise DomainError("INTEGRITY_MISMATCH", "问题当前指针版本不一致。")
    else:
        row = s.scalar(
            select(QualityIssueVersion).where(
                QualityIssueVersion.tenant_id == ctx.tenant_id,
                QualityIssueVersion.product_id == pid,
                QualityIssueVersion.issue_id == issue_id,
                QualityIssueVersion.revision == revision,
            )
        )
    if (
        row is None
        or row.tenant_id != ctx.tenant_id
        or row.product_id != pid
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "问题版本不在当前可读范围。", 403)
    _snapshot(row)
    return row


def _domain(payload):
    if isinstance(payload, IssueCreatePayload):
        return IssueCreate.model_validate(payload.model_dump(exclude={"visibility"}))
    cls = {
        IssueMergePayload: IssueMerge,
        IssueTriagePayload: IssueTriage,
        ContainmentPayload: ContainmentRecord,
        CapaDraftPayload: CapaDraft,
    }[type(payload)]
    return cls.model_validate(
        payload.model_dump(exclude={"issue_id", "expected_issue_revision", "confirmation_token"})
    )


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def _intent(ctx, command, payload):
    return digest(
        {
            "operation": command.operation,
            "actor": str(ctx.requester_id),
            "product": str(command.product_id),
            "payload": semantic(payload),
        }
    )


def _extra_sources(payload):
    if isinstance(payload, ContainmentPayload):
        return (*payload.action.evidence, payload.action.at.source)
    if isinstance(payload, CapaDraftPayload):
        return tuple(source for h in payload.hypotheses for source in h.sources)
    return ()


@dataclass
class Bound:
    scope: Scope
    purpose: str
    visibility: str
    owner_id: UUID
    rows: dict
    issues: dict
    results: tuple
    bindings: tuple
    create_result: object
    failure_issues: dict
    authority: dict
    policy: dict | None
    sources: tuple
    reads: list
    source_basis: dict
    domain_payload: object
    invocation: Invocation


def _load(s, ctx, command, product, payload, *, require_reads=True):
    _human(s, ctx, product.id, write=True)
    if command.operation not in PAYLOADS or not isinstance(payload, PAYLOADS[command.operation]):
        raise DomainError("INVALID_OPERATION", "该品质动作未在本切片开放。", 403)
    rows, issues, results, bindings, failure_issues = {}, {}, [], [], {}
    create = None
    if isinstance(payload, IssueCreatePayload):
        binding = {
            "run_id": payload.run_id,
            "measurement_id": payload.measurement_id,
            "event_id": payload.event_id,
            "write": True,
        }
        create = _result(s, ctx, product.id, **binding)
        selected = failure_ref(create.verified, payload.measurement_id)
        scope, purpose = create.scope, create.purpose
        visibility, owner = payload.visibility, ctx.requester_id
        if create.visibility == "private" and visibility != "private":
            raise DomainError("FORBIDDEN_SCOPE", "私有失败来源不能提升产品共享受众。", 403)
        results.append(create)
        bindings.append(binding)
        mapping = s.scalar(
            select(QualityFailureMap).where(
                QualityFailureMap.tenant_id == ctx.tenant_id,
                QualityFailureMap.product_id == product.id,
                QualityFailureMap.project_id == scope.project_id,
                QualityFailureMap.failure_identity == selected.identity,
            )
        )
        if mapping:
            row = _row(s, ctx, product.id, mapping.issue_id)
            rows[row.issue_id], issues[row.issue_id] = row, _snapshot(row)
            failure_issues[selected.identity] = issues[row.issue_id]
            visibility, owner = row.visibility, row.owner_id
    else:
        row = _row(s, ctx, product.id, payload.issue_id, payload.expected_issue_revision)
        rows[row.issue_id], issues[row.issue_id] = row, _snapshot(row)
        scope, purpose = issues[row.issue_id].scope, row.purpose
        visibility, owner = row.visibility, row.owner_id
        if isinstance(payload, IssueMergePayload):
            for ref in payload.sources:
                other = _row(s, ctx, product.id, ref.id, ref.revision)
                if other.project_id != scope.project_id or other.purpose != purpose:
                    raise DomainError("FORBIDDEN_SCOPE", "归并不能跨项目或固定用途。", 403)
                rows[other.issue_id], issues[other.issue_id] = other, _snapshot(other)
    authority = professional.assess(
        s, ctx, product.id, scope.project_id, command.operation, purpose, now(), write=True
    )
    if authority.get("authorized") is not True or authority.get("qualified") is not True:
        raise DomainError("QUALIFICATION_REQUIRED", "当前具名专业职责与资格不足。", 403)
    for issue in issues.values():
        for failure in issue.failures:
            binding = {
                "run_id": failure.run.id,
                "measurement_id": failure.measurement_id,
                "run_revision": failure.run.revision,
                "write": True,
            }
            value = _result(s, ctx, product.id, **binding)
            if (
                value.scope != scope
                or value.purpose != purpose
                or (failure_ref(value.verified, failure.measurement_id) != failure)
            ):
                raise DomainError("RECHECK_REQUIRED", "原问题失败的精确依据已经变化。")
            results.append(value)
            bindings.append(binding)
    published = None if create else policy.assess(s, ctx, product.id, scope.project_id, purpose)
    if published and published["private"] and visibility != "private":
        raise DomainError("FORBIDDEN_SCOPE", "政策私有出处不能扩大问题受众。", 403)
    extra = union_sources(_extra_sources(payload), *(issue_sources(i) for i in issues.values()))
    known = union_sources(*(v.sources for v in results))
    reads = merge_reads(
        *(v.required_source_read_set for v in results),
        *(r.required_source_read_set for r in rows.values()),
        authority.get("required_source_read_set", []),
        published["required_source_read_set"] if published else [],
    )
    for source in extra:
        if source not in known:
            additional, _, private = check_source(s, ctx, product.id, source)
            reads = merge_reads(reads, additional)
            if private and visibility != "private":
                raise DomainError("FORBIDDEN_SCOPE", "私有判断证据不能扩大问题受众。", 403)
    actual, private = source_basis(s, ctx, product.id, reads)
    if private and visibility != "private":
        raise DomainError("FORBIDDEN_SCOPE", "完整来源包含私有材料，不能生成共享问题。", 403)
    for row in rows.values():
        # Original judgments preserve their source-safety basis; current actor's
        # new authority is assessed independently, not compared to its old writer.
        saved = row.source_basis.get("artifact_sources", [])
        fixed, _ = source_basis(s, ctx, product.id, row.required_source_read_set)
        if saved and saved != fixed:
            raise DomainError("RECHECK_REQUIRED", "问题来源/安全epoch已改变，原历史保留。")
    if require_reads and merge_reads(command.source_read_set) != reads:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "命令须包含本次完整品质来源读集。")
    domain = _domain(payload)
    inv = Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=payload.run_id if create else payload.issue_id,
        expected_revision=0 if create else payload.expected_issue_revision,
        semantic_digest=semantic_digest(domain),
        confirmation_token=getattr(payload, "confirmation_token", None),
    )
    bound = Bound(
        scope,
        purpose,
        visibility,
        owner,
        rows,
        issues,
        tuple(results),
        tuple(bindings),
        create,
        failure_issues,
        authority,
        published,
        union_sources(known, extra, published["sources"] if published else ()),
        reads,
        {"artifact_sources": actual, "result_proofs": [_stamp(v) for v in results]},
        domain,
        inv,
    )
    _refresh(s, ctx, product.id, command.operation, bound)
    return bound


def _refresh(s, ctx, pid, operation, bound):
    # _load independently checked every original byte in this phase. Recheck all
    # fixed proofs without a second byte read, then current human authority last.
    # No proof is reused across validate, preview or apply transactions.
    refresh = getattr(s.get_bind(), "_pdos_quality_result_refresh", None)
    if not callable(refresh):
        raise DomainError("INTEGRATION_REQUIRED", "全部原值读取后历史执行重核接口待接入。", 503)
    for saved in bound.results:
        value = refresh(s, ctx, pid, saved, write=True)
        value = (
            value
            if isinstance(value, FixedQualityResult)
            else FixedQualityResult.model_validate(value)
        )
        if not value.current or _stamp(value) != _stamp(saved):
            raise DomainError("SOURCE_STALE", "完整原件核对后原失败或历史执行证明已变化。")
    if bound.policy is not None:
        current = policy.assess(s, ctx, pid, bound.scope.project_id, bound.purpose)
        if current != bound.policy:
            raise DomainError("SOURCE_STALE", "政策或签发入口已变化，请重新核对。")
    actual, _ = source_basis(s, ctx, pid, bound.reads)
    if actual != bound.source_basis["artifact_sources"]:
        raise DomainError("SOURCE_STALE", "品质原文或安全状态已变化。")
    authority = professional.assess(
        s, ctx, pid, bound.scope.project_id, operation, bound.purpose, now(), write=True
    )
    if (
        authority != bound.authority
        or authority.get("authorized") is not True
        or (authority.get("qualified") is not True)
    ):
        raise DomainError("SOURCE_STALE", "原件核对期间当前专业资格或签发epoch已变化。")
    at = now()
    for proof in (authority, bound.policy):
        if proof is None:
            continue
        try:
            until = datetime.fromisoformat(proof["valid_until"].replace("Z", "+00:00"))
            expired = until.utcoffset() is None or until <= at
        except (KeyError, TypeError, ValueError, AttributeError):
            expired = True
        if expired:
            raise DomainError("SOURCE_STALE", "办理核对结束时专业资格或政策边界已失效。")


def _kernel(s, ctx, pid, bound, record, *, accepted=False):
    authority = Authority(
        scope=bound.scope,
        actor_id=ctx.requester_id,
        actor_kind="human",
        roles=tuple(bound.authority["roles"]),
        audience=(
            f"private:{bound.owner_id}" if bound.visibility == "private" else f"product:{pid}",
        ),
        authorized=bound.authority["authorized"] is True,
        qualified=bound.authority["qualified"] is True,
        cancelled=False,
        now=now(),
    )

    def check(scope, source):
        if scope != bound.scope:
            raise DomainError("FORBIDDEN_SCOPE", "品质证据范围不一致。", 403)
        if source not in union_sources(*(v.sources for v in bound.results)):
            check_source(s, ctx, pid, source)

    commands = TransactionCommands(
        authority,
        bound.invocation,
        bound.issues,
        bound.failure_issues,
        record,
        accepted,
    )
    return kernel(commands, bound.results, bound.create_result, check, bound.policy)


def validate(s, ctx, command, product, payload):
    _load(s, ctx, command, product, payload)


def _has_capa_link(s, ctx, pid, issue):
    # Any saved link freezes the CAPA draft, including a now-stale/private link.
    # Product/Current locks belong to the caller; this immutable child needs no UPDATE grant.
    return (
        s.scalar(
            select(RemediationLinkRecord.id)
            .where(
                RemediationLinkRecord.tenant_id == ctx.tenant_id,
                RemediationLinkRecord.product_id == pid,
                RemediationLinkRecord.project_id == issue.scope.project_id,
                RemediationLinkRecord.issue_id == issue.id,
                RemediationLinkRecord.capa_id == issue.capa.id,
            )
            .limit(1)
        )
        is not None
    )


def _draft_not_linked(s, ctx, pid, payload, bound):
    if isinstance(payload, CapaDraftPayload):
        issue = bound.issues[payload.issue_id]
        if issue.capa is not None and _has_capa_link(s, ctx, pid, issue):
            raise DomainError("INVALID_STATE", "已有实际回链的CAPA不可续改草稿文本。")


def _new_write(s, ctx, command, product, payload, bound):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "产品水位已变化。")
    pointers = {}
    for identity, row in sorted(bound.rows.items(), key=lambda item: str(item[0])):
        pointer = s.scalar(
            select(QualityIssueCurrent)
            .where(
                QualityIssueCurrent.tenant_id == ctx.tenant_id,
                QualityIssueCurrent.product_id == product.id,
                QualityIssueCurrent.issue_id == identity,
            )
            .with_for_update()
        )
        if (
            pointer is None
            or pointer.issue_version_id != row.id
            or pointer.issue_revision != row.revision
        ):
            raise DomainError("VERSION_CONFLICT", "问题领域前版已改变。")
        pointers[identity] = pointer
    _draft_not_linked(s, ctx, product.id, payload, bound)
    if isinstance(payload, CapaDraftPayload):
        for action in payload.actions:
            actor = s.get(Principal, action.executor_id)
            grant = s.scalar(
                select(Grant).where(
                    Grant.tenant_id == ctx.tenant_id,
                    Grant.product_id == product.id,
                    Grant.principal_id == action.executor_id,
                )
            )
            if (
                actor is None
                or actor.tenant_id != ctx.tenant_id
                or not actor.active
                or (actor.kind != "human" or grant is None or grant.expires_at <= now())
            ):
                raise DomainError("FORBIDDEN_SCOPE", "措施责任人须当前产品具名成员。", 403)
    return pointers


def _record(s, ctx, command, product, payload, bound, pointers, mutation):
    _refresh(s, ctx, product.id, command.operation, bound)
    _draft_not_linked(s, ctx, product.id, payload, bound)
    saved = {}
    for issue in mutation.changes:
        old = bound.rows.get(issue.id)
        if issue.scope != bound.scope or issue.revision != (old.revision + 1 if old else 1):
            raise DomainError("INTEGRITY_MISMATCH", "纯品质变更未绑定实际前版或范围。")
        row = QualityIssueVersion(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=product.id,
            project_id=bound.scope.project_id,
            issue_id=issue.id,
            revision=issue.revision,
            previous_issue_version_id=old.id if old else None,
            previous_revision=old.revision if old else None,
            owner_id=old.owner_id if old else bound.owner_id,
            writer_id=ctx.requester_id,
            visibility=old.visibility if old else bound.visibility,
            purpose=bound.purpose,
            status=issue.status,
            operation=command.operation,
            issue_snapshot=issue.model_dump(mode="json"),
            snapshot_sha256=digest(issue.model_dump(mode="json")),
            input_snapshot=semantic(payload),
            authority_snapshot=bound.authority,
            policy_snapshot=bound.policy,
            sources=[r.model_dump(mode="json") for r in bound.sources],
            required_source_read_set=bound.reads,
            source_basis=bound.source_basis,
            intent_digest=_intent(ctx, command, payload),
            reason=getattr(payload, "reason", None)
            or getattr(payload, "title", None)
            or (
                payload.action.text
                if isinstance(payload, ContainmentPayload)
                else command.operation
            ),
        )
        s.add(row)
        s.flush()
        pointer = pointers.get(issue.id)
        if pointer:
            pointer.issue_version_id, pointer.issue_revision, pointer.epoch = (
                row.id,
                row.revision,
                pointer.epoch + 1,
            )
        else:
            pointer = QualityIssueCurrent(
                tenant_id=ctx.tenant_id,
                product_id=product.id,
                project_id=row.project_id,
                issue_id=issue.id,
                issue_version_id=row.id,
                issue_revision=row.revision,
                epoch=1,
            )
            s.add(pointer)
        saved[issue.id] = row
    s.flush()
    if isinstance(payload, IssueCreatePayload):
        selected = failure_ref(bound.create_result.verified, payload.measurement_id)
        issue = bound.failure_issues.get(selected.identity)
        result = saved.get(issue.id if issue else next(iter(saved)))
        if result is None:
            result = bound.rows[issue.id]
        mapping = s.scalar(
            select(QualityFailureMap).where(
                QualityFailureMap.tenant_id == ctx.tenant_id,
                QualityFailureMap.product_id == product.id,
                QualityFailureMap.project_id == bound.scope.project_id,
                QualityFailureMap.failure_identity == selected.identity,
            )
        )
        if mapping is None:
            s.add(
                QualityFailureMap(
                    tenant_id=ctx.tenant_id,
                    product_id=product.id,
                    project_id=bound.scope.project_id,
                    failure_identity=selected.identity,
                    issue_id=result.issue_id,
                    epoch=1,
                    failure=selected.model_dump(mode="json"),
                )
            )
        for delivery in mutation.deliveries:
            exists = s.scalar(
                select(QualityEventFailureLink.id).where(
                    QualityEventFailureLink.tenant_id == ctx.tenant_id,
                    QualityEventFailureLink.product_id == product.id,
                    QualityEventFailureLink.project_id == bound.scope.project_id,
                    QualityEventFailureLink.event_id == delivery.event_id,
                    QualityEventFailureLink.failure_identity == delivery.failure_identity,
                )
            )
            if exists is None:
                value = bound.create_result
                s.add(
                    QualityEventFailureLink(
                        tenant_id=ctx.tenant_id,
                        product_id=product.id,
                        project_id=bound.scope.project_id,
                        issue_id=result.issue_id,
                        issue_version_id=result.id,
                        issue_revision=result.revision,
                        event_id=delivery.event_id,
                        failure_identity=delivery.failure_identity,
                        build_id=value.verified.run.build.id,
                        request_id=value.verified.run.request_id,
                        run_id=value.verified.run.id,
                        run_version_id=value.run_version_id,
                        run_revision=value.run_revision,
                        measurement_id=value.measurement_id,
                        measurement_revision=1,
                        projection_id=value.projection_id,
                        projection_revision=value.projection_revision,
                        basis_sha256=value.basis_sha256,
                        failure=delivery.observed.model_dump(mode="json"),
                        sources=[r.model_dump(mode="json") for r in bound.sources],
                        required_source_read_set=bound.reads,
                        source_basis=bound.source_basis,
                    )
                )
        # Duplicate creation returns the ORIGINAL creation version, so common
        # subject de-duplication aliases its sole Receipt even after Issue advanced.
        if issue:
            result = _row(s, ctx, product.id, issue.id, 1)
    else:
        result = saved[payload.issue_id]
        if isinstance(payload, IssueMergePayload):
            identities = [r.id for r in payload.sources]
            mappings = list(
                s.scalars(
                    select(QualityFailureMap)
                    .where(
                        QualityFailureMap.tenant_id == ctx.tenant_id,
                        QualityFailureMap.product_id == product.id,
                        QualityFailureMap.project_id == bound.scope.project_id,
                        QualityFailureMap.issue_id.in_(identities),
                    )
                    .order_by(QualityFailureMap.failure_identity)
                    .with_for_update()
                )
            )
            for mapping in mappings:
                mapping.issue_id, mapping.epoch = payload.issue_id, mapping.epoch + 1
    result.action_result = {
        "issue_id": str(result.issue_id),
        "capa_id": str(payload.capa_id) if isinstance(payload, CapaDraftPayload) else None,
    }
    s.flush()
    return result


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    pointers = _new_write(s, ctx, command, product, payload, bound)
    saved = []

    def record(mutation):
        row = _record(s, ctx, command, product, payload, bound, pointers, mutation)
        saved.append(row)
        return row

    _kernel(s, ctx, product.id, bound, record, accepted=command.operation in T1).execute(
        bound.invocation, bound.domain_payload
    )
    return saved[0], "quality_issue", saved[0].visibility


def replay_subject_type(payload):
    return "quality_issue"


def replay_subject(s, ctx, command, product, payload):
    # Stable failure business de-duplication belongs to apply/Delivery staging;
    # only exact successful old action may short-circuit common proof consumption.
    if isinstance(payload, IssueCreatePayload):
        return None
    bound = _load(s, ctx, command, product, payload)
    return (
        s.scalar(
            select(QualityIssueVersion).where(
                QualityIssueVersion.tenant_id == ctx.tenant_id,
                QualityIssueVersion.product_id == product.id,
                QualityIssueVersion.issue_id == payload.issue_id,
                QualityIssueVersion.operation == command.operation,
                QualityIssueVersion.writer_id == ctx.requester_id,
                QualityIssueVersion.intent_digest == _intent(ctx, command, payload),
            )
        )
        if bound
        else None
    )


def _preview_issue(issue, before):
    raw = issue.model_dump(mode="json")
    previous = len(before.history) if before else 0
    for history in raw["history"][previous:]:
        history["at"] = None
    return raw


def _review(s, ctx, pid, bound):
    handler = _kernel(s, ctx, pid, bound, lambda _: None)
    preview, mutation = handler._prepare(
        handler.ports.commands.authority, bound.invocation, bound.domain_payload
    )
    if mutation.event_name == "issue.recheck_required":
        raise DomainError("RECHECK_REQUIRED", "原失败漂移须独立重核，不借建单续写。")
    return {
        "before": {str(k): i.model_dump(mode="json") for k, i in bound.issues.items()},
        "after": {str(i.id): _preview_issue(i, bound.issues.get(i.id)) for i in mutation.changes},
        "effect": EFFECT,
        "domain_preview": preview.model_dump(mode="json"),
        "read_basis": {
            "scope": bound.scope.model_dump(mode="json"),
            "purpose": bound.purpose,
            "authority": bound.authority,
            "policy": bound.policy,
            "source_basis": bound.source_basis,
            "read_set": bound.reads,
        },
        "event_effect": mutation.event_name,
        "delivery_effect": [d.model_dump(mode="json") for d in mutation.deliveries],
    }


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, bound)
    return _review(s, ctx, product.id, bound)


def inputs(s, ctx, pid, command):
    cls = PAYLOADS.get(command.operation)
    if cls is None:
        raise DomainError("INVALID_OPERATION", "品质输入动作未开放。", 403)
    product = _human(s, ctx, pid, write=True)
    if command.product_id != pid:
        raise DomainError("FORBIDDEN_SCOPE", "输入命令与当前产品不一致。", 403)
    payload = cls.model_validate(command.payload)
    bound = _load(s, ctx, command, product, payload, require_reads=False)
    _new_write(s, ctx, command, product, payload, bound)
    return {
        "operation": command.operation,
        "allowed": True,
        "required_source_read_set": bound.reads,
        "authority": bound.authority,
        "review": _review(s, ctx, pid, bound),
    }


def _view(s, ctx, pid, row, *, current, assess_capabilities=True):
    issue = _snapshot(row)
    reads = merge_reads(row.required_source_read_set)
    source_current = True
    try:
        source_basis(s, ctx, pid, reads)
    except DomainError as exc:
        if exc.status == 403:
            raise
        source_current = False
    capabilities = {op: False for op in PAYLOADS}
    capabilities.update(
        {
            "quality.issue.root_cause.decide": False,
            "quality.capa.actions.complete": False,
            "quality.capa.effectiveness.decide": False,
            "quality.issue.close": False,
        }
    )
    failures, authorities, published = [], {}, None
    state = "not_evaluated_historical" if source_current else "needs_recheck"
    if current and source_current:
        state = "current"
        for failure in issue.failures:
            try:
                value = _result(
                    s,
                    ctx,
                    pid,
                    run_id=failure.run.id,
                    measurement_id=failure.measurement_id,
                    run_revision=failure.run.revision,
                )
                if failure_ref(value.verified, failure.measurement_id) != failure:
                    raise DomainError("RECHECK_REQUIRED", "原失败固定依据已改变。")
                measurement = next(
                    m for m in value.verified.run.measurements if m.id == failure.measurement_id
                )
                failures.append(
                    FailureReading(
                        failure=failure,
                        available=True,
                        measurement=measurement.model_dump(mode="json"),
                        projection_id=value.projection_id,
                        basis_sha256=value.basis_sha256,
                        required_source_read_set=value.required_source_read_set,
                    )
                )
            except DomainError as exc:
                if exc.status == 403:
                    raise
                state = "needs_recheck"
                failures.append(
                    FailureReading(failure=failure, available=False, reason_codes=(exc.code,))
                )
        if state == "current" and not issue.needs_recheck and not issue.merged_into:
            try:
                published = policy.assess(s, ctx, pid, row.project_id, row.purpose)
                reads = merge_reads(reads, published["required_source_read_set"])
                if assess_capabilities:
                    for op in PAYLOADS:
                        if op == "quality.issue.create":
                            continue
                        authority = professional.assess(
                            s, ctx, pid, row.project_id, op, row.purpose, now()
                        )
                        authorities[op] = authority
                        legal = (
                            (
                                op in {"quality.issue.triage", "quality.issue.merge"}
                                and issue.status == "open"
                            )
                            or (
                                op == "quality.issue.merge"
                                and issue.status == "triaged"
                                and not issue.capa
                            )
                            or (
                                op == "quality.issue.containment.record"
                                and issue.status in {"triaged", "actioning"}
                            )
                            or (
                                op == "quality.capa.draft"
                                and issue.status in {"triaged", "actioning"}
                                and (
                                    issue.capa is None
                                    or (
                                        capa_draft_text_revisable(issue)
                                        and not _has_capa_link(s, ctx, pid, issue)
                                    )
                                )
                            )
                        )
                        capabilities[op] = bool(
                            legal
                            and authority.get("authorized") is True
                            and authority.get("qualified") is True
                        )
                        reads = merge_reads(reads, authority.get("required_source_read_set", []))
            except DomainError as exc:
                if exc.status == 403:
                    raise
                state = "needs_recheck"
    return IssueView(
        id=row.id,
        issue_id=row.issue_id,
        revision=row.revision,
        project_id=row.project_id,
        purpose=row.purpose,
        visibility=row.visibility,
        owner_id=row.owner_id,
        status=row.status,
        issue=issue,
        is_current=current,
        source_status=state,
        failures=tuple(failures),
        capabilities=capabilities,
        authority=authorities,
        policy=published,
        required_source_read_set=reads,
        sources=row.sources,
        created_at=row.created_at,
        reason=row.reason,
        followup_needs=(
            {
                "kind": "new_verification_run",
                "issue_id": str(row.issue_id),
                "issue_revision": row.revision,
                "capa_id": str(issue.capa.id),
                "created_output": None,
            },
        )
        if issue.capa
        else (),
    )


def get_issue(s, ctx, pid, issue_id, revision=None, *, write=False):
    _human(s, ctx, pid, write=write)
    row = _row(s, ctx, pid, issue_id, revision)
    pointer = s.scalar(
        select(QualityIssueCurrent).where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == pid,
            QualityIssueCurrent.issue_id == issue_id,
        )
    )
    return row, _view(
        s, ctx, pid, row, current=bool(pointer and pointer.issue_version_id == row.id)
    )


def get_issue_for_change(s, ctx, pid, issue_id, revision=None, *, write=False):
    """Fixed Issue proof without unrelated quality write-capability assessment.

    Current/source ACL, actual failure bridge and current risk policy remain
    independently checked on every call. No proof is shared across phases.
    """
    _human(s, ctx, pid, write=write)
    row = _row(s, ctx, pid, issue_id, revision)
    pointer = s.scalar(
        select(QualityIssueCurrent).where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == pid,
            QualityIssueCurrent.issue_id == issue_id,
        )
    )
    return row, _view(
        s,
        ctx,
        pid,
        row,
        current=bool(pointer and pointer.issue_version_id == row.id),
        assess_capabilities=False,
    )


def _change_scope_acl(s, ctx, pid):
    """Fresh scalar access only; no identity-map or professional attestation."""
    rows = list(
        s.execute(
            select(
                Product.id.label("product_id"),
                Product.tenant_id.label("tenant_id"),
                Product.revision,
                Product.status,
                Product.owner_id,
                Principal.id.label("person_id"),
                Principal.kind,
                Principal.active,
                Principal.access_epoch.label("person_epoch"),
                Grant.id.label("grant_id"),
                Grant.can_write,
                Grant.access_epoch.label("grant_epoch"),
                Grant.expires_at,
            )
            .select_from(Product)
            .join(Grant, (Grant.tenant_id == Product.tenant_id) & (Grant.product_id == Product.id))
            .join(
                Principal,
                (Principal.tenant_id == Grant.tenant_id) & (Principal.id == Grant.principal_id),
            )
            .where(
                Product.tenant_id == ctx.tenant_id,
                Product.id == pid,
                Principal.id == ctx.requester_id,
            )
            .limit(2)
            .execution_options(autoflush=False)
        ).mappings()
    )
    if (
        len(rows) != 1
        or rows[0]["tenant_id"] != ctx.tenant_id
        or rows[0]["product_id"] != pid
        or rows[0]["person_id"] != ctx.requester_id
        or rows[0]["kind"] != "human"
        or rows[0]["active"] is not True
        or rows[0]["expires_at"] is None
        or rows[0]["expires_at"] <= now()
    ):
        raise DomainError("FORBIDDEN_SCOPE", "当前本人不能读取固定问题范围。", 403)
    return dict(rows[0])


def _change_scope_for_change(s, ctx, pid, ref):
    """Only derive fixed Scope/purpose; the enclosing readers must verify truth.

    No failure, source, policy or professional proof is returned or reused. The
    Change host follows this with initial AND final fresh complete owner reads.
    """
    from pdos_next.domain.capa_effectiveness.fact_atom_storage import _same_uow, _uow
    from pdos_next.schemas.change_control.contracts import Ref
    from pdos_next.service import Context

    uow = _uow(s)
    if (
        type(ctx) is not Context
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id is not None
        or type(ref) is not Ref
        or ref.kind not in {"issue", "capa"}
    ):
        raise DomainError("FIXED_REFERENCE_MISMATCH", "范围读取须固定本人Issue/CAPA引用。")
    caller = digest(vars(ctx))

    def pending():
        from sqlalchemy import inspect

        for row in tuple(s.new) + tuple(s.dirty) + tuple(s.deleted):
            if isinstance(row, Product):
                state = inspect(row)
                changed = (
                    row in s.new
                    or row in s.deleted
                    or any(
                        state.attrs[column.key].history.has_changes()
                        for column in Product.__table__.columns
                        if column.key != "lifecycle_epoch"
                    )
                )
            else:
                changed = isinstance(
                    row, (Principal, Grant, QualityIssueVersion, QualityIssueCurrent)
                )
            if changed:
                raise DomainError("RECHECK_REQUIRED", "未保存范围变动不能作为固定问题依据。")

    pending()
    with s.no_autoflush:
        access = _change_scope_acl(s, ctx, pid)
        rows = list(
            s.scalars(
                select(QualityIssueVersion)
                .where(
                    QualityIssueVersion.tenant_id == ctx.tenant_id,
                    QualityIssueVersion.product_id == pid,
                    QualityIssueVersion.issue_id == ref.id,
                    QualityIssueVersion.revision == ref.revision,
                )
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if len(rows) != 1:
            raise DomainError("FORBIDDEN_SCOPE", "固定问题版本不在当前读取范围。", 403)
        row = rows[0]
        if (
            row.tenant_id != ctx.tenant_id
            or row.product_id != pid
            or row.issue_id != ref.id
            or row.revision != ref.revision
            or row.visibility not in {"private", "product"}
            or (row.visibility == "private" and row.owner_id != ctx.requester_id)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "固定问题范围或私人受众不一致。", 403)
        issue = _snapshot(row)
        expected_audience = (
            f"private:{row.owner_id}" if row.visibility == "private" else f"product:{pid}",
        )
        if (
            issue.audience != expected_audience
            or not isinstance(row.purpose, str)
            or not row.purpose
        ):
            raise DomainError("INTEGRITY_MISMATCH", "固定问题受众或用途无法核对。")
        pointers = list(
            s.scalars(
                select(QualityIssueCurrent)
                .where(
                    QualityIssueCurrent.tenant_id == ctx.tenant_id,
                    QualityIssueCurrent.product_id == pid,
                    QualityIssueCurrent.project_id == row.project_id,
                    QualityIssueCurrent.issue_id == ref.id,
                )
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if len(pointers) != 1:
            raise DomainError("RECHECK_REQUIRED", "固定问题当前指针待重核。")
        pointer = pointers[0]
        if (
            (pointer.tenant_id, pointer.product_id, pointer.project_id, pointer.issue_id)
            != (ctx.tenant_id, pid, row.project_id, ref.id)
            or pointer.issue_version_id != row.id
            or pointer.issue_revision != row.revision
            or type(pointer.epoch) is not int
            or pointer.epoch < 1
        ):
            raise DomainError("RECHECK_REQUIRED", "固定问题已非当前版或指针范围不一致。")
        latest = list(
            s.scalars(
                select(QualityIssueVersion)
                .where(
                    QualityIssueVersion.tenant_id == ctx.tenant_id,
                    QualityIssueVersion.product_id == pid,
                    QualityIssueVersion.project_id == row.project_id,
                    QualityIssueVersion.issue_id == ref.id,
                    QualityIssueVersion.revision >= row.revision,
                )
                .limit(2)
                .execution_options(populate_existing=True, autoflush=False)
            )
        )
        if len(latest) != 1 or latest[0].id != row.id or latest[0].revision != row.revision:
            raise DomainError("RECHECK_REQUIRED", "当前指针不能回退到同一问题的旧版。")
        if (ref.kind == "issue" and ref.key is not None) or (
            ref.kind == "capa" and (issue.capa is None or ref.key != str(issue.capa.id))
        ):
            raise DomainError("FIXED_REFERENCE_MISMATCH", "Issue/CAPA key不属于固定问题版。")
        if _change_scope_acl(s, ctx, pid) != access:
            raise DomainError("FORBIDDEN_SCOPE", "范围读取期间本人权限已变化。", 403)
    _same_uow(s, uow, ctx, caller)
    pending()
    if now() >= access["expires_at"]:
        raise DomainError("FORBIDDEN_SCOPE", "范围读取结束时本人权限已到期。", 403)
    return issue.scope, row.purpose


def list_quality(s, ctx, pid, *, issue_id=None, run_id=None, build_id=None):
    _human(s, ctx, pid)
    # Explicit selection bounds current proofs; empty selection reads no full history.
    query = select(QualityIssueVersion).where(
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == pid,
    )
    mapping_more = False
    if issue_id is not None:
        query = query.where(QualityIssueVersion.issue_id == issue_id)
    elif run_id is not None or build_id is not None:
        targets = select(QualityFailureMap.issue_id.label("issue_id")).where(
            QualityFailureMap.tenant_id == ctx.tenant_id,
            QualityFailureMap.product_id == pid,
        )
        originals = select(QualityEventFailureLink.issue_id.label("issue_id")).where(
            QualityEventFailureLink.tenant_id == ctx.tenant_id,
            QualityEventFailureLink.product_id == pid,
        )
        if run_id is not None:
            targets = targets.where(QualityFailureMap.failure["run"]["id"].astext == str(run_id))
            originals = originals.where(QualityEventFailureLink.run_id == run_id)
        if build_id is not None:
            targets = targets.where(
                QualityFailureMap.failure["build"]["id"].astext == str(build_id)
            )
            originals = originals.where(QualityEventFailureLink.build_id == build_id)
        # Merge retargets the live failure map. Immutable delivery links retain
        # the original Issue identities so their current pointer/history stays
        # selectable. This selects identities only; _row/_view still enforce
        # current visibility, sources and professional proofs for every row.
        logical_scope = targets.union(originals).subquery()
        selected = list(
            s.scalars(
                select(logical_scope.c.issue_id).order_by(logical_scope.c.issue_id).limit(101)
            )
        )
        mapping_more = len(selected) > 100
        query = query.where(QualityIssueVersion.issue_id.in_(selected[:100]))
    else:
        return QualityReading(
            issues=(), current_by_issue={}, capabilities={}, unavailable_count=0, has_more=False
        ).model_dump(mode="json")
    rows = list(s.scalars(query.order_by(QualityIssueVersion.created_at.desc()).limit(101)))
    views, pointers, unavailable = [], {}, 0
    for row in rows[:100]:
        try:
            pointer = s.scalar(
                select(QualityIssueCurrent).where(
                    QualityIssueCurrent.tenant_id == ctx.tenant_id,
                    QualityIssueCurrent.product_id == pid,
                    QualityIssueCurrent.issue_id == row.issue_id,
                )
            )
            current = bool(pointer and pointer.issue_version_id == row.id)
            views.append(
                _view(s, ctx, pid, _row(s, ctx, pid, row.issue_id, row.revision), current=current)
            )
            if current:
                pointers[str(row.issue_id)] = {"issue_version_id": row.id, "revision": row.revision}
        except DomainError:
            unavailable += 1
    failures = _failure_candidates(s, ctx, pid, run_id, build_id) if run_id else ()
    known_policies = {digest(view.policy): view.policy for view in views if view.policy is not None}
    actor = s.get(Principal, ctx.requester_id)
    return QualityReading(
        issues=tuple(views),
        current_by_issue=pointers,
        failures=failures,
        policy=next(iter(known_policies.values())) if len(known_policies) == 1 else None,
        next_owners=({"id": str(actor.id), "label": actor.name},) if actor else (),
        capabilities={op: any(v.capabilities.get(op, False) for v in views) for op in PAYLOADS},
        unavailable_count=unavailable,
        has_more=mapping_more or len(rows) > 100,
    ).model_dump(mode="json")


def _failure_candidates(s, ctx, pid, run_id, build_id):
    from pdos_next.domain.verification_launch.models import (
        VerificationRunCurrent,
        VerificationRunVersion,
    )
    from pdos_next.domain.verification_results.models import TestResultProjection
    from pdos_next.models import Outbox

    pointer = s.scalar(
        select(VerificationRunCurrent).where(
            VerificationRunCurrent.tenant_id == ctx.tenant_id,
            VerificationRunCurrent.product_id == pid,
            VerificationRunCurrent.run_id == run_id,
        )
    )
    row = s.get(VerificationRunVersion, pointer.run_version_id) if pointer else None
    if (
        row is None
        or row.tenant_id != ctx.tenant_id
        or row.product_id != pid
        or (build_id is not None and row.build_id != build_id)
        or (row.visibility == "private" and row.owner_id != ctx.requester_id)
    ):
        raise DomainError("FORBIDDEN_SCOPE", "选择的失败运行与构建不一致。", 403)
    projections = list(
        s.scalars(
            select(TestResultProjection.id).where(
                TestResultProjection.tenant_id == ctx.tenant_id,
                TestResultProjection.product_id == pid,
                TestResultProjection.run_version_id == row.id,
            )
        )
    )
    events = list(
        s.scalars(
            select(Outbox.id)
            .where(
                Outbox.tenant_id == ctx.tenant_id,
                Outbox.subject_id.in_([row.id, *projections]),
            )
            .order_by(Outbox.created_at)
            .limit(100)
        )
    )
    output = []
    for result in row.run_snapshot.get("computed_results", []):
        if result["result"] != "fail" or row.run_snapshot["result"] != "fail":
            continue
        values = []
        for event in events:
            value = _result(
                s,
                ctx,
                pid,
                run_id=run_id,
                measurement_id=UUID(result["measurement_id"]),
                event_id=event,
            )
            values.append(value)
        if not values:
            continue
        fixed = values[0]
        authority = professional.assess(
            s, ctx, pid, fixed.scope.project_id, "quality.issue.create", fixed.purpose, now()
        )
        output.append(
            FailureReading(
                failure=failure_ref(fixed.verified, fixed.measurement_id),
                available=True,
                measurement=next(
                    m for m in fixed.verified.run.measurements if m.id == fixed.measurement_id
                ).model_dump(mode="json"),
                projection_id=fixed.projection_id,
                basis_sha256=fixed.basis_sha256,
                event_ids=tuple(events),
                required_source_read_set=merge_reads(
                    fixed.required_source_read_set, authority.get("required_source_read_set", [])
                ),
                authority=authority,
                capabilities={
                    "quality.issue.create": authority.get("authorized") is True
                    and authority.get("qualified") is True
                },
            )
        )
    return tuple(output)
