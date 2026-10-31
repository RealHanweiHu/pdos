"""Explicit project actions retain the real target, sources and method version."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pdos_next.agent_kernel.api import StartInput
from pdos_next.agent_kernel.context_projection import combine_contracts, project
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.requested_skills import RequestedSkill
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.contracts import SourceRead
from pdos_next.enterprise_search import verification_actions as actions
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import BuildRef
from pdos_next.service import Context, digest
from pydantic import ValidationError


@pytest.fixture
def case(monkeypatch):
    tenant, human, category, product, project_id = [uuid4() for _ in range(5)]
    ctx = Context(tenant, human, human, category_id=category)
    selected = BuildRef(
        id=uuid4(), revision=3, product_id=product, project_id=project_id,
        engineering_configuration={"id": uuid4(), "revision": 2},
        manufacturing_configuration={"id": uuid4(), "revision": 4},
    )
    parent = SimpleNamespace(
        id=uuid4(), tenant_id=tenant, requester_id=human, category_id=category,
        product_id=product, project_id=project_id, session_id=uuid4(),
    )
    current = SimpleNamespace(
        id=uuid4(), tenant_id=tenant, requester_id=human, category_id=category,
        product_id=product, project_id=project_id, session_id=parent.session_id,
        continued_from_id=parent.id,
    )
    citations = [uuid4(), uuid4()]
    requested = actions.VerificationAction(selection=selected, citation_ids=citations)
    source = SourceRead(artifact_id=uuid4(), expected_revision=2)
    effective = StartInput(
        goal="继续准备复验", idempotency_key="action-source-key", session_id=parent.session_id,
        continue_from_run_id=parent.id, product_id=product, project_id=project_id,
        sources=[source],
    )
    proof = {
        "taint": {"private": False, "customer_original": False},
        "read_set": [{"artifact_id": str(uuid4()), "expected_revision": 3}],
        "discussion_sources": [{"citation_id": str(cid)} for cid in citations],
    }
    calls = []
    state = SimpleNamespace(proof=proof, selected=selected)

    def target(session, actual_ctx, actual_parent, selection):
        assert actual_ctx is ctx and actual_parent is parent
        calls.append(("target", selection))
        return None, SimpleNamespace(name="Build复验A"), None, state.selected, []

    def capture(session, actual_ctx, actual_parent, cids, **kwargs):
        assert actual_ctx is ctx and actual_parent is parent
        assert kwargs == {"product_id": product, "build_id": state.selected.id,
                          "include_taint": True}
        assert tuple(cids) == requested.citation_ids
        calls.append(("capture", cids))
        return deepcopy(state.proof)

    def recheck(session, actual_ctx, actual_parent, frozen):
        assert actual_ctx is ctx and actual_parent is parent
        calls.append(("recheck", deepcopy(frozen)))
        return deepcopy(state.proof)

    def get(model, identity):
        assert model is AgentRun and identity == parent.id
        return parent

    monkeypatch.setattr(actions, "_target", target)
    monkeypatch.setattr(actions, "capture", capture)
    monkeypatch.setattr(actions, "recheck", recheck)
    from pdos_next.agent_kernel import requested_skills

    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_args: True)
    return SimpleNamespace(
        ctx=ctx, selected=selected, parent=parent, run=current, requested=requested,
        effective=effective, session=SimpleNamespace(get=get), source=source, state=state,
        calls=calls,
    )


def start(case, **kwargs):
    return actions.prepare_start(
        case.session, case.ctx, kwargs.get("effective", case.effective),
        kwargs.get("parent", case.parent), kwargs.get("requested", case.requested),
    )


def test_no_action_returns_original_input_and_requested_methods_without_source_queries(case):
    effective, action, methods = start(case, requested=None)
    assert effective is case.effective and action is None
    assert methods == tuple(case.effective.requested_skills) and not case.calls


@pytest.mark.parametrize("missing", ["parent", "product_id", "project_id"])
def test_action_requires_an_existing_project_discussion(case, missing):
    parent = None if missing == "parent" else case.parent
    if parent is not None:
        setattr(parent, missing, None)
    with pytest.raises(DomainError) as failure:
        start(case, parent=parent)
    assert failure.value.reason == "INVALID_PAYLOAD" and not case.calls


@pytest.mark.parametrize("field", ["project_id", "product_id", "category_id"])
def test_action_does_not_move_discussion_to_another_scope(case, field):
    if field == "category_id":
        case.parent.category_id = uuid4()
        effective = case.effective
    else:
        effective = case.effective.model_copy(update={field: uuid4()})
    with pytest.raises(DomainError) as failure:
        start(case, effective=effective)
    assert failure.value.code == "FORBIDDEN_SCOPE" and not case.calls


def test_start_adds_real_build_reads_and_current_server_method_without_mutating_input(case):
    effective, action, methods = start(case)
    registered = SkillCatalog().configuration("test_verification")
    assert len(methods) == 1 and methods[0] == RequestedSkill(
        key=registered.key, version=registered.version, digest=registered.digest,
    )
    assert effective is not case.effective and case.effective.sources == [case.source]
    assert {(str(ref.artifact_id), ref.expected_revision) for ref in effective.sources} == {
        (str(case.source.artifact_id), 2),
        (case.state.proof["read_set"][0]["artifact_id"], 3),
    }
    assert action["selection"] == case.selected.model_dump(mode="json")
    assert action["source_run_id"] == str(case.parent.id)
    assert action["citation_ids"] == sorted(str(cid) for cid in case.requested.citation_ids)
    assert action["source_proof"] == case.state.proof
    assert [name for name, _ in case.calls] == ["target", "capture"]


@pytest.mark.parametrize("field,value", [("version", "stale-version"), ("digest", "0" * 64)])
def test_existing_current_method_is_not_duplicated_and_stale_method_is_rejected(case, field, value):
    registered = SkillCatalog().configuration("test_verification")
    current = RequestedSkill(
        key=registered.key, version=registered.version, digest=registered.digest,
    )
    effective = case.effective.model_copy(update={"requested_skills": [current]})
    assert start(case, effective=effective)[2] == (current,)
    stale = current.model_copy(update={field: value})
    with pytest.raises(DomainError) as failure:
        start(case, effective=effective.model_copy(update={"requested_skills": [stale]}))
    assert failure.value.code == "VERSION_CONFLICT"


def test_disabled_server_method_cannot_be_enabled_by_action(case, monkeypatch):
    from pdos_next.agent_kernel import requested_skills

    monkeypatch.setattr(requested_skills, "skill_enabled", lambda *_args: False)
    with pytest.raises(DomainError) as failure:
        start(case)
    assert failure.value.code == "FORBIDDEN_SCOPE"


def test_action_read_merge_cannot_replace_a_pinned_artifact_version(case):
    case.state.proof["read_set"] = [{
        "artifact_id": str(case.source.artifact_id), "expected_revision": 3,
    }]
    with pytest.raises(DomainError) as failure:
        start(case)
    assert failure.value.code == "VERSION_CONFLICT"
    assert case.effective.sources == [case.source]


def test_same_read_is_merged_once_and_discussion_cids_never_become_artifact_reads(case):
    case.state.proof["read_set"] = [case.source.model_dump(mode="json")]
    effective, action, _skills = start(case)
    assert effective.sources == [case.source]
    assert not {str(cid) for cid in case.requested.citation_ids}.intersection(
        str(ref.artifact_id) for ref in effective.sources
    )
    assert len(action["source_proof"]["discussion_sources"]) == 2


def test_request_identity_is_stable_for_one_start_and_changes_for_another(case):
    first = start(case)[1]
    assert start(case)[1]["request_id"] == first["request_id"]
    next_effective = case.effective.model_copy(update={"idempotency_key": "another-action-key"})
    assert start(case, effective=next_effective)[1]["request_id"] != first["request_id"]


@pytest.mark.parametrize("extra", [
    {"request_id": str(uuid4())}, {"source_proof": {}}, {"skill": "admin"},
    {"actor_id": str(uuid4())},
])
def test_client_action_cannot_supply_server_identity_proof_or_method(case, extra):
    with pytest.raises(ValidationError):
        actions.VerificationAction.model_validate({
            **case.requested.model_dump(mode="json"), **extra,
        })


def test_check_action_rechecks_fixed_parent_proof_and_actual_target(case):
    action = start(case)[1]
    case.calls.clear()
    assert actions.check_action(case.session, case.ctx, case.run, action) == case.state.proof
    assert [name for name, _ in case.calls] == ["target", "recheck"]
    assert case.calls[-1][1] == action["source_proof"]


@pytest.mark.parametrize("field", [
    "tenant_id", "session_id", "requester_id", "product_id", "project_id", "category_id", "id",
])
def test_check_action_rejects_other_parent_owner_scope_or_session_before_source_read(case, field):
    action = start(case)[1]
    case.calls.clear()
    if field == "id":
        case.run.continued_from_id = uuid4()
    else:
        setattr(case.parent, field, uuid4())
    with pytest.raises(DomainError) as failure:
        actions.check_action(case.session, case.ctx, case.run, action)
    assert failure.value.code == "FORBIDDEN_SCOPE" and not case.calls


def test_check_action_does_not_accept_a_substituted_discussion_citation(case):
    action = start(case)[1]
    case.state.proof["discussion_sources"][0]["citation_id"] = str(uuid4())
    with pytest.raises(DomainError) as failure:
        actions.check_action(case.session, case.ctx, case.run, action)
    assert failure.value.code == "SOURCE_STALE"


def test_revoked_parent_proof_stops_action_without_substituting_latest_sources(case, monkeypatch):
    action = start(case)[1]

    def revoked(*_args, **_kwargs):
        raise DomainError("SOURCE_UNAVAILABLE", "已撤回")

    monkeypatch.setattr(actions, "recheck", revoked)
    with pytest.raises(DomainError) as failure:
        actions.check_action(case.session, case.ctx, case.run, action)
    assert failure.value.code == "SOURCE_UNAVAILABLE"


def test_dynamic_context_is_closed_and_preserves_target_identity_without_proof_disclosure(case):
    action = start(case)[1]
    value = actions.context_value(action)
    Draft202012Validator.check_schema(actions.CONTEXT_SCHEMA)
    Draft202012Validator(actions.CONTEXT_SCHEMA).validate(value)
    assert value["target"] == case.selected.model_dump(mode="json")
    assert value["request_id"] == action["request_id"]
    assert "source_proof" not in value and "source_run_id" not in value
    contaminated = {**value, "private_proof": "must not leave"}
    with pytest.raises(SchemaValidationError) as failure:
        Draft202012Validator(actions.CONTEXT_SCHEMA).validate(contaminated)
    assert "Additional properties" in str(failure.value)


def test_combined_context_keeps_action_and_drops_unregistered_nested_fields(case):
    catalog = SkillCatalog()
    schema = combine_contracts(catalog, [catalog.configuration("test_verification")])
    value = actions.context_value(start(case)[1])
    injected = deepcopy(value)
    injected["target"]["permission"] = "fake"
    projected, omitted, _issues = project({
        "goal": "prepare", "sources": [], "verification_action": injected,
    }, schema)
    assert projected["verification_action"] == value
    assert {"field": "/verification_action/target/permission",
            "reason": "outside_skill_context_schema"} in omitted
    assert "verification_action" not in schema["required"]
    no_action, omitted, _issues = project({"goal": "prepare", "sources": []}, schema)
    assert "verification_action" not in no_action
    assert not any(row["field"].startswith("/verification_action") for row in omitted)


@pytest.mark.parametrize("invalid", [None, {"version": 2, "kind": "prepare_verification"},
                                      {"version": 1, "kind": "other_action"}])
def test_unknown_action_contract_cannot_reach_parent_or_proof_reads(case, invalid):
    with pytest.raises(DomainError) as failure:
        actions.check_action(case.session, case.ctx, case.run, invalid)
    assert failure.value.code == "VERSION_CONFLICT" and not case.calls


def test_missing_parent_is_unavailable_before_target_or_source_read(case):
    action = start(case)[1]
    case.calls.clear()
    case.session.get = lambda *_args: None
    with pytest.raises(DomainError) as failure:
        actions.check_action(case.session, case.ctx, case.run, action)
    assert failure.value.code == "FORBIDDEN_SCOPE" and not case.calls


def test_source_capture_denial_propagates_without_mutating_start_or_replacing_sources(
    case, monkeypatch,
):
    original = case.effective.model_dump(mode="json")

    def denied(*_args, **_kwargs):
        raise DomainError("FORBIDDEN_SCOPE", "source audience does not cover target")

    monkeypatch.setattr(actions, "capture", denied)
    with pytest.raises(DomainError) as failure:
        start(case)
    assert failure.value.code == "FORBIDDEN_SCOPE"
    assert case.effective.model_dump(mode="json") == original
    assert [name for name, _ in case.calls] == ["target"]


def test_missing_current_run_rejects_action_before_parent_read(case):
    action = start(case)[1]
    case.calls.clear()
    with pytest.raises(DomainError):
        actions.check_action(case.session, case.ctx, None, action)
    assert not case.calls


@pytest.mark.parametrize("include_null,add_action", [(False, False), (True, False), (False, True)])
def test_actual_start_endpoint_preserves_legacy_no_action_idempotency_digest(
    case, monkeypatch, include_null, add_action,
):
    from pdos_next.agent_kernel import api

    legacy_request = {
        "goal": "Existing no-action request", "session_id": uuid4(),
        "continue_from_run_id": None, "product_id": case.parent.product_id,
        "proposal_id": None, "sources": [],
    }
    data = StartInput(idempotency_key="existing-legacy-intent", **legacy_request,
                      **({"verification_action": None} if include_null else {}))
    existing = SimpleNamespace(
        id=uuid4(), tenant_id=case.ctx.tenant_id, requester_id=case.ctx.requester_id,
        category_id=case.ctx.category_id, product_id=case.parent.product_id,
        project_id=None, proposal_id=None, session_id=data.session_id,
        continued_from_id=None, state="queued", intent_digest=digest({
            "category_id": case.ctx.category_id, "request": legacy_request,
        }),
    )
    queries = iter([existing, uuid4()])
    workflows = []

    def no_new_run(*_args, **_kwargs):
        pytest.fail("Legacy retry attempted a new run, command or source binding")

    session = SimpleNamespace(
        execute=lambda *_args, **_kwargs: None,
        scalar=lambda *_args, **_kwargs: next(queries), add=no_new_run,
    )

    @contextmanager
    def transaction(_engine, tenant_id, **kwargs):
        assert tenant_id == case.ctx.tenant_id
        assert kwargs["actor_id"] == kwargs["requester_id"] == case.ctx.requester_id
        yield session

    async def workflow(reference):
        workflows.append(reference)

    monkeypatch.setattr(api, "tenant_session", transaction)
    monkeypatch.setattr(api, "require_access", lambda *_args: None)
    ports = api.ApiPorts(writer_for=no_new_run, binding_for=no_new_run,
                         start_workflow=workflow, signal_workflow=no_new_run,
                         cancel_workflow=no_new_run)
    router = api.router(None, context_dependency=lambda: case.ctx, ports=ports)
    endpoint = next(route.endpoint for route in router.routes if
                    getattr(route, "path", None) == "/v1/categories/{category_id}/agent-runs"
                    and "POST" in route.methods)
    if add_action:
        data = data.model_copy(update={"verification_action": case.requested})
        with pytest.raises(DomainError) as failure:
            asyncio.run(endpoint(data, ctx=case.ctx))
        assert failure.value.code == "DUPLICATE_INTENT_CONFLICT" and not workflows
    else:
        result = asyncio.run(endpoint(data, ctx=case.ctx))
        assert result["run_id"] == str(existing.id) and result["status"] == "queued"
        assert len(workflows) == 1 and workflows[0]["subject_id"] == str(existing.id)


def test_prepare_start_merges_current_proof_taint_without_selecting_uncited_reads(case):
    case.state.proof["taint"] = {"private": True, "customer_original": True}
    case.parent._explicit_context_binding = {
        "private_context": False, "data_categories": ["internal"],
        "customer_identities": ["SyntheticClient"],
    }
    effective, action, _methods = start(case)
    assert case.parent._explicit_context_binding == {
        "private_context": True, "data_categories": ["customer_original", "internal"],
        "customer_identities": ["SyntheticClient"],
    }
    assert effective.sources == case.effective.sources + [
        SourceRead.model_validate(case.state.proof["read_set"][0]),
    ]
    assert action["citation_ids"] == sorted(str(cid) for cid in case.requested.citation_ids)
