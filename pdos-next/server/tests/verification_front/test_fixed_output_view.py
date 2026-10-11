"""Real front reader/projection with in-memory rows; never a database or qualification."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from pdos_next.domain.verification_front import service
from pdos_next.domain.verification_front.adapters import METHOD_POSITION
from pdos_next.domain.verification_front.models import (
    FormalVerificationCurrent,
    FormalVerificationRequest,
    MethodApplicability,
    VerificationWindowProposal,
)
from pdos_next.domain.verification_front.schemas import MethodPreparePayload, ScheduleProposePayload
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import EventTime, SourceRef
from pdos_next.service import Context, digest

from .test_pure import AT, bound, create  # noqa: F401 - register the bounded pure fixture


@pytest.fixture
def fixed_request(monkeypatch, bound):  # noqa: F811 - imported pytest fixture
    def no_connection(*args, **kwargs):
        raise AssertionError("This pure fixed-output test must not connect to a database")

    monkeypatch.setattr(Engine, "connect", no_connection)
    ctx = Context(bound.scope.tenant_id, bound.actor, bound.actor)
    original = create(bound)
    parent_id, prep_id = uuid4(), uuid4()
    reads = [{"artifact_id": str(uuid4()), "expected_revision": 1}]
    source = {
        "artifact_id": reads[0]["artifact_id"],
        "expected_revision": 1,
        "line": 1,
        "quote": "Explicit offline synthetic original",
    }
    parent = SimpleNamespace(
        id=parent_id,
        tenant_id=ctx.tenant_id,
        product_id=bound.scope.product_id,
        request_id=original.id,
        revision=1,
        owner_id=ctx.requester_id,
        visibility="private",
    )
    bound.authority = {**bound.assessment, "operation": "verification.method.prepare"}
    method_bound = service.Bound(
        SimpleNamespace(project_id=bound.scope.project_id),
        None,
        original,
        parent,
        bound.authority,
        [source],
        reads,
        "private",
        AT,
    )
    method_payload = MethodPreparePayload(
        request_id=original.id,
        expected_request_revision=1,
        assessments=[
            {
                "item_id": bound.item.id,
                "status": "applicable",
                "reason": "Offline",
                "sources": [source],
            }
        ],
        reason="Offline original method",
    )
    method = service._children(
        ctx, SimpleNamespace(command_id=uuid4()), method_payload, method_bound
    )[0]
    window_bound = service.Bound(
        method_bound.build,
        None,
        original,
        parent,
        {**bound.assessment, "operation": "verification.schedule.propose"},
        [source],
        reads,
        "private",
        AT,
    )
    window_payload = ScheduleProposePayload(
        request_id=original.id,
        expected_request_revision=1,
        start=AT + timedelta(days=1),
        finish=AT + timedelta(days=1, hours=1),
        original_timezone="UTC",
        reason="Offline tentative window",
    )
    window = service._children(
        ctx, SimpleNamespace(command_id=uuid4()), window_payload, window_bound
    )[0]
    request = original.model_copy(
        update={
            "revision": 2,
            "documents": tuple(
                doc.model_copy(
                    update={
                        "source": SourceRef(
                            kind="domain", id=method.id, revision=1, position=METHOD_POSITION
                        )
                    }
                )
                for doc in original.documents
            ),
            "tentative_start": EventTime(
                occurred_at=window_payload.start,
                original_timezone="UTC",
                source=SourceRef(kind="domain", id=window.id, revision=1, position="window"),
            ),
        }
    )
    row = SimpleNamespace(
        **{
            **vars(parent),
            "id": uuid4(),
            "revision": 2,
            "project_id": bound.scope.project_id,
            "build_id": request.build.id,
            "build_revision": request.build.revision,
            "preparation_id": prep_id,
            "preparation_revision": 1,
            "preparation_sha256": "a" * 64,
            "previous_request_id": parent_id,
            "previous_revision": 1,
            "status": "draft",
            "operation": "verification.schedule.propose",
            "request_snapshot": request.model_dump(mode="json"),
            "snapshot_sha256": digest(request.model_dump(mode="json")),
            "input_snapshot": {"method_assessment_refs": [{"id": str(method.id)}]},
            "required_source_read_set": reads,
            "sources": [source],
            "created_at": AT,
            "reason": "Offline fixed request",
        }
    )
    prep = SimpleNamespace(
        input_snapshot={"items": [bound.item.model_dump(mode="json")], "documents": []}
    )
    work = SimpleNamespace(
        ctx=ctx,
        pid=bound.scope.product_id,
        row=row,
        parent=parent,
        method=method,
        window=window,
        prep=prep,
        calls=[],
        caller_assessments=[],
        review_operations=[],
        valid_reviews=True,
        source_status="current",
        children={MethodApplicability: method, VerificationWindowProposal: window},
    )

    class Rows:
        def scalar(self, statement):
            model = statement.column_descriptions[0]["entity"]
            values = statement.compile().params.values()
            assert ctx.tenant_id in values and work.pid in values
            if model is FormalVerificationCurrent:
                work.calls.append("current")
                return SimpleNamespace(request_version_id=row.id, request_revision=row.revision)
            assert model is FormalVerificationRequest
            work.calls.append("row")
            return parent if parent.id in values else row if row.id in values else None

        def get(self, model, identity):
            work.calls.append(model.__name__)
            if model is FormalVerificationRequest:
                selected = parent if parent.id == identity else row if row.id == identity else None
                return (
                    selected
                    if selected is not None and selected.owner_id == ctx.requester_id
                    else None
                )
            value = work.children[model]
            assert value is None or value.id == identity
            return value

    work.session = Rows()

    def human(s, c, pid):
        assert (s, c, pid) == (work.session, ctx, work.pid)
        work.calls.append("human")

    def preparation(s, c, pid, identity):
        assert (s, c, pid, identity) == (work.session, ctx, work.pid, prep_id)
        work.calls.append("preparation")
        return prep, {}

    def evidence(s, c, pid, selected):
        assert selected is row
        work.calls.append("source")
        return work.source_status

    def sources(*args):
        work.calls.append("child_sources")

    def recheck(s, c, pid, project, snapshot):
        assert (s, c, pid, project) == (work.session, ctx, work.pid, bound.scope.project_id)
        work.review_operations.append(snapshot["operation"])
        return {
            "current": work.valid_reviews,
            "reason_codes": [] if work.valid_reviews else ["REVOKED"],
        }

    def assess(s, c, pid, project, operation, purpose):
        work.caller_assessments.append(operation)
        return {
            "authorized": True,
            "qualified": True,
            "required_source_read_set": [{"artifact_id": str(uuid4()), "expected_revision": 1}],
        }

    monkeypatch.setattr(service, "_human", human)
    monkeypatch.setattr(service.preparation_service, "get_preparation", preparation)
    monkeypatch.setattr(service, "_read_evidence", evidence)
    monkeypatch.setattr(service, "_sources", sources)
    monkeypatch.setattr(service, "_recheck", recheck)
    monkeypatch.setattr(service, "_assess", assess)
    return work


def read(work, **kwargs):
    row, view = service.get_request(work.session, work.ctx, work.pid, work.row.id, **kwargs)
    assert row is work.row
    return view


def test_fixed_view_retains_material_and_children_but_skips_three_caller_assessments(fixed_request):
    work = fixed_request
    normal = read(work)
    assert work.caller_assessments == list(service.OPERATIONS.values())
    assert all(normal["capabilities"][key] for key in service.OPERATIONS)
    assert len(normal["required_source_read_set"]) == 4
    normal_guards = deepcopy(work.calls)
    normal_reviewers = deepcopy(work.review_operations)
    work.calls.clear()
    work.review_operations.clear()
    work.caller_assessments.clear()
    fixed = read(work, assess_capabilities=False)
    assert work.caller_assessments == []
    assert fixed["authority"] == {} and not any(fixed["capabilities"].values())
    assert fixed["required_source_read_set"] == work.row.required_source_read_set
    assert work.calls == normal_guards
    assert (
        work.review_operations
        == normal_reviewers
        == [
            "verification.method.prepare",
            "verification.method.prepare",
            "verification.schedule.propose",
        ]
    )
    omitted = {"authority", "capabilities", "required_source_read_set"}
    assert {k: v for k, v in fixed.items() if k not in omitted} == {
        k: v for k, v in normal.items() if k not in omitted
    }
    assert fixed["method_assessments"][0]["authority"] == work.method.authority_snapshot
    assert fixed["window_proposals"][0]["authority"] == work.window.authority_snapshot


@pytest.mark.parametrize("assess_capabilities", [True, False])
def test_fixed_mode_keeps_original_child_revocation_and_document_freshness(
    fixed_request, assess_capabilities
):
    work = fixed_request
    work.valid_reviews = False
    view = read(work, assess_capabilities=assess_capabilities)
    assert view["method_assessments"][0]["current"] is False
    assert view["method_assessments"][0]["reason_codes"] == ["SOURCE_STALE"]
    assert view["window_proposals"][0]["current"] is False
    assert view["window_proposals"][0]["reason_codes"] == ["REVOKED"]
    assert view["documents_ready"] is False
    assert view["document_gaps"] == []


@pytest.mark.parametrize("assess_capabilities", [True, False])
@pytest.mark.parametrize("child", [MethodApplicability, VerificationWindowProposal])
def test_fixed_mode_cannot_skip_missing_referenced_child(fixed_request, assess_capabilities, child):
    work = fixed_request
    work.children[child] = None
    with pytest.raises(DomainError) as caught:
        read(work, assess_capabilities=assess_capabilities)
    assert caught.value.reason == "INTEGRITY_MISMATCH"


@pytest.mark.parametrize("assess_capabilities", [True, False])
@pytest.mark.parametrize("failure", ["private", "snapshot", "source"])
def test_fixed_mode_keeps_parent_access_snapshot_and_source_guards(
    fixed_request, assess_capabilities, failure
):
    work = fixed_request
    if failure == "private":
        work.row.owner_id = uuid4()
    elif failure == "snapshot":
        work.row.snapshot_sha256 = "0" * 64
    else:
        work.source_status = "needs_recheck"
        view = read(work, assess_capabilities=assess_capabilities)
        assert view["source_status"] == "needs_recheck"
        assert view["freshness"] == "requires_recalculation"
        assert view["documents_ready"] is False and not any(view["capabilities"].values())
        return
    with pytest.raises(DomainError) as caught:
        read(work, assess_capabilities=assess_capabilities)
    assert caught.value.reason == (
        "FORBIDDEN_SCOPE" if failure == "private" else "INTEGRITY_MISMATCH"
    )


def test_fixed_capability_flag_is_keyword_only(fixed_request):
    work = fixed_request
    with pytest.raises(TypeError):
        service.get_request(work.session, work.ctx, work.pid, work.row.id, False)
