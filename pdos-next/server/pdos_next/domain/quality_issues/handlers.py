"""Registry-callable handlers. Host owns one transaction/proof/receipt entry."""

from uuid import NAMESPACE_URL, UUID, uuid5

from pdos_next.errors import DomainError
from pdos_next.schemas.quality_issues.contracts import (
    ActionsComplete,
    Capa,
    CapaDraft,
    ContainmentRecord,
    EffectivenessDecide,
    EffectivenessDecision,
    History,
    Issue,
    IssueClose,
    IssueCreate,
    IssueMerge,
    IssueRecheck,
    IssueTriage,
    NamedConclusion,
    Ref,
    RootCauseDecide,
)

from .ports import Delivery, Invocation, Mutation, Ports, Preview
from .rules import (
    capa_draft_text_revisable,
    digest,
    failure_ref,
    issue_sources,
    replace,
    semantic_digest,
)

# Policy suggestions for noncanonical actions require explicit host registration.
OPERATIONS = {
    "quality.issue.create": (IssueCreate, "T0", False, "issue.created"),
    "quality.issue.merge": (IssueMerge, "T1", False, "issues.merged"),
    "quality.issue.triage": (IssueTriage, "T1", True, "issue.triaged"),
    "quality.issue.containment.record": (ContainmentRecord, "T1", True, "issue.contained"),
    "quality.issue.root_cause.decide": (RootCauseDecide, "T2", True, "issue.root_cause_decided"),
    "quality.capa.draft": (CapaDraft, "T0", False, "capa.drafted"),
    "quality.capa.actions.complete": (ActionsComplete, "T1", True, "capa.actions_completed"),
    "quality.capa.effectiveness.decide": (
        EffectivenessDecide,
        "T2",
        True,
        "capa.effectiveness_decided",
    ),
    "quality.issue.recheck": (IssueRecheck, "T1", True, "issue.recheck_recorded"),
    "quality.issue.close": (IssueClose, "T2", True, "issue.closed"),
}
CANONICAL_OPERATIONS = frozenset(
    {
        "quality.issue.create",
        "quality.issue.merge",
        "quality.capa.draft",
        "quality.capa.effectiveness.decide",
    }
)


class QualityIssueHandler:
    def __init__(self, ports: Ports):
        self.ports = ports

    def _port(self, name):
        value = getattr(self.ports, name)
        methods = {
            "commands": ("context", "begin", "replay", "issue", "by_failure", "confirm", "record"),
            "runs": ("fixed", "original", "delivery", "currentness"),
            "policies": ("assess", "verification"),
            "evidence": ("check", "currentness"),
        }[name]
        if value is None or any(not callable(getattr(value, method, None)) for method in methods):
            raise DomainError("INTEGRATION_REQUIRED", f"{name}完整受控接口待主线接入。", 503)
        return value

    def _authorize(self, authority, operation):
        if authority.now.tzinfo is None or authority.now.utcoffset() is None:
            raise DomainError("INVALID_AUTHORITY", "服务器时间必须含时区。", 503)
        if authority.cancelled:
            raise DomainError("RUN_CANCELLED", "当前运行已取消。")
        if not authority.authorized or not {"quality", "engineering", "test"} & set(
            authority.roles
        ):
            raise DomainError("FORBIDDEN_OPERATION", "当前范围/职责未获授权。", 403)
        if not authority.qualified:
            raise DomainError("QUALIFICATION_REQUIRED", "当前能力/专业资格未满足。", 403)
        _, tier, human, _ = OPERATIONS[operation]
        if (human or tier == "T2") and authority.actor_kind != "human":
            raise DomainError("NAMED_DECISION_REQUIRED", "该动作须当前具名人办理。", 403)
        if tier == "T2" and "quality" not in authority.roles:
            raise DomainError("FORBIDDEN_OPERATION", "品质专业决定须品质职责。", 403)

    def _parse(self, operation, payload):
        entry = OPERATIONS.get(operation)
        if entry is None:
            raise DomainError("INVALID_OPERATION", "未登记本包动作。", 422)
        return entry[0].model_validate(payload)

    def _issue(self, authority, issue_id):
        issue = self._port("commands").issue(authority.scope, issue_id)
        if issue.scope != authority.scope or not set(issue.audience) <= set(authority.audience):
            raise DomainError("FORBIDDEN_SCOPE", "问题范围或受众不可访问。", 403)
        return issue

    def _source(self, authority, source):
        self._port("evidence").check(authority.scope, source, "quality.issue")

    def _current(self, authority, issue, *, allow_stale=False):
        assessments = tuple(
            self._port("runs").currentness(authority.scope, f) for f in issue.failures
        )
        # Normal actions inspect each exact direct reference once. Recheck keeps
        # repeated assessments so its existing diagnostic sequence is unchanged.
        for source in issue_sources(issue, distinct=not allow_stale):
            assessments += (
                self._port("evidence").currentness(authority.scope, source, "quality.issue"),
            )
        if not allow_stale and (issue.needs_recheck or any(not a.current for a in assessments)):
            raise DomainError("RECHECK_REQUIRED", "来源/配置/判断待重核，原事实保留。")
        return assessments

    def _completion(self, authority, completion):
        if completion.executor_id != authority.actor_id:
            raise DomainError(
                "NAMED_EXECUTOR_REQUIRED", "完成记录须本人具名，不能代填执行事实。", 403
            )
        if completion.at.occurred_at > authority.now:
            raise DomainError("INVALID_EVENT_TIME", "已执行措施不能用未来时间。", 422)
        self._source(authority, completion.at.source)
        for source in completion.evidence:
            self._source(authority, source)

    def _verification(self, authority, issue, payload, policy):
        capa = issue.capa
        if not capa or any(a.completion is None for a in capa.actions):
            raise DomainError("ACTIONS_INCOMPLETE", "措施未齐，不可决定有效性。")
        requirement = capa.requirement
        if authority.now < requirement.observation_until:
            raise DomainError("OBSERVATION_PENDING", "规定观察期尚未完成。")
        evidence = tuple(
            self._port("policies").verification(authority, eid, issue)
            for eid in payload.evidence_ids
        )
        if any(e.id != eid for e, eid in zip(evidence, payload.evidence_ids, strict=True)):
            raise DomainError("INVALID_VERIFICATION", "验证引用身份不一致。")
        participants = {f.executor_id for f in issue.failures}
        participants |= {a.executor_id for a in capa.actions}
        participants |= {c.executor_id for c in issue.containment}
        if issue.root_cause:
            participants.add(issue.root_cause.actor_id)
        participants |= {x for e in evidence for x in e.executor_ids}
        if authority.actor_id in participants:
            raise DomainError("INDEPENDENCE_REQUIRED", "执行者/根因决定者不可自证有效。", 403)
        original_runs = {f.run.id for f in issue.failures}
        natures = {f.nature for f in issue.failures}
        failure_natures = {f.identity: f.nature for f in issue.failures}
        completion_at = max(a.completion.at.occurred_at for a in capa.actions)
        requirement_digest = semantic_digest(requirement)
        for e in evidence:
            if (
                e.requirement_digest != requirement_digest
                or e.observed_from.tzinfo is None
                or e.observed_from < completion_at
                or e.observed_from > e.observed_until
            ):
                raise DomainError("INVALID_VERIFICATION", "须按本次CAPA要求在措施完成后复核。")
            if not e.current or not e.applicable or not e.sources or not e.run_ids:
                raise DomainError("INVALID_VERIFICATION", "需要当前、适用的具名固定新结果。")
            if e.observed_until.tzinfo is None or e.observed_until < requirement.observation_until:
                raise DomainError("OBSERVATION_PENDING", "复核证据未覆盖规定观察期。")
            if e.observed_until > authority.now:
                raise DomainError("INVALID_VERIFICATION", "未来观察不构成有效性证据。")
            if any(
                fid in failure_natures and failure_natures[fid] != e.nature for fid in e.failure_ids
            ):
                raise DomainError(
                    "INVALID_VERIFICATION", "证据不得把合成失败与现实失败混为同一依据。"
                )
            if original_runs & set(e.run_ids) or e.nature not in natures:
                raise DomainError("INVALID_VERIFICATION", "不得复用原失败Run或混用合成/现实依据。")
            if e.verifier_id in participants:
                raise DomainError(
                    "INDEPENDENCE_REQUIRED", "验证人员必须独立于整改与测试执行者。", 403
                )
            if policy.independent_verification or policy.risk in {"high", "critical"}:
                if e.verifier_id != authority.actor_id:
                    raise DomainError("INDEPENDENCE_REQUIRED", "本政策须独立复核人本人决定。", 403)
            for source in e.sources:
                self._source(authority, source)
        covered = {f for e in evidence for f in e.failure_ids}
        required = set(requirement.required_failure_ids)
        if covered != required or required != {f.identity for f in issue.failures}:
            raise DomainError("INCOMPLETE_VERIFICATION", "独立证据必须精确覆盖全部原失败范围。")
        if payload.result == "effective" and any(e.result != "pass" for e in evidence):
            raise DomainError("NOT_EFFECTIVE", "不确定/失败证据不能决定有效。")
        if payload.result == "ineffective" and not any(e.result == "fail" for e in evidence):
            raise DomainError("NOT_EFFECTIVE", "无确定失败不能声明无效；未知须待输入。")
        read_digest = digest(
            {
                "failures": [f.model_dump(mode="json") for f in issue.failures],
                "capa": capa.model_dump(
                    mode="json", exclude={"effectiveness", "effectiveness_history"}
                ),
                "root": issue.root_cause.model_dump(mode="json") if issue.root_cause else None,
                "containment": [c.model_dump(mode="json") for c in issue.containment],
                "policy": policy.model_dump(mode="json"),
                "evidence": [e.model_dump(mode="json") for e in evidence],
            }
        )
        return evidence, read_digest

    def preview(self, operation: str, subject_id: UUID, expected_revision: int, payload) -> Preview:
        payload = self._parse(operation, payload)
        authority = self._port("commands").context(operation, subject_id)
        self._authorize(authority, operation)
        inv = Invocation(
            command_id=UUID(int=0),
            operation=operation,
            subject_id=subject_id,
            expected_revision=expected_revision,
            semantic_digest=semantic_digest(payload),
        )
        preview, _ = self._prepare(authority, inv, payload)
        return preview

    def execute(self, invocation: Invocation, payload):
        payload = self._parse(invocation.operation, payload)
        if invocation.semantic_digest != semantic_digest(payload):
            raise DomainError("PAYLOAD_DIGEST_MISMATCH", "载荷不匹配。", 422)
        authority = self._port("commands").begin(invocation)
        self._authorize(authority, invocation.operation)
        replay = self._port("commands").replay(invocation, authority)
        if replay is not None:
            issue = self._issue(authority, replay.subject_id)
            self._current(authority, issue, allow_stale=isinstance(payload, IssueRecheck))
            return replace(replay, replayed=True)
        preview, mutation = self._prepare(authority, invocation, payload)
        if OPERATIONS[invocation.operation][1] != "T0":
            self._port("commands").confirm(invocation, preview, authority)
        return self._port("commands").record(invocation, mutation)

    def _prepare(self, authority, inv, payload):
        changes, before, inserts, deliveries, differences, evidence_read = (), (), (), (), (), ()
        policy = None
        if isinstance(payload, IssueCreate):
            if inv.expected_revision != 0 or inv.subject_id != payload.run_id:
                raise DomainError("INVALID_TARGET", "建单目标为权威Run，领域前版为0。", 422)
            verified = self._port("runs").fixed(authority.scope, payload.run_id)
            if verified.run.scope != authority.scope or verified.run.id != payload.run_id:
                raise DomainError("FORBIDDEN_SCOPE", "Run范围不匹配。", 403)
            failure = failure_ref(verified, payload.measurement_id)
            self._port("runs").delivery(authority.scope, payload.event_id, failure)
            assessment = self._port("runs").currentness(authority.scope, failure)
            if not assessment.current:
                raise DomainError("RECHECK_REQUIRED", "失败来源当前不可用于新建单。")
            for source in (failure.source, failure.method, failure.criterion):
                self._source(authority, source)
            issue = self._port("commands").by_failure(authority.scope, failure.identity)
            if issue is not None:
                issue = self._issue(authority, issue.id)
                # Current original sources need not retain the latest unrelated Run revision.
                old_assessments = self._current(authority, issue, allow_stale=True)
                reasons = tuple(r for a in old_assessments if not a.current for r in a.reasons)
                if any(not a.current for a in old_assessments):
                    reasons = reasons or ("原失败依据已变化，待重核。",)
                    before = (Ref(id=issue.id, revision=issue.revision),)
                    issue = self._updated(
                        issue,
                        authority,
                        inv,
                        "重复失败来源变化，保留原依据。",
                        needs_recheck=True,
                        recheck_reasons=reasons,
                    )
                    changes = (issue,)
                differences = ("重复失败映射原问题；不覆盖原标题、测量、配置或决定。",)
            else:
                issue = Issue(
                    id=uuid5(NAMESPACE_URL, "pdos-quality-failure:" + failure.identity),
                    revision=1,
                    scope=authority.scope,
                    audience=authority.audience,
                    title=payload.title,
                    failures=(failure,),
                    history=(self._history(authority, inv, "固定实测失败建单。"),),
                )
                changes, inserts = (issue,), (issue.id,)
            deliveries = (
                Delivery(
                    event_id=payload.event_id,
                    failure_identity=failure.identity,
                    issue_id=issue.id,
                    observed=failure,
                ),
            )
            read_issues = (issue,)
        else:
            issue = self._issue(authority, inv.subject_id)
            if issue.revision != inv.expected_revision:
                raise DomainError("REVISION_CONFLICT", "问题版本已变化。")
            if issue.merged_into:
                raise DomainError("MERGED_ALIAS", "原单保留；请在关联主问题办理。")
            if issue.status == "closed" and not isinstance(payload, IssueRecheck):
                raise DomainError("INVALID_STATE", "已关闭问题只能记录来源重核要求。")
            assessments = self._current(
                authority, issue, allow_stale=isinstance(payload, IssueRecheck)
            )
            policy = self._port("policies").assess(authority, issue.failures)
            before = (Ref(id=issue.id, revision=issue.revision),)
            read_issues = (issue,)
            updates = {}
            if isinstance(payload, IssueMerge):
                originals = tuple(self._issue(authority, r.id) for r in payload.sources)
                if issue.id in {o.id for o in originals}:
                    raise DomainError("MERGE_CONFLICT", "不能与自身归并。")
                for original, ref in zip(originals, payload.sources, strict=True):
                    self._current(authority, original)
                    if original.revision != ref.revision:
                        raise DomainError("REVISION_CONFLICT", "原问题版本已变化。")
                    if set(original.audience) != set(issue.audience) or original.merged_into:
                        raise DomainError("MERGE_CONFLICT", "受众变化或已有归并冲突。")
                    if (
                        original.status not in {"open", "triaged"}
                        or original.capa
                        or original.root_cause
                    ):
                        raise DomainError("MERGE_CONFLICT", "已有整改/专业判断不可直接归并。")
                if issue.status not in {"open", "triaged"} or issue.capa or issue.root_cause:
                    raise DomainError("MERGE_CONFLICT", "已有整改/专业判断须独立办理。")
                failures = tuple(
                    sorted(
                        issue.failures + tuple(f for o in originals for f in o.failures),
                        key=lambda f: f.identity,
                    )
                )
                if len({f.identity for f in failures}) != len(failures):
                    raise DomainError("MERGE_CONFLICT", "重复稳定失败身份须先对账。")
                aliases = tuple(
                    sorted(
                        set(
                            issue.aliases
                            + tuple(o.id for o in originals)
                            + tuple(a for o in originals for a in o.aliases)
                        ),
                        key=str,
                    )
                )
                updates = {
                    "failures": failures,
                    "aliases": aliases,
                    "containment": issue.containment
                    + tuple(c for o in originals for c in o.containment),
                    "needs_recheck": True,
                    "recheck_reasons": ("归并范围变化，风险与判断待重核。",),
                }
                policy = self._port("policies").assess(authority, failures)
                changes = tuple(
                    self._updated(o, authority, inv, payload.reason, merged_into=issue.id)
                    for o in originals
                )
                before += tuple(Ref(id=o.id, revision=o.revision) for o in originals)
                read_issues += originals
                differences = tuple(
                    f"保留原问题 {o.id} v{o.revision} / {len(o.failures)}个独立失败。"
                    for o in originals
                ) + ("范围并集；不删除原问题及历史。",)
            elif isinstance(payload, IssueTriage):
                if issue.status != "open":
                    raise DomainError("INVALID_STATE", "仅开放问题可分诊。")
                updates = {"status": "triaged", "risk": policy.risk}
            elif isinstance(payload, ContainmentRecord):
                if issue.status not in {"triaged", "actioning"}:
                    raise DomainError("INVALID_STATE", "先分诊再记录遏制。")
                self._completion(authority, payload.action)
                if payload.action.id in {c.id for c in issue.containment}:
                    raise DomainError("ACTION_CONFLICT", "遏制身份已记录，不覆盖。")
                updates = {
                    "status": "actioning",
                    "containment": issue.containment + (payload.action,),
                }
            elif isinstance(payload, RootCauseDecide):
                if issue.status != "actioning" or issue.root_cause is not None:
                    raise DomainError("INVALID_STATE", "根因结论不覆盖已有具名决定。")
                for source in payload.sources:
                    self._source(authority, source)
                updates = {
                    "root_cause": NamedConclusion(
                        text=payload.text,
                        sources=payload.sources,
                        actor_id=authority.actor_id,
                        at=authority.now,
                    )
                }
            elif isinstance(payload, CapaDraft):
                if issue.status not in {"triaged", "actioning"} or (
                    issue.capa is not None and not capa_draft_text_revisable(issue)
                ):
                    raise DomainError("INVALID_STATE", "需分诊；仅未决CAPA草稿可作文本续版。")
                if issue.capa is not None:
                    previous = issue.capa
                    if (
                        payload.capa_id != previous.id
                        or payload.hypotheses != previous.hypotheses
                        or payload.requirement != previous.requirement
                        or tuple(a.model_dump(exclude={"text"}) for a in payload.actions)
                        != tuple(a.model_dump(exclude={"text"}) for a in previous.actions)
                    ):
                        raise DomainError(
                            "INVALID_CAPA_REVISION", "草稿续版仅可更改原措施文本。", 422
                        )
                    if payload.actions == previous.actions:
                        raise DomainError("NO_CHANGES", "草稿措施文本未改变。")
                if set(payload.requirement.required_failure_ids) != {
                    f.identity for f in issue.failures
                }:
                    raise DomainError("INVALID_CAPA_SCOPE", "复核要求须精确覆盖所有失败。", 422)
                for hypothesis in payload.hypotheses:
                    for source in hypothesis.sources:
                        self._source(authority, source)
                updates = {
                    "status": "actioning",
                    "capa": replace(issue.capa, actions=payload.actions)
                    if issue.capa is not None
                    else Capa(
                        id=payload.capa_id,
                        hypotheses=payload.hypotheses,
                        actions=payload.actions,
                        requirement=payload.requirement,
                    ),
                }
            elif isinstance(payload, ActionsComplete):
                if issue.status != "actioning" or issue.capa is None:
                    raise DomainError("INVALID_STATE", "需已有CAPA措施。")
                actions = {a.id: a for a in issue.capa.actions}
                for completion in payload.completions:
                    action = actions.get(completion.id)
                    if (
                        not action
                        or action.completion
                        or action.executor_id != completion.executor_id
                    ):
                        raise DomainError("ACTION_CONFLICT", "未知/已完成措施或执行者不一致。")
                    self._completion(authority, completion)
                    actions[action.id] = replace(action, completion=completion)
                capa = replace(issue.capa, actions=tuple(actions[a.id] for a in issue.capa.actions))
                updates = {
                    "capa": capa,
                    "status": "awaiting_verification"
                    if all(a.completion for a in capa.actions)
                    else "actioning",
                }
            elif isinstance(payload, EffectivenessDecide):
                if issue.status != "awaiting_verification" or issue.root_cause is None:
                    raise DomainError("INVALID_STATE", "需待验证且已有具名根因结论。")
                evidence_read, read_digest = self._verification(authority, issue, payload, policy)
                decision = EffectivenessDecision(
                    text=payload.text,
                    actor_id=authority.actor_id,
                    at=authority.now,
                    sources=tuple(s for e in evidence_read for s in e.sources),
                    result=payload.result,
                    evidence_ids=payload.evidence_ids,
                    policy=policy.ref,
                    read_digest=read_digest,
                )
                updates = {
                    "capa": replace(
                        issue.capa,
                        effectiveness=decision,
                        effectiveness_history=issue.capa.effectiveness_history + (decision,),
                    )
                }
                # Ineffective remains awaiting_verification; subsequent measures need
                # a separately registered revision command, never automatic closure.
            elif isinstance(payload, IssueClose):
                decision = issue.capa.effectiveness if issue.capa else None
                if (
                    issue.status != "awaiting_verification"
                    or not decision
                    or decision.result != "effective"
                ):
                    raise DomainError(
                        "EFFECTIVENESS_REQUIRED", "有效性决定通过后才能独立具名关闭。"
                    )
                if decision.actor_id != authority.actor_id:
                    raise DomainError(
                        "NAMED_DECISION_REQUIRED", "关闭须由独立有效性复核人本人办理。", 403
                    )
                verification = EffectivenessDecide(
                    result=decision.result, text=decision.text, evidence_ids=decision.evidence_ids
                )
                evidence_read, read_digest = self._verification(
                    authority, issue, verification, policy
                )
                if read_digest != decision.read_digest or policy.ref != decision.policy:
                    raise DomainError("RECHECK_REQUIRED", "有效性内容/证据/政策已变化。")
                updates = {
                    "status": "closed",
                    "closure": NamedConclusion(
                        text=payload.text,
                        actor_id=authority.actor_id,
                        at=authority.now,
                        sources=decision.sources,
                    ),
                }
            else:
                reasons = tuple(r for a in assessments if not a.current for r in a.reasons)
                stale = any(not a.current for a in assessments)
                if issue.status == "closed":
                    # Historical closure survives. Current applicability is separately stale.
                    stale = stale or issue.needs_recheck
                updates = {
                    "needs_recheck": stale,
                    "risk": policy.risk if issue.status != "open" else issue.risk,
                    "recheck_reasons": reasons or (("固定来源需重核。",) if stale else ()),
                }
            note = (
                getattr(payload, "reason", None) or getattr(payload, "text", None) or inv.operation
            )
            issue = self._updated(issue, authority, inv, note, **updates)
            changes = (issue,) + changes
        preview_digest = digest(
            {
                "operation": inv.operation,
                "subject": str(inv.subject_id),
                "expected_revision": inv.expected_revision,
                "payload": semantic_digest(payload),
                "scope": authority.scope.model_dump(mode="json"),
                "actor": str(authority.actor_id),
                "audience": authority.audience,
                "issues": [i.model_dump(mode="json", exclude={"history"}) for i in read_issues],
                "policy": policy.model_dump(mode="json") if policy else None,
                "evidence": [e.model_dump(mode="json") for e in evidence_read],
            }
        )
        # New Issue uses dynamic audit time; remove it from confirmation read set above.
        preview = Preview(
            operation=inv.operation,
            subject_id=inv.subject_id,
            expected_revision=inv.expected_revision,
            payload_digest=semantic_digest(payload),
            digest=preview_digest,
            failures=issue.failures,
            issues=tuple(Ref(id=i.id, revision=i.revision) for i in read_issues),
            policy=policy,
            differences=differences,
            effect="保存固定范围与原始历史；不替代工程变更或新Build/Run。",
        )
        mutation = Mutation(
            changes=changes,
            before=before,
            insert_ids=inserts,
            deliveries=deliveries,
            event_name=(
                "issue.recheck_required"
                if changes and not inserts
                else None
                if not changes
                else "issue.created"
            )
            if isinstance(payload, IssueCreate)
            else OPERATIONS[inv.operation][3],
            preview_digest=preview_digest,
        )
        return preview, mutation

    @staticmethod
    def _history(authority, inv, note):
        return History(
            command_id=inv.command_id,
            operation=inv.operation,
            actor_id=authority.actor_id,
            actor_kind=authority.actor_kind,
            at=authority.now,
            note=note,
        )

    def _updated(self, issue, authority, inv, note, **changes):
        return replace(
            issue,
            revision=issue.revision + 1,
            history=issue.history + (self._history(authority, inv, note),),
            **changes,
        )
