"""Register reviewed historical decisions with exact-row reuse and original provenance."""

import hashlib
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversation_attachments import ConversationAttachmentService
from app.domain.conversations import ConversationError
from app.domain.decision_intake_preview import DecisionIntakePreviews, check_source
from app.domain.decision_intake_state import historical_sources, source_states
from app.domain.decision_intake_targets import IntakeTarget, read_target, snapshot
from app.domain.decisions import DecisionDraft, DecisionService, _decision_snapshot
from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentService
from app.domain.intake_ai_imports import (
    cited_sources,
    finish_import,
    read_contents,
    share_documents,
)
from app.domain.issue_intake_preview import canonical_row, source_identity
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class DecisionIntakeConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rows: list[int] = Field(min_length=1, max_length=200)
    publish_to_project: Literal[True]
    reviewed: Literal[True]
    review_note: str = Field(min_length=1, max_length=4000)
    reuse: list[IntakeTarget] = Field(default_factory=list, max_length=200)
    issue_links: list[IntakeTarget] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_rows(self) -> "DecisionIntakeConfirm":
        if len(set(self.rows)) != len(self.rows):
            raise ValueError("请勿重复选择同一行")
        self.review_note = self.review_note.strip()
        if not self.review_note:
            raise ValueError("请填写历史原文核对说明")
        for selections in (self.reuse, self.issue_links):
            if len({item.row for item in selections}) != len(selections):
                raise ValueError("同一行只能选择一个目标决策或关联问题")
            if any(item.row not in self.rows for item in selections):
                raise ValueError("目标选择必须属于本次确认行")
            selections.sort(key=lambda item: item.row)
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
        attach_current(c, row["tenant_id"], [result])
    return result


def attach_current(c: Connection, tenant: UUID, receipts: list[dict[str, Any]]) -> None:
    identities = {
        UUID(item["source_row_id"])
        for receipt in receipts
        for item in receipt["results"]
        if item.get("source_row_id")
    }
    t = tables.decision_intake_rows
    rows = (
        list(
            c.execute(
                select(t.c.id, t.c.project_id).where(
                    t.c.tenant_id == tenant, t.c.id.in_(identities)
                )
            ).mappings()
        )
        if identities
        else []
    )
    states = source_states(c, tenant, rows)
    for receipt in receipts:
        receipt["current_sources"] = {
            str(item["row"]): states[UUID(item["source_row_id"])]
            for item in receipt["results"]
            if item.get("source_row_id") and UUID(item["source_row_id"]) in states
        }


def preview_receipts(c: Connection, tenant: UUID, preview_id: UUID) -> list[dict[str, Any]]:
    t = tables.decision_intake_batches
    values = [
        batch_receipt(row)
        for row in c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.preview_id == preview_id)
            .order_by(t.c.created_at.desc(), t.c.id.desc())
            .limit(100)
        ).mappings()
    ]
    attach_current(c, tenant, values)
    return values


class DecisionIntakeConfirmation:
    def __init__(self, engine: Engine, *, object_store: DocumentObjectStore | None = None):
        self.engine, self.object_store = engine, object_store

    @staticmethod
    def preview(c: Connection, ctx: AuthContext, conversation: UUID, identity: UUID) -> Any:
        t = tables.decision_intake_previews
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
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: DecisionIntakeConfirm
    ) -> dict[str, Any]:
        previews = DecisionIntakePreviews(self.engine)
        signature = digest(
            body.model_dump(
                mode="json",
                exclude={"request_id"}
                | ({"reuse"} if not body.reuse else set())
                | ({"issue_links"} if not body.issue_links else set()),
            )
        )
        t = tables.decision_intake_batches
        original_rows = tables.decision_intake_rows
        # Scope and known receipts are checked before reading the potentially large original.
        with self.engine.connect() as c:
            conv = previews.scope.scope(c, ctx, conversation)
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
            conv = previews.scope.scope(c, ctx, conversation, write=True)
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
            issues_by_row = {item.row: item for item in body.issue_links}
            for number in body.rows:
                row = selected[number]
                reuse, issue_link = reuse_by_row.get(number), issues_by_row.get(number)
                result: dict[str, Any] = {"row": number, "locator": row["locator"]}
                result["requested_reuse"] = reuse.model_dump(mode="json") if reuse else None
                result["requested_issue_link"] = (
                    issue_link.model_dump(mode="json") if issue_link else None
                )
                if row["errors"]:
                    results.append(result | {"status": "error", "errors": row["errors"]})
                    continue
                input_digest = digest({"row": canonical_row(row), "kind": "historical_record"})
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
                    state = source_states(c, ctx.tenant.id, [existing])[existing["id"]]
                    current_decision = (
                        UUID(state["current_decision_id"]) if state["current_decision_id"] else None
                    )
                    current_issue = (
                        UUID(state["current_issue_id"]) if state["current_issue_id"] else None
                    )
                    links = self.links(
                        project,
                        current_decision or existing["decision_id"],
                        existing["document_id"],
                    )
                    matches = canonical_row(existing["source_snapshot"]["row"]) == canonical_row(
                        row
                    )
                    matches = matches and (reuse is None or current_decision == reuse.id)
                    matches = matches and (issue_link is None or current_issue == issue_link.id)
                    errors = []
                    if current_decision is None:
                        errors = [
                            "此来源关联已撤回，请在原决策的来源纠错中处理；本行不会自动复用或新建"
                        ]
                    elif not matches:
                        errors = [
                            "同原件同一来源位置已有登记，当前映射或目标不同；请核对原来源，不重复新建"
                        ]
                    results.append(
                        result
                        | links
                        | {
                            "source_row_id": str(existing["id"]),
                            "related_issue_id": str(current_issue) if current_issue else None,
                            "issue_href": state["current_issue_href"],
                            "status": "error" if errors else "reused",
                            "errors": errors,
                        }
                    )
                    continue
                target = None
                issue = None
                changed = False
                for selection, kind in ((reuse, "decision"), (issue_link, "issue")):
                    if selection is None:
                        continue
                    current_target = read_target(
                        c, ctx.tenant.id, project, kind, selection.id, lock=True
                    )
                    if (
                        current_target is None
                        or digest(snapshot(current_target, kind)) != selection.expected_digest
                    ):
                        results.append(
                            result
                            | {
                                "status": "error",
                                "errors": [
                                    "所选决策或问题已变化，请重新读取核对；本行未登记或关联"
                                ],
                            }
                        )
                        changed = True
                        break
                    if kind == "decision":
                        target = current_target
                    else:
                        issue = current_target
                if changed:
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
                values = row["values"]
                source_row_id = uuid4()
                history = {
                    "source_row_id": str(source_row_id),
                    "document_id": str(document_id),
                    "historical_date": row["historical_date"],
                    "raw_date": values.get("historical_date"),
                    "raw_approver": values.get("historical_approver"),
                    "raw_owner": values.get("historical_owner"),
                    "raw_kind": values.get("historical_kind"),
                    "raw_state": values.get("historical_state"),
                    "external_ref": values.get("external_ref"),
                    "issue_ref": values.get("issue_ref"),
                    "missing_fields": row["gaps"],
                    "reviewed_by_user_id": str(ctx.user.id),
                    "review_note": body.review_note,
                    "date_semantics": (
                        "decided_at is registration time; "
                        "historical_date is the original date, if known"
                    ),
                }
                if target is None:
                    record = DecisionService(self.engine).record_history(
                        tenant_id=ctx.tenant.id,
                        actor_user_id=ctx.user.id,
                        project_id=project,
                        connection=c,
                        historical_source=history,
                        draft=DecisionDraft(
                            decision_kind="historical_record",
                            title=values["title"],
                            outcome=values["outcome"],
                            context=values.get("context") or None,
                            options=(values["options"],) if values.get("options") else (),
                            trade_offs=values.get("trade_offs") or None,
                            rationale=values.get("rationale") or None,
                            consequence=values.get("consequence") or None,
                            evidence_refs=tuple(
                                dict.fromkeys(
                                    f"document:{shared_sources[q['attachment_id']]['id']}#{q['locator']}"
                                    for q in [row["anchor"], *row["original"].values()]
                                )
                            )
                            if shared_sources
                            else (f"document:{document_id}#{row['locator']}",),
                        ),
                    )
                    decision_id = record.id
                    created_snapshot = _decision_snapshot(record)
                    link_kind = "created"
                else:
                    decision_id = target["id"]
                    created_snapshot = snapshot(target, "decision")
                    input_digest = digest(
                        {"row": canonical_row(row), "reuse_decision_id": str(decision_id)}
                    )
                    link_kind = "linked"
                c.execute(
                    original_rows.insert().values(
                        id=source_row_id,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        preview_id=identity,
                        decision_id=decision_id,
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
                        created_snapshot=created_snapshot,
                        link_kind=link_kind,
                        reuse_reason=reuse.reason if reuse else None,
                        related_issue_id=issue["id"] if issue is not None else None,
                        issue_snapshot=snapshot(issue, "issue") if issue is not None else None,
                        issue_reason=issue_link.reason if issue_link else None,
                        review_note=body.review_note,
                        created_by_user_id=ctx.user.id,
                    )
                )
                EventAuditWriter(
                    c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
                ).record(
                    EventDraft(
                        event_id=f"decision-intake:{source_row_id}:registered",
                        event_type="DECISION_INTAKE_SOURCE_RECORDED",
                        source="decision_intake_service",
                        entity_id=source_row_id,
                        payload={
                            "source_row_id": str(source_row_id),
                            "record_id": str(source_row_id),
                            "action": link_kind,
                        },
                    ),
                    AuditDraft(
                        action="decision_intake.source_register",
                        after_snapshot={
                            "source_row_id": str(source_row_id),
                            "decision_id": str(decision_id),
                            "related_issue_id": str(issue["id"]) if issue is not None else None,
                            "link_kind": link_kind,
                            "document_id": str(document_id),
                            "reuse_reason": reuse.reason if reuse else None,
                            "issue_reason": issue_link.reason if issue_link else None,
                        },
                    ),
                )
                results.append(
                    result
                    | self.links(project, decision_id, document_id)
                    | {
                        "source_row_id": str(source_row_id),
                        "status": link_kind,
                        "related_issue_id": str(issue["id"]) if issue is not None else None,
                        "issue_href": (
                            f"/projects?project={project}&tab=work-items&entity_id={issue['id']}"
                        )
                        if issue is not None
                        else None,
                        "errors": [],
                        "missing_fields": row["gaps"],
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
                        review_note=body.review_note,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            finish_import(c, ctx, p, receipt)
            return batch_receipt(receipt, c)

    @staticmethod
    def links(project: UUID, decision: UUID, document: UUID) -> dict[str, str]:
        return {
            "decision_id": str(decision),
            "document_id": str(document),
            "decision_href": f"/projects?project={project}&tab=decisions#decision-{decision}",
            "document_href": f"/projects?project={project}&tab=documents&entity_id={document}",
        }

    def sources(
        self,
        ctx: AuthContext,
        project: UUID,
        decision: UUID | None = None,
        *,
        issue_id: UUID | None = None,
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> dict[str, Any]:
        if (before_created_at is None) != (before_id is None):
            raise ConversationError("来源分页位置不完整，请重新读取")
        if (decision is None) == (issue_id is None):
            raise ConversationError("请选择一个实际决策或问题")
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            KnowledgeCorrectionService._authorize(
                c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_VIEW
            )
            t, people = tables.decision_intake_rows, tables.users
            query = (
                select(t, people.c.display_name.label("reviewed_by_name"))
                .join(
                    people,
                    (people.c.tenant_id == t.c.tenant_id) & (people.c.id == t.c.created_by_user_id),
                )
                .where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.project_id == project,
                    t.c.id.in_(
                        historical_sources(
                            ctx.tenant.id, project, decision=decision, issue=issue_id
                        )
                    ),
                )
            )
            if before_created_at is not None:
                query = query.where(
                    or_(
                        t.c.created_at < before_created_at,
                        (t.c.created_at == before_created_at) & (t.c.id < before_id),
                    )
                )
            records = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            states = source_states(c, ctx.tenant.id, list(records[:20]))
            targets = {}
            for kind, table, key in (
                ("decision", tables.decisions, "current_decision_id"),
                ("issue", tables.issues, "current_issue_id"),
            ):
                identities = {
                    UUID(states[row["id"]][key]) for row in records[:20] if states[row["id"]][key]
                }
                targets[kind] = (
                    {
                        row["id"]: snapshot(row, kind)
                        for row in c.execute(
                            select(table).where(
                                table.c.tenant_id == ctx.tenant.id,
                                table.c.project_id == project,
                                table.c.id.in_(identities),
                            )
                        ).mappings()
                    }
                    if identities
                    else {}
                )
            items = []
            for row in records[:20]:
                item = {
                    key: value
                    for key, value in _plain(row).items()
                    if key not in {"tenant_id", "preview_id"}
                }
                item |= self.links(project, row["decision_id"], row["document_id"])
                state = states[row["id"]]
                item |= state
                item["on_this_target"] = (
                    (state["current_decision_id"] == str(decision))
                    if decision
                    else (state["current_issue_id"] == str(issue_id))
                )
                current_decision = (
                    UUID(state["current_decision_id"]) if state["current_decision_id"] else None
                )
                current_issue = (
                    UUID(state["current_issue_id"]) if state["current_issue_id"] else None
                )
                item["current_decision"] = targets["decision"].get(current_decision)
                item["current_issue"] = targets["issue"].get(current_issue)
                expected = state["association_snapshot"] or {
                    "decision": row["created_snapshot"],
                    "issue": row["issue_snapshot"],
                }
                item["issue_changed"] = item["current_issue"] != expected.get("issue")
                item["decision_changed"] = (
                    item["current_decision"] != expected.get("decision")
                    if state["revision"] > 0 or row["link_kind"] == "linked"
                    else False
                )
                item["issue_href"] = state["current_issue_href"]
                items.append(item)
            return {
                "items": items,
                "next": {"before_created_at": items[-1]["created_at"], "before_id": items[-1]["id"]}
                if len(records) > 20
                else None,
            }
