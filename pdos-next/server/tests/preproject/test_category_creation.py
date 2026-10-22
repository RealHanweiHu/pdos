"""Category creation admission and application-role transaction checks."""

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.clock import now, using_clock
from pdos_next.database import tenant_session
from pdos_next.domain.preproject import category_creation as creation
from pdos_next.domain.preproject.category_creation import CategoryCreate, InitialGroups
from pdos_next.domain.preproject.category_creation_models import CategoryCreationConfirmation
from pdos_next.domain.preproject.category_models import (
    KnowledgeCurrent,
    KnowledgeEntry,
    ParameterCurrent,
    ParameterVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Category, Grant, Outbox, Receipt, RequestKey
from pdos_next.service import Context


def data(**changes):
    return CategoryCreate(
        key="synthetic-category",
        name="合成品类",
        purpose="合成研究用途",
        deidentified_confirmed=True,
        idempotency_key=str(uuid4()),
        **changes,
    )


class MemorySession:
    """Only storage plumbing; real domain proof validation and row creation run."""

    def __init__(self, *answers):
        self.answers, self.added, self.info = iter(answers), [], {}

    def scalar(self, query):
        return next(self.answers)

    def add(self, row):
        self.added.append(row)

    def add_all(self, rows):
        self.added.extend(rows)

    def flush(self, rows=None):
        for row in rows or self.added:
            if hasattr(row, "created_at") and row.created_at is None:
                row.created_at = now()

    def begin_nested(self):
        return nullcontext()


def actor_context():
    tenant, person = uuid4(), uuid4()
    actor = SimpleNamespace(id=person, tenant_id=tenant, active=True, kind="human", access_epoch=1)
    return actor, Context(tenant, person, person)


@pytest.mark.parametrize("key", creation.SEED_KEYS)
def test_unit_seed_preserves_uncertainty_and_independent_groups(key):
    seed = creation.load_seed(key)
    body = CategoryCreate(
        **{k: seed[k] for k in ("key", "name", "purpose", "seed_key", "groups")},
        deidentified_confirmed=True,
        idempotency_key=str(uuid4()),
    )
    raw = seed["material"]["document"]["categories"][0]
    assert len(body.groups.parameters) == len(raw["parameters"])
    assert all(p["origin"] == "ai_draft" for p in raw["parameters"])
    assert any(p["status"] == "expert_pending" for p in raw["parameters"])
    assert "https://" in seed["material"]["sources_markdown"]
    regulations = [k for k in body.groups.knowledge if k.kind == "regulation"]
    assert [k.content["material"] for k in regulations] == raw["regulations"]["items"]
    assert creation._validate(None, None, body)["material"] == seed["material"]
    for group in ("knowledge", "parameters"):
        selection = body.model_copy(deep=True)
        setattr(selection.groups, group, [])
        assert creation._validate(None, None, selection)
    for projected, original in zip(body.groups.parameters, raw["parameters"], strict=True):
        assert projected.value_type == (
            "text" if original["value_type"] == "enum_set" else original["value_type"]
        )
    tampered = body.model_copy(deep=True)
    tampered.groups.parameters[0].name = "伪造名称"
    with pytest.raises(DomainError) as error:
        creation._validate(None, None, tampered)
    assert error.value.detail["reason"] == "seed_material_changed"


def test_unit_inputs_reject_origin_duplicate_keys_and_unpaired_candidate():
    with pytest.raises(ValidationError):
        data(origin="imported")
    item = dict(
        key="pressure", name="压力", value_type="number", direction="higher", change_note="初始"
    )
    with pytest.raises(ValidationError):
        InitialGroups(parameters=[item, item])
    parameter = InitialGroups(parameters=[item]).parameters[0]
    assert parameter.unit is None and parameter.acceptance_criterion is None
    with pytest.raises(ValidationError):
        data(prepared_by_run_id=uuid4())


def test_unit_sources_and_model_ports_fail_closed():
    source = dict(
        kind="boundary",
        content={"definition": "边界"},
        source_refs=[dict(type="snapshot", id=str(uuid4()), version=1, line=1, quote="片段")],
    )
    with pytest.raises(DomainError) as error:
        creation._validate(None, None, data(groups={"knowledge": [source]}))
    assert error.value.detail["reason"] == "private_source_in_shared"
    _, ctx = actor_context()
    with pytest.raises(DomainError) as error:
        creation._validate(
            MemorySession(None),
            ctx,
            data(prepared_by_run_id=uuid4(), candidate_digest="forged"),
        )
    assert error.value.detail["reason"] == "category_candidate_requester_mismatch"


def test_unit_actor_and_deidentification():
    actor, ctx = actor_context()
    actor.kind = "agent"
    with pytest.raises(DomainError) as error:
        creation.preview(MemorySession(actor), ctx, data())
    assert error.value.detail["reason"] == "human_only"
    actor.kind = "human"
    with pytest.raises(DomainError) as error:
        creation.preview(
            MemorySession(actor), ctx, data().model_copy(update={"deidentified_confirmed": False})
        )
    assert error.value.detail["reason"] == "deidentification_not_confirmed"


def test_unit_preview_writes_only_proof_and_create_consumes_once(monkeypatch):
    monkeypatch.setattr("pdos_next.category_scope.category_scope", lambda *args, **kwargs: None)
    actor, ctx = actor_context()
    payload = data(
        groups={
            "parameters": [
                {
                    "key": "pressure",
                    "name": "压力",
                    "value_type": "number",
                    "direction": "higher",
                    "change_note": "初始",
                }
            ]
        }
    )
    preview_session = MemorySession(actor, None)
    view = creation.preview(preview_session, ctx, payload)
    assert len(preview_session.added) == 1
    proof = preview_session.added[0]
    assert isinstance(proof, CategoryCreationConfirmation)
    assert proof.token_hash != view["confirmation_token"]
    payload.confirmation_token = view["confirmation_token"]
    write_session = MemorySession(actor, None, None, proof, None)
    result = creation.create(write_session, ctx, payload)
    assert result["category_id"] == str(proof.reserved_category_id)
    assert proof.consumed
    assert {type(row) for row in write_session.added} == {
        Category,
        Grant,
        ParameterVersion,
        ParameterCurrent,
        Receipt,
        RequestKey,
        Audit,
        Outbox,
    }
    parameter = next(row for row in write_session.added if isinstance(row, ParameterVersion))
    assert parameter.origin == "human" and parameter.unit is None and parameter.run_id is None
    with pytest.raises(DomainError) as error:
        creation.create(MemorySession(actor, None, None, proof), ctx, payload)
    assert error.value.detail["reason"] == "preview_required"


@pytest.mark.parametrize("change", ["payload", "epoch", "expiry"])
def test_unit_confirmation_binds_content_authority_and_deadline(change):
    actor, ctx = actor_context()
    payload, session = data(), MemorySession(actor, None)
    view = creation.preview(session, ctx, payload)
    proof = session.added[0]
    payload.confirmation_token = view["confirmation_token"]
    if change == "payload":
        payload.name += "修改"
    elif change == "epoch":
        actor.access_epoch += 1
    else:
        proof.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        creation.create(MemorySession(actor, None, None, proof), ctx, payload)
    assert error.value.detail["reason"] == "preview_required"


def transaction(setup, action):
    ctx = Context(setup.tenant, setup.human, setup.human)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.human) as session:
        return action(session, ctx)


@pytest.mark.parametrize("key", creation.SEED_KEYS)
def test_database_seed_atomic_provenance_and_idempotency(setup, key):
    seed = creation.load_seed(key)
    payload = CategoryCreate(
        **{k: seed[k] for k in ("key", "name", "purpose", "seed_key", "groups")},
        deidentified_confirmed=True,
        idempotency_key=str(uuid4()),
    )
    view = transaction(setup, lambda s, ctx: creation.preview(s, ctx, payload))
    payload.confirmation_token = view["confirmation_token"]
    result = transaction(setup, lambda s, ctx: creation.create(s, ctx, payload))
    category_id = UUID(result["category_id"])
    with Session(setup.admin) as session:
        category = session.get(Category, category_id)
        assert category.key == key and category.created_by_run_id is None
        parameters = session.scalars(
            select(ParameterVersion).where(ParameterVersion.category_id == category.id)
        ).all()
        knowledge = session.scalars(
            select(KnowledgeEntry).where(KnowledgeEntry.category_id == category.id)
        ).all()
        assert len(parameters) == len(payload.groups.parameters)
        assert len(knowledge) == len(payload.groups.knowledge)
        assert all(
            row.origin == "imported"
            and row.writer_id == setup.human
            and row.run_id is None
            and str(row.receipt_id) == result["id"]
            for row in parameters + knowledge
        )
        for model in (KnowledgeCurrent, ParameterCurrent, Audit, Outbox, RequestKey):
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(model.category_id == category.id)
                )
                > 0
            )
    future = now() + timedelta(hours=1)
    with using_clock(lambda: future):
        assert transaction(setup, lambda s, ctx: creation.create(s, ctx, payload)) == result
    alias = payload.model_copy(update={"idempotency_key": str(uuid4()), "confirmation_token": None})
    assert transaction(setup, lambda s, ctx: creation.create(s, ctx, alias)) == result
    changed = payload.model_copy(update={"purpose": "另一个用途"})
    with pytest.raises(DomainError) as error:
        transaction(setup, lambda s, ctx: creation.create(s, ctx, changed))
    assert error.value.code == "DUPLICATE_INTENT_CONFLICT"
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(Grant.category_id == category_id, Grant.principal_id == setup.human)
        )
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as error:
        transaction(setup, lambda s, ctx: creation.create(s, ctx, payload))
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_database_rollback_restores_token_and_rows(setup, monkeypatch):
    payload = data(groups={"knowledge": [{"kind": "boundary", "content": {"definition": "边界"}}]})
    view = transaction(setup, lambda s, ctx: creation.preview(s, ctx, payload))
    payload.confirmation_token = view["confirmation_token"]
    original = creation.receipt_view

    def fail_after_writes(row):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(creation, "receipt_view", fail_after_writes)
    with pytest.raises(RuntimeError):
        transaction(setup, lambda s, ctx: creation.create(s, ctx, payload))
    with Session(setup.admin) as session:
        assert not session.scalar(
            select(Category.id).where(
                Category.tenant_id == setup.tenant, Category.key == payload.key
            )
        )
        proof = session.scalar(
            select(CategoryCreationConfirmation).where(
                CategoryCreationConfirmation.tenant_id == setup.tenant
            )
        )
        assert not proof.consumed
    monkeypatch.setattr(creation, "receipt_view", original)
    assert (
        transaction(setup, lambda s, ctx: creation.create(s, ctx, payload))["operation"]
        == "category.create"
    )
