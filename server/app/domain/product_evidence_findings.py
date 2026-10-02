"""Private product-work candidates, explicit acceptance and atomic domain application."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, func, null, select

from app.ai.product_evidence_context import catalog, validate_refs
from app.ai.product_work_context import contract, key, rebuild
from app.ai.product_work_runs import authorize, run_row
from app.ai.project_discussion_sources import actor
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.contracts.product_discovery_ai import ExperimentContent, OpportunityContent
from app.contracts.product_planning_ai import DefinitionCandidate, StrategyCandidate
from app.contracts.product_records import SolutionCandidate, SpecificationItem
from app.contracts.product_work_ai import ProductWorkAssessment
from app.db.schema import tables
from app.domain.competitors import (
    CompetitorContent,
    CompetitorDraft,
    create_competitor_in_connection,
)
from app.domain.experiments import ExperimentDraft, ExperimentPlan, create_experiment_in_connection
from app.domain.market_analysis import (
    MarketSegmentContent,
    MarketSegmentDraft,
    calculate_market,
    create_segment_in_connection,
)
from app.domain.opportunities import OpportunityDraft, create_opportunity_in_connection
from app.domain.product_definitions import (
    DefinitionContent,
    DefinitionDraft,
    create_definition_in_connection,
)
from app.domain.product_strategies import (
    ProfessionalConstraint,
    StrategyContent,
    StrategyDraft,
    create_strategy_in_connection,
)
from app.domain.product_workspace import ProductWorkError, _emit, _plain, _record, digest

AGENT = "product_management_intelligence"
CONFIG = {
    "product_strategy": ("product_strategy_drafts", "product_strategies", "product_strategy"),
    "product_definition": (
        "product_definition_drafts",
        "product_definitions",
        "product_definition",
    ),
    "opportunity_mapping": ("product_opportunities", "opportunities", "opportunity"),
    "experiment_design": ("product_experiments", "experiments", "experiment"),
    "competitor_analysis": (
        "product_competitor_observations",
        "competitor_observations",
        "competitor_observation",
    ),
    "market_analysis": ("product_market_segments", "market_segments", "market_segment"),
}


class Competitors(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Literal["competitor_analysis"]
    items: tuple[CompetitorContent, ...] = Field(min_length=1, max_length=6)


class Markets(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Literal["market_analysis"]
    items: tuple[MarketSegmentContent, ...] = Field(min_length=1, max_length=6)


class Opportunities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Literal["opportunity_mapping"]
    items: tuple[OpportunityContent, ...] = Field(min_length=1, max_length=6)


class Experiments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Literal["experiment_design"]
    items: tuple[ExperimentContent, ...] = Field(min_length=1, max_length=6)


class Strategies(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Literal["product_strategy"]
    items: tuple[StrategyCandidate, ...] = Field(min_length=1, max_length=6)


class Definitions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    capability: Literal["product_definition"]
    items: tuple[DefinitionCandidate, ...] = Field(min_length=1, max_length=6)


Bundle = Competitors | Markets | Opportunities | Experiments | Strategies | Definitions
Proposal = Annotated[Bundle, Field(discriminator="capability")]


class Read(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID


class Review(Read):
    finding_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["accepted", "rejected"]
    comment: str = Field(min_length=1, max_length=2048)
    proposal: Proposal | None = None

    @model_validator(mode="after")
    def accepted_shape(self) -> "Review":
        if (self.decision == "accepted") != (self.proposal is not None):
            raise ValueError("接受须核对候选；拒绝不附已接受内容")
        return self


class Apply(Read):
    finding_id: UUID
    accepted_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def config(run: Any) -> tuple[str, str, str]:
    capability = run["run_context"]["product_work_selection"]["capability"]
    if capability not in CONFIG:
        raise ProductWorkError("本入口只办理产品工作领域候选")
    return CONFIG[capability]


def proposal_from(capability: str, data: Any) -> Bundle:
    if capability == "competitor_analysis":
        return Competitors.model_validate(data)
    if capability == "market_analysis":
        return Markets.model_validate(data)
    if capability == "opportunity_mapping":
        return Opportunities.model_validate(data)
    if capability == "experiment_design":
        return Experiments.model_validate(data)
    if capability == "product_strategy":
        return Strategies.model_validate(data)
    return Definitions.model_validate(data)


def allowed(c: Connection, tenant: UUID, finding_type: str) -> bool:
    return FindingQualityService.is_output_allowed_connection(
        c, tenant_id=tenant, agent_key=AGENT, finding_type=finding_type
    )


def create_finding(c: Connection, run: Any, output: ProductWorkAssessment) -> None:
    _, model = contract(run["run_context"]["product_work_prompt_version"])
    assessment = model.model_validate(output.model_dump(mode="json"))
    finding_type, field, _ = config(run)
    items = getattr(assessment, field)
    if not items or not allowed(c, run["tenant_id"], finding_type):
        return
    t = tables.findings
    if c.execute(
        select(t.c.id).where(
            t.c.tenant_id == run["tenant_id"],
            t.c.run_id == run["id"],
            t.c.finding_type == finding_type,
        )
    ).first():
        return
    validate_refs(assessment, run["run_context"]["product_work_source"], run["tenant_id"])
    label = {
        "competitor_observations": "竞品观察",
        "market_segments": "市场细分",
        "opportunities": "机会与方案",
        "experiments": "实验计划",
        "product_strategies": "策略草稿",
        "product_definitions": "定义草稿",
    }[field]
    row = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=run["tenant_id"],
                project_id=None,
                scope_kind="market_space",
                run_id=run["id"],
                model_invocation_id=UUID(run["run_context"]["product_work_invocation_id"]),
                agent_key=AGENT,
                finding_type=finding_type,
                origin_key=f"product-evidence:{run['id']}",
                title=f"{label}候选 · {len(items)}项",
                summary="待原发起人核对接受后独立应用；尚未登记为业务结果",
                proposed_payload={
                    "version": "product-evidence-proposal-v1",
                    "source_digest": run["run_context"]["product_work_source"]["digest"],
                    "assessment": assessment.model_dump(mode="json"),
                },
                evidence_event_ids=[],
                confidence_basis_points=0,
                preflight_version="product-evidence-proposal-v1",
            )
            .returning(t)
        )
        .mappings()
        .one()
    )
    _emit(
        c,
        actor(c, run["tenant_id"], run["requested_by_user_id"]),
        run["market_space_id"],
        finding_type,
        "proposed",
        {**row, "version": 1},
    )


def receipt(row: Any) -> dict[str, Any] | None:
    return (
        None
        if row is None
        else _plain(
            {
                **row,
                "proposed_digest": digest(row["proposed_payload"]),
                "accepted_digest": digest(row["accepted_payload"])
                if row["accepted_payload"]
                else None,
            }
        )
    )


def calculations(proposal: Bundle) -> list[dict[str, Any]]:
    return (
        [calculate_market(item.sizing_inputs) for item in proposal.items]
        if isinstance(proposal, Markets)
        else []
    )


def applied_records(
    c: Connection, context: AuthContext, run: Any, row: Any
) -> list[dict[str, Any]]:
    if row is None or row["status"] != "applied":
        return []
    table = getattr(tables, config(run)[1])
    return [
        _record(item)
        for item in c.execute(
            select(table)
            .where(
                table.c.tenant_id == context.tenant.id,
                table.c.source_finding_id == row["id"],
            )
            .order_by(table.c.source_finding_position)
        ).mappings()
    ]


def evidence_options(snapshot: dict[str, Any], tenant_id: UUID) -> list[dict[str, Any]]:
    refs = {
        item["reference_id"].split(":", 1)[1]: item
        for item in snapshot["references"]
        if item["reference_id"].startswith("evidence:")
    }
    result = []
    for entry in catalog(snapshot, tenant_id):
        ref = entry["reference"]
        fields = refs[ref["ref_id"]]["fields"]
        expires = fields["freshness_expires_at"]
        result.append(
            dict(
                id=ref["ref_id"],
                name=entry["label"],
                reference=ref,
                url=fields["url"],
                captured_at=fields["captured_at"],
                taint=fields["taint"],
                is_stale=expires is not None
                and datetime.fromisoformat(expires) <= datetime.now(UTC),
                superseded=fields["superseded_by_id"] is not None,
                has_conflict=fields["conflicts_with_id"] is not None,
            )
        )
    return result


class ProductEvidenceFindings:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def _load(
        c: Connection, context: AuthContext, space: UUID, body: Read, *, write: bool = False
    ) -> tuple[Any, Any]:
        if write:
            authorize(c, context, space, None, write=True, lock=True)
        run = run_row(c, context, space, body.run_id)
        finding_type, _, _ = config(run)
        if write:
            capability = run["run_context"]["product_work_selection"]["capability"]
            require_live_key(key(capability))
            line = run["run_context"]["product_work_selection"]["product_line_id"]
            authorize(c, context, space, UUID(line) if line else None, write=True)
        query = select(tables.findings).where(
            tables.findings.c.tenant_id == context.tenant.id,
            tables.findings.c.run_id == run["id"],
            tables.findings.c.finding_type == finding_type,
        )
        row = c.execute(query.with_for_update() if write else query).mappings().one_or_none()
        if write and (row is None or row["id"] != getattr(body, "finding_id", None)):
            raise ProductWorkError("原候选不存在或范围不一致")
        return run, row

    @staticmethod
    def _current(c: Connection, context: AuthContext, run: Any) -> None:
        snapshot = run["run_context"]["product_work_source"]
        if rebuild(c, context.tenant.id, snapshot)["digest"] != snapshot["digest"]:
            raise ProductWorkError("原资料已变化，请重新分析后办理")
        if not allowed(c, context.tenant.id, config(run)[0]):
            raise ProductWorkError("候选因质量收窄暂不可接受或应用")

    def read(self, context: AuthContext, space: UUID, body: Read) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            run, row = self._load(c, context, space, body)
            snapshot = run["run_context"]["product_work_source"]
            capability = snapshot["selection"]["capability"]
            _, field, _ = config(run)
            proposal = (
                proposal_from(
                    capability,
                    row["accepted_payload"]["proposal"]
                    if row and row["accepted_payload"]
                    else {
                        "capability": capability,
                        "items": row["proposed_payload"]["assessment"][field],
                    },
                )
                if row
                else None
            )
            return {
                "finding": receipt(row),
                "records": applied_records(c, context, run, row),
                "product_line_id": snapshot["selection"]["product_line_id"],
                "sources_current": rebuild(c, context.tenant.id, snapshot)["digest"]
                == snapshot["digest"],
                "proposal": proposal.model_dump(mode="json") if proposal else None,
                "evidence": evidence_options(snapshot, context.tenant.id),
                "targets": [
                    {
                        "id": ref["reference_id"].split(":", 1)[1],
                        "kind": ref["reference_id"].split(":", 1)[0],
                        **ref["fields"],
                    }
                    for ref in snapshot["references"]
                    if ref["reference_id"].startswith(
                        (
                            "segment:",
                            "opportunity:",
                            "strategy:",
                            "definition:",
                            "product:",
                            "work:",
                        )
                    )
                ],
                "calculations": calculations(proposal) if proposal else [],
            }

    def review(self, context: AuthContext, space: UUID, body: Review) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, row = self._load(c, context, space, body, write=True)
            if body.expected_digest != digest(row["proposed_payload"]):
                raise ProductWorkError("候选已变化，请重新读取")
            accepted = None
            if body.proposal:
                if (
                    body.proposal.capability
                    != run["run_context"]["product_work_selection"]["capability"]
                ):
                    raise ProductWorkError("不能将候选改成另一种业务能力")
                validate_refs(
                    body.proposal, run["run_context"]["product_work_source"], context.tenant.id
                )
                accepted = {
                    "version": "product-evidence-accepted-v1",
                    "source_digest": row["proposed_payload"]["source_digest"],
                    "proposal": body.proposal.model_dump(mode="json"),
                }
            if row["status"] != "pending_review":
                if (
                    row["status"]
                    in (body.decision, "applied" if body.decision == "accepted" else "rejected")
                    and row["accepted_payload"] == accepted
                    and row["review_comment"] == body.comment
                ):
                    return {
                        "finding": receipt(row),
                        "calculations": calculations(body.proposal) if body.proposal else [],
                    }
                raise ProductWorkError("候选已办理，请刷新实际状态")
            if body.decision == "accepted":
                self._current(c, context, run)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = (
                c.execute(
                    tables.findings.update()
                    .where(
                        tables.findings.c.tenant_id == context.tenant.id,
                        tables.findings.c.id == row["id"],
                    )
                    .values(
                        status=body.decision,
                        accepted_payload=accepted if accepted else null(),
                        reviewed_by_user_id=context.user.id,
                        reviewed_at=now,
                        review_comment=body.comment,
                        updated_at=now,
                    )
                    .returning(tables.findings)
                )
                .mappings()
                .one()
            )
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=context.tenant.id, evaluated_at=now
            )
            _emit(
                c,
                context,
                space,
                row["finding_type"],
                body.decision,
                {**saved, "version": 2},
                before=dict(row),
            )
            return {
                "finding": receipt(saved),
                "calculations": calculations(body.proposal) if body.proposal else [],
            }

    def apply(self, context: AuthContext, space: UUID, body: Apply) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, row = self._load(c, context, space, body, write=True)
            if (
                not row["accepted_payload"]
                or digest(row["accepted_payload"]) != body.accepted_digest
            ):
                raise ProductWorkError("请先核对接受，再独立应用")
            finding_type, table_name, entity_type = config(run)
            table = getattr(tables, table_name)
            if row["status"] == "applied":
                return {"finding": receipt(row), "records": applied_records(c, context, run, row)}
            if row["status"] != "accepted":
                raise ProductWorkError("只有已接受候选可以应用")
            self._current(c, context, run)
            proposal = proposal_from(
                run["run_context"]["product_work_selection"]["capability"],
                row["accepted_payload"]["proposal"],
            )
            validate_refs(proposal, run["run_context"]["product_work_source"], context.tenant.id)
            line = run["run_context"]["product_work_selection"]["product_line_id"]
            records = []
            for position, item in enumerate(proposal.items, 1):
                common: dict[str, Any] = dict(
                    request_id=uuid5(row["id"], str(position)),
                    product_line_id=UUID(line) if line else None,
                    supersedes_id=None,
                )
                if isinstance(proposal, Competitors):
                    created = create_competitor_in_connection(
                        c,
                        context,
                        space,
                        CompetitorDraft(**common, **item.model_dump()),
                        source_finding_id=row["id"],
                        source_finding_position=position,
                    )
                elif isinstance(proposal, Markets):
                    created = create_segment_in_connection(
                        c,
                        context,
                        space,
                        MarketSegmentDraft(**common, **item.model_dump()),
                        source_finding_id=row["id"],
                        source_finding_position=position,
                    )
                elif isinstance(proposal, Opportunities):
                    opportunity = OpportunityContent.model_validate(item.model_dump())
                    created = create_opportunity_in_connection(
                        c,
                        context,
                        space,
                        OpportunityDraft(
                            request_id=common["request_id"],
                            **item.model_dump(exclude={"solutions"}),
                            solutions=tuple(
                                SolutionCandidate(
                                    id=uuid5(common["request_id"], str(i)), **solution.model_dump()
                                )
                                for i, solution in enumerate(opportunity.solutions, 1)
                            ),
                        ),
                        source_finding_id=row["id"],
                        source_finding_position=position,
                    )
                elif isinstance(proposal, Experiments):
                    experiment = ExperimentContent.model_validate(item.model_dump())
                    created = create_experiment_in_connection(
                        c,
                        context,
                        space,
                        ExperimentDraft(
                            request_id=common["request_id"],
                            opportunity_id=experiment.opportunity_id,
                            solution_id=experiment.solution_id,
                            plan=ExperimentPlan(
                                owner_user_id=context.user.id,
                                **item.model_dump(exclude={"opportunity_id", "solution_id"}),
                            ),
                        ),
                        source_finding_id=row["id"],
                        source_finding_position=position,
                    )
                elif isinstance(proposal, Strategies):
                    strategy = StrategyCandidate.model_validate(item.model_dump())
                    created = create_strategy_in_connection(
                        c,
                        context,
                        space,
                        StrategyDraft(
                            request_id=common["request_id"],
                            opportunity_id=strategy.opportunity_id,
                            supersedes_id=strategy.supersedes_id,
                            content=StrategyContent(
                                owner_user_id=context.user.id,
                                **strategy.model_dump(
                                    exclude={
                                        "opportunity_id",
                                        "supersedes_id",
                                        "professional_constraints",
                                    }
                                ),
                                professional_constraints=tuple(
                                    ProfessionalConstraint(
                                        id=uuid5(common["request_id"], f"constraint:{i}"),
                                        **value.model_dump(),
                                    )
                                    for i, value in enumerate(strategy.professional_constraints, 1)
                                ),
                            ),
                        ),
                        source_finding_id=row["id"],
                        source_finding_position=position,
                    )
                else:
                    definition = DefinitionCandidate.model_validate(item.model_dump())
                    created = create_definition_in_connection(
                        c,
                        context,
                        space,
                        DefinitionDraft(
                            request_id=common["request_id"],
                            product_id=definition.product_id,
                            strategy_id=definition.strategy_id,
                            supersedes_id=definition.supersedes_id,
                            content=DefinitionContent(
                                owner_user_id=context.user.id,
                                **definition.model_dump(
                                    exclude={"product_id", "strategy_id", "supersedes_id", "items"}
                                ),
                                items=tuple(
                                    SpecificationItem(
                                        **value.model_dump(),
                                        owner_user_id=None,
                                        state="needs_confirmation",
                                    )
                                    for value in definition.items
                                ),
                            ),
                        ),
                        source_finding_id=row["id"],
                        source_finding_position=position,
                    )
                # Return the persisted primary row consistently, including on retry.
                records.append(
                    _record(
                        c.execute(
                            select(table).where(
                                table.c.tenant_id == context.tenant.id,
                                table.c.id == UUID(created["id"]),
                            )
                        )
                        .mappings()
                        .one()
                    )
                )
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = (
                c.execute(
                    tables.findings.update()
                    .where(
                        tables.findings.c.tenant_id == context.tenant.id,
                        tables.findings.c.id == row["id"],
                    )
                    .values(
                        status="applied",
                        applied_by_user_id=context.user.id,
                        applied_at=now,
                        applied_entity_type=entity_type,
                        applied_entity_id=UUID(records[0]["id"]),
                        updated_at=now,
                    )
                    .returning(tables.findings)
                )
                .mappings()
                .one()
            )
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=context.tenant.id, evaluated_at=now
            )
            _emit(
                c,
                context,
                space,
                finding_type,
                "applied",
                {**saved, "version": 3},
                before=dict(row),
            )
            return {"finding": receipt(saved), "records": records}
