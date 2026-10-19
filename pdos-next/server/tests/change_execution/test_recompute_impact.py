"""Recompute with the real exact-one-capture Facts adapter; no DB or fake graph ACL."""

from dataclasses import replace as replace_ports
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.domain.change_control.ports import Authority, Currentness
from pdos_next.domain.change_control.rules import compute_impact, digest, replace
from pdos_next.domain.change_execution import adapters
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import ChangeRequest, ImpactCompute, Ref

from .test_pure import AT, fixture


def case():
    work = fixture()
    old = replace(
        work.snapshot,
        id=uuid4(),
        captured_at=AT - timedelta(hours=2),
        expires_at=AT - timedelta(hours=1),
    )
    new = replace(work.snapshot, id=uuid4())
    request = ChangeRequest(
        id=uuid4(),
        revision=2,
        scope=work.scope,
        audience=work.reader.target,
        requester_id=work.actor,
        title="A fixed change",
        reason="Recompute actual dependencies",
        roots=work.payload.roots,
        references=work.payload.references,
        sources=work.payload.sources,
        status="analysis",
        assessments=(compute_impact(old, 1),),
    )
    authority = Authority(
        scope=work.scope,
        actor_id=work.actor,
        requester_id=work.actor,
        actor_kind="human",
        audience=work.reader.target,
        roles=("engineering",),
        authorized=True,
        qualified=True,
        cancelled=False,
        now=AT,
    )
    core = adapters.kernel(authority, request, work.reader, {digest(work.source)}, graph=new)
    return SimpleNamespace(
        work=work, old=old, graph=new, request=request, authority=authority, core=core
    )


def prepare(value, *, snapshot=None):
    payload = ImpactCompute(
        snapshot=snapshot
        or Ref(kind="graph_snapshot", id=value.graph.id, revision=value.graph.revision)
    )
    _, (after, _, _, _) = value.core._prepare(
        None,
        value.authority,
        "change.impact.compute",
        value.request.id,
        value.request.revision,
        payload,
        None,
    )
    return after


def test_new_exact_capture_can_replace_expired_old_assessment_without_rewriting_history():
    value = case()
    # The adapter stays exact: it cannot resolve the retained graph as its current capture.
    with pytest.raises(DomainError) as failure:
        value.core.ports.facts.ref(
            None, value.authority, Ref(kind="graph_snapshot", id=value.old.id, revision=1)
        )
    assert failure.value.reason == "FIXED_REFERENCE_MISMATCH"
    after = prepare(value)
    assert len(after.assessments) == 2 and after.assessments[0] == value.request.assessments[0]
    assert after.assessments[-1].graph == value.graph
    assert after.roots == value.request.roots and after.sources == value.request.sources


@pytest.mark.parametrize("wrong", ["old", "new_wrong_version", "new_wrong_id"])
def test_recompute_does_not_turn_facts_into_an_arbitrary_graph_reader(wrong):
    value = case()
    ref = Ref(
        kind="graph_snapshot",
        id=value.old.id
        if wrong == "old"
        else uuid4()
        if wrong == "new_wrong_id"
        else value.graph.id,
        revision=2 if wrong == "new_wrong_version" else 1,
    )
    with pytest.raises(DomainError) as failure:
        prepare(value, snapshot=ref)
    assert failure.value.reason == "FIXED_REFERENCE_MISMATCH"


@pytest.mark.parametrize("bad", ["expired", "future", "scope", "roots", "audience"])
def test_replacement_graph_keeps_all_current_scope_clock_and_root_guards(bad):
    value = case()
    updates = {
        "expired": {"captured_at": AT - timedelta(hours=2), "expires_at": AT - timedelta(hours=1)},
        "future": {"captured_at": AT + timedelta(minutes=1)},
        "scope": {"scope": value.graph.scope.model_copy(update={"project_id": uuid4()})},
        "roots": {"roots": (value.graph.nodes[1].ref,)},
        "audience": {"audience": ("private:other-person",)},
    }
    value.graph = replace(value.graph, **updates[bad])
    value.core.ports.facts.graph_value = value.graph
    with pytest.raises(DomainError) as failure:
        prepare(value)
    assert failure.value.reason in {
        "RECHECK_REQUIRED",
        "FORBIDDEN_SCOPE",
        "IMPACT_ROOT_MISMATCH",
        "AUDIENCE_USE_FORBIDDEN",
    }


@pytest.mark.parametrize("stale", ["source", "root", "new_node"])
def test_refresh_still_rejects_withdrawn_request_source_root_and_new_dependency(stale):
    value = case()
    actual = value.core.ports.facts

    class CurrentFacts(adapters.Facts):
        def source(self, *args):
            status = super().source(*args)
            return Currentness(current=False) if stale == "source" else status

        def currentness(self, uow, authority, ref):
            status = super().currentness(uow, authority, ref)
            target = value.request.roots[0] if stale == "root" else value.graph.nodes[-1].ref
            return Currentness(current=False) if stale != "source" and ref == target else status

    value.core.ports = replace_ports(
        value.core.ports, facts=CurrentFacts(actual.reader, actual.sources, value.graph)
    )
    with pytest.raises(DomainError) as failure:
        prepare(value)
    assert failure.value.reason == "RECHECK_REQUIRED"


@pytest.mark.parametrize("reasons", [(), ("Explicit source investigation is pending",)])
def test_recompute_does_not_clear_explicit_needs_recheck(reasons):
    value = case()
    value.request = replace(value.request, needs_recheck=True, recheck_reasons=reasons)
    value.core.ports.commands.request_value = value.request
    with pytest.raises(DomainError) as failure:
        prepare(value)
    assert failure.value.reason == "RECHECK_REQUIRED"


def test_default_current_check_still_requires_the_saved_assessment():
    value = case()
    with pytest.raises(DomainError) as failure:
        value.core._require_current(None, value.authority, value.request)
    assert failure.value.reason == "FIXED_REFERENCE_MISMATCH"


def test_retained_request_acl_is_checked_before_recompute_even_with_a_new_valid_graph():
    value = case()

    def denied(*args):
        raise DomainError(
            "FORBIDDEN_SCOPE", "Native aggregate owner denied retained history ACL", 403
        )

    value.core.ports.commands.request = denied
    with pytest.raises(DomainError) as failure:
        prepare(value)
    assert failure.value.reason == "FORBIDDEN_SCOPE" and failure.value.status == 403
