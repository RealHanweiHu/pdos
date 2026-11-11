"""D77/D78: a run's candidates in 要我决定, grouped by run, and confirmed as one package.

Synthetic stored model calls only. Each package item still runs its own previewed
command in its own transaction; nothing here widens a tier.
"""

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.core.models import Receipt
from pdos_next.core.service import digest
from tests.agent.kernel.test_domain_candidates_pg import OP, fixture, prepare, read
from tests.categories.products.test_platform_links_pg import counts


def another(setup, f, **changes):
    args = deepcopy(f.arguments)
    for key, value in changes.items():
        if key == "code":
            args["new_platform"]["code"] = value
        else:
            args[key] = value
    model = AgentToolCall(
        id=uuid4(),
        tenant_id=setup.tenant,
        run_id=f.scope.run_id,
        call_key=str(uuid4()),
        input_digest=digest(args),
        tool="model",
        state="completed",
        execution_binding=f.model.execution_binding,
        result={"calls": [{"name": OP, "arguments": args}]},
    )
    model_id = model.id
    with Session(setup.admin) as s, s.begin():
        s.add(model)
    return prepare(f, model_id=model_id, arguments=args)


def headers(setup, actor=None):
    return {"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"}


def decisions(setup, actor=None):
    response = setup.client.get("/v1/personal/run-decisions", headers=headers(setup, actor))
    assert response.status_code == 200, response.text
    return response.json()


def group(value, run_id):
    return next((item for item in value["runs"] if item["run_id"] == str(run_id)), None)


def previewed(setup, command):
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=setup.headers, json=command
    )
    assert response.status_code == 200, response.text
    return response.json()["command"]


def package(setup, f, items, actor=None):
    return setup.client.post(
        f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}/candidates/confirm",
        headers=headers(setup, actor),
        json={"items": items},
    )


def ask(setup, f, *, error_code=None):
    with Session(setup.admin) as s, s.begin():
        run = s.get(AgentRun, f.scope.run_id)
        run.state, run.error_code = "waiting_input", error_code
        sequence = s.scalar(
            select(func.max(AgentEvent.sequence)).where(AgentEvent.run_id == run.id)
        )
        s.add(
            AgentEvent(
                id=uuid4(),
                tenant_id=setup.tenant,
                run_id=run.id,
                sequence=(sequence or 0) + 1,
                body={
                    "type": "needs_input",
                    "questions": [
                        {
                            "id": "q1",
                            "question": "合成平台的兼容范围是什么？",
                            "why": "补齐关联判据",
                            "options": [{"value": "all", "label": "全部变体"}],
                            "recommended": None,
                            "allow_free_text": True,
                            "depends_on": [],
                        }
                    ],
                },
            )
        )
        return (sequence or 0) + 1


def test_run_decisions_group_pending_candidates_and_questions_for_the_requester_only(setup):
    f = fixture(setup)
    first, second = prepare(f), another(setup, f, code="SECOND")
    before = counts(setup)
    value = decisions(setup)
    assert value["version"] == "personal-run-decisions/v1"
    assert value["principal_id"] == str(setup.human)
    item = group(value, f.scope.run_id)
    assert item["category"] == {"id": str(setup.category), "name": item["category"]["name"]}
    assert [entry["event_id"] for entry in item["candidates"]] == [
        first["event_id"],
        second["event_id"],
    ]
    assert all(
        entry["package"] and entry["write_tier"] == "T1" and entry["separate_reason"] is None
        for entry in item["candidates"]
    )
    assert item["candidates"][0]["command"] == first["command"]
    assert item["questions"] == [] and not item["needs_review"]
    assert value["candidate_count"] >= 2 and value["total_runs"] == len(value["runs"])
    # Nobody else sees this run, its goal or its candidates.
    for actor in (setup.peer, setup.other_human):
        assert group(decisions(setup, actor), f.scope.run_id) is None
    # A waiting question joins the same run card; reading writes nothing.
    sequence = ask(setup, f)
    item = group(decisions(setup), f.scope.run_id)
    assert item["questions"][0]["question"] == "合成平台的兼容范围是什么？"
    assert item["question_sequence"] == sequence and len(item["candidates"]) == 2
    # Waiting for reconciliation is not a question: shown for review, never as one.
    ask(setup, f, error_code="EXTERNAL_OUTCOME_UNKNOWN")
    item = group(decisions(setup), f.scope.run_id)
    assert item["questions"] == [] and item["needs_review"] is True
    assert counts(setup) == before


def test_package_saves_each_item_alone_and_lists_partial_failures(setup):
    f = fixture(setup)
    first = prepare(f)
    clash = another(setup, f, reason="同一平台编号的第二个合成候选")
    third = another(setup, f, code="THIRD")
    commands = [previewed(setup, entry["command"]) for entry in (first, clash, third)]
    before = counts(setup)
    response = package(
        setup,
        f,
        [
            {"event_id": entry["event_id"], "command": command}
            for entry, command in zip((first, clash, third), commands, strict=True)
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert [entry["status"] for entry in result["items"]] == ["adopted", "failed", "adopted"]
    assert (result["adopted"], result["failed"], result["refused"]) == (2, 1, 0)
    assert result["items"][1]["error"]["reason"] == "platform_code_taken"
    # Every saved item has its own receipt, bound to this run and its own request.
    with Session(setup.admin) as s:
        receipts = {
            row.id: row
            for row in s.scalars(
                select(Receipt).where(Receipt.agent_run_id == f.scope.run_id)
            )
        }
    saved = [result["items"][0]["receipt"]["id"], result["items"][2]["receipt"]["id"]]
    assert {str(key) for key in receipts} == set(saved)
    table = Receipt.__tablename__
    assert counts(setup)[table] == before[table] + 2
    states = {item["event_id"]: item["state"] for item in read(setup, f).json()["items"]}
    assert states == {
        first["event_id"]: "adopted",
        clash["event_id"]: "pending",
        third["event_id"]: "adopted",
    }
    # The run card now holds only the item that failed.
    item = group(decisions(setup), f.scope.run_id)
    assert [entry["event_id"] for entry in item["candidates"]] == [clash["event_id"]]


def test_package_refuses_named_foreign_changed_and_unconfirmed_items_without_writing(setup):
    f = fixture(setup)
    first, second = prepare(f), another(setup, f, code="SECOND")
    command = previewed(setup, first["command"])
    named = {**deepcopy(command), "operation": "proposal.g0.decide"}
    changed = deepcopy(command)
    changed["payload"]["reason"] = "被改动的原因"
    unconfirmed = deepcopy(second["command"])
    before = counts(setup)
    response = package(
        setup,
        f,
        [
            {"event_id": first["event_id"], "command": named},
            {"event_id": str(uuid4()), "command": command},
            {"event_id": second["event_id"], "command": unconfirmed},
        ],
    )
    assert response.status_code == 200, response.text
    reasons = [entry["error"]["reason"] for entry in response.json()["items"]]
    assert reasons == [
        "package_named_decision",
        "candidate_not_in_run",
        "package_unconfirmed",
    ]
    assert all(entry["status"] == "refused" for entry in response.json()["items"])
    changed_response = package(setup, f, [{"event_id": first["event_id"], "command": changed}])
    assert changed_response.json()["items"][0]["error"]["reason"] == "candidate_command_changed"
    assert counts(setup) == before
    # Another person cannot confirm this run's package; duplicates are not accepted.
    foreign = package(setup, f, [{"event_id": first["event_id"], "command": command}], setup.peer)
    assert foreign.status_code == 403
    duplicate = package(
        setup,
        f,
        [{"event_id": first["event_id"], "command": command}] * 2,
    )
    assert duplicate.status_code == 422
    assert counts(setup) == before
    # The untouched original still saves through the package, once.
    saved = package(setup, f, [{"event_id": first["event_id"], "command": command}])
    assert saved.json()["items"][0]["status"] == "adopted"
    again = package(setup, f, [{"event_id": first["event_id"], "command": command}])
    assert again.json()["items"][0]["error"]["reason"] == "candidate_not_pending"
