"""Real Session/UOW + actual DTO/hash/issuer/people/Confirmation guards.

SQL row reads, concrete configuration/Source IO and DB clock are substituted;
this suite does not establish actual PostgreSQL locks, byte trust or qualification.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID
from uuid import UUID as CategoryUUID

import pytest
from psycopg.errors import DeadlockDetected, LockNotAvailable, SerializationFailure
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.change_coverage_owner import owner as people_owner
from pdos_next.domain.manufacturing_resource_owner import owner
from pdos_next.domain.manufacturing_resource_owner.relations import project
from pdos_next.domain.manufacturing_resource_owner.schemas import ResourceRequest
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Grant, Principal, Product
from pdos_next.service import Context

AT = datetime(2026, 10, 5, 8, tzinfo=UTC)
REF = {
    "artifact_id": str(UUID(int=91)),
    "expected_revision": 1,
    "line": 1,
    "quote": "synthetic exact resource requirement",
}


def loaded(s, row):
    make_transient_to_detached(row)
    s.add(row)
    return row


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("postgresql+psycopg://unused@invalid/pdos_test")
    s = Session(engine)
    s.begin()
    ctx = Context(UUID(int=1), UUID(int=2), UUID(int=2), category_id=CategoryUUID(int=1000000))
    publisher = UUID(int=7)
    pid, project_id, bid, process_id = UUID(int=4), UUID(int=5), UUID(int=3), UUID(int=9)
    resource = {"id": str(UUID(int=50)), "revision": 1, "kind": "fixture"}
    scope = {
        "purpose": "internal-prototype",
        "quantity": "10",
        "unit": "ea",
        "site": "SYN-LAB",
        "window": {
            "start": AT + timedelta(hours=1),
            "finish": AT + timedelta(hours=2),
            "original_timezone": "UTC",
        },
    }
    data = FactInput.model_validate(
        {
            "build_id": bid,
            "expected_build_revision": 1,
            "scope": scope,
            "external_id": "NOT-A-RELATION-KEY",
            "valid_from": AT - timedelta(hours=1),
            "valid_until": AT + timedelta(hours=3),
            "sources": [REF],
            "reason": "synthetic original declaration, no actual T2 qualification",
            "resources": [
                {
                    "resource": resource,
                    "purposes": [scope["purpose"]],
                    "operation_ids": ["assembly"],
                    "lifecycle": "active",
                    "sources": [REF],
                    "facts": [
                        {
                            "kind": "acceptance",
                            "purpose": scope["purpose"],
                            "operation_id": "assembly",
                            "status": "accepted",
                            "named_decision_id": UUID(int=61),
                            "actor_id": publisher,
                            "sources": [REF],
                        }
                    ],
                }
            ],
            "requirements": [
                {
                    "operation_key": "assembly",
                    "uses": [{"resource": resource, "units": "1"}],
                    "sources": [REF],
                }
            ],
        }
    )
    request = ResourceRequest.model_validate(
        {
            "scope": {"tenant_id": ctx.tenant_id, "product_id": pid, "project_id": project_id},
            "build": {"id": bid, "revision": 1},
            "process": {"id": process_id, "revision": 1},
            "execution": scope,
            "operation_key": "assembly",
            "resource": resource,
        }
    )
    people, grants = {}, {}
    product = loaded(
        s,
        Product(
            id=pid,
            tenant_id=ctx.tenant_id,
            created_at=AT,
            name="synthetic",
            purpose="synthetic resource projection",
            revision=1,
            lifecycle_epoch=1,
            status="draft",
            owner_id=ctx.requester_id,
            category_id=CategoryUUID(int=1000000),
        ),
    )
    for identity in (ctx.requester_id, publisher):
        people[identity] = loaded(
            s,
            Principal(
                id=identity,
                tenant_id=ctx.tenant_id,
                created_at=AT,
                name="synthetic",
                kind="human",
                active=True,
                access_epoch=1,
            ),
        )
        grants[identity] = loaded(
            s,
            Grant(
                id=UUID(int=100 + identity.int),
                tenant_id=ctx.tenant_id,
                created_at=AT,
                principal_id=identity,
                category_id=CategoryUUID(int=1000000),
                can_write=False,
                access_epoch=1,
                expires_at=AT + timedelta(minutes=5),
            ),
        )
    issuer = operational.configure_local_synthetic(
        engine,
        tenant_id=ctx.tenant_id,
        product_id=pid,
        project_id=project_id,
        enabled=True,
        test_marker_verified=True,
    )
    eng = {"id": str(UUID(int=8)), "revision": 1, "source_status": "current"}
    process = {
        "id": str(process_id),
        "revision": 1,
        "source_status": "current",
        "site": scope["site"],
        "operations": [
            {
                "key": "assembly",
                "resource_requirements": [{"name": "unrelated", "external_id": "NO-MATCH"}],
            }
        ],
    }
    build = SimpleNamespace(id=bid, project_id=project_id, product_id=pid, revision=1)
    reads = [{"artifact_id": REF["artifact_id"], "expected_revision": 1}]
    source_basis = {"synthetic_substituted_owner_source_guard": "a" * 64}
    fact = loaded(
        s,
        BuildOperationalFact(
            id=UUID(int=6),
            tenant_id=ctx.tenant_id,
            created_at=AT,
            product_id=pid,
            project_id=project_id,
            build_id=bid,
            build_revision=1,
            owner_id=publisher,
            visibility="category",
            issuer_key=issuer.key,
            issuer_version=issuer.version,
            issuer_epoch=issuer.epoch,
            nature="synthetic",
            external_id=data.external_id,
            series_id=UUID(int=6),
            revision=1,
            previous_id=None,
            previous_revision=None,
            state="active",
            valid_from=data.valid_from,
            valid_until=data.valid_until,
            binding=operational._binding(build, eng, process, data.scope),
            data=data.model_dump(mode="json"),
            sources=operational._sources(data),
            required_source_read_set=reads,
            source_basis=source_basis,
            fact_sha256="0" * 64,
            reason=data.reason,
        ),
    )
    fact.__dict__["fact_sha256"] = operational._fact_hash(fact)
    pointer = loaded(
        s,
        BuildOperationalCurrent(
            id=UUID(int=15),
            tenant_id=ctx.tenant_id,
            created_at=AT,
            product_id=pid,
            project_id=project_id,
            build_id=bid,
            fact_id=fact.id,
            fact_revision=1,
            epoch=1,
        ),
    )
    assets = {}
    for kind, aid, key, identity, revision, physical in operational._assets(data, ctx.tenant_id):
        assets[aid] = loaded(
            s,
            OperationalAsset(
                id=aid,
                tenant_id=ctx.tenant_id,
                created_at=AT,
                kind=kind,
                external_key=key,
                identity=identity,
                revision=revision,
                data_sha256=operational.digest(physical),
                data={"value": physical, "state": "active"},
                occupancy_epoch=1,
            ),
        )
    result = SimpleNamespace(
        s=s,
        engine=engine,
        ctx=ctx,
        publisher=publisher,
        pid=pid,
        request=request,
        data=data,
        fact=fact,
        pointer=pointer,
        assets=assets,
        people=people,
        grants=grants,
        issuer=issuer,
        reads=reads,
        source_basis=source_basis,
        process=process,
        product=product,
        epoch=1,
        io_hook=lambda: None,
        tail_hook=lambda: None,
        query_log=[],
        statements=[],
        calls=[],
    )

    def rows(statement, *args, **kwargs):
        model = statement.column_descriptions[0]["entity"]
        params = set(statement.compile().params.values())
        result.query_log.append((model.__name__, statement._for_update_arg is not None))
        result.statements.append(statement)
        result.calls.append(("row_select", model.__name__, statement._for_update_arg is not None))
        if model is Product:
            return [result.product] if result.product is not None else []
        if model is Principal:
            return [people[key] for key in people if key in params]
        if model is Grant:
            return [grants[key] for key in grants if key in params]
        if model is BuildOperationalFact:
            return [fact] if fact.id in params else []
        if model is BuildOperationalCurrent:
            return [result.pointer] if result.pointer else []
        if model is OperationalAsset:
            return [row for key, row in assets.items() if key in params]
        raise AssertionError("Unexpected substituted SQL model")

    monkeypatch.setattr(s, "scalars", rows)
    monkeypatch.setattr(s, "scalar", lambda stmt, *a, **k: next(iter(rows(stmt)), None))
    monkeypatch.setattr(owner, "clock", lambda: AT)
    monkeypatch.setattr(people_owner, "clock", lambda: AT)
    # Actual adopted people owner; row SQL is substituted, permission predicates remain.
    monkeypatch.setattr(owner, "lock_people", people_owner.lock_people)
    monkeypatch.setattr(
        operational,
        "_scope",
        lambda *a, **k: (build, eng, process, reads, request.scope, request.execution),
    )
    monkeypatch.setattr(
        operational,
        "_evidence_basis",
        lambda *a, **k: (deepcopy(reads), False, deepcopy(source_basis)),
    )
    monkeypatch.setattr(operational, "_evidence", lambda *a, **k: None)

    def evidence(*args, io=True, **kwargs):
        result.calls.append(("source_bytes", io))
        if io:
            result.io_hook()
        return {"synthetic_byte_guard": "b" * 64}, False, set()

    monkeypatch.setattr(owner.change, "_evidence", evidence)
    monkeypatch.setattr(
        owner,
        "lock_dependency_clock",
        lambda *a, **k: (
            result.calls.append(("actual_SQL_clock_substituted", result.epoch)) or result.epoch
        ),
    )

    def stamp(*args, **kwargs):
        result.tail_hook()
        return {"synthetic_SQL_clock_substituted": result.epoch}

    monkeypatch.setattr(owner, "closure_stamp", stamp)
    yield result
    s.rollback()
    s.close()
    engine.dispose()


def read(env, request=None):
    return owner.inspect_resource(env.s, env.ctx, env.pid, request=request or env.request)


def test_exact_build_relation_and_refresh_preserve_unknown_t2_and_full_source(env):
    value = read(env)
    assert value.view.state == "known" and value.view.current
    assert value.view.resources[0].acceptance == "unknown"
    assert value.view.resources[0].qualification == "unknown"
    assert value.view.execution_authorized is False
    assert value.view.negative_enumeration_complete is False
    assert value.view.nature == "synthetic"
    relation = value.view.relations[0]
    assert relation.build == env.request.build and relation.process == env.request.process
    assert relation.relation_source.id == env.fact.id
    assert relation.relation_source.position == "requirements[0].uses[0]"
    assert relation.relation_originals[0].model_dump(mode="json") == REF
    assert [v.model_dump(mode="json") for v in value.view.required_source_read_set] == env.reads
    assert value.view.valid_until == AT + timedelta(minutes=5)
    assert owner.refresh_resource(env.s, env.ctx, env.pid, value).view == value.view
    assert env.calls[0] == ("row_select", "Product", True)
    assert ("source_bytes", True) in env.calls and ("source_bytes", False) in env.calls
    assert all(lock for name, lock in env.query_log if name in {"Principal", "Grant"})


def test_no_uuid_match_from_same_external_name_or_requirement_text(env):
    request = env.request.model_copy(
        update={"resource": env.request.resource.model_copy(update={"id": UUID(int=99)})}
    )
    value = read(env, request)
    assert value.view.state == "unknown" and not value.view.resources
    assert not value.view.relations and value.view.fact is None
    assert not value.view.negative_enumeration_complete


def test_product_then_preflight_then_full_people_then_clock_then_owner_io_order(env):
    read(env)
    clock_index = next(
        index for index, item in enumerate(env.calls) if item[0] == "actual_SQL_clock_substituted"
    )
    assert env.calls[:clock_index] == [
        ("row_select", "Product", True),
        ("row_select", "BuildOperationalCurrent", False),
        ("row_select", "BuildOperationalFact", False),
        ("row_select", "Principal", True),
        ("row_select", "Grant", True),
        ("row_select", "Principal", True),
        ("row_select", "Grant", True),
    ]
    assert all(
        item[1] != "OperationalAsset" for item in env.calls[:clock_index] if item[0] == "row_select"
    )
    assert not any(item[0] == "source_bytes" for item in env.calls[:clock_index])
    for statement in env.statements:
        if statement.column_descriptions[0]["entity"] in {Principal, Grant}:
            assert statement._for_update_arg.nowait is True


def test_nowait_person_failure_is_fixed_error_and_never_unknown_or_more_io(env, monkeypatch):
    previous = env.s.scalars

    def locked(statement, *args, **kwargs):
        if statement.column_descriptions[0]["entity"] is Principal:
            raise DBAPIError(None, None, LockNotAvailable("synthetic lock unavailable"))
        return previous(statement, *args, **kwargs)

    monkeypatch.setattr(env.s, "scalars", locked)
    with pytest.raises(DomainError) as error:
        read(env)
    assert error.value.reason == "RESOURCE_RECHECK_REQUIRED" and error.value.status == 409
    assert env.calls[-1][:2] == ("row_select", "BuildOperationalFact")
    assert not any(
        item[0] in {"source_bytes", "actual_SQL_clock_substituted"} for item in env.calls
    )


@pytest.mark.parametrize("exception", [DeadlockDetected, SerializationFailure])
def test_non_55p03_db_error_propagates_for_whole_transaction_rollback(env, monkeypatch, exception):
    error = DBAPIError(None, None, exception("synthetic whole transaction failure"))
    previous = env.s.scalars

    def failed(statement, *args, **kwargs):
        if statement.column_descriptions[0]["entity"] is Principal:
            raise error
        return previous(statement, *args, **kwargs)

    monkeypatch.setattr(env.s, "scalars", failed)
    with pytest.raises(DBAPIError) as result:
        read(env)
    assert result.value is error
    assert not any(item[0] == "source_bytes" for item in env.calls)


def test_missing_root_nowait_seam_fails_configured_port_instead_of_fallback(env, monkeypatch):
    def old_signature(s, ctx, product, publisher):
        raise AssertionError("Unpatched people seam must not be called")

    monkeypatch.setattr(owner, "lock_people", old_signature)
    with pytest.raises(DomainError) as error:
        read(env)
    assert error.value.reason == "RESOURCE_PEOPLE_NOWAIT_REQUIRED" and error.value.status == 503
    assert not any(item[0] == "actual_SQL_clock_substituted" for item in env.calls)


def test_preflight_publisher_change_after_clock_cannot_add_identity_or_source_io(env, monkeypatch):
    original = owner.lock_dependency_clock

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        env.fact.__dict__["owner_id"] = UUID(int=999)
        env.fact.__dict__["fact_sha256"] = operational._fact_hash(env.fact)
        return result

    monkeypatch.setattr(owner, "lock_dependency_clock", changed)
    with pytest.raises(DomainError):
        read(env)
    assert not any(item[0] == "source_bytes" for item in env.calls)
    people_statements = [
        stmt for stmt in env.statements if stmt.column_descriptions[0]["entity"] is Principal
    ]
    assert all(UUID(int=999) not in stmt.compile().params.values() for stmt in people_statements)


@pytest.mark.parametrize("kind", ["missing", "wrong_tenant", "wrong_product"])
def test_exact_product_root_lock_not_a_scope_or_permission_grant(env, kind):
    if kind == "missing":
        env.product = None
    elif kind == "wrong_tenant":
        env.product.__dict__["tenant_id"] = UUID(int=999)
    else:
        env.product.__dict__["id"] = UUID(int=999)
    with pytest.raises(DomainError) as error:
        read(env)
    assert error.value.status == 403
    assert env.calls == [("row_select", "Product", True)]


def test_missing_current_is_unknown_not_absence_or_na(env):
    env.pointer = None
    value = read(env)
    assert value.view.state == "unknown" and not value.view.current
    assert not value.view.relations and not value.view.required_source_read_set


def test_readonly_asset_sql_has_no_tuple_wait_or_dml_and_follows_held_clock(env):
    read(env)
    clock_index = next(
        index for index, item in enumerate(env.calls) if item[0] == "actual_SQL_clock_substituted"
    )
    asset_indices = [
        index
        for index, item in enumerate(env.calls)
        if item[:2] == ("row_select", "OperationalAsset")
    ]
    assert asset_indices and all(index > clock_index for index in asset_indices)
    statements = [
        stmt for stmt in env.statements if stmt.column_descriptions[0]["entity"] is OperationalAsset
    ]
    assert len(statements) == 2  # Full owner metadata before/after byte IO.
    for statement in statements:
        assert statement.is_select and not statement.is_dml
        assert statement._for_update_arg is None
        assert statement.get_execution_options()["populate_existing"] is True
        assert statement.get_execution_options()["autoflush"] is False
        parameters = set(statement.compile().params.values())
        assert env.ctx.tenant_id in parameters and env.request.resource.id in parameters


def test_readonly_asset_helper_has_no_create_mode_or_implicit_registration(env):
    with pytest.raises(TypeError):
        owner._read_assets(
            env.s, env.ctx, operational._assets(env.data, env.ctx.tenant_id), create=True
        )
    assert not env.calls


@pytest.mark.parametrize("field", ["tenant_id", "external_key", "identity", "data_sha256", "data"])
def test_plain_asset_select_keeps_original_identity_and_hash_guards(env, field):
    asset = next(iter(env.assets.values()))
    wrong = {
        "tenant_id": UUID(int=999),
        "external_key": "c" * 64,
        "identity": {"id": str(UUID(int=999)), "kind": "fixture"},
        "data_sha256": "d" * 64,
        "data": {},
    }
    asset.__dict__[field] = wrong[field]
    with pytest.raises(DomainError):
        read(env)


def test_same_uow_asset_aba_clock_plus_two_during_source_io_cannot_return_proof(env):
    def source_io_aba():
        asset = next(iter(env.assets.values()))
        original = deepcopy(asset.data)
        asset.__dict__["data"] = {"value": {"temporary": True}, "state": "withdrawn"}
        asset.__dict__["data"] = original
        asset.__dict__["occupancy_epoch"] += 2
        env.epoch += 2  # Explicit substitution for actual same-UOW DB trigger.

    env.io_hook = source_io_aba
    with pytest.raises(DomainError):
        read(env)


def test_explicit_old_fact_has_no_current_edges_or_extended_application_ttl(env):
    env.pointer.__dict__["fact_id"] = UUID(int=999)
    raw = env.request.model_dump(mode="json")
    raw["fact"] = {"id": str(env.fact.id), "revision": 1}
    request = ResourceRequest.model_validate(raw)
    value = read(env, request)
    assert value.view.state == "historical" and not value.view.current
    assert value.view.fact_valid_until == env.fact.valid_until
    assert not value.view.relations and not value.view.resources[0].current


def test_expired_fact_remains_historical_without_extending_fact_deadline(env):
    expired = AT - timedelta(minutes=30)
    raw_data = deepcopy(env.fact.data)
    raw_data["valid_until"] = expired.isoformat()
    env.fact.__dict__["data"] = raw_data
    env.fact.__dict__["valid_until"] = expired
    env.fact.__dict__["fact_sha256"] = operational._fact_hash(env.fact)
    raw = env.request.model_dump(mode="json")
    raw["fact"] = {"id": str(env.fact.id), "revision": 1}
    value = read(env, ResourceRequest.model_validate(raw))
    assert value.view.state == "historical" and not value.view.relations
    assert value.view.fact_valid_until == expired
    assert value.view.valid_until == AT + timedelta(minutes=5)
    assert value.view.execution_authorized is False


def test_saved_read_set_must_equal_full_actual_sources_even_if_hash_matches(env):
    env.fact.__dict__["required_source_read_set"] = []
    env.fact.__dict__["fact_sha256"] = operational._fact_hash(env.fact)
    with pytest.raises(DomainError):
        read(env)


def test_actual_merge_preserves_complete_source_set_over_twenty(env):
    env.reads.extend(
        [{"artifact_id": str(UUID(int=200 + index)), "expected_revision": 1} for index in range(20)]
    )
    env.fact.__dict__["fact_sha256"] = operational._fact_hash(env.fact)
    value = read(env)
    assert len(value.view.required_source_read_set) == len(env.reads) > 20


@pytest.mark.parametrize("field", ["scope", "process", "build", "execution"])
def test_fixed_scope_configuration_and_purpose_cannot_drift(env, field):
    raw = env.request.model_dump(mode="json")
    if field == "scope":
        raw[field]["project_id"] = str(UUID(int=1000))
    elif field == "execution":
        raw[field]["purpose"] = "other-purpose"
    else:
        raw[field]["revision"] += 1
    with pytest.raises(DomainError):
        read(env, ResourceRequest.model_validate(raw))


def test_hidden_fact_discloses_only_generic_unknown(env):
    env.fact.__dict__["visibility"] = "private"
    env.fact.__dict__["fact_sha256"] = operational._fact_hash(env.fact)
    value = read(env)
    assert value.view.state == "unknown" and value.view.fact is None
    assert value.source_basis == {} and not value.view.resources
    assert not value.view.required_source_read_set and value.owner_id is None
    assert str(env.fact.id) not in str(value.view.model_dump())


def test_source_withdrawal_rejects_saved_read_and_new_read_is_unknown(env, monkeypatch):
    previous = read(env)

    def withdrawn(*args, **kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "synthetic withdrawn source")

    monkeypatch.setattr(operational, "_evidence", withdrawn)
    assert read(env).view.state == "unknown"
    with pytest.raises(DomainError):
        owner.refresh_resource(env.s, env.ctx, env.pid, previous)


@pytest.mark.parametrize("kind", ["asset", "pointer", "issuer", "clock"])
def test_aba_or_rotation_invalidates_previous_sealed_read(env, kind):
    previous = read(env)
    if kind == "asset":
        next(iter(env.assets.values())).__dict__["occupancy_epoch"] += 2
    elif kind == "pointer":
        env.pointer.__dict__["epoch"] += 2
    elif kind == "issuer":
        operational.disable_issuer(env.engine, env.issuer.key)
    else:
        env.epoch += 2
    with pytest.raises(DomainError):
        owner.refresh_resource(env.s, env.ctx, env.pid, previous)


@pytest.mark.parametrize("fault", ["principal", "grant_write", "grant_expiry", "grant_epoch"])
def test_original_publisher_pending_revocation_during_source_io_fails(env, fault):
    person, grant = env.people[env.publisher], env.grants[env.publisher]
    if fault == "grant_write":
        grant.__dict__["can_write"] = True

    def change():
        if fault == "principal":
            person.active = False
        elif fault == "grant_write":
            grant.can_write = False
        elif fault == "grant_expiry":
            grant.expires_at = AT - timedelta(seconds=1)
        else:
            grant.access_epoch += 1

    env.io_hook = change
    before = len(env.s.dispatch.do_orm_execute)
    with pytest.raises(DomainError):
        read(env)
    assert len(env.s.dispatch.do_orm_execute) == before
    assert person in env.s.dirty or grant in env.s.dirty


def test_confirmation_memory_change_during_source_io_fails_and_finally_restores(env):
    confirmation = Confirmation(id=UUID(int=777), tenant_id=env.ctx.tenant_id, consumed=True)
    env.s.add(confirmation)
    env.io_hook = lambda: setattr(confirmation, "consumed", False)
    before = len(env.s.dispatch.do_orm_execute)
    with pytest.raises(DomainError):
        read(env)
    assert not confirmation.consumed
    assert len(env.s.dispatch.do_orm_execute) == before
    assert all(name != "Confirmation" for name, _ in env.query_log)


def test_tail_rotation_runtime_and_fresh_deadline_fences(env):
    calls = 0

    def rotate_at_final_clock():
        nonlocal calls
        calls += 1
        if calls == 2:
            operational.disable_issuer(env.engine, env.issuer.key)

    env.tail_hook = rotate_at_final_clock
    with pytest.raises(DomainError):
        read(env)


def test_original_publisher_changed_after_full_source_metadata_is_rechecked(env):
    calls = 0

    def revoke_after_metadata():
        nonlocal calls
        calls += 1
        if calls == 2:
            # Substituted fresh committed row value; does not rely on dirty-row guard.
            env.people[env.publisher].__dict__["active"] = False

    env.tail_hook = revoke_after_metadata
    with pytest.raises(DomainError):
        read(env)


def test_runtime_change_in_byte_io_rejected(env):
    env.io_hook = lambda: setattr(env.engine, "_pdos_security_runtime", object())
    with pytest.raises(DomainError):
        read(env)


def test_refresh_rejects_different_uow_and_mutated_source_basis(env):
    previous = read(env)
    altered = replace(previous, source_basis={"forged": True})
    with pytest.raises(DomainError):
        owner.refresh_resource(env.s, env.ctx, env.pid, altered)
    altered_stamp = replace(previous, _stamp={"synthetic_SQL_clock_substituted": 999})
    with pytest.raises(DomainError):
        owner.refresh_resource(env.s, env.ctx, env.pid, altered_stamp)
    env.s.rollback()
    env.s.begin()
    with pytest.raises(DomainError):
        owner.refresh_resource(env.s, env.ctx, env.pid, previous)


def test_fresh_time_crossing_deadline_during_io_is_rejected(env, monkeypatch):
    env.io_hook = lambda: monkeypatch.setattr(owner, "clock", lambda: AT + timedelta(minutes=5))
    with pytest.raises(DomainError):
        read(env)


def test_untrusted_assertion_fields_not_accepted_in_request(env):
    raw = env.request.model_dump(mode="json")
    for field in ("accepted", "qualified", "complete", "issuer", "nature", "authorized"):
        with pytest.raises(ValidationError):
            ResourceRequest.model_validate({**raw, field: True})


def test_pure_projection_does_not_resolve_text_or_structural_t2_ids(env):
    resources, relations, _ = project(env.fact, env.data, env.request, current=True)
    assert resources[0].acceptance == resources[0].calibration == "unknown"
    assert relations[0].relation_source.kind == "domain"
    resources, relations, gaps = project(env.fact, env.data, env.request, current=False)
    assert not relations and not resources[0].current and gaps
