"""Evidence-backed segments, measurable outcomes and interval market sizing."""

from decimal import Decimal, localcontext
from typing import Any, Self, cast
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select, true

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Key, Quantity, SourceRef, Text, Unit
from app.contracts.product_records import DesiredOutcome, FactStatement
from app.db.schema import tables
from app.domain.product_evidence import evidence_quality, resolve_evidence
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _record,
    _role,
    _scope_ref,
    _space,
    digest,
)

MARKET_ESTIMATE_INTERPRETATION = (
    "市场估计，非实际销量；区间仅传播输入上下界，不是统计置信区间。"
    # The serviceable and obtainable estimates each narrow the preceding market.
    "SAM基于TAM服务比例，SOM基于SAM可获取比例。"
)

PARAMETERS = (
    "potential_customers",
    "annual_units_per_customer",
    "unit_price",
    "serviceable_share",
    "obtainable_share",
)
FACT_GROUPS = (
    "target_users",
    "customer_problems",
    "use_environments",
    "buying_criteria",
    "unmet_needs",
)


class MarketParameter(Contract):
    lower: Quantity | None = Field(ge=0)
    upper: Quantity | None = Field(ge=0)
    basis: FactStatement

    @model_validator(mode="after")
    def bounded_interval(self) -> Self:
        if (self.lower is None) != (self.upper is None) or (
            self.lower is not None and self.upper is not None and self.lower > self.upper
        ):
            raise ValueError("参数须同时提供上下界（点估计填相同值），未知时两者留空")
        if self.basis.approval is not None:
            raise ValueError("此输入不接受客户端提供的业务批准引用")
        return self


class MarketSizing(Contract):
    horizon_year: int = Field(ge=2000, le=2100)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    population_unit: Text
    boundary: Text
    potential_customers: MarketParameter
    annual_units_per_customer: MarketParameter
    unit_price: MarketParameter
    serviceable_share: MarketParameter
    obtainable_share: MarketParameter

    @model_validator(mode="after")
    def shares_are_fractions(self) -> Self:
        for parameter in (self.serviceable_share, self.obtainable_share):
            if parameter.upper is not None and parameter.upper > 1:
                raise ValueError("服务比例和可获取比例须在0到1之间；可获取比例基于SAM")
        return self


class OutcomeDraft(Contract):
    statement: Text
    metric_key: Key
    unit: Unit
    baseline_value: Quantity | None
    target_value: Quantity | None
    measurement_method: Text
    window: Text
    sources: tuple[SourceRef, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def baseline_has_sources(self) -> Self:
        if self.baseline_value is not None and not self.sources:
            raise ValueError("现状基线数值须引用依据，未知基线请留空")
        return self


class MarketSegmentContent(Input):
    title: str = Field(min_length=1, max_length=512)
    target_users: tuple[FactStatement, ...] = Field(min_length=1, max_length=30)
    job_to_be_done: FactStatement
    customer_problems: tuple[FactStatement, ...] = Field(min_length=1, max_length=30)
    use_environments: tuple[FactStatement, ...] = Field(min_length=1, max_length=30)
    buying_criteria: tuple[FactStatement, ...] = Field(min_length=1, max_length=30)
    unmet_needs: tuple[FactStatement, ...] = Field(min_length=1, max_length=30)
    outcome: OutcomeDraft
    sizing_inputs: MarketSizing
    revision_reason: Text

    @model_validator(mode="after")
    def no_claimed_approval(self) -> Self:
        statements = (
            self.job_to_be_done,
            *(fact for group in FACT_GROUPS for fact in getattr(self, group)),
        )
        if any(fact.approval is not None for fact in statements):
            raise ValueError("市场记录不接受客户端提供的业务批准引用")
        return self


class MarketSegmentDraft(MarketSegmentContent):
    request_id: UUID
    product_line_id: UUID | None = None
    supersedes_id: UUID | None = None


def calculate_market(sizing: MarketSizing) -> dict[str, Any]:
    """Nonnegative interval products; decimal arithmetic, no invented point estimates."""
    parameters = {key: getattr(sizing, key) for key in PARAMETERS}

    def product(keys: tuple[str, ...]) -> dict[str, str] | None:
        if any(parameters[key].lower is None for key in keys):
            return None
        with localcontext() as context:
            context.prec = 128
            lower, upper = Decimal(1), Decimal(1)
            for key in keys:
                parameter = parameters[key]
                assert parameter.lower is not None and parameter.upper is not None
                lower *= parameter.lower
                upper *= parameter.upper
            return {"lower": format(lower, "f"), "upper": format(upper, "f")}

    definitions = {
        "tam": ("potential_customers", "annual_units_per_customer"),
        "sam": ("potential_customers", "annual_units_per_customer", "serviceable_share"),
        "som": (
            "potential_customers",
            "annual_units_per_customer",
            "serviceable_share",
            "obtainable_share",
        ),
    }
    return {
        "policy_version": "market-bottom-up-v1",
        "horizon_year": sizing.horizon_year,
        "currency": sizing.currency,
        "boundary": sizing.boundary,
        "population_unit": sizing.population_unit,
        "estimates": {
            name: {
                "annual_units": product(keys),
                "annual_revenue": product((*keys, "unit_price")),
                "units_formula": " × ".join(keys),
                "revenue_formula": " × ".join((*keys, "unit_price")),
            }
            for name, keys in definitions.items()
        },
        "unknown_parameters": [
            key for key, parameter in parameters.items() if parameter.lower is None
        ],
        "hypothesis_parameters": [
            key
            for key, parameter in parameters.items()
            if parameter.basis.fact_kind == "hypothesis"
        ],
        "interpretation": MARKET_ESTIMATE_INTERPRETATION,
    }


def _fact(connection: Connection, context: AuthContext, fact: FactStatement) -> dict[str, Any]:
    return {
        **fact.model_dump(mode="json"),
        "sources": resolve_evidence(connection, context, fact.sources),
    }


def _outcome(row: Any) -> dict[str, Any]:
    contract = DesiredOutcome(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=_scope_ref(row),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        sources=tuple(SourceRef.model_validate(item) for item in row["sources"]),
        **{
            key: row[key]
            for key in (
                "statement",
                "metric_key",
                "unit",
                "baseline_value",
                "target_value",
                "measurement_method",
                "window",
            )
        },
    )
    return {**_record(row), **contract.model_dump(mode="json")}


class MarketAnalysisService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(
        self, context: AuthContext, space_id: UUID, *, record_id: UUID | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.market_segments
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                        table.c.id == record_id if record_id else true(),
                    )
                    .order_by(table.c.created_at.desc())
                    .limit(100)
                ).mappings()
            )
            replaced = set(
                connection.execute(
                    select(table.c.supersedes_id).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.supersedes_id.in_([row["id"] for row in rows]),
                    )
                ).scalars()
            )
            outcomes = {
                row["id"]: row
                for row in connection.execute(
                    select(tables.desired_outcomes).where(
                        tables.desired_outcomes.c.tenant_id == context.tenant.id,
                        tables.desired_outcomes.c.id.in_(
                            [row["desired_outcome_id"] for row in rows]
                        ),
                    )
                ).mappings()
            }
            items = []
            for row in rows:
                refs = list(row["job_to_be_done"]["sources"])
                for group in FACT_GROUPS:
                    for fact in row[group]:
                        refs.extend(fact["sources"])
                for parameter in PARAMETERS:
                    refs.extend(row["sizing_inputs"][parameter]["basis"]["sources"])
                refs.extend(outcomes[row["desired_outcome_id"]]["sources"])
                items.append(
                    {
                        **_record(row),
                        "is_latest": row["id"] not in replaced,
                        "outcome": _outcome(outcomes[row["desired_outcome_id"]]),
                        "source_warnings": evidence_quality(connection, context, refs),
                    }
                )
            return {"items": items}

    def detail(self, context: AuthContext, space_id: UUID, record_id: UUID) -> dict[str, Any]:
        items = self.list(context, space_id, record_id=record_id)["items"]
        if not items:
            raise ProductWorkAccessError("记录不存在或不可访问")
        return cast(dict[str, Any], items[0])

    def create(
        self, context: AuthContext, space_id: UUID, draft: MarketSegmentDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return create_segment_in_connection(connection, context, space_id, draft)


def create_segment_in_connection(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    draft: MarketSegmentDraft,
    *,
    source_finding_id: UUID | None = None,
    source_finding_position: int | None = None,
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
    _space(connection, context, space_id, access="contributor", lock=True)
    _line(
        connection,
        context,
        space_id,
        draft.product_line_id,
        access="contributor",
        writable=True,
    )
    table = tables.market_segments
    fingerprint = digest(draft.model_dump(mode="json"))
    existing = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.market_space_id == space_id,
                table.c.owner_user_id == context.user.id,
                table.c.request_id == draft.request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        if existing["request_digest"] != fingerprint:
            raise ProductWorkError("同一请求编号不能用于不同市场分析")
        return _record(existing)
    node_id, outcome_id = uuid4(), uuid4()
    series_id, version = node_id, 1
    if draft.supersedes_id:
        previous = (
            connection.execute(
                select(table).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.market_space_id == space_id,
                    table.c.id == draft.supersedes_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous is None:
            raise ProductWorkAccessError("此前市场分析不存在或不可访问")
        _line(
            connection,
            context,
            space_id,
            previous["product_line_id"],
            access="contributor",
            writable=True,
        )
        if previous["product_line_id"] != draft.product_line_id:
            raise ProductWorkError("修订不能改变已有市场分析范围")
        if connection.execute(
            select(table.c.id).where(
                table.c.tenant_id == context.tenant.id,
                table.c.supersedes_id == previous["id"],
            )
        ).first():
            raise ProductWorkError("此分析已有新版，请以最新版本追加修订")
        series_id, version = previous["series_id"], previous["version"] + 1
    outcome_values = draft.outcome.model_dump(exclude={"sources"})
    outcome_values["sources"] = resolve_evidence(connection, context, draft.outcome.sources)
    outcome = (
        connection.execute(
            tables.desired_outcomes.insert()
            .values(
                **outcome_values,
                id=outcome_id,
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                product_line_id=draft.product_line_id,
                owner_user_id=context.user.id,
            )
            .returning(tables.desired_outcomes)
        )
        .mappings()
        .one()
    )
    _outcome(outcome)
    sizing = draft.sizing_inputs.model_dump(mode="json")
    for parameter in PARAMETERS:
        sizing[parameter]["basis"] = _fact(
            connection, context, getattr(draft.sizing_inputs, parameter).basis
        )
    values: dict[str, Any] = {
        group: [_fact(connection, context, fact) for fact in getattr(draft, group)]
        for group in FACT_GROUPS
    }
    row = (
        connection.execute(
            table.insert()
            .values(
                **values,
                id=node_id,
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                product_line_id=draft.product_line_id,
                owner_user_id=context.user.id,
                series_id=series_id,
                supersedes_id=draft.supersedes_id,
                version=version,
                title=draft.title,
                job_to_be_done=_fact(connection, context, draft.job_to_be_done),
                desired_outcome_id=outcome_id,
                sizing_inputs=sizing,
                sizing_result=calculate_market(draft.sizing_inputs),
                revision_reason=draft.revision_reason,
                request_id=draft.request_id,
                request_digest=fingerprint,
                source_finding_id=source_finding_id,
                source_finding_position=source_finding_position,
            )
            .returning(table)
        )
        .mappings()
        .one()
    )
    _emit(connection, context, space_id, "desired_outcome", "created", outcome)
    _emit(connection, context, space_id, "market_segment", "recorded", row)
    return {**_record(row), "outcome": _outcome(outcome)}
