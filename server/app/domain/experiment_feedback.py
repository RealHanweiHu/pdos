"""Actual experiment learning against related opportunity, strategy and definition fields."""

from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, SourceRef, Text
from app.db.schema import tables
from app.domain.product_evidence import evidence_quality
from app.domain.product_workspace import (
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _plain,
    _role,
    _sources,
    _space,
    digest,
)

TargetKind = Literal["opportunity", "strategy", "definition"]


class FeedbackOptions(Contract):
    experiment_id: UUID
    target_kind: TargetKind = "opportunity"
    search: str = Field(default="", max_length=128)
    before_id: UUID | None = None


class FeedbackRead(Contract):
    experiment_id: UUID
    target_kind: TargetKind
    target_id: UUID
    before_version: int | None = Field(default=None, ge=1)


class FeedbackTargetRead(Contract):
    target_kind: TargetKind
    target_id: UUID
    before_id: UUID | None = None


class FeedbackWrite(FeedbackRead):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest
    field_paths: tuple[str, ...] = Field(min_length=1, max_length=20)
    verdict: Literal["adopt_for_followup", "reject_application", "needs_evidence", "withdrawn"]
    reason: Text
    proposed_change: Text
    limitations: Text

    @model_validator(mode="after")
    def fields(self) -> Self:
        if len(set(self.field_paths)) != len(self.field_paths) or any(
            not p or len(p) > 1024 for p in self.field_paths
        ):
            raise ValueError("反馈字段不能重复或超出实际字段范围")
        if self.before_version is not None:
            raise ValueError("保存不接受历史翻页参数")
        if self.verdict == "withdrawn" and self.expected_version == 0:
            raise ValueError("尚无反馈可撤回")
        return self


def experiment(
    c: Connection, context: AuthContext, space: UUID, identity: UUID, *, write: bool = False
) -> Any:
    _space(c, context, space, access="manager" if write else "viewer", lock=write)
    if write:
        _role(context, Action.PRODUCT_WORK_MANAGE)
    t = tables.experiments
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id,
                t.c.market_space_id == space,
                t.c.id == identity,
                _line_filter(t, context),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["state"] != "concluded" or row["approval_id"] is None:
        raise ProductWorkError("仅有权读取的已结束真实实验可登记结果反馈")
    _line(
        c,
        context,
        space,
        row["product_line_id"],
        access="manager" if write else "viewer",
        writable=write,
    )
    return row


def targets(context: AuthContext, exp: Any, kind: TargetKind) -> tuple[Any, Any]:
    o, s, d = tables.opportunities, tables.product_strategies, tables.product_definitions
    original_series = (
        select(o.c.series_id)
        .where(o.c.tenant_id == context.tenant.id, o.c.id == exp["opportunity_id"])
        .correlate(None)
        .scalar_subquery()
    )
    opportunities = select(o.c.id).where(
        o.c.tenant_id == context.tenant.id,
        o.c.market_space_id == exp["market_space_id"],
        o.c.series_id == original_series,
        _line_filter(o, context),
        cast(o.c.solutions, JSONB).contains([{"id": str(exp["solution_id"])}]),
    )
    strategies = select(s.c.id).where(
        s.c.tenant_id == context.tenant.id,
        s.c.market_space_id == exp["market_space_id"],
        s.c.opportunity_id.in_(opportunities),
        _line_filter(s, context),
    )
    t = {"opportunity": o, "strategy": s, "definition": d}[kind]
    match = (
        t.c.id.in_(opportunities)
        if kind == "opportunity"
        else t.c.id.in_(strategies)
        if kind == "strategy"
        else t.c.strategy_id.in_(strategies)
    )
    return t, select(t).where(
        t.c.tenant_id == context.tenant.id,
        t.c.market_space_id == exp["market_space_id"],
        match,
        _line_filter(t, context),
    )


def field_values(kind: TargetKind, row: Any) -> list[dict[str, Any]]:
    roots = {
        "opportunity": ("importance_basis", "satisfaction_basis", "solutions"),
        "strategy": (
            "canvas",
            "route_comparisons",
            "professional_constraints",
            "unknowns",
            "decision_reason",
        ),
        "definition": ("content",),
    }[kind]
    values = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict) and (
            "fact_kind" in value
            or "item_key" in value
            or "solution_id" in value
            or ("amount" in value and "basis" in value)
        ):
            values.append({"path": path, "value": value})
        elif isinstance(value, dict):
            for key, child in value.items():
                if key not in {"owner_user_id", "reviewers"}:
                    visit(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, path + "/" + str(i))
        elif value is not None and value != "":
            values.append({"path": path, "value": value})

    plain = _plain(row)
    for key in roots:
        visit(plain[key], "/" + key)
    if len(values) > 10000:
        raise ProductWorkError("目标字段过多，请缩小原业务记录范围；未静默截断")
    return values


def prepared(
    c: Connection, context: AuthContext, space: UUID, query: FeedbackRead, *, write: bool = False
) -> dict[str, Any]:
    exp = experiment(c, context, space, query.experiment_id, write=write)
    _, statement = targets(context, exp, query.target_kind)
    target = (
        c.execute(
            statement.where(
                {
                    "opportunity": tables.opportunities,
                    "strategy": tables.product_strategies,
                    "definition": tables.product_definitions,
                }[query.target_kind].c.id
                == query.target_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if target is None:
        raise ProductWorkError("目标不属于原机会系列/原方案的实际后续记录，或无权读取")
    _line(
        c,
        context,
        space,
        target["product_line_id"],
        access="manager" if write else "viewer",
        writable=write,
    )
    approval = (
        c.execute(
            select(tables.experiment_approvals).where(
                tables.experiment_approvals.c.tenant_id == context.tenant.id,
                tables.experiment_approvals.c.experiment_id == exp["id"],
                tables.experiment_approvals.c.id == exp["approval_id"],
            )
        )
        .mappings()
        .one()
    )
    values = field_values(query.target_kind, target)
    refs = [*approval["plan_snapshot"]["sources"], *exp["result_evidence"]]

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "sources" and isinstance(v, list):
                    refs.extend(v)
                else:
                    collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    collect(values)
    body = {
        "experiment": _plain(exp),
        "approved_plan": _plain(approval),
        "target_kind": query.target_kind,
        "target": _plain(target),
        "fields": values,
        "source_warnings": evidence_quality(c, context, refs),
        "comparison_policy": "experiment-learning-qualitative.v1",
        "interpretation": (
            "原假设/判据与实际结果作具名定性核对；样本、方法和适用范围保留，"
            "不输出未测数值或自动推断因果。"
        ),
    }
    return {**body, "digest": digest(body)}


def feedback_view(
    c: Connection, context: AuthContext, row: Any, current: dict[str, Any]
) -> dict[str, Any]:
    name = c.execute(
        select(tables.users.c.display_name).where(
            tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == row["actor_user_id"]
        )
    ).scalar_one()
    return {
        **_plain(row),
        "actor_name": name,
        "sources_current": row["source_digest"] == current["digest"],
    }


class ExperimentFeedbackService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def for_target(
        self, context: AuthContext, space: UUID, query: FeedbackTargetRead
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _space(c, context, space)
            target_table = {
                "opportunity": tables.opportunities,
                "strategy": tables.product_strategies,
                "definition": tables.product_definitions,
            }[query.target_kind]
            target = (
                c.execute(
                    select(target_table).where(
                        target_table.c.tenant_id == context.tenant.id,
                        target_table.c.market_space_id == space,
                        target_table.c.id == query.target_id,
                        _line_filter(target_table, context),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if target is None:
                raise ProductWorkError("目标不存在或无权读取")
            _line(c, context, space, target["product_line_id"])
            t, e = tables.experiment_feedback, tables.experiments
            q = (
                select(t)
                .join(e, (e.c.id == t.c.experiment_id) & (e.c.tenant_id == t.c.tenant_id))
                .where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.market_space_id == space,
                    t.c.target_kind == query.target_kind,
                    t.c.target_id == query.target_id,
                    _line_filter(e, context),
                )
            )
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            items = []
            for row in values[:20]:
                try:
                    current = prepared(
                        c,
                        context,
                        space,
                        FeedbackRead(
                            experiment_id=row["experiment_id"],
                            target_kind=query.target_kind,
                            target_id=query.target_id,
                        ),
                    )
                except (ValueError, PermissionError):
                    continue
                latest = c.execute(
                    select(func.max(t.c.version)).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.experiment_id == row["experiment_id"],
                        t.c.target_kind == query.target_kind,
                        t.c.target_id == query.target_id,
                    )
                ).scalar_one()
                items.append(
                    {
                        **feedback_view(c, context, row, current),
                        "is_latest": row["version"] == latest,
                    }
                )
            return {
                "items": items,
                "unavailable_count": min(len(values), 20) - len(items),
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def options(self, context: AuthContext, space: UUID, query: FeedbackOptions) -> dict[str, Any]:
        with self.engine.connect() as c:
            exp = experiment(c, context, space, query.experiment_id)
            t, q = targets(context, exp, query.target_kind)
            title = (
                t.c.content["title"].as_string() if query.target_kind == "definition" else t.c.title
            )
            if query.search:
                q = q.where(title.icontains(query.search, autoescape=True))
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            values = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            return {
                "items": [
                    {
                        "id": str(v["id"]),
                        "title": v["content"]["title"]
                        if query.target_kind == "definition"
                        else v["title"],
                        "version": v["version"]
                        if query.target_kind == "opportunity"
                        else v["revision_number"],
                        "state": v["state"],
                    }
                    for v in values[:20]
                ],
                "next_before_id": str(values[19]["id"]) if len(values) > 20 else None,
            }

    def read(self, context: AuthContext, space: UUID, query: FeedbackRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            current = prepared(c, context, space, query)
            can_respond = True
            try:
                _role(context, Action.PRODUCT_WORK_MANAGE)
                selected_space = _space(c, context, space, access="manager")
                if selected_space["lifecycle"] == "archived":
                    can_respond = False
                for row in (current["experiment"], current["target"]):
                    _line(
                        c,
                        context,
                        space,
                        UUID(row["product_line_id"]) if row["product_line_id"] else None,
                        access="manager",
                        writable=True,
                    )
            except (ValueError, PermissionError):
                can_respond = False
            t = tables.experiment_feedback
            conditions = (
                t.c.tenant_id == context.tenant.id,
                t.c.experiment_id == query.experiment_id,
                t.c.target_kind == query.target_kind,
                t.c.target_id == query.target_id,
            )
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(*conditions)
            ).scalar_one()
            q = select(t).where(*conditions)
            if query.before_version:
                q = q.where(t.c.version < query.before_version)
            values = c.execute(q.order_by(t.c.version.desc()).limit(21)).mappings().all()
            return {
                "source": current,
                "can_respond": can_respond,
                "version": version,
                "items": [feedback_view(c, context, v, current) for v in values[:20]],
                "next_before_version": values[19]["version"] if len(values) > 20 else None,
            }

    def save(self, context: AuthContext, space: UUID, command: FeedbackWrite) -> dict[str, Any]:
        with self.engine.begin() as c:
            current = prepared(c, context, space, command, write=True)
            t = tables.experiment_feedback
            signature = digest({"space": str(space), "body": command.model_dump(mode="json")})
            existing = (
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
            if existing is not None:
                if existing["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写实验反馈")
                return feedback_view(c, context, existing, current)
            version = c.execute(
                select(func.coalesce(func.max(t.c.version), 0)).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.experiment_id == command.experiment_id,
                    t.c.target_kind == command.target_kind,
                    t.c.target_id == command.target_id,
                )
            ).scalar_one()
            if version != command.expected_version or command.expected_digest != current["digest"]:
                raise ProductWorkError("原实验/目标或反馈已有变化，请刷新核对")
            fields = {v["path"]: v for v in current["fields"]}
            if not set(command.field_paths).issubset(fields):
                raise ProductWorkError("请选择本次实际读取的目标字段")
            if command.verdict == "adopt_for_followup":
                refs = current["experiment"]["result_evidence"]
                if not refs:
                    raise ProductWorkError("尚无实际结果证据，请先补证；不能用实验计划替代结果")
                _sources(c, context, tuple(SourceRef.model_validate(v) for v in refs))
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space,
                        experiment_id=command.experiment_id,
                        target_kind=command.target_kind,
                        target_id=command.target_id,
                        opportunity_id=command.target_id
                        if command.target_kind == "opportunity"
                        else None,
                        strategy_id=command.target_id
                        if command.target_kind == "strategy"
                        else None,
                        definition_id=command.target_id
                        if command.target_kind == "definition"
                        else None,
                        version=version + 1,
                        verdict=command.verdict,
                        selected_fields=[fields[p] for p in command.field_paths],
                        reason=command.reason,
                        proposed_change=command.proposed_change,
                        limitations=command.limitations,
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
            _emit(c, context, space, "experiment_feedback", "recorded", row)
            return feedback_view(c, context, row, current)
