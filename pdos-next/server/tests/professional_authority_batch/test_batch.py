import ast
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.domain.professional_authority import service as actual
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.errors import DomainError
from tests.professional_authority.test_assessment import AT

from .professional_batch_harness import BatchSession, assessed, clone, install_assessment_ports


def result(function, session, **kwargs):
    try:
        return assessed(function, session, AT, **kwargs)
    except DomainError as error:
        return (error.reason, error.status, error.message)


def diff(session, monkeypatch, **kwargs):
    install_assessment_ports(monkeypatch)
    original, staged = clone(session), clone(session)
    with monkeypatch.context() as legacy:
        legacy.setattr(actual, "_current_fact_rows", lambda *args: None)
        before = result(actual.assess, original, **kwargs)
    after = result(actual.assess, staged, **kwargs)
    assert after == before
    return after, staged


def rehash(row):
    row.fact_sha256 = actual.digest(actual._material(row))


def test_complete_positive_material_roles_facts_sources_and_deadlines_match(monkeypatch):
    value, session = diff(BatchSession(), monkeypatch)
    assert value["authorized"] and value["qualified"] and len(value["fact_refs"]) == 2
    assert len(value["required_source_read_set"]) == 2
    assert (
        sum(q.column_descriptions[0]["entity"] is ProfessionalFact for q in session.statements) == 1
    )
    assert not any(model is ProfessionalFact for model, identity in session.gets)


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "revoked"),
        ("valid_until", AT),
        ("valid_from", AT + timedelta(seconds=1)),
        ("operations", ["test.run.start"]),
        ("purposes", ["different-purpose"]),
        ("role", "engineering"),
        ("nature", "synthetic"),
        ("issuer_version", "wrong-version"),
    ],
)
def test_negative_expired_withdrawn_inapplicable_and_issuer_facts_are_complete(
    field, value, monkeypatch
):
    session = BatchSession()
    row = session.rows[session.pointers[-1].fact_id]
    setattr(row, field, value)
    if field == "visibility":
        row.owner_id = uuid4()
    rehash(row)
    result, _ = diff(session, monkeypatch)
    assert result["authorized"] is False


@pytest.mark.parametrize(
    "field", ["tenant_id", "product_id", "project_id", "subject_id", "series_id", "revision"]
)
def test_mismatched_current_scope_pointer_does_not_disappear_before_fingerprint(field, monkeypatch):
    session = BatchSession()
    row = session.rows[session.pointers[-1].fact_id]
    setattr(row, field, 2 if field == "revision" else uuid4())
    rehash(row)
    value, _ = diff(session, monkeypatch)
    assert "AUTHORITY_INTEGRITY_UNKNOWN" in value["reason_codes"] and not value["authorized"]


@pytest.mark.parametrize("change", ["missing", "epoch", "duplicated_pointer", "overflow", "empty"])
def test_current_missing_duplicate_and_overflow_sets_keep_original_order_basis(change, monkeypatch):
    session = BatchSession()
    if change == "missing":
        del session.rows[session.pointers[-1].fact_id]
    elif change == "epoch":
        session.pointers[-1].epoch += 1
    elif change == "duplicated_pointer":
        session.pointers.insert(1, deepcopy(session.pointers[0]))
    elif change == "overflow":
        session.pointers.extend(deepcopy(session.pointers[0]) for _ in range(101))
    else:
        session.pointers = []
    value, after = diff(session, monkeypatch)
    if change == "overflow":
        assert len(value["fact_refs"]) > 100
    if change == "empty":
        assert not any(
            q.column_descriptions[0]["entity"] is ProfessionalFact for q in after.statements
        )


def test_source_failure_keeps_later_negative_complete_epoch_basis(monkeypatch):
    def fail(*args):
        raise DomainError("SOURCE_UNAVAILABLE", "synthetic source failure")

    install_assessment_ports(monkeypatch, fail)
    session = BatchSession()
    other = clone(session)
    other.pointers[-1].epoch += 1
    with monkeypatch.context() as legacy:
        legacy.setattr(actual, "_current_fact_rows", lambda *args: None)
        old = result(actual.assess, clone(session))
        old_changed = result(actual.assess, clone(other))
    new = result(actual.assess, clone(session))
    new_changed = result(actual.assess, clone(other))
    assert old == new and old_changed == new_changed
    assert old["facts_revision"] != old_changed["facts_revision"]
    assert old["authorized"] is new["authorized"] is False


@pytest.mark.parametrize("tracked", ["new", "dirty", "deleted"])
def test_pending_fact_uses_original_get_position_and_never_refreshes_revoke(tracked, monkeypatch):
    session = BatchSession()
    row = session.rows[session.pointers[-1].fact_id]
    row.state = "revoked"
    rehash(row)
    getattr(session, tracked).append(row)
    value, after = diff(session, monkeypatch)
    assert value["qualified"] is False
    assert not any(q.column_descriptions[0]["entity"] is ProfessionalFact for q in after.statements)
    assert [identity for model, identity in after.gets if model is ProfessionalFact] == [
        p.fact_id for p in after.pointers
    ]
    assert after.rows[row.id].state == "revoked"


@pytest.mark.parametrize(
    "field", ["sources", "operations", "purposes", "source_basis", "required_source_read_set"]
)
def test_untracked_json_mutation_falls_back_without_refresh_or_resealing(field, monkeypatch):
    session = BatchSession()
    row = session.rows[session.pointers[-1].fact_id]
    value = getattr(row, field)
    if isinstance(value, list):
        value.append("synthetic-untracked")
    else:
        value["synthetic-untracked"] = True
    assert session.dirty == []
    before = deepcopy(value)
    result, after = diff(session, monkeypatch)
    assert "AUTHORITY_INTEGRITY_UNKNOWN" in result["reason_codes"]
    assert getattr(after.rows[row.id], field) == before
    assert not any(q.column_descriptions[0]["entity"] is ProfessionalFact for q in after.statements)


def test_real_no_connect_identity_map_proves_plain_json_mutation_is_not_dirty():
    source = BatchSession()
    fact = deepcopy(next(iter(source.rows.values())))
    make_transient_to_detached(fact)
    with Session() as session:
        loaded = session.merge(fact, load=False)
        loaded.operations.append("synthetic-untracked")
        assert not session.dirty and inspect(loaded).persistent
        assert actual._current_fact_rows(session, [SimpleNamespace(fact_id=loaded.id)]) is None
        assert "synthetic-untracked" in loaded.operations


def test_loaded_incomplete_or_expired_fact_avoids_implicit_metadata_select():
    source = BatchSession()
    fact = deepcopy(next(iter(source.rows.values())))
    make_transient_to_detached(fact)
    with Session() as session:
        loaded = session.merge(fact, load=False)
        session.expire(loaded, ["sources"])
        assert actual._current_fact_rows(session, [SimpleNamespace(fact_id=loaded.id)]) is None
        assert "sources" not in inspect(loaded).dict


def test_retained_original_set_and_new_independent_duty_keep_exact_fingerprint(monkeypatch):
    session = BatchSession()
    original_ids = [{"id": str(p.fact_id)} for p in session.pointers]
    extra = deepcopy(session.rows[session.pointers[0].fact_id])
    extra.id = uuid4()
    extra.series_id = extra.id
    extra.external_id = "independent"
    extra.operations = ["npi.work_instruction.record"]
    extra.purposes = ["independent"]
    rehash(extra)
    session.rows[extra.id] = extra
    session.identity_map[extra.id] = extra
    pointer = deepcopy(session.pointers[0])
    pointer.id = uuid4()
    pointer.fact_id = extra.id
    pointer.series_id = extra.id
    pointer.external_id = extra.external_id
    session.pointers.append(pointer)
    value, after = diff(session, monkeypatch, retained_fact_refs=original_ids)
    assert value["authorized"] is True and len(value["fact_refs"]) == 2
    query = next(
        q for q in after.statements if q.column_descriptions[0]["entity"] is ProfessionalFact
    )
    assert set(query._where_criteria[0].right.value) == set(session.rows)


def test_retained_untracked_inapplicable_hash_error_still_raises_original_code(monkeypatch):
    session = BatchSession()
    row = session.rows[session.pointers[0].fact_id]
    row.operations.append("synthetic-untracked")
    row.role = "manufacturing"
    # Leaving original hash deliberately invalid proves the fallback preserves
    # retained first-pass _check_pointer failure, before any _evidence call.
    value, _ = diff(
        session, monkeypatch, retained_fact_refs=[{"id": str(session.pointers[-1].fact_id)}]
    )
    assert value[0] == "AUTHORITY_INTEGRITY_UNKNOWN"


def test_compile_bulk_is_full_orm_ids_only_without_active_scope_or_outer_limit():
    ids = [uuid4(), uuid4()]
    for model in (ProfessionalFact,):
        query = (
            select(model)
            .where(model.id.in_(ids))
            .execution_options(populate_existing=True, autoflush=False)
        )
        compiled = str(query.compile(dialect=PGDialect_psycopg()))
        assert "IN (__[POSTCOMPILE_id_1])" in compiled
        assert str(ids[0]) not in compiled and query._limit_clause is None
        assert query._for_update_arg is None and len(query._where_criteria) == 1
        assert query.column_descriptions[0]["entity"] is model


def test_actual_binding_assess_calls_helper_and_evidence_keeps_original_order():
    tree = ast.parse(open(actual.__file__).read())
    nodes = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert actual._current_fact_rows.__module__ == actual.__name__
    assert actual.assess.__globals__["_current_fact_rows"] is actual._current_fact_rows
    helper_calls = [
        node
        for node in ast.walk(nodes["assess"])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_current_fact_rows"
    ]
    assert len(helper_calls) == 1
    evidence_calls = [
        node
        for node in ast.walk(nodes["_evidence"])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert any(node.func.attr == "get" for node in evidence_calls)
    assert not any(
        isinstance(node, ast.Name) and node.id == "_batch_identity_rows"
        for node in ast.walk(nodes["_evidence"])
    )
