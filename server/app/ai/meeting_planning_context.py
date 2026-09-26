"""Pinned, current project briefing context for ad-hoc meeting generation."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.executor import PromptFile
from app.auth.roles import Action
from app.contracts.meeting_plan import PROMPT_VERSION, MeetingAssessment, references
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.meeting_planning import current, source_value
from app.domain.meeting_preparation import SOURCE_TABLES, MeetingPreparationService
from app.domain.product_workspace import digest

PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "meeting_planning_v1.json").read_text()
)


def fixed_context(original: Any) -> dict[str, Any]:
    return {
        "meeting_planning_brief_id": str(original["id"]),
        "meeting_planning_root_brief_id": str(original["root_id"]),
        "meeting_planning_source_digest": original["source_digest"],
        "meeting_planning_source": {
            "brief_id": str(original["id"]),
            "source_digest": original["source_digest"],
            **original["source_snapshot"],
        },
        "meeting_planning_prompt_version": PROMPT.version,
        "meeting_planning_prompt_digest": digest(PROMPT.model_dump(mode="json")),
        "meeting_planning_schema_digest": digest(MeetingAssessment.model_json_schema()),
    }


def model_context(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": json.dumps(
            {
                key: source[key]
                for key in (
                    "title",
                    "meeting_type",
                    "question",
                    "expected_output",
                    "timezone",
                    "proposed_start_at",
                    "proposed_end_at",
                    "participants",
                    "missing",
                    "template",
                )
            }
            | {
                "coverage": [
                    {
                        "kind": s["kind"],
                        "id": s["id"],
                        "title": s["title"],
                        "omitted_characters": s.get("omitted_characters", {}),
                    }
                    for s in source["sources"]
                ]
            },
            ensure_ascii=False,
        ),
        "references": references(source),
    }


def bound_source(
    c: Connection, tenant: UUID, project: UUID, actor: UUID, rc: dict[str, Any]
) -> Any:
    KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.MEETING_MANAGE)
    KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.WORK_ITEM_VIEW)
    t = tables.meeting_planning_briefs
    try:
        identity = UUID(rc["meeting_planning_brief_id"])
    except (KeyError, TypeError, ValueError) as error:
        raise BudgetLedgerError("MEETING_PLANNING_SOURCE_INVALID") from error
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == tenant,
                t.c.project_id == project,
                t.c.id == identity,
                t.c.created_by_user_id == actor,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or current(c, row)["id"] != row["id"]:
        raise BudgetLedgerError("MEETING_PLANNING_SOURCE_SUPERSEDED")
    state = c.execute(
        select(tables.projects.c.status).where(
            tables.projects.c.tenant_id == tenant, tables.projects.c.id == project
        )
    ).scalar_one()
    if state in ("completed", "archived"):
        raise BudgetLedgerError("MEETING_PLANNING_PROJECT_READONLY")
    expected = {
        "brief_id": str(identity),
        "source_digest": row["source_digest"],
        **row["source_snapshot"],
    }
    if (
        rc.get("meeting_planning_source") != expected
        or rc.get("meeting_planning_source_digest") != row["source_digest"]
        or digest(row["source_snapshot"]) != row["source_digest"]
        or rc.get("meeting_planning_root_brief_id") != str(row["root_id"])
        or rc.get("meeting_planning_prompt_version") != PROMPT_VERSION
        or rc.get("meeting_planning_prompt_digest") != digest(PROMPT.model_dump(mode="json"))
        or rc.get("meeting_planning_schema_digest") != digest(MeetingAssessment.model_json_schema())
    ):
        raise BudgetLedgerError("MEETING_PLANNING_CONTRACT_CHANGED")
    people = {str(p["id"]): p for p in MeetingPreparationService.members(c, tenant, project)}
    for p in row["source_snapshot"]["participants"]:
        if p["id"] not in people or any(
            str(people[p["id"]][k]) != str(p[k]) for k in ("display_name", "role")
        ):
            raise BudgetLedgerError("MEETING_PLANNING_PEOPLE_CHANGED")
    for s in row["source_snapshot"]["sources"]:
        table = SOURCE_TABLES[s["kind"]][0]
        actual = (
            c.execute(
                select(table).where(
                    table.c.tenant_id == tenant,
                    table.c.project_id == project,
                    table.c.id == UUID(s["id"]),
                )
            )
            .mappings()
            .one_or_none()
        )
        if actual is None or source_value(actual, s["kind"], project) != s:
            raise BudgetLedgerError("MEETING_PLANNING_EVIDENCE_CHANGED")
    return row
