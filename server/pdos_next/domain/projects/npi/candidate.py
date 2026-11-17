"""Reviewable NPI candidates from the registered project Run."""

from sqlalchemy import func, select

from pdos_next.agent.kernel.models import AgentEvent
from pdos_next.core.service import digest
from pdos_next.domain.projects.service import _project
from pdos_next.errors import DomainError
from pdos_next.schemas.planning import ScheduleInput

from .planning import validate_plan
from .rules import PlanBasis

KINDS = ("npi_plan_candidate", "npi_plan_check_failed")


def events(session, run_id):
    return list(
        session.scalars(
            select(AgentEvent)
            .where(
                AgentEvent.run_id == run_id,
                AgentEvent.body["type"].astext.in_(KINDS),
            )
            .order_by(AgentEvent.sequence)
        )
    )


def prepare(bootstrap, scope, spec, arguments, intent_key):
    ctx = bootstrap.commands.context(scope)
    failure = None
    skill = bootstrap.catalog.configuration("work_management")
    with bootstrap.commands.transaction(scope) as session:
        bootstrap.store.authority(session, scope)
        command = bootstrap.commands.command(session, scope, spec.name, arguments, intent_key)
        payload = command.payload
        if not scope.project_id or payload.get("project_id") != str(scope.project_id):
            raise DomainError("FORBIDDEN_SCOPE", "计划须绑定运行的实际项目。", 403)
        draft = payload.get("draft")
        if draft is None:
            return None
        project, link, _ = _project(session, ctx, scope.product_id, scope.project_id)
        if (
            project.owner_id != ctx.requester_id
            or draft.get("expected_project_revision") != project.revision
            or draft.get("base_plan_id")
            != (str(project.current_plan_id) if project.current_plan_id else None)
        ):
            raise DomainError("VERSION_CONFLICT", "请使用项目负责人的当前计划与版本。")
        try:
            checked = validate_plan(
                session,
                ctx,
                project,
                link,
                PlanBasis.model_validate(draft["npi"]),
                ScheduleInput.model_validate(draft["schedule"]),
                command.source_read_set,
            )
        except DomainError as error:
            if not error.detail.get("issues"):
                raise
            failure = error.payload()

    serialized = command.model_dump(mode="json")
    fingerprint = digest(serialized)
    with bootstrap.store.transaction(scope, lock=True) as (session, run):
        history = events(session, run.id)
        prior = next((event.body for event in history if event.body["intent"] == intent_key), None)
        failed = sum(event.body["type"] == "npi_plan_check_failed" for event in history)
        if prior:
            if prior["fingerprint"] != fingerprint:
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "原计划调用的内容已变化。")
            value = prior
        elif failed >= 2:
            raise DomainError("VALIDATION_FAILED", "两次框架检查未通过，已交项目负责人核对。", 422)
        else:
            if failure:
                value = {
                    "type": "npi_plan_check_failed",
                    "exception": failed == 1,
                    "error": failure,
                }
            else:
                value = {
                    "type": "npi_plan_candidate",
                    "command": serialized,
                    "framework": checked["framework"],
                    "role_exceptions": checked["role_exceptions"],
                }
            sequence = session.scalar(
                select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                    AgentEvent.run_id == run.id
                )
            )
            session.add(
                AgentEvent(
                    tenant_id=scope.tenant_id,
                    run_id=run.id,
                    sequence=sequence + 1,
                    body={
                        **value,
                        "intent": intent_key,
                        "fingerprint": fingerprint,
                        "skill_key": skill.key,
                        "skill_version": skill.version,
                    },
                )
            )
    if value["type"] == "npi_plan_check_failed":
        raise DomainError(
            "VALIDATION_FAILED",
            "两次框架检查未通过，已交项目负责人核对。"
            if value["exception"]
            else "计划未通过框架检查，请根据问题修正后提交一次。",
            422,
            detail=value["error"]["detail"],
        )
    return {
        "command": value["command"],
        "role_exceptions": value["role_exceptions"],
        "requires_human": True,
        "state": "candidate",
        "write_tier": "T1",
    }
