"""The continuation bridge preserves missing facts and actual execution identity."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource
from pdos_next.agent_kernel.disclosure import disclosure, skill_operations
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentToolCall,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.domain.verification_execution.schemas import PreparationRecordPayload
from pdos_next.domain.verification_execution.service import semantic
from pdos_next.domain.verification_front.schemas import RequestCreatePayload
from pdos_next.enterprise_search.verification_candidates import (
    PREPARATION,
    _command,
    _model_binding,
    _request_binding,
    _run,
    preparation_binding,
    resolve_draft,
)
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Receipt
from pdos_next.schemas.verification.contracts import BuildRef
from pdos_next.service import Context, digest
from tests.agent_kernel.test_gateway import configured_route


def data():
    selection = BuildRef(
        id=uuid4(), revision=3, product_id=uuid4(), project_id=uuid4(),
        engineering_configuration={"id": uuid4(), "revision": 2},
        manufacturing_configuration={"id": uuid4(), "revision": 4},
    )
    source = {"artifact_id": str(uuid4()), "expected_revision": 1,
              "line": 3, "quote": "登记的压力保持要求"}
    draft = {"title": "核对密封措施", "purpose": "验证本次措施在选择的配置下是否有效",
             "return_form": "逐项测量结果与异常记录", "reason": "依据本次已核对讨论准备复验",
             "items": [{"id": "pressure", "feature": "压力保持", "sample_count": 5}],
             "sources": [source]}
    return selection, draft


def ready():
    selection, draft = data()
    result = resolve_draft(draft, request_id=uuid4(), selection=selection)
    assert result["status"] == "ready"
    return selection, result["arguments"]


def test_missing_sample_count_and_build_are_clarified_without_defaulting_to_one():
    _selection, draft = data()
    draft["items"][0].pop("sample_count")
    result = resolve_draft(draft, request_id=uuid4())
    assert result["status"] == "needs_input" and result["arguments"] is None
    assert set(result["missing"]) == {"build_and_configurations", "items.pressure.sample_count"}
    assert {question["id"] for question in result["questions"]} == {
        "build_selection", "sample_count",
    }
    assert all(question["recommended"] is None for question in result["questions"])


def test_ready_draft_is_native_preparation_payload_and_unknown_method_stays_empty():
    selection, arguments = ready()
    payload = PreparationRecordPayload.model_validate(arguments)
    assert payload.build_id == selection.id and payload.expected_build_revision == 3
    assert payload.items[0].sample_count == 5
    assert payload.items[0].method is payload.items[0].criterion is None
    assert payload.expected_at is payload.tentative_at is None
    result = resolve_draft(arguments, request_id=payload.request_id, selection=selection)
    assert result["unconfirmed"] == ["items.pressure.method", "items.pressure.criterion"]
    assert not result["questions"]


@pytest.mark.parametrize("count", [0, True, 1.5, "1", 10_001])
def test_sample_count_keeps_existing_strict_domain_bounds(count):
    selection, draft = data()
    draft["items"][0]["sample_count"] = count
    with pytest.raises(ValidationError):
        resolve_draft(draft, request_id=uuid4(), selection=selection)


def test_discussion_citation_cannot_become_an_execution_artifact_reference():
    selection, draft = data()
    draft["sources"] = [{"citation_id": str(uuid4()), "quote": "已核对的讨论"}]
    with pytest.raises(ValidationError):
        resolve_draft(draft, request_id=uuid4(), selection=selection)


def test_draft_criterion_text_without_an_exact_source_stays_unconfirmed():
    selection, draft = data()
    draft["items"][0]["criterion_text"] = "本次讨论建议的判据，尚无原文"
    result = resolve_draft(draft, request_id=uuid4(), selection=selection)
    assert result["status"] == "ready"
    assert "items.pressure.criterion" in result["unconfirmed"]


def test_bridge_does_not_offer_t2_or_general_command_authority():
    from pdos_next.enterprise_search.verification_candidates import record

    with pytest.raises(DomainError) as error:
        record(None, None, uuid4(), operation="test.run.review", arguments={}, source=None,
               selection=None, owner=None)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_candidate_get_select_is_valid_in_read_only_transaction_and_creation_locks_run():
    original, _selected, _command, _preparation, _receipt = fixture()
    run = AgentRun(**vars(original), writer_id=uuid4(), session_id=uuid4(), proposal_id=None,
                   private_context=False, data_categories=["internal"], customer_identities=[],
                   state="completed", reverted_at=None, trigger="conversation")
    ctx = Context(run.tenant_id, run.requester_id, run.requester_id, category_id=run.category_id)

    class ReadSession:
        info = {"scope": (run.tenant_id, run.requester_id, run.requester_id, run.category_id),
                "read_snapshot": True}

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            assert ("FOR UPDATE" in sql) is not self.info["read_snapshot"]
            return run

        def get(self, model, identity):
            assert model is Principal and identity == run.requester_id
            return SimpleNamespace(kind="human", active=True)

    session = ReadSession()
    assert _run(session, ctx, run.id) is run
    run.state = "running"
    session.info = {**session.info, "read_snapshot": False}
    assert _run(session, ctx, run.id, creating=True) is run


@pytest.mark.parametrize("change", [
    {"build_id": str(uuid4())}, {"expected_build_revision": 1},
    {"confirmation_token": "copied-client-token-value"}, {"expected_request_revision": 1},
])
def test_explicit_selection_and_fresh_confirmation_cannot_be_replaced(change):
    selection, draft = data()
    draft.update(change)
    with pytest.raises(DomainError):
        resolve_draft(draft, request_id=uuid4(), selection=selection)


def fixture():
    selection, arguments = ready()
    run = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), category_id=uuid4(),
                          product_id=selection.product_id, project_id=selection.project_id,
                          requester_id=uuid4(), cancel_epoch=0,
                          read_sources=[arguments["sources"][0]])
    command = _command(run, PREPARATION, arguments, "synthetic-stable-candidate-key", 7)
    preparation = SimpleNamespace(
        id=uuid4(), tenant_id=run.tenant_id, product_id=run.product_id,
        project_id=run.project_id, owner_id=run.requester_id,
        request_id=arguments["request_id"], build_id=selection.id, build_revision=3,
        revision=1, input_snapshot=semantic(PreparationRecordPayload.model_validate(arguments)),
        request_snapshot={"fixed": "server-owned-domain-snapshot"},
    )
    preparation.request_id = PreparationRecordPayload.model_validate(arguments).request_id
    preparation.snapshot_sha256 = digest(preparation.request_snapshot)
    receipt = SimpleNamespace(
        id=uuid4(), tenant_id=run.tenant_id, requester_id=run.requester_id,
        category_id=run.category_id, product_id=run.product_id, command_id=command.command_id,
        operation=PREPARATION, subject_type="verification_preparation",
        subject_id=preparation.id, subject_revision=1, confirmation_id=None,
    )
    return run, selection, command, preparation, receipt


def test_fixed_preparation_comes_from_receipt_revision_and_full_snapshot_hash():
    run, selection, command, preparation, receipt = fixture()
    fixed = preparation_binding(command, receipt, preparation)
    assert fixed == {"receipt_id": str(receipt.id), "preparation_id": str(preparation.id),
                     "expected_preparation_revision": 1,
                     "preparation_sha256": digest(preparation.request_snapshot)}
    request = RequestCreatePayload(
        request_id=uuid4(), preparation_id=preparation.id,
        expected_preparation_revision=fixed["expected_preparation_revision"],
        preparation_sha256=fixed["preparation_sha256"], reason="依据已确认准备记录建立请求",
    )
    _request_binding(request, preparation, run, selection)
    assert _command(run, PREPARATION, command.payload, command.idempotency_key, 7) == command
    assert not hasattr(request, "confirmation_token")  # Native T0 remains unchanged.


@pytest.mark.parametrize("target,field,value", [
    ("receipt", "command_id", uuid4()), ("receipt", "requester_id", uuid4()),
    ("receipt", "product_id", uuid4()), ("receipt", "subject_revision", 2),
    ("preparation", "snapshot_sha256", "0" * 64),
    ("preparation", "build_revision", 4),
])
def test_other_receipt_or_changed_preparation_cannot_advance(target, field, value):
    _run, _selection, command, preparation, receipt = fixture()
    setattr(receipt if target == "receipt" else preparation, field, value)
    with pytest.raises(DomainError):
        preparation_binding(command, receipt, preparation)


def test_changed_payload_is_not_a_confirmation_of_the_old_discussion_candidate():
    _run, _selection, command, preparation, receipt = fixture()
    preparation.input_snapshot = deepcopy(preparation.input_snapshot)
    preparation.input_snapshot["items"][0]["sample_count"] = 6
    with pytest.raises(DomainError):
        preparation_binding(command, receipt, preparation)


def test_candidate_model_identity_is_the_completed_call_and_exact_response_index():
    run, _selection, command, _preparation, _receipt = fixture()
    source = WriteSource(model_call_id=uuid4(), response_index=0, skill=SkillBinding(
        key="test_verification", version="fixed@1", digest="a" * 64, load_event_id=uuid4(),
    ))
    binding = ModelBinding(
        model_version="synthetic@1", model_route_digest="a" * 64,
        tool_definitions_digest="b" * 64, prompt_digest="c" * 64,
        isolation="main", cancel_epoch=0, loaded_skills=(source.skill,),
    )
    call = SimpleNamespace(id=source.model_call_id, tenant_id=run.tenant_id, run_id=run.id,
                           tool="model", state="completed", error_code=None,
                           execution_binding=binding.model_dump(mode="json"),
                           result={"calls": [{"name": PREPARATION,
                                              "arguments": command.payload}]})
    assert _model_binding(call, run, source, PREPARATION, command.payload) == digest(
        call.execution_binding,
    )
    for changes in ({"state": "started"}, {"run_id": uuid4()}, {"tool": "assistant.extract"}):
        changed = SimpleNamespace(**{**vars(call), **changes})
        with pytest.raises(DomainError):
            _model_binding(changed, run, source, PREPARATION, command.payload)
    forged = {**command.payload, "purpose": "换成没有核对的目标"}
    with pytest.raises(DomainError):
        _model_binding(call, run, source, PREPARATION, forged)


def test_event_bridge_replays_actual_model_sources_then_requires_saved_preparation(monkeypatch):
    """Synthetic I/O ports; actual candidate/model-binding/domain DTO logic runs.

    This does not replace the later PostgreSQL/HTTP audience or confirmation
    checks. There is no command executor in this module or this harness.
    """
    from pdos_next.enterprise_search import action_sources
    from pdos_next.enterprise_search import verification_candidates as bridge

    run, selected, _command_row, preparation, receipt = fixture()
    run = AgentRun(
        **vars(run), writer_id=uuid4(), session_id=uuid4(), proposal_id=None,
        private_context=False, data_categories=["internal"], customer_identities=[],
        state="running", reverted_at=None, trigger="conversation",
    )
    ctx = Context(run.tenant_id, run.requester_id, run.requester_id, category_id=run.category_id)
    catalog, registry, route = SkillCatalog(), default_registry(), configured_route()
    skill = catalog.configuration("test_verification")
    skill_source = SkillBinding(key=skill.key, version=skill.version, digest=skill.digest,
                                load_event_id=uuid4())
    binding = ModelBinding(
        model_version=route.version, model_route_digest=route.digest, isolation="main",
        cancel_epoch=0, loaded_skills=(skill_source,), prompt_digest=digest("fixed prefix"),
        tool_definitions_digest=digest(disclosure(registry, "main", skill_operations([skill]))),
    )
    run.versions = {"model_version": route.version, "model_route_digest": route.digest,
                    "tool_definitions": {"main": binding.tool_definitions_digest},
                    "prompt_prefixes": {"main": binding.prompt_digest}}
    loaded = AgentEvent(
        id=skill_source.load_event_id, tenant_id=run.tenant_id, run_id=run.id, sequence=1,
        body={"type": "skill_loaded", "key": skill.key, "version": skill.version,
              "digest": skill.digest, "isolation": "main"},
    )

    class Session:
        def __init__(self):
            self.info = {"scope": (
                run.tenant_id, run.requester_id, run.requester_id, run.category_id,
            )}
            self.rows = {(AgentRun, run.id): run, (AgentEvent, loaded.id): loaded,
                         (Principal, run.requester_id): SimpleNamespace(kind="human", active=True)}

        def get(self, model, identity):
            return self.rows.get((model, identity))

        def scalar(self, query):
            description = query.column_descriptions[0]
            if description["name"] == "coalesce":
                return max(row.sequence for (kind, _), row in self.rows.items()
                           if kind is AgentEvent)
            if description["entity"] is TenantSkillEnablement:
                return SimpleNamespace(enabled=True)
            if description["entity"] is AgentRun:
                return run
            assert description["entity"] is AgentEvent
            values = query.compile().params.values()
            return next((row for (kind, _), row in self.rows.items()
                         if kind is AgentEvent and row.body.get("intent_key") in values), None)

        def add(self, row):
            self.rows[type(row), row.id] = row

        def flush(self):
            pass

    session = Session()
    owner = SimpleNamespace(registry=registry, catalog=catalog, route=lambda *_: route)
    build = SimpleNamespace(id=selected.id, revision=selected.revision,
                            product_id=run.product_id, project_id=run.project_id)
    monkeypatch.setattr(bridge, "require_access", lambda *_: SimpleNamespace(
        revision=7, category_id=run.category_id,
    ))
    monkeypatch.setattr(bridge, "_build", lambda *_: build)
    monkeypatch.setattr(bridge, "_linked", lambda *_, **_kw: (
        SimpleNamespace(), selected.engineering_configuration.model_dump(mode="json"),
        selected.manufacturing_configuration.model_dump(mode="json"), run.read_sources,
    ))
    revoked, captures = [], []

    def recheck(_s, _ctx, _run, frozen, *, preparation_id=None):
        assert _s is session and _run.id == run.id
        if revoked:
            raise DomainError("SOURCE_UNAVAILABLE", "合成来源已撤回")
        assert frozen["digest"] == digest({key: val for key, val in frozen.items()
                                           if key != "digest"})
        return deepcopy(frozen)

    def capture(_s, _ctx, _run, citations, **kwargs):
        captures.append((citations, kwargs))
        proof = {"version": 1, "run_id": str(run.id), "discussion_sources": [
            {"citation_id": citations[0], "origin_run_id": str(uuid4()),
             "source_revision": 2, "content_hash": "a" * 64}],
            "read_set": [{key: value for key, value in ref.items()
                          if key in {"artifact_id", "expected_revision"}}
                         for ref in run.read_sources]}
        proof["digest"] = digest(proof)
        return recheck(_s, _ctx, _run, proof)

    monkeypatch.setattr(action_sources, "capture", capture)
    monkeypatch.setattr(action_sources, "recheck", recheck)

    def model(operation, arguments):
        call = AgentToolCall(id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, tool="model",
                             state="completed", error_code=None,
                             execution_binding=binding.model_dump(mode="json"),
                             result={"calls": [{"name": operation, "arguments": arguments}]})
        session.add(call)
        return WriteSource(model_call_id=call.id, response_index=0, skill=skill_source)

    arguments = _command_row.payload
    source, citations = model(PREPARATION, arguments), [str(uuid4())]
    prepared = bridge.record(session, ctx, run.id, operation=PREPARATION, arguments=arguments,
                             source=source, selection=selected, owner=owner, citation_ids=citations)
    assert prepared["operation_tier"] == "T1" and prepared["next_action"] == "preview"
    assert prepared["command"]["payload"]["confirmation_token"] is None
    same = bridge.record(session, ctx, run.id, operation=PREPARATION, arguments=arguments,
                         source=source, selection=selected, owner=owner, citation_ids=citations)
    assert same == prepared and len(captures) == 1
    assert len([row for (kind, _), row in session.rows.items()
                if kind is AgentEvent and row.body["type"] == bridge.EVENT]) == 1

    # Only a real saved receipt/row supplied by the domain owner enables phase 2.
    receipt.command_id = UUID(prepared["command"]["command_id"])
    session.rows[Receipt, receipt.id] = receipt
    monkeypatch.setattr(bridge.preparation_service, "get_preparation", lambda *_: (preparation, {}))
    request = {"request_id": str(uuid4()), "preparation_id": str(preparation.id),
               "expected_preparation_revision": 1,
               "preparation_sha256": preparation.snapshot_sha256,
               "reason": "采用已确认准备的固定内容"}
    request_source = model(bridge.REQUEST, request)
    next_candidate = bridge.record(
        session, ctx, run.id, operation=bridge.REQUEST, arguments=request, source=request_source,
        selection=selected, owner=owner, parent_event_id=UUID(prepared["event_id"]),
        preparation_receipt_id=receipt.id,
    )
    assert next_candidate["operation_tier"] == "T0"
    assert next_candidate["next_action"] == "confirm_human_command"
    assert next_candidate["preparation"]["receipt_id"] == str(receipt.id)
    assert next_candidate["source_proof"]["discussion_sources"] == prepared["source_proof"][
        "discussion_sources"
    ]
    assert bridge.read(session, ctx, run.id, UUID(next_candidate["event_id"])) == next_candidate
    revoked.append(True)
    with pytest.raises(DomainError):
        bridge.read(session, ctx, run.id, UUID(next_candidate["event_id"]))
