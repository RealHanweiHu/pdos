"""Frozen server project pointers carry real dependencies without fact-body replay."""

from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from pdos_next.agent_kernel import conversation_acl as acl
from pdos_next.agent_kernel import project_history_metadata as pointers
from pdos_next.service import digest


def binding():
    run = NS(**{key: uuid4() for key in (
        "tenant_id", "category_id", "product_id", "project_id", "requester_id")})
    value = {key: str(getattr(run, key)) for key in vars(run)}
    value.update(kind="project-current-facts/v2", references=[], source_proof=[],
                 metadata_snapshot={"version": "project-current-metadata/v1",
                     "project_revision": 1, "current_plan_id": None,
                     "tasks": {"items": [], "has_more": False},
                     "task_commitments": {"items": [], "has_more": False},
                     "named_status": None, "governance": None})
    return run, value


def test_project_context_closes_actual_refs_sources_and_receipts_without_inventing_task_revision():
    run, value = binding()
    artifact, task, plan_task, receipt = [str(uuid4()) for _ in range(4)]
    value["source_proof"] = [{"artifact_id": artifact, "expected_revision": 3}]
    value["references"] = [
        {"kind": "work_task", "id": task, "revision": 2, "receipt_id": receipt},
        {"kind": "plan_task", "id": plan_task, "revision": 7},
    ]
    deps, snapshot = acl.project_context(value, run)
    assert acl.dependency("artifact", artifact, 3) in deps
    assert acl.dependency("work_task", task, 2) in deps
    assert acl.dependency("receipt", receipt) in deps
    assert acl.dependency("plan_task", plan_task) in deps
    assert "version" not in next(row for row in deps if row["kind"] == "plan_task")
    assert snapshot == {"project_id": str(run.project_id),
                        "metadata_snapshot": value["metadata_snapshot"]}


@pytest.mark.parametrize("field", ["tenant_id", "category_id", "product_id",
                                  "project_id", "requester_id"])
def test_projection_cannot_bind_another_requesters_scope(field):
    run, value = binding()
    value[field] = str(uuid4())
    with pytest.raises(ValueError):
        acl.project_context(value, run)


def test_unregistered_reference_and_incomplete_pointer_are_not_silently_accepted():
    run, value = binding()
    value["references"] = [{"kind": "model_invented", "id": str(uuid4())}]
    with pytest.raises(ValueError):
        acl.project_context(value, run)
    value["references"] = []
    del value["metadata_snapshot"]["tasks"]["has_more"]
    with pytest.raises(ValueError):
        acl.project_context(value, run)


def test_legacy_projection_retains_source_acl_without_inventing_pointer_history():
    run, value = binding()
    value["kind"] = "project-current-facts/v1"
    del value["metadata_snapshot"]
    deps, snapshot = acl.project_context(value, run)
    assert snapshot is None
    assert {row["kind"] for row in deps} == {"project", "product"}


def test_pointer_query_is_one_bounded_union_without_source_or_business_body():
    sql = str(pointers.statement({uuid4(), uuid4()}).compile(dialect=postgresql.dialect()))
    assert "UNION ALL" in sql and "row_number()" in sql
    assert "work_task_currents" in sql and "work_commitment_currents" in sql
    assert "history_project_scopes" in sql and "conversation_project_metadata" in sql
    for forbidden in (".body", ".content", ".source_basis", ".command", ".reads", ".title"):
        assert forbidden not in sql


def state_for(context, rows):
    statements = []

    def execute(statement):
        statements.append(statement)
        return NS(mappings=lambda: iter(rows))

    result = pointers.states(NS(execute=execute), [context])
    assert len(statements) == 1
    return result[digest(context)]


def test_current_membership_and_plan_are_current_but_append_or_pointer_change_updates():
    run, value = binding()
    context = acl.project_context(value, run)[1]
    current = {"kind": "project", "project_id": str(run.project_id), "position": 0,
               "metadata": {"project_revision": 1, "current_plan_id": None}}
    assert state_for(context, [current]) == "current"
    member = {"kind": "tasks", "project_id": str(run.project_id), "position": 1,
              "metadata": {"task_id": str(uuid4()), "version_id": str(uuid4()), "revision": 1}}
    assert state_for(context, [current, member]) == "updated"
    changed = deepcopy(current)
    changed["metadata"]["current_plan_id"] = str(uuid4())
    assert state_for(context, [changed]) == "updated"
    assert state_for(context, []) == "hidden"


def test_commitment_pointer_changes_are_compared_only_on_the_same_bounded_task_set():
    run, value = binding()
    task = {"task_id": str(uuid4()), "version_id": str(uuid4()), "revision": 1}
    promise = {"task_id": task["task_id"], "series_id": str(uuid4()),
               "promisor_id": str(uuid4()), "recipient_id": str(uuid4()),
               "version_id": str(uuid4()), "revision": 1}
    value["metadata_snapshot"]["tasks"]["items"] = [task]
    value["metadata_snapshot"]["task_commitments"]["items"] = [promise]
    context = acl.project_context(value, run)[1]
    rows = [{"kind": "project", "project_id": str(run.project_id), "position": 0,
             "metadata": {"project_revision": 1, "current_plan_id": None}},
            {"kind": "tasks", "project_id": str(run.project_id), "position": 1,
             "metadata": task},
            {"kind": "task_commitments", "project_id": str(run.project_id), "position": 1,
             "metadata": promise}]
    assert state_for(context, rows) == "current"
    changed = deepcopy(rows)
    changed[2]["metadata"]["revision"] = 2
    assert state_for(context, changed) == "updated"
    assert state_for(context, rows[:1]) == "updated"


def test_has_more_and_named_pointer_changes_annotate_without_treating_unknown_as_no_record():
    run, value = binding()
    context = acl.project_context(value, run)[1]
    rows = [{"kind": "project", "project_id": str(run.project_id), "position": 0,
             "metadata": {"project_revision": 1, "current_plan_id": None}},
            {"kind": "named_status", "project_id": str(run.project_id), "position": 1,
             "metadata": {"id": str(uuid4()), "revision": 2}}]
    assert state_for(context, rows) == "current"  # Explicit unavailable/null isn't an empty set.
    context["metadata_snapshot"]["named_status"] = {"id": str(uuid4()), "revision": 1}
    assert state_for(context, rows) == "updated"
    context["metadata_snapshot"]["named_status"] = None
    context["metadata_snapshot"]["tasks"]["has_more"] = True
    assert state_for(context, rows) == "updated"


def test_confirmed_no_named_records_detects_first_registration_but_unknown_does_not():
    run, value = binding()
    context = acl.project_context(value, run)[1]
    project = {"kind": "project", "project_id": str(run.project_id), "position": 0,
               "metadata": {"project_revision": 1, "current_plan_id": None}}
    for key in ("named_status", "governance"):
        added = {"kind": key, "project_id": str(run.project_id), "position": 1,
                 "metadata": {"id": str(uuid4()), "revision": 1}}
        context["metadata_snapshot"][key + "_known"] = False
        assert state_for(context, [project, added]) == "current"
        context["metadata_snapshot"][key + "_known"] = True
        assert state_for(context, [project]) == "current"
        assert state_for(context, [project, added]) == "updated"
        context["metadata_snapshot"].pop(key + "_known")


def test_project_source_hash_is_a_frozen_dependency_and_change_is_annotated(monkeypatch):
    run, value = binding()
    source = str(uuid4())
    value["source_proof"] = [{"artifact_id": source, "expected_revision": 3,
                              "content_hash": "old-content"}]
    deps, _ = acl.project_context(value, run)
    artifact = next(item for item in deps if item["kind"] == "artifact")
    assert artifact["content_hash"] == "old-content"
    monkeypatch.setattr(acl, "metadata", lambda *_: {
        ("artifact", source): [{"revision": 3, "content_hash": "new-content", "status": "active"}]})
    access = {"origin": {"dependencies": [artifact], "citations": []}}
    assert acl.classify(None, access) == {"origin": "updated"}
    monkeypatch.setattr(acl, "metadata", lambda *_: {})
    assert acl.classify(None, access) == {"origin": "hidden"}
