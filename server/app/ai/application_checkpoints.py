"""Durable completed application inference; no automatic takeover or model dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.application_leases import bind_write
from app.ai.budget_ledger import BudgetLedger, BudgetLedgerError
from app.ai.model_catalog import ResolvedModelRoute
from app.db.schema import tables

if TYPE_CHECKING:
    from app.ai.gateway import GatewayInvocation, GatewayResult


def save(
    c: Connection, gateway: object, invocation: GatewayInvocation, result: GatewayResult[BaseModel]
) -> None:
    if result.status != "succeeded" or result.output is None or invocation.run_id is None:
        return
    token = bind_write(c, gateway, invocation.tenant_id, invocation.run_id)
    if token is None:
        return
    observation = (
        c.execute(
            select(tables.application_context_observations).where(
                tables.application_context_observations.c.tenant_id == invocation.tenant_id,
                tables.application_context_observations.c.run_id == invocation.run_id,
                tables.application_context_observations.c.model_call_id == invocation.model_call_id,
            )
        )
        .mappings()
        .one()
    )
    manifest = c.execute(
        select(tables.application_context_manifests.c.id)
        .where(tables.application_context_manifests.c.observation_id == observation["id"])
        .order_by(tables.application_context_manifests.c.revision_no.desc())
        .limit(1)
    ).scalar_one()
    try:
        c.execute(
            tables.application_result_checkpoints.insert().values(
                id=uuid4(),
                tenant_id=invocation.tenant_id,
                run_id=invocation.run_id,
                model_call_id=invocation.model_call_id,
                observation_id=observation["id"],
                manifest_id=manifest,
                invocation_id=result.invocation_id,
                owner_lease_id=token,
                body=dict(
                    version="application-result.v1",
                    status="succeeded",
                    output=result.output.model_dump(mode="json"),
                    structured_attempts=result.structured_attempts,
                    removed_context_paths=list(result.removed_context_paths),
                ),
                created_at=func.clock_timestamp(),
            )
        )
    except DBAPIError as error:
        code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
        if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith(
            ("APPLICATION_", "BUDGET_")
        ):
            raise BudgetLedgerError(code) from error
        raise


def load[OutputT: BaseModel](
    engine: Engine,
    gateway: object,
    invocation: GatewayInvocation,
    output_type: type[OutputT],
    *,
    route: ResolvedModelRoute,
) -> GatewayResult[OutputT] | None:
    from app.ai.gateway import GatewayResult

    if invocation.run_id is None or invocation.model_call_id is None:
        return None
    with engine.begin() as c:
        row = (
            c.execute(
                select(tables.application_result_checkpoints).where(
                    tables.application_result_checkpoints.c.tenant_id == invocation.tenant_id,
                    tables.application_result_checkpoints.c.run_id == invocation.run_id,
                    tables.application_result_checkpoints.c.model_call_id
                    == invocation.model_call_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        # Match finish_model_call's lock order. Ownership comes only from the
        # current request keeper, never from the stored checkpoint's lease id.
        c.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended("
                "'pdos-budget:' || CAST(:t AS text),0))"
            ),
            dict(t=invocation.tenant_id),
        )
        bind_write(c, gateway, invocation.tenant_id, invocation.run_id)
        BudgetLedger._require_active(c, invocation.tenant_id, invocation.run_id)
        trace = (
            c.execute(
                select(tables.model_invocations).where(
                    tables.model_invocations.c.tenant_id == invocation.tenant_id,
                    tables.model_invocations.c.id == row["invocation_id"],
                )
            )
            .mappings()
            .one()
        )
        if (trace["provider"], trace["model"], trace["protocol"], trace["agent_tier"]) != (
            route.provider.value,
            route.model,
            route.protocol.value,
            route.agent_tier.value,
        ):
            raise BudgetLedgerError("APPLICATION_RESULT_MODEL_CHANGED")
        if not c.execute(
            text("SELECT cehub_ai.application_result_receipt_valid(:t,:r,:call,:obs,:m,:i,:l)"),
            dict(
                t=row["tenant_id"],
                r=row["run_id"],
                call=row["model_call_id"],
                obs=row["observation_id"],
                m=row["manifest_id"],
                i=row["invocation_id"],
                l=row["owner_lease_id"],
            ),
        ).scalar_one():
            raise BudgetLedgerError("APPLICATION_RESULT_RECEIPT_INVALID")
        body = row["body"]
        try:
            output = output_type.model_validate(body["output"])
        except ValidationError as error:
            raise BudgetLedgerError("APPLICATION_RESULT_SCHEMA_CHANGED") from error
        return GatewayResult(
            status="succeeded",
            output=output,
            error_code=None,
            structured_attempts=body["structured_attempts"],
            removed_context_paths=tuple(body["removed_context_paths"]),
            invocation_id=row["invocation_id"],
        )
