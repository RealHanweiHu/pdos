"""Source-bound meeting reading, preceding official minutes and separate Findings."""

from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, RowMapping, func, select, true

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.application_recovery import try_resume
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.capability_contract import resolve_capability
from app.ai.executor import PromptFile
from app.ai.gateway import GatewayInvocation
from app.ai.model_catalog import AgentTier
from app.ai.rollout_guard import CapabilityUnavailableError, require_live_key
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeVersionError
from app.domain.meeting_transcripts import transcript_snapshot
from app.domain.meetings import MeetingService, MeetingStateError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope

KEY = "knowledge_lite.meeting_reading"
MINUTES_KEY = "knowledge_lite.meeting_minutes"
ACTIONS_KEY = "knowledge_lite.meeting_actions"
DECISIONS_KEY = "knowledge_lite.meeting_decisions"
BUSINESS_KEY = "knowledge_lite.meeting_business"
PURPOSE = "meeting_reading"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "meeting_reading_v1.json").read_text()
)


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    segment_id: UUID
    exact_quote: str = Field(min_length=1, max_length=2000)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str = Field(min_length=1, max_length=2000)
    citations: tuple[Quote, ...] = Field(min_length=1, max_length=8)


class MeetingReading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["reading", "insufficient_evidence"]
    claims: tuple[Claim, ...] = Field(max_length=30)
    open_questions: tuple[str, ...] = Field(max_length=15)

    @model_validator(mode="after")
    def complete_shape(self) -> Self:
        if (self.disposition == "reading") != bool(self.claims):
            raise ValueError("reading requires cited claims; insufficient evidence has no claims")
        if any(not question.strip() or len(question) > 2000 for question in self.open_questions):
            raise ValueError("questions must be nonblank and bounded")
        if any(not claim.text.strip() for claim in self.claims):
            raise ValueError("claims must be nonblank")
        return self


def source_state(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    meeting_id: UUID,
    transcript_id: UUID,
    *,
    include_minutes: bool = False,
    include_actions: bool = False,
    include_decisions: bool = False,
    include_business: bool = False,
) -> dict[str, Any]:
    meeting = MeetingService._get(
        connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
    )
    snapshot = transcript_snapshot(connection, tenant_id, meeting_id, transcript_id)
    if meeting.deleted_at or meeting.archived_at or snapshot["superseded"]:
        raise MeetingStateError("该会议或转写稿已只读，不能继续生成")
    if not snapshot["source_complete"]:
        raise MeetingStateError("转写原文或引用片段不完整，请先补齐")
    # Bind current speaker names without exposing the complete project directory.
    speaker_ids = {
        UUID(segment["speaker_user_id"])
        for segment in snapshot["segments"]
        if segment["speaker_user_id"]
    }
    names = {
        str(row.id): row.display_name
        for row in connection.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant_id, tables.users.c.id.in_(speaker_ids)
            )
        )
    }
    state: dict[str, Any] = {
        "meeting_id": str(meeting_id),
        "transcript_id": str(transcript_id),
        "meeting_title": meeting.title,
        "meeting_status": meeting.status,
        "transcript_digest": snapshot["digest"],
        "segments": snapshot["segments"],
        "speakers": names,
    }
    if include_minutes:
        if meeting.status != "completed":
            raise MeetingStateError("请在会议结束后生成正式纪要待审稿")
        latest = (
            connection.execute(
                select(tables.meeting_minutes_versions)
                .where(
                    tables.meeting_minutes_versions.c.tenant_id == tenant_id,
                    tables.meeting_minutes_versions.c.meeting_id == meeting_id,
                )
                .order_by(tables.meeting_minutes_versions.c.version_no.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        state["minutes_base"] = {
            "version": latest["version_no"] if latest else 0,
            "id": str(latest["id"]) if latest else None,
            "body": latest["body"] if latest else "",
            "unresolved_points": latest["unresolved_points"] if latest else "",
            "digest": latest["document_digest"] if latest else None,
        }
    if include_actions:
        from app.domain.meeting_action_proposals import action_options

        if meeting.status not in {"in_progress", "completed"}:
            raise MeetingStateError("请在会议开始后整理行动建议")
        state["action_options"] = action_options(connection, tenant_id, project_id, meeting_id)
    if include_decisions:
        from app.domain.meeting_action_proposals import action_options

        if meeting.status not in {"in_progress", "completed"}:
            raise MeetingStateError("请在会议开始后整理决策建议")
        state["decision_options"] = action_options(connection, tenant_id, project_id, meeting_id)[
            "members"
        ]
    if include_business:
        from app.domain.meeting_action_proposals import action_options

        if meeting.status not in {"in_progress", "completed"}:
            raise MeetingStateError("请在会议开始后整理业务建议")
        state["business_options"] = action_options(connection, tenant_id, project_id, meeting_id)[
            "members"
        ]
    return state


def model_context(snapshot: dict[str, Any], user_instruction: str = "") -> dict[str, Any]:
    return {
        "question": "阅读本次会议转写并给出带原文引用的归纳。会议主题："
        + snapshot["meeting_title"]
        + ("\n用户本次要求：" + user_instruction if user_instruction else ""),
        "references": [
            {
                "reference_id": segment["id"],
                "entity": "meeting_transcript_segment",
                "entity_id": segment["id"],
                "label": (
                    f"片段{segment['sequence']} · {segment['speaker_label'] or '标签不明'} · "
                    + snapshot["speakers"].get(segment["speaker_user_id"], "身份未绑定")
                ),
                "excerpt": segment["content"],
            }
            for segment in snapshot["segments"]
        ],
    }


class MeetingReadingService:
    def __init__(self, engine: Engine, *, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    @staticmethod
    def list_results(
        engine: Engine,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        actor_id: UUID,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        with engine.connect() as connection:
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_VIEW
            )
            MeetingService._get(
                connection, tenant_id=tenant_id, project_id=project_id, meeting_id=meeting_id
            )
            # Historical output remains visible with an explicit stale marker.
            transcript_snapshot(connection, tenant_id, meeting_id, transcript_id)
            try:
                current = source_state(connection, tenant_id, project_id, meeting_id, transcript_id)
                current_digest = digest(current)
            except MeetingStateError:
                current_digest = None
            try:
                minutes_current = source_state(
                    connection,
                    tenant_id,
                    project_id,
                    meeting_id,
                    transcript_id,
                    include_minutes=True,
                )
                minutes_digest = digest(minutes_current)
                minutes_version = minutes_current["minutes_base"]["version"]
            except MeetingStateError:
                minutes_digest, minutes_version = None, None
            try:
                actions_digest = digest(
                    source_state(
                        connection,
                        tenant_id,
                        project_id,
                        meeting_id,
                        transcript_id,
                        include_actions=True,
                    )
                )
            except MeetingStateError:
                actions_digest = None
            try:
                decisions_digest = digest(
                    source_state(
                        connection,
                        tenant_id,
                        project_id,
                        meeting_id,
                        transcript_id,
                        include_decisions=True,
                    )
                )
            except MeetingStateError:
                decisions_digest = None
            try:
                business_digest = digest(
                    source_state(
                        connection,
                        tenant_id,
                        project_id,
                        meeting_id,
                        transcript_id,
                        include_business=True,
                    )
                )
            except MeetingStateError:
                business_digest = None
            rows = connection.execute(
                select(tables.agent_runs)
                .where(
                    tables.agent_runs.c.tenant_id == tenant_id,
                    tables.agent_runs.c.project_id == project_id,
                    tables.agent_runs.c.agent_key == "knowledge_lite",
                    tables.agent_runs.c.id == run_id if run_id is not None else true(),
                    tables.agent_runs.c.context_version.in_(
                        (
                            "meeting-reading-request-v1",
                            "meeting-minutes-request-v1",
                            "meeting-actions-request-v1",
                            "meeting-decisions-request-v1",
                            "meeting-business-request-v1",
                        )
                    ),
                    tables.agent_runs.c.run_context["reading_meeting_id"].as_string()
                    == str(meeting_id),
                    tables.agent_runs.c.run_context["reading_transcript_id"].as_string()
                    == str(transcript_id),
                )
                .order_by(tables.agent_runs.c.created_at.desc())
                .limit(20)
            ).mappings()
            rollout = resolve_capability(KEY).rollout.value
            minutes_rollout = resolve_capability(MINUTES_KEY).rollout.value
            actions_rollout = resolve_capability(ACTIONS_KEY).rollout.value
            decisions_rollout = resolve_capability(DECISIONS_KEY).rollout.value
            business_rollout = resolve_capability(BUSINESS_KEY).rollout.value
            return _plain(
                {
                    "rollout": rollout,
                    "minutes_rollout": minutes_rollout,
                    "minutes_version": minutes_version,
                    "actions_rollout": actions_rollout,
                    "actions_available": actions_digest is not None,
                    "decisions_rollout": decisions_rollout,
                    "decisions_available": decisions_digest is not None,
                    "business_rollout": business_rollout,
                    "business_available": business_digest is not None,
                    "items": [
                        {
                            "run_id": row["id"],
                            "status": row["status"],
                            "error_code": row["error_code"],
                            "created_at": row["created_at"],
                            "current": row["run_context"].get("reading_source_digest")
                            == (
                                business_digest
                                if row["run_context"].get("reading_propose_business")
                                else (
                                    decisions_digest
                                    if row["run_context"].get("reading_propose_decisions")
                                    else (
                                        actions_digest
                                        if row["run_context"].get("reading_propose_actions")
                                        else (
                                            minutes_digest
                                            if row["run_context"].get("reading_propose_minutes")
                                            else current_digest
                                        )
                                    )
                                )
                            ),
                            "finding_id": row["run_context"].get("reading_finding_id")
                            if minutes_rollout == "live"
                            else None,
                            "proposal": bool(row["run_context"].get("reading_propose_minutes")),
                            "actions": bool(row["run_context"].get("reading_propose_actions")),
                            "decisions": bool(row["run_context"].get("reading_propose_decisions")),
                            "business": bool(row["run_context"].get("reading_propose_business")),
                            "finding_ids": row["run_context"].get("reading_finding_ids", [])
                            if (
                                business_rollout
                                if row["run_context"].get("reading_propose_business")
                                else decisions_rollout
                                if row["run_context"].get("reading_propose_decisions")
                                else actions_rollout
                            )
                            == "live"
                            else [],
                            "result": row["run_context"].get("reading_result")
                            if rollout == "live"
                            and not row["run_context"].get("reading_propose_minutes")
                            and not row["run_context"].get("reading_propose_actions")
                            and not row["run_context"].get("reading_propose_decisions")
                            and not row["run_context"].get("reading_propose_business")
                            else None,
                        }
                        for row in rows
                    ],
                }
            )

    def create(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        meeting_id: UUID,
        transcript_id: UUID,
        actor_id: UUID,
        auth_version: int,
        request_id: UUID,
        expected_digest: str,
        propose_minutes: bool = False,
        propose_actions: bool = False,
        propose_decisions: bool = False,
        propose_business: bool = False,
        expected_minutes_version: int | None = None,
        user_instruction: str = "",
    ) -> dict[str, Any]:
        if len(user_instruction) > 20000:
            raise MeetingStateError("本次会话说明过长，请缩小范围")
        require_live_key(KEY)
        if sum((propose_minutes, propose_actions, propose_decisions, propose_business)) > 1:
            raise MeetingStateError("请分别发起纪要、行动或决策候选")
        purpose = (
            "meeting_business"
            if propose_business
            else "meeting_decisions"
            if propose_decisions
            else "meeting_actions"
            if propose_actions
            else "meeting_minutes"
            if propose_minutes
            else PURPOSE
        )
        if propose_business:
            require_live_key(BUSINESS_KEY)
        if propose_decisions:
            require_live_key(DECISIONS_KEY)
        if propose_actions:
            require_live_key(ACTIONS_KEY)
        if propose_minutes:
            require_live_key(MINUTES_KEY)
            if expected_minutes_version is None:
                raise MeetingStateError("请核对当前正式纪要版本")
        elif expected_minutes_version is not None:
            raise MeetingStateError("普通阅读请求不能指定纪要应用版本")
        with self.engine.begin() as connection:
            # One persistent request per tenant; no model call while this lock is held.
            connection.execute(
                select(tables.tenants.c.id)
                .where(tables.tenants.c.id == tenant_id)
                .with_for_update()
            ).scalar_one()
            KnowledgeCorrectionService._authorize(
                connection, tenant_id, actor_id, project_id, Action.MEETING_TRANSCRIPT_UPLOAD
            )
            existing = (
                connection.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.project_id == project_id,
                        tables.agent_runs.c.agent_key == "knowledge_lite",
                        tables.agent_runs.c.request_id == str(request_id),
                    )
                )
                .mappings()
                .one_or_none()
            )
            request_body = {
                "reading_meeting_id": str(meeting_id),
                "reading_transcript_id": str(transcript_id),
                "reading_expected_digest": expected_digest,
                **({"reading_user_instruction": user_instruction} if user_instruction else {}),
                **({"reading_propose_actions": True} if propose_actions else {}),
                **({"reading_propose_decisions": True} if propose_decisions else {}),
                **({"reading_propose_business": True} if propose_business else {}),
                **(
                    {
                        "reading_propose_minutes": True,
                        "reading_expected_minutes_version": expected_minutes_version,
                    }
                    if propose_minutes
                    else {}
                ),
            }
            if existing is not None:
                context = existing["run_context"]
                if (
                    context.get("reading_user_instruction", "") != user_instruction
                    or bool(context.get("reading_propose_minutes")) != propose_minutes
                    or bool(context.get("reading_propose_actions")) != propose_actions
                    or bool(context.get("reading_propose_decisions")) != propose_decisions
                    or bool(context.get("reading_propose_business")) != propose_business
                    or existing["requested_by_user_id"] != actor_id
                    or any(context.get(key) != value for key, value in request_body.items())
                ):
                    raise KnowledgeVersionError("本请求已用于其他转写阅读")
                if not try_resume(
                    connection,
                    self.gateway,
                    existing,
                    actor=actor_id,
                    auth_version=auth_version,
                    purpose=purpose,
                ):
                    return self._receipt(existing)
                row = existing
                snapshot = context["reading_source"]
            else:
                snapshot = source_state(
                    connection,
                    tenant_id,
                    project_id,
                    meeting_id,
                    transcript_id,
                    include_minutes=propose_minutes,
                    include_actions=propose_actions,
                    include_decisions=propose_decisions,
                    include_business=propose_business,
                )
                if snapshot["transcript_digest"] != expected_digest:
                    raise KnowledgeVersionError("转写或说话人校正已变化，请刷新核对")
                if (
                    propose_minutes
                    and snapshot["minutes_base"]["version"] != expected_minutes_version
                ):
                    raise KnowledgeVersionError("正式纪要已有新版，请刷新后再生成候选")
                # New capability always uses the admitted budget/authorization path.
                if getattr(self.gateway, "creation_budget_profile", None) is None:
                    raise BudgetLedgerError("APPLICATION_QUEUE_BUDGET_REQUIRED")
                now = connection.execute(select(func.clock_timestamp())).scalar_one()
                row = (
                    connection.execute(
                        tables.agent_runs.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            project_id=project_id,
                            agent_key="knowledge_lite",
                            request_id=str(request_id),
                            requested_by_user_id=actor_id,
                            status="running",
                            event_count=0,
                            event_row_ids=[],
                            window_started_at=now,
                            window_ended_at=now,
                            context_version="meeting-business-request-v1"
                            if propose_business
                            else "meeting-decisions-request-v1"
                            if propose_decisions
                            else "meeting-actions-request-v1"
                            if propose_actions
                            else (
                                "meeting-minutes-request-v1"
                                if propose_minutes
                                else "meeting-reading-request-v1"
                            ),
                            started_at=now,
                            created_at=now,
                            updated_at=now,
                            run_context={
                                **request_body,
                                "reading_source": snapshot,
                                "reading_source_digest": digest(snapshot),
                            },
                        )
                        .returning(tables.agent_runs)
                    )
                    .mappings()
                    .one()
                )
                freeze_created_application_run(
                    connection,
                    self.gateway,
                    tenant_id=tenant_id,
                    run_id=row["id"],
                    actor_user_id=actor_id,
                    purpose=purpose,
                    auth_version=auth_version,
                )
        return self._execute(row, snapshot)

    @staticmethod
    def _receipt(row: RowMapping) -> dict[str, Any]:
        return _plain(
            {
                "run_id": row["id"],
                "status": row["status"],
                "error_code": row["error_code"],
                "result": row["run_context"].get("reading_result")
                if not row["run_context"].get("reading_propose_minutes")
                and not row["run_context"].get("reading_propose_actions")
                and not row["run_context"].get("reading_propose_decisions")
                and not row["run_context"].get("reading_propose_business")
                else None,
                "finding_id": row["run_context"].get("reading_finding_id"),
                "finding_ids": row["run_context"].get("reading_finding_ids", []),
            }
        )

    def _execute(self, row: RowMapping, snapshot: dict[str, Any]) -> dict[str, Any]:
        from app.ai.application_domain_context import record, sources_current
        from app.domain.meeting_action_proposals import (
            MeetingActionAssessment,
            persist_actions,
            prompt_data,
        )
        from app.domain.meeting_business_proposals import (
            MeetingBusinessAssessment,
            persist_business,
        )
        from app.domain.meeting_business_proposals import (
            prompt_data as business_prompt,
        )
        from app.domain.meeting_decision_proposals import (
            MeetingDecisionAssessment,
            persist_decisions,
        )
        from app.domain.meeting_decision_proposals import (
            prompt_data as decision_prompt,
        )

        business = bool(row["run_context"].get("reading_propose_business"))
        decisions = bool(row["run_context"].get("reading_propose_decisions"))
        actions = bool(row["run_context"].get("reading_propose_actions"))
        proposal = (
            bool(row["run_context"].get("reading_propose_minutes"))
            or actions
            or decisions
            or business
        )
        purpose = (
            "meeting_business"
            if business
            else "meeting_decisions"
            if decisions
            else "meeting_actions"
            if actions
            else "meeting_minutes"
            if proposal
            else PURPOSE
        )
        proposal_key = (
            BUSINESS_KEY
            if business
            else DECISIONS_KEY
            if decisions
            else ACTIONS_KEY
            if actions
            else MINUTES_KEY
        )
        prompt = (
            PromptFile.model_validate(business_prompt())
            if business
            else PromptFile.model_validate(decision_prompt())
            if decisions
            else PromptFile.model_validate(prompt_data())
            if actions
            else PROMPT
        )
        call_id = model_call_id(
            row["id"],
            ModelCallSlot.MEETING_BUSINESS
            if business
            else ModelCallSlot.MEETING_DECISIONS
            if decisions
            else ModelCallSlot.MEETING_ACTIONS
            if actions
            else ModelCallSlot.MEETING_MINUTES
            if proposal
            else ModelCallSlot.MEETING_READING,
        )
        invocation = GatewayInvocation(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            run_id=row["id"],
            model_call_id=call_id,
            agent_key="knowledge_lite",
            agent_tier=AgentTier.REASONING,
            prompt_version=prompt.version,
            system_prompt=prompt.system_prompt,
            instruction=prompt.instruction,
            context=model_context(snapshot, row["run_context"].get("reading_user_instruction", "")),
        )
        output = None
        error_code = None
        invocation_id = None
        try:
            require_live_key(KEY)
            if proposal:
                require_live_key(proposal_key)
            record(
                self.engine,
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                run_id=row["id"],
                model_call_id=call_id,
                purpose=purpose,
                context=invocation.context,
                snapshot=snapshot,
            )
            result = self.gateway.invoke_structured(
                invocation,
                MeetingBusinessAssessment
                if business
                else MeetingDecisionAssessment
                if decisions
                else MeetingActionAssessment
                if actions
                else MeetingReading,
            )
            if result.status == "degraded" or result.output is None:
                error_code = result.error_code or "MODEL_UNAVAILABLE"
            else:
                if not isinstance(
                    result.output,
                    (
                        MeetingBusinessAssessment,
                        MeetingDecisionAssessment,
                        MeetingActionAssessment,
                        MeetingReading,
                    ),
                ):
                    raise MeetingStateError("MEETING_READING_OUTPUT_INVALID")
                segments = {segment["id"]: segment["content"] for segment in snapshot["segments"]}
                if any(
                    not quote.exact_quote.strip()
                    or quote.exact_quote not in segments.get(str(quote.segment_id), "")
                    for claim in (
                        result.output.proposals
                        if isinstance(result.output, MeetingBusinessAssessment)
                        else result.output.decisions
                        if isinstance(result.output, MeetingDecisionAssessment)
                        else result.output.actions
                        if isinstance(result.output, MeetingActionAssessment)
                        else result.output.claims
                    )
                    for quote in claim.citations
                ):
                    raise MeetingStateError("MEETING_READING_CITATION_INVALID")
                if result.invocation_id is None:
                    raise MeetingStateError("MEETING_READING_TRACE_MISSING")
                if not sources_current(self.engine, invocation, purpose, snapshot):
                    raise MeetingStateError("MEETING_READING_SOURCE_CHANGED")
                output = result.output.model_dump(mode="json")
                invocation_id = result.invocation_id
        except (BudgetLedgerError, CapabilityUnavailableError) as error:
            error_code = error.code
        except MeetingStateError as error:
            error_code = str(error)
        except Exception:
            error_code = "MEETING_READING_EXECUTION_FAILED"
        with self.engine.begin() as connection:
            if proposal and not lock_project_write_scope(
                connection, tenant_id=row["tenant_id"], project_id=row["project_id"]
            ):
                raise MeetingStateError("项目已不可用")
            current = (
                connection.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.tenant_id == row["tenant_id"],
                        tables.agent_runs.c.id == row["id"],
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if current["status"] != "running":
                return self._receipt(current)
            try:
                require_live_key(KEY)
                if proposal:
                    require_live_key(proposal_key)
            except CapabilityUnavailableError as error:
                error_code, output = error.code, None
            bind_write(
                connection, self.gateway, row["tenant_id"], row["id"], success=error_code is None
            )
            now = connection.execute(select(func.clock_timestamp())).scalar_one()
            finding_id = None
            finding_ids: list[str] = []
            if proposal and output is not None and invocation_id is not None and error_code is None:
                from app.domain.meeting_minutes_proposals import (
                    MeetingMinutesProposalError,
                    persist_minutes_proposal,
                )

                try:
                    with connection.begin_nested():
                        if business:
                            finding_ids = persist_business(
                                connection,
                                row=current,
                                snapshot=snapshot,
                                output=output,
                                invocation_id=invocation_id,
                                created_at=now,
                            )
                        elif decisions:
                            finding_ids = persist_decisions(
                                connection,
                                row=current,
                                snapshot=snapshot,
                                output=output,
                                invocation_id=invocation_id,
                                created_at=now,
                            )
                        elif actions:
                            finding_ids = persist_actions(
                                connection,
                                row=current,
                                snapshot=snapshot,
                                output=output,
                                invocation_id=invocation_id,
                                created_at=now,
                            )
                        else:
                            finding_id = persist_minutes_proposal(
                                connection,
                                row=current,
                                snapshot=snapshot,
                                output=output,
                                invocation_id=invocation_id,
                                created_at=now,
                            )
                except (MeetingMinutesProposalError, ValueError):
                    error_code, output = (
                        "MEETING_BUSINESS_PROPOSAL_INVALID"
                        if business
                        else "MEETING_DECISION_PROPOSAL_INVALID"
                        if decisions
                        else "MEETING_ACTION_PROPOSAL_INVALID"
                        if actions
                        else "MEETING_MINUTES_PROPOSAL_INVALID",
                        None,
                    )
            saved = (
                connection.execute(
                    tables.agent_runs.update()
                    .where(
                        tables.agent_runs.c.tenant_id == row["tenant_id"],
                        tables.agent_runs.c.id == row["id"],
                    )
                    .values(
                        status="degraded" if error_code else "succeeded",
                        error_code=error_code,
                        completed_at=now,
                        updated_at=now,
                        run_context={
                            **current["run_context"],
                            "reading_result": output,
                            **(
                                {"reading_finding_ids": finding_ids}
                                if actions or decisions or business
                                else {}
                            ),
                            "reading_invocation_id": str(invocation_id) if invocation_id else None,
                            **(
                                {"reading_finding_id": str(finding_id) if finding_id else None}
                                if proposal
                                else {}
                            ),
                        },
                    )
                    .returning(tables.agent_runs)
                )
                .mappings()
                .one()
            )
            return self._receipt(saved)
