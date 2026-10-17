"""Transaction/seal and persistence invariants, with no DB or grants."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from pdos_next.contracts import Command
from pdos_next.domain.external_handoff import service
from pdos_next.domain.external_handoff.constants import AUTHORIZE
from pdos_next.domain.release.rules import digest as body_digest
from pdos_next.errors import DomainError
from pdos_next.service import digest

from .test_rules import case as handoff_case  # noqa: F401
from .test_rules import release_case  # noqa: F401


@pytest.fixture
def work(request):
    case = request.getfixturevalue("handoff_case")
    engine = create_engine("postgresql+psycopg://unused/never_connect")

    @event.listens_for(engine, "do_connect")
    def refuse(*args):
        raise AssertionError("Pure handoff phase must never connect")

    service.configure(engine)
    s = Session(engine)
    s.begin()
    command = Command(
        command_id=uuid4(),
        operation=AUTHORIZE,
        category_id=case.base.ctx.category_id,
        product_id=case.base.scope.product_id,
        expected_revision=3,
        idempotency_key="unpersisted-private-key-" + str(uuid4()),
        payload=case.payload.model_dump(mode="json"),
        source_read_set=case.data.required_source_read_set,
    )
    bound = service.Bound(
        material=case.data,
        basis={"actual-source": "unexecuted fixture"},
        candidate=case.plan,
        reads=case.data.required_source_read_set,
        authority={},
        diagnostics=(),
    )
    product = SimpleNamespace(id=case.base.scope.product_id, revision=3)
    value = SimpleNamespace(
        case=case,
        engine=engine,
        s=s,
        ctx=case.base.ctx,
        command=command,
        product=product,
        payload=case.payload,
        bound=bound,
    )
    value.phase = lambda: service.Prepared(
        service._CAPABILITY, s, value.ctx, value.command, product, value.payload, value.bound
    )
    yield value
    s.close()
    engine.dispose()


def rejects(call, reason):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == reason


def test_candidate_body_hash_survives_json_storage_and_t2_has_one_consumption_intent(work):
    phase = work.phase()
    columns = service._columns(
        work.ctx,
        work.command,
        work.product,
        work.payload,
        phase,
        owner_id=work.ctx.requester_id,
        visibility=work.payload.visibility,
    )
    assert (
        columns["body_sha256"] == body_digest(columns["body"]) == body_digest(work.bound.candidate)
    )
    assert "intent_digest" not in columns
    assert columns["network_send"] is False
    saved = service._saved_input(work.command, work.payload, phase)
    assert "idempotency_key" not in saved["command"]
    assert work.command.idempotency_key not in str(saved)
    assert saved["original_key_sha256"] == digest(work.command.idempotency_key)


def test_preview_uses_one_real_phase_without_recollecting_or_consuming(work, monkeypatch):
    phase = work.phase()

    def forbidden(*args, **kwargs):
        raise AssertionError("Preview must not recollect or perform a T2 transition")

    monkeypatch.setattr(service, "_load", forbidden)
    monkeypatch.setattr(service, "_still_current", forbidden)
    review = service.preview_prepared(
        work.s, work.ctx, work.command, work.product, work.payload, phase
    )
    assert review["after"]["prepared_at"] is None and phase.used
    assert not (work.s.new or work.s.dirty or work.s.deleted)
    rejects(
        lambda: service.preview_prepared(
            work.s, work.ctx, work.command, work.product, work.payload, phase
        ),
        "INVALID_PHASE",
    )


@pytest.mark.parametrize("fault", ["pointer", "review", "request", "runtime", "uow"])
def test_phase_seal_rejects_changed_sequence_request_or_transaction(work, fault):
    phase = work.phase()
    command = work.command
    reason = "INVALID_PHASE"
    if fault == "pointer":
        work.bound.basis["previous_current"] = {"receipt_count": 2, "epoch": 3}
    elif fault == "review":
        phase.review["after"]["external_received"] = True
    elif fault == "request":
        command = command.model_copy(update={"idempotency_key": "different-explicit-key"})
    elif fault == "runtime":
        service.configure(work.engine)
    else:
        work.s.rollback()
        work.s.begin()
        reason = "FACT_CALLER_UOW_CHANGED"
    rejects(
        lambda: service._phase(work.s, work.ctx, command, work.product, work.payload, phase), reason
    )


def test_review_preserves_parent_decisions_and_normalizes_only_candidate_time(work):
    phase = work.phase()
    assert [value.plan.expiry for value in phase.bound.material.decisions] == [None, None]
    assert phase.review["after"]["network_send"] is False
    altered = replace(
        work.bound,
        candidate=work.bound.candidate.model_copy(
            update={"prepared_at": work.bound.candidate.prepared_at.replace(year=2030)}
        ),
    )
    assert service._review(work.command, altered) == service._review(work.command, work.bound)
    assert service._bound_digest(altered) != service._bound_digest(work.bound)


@pytest.mark.parametrize("private_field", ["visibility", "original_visibility"])
def test_private_receipt_original_cannot_expand_to_shared_handoff(private_field):
    read = SimpleNamespace(
        source_basis={"artifact_sources": {str(uuid4()): {private_field: "private"}}}
    )
    with pytest.raises(DomainError) as error:
        service._receipt_audience(SimpleNamespace(visibility="category"), read)
    assert error.value.reason == "FORBIDDEN_SCOPE" and error.value.status == 403
    service._receipt_audience(SimpleNamespace(visibility="private"), read)
    service._receipt_audience(
        SimpleNamespace(visibility="category"),
        SimpleNamespace(
            source_basis={"artifact_sources": {str(uuid4()): {"visibility": "category"}}}
        ),
    )
