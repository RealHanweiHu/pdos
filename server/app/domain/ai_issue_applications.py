"""Confirmed event-Issue application with immutable AI/request-source lineage.

Automatic qualification is deliberately separate. This trial route may be exposed
only once the operation's trial adapter is ready, in addition to current grants.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, RowMapping, String, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.ai.issue_event_proposal import (
    OPERATION,
    IssueEventProposalError,
    source_snapshot,
    validate_proposal,
)
from app.ai.rollout_guard import CapabilityUnavailableError
from app.ai.write_policy import WRITE_OPERATIONS
from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.ai_issue_event_sources import read_event_source
from app.domain.ai_issue_write_access import authorize, write_settings
from app.domain.ai_write_policy import WritePolicyError
from app.domain.issues import IssueDraft, IssueService, _issue_snapshot
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class IssueApplicationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: UUID
    result_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _result(c: Connection, tenant: UUID, project: UUID, run: UUID) -> RowMapping:
    r, a = tables.ai_issue_event_results, tables.agent_runs
    row = (
        c.execute(
            select(r, a.c.requested_by_user_id)
            .join(a, (a.c.tenant_id == r.c.tenant_id) & (a.c.id == r.c.run_id))
            .where(
                r.c.tenant_id == tenant,
                r.c.project_id == project,
                r.c.run_id == run,
                a.c.project_id == project,
                a.c.status == "succeeded",
                a.c.context_version == "event-issue-request-v1",
                a.c.run_context["issue_event_result_id"].as_string() == r.c.id.cast(String),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("原运行没有可办理的实际建议")
    return row


def _existing(c: Connection, tenant: UUID, project: UUID, source_key: str) -> RowMapping | None:
    t = tables.ai_issue_applications
    return (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant, t.c.project_id == project, t.c.source_key == source_key
            )
        )
        .mappings()
        .one_or_none()
    )


def _application(c: Connection, row: RowMapping, *, may_write: bool) -> dict[str, Any]:
    principal = c.execute(
        select(tables.ai_principals.c.display_name).where(
            tables.ai_principals.c.tenant_id == row["tenant_id"],
            tables.ai_principals.c.id == row["principal_id"],
        )
    ).scalar_one()
    name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == row["tenant_id"],
            tables.users.c.id == row["confirmed_by_user_id"],
        )
    ).scalar_one_or_none()
    requested_name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == row["tenant_id"],
            tables.users.c.id == row["requested_by_user_id"],
        )
    ).scalar_one()
    from app.domain.ai_issue_withdrawals import application_withdrawal_state

    automatic_stop = None
    execution = row["receipt"].get("write_receipt")
    if row["capture_mode"] == "direct" and isinstance(execution, dict):
        t = tables.ai_write_runtime_stops
        stopped = (
            c.execute(
                select(t.c.id, t.c.receipt).where(
                    t.c.tenant_id == row["tenant_id"],
                    t.c.project_id == row["project_id"],
                    t.c.policy_id == row["policy_id"],
                    t.c.operation_key == OPERATION,
                    t.c.binding_digest == execution["binding_digest"],
                )
            )
            .mappings()
            .one_or_none()
        )
        automatic_stop = dict(stopped) if stopped else None

    return _plain(
        {
            **dict(row),
            "writer_name": principal,
            "confirmed_by_name": name,
            "requested_by_name": requested_name,
            "automatic_stop": automatic_stop,
            **application_withdrawal_state(c, row, may_write=may_write),
        }
    )


def _read(c: Connection, context: AuthContext, project: UUID, run: UUID) -> dict[str, Any]:
    authorize(c, context, project, write=False)
    result = _result(c, context.tenant.id, project, run)
    snapshot = result["source_snapshot"]
    previous = _existing(c, context.tenant.id, project, snapshot["source_key"])
    source = read_event_source(c, context.tenant.id, project, result["event_row_id"])
    current = source["source_digest"] == (
        previous["receipt"]["post_source_digest"] if previous else result["source_digest"]
    )
    may_write = True
    try:
        authorize(c, context, project, write=True)
    except PermissionError:
        may_write = False
    can_apply = False
    notice = "原建议尚未办理。"
    if previous:
        notice = "已按原回执办理；重复确认不会再次创建或改写问题。"
    elif not WRITE_OPERATIONS[OPERATION].trial_ready:
        notice = "独立评测与试运行准备尚未完成，当前仅可核对原建议与办理回执。"
    else:
        try:
            authorize(c, context, project, write=True)
            write_settings(c, context.tenant.id, project)
            if not current or source_snapshot(source) != snapshot:
                raise IssueApplicationError("SOURCE_CHANGED", "来源已变化，请重新核对并生成建议。")
            proposal = validate_proposal(source, result["proposal"])
            if proposal.disposition == "insufficient_evidence":
                notice = "原资料仍需补证，不能据此创建问题。"
            else:
                can_apply, notice = True, "核对原建议后一次确认，以AI身份办理并保留具名确认回执。"
        except (WritePolicyError, IssueApplicationError, IssueEventProposalError) as error:
            notice = error.message
        except CapabilityUnavailableError:
            notice = "本能力仍处独立评测阶段，实际办理尚未开放。"
        except PermissionError:
            notice = "当前没有办理权限，原建议和回执仍按读取范围显示。"
    from app.domain.ai_issue_proposal_reviews import state as review_state

    review = review_state(c, result, applied=previous is not None, may_write=may_write)
    if previous is None and review["state"] == "declined":
        can_apply, notice = False, "该建议已标记不采纳；可先记录重新考虑，再核对实际办理条件。"
    return _plain(
        {
            "result_id": result["id"],
            "source_digest": result["source_digest"],
            "can_apply": can_apply,
            "notice": notice,
            "sources_current": current,
            "application": _application(c, previous, may_write=may_write) if previous else None,
            "review": review,
        }
    )


class IssueApplicationService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID, run_id: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return _read(c, context, project_id, run_id)

    def apply(
        self, context: AuthContext, project_id: UUID, run_id: UUID, change: ApplyRequest
    ) -> dict[str, Any]:
        tenant, actor = context.tenant.id, context.user.id
        request_digest = digest(
            {
                "project_id": str(project_id),
                "run_id": str(run_id),
                **change.model_dump(mode="json", exclude={"request_id"}),
            }
        )
        with self.engine.begin() as c:
            c.execute(
                select(tables.tenants.c.id).where(tables.tenants.c.id == tenant).with_for_update()
            )
            if not lock_project_write_scope(c, tenant_id=tenant, project_id=project_id):
                raise LookupError("原项目已不可办理")
            authorize(c, context, project_id, write=True)
            t = tables.ai_issue_applications
            replay = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.confirmed_by_user_id == actor,
                        t.c.request_id == change.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if replay and replay["request_digest"] != request_digest:
                raise IssueApplicationError("REQUEST_ID_REUSED", "本请求已用于其他办理内容")
            result = _result(c, tenant, project_id, run_id)
            if (
                result["id"] != change.result_id
                or result["source_digest"] != change.expected_digest
            ):
                raise IssueApplicationError("RESULT_CHANGED", "请按原建议编号与依据重新核对")
            snapshot = result["source_snapshot"]
            if replay or _existing(c, tenant, project_id, snapshot["source_key"]):
                return _read(c, context, project_id, run_id)
            from app.domain.ai_issue_proposal_reviews import latest as latest_review

            review = latest_review(c, result)
            if review and review["action"] == "decline":
                raise IssueApplicationError("PROPOSAL_DECLINED", "请先记录重新考虑，再办理原建议")
            if not WRITE_OPERATIONS[OPERATION].trial_ready:
                raise IssueApplicationError(
                    "ADAPTER_NOT_READY", "独立评测与试运行准备尚未完成，当前不能办理"
                )
            settings, grant = write_settings(c, tenant, project_id)
            self._write_application(
                c,
                tenant=tenant,
                project_id=project_id,
                run_id=run_id,
                result=result,
                settings=settings,
                grant=grant,
                confirmed_by=actor,
                request_id=change.request_id,
                request_digest=request_digest,
            )
            return _read(c, context, project_id, run_id)

    def apply_generated(self, c: Connection, run: RowMapping) -> dict[str, Any]:
        """Process a newly saved result under the caller's tenant/project locks.

        No HTTP route accepts execution evidence. Failure to apply preserves the
        completed model result, and the nested transaction prevents partial Issues.
        A replay returns the original run receipt and never retries a direct write.
        """
        from app.ai.issue_event_runs import _access
        from app.domain.ai_issue_direct_route import resolve_direct_route
        from app.domain.ai_issue_proposal_reviews import latest as latest_review

        tenant, project, identity = run["tenant_id"], run["project_id"], run["id"]
        now = c.execute(select(func.clock_timestamp())).scalar_one()
        fallback = {
            "version": "event-issue-write-execution-v1",
            "route": "confirm",
            "reason": "automatic_unavailable",
            "reason_label": "自动办理条件尚未满足，保留原建议供逐次确认。",
            "checked_at": now.isoformat(),
            "run_id": str(identity),
            "sampled": False,
        }
        try:
            with c.begin_nested():
                result = _result(c, tenant, project, identity)
                previous = _existing(c, tenant, project, result["source_snapshot"]["source_key"])
                if previous is not None:
                    return {
                        **fallback,
                        "reason": "already_applied",
                        "reason_label": "同一来源已有办理回执，沿原问题继续，不重复创建。",
                        "application_id": str(previous["id"]),
                    }
                if result["proposal"]["disposition"] == "insufficient_evidence":
                    return {
                        **fallback,
                        "route": "exception",
                        "reason": "evidence_required",
                        "reason_label": "原建议仍需补充证据，暂不创建问题。",
                    }
                _access(c, tenant, run["requested_by_user_id"], project, write=True)
                active = c.execute(
                    select(tables.users.c.is_active).where(
                        tables.users.c.tenant_id == tenant,
                        tables.users.c.id == run["requested_by_user_id"],
                    )
                ).scalar_one_or_none()
                if active is not True:
                    raise PermissionError("原请求人当前不可办理")
                review = latest_review(c, result)
                if review and review["action"] == "decline":
                    return {
                        **fallback,
                        "reason": "proposal_declined",
                        "reason_label": "原建议已具名不采纳，自动办理停止。",
                    }
                execution = resolve_direct_route(
                    c, tenant_id=tenant, project_id=project, run_id=identity, as_of=now
                )
                if execution["route"] != "direct":
                    return execution
                settings, grant = write_settings(c, tenant, project)
                if (
                    not WRITE_OPERATIONS[OPERATION].adapter_ready
                    or settings["operation_settings"][OPERATION]["mode"] != "automatic"
                    or execution.get("policy_id") != str(settings["id"])
                    or execution.get("scope_revision_id") != str(grant["id"])
                    or execution.get("principal_id") != str(grant["principal_id"])
                    or execution.get("run_id") != str(identity)
                ):
                    raise IssueApplicationError("DIRECT_CONTROLS_CHANGED", "自动办理条件已变化")
                c.execute(
                    tables.agent_runs.update()
                    .where(
                        tables.agent_runs.c.tenant_id == tenant,
                        tables.agent_runs.c.id == identity,
                    )
                    .values(run_context={**run["run_context"], "issue_write_execution": execution})
                )
                application_id = self._write_application(
                    c,
                    tenant=tenant,
                    project_id=project,
                    run_id=identity,
                    result=result,
                    settings=settings,
                    grant=grant,
                    confirmed_by=None,
                    request_id=run["request_id"],
                    execution=execution,
                    request_digest=digest(
                        {
                            "run_id": str(identity),
                            "result_id": str(result["id"]),
                            "route": "automatic",
                        }
                    ),
                )
                return {**execution, "application_id": str(application_id)}
        except (WritePolicyError, IssueApplicationError, IssueEventProposalError) as error:
            return {
                **fallback,
                "route": "exception",
                "reason": error.code,
                "reason_label": error.message,
            }
        except (PermissionError, LookupError, CapabilityUnavailableError):
            return {
                **fallback,
                "route": "exception",
                "reason": "current_access_unavailable",
                "reason_label": "当前来源、授权或运行条件已变化，原建议保留供有权人员核对。",
            }
        except (SQLAlchemyError, ValueError):
            logging.getLogger(__name__).exception("Automatic Issue application rolled back")
            return {
                **fallback,
                "route": "exception",
                "reason": "automatic_apply_failed",
                "reason_label": "自动办理未完成，已回滚本次业务写入；原建议保留，可逐次确认。",
            }

    def _write_application(
        self,
        c: Connection,
        *,
        tenant: UUID,
        project_id: UUID,
        run_id: UUID,
        result: RowMapping,
        settings: RowMapping,
        grant: RowMapping,
        confirmed_by: UUID | None,
        request_id: UUID,
        request_digest: str,
        execution: dict[str, Any] | None = None,
    ) -> UUID:
        """Shared mutation; caller holds locks and has checked its distinct authority."""
        t = tables.ai_issue_applications
        snapshot = result["source_snapshot"]
        # All source writers use the same project lock. Explicit case lock also
        # binds the compare-and-set association to this exact failed test.
        case = None
        if snapshot["source_kind"] == "test_failure":
            case = (
                c.execute(
                    select(tables.test_cases)
                    .where(
                        tables.test_cases.c.tenant_id == tenant,
                        tables.test_cases.c.project_id == project_id,
                        tables.test_cases.c.id == UUID(snapshot["entity_id"]),
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if case is None:
                raise LookupError("原测试已不存在")
        source = read_event_source(c, tenant, project_id, result["event_row_id"])
        if source_snapshot(source) != snapshot:
            raise IssueApplicationError("SOURCE_CHANGED", "原依据已变化，请重新核对并生成建议")
        proposal = validate_proposal(source, result["proposal"])
        if proposal.disposition == "insufficient_evidence":
            raise IssueApplicationError("EVIDENCE_REQUIRED", "请先补齐原建议要求的证据")
        now, application_id = c.execute(select(func.clock_timestamp())).scalar_one(), uuid4()
        issue_event_id = None
        before_case = _plain(dict(case)) if case else None
        if proposal.disposition == "create_issue":
            if (
                case is None
                or case["related_issue_id"] is not None
                or source["source"]["origin_kind"] != "legacy_test_case"
            ):
                raise IssueApplicationError("SOURCE_REQUIRES_REUSE", "当前来源只可沿原问题办理")
            assert proposal.title is not None and proposal.severity is not None
            issue = IssueService(self.engine).create_from_ai_event(
                tenant_id=tenant,
                project_id=project_id,
                principal_id=grant["principal_id"],
                policy_id=settings["id"],
                scope_revision_id=grant["id"],
                requested_by_user_id=result["requested_by_user_id"],
                confirmed_by_user_id=confirmed_by,
                result_id=result["id"],
                run_id=run_id,
                model_invocation_id=result["model_invocation_id"],
                source_event_row_id=result["event_row_id"],
                application_id=application_id,
                draft=IssueDraft(
                    stage_id=None,
                    owner_user_id=None,
                    verifier_user_id=None,
                    sample_id=None,
                    title=proposal.title,
                    description=proposal.description,
                    issue_type="test_failure",
                    severity=proposal.severity,
                    root_cause=None,
                    resolution=None,
                    closure_criteria=None,
                    target_date=None,
                ),
                connection=c,
                write_execution=execution,
                now=now,
            )
            c.execute(
                tables.test_cases.update()
                .where(
                    tables.test_cases.c.tenant_id == tenant,
                    tables.test_cases.c.project_id == project_id,
                    tables.test_cases.c.id == case["id"],
                    tables.test_cases.c.related_issue_id.is_(None),
                )
                .values(related_issue_id=issue.id, updated_at=now)
            )
            issue_event_id = c.execute(
                select(tables.events.c.id).where(
                    tables.events.c.tenant_id == tenant,
                    tables.events.c.project_id == project_id,
                    tables.events.c.event_id == f"issue:{issue.id}:created",
                )
            ).scalar_one()
            disposition = "created"
        else:
            assert proposal.existing_issue_id is not None
            issue = IssueService._get_record(
                c, tenant_id=tenant, project_id=project_id, issue_id=proposal.existing_issue_id
            )
            disposition = "reused"
        post_source = read_event_source(c, tenant, project_id, result["event_row_id"])
        receipt = {
            "origin": "ai",
            "version": "issue-application-v1",
            "source_snapshot": snapshot,
            "post_source_digest": post_source["source_digest"],
            "proposal": result["proposal"],
            "issue_snapshot": {
                "id": str(issue.id),
                "updated_at": issue.updated_at.isoformat(),
                **_issue_snapshot(issue),
            },
            "source_case_before": before_case,
            "source_case_after": post_source["source"].get("current_case"),
            "route": "automatic" if execution else "confirmed_trial",
            **({"write_receipt": execution} if execution else {}),
        }
        written = EventAuditWriter(
            c, tenant_id=tenant, project_id=project_id, actor_user_id=None
        ).record(
            EventDraft(
                event_id=f"ai-issue-application:{application_id}",
                event_type="AI_ISSUE_APPLICATION_RECORDED",
                source="ai_issue_application_service",
                entity_id=application_id,
                occurred_at=now,
                payload={
                    "application_id": str(application_id),
                    "issue_id": str(issue.id),
                    "disposition": disposition,
                },
            ),
            AuditDraft(
                action="ai_issue.automatic_apply" if execution else "ai_issue.confirmed_apply",
                after_snapshot=receipt,
                context={
                    "origin": "ai",
                    "writer_principal_id": str(grant["principal_id"]),
                    "requested_by_user_id": str(result["requested_by_user_id"]),
                    "confirmed_by_user_id": str(confirmed_by) if confirmed_by else None,
                    "run_id": str(run_id),
                    "model_invocation_id": str(result["model_invocation_id"]),
                    "result_id": str(result["id"]),
                    "policy_id": str(settings["id"]),
                    "scope_revision_id": str(grant["id"]),
                },
            ),
        )
        c.execute(
            t.insert().values(
                id=application_id,
                tenant_id=tenant,
                project_id=project_id,
                result_id=result["id"],
                run_id=run_id,
                model_invocation_id=result["model_invocation_id"],
                principal_id=grant["principal_id"],
                policy_id=settings["id"],
                scope_revision_id=grant["id"],
                requested_by_user_id=result["requested_by_user_id"],
                confirmed_by_user_id=confirmed_by,
                request_id=request_id,
                request_digest=request_digest,
                source_event_row_id=result["event_row_id"],
                source_key=snapshot["source_key"],
                issue_id=issue.id,
                disposition=disposition,
                capture_mode="direct" if execution else "trial",
                output_event_row_id=written.event_row_id,
                issue_event_row_id=issue_event_id,
                receipt=receipt,
                created_at=now,
            )
        )
        return application_id
