"""Source-bound proposal editing candidates through the existing tenant model gateway."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid5

from sqlalchemy import Connection, Engine, func, select

from app.ai.application_gateway import ApplicationModelGateway
from app.ai.application_leases import bind_write
from app.ai.call_identity import ModelCallSlot, model_call_id
from app.ai.durable import agent_entry
from app.ai.gateway import GatewayInvocation
from app.ai.run_budget_creation import freeze_created_application_run
from app.auth.repository import AuthContext
from app.contracts.product_proposals import ProposalAIRequest, ProposalAssessment, ProposalDocument
from app.db.schema import tables
from app.domain.product_proposals import (
    active_actor,
    proposal_row,
    serial,
    source_catalog,
    validate_document,
)
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _plain, digest

VERSION = "product-proposal-v1"
PURPOSE = "product_proposal"
PROMPT = json.loads((Path(__file__).with_name("prompts") / "product_proposal_v1.json").read_text())


class ProposalOutputError(ProductWorkError):
    pass


def snapshot(c: Connection, ctx: AuthContext, row: Any, instruction: str) -> dict[str, Any]:
    body = dict(
        actor_id=str(ctx.user.id),
        auth_version=ctx.user.auth_version,
        proposal=serial(row),
        source_catalog=source_catalog(c, ctx, row, model=True),
        instruction=instruction,
    )
    return {**body, "digest": digest(body)}


def model_context(source: dict[str, Any]) -> dict[str, object]:
    return {
        "question": json.dumps(
            {
                "instruction": source["instruction"],
                "entry_kind": source["proposal"]["entry_kind"],
                "brief": source["proposal"]["brief"],
                "document": source["proposal"]["document"],
                "source_catalog": source["source_catalog"],
            },
            ensure_ascii=False,
        )
    }


def current(engine: Engine, ctx: AuthContext, source: dict[str, Any]) -> bool:
    try:
        ctx = active_actor(ctx, engine)
        with engine.connect() as c:
            row = proposal_row(
                c, ctx, UUID(source["proposal"]["market_space_id"]), UUID(source["proposal"]["id"])
            )
            return source == snapshot(c, ctx, row, source["instruction"])
    except (ProductWorkAccessError, ProductWorkError):
        return False


def protect_confirmed(before: ProposalDocument, generated: ProposalDocument) -> ProposalDocument:
    """An AI rewrite cannot overwrite human-confirmed specifications, even by omission."""
    bound = {item.id: item for item in before.specifications if item.parameter_id}
    confirmed = {item.id: item for item in before.specifications if item.state == "confirmed"}
    values = []
    for item in generated.specifications:
        if item.id in confirmed:
            values.append(confirmed.pop(item.id))
        else:
            if item.id in bound:
                prior = bound[item.id]
                item = item.model_copy(
                    update={
                        key: getattr(prior, key)
                        for key in (
                            "parameter_id",
                            "parameter_version",
                            "id",
                            "label",
                            "unit",
                            "conditions",
                            "direction",
                        )
                    }
                )
            values.append(
                item.model_copy(update={"state": "ai_draft"}) if item.state == "confirmed" else item
            )
    values.extend(confirmed.values())
    present = {item.id for item in values}
    values.extend(item for key, item in bound.items() if key not in present)
    return generated.model_copy(update={"specifications": values})


def validate_application(c: Connection, ctx: AuthContext, row: Any, run_id: UUID) -> None:
    run = (
        c.execute(
            select(tables.agent_runs).where(
                tables.agent_runs.c.tenant_id == ctx.tenant.id,
                tables.agent_runs.c.id == run_id,
                tables.agent_runs.c.requested_by_user_id == ctx.user.id,
                tables.agent_runs.c.context_version == VERSION,
            )
        )
        .mappings()
        .one_or_none()
    )
    if run is None or run["status"] != "succeeded":
        raise ProductWorkAccessError("AI编辑回执不存在或不属于当前发起人")
    source = run["run_context"]["proposal_source"]
    result = run["run_context"].get("proposal_result", {})
    if (
        source["proposal"] != serial(row)
        or (datetime.now(UTC) >= datetime.fromisoformat(result["fresh_until"]))
        or source != snapshot(c, ctx, row, source["instruction"])
    ):
        raise ProductWorkError("AI编辑稿的原版本、来源或有效期已变化，请重新起草")


class ProposalAI:
    def __init__(self, engine: Engine, gateway: ApplicationModelGateway):
        self.engine, self.gateway = engine, gateway

    @agent_entry
    def generate(
        self, ctx: AuthContext, space: UUID, identity: UUID, request: ProposalAIRequest
    ) -> dict[str, Any]:
        ctx = active_actor(ctx, self.engine)
        run_id = uuid5(identity, str(request.idempotency_key))
        with self.engine.begin() as c:
            row = proposal_row(c, ctx, space, identity, write=True)
            if row["owner_user_id"] != ctx.user.id:
                raise ProductWorkAccessError("仅提案负责人可要求AI改写此草稿")
            old = (
                c.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == ctx.tenant.id,
                        tables.agent_runs.c.id == run_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if (
                    old["run_context"].get("proposal_request_digest")
                    != digest(request.model_dump(mode="json"))
                    or old["requested_by_user_id"] != ctx.user.id
                ):
                    raise ProductWorkError("同一AI请求不能用于不同指令或版本")
                return cast(
                    dict[str, Any],
                    old["run_context"].get(
                        "proposal_result",
                        {"status": "running", "run_id": str(run_id), "document": None},
                    ),
                )
            if row["state"] not in {"draft", "returned"}:
                raise ProductWorkError("请在未提交的提案草稿上起草")
            if (
                row["version"] != request.expected_version
                or serial(row)["payload_digest"] != request.payload_digest
            ):
                raise ProductWorkError("草稿版本已变化，请保存并重新读取后起草")
            source = snapshot(c, ctx, row, request.instruction)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            c.execute(
                tables.agent_runs.insert().values(
                    id=run_id,
                    tenant_id=ctx.tenant.id,
                    project_id=None,
                    scope_kind="tenant",
                    agent_key="ai_chat",
                    request_id=str(run_id),
                    requested_by_user_id=ctx.user.id,
                    status="running",
                    window_started_at=now,
                    window_ended_at=now,
                    event_count=0,
                    event_row_ids=[],
                    context_version=VERSION,
                    run_context={
                        "proposal_source": source,
                        "proposal_request_digest": digest(request.model_dump(mode="json")),
                    },
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            freeze_created_application_run(
                c,
                self.gateway,
                tenant_id=ctx.tenant.id,
                run_id=run_id,
                actor_user_id=ctx.user.id,
                auth_version=ctx.user.auth_version,
                purpose=PURPOSE,
            )
        result: dict[str, Any] = {
            "status": "unavailable",
            "run_id": str(run_id),
            "document": None,
            "error_code": "PROPOSAL_GENERATION_FAILED",
        }
        try:
            from app.ai.application_domain_context import record

            call_id = model_call_id(run_id, ModelCallSlot.CHAT_ANSWER)
            record(
                self.engine,
                tenant_id=ctx.tenant.id,
                project_id=None,
                run_id=run_id,
                model_call_id=call_id,
                purpose=PURPOSE,
                context=model_context(source),
                snapshot=source,
            )
            if not current(self.engine, ctx, source):
                raise ProductWorkError("提案来源或当前权限已变化")
            generated = self.gateway.invoke_structured(
                GatewayInvocation(
                    tenant_id=ctx.tenant.id,
                    project_id=None,
                    run_id=run_id,
                    model_call_id=call_id,
                    agent_key="ai_chat",
                    prompt_version=PROMPT["version"],
                    system_prompt=PROMPT["system_prompt"],
                    instruction=PROMPT["instruction"],
                    context=model_context(source),
                ),
                ProposalAssessment,
            )
            if generated.status == "succeeded" and generated.output:
                if not current(self.engine, ctx, source):
                    raise ProductWorkError("生成过程中来源、草稿或权限已变化")
                document = protect_confirmed(
                    ProposalDocument.model_validate(row["document"]), generated.output.document
                )
                try:
                    validate_document(document, source["source_catalog"])
                except ProductWorkError as error:
                    raise ProposalOutputError(str(error)) from error
                if row["entry_kind"] == "new_product" and len(document.options) < 2:
                    raise ProposalOutputError("新品起草尚未给出至少两个定位方向，请重新起草")
                result = {
                    "status": "prepared",
                    "run_id": str(run_id),
                    "document": document.model_dump(mode="json"),
                    "completed": generated.output.completed,
                    "needs_answers": generated.output.needs_answers,
                    "fresh_until": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
                    "error_code": None,
                    "write_tier": "T1",
                }
            else:
                result["error_code"] = generated.error_code or "PROPOSAL_GENERATION_FAILED"
        except ProposalOutputError as error:
            result["error_code"] = "PROPOSAL_OUTPUT_INVALID"
            result["message"] = str(error)
        except (ProductWorkAccessError, ProductWorkError) as error:
            result["error_code"] = "PROPOSAL_SOURCE_CHANGED"
            result["message"] = str(error)
        except Exception:
            # Failed generation never overwrites a draft or retries with another provider.
            result["error_code"] = "PROPOSAL_GENERATION_FAILED"
        with self.engine.begin() as c:
            run = (
                c.execute(
                    select(tables.agent_runs)
                    .where(tables.agent_runs.c.id == run_id)
                    .with_for_update()
                )
                .mappings()
                .one()
            )
            bind_write(
                c, self.gateway, ctx.tenant.id, run_id, success=result["status"] == "prepared"
            )
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == run_id)
                .values(
                    run_context={**run["run_context"], "proposal_result": _plain(result)},
                    status="succeeded" if result["status"] == "prepared" else "degraded",
                    error_code=result["error_code"],
                    completed_at=func.clock_timestamp(),
                    updated_at=func.clock_timestamp(),
                )
            )
        return result
