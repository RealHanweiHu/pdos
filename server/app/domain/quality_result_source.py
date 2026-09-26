"""Actual NCR chain and current evidence for product-definition feedback."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_sources import snapshot_problem
from app.domain.nonconformance import NcrNotFoundError
from app.domain.product_workspace import ProductWorkError, _plain, _role
from app.domain.quality_operations import evidence_value, state


def ncr_source(
    c: Connection, context: AuthContext, project: UUID, identity: UUID
) -> dict[str, Any]:
    try:
        chain = state(c, context.tenant.id, project, identity)
    except NcrNotFoundError as error:
        raise ProductWorkError("原 NCR 不存在或不属于当前项目") from error
    roots, actions, reviews = chain["root_causes"], chain["actions"], chain["reviews"]
    root = roots[-1] if roots else None
    review = reviews[-1] if reviews else None
    current_root = root if root and root["status"] == "approved" else None
    warnings = []
    if current_root is None:
        warnings.append("当前尚无有效已批准根因；草稿、历史替代版本不当作确认根因。")
    if review is None:
        warnings.append("尚无实际有效性复核，不把整改完成当作已经有效。")
    elif review["result"] == "ineffective":
        warnings.append("最近一次整改复核无效，保留失败结果及后续行动，不推定已经恢复。")
    if chain["ncr"]["status"] != "closed":
        warnings.append("原 NCR 尚未关闭，本次反馈不替代质量关闭或产品定义发布。")
    refs = []
    basis_times: dict[tuple[str, str], list[datetime]] = {}
    for item in [
        *([current_root] if current_root else []),
        *[a for a in actions if a["status"] == "completed"],
        *([review] if review else []),
    ]:
        refs.extend(item["evidence_refs"])
        basis_time = item.get("approved_at") or item.get("completed_at") or item.get("reviewed_at")
        if basis_time:
            for ref in item["evidence_refs"]:
                basis_times.setdefault((ref["kind"], ref["reference"]), []).append(
                    datetime.fromisoformat(basis_time)
                )
    resolved, missing = [], []
    for kind, reference in dict.fromkeys((ref["kind"], ref["reference"]) for ref in refs):
        try:
            if kind in {"document", "event", "test_run"}:
                value = evidence_value(c, context.tenant.id, project, kind, reference)
                if kind == "test_run" and (
                    value["draft_state"] != "confirmed"
                    or value["status"] not in {"passed", "failed", "aborted"}
                ):
                    raise ProductWorkError("测试依据尚未确认实际结果")
            elif kind == "decision":
                t = tables.decisions
                row = (
                    c.execute(
                        select(t).where(
                            t.c.tenant_id == context.tenant.id,
                            t.c.project_id == project,
                            t.c.id == UUID(reference),
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    raise ProductWorkError("决策依据不可用")
                value = _plain(row)
            elif kind == "evidence_snapshot":
                _role(context, Action.EVIDENCE_VIEW)
                t, s = tables.evidence_snapshots, tables.research_sources
                row = (
                    c.execute(
                        select(t, s.c.status.label("source_status"))
                        .outerjoin(s, (s.c.tenant_id == t.c.tenant_id) & (s.c.id == t.c.source_id))
                        .where(t.c.tenant_id == context.tenant.id, t.c.id == UUID(reference))
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None or snapshot_problem(c, context.tenant.id, row):
                    raise ProductWorkError("共享证据版本已不可用或失效")
                value = _plain(row)
            else:
                raise ProductWorkError("此类原依据待人工核对")
            times = basis_times.get((kind, reference), [])
            changed = bool(
                value.get("updated_at")
                and times
                and datetime.fromisoformat(value["updated_at"]) > min(times)
            )
            resolved.append(
                {
                    "kind": kind,
                    "reference": reference,
                    "current_record": value,
                    "changed_since_quality_basis": changed,
                }
            )
            if changed:
                missing.append({"kind": kind, "reference": reference})
                warnings.append(
                    "原质量依据在具名判断后已变化；当前值单列，不能替代当时版本作为采用依据。"
                )
        except (ValueError, LookupError, PermissionError):
            missing.append({"kind": kind, "reference": reference})
    if missing:
        warnings.append("当前根因、已完成行动或最近复核存在不可用依据，需补证后再采用。")
    if not resolved:
        warnings.append("尚无可核对的当前结果依据，不能仅用计划或状态证明效果。")
    return {
        "kind": "ncr",
        "record": chain["ncr"],
        "quality_chain": chain,
        "current_approved_root": current_root,
        "latest_review": review,
        "evidence": resolved,
        "missing_evidence": missing,
        "warnings": warnings,
        "interpretation": (
            "只保存原质量判断、证据与人工适用依据，不从投诉数量推算失效率，不将相关性提升为因果。"
        ),
    }
