"""Actual proposal-bound runs and current read scope; no provider calls."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.bindings import ModelBinding, SkillBinding, execution_key
from pdos_next.agent.kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent.kernel.disclosure import disclosure_digest
from pdos_next.agent.kernel.execution import scope_for_run
from pdos_next.agent.kernel.models import AgentEvent, AgentRun, AgentToolCall, TenantSkillEnablement
from pdos_next.core.models import Grant
from pdos_next.core.service import digest
from tests.categories.preproject.test_g0 import create, post, read, request
from tests.categories.preproject.test_g0 import work as work


def start(setup, proposal_id=None):
    body = {"goal": "Synthetic proposal draft and gaps", "idempotency_key": str(uuid4())}
    if proposal_id:
        body["proposal_id"] = proposal_id
    path = f"/v1/categories/{setup.category}/agent-runs"
    response = setup.client.post(path, headers=setup.headers, json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"], body


@pytest.mark.parametrize("cancelled", [False, True])
def test_g0_candidate_uses_actual_proposal_revision_and_owner_confirmation(work, cancelled):
    proposal_id, _ = create(work)
    item = read(work, proposal_id).json()["items"][0]
    patch = request(work, "proposal.item.patch", {
        "proposal_id": proposal_id,
        "ops": [{"kind": item["kind"], "item_id": item["item_id"],
                 "base_version": item["version"],
                 "content": {**item["content"], "text": "复核稿"}}],
    })
    assert post(work, patch).status_code == 200
    revision = read(work, proposal_id).json()["revision"]
    assert revision > 1
    run_id, _ = start(work, proposal_id)
    owner = Bootstrap(work.engine, ports=RuntimePorts())
    route = SimpleNamespace(version="synthetic@1", digest=digest("synthetic route"))
    owner.route = lambda *_: route
    skill = owner.catalog.configuration("proposal_drafting")
    skill_event, model_id = uuid4(), uuid4()
    arguments = {"proposal_id": proposal_id, "expected_revision": revision,
                 "reviewer_id": str(work.peer)}
    with Session(work.admin) as session, session.begin():
        run = session.get(AgentRun, UUID(run_id))
        scope = scope_for_run(run)
        binding = ModelBinding(
            model_version=route.version, model_route_digest=route.digest,
            tool_definitions_digest=disclosure_digest(
                owner.registry, "main", skill.operations, scope,
            ),
            prompt_digest=digest("synthetic prefix"), isolation="main", cancel_epoch=0,
            loaded_skills=(SkillBinding(key=skill.key, version=skill.version, digest=skill.digest,
                                       load_event_id=skill_event),),
        )
        run.versions = {**run.versions, "model_version": route.version,
                        "model_route_digest": route.digest,
                        "tool_definitions": {"main": binding.tool_definitions_digest},
                        "prompt_prefixes": {"main": binding.prompt_digest}}
        session.add_all([
            TenantSkillEnablement(tenant_id=work.tenant, skill_key=skill.key, enabled=True),
            AgentEvent(id=skill_event, tenant_id=work.tenant, run_id=run.id, sequence=2,
                       body={"type": "skill_loaded", "key": skill.key, "version": skill.version,
                             "digest": skill.digest, "isolation": "main"}),
            AgentToolCall(id=model_id, tenant_id=work.tenant, run_id=run.id, tool="model",
                          call_key=str(model_id), state="completed", input_digest=digest("input"),
                          execution_binding=binding.model_dump(mode="json"),
                          result={"calls": [{"name": "proposal.g0.submit",
                                             "arguments": arguments}]}),
        ])
    key = execution_key(scope.run_id, model_id, 0)
    spec = owner.registry.get("proposal.g0.submit")
    prepared = owner.prepare_candidate(scope, spec, arguments, key)
    assert prepared["event_id"] == owner.prepare_candidate(scope, spec, arguments, key)["event_id"]
    path = f"/v1/categories/{work.category}/agent-runs/{run_id}/candidates"
    page = work.client.get(path, headers=work.headers)
    assert page.status_code == 200, page.text
    item = page.json()["items"][0]
    assert item["state"] == "pending" and item["command"] == prepared["command"]
    command = item["command"]
    assert command["expected_revision"] == revision
    assert post(work, command, actor=work.peer, preview=True).status_code in {403, 404}
    forged = {**command, "payload": {**command["payload"], "reviewer_id": str(work.human)}}
    assert post(work, forged, preview=True).status_code == 403
    checked = post(work, command, preview=True)
    assert checked.status_code == 200, checked.text
    if cancelled:
        cancel = work.client.post(
            path.removesuffix("/candidates") + "/cancel", headers=work.headers,
        )
        assert cancel.status_code == 200, cancel.text
        response = post(work, checked.json()["command"])
        assert response.json()["code"] == "CANCELLED_RUN", response.text
        assert read(work, proposal_id).json()["status"] == "draft"
        return
    response = post(work, checked.json()["command"])
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["agent_run_id"] is None and receipt["subject_id"] == proposal_id
    assert receipt["result"]["g0_candidate_event_id"] == item["event_id"]
    assert post(work, checked.json()["command"]).json()["id"] == receipt["id"]
    adopted = work.client.get(path, headers=work.headers).json()["items"][0]
    assert adopted["state"] == "adopted" and adopted["receipt"]["id"] == receipt["id"]


def test_history_and_replay_use_actual_proposal_scope(setup):
    first, _ = create(setup, {"title": "Synthetic proposal one", "entry_kind": "new_product"})
    other, _ = create(setup, {"title": "Synthetic proposal two", "entry_kind": "new_product"})
    a, body = start(setup, first)
    b, _ = start(setup, first)
    c, _ = start(setup, other)
    start(setup)
    path = f"/v1/categories/{setup.category}/agent-runs"
    page = setup.client.get(
        path, headers=setup.headers, params={"proposal_id": first, "page_size": 1}
    ).json()
    assert [(r["run_id"], r["proposal_id"]) for r in page["items"]] == [(b, first)]
    tail = setup.client.get(
        path, headers=setup.headers, params={"proposal_id": first, "cursor": page["next_cursor"]}
    ).json()
    assert [r["run_id"] for r in tail["items"]] == [a] and tail["next_cursor"] is None
    assert (
        setup.client.get(
            path, headers=setup.headers, params={"proposal_id": first, "cursor": c}
        ).status_code
        == 403
    )
    detail = setup.client.get(path + "/" + a, headers=setup.headers).json()
    assert detail["proposal_id"] == first and detail["product_id"] is None
    repeat = setup.client.post(path, headers=setup.headers, json=body)
    assert repeat.status_code == 202 and repeat.json()["run_id"] == a
    with Session(setup.admin) as session:
        row = session.get(AgentRun, UUID(a))
        assert row.proposal_id == UUID(first) and row.private_context
        assert row.requester_id == setup.human and row.writer_id == setup.agent
        assert (
            session.scalar(
                select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
            )
            == 4
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AgentToolCall)
                .where(AgentToolCall.tenant_id == setup.tenant)
            )
            == 0
        )


def test_proposal_history_needs_current_audience_and_category_entry(setup):
    identity, _ = create(
        setup, {"title": "Synthetic private proposal", "entry_kind": "new_product"}
    )
    run, _ = start(setup, identity)
    path = f"/v1/categories/{setup.category}/agent-runs"
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.get(path, headers=peer, params={"proposal_id": identity}).status_code == 404
    assert (
        setup.client.get(
            "/v1/personal/agent-runs", headers=setup.headers, params={"proposal_id": identity}
        ).status_code
        == 403
    )
    assert (
        setup.client.get(path, headers=setup.headers, params={"proposal_id": "invalid"}).status_code
        == 422
    )
    with Session(setup.admin) as session, session.begin():
        session.delete(
            session.scalar(
                select(Grant).where(
                    Grant.category_id == setup.category, Grant.principal_id == setup.human
                )
            )
        )
    for suffix in ("/" + run, "/" + run + "/events", "/" + run + "/candidates"):
        assert setup.client.get(path + suffix, headers=setup.headers).status_code == 403
    assert (
        setup.client.get(path, headers=setup.headers, params={"proposal_id": identity}).status_code
        == 403
    )
