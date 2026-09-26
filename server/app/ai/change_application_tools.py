"""Fixed engineering handlers with shared call admission and immutable observations.

Handlers run inside the observation transaction: the reader is pure and the
candidate writer uses this connection. No remote calls or business application
are available here. A committed result is replayed without redispatch.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, RowMapping, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_authorization import verify_application_authorization
from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.change_impact_preparation import trace_impact
from app.ai.observations import digest
from app.ai.rollout_guard import require_live_key
from app.contracts.change_work_package import ChangeImpactAssessment
from app.contracts.runtime_records import Observation
from app.contracts.tool_payloads import BoundHandle, TraceImpactInput
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError

VERSION = "application-engineering-tools.v1"
CAPABILITY = "engineering_intelligence.change_work_package"
TRACE = "engineering.trace_impact"
PREPARE = "change.prepare_work_package"
TOOLSET = {
    "version": VERSION,
    "dispatch": "server_fixed_sequence",
    "tools": [
        {"name": TRACE, "version": "engineering.trace_impact.v1", "effect": "read"},
        {"name": PREPARE, "version": "change.prepare_work_package.v1", "effect": "propose_finding"},
    ],
}


def arguments(
    row: RowMapping,
    tool: str,
    *,
    output: ChangeImpactAssessment | None = None,
    invocation_id: UUID | None = None,
) -> dict[str, Any]:
    snapshot = row["run_context"]["impact_source"]
    body: dict[str, Any] = {
        "version": VERSION,
        "ecr_id": snapshot["ecr_id"],
        "source_digest": snapshot["digest"],
    }
    if tool == TRACE:
        root = next(
            r
            for r in snapshot["model_context"]["references"]
            if r["reference_id"] == "ecr:" + snapshot["ecr_id"]
        )
        request = TraceImpactInput(
            changed_objects=(BoundHandle(handle=root["reference_id"], digest=root["digest"]),),
            proposed_change="追踪本次固定工程变更资料的显式引用；变更内容按原 ECR 引用判断",
            depth=row["run_context"]["impact_depth"],
        )
        body["request"] = request.model_dump(mode="json")
    elif tool == PREPARE and output is not None and invocation_id is not None:
        body.update(assessment=output.model_dump(mode="json"), invocation_id=str(invocation_id))
    else:
        raise ProductWorkError("工程工具输入不完整")
    return body


def admit(
    engine: Engine, gateway: object, row: RowMapping, tool: str, body: dict[str, Any]
) -> UUID:
    """Reserve one call using the same tenant lock and cumulative event-run ledger."""
    require_live_key(CAPABILITY)
    from app.ai.change_notice_preparation import require_enabled

    require_enabled(row["run_context"]["impact_source"])
    verify_application_authorization(
        engine,
        tenant_id=row["tenant_id"],
        run_id=row["id"],
        project_id=row["project_id"],
        agent_key=row["agent_key"],
    )
    if tool not in {TRACE, PREPARE} or body["version"] != VERSION:
        raise ProductWorkError("本次未登记该工程工具")
    call_key = VERSION + ":" + tool
    intent = uuid5(row["id"], call_key)
    try:
        with engine.begin() as c:
            BudgetLedger._lock(c, row["tenant_id"])
            bind_write(c, gateway, row["tenant_id"], row["id"])
            current = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.tenant_id == row["tenant_id"],
                    tables.agent_runs.c.id == row["id"],
                )
            ).scalar_one()
            auth = c.execute(
                select(tables.application_authorizations.c.body).where(
                    tables.application_authorizations.c.tenant_id == row["tenant_id"],
                    tables.application_authorizations.c.run_id == row["id"],
                )
            ).scalar_one()
            if (
                current.get("impact_toolset_version") != VERSION
                or auth["purpose"] != "change_work_package"
                or auth["toolset_version"] != VERSION
                or body["source_digest"] != current["impact_source"]["digest"]
                or body["ecr_id"] != current["impact_ecr_id"]
            ):
                raise ProductWorkError("原运行工具或资料版本已不可用")
            old = (
                c.execute(
                    select(tables.agent_tool_intents).where(
                        tables.agent_tool_intents.c.tenant_id == row["tenant_id"],
                        tables.agent_tool_intents.c.run_id == row["id"],
                        tables.agent_tool_intents.c.call_key == call_key,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                if old["id"] != intent or old["input_body"] != body or old["tool_key"] != tool:
                    raise ProductWorkError("不能改写原工具请求")
                return intent
            c.execute(
                text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
                dict(t=row["tenant_id"], r=row["id"]),
            )
            lineage = BudgetLedger._link(c, row["tenant_id"], row["id"])
            if lineage is None:
                raise BudgetLedgerError("BUDGET_RUN_UNBOUND")
            used = c.execute(
                text("""SELECT cehub_ai.tool_intent_call_count(:t,:l) +
              (SELECT count(*) FROM (SELECT DISTINCT ON(attempt_id) reservation_status
               FROM cehub_ai.budget_journal
               WHERE tenant_id=:t AND lineage_id=:l AND call_kind='tool'
               ORDER BY attempt_id,revision DESC) latest
               WHERE reservation_status<>'cancelled_before_dispatch')"""),
                dict(t=row["tenant_id"], l=lineage["id"]),
            ).scalar_one()
            limit = lineage["profile"].get("tool_call_limit")
            if type(limit) is not int or limit < 1:
                raise BudgetLedgerError("BUDGET_TOOL_PROFILE_INVALID")
            if used >= limit:
                raise BudgetLedgerError("BUDGET_TOOL_CALL_COUNT_EXHAUSTED")
            c.execute(
                tables.agent_tool_intents.insert().values(
                    id=intent,
                    tenant_id=row["tenant_id"],
                    run_id=row["id"],
                    lineage_id=lineage["id"],
                    call_key=call_key,
                    tool_key=tool,
                    input_body=body,
                    created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                )
            )
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
            raise BudgetLedgerError(code) from error
        raise
    return intent


def dispatch(c: Connection, gateway: object, row: RowMapping, intent: UUID) -> dict[str, Any]:
    """Caller owns the transaction (and project lock for candidate creation)."""
    require_live_key(CAPABILITY)
    from app.ai.change_notice_preparation import require_enabled

    require_enabled(row["run_context"]["impact_source"])
    token = bind_write(c, gateway, row["tenant_id"], row["id"])
    if token is None:
        raise BudgetLedgerError("APPLICATION_RUN_LEASE_REQUIRED")
    original = (
        c.execute(
            select(tables.agent_tool_intents).where(
                tables.agent_tool_intents.c.tenant_id == row["tenant_id"],
                tables.agent_tool_intents.c.run_id == row["id"],
                tables.agent_tool_intents.c.id == intent,
            )
        )
        .mappings()
        .one()
    )
    prior = (
        c.execute(
            select(tables.application_tool_observations).where(
                tables.application_tool_observations.c.tenant_id == row["tenant_id"],
                tables.application_tool_observations.c.run_id == row["id"],
                tables.application_tool_observations.c.tool_intent_id == intent,
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior is not None:
        return {"observation_id": str(prior["id"]), **prior["output_body"]}
    if (
        c.execute(
            select(tables.agent_tool_dispatches.c.intent_id).where(
                tables.agent_tool_dispatches.c.intent_id == intent
            )
        ).first()
        is not None
    ):
        raise BudgetLedgerError("APPLICATION_TOOL_RESULT_UNKNOWN")
    c.execute(
        text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
        dict(t=row["tenant_id"], r=row["id"]),
    )
    stamp = c.execute(select(func.clock_timestamp())).scalar_one()
    c.execute(
        tables.agent_tool_dispatches.insert().values(
            intent_id=intent,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            lease_token=token,
            created_at=stamp,
        )
    )
    tool, body, snapshot = (
        original["tool_key"],
        original["input_body"],
        row["run_context"]["impact_source"],
    )
    result: dict[str, Any]
    error_code = None
    try:
        with c.begin_nested():
            if tool == TRACE:
                output = trace_impact(snapshot, TraceImpactInput.model_validate(body["request"]))
                result = {"data": output.model_dump(mode="json")}
                shown, status = len(output.links), "partial" if output.missing else "completed"
            elif tool == PREPARE:
                from app.domain.change_work_package_proposals import persist

                assessment = ChangeImpactAssessment.model_validate(body["assessment"])
                finding = persist(
                    c,
                    row=row,
                    snapshot=snapshot,
                    output=assessment,
                    invocation_id=UUID(body["invocation_id"]),
                    created_at=stamp,
                )
                result = {
                    "finding_id": str(finding) if finding else None,
                    "missing": assessment.missing,
                    "disposition": assessment.disposition,
                }
                shown, status = int(finding is not None), "completed" if finding else "partial"
            else:
                raise ProductWorkError("本次未登记该工程工具")
    except (ProductWorkError, ValueError):
        error_code, shown, status = "CHANGE_TOOL_SOURCE_OR_OUTPUT_INVALID", 0, "failed"
        result = {"error_code": error_code}
    # Candidate mutation and observation both roll back if authority expired.
    bind_write(c, gateway, row["tenant_id"], row["id"])
    auth = (
        c.execute(
            select(tables.application_authorizations).where(
                tables.application_authorizations.c.tenant_id == row["tenant_id"],
                tables.application_authorizations.c.run_id == row["id"],
            )
        )
        .mappings()
        .one()
    )
    oid = uuid5(intent, "observation")
    finished = c.execute(select(func.clock_timestamp())).scalar_one()
    sources = [
        dict(
            tenant_id=row["tenant_id"],
            project_id=row["project_id"],
            kind="change_impact_snapshot",
            ref_id=UUID(snapshot["ecr_id"]),
            as_of=snapshot["read_at"],
            digest=snapshot["digest"],
        )
    ]
    derived_from = []
    if tool == PREPARE:
        sources.append(
            dict(
                tenant_id=row["tenant_id"],
                project_id=row["project_id"],
                kind="model_invocation",
                ref_id=UUID(body["invocation_id"]),
                as_of=stamp,
                digest=digest(body["assessment"]),
            )
        )
        derived_from = [uuid5(uuid5(row["id"], VERSION + ":" + TRACE), "observation")]
    observed = Observation.model_validate(
        dict(
            id=oid,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            tool_call_id=intent,
            parent_observation_id=None,
            sequence=1 if tool == TRACE else 2,
            tool_version=tool + ".v1",
            status=status,
            sources=sources,
            derived_from_ids=derived_from,
            observed_at=finished,
            as_of=stamp,
            fresh_until=None,
            acl_policy_version=auth["body"]["policy_version"],
            allowed_purpose="change_work_package",
            taint="untrusted_external",
            input_digest=digest(body),
            output_digest=digest(result),
            shown_count=shown,
            total_count=None,
            truncated=False,
            continuation=None,
            error_code=error_code,
        )
    )
    c.execute(
        tables.application_tool_observations.insert().values(
            id=oid,
            tenant_id=row["tenant_id"],
            run_id=row["id"],
            authorization_id=auth["id"],
            tool_intent_id=intent,
            metadata=observed.model_dump(mode="json"),
            output_body=result,
            created_at=finished,
        )
    )
    current = c.execute(
        select(tables.agent_runs.c.run_context).where(
            tables.agent_runs.c.tenant_id == row["tenant_id"], tables.agent_runs.c.id == row["id"]
        )
    ).scalar_one()
    receipts = {
        **current.get("impact_tool_receipts", {}),
        tool: {
            "observation_id": str(oid),
            "status": status,
            "shown_count": shown,
            "created_at": finished.isoformat(),
            "error_code": error_code,
            "missing": result.get("data", result).get("missing", []),
        },
    }
    c.execute(
        tables.agent_runs.update()
        .where(
            tables.agent_runs.c.tenant_id == row["tenant_id"], tables.agent_runs.c.id == row["id"]
        )
        .values(run_context={**current, "impact_tool_receipts": receipts}, updated_at=finished)
    )
    return {"observation_id": str(oid), **result}


def trace_context(result: dict[str, Any]) -> str:
    """Bound the model projection; every relationship points to an original ref."""
    from app.ai.change_impact_preparation import encoded

    data = result["data"]
    links = data["links"]
    return encoded(
        {
            "tool": TRACE,
            "observation_id": result["observation_id"],
            "relationship_references": [
                link["rationale"]["citations"][0]["handle"] for link in links[:100]
            ],
            "shown_relationships": min(len(links), 100),
            "total_relationships": len(links),
            "missing": data["missing"][:20],
            "omitted_missing_count": max(0, len(data["missing"]) - 20),
            "limit": (
                "仅显式引用关系；不能据此判断变更影响或执行依赖。请引用原资料字段，缺项保持未知。"
            ),
        }
    )
