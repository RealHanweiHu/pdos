"""Research sources and evidence snapshots (vNext V2-7, C8).

Brought forward from Phase 5 because D25's agent-reach gives *every* seat the
ability to fetch external material, and a fetch without a snapshot is a claim
without ground truth.

Two rules carry the weight:

* **A snapshot is immutable.** Correcting one means capturing a new snapshot
  and pointing `superseded_by_id` at it. A database trigger enforces this, so
  even a direct SQL write cannot silently change what a citation resolves to.
* **External material is labelled, not blocked.** Anything collected from a
  web or api source is born `untrusted_external`. Per D25 the label travels
  with the citation rather than stopping the fetch; promoting it to `verified`
  is a human act with its own audit trail.

Sources are tenant-scoped, not project-scoped: the point of a shared evidence
base is that one capture serves every project that needs it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

# `EvidenceService.list_sources` does not shadow the builtin, but keeping the
# alias here matches the other domain modules and survives a later rename.
EvidenceList = list

SOURCE_TYPES = frozenset({"web", "api", "file", "internal_system"})
TRUST_TIERS = frozenset({"official", "public", "community", "unknown"})
TAINTS = frozenset({"untrusted_external", "internal", "verified"})
# Anything fetched over the network is untrusted until a person says otherwise.
REMOTE_SOURCE_TYPES = frozenset({"web", "api"})


class ResearchSourceNotFoundError(LookupError):
    """Raised when the research source is absent from the tenant."""


class EvidenceSnapshotNotFoundError(LookupError):
    """Raised when the snapshot is absent from the tenant."""


class EvidenceValidationError(ValueError):
    """Raised when a source or snapshot is malformed."""


class EvidenceContentUnavailableError(LookupError):
    """Historical metadata exists, but its captured body was never persisted."""


class EvidenceImmutableError(ValueError):
    """Raised when a caller tries to rewrite a captured snapshot."""


@dataclass(frozen=True)
class ResearchSourceRecord:
    id: UUID
    name: str
    source_type: str
    base_url: str | None
    owner_user_id: UUID
    license_note: str | None
    allowed_use: str
    collection_frequency: str
    retention_policy: str
    trust_tier: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class EvidenceSnapshotRecord:
    id: UUID
    source_id: UUID | None
    url: str | None
    captured_at: datetime
    captured_by_user_id: UUID
    content_digest: str
    content_ref: str
    content_language: str
    source_version: str | None
    trust_tier: str
    taint: str
    byte_size: int
    freshness_expires_at: datetime | None
    superseded_by_id: UUID | None
    conflicts_with_id: UUID | None
    conflict_note: str | None
    reused_existing: bool

    def is_stale(self, *, as_of: datetime) -> bool:
        """Expired freshness, or superseded by a later capture."""
        if self.superseded_by_id is not None:
            return True
        if self.freshness_expires_at is None:
            return False
        return self.freshness_expires_at <= as_of


def content_digest(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _source(row: RowMapping) -> ResearchSourceRecord:
    return ResearchSourceRecord(
        id=row["id"],
        name=row["name"],
        source_type=row["source_type"],
        base_url=row["base_url"],
        owner_user_id=row["owner_user_id"],
        license_note=row["license_note"],
        allowed_use=row["allowed_use"],
        collection_frequency=row["collection_frequency"],
        retention_policy=row["retention_policy"],
        trust_tier=row["trust_tier"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot(row: RowMapping, *, reused_existing: bool) -> EvidenceSnapshotRecord:
    return EvidenceSnapshotRecord(
        id=row["id"],
        source_id=row["source_id"],
        url=row["url"],
        captured_at=row["captured_at"],
        captured_by_user_id=row["captured_by_user_id"],
        content_digest=row["content_digest"],
        content_ref=row["content_ref"],
        content_language=row["content_language"],
        source_version=row["source_version"],
        trust_tier=row["trust_tier"],
        taint=row["taint"],
        byte_size=row["byte_size"],
        freshness_expires_at=row["freshness_expires_at"],
        superseded_by_id=row["superseded_by_id"],
        conflicts_with_id=row["conflicts_with_id"],
        conflict_note=row["conflict_note"],
        reused_existing=reused_existing,
    )


def _source_audit(record: ResearchSourceRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "name": record.name,
        "source_type": record.source_type,
        "allowed_use": record.allowed_use,
        "trust_tier": record.trust_tier,
        "status": record.status,
    }


def _snapshot_audit(record: EvidenceSnapshotRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "source_id": str(record.source_id) if record.source_id else None,
        "content_digest": record.content_digest,
        "source_version": record.source_version,
        "taint": record.taint,
        "trust_tier": record.trust_tier,
        "superseded_by_id": (str(record.superseded_by_id) if record.superseded_by_id else None),
    }


class EvidenceService:
    def __init__(
        self,
        engine: Engine,
        *,
        authorize_write: Callable[[Connection], None] | None = None,
        on_capture: Callable[[Connection, EvidenceSnapshotRecord], None] | None = None,
    ) -> None:
        self._engine = engine
        self._authorize_write = authorize_write
        self._on_capture = on_capture

    def list_sources(self, *, tenant_id: UUID) -> EvidenceList[ResearchSourceRecord]:
        with self._engine.connect() as connection:
            return [
                _source(row)
                for row in connection.execute(
                    select(tables.research_sources)
                    .where(tables.research_sources.c.tenant_id == tenant_id)
                    .order_by(tables.research_sources.c.name)
                ).mappings()
            ]

    def create_source(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        name: str,
        source_type: str,
        allowed_use: str,
        collection_frequency: str,
        retention_policy: str,
        trust_tier: str,
        base_url: str | None = None,
        license_note: str | None = None,
        owner_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> ResearchSourceRecord:
        if source_type not in SOURCE_TYPES:
            raise EvidenceValidationError(f"unknown source type: {source_type}")
        if trust_tier not in TRUST_TIERS:
            raise EvidenceValidationError(f"unknown trust tier: {trust_tier}")
        if source_type in REMOTE_SOURCE_TYPES and not base_url:
            raise EvidenceValidationError(
                "a web or api source needs a base URL so its licence scope stays auditable"
            )
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        source_id = uuid4()
        with self._engine.begin() as connection:
            if self._authorize_write is not None:
                self._authorize_write(connection)
            connection.execute(
                tables.research_sources.insert(),
                {
                    "id": source_id,
                    "tenant_id": tenant_id,
                    "name": name,
                    "source_type": source_type,
                    "base_url": base_url,
                    "owner_user_id": owner_user_id or actor_user_id,
                    "license_note": license_note,
                    "allowed_use": allowed_use,
                    "collection_frequency": collection_frequency,
                    "retention_policy": retention_policy,
                    "trust_tier": trust_tier,
                    "status": "active",
                    "created_at": occurred_at,
                    "updated_at": occurred_at,
                },
            )
            record = self._get_source(connection, tenant_id=tenant_id, source_id=source_id)
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"research-source:{source_id}:created:{uuid4()}",
                    event_type="RESEARCH_SOURCE_CHANGED",
                    source="evidence_service",
                    entity_id=source_id,
                    payload={
                        "source_id": str(source_id),
                        "source_type": source_type,
                        "action": "created",
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="research_source.created",
                    before_snapshot=None,
                    after_snapshot=_source_audit(record),
                ),
            )
            return record

    def capture(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        content: str,
        source_id: UUID | None = None,
        url: str | None = None,
        source_version: str | None = None,
        content_language: str = "zh-CN",
        trust_tier: str | None = None,
        taint: str | None = None,
        freshness_expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> EvidenceSnapshotRecord:
        """Record an observation.

        Re-capturing identical bytes from the same source version returns the
        existing snapshot: the same observation twice is one observation, and
        inflating the evidence count would make a single source look like
        corroboration.
        """
        if not content.strip():
            raise EvidenceValidationError("snapshot content is empty")
        if "\x00" in content or len(content.encode("utf-8")) > 2 * 1024 * 1024:
            raise EvidenceValidationError("snapshot must be readable text within 2 MiB")
        digest = content_digest(content)
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if self._authorize_write is not None:
                self._authorize_write(connection)
            source: ResearchSourceRecord | None = None
            if source_id is not None:
                source = self._get_source(connection, tenant_id=tenant_id, source_id=source_id)
                if source.status != "active":
                    raise EvidenceValidationError("cannot capture from a disabled research source")

            resolved_tier = trust_tier or (source.trust_tier if source else "unknown")
            if resolved_tier not in TRUST_TIERS:
                raise EvidenceValidationError(f"unknown trust tier: {resolved_tier}")
            resolved_taint = taint or _default_taint(source)
            if resolved_taint not in TAINTS:
                raise EvidenceValidationError(f"unknown taint: {resolved_taint}")
            # A caller cannot declare network-fetched material trusted at
            # capture time; promotion to `verified` is a separate human act.
            if (
                source is not None
                and source.source_type in REMOTE_SOURCE_TYPES
                and resolved_taint == "verified"
            ):
                raise EvidenceValidationError(
                    "remote material cannot be captured as verified; "
                    "capture it untrusted and verify it explicitly"
                )

            # Serialize the same observation; parallel retries cannot inflate evidence counts.
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"evidence:{tenant_id}:{source_id}:{source_version}:{digest}"},
            )
            connection.execute(
                insert(tables.evidence_contents)
                .values(
                    tenant_id=tenant_id,
                    content_digest=digest,
                    body=content,
                    byte_size=len(content.encode("utf-8")),
                )
                .on_conflict_do_nothing(index_elements=["tenant_id", "content_digest"])
            )
            existing = (
                connection.execute(
                    select(tables.evidence_snapshots).where(
                        tables.evidence_snapshots.c.tenant_id == tenant_id,
                        tables.evidence_snapshots.c.source_id.is_not_distinct_from(source_id),
                        tables.evidence_snapshots.c.content_digest == digest,
                        tables.evidence_snapshots.c.source_version.is_not_distinct_from(
                            source_version
                        ),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                reused = _snapshot(existing, reused_existing=True)
                if self._on_capture is not None:
                    self._on_capture(connection, reused)
                return reused

            snapshot_id = uuid4()
            connection.execute(
                tables.evidence_snapshots.insert(),
                {
                    "id": snapshot_id,
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "url": url,
                    "captured_at": occurred_at,
                    "captured_by_user_id": actor_user_id,
                    "content_digest": digest,
                    "content_ref": f"db:evidence_contents/{tenant_id}/{digest}",
                    "content_language": content_language,
                    "source_version": source_version,
                    "trust_tier": resolved_tier,
                    "taint": resolved_taint,
                    "byte_size": len(content.encode("utf-8")),
                    "freshness_expires_at": freshness_expires_at,
                    "created_at": occurred_at,
                },
            )
            record = self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"evidence:{snapshot_id}:captured:{uuid4()}",
                    event_type="EVIDENCE_SNAPSHOT_CAPTURED",
                    source="evidence_service",
                    entity_id=snapshot_id,
                    payload={
                        "snapshot_id": str(snapshot_id),
                        "content_digest": digest,
                        "taint": resolved_taint,
                        "trust_tier": resolved_tier,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="evidence_snapshot.captured",
                    before_snapshot=None,
                    after_snapshot=_snapshot_audit(record),
                ),
            )
            if self._on_capture is not None:
                self._on_capture(connection, record)
            return record

    def supersede(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        snapshot_id: UUID,
        superseded_by_id: UUID,
        now: datetime | None = None,
    ) -> EvidenceSnapshotRecord:
        """Point an older snapshot at the capture that replaces it."""
        if snapshot_id == superseded_by_id:
            raise EvidenceValidationError("a snapshot cannot supersede itself")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if self._authorize_write is not None:
                self._authorize_write(connection)
            before = self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)
            replacement = self._get_snapshot(
                connection, tenant_id=tenant_id, snapshot_id=superseded_by_id
            )
            if before.superseded_by_id is not None:
                raise EvidenceImmutableError(
                    "snapshot is already superseded; supersede the newest one instead"
                )
            if replacement.captured_at < before.captured_at:
                raise EvidenceValidationError(
                    "the replacement snapshot is older than the one it supersedes"
                )
            connection.execute(
                tables.evidence_snapshots.update()
                .where(
                    tables.evidence_snapshots.c.tenant_id == tenant_id,
                    tables.evidence_snapshots.c.id == snapshot_id,
                )
                .values(superseded_by_id=superseded_by_id)
            )
            record = self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"evidence:{snapshot_id}:superseded:{uuid4()}",
                    event_type="EVIDENCE_SNAPSHOT_CAPTURED",
                    source="evidence_service",
                    entity_id=snapshot_id,
                    payload={
                        "snapshot_id": str(snapshot_id),
                        "content_digest": record.content_digest,
                        "taint": record.taint,
                        "trust_tier": record.trust_tier,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="evidence_snapshot.superseded",
                    before_snapshot=_snapshot_audit(before),
                    after_snapshot=_snapshot_audit(record),
                ),
            )
            return record

    def record_conflict(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        snapshot_id: UUID,
        conflicts_with_id: UUID,
        note: str,
        now: datetime | None = None,
    ) -> EvidenceSnapshotRecord:
        """Flag two snapshots as disagreeing, with the disagreement stated.

        Conflicts are recorded rather than resolved: two sources disagreeing is
        itself a finding, and silently picking one would hide it.
        """
        if snapshot_id == conflicts_with_id:
            raise EvidenceValidationError("a snapshot cannot conflict with itself")
        if not note.strip():
            raise EvidenceValidationError("a conflict needs a stated disagreement")
        occurred_at = (now or datetime.now(UTC)).astimezone(UTC)
        with self._engine.begin() as connection:
            if self._authorize_write is not None:
                self._authorize_write(connection)
            before = self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)
            self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=conflicts_with_id)
            connection.execute(
                tables.evidence_snapshots.update()
                .where(
                    tables.evidence_snapshots.c.tenant_id == tenant_id,
                    tables.evidence_snapshots.c.id == snapshot_id,
                )
                .values(conflicts_with_id=conflicts_with_id, conflict_note=note)
            )
            record = self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)
            EventAuditWriter(connection, tenant_id=tenant_id, actor_user_id=actor_user_id).record(
                EventDraft(
                    event_id=f"evidence:{snapshot_id}:conflict:{uuid4()}",
                    event_type="EVIDENCE_SNAPSHOT_CAPTURED",
                    source="evidence_service",
                    entity_id=snapshot_id,
                    payload={
                        "snapshot_id": str(snapshot_id),
                        "content_digest": record.content_digest,
                        "taint": record.taint,
                        "trust_tier": record.trust_tier,
                    },
                    occurred_at=occurred_at,
                ),
                AuditDraft(
                    action="evidence_snapshot.conflict_recorded",
                    before_snapshot=_snapshot_audit(before),
                    after_snapshot=_snapshot_audit(record),
                ),
            )
            return record

    def list_snapshots(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID | None = None,
        include_superseded: bool = True,
    ) -> EvidenceList[EvidenceSnapshotRecord]:
        statement = select(tables.evidence_snapshots).where(
            tables.evidence_snapshots.c.tenant_id == tenant_id
        )
        if source_id is not None:
            statement = statement.where(tables.evidence_snapshots.c.source_id == source_id)
        if not include_superseded:
            statement = statement.where(tables.evidence_snapshots.c.superseded_by_id.is_(None))
        with self._engine.connect() as connection:
            return [
                _snapshot(row, reused_existing=False)
                for row in connection.execute(
                    statement.order_by(tables.evidence_snapshots.c.captured_at.desc())
                ).mappings()
            ]

    def read_content(self, *, tenant_id: UUID, snapshot_id: UUID) -> dict[str, Any]:
        with self._engine.connect() as connection:
            snapshot = self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)
            if snapshot.source_id is not None:
                source = self._get_source(
                    connection, tenant_id=tenant_id, source_id=snapshot.source_id
                )
                if source.status != "active":
                    raise EvidenceValidationError("来源已停用，正文暂不可访问")
            row = (
                connection.execute(
                    select(tables.evidence_contents).where(
                        tables.evidence_contents.c.tenant_id == tenant_id,
                        tables.evidence_contents.c.content_digest == snapshot.content_digest,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise EvidenceContentUnavailableError(
                    "此历史快照仅有元数据，原正文未保存；请重新采集来源"
                )
            return {
                "snapshot_id": str(snapshot_id),
                "content_digest": snapshot.content_digest,
                "content": row["body"],
                "byte_size": row["byte_size"],
                "stored_at": row["stored_at"].isoformat(),
                "taint": snapshot.taint,
                "content_language": snapshot.content_language,
            }

    def get_snapshot(self, *, tenant_id: UUID, snapshot_id: UUID) -> EvidenceSnapshotRecord:
        with self._engine.connect() as connection:
            return self._get_snapshot(connection, tenant_id=tenant_id, snapshot_id=snapshot_id)

    @staticmethod
    def _get_source(
        connection: Connection, *, tenant_id: UUID, source_id: UUID
    ) -> ResearchSourceRecord:
        row = (
            connection.execute(
                select(tables.research_sources).where(
                    tables.research_sources.c.tenant_id == tenant_id,
                    tables.research_sources.c.id == source_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ResearchSourceNotFoundError
        return _source(row)

    @staticmethod
    def _get_snapshot(
        connection: Connection, *, tenant_id: UUID, snapshot_id: UUID
    ) -> EvidenceSnapshotRecord:
        row = (
            connection.execute(
                select(tables.evidence_snapshots).where(
                    tables.evidence_snapshots.c.tenant_id == tenant_id,
                    tables.evidence_snapshots.c.id == snapshot_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise EvidenceSnapshotNotFoundError
        return _snapshot(row, reused_existing=False)


def _default_taint(source: ResearchSourceRecord | None) -> str:
    if source is None:
        # Uploaded by a person inside the tenant with no external source.
        return "internal"
    return "untrusted_external" if source.source_type in REMOTE_SOURCE_TYPES else "internal"
