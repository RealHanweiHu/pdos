"""Current, permission-bound supply references for a human Issue work card."""

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_exceptions import MaterialExceptionService


def read_issue_material_closure(
    connection: Connection, context: AuthContext, project_id: UUID, issue_id: UUID
) -> dict[str, Any]:
    t = tables.material_exceptions
    entries = list(
        connection.execute(
            select(t.c.id)
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.issue_id == issue_id,
            )
            .order_by(t.c.id)
        ).scalars()
    )
    if not entries:
        return {"required": False, "ready": True, "items": []}
    # Each projection uses the supply service's consistent source snapshot and
    # current permissions. The close transaction rechecks all references under locks.
    service = MaterialExceptionService(connection.engine)
    items = []
    try:
        for exception_id in entries:
            detail = service.get(context, project_id, exception_id)
            items.append(
                {
                    "exception_id": str(exception_id),
                    "title": (
                        f"{detail['exception']['material_reference']} · {detail['issue']['title']}"
                    ),
                    "closure": detail["closure"],
                }
            )
    except KnowledgeAccessError:
        return {
            "required": True,
            "ready": False,
            "items": [],
            "access_denied": True,
            "reason": "当前无权读取供给恢复依据，请由有权限的具名验证人核对",
        }
    return {
        "required": True,
        "ready": all(item["closure"]["ready"] for item in items),
        "items": items,
    }
