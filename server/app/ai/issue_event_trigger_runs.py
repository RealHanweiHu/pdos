"""Source-bound automatic requests use the same budgeted Issue application runtime."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import Connection, RowMapping, func, select

from app.ai.application_queue_claim import claim_application_queue
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.issue_event_proposal import (
    OPERATION,
    PROMPT,
    PURPOSE,
    IssueEventProposal,
    IssueEventProposalError,
    source_snapshot,
)
from app.ai.rollout_guard import CapabilityUnavailableError
from app.ai.run_budget_creation import freeze_created_application_run
from app.db.schema import tables
from app.domain.ai_issue_event_sources import read_event_source
from app.domain.ai_issue_write_access import write_settings
from app.domain.product_workspace import digest
from app.domain.project_write_lock import lock_project_write_scope

if TYPE_CHECKING:
    from app.ai.issue_event_runs import IssueEventRuns


def authority(
    c: Connection,
    *,
    tenant: UUID,
    project: UUID,
    event_row_id: int,
    policy_id: UUID,
    scope_revision_id: UUID,
    principal_id: UUID,
) -> tuple[dict[str, Any], RowMapping]:
    from app.ai.issue_event_runs import _access

    source = read_event_source(c, tenant, project, event_row_id)
    # source_snapshot refuses unverifiable, stale and unsupported sources.
    source_snapshot(source)
    original = source["source"]["event"]
    audit = source["source"]["audit"]
    actor = UUID(audit["actor_user_id"])
    _access(c, tenant, actor, project, write=True)
    user = (
        c.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == tenant,
                tables.users.c.id == actor,
                tables.users.c.is_active.is_(True),
            )
        )
        .mappings()
        .one_or_none()
    )
    if user is None:
        raise IssueEventProposalError("EVENT_ISSUE_ACTOR_UNAVAILABLE", "原发起人当前不可办理")
    policy, scope = write_settings(c, tenant, project)
    if (
        policy["id"] != policy_id
        or scope["id"] != scope_revision_id
        or policy["principal_id"] != principal_id
        or scope["principal_id"] != principal_id
        or policy["operation_settings"].get(OPERATION, {}).get("mode") != "automatic"
        or datetime.fromisoformat(original["timestamp"]) < policy["created_at"]
        or datetime.fromisoformat(original["timestamp"]) < scope["created_at"]
    ):
        raise IssueEventProposalError("EVENT_ISSUE_AUTHORITY_CHANGED", "原自动处理授权已有变化")
    return source, user


def require_current(c: Connection, row: Mapping[str, Any] | RowMapping) -> None:
    trigger = row["run_context"].get("issue_event_trigger")
    if trigger is None:
        return
    if not isinstance(trigger, dict) or trigger.get("version") != "issue-event.v1":
        raise IssueEventProposalError("EVENT_ISSUE_TRIGGER_INVALID", "原触发依据不可核对")
    source, actor = authority(
        c,
        tenant=row["tenant_id"],
        project=row["project_id"],
        event_row_id=trigger["event_row_id"],
        policy_id=UUID(trigger["policy_id"]),
        scope_revision_id=UUID(trigger["scope_revision_id"]),
        principal_id=UUID(trigger["principal_id"]),
    )
    if (
        str(actor["id"]) != trigger["actor_user_id"]
        or actor["id"] != row["requested_by_user_id"]
        or actor["auth_version"] != trigger["auth_version"]
        or source["event_id"] != trigger["event_id"]
        or source_snapshot(source) != row["run_context"]["issue_event_source"]
        or source_snapshot(source)["source_digest"] != trigger["source_digest"]
        or row["event_count"] != 0
        or row["event_row_ids"] != []
    ):
        raise IssueEventProposalError("EVENT_ISSUE_AUTHORITY_CHANGED", "原触发授权或来源已有变化")


def enqueue_event(
    c: Connection,
    gateway: Any,
    *,
    event: Mapping[str, Any],
    source: dict[str, Any],
    policy_id: UUID,
    scope_revision_id: UUID,
    principal_id: UUID,
) -> dict[str, Any]:
    from app.ai.issue_event_runs import AGENT_KEY, RUN_VERSION
    from app.domain import ai_issue_generation_bindings

    tenant, project = event["tenant_id"], event["project_id"]
    state = c.execute(
        select(tables.tenants.c.status).where(tables.tenants.c.id == tenant).with_for_update()
    ).scalar_one_or_none()
    if state != "active" or not lock_project_write_scope(c, tenant_id=tenant, project_id=project):
        raise LookupError("项目当前不可生成")
    current, actor = authority(
        c,
        tenant=tenant,
        project=project,
        event_row_id=event["id"],
        policy_id=policy_id,
        scope_revision_id=scope_revision_id,
        principal_id=principal_id,
    )
    snapshot = source_snapshot(current)
    if snapshot != source_snapshot(source) or actor["id"] != event["actor_user_id"]:
        raise IssueEventProposalError("EVENT_ISSUE_SOURCE_CHANGED", "排队前原来源已有变化")
    request_id = uuid5(
        NAMESPACE_URL,
        "pdos:issue-event:"
        + digest(
            {
                "tenant": str(tenant),
                "project": str(project),
                "event": event["id"],
                "actor": str(actor["id"]),
                "policy": str(policy_id),
                "scope": str(scope_revision_id),
                "principal": str(principal_id),
            }
        ),
    )
    trigger = {
        "version": "issue-event.v1",
        "event_row_id": event["id"],
        "event_id": current["event_id"],
        "actor_user_id": str(actor["id"]),
        "policy_id": str(policy_id),
        "scope_revision_id": str(scope_revision_id),
        "principal_id": str(principal_id),
        "auth_version": actor["auth_version"],
        "source_digest": snapshot["source_digest"],
    }
    run = tables.agent_runs
    old = (
        c.execute(
            select(run).where(
                run.c.tenant_id == tenant,
                run.c.project_id == project,
                run.c.agent_key == AGENT_KEY,
                run.c.request_id == str(request_id),
            )
        )
        .mappings()
        .one_or_none()
    )
    if old is not None:
        if (
            old["context_version"] != RUN_VERSION
            or old["run_context"].get("issue_event_trigger") != trigger
        ):
            raise IssueEventProposalError(
                "EVENT_ISSUE_REQUEST_CONFLICT", "原触发请求已固定其他依据"
            )
        return {"run_id": old["id"], "source_digest": snapshot["source_digest"], "reused": True}
    if getattr(gateway, "creation_budget_profile", None) is None:
        raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    row = (
        c.execute(
            run.insert()
            .values(
                id=uuid4(),
                tenant_id=tenant,
                project_id=project,
                agent_key=AGENT_KEY,
                request_id=str(request_id),
                requested_by_user_id=actor["id"],
                status="running",
                event_count=0,
                event_row_ids=[],
                window_started_at=now,
                window_ended_at=now,
                context_version=RUN_VERSION,
                started_at=now,
                created_at=now,
                updated_at=now,
                run_context={
                    "issue_event_event_row_id": event["id"],
                    "issue_event_expected_digest": snapshot["source_digest"],
                    "issue_event_source": snapshot,
                    "issue_event_source_title": source["title"],
                    "issue_event_prompt_version": PROMPT.version,
                    "issue_event_schema_digest": digest(IssueEventProposal.model_json_schema()),
                    "issue_event_trigger": trigger,
                    "application_queue_version": "1",
                },
            )
            .returning(run)
        )
        .mappings()
        .one()
    )
    ai_issue_generation_bindings.capture(c, row, snapshot, now)
    freeze_created_application_run(
        c,
        gateway,
        tenant_id=tenant,
        run_id=row["id"],
        actor_user_id=actor["id"],
        purpose=PURPOSE,
        auth_version=actor["auth_version"],
        issue_lease=False,
    )
    c.execute(run.update().where(run.c.id == row["id"]).values(status="queued", started_at=None))
    return {"run_id": row["id"], "source_digest": snapshot["source_digest"], "reused": False}


def execute_queued(service: IssueEventRuns, run_id: UUID) -> dict[str, Any]:
    from app.ai.issue_event_runs import AGENT_KEY, RUN_VERSION, receipt, result_for_run
    from app.domain import ai_issue_generation_bindings
    from app.domain.ai_write_policy import WritePolicyError

    with service.engine.begin() as c:
        run = tables.agent_runs
        # Discover immutable scope, then follow tenant -> project -> run lock order.
        identity = c.execute(
            select(run.c.tenant_id, run.c.project_id).where(run.c.id == run_id)
        ).one()
        c.execute(
            select(tables.tenants.c.id)
            .where(tables.tenants.c.id == identity.tenant_id)
            .with_for_update()
        )
        project_available = lock_project_write_scope(
            c, tenant_id=identity.tenant_id, project_id=identity.project_id
        )
        row = c.execute(select(run).where(run.c.id == run_id).with_for_update()).mappings().one()
        if row["agent_key"] != AGENT_KEY or row["context_version"] != RUN_VERSION:
            raise LookupError("没有对应异常事件运行")
        if row["status"] != "queued":
            return receipt(
                row, result_for_run(c, row), ai_issue_generation_bindings.read_for_run(c, row)
            )
        try:
            with c.begin_nested():
                if not project_available:
                    raise LookupError("项目已不可用")
                trigger = row["run_context"].get("issue_event_trigger")
                if not trigger:
                    raise IssueEventProposalError(
                        "EVENT_ISSUE_TRIGGER_INVALID", "原触发依据不可核对"
                    )
                require_current(c, row)
                claimed = claim_application_queue(
                    c, service.gateway, row, auth_version=trigger["auth_version"], purpose=PURPOSE
                )
        except (
            IssueEventProposalError,
            WritePolicyError,
            BudgetLedgerError,
            CapabilityUnavailableError,
            PermissionError,
            LookupError,
            ValueError,
        ) as error:
            code = getattr(error, "code", "EVENT_ISSUE_AUTHORITY_CHANGED")
            stopped = (
                c.execute(
                    run.update()
                    .where(run.c.id == run_id)
                    .values(
                        status="failed",
                        error_code=code,
                        completed_at=func.clock_timestamp(),
                        updated_at=func.clock_timestamp(),
                    )
                    .returning(run)
                )
                .mappings()
                .one()
            )
            return receipt(
                stopped,
                result_for_run(c, stopped),
                ai_issue_generation_bindings.read_for_run(c, stopped),
            )
    return service._execute(claimed, claimed["run_context"]["issue_event_source"])
