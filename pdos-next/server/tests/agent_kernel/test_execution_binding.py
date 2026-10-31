"""Pure synthetic ledger/graph checks; no provider, PostgreSQL or qualification grant."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pdos_agent_runtime.graph import registered_graph_context

from pdos_next.agent_kernel.disclosure import binding_operations, disclosure, skill_operations
from pdos_next.agent_kernel.bindings import ModelBinding, SkillBinding, WriteSource, execution_key
from pdos_next.agent_kernel.execution import (
    finish_domain_call,
    prepare_domain_call,
    recover_domain_call,
    validate_model_source,
    validate_skill_load,
)
from pdos_next.agent_kernel.gateway import AgentGateway
from pdos_next.agent_kernel.graph import AgentKernel
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall, TenantSkillEnablement
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.tools import default_registry
from pdos_next.agent_kernel.types import ModelTurn, ToolCall
from pdos_next.errors import DomainError
from pdos_next.models import Receipt, now
from pdos_next.providers.agent_client import AgentProviderClient, tool_name
from pdos_next.service import digest
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_graph import Host, final, scope


class WriterHost(Host):
    def qualified(self, *_):
        return True  # Only this synthetic port; does not create real qualification records.

    def write(self, bound, spec, arguments, intent, *, source):
        self.writes.append((bound, spec, arguments, intent, source))
        return {"id": str(uuid4())}

    def receipt(self, _, result):
        return result


def patch_turn(*, identity="native", ledger=True):
    return ModelTurn(
        calls=(ToolCall(id=identity, name="proposal.item.patch", arguments={"text": "draft"}),),
        ledger_call_id=uuid4() if ledger else None,
    )


def test_selected_skill_and_response_index_use_server_model_identity():
    turn = patch_turn(identity=str(uuid4()))
    host = WriterHost([turn, final()])
    kernel = AgentKernel(host, default_registry())
    first = kernel.catalog._skills["proposal_drafting"]
    kernel.catalog._skills["another"] = replace(first, key="another", version="another@1")
    actual = scope()
    kernel.execute(actual, goal="synthetic", preload=["proposal_drafting", "another"])
    assert len(host.writes) == 1
    _, _, _, key, source = host.writes[0]
    assert source.skill.key == first.key and source.skill.digest == first.digest
    assert source.model_call_id == turn.ledger_call_id and source.response_index == 0
    assert key == execution_key(actual.run_id, turn.ledger_call_id, 0)
    assert turn.calls[0].id not in key
    assert source.skill.load_event_id is not None


def test_loading_skill_in_same_reply_does_not_authorize_that_output():
    first = ModelTurn(calls=(
        ToolCall(id="load", name="skill.load", arguments={"name": "proposal_drafting"}),
        patch_turn().calls[0],
    ), ledger_call_id=uuid4())
    later = patch_turn()
    host = WriterHost([first, later, final()])
    AgentKernel(host, default_registry()).execute(scope(), goal="synthetic")
    assert len(host.prepared) == 1 and len(host.writes) == 1
    assert host.writes[0][-1].model_call_id == later.ledger_call_id


def test_missing_actual_model_ledger_cannot_execute_t0():
    host = WriterHost([patch_turn(ledger=False), final()])
    state = AgentKernel(host, default_registry()).execute(
        scope(), goal="synthetic", preload=["proposal_drafting"]
    )
    assert not host.writes
    assert state["tool_results"][0]["value"]["error"]["code"] == "SOURCE_UNAVAILABLE"


def test_generic_store_cannot_claim_t0_in_its_separate_transaction():
    with pytest.raises(DomainError) as error:
        KernelStore(None).claim(
            scope(), "synthetic", "proposal.item.patch", {},
            execution_binding={"kind": "domain_t0"},
        )
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("method", ["settle", "reconcile"])
def test_generic_store_cannot_finish_or_reconcile_domain_call(method):
    f = ledger()
    call, _ = prepare(f)
    store = KernelStore(None)

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield f.session, f.run

    store.transaction = transaction
    with pytest.raises(DomainError):
        if method == "settle":
            store.settle(f.scope, call.id, result={"fake": "completed"})
        else:
            store.reconcile(
                f.scope, call.id, receipt_lookup=lambda *_: pytest.fail("No domain lookup here")
            )
    assert call.state == "started" and call.receipt_id is None


def test_duplicate_protocol_ids_are_rejected_before_any_tool_dispatch():
    native = patch_turn().calls[0]
    host = WriterHost([ModelTurn(calls=(native, native), ledger_call_id=uuid4())])
    with pytest.raises(DomainError) as error:
        AgentKernel(host, default_registry()).execute(
            scope(), goal="synthetic", preload=["proposal_drafting"]
        )
    assert error.value.code == "VALIDATION_FAILED" and not host.writes


@pytest.mark.parametrize("change", ["version", "content", "operations"])
def test_checkpoint_restore_rejects_skill_drift_before_another_model_turn(change):
    question = ModelTurn(structured={
        "status": "needs_input", "summary": "synthetic", "result": {}, "unfinished": [],
        "questions": [{"id": "q", "question": "Region?", "why": "scope", "options": []}],
    })
    saver, actual = InMemorySaver(), scope()
    kernel = AgentKernel(Host([question]), default_registry())
    assert kernel.execute(actual, goal="synthetic", preload=["proposal_drafting"],
                          checkpointer=saver)["__interrupt__"]
    host = WriterHost([patch_turn(), final()])
    changed = SkillCatalog()
    old = changed._skills["proposal_drafting"]
    value = {"version": "different", "content": "changed", "operations": frozenset()}
    changed._skills[old.key] = replace(old, **{change: value[change]})
    with pytest.raises(DomainError) as error:
        AgentKernel(host, default_registry(), catalog=changed).execute(
            actual, answer={"q": "US"}, checkpointer=saver
        )
    assert error.value.code == "VERSION_CONFLICT" and not host.prefixes and not host.writes


from pdos_next.agent_kernel.models import TenantPilotAdmission
from pdos_next.agent_kernel.qualification_binding import model_identity, tool_identity


class LedgerSession:
    """In-memory Session port double; deliberately provides no commit/transaction API."""
    def __init__(self, actual, run, model, event, qualification):
        self.info = {"scope": (
            actual.tenant_id, actual.writer_id, actual.requester_id, actual.category_id,
        )}
        self.rows = {(type(r), r.id): r for r in (run, model, event, qualification)}
        self.domain = None
        self.flushes = 0

    def get(self, model, identity):
        if model is TenantPilotAdmission:
            return SimpleNamespace(active=True)
        return self.rows.get((model, identity))

    def scalar(self, query, params=None):
        if str(query).startswith("SELECT kernel_pilot_active"):
            return True
        entity = query.column_descriptions[0]["entity"]
        if entity is AgentToolCall:
            return self.domain
        return next((r for (m, _), r in self.rows.items() if m is entity), None)

    def add(self, row):
        self.rows[type(row), row.id] = row
        if isinstance(row, AgentToolCall):
            self.domain = row

    def flush(self):
        self.flushes += 1
        if self.domain and self.domain.state is None:
            self.domain.state = "started"  # SQLAlchemy defaults normally apply on real flush.


def ledger():
    actual, registry, catalog = scope(), default_registry(), SkillCatalog()
    skill = catalog._skills["proposal_drafting"]
    bound = SkillBinding(key=skill.key, version=skill.version, digest=skill.digest,
                         load_event_id=uuid4())
    route = SimpleNamespace(version="synthetic@1", digest=digest("synthetic route"), protocol="openai-compatible", base_url="https://synthetic.invalid/v1", model="synthetic-model")
    spec, arguments = registry.get("proposal.item.patch"), {"text": "draft"}
    model_binding = ModelBinding(
        model_version=route.version, model_route_digest=route.digest,
        # The call discloses what its loaded skill allows, not the whole registry.
        tool_definitions_digest=digest(
            disclosure(registry, "main", skill_operations([skill]))
        ), prompt_digest=digest("prefix"),
        isolation="main", cancel_epoch=actual.cancel_epoch, loaded_skills=(bound,),
    )
    row = AgentRun(
        id=actual.run_id, tenant_id=actual.tenant_id, category_id=actual.category_id,
        product_id=actual.product_id, proposal_id=actual.proposal_id, session_id=actual.session_id,
        writer_id=actual.writer_id, requester_id=actual.requester_id,
        private_context=actual.private_context, data_categories=list(actual.data_categories),
        customer_identities=list(actual.customer_identities), state="running", cancel_epoch=0,
        versions={"model_version": route.version, "model_route_digest": route.digest,
                  "tool_definitions": {"main": model_binding.tool_definitions_digest},
                  "prompt_prefixes": {"main": model_binding.prompt_digest}},
    )
    model = AgentToolCall(
        id=uuid4(), tenant_id=actual.tenant_id, run_id=actual.run_id, tool="model",
        state="completed", execution_binding=model_binding.model_dump(mode="json"),
        result={"calls": [{"id": "untrusted-native", "name": spec.name, "arguments": arguments}]},
    )
    event = AgentEvent(id=bound.load_event_id, tenant_id=actual.tenant_id, run_id=actual.run_id,
                       sequence=1, body={"type": "skill_loaded", "key": bound.key,
                                         "version": bound.version, "digest": bound.digest,
                                         "isolation": "main"})
    qualification = TenantSkillEnablement(
        id=uuid4(), tenant_id=actual.tenant_id, skill_key=skill.key, enabled=True, pilot=True,
        qualification_revoked=False, qualified_skill_version=skill.version,
        qualified_model_version=route.version, qualified_skill_digest=skill.digest,
        qualified_tool_digest=tool_identity(skill, registry), qualified_model_digest=model_identity(route), quality_paused=False,
        review_case_refs=[str(uuid4()) for _ in range(10)],
        reviewed_by=actual.requester_id, reviewed_at=now(),
    )
    f = SimpleNamespace(
        scope=actual, registry=registry, catalog=catalog, spec=spec, arguments=arguments,
        run=row, model=model, event=event, qualification=qualification, route=route,
        source=WriteSource(skill=bound, model_call_id=model.id, response_index=0),
        session=LedgerSession(actual, row, model, event, qualification),
        reads=[], read_allowed=True,
    )

    def read_receipt(session, bound_scope, receipt):
        assert session is f.session and bound_scope == f.scope
        f.reads.append(receipt.id)
        if not f.read_allowed:
            raise DomainError("FORBIDDEN_SCOPE", "原回执当前不可读。")

    f.read_receipt = read_receipt
    return f


@pytest.mark.parametrize("change,category", [
    ("run_id", "FORBIDDEN_SCOPE"), ("tenant_id", "FORBIDDEN_SCOPE"),
    ("state", "FORBIDDEN_SCOPE"), ("result_index", "FORBIDDEN_SCOPE"),
    ("arguments", "DUPLICATE_INTENT_CONFLICT"), ("skill", "FORBIDDEN_SCOPE"),
    ("model_version", "VERSION_CONFLICT"), ("route_digest", "VERSION_CONFLICT"),
    ("epoch", "CANCELLED_RUN"), ("reverted", "CANCELLED_RUN"),
])
def test_actual_model_source_rejects_scope_index_version_and_epoch_changes(change, category):
    f = ledger()
    if change in {"run_id", "tenant_id"}:
        setattr(f.model, change, uuid4())
    elif change == "state":
        f.model.state = "started"
    elif change == "result_index":
        f.source = f.source.model_copy(update={"response_index": 1})
    elif change == "arguments":
        f.arguments = {"text": "other"}
    elif change == "skill":
        f.source = f.source.model_copy(update={
            "skill": f.source.skill.model_copy(update={"load_event_id": uuid4()}),
        })
    elif change == "model_version":
        f.route.version = "other"
    elif change == "route_digest":
        f.route.digest = digest("other")
    elif change == "epoch":
        f.run.cancel_epoch += 1
    else:
        f.run.reverted_at = now()
    with pytest.raises(DomainError) as error:
        validate_model_source(f.run, f.model, f.scope, f.source, f.spec, f.arguments, route=f.route)
    assert error.value.code == category


def prepare(f, **changes):
    values = dict(catalog=f.catalog, registry=f.registry, route=f.route,
                  command_digest=digest("synthetic command"), read_receipt=f.read_receipt)
    values.update(changes)
    return prepare_domain_call(f.session, f.scope, f.spec, f.arguments, f.source, **values)


def add_receipt(f, call, **changes):
    values = dict(
        id=uuid4(), tenant_id=f.scope.tenant_id, category_id=f.scope.category_id,
        product_id=f.scope.product_id, actor_id=f.scope.writer_id,
        requester_id=f.scope.requester_id, agent_run_id=f.scope.run_id, run_id=None,
        operation=f.spec.operation_key, request_digest=call.execution_binding["command_digest"],
        subject_type="synthetic", subject_id=uuid4(), subject_revision=1,
        result={"status": "draft"}, created_at=now(),
    )
    values.update(changes)
    row = Receipt(**values)
    f.session.add(row)
    return row


def test_in_session_call_completion_and_replay_keep_actual_receipt_and_single_call():
    f = ledger()
    call, previous = prepare(f)
    assert previous is None and call.execution_binding["skill"]["digest"] == f.source.skill.digest
    receipt = add_receipt(f, call)
    result = finish_domain_call(f.session, f.scope, call.id, receipt.id)
    same, previous = prepare(f)
    assert same is call and previous == result and call.state == "completed"
    assert result["agent_call_id"] == str(call.id) and call.receipt_id == receipt.id
    assert not hasattr(f.session, "commit")  # Helpers do not own the domain transaction.


@pytest.mark.parametrize("run_state", ["running", "completed", "partial", "failed"])
def test_completed_result_recovery_needs_read_authority_not_new_write_qualification(run_state):
    f = ledger()
    call, _ = prepare(f)
    receipt = add_receipt(f, call)
    result = finish_domain_call(f.session, f.scope, call.id, receipt.id)
    f.qualification.qualification_revoked = True
    f.qualification.enabled = False
    f.run.state = run_state
    before = f.session.flushes

    def new_write_route(*_):
        raise AssertionError("Completed recovery must not access current model routing.")

    same, previous = prepare(f, catalog=None, registry=None, route=new_write_route)
    assert same is call and previous == result and f.reads == [receipt.id]
    assert f.session.flushes == before
    assert call.state == "completed" and call.result == result and call.receipt_id == receipt.id


@pytest.mark.parametrize("read_callback", ["missing", "denied"])
def test_completed_result_recovery_fails_without_current_read_authority(read_callback):
    f = ledger()
    call, _ = prepare(f)
    receipt = add_receipt(f, call)
    finish_domain_call(f.session, f.scope, call.id, receipt.id)
    f.read_allowed = False
    with pytest.raises(DomainError) as error:
        prepare(f, read_receipt=None if read_callback == "missing" else f.read_receipt)
    assert error.value.code == (
        "SOURCE_UNAVAILABLE" if read_callback == "missing" else "FORBIDDEN_SCOPE"
    )
    assert call.state == "completed" and call.receipt_id == receipt.id


def test_recovery_port_has_no_new_write_dependencies_or_ledger_mutation():
    f = ledger()
    values = dict(command_digest=digest("synthetic command"), read_receipt=f.read_receipt)
    assert recover_domain_call(f.session, f.scope, f.spec, f.arguments, f.source, **values) is None
    assert f.session.domain is None and not f.reads
    call, _ = prepare(f)
    receipt = add_receipt(f, call)
    result = finish_domain_call(f.session, f.scope, call.id, receipt.id)
    f.qualification.qualification_revoked = True
    before = f.session.flushes
    same, previous = recover_domain_call(
        f.session, f.scope, f.spec, f.arguments, f.source, **values
    )
    assert same is call and previous == result and f.session.flushes == before


@pytest.mark.parametrize("change", ["arguments", "command_digest", "epoch", "reverted"])
def test_completed_recovery_rejects_new_intents_and_cancelled_or_reverted_runs(change):
    f = ledger()
    call, _ = prepare(f)
    receipt = add_receipt(f, call)
    finish_domain_call(f.session, f.scope, call.id, receipt.id)
    changes = {}
    if change == "arguments":
        f.arguments = {"text": "new intent"}
    elif change == "command_digest":
        changes[change] = digest("other command")
    elif change == "epoch":
        f.run.cancel_epoch += 1
    else:
        f.run.reverted_at = now()
    with pytest.raises(DomainError) as error:
        prepare(f, **changes)
    assert error.value.code == (
        "DUPLICATE_INTENT_CONFLICT" if change in {"arguments", "command_digest"}
        else "CANCELLED_RUN"
    )
    assert call.state == "completed" and call.receipt_id == receipt.id


@pytest.mark.parametrize("change", ["qualification", "loaded_event", "wrong_session"])
def test_prepare_refuses_revoked_qualification_unbound_load_and_borrowed_session(change):
    f = ledger()
    if change == "qualification":
        f.qualification.qualification_revoked = True
    elif change == "loaded_event":
        f.event.run_id = uuid4()
    else:
        f.session.info["scope"] = (f.scope.tenant_id, uuid4(), uuid4(), f.scope.category_id)
    with pytest.raises(DomainError):
        prepare(f)
    assert f.session.domain is None


@pytest.mark.parametrize("field", ["agent_run_id", "category_id", "actor_id", "request_digest"])
def test_other_receipt_cannot_be_reparented_or_complete_call(field):
    f = ledger()
    call, _ = prepare(f)
    different = digest("other") if field == "request_digest" else uuid4()
    receipt = add_receipt(f, call, **{field: different})
    with pytest.raises(DomainError):
        finish_domain_call(f.session, f.scope, call.id, receipt.id)
    assert call.state == "started" and call.receipt_id is None


def test_prepared_call_cannot_change_payload_or_command_on_replay():
    f = ledger()
    call, _ = prepare(f)
    saved = deepcopy(call.execution_binding)
    with pytest.raises(DomainError) as error:
        prepare(f, command_digest=digest("different command"))
    assert error.value.code == "DUPLICATE_INTENT_CONFLICT"
    assert call.execution_binding == saved


def test_actual_route_is_rechecked_through_the_same_domain_session_callback():
    f = ledger()
    sessions = []

    def rotated(session, actual):
        sessions.append(session)
        assert actual == f.scope
        return SimpleNamespace(version="changed", digest=f.route.digest)

    with pytest.raises(DomainError) as error:
        prepare(f, route=rotated)
    assert error.value.code == "VERSION_CONFLICT"
    assert sessions == [f.session] and f.session.domain is None


def test_loading_event_binding_is_actual_immutable_event_not_latest_name():
    f = ledger()
    validate_skill_load(f.session, f.scope, f.source.skill)
    f.event.body = {**f.event.body, "version": "changed"}
    with pytest.raises(DomainError) as error:
        validate_skill_load(f.session, f.scope, f.source.skill)
    assert error.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("change", ["epoch", "reverted"])
def test_cancellation_or_revert_after_prepare_cannot_finish_call(change):
    f = ledger()
    call, _ = prepare(f)
    receipt = add_receipt(f, call)
    if change == "epoch":
        f.run.cancel_epoch += 1
    else:
        f.run.reverted_at = now()
    with pytest.raises(DomainError) as error:
        finish_domain_call(f.session, f.scope, call.id, receipt.id)
    assert error.value.code == "CANCELLED_RUN"
    assert call.state == "started" and call.receipt_id is None


@pytest.mark.parametrize("attribute", ["tenant_id", "run_id"])
def test_skill_load_event_from_another_scope_is_not_a_loading_fact(attribute):
    f = ledger()
    setattr(f.event, attribute, uuid4())
    with pytest.raises(DomainError) as error:
        validate_skill_load(f.session, f.scope, f.source.skill)
    assert error.value.code == "FORBIDDEN_SCOPE"


class GatewayStore:
    """Pure ledger port double: no database, real HTTP or model credentials."""
    def __init__(self, f):
        self.f = f
        self.calls = {}

    def current(self, actual):
        assert actual == self.f.scope

    @contextmanager
    def transaction(self, actual, **_):
        self.current(actual)
        yield self.f.session, self.f.run

    def emit(self, *_):
        return uuid4()

    def claim(self, actual, key, tool, payload, **options):
        assert actual == self.f.scope and tool == "model"
        call = self.calls.get(key)
        if call is None:
            call = AgentToolCall(
                id=uuid4(), tenant_id=actual.tenant_id, run_id=actual.run_id, call_key=key,
                tool=tool, input_digest=digest([tool, payload]), state="started",
                execution_binding=options["execution_binding"],
            )
            self.calls[key] = call
        assert call.execution_binding == options["execution_binding"]
        return call.id, call.result

    def settle(self, _, call_id, *, result, **__):
        call = next(c for c in self.calls.values() if c.id == call_id)
        call.result, call.state = result, "completed"

    def release_call(self, *_args, **_kwargs):
        pytest.fail("Successful synthetic native exchange must not release as unknown")


def test_gateway_returns_actual_model_ledger_and_keeps_binding_out_of_native_payload():
    f = ledger()
    route, seen = configured_route(), []
    f.run.versions = {}

    def transport(request):
        import json

        body = json.loads(request.content)
        seen.append(body)
        assert "execution_binding" not in body and "loaded_skills" not in body
        return httpx.Response(200, json={
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            "choices": [{"finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "native_untrusted", "type": "function", "function": {
                    "name": tool_name(f.spec.name), "arguments": json.dumps(f.arguments),
                }}],
            }}],
        })

    client = AgentProviderClient(httpx.MockTransport(transport))
    store = GatewayStore(f)
    gateway = AgentGateway(store, route_for=lambda _: route, cost_required=False, client=client)
    options = dict(
        system="frozen", messages=[{"role": "user", "content": "synthetic"}],
        tools=disclosure(f.registry, operations=binding_operations(f.catalog, (f.source.skill,))),
        output_schema={"type": "object"}, loaded_skills=(f.source.skill,),
    )
    assert f.spec.name in {tool["name"] for tool in options["tools"]}
    try:
        with registered_graph_context("xiaopai"):
            first = gateway.turn(f.scope, **options)
            cached = gateway.turn(f.scope, **options)
        assert len(seen) == 1 and first.ledger_call_id == cached.ledger_call_id
        call = next(iter(store.calls.values()))
        assert first.ledger_call_id == call.id
        assert call.result["calls"][0]["id"] == "native_untrusted"
        source = WriteSource(skill=f.source.skill, model_call_id=call.id, response_index=0)
        checked = validate_model_source(
            f.run, call, f.scope, source, f.spec, f.arguments, route=route
        )
        assert checked.loaded_skills == (f.source.skill,)
    finally:
        client.close()
