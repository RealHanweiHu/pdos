"""Named business repair results using original Issue writes and original project evidence."""

from datetime import date, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.issue_intake_compensations import task_view
from app.domain.issue_intake_corrections import public_source, source_state
from app.domain.issue_intake_reference_reviews import (
    BusinessReferenceReview,
    freeze_reviews,
    resolve,
    visible_reviews,
)
from app.domain.issue_intake_reuse import target_snapshot
from app.domain.issues import IssueFourEyesError, IssueService, IssueTerminalError, IssueUpdate
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class IssueRepair(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=20000)
    root_cause: str | None = Field(default=None, max_length=20000)
    resolution: str | None = Field(default=None, max_length=20000)
    issue_type: (
        Literal["engineering", "quality", "supplier", "test_failure", "certification"] | None
    ) = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    target_date: date | None = None

    @field_validator("description", "root_cause", "resolution", mode="before")
    @classmethod
    def nullable_text(cls, value: Any) -> Any:
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode="after")
    def values(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("请明确需要修正的字段")
        if any(
            key in self.model_fields_set and getattr(self, key) is None
            for key in ("title", "issue_type", "severity")
        ):
            raise ValueError("标题、问题类型和严重度不可清空")
        return self


class ResultEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    correspondence: str = Field(min_length=1, max_length=4000)


class CompensationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["recorded", "issue_corrected", "no_change_needed", "needs_follow_up"]
    summary: str = Field(min_length=1, max_length=10000)
    criteria_response: str = Field(min_length=1, max_length=10000)
    remaining: str = Field(min_length=1, max_length=10000)
    changes: IssueRepair | None = None
    evidence: list[ResultEvidence] = Field(default_factory=list, max_length=10)

    business_references: list[BusinessReferenceReview] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def references(self) -> Self:
        keys = [(item.kind, item.id, item.path_id) for item in self.business_references]
        if len(set(keys)) != len(keys):
            raise ValueError("同一业务引用路径请合并核对结果")
        self.business_references.sort(key=lambda item: (item.kind, str(item.id), str(item.path_id)))
        if len({item.document_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("同一文件请合并说明，不重复引用")
        if self.outcome in {"issue_corrected", "no_change_needed"} and not self.evidence:
            raise ValueError("请选择实际原文件并说明如何支持本次核对结果")
        return self


def document_snapshot(row: Any) -> dict[str, Any]:
    return _plain(
        {
            key: row[key]
            for key in (
                "id",
                "project_id",
                "filename",
                "sha256",
                "size_bytes",
                "classification",
                "created_at",
            )
        }
    )


def result_state(c: Connection, ctx: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
    KnowledgeCorrectionService._authorize(
        c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
    )
    t = tables.issue_intake_compensations
    binding = (
        c.execute(
            select(t).where(
                t.c.tenant_id == ctx.tenant.id, t.c.project_id == project, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if binding is None:
        raise ConversationError("本项目没有这条导入补偿任务安排")
    issue = (
        c.execute(
            select(tables.issues).where(
                tables.issues.c.tenant_id == ctx.tenant.id,
                tables.issues.c.project_id == project,
                tables.issues.c.id == binding["issue_id"],
            )
        )
        .mappings()
        .one()
    )
    task = (
        c.execute(
            select(tables.tasks).where(
                tables.tasks.c.tenant_id == ctx.tenant.id,
                tables.tasks.c.project_id == project,
                tables.tasks.c.id == binding["task_id"],
            )
        )
        .mappings()
        .one()
    )
    source = (
        c.execute(
            select(tables.issue_intake_rows).where(
                tables.issue_intake_rows.c.tenant_id == ctx.tenant.id,
                tables.issue_intake_rows.c.id == binding["source_row_id"],
            )
        )
        .mappings()
        .one()
    )
    r = tables.issue_intake_compensation_results
    latest = c.execute(
        select(r.c.revision)
        .where(r.c.tenant_id == ctx.tenant.id, r.c.binding_id == identity)
        .order_by(r.c.revision.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "binding": _plain(binding),
        "issue": target_snapshot(issue),
        "task": task_view(task),
        "source": public_source(source),
        "current_source": source_state(c, ctx.tenant.id, source),
        "result_revision": latest or 0,
    }


def current_evidence(
    c: Connection, tenant: UUID, project: UUID, references: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ids = [UUID(str(item["document_id"])) for item in references]
    t = tables.documents
    documents = (
        {
            str(row["id"]): document_snapshot(row)
            for row in c.execute(
                select(t).where(
                    t.c.tenant_id == tenant,
                    t.c.project_id == project,
                    t.c.id.in_(ids),
                    t.c.classification == "internal",
                )
            ).mappings()
        }
        if ids
        else {}
    )
    return [
        item
        | {
            "current": documents.get(str(item["document_id"])),
            "changed": str(item["document_id"]) not in documents
            or digest(documents[str(item["document_id"])]) != item["expected_digest"],
        }
        for item in references
    ]


def public_result(row: Any) -> dict[str, Any]:
    value = _plain(row)
    # Business snapshots are returned only through the current per-domain visibility check.
    value["context_snapshot"].pop("business_references", None)
    return value


class IssueIntakeCompensationResults:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(
        self, ctx: AuthContext, project: UUID, identity: UUID, *, before_revision: int | None = None
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            basis = result_state(c, ctx, project, identity)
            t = tables.issue_intake_compensation_results
            query = (
                select(t, tables.users.c.display_name.label("actor_name"))
                .join(
                    tables.users,
                    (tables.users.c.tenant_id == t.c.tenant_id)
                    & (tables.users.c.id == t.c.created_by_user_id),
                )
                .where(t.c.tenant_id == ctx.tenant.id, t.c.binding_id == identity)
            )
            if before_revision is not None:
                query = query.where(t.c.revision < before_revision)
            rows = c.execute(query.order_by(t.c.revision.desc()).limit(21)).mappings().all()
            requested = [
                item
                for row in rows[:20]
                for item in row["context_snapshot"].get("business_references", [])
            ]
            reference_states = resolve(
                c, ctx, project, basis["source"], UUID(basis["issue"]["id"]), requested
            )
            items = []
            for row in rows[:20]:
                evidence = current_evidence(c, ctx.tenant.id, project, row["evidence_snapshot"])
                items.append(
                    public_result(row)
                    | {
                        "source_current": row["source_revision"]
                        == basis["current_source"]["revision"],
                        "issue_current": row["after_snapshot"] == basis["issue"],
                        "evidence": evidence,
                        "business_references": visible_reviews(
                            row["context_snapshot"].get("business_references", []), reference_states
                        ),
                    }
                )
            return {
                "basis": basis,
                "digest": digest(basis),
                "items": items,
                "next_before_revision": rows[19]["revision"] if len(rows) > 20 else None,
            }

    def evidence(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        *,
        search: str = "",
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> dict[str, Any]:
        if (before_created_at is None) != (before_id is None):
            raise ConversationError("文件分页位置不完整，请重新查询")
        with self.engine.connect() as c:
            state = result_state(c, ctx, project, identity)
            t = tables.documents
            query = select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.project_id == project,
                t.c.classification == "internal",
            )
            if search.strip():
                query = query.where(t.c.filename.icontains(search.strip(), autoescape=True))
            if before_created_at is not None:
                query = query.where(
                    or_(
                        t.c.created_at < before_created_at,
                        (t.c.created_at == before_created_at) & (t.c.id < before_id),
                    )
                )
            rows = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(51))
                .mappings()
                .all()
            )
            original = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.id == UUID(state["source"]["document_id"]),
                        t.c.classification == "internal",
                    )
                )
                .mappings()
                .one_or_none()
            )

            def view(row: Any) -> dict[str, Any]:
                value = document_snapshot(row)
                return value | {
                    "digest": digest(value),
                    "href": f"/projects?project={project}&tab=documents&entity_id={row['id']}",
                }

            return {
                "items": [view(row) for row in rows[:50]],
                "original": view(original) if original else None,
                "next": {
                    "before_created_at": rows[49]["created_at"].isoformat(),
                    "before_id": str(rows[49]["id"]),
                }
                if len(rows) > 50
                else None,
            }

    def save(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: CompensationResult
    ) -> dict[str, Any]:
        excluded = {"request_id"}
        if not body.business_references:
            excluded.add(
                "business_references"
            )  # Preserve requests recorded before reference reviews.
        signature = digest(body.model_dump(mode="json", exclude=excluded))
        with self.engine.begin() as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_EDIT
            )
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            t = tables.issue_intake_compensation_results
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.binding_id == identity,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("本请求已对应其他办理结果，请读取原回执")
                return public_result(prior)
            basis = result_state(c, ctx, project, identity)
            if digest(basis) != body.expected_digest:
                raise ConversationError("任务、来源、问题或前次结果已变化，请刷新后重新核对")
            refs = current_evidence(
                c, ctx.tenant.id, project, [item.model_dump(mode="json") for item in body.evidence]
            )
            if any(item["changed"] for item in refs):
                raise ConversationError("所选文件已变化或不可读取，请重新选择实际证据")
            business_references = freeze_reviews(
                c,
                ctx,
                project,
                basis["source"],
                UUID(basis["issue"]["id"]),
                body.business_references,
            )
            before = basis["issue"]
            changes = {
                key: value
                for key, value in (
                    body.changes.model_dump(exclude_unset=True) if body.changes else {}
                ).items()
                if _plain({"value": value})["value"] != before.get(key)
            }
            if body.outcome == "no_change_needed" and changes:
                raise ConversationError("无需改值的结果不能同时提交问题字段修改")
            if "target_date" in changes:
                KnowledgeCorrectionService._authorize(
                    c, ctx.tenant.id, ctx.user.id, project, Action.ISSUE_ASSIGN
                )
            if changes:
                try:
                    IssueService(self.engine).update(
                        tenant_id=ctx.tenant.id,
                        actor_user_id=ctx.user.id,
                        project_id=project,
                        issue_id=UUID(before["id"]),
                        patch=IssueUpdate(changes=changes),
                        connection=c,
                    )
                except IssueTerminalError as error:
                    raise ConversationError(
                        "问题已关闭，请先沿原流程受控重开，再修正内容"
                    ) from error
                except IssueFourEyesError as error:
                    raise ConversationError(
                        "修正后的高严重度问题仍须独立负责人和验证人，请先沿原流程调整"
                    ) from error
            after_row = (
                c.execute(
                    select(tables.issues).where(
                        tables.issues.c.tenant_id == ctx.tenant.id,
                        tables.issues.c.project_id == project,
                        tables.issues.c.id == UUID(before["id"]),
                    )
                )
                .mappings()
                .one()
            )
            after = target_snapshot(after_row)
            original = basis["binding"]["snapshot"]["issue"]
            if (
                body.outcome == "issue_corrected"
                and not changes
                and not any(
                    after.get(key) != original.get(key) for key in set(after) - {"updated_at"}
                )
            ):
                raise ConversationError("原问题尚无可核对的业务变化，可先登记进展或后续要求")
            identity_result = uuid4()
            stored_refs = [
                {
                    "document_id": item["document_id"],
                    "expected_digest": item["expected_digest"],
                    "correspondence": item["correspondence"],
                    "snapshot": item["current"],
                }
                for item in refs
            ]
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity_result,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        binding_id=identity,
                        source_row_id=UUID(basis["source"]["id"]),
                        source_revision=basis["current_source"]["revision"],
                        revision=basis["result_revision"] + 1,
                        request_id=body.request_id,
                        request_digest=signature,
                        outcome=body.outcome,
                        summary=body.summary,
                        criteria_response=body.criteria_response,
                        remaining=body.remaining,
                        before_snapshot=before,
                        after_snapshot=after,
                        context_snapshot={
                            "business_references": business_references,
                            "task": basis["task"],
                            "source": basis["current_source"],
                            "completion_criteria": basis["binding"]["snapshot"][
                                "completion_criteria"
                            ],
                        },
                        evidence_snapshot=stored_refs,
                        created_by_user_id=ctx.user.id,
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
                    event_id=f"issue-intake-compensation-result:{identity_result}",
                    event_type="ISSUE_INTAKE_SOURCE_RECORDED",
                    source="issue_intake_service",
                    entity_id=UUID(basis["source"]["id"]),
                    payload={
                        "source_row_id": basis["source"]["id"],
                        "record_id": str(identity_result),
                        "action": "result_recorded",
                    },
                ),
                AuditDraft(
                    action="issue_intake.compensation_result",
                    before_snapshot={"issue": before},
                    after_snapshot={"issue": after},
                    context={
                        "binding_id": str(identity),
                        "result_id": str(identity_result),
                        "outcome": body.outcome,
                        "changed_fields": sorted(changes),
                    },
                ),
            )
            return public_result(row)
