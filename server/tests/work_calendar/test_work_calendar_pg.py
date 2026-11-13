"""D221 tenant working calendars on PostgreSQL: who may write, what is kept, and that
the SQL twin answers exactly like the Python arithmetic."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantAdministrator
from pdos_next.core.database import tenant_session
from pdos_next.core.models import now
from pdos_next.core.service import Context
from pdos_next.domain.work_calendar import rules, service
from pdos_next.domain.work_calendar.models import WorkCalendar, WorkCalendarVersion
from pdos_next.errors import DomainError

SH = ZoneInfo("Asia/Shanghai")
PATH = "/v1/work-calendars"

SPRING_2027 = [
    {"kind": "shutdown", "start": "2027-01-30", "end": "2027-02-21", "label": "2027 春节停线"},
    {"kind": "holiday", "start": "2027-02-05", "end": "2027-02-13", "label": "春节"},
    {"kind": "makeup_workday", "start": "2027-02-20", "end": "2027-02-20", "label": "调休"},
    {"kind": "makeup_workday", "start": "2027-02-28", "end": "2027-02-28", "label": "调休"},
]


def body(**overrides):
    value = {
        "timezone": "Asia/Shanghai",
        "working_weekdays": [1, 2, 3, 4, 5],
        "entries": SPRING_2027,
        "reason": "登记 2027 年春节停线",
        "request_key": str(uuid4()),
    }
    return {**value, **overrides}


def headers(setup, principal):
    return {"Authorization": f"Bearer {setup.tokens[principal]}"}


def reason(response):
    return response.json()["detail"]["reason"]


@pytest.fixture
def calendars(setup):
    """setup.human administers the tenant; setup.peer is an ordinary member."""
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    return setup


def create_factory(setup, **overrides):
    response = setup.client.post(
        PATH, headers=setup.headers, json={"kind": "factory", **body(**overrides)}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_administrator_maintains_and_every_member_reads(calendars):
    setup = calendars
    empty = setup.client.get(PATH, headers=headers(setup, setup.peer)).json()
    assert empty["calendars"] == [] and empty["can_manage"] is False
    assert empty["basis"]["basis"] == "weekdays_estimate"

    created = create_factory(setup)
    assert created["revision"] == 1 and created["label"] == "工厂日历"
    assert created["updated_by"]["name"] == "Synthetic owner"
    assert [e["kind_label"] for e in created["entries"]] == [
        "停线",
        "法定假日",
        "调休上班",
        "调休上班",
    ]

    seen = setup.client.get(PATH, headers=headers(setup, setup.peer)).json()
    assert seen["can_manage"] is False and [c["calendar_id"] for c in seen["calendars"]] == [
        created["calendar_id"]
    ]
    assert seen["basis"] == {
        "basis": "tenant_calendar",
        "basis_label": "按工厂日历第 1 版计算",
        "timezone": "Asia/Shanghai",
        "calendar_id": created["calendar_id"],
        "calendar_name": "工厂日历",
        "calendar_revision": 1,
    }
    assert setup.client.get(PATH, headers=setup.headers).json()["can_manage"] is True

    for response in (
        setup.client.post(
            PATH,
            headers=headers(setup, setup.peer),
            json={"kind": "supplier", "name": "x", **body()},
        ),
        setup.client.post(
            f"{PATH}/{created['calendar_id']}/versions",
            headers=headers(setup, setup.peer),
            json={"expected_revision": 1, **body()},
        ),
    ):
        assert response.status_code == 403 and reason(response) == "ADMINISTRATOR_REQUIRED"

    other = setup.client.get(PATH, headers=headers(setup, setup.other_human)).json()
    assert other["calendars"] == [] and other["basis"]["basis"] == "weekdays_estimate"


def test_saves_are_versions_with_revision_checks_and_retries(calendars):
    setup = calendars
    created = create_factory(setup)
    url = f"{PATH}/{created['calendar_id']}/versions"
    change = body(entries=SPRING_2027[:2], reason="停线改为只登记假期前后")
    saved = setup.client.post(url, headers=setup.headers, json={"expected_revision": 1, **change})
    assert saved.status_code == 201 and saved.json()["revision"] == 2

    again = setup.client.post(url, headers=setup.headers, json={"expected_revision": 1, **change})
    assert again.status_code == 201 and again.json() == saved.json()

    reused = setup.client.post(
        url,
        headers=setup.headers,
        json={"expected_revision": 2, **change, "reason": "另一次修改"},
    )
    assert reused.status_code == 409 and reason(reused) == "IDEMPOTENCY_CONFLICT"

    stale = setup.client.post(url, headers=setup.headers, json={"expected_revision": 1, **body()})
    assert stale.status_code == 409 and reason(stale) == "REVISION_CONFLICT"
    assert stale.json()["detail"]["current_revision"] == 2

    history = setup.client.get(url, headers=headers(setup, setup.peer)).json()["items"]
    assert [item["revision"] for item in history] == [2, 1]
    assert history[1]["entries"][0]["label"] == "2027 春节停线"

    invalid = setup.client.post(
        url,
        headers=setup.headers,
        json={
            "expected_revision": 2,
            **body(entries=[{**SPRING_2027[2], "start": "2027-02-22", "end": "2027-02-22"}]),
        },
    )
    assert invalid.status_code == 422 and reason(invalid) == "VALIDATION_FAILED"
    assert "本来就是工作日" in invalid.json()["message"]

    second_factory = setup.client.post(
        PATH, headers=setup.headers, json={"kind": "factory", **body()}
    )
    assert second_factory.status_code == 422 and "已存在" in second_factory.json()["message"]


def test_supplier_calendars_are_kept_apart_from_the_factory(calendars):
    setup = calendars
    factory = create_factory(setup, entries=[])
    supplier = setup.client.post(
        PATH,
        headers=setup.headers,
        json={
            "kind": "supplier",
            "name": "  合成 电芯厂 ",
            **body(
                entries=[
                    {
                        "kind": "shutdown",
                        "start": "2027-01-20",
                        "end": "2027-02-28",
                        "label": "停产",
                    }
                ]
            ),
        },
    )
    assert supplier.status_code == 201, supplier.text
    supplier = supplier.json()
    assert supplier["name"] == "合成 电芯厂" and supplier["label"] == "供应商日历（合成 电芯厂）"
    duplicate = setup.client.post(
        PATH, headers=setup.headers, json={"kind": "supplier", "name": "合成 电芯厂", **body()}
    )
    assert duplicate.status_code == 422
    reserved = setup.client.post(
        PATH, headers=setup.headers, json={"kind": "supplier", "name": "factory", **body()}
    )
    assert reserved.status_code == 422

    at = datetime(2027, 2, 1, 9, tzinfo=SH).isoformat()
    by_factory = setup.client.get(
        f"{PATH}/working-days", params={"at": at, "days": 1}, headers=headers(setup, setup.peer)
    ).json()
    assert by_factory["result"] == datetime(2027, 2, 2, 1, tzinfo=UTC).isoformat()
    assert by_factory["calendar_id"] == factory["calendar_id"]
    by_supplier = setup.client.get(
        f"{PATH}/working-days",
        params={"at": at, "days": 1, "calendar_id": supplier["calendar_id"]},
        headers=headers(setup, setup.peer),
    ).json()
    assert by_supplier["result"] == datetime(2027, 3, 2, 0, tzinfo=SH).astimezone(UTC).isoformat()
    assert by_supplier["basis_label"] == "按供应商日历（合成 电芯厂）第 1 版计算"


def _agent_context(setup):
    return Context(setup.tenant, setup.agent, setup.human)


def test_ai_identity_and_delegated_or_run_sessions_cannot_write(calendars):
    setup = calendars
    created = create_factory(setup)
    definition = {"working_weekdays": [1, 2, 3, 4, 5], "entries": []}
    contexts = [
        _agent_context(setup),
        Context(setup.tenant, setup.human, setup.human, agent_run_id=uuid4()),
    ]
    for ctx in contexts:
        with pytest.raises(DomainError) as refused:
            with tenant_session(
                setup.engine, setup.tenant, actor_id=ctx.actor_id, requester_id=ctx.requester_id
            ) as s:
                service.save(
                    s,
                    ctx,
                    created["calendar_id"],
                    expected_revision=1,
                    definition=definition,
                    reason="AI 不能改",
                    request_key=uuid4(),
                )
        assert refused.value.reason == "ADMINISTRATOR_REQUIRED"

    # The database refuses the AI identity even past the service.
    with pytest.raises(ProgrammingError, match="row-level security"):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human
        ) as s:
            s.add(
                WorkCalendarVersion(
                    tenant_id=setup.tenant,
                    calendar_id=created["calendar_id"],
                    revision=2,
                    timezone="Asia/Shanghai",
                    working_weekdays=[1, 2, 3, 4, 5],
                    entries=[],
                    reason="AI 直写",
                    author_id=setup.agent,
                    request_key=uuid4(),
                    request_sha256="0" * 64,
                )
            )
            s.flush()

    with setup.admin.connect() as connection:
        for role in ("pdos_agent", "pdos_next_auth", "pdos_next_dispatch"):
            for table in ("work_calendars", "work_calendar_versions"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not connection.execute(
                        text("SELECT has_table_privilege(:r, :t, :p)"),
                        {"r": role, "t": f"public.{table}", "p": privilege},
                    ).scalar_one(), (role, table, privilege)
            assert not connection.execute(
                text(
                    "SELECT has_function_privilege(:r, "
                    "'public.work_calendar_add(timestamptz,integer)', 'EXECUTE')"
                ),
                {"r": role},
            ).scalar_one()


def test_deactivated_administrator_and_skipped_revisions_are_refused(calendars):
    setup = calendars
    created = create_factory(setup)
    with pytest.raises(ProgrammingError, match="row-level security"):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human
        ) as s:
            s.add(
                WorkCalendarVersion(
                    tenant_id=setup.tenant,
                    calendar_id=created["calendar_id"],
                    revision=5,
                    timezone="Asia/Shanghai",
                    working_weekdays=[1, 2, 3, 4, 5],
                    entries=[],
                    reason="跳号",
                    author_id=setup.human,
                    request_key=uuid4(),
                    request_sha256="0" * 64,
                )
            )
            s.flush()
    with Session(setup.admin) as s, s.begin():
        s.execute(
            text("UPDATE tenant_administrators SET active=false WHERE tenant_id=:t"),
            {"t": setup.tenant},
        )
    response = setup.client.post(
        f"{PATH}/{created['calendar_id']}/versions",
        headers=setup.headers,
        json={"expected_revision": 1, **body()},
    )
    assert response.status_code == 403 and reason(response) == "ADMINISTRATOR_REQUIRED"


def test_versions_are_never_updated_or_deleted(calendars):
    setup = calendars
    create_factory(setup)
    for statement in (
        "UPDATE work_calendar_versions SET reason='改写' WHERE tenant_id=:t",
        "DELETE FROM work_calendar_versions WHERE tenant_id=:t",
        "UPDATE work_calendars SET name='factory' WHERE tenant_id=:t",
        "DELETE FROM work_calendars WHERE tenant_id=:t",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with Session(setup.admin) as s, s.begin():
                s.execute(text(statement), {"t": setup.tenant})
        with pytest.raises(ProgrammingError, match="permission denied"):
            with tenant_session(
                setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human
            ) as s:
                s.execute(text(statement), {"t": setup.tenant})


def _sql_add(setup, tenant, actor, at, days):
    with tenant_session(setup.engine, tenant, actor_id=actor, requester_id=actor) as s:
        return s.execute(
            text("SELECT public.work_calendar_add(:at, :days)"), {"at": at, "days": days}
        ).scalar_one()


def test_sql_twin_matches_the_python_arithmetic(calendars):
    setup = calendars
    starts = [
        datetime(2027, 1, 25, 0, tzinfo=SH) + timedelta(hours=7 * step) for step in range(150)
    ]
    # Without a calendar: the Monday-to-Friday estimate, for both.
    for at in starts[::10]:
        for days in (0, 1, 3):
            assert _sql_add(setup, setup.tenant, setup.peer, at, days) == rules.add_working_days(
                None, at, days
            )
    create_factory(setup)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.peer, requester_id=setup.peer
    ) as s:
        current = service.factory(s, setup.tenant)
    assert current.revision == 1
    for at in starts:
        for days in (0, 1, 5):
            assert _sql_add(setup, setup.tenant, setup.peer, at, days) == rules.add_working_days(
                current, at, days
            ), (at, days)
    assert _sql_add(
        setup, setup.tenant, setup.peer, datetime(2027, 1, 29, 10, tzinfo=SH), 1
    ) == datetime(2027, 2, 22, 10, tzinfo=SH)
    # Another tenant still gets the estimate: the calendar never crosses tenants.
    assert _sql_add(
        setup, setup.other_tenant, setup.other_human, datetime(2027, 1, 29, 10, tzinfo=SH), 1
    ) == datetime(2027, 2, 1, 10, tzinfo=SH)
    with pytest.raises(DBAPIError, match="0 to 366"):
        _sql_add(setup, setup.tenant, setup.peer, now(), 367)


def test_rows_are_readable_only_inside_the_tenant(calendars):
    setup = calendars
    create_factory(setup)
    with tenant_session(
        setup.engine, setup.other_tenant, actor_id=setup.other_human, requester_id=setup.other_human
    ) as s:
        assert s.scalars(select(WorkCalendar)).all() == []
        assert s.scalars(select(WorkCalendarVersion)).all() == []
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.agent, requester_id=setup.human
    ) as s:
        # 小Pai reads the calendar to explain dates; it only cannot write.
        assert service.factory(s, setup.tenant).revision == 1
