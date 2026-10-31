"""Native current-project projections and bound egress; no DB/provider/egress."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, date, datetime
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import pytest

from pdos_next.agent_kernel import project_current_context as facts
from pdos_next.agent_kernel.context_projection import combine_contracts, project
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.types import RunScope
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.projects.models import PlanRevision, Project
from pdos_next.domain.work_management.models import ProjectStatusUpdate
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Principal
from pdos_next.service import Context


class Reading:
    def __init__(self):
        self.scope = RunScope(*(uuid4() for _ in range(7)), project_id=uuid4(),
                              data_categories=frozenset({"internal"}))
        self.ctx = Context(self.scope.tenant_id, self.scope.requester_id, self.scope.requester_id,
                           category_id=self.scope.category_id)
        self.info = {"scope": (self.ctx.tenant_id, self.ctx.actor_id,
                              self.ctx.requester_id, self.ctx.category_id)}
        self.project = NS(id=self.scope.project_id, tenant_id=self.scope.tenant_id,
                          category_id=self.scope.category_id, product_id=self.scope.product_id,
                          revision=3, visibility="category", current_plan_id=None)
        self.product = NS(visibility="category")
        self.definition = NS(id=uuid4(), revision=2, tenant_id=self.scope.tenant_id,
                             category_id=self.scope.category_id, product_id=self.scope.product_id)
        self.rows, self.open_items, self.queries = {}, [], []
        fields = asdict(self.scope)
        fields["id"] = fields.pop("run_id")
        self.run = NS(**fields, state="running", reverted_at=None, versions={}, read_sources=[])
        self.rows[AgentRun, self.run.id] = self.run
        self.rows[Project, self.project.id] = self.project
        self.rows[DefinitionRevision, self.definition.id] = self.definition
        self.rows[Principal, self.run.requester_id] = NS(kind="human", active=True)

    def scalar(self, statement):
        assert "transaction_timestamp()" in str(statement)
        return datetime(2026, 10, 29, 10, tzinfo=UTC)

    def execute(self, statement):
        assert "project_work_task_heads" in str(statement)
        return NS(all=lambda: [])

    def scalars(self, statement):
        self.queries.append(statement)
        assert statement.column_descriptions[0]["entity"] is facts.ProjectOpenItem
        return self.open_items

    def get(self, model, identity):
        return self.rows.get((model, identity))


def native(project, *, state="UNKNOWN"):
    stage = {"id": str(uuid4()), "key": "evt", "name": "EVT", "rules": ["engineering"]}
    check = {"key": "engineering", "label": "工程条件", "state": state,
             "detail": "规则结果与专业签核分别核对", "assessment": {
                 "blocked": ["TEST_FAILED"] if state == "BLOCKED" else [],
                 "unknown": ["TEST_NOT_RECORDED"] if state == "UNKNOWN" else [],
                 "checks": [{"key": "test", "state": "blocked" if state == "BLOCKED"
                             else "unknown", "detail": "固定测试结果尚未满足条件",
                             "sources": [{"quote": "RAW_PACKAGE_MARKER"}]}],
             }, "decisions": []}
    return {"revision": 4, "current_stage": stage,
            "stages": [{**stage, "status": "current"},
                       {"id": str(uuid4()), "key": "dvt", "name": "DVT", "status": "upcoming"}],
            "gate": {"stage_id": stage["id"], "state": state, "checks": [check],
                     "review_current": False, "required_source_read_set": [],
                     "release": None, "omitted_payload": "RAW_PACKAGE_MARKER"},
            "next_gate": {"stage_id": str(uuid4()), "state": "UNKNOWN", "checks": [],
                          "required_source_read_set": []},
            "timeline": {"task_key": "evt-exit", "baseline": {"latest_finish": "2026-10-30"},
                         "forecast": {"latest_finish": "2026-11-02", "estimate": "RAW_PLAN"},
                         "actual": None, "commitments": []},
            "history": [{"id": str(uuid4()), "revision": 4, "receipt_id": str(uuid4())}],
            "completed": False, "commitments": [], "health": {"state": "RAW_HEALTH"},
            "bindings": {"do_not_copy": "RAW_BINDING"}}


@pytest.fixture
def reading(monkeypatch):
    value = Reading()
    value.native = native(value.project)
    value.update, value.verified, value.native_reads = None, [], []
    monkeypatch.setattr(facts, "latest_updates", lambda *_: {
        value.project.id: value.update,
    } if value.update else {})

    def governance(session, ctx, pid, identity):
        value.native_reads.append((session, ctx, pid, identity))
        return value.native

    monkeypatch.setattr(facts.governance, "view", governance)
    monkeypatch.setattr(facts.governance, "_project", lambda *_: (
        value.project, None,
        {"id": str(value.definition.id), "revision": value.definition.revision},
    ))
    monkeypatch.setattr(facts, "require_access", lambda *_args: value.product)
    monkeypatch.setattr(facts, "sources_current", lambda *_args: value.verified.append(_args))
    monkeypatch.setattr(facts, "require_project", lambda *_args: value.project)
    monkeypatch.setattr(facts, "source_privacy", lambda *_: "shared")
    monkeypatch.setattr(facts, "source_for", lambda session, _ctx, _pid, identity, revision=None: (
        session.get(Artifact, identity)
    ))
    from pdos_next.domain.project_governance.models import GovernanceEvent

    original = value.native["history"][-1]
    value.rows[GovernanceEvent, UUID(original["id"])] = NS(
        tenant_id=value.scope.tenant_id, category_id=value.scope.category_id,
        product_id=value.scope.product_id, project_id=value.scope.project_id,
    )
    return value


def status(reading):
    row = NS(id=uuid4(), revision=1, receipt_id=uuid4(), reads=[], source_basis={"artifacts": []},
             tenant_id=reading.scope.tenant_id, category_id=reading.scope.category_id,
             product_id=reading.scope.product_id, project_id=reading.scope.project_id)
    reading.rows[ProjectStatusUpdate, row.id] = row
    reading.update = {"id": str(row.id), "revision": row.revision,
                      "actor": {"id": str(uuid4()), "name": "具名更新人"},
                      "fact_summary": "工程验证尚缺结果", "next_steps": "等待品质补录",
                      "created_at": "2026-10-29T10:00:00+00:00", "receipt_id": str(row.receipt_id)}
    return row


@pytest.mark.parametrize("state", ["BLOCKED", "UNKNOWN", "READY"])
def test_actual_native_gate_states_reasons_and_dates_are_preserved_without_package_body(
    reading, state,
):
    f = reading
    f.native["gate"]["state"] = state
    f.native["gate"]["checks"][0]["state"] = state
    value, proof, private, categories = facts._collect(f, f.ctx, f.project)
    assert value.governance.gate.state == value.governance.gate.checks[0].state == state
    assert value.governance.current_stage.key == "evt"
    assert value.governance.next_gate.state == "UNKNOWN"
    assert value.governance.timeline.baseline.latest_finish == "2026-10-30"
    assert value.governance.timeline.forecast.latest_finish == "2026-11-02"
    assert value.governance.timeline.actual is None
    assert value.plan.state == "not_created" and value.named_status.state == "not_recorded"
    assert "RAW_" not in str(value.model_dump())
    assert not proof and not private and categories == {"internal"}
    assert f.native_reads == [(f, f.ctx, f.project.product_id, f.project.id)]


def test_named_update_reuses_actual_author_and_source_check_never_project_owner(reading):
    row = status(reading)
    value, *_ = facts._collect(reading, reading.ctx, reading.project)
    assert value.named_status.state == "available"
    assert value.named_status.actor_id == reading.update["actor"]["id"]
    assert value.named_status.reference.receipt_id == str(row.receipt_id)
    assert value.named_status.fact_summary == "工程验证尚缺结果"
    assert reading.verified[0] == (
        reading, reading.ctx, reading.project.product_id, row.source_basis,
    )


def test_native_release_header_decision_and_condition_keep_fixed_identity_without_bodies(reading):
    gate = reading.native["gate"]
    release = {"id": str(uuid4()), "revision": 3, "receipt_id": str(uuid4()),
               "package": {"raw": "RAW_PACKAGE"}, "authority": "RAW_AUTHORITY"}
    decision = {"id": str(uuid4()), "revision": 2, "receipt_id": str(uuid4()),
                "authority": {"evidence": "RAW_SIGNER_BODY"}}
    condition = {"id": str(uuid4()), "revision": 1}
    gate["release"] = release
    gate["checks"][0]["decisions"] = [decision]
    gate["checks"][0]["assessment"]["conditions"] = [condition]
    value, *_ = facts._collect(reading, reading.ctx, reading.project)
    projected = value.governance.gate
    assert projected.release.id == release["id"] and projected.release.revision == 3
    assert projected.checks[0].decisions[0].receipt_id == decision["receipt_id"]
    assert projected.checks[0].conditions[0].id == condition["id"]
    assert {"release_package", "release_decision", "release_exception"} <= {
        ref.kind for ref in value.references
    }
    assert "RAW_" not in str(value.model_dump())


def test_missing_named_source_is_partial_and_never_discloses_old_summary(reading, monkeypatch):
    status(reading)

    def denied(*_):
        raise DomainError("SOURCE_UNAVAILABLE", "source revoked", 403)

    monkeypatch.setattr(facts, "sources_current", denied)
    value, *_ = facts._collect(reading, reading.ctx, reading.project)
    assert value.named_status.state == "unavailable" and value.named_status.fact_summary is None
    assert not value.complete and value.missing == ["named_status_sources_unavailable"]
    assert "工程验证尚缺结果" not in str(value.model_dump())
    assert value.governance.current_stage.key == "evt"


def test_metadata_distinguishes_known_no_records_from_unavailable_pointers(reading, monkeypatch):
    reading.native.update(stages=[], current_stage=None, history=[], gate=None, next_gate=None)
    before = facts.bind(reading, reading.ctx, reading.project)
    empty = before["metadata_snapshot"]
    assert empty["named_status"] is empty["governance"] is None
    assert empty["named_status_known"] is empty["governance_known"] is True
    value = facts._collect(reading, reading.ctx, reading.project)[0]
    assert before["basis_digest"] == facts._basis(value)
    assert "named_status_known" not in str(value.model_dump())
    assert "governance_known" not in str(value.model_dump())

    def unavailable(*_):
        raise DomainError("SOURCE_UNAVAILABLE", "当前来源未能读取。", 403)

    status(reading)
    monkeypatch.setattr(facts, "sources_current", unavailable)
    monkeypatch.setattr(facts.governance, "view", unavailable)
    failed = facts.bind(reading, reading.ctx, reading.project)["metadata_snapshot"]
    assert failed["named_status"] is failed["governance"] is None
    assert failed["named_status_known"] is failed["governance_known"] is False


def test_metadata_first_named_record_changes_known_empty_without_project_revision(reading):
    before = facts.bind(reading, reading.ctx, reading.project)["metadata_snapshot"]
    row = status(reading)
    after = facts.bind(reading, reading.ctx, reading.project)["metadata_snapshot"]
    assert before["project_revision"] == after["project_revision"]
    assert before["named_status_known"] is after["named_status_known"] is True
    assert before["named_status"] is None
    assert after["named_status"] == {"id": str(row.id), "revision": row.revision}


def test_metadata_available_pointer_known_flags_do_not_change_legacy_v2_recheck(reading):
    status(reading)
    bound = facts.bind(reading, reading.ctx, reading.project)
    metadata = bound["metadata_snapshot"]
    assert metadata["named_status"] and metadata["governance"]
    assert metadata.pop("named_status_known") is metadata.pop("governance_known") is True
    # Existing v2 snapshots never had these optional server metadata markers.
    reading.run.versions[facts.KEY] = deepcopy(bound)
    assert facts._basis(facts._current(reading, reading.ctx, reading.run)) == bound["basis_digest"]
    reading.update = None
    reading.native.update(stages=[], current_stage=None, history=[], gate=None, next_gate=None)
    empty = facts.bind(reading, reading.ctx, reading.project)
    empty["metadata_snapshot"].pop("named_status_known")
    empty["metadata_snapshot"].pop("governance_known")
    reading.run.versions[facts.KEY] = empty
    assert facts._basis(facts._current(reading, reading.ctx, reading.run)) == empty["basis_digest"]


def test_plan_pointer_and_bounded_open_items_preserve_unknown_and_actual_owner(reading):
    f = reading
    identity = f.project.current_plan_id = uuid4()
    f.rows[PlanRevision, identity] = NS(
        id=identity, tenant_id=f.ctx.tenant_id, category_id=f.ctx.category_id,
        product_id=f.project.product_id, project_id=f.project.id,
        revision=2, status="applied", forecast={"earliest_finish": None, "latest_finish": None},
    )
    owner = uuid4()
    f.open_items = [NS(id=uuid4(), kind="risk", title="待确认工况", owner_id=owner,
                       due_date=date(2026, 11, 3), status="open") for _ in range(facts.LIMIT + 1)]
    value, *_ = facts._collect(f, f.ctx, f.project)
    assert value.plan.state == "available" and value.plan.reference.revision == 2
    assert value.plan.latest_finish is value.plan.earliest_finish is None
    assert len(value.open_items) == facts.LIMIT and value.open_items_has_more
    assert all(item.owner_id == str(owner) for item in value.open_items)
    assert not value.complete and "open_items_truncated" in value.missing
    sql = str(f.queries[0])
    params = f.queries[0].compile().params
    assert all(name in sql for name in (
        "tenant_id =", "category_id =", "product_id =", "project_id =",
    ))
    assert facts.LIMIT + 1 in params.values() and f.queries[0]._for_update_arg is None


def test_source_footprint_uses_server_identity_hash_privacy_and_original_category(
    reading, monkeypatch,
):
    f = reading
    artifact = NS(id=uuid4(), revision=3, content_hash="a" * 64, visibility="private",
                  original_id=uuid4(), product_id=f.scope.product_id)
    f.rows[Artifact, artifact.id] = artifact
    monkeypatch.setattr(facts, "source_privacy", lambda *_: "private")
    row = status(f)
    row.reads = [{"artifact_id": str(artifact.id), "expected_revision": 3}]
    bound = facts.bind(f, f.ctx, f.project)
    assert bound["private_context"]
    assert bound["data_categories"] == ["customer_original", "internal"]
    assert bound["source_proof"][0] == {
        "artifact_id": str(artifact.id), "expected_revision": 3,
        "product_id": str(artifact.product_id), "content_hash": "a" * 64,
        "visibility": "private", "original_id": str(artifact.original_id),
    }
    assert f.run.read_sources == []
    assert "fact_summary" not in str(bound) and "RAW_" not in str(bound)
    assert bound["basis_digest"] == facts._basis(facts._collect(f, f.ctx, f.project)[0])


@pytest.mark.parametrize("explicit", [False, True])
def test_native_footprint_rechecks_without_becoming_explicit_sources(
    reading, monkeypatch, explicit,
):
    f = reading
    source = NS(id=uuid4(), revision=1, content_hash="a" * 64, visibility="private",
                original_id=uuid4(), product_id=f.scope.product_id)
    f.rows[Artifact, source.id] = source
    row = status(f)
    row.reads = [{"artifact_id": str(source.id), "expected_revision": 1}]
    monkeypatch.setattr(facts, "source_privacy", lambda *_: "private")
    if explicit:
        f.run.read_sources = [{"artifact_id": str(source.id), "expected_revision": 1,
                               "product_id": str(source.product_id)}]
    original = deepcopy(f.run.read_sources)
    f.run.versions[facts.KEY] = facts.bind(f, f.ctx, f.project)
    f.run.private_context = True
    f.run.data_categories = frozenset({"internal", "customer_original"})
    assert facts._current(f, f.ctx, f.run).named_status.fact_summary == "工程验证尚缺结果"
    assert f.run.read_sources == original
    f.run.private_context = False
    with pytest.raises(DomainError) as privacy:
        facts._current(f, f.ctx, f.run)
    assert privacy.value.code == "FORBIDDEN_SCOPE"
    f.run.private_context = True
    f.run.data_categories = frozenset({"internal"})
    with pytest.raises(DomainError) as classification:
        facts._current(f, f.ctx, f.run)
    assert classification.value.code == "FORBIDDEN_SCOPE"
    f.run.data_categories = frozenset({"internal", "customer_original"})
    source.content_hash = "b" * 64
    with pytest.raises(DomainError) as changed:
        facts._current(f, f.ctx, f.run)
    assert changed.value.code == "SOURCE_STALE"
    del f.rows[Artifact, source.id]
    with pytest.raises(DomainError) as revoked:
        facts._current(f, f.ctx, f.run)
    assert revoked.value.code == "SOURCE_UNAVAILABLE"
    assert f.run.read_sources == original


def test_current_record_change_cannot_silently_replace_the_bound_basis(reading):
    f = reading
    status(f)
    original = facts.bind(f, f.ctx, f.project)
    f.run.versions[facts.KEY] = original
    assert facts._current(f, f.ctx, f.run).named_status.fact_summary == "工程验证尚缺结果"
    f.update["fact_summary"] = "新具名更新，待当前读取"
    with pytest.raises(DomainError) as failure:
        facts._current(f, f.ctx, f.run)
    assert failure.value.code == "SOURCE_STALE" and f.run.versions[facts.KEY] is original
    f.run.versions[facts.KEY] = facts.bind(f, f.ctx, f.project)
    assert facts._current(f, f.ctx, f.run).named_status.fact_summary == "新具名更新，待当前读取"


def test_context_contract_carries_typed_current_facts_and_rejects_package_copy(reading):
    value, *_ = facts._collect(reading, reading.ctx, reading.project)
    raw = {"goal": "为何未进入DVT", "sources": [], "project": {
        "id": str(reading.project.id), "name": "合成项目", "revision": 3,
        "visibility": "category", "current_facts": value.model_dump(mode="json"),
    }}
    schema = combine_contracts(SkillCatalog(), [])
    result, omitted, issues = project(raw, schema)
    assert result == raw and not omitted and not issues
    bad = deepcopy(raw)
    bad["project"]["current_facts"]["release_package"] = {"raw": "SECRET"}
    result, omitted, issues = project(bad, schema)
    assert "SECRET" not in str(result) and omitted and not issues


def test_text_truncation_is_explicit_and_never_fills_a_missing_forecast(reading):
    status(reading)
    reading.update["fact_summary"] = "界" * (facts.TEXT_LIMIT + 9)
    value, *_ = facts._collect(reading, reading.ctx, reading.project)
    assert len(value.named_status.fact_summary) == facts.TEXT_LIMIT
    assert "text_truncated" in value.missing and not value.complete
    assert value.plan.latest_finish is None


def test_readonly_owner_snapshot_is_bound_to_actual_run_and_old_runs_are_unchanged(
    reading, monkeypatch,
):
    from pdos_next.enterprise_search import assistant_sources

    f = reading
    seen = []

    @contextmanager
    def transaction(scope):
        assert scope == f.scope
        yield f, f.run

    @contextmanager
    def snapshot(engine, scope):
        seen.append((engine, scope))
        yield f

    store = NS(engine="same_engine", transaction=transaction)
    monkeypatch.setattr(assistant_sources, "human_snapshot", snapshot)
    assert facts.read(store, f.scope) is None and not seen
    f.run.versions[facts.KEY] = facts.bind(f, f.ctx, f.project)
    result = facts.read(store, f.scope)
    assert result["project_revision"] == 3 and seen == [("same_engine", f.scope)]
    f.run.requester_id = uuid4()
    with pytest.raises(DomainError):
        facts.read(store, f.scope)
    assert len(seen) == 1


def test_model_or_peer_context_cannot_classify_a_project_run(reading):
    for ctx in [Context(reading.ctx.tenant_id, uuid4(), reading.ctx.requester_id,
                        category_id=reading.ctx.category_id),
                Context(reading.ctx.tenant_id, reading.ctx.actor_id, reading.ctx.requester_id,
                        category_id=reading.ctx.category_id, agent_run_id=uuid4())]:
        with pytest.raises(DomainError):
            facts.bind(reading, ctx, reading.project)


def test_current_commitment_reuses_native_promisor_and_fixed_source_basis(reading):
    f = reading
    row = NS(id=uuid4(), revision=2, receipt_id=uuid4(), reads=[], source_basis={"artifacts": []})
    f.rows[facts.WorkCommitmentVersion, row.id] = row
    promise = {"id": str(row.id), "task_id": str(uuid4()), "promisor_id": str(uuid4()),
               "recipient_id": str(uuid4()), "promised_at": None, "fulfilled": False}
    f.native["commitments"] = [promise]
    value, *_ = facts._collect(f, f.ctx, f.project)
    assert value.commitments[0].promisor_id == promise["promisor_id"]
    assert value.commitments[0].promised_at is None and not value.commitments[0].fulfilled
    assert value.commitments[0].reference.receipt_id == str(row.receipt_id)
    assert f.verified == [(f, f.ctx, f.project.product_id, row.source_basis)]


def test_server_basis_requires_actual_context_projection_and_never_invents_rag_lookup(
    reading, monkeypatch,
):
    f = reading
    value = facts._collect(f, f.ctx, f.project)[0].model_dump(mode="json")

    @contextmanager
    def transaction(scope):
        assert scope == f.scope
        yield f, f.run

    store = NS(transaction=transaction)
    monkeypatch.setattr(facts, "read", lambda *_: value)
    output = {"status": "completed", "summary": "已按项目记录核对", "result": {
        "assistant": {"version": 1, "kind": "general", "lookup": "not_run"},
    }}
    assert facts.attach(store, f.scope, output) is output
    f.run.versions = {facts.KEY: facts.bind(f, f.ctx, f.project),
                      "context_snapshots": {"actual": {"fields": ["project"]}}}
    actual = facts.attach(store, f.scope, output)
    basis = actual["result"]["assistant"]["project_basis"]
    assert basis["as_of"] == value["as_of"] and basis["references"] == value["references"]
    assert "lookup" not in actual["result"]["assistant"]
    assert "kind" not in actual["result"]["assistant"] and "sources" not in basis
    assert output["result"]["assistant"]["lookup"] == "not_run"
    mixed = deepcopy(output)
    mixed["result"]["assistant"].update(kind="enterprise", lookup="cited", citation_ids=["real"])
    assert facts.attach(store, f.scope, mixed)["result"]["assistant"]["lookup"] == "cited"


def test_p32_keeps_original_answer_on_update_and_hides_after_fixed_native_acl_loss(reading):
    f = reading
    status(f)
    f.run.versions[facts.KEY] = facts.bind(f, f.ctx, f.project)
    value = facts._collect(f, f.ctx, f.project)[0].model_dump(mode="json")
    original = {"status": "completed", "summary": "按旧具名状态答复。", "result": {
        "assistant": {"version": 1, "project_basis": facts._basis_view(value)},
    }}
    assert facts.checked_result(f, f.ctx, f.run, original) == original
    f.update["fact_summary"] = "新的具名更新"
    preserved = facts.checked_result(f, f.ctx, f.run, original)
    assert preserved["summary"] == original["summary"]
    assert preserved["result"]["assistant"]["project_basis"]["currentness"] == "updated"
    assert preserved["result"]["assistant"]["project_basis"]["as_of"] == value["as_of"]
    del f.rows[ProjectStatusUpdate, UUID(f.update["id"])]
    with pytest.raises(DomainError) as denied:
        facts.checked_result(f, f.ctx, f.run, original)
    assert denied.value.code == "FORBIDDEN_SCOPE"


def test_p32_original_source_update_is_a_notice_but_revocation_is_hidden(reading):
    f = reading
    row = status(f)
    source = NS(id=uuid4(), revision=1, content_hash="a" * 64, original_id=None,
                product_id=f.scope.product_id, visibility="category")
    f.rows[Artifact, source.id] = source
    row.reads = [{"artifact_id": str(source.id), "expected_revision": 1}]
    f.run.versions[facts.KEY] = facts.bind(f, f.ctx, f.project)
    value = facts._collect(f, f.ctx, f.project)[0].model_dump(mode="json")
    original = {"summary": "固定旧记录", "result": {
        "assistant": {"project_basis": facts._basis_view(value)},
    }}
    source.revision, source.content_hash = 2, "b" * 64
    result = facts.checked_result(f, f.ctx, f.run, original)
    assert result["summary"] == "固定旧记录"
    assert result["result"]["assistant"]["project_basis"]["currentness"] == "updated"
    del f.rows[Artifact, source.id]
    with pytest.raises(DomainError) as denied:
        facts.checked_result(f, f.ctx, f.run, original)
    assert denied.value.code == "FORBIDDEN_SCOPE"
