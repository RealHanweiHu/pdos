"""Learning from an actual product retirement, without changing lifecycle decisions."""

from typing import Any, Literal, Self, cast
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, SourceRef, Text
from app.db.schema import tables
from app.domain.experiment_feedback import TargetKind, field_values
from app.domain.product_catalog import _node_row
from app.domain.product_evidence import evidence_quality
from app.domain.product_workspace import (
    ProductWorkError,
    _emit,
    _line,
    _plain,
    _role,
    _sources,
    _space,
    digest,
)


class RetirementOptions(Contract):
    product_id: UUID
    retirement_audit_id: int | None = Field(default=None, ge=1)
    before_audit_id: int | None = Field(default=None, ge=1)
    before_definition_id: UUID | None = None


class RetirementRead(Contract):
    product_id: UUID
    retirement_audit_id: int = Field(ge=1)
    definition_id: UUID | None = None
    before_version: int | None = Field(default=None, ge=1)


class RetirementSave(RetirementRead):
    request_id: UUID
    expected_digest: Digest
    expected_version: int = Field(ge=0)
    field_paths: tuple[str, ...] = Field(min_length=1, max_length=20)
    verdict: Literal["adopt_for_followup", "retain_assumption", "needs_evidence", "withdrawn"]
    finding: Text
    follow_up: Text
    limitations: Text
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (
            self.before_version is not None
            or len(set(self.field_paths)) != len(self.field_paths)
            or any(not p or len(p) > 1024 for p in self.field_paths)
        ):
            raise ValueError("请选择不重复的实际字段，保存不接受历史翻页")
        if self.verdict == "withdrawn" and not self.expected_version:
            raise ValueError("尚无退市反馈可撤回")
        return self


def product(
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
    row = _node_row(c, context, space, identity)
    _line(c, context, space, row["product_line_id"], access="manager" if write else "viewer")
    if write:
        _role(context, Action.PRODUCT_WORK_MANAGE)
    return row


def retirement_query(context: AuthContext, space: UUID, identity: UUID) -> Any:
    a = tables.audit_log
    return select(a).where(
        a.c.tenant_id == context.tenant.id,
        a.c.entity_id == identity,
        a.c.project_id.is_(None),
        a.c.action == "product_node.updated",
        a.c.after_snapshot["market_space_id"].as_string() == str(space),
        a.c.before_snapshot["lifecycle"].as_string().is_not(None),
        a.c.before_snapshot["lifecycle"].as_string() != "retired",
        a.c.after_snapshot["lifecycle"].as_string() == "retired",
    )


def retirement(
    c: Connection, context: AuthContext, space: UUID, identity: UUID, audit_id: int
) -> Any:
    row = (
        c.execute(
            retirement_query(context, space, identity).where(tables.audit_log.c.id == audit_id)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("须选择此产品真实登记的退市变更；不能由当前状态推造历史原因")
    return row


def definitions(context: AuthContext, space: UUID, identity: UUID, audit: Any) -> Any:
    d = tables.product_definitions
    return select(d).where(
        d.c.tenant_id == context.tenant.id,
        d.c.market_space_id == space,
        d.c.product_id == identity,
        d.c.state == "published",
        d.c.published_at <= audit["timestamp"],
    )


def prepared(
    c: Connection, context: AuthContext, space: UUID, query: RetirementRead, *, write: bool = False
) -> dict[str, Any]:
    node = product(c, context, space, query.product_id, write=write)
    audit = retirement(c, context, space, query.product_id, query.retirement_audit_id)
    original = audit["after_snapshot"]
    fields = [
        {"path": "/product/" + key, "value": original[key]}
        for key in ("name", "code", "level", "regions", "channels", "lifecycle")
    ]
    linked: dict[str, Any] = {}
    if query.definition_id:
        d = (
            c.execute(
                definitions(context, space, query.product_id, audit).where(
                    tables.product_definitions.c.id == query.definition_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if d is None:
            raise ProductWorkError("定义须属于原退市对象，并在该次退市前已发布")
        linked["definition"] = _plain(d)
        for kind, table, identity in (("strategy", tables.product_strategies, d["strategy_id"]),):
            row = (
                c.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space,
                        table.c.id == identity,
                    )
                )
                .mappings()
                .one()
            )
            linked[kind] = _plain(row)
        o = tables.opportunities
        row = (
            c.execute(
                select(o).where(
                    o.c.tenant_id == context.tenant.id,
                    o.c.market_space_id == space,
                    o.c.id == UUID(linked["strategy"]["opportunity_id"]),
                )
            )
            .mappings()
            .one()
        )
        linked["opportunity"] = _plain(row)
        for kind, item in linked.items():
            _line(
                c,
                context,
                space,
                UUID(item["product_line_id"]) if item["product_line_id"] else None,
                access="manager" if write else "viewer",
            )
            fields.extend(
                {"path": "/" + kind + f["path"], "value": f["value"]}
                for f in field_values(cast(TargetKind, kind), item)
            )
    refs: list[Any] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "sources" and isinstance(child, list):
                    refs.extend(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(linked)
    body = {
        "retirement": {
            "audit_id": str(audit["id"]),
            "recorded_at": audit["timestamp"].isoformat(),
            "actor_user_id": str(audit["actor_user_id"]),
            "reason": audit["context"].get("reason"),
            "before": audit["before_snapshot"],
            "after": original,
        },
        "current_product": _plain(node),
        "linked_records": linked,
        "fields": fields,
        "source_warnings": evidence_quality(c, context, refs),
        "policy_version": "retirement-learning.v1",
    }
    return {**body, "digest": digest(body)}


def conditions(context: AuthContext, query: RetirementRead) -> tuple[Any, ...]:
    t = tables.retirement_feedback
    return (
        t.c.tenant_id == context.tenant.id,
        t.c.retirement_audit_id == query.retirement_audit_id,
        t.c.target_id == (query.definition_id or query.product_id),
    )


class RetirementFeedbackService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(
        self, context: AuthContext, space: UUID, query: RetirementOptions
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            product(c, context, space, query.product_id)
            if query.retirement_audit_id is None:
                t = tables.audit_log
                q = retirement_query(context, space, query.product_id)
                if query.before_audit_id:
                    q = q.where(t.c.id < query.before_audit_id)
                values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
                return {
                    "items": [
                        {
                            "id": str(v["id"]),
                            "recorded_at": v["timestamp"].isoformat(),
                            "reason": v["context"].get("reason"),
                            "version": v["after_snapshot"]["version"],
                        }
                        for v in values[:20]
                    ],
                    "next_before_audit_id": str(values[19]["id"]) if len(values) > 20 else None,
                }
            audit = retirement(c, context, space, query.product_id, query.retirement_audit_id)
            t = tables.product_definitions
            q = definitions(context, space, query.product_id, audit)
            if query.before_definition_id:
                q = q.where(t.c.id < query.before_definition_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [
                    {
                        "id": str(v["id"]),
                        "title": v["title"],
                        "revision_number": v["revision_number"],
                        "published_at": v["published_at"].isoformat(),
                    }
                    for v in values[:20]
                ],
                "next_before_definition_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def read(self, context: AuthContext, space: UUID, query: RetirementRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            source = prepared(c, context, space, query)
            can_respond = True
            try:
                prepared(c, context, space, query, write=True)
            except (ValueError, PermissionError):
                can_respond = False
            t, u = tables.retirement_feedback, tables.users
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(*conditions(context, query))
            ).scalar_one()
            q = (
                select(t, u.c.display_name.label("actor_name"))
                .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.actor_user_id))
                .where(*conditions(context, query))
            )
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            values = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            return {
                "source": source,
                "version": version,
                "can_respond": can_respond,
                "items": [
                    {
                        **_plain(v),
                        "sources_current": v["source_digest"] == source["digest"],
                        "additional_source_warnings": evidence_quality(c, context, v["sources"]),
                    }
                    for v in values[:20]
                ],
                "next_before_version": values[19]["version"] if len(values) > 20 else None,
            }

    def save(self, context: AuthContext, space: UUID, command: RetirementSave) -> dict[str, Any]:
        with self.engine.begin() as c:
            source = prepared(c, context, space, command, write=True)
            signature = digest({"space": str(space), "command": command.model_dump(mode="json")})
            t = tables.retirement_feedback
            old = (
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
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写退市反馈")
                return _plain(old)
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(*conditions(context, command))
            ).scalar_one()
            if version != command.expected_version or source["digest"] != command.expected_digest:
                raise ProductWorkError("原资料或反馈已有变化，请重新核对")
            fields = {v["path"]: v for v in source["fields"]}
            if not set(command.field_paths).issubset(fields):
                raise ProductWorkError("请选择本次实际读取的原字段")
            refs = _sources(c, context, command.sources)
            linked = source["linked_records"]
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        product_id=command.product_id,
                        retirement_audit_id=command.retirement_audit_id,
                        target_id=command.definition_id or command.product_id,
                        definition_id=command.definition_id,
                        strategy_id=UUID(linked["strategy"]["id"]) if linked else None,
                        opportunity_id=UUID(linked["opportunity"]["id"]) if linked else None,
                        version=version + 1,
                        verdict=command.verdict,
                        selected_fields=[fields[p] for p in command.field_paths],
                        finding=command.finding,
                        follow_up=command.follow_up,
                        limitations=command.limitations,
                        sources=refs,
                        source_snapshot=source,
                        source_digest=source["digest"],
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
                "retirement_feedback",
                "recorded",
                {"id": row["id"], "version": row["version"], "product_id": row["product_id"]},
            )
            return _plain(row)
