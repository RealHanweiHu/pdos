"""Human-feedback quality telemetry and deterministic output narrowing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.schema import tables

DEFAULT_MINIMUM_REVIEW_COUNT = 5
DEFAULT_ACCEPTANCE_THRESHOLD_BASIS_POINTS = 5_000


@dataclass(frozen=True)
class FindingQualityControl:
    agent_key: str
    finding_type: str
    status: str
    minimum_review_count: int
    acceptance_threshold_basis_points: int
    reviewed_count: int
    accepted_count: int
    applied_count: int
    acceptance_rate_basis_points: int | None
    narrowed_at: datetime | None
    narrowed_reason: str | None


@dataclass(frozen=True)
class FindingQualitySnapshot:
    reviewed_count: int
    accepted_count: int
    applied_count: int
    acceptance_rate_basis_points: int | None
    narrowed_output_count: int
    controls: tuple[FindingQualityControl, ...]


class FindingQualityService:
    def __init__(
        self,
        engine: Engine,
        *,
        minimum_review_count: int = DEFAULT_MINIMUM_REVIEW_COUNT,
        acceptance_threshold_basis_points: int = DEFAULT_ACCEPTANCE_THRESHOLD_BASIS_POINTS,
    ) -> None:
        if not 1 <= minimum_review_count <= 1_000:
            raise ValueError("minimum review count is outside the supported range")
        if not 0 <= acceptance_threshold_basis_points <= 10_000:
            raise ValueError("acceptance threshold is outside the supported range")
        self._engine = engine
        self._minimum_review_count = minimum_review_count
        self._acceptance_threshold_basis_points = acceptance_threshold_basis_points

    @staticmethod
    def _rate(*, accepted_count: int, reviewed_count: int) -> int | None:
        if reviewed_count == 0:
            return None
        return round(accepted_count * 10_000 / reviewed_count)

    @staticmethod
    def _quality_counts(
        connection: Connection,
        *,
        tenant_id: UUID,
    ) -> dict[tuple[str, str], tuple[int, int, int]]:
        rows = connection.execute(
            select(
                tables.findings.c.agent_key,
                tables.findings.c.finding_type,
                func.count().filter(tables.findings.c.reviewed_at.is_not(None)).label("reviewed"),
                func.count()
                .filter(tables.findings.c.status.in_(("accepted", "applied")))
                .label("accepted"),
                func.count().filter(tables.findings.c.status == "applied").label("applied"),
            )
            .where(tables.findings.c.tenant_id == tenant_id)
            .group_by(tables.findings.c.agent_key, tables.findings.c.finding_type)
        ).mappings()
        return {
            (str(row["agent_key"]), str(row["finding_type"])): (
                int(row["reviewed"]),
                int(row["accepted"]),
                int(row["applied"]),
            )
            for row in rows
        }

    def evaluate(
        self,
        *,
        tenant_id: UUID,
        now: datetime | None = None,
    ) -> FindingQualitySnapshot:
        evaluated_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            return self.evaluate_connection(
                connection,
                tenant_id=tenant_id,
                evaluated_at=evaluated_at,
            )

    def evaluate_connection(
        self,
        connection: Connection,
        *,
        tenant_id: UUID,
        evaluated_at: datetime,
    ) -> FindingQualitySnapshot:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"finding-quality:{tenant_id}"},
        )
        counts = self._quality_counts(connection, tenant_id=tenant_id)
        for (agent_key, finding_type), (reviewed, accepted, applied) in counts.items():
            current = (
                connection.execute(
                    select(tables.finding_quality_controls)
                    .where(
                        tables.finding_quality_controls.c.tenant_id == tenant_id,
                        tables.finding_quality_controls.c.agent_key == agent_key,
                        tables.finding_quality_controls.c.finding_type == finding_type,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            minimum_reviews = (
                int(current["minimum_review_count"])
                if current is not None
                else self._minimum_review_count
            )
            threshold = (
                int(current["acceptance_threshold_basis_points"])
                if current is not None
                else self._acceptance_threshold_basis_points
            )
            rate = self._rate(accepted_count=accepted, reviewed_count=reviewed)
            should_narrow = reviewed >= minimum_reviews and rate is not None and rate < threshold
            already_narrowed = current is not None and current["status"] == "narrowed"
            status = "narrowed" if should_narrow or already_narrowed else "active"
            narrowed_at = (
                current["narrowed_at"]
                if current is not None and already_narrowed
                else (evaluated_at if should_narrow else None)
            )
            narrowed_reason = (
                str(current["narrowed_reason"])
                if current is not None and already_narrowed
                else (
                    f"ACCEPTANCE_RATE_BELOW_THRESHOLD:rate={rate}:"
                    f"threshold={threshold}:reviewed={reviewed}"
                    if should_narrow
                    else None
                )
            )
            connection.execute(
                insert(tables.finding_quality_controls)
                .values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    agent_key=agent_key,
                    finding_type=finding_type,
                    status=status,
                    minimum_review_count=minimum_reviews,
                    acceptance_threshold_basis_points=threshold,
                    reviewed_count=reviewed,
                    accepted_count=accepted,
                    applied_count=applied,
                    last_evaluated_at=evaluated_at,
                    narrowed_at=narrowed_at,
                    narrowed_reason=narrowed_reason,
                    updated_at=evaluated_at,
                )
                .on_conflict_do_update(
                    constraint="uq_finding_quality_controls_tenant_agent_type",
                    set_={
                        "status": status,
                        "reviewed_count": reviewed,
                        "accepted_count": accepted,
                        "applied_count": applied,
                        "last_evaluated_at": evaluated_at,
                        "narrowed_at": narrowed_at,
                        "narrowed_reason": narrowed_reason,
                        "updated_at": evaluated_at,
                    },
                )
            )
        controls = list(
            connection.execute(
                select(tables.finding_quality_controls)
                .where(tables.finding_quality_controls.c.tenant_id == tenant_id)
                .order_by(
                    tables.finding_quality_controls.c.agent_key,
                    tables.finding_quality_controls.c.finding_type,
                )
            ).mappings()
        )

        return self._snapshot(counts=counts, controls=controls)

    def snapshot(self, *, tenant_id: UUID) -> FindingQualitySnapshot:
        with self._engine.connect() as connection:
            counts = self._quality_counts(connection, tenant_id=tenant_id)
            controls = list(
                connection.execute(
                    select(tables.finding_quality_controls)
                    .where(tables.finding_quality_controls.c.tenant_id == tenant_id)
                    .order_by(
                        tables.finding_quality_controls.c.agent_key,
                        tables.finding_quality_controls.c.finding_type,
                    )
                ).mappings()
            )
        return self._snapshot(counts=counts, controls=controls)

    def _snapshot(
        self,
        *,
        counts: dict[tuple[str, str], tuple[int, int, int]],
        controls: list[RowMapping],
    ) -> FindingQualitySnapshot:
        controls_by_type = {
            (str(row["agent_key"]), str(row["finding_type"])): row for row in controls
        }
        control_records = tuple(
            FindingQualityControl(
                agent_key=agent_key,
                finding_type=finding_type,
                status=(str(row["status"]) if row is not None else "active"),
                minimum_review_count=(
                    int(row["minimum_review_count"])
                    if row is not None
                    else self._minimum_review_count
                ),
                acceptance_threshold_basis_points=(
                    int(row["acceptance_threshold_basis_points"])
                    if row is not None
                    else self._acceptance_threshold_basis_points
                ),
                reviewed_count=count[0],
                accepted_count=count[1],
                applied_count=count[2],
                acceptance_rate_basis_points=self._rate(
                    accepted_count=count[1],
                    reviewed_count=count[0],
                ),
                narrowed_at=(row["narrowed_at"] if row is not None else None),
                narrowed_reason=(row["narrowed_reason"] if row is not None else None),
            )
            for (agent_key, finding_type), count in sorted(counts.items())
            for row in (controls_by_type.get((agent_key, finding_type)),)
        )
        reviewed_count = sum(item.reviewed_count for item in control_records)
        accepted_count = sum(item.accepted_count for item in control_records)
        return FindingQualitySnapshot(
            reviewed_count=reviewed_count,
            accepted_count=accepted_count,
            applied_count=sum(item.applied_count for item in control_records),
            acceptance_rate_basis_points=self._rate(
                accepted_count=accepted_count,
                reviewed_count=reviewed_count,
            ),
            narrowed_output_count=sum(item.status == "narrowed" for item in control_records),
            controls=control_records,
        )

    def is_output_allowed(
        self,
        *,
        tenant_id: UUID,
        agent_key: str,
        finding_type: str,
    ) -> bool:
        with self._engine.begin() as connection:
            return self.is_output_allowed_connection(
                connection,
                tenant_id=tenant_id,
                agent_key=agent_key,
                finding_type=finding_type,
            )

    @staticmethod
    def is_output_allowed_connection(
        connection: Connection,
        *,
        tenant_id: UUID,
        agent_key: str,
        finding_type: str,
    ) -> bool:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"finding-quality:{tenant_id}"},
        )
        status = connection.execute(
            select(tables.finding_quality_controls.c.status).where(
                tables.finding_quality_controls.c.tenant_id == tenant_id,
                tables.finding_quality_controls.c.agent_key == agent_key,
                tables.finding_quality_controls.c.finding_type == finding_type,
            )
        ).scalar_one_or_none()
        return status != "narrowed"
