"""Human-confirmed Issue intake with exact original-row reuse and durable receipts."""

import hashlib
from datetime import date
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversation_attachments import ConversationAttachmentService
from app.domain.conversations import ConversationError
from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentService
from app.domain.intake_ai_imports import (
    cited_sources,
    finish_import,
    read_contents,
    share_documents,
)
from app.domain.issue_intake_corrections import IssueIntakeCorrections, source_state, source_states
from app.domain.issue_intake_preview import (
    IssueIntakePreviews,
    canonical_row,
    check_source,
    source_identity,
)
from app.domain.issue_intake_reuse import IssueIntakeReuse, target_snapshot
from app.domain.issues import IssueDraft, IssueService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class IssueIntakeConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: list[int] = Field(min_length=1, max_length=200)
    issue_type: Literal["engineering", "quality", "supplier", "test_failure", "certification"]
    severity: Literal["low", "medium", "high", "critical"]
    publish_to_project: Literal[True]
    reviewed: Literal[True]
    reuse: list[IssueIntakeReuse] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_rows(self) -> "IssueIntakeConfirm":
        if len(set(self.rows)) != len(self.rows):
            raise ValueError("请勿重复选择同一行")
        if len({item.row for item in self.reuse}) != len(self.reuse):
            raise ValueError("同一行只能选择一个复用问题")
        if any(item.row not in self.rows for item in self.reuse):
            raise ValueError("复用选择必须属于本次确认行")
        self.reuse.sort(key=lambda item: item.row)
        self.rows.sort()
        return self


def batch_receipt(row: Any, c: Connection | None = None) -> dict[str, Any]:
    result = _plain(row)
    result["counts"] = {
        status: sum(item["status"] == status for item in row["results"])
        for status in ("created", "linked", "reused", "error")
    }
    result["status"] = "completed_with_errors" if result["counts"]["error"] else "completed"
    if c is not None:
        attach_current_sources(c, [row], [result])
    return result


def attach_current_sources(c: Connection, rows: list[Any], results: list[dict[str, Any]]) -> None:
    if not rows:
        return
    first = rows[0]
    preview = (
        c.execute(
            select(tables.issue_intake_previews).where(
                tables.issue_intake_previews.c.tenant_id == first["tenant_id"],
                tables.issue_intake_previews.c.id == first["preview_id"],
            )
        )
        .mappings()
        .one()
    )
    t = tables.issue_intake_rows
    locators = {item["locator"] for row in rows for item in row["results"]}
    sources = (
        c.execute(
            select(t.c.id, t.c.project_id, t.c.issue_id, t.c.locator).where(
                t.c.tenant_id == first["tenant_id"],
                t.c.project_id == first["project_id"],
                t.c.source_sha256 == preview["source_snapshot"]["sha256"],
                t.c.locator.in_(locators),
            )
        )
        .mappings()
        .all()
    )
    states = source_states(c, first["tenant_id"], list(sources))
    by_locator = {source["locator"]: states[source["id"]] for source in sources}
    for result in results:
        result["current_sources"] = {
            str(item["row"]): by_locator[item["locator"]]
            for item in result["results"]
            if item["locator"] in by_locator
        }


def preview_receipts(c: Connection, tenant: UUID, preview_id: UUID) -> list[dict[str, Any]]:
    t = tables.issue_intake_batches
    rows = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.preview_id == preview_id)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
            .limit(100)
        )
        .mappings()
        .all()
    )
    results = [batch_receipt(row) for row in rows]
    attach_current_sources(c, list(rows), results)
    return results


class IssueIntakeConfirmation:
    def __init__(self, engine: Engine, *, object_store: DocumentObjectStore | None = None):
        self.engine, self.object_store = engine, object_store

    @staticmethod
    def preview(c: Connection, ctx: AuthContext, conversation: UUID, identity: UUID) -> Any:
        t = tables.issue_intake_previews
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.conversation_id == conversation,
                    t.c.id == identity,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ConversationError("此映射草稿不属于当前会话")
        return row

    def confirm(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: IssueIntakeConfirm
    ) -> dict[str, Any]:
        previews = IssueIntakePreviews(self.engine)
        signature = digest(
            body.model_dump(
                mode="json", exclude={"request_id"} | ({"reuse"} if not body.reuse else set())
            )
        )
        t = tables.issue_intake_batches
        original_rows = tables.issue_intake_rows
        # Scope and known receipts are checked before reading the potentially large original.
        with self.engine.connect() as c:
            conv = previews.scope(c, ctx, conversation)
            p = self.preview(c, ctx, conversation, identity)
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.preview_id == identity,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("此确认请求已对应不同的选择，请读取原回执")
                return batch_receipt(prior, c)
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, conv["project_id"], Action.WORK_ITEM_EDIT
            )
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, conv["project_id"], Action.DOCUMENT_ANALYZE
            )
            source = ConversationAttachmentService._row(
                c, ctx.tenant.id, conversation, p["attachment_id"]
            )
            check_source(source, p["parser_version"])
            cited = cited_sources(c, ctx, conversation, p)
            if (
                p["request_digest"] != body.expected_digest
                or source_identity(source) != p["source_snapshot"]
            ):
                raise ConversationError("原草稿或附件抽取已变化，请重新读取并核对")
        if not isinstance(self.object_store, ReadableDocumentObjectStore):
            raise ConversationError("原件读取服务暂不可用，请保留草稿稍后继续")
        content = self.object_store.get(
            object_key=source["object_key"], max_bytes=MAX_DOCUMENT_BYTES
        )
        if (
            len(content) != source["size_bytes"]
            or hashlib.sha256(content).hexdigest() != source["sha256"]
        ):
            raise ConversationError("原件与已登记摘要不一致，不能确认录入")
        cited_contents = {str(source["id"]): content} if cited else {}
        cited_contents.update(
            read_contents(
                {key: value for key, value in cited.items() if key != str(source["id"])},
                self.object_store,
            )
        )
        with self.engine.begin() as c:
            conv = previews.scope(c, ctx, conversation, write=True)
            project = conv["project_id"]
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
            )
            p = self.preview(c, ctx, conversation, identity)
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.preview_id == identity,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("此确认请求已对应不同的选择，请读取原回执")
                return batch_receipt(prior, c)
            current = ConversationAttachmentService._row(
                c, ctx.tenant.id, conversation, p["attachment_id"], lock=True
            )
            check_source(current, p["parser_version"])
            if source_identity(current) != p["source_snapshot"] or source_identity(
                current
            ) != source_identity(source):
                raise ConversationError("读取原件期间来源变化，请重新准备草稿")
            cited_sources(c, ctx, conversation, p)
            selected = {row["row"]: row for row in p["rows"]}
            if any(number not in selected for number in body.rows):
                raise ConversationError("确认行不属于当前已保存草稿")
            results: list[dict[str, Any]] = []
            document_id = None
            shared_sources: dict[str, Any] = {}
            reuse_by_row = {item.row: item for item in body.reuse}
            for number in body.rows:
                row = selected[number]
                reuse = reuse_by_row.get(number)
                result: dict[str, Any] = {"row": number, "locator": row["locator"]}
                if reuse is not None:
                    result |= {
                        "requested_reuse": reuse.model_dump(mode="json"),
                        "reuse_reason": reuse.reason,
                    }
                if row["errors"]:
                    results.append(result | {"status": "error", "errors": row["errors"]})
                    continue
                input_digest = digest(
                    {
                        "row": canonical_row(row),
                        "issue_type": body.issue_type,
                        "severity": body.severity,
                    }
                )
                existing = (
                    c.execute(
                        select(original_rows).where(
                            original_rows.c.tenant_id == ctx.tenant.id,
                            original_rows.c.project_id == project,
                            original_rows.c.source_sha256 == source["sha256"],
                            original_rows.c.locator == row["locator"],
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is not None:
                    state = source_state(c, ctx.tenant.id, existing)
                    active_id = (
                        UUID(state["current_issue_id"]) if state["current_issue_id"] else None
                    )
                    links = self.links(
                        project, active_id or existing["issue_id"], existing["document_id"]
                    )
                    if active_id is None:
                        results.append(
                            result
                            | links
                            | {
                                "status": "error",
                                "errors": [
                                    "此来源关联已撤回，不能自动复用或重新新建；请打开原问题的来源纠错记录办理"
                                ],
                            }
                        )
                        continue
                    matches = existing["input_digest"] == input_digest
                    if (
                        reuse is not None
                        or existing["link_kind"] == "linked"
                        or state["revision"] > 0
                    ):
                        matches = canonical_row(
                            existing["source_snapshot"]["row"]
                        ) == canonical_row(row) and (reuse is None or reuse.issue_id == active_id)
                    if not matches:
                        results.append(
                            result
                            | links
                            | {
                                "status": "error",
                                "errors": [
                                    "同原件同一来源位置已登记，当前映射、分类或复用目标不同；请进入原问题核对，不另建重复问题"
                                ],
                            }
                        )
                    else:
                        results.append(result | links | {"status": "reused", "errors": []})
                    continue
                target = None
                if reuse is not None:
                    target = (
                        c.execute(
                            select(tables.issues)
                            .where(
                                tables.issues.c.tenant_id == ctx.tenant.id,
                                tables.issues.c.project_id == project,
                                tables.issues.c.id == reuse.issue_id,
                                tables.issues.c.withdrawn_at.is_(None),
                            )
                            .with_for_update()
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if target is None or target["updated_at"] != reuse.expected_updated_at:
                        results.append(
                            result
                            | {
                                "status": "error",
                                "errors": [
                                    "所选复用问题已变化或当前不可用，请重新读取、核对后继续；本行未建立关联"
                                ],
                            }
                        )
                        continue
                if cited and not shared_sources:
                    shared_sources = share_documents(
                        c, ctx, project, cited, cited_contents, self.object_store
                    )
                    document_id = UUID(shared_sources[str(source["id"])]["id"])
                if document_id is None:
                    docs = tables.documents
                    document_id = c.execute(
                        select(docs.c.id)
                        .where(
                            docs.c.tenant_id == ctx.tenant.id,
                            docs.c.project_id == project,
                            docs.c.sha256 == source["sha256"],
                            docs.c.classification == "internal",
                        )
                        .order_by(docs.c.created_at, docs.c.id)
                        .limit(1)
                    ).scalar_one_or_none()
                    if document_id is None:
                        document_id = (
                            DocumentService(self.engine, object_store=self.object_store)
                            .analyze(
                                tenant_id=ctx.tenant.id,
                                project_id=project,
                                actor_user_id=ctx.user.id,
                                filename=source["filename"],
                                classification="internal",
                                content=content,
                                connection=c,
                            )
                            .id
                        )
                proposed = row["proposed"]
                if target is not None:
                    issue_id = target["id"]
                    link_kind = "linked"
                    snapshot = target_snapshot(target)
                    input_digest = digest(
                        {"row": canonical_row(row), "reuse_issue_id": str(issue_id)}
                    )
                else:
                    issue = IssueService(self.engine).create(
                        tenant_id=ctx.tenant.id,
                        actor_user_id=ctx.user.id,
                        project_id=project,
                        connection=c,
                        draft=IssueDraft(
                            stage_id=None,
                            owner_user_id=None,
                            verifier_user_id=None,
                            sample_id=None,
                            title=proposed["title"],
                            description=proposed["description"],
                            issue_type=body.issue_type,
                            severity=body.severity,
                            root_cause=proposed["root_cause"],
                            resolution=proposed["resolution"],
                            closure_criteria=None,
                            target_date=date.fromisoformat(proposed["target_date"])
                            if proposed["target_date"]
                            else None,
                        ),
                    )
                    issue_id = issue.id
                    link_kind = "created"
                    snapshot = _plain(
                        proposed | {"issue_type": body.issue_type, "severity": body.severity}
                    )
                source_row_id = uuid4()
                c.execute(
                    original_rows.insert().values(
                        id=source_row_id,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        preview_id=identity,
                        issue_id=issue_id,
                        document_id=document_id,
                        source_sha256=source["sha256"],
                        locator=row["locator"],
                        input_digest=input_digest,
                        source_snapshot={
                            "filename": source["filename"],
                            **({"additional_documents": shared_sources} if shared_sources else {}),
                            **(
                                {"extraction_metadata": p["source_snapshot"]["extraction_metadata"]}
                                if p["source_snapshot"].get("extraction_metadata")
                                else {}
                            ),
                            "mapping": p["mapping"],
                            "row": row,
                            "parser_version": p["parser_version"],
                            "permission_basis": p["permission_basis"],
                            "purpose": p["purpose"],
                        },
                        created_snapshot=snapshot,
                        link_kind=link_kind,
                        reuse_reason=reuse.reason if reuse else None,
                        created_by_user_id=ctx.user.id,
                    )
                )
                EventAuditWriter(
                    c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
                ).record(
                    EventDraft(
                        event_id=f"issue-intake-source:{source_row_id}:initial",
                        event_type="ISSUE_INTAKE_SOURCE_RECORDED",
                        source="issue_intake_service",
                        entity_id=source_row_id,
                        payload={
                            "source_row_id": str(source_row_id),
                            "record_id": str(source_row_id),
                            "action": link_kind,
                        },
                    ),
                    AuditDraft(
                        action="issue_intake.source_register",
                        after_snapshot={
                            "source_row_id": str(source_row_id),
                            "issue_id": str(issue_id),
                            "document_id": str(document_id),
                            "source_sha256": source["sha256"],
                            "locator": row["locator"],
                            "link_kind": link_kind,
                        },
                        context={"reuse_reason": reuse.reason if reuse else None},
                    ),
                )
                results.append(
                    result
                    | self.links(project, issue_id, document_id)
                    | {
                        "status": link_kind,
                        "errors": [],
                        "reuse_reason": reuse.reason if reuse else None,
                    }
                )
            receipt = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        preview_id=identity,
                        created_by_user_id=ctx.user.id,
                        request_id=body.request_id,
                        request_digest=signature,
                        results=results,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            finish_import(c, ctx, p, receipt)
            return batch_receipt(receipt, c)

    @staticmethod
    def links(project: UUID, issue: UUID, document: UUID) -> dict[str, str]:
        return {
            "issue_id": str(issue),
            "document_id": str(document),
            "issue_href": f"/projects?project={project}&tab=work-items&entity_id={issue}",
            "document_href": f"/projects?project={project}&tab=documents&entity_id={document}",
        }

    def issue_sources(self, ctx: AuthContext, project: UUID, issue: UUID) -> dict[str, Any]:
        return IssueIntakeCorrections(self.engine).for_issue(ctx, project, issue)
