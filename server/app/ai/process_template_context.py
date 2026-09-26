"""Organization-scoped source binding for process-template application runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, RowMapping, select, text

from app.ai.budget_ledger import BudgetLedgerError
from app.db.schema import tables
from app.domain.process_template_briefs import source_status
from app.domain.product_workspace import digest

PURPOSE = "process_template_configuration"
RUN_VERSION = "process-template-request-v1"
PROMPT_VERSION = "process-template-configuration-v9"


def root_brief_id(c: Connection, tenant: UUID, identity: UUID) -> UUID:
    return UUID(
        str(
            c.execute(
                text("""
        WITH RECURSIVE ancestry AS (
          SELECT id,previous_brief_id FROM cehub_core.process_template_briefs
           WHERE tenant_id=:tenant AND id=:identity
          UNION ALL
          SELECT b.id,b.previous_brief_id FROM cehub_core.process_template_briefs b
           JOIN ancestry a ON b.id=a.previous_brief_id WHERE b.tenant_id=:tenant
        ) SELECT id FROM ancestry WHERE previous_brief_id IS NULL
    """),
                {"tenant": tenant, "identity": identity},
            ).scalar_one()
        )
    )


def prompt_data(version: str | None = None) -> dict[str, Any]:
    from app.contracts.process_template_proposal import V1, V2, V3, V4, V5, V6, V7, V8, V9

    selected = version or PROMPT_VERSION
    files = {
        V1: "process_template_configuration_v1.json",
        V2: "process_template_configuration_v2.json",
        V3: "process_template_configuration_v3.json",
        V4: "process_template_configuration_v4.json",
        V5: "process_template_configuration_v5.json",
        V6: "process_template_configuration_v6.json",
        V7: "process_template_configuration_v7.json",
        V8: "process_template_configuration_v8.json",
        V9: "process_template_configuration_v9.json",
    }
    if selected not in files:
        raise BudgetLedgerError("PROCESS_TEMPLATE_PROMPT_VERSION_CHANGED")
    value: dict[str, Any] = json.loads(
        (Path(__file__).with_name("prompts") / files[selected]).read_text()
    )
    if value["version"] != selected or value["agent_key"] != "knowledge_lite":
        raise BudgetLedgerError("PROCESS_TEMPLATE_PROMPT_VERSION_CHANGED")
    return value


def model_context(
    source: dict[str, Any], version: str = "process-template-configuration-v1"
) -> dict[str, Any]:
    from app.contracts.process_template_proposal import V2, V3, V4, V5, V6, V7, V8, V9
    from app.domain.process_template_gates import baseline

    result: dict[str, Any] = {
        "question": source["instruction"],
        "references": [
            {
                "reference_id": "acceptance_criteria",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "原始验收预期",
                "excerpt": source["acceptance_criteria"],
            },
            {
                "reference_id": "base_template",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "冻结模板配置依据（包含完整约束）",
                "excerpt": json.dumps(source["base_snapshot"], ensure_ascii=False, sort_keys=True),
            },
        ],
    }

    if version in {V2, V3, V4, V5, V6, V7, V8, V9}:
        result["references"].append(
            {
                "reference_id": "gate_baseline",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "现有不可降低的阶段签核基线",
                "excerpt": json.dumps(
                    baseline(source["base_snapshot"]), ensure_ascii=False, sort_keys=True
                ),
            }
        )
    if version in {V4, V5, V6, V7, V8, V9}:
        from app.domain.process_template_reminders import policy

        result["references"].append(
            {
                "reference_id": "reminder_policy",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "现有任务与问题提醒规则（含默认值）",
                "excerpt": json.dumps(
                    policy(source["base_snapshot"]).model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    if version in {V5, V6, V7, V8, V9}:
        from app.domain.process_template_approval_routes import routes

        result["references"].append(
            {
                "reference_id": "approval_routes",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "现有阶段签核先后依赖（不改变人员权限）",
                "excerpt": json.dumps(
                    routes(source["base_snapshot"]), ensure_ascii=False, sort_keys=True
                ),
            }
        )
    if version in {V7, V8, V9}:
        from app.domain.process_template_task_fields import definitions

        result["references"].append(
            {
                "reference_id": "task_fields",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "创建版任务补充字段与办理时点",
                "excerpt": json.dumps(
                    {
                        "fields": [
                            item.model_dump(mode="json")
                            for item in definitions(source["base_snapshot"])
                        ],
                        "required_checkpoints": ["in_progress", "done"],
                        "draft_states": ["todo", "blocked", "pending_approval", "skipped"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    if version in {V8, V9}:
        from app.domain.process_template_named_signers import named_slots

        result["references"].append(
            {
                "reference_id": "named_gate_slots",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "创建版具名签核要求及适用边界",
                "excerpt": json.dumps(
                    {
                        "named_gate_slots": named_slots(source["base_snapshot"]),
                        "selection_time": "each_gate_round_open",
                        "eligibility": "active_project_member_with_original_slot_permission",
                        "replacement": "supersede_round_and_repeat_all_applicable_signoffs",
                        "scenarios": ["qualified", "missing", "unqualified", "nonmember"],
                        "scope": "future_project_creation_only",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    if version == V9:
        from app.domain.process_template_risk_fields import definitions as risk_definitions

        result["references"].append(
            {
                "reference_id": "risk_fields",
                "entity": "process_template_brief",
                "entity_id": source["id"],
                "label": "创建版风险补充字段与两条处理路径",
                "excerpt": json.dumps(
                    {
                        "fields": [
                            field.model_dump(mode="json")
                            for field in risk_definitions(source["base_snapshot"])
                        ],
                        "required_checkpoints": {
                            "response": ["mitigating", "watching", "closed"],
                            "closed": ["closed"],
                        },
                        "draft_state": "open",
                        "scope": "confirmed_risks_in_new_projects",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return result


def bound_source(c: Connection, tenant: UUID, context: dict[str, Any]) -> RowMapping:
    try:
        identity = UUID(context["process_template_brief_id"])
    except (ValueError, TypeError, KeyError) as error:
        raise BudgetLedgerError("PROCESS_TEMPLATE_SOURCE_INVALID") from error
    b = tables.process_template_briefs
    row = (
        c.execute(select(b).where(b.c.tenant_id == tenant, b.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or context.get("process_template_source_digest") != row["source_digest"]
        or context.get("process_template_source") != row["source_snapshot"]
        or digest(row["source_snapshot"]) != row["source_digest"]
        or context.get("process_template_root_brief_id") != str(root_brief_id(c, tenant, identity))
    ):
        raise BudgetLedgerError("PROCESS_TEMPLATE_SOURCE_CHANGED")
    if not source_status(c, tenant, row)["source_current"]:
        raise BudgetLedgerError("PROCESS_TEMPLATE_BASE_CHANGED")
    return row
