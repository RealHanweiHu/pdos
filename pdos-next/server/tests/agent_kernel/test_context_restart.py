"""Closed state provenance and verbatim proofs, without provider or database calls."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.context_restart import KEY, carried_body, origin_ids, validate_body
from pdos_next.agent_kernel.work_state import empty, validate_constraints
from pdos_next.errors import DomainError
from pdos_next.service import digest


def state():
    identity = str(uuid4())
    goal = "只看D16，保留压力单位未知。"
    body = empty()
    body["root_goal"] = body["current_goal"] = {"run_id": identity, "text": goal}
    body["constraints"], _ = validate_constraints(
        [{"run_id": identity, "text": "只看D16"}], {identity: goal}, set(),
    )
    body["removed_constraints"] = [str(uuid4())]
    body["exclusions"] = [{"id": str(uuid4()), "kind": "artifact", "reason": "不相关"}]
    body["context_selection"] = {"version_mode": "current"}
    return identity, goal, body


def test_server_copy_preserves_verbatim_origin_tombstones_exclusions_and_corrections():
    identity, goal, body = state()
    copied = validate_body(body, {identity: goal})
    assert copied == body and copied is not body
    copied["constraints"].clear()
    assert body["constraints"] and copied["removed_constraints"] == body["removed_constraints"]


@pytest.mark.parametrize("fault", ["paraphrase", "wrong_origin", "removed", "false_goal"])
def test_state_with_unproved_or_deleted_human_claims_is_not_carried(fault):
    identity, goal, body = state()
    if fault == "paraphrase":
        body["constraints"][0]["text"] = "压力单位已确认"
    elif fault == "wrong_origin":
        body["constraints"][0]["run_id"] = str(uuid4())
    elif fault == "removed":
        body["removed_constraints"].append(body["constraints"][0]["id"])
    else:
        body["root_goal"] = {"run_id": identity, "text": "伪造目标"}
    with pytest.raises(DomainError, match="原工作"):
        validate_body(body, {identity: goal})


def provenance():
    identity, _goal, body = state()
    source = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), owner_id=uuid4(), session_id=uuid4(),
                             revision=3, body=body)
    proof = {"version": 1, "source_run_id": identity,
             "source_session_id": str(source.session_id), "source_state_id": str(source.id),
             "source_revision": source.revision, "source_sha256": digest(body),
             "origin_run_ids": sorted(origin_ids(body))}
    root = SimpleNamespace(id=uuid4(), session_id=uuid4(), tenant_id=source.tenant_id,
                           requester_id=source.owner_id, continued_from_id=None,
                           versions={KEY: proof})
    return root, source


def test_old_state_access_is_bound_to_an_immutable_exact_server_revision():
    root, source = provenance()
    session = SimpleNamespace(get=lambda *_: source)
    assert carried_body(session, root) == source.body
    source.body = deepcopy(source.body)
    source.body["exclusions"] = []
    with pytest.raises(DomainError, match="原始版本"):
        carried_body(session, root)


def test_reusing_session_id_alone_does_not_authorize_old_state_references():
    root, _source = provenance()
    root.versions = {}
    assert carried_body(SimpleNamespace(), root) == {}


@pytest.mark.parametrize("fault", ["owner", "tenant", "same_session", "origin", "revision"])
def test_provenance_cannot_import_another_owner_scope_or_state_version(fault):
    root, source = provenance()
    if fault == "owner":
        source.owner_id = uuid4()
    elif fault == "tenant":
        source.tenant_id = uuid4()
    elif fault == "same_session":
        source.session_id = root.session_id
    elif fault == "origin":
        root.versions[KEY]["origin_run_ids"].append(str(uuid4()))
    else:
        source.revision += 1
    with pytest.raises(DomainError):
        carried_body(SimpleNamespace(get=lambda *_: source), root)


@pytest.mark.parametrize("proven", [False, True])
def test_history_manifest_only_resolves_cross_session_citations_from_exact_restart_proof(
    monkeypatch, proven,
):
    from pdos_next.agent_kernel import context_restart, conversation_acl
    from tests.agent_kernel.test_conversation_acl import batch_session, native_ledger

    consumer, _calls = native_ledger()
    origin, cid, source = str(uuid4()), str(uuid4()), str(uuid4())
    preview = {"origin_run_id": origin, "origin_citation_id": cid,
               "citation_id": str(uuid4()), "source_type": "artifact"}
    exact = {"source_type": "artifact", "source_id": source, "citation_id": cid}
    frozen = [{"id": consumer.id, "proposal_refs": [], "citations": [preview]}]
    session = batch_session([], [consumer], frozen=frozen)
    session.get = lambda *_: consumer
    monkeypatch.setattr(context_restart, "citation_roots",
                        lambda *_: {cid: (origin, exact)} if proven else {})
    monkeypatch.setattr(conversation_acl, "metadata", lambda *_: {})
    value = conversation_acl.manifests(session, [consumer])[str(consumer.id)]
    assert (exact in value["citations"]) is proven
    assert bool(value.get("unavailable")) is not proven


@pytest.mark.parametrize("status,revision,expected", [
    ("active", 1, "current"), ("active", 2, "updated"), ("withdrawn", 1, "hidden"),
])
def test_unquoted_read_dependency_is_rechecked_without_body_and_updates_remain_usable(
    monkeypatch, status, revision, expected,
):
    from pdos_next.agent_kernel import conversation_acl
    from pdos_next.agent_kernel.context_restart import access_state

    source, origin = str(uuid4()), str(uuid4())
    access = {origin: {"run_id": origin, "dependencies": [
        conversation_acl.dependency("artifact", source, 1)], "citations": []}}
    monkeypatch.setattr(conversation_acl, "metadata", lambda *_: {
        ("artifact", source): [{"status": status, "revision": revision}],
    })
    assert access_state(None, None, access) == expected


def test_full_read_acl_is_server_only_in_public_and_frozen_model_projection(monkeypatch):
    from pdos_next.agent_kernel import context_restart, work_state

    identity, session_id = uuid4(), uuid4()
    body = empty()
    body["current_goal"] = {"run_id": str(identity), "text": "继续核对"}
    body["_restart_access"] = {"SERVER_ONLY_ORIGIN": {"dependencies": ["SERVER_ONLY_SOURCE"]}}
    row = SimpleNamespace(body=body, revision=1, session_id=session_id)
    run = SimpleNamespace(id=identity, session_id=session_id, versions={}, goal="继续核对",
                          continued_from_id=None, project_id=None, proposal_id=None,
                          category_id=None)
    monkeypatch.setattr(context_restart, "access_state", lambda *_: "current")
    monkeypatch.setattr(work_state, "latest", lambda *_: row)
    monkeypatch.setattr(work_state, "_covered", lambda *_: True)
    public = work_state._project(None, SimpleNamespace(), row, current_run=run)
    model = work_state.frozen(None, run, SimpleNamespace())
    for value in (public, model):
        assert "_restart_access" not in value and "SERVER_ONLY_SOURCE" not in str(value)
    assert run.versions["work_state_access"] == body["_restart_access"]
