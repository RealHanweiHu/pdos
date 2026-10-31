"""Service admissions bind actual 小Pai/delegator identities, never a borrowed human session."""

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Outbox, Receipt, now
from pdos_next.service import Context, digest, require_access

from .models import AutomationRuleCurrent as Current
from .models import AutomationRuleVersion as Version
from .schemas import AutomationSpec, EventTrigger
from .service_models import AutomationCausalChain as Chain
from .service_models import AutomationServiceAttempt as Attempt
from .service_models import AutomationServiceGrant as Grant
from .trigger_sources import condition_state, relative_due
from .trigger_time import Schedule

TRIGGER = "automation_service"
STOP_REASONS = frozenset(
    {"GOAL_REACHED", "SCOPE_INVALID", "EXPIRED", "SUPERSEDED", "MAX_RUNS", "MODEL_BUDGET_EXHAUSTED"}
)


def reference(grant):
    return {
        "tenant_id": str(grant.tenant_id),
        "category_id": str(grant.category_id),
        "owner_id": str(grant.owner_id),
        "writer_id": str(grant.writer_id),
        "grant_id": str(grant.id),
    }


def context(ref):
    if not isinstance(ref, dict) or set(ref) != {
        "tenant_id",
        "category_id",
        "owner_id",
        "writer_id",
        "grant_id",
    }:
        raise DomainError("FORBIDDEN_SCOPE", "服务工作须使用已保存授权的固定引用。", 403)
    try:
        values = {key: UUID(str(value)) for key, value in ref.items()}
    except (ValueError, TypeError):
        raise DomainError("FORBIDDEN_SCOPE", "服务授权引用无效。", 403) from None
    return Context(
        values["tenant_id"],
        values["writer_id"],
        values["owner_id"],
        category_id=values["category_id"],
    )


def session(engine, ref):
    ctx = context(ref)
    return tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    )


def saved(s, ref, *, admission=False):
    ctx = context(ref)
    grant = s.get(Grant, UUID(ref["grant_id"]))
    if not grant or (grant.tenant_id, grant.category_id, grant.owner_id, grant.writer_id) != (
        ctx.tenant_id,
        ctx.category_id,
        ctx.requester_id,
        ctx.actor_id,
    ):
        raise DomainError("FORBIDDEN_SCOPE", "服务身份与实际具名授权不一致。", 403)
    version = s.get(Version, grant.published_version_id)
    if (
        not version
        or version.rule_id != grant.rule_id
        or version.action != "activate"
        or version.owner_id != grant.owner_id
        or version.receipt_id != grant.receipt_id
    ):
        raise DomainError("FORBIDDEN_SCOPE", "服务授权缺少原激活确认。", 403)
    spec = AutomationSpec.model_validate(version.spec)
    if spec.trigger_kind == "manual":
        raise DomainError("FORBIDDEN_SCOPE", "人工规则不能作为服务授权。", 403)
    if admission:
        require_access(s, ctx, spec.product_id)
        if Bootstrap.writer_for(s, ctx) != grant.writer_id:
            raise DomainError("FORBIDDEN_SCOPE", "小Pai执行身份已变化。", 403)
    return grant, version, spec


def run_binding(s, run):
    attempt = s.scalar(select(Attempt).where(Attempt.run_id == run.id))
    if attempt is None or attempt.state != "admitted":
        raise DomainError("FORBIDDEN_SCOPE", "自动运行缺少实际服务受理记录。", 403)
    grant, version, spec = saved(
        s,
        {
            "tenant_id": str(run.tenant_id),
            "category_id": str(run.category_id),
            "owner_id": str(run.requester_id),
            "writer_id": str(run.writer_id),
            "grant_id": str(attempt.service_grant_id),
        },
    )
    if (
        attempt.published_version_id != version.id
        or attempt.request_digest != run.intent_digest
        or attempt.rule_id != grant.rule_id
        or run.trigger != TRIGGER
        or run.product_id != spec.product_id
        or run.goal != spec.goal
        or run.validation_budget_id != spec.validation_budget_id
        or run.token_limit != spec.token_limit
        or run.proposal_id is not None
        or getattr(run, "project_id", None) is not None and (
            spec.trigger_kind != "relative_milestone"
            or str(run.project_id) != str(spec.trigger_config["project_id"])
        )
    ):
        raise DomainError("FORBIDDEN_SCOPE", "运行超出固定服务授权。", 403)
    if grant.expires_at is not None and now() >= grant.expires_at:
        raise DomainError("FORBIDDEN_SCOPE", "服务授权已到明确截止时刻。", 403)
    return attempt, spec


def enqueue(s, grant, spec, *, key, origin, due_at=None, parent_run_id=None):
    """Persist the source intent before Outbox acknowledgement; no model runs here."""
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"automation-queue:{grant.id}:{key}"},
    )
    prior = s.scalar(
        select(Attempt).where(Attempt.service_grant_id == grant.id, Attempt.trigger_key == key)
    )
    fingerprint = digest([grant.id, key, origin])
    if prior:
        if prior.request_digest != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原触发引用对应不同来源。")
        return prior
    parent = (
        s.scalar(select(Attempt).where(Attempt.run_id == parent_run_id)) if parent_run_id else None
    )
    if parent_run_id is not None and origin.get("kind") == "domain_event":
        metadata = s.execute(
            text("SELECT * FROM automation_event_parent(:grant,:event)"),
            {"grant": grant.id, "event": UUID(origin["event_id"])},
        ).one_or_none()
        if metadata is not None:
            if metadata.run_id != parent_run_id:
                raise DomainError("FORBIDDEN_SCOPE", "事件的父运行与实际回执不一致。", 403)
            parent = metadata
    if parent is not None:
        chain_id, depth = parent.chain_id, parent.depth + 1
    else:
        chain = Chain(
            id=uuid4(),
            tenant_id=grant.tenant_id,
            category_id=grant.category_id,
            owner_id=grant.owner_id,
            root_grant_id=grant.id,
            budget=spec.budget.model_dump(mode="json"),
            max_depth=spec.max_cascade_depth,
        )
        s.add(chain)
        s.flush([chain])
        chain_id, depth, parent_run_id = chain.id, 0, None
    attempt = Attempt(
        id=uuid4(),
        tenant_id=grant.tenant_id,
        category_id=grant.category_id,
        owner_id=grant.owner_id,
        writer_id=grant.writer_id,
        rule_id=grant.rule_id,
        published_version_id=grant.published_version_id,
        service_grant_id=grant.id,
        chain_id=chain_id,
        parent_run_id=parent_run_id,
        depth=depth,
        trigger_kind=spec.trigger_kind,
        trigger_key=key,
        origin=origin,
        request_digest=fingerprint,
        state="queued",
        error_code=None,
        run_id=None,
        due_at=due_at,
        admitted_at=None,
    )
    s.add(attempt)
    s.flush([attempt])
    return attempt


def suppress(s, attempt, reason):
    if attempt.state == "queued":
        attempt.state, attempt.error_code = "suppressed", reason


def event_source(s, grant, event):
    """Ordinary caller RLS protects private event subjects and the actual common receipt."""
    row = s.get(Outbox, UUID(event.event_id))
    receipt = s.get(Receipt, row.receipt_id) if row else None
    if (
        not row
        or not receipt
        or str(row.lease_id) != event.lease_id
        or row.type != event.event_type
        or str(row.subject_id) != event.subject_id
        or row.subject_revision != event.subject_revision
        or row.category_id != grant.category_id
        or str(row.tenant_id) != event.tenant_id
        or (str(receipt.product_id) if receipt.product_id else None) != event.product_id
        or row.delivered_at is not None
        or row.lease_until is None
        or row.lease_until <= now()
        or row.schema_version != event.schema_version
        or str(row.correlation_id) != event.correlation_id
        or str(row.actor_id) != event.actor_id
        or str(receipt.requester_id) != event.requester_id
        or receipt.id != row.receipt_id
        or receipt.category_id != row.category_id
        or receipt.command_id != row.correlation_id
    ):
        return None
    imported = receipt.operation in {
        "integration.receipt.record",
        "test.results.import",
        "evidence.original.upload",
        "evidence.artifact.register",
        "research.snapshot.register",
    }
    return {
        "kind": "domain_event",
        "event_id": str(row.id),
        "event_type": row.type,
        "receipt_id": str(receipt.id),
        "operation": receipt.operation,
        "subject_type": receipt.subject_type,
        "subject_id": str(row.subject_id),
        "subject_revision": row.subject_revision,
        "source_kind": "external_input" if imported else "domain_command",
        "parent_run_id": str(receipt.agent_run_id) if receipt.agent_run_id else None,
        "occurred_at": row.created_at.isoformat(),
    }


def queue_event(engine, ref, event):
    with session(engine, ref) as s:
        grant, _, spec = saved(s, ref, admission=True)
        if stopped_reason(s, grant.id):
            return None
        if spec.trigger_kind != "domain_event":
            return None
        config = EventTrigger.model_validate(spec.trigger_config)
        if event.event_type not in config.event_types:
            return None
        pointer = s.scalar(select(Current).where(Current.rule_id == grant.rule_id))
        if (
            pointer is None
            or pointer.state != "active"
            or pointer.published_version_id != grant.published_version_id
            or (grant.expires_at is not None and now() >= grant.expires_at)
        ):
            return None
        source = event_source(s, grant, event)
        if source is None:
            return None
        attempt = enqueue(
            s,
            grant,
            spec,
            key="event:" + event.event_id,
            origin=source,
            due_at=now() + timedelta(seconds=config.merge_window_seconds),
            parent_run_id=UUID(source["parent_run_id"]) if source["parent_run_id"] else None,
        )
        if source["source_kind"] != "domain_command":
            suppress(s, attempt, "EXTERNAL_TRIGGER_DISABLED")
        return str(attempt.id)


def _finish_goal_queue(s, grant_id):
    # The lifecycle stop is already saved in this transaction or a previous one.
    # Its narrow SQL start path suppresses each old queued attempt without a Run.
    targets = list(
        s.scalars(
            select(Attempt.id)
            .where(Attempt.service_grant_id == grant_id, Attempt.state == "queued")
            .order_by(Attempt.created_at, Attempt.id)
        )
    )
    for identity in targets:
        s.execute(text("SELECT automation_service_start(:attempt)"), {"attempt": identity})


def stop(engine, ref, reason):
    if reason not in STOP_REASONS:
        raise ValueError("Unregistered automation stop reason")
    with session(engine, ref) as s:
        s.execute(
            text("SELECT automation_service_stop(:grant,:reason)"),
            {"grant": UUID(ref["grant_id"]), "reason": reason},
        )
        if reason == "GOAL_REACHED":
            _finish_goal_queue(s, UUID(ref["grant_id"]))


def stopped_reason(s, grant_id):
    return s.scalar(
        select(Attempt.error_code)
        .where(
            Attempt.service_grant_id == grant_id,
            Attempt.state == "suppressed",
            Attempt.origin["kind"].astext == "lifecycle",
            Attempt.error_code.in_(STOP_REASONS),
        )
        .limit(1)
    )


def tick(engine, ref):
    """A Temporal Activity owns each durable wake. Failures never invoke an LLM."""
    ctx, point = context(ref), now()
    wake_at = point + timedelta(seconds=30)
    try:
        with session(engine, ref) as s:
            grant, _, spec = saved(s, ref, admission=True)
            reason = stopped_reason(s, grant.id)
            if reason:
                if reason == "GOAL_REACHED":
                    _finish_goal_queue(s, grant.id)
                return {"state": "stopped", "wake_at": None, "reason": reason}
            pointer = s.scalar(select(Current).where(Current.rule_id == grant.rule_id))
            if not pointer or pointer.published_version_id != grant.published_version_id:
                raise DomainError("CANCELLED_RUN", "SUPERSEDED")
            if pointer.state != "active":
                return {"state": "stopped", "wake_at": None, "reason": "PAUSED"}
            if grant.expires_at is not None and point >= grant.expires_at:
                raise DomainError("CANCELLED_RUN", "EXPIRED")
            if pointer.admitted_count >= spec.max_runs:
                raise DomainError("CANCELLED_RUN", "MAX_RUNS")
            if grant.expires_at is not None:
                wake_at = min(wake_at, grant.expires_at)
            # A fixed recipient's fulfilled promise stops even with an unknown
            # date or while a separate explicit Task condition is waiting.
            relative = (
                relative_due(s, ctx, spec) if spec.trigger_kind == "relative_milestone" else None
            )
            if relative is not None and relative["goal_reached"]:
                raise DomainError("CANCELLED_RUN", "GOAL_REACHED")
            condition = condition_state(s, ctx, spec)
            if condition == "goal_reached":
                # Persisted below through a separate narrow technical transaction.
                raise DomainError("CANCELLED_RUN", "GOAL_REACHED")
            if condition == "waiting":
                if relative is not None and relative["origin"].get("source_kind") == "commitment":
                    for attempt in s.scalars(
                        select(Attempt).where(
                            Attempt.service_grant_id == grant.id, Attempt.state == "queued"
                        )
                    ):
                        if (
                            attempt.trigger_kind == "relative_milestone"
                            and attempt.trigger_key != relative["target_key"]
                        ):
                            suppress(s, attempt, "SOURCE_SUPERSEDED")
                return {"state": "active", "wake_at": wake_at.isoformat()}
            if spec.trigger_kind == "schedule":
                config = Schedule.model_validate(spec.trigger_config)
                previous = s.scalar(
                    select(Attempt.due_at)
                    .where(
                        Attempt.service_grant_id == grant.id,
                        Attempt.trigger_kind == "schedule",
                        Attempt.origin["kind"].astext == "schedule",
                    )
                    .order_by(Attempt.due_at.desc())
                    .limit(1)
                )
                wake_at = config.wake_before(point, wake_at)
                due = config.due(point, last_due=previous)
                if due is not None:
                    enqueue(
                        s,
                        grant,
                        spec,
                        key="schedule:" + due.isoformat(),
                        due_at=due,
                        origin={
                            "kind": "schedule",
                            "scheduled_at": due.isoformat(),
                            "original_timezone": config.original_timezone,
                        },
                    )
            elif spec.trigger_kind == "relative_milestone":
                if relative["scheduled_at"] is not None and relative["scheduled_at"] > point:
                    wake_at = min(wake_at, relative["scheduled_at"])
                if relative["scheduled_at"] is not None and relative["scheduled_at"] <= point:
                    enqueue(
                        s,
                        grant,
                        spec,
                        key=relative["target_key"],
                        due_at=relative["scheduled_at"],
                        origin={"kind": "relative_milestone", **relative["origin"]},
                    )
            pending = list(
                s.scalars(
                    select(Attempt)
                    .where(Attempt.service_grant_id == grant.id, Attempt.state == "queued")
                    .order_by(Attempt.created_at.desc(), Attempt.id.desc())
                )
            )
            targets = set()
            for attempt in pending:
                if (
                    relative is not None
                    and relative["origin"].get("source_kind") == "commitment"
                    and attempt.trigger_kind == "relative_milestone"
                    and attempt.trigger_key != relative["target_key"]
                ):
                    suppress(s, attempt, "SOURCE_SUPERSEDED")
                    continue
                target = (attempt.origin.get("subject_type"), attempt.origin.get("subject_id"))
                if attempt.trigger_kind == "domain_event" and target in targets:
                    suppress(s, attempt, "SOURCE_SUPERSEDED")
                    continue
                targets.add(target)
                if attempt.due_at is not None and attempt.due_at > point:
                    wake_at = min(wake_at, attempt.due_at)
                    continue
                if pointer.last_admitted_at and point < pointer.last_admitted_at + timedelta(
                    seconds=spec.cooldown_seconds
                ):
                    wake_at = min(
                        wake_at, pointer.last_admitted_at + timedelta(seconds=spec.cooldown_seconds)
                    )
                    continue
                if attempt.parent_run_id:
                    parent = s.scalar(
                        select(Attempt).where(Attempt.run_id == attempt.parent_run_id)
                    )
                    if parent and parent.rule_id == grant.rule_id:
                        suppress(s, attempt, "SELF_TRIGGERED")
                        continue
                # This SQL command rechecks current publication, identity, wallet,
                # counts, cooldown, causal depth and exact immutable attempt.
                s.flush()
                s.execute(
                    text("SELECT automation_service_start(:attempt)"), {"attempt": attempt.id}
                )
                s.expire(pointer)
                s.expire(attempt)
            reason = stopped_reason(s, grant.id)
            if reason:
                return {"state": "stopped", "wake_at": None, "reason": reason}
            return {"state": "active", "wake_at": wake_at.isoformat()}
    except DomainError as error:
        reason = (
            error.message
            if error.code == "CANCELLED_RUN" and error.message in STOP_REASONS
            else "SCOPE_INVALID"
        )
        stop(engine, ref, reason)
        return {"state": "stopped", "wake_at": None, "reason": reason}


def grant_view(s, pointer):
    grant = s.scalar(
        select(Grant).where(Grant.published_version_id == pointer.published_version_id)
    )
    if grant is None:
        return None
    state = "active" if pointer.state == "active" else "paused"
    if grant.expires_at is not None and now() >= grant.expires_at:
        state = "expired"
    stopped = s.scalar(
        select(Attempt.id)
        .where(
            Attempt.service_grant_id == grant.id,
            Attempt.origin["kind"].astext == "lifecycle",
            Attempt.error_code.in_(STOP_REASONS),
        )
        .limit(1)
    )
    if stopped:
        state = "stopped"
    return {
        "id": str(grant.id),
        "service_principal_id": str(grant.writer_id),
        "delegator_id": str(grant.owner_id),
        "version_id": str(grant.published_version_id),
        "receipt_id": str(grant.receipt_id),
        "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
        "state": state,
    }
