"""Actual bound reads and private saves, using only the offline synthetic provider."""
# ruff: noqa: F401, F811 -- imported fixtures preserve their existing dependency tree

import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from external_wait_pg.test_workflow import create_record, original_security_work, work
from external_wait_pg.test_workflow import execute as wait_execute
from sqlalchemy.orm import Session

from pdos_next.models import Artifact, now
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_business_sources_pg import NativeClient, apply_event
from tests.enterprise_search.test_retrieval_pg import index, register


class TaskClient(SyntheticClient):
    def __init__(self, format_, field, *, forged=False, after_extract=None):
        super().__init__(after_extract=after_extract)
        self.format, self.field, self.forged_cell = format_, field, forged

    def turn(self, route, **kwargs):
        turn = super().turn(route, **kwargs)
        if not turn.structured or {row["name"] for row in kwargs["tools"]} - {"result.read"} == {
            "assistant.passage.read"
        }:
            return turn
        payload = turn.structured
        assistant = payload["result"]["assistant"]
        cid = str(uuid4()) if self.forged_cell else assistant["citation_ids"][0]
        # No duplicate top-level citation selector is required: the checked cell
        # itself selects the actual ledger reference, never creates one.
        assistant["citation_ids"] = []
        assistant["task_result"] = {
            "format": self.format,
            "rows": [
                {
                    "cells": {
                        self.field: {
                            "status": "recorded",
                            "citation_id": cid,
                            "quote": "更换密封圈",
                            "text": "参考已记录措施，当前工况与复验结果仍需确认。",
                        },
                    }
                }
            ],
        }
        return replace(turn, structured=payload)


@pytest.mark.parametrize(
    "format_,field",
    [
        ("blockers", "next_step"),
        ("cases", "measures"),
        ("review", "key_changes"),
        ("commitments", "follow_up"),
    ],
)
def test_four_tables_replay_actual_citations_and_save_the_same_private_cells(setup, format_, field):
    identity = register(setup, "漏气措施记录", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, identity)
    client = TaskClient(format_, field)
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    answer = output["result"]["assistant"]
    cell = answer["task_result"]["rows"][0]["cells"][field]
    assert cell["basis_text"] == "更换密封圈" and cell["content_kind"] == "analysis"
    assert cell["citation_id"] in answer["citation_ids"] and answer["lookup"] == "cited"
    assert client.calls == 5 and client.child_calls == 2
    stored = setup.client.get(f"/v1/personal/agent-runs/{scope.run_id}", headers=setup.headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["result"]["result"]["assistant"]["task_result"] == answer["task_result"]
    saved = setup.client.post(
        "/v1/personal/work-products/from-run",
        headers=setup.headers,
        json={"run_id": str(scope.run_id), "kind": "table", "request_key": str(uuid4())},
    )
    assert saved.status_code == 201, saved.text
    assert "分析：" in str(saved.json()) and "依据：更换密封圈" in str(saved.json())
    assert "待确认" in str(saved.json()) and client.calls == 5


def test_forged_cell_reference_is_partial_and_cannot_be_saved_as_a_fact(setup):
    index(setup, register(setup, "漏气措施记录", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER"))
    owner, scope, host, _adapter = fixture(setup, TaskClient("cases", "measures", forged=True))
    output = execute(owner, scope, host)
    assert output["status"] == "partial", output
    answer = output["result"]["assistant"]
    assert answer["lookup"] == "uncited" and answer["sources"] == []
    assert answer["task_result"]["rows"][0]["cells"]["measures"]["text"] == "待确认"
    assert "当前工况与复验结果" not in str(output)


def test_withdrawn_table_sources_remove_the_table_and_dependent_analysis(setup):
    identity = register(setup, "漏气措施记录", "措施：更换密封圈。RAW_ONLY_CHILD_MARKER")
    index(setup, identity)

    def withdraw():
        with Session(setup.admin) as session, session.begin():
            session.get(Artifact, identity).status = "withdrawn"

    owner, scope, host, _adapter = fixture(
        setup, TaskClient("cases", "measures", after_extract=withdraw)
    )
    output = execute(owner, scope, host)
    assert output["status"] == "partial" and "task_result" not in output["result"]["assistant"]
    assert "更换密封圈" not in str(output) and "当前工况与复验结果" not in str(output)


class WaitTaskClient(NativeClient):
    def turn(self, route, **kwargs):
        turn = super().turn(route, **kwargs)
        if turn.structured is None:
            return turn
        values = [json.loads(row["content"]) for row in kwargs["messages"] if row["role"] == "tool"]
        cid = values[-1]["rows"][0]["citation_id"]
        turn.structured["result"]["assistant"]["task_result"] = {
            "format": "blockers",
            "rows": [
                {
                    "cells": {
                        key: {
                            "status": "recorded",
                            "citation_id": cid,
                            "field_path": ["facts", "wait", field],
                        }
                        for key, field in (
                            ("conclusion", "state"),
                            ("owner", "responsible_id"),
                            ("next_step", "next_check_at"),
                        )
                    }
                }
            ],
        }
        return turn


def test_real_wait_responsibility_state_and_date_come_only_from_registered_fields(work):
    data = create_record()
    data["next_check_at"] = (now() + timedelta(days=7)).isoformat()
    _command, receipt = wait_execute(work, data)
    setup = work.setup
    assert apply_event(setup, receipt["id"])["processed"] == 1
    client = WaitTaskClient(receipt["result"]["wait_id"], ["external_wait"])
    owner, scope, host, _adapter = fixture(setup, client)
    output = execute(owner, scope, host)
    assert output["status"] == "completed", output
    cells = output["result"]["assistant"]["task_result"]["rows"][0]["cells"]
    assert cells["owner"]["text"] == str(setup.human)
    assert cells["owner"]["locator"] == {"json_pointer": "/facts/wait/responsible_id"}
    assert cells["conclusion"]["text"] == "open"
    assert cells["next_step"]["text"].startswith(data["next_check_at"][:19])
    assert all(
        cell["content_kind"] == "recorded"
        for cell in cells.values()
        if cell["status"] == "recorded"
    )
    assert client.calls == 3
