"""Creation-time user authority for budgeted application runs, never model input."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, text

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.observations import digest
from app.auth import roles
from app.auth.roles import Action, Role, is_allowed
from app.contracts.runtime_records import AuthorizationEnvelope
from app.db.schema import tables

PURPOSE_ACTIONS = {
    "product_matrix": Action.PRODUCT_WORK_CONTRIBUTE,
    "portfolio_explanation": Action.PROJECT_EDIT,
    "executive_brief": Action.PROJECT_EDIT,
    "cost_reduction": Action.PRODUCT_ENGINEERING_EDIT,
    "supplier_recovery": Action.PRODUCT_ENGINEERING_EDIT,
    "meeting_planning": Action.MEETING_MANAGE,
    "intake_organization": Action.WORK_ITEM_EDIT,
    "process_template_configuration": Action.USER_MANAGE,
    "change_discussion": Action.CHANGE_EDIT,
    "change_work_package": Action.CHANGE_EDIT,
    "quality_work_package": Action.CAPA_EXECUTE,
    "meeting_minutes": Action.MEETING_TRANSCRIPT_UPLOAD,
    "meeting_actions": Action.MEETING_TRANSCRIPT_UPLOAD,
    "meeting_decisions": Action.MEETING_TRANSCRIPT_UPLOAD,
    "meeting_business": Action.MEETING_TRANSCRIPT_UPLOAD,
    "meeting_reading": Action.MEETING_TRANSCRIPT_UPLOAD,
    "chat_answer": Action.AI_CHAT_USE,
    "risk_suggestion": Action.RISK_SUGGESTION_CREATE,
    "test_plan_suggestion": Action.WORK_ITEM_EDIT,
    "report_mapping": Action.PRODUCT_ENGINEERING_EDIT,
}


def policy_version() -> str:
    return (
        "sha256:"
        + sha256(Path(__file__).read_bytes() + Path(roles.__file__).read_bytes()).hexdigest()
    )


def issue_application_authorization(
    connection: Connection,
    *,
    tenant_id: UUID,
    run_id: UUID,
    actor_user_id: UUID,
    purpose: str,
    auth_version: int | None = None,
) -> None:
    action = PURPOSE_ACTIONS[purpose]
    run = (
        connection.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == tenant_id, tables.agent_runs.c.id == run_id
            )
        )
        .mappings()
        .one()
    )
    user = (
        connection.execute(
            select(tables.users).where(
                tables.users.c.tenant_id == tenant_id, tables.users.c.id == actor_user_id
            )
        )
        .mappings()
        .one_or_none()
    )
    active = connection.execute(
        select(tables.tenants.c.status).where(tables.tenants.c.id == tenant_id)
    ).scalar_one()
    if (
        user is None
        or not user["is_active"]
        or active != "active"
        or not is_allowed(user["role"], action)
        or (auth_version is not None and user["auth_version"] != auth_version)
    ):
        raise BudgetLedgerError("APPLICATION_AUTHORIZATION_DENIED")
    now = connection.execute(select(func.clock_timestamp())).scalar_one()
    link = connection.execute(
        select(tables.budget_lineages.c.id, tables.budget_lineages.c.absolute_deadline)
        .join(
            tables.budget_run_links,
            tables.budget_run_links.c.lineage_id == tables.budget_lineages.c.id,
        )
        .where(
            tables.budget_run_links.c.tenant_id == tenant_id,
            tables.budget_run_links.c.run_id == run_id,
        )
    ).one()
    deadline = link.absolute_deadline
    membership = None
    delegation = None
    if purpose != "product_matrix" and user["role"] not in {Role.OWNER, Role.ADMIN}:
        membership = (
            connection.execute(
                select(tables.project_members).where(
                    tables.project_members.c.tenant_id == tenant_id,
                    tables.project_members.c.project_id == run["project_id"],
                    tables.project_members.c.user_id == actor_user_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if membership is None:
            candidates = connection.execute(
                select(tables.user_delegations)
                .where(
                    tables.user_delegations.c.tenant_id == tenant_id,
                    tables.user_delegations.c.delegate_user_id == actor_user_id,
                    tables.user_delegations.c.revoked_at.is_(None),
                    tables.user_delegations.c.starts_at <= now,
                    tables.user_delegations.c.ends_at > now,
                )
                .order_by(tables.user_delegations.c.id)
            ).mappings()
            for candidate in candidates:
                membership = (
                    connection.execute(
                        select(tables.project_members).where(
                            tables.project_members.c.tenant_id == tenant_id,
                            tables.project_members.c.project_id == run["project_id"],
                            tables.project_members.c.user_id == candidate["principal_user_id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if membership is not None:
                    delegation = candidate
                    deadline = min(deadline, candidate["ends_at"])
                    break
        if membership is None:
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_DENIED")
    pins = dict(
        role=user["role"],
        auth_version=user["auth_version"],
        action=action.value,
        membership_id=str(membership["id"]) if membership else None,
        membership_user_id=str(membership["user_id"]) if membership else None,
        delegation_id=str(delegation["id"]) if delegation else None,
    )
    policy = policy_version()
    aid = uuid4()
    scope = dict(kind="project", ref_id=run["project_id"])
    sources = [
        dict(
            tenant_id=tenant_id,
            project_id=run["project_id"],
            kind="project",
            ref_id=run["project_id"],
            as_of=now,
            digest=digest(pins),
        )
    ]
    if purpose == "product_matrix":
        from app.ai.product_matrix_preparation import readable
        from app.ai.product_matrix_runs import authorize
        from app.ai.project_discussion_sources import actor

        if (
            run["scope_kind"] != "market_space"
            or run["project_id"] is not None
            or run["market_space_id"] is None
            or run["requested_by_user_id"] != actor_user_id
            or run["agent_key"] != "product_management_intelligence"
            or run["context_version"] != "product-matrix-request-v1"
        ):
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_SCOPE_INVALID")
        original_context = actor(connection, tenant_id, actor_user_id)
        snapshot = run["run_context"]["matrix_source"]
        readable(connection, original_context, snapshot)
        original = authorize(
            connection,
            original_context,
            run["market_space_id"],
            UUID(snapshot["selection"]["record_id"]),
            write=True,
        )
        if snapshot["record_result_digest"] != original["result_digest"] or snapshot[
            "market_space_id"
        ] != str(run["market_space_id"]):
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_SCOPE_INVALID")
        scope = dict(kind="market_space", ref_id=run["market_space_id"])
        sources = [
            dict(
                tenant_id=tenant_id,
                project_id=None,
                kind="product_matrix_record",
                ref_id=original["id"],
                as_of=original["created_at"],
                digest=original["result_digest"],
            )
        ]
    elif purpose == "process_template_configuration":
        from app.ai.process_template_context import bound_source

        if run["scope_kind"] != "tenant" or run["project_id"] is not None:
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_SCOPE_INVALID")
        original = bound_source(connection, tenant_id, run["run_context"])
        scope = dict(kind="tenant", ref_id=tenant_id)
        sources = [
            dict(
                tenant_id=tenant_id,
                project_id=None,
                kind="process_template_brief",
                ref_id=original["id"],
                as_of=original["created_at"],
                digest=original["source_digest"],
            )
        ]
    elif run["project_id"] is None or run["scope_kind"] != "project":
        raise BudgetLedgerError("APPLICATION_AUTHORIZATION_SCOPE_INVALID")
    body = AuthorizationEnvelope.model_validate(
        dict(
            schema_version=1,
            id=aid,
            tenant_id=tenant_id,
            scope=scope,
            version=1,
            owner_user_id=actor_user_id,
            sources=sources,
            run_id=run_id,
            lineage_id=link.id,
            principal_kind="user",
            principal_id=actor_user_id,
            trigger_actor_user_id=actor_user_id,
            delegation_id=delegation["id"] if delegation else None,
            policy_version=policy,
            purpose=purpose,
            issued_at=now,
            expires_at=deadline,
            capability_version=f"{purpose}.v1",
            toolset_version=(
                "discussion-research-tools.v1"
                if purpose == "change_discussion"
                and run["run_context"].get("discussion_toolset_version")
                == "discussion-research-tools.v1"
                else "application-engineering-tools.v1"
                if purpose == "change_work_package"
                else "application-quality-tools.v1"
                if purpose == "quality_work_package"
                else "application-readers.v1"
            ),
        )
    )
    connection.execute(
        tables.application_authorizations.insert().values(
            id=aid,
            tenant_id=tenant_id,
            run_id=run_id,
            lineage_id=link.id,
            principal_id=actor_user_id,
            project_id=run["project_id"],
            body=body.model_dump(mode="json"),
            pins=pins,
            issued_at=now,
            expires_at=deadline,
        )
    )
    if not connection.execute(
        text("SELECT cehub_ai.application_authorization_is_current(:run)"), {"run": run_id}
    ).scalar_one():
        raise BudgetLedgerError("APPLICATION_AUTHORIZATION_DENIED")


def verify_application_authorization(
    engine: Engine,
    *,
    tenant_id: UUID,
    run_id: UUID | None,
    project_id: UUID | None = None,
    agent_key: str | None = None,
) -> None:
    if run_id is None:
        return
    with engine.connect() as connection:
        row = (
            connection.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.id == run_id, tables.agent_runs.c.tenant_id == tenant_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_SCOPE_INVALID")
        authorization = (
            connection.execute(
                select(tables.application_authorizations).where(
                    tables.application_authorizations.c.tenant_id == tenant_id,
                    tables.application_authorizations.c.run_id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if authorization is not None and (
            authorization["body"]["policy_version"] != policy_version()
            or project_id is not None
            and project_id != row["project_id"]
            or agent_key is not None
            and agent_key != row["agent_key"]
        ):
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_BINDING_CHANGED")
        if not connection.execute(
            text("SELECT cehub_ai.application_authorization_is_current(:run)"), {"run": run_id}
        ).scalar_one():
            raise BudgetLedgerError("APPLICATION_AUTHORIZATION_CHANGED")
