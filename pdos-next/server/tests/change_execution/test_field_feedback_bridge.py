# ruff: noqa: F811 -- imported pytest fixture is used through test parameters
"""Exact Field-to-Change port binding; no database or invented failure fixture."""

import sys
from copy import deepcopy
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.change_execution import field_bridge, graph, service
from pdos_next.domain.change_execution.schemas import ChangeCreatePayload
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import Ref
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context

from .test_api_query import route  # noqa: F401 -- explicit shared route fixture


@pytest.fixture
def feedback(monkeypatch):
    actor, tenant, category, product, project = (uuid4() for _ in range(5))
    ctx = Context(tenant, actor, actor, category_id=category)
    row = SimpleNamespace(
        id=uuid4(),
        feedback_id=uuid4(),
        tenant_id=tenant,
        category_id=category,
        product_id=product,
        project_id=project,
        owner_id=actor,
        visibility="private",
        revision=3,
        body_sha256="a" * 64,
        source_basis={"artifacts": [{"id": str(uuid4()), "revision": 2}]},
    )
    view = {
        "feedback_id": str(row.feedback_id),
        "version_id": str(row.id),
        "revision": row.revision,
        "project_id": str(project),
        "purpose": "field containment investigation",
        "title": "Customer vibration at an identified configuration",
        "is_current": True,
        "source_status": "current",
        "required_source_read_set": [{"artifact_id": str(uuid4()), "expected_revision": 2}],
        "sources": [],
        "location": {
            "state": "known",
            "engineering_configuration": {"id": str(uuid4()), "revision": 4},
            "manufacturing_configuration": {"id": str(uuid4()), "revision": 6},
            "batch": {"id": str(uuid4()), "revision": 1},
        },
    }
    calls = []

    def native(s, caller, pid, feedback_id, revision, *, write=False):
        calls.append((s, caller, pid, feedback_id, revision, write))
        return row, view

    module = ModuleType("pdos_next.domain.field_feedback.owner")
    module.get_feedback_for_change = native
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return SimpleNamespace(
        ctx=ctx,
        product=product,
        project=project,
        row=row,
        view=view,
        calls=calls,
        ref=Ref(id=row.feedback_id, revision=3, kind="field_feedback"),
        session=object(),
    )


def test_create_can_use_actual_field_without_issue_but_not_configuration_alone(feedback):
    source = {
        "kind": "artifact",
        "id": str(uuid4()),
        "revision": 1,
        "position": "line:1;quote_sha256:" + "b" * 64,
    }
    payload = ChangeCreatePayload(
        title="Investigate fixed Field feedback",
        reason="A sourced report suggests a configuration change",
        roots=(feedback.ref,),
        sources=(source,),
    )
    assert payload.roots == (feedback.ref,)
    with pytest.raises(ValidationError, match="现场反馈"):
        ChangeCreatePayload.model_validate(
            {
                **payload.model_dump(),
                "roots": ({"kind": "engineering_configuration", "id": uuid4(), "revision": 1},),
            }
        )


def test_scope_comes_from_fresh_native_feedback_not_issue_or_caller_project(feedback, monkeypatch):
    monkeypatch.setattr(service, "_issue_loader", lambda s: pytest.fail("No Issue is required"))
    actual_scope, purpose = service._scope_seed(
        feedback.session, feedback.ctx, feedback.product, (feedback.ref,)
    )
    assert actual_scope == Scope(
        tenant_id=feedback.ctx.tenant_id,
        product_id=feedback.product,
        project_id=feedback.project,
    )
    assert purpose == feedback.view["purpose"]
    assert feedback.calls[-1][3:] == (feedback.row.feedback_id, 3, False)


def test_only_get_options_may_choose_current_and_result_ref_stays_exact(feedback):
    row, view, scope, _ = field_bridge.current(
        feedback.session, feedback.ctx, feedback.product, feedback.row.feedback_id
    )
    assert row is feedback.row and view is feedback.view
    assert scope.project_id == feedback.project
    assert feedback.calls[-1][4] is None
    field_bridge.get(feedback.session, feedback.ctx, feedback.product, feedback.ref)
    assert feedback.calls[-1][4] == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_current", False),
        ("source_status", "needs_recheck"),
        ("purpose", " "),
        ("location", {"state": "unknown"}),
    ],
)
def test_unknown_stale_or_unusable_field_does_not_seed_new_change(feedback, field, value):
    feedback.view[field] = value
    with pytest.raises(DomainError) as failure:
        service._seed(feedback.session, feedback.ctx, feedback.product, (feedback.ref,))
    assert failure.value.reason == "RECHECK_REQUIRED"
    assert failure.value.code == "SOURCE_STALE"


@pytest.mark.parametrize("field", ["product_id", "category_id", "project_id", "feedback_id", "id"])
def test_fixed_port_cannot_substitute_scope_or_version(feedback, field):
    setattr(feedback.row, field, uuid4())
    with pytest.raises(DomainError) as failure:
        field_bridge.get(feedback.session, feedback.ctx, feedback.product, feedback.ref)
    assert failure.value.reason == "FIXED_REFERENCE_MISMATCH"


def test_field_and_issue_must_keep_same_actual_project_and_precise_purpose(feedback, monkeypatch):
    issue_id = uuid4()
    issue = SimpleNamespace(
        id=uuid4(),
        tenant_id=feedback.ctx.tenant_id,
        product_id=feedback.product,
        project_id=feedback.project,
    )
    issue_view = {
        "issue_id": str(issue_id),
        "revision": 1,
        "purpose": feedback.view["purpose"],
    }
    monkeypatch.setattr(service, "_issue_loader", lambda s: lambda *a: (issue, issue_view))
    refs = (feedback.ref, Ref(kind="issue", id=issue_id, revision=1))
    assert (
        service._seed(feedback.session, feedback.ctx, feedback.product, refs)[1]
        == issue_view["purpose"]
    )
    issue_view["purpose"] = "another purpose"
    with pytest.raises(DomainError) as failure:
        service._seed(feedback.session, feedback.ctx, feedback.product, refs)
    assert failure.value.status == 403


def test_graph_preserves_native_feedback_and_only_actual_configuration_edges(feedback):
    scope = Scope(
        tenant_id=feedback.ctx.tenant_id,
        product_id=feedback.product,
        project_id=feedback.project,
    )
    reader = graph.OwnerReader(
        feedback.session,
        feedback.ctx,
        feedback.product,
        scope,
        graph.audience(feedback.product, feedback.ctx.requester_id, "private"),
        lambda *a: pytest.fail("No TestRun or Issue is synthesized"),
    )
    obj = reader.resolve(feedback.ref)
    assert obj.current and obj.ref.id == feedback.row.feedback_id
    assert obj.source_basis == {
        "feedback_version_id": str(feedback.row.id),
        "feedback_sha256": feedback.row.body_sha256,
        "feedback_source_basis": feedback.row.source_basis,
    }
    links = reader.links(obj)
    assert [(ref.kind, ref.revision) for ref, _ in links] == [
        ("engineering_configuration", 4),
        ("manufacturing_configuration", 6),
    ]
    assert {ref.id for ref, _ in links} == {
        field_bridge.configuration_refs(feedback.view)[0].id,
        field_bridge.configuration_refs(feedback.view)[1].id,
    }
    # The immutable owner basis is copied, rather than changing with a mutable
    # object returned by a host substitute during the same phase.
    original = deepcopy(obj.source_basis)
    feedback.row.source_basis["artifacts"] = []
    assert obj.source_basis == original


def test_private_feedback_cannot_seed_a_category_graph(feedback):
    reader = graph.OwnerReader(
        feedback.session,
        feedback.ctx,
        feedback.product,
        Scope(
            tenant_id=feedback.ctx.tenant_id,
            product_id=feedback.product,
            project_id=feedback.project,
        ),
        graph.audience(feedback.product, feedback.ctx.requester_id, "category"),
        lambda *a: pytest.fail("No Issue read"),
    )
    with pytest.raises(DomainError) as failure:
        reader.resolve(feedback.ref)
    assert failure.value.status == 403
    assert failure.value.reason == "AUDIENCE_USE_FORBIDDEN"


def test_feedback_get_selection_reaches_domain_reader_with_actual_uuid(route):
    client, product, opened = route
    selection = str(uuid4())
    response = client.get(
        f"/v1/categories/{uuid4()}/products/{product}/change-execution",
        params={"field_feedback_id": selection},
    )
    assert response.status_code == 200
    assert response.json()["selection"]["field_feedback_id"] == selection
    assert len(opened) == 1


def test_duplicate_feedback_get_selection_rejects_before_tenant_uow(route):
    client, product, opened = route
    selection = str(uuid4())
    response = client.get(
        f"/v1/categories/{uuid4()}/products/{product}/change-execution",
        params=[("field_feedback_id", selection), ("field_feedback_id", selection)],
    )
    assert response.status_code == 422
    assert opened == []


def test_field_source_options_accept_exact_registered_native_text_only_when_enabled(monkeypatch):
    from pdos_next import service as common

    from .test_native_evidence import native

    session, ctx, pid, reads, exact, _, _, _ = native(monkeypatch)
    source = common.source_for(session, ctx, pid, exact.id, exact.revision)
    source.title = "Actual registered synthetic Field report"
    assert service._source_options(session, ctx, pid, reads) == []  # Existing Issue entry stays.
    options = service._source_options(session, ctx, pid, reads, include_registered_native=True)
    assert len(options) == 2
    assert options[0]["source"] == exact.model_dump(mode="json")
    assert options[0]["quote"] == source.content.splitlines()[0]
    assert options[0]["required_source_read_set"] == reads


@pytest.mark.parametrize("invalid", ["missing", "duplicate", "foreign_requester", "bad_result"])
def test_field_native_source_option_requires_actual_registration_proof(monkeypatch, invalid):
    from pdos_next import service as common

    from .test_native_evidence import native

    session, ctx, pid, reads, exact, _, receipt, _ = native(monkeypatch)
    common.source_for(session, ctx, pid, exact.id, exact.revision).title = "Unproven Field report"
    if invalid in {"missing", "duplicate"}:
        session.scalars = lambda query: () if invalid == "missing" else (receipt, receipt)
    elif invalid == "foreign_requester":
        receipt.requester_id = uuid4()
    else:
        receipt.result = {"id": str(exact.id), "revision": 1, "status": "withdrawn"}
    assert service._source_options(session, ctx, pid, reads, include_registered_native=True) == []
