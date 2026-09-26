"""Recurring meeting generation and conference booking (vNext V2-2, D35)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Table, create_engine

from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.domain.meeting_scheduling import (
    MeetingSchedulingService,
    RecurrenceRecord,
    RecurrenceValidationError,
    occurrences_between,
)
from app.integrations.conference import (
    ConferenceProviderError,
    InMemoryConferenceProvider,
    UnconfiguredConferenceProvider,
)
from tests.db_cleanup import clear_test_tenants

SERVER_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)  # a Tuesday


@pytest.fixture
def database_url() -> Iterator[str]:
    test_url = configured_test_database_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            clear_test_tenants(connection)
        yield test_url
    finally:
        engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


class Scope:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(psycopg_database_url(database_url))
        self.tenant_id = uuid4()
        self.owner_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                tables.tenants.insert(),
                {"id": self.tenant_id, "slug": f"sched-{self.tenant_id}", "name": "Sched"},
            )
            connection.execute(
                tables.users.insert(),
                {
                    "id": self.owner_id,
                    "tenant_id": self.tenant_id,
                    "username": "owner",
                    "display_name": "Owner",
                    "role": "owner",
                    "password_hash": "x" * 60,
                },
            )
        workflow_id = self._insert(tables.workflows, {"code": "WF-S", "name": "WF"})
        self.project_id = self._insert(
            tables.projects,
            {
                "workflow_id": workflow_id,
                "owner_user_id": self.owner_id,
                "code": "PRJ-S",
                "name": "Scheduling project",
                "status": "active",
            },
        )
        self._insert(
            tables.project_members,
            {
                "project_id": self.project_id,
                "user_id": self.owner_id,
                "added_by_user_id": self.owner_id,
            },
        )

    def dispose(self) -> None:
        self.engine.dispose()

    def _insert(self, table: Table, values: dict[str, Any]) -> UUID:
        row_id: UUID = values.setdefault("id", uuid4())
        values.setdefault("tenant_id", self.tenant_id)
        with self.engine.begin() as connection:
            connection.execute(table.insert(), values)
        return row_id

    def member(self, username: str) -> UUID:
        user_id = self._insert(
            tables.users,
            {
                "username": username,
                "display_name": username.title(),
                "role": "engineer",
                "password_hash": "x" * 60,
            },
        )
        self._insert(
            tables.project_members,
            {
                "project_id": self.project_id,
                "user_id": user_id,
                "added_by_user_id": self.owner_id,
            },
        )
        return user_id


@pytest.fixture
def scope(database_url: str) -> Iterator[Scope]:
    built = Scope(database_url)
    try:
        yield built
    finally:
        built.dispose()


def weekly(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "meeting_type": "weekly",
        "title": "项目周会",
        "cadence": "weekly",
        "day_of_week": 1,  # Monday
        "start_minute_of_day": 9 * 60,
        "duration_minutes": 60,
    }
    body.update(overrides)
    return body


def make_recurrence(
    service: MeetingSchedulingService, scope: Scope, **overrides: Any
) -> RecurrenceRecord:
    return service.create_recurrence(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        actor_user_id=scope.owner_id,
        now=NOW,
        **weekly(**overrides),
    )


def test_weekly_occurrences_land_on_the_configured_weekday() -> None:
    recurrence = RecurrenceRecord(
        id=uuid4(),
        project_id=uuid4(),
        meeting_type="weekly",
        title="周会",
        cadence="weekly",
        day_of_week=1,
        day_of_month=None,
        start_minute_of_day=540,
        duration_minutes=60,
        timezone="Asia/Shanghai",
        default_participants=[],
        agenda_template=[],
        auto_conference=False,
        status="active",
    )
    dates = occurrences_between(recurrence, start=date(2026, 9, 1), end=date(2026, 9, 30))

    assert dates == [
        date(2026, 9, 7),
        date(2026, 9, 14),
        date(2026, 9, 21),
        date(2026, 9, 28),
    ]
    assert all(day.isoweekday() == 1 for day in dates)


def a_recurrence(
    *, cadence: str, day_of_week: int | None = None, day_of_month: int | None = None
) -> RecurrenceRecord:
    return RecurrenceRecord(
        id=uuid4(),
        project_id=uuid4(),
        meeting_type="weekly",
        title="会",
        cadence=cadence,
        day_of_week=day_of_week,
        day_of_month=day_of_month,
        start_minute_of_day=540,
        duration_minutes=60,
        timezone="Asia/Shanghai",
        default_participants=[],
        agenda_template=[],
        auto_conference=False,
        status="active",
        start_date=date(2026, 9, 1),
    )


def test_biweekly_steps_a_fortnight_and_monthly_uses_day_of_month() -> None:
    fortnightly = a_recurrence(cadence="biweekly", day_of_week=1)
    assert occurrences_between(fortnightly, start=date(2026, 9, 1), end=date(2026, 9, 30)) == [
        date(2026, 9, 7),
        date(2026, 9, 21),
    ]

    assert occurrences_between(fortnightly, start=date(2026, 9, 8), end=date(2026, 9, 30)) == [
        date(2026, 9, 21),
    ], "Changing the query window must not move the saved biweekly phase"

    monthly = a_recurrence(cadence="monthly", day_of_month=15)
    assert occurrences_between(monthly, start=date(2026, 9, 1), end=date(2026, 11, 30)) == [
        date(2026, 9, 15),
        date(2026, 10, 15),
        date(2026, 11, 15),
    ]


def test_generation_is_idempotent(scope: Scope) -> None:
    """A retried or double-fired job must not produce two Monday reviews."""
    service = MeetingSchedulingService(scope.engine)
    recurrence = make_recurrence(service, scope, auto_conference=False)

    first = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 30),
        now=NOW,
    )
    second = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 30),
        now=NOW,
    )

    assert [item.created for item in first] == [True] * 4
    assert [item.created for item in second] == [False] * 4
    assert [item.meeting.id for item in second] == [item.meeting.id for item in first]

    from app.domain.meetings import MeetingService

    assert (
        len(
            MeetingService(scope.engine).list(
                tenant_id=scope.tenant_id, project_id=scope.project_id
            )
        )
        == 4
    )


def test_generated_meetings_carry_default_participants_and_agenda(
    scope: Scope,
) -> None:
    from app.domain.meetings import MeetingService

    engineer_id = scope.member("engineer")
    service = MeetingSchedulingService(scope.engine)
    recurrence = make_recurrence(
        service,
        scope,
        auto_conference=False,
        default_participants=[{"user_id": str(engineer_id), "participation": "required"}],
        agenda_template=[
            {"title": "上周行动项复查", "item_kind": "review"},
            {"title": "本周风险", "item_kind": "topic"},
        ],
    )

    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 8),
        now=NOW,
    )
    meeting_id = generated[0].meeting.id
    meetings = MeetingService(scope.engine)

    seats = {
        item.user_id
        for item in meetings.participants(
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            meeting_id=meeting_id,
        )
    }
    agenda = meetings.agenda(
        tenant_id=scope.tenant_id, project_id=scope.project_id, meeting_id=meeting_id
    )

    assert engineer_id in seats
    assert [item.title for item in agenda] == ["上周行动项复查", "本周风险"]


def test_a_conference_is_booked_and_bound_to_the_meeting(scope: Scope) -> None:
    provider = InMemoryConferenceProvider()
    service = MeetingSchedulingService(scope.engine, conference_provider=provider)
    recurrence = make_recurrence(service, scope)

    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 8),
        now=NOW,
    )

    assert generated[0].conference_booked is True
    assert generated[0].meeting.external_provider == "dingtalk"
    join_url = generated[0].meeting.external_join_url
    assert join_url is not None and join_url.startswith("https://")


def test_a_provider_failure_degrades_to_a_manual_booking(scope: Scope) -> None:
    """API 失败降级为手工建会: losing the agenda over a conference blip would be
    a far worse outcome than a meeting with no link."""
    provider = InMemoryConferenceProvider()
    provider.fail_next = ConferenceProviderError("provider unavailable")
    service = MeetingSchedulingService(scope.engine, conference_provider=provider)
    recurrence = make_recurrence(service, scope)

    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 8),
        now=NOW,
    )

    assert generated[0].created is True
    assert generated[0].conference_booked is False
    assert "provider unavailable" in (generated[0].conference_error or "")
    # The meeting stands, with no link.
    assert generated[0].meeting.external_provider is None
    assert generated[0].meeting.status == "scheduled"


def test_an_unconfigured_provider_fails_loudly_rather_than_faking_a_link(
    scope: Scope,
) -> None:
    service = MeetingSchedulingService(
        scope.engine, conference_provider=UnconfiguredConferenceProvider("tencent_meeting")
    )
    recurrence = make_recurrence(service, scope)

    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 8),
        now=NOW,
    )

    assert generated[0].conference_booked is False
    assert "not configured" in (generated[0].conference_error or "")
    assert generated[0].meeting.external_join_url is None


def test_regenerating_reuses_the_providers_booking_rather_than_a_second_room(
    scope: Scope,
) -> None:
    provider = InMemoryConferenceProvider()
    service = MeetingSchedulingService(scope.engine, conference_provider=provider)
    recurrence = make_recurrence(service, scope)

    for _ in range(2):
        service.generate(
            tenant_id=scope.tenant_id,
            recurrence_id=recurrence.id,
            actor_user_id=scope.owner_id,
            since=date(2026, 9, 1),
            through=date(2026, 9, 8),
            now=NOW,
        )

    assert len(provider.bookings) == 1


def test_a_paused_recurrence_generates_nothing(scope: Scope) -> None:
    service = MeetingSchedulingService(scope.engine)
    recurrence = make_recurrence(service, scope, auto_conference=False)
    service.set_status(tenant_id=scope.tenant_id, recurrence_id=recurrence.id, status="paused")

    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 30),
        now=NOW,
    )
    assert generated == []


def test_cancelling_an_occurrence_releases_the_conference_room(scope: Scope) -> None:
    provider = InMemoryConferenceProvider()
    service = MeetingSchedulingService(scope.engine, conference_provider=provider)
    recurrence = make_recurrence(service, scope)
    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 8),
        now=NOW,
    )
    conference_id = generated[0].meeting.external_meeting_id

    cancelled = service.cancel_occurrence(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        meeting_id=generated[0].meeting.id,
        actor_user_id=scope.owner_id,
        reason="本周无议题",
    )

    assert cancelled.status == "cancelled"
    assert provider.cancelled == [conference_id]


def test_a_failed_room_release_does_not_undo_the_cancellation(scope: Scope) -> None:
    provider = InMemoryConferenceProvider()
    service = MeetingSchedulingService(scope.engine, conference_provider=provider)
    recurrence = make_recurrence(service, scope)
    generated = service.generate(
        tenant_id=scope.tenant_id,
        recurrence_id=recurrence.id,
        actor_user_id=scope.owner_id,
        since=date(2026, 9, 1),
        through=date(2026, 9, 8),
        now=NOW,
    )
    provider.fail_next = ConferenceProviderError("cancel failed")

    cancelled = service.cancel_occurrence(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        meeting_id=generated[0].meeting.id,
        actor_user_id=scope.owner_id,
        reason="本周无议题",
    )
    assert cancelled.status == "cancelled"


def test_a_cadence_must_say_which_day_it_falls_on(scope: Scope) -> None:
    service = MeetingSchedulingService(scope.engine)

    with pytest.raises(RecurrenceValidationError):
        service.create_recurrence(
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            actor_user_id=scope.owner_id,
            meeting_type="weekly",
            title="无日周会",
            cadence="weekly",
            start_minute_of_day=540,
            duration_minutes=60,
        )
    with pytest.raises(RecurrenceValidationError):
        service.create_recurrence(
            tenant_id=scope.tenant_id,
            project_id=scope.project_id,
            actor_user_id=scope.owner_id,
            meeting_type="weekly",
            title="无日月会",
            cadence="monthly",
            start_minute_of_day=540,
            duration_minutes=60,
        )
