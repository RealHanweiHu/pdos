"""Pinned source excerpts for intake organization; no implicit whole-file reading."""

import json
from pathlib import Path
from typing import Any

from app.ai.executor import PromptFile
from app.contracts.intake_proposal import PROMPT_VERSION, SOURCE_VERSION

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "intake_organization_v1.json").read_text()
)


def model_context(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("version") != SOURCE_VERSION or PROMPT.version != PROMPT_VERSION:
        raise ValueError("导入整理原文或提示词版本不一致")
    coverage = [
        {
            "attachment_id": identity,
            "filename": item["identity"]["filename"],
            "selected_fragments": item["selected_count"],
            "all_fragments": item["fragment_count"],
            "parser_version": item["identity"]["parser_version"],
            "scope": "仅所选抽取文字；未选片段和排版/图片未知；EML未读附件/外链；XLSX公式不代算",
        }
        for identity, item in source["sources"].items()
    ]
    return {
        "question": json.dumps(
            {
                "instruction": source["instruction"],
                "kinds": source["kinds"],
                "purpose": source["purpose"],
                "coverage": coverage,
            },
            ensure_ascii=False,
        ),
        "references": [
            {
                "reference_id": item["reference_id"],
                "entity": "conversation_attachment_fragment",
                "entity_id": item["attachment_id"],
                "label": item["locator"],
                "excerpt": item["text"],
            }
            for item in source["fragments"]
        ],
    }


PURPOSE = "intake_organization"
RUN_VERSION = "intake-organization-request-v1"
CAPABILITY = "knowledge_lite.intake_organization"
FINDING_TYPE = "intake_organization"


def bound_source(c: Any, tenant: Any, project: Any, actor: Any, context: dict[str, Any]) -> Any:
    from uuid import UUID

    from sqlalchemy import select

    from app.ai.budget_ledger import BudgetLedgerError
    from app.auth.roles import Action
    from app.contracts.intake_proposal import IntakeOrganization
    from app.db.schema import tables
    from app.domain.conversation_attachments import (
        ConversationAttachmentService,
        message_attachment_ids,
    )
    from app.domain.intake_ai_sources import check_source
    from app.domain.issue_intake_preview import source_identity
    from app.domain.knowledge_corrections import KnowledgeCorrectionService
    from app.domain.product_workspace import digest

    try:
        identity = UUID(context["intake_brief_id"])
    except (KeyError, ValueError, TypeError) as error:
        raise BudgetLedgerError("INTAKE_SOURCE_INVALID") from error
    t, conv = tables.intake_ai_briefs, tables.conversations
    row = (
        c.execute(
            select(t)
            .join(conv, (conv.c.tenant_id == t.c.tenant_id) & (conv.c.id == t.c.conversation_id))
            .where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.id == identity,
                t.c.created_by_user_id == actor,
                conv.c.created_by_user_id == actor,
                conv.c.archived_at.is_(None),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise BudgetLedgerError("INTAKE_SOURCE_UNAVAILABLE")
    KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.WORK_ITEM_EDIT)
    expected = {"brief_id": str(row["id"]), **row["source_snapshot"]}
    if (
        context.get("intake_source") != expected
        or context.get("intake_source_digest") != row["source_digest"]
        or digest(row["source_snapshot"]) != row["source_digest"]
        or context.get("intake_root_brief_id") != str(row["root_brief_id"])
        or context.get("intake_prompt_version") != PROMPT_VERSION
        or context.get("intake_prompt_digest") != digest(PROMPT.model_dump(mode="json"))
        or context.get("intake_schema_digest") != digest(IntakeOrganization.model_json_schema())
    ):
        raise BudgetLedgerError("INTAKE_SOURCE_CONTRACT_CHANGED")
    allowed = set(message_attachment_ids(c, tenant, row["message_id"]))
    for key, source in row["source_snapshot"]["sources"].items():
        if UUID(key) not in allowed:
            raise BudgetLedgerError("INTAKE_SOURCE_CHANGED")
        attachment = ConversationAttachmentService._row(
            c, tenant, row["conversation_id"], UUID(key)
        )
        check_source(attachment)
        if source_identity(attachment) != source["identity"]:
            raise BudgetLedgerError("INTAKE_SOURCE_CHANGED")
    return row
