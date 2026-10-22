"""Human rule configuration uses the same confirmation and receipt transaction as other work."""

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from pdos_next.agent_kernel.models import TenantSkillEnablement, ValidationBudget
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.domain.preproject.access import human
from pdos_next.errors import DomainError
from pdos_next.models import now
from pdos_next.request_proof import command_inputs_once
from pdos_next.service import EVENTS, command_digest, digest, require_access

from .models import AutomationRuleCurrent as Current
from .models import AutomationRuleVersion as Version
from .schemas import AutomationSpec

DRAFT = "ai.automation.draft.save"
ACTIVATE = "ai.automation.activate"
PAUSE = "ai.automation.pause"
EFFECT = "规则仅供本人手动触发只读工作；暂停只阻止新受理。"
SERVICE_EFFECT = "按固定服务授权自动触发小Pai只读工作；暂停只阻止新受理。"


def semantic(payload):
    return payload.model_dump(mode="json", exclude={"confirmation_token"})


def owned(s, ctx, rule_id, *, lock=False):
    query = select(Current).where(
        Current.tenant_id == ctx.tenant_id,
        Current.category_id == ctx.category_id,
        Current.owner_id == ctx.requester_id,
        Current.rule_id == rule_id,
    )
    row = s.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise DomainError("NOT_FOUND", "规则不存在或不在本人当前范围。", 404)
    return row


def spec_current(s, ctx, spec, *, enabled=False):
    """A saved selection narrows real configuration; it does not confer a skill or wallet."""
    require_access(s, ctx, spec.product_id)
    from .trigger_sources import condition_state, relative_due

    if spec.trigger_kind == "domain_event":
        if not set(spec.trigger_config["event_types"]) <= set(EVENTS.values()):
            raise DomainError("FORBIDDEN_SCOPE", "事件须来自已登记的领域事件目录。", 403)
    elif spec.trigger_kind == "relative_milestone":
        relative_due(s, ctx, spec)
    condition_state(s, ctx, spec)
    if enabled and spec.trigger_kind != "manual":
        from types import SimpleNamespace

        from pdos_next.agent_kernel.bootstrap import Bootstrap

        from .trigger_time import Schedule

        expiry = spec.trigger_config.get("expires_at")
        if expiry:
            from datetime import datetime

            if datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= now():
                raise DomainError("VERSION_CONFLICT", "自动规则已超过明确截止时刻。")
        if spec.trigger_kind == "schedule":
            Schedule.model_validate(spec.trigger_config)
        # Verifies the unique writer and its current category/product access;
        # the confirmation stores that actual identity, never a client supplied one.
        Bootstrap(s.bind).binding_for(
            s, ctx, SimpleNamespace(product_id=spec.product_id, proposal_id=None, sources=[])
        )
    catalog = SkillCatalog()
    for ref in spec.skill_keys:
        actual = catalog.configuration(ref.key)
        if actual is None or (actual.version, actual.digest) != (ref.version, ref.digest):
            raise DomainError("VERSION_CONFLICT", "规则所选技能版本已变化，请重新选择。")
        if enabled:
            control = s.scalar(
                select(TenantSkillEnablement).where(
                    TenantSkillEnablement.skill_key == ref.key,
                )
            )
            if not control or not control.enabled or control.quality_paused:
                raise DomainError("FORBIDDEN_SCOPE", "规则所选技能尚未启用或已暂停。", 403)
    wallet = s.scalar(
        select(ValidationBudget).where(
            ValidationBudget.id == spec.validation_budget_id,
            ValidationBudget.tenant_id == ctx.tenant_id,
            ValidationBudget.requester_id == ctx.requester_id,
        )
    )
    if wallet is None or (enabled and not wallet.active):
        raise DomainError("SOURCE_UNAVAILABLE", "规则须绑定本人实际预算；当前预算不可用。", 503)


@dataclass
class Prepared:
    pointer: object
    previous: object
    review: dict
    confirmation_id: object = None


@command_inputs_once
def prepared(s, ctx, command, scope, payload):
    human(s, ctx)
    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "规则在当前品类保存；本切片不附加原件来源。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "品类版本已变化，请刷新。")
    pointer = owned(s, ctx, payload.rule_id, lock=True) if payload.rule_id else None
    if payload.expected_rule_revision != (pointer.revision if pointer else 0):
        raise DomainError("VERSION_CONFLICT", "规则已由另一操作更新，请刷新。")
    previous = s.get(Version, pointer.version_id) if pointer else None
    action = {DRAFT: "draft", ACTIVATE: "activate", PAUSE: "pause"}[command.operation]
    if command.operation == DRAFT:
        spec = payload.spec
        saved_spec = spec.model_dump(mode="json")
        if payload.restored_from is not None:
            old = s.get(Version, payload.restored_from)
            if (
                not old
                or pointer is None
                or old.rule_id != pointer.rule_id
                or old.spec != spec.model_dump(mode="json")
            ):
                raise DomainError("VERSION_CONFLICT", "回滚须复制本规则实际历史版本为新草稿。")
    else:
        selected = pointer.draft_version_id or pointer.published_version_id if pointer else None
        if command.operation == PAUSE:
            selected = pointer.published_version_id if pointer else None
            if pointer is None or pointer.state != "active":
                raise DomainError("VERSION_CONFLICT", "当前规则未启用。")
        if selected is None or payload.version_id != selected:
            raise DomainError("VERSION_CONFLICT", "请明确确认当前草稿或已发布版本。")
        fixed = s.get(Version, selected)
        spec = AutomationSpec.model_validate(fixed.spec)
        saved_spec = deepcopy(fixed.spec)
    if command.operation != PAUSE:
        spec_current(s, ctx, spec, enabled=command.operation == ACTIVATE)
    rule_id = pointer.rule_id if pointer else uuid4()
    after = {
        "rule_id": str(rule_id),
        "revision": pointer.revision + 1 if pointer else 1,
        "action": action,
        "state": {"draft": "draft", "activate": "active", "pause": "paused"}[action],
        "spec": saved_spec,
    }
    before = (
        None
        if pointer is None
        else {
            "revision": pointer.revision,
            "state": pointer.state,
            "draft_version_id": str(pointer.draft_version_id) if pointer.draft_version_id else None,
            "published_version_id": str(pointer.published_version_id)
            if pointer.published_version_id
            else None,
        }
    )
    review = {
        "operation": command.operation,
        "declaration": semantic(payload),
        "before": before,
        "after": after,
        "effect": EFFECT if spec.trigger_kind == "manual" else SERVICE_EFFECT,
    }
    if command.operation == ACTIVATE and spec.trigger_kind != "manual":
        from pdos_next.agent_kernel.bootstrap import Bootstrap

        review["service_authorization"] = {
            "service_principal_id": str(Bootstrap.writer_for(s, ctx)),
            "delegator_id": str(ctx.requester_id),
            "category_id": str(ctx.category_id),
            "product_id": str(spec.product_id) if spec.product_id else None,
            "purpose": spec.purpose,
            "budget": spec.budget.model_dump(mode="json"),
            "expires_at": spec.trigger_config.get("expires_at"),
        }
    return Prepared(pointer, previous, review)


def validate(s, ctx, command, scope, payload):
    return prepared(s, ctx, command, scope, payload)


def preview_view(s, ctx, command, scope, payload):
    return prepared(s, ctx, command, scope, payload).review


def apply_validated(s, ctx, command, scope, payload, plan):
    after = plan.review["after"]
    from uuid import UUID

    envelope = command.model_dump(mode="json", exclude={"idempotency_key"})
    envelope["payload"] = semantic(payload)
    row = Version(
        id=uuid4() if plan.pointer else UUID(after["rule_id"]),
        tenant_id=ctx.tenant_id,
        category_id=ctx.category_id,
        owner_id=ctx.requester_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        rule_id=UUID(after["rule_id"]),
        revision=after["revision"],
        previous_id=plan.previous.id if plan.previous else None,
        previous_revision=plan.previous.revision if plan.previous else None,
        action=after["action"],
        state=after["state"],
        spec=deepcopy(after["spec"]),
        spec_sha256=digest(after["spec"]),
        operation=command.operation,
        command_id=command.command_id,
        command={
            "envelope": envelope,
            "review": deepcopy(plan.review),
            "original_key_sha256": sha256(command.idempotency_key.encode()).hexdigest(),
        },
        request_digest=command_digest(command),
        intent_digest=digest(
            {
                "operation": command.operation,
                "category": command.category_id,
                "product": None,
                "payload": semantic(payload),
                "named_actor": ctx.requester_id,
                "source_revision": None,
                "private_owner": ctx.requester_id,
            }
        ),
        receipt_id=uuid4(),
        confirmation_id=plan.confirmation_id,
    )
    # The Current BEFORE guard reads this exact immutable version. Without an
    # ORM relationship SQLAlchemy can otherwise flush the pointer first.
    s.add(row)
    s.flush([row])
    pointer = plan.pointer
    if pointer is None:
        pointer = Current(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            owner_id=ctx.requester_id,
            rule_id=row.rule_id,
            revision=1,
            version_id=row.id,
            state="draft",
            draft_version_id=row.id,
            published_version_id=None,
            admitted_count=0,
            last_admitted_at=None,
        )
        s.add(pointer)
    else:
        pointer.version_id, pointer.revision = row.id, row.revision
        if row.action == "draft":
            pointer.draft_version_id = row.id
        elif row.action == "activate":
            pointer.state, pointer.published_version_id, pointer.draft_version_id = (
                "active",
                row.id,
                None,
            )
        else:
            pointer.state = "paused"
    if row.action == "activate" and row.spec["trigger_kind"] != "manual":
        from datetime import datetime

        from .service_models import AutomationServiceGrant

        authorization = plan.review["service_authorization"]
        expiry = authorization["expires_at"]
        s.add(
            AutomationServiceGrant(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                category_id=ctx.category_id,
                owner_id=ctx.requester_id,
                writer_id=UUID(authorization["service_principal_id"]),
                rule_id=row.rule_id,
                published_version_id=row.id,
                receipt_id=row.receipt_id,
                expires_at=datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                if expiry
                else None,
            )
        )
    row.prepared_receipt_id = row.receipt_id
    row.action_result = {"rule_id": str(row.rule_id), "state": pointer.state}
    return row, "automation_rule", "private"


def version_view(row):
    return None if row is None else {"id": str(row.id), "revision": row.revision, "spec": row.spec}


def rule_view(s, pointer):
    from .service_runtime import grant_view

    draft = s.get(Version, pointer.draft_version_id) if pointer.draft_version_id else None
    published = (
        s.get(Version, pointer.published_version_id) if pointer.published_version_id else None
    )
    latest = s.get(Version, pointer.version_id)
    return {
        "id": str(pointer.rule_id),
        "revision": pointer.revision,
        "name": latest.spec["name"],
        "state": pointer.state,
        "draft": version_view(draft),
        "published": version_view(published),
        "service_grant": grant_view(s, pointer),
        "admitted_count": pointer.admitted_count,
        "last_admitted_at": pointer.last_admitted_at.isoformat()
        if pointer.last_admitted_at
        else None,
    }


def workspace(s, ctx):
    scope = require_access(s, ctx, None)
    human(s, ctx)
    pointers = s.scalars(
        select(Current)
        .where(Current.owner_id == ctx.requester_id, Current.category_id == ctx.category_id)
        .order_by(Current.created_at.desc(), Current.id)
    ).all()
    catalog = SkillCatalog()
    budgets = s.scalars(
        select(ValidationBudget)
        .where(
            ValidationBudget.requester_id == ctx.requester_id,
            ValidationBudget.active.is_(True),
        )
        .order_by(ValidationBudget.created_at.desc(), ValidationBudget.id)
    ).all()
    return {
        "category_revision": scope.revision,
        "as_of": now().isoformat(),
        "event_types": sorted(set(EVENTS.values())),
        "rules": [rule_view(s, p) for p in pointers],
        "skills": [
            {
                "key": v["key"],
                "name": v["purpose"],
                "version": catalog.configuration(v["key"]).version,
                "digest": catalog.configuration(v["key"]).digest,
            }
            for v in catalog.index
        ],
        "budgets": [
            {
                "id": str(b.id),
                "limit_micro_usd": b.limit_micro_usd,
                "input_token_limit": b.input_token_limit,
                "output_token_limit": b.output_token_limit,
                "call_limit": b.call_limit,
            }
            for b in budgets
        ],
    }


def detail(s, ctx, rule_id):
    from pdos_next.agent_kernel.models import AgentRun

    from .models import AutomationTriggerOccurrence as Occurrence

    require_access(s, ctx, None)
    human(s, ctx)
    pointer = owned(s, ctx, rule_id)
    history = s.scalars(
        select(Version).where(Version.rule_id == rule_id).order_by(Version.revision.desc())
    ).all()
    runs = s.execute(
        select(Occurrence, AgentRun.state)
        .join(AgentRun, AgentRun.id == Occurrence.run_id)
        .where(Occurrence.rule_id == rule_id)
        .order_by(Occurrence.created_at.desc(), Occurrence.id)
    ).all()
    from .service_models import AutomationServiceAttempt as Attempt

    triggers = list(
        s.scalars(
            select(Attempt)
            .where(Attempt.rule_id == rule_id)
            .order_by(Attempt.created_at.desc(), Attempt.id)
        )
    )
    service_runs = s.execute(
        select(Attempt, AgentRun.state)
        .join(AgentRun, AgentRun.id == Attempt.run_id)
        .where(Attempt.rule_id == rule_id, Attempt.state == "admitted")
    ).all()
    runs = sorted(
        [*runs, *service_runs], key=lambda item: (item[0].created_at, item[0].id), reverse=True
    )
    return {
        "rule": rule_view(s, pointer),
        "triggers": [
            {
                "id": str(a.id),
                "version_id": str(a.published_version_id),
                "kind": a.trigger_kind,
                "source": a.origin,
                "decision": a.state,
                "error_code": a.error_code,
                "run_id": str(a.run_id) if a.run_id else None,
                "created_at": a.created_at.isoformat(),
                "admitted_at": a.admitted_at.isoformat() if a.admitted_at else None,
            }
            for a in triggers
        ],
        "history": [
            {
                "id": str(v.id),
                "revision": v.revision,
                "action": v.action,
                "actor_id": str(v.actor_id),
                "created_at": v.created_at.isoformat(),
                "receipt_id": str(v.receipt_id),
            }
            for v in history
        ],
        "runs": [
            {
                "id": str(o.id),
                "version_id": str(o.published_version_id),
                "run_id": str(o.run_id),
                "state": state,
                "created_at": o.created_at.isoformat(),
            }
            for o, state in runs
        ],
    }
