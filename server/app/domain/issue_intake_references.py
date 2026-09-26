"""Read actual incoming business references for every Issue in a source's history."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Engine, String, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_state import effective_sources, reference_edges
from app.domain.issue_intake_corrections import IssueIntakeCorrections, source_state
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest

ReferenceKind = Literal[
    "task",
    "risk",
    "decision",
    "test_case",
    "test_run",
    "quality_link",
    "capa",
    "fmea",
    "fmea_candidate",
    "change_scope",
    "memory",
]
KINDS = {
    "task": ("问题行动任务", Action.WORK_ITEM_VIEW),
    "risk": ("问题来源风险", Action.WORK_ITEM_VIEW),
    "decision": ("问题裁决", Action.WORK_ITEM_VIEW),
    "test_case": ("关联测试项", Action.PRODUCT_ENGINEERING_VIEW),
    "test_run": ("关联测试项的实际执行", Action.PRODUCT_ENGINEERING_VIEW),
    "quality_link": ("NCR关系及解除记录", Action.QUALITY_VIEW),
    "capa": ("关联NCR的CAPA措施", Action.QUALITY_VIEW),
    "fmea": ("引用问题的FMEA版本", Action.QUALITY_VIEW),
    "fmea_candidate": ("问题来源的FMEA候选", Action.QUALITY_VIEW),
    "change_scope": ("引用问题的变更范围版本", Action.CHANGE_VIEW),
    "memory": ("问题来源知识", Action.MEMORY_VIEW),
}
FIELDS = (
    "id",
    "title",
    "description",
    "kind",
    "status",
    "draft_state",
    "source_entity",
    "source_entity_id",
    "assignee_user_id",
    "owner_user_id",
    "start_date",
    "due_date",
    "target_date",
    "expected_output",
    "completion_evidence_ref",
    "completed_at",
    "updated_at",
    "created_at",
    "decision_kind",
    "historical_source",
    "outcome",
    "rationale",
    "consequence",
    "follow_up_state",
    "follow_up_task_id",
    "acceptance_criteria",
    "method",
    "result_notes",
    "executed_at",
    "test_case_id",
    "sample_id",
    "run_number",
    "evidence_document_id",
    "ncr_id",
    "origin",
    "reason",
    "action_type",
    "completion_summary",
    "entry_id",
    "version",
    "ecr_id",
    "revision_number",
    "content_sha256",
    "source_issue_id",
    "input_digest",
    "metrics",
    "conditions",
    "equipment",
    "environment",
    "started_at",
    "sample_configuration_revision_id",
    "evidence_refs",
    "follow_up_note",
    "mitigation_plan",
    "contingency_plan",
)


def query_for(kind: str, tenant: UUID, project: UUID, source: Any) -> tuple[Any, Any]:
    i, h = tables.issues.alias("referenced_issue"), tables.issue_intake_corrections
    in_history = exists(
        select(h.c.id).where(
            h.c.tenant_id == tenant,
            h.c.project_id == project,
            h.c.source_row_id == source["id"],
            or_(h.c.previous_issue_id == i.c.id, h.c.target_issue_id == i.c.id),
        )
    )
    anchors = [
        i.c.tenant_id == tenant,
        i.c.project_id == project,
        or_(i.c.id == source["issue_id"], in_history),
    ]
    extra: list[Any] = []

    def scope(t: Any) -> Any:
        return (t.c.tenant_id == tenant) & (t.c.project_id == project)

    if kind in {"task", "risk", "decision", "test_case", "memory", "fmea_candidate"}:
        t = {
            "task": tables.tasks,
            "risk": tables.risks,
            "decision": tables.decisions,
            "test_case": tables.test_cases,
            "memory": tables.memories,
            "fmea_candidate": tables.fmea_revision_candidates,
        }[kind]
        fk = {
            "task": "source_entity_id",
            "risk": "source_entity_id",
            "decision": "issue_id",
            "test_case": "related_issue_id",
            "memory": "source_issue_id",
            "fmea_candidate": "issue_id",
        }[kind]
        condition = t.c[fk] == i.c.id
        if kind in {"task", "risk"}:
            condition &= t.c.source_entity == ("issues" if kind == "task" else "issue")
        if kind == "decision":
            origins = tables.decision_intake_rows
            edges, active = reference_edges(tenant, project), effective_sources(tenant, project)
            relation_rows = origins.join(edges, edges.c.source_id == origins.c.id).join(
                active, active.c.id == origins.c.id
            )
            relation = (
                scope(origins) & (edges.c.decision_id == t.c.id) & (edges.c.issue_id == i.c.id)
            )
            condition |= exists(
                select(origins.c.id).select_from(relation_rows).where(relation).correlate(t, i)
            )
        joined = t.join(i, condition)
        if kind == "decision":
            follow = tables.tasks.alias("decision_follow_up")
            joined = joined.outerjoin(
                follow, scope(follow) & (follow.c.id == t.c.follow_up_task_id)
            )
            links = (
                select(
                    func.jsonb_agg(
                        aggregate_order_by(
                            func.jsonb_build_object(
                                "source_row_id",
                                origins.c.id,
                                "issue_id",
                                edges.c.issue_id,
                                "reason",
                                func.coalesce(active.c.reason, origins.c.issue_reason),
                                "original_reason",
                                origins.c.issue_reason,
                                "active",
                                func.coalesce(
                                    (active.c.decision_id == t.c.id)
                                    & (active.c.issue_id == i.c.id),
                                    False,
                                ),
                                "revision",
                                active.c.revision,
                                "impact_note",
                                active.c.impact_note,
                                "current_decision_id",
                                active.c.decision_id,
                                "current_issue_id",
                                active.c.issue_id,
                                "created_by_user_id",
                                origins.c.created_by_user_id,
                                "created_at",
                                origins.c.created_at,
                            ),
                            origins.c.created_at,
                            origins.c.id,
                        )
                    )
                )
                .select_from(relation_rows)
                .where(relation)
                .correlate(t, i)
                .scalar_subquery()
            )
            extra = [
                links.label("historical_issue_links"),
                follow.c.status.label("follow_up_task_status"),
                follow.c.updated_at.label("follow_up_task_updated_at"),
                follow.c.completion_evidence_ref.label("follow_up_task_evidence"),
            ]
    elif kind == "test_run":
        t, parent = tables.test_runs, tables.test_cases
        joined = t.join(parent, scope(parent) & (parent.c.id == t.c.test_case_id)).join(
            i, parent.c.related_issue_id == i.c.id
        )
        extra = [
            parent.c.title.label("via_title"),
            parent.c.id.label("via_id"),
            parent.c.updated_at.label("test_case_updated_at"),
            parent.c.acceptance_criteria.label("test_criteria"),
            parent.c.method.label("test_method"),
        ]
    elif kind in {"quality_link", "capa"}:
        link, retract, ncr = (
            tables.quality_issue_links,
            tables.quality_issue_link_retractions,
            tables.nonconformance_reports,
        )
        t = link if kind == "quality_link" else tables.capa_actions
        joined = link.join(i, link.c.issue_id == i.c.id).join(
            ncr, scope(ncr) & (ncr.c.id == link.c.ncr_id)
        )
        if kind == "capa":
            # The same CAPA may have several historical links to one Issue; retain each path.
            joined = joined.join(t, scope(t) & (t.c.ncr_id == ncr.c.id))
        joined = joined.outerjoin(retract, scope(retract) & (retract.c.link_id == link.c.id))
        extra = [
            link.c.id.label("link_id"),
            ncr.c.code.label("via_title"),
            ncr.c.id.label("via_id"),
            ncr.c.status.label("ncr_status"),
            ncr.c.updated_at.label("ncr_updated_at"),
            ncr.c.nonconformity.label("ncr_nonconformity"),
            ncr.c.containment_action.label("ncr_containment_action"),
            ncr.c.effectiveness_criteria.label("ncr_effectiveness_criteria"),
            retract.c.id.label("retraction_id"),
            retract.c.reason.label("retraction_reason"),
            retract.c.created_at.label("retracted_at"),
        ]
        anchors.append(scope(link))
    elif kind in {"fmea", "change_scope"}:
        t = tables.fmea_versions if kind == "fmea" else tables.change_impact_scope_versions
        refs = t.c.body["references"] if kind == "fmea" else t.c.snapshot["items"]
        contains = refs.op("@>")(
            func.jsonb_build_array(
                func.jsonb_build_object("kind", "issue", "id", cast(i.c.id, String))
            )
        )
        joined = t.join(i, contains)
        if kind == "change_scope":
            parent = tables.engineering_change_requests
            joined = joined.join(parent, scope(parent) & (parent.c.id == t.c.ecr_id))
            extra = [
                parent.c.title.label("via_title"),
                parent.c.status.label("ecr_status"),
                parent.c.updated_at.label("ecr_updated_at"),
            ]
        else:
            extra = [
                t.c.body["title"].astext.label("title"),
                t.c.body["failure_mode"].astext.label("failure_mode"),
            ]
            pub = tables.fmea_publications
            extra.append(
                exists(select(pub.c.id).where(scope(pub), pub.c.version_id == t.c.id)).label(
                    "was_published"
                )
            )
        latest = t.alias("later_version")
        parent_key = "entry_id" if kind == "fmea" else "ecr_id"
        version_key = "version" if kind == "fmea" else "revision_number"
        extra.append(
            (
                ~exists(
                    select(latest.c.id).where(
                        scope(latest),
                        latest.c[parent_key] == t.c[parent_key],
                        latest.c[version_key] > t.c[version_key],
                    )
                )
            ).label("is_latest_version")
        )
    else:
        raise ConversationError("请选择已支持的业务引用类型")
    # A link is part of the page identity for repeated historical Issue/NCR paths.
    link_id = tables.quality_issue_links.c.id if kind == "capa" else t.c.id
    query = (
        select(
            *[t.c[key] for key in FIELDS if key in t.c],
            *extra,
            i.c.id.label("referenced_issue_id"),
            i.c.title.label("issue_title"),
            link_id.label("path_id"),
        )
        .select_from(joined)
        .where(scope(t), *anchors)
    )
    return query, t


def href(kind: str, project: UUID, row: dict[str, Any]) -> str:
    base = f"/projects?project={project}"
    if kind in {"task", "risk"}:
        return f"{base}&tab=work-items&entity_id={row['id']}"
    if kind == "decision":
        return f"{base}&tab=decisions"
    if kind in {"test_case", "test_run"}:
        return f"{base}&tab=quality&test_case_id={row.get('test_case_id', row['id'])}" + (
            f"&test_run_id={row['id']}" if kind == "test_run" else ""
        )
    if kind in {"quality_link", "capa"}:
        return f"{base}&tab=quality&ncr={row['ncr_id']}"
    if kind == "change_scope":
        return f"{base}&tab=engineering#ecr-{row['ecr_id']}"
    if kind in {"fmea", "fmea_candidate"}:
        return f"{base}&tab=quality"
    return "/knowledge"


def reference_view(kind: str, project: UUID, row: Any) -> dict[str, Any]:
    value = _plain(row)
    for key in ("historical_source", "historical_issue_links"):
        if value.get(key) is None:
            value.pop(key, None)
    # An Issue rename does not change the referred business result or its relationship.
    facts_digest = digest({key: item for key, item in value.items() if key != "issue_title"})
    return {
        "kind": kind,
        "id": value["id"],
        "issue_id": value["referenced_issue_id"],
        "path_id": value["path_id"],
        "issue_title": value["issue_title"],
        "title": next(
            (
                str(value[k])
                for k in ("title", "failure_mode", "via_title", "description")
                if value.get(k)
            ),
            KINDS[kind][0],
        ),
        "facts": value,
        "digest": facts_digest,
        "href": href(kind, project, value),
    }


class IssueIntakeReferences:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        *,
        kind: ReferenceKind = "task",
        issue_id: UUID | None = None,
        before_id: UUID | None = None,
        before_issue_id: UUID | None = None,
        before_path_id: UUID | None = None,
    ) -> dict[str, Any]:
        cursor = (before_id, before_issue_id, before_path_id)
        if any(value is not None for value in cursor) and any(value is None for value in cursor):
            raise ConversationError("引用分页位置不完整，请重新读取")
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            source = IssueIntakeCorrections.source(c, ctx, project, identity)
            allowed = []
            for key, (label, action) in KINDS.items():
                try:
                    KnowledgeCorrectionService._authorize(
                        c, ctx.tenant.id, ctx.user.id, project, action
                    )
                except KnowledgeAccessError:
                    continue
                allowed.append({"kind": key, "label": label})
            if kind not in {item["kind"] for item in allowed}:
                raise KnowledgeAccessError("当前没有读取此类业务引用的权限")
            query, _ = query_for(kind, ctx.tenant.id, project, source)
            # Subquery columns keep the composite cursor independent of join aliases.
            q = query.subquery()
            query = select(q)
            if issue_id is not None:
                query = query.where(q.c.referenced_issue_id == issue_id)
            if before_id is not None:
                query = query.where(
                    or_(
                        q.c.id < before_id,
                        (q.c.id == before_id) & (q.c.referenced_issue_id < before_issue_id),
                        (q.c.id == before_id)
                        & (q.c.referenced_issue_id == before_issue_id)
                        & (q.c.path_id < before_path_id),
                    )
                )
            rows = (
                c.execute(
                    query.order_by(
                        q.c.id.desc(), q.c.referenced_issue_id.desc(), q.c.path_id.desc()
                    ).limit(51)
                )
                .mappings()
                .all()
            )
            items = [reference_view(kind, project, row) for row in rows[:50]]
            return {
                "source_id": str(identity),
                "current_source": source_state(c, ctx.tenant.id, source),
                "kind": kind,
                "kinds": allowed,
                "items": items,
                "read_at": datetime.now(UTC).isoformat(),
                "next": {
                    "before_id": str(rows[49]["id"]),
                    "before_issue_id": str(rows[49]["referenced_issue_id"]),
                    "before_path_id": str(rows[49]["path_id"]),
                }
                if len(rows) > 50
                else None,
                "coverage": (
                    "本来源最初及历史关联问题的明确业务引用；"
                    "含关联测试执行、NCR/CAPA及历史范围版本。每类单独分页。"
                ),
                "remaining": (
                    "自由文本、未登记关系、其他快照中的引用及更深层后继仍需人工核对；"
                    "没有查询结果不能证明可撤销全部业务。"
                ),
            }
