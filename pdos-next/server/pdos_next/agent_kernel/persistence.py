"""Durable run, call and budget state. Every attempt checks current bound principals/ACL."""

from contextlib import contextmanager
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text

from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Category, Grant, Principal
from pdos_next.service import Context, digest, require_access

from .models import AgentEvent, AgentRun, AgentSession, AgentToolCall, ValidationBudget
from .types import RunScope


class KernelStore:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def composition_lock(self, scope, call_key):
        """Fence the resumable read orchestrator across processes, without a long transaction."""
        key = int(
            digest(["research-composition", scope.tenant_id, scope.run_id, call_key])[:16], 16
        )
        if key >= 2**63:
            key -= 2**64
        self.current(scope)
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            if not connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
                raise RuntimeError("Research composition is already advancing in another process")
            try:
                yield
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})

    def release_call(
        self, scope, call_id, *, error, unknown=False, usage=0, request_id=None, cost_usage=None
    ):
        # This narrowly scoped DB function works after ACL revocation. It returns
        # no source/result data and only frees an existing technical reservation.
        with tenant_session(
            self.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
        ) as session:
            if cost_usage is not None:
                session.execute(
                    text("SELECT kernel_record_cost(:run,:call,:inp,:outp,:cost)"),
                    {
                        "run": scope.run_id,
                        "call": call_id,
                        "inp": cost_usage.input_tokens,
                        "outp": cost_usage.output_tokens,
                        "cost": cost_usage.micro_usd,
                    },
                )
            return session.scalar(
                text("SELECT kernel_release_call(:run,:call,:reason,:unknown,:usage,:request_id)"),
                {
                    "run": scope.run_id,
                    "call": call_id,
                    "reason": error,
                    "unknown": unknown,
                    "usage": usage,
                    "request_id": request_id,
                },
            )

    @contextmanager
    def transaction(self, scope, *, lock=False):
        with tenant_session(
            self.engine,
            scope.tenant_id,
            actor_id=scope.writer_id,
            requester_id=scope.requester_id,
            category_id=scope.category_id,
        ) as session:
            run = session.scalar(
                select(AgentRun).where(AgentRun.id == scope.run_id).with_for_update()
                if lock
                else select(AgentRun).where(AgentRun.id == scope.run_id)
            )
            if (
                not run
                or run.tenant_id != scope.tenant_id
                or run.requester_id != scope.requester_id
                or run.writer_id != scope.writer_id
                or run.category_id != scope.category_id
                or run.product_id != scope.product_id
                or run.proposal_id != scope.proposal_id
                or getattr(run, "project_id", None) != getattr(scope, "project_id", None)
                or run.session_id != scope.session_id
                or run.trigger != scope.trigger
                or run.private_context != scope.private_context
                or frozenset(run.data_categories) != scope.data_categories
                or tuple(run.customer_identities) != scope.customer_identities
            ):
                raise DomainError("FORBIDDEN_SCOPE", "运行与服务器范围不一致。")
            if (
                run.reverted_at
                or run.cancel_epoch != scope.cancel_epoch
                or run.state == "cancelled"
            ):
                raise DomainError("CANCELLED_RUN", "运行已取消；已办理动作保留。")
            self.authority(session, scope)
            # Budget admission belongs to the new model reservation below. Reading
            # committed calls/events does not spend or require an active budget.
            yield session, run

    def authority(self, session, scope):
        if scope.trigger == "automation_service":
            from pdos_next.domain.automations.service_runtime import run_binding

            run_binding(session, session.get(AgentRun, scope.run_id))
        for person in {scope.writer_id, scope.requester_id}:
            row = session.get(Principal, person)
            if not row or row.tenant_id != scope.tenant_id or not row.active:
                raise DomainError("FORBIDDEN_SCOPE", "运行身份失效。")
        if scope.product_id:
            require_access(
                session,
                Context(
                    scope.tenant_id,
                    scope.writer_id,
                    scope.requester_id,
                    category_id=scope.category_id,
                ),
                scope.product_id,
                write=False,
            )
        elif scope.category_id:
            category = session.get(Category, scope.category_id)
            grants = session.scalars(
                select(Grant).where(
                    Grant.category_id == scope.category_id,
                    Grant.principal_id.in_({scope.writer_id, scope.requester_id}),
                    or_(Grant.expires_at.is_(None), Grant.expires_at > now()),
                )
            ).all()
            if not category or {g.principal_id for g in grants} != {
                scope.writer_id,
                scope.requester_id,
            }:
                raise DomainError("FORBIDDEN_SCOPE", "品类运行授权失效。")
        if scope.proposal_id is not None:
            from pdos_next.domain.preproject.access import proposal

            proposal(
                session,
                Context(
                    scope.tenant_id,
                    scope.writer_id,
                    scope.requester_id,
                    category_id=scope.category_id,
                ),
                scope.proposal_id,
            )
        if getattr(scope, "project_id", None) is not None:
            from .project_scope import require_project

            require_project(
                session,
                Context(
                    scope.tenant_id,
                    scope.writer_id,
                    scope.requester_id,
                    category_id=scope.category_id,
                ),
                scope.project_id,
                scope.product_id,
            )

    def scope(self, *, tenant_id, requester_id, writer_id, category_id, run_id):
        with tenant_session(
            self.engine,
            tenant_id,
            actor_id=writer_id,
            requester_id=requester_id,
            category_id=category_id,
        ) as session:
            run = session.get(AgentRun, run_id)
            if not run or run.requester_id != requester_id or run.writer_id != writer_id:
                raise DomainError("FORBIDDEN_SCOPE", "运行不可用。")
            if run.reverted_at:
                raise DomainError("CANCELLED_RUN", "整次运行已撤回；不能恢复执行。")
            scope = RunScope(
                tenant_id,
                requester_id,
                writer_id,
                run.session_id,
                run.id,
                run.category_id,
                run.product_id,
                run.proposal_id,
                run.cancel_epoch,
                run.private_context,
                frozenset(run.data_categories),
                tuple(run.customer_identities),
                trigger=run.trigger,
                project_id=getattr(run, "project_id", None),
            )
            self.authority(session, scope)
            return scope

    def current(self, scope):
        with self.transaction(scope):
            pass

    def emit(self, scope, body):
        with self.transaction(scope, lock=True) as (session, run):
            seq = (
                session.scalar(
                    select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                        AgentEvent.run_id == run.id
                    )
                )
                + 1
            )
            event = AgentEvent(
                id=uuid4(), tenant_id=scope.tenant_id, run_id=run.id, sequence=seq, body=body
            )
            session.add(event)
            return event.id

    def events(self, scope, after=0, page_size=50):
        with self.transaction(scope) as (session, run):
            rows = session.scalars(
                select(AgentEvent)
                .where(AgentEvent.run_id == run.id, AgentEvent.sequence > after)
                .order_by(AgentEvent.sequence)
                .limit(min(max(page_size, 1), 200))
            ).all()
            return [{"sequence": row.sequence, "body": row.body} for row in rows]

    def claim(
        self,
        scope,
        call_key,
        tool,
        payload,
        *,
        reservation=0,
        cost_lease=None,
        execution_binding=None,
        resume_started=False,
    ):
        try:
            return self._claim(
                scope,
                call_key,
                tool,
                payload,
                reservation=reservation,
                cost_lease=cost_lease,
                execution_binding=execution_binding,
                resume_started=resume_started,
            )
        except DomainError as error:
            if error.code == "EXTERNAL_OUTCOME_UNKNOWN" and error.detail.get("call_id"):
                from uuid import UUID

                self.release_call(
                    scope,
                    UUID(error.detail["call_id"]),
                    unknown=True,
                    error="EXTERNAL_OUTCOME_UNKNOWN",
                )
            raise

    def _claim(
        self,
        scope,
        call_key,
        tool,
        payload,
        *,
        reservation=0,
        cost_lease=None,
        execution_binding=None,
        resume_started=False,
    ):
        fingerprint = digest([tool, payload])
        binding = execution_binding or {"kind": "unbound"}
        resumable_read = (
            tool in {"research.fanout", "mcp.tools.list", "mcp.read"}
            and binding.get("kind") == "read"
            and binding.get("read_kind") == "ordinary/v1"
            and binding.get("isolation") == "main"
            and reservation == 0
            and cost_lease is None
        )
        resumable_mcp = (
            binding.get("kind") == "unbound"
            and binding.get("dispatch") == "mcp-read/v1"
            and binding.get("isolation") == "mcp"
            and scope.isolation == "mcp"
            and tool.startswith("mcp.")
            and reservation == 0
            and cost_lease is None
        )
        if resume_started and not (resumable_read or resumable_mcp):
            raise DomainError("FORBIDDEN_SCOPE", "只有已绑定的只读编排可接续原调用。")
        if binding.get("kind") == "domain_t0":
            raise DomainError("FORBIDDEN_SCOPE", "T0 调用须在领域事务内领取。")
        with self.transaction(scope, lock=True) as (session, run):
            if resume_started and resumable_mcp:
                try:
                    parent = session.get(AgentToolCall, UUID(binding["parent_read_call_id"]))
                    if (
                        not parent
                        or parent.run_id != run.id
                        or parent.tenant_id != run.tenant_id
                        or parent.tool != "mcp.read"
                        or parent.state not in {"started", "completed"}
                        or parent.execution_binding.get("kind") != "read"
                        or parent.execution_binding.get("isolation") != "main"
                    ):
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    raise DomainError("FORBIDDEN_SCOPE", "MCP 接续缺少实际主图读取。") from None
            call = session.scalar(
                select(AgentToolCall)
                .where(AgentToolCall.run_id == run.id, AgentToolCall.call_key == call_key)
                .with_for_update()
            )
            if call:
                if (
                    call.tool != tool
                    or call.input_digest != fingerprint
                    or call.execution_binding != binding
                ):
                    raise DomainError("DUPLICATE_INTENT_CONFLICT", "原调用绑定了不同载荷。")
                if call.state == "completed":
                    if binding.get("kind") == "read" and (
                        call.error_code is not None
                        or call.receipt_id is not None
                        or not isinstance(call.result, dict)
                    ):
                        raise DomainError(
                            "SOURCE_UNAVAILABLE",
                            "原读取没有成功完成的可信结果。",
                            detail={"reason": "read_call_invalid"},
                        )
                    return call.id, call.result
                if resume_started and call.state == "started" and call.error_code is None:
                    # Only the orchestrator resumes. Its child model/network calls retain
                    # their original completed/unknown rules and cannot be blindly reissued.
                    return call.id, None
                raise DomainError(
                    "EXTERNAL_OUTCOME_UNKNOWN",
                    "原调用须按回执对账，不能盲目重发。",
                    detail={"call_id": str(call.id)},
                )
            if reservation < 0 or run.held_tokens + run.used_tokens + reservation > run.token_limit:
                raise DomainError("RATE_LIMITED", "运行预算不足。")
            if run.trigger in {"automation_manual", "automation_service"}:
                from pdos_next.domain.automations.runtime import reserve

                reserve(session, run, reservation=reservation, cost_lease=cost_lease)
            call = AgentToolCall(
                tenant_id=scope.tenant_id,
                run_id=run.id,
                call_key=call_key,
                tool=tool,
                input_digest=fingerprint,
                execution_binding=binding,
                reserved_tokens=reservation,
            )
            if cost_lease is not None:
                budget = session.scalar(
                    select(ValidationBudget)
                    .where(ValidationBudget.id == run.validation_budget_id)
                    .with_for_update()
                )
                if not budget or budget.requester_id != run.requester_id:
                    raise DomainError("SOURCE_UNAVAILABLE", "该运行尚未绑定可用的本人预算。")
                if not budget.active:
                    raise DomainError(
                        "SOURCE_UNAVAILABLE",
                        "该运行的预算已停用。请核对活动预算后以新请求开始工作；"
                        "已发生用量保留在原预算。",
                        detail={"reason_key": "budget_inactive"},
                    )
                cost, inp, outp, pricing = cost_lease
                if (
                    budget.calls + 1 > budget.call_limit
                    or budget.held_micro_usd + budget.spent_micro_usd + cost
                    > budget.limit_micro_usd
                    or budget.held_input_tokens + budget.used_input_tokens + inp
                    > budget.input_token_limit
                    or budget.held_output_tokens + budget.used_output_tokens + outp
                    > budget.output_token_limit
                ):
                    raise DomainError("RATE_LIMITED", "验证的费用、次数或 token 总额已达上限。")
                budget.calls += 1
                budget.held_micro_usd += cost
                budget.held_input_tokens += inp
                budget.held_output_tokens += outp
                call.cost_pricing = pricing
                call.cost_state = "reserved"
                call.cost_reserved_micro_usd = cost
                call.input_token_reservation = inp
                call.output_token_reservation = outp
            session.add(call)
            run.held_tokens += reservation
            session.flush()
            return call.id, None

    def settle(
        self,
        scope,
        call_id,
        *,
        result=None,
        usage=0,
        unknown=False,
        error=None,
        receipt_id=None,
        request_id=None,
        cost_usage=None,
    ):
        with self.transaction(scope, lock=True) as (session, run):
            call = session.scalar(
                select(AgentToolCall)
                .where(AgentToolCall.id == call_id, AgentToolCall.run_id == run.id)
                .with_for_update()
            )
            if not call:
                raise DomainError("FORBIDDEN_SCOPE", "原调用不存在于当前运行。")
            if call.execution_binding.get("kind") == "domain_t0":
                raise DomainError("FORBIDDEN_SCOPE", "T0 完成须与领域回执处于同一事务。")
            if call.state in {"completed", "failed", "reconciled"}:
                return
            if usage < 0:
                raise DomainError("VALIDATION_FAILED", "用量须非负。")
            if unknown:
                # Release the active slot immediately; retain a bounded estimate for accounting.
                usage = max(usage, call.reserved_tokens)
            run.held_tokens -= call.reserved_tokens
            run.used_tokens += usage
            call.charged_tokens, call.reserved_tokens = usage, 0
            call.result, call.receipt_id, call.error_code = result, receipt_id, error
            call.provider_request_id = request_id
            call.state = "unknown" if unknown else "failed" if error else "completed"
            if cost_usage is not None:
                call.cost_state = "actual"
                call.cost_charged_micro_usd = cost_usage.micro_usd
                call.actual_input_tokens = cost_usage.input_tokens
                call.actual_output_tokens = cost_usage.output_tokens

    def reconcile(self, scope, call_id, *, receipt_lookup, final=False):
        with self.transaction(scope, lock=True) as (session, run):
            call = session.scalar(
                select(AgentToolCall)
                .where(AgentToolCall.id == call_id, AgentToolCall.run_id == run.id)
                .with_for_update()
            )
            if not call or call.state not in {"started", "unknown"}:
                return {"state": call.state if call else "unavailable"}
            if call.execution_binding.get("kind") == "domain_t0":
                raise DomainError("VERSION_CONFLICT", "T0 恢复须由共同领域事务核对。")
            receipt = receipt_lookup(session, scope, call.call_key)
            if receipt:
                if (
                    getattr(receipt, "agent_run_id", None) != scope.run_id
                    or receipt.actor_id != scope.writer_id
                    or receipt.requester_id != scope.requester_id
                    or receipt.operation != call.tool
                    or call.tool == "model"
                ):
                    raise DomainError("FORBIDDEN_SCOPE", "对账回执不属于当前 Agent 运行。")
                call.receipt_id, call.result, call.state = receipt.id, receipt.result, "completed"
            else:
                if call.state == "started":
                    # A lost Worker has no proof that the request was unsent or free.
                    # Flush unknown in this transaction to consume the estimate
                    # before final closure, without refunding it on recovery.
                    run.held_tokens -= call.reserved_tokens
                    run.used_tokens += call.reserved_tokens
                    call.charged_tokens += call.reserved_tokens
                    call.reserved_tokens, call.state = 0, "unknown"
                    call.error_code = "EXTERNAL_OUTCOME_UNKNOWN"
                    session.flush()
                if final:
                    call.state, call.error_code = "failed", "EXTERNAL_OUTCOME_UNKNOWN"
                else:
                    return {"state": "needs_reconciliation", "call_id": str(call.id)}
            run.held_tokens -= call.reserved_tokens
            call.reserved_tokens = 0
            return {
                "state": call.state,
                "receipt_id": str(call.receipt_id) if call.receipt_id else None,
                "may_retry_with_new_request": call.state == "failed",
            }

    def finish(self, scope, result):
        with self.transaction(scope, lock=True) as (session, run):
            previous_state = run.state
            run.result, run.state = (
                result,
                "partial" if result["status"] == "partial" else "completed",
            )
            from .process_view import record_state

            if previous_state != run.state:
                record_state(session, run)


def create_run(
    session,
    ctx,
    *,
    goal,
    writer_id,
    intent_key,
    session_id=None,
    product_id=None,
    proposal_id=None,
    project_id=None,
    trigger="conversation",
    private_context=False,
    data_categories=("public",),
    customer_identities=(),
    token_limit=100000,
    read_sources=(),
    outbound_context=None,
    validation_budget_id=None,
    request_digest=None,
    continued_from_id=None,
):
    from pdos_next.database import require_context

    require_context(session, ctx)
    actor = session.get(Principal, ctx.actor_id)
    writer = session.get(Principal, writer_id)
    if (
        ctx.run_id
        or getattr(ctx, "agent_run_id", None)
        or ctx.actor_id != ctx.requester_id
        or not actor
        or actor.kind != "human"
        or not actor.active
        or not writer
        or writer.kind != "agent"
        or not writer.active
    ):
        raise DomainError("FORBIDDEN_SCOPE", "发起人与独立 AI 身份须由服务器绑定。")
    if project_id is not None:
        from .project_scope import require_project

        actual_project = require_project(session, ctx, project_id, product_id, lock=True)
        private_context = private_context or actual_project.visibility != "category"
    fingerprint = request_digest or digest(
        [
            goal,
            session_id,
            ctx.category_id,
            product_id,
            proposal_id,
            trigger,
            validation_budget_id,
            sorted(read_sources, key=lambda r: str(r["artifact_id"])),
            *([{"project_id": project_id}] if project_id is not None else []),
        ]
    )
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(value not in "0123456789abcdef" for value in fingerprint)
    ):
        raise DomainError("INVALID_PAYLOAD", "运行请求摘要无效。", 422)
    prior = session.scalar(
        select(AgentRun).where(
            AgentRun.requester_id == ctx.requester_id, AgentRun.intent_key == intent_key
        )
    )
    if prior:
        if prior.intent_digest != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同目标。")
        return prior
    if read_sources:
        from pdos_next.contracts import SourceRead
        from pdos_next.service import source_for

        if ctx.category_id is None:
            raise DomainError("FORBIDDEN_SCOPE", "个人运行不能绑定业务原件。", 403)
        require_access(session, ctx, product_id)
        canonical_reads = []
        for ref in read_sources:
            parsed = SourceRead.model_validate(
                {key: value for key, value in ref.items() if key != "product_id"}
            )
            source_product = UUID(ref["product_id"]) if ref.get("product_id") else None
            actual = source_for(
                session,
                ctx,
                product_id or source_product,
                parsed.artifact_id,
                parsed.expected_revision,
            )
            actual_product = str(actual.product_id) if actual.product_id else None
            if ref.get("product_id") != actual_product:
                raise DomainError("FORBIDDEN_SCOPE", "运行来源须保留原件的实际型号范围。", 403)
            canonical_reads.append({**parsed.model_dump(mode="json"), "product_id": actual_product})
        read_sources = canonical_reads
    if session_id:
        conversation = session.get(AgentSession, session_id)
        if (
            not conversation
            or conversation.owner_id != ctx.requester_id
            or conversation.category_id != ctx.category_id
            or conversation.product_id != product_id
            or conversation.proposal_id != proposal_id
            or getattr(conversation, "project_id", None) != project_id
        ):
            raise DomainError("FORBIDDEN_SCOPE", "会话范围不一致。")
    else:
        conversation = AgentSession(
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=product_id,
            proposal_id=proposal_id,
            project_id=project_id,
            owner_id=ctx.requester_id,
        )
        session.add(conversation)
        session.flush()
    # Taint is supplied by the trusted host source read-set, never by model arguments.
    from .session_checkpoints import LAYOUT_KEY, SESSION_LAYOUT

    run = AgentRun(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        product_id=product_id,
        proposal_id=proposal_id,
        project_id=project_id,
        session_id=conversation.id,
        continued_from_id=continued_from_id,
        requester_id=ctx.requester_id,
        writer_id=writer_id,
        trigger=trigger,
        goal=goal,
        intent_key=intent_key,
        intent_digest=fingerprint,
        private_context=private_context,
        data_categories=list(data_categories),
        customer_identities=list(customer_identities),
        token_limit=token_limit,
        read_sources=list(read_sources),
        versions={
            LAYOUT_KEY: SESSION_LAYOUT,
            **({"proposal_context": outbound_context} if outbound_context is not None else {}),
        },
        validation_budget_id=validation_budget_id,
    )
    session.add(run)
    session.flush()
    return run


def cancel_run(session, ctx, run_id):
    from pdos_next.database import require_context

    require_context(session, ctx)
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    if (
        not run
        or run.requester_id != ctx.actor_id
        or ctx.run_id
        or getattr(ctx, "agent_run_id", None)
        or ctx.actor_id != ctx.requester_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "只能取消本人运行。")
    if not run.reverted_at and run.state not in {"completed", "partial", "failed", "cancelled"}:
        calls = session.scalars(
            select(AgentToolCall)
            .where(AgentToolCall.run_id == run.id, AgentToolCall.state == "started")
            .with_for_update()
        ).all()
        for call in calls:
            run.used_tokens += call.reserved_tokens
            call.charged_tokens += call.reserved_tokens
            call.reserved_tokens, call.state, call.error_code = 0, "unknown", "CANCELLED_RUN"
        run.held_tokens, run.state = 0, "cancelled"
        run.cancel_epoch += 1
        from .process_view import record_state

        record_state(session, run)
    return {
        "run_id": str(run.id),
        "status": run.state,
        "cancel_epoch": run.cancel_epoch,
        "held_tokens": run.held_tokens,
    }


def prepare_run_revert(session, ctx, run_id, *, lock=False):
    """Return the complete, readable actual receipt set in the caller's existing UOW.

    The narrowly scoped database index includes hidden receipt IDs so RLS cannot
    silently truncate this set. Public domain owners validate reversibility and
    dependencies, then reverse every business object in this same transaction.
    """
    from pdos_next.database import require_context
    from pdos_next.models import Receipt

    require_context(session, ctx)
    actor = session.get(Principal, ctx.actor_id)
    query = select(AgentRun).where(AgentRun.id == run_id)
    run = session.scalar(query.with_for_update() if lock else query)
    if (
        not run
        or run.tenant_id != ctx.tenant_id
        or run.category_id != ctx.category_id
        or run.requester_id != ctx.requester_id
        or ctx.actor_id != ctx.requester_id
        or ctx.run_id
        or getattr(ctx, "agent_run_id", None)
        or not actor
        or not actor.active
        or actor.kind != "human"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "只能以当前授权撤回本人运行。")
    if run.category_id and not session.scalar(
        text("SELECT category_access(:tenant,:category,true)"),
        {"tenant": ctx.tenant_id, "category": ctx.category_id},
    ):
        raise DomainError("FORBIDDEN_SCOPE", "整次撤回需要当前品类写入授权。")
    ids = set(session.scalars(text("SELECT kernel_run_receipt_ids(:id)"), {"id": run.id}))
    receipts = (
        session.scalars(
            select(Receipt).where(Receipt.id.in_(ids)).order_by(Receipt.created_at, Receipt.id)
        ).all()
        if ids
        else []
    )
    recorded = set(
        session.scalars(
            select(AgentToolCall.receipt_id).where(
                AgentToolCall.run_id == run.id, AgentToolCall.receipt_id.is_not(None)
            )
        )
    )
    if {r.id for r in receipts} != ids or not recorded.issubset(ids):
        raise DomainError("FORBIDDEN_SCOPE", "运行有缺失或当前不可读回执，不能部分撤回。")
    for receipt in receipts:
        if (
            receipt.tenant_id != run.tenant_id
            or receipt.category_id != run.category_id
            or (run.product_id is not None and receipt.product_id != run.product_id)
            or not (
                receipt.actor_id == run.writer_id
                or (
                    receipt.actor_id == run.requester_id
                    and receipt.operation
                    in {"evidence.claim.record", "product.definition.item.patch"}
                    and receipt.result.get("origin") == "ai_draft"
                    and receipt.result.get("writer_id") == str(run.writer_id)
                    and receipt.result.get("confirmed_by") == str(run.requester_id)
                )
            )
            or receipt.requester_id != run.requester_id
            or receipt.agent_run_id != run.id
            or receipt.run_id is not None
        ):
            raise DomainError("FORBIDDEN_SCOPE", "回执与实际运行身份或范围不一致。")
    return run, receipts


def finish_run_revert(session, ctx, run_id, *, revert_receipt_id, expected_cancel_epoch):
    """Stamp only technical state after the public owner flushed its Human receipt."""
    from pdos_next.models import Receipt

    run, _receipts = prepare_run_revert(session, ctx, run_id, lock=True)
    if run.reverted_at:
        if run.revert_receipt_id != revert_receipt_id:
            raise DomainError("VERSION_CONFLICT", "运行已由另一撤回回执完成。")
        return run_revert_status(run)
    if run.cancel_epoch != expected_cancel_epoch:
        raise DomainError("VERSION_CONFLICT", "运行已改变，请重新确认整次撤回。")
    receipt = session.get(Receipt, revert_receipt_id)
    if (
        not receipt
        or receipt.tenant_id != run.tenant_id
        or receipt.category_id != run.category_id
        or receipt.product_id != run.product_id
        or receipt.actor_id != ctx.actor_id
        or receipt.requester_id != ctx.requester_id
        or receipt.operation != "ai.run.revert"
        or receipt.subject_type != "agent_run"
        or receipt.subject_id != run.id
        or receipt.agent_run_id is not None
        or receipt.run_id is not None
    ):
        raise DomainError("FORBIDDEN_SCOPE", "须使用公共命令的实际整次撤回回执。")
    calls = session.scalars(
        select(AgentToolCall)
        .where(AgentToolCall.run_id == run.id, AgentToolCall.state == "started")
        .order_by(AgentToolCall.id)
        .with_for_update()
    ).all()
    consumed = 0
    for call in calls:
        # A started send has unknown outcome; retain its conservative token/fee cost.
        consumed += call.reserved_tokens
        call.charged_tokens += call.reserved_tokens
        call.reserved_tokens, call.state, call.error_code = 0, "unknown", "CANCELLED_RUN"
    session.flush()
    run.used_tokens += consumed
    run.held_tokens = 0
    run.cancel_epoch += 1
    run.reverted_at, run.reverted_by, run.revert_receipt_id = (
        receipt.created_at,
        ctx.actor_id,
        receipt.id,
    )
    sequence = (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run.id
            )
        )
        + 1
    )
    session.add(
        AgentEvent(
            tenant_id=run.tenant_id,
            run_id=run.id,
            sequence=sequence,
            body={
                "type": "run_reverted",
                "receipt_id": str(receipt.id),
                "cancel_epoch": run.cancel_epoch,
            },
        )
    )
    session.flush()
    return run_revert_status(run)


def run_revert_status(run):
    return {
        "reverted": run.reverted_at is not None,
        "reverted_at": run.reverted_at.isoformat() if run.reverted_at else None,
        "reverted_by": str(run.reverted_by) if run.reverted_by else None,
        "revert_receipt_id": str(run.revert_receipt_id) if run.revert_receipt_id else None,
        "cancel_epoch": run.cancel_epoch,
    }


def record_answers(session, ctx, run_id, *, answers, idempotency_key):
    from pdos_next.database import require_context

    from .models import AgentInput

    require_context(session, ctx)
    if answers.get("type") == "category_adoption" or idempotency_key.startswith(
        "category-adoption:"
    ):
        raise DomainError("FORBIDDEN_SCOPE", "品类采用须经本人确认创建并取得实际回执。")
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    if (
        not run
        or run.requester_id != ctx.actor_id
        or ctx.run_id
        or getattr(ctx, "agent_run_id", None)
        or ctx.actor_id != ctx.requester_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "只能回答本人运行中的待答问题。")
    if run.reverted_at:
        raise DomainError("CANCELLED_RUN", "运行已整次撤回，不能继续答复。")
    fingerprint = digest(answers)
    prior = session.scalar(
        select(AgentInput).where(
            AgentInput.run_id == run.id, AgentInput.idempotency_key == idempotency_key
        )
    )
    if prior:
        if prior.payload_digest != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原答复编号绑定了不同回答。")
        return prior
    if run.state != "waiting_input":
        raise DomainError("VERSION_CONFLICT", "运行当前没有待答问题。")
    if run.error_code == "EXTERNAL_OUTCOME_UNKNOWN":
        raise DomainError("VERSION_CONFLICT", "原调用结果待核对，普通答复不能重发此调用。")
    row = AgentInput(
        tenant_id=ctx.tenant_id,
        run_id=run.id,
        requester_id=ctx.requester_id,
        idempotency_key=idempotency_key,
        payload_digest=fingerprint,
        answers=answers,
    )
    session.add(row)
    session.flush()
    return row
