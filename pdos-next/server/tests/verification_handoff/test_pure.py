"""Pure physical-kernel checks; synthetic facts are never real qualification."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next.domain.verification.handlers import semantic_digest
from pdos_next.domain.verification.ports import Invocation
from pdos_next.domain.verification_front.adapters import authority_dto
from pdos_next.domain.verification_handoff import service
from pdos_next.domain.verification_handoff.adapters import HandoffCommands, InspectedSamples, kernel
from pdos_next.domain.verification_handoff.schemas import (
    AcceptPayload,
    ActualMethodPreparePayload,
    OfferPayload,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import (
    BuildRef,
    ConfigurationRef,
    Coverage,
    EventTime,
    HandoffAccept,
    HandoffOffer,
    NumericCriterion,
    SampleRef,
    Scope,
    SourceRef,
    TimeFact,
    Timeline,
    VerificationRequest,
)
from pdos_next.schemas.verification.contracts import TestItem as Item
from pdos_next.service import Context, digest

AT = datetime(2026, 10, 2, 18, tzinfo=UTC)


@pytest.fixture
def work():
    actor, source_id = uuid4(), uuid4()
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    source = SourceRef(id=source_id, revision=1, position="Synthetic exact source")
    build = BuildRef(
        id=uuid4(),
        revision=1,
        product_id=scope.product_id,
        project_id=scope.project_id,
        engineering_configuration=ConfigurationRef(id=uuid4(), revision=1),
        manufacturing_configuration=ConfigurationRef(id=uuid4(), revision=1),
    )
    item = Item(
        id="dimension",
        feature="Synthetic dimension",
        drawing=source,
        method=source,
        criterion=NumericCriterion(lower="1", upper="2", source=source),
        unit="mm",
        conditions="Synthetic 20C",
        material="Synthetic material",
        sample_count=2,
    )
    clock = TimeFact(
        occurred_at=AT - timedelta(hours=2),
        received_at=AT - timedelta(hours=1),
        original_timezone="UTC",
        source=source,
        actor_id=actor,
    )
    request = VerificationRequest(
        id=uuid4(),
        revision=1,
        scope=scope,
        build=build,
        title="Synthetic physical request",
        purpose="Synthetic limited validation",
        items=(item,),
        return_form="Synthetic evidence",
        timeline=Timeline(request_created=clock),
    )
    samples = tuple(
        SampleRef(
            id=uuid4(),
            revision=1,
            build_id=build.id,
            actual_configuration=ConfigurationRef(id=uuid4(), revision=1),
        )
        for _ in range(2)
    )
    return SimpleNamespace(
        actor=actor, source=source, request=request, samples=samples, recorded=[]
    )


def handler(
    work,
    request=None,
    *,
    availability="ready",
    applicable=True,
    qualified=True,
    confirmed=True,
    status="executing",
    roles=("engineering",),
):
    request = request or work.request
    authority = authority_dto(
        {
            "scope": request.scope.model_dump(mode="json"),
            "authorized": True,
            "qualified": qualified,
            "roles": roles,
        },
        work.actor,
        AT,
    )

    def save(mutation):
        work.recorded.append(mutation.request)
        return mutation.request

    commands = HandoffCommands(authority, request, save, accepted_confirmation=confirmed)

    def inspect(sample):
        return {
            "availability": availability,
            "current_readiness": {
                "source_ref": work.source.model_dump(mode="json"),
                "clocks": {
                    "occurred_at": (AT - timedelta(minutes=10)).isoformat(),
                    "original_timezone": "UTC",
                },
            },
        }

    samples = InspectedSamples(inspect, lambda sample: applicable)
    return kernel(commands, request.build, status, lambda *_: None, samples)


def execute(work, h, payload, operation):
    return h.execute(
        Invocation(
            command_id=uuid4(),
            operation=operation,
            subject_id=work.request.id,
            expected_revision=h.ports.commands.fixed_request.revision,
            semantic_digest=semantic_digest(payload),
        ),
        payload,
    )


def offer(work):
    return HandoffOffer(
        samples=work.samples,
        coverage=tuple(Coverage(sample_id=s.id, item_id="dimension") for s in work.samples),
        at=EventTime(
            occurred_at=AT - timedelta(minutes=5), original_timezone="UTC", source=work.source
        ),
    )


@pytest.mark.parametrize(
    "availability,applicable",
    [("unknown", False), ("hold", False), ("ready", False), ("ready", True)],
)
def test_offer_records_precise_scope_without_fabricating_ready_or_acceptance(
    work, availability, applicable
):
    execute(
        work,
        handler(work, availability=availability, applicable=applicable),
        offer(work),
        "verification.handoff.offer",
    )
    result = work.recorded[0]
    assert result.status == "offered" and result.samples == work.samples
    assert not result.acceptances and result.timeline.accepted is None
    assert result.timeline.actual_start is None and result.timeline.promised_start is None
    assert (result.timeline.sample_ready is not None) == (availability == "ready")


@pytest.mark.parametrize(
    "status,code", [("planned", "ACTUAL_SAMPLE_REQUIRED"), ("executing", "CONFIRMATION_REQUIRED")]
)
def test_existing_actual_samples_and_generic_confirm_do_not_authorize_offer(work, status, code):
    with pytest.raises(DomainError) as error:
        execute(
            work,
            handler(work, confirmed=False, status=status),
            offer(work),
            "verification.handoff.offer",
        )
    assert error.value.reason == code and not work.recorded


def offered(work):
    execute(work, handler(work), offer(work), "verification.handoff.offer")
    return work.recorded[-1]


@pytest.mark.parametrize(
    "availability,applicable", [("unknown", True), ("hold", True), ("ready", False)]
)
def test_partial_accept_requires_current_ready_and_actual_applicable(
    work, availability, applicable
):
    request = offered(work)
    payload = HandoffAccept(
        coverage=request.offered_coverage[:1],
        reason="Remaining sample needs review",
        next_owner_id=uuid4(),
        at=EventTime(occurred_at=AT, original_timezone="UTC", source=work.source),
    )
    with pytest.raises(DomainError) as error:
        execute(
            work,
            handler(
                work, request, availability=availability, applicable=applicable, roles=("quality",)
            ),
            payload,
            "verification.handoff.accept",
        )
    assert error.value.reason == "SAMPLE_UNAVAILABLE" and len(work.recorded) == 1


def test_partial_accept_keeps_count_gap_and_next_owner_without_start_clock(work):
    request = offered(work)
    owner = uuid4()
    payload = HandoffAccept(
        coverage=request.offered_coverage[:1],
        returned_coverage=request.offered_coverage[1:],
        reason="Second sample unavailable",
        next_owner_id=owner,
        at=EventTime(occurred_at=AT, original_timezone="UTC", source=work.source),
    )
    execute(
        work, handler(work, request, roles=("quality",)), payload, "verification.handoff.accept"
    )
    accepted = work.recorded[-1]
    assert accepted.status == "accepted" and len(accepted.acceptances) == 1
    assert accepted.returns[0].next_owner_id == owner
    assert accepted.returns[0].coverage == payload.returned_coverage
    assert any(gap.code == "PARTIAL_SAMPLE_COUNT" for gap in accepted.returns[0].gaps)
    assert accepted.timeline.accepted.occurred_at == AT
    assert accepted.timeline.actual_start is None
    with pytest.raises(DomainError) as error:
        execute(
            work,
            handler(work, accepted, roles=("quality",)),
            payload,
            "verification.handoff.accept",
        )
    assert error.value.reason == "ALREADY_ACCEPTED"


@pytest.mark.parametrize("qualified", [False, None])
def test_qualified_current_role_is_independent_of_product_access(work, qualified):
    with pytest.raises(DomainError) as error:
        execute(work, handler(work, qualified=qualified), offer(work), "verification.handoff.offer")
    assert error.value.reason == "QUALIFICATION_REQUIRED"


def test_actual_positive_requires_sources_unknown_can_be_saved(work):
    data = {
        "request_id": work.request.id,
        "expected_request_revision": 1,
        "reason": "Synthetic",
        "assessments": [
            {
                "sample": work.samples[0],
                "item_id": "dimension",
                "expected_assessment_revision": 0,
                "status": "unknown",
                "reason": "Unknown actual method",
            }
        ],
    }
    assert ActualMethodPreparePayload.model_validate(data).assessments[0].status == "unknown"
    data["assessments"][0]["status"] = "applicable"
    with pytest.raises(ValidationError):
        ActualMethodPreparePayload.model_validate(data)


def test_payload_forbids_scope_authority_and_server_receive_time(work):
    raw = {
        "request_id": work.request.id,
        "expected_request_revision": 1,
        "samples": work.samples,
        "coverage": offer(work).coverage,
        "at": offer(work).at,
        "reason": "Synthetic",
    }
    for key, value in [("tenant_id", uuid4()), ("qualified", True), ("received_at", AT)]:
        with pytest.raises(ValidationError):
            OfferPayload.model_validate({**raw, key: value})


def test_exact_time_source_is_existing_line_quote_hash():
    import hashlib

    from pdos_next.domain.configurations.schemas import DefinitionReference

    reference = DefinitionReference(
        artifact_id=uuid4(), expected_revision=1, line=2, quote="合成原文"
    )
    assert (
        service.event_source(reference).position
        == f"line:2;quote_sha256:{hashlib.sha256('合成原文'.encode()).hexdigest()}"
    )


def test_semantic_reordering_keeps_scope_but_changed_pair_is_distinct(work):
    raw = {
        "request_id": work.request.id,
        "expected_request_revision": 1,
        "samples": work.samples,
        "coverage": offer(work).coverage,
        "at": offer(work).at,
        "reason": "Synthetic",
    }
    first = OfferPayload.model_validate(raw)
    second = OfferPayload.model_validate(
        {
            **raw,
            "samples": tuple(reversed(work.samples)),
            "coverage": tuple(reversed(raw["coverage"])),
        }
    )
    assert digest(service.semantic(first)) == digest(service.semantic(second))


def test_accept_and_return_scope_are_disjoint(work):
    raw = {
        "request_id": work.request.id,
        "expected_request_revision": 1,
        "coverage": offer(work).coverage,
        "returned_coverage": offer(work).coverage,
        "at": offer(work).at,
        "reason": "Synthetic",
    }
    with pytest.raises(ValidationError):
        AcceptPayload.model_validate(raw)


def test_preview_masks_only_new_server_receive_clocks_including_nested_sample_ready():
    old = {"timeline": {"request_created": {"received_at": "fixed"}}, "acceptances": []}

    def proposed(clock):
        return {
            "timeline": {
                "request_created": {"received_at": "fixed"},
                "accepted": {"received_at": clock},
            },
            "acceptances": [{"at": {"received_at": clock}, "sample_ready": {"received_at": clock}}],
        }

    first = service._preview_receives(proposed("time-A"), old)
    second = service._preview_receives(proposed("time-B"), old)
    assert digest(first) == digest(second)
    assert first["timeline"]["request_created"]["received_at"] == "fixed"
    assert first["acceptances"][0]["sample_ready"]["received_at"] is None


@pytest.mark.parametrize("status", ["unknown", "not_applicable", "applicable"])
def test_actual_candidates_are_independent_of_planned_configuration(work, monkeypatch, status):
    monkeypatch.setattr(service, "_method_pointer", lambda *_args, **_kw: (None, None))
    monkeypatch.setattr(
        service, "_execution", lambda *_args: {"execution_qualification": "limited_current"}
    )
    sample = work.samples[0]
    actual = {
        "id": str(sample.actual_configuration.id),
        "revision": 1,
        "actual_engineering_configuration_id": str(uuid4()),
        "actual_manufacturing_configuration_id": str(uuid4()),
    }
    authority = {"subject_id": str(work.actor), "operation": "verification.actual_method.prepare"}
    bound = service.Bound(
        SimpleNamespace(id=uuid4(), revision=1),
        work.request,
        SimpleNamespace(id=work.request.build.id, project_id=work.request.scope.project_id),
        authority,
        [],
        [],
        {"refs": [], "security": []},
        {sample.id: {"actual_configuration": actual}},
        {},
        "private",
        AT,
    )
    data = ActualMethodPreparePayload(
        request_id=work.request.id,
        expected_request_revision=1,
        reason="Synthetic actual review",
        assessments=[
            {
                "sample": sample,
                "item_id": "dimension",
                "expected_assessment_revision": 0,
                "status": status,
                "reason": "Actual scope review",
                "sources": [
                    {
                        "artifact_id": uuid4(),
                        "expected_revision": 1,
                        "line": 1,
                        "quote": "Synthetic source",
                    }
                ]
                if status == "applicable"
                else [],
            }
        ],
    )
    rows, _ = service._actual_candidates(
        None,
        SimpleNamespace(tenant_id=work.request.scope.tenant_id, requester_id=work.actor),
        SimpleNamespace(command_id=uuid4()),
        SimpleNamespace(id=work.request.scope.product_id),
        data,
        bound,
    )
    row = rows[0]
    assert row.actual_configuration_id == sample.actual_configuration.id
    assert row.actual_configuration_id != work.request.build.engineering_configuration.id
    assert row.assessment_snapshot["actual_configuration"] == actual
    assert row.assessment_snapshot["fixed_item"] == work.request.items[0].model_dump(mode="json")
    assert row.authority_snapshot == authority and row.status == status


def test_actual_positive_cannot_compensate_unknown_method(work, monkeypatch):
    monkeypatch.setattr(service, "_method_pointer", lambda *_args, **_kw: (None, None))
    request = type(work.request).model_validate(
        {
            **work.request.model_dump(),
            "items": [work.request.items[0].model_copy(update={"method": None})],
        }
    )
    sample = work.samples[0]
    bound = service.Bound(
        SimpleNamespace(id=uuid4(), revision=1),
        request,
        SimpleNamespace(id=request.build.id, project_id=request.scope.project_id),
        {},
        [],
        [],
        {},
        {sample.id: {"actual_configuration": {}}},
        {},
        "private",
        AT,
    )
    payload = ActualMethodPreparePayload(
        request_id=request.id,
        expected_request_revision=1,
        reason="Synthetic",
        assessments=[
            {
                "sample": sample,
                "item_id": "dimension",
                "expected_assessment_revision": 0,
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
    )
    with pytest.raises(DomainError) as error:
        service._actual_candidates(
            None,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(id=request.scope.product_id),
            payload,
            bound,
        )
    assert error.value.reason == "MISSING_REQUIRED_EVIDENCE"


def test_foreign_actual_configuration_cannot_use_positive_fact(work):
    request, sample = work.request, work.samples[0]
    row = SimpleNamespace(
        tenant_id=request.scope.tenant_id,
        product_id=request.scope.product_id,
        request_id=request.id,
        project_id=request.scope.project_id,
        sample_id=sample.id,
        sample_revision=1,
        actual_configuration_id=uuid4(),
        actual_configuration_revision=1,
        build_id=request.build.id,
        item_id="dimension",
        assessment_snapshot={},
    )
    with pytest.raises(DomainError) as error:
        service._actual_check(
            None,
            SimpleNamespace(tenant_id=request.scope.tenant_id),
            request.scope.product_id,
            request,
            sample,
            {},
            row,
        )
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_read_memoization_is_local_and_keeps_purpose_and_operation_separate():
    calls = []

    def read(value):
        calls.append(value)
        return value

    cache = service._ReadCache()
    assert cache.get("authority", ("project", "purpose-A", "offer"), lambda: read("A")) == "A"
    assert cache.get("authority", ("project", "purpose-A", "offer"), lambda: read("ignored")) == "A"
    assert cache.get("authority", ("project", "purpose-B", "offer"), lambda: read("B")) == "B"
    assert (
        cache.get("authority", ("project", "purpose-A", "accept"), lambda: read("accept"))
        == "accept"
    )
    fresh = service._ReadCache()
    assert (
        fresh.get("authority", ("project", "purpose-A", "offer"), lambda: read("new-GET"))
        == "new-GET"
    )
    assert calls == ["A", "B", "accept", "new-GET"]


def test_read_memoization_keeps_unavailable_facts_blocked_within_one_get():
    calls = []

    def unavailable():
        calls.append(1)
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic unavailable source")

    cache = service._ReadCache()
    for _ in range(2):
        with pytest.raises(DomainError) as error:
            cache.get("sample", ("build", "purpose", "sample", 1), unavailable)
        assert error.value.reason == "SOURCE_UNAVAILABLE"
    assert calls == [1]


def test_history_is_guarded_but_does_not_repeat_current_actions_or_next_owners(work, monkeypatch):
    from pdos_next.domain.sample_handoff import service as sample_service
    from pdos_next.domain.verification_launch.models import VerificationRunIdentity

    calls = {name: [] for name in ("source", "proof", "execution", "owner", "preparation")}
    project_b = uuid4()
    prep_ids = {work.request.scope.project_id: uuid4(), project_b: uuid4()}
    rows, current = [], {}
    for project_id in (work.request.scope.project_id, work.request.scope.project_id, project_b):
        logical_id = uuid4()
        for revision in (1, 2):
            request = work.request.model_copy(
                update={
                    "id": logical_id,
                    "revision": revision,
                    "scope": work.request.scope.model_copy(update={"project_id": project_id}),
                    "status": "offered",
                    "samples": work.samples,
                    "offered_coverage": (
                        Coverage(sample_id=work.samples[0].id, item_id="dimension"),
                    ),
                }
            )
            row = SimpleNamespace(
                id=uuid4(),
                request_id=logical_id,
                revision=revision,
                request=request,
                project_id=project_id,
                build_id=request.build.id,
                snapshot_sha256=digest(request.model_dump(mode="json")),
                preparation_id=prep_ids[project_id],
                required_source_read_set=[],
            )
            rows.append(row)
            current[logical_id] = row
    identities = {row.id: row for row in rows}
    owner = SimpleNamespace(id=uuid4())
    planned_request, planned_run = rows[0].request_id, uuid4()

    class ReadSession:
        def __init__(self):
            self.owner_queries = 0
            self.run_queries = []

        def scalar(self, statement):
            assert statement.column_descriptions[0]["entity"] is VerificationRunIdentity
            scope = statement.compile().params
            assert scope["tenant_id_1"] == work.request.scope.tenant_id
            assert scope["product_id_1"] == work.request.scope.product_id
            request_id = scope["request_id_1"]
            self.run_queries.append(request_id)
            return planned_run if request_id == planned_request else None

        def scalars(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is service.FormalVerificationRequest:
                values = rows
            elif entity is service.Principal:
                self.owner_queries += 1
                values = [owner]
            else:
                values = []
            return SimpleNamespace(all=lambda: values)

    s = ReadSession()
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    monkeypatch.setattr(sample_service, "ReadContext", lambda *_: object(), raising=False)
    monkeypatch.setattr(service, "_human", lambda *_: None)
    monkeypatch.setattr(
        service.front, "_row", lambda _s, _ctx, _pid, identity: identities[identity]
    )
    monkeypatch.setattr(service.front, "_snapshot", lambda row: row.request)
    monkeypatch.setattr(
        service.front,
        "_current",
        lambda _s, _ctx, _pid, identity: (object(), current[identity]),
    )
    monkeypatch.setattr(
        service.front, "_build", lambda *_: SimpleNamespace(id=work.request.build.id)
    )

    def source(_s, _ctx, _pid, row):
        calls["source"].append(row.id)
        return "needs_recheck" if row.revision == 1 else "current"

    def prep(_s, _ctx, _pid, identity):
        calls["preparation"].append(identity)
        return SimpleNamespace(), {}

    def view(_s, _ctx, _pid, row, request, *, current, preparation_row):
        return {
            "id": str(row.id),
            "is_current": current,
            "revision": row.revision,
            "timeline": {"request_created": "fixed server clock"},
            "capabilities": {key: False for key in service.OPERATIONS},
        }

    def assignee(_s, _ctx, _pid, project_id, identity):
        calls["owner"].append((project_id, identity))
        if project_id == project_b:
            raise DomainError("INVALID_ASSIGNEE", "Synthetic private project")
        return {"id": str(identity), "label": "Synthetic eligible person"}

    monkeypatch.setattr(service, "_read_evidence", source)
    monkeypatch.setattr(service.preparation, "get_preparation", prep)
    monkeypatch.setattr(service, "_request_view", view)
    monkeypatch.setattr(service, "_assignee", assignee)
    monkeypatch.setattr(
        service.front,
        "_assess",
        lambda *_: {
            "authorized": True,
            "qualified": True,
            "required_source_read_set": [],
        },
    )
    monkeypatch.setattr(
        service.front, "_check_existing_proofs", lambda *_: calls["proof"].append(1)
    )
    monkeypatch.setattr(service, "_execution", lambda *_a, **_kw: calls["execution"].append(1))
    result = service.list_verification_handoff(s, ctx, work.request.scope.product_id)
    history = [row for row in result["requests"] if not row["is_current"]]
    assert len(history) == 3 and len(calls["source"]) == 6
    assert all(row["source_status"] == "needs_recheck" for row in history)
    assert all(
        row["documents_ready"] is None
        and row["document_milestone_current"] is None
        and row["current_evaluation"] == "not_evaluated_historical"
        for row in history
    )
    assert all(
        not any(row["capabilities"].values()) and not row["next_owner_ids"] for row in history
    )
    assert all(row["timeline"]["request_created"] == "fixed server clock" for row in history)
    assert len(calls["proof"]) == 3 and len(calls["execution"]) == 3
    assert len(s.run_queries) == 3 and set(s.run_queries) == set(current)
    current_views = {UUID(row["id"]): row for row in result["requests"] if row["is_current"]}
    planned_view = current_views[current[planned_request].id]
    assert planned_view["planned_run_id"] == str(planned_run)
    assert not planned_view["capabilities"]["handoff_accept"]
    assert not planned_view["capabilities"]["handoff_return"]
    # Identical pending offered scope without a Run can still be returned.
    assert all(
        row["planned_run_id"] is None and row["capabilities"]["handoff_return"]
        for identity, row in current_views.items()
        if identity != current[planned_request].id
    )
    assert len(calls["preparation"]) == 2 and s.owner_queries == 1
    assert calls["owner"] == [(work.request.scope.project_id, owner.id), (project_b, owner.id)]
    assert result["requests"][-1]["next_owner_ids"] == []
    # A fresh GET never reuses either a positive nomination or an unavailable one.
    service.list_verification_handoff(s, ctx, work.request.scope.product_id)
    assert len(calls["source"]) == 12 and len(calls["owner"]) == 4
    hidden_id = rows[0].id

    def unavailable_history(_s, _ctx, _pid, row):
        if row.id == hidden_id:
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic withdrawn private audience", 403)
        return source(_s, _ctx, _pid, row)

    monkeypatch.setattr(service, "_read_evidence", unavailable_history)
    guarded = service.list_verification_handoff(s, ctx, work.request.scope.product_id)
    assert hidden_id not in {UUID(row["id"]) for row in guarded["requests"]}
    assert guarded["unavailable_count"] == 1


def test_actual_read_proof_cache_preserves_unknown_and_separates_changed_facts(work, monkeypatch):
    calls = []
    row = SimpleNamespace(id=uuid4(), snapshot_sha256="a" * 64, status="unknown")
    sample = work.samples[0]
    value = {"facts_revision": "a" * 64, "availability": "ready"}
    monkeypatch.setattr(service, "_actual_check", lambda *_a, **_kw: calls.append(1))
    cache = service._ReadCache()
    service._read_actual_check(
        None, None, None, work.request, sample, value, row, cache, positive=False
    )
    with pytest.raises(DomainError) as error:
        service._read_actual_check(None, None, None, work.request, sample, value, row, cache)
    assert error.value.reason == "ACTUAL_METHOD_UNKNOWN" and calls == [1]
    service._read_actual_check(
        None,
        None,
        None,
        work.request,
        sample,
        {**value, "facts_revision": "b" * 64},
        row,
        cache,
        positive=False,
    )
    assert calls == [1, 1]


@pytest.mark.parametrize("source_access", [True, False])
def test_superseded_actual_history_keeps_bindings_and_source_audience(
    work, monkeypatch, source_access
):
    request, sample = work.request, work.samples[0]
    owner = work.actor
    parent = SimpleNamespace(id=uuid4(), request_id=request.id, revision=1)
    snap = {
        "sample": sample.model_dump(mode="json"),
        "fixed_item": request.items[0].model_dump(mode="json"),
        "actual_configuration": {"id": str(sample.actual_configuration.id), "revision": 1},
        "reviewer_id": str(owner),
        "conditions": [],
        "reason": "Synthetic historical assessment",
    }
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=request.scope.tenant_id,
        product_id=request.scope.product_id,
        request_id=request.id,
        project_id=request.scope.project_id,
        sample_id=sample.id,
        sample_revision=1,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=1,
        build_id=request.build.id,
        item_id="dimension",
        assessment_snapshot=snap,
        snapshot_sha256=digest(snap),
        method_digest=digest(request.items[0].model_dump(mode="json")),
        owner_id=owner,
        authority_snapshot={
            "subject_id": str(owner),
            "operation": "verification.actual_method.prepare",
            "purpose": request.purpose,
        },
        visibility="private",
        request_version_id=parent.id,
        request_revision=1,
        revision=1,
        status="applicable",
        sources=[],
        required_source_read_set=[],
        created_at=AT,
    )
    ctx = Context(request.scope.tenant_id, owner, owner)
    monkeypatch.setattr(service.front, "_row", lambda *_: parent)
    monkeypatch.setattr(service.front, "_snapshot", lambda *_: request)

    def unexpected_current_review(*_a, **_kw):
        raise AssertionError("Superseded history must not perform a current applicability review")

    def source_guard(*_):
        if not source_access:
            raise DomainError("SOURCE_UNAVAILABLE", "Synthetic unavailable audience", 403)
        return "needs_recheck"

    monkeypatch.setattr(service, "_read_evidence", source_guard)
    monkeypatch.setattr(service, "_basis", unexpected_current_review)
    monkeypatch.setattr(service, "_inspect", unexpected_current_review)
    monkeypatch.setattr(service.front, "_recheck", unexpected_current_review)
    if not source_access:
        with pytest.raises(DomainError) as error:
            service._historical_actual_view(
                None, ctx, request.scope.product_id, row, service._ReadCache()
            )
        assert error.value.reason == "SOURCE_UNAVAILABLE"
        return
    view = service._historical_actual_view(
        None, ctx, request.scope.product_id, row, service._ReadCache()
    )
    assert view["id"] == str(row.id) and view["status"] == "applicable" and not view["current"]
    assert view["source_status"] == "needs_recheck"
    assert view["current_evaluation"] == "not_evaluated_historical"
    assert view["created_at"] == AT.isoformat()
    row.snapshot_sha256 = "bad digest"
    with pytest.raises(DomainError) as error:
        service._historical_actual_view(
            None, ctx, request.scope.product_id, row, service._ReadCache()
        )
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_get_execution_uses_same_explicit_sample_read_context(work, monkeypatch):
    from pdos_next.domain.sample_handoff import service as sample_service

    context, seen = object(), []
    projection = {
        "execution_status": "executing",
        "execution_qualification": "limited_current",
        "stop_required": False,
    }

    def inspect(_s, _ctx, _pid, build_id, *, read_context):
        seen.append((build_id, read_context))
        return projection

    monkeypatch.setattr(sample_service, "inspect_execution", inspect, raising=False)
    assert (
        service._execution(
            None,
            None,
            None,
            work.request.build,
            read_context=context,
        )
        == projection
    )
    assert seen == [(work.request.build.id, context)]
    projection["stop_required"] = True
    with pytest.raises(DomainError) as error:
        service._execution(None, None, None, work.request.build, read_context=context)
    assert error.value.reason == "ACTUAL_SAMPLE_REQUIRED"


def proof_session(work, monkeypatch):
    """Explicit in-memory authority rows and watermarks; all IO is substituted."""
    from pdos_next import service as common_service
    from pdos_next.models import Grant, Principal, Product

    monkeypatch.setattr(common_service, "now", lambda: service.now())
    reviewer = uuid4()
    grant_end = AT + timedelta(hours=2)

    class ProofSession:
        new, dirty, deleted = (), (), ()

        def __init__(self):
            self.info = {}
            self.transaction = object()
            self.engine = SimpleNamespace(_pdos_professional_issuer_epochs={"test": 1})
            self.product = SimpleNamespace(
                id=work.request.scope.product_id,
                tenant_id=work.request.scope.tenant_id,
                category_id=uuid4(),
                lifecycle_epoch=1,
            )
            self.access = [
                (
                    SimpleNamespace(
                        id=person,
                        tenant_id=self.product.tenant_id,
                        kind="human",
                        active=True,
                        access_epoch=1,
                    ),
                    SimpleNamespace(
                        id=uuid4(),
                        principal_id=person,
                        tenant_id=self.product.tenant_id,
                        category_id=self.product.category_id,
                        can_write=True,
                        access_epoch=1,
                        expires_at=grant_end,
                    ),
                )
                for person in (work.actor, reviewer)
            ]
            self.pointers = [SimpleNamespace(id=uuid4(), fact_id=uuid4(), fact_revision=1, epoch=1)]

        @property
        def epoch(self):
            return self.product.lifecycle_epoch

        @epoch.setter
        def epoch(self, value):
            self.product.lifecycle_epoch = value

        def get(self, model, identity):
            if model is Product:
                assert identity == self.product.id
                return self.product
            assert model is Principal
            return next(person for person, _ in self.access if person.id == identity)

        def execute(self, statement):
            assert statement.column_descriptions[0]["entity"] is Principal
            return SimpleNamespace(all=lambda: [self.access[0]])

        def scalar(self, statement):
            assert statement.column_descriptions[0]["entity"] is Grant
            identities = statement.compile().params.values()
            return next(grant for person, grant in self.access if person.id in identities)

        def scalars(self, statement):
            return self.pointers

        def get_transaction(self):
            return self.transaction

        def get_bind(self):
            return self.engine

    operation, purpose = "verification.actual_method.prepare", work.request.purpose
    row = SimpleNamespace(
        owner_id=reviewer,
        project_id=work.request.scope.project_id,
        authority_snapshot={
            "subject_id": str(reviewer),
            "operation": operation,
            "purpose": purpose,
            "roles": ["quality"],
            "synthetic": True,
            "fact_refs": [
                {
                    "id": str(uuid4()),
                    "kind": kind,
                    "role": "quality",
                    "state": "active",
                    "nature": "synthetic",
                    "operations": [operation],
                    "purposes": [purpose],
                    "valid_from": (AT - timedelta(hours=1)).isoformat(),
                    "valid_until": (AT + timedelta(hours=1)).isoformat(),
                }
                for kind in ("duty", "qualification")
            ],
        },
    )
    return ProofSession(), row


def test_bound_proof_reuses_only_current_same_phase_and_rechecks_sources(work, monkeypatch):
    s, row = proof_session(work, monkeypatch)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    monkeypatch.setattr(service, "now", lambda: AT)
    bound, calls = SimpleNamespace(proofs={}), []

    def proof(target=bound):
        service._bound_proof(
            s,
            ctx,
            work.request.scope.product_id,
            target,
            row,
            ("fixed immutable pair",),
            lambda: calls.append("full"),
            lambda: calls.append("source"),
        )

    proof()
    proof()
    assert calls == ["full", "source"]
    proof(SimpleNamespace(proofs={}))  # Another preview/apply Bound cannot share a success.
    assert calls == ["full", "source", "full"]
    s.transaction = object()
    proof()
    assert calls[-1] == "full"
    s.epoch += 1
    proof()
    assert calls[-1] == "full"
    s.engine._pdos_professional_issuer_epochs["test"] += 1
    proof()
    assert calls[-1] == "full"
    s.dirty = (object(),)
    proof()
    assert calls[-1] == "full"


@pytest.mark.parametrize("change", ["principal", "grant_aba", "expires", "qualification_time"])
def test_bound_proof_fresh_scalar_or_time_change_cannot_reuse_positive(work, monkeypatch, change):
    s, row = proof_session(work, monkeypatch)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    clock, full = [AT], []
    monkeypatch.setattr(service, "now", lambda: clock[0])
    bound = SimpleNamespace(proofs={})
    revoked = [False]

    def check():
        full.append(1)
        if revoked[0]:
            raise DomainError("SOURCE_STALE", "Synthetic current professional recheck rejected")

    def proof():
        service._bound_proof(
            s, ctx, work.request.scope.product_id, bound, row, ("fixed",), check, lambda: None
        )

    proof()
    if change == "principal":
        s.access[0][0].active = False
        s.access[0][0].access_epoch += 1
    elif change == "grant_aba":
        s.access[0][1].access_epoch += 2  # Reader revoke/restore with unchanged final rights.
    elif change == "expires":
        clock[0] = s.access[0][1].expires_at
    else:
        s.pointers[0].epoch += 1
        proof()  # A referenced authority watermark change requires a new full check.
        clock[0] = AT + timedelta(hours=1)
    revoked[0] = True
    with pytest.raises(DomainError) as error:
        proof()
    assert error.value.reason == (
        "FORBIDDEN_SCOPE" if change in {"principal", "expires"} else "SOURCE_STALE"
    )
    assert full  # The original full check ran; rejection cannot fabricate a new success.


def test_bound_proof_source_withdrawal_still_rejects_cached_qualification(work, monkeypatch):
    s, row = proof_session(work, monkeypatch)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    monkeypatch.setattr(service, "now", lambda: AT)
    bound = SimpleNamespace(proofs={})
    full = []

    def unavailable():
        raise DomainError("SOURCE_UNAVAILABLE", "Synthetic original withdrawn")

    service._bound_proof(
        s,
        ctx,
        work.request.scope.product_id,
        bound,
        row,
        ("fixed",),
        lambda: full.append(1),
        unavailable,
    )
    with pytest.raises(DomainError) as error:
        service._bound_proof(
            s,
            ctx,
            work.request.scope.product_id,
            bound,
            row,
            ("fixed",),
            lambda: full.append(1),
            unavailable,
        )
    assert error.value.reason == "SOURCE_UNAVAILABLE" and full == [1]


def test_build_filter_authorizes_before_scoped_queries(work, monkeypatch):
    from pdos_next.domain.sample_handoff import service as sample_service

    events, statements = [], []
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    build = SimpleNamespace(id=work.request.build.id)

    class ReadSession:
        def scalars(self, statement):
            statements.append(statement)
            events.append("query")
            return SimpleNamespace(all=lambda: [])

    monkeypatch.setattr(service, "_human", lambda *_: events.append("human"))
    monkeypatch.setattr(sample_service, "ReadContext", lambda *_: object())
    monkeypatch.setattr(service.front, "_build", lambda *_: events.append("build") or build)
    read = {"artifact_id": str(work.source.id), "expected_revision": work.source.revision}

    def linked(*_):
        events.append("linked")
        return object(), {}, {}, [read]

    def sources(_s, _ctx, _pid, reads):
        assert reads == [read]
        events.append("source")

    monkeypatch.setattr(service.front, "_linked", linked)
    monkeypatch.setattr(service, "_sources", sources)
    s = ReadSession()
    result = service.list_verification_handoff(
        s, ctx, work.request.scope.product_id, build_id=build.id
    )
    assert events[:4] == ["human", "build", "linked", "source"]
    assert result["requests"] == result["actual_methods"] == result["handoffs"] == []
    assert len(statements) == 3
    for statement in statements:
        text = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert ".build_id = " in text and str(build.id).replace("-", "") in text.replace("-", "")
    statements.clear()
    service.list_verification_handoff(s, ctx, work.request.scope.product_id)
    assert all(".build_id = " not in str(statement) for statement in statements)

    def hidden(*_):
        raise DomainError("FORBIDDEN_SCOPE", "Synthetic private other Build", 403)

    statements.clear()
    monkeypatch.setattr(service.front, "_build", hidden)
    with pytest.raises(DomainError) as error:
        service.list_verification_handoff(s, ctx, work.request.scope.product_id, build_id=uuid4())
    assert error.value.reason == "FORBIDDEN_SCOPE" and not statements


@pytest.mark.parametrize("advance", ["clock", "source"])
def test_bound_proof_referenced_fact_expiry_during_io_cannot_reuse_success(
    work, monkeypatch, advance
):
    s, row = proof_session(work, monkeypatch)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    clock, full, enabled = [AT], [], [False]
    expiry = AT + timedelta(seconds=1)
    for fact in row.authority_snapshot["fact_refs"]:
        fact["valid_until"] = expiry.isoformat()
    monkeypatch.setattr(
        service, "now", lambda: expiry if enabled[0] and advance == "clock" else clock[0]
    )

    def sources():
        if enabled[0] and advance == "source":
            clock[0] = expiry

    bound = SimpleNamespace(proofs={})

    def proof():
        service._bound_proof(
            s,
            ctx,
            work.request.scope.product_id,
            bound,
            row,
            ("fixed",),
            lambda: full.append(1),
            sources,
        )

    proof()
    assert bound.proofs[("fixed",)][1] == s.access[0][1].expires_at
    enabled[0] = True
    with pytest.raises(DomainError) as error:
        proof()
    assert error.value.reason == "SOURCE_STALE" and full == [1]


@pytest.mark.parametrize("change", ["clock", "issuer"])
def test_bound_proof_drift_during_full_check_never_returns_success(work, monkeypatch, change):
    s, row = proof_session(work, monkeypatch)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    clock = [AT]
    monkeypatch.setattr(service, "now", lambda: clock[0])
    bound = SimpleNamespace(proofs={})

    def check():
        if change == "clock":
            clock[0] = AT + timedelta(hours=1)
        else:
            s.engine._pdos_professional_issuer_epochs["test"] += 1

    with pytest.raises(DomainError) as error:
        service._bound_proof(
            s, ctx, work.request.scope.product_id, bound, row, ("fixed",), check, lambda: None
        )
    assert error.value.reason == "SOURCE_STALE" and bound.proofs == {}


def test_sample_view_inspects_full_chain_once_and_preserves_existing_renderer(work, monkeypatch):
    from pdos_next.domain.build_execution import service as builds

    ref, inspected, calls = work.samples[0], {}, []
    row = SimpleNamespace(
        id=ref.id,
        revision=ref.revision,
        build_id=ref.build_id,
        actual_configuration_id=ref.actual_configuration.id,
        cavity=ref.cavity,
    )
    context = object()

    def inspect(_s, _ctx, _pid, _request, reference, *, read_context):
        calls.append((reference, read_context))
        return {
            "actual_configuration": {"id": str(ref.actual_configuration.id), "revision": 1},
            "lot": {"nature": "synthetic"},
            "availability": "hold",
            "current_readiness": {"state": "hold"},
            "facts_revision": "a" * 64,
            "reason_codes": ["SAMPLE_ON_HOLD"],
            "required_source_read_set": [],
            "source_refs": [],
        }

    def render(_s, _ctx, _pid, identity, chain):
        assert identity is row and chain["actual_row"].revision == 1
        assert chain["lot"].observation_nature == "synthetic"
        inspected["renderer"] = True
        return {"label": "Synthetic original label", "reservation": None, "consumption": None}

    def repeated_chain(*_):
        raise AssertionError("GET must not call get_sample before the complete inspector")

    monkeypatch.setattr(builds, "get_sample", repeated_chain)
    monkeypatch.setattr(builds, "sample_view", render)
    monkeypatch.setattr(service, "_inspect", inspect)
    actual = SimpleNamespace(
        id=ref.actual_configuration.id,
        tenant_id=work.request.scope.tenant_id,
        product_id=work.request.scope.product_id,
        build_id=work.request.build.id,
        revision=ref.actual_configuration.revision,
    )
    s = SimpleNamespace(get=lambda model, identity: actual if identity == actual.id else None)
    ctx = Context(work.request.scope.tenant_id, work.actor, work.actor)
    view, reference, value = service._sample_view(
        s, ctx, work.request.scope.product_id, work.request, row, read_context=context
    )
    assert len(calls) == 1 and calls[0] == (ref, context)
    assert inspected["renderer"] and view["label"] == "Synthetic original label"
    assert view["availability"] == "hold" and value["availability"] == "hold"
    assert reference == ref and view["reservation"] is view["consumption"] is None
