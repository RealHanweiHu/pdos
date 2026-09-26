"""Named learning from actual tests and service cases to inherited product definitions."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, or_, select

from app.ai.project_discussion_sources import linked_definitions
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.document_previews import document_row, metadata
from app.domain.experiment_feedback import field_values
from app.domain.product_definitions import _row as definition_row
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _plain,
    _role,
    _space,
    digest,
)
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_result_source import ncr_source

SourceKind = Literal["test_run", "complaint", "ncr"]


class ResultOptions(Contract):
    definition_id: UUID
    project_id: UUID | None = None
    source_kind: SourceKind = "test_run"
    search: str = Field(default="", max_length=128)
    before_id: UUID | None = None


class ResultRead(Contract):
    definition_id: UUID
    project_id: UUID
    source_kind: SourceKind
    source_id: UUID
    before_version: int | None = Field(default=None, ge=1)


class ResultHistory(Contract):
    definition_id: UUID
    before_id: UUID | None = None


class ResultSave(ResultRead):
    request_id: UUID
    expected_digest: Digest
    expected_version: int = Field(ge=0)
    field_paths: tuple[str, ...] = Field(min_length=1, max_length=20)
    verdict: Literal["adopt_for_followup", "reject_application", "needs_evidence", "withdrawn"]
    finding: Text
    proposed_change: Text
    limitations: Text
    applicability_basis: Text

    @model_validator(mode="after")
    def valid(self) -> Self:
        if len(set(self.field_paths)) != len(self.field_paths) or any(
            not p or len(p) > 1024 for p in self.field_paths
        ):
            raise ValueError("请选择不重复的实际定义字段")
        if self.before_version is not None or (
            self.verdict == "withdrawn" and self.expected_version == 0
        ):
            raise ValueError("保存不接受历史翻页，首条反馈不能撤回")
        return self


def project_access(c: Connection, context: AuthContext, project: UUID) -> None:
    try:
        ProjectAccessService(SqlProjectAccessRepository(c.engine)).authorize(
            context=context, project_id=project, action=Action.QUALITY_VIEW
        )
    except ObjectPermissionDeniedError as error:
        raise ProductWorkAccessError("需同时有权读取原项目质量资料和产品定义") from error


def target(
    c: Connection, context: AuthContext, space: UUID, identity: UUID, *, write: bool = False
) -> Any:
    _space(
        c,
        context,
        space,
        access="manager" if write else "viewer",
        lock=write,
        allow_archived=not write,
    )
    row = definition_row(c, context, space, identity)
    if row["state"] != "published":
        raise ProductWorkError("请选择本项目实际继承的已发布定义")
    if write:
        _role(context, Action.PRODUCT_WORK_MANAGE)
        _line(c, context, space, row["product_line_id"], access="manager", writable=True)
    return row


def scoped_row(
    c: Connection, context: AuthContext, project: UUID, table: Any, identity: UUID
) -> Any:
    row = (
        c.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.project_id == project,
                table.c.id == identity,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("来源不存在或不属于当前项目")
    return row


def actual_source(c: Connection, context: AuthContext, query: ResultRead) -> dict[str, Any]:
    project_access(c, context, query.project_id)
    if query.source_kind == "ncr":
        return ncr_source(c, context, query.project_id, query.source_id)
    table = tables.test_runs if query.source_kind == "test_run" else tables.complaints
    row = scoped_row(c, context, query.project_id, table, query.source_id)
    body: dict[str, Any] = {"kind": query.source_kind, "record": _plain(row)}
    docs: list[UUID] = []
    warnings: list[str] = []
    if query.source_kind == "test_run":
        if row["draft_state"] != "confirmed" or row["status"] not in {
            "passed",
            "failed",
            "aborted",
        }:
            raise ProductWorkError("仅已确认的完成/失败/中止逐次测试可作为实际反馈来源")
        case = scoped_row(c, context, query.project_id, tables.test_cases, row["test_case_id"])
        body["test_case"] = _plain(case)
        body["test_plan"] = _plain(
            scoped_row(c, context, query.project_id, tables.test_plans, case["plan_id"])
        )
        spec = (
            scoped_row(
                c, context, query.project_id, tables.specifications, case["specification_id"]
            )
            if case["specification_id"]
            else None
        )
        body["specification"] = _plain(spec) if spec is not None else None
        links = tables.definition_requirement_links
        body["inherited_specifications"] = (
            [
                _plain(v)
                for v in c.execute(
                    select(links).where(
                        links.c.tenant_id == context.tenant.id,
                        links.c.definition_id == query.definition_id,
                        links.c.requirement_id == spec["requirement_id"],
                    )
                ).mappings()
            ]
            if spec is not None and spec["requirement_id"]
            else []
        )
        if not body["inherited_specifications"]:
            warnings.append(
                "本次测试未沿规格/需求直接对应此定义条目；须人工说明适用范围，不视为已验证定义。"
            )
        body["sample"] = (
            _plain(scoped_row(c, context, query.project_id, tables.samples, row["sample_id"]))
            if row["sample_id"]
            else None
        )
        revision = tables.sample_configuration_revisions
        configuration = (
            c.execute(
                select(revision).where(
                    revision.c.tenant_id == context.tenant.id,
                    revision.c.project_id == query.project_id,
                    revision.c.id == row["sample_configuration_revision_id"],
                )
            )
            .mappings()
            .one_or_none()
            if row["sample_configuration_revision_id"]
            else None
        )
        body["sample_configuration"] = _plain(configuration) if configuration is not None else None
        if row["evidence_document_id"]:
            docs.append(row["evidence_document_id"])
        if not row["metrics"]:
            warnings.append("本次测试未登记结构化实测指标，仅保留原判定和说明，不能补造数值。")
        if row["status"] == "aborted":
            warnings.append("原测试已中止，不构成通过或失败验证结论。")
    else:
        docs = [UUID(v) for v in row["document_refs"]]
        if row["status"] not in {"resolved", "closed"}:
            warnings.append("原投诉仍在办理，现象/客户陈述尚不代表确认根因或有效整改。")
        warnings.append("投诉不是失效率；没有出货量、观察范围和一致口径，不推算发生率或因果。")
    body["evidence"] = []
    body["missing_evidence"] = []
    for identity in dict.fromkeys(docs):
        try:
            body["evidence"].append(
                metadata(document_row(c, context.tenant.id, query.project_id, identity))
            )
        except LookupError:
            body["missing_evidence"].append(str(identity))
            warnings.append(f"原依据 {identity} 已不可读取，保留缺项。")
    body["warnings"] = warnings
    return body


def prepared(
    c: Connection, context: AuthContext, space: UUID, query: ResultRead, *, write: bool = False
) -> dict[str, Any]:
    definition = target(c, context, space, query.definition_id, write=write)
    project_access(c, context, query.project_id)
    inherited = bool(linked_definitions(c, context, query.project_id, [query.definition_id]))
    if write and not inherited:
        raise ProductWorkAccessError("定义不是此项目当前实际需求继承的来源")
    source = actual_source(c, context, query)
    body = {
        "definition": _plain(definition),
        "fields": field_values("definition", definition),
        "source": source,
        "policy_version": "product-result-learning.v1",
        "inheritance_current": inherited,
    }
    return {**body, "digest": digest(body)}


def conditions(context: AuthContext, query: ResultRead) -> tuple[Any, ...]:
    t = tables.product_result_feedback
    return (
        t.c.tenant_id == context.tenant.id,
        t.c.definition_id == query.definition_id,
        t.c.project_id == query.project_id,
        t.c.source_kind == query.source_kind,
        t.c.source_id == query.source_id,
    )


class ProductResultFeedbackService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def history(self, context: AuthContext, space: UUID, query: ResultHistory) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            target(c, context, space, query.definition_id)
            t, users = tables.product_result_feedback, tables.users
            q = (
                select(t, users.c.display_name.label("actor_name"))
                .join(
                    users, (users.c.tenant_id == t.c.tenant_id) & (users.c.id == t.c.actor_user_id)
                )
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.market_space_id == space,
                    t.c.definition_id == query.definition_id,
                )
            )
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            items = []
            for row in values[:20]:
                original = ResultRead(
                    definition_id=query.definition_id,
                    project_id=row["project_id"],
                    source_kind=row["source_kind"],
                    source_id=row["source_id"],
                )
                try:
                    project_access(c, context, row["project_id"])
                    current = prepared(c, context, space, original)
                    unchanged = current["digest"] == row["source_digest"]
                    inheritance = current["inheritance_current"]
                except PermissionError:
                    continue
                except (ValueError, LookupError):
                    unchanged, inheritance = False, False
                latest = c.execute(
                    select(func.max(t.c.version)).where(*conditions(context, original))
                ).scalar_one()
                items.append(
                    {
                        **_plain(row),
                        "sources_current": unchanged,
                        "inheritance_current": inheritance,
                        "is_latest": row["version"] == latest,
                    }
                )
            return {
                "items": items,
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def options(self, context: AuthContext, space: UUID, query: ResultOptions) -> dict[str, Any]:
        with self.engine.connect() as c:
            target(c, context, space, query.definition_id)
            if query.project_id is None:
                p, cases, links, inherited = (
                    tables.projects,
                    tables.development_cases,
                    tables.case_requirement_links,
                    tables.definition_requirement_links,
                )
                requirements = select(inherited.c.requirement_id).where(
                    inherited.c.tenant_id == context.tenant.id,
                    inherited.c.definition_id == query.definition_id,
                )
                q = (
                    select(p)
                    .join(
                        cases,
                        (cases.c.tenant_id == p.c.tenant_id)
                        & (cases.c.id == p.c.development_case_id),
                    )
                    .where(
                        p.c.tenant_id == context.tenant.id,
                        or_(
                            cases.c.requirement_id.in_(requirements),
                            cases.c.id.in_(
                                select(links.c.case_id).where(
                                    links.c.tenant_id == context.tenant.id,
                                    links.c.requirement_id.in_(requirements),
                                )
                            ),
                        ),
                    )
                )
                table, title = p, p.c.name
            else:
                project_access(c, context, query.project_id)
                if not linked_definitions(c, context, query.project_id, [query.definition_id]):
                    raise ProductWorkAccessError("项目与定义当前没有实际需求继承关系")
                table = {
                    "test_run": tables.test_runs,
                    "complaint": tables.complaints,
                    "ncr": tables.nonconformance_reports,
                }[query.source_kind]
                q = select(table).where(
                    table.c.tenant_id == context.tenant.id, table.c.project_id == query.project_id
                )
                if query.source_kind == "test_run":
                    case = tables.test_cases
                    q = (
                        q.add_columns(case.c.title.label("source_title"))
                        .join(
                            case,
                            (case.c.tenant_id == table.c.tenant_id)
                            & (case.c.id == table.c.test_case_id),
                        )
                        .where(
                            table.c.draft_state == "confirmed",
                            table.c.status.in_(["passed", "failed", "aborted"]),
                        )
                    )
                    title = case.c.title
                elif query.source_kind == "ncr":
                    title = table.c.nonconformity
                    q = q.add_columns(title.label("source_title"))
                else:
                    title = table.c.title
            if query.search:
                q = q.where(title.icontains(query.search, autoescape=True))
            if query.before_id:
                q = q.where(table.c.id < query.before_id)
            values = c.execute(q.order_by(table.c.id.desc()).limit(21)).mappings().all()
            items = []
            for row in values[:20]:
                if query.project_id is None:
                    try:
                        project_access(c, context, row["id"])
                        if not linked_definitions(c, context, row["id"], [query.definition_id]):
                            continue
                    except PermissionError:
                        continue
                    items.append({"id": str(row["id"]), "title": row["name"]})
                else:
                    items.append(
                        {
                            "id": str(row["id"]),
                            "title": row.get("source_title", row.get("title", "")),
                            "status": row["status"],
                            "run_number": row.get("run_number"),
                            "time": _plain(row).get(
                                "executed_at",
                                _plain(row).get("occurred_at", _plain(row).get("created_at")),
                            ),
                        }
                    )
            return {
                "items": items,
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def read(self, context: AuthContext, space: UUID, query: ResultRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            source = prepared(c, context, space, query)
            can_respond = source["inheritance_current"]
            try:
                target(c, context, space, query.definition_id, write=True)
            except (ValueError, PermissionError):
                can_respond = False
            t = tables.product_result_feedback
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(*conditions(context, query))
            ).scalar_one()
            users = tables.users
            q = (
                select(t, users.c.display_name.label("actor_name"))
                .join(
                    users, (users.c.tenant_id == t.c.tenant_id) & (users.c.id == t.c.actor_user_id)
                )
                .where(*conditions(context, query))
            )
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            values = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            return {
                "source": source,
                "can_respond": can_respond,
                "version": version,
                "items": [
                    {**_plain(v), "sources_current": v["source_digest"] == source["digest"]}
                    for v in values[:20]
                ],
                "next_before_version": values[19]["version"] if len(values) > 20 else None,
            }

    def save(self, context: AuthContext, space: UUID, command: ResultSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            project_access(c, context, command.project_id)
            if not lock_project_write_scope(
                c, tenant_id=context.tenant.id, project_id=command.project_id
            ):
                raise ProductWorkError("原项目不可用")
            current = prepared(c, context, space, command, write=True)
            signature = digest({"space": str(space), "command": command.model_dump(mode="json")})
            t = tables.product_result_feedback
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写反馈")
                return _plain(prior)
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(*conditions(context, command))
            ).scalar_one()
            if version != command.expected_version or current["digest"] != command.expected_digest:
                raise ProductWorkError("来源、定义或反馈已变化，请重新核对")
            fields = {v["path"]: v for v in current["fields"]}
            if not set(command.field_paths).issubset(fields):
                raise ProductWorkError("请选择当前实际定义字段")
            if command.verdict == "adopt_for_followup" and (
                not current["source"]["evidence"] or current["source"]["missing_evidence"]
            ):
                raise ProductWorkError("采用须有实际原依据；请先沿原测试/投诉补证，再核对反馈")
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        definition_id=command.definition_id,
                        project_id=command.project_id,
                        source_kind=command.source_kind,
                        source_id=command.source_id,
                        test_run_id=command.source_id
                        if command.source_kind == "test_run"
                        else None,
                        complaint_id=command.source_id
                        if command.source_kind == "complaint"
                        else None,
                        ncr_id=command.source_id if command.source_kind == "ncr" else None,
                        version=version + 1,
                        verdict=command.verdict,
                        selected_fields=[fields[p] for p in command.field_paths],
                        finding=command.finding,
                        proposed_change=command.proposed_change,
                        limitations=command.limitations,
                        applicability_basis=command.applicability_basis,
                        source_snapshot=current,
                        source_digest=current["digest"],
                        actor_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=c.execute(select(func.clock_timestamp())).scalar_one(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _emit(
                c,
                context,
                space,
                "product_result_feedback",
                "recorded",
                {
                    "id": row["id"],
                    "version": row["version"],
                    "definition_id": row["definition_id"],
                },
            )
            return _plain(row)
