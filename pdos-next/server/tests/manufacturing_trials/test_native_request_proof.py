"""Actual T1 phases/common consumer with explicit, no-connect owner IO.

The ports below substitute current/material/professional SELECT results only.
No case proves real authority, PostgreSQL storage, RLS or measured latency.
The tests exercise the actual phase, loaded Confirmation, consumption marker,
saved input and GET paths while expensive owner entrypoints are forbidden.
"""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from manufacturing_preparation.test_expiry import authority_result
from manufacturing_preparation.test_publication_service import MemorySession
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from pdos_next import service as common
from pdos_next.contracts import Command
from pdos_next.domain.manufacturing_baseline import consumption as consumption_module
from pdos_next.domain.manufacturing_baseline import service as preparation
from pdos_next.domain.manufacturing_trials import native_service as native
from pdos_next.domain.manufacturing_trials.native_material_owner import NativePilotMaterial
from pdos_next.domain.manufacturing_trials.native_models import NativePilotCurrent as Current
from pdos_next.domain.manufacturing_trials.native_models import (
    NativePilotObservation as Observation,
)
from pdos_next.domain.manufacturing_trials.native_models import NativePilotRun as Pilot
from pdos_next.domain.manufacturing_trials.native_schemas import (
    PilotCreatePayload,
    PilotResultPayload,
    semantic,
)
from pdos_next.domain.projects.models import Project
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Grant, Principal, Product, RequestKey
from pdos_next.request_proof import request_proof

from .helpers import SCOPE, creation, record

AT = datetime(2026, 10, 17, 12, tzinfo=UTC)
TOKEN = "explicit-loaded-common-T1-token"


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromtimestamp(AT.timestamp(), tz=tz)


def forbidden(*_args, **_kwargs):
    raise AssertionError("The request must not reconstruct owners or historical authority")


class NativeSession(MemorySession):
    def flush(self, objects=None):
        super().flush(objects)
        if objects is None:
            # Complete the same identity-map clean transition as an actual SQL
            # flush. The inherited no-connect driver writes only ORM row data.
            for state in self.identity_map.all_states():
                state._commit_all(state.dict, self.identity_map)


class OwnerIO:
    """Leaf IO driver; production phases and common proof handling stay real."""

    def __init__(self, frame, statistics=False):
        self.frame, self.statistics = frame, statistics
        self.reads, self.currents = [], []
        self.ok, self.forbid_read = True, False

    def read(self, s, ctx, pid, details, statistics=None, **options):
        if self.forbid_read:
            forbidden()
        f = self.frame
        assert s is f.s and ctx is f.ctx and pid == f.pid and details == f.create.details
        self.reads.append(options)
        if self.statistics:
            material = {"statistics": None, "record": options.get("record")}
            material = native.json_snapshot(material)
            return SimpleNamespace(
                material=material,
                fixed=None,
                projection=None,
                batch=None,
                sources=(details.source,),
                required_source_read_set=tuple(f.command.source_read_set),
                gaps=(),
                source_basis={"statistics_watermark": "explicit IO"},
                checked_at=AT,
            )
        return SimpleNamespace(
            material=f.material,
            source_basis={"product_watermark": f.product.revision},
            sources=(details.source,),
            required_source_read_set=tuple(f.command.source_read_set),
            checked_at=AT,
        )

    def refresh(self, *_args, **_kwargs):
        forbidden()

    def current(self, s, ctx, pid, material, basis):
        assert s is self.frame.s and ctx is self.frame.ctx and pid == self.frame.pid
        self.currents.append((deepcopy(material), deepcopy(basis)))
        return self.ok


@pytest.fixture
def work(monkeypatch):
    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    engine = create_engine("postgresql+psycopg://unused/never_connect")
    event.listen(engine, "do_connect", forbidden)
    s = NativeSession(engine)
    s.begin()
    actor, category = UUID(int=70), UUID(int=71)
    ctx = common.Context(SCOPE.tenant_id, actor, actor, category_id=category)
    product = s.seed(
        Product(
            id=SCOPE.product_id,
            tenant_id=ctx.tenant_id,
            category_id=category,
            owner_id=actor,
            revision=7,
        )
    )
    s.person = s.seed(
        Principal(id=actor, tenant_id=ctx.tenant_id, kind="human", active=True, access_epoch=1)
    )
    s.grant = s.seed(
        Grant(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=category,
            principal_id=actor,
            can_write=True,
            expires_at=AT + timedelta(hours=1),
            access_epoch=1,
        )
    )
    s.product, s.clock = product, lambda: AT
    s.info["scope"] = (ctx.tenant_id, actor, actor, category)
    request_proof(s).scope_locks.add(product.id)  # Explicit model-gate IO substitute.
    payload = PilotCreatePayload(
        project_id=SCOPE.project_id, details=creation(), confirmation_token=TOKEN
    )
    project = s.seed(
        Project(
            id=SCOPE.project_id,
            tenant_id=ctx.tenant_id,
            category_id=category,
            product_id=product.id,
            owner_id=actor,
            visibility="private",
            purpose=payload.details.purpose,
        )
    )
    f = SimpleNamespace(
        s=s,
        engine=engine,
        ctx=ctx,
        tenant=ctx.tenant_id,
        actor=actor,
        pid=product.id,
        product=product,
        project=project,
        create=payload,
        payload=payload,
        source_status="current",
        signature_ok=True,
        authority_revision="current-authority-watermark",
        authority_calls=[],
        evidence_calls=[],
        signature_calls=[],
    )
    f.command = Command(
        command_id=uuid4(),
        idempotency_key="原始T1请求键-仅真实RequestKey保留",
        category_id=category,
        product_id=product.id,
        expected_revision=7,
        operation=native.CREATE_OPERATION,
        source_read_set=[{"artifact_id": payload.details.source.id, "expected_revision": 1}],
        payload=payload.model_dump(mode="json"),
    )
    f.material = NativePilotMaterial(
        scope=SCOPE,
        category_id=category,
        product_revision=7,
        purpose=project.purpose,
        basis=payload.details.basis,
        build={},
        lot={},
        actual_configuration={},
        engineering_configuration={},
        process={},
        publication=None,
        gaps=(),
    )
    runtime = native.configure(engine)
    f.material_io, f.statistics_io = OwnerIO(f), OwnerIO(f, statistics=True)
    engine._pdos_native_pilot = native.Runtime(
        f.material_io, f.statistics_io, runtime.consumption, native
    )

    def professional_io(session, caller, pid, project_id, operation, purpose, at, **options):
        assert session is s and caller is ctx
        assert (pid, project_id, operation, purpose) == (
            product.id,
            project.id,
            f.command.operation,
            project.purpose,
        )
        f.authority_calls.append(options)
        result = authority_result(f, project, at)
        result["facts_revision"] = f.authority_revision
        return result

    def evidence_io(session, caller, pid, reads, sources=(), **options):
        assert session is s and caller is ctx and pid == product.id
        f.evidence_calls.append((deepcopy(reads), sources, options))
        return (
            {
                value["artifact_id"]: {"revision": value["expected_revision"], "sha256": "a" * 64}
                for value in reads
            },
            True,
            set(),
        )

    def signature_io(session, caller, pid, project_id, snapshot):
        assert session is s and caller is ctx
        assert (pid, project_id) == (f.pid, f.project.id)
        assert snapshot["subject_id"] == str(f.actor)
        f.signature_calls.append(deepcopy(snapshot))
        return f.signature_ok

    monkeypatch.setattr(preparation.professional, "assess", professional_io)
    monkeypatch.setattr(native.evidence, "_evidence", evidence_io)
    monkeypatch.setattr(native.configurations, "_source_state", lambda *_args: f.source_status)
    monkeypatch.setattr(native, "now", lambda: AT)
    monkeypatch.setattr(preparation, "now", lambda: AT)
    monkeypatch.setattr(common, "now", lambda: AT)
    monkeypatch.setattr(consumption_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(native, "signature_current", signature_io)
    yield f
    s.close()
    engine.dispose()


def preview(work):
    phase = native.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    review = native.preview_prepared(
        work.s, work.ctx, work.command, work.product, work.payload, phase
    )
    return phase, review


def confirmation(work, review):
    return work.s.seed(
        Confirmation(
            id=uuid4(),
            tenant_id=work.tenant,
            category_id=work.ctx.category_id,
            product_id=work.pid,
            actor_id=work.actor,
            subject_id=work.pid,
            subject_type="product",
            operation=work.command.operation,
            revision=work.product.revision,
            token_hash=common.digest(TOKEN),
            payload_digest=common.material_digest(work.ctx, work.command, work.payload, native),
            snapshot=deepcopy(review),
            consumed=False,
            created_at=FrozenDatetime.fromtimestamp(
                (AT - timedelta(seconds=1)).timestamp(), tz=UTC
            ),
            expires_at=AT + timedelta(minutes=2),
        )
    )


def forbid_reconstruction(monkeypatch, work, *, chain=True):
    work.material_io.forbid_read = work.statistics_io.forbid_read = True
    monkeypatch.setattr(native, "_load", forbidden)
    monkeypatch.setattr(native.evidence, "_evidence", forbidden)
    if chain:
        monkeypatch.setattr(native, "_chain", forbidden)


def write(work, monkeypatch):
    _, review = preview(work)
    proof = confirmation(work, review)
    with monkeypatch.context() as check:
        forbid_reconstruction(check, work)
        phase, reused = native.prepare_write_review(
            work.s, work.ctx, work.command, work.product, work.payload, proof=proof
        )
        check.setattr(common, "material_confirmation_for", forbidden)
        consumed = common.consume_material_confirmation(
            work.s,
            work.ctx,
            work.command,
            work.product,
            work.payload,
            native,
            prepared_review=reused,
            write_phase=phase,
            prepared_confirmation=proof,
        )
        row, subject_type, visibility = native.apply_prepared_write(
            work.s,
            work.ctx,
            work.command,
            work.product,
            work.payload,
            phase,
            consumption=consumed,
        )
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
        native.finalize_receipt(
            work.s, work.ctx, work.command, work.product, work.payload, row, receipt
        )
    return row, receipt, phase, proof, review


def result_request(work):
    # A separate request's selected SQL rows may now include the committed root;
    # drop only the explicit SELECT driver's old read cache, retaining ORM rows.
    held = request_proof(work.s)
    held.read_rows.clear()
    held.scalar_rows.clear()
    work.material_io.forbid_read = work.statistics_io.forbid_read = False
    work.payload = PilotResultPayload(
        pilot_id=work.create.details.pilot_id,
        expected_pilot_revision=1,
        record=record(SimpleNamespace(details=work.create.details, revision=1)),
        confirmation_token=TOKEN,
    )
    work.command = work.command.model_copy(
        update={
            "command_id": uuid4(),
            "idempotency_key": "本次原始观察的独立原请求键",
            "operation": native.RESULT_OPERATION,
            "payload": work.payload.model_dump(mode="json"),
        }
    )


def test_preview_uses_one_loaded_owner_proof_and_returns_an_independent_review(work):
    phase = native.prepare_preview(work.s, work.ctx, work.command, work.product, work.payload)
    counts = (len(work.material_io.reads), len(work.statistics_io.reads), len(work.authority_calls))
    assert counts == (1, 1, 1)
    work.material_io.forbid_read = work.statistics_io.forbid_read = True
    review = native.preview_prepared(
        work.s, work.ctx, work.command, work.product, work.payload, phase
    )
    assert counts == (
        len(work.material_io.reads),
        len(work.statistics_io.reads),
        len(work.authority_calls),
    )
    assert review == phase.review and review is not phase.review
    review["after"]["qualification"] = "caller mutation"
    assert phase.review["after"]["qualification"] == "unknown"
    with pytest.raises(DomainError):
        native.preview_prepared(work.s, work.ctx, work.command, work.product, work.payload, phase)


def test_actual_common_t1_save_and_tail_reuse_snapshot_without_owner_or_history_reconstruction(
    work, monkeypatch
):
    row, receipt, phase, proof, review = write(work, monkeypatch)
    assert proof.consumed is True and phase.used is True
    assert receipt.id == row.receipt_id == row.prepared_receipt_id
    assert receipt.confirmation_id == row.shared_proof_id == proof.id
    assert row.shared_proof_revision == 7 and row.revision == 1
    assert row.input_snapshot["review"] == review == proof.snapshot
    assert row.input_snapshot["semantic"] == semantic(work.payload)
    assert (
        row.input_snapshot["original_key_sha256"]
        == sha256(work.command.idempotency_key.encode("utf-8")).hexdigest()
    )
    assert "idempotency_key" not in row.input_snapshot["command"]
    assert "confirmation_token" not in row.input_snapshot["command"]["payload"]
    assert len(work.material_io.reads) == len(work.statistics_io.reads) == 1
    assert len(work.material_io.currents) == len(work.statistics_io.currents) == 1
    assert len(work.authority_calls) == 2  # Preview, then one current write assessment.
    assert not hasattr(row, "_pilot_finalization")


def test_observation_uses_the_confirmed_current_once_and_keeps_root_material_immutable(
    work, monkeypatch
):
    root, _, _, _, _ = write(work, monkeypatch)
    original = deepcopy(root.input_snapshot)
    result_request(work)
    query_start = len(work.s.queries)
    row, receipt, _, proof, _ = write(work, monkeypatch)
    pointer = work.s.rows[Current][0]
    assert type(row) is Observation and row.pilot_id == root.id
    assert row.pilot_revision_before == 1 and row.revision == receipt.subject_revision == 2
    assert row.shared_proof_revision == proof.revision == 7
    assert (pointer.revision, pointer.epoch, pointer.latest_observation_id) == (2, 2, row.id)
    assert root.revision == 1 and root.input_snapshot == original
    # Snapshot lookup upgrades the selected Current's lock once; apply/tail use
    # the actual pointer retained by Prepared rather than selecting it again.
    locked = [
        query
        for query in work.s.queries[query_start:]
        if query.column_descriptions[0]["entity"] is Current and query._for_update_arg is not None
    ]
    assert len(locked) == 1


@pytest.mark.parametrize("fault", ["pilot_current", "signed_authority_current"])
def test_result_confirmation_rejects_changed_current_without_reconstructing_history(
    work, monkeypatch, fault
):
    write(work, monkeypatch)
    result_request(work)
    _, review = preview(work)
    proof = confirmation(work, review)
    if fault == "pilot_current":
        pointer = work.s.rows[Current][0]
        pointer.revision, pointer.epoch, pointer.latest_observation_id = 2, 2, uuid4()
    else:
        work.signature_ok = False
    forbid_reconstruction(monkeypatch, work)
    with pytest.raises(DomainError):
        native.prepare_write_review(
            work.s, work.ctx, work.command, work.product, work.payload, proof=proof
        )
    assert proof.consumed is False
    assert work.s.rows.get(Observation, []) == []


@pytest.mark.parametrize("fault", ["product", "material", "statistics", "source", "authority"])
def test_confirmed_snapshot_rejects_changed_direct_watermark_without_rebuilding(
    work, monkeypatch, fault
):
    _, review = preview(work)
    proof = confirmation(work, review)
    if fault == "product":
        work.product.revision += 1
    elif fault == "material":
        work.material_io.ok = False
    elif fault == "statistics":
        work.statistics_io.ok = False
    elif fault == "source":
        work.source_status = "needs_recheck"
    else:
        work.authority_revision = "new current authority"
    forbid_reconstruction(monkeypatch, work)
    with pytest.raises(DomainError):
        native.prepare_write_review(
            work.s, work.ctx, work.command, work.product, work.payload, proof=proof
        )
    assert proof.consumed is False
    assert work.s.rows.get(Pilot, []) == []


@pytest.mark.parametrize("fault", ["payload", "readset"])
def test_confirmation_rejects_different_payload_or_sources_before_lightweight_owner_reads(
    work, monkeypatch, fault
):
    _, review = preview(work)
    proof = confirmation(work, review)
    if fault == "payload":
        work.payload = work.payload.model_copy(update={"visibility": "category"})
        work.command = work.command.model_copy(
            update={"payload": work.payload.model_dump(mode="json")}
        )
    else:
        work.command = work.command.model_copy(update={"source_read_set": []})
    forbid_reconstruction(monkeypatch, work)
    with pytest.raises(DomainError, match="确认载荷"):
        native.prepare_write_review(
            work.s, work.ctx, work.command, work.product, work.payload, proof=proof
        )
    assert work.material_io.currents == work.statistics_io.currents == []
    assert proof.consumed is False


def test_get_keeps_storage_guarded_history_and_uses_only_current_owner_watermarks(
    work, monkeypatch
):
    row, _, _, _, _ = write(work, monkeypatch)
    proof = request_proof(work.s)
    proof.read_rows.clear()
    proof.scalar_rows.clear()
    calls = len(work.authority_calls)
    forbid_reconstruction(monkeypatch, work, chain=False)
    monkeypatch.setattr(preparation.professional, "assess", forbidden)
    root, view = native.get_pilot(work.s, work.ctx, work.pid, row.id)
    assert root is row
    assert view["pilot"]["source_status"] == "current"
    assert view["pilot"]["statistics_basis"] is None
    assert view["current"] == {"revision": 1, "epoch": 1, "latest_observation_id": None}
    assert len(work.authority_calls) == calls
    assert view["qualification"] == "unknown" and view["start_authorized"] is False
    assert view["manufacturing_release"] is None
    work.material_io.ok = False
    _, stale = native.get_pilot(work.s, work.ctx, work.pid, row.id)
    assert stale["pilot"]["source_status"] == "needs_recheck"
    assert row.material_snapshot == view["pilot"]["material"]


@pytest.mark.parametrize("private_kind", ["project", "physical"])
def test_shared_pilot_cannot_expand_readable_private_parent_facts(work, private_kind):
    work.project.visibility = "category"
    if private_kind == "project":
        work.project.visibility = "private"
    else:
        work.material = work.material.model_copy(update={"build": {"visibility": "private"}})
    work.create = work.create.model_copy(update={"visibility": "category"})
    work.payload = work.create
    work.command = work.command.model_copy(update={"payload": work.payload.model_dump(mode="json")})
    with pytest.raises(DomainError) as caught:
        preview(work)
    assert caught.value.status == 403
