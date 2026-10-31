"""No-DB tests of the actual Activity/registered graph and owner capability boundary."""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pdos_agent_runtime.graph import in_registered_agent_graph
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import OperationalError

from pdos_next import personal_summary, personal_summary_graph
from pdos_next import personal_summary_runtime as runtime
from pdos_next.agent_kernel import activities
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.schemas import AutomationSpec
from pdos_next.errors import DomainError
from pdos_next.models import Principal, Receipt
from pdos_next.personal_summary_schemas import ObjectRef, Selection
from pdos_next.service import Context, digest

AT = datetime(2026, 10, 29, tzinfo=UTC)


def specification(**overrides):
    return {
        "name": "本人摘要", "goal": "读取固定范围的结构条目", "purpose": "本人工作",
        "stop_condition": "生成或明确失能", "trigger_kind": "schedule",
        "trigger_config": {"first_at": AT.isoformat(), "original_timezone": "UTC"},
        "skill_keys": [{"key": "gap_check", "version": "1", "digest": "a" * 64}],
        "validation_budget_id": str(uuid4()), "token_limit": 1000,
        "budget": {"limit_micro_usd": 0, "input_token_limit": 1,
                   "output_token_limit": 1, "call_limit": 1},
        "cooldown_seconds": 0, "max_runs": 3, **overrides,
    }


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class Session:
    def __init__(self, run, principal):
        self.run, self.principal = run, principal
        self.info = {}
        self.queries = []
        self.rows = []
        self.no_autoflush = nullcontext()

    def get(self, model, _identity):
        return self.run if model is AgentRun else self.principal if model is Principal else None

    def execute(self, query):
        self.queries.append(query)
        return Rows(self.rows)


class Store:
    def __init__(self, scope, session):
        self.engine, self.scope_value, self.session = NS(), scope, session
        self.transactions = []

    @contextmanager
    def transaction(self, scope, *, lock=False):
        assert scope == self.scope_value
        self.transactions.append(lock)
        if self.session.run.cancel_epoch != scope.cancel_epoch:
            raise DomainError("CANCELLED_RUN", "cancelled")
        yield self.session, self.session.run

    def scope(self, **_values):
        return self.scope_value

    def current(self, scope):
        with self.transaction(scope):
            pass


@pytest.fixture
def bound(monkeypatch):
    tenant, owner, writer, category, run_id, session_id, product = [uuid4() for _ in range(7)]
    scope = RunScope(tenant, owner, writer, session_id, run_id, category, product,
                     trigger="automation_service")
    run = NS(id=run_id, tenant_id=tenant, requester_id=owner, writer_id=writer,
             category_id=category, product_id=product, session_id=session_id,
             trigger="automation_service", cancel_epoch=0, reverted_at=None,
             state="queued", result=None, error_code=None, created_at=AT, goal="本人摘要",
             used_tokens=0, held_tokens=0)
    principal = NS(id=owner, tenant_id=tenant, active=True, kind="human")
    session = Session(run, principal)
    store = Store(scope, session)
    spec = AutomationSpec.model_validate(specification(
        personal_summary={}, product_id=str(product),
    ))
    calls, snapshots = [], []

    def binding(s, actual, **_kwargs):
        assert actual is run
        calls.append((s, actual))
        return NS(), spec

    @contextmanager
    def snapshot(_engine, actual_tenant, **kwargs):
        assert actual_tenant == run.tenant_id
        snapshots.append(kwargs)
        session.info = {"scope": (tenant, kwargs["actor_id"], kwargs["requester_id"], None),
                        "read_snapshot": kwargs["read_snapshot"]}
        yield session

    monkeypatch.setattr(service_runtime, "summary_binding", binding)
    monkeypatch.setattr(runtime, "tenant_session", snapshot)
    monkeypatch.setattr(runtime, "require_access", lambda *_a, **_k: None)
    monkeypatch.setattr(runtime, "_previous", lambda *_a: None)
    monkeypatch.setattr("pdos_next.agent_kernel.process_view.record_state", lambda *_a: None)
    return NS(scope=scope, run=run, session=session, store=store, spec=spec,
              calls=calls, snapshots=snapshots, owner=owner)


def empty(bound, *, complete=True):
    ctx = Context(bound.run.tenant_id, bound.owner, bound.owner)
    choice = Selection(category_ids=(bound.run.category_id,))
    return personal_summary.compose(ctx, choice, AT, [], []).model_copy(
        update={"complete": complete},
    ).model_dump(mode="json")


@pytest.mark.parametrize("kind", ["manual", "schedule", "domain_event", "relative_milestone"])
def test_absent_new_field_preserves_existing_canonical_spec_digest(kind):
    config = {
        "schedule": {"first_at": AT.isoformat(), "original_timezone": "UTC"},
        "domain_event": {"event_types": ["synthetic.event"]},
        "relative_milestone": {"source_kind": "plan_task", "project_id": str(uuid4()),
                               "task_id": str(uuid4()), "clock": "latest_finish",
                               "offset_seconds": 0},
    }
    raw = specification(trigger_kind=kind, trigger_config=config.get(kind), product_id=str(uuid4()))
    before = AutomationSpec.model_validate(raw).model_dump(mode="json")
    explicit_none = AutomationSpec.model_validate({**raw, "personal_summary": None})
    assert "personal_summary" not in before
    assert before == explicit_none.model_dump(mode="json")
    assert digest(before) == digest(explicit_none.model_dump(mode="json"))


def test_summary_choice_enters_same_t1_version_and_rejects_owner_authority_fields():
    original = AutomationSpec.model_validate(specification())
    saved = AutomationSpec.model_validate(specification(
        validation_budget_id=str(original.validation_budget_id),
        personal_summary={"groups": ["waiting"]},
    ))
    assert saved.personal_summary.groups == ("waiting",)
    assert digest(saved.model_dump(mode="json")) != digest(original.model_dump(mode="json"))
    for key in ("owner_id", "grant_id", "writer_id", "role", "authorized"):
        with pytest.raises(ValidationError):
            AutomationSpec.model_validate(specification(personal_summary={key: str(uuid4())}))
    with pytest.raises(ValidationError):
        AutomationSpec.model_validate(specification(trigger_kind="manual", trigger_config=None,
                                                   personal_summary={}))


def test_owner_snapshot_uses_actual_run_owner_and_scope(bound, monkeypatch):
    def read(s, ctx, choice, *, previous, product_id):
        assert s is bound.session and ctx.actor_id == ctx.requester_id == bound.owner
        assert ctx.category_id is None and ctx.run_id is None and ctx.agent_run_id is None
        assert choice.category_ids == (bound.run.category_id,)
        assert product_id == bound.run.product_id
        assert previous is None and len(bound.calls) == 2
        return personal_summary.Summary.model_validate(empty(bound))

    monkeypatch.setattr(personal_summary, "read", read)
    actual = runtime.generate(bound.store, bound.scope)
    assert actual["model_used"] is False
    assert bound.snapshots == [{"actor_id": bound.owner, "requester_id": bound.owner,
                                "read_snapshot": True}]
    assert all(call[1] is bound.run for call in bound.calls)


@pytest.mark.parametrize("change", ["scope", "cancelled", "inactive", "agent_owner", "isolation"])
def test_owner_read_adapter_cannot_become_generic_impersonation(bound, change):
    from dataclasses import replace

    scope = bound.scope
    if change == "scope":
        bound.run.requester_id = uuid4()
    elif change == "cancelled":
        bound.run.cancel_epoch += 1
    elif change == "inactive":
        bound.session.principal.active = False
    elif change == "agent_owner":
        bound.session.principal.kind = "agent"
    else:
        scope = replace(scope, isolation="assistant_extract")
    with pytest.raises(DomainError) as error:
        runtime.generate(bound.store, scope)
    assert error.value.code in {"FORBIDDEN_SCOPE", "CANCELLED_RUN"}


def test_repeated_terminal_persist_keeps_original_snapshot_and_zero_model_cost(bound):
    original = runtime.persist(bound.store, bound.scope, empty(bound))
    assert bound.run.state == "completed" and bound.run.used_tokens == bound.run.held_tokens == 0
    different = deepcopy(empty(bound))
    different["as_of"] = "2026-10-30T00:00:00Z"
    again = runtime.persist(bound.store, bound.scope, different)
    assert again == original == bound.run.result
    assert original["result"]["delivery"]["state"] == "available_in_inbox"
    assert bound.store.transactions[-1] is True


def test_partial_coverage_persists_partial_not_invented_complete(bound):
    output = runtime.persist(bound.store, bound.scope, empty(bound, complete=False))
    assert output["status"] == bound.run.state == "partial" and output["unfinished"]


def test_actual_registered_graph_restores_read_checkpoint_and_rechecks_sources(bound, monkeypatch):
    saver, generations, attempts = InMemorySaver(), [], []
    snapshot = empty(bound)

    def generate(store, scope):
        assert in_registered_agent_graph()
        generations.append(scope.run_id)
        return snapshot

    original = runtime.persist

    def interrupted(store, scope, value):
        assert in_registered_agent_graph()
        attempts.append(value)
        if len(attempts) == 1:
            raise RuntimeError("synthetic worker interruption before terminal commit")
        return original(store, scope, value)

    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "persist", interrupted)
    with pytest.raises(RuntimeError):
        personal_summary_graph.execute(bound.store, bound.scope, checkpointer=saver)
    assert bound.run.result is None
    output = personal_summary_graph.execute(bound.store, bound.scope, checkpointer=saver)
    assert output["output"]["status"] == "completed" and len(generations) == 1
    assert attempts == [snapshot, snapshot] and len(bound.calls) >= 3


@pytest.mark.parametrize("transient", [False, True])
def test_activity_without_adapters_runs_summary_and_retries_sql(bound, monkeypatch, transient):
    @contextmanager
    def initial(*_args, **_kwargs):
        yield bound.session

    def binding(s, run):
        assert run is bound.run
        return NS(), bound.spec

    def no_gateway(*_a, **_k):
        pytest.fail("deterministic summary must not instantiate model host")

    memory, persist_calls = InMemorySaver(), []
    original_persist = runtime.persist

    def persist(store, scope, value):
        persist_calls.append(value)
        if transient and len(persist_calls) == 1:
            raise OperationalError("synthetic no-SQL disconnect", {}, ConnectionError())
        return original_persist(store, scope, value)

    @contextmanager
    def saver(_url):
        yield memory

    def generate(*_a):
        assert in_registered_agent_graph()
        return empty(bound)

    monkeypatch.setattr(activities, "tenant_session", initial)
    monkeypatch.setattr("pdos_next.domain.automations.runtime.binding", binding)
    monkeypatch.setattr(activities, "BoundHost", no_gateway)
    monkeypatch.setattr(activities.activity, "heartbeat", lambda *_a: None)
    monkeypatch.setattr(activities, "verified_checkpoint_url", lambda url: url)
    monkeypatch.setattr(activities.PostgresSaver, "from_conn_string", saver)
    monkeypatch.setattr(runtime, "generate", generate)
    monkeypatch.setattr(runtime, "persist", persist)
    worker = activities.KernelActivities(bound.store.engine, checkpoint_url="synthetic-local-only")
    worker.store = bound.store
    ref = {"tenant_id": str(bound.run.tenant_id), "category_id": str(bound.run.category_id),
           "actor_id": str(bound.run.writer_id), "requester_id": str(bound.owner),
           "subject_id": str(bound.run.id)}
    if transient:
        with pytest.raises(OperationalError):
            worker.advance(ref)
        assert bound.run.result is None and bound.run.state == "running"
    output = worker.advance(ref)
    assert output == {"run_id": str(bound.run.id), "status": "completed"}
    assert bound.run.result["result"]["personal_summary"]["model_used"] is False
    assert bound.run.used_tokens == 0
    assert worker.advance(ref) == output


def test_history_read_is_ordinary_human_and_never_returns_other_owner_snapshot(bound):
    runtime.persist(bound.store, bound.scope, empty(bound))
    ctx = Context(bound.run.tenant_id, bound.owner, bound.owner, category_id=bound.run.category_id)
    bound.session.info["scope"] = (ctx.tenant_id, ctx.actor_id, ctx.requester_id, ctx.category_id)
    actual = runtime.checked_result(bound.session, ctx, bound.run)
    assert actual == bound.run.result and actual is not bound.run.result
    other = Context(ctx.tenant_id, uuid4(), uuid4(), category_id=ctx.category_id)
    with pytest.raises(DomainError):
        runtime.checked_result(bound.session, other, bound.run)


def test_history_metadata_batches_keep_fixed_versions_and_fail_on_revocation(bound):
    version, project = uuid4(), uuid4()
    source = ObjectRef(kind="project_status_update", id=project, version_id=version,
                       revision=1, category_id=bound.run.category_id,
                       product_id=bound.run.product_id, project_id=project)
    bound.session.rows = [{"id": version, "source_id": project,
                           "category_id": source.category_id, "product_id": source.product_id,
                           "project_id": project, "revision": 1}]
    assert runtime._readable_sources(bound.session, bound.run, {source}) == {source}
    sql = str(bound.session.queries[-1].compile(dialect=dialect()))
    assert "project_status_updates" in sql and "fact_summary" not in sql
    assert "next_steps" not in sql and "current" not in sql.lower()
    bound.session.rows = []  # Ordinary RLS no longer returns the original version.
    assert runtime._readable_sources(bound.session, bound.run, {source}) == set()
    # A new current version cannot satisfy the fixed historical identity.
    bound.session.rows = [{"id": uuid4(), "source_id": project,
                           "category_id": source.category_id, "product_id": source.product_id,
                           "project_id": project, "revision": 1}]
    assert runtime._readable_sources(bound.session, bound.run, {source}) == set()


def test_native_source_map_handles_actual_handoff_receipt_and_run_identity():
    models = runtime._source_models()
    assert models["external_handoff"][0].__name__ == "ExternalReceipt"
    run_model = models["verification_result_return"][0]
    assert runtime._source_key(run_model).key == "run_id"
    assert runtime._source_key(models["project_status_update"][0]).key == "project_id"


def test_product_narrowing_occurs_in_sql_before_paging_counts():
    from sqlalchemy import column, select, table

    t = table("native_summary", column("category_id"), column("product_id"))
    category, product = uuid4(), uuid4()
    query = personal_summary._categories(
        select(t), t.c.category_id, Selection(category_ids=(category,)),
        product=t.c.product_id, product_id=product,
    )
    sql = str(query.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    assert str(category) in sql and str(product) in sql and "WHERE" in sql


def actual_service_binding():
    from pdos_next.domain.automations.models import AutomationRuleVersion
    from pdos_next.domain.automations.service_models import AutomationServiceGrant

    tenant, owner, writer, category, product, rule_id, run_id, version_id, grant_id = (
        uuid4() for _ in range(9)
    )
    spec = AutomationSpec.model_validate(specification(
        personal_summary={}, product_id=str(product),
    ))
    receipt_id, command_id, confirmation_id = (uuid4() for _ in range(3))
    run = NS(id=run_id, tenant_id=tenant, requester_id=owner, writer_id=writer,
             category_id=category, product_id=product, trigger="automation_service",
             goal=spec.goal, validation_budget_id=spec.validation_budget_id,
             token_limit=spec.token_limit, proposal_id=None, project_id=None,
             intent_digest="b" * 64)
    grant = NS(id=grant_id, tenant_id=tenant, owner_id=owner, writer_id=writer,
               category_id=category, rule_id=rule_id, published_version_id=version_id,
               receipt_id=receipt_id, expires_at=None)
    version = NS(id=version_id, tenant_id=tenant, category_id=category, rule_id=rule_id,
                 owner_id=owner, actor_id=owner, requester_id=owner, action="activate",
                 state="active", receipt_id=receipt_id, operation="ai.automation.activate",
                 spec=spec.model_dump(mode="json"), revision=2, command_id=command_id,
                 confirmation_id=confirmation_id, request_digest="c" * 64, intent_digest="d" * 64)
    version.spec_sha256 = digest(version.spec)
    receipt = NS(id=receipt_id, tenant_id=tenant, category_id=category, actor_id=owner,
                 requester_id=owner, operation="ai.automation.activate",
                 subject_type="automation_rule",
                 subject_id=version_id, subject_revision=2, command_id=command_id,
                 confirmation_id=confirmation_id, request_digest="c" * 64, intent_digest="d" * 64)
    attempt = NS(id=uuid4(), state="admitted", tenant_id=tenant, owner_id=owner, writer_id=writer,
                 category_id=category, rule_id=rule_id, run_id=run_id,
                 published_version_id=version_id, service_grant_id=grant_id,
                 request_digest=run.intent_digest, trigger_kind="schedule")
    rows = {(AutomationServiceGrant, grant_id): grant, (AutomationRuleVersion, version_id): version,
            (Receipt, receipt_id): receipt}
    session = NS(get=lambda model, identity: rows.get((model, identity)),
                 scalar=lambda _q: attempt)
    return NS(session=session, run=run, grant=grant, version=version, receipt=receipt,
              attempt=attempt)


def test_summary_binding_uses_real_existing_run_binding_and_actual_t1_receipt():
    actual = actual_service_binding()
    occurrence, spec = service_runtime.summary_binding(actual.session, actual.run)
    assert occurrence is actual.attempt and spec.personal_summary == Selection()


@pytest.mark.parametrize("row,field,value", [
    ("attempt", "owner_id", uuid4()), ("attempt", "writer_id", uuid4()),
    ("attempt", "category_id", uuid4()), ("attempt", "run_id", uuid4()),
    ("attempt", "state", "queued"), ("attempt", "published_version_id", uuid4()),
    ("attempt", "request_digest", "f" * 64), ("run", "goal", "different declared work"),
    ("grant", "writer_id", uuid4()), ("version", "spec_sha256", "f" * 64),
    ("receipt", "requester_id", uuid4()), ("receipt", "actor_id", uuid4()),
    ("receipt", "confirmation_id", None), ("receipt", "subject_id", uuid4()),
    ("receipt", "subject_revision", 1), ("receipt", "command_id", uuid4()),
])
def test_summary_binding_rejects_forged_or_mismatched_actual_authority(row, field, value):
    actual = actual_service_binding()
    setattr(getattr(actual, row), field, value)
    with pytest.raises(DomainError) as error:
        service_runtime.summary_binding(actual.session, actual.run)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_checkpoint_replay_after_committed_response_loss_preserves_exact_output(bound, monkeypatch):
    saver, calls = InMemorySaver(), []
    original = runtime.persist

    def committed_but_lost(store, scope, value):
        assert in_registered_agent_graph()
        output = original(store, scope, value)
        calls.append(output)
        if len(calls) == 1:
            raise RuntimeError("synthetic response loss after terminal commit")
        return output

    monkeypatch.setattr(runtime, "generate", lambda *_a: empty(bound))
    monkeypatch.setattr(runtime, "persist", committed_but_lost)
    with pytest.raises(RuntimeError):
        personal_summary_graph.execute(bound.store, bound.scope, checkpointer=saver)
    assert bound.run.state == "completed"
    result = personal_summary_graph.execute(bound.store, bound.scope, checkpointer=saver)
    assert result["output"] == calls[0] == bound.run.result
    # An already-complete graph checkpoint still checks current READ.
    completed = personal_summary_graph.execute(bound.store, bound.scope, checkpointer=saver)
    assert completed["output"] == bound.run.result


def test_expired_service_still_requires_live_execution_but_retains_authorized_history():
    actual = actual_service_binding()
    actual.grant.expires_at = service_runtime.now() - timedelta(seconds=1)
    with pytest.raises(DomainError):
        service_runtime.summary_binding(actual.session, actual.run)
    actual.run.state = "queued"
    with pytest.raises(DomainError):
        service_runtime.summary_binding(actual.session, actual.run, historical=True)
    actual.run.state = "completed"
    _attempt, spec = service_runtime.summary_binding(actual.session, actual.run, historical=True)
    assert spec.personal_summary is not None
    # Original T1 and owner proof still applies; history does not bypass identity.
    actual.receipt.requester_id = uuid4()
    with pytest.raises(DomainError):
        service_runtime.summary_binding(actual.session, actual.run, historical=True)
