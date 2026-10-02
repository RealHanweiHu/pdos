"""Source-backed project working memory, separate from verified organization knowledge."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, select

from app.ai.chat import ChatEvidence
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService


def evidence(
    c: Connection, tenant: UUID, project: UUID, actor: UUID, question: str
) -> list[ChatEvidence]:
    KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.WORK_ITEM_VIEW)
    m, conversation = tables.conversation_messages, tables.conversations
    messages = (
        c.execute(
            select(m.c.id, m.c.body, m.c.author_user_id, m.c.conversation_id, m.c.created_at)
            .join(conversation, conversation.c.id == m.c.conversation_id)
            .where(
                m.c.tenant_id == tenant,
                m.c.project_id == project,
                conversation.c.visibility == "project",
                conversation.c.archived_at.is_(None),
                m.c.action.in_(("note", "project_query")),
                m.c.object_focus.is_(None),
            )
            .order_by(m.c.created_at.desc(), m.c.id.desc())
            .limit(20)
        )
        .mappings()
        .all()
    )
    return [
        ChatEvidence(
            reference_id=f"project-note:{m['id']}",
            entity="project_working_memory",
            entity_id=str(m["id"]),
            label="项目成员补充说明（未核实的工作记忆）",
            href=f"/ask?project={project}&conversation={m['conversation_id']}",
            excerpt=f"作者：{m['author_user_id']}；记录时间：{m['created_at']}。以下是共享会话原话，只能证明成员曾这样说明，不是已核实业务事实、正式知识或批准；后续纠正和当前业务记录优先。\n{m['body']}",
        )
        for m in messages
        if not question.endswith(m["body"])
    ]
