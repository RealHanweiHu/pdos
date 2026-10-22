"""No-connect tests of actual public command seams; owner SQL/bytes are explicit substitutes.

These tests cannot attest real professional facts, persisted atom/RLS or a Pilot.
"""

import ast
import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, inspect
from sqlalchemy.orm import make_transient_to_detached

from pdos_next import command_handlers, contracts, lifecycle_catalog, models
from pdos_next import service as common
from pdos_next.domain.manufacturing_baseline import api, rules, schema_proposal, schemas, service
from pdos_next.errors import DomainError

from .test_preparation import frame

SERVER = Path(__file__).resolve().parents[2]

CANONICAL_SCHEMA_BASELINE_JSON = (
    '{\n  "pdos_next/schemas/change_control/__init__.py": "8782cb2a128599a5f'
    '6b1021092c61ebc3cb374a6491ffc63aa4d909cac266a98",\n  "pdos_next/schemas'
    '/change_control/contracts.py": "0e326e0762fa1e2aa275f12b7e39b82635fa6a'
    '712aa27c582104fe49b072654a",\n  "pdos_next/schemas/discovery/__init__.p'
    'y": "cd544e445e6b214900c3e98381069c97aafa221f2355a5d254c684f5ef0f9e91"'
    ',\n  "pdos_next/schemas/discovery/contracts.py": "7984b38309958d115c621'
    'c0fc3a255ecc53c16688464c09d09a33737e5bd73ca",\n  "pdos_next/schemas/man'
    'ufacturing_trials/__init__.py": "e5096d3a2e9d6e2dae95d0f55faf8ee1ba749'
    'fc32277815b06d62a2a9910e7dc",\n  "pdos_next/schemas/manufacturing_trial'
    's/contracts.py": "8056ad6dcb9846620313f0ca41bc300f29faa4b356f437f8c379'
    '3fc06ee28422",\n  "pdos_next/schemas/model_configuration/__init__.py": '
    '"3dbfb6c4b4ee4a848b70b8bc591a2e0adf766085184e86ee5a2ee9d9a6e3a2a9",\n  '
    '"pdos_next/schemas/model_configuration/dto.py": "9af27f92bd241e587a9c6'
    '62741d24053d5d49bc81b0d43a23ebc463c188d7349",\n  "pdos_next/schemas/pla'
    'nning/__init__.py": "f0dc71b3ef368bf75c3510faf6ff5909cc0e2c200dde2ec3b'
    'cc4d1ba9115740f",\n  "pdos_next/schemas/planning/plan.py": "c98ac6c3651'
    '64c293663afbb603c52f0b3e162cfd29979f2da6eb47f5d39217b",\n  "pdos_next/s'
    'chemas/products/definitions.py": "591c8e070a1d36e146da212cb266e055ed51'
    'de553183b1e6364af372b5f57424",\n  "pdos_next/schemas/products/variants.'
    'py": "903b6fc4741c6804cc04dac507825c0f4b54ba0810ebe243cf79c03cdf2501aa'
    '",\n  "pdos_next/schemas/quality_issues/__init__.py": "4412a5783dd9975e'
    '04ad78569fff2c5aca8e83e7bd36dc439690eda1cefad0b1",\n  "pdos_next/schema'
    's/quality_issues/contracts.py": "ea567a91cffb6cf824dbeaac4d9202a63121a'
    '2cb8d17968267295e95034f8aea",\n  "pdos_next/schemas/resource_readiness/'
    '__init__.py": "7d90a63e154b7b5376b31211bbdfcb710624abfaaa4944729f4ad20'
    'e127b2a64",\n  "pdos_next/schemas/resource_readiness/contracts.py": "56'
    '3b181ad3e4051a6360e61f701223364cdb5d53087ff499abfd275d877dd871",\n  "pd'
    'os_next/schemas/supply_cost/__init__.py": "44abfc6833aa379358f095310a0'
    '38b38451e3f48e7d7c37b0dc5981314d77a5f",\n  "pdos_next/schemas/supply_co'
    'st/dto.py": "539f725a0c39df2ebea96ec32c6af8ac332ab99d45f54219c086cdad9'
    'c04f3e3",\n  "pdos_next/schemas/verification/__init__.py": "9c5d73deba8'
    '6ef0ba3535f8f8ac6b350382e0c0a4a323283e80a4b401f89a504",\n  "pdos_next/s'
    'chemas/verification/contracts.py": "5262b95c950a20625da5abb54b4c47dc5e'
    '77bb790f97518ca21cd3c422039734"\n}'
)


def phase_frame(monkeypatch, operation="npi.work_instruction.record"):
    f = frame(operation)
    product = models.Product(
        id=f.pid,
        tenant_id=f.tenant,
        owner_id=f.actor,
        name="pure",
        revision=4,
        category_id=CategoryUUID(int=1000000),
    )
    make_transient_to_detached(product)
    f.s.add(product)
    service.configure(f.engine)
    authority = {"valid_until": (datetime.now(UTC) + timedelta(minutes=2)).isoformat()}
    bound = service.Bound(
        SimpleNamespace(purpose="precise source-bound purpose"),
        None,
        None,
        {"status": "draft", "input": rules.semantic(f.payload)},
        [],
        {"explicit_owner_substitute": True},
        authority,
        None,
        {},
        "test-runtime",
    )
    monkeypatch.setattr(service, "_runtime", lambda s: "test-runtime")
    monkeypatch.setattr(service, "_load", lambda *a, **k: bound)
    monkeypatch.setattr(service, "_cas", lambda *a: None)
    monkeypatch.setattr(service, "_refresh", lambda *a: bound)
    return f, product, bound


@pytest.mark.parametrize("op", list(schemas.PAYLOADS))
def test_actual_closed_command_registries_and_event_families(op):
    assert command_handlers.handler(op) is service
    assert contracts.PAYLOADS[op] is schemas.PAYLOADS[op]
    assert op in command_handlers.T1_OPERATIONS
    assert op in command_handlers.PHASED_MATERIAL_OPERATIONS
    assert op in command_handlers.LIVE_CONSUMPTION_OPERATIONS
    assert op not in command_handlers.T2_OPERATIONS
    assert common.EVENTS[op] == f"{schemas.KINDS[op]}.recorded"


def test_canonical_pilot_is_native_and_draft_never_authorizes_it():
    from pdos_next.domain.manufacturing_trials import native_service

    assert command_handlers.handler("npi.pilot.create") is native_service
    assert command_handlers.handler("npi.pilot.create") is not service
    assert "npi.pilot.create" not in schemas.PAYLOADS
    assert "npi.pilot.create" not in command_handlers.T2_OPERATIONS
    with pytest.raises(DomainError) as error:
        service.qualified_pilot_baseline()
    assert (error.value.status, error.value.reason) == (
        503,
        "MANUFACTURING_BASELINE_RELEASE_REQUIRED",
    )


@pytest.mark.parametrize("op", list(schemas.PAYLOADS))
def test_public_once_preview_has_actual_phase_and_stable_save_clock(monkeypatch, op):
    f, product, bound = phase_frame(monkeypatch, op)
    prepared = service.prepare_preview(f.s, f.ctx, f.command, product, f.payload)
    result = service.preview_prepared(f.s, f.ctx, f.command, product, f.payload, prepared)
    assert result["operation"] == op
    assert result["after"]["status"] == "draft"
    assert result["after"]["id"] is result["after"]["created_at"] is None
    assert result["after"]["time_policy"] == "server_on_save"
    with pytest.raises(DomainError, match="准备阶段"):
        service.preview_prepared(f.s, f.ctx, f.command, product, f.payload, prepared)


def test_preview_retains_post_owner_fresh_deadline(monkeypatch):
    f, product, bound = phase_frame(monkeypatch)
    phase = service.prepare_preview(f.s, f.ctx, f.command, product, f.payload)

    def expired(*args):
        service._deadline(bound.authority, datetime.now(UTC) + timedelta(minutes=10))

    monkeypatch.setattr(service, "_refresh", expired)
    with pytest.raises(DomainError):
        service.preview_prepared(f.s, f.ctx, f.command, product, f.payload, phase)
    assert phase.used is True


@pytest.mark.parametrize("change", ["key", "payload", "reads", "scope"])
def test_public_preview_phase_cannot_change_original_material(monkeypatch, change):
    f, product, bound = phase_frame(monkeypatch)
    phase = service.prepare_preview(f.s, f.ctx, f.command, product, f.payload)
    changes = {
        "key": {"idempotency_key": str(uuid4())},
        "payload": {"payload": {**f.command.payload, "reason": "changed"}},
        "reads": {"source_read_set": []},
        "scope": {"product_id": uuid4()},
    }
    with pytest.raises(DomainError):
        service.preview_prepared(
            f.s, f.ctx, f.command.model_copy(update=changes[change]), product, f.payload, phase
        )


@pytest.mark.parametrize("op", list(schemas.PAYLOADS))
def test_actual_common_consumes_full_phase_callback_signature_and_first_clock(monkeypatch, op):
    f, product, bound = phase_frame(monkeypatch, op)
    phase, review = service.prepare_write_review(f.s, f.ctx, f.command, product, f.payload)
    # Real ORM Confirmation history; SELECT itself is an explicit no-connect substitute.
    f.proof.snapshot = deepcopy(review)
    # restore immutable proof baseline after creating the real preview substitute.
    from sqlalchemy.orm.attributes import set_committed_value

    set_committed_value(f.proof, "snapshot", deepcopy(review))
    f.s.scalar = lambda q: f.proof
    binding, marker = common.consume_material_confirmation(
        f.s,
        f.ctx,
        f.command,
        product,
        f.payload,
        service,
        prepared_review=review,
        write_phase=phase,
    )
    assert f.proof.consumed is True
    assert inspect(f.proof).attrs.consumed.history.deleted == [False]
    live = service._host(f.s).require_live(
        f.s,
        f.ctx,
        f.command,
        f.payload,
        service,
        f.proof,
        binding=binding,
        marker=marker,
    )
    assert live.consumed_at <= datetime.now(UTC) < live.expires_at
    assert live.proof_id == f.proof.id
    assert phase.used is False  # Consumption is not applying a prepared write.


def test_public_read_dto_preserves_unknown_and_rejects_forged_qualification():
    raw = {
        "schema_version": service.SCHEMA_VERSION,
        "versions": [],
        "has_more": False,
        "unavailable_count": 0,
        "qualification": "unknown",
        "manufacturing_release": None,
        "negative_enumeration_complete": False,
    }
    assert schemas.PreparationReading.model_validate(raw).manufacturing_release is None
    for field, value in (
        ("qualification", "ready"),
        ("manufacturing_release", {}),
        ("negative_enumeration_complete", True),
        ("has_more", "false"),
    ):
        with pytest.raises(ValidationError):
            schemas.PreparationReading.model_validate({**raw, field: value})


def test_api_registers_selected_read_and_only_common_command_inputs_no_write_route():
    app = FastAPI()
    api.register_routes(app, None, Depends(lambda: None))
    routes = [r for r in app.routes if "manufacturing-preparations" in r.path]
    assert len(routes) == 3
    assert [(r.path, r.methods) for r in routes] == [
        ("/v1/categories/{category_id}/products/{product_id}/manufacturing-preparations", {"GET"}),
        (
            "/v1/categories/{category_id}/products/{product_id}/manufacturing-preparations/{kind}/{object_id}",
            {"GET"},
        ),
        (
            "/v1/categories/{category_id}/products/{product_id}/manufacturing-preparations/inputs",
            {"POST"},
        ),
    ]
    with pytest.raises(DomainError):
        from starlette.requests import Request

        api._query(
            Request({"type": "http", "query_string": b"project_id=a&project_id=b"}), {"project_id"}
        )


def test_all_new_tables_full_catalog_guard_and_lifecycle_triggers():
    sql = "\n".join(schema_proposal.proposed_sql())
    for table in schema_proposal.TABLES:
        assert lifecycle_catalog.COVERED_COLUMNS[table.name] == tuple(c.name for c in table.columns)
        assert table.name in lifecycle_catalog.GUARDED
        assert f'ON "{table.name}" FOR EACH ROW EXECUTE FUNCTION lifecycle_reference_gate()' in sql
    assert (
        "input_snapshot"
        in lifecycle_catalog.COVERED_COLUMNS[service.PreparationVersion.__tablename__]
    )
    assert (
        "source_basis"
        in lifecycle_catalog.COVERED_COLUMNS[service.PreparationVersion.__tablename__]
    )


def test_new_atom_reciprocal_scoped_proof_and_family_receipt_does_not_replace_old():
    sql = schema_proposal.GUARDS
    assert (
        "OLD.consumed IS DISTINCT FROM false" in sql and "NEW.consumed IS DISTINCT FROM true" in sql
    )
    assert "One transitioned preparation proof requires one new target" in sql
    assert "to_jsonb(NEW)-'consumed'" in sql
    assert "OR NEW.subject_type IN" in sql
    assert "Preparation proof history is retained" in sql
    assert "CREATE OR REPLACE" not in sql
    assert "xmin" not in sql and "pg_current_xact" not in sql
    for table in schema_proposal.TABLES:
        assert "manufacturing" in table.name
    assert any(
        isinstance(c, UniqueConstraint)
        and tuple(c.columns.keys()) == ("tenant_id", "shared_proof_id")
        for c in service.PreparationVersion.__table__.constraints
    )


def test_archived_migration28_retains_static_frozen_sql():
    path = SERVER / "migrations/archive/pre-s0/versions/0028_manufacturing_preparation.py"
    spec = importlib.util.spec_from_file_location("owned_manufacturing_migration28", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "next_0028" and module.down_revision == "next_0027"
    assert not any("CASCADE" in v for v in module.DOWNGRADE_SQL)
    assert any("Retained manufacturing preparation" in v for v in module.DOWNGRADE_SQL)
    assert not any("CREATE OR REPLACE" in v for v in module.UPGRADE_SQL)
    assert module.DOWNGRADE_SQL[0] == (
        "LOCK TABLE products,confirmations,action_receipts,request_keys,audit_entries,"
        "outbox_events,"
        "manufacturing_preparation_versions,manufacturing_preparation_currents,"
        "manufacturing_baseline_document_links IN SHARE ROW EXCLUSIVE MODE"
    )
    for table in schema_proposal.TABLES:
        assert f"EXISTS(SELECT 1 FROM {table.name})" in module.DOWNGRADE_SQL[1]
        assert any(f"CREATE TABLE {table.name}" in sql for sql in module.UPGRADE_SQL)
    assert "FROM confirmations WHERE operation IN" in module.DOWNGRADE_SQL[1]
    assert "FROM action_receipts WHERE operation IN" in module.DOWNGRADE_SQL[1]
    assert "OR subject_type IN" in module.DOWNGRADE_SQL[1]
    imports = [
        n.module for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.ImportFrom)
    ]
    assert imports == ["alembic", "sqlalchemy"]
    tree = ast.parse(path.read_text())
    for name, collection in (("upgrade", "UPGRADE_SQL"), ("downgrade", "DOWNGRADE_SQL")):
        function = next(node for node in tree.body if getattr(node, "name", None) == name)
        loop = next(node for node in function.body if isinstance(node, ast.For))
        assert ast.unparse(loop.iter) == collection
        assert ast.unparse(loop.body[0]) == "op.execute(text(statement))"


def test_all_physical_fks_point_to_existing_exact_unique_columns():
    for table in schema_proposal.TABLES:
        for fk in (c for c in table.constraints if isinstance(c, ForeignKeyConstraint)):
            parent = fk.elements[0].column.table
            columns = tuple(e.column.name for e in fk.elements)
            unique = [
                tuple(parent.primary_key.columns.keys()),
                *(
                    tuple(c.columns.keys())
                    for c in parent.constraints
                    if isinstance(c, UniqueConstraint)
                ),
            ]
            assert columns in unique, (table.name, parent.name, columns)


def test_actual_common_preview_dispatch_uses_once_hooks_and_returned_command(monkeypatch):
    f, product, bound = phase_frame(monkeypatch)
    f.s.scalar = lambda q: product
    f.s.get = lambda *a: SimpleNamespace(kind="human", id=f.command.category_id)
    monkeypatch.setattr(common, "require_access", lambda *a, **k: None)
    monkeypatch.setattr(common, "command_scope", lambda *a, **k: product)
    monkeypatch.setattr(common, "prove_sources", lambda *a, **k: None)
    monkeypatch.setattr(common, "source_for", lambda *a: None)
    calls = []
    original_prepare = service.prepare_preview
    original_render = service.preview_prepared

    def prepare(*args):
        calls.append("prepare")
        return original_prepare(*args)

    def render(*args):
        calls.append("render")
        return original_render(*args)

    monkeypatch.setattr(service, "prepare_preview", prepare)
    monkeypatch.setattr(service, "preview_prepared", render)
    value = common.preview_command(f.s, f.ctx, f.command)
    assert calls == ["prepare", "render"]
    assert value["command"]["command_id"] == str(f.command.command_id)
    assert value["command"]["idempotency_key"] == f.command.idempotency_key
    assert (
        value["command"]["source_read_set"] == f.command.model_dump(mode="json")["source_read_set"]
    )
    assert value["command"]["payload"]["confirmation_token"]
    assert value["review"]["after"]["created_at"] is None
    proofs = [v for v in f.s.new if isinstance(v, models.Confirmation)]
    assert len(proofs) == 1 and proofs[0].snapshot == value["review"]
    assert proofs[0].operation == f.command.operation


def test_unchanged_canonical_specs_retain_baseline_and_s0_changes_are_explicit():
    import hashlib
    import json

    baseline = json.loads(CANONICAL_SCHEMA_BASELINE_JSON)
    source = SERVER
    approved_s0_changes = {
        "pdos_next/schemas/change_control/contracts.py",
        "pdos_next/schemas/discovery/contracts.py",
        "pdos_next/schemas/manufacturing_trials/contracts.py",
        "pdos_next/schemas/planning/plan.py",
        "pdos_next/schemas/products/definitions.py",
        "pdos_next/schemas/products/variants.py",
        "pdos_next/schemas/quality_issues/contracts.py",
        "pdos_next/schemas/resource_readiness/contracts.py",
        "pdos_next/schemas/supply_cost/dto.py",
        "pdos_next/schemas/verification/contracts.py",
    }
    specs = [
        p for p in baseline if p.startswith("pdos_next/schemas/") and p not in approved_s0_changes
    ]
    from pdos_next.schemas.change_control.contracts import GraphSnapshot

    assert GraphSnapshot.model_fields["expires_at"].default is None
    assert specs
    assert all(hashlib.sha256((source / p).read_bytes()).hexdigest() == baseline[p] for p in specs)


def test_reverse_common_members_preserve_delivery_and_aliases_without_current_reauthorization():
    sql = schema_proposal.MEMBER_GUARDS
    assert "Retained" not in sql  # scoped messages below are exact, not a SQL digest surrogate.
    assert "Preparation retained group requires one receipt" in sql
    assert "audit_entries WHERE tenant_id=t AND receipt_id=r.id)<>1" in sql
    assert "outbox_events WHERE tenant_id=t AND receipt_id=r.id)<>1" in sql
    assert "['delivered_at','lease_id','lease_until','attempts','last_error']" in sql
    assert "Preparation Audit/RequestKey is immutable" in sql
    assert "manufacturing_preparation_currents" not in sql
    assert "key=v.input_snapshot->'command'->>'idempotency_key'" in sql
    # Further RequestKey aliases are legitimate common recovery; only the exact
    # original key is required, not a fabricated one-key-only receipt policy.
    assert "count(*) FROM request_keys WHERE tenant_id=t AND receipt_id=r.id)" not in sql
    assert sql.count("DEFERRABLE INITIALLY DEFERRED") == 3


def test_full_lifecycle_catalog_matches_actual_isolated_model_namespace():
    assert set(models.Base.metadata.tables) == set(lifecycle_catalog.COVERED_COLUMNS)
    for name, table in models.Base.metadata.tables.items():
        assert set(c.name for c in table.columns) == set(lifecycle_catalog.COVERED_COLUMNS[name])


def test_offline_pg_text_compilation_has_no_accidental_parameters_or_driver_percent_alias():
    from sqlalchemy import text
    from sqlalchemy.dialects.postgresql import psycopg

    for value in schema_proposal.proposed_sql():
        compiled = text(value).compile(dialect=psycopg.dialect())
        assert compiled.params == {}
        if "%ROWTYPE" in value:
            assert "%%ROWTYPE" in str(compiled)


@pytest.mark.parametrize("gate", ["load", "cas", "history"])
def test_owner_or_history_io_cannot_silently_change_actual_caller_uow(monkeypatch, gate):
    f = frame()

    def crossed(*args, **kwargs):
        f.s.rollback()
        f.s.begin()
        return None

    name = {"load": "_load_fixed", "cas": "_cas_fixed", "history": "_get_preparation"}[gate]
    monkeypatch.setattr(service, name, crossed)
    with pytest.raises(DomainError):
        if gate == "load":
            service._load(f.s, f.ctx, f.command, None, f.payload)
        elif gate == "cas":
            service._cas(f.s, f.ctx, f.command, None, f.payload, None)
        else:
            service.get_preparation(f.s, f.ctx, f.pid, None)


def test_preview_refresh_cannot_silently_change_actual_uow(monkeypatch):
    f, product, bound = phase_frame(monkeypatch)
    phase = service.prepare_preview(f.s, f.ctx, f.command, product, f.payload)

    def crossed(*args):
        f.s.rollback()
        f.s.begin()
        return bound

    monkeypatch.setattr(service, "_refresh", crossed)
    with pytest.raises(DomainError):
        service.preview_prepared(f.s, f.ctx, f.command, product, f.payload, phase)
