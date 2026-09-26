"""Versioned results and independent named receipt of risk follow-up work."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, Select, or_, select, text

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.issue_intake_compensation_results import (
    ResultEvidence,
    current_evidence,
    document_snapshot,
)
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.risk_followups import audit_query, authorize, basis
from app.domain.risk_references import KINDS
from app.domain.risks import RiskNotFoundError, RiskVersionConflictError
from app.domain.tasks import TaskService
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class RiskResultError(ValueError):
    pass


class ReferenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["task", "initialization", "meeting", "gate", "handoff"]
    id: UUID
    outcome: Literal["unaffected", "handled", "needs_work"]
    explanation: str = Field(min_length=1, max_length=4000)
    evidence: str = Field(min_length=1, max_length=4000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)


class ReceiverChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    previous_submission_id: UUID
    reason: str = Field(min_length=1, max_length=4000)


class ResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["submitted", "accepted", "returned"]
    submission_id: UUID | None = None
    receiver_user_id: UUID | None = None
    summary: str = Field(min_length=1, max_length=10000)
    references: list[ReferenceResult] = Field(default_factory=list, max_length=1000)
    evidence: list[ResultEvidence] = Field(default_factory=list, max_length=10)
    receiver_change: ReceiverChange | None = None

    @model_validator(mode="after")
    def action_fields(self) -> Self:
        if self.action == "submitted":
            if not self.receiver_user_id or self.submission_id:
                raise ValueError("提交结果须指定接收人")
        elif (
            not self.submission_id
            or self.receiver_user_id
            or self.references
            or self.evidence
            or self.receiver_change
        ):
            raise ValueError("接收或退回须对应原提交，不修改处理人的逐项结果")
        if len({(r.kind, r.id) for r in self.references}) != len(self.references):
            raise ValueError("每条引用只填写一次")
        if len({item.document_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("同一证据文件请合并对应说明")
        if any(len(set(item.document_ids)) != len(item.document_ids) for item in self.references):
            raise ValueError("同一引用内不要重复关联同一文件")
        self.references.sort(key=lambda r: (r.kind, str(r.id)))
        return self


def freeze_evidence(
    c: Connection, ctx: AuthContext, project: UUID, references: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    t = tables.documents
    c.execute(
        select(t.c.id)
        .where(
            t.c.tenant_id == ctx.tenant.id,
            t.c.project_id == project,
            t.c.id.in_([UUID(item["document_id"]) for item in references]),
        )
        .order_by(t.c.id)
        .with_for_update()
    ).all()
    current = current_evidence(c, ctx.tenant.id, project, references)
    if any(item["changed"] for item in current):
        raise RiskResultError("所选证据文件已变化或不可读取，请重新选取并核对后提交")
    return [
        {
            "document_id": item["document_id"],
            "expected_digest": item["expected_digest"],
            "correspondence": item["correspondence"],
            "snapshot": item["current"],
        }
        for item in current
    ]


def evidence_options(
    engine: Engine,
    ctx: AuthContext,
    project: UUID,
    risk: UUID,
    task: UUID,
    search: str = "",
    before_created_at: datetime | None = None,
    before_id: UUID | None = None,
) -> dict[str, Any]:
    if (before_created_at is None) != (before_id is None):
        raise RiskResultError("文件分页位置不完整，请重新查询")
    with engine.connect() as c:
        authorize(c, ctx, project, Action.WORK_ITEM_VIEW)
        _state(c, ctx, project, risk, task)
        t = tables.documents
        q = select(t).where(
            t.c.tenant_id == ctx.tenant.id,
            t.c.project_id == project,
            t.c.classification == "internal",
        )
        if search.strip():
            q = q.where(t.c.filename.icontains(search.strip(), autoescape=True))
        if before_created_at is not None:
            q = q.where(
                or_(
                    t.c.created_at < before_created_at,
                    (t.c.created_at == before_created_at) & (t.c.id < before_id),
                )
            )
        docs = (
            c.execute(q.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(51)).mappings().all()
        )
        items = []
        for doc in docs[:50]:
            snapshot = document_snapshot(doc)
            items.append(
                snapshot
                | {
                    "digest": digest(snapshot),
                    "href": f"/projects?project={project}&tab=documents&entity_id={doc['id']}",
                }
            )
        return {
            "items": items,
            "next": {
                "before_created_at": docs[49]["created_at"].isoformat(),
                "before_id": str(docs[49]["id"]),
            }
            if len(docs) > 50
            else None,
        }


def _state(
    c: Connection, ctx: AuthContext, project: UUID, risk: UUID, task: UUID
) -> dict[str, Any]:
    origin = (
        c.execute(
            audit_query(ctx, project, risk).where(
                tables.audit_log.c.entity_id == task,
            )
        )
        .mappings()
        .one_or_none()
    )
    if origin is None:
        raise RiskNotFoundError
    saved = origin["context"]["risk_followup"]
    current = basis(c, ctx, project, risk)
    original = saved["basis"]
    refs: dict[tuple[str, str], dict[str, Any]] = {}
    for side, source in (("original", original), ("current", current)):
        for group in source["references"]:
            if group["items"]:
                authorize(c, ctx, project, KINDS[group["kind"]][1])
            for item in group["items"]:
                if group["kind"] == "task" and item["id"] == str(task):
                    continue
                key = (group["kind"], item["id"])
                refs.setdefault(
                    key,
                    {
                        "kind": key[0],
                        "id": key[1],
                        "label": group["label"],
                        "original": None,
                        "current": None,
                    },
                )[side] = item
    t = tables.tasks
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == task
            )
        )
        .mappings()
        .one()
    )
    result_table = tables.risk_followup_results
    latest = (
        c.execute(
            select(result_table)
            .where(result_table.c.tenant_id == ctx.tenant.id, result_table.c.task_id == task)
            .order_by(result_table.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    frozen = {
        "risk": current["risk"],
        "task": _plain(dict(row)),
        "references": [refs[key] for key in sorted(refs)],
    }
    return {
        "origin_id": origin["id"],
        "basis": frozen,
        "latest": _plain(latest) if latest else None,
        "digest": digest({"basis": frozen, "latest_id": str(latest["id"]) if latest else None}),
    }


def _visible(c: Connection, ctx: AuthContext, project: UUID, row: Any) -> dict[str, Any]:
    for item in row["basis"]["references"]:
        authorize(c, ctx, project, KINDS[item["kind"]][1])
    value = _plain(dict(row))
    evidence = current_evidence(c, ctx.tenant.id, project, value["payload"].get("evidence", []))
    for item in evidence:
        if item["current"] is None:
            item.pop("snapshot", None)
    value["payload"]["evidence"] = evidence
    return value


def read(engine: Engine, ctx: AuthContext, project: UUID, risk: UUID, task: UUID) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        authorize(c, ctx, project, Action.WORK_ITEM_VIEW)
        state = _state(c, ctx, project, risk, task)
        t = tables.risk_followup_results
        history = (
            c.execute(
                select(t)
                .where(t.c.tenant_id == ctx.tenant.id, t.c.task_id == task)
                .order_by(t.c.revision.desc())
                .limit(21)
            )
            .mappings()
            .all()
        )
        latest = state["latest"]
        submission = (
            latest
            if latest and latest["action"] == "submitted"
            else next(
                (
                    dict(row)
                    for row in history
                    if latest and str(row["id"]) == latest["submission_id"]
                ),
                None,
            )
        )
        u, m = tables.users, tables.project_members
        people = [
            dict(r)
            for r in c.execute(
                select(u.c.id, u.c.display_name)
                .join(m, (m.c.tenant_id == u.c.tenant_id) & (m.c.user_id == u.c.id))
                .where(
                    m.c.tenant_id == ctx.tenant.id,
                    m.c.project_id == project,
                    u.c.is_active.is_(True),
                    u.c.role.in_(["owner", "admin", "project_manager", "engineer", "quality"]),
                )
                .order_by(u.c.display_name, u.c.id)
            ).mappings()
        ]
        may_edit = True
        try:
            authorize(c, ctx, project, Action.WORK_ITEM_EDIT)
        except KnowledgeAccessError:
            may_edit = False
        task_state = state["basis"]["task"]
        visible_submission = _visible(c, ctx, project, submission) if submission else None
        evidence_changed = (
            bool(
                submission
                and (
                    not submission["payload"].get("evidence")
                    or any(item["changed"] for item in visible_submission["payload"]["evidence"])
                )
            )
            if visible_submission
            else False
        )
        return {
            **state,
            "submission": visible_submission,
            "latest": _visible(c, ctx, project, latest) if latest else None,
            "evidence_changed": evidence_changed,
            "source_changed": bool(latest and digest(latest["basis"]) != digest(state["basis"])),
            "people": people,
            "actor_id": str(ctx.user.id),
            "can_submit": may_edit
            and task_state["assignee_user_id"] == str(ctx.user.id)
            and task_state["status"] == "done"
            and bool(task_state["completion_evidence_ref"]),
            "can_change_receiver": may_edit
            and task_state["assignee_user_id"] == str(ctx.user.id)
            and task_state["status"] == "done"
            and bool(task_state["completion_evidence_ref"])
            and bool(latest and latest["action"] == "submitted")
            and not evidence_changed
            and bool(latest and digest(latest["basis"]) == digest(state["basis"])),
            "can_review": may_edit
            and bool(
                latest
                and latest["action"] == "submitted"
                and latest["receiver_user_id"] == str(ctx.user.id)
                and task_state["assignee_user_id"] != str(ctx.user.id)
            ),
            "history": [_visible(c, ctx, project, row) for row in history[:20]],
            "has_more": len(history) > 20,
        }


def require_receiver_change(
    body: ResultRequest, latest: Any, current_basis: dict[str, Any]
) -> None:
    change = body.receiver_change
    if (
        not change
        or not latest
        or latest["action"] != "submitted"
        or latest["id"] != str(change.previous_submission_id)
    ):
        raise RiskResultError("只能对当前尚未接收的提交更换接收人，请刷新原结果")
    if str(body.receiver_user_id) == latest["receiver_user_id"]:
        raise RiskResultError("请选择与原接收人不同的独立项目成员")
    if digest(latest["basis"]) != digest(current_basis):
        raise RiskResultError("原业务依据已变化，请核对并重新提交完整结果后再指定接收人")
    original = latest["payload"]
    original_refs = sorted(original["references"], key=lambda r: (r["kind"], r["id"]))
    expected = {
        "summary": original["summary"],
        "references": [
            ReferenceResult.model_validate(r).model_dump(mode="json") for r in original_refs
        ],
        "evidence": [
            {key: item[key] for key in ("document_id", "expected_digest", "correspondence")}
            for item in original.get("evidence", [])
        ],
    }
    actual = body.model_dump(mode="json", include={"summary", "references", "evidence"})
    if not expected["evidence"] or actual != expected:
        raise RiskResultError(
            "更换接收人须保留原结果、逐项结论和固定证据；内容变化请使用完整结果提交"
        )


def save(
    engine: Engine, ctx: AuthContext, project: UUID, risk: UUID, task: UUID, body: ResultRequest
) -> dict[str, Any]:
    signing_payload = body.model_dump(mode="json")
    # Preserve replay of requests recorded before file bindings were introduced.
    if "evidence" not in body.model_fields_set:
        signing_payload.pop("evidence")
    for request_ref, serialized in zip(body.references, signing_payload["references"], strict=True):
        if "document_ids" not in request_ref.model_fields_set:
            serialized.pop("document_ids")
    if "receiver_change" not in body.model_fields_set:
        signing_payload.pop("receiver_change")
    signature = digest(signing_payload)
    with engine.begin() as c:
        authorize(c, ctx, project, Action.WORK_ITEM_EDIT)
        c.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"risk-result:{ctx.tenant.id}:{ctx.user.id}:{body.request_id}"},
        )
        t = tables.risk_followup_results
        prior = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.actor_user_id == ctx.user.id,
                    t.c.request_id == body.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if prior is not None:
            if (
                prior["project_id"] != project
                or prior["risk_id"] != risk
                or prior["task_id"] != task
                or prior["request_digest"] != signature
            ):
                raise RiskVersionConflictError
            return _visible(c, ctx, project, prior)
        if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
            raise RiskNotFoundError
        state = _state(c, ctx, project, risk, task)
        if state["digest"] != body.expected_digest:
            raise RiskVersionConflictError
        task_state, latest = state["basis"]["task"], state["latest"]
        evidence = []
        if body.action == "submitted":
            if (
                task_state["assignee_user_id"] != str(ctx.user.id)
                or task_state["status"] != "done"
                or not task_state["completion_evidence_ref"]
            ):
                raise RiskResultError("须由当前任务负责人在完成任务并登记实际证据后提交处理结果")
            if body.receiver_user_id == ctx.user.id:
                raise RiskResultError("请选择另一位项目成员接收处理结果")
            TaskService._validate_member(
                c, tenant_id=ctx.tenant.id, project_id=project, user_id=body.receiver_user_id
            )
            if body.receiver_change:
                require_receiver_change(body, latest, state["basis"])
            keys = {(item["kind"], item["id"]) for item in state["basis"]["references"]}
            if keys != {(item.kind, str(item.id)) for item in body.references}:
                raise RiskResultError("请逐项核对原引用与当前新增或解除的引用，不遗漏处理范围")
            if not body.evidence:
                raise RiskResultError(
                    "请选择至少一份本项目实际证据文件，并说明与本次结果的对应关系"
                )
            selected_ids = {item.document_id for item in body.evidence}
            for item in body.references:
                if not set(item.document_ids) <= selected_ids:
                    raise RiskResultError("逐项引用所用文件必须在本次所选证据中")
                if item.outcome != "needs_work" and not item.document_ids:
                    raise RiskResultError("已处理或不受影响的结论须关联本次实际证据文件")
            evidence = freeze_evidence(
                c, ctx, project, [item.model_dump(mode="json") for item in body.evidence]
            )
            receiver = body.receiver_user_id
        else:
            if (
                not latest
                or latest["action"] != "submitted"
                or latest["id"] != str(body.submission_id)
            ):
                raise RiskResultError("此结果已被接收、退回或被新提交替代，请刷新")
            if (
                latest["receiver_user_id"] != str(ctx.user.id)
                or latest["actor_user_id"] == str(ctx.user.id)
                or task_state["assignee_user_id"] == str(ctx.user.id)
            ):
                raise KnowledgeAccessError("须由本次指定的独立接收人本人办理")
            if body.action == "accepted":
                if not latest["payload"].get("evidence"):
                    raise RiskResultError("原结果尚未固定项目证据文件，请退回补充后重新提交")
                freeze_evidence(c, ctx, project, latest["payload"]["evidence"])
                if digest(latest["basis"]) != digest(state["basis"]):
                    raise RiskResultError("提交后的风险、任务或引用已变化，请退回重新核对后提交")
                if any(item["outcome"] == "needs_work" for item in latest["payload"]["references"]):
                    raise RiskResultError("仍有需要继续处理的引用，请退回补齐后再接收")
            receiver = ctx.user.id
        now, identity = datetime.now(UTC), uuid4()
        c.execute(
            tables.tasks.update()
            .where(
                tables.tasks.c.tenant_id == ctx.tenant.id,
                tables.tasks.c.project_id == project,
                tables.tasks.c.id == task,
            )
            .values(updated_at=now)
        )
        updated = _state(c, ctx, project, risk, task)
        receiver_name = c.execute(
            select(tables.users.c.display_name).where(
                tables.users.c.tenant_id == ctx.tenant.id, tables.users.c.id == receiver
            )
        ).scalar_one()
        payload = body.model_dump(mode="json") | {
            "actor_name": ctx.user.display_name,
            "receiver_name": receiver_name,
        }
        if body.action == "submitted":
            payload["evidence"] = evidence
            payload["evidence_version"] = 2
            if body.receiver_change:
                payload["receiver_change"] = body.receiver_change.model_dump(mode="json") | {
                    "previous_receiver_user_id": latest["receiver_user_id"],
                    "previous_receiver_name": latest["payload"].get("receiver_name"),
                    "previous_revision": latest["revision"],
                }
        row = (
            c.execute(
                t.insert()
                .values(
                    id=identity,
                    tenant_id=ctx.tenant.id,
                    project_id=project,
                    risk_id=risk,
                    task_id=task,
                    origin_audit_id=state["origin_id"],
                    revision=latest["revision"] + 1 if latest else 1,
                    action=body.action,
                    submission_id=body.submission_id,
                    actor_user_id=ctx.user.id,
                    receiver_user_id=receiver,
                    request_id=body.request_id,
                    request_digest=signature,
                    basis=updated["basis"],
                    payload=payload,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        EventAuditWriter(
            c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
        ).record(
            EventDraft(
                event_id=f"risk-followup-result:{identity}",
                event_type="TASK_UPDATED",
                source="task_service",
                entity_id=task,
                payload={"changed_fields": ["updated_at"], "status": task_state["status"]},
                occurred_at=now,
            ),
            AuditDraft(
                action=f"risk.followup_result_{body.action}",
                before_snapshot={
                    "updated_at": task_state["updated_at"],
                    "result_id": latest["id"] if latest else None,
                },
                after_snapshot={
                    "updated_at": now.isoformat(),
                    "result_id": str(identity),
                    "action": body.action,
                },
                context={
                    "risk_id": str(risk),
                    "request_id": str(body.request_id),
                    **(
                        {"receiver_change": payload["receiver_change"]}
                        if body.receiver_change
                        else {}
                    ),
                },
            ),
        )
        return _visible(c, ctx, project, row)


def read_request(
    engine: Engine, ctx: AuthContext, project: UUID, risk: UUID, task: UUID, request: UUID
) -> dict[str, Any]:
    with engine.connect() as c:
        authorize(c, ctx, project, Action.WORK_ITEM_VIEW)
        t = tables.risk_followup_results
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.project_id == project,
                    t.c.risk_id == risk,
                    t.c.task_id == task,
                    t.c.actor_user_id == ctx.user.id,
                    t.c.request_id == request,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RiskNotFoundError
        return _visible(c, ctx, project, row)


def inbox_statement(
    c: Connection, tenant_id: UUID, user_id: UUID, role: Role
) -> Select[Any] | None:
    from sqlalchemy import exists, func, literal, union_all

    from app.domain.knowledge_push import knowledge_scope

    if not is_allowed(role, Action.WORK_ITEM_VIEW):
        return None
    unrestricted, principals = knowledge_scope(c, tenant_id, user_id)
    t, p, task, a = (
        tables.risk_followup_results,
        tables.projects,
        tables.tasks,
        tables.audit_log,
    )
    newer = t.alias("newer_risk_result")
    review = select(
        task.c.id,
        t.c.risk_id,
        t.c.task_id,
        t.c.project_id,
        task.c.title,
        p.c.code.label("project_code"),
        p.c.name.label("project_name"),
        t.c.created_at,
        literal("review").label("mode"),
    ).select_from(
        t.join(p, (p.c.tenant_id == t.c.tenant_id) & (p.c.id == t.c.project_id)).join(
            task, (task.c.tenant_id == t.c.tenant_id) & (task.c.id == t.c.task_id)
        )
    )
    review = review.where(
        t.c.tenant_id == tenant_id,
        t.c.receiver_user_id == user_id,
        t.c.action == "submitted",
        ~exists(
            select(newer.c.id).where(
                newer.c.tenant_id == t.c.tenant_id,
                newer.c.task_id == t.c.task_id,
                newer.c.revision > t.c.revision,
            )
        ),
    )
    latest_action = (
        select(t.c.action)
        .where(t.c.tenant_id == task.c.tenant_id, t.c.task_id == task.c.id)
        .order_by(t.c.revision.desc())
        .limit(1)
        .correlate(task)
        .scalar_subquery()
    )
    submit = (
        select(
            task.c.id,
            task.c.source_entity_id.label("risk_id"),
            task.c.id.label("task_id"),
            task.c.project_id,
            task.c.title,
            p.c.code.label("project_code"),
            p.c.name.label("project_name"),
            task.c.updated_at.label("created_at"),
            literal("submit").label("mode"),
        )
        .select_from(
            task.join(p, (p.c.tenant_id == task.c.tenant_id) & (p.c.id == task.c.project_id))
        )
        .where(
            task.c.tenant_id == tenant_id,
            task.c.assignee_user_id == user_id,
            task.c.kind == "risk_action",
            task.c.status == "done",
            func.coalesce(latest_action, "").in_(["", "returned"]),
            exists(
                select(a.c.id).where(
                    a.c.tenant_id == task.c.tenant_id,
                    a.c.project_id == task.c.project_id,
                    a.c.entity_id == task.c.id,
                    a.c.action == "task.create",
                    a.c.context["risk_followup"]["request_id"].as_string().is_not(None),
                )
            ),
        )
    )
    combined = union_all(review, submit).subquery("risk_result_work")
    q = select(combined)
    if not unrestricted:
        m = tables.project_members
        q = q.where(
            combined.c.project_id.in_(
                select(m.c.project_id).where(
                    m.c.tenant_id == tenant_id, m.c.user_id.in_(principals)
                )
            )
        )
    return q


def pending_reviews(engine: Engine, ctx: AuthContext, offset: int) -> dict[str, Any]:
    from sqlalchemy import func

    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        q = inbox_statement(c, ctx.tenant.id, ctx.user.id, Role(ctx.user.role))
        if q is None:
            raise KnowledgeAccessError
        columns = q.selected_columns
        count = c.execute(select(func.count()).select_from(q.subquery())).scalar_one()
        rows = (
            c.execute(q.order_by(columns.created_at, columns.id).offset(offset).limit(51))
            .mappings()
            .all()
        )
        return {
            "count": count,
            "offset": offset,
            "next_offset": offset + 50 if len(rows) > 50 else None,
            "items": [_plain(dict(row)) for row in rows[:50]],
        }
