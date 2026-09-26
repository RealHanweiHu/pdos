"""Durable public research dispatch with the original discussion authority and budget."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, RowMapping, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_authorization import verify_application_authorization
from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.discussion_research_loop import KEY, VERSION, ResearchChoice
from app.ai.observations import digest
from app.ai.reach import (
    ReachDeniedError,
    ReachFetchError,
    ReachPolicy,
    ReachRateLimitedError,
    ReachSearchUnavailableError,
    ReachService,
)
from app.ai.reach_transport import PublicReachTransport
from app.ai.research_search import SearxSearchProvider
from app.ai.rollout_guard import require_live_key
from app.auth.roles import Action
from app.contracts.runtime_records import Observation
from app.db.schema import tables
from app.domain.evidence import EvidenceService, EvidenceValidationError
from app.domain.product_workspace import ProductWorkError, _plain, _role
from app.settings import get_settings

TOOLS = {"search": "research.search_public", "read": "research.capture_snapshot"}


def observations(c: Connection, tenant: UUID, run: UUID) -> list[dict[str, Any]]:
    o, i = tables.application_tool_observations, tables.agent_tool_intents
    return [
        _plain(dict(v))
        for v in c.execute(
            select(o, i.c.tool_key, i.c.input_body)
            .join(i, (i.c.tenant_id == o.c.tenant_id) & (i.c.id == o.c.tool_intent_id))
            .where(
                o.c.tenant_id == tenant, o.c.run_id == run, i.c.tool_key.in_(list(TOOLS.values()))
            )
            .order_by(o.c.created_at, o.c.id)
        ).mappings()
    ]


def additions(c: Connection, tenant: UUID, run: UUID) -> list[dict[str, Any]]:
    result = []
    for item in observations(c, tenant, run):
        data = item["output_body"]
        if not data.get("reference"):
            continue
        ref = data["reference"]
        result.append(
            {
                "id": item["id"],
                "snapshot_id": ref["fields"]["id"],
                "origin": "agent_research",
                "created_at": item["created_at"],
                "reference": ref,
                "request": {
                    "snapshot_id": ref["fields"]["id"],
                    "offset": item["input_body"]["choice"]["offset"],
                    "length": item["input_body"]["choice"]["length"],
                    "note": item["input_body"]["choice"]["reason"],
                },
            }
        )
    return result


def authorize(c: Connection, gateway: object, row: RowMapping) -> UUID:
    from app.ai.project_discussion_sources import actor

    require_live_key(KEY)
    token = bind_write(c, gateway, row["tenant_id"], row["id"])
    if token is None:
        raise BudgetLedgerError("APPLICATION_RUN_LEASE_REQUIRED")
    context = actor(c, row["tenant_id"], row["requested_by_user_id"])
    _role(context, Action.EVIDENCE_VIEW)
    _role(context, Action.EVIDENCE_CAPTURE)
    try:
        c.execute(
            text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
            dict(t=row["tenant_id"], r=row["id"]),
        )
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
            raise BudgetLedgerError(code) from error
        raise
    return token


def execute(
    engine: Engine, gateway: object, row: RowMapping, call: UUID, choice: ResearchChoice
) -> dict[str, Any]:
    """Commit dispatch before network I/O; an unknown result is never re-fetched."""
    if choice.action not in TOOLS:
        raise ProductWorkError("本次没有可派发的研究工具")
    verify_application_authorization(
        engine,
        tenant_id=row["tenant_id"],
        run_id=row["id"],
        project_id=row["project_id"],
        agent_key=row["agent_key"],
    )
    tool = TOOLS[choice.action]
    intent = uuid5(call, VERSION + ":" + tool)
    with engine.begin() as c:
        BudgetLedger._lock(c, row["tenant_id"])
        token = authorize(c, gateway, row)
        cp = (
            c.execute(
                select(tables.application_result_checkpoints).where(
                    tables.application_result_checkpoints.c.tenant_id == row["tenant_id"],
                    tables.application_result_checkpoints.c.run_id == row["id"],
                    tables.application_result_checkpoints.c.model_call_id == call,
                )
            )
            .mappings()
            .one()
        )
        if cp["body"]["output"] != choice.model_dump(mode="json"):
            raise ProductWorkError("研究工具须来自原模型成功回执")
        body = {
            "version": VERSION,
            "checkpoint_id": str(cp["id"]),
            "model_call_id": str(call),
            "source_digest": row["run_context"]["discussion_source_digest"],
            "choice": choice.model_dump(mode="json"),
        }
        prior = c.execute(
            select(tables.application_tool_observations.c.output_body).where(
                tables.application_tool_observations.c.tenant_id == row["tenant_id"],
                tables.application_tool_observations.c.run_id == row["id"],
                tables.application_tool_observations.c.tool_intent_id == intent,
            )
        ).scalar_one_or_none()
        if prior is not None:
            return dict(prior)
        old = (
            c.execute(
                select(tables.agent_tool_intents).where(
                    tables.agent_tool_intents.c.id == intent,
                )
            )
            .mappings()
            .one_or_none()
        )
        if old is not None and (old["input_body"] != body or old["tool_key"] != tool):
            raise ProductWorkError("不能改写原研究请求")
        if c.execute(
            select(tables.agent_tool_dispatches.c.intent_id).where(
                tables.agent_tool_dispatches.c.intent_id == intent,
            )
        ).first():
            raise BudgetLedgerError("APPLICATION_TOOL_RESULT_UNKNOWN")
        if old is None:
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
                    call_key=VERSION + ":" + str(call),
                    tool_key=tool,
                    input_body=body,
                    created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                )
            )
        c.execute(
            tables.agent_tool_dispatches.insert().values(
                intent_id=intent,
                tenant_id=row["tenant_id"],
                run_id=row["id"],
                lease_token=token,
                created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
            )
        )

    def before_read() -> None:
        with engine.begin() as c:
            authorize(c, gateway, row)

    def authorize_capture(c: Connection) -> None:
        authorize(c, gateway, row)

    data: dict[str, Any]
    status, shown, error_code = "completed", 0, None
    try:
        before_read()
        if choice.action == "search":
            provider = SearxSearchProvider(get_settings().research_search_endpoint)
            result = provider.search(choice.target or "", language="auto", time_range=None, limit=5)
            status = (
                "partial"
                if result.status == "partial"
                else "failed"
                if result.status == "unavailable"
                else "completed"
            )
            data = {
                "status": result.status,
                "hits": result.hits,
                "warnings": result.warnings,
                "response_digest": result.response_digest,
                "reference": None,
                "notice": "搜索命中仅作线索，必须读取实际原文快照才可引用",
            }
            shown = len(result.hits)
            if result.status == "unavailable":
                error_code = "SEARCH_UNAVAILABLE"
        else:
            captured = ReachService(
                transport=PublicReachTransport(total_timeout=20),
                evidence=EvidenceService(engine, authorize_write=authorize_capture),
                policy=ReachPolicy(),
                before_read=before_read,
            ).fetch(
                tenant_id=row["tenant_id"],
                actor_user_id=row["requested_by_user_id"],
                url=choice.target or "",
            )
            from app.ai.discussion_research import Preview, preview
            from app.ai.project_discussion_sources import actor

            with engine.begin() as c:
                authorize(c, gateway, row)
                selected = preview(
                    c,
                    actor(c, row["tenant_id"], row["requested_by_user_id"]),
                    Preview(
                        snapshot_id=captured.snapshot_id, offset=choice.offset, length=choice.length
                    ),
                )
            shown = len(selected["reference"]["fields"]["excerpt"])
            status = "partial" if shown < selected["total_characters"] else "completed"
            data = {
                "status": status,
                "reference": selected["reference"],
                "total_characters": selected["total_characters"],
                "redirect_chain": list(captured.redirect_chain),
                "notice": "公开原文快照仍需核对；只向本次讨论传入所选片段",
            }
    except ReachSearchUnavailableError:
        status, error_code = (
            "failed",
            "SEARCH_NOT_CONFIGURED"
            if not get_settings().research_search_endpoint
            else "SEARCH_UNAVAILABLE",
        )
        data = {
            "status": "unavailable",
            "error_code": error_code,
            "reference": None,
            "notice": "搜索服务尚未配置或暂不可用，不代表没有结果",
        }
    except (
        ReachDeniedError,
        ReachFetchError,
        ReachRateLimitedError,
        EvidenceValidationError,
        ProductWorkError,
    ) as error:
        status, error_code = "failed", getattr(error, "reason", "RESEARCH_READ_UNAVAILABLE")
        data = {
            "status": "denied" if isinstance(error, ReachDeniedError) else "unavailable",
            "error_code": error_code,
            "reference": None,
            "notice": "本次公开资料未读取成功，不能把失败当作不存在证据",
        }
    with engine.begin() as c:
        authorize(c, gateway, row)
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
        stamp = c.execute(select(func.clock_timestamp())).scalar_one()
        oid = uuid5(intent, "observation")
        ref = data.get("reference")
        observed = Observation.model_validate(
            dict(
                id=oid,
                tenant_id=row["tenant_id"],
                run_id=row["id"],
                tool_call_id=intent,
                parent_observation_id=None,
                sequence=1,
                tool_version=tool + ".v1",
                status=status,
                sources=[
                    dict(
                        tenant_id=row["tenant_id"],
                        project_id=row["project_id"],
                        kind="evidence_snapshot",
                        ref_id=UUID(ref["fields"]["id"]),
                        as_of=ref["fields"]["captured_at"],
                        digest=ref["fields"]["content_digest"],
                        locator=ref["fields"]["url"],
                    )
                ]
                if ref
                else [],
                observed_at=stamp,
                as_of=stamp,
                fresh_until=None,
                acl_policy_version=auth["body"]["policy_version"],
                allowed_purpose="change_discussion",
                taint="untrusted_external",
                input_digest=digest(body),
                output_digest=digest(data),
                shown_count=shown,
                total_count=data.get("total_characters"),
                truncated=bool(ref and status == "partial"),
                continuation="读取后续片段" if ref and status == "partial" else None,
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
                output_body=data,
                created_at=stamp,
            )
        )
        from app.ai.change_discussion_runs import event

        event(
            c, row["tenant_id"], UUID(row["run_context"]["debate_session_id"]), "research_observed"
        )
    return data
