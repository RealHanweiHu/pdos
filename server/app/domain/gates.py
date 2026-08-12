"""Versioned NPD Gate policy and deterministic signoff readiness rules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, or_, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

from app.auth.roles import Role
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

GateSlot = Literal["product", "engineering", "quality"]
GateRequirement = Literal["required", "conditional", "not_applicable"]
GateSignoffStatus = Literal[
    "pending",
    "approved",
    "conditional",
    "rejected",
    "not_applicable",
]

NPD_GATE_POLICY_VERSION = "npd-gate-v1"
NPD_GATE_REQUIREMENTS: Mapping[str, Mapping[GateSlot, GateRequirement]] = MappingProxyType(
    {
        "concept": MappingProxyType(
            {"product": "required", "engineering": "required", "quality": "conditional"}
        ),
        "planning": MappingProxyType(
            {"product": "required", "engineering": "required", "quality": "required"}
        ),
        "design": MappingProxyType(
            {"product": "required", "engineering": "required", "quality": "required"}
        ),
        "evt": MappingProxyType(
            {"product": "conditional", "engineering": "required", "quality": "required"}
        ),
        "dvt": MappingProxyType(
            {"product": "required", "engineering": "required", "quality": "required"}
        ),
        "pvt": MappingProxyType(
            {"product": "required", "engineering": "required", "quality": "required"}
        ),
        "mp": MappingProxyType(
            {"product": "required", "engineering": "conditional", "quality": "required"}
        ),
    }
)

_REQUIREMENT_RANK: Mapping[GateRequirement, int] = MappingProxyType(
    {"not_applicable": 0, "conditional": 1, "required": 2}
)
_ROLE_SLOTS: Mapping[Role, frozenset[GateSlot]] = MappingProxyType(
    {
        Role.OWNER: frozenset({"product", "engineering", "quality"}),
        Role.ADMIN: frozenset({"product", "engineering", "quality"}),
        Role.PROJECT_MANAGER: frozenset({"product"}),
        Role.ENGINEER: frozenset({"engineering"}),
        Role.QUALITY: frozenset({"quality"}),
        Role.SUPPLIER: frozenset(),
        Role.CUSTOMER: frozenset(),
    }
)


@dataclass(frozen=True)
class GateSignoffReadiness:
    ready: bool
    blockers: tuple[str, ...]


def may_sign_gate_slot(role: Role, slot: GateSlot) -> bool:
    return slot in _ROLE_SLOTS[role]


def promote_requirement(
    current: GateRequirement,
    requested: GateRequirement,
) -> GateRequirement | None:
    if _REQUIREMENT_RANK[requested] <= _REQUIREMENT_RANK[current]:
        return None
    return requested


def gate_signoffs_ready(
    requirements: Mapping[GateSlot, GateRequirement],
    statuses: Mapping[GateSlot, GateSignoffStatus],
) -> GateSignoffReadiness:
    blockers: list[str] = []
    for slot in ("product", "engineering", "quality"):
        requirement = requirements[slot]
        status = statuses.get(slot, "pending")
        accepted = (
            status == "not_applicable"
            if requirement == "not_applicable"
            else status in {"approved", "conditional"}
            if requirement == "conditional"
            else status == "approved"
        )
        if not accepted:
            blockers.append(f"signoff:{slot}")
    return GateSignoffReadiness(ready=not blockers, blockers=tuple(blockers))


class GateNotFoundError(LookupError):
    """Raised when a Gate is outside the tenant-bound Project."""


class GateNotCurrentError(ValueError):
    """Raised when a current/future-only action targets another Stage."""


class GateInvalidStateError(ValueError):
    """Raised when the frozen four-state graph rejects an operation."""


class GateRoundNotOpenError(ValueError):
    """Raised when a signature or decision targets a historical round."""


class GateSigningDeniedError(PermissionError):
    """Raised when a role attempts to sign another professional slot."""


class GateRequirementPromotionError(ValueError):
    """Raised when a project addition would repeat or reduce policy."""


class GateGrandfatherNotAllowedError(ValueError):
    """Raised when an exemption targets a current, future, or unapproved Gate."""


class GateGrandfatherPermissionError(PermissionError):
    """Raised when a non-governance role attempts a grandfather decision."""


class GateNotReadyError(ValueError):
    def __init__(self, blockers: tuple[str, ...]) -> None:
        self.blockers = blockers
        super().__init__("Gate readiness blockers remain")


class GateConflictError(ValueError):
    """Raised when an idempotent governance key already exists."""


@dataclass(frozen=True)
class GateStageRecord:
    id: UUID
    code: str
    name: str
    sequence: int


@dataclass(frozen=True)
class GateSignoffRecord:
    id: UUID
    slot: GateSlot
    requirement: GateRequirement
    status: GateSignoffStatus
    signed_by_user_id: UUID | None
    signer_role: str | None
    signed_at: datetime | None
    note: str | None


@dataclass(frozen=True)
class GateRoundRecord:
    id: UUID
    round_number: int
    status: str
    policy_version: str
    requirements: Mapping[GateSlot, GateRequirement]
    risk_snapshot: dict[str, object]
    readiness_snapshot: dict[str, object] | None
    opened_by_user_id: UUID
    opened_at: datetime
    superseded_at: datetime | None
    supersede_reason: str | None
    completed_at: datetime | None
    signoffs: tuple[GateSignoffRecord, ...]


@dataclass(frozen=True)
class GateReadinessRecord:
    ready: bool
    blocker_keys: tuple[str, ...]
    blockers: tuple[dict[str, str], ...]
    evaluated_at: datetime


@dataclass(frozen=True)
class GateAdditionRecord:
    id: UUID
    slot: GateSlot
    requirement: GateRequirement
    reason: str
    added_by_user_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class GateGrandfatherRecord:
    id: UUID
    requirement_key: str
    policy_version: str
    reason: str
    approved_by_user_id: UUID
    created_at: datetime


@dataclass(frozen=True)
class GateRecord:
    id: UUID
    project_id: UUID
    stage: GateStageRecord
    code: str
    name: str
    status: str
    review_due_at: datetime | None
    decided_at: datetime | None
    decided_by_user_id: UUID | None
    is_current: bool
    round: GateRoundRecord | None
    readiness: GateReadinessRecord
    additions: tuple[GateAdditionRecord, ...]
    grandfather_exemptions: tuple[GateGrandfatherRecord, ...]


def _requirements(value: object) -> dict[GateSlot, GateRequirement]:
    if not isinstance(value, Mapping):
        raise GateInvalidStateError
    return {
        cast(GateSlot, slot): cast(GateRequirement, requirement)
        for slot, requirement in value.items()
    }


def _gate_snapshot(row: RowMapping, *, status: str | None = None) -> dict[str, object]:
    return {
        "project_id": str(row["project_id"]),
        "stage_id": str(row["stage_id"]),
        "code": row["code"],
        "name": row["name"],
        "status": status or row["status"],
        "decided_at": (
            row["decided_at"].isoformat() if row.get("decided_at") is not None else None
        ),
        "decided_by_user_id": (
            str(row["decided_by_user_id"]) if row.get("decided_by_user_id") is not None else None
        ),
    }


def _audit_only(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    gate_id: UUID,
    action: str,
    before_snapshot: dict[str, object] | None,
    after_snapshot: dict[str, object] | None,
    context: dict[str, object] | None = None,
    occurred_at: datetime,
) -> None:
    values: dict[str, object] = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "actor_user_id": actor_user_id,
        "event_id": f"gate:{gate_id}:{action}:{uuid4()}",
        "action": action,
        "entity": "gate",
        "entity_id": gate_id,
        "context": context or {},
        "timestamp": occurred_at,
    }
    if before_snapshot is not None:
        values["before_snapshot"] = before_snapshot
    if after_snapshot is not None:
        values["after_snapshot"] = after_snapshot
    connection.execute(
        tables.audit_log.insert(),
        values,
    )


class GateService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _gate_statement() -> Any:
        return (
            select(
                tables.gates,
                tables.stages.c.code.label("stage_code"),
                tables.stages.c.name.label("stage_name"),
                tables.stages.c.sequence.label("stage_sequence"),
                tables.projects.c.current_stage_id,
            )
            .join(
                tables.stages,
                (tables.stages.c.tenant_id == tables.gates.c.tenant_id)
                & (tables.stages.c.id == tables.gates.c.stage_id),
            )
            .join(
                tables.projects,
                (tables.projects.c.tenant_id == tables.gates.c.tenant_id)
                & (tables.projects.c.id == tables.gates.c.project_id),
            )
        )

    @classmethod
    def _gate_row(
        cls,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        for_update: bool = False,
    ) -> RowMapping:
        statement = cls._gate_statement().where(
            tables.gates.c.tenant_id == tenant_id,
            tables.gates.c.project_id == project_id,
            tables.gates.c.id == gate_id,
        )
        if for_update:
            statement = statement.with_for_update(of=tables.gates)
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise GateNotFoundError
        return row

    @staticmethod
    def _lock_project(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
    ) -> RowMapping:
        row = (
            connection.execute(
                select(
                    tables.projects.c.id,
                    tables.projects.c.current_stage_id,
                    tables.projects.c.status,
                )
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id == project_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise GateNotFoundError
        return row

    @staticmethod
    def _requirements_for_gate(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        stage_code: str,
    ) -> dict[GateSlot, GateRequirement]:
        base = NPD_GATE_REQUIREMENTS.get(stage_code)
        if base is None:
            raise GateInvalidStateError
        requirements = dict(base)
        additions = connection.execute(
            select(
                tables.gate_signoff_additions.c.slot,
                tables.gate_signoff_additions.c.requirement,
            ).where(
                tables.gate_signoff_additions.c.tenant_id == tenant_id,
                tables.gate_signoff_additions.c.project_id == project_id,
                tables.gate_signoff_additions.c.gate_id == gate_id,
                tables.gate_signoff_additions.c.active.is_(True),
            )
        ).mappings()
        for addition in additions:
            requirements[cast(GateSlot, addition["slot"])] = cast(
                GateRequirement, addition["requirement"]
            )
        return requirements

    @staticmethod
    def _round(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        open_only: bool = False,
        for_update: bool = False,
    ) -> RowMapping | None:
        statement = (
            select(tables.gate_signoff_rounds)
            .where(
                tables.gate_signoff_rounds.c.tenant_id == tenant_id,
                tables.gate_signoff_rounds.c.project_id == project_id,
                tables.gate_signoff_rounds.c.gate_id == gate_id,
            )
            .order_by(tables.gate_signoff_rounds.c.round_number.desc())
            .limit(1)
        )
        if open_only:
            statement = statement.where(tables.gate_signoff_rounds.c.status == "open")
        if for_update:
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().one_or_none()

    @staticmethod
    def _signoff_rows(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        round_id: UUID,
        for_update: bool = False,
    ) -> tuple[RowMapping, ...]:
        statement = (
            select(tables.gate_signoffs)
            .where(
                tables.gate_signoffs.c.tenant_id == tenant_id,
                tables.gate_signoffs.c.project_id == project_id,
                tables.gate_signoffs.c.gate_id == gate_id,
                tables.gate_signoffs.c.round_id == round_id,
            )
            .order_by(tables.gate_signoffs.c.slot)
        )
        if for_update:
            statement = statement.with_for_update()
        return tuple(connection.execute(statement).mappings())

    @staticmethod
    def _signoff_record(row: RowMapping) -> GateSignoffRecord:
        return GateSignoffRecord(
            id=row["id"],
            slot=cast(GateSlot, row["slot"]),
            requirement=cast(GateRequirement, row["requirement"]),
            status=cast(GateSignoffStatus, row["status"]),
            signed_by_user_id=row["signed_by_user_id"],
            signer_role=row["signer_role"],
            signed_at=row["signed_at"],
            note=row["note"],
        )

    @staticmethod
    def _live_non_signoff_blockers(
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        stage_id: UUID,
        for_update: bool = False,
    ) -> list[dict[str, str]]:
        task_statement = select(tables.tasks.c.id, tables.tasks.c.title).where(
            tables.tasks.c.tenant_id == tenant_id,
            tables.tasks.c.project_id == project_id,
            tables.tasks.c.stage_id == stage_id,
            tables.tasks.c.status == "blocked",
        )
        issue_statement = select(tables.issues.c.id, tables.issues.c.title).where(
            tables.issues.c.tenant_id == tenant_id,
            tables.issues.c.project_id == project_id,
            or_(tables.issues.c.stage_id == stage_id, tables.issues.c.stage_id.is_(None)),
            tables.issues.c.severity == "critical",
            tables.issues.c.status != "closed",
        )
        risk_statement = select(tables.risks.c.id, tables.risks.c.title).where(
            tables.risks.c.tenant_id == tenant_id,
            tables.risks.c.project_id == project_id,
            tables.risks.c.status != "closed",
            tables.risks.c.likelihood * tables.risks.c.impact >= 16,
        )
        if for_update:
            task_statement = task_statement.with_for_update()
            issue_statement = issue_statement.with_for_update()
            risk_statement = risk_statement.with_for_update()
        blockers: list[dict[str, str]] = []
        for kind, statement in (
            ("task", task_statement),
            ("issue", issue_statement),
            ("risk", risk_statement),
        ):
            blockers.extend(
                {"key": f"{kind}:{row.id}", "kind": kind, "label": row.title}
                for row in connection.execute(statement)
            )
        stage_code = connection.execute(
            select(tables.stages.c.code).where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.id == stage_id,
            )
        ).scalar_one_or_none()
        if stage_code in {"evt", "dvt", "pvt"}:
            build_statement = select(
                tables.build_batches.c.id,
                tables.build_batches.c.code,
                tables.build_batches.c.status,
            ).where(
                tables.build_batches.c.tenant_id == tenant_id,
                tables.build_batches.c.project_id == project_id,
                tables.build_batches.c.phase == stage_code,
            )
            test_case_statement = (
                select(tables.test_cases.c.id, tables.test_cases.c.title)
                .join(tables.test_plans, tables.test_plans.c.id == tables.test_cases.c.plan_id)
                .where(
                    tables.test_cases.c.tenant_id == tenant_id,
                    tables.test_cases.c.project_id == project_id,
                    tables.test_plans.c.phase == stage_code,
                    tables.test_cases.c.status.in_(("failed", "blocked")),
                )
            )
            signoff_statement = select(
                tables.sample_signoffs.c.id,
                tables.sample_signoffs.c.title,
                tables.sample_signoffs.c.status,
            ).where(
                tables.sample_signoffs.c.tenant_id == tenant_id,
                tables.sample_signoffs.c.project_id == project_id,
                tables.sample_signoffs.c.phase == stage_code,
                tables.sample_signoffs.c.status.in_(("pending", "rejected")),
            )
            report_statement = (
                select(tables.test_reports.c.id)
                .join(tables.test_plans, tables.test_plans.c.id == tables.test_reports.c.plan_id)
                .where(
                    tables.test_reports.c.tenant_id == tenant_id,
                    tables.test_reports.c.project_id == project_id,
                    tables.test_plans.c.phase == stage_code,
                    tables.test_reports.c.review_status == "approved",
                    tables.test_reports.c.result.in_(("pass", "conditional")),
                )
            )
            if for_update:
                build_statement = build_statement.with_for_update()
                test_case_statement = test_case_statement.with_for_update(of=tables.test_cases)
                signoff_statement = signoff_statement.with_for_update()
                report_statement = report_statement.with_for_update(of=tables.test_reports)
            build_rows = tuple(connection.execute(build_statement))
            completed_build_ids = tuple(row.id for row in build_rows if row.status == "completed")
            if not completed_build_ids:
                blockers.append(
                    {
                        "key": f"build:{stage_code}:completed_missing",
                        "kind": "build",
                        "label": f"{stage_code.upper()} completed Build is missing",
                    }
                )
            else:
                sample_statement = select(tables.samples.c.id).where(
                    tables.samples.c.tenant_id == tenant_id,
                    tables.samples.c.project_id == project_id,
                    tables.samples.c.build_batch_id.in_(completed_build_ids),
                    tables.samples.c.status != "scrapped",
                )
                if for_update:
                    sample_statement = sample_statement.with_for_update()
                if connection.execute(sample_statement.limit(1)).first() is None:
                    blockers.append(
                        {
                            "key": f"sample:{stage_code}:missing",
                            "kind": "sample",
                            "label": f"{stage_code.upper()} Sample is missing",
                        }
                    )
            for row in connection.execute(test_case_statement):
                blockers.append(
                    {
                        "key": f"test_case:{row.id}",
                        "kind": "test_case",
                        "label": row.title,
                    }
                )
            if connection.execute(report_statement.limit(1)).first() is None:
                blockers.append(
                    {
                        "key": f"test_report:{stage_code}:approved_missing",
                        "kind": "test_report",
                        "label": (
                            f"{stage_code.upper()} approved pass/conditional report is missing"
                        ),
                    }
                )
            for row in connection.execute(signoff_statement):
                blockers.append(
                    {
                        "key": f"sample_signoff:{row.id}",
                        "kind": "sample_signoff",
                        "label": row.title,
                    }
                )
            if stage_code == "pvt":
                certification_statement = select(
                    tables.certifications.c.id,
                    tables.certifications.c.certificate_type,
                    tables.certifications.c.status,
                    tables.certifications.c.valid_from,
                    tables.certifications.c.valid_until,
                ).where(
                    tables.certifications.c.tenant_id == tenant_id,
                    tables.certifications.c.project_id == project_id,
                    tables.certifications.c.is_required.is_(True),
                )
                if for_update:
                    certification_statement = certification_statement.with_for_update()
                for row in connection.execute(certification_statement):
                    if (
                        row.status != "valid"
                        or row.valid_from is not None
                        and row.valid_from > date.today()
                        or row.valid_until is None
                        or row.valid_until < date.today()
                    ):
                        blockers.append(
                            {
                                "key": f"certification:{row.id}",
                                "kind": "certification",
                                "label": (
                                    f"Required {row.certificate_type} certification is not valid"
                                ),
                            }
                        )
        return blockers

    @classmethod
    def _readiness(
        cls,
        connection: Connection,
        *,
        tenant_id: UUID,
        project_id: UUID,
        stage_id: UUID,
        requirements: Mapping[GateSlot, GateRequirement],
        signoff_rows: tuple[RowMapping, ...],
        for_update: bool = False,
        evaluated_at: datetime | None = None,
    ) -> GateReadinessRecord:
        statuses = {
            cast(GateSlot, row["slot"]): cast(GateSignoffStatus, row["status"])
            for row in signoff_rows
        }
        signoff = gate_signoffs_ready(requirements, statuses)
        blockers = [
            {
                "key": key,
                "kind": "signoff",
                "label": f"{key.split(':', 1)[1]} signoff is incomplete",
            }
            for key in signoff.blockers
        ]
        blockers.extend(
            cls._live_non_signoff_blockers(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                stage_id=stage_id,
                for_update=for_update,
            )
        )
        return GateReadinessRecord(
            ready=not blockers,
            blocker_keys=tuple(blocker["key"] for blocker in blockers),
            blockers=tuple(blockers),
            evaluated_at=evaluated_at or datetime.now(UTC),
        )

    @staticmethod
    def _readiness_dict(readiness: GateReadinessRecord) -> dict[str, object]:
        return {
            "ready": readiness.ready,
            "blocker_keys": list(readiness.blocker_keys),
            "blockers": list(readiness.blockers),
            "evaluated_at": readiness.evaluated_at.isoformat(),
        }

    @staticmethod
    def _readiness_from_dict(value: Mapping[str, object]) -> GateReadinessRecord:
        evaluated = value.get("evaluated_at")
        if not isinstance(evaluated, str):
            raise GateInvalidStateError
        raw_blockers = value.get("blockers", [])
        if not isinstance(raw_blockers, list):
            raise GateInvalidStateError
        blockers = tuple(
            {str(key): str(nested) for key, nested in blocker.items()}
            for blocker in raw_blockers
            if isinstance(blocker, Mapping)
        )
        raw_blocker_keys = value.get("blocker_keys", [])
        if not isinstance(raw_blocker_keys, list):
            raise GateInvalidStateError
        return GateReadinessRecord(
            ready=value.get("ready") is True,
            blocker_keys=tuple(str(key) for key in raw_blocker_keys),
            blockers=blockers,
            evaluated_at=datetime.fromisoformat(evaluated),
        )

    @classmethod
    def _record_from_row(
        cls,
        connection: Connection,
        *,
        tenant_id: UUID,
        row: RowMapping,
    ) -> GateRecord:
        project_id = cast(UUID, row["project_id"])
        gate_id = cast(UUID, row["id"])
        round_row = cls._round(
            connection,
            tenant_id=tenant_id,
            project_id=project_id,
            gate_id=gate_id,
        )
        signoff_rows: tuple[RowMapping, ...] = ()
        round_record: GateRoundRecord | None = None
        if round_row is not None:
            signoff_rows = cls._signoff_rows(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                round_id=round_row["id"],
            )
            round_record = GateRoundRecord(
                id=round_row["id"],
                round_number=round_row["round_number"],
                status=round_row["status"],
                policy_version=round_row["policy_version"],
                requirements=_requirements(round_row["requirements"]),
                risk_snapshot=dict(round_row["risk_snapshot"]),
                readiness_snapshot=(
                    dict(round_row["readiness_snapshot"])
                    if round_row["readiness_snapshot"] is not None
                    else None
                ),
                opened_by_user_id=round_row["opened_by_user_id"],
                opened_at=round_row["opened_at"],
                superseded_at=round_row["superseded_at"],
                supersede_reason=round_row["supersede_reason"],
                completed_at=round_row["completed_at"],
                signoffs=tuple(cls._signoff_record(item) for item in signoff_rows),
            )
        if round_record is not None and round_record.readiness_snapshot is not None:
            readiness = cls._readiness_from_dict(round_record.readiness_snapshot)
        elif round_record is not None and round_record.status == "open":
            readiness = cls._readiness(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                stage_id=row["stage_id"],
                requirements=round_record.requirements,
                signoff_rows=signoff_rows,
            )
        else:
            now = datetime.now(UTC)
            live_blockers = cls._live_non_signoff_blockers(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                stage_id=row["stage_id"],
            )
            round_blocker = {
                "key": "round:not_open",
                "kind": "round",
                "label": "Gate signoff round is not open",
            }
            all_blockers = (round_blocker, *live_blockers)
            readiness = GateReadinessRecord(
                ready=False,
                blocker_keys=tuple(blocker["key"] for blocker in all_blockers),
                blockers=all_blockers,
                evaluated_at=now,
            )

        addition_rows = connection.execute(
            select(tables.gate_signoff_additions)
            .where(
                tables.gate_signoff_additions.c.tenant_id == tenant_id,
                tables.gate_signoff_additions.c.project_id == project_id,
                tables.gate_signoff_additions.c.gate_id == gate_id,
                tables.gate_signoff_additions.c.active.is_(True),
            )
            .order_by(tables.gate_signoff_additions.c.created_at)
        ).mappings()
        grandfather_rows = connection.execute(
            select(tables.gate_grandfather_exemptions)
            .where(
                tables.gate_grandfather_exemptions.c.tenant_id == tenant_id,
                tables.gate_grandfather_exemptions.c.project_id == project_id,
                tables.gate_grandfather_exemptions.c.gate_id == gate_id,
            )
            .order_by(tables.gate_grandfather_exemptions.c.created_at)
        ).mappings()
        return GateRecord(
            id=gate_id,
            project_id=project_id,
            stage=GateStageRecord(
                id=row["stage_id"],
                code=row["stage_code"],
                name=row["stage_name"],
                sequence=row["stage_sequence"],
            ),
            code=row["code"],
            name=row["name"],
            status=row["status"],
            review_due_at=row["review_due_at"],
            decided_at=row["decided_at"],
            decided_by_user_id=row["decided_by_user_id"],
            is_current=row["stage_id"] == row["current_stage_id"],
            round=round_record,
            readiness=readiness,
            additions=tuple(
                GateAdditionRecord(
                    id=item["id"],
                    slot=cast(GateSlot, item["slot"]),
                    requirement=cast(GateRequirement, item["requirement"]),
                    reason=item["reason"],
                    added_by_user_id=item["added_by_user_id"],
                    created_at=item["created_at"],
                )
                for item in addition_rows
            ),
            grandfather_exemptions=tuple(
                GateGrandfatherRecord(
                    id=item["id"],
                    requirement_key=item["requirement_key"],
                    policy_version=item["policy_version"],
                    reason=item["reason"],
                    approved_by_user_id=item["approved_by_user_id"],
                    created_at=item["created_at"],
                )
                for item in grandfather_rows
            ),
        )

    def list(self, *, tenant_id: UUID, project_id: UUID) -> list[GateRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                self._gate_statement()
                .where(
                    tables.gates.c.tenant_id == tenant_id,
                    tables.gates.c.project_id == project_id,
                )
                .order_by(tables.stages.c.sequence)
            ).mappings()
            return [self._record_from_row(connection, tenant_id=tenant_id, row=row) for row in rows]

    def open_round(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        actor_user_id: UUID,
    ) -> GateRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            project = self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            gate = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                for_update=True,
            )
            if project["current_stage_id"] != gate["stage_id"]:
                raise GateNotCurrentError
            if gate["status"] == "approved":
                raise GateInvalidStateError
            existing = self._round(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                open_only=True,
                for_update=True,
            )
            if existing is not None:
                return self._record_from_row(connection, tenant_id=tenant_id, row=gate)
            latest_number = connection.execute(
                select(func.coalesce(func.max(tables.gate_signoff_rounds.c.round_number), 0)).where(
                    tables.gate_signoff_rounds.c.tenant_id == tenant_id,
                    tables.gate_signoff_rounds.c.project_id == project_id,
                    tables.gate_signoff_rounds.c.gate_id == gate_id,
                )
            ).scalar_one()
            requirements = self._requirements_for_gate(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                stage_code=gate["stage_code"],
            )
            risk_blockers = self._live_non_signoff_blockers(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                stage_id=gate["stage_id"],
                for_update=True,
            )
            round_id = uuid4()
            connection.execute(
                tables.gate_signoff_rounds.insert(),
                {
                    "id": round_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "gate_id": gate_id,
                    "round_number": latest_number + 1,
                    "status": "open",
                    "policy_version": NPD_GATE_POLICY_VERSION,
                    "requirements": requirements,
                    "risk_snapshot": {"blockers": risk_blockers},
                    "opened_by_user_id": actor_user_id,
                    "opened_at": occurred_at,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            connection.execute(
                tables.gate_signoffs.insert(),
                [
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "gate_id": gate_id,
                        "round_id": round_id,
                        "slot": slot,
                        "requirement": requirement,
                        "status": (
                            "not_applicable" if requirement == "not_applicable" else "pending"
                        ),
                        "created_at": occurred_at,
                        "updated_at": occurred_at,
                    }
                    for slot, requirement in requirements.items()
                ],
            )
            connection.execute(
                tables.gates.update()
                .where(
                    tables.gates.c.tenant_id == tenant_id,
                    tables.gates.c.id == gate_id,
                )
                .values(
                    status="reviewing",
                    decided_at=None,
                    decided_by_user_id=None,
                    updated_at=occurred_at,
                )
            )
            after = dict(_gate_snapshot(gate, status="reviewing"))
            _audit_only(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                gate_id=gate_id,
                action="gate.round.open",
                before_snapshot=_gate_snapshot(gate),
                after_snapshot=after,
                context={
                    "round_id": str(round_id),
                    "round_number": latest_number + 1,
                    "policy_version": NPD_GATE_POLICY_VERSION,
                },
                occurred_at=occurred_at,
            )
            current = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
            )
            return self._record_from_row(connection, tenant_id=tenant_id, row=current)

    def sign(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        round_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        slot: GateSlot,
        status: GateSignoffStatus,
        note: str | None,
    ) -> GateRecord:
        if not may_sign_gate_slot(actor_role, slot):
            raise GateSigningDeniedError
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            project = self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            gate = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                for_update=True,
            )
            if project["current_stage_id"] != gate["stage_id"]:
                raise GateNotCurrentError
            if gate["status"] != "reviewing":
                raise GateInvalidStateError
            round_row = self._round(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                open_only=True,
                for_update=True,
            )
            if round_row is None or round_row["id"] != round_id:
                raise GateRoundNotOpenError
            signoff = (
                connection.execute(
                    select(tables.gate_signoffs)
                    .where(
                        tables.gate_signoffs.c.tenant_id == tenant_id,
                        tables.gate_signoffs.c.project_id == project_id,
                        tables.gate_signoffs.c.gate_id == gate_id,
                        tables.gate_signoffs.c.round_id == round_id,
                        tables.gate_signoffs.c.slot == slot,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if signoff is None:
                raise GateRoundNotOpenError
            if status == "conditional" and signoff["requirement"] != "conditional":
                raise GateInvalidStateError
            before = {
                "round_id": str(round_id),
                "slot": slot,
                "requirement": signoff["requirement"],
                "status": signoff["status"],
                "signed_by_user_id": (
                    str(signoff["signed_by_user_id"])
                    if signoff["signed_by_user_id"] is not None
                    else None
                ),
            }
            after = {
                "round_id": str(round_id),
                "slot": slot,
                "requirement": signoff["requirement"],
                "status": status,
                "signed_by_user_id": str(actor_user_id),
            }
            connection.execute(
                tables.gate_signoffs.update()
                .where(tables.gate_signoffs.c.id == signoff["id"])
                .values(
                    status=status,
                    signed_by_user_id=actor_user_id,
                    signer_role=actor_role.value,
                    signed_at=occurred_at,
                    note=note,
                    updated_at=occurred_at,
                )
            )
            _audit_only(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                gate_id=gate_id,
                action="gate.signoff.update",
                before_snapshot=before,
                after_snapshot=after,
                context={"governance_override": actor_role in {Role.OWNER, Role.ADMIN}},
                occurred_at=occurred_at,
            )
            current = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
            )
            return self._record_from_row(connection, tenant_id=tenant_id, row=current)

    def promote(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        actor_user_id: UUID,
        slot: GateSlot,
        requested: GateRequirement,
        reason: str,
    ) -> GateAdditionRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            project = self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            gate = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                for_update=True,
            )
            if project["current_stage_id"] != gate["stage_id"]:
                raise GateNotCurrentError
            if gate["status"] == "approved":
                raise GateInvalidStateError
            current_requirements = self._requirements_for_gate(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                stage_code=gate["stage_code"],
            )
            promoted = promote_requirement(current_requirements[slot], requested)
            if promoted is None or promoted == "not_applicable":
                raise GateRequirementPromotionError
            existing = (
                connection.execute(
                    select(tables.gate_signoff_additions)
                    .where(
                        tables.gate_signoff_additions.c.tenant_id == tenant_id,
                        tables.gate_signoff_additions.c.project_id == project_id,
                        tables.gate_signoff_additions.c.gate_id == gate_id,
                        tables.gate_signoff_additions.c.slot == slot,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            addition_id = existing["id"] if existing is not None else uuid4()
            values = {
                "requirement": promoted,
                "reason": reason,
                "active": True,
                "added_by_user_id": actor_user_id,
                "updated_at": occurred_at,
            }
            if existing is None:
                connection.execute(
                    tables.gate_signoff_additions.insert(),
                    {
                        "id": addition_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "gate_id": gate_id,
                        "slot": slot,
                        **values,
                        "created_at": occurred_at,
                    },
                )
            else:
                connection.execute(
                    tables.gate_signoff_additions.update()
                    .where(tables.gate_signoff_additions.c.id == addition_id)
                    .values(**values)
                )
            open_round = self._round(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                open_only=True,
                for_update=True,
            )
            if open_round is not None:
                connection.execute(
                    tables.gate_signoff_rounds.update()
                    .where(tables.gate_signoff_rounds.c.id == open_round["id"])
                    .values(
                        status="superseded",
                        superseded_by_user_id=actor_user_id,
                        superseded_at=occurred_at,
                        supersede_reason=f"Project requirement promoted: {slot}",
                        updated_at=occurred_at,
                    )
                )
            _audit_only(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                gate_id=gate_id,
                action="gate.requirement.promote",
                before_snapshot={"slot": slot, "requirement": current_requirements[slot]},
                after_snapshot={"slot": slot, "requirement": promoted, "reason": reason},
                occurred_at=occurred_at,
            )
            return GateAdditionRecord(
                id=addition_id,
                slot=slot,
                requirement=promoted,
                reason=reason,
                added_by_user_id=actor_user_id,
                created_at=existing["created_at"] if existing is not None else occurred_at,
            )

    def decide(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        actor_user_id: UUID,
        status: Literal["approved", "rejected"],
        rationale: str,
    ) -> GateRecord:
        occurred_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            project = self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
            gate = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                for_update=True,
            )
            if project["current_stage_id"] != gate["stage_id"]:
                raise GateNotCurrentError
            if gate["status"] != "reviewing":
                raise GateInvalidStateError
            round_row = self._round(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                open_only=True,
                for_update=True,
            )
            if round_row is None:
                raise GateRoundNotOpenError
            signoffs = self._signoff_rows(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
                round_id=round_row["id"],
                for_update=True,
            )
            readiness = self._readiness(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                stage_id=gate["stage_id"],
                requirements=_requirements(round_row["requirements"]),
                signoff_rows=signoffs,
                for_update=True,
                evaluated_at=occurred_at,
            )
            if status == "approved" and not readiness.ready:
                raise GateNotReadyError(readiness.blocker_keys)
            readiness_snapshot = self._readiness_dict(readiness)
            decision_id = uuid4()
            connection.execute(
                tables.decisions.insert(),
                {
                    "id": decision_id,
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "gate_id": gate_id,
                    "decided_by_user_id": actor_user_id,
                    "decision_kind": "gate_review",
                    "title": f"{gate['name']} · round {round_row['round_number']}",
                    "outcome": status,
                    "rationale": rationale,
                    "decided_at": occurred_at,
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            connection.execute(
                tables.gate_signoff_rounds.update()
                .where(tables.gate_signoff_rounds.c.id == round_row["id"])
                .values(
                    status="completed",
                    readiness_snapshot=readiness_snapshot,
                    completed_by_user_id=actor_user_id,
                    completed_at=occurred_at,
                    updated_at=occurred_at,
                )
            )
            connection.execute(
                tables.gates.update()
                .where(tables.gates.c.id == gate_id)
                .values(
                    status=status,
                    decided_at=occurred_at,
                    decided_by_user_id=actor_user_id,
                    updated_at=occurred_at,
                )
            )
            after = dict(_gate_snapshot(gate, status=status))
            after["decided_at"] = occurred_at.isoformat()
            after["decided_by_user_id"] = str(actor_user_id)
            if status == "approved":
                EventAuditWriter(
                    connection,
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    project_id=project_id,
                ).record(
                    EventDraft(
                        event_id=f"gate:{gate_id}:approved:{decision_id}",
                        event_type="GATE_APPROVED",
                        source="gate_service",
                        entity_id=gate_id,
                        payload={"gate_id": str(gate_id), "decision_id": str(decision_id)},
                        occurred_at=occurred_at,
                    ),
                    AuditDraft(
                        action="gate.approve",
                        before_snapshot=_gate_snapshot(gate),
                        after_snapshot=after,
                        context={
                            "round_id": str(round_row["id"]),
                            "round_number": round_row["round_number"],
                            "readiness": readiness_snapshot,
                        },
                    ),
                )
            else:
                _audit_only(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    gate_id=gate_id,
                    action="gate.reject",
                    before_snapshot=_gate_snapshot(gate),
                    after_snapshot=after,
                    context={
                        "decision_id": str(decision_id),
                        "round_id": str(round_row["id"]),
                    },
                    occurred_at=occurred_at,
                )
            current = self._gate_row(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                gate_id=gate_id,
            )
            return self._record_from_row(connection, tenant_id=tenant_id, row=current)

    def create_grandfather_exemption(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        gate_id: UUID,
        actor_user_id: UUID,
        actor_role: Role,
        requirement_key: str,
        policy_version: str,
        reason: str,
    ) -> GateGrandfatherRecord:
        if actor_role not in {Role.OWNER, Role.ADMIN}:
            raise GateGrandfatherPermissionError
        occurred_at = datetime.now(UTC)
        exemption_id = uuid4()
        try:
            with self._engine.begin() as connection:
                project = self._lock_project(connection, tenant_id=tenant_id, project_id=project_id)
                gate = self._gate_row(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    gate_id=gate_id,
                    for_update=True,
                )
                current_sequence = connection.execute(
                    select(tables.stages.c.sequence).where(
                        tables.stages.c.tenant_id == tenant_id,
                        tables.stages.c.id == project["current_stage_id"],
                    )
                ).scalar_one()
                if gate["status"] != "approved" or gate["stage_sequence"] >= current_sequence:
                    raise GateGrandfatherNotAllowedError
                connection.execute(
                    tables.gate_grandfather_exemptions.insert(),
                    {
                        "id": exemption_id,
                        "tenant_id": tenant_id,
                        "project_id": project_id,
                        "gate_id": gate_id,
                        "requirement_key": requirement_key,
                        "policy_version": policy_version,
                        "reason": reason,
                        "approved_by_user_id": actor_user_id,
                        "created_at": occurred_at,
                    },
                )
                after: dict[str, object] = {
                    "requirement_key": requirement_key,
                    "policy_version": policy_version,
                    "reason": reason,
                    "approved_by_user_id": str(actor_user_id),
                }
                _audit_only(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    gate_id=gate_id,
                    action="gate.grandfather.create",
                    before_snapshot=None,
                    after_snapshot=after,
                    occurred_at=occurred_at,
                )
                return GateGrandfatherRecord(
                    id=exemption_id,
                    requirement_key=requirement_key,
                    policy_version=policy_version,
                    reason=reason,
                    approved_by_user_id=actor_user_id,
                    created_at=occurred_at,
                )
        except IntegrityError as error:
            diagnostic = getattr(error.orig, "diag", None)
            if (
                getattr(diagnostic, "constraint_name", None)
                == "uq_gate_grandfather_tenant_gate_policy_key"
            ):
                raise GateConflictError from error
            raise
