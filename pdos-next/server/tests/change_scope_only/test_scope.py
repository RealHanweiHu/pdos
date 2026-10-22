"""Real helper and SQLAlchemy Session ancestry; owner IO is explicitly synthetic.

No DB/HTTP/current qualification is exercised. Root applies the patch before
running these imports against actual source. Our candidate runner is separate.
"""

import ast
import inspect
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import pytest
from quality_issues.helpers import NOW, fixed_run, source, uid
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.domain.change_execution import service as change
from pdos_next.domain.quality_execution import service as quality
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.quality_issues.rules import failure_ref
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Principal, Product
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.service import Context, digest


@pytest.fixture
def case(monkeypatch):
    engine = create_engine("postgresql+psycopg://")
    session = Session(engine)
    session.begin()  # Actual root transaction; no connection is acquired.
    actor = uid("scope-reader")
    run = fixed_run()
    failure = failure_ref(VerifiedRun(run=run, nature="synthetic"), run.measurements[0].id)
    capa_id = uuid4()
    issue = Issue.model_validate(
        {
            "id": str(uuid4()),
            "revision": 4,
            "scope": run.scope.model_dump(mode="json"),
            "audience": [f"private:{actor}"],
            "title": "Synthetic scope only",
            "status": "actioning",
            "failures": [failure.model_dump(mode="json")],
            "capa": {
                "id": str(capa_id),
                "hypotheses": [{"text": "Unproven", "sources": [source().model_dump(mode="json")]}],
                "actions": [
                    {
                        "id": str(uuid4()),
                        "kind": "corrective",
                        "text": "Planned",
                        "executor_id": str(actor),
                    }
                ],
                "requirement": {
                    "method": "Separate actual verification",
                    "acceptance": "Fixed affected pairs pass",
                    "observation_until": (NOW + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [failure.identity],
                },
            },
        }
    )
    ctx = Context(run.scope.tenant_id, actor, actor, category_id=CategoryUUID(int=1000000))
    row = QualityIssueVersion(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        product_id=run.scope.product_id,
        project_id=run.scope.project_id,
        issue_id=issue.id,
        revision=issue.revision,
        owner_id=actor,
        writer_id=actor,
        visibility="private",
        purpose="fixed-purpose",
        status=issue.status,
        operation="quality.capa.draft",
        issue_snapshot=issue.model_dump(mode="json"),
        snapshot_sha256=digest(issue.model_dump(mode="json")),
    )
    pointer = QualityIssueCurrent(
        tenant_id=ctx.tenant_id,
        product_id=row.product_id,
        project_id=row.project_id,
        issue_id=row.issue_id,
        issue_version_id=row.id,
        issue_revision=row.revision,
        epoch=4,
    )
    access = {
        "product_id": row.product_id,
        "tenant_id": ctx.tenant_id,
        "revision": 1,
        "status": "active",
        "owner_id": actor,
        "person_id": actor,
        "kind": "human",
        "active": True,
        "person_epoch": 1,
        "grant_id": uuid4(),
        "can_write": True,
        "grant_epoch": 1,
        "expires_at": NOW + timedelta(hours=1),
    }
    state = {
        "rows": [row],
        "pointers": [pointer],
        "latest": [row],
        "acl": [access],
        "queries": [],
        "hook": lambda kind: None,
    }

    def scalars(statement):
        model = statement.column_descriptions[0]["entity"]
        assert model in {QualityIssueVersion, QualityIssueCurrent}
        assert statement.get_execution_options() == {"populate_existing": True, "autoflush": False}
        assert statement._limit_clause.value == 2
        kind = "row" if model is QualityIssueVersion else "pointer"
        if kind == "row" and " >= " in str(statement):
            kind = "latest"
        state["queries"].append((kind, statement))
        state["hook"](kind)
        return state[{"row": "rows", "pointer": "pointers", "latest": "latest"}[kind]]

    def execute(statement):
        assert statement.get_execution_options()["autoflush"] is False
        state["queries"].append(("acl", statement))
        state["hook"]("acl")
        return SimpleNamespace(mappings=lambda: deepcopy(state["acl"]))

    monkeypatch.setattr(session, "scalars", scalars)
    monkeypatch.setattr(session, "execute", execute)
    monkeypatch.setattr(quality, "now", lambda: NOW)

    def forbidden(*args, **kwargs):
        raise AssertionError("Scope derivation cannot attest a deep proof")

    for name in ("_view", "_result", "source_basis"):
        monkeypatch.setattr(quality, name, forbidden)
    monkeypatch.setattr(quality.policy, "assess", forbidden)
    monkeypatch.setattr(quality.professional, "assess", forbidden)
    value = SimpleNamespace(
        s=session,
        engine=engine,
        ctx=ctx,
        row=row,
        pointer=pointer,
        issue=issue,
        access=access,
        state=state,
        scope=run.scope,
        issue_ref=Ref(id=issue.id, revision=4, kind="issue"),
        capa_ref=Ref(id=issue.id, revision=4, kind="capa", key=str(capa_id)),
    )
    try:
        yield value
    finally:
        session.close()
        engine.dispose()


def read(case, ref=None):
    return quality._change_scope_for_change(
        case.s, case.ctx, case.row.product_id, ref or case.issue_ref
    )


@pytest.mark.parametrize("kind", ["issue", "capa"])
def test_scope_only_returns_no_attestation_and_reads_fresh_compound_pointer(case, kind):
    assert read(case, getattr(case, f"{kind}_ref")) == (case.scope, "fixed-purpose")
    assert [name for name, _ in case.state["queries"]] == ["acl", "row", "pointer", "latest", "acl"]
    query = next(q for name, q in case.state["queries"] if name == "pointer")
    params = set(query.compile().params.values())
    assert {case.ctx.tenant_id, case.row.product_id, case.row.project_id, case.issue.id} <= params


def test_default_seed_does_not_read_bridge_or_cache_across_calls(case):
    assert change._scope_seed(
        case.s, case.ctx, case.row.product_id, (case.issue_ref, case.capa_ref)
    ) == (
        case.scope,
        "fixed-purpose",
    )
    assert len(case.state["queries"]) == 10
    change._scope_seed(case.s, case.ctx, case.row.product_id, (case.issue_ref, case.capa_ref))
    assert len(case.state["queries"]) == 20


@pytest.mark.parametrize(
    "field", ["tenant_id", "product_id", "issue_id", "revision", "owner_id", "visibility"]
)
def test_wrong_fixed_row_or_private_owner_refused(case, field):
    setattr(
        case.row,
        field,
        9 if field == "revision" else "unknown" if field == "visibility" else uuid4(),
    )
    with pytest.raises(DomainError, match="固定问题") as error:
        read(case)
    assert error.value.reason == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("group", ["rows", "pointers"])
def test_missing_or_ambiguous_fixed_rows_current_fail_closed(case, count, group):
    case.state[group] = case.state[group] * count
    with pytest.raises(DomainError):
        read(case)


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "product_id",
        "project_id",
        "issue_id",
        "issue_version_id",
        "issue_revision",
        "epoch",
    ],
)
def test_current_compound_identity_must_match_exact_fixed_row(case, field):
    setattr(
        case.pointer, field, 0 if field == "epoch" else 7 if field == "issue_revision" else uuid4()
    )
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "RECHECK_REQUIRED"


@pytest.mark.parametrize("field", ["id", "revision", "status", "scope", "audience", "sha"])
def test_snapshot_full_digest_and_header_checked(case, field):
    body = deepcopy(case.row.issue_snapshot)
    if field == "sha":
        case.row.snapshot_sha256 = "0" * 64
    else:
        body[field] = {
            "id": str(uuid4()),
            "revision": 9,
            "status": "triaged",
            "scope": {**body["scope"], "project_id": str(uuid4())},
            "audience": [f"private:{uuid4()}"],
        }[field]
        case.row.issue_snapshot, case.row.snapshot_sha256 = body, digest(body)
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "INTEGRITY_MISMATCH"


@pytest.mark.parametrize(
    "kind,key", [("issue", "arbitrary"), ("capa", None), ("capa", "wrong"), ("bom", None)]
)
def test_exact_ref_semantics(case, kind, key):
    with pytest.raises(DomainError) as error:
        read(case, Ref(id=case.issue.id, revision=4, kind=kind, key=key))
    assert error.value.reason == "FIXED_REFERENCE_MISMATCH"


@pytest.mark.parametrize(
    "field,value",
    [
        ("active", False),
        ("kind", "ai"),
        ("expires_at", NOW),
        ("tenant_id", None),
        ("product_id", None),
        ("person_id", None),
    ],
)
def test_current_acl_or_exact_deadline_refused(case, field, value):
    case.access[field] = value
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_acl_aba_after_current_read_refused(case):
    def hook(kind):
        if kind == "pointer":
            case.access["grant_epoch"] = 3

    case.state["hook"] = hook
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_expiry_after_all_io_refused(case, monkeypatch):
    ticks = iter([NOW, NOW, case.access["expires_at"]])
    monkeypatch.setattr(quality, "now", lambda: next(ticks))
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize(
    "model", [QualityIssueVersion, QualityIssueCurrent, Product, Principal, Grant]
)
def test_pending_local_changes_disable_scope_derivation(case, model):
    case.s.add(model(id=uuid4(), tenant_id=case.ctx.tenant_id))
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "RECHECK_REQUIRED" and not case.state["queries"]


@pytest.mark.parametrize("change_at", ["engine", "root", "savepoint", "caller"])
def test_uow_engine_ancestry_caller_change_refused(case, change_at, monkeypatch):
    def hook(kind):
        if kind != "pointer":
            return
        if change_at == "engine":
            monkeypatch.setattr(case.s, "get_bind", lambda: object())
        elif change_at == "root":
            case.s.rollback()
            case.s.begin()
        elif change_at == "savepoint":
            case.s.begin_nested()
        else:
            object.__setattr__(case.ctx, "actor_id", uuid4())

    case.state["hook"] = hook
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "FACT_CALLER_UOW_CHANGED"


def test_non_session_cannot_derive_scope(case):
    with pytest.raises(DomainError) as error:
        quality._change_scope_for_change(object(), case.ctx, case.row.product_id, case.issue_ref)
    assert error.value.reason == "FACT_ACTIVE_SESSION_REQUIRED"


def test_custom_issue_loader_keeps_full_old_path_even_if_default_function(case, monkeypatch):
    calls = []

    def configured(s, ctx, pid, identity, revision):
        calls.append((identity, revision))
        return case.row, {
            "issue_id": str(identity),
            "revision": revision,
            "purpose": case.row.purpose,
        }

    change.configure_issue_loader(case.engine, configured)
    assert change._scope_seed(
        case.s, case.ctx, case.row.product_id, (case.issue_ref, case.capa_ref)
    ) == (
        case.scope,
        "fixed-purpose",
    )
    assert calls == [(case.issue.id, 4)] and not case.state["queries"]
    change.configure_issue_loader(case.engine, quality.get_issue_for_change)
    monkeypatch.setattr(
        quality, "_change_scope_for_change", lambda *args: pytest.fail("explicit loader bypassed")
    )
    monkeypatch.setattr(
        quality, "_human", lambda *args, **kwargs: pytest.fail("full explicit port invoked")
    )
    with pytest.raises(pytest.fail.Exception, match="full explicit port invoked"):
        change._scope_seed(case.s, case.ctx, case.row.product_id, (case.issue_ref,))


@pytest.mark.parametrize("function", [change._load, change.prepare_capture])
def test_all_seed_consumers_still_run_initial_and_final_complete_owner_reads(function):
    parsed = ast.parse(inspect.getsource(function))
    calls = [
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(parsed)
        if isinstance(node, ast.Call)
    ]

    def line(name):
        return min(n for n, fn in calls if fn == name)

    assert (
        line("_scope_seed")
        < line("_authority")
        < line("OwnerReader")
        < line("_evidence")
        < line("_refresh")
    )
    assert "fresh = OwnerReader" in inspect.getsource(change._refresh)
    assert "current = fresh.resolve(obj.ref)" in inspect.getsource(change._refresh)


def test_list_history_uses_scope_only_seed_without_complete_seed_walk():
    source = inspect.getsource(change.list_changes)
    assert "_scope_seed(" in source and "_seed(s, ctx, product_id" not in source


@pytest.mark.parametrize("variant", ["missing", "future", "wrong_id"])
def test_current_pointer_cannot_rollback_same_issue_series(case, variant):
    case.state["latest"] = {
        "missing": [],
        "future": [case.row, SimpleNamespace(id=uuid4(), revision=5)],
        "wrong_id": [SimpleNamespace(id=uuid4(), revision=4)],
    }[variant]
    with pytest.raises(DomainError) as error:
        read(case)
    assert error.value.reason == "RECHECK_REQUIRED"
    query = next(q for name, q in case.state["queries"] if name == "latest")
    assert {case.ctx.tenant_id, case.row.product_id, case.row.project_id, case.issue.id, 4} <= set(
        query.compile().params.values()
    )


def test_lifecycle_bookkeeping_allowed_without_clearing_confirmation(case):
    from pdos_next.models import Confirmation

    product = Product(
        id=case.row.product_id,
        tenant_id=case.ctx.tenant_id,
        lifecycle_epoch=1,
        category_id=CategoryUUID(int=1000000),
    )
    make_transient_to_detached(product)
    case.s.add(product)
    product.lifecycle_epoch = 2
    confirmation = Confirmation(id=uuid4(), tenant_id=case.ctx.tenant_id)
    case.s.add(confirmation)
    assert read(case) == (case.scope, "fixed-purpose")
    assert product in case.s.dirty and confirmation in case.s.new
