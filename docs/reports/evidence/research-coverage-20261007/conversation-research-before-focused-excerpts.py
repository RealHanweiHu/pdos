"""Bounded public research for ordinary conversations, with durable tool receipts."""

from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.exc import IntegrityError

from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.firecrawl import FirecrawlReachTransport
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
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.runtime_records import Observation
from app.db.schema import tables
from app.domain.evidence import (
    EvidenceContentUnavailableError,
    EvidenceService,
    EvidenceValidationError,
)
from app.domain.research_index import extract_page
from app.domain.research_search import resolve_search_provider
from app.settings import get_settings

VERSION = "xiaopai-public-research-v2"
MAX_RESEARCH_STEPS = 7
SEARCH_LIMIT = 6
READ_LIMIT = 24
RESULT_LIMIT = 10
AUTO_READ_LIMIT = 3
REFERENCE_CHARACTER_BUDGET = 24_000
TOOLSET = {
    "version": VERSION,
    "dispatch": "model_selected",
    "tools": [
        {"name": "conversation.search_public", "effect": "read", "result_limit": RESULT_LIMIT},
        {
            "name": "conversation.read_public",
            "effect": "record_observation",
            "character_limit": 6000,
        },
    ],
    "search_limit": SEARCH_LIMIT,
    "read_limit": READ_LIMIT,
    "research_step_limit": MAX_RESEARCH_STEPS,
    "auto_read_limit": AUTO_READ_LIMIT,
}


def url_key(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, "")
    )


def research_context(receipt: dict | None) -> dict:
    items = (receipt or {}).get("observations", [])
    legacy = receipt is not None and receipt.get("version") == "xiaopai-public-research-v1"
    rounds = len((receipt or {}).get("rounds", []))
    searches = sum(item["output"].get("tool") == "search" for item in items)
    reads = sum(item["output"].get("tool") == "read" for item in items)
    candidates = {}
    for item in items:
        for hit in item["output"].get("hits", []):
            candidates.setdefault(
                url_key(hit["url"]),
                {
                    "url": hit["url"],
                    **{key: hit[key][:160] for key in ("title", "snippet") if key in hit},
                },
            )
    read_urls = {
        url_key(item["output"]["target"]) for item in items if item["output"].get("tool") == "read"
    }
    visible_candidates = []
    characters = 0
    for key, candidate in candidates.items():
        if key in read_urls:
            continue
        size = sum(len(value) for value in candidate.values())
        if len(visible_candidates) >= 32 or characters + size > 8000:
            continue
        visible_candidates.append(candidate)
        characters += size
    return {
        "remaining": 0 if legacy else max(0, MAX_RESEARCH_STEPS - rounds),
        "search_remaining": max(0, SEARCH_LIMIT - searches) if not legacy else 0,
        "read_remaining": max(0, READ_LIMIT - reads) if not legacy else 0,
        "searches": searches,
        "read_attempts": reads,
        "sources_read": len((receipt or {}).get("references", [])),
        "candidate_count": len(candidates),
        "candidates": visible_candidates,
        "candidates_truncated": len(visible_candidates) < len(set(candidates) - read_urls),
        "last_action": (receipt or {}).get("rounds", [])[-1:] or [],
        "failures": [
            {
                "tool": item["output"]["tool"],
                "target": item["output"]["target"],
                "source_host": urlsplit(item["output"]["target"]).hostname
                if item["output"]["tool"] == "read"
                else None,
                "error_code": item["output"].get("error_code"),
                "reason": "\n".join(item["output"].get("warnings", []))[:512],
                "attribution": "仅此工具和目标失败，不能归因于其他来源或认定没有证据",
            }
            for item in items
            if item["output"].get("status") == "unavailable"
        ],
        "observations": [
            {
                k: "\n".join(v)[:256] if k == "warnings" else v
                for k, v in item["output"].items()
                if k
                in {
                    "tool",
                    "target",
                    "status",
                    "warnings",
                    "error_code",
                    "shown_count",
                    "total_count",
                    "provider_key",
                    "providers_tried",
                }
            }
            for item in items
        ],
    }


def research_references(receipt: dict | None) -> list[dict]:
    """Expose all source identities within a shared text window; retain full receipts."""
    references = (receipt or {}).get("references", [])
    allowance = min(6000, REFERENCE_CHARACTER_BUDGET // max(1, len(references)))
    return [
        {
            **ref,
            "excerpt": ref["excerpt"][:allowance]
            + (
                "\n[原文摘要截断；未显示部分不可据此推断]"
                if len(ref["excerpt"]) > allowance
                else ""
            ),
        }
        for ref in references
    ]


def receipt_current(
    engine: Engine, context: AuthContext, run_id: UUID, receipt: dict | None
) -> bool:
    if receipt is None:
        return True
    if not is_allowed(context.user.role, Action.EVIDENCE_VIEW):
        return False
    reads = [
        item["output"]
        for item in receipt.get("observations", [])
        if item["output"].get("reference")
    ]
    if (
        receipt.get("version") not in {VERSION, "xiaopai-public-research-v1"}
        or receipt.get("references") != [item["reference"] for item in reads]
        or receipt.get("pins") != [item["pin"] for item in reads]
    ):
        return False
    with engine.connect() as c:
        rc = c.execute(
            select(tables.agent_runs.c.run_context).where(
                tables.agent_runs.c.tenant_id == context.tenant.id, tables.agent_runs.c.id == run_id
            )
        ).scalar_one_or_none()
        if not rc or rc.get("reply_research") != receipt:
            return False
        for item in receipt["observations"]:
            stored = c.execute(
                select(tables.application_tool_observations.c.output_body).where(
                    tables.application_tool_observations.c.tenant_id == context.tenant.id,
                    tables.application_tool_observations.c.run_id == run_id,
                    tables.application_tool_observations.c.id == UUID(item["id"]),
                )
            ).scalar_one_or_none()
            if stored != item["output"]:
                return False
        for pin in receipt["pins"]:
            snap = (
                c.execute(
                    select(tables.evidence_snapshots).where(
                        tables.evidence_snapshots.c.tenant_id == context.tenant.id,
                        tables.evidence_snapshots.c.id == UUID(pin["id"]),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if snap is None or _pin(snap) != pin or snap["superseded_by_id"]:
                return False
            if (
                snap["source_id"]
                and c.execute(
                    select(tables.research_sources.c.status).where(
                        tables.research_sources.c.tenant_id == context.tenant.id,
                        tables.research_sources.c.id == snap["source_id"],
                    )
                ).scalar_one_or_none()
                != "active"
            ):
                return False
    return True


def _pin(row) -> dict:
    return {
        k: str(row[k]) if row[k] is not None else None
        for k in (
            "id",
            "source_id",
            "url",
            "content_digest",
            "captured_at",
            "taint",
            "trust_tier",
            "superseded_by_id",
            "conflicts_with_id",
            "conflict_note",
            "freshness_expires_at",
        )
    }


class ConversationResearch:
    def __init__(self, engine: Engine, gateway: object):
        self.engine, self.gateway = engine, gateway

    def run(self, context, conversation, run_id, call_id, snapshot, choice, emit, check_stop):
        previous = snapshot.get("research_receipt") or {}
        observations = list(previous.get("observations", []))
        references = list(previous.get("references", []))
        pins = list(previous.get("pins", []))
        rounds = list(previous.get("rounds", []))
        available = research_context(previous or None)
        selected_target = (
            " ".join(choice.target.split()).casefold()
            if choice.action == "search"
            else url_key(choice.target)
        )
        prior_targets = {
            " ".join(item["output"]["target"].split()).casefold()
            if choice.action == "search"
            else url_key(item["output"]["target"])
            for item in observations
            if item["output"]["tool"] == choice.action
        }
        skip = (
            "duplicate"
            if selected_target in prior_targets
            else "limit"
            if available["remaining"] == 0 or available[f"{choice.action}_remaining"] == 0
            else None
        )
        rounds.append(
            dict(
                action=choice.action,
                target=choice.target,
                status=skip or "executed",
                model_call_id=str(call_id),
            )
        )

        def check():
            from app.ai.conversation_reply import current

            check_stop()
            if not current(self.engine, context, snapshot):
                raise PermissionError("会话来源或权限已变化")

        def execute(tool: str, target: str, handler: Callable[[], dict]):
            check()
            intent = uuid5(call_id, VERSION + ":" + tool + ":" + target)
            body = {
                "version": VERSION,
                "model_call_id": str(call_id),
                "source_digest": snapshot["digest"],
                "choice": choice.model_dump(mode="json"),
                "tool": tool,
                "target": target,
            }
            with self.engine.begin() as c:
                BudgetLedger._lock(c, context.tenant.id)
                token = self._authorize(c, context, run_id)
                cp = c.execute(
                    select(tables.application_result_checkpoints.c.body).where(
                        tables.application_result_checkpoints.c.tenant_id == context.tenant.id,
                        tables.application_result_checkpoints.c.run_id == run_id,
                        tables.application_result_checkpoints.c.model_call_id == call_id,
                    )
                ).scalar_one()
                if cp["output"].get("research") != choice.model_dump(mode="json"):
                    raise BudgetLedgerError("APPLICATION_TOOL_CHOICE_INVALID")
                prior = c.execute(
                    select(tables.application_tool_observations.c.output_body).where(
                        tables.application_tool_observations.c.tenant_id == context.tenant.id,
                        tables.application_tool_observations.c.tool_intent_id == intent,
                    )
                ).scalar_one_or_none()
                if prior is not None:
                    observations.append({"id": str(uuid5(intent, "observation")), "output": prior})
                    return prior
                if c.execute(
                    select(tables.agent_tool_dispatches.c.intent_id).where(
                        tables.agent_tool_dispatches.c.intent_id == intent
                    )
                ).first():
                    raise BudgetLedgerError("APPLICATION_TOOL_RESULT_UNKNOWN")
                lineage = BudgetLedger._link(c, context.tenant.id, run_id)
                used = c.execute(
                    text("""SELECT cehub_ai.tool_intent_call_count(:t,:l) +
                    (SELECT count(*) FROM (SELECT DISTINCT ON(attempt_id) reservation_status
                     FROM cehub_ai.budget_journal
                     WHERE tenant_id=:t AND lineage_id=:l AND call_kind='tool'
                     ORDER BY attempt_id,revision DESC) latest
                     WHERE reservation_status<>'cancelled_before_dispatch')"""),
                    dict(t=context.tenant.id, l=lineage["id"]),
                ).scalar_one()
                if used >= lineage["profile"]["tool_call_limit"]:
                    raise BudgetLedgerError("BUDGET_TOOL_CALL_COUNT_EXHAUSTED")
                c.execute(
                    tables.agent_tool_intents.insert().values(
                        id=intent,
                        tenant_id=context.tenant.id,
                        run_id=run_id,
                        lineage_id=lineage["id"],
                        call_key=str(intent),
                        tool_key="conversation." + tool + "_public",
                        input_body=body,
                        created_at=func.clock_timestamp(),
                    )
                )
                c.execute(
                    tables.agent_tool_dispatches.insert().values(
                        intent_id=intent,
                        tenant_id=context.tenant.id,
                        run_id=run_id,
                        lease_token=token,
                        created_at=func.clock_timestamp(),
                    )
                )
            # Progress describes an admitted dispatch, never a rejected tool choice.
            emit(
                dict(
                    type="status",
                    message=("正在搜索：" if tool == "search" else "正在读取：") + target,
                    step_key=str(intent),
                    run_id=str(run_id),
                )
            )
            try:
                check()
                data = handler()
            except (
                ReachDeniedError,
                ReachFetchError,
                ReachRateLimitedError,
                ReachSearchUnavailableError,
                EvidenceValidationError,
                EvidenceContentUnavailableError,
            ) as error:
                data = dict(
                    status="unavailable",
                    error_code=type(error).__name__,
                    warnings=[str(error)[:512]],
                )
            check()
            data = {**data, "tool": tool, "target": target}
            with self.engine.begin() as c:
                self._authorize(c, context, run_id)
                auth = (
                    c.execute(
                        select(tables.application_authorizations).where(
                            tables.application_authorizations.c.tenant_id == context.tenant.id,
                            tables.application_authorizations.c.run_id == run_id,
                        )
                    )
                    .mappings()
                    .one()
                )
                stamp = c.execute(select(func.clock_timestamp())).scalar_one()
                oid = uuid5(intent, "observation")
                pin = data.get("pin")
                truncated = (
                    data.get("total_count") is not None
                    and data.get("shown_count", 0) < data["total_count"]
                )
                metadata = Observation.model_validate(
                    dict(
                        id=oid,
                        tenant_id=context.tenant.id,
                        run_id=run_id,
                        tool_call_id=intent,
                        parent_observation_id=None,
                        sequence=1,
                        tool_version=VERSION,
                        status="failed"
                        if data["status"] == "unavailable"
                        else "partial"
                        if data["status"] == "partial"
                        else "completed",
                        sources=[
                            dict(
                                tenant_id=context.tenant.id,
                                project_id=conversation["project_id"],
                                kind="evidence_snapshot",
                                ref_id=UUID(pin["id"]),
                                as_of=pin["captured_at"],
                                digest=pin["content_digest"],
                                locator=pin["url"],
                            )
                        ]
                        if pin
                        else [],
                        observed_at=stamp,
                        as_of=stamp,
                        fresh_until=None,
                        acl_policy_version=auth["body"]["policy_version"],
                        allowed_purpose="xiaopai_reply",
                        taint="untrusted_external",
                        input_digest=digest(body),
                        output_digest=digest(data),
                        shown_count=data.get("shown_count", 0),
                        total_count=data.get("total_count"),
                        truncated=truncated,
                        continuation=(f"snapshot:{pin['id']}" if pin else target)
                        if truncated
                        else None,
                        error_code=data.get("error_code"),
                    )
                )
                c.execute(
                    tables.application_tool_observations.insert().values(
                        id=oid,
                        tenant_id=context.tenant.id,
                        run_id=run_id,
                        authorization_id=auth["id"],
                        tool_intent_id=intent,
                        metadata=metadata.model_dump(mode="json"),
                        output_body=data,
                        created_at=stamp,
                    )
                )
            observations.append({"id": str(oid), "output": data})
            emit(
                dict(
                    type="status",
                    run_id=str(run_id),
                    step_key=str(intent),
                    message=("搜索：" if tool == "search" else "读取：") + target,
                    step_state="failed"
                    if data["status"] == "unavailable"
                    else ("partial" if data["status"] == "partial" else "completed"),
                    detail=(
                        f"{data.get('provider_key', '搜索服务')}"
                        f"返回{data.get('shown_count', 0)}条候选线索。"
                        if tool == "search" and data["status"] != "unavailable"
                        else f"已保存原文快照，提供{data.get('shown_count', 0)}字符正文。"
                        if data.get("reference")
                        else "本次未取得可用资料，保留失败记录。"
                    ),
                )
            )
            return data

        def search():
            settings = get_settings()
            provider = resolve_search_provider(
                self.engine,
                tenant_id=context.tenant.id,
                space_id=conversation["market_space_id"],
                line_id=conversation["product_line_id"],
                endpoint=settings.research_search_endpoint,
                tavily_api_key=(
                    settings.research_tavily_api_key.get_secret_value().strip()
                    if settings.research_tavily_api_key
                    else None
                ),
                firecrawl_api_key=(
                    settings.research_firecrawl_api_key.get_secret_value().strip()
                    if settings.research_firecrawl_api_key
                    else None
                ),
                before_attempt=check,
            )
            result = provider.search(
                choice.target, language="auto", time_range=None, limit=RESULT_LIMIT
            )
            return dict(
                status=result.status,
                hits=result.hits[:RESULT_LIMIT],
                warnings=result.warnings,
                response_digest=result.response_digest,
                shown_count=min(RESULT_LIMIT, len(result.hits)),
                provider_key=result.provider_key or provider.key,
                providers_tried=list(result.providers_tried or (provider.key,)),
            )

        if skip:
            check()
            self._check_authority(context, run_id)
            emit(
                dict(
                    type="status",
                    run_id=str(run_id),
                    message="已跳过重复资料，继续核对覆盖缺口"
                    if skip == "duplicate"
                    else "本轮检索已达到边界，整理已有资料",
                    step_key=f"research-skip-{len(rounds)}",
                    step_state="completed",
                )
            )
            hits = []
        elif choice.action == "search":
            searched = execute("search", choice.target, search)
            new_hits = []
            seen = {
                url_key(item["output"]["target"])
                for item in observations
                if item["output"]["tool"] == "read"
            }
            for hit in searched.get("hits", []):
                key = url_key(hit["url"])
                if key not in seen:
                    new_hits.append(hit)
                    seen.add(key)
            # Prefer different sites while preserving the provider's order within a site.
            sites = set()
            diverse, same_site = [], []
            for hit in new_hits:
                site = urlsplit(hit["url"]).hostname
                (same_site if site in sites else diverse).append(hit)
                sites.add(site)
            hits = (diverse + same_site)[: min(AUTO_READ_LIMIT, available["read_remaining"])]
        else:
            hits = [{"url": choice.target}]
        for hit in hits:

            def read(hit=hit):
                return self._read(context, run_id, hit, check)

            data = execute("read", hit["url"], read)
            if data.get("reference"):
                references.append(data["reference"])
                pins.append(data["pin"])
        check()
        receipt = dict(
            version=VERSION,
            observations=observations,
            references=references,
            pins=pins,
            rounds=rounds,
        )
        with self.engine.begin() as c:
            self._authorize(c, context, run_id)
            row = c.execute(
                select(tables.agent_runs.c.run_context)
                .where(tables.agent_runs.c.id == run_id)
                .with_for_update()
            ).scalar_one()
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == run_id)
                .values(
                    run_context={**row, "reply_research": receipt},
                    updated_at=func.clock_timestamp(),
                )
            )
        return receipt

    def _check_authority(self, context, run_id):
        with self.engine.begin() as connection:
            self._authorize(connection, context, run_id)

    def _authorize(self, c: Connection, context: AuthContext, run_id: UUID) -> UUID:
        if not is_allowed(context.user.role, Action.EVIDENCE_VIEW):
            raise PermissionError("当前岗位不能读取研究资料")
        if not c.execute(
            select(tables.application_authorizations.c.id).where(
                tables.application_authorizations.c.tenant_id == context.tenant.id,
                tables.application_authorizations.c.run_id == run_id,
            )
        ).first():
            raise BudgetLedgerError("APPLICATION_RESEARCH_BUDGET_REQUIRED")
        token = bind_write(c, self.gateway, context.tenant.id, run_id)
        if token is None:
            raise BudgetLedgerError("APPLICATION_RUN_LEASE_REQUIRED")
        c.execute(
            text("SELECT cehub_ai.check_run_active_budget(:t,:r)"),
            dict(t=context.tenant.id, r=run_id),
        )
        return token

    def _read(self, context: AuthContext, run_id: UUID, hit: dict, check: Callable) -> dict:
        evidence = EvidenceService(
            self.engine,
            authorize_write=lambda c: self._authorize_capture(c, context, run_id, check),
        )
        if hit.get("snapshot_id"):
            snapshot_id = UUID(hit["snapshot_id"])
        else:
            key = get_settings().research_firecrawl_api_key
            policy = ReachPolicy()
            source_id = None
            with self.engine.connect() as c:
                rc = c.execute(
                    select(tables.agent_runs.c.run_context).where(
                        tables.agent_runs.c.tenant_id == context.tenant.id,
                        tables.agent_runs.c.id == run_id,
                    )
                ).scalar_one()
            if rc.get("reply_source", {}).get("preproject"):
                # Intake adopts public snapshots through the existing shared evidence contract.
                safe_url = policy.assert_url_allowed(hit["url"])
                parsed = urlsplit(safe_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                source_id = self._public_source(evidence, context, parsed.hostname, origin)
            snapshot_id = (
                ReachService(
                    transport=FirecrawlReachTransport(
                        key.get_secret_value().strip(), before_read=check
                    )
                    if key and key.get_secret_value().strip()
                    else PublicReachTransport(total_timeout=15),
                    evidence=evidence,
                    policy=policy,
                    before_read=check,
                )
                .fetch(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    url=hit["url"],
                    source_id=source_id,
                )
                .snapshot_id
            )
        check()
        body = evidence.read_content(tenant_id=context.tenant.id, snapshot_id=snapshot_id)
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(tables.evidence_snapshots).where(
                        tables.evidence_snapshots.c.tenant_id == context.tenant.id,
                        tables.evidence_snapshots.c.id == snapshot_id,
                    )
                )
                .mappings()
                .one()
            )
        if row["superseded_by_id"]:
            raise EvidenceValidationError("原文快照已被替代")
        page = extract_page(body["content"], base_url=row["url"] or hit["url"])
        if not page.text.strip():
            raise EvidenceValidationError("页面没有可读取的正文")
        excerpt = page.text[:6000]
        notes = [
            f"公开来源；采集时间 {row['captured_at'].isoformat()}；"
            f"taint={row['taint']}；trust={row['trust_tier']}"
        ]
        if row["source_version"] == "firecrawl-scrape-v2":
            notes.append("正文由Firecrawl提取；保留未信任外部资料标记")
        if row["freshness_expires_at"] and row["freshness_expires_at"] <= datetime.now(UTC):
            notes.append("资料已超过新鲜度期限，不能当作最新事实")
        if row["conflicts_with_id"]:
            notes.append("该资料有已记录的来源冲突，需要核对")
        source_host = urlsplit(row["url"]).hostname
        title = page.title or hit.get("title") or row["url"]
        return dict(
            status="partial" if len(page.text) > len(excerpt) else "completed",
            shown_count=len(excerpt),
            total_count=len(page.text),
            pin=_pin(row),
            warnings=notes,
            reference=dict(
                reference_id=f"snapshot:{snapshot_id}",
                entity="evidence_snapshot",
                entity_id=str(snapshot_id),
                label=f"{title} · {source_host}",
                href=row["url"],
                source_host=source_host,
                title_origin="page" if page.title else "search_hint" if hit.get("title") else "url",
                excerpt="；".join(notes) + "\n" + excerpt,
            ),
        )

    def _public_source(self, evidence, context, hostname, origin) -> UUID:
        name = f"公开研究 · {hostname}"

        def existing():
            with self.engine.connect() as c:
                return (
                    c.execute(
                        select(tables.research_sources).where(
                            tables.research_sources.c.tenant_id == context.tenant.id,
                            tables.research_sources.c.name == name,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )

        row = existing()
        if row is None:
            try:
                return evidence.create_source(
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    name=name,
                    source_type="web",
                    base_url=origin,
                    allowed_use="internal_analysis",
                    collection_frequency="on_demand",
                    retention_policy="standard",
                    trust_tier="unknown",
                    license_note="小Pai公开研究原文；仅内部分析，许可与专业适用性待核对",
                ).id
            except IntegrityError as error:
                if getattr(getattr(error.orig, "diag", None), "constraint_name", None) != (
                    "uq_research_sources_tenant_name"
                ):
                    raise
                row = existing()
        if (
            row is None
            or row["source_type"] != "web"
            or row["base_url"] != origin
            or row["allowed_use"] != "internal_analysis"
            or row["status"] != "active"
        ):
            raise EvidenceValidationError("同名公开来源已停用或登记范围不同，请人工核对")
        return row["id"]

    def _authorize_capture(self, c, context, run_id, check):
        check()
        if not is_allowed(context.user.role, Action.EVIDENCE_CAPTURE):
            raise PermissionError("当前岗位不能采集公开资料")
        self._authorize(c, context, run_id)
