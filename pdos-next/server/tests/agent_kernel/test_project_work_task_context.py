"""Current task projections, batch metadata guards and exact legacy compatibility."""

from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import project_current_context as facts
from pdos_next.agent_kernel import project_work_task_context as work
from pdos_next.domain.preproject.models import ProjectOpenItem
from pdos_next.domain.projects.models import ProjectTask
from pdos_next.domain.work_management.models import WorkTaskVersion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, OriginalSecurity, Product, UploadedOriginal
from pdos_next.service import Context, digest


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Reading:
    def __init__(self):
        tenant, category, product, identity, human = [uuid4() for _ in range(5)]
        self.ctx = Context(tenant, human, human, category_id=category)
        self.info = {"scope": (tenant, human, human, category)}
        self.project = NS(id=identity, tenant_id=tenant, category_id=category,
                          product_id=product, current_plan_id=None, revision=1)
        self.heads, self.promises, self.queries, self.source_rows = [], [], [], {}
        self.proofs = {}

    def execute(self, statement):
        self.queries.append(statement)
        sql = str(statement)
        if "project_work_task_heads" in sql:
            return Rows(self.heads)
        if "project_work_commitment_heads" in sql:
            return Rows(self.promises)
        assert "project_work_receipt_groups" in sql
        return Rows(list(self.proofs.values()))

    def scalars(self, statement):
        self.queries.append(statement)
        return Rows(self.source_rows.get(statement.column_descriptions[0]["entity"], []))

    def link(self, kind, identity, revision=None, receipt=None):
        return {"kind": kind, "id": str(identity), "revision": revision,
                "receipt_id": str(receipt) if receipt else None, "url": "/actual-project"}


def source(reading, *, original=False):
    p = reading.project
    row = NS(id=uuid4(), tenant_id=p.tenant_id, category_id=p.category_id,
             product_id=p.product_id, revision=1, status="active", content_hash="a" * 64,
             owner_id=reading.ctx.requester_id, visibility="category",
             original_id=uuid4() if original else None)
    reading.source_rows.setdefault(Artifact, []).append(row)
    reading.source_rows[Product] = [NS(id=p.product_id, visibility="category")]
    return row


def proof(reading, row, *, actor=None):
    actor = actor or reading.ctx.requester_id
    receipt = NS(id=row.receipt_id, subject_id=row.id, subject_revision=row.revision,
                 visibility=row.visibility, operation=row.operation, actor_id=actor,
                 result={"id": str(row.id), "revision": row.revision},
                 agent_run_id=None, run_id=None, command_id=uuid4())
    audit = NS(actor_id=actor, operation=row.operation)
    outbox = NS(type=work.OPERATIONS[row.operation][1], actor_id=actor,
                correlation_id=receipt.command_id, subject_id=row.id,
                subject_revision=row.revision)
    reading.proofs[row.id] = (receipt, audit, outbox, True)


def task(reading, *, assigned=False, original=None):
    p = reading.project
    identity, assignee = uuid4(), uuid4() if assigned else None
    body = {"task_id": str(identity), "revision": 1,
            "state": "assigned" if assigned else "proposed", "title": "实际复验待办",
            "goal": "RAW_GOAL_NOT_IN_CONTEXT", "outcomes": [{"key": "review", "text": "原记录",
                                                            "required": True}],
            "plan_task": None, "assignee_id": str(assignee) if assignee else None,
            "recipient_id": str(reading.ctx.requester_id) if assigned else None}
    row = NS(**{key: getattr(p, key) for key in work.SCOPE if key != "project_id"},
             project_id=p.id, id=uuid4(), task_id=identity, revision=1,
             state=body["state"], owner_id=reading.ctx.requester_id, visibility="category",
             body=body, body_sha256=digest(body), receipt_id=uuid4(),
             operation="work.task.assign" if assigned else "work.task.create",
             source_basis={"artifacts": []}, reads=[])
    if original:
        basis = {"id": str(original.id), "revision": original.revision,
                 "hash": original.content_hash, "owner_id": str(original.owner_id),
                 "visibility": original.visibility}
        if original.original_id:
            basis["original"] = {"id": str(original.original_id), "epoch": 2}
        row.source_basis["artifacts"].append(basis)
        row.reads.append({"artifact_id": str(original.id), "expected_revision": original.revision})
    pointer = NS(**{key: getattr(row, key) for key in (*work.BINDING, "task_id", "revision",
                                                     "state")}, version_id=row.id)
    reading.heads.append((row, pointer, None, None, assignee, "具名受派人" if assignee else None))
    proof(reading, row)
    return row


def planned(reading, row, *, known=True):
    plan = NS(**{key: getattr(row, key) for key in work.SCOPE}, id=uuid4(), revision=2,
              visibility="category")
    value = NS(**{key: getattr(row, key) for key in work.SCOPE}, id=uuid4(), plan_id=plan.id,
               forecast={"earliest_finish": "2026-11-08T01:00:00Z" if known else None,
                         "latest_finish": "2026-11-08T02:00:00Z" if known else None,
                         "unknown_reasons": [] if known else ["DURATION_MAX_UNKNOWN"]})
    row.body["plan_task"] = {"id": str(value.id), "revision": plan.revision}
    row.body_sha256 = digest(row.body)
    old = next(item for item in reading.heads if item[0] is row)
    reading.heads[reading.heads.index(old)] = (*old[:2], value, plan, *old[4:])
    reading.project.current_plan_id = plan.id
    return value, plan


def collect(reading):
    return work.collect(reading, reading.ctx, reading.project, link=reading.link)


def test_current_assignee_plan_unknown_and_commitment_are_separate():
    reading = Reading()
    first = task(reading, assigned=True)
    task_id, plan = planned(reading, first)
    second = task(reading)
    planned(reading, second, known=False)
    reading.project.current_plan_id = plan.id
    values, more, refs, roots, private, _, missing, snapshot = collect(reading)
    actual, unknown = values
    assert actual.assignee_id != str(first.owner_id) and actual.assignee_name == "具名受派人"
    assert actual.reference.id == str(first.id)
    assert actual.reference.receipt_id == str(first.receipt_id)
    assert actual.plan.state == "available" and actual.plan.date_nature == "forecast"
    assert actual.plan.latest_finish == "2026-11-08T02:00:00Z" and actual.commitments == []
    assert actual.plan.task_reference.id == str(task_id.id)
    assert unknown.assignee_id is unknown.assignee_name is None
    assert unknown.plan.latest_finish is None and unknown.plan.unknown_reasons
    assert unknown.plan.state == "historical"  # Exact fixed plan, never substituted.
    assert not more and not private and not roots and not missing
    assert "RAW_GOAL" not in str([value.model_dump() for value in values])
    assert {ref["kind"] for ref in refs} == {"work_task", "plan_task", "plan"}
    assert snapshot["tasks"]["items"][0]["version_id"] == str(first.id)


def test_heads_and_sources_query_count_is_constant_with_twenty_distinct_roots():
    counts = []
    for amount in (1, 20):
        reading = Reading()
        for _ in range(amount):
            task(reading, original=source(reading))
        values, _, _, roots, _, _, missing, _ = collect(reading)
        assert len(values) == len(roots) == amount and not missing
        counts.append(len(reading.queries))
        source_query = next(query for query in reading.queries
                            if query.column_descriptions[0].get("entity") is Artifact)
        sql = str(source_query)
        assert "artifact_versions.content," not in sql and "FOR UPDATE" not in sql
    assert counts == [5, 5]


@pytest.mark.parametrize("field,value", [
    ("revision", 2), ("content_hash", "b" * 64), ("owner_id", uuid4()),
    ("visibility", "private"), ("status", "withdrawn"),
])
def test_changed_or_withdrawn_source_has_no_task_body_but_keeps_actual_pointer(field, value):
    reading = Reading()
    original = source(reading)
    row = task(reading, original=original)
    setattr(original, field, value)
    values, _, _, roots, _, _, missing, snapshot = collect(reading)
    assert values == [] and roots == [] and missing
    assert snapshot["tasks"]["items"] == [
        {"task_id": str(row.task_id), "version_id": str(row.id), "revision": 1}]


def test_revoked_source_and_scan_epoch_are_rejected(monkeypatch):
    reading = Reading()
    original = source(reading, original=True)
    row = task(reading, original=original)
    oid = original.original_id
    reading.source_rows[UploadedOriginal] = [NS(id=oid, product_id=None, visibility="private")]
    reading.source_rows[OriginalSecurity] = [NS(original_id=oid, product_id=original.product_id,
                                               epoch=2,
                                               source_state="active", disposition="active")]
    monkeypatch.setattr(work, "safe_originals", lambda _session, ids: set(ids))
    assert collect(reading)[4] is True
    reading.source_rows[OriginalSecurity][0].epoch = 3
    assert collect(reading)[0] == []
    reading.source_rows[OriginalSecurity][0].epoch = 2
    monkeypatch.setattr(work, "safe_originals", lambda *_: set())
    assert collect(reading)[0] == []
    reading.source_rows[Artifact] = []
    assert "task_sources_source_unavailable" in collect(reading)[6]
    assert row.id


@pytest.mark.parametrize("tamper", ["hash", "receipt", "audit", "outbox", "peer_key"])
def test_tampered_work_or_shared_proof_never_projects_a_fact(tamper):
    reading = Reading()
    row = task(reading)
    receipt, audit, outbox, _ = reading.proofs[row.id]
    if tamper == "hash":
        row.body["title"] = "TAMPERED"
        with pytest.raises(DomainError, match="固定版本") as failed:
            collect(reading)
        assert failed.value.reason == "INTEGRITY_MISMATCH"
        return
    if tamper == "receipt":
        receipt.result["revision"] = 2
    elif tamper == "audit":
        audit.actor_id = uuid4()
    elif tamper == "outbox":
        outbox.correlation_id = uuid4()
    else:
        receipt.actor_id = audit.actor_id = outbox.actor_id = uuid4()
        reading.proofs[row.id] = (receipt, audit, outbox, False)
    values, *_, missing, snapshot = collect(reading)
    assert not values and "work_receipt_unavailable" in missing
    assert snapshot["tasks"]["items"]


def test_bounded_twenty_rows_and_cross_scope_are_not_silently_projected():
    reading = Reading()
    for _ in range(21):
        task(reading)
    values, more, *_tail = collect(reading)
    assert len(values) == 20 and more and "tasks_truncated" in _tail[-2]
    assert len(_tail[-1]["tasks"]["items"]) == 20
    reading.heads[0][0].project_id = uuid4()
    with pytest.raises(DomainError) as failed:
        collect(reading)
    assert failed.value.reason == "INTEGRITY_MISMATCH"


def test_actual_commitment_has_its_own_series_and_date_not_the_plan_forecast():
    reading = Reading()
    assigned = task(reading, assigned=True)
    planned(reading, assigned)
    row = deepcopy(assigned)
    row.id, row.receipt_id, row.series_id = uuid4(), uuid4(), uuid4()
    row.operation = "work.commitment.accept"
    row.task_revision = assigned.revision
    row.promisor_id = reading.heads[0][4]
    row.recipient_id = reading.ctx.requester_id
    row.body = {"revision": 1, "task_id": str(assigned.task_id), "task_revision": 1,
                "promisor_id": str(row.promisor_id), "recipient_id": str(row.recipient_id),
                "outcome_keys": ["review"], "promised_at": "2026-11-10T02:00:00Z",
                "original_timezone": "UTC", "recorded_at": datetime.now(UTC).isoformat()}
    row.body_sha256 = digest(row.body)
    row.promised_at = datetime(2026, 11, 10, 2, tzinfo=UTC)
    pointer = NS(**{key: getattr(row, key) for key in (*work.BINDING, "task_id", "revision")})
    reading.promises = [(row, pointer)]
    proof(reading, row, actor=row.promisor_id)
    actual, _, refs, _, _, _, missing, metadata = collect(reading)
    commitment = actual[0].commitments[0]
    assert commitment.reference.id == str(row.id) and commitment.series_id == str(row.series_id)
    assert commitment.promised_at.startswith("2026-11-10")
    assert actual[0].plan.latest_finish.startswith("2026-11-08")
    assert not missing and "work_commitment" in {ref["kind"] for ref in refs}
    assert metadata["task_commitments"]["items"][0]["series_id"] == str(row.series_id)


def test_sql_scope_keyset_order_and_actual_plan_are_closed():
    reading = Reading()
    query = work.task_query(reading.ctx, reading.project)
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert all("work_task_currents." + name + " =" in sql for name in work.SCOPE)
    assert "ORDER BY work_task_currents.task_id" in sql and "FOR UPDATE" not in sql
    assert "principals.active" not in sql  # Assigned identity survives deactivation.
    assert 21 in query.compile().params.values()
    assert "project_tasks.id AS" in sql and "plan_revisions.id AS" in sql
    assert ProjectTask and WorkTaskVersion


def test_native_g0_basis_is_checked_without_private_proposal_or_original_body():
    reading = Reading()
    row = task(reading)
    item = NS(**{key: getattr(row, key) for key in work.SCOPE}, id=uuid4(),
              g0_decision_id=uuid4(), kind="task", title="G0原生事项", note="原生记录",
              owner_id=row.owner_id, due_date=date(2026, 11, 8), source_question_id=uuid4(),
              source_spec_item_id=None, status="open")
    actual = {key: getattr(item, "g0_decision_id" if key == "decision_id" else key)
              for key in (*work.SCOPE, *work.g0_sources._FIXED)}
    row.source_basis["g0_open_item"] = work.g0_sources._basis(
        actual, reading.ctx, reading.project.product_id, reading.project.id,
    )
    reading.source_rows[ProjectOpenItem] = [item]
    values, _, refs, roots, _, _, missing, _ = collect(reading)
    assert len(values) == 1 and roots == [] and not missing
    assert {ref["kind"] for ref in refs} == {"work_task", "project_open_item"}
    item.status = "closed"
    assert len(collect(reading)[0]) == 1  # Status is outside immutable G0 provenance.
    item.due_date = date(2026, 11, 9)
    assert collect(reading)[0] == []
    assert "task_sources_source_stale" in collect(reading)[6]


def test_unreadable_person_label_does_not_become_task_owner_or_no_assignment():
    reading = Reading()
    row = task(reading, assigned=True)
    old = reading.heads[0]
    reading.heads[0] = (*old[:4], None, None)
    values, *_tail = collect(reading)
    assert values[0].assignee_id == row.body["assignee_id"]
    assert values[0].assignee_name is None and "task_assignee_unavailable" in _tail[-2]
    assert values[0].assignee_id != str(row.owner_id)


def test_v1_serialization_and_basis_are_exact_after_v2_release(monkeypatch):
    from tests.agent_kernel.test_project_current_context import Reading as OldReading
    from tests.agent_kernel.test_project_current_context import native

    reading = OldReading()
    monkeypatch.setattr(facts, "latest_updates", lambda *_: {})
    monkeypatch.setattr(facts.governance, "view", lambda *_: native(reading.project))
    monkeypatch.setattr(facts.governance, "_project", lambda *_: (
        reading.project, None, {"id": str(reading.definition.id), "revision": 2}))
    monkeypatch.setattr(facts, "require_access", lambda *_: reading.product)
    old, roots, private, categories = facts._collect(
        reading, reading.ctx, reading.project, version=facts.LEGACY_KIND,
    )
    old_body = old.model_dump(mode="json")
    assert old_body["version"] == "project-current-facts/v1"
    assert "tasks" not in old_body and "tasks_has_more" not in old_body
    assert type(old) is facts.LegacyCurrentFacts and not roots and not private
    assert categories == {"internal"}
    frozen = {"kind": facts.LEGACY_KIND, "tenant_id": str(reading.scope.tenant_id),
              "category_id": str(reading.scope.category_id),
              "product_id": str(reading.scope.product_id),
              "project_id": str(reading.scope.project_id),
              "requester_id": str(reading.scope.requester_id), "basis_digest": facts._basis(old),
              "source_proof": [], "as_of": old.as_of}
    reading.run.versions[facts.KEY] = deepcopy(frozen)
    monkeypatch.setattr(facts, "require_project", lambda *_: reading.project)
    # Keep every legacy record deterministic and disallow the new task query.
    native_value = native(reading.project)
    monkeypatch.setattr(facts.governance, "view", lambda *_: native_value)
    old = facts._collect(reading, reading.ctx, reading.project, version=facts.LEGACY_KIND)[0]
    reading.run.versions[facts.KEY]["basis_digest"] = facts._basis(old)
    monkeypatch.setattr(reading, "execute", lambda *_: pytest.fail("v1 queried v2 tasks"))
    assert facts._current(reading, reading.ctx, reading.run).model_dump(mode="json") == (
        old.model_dump(mode="json"))
