"""Evidence-bound supplier engineering observations and reproducible project metrics."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, DateTime, Engine, cast, func, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest


class TimedEvidence(Contract):
    at: AwareDatetime
    evidence_id: UUID
    location: Text


class EngineeringDraft(Contract):
    kind: Literal["sample_delivery", "technical_response", "engineering_failure"]
    source_reference: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=256)
    status: Literal["active", "withdrawn"] = "active"
    requested: TimedEvidence | None = None
    promised: TimedEvidence | None = None
    responded: TimedEvidence | None = None
    received: TimedEvidence | None = None
    detected: TimedEvidence | None = None
    build_id: UUID | None = None
    issue_id: UUID | None = None
    test_run_id: UUID | None = None
    evidence_id: UUID
    reason: Text

    @model_validator(mode="after")
    def consistent(self) -> "EngineeringDraft":
        if not self.source_reference.strip() or not self.title.strip():
            raise ValueError("请填写实际来源编号和事项名称")
        if self.kind == "engineering_failure":
            if not self.detected or not self.issue_id:
                raise ValueError("历史失效记录须有实际发现证据和原问题")
            if any((self.requested, self.promised, self.responded, self.received)):
                raise ValueError("失效记录不填写样品或响应时间")
        else:
            if not self.requested or self.detected:
                raise ValueError("样品和技术响应须有原请求证据")
            if self.kind == "technical_response" and (self.received or self.promised):
                raise ValueError("技术响应记录不填写样品交期")
            for fact in (self.responded, self.received):
                if fact and fact.at < self.requested.at:
                    raise ValueError("实际响应或收样不能早于请求")
            if self.promised and self.promised.at < self.requested.at:
                raise ValueError("承诺交付不能早于原请求")
        for fact in (self.requested, self.responded, self.received, self.detected):
            if fact and fact.at > datetime.now(UTC):
                raise ValueError("实际发生时间不能填写未来时间")
        return self


class EngineeringApply(EngineeringDraft):
    expected_version: int = Field(ge=0)
    expected_digest: Digest
    request_id: UUID


def current_query(tenant: UUID, project: UUID, supplier: UUID) -> Any:
    t = tables.supplier_engineering_records
    newer = t.alias("newer_engineering_record")
    return select(t).where(
        t.c.tenant_id == tenant,
        t.c.project_id == project,
        t.c.supplier_id == supplier,
        ~select(newer.c.id)
        .where(
            newer.c.tenant_id == t.c.tenant_id,
            newer.c.project_id == t.c.project_id,
            newer.c.record_id == t.c.record_id,
            newer.c.version > t.c.version,
        )
        .correlate(t)
        .exists(),
    )


def metric_query(tenant: UUID, project: UUID, supplier: UUID) -> Any:
    rows = current_query(tenant, project, supplier).subquery()

    def at(field: str) -> Any:
        return cast(rows.c.payload[field]["at"].as_string(), DateTime(timezone=True))

    requested, received, responded = at("requested"), at("received"), at("responded")
    first_promise = cast(
        rows.c.snapshot["first_promise"]["at"].as_string(), DateTime(timezone=True)
    )
    sample = rows.c.kind == "sample_delivery"
    response = rows.c.kind == "technical_response"
    comparable = sample & received.is_not(None) & first_promise.is_not(None)
    return (
        select(
            func.count().filter(sample).label("sample_records"),
            func.count().filter(sample & received.is_not(None)).label("received_samples"),
            func.count().filter(comparable).label("comparable_deliveries"),
            func.count()
            .filter(comparable & (received <= first_promise))
            .label("on_time_deliveries"),
            func.avg(func.extract("epoch", received - requested) / 86400)
            .filter(sample)
            .label("mean_delivery_elapsed_days"),
            func.count().filter(response).label("response_records"),
            func.count().filter(response & responded.is_not(None)).label("responded_records"),
            func.avg(func.extract("epoch", responded - requested) / 3600)
            .filter(response)
            .label("mean_first_response_elapsed_hours"),
            func.count()
            .filter(rows.c.kind == "engineering_failure")
            .label("reported_failure_records"),
        )
        .select_from(rows)
        .where(rows.c.status == "active")
    )


def supplier_row(c: Connection, tenant: UUID, supplier: UUID) -> dict[str, Any]:
    s = tables.suppliers
    row = (
        c.execute(select(s).where(s.c.tenant_id == tenant, s.c.id == supplier))
        .mappings()
        .one_or_none()
    )
    if not row:
        raise ProductWorkError("供方不存在或不属于本租户")
    return _plain(dict(row))


def sources(
    c: Connection, tenant: UUID, project: UUID, command: EngineeringDraft
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "evidence": metadata(document_row(c, tenant, project, command.evidence_id))
    }
    for key in ("requested", "promised", "responded", "received", "detected"):
        fact = getattr(command, key)
        if fact:
            result[key] = {
                **fact.model_dump(mode="json"),
                "document": metadata(document_row(c, tenant, project, fact.evidence_id)),
            }
    for key, table in (
        ("build_id", tables.build_batches),
        ("issue_id", tables.issues),
        ("test_run_id", tables.test_runs),
    ):
        identity = getattr(command, key)
        if identity:
            row = NpiExecutionService._row(
                c, table, tenant_id=tenant, project_id=project, record_id=identity
            )
            result[key] = _plain(dict(row))
    return result


def preview(
    c: Connection,
    context: AuthContext,
    project: UUID,
    supplier: UUID,
    record: UUID,
    command: EngineeringDraft,
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    t = tables.supplier_engineering_records
    current = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.record_id == record,
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    actual_supplier = supplier_row(c, context.tenant.id, supplier)
    if current:
        if (
            current["supplier_id"] != supplier
            or current["kind"] != command.kind
            or current["source_reference"] != command.source_reference
        ):
            raise ProductWorkError("原供方、事项类型和来源编号固定；错误关联请撤回后另建")
    elif actual_supplier["status"] != "active" or command.status == "withdrawn":
        raise ProductWorkError("新增须使用启用的供方和有效事项")
    duplicate = c.execute(
        select(t.c.record_id)
        .where(
            t.c.tenant_id == context.tenant.id,
            t.c.project_id == project,
            t.c.supplier_id == supplier,
            t.c.kind == command.kind,
            t.c.source_reference == command.source_reference,
            t.c.record_id != record,
        )
        .limit(1)
    ).scalar_one_or_none()
    if duplicate:
        raise ProductWorkError(f"该来源已有记录，请沿原记录修订：{duplicate}")
    actual_sources = sources(c, context.tenant.id, project, command)
    first_promise = (
        current["snapshot"].get("first_promise") if current else None
    ) or actual_sources.get("promised")
    basis = {
        "supplier": actual_supplier,
        "sources": actual_sources,
        "first_promise": first_promise,
        "previous_version": current["version"] if current else 0,
        "command": command.model_dump(
            mode="json", exclude={"request_id", "expected_version", "expected_digest"}
        ),
    }
    return {"basis": basis, "digest": digest(basis)}


class SupplierEngineeringService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        supplier: UUID | None = None,
        after: UUID | None = None,
        record: UUID | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            s, d = tables.suppliers, tables.documents
            options: dict[str, Any] = {}
            for name, table in (
                ("builds", tables.build_batches),
                ("issues", tables.issues),
                ("tests", tables.test_runs),
            ):
                options[name] = [
                    _plain(dict(row))
                    for row in c.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.project_id == project,
                        )
                        .order_by(table.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ]
            result: dict[str, Any] = {
                "suppliers": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(s).where(s.c.tenant_id == context.tenant.id).order_by(s.c.code)
                    ).mappings()
                ],
                "documents": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(d.c.id, d.c.filename)
                        .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project)
                        .order_by(d.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ],
                "options": options,
                "items": [],
                "history": [],
                "next_cursor": None,
                "metrics": None,
            }
            if supplier is None:
                return result
            result["supplier"] = supplier_row(c, context.tenant.id, supplier)
            result["metrics"] = _plain(
                dict(c.execute(metric_query(context.tenant.id, project, supplier)).mappings().one())
            )
            t = tables.supplier_engineering_records
            query = current_query(context.tenant.id, project, supplier)
            if record:
                query = query.where(t.c.record_id == record)
                result["history"] = [
                    _plain(dict(row))
                    for row in c.execute(
                        select(t)
                        .where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.project_id == project,
                            t.c.supplier_id == supplier,
                            t.c.record_id == record,
                        )
                        .order_by(t.c.version.desc())
                        .limit(20)
                    ).mappings()
                ]
            elif after:
                query = query.where(t.c.record_id > after)
            rows = list(c.execute(query.order_by(t.c.record_id).limit(21)).mappings())
            result["items"] = [_plain(dict(row)) for row in rows[:20]]
            result["next_cursor"] = str(rows[19]["record_id"]) if len(rows) > 20 else None
            return result

    def preview(
        self,
        context: AuthContext,
        project: UUID,
        supplier: UUID,
        record: UUID,
        command: EngineeringDraft,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, supplier, record, command)

    def apply(
        self,
        context: AuthContext,
        project: UUID,
        supplier: UUID,
        record: UUID,
        command: EngineeringApply,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "supplier": str(supplier),
                "record": str(record),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.supplier_engineering_records
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("原请求已用于不同供方工程记录")
                return _plain(dict(prior))
            observed = preview(c, context, project, supplier, record, command)
            if (
                observed["digest"] != command.expected_digest
                or observed["basis"]["previous_version"] != command.expected_version
            ):
                raise ProductWorkError("原记录、供方或证据已变化，请重新预览")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        supplier_id=supplier,
                        record_id=record,
                        version=command.expected_version + 1,
                        kind=command.kind,
                        source_reference=command.source_reference,
                        status=command.status,
                        payload=command.model_dump(
                            mode="json",
                            exclude={"expected_version", "expected_digest", "request_id"},
                        ),
                        snapshot=observed["basis"],
                        evidence_id=command.evidence_id,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=record,
                record_type="supplier_engineering_record",
                action=command.status,
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
