"""Actual tooling rounds with separate commitments, results and evidence revisions."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.document_previews import document_row, metadata
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_engineering import TimedEvidence, supplier_row


class RoundDraft(Contract):
    code: str = Field(min_length=1, max_length=128)
    asset_reference: str = Field(min_length=1, max_length=128)
    tooling_kind: Literal["mold", "fixture", "tooling"]
    round_label: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    phase: Literal["EVT", "DVT", "PVT", "other"]
    supplier_id: UUID | None = None
    planning_resource_id: UUID | None = None
    status: Literal["planned", "in_progress", "completed", "cancelled"] = "planned"
    outcome: Literal["pending", "accepted", "conditional", "rejected"] = "pending"
    conditions: Text | None = None
    promised: TimedEvidence | None = None
    estimated_ready: TimedEvidence | None = None
    started: TimedEvidence | None = None
    completed: TimedEvidence | None = None
    available: TimedEvidence | None = None
    schedule_target_point: Literal["start", "finish"] | None = None
    report_id: UUID | None = None
    report_location: Text | None = None
    inspected_count: int | None = Field(default=None, ge=1)
    accepted_count: int | None = Field(default=None, ge=0)
    build_ids: list[UUID] = Field(default_factory=list, max_length=30)
    sample_ids: list[UUID] = Field(default_factory=list, max_length=100)
    issue_ids: list[UUID] = Field(default_factory=list, max_length=30)
    need_node_ids: list[UUID] = Field(default_factory=list, max_length=50)
    evidence_id: UUID
    reason: Text

    @model_validator(mode="after")
    def actual_facts(self) -> "RoundDraft":
        if not all(
            value.strip()
            for value in (self.code, self.asset_reference, self.round_label, self.title)
        ):
            raise ValueError("工装编号、原件标识、轮次与名称不可为空")
        if self.status == "planned" and (self.started or self.completed):
            raise ValueError("尚未开始的轮次不填写实际开始/完成")
        if self.status == "in_progress" and (not self.started or self.completed):
            raise ValueError("进行中须有实际开始，不能已有实际完成")
        if self.status == "completed" and (
            not self.started or not self.completed or not self.report_id or not self.report_location
        ):
            raise ValueError("完成轮次须有实际起止时间及报告原件位置")
        if self.status == "cancelled" and self.completed:
            raise ValueError("取消轮次不作为已完成轮次")
        if (self.status == "completed") != (self.outcome != "pending"):
            raise ValueError("只有完成轮次才能记录接受、有条件接受或拒绝")
        if self.outcome == "conditional" and not self.conditions:
            raise ValueError("有条件接受须说明尚待完成的条件")
        if self.schedule_target_point and not self.need_node_ids:
            raise ValueError("工装齐套条件须选择实际需用节点")
        if self.available and (
            self.status != "completed"
            or self.outcome != "accepted"
            or not self.completed
            or self.available.at < self.completed.at
        ):
            raise ValueError("实际可用须在本轮无条件接受并完成后，绑定具名核对证据")
        for fact in (self.started, self.completed, self.available):
            if fact and fact.at > datetime.now(UTC):
                raise ValueError("实际时间不能填写未来")
        if self.completed and (not self.started or self.completed.at < self.started.at):
            raise ValueError("实际完成不得早于开始")
        if (self.inspected_count is None) != (self.accepted_count is None):
            raise ValueError("实际检验数与合格数须同时填写；未知时留空")
        if self.inspected_count is not None and (
            self.accepted_count is not None
            and self.accepted_count > self.inspected_count
            or not self.report_id
            or not self.report_location
        ):
            raise ValueError("合格数不能超过检验数，数量须有报告依据")
        for name in LINKS:
            ids = getattr(self, name)
            if len(ids) != len(set(ids)):
                raise ValueError("同一实际关联不能重复选择")
        return self


class RoundApply(RoundDraft):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest


LINKS = {
    "build_ids": tables.build_batches,
    "sample_ids": tables.samples,
    "issue_ids": tables.issues,
    "need_node_ids": tables.schedule_nodes,
}


def source_basis(c: Connection, tenant: UUID, project: UUID, command: RoundDraft) -> dict[str, Any]:
    result: dict[str, Any] = {
        "supplier": supplier_row(c, tenant, command.supplier_id) if command.supplier_id else None
    }
    from app.domain.tooling_resources import source as resource_source

    result["planning_resource"] = (
        resource_source(c, tenant, command.planning_resource_id, command.tooling_kind)
        if command.planning_resource_id
        else None
    )
    for key in ("evidence_id", "report_id"):
        identity = getattr(command, key)
        result[key] = metadata(document_row(c, tenant, project, identity)) if identity else None
    for key in ("promised", "estimated_ready", "started", "completed", "available"):
        fact = getattr(command, key)
        result[key] = (
            {
                **fact.model_dump(mode="json"),
                "document": metadata(document_row(c, tenant, project, fact.evidence_id)),
            }
            if fact
            else None
        )
    for key, table in LINKS.items():
        result[key] = [
            _plain(
                dict(
                    NpiExecutionService._row(
                        c, table, tenant_id=tenant, project_id=project, record_id=identity
                    )
                )
            )
            for identity in getattr(command, key)
        ]
    if any(issue.get("withdrawn_at") is not None for issue in result["issue_ids"]):
        raise ProductWorkError("原问题已撤回，不能新增模具轮次关联")
    if any(
        UUID(sample["build_batch_id"]) not in command.build_ids for sample in result["sample_ids"]
    ):
        raise ProductWorkError("所选样机的实际试制批次须同时纳入本轮关联")
    return result


def preview(
    c: Connection, context: AuthContext, project: UUID, round_id: UUID, command: RoundDraft
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    t = tables.tooling_rounds
    current = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == round_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if current and any(
        current[key] != getattr(command, key)
        for key in ("code", "asset_reference", "tooling_kind", "round_label")
    ):
        raise ProductWorkError("原工装及轮次身份固定；实际新轮次请另行登记")
    actual = source_basis(c, context.tenant.id, project, command)
    schedule_baseline_id = None
    if command.schedule_target_point:
        from app.domain.formal_schedule import current_plan

        formal = current_plan(c, context.tenant.id, project)
        schedule_baseline_id = str(formal["baseline_id"]) if formal else None
        planned = {str(node["id"]) for node in formal["nodes"]} if formal else set()
        if any(str(identity) not in planned for identity in command.need_node_ids):
            raise ProductWorkError("工装齐套条件须选择当前正式计划内的实际需用节点")
        if any(row.get("tooling_id") == str(round_id) for row in actual["need_node_ids"]):
            raise ProductWorkError("工装轮次不能把自身作为等待其可用的需用节点")
    first_promise = (current["snapshot"].get("first_promise") if current else None) or actual[
        "promised"
    ]
    basis = {
        "previous_version": current["version"] if current else 0,
        "schedule_baseline_id": schedule_baseline_id,
        "sources": actual,
        "first_promise": first_promise,
        "command": command.model_dump(
            mode="json", exclude={"request_id", "expected_version", "expected_digest"}
        ),
    }
    return {"basis": basis, "digest": digest(basis)}


def readout(row: dict[str, Any]) -> dict[str, Any]:
    command = RoundDraft.model_validate(row["payload"])
    first = row["snapshot"].get("first_promise")
    return {
        "reported_yield": str(Decimal(command.accepted_count) / Decimal(command.inspected_count))
        if command.accepted_count is not None and command.inspected_count
        else None,
        "on_first_promise": command.completed.at <= datetime.fromisoformat(first["at"])
        if command.completed and first
        else None,
        "execution_finished": command.status == "completed",
        "round_accepted": command.status == "completed" and command.outcome == "accepted",
        "availability_unconfirmed": command.available is None,
    }


class ToolingRoundService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        after: UUID | None = None,
        round_id: UUID | None = None,
        before_version: int | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            t, d, s = tables.tooling_rounds, tables.documents, tables.suppliers
            options = {}
            for name, table in LINKS.items():
                options[name] = [
                    _plain(dict(row))
                    for row in c.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id, table.c.project_id == project
                        )
                        .order_by(table.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ]
            query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if round_id:
                query = query.where(t.c.id == round_id)
            elif after:
                query = query.where(t.c.id > after)
            rows = list(c.execute(query.order_by(t.c.id).limit(21)).mappings())
            items = [_plain(dict(row)) for row in rows[:20]]
            for row in items:
                row["readout"] = readout(row)
                from app.domain.tooling_schedule import assess

                row["schedule_condition"] = assess(c, context.tenant.id, project, row)
                from app.domain.tooling_resources import readout as resource_readout

                row["resource_view"] = resource_readout(c, context, project, row)
                revisions = tables.tooling_round_revisions
                author = (
                    c.execute(
                        select(revisions.c.created_by_user_id, revisions.c.created_at).where(
                            revisions.c.tenant_id == context.tenant.id,
                            revisions.c.project_id == project,
                            revisions.c.round_id == UUID(row["id"]),
                            revisions.c.version == row["version"],
                        )
                    )
                    .mappings()
                    .one()
                )
                row["revision_actor_id"] = str(author["created_by_user_id"])
                row["revision_recorded_at"] = author["created_at"].isoformat()
            from app.domain.tooling_resources import choices as resource_choices

            result: dict[str, Any] = {
                "resources": resource_choices(c, context),
                "items": items,
                "next_cursor": str(rows[19]["id"]) if len(rows) > 20 else None,
                "options": options,
                "history": [],
                "history_next_before": None,
                "documents": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(d.c.id, d.c.filename)
                        .where(d.c.tenant_id == context.tenant.id, d.c.project_id == project)
                        .order_by(d.c.created_at.desc())
                        .limit(200)
                    ).mappings()
                ],
                "suppliers": [
                    _plain(dict(row))
                    for row in c.execute(
                        select(s).where(s.c.tenant_id == context.tenant.id).order_by(s.c.code)
                    ).mappings()
                ],
            }
            if round_id:
                r = tables.tooling_round_revisions
                query = select(r).where(
                    r.c.tenant_id == context.tenant.id,
                    r.c.project_id == project,
                    r.c.round_id == round_id,
                )
                if before_version:
                    query = query.where(r.c.version < before_version)
                history = list(c.execute(query.order_by(r.c.version.desc()).limit(21)).mappings())
                result["history"] = [_plain(dict(row)) for row in history[:20]]
                result["history_next_before"] = (
                    history[19]["version"] if len(history) > 20 else None
                )
            return result

    def preview(
        self, context: AuthContext, project: UUID, round_id: UUID, command: RoundDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return preview(c, context, project, round_id, command)

    def apply(
        self, context: AuthContext, project: UUID, round_id: UUID, command: RoundApply
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "round": str(round_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            r, t = tables.tooling_round_revisions, tables.tooling_rounds
            prior = (
                c.execute(
                    select(r).where(
                        r.c.tenant_id == context.tenant.id,
                        r.c.created_by_user_id == context.user.id,
                        r.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise ProductWorkError("原请求已用于另一工装轮次记录")
                return _plain(dict(prior))
            observed = preview(c, context, project, round_id, command)
            if (
                observed["digest"] != command.expected_digest
                or observed["basis"]["previous_version"] != command.expected_version
            ):
                raise ProductWorkError("原轮次或证据资料已变化，请重新预览")
            from app.domain.schedule_execution import guard_source_execution
            from app.domain.schedule_source_actuals import latest_observations, projection

            nodes = tables.schedule_nodes
            node_id = c.execute(
                select(nodes.c.id).where(
                    nodes.c.tenant_id == context.tenant.id,
                    nodes.c.project_id == project,
                    nodes.c.tooling_id == round_id,
                )
            ).scalar_one_or_none()
            if node_id:
                previous = next(
                    (
                        row
                        for row in latest_observations(c, context.tenant.id, project)
                        if row["node_id"] == node_id
                    ),
                    None,
                )
                action = f"npi.tooling_round.{command.status}"
                actual = projection(
                    "tooling",
                    {"action": action, "after_snapshot": observed["basis"]["command"]},
                    previous,
                )
                guard_source_execution(
                    c, context.tenant.id, project, node_id, action, actual, previous
                )
            payload = observed["basis"]["command"]
            values = {
                key: getattr(command, key)
                for key in (
                    "code",
                    "asset_reference",
                    "tooling_kind",
                    "planning_resource_id",
                    "round_label",
                    "title",
                    "phase",
                    "status",
                    "outcome",
                )
            }
            values.update(
                version=command.expected_version + 1,
                payload=payload,
                snapshot=observed["basis"],
                started_at=command.started.at if command.started else None,
                completed_at=command.completed.at if command.completed else None,
                updated_at=datetime.now(UTC),
            )
            if command.expected_version == 0:
                c.execute(
                    t.insert().values(
                        **values,
                        id=round_id,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        created_by_user_id=context.user.id,
                    )
                )
            else:
                c.execute(
                    t.update()
                    .where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == round_id,
                    )
                    .values(**values)
                )
            saved = (
                c.execute(
                    r.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        round_id=round_id,
                        version=command.expected_version + 1,
                        payload=payload,
                        snapshot=observed["basis"],
                        evidence_id=command.evidence_id,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(r)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=round_id,
                record_type="tooling_round",
                action=command.status,
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
