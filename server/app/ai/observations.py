"""Trusted observation persistence; these service methods are not model tools."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.ai.context_projection import project_gateway_context
from app.ai.lease_heartbeat import AgentLeaseLostError
from app.ai.run_store import AgentRunStore
from app.ai.runtime_contract import FrozenRunContext
from app.contracts.common_objects import SourceRef
from app.contracts.runtime_records import AuthorizationEnvelope, Observation


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def context_receipt_body(
    *,
    context: dict[str, object],
    prompt_version: str,
    system_prompt: str,
    instruction: str,
    output_type: type[BaseModel],
) -> dict[str, object]:
    return {
        "version": "projected-context-receipt.v1",
        "context": project_gateway_context(context).payload,
        "prompt_version": prompt_version,
        "system_prompt_sha256": sha256(system_prompt.encode()).hexdigest(),
        "instruction_sha256": sha256(instruction.encode()).hexdigest(),
        "output_schema_sha256": digest(output_type.model_json_schema()),
    }


class AgentObservationError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AgentObservations:
    def __init__(self, engine: Engine, run_store: AgentRunStore):
        if not run_store.projection_only:
            raise ValueError("observations require a restricted run lease")
        self._engine, self._store = engine, run_store

    def _call(self, sql: str, **values: Any) -> Any:
        try:
            with self._engine.begin() as connection:
                self._store.bind(connection)
                return connection.execute(text(sql), values).scalar_one()
        except DBAPIError as error:
            message = getattr(getattr(error.orig, "diag", None), "message_primary", "")
            if getattr(error.orig, "sqlstate", None) == "42501" and "lease" in message.lower():
                raise AgentLeaseLostError("AGENT_RUN_LEASE_LOST") from error
            if getattr(error.orig, "sqlstate", None) == "22023" and message.startswith(
                ("AGENT_", "BUDGET_")
            ):
                raise AgentObservationError(message) from error
            raise

    def authorization(self) -> AuthorizationEnvelope | None:
        body = self._call("SELECT cehub_ai.read_agent_authorization()")
        return AuthorizationEnvelope.model_validate(body) if body is not None else None

    def prepare(
        self,
        *,
        context: FrozenRunContext,
        call_key: str,
        tool_key: str,
        arguments: dict[str, object],
    ) -> UUID:
        return UUID(
            str(
                self._call(
                    "SELECT cehub_ai.prepare_agent_tool_call(:call,:key,:tool,:args)",
                    call=uuid5(context.run_id, call_key),
                    key=call_key,
                    tool=tool_key,
                    args=json.dumps(arguments),
                )
            )
        )

    def dispatch(self, call_id: UUID) -> None:
        # Commit the one-time grant before executing any handler. An uncertain
        # response is never retried automatically, even for a read-only tool.
        self._call("SELECT cehub_ai.dispatch_agent_tool_call(:call)", call=call_id)

    def append(
        self,
        *,
        context: FrozenRunContext,
        call_key: str,
        tool_key: str,
        arguments: dict[str, object],
        output: dict[str, Any],
        error_code: str | None = None,
    ) -> Observation:
        unavailable = output.get("source_status") == "not_enabled"
        failed = error_code is not None
        shown = int(output.get("shown_count", 0))
        total = None if unavailable or failed else int(output.get("total_count", shown))
        # Offset tools report a corpus total; Observation describes this query's
        # remaining window, just like an event query with after_id. Never pretend
        # skipped rows were shown to the model.
        if total is not None and "offset" in arguments:
            total = max(shown, total - int(str(arguments["offset"])))
        truncated = bool(output.get("truncated", False))
        observed_asof = context.built_at if tool_key == "get_project_context" else datetime.now(UTC)
        sources = []
        if not failed:
            if tool_key == "get_project_context":
                sources.append(
                    SourceRef(
                        tenant_id=context.tenant_id,
                        project_id=context.project_id,
                        kind="project",
                        ref_id=context.project_id,
                        as_of=observed_asof,
                        digest=digest(output),
                    )
                )
            else:
                for item in output.get("items", []):
                    ref: UUID | int
                    if tool_key == "get_recent_events":
                        kind, ref = "event", int(item["id"])
                    elif tool_key == "search_memory":
                        kind, ref = "memory", UUID(str(item["memory_id"]))
                    else:
                        kind, ref = str(item["entity"]), UUID(str(item["entity_id"]))
                    sources.append(
                        SourceRef(
                            tenant_id=context.tenant_id,
                            project_id=(
                                None
                                if tool_key
                                in {
                                    "get_portfolio_brief",
                                    "get_supplier_delay_evidence",
                                    "search_memory",
                                }
                                else context.project_id
                            ),
                            kind=kind,
                            ref_id=ref,
                            as_of=observed_asof,
                            digest=digest(item),
                        )
                    )
        meta = Observation(
            id=uuid4(),
            tenant_id=context.tenant_id,
            run_id=context.run_id,
            tool_call_id=uuid5(context.run_id, call_key),
            parent_observation_id=None,
            sequence=1,
            tool_version=f"{tool_key}.v1",
            status=(
                "failed"
                if failed
                else "unavailable"
                if unavailable
                else "partial"
                if truncated
                else "completed"
            ),
            sources=tuple(sources),
            observed_at=datetime.now(UTC),
            as_of=observed_asof,
            fresh_until=None,
            acl_policy_version="agent-projection-lease.v1",
            allowed_purpose="event_assessment",
            taint="verified"
            if tool_key == "search_memory" and not (unavailable or failed)
            else "internal",
            input_digest=digest(arguments),
            output_digest=digest(output),
            shown_count=shown,
            total_count=total,
            truncated=truncated,
            continuation=output.get("continuation"),
            error_code=error_code or ("TOOL_NOT_ENABLED" if unavailable else None),
        )
        body = self._call(
            """SELECT cehub_ai.append_agent_tool_observation(
            :key,:tool,:args,:result,:metadata)""",
            key=call_key,
            tool=tool_key,
            args=json.dumps(arguments),
            result=json.dumps(output),
            metadata=meta.model_dump_json(),
        )
        return Observation.model_validate(body)

    def freeze(self, model_call_id: UUID, body: dict[str, object], ids: tuple[UUID, ...]) -> UUID:
        return UUID(
            str(
                self._call(
                    """SELECT cehub_ai.freeze_agent_context_receipt(
            :call,:body,CAST(:ids AS uuid[]))""",
                    call=model_call_id,
                    body=json.dumps(body),
                    ids=list(ids),
                )
            )
        )

    def verify(self, receipt_id: UUID, model_call_id: UUID | None, body: dict[str, object]) -> None:
        self._call(
            "SELECT cehub_ai.verify_agent_context_receipt(:receipt,:call,:body)",
            receipt=receipt_id,
            call=model_call_id,
            body=json.dumps(body),
        )
