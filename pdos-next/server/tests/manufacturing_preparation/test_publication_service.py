"""Actual publication hooks/ORM history; all SQL/owner IO is substituted.

Real normalization, common consumption, phases, CAS, saved-group and tail checks
execute. These tests prove neither PostgreSQL constraints/RLS nor real material,
professional qualification, a production publication or manufacturing release.
"""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb, JsonbDumper
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.orm import Session, make_transient_to_detached
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.sql import operators

from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.manufacturing_baseline import publication_service as service
from pdos_next.domain.manufacturing_baseline import service as preparation
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublication as Publication,
)
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingBaselinePublicationCurrent as Current,
)
from pdos_next.domain.manufacturing_baseline.publication_models import (
    ManufacturingPublicationDocument as Document,
)
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import (
    Confirmation,
    Grant,
    Outbox,
    Principal,
    Product,
    RequestKey,
)

from .test_expiry import authority_result
from .test_publication_rules import case as publication_case
from .test_publication_rules import rebuild_links


class MemorySession(Session):
    """Only database SELECT/flush results; real Session and proof history survive."""

    def __init__(self, engine):
        super().__init__(engine)
        self.rows, self.queries, self.flushes = {}, [], []
        self.peer_bound, self.hide_keys = True, False
        self.binding_calls = []

    def seed(self, row):
        make_transient_to_detached(row)
        super().add(row)
        self.rows.setdefault(type(row), []).append(row)
        return row

    def get(self, model, identity, **kwargs):
        return next((row for row in self.rows.get(model, ()) if row.id == identity), None)

    def scalars(self, query, *args, **kwargs):
        self.queries.append(query)
        model = query.column_descriptions[0]["entity"]
        values = list(self.rows.get(model, ()))
        if model is RequestKey and self.hide_keys:
            return []
        for clause in query._where_criteria:
            assert clause.operator in {operators.eq, operators.is_}
            wanted = getattr(clause.right, "value", None)
            values = [value for value in values if getattr(value, clause.left.key) == wanted]
        if query._limit_clause is not None:
            values = values[: query._limit_clause.value]
        return values

    def scalar(self, query, *args, **kwargs):
        first = list(query.selected_columns)[0]
        function = getattr(first, "element", None)
        if getattr(function, "name", None) == "change_receipt_key_bound":
            assert function.packagenames == ("public",)
            assert tuple(v.value for v in function.clauses)[:2] == (
                self.info["scope"][0],
                self.product.id,
            )
            self.binding_calls.append(tuple(v.value for v in function.clauses))
            return self.peer_bound
        rows = self.scalars(query)
        assert len(rows) <= 1
        return rows[0] if rows else None

    def execute(self, query, *args, **kwargs):
        assert [v["entity"] for v in query.column_descriptions] == [Principal, Grant]
        self.queries.append(query)
        return SimpleNamespace(all=lambda: [(self.person, self.grant)])

    def flush(self, objects=None):
        pending = list(objects) if objects is not None else list(self.new)
        self.flushes.append(tuple(type(value) for value in pending))
        for value in pending:
            if value.id is None:
                value.id = uuid4()
            if hasattr(type(value), "created_at") and value.created_at is None:
                value.created_at = self.clock()
            if "category_id" in value.__table__.columns and value.category_id is None:
                value.category_id = self.product.category_id
            if isinstance(value, Outbox):
                value.schema_version = value.schema_version or 1
                value.attempts = value.attempts or 0
            self.expunge(value)
            make_transient_to_detached(value)
            super().add(value)
            self.rows.setdefault(type(value), []).append(value)
        if objects is None:
            for value in list(self.dirty):
                for name in inspect(value).mapper.column_attrs.keys():
                    if name in vars(value):
                        set_committed_value(value, name, getattr(value, name))

    def commit(self):
        raise AssertionError("The domain service must never COMMIT")


class MaterialIO:
    """Explicit owner IO substitute, not an actual original/provenance proof."""

    def __init__(self, frame):
        self.frame, self.issued, self.calls = frame, [], []

    def read(self, s, ctx, pid, payload):
        f = self.frame
        assert s is f.s and pid == f.pid and ctx.tenant_id == f.tenant
        assert payload.project_id == f.material.scope.project_id
        self.calls.append("read")
        value = SimpleNamespace(
            material=f.material.model_copy(deep=True),
            # ActualPublicationMaterialOwner._values retains native ORM UUIDs
            # inside this ordinary dict; json_value(dict) is only a deepcopy.
            source_basis={
                "owners": {
                    "product": {"id": f.product.id, "tenant_id": f.tenant},
                    "project": {
                        "id": f.material.scope.project_id,
                        "owner_id": f.material.baseline.owner_id,
                    },
                    "fixed_baseline": str(f.material.baseline.id),
                }
            },
            sources=f.material.additional_sources,
            required_source_read_set=f.material.required_source_read_set,
            checked_at=f.now(),
        )
        self.issued.append(value)
        return value

    def refresh(self, s, ctx, pid, payload, previous):
        assert any(previous is value for value in self.issued)
        self.calls.append("refresh")
        if self.frame.owner_hook:
            self.frame.owner_hook()
        return self.read(s, ctx, pid, payload)


@pytest.fixture
def work(monkeypatch):
    case = publication_case.__wrapped__()
    offset = [timedelta(0)]

    def clock():
        return datetime.now(UTC) + offset[0]

    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def no_connection(*_args):
        raise AssertionError("publication service pure checks must never connect")

    s = MemorySession(engine)
    s.begin()
    ctx = common.Context(case.scope.tenant_id, case.owner, case.owner, category_id=case.category)
    product = s.seed(
        Product(
            id=case.scope.product_id,
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            revision=case.material.product_revision,
            owner_id=ctx.actor_id,
        )
    )
    person = s.seed(
        Principal(
            id=ctx.actor_id,
            tenant_id=ctx.tenant_id,
            kind="human",
            active=True,
            access_epoch=1,
        )
    )
    grant = s.seed(
        Grant(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            principal_id=ctx.actor_id,
            can_write=True,
            expires_at=clock() + timedelta(hours=2),
            access_epoch=1,
        )
    )
    s.product, s.person, s.grant, s.clock = product, person, grant, clock
    s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    command = Command(
        command_id=uuid4(),
        idempotency_key="原始发布请求键-保留内存",
        operation=service.OPERATION,
        category_id=ctx.category_id,
        product_id=product.id,
        expected_revision=product.revision,
        source_read_set=[v.model_dump(mode="json") for v in case.material.required_source_read_set],
        payload=case.payload.model_dump(mode="json"),
    )
    project = s.seed(
        Project(
            id=case.scope.project_id,
            tenant_id=ctx.tenant_id,
            category_id=ctx.category_id,
            product_id=product.id,
            owner_id=ctx.actor_id,
            visibility="category",
            purpose=case.payload.purpose,
        )
    )
    f = SimpleNamespace(
        s=s,
        engine=engine,
        ctx=ctx,
        tenant=ctx.tenant_id,
        actor=ctx.actor_id,
        pid=product.id,
        product=product,
        grant=grant,
        material=case.material,
        payload=case.payload,
        command=command,
        project=project,
        now=clock,
        offset=offset,
        owner_hook=None,
        evidence_hook=None,
        authority_hook=None,
        source_status="current",
        retained=True,
        private_sources=True,
    )
    f.authority = authority_result(f, project, clock())
    preparation.configure(engine)
    runtime = service.configure(engine)
    f.actual_owner = runtime.owner
    f.owner = MaterialIO(f)
    engine._pdos_manufacturing_publication = service.Runtime(f.owner, runtime.consumption, service)
    monkeypatch.setattr(service, "now", clock)
    monkeypatch.setattr(preparation, "now", clock)
    monkeypatch.setattr(common, "now", clock)

    def project_io(session, caller, pid, project_id):
        assert session is s and caller.tenant_id == ctx.tenant_id
        assert pid == product.id and project_id == project.id
        return project, None, None

    def authority_io(session, caller, pid, project_id, operation, purpose, at, *, write=False):
        assert session is s and caller.actor_id == f.ctx.actor_id
        assert (pid, project_id, operation, purpose) == (
            product.id,
            project.id,
            service.OPERATION,
            project.purpose,
        )
        if f.authority_hook:
            f.authority_hook()
        return deepcopy(f.authority)

    def evidence_io(session, caller, pid, reads, refs=(), **kwargs):
        assert session is s and caller.tenant_id == ctx.tenant_id and pid == product.id
        if f.evidence_hook:
            f.evidence_hook()
        raw = {
            v["artifact_id"]: {
                "revision": v["expected_revision"],
                "sha256": common.digest(v["artifact_id"]),
                "source_origin": "registered_native_text",
                "visibility": "private" if f.private_sources else "category",
                "owner_id": str(ctx.actor_id),
                "registration_receipt_id": str(uuid4())
                if f.evidence_hook
                else "fixed-registration",
            }
            for v in reads
        }
        return raw, f.private_sources, set()

    monkeypatch.setattr(service, "signature_current", lambda *args: f.retained)
    monkeypatch.setattr(service.projects, "_project", project_io)
    monkeypatch.setattr(preparation.professional, "assess", authority_io)
    monkeypatch.setitem(
        preparation.professional.OPERATION_ROLES, service.OPERATION, {"manufacturing"}
    )
    monkeypatch.setattr(service.evidence, "_evidence", evidence_io)
    monkeypatch.setattr(service.configurations, "_source_state", lambda *args: f.source_status)
    monkeypatch.setattr(
        service,
        "_recheck",
        lambda *args, **kwargs: {"current": f.retained, "historical_valid": f.retained},
    )
    monkeypatch.setattr(common, "T2_OPERATIONS", common.T2_OPERATIONS | {service.OPERATION})
    monkeypatch.setattr(
        common,
        "PHASED_MATERIAL_OPERATIONS",
        common.PHASED_MATERIAL_OPERATIONS | {service.OPERATION},
    )
    monkeypatch.setattr(
        common,
        "LIVE_CONSUMPTION_OPERATIONS",
        common.LIVE_CONSUMPTION_OPERATIONS | {service.OPERATION},
    )
    monkeypatch.setitem(common.EVENTS, service.OPERATION, service.EVENT)
    yield f
    s.close()
    engine.dispose()


def prepare(work, *, expiry=None):
    phase, review = service.prepare_write_review(
        work.s, work.ctx, work.command, work.product, work.payload
    )
    proof = work.s.seed(
        Confirmation(
            id=uuid4(),
            tenant_id=work.tenant,
            category_id=work.ctx.category_id,
            product_id=work.pid,
            actor_id=work.actor,
            subject_id=work.pid,
            subject_type="product",
            operation=service.OPERATION,
            revision=work.product.revision,
            consumed=False,
            token_hash=common.digest(work.payload.approval_token),
            payload_digest=common.material_digest(work.ctx, work.command, work.payload, service),
            snapshot=deepcopy(review),
            created_at=work.now() - timedelta(seconds=2),
            expires_at=expiry,
        )
    )
    return phase, review, proof


def consume(work, phase, review):
    return common.consume_material_confirmation(
        work.s,
        work.ctx,
        work.command,
        work.product,
        work.payload,
        service,
        prepared_review=review,
        write_phase=phase,
    )


def write(work, *, expiry=None):
    phase, review, proof = prepare(work, expiry=expiry)
    consumed = consume(work, phase, review)
    row, subject_type, visibility = service.apply_prepared_write(
        work.s, work.ctx, work.command, work.product, work.payload, phase, consumption=consumed
    )
    return row, phase, proof, consumed, subject_type, visibility


def finish(work, written):
    row, phase, proof, consumed, subject_type, visibility = written
    receipt = common.append_receipt(
        work.s,
        work.ctx,
        work.command,
        subject_type,
        row,
        preparation._request_digest(work.command, work.payload),
        consumed[1].common_intent_sha256,
        visibility,
    )
    work.s.add(
        RequestKey(
            id=uuid4(),
            tenant_id=work.tenant,
            category_id=work.ctx.category_id,
            actor_id=work.actor,
            key=work.command.idempotency_key,
            digest=receipt.request_digest,
            receipt_id=receipt.id,
        )
    )
    work.s.flush()
    service.finalize_receipt(
        work.s, work.ctx, work.command, work.product, work.payload, row, receipt
    )
    return row, receipt


def test_configure_uses_actual_material_owner_and_independent_named_common_host(work):
    from pdos_next.domain.manufacturing_baseline.publication_material_owner import (
        ActualPublicationMaterialOwner,
    )

    assert type(work.actual_owner) is ActualPublicationMaterialOwner
    assert service._runtime(work.s).consumption.modules == {service.OPERATION: service}
    assert service._runtime(work.s).consumption is not preparation._host(work.s)


def test_inputs_rebuilds_only_server_read_set_without_writing_or_changing_original_command(work):
    original = work.command.model_copy(update={"source_read_set": []})
    before = original.model_dump(mode="json")
    result = service.inputs(work.s, work.ctx, work.pid, original)
    assert original.model_dump(mode="json") == before
    assert result["command"]["source_read_set"]
    assert result["command"]["idempotency_key"] == original.idempotency_key
    assert result["review"]["after"]["status"] == "published"
    assert not work.s.new and work.s.rows.get(Publication, []) == []


def test_preview_is_real_one_use_material_and_does_not_claim_qualification(work):
    phase = service.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    review = service.preview_prepared(
        work.s, work.ctx, work.command, work.product, work.payload, phase
    )
    assert review["after"]["id"] is review["after"]["created_at"] is None
    assert review["after"]["body"]["qualification"] == "unknown"
    assert review["after"]["body"]["manufacturing_release"] is None
    assert "refresh" in work.owner.calls
    with pytest.raises(DomainError):
        service.preview_prepared(work.s, work.ctx, work.command, work.product, work.payload, phase)


def test_actual_common_preview_snapshot_serializes_native_owner_ids_as_jsonb(work):
    phase = service.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    original_basis = phase.bound.material_read.source_basis
    assert original_basis["owners"]["product"]["id"] is work.product.id
    review = service.preview_prepared(
        work.s, work.ctx, work.command, work.product, work.payload, phase
    )
    # Match the real Confirmation.snapshot JSONB binding, with its default
    # JSON serializer and no default=str workaround or HTTP encoder.
    confirmation = Confirmation(snapshot=review)
    dialect = PGDialect_psycopg()
    processor = Confirmation.__table__.c.snapshot.type.dialect_impl(dialect).bind_processor(dialect)
    saved_json = JsonbDumper(Jsonb).dump(processor(confirmation.snapshot))
    assert json.loads(saved_json) == review
    assert json.loads(json.dumps(review, allow_nan=False)) == review
    owners = review["read_basis"]["material_owner"]["owners"]
    assert owners["product"]["id"] == str(work.product.id)
    assert owners["project"]["id"] == str(work.material.scope.project_id)
    # Serialization changes the saved projection, never the owner's opaque
    # input or its exact same-UOW refresh binding.
    assert original_basis["owners"]["product"]["id"] is work.product.id


@pytest.mark.parametrize("change", ["key", "payload", "read_set", "scope", "actor"])
def test_phase_rejects_original_request_or_named_scope_substitution(work, change):
    phase = service.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    command, ctx = work.command, work.ctx
    if change == "key":
        command = command.model_copy(update={"idempotency_key": "a-different-original-key"})
    elif change == "payload":
        command = command.model_copy(update={"payload": {**command.payload, "reason": "changed"}})
    elif change == "read_set":
        command = command.model_copy(update={"source_read_set": []})
    elif change == "scope":
        command = command.model_copy(update={"product_id": uuid4()})
    else:
        ctx = replace(ctx, actor_id=uuid4(), requester_id=uuid4())
    with pytest.raises(DomainError):
        service.preview_prepared(work.s, ctx, command, work.product, work.payload, phase)


@pytest.mark.parametrize("field", ["qualified", "authorized", "roles", "purpose"])
def test_publication_plan_never_replaces_current_exact_manufacturing_authority(work, field):
    work.authority[field] = (
        [] if field == "roles" else ("different-purpose" if field == "purpose" else False)
    )
    with pytest.raises(DomainError):
        service.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    assert not work.s.new


@pytest.mark.parametrize("finite", [False, True])
def test_actual_common_t2_transition_saves_fixed_publication_and_real_reserved_receipt(
    work, finite
):
    expiry = work.now() + timedelta(minutes=10) if finite else None
    written = write(work, expiry=expiry)
    row, phase, proof, consumed, _, _ = written
    assert proof.consumed is True and consumed[1].expires_at == expiry
    assert row.receipt_id == row.prepared_receipt_id
    assert row.confirmation_id == row.shared_proof_id == proof.id
    assert (
        row.input_snapshot["original_key_sha256"]
        == sha256(work.command.idempotency_key.encode()).hexdigest()
    )
    assert "idempotency_key" not in row.input_snapshot["command"]
    assert "approval_token" not in row.input_snapshot["command"]["payload"]
    assert work.command.idempotency_key not in str(row.input_snapshot)
    assert work.payload.approval_token not in str(row.input_snapshot)
    row, receipt = finish(work, written)
    assert receipt.id == row.receipt_id and receipt.confirmation_id == proof.id
    assert row.body["qualification"] == "unknown" and row.body["manufacturing_release"] is None
    assert len(work.s.rows[Document]) == 4
    assert work.s.rows[Current][0].version_id == row.id
    assert work.material.baseline.status == "draft"
    assert all(value.status == "draft" for value in work.material.documents)
    assert not hasattr(row, "_publication_finalization")


def test_omitted_optional_command_fields_save_canonical_semantics_without_changing_request(work):
    raw_payload = deepcopy(work.command.payload)
    for field in ("valid_from", "valid_until"):
        raw_payload["applicability"].pop(field)
    work.command = work.command.model_copy(update={"payload": raw_payload})
    original_request = work.command.model_dump(mode="json")
    original_request_digest = common.command_digest(work.command)
    original_material_digest = common.material_digest(work.ctx, work.command, work.payload, service)
    written = write(work)
    row, phase, proof, consumed, _, _ = written
    stored_payload = row.input_snapshot["command"]["payload"]
    assert stored_payload == row.input_snapshot["semantic"] == service.semantic(work.payload)
    assert stored_payload["applicability"]["valid_from"] is None
    assert stored_payload["applicability"]["valid_until"] is None
    assert "approval_token" not in stored_payload
    assert row.input_snapshot["review"] == phase.review == proof.snapshot
    assert row.input_snapshot["plan"]["input_snapshot"] == stored_payload
    assert row.material_sha256 == consumed[1].material_sha256 == original_material_digest
    assert row.request_digest == original_request_digest
    row, receipt = finish(work, written)
    saved_command, saved_payload, _, _ = service._saved_input(row)
    assert (
        common.material_digest(work.ctx, saved_command, saved_payload, service)
        == original_material_digest
    )
    assert receipt.request_digest == original_request_digest == common.command_digest(work.command)
    assert work.command.model_dump(mode="json") == original_request
    assert "valid_from" not in work.command.payload["applicability"]
    # The saved projection has an exact SQL contract; semantic equivalence must
    # not hide a missing canonical key when rereading an immutable record.
    tampered = deepcopy(row.input_snapshot)
    tampered["command"]["payload"]["applicability"].pop("valid_from")
    row.input_snapshot = tampered
    with pytest.raises(DomainError) as error:
        service._saved_input(row)
    assert error.value.reason == "STORED_ATOM_MISMATCH"


def test_historical_consumed_flag_does_not_supply_this_invocation_consumption(work):
    phase, review, proof = prepare(work)
    set_committed_value(proof, "consumed", True)
    with pytest.raises(DomainError):
        consume(work, phase, review)
    assert work.s.rows.get(Publication, []) == []


def test_confirmation_snapshot_must_match_real_refreshed_review(work):
    phase, review, proof = prepare(work)
    set_committed_value(proof, "snapshot", {"invented": "approval"})
    with pytest.raises(DomainError) as error:
        consume(work, phase, review)
    assert error.value.reason == "CONFIRMATION_SCOPE_CHANGED"
    assert proof.consumed is False


@pytest.mark.parametrize("fault", ["source", "material", "authority-time", "proof-time", "grant"])
def test_all_final_owner_io_precedes_fresh_live_consumption_and_save_clock(work, fault):
    phase, review, proof = prepare(work, expiry=work.now() + timedelta(minutes=1))
    consumption = consume(work, phase, review)
    if fault == "source":
        work.evidence_hook = lambda: None
    elif fault == "material":
        work.material = work.material.model_copy(update={"product_revision": 99})
    elif fault == "authority-time":
        work.offset[0] = timedelta(hours=2)
    elif fault == "proof-time":
        work.offset[0] = timedelta(minutes=2)
    else:
        work.grant.expires_at = work.now() - timedelta(seconds=1)
    with pytest.raises(DomainError):
        service.apply_prepared_write(
            work.s,
            work.ctx,
            work.command,
            work.product,
            work.payload,
            phase,
            consumption=consumption,
        )
    assert work.s.rows.get(Publication, []) == []


def test_current_cas_keeps_previous_publication_and_fixed_draft_ledger(work):
    first, receipt = finish(work, write(work))
    first_body = deepcopy(first.body)
    payload = work.payload.model_copy(
        update={
            "previous_id": first.id,
            "expected_previous_revision": 1,
            "approval_token": "second-explicit-named-approval-token",
        }
    )
    work.payload = payload
    work.command = work.command.model_copy(
        update={
            "command_id": uuid4(),
            "idempotency_key": "second-publication-key",
            "payload": payload.model_dump(mode="json"),
        }
    )
    second, _ = finish(work, write(work))
    assert second.revision == 2 and second.series_id == first.series_id
    assert first.body == first_body and first.revision == 1
    assert work.s.rows[Current][0].epoch == 2
    assert work.s.rows[Current][0].version_id == second.id
    assert len(work.s.rows[Publication]) == 2
    old_row, old_view = service.get_publication(work.s, work.ctx, work.pid, first.id, revision=1)
    assert old_row is first and old_view["is_current"] is False
    assert old_view["receipt_id"] == str(receipt.id) and old_view["qualification"] == "unknown"


def test_successor_final_current_change_is_rejected_after_approval(work):
    first, _ = finish(work, write(work))
    work.payload = work.payload.model_copy(
        update={
            "previous_id": first.id,
            "expected_previous_revision": 1,
            "approval_token": "successor-explicit-named-approval-token",
        }
    )
    work.command = work.command.model_copy(
        update={
            "command_id": uuid4(),
            "idempotency_key": "successor-original-key",
            "payload": work.payload.model_dump(mode="json"),
        }
    )
    phase, review, proof = prepare(work)
    consumed = consume(work, phase, review)
    work.s.rows[Current][0].version_id = uuid4()
    with pytest.raises(DomainError):
        service.apply_prepared_write(
            work.s, work.ctx, work.command, work.product, work.payload, phase, consumption=consumed
        )
    assert len(work.s.rows[Publication]) == 1


def test_tail_actual_receipt_and_original_professional_group_cannot_be_replaced(work):
    written = write(work)
    work.retained = False
    with pytest.raises(DomainError):
        finish(work, written)
    assert not hasattr(written[0], "_publication_finalization")


def test_tail_checks_finite_t2_deadline_after_actual_refresh_and_common_flush(work):
    written = write(work, expiry=work.now() + timedelta(minutes=1))

    def advance_after_common_flush():
        work.offset[0] = timedelta(minutes=2)

    work.owner_hook = advance_after_common_flush
    with pytest.raises(DomainError):
        finish(work, written)
    assert not hasattr(written[0], "_publication_finalization")


def shared_publication(work):
    material = work.material.model_dump(mode="json")
    material["process_snapshot"]["visibility"] = "category"
    for view in [material["baseline"], *material["documents"]]:
        view["visibility"] = view["body"]["input"]["visibility"] = "category"
        view["body"]["process_snapshot"]["visibility"] = "category"
    rebuild_links(material)
    work.material = type(work.material).model_validate(material)
    work.payload = work.payload.model_copy(update={"visibility": "category"})
    work.command = work.command.model_copy(update={"payload": work.payload.model_dump(mode="json")})
    work.private_sources = False
    return finish(work, write(work))[0]


@pytest.mark.parametrize(
    "bound", [True, False, None, 1], ids=["true", "false", "none", "integer-one"]
)
def test_peer_reads_frozen_signature_without_private_key_or_original_actor_context(work, bound):
    row = shared_publication(work)
    peer = uuid4()
    work.ctx = replace(work.ctx, actor_id=peer, requester_id=peer)
    work.s.info["scope"] = (work.tenant, peer, peer, work.ctx.category_id)
    work.s.person = work.s.seed(
        Principal(
            id=peer,
            tenant_id=work.tenant,
            kind="human",
            active=True,
            access_epoch=1,
        )
    )
    work.s.grant = work.s.seed(
        Grant(
            id=uuid4(),
            tenant_id=work.tenant,
            category_id=work.ctx.category_id,
            principal_id=peer,
            can_write=True,
            expires_at=work.now() + timedelta(hours=1),
            access_epoch=1,
        )
    )
    work.s.hide_keys, work.s.peer_bound = True, bound
    # The installed immutable reciprocal storage guard established the common
    # group once. GET must not impersonate the writer or re-read its private key.
    _, view = service.get_publication(work.s, work.ctx, work.pid, row.id)
    assert view["qualification"] == "unknown"
    assert work.command.idempotency_key not in str(view)
    assert work.s.binding_calls == []
    assert work.s.info["scope"][1] == work.ctx.actor_id == peer != row.actor_id


def test_fixed_read_preserves_signature_and_explicit_proof_check_still_detects_corruption(work):
    row, _ = finish(work, write(work))
    _, view = service.get_publication(work.s, work.ctx, work.pid, row.id)
    assert view["is_current"] and view["source_status"] == "current"
    assert view["qualification"] == "unknown" and view["manufacturing_release"] is None
    work.s.rows[Outbox][0].correlation_id = uuid4()
    # This in-memory corruption is prevented by the actual immutable DB guard.
    # A fixed read does not rescan the original common closure; T2 reproof does.
    assert service.get_publication(work.s, work.ctx, work.pid, row.id)[1] == view
    with pytest.raises(DomainError):
        service._read_record(work.s, work.ctx, work.pid, row)


def test_replay_uses_same_category_bound_common_intent_and_reads_actual_old_group(work):
    row, _ = finish(work, write(work))
    assert service.replay_subject(work.s, work.ctx, work.command, work.product, work.payload) is row
    changed = work.command.model_copy(update={"category_id": uuid4()})
    assert service.replay_subject(work.s, work.ctx, changed, work.product, work.payload) is None


@pytest.mark.parametrize("status", [403, 409])
def test_fixed_read_hides_inaccessible_sources_but_retains_readable_withdrawn_history(
    work, monkeypatch, status
):
    row, _ = finish(work, write(work))

    def unavailable(*args, **kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "Explicit source visibility boundary", status)

    monkeypatch.setattr(service.evidence, "_evidence", unavailable)
    if status == 403:
        with pytest.raises(DomainError) as caught:
            service.get_publication(work.s, work.ctx, work.pid, row.id)
        assert caught.value.status == 403
    else:
        _, view = service.get_publication(work.s, work.ctx, work.pid, row.id)
        assert view["source_status"] == "needs_recheck"
        assert view["body"] == row.body
