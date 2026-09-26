"""Versioned project quiet windows and named, sequential ECR exception decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, exists, func, select

from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain import change_quiet_sources as anchors
from app.domain.findings import FindingService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Window(Strict):
    key: Literal["pvt", "mp"]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    anchor: anchors.Anchor | None = None
    planning_basis: str = Field(min_length=1, max_length=4000)
    approver_ids: list[UUID] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid(self) -> Window:
        if self.ends_at <= self.starts_at or len(set(self.approver_ids)) != len(self.approver_ids):
            raise ValueError("冻结结束须晚于开始，具名审批人不得重复")
        return self


class Policy(Strict):
    request_id: UUID
    expected_version: int = Field(ge=0)
    enabled: bool
    reason: str = Field(min_length=1, max_length=4000)
    windows: list[Window] = Field(max_length=2)

    @model_validator(mode="after")
    def valid(self) -> Policy:
        if (
            self.enabled
            and not self.windows
            or len({w.key for w in self.windows}) != len(self.windows)
        ):
            raise ValueError("启用政策须有冻结窗口，PVT/MP 各保留一个窗口")
        if self.enabled and any(w.anchor is None for w in self.windows):
            raise ValueError("启用政策须为每个窗口选择实际正式基线节点")
        return self


class ExceptionRequest(Strict):
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_id: UUID
    window_key: Literal["pvt", "mp"]
    reason: str = Field(min_length=1, max_length=4000)
    risk_and_controls: str = Field(min_length=1, max_length=10000)


class Vote(Strict):
    request_id: UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["approved", "rejected"]
    note: str = Field(min_length=1, max_length=4000)


def access(c: Connection, tenant: UUID, project: UUID, actor: UUID, action: Action) -> None:
    FindingService._authorize_user(
        c, tenant_id=tenant, project_id=project, user_id=actor, action=action
    )


def people(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, Any]]:
    u, m = tables.users, tables.project_members
    values = c.execute(
        select(u.c.id, u.c.display_name.label("name"), u.c.role)
        .where(
            u.c.tenant_id == tenant,
            u.c.is_active.is_(True),
            (u.c.role.in_(["owner", "admin"]))
            | exists().where(
                m.c.tenant_id == tenant, m.c.project_id == project, m.c.user_id == u.c.id
            ),
        )
        .order_by(u.c.display_name, u.c.id)
    ).mappings()
    return [_plain(dict(v)) for v in values if is_allowed(Role(v["role"]), Action.CHANGE_APPROVE)]


def latest(c: Connection, tenant: UUID, project: UUID) -> Any:
    t = tables.change_quiet_policies
    return (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project)
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def active(c: Connection, tenant: UUID, project: UUID) -> list[dict[str, Any]]:
    policy = latest(c, tenant, project)
    if policy is None or not policy["body"]["enabled"]:
        return []
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    return [
        {"policy_id": str(policy["id"]), "policy_version": policy["version"], "window": w}
        for w in policy["body"]["windows"]
        if datetime.fromisoformat(w["starts_at"]) <= now < datetime.fromisoformat(w["ends_at"])
    ]


def freeze(
    c: Connection, tenant: UUID, project: UUID, analysis: dict[str, Any], *, ecr_id: UUID
) -> dict[str, Any]:
    # Derive from persisted business evidence, including creation and explicit policy adoptions.
    return {
        **analysis,
        "quiet_period": required(c, tenant, project, ecr_row(c, tenant, project, ecr_id)),
    }


def required(c: Connection, tenant: UUID, project: UUID, ecr: Any) -> list[dict[str, Any]]:
    frozen = (ecr["impact_analysis"] or {}).get("quiet_period", [])
    requirements = {(v["policy_id"], v["window"]["key"]): v for v in frozen}
    if ecr["status"] not in {"approved", "rejected", "cancelled"}:
        requirements.update(
            {(v["policy_id"], v["window"]["key"]): v for v in active(c, tenant, project)}
        )
    r, p = tables.change_quiet_requests, tables.change_quiet_policies
    saved = c.execute(
        select(r.c.policy_id, r.c.window, p.c.version)
        .join(p, p.c.id == r.c.policy_id)
        .where(
            r.c.tenant_id == tenant,
            r.c.project_id == project,
            r.c.ecr_id == ecr["id"],
            r.c.analysis_snapshot == ecr["impact_analysis"],
        )
    ).mappings()
    for row in saved:
        requirements[(str(row["policy_id"]), row["window"]["key"])] = {
            "policy_id": str(row["policy_id"]),
            "policy_version": row["version"],
            "window": row["window"],
        }
    from app.domain.change_quiet_origins import history, resolve

    return resolve([dict(v) for v in requirements.values()], history(c, tenant, project, ecr["id"]))


def ecr_row(c: Connection, tenant: UUID, project: UUID, id: UUID) -> Any:
    t = tables.engineering_change_requests
    row = (
        c.execute(select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkError("原 ECR 不可用")
    return row


def requests(c: Connection, tenant: UUID, project: UUID, ecr_id: UUID) -> list[dict[str, Any]]:
    t, v = tables.change_quiet_requests, tables.change_quiet_votes
    entries = (
        c.execute(
            select(t)
            .where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.ecr_id == ecr_id)
            .order_by(t.c.created_at, t.c.id)
        )
        .mappings()
        .all()
    )
    votes = (
        c.execute(
            select(v)
            .where(
                v.c.tenant_id == tenant,
                v.c.project_id == project,
                v.c.exception_id.in_([r["id"] for r in entries]),
            )
            .order_by(v.c.chain_revision, v.c.step)
        )
        .mappings()
        .all()
        if entries
        else []
    )
    replacement = tables.change_quiet_replacements
    replacements = (
        c.execute(
            select(replacement)
            .where(
                replacement.c.tenant_id == tenant,
                replacement.c.project_id == project,
                replacement.c.exception_id.in_([r["id"] for r in entries]),
            )
            .order_by(replacement.c.revision)
        )
        .mappings()
        .all()
        if entries
        else []
    )
    result = []
    for entry in entries:
        history = [dict(r) for r in replacements if r["exception_id"] == entry["id"]]
        revision = history[-1]["revision"] if history else 0
        chain = history[-1]["body"]["approver_ids"] if history else entry["window"]["approver_ids"]
        all_votes = [dict(v) for v in votes if v["exception_id"] == entry["id"]]
        result.append(
            {
                **dict(entry),
                "chain_revision": revision,
                "approver_ids": chain,
                "chain_history": history,
                "vote_history": all_votes,
                "votes": [v for v in all_votes if v["chain_revision"] == revision],
            }
        )
    return result


def state(c: Connection, tenant: UUID, project: UUID, ecr_id: UUID) -> dict[str, Any]:
    ecr = ecr_row(c, tenant, project, ecr_id)
    values = requests(c, tenant, project, ecr_id)
    needed = required(c, tenant, project, ecr)
    eligible = {p["id"] for p in people(c, tenant, project)}
    current_sources, _ = anchors.available(c, tenant, project)
    for item in needed:
        item["source"] = anchors.assess(
            c, tenant, project, UUID(item["policy_id"]), item["window"]["key"], current_sources
        )
    for value in values:
        value["current"] = value["analysis_snapshot"] == _plain(ecr["impact_analysis"])
        value["source"] = anchors.assess(
            c, tenant, project, value["policy_id"], value["window_key"], current_sources
        )
        value["status"] = (
            "rejected"
            if any(v["outcome"] == "rejected" for v in value["votes"])
            else "approved"
            if len(value["votes"]) == len(value["approver_ids"])
            else "pending"
        )
        chain = value["approver_ids"]
        value["next_approver_id"] = (
            chain[len(value["votes"])] if value["status"] == "pending" else None
        )
        value["ineligible_approver_ids"] = [
            id
            for id in chain
            if id not in eligible
            or id
            in {
                str(ecr["requested_by_user_id"]),
                str(ecr["analyzed_by_user_id"]),
                str(value["created_by_user_id"]),
            }
        ]
    from app.domain.change_quiet_origins import history

    policy = latest(c, tenant, project)
    policy_sources = (
        {
            w["key"]: anchors.assess(c, tenant, project, policy["id"], w["key"], current_sources)
            for w in policy["body"]["windows"]
        }
        if policy
        else {}
    )
    basis = {
        "ecr": _plain(dict(ecr)),
        "required": needed,
        "requests": values,
        "latest_policy": policy,
        "latest_policy_sources": policy_sources,
        **history(c, tenant, project, ecr_id),
    }
    return {**basis, "digest": digest(_plain(basis))}


def event(
    c: Connection,
    tenant: UUID,
    project: UUID,
    actor: UUID,
    id: UUID,
    kind: str,
    detail: dict[str, Any],
) -> None:
    EventAuditWriter(c, tenant_id=tenant, project_id=project, actor_user_id=actor).record(
        EventDraft(
            event_id=f"change-quiet:{id}:{kind}",
            event_type="CHANGE_QUIET_PERIOD_RECORDED",
            source="change_governance_service",
            entity_id=id,
            payload={"action": kind},
            occurred_at=c.execute(select(func.clock_timestamp())).scalar_one(),
        ),
        AuditDraft(action="change_quiet." + kind, after_snapshot=_plain(detail)),
    )


def read_policy(
    engine: Engine, context: AuthContext, project: UUID, before_version: int | None = None
) -> dict[str, Any]:
    with engine.connect() as c:
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_VIEW)
        t = tables.change_quiet_policies
        query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
        if before_version is not None:
            query = query.where(t.c.version < before_version)
        history = c.execute(query.order_by(t.c.version.desc()).limit(21)).mappings().all()
        current = latest(c, context.tenant.id, project)
        current_sources, source_error = anchors.available(c, context.tenant.id, project)
        source_status = {
            str(p["id"]): {
                w["key"]: anchors.assess(
                    c, context.tenant.id, project, p["id"], w["key"], current_sources
                )
                for w in p["body"]["windows"]
            }
            for p in history[:20]
        }
        return _plain(
            {
                "current": dict(current) if current else None,
                "source_status": source_status,
                "source_error": source_error,
                "history": [dict(v) for v in history[:20]],
                "next_before_version": history[19]["version"] if len(history) > 20 else None,
                "people": people(c, context.tenant.id, project),
                "active": active(c, context.tenant.id, project),
                "can_manage": is_allowed(context.user.role, Action.CHANGE_APPROVE),
            }
        )


def save_policy(
    engine: Engine, context: AuthContext, project: UUID, command: Policy
) -> dict[str, Any]:
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_APPROVE)
        t = tables.change_quiet_policies
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
            if old["body"] != body:
                raise ProductWorkError("原政策请求已保存其他内容")
            return _plain(dict(old))
        current = latest(c, context.tenant.id, project)
        if (current["version"] if current else 0) != command.expected_version:
            raise ProductWorkError("政策版本已变化，请核对后修订")
        eligible = {p["id"] for p in people(c, context.tenant.id, project)}
        if any(str(id) not in eligible for w in command.windows for id in w.approver_ids):
            raise ProductWorkError("升级审批人须具备当前项目审批资格")
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    version=command.expected_version + 1,
                    body=body,
                    created_by_user_id=context.user.id,
                    request_id=command.request_id,
                )
                .returning(t)
            )
            .mappings()
            .one()
        )
        current_sources = (
            anchors.sources(c, context.tenant.id, project)
            if command.enabled and any(w.anchor for w in command.windows)
            else []
        )
        for window in command.windows:
            if command.enabled and window.anchor:
                value = anchors.resolve(current_sources, window.anchor)
                anchors.bind(
                    c, context.tenant.id, project, row["id"], window.key, window.anchor, value
                )
        event(
            c, context.tenant.id, project, context.user.id, row["id"], "policy_published", dict(row)
        )
        return _plain(dict(row))


def read(engine: Engine, context: AuthContext, project: UUID, ecr_id: UUID) -> dict[str, Any]:
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_VIEW)
        return _plain(
            {
                **state(c, context.tenant.id, project, ecr_id),
                "people": people(c, context.tenant.id, project),
                "actor_id": str(context.user.id),
                "can_request": is_allowed(context.user.role, Action.CHANGE_EDIT),
                "can_decide": is_allowed(context.user.role, Action.CHANGE_APPROVE),
            }
        )


def request_exception(
    engine: Engine, context: AuthContext, project: UUID, ecr_id: UUID, command: ExceptionRequest
) -> dict[str, Any]:
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_EDIT)
        t = tables.change_quiet_requests
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
                raise ProductWorkError("原例外请求已保存其他内容")
            return _plain(dict(old))
        current = state(c, context.tenant.id, project, ecr_id)
        if current["digest"] != command.expected_digest or current["ecr"]["status"] != "approval":
            raise ProductWorkError("待审批分析或冻结要求已变化，请刷新")
        item = next(
            (
                r
                for r in current["required"]
                if r["policy_id"] == str(command.policy_id)
                and r["window"]["key"] == command.window_key
            ),
            None,
        )
        if item is None:
            raise ProductWorkError("本次没有该冻结窗口的升级要求")
        if not item["source"]["current"]:
            raise ProductWorkError(item["source"]["reason"])
        if any(
            r["policy_id"] == command.policy_id
            and r["window"]["key"] == command.window_key
            and r["current"]
            for r in current["requests"]
        ):
            raise ProductWorkError("本版分析已有升级请求；被退回后须重新分析")
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    ecr_id=ecr_id,
                    policy_id=command.policy_id,
                    window_key=command.window_key,
                    window=item["window"],
                    analysis_snapshot=current["ecr"]["impact_analysis"],
                    analysis_digest=digest(current["ecr"]["impact_analysis"]),
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
            "exception_requested",
            dict(row),
        )
        return _plain(dict(row))


def decide(
    engine: Engine,
    context: AuthContext,
    project: UUID,
    ecr_id: UUID,
    exception_id: UUID,
    command: Vote,
) -> dict[str, Any]:
    with engine.begin() as c:
        if not lock_project_write_scope(c, tenant_id=context.tenant.id, project_id=project):
            raise ProductWorkError("项目不可用")
        access(c, context.tenant.id, project, context.user.id, Action.CHANGE_APPROVE)
        t = tables.change_quiet_votes
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
                raise ProductWorkError("原审批请求已有不同内容")
            return _plain(dict(old))
        current = state(c, context.tenant.id, project, ecr_id)
        entry = next((r for r in current["requests"] if r["id"] == exception_id), None)
        if (
            current["digest"] != command.expected_digest
            or current["ecr"]["status"] != "approval"
            or entry is None
            or not entry["current"]
        ):
            raise ProductWorkError("升级请求或原分析已变化，请刷新")
        if not entry["source"]["current"]:
            raise ProductWorkError(entry["source"]["reason"])
        if entry["next_approver_id"] != str(context.user.id) or entry["ineligible_approver_ids"]:
            raise ProductWorkError(
                "须由当前顺序的具名独立审批人办理；缺少资格时先修订安排并重新分析"
            )
        row = (
            c.execute(
                t.insert()
                .values(
                    id=uuid4(),
                    tenant_id=context.tenant.id,
                    project_id=project,
                    exception_id=exception_id,
                    step=len(entry["votes"]) + 1,
                    chain_revision=entry["chain_revision"],
                    outcome=command.outcome,
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
            "exception_" + command.outcome,
            dict(row),
        )
        return _plain(dict(row))


def require_approval(c: Connection, tenant: UUID, project: UUID, ecr_id: UUID) -> None:
    current = state(c, tenant, project, ecr_id)
    for item in current["required"]:
        if not item["source"]["current"]:
            raise ProductWorkError(item["source"]["reason"])
        ready = any(
            str(r["policy_id"]) == item["policy_id"]
            and r["window"] == item["window"]
            and r["current"]
            and r["status"] == "approved"
            and not r["ineligible_approver_ids"]
            for r in current["requests"]
        )
        if not ready:
            raise ProductWorkError("冻结期变更须先完成全部具名升级审批，再独立批准原 ECR")
