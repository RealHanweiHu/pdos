"""Tenant working calendar routes (D221). Writes need a human tenant administrator."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import Query
from pydantic import Field

from pdos_next.core.database import tenant_session
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import Context
from pdos_next.errors import DomainError

from . import rules, service


class EntryInput(StrictModel):
    kind: Literal["holiday", "makeup_workday", "shutdown"]
    start: date
    end: date
    label: str = Field(min_length=1, max_length=80)


class DefinitionInput(StrictModel):
    timezone: str = Field(default=rules.DEFAULT_TIMEZONE, min_length=1, max_length=64)
    working_weekdays: list[int] = Field(min_length=1, max_length=7)
    entries: list[EntryInput] = Field(default=[], max_length=rules.MAX_ENTRIES)
    reason: str = Field(min_length=1, max_length=200)
    request_key: UUID

    def definition(self):
        return {
            "timezone": self.timezone,
            "working_weekdays": self.working_weekdays,
            "entries": [entry.model_dump() for entry in self.entries],
        }


class CalendarCreate(DefinitionInput):
    kind: Literal["factory", "supplier"]
    name: str | None = Field(default=None, max_length=80)


class CalendarSave(DefinitionInput):
    expected_revision: int = Field(ge=1)


def register_routes(app, engine, auth_dependency):
    def scope(ctx: Context):
        return tenant_session(
            engine, ctx.tenant_id, actor_id=ctx.actor_id, requester_id=ctx.requester_id
        )

    @app.get("/v1/work-calendars")
    def work_calendars(ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return service.listing(s, ctx)

    @app.post("/v1/work-calendars", status_code=201)
    def work_calendar_create(data: CalendarCreate, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return service.create(
                s,
                ctx,
                kind=data.kind,
                name=data.name,
                definition=data.definition(),
                reason=data.reason,
                request_key=data.request_key,
            )

    @app.get("/v1/work-calendars/working-days")
    def work_calendar_working_days(
        at: datetime,
        days: int = Query(ge=0, le=rules.MAX_DAYS),
        calendar_id: UUID | None = None,
        ctx: Context = auth_dependency,
    ):
        """Try the arithmetic: ``days`` working days after ``at`` (factory by default)."""
        if at.utcoffset() is None:
            raise DomainError("VALIDATION_FAILED", "时刻须带时区。", 422)
        with scope(ctx) as s:
            chosen = (
                service.calendar(s, ctx.tenant_id, calendar_id)
                if calendar_id is not None
                else service.factory(s, ctx.tenant_id)
            )
        return {
            "at": at.isoformat(),
            "days": days,
            "result": rules.add_working_days(chosen, at, days).isoformat(),
            **rules.basis(chosen),
        }

    @app.get("/v1/work-calendars/{calendar_id}/versions")
    def work_calendar_history(calendar_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return service.history(s, ctx, calendar_id)

    @app.post("/v1/work-calendars/{calendar_id}/versions", status_code=201)
    def work_calendar_save(calendar_id: UUID, data: CalendarSave, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return service.save(
                s,
                ctx,
                calendar_id,
                expected_revision=data.expected_revision,
                definition=data.definition(),
                reason=data.reason,
                request_key=data.request_key,
            )
