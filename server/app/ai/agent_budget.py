"""Run-lease budget ports using service-frozen lineages and current tenant settings.

No policy publication, scope binding, model qualification or default adoption is
granted here. Methods are runtime metadata services, never model tools.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.ai.budget_evidence import BudgetRequestBinding, BudgetUsageEvidence
from app.ai.budget_ledger import BudgetLedgerError, BudgetReceipt, _receipt
from app.ai.run_store import AgentRunStore
from app.contracts.runtime_policy import RunBudgetProfile


class RestrictedBudgetTransitions:
    def __init__(self, engine: Engine, run_store: AgentRunStore):
        if not run_store.projection_only:
            raise ValueError("restricted budget transitions require a run lease")
        self._engine, self._store = engine, run_store

    def transition(
        self,
        *,
        attempt_id: UUID,
        action: Literal["dispatch", "unknown", "cancel", "settle"],
        evidence: BudgetUsageEvidence | None = None,
    ) -> BudgetReceipt:
        if action not in {"dispatch", "unknown", "cancel", "settle"} or (
            (action == "settle") != (evidence is not None)
        ):
            raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
        body = (
            json.dumps(
                evidence.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if evidence is not None
            else None
        )
        try:
            with self._engine.begin() as connection:
                self._store.bind(connection)
                result = connection.execute(
                    text("SELECT cehub_ai.agent_transition_model_budget(:attempt, :action, :body)"),
                    {"attempt": attempt_id, "action": action, "body": body},
                ).scalar_one()
        except DBAPIError as error:
            diagnostic = getattr(error.orig, "diag", None)
            code = getattr(diagnostic, "message_primary", "")
            if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
                raise BudgetLedgerError(code) from error
            raise
        return _receipt(
            result["row"], changed=result["changed"], dispatch=result["dispatch_granted"]
        )


class RestrictedBudgetLedger:
    """Complete controller port; lineage provisioning remains a trusted service action."""

    def __init__(self, engine: Engine, run_store: AgentRunStore):
        if not run_store.projection_only:
            raise ValueError("restricted budget ledger requires a run lease")
        self._engine, self._store = engine, run_store

    def _call(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID | None = None,
        statement: str | None = None,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        try:
            with self._engine.begin() as connection:
                self._store.bind(connection)
                scope = connection.execute(
                    text("SELECT cehub_ai.agent_budget_profile()")
                ).scalar_one()
                if UUID(scope["tenant_id"]) != tenant_id or (
                    run_id is not None and UUID(scope["run_id"]) != run_id
                ):
                    raise BudgetLedgerError("BUDGET_RUN_SCOPE_INVALID")
                if statement is None:
                    return cast(dict[str, Any], scope)
                return cast(
                    dict[str, Any],
                    connection.execute(text(statement), parameters or {}).scalar_one(),
                )
        except DBAPIError as error:
            diagnostic = getattr(error.orig, "diag", None)
            code = getattr(diagnostic, "message_primary", "")
            if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
                raise BudgetLedgerError(code) from error
            raise

    def open_lineage(self, *, tenant_id: UUID, run_id: UUID, profile: RunBudgetProfile) -> UUID:
        scope = self._call(tenant_id=tenant_id, run_id=run_id)
        if RunBudgetProfile.model_validate(scope["profile"]) != profile:
            raise BudgetLedgerError("BUDGET_PROFILE_CONFLICT")
        return UUID(scope["lineage_id"])

    def require_active(self, *, tenant_id: UUID, run_id: UUID) -> None:
        self._call(
            tenant_id=tenant_id,
            run_id=run_id,
            statement="SELECT cehub_ai.agent_check_active_budget()",
        )

    def reserve(
        self,
        *,
        tenant_id: UUID,
        run_id: UUID,
        attempt_id: UUID,
        call_kind: Literal["model", "tool"],
        input_tokens: int,
        output_tokens: int,
        tenant_daily_token_limit: int,
        request_binding: BudgetRequestBinding | None = None,
    ) -> BudgetReceipt:
        # The database's current tenant setting is the authority. No caller-supplied
        # quota is sent to the restricted SQL function.
        del tenant_daily_token_limit
        if (
            call_kind != "model"
            or request_binding is None
            or request_binding.output_limit != output_tokens
            or type(input_tokens) is not int
            or input_tokens < 0
        ):
            raise BudgetLedgerError("BUDGET_REQUEST_BINDING_INVALID")
        result = self._call(
            tenant_id=tenant_id,
            run_id=run_id,
            statement=(
                "SELECT cehub_ai.agent_reserve_model_budget("
                ":attempt,:inputs,CAST(:binding AS jsonb))"
            ),
            parameters=dict(
                attempt=attempt_id,
                inputs=input_tokens,
                binding=json.dumps(request_binding.model_dump(mode="json")),
            ),
        )
        return _receipt(result["row"], changed=result["changed"])

    def transition(
        self,
        *,
        tenant_id: UUID,
        attempt_id: UUID,
        action: Literal["dispatch", "unknown", "cancel", "settle"],
        charged_tokens: int | None = None,
        reconciliation_ref: str | None = None,
        provider_request_id: str | None = None,
        usage_evidence: BudgetUsageEvidence | None = None,
    ) -> BudgetReceipt:
        if action not in {"dispatch", "unknown", "cancel", "settle"}:
            raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
        if action == "settle":
            if (
                usage_evidence is None
                or charged_tokens != usage_evidence.input_tokens + usage_evidence.output_tokens
                or provider_request_id != usage_evidence.request_id
                or reconciliation_ref != usage_evidence.evidence_ref
            ):
                raise BudgetLedgerError("BUDGET_SETTLEMENT_EVIDENCE_CONFLICT")
        elif any(
            v is not None
            for v in (charged_tokens, reconciliation_ref, provider_request_id, usage_evidence)
        ):
            raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
        body = (
            json.dumps(
                usage_evidence.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            if usage_evidence is not None
            else None
        )
        result = self._call(
            tenant_id=tenant_id,
            statement="SELECT cehub_ai.agent_transition_model_budget(:attempt,:action,:body)",
            parameters=dict(attempt=attempt_id, action=action, body=body),
        )
        return _receipt(
            result["row"], changed=result["changed"], dispatch=result["dispatch_granted"]
        )
