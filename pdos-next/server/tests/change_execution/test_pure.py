from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from uuid import UUID as CategoryUUID

import pytest
from pydantic import ValidationError

from pdos_next.domain.change_control.ports import Authority, Invocation, Outcome
from pdos_next.domain.change_control.rules import compute_impact, digest
from pdos_next.domain.change_execution import adapters, graph, service
from pdos_next.domain.change_execution.schemas import (
    ChangeCreatePayload,
    GraphCaptureInput,
    ImpactComputePayload,
)
from pdos_next.errors import DomainError
from pdos_next.schemas.change_control.contracts import ChangeRequest, Ref, RequestCreate
from pdos_next.schemas.verification.contracts import Scope, SourceRef

AT = datetime(2026, 10, 2, 12, tzinfo=UTC)


def fixture():
    scope = Scope(tenant_id=uuid4(), product_id=uuid4(), project_id=uuid4())
    actor, identity = uuid4(), uuid4()
    source = SourceRef(
        id=uuid4(), revision=1, kind="artifact", position="line:1;quote_sha256:" + "a" * 64
    )
    refs = {
        kind: Ref(id=uuid4(), revision=1, kind=kind)
        for kind in (
            "issue",
            "engineering_configuration",
            "bom",
            "part",
            "manufacturing_configuration",
            "build",
            "sample",
            "test_run",
        )
    }
    refs["operation"] = Ref(
        id=refs["manufacturing_configuration"].id, revision=1, kind="operation", key="assembly"
    )
    refs["sop"] = Ref(
        id=refs["manufacturing_configuration"].id, revision=1, kind="sop", key="assembly"
    )
    links = {
        "issue": ("engineering_configuration",),
        "engineering_configuration": ("bom", "manufacturing_configuration", "build"),
        "bom": ("part", "engineering_configuration"),
        "manufacturing_configuration": ("operation",),
        "operation": ("sop",),
        "build": ("sample",),
        "sample": ("test_run",),
    }
    objects = {
        ref.identity: graph.OwnedObject(ref, kind, scope, actor, "product", {}, [], {}, True)
        for kind, ref in refs.items()
    }

    class Reader:
        target = graph.audience(scope.product_id, actor, "product")

        def __init__(self):
            self.scope, self.objects = scope, {}

        def resolve(self, ref):
            self.objects[ref.identity] = objects[ref.identity]
            return objects[ref.identity]

        def links(self, obj):
            return [(refs[kind], "actual-fixed-owner-link") for kind in links.get(obj.label, ())]

    reader = Reader()
    snapshot = graph.capture_graph(
        reader,
        identity=identity,
        roots=(refs["issue"],),
        captured_at=AT,
        expires_at=AT + timedelta(minutes=10),
        nature="synthetic",
        sources=(source,),
    )
    payload = ChangeCreatePayload(
        title="Fixed issue change",
        reason="Known failure needs proposal",
        roots=(refs["issue"],),
        references=(),
        sources=(source,),
        visibility="category",
    )
    return SimpleNamespace(
        scope=scope,
        actor=actor,
        source=source,
        refs=refs,
        reader=reader,
        snapshot=snapshot,
        payload=payload,
    )


def test_bounded_actual_paths_keep_all_eight_facets_unknown_and_no_orders():
    work = fixture()
    assessment = compute_impact(work.snapshot, 1)
    assert {row.node.ref.kind for row in assessment.known} >= {
        "part",
        "bom",
        "engineering_configuration",
        "manufacturing_configuration",
        "operation",
        "sop",
        "build",
        "sample",
        "test_run",
    }
    assert {unknown.facet for unknown in assessment.unknown} == set(graph.UNKNOWN_REASONS)
    assert all(c.status == "unknown" and c.source is None for c in work.snapshot.coverage)
    assert assessment.computed_at == work.snapshot.captured_at


def test_t0_adapter_stages_one_pure_mutation_without_confirmation_or_second_receipt():
    work = fixture()
    authority = Authority(
        scope=work.scope,
        actor_id=work.actor,
        requester_id=work.actor,
        actor_kind="human",
        audience=work.reader.target,
        roles=("engineering",),
        authorized=True,
        qualified=True,
        cancelled=False,
        now=AT,
    )
    parsed = RequestCreate.model_validate(work.payload.model_dump(exclude={"visibility"}))
    saved = []

    def save(mutation):
        saved.append(mutation)
        return Outcome(
            subject_id=mutation.change.id,
            revision=mutation.change.revision,
            status=mutation.change.status,
        )

    core = adapters.kernel(authority, None, work.reader, {digest(work.source)}, save=save)
    invocation = Invocation(
        command_id=uuid4(),
        operation="change.request.create",
        subject_id=uuid4(),
        expected_revision=0,
        semantic_digest=digest(parsed),
    )
    core.execute(object(), invocation, parsed.model_dump(mode="json"))
    assert len(saved) == 1 and saved[0].insert and saved[0].change.revision == 1
    assert saved[0].change.orders == () and saved[0].change.status == "draft"
    assert saved[0].change.history[0].command_id == invocation.command_id


def test_private_source_never_expands_product_audience_but_can_stay_private():
    work = fixture()
    private = graph.OwnedObject(
        work.refs["issue"], "issue", work.scope, work.actor, "private", {}, [], {}, True
    )
    with pytest.raises(DomainError) as error:
        graph.require_audience(work.reader.target, private)
    assert error.value.reason == "AUDIENCE_USE_FORBIDDEN"
    graph.require_audience(graph.audience(work.scope.product_id, work.actor, "private"), private)
    with pytest.raises(DomainError):
        graph.require_audience(graph.audience(work.scope.product_id, uuid4(), "private"), private)


def test_stable_create_identity_excludes_client_key_but_binds_scope_actor_and_audience():
    work = fixture()
    identity = service.stable_change_id(work.scope, work.actor, work.reader.target, work.payload)
    assert identity == service.stable_change_id(
        work.scope, work.actor, work.reader.target, work.payload
    )
    assert identity != service.stable_change_id(
        work.scope, uuid4(), work.reader.target, work.payload
    )
    assert identity != service.stable_change_id(
        work.scope,
        work.actor,
        graph.audience(work.scope.product_id, work.actor, "private"),
        work.payload,
    )
    other = work.scope.model_copy(update={"project_id": uuid4()})
    assert identity != service.stable_change_id(other, work.actor, work.reader.target, work.payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("change_id", str(uuid4())),
        ("project_id", str(uuid4())),
        ("qualified", True),
        ("nature", "real"),
        ("actor_id", str(uuid4())),
        ("complete", True),
    ],
)
def test_create_rejects_client_generated_identity_or_policy_fields(field, value):
    raw = fixture().payload.model_dump(mode="json")
    raw[field] = value
    with pytest.raises(ValidationError):
        ChangeCreatePayload.model_validate(raw)


@pytest.mark.parametrize("revision", [True, 1.0, "1", 0])
def test_public_fixed_reference_revision_is_strict(revision):
    raw = fixture().payload.model_dump(mode="json")
    raw["roots"][0]["revision"] = revision
    with pytest.raises(ValidationError):
        ChangeCreatePayload.model_validate(raw)


def test_create_requires_fixed_issue_and_capa_key_not_a_client_uuid_only():
    raw = fixture().payload.model_dump(mode="json")
    raw["roots"][0]["kind"] = "engineering_configuration"
    with pytest.raises(ValidationError):
        ChangeCreatePayload.model_validate(raw)


@pytest.mark.parametrize("kind,key", [("engineering_configuration", None), ("graph_snapshot", "x")])
def test_impact_requires_exact_saved_graph_ref(kind, key):
    with pytest.raises(ValidationError):
        ImpactComputePayload(
            change_id=uuid4(),
            expected_change_revision=1,
            snapshot={"id": uuid4(), "revision": 1, "kind": kind, "key": key},
        )


def test_capture_schema_has_no_roots_time_nature_or_policy_claims():
    raw = {
        "capture_key": "stable-capture-1",
        "change_id": str(uuid4()),
        "expected_change_revision": 1,
        "reason": "Read real fixed owner edges",
    }
    for key, value in (("roots", []), ("expires_at", AT.isoformat()), ("nature", "real")):
        with pytest.raises(ValidationError):
            GraphCaptureInput.model_validate({**raw, key: value})


@pytest.mark.parametrize("method", ["selection", "implementation", "effectivity", "verification"])
def test_unopened_fact_ports_are_explicitly_unavailable(method):
    work = fixture()
    with pytest.raises(DomainError) as error:
        getattr(adapters.Facts(work.reader, set()), method)(object())
    assert error.value.reason == "INTEGRATION_REQUIRED" and error.value.status == 503


def test_impact_does_not_turn_unknown_graph_into_approved_change():
    work = fixture()
    request = ChangeRequest(
        id=uuid4(),
        revision=1,
        scope=work.scope,
        audience=work.reader.target,
        requester_id=work.actor,
        title=work.payload.title,
        reason=work.payload.reason,
        roots=work.payload.roots,
        references=(),
        sources=work.payload.sources,
    )
    authority = Authority(
        scope=work.scope,
        actor_id=work.actor,
        requester_id=work.actor,
        actor_kind="human",
        audience=work.reader.target,
        roles=("quality",),
        authorized=True,
        qualified=True,
        cancelled=False,
        now=AT + timedelta(seconds=1),
    )
    core = adapters.kernel(authority, request, work.reader, {digest(work.source)}, work.snapshot)
    from pdos_next.schemas.change_control.contracts import ImpactCompute

    payload = ImpactCompute(snapshot=Ref(id=work.snapshot.id, revision=1, kind="graph_snapshot"))
    _, (after, _, _, _) = core._prepare(
        object(), authority, "change.impact.compute", request.id, 1, payload, None
    )
    assert after.status == "analysis" and after.orders == ()
    assert after.assessments[-1].unknown and request.assessments == ()


def test_runtime_revocation_after_owner_io_is_rejected(monkeypatch):
    work = fixture()

    class Reader:
        def resolve(self, ref):
            return work.reader.objects[ref.identity]

    monkeypatch.setattr(service, "OwnerReader", lambda *args: Reader())
    monkeypatch.setattr(service, "_issue_loader", lambda s: object())
    monkeypatch.setattr(service, "_evidence", lambda *args, **kwargs: ({}, False, set()))
    monkeypatch.setattr(service, "_authority", lambda *args, **kwargs: {"qualified": True})
    monkeypatch.setattr(service, "_runtime_stamp", lambda s: "revoked-then-restored-epoch")
    bound = SimpleNamespace(
        coverage=None,
        reader=work.reader,
        scope=work.scope,
        target=work.reader.target,
        reads=[],
        sources=(),
        purpose="fixed-purpose",
        authority={"qualified": True},
        source_basis={"evidence": {}},
        runtime_stamp="old-epoch",
    )
    with pytest.raises(DomainError) as error:
        service._refresh(
            object(), SimpleNamespace(), work.scope.product_id, "change.impact.compute", bound
        )
    assert error.value.reason == "SOURCE_STALE"


def test_io_refresh_checks_sources_after_owner_io_not_before(monkeypatch):
    work = fixture()
    order = []

    class Reader:
        def resolve(self, ref):
            order.append("owner")
            return work.reader.objects[ref.identity]

    monkeypatch.setattr(service, "OwnerReader", lambda *args: Reader())
    monkeypatch.setattr(service, "_issue_loader", lambda s: object())

    def evidence(*args, **kwargs):
        order.append("source")
        return {}, False, set()

    monkeypatch.setattr(service, "_evidence", evidence)
    monkeypatch.setattr(service, "_authority", lambda *a, **k: order.append("authority") or {})
    monkeypatch.setattr(service, "_runtime_stamp", lambda s: "stable")
    bound = SimpleNamespace(
        coverage=None,
        reader=work.reader,
        scope=work.scope,
        target=work.reader.target,
        reads=[],
        sources=(),
        purpose="purpose",
        authority={},
        source_basis={"evidence": {}},
        runtime_stamp="stable",
    )
    service._refresh(
        object(), SimpleNamespace(), work.scope.product_id, "change.impact.compute", bound
    )
    assert order.index("source") > max(i for i, value in enumerate(order) if value == "owner")
    assert order[-1] == "authority"


@pytest.mark.parametrize("kind", ["build", "sample"])
def test_current_run_discovery_joins_exact_pointer_and_keeps_fixed_failure_edges(kind):
    from sqlalchemy.sql import visitors
    from sqlalchemy.sql.elements import BinaryExpression

    from pdos_next.domain.build_execution.models import SampleUnit
    from pdos_next.domain.verification_launch.models import VerificationRunVersion

    work = fixture()
    build_id, run_id, sample_id = uuid4(), uuid4(), uuid4()
    pointed = SimpleNamespace(
        id=uuid4(), run_id=run_id, revision=3, run_snapshot={"samples": [{"id": str(sample_id)}]}
    )
    queries = []

    class Session:
        def scalars(self, statement):
            if statement.column_descriptions[0]["entity"] is SampleUnit:
                return SimpleNamespace(all=lambda: [])
            assert statement.column_descriptions[0]["entity"] is VerificationRunVersion
            queries.append(statement)
            join = statement.get_final_froms()[0]
            actual = {
                ((v.left.table.name, v.left.name), (v.right.table.name, v.right.name))
                for v in visitors.iterate(join.onclause)
                if isinstance(v, BinaryExpression)
            }
            assert actual == {
                (("verification_current_runs", left), ("verification_run_versions", right))
                for left, right in (
                    ("tenant_id", "tenant_id"),
                    ("product_id", "product_id"),
                    ("request_id", "request_id"),
                    ("run_id", "run_id"),
                    ("run_version_id", "id"),
                    ("run_revision", "revision"),
                )
            }
            scoped = {v.left.name: v.right.value for v in statement._where_criteria}
            assert scoped == {
                "tenant_id": work.scope.tenant_id,
                "product_id": work.scope.product_id,
                "build_id": build_id,
            }
            # There is deliberately no status filter: a current planned Run
            # must be discovered and then fail its real owner proof.
            assert "planned" not in statement.compile().params.values()
            return SimpleNamespace(all=lambda: [pointed])

    reader = graph.OwnerReader(
        Session(),
        SimpleNamespace(tenant_id=work.scope.tenant_id),
        work.scope.product_id,
        work.scope,
        work.reader.target,
        None,
    )
    view = (
        {
            "engineering": {"id": uuid4(), "revision": 1},
            "manufacturing": {"id": uuid4(), "revision": 1},
        }
        if kind == "build"
        else {"build_id": str(build_id)}
    )
    obj = graph.OwnedObject(
        Ref(id=build_id if kind == "build" else sample_id, revision=1, kind=kind),
        kind,
        work.scope,
        work.actor,
        "product",
        view,
        [],
        {},
        True,
    )
    discovered = {ref for ref, _ in reader.links(obj) if ref.kind == "test_run"}
    assert discovered == {Ref(id=run_id, revision=3, kind="test_run")}
    assert len(queries) == 1
    historical = graph.OwnedObject(
        work.refs["issue"],
        "issue",
        work.scope,
        work.actor,
        "product",
        {
            "failures": [
                {
                    "build": {"id": build_id, "revision": 1},
                    "sample": {"id": sample_id, "revision": 1},
                    "run": {"id": run_id, "revision": 2},
                }
            ]
        },
        [],
        {},
        True,
    )
    assert Ref(id=run_id, revision=2, kind="test_run") in {
        ref for ref, _ in reader.links(historical)
    }
    assert len(queries) == 1


def test_current_planned_run_is_not_given_retained_execution_or_plan_port(monkeypatch):
    from sqlalchemy.orm import Session

    from pdos_next.domain.test_resources import retained
    from pdos_next.service import Context

    work = fixture()
    run_ref = Ref(id=uuid4(), revision=1, kind="test_run")
    row = SimpleNamespace(
        owner_id=work.actor,
        visibility="category",
        revision=1,
        status="planned",
        project_id=work.scope.project_id,
        run_snapshot={"status": "planned"},
        required_source_read_set=[],
    )
    # The actual retained reader now requires a live caller UOW before its
    # planned-Run guard. Only the SQL/authority owners remain substitutes.
    session = Session(bind=SimpleNamespace())
    session.begin()
    monkeypatch.setattr(session, "scalar", lambda query: row)
    monkeypatch.setattr(retained, "_human", lambda *args, **kwargs: None)
    monkeypatch.setattr(retained, "_caller", lambda *args, **kwargs: ((), AT))
    monkeypatch.setattr(retained, "_runtime", lambda *args: ())
    monkeypatch.setattr(
        retained.launch, "_snapshot", lambda value: (SimpleNamespace(status="planned"), None)
    )
    reader = graph.OwnerReader(
        session,
        Context(
            work.scope.tenant_id, work.actor, work.actor, category_id=CategoryUUID(int=1000000)
        ),
        work.scope.product_id,
        work.scope,
        work.reader.target,
        None,
    )
    selected = reader.resolve(run_ref)
    assert selected.current is False
    assert selected.view["owner_port"] == "plan_not_integrated"
    assert selected.view["reason_codes"] == ["RUN_NOT_STARTED"]
    assert selected.source_basis["occupancy"] == selected.source_basis["sample_usage"] == []
    with pytest.raises(DomainError) as error:
        graph.capture_graph(
            reader,
            identity=uuid4(),
            roots=(run_ref,),
            captured_at=AT,
            expires_at=AT + timedelta(minutes=10),
            nature="synthetic",
            sources=(work.source,),
        )
    session.close()
    assert error.value.reason == "RECHECK_REQUIRED"
    assert "计划所有者来源端口未接入" in error.value.message


def test_run_owner_basis_ignores_only_information_clock_and_keeps_safety_effects(monkeypatch):
    from copy import deepcopy

    from pdos_next.domain.test_resources import retained

    work = fixture()
    run_ref = Ref(id=uuid4(), revision=3, kind="test_run")
    row = SimpleNamespace(
        owner_id=work.actor,
        visibility="category",
        revision=3,
        status="results_pending",
        run_snapshot={"status": "results_pending"},
        required_source_read_set=[],
    )
    proof = {
        "current": True,
        "checked_at": AT.isoformat(),
        "execution_window_elapsed": False,
        "reason_codes": [],
        "source_basis": {"security_epoch": 7},
        "facts_revision": "fixed",
        "original_start_intent": "same-intent",
        "occupancy": [{"id": "fixed-occupancy"}],
        "sample_usage": [{"id": "fixed-usage", "epoch": 1}],
    }
    later = {
        **deepcopy(proof),
        "checked_at": (AT + timedelta(hours=1)).isoformat(),
        "execution_window_elapsed": True,
    }
    changed = {**deepcopy(later), "source_basis": {"security_epoch": 8}}
    snapshots = iter((proof, later, changed))
    monkeypatch.setattr(
        retained, "inspect_retained_execution", lambda *args, **kwargs: next(snapshots)
    )
    reader = graph.OwnerReader(
        SimpleNamespace(scalar=lambda query: row),
        SimpleNamespace(tenant_id=work.scope.tenant_id, requester_id=work.actor),
        work.scope.product_id,
        work.scope,
        work.reader.target,
        None,
    )
    before = reader._load(run_ref)[3]
    after = reader._load(run_ref)[3]
    assert before == after
    assert set(before) == set(proof) - {"checked_at", "execution_window_elapsed"}
    assert before["occupancy"] == proof["occupancy"]
    assert before["sample_usage"] == proof["sample_usage"]
    assert digest(before) != digest(reader._load(run_ref)[3])


def issue_owner_fixture():
    """One explicit phase's synthetic fixed owner, never a positive DB proof."""
    work = fixture()
    logical_id, capa_id = work.refs["issue"].id, uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        issue_id=logical_id,
        tenant_id=work.scope.tenant_id,
        product_id=work.scope.product_id,
        project_id=work.scope.project_id,
        revision=1,
        owner_id=work.actor,
        visibility="category",
        source_basis={"sources": [{"security_epoch": 7}]},
    )
    state = {"calls": [], "policy_epoch": 1, "source_status": "current"}

    def loader(s, ctx, pid, identity, revision):
        assert pid == work.scope.product_id and identity == logical_id and revision == 1
        state["calls"].append((identity, revision))
        return row, {
            "issue_id": str(logical_id),
            "revision": 1,
            "purpose": "same-fixed-purpose",
            "issue": {"id": str(logical_id), "capa": {"id": str(capa_id)}},
            "source_status": state["source_status"],
            "required_source_read_set": [],
            "policy": {"facts_revision": digest(state["policy_epoch"])},
        }

    def reader():
        return graph.OwnerReader(
            object(),
            SimpleNamespace(tenant_id=work.scope.tenant_id, requester_id=work.actor),
            work.scope.product_id,
            work.scope,
            work.reader.target,
            loader,
        )

    return SimpleNamespace(
        work=work,
        row=row,
        state=state,
        loader=loader,
        reader=reader,
        issue=work.refs["issue"],
        capa=Ref(id=logical_id, revision=1, kind="capa", key=str(capa_id)),
    )


def test_one_reader_shares_exact_issue_wrapper_but_fresh_reader_reloads():
    host = issue_owner_fixture()
    first = host.reader()
    issue, capa = first.resolve(host.issue), first.resolve(host.capa)
    assert host.state["calls"] == [(host.issue.id, 1)]
    assert issue.view["capa"] == capa.view["selected_capa"]
    assert issue.source_basis == capa.source_basis
    assert "selected_capa" not in issue.view
    fresh = host.reader()
    assert fresh.resolve(host.issue).source_basis == issue.source_basis
    fresh.resolve(host.capa)
    assert host.state["calls"] == [(host.issue.id, 1), (host.issue.id, 1)]


@pytest.mark.parametrize("kind", ["issue", "capa"])
def test_memo_hit_still_rejects_wrong_issue_or_capa_key(kind):
    host = issue_owner_fixture()
    reader = host.reader()
    reader.resolve(host.issue)
    wrong = Ref(id=host.issue.id, revision=1, kind=kind, key=str(uuid4()))
    with pytest.raises(DomainError) as error:
        reader.resolve(wrong)
    assert error.value.reason == "FIXED_REFERENCE_MISMATCH"
    assert len(host.state["calls"]) == 1
    assert reader.resolve(host.capa).current is True


def test_new_seed_call_rechecks_same_issue_capa_after_local_dedup(monkeypatch):
    host = issue_owner_fixture()
    monkeypatch.setattr(service, "_issue_loader", lambda s: host.loader)
    ctx = SimpleNamespace(tenant_id=host.work.scope.tenant_id)
    refs = (host.issue, host.capa)
    assert service._seed(object(), ctx, host.work.scope.product_id, refs) == (
        host.work.scope,
        "same-fixed-purpose",
    )
    assert len(host.state["calls"]) == 1
    service._seed(object(), ctx, host.work.scope.product_id, refs)
    assert len(host.state["calls"]) == 2


def test_seed_local_memo_does_not_allow_another_issue_project(monkeypatch):
    host = issue_owner_fixture()
    another = Ref(id=uuid4(), revision=1, kind="issue")

    def loader(s, ctx, pid, identity, revision):
        if identity == host.issue.id:
            return host.loader(s, ctx, pid, identity, revision)
        return SimpleNamespace(**{**vars(host.row), "project_id": uuid4()}), {
            "issue_id": str(another.id),
            "revision": another.revision,
            "purpose": "same-fixed-purpose",
        }

    monkeypatch.setattr(service, "_issue_loader", lambda s: loader)
    with pytest.raises(DomainError) as error:
        service._seed(
            object(),
            SimpleNamespace(tenant_id=host.work.scope.tenant_id),
            host.work.scope.product_id,
            (host.issue, host.capa, another),
        )
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_default_change_issue_loader_is_lean_and_explicit_host_port_wins():
    from pdos_next.domain.quality_execution.service import get_issue_for_change

    engine = SimpleNamespace()
    session = SimpleNamespace(get_bind=lambda: engine)
    assert service._issue_loader(session) is get_issue_for_change

    def configured(*args):
        return None

    service.configure_issue_loader(engine, configured)
    assert service._issue_loader(session) is configured


@pytest.mark.parametrize("change", ["policy_epoch", "source_status"])
def test_post_io_fresh_reader_rejects_policy_aba_or_invalid_owner(monkeypatch, change):
    host = issue_owner_fixture()
    first = host.reader()
    first.resolve(host.issue)
    first.resolve(host.capa)
    if change == "policy_epoch":
        host.state["policy_epoch"] = 3  # Revoke and restore is a new positive epoch.
    else:
        host.state["source_status"] = "needs_recheck"
    monkeypatch.setattr(service, "_issue_loader", lambda s: host.loader)
    bound = SimpleNamespace(
        coverage=None,
        source_basis={},
        reader=first,
        scope=host.work.scope,
        target=host.work.reader.target,
    )
    with pytest.raises(DomainError) as error:
        service._refresh(
            object(),
            SimpleNamespace(tenant_id=host.work.scope.tenant_id),
            host.work.scope.product_id,
            "change.impact.compute",
            bound,
        )
    assert error.value.reason == "SOURCE_STALE"
    assert len(host.state["calls"]) == 2


def lean_quality_fixture(monkeypatch):
    from quality_issues.helpers import fixed_run

    from pdos_next.domain.quality_execution import service as quality
    from pdos_next.domain.quality_execution.direct import issue_refs
    from pdos_next.domain.quality_issues.ports import VerifiedRun
    from pdos_next.domain.quality_issues.rules import failure_ref
    from pdos_next.schemas.quality_issues.contracts import Issue
    from pdos_next.service import digest as saved_digest

    run = fixed_run()
    verified = VerifiedRun(run=run, nature="synthetic")
    failure = failure_ref(verified, run.measurements[0].id)
    issue = Issue(
        id=uuid4(),
        revision=1,
        scope=run.scope,
        audience=(f"product:{run.scope.product_id}",),
        title="Actual fixed synthetic failure",
        failures=(failure,),
    )
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=run.scope.tenant_id,
        product_id=run.scope.product_id,
        project_id=run.scope.project_id,
        issue_id=issue.id,
        revision=1,
        status="open",
        purpose="same-fixed-purpose",
        visibility="category",
        owner_id=failure.executor_id,
        issue_snapshot=issue.model_dump(mode="json"),
        snapshot_sha256=saved_digest(issue.model_dump(mode="json")),
        required_source_read_set=[{"artifact_id": str(uuid4()), "expected_revision": 1}],
        source_basis={"artifact_sources": []},
        sources=(),
        created_at=AT,
        reason="Fixed synthetic evidence",
    )
    policy_read = {"artifact_id": str(uuid4()), "expected_revision": 1}
    calls = {"source": 0, "failure": 0, "policy": 0, "authority": []}

    def sources(*args):
        calls["source"] += 1
        return [], False

    def bridge(s, ctx, pid, actual_issue, actual_failure, *, purpose):
        calls["failure"] += 1
        assert pid == row.product_id and actual_issue == issue and actual_failure == failure
        assert purpose == row.purpose
        return SimpleNamespace(
            measurement=run.measurements[0].model_dump(mode="json"),
            projection_id=uuid4(),
            basis_sha256="a" * 64,
            required_source_read_set=(),
        )

    def policy(*args):
        calls["policy"] += 1
        return {"facts_revision": "b" * 64, "required_source_read_set": [policy_read]}

    def authority(*args, **kwargs):
        calls["authority"].append(args[4])
        return {"authorized": True, "qualified": True, "required_source_read_set": []}

    from pdos_next import quality_result_bridge, source_current

    monkeypatch.setattr(source_current, "direct_source_basis", sources)
    monkeypatch.setattr(quality_result_bridge, "direct_issue_failure", bridge)
    monkeypatch.setattr(quality.policy, "assess", policy)
    monkeypatch.setattr(quality.professional, "assess", authority)
    return SimpleNamespace(
        quality=quality,
        row=row,
        issue=issue,
        calls=calls,
        policy_read=policy_read,
        direct_reads=[
            {"artifact_id": str(r.id), "expected_revision": r.revision} for r in issue_refs(issue)
        ],
        source_current=source_current,
        failure_bridge=quality_result_bridge,
    )


def test_lean_issue_keeps_fixed_failure_risk_policy_and_reads_without_unrelated_caps(monkeypatch):
    host = lean_quality_fixture(monkeypatch)
    full = host.quality._view(object(), object(), host.row.product_id, host.row, current=True)
    lean = host.quality._view(
        object(), object(), host.row.product_id, host.row, current=True, assess_capabilities=False
    )
    assert host.calls["source"] == host.calls["failure"] == host.calls["policy"] == 2
    assert set(host.calls["authority"]) == set(host.quality.PAYLOADS) - {"quality.issue.create"}
    assert len(host.calls["authority"]) == 4
    assert lean.issue == full.issue == host.issue
    assert lean.source_status == "current" and lean.is_current
    assert lean.failures[0].failure == full.failures[0].failure
    assert lean.failures[0].measurement == full.failures[0].measurement
    assert lean.policy == full.policy
    assert not any(lean.capabilities.values()) and lean.authority == {}
    assert {r.artifact_id for r in lean.required_source_read_set} == {
        UUID(r["artifact_id"]) for r in (*host.direct_reads, host.policy_read)
    }


@pytest.mark.parametrize("port", ["source", "failure", "policy"])
def test_lean_issue_does_not_turn_unavailable_required_proof_current(monkeypatch, port):
    host = lean_quality_fixture(monkeypatch)

    def rejected(*args, **kwargs):
        raise DomainError("RECHECK_REQUIRED", "Required synthetic proof is no longer current")

    if port == "source":
        monkeypatch.setattr(host.source_current, "direct_source_basis", rejected)
    elif port == "failure":
        monkeypatch.setattr(host.failure_bridge, "direct_issue_failure", rejected)
    else:
        monkeypatch.setattr(host.quality.policy, "assess", rejected)
    view = host.quality._view(
        object(), object(), host.row.product_id, host.row, current=True, assess_capabilities=False
    )
    assert view.source_status == "needs_recheck"
    assert not any(view.capabilities.values()) and view.authority == {}


def test_get_issue_for_change_keeps_fixed_row_private_acl_and_real_current_pointer(monkeypatch):
    from pdos_next.domain.quality_execution.models import QualityIssueCurrent

    host = lean_quality_fixture(monkeypatch)
    ctx = SimpleNamespace(
        tenant_id=host.row.tenant_id,
        requester_id=host.row.owner_id,
        actor_id=host.row.owner_id,
        run_id=None,
    )
    guards = []
    monkeypatch.setattr(
        host.quality, "_human", lambda *args, **kwargs: guards.append(kwargs["write"])
    )

    class Session:
        def __init__(self):
            self.pointed = host.row.id

        def scalar(self, query):
            if query.column_descriptions[0]["entity"] is QualityIssueCurrent:
                assert {v.left.name: v.right.value for v in query._where_criteria} == {
                    "tenant_id": ctx.tenant_id,
                    "product_id": host.row.product_id,
                    "issue_id": host.row.issue_id,
                }
                return SimpleNamespace(issue_version_id=self.pointed, issue_revision=1)
            return host.row

    session = Session()
    row, view = host.quality.get_issue_for_change(
        session, ctx, host.row.product_id, host.row.issue_id, 1, write=True
    )
    assert row is host.row and view.is_current and view.source_status == "current"
    session.pointed = uuid4()
    _, historical = host.quality.get_issue_for_change(
        session, ctx, host.row.product_id, host.row.issue_id, 1
    )
    assert not historical.is_current and historical.source_status == "not_evaluated_historical"
    assert host.calls["failure"] == host.calls["policy"] == 1
    assert guards == [True, False]
    host.row.visibility, host.row.owner_id = "private", uuid4()
    with pytest.raises(DomainError) as error:
        host.quality.get_issue_for_change(session, ctx, host.row.product_id, host.row.issue_id, 1)
    assert error.value.reason == "FORBIDDEN_SCOPE"


def test_capture_expiry_still_rejects_exact_boundary_before_any_memo_or_owner_read(monkeypatch):
    monkeypatch.setattr(service, "now", lambda: AT)
    capture = SimpleNamespace(expires_at=AT)
    with pytest.raises(DomainError) as error:
        service._capture_valid(
            object(), object(), uuid4(), SimpleNamespace(capture=capture, graph=None)
        )
    assert error.value.reason == "GRAPH_CAPTURE_EXPIRED"


def test_create_payload_keeps_more_than_twenty_exact_sources():
    work = fixture()
    sources = tuple(work.source.model_copy(update={"id": uuid4()}) for _ in range(21))
    value = ChangeCreatePayload.model_validate({**work.payload.model_dump(), "sources": sources})
    assert value.sources == sources
