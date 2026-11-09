"""Read and maintain the tenant's working calendars (D221).

Reads: every active member of the tenant (schedules and 小Pai explain dates with
them). Writes: only an active human tenant administrator acting for themself; the
AI identity, a delegated session or any Run is refused here and again by the
database policies (s0_0910). This is tenant configuration, like accounts (P78),
not a business command, so it carries no AI write tier.

Every save is a complete new version. ``expected_revision`` must match the current
one, and the request key makes a retried save return the version it already wrote.
"""

from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select, text

from pdos_next.core.models import Principal, now
from pdos_next.core.service import digest
from pdos_next.errors import DomainError

from . import rules
from .models import FACTORY_NAME, WorkCalendar, WorkCalendarVersion


def can_manage(s) -> bool:
    return bool(s.scalar(text("SELECT public.account_administrator()")))


def _require_administrator(s, ctx):
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"work_calendar:{ctx.tenant_id}"},
    )
    if ctx.run_id or ctx.agent_run_id or ctx.actor_id != ctx.requester_id or not can_manage(s):
        raise DomainError("ADMINISTRATOR_REQUIRED", "工作日历须由租户管理员本人维护。", 403)


def _definition(value) -> rules.Definition:
    try:
        return rules.Definition.model_validate(value)
    except ValidationError as error:
        first = error.errors()[0]
        message = str(first.get("ctx", {}).get("error") or first.get("msg", "日历内容无效"))
        raise DomainError("VALIDATION_FAILED", message.removeprefix("Value error, "), 422) from None


def _reason(value: str) -> str:
    value = " ".join(str(value or "").split())
    if not 1 <= len(value) <= 200:
        raise DomainError("VALIDATION_FAILED", "请写明修改原因（200 字以内）。", 422)
    return value


def _supplier_name(value: str) -> str:
    value = " ".join(str(value or "").split())
    if not 1 <= len(value) <= 80:
        raise DomainError("VALIDATION_FAILED", "供应商名称须为 1–80 个字。", 422)
    if value == FACTORY_NAME:
        raise DomainError("VALIDATION_FAILED", "该名称保留给工厂日历。", 422)
    return value


def _stored(definition: rules.Definition) -> dict:
    return {
        "timezone": definition.timezone,
        "working_weekdays": list(definition.working_weekdays),
        "entries": [entry.model_dump(mode="json") for entry in definition.entries],
    }


def _calendar(identity: WorkCalendar, version: WorkCalendarVersion) -> rules.Calendar:
    return rules.Calendar(
        calendar_id=str(identity.id),
        kind=identity.kind,
        name=identity.name,
        revision=version.revision,
        definition=rules.Definition(
            timezone=version.timezone,
            working_weekdays=tuple(version.working_weekdays),
            entries=version.entries,
        ),
    )


def _currents(s, tenant_id, *, kind=None, calendar_id=None):
    latest = (
        select(
            WorkCalendarVersion.calendar_id,
            func.max(WorkCalendarVersion.revision).label("revision"),
        )
        .where(WorkCalendarVersion.tenant_id == tenant_id)
        .group_by(WorkCalendarVersion.calendar_id)
        .subquery()
    )
    query = (
        select(WorkCalendar, WorkCalendarVersion)
        .join(
            latest,
            latest.c.calendar_id == WorkCalendar.id,
        )
        .join(
            WorkCalendarVersion,
            (WorkCalendarVersion.tenant_id == WorkCalendar.tenant_id)
            & (WorkCalendarVersion.calendar_id == WorkCalendar.id)
            & (WorkCalendarVersion.revision == latest.c.revision),
        )
        .where(WorkCalendar.tenant_id == tenant_id)
    )
    if kind is not None:
        query = query.where(WorkCalendar.kind == kind)
    if calendar_id is not None:
        query = query.where(WorkCalendar.id == calendar_id)
    return s.execute(query.order_by(WorkCalendar.kind, WorkCalendar.name)).all()


def factory(s, tenant_id) -> rules.Calendar | None:
    """The current factory calendar, or None (arithmetic then uses the estimate)."""
    rows = _currents(s, tenant_id, kind="factory")
    return _calendar(*rows[0]) if rows else None


def calendar(s, tenant_id, calendar_id: UUID) -> rules.Calendar:
    rows = _currents(s, tenant_id, calendar_id=calendar_id)
    if not rows:
        raise DomainError("NOT_FOUND", "没有这个工作日历。", 404)
    return _calendar(*rows[0])


def _names(s, tenant_id, ids):
    if not ids:
        return {}
    rows = s.execute(
        select(Principal.id, Principal.name).where(
            Principal.tenant_id == tenant_id, Principal.id.in_(ids)
        )
    )
    return {row.id: row.name for row in rows}


def _view(identity, version, names):
    value = _calendar(identity, version)
    return {
        "calendar_id": str(identity.id),
        "kind": identity.kind,
        "name": identity.name,
        "label": rules.calendar_label(value),
        "revision": version.revision,
        "timezone": version.timezone,
        "working_weekdays": list(version.working_weekdays),
        "entries": [
            {
                **entry.model_dump(mode="json"),
                "kind_label": rules.KIND_LABELS[entry.kind],
                "days": (entry.end - entry.start).days + 1,
            }
            for entry in value.definition.entries
        ],
        "reason": version.reason,
        "updated_at": version.created_at.isoformat(),
        "updated_by": {"id": str(version.author_id), "name": names.get(version.author_id)},
    }


def listing(s, ctx) -> dict:
    rows = _currents(s, ctx.tenant_id)
    names = _names(s, ctx.tenant_id, {version.author_id for _, version in rows})
    factory_row = next((row for row in rows if row[0].kind == "factory"), None)
    return {
        "can_manage": can_manage(s),
        "basis": rules.basis(_calendar(*factory_row) if factory_row else None),
        "calendars": [_view(identity, version, names) for identity, version in rows],
    }


def history(s, ctx, calendar_id: UUID) -> dict:
    identity = s.scalar(
        select(WorkCalendar).where(
            WorkCalendar.tenant_id == ctx.tenant_id, WorkCalendar.id == calendar_id
        )
    )
    if identity is None:
        raise DomainError("NOT_FOUND", "没有这个工作日历。", 404)
    versions = list(
        s.scalars(
            select(WorkCalendarVersion)
            .where(
                WorkCalendarVersion.tenant_id == ctx.tenant_id,
                WorkCalendarVersion.calendar_id == calendar_id,
            )
            .order_by(WorkCalendarVersion.revision.desc())
            .limit(200)
        )
    )
    names = _names(s, ctx.tenant_id, {version.author_id for version in versions})
    return {"items": [_view(identity, version, names) for version in versions]}


def _replayed(s, ctx, calendar_id, request_key, fingerprint):
    """A retried save returns what it wrote; a different body under the key is refused."""
    query = select(WorkCalendarVersion).where(
        WorkCalendarVersion.tenant_id == ctx.tenant_id,
        WorkCalendarVersion.request_key == request_key,
        WorkCalendarVersion.author_id == ctx.actor_id,
    )
    if calendar_id is not None:
        query = query.where(WorkCalendarVersion.calendar_id == calendar_id)
    else:
        query = query.where(WorkCalendarVersion.revision == 1)
    existing = s.scalar(query)
    if existing is None:
        return None
    if existing.request_sha256 != fingerprint:
        raise DomainError("IDEMPOTENCY_CONFLICT", "同一请求编号已用于不同的修改。", 409)
    identity = s.get(WorkCalendar, existing.calendar_id)
    return _view(identity, existing, _names(s, ctx.tenant_id, {existing.author_id}))


def _write(s, ctx, identity, revision, definition, reason, request_key, fingerprint):
    stored = _stored(definition)
    version = WorkCalendarVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        created_at=now(),
        calendar_id=identity.id,
        revision=revision,
        timezone=stored["timezone"],
        working_weekdays=stored["working_weekdays"],
        entries=stored["entries"],
        reason=reason,
        author_id=ctx.actor_id,
        request_key=request_key,
        request_sha256=fingerprint,
    )
    s.add(version)
    s.flush()
    return _view(identity, version, _names(s, ctx.tenant_id, {ctx.actor_id}))


def create(s, ctx, *, kind, name, definition, reason, request_key: UUID) -> dict:
    """The factory calendar (once) or a new supplier calendar, as revision 1."""
    _require_administrator(s, ctx)
    if kind not in ("factory", "supplier"):
        raise DomainError("VALIDATION_FAILED", "日历类型须是工厂或供应商。", 422)
    name = FACTORY_NAME if kind == "factory" else _supplier_name(name)
    value, reason = _definition(definition), _reason(reason)
    fingerprint = digest(
        {"kind": kind, "name": name, "definition": _stored(value), "reason": reason}
    )
    if replay := _replayed(s, ctx, None, request_key, fingerprint):
        return replay
    exists = s.scalar(
        select(WorkCalendar.id).where(
            WorkCalendar.tenant_id == ctx.tenant_id, WorkCalendar.name == name
        )
    )
    if exists is not None:
        message = "工厂日历已存在。" if kind == "factory" else "已有同名的供应商日历。"
        raise DomainError("VALIDATION_FAILED", message, 422)
    identity = WorkCalendar(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        created_at=now(),
        kind=kind,
        name=name,
        created_by=ctx.actor_id,
    )
    s.add(identity)
    s.flush()
    return _write(s, ctx, identity, 1, value, reason, request_key, fingerprint)


def save(
    s, ctx, calendar_id: UUID, *, expected_revision: int, definition, reason, request_key: UUID
) -> dict:
    """A complete new version on top of ``expected_revision``."""
    _require_administrator(s, ctx)
    value, reason = _definition(definition), _reason(reason)
    fingerprint = digest(
        {"expected_revision": expected_revision, "definition": _stored(value), "reason": reason}
    )
    if replay := _replayed(s, ctx, calendar_id, request_key, fingerprint):
        return replay
    rows = _currents(s, ctx.tenant_id, calendar_id=calendar_id)
    if not rows:
        raise DomainError("NOT_FOUND", "没有这个工作日历。", 404)
    identity, current = rows[0]
    if current.revision != expected_revision:
        raise DomainError(
            "REVISION_CONFLICT",
            f"日历已被更新到第 {current.revision} 版，请刷新后再改。",
            409,
            detail={"current_revision": current.revision},
        )
    return _write(s, ctx, identity, current.revision + 1, value, reason, request_key, fingerprint)
