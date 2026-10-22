"""Category creation service composition; no database, model or outbound calls."""

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.clock import now
from pdos_next.domain.preproject import category_creation as creation
from pdos_next.domain.preproject.category_creation_models import CategoryCreationConfirmation
from pdos_next.domain.preproject.category_models import KnowledgeEntry, ParameterVersion
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Category, Grant, Outbox, Receipt, RequestKey
from pdos_next.research.types import Snapshot
from pdos_next.service import Context, digest


class MemorySession:
    def __init__(self, *answers):
        self.answers, self.added, self.info = iter(answers), [], {}
        self.flushes = []

    def scalar(self, query):
        if "max(" in str(query):
            return 2
        return next(self.answers)

    def add(self, row):
        self.added.append(row)

    def add_all(self, rows):
        self.added.extend(rows)

    def flush(self, rows=None):
        self.flushes.append(tuple(type(row) for row in rows or self.added))
        for row in rows or self.added:
            if hasattr(row, "created_at") and row.created_at is None:
                row.created_at = now()

    def begin_nested(self):
        return nullcontext()


@pytest.fixture
def candidate(monkeypatch):
    from pdos_next.agent_kernel import category_candidate

    tenant, requester, writer, run_id = (uuid4() for _ in range(4))
    actor = NS(id=requester, tenant_id=tenant, active=True, kind="human", access_epoch=7)
    ctx = Context(tenant, requester, requester)
    body = "First actual public quote\nSecond public quotation\n"
    snapshot = Snapshot(
        uuid4(),
        "https://example.test/original",
        "https://example.test/final",
        "Actual title",
        "Actual summary",
        datetime(2026, 10, 11, tzinfo=UTC),
        body,
        sha256(body.encode()).hexdigest(),
        "synthetic",
        "public_web",
    )
    calls = [uuid4(), uuid4()]
    ref = {
        "type": "snapshot",
        "id": str(snapshot.id),
        "version": 1,
        "line": 1,
        "quote": "First actual public quote",
    }
    groups = {
        "knowledge": [
            {
                "kind": "voice",
                "content": {
                    "label": "反馈",
                    "source_platform": "public",
                    "representative_refs": [ref, ref],
                },
                "source_refs": [ref],
            }
        ],
        "parameters": [
            {
                "key": "pressure",
                "name": "压力",
                "value_type": "number",
                "direction": "higher",
                "unit": "kPa",
                "change_note": "实际候选",
            }
        ],
        "snapshot_refs": [
            {"call_id": str(call), "content_hash": snapshot.content_hash} for call in calls
        ],
    }
    data = creation.CategoryCreate(
        key="actual-candidate",
        name="实际候选品类",
        purpose="公开研究",
        groups=groups,
        deidentified_confirmed=True,
        prepared_by_run_id=run_id,
        candidate_digest="a" * 64,
        idempotency_key="category-candidate-test",
    )
    proof = NS(
        run=NS(
            id=run_id, tenant_id=tenant, writer_id=writer, requester_id=requester, cancel_epoch=0
        ),
        event=NS(
            id=uuid4(),
            body={
                "candidate_digest": data.candidate_digest,
                "input": {
                    "key": data.key,
                    "name": data.name,
                    "purpose": data.purpose,
                    "groups": data.groups.model_dump(mode="json"),
                },
            },
        ),
        snapshots=tuple(
            NS(snapshot=snapshot, read_call_id=call, snapshot_digest=digest(asdict(snapshot)))
            for call in calls
        ),
    )
    checked = []

    def validate(session, actual_ctx, actual_data):
        checked.append((session, actual_ctx, actual_data))
        return proof

    monkeypatch.setattr(category_candidate, "validate", validate)
    return NS(
        actor=actor,
        ctx=ctx,
        data=data,
        proof=proof,
        checked=checked,
        snapshot=snapshot,
        calls=calls,
        validator=validate,
        candidate_module=category_candidate,
    )


def preview(f):
    session = MemorySession(f.actor, None)
    result = creation.preview(session, f.ctx, f.data)
    f.data.confirmation_token = result["confirmation_token"]
    return result, session.added[0]


def test_preview_keeps_server_candidate_provenance_and_creates_only_confirmation(candidate):
    f = candidate
    result, confirmation = preview(f)
    assert isinstance(confirmation, CategoryCreationConfirmation)
    assert result["origin"] == "ai_draft" and result["writer_id"] == str(f.proof.run.writer_id)
    assert result["prepared_by_run_id"] == str(f.proof.run.id)
    assert result["candidate"]["input"] == f.proof.event.body["input"]
    assert len(result["candidate"]["sources"]) == 2
    assert result["groups"]["snapshot_refs"]["selected_count"] == 2
    assert result["groups"]["knowledge"]["depends_on"] == "snapshot_refs"
    assert confirmation.snapshot["material_digest"] == f.data.candidate_digest
    assert confirmation.snapshot["category_candidate_event_id"] == str(f.proof.event.id)
    assert confirmation.snapshot["actor_access_epoch"] == f.actor.access_epoch
    assert confirmation.token_hash == digest(result["confirmation_token"])
    assert len(f.checked) == 1 and f.checked[0][1] is f.ctx


def test_create_retains_ai_authorship_and_registers_each_snapshot_once(candidate):
    f = candidate
    _, confirmation = preview(f)
    session = MemorySession(f.actor, None, None, confirmation, None)
    result = creation.create(session, f.ctx, f.data)
    assert len(f.checked) == 2 and confirmation.consumed
    category = next(row for row in session.added if isinstance(row, Category))
    assert category.created_by_run_id == f.proof.run.id and category.owner_id == f.ctx.actor_id
    grants = [row for row in session.added if isinstance(row, Grant)]
    assert len(grants) == 1 and grants[0].principal_id == f.ctx.actor_id and grants[0].can_write
    snapshots = [row for row in session.added if isinstance(row, PublicWebSnapshot)]
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.id == f.snapshot.id and snapshot.markdown == f.snapshot.markdown
    assert snapshot.visibility == "category" and snapshot.registered_by_run_id == f.proof.run.id
    assert snapshot.owner_id == f.ctx.actor_id and snapshot.category_id == category.id
    materials = [
        row for row in session.added if isinstance(row, (KnowledgeEntry, ParameterVersion))
    ]
    assert len(materials) == 2
    for row in materials:
        assert row.origin == "ai_draft" and row.writer_id == f.proof.run.writer_id
        assert row.run_id == f.proof.run.id and row.confirmed_by == f.ctx.actor_id
        assert row.prepared_candidate_id is None and row.receipt_id == snapshot.receipt_id
    voice = next(row for row in materials if isinstance(row, KnowledgeEntry))
    assert voice.content["sample_size"] == 1  # Repeated refs cannot inflate the sample.
    receipt = next(row for row in session.added if isinstance(row, Receipt))
    assert (
        receipt.actor_id == f.ctx.actor_id
        and receipt.agent_run_id is None
        and receipt.run_id is None
    )
    manifest = receipt.result
    assert manifest["proof_version"] == 1
    assert manifest["prepared_by_run_id"] == manifest["registered_by_run_id"] == str(f.proof.run.id)
    assert manifest["category_candidate_event_id"] == str(f.proof.event.id)
    assert manifest["candidate_digest"] == f.data.candidate_digest
    assert manifest["snapshot_refs"] == [
        {
            "snapshot_id": str(f.snapshot.id),
            "content_hash": f.snapshot.content_hash,
            "call_id": str(f.calls[0]),
        }
    ]
    assert manifest["groups_digest"] == digest(f.data.groups.model_dump(mode="json"))
    assert {Audit, Outbox, RequestKey} <= {type(row) for row in session.added}
    assert result["result"] == manifest and result["agent_run_id"] is None


def test_omitted_complete_groups_create_only_the_selected_material(candidate):
    f = candidate
    f.data.groups.knowledge = []
    f.data.groups.snapshot_refs = []
    f.proof.snapshots = ()
    result, confirmation = preview(f)
    assert result["groups"]["knowledge"] == {
        "selected_count": 0,
        "available_count": 1,
        "depends_on": "category",
    }
    session = MemorySession(f.actor, None, None, confirmation, None)
    creation.create(session, f.ctx, f.data)
    assert not any(isinstance(row, (PublicWebSnapshot, KnowledgeEntry)) for row in session.added)
    assert any(isinstance(row, ParameterVersion) for row in session.added)


def test_deidentification_must_be_confirmed_before_candidate_admission(candidate):
    f = candidate
    f.data.deidentified_confirmed = False
    with pytest.raises(DomainError) as error:
        creation.preview(MemorySession(f.actor), f.ctx, f.data)
    assert error.value.detail["reason"] == "deidentification_not_confirmed"
    assert f.checked == []


@pytest.mark.parametrize("change", ["payload", "actor_epoch", "expiry", "candidate_event"])
def test_final_confirmation_rechecks_exact_material_and_authority(candidate, change):
    f = candidate
    _, confirmation = preview(f)
    if change == "payload":
        f.data.name += "改变"
    elif change == "actor_epoch":
        f.actor.access_epoch += 1
    elif change == "expiry":
        confirmation.expires_at = now() - timedelta(seconds=1)
    else:
        f.proof.event.id = uuid4()
    session = MemorySession(f.actor, None, None, confirmation)
    with pytest.raises(DomainError) as error:
        creation.create(session, f.ctx, f.data)
    assert error.value.detail["reason"] == "preview_required" and session.added == []
    assert not confirmation.consumed


def test_candidate_revalidation_failure_prevents_all_creation(candidate, monkeypatch):
    f = candidate
    _, confirmation = preview(f)

    def unavailable(*_):
        raise DomainError("SOURCE_UNAVAILABLE", "Original immutable source is missing")

    monkeypatch.setattr(f.candidate_module, "validate", unavailable)
    session = MemorySession(f.actor, None, None)
    with pytest.raises(DomainError):
        creation.create(session, f.ctx, f.data)
    assert session.added == [] and not confirmation.consumed


def test_unbound_research_refs_cannot_enter_human_creation(candidate):
    f = candidate
    f.data.prepared_by_run_id = f.data.candidate_digest = None
    with pytest.raises(DomainError) as error:
        creation._validate(None, None, f.data)
    assert error.value.detail["reason"] == "category_candidate_required"
    assert f.checked == []


def test_create_does_not_modify_the_sealed_candidate_groups(candidate):
    f = candidate
    saved = deepcopy(f.proof.event.body)
    _, confirmation = preview(f)
    creation.create(MemorySession(f.actor, None, None, confirmation, None), f.ctx, f.data)
    assert f.proof.event.body == saved
    assert "sample_size" not in f.data.groups.knowledge[0].content
