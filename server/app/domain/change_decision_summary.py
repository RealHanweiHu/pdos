"""Source-backed change brief: recorded facts, unresolved matters and proposed actions."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.domain.change_discussion_briefs import comparison_summaries
from app.domain.change_execution_overview import _read as execution_overview
from app.domain.change_execution_results import _access
from app.domain.change_quiet_periods import state as quiet_state
from app.domain.product_workspace import _plain, digest


def read(engine: Engine, context: AuthContext, project: UUID, ecr_id: UUID) -> dict[str, Any]:
    _access(engine, context, project, Action.CHANGE_VIEW)
    tenant = context.tenant.id
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        quiet = quiet_state(c, tenant, project, ecr_id)
        ecr = quiet["ecr"]
        analysis = ecr["impact_analysis"] or {}
        bound = (analysis.get("impact_scope") or {}).get("basis")
        version = bound["version"] if bound else None
        proposals = []
        for kind in ("id_design", "professional", "supplier_notices"):
            section = analysis.get(kind) or {}
            for axis, value in (section.get("assessments") or {}).items():
                proposals.append({"source": kind, "axis": axis, **value})
        for index, response in enumerate(
            (analysis.get("supplier_notices") or {}).get("source_responses", {}).values(), 1
        ):
            proposals.append({"source": "supplier_notices", "axis": f"通告 {index}", **response})
        notices, decisions = tables.engineering_change_notices, tables.decisions
        ecns = [
            dict(r)
            for r in c.execute(
                select(notices)
                .where(
                    notices.c.tenant_id == tenant,
                    notices.c.project_id == project,
                    notices.c.ecr_id == ecr_id,
                )
                .order_by(notices.c.created_at, notices.c.id)
            ).mappings()
        ]
        decision_ids = {UUID(v) for v in [ecr["approval_decision_id"]] if v}
        decision_ids.update(
            r["effectivity_decision_id"] for r in ecns if r["effectivity_decision_id"]
        )
        actual_decisions = (
            [
                dict(r)
                for r in c.execute(
                    select(decisions).where(
                        decisions.c.tenant_id == tenant,
                        decisions.c.project_id == project,
                        decisions.c.id.in_(decision_ids),
                    )
                ).mappings()
            ]
            if decision_ids
            else []
        )
        execution = execution_overview(c, tenant, project, ecr_id)
        items = version["snapshot"]["items"] if version else []
        unresolved = []
        if not analysis:
            unresolved.append("尚未提交影响分析")
        elif ecr["status"] == "impact_analysis":
            unresolved.append("正在重新分析；保留的原分析不能视为本次已提交结论")
        if version is None:
            unresolved.append("尚无已提交分析绑定的具体影响范围")
        elif bound is not None:
            from app.domain.change_impact_scope import current_basis

            current = current_basis(c, tenant, project, ecr_id)
            if not current or current["version"]["id"] != version["id"] or not current["ready"]:
                unresolved.append("当前范围或来源已变化，需对照原分析重新核对")
        for kind, label in (("id_design", "ID 来源"), ("professional", "专业来源")):
            if not (analysis.get(kind) or {}).get("assessments"):
                unresolved.append(f"尚未登记{label}评估，未据此判定无影响")
        from app.domain.supplier_notice_impact import basis as notice_basis
        from app.domain.supplier_notice_impact import compact, has_sources

        notice_summary = None
        if has_sources(c, tenant, project, ecr_id):
            current_notices = notice_basis(c, context, project, ecr_id)
            notice_summary = {
                "source_count": len(current_notices["sources"]),
                "ready": all(v["ready"] for v in current_notices["sources"]),
                "matches_submitted": (analysis.get("supplier_notices") or {}).get("basis")
                == compact(current_notices),
            }
            if not notice_summary["ready"]:
                unresolved.append("关联通告的人审、来源或在用范围尚未就绪／不可读取")
            if not notice_summary["matches_submitted"]:
                unresolved.append("当前通告依据与已提交分析不一致或尚未纳入，须重新分析")
        if not quiet["origin"]:
            unresolved.append("历史变更缺少创建时冻结政策记录；无法据此判断当时是否命中窗口")
        people_ids = set()
        for record in [ecr, *ecns, *actual_decisions, *quiet["requests"], *quiet["adoptions"]]:
            for key, value in record.items():
                if key.endswith("_user_id") and value:
                    people_ids.add(UUID(str(value)))
        for record in quiet["requests"]:
            people_ids.update(UUID(v) for v in record["approver_ids"])
            people_ids.update(v["created_by_user_id"] for v in record["vote_history"])
        users = tables.users
        people = (
            [
                dict(r)
                for r in c.execute(
                    select(users.c.id, users.c.display_name).where(
                        users.c.tenant_id == tenant, users.c.id.in_(people_ids)
                    )
                ).mappings()
            ]
            if people_ids
            else []
        )
        payload = _plain(
            {
                "facts": {
                    "ecr": {k: v for k, v in ecr.items() if k != "impact_analysis"},
                    "analysis_digest": digest(analysis),
                    "supplier_notices": notice_summary,
                    "decisions": actual_decisions,
                    "ecns": ecns,
                },
                "analysis_summary": analysis.get("summary"),
                "analysis_status": "approved" if ecr["status"] == "approved" else "not_approved",
                "bound_scope": version,
                "assessments": proposals,
                "unknown_items": [i for i in items if i["conclusion"] == "unknown"],
                "unknown_assessments": [p for p in proposals if p["conclusion"] == "unknown"],
                "unresolved": unresolved,
                "quiet": {k: quiet[k] for k in ("origin", "adoptions", "required", "requests")},
                "execution": {
                    k: execution[k]
                    for k in (
                        "counts",
                        "required_count",
                        "all_required_verified",
                        "scope_gaps",
                        "source_changes",
                    )
                },
                "discussion_comparisons": comparison_summaries(c, tenant, project, ecr_id)
                if is_allowed(context.user.role, Action.QUALITY_VIEW)
                else None,
                "people": people,
            }
        )
        return {**payload, "digest": digest(payload), "read_at": datetime.now(UTC).isoformat()}
