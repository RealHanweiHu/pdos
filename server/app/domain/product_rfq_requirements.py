"""DC-13 RFQ T1: same actor and source version, one atomic draft-intake confirmation."""

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, func, null, select

from app.ai.product_work_context import rebuild, validate_assessment, validate_statements
from app.ai.product_work_runs import authorize, run_row
from app.ai.project_discussion_sources import actor
from app.ai.quality import FindingQualityService
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.product_rfq_ai import ProductRfqAssessment, RfqRequirement
from app.contracts.product_work_ai import ProductWorkAssessment
from app.db.schema import tables
from app.domain.product_evidence_findings import receipt
from app.domain.product_workspace import ProductWorkError, _emit, _plain, _role, digest
from app.domain.requirements import RequirementCreate, RequirementService

KIND = "product_rfq_requirements"
AGENT = "product_management_intelligence"


class Read(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: UUID


class Confirm(Read):
    finding_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["accepted", "rejected"]
    comment: str = Field(min_length=1, max_length=2048)
    items: tuple[RfqRequirement, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def shape(self) -> "Confirm":
        if bool(self.items) != (self.decision == "accepted"):
            raise ValueError("确认须核对至少一项需求；拒绝不附登记内容")
        return self


def allowed(c: Connection, tenant: UUID) -> bool:
    return FindingQualityService.is_output_allowed_connection(
        c, tenant_id=tenant, agent_key=AGENT, finding_type=KIND
    )


def create_finding(c: Connection, run: Any, output: ProductWorkAssessment) -> None:
    assessment = ProductRfqAssessment.model_validate(output.model_dump(mode="json"))
    if not assessment.requirements or not allowed(c, run["tenant_id"]):
        return
    t = tables.findings
    if c.execute(
        select(t.c.id).where(
            t.c.tenant_id == run["tenant_id"], t.c.run_id == run["id"], t.c.finding_type == KIND
        )
    ).first():
        return
    snapshot = run["run_context"]["product_work_source"]
    validate_assessment(assessment, snapshot)
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
                finding_type=KIND,
                origin_key=f"product-rfq:{run['id']}",
                title=f"RFQ需求候选 · {len(assessment.requirements)}项",
                summary="待原发起人核对后一次确认登记为需求草稿；尚未批准规格",
                proposed_payload={
                    "version": "product-rfq-proposal-v1",
                    "source_digest": snapshot["digest"],
                    "assessment": assessment.model_dump(mode="json"),
                },
                evidence_event_ids=[],
                confidence_basis_points=0,
                preflight_version="product-rfq-proposal-v1",
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
        KIND,
        "proposed",
        {**row, "version": 1},
    )


class ProductRfqRequirements:
    def __init__(self, engine: Engine):
        self.engine = engine

    @staticmethod
    def load(
        c: Connection, context: AuthContext, space: UUID, body: Read, *, write: bool = False
    ) -> tuple[Any, Any]:
        if write:
            _role(context, Action.REQUIREMENT_CREATE)
            authorize(c, context, space, None, write=True, lock=True)
        run = run_row(c, context, space, body.run_id)
        selection = run["run_context"]["product_work_selection"]
        if selection["capability"] != "rfq_requirements":
            raise ProductWorkError("本入口只办理RFQ需求候选")
        if write:
            require_live_key("product_management_intelligence.rfq_requirements")
            line = selection["product_line_id"]
            authorize(c, context, space, UUID(line) if line else None, write=True)
        t = tables.findings
        query = select(t).where(
            t.c.tenant_id == context.tenant.id, t.c.run_id == run["id"], t.c.finding_type == KIND
        )
        row = c.execute(query.with_for_update() if write else query).mappings().one_or_none()
        if write and (row is None or row["id"] != getattr(body, "finding_id", None)):
            raise ProductWorkError("原候选不存在或范围不一致")
        return run, row

    @staticmethod
    def records(c: Connection, tenant: UUID, finding: UUID) -> list[dict[str, Any]]:
        t = tables.product_rfq_requirement_links
        return [
            _plain(row)
            for row in c.execute(
                select(t)
                .where(t.c.tenant_id == tenant, t.c.source_finding_id == finding)
                .order_by(t.c.source_finding_position)
            ).mappings()
        ]

    def read(self, context: AuthContext, space: UUID, body: Read) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            run, row = self.load(c, context, space, body)
            snapshot = run["run_context"]["product_work_source"]
            return {
                "finding": receipt(row),
                "sources_current": rebuild(c, context.tenant.id, snapshot)["digest"]
                == snapshot["digest"],
                "items": (
                    row["accepted_payload"]["items"]
                    if row["accepted_payload"]
                    else row["proposed_payload"]["assessment"]["requirements"]
                )
                if row
                else [],
                "references": snapshot["references"],
                "records": self.records(c, context.tenant.id, row["id"]) if row else [],
            }

    def confirm(self, context: AuthContext, space: UUID, body: Confirm) -> dict[str, Any]:
        with self.engine.begin() as c:
            run, row = self.load(c, context, space, body, write=True)
            if body.expected_digest != digest(row["proposed_payload"]):
                raise ProductWorkError("候选版本不一致，请重新读取")
            snapshot = run["run_context"]["product_work_source"]
            accepted = (
                {
                    "version": "product-rfq-accepted-v1",
                    "source_digest": snapshot["digest"],
                    "items": [item.model_dump(mode="json") for item in body.items],
                }
                if body.items
                else None
            )
            if row["status"] != "pending_review":
                if (
                    row["status"] == ("applied" if body.items else "rejected")
                    and row["accepted_payload"] == accepted
                    and row["review_comment"] == body.comment
                ):
                    return {
                        "finding": receipt(row),
                        "records": self.records(c, context.tenant.id, row["id"]),
                    }
                raise ProductWorkError("候选已办理，请刷新实际状态")
            if body.items:
                if rebuild(c, context.tenant.id, snapshot)["digest"] != snapshot["digest"]:
                    raise ProductWorkError("原资料已变化，请重新抽取后确认")
                if not allowed(c, context.tenant.id):
                    raise ProductWorkError("此候选因质量收窄暂不可登记")
                validate_statements(
                    [item.basis for item in body.items],
                    {ref["reference_id"]: ref for ref in snapshot["references"]},
                )
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            t = tables.findings
            saved = (
                c.execute(
                    t.update()
                    .where(t.c.tenant_id == context.tenant.id, t.c.id == row["id"])
                    .values(
                        status=body.decision,
                        accepted_payload=accepted if accepted else null(),
                        reviewed_by_user_id=context.user.id,
                        reviewed_at=now,
                        review_comment=body.comment,
                        updated_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            _emit(c, context, space, KIND, body.decision, {**saved, "version": 2}, before=dict(row))
            records = []
            service = RequirementService(self.engine)
            for pos, item in enumerate(body.items, 1):
                source = "; ".join(
                    dict.fromkeys(
                        ref["label"]
                        for ref in snapshot["references"]
                        if ref["reference_id"]
                        in {citation.reference_id for citation in item.basis.citations}
                    )
                )
                record = service.create_connection(
                    c,
                    tenant_id=context.tenant.id,
                    actor_user_id=context.user.id,
                    draft=RequirementCreate(
                        code=f"RFQ-{row['id'].hex}-{pos:02}",
                        title=item.title,
                        description=item.description,
                        source=source[:64],
                        priority=item.priority,
                        acceptance_criteria=list(item.acceptance_criteria),
                        customer_id=None,
                    ),
                )
                link = (
                    c.execute(
                        tables.product_rfq_requirement_links.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            market_space_id=space,
                            source_finding_id=row["id"],
                            source_finding_position=pos,
                            requirement_id=record.id,
                            accepted_item=item.model_dump(mode="json"),
                        )
                        .returning(tables.product_rfq_requirement_links)
                    )
                    .mappings()
                    .one()
                )
                records.append(_plain(link))
            if records:
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                saved = (
                    c.execute(
                        t.update()
                        .where(t.c.tenant_id == context.tenant.id, t.c.id == row["id"])
                        .values(
                            status="applied",
                            applied_by_user_id=context.user.id,
                            applied_at=now,
                            applied_entity_type="requirement",
                            applied_entity_id=UUID(records[0]["requirement_id"]),
                            updated_at=now,
                        )
                        .returning(t)
                    )
                    .mappings()
                    .one()
                )
                _emit(c, context, space, KIND, "applied", {**saved, "version": 3}, before=dict(row))
            FindingQualityService(self.engine).evaluate_connection(
                c, tenant_id=context.tenant.id, evaluated_at=now
            )
            return {"finding": receipt(saved), "records": records}
