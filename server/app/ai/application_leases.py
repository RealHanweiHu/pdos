"""Request-owned lease identities; PostgreSQL fences work and supervises expiry."""

from __future__ import annotations

from datetime import timedelta
from threading import Lock
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, text

from app.ai.budget_ledger import BudgetLedgerError
from app.ai.lease_heartbeat import LeaseHeartbeat
from app.db.schema import tables


class ApplicationLeaseKeeper:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.owner_id = uuid4()
        self._tokens: dict[tuple[UUID, UUID], UUID] = {}
        self._recoveries: set[tuple[UUID, UUID]] = set()
        self._lock = Lock()
        self._heartbeat = LeaseHeartbeat(self.renew_all)

    def __enter__(self) -> ApplicationLeaseKeeper:
        self._heartbeat.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._heartbeat.close()

    def issue(self, c: Connection, tenant: UUID, run: UUID) -> None:
        auth = (
            c.execute(
                select(tables.application_authorizations).where(
                    tables.application_authorizations.c.tenant_id == tenant,
                    tables.application_authorizations.c.run_id == run,
                )
            )
            .mappings()
            .one()
        )
        now = c.execute(select(func.clock_timestamp())).scalar_one()
        expiry = min(now + timedelta(seconds=60), auth["expires_at"])
        if expiry <= now:
            raise BudgetLedgerError("APPLICATION_RUN_LEASE_EXPIRED")
        token = uuid4()
        c.execute(
            tables.application_run_leases.insert().values(
                id=token,
                tenant_id=tenant,
                run_id=run,
                authorization_id=auth["id"],
                owner_id=self.owner_id,
                issued_at=now,
                renewed_at=now,
                expires_at=expiry,
            )
        )
        with self._lock:
            self._tokens[tenant, run] = token

    def register_recovery(self, tenant: UUID, run: UUID, token: UUID) -> None:
        with self._lock:
            self._tokens[tenant, run] = token
            self._recoveries.add((tenant, run))

    def is_recovery(self, tenant: UUID, run: UUID) -> bool:
        with self._lock:
            return (tenant, run) in self._recoveries

    def token(self, tenant: UUID, run: UUID) -> UUID | None:
        with self._lock:
            return self._tokens.get((tenant, run))

    def renew_all(self) -> None:
        with self._lock:
            tokens = list(self._tokens.items())
        for (tenant, run), token in tokens:
            with self.engine.begin() as c:
                c.execute(text("SET LOCAL lock_timeout='2s'"))
                c.execute(text("SET LOCAL statement_timeout='5s'"))
                row = c.execute(
                    select(tables.agent_runs.c.status)
                    .where(
                        tables.agent_runs.c.tenant_id == tenant,
                        tables.agent_runs.c.id == run,
                    )
                    .with_for_update()
                ).first()
                # Registration happens in creation's transaction. An uncommitted
                # or rolled-back creation is never treated as a renewable run.
                if row is None or row.status != "running":
                    continue
                if not c.execute(
                    text("SELECT cehub_ai.application_lease_is_current(:r,:t)"),
                    dict(r=run, t=token),
                ).scalar_one():
                    continue
                now = c.execute(select(func.clock_timestamp())).scalar_one()
                deadline = c.execute(
                    select(tables.application_authorizations.c.expires_at).where(
                        tables.application_authorizations.c.tenant_id == tenant,
                        tables.application_authorizations.c.run_id == run,
                    )
                ).scalar_one()
                c.execute(
                    tables.application_run_leases.update()
                    .where(
                        tables.application_run_leases.c.id == token,
                    )
                    .values(renewed_at=now, expires_at=min(now + timedelta(seconds=60), deadline))
                )


def bind_write(
    c: Connection, gateway: object, tenant: UUID, run: UUID, *, success: bool = True
) -> UUID | None:
    auth = c.execute(
        select(tables.application_authorizations.c.id).where(
            tables.application_authorizations.c.tenant_id == tenant,
            tables.application_authorizations.c.run_id == run,
        )
    ).first()
    if auth is None:
        return None
    keeper = getattr(gateway, "application_lease_keeper", None)
    token = keeper.token(tenant, run) if isinstance(keeper, ApplicationLeaseKeeper) else None
    if token is None:
        raise BudgetLedgerError("APPLICATION_RUN_LEASE_REQUIRED")
    status = c.execute(
        select(tables.agent_runs.c.status)
        .where(
            tables.agent_runs.c.tenant_id == tenant,
            tables.agent_runs.c.id == run,
        )
        .with_for_update()
    ).scalar_one()
    lease = (
        c.execute(
            select(tables.application_run_leases)
            .where(
                tables.application_run_leases.c.tenant_id == tenant,
                tables.application_run_leases.c.run_id == run,
                tables.application_run_leases.c.id == token,
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if status != "running" or lease is None or lease["id"] != token or lease["ended_at"]:
        raise BudgetLedgerError("APPLICATION_RUN_LEASE_LOST")
    if (
        success
        and not c.execute(
            text("SELECT cehub_ai.application_lease_is_current(:r,:t)"), dict(r=run, t=token)
        ).scalar_one()
    ):
        raise BudgetLedgerError("APPLICATION_RUN_LEASE_LOST")
    c.execute(
        text("SELECT set_config('pdos.application_lease_id',:token,true)"), dict(token=str(token))
    )
    return token


def verify(engine: Engine, gateway: object, tenant: UUID, run: UUID | None) -> None:
    if run is not None:
        with engine.begin() as c:
            bind_write(c, gateway, tenant, run)
