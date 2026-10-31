"""Fixed Issue/Change cards and unsaved-title hints through ordinary RLS retrieval."""
# ruff: noqa: I001 -- shared schema registers domain models before direct domain imports

from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import and_, select, text, tuple_

from pdos_next.models import Category, Principal, Product
from pdos_next.database import require_context
from pdos_next.domain.change_execution.models import ChangeRequestVersion
from pdos_next.domain.projects.models import Project
from pdos_next.domain.quality_execution.models import QualityIssueVersion
from pdos_next.errors import DomainError
from pdos_next.service import digest, require_access

from .navigation import links
from .query import search
from .relations import edges
from .safety import safe_originals
from .schemas import SearchInput
from .similar_history_models import SimilarHistoryFeedback as FeedbackRow
from .similar_history_schemas import SimilarHistoryFeedback, SimilarHistoryTitleInput
from .similar_history_context import structural_context
from .sources import catalog, prepare_read

KINDS = ("issue", "capa", "change")
LIMIT = 5


def _human(session, ctx):
    require_context(session, ctx)
    if (ctx.category_id is None or ctx.actor_id != ctx.requester_id
            or ctx.run_id is not None or ctx.agent_run_id is not None):
        raise DomainError("FORBIDDEN_SCOPE", "相似历史须由本人在当前可读范围查看。", 403)
    person = session.scalar(select(Principal.id).where(
        Principal.tenant_id == ctx.tenant_id, Principal.id == ctx.actor_id,
        Principal.kind == "human", Principal.active.is_(True),
    ))
    if person is None:
        raise DomainError("FORBIDDEN_SCOPE", "当前查看者不可用。", 403)


def _anchor(session, ctx, product_id, issue_id, version_id):
    prepare_read(session, KINDS)
    authority = catalog(["issue"])
    row = session.execute(select(QualityIssueVersion, authority.c.original_ids).join(
        authority, and_(authority.c.source_id == QualityIssueVersion.id,
                        authority.c.tenant_id == QualityIssueVersion.tenant_id),
    ).where(
        QualityIssueVersion.tenant_id == ctx.tenant_id,
        QualityIssueVersion.category_id == ctx.category_id,
        QualityIssueVersion.product_id == product_id,
        QualityIssueVersion.issue_id == issue_id, QualityIssueVersion.id == version_id,
    )).one_or_none()
    if row is None or not set(row[1]) <= safe_originals(session, row[1]):
        raise DomainError("FORBIDDEN_SCOPE", "当前问题或其依据不可读取。", 403)
    return row[0]


def _change_anchor(session, ctx, product_id, change_id, version_id):
    prepare_read(session, KINDS)
    authority = catalog(["change"])
    row = session.execute(select(ChangeRequestVersion, authority.c.original_ids).join(
        authority, and_(authority.c.source_id == ChangeRequestVersion.id,
                        authority.c.tenant_id == ChangeRequestVersion.tenant_id),
    ).where(
        ChangeRequestVersion.tenant_id == ctx.tenant_id,
        ChangeRequestVersion.category_id == ctx.category_id,
        ChangeRequestVersion.product_id == product_id,
        ChangeRequestVersion.change_id == change_id, ChangeRequestVersion.id == version_id,
    )).one_or_none()
    if row is None or not set(row[1]) <= safe_originals(session, row[1]):
        raise DomainError("FORBIDDEN_SCOPE", "当前变更或其依据不可读取。", 403)
    return row[0]


def _exclusions(session, anchor, *, kind="issue"):
    """Exclude whole logical objects, including revisions and registered one-hop links."""
    seeds = {(kind, anchor.id)}
    if kind == "issue":
        seeds.add(("capa", anchor.id))
    graph = edges(set(KINDS), seeds)
    related = session.execute(select(graph.c.target_kind, graph.c.target_id)).all()
    quality_ids = ({anchor.id} if kind == "issue" else set()) | {
        row.target_id for row in related if row.target_kind in {"issue", "capa"}
    }
    result = []
    if quality_ids:
        q = QualityIssueVersion
        logical = select(q.issue_id).where(q.tenant_id == anchor.tenant_id, q.id.in_(quality_ids))
        versions = session.scalars(select(q.id).where(
            q.tenant_id == anchor.tenant_id, q.issue_id.in_(logical),
        ))
        result.extend((kind, identity) for identity in versions for kind in ("issue", "capa"))
    change_ids = ({anchor.id} if kind == "change" else set()) | {
        row.target_id for row in related if row.target_kind == "change"
    }
    if change_ids:
        c = ChangeRequestVersion
        identities = select(c.change_id).where(c.tenant_id == anchor.tenant_id,
                                                c.id.in_(change_ids))
        result.extend(("change", identity) for identity in session.scalars(select(c.id).where(
            c.tenant_id == anchor.tenant_id, c.change_id.in_(identities),
        )))
    return result


def _text(value, *, limit=240):
    if not isinstance(value, str) or not value.strip():
        return "未记录"
    return value.strip()[:limit] + ("…（摘录）" if len(value.strip()) > limit else "")


def quality_fields(snapshot):
    root = snapshot.get("root_cause") or {}
    capa = snapshot.get("capa") or {}
    decision = capa.get("effectiveness") or {}
    result = decision.get("result")
    verification = (
        "该固定记录已具名判为有效，当前适用性仍须核对" if result == "effective"
        else "该固定记录已具名判为无效" if result == "ineffective"
        else "待复验：该固定记录未登记有效性决定"
    )
    if snapshot.get("needs_recheck"):
        verification = "依据待重核；" + verification
    return {
        "root_cause": _text(root.get("text")),
        "containment": [_text(row.get("text"), limit=160)
                        for row in snapshot.get("containment", [])[:3]] or ["未记录"],
        "capa_actions": [_text(row.get("text"), limit=160)
                         for row in capa.get("actions", [])[:3]] or ["未记录"],
        "verification": verification,
    }


def change_fields(snapshot):
    actions, verification = [], []
    for order in snapshot.get("orders", []):
        actions.extend("计划：" + _text(item.get("intent", {}).get("description"), limit=160)
                       for item in order.get("plan", {}).get("items", []))
        actions.extend("实施：" + _text(item.get("note"), limit=160)
                       + "；登记结果：" + str(item.get("outcome", "未记录"))
                       for item in order.get("implementations", []))
        verification.extend(_text(item.get("text"), limit=160)
                            + "；具名结果：" + str(item.get("fact", {}).get("result", "未记录"))
                            for item in order.get("verifications", []))
        verification.extend("生效阶段：" + str(item.get("stage", "未记录"))
                            + "；结果：" + str(item.get("outcome", "未记录"))
                            for item in order.get("effectivity", []))
    return {
        "root_cause": "未记录：根因结论须查看所关联的问题",
        "containment": ["未记录（变更未登记临时遏制）"],
        "capa_actions": actions[:3] or ["未记录变更计划或实施措施"],
        "verification": "；".join(verification[:3]) if verification
        else "待复验：该固定变更未登记验证或生效结果",
    }


def differences(anchor, candidate, names, context):
    current, other = str(anchor.product_id), str(candidate["product_id"])
    anchor_id, other_id = str(anchor.id), candidate["source_id"]
    def comparison(field, left, right):
        return {"field": field, "status": "unknown" if not left or not right
                else "same" if left == right else "different",
                "current": "；".join(left) if left else "未记录或未读取",
                "candidate": "；".join(right) if right else "未记录或未读取"}
    return [
        {"field": "型号", "status": "same" if current == other else "different",
         "current": names.get(("product", current), "名称未读取"),
         "candidate": names.get(("product", other), "名称未读取")},
        comparison("已读实际配置BOM料号（非故障件认定）",
                   context["parts"].get(anchor_id), context["parts"].get(other_id)),
        comparison("试制轮次编号/名称", context["builds"].get(anchor_id),
                   context["builds"].get(other_id)),
        comparison("项目当前阶段（非历史发生阶段）",
                   [context["stages"][str(anchor.project_id)]]
                   if str(anchor.project_id) in context["stages"] else [],
                   [context["stages"][candidate["project_id"]]]
                   if candidate["project_id"] in context["stages"] else []),
    ]


def _names(session, anchor, candidates):
    names = {}
    for kind, model, identities in (
        ("category", Category, {anchor.category_id} | {UUID(row["category_id"])
                                                      for row in candidates}),
        ("project", Project, ({anchor.project_id} if anchor.project_id else set())
         | {UUID(row["project_id"]) for row in candidates}),
        ("product", Product, {anchor.product_id} | {UUID(row["product_id"])
                                                   for row in candidates}),
    ):
        for identity, name in session.execute(select(model.id, model.name).where(
            model.tenant_id == anchor.tenant_id, model.id.in_(identities),
        )):
            names[kind, str(identity)] = name
    return names


def read(session, ctx, product_id, issue_id, version_id):
    _human(session, ctx)
    anchor = _anchor(session, ctx, product_id, issue_id, version_id)
    query = (anchor.issue_snapshot["title"] + "\n" + anchor.reason)[:2000]
    return _view(session, ctx, anchor, query, exclusions=_exclusions(session, anchor))


def read_change(session, ctx, product_id, change_id, version_id):
    _human(session, ctx)
    anchor = _change_anchor(session, ctx, product_id, change_id, version_id)
    snapshot = anchor.request_snapshot
    query = (snapshot["title"] + "\n" + snapshot["reason"])[:2000]
    return _view(session, ctx, anchor, query, kind="change",
                 exclusions=_exclusions(session, anchor, kind="change"))


def read_title(session, ctx, product_id, data: SimilarHistoryTitleInput):
    _human(session, ctx)
    product = require_access(session, ctx, product_id)
    if data.project_id is not None:
        from pdos_next.domain.work_management.owner import project

        project(session, ctx, product_id, data.project_id)
    # This is an unsaved form context, never an Issue/Change or source version.
    anchor = SimpleNamespace(
        id=None, tenant_id=ctx.tenant_id, category_id=product.category_id,
        product_id=product.id, project_id=data.project_id, title=data.title,
    )
    return _view(session, ctx, anchor, data.title, kind=data.kind + "_draft")


def _anchor_view(anchor, kind):
    base = {"category_id": str(anchor.category_id), "product_id": str(anchor.product_id),
            "project_id": str(anchor.project_id) if anchor.project_id else None}
    if kind.endswith("_draft"):
        return {**base, "kind": kind, "title": anchor.title}
    return {**base, "version_id": str(anchor.id), "revision": anchor.revision, **(
        {"issue_id": str(anchor.issue_id), "title": anchor.issue_snapshot["title"]}
        if kind == "issue" else {"kind": "change", "change_id": str(anchor.change_id),
                                 "title": anchor.request_snapshot["title"]}
    )}


def _view(session, ctx, anchor, query, *, kind="issue", exclusions=()):
    result = search(session, ctx, SearchInput(
        query=query, source_types=list(KINDS), category_id=ctx.category_id, limit=20,
    ), exclude_sources=exclusions)
    # Retrieval authorizes before ranking; hydration repeats its fixed identity/hash.
    selected, seen = [], set()
    for row in result["items"]:
        identity = ("quality" if row["source_type"] in {"issue", "capa"} else "change",
                    row["source_id"])
        if identity not in seen:
            selected.append(row)
            seen.add(identity)
        if len(selected) == LIMIT:
            break
    authority = catalog(KINDS)
    records = {} if not selected else {
        (row["source_type"], str(row["source_id"])): row
        for row in session.execute(select(authority).where(
            authority.c.tenant_id == ctx.tenant_id,
            tuple_(authority.c.source_type, authority.c.source_id).in_(
                [(row["source_type"], UUID(row["source_id"])) for row in selected]
            ),
        )).mappings()
    }
    quality_ids = {UUID(row["source_id"]) for row in selected
                   if row["source_type"] in {"issue", "capa"}}
    snapshots = {} if not quality_ids else {
        str(row.id): row.issue_snapshot for row in session.scalars(
            select(QualityIssueVersion).where(
                QualityIssueVersion.tenant_id == ctx.tenant_id,
                QualityIssueVersion.id.in_(quality_ids),
            )
        )
    }
    change_ids = {UUID(row["source_id"]) for row in selected if row["source_type"] == "change"}
    changes = {} if not change_ids else {
        str(row.id): row.request_snapshot for row in session.scalars(select(ChangeRequestVersion)
            .where(ChangeRequestVersion.tenant_id == ctx.tenant_id,
                   ChangeRequestVersion.id.in_(change_ids)))
    }
    anchor_snapshots = {str(anchor.id): anchor.issue_snapshot} if kind == "issue" else {}
    projects = ({anchor.project_id} if anchor.project_id else set()) | {
        UUID(row["project_id"]) for row in selected
    }
    context = structural_context(
        session, ctx.tenant_id, {**snapshots, **anchor_snapshots}, projects,
    )
    names = _names(session, anchor, selected)
    destinations = links(session, {str(index): row for index, row in enumerate(selected)})
    cards = []
    for index, source in enumerate(selected):
        stored = records.get((source["source_type"], source["source_id"]))
        if (stored is None or stored["content_hash"] != source["content_hash"]
                or stored["source_revision"] != source["source_revision"]):
            continue
        snapshot = snapshots.get(source["source_id"])
        fields = quality_fields(snapshot) if snapshot else change_fields(
            changes.get(source["source_id"], {}),
        )
        facts = stored["structured"]["facts"]
        reason = {"exact_id": "对象编号命中", "exact_code": "同编号",
                  "code_family": "同系列编号", "keyword": "标题或记录词命中",
                  "relation": "与命中案例存在登记关系"}[source["channel"]]
        same_scope = (str(anchor.product_id) == source["product_id"]
                      and str(anchor.project_id) == source["project_id"])
        merge = bool(kind == "issue" and snapshot and source["source_type"] == "issue"
                     and same_scope
                     and source["is_current"] and source["read_basis_status"] == "current"
                     and snapshot.get("status") in {"open", "triaged"}
                     and not snapshot.get("root_cause") and not snapshot.get("capa")
                     and not snapshot.get("merged_into"))
        cards.append({
            "kind": source["source_type"], "title": source["title"],
            "object_id": source["object_id"], "source_id": source["source_id"],
            "source_revision": source["source_revision"], "is_current": source["is_current"],
            "status": facts.get("status", facts.get("issue_status", "unknown")),
            "category": names.get(("category", source["category_id"]), "名称未读取"),
            "project": names.get(("project", source["project_id"]), "名称未读取"),
            "reason": reason, **fields, "differences": differences(anchor, source, names, context),
            "can_prepare_merge": merge,
            **destinations.get(str(index), {
                "object_url": None, "object_label": "原对象暂不可打开",
            }),
        })
    return {
        "version": "similar-history/v1", "as_of": result["as_of"],
        "anchor": _anchor_view(anchor, kind),
        "items": cards, "coverage": result["coverage"],
        "ranking_version": result["ranking_version"],
        "notice": "相似仅供查找经验，不代表重复、已验证或适用于当前问题。",
    }


def feedback(session, ctx, product_id, issue_id, data: SimilarHistoryFeedback):
    return _feedback(session, ctx, product_id, issue_id, data)


def feedback_change(session, ctx, product_id, change_id, data: SimilarHistoryFeedback):
    return _feedback(session, ctx, product_id, change_id, data, kind="change")


def _feedback(session, ctx, product_id, object_id, data, *, kind="issue"):
    _human(session, ctx)
    if kind == "change" and data.action == "merge_prepared":
        raise DomainError("FORBIDDEN_SCOPE", "只有问题之间可以准备归并。", 403)
    lock = int(digest(["similar-history-feedback", ctx.tenant_id, ctx.actor_id,
                       data.request_key])[:16], 16)
    if lock >= 2**63:
        lock -= 2**64
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock})
    fingerprint = digest({"product_id": product_id, kind + "_id": object_id,
                          **data.model_dump(mode="json", exclude={"request_key"})})
    existing = session.scalar(select(FeedbackRow).where(
        FeedbackRow.tenant_id == ctx.tenant_id, FeedbackRow.owner_id == ctx.actor_id,
        FeedbackRow.request_key == data.request_key,
    ))
    if existing is not None:
        if existing.request_sha256 != fingerprint:
            raise DomainError("VERSION_CONFLICT", "原反馈请求内容已变化，请重新查看卡片。", 409)
        return {"feedback_id": str(existing.id), "action": existing.action}
    view = (read if kind == "issue" else read_change)(
        session, ctx, product_id, object_id, data.version_id,
    )
    candidate = next((row for row in view["items"] if
                      row["kind"] == data.candidate_kind
                      and row["source_id"] == str(data.candidate_source_id)
                      and row["source_revision"] == data.candidate_revision), None)
    if candidate is None:
        raise DomainError("SOURCE_STALE", "候选已变化或不可读取，请重新查看相似历史。", 409)
    if data.action == "merge_prepared" and not candidate["can_prepare_merge"]:
        raise DomainError("FORBIDDEN_SCOPE", "当前候选不能进入问题归并准备。", 403)
    anchor = view["anchor"]
    row = FeedbackRow(
        tenant_id=ctx.tenant_id, category_id=ctx.category_id, product_id=product_id,
        project_id=UUID(anchor["project_id"]), owner_id=ctx.actor_id,
        issue_id=object_id if kind == "issue" else None,
        issue_version_id=data.version_id if kind == "issue" else None,
        issue_revision=anchor["revision"] if kind == "issue" else None,
        change_id=object_id if kind == "change" else None,
        change_version_id=data.version_id if kind == "change" else None,
        change_revision=anchor["revision"] if kind == "change" else None,
        candidate_kind=data.candidate_kind, candidate_source_id=data.candidate_source_id,
        candidate_revision=data.candidate_revision, ranking_version=view["ranking_version"],
        action=data.action, request_key=data.request_key, request_sha256=fingerprint,
    )
    session.add(row)
    session.flush()
    return {"feedback_id": str(row.id), "action": row.action}
