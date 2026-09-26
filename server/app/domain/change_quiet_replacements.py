"""Explicit independent replacements restart the named chain; past votes remain history."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain
from app.domain.project_write_lock import lock_project_write_scope


class Replacement(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    approver_ids: list[UUID] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def unique(self) -> "Replacement":
        if len(set(self.approver_ids)) != len(self.approver_ids):
            raise ValueError("具名审批人不得重复")
        return self


def replace(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    ecr_id: UUID,
    exception_id: UUID,
    command: Replacement,
) -> dict[str, Any]:
    from app.domain.change_quiet_periods import access, event, people, state

    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_APPROVE)
        t = tables.change_quiet_replacements
        body = command.model_dump(mode="json")
        old = (
            c.execute(
                select(t).where(
                    t.c.tenant_id == context.tenant.id,
                    t.c.project_id == project,
                    t.c.created_by_user_id == context.user.id,
                    t.c.request_id == command.request_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if old is not None:
            if old["body"] != body or old["exception_id"] != exception_id:
                raise ProductWorkError("原替换请求已有不同内容")
            return _plain(dict(old))
        current = state(c, context.tenant.id, project, ecr_id)
        entry = next((r for r in current["requests"] if r["id"] == exception_id), None)
        if (
            current["digest"] != command.expected_digest
            or current["ecr"]["status"] != "approval"
            or entry is None
            or not entry["current"]
        ):
            raise ProductWorkError("原请求或分析已变化，请重新核对")
        if not entry["source"]["current"]:
            raise ProductWorkError(entry["source"]["reason"])
        if entry["status"] == "rejected":
            raise ProductWorkError("被退回的例外须先重新分析，不能通过换人继续批准")
        disallowed = {
            current["ecr"]["requested_by_user_id"],
            current["ecr"]["analyzed_by_user_id"],
            str(entry["created_by_user_id"]),
        }
        new_chain = [str(id) for id in command.approver_ids]
        eligible = {p["id"] for p in people(c, context.tenant.id, project)}
        if str(context.user.id) in disallowed or str(context.user.id) in new_chain:
            raise ProductWorkError("须由独立于申请、分析和新审批链的授权人员确认替换")
        if len(new_chain) != len(entry["approver_ids"]) or new_chain == entry["approver_ids"]:
            raise ProductWorkError("替换须保留审批环节数量，并明确实际变更人员")
        if any(id not in eligible or id in disallowed for id in new_chain):
            raise ProductWorkError("替代审批人须具有当前项目审批资格并保持独立")
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    exception_id=exception_id,
                    revision=entry["chain_revision"] + 1,
                    body=body,
                    created_by_user_id=context.user.id,
                    request_id=command.request_id,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        event(
            c,
            context.tenant.id,
            project,
            context.user.id,
            row["id"],
            "approvers_replaced",
            dict(row),
        )
        return _plain(dict(row))
