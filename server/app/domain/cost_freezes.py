"""Named human approval binds a cost calculation to a retained frozen version."""

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.cost_rollups import ALGORITHM, RollupDraft, basis, calculate
from app.domain.document_previews import document_row, metadata
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_execution import _person


class FreezeDraft(Contract):
    rollup_id: UUID
    expected_calculation_digest: Digest
    previous_freeze_id: UUID | None = None
    approver_user_id: UUID
    evidence_id: UUID
    evidence_location: Text
    authority_basis: Text
    accepted_limits: Text
    reason: Text


class FreezeRequest(FreezeDraft):
    request_id: UUID
    expected_digest: Digest


class FreezeDecision(Contract):
    action: Literal["approve", "reject", "withdraw"]
    reason: Text
    scope_checked: bool = False
    cost_gap_checked: bool = False
    nre_checked: bool = False


class FreezeDecide(FreezeDecision):
    request_id: UUID
    expected_digest: Digest


def latest(c: Connection, tenant: UUID, project: UUID) -> Any:
    t = tables.cost_freezes
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def row(c: Connection, tenant: UUID, project: UUID, table: Any, identity: UUID) -> Any:
    value = (
        c.execute(
            select(table).where(
                table.c.tenant_id == tenant, table.c.project_id == project, table.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if value is None:
        raise ProductWorkError("成本记录不存在或不属于此项目")
    return value


def ready(
    c: Connection, context: AuthContext, project: UUID, command: FreezeDraft
) -> dict[str, Any]:
    calculation = row(c, context.tenant.id, project, tables.cost_rollups, command.rollup_id)
    if calculation["calculation_digest"] != command.expected_calculation_digest:
        raise ProductWorkError("请重新打开原计算核对版本")
    if calculation["algorithm"] != ALGORITHM or not calculation["result"]["complete"]:
        raise ProductWorkError("只能申请冻结本版算法下、选定范围无计算缺口的成本")
    draft = RollupDraft.model_validate(calculation["command"])
    if draft.stage == "actual":
        raise ProductWorkError("ERP实际留作回测，不作为目标冻结版本")
    fixed = basis(c, context.tenant.id, project, draft)
    if digest(fixed) != calculation["source_digest"] or not all(
        v["current"] and v["source_current"] for v in fixed["inputs"]
    ):
        raise ProductWorkError("BOM、价格、目标、汇率或原文件已变化，请重新计算后申请冻结")
    if calculate(draft, fixed) != calculation["result"]:
        raise ProductWorkError("原计算与固定算法结果不一致，不能冻结")
    now = datetime.now(UTC).date()
    for entry in fixed["inputs"]:
        p = entry["payload"]
        if p.get("stage") == "quote" and not date.fromisoformat(
            p["valid_from"]
        ) <= now <= date.fromisoformat(p["valid_until"]):
            raise ProductWorkError("所选报价当前未生效或已过期，请重新取得有效依据并计算")
    previous = latest(c, context.tenant.id, project)
    if (previous["id"] if previous else None) != command.previous_freeze_id:
        raise ProductWorkError("项目当前冻结成本已变化，请核对替代范围后重新申请")
    person = _person(c, context, project, command.approver_user_id)
    if not is_allowed(person["role"], Action.COST_APPROVE):
        raise ProductWorkError("请选择具备成本批准权限的当前项目参与人")
    return {
        "calculation": _plain(dict(calculation)),
        "approver": _plain(dict(person)),
        "authority_document": metadata(
            document_row(c, context.tenant.id, project, command.evidence_id)
        ),
        "previous_freeze": None
        if previous is None
        else {
            "id": str(previous["id"]),
            "version": previous["version"],
            "calculation_digest": previous["calculation_digest"],
        },
        "command": command.model_dump(mode="json", exclude={"request_id", "expected_digest"}),
    }


def request_preview(
    c: Connection, context: AuthContext, project: UUID, command: FreezeDraft
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    value = ready(c, context, project, command)
    return {"basis": value, "digest": digest(value)}


def decision_preview(
    c: Connection, context: AuthContext, project: UUID, identity: UUID, command: FreezeDecision
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    request = row(c, context.tenant.id, project, tables.cost_freeze_requests, identity)
    d = tables.cost_freeze_decisions
    if c.execute(
        select(d.c.id).where(d.c.tenant_id == context.tenant.id, d.c.freeze_request_id == identity)
    ).first():
        raise ProductWorkError("此申请已经办理，请读取原结果")
    if command.action == "withdraw":
        if request["created_by_user_id"] != context.user.id:
            raise ProductWorkError("仅原申请人可撤回待批申请")
    else:
        if request["approver_user_id"] != context.user.id:
            raise ProductWorkError("须由申请中指定的批准人本人办理")
        KnowledgeCorrectionService._authorize(
            c, context.tenant.id, context.user.id, project, Action.COST_APPROVE
        )
        _person(c, context, project, context.user.id)
    current = None
    if command.action == "approve":
        if not all((command.scope_checked, command.cost_gap_checked, command.nre_checked)):
            raise ProductWorkError("批准前须核对构成范围、目标差异与NRE口径")
        current = ready(c, context, project, FreezeDraft.model_validate(request["payload"]))
        if current["authority_document"] != request["snapshot"]["authority_document"]:
            raise ProductWorkError("原批准依据文件已变化，请重新申请")
    value = {
        "request": _plain(dict(request)),
        "current": current,
        "decision": command.model_dump(mode="json", exclude={"request_id", "expected_digest"}),
    }
    return {"basis": value, "digest": digest(value)}


class CostFreezeService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(
        self,
        context: AuthContext,
        project: UUID,
        after: UUID | None = None,
        identity: UUID | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project)
            r, d, f = tables.cost_freeze_requests, tables.cost_freeze_decisions, tables.cost_freezes
            columns = (
                list(r.c)
                if identity
                else [
                    r.c.id,
                    r.c.approver_user_id,
                    r.c.created_by_user_id,
                    r.c.created_at,
                    r.c.snapshot["calculation"]["title"].as_string().label("title"),
                    r.c.snapshot["approver"]["display_name"].as_string().label("approver_name"),
                ]
            )
            q = select(*columns).where(
                r.c.tenant_id == context.tenant.id, r.c.project_id == project
            )
            if identity:
                q = q.where(r.c.id == identity)
            if after:
                cursor = row(c, context.tenant.id, project, r, after)
                q = q.where(
                    (r.c.created_at < cursor["created_at"])
                    | ((r.c.created_at == cursor["created_at"]) & (r.c.id < after))
                )
            records = list(
                c.execute(q.order_by(r.c.created_at.desc(), r.c.id.desc()).limit(21)).mappings()
            )
            values = []
            for request in records[:20]:
                decision = (
                    c.execute(
                        select(
                            *(list(d.c) if identity else [d.c.id, d.c.action, d.c.created_at])
                        ).where(
                            d.c.tenant_id == context.tenant.id,
                            d.c.freeze_request_id == request["id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                frozen = (
                    c.execute(
                        select(
                            *(list(f.c) if identity else [f.c.id, f.c.version, f.c.created_at])
                        ).where(
                            f.c.tenant_id == context.tenant.id,
                            f.c.freeze_request_id == request["id"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                values.append(
                    {
                        **_plain(dict(request)),
                        "decision": _plain(dict(decision)) if decision else None,
                        "freeze": _plain(dict(frozen)) if frozen else None,
                        "can_decide": decision is None
                        and context.user.id == request["approver_user_id"]
                        and is_allowed(context.user.role, Action.COST_APPROVE),
                        "can_withdraw": decision is None
                        and context.user.id == request["created_by_user_id"],
                    }
                )
            u, m = tables.users, tables.project_members
            candidates = (
                c.execute(
                    select(u.c.id, u.c.display_name)
                    .where(
                        u.c.tenant_id == context.tenant.id,
                        u.c.is_active.is_(True),
                        u.c.role.in_(("owner", "admin", "project_manager")),
                        or_(
                            u.c.role.in_(("owner", "admin")),
                            select(m.c.id)
                            .where(
                                m.c.tenant_id == context.tenant.id,
                                m.c.project_id == project,
                                m.c.user_id == u.c.id,
                            )
                            .exists(),
                        ),
                    )
                    .order_by(u.c.display_name, u.c.id)
                )
                .mappings()
                .all()
            )
            doc = tables.documents
            dq = select(doc.c.id, doc.c.filename).where(
                doc.c.tenant_id == context.tenant.id, doc.c.project_id == project
            )
            if search:
                needle = (
                    "%"
                    + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    + "%"
                )
                dq = dq.where(doc.c.filename.ilike(needle, escape="\\"))
            documents = (
                c.execute(dq.order_by(doc.c.created_at.desc(), doc.c.id.desc()).limit(201))
                .mappings()
                .all()
            )
            current = (
                c.execute(
                    select(
                        f.c.id,
                        f.c.version,
                        f.c.freeze_request_id,
                        f.c.previous_freeze_id,
                        f.c.calculation_digest,
                        f.c.created_at,
                        f.c.snapshot["calculation"]["title"].as_string().label("title"),
                    )
                    .where(f.c.tenant_id == context.tenant.id, f.c.project_id == project)
                    .order_by(f.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            return {
                "items": values,
                "current": _plain(dict(current)) if current else None,
                "next_cursor": str(records[19]["id"]) if len(records) > 20 else None,
                "approvers": [_plain(dict(v)) for v in candidates],
                "documents": [_plain(dict(v)) for v in documents[:200]],
                "documents_more": len(documents) > 200,
            }

    def preview(self, context: AuthContext, project: UUID, command: FreezeDraft) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return request_preview(c, context, project, command)

    def request(
        self, context: AuthContext, project: UUID, command: FreezeRequest
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.cost_freeze_requests
            signature = digest(command.model_dump(mode="json"))
            old = (
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
            if old:
                if old["project_id"] != project or old["request_digest"] != signature:
                    raise ProductWorkError("此请求已用于不同冻结申请")
                return _plain(dict(old))
            observed = request_preview(c, context, project, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("申请依据已变化，请重新预览")
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        rollup_id=command.rollup_id,
                        previous_freeze_id=command.previous_freeze_id,
                        approver_user_id=command.approver_user_id,
                        evidence_id=command.evidence_id,
                        payload=observed["basis"]["command"],
                        snapshot=observed["basis"],
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=func.clock_timestamp(),
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
                record_id=saved["id"],
                record_type="cost_freeze_request",
                action="requested",
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))

    def preview_decision(
        self, context: AuthContext, project: UUID, identity: UUID, command: FreezeDecision
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return decision_preview(c, context, project, identity, command)

    def decide(
        self, context: AuthContext, project: UUID, identity: UUID, command: FreezeDecide
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.cost_freeze_decisions
            signature = digest({"id": str(identity), "command": command.model_dump(mode="json")})
            old = (
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
            if old:
                if old["project_id"] != project or old["request_digest"] != signature:
                    raise ProductWorkError("此请求已用于不同冻结裁决")
                return _plain(dict(old))
            observed = decision_preview(c, context, project, identity, command)
            if observed["digest"] != command.expected_digest:
                raise ProductWorkError("冻结前依据已变化，请重新预览")
            request = observed["basis"]["request"]
            saved = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        freeze_request_id=identity,
                        action=command.action,
                        reason=command.reason,
                        snapshot=observed["basis"],
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=func.clock_timestamp(),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            if command.action == "approve":
                current = observed["basis"]["current"]
                calculation = current["calculation"]
                c.execute(
                    tables.cost_freezes.insert().values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        freeze_request_id=identity,
                        decision_id=saved["id"],
                        rollup_id=UUID(request["rollup_id"]),
                        previous_freeze_id=UUID(request["previous_freeze_id"])
                        if request["previous_freeze_id"]
                        else None,
                        version=(
                            current["previous_freeze"]["version"]
                            if current["previous_freeze"]
                            else 0
                        )
                        + 1,
                        calculation_digest=calculation["calculation_digest"],
                        snapshot={
                            "calculation": calculation,
                            "request": request,
                            "approval": _plain(dict(saved)),
                        },
                        approved_by_user_id=context.user.id,
                        created_at=func.clock_timestamp(),
                    )
                )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                actor_user_id=context.user.id,
                record_id=identity,
                record_type="cost_freeze_request",
                action=command.action,
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
