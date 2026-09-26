"""Explicit, permission-checked work-card evidence for private conversations."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, select

from app.auth.roles import Action
from app.db.schema import tables
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import ProductWorkError, _plain, digest

Kind = Literal["task", "issue", "risk", "capa", "gate"]


class FocusRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Kind
    id: UUID
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


LABELS = {
    "title": "标题",
    "description": "内容",
    "status": "当前状态",
    "assignee_user_id": "任务负责人",
    "owner_user_id": "负责人",
    "verifier_user_id": "验证人",
    "expected_output": "预期输出",
    "completion_evidence_ref": "已登记完成依据",
    "blocked_reason": "阻塞原因",
    "priority": "优先级",
    "start_date": "开始日期",
    "due_date": "到期日期",
    "updated_at": "更新时间",
    "severity": "严重程度",
    "root_cause": "根因说明",
    "resolution": "解决措施",
    "closure_criteria": "关闭条件",
    "closure_evidence_ref": "关闭依据",
    "target_date": "目标日期",
    "likelihood": "可能性",
    "impact": "影响",
    "mitigation_plan": "缓解措施",
    "contingency_plan": "应急预案",
    "draft_state": "确认状态",
    "action_type": "措施类型",
    "completion_summary": "实际完成说明",
    "ncr_status": "NCR阶段",
    "nonconformity": "原不符合事项",
    "requirement_reference": "原要求",
    "quality_owner_user_id": "后续质量负责人",
    "name": "阶段签核名称",
    "round": "当前签核轮次",
    "signoffs": "本轮专业签核",
    "blockers": "当前阶段未满足项",
}
FIELDS = {
    "task": (
        "title description status assignee_user_id expected_output completion_evidence_ref "
        "blocked_reason priority start_date due_date updated_at"
    ),
    "issue": (
        "title description status owner_user_id verifier_user_id severity root_cause "
        "resolution closure_criteria closure_evidence_ref target_date updated_at"
    ),
    "risk": (
        "title description status owner_user_id likelihood impact mitigation_plan "
        "contingency_plan draft_state target_date updated_at"
    ),
    "capa": "description status owner_user_id action_type completion_summary due_date updated_at",
}


def snapshot(
    c: Connection, tenant_id: UUID, project_id: UUID, actor_id: UUID, kind: Kind, object_id: UUID
) -> dict[str, Any]:
    action = (
        Action.GATE_VIEW
        if kind == "gate"
        else Action.QUALITY_VIEW
        if kind == "capa"
        else Action.WORK_ITEM_VIEW
    )
    KnowledgeCorrectionService._authorize(c, tenant_id, actor_id, project_id, action)
    href = f"/projects?project={project_id}"
    if kind == "gate":
        from app.domain.gates import GateNotFoundError, GateService

        try:
            gate_row = GateService._gate_row(
                c, tenant_id=tenant_id, project_id=project_id, gate_id=object_id
            )
        except GateNotFoundError as error:
            raise ProductWorkError("原阶段签核当前不可用") from error
        gate = GateService._record_from_row(c, tenant_id=tenant_id, row=gate_row)
        values: dict[str, Any] = {
            "name": gate.name,
            "status": gate.status,
            "round": gate.round.round_number if gate.round else None,
            "signoffs": [asdict(s) for s in gate.round.signoffs] if gate.round else [],
            "blockers": list(gate.readiness.blockers),
        }
        basis: Any = gate.signing_basis
        title = gate.name
        href += "&tab=gates"
    else:
        table = {
            "task": tables.tasks,
            "issue": tables.issues,
            "risk": tables.risks,
            "capa": tables.capa_actions,
        }[kind]
        row = (
            c.execute(
                select(table).where(
                    table.c.tenant_id == tenant_id,
                    table.c.project_id == project_id,
                    table.c.id == object_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProductWorkError("原工作对象当前不可用")
        values = {key: row[key] for key in FIELDS[kind].split()}
        basis = str(row["updated_at"])
        title = str(row.get("title") or row.get("description") or "工作对象")[:256]
        if kind == "capa":
            ncr = (
                c.execute(
                    select(tables.nonconformance_reports).where(
                        tables.nonconformance_reports.c.tenant_id == tenant_id,
                        tables.nonconformance_reports.c.project_id == project_id,
                        tables.nonconformance_reports.c.id == row["ncr_id"],
                    )
                )
                .mappings()
                .one()
            )
            values.update(
                ncr_status=ncr["status"],
                nonconformity=ncr["nonconformity"],
                requirement_reference=ncr["requirement_reference"],
                quality_owner_user_id=ncr["owner_user_id"],
            )
            basis = [basis, str(ncr["updated_at"])]
            href += f"&tab=quality&ncr={row['ncr_id']}"
        else:
            href += f"&tab=work-items&entity_id={object_id}"
    for key, value in list(values.items()):
        if key.endswith("user_id") and value is not None:
            name = c.execute(
                select(tables.users.c.display_name).where(
                    tables.users.c.tenant_id == tenant_id, tables.users.c.id == value
                )
            ).scalar_one_or_none()
            values[key] = {"id": str(value), "name": name}
    raw = _plain(values)
    source_digest = digest(
        {"version": 1, "kind": kind, "id": str(object_id), "basis": basis, "fields": raw}
    )
    fields = []
    for key, value in raw.items():
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        fields.append(
            {
                "label": LABELS.get(key, key),
                "value": rendered[:2000],
                "truncated": len(rendered) > 2000,
            }
        )
    return {
        "kind": kind,
        "id": str(object_id),
        "digest": source_digest,
        "title": title,
        "href": href,
        "fields": fields,
    }


def current(
    c: Connection, tenant_id: UUID, project_id: UUID, actor_id: UUID, focus: dict[str, Any]
) -> dict[str, Any]:
    ref = FocusRef.model_validate({key: focus[key] for key in ("kind", "id", "digest")})
    value = snapshot(c, tenant_id, project_id, actor_id, ref.kind, ref.id)
    if value["digest"] != ref.digest:
        raise ProductWorkError("工作对象或签核依据已变化，请刷新资料并保存新消息")
    return value
