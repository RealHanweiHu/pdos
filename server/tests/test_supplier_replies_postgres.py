"""Real PostgreSQL reply transactions. No migrations, cleanup or service doubles.

Run only after the coordinator assigns an exclusively owned temporary pdos_test.
Synthetic source registrations and committed tenant rows are retained for inspection.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, Table, create_engine, delete, func, select, text, update
from sqlalchemy.engine import make_url

from app.auth.repository import AuthContext, TenantRecord, UserRecord
from app.auth.roles import Role
from app.db.schema import tables
from app.db.test_safety import require_test_database_url
from app.db.url import psycopg_database_url
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.npi_execution import NpiNotFoundError
from app.domain.product_workspace import ProductWorkError
from app.domain.supplier_engineering import (
    EngineeringApply,
    EngineeringDraft,
    SupplierEngineeringService,
)
from app.domain.supplier_replies import ReplyConfirm, ReplyDraft, SupplierReplyService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft, WrittenEventAudit


def isolated_postgres_url() -> str:
    """Fail before engine creation; never resolve an endpoint from application settings."""
    configured = os.environ.get("TEST_DATABASE_URL")
    assert configured and configured.strip(), "Coordinator must explicitly assign TEST_DATABASE_URL"
    safe = require_test_database_url(configured)
    url = make_url(safe)
    assert os.environ.get("SUPPLY_POSTGRES_EXCLUSIVE") == "1", (
        "Coordinator must confirm exclusive ownership of the temporary container"
    )
    assert url.get_backend_name() == "postgresql", "A real PostgreSQL test URL is required"
    assert url.host in {"localhost", "127.0.0.1", "::1"}, "Use the dedicated local test container"
    assert url.port not in {None, 5432, 55432, 57432, 57433, 57434, 57439}, (
        "Protected, development or unassigned test port"
    )
    assert not {"servicefile", "host", "hostaddr", "port", "dbname", "service"} & set(url.query)
    assert url.database == "pdos_test"
    return psycopg_database_url(safe)


def postgres_engine(url: str, *, pool_size: int = 2) -> Engine:
    return create_engine(
        url,
        pool_size=pool_size,
        max_overflow=0,
        connect_args={"options": "-c statement_timeout=15000 -c lock_timeout=10000"},
    )


def seed_context(engine: Engine, *, tenant: TenantRecord | None = None, role: Role) -> AuthContext:
    if tenant is None:
        identifier = uuid4()
        tenant = TenantRecord(
            identifier, f"supply-pg-{identifier.hex}", "Supply PG fixture", "active"
        )
        with engine.begin() as c:
            c.execute(
                tables.tenants.insert().values(id=tenant.id, slug=tenant.slug, name=tenant.name)
            )
    user_id = uuid4()
    user = UserRecord(
        user_id,
        tenant.id,
        f"staff-{user_id.hex}",
        f"Fixture {role.value}",
        role,
        None,
        None,
        1,
        True,
    )
    with engine.begin() as c:
        c.execute(
            tables.users.insert().values(
                id=user.id,
                tenant_id=tenant.id,
                username=user.username,
                display_name=user.display_name,
                role=role.value,
            )
        )
    return AuthContext(tenant, user)


@dataclass
class SupplyPostgresScope:
    engine: Engine
    url: str
    owner: AuthContext
    peer: AuthContext
    engineer: AuthContext
    foreign: AuthContext
    project: UUID
    other_project: UUID
    supplier: UUID
    document: UUID
    reply_document: UUID
    record: UUID
    now: datetime

    def insert(self, table: Table, **values: Any) -> UUID:
        identity = uuid4()
        with self.engine.begin() as c:
            c.execute(table.insert().values(id=identity, tenant_id=self.owner.tenant.id, **values))
        return identity

    def document_for(self, project: UUID, title: str) -> UUID:
        body = f"Synthetic authorized test fixture: {title} {uuid4()}".encode()
        return self.insert(
            tables.documents,
            project_id=project,
            uploaded_by_user_id=self.owner.user.id,
            object_key=f"synthetic-postgres/{uuid4()}",
            filename=title,
            media_type="application/pdf",
            classification="internal",
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            extraction_status="preview_only",
        )

    def original(self, *, project: UUID | None = None, source: str | None = None) -> dict[str, Any]:
        actual_project = project or self.project
        document = (
            self.document
            if actual_project == self.project
            else self.document_for(actual_project, "other-project-source.pdf")
        )
        record = uuid4()
        draft = EngineeringDraft.model_validate(
            dict(
                kind="sample_delivery",
                source_reference=source or f"sample:{record}",
                title="Synthetic sample delivery",
                evidence_id=document,
                reason="Synthetic source seed",
                requested=dict(
                    at=self.now - timedelta(days=2), evidence_id=document, location="request p1"
                ),
                promised=dict(
                    at=self.now + timedelta(days=2), evidence_id=document, location="promise p2"
                ),
            )
        )
        service = SupplierEngineeringService(self.engine)
        observed = service.preview(self.owner, actual_project, self.supplier, record, draft)
        return service.apply(
            self.owner,
            actual_project,
            self.supplier,
            record,
            EngineeringApply.model_validate(
                {
                    **draft.model_dump(),
                    "request_id": uuid4(),
                    "expected_version": 0,
                    "expected_digest": observed["digest"],
                }
            ),
        )

    def reply(self, update_kind: str = "first_response") -> ReplyDraft:
        return ReplyDraft.model_validate(
            dict(
                update=update_kind,
                at=self.now,
                evidence_id=self.reply_document,
                location="internal forwarded reply p1",
                reason="Reply to the original sample request",
            )
        )

    def confirmation(
        self, *, actor: AuthContext | None = None, update_kind: str = "first_response"
    ) -> ReplyConfirm:
        draft = self.reply(update_kind)
        observed = SupplierReplyService(self.engine).preview(
            actor or self.owner, self.project, self.supplier, self.record, draft
        )
        return ReplyConfirm.model_validate(
            {
                **draft.model_dump(),
                "request_id": uuid4(),
                "expected_digest": observed["digest"],
                "expected_version": observed["basis"]["previous_version"],
                "evidence_checked": True,
            }
        )

    def footprint(self) -> tuple[int, int, int]:
        """Count committed business rows/events/audits in this dedicated tenant only."""
        with self.engine.connect() as c:
            counts = [
                int(
                    c.execute(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.tenant_id == self.owner.tenant.id)
                    ).scalar_one()
                )
                for table in (tables.supplier_engineering_records, tables.events, tables.audit_log)
            ]
        return counts[0], counts[1], counts[2]


def seed_project(scope: SupplyPostgresScope, label: str) -> UUID:
    requirement = scope.insert(
        tables.requirements,
        created_by_user_id=scope.owner.user.id,
        code=f"REQ-{label}",
        title=label,
        status="converted",
    )
    case = scope.insert(
        tables.development_cases,
        requirement_id=requirement,
        created_by_user_id=scope.owner.user.id,
        code=f"CASE-{label}",
        title=label,
        status="converted",
    )
    workflow = scope.insert(tables.workflows, code=f"WF-{label}", name=label)
    stage = scope.insert(tables.stages, workflow_id=workflow, code="evt", name="EVT", sequence=1)
    project = scope.insert(
        tables.projects,
        development_case_id=case,
        workflow_id=workflow,
        current_stage_id=stage,
        owner_user_id=scope.owner.user.id,
        code=f"PRJ-{label}",
        name=label,
        status="active",
    )
    for actor in (scope.owner, scope.peer, scope.engineer):
        scope.insert(
            tables.project_members,
            project_id=project,
            user_id=actor.user.id,
            added_by_user_id=scope.owner.user.id,
        )
    return project


@pytest.fixture
def supply_postgres_scope() -> Iterator[SupplyPostgresScope]:
    url = isolated_postgres_url()
    engine = postgres_engine(url)
    try:
        with engine.connect() as c:
            assert c.execute(text("SELECT current_database()")).scalar_one() == "pdos_test"
            assert c.execute(text("SHOW session_replication_role")).scalar_one() == "origin"
            assert (
                c.execute(
                    text("SELECT to_regclass('cehub_supplier.supplier_engineering_records')")
                ).scalar_one()
                is not None
            ), "Coordinator must migrate the isolated candidate first"
        owner = seed_context(engine, role=Role.OWNER)
        peer = seed_context(engine, tenant=owner.tenant, role=Role.PROJECT_MANAGER)
        engineer = seed_context(engine, tenant=owner.tenant, role=Role.ENGINEER)
        foreign = seed_context(engine, role=Role.OWNER)
        scope = SupplyPostgresScope(
            engine,
            url,
            owner,
            peer,
            engineer,
            foreign,
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            datetime.now(UTC) - timedelta(seconds=5),
        )
        scope.project = seed_project(scope, "one")
        scope.other_project = seed_project(scope, "two")
        scope.supplier = scope.insert(tables.suppliers, code="SUPPLY-PG", name="Synthetic supplier")
        scope.document = scope.document_for(scope.project, "supplier-request.pdf")
        scope.reply_document = scope.document_for(scope.project, "forwarded-reply.pdf")
        scope.record = UUID(scope.original()["record_id"])
        print(f"Retained supply fixture tenant={owner.tenant.id} project={scope.project}")
        yield scope
    finally:
        engine.dispose()


@pytest.mark.parametrize("update_kind", ["first_response", "sample_received"])
def test_reply_saves_v2_event_audit_and_serial_replay_once(
    supply_postgres_scope: SupplyPostgresScope,
    update_kind: str,
) -> None:
    s = supply_postgres_scope
    command = s.confirmation(update_kind=update_kind)
    before = s.footprint()
    service = SupplierReplyService(s.engine)
    saved = service.confirm(s.owner, s.project, s.supplier, s.record, command)
    assert saved["version"] == 2
    assert service.confirm(s.owner, s.project, s.supplier, s.record, command)["id"] == saved["id"]
    assert s.footprint() == tuple(n + 1 for n in before)
    with s.engine.connect() as c:
        rows = list(
            c.execute(
                select(tables.supplier_engineering_records)
                .where(
                    tables.supplier_engineering_records.c.tenant_id == s.owner.tenant.id,
                    tables.supplier_engineering_records.c.record_id == s.record,
                )
                .order_by(tables.supplier_engineering_records.c.version)
            ).mappings()
        )
        assert [r["version"] for r in rows] == [1, 2]
        assert rows[0]["payload"]["promised"] == rows[1]["payload"]["promised"]
        assert rows[1]["snapshot"]["supplier_reply"]["reply"] == s.reply(update_kind).model_dump(
            mode="json"
        )
        field = "responded" if update_kind == "first_response" else "received"
        assert rows[1]["payload"][field]["evidence_id"] == str(s.reply_document)
        audit = (
            c.execute(
                select(tables.audit_log).where(
                    tables.audit_log.c.tenant_id == s.owner.tenant.id,
                    tables.audit_log.c.after_snapshot["id"].as_string() == saved["id"],
                )
            )
            .mappings()
            .one()
        )
        event = (
            c.execute(
                select(tables.events).where(
                    tables.events.c.tenant_id == s.owner.tenant.id,
                    tables.events.c.entity_id == s.record,
                    tables.events.c.event_id == audit["event_id"],
                )
            )
            .mappings()
            .one()
        )
        assert event["event_type"] == "NPI_RECORD_CHANGED"
        assert audit["actor_user_id"] == s.owner.user.id
        assert audit["after_snapshot"]["id"] == saved["id"]


def test_two_real_connections_replay_same_reply_once(
    supply_postgres_scope: SupplyPostgresScope,
) -> None:
    s = supply_postgres_scope
    command, before, ready = s.confirmation(), s.footprint(), Barrier(2)

    def submit() -> tuple[int, dict[str, Any]]:
        worker_engine = postgres_engine(s.url, pool_size=1)
        try:
            with worker_engine.connect() as c:
                pid = int(c.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.wait(timeout=10)
            result = SupplierReplyService(worker_engine).confirm(
                s.owner, s.project, s.supplier, s.record, command
            )
            return pid, result
        finally:
            worker_engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        values = [future.result(timeout=30) for future in futures]
    assert values[0][0] != values[1][0]
    assert values[0][1]["id"] == values[1][1]["id"]
    assert values[0][1]["version"] == 2
    assert s.footprint() == tuple(n + 1 for n in before)


@pytest.mark.parametrize("replay", ["content", "actor", "project", "record", "tenant"])
def test_reply_request_reuse_outside_original_binding_is_rejected(
    supply_postgres_scope: SupplyPostgresScope,
    replay: str,
) -> None:
    s = supply_postgres_scope
    service, command = SupplierReplyService(s.engine), s.confirmation()
    original_command = command
    alternate = UUID(s.original(source="alternate-request")["record_id"])
    saved = service.confirm(s.owner, s.project, s.supplier, s.record, command)
    before = s.footprint()
    actor, project, record = s.owner, s.project, s.record
    if replay == "content":
        command = ReplyConfirm.model_validate({**command.model_dump(), "reason": "different reply"})
    elif replay == "actor":
        actor = s.peer
    elif replay == "project":
        project = s.other_project
    elif replay == "record":
        record = alternate
    else:
        actor = s.foreign
    with pytest.raises((ProductWorkError, NpiNotFoundError, KnowledgeAccessError)):
        service.confirm(actor, project, s.supplier, record, command)
    assert s.footprint() == before
    assert (
        service.confirm(s.owner, s.project, s.supplier, s.record, original_command)["id"]
        == saved["id"]
    )


@pytest.mark.parametrize("drift", ["source", "version", "actor", "revoked"])
def test_reply_preview_drift_refuses_any_partial_write(
    supply_postgres_scope: SupplyPostgresScope,
    drift: str,
) -> None:
    s = supply_postgres_scope
    actor = s.engineer if drift == "revoked" else s.owner
    command = s.confirmation(actor=actor)
    if drift == "source":
        with s.engine.begin() as c:
            c.execute(
                update(tables.documents)
                .where(
                    tables.documents.c.tenant_id == s.owner.tenant.id,
                    tables.documents.c.id == s.reply_document,
                )
                .values(sha256="f" * 64)
            )
    elif drift == "version":
        service = SupplierEngineeringService(s.engine)
        with s.engine.connect() as c:
            current = c.execute(
                select(tables.supplier_engineering_records.c.payload).where(
                    tables.supplier_engineering_records.c.tenant_id == s.owner.tenant.id,
                    tables.supplier_engineering_records.c.record_id == s.record,
                )
            ).scalar_one()
        draft = EngineeringDraft.model_validate(
            {**current, "reason": "Named revision before reply"}
        )
        observed = service.preview(s.owner, s.project, s.supplier, s.record, draft)
        service.apply(
            s.owner,
            s.project,
            s.supplier,
            s.record,
            EngineeringApply.model_validate(
                {
                    **draft.model_dump(),
                    "request_id": uuid4(),
                    "expected_version": 1,
                    "expected_digest": observed["digest"],
                }
            ),
        )
    elif drift == "actor":
        actor = s.peer
    else:
        with s.engine.begin() as c:
            c.execute(
                delete(tables.project_members).where(
                    tables.project_members.c.tenant_id == s.owner.tenant.id,
                    tables.project_members.c.project_id == s.project,
                    tables.project_members.c.user_id == actor.user.id,
                )
            )
    before = s.footprint()
    with pytest.raises((ProductWorkError, KnowledgeAccessError)):
        SupplierReplyService(s.engine).confirm(actor, s.project, s.supplier, s.record, command)
    assert s.footprint() == before


def test_real_event_and_audit_inserts_roll_back_on_audit_failure_then_recover(
    supply_postgres_scope: SupplyPostgresScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = supply_postgres_scope
    command, before = s.confirmation(), s.footprint()
    original = EventAuditWriter.record

    def fail_after_sql(
        self: EventAuditWriter, event: EventDraft, audit: AuditDraft
    ) -> WrittenEventAudit:
        original(
            self, event, audit
        )  # Real event and audit SQL execute inside the business transaction.
        raise RuntimeError("Injected audit failure after real inserts")

    with monkeypatch.context() as patch:
        patch.setattr(EventAuditWriter, "record", fail_after_sql)
        with pytest.raises(RuntimeError, match="Injected audit failure"):
            SupplierReplyService(s.engine).confirm(
                s.owner, s.project, s.supplier, s.record, command
            )
    assert s.footprint() == before
    result = SupplierReplyService(s.engine).confirm(
        s.owner, s.project, s.supplier, s.record, command
    )
    assert result["version"] == 2
    assert s.footprint() == tuple(n + 1 for n in before)
