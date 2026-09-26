"""Creation-time freeze evidence and explicit adoption of a newer policy during reanalysis."""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError, _plain
from app.domain.project_write_lock import lock_project_write_scope


class Adoption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    old_policy_id: UUID
    new_policy_id: UUID
    window_key: str = Field(pattern=r"^(pvt|mp)$")
    reason: str = Field(min_length=1, max_length=4000)


def history(c: Connection, tenant: UUID, project: UUID, ecr_id: UUID) -> dict[str, Any]:
    o, a = tables.change_quiet_origins, tables.change_quiet_adoptions
    origin = (
        c.execute(
            select(o).where(
                o.c.tenant_id == tenant, o.c.project_id == project, o.c.ecr_id == ecr_id
            )
        )
        .mappings()
        .one_or_none()
    )
    adoptions = (
        c.execute(
            select(a)
            .where(a.c.tenant_id == tenant, a.c.project_id == project, a.c.ecr_id == ecr_id)
            .order_by(a.c.created_at, a.c.id)
        )
        .mappings()
        .all()
    )
    return {"origin": dict(origin) if origin else None, "adoptions": [dict(v) for v in adoptions]}


def resolve(requirements: list[dict[str, Any]], records: dict[str, Any]) -> list[dict[str, Any]]:
    origin = records["origin"]
    base = [
        *requirements,
        *(origin["requirements"] if origin else []),
        *(
            {
                "policy_id": str(a["new_policy_id"]),
                "policy_version": a["new_policy_version"],
                "window": a["new_window"],
            }
            for a in records["adoptions"]
        ),
    ]
    replacements = {(str(a["old_policy_id"]), a["window_key"]): a for a in records["adoptions"]}
    result = {}
    for entry in base:
        current = dict(entry)
        seen: set[str] = set()
        while (str(current["policy_id"]), current["window"]["key"]) in replacements:
            if current["policy_id"] in seen:
                raise ProductWorkError("政策承接记录不完整，请核对原审批历史")
            seen.add(current["policy_id"])
            adopted = replacements[(str(current["policy_id"]), current["window"]["key"])]
            current = {
                "policy_id": str(adopted["new_policy_id"]),
                "policy_version": adopted["new_policy_version"],
                "window": adopted["new_window"],
            }
        result[(str(current["policy_id"]), current["window"]["key"])] = current
    return list(result.values())


def adopt(
    engine: Engine, context: AuthContext, project: UUID, ecr_id: UUID, command: Adoption
) -> dict[str, Any]:
    from app.domain.change_quiet_periods import access, event, latest, state
    from app.domain.change_quiet_sources import assess, sources

    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_APPROVE)
        t = tables.change_quiet_adoptions
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
            if old["body"] != body or old["ecr_id"] != ecr_id:
                raise ProductWorkError("原政策承接请求已有不同内容")
            return _plain(dict(old))
        current = state(c, context.tenant.id, project, ecr_id)
        if (
            current["digest"] != command.expected_digest
            or current["ecr"]["status"] != "impact_analysis"
        ):
            raise ProductWorkError("须在重新分析阶段核对政策承接依据")
        prior = next(
            (
                v
                for v in current["required"]
                if v["policy_id"] == str(command.old_policy_id)
                and v["window"]["key"] == command.window_key
            ),
            None,
        )
        policy = latest(c, context.tenant.id, project)
        if (
            prior is None
            or policy is None
            or policy["id"] != command.new_policy_id
            or not policy["body"]["enabled"]
            or policy["version"] <= prior["policy_version"]
        ):
            raise ProductWorkError("须选择已发布启用且晚于原要求的最新政策")
        window = next(
            (w for w in policy["body"]["windows"] if w["key"] == command.window_key), None
        )
        if window is None or len(window["approver_ids"]) < len(prior["window"]["approver_ids"]):
            raise ProductWorkError("承接政策须保留同类窗口，且不减少原审批环节")
        forbidden = {
            current["ecr"]["requested_by_user_id"],
            current["ecr"]["analyzed_by_user_id"],
            *window["approver_ids"],
        }
        if str(context.user.id) in forbidden:
            raise ProductWorkError("须由独立于变更申请及新审批链的授权人员确认承接")
        actual = assess(
            c,
            context.tenant.id,
            project,
            policy["id"],
            command.window_key,
            sources(c, context.tenant.id, project),
        )
        if not actual["current"]:
            raise ProductWorkError(actual["reason"])
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    ecr_id=ecr_id,
                    old_policy_id=command.old_policy_id,
                    new_policy_id=command.new_policy_id,
                    new_policy_version=policy["version"],
                    window_key=command.window_key,
                    old_window=prior["window"],
                    new_window=window,
                    body=body,
                    analysis_snapshot=current["ecr"]["impact_analysis"],
                    created_by_user_id=context.user.id,
                    request_id=command.request_id,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        event(
            c, context.tenant.id, project, context.user.id, row["id"], "policy_adopted", dict(row)
        )
        return _plain(dict(row))
