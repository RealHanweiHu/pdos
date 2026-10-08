"""Read-only personal product queue; original domain endpoints still make every decision."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import Engine, and_, select

from app.ai.product_work_context import readable
from app.ai.product_work_runs import RUN_VERSION, authorize
from app.auth.repository import AuthContext
from app.contracts.product_work_ai import ProductWorkSelection
from app.db.schema import tables
from app.domain.product_evidence_findings import CONFIG
from app.domain.product_evidence_items import item_receipts, item_title
from app.domain.product_workspace import ProductWorkError, _plain, digest


class AttentionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_line_id: UUID | None = None
    all_lines: bool = False

    @model_validator(mode="after")
    def explicit_scope(self) -> "AttentionScope":
        if self.all_lines and self.product_line_id:
            raise ValueError("全部范围不能同时绑定单一产品线")
        return self


def selection_for_summary(row: Any, context: AuthContext, space_id: UUID) -> ProductWorkSelection:
    saved = row["run_context"]
    snapshot = saved["product_work_source"]
    selection = ProductWorkSelection.model_validate(saved["product_work_selection"])
    if (
        snapshot["actor_id"] != str(context.user.id)
        or snapshot["market_space_id"] != str(space_id)
        or snapshot["selection"] != selection.model_dump(mode="json")
        or snapshot["digest"] != saved["product_work_expected_digest"]
        or snapshot["digest"] != digest({k: v for k, v in snapshot.items() if k != "digest"})
    ):
        raise ProductWorkError("原运行绑定不可用于此工作范围")
    return selection


def product_work_attention(
    engine: Engine, context: AuthContext, space_id: UUID, scope: AttentionScope
) -> dict[str, Any]:
    r, f = tables.agent_runs, tables.findings
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        authorize(c, context, space_id, scope.product_line_id)
        filters = [
            r.c.tenant_id == context.tenant.id,
            r.c.market_space_id == space_id,
            r.c.requested_by_user_id == context.user.id,
            r.c.project_id.is_(None),
            r.c.scope_kind == "market_space",
            r.c.agent_key == "product_management_intelligence",
            r.c.context_version == RUN_VERSION,
        ]
        if not scope.all_lines:
            filters.append(
                r.c.run_context["product_work_selection"]["product_line_id"].as_string()
                == (str(scope.product_line_id) if scope.product_line_id else None)
            )
        queued = list(
            c.execute(
                select(
                    r,
                    f.c.id.label("finding_id"),
                    f.c.title.label("finding_title"),
                    f.c.summary.label("finding_summary"),
                    f.c.status.label("finding_status"),
                    f.c.proposed_payload.label("finding_payload"),
                )
                .join(f, and_(f.c.tenant_id == r.c.tenant_id, f.c.run_id == r.c.id))
                .where(
                    *filters,
                    f.c.project_id.is_(None),
                    f.c.scope_kind == "market_space",
                    f.c.agent_key == r.c.agent_key,
                    f.c.status.in_(["pending_review", "accepted"]),
                    f.c.proposed_payload["parent_finding_id"].as_string().is_(None),
                )
                .order_by(f.c.created_at.desc(), f.c.id.desc())
                .limit(101)
            ).mappings()
        )
        recent = list(
            c.execute(
                select(r).where(*filters).order_by(r.c.created_at.desc(), r.c.id.desc()).limit(10)
            ).mappings()
        )
        checked: dict[UUID, ProductWorkSelection | None] = {}
        unavailable = False

        def visible(row: Any) -> ProductWorkSelection | None:
            nonlocal unavailable
            if row["id"] not in checked:
                try:
                    selection = selection_for_summary(row, context, space_id)
                    authorize(c, context, space_id, selection.product_line_id)
                    readable(c, context, row["run_context"]["product_work_source"])
                    checked[row["id"]] = selection
                except (PermissionError, LookupError, ValueError, KeyError, TypeError):
                    checked[row["id"]] = None
                    unavailable = True
            return checked[row["id"]]

        candidates, runs = [], []
        for row in queued[:100]:
            selection = visible(row)
            if selection is not None:
                common = {
                    "run_id": row["id"],
                    "capability": selection.capability,
                    "product_line_id": selection.product_line_id,
                    "created_at": row["created_at"],
                }
                if row["finding_status"] == "pending_review" and selection.capability in CONFIG:
                    parent = {
                        "id": row["finding_id"],
                        "proposed_payload": row["finding_payload"],
                        "accepted_payload": None,
                        "status": "pending_review",
                    }
                    field = CONFIG[selection.capability][1]
                    for item in item_receipts(c, context, row, parent):
                        if item["status"] not in {"pending_review", "accepted"}:
                            continue
                        payload = (
                            item["accepted_payload"]["proposal"]["items"][0]
                            if item["accepted_payload"]
                            else item["proposed_payload"]["assessment"][field][0]
                        )
                        candidates.append(
                            {
                                **common,
                                **item,
                                "title": item_title(payload),
                                "summary": "逐条核对来源与草案，接受后独立应用",
                                "parent_finding_id": row["finding_id"],
                                "item_position": item["proposed_payload"]["position"],
                                "item": payload,
                            }
                        )
                else:
                    candidates.append(
                        {
                            **common,
                            "id": row["finding_id"],
                            "title": row["finding_title"],
                            "summary": row["finding_summary"],
                            "status": row["finding_status"],
                        }
                    )
        for row in recent:
            selection = visible(row)
            if selection is not None:
                runs.append(
                    {
                        "run_id": row["id"],
                        "status": row["status"],
                        "capability": selection.capability,
                        "product_line_id": selection.product_line_id,
                        "created_at": row["created_at"],
                        "missing": row["run_context"]
                        .get("product_work_result", {})
                        .get("missing", [])
                        if row["run_context"].get("product_work_result")
                        else [],
                    }
                )
        return _plain(
            {
                "candidates": candidates,
                "runs": runs,
                "limited": len(queued) > 100,
                "unavailable": unavailable,
            }
        )
