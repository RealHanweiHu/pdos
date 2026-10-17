"""No-connect protocol/owner seams. Substitutes never attest actual qualification."""

import copy
import pickle
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID as CategoryUUID
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, make_transient_to_detached
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import Uuid

from pdos_next.contracts import Command
from pdos_next.domain.manufacturing_baseline import consumption, models, rules, schemas, service
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.service import Context, digest, material_digest


def source():
    return {"artifact_id": str(uuid4()), "expected_revision": 1, "line": 1, "quote": "整行原文"}


def material(kind="work_instruction", **changes):
    common = {
        "project_id": uuid4(),
        "process": {"id": uuid4(), "revision": 1},
        "title": "固定制造准备",
        "sources": [source()],
        "reason": "记录真实拟定资料",
    }
    if kind == "work_instruction":
        common.update(
            operation_key="assemble",
            steps=[{"key": "fit", "text": "按图装配", "sources": [source()]}],
        )
    elif kind == "control_plan":
        common.update(
            operation_key="assemble",
            checks=[{"key": "check", "feature": "位置", "sources": [source()]}],
        )
    else:
        common.update(operations=[{"operation_key": "assemble"}])
    common.update(changes)
    return schemas.PAYLOADS[{v: k for k, v in schemas.KINDS.items()}[kind]].model_validate(common)


def frame(operation="npi.work_instruction.record", *, nested=False):
    payload = material(schemas.KINDS[operation], confirmation_token="owned-pure-token-substitute")
    tenant, actor, pid = uuid4(), uuid4(), uuid4()
    ctx = Context(tenant, actor, actor, category_id=CategoryUUID(int=1000000))
    command = Command(
        command_id=uuid4(),
        idempotency_key=str(uuid4()),
        operation=operation,
        product_id=pid,
        expected_revision=4,
        payload=payload.model_dump(mode="json"),
        source_read_set=rules.source_reads(payload),
        category_id=CategoryUUID(int=1000000),
    )
    proof = Confirmation(
        id=uuid4(),
        tenant_id=tenant,
        product_id=pid,
        actor_id=actor,
        subject_id=pid,
        operation=operation,
        revision=4,
        consumed=False,
        token_hash=digest(payload.confirmation_token),
        payload_digest=material_digest(ctx, command, payload, service),
        snapshot={"explicit": "no owner qualification attestation"},
        created_at=datetime.now(UTC) - timedelta(seconds=2),
        expires_at=datetime.now(UTC) + timedelta(minutes=3),
    )
    make_transient_to_detached(proof)  # ORM-history substitute, not a fetched DB row.
    engine = SimpleNamespace()
    s = Session(bind=engine)
    s.begin()
    if nested:
        s.begin_nested()
    s.add(proof)
    host = consumption.ConsumptionHost({operation: service})
    for name in ("execute", "scalar", "scalars", "flush", "commit"):
        setattr(s, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("No IO allowed")))

    def bind():
        return host.bind_before_transition(
            s, ctx, command, payload, service, proof, reviewed_snapshot=proof.snapshot
        )

    def capture(binding):
        return host.capture_after_transition(
            s, ctx, command, payload, service, proof, binding=binding
        )

    def live(binding, marker, **kw):
        args = dict(
            s=s,
            ctx=ctx,
            command=command,
            payload=payload,
            module=service,
            proof=proof,
            binding=binding,
            marker=marker,
        )
        args.update(kw)
        return host.require_live(**args)

    return SimpleNamespace(**locals())


@pytest.mark.parametrize("kind", list(schemas.KINDS.values()))
def test_draft_material_has_no_client_qualification_clock_or_release_fields(kind):
    value = material(kind)
    assert value.visibility == "private"
    for extra in (
        "qualified",
        "released",
        "received_at",
        "approval_token",
        "issuer",
        "complete_graph",
    ):
        with pytest.raises(ValidationError):
            type(value).model_validate({**value.model_dump(mode="json"), extra: True})


@pytest.mark.parametrize("value", [True, 1.1, "NaN", "Infinity", "1E10000", "0.0000000000001", "x"])
def test_declared_decimal_never_accepts_lossy_or_unbounded_numbers(value):
    with pytest.raises(ValidationError):
        schemas.Parameter(key="temp", nominal=value, unit="C", sources=[source()])


def test_decimal_units_and_exact_sources_required_no_zero_default():
    empty = schemas.Parameter(key="temp")
    assert empty.nominal is empty.lower is empty.upper is None
    good = schemas.Parameter(
        key="temp", lower="-10.0000", upper="20.0001", unit="C", sources=[source()]
    )
    assert good.lower == Decimal("-10.0000")
    with pytest.raises(ValidationError):
        schemas.Parameter(key="temp", nominal="0")
    with pytest.raises(ValidationError):
        schemas.Parameter(key="temp", lower="2", upper="1", unit="C", sources=[source()])


def test_semantic_excludes_only_common_token_keeps_exact_quote_and_order():
    value = material(confirmation_token="owned-pure-token-substitute")
    raw = rules.semantic(value)
    assert "confirmation_token" not in raw
    assert raw["sources"][0]["quote"] == value.sources[0].quote
    assert raw["steps"][0]["text"] == value.steps[0].text
    assert digest(raw) != digest({**raw, "reason": "different"})


@pytest.mark.parametrize("name", ["project_id", "process", "sources", "reason", "previous_id"])
def test_scope_and_evidence_semantics_do_not_silently_migrate(name):
    value = material()
    raw = rules.semantic(value)
    changed = copy.deepcopy(raw)
    changed[name] = "different"
    assert digest(raw) != digest(changed)


def test_source_hash_uses_whole_utf8_quote_and_merges_distinct_artifact_reads():
    same = source()
    value = material(sources=[same], steps=[{"key": "fit", "text": "装配", "sources": [same]}])
    assert len(rules.source_refs(value)) == len(rules.source_reads(value)) == 1
    assert rules.source_refs(value)[0].position.startswith("line:1;quote_sha256:")
    with pytest.raises(ValidationError):
        material(sources=[same, same])
    wrong = copy.deepcopy(same)
    wrong["expected_revision"] = 2
    value = material(sources=[same], steps=[{"key": "fit", "text": "装配", "sources": [wrong]}])
    with pytest.raises(DomainError, match="同一来源"):
        rules.source_reads(value)


def test_full_source_closure_over_twenty_remains_complete():
    value = material(sources=[source() for _ in range(20)])
    reads = rules.source_reads(value)
    assert len(reads) > 20
    assert {str(ref.id) for ref in rules.source_refs(value)} == {
        str(read["artifact_id"]) for read in reads
    }


def documents_for(payload):
    result = {}
    for item in payload.operations:
        for kind in ("work_instruction", "control_plan"):
            ref = getattr(item, kind)
            if ref is not None:
                result[(item.operation_key, kind)] = {
                    "id": str(ref.id),
                    "revision": ref.revision,
                    "kind": kind,
                    "operation_key": item.operation_key,
                    "process": payload.process.model_dump(mode="json"),
                    "status": "draft",
                    "is_current": True,
                    "source_status": "current",
                    "visibility": payload.visibility,
                }
    return result


def baseline():
    return material(
        "manufacturing_baseline",
        operations=[
            {
                "operation_key": "assemble",
                "work_instruction": {"kind": "work_instruction", "id": uuid4(), "revision": 1},
                "control_plan": {"kind": "control_plan", "id": uuid4(), "revision": 1},
            }
        ],
    )


def test_draft_complete_documents_still_unknown_not_named_release_or_negative_enumeration():
    value = baseline()
    gaps = rules.check_material(value, {"operations": [{"key": "assemble"}]}, documents_for(value))
    codes = {v["code"] for v in gaps}
    assert "MANUFACTURING_BASELINE_RELEASE_NOT_CONFIGURED" in codes
    assert "MANUFACTURING_SCOPE_ENUMERATION_NOT_CONFIGURED" in codes
    assert "FIXTURE_QUALIFICATION_OWNER_NOT_CONFIGURED" in codes
    with pytest.raises(DomainError) as error:
        service.qualified_pilot_baseline()
    assert error.value.status == 503


def test_incomplete_baseline_is_explicit_draft_not_false_negative_complete():
    value = material("manufacturing_baseline")
    gaps = rules.check_material(value, {"operations": [{"key": "assemble"}]}, {})
    assert sum(v["code"] == "MISSING_OPERATION_DOCUMENT" for v in gaps) == 2


@pytest.mark.parametrize("visibility", ["private", "category", "audience"])
def test_baseline_accepts_exact_documents_in_current_shared_audience(visibility):
    value = baseline().model_copy(update={"visibility": visibility})
    gaps = rules.check_material(value, {"operations": [{"key": "assemble"}]}, documents_for(value))
    assert not any(v["code"] == "MISSING_OPERATION_DOCUMENT" for v in gaps)
    assert any(v["code"] == "MANUFACTURING_BASELINE_RELEASE_NOT_CONFIGURED" for v in gaps)


@pytest.mark.parametrize("visibility", ["category", "audience"])
def test_shared_baseline_does_not_expand_private_operation_document(visibility):
    value = baseline().model_copy(update={"visibility": visibility})
    documents = documents_for(value)
    documents[("assemble", "work_instruction")]["visibility"] = "private"
    with pytest.raises(DomainError) as error:
        rules.check_material(value, {"operations": [{"key": "assemble"}]}, documents)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_baseline_rejects_retired_product_visibility_in_operation_document():
    value = baseline().model_copy(update={"visibility": "category"})
    documents = documents_for(value)
    documents[("assemble", "work_instruction")]["visibility"] = "product"
    with pytest.raises(DomainError) as error:
        rules.check_material(value, {"operations": [{"key": "assemble"}]}, documents)
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "wrongkind",
        "wrongprocess",
        "wrongop",
        "wrongrev",
        "boolrev",
        "oldcurrent",
        "withdrawn",
        "private",
    ],
)
def test_baseline_exact_fixed_document_child_owner_boundaries(mutation):
    value = baseline().model_copy(update={"visibility": "category"})
    docs = documents_for(value)
    child = docs[("assemble", "work_instruction")]
    if mutation == "missing":
        docs.pop(("assemble", "work_instruction"))
    elif mutation == "extra":
        docs[("other", "work_instruction")] = copy.deepcopy(child)
    elif mutation == "wrongkind":
        child["kind"] = "control_plan"
    elif mutation == "wrongprocess":
        child["process"]["id"] = str(uuid4())
    elif mutation == "wrongop":
        child["operation_key"] = "other"
    elif mutation == "wrongrev":
        child["revision"] = 2
    elif mutation == "boolrev":
        child["revision"] = True
    elif mutation == "oldcurrent":
        child["is_current"] = False
    elif mutation == "withdrawn":
        child["source_status"] = "needs_recheck"
    else:
        child["visibility"] = "private"
    with pytest.raises(DomainError):
        rules.check_material(value, {"operations": [{"key": "assemble"}]}, docs)


@pytest.mark.parametrize(
    "operations",
    [[], [{"key": "assemble"}, {"key": "assemble"}], [{"key": None}], [{"key": "other"}]],
)
def test_fixed_operation_list_not_inferred_or_subset(operations):
    value = material("manufacturing_baseline")
    with pytest.raises(DomainError):
        rules.check_material(value, {"operations": operations}, {})


def test_control_unknown_fields_never_synthesized():
    value = material("control_plan")
    gaps = rules.check_material(value, {"operations": [{"key": "assemble"}]}, {})
    unknown = next(g for g in gaps if g["code"] == "CONTROL_CHECK_INCOMPLETE")
    assert "reaction_plan" in unknown["fields"] and "sampling_method" in unknown["fields"]
    assert rules.semantic(value)["checks"][0]["method"] is None


@pytest.mark.parametrize("operation", list(schemas.PAYLOADS))
def test_common_transition_preserves_first_clock_and_domain_vs_common_intent(operation):
    f = frame(operation)
    binding = f.bind()
    f.proof.consumed = True  # Emulate actual common assignment, not an owner grant.
    marker = f.capture(binding)
    assert f.capture(binding) is marker and f.live(binding, marker) is marker
    assert marker.tier == "T1"
    assert marker.common_intent_sha256 != digest(rules.semantic(f.payload))
    assert inspect(f.proof).attrs.consumed.history.deleted == [False]


@pytest.mark.parametrize(
    "fault",
    [
        "historicaltrue",
        "notransition",
        "flushedhistory",
        "expired",
        "token",
        "material",
        "boolrevision",
        "key",
        "actor",
        "newuow",
        "nested",
    ],
)
def test_actual_consumption_never_accepts_historical_bool_or_changed_material(fault):
    f = frame(nested=fault == "nested")
    if fault == "historicaltrue":
        f.proof.consumed = True
        with pytest.raises(DomainError):
            f.bind()
        return
    binding = f.bind()
    if fault != "notransition":
        f.proof.consumed = True
    if fault == "flushedhistory":
        from sqlalchemy.orm.attributes import set_committed_value

        set_committed_value(f.proof, "consumed", True)
    elif fault == "expired":
        f.proof.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif fault == "token":
        f.proof.token_hash = digest("different")
    elif fault == "material":
        f.proof.snapshot["unexpected"] = "changed"
    elif fault == "boolrevision":
        f.proof.revision = True
    elif fault in {"newuow", "nested"}:
        if fault == "nested":
            f.s.get_nested_transaction().rollback()
        else:
            f.s.rollback()
        f.s.begin() if f.s.get_transaction() is None else None
    if fault in {"key", "actor"}:
        marker = f.capture(binding)
        kw = (
            {"command": f.command.model_copy(update={"idempotency_key": str(uuid4())})}
            if fault == "key"
            else {"ctx": Context(f.tenant, uuid4(), f.actor, category_id=CategoryUUID(int=1000000))}
        )
        with pytest.raises(DomainError):
            f.live(binding, marker, **kw)
    else:
        with pytest.raises(DomainError):
            f.capture(binding)


def test_confirm_false_true_does_not_flush_or_reset_during_fresh_select_context():
    f = frame()
    binding = f.bind()
    f.proof.consumed = True
    before = tuple(f.s.dispatch.do_orm_execute)
    with service._fresh_selects(f.s):
        assert len(tuple(f.s.dispatch.do_orm_execute)) == len(before) + 1
        assert inspect(f.proof).attrs.consumed.history.deleted == [False]
    assert tuple(f.s.dispatch.do_orm_execute) == before
    assert f.capture(binding)


def test_default_missing_common_host_fails_closed():
    f = frame()
    with pytest.raises(DomainError) as error:
        service._host(f.s)
    assert error.value.status == 503


def test_t1_phase_keeps_full_command_and_nested_uow_identity(monkeypatch):
    f = frame()
    product = Product(
        id=f.pid,
        tenant_id=f.tenant,
        owner_id=f.actor,
        name="actual ORM substitute",
        revision=4,
        category_id=CategoryUUID(int=1000000),
    )
    make_transient_to_detached(product)
    f.s.add(product)
    monkeypatch.setattr(service, "_runtime", lambda s: "current-runtime")
    bound = service.Bound(
        SimpleNamespace(purpose="exact purpose"),
        None,
        None,
        {"status": "draft"},
        [],
        {},
        {"valid_until": (datetime.now(UTC) + timedelta(minutes=1)).isoformat()},
        None,
        {},
        "current-runtime",
    )
    phase = service.Prepared(service._CAPABILITY, f.s, f.ctx, f.command, product, f.payload, bound)
    service._phase(f.s, f.ctx, f.command, product, f.payload, phase)
    for change in (
        {"idempotency_key": str(uuid4())},
        {"command_id": uuid4()},
        {"source_read_set": []},
        {"expected_revision": 5},
    ):
        with pytest.raises(DomainError):
            service._phase(
                f.s, f.ctx, f.command.model_copy(update=change), product, f.payload, phase
            )
    with pytest.raises(TypeError):
        copy.copy(phase)
    with pytest.raises(TypeError):
        pickle.dumps(phase)
    f.s.flush = Session.flush.__get__(f.s, Session)  # Clean persistent rows: no connection or SQL.
    with f.s.begin_nested():
        with pytest.raises(DomainError):
            service._phase(f.s, f.ctx, f.command, product, f.payload, phase)
    phase.used = True
    with pytest.raises(DomainError):
        service._phase(f.s, f.ctx, f.command, product, f.payload, phase)


def test_final_owner_io_expiry_rechecked_with_fresh_clock(monkeypatch):
    f = frame()
    bound = service.Bound(
        None,
        None,
        None,
        {},
        [],
        {},
        {"valid_until": (datetime.now(UTC) + timedelta(seconds=2)).isoformat()},
        None,
        {},
        "current-runtime",
    )
    monkeypatch.setattr(service, "_load", lambda *a, **k: bound)
    monkeypatch.setattr(service, "_cas", lambda *a, **k: None)
    monkeypatch.setattr(service, "_runtime", lambda s: "current-runtime")
    monkeypatch.setattr(service, "now", lambda: datetime.now(UTC) + timedelta(seconds=3))
    with pytest.raises(DomainError) as error:
        service._refresh(f.s, f.ctx, f.command, None, f.payload, bound)
    assert error.value.reason == "SOURCE_STALE"


def test_end_owner_refresh_rejects_source_or_configuration_drift(monkeypatch):
    f = frame()
    bound = service.Bound(
        None, None, None, {"fixed": "original"}, [], {}, {}, None, {}, "current-runtime"
    )
    latest = service.Bound(
        None, None, None, {"fixed": "replacement"}, [], {}, {}, None, {}, "current-runtime"
    )
    monkeypatch.setattr(service, "_load", lambda *a, **k: latest)
    with pytest.raises(DomainError) as error:
        service._refresh(f.s, f.ctx, f.command, None, f.payload, bound)
    assert error.value.reason == "RECHECK_REQUIRED"


def test_model_physical_scope_and_fixed_child_fks_offline_compile():
    for model in (
        models.PreparationVersion,
        models.PreparationCurrent,
        models.BaselineDocumentLink,
    ):
        sql = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert model.__tablename__ in sql and "FOREIGN KEY" in sql
    table = models.BaselineDocumentLink.__table__
    child = next(
        c
        for c in table.constraints
        if isinstance(c, ForeignKeyConstraint) and "document_kind" in c.column_keys
    )
    assert tuple(child.column_keys) == (
        "tenant_id",
        "product_id",
        "project_id",
        "document_kind",
        "document_id",
        "document_revision",
        "process_id",
        "process_revision",
        "operation_key",
    )
    assert all(not table.c[k].nullable for k in child.column_keys)
    assert "purpose" in models.PreparationVersion.__table__.c
    assert not any(
        "purpose" in tuple(c.columns.keys())
        for c in models.PreparationVersion.__table__.constraints
        if isinstance(c, UniqueConstraint)
    )


def test_all_btree_identity_bounds_use_utf8_not_character_claims():
    # Conservative per datum aligned overhead + full UTF-8 maximum, no compression.
    # 2704 comes from default 8KB PostgreSQL B-tree tuple limit; Root must test real PG.
    for model in (
        models.PreparationVersion,
        models.PreparationCurrent,
        models.BaselineDocumentLink,
    ):
        indexes = [
            tuple(c.columns) for c in model.__table__.constraints if isinstance(c, UniqueConstraint)
        ]
        indexes += [tuple(i.columns) for i in model.__table__.indexes]
        for columns in indexes:
            total = 32
            for column in columns:
                typ = column.type
                if getattr(typ, "length", None) is not None:
                    total += ((4 * typ.length + 8 + 7) // 8) * 8
                elif isinstance(typ, Uuid):
                    total += 16
                elif str(typ) == "INTEGER":
                    total += 8
                else:
                    raise AssertionError(f"Unbounded physical identity: {column}")
            assert total < 2704, (model.__tablename__, total)


def test_current_and_version_checks_are_narrow_and_draft_only():
    texts = [
        str(c.sqltext)
        for c in models.PreparationVersion.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    assert any("status='draft'" in text for text in texts)
    assert any("revision=previous_revision+1" in text for text in texts)
    assert any("proof_consumed_at<proof_expires_at" in text for text in texts)
    assert set(models.PreparationCurrent.__table__.c.keys()).isdisjoint(
        {"released", "qualified", "scope_complete"}
    )


def test_actual_authority_cannot_be_borrowed_from_different_caller_or_project(monkeypatch):
    f = frame()
    project = SimpleNamespace(id=f.payload.project_id, purpose="exact purpose")
    value = {
        "scope": {"tenant_id": str(f.tenant), "product_id": str(f.pid), "project_id": str(uuid4())},
        "subject_id": str(f.actor),
        "operation": f.command.operation,
        "purpose": project.purpose,
        "authorized": True,
        "qualified": True,
        "roles": ["manufacturing"],
        "reason_codes": [],
    }
    monkeypatch.setattr(service.professional, "assess", lambda *a, **k: value)
    with pytest.raises(DomainError) as error:
        service._authority(f.s, f.ctx, f.command, project)
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_explicit_public_registry_is_manufacturing_t1_without_release():
    from pdos_next.command_handlers import LIVE_CONSUMPTION_OPERATIONS, T1_OPERATIONS, T2_OPERATIONS
    from pdos_next.service import EVENTS

    assert set(schemas.PAYLOADS) <= set(T1_OPERATIONS) & set(LIVE_CONSUMPTION_OPERATIONS)
    assert not set(schemas.PAYLOADS) & set(T2_OPERATIONS)
    assert all(
        service.professional.OPERATION_ROLES[op] == {"manufacturing"} for op in schemas.PAYLOADS
    )
    assert all(EVENTS[op] == f"{schemas.KINDS[op]}.recorded" for op in schemas.PAYLOADS)


def test_schema_proposal_rls_atom_and_negative_public_permissions():
    from pdos_next.domain.manufacturing_baseline import schema_proposal

    sql = "\n".join(schema_proposal.proposed_sql())
    assert sql.count("FORCE ROW LEVEL SECURITY") == 3
    assert "GRANT UPDATE(version_id,revision)" in sql
    assert "GRANT UPDATE ON" not in sql
    assert "GRANT SELECT,INSERT" in sql
    assert "TO pdos_agent" not in sql
    assert "OLD.consumed IS DISTINCT FROM false" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "require_quality_change_atom" not in sql and "CREATE OR REPLACE" not in sql
    assert "jsonb::text" not in sql


def test_whole_quote_duplicates_inside_step_rejected():
    same = source()
    with pytest.raises(ValidationError):
        material(steps=[{"key": "fit", "text": "装配", "sources": [same, same]}])


def test_actual_phase_stages_one_draft_only_after_live_consumption(monkeypatch):
    f = frame()
    product = Product(
        id=f.pid,
        tenant_id=f.tenant,
        owner_id=f.actor,
        name="ORM protocol substitute",
        revision=4,
        category_id=CategoryUUID(int=1000000),
    )
    make_transient_to_detached(product)
    f.s.add(product)
    f.engine._pdos_manufacturing_preparation_consumption = f.host
    from .test_expiry import authority_result

    authority = authority_result(
        f, SimpleNamespace(id=f.payload.project_id, purpose="actual purpose"), datetime.now(UTC)
    )
    bound = service.Bound(
        SimpleNamespace(id=f.payload.project_id, purpose="exact purpose"),
        None,
        None,
        {"status": "draft"},
        rules.source_reads(f.payload),
        {},
        authority,
        None,
        {},
        "runtime",
    )
    monkeypatch.setattr(service, "_runtime", lambda s: "runtime")
    monkeypatch.setattr(service, "_refresh", lambda *a, **k: bound)  # Explicit owner substitute.
    phase = service.Prepared(service._CAPABILITY, f.s, f.ctx, f.command, product, f.payload, bound)
    f.proof.snapshot = copy.deepcopy(phase.review)
    binding = f.bind()
    f.proof.consumed = True
    marker = f.capture(binding)
    flushed = []
    f.s.flush = lambda objects=None: flushed.append(tuple(objects or ()))  # Never SQL.
    row, family, audience = service.apply_prepared_write(
        f.s, f.ctx, f.command, product, f.payload, phase, consumption=(binding, marker)
    )
    assert family == "work_instruction" and audience == "private" and row.status == "draft"
    assert row.shared_proof_id == f.proof.id and row.proof_consumed_at == marker.consumed_at
    assert row.input_snapshot["request_digest"] == service._request_digest(f.command, f.payload)
    assert "confirmation_token" not in row.input_snapshot["command"]["payload"]
    assert len([v for v in f.s.new if isinstance(v, models.PreparationCurrent)]) == 1
    assert len(flushed) == 1 and flushed[0] == (row,)
    with pytest.raises(DomainError):
        service.apply_prepared_write(
            f.s, f.ctx, f.command, product, f.payload, phase, consumption=(binding, marker)
        )


@pytest.mark.parametrize("quote", ["line1\nline2", "line\r", "bad\x00", "\ud800"])
def test_source_single_whole_utf8_line_only(quote):
    with pytest.raises(ValidationError):
        schemas.Source.model_validate({**source(), "quote": quote})


@pytest.mark.parametrize("fault", [None, "visibility", "project", "process", "purpose", "kind"])
def test_fixed_saved_material_columns_never_widen_private_or_drift_scope(fault):
    f = frame()
    row = SimpleNamespace(
        operation=f.command.operation,
        kind="work_instruction",
        project_id=f.payload.project_id,
        product_id=f.pid,
        visibility="private",
        title=f.payload.title,
        process_id=f.payload.process.id,
        process_revision=f.payload.process.revision,
        operation_key=f.payload.operation_key,
        previous_id=None,
        previous_revision=None,
        shared_proof_revision=4,
        purpose="exact purpose",
        body={
            "schema_version": service.SCHEMA_VERSION,
            "scope": {"project_id": str(f.payload.project_id), "purpose": "exact purpose"},
            "kind": "work_instruction",
            "status": "draft",
            "input": rules.semantic(f.payload),
        },
        input_snapshot={
            "command": service._saved_command(f.command),
            "semantic": rules.semantic(f.payload),
        },
    )
    if fault is None:
        command, payload = service._record_input(row)
        assert command.command_id == f.command.command_id and payload.confirmation_token is None
    else:
        if fault in {"project", "process"}:
            setattr(row, fault + "_id", uuid4())
        elif fault == "visibility":
            row.visibility = "product"
        elif fault == "purpose":
            row.purpose = "other purpose"
        else:
            row.kind = "control_plan"
        with pytest.raises(DomainError) as error:
            service._record_input(row)
        assert error.value.status == 503


def test_present_quantitative_criterion_without_values_stays_unknown():
    value = material(
        "control_plan",
        checks=[
            {
                "key": "check",
                "feature": "位置",
                "method": "按图核查",
                "criterion": {"key": "position"},
                "frequency": "每件",
                "sampling_method": "逐件",
                "reaction_plan": "暂缓",
                "responsible_role": "制造",
                "sources": [source()],
            }
        ],
    )
    gaps = rules.check_material(value, {"operations": [{"key": "assemble"}]}, {})
    assert next(v for v in gaps if v["code"] == "CONTROL_CHECK_INCOMPLETE")["fields"] == [
        "criterion_values"
    ]
