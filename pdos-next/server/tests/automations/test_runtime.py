"""Runtime boundaries with SQL transport substitutes, without database or model execution."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentEvent, AgentRun
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.automations import runtime
from pdos_next.domain.automations.schemas import AutomationSpec, Trigger
from pdos_next.errors import DomainError
from pdos_next.service import Context

AT = datetime(2026, 10, 18, 10, tzinfo=UTC)


class SQL:
    """Supply owner-read rows; deliberately do not implement database filtering or writes."""

    def __init__(self, version):
        self.version, self.run, self.occurrence = version, None, None
        self.added, self.statements, self.flushes = [], [], 0
        self.used = (0, 0, 0, 0)

    def scalar(self, statement):
        assert statement.column_descriptions[0]["entity"] is runtime.Occurrence
        self.statements.append(statement)
        return self.occurrence

    def get(self, model, identity):
        if model is runtime.Version:
            assert identity == self.version.id
            return self.version
        if model is AgentRun:
            assert self.run is not None and identity == self.run.id
            return self.run
        raise AssertionError("Unexpected row read")

    def execute(self, statement, params=None):
        self.statements.append(statement)
        return SimpleNamespace(one=lambda: self.used)

    def add(self, row):
        self.added.append(row)
        if isinstance(row, runtime.Occurrence):
            self.occurrence = row

    def flush(self):
        self.flushes += 1


@pytest.fixture
def case(monkeypatch):
    tenant, category, owner, writer, rule, version_id, wallet = (uuid4() for _ in range(7))
    ctx = Context(tenant, owner, owner, category_id=category)
    spec = AutomationSpec(
        name="Fixed manual read",
        goal="Read current records and keep unknowns",
        purpose="Named manual inspection",
        stop_condition="Return this inspection result",
        trigger_kind="manual",
        product_id=uuid4(),
        skill_keys=[{"key": "gap_check", "version": "1", "digest": "a" * 64}],
        validation_budget_id=wallet,
        token_limit=1000,
        budget={
            "limit_micro_usd": 10,
            "input_token_limit": 100,
            "output_token_limit": 100,
            "call_limit": 2,
        },
        cooldown_seconds=60,
        max_runs=2,
    )
    version = SimpleNamespace(
        id=version_id,
        tenant_id=tenant,
        category_id=category,
        rule_id=rule,
        owner_id=owner,
        action="activate",
        state="active",
        spec=spec.model_dump(mode="json"),
    )
    pointer = SimpleNamespace(
        rule_id=rule,
        state="active",
        revision=3,
        published_version_id=version.id,
        admitted_count=0,
        last_admitted_at=None,
    )
    session = SQL(version)
    taint = SimpleNamespace(
        private_context=True,
        data_categories=("internal",),
        customer_identities=(),
        read_sources=[],
    )
    ports = SimpleNamespace(
        writer_for=Mock(return_value=writer), binding_for=Mock(return_value=taint)
    )

    def new_run(_session, actual_ctx, **kwargs):
        assert _session is session and actual_ctx is ctx
        session.run = SimpleNamespace(
            id=uuid4(),
            tenant_id=tenant,
            category_id=category,
            requester_id=owner,
            proposal_id=None,
            intent_digest=kwargs["request_digest"],
            state="queued",
            **kwargs,
        )
        return session.run

    creator = Mock(side_effect=new_run)
    monkeypatch.setattr(runtime, "now", lambda: AT)
    monkeypatch.setattr(runtime, "human", Mock())
    monkeypatch.setattr(runtime, "require_access", Mock())
    monkeypatch.setattr(runtime, "owned", Mock(return_value=pointer))
    monkeypatch.setattr(runtime, "spec_current", Mock())
    monkeypatch.setattr(runtime, "create_run", creator)
    return SimpleNamespace(
        ctx=ctx,
        spec=spec,
        pointer=pointer,
        version=version,
        session=session,
        ports=ports,
        creator=creator,
        trigger=Trigger(
            expected_rule_revision=3, version_id=version.id, idempotency_key="manual-request-001"
        ),
    )


def admit(case, trigger=None):
    return runtime.admit(
        case.session, case.ctx, case.pointer.rule_id, trigger or case.trigger, case.ports
    )


def test_admission_binds_actual_published_spec_and_original_replay_survives_pause(case):
    run, occurrence = admit(case)
    assert run.trigger == runtime.TRIGGER and run.goal == case.spec.goal
    assert (
        run.product_id == case.spec.product_id
        and run.validation_budget_id == case.spec.validation_budget_id
    )
    assert run.token_limit == case.spec.token_limit and run.private_context is True
    assert occurrence.run_id == run.id and occurrence.published_version_id == case.version.id
    assert case.pointer.admitted_count == 1 and case.pointer.last_admitted_at == AT
    assert [type(row) for row in case.session.added] == [runtime.Occurrence, AgentEvent]
    case.pointer.state, case.pointer.revision = "paused", 4
    before = len(case.session.added), case.session.flushes, case.pointer.admitted_count
    assert admit(case) == (run, occurrence)
    assert case.creator.call_count == 1
    assert (len(case.session.added), case.session.flushes, case.pointer.admitted_count) == before
    # Replay reads its original proof, rather than revalidating new-admission skill enablement.
    assert runtime.spec_current.call_count == 1


@pytest.mark.parametrize("fault", ["paused", "stale", "maximum", "cooldown", "disabled_skill"])
def test_refused_new_admission_never_reaches_run_creation_or_writes(case, fault):
    if fault == "paused":
        case.pointer.state = "paused"
    elif fault == "stale":
        case.pointer.revision += 1
    elif fault == "maximum":
        case.pointer.admitted_count, case.pointer.last_admitted_at = 2, AT - timedelta(days=1)
    elif fault == "cooldown":
        case.pointer.admitted_count, case.pointer.last_admitted_at = 1, AT
    else:
        runtime.spec_current.side_effect = DomainError("FORBIDDEN_SCOPE", "Skill disabled", 403)
    with pytest.raises(DomainError):
        admit(case)
    case.creator.assert_not_called()
    case.ports.binding_for.assert_not_called()
    case.ports.writer_for.assert_not_called()
    assert case.session.added == [] and case.session.flushes == 0


def test_original_key_with_changed_trigger_version_cannot_create_or_replace_a_run(case):
    original, _ = admit(case)
    changed = case.trigger.model_copy(update={"version_id": uuid4()})
    with pytest.raises(DomainError) as error:
        admit(case, changed)
    assert error.value.code == "DUPLICATE_INTENT_CONFLICT"
    assert case.creator.call_count == 1 and case.session.run is original
    assert case.pointer.admitted_count == 1


@pytest.mark.parametrize(
    "field", ["goal", "product_id", "validation_budget_id", "token_limit", "proposal_id"]
)
def test_run_must_match_the_saved_rule_instead_of_caller_selected_configuration(case, field):
    run, _ = admit(case)
    setattr(
        run, field, "Changed goal" if field == "goal" else 1 if field == "token_limit" else uuid4()
    )
    with pytest.raises(DomainError) as error:
        runtime.binding(case.session, run)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_run_requires_actual_occurrence_and_matching_persisted_request_digest(case):
    run, occurrence = admit(case)
    case.session.occurrence = None
    with pytest.raises(DomainError):
        runtime.binding(case.session, run)
    case.session.occurrence = occurrence
    occurrence.request_digest = "0" * 64
    with pytest.raises(DomainError):
        runtime.binding(case.session, run)


def store_for(case):
    @contextmanager
    def transaction(_scope):
        yield case.session, case.session.run

    return SimpleNamespace(transaction=transaction)


def test_pinned_skill_and_preload_survive_rule_pause_but_not_skill_version_substitution(case):
    admit(case)
    case.pointer.state = "paused"
    scope, store = SimpleNamespace(trigger=runtime.TRIGGER), store_for(case)
    selected = case.spec.skill_keys[0]
    assert runtime.preload(store, scope, fallback=("proposal_drafting",)) == ("gap_check",)
    assert runtime.permitted_skill(store, scope, selected)
    assert not runtime.permitted_skill(store, scope, selected.model_copy(update={"version": "2"}))
    assert not runtime.permitted_skill(
        store, scope, selected.model_copy(update={"digest": "b" * 64})
    )


@pytest.mark.parametrize(
    "tool",
    [
        "research.search",
        "research.read",
        "research.fanout",
        "mcp.tools.list",
        "mcp.read",
        "web.read",
    ],
)
def test_network_guard_prevents_adapter_invocation_for_actual_registered_names(case, tool):
    admit(case)
    host = object.__new__(BoundHost)
    host.store = store_for(case)
    callback = Mock(side_effect=AssertionError("No network callback for read-only automation"))
    host.adapters = SimpleNamespace(read_tools={tool: callback})
    host.read_callback = Mock(side_effect=AssertionError("No read reservation for denied tool"))
    with pytest.raises(DomainError) as error:
        host.read(SimpleNamespace(trigger=runtime.TRIGGER, isolation="main"),
                  SimpleNamespace(name=tool), {}, "call")
    assert error.value.code == "FORBIDDEN_SCOPE"
    callback.assert_not_called()
    host.read_callback.assert_not_called()


@pytest.mark.parametrize("method", ["prepare", "write"])
def test_write_guard_prevents_candidate_or_domain_adapter_calls(case, method):
    admit(case)
    host = object.__new__(BoundHost)
    host.store = store_for(case)
    host.current = Mock(side_effect=AssertionError("Denied writes must stop before execution"))
    host.adapters = SimpleNamespace(prepare_candidate=Mock(), execute_command=Mock())
    with pytest.raises(DomainError) as error:
        getattr(host, method)(
            SimpleNamespace(trigger=runtime.TRIGGER),
            SimpleNamespace(),
            {},
            "call",
            **({"source": None} if method == "write" else {}),
        )
    assert error.value.code == "FORBIDDEN_SCOPE"
    host.current.assert_not_called()
    host.adapters.prepare_candidate.assert_not_called()
    host.adapters.execute_command.assert_not_called()


@pytest.mark.parametrize("exceeded", [None, 0, 1, 2, 3])
def test_cumulative_rule_budget_allows_exact_boundary_and_rejects_one_over(case, exceeded):
    run, _ = admit(case)
    used, additional = [5, 40, 10, 1], (5, 60, 90, 1)
    if exceeded is not None:
        used[exceeded] += 1
    case.session.used = tuple(used)
    before = deepcopy(case.version.spec)
    if exceeded is None:
        runtime.reserve(case.session, run, reservation=150, cost_lease=(*additional[:3], {}))
    else:
        with pytest.raises(DomainError) as error:
            runtime.reserve(case.session, run, reservation=150, cost_lease=(*additional[:3], {}))
        assert error.value.code == "RATE_LIMITED"
    assert case.session.statements[-2].text.startswith("SELECT pg_advisory_xact_lock")
    assert case.version.spec == before and case.creator.call_count == 1


def test_normal_conversation_keeps_existing_runtime_policy_and_fallbacks():
    @contextmanager
    def transaction(_scope):
        yield object(), SimpleNamespace(trigger="conversation")

    store, scope = SimpleNamespace(transaction=transaction), SimpleNamespace(trigger="conversation")
    assert runtime.preload(store, scope, fallback=("proposal_drafting",)) == ("proposal_drafting",)
    assert runtime.permitted_skill(store, scope, SimpleNamespace())
    runtime.guard_tool(store, scope, "research.fanout")
    runtime.guard_tool(store, scope, writing=True)


def test_common_store_rejects_changed_scope_trigger_before_authority_or_callback(monkeypatch):
    from pdos_next.agent_kernel import persistence

    scope = RunScope(
        tenant_id=uuid4(),
        requester_id=uuid4(),
        writer_id=uuid4(),
        session_id=uuid4(),
        run_id=uuid4(),
        category_id=uuid4(),
        trigger=runtime.TRIGGER,
    )
    stored = SimpleNamespace(
        id=scope.run_id,
        tenant_id=scope.tenant_id,
        requester_id=scope.requester_id,
        writer_id=scope.writer_id,
        category_id=scope.category_id,
        product_id=scope.product_id,
        proposal_id=scope.proposal_id,
        session_id=scope.session_id,
        trigger=runtime.TRIGGER,
        private_context=scope.private_context,
        data_categories=list(scope.data_categories),
        customer_identities=list(scope.customer_identities),
        reverted_at=None,
        cancel_epoch=scope.cancel_epoch,
        state="running",
    )
    session = SimpleNamespace(scalar=Mock(return_value=stored))

    @contextmanager
    def tenant_session(engine, tenant, **kwargs):
        assert engine is store.engine and tenant == scope.tenant_id
        assert kwargs == {
            "actor_id": scope.writer_id,
            "requester_id": scope.requester_id,
            "category_id": scope.category_id,
        }
        yield session

    monkeypatch.setattr(persistence, "tenant_session", tenant_session)
    store = KernelStore(object())
    store.authority = Mock()
    with store.transaction(scope) as (_session, actual):
        assert _session is session and actual is stored
    store.authority.reset_mock()
    callback = Mock()
    with pytest.raises(DomainError) as error:
        with store.transaction(replace(scope, trigger="conversation")):
            callback()
    assert error.value.code == "FORBIDDEN_SCOPE"
    store.authority.assert_not_called()
    callback.assert_not_called()
