"""Private typed conversation adapter for the existing product work runtime."""

from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import Connection, func, select

from app.ai.product_work_context import readable
from app.ai.product_work_preparation import authorize, source_state
from app.ai.product_work_runs import Request, receipt
from app.ai.project_discussion_sources import actor
from app.auth.repository import AuthContext
from app.contracts.product_work_ai import (
    ProductCapability,
    ProductPrivateAttachmentSelection,
    ProductSourceSelection,
    ProductWorkSelection,
)
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError, _plain, digest


class ConversationScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_kind: Literal["project", "personal", "market_space", "product_line"] = "project"
    project_id: UUID | None = None
    meeting_id: UUID | None = None
    market_space_id: UUID | None = None
    product_line_id: UUID | None = None
    visibility: Literal["private", "project"] = "private"

    @model_validator(mode="after")
    def valid_scope(self) -> "ConversationScope":
        from app.domain.conversations import ConversationError

        valid = (
            self.scope_kind == "project"
            and self.project_id is not None
            and self.market_space_id is None
            and self.product_line_id is None
        ) or (
            self.scope_kind != "project"
            and self.project_id is None
            and self.meeting_id is None
            and self.visibility == "private"
            and (
                self.scope_kind == "personal"
                and self.market_space_id is None
                and self.product_line_id is None
                or self.scope_kind == "market_space"
                and self.market_space_id is not None
                and self.product_line_id is None
                or self.scope_kind == "product_line"
                and self.market_space_id is not None
                and self.product_line_id is not None
            )
        )
        if not valid:
            raise ConversationError("会话范围不完整或混用，请从已授权工作页面继续")
        return self


def authorize_private(c: Connection, context: AuthContext, scope: Any) -> None:
    current = actor(c, context.tenant.id, context.user.id)
    if (
        current.user.auth_version != context.user.auth_version
        or current.user.role != context.user.role
        or current.user.role in {"supplier", "customer"}
    ):
        raise ProductWorkAccessError("当前身份已变化或不能使用私人工作会话")
    if scope["scope_kind"] != "personal":
        authorize(c, context, scope["market_space_id"], scope["product_line_id"])


INTENTS: tuple[tuple[ProductCapability, tuple[str, ...]], ...] = (
    ("rfq_requirements", ("rfq", "询价", "客户需求抽取", "抽取需求", "提取需求")),
    ("research_planning", ("研究计划", "研究规划", "调研计划", "调研规划")),
    ("competitor_analysis", ("竞品", "竞争产品", "竞争对手")),
    ("market_analysis", ("市场分析", "市场规模", "市场细分", "用户需求", "jtbd")),
    ("opportunity_mapping", ("机会", "多方案", "方案比较")),
    ("experiment_design", ("实验", "验证假设")),
    ("product_strategy", ("产品策略", "策略方案", "专业约束", "pie约束")),
    ("product_definition", ("产品定义", "定义草案", "规格草案")),
)
LINE_CAPABILITIES = {
    "opportunity_mapping",
    "experiment_design",
    "product_strategy",
    "product_definition",
}


def matrix_intent(body: str) -> bool:
    return any(term in body.lower() for term in ("矩阵", "路线图", "产品定位", "matrix", "roadmap"))


def intent(
    body: str, scope: Any
) -> tuple[ProductCapability | Literal["matrix"] | None, str | None]:
    if scope["scope_kind"] == "personal":
        return None, "说明与附件已私人保存。请进入已授权市场空间或产品线继续产品研究。"
    matches: list[ProductCapability | Literal["matrix"]] = [
        cap for cap, terms in INTENTS if any(t in body.lower() for t in terms)
    ]
    if matrix_intent(body):
        matches.append("matrix")
    if len(matches) != 1:
        return (
            None,
            "说明已保存。请明确本轮目标，例如竞品分析、市场分析或研究规划；多个目标请分轮办理。",
        )
    cap = matches[0]
    if cap in LINE_CAPABILITIES and scope["product_line_id"] is None:
        return None, "说明已保存。此目标需要具体产品线，请进入该产品线后继续。"
    return cap, None


def save(
    c: Connection,
    context: AuthContext,
    conversation: Any,
    *,
    request_id: UUID,
    expected_context_version: int,
    body: str,
    attachment_ids: tuple[UUID, ...],
    product_sources: list[dict[str, Any]],
    matrix_selection: dict[str, Any] | None = None,
    attachment_selections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from app.domain.conversation_attachments import ConversationAttachmentService, bind_attachments
    from app.domain.conversations import ConversationError

    signature = digest(
        _plain(
            {
                "body": body,
                "context_version": expected_context_version,
                "attachment_ids": attachment_ids,
                "product_sources": product_sources,
                **({"matrix_selection": matrix_selection} if matrix_selection is not None else {}),
                **(
                    {"attachment_selections": attachment_selections}
                    if attachment_selections is not None
                    else {}
                ),
            }
        )
    )
    old = (
        c.execute(
            select(tables.conversation_messages).where(
                tables.conversation_messages.c.tenant_id == context.tenant.id,
                tables.conversation_messages.c.conversation_id == conversation["id"],
                tables.conversation_messages.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if old is not None:
        if old["request_digest"] != signature or old["author_user_id"] != context.user.id:
            raise ConversationError("本消息号已提交不同内容，请核对原回执")
        if old["product_work_request"]:
            fixed = old["product_work_request"]
            validate_current_sources(c, context, conversation, fixed)
        return _plain(dict(old)) | {
            "guidance": guidance_for(body, conversation, matrix_selection, attachment_ids)
            if old["action"] == "note"
            else None
        }
    if (
        conversation["archived_at"] is not None
        or conversation["context_version"] != expected_context_version
    ):
        raise ConversationError("会话已归档或范围版本变化，请刷新")
    cap, guidance = intent(body, conversation)
    fragments = [
        ProductPrivateAttachmentSelection.model_validate(s) for s in attachment_selections or []
    ]
    selected_ids = {s.id for s in fragments}
    if (
        len(attachment_ids) > 6
        or len(set(attachment_ids)) != len(attachment_ids)
        or len(fragments) > 6
        or len(selected_ids) != len(fragments)
        or any(
            s.conversation_id != conversation["id"] or s.id not in attachment_ids for s in fragments
        )
    ):
        raise ConversationError("请明确选择本会话附件及其原文片段，不要混用其他会话来源")
    prepared: dict[str, Any] | None = None
    if cap == "matrix":
        if attachment_ids or product_sources or fragments:
            raise ConversationError(
                "矩阵解释使用已保存的矩阵与明确选择的路线图版本，请分轮办理其他资料"
            )
        if matrix_selection is None:
            guidance = "说明已保存。请明确选择已保存的矩阵记录及需要引用的路线图版本，再继续解释。"
        else:
            from app.domain.conversation_matrix import prepare

            prepared = prepare(c, context, conversation, matrix_selection) | {
                "user_instruction": body
            }
    elif cap is not None:
        if matrix_selection is not None:
            raise ConversationError("本轮产品研究目标与所选矩阵记录不一致，请分轮办理")
        sources: list[dict[str, Any]] = [
            ProductSourceSelection.model_validate(s).model_dump(mode="json")
            for s in product_sources
        ]
        if cap == "rfq_requirements" and not attachment_ids:
            guidance = "说明已保存。需求抽取需要本会话已解析的原件，请上传并核对PDF或XLSX。"
        elif attachment_ids and selected_ids != set(attachment_ids):
            guidance = attachment_guidance()
        else:
            for selected in fragments:
                row = ConversationAttachmentService._row(
                    c, context.tenant.id, conversation["id"], selected.id
                )
                if (
                    row["status"] != "extracted"
                    or row["revoked_at"] is not None
                    or row["classification"] != "internal"
                ):
                    raise ConversationError(
                        "产品分析须使用已解析且未撤回的内部附件，或先保存普通说明"
                    )
                available = {
                    fragment["ordinal"]
                    for fragment in row["fragments"]
                    if str(fragment.get("text", "")).strip()
                }
                if any(ordinal not in available for ordinal in selected.ordinals):
                    raise ConversationError("所选原文片段当前不存在或为空，请重新核对原附件")
                sources.append(selected.model_dump(mode="json"))
            selection = ProductWorkSelection.model_validate(
                {
                    "capability": cap,
                    "question": body,
                    "product_line_id": conversation["product_line_id"],
                    "sources": sources,
                }
            )
            snapshot = source_state(c, context, conversation["market_space_id"], selection)
            prepared = {
                "selection": selection.model_dump(mode="json"),
                "expected_digest": snapshot["digest"],
                "user_instruction": body,
            }
    if conversation["scope_kind"] == "personal" and (
        product_sources or matrix_selection is not None
    ):
        raise ConversationError("私人暂存会话不读取未指定市场空间的业务来源")
    message_id = uuid4()
    message = (
        c.execute(
            tables.conversation_messages.insert()
            .values(
                id=message_id,
                tenant_id=context.tenant.id,
                project_id=None,
                conversation_id=conversation["id"],
                author_user_id=context.user.id,
                sequence=conversation["next_sequence"],
                context_version=expected_context_version,
                request_id=request_id,
                request_digest=signature,
                body=body,
                action="product_work" if prepared else "note",
                dispatch_input=body,
                operation_request_id=str(uuid5(message_id, "conversation-operation.v1")),
                product_work_request=prepared,
            )
            .returning(tables.conversation_messages)
        )
        .mappings()
        .one()
    )
    bind_attachments(c, context, conversation, message_id, attachment_ids, message["action"])
    c.execute(
        tables.conversations.update()
        .where(tables.conversations.c.id == conversation["id"])
        .values(next_sequence=conversation["next_sequence"] + 1, updated_at=func.clock_timestamp())
    )
    return _plain(dict(message)) | {"guidance": guidance}


def attachment_guidance() -> str:
    return "说明与附件已私人保存。请为每份附件明确选择已解析、未撤回的内部原文片段，再继续分析。"


def guidance_for(
    body: str,
    conversation: Any,
    matrix_selection: Any = None,
    attachment_ids: tuple[UUID, ...] = (),
) -> str | None:
    cap, guidance = intent(body, conversation)
    if cap == "matrix" and matrix_selection is None:
        return "说明已保存。请明确选择已保存的矩阵记录及需要引用的路线图版本，再继续解释。"
    if cap is not None and cap != "matrix" and attachment_ids:
        return attachment_guidance()
    if cap == "rfq_requirements":
        return "说明已保存。需求抽取需要本会话已解析的原件，请上传并核对PDF或XLSX。"
    return guidance


def is_matrix(fixed: dict[str, Any]) -> bool:
    from app.domain.conversations import ConversationError

    kind = fixed.get("kind", "work")
    if kind not in {"work", "matrix"}:
        raise ConversationError("原消息的产品办理类型不可用，请核对原回执")
    return bool(kind == "matrix")


def validate_current_sources(
    c: Connection, context: AuthContext, conversation: Any, fixed: dict[str, Any]
) -> None:
    if is_matrix(fixed):
        from app.domain.conversation_matrix import prepare
        from app.domain.conversations import ConversationError

        if fixed.get("product_line_id") != (
            str(conversation["product_line_id"]) if conversation["product_line_id"] else None
        ):
            raise ConversationError("原矩阵运行的产品线与本会话不一致")
        # Revalidate current access without replacing the saved selection or digest.
        prepare(c, context, conversation, fixed["selection"])
    else:
        source_state(
            c,
            context,
            conversation["market_space_id"],
            ProductWorkSelection.model_validate(fixed["selection"]),
        )


def product_run(c: Connection, context: AuthContext, conversation: Any, message: Any) -> Any:
    from app.domain.conversations import ConversationError

    if message["action"] != "product_work":
        return None
    fixed = message["product_work_request"]
    matrix = is_matrix(fixed)
    row = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == context.tenant.id,
                tables.agent_runs.c.request_id == message["operation_request_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        # Source access is revalidated even when a model has never started.
        validate_current_sources(c, context, conversation, fixed)
        return None
    prefix = "matrix" if matrix else "product_work"
    expected = {
        f"{prefix}_selection": fixed["selection"],
        f"{prefix}_expected_digest": fixed["expected_digest"],
        f"{prefix}_user_instruction": fixed["user_instruction"],
    }
    if (
        row["scope_kind"] != "market_space"
        or row["project_id"] is not None
        or row["market_space_id"] != conversation["market_space_id"]
        or row["requested_by_user_id"] != message["author_user_id"]
        or row["agent_key"] != "product_management_intelligence"
        or row["context_version"]
        != ("product-matrix-request-v1" if matrix else "product-work-request-v1")
        or any(row["run_context"].get(k) != v for k, v in expected.items())
    ):
        raise ConversationError("原产品运行与保存消息不一致，请核对原回执")
    snapshot = row["run_context"].get(f"{prefix}_source")
    if not isinstance(snapshot, dict) or any(
        snapshot.get(k) != v
        for k, v in {
            "actor_id": str(message["author_user_id"]),
            "market_space_id": str(conversation["market_space_id"]),
            "selection": fixed["selection"],
            "digest": fixed["expected_digest"],
        }.items()
    ):
        raise ConversationError("原产品运行来源与保存消息不一致，请核对原回执")
    if digest({k: v for k, v in snapshot.items() if k != "digest"}) != fixed["expected_digest"]:
        raise ConversationError("原产品运行来源摘要不匹配，请核对原回执")
    if matrix:
        from app.ai.product_matrix_preparation import readable as matrix_readable
        from app.contracts.product_matrix_explanation import MatrixExplanationSelection
        from app.domain.conversation_matrix import authorize_selection

        if fixed.get("product_line_id") != (
            str(conversation["product_line_id"]) if conversation["product_line_id"] else None
        ):
            raise ConversationError("原矩阵运行的产品线与本会话不一致")
        authorize_selection(
            c, context, conversation, MatrixExplanationSelection.model_validate(fixed["selection"])
        )
        matrix_readable(c, context, snapshot)
    else:
        readable(c, context, snapshot)
    return row


def product_receipt(row: Any) -> dict[str, Any]:
    if row["context_version"] == "product-matrix-request-v1":
        from app.ai.product_matrix_runs import receipt as matrix_receipt

        return matrix_receipt(row) | {"runtime": "product_matrix"}
    return receipt(row) | {"runtime": "product_work"}


def get(
    c: Connection, context: AuthContext, conversation: Any, before_sequence: int | None
) -> dict[str, Any]:
    from app.domain.conversation_attachments import message_attachment_ids

    query = select(tables.conversation_messages).where(
        tables.conversation_messages.c.tenant_id == context.tenant.id,
        tables.conversation_messages.c.conversation_id == conversation["id"],
    )
    if before_sequence is not None:
        query = query.where(tables.conversation_messages.c.sequence < before_sequence)
    fetched = list(
        c.execute(
            query.order_by(tables.conversation_messages.c.sequence.desc()).limit(31)
        ).mappings()
    )
    items = []
    for message in reversed(fetched[:30]):
        run = product_run(c, context, conversation, message)
        actual = product_receipt(run) if run is not None else None
        attachments = message_attachment_ids(c, context.tenant.id, message["id"])
        items.append(
            _plain(dict(message))
            | {
                "run": actual,
                "receipt": actual,
                "attachment_ids": [str(a) for a in attachments],
                "guidance": guidance_for(message["body"], conversation, attachment_ids=attachments)
                if message["action"] == "note"
                else None,
            }
        )
    return _plain(
        {
            "conversation": dict(conversation),
            "items": items,
            "next_before": fetched[29]["sequence"] if len(fetched) > 30 else None,
        }
    )


def run_request(message: Any) -> Any:
    fixed = message["product_work_request"]
    if is_matrix(fixed):
        from app.ai.product_matrix_runs import Request as MatrixRequest

        return MatrixRequest(
            request_id=UUID(message["operation_request_id"]),
            **{k: fixed[k] for k in ("selection", "expected_digest", "user_instruction")},
        )
    return Request(
        request_id=UUID(message["operation_request_id"]),
        **{k: fixed[k] for k in ("selection", "expected_digest", "user_instruction")},
    )
