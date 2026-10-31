"""Synthetic completed model/read ledger; no database, provider, or network."""

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import category_candidate as candidate
from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, execution_key
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentRun,
    AgentSession,
    AgentToolCall,
    TenantSkillEnablement,
)
from pdos_next.agent_kernel.read_execution import ReadBinding
from pdos_next.agent_kernel.registry import ToolRegistry, ToolSpec
from pdos_next.agent_kernel.research_read_ledger import page_result
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.preproject.category_creation import CategoryCreate
from pdos_next.errors import DomainError
from pdos_next.models import Principal
from pdos_next.research.types import ReadPage, Snapshot
from pdos_next.service import Context, digest


class MemorySession:
    def __init__(self):
        self.rows = {}
        self.info = {}

    def put(self, cls, row):
        self.rows[cls, row.id] = row
        return row

    def get(self, cls, identity):
        return self.rows.get((cls, identity))

    def scalar(self, query):
        if "max(" in str(query):
            return max((r.sequence for (cls, _), r in self.rows.items()
                        if cls is AgentEvent), default=0)
        cls = query.column_descriptions[0]["entity"]
        return next((r for (kind, _), r in self.rows.items() if kind is cls), None)

    def scalars(self, query):
        cls = query.column_descriptions[0]["entity"]
        rows = [r for (kind, _), r in self.rows.items() if kind is cls]
        if cls is AgentEvent:
            rows = [r for r in rows if r.body.get("type") == candidate.CANDIDATE]
        return NS(all=lambda: rows)

    def add(self, row):
        self.put(type(row), row)

    def flush(self):
        pass


@pytest.fixture
def ledger():
    s = MemorySession()
    scope = RunScope(*(uuid4() for _ in range(5)), category_id=None)
    values = asdict(scope)
    values["id"] = values.pop("run_id")
    spec = ToolSpec(
        candidate.OPERATION, "Create a candidate",
        candidate.CategoryCandidateInput.model_json_schema(),
        {}, "write", "T1", candidate.OPERATION,
    )
    registry = ToolRegistry([spec])
    catalog = SkillCatalog()
    skill = catalog._skills["category_framing"]
    loaded = SkillBinding(key=skill.key, version=skill.version, digest=skill.digest,
                          load_event_id=uuid4())
    route = NS(version="synthetic", digest="a" * 64)
    run = s.put(AgentRun, NS(
        **values, state="running", reverted_at=None, read_sources=[],
        versions={"model_version": route.version, "model_route_digest": route.digest,
                  "tool_definitions": {
                      "main": digest(registry.definitions()), "research": "b" * 64,
                  },
                  "prompt_prefixes": {"main": "c" * 64, "research": "d" * 64}},
    ))
    conversation = s.put(AgentSession, NS(
        id=run.session_id, tenant_id=run.tenant_id, owner_id=run.requester_id,
        category_id=None, product_id=None, proposal_id=None,
    ))
    for identity, kind in ((scope.requester_id, "human"), (scope.writer_id, "agent")):
        s.put(Principal, NS(id=identity, tenant_id=scope.tenant_id, kind=kind, active=True))
    enablement = s.put(TenantSkillEnablement, NS(id=uuid4(), enabled=True))
    load = s.put(AgentEvent, NS(
        id=loaded.load_event_id, tenant_id=run.tenant_id, run_id=run.id, sequence=1,
        body={"type": "skill_loaded", "key": loaded.key, "version": loaded.version,
              "digest": loaded.digest, "isolation": "main"},
    ))
    body = "Header\r\n公共证据 💡 repeat repeat\r\nUnread tail"
    snapshot = Snapshot(
        uuid4(), "https://example.test/article", "https://example.test/article", "Synthetic", "",
        datetime(2026, 10, 11, tzinfo=UTC), body, sha256(body.encode()).hexdigest(), "synthetic",
        "public_web",
    )
    artifacts = NS(snapshot=lambda bound, identity: snapshot)
    owner = NS(registry=registry, catalog=catalog, route=lambda session, bound: route,
               commands=NS(artifacts=artifacts))
    s.info = {"domain_command_owner": owner,
              "scope": (run.tenant_id, run.writer_id, run.requester_id, None)}
    read_model_binding = ModelBinding(
        model_version=route.version, model_route_digest=route.digest,
        tool_definitions_digest="b" * 64, prompt_digest="d" * 64,
        isolation="research", cancel_epoch=0,
    )
    read_args = {"url": snapshot.url, "cursor": 8}
    read_model = s.put(AgentToolCall, NS(
        id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, tool="model", state="completed",
        error_code=None, receipt_id=None,
        execution_binding=read_model_binding.model_dump(mode="json"),
        result={"calls": [{"name": "research.read", "arguments": read_args}]},
    ))
    read_binding = ReadBinding(
        read_kind="ordinary/v1", isolation="research", run_id=run.id,
        **{key: getattr(run, key) for key in (
            "tenant_id", "category_id", "session_id", "requester_id", "writer_id",
            "product_id", "proposal_id", "cancel_epoch", "private_context",
        )}, data_categories=("public",), customer_identities=(), tool="research.read",
        call_key=execution_key(run.id, read_model.id, 0),
        model_call_id=read_model.id, response_index=0,
        **{key: getattr(read_model_binding, key) for key in (
            "model_version", "model_route_digest", "tool_definitions_digest", "prompt_digest",
        )},
    )
    end = body.index("\r\n", 8)
    read = s.put(AgentToolCall, NS(
        id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, tool="research.read", state="completed",
        error_code=None, receipt_id=None, call_key=read_binding.call_key,
        input_digest=digest(["research.read", read_args]),
        execution_binding=read_binding.model_dump(mode="json"),
        result=page_result(ReadPage(snapshot, f"chars:8:{end}", body[8:end], end)),
    ))
    args = {"key": "synthetic", "name": "合成品类", "purpose": "明确范围",
            "groups": {"snapshot_refs": [{"call_id": str(read.id),
                                           "content_hash": snapshot.content_hash}],
                       "knowledge": [{"kind": "boundary", "content": {"definition": "范围"},
                                      "source_refs": [{"type": "snapshot", "id": str(snapshot.id),
                                                       "version": 1, "line": 2,
                                                       "quote": "公共证据 💡"}]}]}}
    binding = ModelBinding(
        model_version=route.version, model_route_digest=route.digest,
        tool_definitions_digest=digest(registry.definitions()), prompt_digest="c" * 64,
        isolation="main", cancel_epoch=0, loaded_skills=(loaded,),
    )
    model = s.put(AgentToolCall, NS(
        id=uuid4(), tenant_id=run.tenant_id, run_id=run.id, tool="model", state="completed",
        error_code=None, receipt_id=None, execution_binding=binding.model_dump(mode="json"),
        result={"calls": [{"name": candidate.OPERATION, "arguments": args}]},
    ))
    return NS(s=s, run=run, scope=scope, spec=spec, owner=owner, args=args, model=model,
              read=read, read_model=read_model, snapshot=snapshot, route=route,
              conversation=conversation, enablement=enablement, load=load,
              intent=execution_key(run.id, model.id, 0))


def prepare(f):
    return candidate.prepare(f.s, f.scope, f.spec, f.args, f.intent, f.owner)


def adopt(f, result):
    data = CategoryCreate.model_validate(result["payload"])
    ctx = Context(f.run.tenant_id, f.run.requester_id, f.run.requester_id)
    f.s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, None)
    return candidate.validate(f.s, ctx, data)


def test_prepare_and_human_adopt_complete_immutable_proof(ledger):
    f = ledger
    before = deepcopy(f.args)
    result = prepare(f)
    assert result["state"] == "candidate" and result["write_tier"] == "T1"
    assert result["requires_human"] and not result["payload"]["deidentified_confirmed"]
    assert prepare(f) == result
    f.run.state = "completed"
    proof = adopt(f, result)
    assert proof.run is f.run and proof.event.id == UUID(result["event_id"])
    assert proof.snapshots[0].snapshot is f.snapshot
    assert proof.snapshots[0].read_call_id == f.read.id
    assert proof.event.body["input"]["groups"]["parameters"] == []
    assert f.args == before


@pytest.mark.parametrize("field", ["tenant_id", "prepared_by_run_id", "candidate_digest",
                                    "idempotency_key", "deidentified_confirmed", "seed_key"])
def test_model_cannot_supply_server_identity_or_confirmation(ledger, field):
    with pytest.raises(ValidationError):
        candidate.CategoryCandidateInput.model_validate({**ledger.args, field: "forged"})


@pytest.mark.parametrize("change", [
    "category", "product", "proposal", "private", "customer", "source", "session_owner",
    "session_category", "human_inactive", "agent_inactive", "skill_disabled", "skill_event",
    "skill_digest", "route", "model_state", "model_error", "model_receipt", "model_run",
    "model_binding", "model_args", "schema", "tier", "intent", "epoch", "cancelled", "failed",
])
def test_preparation_rejects_forged_or_stale_execution(ledger, change):
    f = ledger
    if change in {"category", "product", "proposal"}:
        setattr(f.run, change + "_id", uuid4())
    elif change == "private":
        f.run.private_context = True
    elif change == "customer":
        f.run.customer_identities = ["private customer"]
    elif change == "source":
        f.run.read_sources = [{"id": str(uuid4())}]
    elif change == "session_owner":
        f.conversation.owner_id = uuid4()
    elif change == "session_category":
        f.conversation.category_id = uuid4()
    elif change.endswith("_inactive"):
        who = f.run.requester_id if change.startswith("human") else f.run.writer_id
        f.s.get(Principal, who).active = False
    elif change == "skill_disabled":
        f.enablement.enabled = False
    elif change == "skill_event":
        f.load.body["isolation"] = "research"
    elif change == "skill_digest":
        f.owner.catalog._skills["category_framing"] = replace(
            f.owner.catalog._skills["category_framing"], content="changed",
        )
    elif change == "route":
        f.route.digest = "f" * 64
    elif change in {"model_state", "model_error", "model_receipt", "model_run"}:
        key, value = {"model_state": ("state", "started"), "model_error": ("error_code", "error"),
                      "model_receipt": ("receipt_id", uuid4()),
                      "model_run": ("run_id", uuid4())}[change]
        setattr(f.model, key, value)
    elif change == "model_binding":
        f.model.execution_binding["forged"] = True
    elif change == "model_args":
        f.model.result = {"calls": [{"name": candidate.OPERATION, "arguments": {}}]}
    elif change == "schema":
        f.owner.registry._specs[candidate.OPERATION] = replace(f.spec, input_schema={})
    elif change == "tier":
        f.owner.registry._specs[candidate.OPERATION] = replace(f.spec, tier="T0")
    elif change == "intent":
        f.intent += "0"
    elif change == "epoch":
        f.run.cancel_epoch += 1
    else:
        f.run.state = change
    with pytest.raises(DomainError):
        prepare(f)


@pytest.mark.parametrize("change", ["state", "run", "input", "binding", "page", "extra", "hash",
                                    "snapshot", "body", "model", "locator"])
def test_snapshot_requires_actual_complete_read_and_retained_body(ledger, change):
    f = ledger
    if change == "state":
        f.read.state = "started"
    elif change == "run":
        f.read.run_id = uuid4()
    elif change == "input":
        f.read.input_digest = "f" * 64
    elif change == "binding":
        f.read.execution_binding["private_context"] = True
    elif change == "page":
        f.read.result["markdown"] += "added"
    elif change == "extra":
        f.read.result["approved"] = True
    elif change == "hash":
        f.args["groups"]["snapshot_refs"][0]["content_hash"] = "f" * 64
    elif change == "snapshot":
        f.read.result["snapshot_id"] = str(uuid4())
    elif change == "body":
        f.owner.commands.artifacts.snapshot = lambda *_: replace(f.snapshot, markdown="changed")
    elif change == "model":
        f.read_model.result["calls"][0]["arguments"]["cursor"] = 0
    else:
        f.read.result["locator"] = "chars:0:9999"
    with pytest.raises(DomainError):
        prepare(f)


@pytest.mark.parametrize("change", ["unread", "wrong_line", "no_line", "no_quote", "empty", "other",
                                    "artifact", "cross_scope", "duplicate"])
def test_knowledge_quote_must_be_in_selected_actual_page(ledger, change):
    f = ledger
    ref = f.args["groups"]["knowledge"][0]["source_refs"][0]
    if change == "unread":
        ref.update(line=3, quote="Unread tail")
    elif change == "wrong_line":
        ref["line"] = 1
    elif change == "no_line":
        del ref["line"]
    elif change == "no_quote":
        del ref["quote"]
    elif change == "empty":
        ref["quote"] = " \t "
    elif change == "other":
        ref["id"] = str(uuid4())
    elif change == "artifact":
        ref["type"] = "artifact"
    elif change == "cross_scope":
        f.read.execution_binding["category_id"] = str(uuid4())
    else:
        f.args["groups"]["snapshot_refs"] *= 2
    with pytest.raises(DomainError):
        prepare(f)


@pytest.mark.parametrize("state", ["running", "waiting_input", "completed", "partial"])
def test_human_can_adopt_active_or_successfully_finished_run(ledger, state):
    result = prepare(ledger)
    ledger.run.state = state
    assert adopt(ledger, result)


@pytest.mark.parametrize("change", ["failed", "cancelled", "reverted", "epoch", "inactive",
                                    "changed_key", "changed_name", "changed_purpose", "group",
                                    "forged_digest", "body", "source", "snapshot"])
def test_adoption_rechecks_original_input_current_authority_and_digest(ledger, change):
    f = ledger
    result = prepare(f)
    if change in {"failed", "cancelled"}:
        f.run.state = change
    elif change == "reverted":
        f.run.reverted_at = datetime.now(UTC)
    elif change == "epoch":
        f.run.cancel_epoch += 1
    elif change == "inactive":
        f.s.get(Principal, f.run.writer_id).active = False
    elif change.startswith("changed_"):
        result["payload"][change.removeprefix("changed_")] = "changed"
    elif change == "group":
        result["payload"]["groups"]["knowledge"][0]["content"]["definition"] = "edited"
    elif change == "forged_digest":
        result["payload"]["candidate_digest"] = "f" * 64
    elif change == "body":
        f.s.get(AgentEvent, UUID(result["event_id"])).body["input"]["name"] = "changed"
    elif change == "source":
        f.model.result["calls"][0]["arguments"]["purpose"] = "changed"
    else:
        f.read.result["markdown"] += "changed"
    with pytest.raises(DomainError):
        adopt(f, result)


def test_human_may_omit_groups_but_cannot_keep_dangling_snapshot_reference(ledger):
    f = ledger
    result = prepare(f)
    result["payload"]["groups"]["snapshot_refs"] = []
    with pytest.raises(DomainError):
        adopt(f, result)
    result["payload"]["groups"]["knowledge"] = []
    assert adopt(f, result).snapshots == ()


def test_named_current_human_statement_can_supply_initial_evidence(ledger):
    f = ledger
    f.args["groups"] = {"knowledge": [{
        "kind": "boundary", "content": {"definition": "scope"},
        "source_refs": [{"type": "human", "id": str(f.run.requester_id), "version": 1,
                         "statement": "Synthetic owner statement"}],
    }]}
    f.model.result["calls"][0]["arguments"] = f.args
    result = prepare(f)
    assert adopt(f, result).snapshots == ()
    f.s.get(Principal, f.run.requester_id).active = False
    with pytest.raises(DomainError):
        adopt(f, result)


def test_unsupported_fact_without_source_is_rejected_but_question_is_allowed(ledger):
    f = ledger
    f.args["groups"] = {"knowledge": [{"kind": "competitor", "content": {
        "brand": "Synthetic", "model": "X",
    }}]}
    f.model.result["calls"][0]["arguments"] = f.args
    with pytest.raises(DomainError):
        prepare(f)
    f.args["groups"] = {"knowledge": [{"kind": "research_question", "content": {
        "question": "What should be researched?",
    }}]}
    assert prepare(f)["state"] == "candidate"


def test_distinct_pages_of_same_snapshot_remain_distinct_proofs(ledger):
    f = ledger
    start = f.snapshot.markdown.index("Unread tail")
    end = len(f.snapshot.markdown)
    model = deepcopy(f.read_model)
    model.id = uuid4()
    model.result["calls"][0]["arguments"]["cursor"] = start
    f.s.put(AgentToolCall, model)
    read = deepcopy(f.read)
    read.id = uuid4()
    read.call_key = execution_key(f.run.id, model.id, 0)
    read.execution_binding.update(model_call_id=str(model.id), call_key=read.call_key)
    read.input_digest = digest([read.tool, model.result["calls"][0]["arguments"]])
    read.result = page_result(ReadPage(
        f.snapshot, f"chars:{start}:{end}", f.snapshot.markdown[start:end], None,
    ))
    f.s.put(AgentToolCall, read)
    f.args["groups"]["snapshot_refs"].append({
        "call_id": str(read.id), "content_hash": f.snapshot.content_hash,
    })
    f.args["groups"]["knowledge"][0]["source_refs"].append({
        "type": "snapshot", "id": str(f.snapshot.id), "version": 1,
        "line": 3, "quote": "Unread tail",
    })
    proof = adopt(f, prepare(f))
    assert len(proof.snapshots) == 2
    assert {p.snapshot.id for p in proof.snapshots} == {f.snapshot.id}
    assert {p.read_call_id for p in proof.snapshots} == {f.read.id, read.id}


def test_quote_occurrence_must_be_wholly_within_one_page(ledger):
    f = ledger
    ref = f.args["groups"]["knowledge"][0]["source_refs"][0]
    ref["quote"] = "repeat"
    body = f.snapshot.markdown
    start = body.rindex("repeat")
    end = start + len("repeat")
    f.read_model.result["calls"][0]["arguments"]["cursor"] = start
    f.read.input_digest = digest([f.read.tool, f.read_model.result["calls"][0]["arguments"]])
    f.read.result = page_result(ReadPage(f.snapshot, f"chars:{start}:{end}", body[start:end], end))
    assert prepare(f)
    f.read.result = page_result(ReadPage(f.snapshot, f"chars:{start}:{end - 1}",
                                        body[start:end - 1], end - 1))
    with pytest.raises(DomainError):
        prepare(f)


@pytest.mark.parametrize("group", ["knowledge", "parameters", "snapshot_refs"])
def test_partial_group_selection_is_rejected(ledger, group):
    f = ledger
    if group == "knowledge":
        f.args["groups"][group].append({"kind": "research_question", "content": {"question": "Q?"}})
    elif group == "parameters":
        f.args["groups"][group] = [
            {"key": key, "name": key, "value_type": "text", "direction": "neutral",
             "change_note": "Synthetic initial parameter"} for key in ("one", "two")
        ]
    else:
        # Even replacing the entire group with a different valid-looking reference is rejected.
        result = prepare(f)
        result["payload"]["groups"][group][0]["call_id"] = str(uuid4())
        with pytest.raises(DomainError):
            adopt(f, result)
        return
    result = prepare(f)
    result["payload"]["groups"][group] = result["payload"]["groups"][group][:1]
    with pytest.raises(DomainError):
        adopt(f, result)


@pytest.mark.parametrize("change", ["source_bool", "binding_bool", "skill_disabled", "route",
                                    "session_owner", "snapshot_digest", "extra_event"])
def test_even_resealed_event_must_match_historical_and_current_facts(ledger, change):
    f = ledger
    result = prepare(f)
    event = f.s.get(AgentEvent, UUID(result["event_id"]))
    if change == "source_bool":
        event.body["source"]["response_index"] = False
    elif change == "binding_bool":
        event.body["model_binding"]["cancel_epoch"] = False
        f.model.execution_binding["cancel_epoch"] = False
    elif change == "skill_disabled":
        f.enablement.enabled = False
    elif change == "route":
        f.route.version = "changed"
    elif change == "session_owner":
        f.conversation.owner_id = uuid4()
    elif change == "snapshot_digest":
        event.body["snapshots"][0]["snapshot_digest"] = "f" * 64
    else:
        event.body["approved"] = True
    event.body["candidate_digest"] = candidate.candidate_digest(f.run, event.body)
    result["payload"]["candidate_digest"] = event.body["candidate_digest"]
    with pytest.raises(DomainError):
        adopt(f, result)


@pytest.mark.parametrize("change", ["actor", "tenant", "category", "requester", "run", "seed"])
def test_human_adoption_context_cannot_borrow_other_identity(ledger, change):
    f = ledger
    result = prepare(f)
    data = CategoryCreate.model_validate(result["payload"])
    ctx = Context(f.run.tenant_id, f.run.requester_id, f.run.requester_id)
    if change == "seed":
        data.seed_key = "bicycle-pump"
    else:
        name = {"actor": "actor_id", "tenant": "tenant_id", "category": "category_id",
                "requester": "requester_id", "run": "agent_run_id"}[change]
        ctx = replace(ctx, **{name: uuid4()})
    f.s.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    with pytest.raises(DomainError):
        candidate.validate(f.s, ctx, data)


@pytest.mark.parametrize('whole_registry', [False, True])
def test_category_candidate_matches_actual_skill_disclosure_not_unloaded_write_tools(
    ledger, whole_registry
):
    from pdos_next.agent_kernel.disclosure import binding_operations, disclosure

    f = ledger
    f.owner.registry.add(ToolSpec('proposal.create', 'Unloaded write', {}, {}, 'write', 'T1'))
    binding = ModelBinding.model_validate(f.model.execution_binding)
    actual = disclosure(
        f.owner.registry, 'main', binding_operations(f.owner.catalog, binding.loaded_skills)
    )
    assert not any(item['name'] == 'proposal.create' for item in actual)
    fingerprint = digest(f.owner.registry.definitions() if whole_registry else actual)
    f.model.execution_binding = binding.model_copy(update={
        'tool_definitions_digest': fingerprint,
    }).model_dump(mode='json')
    f.run.versions['tool_definitions']['main'] = fingerprint
    if whole_registry:
        with pytest.raises(DomainError):
            prepare(f)
    else:
        result = prepare(f)
        assert adopt(f, result).run is f.run
