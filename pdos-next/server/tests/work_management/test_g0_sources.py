"""Native G0 sources under current project scope, without IO or private proposal reads."""

from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Engine

from pdos_next.domain.work_management import g0_sources as sources
from pdos_next.errors import DomainError
from pdos_next.service import Context, digest


class Reference(BaseModel):
    id: UUID
    decision_id: UUID


class Rows:
    def __init__(self, values):
        self.values = values

    def mappings(self):
        return self

    def one_or_none(self):
        assert len(self.values) <= 1
        return self.values[0] if self.values else None

    def __iter__(self):
        return iter(self.values)


class Session:
    def __init__(self, *groups):
        self.groups, self.statements = list(groups), []

    def execute(self, statement):
        self.statements.append(statement)
        assert self.groups, "Unexpected additional source query"
        return Rows(self.groups.pop(0))

    def __getattr__(self, name):
        raise AssertionError(f"Native G0 read must not invoke Session.{name}")


def sql(statement):
    return str(statement.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("G0 source pure tests must not connect")

    monkeypatch.setattr(Engine, "connect", deny)
    monkeypatch.setattr(Engine, "raw_connection", deny)


@pytest.fixture
def case(monkeypatch):
    tenant, category, actor, pid, project_id = (uuid4() for _ in range(5))
    ctx = Context(tenant, actor, actor, category_id=category)
    project = SimpleNamespace(
        tenant_id=tenant,
        category_id=category,
        product_id=pid,
        id=project_id,
        owner_id=actor,
        visibility="audience",
    )
    item = {
        "tenant_id": tenant,
        "category_id": category,
        "product_id": pid,
        "project_id": project_id,
        "id": uuid4(),
        "decision_id": uuid4(),
        "kind": "task",
        "title": "Follow the actual G0 requirement",
        "note": "Keep the fixed native result, without private proposal text",
        "owner_id": uuid4(),
        "due_date": date(2026, 11, 1),
        "source_question_id": uuid4(),
        "source_spec_item_id": None,
    }
    ref = {field: item[field] for field in ("id", "decision_id")}
    calls = []

    def actual_project(session, context, product_id, identity, *, lock=False):
        assert context is ctx and product_id == pid and identity == project_id
        calls.append((session, lock))
        return project

    monkeypatch.setattr(sources.owner, "project", actual_project)
    return SimpleNamespace(**locals())


@pytest.mark.parametrize("typed", ["uuid_dict", "string_dict", "pydantic"])
@pytest.mark.parametrize("lock", [False, True])
def test_resolve_fixes_native_metadata_and_exact_scope_without_private_reads(case, typed, lock):
    ref = case.ref
    if typed == "string_dict":
        ref = {key: str(value) for key, value in ref.items()}
    elif typed == "pydantic":
        ref = Reference(**ref)
    session = Session([case.item])
    basis = sources.resolve(session, case.ctx, case.pid, case.project_id, ref, lock=lock)
    assert case.calls == [(session, lock)]
    assert len(session.statements) == 1 and session.groups == []
    selected = sql(session.statements[0])
    # Scope admission still locks the Project, but the native source is read-only:
    # SELECT FOR UPDATE would additionally apply its unrelated UPDATE policy.
    assert "FOR UPDATE" not in selected
    for field, value in {
        "tenant_id": case.ctx.tenant_id,
        "category_id": case.ctx.category_id,
        "product_id": case.pid,
        "project_id": case.project_id,
        "id": case.item["id"],
        "g0_decision_id": case.item["decision_id"],
    }.items():
        assert f"project_open_items.{field} = '{value}'" in selected
    assert not any(
        forbidden in selected
        for forbidden in ("proposal_decisions", "proposals", "project_open_items.status", "body")
    )
    assert set(basis) == set(case.item) - {"tenant_id"} | {"digest"}
    assert basis["due_date"] == "2026-11-01"
    assert basis["owner_id"] == str(case.item["owner_id"])
    assert basis["source_question_id"] == str(case.item["source_question_id"])
    assert basis["source_spec_item_id"] is None
    assert basis["digest"] == digest(
        {key: value for key, value in basis.items() if key != "digest"}
    )


@pytest.mark.parametrize(
    "field", ["tenant_id", "category_id", "product_id", "project_id", "id", "decision_id"]
)
def test_resolve_rejects_an_unmatched_native_identity_or_scope(case, field):
    item = {**case.item, field: uuid4()}
    with pytest.raises(DomainError) as error:
        sources.resolve(Session([item]), case.ctx, case.pid, case.project_id, case.ref)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and error.value.status == 403


@pytest.mark.parametrize("value", [None, 3, True, "not-a-uuid"])
def test_native_ref_requires_uuid_instead_of_coercing_an_unrelated_identifier(case, value):
    session = Session()
    with pytest.raises(DomainError) as error:
        sources.resolve(session, case.ctx, case.pid, case.project_id, {**case.ref, "id": value})
    assert error.value.reason == "VALIDATION_FAILED" and error.value.status == 422
    assert not session.statements and not case.calls


def test_unreadable_native_item_and_current_project_return_source_unavailable(case, monkeypatch):
    with pytest.raises(DomainError) as error:
        sources.resolve(Session([]), case.ctx, case.pid, case.project_id, case.ref)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and error.value.status == 403

    def lost_scope(*_args, **_kwargs):
        raise DomainError("FORBIDDEN_SCOPE", "Current audience was withdrawn", 403)

    monkeypatch.setattr(sources.owner, "project", lost_scope)
    session = Session()
    with pytest.raises(DomainError) as error:
        sources.resolve(session, case.ctx, case.pid, case.project_id, case.ref)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and error.value.status == 403
    assert not session.statements


def test_sources_current_excludes_legacy_status_but_rechecks_exact_native_fields(case):
    basis = sources.resolve(Session([case.item]), case.ctx, case.pid, case.project_id, case.ref)
    assert sources.sources_current(
        Session([{**case.item, "status": "legacy-completed"}]), case.ctx, case.pid, basis
    )
    assert "status" not in basis and "tenant_id" not in basis


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "A changed native title"},
        {"note": "Changed disposition"},
        {"owner_id": uuid4()},
        {"due_date": date(2026, 11, 2)},
        {"kind": "risk"},
        {"source_question_id": None, "source_spec_item_id": uuid4()},
    ],
)
def test_sources_current_reports_fixed_metadata_drift_as_source_stale(case, changes):
    basis = sources.resolve(Session([case.item]), case.ctx, case.pid, case.project_id, case.ref)
    with pytest.raises(DomainError) as error:
        sources.sources_current(Session([{**case.item, **changes}]), case.ctx, case.pid, basis)
    assert error.value.reason == "SOURCE_STALE" and error.value.status == 409


def test_saved_basis_digest_is_checked_and_a_wrapper_is_not_a_direct_basis(case):
    basis = sources.resolve(Session([case.item]), case.ctx, case.pid, case.project_id, case.ref)
    for changed in ({**basis, "digest": "0" * 64}, {**basis, "title": "Client supplied title"}):
        with pytest.raises(DomainError) as error:
            sources.sources_current(Session([case.item]), case.ctx, case.pid, changed)
        assert error.value.reason == "SOURCE_STALE" and error.value.status == 409
    session = Session()
    with pytest.raises(DomainError) as error:
        sources.sources_current(session, case.ctx, case.pid, {"g0_open_item": basis})
    assert error.value.reason == "SOURCE_STALE" and not session.statements


def test_sources_current_after_audience_loss_is_not_an_integrity_error(case, monkeypatch):
    basis = sources.resolve(Session([case.item]), case.ctx, case.pid, case.project_id, case.ref)

    def lost_scope(*_args, **_kwargs):
        raise DomainError("FORBIDDEN_SCOPE", "No current Project audience", 403)

    monkeypatch.setattr(sources.owner, "project", lost_scope)
    with pytest.raises(DomainError) as error:
        sources.sources_current(Session(), case.ctx, case.pid, basis)
    assert error.value.reason == "SOURCE_UNAVAILABLE" and error.value.status == 403


def test_workspace_batches_both_native_sources_and_exact_current_task_links(case):
    first = {**case.item, "task_id": uuid4(), "task_revision": 4, "task_state": "in_progress"}
    second = {
        **case.item,
        "id": uuid4(),
        "kind": "risk",
        "due_date": case.item["due_date"] + timedelta(days=1),
        "source_question_id": None,
        "source_spec_item_id": uuid4(),
        "task_id": None,
        "task_revision": None,
        "task_state": None,
    }
    original = deepcopy([first, second])
    session = Session([first, second])
    result = sources.workspace_items(session, case.ctx, case.pid, case.project_id)
    assert case.calls == [(session, False)] and len(session.statements) == 1
    assert [first, second] == original and not session.groups
    assert result == [
        {
            **{field: str(first[field]) for field in ("id", "decision_id", "owner_id")},
            **{field: first[field] for field in ("kind", "title", "note")},
            "due_date": first["due_date"].isoformat(),
            "source": {"kind": "question", "id": str(first["source_question_id"])},
            "task": {"id": str(first["task_id"]), "revision": 4, "state": "in_progress"},
        },
        {
            **{field: str(second[field]) for field in ("id", "decision_id", "owner_id")},
            **{field: second[field] for field in ("kind", "title", "note")},
            "due_date": second["due_date"].isoformat(),
            "source": {"kind": "spec", "id": str(second["source_spec_item_id"])},
            "task": None,
        },
    ]
    selected = sql(session.statements[0])
    assert "LEFT OUTER JOIN" in selected
    for field in ("tenant_id", "category_id", "product_id", "project_id", "owner_id", "visibility"):
        assert f"work_task_currents.{field} = work_task_versions.{field}" in selected
    for field, version_field in (
        ("version_id", "id"),
        ("task_id", "task_id"),
        ("revision", "revision"),
        ("state", "state"),
    ):
        assert f"work_task_currents.{field} = work_task_versions.{version_field}" in selected
    assert "g0_current_task.g0_open_item_id = project_open_items.id" in selected
    assert "g0_current_task.g0_decision_id = project_open_items.g0_decision_id" in selected
    assert not any(
        forbidden in selected
        for forbidden in (
            "proposal_decisions",
            "proposals",
            "project_open_items.status",
            "work_task_versions.body",
            "source_basis",
            "command",
        )
    )


def test_workspace_empty_sources_do_not_trigger_per_item_reads(case):
    session = Session([])
    assert sources.workspace_items(session, case.ctx, case.pid, case.project_id) == []
    assert len(session.statements) == 1 and case.calls == [(session, False)]
