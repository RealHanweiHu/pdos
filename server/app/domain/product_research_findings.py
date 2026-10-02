"""Original-actor research proposal acceptance and separate, atomic domain application."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, func, null, select

from app.ai.product_work_context import key, rebuild
from app.ai.product_work_runs import authorize, run_row
from app.ai.project_discussion_sources import actor
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.contracts.product_work_ai import ProductResearchAssessment, ResearchPlanProposal
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkError,
    ResearchDraft,
    _emit,
    _plain,
    _research,
    create_research_in_connection,
    digest,
)

TYPE = "product_research_plan"
AGENT = "product_management_intelligence"


class Read(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID


class Review(Read):
    finding_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["accepted", "rejected"]
    comment: str = Field(min_length=1, max_length=2048)
    proposal: ResearchPlanProposal | None = None

    @model_validator(mode="after")
    def consistent(self) -> "Review":
        if not self.comment.strip() or (self.decision == "accepted") != (self.proposal is not None):
            raise ValueError("接受需核对研究计划；拒绝不附已接受内容；请填写办理说明")
        return self


class Apply(Read):
    finding_id: UUID
    accepted_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def allowed(c: Connection, tenant_id: UUID) -> bool:
    return FindingQualityService.is_output_allowed_connection(
        c,
        tenant_id=tenant_id,
        agent_key=AGENT,
        finding_type=TYPE,
    )


def create_finding(c: Connection, run: Any, assessment: ProductResearchAssessment) -> None:
    if assessment.research_plan is None or not allowed(c, run["tenant_id"]):
        return
    t = tables.findings
    if c.execute(
        select(t.c.id).where(
            t.c.tenant_id == run["tenant_id"], t.c.run_id == run["id"], t.c.finding_type == TYPE
        )
    ).first():
        return
    row = (
        c.execute(
            t.insert()
            .values(
                id=uuid4(),
                tenant_id=run["tenant_id"],
                project_id=None,
                scope_kind="market_space",
                run_id=run["id"],
                agent_key=AGENT,
                finding_type=TYPE,
                model_invocation_id=UUID(run["run_context"]["product_work_invocation_id"]),
                origin_key=f"product-research:{run['id']}",
                status="pending_review",
                title=assessment.research_plan.question[:512],
                summary="研究规划候选，待原发起人核对并独立应用",
                proposed_payload={
                    "version": "product-research-proposal-v1",
                    "source_digest": run["run_context"]["product_work_source"]["digest"],
                    "assessment": assessment.model_dump(mode="json"),
                },
                evidence_event_ids=[],
                confidence_basis_points=0,
                preflight_version="product-research-proposal-v1",
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
        TYPE,
        "proposed",
        {**row, "version": 1},
    )


def finding(c: Connection, context: AuthContext, run: Any, *, lock: bool = False) -> Any:
    t = tables.findings
    query = select(t).where(
        t.c.tenant_id == context.tenant.id, t.c.run_id == run["id"], t.c.finding_type == TYPE
    )
    return c.execute(query.with_for_update() if lock else query).mappings().one_or_none()


def response(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return _plain(
        {
            **row,
            "proposed_digest": digest(row["proposed_payload"]),
            "accepted_digest": digest(row["accepted_payload"]) if row["accepted_payload"] else None,
        }
    )


class ProductResearchFindings:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(self, context: AuthContext, space: UUID, body: Read) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            run = run_row(c, context, space, body.run_id)
            snapshot = run["run_context"]["product_work_source"]
            row = finding(c, context, run)
            current = rebuild(c, context.tenant.id, snapshot)["digest"] == snapshot["digest"]
            return {
                "finding": response(row),
                "sources_current": current,
                "owner_user_id": str(run["requested_by_user_id"]),
                "product_line_id": snapshot["selection"]["product_line_id"],
            }

    def _mutation(
        self, c: Connection, context: AuthContext, space: UUID, body: Review | Apply
    ) -> tuple[Any, Any]:
        require_live_key(key("research_planning"))
        # Use the same space-first lock order as research and source mutations.
        authorize(c, context, space, None, write=True, lock=True)
        run = run_row(c, context, space, body.run_id)
        snapshot = run["run_context"]["product_work_source"]
        line = snapshot["selection"]["product_line_id"]
        authorize(c, context, space, UUID(line) if line else None, write=True)
        row = finding(c, context, run, lock=True)
        if row is None or row["id"] != body.finding_id:
            raise ProductWorkError("原研究候选不存在")
        return run, row

    @staticmethod
    def _current(c: Connection, context: AuthContext, run: Any) -> None:
        snapshot = run["run_context"]["product_work_source"]
        if rebuild(c, context.tenant.id, snapshot)["digest"] != snapshot["digest"]:
            raise ProductWorkError("原资料已变化，请重新分析后办理")
        if not allowed(c, context.tenant.id):
            raise ProductWorkError("研究候选因质量收窄暂不可接受或应用")

    def review(self, context: AuthContext, space: UUID, body: Review) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, row = self._mutation(c, context, space, body)
            if body.expected_digest != digest(row["proposed_payload"]):
                raise ProductWorkError("请核对原候选后办理")
            accepted = (
                {
                    "version": "product-research-accepted-v1",
                    "source_digest": row["proposed_payload"]["source_digest"],
                    "proposal": body.proposal.model_dump(mode="json"),
                }
                if body.proposal
                else None
            )
            if row["status"] != "pending_review":
                if (
                    row["status"]
                    in (body.decision, "applied" if body.decision == "accepted" else "rejected")
                    and row["accepted_payload"] == accepted
                    and row["review_comment"] == body.comment
                ):
                    return {"finding": response(row)}
                raise ProductWorkError("候选已办理，请刷新记录")
            if body.decision == "accepted":
                self._current(c, context, run)
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = (
                c.execute(
                    tables.findings.update()
                    .where(
                        tables.findings.c.id == row["id"],
                        tables.findings.c.tenant_id == context.tenant.id,
                    )
                    .values(
                        status=body.decision,
                        accepted_payload=accepted if accepted is not None else null(),
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
            _emit(c, context, space, TYPE, body.decision, {**saved, "version": 2}, before=dict(row))
            return {"finding": response(saved)}

    def apply(self, context: AuthContext, space: UUID, body: Apply) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, row = self._mutation(c, context, space, body)
            if not row["accepted_payload"] or body.accepted_digest != digest(
                row["accepted_payload"]
            ):
                raise ProductWorkError("请先接受并核对计划，再单独应用")
            if row["status"] == "applied":
                existing_task = (
                    c.execute(
                        select(tables.research_tasks).where(
                            tables.research_tasks.c.tenant_id == context.tenant.id,
                            tables.research_tasks.c.id == row["applied_entity_id"],
                            tables.research_tasks.c.source_finding_id == row["id"],
                        )
                    )
                    .mappings()
                    .one()
                )
                return {"finding": response(row), "research_task": _research(existing_task)}
            if row["status"] != "accepted":
                raise ProductWorkError("只有已接受的研究计划可以独立应用")
            self._current(c, context, run)
            proposal = ResearchPlanProposal.model_validate(row["accepted_payload"]["proposal"])
            line = run["run_context"]["product_work_selection"]["product_line_id"]
            task = create_research_in_connection(
                c,
                context,
                space,
                ResearchDraft(
                    request_id=row["id"],
                    owner_user_id=context.user.id,
                    product_line_id=UUID(line) if line else None,
                    **proposal.model_dump(),
                ),
                source_finding_id=row["id"],
            )
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            saved = (
                c.execute(
                    tables.findings.update()
                    .where(
                        tables.findings.c.id == row["id"],
                        tables.findings.c.tenant_id == context.tenant.id,
                    )
                    .values(
                        status="applied",
                        applied_by_user_id=context.user.id,
                        applied_at=now,
                        applied_entity_type="research_task",
                        applied_entity_id=UUID(task["id"]),
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
            _emit(c, context, space, TYPE, "applied", {**saved, "version": 3}, before=dict(row))
            return {"finding": response(saved), "research_task": task}
