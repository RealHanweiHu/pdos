"""Explicit native calendar selection and current invalidation, without DB IO."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine

from pdos_next.domain.external_wait import calendar_owner as owner
from pdos_next.domain.planning.calendar import WorkingCalendar
from pdos_next.engines.planning.calendar import WorkingTime
from pdos_next.engines.planning.dto import CalendarSnapshot
from pdos_next.errors import DomainError
from pdos_next.schemas.planning import Calendar
from pdos_next.service import Context, digest

AT = datetime(2026, 10, 19, 9, tzinfo=UTC)
SOURCE_RECHECK = owner._sources


class Rows:
    def __init__(self, values):
        self.values = values

    def one_or_none(self):
        assert len(self.values) <= 1
        return self.values[0] if self.values else None

    def __iter__(self):
        return iter(self.values)


class Session:
    def __init__(self, *, queries=(), scalars=(), values=(), issuer=None):
        self.queries, self.scalar_rows, self.values = list(queries), list(scalars), list(values)
        self.statements = []
        self.engine = NS(_pdos_operational_issuers={"actual-host": issuer})

    def execute(self, statement):
        self.statements.append(statement)
        assert self.queries, "Unexpected extra native query"
        return Rows(self.queries.pop(0))

    def scalar(self, statement):
        self.statements.append(statement)
        assert self.scalar_rows, "Unexpected extra native scalar query"
        return self.scalar_rows.pop(0)

    def scalars(self, statement):
        self.statements.append(statement)
        assert self.values, "Unexpected extra resource batch"
        return self.values.pop(0)

    def get_bind(self):
        return self.engine

    def __getattr__(self, name):
        raise AssertionError(f"Calendar read must not call Session.{name}")


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Calendar owner pure tests must not connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.fixture
def case(monkeypatch):
    tenant, category, person, pid, project_id = (uuid4() for _ in range(5))
    ctx = Context(tenant, person, person, category_id=category)
    scope = dict(tenant_id=tenant, category_id=category, product_id=pid, project_id=project_id)
    project = NS(
        **{key: value for key, value in scope.items() if key != "project_id"}, id=project_id
    )
    raw = Calendar(
        key="explicit-project-clock",
        version="v1",
        timezone="UTC",
        working_weekdays=[0, 1, 2, 3, 4],
        intervals=[{"start_minute": 540, "end_minute": 1020}],
        holidays=["2026-10-20"],
    ).model_dump(mode="json")
    raw["timezone_rules_sha256"] = WorkingCalendar(
        Calendar.model_validate(raw)
    ).timezone_rules_sha256
    proposal = NS(**scope, id=uuid4(), revision=2, input_snapshot={"calendar": raw})
    plan = NS(
        **scope,
        id=uuid4(),
        revision=1,
        proposal_id=proposal.id,
        status="applied",
        forecast={
            "calendar_ref": {
                key: raw[key] for key in ("key", "version", "timezone", "timezone_rules_sha256")
            }
        },
    )
    project.current_plan_id = plan.id
    link = NS(definition_id=uuid4(), definition_revision=1)
    definition = {"source_status": "current", "sources": []}
    calls = []

    def project_read(s, context, product, identity, **kwargs):
        assert context is ctx and product == pid and identity == project_id
        assert not kwargs.get("lock", False)
        calls.append("project")
        return project

    def source_read(s, context, product, identity):
        assert context is ctx and product == pid and identity == project_id
        calls.append("definition")
        return project, link, definition

    def sources(s, context, product, refs, expected=None):
        assert context is ctx and product == pid
        calls.append("sources")
        material = {"references_sha256": digest(refs), "artifacts": []}
        assert expected is None or expected == material
        return material

    monkeypatch.setattr(owner.work_owner, "project", project_read)
    monkeypatch.setattr(owner.projects, "_project", source_read)
    monkeypatch.setattr(owner, "_sources", sources)
    monkeypatch.setattr(owner, "now", lambda: AT)
    ref = {
        "kind": "project_plan",
        "id": str(plan.id),
        "revision": 1,
        "calendar_key": raw["key"],
        "calendar_version": raw["version"],
        "resource_id": None,
    }
    return NS(**locals())


def test_real_applied_plan_normalizes_to_existing_engine_and_retains_original_json(case):
    session = Session(queries=[[(case.plan, case.proposal)]])
    result = owner.resolve(session, case.ctx, case.pid, case.project_id, case.ref)
    assert result["ref"] == case.ref
    assert result["basis"]["source_calendar"] == case.raw
    assert result["basis"]["material"]["proposal_id"] == str(case.proposal.id)
    assert result["basis"]["material"]["definition_ref"] == {
        "id": str(case.link.definition_id),
        "revision": 1,
    }
    clock = WorkingTime(CalendarSnapshot.model_validate(result["calendar"]))
    assert clock.working_minutes(AT, AT + timedelta(days=2)) == 480
    assert clock.advance(AT, 481) == AT + timedelta(days=2, minutes=1)
    assert result["calendar"]["calendar_id"] == case.raw["key"]
    assert case.calls == ["project", "definition", "sources"]
    sql = str(session.statements[0].compile(dialect=dialect()))
    assert "plan_revisions.proposal_id = plan_proposals.id" in sql
    assert "plan_revisions.status" in sql and "FOR UPDATE" not in sql
    assert "proposal_decisions" not in sql and "JOIN proposals" not in sql


def test_explicit_plan_does_not_follow_later_current_plan_and_detects_changed_calendar(case):
    result = owner.resolve(
        Session(queries=[[(case.plan, case.proposal)]]),
        case.ctx,
        case.pid,
        case.project_id,
        case.ref,
    )
    case.project.current_plan_id = uuid4()
    assert owner.recheck(
        Session(queries=[[(case.plan, case.proposal)]]),
        case.ctx,
        case.pid,
        case.project_id,
        result["basis"],
    )
    case.proposal.input_snapshot["calendar"]["holidays"].append("2026-10-21")
    with pytest.raises(DomainError) as error:
        owner.recheck(
            Session(queries=[[(case.plan, case.proposal)]]),
            case.ctx,
            case.pid,
            case.project_id,
            result["basis"],
        )
    assert error.value.reason == "SOURCE_STALE" and error.value.status == 409


def test_unreadable_plan_or_revoked_original_cannot_be_replaced_by_applied_label(case):
    with pytest.raises(DomainError) as error:
        owner.resolve(Session(queries=[[]]), case.ctx, case.pid, case.project_id, case.ref)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and error.value.status == 403
    case.definition["source_status"] = "needs_recheck"
    with pytest.raises(DomainError) as error:
        owner.resolve(
            Session(queries=[[(case.plan, case.proposal)]]),
            case.ctx,
            case.pid,
            case.project_id,
            case.ref,
        )
    assert error.value.reason == "SOURCE_STALE"


def test_inline_or_cross_project_calendar_never_establishes_native_fact(case):
    with pytest.raises(DomainError) as error:
        owner.resolve(
            Session(), case.ctx, case.pid, case.project_id, {**case.ref, "calendar": case.raw}
        )
    assert error.value.reason == "VALIDATION_FAILED"
    case.plan.project_id = uuid4()
    with pytest.raises(DomainError) as error:
        owner.resolve(
            Session(queries=[[(case.plan, case.proposal)]]),
            case.ctx,
            case.pid,
            case.project_id,
            case.ref,
        )
    assert error.value.reason == "SOURCE_UNAVAILABLE"


@pytest.fixture
def resource_case(case, monkeypatch):
    resource_id, build_id = uuid4(), uuid4()
    calendar = WorkingCalendar(Calendar.model_validate(case.raw))._engine.definition.model_dump(
        mode="json"
    )
    reference = {
        "artifact_id": str(uuid4()),
        "expected_revision": 1,
        "line": 1,
        "quote": "actual calendar",
    }
    resource = owner.ResourceInput(
        resource={"id": resource_id, "revision": 1, "kind": "person"},
        purposes=["test"],
        operation_ids=["read"],
        lifecycle="active",
        calendar=calendar,
        calendar_sources=[reference],
        sources=[reference],
    )
    issuer = NS(version="v1", epoch=1, nature="synthetic")
    fixed = NS(
        **case.scope,
        id=uuid4(),
        revision=1,
        series_id=uuid4(),
        build_id=build_id,
        state="active",
        valid_from=AT - timedelta(days=1),
        valid_until=None,
        fact_sha256="a" * 64,
        issuer_key="actual-host",
        issuer_version="v1",
        issuer_epoch=1,
        nature="synthetic",
        sources=[reference],
        data={"resources": [resource.model_dump(mode="json")]},
    )
    pointer = NS(**case.scope, build_id=build_id, fact_id=fixed.id, fact_revision=1, epoch=1)
    build = NS(**case.scope, id=build_id, revision=4)
    physical = owner.operational._physical(resource.model_dump(mode="json"))
    asset = NS(
        id=resource_id,
        tenant_id=case.tenant,
        kind="resource",
        revision=1,
        data={"value": physical, "state": "active"},
        data_sha256=owner.operational.digest(physical),
    )
    monkeypatch.setattr(owner.operational, "_fact_hash", lambda fact: fact.fact_sha256)
    monkeypatch.setattr(owner.operational, "_issuer", lambda s, ctx, pid, project, actual: actual)
    ref = {
        "kind": "build_resource",
        "id": str(fixed.id),
        "revision": 1,
        "calendar_key": calendar["calendar_id"],
        "calendar_version": calendar["version"],
        "resource_id": str(resource_id),
    }

    def session(*, current=None, pointer_value=None, include_fixed=True):
        current = current or fixed
        return Session(
            queries=[[(pointer_value or pointer, current, build)]],
            scalars=[fixed, asset] if include_fixed else [asset],
            issuer=issuer,
        )

    return NS(**locals())


def test_resource_calendar_uses_real_fact_asset_and_original_calendar_path(resource_case):
    r, c = resource_case, resource_case.case
    result = owner.resolve(r.session(), c.ctx, c.pid, c.project_id, r.ref)
    assert result["basis"]["source_calendar"] == r.fixed.data["resources"][0]["calendar"]
    assert result["basis"]["current"] == {"fact_id": str(r.fixed.id), "revision": 1, "epoch": 1}
    assert result["basis"]["material"]["resource_revision"] == 1
    assert result["calendar"]["calendar_id"] == r.calendar["calendar_id"]


def test_resource_new_calendar_does_not_rewrite_adopted_calendar_but_withdrawal_blocks(
    resource_case,
):
    r, c = resource_case, resource_case.case
    original = owner.resolve(r.session(), c.ctx, c.pid, c.project_id, r.ref)
    changed = deepcopy(r.fixed)
    changed.id, changed.revision = uuid4(), 2
    changed.data["resources"][0]["calendar"]["version"] = "v2"
    changed.data["resources"][0]["resource"]["revision"] = 2
    r.asset.revision = 2
    pointer = NS(**{**vars(r.pointer), "fact_id": changed.id, "fact_revision": 2, "epoch": 2})
    physical = owner.operational._physical(
        owner.ResourceInput.model_validate(changed.data["resources"][0]).model_dump(mode="json")
    )
    r.asset.data, r.asset.data_sha256 = (
        {"value": physical, "state": "active"},
        owner.operational.digest(physical),
    )
    assert owner.recheck(
        r.session(current=changed, pointer_value=pointer),
        c.ctx,
        c.pid,
        c.project_id,
        original["basis"],
    )
    assert original["calendar"]["version"] == "v1"
    changed.state = "withdrawn"
    with pytest.raises(DomainError) as error:
        owner.recheck(
            r.session(current=changed, pointer_value=pointer),
            c.ctx,
            c.pid,
            c.project_id,
            original["basis"],
        )
    assert error.value.reason == "SOURCE_STALE"


@pytest.mark.parametrize("invalid", ["fact", "issuer", "resource", "asset"])
def test_resource_current_invalidity_blocks_calendar_use(resource_case, invalid):
    r, c = resource_case, resource_case.case
    if invalid == "fact":
        r.fixed.valid_until = AT
    elif invalid == "issuer":
        r.issuer.epoch += 1
    elif invalid == "resource":
        r.fixed.data["resources"][0]["lifecycle"] = "withdrawn"
    else:
        r.asset.data["state"] = "withdrawn"
    with pytest.raises(DomainError) as error:
        owner.resolve(r.session(), c.ctx, c.pid, c.project_id, r.ref)
    assert error.value.reason == "SOURCE_STALE" and error.value.status == 409


def test_available_reads_real_current_plan_and_batches_resource_assets(resource_case):
    r, c = resource_case, resource_case.case
    s = Session(
        queries=[[(c.plan, c.proposal)], [(r.pointer, r.fixed, r.build)]],
        values=[[r.asset]],
        issuer=r.issuer,
    )
    results = owner.available(s, c.ctx, c.pid, c.project_id, {"id": str(r.build_id), "revision": 4})
    assert len(results) == 2 and not s.queries and not s.values
    assert all("采用的" in value["label"] and "供应方" not in value["label"] for value in results)
    assert [value["ref"]["kind"] for value in results] == ["project_plan", "build_resource"]
    assert len(s.statements) == 3
    selected = str(
        s.statements[1].compile(dialect=dialect(), compile_kwargs={"literal_binds": True})
    )
    assert f"builds.id = '{r.build_id}'" in selected and "builds.revision = 4" in selected


def test_recheck_direct_source_metadata_rejects_actual_source_withdrawal(case, monkeypatch):
    reference = {
        "artifact_id": str(uuid4()),
        "expected_revision": 1,
        "line": 1,
        "quote": "Real registered calendar source",
    }
    expected = {
        "references_sha256": digest([reference]),
        "artifacts": [{"id": reference["artifact_id"], "revision": 1}],
    }
    seen = []

    def current(s, ctx, pid, basis):
        assert ctx is case.ctx and pid == case.pid
        assert basis == {"artifacts": expected["artifacts"]}
        seen.append(True)
        return True

    monkeypatch.setattr(owner.work_owner, "sources_current", current)
    assert SOURCE_RECHECK(Session(), case.ctx, case.pid, [reference], expected) == expected
    assert seen == [True]

    def withdrawn(*_args, **_kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "Original source was withdrawn", 403)

    monkeypatch.setattr(owner.work_owner, "sources_current", withdrawn)
    with pytest.raises(DomainError) as error:
        SOURCE_RECHECK(Session(), case.ctx, case.pid, [reference], expected)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and error.value.status == 403
