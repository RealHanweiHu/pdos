"""Request proof and unknown-policy guards, not a saved release qualification."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.contracts import Command
from pdos_next.domain.release import rules, schemas, service
from pdos_next.errors import DomainError
from pdos_next.service import digest

from . import test_rules

AT = test_rules.AT


@pytest.fixture
def case():
    return test_rules.case.__wrapped__()


def bound(case):
    return service.Bound(
        material=case.material,
        basis={"material_owner": {"actual": ["fixed"]}},
        plan=case.plan,
        candidate=case.plan,
        reads=case.material.required_source_read_set,
        authority={},
        diagnostics=(),
    )


def command(case):
    return Command(
        command_id=uuid4(),
        category_id=case.ctx.category_id,
        product_id=case.scope.product_id,
        operation=schemas.ASSEMBLE,
        expected_revision=3,
        idempotency_key="release-preparation-" + str(uuid4()),
        payload=case.payload.model_dump(mode="json"),
        source_read_set=case.material.required_source_read_set,
    )


def test_preview_consumes_same_bound_phase_without_reading_again(case, monkeypatch):
    s, product, runtime, uow = object(), object(), object(), object()
    calls = []
    monkeypatch.setattr(service, "_runtime", lambda _s: runtime)
    monkeypatch.setattr(service, "_uow", lambda _s: uow)
    monkeypatch.setattr(service, "_same_uow", lambda *values: calls.append(values))
    phase = service.Prepared(
        service._CAPABILITY, s, case.ctx, command(case), product, case.payload, bound(case)
    )
    cmd = command(case)
    phase.command_sha = digest(cmd)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Phase preview must not reconstruct material")

    monkeypatch.setattr(service, "_load", forbidden)
    monkeypatch.setattr(service, "_current_material", forbidden)
    review = service.preview_prepared(s, case.ctx, cmd, product, case.payload, phase)
    assert review["after"] == case.plan.model_dump(mode="json")
    assert len(calls) == 1 and phase.used
    with pytest.raises(DomainError, match="准备事务"):
        service.preview_prepared(s, case.ctx, cmd, product, case.payload, phase)


@pytest.mark.parametrize("field", ["basis", "authority", "pointer"])
def test_phase_rejects_mutated_bound_values_without_io(case, monkeypatch, field):
    s, product, runtime = object(), object(), object()
    monkeypatch.setattr(service, "_runtime", lambda _s: runtime)
    monkeypatch.setattr(service, "_uow", lambda _s: object())
    monkeypatch.setattr(service, "_same_uow", lambda *_args: None)
    selected = bound(case)
    if field == "pointer":
        selected = replace(selected, pointer={"epoch": 1})
    cmd = command(case)
    phase = service.Prepared(service._CAPABILITY, s, case.ctx, cmd, product, case.payload, selected)
    getattr(phase.bound, field)["changed"] = True
    with pytest.raises(DomainError, match="准备事务"):
        service.preview_prepared(s, case.ctx, cmd, product, case.payload, phase)


def test_assembly_keeps_unknown_policy_in_both_professional_views(case):
    material = case.material.model_copy(update={"policy": None, "checks": ()})
    plan = rules.assemble(case.payload, material, owner_id=case.actor)
    views = service._assessments(plan)
    assert set(views) == {"engineering", "manufacturing"}
    for view in views.values():
        assert view["state"] == "UNKNOWN"
        assert view["unknown"] == ["RELEASE_POLICY_MISSING"]


def test_unknown_policy_cannot_reach_common_t2_consumption(case, monkeypatch):
    plan = rules.assemble(
        case.payload, case.material.model_copy(update={"policy": None}), owner_id=case.actor
    )
    candidate = case.candidate(plan=plan)
    selected = replace(bound(case), plan=plan, candidate=candidate)
    phase = SimpleNamespace(bound=selected, review={"not_a_saved_decision": True})
    calls = []
    monkeypatch.setattr(service, "validate", lambda *_args: calls.append("once") or phase)
    with pytest.raises(DomainError, match="未知"):
        service.prepare_write_review(None, case.ctx, None, None, candidate)
    assert calls == ["once"]


def test_t2_review_fixes_material_but_not_a_preview_timestamp(case):
    first = case.candidate()
    second = first.model_copy(update={"prepared_at": AT.replace(year=2027)})
    one = replace(bound(case), candidate=first)
    two = replace(bound(case), candidate=second)
    cmd = SimpleNamespace(operation=schemas.MANUFACTURING_APPROVE)
    assert service._review(cmd, one) == service._review(cmd, two)
    assert service._bound_digest(one) != service._bound_digest(two)
    # Preparing a view must not turn the original candidate into a signed fact.
    assert first.status == "unexecuted_candidate" and first.structural_only


def test_original_request_snapshot_contains_neither_key_nor_token(case):
    cmd = command(case)
    phase = SimpleNamespace(review={"after": case.plan.model_dump(mode="json")})
    saved = service._saved_input(cmd, case.payload, phase)
    assert "idempotency_key" not in saved["command"]
    assert cmd.idempotency_key not in str(saved)
    assert saved["semantic"] == case.payload.model_dump(mode="json")
    altered = deepcopy(saved)
    altered["review"]["after"]["owner_id"] = str(uuid4())
    assert altered != saved and case.plan.owner_id == case.actor
