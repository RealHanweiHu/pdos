"""Customer-visible whitelist, independent approval, and revocable local exports."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.audit_customer_projection import VERSION as AUDIT_VERSION
from app.domain.audit_customer_projection import (
    AuditDisclosureOptions,
    AuditPackageDraft,
    AuditPackageSave,
)
from app.domain.audit_customer_projection import access as audit_access
from app.domain.audit_customer_projection import prepare as audit_prepare
from app.domain.audit_customer_projection import sections as audit_sections
from app.domain.formal_schedule import current_plan, current_states
from app.domain.portfolio_milestones import commitments
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.domain.quality_operations import authorize
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.exports.definition_documents import MIMES, render_sections
from app.storage.documents import DocumentObjectStore

VERSION = "customer-reply-commitment.v1"


class Milestone(Contract):
    node_id: UUID
    customer_label: str = Field(min_length=1, max_length=128)


class PackageDraft(Contract):
    customer_id: UUID
    title: str = Field(min_length=1, max_length=256)
    reply_ids: tuple[UUID, ...] = Field(default=(), max_length=20)
    milestones: tuple[Milestone, ...] = Field(default=(), max_length=20)
    internal_reason: Text

    @model_validator(mode="after")
    def valid(self) -> Self:
        if not self.reply_ids and not self.milestones:
            raise ValueError("请至少选择一条已批准回复或实际承诺")
        if len(set(self.reply_ids)) != len(self.reply_ids) or len(
            {v.node_id for v in self.milestones}
        ) != len(self.milestones):
            raise ValueError("回复和承诺节点不能重复")
        return self


class PackageSave(PackageDraft):
    request_id: UUID
    expected_digest: Digest


class PackageOptions(Contract):
    customer_id: UUID | None = None
    before_reply_id: UUID | None = None
    before_node_id: UUID | None = None


class PackageHistory(Contract):
    before_id: UUID | None = None


class PackageRead(Contract):
    package_id: UUID


class PackageDecision(PackageRead):
    request_id: UUID
    expected_version: int = Field(ge=0)
    expected_digest: Digest
    action: Literal["approved", "returned", "withdrawn"]
    reason: Text


class PackageExport(PackageRead):
    decision_id: UUID
    format: Literal["docx", "xlsx", "pptx", "pdf", "zip"]


def parse_draft(value: Any) -> PackageDraft | AuditPackageDraft:
    return (
        AuditPackageDraft.model_validate(value)
        if "audit_report_id" in value
        else PackageDraft.model_validate(value)
    )


def access(
    c: Connection, context: AuthContext, project: UUID, action: Action = Action.CHANGE_VIEW
) -> None:
    authorize(c, context, project, action)


def permissions(c: Connection, context: AuthContext, project: UUID) -> dict[str, bool]:
    result = {}
    for name, action in (
        ("can_prepare", Action.CHANGE_EDIT),
        ("can_decide", Action.CHANGE_APPROVE),
    ):
        try:
            access(c, context, project, action)
            result[name] = True
        except PermissionError:
            result[name] = False
    return result


def customer(c: Connection, context: AuthContext, project: UUID, identity: UUID) -> Any:
    customers, projects, changes = (
        tables.customers,
        tables.projects,
        tables.customer_change_requests,
    )
    allowed = or_(
        customers.c.id.in_(
            select(projects.c.customer_id).where(
                projects.c.tenant_id == context.tenant.id, projects.c.id == project
            )
        ),
        customers.c.id.in_(
            select(changes.c.customer_id).where(
                changes.c.tenant_id == context.tenant.id, changes.c.project_id == project
            )
        ),
    )
    result = (
        c.execute(
            select(customers.c.id, customers.c.name).where(
                customers.c.tenant_id == context.tenant.id, customers.c.id == identity, allowed
            )
        )
        .mappings()
        .one_or_none()
    )
    if result is None:
        raise ProductWorkError("客户须为此项目或原客户变更中的实际客户")
    return result


def node_state(
    c: Connection, context: AuthContext, project: UUID
) -> tuple[dict[str, Any], dict[str, str]]:
    authorize(c, context, project, Action.WORK_ITEM_VIEW)
    plan = current_plan(c, context.tenant.id, project)
    rows, titles = current_states(c, context.tenant.id, project, plan) if plan else ([], {})
    return {v["node_id"]: v for v in rows}, titles


def latest_commitment(c: Connection, context: AuthContext, project: UUID, node: UUID) -> Any:
    q = commitments(context.tenant.id, project, node).subquery()
    record = c.execute(select(q).order_by(q.c.version.desc()).limit(1)).mappings().one_or_none()
    if record is None or record["end"] is None or record["approved_at"] is None:
        raise ProductWorkError("所选节点尚无具名确认、带明确结束时间的实际承诺")
    return record


def prepare(
    c: Connection, context: AuthContext, project: UUID, draft: PackageDraft | AuditPackageDraft
) -> dict[str, Any]:
    access(c, context, project)
    if isinstance(draft, AuditPackageDraft):
        return audit_prepare(c, context, project, draft)
    actual_customer = customer(c, context, project, draft.customer_id)
    replies = []
    refs = []
    for identity in draft.reply_ids:
        t = tables.customer_change_requests
        row = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.customer_id == draft.customer_id,
                    t.c.id == identity,
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            row is None
            or row["status"] not in {"reply_approved", "accepted"}
            or not row["reply_approved_at"]
            or not row["reply_approved_by_user_id"]
        ):
            raise ProductWorkError(
                "只能选择本客户仍有效的已批准回复；未批、拒绝或取消项不进入客户报告"
            )
        replies.append(
            {
                "reference": row["code"],
                "approved_reply": row["quote_note"],
                "lead_time_days": row["lead_time_days"],
                "reply_approved_at": row["reply_approved_at"].isoformat(),
            }
        )
        refs.append(
            {
                "kind": "customer_reply",
                "id": str(identity),
                "reply_approved_by": str(row["reply_approved_by_user_id"]),
                "reply_approved_at": row["reply_approved_at"].isoformat(),
                "quote_note": row["quote_note"],
                "lead_time_days": row["lead_time_days"],
            }
        )
    promised = []
    states, _ = node_state(c, context, project) if draft.milestones else ({}, {})
    for item in draft.milestones:
        state = states.get(str(item.node_id))
        if state is None or state["status"] == "skipped":
            raise ProductWorkError("承诺节点已不在当前正式计划或已跳过，请先处理原承诺范围")
        record = latest_commitment(c, context, project, item.node_id)
        promised.append(
            {
                "milestone": item.customer_label,
                "committed_finish": record["end"].isoformat(),
                "confirmed_at": record["approved_at"].isoformat(),
            }
        )
        refs.append(
            {
                "kind": "commitment",
                "node_id": str(item.node_id),
                "record_id": str(record["record_id"]),
                "confirmation_id": str(record["confirmation_id"]),
                "version": record["version"],
                "end": record["end"].isoformat(),
                "approved_at": record["approved_at"].isoformat(),
            }
        )
    projection = {
        "template_version": VERSION,
        "title": draft.title,
        "customer_name": actual_customer["name"],
        "approved_replies": replies,
        "commitments": promised,
        "interpretation": (
            "回复按原单据适用范围执行；所列日期为具名确认的承诺，不代表新的预测或履约完成证明。"
        ),
    }
    body = {
        "draft": draft.model_dump(mode="json"),
        "customer_id": str(draft.customer_id),
        "projection": projection,
        "source_refs": refs,
    }
    return {**body, "digest": digest(body)}


def package(c: Connection, context: AuthContext, project: UUID, identity: UUID) -> Any:
    access(c, context, project)
    t = tables.customer_report_packages
    row = (
        c.execute(
            select(t).where(
                t.c.tenant_id == context.tenant.id, t.c.project_id == project, t.c.id == identity
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("客户报告不存在或不可读取")
    if row["draft"].get("audit_report_id"):
        audit_access(c, context, project, AuditPackageDraft.model_validate(row["draft"]))
    return row


def last_decision(c: Connection, tenant: UUID, identity: UUID) -> Any:
    t = tables.customer_report_decisions
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.package_id == identity)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def record_event(
    c: Connection, context: AuthContext, project: UUID, identity: UUID, action: str
) -> None:
    EventAuditWriter(
        c, tenant_id=context.tenant.id, actor_user_id=context.user.id, project_id=project
    ).record(
        EventDraft(
            event_id=f"customer-report:{identity}:{action}",
            event_type="CUSTOMER_REPORT_RECORDED",
            source="report_export_service",
            entity_id=identity,
            payload={"record_id": str(identity), "action": action},
        ),
        AuditDraft(action=f"customer_report.{action}", after_snapshot={"record_id": str(identity)}),
    )


class CustomerReportService:
    def __init__(self, engine: Engine, store: DocumentObjectStore | None = None):
        self.engine = engine
        self.store = store

    def preview(
        self, context: AuthContext, project: UUID, draft: PackageDraft | AuditPackageDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return prepare(c, context, project, draft)

    def save(
        self, context: AuthContext, project: UUID, command: PackageSave | AuditPackageSave
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            access(c, context, project, Action.CHANGE_EDIT)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            t = tables.customer_report_packages
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
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
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能修改报告内容")
                if old["draft"].get("audit_report_id"):
                    audit_access(
                        c, context, project, AuditPackageDraft.model_validate(old["draft"])
                    )
                return _plain(old)
            draft_type = (
                AuditPackageDraft if isinstance(command, AuditPackageSave) else PackageDraft
            )
            draft = draft_type.model_validate(
                {
                    key: value
                    for key, value in command.model_dump(mode="json").items()
                    if key in draft_type.model_fields
                }
            )
            current = prepare(c, context, project, draft)
            if current["digest"] != command.expected_digest:
                raise ProductWorkError("回复、客户或承诺已变化，请重新预览")
            row = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        customer_id=draft.customer_id,
                        audit_report_id=draft.audit_report_id
                        if isinstance(draft, AuditPackageDraft)
                        else None,
                        draft=draft.model_dump(mode="json"),
                        snapshot=current,
                        source_digest=current["digest"],
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            if isinstance(draft, AuditPackageDraft):
                for document in draft.documents:
                    c.execute(
                        tables.customer_report_documents.insert().values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=project,
                            package_id=row["id"],
                            source_document_id=document.source_document_id,
                            document_id=document.document_id,
                        )
                    )
            record_event(c, context, project, row["id"], "prepared")
            return _plain(row)

    def read(self, context: AuthContext, project: UUID, query: PackageRead) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            row = package(c, context, project, query.package_id)
            problem = None
            try:
                current = prepare(c, context, project, parse_draft(row["draft"]))
                unchanged = current["digest"] == row["source_digest"]
            except (ValueError, PermissionError) as error:
                current = None
                unchanged = False
                problem = str(error)
            t = tables.customer_report_decisions
            history = (
                c.execute(
                    select(t)
                    .where(t.c.tenant_id == context.tenant.id, t.c.package_id == query.package_id)
                    .order_by(t.c.version)
                )
                .mappings()
                .all()
            )
            body = {
                "record": _plain(row),
                "decisions": [_plain(v) for v in history],
                "sources_current": unchanged,
                "source_problem": problem,
                "current_projection": current["projection"] if current else None,
            }
            f = tables.customer_report_files
            files = (
                c.execute(
                    select(*(col for col in f.c if col.name != "content"))
                    .where(f.c.tenant_id == context.tenant.id, f.c.package_id == row["id"])
                    .order_by(f.c.created_at)
                )
                .mappings()
                .all()
            )
            return {
                **body,
                "digest": digest(body),
                "current_user_id": str(context.user.id),
                **permissions(c, context, project),
                "files": [file_meta(v) for v in files],
            }

    def decide(
        self, context: AuthContext, project: UUID, command: PackageDecision
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            access(c, context, project, Action.CHANGE_APPROVE)
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            row = package(c, context, project, command.package_id)
            t = tables.customer_report_decisions
            signature = digest(
                {"project": str(project), "command": command.model_dump(mode="json")}
            )
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.actor_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise ProductWorkError("同一请求不能改写裁决")
                return _plain(old)
            previous = last_decision(c, context.tenant.id, row["id"])
            version = previous["version"] if previous else 0
            if version != command.expected_version:
                raise ProductWorkError("已有新裁决，请刷新")
            # Rebuild the review digest in this locked transaction, without a second connection.
            history = (
                c.execute(
                    select(t)
                    .where(t.c.tenant_id == context.tenant.id, t.c.package_id == row["id"])
                    .order_by(t.c.version)
                )
                .mappings()
                .all()
            )
            problem = None
            try:
                current = prepare(c, context, project, parse_draft(row["draft"]))
                unchanged = current["digest"] == row["source_digest"]
            except (ValueError, PermissionError) as error:
                current = None
                unchanged = False
                problem = str(error)
            body = {
                "record": _plain(row),
                "decisions": [_plain(v) for v in history],
                "sources_current": unchanged,
                "source_problem": problem,
                "current_projection": current["projection"] if current else None,
            }
            if digest(body) != command.expected_digest:
                raise ProductWorkError("审阅资料或来源已变化，请重新核对")
            if command.action == "approved":
                if row["created_by_user_id"] == context.user.id:
                    raise ProductWorkError("客户可见内容须由另一位有审批权人员核准")
                if not unchanged:
                    raise ProductWorkError("原来源已变化，请重新准备报告")
                if previous is not None:
                    raise ProductWorkError("已裁决报告保持原记录；修改或再次申请请新建报告")
            elif command.action == "returned" and previous is not None:
                raise ProductWorkError("只能退回尚未裁决的报告")
            elif command.action == "withdrawn" and (
                previous is None or previous["action"] != "approved"
            ):
                raise ProductWorkError("只能撤回当前已批准报告")
            result = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project,
                        package_id=row["id"],
                        version=version + 1,
                        action=command.action,
                        reason=command.reason,
                        actor_user_id=context.user.id,
                        source_digest=row["source_digest"],
                        request_id=command.request_id,
                        request_digest=signature,
                        created_at=datetime.now(UTC),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            record_event(c, context, project, result["id"], command.action)
            return _plain(result)

    def audit_options(
        self, context: AuthContext, project: UUID, query: AuditDisclosureOptions
    ) -> dict[str, Any]:
        from app.domain.audit_report_bundles import report

        customers = self.options(context, project, PackageOptions())["customers"]
        with self.engine.connect() as c:
            original = report(c, context, project, query.audit_report_id)
            return {
                "customers": customers,
                **permissions(c, context, project),
                "clauses": original["scope"]["audit_clauses"],
                "original_sources": original["snapshot"]["actual"]["sources"],
            }

    def options(self, context: AuthContext, project: UUID, query: PackageOptions) -> dict[str, Any]:
        with self.engine.connect() as c:
            access(c, context, project)
            p, cc, cu = tables.projects, tables.customer_change_requests, tables.customers
            customers = (
                c.execute(
                    select(cu.c.id, cu.c.name)
                    .where(
                        cu.c.tenant_id == context.tenant.id,
                        or_(
                            cu.c.id.in_(
                                select(p.c.customer_id).where(
                                    p.c.tenant_id == context.tenant.id, p.c.id == project
                                )
                            ),
                            cu.c.id.in_(
                                select(cc.c.customer_id).where(
                                    cc.c.tenant_id == context.tenant.id, cc.c.project_id == project
                                )
                            ),
                        ),
                    )
                    .order_by(cu.c.name, cu.c.id)
                )
                .mappings()
                .all()
            )
            replies = []
            nodes = []
            next_reply = None
            next_node = None
            if query.customer_id:
                customer(c, context, project, query.customer_id)
                q = select(
                    cc.c.id, cc.c.code, cc.c.quote_note, cc.c.lead_time_days, cc.c.reply_approved_at
                ).where(
                    cc.c.tenant_id == context.tenant.id,
                    cc.c.project_id == project,
                    cc.c.customer_id == query.customer_id,
                    cc.c.status.in_(["reply_approved", "accepted"]),
                    cc.c.reply_approved_at.is_not(None),
                )
                if query.before_reply_id:
                    q = q.where(cc.c.id < query.before_reply_id)
                rows = c.execute(q.order_by(cc.c.id.desc()).limit(21)).mappings().all()
                replies = [_plain(v) for v in rows[:20]]
                next_reply = str(rows[19]["id"]) if len(rows) > 20 else None
                states, titles = node_state(c, context, project)
                for identity, state in sorted(states.items(), reverse=True):
                    if query.before_node_id and identity >= str(query.before_node_id):
                        continue
                    if state["status"] == "skipped":
                        continue
                    try:
                        record = latest_commitment(c, context, project, UUID(identity))
                    except ProductWorkError:
                        continue
                    nodes.append(
                        {
                            "node_id": identity,
                            "internal_title": titles[state["node_key"]],
                            "version": record["version"],
                            "committed_finish": record["end"].isoformat(),
                            "confirmed_at": record["approved_at"].isoformat(),
                        }
                    )
                    if len(nodes) == 21:
                        break
                next_node = nodes[19]["node_id"] if len(nodes) > 20 else None
            return {
                "customers": [_plain(v) for v in customers],
                **permissions(c, context, project),
                "replies": replies,
                "nodes": nodes[:20],
                "next_before_reply_id": next_reply,
                "next_before_node_id": next_node,
            }

    def history(self, context: AuthContext, project: UUID, query: PackageHistory) -> dict[str, Any]:
        with self.engine.connect() as c:
            access(c, context, project)
            t = tables.customer_report_packages
            q = select(
                t.c.id, t.c.customer_id, t.c.draft, t.c.created_by_user_id, t.c.created_at
            ).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if query.before_id:
                q = q.where(t.c.id < query.before_id)
            rows = c.execute(q.order_by(t.c.id.desc()).limit(21)).mappings().all()
            visible = []
            for record in rows[:20]:
                if record["draft"].get("audit_report_id"):
                    try:
                        audit_access(
                            c, context, project, AuditPackageDraft.model_validate(record["draft"])
                        )
                    except PermissionError:
                        continue
                visible.append(record)
            return {
                "items": [
                    {
                        **_plain(r),
                        "decision": _plain(d)
                        if (d := last_decision(c, context.tenant.id, r["id"]))
                        else None,
                    }
                    for r in visible
                ],
                "next_before_id": str(rows[19]["id"]) if len(rows) > 20 else None,
            }

    def export(self, context: AuthContext, project: UUID, command: PackageExport) -> dict[str, Any]:
        if command.format == "zip":
            from app.domain.audit_customer_files import export_zip

            return export_zip(self.engine, self.store, context, project, command)
        with self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
                raise ProductWorkError("项目不可用")
            row, decision = approved(c, context, project, command.package_id, command.decision_id)
            t = tables.customer_report_files
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.package_id == row["id"],
                        t.c.decision_id == decision["id"],
                        t.c.format == command.format,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                return file_meta(old)
            identity = uuid4()
            now = datetime.now(UTC)
            projection = row["snapshot"]["projection"]
            sections = [("客户", projection["customer_name"])]
            for reply in projection.get("approved_replies", []):
                days = reply["lead_time_days"]
                lead_time = "未提供" if days is None else f"{days} 天"
                sections.append(
                    (
                        f"已批准回复 · {reply['reference']}",
                        f"{reply['approved_reply'] or '未提供回复正文'}\n"
                        f"原回复工期：{lead_time}\n"
                        f"批准时间：{reply['reply_approved_at']}",
                    )
                )
            for item in projection.get("commitments", []):
                sections.append(
                    (
                        item["milestone"],
                        f"已确认完成承诺：{item['committed_finish']}\n"
                        f"确认时间：{item['confirmed_at']}",
                    )
                )
            sections.append(("适用说明", projection["interpretation"]))
            if projection["template_version"] == AUDIT_VERSION:
                sections = audit_sections(projection)
            content = render_sections(
                projection["title"],
                "已批准客户可见内容",
                sections,
                command.format,
                {
                    "报告编号": str(identity),
                    "编号": str(identity),
                    "内容批准时间": decision["created_at"].isoformat(),
                    "生成时间": now.isoformat(),
                    "模板": projection["template_version"],
                },
                audience="customer",
            )
            if len(content) > 12 * 1024 * 1024:
                raise ProductWorkError("客户报告超过单文件容量，请缩小范围重新申请")
            result = (
                c.execute(
                    t.insert()
                    .values(
                        id=identity,
                        tenant_id=context.tenant.id,
                        project_id=project,
                        package_id=row["id"],
                        decision_id=decision["id"],
                        format=command.format,
                        filename=f"customer-report-{identity}.{command.format}",
                        mime_type=MIMES[command.format],
                        content=content,
                        byte_size=len(content),
                        content_digest=sha256(content).hexdigest(),
                        created_by_user_id=context.user.id,
                        created_at=now,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            record_event(c, context, project, identity, "file_created")
            return file_meta(result)

    def download(
        self, context: AuthContext, project: UUID, identity: UUID
    ) -> tuple[bytes, str, str]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            t = tables.customer_report_files
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.project_id == project,
                        t.c.id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ProductWorkError("客户报告文件不存在或不可读取")
            approved(c, context, project, row["package_id"], row["decision_id"])
            content = bytes(row["content"])
            if (
                len(content) != row["byte_size"]
                or sha256(content).hexdigest() != row["content_digest"]
            ):
                raise ProductWorkError("文件校验与原回执不一致")
            return content, row["mime_type"], row["filename"]


def approved(
    c: Connection, context: AuthContext, project: UUID, identity: UUID, decision_id: UUID
) -> tuple[Any, Any]:
    row = package(c, context, project, identity)
    decision = last_decision(c, context.tenant.id, identity)
    if decision is None or decision["id"] != decision_id or decision["action"] != "approved":
        raise ProductWorkError("报告未批准或已撤回，不能生成或下载客户文件")
    current = prepare(c, context, project, parse_draft(row["draft"]))
    if current["digest"] != row["source_digest"]:
        raise ProductWorkError("原客户回复或承诺已有变化，停止使用旧文件；请重新准备并核准")
    return row, decision


def file_meta(row: Any) -> dict[str, Any]:
    return _plain(
        {
            k: row[k]
            for k in (
                "id",
                "package_id",
                "decision_id",
                "format",
                "filename",
                "mime_type",
                "byte_size",
                "content_digest",
                "created_by_user_id",
                "created_at",
            )
        }
    )
