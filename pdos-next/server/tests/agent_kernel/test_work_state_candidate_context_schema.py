"""Native readonly candidate summaries fit the closed registered skill contract."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from pdos_next.agent_kernel import work_state_candidates as metadata
from pdos_next.agent_kernel.context_projection import combine_contracts, project
from pdos_next.agent_kernel.skills import SkillCatalog
from pdos_next.agent_kernel.work_state import empty


def schema():
    catalog = SkillCatalog()
    return combine_contracts(catalog, [catalog.configuration("work_management")])


def native_summary(kind, state, *, work_followup=False):
    event = SimpleNamespace(id=uuid4(), body={"type": kind})
    if work_followup:
        event.body["kind"] = "work_followup"
    run = SimpleNamespace(id=uuid4())
    native = {"operation": "work.task.create", "state": state,
              "kind": "work_followup" if work_followup else metadata.KINDS[kind]}
    if state == "adopted":
        native["receipt"] = {"id": str(uuid4())}
    return metadata._summary(event, run, native)


def context(candidates):
    body = {key: value for key, value in empty().items() if key != "removed_constraints"}
    body.update(version="agent-work-state/v1", revision=1, session_id=str(uuid4()),
                notes=[], estimated_tokens=0, context_incomplete=False, missing=[],
                candidates=candidates)
    return {"goal": "只核对当前候选，未确认不创建或指派。", "sources": [], "work_state": body}


def test_registered_metadata_shape_and_enums_match_the_native_projection_whitelist():
    item = schema()["$defs"]["work_state"]["properties"]["candidates"]["items"]
    assert set(item["properties"]) == {
        "event_id", "run_id", "kind", "operation", "state", "receipt_id",
    }
    assert set(item["properties"]["kind"]["enum"]) == set(metadata.KINDS.values())
    assert set(item["properties"]["state"]["enum"]) == metadata.STATES
    assert item["properties"]["operation"]["type"] == ["string", "null"]
    assert item["properties"]["receipt_id"]["type"] == ["string", "null"]
    assert item["additionalProperties"] is False


@pytest.mark.parametrize("kind", sorted(metadata.KINDS))
@pytest.mark.parametrize("state", sorted(metadata.STATES))
def test_every_native_candidate_kind_and_state_survives_the_loaded_contract(kind, state):
    summary = native_summary(kind, state)
    raw = context([summary])
    projected, omitted, issues = project(raw, schema())
    assert projected == raw and not omitted and not issues
    if state == "adopted":
        assert isinstance(summary["receipt_id"], str)
    else:
        assert summary["receipt_id"] is None
    if state == "unavailable":
        assert summary["operation"] is None


def test_old_and_current_work_followup_pending_metadata_stays_unchanged():
    old = native_summary("domain_candidate", "pending", work_followup=True)
    current = native_summary("domain_candidate", "pending", work_followup=True)
    before = deepcopy([old, current])
    projected, omitted, issues = project(context([old, current]), schema())
    assert not omitted and not issues
    assert projected["work_state"]["candidates"] == before == [old, current]
    assert old["event_id"] != current["event_id"] and old["run_id"] != current["run_id"]
    assert all(row["state"] == "pending" and row["receipt_id"] is None for row in before)


@pytest.mark.parametrize("field", [
    "task_id", "request_key", "command", "payload", "source_proof", "title", "quote",
])
def test_unknown_or_private_candidate_fields_remain_outside_the_contract(field):
    summary = native_summary("domain_candidate", "pending", work_followup=True)
    raw = context([{**summary, field: "PRIVATE_UNDECLARED_VALUE"}])
    registered = schema()
    assert not Draft202012Validator(registered).is_valid(raw)
    projected, omitted, issues = project(raw, registered)
    assert projected["work_state"]["candidates"] == [summary] and not issues
    assert omitted == [{"field": "/work_state/candidates/0/" + field,
                        "reason": "outside_skill_context_schema"}]
    assert "PRIVATE_UNDECLARED_VALUE" not in str(omitted)


@pytest.mark.parametrize("field,value", [("kind", "model_supplied"), ("state", "requires_human")])
def test_unregistered_candidate_kind_or_state_is_a_schema_error(field, value):
    summary = native_summary("domain_candidate", "pending", work_followup=True)
    raw = context([{**summary, field: value}])
    _projected, omitted, issues = project(raw, schema())
    assert not omitted
    assert issues == [{"field": "/work_state/candidates/0/" + field, "reason": "context_enum"}]
