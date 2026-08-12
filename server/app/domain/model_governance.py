"""Tenant-bound model selection, budget accounting, and audited governance writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, func, select, update

from app.ai.model_catalog import EligibleModel, GoldenQualification, ModelCatalog, ProviderName
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class ModelNotEligibleError(ValueError):
    """Raised when a tenant attempts to select a model outside the qualified pool."""


@dataclass(frozen=True)
class ModelSelection:
    provider: ProviderName
    model: str
    available: bool


@dataclass(frozen=True)
class BudgetSnapshot:
    daily_token_budget: int
    used_tokens_today: int
    remaining_tokens_today: int
    exhausted: bool


@dataclass(frozen=True)
class ModelGovernanceSnapshot:
    eligible_models: list[EligibleModel]
    selection: ModelSelection | None
    budget: BudgetSnapshot


@dataclass(frozen=True)
class ModelSettingsUpdate:
    provider: ProviderName
    model: str
    daily_token_budget: int


class ModelGovernanceService:
    def __init__(
        self,
        engine: Engine,
        *,
        catalog: ModelCatalog,
        qualifications: list[GoldenQualification],
        default_daily_token_budget: int,
    ) -> None:
        if not 1 <= default_daily_token_budget <= 1_000_000_000:
            raise ValueError("default daily token budget is invalid")
        self._engine = engine
        self._catalog = catalog
        self._qualifications = qualifications
        self._default_daily_token_budget = default_daily_token_budget

    def get(
        self,
        *,
        tenant_id: UUID,
        now: datetime | None = None,
    ) -> ModelGovernanceSnapshot:
        current_time = (now or datetime.now(UTC)).astimezone(UTC)
        eligible = self._catalog.eligible_models(self._qualifications)
        eligible_identities = {(item.provider, item.model) for item in eligible}
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(tables.tenant_model_settings).where(
                        tables.tenant_model_settings.c.tenant_id == tenant_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            used_tokens = self._used_tokens_today(
                connection,
                tenant_id=tenant_id,
                now=current_time,
            )

        if row is None:
            default_candidate = next(
                (item for item in eligible if item.provider is ProviderName.MINIMAX),
                None,
            )
            selection = (
                ModelSelection(
                    provider=default_candidate.provider,
                    model=default_candidate.model,
                    available=True,
                )
                if default_candidate is not None
                else None
            )
            budget = self._default_daily_token_budget
        else:
            provider = ProviderName(row["provider"])
            model = str(row["model"])
            selection = ModelSelection(
                provider=provider,
                model=model,
                available=(provider, model) in eligible_identities,
            )
            budget = int(row["daily_token_budget"])

        remaining = max(0, budget - used_tokens)
        return ModelGovernanceSnapshot(
            eligible_models=eligible,
            selection=selection,
            budget=BudgetSnapshot(
                daily_token_budget=budget,
                used_tokens_today=used_tokens,
                remaining_tokens_today=remaining,
                exhausted=used_tokens >= budget,
            ),
        )

    def update(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        changes: ModelSettingsUpdate,
        now: datetime | None = None,
    ) -> ModelGovernanceSnapshot:
        eligible = {
            (item.provider, item.model)
            for item in self._catalog.eligible_models(self._qualifications)
        }
        if (changes.provider, changes.model) not in eligible:
            raise ModelNotEligibleError

        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(tables.tenant_model_settings)
                    .where(tables.tenant_model_settings.c.tenant_id == tenant_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            settings_id = existing["id"] if existing is not None else uuid4()
            after_snapshot = {
                "provider": changes.provider.value,
                "model": changes.model,
                "daily_token_budget": changes.daily_token_budget,
            }
            before_snapshot: dict[str, object]
            if existing is None:
                connection.execute(
                    tables.tenant_model_settings.insert(),
                    {
                        "id": settings_id,
                        "tenant_id": tenant_id,
                        **after_snapshot,
                        "updated_by_user_id": actor_user_id,
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    },
                )
                before_snapshot = {"configured": False}
            else:
                connection.execute(
                    update(tables.tenant_model_settings)
                    .where(
                        tables.tenant_model_settings.c.tenant_id == tenant_id,
                        tables.tenant_model_settings.c.id == settings_id,
                    )
                    .values(
                        **after_snapshot,
                        updated_by_user_id=actor_user_id,
                        updated_at=occurred_at,
                    )
                )
                before_snapshot = self._settings_snapshot(existing)

            EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
            ).record(
                EventDraft(
                    event_id=f"tenant-model-settings:{settings_id}:updated:{uuid4()}",
                    event_type="TENANT_MODEL_SETTINGS_UPDATED",
                    source="model_governance_service",
                    entity_id=settings_id,
                    payload=after_snapshot,
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="tenant_model_settings.update",
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                    context={"qualification_gate": "credential_and_golden_passed"},
                ),
            )
        return self.get(tenant_id=tenant_id, now=occurred_at)

    @staticmethod
    def _settings_snapshot(row: RowMapping) -> dict[str, object]:
        return {
            "provider": row["provider"],
            "model": row["model"],
            "daily_token_budget": row["daily_token_budget"],
        }

    @staticmethod
    def _used_tokens_today(connection: Connection, *, tenant_id: UUID, now: datetime) -> int:
        day_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        value = connection.execute(
            select(func.coalesce(func.sum(tables.model_invocations.c.total_tokens), 0)).where(
                tables.model_invocations.c.tenant_id == tenant_id,
                tables.model_invocations.c.created_at >= day_start,
                tables.model_invocations.c.created_at < day_end,
            )
        ).scalar_one()
        return int(value)
