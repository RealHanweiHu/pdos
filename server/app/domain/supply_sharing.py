"""Two-party sharing of exact normalized supply rows; grants do not reserve stock."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import Connection, Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.common_objects import Contract, Digest, Quantity, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.material_supply_pools import lock_pools
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import _plain, digest


class ShareOffer(Contract):
    request_id: UUID
    expected_digest: Digest
    recipient_project_id: UUID
    recipient_user_id: UUID
    quantity_limit: Quantity = Field(ge=0)
    expires_at: AwareDatetime
    reason: Text


class ShareDecision(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    outcome: Literal["accepted", "rejected", "revoked"]
    reason: Text


def active_grant_query(tenant: UUID, recipient: UUID, now: datetime | None = None) -> Any:
    g, a = tables.supply_share_grants, tables.supply_share_actions
    newer = a.alias("newer_supply_share_action")
    return (
        select(g)
        .join(a, (a.c.tenant_id == g.c.tenant_id) & (a.c.grant_id == g.c.id))
        .where(
            g.c.tenant_id == tenant,
            g.c.recipient_project_id == recipient,
            g.c.expires_at > (now or datetime.now(UTC)),
            a.c.outcome == "accepted",
            ~select(newer.c.id)
            .where(
                newer.c.tenant_id == a.c.tenant_id,
                newer.c.grant_id == a.c.grant_id,
                newer.c.version > a.c.version,
            )
            .exists(),
        )
    )


def visible_source_clause(tenant: UUID, recipient: UUID) -> Any:
    grants = active_grant_query(tenant, recipient).subquery()
    return or_(
        tables.supply_snapshots.c.project_id == recipient,
        tables.supply_snapshots.c.id.in_(select(grants.c.supply_snapshot_id)),
    )


def shared_source(source: dict[str, Any], grant: dict[str, Any]) -> dict[str, Any]:
    # No whole-file access or supplier attribution/evidence is implied by row sharing.
    return {
        **source,
        "document_id": None,
        "source_grant_id": str(grant["id"]),
        "share_expires_at": grant["expires_at"],
        "share_quantity_limit": grant["quantity_limit"],
    }


def _manage(c: Connection, context: AuthContext, project: UUID) -> None:
    BuildMaterialService._authorize(c, context, project, write=True)
    KnowledgeCorrectionService._authorize(
        c, context.tenant.id, context.user.id, project, Action.GATE_MANAGE
    )


def _error(message: str) -> Exception:
    from app.domain.material_allocations import MaterialAllocationError

    return MaterialAllocationError(message)


def _latest(c: Connection, tenant: UUID, identity: UUID) -> dict[str, Any] | None:
    a = tables.supply_share_actions
    row = (
        c.execute(
            select(a)
            .where(a.c.tenant_id == tenant, a.c.grant_id == identity)
            .order_by(a.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _lock_projects(c: Connection, tenant: UUID, ids: list[UUID]) -> None:
    for identity in sorted(set(ids)):
        NpiExecutionService._project(c, tenant_id=tenant, project_id=identity, lock=True)


def _current_source(
    c: Connection, tenant: UUID, project: UUID, identity: UUID, lock: bool = False
) -> dict[str, Any]:
    from app.domain.material_allocations import _key, _pools, _source_query

    s = tables.supply_snapshots
    row = (
        c.execute(_source_query(tenant).where(s.c.project_id == project, s.c.id == identity))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _error("来源项目中没有该供给快照")
    if lock:
        lock_pools(c, tenant, [_key(row)])
    pool = _pools(c, tenant, project, [_key(row)])[_key(row)]
    if not pool["source"] or pool["source"]["id"] != str(identity):
        raise _error("共享须从来源项目当前的原供给版本发起")
    source = _plain(dict(row))
    source["document_id"] = None
    return {"source": source, "digest": digest(source), "state": pool["state"]}


class SupplySharingService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def options(self, context: AuthContext, project_id: UUID, source_id: UUID) -> dict[str, Any]:
        from app.domain.material_exposure import _project_ids

        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _manage(c, context, project_id)
            source = _current_source(c, context.tenant.id, project_id, source_id)
            p, u, m = tables.projects, tables.users, tables.project_members
            projects = [
                _plain(dict(row))
                for row in c.execute(
                    select(p.c.id, p.c.name)
                    .where(
                        p.c.tenant_id == context.tenant.id,
                        p.c.id != project_id,
                        p.c.id.in_(_project_ids(c, context)),
                    )
                    .order_by(p.c.name)
                ).mappings()
            ]
            people = [
                _plain(dict(row))
                for row in c.execute(
                    select(u.c.id, u.c.display_name, u.c.role)
                    .where(
                        u.c.tenant_id == context.tenant.id,
                        u.c.is_active.is_(True),
                        u.c.id != context.user.id,
                        u.c.role.in_(("owner", "admin", "project_manager")),
                    )
                    .order_by(u.c.display_name)
                ).mappings()
            ]
            members = [
                (str(row.project_id), str(row.user_id))
                for row in c.execute(
                    select(m.c.project_id, m.c.user_id).where(
                        m.c.tenant_id == context.tenant.id,
                        m.c.project_id.in_([UUID(row["id"]) for row in projects]),
                    )
                )
            ]
            return {
                **source,
                "projects": [
                    {
                        **project,
                        "people": [
                            person
                            for person in people
                            if person["role"] in {"owner", "admin"}
                            or (project["id"], person["id"]) in members
                        ],
                    }
                    for project in projects
                ],
            }

    def offer(
        self, context: AuthContext, project_id: UUID, source_id: UUID, command: ShareOffer
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project_id),
                "source": str(source_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            _manage(c, context, project_id)
            # Destination choice is restricted to projects the offering actor may currently read.
            BuildMaterialService._authorize(c, context, command.recipient_project_id)
            _lock_projects(c, context.tenant.id, [project_id, command.recipient_project_id])
            g = tables.supply_share_grants
            prior = (
                c.execute(
                    select(g).where(
                        g.c.tenant_id == context.tenant.id,
                        g.c.created_by_user_id == context.user.id,
                        g.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise _error("原共享请求已用于其他内容")
                return _plain(dict(prior))
            if (
                project_id == command.recipient_project_id
                or context.user.id == command.recipient_user_id
            ):
                raise _error("共享须由另一项目的另一位具名负责人确认")
            KnowledgeCorrectionService._authorize(
                c,
                context.tenant.id,
                command.recipient_user_id,
                command.recipient_project_id,
                Action.GATE_MANAGE,
            )
            observed = _current_source(c, context.tenant.id, project_id, source_id, lock=True)
            if observed["digest"] != command.expected_digest or command.expires_at <= datetime.now(
                UTC
            ):
                raise _error("供给原依据已变化或共享期限已过，请刷新核对")
            quantity = observed["source"]["quantity"]
            if (quantity is None and command.quantity_limit != 0) or (
                quantity is not None and command.quantity_limit > Decimal(quantity)
            ):
                raise _error("共享上限须不超过该来源已知数量；未知数量仅可授权0，即只读共享")
            pending = c.execute(
                select(g).where(
                    g.c.tenant_id == context.tenant.id,
                    g.c.supply_snapshot_id == source_id,
                    g.c.recipient_project_id == command.recipient_project_id,
                    g.c.expires_at > datetime.now(UTC),
                )
            ).mappings()
            for row in pending:
                latest = _latest(c, context.tenant.id, row["id"])
                if latest is None or latest["outcome"] == "accepted":
                    raise _error("该原来源已有待确认或有效共享，请先完成或解除原共享")
            projects = {
                str(row.id): row.name
                for row in c.execute(
                    select(tables.projects.c.id, tables.projects.c.name).where(
                        tables.projects.c.tenant_id == context.tenant.id,
                        tables.projects.c.id.in_([project_id, command.recipient_project_id]),
                    )
                )
            }
            snapshot = {
                **observed,
                "source_project_name": projects[str(project_id)],
                "recipient_project_name": projects[str(command.recipient_project_id)],
                "scope": "normalized_supply_row_read_and_allocate",
                "whole_file_access": False,
            }
            saved = (
                c.execute(
                    g.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        source_project_id=project_id,
                        recipient_project_id=command.recipient_project_id,
                        recipient_user_id=command.recipient_user_id,
                        supply_snapshot_id=source_id,
                        quantity_limit=command.quantity_limit,
                        expires_at=command.expires_at,
                        snapshot=snapshot,
                        reason=command.reason,
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(g)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=saved["id"],
                record_type="supply_share",
                action="offered",
                before=None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))

    def list(
        self, context: AuthContext, project_id: UUID, grant_id: UUID | None = None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            BuildMaterialService._authorize(c, context, project_id)
            g = tables.supply_share_grants
            query = select(g).where(
                g.c.tenant_id == context.tenant.id,
                or_(g.c.source_project_id == project_id, g.c.recipient_project_id == project_id),
            )
            if grant_id:
                query = query.where(g.c.id == grant_id)
            rows = list(
                c.execute(query.order_by(g.c.created_at.desc(), g.c.id).limit(51)).mappings()
            )
            try:
                _manage(c, context, project_id)
                can_manage = True
            except KnowledgeAccessError:
                can_manage = False
            items = []
            for row in rows[:50]:
                latest = _latest(c, context.tenant.id, row["id"])
                from app.domain.material_allocations import MaterialAllocationError

                try:
                    current_source = _current_source(
                        c, context.tenant.id, row["source_project_id"], row["supply_snapshot_id"]
                    )
                    source_current = current_source["digest"] == row["snapshot"]["digest"]
                    source_state = current_source["state"]
                except MaterialAllocationError:
                    source_current, source_state = False, "source_changed"
                actions = [
                    _plain(dict(action))
                    for action in c.execute(
                        select(tables.supply_share_actions)
                        .where(
                            tables.supply_share_actions.c.tenant_id == context.tenant.id,
                            tables.supply_share_actions.c.grant_id == row["id"],
                        )
                        .order_by(tables.supply_share_actions.c.version)
                    ).mappings()
                ]

                items.append(
                    {
                        **_plain(dict(row)),
                        "source_current": source_current,
                        "source_state": source_state,
                        "actions": actions,
                        "latest_action": _plain(latest) if latest else None,
                        "expired": row["expires_at"] <= datetime.now(UTC),
                        "can_accept": can_manage
                        and row["recipient_project_id"] == project_id
                        and row["recipient_user_id"] == context.user.id,
                        "can_revoke": can_manage,
                    }
                )
            from app.domain.input_wait_responsibilities import people

            named = [
                identity
                for item in items
                for identity in (
                    item["created_by_user_id"],
                    item["recipient_user_id"],
                    *(action["created_by_user_id"] for action in item["actions"]),
                )
            ]
            return {
                "items": items,
                "has_more": len(rows) > 50,
                "project_id": str(project_id),
                "actor_id": str(context.user.id),
                "people": people(c, context.tenant.id, named),
            }

    def decide(
        self, context: AuthContext, project_id: UUID, grant_id: UUID, command: ShareDecision
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project_id),
                "grant": str(grant_id),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            _manage(c, context, project_id)
            g, a = tables.supply_share_grants, tables.supply_share_actions
            grant = (
                c.execute(
                    select(g).where(
                        g.c.tenant_id == context.tenant.id,
                        g.c.id == grant_id,
                        or_(
                            g.c.source_project_id == project_id,
                            g.c.recipient_project_id == project_id,
                        ),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if grant is None:
                raise _error("当前项目没有该共享")
            _lock_projects(
                c, context.tenant.id, [grant["source_project_id"], grant["recipient_project_id"]]
            )
            source = grant["snapshot"]["source"]
            lock_pools(
                c,
                context.tenant.id,
                [(source["source_system"], source["external_pool_id"], source["external_item_id"])],
            )
            prior = (
                c.execute(
                    select(a).where(
                        a.c.tenant_id == context.tenant.id,
                        a.c.created_by_user_id == context.user.id,
                        a.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["request_digest"] != signature:
                    raise _error("原请求已用于其他共享办理")
                return _plain(dict(prior))
            latest = _latest(c, context.tenant.id, grant_id)
            if command.expected_version != (latest["version"] if latest else 0) or (
                latest and latest["outcome"] in {"rejected", "revoked"}
            ):
                raise _error("共享状态已有变化或已经终止，请刷新")
            if command.outcome in {"accepted", "rejected"}:
                if (
                    latest
                    or project_id != grant["recipient_project_id"]
                    or context.user.id != grant["recipient_user_id"]
                    or context.user.id == grant["created_by_user_id"]
                ):
                    raise _error("仅原指定的另一位接收负责人可首次确认或拒绝共享")
                if command.outcome == "accepted":
                    current = _current_source(
                        c,
                        context.tenant.id,
                        grant["source_project_id"],
                        grant["supply_snapshot_id"],
                    )
                    if current["digest"] != grant["snapshot"]["digest"] or grant[
                        "expires_at"
                    ] <= datetime.now(UTC):
                        raise _error("原共享依据已变化或已过期，请由来源项目重新发起")
            saved = (
                c.execute(
                    a.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        grant_id=grant_id,
                        version=command.expected_version + 1,
                        outcome=command.outcome,
                        reason=command.reason,
                        snapshot={
                            "grant_id": str(grant_id),
                            "source_digest": grant["snapshot"]["digest"],
                            "previous_action_id": str(latest["id"]) if latest else None,
                        },
                        created_by_user_id=context.user.id,
                        request_id=command.request_id,
                        request_digest=signature,
                    )
                    .returning(a)
                )
                .mappings()
                .one()
            )
            NpiExecutionService._record_change(
                c,
                tenant_id=context.tenant.id,
                project_id=project_id,
                actor_user_id=context.user.id,
                record_id=grant_id,
                record_type="supply_share",
                action=command.outcome,
                before=_plain(latest) if latest else None,
                after=_plain(dict(saved)),
            )
            return _plain(dict(saved))
