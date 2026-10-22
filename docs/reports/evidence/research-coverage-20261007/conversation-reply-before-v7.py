"""Durable, read-only multi-turn replies bound to an authorized conversation."""

import json
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from time import monotonic
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, func, select

from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.gateway import GatewayInvocation
from app.ai.observations import digest
from app.ai.provider_streaming import observe_text, partial_answer, partial_approach
from app.ai.reply_progress import ReplyProgress
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.contracts.preproject_dialogue import Assessment
from app.db.schema import tables
from app.domain.conversations import ConversationAccessError, ConversationService
from app.domain.product_workspace import _plain

VERSION = "xiaopai-conversation-v1"
PURPOSE = "xiaopai_reply"
PROMPT = json.loads((Path(__file__).with_name("prompts") / "xiaopai_reply_v6.json").read_text())
PREPROJECT_PROMPT = json.loads(
    (Path(__file__).with_name("prompts") / "preproject_dialogue_v6.json").read_text()
)


def reply_prompt(snapshot: dict) -> dict:
    return PREPROJECT_PROMPT if snapshot.get("preproject") else PROMPT


class ReplyStoppedError(ValueError):
    pass


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    action: Literal["search", "read"]
    target: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def bounded_query(self) -> Self:
        if self.action == "search" and len(self.target) > 512:
            raise ValueError("搜索词最多512字符")
        return self


class ReplyAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    approach: str = Field(
        default="",
        max_length=512,
        description="用户可见的简短处理思路：目标、资料与检查方法，不含内部逐步推理。",
    )
    answer: str = Field(max_length=12_000)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=40)
    research: ResearchRequest | None = None

    @model_validator(mode="after")
    def answer_or_research(self) -> Self:
        if self.research:
            if self.answer or self.citation_ids or getattr(self, "preproject", None):
                raise ValueError("先检索资料，再生成回复和引用")
        elif not self.answer.strip():
            raise ValueError("回复不能为空")
        return self


class PreprojectReplyAssessment(ReplyAssessment):
    preproject: Assessment | None = None


def reply_output(snapshot: dict):
    return PreprojectReplyAssessment if snapshot.get("preproject") else ReplyAssessment


def identity(message_id: UUID) -> UUID:
    return uuid5(message_id, VERSION)


def authorize(engine: Engine, context: AuthContext, conversation_id: UUID, message_id: UUID):
    current = AuthRepository(engine).find_user_context(context.user.id)
    if (
        current is None
        or current.tenant.id != context.tenant.id
        or current.user.auth_version != context.user.auth_version
        or not is_allowed(current.user.role, Action.AI_CHAT_USE)
    ):
        raise ConversationAccessError("当前身份不能继续小Pai会话")
    with engine.connect() as c:
        conversation = ConversationService(engine)._conversation(c, current, conversation_id)
        message = (
            c.execute(
                select(tables.conversation_messages).where(
                    tables.conversation_messages.c.tenant_id == context.tenant.id,
                    tables.conversation_messages.c.conversation_id == conversation_id,
                    tables.conversation_messages.c.id == message_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if message is None:
            raise ConversationAccessError("此消息不属于当前会话")
    return conversation, message


def source(
    engine: Engine, context: AuthContext, conversation_id: UUID, message_id: UUID
) -> dict[str, Any]:
    conversation, message = authorize(engine, context, conversation_id, message_id)
    references: list[dict] = []
    if conversation["project_id"]:
        from app.ai.chat import ChatEvidenceRepository

        references = [
            item.model_dump(mode="json")
            for item in ChatEvidenceRepository(engine).collect(
                tenant_id=context.tenant.id,
                project_id=conversation["project_id"],
                question=message["body"],
                actor_user_id=context.user.id,
            )
        ]
    with engine.connect() as c:
        if conversation["market_space_id"]:
            space = (
                c.execute(
                    select(tables.market_spaces).where(
                        tables.market_spaces.c.id == conversation["market_space_id"],
                        tables.market_spaces.c.tenant_id == context.tenant.id,
                    )
                )
                .mappings()
                .one()
            )
            references.append(
                dict(
                    reference_id=f"space:{space['id']}",
                    entity="market_space",
                    entity_id=str(space["id"]),
                    label=space["title"],
                    href=f"/product-work?space={space['id']}",
                    excerpt=f"当前已授权市场空间：{space['title']}",
                )
            )
        if conversation["product_line_id"]:
            line = (
                c.execute(
                    select(tables.product_nodes).where(
                        tables.product_nodes.c.id == conversation["product_line_id"],
                        tables.product_nodes.c.tenant_id == context.tenant.id,
                    )
                )
                .mappings()
                .one()
            )
            references.append(
                dict(
                    reference_id=f"line:{line['id']}",
                    entity="product_line",
                    entity_id=str(line["id"]),
                    label=line["name"],
                    href=(
                        f"/product-work?space={conversation['market_space_id']}&line={line['id']}"
                    ),
                    excerpt=(
                        f"产品线：{line['code']} · {line['name']} · lifecycle={line['lifecycle']}"
                    ),
                )
            )
        rows = list(
            c.execute(
                select(tables.conversation_messages)
                .where(
                    tables.conversation_messages.c.tenant_id == context.tenant.id,
                    tables.conversation_messages.c.conversation_id == conversation_id,
                    tables.conversation_messages.c.sequence < message["sequence"],
                )
                .order_by(tables.conversation_messages.c.sequence.desc())
                .limit(21)
            ).mappings()
        )
        replies = {
            row["id"]: row["run_context"]
            for row in c.execute(
                select(tables.agent_runs.c.id, tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.id.in_([identity(item["id"]) for item in rows[:20]]),
                    tables.agent_runs.c.context_version == VERSION,
                )
            ).mappings()
        }
        history = []
        for previous in reversed(rows[:20]):
            history.append(dict(role="user", content=previous["body"]))
            result = replies.get(identity(previous["id"]))
            if result and result.get("reply_result", {}).get("status") == "answered":
                # Earlier answers establish dialogue, never current business evidence.
                previous_reply = result["reply_result"]
                links = "\n".join(
                    f"{ref['label']}: {ref['href']}"
                    for ref in previous_reply.get("citations", [])[:2]
                )
                history.append(
                    dict(
                        role="assistant",
                        content=previous_reply["answer"]
                        + ("\n上一轮引用（仅会话线索）：\n" + links if links else ""),
                    )
                )
    snapshot = dict(
        conversation_id=str(conversation_id),
        message_id=str(message_id),
        actor_id=str(context.user.id),
        scope_kind=conversation["scope_kind"],
        context_version=conversation["context_version"],
        archived_at=str(conversation["archived_at"]) if conversation["archived_at"] else None,
        project_id=str(conversation["project_id"]) if conversation["project_id"] else None,
        question=message["body"],
        history=history,
        history_truncated=len(rows) > 20,
        references=references,
    )
    if message["preproject_goal"]:
        from app.domain.preproject_dialogue import dialogue_context

        snapshot["preproject"] = dialogue_context(engine, context, conversation, message)
    return snapshot | {"digest": digest(snapshot)}


def model_context(snapshot: dict) -> dict:
    from app.ai.conversation_research import research_context, research_references

    base = {
        key: snapshot[key] for key in ("question", "history", "history_truncated", "references")
    }
    research = snapshot.get("research_receipt")
    return {
        **base,
        **({"preproject": snapshot["preproject"]} if snapshot.get("preproject") else {}),
        "references": [*base["references"], *research_references(research)],
        "research": research_context(research),
    }


def current(engine: Engine, context: AuthContext, snapshot: dict) -> bool:
    from app.ai.conversation_research import receipt_current

    base = {k: v for k, v in snapshot.items() if k != "research_receipt"}
    return source(
        engine, context, UUID(snapshot["conversation_id"]), UUID(snapshot["message_id"])
    ) == base and receipt_current(
        engine, context, identity(UUID(snapshot["message_id"])), snapshot.get("research_receipt")
    )


def read_reply(
    engine: Engine, context: AuthContext, conversation_id: UUID, message_id: UUID
) -> dict | None:
    authorize(engine, context, conversation_id, message_id)
    with engine.connect() as c:
        run = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == context.tenant.id,
                    tables.agent_runs.c.id == identity(message_id),
                    tables.agent_runs.c.context_version == VERSION,
                )
            )
            .mappings()
            .one_or_none()
        )
    if run is None:
        return None
    original_actor = AuthRepository(engine).find_user_context(run["requested_by_user_id"])
    try:
        valid = original_actor is not None and current(
            engine,
            original_actor,
            {
                **run["run_context"]["reply_source"],
                **(
                    {"research_receipt": run["run_context"]["reply_research"]}
                    if run["run_context"].get("reply_research")
                    else {}
                ),
            },
        )
    except (PermissionError, ValueError):
        valid = False
    if not valid:
        return dict(
            status="unavailable",
            answer=None,
            citations=[],
            error_code="REPLY_SOURCE_CHANGED",
            run_id=str(run["id"]),
        )
    return run["run_context"].get("reply_result") or dict(
        status="running", answer=None, citations=[], run_id=str(run["id"])
    )


class ConversationReplies:
    def __init__(self, engine: Engine, gateway):
        self.engine, self.gateway = engine, gateway

    def answer(
        self,
        context: AuthContext,
        conversation_id: UUID,
        message_id: UUID,
        emit: Callable[[dict], None],
    ) -> dict:
        conversation, message = authorize(self.engine, context, conversation_id, message_id)
        if message["author_user_id"] != context.user.id or conversation["archived_at"] is not None:
            raise ConversationAccessError("只能继续本人提交且未归档的会话消息")
        run_id = identity(message_id)
        snapshot = source(self.engine, context, conversation_id, message_id)
        with self.engine.begin() as c:
            c.execute(
                select(tables.conversations.c.id)
                .where(tables.conversations.c.id == conversation_id)
                .with_for_update()
            ).scalar_one()
            old = (
                c.execute(select(tables.agent_runs).where(tables.agent_runs.c.id == run_id))
                .mappings()
                .one_or_none()
            )
            if old:
                return read_reply(self.engine, context, conversation_id, message_id)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            c.execute(
                tables.agent_runs.insert().values(
                    id=run_id,
                    tenant_id=context.tenant.id,
                    project_id=conversation["project_id"],
                    scope_kind="project" if conversation["project_id"] else "tenant",
                    agent_key="ai_chat",
                    request_id=str(run_id),
                    requested_by_user_id=context.user.id,
                    status="running",
                    window_started_at=now,
                    window_ended_at=now,
                    event_count=0,
                    event_row_ids=[],
                    context_version=VERSION,
                    run_context={"reply_source": snapshot},
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            freeze_created_application_run(
                c,
                self.gateway,
                tenant_id=context.tenant.id,
                run_id=run_id,
                actor_user_id=context.user.id,
                auth_version=context.user.auth_version,
                purpose=PURPOSE,
            )
        progress = ReplyProgress(emit, str(run_id))
        emit = progress.emit
        model_step = "understand"
        progress.step(
            model_step,
            "正在分析问题与当前资料",
            f"已读取本轮问题、{len(snapshot['history'])}条历史消息和"
            f"{len(snapshot['references'])}条当前资料引用。",
        )
        result = dict(
            status="unavailable",
            answer=None,
            citations=[],
            error_code="REPLY_REQUEST_FAILED",
            run_id=str(run_id),
        )
        try:
            from app.ai.application_domain_context import record

            prompt = reply_prompt(snapshot)

            checked_at = 0.0

            def guard_stream():
                nonlocal checked_at
                # Never send text after source/authority changes during generation.
                if monotonic() - checked_at >= 1:
                    self.check_stop(run_id)
                    if not current(self.engine, context, snapshot):
                        raise ConversationAccessError("会话来源或权限已变化")
                    checked_at = monotonic()

            def thinking():
                guard_stream()
                existing = next(step for step in progress.steps if step["key"] == model_step)
                progress.step(model_step, "正在思考", existing["detail"])

            def text(content: str):
                guard_stream()
                approach = partial_approach(content)
                if approach:
                    existing = next(step for step in progress.steps if step["key"] == model_step)
                    if approach != existing["detail"]:
                        progress.step(model_step, existing["label"], approach)
                answer = partial_answer(content)
                if answer:
                    progress.step("answer", "正在组织回复", "整理结论、依据和仍需确认的问题。")
                emit(dict(type="text", text=answer, provisional=True))

            from app.ai.conversation_research import (
                MAX_RESEARCH_STEPS,
                ConversationResearch,
                research_context,
            )

            for research_step in range(MAX_RESEARCH_STEPS + 1):
                call_id = (
                    model_call_id(run_id, ModelCallSlot.CHAT_ANSWER)
                    if research_step == 0
                    else uuid5(run_id, f"xiaopai-research-answer-v2:{research_step}")
                )
                record(
                    self.engine,
                    tenant_id=context.tenant.id,
                    project_id=conversation["project_id"],
                    run_id=run_id,
                    model_call_id=call_id,
                    purpose=PURPOSE,
                    context=model_context(snapshot),
                    snapshot=snapshot,
                )
                if research_step:
                    model_step = f"assess_sources_{research_step}"
                    coverage = research_context(snapshot["research_receipt"])
                    progress.step(
                        model_step,
                        "正在核对覆盖缺口",
                        f"已搜索{coverage['searches']}次、发现{coverage['candidate_count']}条不同线索，"
                        f"读取{coverage['sources_read']}份正文；决定补查还是整理结果。",
                    )
                self.check_stop(run_id)
                with observe_text(text, on_thinking=thinking):
                    generated = self.gateway.invoke_structured(
                        GatewayInvocation(
                            tenant_id=context.tenant.id,
                            project_id=conversation["project_id"],
                            run_id=run_id,
                            model_call_id=call_id,
                            agent_key="ai_chat",
                            prompt_version=prompt["version"],
                            system_prompt=prompt["system_prompt"],
                            instruction=prompt["instruction"],
                            context=model_context(snapshot),
                        ),
                        reply_output(snapshot),
                    )
                self.check_stop(run_id)
                if (
                    generated.status == "succeeded"
                    and generated.output
                    and generated.output.approach
                ):
                    progress.step(
                        model_step,
                        "资料处理思路" if research_step else "处理思路",
                        generated.output.approach,
                        "completed",
                    )
                if (
                    generated.status != "succeeded"
                    or not generated.output
                    or not generated.output.research
                ):
                    break
                if research_context(snapshot.get("research_receipt"))["remaining"] == 0:
                    break
                if not current(self.engine, context, snapshot):
                    raise ConversationAccessError("会话来源或权限已变化")
                research = ConversationResearch(self.engine, self.gateway).run(
                    context,
                    conversation,
                    run_id,
                    call_id,
                    snapshot,
                    generated.output.research,
                    emit,
                    lambda: self.check_stop(run_id),
                )
                snapshot = {**snapshot, "research_receipt": research}
            if generated.output is None or generated.status != "succeeded":
                result["error_code"] = generated.error_code or "MODEL_UNAVAILABLE"
            elif not current(self.engine, context, snapshot):
                result["error_code"] = "REPLY_SOURCE_CHANGED"
            else:
                refs = {
                    item["reference_id"]: item for item in model_context(snapshot)["references"]
                }
                if generated.output.research:
                    result["error_code"] = "RESEARCH_STEP_LIMIT"
                elif any(cid not in refs for cid in generated.output.citation_ids):
                    result["error_code"] = "CITATION_SCOPE_INVALID"
                else:
                    result = dict(
                        status="answered",
                        answer=generated.output.answer,
                        citations=[
                            refs[cid]
                            for cid in dict.fromkeys(
                                [
                                    *generated.output.citation_ids,
                                    *(
                                        item["reference_id"]
                                        for item in snapshot.get("research_receipt", {}).get(
                                            "references", []
                                        )
                                    ),
                                ]
                            )
                        ],
                        error_code=None,
                        run_id=str(run_id),
                    )
                    if snapshot.get("preproject"):
                        from app.domain.preproject_dialogue import validate_assessment

                        try:
                            assessment = validate_assessment(generated.output.preproject, snapshot)
                        except ValueError:
                            result.update(
                                status="unavailable",
                                answer=None,
                                citations=[],
                                error_code="PREPROJECT_OUTPUT_INVALID",
                            )
                        else:
                            result["preproject"] = {
                                **assessment.model_dump(mode="json"),
                                "candidate_digest": digest(assessment.model_dump(mode="json")),
                            }
                    elif getattr(generated.output, "preproject", None):
                        result.update(
                            status="unavailable",
                            answer=None,
                            citations=[],
                            error_code="PREPROJECT_OUTPUT_INVALID",
                        )
            if (
                snapshot.get("research_receipt")
                and result.get("error_code") != "REPLY_SOURCE_CHANGED"
            ):
                result["research"] = {
                    **model_context(snapshot)["research"],
                    **(
                        {"remaining": 0, "stop_reason": "model_completed"}
                        if result["status"] == "answered"
                        else {}
                    ),
                }
            result["process"] = progress.finish(result)
            self.finish(context, run_id, result)
            return result
        except ReplyStoppedError:
            result["error_code"] = "REPLY_CANCELLED"
            result["process"] = progress.finish(result)
            self.finish(context, run_id, result)
            return result
        except BudgetLedgerError as error:
            result["error_code"] = error.code
            result["process"] = progress.finish(result)
            with suppress(Exception):
                self.finish(context, run_id, result)
            if error.code == "APPLICATION_RESEARCH_BUDGET_REQUIRED":
                # The message is saved and this known configuration failure is terminal.
                # Return its receipt so the composer can continue without a retry loop.
                return result
            raise
        except Exception:
            result["process"] = progress.finish(result)
            with suppress(Exception):
                self.finish(context, run_id, result)
            raise

    def check_stop(self, run_id: UUID) -> None:
        with self.engine.connect() as c:
            rc = c.execute(
                select(tables.agent_runs.c.run_context).where(tables.agent_runs.c.id == run_id)
            ).scalar_one()
        if rc.get("reply_stop_requested"):
            raise ReplyStoppedError("回复已停止")

    def finish(self, context: AuthContext, run_id: UUID, result: dict) -> None:
        with self.engine.begin() as c:
            row = (
                c.execute(
                    select(tables.agent_runs)
                    .where(
                        tables.agent_runs.c.id == run_id,
                        tables.agent_runs.c.tenant_id == context.tenant.id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            if row["status"] != "running":
                return
            bind_write(
                c, self.gateway, context.tenant.id, run_id, success=result["status"] == "answered"
            )
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == run_id)
                .values(
                    run_context={**row["run_context"], "reply_result": _plain(result)},
                    status="succeeded" if result["status"] == "answered" else "degraded",
                    error_code=result.get("error_code"),
                    completed_at=func.clock_timestamp(),
                    updated_at=func.clock_timestamp(),
                )
            )
