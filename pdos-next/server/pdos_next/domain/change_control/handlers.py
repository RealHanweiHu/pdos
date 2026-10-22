"""Registry-callable command participant; host owns Session, proof and commit."""

from pdos_next.clock import deadline_current
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import (
    Approval,
    ChangeOrder,
    ChangeRequest,
    Close,
    EffectivityRecord,
    History,
    ImpactCompute,
    ImplementationRecord,
    NamedRecord,
    OrderApprove,
    OrderPrepare,
    Recheck,
    Ref,
    RequestCreate,
    Verification,
    VerificationRecord,
)

from .ports import Invocation, Mutation, Ports, Preview
from .rules import (
    EFFECTS,
    compute_impact,
    digest,
    fully_effective,
    graph_sources,
    identity,
    replace,
)

OPERATIONS = {
    "change.request.create": (RequestCreate, "T0", "change.requested"),
    "change.impact.compute": (ImpactCompute, "T0", "change.impact_created"),
    "change.order.approve": (OrderApprove, "T2", "change.approved"),
    "change.implementation.record": (ImplementationRecord, "T1", "change.implementation_recorded"),
    # Candidates only: public registration/permissions/schema remain mainline-owned.
    "change.request.revise": (RequestCreate, "T1", "change.request_revised"),
    "change.order.prepare": (OrderPrepare, "T1", "change.order_prepared"),
    "change.effectivity.record": (EffectivityRecord, "T1", "change.effectivity_recorded"),
    "change.verification.record": (VerificationRecord, "T2", "change.verification_recorded"),
    "change.close": (Close, "T2", "change.closed"),
    "change.recheck": (Recheck, "T1", "change.recheck_required"),
}
CANONICAL_OPERATIONS = frozenset(
    {
        "change.request.create",
        "change.impact.compute",
        "change.order.approve",
        "change.implementation.record",
    }
)


class ChangeControlHandler:
    def __init__(self, ports: Ports):
        self.ports = ports

    def _port(self, name):
        value = getattr(self.ports, name)
        methods = {
            "commands": ("context", "begin", "replay", "request", "confirm", "record"),
            "facts": (
                "audience",
                "ref",
                "source",
                "currentness",
                "graph",
                "selection",
                "implementation",
                "effectivity",
                "verification",
            ),
            "policies": ("assess",),
        }[name]
        if value is None or any(not callable(getattr(value, m, None)) for m in methods):
            raise DomainError("INTEGRATION_REQUIRED", f"{name}完整受控端口待接入。", 503)
        return value

    def _parse(self, operation, payload):
        if operation not in OPERATIONS:
            raise DomainError("INVALID_OPERATION", "本包未登记该动作。", 422)
        return OPERATIONS[operation][0].model_validate(payload)

    def _authorize(self, authority, operation):
        if authority.cancelled:
            raise DomainError("RUN_CANCELLED", "当前运行已取消。")
        if not authority.authorized or not set(authority.roles) & {
            "engineering",
            "manufacturing",
            "quality",
            "customer",
            "regulatory",
        }:
            raise DomainError("FORBIDDEN_OPERATION", "当前范围或专业职责未授权。", 403)
        if not authority.qualified:
            raise DomainError("QUALIFICATION_REQUIRED", "现行能力或专业资格未满足。", 403)
        tier = OPERATIONS[operation][1]
        if tier in {"T1", "T2"} and authority.actor_kind != "human":
            raise DomainError("NAMED_HUMAN_REQUIRED", "该记录/决定须当前具名人办理。", 403)

    def _request(self, uow, authority, subject_id):
        request = self._port("commands").request(uow, authority.scope, subject_id)
        if (
            request.id != subject_id
            or request.scope != authority.scope
            or not set(request.audience) <= set(authority.audience)
        ):
            raise DomainError("FORBIDDEN_SCOPE", "对象、租户/项目范围或受众不匹配。", 403)
        return request

    def _ref(self, uow, authority, ref):
        result = self._port("facts").ref(uow, authority, ref)
        if result != ref:
            raise DomainError("FIXED_REFERENCE_MISMATCH", "端口必须返回精确固定引用。")
        return self._port("facts").currentness(uow, authority, ref)

    def _source(self, uow, authority, source):
        return self._port("facts").source(uow, authority, source)

    def _policy(self, uow, authority, request, *, require_current=True):
        policy = self._port("policies").assess(uow, authority, request)
        if not {"engineering", "manufacturing"} <= set(policy.required_disciplines) or (
            len(set(policy.required_disciplines)) != len(policy.required_disciplines)
        ):
            raise DomainError("INVALID_POLICY", "双专业决定政策须完整且不重复。", 503)
        if require_current and not self._source(uow, authority, policy.source).current:
            raise DomainError("RECHECK_REQUIRED", "当前政策来源待重核。")
        return policy

    def _fixed_graph(self, uow, authority, snapshot):
        statuses = [
            self._ref(
                uow,
                authority,
                Ref(id=snapshot.id, revision=snapshot.revision, kind="graph_snapshot"),
            )
        ]
        if snapshot.scope != authority.scope or not set(snapshot.audience) <= set(
            authority.audience
        ):
            raise DomainError("FORBIDDEN_SCOPE", "影响图范围/受众不可访问。", 403)
        self._port("facts").audience(
            uow,
            authority,
            snapshot.audience,
            tuple(n.ref for n in snapshot.nodes),
            graph_sources(snapshot),
        )
        for node in snapshot.nodes:
            if node.scope != authority.scope or not set(node.audience) <= set(authority.audience):
                raise DomainError("FORBIDDEN_SCOPE", "依赖节点范围/受众不可访问。", 403)
            statuses.append(self._ref(uow, authority, node.ref))
        statuses += [self._source(uow, authority, s) for s in graph_sources(snapshot)]
        return statuses

    def _current(self, uow, authority, request, *, include_assessment=True):
        """ACL checked even on stale history. Return reasons; callers choose block."""
        reasons = list(request.recheck_reasons) if request.needs_recheck else []
        self._port("facts").audience(
            uow,
            authority,
            request.audience,
            (*request.roots, *request.references),
            request.sources,
        )
        checks = [self._ref(uow, authority, r) for r in (*request.roots, *request.references)]
        checks += [self._source(uow, authority, s) for s in request.sources]
        if include_assessment and request.assessments and request.status != "draft":
            a = request.assessments[-1]
            checks += self._fixed_graph(uow, authority, a.graph)
            checks += [self._source(uow, authority, s) for h in a.hypotheses for s in h.sources]
            if not deadline_current(a.graph.expires_at, authority.now):
                reasons.append("影响来源快照已过期。")
        if request.orders and request.status not in {"draft", "analysis"}:
            order = request.orders[-1]
            policy = self._policy(uow, authority, request, require_current=False)
            if order.policy != policy.source or (
                set(order.required_disciplines) != set(policy.required_disciplines)
            ):
                reasons.append("决定政策/所需专业范围已变化。")
            checks.append(self._source(uow, authority, order.policy))
            if not deadline_current(order.plan.expires_at, authority.now):
                reasons.append("生效计划已过期。")
            self._port("facts").audience(
                uow,
                authority,
                request.audience,
                tuple(r for i in order.plan.items for r in (*i.selection.objects, *i.intent.basis)),
                tuple(s for i in order.plan.items for s in i.selection.sources),
            )
            for disposition in order.plan.dispositions:
                checks.append(self._ref(uow, authority, disposition.object))
                checks += [self._source(uow, authority, s) for s in disposition.sources]
            for item in order.plan.items:
                self._port("facts").selection(uow, authority, item)
                checks += [
                    self._ref(uow, authority, r)
                    for r in (*item.selection.objects, *item.intent.basis)
                ]
                checks += [self._source(uow, authority, s) for s in item.selection.sources]
            for approval in order.approvals:
                checks += [self._source(uow, authority, s) for s in approval.sources]
                if not deadline_current(approval.expires_at, authority.now):
                    reasons.append(f"{approval.discipline}批准已过期。")
            for fact in (*order.implementations, *order.effectivity):
                item = self._item(order, fact.item_id)
                if hasattr(fact, "outputs"):
                    actual = self._port("facts").implementation(
                        uow, authority, fact.id, order, item
                    )
                else:
                    actual = self._port("facts").effectivity(uow, authority, fact.id, order, item)
                if actual != fact:
                    reasons.append("实施或实际生效事实已更正/变化，原回执保留。")
                checks += [self._source(uow, authority, s) for s in fact.sources]
                outputs = fact.outputs if hasattr(fact, "outputs") else fact.output_refs
                checks += [self._ref(uow, authority, r) for r in outputs]
            for verification in order.verifications:
                checks += [self._source(uow, authority, s) for s in verification.sources]
                checks += [self._source(uow, authority, s) for s in verification.fact.sources]
                checks += [self._ref(uow, authority, r) for r in verification.fact.output_refs]
                checked = self._port("facts").verification(
                    uow,
                    authority,
                    verification.fact.id,
                    order,
                )
                if checked != verification.fact or not checked.current or not checked.applicable:
                    reasons.append("独立复核依据/适用性已变化。")
        for check in checks:
            if not check.current:
                reasons += list(check.reasons) or ["固定来源或配置已变化/撤回。"]
        return tuple(dict.fromkeys(reasons))

    def _require_current(self, uow, authority, request, *, include_assessment=True):
        reasons = self._current(uow, authority, request, include_assessment=include_assessment)
        if reasons or request.needs_recheck:
            raise DomainError("RECHECK_REQUIRED", "；".join(reasons) or "当前变更待显式重核。")

    def _order(self, request):
        if not request.orders:
            raise DomainError("ORDER_REQUIRED", "尚无固定变更令。")
        return request.orders[-1]

    def _item(self, order, item_id):
        item = next((i for i in order.plan.items if i.id == item_id), None)
        if item is None:
            raise DomainError("INVALID_EFFECTIVITY_ITEM", "实施项不在批准范围。", 422)
        return item

    def _state(self, request, allowed):
        if request.status not in allowed:
            raise DomainError("INVALID_STATE", f"{request.status}不能办理该动作。")

    def _fact(self, uow, authority, fact, expected_id, item, order, request, *, effectivity=False):
        if fact.id != expected_id or fact.item_id != item.id or fact.intent_id != item.intent.id:
            raise DomainError("FACT_BINDING_MISMATCH", "事实不属于固定实施意图/范围。")
        if fact.nature != self._assessment(order, request).graph.nature:
            raise DomainError("FACT_NATURE_MISMATCH", "合成/真实事实不可混用。")
        if (
            fact.occurred_at > authority.now
            or fact.received_at > authority.now
            or (fact.received_at < fact.occurred_at)
        ):
            raise DomainError("INVALID_EVENT_TIME", "执行/接收时间未发生或时序不一致。", 422)
        if not all(self._source(uow, authority, s).current for s in fact.sources):
            raise DomainError("RECHECK_REQUIRED", "事实来源已变化/撤回。")
        refs = fact.output_refs if effectivity else fact.outputs
        self._port("facts").audience(uow, authority, request.audience, refs, fact.sources)
        for ref in refs:
            if not self._ref(uow, authority, ref).current:
                raise DomainError("RECHECK_REQUIRED", "实际输出引用已变化。")
        # Existing frozen configurations/Run may never be overwritten.
        if any(r.id in {b.id for b in item.intent.basis} for r in refs) and (
            item.intent.kind != "erp_mes_effectivity"
        ):
            raise DomainError(
                "ORIGINAL_REWRITE_FORBIDDEN", "实施须产生新对象，禁止覆盖原配置/Run。"
            )
        expected_kind = {
            "new_engineering_configuration": "engineering_configuration",
            "new_manufacturing_configuration": "manufacturing_configuration",
            "new_build": "build",
            "new_test_run": "test_run",
        }.get(item.intent.kind)
        if (
            fact.outcome == "succeeded"
            and expected_kind
            and (not refs or any(r.kind != expected_kind for r in refs))
        ):
            raise DomainError("ACTUAL_OUTPUT_REQUIRED", "实施成功须有所有者核验的新对象固定引用。")
        if order.approvals and fact.occurred_at < max(a.at for a in order.approvals):
            raise DomainError("EXECUTION_BEFORE_APPROVAL", "执行事实不能早于各专业批准。")
        if not effectivity and fact.executor_id != authority.actor_id:
            raise DomainError("NAMED_EXECUTOR_REQUIRED", "实施记录须由本人具名办理。", 403)
        if effectivity:
            if fact.conditions_digest != digest(item.selection):
                raise DomainError("CONDITION_MISMATCH", "生效回执不符合批准范围/条件。")
            if not set(fact.covered_units) <= set(item.selection.units):
                raise DomainError("EFFECTIVITY_SCOPE_MISMATCH", "回执超出批准生效范围。")
            if fact.stage == "effective" and fact.outcome == "succeeded" and not fact.covered_units:
                raise DomainError("ACTUAL_SCOPE_REQUIRED", "实际生效必须有明确对象/批次/序号。")
        return fact

    def _assessment(self, order, request):
        assessment = next((a for a in request.assessments if a.id == order.assessment_id), None)
        if assessment is None or digest(assessment) != order.assessment_digest:
            raise DomainError("ASSESSMENT_MISMATCH", "变更令的固定影响依据不匹配。")
        return assessment

    def _verify(self, uow, authority, request, order, fact_id):
        fact = self._port("facts").verification(uow, authority, fact_id, order)
        if (
            fact.id != fact_id
            or fact.content_digest != order.content_digest
            or (set(fact.item_ids) != {i.id for i in order.plan.items})
            or len(set(fact.item_ids)) != len(fact.item_ids)
        ):
            raise DomainError(
                "VERIFICATION_SCOPE_MISMATCH", "独立复核未覆盖固定变更内容/全部生效项。"
            )
        if fact.nature != self._assessment(order, request).graph.nature:
            raise DomainError("FACT_NATURE_MISMATCH", "合成/真实依据不可混用。")
        if not fact.current or not fact.applicable or fact.result == "unknown":
            raise DomainError("VERIFICATION_INSUFFICIENT", "未知/失效/不适用依据不能作正式复核。")
        involved = {request.requester_id} | {a.actor_id for a in order.approvals}
        involved |= {f.executor_id for f in order.implementations} | set(fact.executor_ids)
        if fact.verifier_id != authority.actor_id or authority.actor_id in involved:
            raise DomainError(
                "INDEPENDENT_VERIFIER_REQUIRED", "提出/批准/实施/测试执行者不能自证。", 403
            )
        if "quality" not in authority.roles:
            raise DomainError("FORBIDDEN_OPERATION", "独立复核须具备品质职责。", 403)
        if fact.observed_from > fact.observed_until or fact.observed_until > authority.now:
            raise DomainError("INVALID_EVENT_TIME", "复核必须有已发生的完整观察窗口。", 422)
        effective_times = [
            f.occurred_at
            for f in order.effectivity
            if f.stage == "effective" and f.outcome == "succeeded"
        ]
        if not effective_times or fact.observed_from < max(effective_times):
            raise DomainError("VERIFICATION_TOO_EARLY", "独立复核不能早于全部实际生效。")
        outputs = {
            r.identity for f in order.implementations for r in f.outputs if f.outcome == "succeeded"
        }
        outputs |= {
            r.identity
            for f in order.effectivity
            for r in f.output_refs
            if f.stage == "effective" and f.outcome == "succeeded"
        }
        if not outputs or not outputs <= {r.identity for r in fact.output_refs}:
            raise DomainError("VERIFICATION_OUTPUT_MISSING", "复核必须覆盖实际新配置/Build/Run。")
        self._port("facts").audience(
            uow,
            authority,
            request.audience,
            fact.output_refs,
            fact.sources,
        )
        for ref in fact.output_refs:
            if not self._ref(uow, authority, ref).current:
                raise DomainError("RECHECK_REQUIRED", "复核输出引用已变化。")
        if not all(self._source(uow, authority, s).current for s in fact.sources):
            raise DomainError("RECHECK_REQUIRED", "复核依据已变化。")
        return fact

    def _prepare(self, uow, authority, operation, subject_id, revision, payload, decision_id):
        insert = operation == "change.request.create"
        if insert:
            if revision != 0:
                raise DomainError("VERSION_CONFLICT", "新请求的领域版本必须为0。")
            for ref in (*payload.roots, *payload.references):
                if not self._ref(uow, authority, ref).current:
                    raise DomainError("RECHECK_REQUIRED", "创建请求的引用已变化。")
            if not all(self._source(uow, authority, s).current for s in payload.sources):
                raise DomainError("RECHECK_REQUIRED", "请求来源已变化。")
            self._port("facts").audience(
                uow,
                authority,
                authority.audience,
                (*payload.roots, *payload.references),
                payload.sources,
            )
            request = ChangeRequest(
                id=subject_id,
                revision=1,
                scope=authority.scope,
                audience=authority.audience,
                requester_id=authority.requester_id,
                **payload.model_dump(),
            )
            read = digest(
                {
                    "scope": authority.scope.model_dump(mode="json"),
                    "audience": authority.audience,
                    "payload": payload.model_dump(mode="json"),
                }
            )
        else:
            request = self._request(uow, authority, subject_id)
            if request.revision != revision:
                raise DomainError("VERSION_CONFLICT", "变更版本已变化。")
            if operation not in {"change.recheck", "change.request.revise"}:
                # Recompute validates the selected new graph below. Requiring
                # the old graph's currentness would prevent its replacement and
                # ask a single-capture Facts port to resolve another identity.
                # The request owner still owns all retained-history read ACLs.
                self._require_current(
                    uow,
                    authority,
                    request,
                    include_assessment=operation != "change.impact.compute",
                )
            read = digest(request)

        new_ids = ()
        if operation in {"change.request.create", "change.request.revise"}:
            if not insert:
                if request.status in {"approved", "implementing", "verifying", "closed"} and (
                    not request.needs_recheck
                ):
                    raise DomainError("RECHECK_REQUIRED", "已批准或已执行内容须先显式重核。")
                for ref in (*payload.roots, *payload.references):
                    if not self._ref(uow, authority, ref).current:
                        raise DomainError("RECHECK_REQUIRED", "新请求引用仍失效。")
                if not all(self._source(uow, authority, s).current for s in payload.sources):
                    raise DomainError("RECHECK_REQUIRED", "新请求来源仍失效。")
                self._port("facts").audience(
                    uow,
                    authority,
                    request.audience,
                    (*payload.roots, *payload.references),
                    payload.sources,
                )
                request = replace(
                    request,
                    **payload.model_dump(),
                    status="draft",
                    needs_recheck=False,
                    recheck_reasons=(),
                )
        elif operation == "change.impact.compute":
            self._state(request, {"draft", "analysis"})
            graph = self._port("facts").graph(uow, authority, payload.snapshot)
            if graph.id != payload.snapshot.id or graph.revision != payload.snapshot.revision:
                raise DomainError("FIXED_REFERENCE_MISMATCH", "影响快照版本不匹配。")
            if set(r.identity for r in graph.roots) != {r.identity for r in request.roots}:
                raise DomainError("IMPACT_ROOT_MISMATCH", "影响根不匹配请求的精确版本。")
            if not set(request.audience) <= set(graph.audience):
                raise DomainError(
                    "AUDIENCE_USE_FORBIDDEN", "影响来源不允许当前请求的输出受众。", 403
                )
            self._port("facts").audience(
                uow,
                authority,
                request.audience,
                tuple(n.ref for n in graph.nodes),
                graph_sources(graph),
            )
            checks = self._fixed_graph(uow, authority, graph)
            if (
                graph.captured_at > authority.now
                or not deadline_current(graph.expires_at, authority.now)
                or (any(not c.current for c in checks))
            ):
                raise DomainError("RECHECK_REQUIRED", "影响来源/配置过期或待重核。")
            self._port("facts").audience(
                uow,
                authority,
                request.audience,
                (),
                tuple(s for h in payload.hypotheses for s in h.sources),
            )
            for h in payload.hypotheses:
                if not all(self._source(uow, authority, s).current for s in h.sources):
                    raise DomainError("RECHECK_REQUIRED", "AI假设来源已失效。")
            assessment = compute_impact(graph, request.revision, payload.hypotheses)
            read = digest({"request": read, "graph": digest(graph), "hypotheses": digest(payload)})
            request = replace(
                request, assessments=(*request.assessments, assessment), status="analysis"
            )
        elif operation == "change.order.prepare":
            self._state(request, {"analysis", "review"})
            if not request.assessments or request.assessments[-1].id != payload.assessment_id:
                raise DomainError("ASSESSMENT_MISMATCH", "必须选择最新固定影响评估。")
            assessment = request.assessments[-1]
            policy = self._policy(uow, authority, request)
            if not deadline_current(payload.plan.expires_at, authority.now):
                raise DomainError("PLAN_EXPIRED", "新生效计划已过期。")
            known = {row.node.ref.identity for row in assessment.known}
            if {d.object.identity for d in payload.plan.dispositions} != known:
                raise DomainError("IMPACT_DISPOSITION_MISSING", "必须明确处置全部已知影响对象。")
            for disposition in payload.plan.dispositions:
                if not all(self._source(uow, authority, s).current for s in disposition.sources):
                    raise DomainError("RECHECK_REQUIRED", "影响处置依据待重核。")
            for item in payload.plan.items:
                if not {r.identity for r in (*item.selection.objects, *item.intent.basis)} <= known:
                    raise DomainError(
                        "PLAN_SCOPE_MISMATCH", "计划对象/实施依据不在显式已知影响内。"
                    )
                if item.discipline not in policy.required_disciplines:
                    raise DomainError("PLAN_DISCIPLINE_MISMATCH", "计划专业不在当前决定政策。")
                self._port("facts").selection(uow, authority, item)
                if not all(self._source(uow, authority, s).current for s in item.selection.sources):
                    raise DomainError("RECHECK_REQUIRED", "生效范围来源待重核。")
            content = digest(
                {
                    "assessment": digest(assessment),
                    "plan": payload.plan.model_dump(mode="json"),
                    "policy": policy.model_dump(mode="json"),
                }
            )
            order = ChangeOrder(
                id=identity(authority.scope, subject_id, revision, operation, payload),
                assessment_id=assessment.id,
                assessment_digest=digest(assessment),
                plan=payload.plan,
                policy=policy.source,
                required_disciplines=policy.required_disciplines,
                content_digest=content,
            )
            read = digest({"request": read, "content": content})
            request = replace(request, orders=(*request.orders, order), status="review")
        elif operation == "change.order.approve":
            self._state(request, {"review"})
            order = self._order(request)
            assessment = self._assessment(order, request)
            if assessment.unknown or any(d.handling == "unknown" for d in order.plan.dispositions):
                raise DomainError(
                    "IMPACT_UNKNOWN", "缺边/来源/受众或版本范围未完整核对，不能批准。"
                )
            if payload.discipline not in order.required_disciplines or (
                payload.discipline not in authority.roles
            ):
                raise DomainError("FORBIDDEN_DISCIPLINE", "只能办理获授权的本专业决定。", 403)
            if authority.actor_id == request.requester_id:
                raise DomainError("SELF_APPROVAL_FORBIDDEN", "提出者不能自批。", 403)
            if any(a.discipline == payload.discipline for a in order.approvals):
                raise DomainError("APPROVAL_ALREADY_RECORDED", "本专业已批准，修订须新内容/决定。")
            if not deadline_current(payload.expires_at, authority.now) or (
                payload.expires_at is not None
                and order.plan.expires_at is not None
                and payload.expires_at > order.plan.expires_at
            ):
                raise DomainError("APPROVAL_EXPIRY_INVALID", "批准有效期必须在固定计划范围内。")
            sources = tuple(dict.fromkeys((*request.sources, order.policy)))
            approval = Approval(
                actor_id=authority.actor_id,
                at=authority.now,
                text=payload.text,
                read_digest=read,
                sources=sources,
                discipline=payload.discipline,
                decision_id=decision_id,
                content_digest=order.content_digest,
                expires_at=payload.expires_at,
            )
            order = replace(order, approvals=(*order.approvals, approval))
            complete = {a.discipline for a in order.approvals} == set(order.required_disciplines)
            request = replace(
                request,
                orders=(*request.orders[:-1], order),
                status="approved" if complete else "review",
            )
        elif operation == "change.implementation.record":
            self._state(request, {"approved", "implementing"})
            order = self._order(request)
            item = self._item(order, payload.item_id)
            fact = self._port("facts").implementation(uow, authority, payload.fact_id, order, item)
            fact = self._fact(uow, authority, fact, payload.fact_id, item, order, request)
            if fact.reconciles_id is not None:
                previous = next(
                    (f for f in order.implementations if f.id == fact.reconciles_id), None
                )
                if (
                    previous is None
                    or previous.outcome != "unknown"
                    or (
                        previous.item_id != fact.item_id
                        or previous.intent_id != fact.intent_id
                        or previous.executor_id != fact.executor_id
                        or previous.occurred_at != fact.occurred_at
                        or fact.outcome == "unknown"
                    )
                ):
                    raise DomainError(
                        "INVALID_RECONCILIATION", "对账须解析同一未知执行，不能重发。"
                    )
                if any(
                    f.reconciles_id == previous.id and f.id != fact.id
                    for f in order.implementations
                ):
                    raise DomainError("RECONCILIATION_ALREADY_RECORDED", "未知执行已有对账结果。")
            blockers = [
                f
                for f in order.implementations
                if f.item_id == item.id
                and f.outcome in {"succeeded", "unknown"}
                and f.id not in {r.reconciles_id for r in order.implementations}
            ]
            if any(f.id != fact.id and f.id != fact.reconciles_id for f in blockers):
                raise DomainError(
                    "IMPLEMENTATION_RECONCILE_REQUIRED",
                    "已有成功/未知执行；未知先对账，不盲目重发。",
                )
            duplicate = next((f for f in order.implementations if f.id == fact.id), None)
            if duplicate:
                if duplicate != fact:
                    raise DomainError("FACT_ID_CONFLICT", "同执行身份载荷不同。")
                return self._preview(operation, subject_id, revision, payload, read, request), (
                    request,
                    False,
                    (),
                    None,
                )
            read = digest({"request": read, "fact": digest(fact)})
            order = replace(order, implementations=(*order.implementations, fact))
            request = replace(request, orders=(*request.orders[:-1], order), status="implementing")
            new_ids = (fact.id,)
        elif operation == "change.effectivity.record":
            self._state(request, {"implementing", "verifying"})
            order = self._order(request)
            item = self._item(order, payload.item_id)
            implementation = next(
                (
                    f
                    for f in order.implementations
                    if f.item_id == item.id and f.outcome == "succeeded"
                ),
                None,
            )
            if implementation is None:
                raise DomainError("IMPLEMENTATION_INCOMPLETE", "没有核验的成功实施，不可记录生效。")
            fact = self._port("facts").effectivity(uow, authority, payload.fact_id, order, item)
            fact = self._fact(
                uow, authority, fact, payload.fact_id, item, order, request, effectivity=True
            )
            if fact.occurred_at < implementation.occurred_at or (
                item.intent.kind != "erp_mes_effectivity"
                and fact.output_refs != implementation.outputs
            ):
                raise DomainError(
                    "EFFECTIVITY_OUTPUT_MISMATCH", "回执早于实施或输出不是已实施新对象。"
                )
            if fact.reconciles_id is not None:
                previous = next((f for f in order.effectivity if f.id == fact.reconciles_id), None)
                if (
                    previous is None
                    or previous.outcome != "unknown"
                    or (
                        previous.item_id != fact.item_id
                        or previous.intent_id != fact.intent_id
                        or previous.stage != fact.stage
                        or previous.system != fact.system
                        or previous.external_id != fact.external_id
                        or previous.occurred_at != fact.occurred_at
                        or fact.outcome == "unknown"
                        or set(fact.covered_units)
                        != set(previous.covered_units or item.selection.units)
                    )
                ):
                    raise DomainError(
                        "INVALID_RECONCILIATION", "对账须解析同一未知回执的全部范围。"
                    )
                if any(
                    f.reconciles_id == previous.id and f.id != fact.id for f in order.effectivity
                ):
                    raise DomainError("RECONCILIATION_ALREADY_RECORDED", "未知回执已有对账结果。")
            reconciled = {f.reconciles_id for f in order.effectivity if f.reconciles_id is not None}
            pending = [
                f
                for f in order.effectivity
                if f.id not in reconciled
                and f.outcome == "unknown"
                and f.item_id == item.id
                and f.stage == fact.stage
            ]
            if any(
                f.id != fact.id
                and f.id != fact.reconciles_id
                and (
                    not f.covered_units
                    or not fact.covered_units
                    or set(f.covered_units) & set(fact.covered_units)
                )
                for f in pending
            ):
                raise DomainError(
                    "EFFECTIVITY_RECONCILE_REQUIRED",
                    "同范围生效结果未知，须核对原回执，不能换外部ID重发。",
                )
            if fact.reconciles_id is None and any(
                f.id != fact.id
                and (f.system, f.external_id, f.stage, f.occurred_at)
                == (fact.system, fact.external_id, fact.stage, fact.occurred_at)
                for f in order.effectivity
            ):
                raise DomainError(
                    "RECEIPT_IDENTITY_CONFLICT", "同一原始回执不能用新ID重复导入；更正须受控对账。"
                )
            duplicate = next((f for f in order.effectivity if f.id == fact.id), None)
            if duplicate:
                if duplicate != fact:
                    raise DomainError("FACT_ID_CONFLICT", "同回执身份载荷不同。")
                return self._preview(operation, subject_id, revision, payload, read, request), (
                    request,
                    False,
                    (),
                    None,
                )
            read = digest({"request": read, "fact": digest(fact)})
            order = replace(order, effectivity=(*order.effectivity, fact))
            request = replace(
                request,
                orders=(*request.orders[:-1], order),
                status="verifying" if fully_effective(order) else "implementing",
            )
            new_ids = (fact.id,)
        elif operation == "change.verification.record":
            self._state(request, {"verifying"})
            order = self._order(request)
            if not fully_effective(order):
                raise DomainError("EFFECTIVITY_INCOMPLETE", "部分/未知生效不能独立决定整包完成。")
            fact = self._verify(uow, authority, request, order, payload.fact_id)
            if any(v.fact.id == fact.id for v in order.verifications):
                raise DomainError("VERIFICATION_ALREADY_RECORDED", "该固定依据已有具名决定。")
            read = digest({"request": read, "verification": digest(fact)})
            verification = Verification(
                actor_id=authority.actor_id,
                at=authority.now,
                text=payload.text,
                read_digest=read,
                sources=fact.sources,
                fact=fact,
                decision_id=decision_id,
            )
            order = replace(order, verifications=(*order.verifications, verification))
            request = replace(request, orders=(*request.orders[:-1], order))
            new_ids = (fact.id,)
        elif operation == "change.close":
            self._state(request, {"verifying"})
            order = self._order(request)
            if (
                not fully_effective(order)
                or not order.verifications
                or (order.verifications[-1].fact.result != "pass")
            ):
                raise DomainError("CLOSURE_INCOMPLETE", "关闭须全范围实际生效及独立通过。")
            fact = self._verify(uow, authority, request, order, order.verifications[-1].fact.id)
            if fact != order.verifications[-1].fact:
                raise DomainError("RECHECK_REQUIRED", "关闭依据已变化。")
            closure = NamedRecord(
                actor_id=authority.actor_id,
                at=authority.now,
                text=payload.text,
                read_digest=read,
                sources=fact.sources,
            )
            order = replace(order, closure=closure)
            request = replace(request, orders=(*request.orders[:-1], order), status="closed")
        elif operation == "change.recheck":
            reasons = self._current(uow, authority, request)
            if not reasons:
                raise DomainError("RECHECK_NOT_REQUIRED", "没有服务器确认的失效原因。")
            request = replace(request, needs_recheck=True, recheck_reasons=reasons)
        preview = self._preview(operation, subject_id, revision, payload, read, request)
        return preview, (request, insert, new_ids, OPERATIONS[operation][2])

    def _preview(self, operation, subject_id, revision, payload, read, request):
        payload_digest = digest(payload)
        unknown = (
            tuple(u.reason for u in request.assessments[-1].unknown)
            if (request.assessments and request.status != "draft")
            else ()
        )
        result = Preview(
            operation=operation,
            subject_id=subject_id,
            expected_revision=revision,
            payload_digest=payload_digest,
            read_digest=read,
            digest=digest(
                {
                    "operation": operation,
                    "subject": str(subject_id),
                    "revision": revision,
                    "payload": payload_digest,
                    "read": read,
                    "next_state": request.status,
                }
            ),
            effect=EFFECTS.get(operation, "修订请求；旧批准、配置及历史结果保留。"),
            next_state=request.status,
            unknown=unknown,
        )
        return result

    def preview(self, uow, operation, subject_id, expected_revision, payload):
        parsed = self._parse(operation, payload)
        authority = self._port("commands").context(uow, operation, subject_id)
        self._authorize(authority, operation)
        # Preview validates named domain rules, but proof/decision ID is supplied
        # only by the common executor after a real human decision.
        return self._prepare(
            uow,
            authority,
            operation,
            subject_id,
            expected_revision,
            parsed,
            subject_id,
        )[0]

    def execute(self, uow, invocation: Invocation, payload):
        parsed = self._parse(invocation.operation, payload)
        if invocation.semantic_digest != digest(parsed):
            raise DomainError("PAYLOAD_DIGEST_MISMATCH", "固定载荷摘要不匹配。", 422)
        commands = self._port("commands")
        authority = commands.begin(uow, invocation)
        self._authorize(authority, invocation.operation)
        replay = commands.replay(uow, invocation, authority)
        if replay is not None:
            self._request(uow, authority, replay.subject_id)
            return replay
        tier = OPERATIONS[invocation.operation][1]
        if tier == "T2" and invocation.decision_id is None:
            raise DomainError("NAMED_DECISION_REQUIRED", "须共同具名决定ID。", 403)
        preview, (request, insert, fact_ids, event) = self._prepare(
            uow,
            authority,
            invocation.operation,
            invocation.subject_id,
            invocation.expected_revision,
            parsed,
            invocation.decision_id,
        )
        if tier in {"T1", "T2"}:
            commands.confirm(uow, invocation, preview, authority)
        if event is not None:
            old = None if insert else request.status
            # Re-read the locked original to retain the genuine transition source.
            if not insert:
                old = self._request(uow, authority, invocation.subject_id).status
            history = History(
                command_id=invocation.command_id,
                operation=invocation.operation,
                actor_id=authority.actor_id,
                at=authority.now,
                from_state=old,
                to_state=request.status,
                note=preview.effect,
            )
            request = replace(
                request,
                revision=1 if insert else invocation.expected_revision + 1,
                history=(*request.history, history),
            )
        return commands.record(
            uow,
            invocation,
            Mutation(
                change=request,
                expected_revision=invocation.expected_revision,
                insert=insert,
                event_name=event,
                preview_digest=preview.digest,
                new_fact_ids=fact_ids,
            ),
        )
