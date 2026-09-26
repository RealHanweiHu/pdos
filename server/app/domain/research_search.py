"""Scope-bound search observations, with durable request identity and honest outcomes."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.ai.reach import ReachDeniedError, ReachFetchError, ReachSearchUnavailableError
from app.ai.research_search import SearxSearchProvider
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.product_workspace import (
    Input,
    ProductWorkAccessError,
    ProductWorkError,
    _emit,
    _line,
    _line_filter,
    _plain,
    _role,
    _space,
    digest,
)


class ResearchSearchRequest(Input):
    request_id: UUID
    product_line_id: UUID | None = None
    query: str = Field(min_length=1, max_length=512)
    language: str = Field(default="auto", min_length=2, max_length=16, pattern=r"^[a-zA-Z-]+$")
    time_range: Literal["day", "month", "year"] | None = None
    result_limit: int = Field(default=5, ge=1, le=10)


def _access(
    connection: Connection,
    context: AuthContext,
    space_id: UUID,
    line_id: UUID | None,
    *,
    lock: bool = False,
) -> None:
    _role(context, Action.EVIDENCE_VIEW)
    current = (
        connection.execute(
            select(tables.users.c.role, tables.users.c.is_active).where(
                tables.users.c.tenant_id == context.tenant.id, tables.users.c.id == context.user.id
            )
        )
        .mappings()
        .one_or_none()
    )
    if current is None or not current["is_active"] or current["role"] != context.user.role.value:
        raise ProductWorkAccessError("当前岗位授权已变化，请重新登录")
    _space(connection, context, space_id, lock=lock)
    _line(connection, context, space_id, line_id)


class ResearchSearchService:
    def __init__(self, engine: Engine, *, endpoint: str | None) -> None:
        self.engine = engine
        self.provider = SearxSearchProvider(endpoint)

    def history(self, context: AuthContext, space_id: UUID) -> list[dict[str, Any]]:
        with self.engine.begin() as connection:
            _access(connection, context, space_id, None)
            # Serialize lifecycle reconciliation with search completion and space changes.
            _space(connection, context, space_id, lock=True, allow_archived=True)
            table = tables.research_searches
            rows = list(
                connection.execute(
                    select(table)
                    .where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        _line_filter(table, context),
                    )
                    .order_by(table.c.started_at.desc())
                    .limit(30)
                ).mappings()
            )
            result: list[dict[str, Any]] = []
            now = datetime.now(UTC)
            for row in rows:
                if row["status"] == "running" and row["started_at"] < now - timedelta(seconds=90):
                    after = (
                        connection.execute(
                            table.update()
                            .where(table.c.id == row["id"])
                            .values(
                                status="failed",
                                error_code="SEARCH_INTERRUPTED",
                                error_message="搜索未在期限内返回，可重新发起查询",
                                version=row["version"] + 1,
                                finished_at=now,
                            )
                            .returning(table)
                        )
                        .mappings()
                        .one()
                    )
                    _emit(
                        connection,
                        context,
                        space_id,
                        "research_search",
                        "interrupted",
                        after,
                        before=row,
                    )
                    row = after
                result.append(_plain(row))
            return result

    def search(
        self, context: AuthContext, space_id: UUID, request: ResearchSearchRequest
    ) -> dict[str, Any]:
        table = tables.research_searches
        now = datetime.now(UTC)
        fingerprint = digest(request.model_dump(mode="json"))
        with self.engine.begin() as connection:
            _access(connection, context, space_id, request.product_line_id, lock=True)
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == context.tenant.id,
                        table.c.market_space_id == space_id,
                        table.c.requested_by_user_id == context.user.id,
                        table.c.request_id == request.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing:
                if existing["request_digest"] != fingerprint:
                    raise ProductWorkError("同一搜索请求编号不能用于不同查询")
                # A replay never launches a second search.
                # An interrupted request gets a visible terminal result.
                if existing["status"] == "running" and existing["started_at"] < now - timedelta(
                    seconds=90
                ):
                    after = (
                        connection.execute(
                            table.update()
                            .where(table.c.id == existing["id"])
                            .values(
                                status="failed",
                                error_code="SEARCH_INTERRUPTED",
                                error_message="搜索未在期限内返回，可重新发起查询",
                                version=existing["version"] + 1,
                                finished_at=now,
                            )
                            .returning(table)
                        )
                        .mappings()
                        .one()
                    )
                    _emit(
                        connection,
                        context,
                        space_id,
                        "research_search",
                        "interrupted",
                        after,
                        before=existing,
                    )
                    return _plain(after)
                return _plain(existing)
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        **request.model_dump(exclude={"request_id"}),
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        market_space_id=space_id,
                        requested_by_user_id=context.user.id,
                        request_id=request.request_id,
                        request_digest=fingerprint,
                        provider_key=self.provider.key,
                        provider_protocol_version=self.provider.protocol_version,
                        provider_endpoint_digest=digest(self.provider.endpoint)
                        if self.provider.endpoint
                        else None,
                        status="running",
                        started_at=now,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _emit(connection, context, space_id, "research_search", "started", row)
        values: dict[str, Any] = {"hits": [], "warnings": [], "status": "failed"}
        try:
            result = self.provider.search(
                request.query,
                language=request.language,
                time_range=request.time_range,
                limit=request.result_limit,
            )
            values.update(
                status=result.status,
                hits=result.hits,
                warnings=result.warnings,
                response_digest=result.response_digest,
            )
        except ReachSearchUnavailableError as error:
            values.update(
                status="not_configured" if not self.provider.configured else "unavailable",
                error_code="SEARCH_NOT_CONFIGURED"
                if not self.provider.configured
                else "SEARCH_UNAVAILABLE",
                error_message=str(error),
            )
        except ReachDeniedError as error:
            values.update(status="denied", error_code=error.reason, error_message=str(error))
        except ReachFetchError as error:
            values.update(
                status="unavailable", error_code="SEARCH_UNAVAILABLE", error_message=str(error)
            )
        denied = False
        with self.engine.begin() as connection:
            # Keep lock ordering identical to ordinary market-space commands.
            try:
                _access(connection, context, space_id, request.product_line_id, lock=True)
            except (ProductWorkAccessError, ProductWorkError):
                denied = True
                values = {
                    "status": "denied",
                    "hits": [],
                    "warnings": [],
                    "error_code": "SEARCH_SCOPE_REVOKED",
                    "error_message": "查询期间授权变化，结果未披露",
                }
            current = (
                connection.execute(select(table).where(table.c.id == row["id"]).with_for_update())
                .mappings()
                .one()
            )
            if current["status"] == "running":
                current_after = (
                    connection.execute(
                        table.update()
                        .where(table.c.id == row["id"])
                        .values(
                            **values, version=current["version"] + 1, finished_at=datetime.now(UTC)
                        )
                        .returning(table)
                    )
                    .mappings()
                    .one()
                )
                _emit(
                    connection,
                    context,
                    space_id,
                    "research_search",
                    "finished",
                    current_after,
                    before=current,
                )
                current = current_after
        if denied:
            raise ProductWorkAccessError("查询期间授权变化，结果未披露")
        return _plain(current)
