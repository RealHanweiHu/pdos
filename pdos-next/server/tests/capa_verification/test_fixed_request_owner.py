"""Fixed Formal owner material excludes UI command reads, without database I/O."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from pdos_next.domain.capa_verification import service
from pdos_next.domain.capa_verification.schemas import FixedRef, SourceRead
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.verification_front import service as front
from pdos_next.errors import DomainError

from .test_pure import basis, context, output  # noqa: F401


@pytest.fixture
def fixed_request(monkeypatch, basis, context):  # noqa: F811 - imported pytest fixtures
    def no_connection(*args, **kwargs):
        raise AssertionError("This bounded owner regression must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_connection)
    selected = output(basis, kind="verification_request")
    reads = [read.model_dump(mode="json") for read in basis.required_source_read_set]
    row = SimpleNamespace(
        id=selected.ref.id,
        revision=1,
        request_id=uuid4(),
        tenant_id=basis.scope.tenant_id,
        product_id=basis.scope.product_id,
        project_id=basis.scope.project_id,
        owner_id=context.requester_id,
        visibility="category",
        status="draft",
        required_source_read_set=reads,
    )
    view = {
        "id": str(row.id),
        "request_id": str(row.request_id),
        "revision": 1,
        "status": "draft",
        "title": "Fixed unstarted Formal output",
        "source_status": "current",
        "is_current": True,
        "freshness": "current",
        "documents_ready": False,
        "document_milestone_current": None,
        "method_assessments": [],
        "window_proposals": [],
        "required_source_read_set": deepcopy(reads),
        "authority": {},
        "capabilities": {"request_create": True},
    }
    work = SimpleNamespace(
        row=row,
        view=view,
        ref=selected.ref,
        basis=basis,
        context=context,
        source_epoch=1,
        withdrawn=False,
        source_calls=[],
        front_calls=[],
    )

    def read_request(s, ctx, pid, identity, *, assess_capabilities=True):
        assert (ctx, pid, identity) == (context, basis.scope.product_id, row.id)
        work.front_calls.append((identity, assess_capabilities))
        selected_view = deepcopy(view)
        if not assess_capabilities:
            selected_view.update(
                authority={},
                capabilities={},
                required_source_read_set=deepcopy(row.required_source_read_set),
            )
        return row, selected_view

    def read_sources(s, ctx, pid, current_reads):
        if work.withdrawn:
            raise DomainError("SOURCE_UNAVAILABLE", "Explicit offline withdrawn source")
        values = service.merge_reads(current_reads)
        work.source_calls.append(values)
        return [
            {
                "id": value["artifact_id"],
                "revision": value["expected_revision"],
                "offline_security_epoch": work.source_epoch,
            }
            for value in values
        ], False

    monkeypatch.setattr(front, "get_request", read_request)
    monkeypatch.setattr(service, "source_basis", read_sources)
    monkeypatch.setattr(service, "recheck_followup_basis", lambda *args, **kwargs: basis)
    monkeypatch.setattr(service.quality, "_human", lambda *args, **kwargs: None)
    return work


def reading(work):
    return service._reading(None, work.context, work.basis.scope.product_id, work.basis, work.ref)


def save_link(work, monkeypatch):
    # This regression isolates fixed Draft material only. Professional, policy
    # and principal guards below are explicit doubles, not actual qualification.
    deadline = datetime.now(UTC) + timedelta(days=1)
    assessment = {
        "subject_id": str(work.context.requester_id),
        "scope": work.basis.scope.model_dump(mode="json"),
        "operation": "quality.capa.followup.link",
        "purpose": work.basis.purpose,
        "valid_until": None,
        "synthetic": True,
        "roles": ["quality"],
        "fact_refs": [
            {
                "kind": kind,
                "role": "quality",
                "nature": "synthetic",
                "state": "active",
                "operations": ["quality.capa.followup.link"],
                "purposes": [work.basis.purpose],
                "valid_from": (deadline - timedelta(days=2)).isoformat(),
                "valid_until": deadline.isoformat(),
            }
            for kind in ("duty", "qualification")
        ],
    }
    resolved = service.resolve_followup_outputs(
        None,
        work.context,
        work.basis.scope.product_id,
        work.basis,
        work.basis.actions[0].action_id,
        (work.ref,),
    )
    evidence, _ = service.source_basis(
        None, work.context, work.basis.scope.product_id, resolved.required_source_read_set
    )
    row = SimpleNamespace(
        id=uuid4(),
        writer_id=work.context.requester_id,
        owner_id=work.context.requester_id,
        project_id=work.basis.scope.project_id,
        purpose=work.basis.purpose,
        visibility="category",
        action_id=resolved.action_id,
        basis_snapshot=work.basis.model_dump(mode="json"),
        basis_sha256=work.basis.basis_sha256,
        output_snapshot=resolved.model_dump(mode="json"),
        resolution_sha256=resolved.resolution_sha256,
        required_source_read_set=[
            read.model_dump(mode="json") for read in resolved.required_source_read_set
        ],
        source_basis={"artifact_sources": evidence},
        authority_snapshot=assessment,
        policy_snapshot={
            "id": "offline-policy",
            "revision": 1,
            "valid_until": None,
            "offline_substitute_only": True,
            "source_basis": [
                {
                    "id": "offline-policy",
                    "revision": 1,
                    "state": "active",
                    "valid_from": (deadline - timedelta(days=2)).isoformat(),
                    "valid_until": deadline.isoformat(),
                }
            ],
        },
    )
    monkeypatch.setattr(service, "_fixed_row", lambda *args: row)
    monkeypatch.setattr(
        professional,
        "recheck_snapshot",
        lambda *args, **kwargs: {"current": True, "assessment": assessment},
    )
    monkeypatch.setattr(service, "_link_runtime", lambda *args: "explicit offline runtime")
    monkeypatch.setattr(service, "_link_access", lambda *args, **kwargs: {"expires_at": deadline})
    monkeypatch.setattr(service, "_link_policy", lambda *args: row.policy_snapshot)
    work.link = row
    return resolved


def read_link(work):
    return service._link(
        None,
        work.context,
        work.basis.scope.product_id,
        work.basis,
        FixedRef(id=work.link.id, revision=1),
    )


@pytest.mark.parametrize("children", [(), ("method_assessments",), ("window_proposals",)])
def test_fixed_parent_and_referenced_child_closure_excludes_ui_command_sources(
    fixed_request, children
):
    work = fixed_request
    extra = SourceRead(artifact_id=uuid4(), expected_revision=1).model_dump(mode="json")
    for field in children:
        child = {
            "id": str(uuid4()),
            "current": True,
            "reason_codes": [],
            "sources": [],
            "required_source_read_set": [extra],
            "authority": {"preserved_saved_signer": "original"},
        }
        work.view[field].append(child)
    ui_only = SourceRead(artifact_id=uuid4(), expected_revision=1).model_dump(mode="json")
    work.view["required_source_read_set"] = service.merge_reads(
        work.row.required_source_read_set, [extra] if children else [], [ui_only]
    )
    current = reading(work)
    expected = service.merge_reads(work.row.required_source_read_set, [extra] if children else [])
    assert [read.model_dump(mode="json") for read in current.required_source_read_set] == expected
    assert current.snapshot["required_source_read_set"] == expected
    assert ui_only not in expected and work.source_calls[-1] == expected
    assert work.front_calls == [(work.ref.id, False)]
    for field in ("method_assessments", "window_proposals"):
        assert current.snapshot[field] == work.view[field]
    assert work.view["required_source_read_set"] != expected  # no mutation of the UI result


def test_original_saved_link_remains_exact_after_unrelated_ui_authority_source_addition(
    fixed_request, monkeypatch
):
    work = fixed_request
    resolved = save_link(work, monkeypatch)
    before_saved = deepcopy(vars(work.link))
    ui_only = SourceRead(artifact_id=uuid4(), expected_revision=1).model_dump(mode="json")
    work.view["required_source_read_set"] = service.merge_reads(
        work.row.required_source_read_set, [ui_only]
    )
    work.view["authority"] = {"new_ui_operation": {"required_source_read_set": [ui_only]}}
    refreshed = read_link(work)
    assert refreshed.outputs == resolved.outputs
    assert refreshed.source_basis_sha256 == resolved.source_basis_sha256
    assert vars(work.link) == before_saved
    assert all(ui_only not in reads for reads in work.source_calls)


def test_skipped_ui_assessment_preserves_full_fixed_snapshot_and_material_digest(
    fixed_request, monkeypatch
):
    work = fixed_request
    ui_only = SourceRead(artifact_id=uuid4(), expected_revision=1).model_dump(mode="json")
    work.view.update(
        authority={"future_action": {"required_source_read_set": [ui_only]}},
        capabilities={"future_action": True},
        required_source_read_set=service.merge_reads(work.row.required_source_read_set, [ui_only]),
    )
    actual_boundary = front.get_request

    def original_ui_read(s, ctx, pid, identity, *, assess_capabilities=True):
        return actual_boundary(s, ctx, pid, identity, assess_capabilities=True)

    monkeypatch.setattr(front, "get_request", original_ui_read)
    before = reading(work).model_dump(mode="json")
    monkeypatch.setattr(front, "get_request", actual_boundary)
    after = reading(work).model_dump(mode="json")
    assert before == after and service.digest(before) == service.digest(after)
    assert work.front_calls == [(work.ref.id, True), (work.ref.id, False)]
    assert work.source_calls[0] == work.source_calls[1] == work.row.required_source_read_set


@pytest.mark.parametrize(
    "change", ["method_current", "window_current", "documents", "security", "fixed_revision"]
)
def test_fixed_method_window_business_and_security_changes_still_require_recheck(
    fixed_request, monkeypatch, change
):
    work = fixed_request
    work.view["method_assessments"] = [
        {
            "id": str(uuid4()),
            "current": True,
            "status": "applicable",
            "reason_codes": [],
            "required_source_read_set": deepcopy(work.row.required_source_read_set),
        }
    ]
    work.view["window_proposals"] = [
        {
            "id": str(uuid4()),
            "current": True,
            "reason_codes": [],
            "required_source_read_set": deepcopy(work.row.required_source_read_set),
        }
    ]
    save_link(work, monkeypatch)
    if change in {"method_current", "window_current"}:
        field = "method_assessments" if change == "method_current" else "window_proposals"
        work.view[field][0]["current"] = False
        work.view[field][0]["reason_codes"] = ["PROFESSIONAL_AUTHORITY_CHANGED"]
    elif change == "documents":
        work.view["documents_ready"] = True
    elif change == "security":
        work.source_epoch += 1
    else:
        work.row.required_source_read_set[0]["expected_revision"] = 2
        work.view["method_assessments"] = []
        work.view["window_proposals"] = []
    with pytest.raises(DomainError) as raised:
        read_link(work)
    assert raised.value.reason == (
        "SOURCE_STALE" if change == "fixed_revision" else "RECHECK_REQUIRED"
    )


def test_original_fixed_source_withdrawal_is_not_hidden_by_stable_ui_status(
    fixed_request, monkeypatch
):
    work = fixed_request
    save_link(work, monkeypatch)
    work.withdrawn = True
    with pytest.raises(DomainError) as raised:
        read_link(work)
    assert raised.value.reason == "SOURCE_UNAVAILABLE"


def test_fixed_request_private_scope_still_rejects_another_reader(fixed_request):
    work = fixed_request
    work.row.visibility, work.row.owner_id = "private", uuid4()
    with pytest.raises(DomainError) as raised:
        reading(work)
    assert (raised.value.reason, raised.value.status) == ("FORBIDDEN_SCOPE", 403)


def test_fixed_child_source_revision_cannot_be_boolean(fixed_request):
    work = fixed_request
    child = deepcopy(work.row.required_source_read_set)
    child[0]["expected_revision"] = True
    work.view["method_assessments"] = [{"required_source_read_set": child}]
    with pytest.raises(ValidationError):
        reading(work)
