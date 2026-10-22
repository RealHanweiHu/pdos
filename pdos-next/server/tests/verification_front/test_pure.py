"""Pure kernel binding checks; no database, network or production qualification."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification_front import service
from pdos_next.domain.verification_front.adapters import (
    METHOD_POSITION,
    TransactionCommands,
    authority_dto,
    handler,
    professional_documents,
)
from pdos_next.domain.verification_front.schemas import (
    ItemAssessment,
    MethodPreparePayload,
    RequestCreatePayload,
    ScheduleProposePayload,
)
from pdos_next.errors import DomainError

# Load host model registry first; production performs the same ordered registration.
from pdos_next.models import Base  # noqa: F401
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ConfigurationRef,
    NumericCriterion,
    RequestCreate,
    Scope,
    SourceRef,
)
from pdos_next.schemas.verification.contracts import (
    TestItem as ItemDTO,
)

AT = datetime(2026, 10, 2, 1, tzinfo=UTC)


@pytest.fixture
def bound():
    actor = uuid4()
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    ref = SourceRef(id=uuid4(), revision=1, position="line:1")
    item = ItemDTO(
        id="pressure",
        feature="Pressure",
        drawing=ref,
        method=ref,
        criterion=NumericCriterion(lower="1", upper="2", source=ref),
        unit="PSI",
        conditions="Synthetic 20C",
        material="Synthetic polymer",
        sample_count=2,
        cavities=("A", "B"),
    )
    build = BuildRef(
        id=uuid4(),
        revision=1,
        product_id=scope.product_id,
        project_id=scope.project_id,
        engineering_configuration=ConfigurationRef(id=uuid4(), revision=1),
        manufacturing_configuration=ConfigurationRef(id=uuid4(), revision=1),
    )
    assessment = {
        "scope": scope.model_dump(mode="json"),
        "subject_id": str(actor),
        "operation": "verification.request.create",
        "purpose": "Synthetic pressure purpose",
        "roles": ["quality"],
        "authorized": True,
        "qualified": True,
    }
    return SimpleNamespace(actor=actor, scope=scope, item=item, build=build, assessment=assessment)


def create(bound, *, item=None):
    item = item or bound.item
    data = RequestCreate(
        request_id=uuid4(),
        build_id=bound.build.id,
        expected_build_revision=1,
        title="Synthetic formal request",
        purpose="Synthetic pressure purpose",
        items=(item,),
        documents=professional_documents((item,), ()),
        return_form="Sourced report",
    )
    recorded = []

    def record(mutation):
        recorded.append(mutation.request)
        return mutation.request

    commands = TransactionCommands(authority_dto(bound.assessment, bound.actor, AT), None, record)
    kernel = handler(commands, bound.build, "planned", lambda *_: None)
    from pdos_next.domain.verification.handlers import semantic_digest

    inv = Invocation(
        command_id=uuid4(),
        operation="verification.request.create",
        subject_id=data.request_id,
        expected_revision=0,
        semantic_digest=semantic_digest(data),
    )
    kernel.execute(inv, data)
    return recorded[0]


def test_populated_methods_still_require_per_item_professional_proof(bound):
    request = create(bound)
    assert request.timeline.request_created.occurred_at == AT
    assert request.timeline.documents_complete is None
    assert not request.samples and not request.acceptances
    gaps = service.document_gaps(request)
    assert len(gaps) == 1 and gaps[0].item_id == "pressure"


def test_long_valid_item_identity_and_feature_fit_generated_proof_dto(bound):
    item = bound.item.model_copy(update={"id": "x" * 120, "feature": "x" * 2000})
    docs = professional_documents((item,), ())
    assert len(docs[0].id) <= 120 and docs[0].item_ids == (item.id,)
    assert len(docs[0].title) <= 2000
    assert create(bound, item=item).timeline.documents_complete is None


@pytest.mark.parametrize("qualified", [False, None])
def test_product_access_never_substitutes_professional_qualification(bound, qualified):
    bound.assessment["qualified"] = qualified
    with pytest.raises(DomainError) as error:
        create(bound)
    assert error.value.reason == "QUALIFICATION_REQUIRED"


def test_quality_role_is_not_inferred_from_authorized_flag(bound):
    bound.assessment["roles"] = []
    with pytest.raises(DomainError) as error:
        create(bound)
    assert error.value.reason == "FORBIDDEN_OPERATION"


def test_shared_t1_proof_cannot_be_enabled_by_payload(bound):
    request = create(bound)
    bound.assessment["operation"] = "verification.method.prepare"
    commands = TransactionCommands(
        authority_dto(bound.assessment, bound.actor, AT), request, lambda _: None
    )
    with pytest.raises(DomainError) as error:
        commands.confirm(SimpleNamespace(operation="verification.method.prepare"), None, None)
    assert error.value.reason == "CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("status", ["unknown", "not_applicable", "applicable"])
def test_method_candidates_bind_exact_item_scope_and_original_reviewer(bound, status):
    request = create(bound)
    context = SimpleNamespace(tenant_id=bound.scope.tenant_id, requester_id=bound.actor)
    payload = MethodPreparePayload(
        request_id=request.id,
        expected_request_revision=1,
        assessments=[
            ItemAssessment(
                item_id="pressure",
                status=status,
                reason="Synthetic review",
                sources=[
                    {
                        "artifact_id": uuid4(),
                        "expected_revision": 1,
                        "line": 1,
                        "quote": "Synthetic evidence",
                    }
                ]
                if status == "applicable"
                else [],
            )
        ],
        reason="Synthetic review",
    )
    value = service.Bound(
        SimpleNamespace(project_id=bound.scope.project_id),
        None,
        request,
        SimpleNamespace(id=uuid4(), revision=1, input_snapshot={}),
        bound.assessment,
        [],
        [],
        "private",
        AT,
    )
    candidate = service._children(context, SimpleNamespace(command_id=uuid4()), payload, value)[0]
    assert candidate.request_version_id == value.previous.id
    assert candidate.assessment_snapshot["fixed_item"] == bound.item.model_dump(mode="json")
    assert candidate.assessment_snapshot["reviewer_id"] == str(bound.actor)
    kernel = service._kernel_payload(None, payload, value, [candidate])
    proof = kernel.documents[-1]
    assert (proof.source is not None) == (status == "applicable")
    if proof.source:
        assert proof.source.kind == "domain" and proof.source.position == METHOD_POSITION


def test_positive_method_cannot_compensate_missing_fixed_method(bound):
    request = create(bound, item=bound.item.model_copy(update={"method": None}))
    value = service.Bound(
        SimpleNamespace(project_id=bound.scope.project_id),
        None,
        request,
        SimpleNamespace(id=uuid4(), revision=1),
        bound.assessment,
        [],
        [],
        "private",
        AT,
    )
    payload = MethodPreparePayload(
        request_id=request.id,
        expected_request_revision=1,
        assessments=[
            {
                "item_id": "pressure",
                "status": "applicable",
                "reason": "Synthetic",
                "sources": [
                    {
                        "artifact_id": uuid4(),
                        "expected_revision": 1,
                        "line": 1,
                        "quote": "Synthetic",
                    }
                ],
            }
        ],
        reason="Synthetic review",
    )
    with pytest.raises(DomainError) as error:
        service._children(
            SimpleNamespace(tenant_id=bound.scope.tenant_id, requester_id=bound.actor),
            SimpleNamespace(command_id=uuid4()),
            payload,
            value,
        )
    assert error.value.reason == "METHOD_EVIDENCE_INCOMPLETE"


def test_tentative_interval_keeps_unknowns_zero_occupancy_and_no_run(bound):
    request = create(bound)
    value = service.Bound(
        SimpleNamespace(project_id=bound.scope.project_id),
        None,
        request,
        SimpleNamespace(id=uuid4(), revision=1),
        bound.assessment,
        [],
        [],
        "private",
        AT,
    )
    payload = ScheduleProposePayload(
        request_id=request.id,
        expected_request_revision=1,
        start=AT + timedelta(days=1),
        finish=AT + timedelta(days=1, hours=2),
        original_timezone="America/Los_Angeles",
        reason="Synthetic tentative window",
    )
    child = service._children(
        SimpleNamespace(tenant_id=bound.scope.tenant_id, requester_id=bound.actor),
        SimpleNamespace(command_id=uuid4()),
        payload,
        value,
    )[0]
    assert child.occupancy == 0 and child.status == "tentative"
    assert {gap["code"] for gap in child.gaps} >= {"DURATION_UNKNOWN", "CALENDAR_UNKNOWN"}
    assert child.window["original_timezone"] == "America/Los_Angeles"
    assert not hasattr(child, "owner_run_id")


@pytest.mark.parametrize(
    "changes",
    [
        {"qualified": True},
        {"owner_id": str(uuid4())},
        {"request_snapshot": {}},
        {"documents_complete": True},
    ],
)
def test_create_wrapper_cannot_accept_trusted_fields(changes):
    with pytest.raises(ValidationError):
        RequestCreatePayload(
            request_id=uuid4(),
            preparation_id=uuid4(),
            expected_preparation_revision=1,
            preparation_sha256="a" * 64,
            reason="Synthetic request",
            **changes,
        )


def test_semantic_reorders_assessments_and_excludes_confirmation_token():
    data = {
        "request_id": uuid4(),
        "expected_request_revision": 1,
        "reason": "Synthetic review",
        "assessments": [
            {"item_id": key, "status": "unknown", "reason": "Unknown"} for key in ("a", "b")
        ],
    }
    one = MethodPreparePayload(**data)
    other = MethodPreparePayload(
        **{**data, "assessments": data["assessments"][::-1], "confirmation_token": "x" * 40}
    )
    assert service.semantic(one) == service.semantic(other)
