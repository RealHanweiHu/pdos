"""Human-maintained opportunity trees with immutable alternatives and scoring."""

from decimal import Decimal, localcontext
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Quantity, Text
from app.contracts.product_records import FactStatement, Opportunity, SolutionCandidate
from app.db.schema import tables
from app.domain.market_analysis import _fact
from app.domain.opportunity_requirements import RequirementLinkDraft, links_for, save_links
from app.domain.product_evidence import evidence_quality
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _plain,
    _record,
    _role,
    _scope_ref,
    _space,
    digest,
)


class OpportunityDraft(Input):
    request_id: UUID
    supersedes_id: UUID | None = None
    segment_id: UUID
    parent_opportunity_id: UUID | None = None
    title: Text
    importance: Quantity | None = Field(ge=0, le=1)
    satisfaction: Quantity | None = Field(ge=0, le=1)
    importance_basis: FactStatement
    satisfaction_basis: FactStatement
    solutions: tuple[SolutionCandidate, ...] = Field(default=(), max_length=30)
    selected_solution_id: UUID | None = None
    state: Literal["exploring", "evaluating", "selected", "deferred", "closed"] = "exploring"
    revision_reason: Text
    requirement_links: tuple[RequirementLinkDraft, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def alternatives_and_facts(self) -> Self:
        if len({link.requirement_id for link in self.requirement_links}) != len(
            self.requirement_links
        ):
            raise ValueError("同一机会版本不能重复关联相同需求")
        ids = {item.id for item in self.solutions}
        if len(ids) != len(self.solutions):
            raise ValueError("候选方案编号不能重复")
        if self.selected_solution_id is not None and (
            len(ids) < 3 or self.selected_solution_id not in ids
        ):
            raise ValueError("收敛前须至少保留三个候选方案，并从中选择")
        if self.state == "selected" and self.selected_solution_id is None:
            raise ValueError("已选定状态须指定候选方案")
        if self.state in {"exploring", "evaluating"} and self.selected_solution_id is not None:
            raise ValueError("探索和比较阶段不能同时声明已选定方案")
        facts = [self.importance_basis, self.satisfaction_basis]
        for solution in self.solutions:
            facts.extend((solution.rationale, *solution.constraints))
        if any(fact.approval is not None for fact in facts):
            raise ValueError("机会输入不接受客户端提供的批准引用")
        return self


def score(importance: Decimal | None, satisfaction: Decimal | None) -> Decimal | None:
    if importance is None or satisfaction is None:
        return None
    with localcontext() as context:
        context.prec = 64
        return importance * (1 - satisfaction)


def _dto(row: Any, segment: Any) -> dict[str, Any]:
    sources = [*row["importance_basis"]["sources"], *row["satisfaction_basis"]["sources"]]
    for solution in row["solutions"]:
        sources.extend(solution["rationale"]["sources"])
        for constraint in solution["constraints"]:
            sources.extend(constraint["sources"])
    unique_refs = {ref["ref_id"]: ref for ref in sources}
    contract = Opportunity(
        id=row["id"],
        tenant_id=row["tenant_id"],
        scope=_scope_ref(row),
        version=row["version"],
        owner_user_id=row["owner_user_id"],
        sources=tuple(unique_refs.values()),
        title=row["title"],
        segment=segment["title"],
        job_to_be_done=segment["job_to_be_done"]["text"],
        **{
            key: row[key]
            for key in (
                "desired_outcome_id",
                "parent_opportunity_id",
                "importance",
                "satisfaction",
                "scoring_policy_version",
                "solutions",
                "selected_solution_id",
                "state",
            )
        },
    )
    return {
        **_record(row),
        **contract.model_dump(mode="json"),
        "segment_version": segment["version"],
        "alternatives_missing": max(0, 3 - len(row["solutions"])),
    }


def create_opportunity_in_connection(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    draft: OpportunityDraft,
    *,
    source_finding_id: UUID | None = None,
    source_finding_position: int | None = None,
) -> dict[str, Any]:
    _role(context, Action.PRODUCT_WORK_CONTRIBUTE)
    _space(connection, context, space_id, access="contributor", lock=True)
    segment = (
        connection.execute(
            select(tables.market_segments).where(
                tables.market_segments.c.tenant_id == context.tenant.id,
                tables.market_segments.c.market_space_id == space_id,
                tables.market_segments.c.id == draft.segment_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if segment is None:
        raise ProductWorkAccessError("所选市场细分不存在或不可访问")
    line_id = segment["product_line_id"]
    _line(connection, context, space_id, line_id, access="contributor", writable=True)
    table = tables.opportunities
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
            raise ProductWorkError("同一请求编号不能用于不同机会内容")
        result = _dto(existing, segment)
        result["requirement_links"] = links_for(connection, context, existing["id"])
        result["requirement_refs"] = [link["reference"] for link in result["requirement_links"]]
        return result
    node_id = uuid4()
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
            raise ProductWorkAccessError("此前机会版本不存在或不可访问")
        _line(
            connection,
            context,
            space_id,
            previous["product_line_id"],
            access="contributor",
            writable=True,
        )
        if (previous["segment_id"], previous["parent_opportunity_id"]) != (
            draft.segment_id,
            draft.parent_opportunity_id,
        ):
            raise ProductWorkError("修订须保留原市场细分和父机会关系；新的问题分支请另建机会")
        if previous["state"] == "closed":
            raise ProductWorkError("已关闭机会保留历史；后续探索请另建机会")
        if connection.execute(
            select(table.c.id).where(
                table.c.tenant_id == context.tenant.id,
                table.c.supersedes_id == previous["id"],
            )
        ).first():
            raise ProductWorkError("机会已有新版，请从最新版本修订")
        series_id, version = previous["series_id"], previous["version"] + 1
    if draft.parent_opportunity_id:
        parent = (
            connection.execute(
                select(table).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.market_space_id == space_id,
                    table.c.id == draft.parent_opportunity_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent is None or parent["segment_id"] != draft.segment_id:
            raise ProductWorkError("父机会须属于同一市场细分版本")
        if draft.supersedes_id is None and parent["state"] == "closed":
            raise ProductWorkError("不能在已关闭机会下创建新分支")
        if (
            draft.supersedes_id is None
            and connection.execute(
                select(table.c.id).where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.supersedes_id == parent["id"],
                )
            ).first()
        ):
            raise ProductWorkError("父机会已有新版，请刷新后选择最新版本创建分支")
    solutions = []
    for solution in draft.solutions:
        solutions.append(
            {
                **solution.model_dump(mode="json"),
                "rationale": _fact(connection, context, solution.rationale),
                "constraints": [_fact(connection, context, fact) for fact in solution.constraints],
            }
        )
    values = draft.model_dump(
        exclude={
            "requirement_links",
            "request_id",
            "supersedes_id",
            "solutions",
            "importance_basis",
            "satisfaction_basis",
        }
    )
    row = (
        connection.execute(
            table.insert()
            .values(
                **values,
                id=node_id,
                tenant_id=context.tenant.id,
                market_space_id=space_id,
                product_line_id=line_id,
                owner_user_id=context.user.id,
                series_id=series_id,
                supersedes_id=draft.supersedes_id,
                version=version,
                desired_outcome_id=segment["desired_outcome_id"],
                importance_basis=_fact(connection, context, draft.importance_basis),
                satisfaction_basis=_fact(connection, context, draft.satisfaction_basis),
                scoring_policy_version="importance-unmet-v1",
                opportunity_score=score(draft.importance, draft.satisfaction),
                solutions=solutions,
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
    result = _dto(row, segment)
    result["requirement_links"] = save_links(
        connection,
        context,
        space_id,
        row["id"],
        draft.supersedes_id,
        draft.requirement_links,
    )
    result["requirement_refs"] = [link["reference"] for link in result["requirement_links"]]
    _emit(
        connection,
        context,
        space_id,
        "opportunity",
        "recorded",
        {**row, "requirement_links": result["requirement_links"]},
    )
    return result


class OpportunityService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self, context: AuthContext, space_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.opportunities
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                    )
                    .order_by(table.c.created_at.desc())
                    .limit(300)
                ).mappings()
            )
            segments = {
                row["id"]: row
                for row in connection.execute(
                    select(tables.market_segments).where(
                        tables.market_segments.c.tenant_id == context.tenant.id,
                        tables.market_segments.c.id.in_([row["segment_id"] for row in rows]),
                    )
                ).mappings()
            }
            replaced = {row["supersedes_id"] for row in rows if row["supersedes_id"]}
            experiment_rows = connection.execute(
                select(
                    tables.experiments.c.id,
                    tables.experiments.c.opportunity_id,
                    tables.experiments.c.solution_id,
                    tables.experiments.c.dimension,
                    tables.experiments.c.state,
                    tables.experiments.c.result,
                    tables.experiments.c.hypothesis,
                    tables.experiments.c.result_explanation,
                    tables.experiments.c.concluded_at,
                )
                .where(
                    tables.experiments.c.tenant_id == context.tenant.id,
                    tables.experiments.c.opportunity_id.in_([row["id"] for row in rows]),
                )
                .order_by(tables.experiments.c.updated_at.desc())
                .limit(300)
            ).mappings()
            experiments_by_opportunity: dict[UUID, list[dict[str, Any]]] = {}
            for experiment in experiment_rows:
                experiments_by_opportunity.setdefault(experiment["opportunity_id"], []).append(
                    _plain(experiment)
                )
            items = []
            for row in rows:
                item = _dto(row, segments[row["segment_id"]])
                item.update(
                    is_latest=row["id"] not in replaced,
                    source_warnings=evidence_quality(connection, context, item["sources"]),
                )
                item["experiment_results"] = experiments_by_opportunity.get(row["id"], [])
                item["requirement_links"] = links_for(connection, context, row["id"])
                item["requirement_refs"] = [link["reference"] for link in item["requirement_links"]]
                items.append(item)
            return {"items": items}

    def detail(self, context: AuthContext, space_id: UUID, opportunity_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as connection:
            _space(connection, context, space_id)
            table = tables.opportunities
            row = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.id == opportunity_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkAccessError("机会不存在或不可访问")
            _line(connection, context, space_id, row["product_line_id"])
            segment = (
                connection.execute(
                    select(tables.market_segments).where(
                        tables.market_segments.c.tenant_id == context.tenant.id,
                        tables.market_segments.c.id == row["segment_id"],
                    )
                )
                .mappings()
                .one()
            )
            item = _dto(row, segment)
            item["is_latest"] = (
                connection.execute(
                    select(table.c.id).where(
                        table.c.tenant_id == context.tenant.id, table.c.supersedes_id == row["id"]
                    )
                ).first()
                is None
            )
            item["source_warnings"] = evidence_quality(connection, context, item["sources"])
            item["requirement_links"] = links_for(connection, context, row["id"])
            item["requirement_refs"] = [link["reference"] for link in item["requirement_links"]]
            experiment = tables.experiments
            item["experiment_results"] = [
                _plain(record)
                for record in connection.execute(
                    select(
                        experiment.c.id,
                        experiment.c.solution_id,
                        experiment.c.dimension,
                        experiment.c.state,
                        experiment.c.result,
                        experiment.c.hypothesis,
                        experiment.c.result_explanation,
                    )
                    .where(
                        experiment.c.tenant_id == context.tenant.id,
                        experiment.c.opportunity_id == row["id"],
                    )
                    .order_by(experiment.c.updated_at.desc())
                    .limit(300)
                ).mappings()
            ]
            return item

    def create(
        self, context: AuthContext, space_id: UUID, draft: OpportunityDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return create_opportunity_in_connection(connection, context, space_id, draft)
