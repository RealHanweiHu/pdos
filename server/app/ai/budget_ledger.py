"""Transactional, append-only token reservations for server-bound runs.

This is an owner/service persistence port, not a model tool or authorization
issuer. Callers must authorize linked scopes and verify settlement evidence.
Monetary enforcement and recovery supervision remain separate adoption work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.budget_evidence import BudgetRequestBinding, BudgetUsageEvidence
from app.contracts.runtime_policy import BudgetEntry, RunBudgetProfile
from app.db.schema import tables


class BudgetLedgerError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BudgetReceipt:
    entry: BudgetEntry
    revision: int
    changed: bool
    dispatch_granted: bool = False


def _profile_digest(profile: RunBudgetProfile) -> str:
    body = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(body.encode()).hexdigest()


def _receipt(
    row: RowMapping | dict[str, Any], *, changed: bool, dispatch: bool = False
) -> BudgetReceipt:
    return BudgetReceipt(
        entry=BudgetEntry.model_validate({key: row[key] for key in BudgetEntry.model_fields}),
        revision=int(row["revision"]),
        changed=changed,
        dispatch_granted=dispatch,
    )


class BudgetLedger:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _require_active(connection: Connection, tenant_id: UUID, run_id: UUID) -> None:
        try:
            connection.execute(
                text("SELECT cehub_ai.check_run_active_budget(:tenant,:run)"),
                {"tenant": tenant_id, "run": run_id},
            )
        except DBAPIError as error:
            code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
            if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
                raise BudgetLedgerError(code) from error
            raise

    def require_active(self, *, tenant_id: UUID, run_id: UUID) -> None:
        with self._engine.begin() as connection:
            self._require_active(connection, tenant_id, run_id)

    @staticmethod
    def _lock(connection: Connection, tenant_id: UUID) -> datetime:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"pdos-budget:{tenant_id}"},
        )
        return cast(
            datetime, connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        ).astimezone(UTC)

    @staticmethod
    def _require_run(
        connection: Connection, tenant_id: UUID, run_id: UUID, *, active: bool = False
    ) -> None:
        status = connection.execute(
            select(tables.agent_runs.c.status).where(
                tables.agent_runs.c.tenant_id == tenant_id,
                tables.agent_runs.c.id == run_id,
            )
        ).scalar_one_or_none()
        if status is None:
            raise BudgetLedgerError("BUDGET_RUN_SCOPE_INVALID")
        if active and status != "running":
            raise BudgetLedgerError("BUDGET_RUN_NOT_RUNNING")

    @staticmethod
    def _link(connection: Connection, tenant_id: UUID, run_id: UUID) -> RowMapping | None:
        return (
            connection.execute(
                select(tables.budget_lineages)
                .join(
                    tables.budget_run_links,
                    (tables.budget_lineages.c.tenant_id == tables.budget_run_links.c.tenant_id)
                    & (tables.budget_lineages.c.id == tables.budget_run_links.c.lineage_id),
                )
                .where(
                    tables.budget_run_links.c.tenant_id == tenant_id,
                    tables.budget_run_links.c.run_id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def freeze_created_run(
        connection: Connection,
        *,
        tenant_id: UUID,
        run_id: UUID,
        profile: RunBudgetProfile,
        parent_run_id: UUID | None = None,
    ) -> UUID:
        """Bind a fresh INSERT in its transaction; never allocate on model invocation.

        The new run is not visible outside this transaction and its unique link
        cannot race another creator. Parent links/profiles are immutable. No tenant
        budget lock is needed here (nor taken after the request's tenant row lock).
        Callers authorize the parent business relation before providing its run.
        """
        row = (
            connection.execute(
                text("""SELECT project_id, scope_kind, market_space_id,
                  requested_by_user_id, run_context,
                  context_version, status FROM cehub_ai.agent_runs
                WHERE tenant_id=:tenant AND id=:run
                  AND xmin::text::numeric = pg_current_xact_id()::text::numeric % 4294967296"""),
                {"tenant": tenant_id, "run": run_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["status"] != "running":
            raise BudgetLedgerError("BUDGET_RUN_CREATION_REQUIRED")
        if BudgetLedger._link(connection, tenant_id, run_id) is not None:
            raise BudgetLedgerError("BUDGET_RUN_ALREADY_BOUND")
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        if parent_run_id is not None:
            parent_run = (
                connection.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.tenant_id == tenant_id,
                        tables.agent_runs.c.id == parent_run_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                parent_run is None
                or parent_run["project_id"] != row["project_id"]
                or parent_run["scope_kind"] != row["scope_kind"]
                or parent_run["market_space_id"] != row["market_space_id"]
                or parent_run_id == run_id
            ):
                raise BudgetLedgerError("BUDGET_PARENT_SCOPE_INVALID")
            if row["scope_kind"] == "market_space" and (
                parent_run["requested_by_user_id"] != row["requested_by_user_id"]
                or parent_run["context_version"] != row["context_version"]
                or parent_run["run_context"].get("matrix_selection", {}).get("record_id")
                != row["run_context"].get("matrix_selection", {}).get("record_id")
            ):
                raise BudgetLedgerError("BUDGET_PARENT_SCOPE_INVALID")
            if row["scope_kind"] == "tenant":
                original = parent_run["run_context"].get("process_template_root_brief_id")
                current = row["run_context"].get("process_template_source", {})
                if (
                    parent_run["context_version"] != row["context_version"]
                    or not original
                    or original != row["run_context"].get("process_template_root_brief_id")
                    or parent_run["run_context"]
                    .get("process_template_source", {})
                    .get("template_id")
                    != current.get("template_id")
                ):
                    raise BudgetLedgerError("BUDGET_PARENT_SCOPE_INVALID")
            parent = BudgetLedger._link(connection, tenant_id, parent_run_id)
            if parent is None:
                raise BudgetLedgerError("BUDGET_PARENT_RUN_UNBOUND")
            if parent["profile_digest"] != _profile_digest(profile):
                raise BudgetLedgerError("BUDGET_PROFILE_CONFLICT")
            if now >= parent["absolute_deadline"]:
                raise BudgetLedgerError("BUDGET_LINEAGE_EXPIRED")
            lineage_id = UUID(str(parent["id"]))
        else:
            lineage_id = uuid4()
            connection.execute(
                tables.budget_lineages.insert().values(
                    id=lineage_id,
                    tenant_id=tenant_id,
                    profile=profile.model_dump(mode="json"),
                    profile_digest=_profile_digest(profile),
                    created_at=now,
                    absolute_deadline=now + timedelta(seconds=profile.lifetime_seconds),
                )
            )
        try:
            connection.execute(
                tables.budget_run_links.insert().values(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    lineage_id=lineage_id,
                    created_at=now,
                )
            )
        except DBAPIError as error:
            code = getattr(getattr(error.orig, "diag", None), "message_primary", "")
            if (
                getattr(error.orig, "sqlstate", None) == "22023"
                and code == "BUDGET_LINEAGE_CANCELLED"
            ):
                raise BudgetLedgerError(code) from error
            raise
        return lineage_id

    def open_lineage(self, *, tenant_id: UUID, run_id: UUID, profile: RunBudgetProfile) -> UUID:
        with self._engine.begin() as connection:
            now = self._lock(connection, tenant_id)
            self._require_run(connection, tenant_id, run_id)
            existing = self._link(connection, tenant_id, run_id)
            digest = _profile_digest(profile)
            if existing is not None:
                if existing["profile_digest"] != digest:
                    raise BudgetLedgerError("BUDGET_PROFILE_CONFLICT")
                return UUID(str(existing["id"]))
            lineage_id = uuid4()
            connection.execute(
                tables.budget_lineages.insert(),
                {
                    "id": lineage_id,
                    "tenant_id": tenant_id,
                    "profile": profile.model_dump(mode="json"),
                    "profile_digest": digest,
                    "created_at": now,
                    "absolute_deadline": now + timedelta(seconds=profile.lifetime_seconds),
                },
            )
            connection.execute(
                tables.budget_run_links.insert(),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "lineage_id": lineage_id,
                    "created_at": now,
                },
            )
            return lineage_id

    def link_run(self, *, tenant_id: UUID, lineage_id: UUID, run_id: UUID) -> None:
        with self._engine.begin() as connection:
            now = self._lock(connection, tenant_id)
            self._require_run(connection, tenant_id, run_id)
            if (
                connection.execute(
                    select(tables.budget_lineages.c.id).where(
                        tables.budget_lineages.c.tenant_id == tenant_id,
                        tables.budget_lineages.c.id == lineage_id,
                    )
                ).first()
                is None
            ):
                raise BudgetLedgerError("BUDGET_LINEAGE_SCOPE_INVALID")
            existing = self._link(connection, tenant_id, run_id)
            if existing is not None:
                if existing["id"] != lineage_id:
                    raise BudgetLedgerError("BUDGET_RUN_ALREADY_BOUND")
                return
            connection.execute(
                tables.budget_run_links.insert(),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "lineage_id": lineage_id,
                    "created_at": now,
                },
            )

    @staticmethod
    def _attempt(connection: Connection, tenant_id: UUID, attempt_id: UUID) -> RowMapping | None:
        return (
            connection.execute(
                select(tables.budget_journal)
                .where(
                    tables.budget_journal.c.tenant_id == tenant_id,
                    tables.budget_journal.c.attempt_id == attempt_id,
                )
                .order_by(tables.budget_journal.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
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
        if (
            call_kind not in {"model", "tool"}
            or any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens))
            or input_tokens + output_tokens <= 0
            or type(tenant_daily_token_limit) is not int
            or tenant_daily_token_limit <= 0
        ):
            raise BudgetLedgerError("BUDGET_RESERVATION_INVALID")
        if request_binding is not None and (
            call_kind != "model" or request_binding.output_limit != output_tokens
        ):
            raise BudgetLedgerError("BUDGET_REQUEST_BINDING_INVALID")
        try:
            with self._engine.begin() as connection:
                result = connection.execute(
                    text(
                        "SELECT cehub_ai.reserve_run_budget(:tenant,:run,:attempt,:kind,"
                        ":inputs,:outputs,:daily,CAST(:binding AS jsonb))"
                    ),
                    dict(
                        tenant=tenant_id,
                        run=run_id,
                        attempt=attempt_id,
                        kind=call_kind,
                        inputs=input_tokens,
                        outputs=output_tokens,
                        daily=tenant_daily_token_limit,
                        binding=json.dumps(request_binding.model_dump(mode="json"))
                        if request_binding is not None
                        else None,
                    ),
                ).scalar_one()
        except DBAPIError as error:
            diagnostic = getattr(error.orig, "diag", None)
            code = getattr(diagnostic, "message_primary", "")
            if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith("BUDGET_"):
                raise BudgetLedgerError(code) from error
            raise
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
        if action == "settle" and (
            type(charged_tokens) is not int
            or charged_tokens < 0
            or not reconciliation_ref
            or not reconciliation_ref.strip()
        ):
            raise BudgetLedgerError("BUDGET_SETTLEMENT_EVIDENCE_REQUIRED")
        if action != "settle" and any(
            v is not None
            for v in (charged_tokens, reconciliation_ref, provider_request_id, usage_evidence)
        ):
            raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
        with self._engine.begin() as connection:
            now = self._lock(connection, tenant_id)
            before = self._attempt(connection, tenant_id, attempt_id)
            if before is None:
                raise BudgetLedgerError("BUDGET_ATTEMPT_NOT_FOUND")
            binding = before["request_binding"]
            if binding is not None:
                if action == "settle" and (
                    usage_evidence is None
                    or usage_evidence.request_digest != binding["request_digest"]
                    or charged_tokens != usage_evidence.input_tokens + usage_evidence.output_tokens
                    or provider_request_id != usage_evidence.request_id
                    or reconciliation_ref != usage_evidence.evidence_ref
                ):
                    raise BudgetLedgerError("BUDGET_SETTLEMENT_EVIDENCE_CONFLICT")
                # Owner and lease-scoped Agent ports advance bound attempts through
                # the same database state machine and tenant lock.
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
                try:
                    result = connection.execute(
                        text(
                            "SELECT cehub_ai.transition_bound_model_budget("
                            ":tenant, :run, :attempt, :action, :body)"
                        ),
                        dict(
                            tenant=tenant_id,
                            run=before["run_id"],
                            attempt=attempt_id,
                            action=action,
                            body=body,
                        ),
                    ).scalar_one()
                except DBAPIError as error:
                    diagnostic = getattr(error.orig, "diag", None)
                    code = getattr(diagnostic, "message_primary", "")
                    if getattr(error.orig, "sqlstate", None) == "22023" and code.startswith(
                        "BUDGET_"
                    ):
                        raise BudgetLedgerError(code) from error
                    raise
                return _receipt(
                    result["row"], changed=result["changed"], dispatch=result["dispatch_granted"]
                )
            status = before["reservation_status"]
            row = dict(before)
            if action == "dispatch":
                if before["dispatched_at"] is not None:
                    return _receipt(before, changed=False)
                if status != "reserved":
                    raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
                self._require_run(connection, tenant_id, before["run_id"], active=True)
                lineage = self._link(connection, tenant_id, before["run_id"])
                if lineage is None or now >= lineage["absolute_deadline"]:
                    raise BudgetLedgerError("BUDGET_LINEAGE_EXPIRED")
                self._require_active(connection, tenant_id, before["run_id"])
                row["dispatched_at"] = now
            elif action == "unknown":
                if status == "unknown":
                    return _receipt(before, changed=False)
                if status != "reserved" or before["dispatched_at"] is None:
                    raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
                row["reservation_status"] = "unknown"
            elif action == "cancel":
                if status == "cancelled_before_dispatch":
                    return _receipt(before, changed=False)
                if status != "reserved" or before["dispatched_at"] is not None:
                    raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
                row.update(
                    reservation_status="cancelled_before_dispatch", held_tokens=0, charged_tokens=0
                )
            else:
                if usage_evidence is not None:
                    raise BudgetLedgerError("BUDGET_SETTLEMENT_EVIDENCE_CONFLICT")
                changes = {
                    "reservation_status": "settled",
                    "held_tokens": 0,
                    "charged_tokens": charged_tokens,
                    "reconciliation_ref": reconciliation_ref,
                    "provider_request_id": provider_request_id,
                    "usage_evidence": (
                        usage_evidence.model_dump(mode="json") if usage_evidence else None
                    ),
                }
                if status == "settled":
                    if any(before[key] != value for key, value in changes.items()):
                        raise BudgetLedgerError("BUDGET_SETTLEMENT_CONFLICT")
                    return _receipt(before, changed=False)
                if before["dispatched_at"] is None or status not in {"reserved", "unknown"}:
                    raise BudgetLedgerError("BUDGET_TRANSITION_INVALID")
                row.update(changes)
            row.update(id=uuid4(), revision=int(before["revision"]) + 1, created_at=now)
            receipt = _receipt(row, changed=True, dispatch=action == "dispatch")
            connection.execute(tables.budget_journal.insert(), row)
            return receipt


class ExistingRunBudgetLedger(BudgetLedger):
    """Application model admission reads creation-time bindings; it cannot allocate."""

    def open_lineage(self, *, tenant_id: UUID, run_id: UUID, profile: RunBudgetProfile) -> UUID:
        with self._engine.begin() as connection:
            self._require_run(connection, tenant_id, run_id)
            row = self._link(connection, tenant_id, run_id)
            if row is None:
                raise BudgetLedgerError("BUDGET_RUN_UNBOUND")
            if row["profile_digest"] != _profile_digest(profile):
                raise BudgetLedgerError("BUDGET_PROFILE_CONFLICT")
            return UUID(str(row["id"]))
