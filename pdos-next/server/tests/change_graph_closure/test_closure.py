"""Actual BFS/DTO/Session offline boundaries; owner rows and SQL results substituted."""

import ast
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, make_transient_to_detached

from pdos_next import change_graph_closure as c
from pdos_next.contracts import Command
from pdos_next.domain.change_execution import graph as graph_owner
from pdos_next.errors import DomainError
from pdos_next.models import Confirmation, Product
from pdos_next.schemas.change_control.contracts import Coverage, Ref
from pdos_next.schemas.verification.contracts import Scope, SourceRef
from pdos_next.service import Context


@pytest.fixture
def case(monkeypatch):
    engine = create_engine("postgresql+psycopg://invalid/never_connected")
    s = Session(bind=engine)
    s.begin()
    ctx = Context(uuid4(), uuid4(), uuid4(), category_id=UUID(int=1000000))
    scope = Scope(tenant_id=ctx.tenant_id, product_id=uuid4(), project_id=uuid4())
    audience = (f"product:{scope.product_id}",)
    root = Ref(id=uuid4(), revision=1, kind="engineering_configuration")
    child = Ref(id=uuid4(), revision=1, kind="part")
    source = SourceRef(id=uuid4(), revision=1, position="fixed-source")
    now = datetime.now(UTC)
    product = {
        "id": scope.product_id,
        "category_id": ctx.category_id,
        "tenant_id": ctx.tenant_id,
        "created_at": now,
        "name": "fixed-product",
        "purpose": "fixed-purpose",
        "revision": 1,
        "status": "draft",
        "visibility": "category",
        "owner_id": ctx.requester_id,
        "parent_product_id": None,
        "target_price": None,
        "target_price_currency": None,
        "target_price_basis": None,
        "target_price_includes_tax": None,
        "target_price_as_of": None,
    }
    state = SimpleNamespace(
        epoch=1,
        product=product,
        rows=None,
        links={root.identity: [(child, "fixed-child")]},
        hidden=set(),
        views={},
        reads={},
        reader_count=0,
        before_reader=None,
        in_load=None,
        on_stamp=None,
        stamp_count=0,
    )

    def issue_loader(*args):
        raise AssertionError("This synthetic owner does not load Issue")

    monkeypatch.setattr(c.old, "_issue_loader", lambda session: issue_loader)

    def stamp_rows(session, actual_scope):
        state.stamp_count += 1
        if state.on_stamp:
            state.on_stamp(state.stamp_count)
        return (
            deepcopy(state.rows)
            if state.rows is not None
            else [{**state.product, "dependency_epoch": state.epoch}]
        )

    monkeypatch.setattr(c, "_stamp_rows", stamp_rows)

    class Reader(c._TrackedReader):
        def _load(self, ref):
            if state.in_load:
                state.in_load(self, ref)
            if ref.identity in state.hidden:
                raise DomainError("FORBIDDEN_SCOPE", "private undisclosed source", 403)
            row = SimpleNamespace(
                revision=ref.revision,
                owner_id=ctx.requester_id,
                visibility="product",
                project_id=scope.project_id,
            )
            return (
                row,
                {"name": ref.kind, **state.views.get(ref.identity, {})},
                deepcopy(state.reads.get(ref.identity, [])),
                {},
            )

        def links(self, obj):
            return tuple(state.links.get(obj.ref.identity, ()))

    def reader(session, caller, actual_scope, target):
        state.reader_count += 1
        if state.before_reader:
            state.before_reader(state.reader_count)
        return Reader(session, caller, actual_scope.product_id, actual_scope, target, issue_loader)

    monkeypatch.setattr(c, "_reader", reader)
    graph = graph_owner.capture_graph(
        reader(s, ctx, scope, audience),
        identity=uuid4(),
        roots=(root,),
        captured_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        nature="real",
        sources=(source,),
    )
    state.reader_count = 0
    command = Command(
        category_id=ctx.category_id,
        command_id=uuid4(),
        idempotency_key="closure-original-request",
        operation="change.order.approve",
        product_id=scope.product_id,
        expected_revision=1,
        source_read_set=[{"artifact_id": source.id, "expected_revision": 1}],
        payload={},
    )
    expected = c.closure_stamp(s, ctx, scope=scope, audience=audience)
    state.stamp_count = 0
    value = SimpleNamespace(
        s=s,
        engine=engine,
        ctx=ctx,
        scope=scope,
        audience=audience,
        root=root,
        child=child,
        source=source,
        graph=graph,
        command=command,
        state=state,
        expected=expected,
        valid_until=now + timedelta(minutes=5),
    )
    yield value
    s.close()
    engine.dispose()


def run(case, **kwargs):
    values = dict(
        graph=case.graph,
        scope=case.scope,
        audience=case.audience,
        roots=case.graph.roots,
        expected_closure=case.expected,
        valid_until=case.valid_until,
        complete_recheck=True,
    )
    values.update(kwargs)
    return c.recheck_graph_closure(case.s, case.ctx, case.command, **values)


def rejected(case, **kwargs):
    before = tuple(case.s.dispatch.do_orm_execute)
    with pytest.raises(DomainError) as error:
        run(case, **kwargs)
    assert error.value.reason == "RECHECK_REQUIRED"
    assert tuple(case.s.dispatch.do_orm_execute) == before
    return error.value


def test_actual_t2_bfs_once_retains_original_graph_and_watermarks(case):
    before = tuple(case.s.dispatch.do_orm_execute)
    result = run(case)
    assert result.graph is case.graph
    assert result.closure == case.expected and result.closure is not case.expected
    assert result.authority_attested is False
    assert result.required_source_read_set == (
        {"artifact_id": str(case.source.id), "expected_revision": 1},
    )
    assert case.state.reader_count == 1 and case.state.stamp_count == 2
    assert tuple(case.s.dispatch.do_orm_execute) == before
    assert datetime.now(UTC) >= result.checked_at


def test_offline_scalar_stamp_sql_uses_actual_clock_no_lifecycle_epoch(case):
    sql = str(c.stamp_statement(case.scope).compile(dialect=postgresql.dialect()))
    assert "JOIN change_dependency_clocks" in sql
    assert "products.tenant_id" in sql and "products.id" in sql
    assert "change_dependency_clocks.epoch AS dependency_epoch" in sql
    assert "lifecycle_epoch" not in sql and "confirmations" not in sql
    assert c.stamp_statement(case.scope).get_execution_options()["autoflush"] is False


@pytest.mark.parametrize("epoch", [None, False, True, 0, -1, "1", 1.0])
def test_clock_positive_builtin_integer_only(case, epoch):
    case.state.epoch = epoch
    rejected(case)


@pytest.mark.parametrize("rows", [[], [{}, {}]])
def test_missing_or_duplicate_clock_rows(case, rows):
    case.state.rows = rows
    rejected(case)


@pytest.mark.parametrize(
    "field", ["id", "tenant_id", "name", "purpose", "revision", "status", "owner_id", "created_at"]
)
def test_actual_product_business_material_change(case, field):
    value = case.state.product[field]
    case.state.product[field] = uuid4() if isinstance(value, type(uuid4())) else str(value) + "x"
    rejected(case)


def test_clock_aba_visible_graph_identical_still_rejects(case):
    # Represents two committed SQL owner mutations after capture, then restore.
    case.state.epoch += 2
    rejected(case)


@pytest.mark.parametrize("when", [1, 2])
def test_clock_changes_before_or_after_each_complete_pass(case, when):
    def drift(count):
        if count == when:
            case.state.epoch += 1

    case.state.on_stamp = drift
    rejected(case)


def test_new_reverse_node_requires_recheck(case):
    new = Ref(id=uuid4(), revision=1, kind="build")
    case.state.links[case.root.identity].append((new, "new reverse Build"))
    rejected(case)


def test_new_edge_between_original_nodes_requires_recheck(case):
    case.state.links[case.child.identity] = [(case.root, "new reverse relation")]
    rejected(case)


@pytest.mark.parametrize("mutation", ["remove", "relation", "source", "label", "current"])
def test_existing_topology_and_node_source_changes(case, mutation):
    if mutation == "remove":
        case.state.links[case.root.identity] = []
    elif mutation == "relation":
        case.state.links[case.root.identity] = [(case.child, "changed relation")]
    elif mutation == "source":
        new = case.graph.nodes[0].model_copy(update={"source": case.source})
        case.graph = case.graph.model_copy(update={"nodes": (new, *case.graph.nodes[1:])})
    elif mutation == "label":
        case.state.views[case.root.identity] = {"name": "changed source name"}
    else:
        case.state.views[case.root.identity] = {"needs_recheck": True}
    rejected(case)


def test_discovered_hidden_dependency_never_silently_reuses_complete_graph(case):
    hidden = Ref(id=uuid4(), revision=1, kind="build")
    case.state.links[case.root.identity].append((hidden, "hidden dependency"))
    case.state.hidden.add(hidden.identity)
    error = rejected(case)
    assert str(hidden.id) not in error.message


def test_explicit_root_becomes_hidden_generic_recheck(case):
    case.state.hidden.add(case.root.identity)
    error = rejected(case)
    assert str(case.root.id) not in error.message


def test_hidden_rls_zero_row_aba_uses_actual_clock(case):
    # RLS returns no discoverable object; visible graph remains byte-identical.
    case.state.epoch += 2
    rejected(case)


def test_discovery_order_and_generated_edge_ids_are_not_topology(case):
    another = Ref(id=uuid4(), revision=1, kind="sample")
    node = case.graph.nodes[1].model_copy(
        update={
            "ref": another,
            "label": another.kind,
            "source": case.graph.nodes[1].source.model_copy(
                update={"id": another.id, "position": "change-owner:sample:"}
            ),
        }
    )
    edge = case.graph.edges[0].model_copy(update={"id": "original-path-id", "target": another})
    coverage = tuple(
        v.model_copy(update={"node": another}) for v in case.graph.coverage if v.node == case.child
    )
    case.graph = case.graph.model_copy(
        update={
            "nodes": (node, *case.graph.nodes),
            "edges": (edge, *case.graph.edges),
            "coverage": (*coverage, *case.graph.coverage),
        }
    )
    case.state.links[case.root.identity] = [(another, "fixed-child"), (case.child, "fixed-child")]

    def reverse(count):
        case.state.links[case.root.identity].reverse()

    case.state.before_reader = reverse
    result = run(case)
    assert result.graph is case.graph
    assert result.graph.edges[0].id == "original-path-id"


@pytest.mark.parametrize("field", ["scope", "audience", "roots"])
def test_server_graph_scope_audience_and_fixed_roots_binding(case, field):
    value = {
        "scope": case.scope.model_copy(update={"project_id": uuid4()}),
        "audience": (f"private:{case.ctx.requester_id}",),
        "roots": (case.child,),
    }[field]
    rejected(case, **{field: value})


@pytest.mark.parametrize("expected", [None, {}, {"version": "legacy"}])
def test_old_capture_without_closure_stamp_cannot_be_used_for_g3(case, expected):
    rejected(case, expected_closure=expected)


def complete(case):
    first = case.graph.coverage[0].model_copy(
        update={"status": "complete", "source": case.source, "reason": None}
    )
    case.graph = case.graph.model_copy(update={"coverage": (first, *case.graph.coverage[1:])})


def test_saved_complete_requires_real_server_owner_integration(case):
    complete(case)
    rejected(case)


def test_trusted_complete_callback_can_preserve_exact_coverage_for_offline_contract(case):
    complete(case)
    calls = []

    def callback(s, ctx, pid, *, graph, current_graph, reader):
        assert s is case.s and ctx is case.ctx and pid == case.scope.product_id
        assert graph is case.graph and current_graph.id == graph.id
        calls.append(reader)
        return graph.coverage

    result = run(case, coverage_refresh=callback)
    assert len(calls) == 1
    assert result.authority_attested is False  # Substitute grants no real qualification.


def test_complete_must_not_be_replaced_by_unknown(case):
    complete(case)
    rejected(case, coverage_refresh=lambda *args, **kw: kw["current_graph"].coverage)


@pytest.mark.parametrize("mutation", ["source", "reason", "missing", "status"])
def test_coverage_owner_current_material_drift(case, mutation):
    complete(case)
    values = list(case.graph.coverage)
    if mutation == "missing":
        values.pop()
    else:
        updates = {
            "source": {"source": case.source.model_copy(update={"revision": 2})},
            "reason": {"reason": "changed owner boundary"},
            "status": {"status": "unknown", "reason": "not proven"},
        }[mutation]
        values[0] = values[0].model_copy(update=updates)
    rejected(case, coverage_refresh=lambda *a, **kw: tuple(values))


def test_never_promotes_unknown_from_a_callback(case):
    def callback(*args, **kw):
        values = list(kw["current_graph"].coverage)
        values[0] = Coverage(
            node=values[0].node, facet=values[0].facet, status="complete", source=case.source
        )
        return tuple(values)

    rejected(case, coverage_refresh=callback)


def test_owner_material_change_between_passes_even_if_visible_graph_same(case):
    def drift(count):
        if count == 1:
            case.state.epoch += 1
            case.state.views[case.root.identity] = {"other_material": "changed"}

    case.state.before_reader = drift
    rejected(case)


def test_same_call_owner_reads_change_between_passes(case):
    def drift(count):
        if count == 1:
            case.state.epoch += 1
            case.state.reads[case.root.identity] = [
                {"artifact_id": str(uuid4()), "expected_revision": 1}
            ]

    case.state.before_reader = drift
    rejected(case)


def test_21_unique_artifact_sources_remain_complete(case):
    case.state.reads[case.root.identity] = [
        {"artifact_id": str(uuid4()), "expected_revision": 1} for _ in range(20)
    ]
    result = run(case)
    assert len(result.required_source_read_set) == 21


def test_conflicting_fixed_revision_for_same_artifact_rejects(case):
    case.state.reads[case.root.identity] = [
        {"artifact_id": str(case.source.id), "expected_revision": 2}
    ]
    rejected(case)


def test_251_nodes_actual_bounded_bfs_rejects(case):
    case.state.links[case.root.identity] = [
        (Ref(id=uuid4(), revision=1, kind="part"), "fixed child") for _ in range(250)
    ]
    rejected(case)


def test_pending_domain_dependency_cannot_be_hidden_by_no_autoflush(case):
    from pdos_next.domain.builds.models import Build

    case.s.add(Build(id=uuid4(), tenant_id=case.ctx.tenant_id, product_id=case.scope.product_id))
    rejected(case)


def test_pending_product_business_mutation_rejects(case):
    row = Product(**case.state.product, lifecycle_epoch=1)
    make_transient_to_detached(row)
    case.s.add(row)
    row.name = "pending-name"
    rejected(case)


def test_product_lifecycle_only_watermark_does_not_self_invalidate(case):
    row = Product(**case.state.product, lifecycle_epoch=1)
    make_transient_to_detached(row)
    case.s.add(row)
    row.lifecycle_epoch = 2
    assert run(case).closure == case.expected


@pytest.mark.parametrize("mutation", ["ctx", "command", "graph", "expected", "runtime", "reader"])
def test_current_same_call_bindings_must_close_after_owner_io(case, mutation):
    once = [False]

    def drift(reader, ref):
        if once[0]:
            return
        once[0] = True
        if mutation == "ctx":
            object.__setattr__(case.ctx, "requester_id", uuid4())
        elif mutation == "command":
            case.command.payload["new"] = True
        elif mutation == "graph":
            object.__setattr__(case.graph, "nature", "synthetic")
        elif mutation == "expected":
            case.expected["dependency_epoch"] += 1
        elif mutation == "runtime":
            case.engine._pdos_change_store = object()
        else:
            reader.s = Session(bind=case.engine)

    case.state.in_load = drift
    with pytest.raises(DomainError):
        run(case)
    assert all(
        hook.__name__ == "_discard_direct_mutation_reads" for hook in case.s.dispatch.do_orm_execute
    )


def test_same_root_and_savepoint_required_after_callback(case):
    def callback(*args, **kw):
        case.s.begin_nested()
        return kw["current_graph"].coverage

    with pytest.raises(DomainError):
        run(case, coverage_refresh=callback)
    assert all(
        hook.__name__ == "_discard_direct_mutation_reads" for hook in case.s.dispatch.do_orm_execute
    )


def test_expired_graph_or_current_qualification_deadline(case):
    rejected(case, valid_until=datetime.now(UTC) - timedelta(seconds=1))


def test_real_clock_checked_after_last_owner_io(case):
    entered = []

    def callback(*args, **kw):
        entered.append(True)
        time.sleep(0.4)
        return kw["current_graph"].coverage

    rejected(
        case, valid_until=datetime.now(UTC) + timedelta(seconds=0.3), coverage_refresh=callback
    )
    assert entered


def proof(case):
    now = datetime.now(UTC)
    row = Confirmation(
        id=uuid4(),
        tenant_id=case.ctx.tenant_id,
        created_at=now,
        product_id=case.scope.product_id,
        actor_id=case.ctx.actor_id,
        subject_id=uuid4(),
        operation="change.order.approve",
        revision=1,
        token_hash="x" * 64,
        expires_at=now + timedelta(minutes=5),
        consumed=False,
        payload_digest="y" * 64,
        snapshot={"controlled": "immutable stored proof"},
    )
    make_transient_to_detached(row)
    case.s.add(row)
    row.consumed = True  # Already pending common False -> True; no DB IO.
    return row


def test_pending_loaded_confirmation_keeps_consumption_and_other_fields(case):
    row = proof(case)
    assert run(case).authority_attested is False
    assert row.consumed is True and row in case.s.dirty


@pytest.mark.parametrize("field", ["consumed", "snapshot", "token_hash", "expires_at"])
def test_nested_owner_cannot_reset_pending_confirmation(case, field):
    row = proof(case)

    def reset(reader, ref):
        if field == "consumed":
            row.consumed = False
        elif field == "snapshot":
            row.snapshot["changed"] = True
        elif field == "token_hash":
            row.token_hash = "z" * 64
        else:
            row.expires_at += timedelta(minutes=1)

    case.state.in_load = reset
    rejected(case)


def test_scoped_listener_fresh_owners_excludes_confirmation_and_cleans_up(case):
    previous = list(case.s.dispatch.do_orm_execute)
    with c._fresh_selects(case.s):
        listener = list(case.s.dispatch.do_orm_execute)[-1]
        for model, expected in [(Product, True), (Confirmation, False)]:
            options = {}
            state = SimpleNamespace(
                is_select=True,
                statement=select(model),
                update_execution_options=lambda options=options, **kw: options.update(kw),
            )
            listener(state)
            assert options == {"populate_existing": expected, "autoflush": False}
        assert case.s.autoflush is False
    assert list(case.s.dispatch.do_orm_execute) == previous
    assert case.s.autoflush is True


def test_listener_finally_cleanup_on_owner_exception(case):
    def broken(reader, ref):
        raise RuntimeError("explicit owner failure")

    case.state.in_load = broken
    with pytest.raises(RuntimeError):
        run(case)
    assert all(
        hook.__name__ == "_discard_direct_mutation_reads" for hook in case.s.dispatch.do_orm_execute
    )


def test_dedicated_clock_table_set_matches_archived_clock_contract():
    source = (
        Path(__file__).resolve().parents[3]
        / "server/migrations/archive/pre-s0/versions/0030_change_dependency_clock.py"
    )
    module = ast.parse(source.read_text())
    actual = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "DEPENDENCY_TABLES" for t in node.targets)
    )
    assert c.DEPENDENCY_TABLES == frozenset(actual) | {
        "field_feedback_versions", "field_feedback_currents"
    }
    assert len(actual) == 70
    assert (
        not {
            "change_graph_captures",
            "change_request_versions",
            "confirmations",
            "action_receipts",
            "audit_events",
            "outbox_events",
        }
        & c.DEPENDENCY_TABLES
    )
