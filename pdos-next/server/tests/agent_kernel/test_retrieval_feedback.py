"""Pure provenance, private metadata and Run-before-memory locking contracts."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.agent_kernel import retrieval_feedback as feedback
from pdos_next.agent_kernel import work_state
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.process_view import KINDS
from pdos_next.enterprise_search import assistant_inheritance as inheritance
from pdos_next.enterprise_search import assistant_ledger as ledger
from pdos_next.errors import DomainError
from pdos_next.service import digest


def sample():
    run = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), requester_id=uuid4(), session_id=uuid4(), read_sources=[]
    )
    ctx = SimpleNamespace(
        tenant_id=run.tenant_id, actor_id=run.requester_id, requester_id=run.requester_id
    )
    return run, ctx


def read(run, *, tool="assistant.search", version=2, identity=None):
    call = SimpleNamespace(id=uuid4(), tool=tool, result={})
    item = {
        "source_type": "artifact",
        "source_id": str(identity or uuid4()),
        "object_id": str(uuid4()),
        "source_revision": version,
        "content_hash": "a" * 64,
        "chunk_id": str(uuid4()),
        "rank": 4,
        "title": "PRIVATE_TITLE",
        "locator": {"quote": "PRIVATE_QUOTE"},
    }
    item["citation_id"] = ledger.citation_id(run.id, call.id, item)
    call.result = {
        "items": [item],
        "ranking_version": "historical-ranking@4",
        "query_trace": {"query": "PRIVATE_QUERY"},
    }
    return call, item


def install(monkeypatch, run, calls):
    monkeypatch.setattr(feedback, "scope_for_run", lambda row: row)
    monkeypatch.setattr(ledger, "completed", lambda *_args, **_kwargs: [(row, {}) for row in calls])
    monkeypatch.setattr(
        inheritance,
        "registry",
        lambda *_args, **kwargs: (
            (
                {
                    item["citation_id"]: (str(run.id), item)
                    for call in calls
                    for item in call.result["items"]
                },
                [run],
            )
            if kwargs["include_self"]
            else pytest.fail("own root reads must be eligible")
        ),
    )
    monkeypatch.setattr(
        inheritance,
        "_aliases",
        lambda _s, _rows, roots: {
            **{cid: cid for cid in roots},
            "reissued-alias": next(iter(roots), None),
        },
    )


class Session:
    def __init__(self, run, scalars=()):
        self.run, self.scalars, self.events = run, list(scalars), []

    def get(self, model, identity):
        assert model is AgentRun and identity == self.run.id
        return self.run

    def scalar(self, _query):
        return self.scalars.pop(0)

    def add(self, event):
        self.events.append(event)

    def flush(self):
        pass


@pytest.mark.parametrize(
    "tool,origin,ranking",
    [
        ("assistant.search", "search", "historical-ranking@4"),
        ("assistant.materials.read", "materials", None),
    ],
)
def test_citation_uses_actual_root_call_and_search_only_ranking(monkeypatch, tool, origin, ranking):
    run, _ctx = sample()
    call, item = read(run, tool=tool)
    install(monkeypatch, run, [call])
    proof = feedback.provenance(Session(run), run, {"kind": "citation", "id": "reissued-alias"}, {})
    assert proof["origin"] == origin and proof["origin_call_id"] == str(call.id)
    assert proof["citation_id"] == item["citation_id"]
    assert proof["source"]["object_id"] == item["object_id"]
    assert proof["candidate"]["ranking_version"] == ranking
    assert proof["candidate"]["rank"] == (4 if tool == "assistant.search" else None)
    assert all(
        secret not in str(proof) for secret in ("PRIVATE_QUERY", "PRIVATE_TITLE", "PRIVATE_QUOTE")
    )


def test_unknown_or_changed_citation_never_becomes_a_fabricated_candidate(monkeypatch):
    run, _ctx = sample()
    call, _item = read(run)
    install(monkeypatch, run, [call])
    with pytest.raises(DomainError):
        feedback.provenance(Session(run), run, {"kind": "citation", "id": str(uuid4())}, {})
    call.result["items"][0]["source_revision"] += 1
    with pytest.raises(DomainError):
        feedback.provenance(Session(run), run, {"kind": "citation", "id": "reissued-alias"}, {})


def bound_body(run, identity, version=2):
    run.read_sources = [{"artifact_id": identity, "expected_revision": version}]
    return {
        "focus_objects": [
            {"kind": "artifact", "id": identity, "version": version, "run_id": str(run.id)}
        ]
    }


def test_bound_unsearched_material_has_no_call_candidate_or_ranking(monkeypatch):
    run, _ctx = sample()
    identity = str(uuid4())
    body = bound_body(run, identity)
    install(monkeypatch, run, [])
    proof = feedback.provenance(Session(run), run, {"kind": "artifact", "id": identity}, body)
    assert proof["origin"] == "bound_source" and proof["origin_call_id"] is None
    assert proof["citation_id"] is None
    assert proof["candidate"] == {"chunk_id": None, "rank": None, "ranking_version": None}
    assert proof["source"]["source_revision"] == 2


def test_artifact_uses_last_matching_actual_read_without_replacing_its_fixed_version(monkeypatch):
    run, _ctx = sample()
    identity = str(uuid4())
    body = bound_body(run, identity)
    earlier, _ = read(run, identity=identity)
    materials, item = read(run, tool="assistant.materials.read", identity=identity)
    newer, _ = read(run, identity=identity, version=3)
    install(monkeypatch, run, [earlier, materials, newer])
    proof = feedback.provenance(Session(run), run, {"kind": "artifact", "id": identity}, body)
    assert proof["origin"] == "materials" and proof["citation_id"] == item["citation_id"]
    assert proof["source"]["source_revision"] == 2
    assert proof["candidate"]["ranking_version"] is None
    run.read_sources[0]["expected_revision"] = 3
    with pytest.raises(DomainError):
        feedback.provenance(Session(run), run, {"kind": "artifact", "id": identity}, body)


def test_missing_old_search_rank_is_unknown_and_never_filled_from_current_policy(monkeypatch):
    run, _ctx = sample()
    call, item = read(run)
    call.result.pop("ranking_version")
    item.pop("rank")
    item["citation_id"] = ledger.citation_id(run.id, call.id, item)
    install(monkeypatch, run, [call])
    proof = feedback.provenance(
        Session(run), run, {"kind": "citation", "id": item["citation_id"]}, {}
    )
    assert proof["candidate"]["rank"] is None
    assert proof["candidate"]["ranking_version"] is None


def state(run, identity):
    return SimpleNamespace(
        id=uuid4(),
        origin="human",
        session_id=run.session_id,
        owner_id=run.requester_id,
        request_key=uuid4(),
        request_sha256="b" * 64,
        revision=2,
        body={"exclusions": [{"id": identity, "kind": "artifact", "reason": "PRIVATE_REASON"}]},
    )


def test_event_contains_only_metadata_and_does_not_change_run_or_activity_truth(monkeypatch):
    run, ctx = sample()
    identity = str(uuid4())
    row = state(run, identity)
    proof = {"origin": "bound_source", "candidate": {"ranking_version": None}}
    checked = []
    monkeypatch.setattr(feedback, "owner", lambda *args: checked.append(args))
    monkeypatch.setattr(feedback, "provenance", lambda *_args: proof)
    session = Session(run, [None, 12])
    before = deepcopy(vars(run))
    event_id = feedback.record(session, ctx, run, row, identity)
    assert checked and len(session.events) == 1
    event = session.events[0]
    assert event.id == event_id and event.sequence == 13 and event.run_id == run.id
    assert event.body["action"] == "not_relevant" and event.body["recorded_by"] == str(ctx.actor_id)
    assert event.body["request_key"] == str(row.request_key)
    assert event.body["work_state_id"] == str(row.id)
    assert "PRIVATE_REASON" not in str(event.body)
    assert vars(run) == before and feedback.KIND not in KINDS


def test_helper_replay_never_rereads_sources_or_generates_another_sequence(monkeypatch):
    run, ctx = sample()
    identity = str(uuid4())
    row = state(run, identity)
    previous = SimpleNamespace(
        id=uuid4(), body={"request_digest": row.request_sha256, "work_state_id": str(row.id)}
    )
    monkeypatch.setattr(feedback, "owner", lambda *_args: None)
    monkeypatch.setattr(
        feedback, "provenance", lambda *_args: pytest.fail("No provenance on replay")
    )
    session = Session(run, [previous])
    assert feedback.record(session, ctx, run, row, identity) == previous.id
    assert not session.events
    previous.body["work_state_id"] = str(uuid4())
    with pytest.raises(DomainError) as caught:
        feedback.record(Session(run, [previous]), ctx, run, row, identity)
    assert caught.value.code == "DUPLICATE_INTENT_CONFLICT"


def test_feedback_keeps_the_same_human_owner_check_as_run_feedback(monkeypatch):
    run, ctx = sample()
    row = state(run, str(uuid4()))

    def denied(*_args):
        raise DomainError("FORBIDDEN_SCOPE", "human only")

    monkeypatch.setattr(feedback, "owner", denied)
    with pytest.raises(DomainError):
        feedback.record(Session(run), ctx, run, row, row.body["exclusions"][0]["id"])


def change_fixture(monkeypatch, *, changed_goal=False, replay=False, action="exclude_source"):
    run, ctx = sample()
    identity = str(uuid4())
    data = work_state.ChangeInput(
        expected_revision=1, request_key=uuid4(), action=action, item_id=identity
    )
    body = {
        "current_goal": {"run_id": str(run.id)},
        "constraints": [{"id": identity}],
        "focus_objects": [{"kind": "artifact", "id": identity, "version": 2}],
        "exclusions": [],
        "removed_constraints": [],
        "citations": [],
    }
    before = SimpleNamespace(body=deepcopy(body), revision=1)
    current = SimpleNamespace(body=deepcopy(body), revision=1)
    if changed_goal:
        current.body["current_goal"]["run_id"] = str(uuid4())
    order = []
    values = iter([before, current] if action == "exclude_source" else [current])
    monkeypatch.setattr(work_state, "latest", lambda *_args: next(values))
    monkeypatch.setattr(work_state, "_human", lambda *_args: None)
    monkeypatch.setattr(work_state, "_target", lambda *_args: None)
    monkeypatch.setattr(work_state, "_lock", lambda *_args: order.append("advisory"))
    monkeypatch.setattr(work_state, "_project", lambda _s, _ctx, row: row.body)

    def append(_s, _run, updated, **_kwargs):
        order.append("work_state")
        return SimpleNamespace(body=updated, id=uuid4())

    monkeypatch.setattr(work_state, "_append", append)
    monkeypatch.setattr(feedback, "record", lambda *_args: order.append("feedback"))

    class ChangeSession:
        def scalar(self, query):
            if query.column_descriptions[0]["entity"] is AgentRun:
                assert query._for_update_arg is not None
                order.append("run_lock")
                return run
            if replay:
                return SimpleNamespace(
                    body=body,
                    request_sha256=digest(
                        data.model_dump(mode="json", exclude={"request_key"}, exclude_none=True)
                    ),
                )
            return None

        def get(self, model, _identity):
            assert model is AgentRun
            return run

    return ChangeSession(), run, ctx, data, order


def test_work_state_exclusion_locks_run_before_advisory_and_appends_atomically(monkeypatch):
    session, run, ctx, data, order = change_fixture(monkeypatch)
    result = work_state.change(session, ctx, run.session_id, data)
    assert result["exclusions"][0]["id"] == str(data.item_id)
    assert order == ["run_lock", "advisory", "work_state", "feedback"]


def test_goal_swap_after_run_lock_returns_conflict_without_locking_second_run(monkeypatch):
    session, run, ctx, data, order = change_fixture(monkeypatch, changed_goal=True)
    with pytest.raises(DomainError) as caught:
        work_state.change(session, ctx, run.session_id, data)
    assert caught.value.code == "VERSION_CONFLICT" and order == ["run_lock", "advisory"]


def test_work_state_key_replay_returns_without_appending_feedback(monkeypatch):
    session, run, ctx, data, order = change_fixture(monkeypatch, replay=True)
    work_state.change(session, ctx, run.session_id, data)
    assert order == ["run_lock", "advisory"]


def test_other_work_state_changes_keep_their_original_no_event_path(monkeypatch):
    session, run, ctx, data, order = change_fixture(monkeypatch, action="remove_constraint")
    work_state.change(session, ctx, run.session_id, data)
    assert order == ["advisory", "work_state"]


def test_existing_exclusion_input_cannot_supply_ranking_candidate_or_source_facts():
    from pydantic import ValidationError

    original = {
        "expected_revision": 1,
        "request_key": uuid4(),
        "action": "exclude_source",
        "item_id": uuid4(),
    }
    for field, value in (
        ("ranking_version", "client-invented"),
        ("source_id", str(uuid4())),
        ("origin_call_id", str(uuid4())),
    ):
        with pytest.raises(ValidationError):
            work_state.ChangeInput(**original, **{field: value})
