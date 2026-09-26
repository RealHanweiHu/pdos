"""Shared collection path for explicit requests and authorized subscriptions."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import Connection, Engine, select

from app.ai.reach import ReachResult, ReachService
from app.ai.reach_transport import PublicReachTransport
from app.auth.repository import AuthContext
from app.auth.roles import Action, Role, is_allowed
from app.db.schema import tables
from app.domain.evidence import EvidenceService, EvidenceSnapshotRecord
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, _line, _space


def authorize_collection(
    connection: Connection, context: AuthContext, space_id: UUID, line_id: UUID | None
) -> None:
    current = (
        connection.execute(
            select(
                tables.users.c.is_active,
                tables.users.c.role,
                tables.tenants.c.status.label("tenant_status"),
            )
            .join(tables.tenants, tables.tenants.c.id == tables.users.c.tenant_id)
            .where(
                tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == context.user.id
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        current is None
        or not current["is_active"]
        or current["tenant_status"] != "active"
        or current["role"] != context.user.role.value
        or not is_allowed(Role(current["role"]), Action.EVIDENCE_CAPTURE)
    ):
        raise ProductWorkAccessError("账号、租户或岗位授权已变化，采集已停止")
    _space(connection, context, space_id, access="contributor", lock=True)
    _line(connection, context, space_id, line_id, access="contributor", writable=True)


def source_origin(connection: Connection, tenant_id: UUID, source_id: UUID) -> tuple[str, str, int]:
    source = (
        connection.execute(
            select(tables.research_sources).where(
                tables.research_sources.c.tenant_id == tenant_id,
                tables.research_sources.c.id == source_id,
                tables.research_sources.c.status == "active",
                tables.research_sources.c.source_type.in_(("web", "api")),
            )
        )
        .mappings()
        .one_or_none()
    )
    if source is None:
        raise ProductWorkError("请选择有效的公开网页或API来源")
    try:
        parsed = urlsplit(source["base_url"])
        return (
            parsed.scheme,
            (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip("."),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except (ValueError, UnicodeError) as error:
        raise ProductWorkError("来源地址无效，请修正来源配置") from error


@dataclass(frozen=True)
class CollectionResult:
    snapshot: EvidenceSnapshotRecord
    read: ReachResult


def collect_page(
    engine: Engine,
    context: AuthContext,
    *,
    space_id: UUID,
    line_id: UUID | None,
    source_id: UUID,
    url: str,
    freshness_days: int | None,
    guard: Callable[[Connection], None] | None = None,
    on_capture: Callable[[Connection, EvidenceSnapshotRecord], None] | None = None,
) -> CollectionResult:
    def authorize(connection: Connection) -> None:
        authorize_collection(connection, context, space_id, line_id)
        if guard is not None:
            guard(connection)

    def before_read() -> None:
        with engine.begin() as connection:
            authorize(connection)

    with engine.begin() as connection:
        authorize(connection)
        origin = source_origin(connection, context.tenant.id, source_id)
    evidence = EvidenceService(engine, authorize_write=authorize, on_capture=on_capture)
    result = ReachService(
        transport=PublicReachTransport(required_origin=origin),
        evidence=evidence,
        before_read=before_read,
    ).fetch(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        url=url,
        source_id=source_id,
        freshness_expires_at=datetime.now(UTC) + timedelta(days=freshness_days)
        if freshness_days
        else None,
    )
    return CollectionResult(
        evidence.get_snapshot(tenant_id=context.tenant.id, snapshot_id=result.snapshot_id), result
    )
