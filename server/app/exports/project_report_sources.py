"""Explicit internal report projections from actual project records."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import Connection, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract
from app.db.schema import tables
from app.domain.living_fmea import current_sources
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.quality_operations import authorize
from app.domain.quality_result_source import ncr_source
from app.exports.audit_report_sources import AuditClause
from app.exports.audit_report_sources import prepare as audit_prepare
from app.exports.audit_report_text import VERSION as AUDIT_VERSION
from app.exports.audit_report_text import sections as audit_sections
from app.exports.definition_documents import value
from app.exports.eight_d_report_text import VERSION as EIGHT_D_VERSION
from app.exports.eight_d_report_text import people_ids
from app.exports.eight_d_report_text import sections as eight_d_sections
from app.exports.engineering_report_text import VERSIONS, dfmea_sections, gate_sections
from app.exports.weekly_report_text import weekly_sections

Kind = Literal["8d", "dfmea", "gate", "weekly", "audit"]
LABELS = {
    "8d": "8D 问题解决报告",
    "dfmea": "DFMEA 设计风险报告",
    "gate": "Gate 签核与裁决报告",
    "weekly": "项目周报",
    "audit": "签核与审核条款证据包",
}
VERSION = "internal-project-reports.v1"


class ReportScope(Contract):
    kind: Kind
    object_id: UUID | None = None
    entry_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    audit_clauses: tuple[AuditClause, ...] = Field(default=(), max_length=30)
    period_start: date | None = None
    period_end: date | None = None

    @model_validator(mode="after")
    def scope(self) -> Self:
        if (self.kind in {"8d", "gate"}) != (self.object_id is not None):
            raise ValueError("8D/Gate须选实际记录，其他模板不接受该对象字段")
        if (self.kind == "dfmea") != bool(self.entry_ids) or len(set(self.entry_ids)) != len(
            self.entry_ids
        ):
            raise ValueError("DFMEA须显式选择不重复的实际条目，其他模板不接受条目范围")
        if (self.kind == "audit") != bool(self.audit_clauses):
            raise ValueError("审核证据包须明确条款，其他模板不接受条款字段")
        if sum(len(v.evidence) for v in self.audit_clauses) > 100:
            raise ValueError("单包最多100处证据对应，请按范围分包")
        if self.kind == "weekly":
            if (
                self.period_start is None
                or self.period_end is None
                or not 0 <= (self.period_end - self.period_start).days <= 30
            ):
                raise ValueError("周报须明确1至31天的UTC统计日期范围")
        elif self.period_start is not None or self.period_end is not None:
            raise ValueError("只有周报使用统计窗口")
        return self


def access(c: Connection, context: AuthContext, project: UUID, kind: Kind) -> None:
    authorize(
        c,
        context,
        project,
        {
            "8d": Action.QUALITY_VIEW,
            "dfmea": Action.QUALITY_VIEW,
            "gate": Action.GATE_VIEW,
            "weekly": Action.WORK_ITEM_VIEW,
            "audit": Action.QUALITY_VIEW,
        }[kind],
    )


def all_rows(c: Connection, query: Any, maximum: int = 1000) -> list[dict[str, Any]]:
    rows = c.execute(query.limit(maximum + 1)).mappings().all()
    if len(rows) > maximum:
        raise ProductWorkError("所选资料超过单次组包容量，请缩小范围；未截断原记录")
    return [_plain(r) for r in rows]


def scoped(table: Any, context: AuthContext, project: UUID) -> Any:
    return select(table).where(
        table.c.tenant_id == context.tenant.id, table.c.project_id == project
    )


def source(
    c: Connection,
    context: AuthContext,
    project: UUID,
    scope: ReportScope,
    *,
    audit_template: str | None = None,
) -> dict[str, Any]:
    if audit_template not in {None, "internal-audit-evidence.v1", AUDIT_VERSION}:
        raise ProductWorkError("原审核模板版本不可读取")
    access(c, context, project, scope.kind)
    p = tables.projects
    row = (
        c.execute(
            select(p.c.id, p.c.code, p.c.name, p.c.status, p.c.current_stage_id).where(
                p.c.tenant_id == context.tenant.id, p.c.id == project
            )
        )
        .mappings()
        .one()
    )
    body: dict[str, Any] = {
        "project": _plain(row),
        "scope": scope.model_dump(mode="json"),
        "template_version": (audit_template or AUDIT_VERSION)
        if scope.kind == "audit"
        else {"weekly": "internal-project-weekly.v2", "8d": EIGHT_D_VERSION, **VERSIONS}.get(
            scope.kind, VERSION
        ),
        "audience": "internal",
    }
    warnings: list[str] = []
    sections: list[tuple[str, str]] = []
    status = "内部整理草稿 · 未作报告审批"
    if scope.kind == "audit":
        audit_package = audit_prepare(c, context, project, scope.audit_clauses)
        body["actual"] = {"clauses": audit_package["clauses"], "sources": audit_package["sources"]}
        warnings = audit_package["warnings"]
        sections = audit_package["sections"]
        if body["template_version"] == AUDIT_VERSION:
            people = all_rows(
                c,
                select(tables.users.c.id, tables.users.c.display_name)
                .where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.id.in_(
                        {UUID(identity) for identity in people_ids(body["actual"])}
                    ),
                )
                .order_by(tables.users.c.id),
                maximum=4000,
            )
            body["people"] = people
            sections = audit_sections(body["actual"], people)
    elif scope.kind == "8d":
        assert scope.object_id is not None
        actual = ncr_source(c, context, project, scope.object_id)
        body["actual"] = actual
        warnings = [
            *actual["warnings"],
            "D1专门团队确认、D8团队认可未在现有结构化记录登记，保持缺项；NCR关闭不代表完整8D报告获批。",
        ]
        people = all_rows(
            c,
            select(tables.users.c.id, tables.users.c.display_name)
            .where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id.in_({UUID(identity) for identity in people_ids(actual)}),
            )
            .order_by(tables.users.c.id),
            maximum=4000,
        )
        body["people"] = people
        sections = eight_d_sections(actual, people)
    elif scope.kind == "dfmea":
        entries = []
        for identity in scope.entry_ids:
            t = tables.fmea_versions
            history = all_rows(
                c, scoped(t, context, project).where(t.c.entry_id == identity).order_by(t.c.version)
            )
            if not history:
                raise ProductWorkError("所选FMEA条目不存在或不属于当前项目")
            latest = (
                c.execute(scoped(t, context, project).where(t.c.id == UUID(history[-1]["id"])))
                .mappings()
                .one()
            )
            refs, gaps = current_sources(c, latest)
            pub = tables.fmea_publications
            publications = all_rows(
                c,
                scoped(pub, context, project)
                .where(pub.c.entry_id == identity)
                .order_by(pub.c.published_at, pub.c.id),
            )
            latest_pub = publications[-1] if publications else None
            published = next(
                (v for v in history if latest_pub and v["id"] == latest_pub["version_id"]), None
            )
            published_refs: list[dict[str, Any]] = []
            published_gaps: list[str] = []
            if published:
                original = (
                    c.execute(scoped(t, context, project).where(t.c.id == UUID(published["id"])))
                    .mappings()
                    .one()
                )
                published_refs, published_gaps = current_sources(c, original)
            entry = {
                "entry_id": str(identity),
                "latest": history[-1],
                "current_publication": latest_pub,
                "published_version": published,
                "latest_sources": refs,
                "latest_source_gaps": gaps,
                "published_sources": published_refs,
                "published_source_gaps": published_gaps,
                "versions": history,
                "publications": publications,
            }
            entries.append(entry)
            if not latest_pub or latest_pub["version_id"] != history[-1]["id"]:
                warnings.append(f"条目 {identity} 的最新版尚未发布；已发布原版单列。")
            if gaps or published_gaps:
                warnings.append(f"条目 {identity} 存在来源变化或缺失，原风险判断须重核。")
        body["entries"] = entries
        warnings.append(
            "本报告仅包含明确选中的条目；S/O/D沿原版本和原评分依据，不补评分，不代表全项目风险覆盖。"
        )
    elif scope.kind == "gate":
        t = tables.gates
        gate = (
            c.execute(scoped(t, context, project).where(t.c.id == scope.object_id))
            .mappings()
            .one_or_none()
        )
        if gate is None:
            raise ProductWorkError("Gate不存在或不属于当前项目")
        actual = {"gate": _plain(gate)}
        for key, table, order in [
            ("rounds", tables.gate_signoff_rounds, "round_number"),
            ("signoffs", tables.gate_signoffs, "created_at"),
            ("additions", tables.gate_signoff_additions, "created_at"),
            ("exemptions", tables.gate_grandfather_exemptions, "created_at"),
            ("historical_records", tables.gate_history_records, "reviewed_at"),
            ("decisions", tables.decisions, "created_at"),
        ]:
            actual[key] = all_rows(
                c,
                scoped(table, context, project)
                .where(table.c.gate_id == scope.object_id)
                .order_by(table.c[order], table.c.id),
            )
        body["actual"] = actual
        authorize(c, context, project, Action.WORK_ITEM_VIEW)
        task = tables.tasks
        actual["condition_tasks"] = all_rows(
            c,
            scoped(task, context, project)
            .where(
                task.c.kind == "gate_action",
                task.c.source_entity == "gate",
                task.c.source_entity_id == scope.object_id,
            )
            .order_by(task.c.created_at, task.c.id),
        )
        audit = tables.audit_log
        actual["condition_links"] = all_rows(
            c,
            select(audit.c.id, audit.c.timestamp, audit.c.actor_user_id, audit.c.context)
            .where(
                audit.c.tenant_id == context.tenant.id,
                audit.c.project_id == project,
                audit.c.entity == "gate",
                audit.c.entity_id == scope.object_id,
                audit.c.action == "gate.conditional",
            )
            .order_by(audit.c.timestamp, audit.c.id),
        )
        warnings = [
            "只重现已有签核/裁决和轮次快照，未重新进行Gate就绪判断。历史迁入记录与正式签核轮次分列；不代表认证通过。"
        ]
    else:
        assert scope.period_start is not None and scope.period_end is not None
        start = datetime.combine(scope.period_start, time.min, UTC)
        end = datetime.combine(scope.period_end + timedelta(days=1), time.min, UTC)
        audit = tables.audit_log
        events = all_rows(
            c,
            select(
                audit.c.id,
                audit.c.entity,
                audit.c.entity_id,
                audit.c.action,
                audit.c.timestamp,
                audit.c.actor_user_id,
            )
            .where(
                audit.c.tenant_id == context.tenant.id,
                audit.c.project_id == project,
                audit.c.timestamp >= start,
                audit.c.timestamp < end,
                audit.c.entity.in_(["task", "issue"]),
            )
            .order_by(audit.c.timestamp, audit.c.id),
        )
        values = {}
        for key, table, columns in [
            (
                "tasks",
                tables.tasks,
                (
                    "id",
                    "title",
                    "status",
                    "assignee_user_id",
                    "due_date",
                    "completed_at",
                    "blocked_reason",
                    "updated_at",
                ),
            ),
            (
                "issues",
                tables.issues,
                (
                    "id",
                    "title",
                    "status",
                    "severity",
                    "owner_user_id",
                    "verifier_user_id",
                    "target_date",
                    "closed_at",
                    "reopen_count",
                    "updated_at",
                ),
            ),
        ]:
            identities = [UUID(v["entity_id"]) for v in events if v["entity"] == key[:-1]]
            values[key] = all_rows(
                c,
                select(*(table.c[k] for k in columns))
                .where(
                    table.c.tenant_id == context.tenant.id,
                    table.c.project_id == project,
                    *([table.c.withdrawn_at.is_(None)] if table is tables.issues else []),
                    or_(
                        table.c.id.in_(identities),
                        table.c.status.not_in(["done", "closed", "cancelled", "skipped"]),
                    ),
                )
                .order_by(table.c.id),
            )
        body["events"] = events
        body["current_work"] = values
        user_ids = {
            UUID(identity)
            for records in [*values.values(), events]
            for record in records
            for key, identity in record.items()
            if key.endswith("_user_id") and identity is not None
        }
        people = all_rows(
            c,
            select(tables.users.c.id, tables.users.c.display_name)
            .where(tables.users.c.tenant_id == context.tenant.id, tables.users.c.id.in_(user_ids))
            .order_by(tables.users.c.id),
            maximum=4000,
        )
        body["people"] = people
        sections = [
            (
                "统计窗口",
                f"UTC {scope.period_start} 至 {scope.period_end}（含结束日）。"
                "以下办理日志按该窗口；对象状态是本次读取当前值，并非历史日末快照。",
            ),
            *weekly_sections(values, events, people),
        ]
        warnings = [
            "本模板覆盖任务/问题办理与当前待办；成本、齐套、进度预测及正式对外Commitment未纳入此版本，未据内部任务日期推定客户承诺。",
            "无日志只说明此窗口没有已登记的上述办理，不推定没有实际工作；报告未经具名审批。",
        ]
    if scope.kind in {"gate", "dfmea"}:
        records = body["actual"] if scope.kind == "gate" else body["entries"]
        people = all_rows(
            c,
            select(tables.users.c.id, tables.users.c.display_name)
            .where(
                tables.users.c.tenant_id == context.tenant.id,
                tables.users.c.id.in_({UUID(identity) for identity in people_ids(records)}),
            )
            .order_by(tables.users.c.id),
            maximum=4000,
        )
        body["people"] = people
        sections = (
            gate_sections(body["actual"], people)
            if scope.kind == "gate"
            else dfmea_sections(body["entries"], people)
        )
    title = row["name"] + " · " + LABELS[scope.kind]
    body.update({"title": title, "status_label": status, "warnings": warnings})
    body["sections"] = [
        {"title": h, "text": t}
        for h, t in [
            ("范围与状态", "内部用途。" + status + "；以系统当前来源和业务审批为准。"),
            (
                "项目与所选范围",
                f"项目：{row['name']}（{row['code']}）\n"
                f"报告：项目周报\n统计日期：{scope.period_start} 至 {scope.period_end}（UTC）"
                if scope.kind == "weekly"
                else (
                    f"项目：{row['name']}（{row['code']}）\n报告：8D 问题解决报告\n"
                    f"所选 NCR：{body['actual']['record']['code']}"
                    if scope.kind == "8d"
                    else (
                        f"项目：{row['name']}（{row['code']}）\n报告：{LABELS[scope.kind]}\n"
                        + (
                            f"所选 Gate：{body['actual']['gate']['name']}"
                            if scope.kind == "gate"
                            else f"明确选中 {len(scope.entry_ids)} 项；未选条目不纳入报告。"
                        )
                        if scope.kind in {"gate", "dfmea"}
                        else (
                            (
                                f"项目：{row['name']}（{row['code']}）\n报告：签核与审核条款证据包\n"
                                f"明确选择 {len(scope.audit_clauses)} 条要求；"
                                "未选条款不在本次范围。"
                            )
                            if scope.kind == "audit" and body["template_version"] == AUDIT_VERSION
                            else value(body["project"]) + "\n" + value(body["scope"])
                        )
                    )
                ),
            ),
            ("缺项和适用限制", "\n".join(warnings)),
            *sections,
        ]
    ]
    return {**body, "digest": digest(body)}
