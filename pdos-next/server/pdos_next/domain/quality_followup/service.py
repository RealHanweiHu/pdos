"""Root-cause and completion host; shared service owns proof/Receipt/UOW.

No callbacks are production defaults. Every phase independently reads archived
failure bytes and rechecks current authority/policy after the final I/O. This
module never commits, consumes a proof, creates output or starts verification.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.database import category_for_product
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution.evidence import (
    check_source,
    merge_reads,
    source_basis,
    union_sources,
)
from pdos_next.domain.quality_execution.models import (
    QualityEventFailureLink,
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
)
from pdos_next.domain.quality_execution.ports import FixedQualityResult
from pdos_next.domain.quality_issues.ports import Authority, Invocation
from pdos_next.domain.quality_issues.rules import failure_ref, issue_sources, semantic_digest
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product, now
from pdos_next.schemas.quality_issues.contracts import ActionsComplete, Issue, RootCauseDecide
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import digest, require_access, source_for

from .adapters import TransactionCommands, kernel
from .evidence import completion_observation
from .ports import Runtime
from .schemas import ActionsCompletePayload, CompletionAssessment, RootCausePayload

ROOT_CAUSE = "quality.issue.root_cause.decide"
COMPLETE = "quality.capa.actions.complete"
PAYLOADS = {ROOT_CAUSE: RootCausePayload, COMPLETE: ActionsCompletePayload}
deduplicate_subject = frozenset({"quality_issue"})
EFFECT = "具名根因或本人实际完成；保留原失败、假设、措施与历史，不决定有效性或关闭。"


def configure_followup(engine, *, append_issue, consumed_proof, assess_action_completion=None):
    if not callable(append_issue) or not callable(consumed_proof):
        raise TypeError("Follow-up requires explicit append and real consumed-proof callbacks")
    if assess_action_completion is not None and not callable(assess_action_completion):
        raise TypeError("Completion assessment must be a trusted callable")
    engine._pdos_quality_followup = Runtime(append_issue, consumed_proof, assess_action_completion)


def _runtime(s):
    value = getattr(s.get_bind(), "_pdos_quality_followup", None)
    if (
        not isinstance(value, Runtime)
        or not callable(value.append_issue)
        or not callable(value.consumed_proof)
    ):
        raise DomainError("INTEGRATION_REQUIRED", "品质后续共同事务入口尚未接入。", 503)
    return value


def _human(s, ctx, pid, *, write=False):
    product = s.scalar(select(Product).where(Product.id == pid, Product.tenant_id == ctx.tenant_id))
    if product is None:
        raise DomainError("FORBIDDEN_SCOPE", "品质后续对象不在型号范围。", 403)
    require_access(s, ctx, pid, write=write, lock=write)
    actor = s.execute(
        select(Principal.tenant_id, Principal.kind, Principal.active).where(
            Principal.id == ctx.requester_id
        )
    ).one_or_none()
    if (
        actor is None
        or actor.tenant_id != ctx.tenant_id
        or actor.kind != "human"
        or actor.active is not True
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
    ):
        raise DomainError("NAMED_PERSON_REQUIRED", "此动作只由当前有权具名本人办理。", 403)
    return product


def _snapshot(row):
    if digest(row.issue_snapshot) != row.snapshot_sha256:
        raise DomainError("INTEGRITY_MISMATCH", "问题不可变内容摘要不一致。")
    issue = Issue.model_validate(row.issue_snapshot)
    if (
        issue.id != row.issue_id
        or issue.revision != row.revision
        or issue.status != row.status
        or issue.scope
        != Scope(tenant_id=row.tenant_id, product_id=row.product_id, project_id=row.project_id)
        or issue.audience
        != (
            f"private:{row.owner_id}"
            if row.visibility == "private"
            else f"category:{row.category_id}",
        )
    ):
        raise DomainError("INTEGRITY_MISMATCH", "固定问题范围与版本不一致。")
    return issue


def _row(s, ctx, pid, issue_id, revision):
    row = s.scalar(
        select(QualityIssueVersion).where(
            QualityIssueVersion.tenant_id == ctx.tenant_id,
            QualityIssueVersion.product_id == pid,
            QualityIssueVersion.issue_id == issue_id,
            QualityIssueVersion.revision == revision,
        )
    )
    if row is None or (row.visibility == "private" and row.owner_id != ctx.requester_id):
        raise DomainError("FORBIDDEN_SCOPE", "问题固定版不在当前可读范围。", 403)
    _snapshot(row)
    return row


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"approval_token", "confirmation_token"})


def _domain(payload):
    cls = RootCauseDecide if isinstance(payload, RootCausePayload) else ActionsComplete
    return cls.model_validate(
        payload.model_dump(
            exclude={
                "issue_id",
                "expected_issue_revision",
                "approval_token",
                "confirmation_token",
            }
        )
    )


def _intent(ctx, command, payload):
    return digest(
        {
            "operation": command.operation,
            "actor": str(ctx.requester_id),
            "product": str(command.product_id),
            "payload": semantic(payload),
        }
    )


def request_subject(payload):
    return payload.issue_id


def replay_subject_type(payload):
    return "quality_issue"


def _stamp(value):
    raw = value.model_dump(mode="json")
    raw["retained"] = {
        k: v
        for k, v in raw["retained"].items()
        if k not in {"checked_at", "execution_window_elapsed"}
    }
    return digest(raw)


def _result(s, ctx, pid, failure, *, write):
    bridge = getattr(s.get_bind(), "_pdos_quality_result_bridge", None)
    if not callable(bridge):
        raise DomainError("INTEGRATION_REQUIRED", "固定原失败原件/执行证明入口尚未接入。", 503)
    value = bridge(
        s,
        ctx,
        pid,
        run_id=failure.run.id,
        run_revision=failure.run.revision,
        measurement_id=failure.measurement_id,
        write=write,
    )
    value = (
        value if isinstance(value, FixedQualityResult) else FixedQualityResult.model_validate(value)
    )
    if not value.current or failure_ref(value.verified, failure.measurement_id) != failure:
        raise DomainError("RECHECK_REQUIRED", "固定原失败依据已变化，需要独立重核。")
    return value


def _extra(payload):
    if isinstance(payload, RootCausePayload):
        return payload.sources
    return tuple(s for c in payload.completions for s in (*c.evidence, c.at.source))


def _exact_basis(s, ctx, pid, row, *, results=(), write):
    # Only called after A's current fixed-failure bytes and exact judgment
    # sources were checked in this phase. No unverified client DTO can enter.
    from pdos_next.domain.capa_verification import service as followups

    build = getattr(followups, "basis_from_issue", None)
    if not callable(build):
        raise DomainError("INTEGRATION_REQUIRED", "固定CAPA依据读取接口尚未接入。", 503)
    reads = merge_reads(
        row.required_source_read_set, *(v.required_source_read_set for v in results)
    )
    fixed, _ = source_basis(s, ctx, pid, reads)
    original, _ = source_basis(s, ctx, pid, row.required_source_read_set)
    if (
        not row.source_basis.get("artifact_sources")
        or row.source_basis["artifact_sources"] != original
    ):
        raise DomainError("RECHECK_REQUIRED", "原问题完整來源/安全epoch已改变。")
    issue = _snapshot(row)
    return build(
        row,
        issue,
        sources=union_sources(row.sources, issue_sources(issue), *(v.sources for v in results)),
        reads=reads,
        source_basis=fixed,
    )


def _assessment(
    s, ctx, pid, runtime, basis, policy_value, issue, completion, observation, *, write
):
    callback = runtime.assess_action_completion
    if not callable(callback):
        raise DomainError("INTEGRATION_REQUIRED", "调查/正式实施真实完成核对入口尚未接入。", 503)
    action = next((a for a in issue.capa.actions if a.id == completion.id), None)
    if action is None:
        raise DomainError("ACTION_CONFLICT", "完成不能增加未知措施。")
    value = callback(
        s,
        ctx,
        pid,
        basis,
        action,
        completion,
        policy_snapshot=policy_value,
        observation=observation,
        write=write,
    )
    value = (
        value
        if isinstance(value, CompletionAssessment)
        else CompletionAssessment.model_validate(value)
    )
    binding = next(a for a in basis.actions if a.action_id == action.id)
    if (
        value.scope != issue.scope
        or value.issue_id != issue.id
        or value.capa_id != issue.capa.id
        or value.action_id != action.id
        or value.executor_id != ctx.requester_id
        or value.purpose != basis.purpose
        or value.basis_sha256 != basis.basis_sha256
        or value.action_sha256 != binding.action_sha256
        or value.completion_sha256 != digest(completion.model_dump(mode="json"))
        or value.event_source.model_dump(mode="json")
        != completion.at.source.model_dump(mode="json")
        or value.policy_basis_sha256 != digest(policy_value)
        or value.nature != basis.nature
        or value.proof_sha256 != digest(value.model_dump(mode="json", exclude={"proof_sha256"}))
    ):
        raise DomainError("INTEGRITY_MISMATCH", "完成核对未绑定服务器措施/政策/真实发生事实。")
    if (
        value.allowed is not True
        or value.current is not True
        or value.classification == "unknown"
        or (value.valid_until is not None and value.valid_until <= now())
        or any(bound <= now() for bound in value.time_constraints)
        or (value.classification == "formal_change" and not value.owner_proofs)
    ):
        raise DomainError(
            "ACTION_COMPLETION_UNVERIFIED", "真实完成或正式实施证据不足，不能标记完成。"
        )
    return value


@dataclass
class Bound:
    row: object
    issue: Issue
    purpose: str
    runtime: Runtime
    authority: dict
    policy: dict
    results: tuple
    basis: object
    observations: tuple
    assessments: tuple
    sources: tuple
    reads: list
    source_basis: dict
    invocation: Invocation
    domain_payload: object
    payload: object
    write: bool


def _load(s, ctx, command, product, payload, *, require_reads=True, write=True):
    _human(s, ctx, product.id, write=write)
    if command.product_id != product.id or type(payload) is not PAYLOADS.get(command.operation):
        raise DomainError("INVALID_OPERATION", "当前后续操作未开放或产品不匹配。", 403)
    runtime = _runtime(s)
    row = _row(s, ctx, product.id, payload.issue_id, payload.expected_issue_revision)
    issue = _snapshot(row)
    if issue.needs_recheck or issue.merged_into:
        raise DomainError("RECHECK_REQUIRED", "归并或问题原依据待独立重核。")
    authority = professional.assess(
        s, ctx, product.id, row.project_id, command.operation, row.purpose, now(), write=write
    )
    if authority.get("authorized") is not True or authority.get("qualified") is not True:
        raise DomainError("QUALIFICATION_REQUIRED", "本动作当前具名专业职责/资格不足。", 403)
    if command.operation == ROOT_CAUSE and "quality" not in authority.get("roles", []):
        raise DomainError("FORBIDDEN_OPERATION", "根因专业决定须品质职责。", 403)
    results = tuple(_result(s, ctx, product.id, f, write=write) for f in issue.failures)
    if any(v.scope != issue.scope or v.purpose != row.purpose for v in results):
        raise DomainError("FORBIDDEN_SCOPE", "失败证明不能跨项目或固定用途。", 403)
    published = policy.assess(s, ctx, product.id, row.project_id, row.purpose)
    sources = union_sources(
        *(v.sources for v in results), issue_sources(issue), _extra(payload), published["sources"]
    )
    reads = merge_reads(
        row.required_source_read_set,
        *(v.required_source_read_set for v in results),
        published["required_source_read_set"],
        authority["required_source_read_set"],
    )
    known = union_sources(*(v.sources for v in results))
    for source in sources:
        if source not in known:
            extra_reads, _, private = check_source(s, ctx, product.id, source)
            if private and row.visibility != "private":
                raise DomainError("FORBIDDEN_SCOPE", "私有来源不能扩大问题受众。", 403)
            reads = merge_reads(reads, extra_reads)
    basis = _exact_basis(s, ctx, product.id, row, results=results, write=write)
    if (basis.issue_version_id, basis.issue_revision, basis.scope, basis.purpose) != (
        row.id,
        row.revision,
        issue.scope,
        row.purpose,
    ):
        raise DomainError("INTEGRITY_MISMATCH", "CAPA依据未绑定精确问题前版。")
    reads = merge_reads(reads, basis.required_source_read_set)
    observations, assessments = [], []
    if isinstance(payload, ActionsCompletePayload):
        for completion in payload.completions:
            observed, extra_reads, _, private = completion_observation(
                s,
                ctx,
                product.id,
                issue,
                row.purpose,
                completion,
                now,
            )
            if private and row.visibility != "private":
                raise DomainError("FORBIDDEN_SCOPE", "私有完成事实不能扩大问题受众。", 403)
            observations.append(observed)
            assessed = _assessment(
                s,
                ctx,
                product.id,
                runtime,
                basis,
                published,
                issue,
                completion,
                observed,
                write=write,
            )
            assessments.append(assessed)
            reads = merge_reads(reads, extra_reads, assessed.required_source_read_set)
            sources = union_sources(sources, assessed.sources)
            for source in assessed.sources:
                source_reads, _, private = check_source(s, ctx, product.id, source)
                if private and row.visibility != "private":
                    raise DomainError("FORBIDDEN_SCOPE", "完成政策私有来源不能扩受众。", 403)
                reads = merge_reads(reads, source_reads)
    actual, private = source_basis(s, ctx, product.id, reads)
    if (private or published["private"]) and row.visibility != "private":
        raise DomainError("FORBIDDEN_SCOPE", "完整后续来源不能扩共享受众。", 403)
    saved = row.source_basis.get("artifact_sources", [])
    previous, _ = source_basis(s, ctx, product.id, row.required_source_read_set)
    if not saved or saved != previous:
        raise DomainError("RECHECK_REQUIRED", "固定问题来源或安全epoch已变化。")
    if require_reads and merge_reads(command.source_read_set) != reads:
        raise DomainError("MISSING_REQUIRED_EVIDENCE", "后续命令须固定本次全部来源读集。")
    domain = _domain(payload)
    inv = Invocation(
        command_id=command.command_id,
        operation=command.operation,
        subject_id=payload.issue_id,
        expected_revision=payload.expected_issue_revision,
        semantic_digest=semantic_digest(domain),
        confirmation_token=getattr(payload, "confirmation_token", None),
    )
    bound = Bound(
        row,
        issue,
        row.purpose,
        runtime,
        authority,
        published,
        results,
        basis,
        tuple(observations),
        tuple(assessments),
        sources,
        reads,
        {
            "artifact_sources": actual,
            "result_proofs": [_stamp(v) for v in results],
            "followup_basis": basis.model_dump(mode="json"),
            "completion_assessments": [v.model_dump(mode="json") for v in assessments],
        },
        inv,
        domain,
        payload,
        write,
    )
    _refresh(s, ctx, product.id, command.operation, bound)
    return bound


def _refresh(s, ctx, pid, operation, bound):
    if _runtime(s) is not bound.runtime:
        raise DomainError("SOURCE_STALE", "后续宿主入口在核对期间已改变。")
    refresh = getattr(s.get_bind(), "_pdos_quality_result_refresh", None)
    if not callable(refresh):
        raise DomainError("INTEGRATION_REQUIRED", "全部原件读取后的原执行证明重核入口缺失。", 503)
    for completion, observation, saved in zip(
        getattr(bound.payload, "completions", ()),
        bound.observations,
        bound.assessments,
        strict=True,
    ):
        actual = _assessment(
            s,
            ctx,
            pid,
            bound.runtime,
            bound.basis,
            bound.policy,
            bound.issue,
            completion,
            observation,
            write=bound.write,
        )
        if actual != saved:
            raise DomainError("SOURCE_STALE", "完成核对政策/owner实施证明已改变。")
    actual, _ = source_basis(s, ctx, pid, bound.reads)
    if actual != bound.source_basis["artifact_sources"]:
        raise DomainError("SOURCE_STALE", "末端来源/原件安全状态已改变。")
    if policy.assess(s, ctx, pid, bound.issue.scope.project_id, bound.purpose) != bound.policy:
        raise DomainError("SOURCE_STALE", "当前风险政策或签发入口已经改变。")
    _human(s, ctx, pid, write=bound.write)
    # Completion/owner and source checks may perform I/O or revoke a runtime
    # issuer. Refresh all earlier fixed results AFTER those readers, not before.
    for saved in bound.results:
        value = refresh(s, ctx, pid, saved, write=bound.write)
        value = (
            value
            if isinstance(value, FixedQualityResult)
            else FixedQualityResult.model_validate(value)
        )
        if not value.current or _stamp(value) != _stamp(saved):
            raise DomainError("SOURCE_STALE", "全部完成/来源核对后原失败执行证明已改变。")
    authority = professional.assess(
        s,
        ctx,
        pid,
        bound.issue.scope.project_id,
        operation,
        bound.purpose,
        now(),
        write=bound.write,
    )
    if (
        authority != bound.authority
        or not authority.get("authorized")
        or not authority.get("qualified")
    ):
        raise DomainError("SOURCE_STALE", "全部原件核对后当前专业资格/签发epoch已改变。")
    at = now()
    if any(
        (value.valid_until is not None and value.valid_until <= at)
        or any(bound <= at for bound in value.time_constraints)
        for value in bound.assessments
    ):
        raise DomainError("SOURCE_STALE", "末端措施完成核对证明已到期。")
    if not professional.authority_time_current(authority, at):
        raise DomainError("SOURCE_STALE", "末端当前职责或实际资格已失效。")
    if not policy.policy_time_current(bound.policy, at):
        raise DomainError("SOURCE_STALE", "专业/政策核对结束时已过有效边界。")
    if _runtime(s) is not bound.runtime:
        raise DomainError("SOURCE_STALE", "末端宿主配置已撤回或改变。")


def _new_write(s, ctx, command, product, payload, bound):
    if command.expected_revision != product.revision:
        raise DomainError("VERSION_CONFLICT", "产品水位已改变。")
    pointer = s.scalar(
        select(QualityIssueCurrent)
        .where(
            QualityIssueCurrent.tenant_id == ctx.tenant_id,
            QualityIssueCurrent.product_id == product.id,
            QualityIssueCurrent.issue_id == payload.issue_id,
        )
        .with_for_update()
    )
    if pointer is None or (pointer.issue_version_id, pointer.issue_revision) != (
        bound.row.id,
        bound.row.revision,
    ):
        raise DomainError("VERSION_CONFLICT", "问题前版已变化；原历史仍保留。")
    return pointer


def _kernel(s, ctx, pid, bound, record, *, proof_id=None):
    authority = Authority(
        scope=bound.issue.scope,
        actor_id=ctx.requester_id,
        actor_kind="human",
        roles=tuple(bound.authority["roles"]),
        audience=bound.issue.audience,
        authorized=True,
        qualified=True,
        cancelled=False,
        now=now(),
    )
    inv = bound.invocation
    if proof_id is not None and inv.operation == ROOT_CAUSE:
        inv = inv.model_copy(update={"decision_id": proof_id})

    def check(scope, source):
        if scope != bound.issue.scope:
            raise DomainError("FORBIDDEN_SCOPE", "品质后续来源范围不匹配。", 403)
        if source not in union_sources(*(v.sources for v in bound.results)):
            check_source(s, ctx, pid, source)

    commands = TransactionCommands(authority, inv, bound.issue, record, proof_id)
    return kernel(commands, bound.results, check, bound.policy), inv


def _preview_issue(after, before):
    raw = after.model_dump(mode="json")
    for history in raw["history"][len(before.history) :]:
        history["at"] = None
    if before.root_cause is None and raw["root_cause"] is not None:
        raw["root_cause"]["at"] = None
    return raw


def _review(s, ctx, pid, bound):
    handler, inv = _kernel(s, ctx, pid, bound, lambda _: None)
    handler._authorize(handler.ports.commands.authority, inv.operation)
    preview, mutation = handler._prepare(
        handler.ports.commands.authority, inv, bound.domain_payload
    )
    return {
        "before": {str(bound.issue.id): bound.issue.model_dump(mode="json")},
        "after": {str(i.id): _preview_issue(i, bound.issue) for i in mutation.changes},
        "effect": EFFECT,
        "event_effect": mutation.event_name,
        "domain_preview": preview.model_dump(mode="json"),
        "completion_observations": [v.model_dump(mode="json") for v in bound.observations],
        "completion_assessments": [v.model_dump(mode="json") for v in bound.assessments],
        "received_at": None,
        "clock_basis": "server_on_save",
        "read_basis": {
            "scope": bound.issue.scope.model_dump(mode="json"),
            "purpose": bound.purpose,
            "authority": bound.authority,
            "policy": bound.policy,
            "source_basis": bound.source_basis,
            "read_set": bound.reads,
        },
        "effectiveness_decide": False,
        "issue_close": False,
    }


def validate(s, ctx, command, product, payload):
    _load(s, ctx, command, product, payload)


def preview_view(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, bound)
    return _review(s, ctx, product.id, bound)


def inputs(s, ctx, pid, command):
    cls = PAYLOADS.get(command.operation)
    if cls is None or command.product_id != pid:
        raise DomainError("FORBIDDEN_SCOPE", "后续输入动作或产品未匹配。", 403)
    product = _human(s, ctx, pid, write=True)
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


def apply(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    _new_write(s, ctx, command, product, payload, bound)
    proof_id = bound.runtime.consumed_proof(
        s,
        ctx,
        command,
        payload,
        tier="T2" if command.operation == ROOT_CAUSE else "T1",
    )
    if not isinstance(proof_id, UUID):
        raise DomainError("NAMED_APPROVAL_REQUIRED", "共同实际已消费证明无法核对。")
    saved = []

    def record(mutation):
        _refresh(s, ctx, product.id, command.operation, bound)
        final_proof = bound.runtime.consumed_proof(
            s,
            ctx,
            command,
            payload,
            tier="T2" if command.operation == ROOT_CAUSE else "T1",
        )
        if final_proof != proof_id:
            raise DomainError("SOURCE_STALE", "末端共同具名证明绑定已改变。")
        if len(mutation.changes) != 1 or mutation.insert_ids or mutation.deliveries:
            raise DomainError("INTEGRITY_MISMATCH", "后续动作仅追加现有一个问题版本。")
        next_issue = mutation.changes[0]
        if next_issue.id != bound.issue.id or next_issue.revision != bound.row.revision + 1:
            raise DomainError("INTEGRITY_MISMATCH", "问题变更未绑定原聚合前版。")
        basis = deepcopy(bound.source_basis)
        basis["shared_proof"] = {
            "id": str(proof_id),
            "tier": "T2" if command.operation == ROOT_CAUSE else "T1",
        }
        basis["completion_observations"] = [
            {"fact": v.model_dump(mode="json"), "received_at": now().isoformat()}
            for v in bound.observations
        ]
        row = bound.runtime.append_issue(
            s,
            ctx,
            product,
            bound.row,
            mutation,
            operation=command.operation,
            authority=bound.authority,
            policy_snapshot=bound.policy,
            required_source_read_set=bound.reads,
            source_basis=basis,
            input_snapshot=semantic(payload),
            intent_digest=_intent(ctx, command, payload),
            expected_issue_revision=payload.expected_issue_revision,
        )
        if (
            row.tenant_id != ctx.tenant_id
            or row.product_id != product.id
            or row.issue_id != next_issue.id
            or row.revision != next_issue.revision
            or row.issue_snapshot != next_issue.model_dump(mode="json")
        ):
            raise DomainError("INTEGRITY_MISMATCH", "共享追加未返回精确新问题版。")
        saved.append(row)
        return row

    handler, inv = _kernel(s, ctx, product.id, bound, record, proof_id=proof_id)
    handler.execute(inv, bound.domain_payload)
    return saved[0], "quality_issue", bound.row.visibility


def replay_subject(s, ctx, command, product, payload):
    bound = _load(s, ctx, command, product, payload)
    row = s.scalar(
        select(QualityIssueVersion).where(
            QualityIssueVersion.tenant_id == ctx.tenant_id,
            QualityIssueVersion.product_id == product.id,
            QualityIssueVersion.issue_id == payload.issue_id,
            QualityIssueVersion.operation == command.operation,
            QualityIssueVersion.writer_id == ctx.requester_id,
            QualityIssueVersion.intent_digest == _intent(ctx, command, payload),
        )
    )
    if row is not None:
        _snapshot(row)
        _refresh(s, ctx, product.id, command.operation, bound)
    return row


def _source_options(s, ctx, pid, sources):
    """Referenced readable lines only; no all-product source/instrument scan."""
    from pdos_next.domain.quality_execution.evidence import POSITION

    options = []
    for source in union_sources(sources)[:100]:
        match = POSITION.fullmatch(source.position) if source.kind == "artifact" else None
        if match is None:
            continue
        artifact = source_for(s, ctx, pid, source.id, source.revision)
        lines = artifact.content.splitlines()
        index = int(match[1]) - 1
        if index >= len(lines):
            raise DomainError("SOURCE_STALE", "已引用原文行不再存在。")
        options.append(
            {
                "artifact_id": str(artifact.id),
                "revision": artifact.revision,
                "title": artifact.title,
                "line": index + 1,
                "quote": lines[index],
                "source": source.model_dump(mode="json"),
            }
        )
    return options


def _read_row(s, ctx, pid, row, *, current):
    issue = _snapshot(row)
    reads = merge_reads(row.required_source_read_set)
    actual, _ = source_basis(s, ctx, pid, reads)
    options = _source_options(s, ctx, pid, row.sources) if current else []
    saved = row.source_basis.get("artifact_sources", [])
    state = "not_evaluated_historical" if saved and actual == saved else "needs_recheck"
    authorities, published, followup_basis = {}, None, None
    caps = {
        ROOT_CAUSE: False,
        COMPLETE: False,
        "quality.capa.effectiveness.decide": False,
        "quality.issue.close": False,
    }
    reasons = []
    runtime = getattr(s.get_bind(), "_pdos_quality_followup", None)
    if current and state != "needs_recheck" and not issue.needs_recheck and not issue.merged_into:
        state = "current"
        try:
            values = tuple(_result(s, ctx, pid, f, write=False) for f in issue.failures)
            if any(v.scope != issue.scope or v.purpose != row.purpose for v in values):
                raise DomainError("FORBIDDEN_SCOPE", "原失败不能跨固定项目或用途。", 403)
            if issue.capa is not None:
                followup_basis = _exact_basis(s, ctx, pid, row, results=values, write=False)
            published = policy.assess(s, ctx, pid, row.project_id, row.purpose)
            if published.get("private") and row.visibility != "private":
                raise DomainError("RECHECK_REQUIRED", "当前政策私有来源不能扩至共享问题。")
            reads = merge_reads(
                reads,
                *(v.required_source_read_set for v in values),
                published["required_source_read_set"],
            )
            grant = s.execute(
                select(Grant.can_write, Grant.expires_at).where(
                    Grant.tenant_id == ctx.tenant_id,
                    Grant.category_id == category_for_product(pid),
                    Grant.principal_id == ctx.requester_id,
                )
            ).one_or_none()
            writable = (
                grant is not None
                and grant.can_write is True
                and (grant.expires_at is None or grant.expires_at > now())
            )
            for op in PAYLOADS:
                authority = professional.assess(s, ctx, pid, row.project_id, op, row.purpose, now())
                authorities[op] = authority
                reads = merge_reads(reads, authority["required_source_read_set"])
                legal = issue.status == "actioning" and issue.capa is not None
                if op == ROOT_CAUSE:
                    legal &= issue.root_cause is None and "quality" in authority.get("roles", [])
                else:
                    legal &= (
                        any(
                            a.executor_id == ctx.requester_id and a.completion is None
                            for a in issue.capa.actions
                        )
                        if issue.capa
                        else False
                    )
                    legal &= isinstance(runtime, Runtime) and callable(
                        runtime.assess_action_completion
                    )
                caps[op] = bool(
                    legal
                    and writable
                    and isinstance(runtime, Runtime)
                    and authority.get("authorized") is True
                    and authority.get("qualified") is True
                )
            # Read capability is permission to present exact evidence, not an
            # assertion that any as-yet absent completion fact has passed.
            refresh = getattr(s.get_bind(), "_pdos_quality_result_refresh", None)
            if not callable(refresh):
                raise DomainError("INTEGRATION_REQUIRED", "原失败末端证明核对入口缺失。", 503)
            for value in values:
                fresh = refresh(s, ctx, pid, value, write=False)
                fresh = (
                    fresh
                    if isinstance(fresh, FixedQualityResult)
                    else FixedQualityResult.model_validate(fresh)
                )
                if not fresh.current or _stamp(fresh) != _stamp(value):
                    raise DomainError("SOURCE_STALE", "能力核对后原失败证明发生变化。")
            final_sources, _ = source_basis(s, ctx, pid, reads)
            if policy.assess(s, ctx, pid, row.project_id, row.purpose) != published:
                raise DomainError("SOURCE_STALE", "能力核对期间政策已变化。")
            for op, authority in authorities.items():
                final = professional.assess(s, ctx, pid, row.project_id, op, row.purpose, now())
                if final != authority:
                    raise DomainError("SOURCE_STALE", "能力核对期间专业事实已变化。")
            if source_basis(s, ctx, pid, reads)[0] != final_sources:
                raise DomainError("SOURCE_STALE", "能力核对结束时来源已变化。")
            if getattr(s.get_bind(), "_pdos_quality_followup", None) is not runtime:
                raise DomainError("SOURCE_STALE", "能力核对期间宿主配置变化。")
        except DomainError as exc:
            if exc.status == 403:
                raise
            state = "needs_recheck"
            caps = dict.fromkeys(caps, False)
            reasons.append(exc.code)
    if not isinstance(runtime, Runtime):
        reasons.append("INTEGRATION_REQUIRED")
    actions = [
        {
            "action_id": str(a.id),
            "executor_id": str(a.executor_id),
            "text": a.text,
            "completion": a.completion.model_dump(mode="json") if a.completion else None,
            "capabilities": {
                COMPLETE: bool(
                    caps[COMPLETE] and a.executor_id == ctx.requester_id and a.completion is None
                )
            },
            "can_prepare_completion": bool(
                caps[COMPLETE] and a.executor_id == ctx.requester_id and a.completion is None
            ),
            "can_complete": False,
            "completion_verified": None,
            "blockers": []
            if a.completion
            else [
                {
                    "code": "STRUCTURED_COMPLETION_REQUIRED",
                    "detail": "须提交本人实际完成整行原文，并核对调查政策/正式实施owner证明。",
                }
            ],
        }
        for a in (issue.capa.actions if issue.capa else ())
    ]
    return {
        "id": str(row.id),
        "issue_id": str(row.issue_id),
        "revision": row.revision,
        "project_id": str(row.project_id),
        "purpose": row.purpose,
        "owner_id": str(row.owner_id),
        "visibility": row.visibility,
        "status": row.status,
        "issue": issue.model_dump(mode="json"),
        "is_current": current,
        "source_status": state,
        "capabilities": caps,
        "authority": authorities,
        "policy": published,
        "required_source_read_set": reads,
        "sources": [r.model_dump(mode="json") for r in union_sources(row.sources)],
        "created_at": row.created_at.isoformat(),
        "reason": row.reason,
        "actions": actions,
        "reason_codes": reasons,
        "followup_basis": followup_basis.model_dump(mode="json") if followup_basis else None,
        "saved_followup_basis": row.source_basis.get("followup_basis"),
        "shared_proof": row.source_basis.get("shared_proof"),
        "completion_observations": row.source_basis.get("completion_observations", []),
        "source_options": options,
        "source_options_has_more": current and len(union_sources(row.sources)) > 100,
        "historical_root_cause_limit": "根因仅执行措施中可决定；全部完成后不能补办根因。",
    }


def list_quality_followup(s, ctx, pid, *, issue_id=None, revision=None, run_id=None, build_id=None):
    _human(s, ctx, pid)
    query = select(QualityIssueVersion).where(
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.product_id == pid,
    )
    mapping_more = False
    if issue_id is not None:
        query = query.where(QualityIssueVersion.issue_id == issue_id)
        if revision is not None:
            if type(revision) is not int or revision < 1:
                raise DomainError("INVALID_PAYLOAD", "问题版号须为严格正整数。", 422)
            query = query.where(QualityIssueVersion.revision == revision)
    elif revision is not None:
        raise DomainError("INVALID_PAYLOAD", "固定版号必须同时指定问题逻辑身份。", 422)
    elif run_id is not None or build_id is not None:
        target = select(QualityFailureMap.issue_id.label("issue_id")).where(
            QualityFailureMap.tenant_id == ctx.tenant_id,
            QualityFailureMap.product_id == pid,
        )
        original = select(QualityEventFailureLink.issue_id.label("issue_id")).where(
            QualityEventFailureLink.tenant_id == ctx.tenant_id,
            QualityEventFailureLink.product_id == pid,
        )
        if run_id is not None:
            target = target.where(QualityFailureMap.failure["run"]["id"].astext == str(run_id))
            original = original.where(QualityEventFailureLink.run_id == run_id)
        if build_id is not None:
            target = target.where(QualityFailureMap.failure["build"]["id"].astext == str(build_id))
            original = original.where(QualityEventFailureLink.build_id == build_id)
        identities = target.union(original).subquery()
        found = list(
            s.scalars(select(identities.c.issue_id).order_by(identities.c.issue_id).limit(101))
        )
        mapping_more = len(found) > 100
        query = query.where(QualityIssueVersion.issue_id.in_(found[:100]))
    else:
        return {
            "issues": [],
            "current_by_issue": {},
            "capabilities": {},
            "unavailable_count": 0,
            "has_more": False,
        }
    rows = list(
        s.scalars(
            query.order_by(QualityIssueVersion.created_at.desc(), QualityIssueVersion.id).limit(101)
        )
    )
    views, pointers, unavailable = [], {}, 0
    held = isinstance(s, Session) and s.info.get("read_snapshot")
    if held:
        from pdos_next.domain.quality_execution.service import read_current_rows

        selected_pointers = read_current_rows(s, ctx, pid, rows[:100])
    for row in rows[:100]:
        pointer = (
            selected_pointers.get(row.issue_id)
            if held
            else s.scalar(
                select(QualityIssueCurrent).where(
                    QualityIssueCurrent.tenant_id == ctx.tenant_id,
                    QualityIssueCurrent.product_id == pid,
                    QualityIssueCurrent.issue_id == row.issue_id,
                )
            )
        )
        current = bool(pointer and pointer.issue_version_id == row.id)
        try:
            if row.visibility == "private" and row.owner_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "私有问题不可读取。", 403)
            view = _read_row(s, ctx, pid, row, current=current)
            views.append(view)
            if current:
                pointers[str(row.issue_id)] = {
                    "issue_version_id": str(row.id),
                    "revision": row.revision,
                }
        except DomainError:
            unavailable += 1
    return {
        "issues": views,
        "current_by_issue": pointers,
        "capabilities": {op: any(v["capabilities"][op] for v in views) for op in PAYLOADS},
        "unavailable_count": unavailable,
        "has_more": mapping_more or len(rows) > 100,
    }
