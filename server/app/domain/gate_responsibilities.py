"""Named reviewer obligations in unfinished Gate rounds for personnel handover."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Select, select

from app.db.schema import tables
from app.domain.product_workspace import _plain, digest


def statement(tenant: UUID, user: UUID) -> Select[Any]:
    s, r, g, p, stage = (
        tables.gate_signoffs,
        tables.gate_signoff_rounds,
        tables.gates,
        tables.projects,
        tables.stages,
    )
    return (
        select(
            s.c.id,
            s.c.slot,
            s.c.status,
            s.c.requirement,
            s.c.signed_by_user_id,
            s.c.signed_at,
            s.c.note,
            s.c.updated_at,
            r.c.id.label("round_id"),
            r.c.round_number,
            r.c.routing_snapshot,
            g.c.id.label("gate_id"),
            g.c.name.label("gate_name"),
            g.c.updated_at.label("gate_updated_at"),
            stage.c.name.label("stage_name"),
            p.c.id.label("project_id"),
            p.c.name.label("project_name"),
            p.c.current_stage_id,
            p.c.status.label("project_status"),
        )
        .select_from(s)
        .join(r, (r.c.tenant_id == s.c.tenant_id) & (r.c.id == s.c.round_id))
        .join(g, (g.c.tenant_id == s.c.tenant_id) & (g.c.id == s.c.gate_id))
        .join(p, (p.c.tenant_id == g.c.tenant_id) & (p.c.id == g.c.project_id))
        .join(stage, (stage.c.tenant_id == g.c.tenant_id) & (stage.c.id == g.c.stage_id))
        .where(
            s.c.tenant_id == tenant,
            r.c.status == "open",
            g.c.status == "reviewing",
            g.c.stage_id == p.c.current_stage_id,
            p.c.status.not_in(("completed", "archived")),
            s.c.requirement != "not_applicable",
            r.c.routing_snapshot["assignment"]["signers"][s.c.slot]["user_id"].as_string()
            == str(user),
        )
        .order_by(p.c.id, g.c.id, r.c.round_number, s.c.slot, s.c.id)
    )


def groups(c: Connection, tenant: UUID, source: UUID) -> list[dict[str, Any]]:
    slots = {"product": "产品", "engineering": "工程", "quality": "品质"}
    states = {
        "pending": "待签核",
        "approved": "已批准",
        "conditional": "有条件批准",
        "rejected": "已退回",
    }
    items = [
        {
            "id": str(row["id"]),
            "title": (
                f"{row['project_name']} · {row['stage_name']} · 第{row['round_number']}轮 "
                f"{slots[row['slot']]}签核（{states.get(row['status'], row['status'])}）"
            ),
            "href": (
                f"/projects?project={row['project_id']}&tab=gates&gate={row['gate_id']}"
                f"&gate_round={row['round_id']}&gate_signer={source}"
            ),
            "basis": digest(_plain(row)),
        }
        for row in c.execute(statement(tenant, source)).mappings()
    ]
    if not items:
        return []
    return [
        {
            "key": "gate_named_signers",
            "label": "未结束 Gate 轮次的具名签核责任",
            "count": len(items),
            "can_transfer": False,
            "items": items,
            "reasons": [
                "请在原 Gate 完成本轮，或由项目负责人说明原因、更换具备权限的项目成员并重开轮次；"
                "新轮次重新签核，原人员签名和意见保留，不能直接改写或代签",
                "本轮尚未结束时，已签署槽位仍可能因材料或前置意见变化而需重新核对，因此保留在清单中",
            ],
        }
    ]
