"""No-connect actual content readers; SQL and retained professional IO substituted.

get_preparation, project/definition, configuration and whole-line source readers
execute unmodified. These cases prove their composition and opaque/UOW guards,
not PG/RLS, historical professional qualification or publication permission.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import Null

from pdos_next.contracts import Command
from pdos_next.domain.configurations.models import (
    BomRevision,
    EngineeringConfiguration,
    ProcessRevision,
)
from pdos_next.domain.manufacturing_baseline import models, publication_rules, schemas, service
from pdos_next.domain.manufacturing_baseline.publication_material_owner import (
    ActualPublicationMaterialOwner,
)
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    Receipt,
    RequestKey,
)
from pdos_next.service import Context, digest, material_digest

from .test_publication_rules import case as publication_case  # noqa: F401


class SelectSession(Session):
    def __init__(self, engine):
        super().__init__(engine)
        self.rows, self.queries, self.hook = {}, [], None

    def add_row(self, row):
        self.rows.setdefault(type(row), []).append(row)
        return row

    def get(self, model, identity, **kwargs):
        return next((v for v in self.rows.get(model, ()) if v.id == identity), None)

    def _matches(self, row, expression):
        if expression.operator is operators.and_:
            return all(self._matches(row, part) for part in expression.clauses)
        if expression.operator is operators.or_:
            return any(self._matches(row, part) for part in expression.clauses)
        if getattr(expression.right, "name", None) == "category_for_product":
            value = self.get(Product, next(iter(expression.right.clauses)).value).category_id
        elif isinstance(expression.right, Null):
            value = None
        else:
            assert hasattr(expression.right, "value"), "new SQL needs an explicit substitute"
            value = expression.right.value
        actual = getattr(row, expression.left.key)
        if expression.operator is operators.in_op:
            return actual in value
        assert expression.operator in (operators.eq, operators.is_, operators.is_not_distinct_from)
        return actual == value

    def scalars(self, statement, *args, **kwargs):
        self.queries.append(statement)
        model = statement.column_descriptions[0]["entity"]
        rows = list(self.rows.get(model, ()))
        assert not statement._setup_joins or not rows
        for expression in statement._where_criteria:
            rows = [v for v in rows if self._matches(v, expression)]
        if model is ProcessRevision:
            rows.sort(key=lambda v: v.revision, reverse=True)
        if statement._limit_clause is not None:
            rows = rows[: statement._limit_clause.value]
        if self.hook:
            self.hook(model)
        return rows

    def scalar(self, statement, *args, **kwargs):
        rows = self.scalars(statement)
        return rows[0] if rows else None

    def execute(self, statement, *args, **kwargs):
        assert [v["entity"] for v in statement.column_descriptions] == [Principal, Grant]
        rows = []
        for person in self.rows[Principal]:
            for grant in self.rows[Grant]:
                if (person.id, person.tenant_id) != (grant.principal_id, grant.tenant_id):
                    continue
                if all(
                    self._matches(
                        person if clause.left.table.name == Principal.__tablename__ else grant,
                        clause,
                    )
                    for clause in statement._where_criteria
                ):
                    rows.append((person, grant))
        return SimpleNamespace(all=lambda: rows)

    def flush(self, *args, **kwargs):
        raise AssertionError("Publication material reading must not flush")


def _saved_preparation(s, ctx, pid, view):
    operation = next(key for key, value in schemas.KINDS.items() if value == view.kind)
    payload = schemas.PAYLOADS[operation].model_validate(view.body["input"])
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=operation,
        category_id=ctx.category_id,
        product_id=pid,
        expected_revision=7,
        payload=payload.model_dump(mode="json"),
        source_read_set=[value.model_dump(mode="json") for value in view.required_source_read_set],
    )
    at = datetime.now(UTC) - timedelta(seconds=1)
    review = {"explicit": "retained common-group SELECT substitute"}
    row = models.PreparationVersion(
        **{
            key: getattr(view, key)
            for key in (
                "id",
                "kind",
                "revision",
                "series_id",
                "project_id",
                "owner_id",
                "visibility",
                "title",
                "previous_id",
                "previous_revision",
                "operation_key",
                "purpose",
            )
        },
        tenant_id=ctx.tenant_id,
        product_id=pid,
        status="draft",
        process_id=view.process.id,
        process_revision=view.process.revision,
        purpose_sha256=digest(view.purpose),
        operation=operation,
        body=deepcopy(view.body),
        body_sha256=digest(view.body),
        intent_digest=digest(str(view.id)),
        input_snapshot={
            "command": service._saved_command(command),
            "semantic": service.semantic(payload),
            "request_digest": service._request_digest(command, payload),
        },
        sources=[v.model_dump(mode="json") for v in view.sources],
        required_source_read_set=[v.model_dump(mode="json") for v in view.required_source_read_set],
        review=review,
        shared_proof_id=uuid4(),
        shared_proof_revision=7,
        proof_consumed_at=at,
        proof_expires_at=at + timedelta(hours=1),
        token_sha256=digest("original explicit T1 proof"),
        material_sha256=material_digest(
            Context(ctx.tenant_id, view.owner_id, view.owner_id), command, payload, service
        ),
        read_set_sha256=digest(
            [service.json_value(v) for v in service.canonical_reads(command.source_read_set)]
        ),
        authority_snapshot={"subject_id": str(view.owner_id)},
        created_at=at,
    )
    s.add_row(row)
    s.add_row(
        models.PreparationCurrent(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            project_id=view.project_id,
            kind=view.kind,
            series_id=view.series_id,
            version_id=view.id,
            revision=view.revision,
        )
    )
    s.add_row(
        Confirmation(
            id=row.shared_proof_id,
            tenant_id=ctx.tenant_id,
            product_id=pid,
            actor_id=view.owner_id,
            subject_id=pid,
            operation=operation,
            revision=7,
            consumed=True,
            token_hash=row.token_sha256,
            payload_digest=row.material_sha256,
            snapshot=review,
            created_at=at - timedelta(seconds=1),
            expires_at=row.proof_expires_at,
        )
    )
    receipt = s.add_row(
        Receipt(
            id=view.receipt_id,
            tenant_id=ctx.tenant_id,
            product_id=pid,
            command_id=command.command_id,
            actor_id=view.owner_id,
            requester_id=view.owner_id,
            operation=operation,
            subject_type=view.kind,
            subject_id=view.id,
            subject_revision=view.revision,
            visibility=view.visibility,
            intent_digest=row.intent_digest,
            request_digest=row.input_snapshot["request_digest"],
            run_id=None,
            result={"id": str(view.id), "revision": view.revision, "status": "draft"},
        )
    )
    s.add_row(
        Audit(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            receipt_id=receipt.id,
            actor_id=view.owner_id,
            operation=operation,
        )
    )
    s.add_row(
        Outbox(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            receipt_id=receipt.id,
            actor_id=view.owner_id,
            type=service.EVENTS[operation],
            subject_id=view.id,
            subject_revision=view.revision,
            correlation_id=command.command_id,
        )
    )
    s.add_row(
        RequestKey(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            actor_id=view.owner_id,
            receipt_id=receipt.id,
            key=command.idempotency_key,
            digest=receipt.request_digest,
        )
    )
    return row


@pytest.fixture
def world(request, monkeypatch):
    case = request.getfixturevalue("publication_case")
    engine = create_engine("postgresql+psycopg://unused/never_connect")
    engine._pdos_change_store = object()  # Native sources use their actual registration reader.

    @event.listens_for(engine, "do_connect")
    def no_connection(*_args):
        raise AssertionError("Pure material owner must never connect")

    s = SelectSession(engine)
    s.begin()
    ctx = Context(case.scope.tenant_id, case.owner, case.owner, category_id=case.category)
    s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    pid, project_id = case.scope.product_id, case.scope.project_id
    s.add_row(
        Principal(id=case.owner, tenant_id=ctx.tenant_id, kind="human", active=True, access_epoch=1)
    )
    s.add_row(
        Grant(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=case.category,
            principal_id=case.owner,
            can_write=True,
            access_epoch=1,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    product = s.add_row(
        Product(
            id=pid,
            tenant_id=ctx.tenant_id,
            category_id=case.category,
            revision=7,
            visibility="private",
        )
    )
    definition = s.add_row(
        DefinitionRevision(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            owner_id=case.owner,
            revision=1,
            title="native fixed definition",
            purpose=case.payload.purpose,
            status="draft",
            visibility="private",
            sealed=True,
            use_cases=[],
            requirements=[],
            constraints=[],
            unknowns=[],
            exclusions=[],
            change_reason="explicit fixture",
            created_at=datetime.now(UTC),
        )
    )
    definition.category_id = case.category
    project = s.add_row(
        Project(
            id=project_id,
            tenant_id=ctx.tenant_id,
            product_id=pid,
            owner_id=case.owner,
            purpose=case.payload.purpose,
            scope="native fixed project",
            status="active",
            visibility="private",
            revision=1,
        )
    )
    s.add_row(
        ProjectProductLink(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            project_id=project_id,
            definition_id=definition.id,
            definition_revision=1,
            variant_id=None,
            scope="fixed",
        )
    )
    bom = s.add_row(
        BomRevision(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            owner_id=case.owner,
            name="native empty BOM",
            status="draft",
            visibility="private",
            revision=1,
            series_id=uuid4(),
            sources=[],
            required_source_read_set=[],
            created_at=datetime.now(UTC),
        )
    )
    engineering = s.add_row(
        EngineeringConfiguration(
            id=UUID(case.material.process_snapshot["engineering_configuration_id"]),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            owner_id=case.owner,
            name="fixed engineering",
            status="draft",
            visibility="private",
            revision=2,
            series_id=uuid4(),
            definition_id=definition.id,
            definition_revision=1,
            bom_id=bom.id,
            bom_revision=1,
            design_versions={},
            sources=[],
            required_source_read_set=[
                case.read_only.model_dump(mode="json", include={"artifact_id", "expected_revision"})
            ],
            created_at=datetime.now(UTC),
        )
    )
    raw = case.material.process_snapshot
    process = s.add_row(
        ProcessRevision(
            id=UUID(raw["id"]),
            tenant_id=ctx.tenant_id,
            product_id=pid,
            owner_id=case.owner,
            name=raw["name"],
            status="draft",
            visibility="private",
            revision=raw["revision"],
            series_id=uuid4(),
            engineering_configuration_id=engineering.id,
            engineering_revision=2,
            operations=deepcopy(raw["operations"]),
            site=raw["site"],
            line=raw["line"],
            sources=deepcopy(raw["sources"]),
            required_source_read_set=deepcopy(raw["required_source_read_set"]),
            created_at=datetime.now(UTC),
        )
    )
    sources = tuple(
        dict.fromkeys(
            (
                *schemas.sources_of(case.payload),
                *case.material.baseline.sources,
                *(v for view in case.material.documents for v in view.sources),
                *(schemas.Source.model_validate(v) for v in raw["sources"]),
                case.read_only,
            )
        )
    )
    for source in sources:
        content = "preamble\n" + source.quote
        artifact = s.add_row(
            Artifact(
                id=source.artifact_id,
                tenant_id=ctx.tenant_id,
                product_id=pid,
                owner_id=case.owner,
                title="native registered source",
                visibility="private",
                revision=1,
                status="active",
                original_id=None,
                content=content,
                content_hash=digest(content),
            )
        )
        artifact.category_id = case.category
        registration = s.add_row(
            Receipt(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                product_id=pid,
                actor_id=case.owner,
                requester_id=case.owner,
                command_id=uuid4(),
                operation="evidence.artifact.register",
                subject_type="artifact",
                subject_id=artifact.id,
                subject_revision=1,
                visibility="private",
                request_digest=digest(str(artifact.id)),
                intent_digest=digest("native origin"),
                run_id=None,
                result={"id": str(artifact.id), "revision": 1, "status": "active"},
            )
        )
        registration.category_id = case.category

    # Only the historical professional IO is substituted. It never grants the
    # publisher authority; actual caller/retained UOW and all content IO remain.
    def retained(_s, _ctx, _pid, _project, saved, *, at):
        assert _s is s and _ctx is ctx and _pid == pid and _project == project_id
        return {"current": True}

    monkeypatch.setattr(service, "_recheck", retained)
    views = (case.material.baseline, *case.material.documents)
    rows = {}
    for view in views:
        row = _saved_preparation(s, ctx, pid, view)
        row.source_basis = service.evidence._evidence(
            s,
            ctx,
            pid,
            row.required_source_read_set,
            service.source_refs(
                schemas.PAYLOADS[row.operation].model_validate(row.input_snapshot["semantic"])
            ),
        )[0]
        rows[row.id] = row
    declaration = schemas.BaselinePayload.model_validate(case.material.baseline.body["input"])
    for operation in declaration.operations:
        for kind in ("work_instruction", "control_plan"):
            child = getattr(operation, kind)
            s.add_row(
                models.BaselineDocumentLink(
                    id=uuid4(),
                    tenant_id=ctx.tenant_id,
                    product_id=pid,
                    project_id=project_id,
                    baseline_id=case.material.baseline.id,
                    baseline_revision=1,
                    process_id=process.id,
                    process_revision=process.revision,
                    operation_key=operation.operation_key,
                    document_kind=kind,
                    document_id=child.id,
                    document_revision=child.revision,
                )
            )
    owner = ActualPublicationMaterialOwner(engine)
    work = SimpleNamespace(
        s=s,
        ctx=ctx,
        pid=pid,
        payload=case.payload,
        case=case,
        owner=owner,
        product=product,
        project=project,
        process=process,
        engineering=engineering,
        rows=rows,
    )
    work.read = lambda: owner.read(s, work.ctx, pid, work.payload)
    yield work
    s.close()
    engine.dispose()


def rejects(call, reason):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == reason


def test_actual_fixed_readers_build_complete_native_material_and_opaque_refresh(world):
    value = world.read()
    assert value.material.scope == world.case.scope
    assert value.material.baseline.id == world.case.material.baseline.id
    assert len(value.material.documents) == 4
    assert world.case.read_only.artifact_id in {
        v.artifact_id for v in value.required_source_read_set
    }
    assert all(
        v["source_origin"] == "registered_native_text"
        for v in value.source_basis["artifact_sources"]
    )
    refreshed = world.owner.refresh(world.s, world.ctx, world.pid, world.payload, value)
    assert refreshed is not value and refreshed.material == value.material
    assert refreshed.checked_at >= value.checked_at
    assert not (world.s.new or world.s.dirty or world.s.deleted)


def test_fixed_history_drift_keeps_fixed_process_and_documents(world):
    newer = deepcopy(world.process)
    newer.id, newer.revision = uuid4(), world.process.revision + 1
    world.s.add_row(newer)
    child = next(row for row in world.rows.values() if row.kind == "work_instruction")
    pointer = next(v for v in world.s.rows[models.PreparationCurrent] if v.version_id == child.id)
    pointer.version_id, pointer.revision = uuid4(), pointer.revision + 1
    value = world.read()
    assert value.material.current_process.id == newer.id
    assert value.material.baseline.process.id == world.process.id
    plan = publication_rules.prepare_publication(world.payload, value.material)
    assert {"process_reference_drift", "document_reference_drift"} <= {v.code for v in plan.gaps}


@pytest.mark.parametrize(
    "fault", ("purpose", "category", "baseline_scope", "document_scope", "engineering")
)
def test_actual_scope_or_fixed_binding_mismatch_rejected(world, fault):
    if fault == "purpose":
        world.payload = world.payload.model_copy(update={"purpose": "other purpose"})
    elif fault == "category":
        world.product.category_id = uuid4()
    elif fault == "baseline_scope":
        world.payload = world.payload.model_copy(update={"project_id": uuid4()})
    elif fault == "document_scope":
        child = next(row for row in world.rows.values() if row.kind == "work_instruction")
        child.project_id = uuid4()
    else:
        world.engineering.definition_id = uuid4()
    with pytest.raises(DomainError):
        world.read()


def test_actual_withdrawn_original_cannot_be_a_drift_warning(world):
    world.s.rows[Artifact][0].status = "withdrawn"
    rejects(world.read, "SOURCE_UNAVAILABLE")


def test_actual_whole_line_quote_change_is_not_satisfied_by_saved_labels(world):
    source = world.payload.sources[0]
    changed = source.model_copy(update={"quote": "not the registered line"})
    world.payload = world.payload.model_copy(update={"sources": (changed,)})
    rejects(world.read, "MISSING_REQUIRED_EVIDENCE")


def test_last_source_io_change_rejects_previously_read_project(world, monkeypatch):
    original = service.evidence._evidence
    changed = False

    def evidence(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        refs = args[4] if len(args) > 4 else kwargs.get("sources", ())
        if not changed and any(value.id == world.payload.sources[0].artifact_id for value in refs):
            world.project.revision += 1
            changed = True
        return result

    monkeypatch.setattr(service.evidence, "_evidence", evidence)
    rejects(world.read, "SOURCE_STALE")


def test_final_actual_caller_gate_rejects_expiry_after_source_io(world, monkeypatch):
    original = service.evidence._evidence

    def evidence(*args, **kwargs):
        result = original(*args, **kwargs)
        refs = args[4] if len(args) > 4 else kwargs.get("sources", ())
        if any(value.id == world.payload.sources[0].artifact_id for value in refs):
            world.s.rows[Grant][0].expires_at = datetime.now(UTC) - timedelta(microseconds=1)
        return result

    monkeypatch.setattr(service.evidence, "_evidence", evidence)
    rejects(world.read, "FORBIDDEN_SCOPE")


@pytest.mark.parametrize(
    "fault", ("forged", "body", "source_basis", "caller", "transaction", "payload")
)
def test_refresh_requires_exact_owner_handle_and_original_actual_binding(world, fault):
    value = world.read()
    if fault == "forged":
        value = replace(value)
    elif fault == "body":
        value.material.baseline.body["input"]["reason"] = "tampered"
    elif fault == "source_basis":
        value.source_basis["artifact_sources"].clear()
    elif fault == "caller":
        world.ctx = replace(world.ctx, actor_id=uuid4(), requester_id=uuid4())
    elif fault == "transaction":
        world.s.rollback()
        world.s.begin()
    else:
        world.payload = world.payload.model_copy(update={"reason": "different actual content"})
    with pytest.raises(DomainError):
        world.owner.refresh(world.s, world.ctx, world.pid, world.payload, value)


def test_refresh_rechecks_later_actual_source_revision(world):
    value = world.read()
    world.s.rows[Artifact][0].revision += 1
    with pytest.raises(DomainError):
        world.owner.refresh(world.s, world.ctx, world.pid, world.payload, value)
