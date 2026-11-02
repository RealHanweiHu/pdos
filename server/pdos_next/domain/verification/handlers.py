"""Callable verification handlers; all writes are delegated to one host transaction."""

import hashlib
import json
from uuid import UUID

from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    Acceptance,
    EventTime,
    Gap,
    HandoffAccept,
    HandoffOffer,
    HandoffReturn,
    MethodPrepare,
    PartialResultsReturn,
    ProfessionalConclusion,
    RequestCreate,
    ResultsSubmit,
    ReturnedScope,
    RunDisposition,
    RunPlan,
    RunReview,
    RunStart,
    SchedulePromise,
    ScheduleProposal,
    SourceRef,
    TestRun,
    TimeFact,
    Timeline,
    VerificationRequest,
)

from .ports import Authority, DomainEvent, Invocation, Mutation, Outcome, Ports, Preview
from .rules import (
    accepted_coverage,
    check_coverage,
    compute_results,
    coverage_gaps,
    document_gaps,
    pairs,
)

OPERATIONS = {
    "verification.request.create": (RequestCreate, "T0", {"engineering", "quality"}, False),
    "verification.method.prepare": (MethodPrepare, "T1", {"quality"}, True),
    "verification.handoff.offer": (HandoffOffer, "T1", {"engineering", "production"}, False),
    "verification.handoff.accept": (HandoffAccept, "T1", {"quality"}, True),
    "verification.handoff.return": (HandoffReturn, "T1", {"quality"}, True),
    "verification.schedule.propose": (ScheduleProposal, "T0", {"quality"}, False),
    "verification.schedule.promise": (SchedulePromise, "T1", {"quality"}, True),
    "test.run.plan": (RunPlan, "T1", {"quality"}, True),
    "test.run.start": (RunStart, "T1", {"quality", "test"}, True),
    "test.results.import": (ResultsSubmit, "T1", {"quality", "test"}, False),
    "test.run.review": (RunReview, "T2", {"quality"}, True),
    "test.disposition.decide": (RunDisposition, "T2", {"quality"}, True),
}


def semantic_digest(payload) -> str:
    value = payload.model_dump(mode="json")
    # These sets describe the same business scope regardless of UI selection order.
    for key in ("coverage", "returned_coverage", "samples", "measurements"):
        if key in value:
            value[key] = sorted(value[key], key=lambda v: json.dumps(v, sort_keys=True))
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _replace(record, **changes):
    # model_copy does not validate updates; revalidate the complete immutable DTO.
    return type(record).model_validate({**record.model_dump(), **changes})


class VerificationHandler:
    def __init__(self, ports: Ports):
        self.ports = ports

    def _port(self, name):
        port = getattr(self.ports, name)
        if port is None:
            raise DomainError("INTEGRATION_REQUIRED", f"{name} 受控接口待主线接入。", 503)
        return port

    def _authorize(self, authority, operation):
        _, _, roles, human = OPERATIONS[operation]
        if authority.now.tzinfo is None or authority.now.utcoffset() is None:
            raise DomainError("INVALID_AUTHORITY", "服务器时间必须带时区。", 503)
        if authority.cancelled:
            raise DomainError("RUN_CANCELLED", "当前运行已取消。")
        if not authority.authorized or not roles.intersection(authority.roles):
            raise DomainError("FORBIDDEN_OPERATION", "当前范围及职责未获本操作授权。", 403)
        if authority.actor_kind == "ai" and human:
            raise DomainError(
                "NAMED_DECISION_REQUIRED",
                "该动作需要本人具名办理。",
                403,
            )
        if not authority.qualified:
            raise DomainError("QUALIFICATION_REQUIRED", "当前操作所需能力/专业资格未满足。", 403)

    def _source(self, authority, source, purpose):
        self._port("evidence").check(authority.scope, source, purpose)

    def _measurement_source(self, authority, measurement, run):
        verifier = getattr(self._port("evidence"), "verify_measurement", None)
        if not callable(verifier):
            raise DomainError("INTEGRATION_REQUIRED", "测量原值与原始来源核对接口待主线接入。", 503)
        verifier(authority.scope, measurement, run)

    def _fact(self, authority, at: EventTime, *, future=False):
        self._source(authority, at.source, "verification.time")
        if not future and at.occurred_at > authority.now:
            raise DomainError("INVALID_EVENT_TIME", "实际事件不得使用未来时间。", 422)
        return TimeFact(**at.model_dump(), received_at=authority.now, actor_id=authority.actor_id)

    def _command_fact(self, authority, command_id):
        return TimeFact(
            occurred_at=authority.now,
            original_timezone="UTC",
            received_at=authority.now,
            actor_id=authority.actor_id,
            source=SourceRef(id=command_id, revision=1, kind="command", position="receipt"),
        )

    def _source_guard(self, authority, request, item_ids=None):
        for item in request.items:
            if item_ids is not None and item.id not in item_ids:
                continue
            refs = (
                item.drawing,
                item.method,
                item.criterion_source,
                item.criterion.source if item.criterion else None,
            )
            for source in refs:
                if source:
                    self._source(authority, source, "verification.method")
        for document in request.documents:
            if document.source and (item_ids is None or set(document.item_ids) & item_ids):
                self._source(authority, document.source, "verification.document")

    def _build(self, authority, reference, *, actual=False):
        current = self._port("builds").get(authority.scope, reference.id)
        if current.ref != reference:
            raise DomainError("SOURCE_CHANGED", "Build 或固定双配置已漂移，须重新核对请求。")
        if (
            reference.product_id != authority.scope.product_id
            or reference.project_id != authority.scope.project_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "Build 不在服务器绑定范围。", 403)
        if actual and current.status not in {"executing", "evaluating", "closed"}:
            raise DomainError("ACTUAL_SAMPLE_REQUIRED", "计划 Build 不能证明真实样件产出。")
        return current

    def _request(self, authority, request_id, revision=None):
        request = self._port("commands").request(authority.scope, request_id)
        if request.scope != authority.scope:
            raise DomainError("FORBIDDEN_SCOPE", "验证请求不在服务器绑定范围。", 403)
        if revision is not None and request.revision != revision:
            raise DomainError("VERSION_CONFLICT", "验证请求版本已变化。")
        self._build(authority, request.build)
        return request

    def _run(self, authority, run_id, revision):
        run = self._port("commands").run(authority.scope, run_id)
        if run.scope != authority.scope:
            raise DomainError("FORBIDDEN_SCOPE", "测试运行不在服务器绑定范围。", 403)
        if run.revision != revision:
            raise DomainError("VERSION_CONFLICT", "测试运行版本已变化。")
        request = self._request(authority, run.request_id)
        if run.build != request.build:
            raise DomainError("SOURCE_CHANGED", "运行与请求的固定 Build 已不一致。")
        fixed_items = {i.id: i for i in run.items}
        current_items = {i.id: i for i in request.items if i.id in fixed_items}
        fixed_samples = {s.id: s for s in run.samples}
        current_samples = {s.id: s for s in request.samples if s.id in fixed_samples}
        if fixed_items != current_items or fixed_samples != current_samples:
            raise DomainError("SOURCE_CHANGED", "Run 的固定方法或样件范围已漂移。")
        self._source_guard(authority, request, {c.item_id for c in run.coverage})
        for measurement in run.measurements:
            self._measurement_source(authority, measurement, run)
            for source in (measurement.source, measurement.method, measurement.equipment):
                if source:
                    self._source(authority, source, "test.measurement")
        if run.execution:
            for source in (run.execution.equipment, run.execution.calibration):
                self._source(authority, source, "test.execution")
        return run, request

    def _inspect(self, authority, request, samples, coverage, *, ready):
        check_coverage(request, coverage, samples)
        selected = {c.sample_id for c in coverage}
        gaps, facts = [], []
        for sample in samples:
            if sample.id not in selected:
                continue
            current = self._port("samples").inspect(authority.scope, sample, "verification")
            if current.sample != sample:
                raise DomainError("SOURCE_CHANGED", "样件或实际配置版本已漂移，须新 Run/重新接收。")
            self._source(authority, current.source, "verification.sample")
            fact = self._fact(authority, current.ready_at) if current.ready_at else None
            if fact:
                facts.append(fact)
            if not current.available or not current.applicable or fact is None:
                gaps.append(
                    Gap(
                        code="SAMPLE_UNAVAILABLE"
                        if not current.available
                        else "INAPPLICABLE_CONFIGURATION",
                        sample_id=sample.id,
                        detail=current.reason or "实物不可用或配置适用性未确认",
                    )
                )
        if ready and gaps:
            raise DomainError("SAMPLE_UNAVAILABLE", "样件可用性或配置适用性未通过原子复查。")
        return tuple(gaps), (
            max(facts, key=lambda t: t.occurred_at)
            if facts and len(facts) == len(selected)
            else None
        )

    def _event(self, name, record, fact, coverage=()):
        return DomainEvent(
            name=name,
            subject_id=record.id,
            revision=record.revision,
            scope=record.scope,
            at=fact,
            coverage=coverage,
        )

    def preview(self, operation: str, subject_id: UUID, expected_revision: int, payload) -> Preview:
        self._shape(operation, payload)
        authority = self._port("commands").context(operation, subject_id)
        self._authorize(authority, operation)
        invocation = Invocation(
            command_id=subject_id,
            operation=operation,
            subject_id=subject_id,
            expected_revision=expected_revision,
            semantic_digest=semantic_digest(payload),
        )
        return self._prepare(authority, invocation, payload)[0]

    def _shape(self, operation, payload):
        if operation not in OPERATIONS or not isinstance(payload, OPERATIONS[operation][0]):
            raise DomainError("INVALID_OPERATION_PAYLOAD", "操作与专用载荷不匹配。", 422)

    def execute(self, invocation: Invocation, payload) -> Outcome:
        self._shape(invocation.operation, payload)
        if invocation.semantic_digest != semantic_digest(payload):
            raise DomainError("INTENT_CONFLICT", "命令实质载荷摘要不匹配。")
        authority = self._port("commands").begin(invocation)
        if isinstance(authority, Outcome):
            return authority
        self._authorize(authority, invocation.operation)
        preview, mutation = self._prepare(authority, invocation, payload)
        if not preview.allowed:
            raise DomainError("MISSING_REQUIRED_EVIDENCE", "所选范围缺少必要资料或样件。")
        if OPERATIONS[invocation.operation][1] != "T0":
            self._port("commands").confirm(invocation, preview, authority)
        if isinstance(payload, RunStart):
            run = mutation.run
            self._port("samples").reserve(
                authority.scope,
                run.id,
                run.samples,
                run.coverage,
                tuple(
                    c
                    for c in run.coverage
                    if next(item for item in run.items if item.id == c.item_id).destructive
                ),
                run.execution,
            )
        return self._port("commands").record(invocation, mutation)

    def _prepare(self, authority: Authority, inv: Invocation, payload):
        request, run, gaps, coverage = None, None, (), ()
        request_before_revision, run_before_revision = 0, None
        effect = "保存验证事实与同事务回执。"
        operation = inv.operation
        if isinstance(payload, RequestCreate):
            if inv.expected_revision != 0 or inv.subject_id != payload.request_id:
                raise DomainError("VERSION_CONFLICT", "新请求必须使用自身 ID 和零起始版本。")
            current = self._port("builds").get(authority.scope, payload.build_id)
            if current.ref.revision != payload.expected_build_revision:
                raise DomainError("VERSION_CONFLICT", "Build 版本已变化。")
            self._build(authority, current.ref)
            fact = self._command_fact(authority, inv.command_id)
            request = VerificationRequest(
                id=payload.request_id,
                revision=1,
                scope=authority.scope,
                build=current.ref,
                title=payload.title,
                purpose=payload.purpose,
                items=payload.items,
                documents=payload.documents,
                expected_at=payload.expected_at,
                expected_timezone=payload.expected_timezone,
                return_form=payload.return_form,
                timeline=Timeline(request_created=fact),
            )
            self._source_guard(authority, request)
            gaps = document_gaps(request)
            event_name, effect = "verification.requested", "建立前置验证请求；缺项保留待补。"
            if not gaps:
                request = _replace(
                    request, timeline=_replace(request.timeline, documents_complete=fact)
                )
        elif isinstance(payload, (RunStart, ResultsSubmit, RunReview, RunDisposition)):
            run, request = self._run(authority, inv.subject_id, inv.expected_revision)
            request_before_revision, run_before_revision = request.revision, run.revision
            coverage = run.coverage
            fact = self._fact(authority, payload.at)
            run, request, event_name = self._run_action(authority, inv, payload, run, request, fact)
            effect = "保存本 Run 精确覆盖结果；执行状态与判定分别记录。"
        else:
            request = self._request(authority, inv.subject_id, inv.expected_revision)
            request_before_revision = request.revision
            request, run, gaps, coverage, fact, event_name, effect = self._request_action(
                authority, inv, payload, request
            )
        record = run or request
        events = (self._event(event_name, record, fact, coverage),)
        mutation = Mutation(
            operation=operation,
            before_revision=inv.expected_revision,
            request_before_revision=request_before_revision,
            run_before_revision=0 if isinstance(payload, RunPlan) else run_before_revision,
            request=request,
            run=run,
            events=events,
        )
        # Digest excludes receipt/actual system receive timestamps, and includes fixed
        # source/sample/configuration refs, actor/scope and semantic command content.
        basis = dict(
            operation=operation,
            subject=str(inv.subject_id),
            revision=inv.expected_revision,
            scope=authority.scope.model_dump(mode="json"),
            actor=str(authority.actor_id),
            intent=inv.semantic_digest,
            request_revision=request_before_revision,
            build=request.build.model_dump(mode="json"),
            items=[i.model_dump(mode="json") for i in (run.items if run else request.items)],
            documents=[d.model_dump(mode="json") for d in request.documents],
            samples=[s.model_dump(mode="json") for s in (run.samples if run else request.samples)],
            coverage=[c.model_dump(mode="json") for c in coverage],
            gaps=[g.model_dump(mode="json") for g in gaps],
        )
        for key in ("samples", "coverage", "gaps"):
            basis[key] = sorted(basis[key], key=lambda value: json.dumps(value, sort_keys=True))
        digest = hashlib.sha256(
            json.dumps(basis, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        allowed = not gaps or isinstance(
            payload, (RequestCreate, MethodPrepare, HandoffOffer, HandoffReturn)
        )
        return Preview(
            operation=operation,
            subject_id=inv.subject_id,
            expected_revision=inv.expected_revision,
            digest=digest,
            allowed=allowed,
            coverage=coverage,
            gaps=gaps,
            effect=effect,
        ), mutation

    def _request_action(self, authority, inv, payload, request):
        gaps, coverage, run = (), (), None
        if isinstance(payload, MethodPrepare):
            if request.status not in {"draft", "offered", "accepted", "scheduled", "executing"}:
                raise DomainError("INVALID_STATE", "结果返回后的方法变更需新请求/新 Run。")
            if request.status != "draft":
                if {i.id for i in payload.items} != {i.id for i in request.items}:
                    raise DomainError("INVALID_COVERAGE", "交接后不得增删原测试项身份。", 422)
                accepted_items = {c.item_id for c in accepted_coverage(request)}
                before = {i.id: i for i in request.items if i.id in accepted_items}
                after = {i.id: i for i in payload.items if i.id in accepted_items}
                before_docs = {
                    d.id: d for d in request.documents if set(d.item_ids) & accepted_items
                }
                after_docs = {
                    d.id: d for d in payload.documents if set(d.item_ids) & accepted_items
                }
                if before != after or before_docs != after_docs:
                    raise DomainError(
                        "ACCEPTED_SCOPE_FROZEN", "已接收项和适用资料不可重写，须新请求/Run。"
                    )
            if payload.tentative_start:
                self._fact(authority, payload.tentative_start, future=True)
            request = _replace(
                request,
                items=payload.items,
                documents=payload.documents,
                tentative_start=payload.tentative_start,
            )
            self._source_guard(authority, request)
            gaps = document_gaps(request)
            fact = self._command_fact(authority, inv.command_id)
            timeline = _replace(request.timeline, documents_complete=None if gaps else fact)
            request = _replace(request, timeline=timeline)
            event_name, effect = (
                "verification.method_prepared",
                "方法/暂定时段准备；不确认实物交样。",
            )
        elif isinstance(payload, HandoffOffer):
            if request.status != "draft":
                raise DomainError("INVALID_STATE", "当前请求不能再次发起交接。")
            coverage = payload.coverage
            self._build(authority, request.build, actual=True)
            if {s.id for s in payload.samples} != {c.sample_id for c in coverage}:
                raise DomainError("INVALID_COVERAGE", "每件交接样件必须有明确测试项范围。", 422)
            sample_gaps, ready_at = self._inspect(
                authority, request, payload.samples, coverage, ready=False
            )
            self._source_guard(authority, request)
            gaps = document_gaps(request) + sample_gaps
            fact = self._fact(authority, payload.at)
            if ready_at and ready_at.occurred_at > fact.occurred_at:
                raise DomainError("INVALID_EVENT_TIME", "交样时间不得早于实际样件就绪。", 422)
            timeline = _replace(
                request.timeline,
                offered=fact,
                sample_ready=ready_at,
                documents_complete=request.timeline.documents_complete
                if not document_gaps(request)
                else None,
            )
            request = _replace(
                request,
                status="offered",
                samples=payload.samples,
                offered_coverage=coverage,
                timeline=timeline,
            )
            event_name, effect = "handoff.offered", "发起明确范围交接；样件与资料就绪各自记录。"
        elif isinstance(payload, (HandoffAccept, HandoffReturn)):
            if request.status not in {"offered", "accepted", "scheduled", "executing"}:
                raise DomainError("INVALID_STATE", "当前状态不能接收或退缺项。")
            coverage = payload.coverage
            check_coverage(request, coverage)
            if not pairs(coverage) <= pairs(request.offered_coverage):
                raise DomainError("INVALID_COVERAGE", "接收/退回超出已交接范围。", 422)
            if pairs(coverage) & pairs(accepted_coverage(request)):
                raise DomainError("ALREADY_ACCEPTED", "已接收范围不能重复接收或退回。")
            fact = self._fact(authority, payload.at)
            if fact.occurred_at < request.timeline.offered.occurred_at:
                raise DomainError("INVALID_EVENT_TIME", "接收/退回不能早于交接。", 422)
            if isinstance(payload, HandoffAccept):
                self._build(authority, request.build, actual=True)
                _, ready_at = self._inspect(
                    authority, request, request.samples, coverage, ready=True
                )
                if ready_at and fact.occurred_at < ready_at.occurred_at:
                    raise DomainError("INVALID_EVENT_TIME", "接收不能早于所选实物就绪。", 422)
                selected = {c.item_id for c in coverage}
                self._source_guard(authority, request, selected)
                gaps = document_gaps(request, selected)
                remaining = pairs(request.offered_coverage) - pairs(accepted_coverage(request))
                returned = payload.returned_coverage
                if pairs(coverage) & pairs(returned) or len(pairs(returned)) != len(returned):
                    raise DomainError("INVALID_COVERAGE", "接收与退回范围须明确且不重复。", 422)
                if not pairs(returned) <= remaining:
                    raise DomainError("INVALID_COVERAGE", "退回范围超出未接收交接范围。", 422)
                cumulative = accepted_coverage(request) + coverage
                partial = pairs(coverage) != remaining or bool(coverage_gaps(request, cumulative))
                if partial and (not payload.reason or not payload.next_owner_id):
                    raise DomainError(
                        "PARTIAL_RESPONSIBILITY_REQUIRED", "部分接收须说明缺项和下一责任人。", 422
                    )
                returns = request.returns
                if partial:
                    remainder = tuple(
                        c
                        for c in request.offered_coverage
                        if (c.sample_id, c.item_id) in remaining - pairs(coverage)
                    )
                    returns += (
                        ReturnedScope(
                            coverage=returned or remainder,
                            gaps=document_gaps(request, {c.item_id for c in remainder})
                            + coverage_gaps(request, cumulative),
                            reason=payload.reason,
                            next_owner_id=payload.next_owner_id,
                            actor_id=authority.actor_id,
                            at=fact,
                        ),
                    )
                all_ready = request.timeline.sample_ready
                accepted_times = tuple(
                    a.sample_ready for a in request.acceptances if a.sample_ready
                )
                if (
                    all_ready is None
                    and ready_at
                    and ({c.sample_id for c in cumulative} == {s.id for s in request.samples})
                ):
                    all_ready = max(accepted_times + (ready_at,), key=lambda t: t.occurred_at)
                timeline = _replace(
                    request.timeline,
                    accepted=request.timeline.accepted or fact,
                    sample_ready=all_ready,
                )
                request = _replace(
                    request,
                    status=request.status
                    if request.status in {"scheduled", "executing"}
                    else "accepted",
                    timeline=timeline,
                    returns=returns,
                    acceptances=request.acceptances
                    + (
                        Acceptance(
                            coverage=coverage,
                            actor_id=authority.actor_id,
                            at=fact,
                            sample_ready=ready_at,
                        ),
                    ),
                )
                event_name, effect = (
                    "handoff.accepted",
                    "具名接收所选样件/测试项；未覆盖项仍待办理。",
                )
            else:
                gaps = document_gaps(request, {c.item_id for c in coverage})
                returned = ReturnedScope(
                    coverage=coverage,
                    gaps=gaps,
                    reason=payload.reason,
                    next_owner_id=payload.next_owner_id,
                    actor_id=authority.actor_id,
                    at=fact,
                )
                request = _replace(request, returns=request.returns + (returned,))
                event_name, effect = (
                    "handoff.returned",
                    "退回缺项并记录下一责任人；不制造接收事实。",
                )
        elif isinstance(payload, ScheduleProposal):
            if request.status in {"reported", "disposed"}:
                raise DomainError("INVALID_STATE", "已返回结果的请求不能再提议前置时段。")
            self._fact(authority, payload.at, future=True)
            request = _replace(request, tentative_start=payload.at)
            fact = self._command_fact(authority, inv.command_id)
            event_name, effect = (
                "verification.schedule_proposed",
                "暂定测试时段；不占用资源或改变承诺。",
            )
        elif isinstance(payload, SchedulePromise):
            if request.status not in {"accepted", "scheduled", "executing"}:
                raise DomainError("INVALID_STATE", "正式承诺窗口须先接收明确范围。")
            fixed_run, fixed_request = self._run(
                authority, payload.run_id, payload.expected_run_revision
            )
            if fixed_request.id != request.id or fixed_run.status != "planned":
                raise DomainError("INVALID_STATE", "承诺须绑定本请求尚未开测的固定Run。")
            coverage = fixed_run.coverage
            check_coverage(request, coverage)
            if not pairs(coverage) <= pairs(accepted_coverage(request)):
                raise DomainError("INVALID_COVERAGE", "承诺超出实际接收范围。", 422)
            fact = self._fact(authority, payload.at, future=True)
            request = _replace(
                request,
                status="executing" if request.status == "executing" else "scheduled",
                timeline=_replace(
                    request.timeline, promised_start=request.timeline.promised_start or fact
                ),
            )
            event_name, effect = "verification.start_promised", "品质承诺窗口；实际开始仍为空。"
        elif isinstance(payload, RunPlan):
            if request.status not in {"accepted", "scheduled", "executing"}:
                raise DomainError("INVALID_STATE", "Run 只能计划在已接收范围内。")
            coverage = payload.coverage
            check_coverage(request, coverage)
            if not pairs(coverage) <= pairs(accepted_coverage(request)):
                raise DomainError("INVALID_COVERAGE", "Run 超出实际接收范围。", 422)
            self._build(authority, request.build, actual=True)
            self._inspect(authority, request, request.samples, coverage, ready=True)
            selected = {c.item_id for c in coverage}
            self._source_guard(authority, request, selected)
            gaps = document_gaps(request, selected)
            samples = tuple(s for s in request.samples if s.id in {c.sample_id for c in coverage})
            run = TestRun(
                id=payload.run_id,
                revision=1,
                scope=authority.scope,
                request_id=request.id,
                request_revision=request.revision,
                build=request.build,
                items=tuple(i for i in request.items if i.id in selected),
                samples=samples,
                coverage=coverage,
            )
            fact = self._command_fact(authority, inv.command_id)
            event_name, effect = "test.run_planned", "固定真实样件/实际配置与方法；尚未开始执行。"
        else:
            raise DomainError("INVALID_OPERATION_PAYLOAD", "不支持该请求动作。", 422)
        if not isinstance(payload, RunPlan):
            request = _replace(request, revision=request.revision + 1)
        return request, run, gaps, coverage, fact, event_name, effect

    def _run_action(self, authority, inv, payload, run, request, fact):
        if isinstance(payload, RunStart):
            if run.status != "planned":
                raise DomainError("INVALID_STATE", "仅已计划 Run 可以开始。")
            self._build(authority, run.build, actual=True)
            self._inspect(authority, request, run.samples, run.coverage, ready=True)
            if not pairs(run.coverage) <= pairs(accepted_coverage(request)):
                raise DomainError("INVALID_COVERAGE", "本 Run 范围已不在实际接收范围。")
            accepted_times = [
                a.at.occurred_at
                for a in request.acceptances
                if pairs(a.coverage) & pairs(run.coverage)
            ]
            if not accepted_times or fact.occurred_at < max(accepted_times):
                raise DomainError("INVALID_EVENT_TIME", "开测不能早于实际接收。", 422)
            if payload.execution.executor_id != authority.actor_id:
                raise DomainError("NAMED_DECISION_REQUIRED", "开始执行须绑定当前本人执行者。", 403)
            self._source(authority, payload.execution.equipment, "test.equipment")
            self._source(authority, payload.execution.calibration, "test.calibration")
            destructive = [
                c.sample_id
                for c in run.coverage
                if next(i for i in run.items if i.id == c.item_id).destructive
            ]
            if len(destructive) != len(set(destructive)):
                raise DomainError("DESTRUCTIVE_CONFLICT", "同一样件不能承担多个破坏性测试。")
            run = _replace(run, status="running", actual_start=fact, execution=payload.execution)
            request = _replace(
                request,
                status="executing",
                revision=request.revision + 1,
                timeline=_replace(
                    request.timeline, actual_start=request.timeline.actual_start or fact
                ),
            )
            event_name = "test.run_started"
        elif isinstance(payload, ResultsSubmit):
            if run.status != "running":
                raise DomainError("INVALID_STATE", "仅运行中的 Run 可以提交部分/最终结果。")
            self._port("samples").recheck_running(authority.scope, run)
            if fact.occurred_at < run.actual_start.occurred_at:
                raise DomainError("INVALID_EVENT_TIME", "结果发生时间不能早于实际开始。", 422)
            old_pairs = pairs(tuple(m.coverage for m in run.measurements))
            if old_pairs & pairs(tuple(m.coverage for m in payload.measurements)):
                raise DomainError(
                    "MEASUREMENT_ALREADY_RECORDED", "原始测量不能静默覆盖，纠正须新版本。"
                )
            measurements = run.measurements + payload.measurements
            for measurement in payload.measurements:
                self._measurement_source(authority, measurement, run)
                for source in (measurement.source, measurement.method, measurement.equipment):
                    if source:
                        self._source(authority, source, "test.measurement")
                if measurement.observed_at is not None and not (
                    run.actual_start.occurred_at <= measurement.observed_at <= fact.occurred_at
                ):
                    raise DomainError(
                        "INVALID_EVENT_TIME", "测量时间须在真实开始与结果时间之间。", 422
                    )
            computed, result = compute_results(run, measurements, final=payload.final)
            if payload.final:
                if pairs(tuple(m.coverage for m in measurements)) != pairs(run.coverage):
                    raise DomainError(
                        "INCOMPLETE_FINAL_SCOPE", "最终返回须明确全 Run 覆盖；未知值保留未知。"
                    )
                if payload.actual_end is None:
                    raise DomainError("ACTUAL_END_REQUIRED", "最终结果需真实结束时间和来源。", 422)
                end = self._fact(authority, payload.actual_end)
                observed = [m.observed_at for m in measurements if m.observed_at is not None]
                if not run.actual_start.occurred_at <= end.occurred_at <= fact.occurred_at or (
                    observed and max(observed) > end.occurred_at
                ):
                    raise DomainError("INVALID_EVENT_TIME", "实际结束不能早于测量或晚于返回。", 422)
                run = _replace(run, status="results_pending", actual_end=end, final_result=fact)
            elif payload.actual_end is not None:
                raise DomainError("INVALID_EVENT_TIME", "部分返回不能暗中记录最终结束。", 422)
            if not payload.final:
                present = pairs(tuple(m.coverage for m in measurements))
                partial = PartialResultsReturn(
                    returned_coverage=tuple(m.coverage for m in payload.measurements),
                    pending_coverage=tuple(
                        c for c in run.coverage if (c.sample_id, c.item_id) not in present
                    ),
                    reason=payload.incomplete_reason,
                    next_owner_id=payload.next_owner_id,
                    at=fact,
                )
                run = _replace(run, partial_returns=run.partial_returns + (partial,))
            run = _replace(
                run,
                measurements=measurements,
                computed_results=computed,
                result=result,
                preliminary_result=run.preliminary_result or (None if payload.final else fact),
            )
            request = _replace(
                request,
                revision=request.revision + 1,
                timeline=_replace(
                    request.timeline,
                    preliminary_result=request.timeline.preliminary_result
                    or (None if payload.final else fact),
                ),
            )
            if payload.final and self._request_complete(authority, request, run):
                request = _replace(
                    request,
                    status="reported",
                    timeline=_replace(request.timeline, final_result=fact),
                )
            event_name = "test.results_imported"
        elif isinstance(payload, RunReview):
            if run.status != "results_pending":
                raise DomainError("INVALID_STATE", "最终结果返回后才能具名专业审核。")
            if fact.occurred_at < run.final_result.occurred_at:
                raise DomainError("INVALID_EVENT_TIME", "专业结论不能早于最终结果。", 422)
            conclusion = ProfessionalConclusion(
                text=payload.text, actor_id=authority.actor_id, source=payload.at.source, at=fact
            )
            run = _replace(run, status="reviewed", professional_conclusion=conclusion)
            event_name = "test.run_reviewed"
        else:
            if run.status != "reviewed":
                raise DomainError("INVALID_STATE", "仅具名审核后的 Run 可以处置。")
            if fact.occurred_at < run.professional_conclusion.at.occurred_at:
                raise DomainError("INVALID_EVENT_TIME", "处置不能早于专业结论。", 422)
            conclusion = ProfessionalConclusion(
                text=payload.text, actor_id=authority.actor_id, source=payload.at.source, at=fact
            )
            run = _replace(run, status="disposed", disposition=conclusion)
            if self._request_complete(authority, request, run, disposed=True):
                request = _replace(
                    request,
                    status="disposed",
                    revision=request.revision + 1,
                    timeline=_replace(request.timeline, disposed=fact),
                )
            event_name = "test.disposition_decided"
        return _replace(run, revision=run.revision + 1), request, event_name

    def _request_complete(self, authority, request, current_run, *, disposed=False):
        runs = self._port("commands").runs(authority.scope, request.id)
        compatible = [r for r in runs if r.id != current_run.id] + [current_run]
        completed = tuple(
            c
            for r in compatible
            if r.final_result is not None
            and r.result != "invalid"
            and (not disposed or r.status == "disposed")
            for c in r.coverage
        )
        accepted = accepted_coverage(request)
        return (
            pairs(accepted) == pairs(request.offered_coverage)
            and pairs(completed) >= pairs(accepted)
            and not coverage_gaps(request, accepted)
        )
