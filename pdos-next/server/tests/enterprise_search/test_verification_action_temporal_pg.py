"""Actual parent answer→action→T1 preparation→Human request; offline provider only."""

# ruff: noqa: F401, F811 -- imported fixtures retain the actual native dependency tree

import asyncio
import os
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import pytest
from build_operational_facts.fixtures import configuration, definition, operational_work, project
from build_start.test_transactions import ready_work
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from verification_handoff.fixtures import artifact, handoff_work, known_configuration

from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall, TenantSkillEnablement
from pdos_next.database import tenant_session
from pdos_next.domain.verification_execution.models import VerificationPreparation
from pdos_next.domain.verification_front.models import FormalVerificationRequest
from pdos_next.models import Receipt
from tests.enterprise_search.test_retrieval_pg import index
from tests.enterprise_search.verification_action_harness import (
    PREPARATION,
    REQUEST,
    VerificationClient,
    actual_runtime,
    bound_target,
    candidate,
    question_ready,
    start,
)
from tests.enterprise_search.verification_negative_fixture import (
    change_execution_revision,
    private_action_work,
    restricted_materials,
    revoke_auxiliary,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("PDOS_TEMPORAL_ADDRESS")
    or not os.environ.get("PDOS_CHECKPOINT_DATABASE_URL"),
    reason="Explicit guarded PG, verified local Temporal and checkpoint runtime required",
)


def totals(person):
    with Session(person.admin) as session:
        return tuple(session.scalar(select(func.count()).select_from(model).where(
            model.tenant_id == person.tenant,
        )) for model in (VerificationPreparation, FormalVerificationRequest))


async def discussion(runtime, selection):
    identity, handle = await start(runtime, {
        "goal": "以前漏气怎么处理？", "idempotency_key": str(uuid4()),
        "product_id": str(runtime.person.product), "project_id": selection["project_id"],
    }, accepted_statuses=("completed", "partial"))
    response = await runtime.http.get(runtime.path + f"/{identity}",
                                      headers=runtime.person.headers)
    assert response.status_code == 200, response.text
    answer = response.json()["result"]["result"]["assistant"]
    assert answer["lookup"] == "cited" and len(answer["citation_ids"]) == 1
    assert answer["sources"][0]["quote"] == "更换密封圈"
    if response.json()["status"] == "partial":
        # The native project fixture contains unindexed records; this selected
        # fixed citation remains verified while overall coverage stays partial.
        assert any(group["coverage"]["status"] == "partial"
                   for group in answer["search_groups"])
        assert answer["sources"][0]["read_basis_status"] == "current"
    assert "RAW_ONLY_CHILD_MARKER" not in str(await handle.fetch_history())
    return identity, answer


async def continuation(runtime, parent, answer, selection, *, missing=False):
    runtime.provider.phase = "action"
    payload = {
        "goal": "依据上条讨论准备复验，样本数量请先问我。" if missing
        else "依据上条讨论准备3件复验，方法与合格判据未知保留待确认。",
        "idempotency_key": str(uuid4()), "continue_from_run_id": str(parent),
        "sources": [{"artifact_id": runtime.provider.source["artifact_id"],
                     "expected_revision": runtime.provider.source["expected_revision"]}],
        "verification_action": {"selection": selection,
                                "citation_ids": answer["citation_ids"]},
    }
    identity, handle = await start(runtime, payload, complete=not missing)
    if missing:
        before = totals(runtime.person)
        event = await question_ready(runtime, identity)
        question = event["questions"][0]
        assert question["id"] == "sample_count" and question["recommended"] is None
        assert runtime.provider.arguments is None
        response = await runtime.http.get(runtime.path + f"/{identity}/candidates",
                                          headers=runtime.person.headers)
        assert response.status_code == 200 and response.json()["items"] == []
        assert totals(runtime.person) == before
        answer_payload = {"answers": {"sample_count": "3"}, "idempotency_key": str(uuid4())}
        answered = await runtime.http.post(runtime.path + f"/{identity}/answers",
                                          headers=runtime.person.headers, json=answer_payload)
        assert answered.status_code == 202, answered.text
        result = await asyncio.wait_for(handle.result(), 90)
        assert result["status"] == "completed", result
        assert totals(runtime.person) == before
    before_calls = runtime.provider.calls
    replay = await runtime.http.post(runtime.path, headers=runtime.person.headers, json=payload)
    assert replay.status_code == 202 and replay.json()["run_id"] == str(identity)
    row = await candidate(runtime, identity)
    assert row["state"] == "pending" and row["target"] == selection and row["basis_count"] >= 2
    assert row["receipt"] is row["preparation"] is None
    assert row["command"]["operation"] == PREPARATION
    assert row["command"]["payload"]["items"][0]["sample_count"] == 3
    assert row["command"]["payload"]["items"][0]["method"] is None
    assert row["command"]["payload"]["items"][0]["criterion"] is None
    assert runtime.provider.calls == before_calls
    person = runtime.person
    with tenant_session(person.engine, person.tenant, actor_id=person.human,
                        category_id=person.category) as session:
        run = session.get(AgentRun, identity)
        assert run.continued_from_id == parent
        assert run.versions["verification_action"]["request_id"] == (
            row["command"]["payload"]["request_id"]
        )
        event = session.get(AgentEvent, UUID(row["event_id"]))
        source = event.body["source"]
        model = session.get(AgentToolCall, UUID(source["model_call_id"]))
        assert model.state == "completed" and model.tool == "model" and model.run_id == identity
        assert source["skill"]["key"] == "test_verification"
        actual = model.result["calls"][source["response_index"]]
        assert actual["name"] == PREPARATION
        assert actual["arguments"] == runtime.provider.arguments
        enabled = session.scalar(select(TenantSkillEnablement).where(
            TenantSkillEnablement.tenant_id == person.tenant,
            TenantSkillEnablement.skill_key == "test_verification",
        ))
        assert enabled.enabled and not enabled.pilot and not enabled.review_case_refs
    assert "VERIFICATION_EXECUTION_RAW_ONLY" not in str(await handle.fetch_history())
    return identity, row


async def command(runtime, value, *, preview=False):
    response = await runtime.http.post(
        f"/v1/categories/{runtime.person.category}/commands" + ("/preview" if preview else ""),
        headers=runtime.person.headers, json=value,
    )
    return response


async def prepared(runtime, identity, pending, *, lose=False):
    response = await command(runtime, pending["command"], preview=True)
    assert response.status_code == 200, response.text
    confirmed = response.json()["command"]
    assert confirmed["payload"]["confirmation_token"]
    if lose:
        runtime.transport.drop_command_id = confirmed["command_id"]
        with pytest.raises(httpx.ReadError, match="after commit"):
            await command(runtime, confirmed)
        recovered = await candidate(runtime, identity)
        assert recovered["state"] == "adopted" and recovered["preparation"]
        receipt_id = recovered["receipt"]["id"]
    else:
        saved = await command(runtime, confirmed)
        assert saved.status_code == 200, saved.text
        receipt_id = saved.json()["id"]
    replay = await command(runtime, confirmed)
    assert replay.status_code == 200 and replay.json()["id"] == receipt_id, replay.text
    adopted = await candidate(runtime, identity)
    assert adopted["state"] == "adopted" and adopted["receipt"]["id"] == receipt_id
    assert adopted["command"] == pending["command"]
    binding = adopted["preparation"]
    assert binding["receipt_id"] == receipt_id
    assert binding["preparation_id"] == replay.json()["subject_id"]
    return adopted


async def request_command(runtime, adopted):
    person = runtime.person
    response = await runtime.http.get(
        f"/v1/categories/{person.category}/products/{person.product}/verification-professional",
        headers=person.headers,
    )
    assert response.status_code == 200, response.text
    prep = next(row for row in response.json()["preparations"]
                if row["id"] == adopted["preparation"]["preparation_id"])
    assert prep["capabilities"]["request_create"] and prep["source_status"] == "current"
    assert prep["revision"] == adopted["preparation"]["expected_preparation_revision"]
    assert prep["sha256"] == adopted["preparation"]["preparation_sha256"]
    return {
        "command_id": str(uuid4()), "idempotency_key": str(uuid4()), "operation": REQUEST,
        "category_id": str(person.category), "product_id": str(person.product),
        "expected_revision": adopted["command"]["expected_revision"],
        "source_read_set": prep["required_source_read_set"],
        "payload": {"request_id": str(uuid4()), "preparation_id": prep["id"],
                    "expected_preparation_revision": prep["revision"],
                    "preparation_sha256": prep["sha256"],
                    "reason": "本人按固定准备建立请求，未交样或开测"},
    }


def materials(work):
    person, selection = bound_target(work)
    discussion_source = artifact(work.setup, "漏气。更换密封圈。RAW_ONLY_CHILD_MARKER",
                                 "Synthetic historical discussion")
    index(person, UUID(discussion_source["artifact_id"]))
    execution = artifact(work.setup, "Synthetic drawing\nVERIFICATION_EXECUTION_RAW_ONLY",
                         "Synthetic current execution definition")
    return person, selection, discussion_source, execution


def test_actual_verification_chain_recovers_lost_responses_without_second_model(
    handoff_work, monkeypatch,
):
    work = handoff_work
    person, selection, _discussion, execution = materials(work)
    provider = VerificationClient(execution, work.scope.purpose)
    before = totals(person)

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await discussion(runtime, selection)
            identity, pending = await continuation(runtime, parent, answer, selection)
            calls = provider.calls
            assert totals(person) == before
            adopted = await prepared(runtime, identity, pending, lose=True)
            assert totals(person) == (before[0] + 1, before[1])
            value = await request_command(runtime, adopted)
            runtime.transport.drop_command_id = value["command_id"]
            with pytest.raises(httpx.ReadError, match="after commit"):
                await command(runtime, value)
            assert totals(person) == (before[0] + 1, before[1] + 1)
            saved = await command(runtime, value)
            again = await command(runtime, value)
            assert saved.status_code == again.status_code == 200, saved.text
            assert saved.json()["id"] == again.json()["id"]
            assert runtime.transport.lost == 2 and provider.calls == calls
            assert totals(person) == (before[0] + 1, before[1] + 1)
            with Session(person.admin) as session:
                row = session.get(FormalVerificationRequest, UUID(saved.json()["subject_id"]))
                assert row.preparation_id == UUID(adopted["preparation"]["preparation_id"])
                assert row.preparation_sha256 == adopted["preparation"]["preparation_sha256"]
                assert row.request_snapshot["status"] == "draft"
                assert not row.request_snapshot["samples"]
                assert not row.request_snapshot["acceptances"]
                assert row.request_snapshot["timeline"]["actual_start"] is None
                for receipt_id in (adopted["receipt"]["id"], saved.json()["id"]):
                    receipt = session.get(Receipt, UUID(receipt_id))
                    assert receipt.actor_id == receipt.requester_id == person.human
                    assert receipt.agent_run_id is receipt.run_id is None
    asyncio.run(actual())


def test_missing_count_interrupts_real_graph_and_only_explicit_answer_becomes_three(
    handoff_work, monkeypatch,
):
    work = handoff_work
    person, selection, _discussion, execution = materials(work)
    provider = VerificationClient(execution, work.scope.purpose, missing_count=True)
    before = totals(person)

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await discussion(runtime, selection)
            await continuation(runtime, parent, answer, selection, missing=True)
            assert provider.arguments["items"][0]["sample_count"] == 3
            assert totals(person) == before  # Asking and preparing never save domain rows.
    asyncio.run(actual())


@pytest.mark.parametrize("damage,at", [
    ("aux_permission", "before_preview"), ("aux_permission", "after_preview"),
    ("execution_version", "after_preview"), ("aux_permission", "after_preparation"),
])
def test_actual_authority_changes_block_native_adoption_at_each_boundary(
    private_action_work, monkeypatch, damage, at,
):
    work = private_action_work
    sources = restricted_materials(work)
    person, selection, execution = sources.person, sources.selection, sources.execution
    provider = VerificationClient(execution, work.scope.purpose)
    before = totals(person)

    async def actual():
        async with actual_runtime(person, provider, monkeypatch) as runtime:
            parent, answer = await discussion(runtime, selection)
            identity, pending = await continuation(runtime, parent, answer, selection)
            value = deepcopy(pending["command"])
            if at == "after_preview":
                preview = await command(runtime, value, preview=True)
                assert preview.status_code == 200, preview.text
                value = preview.json()["command"]
            elif at == "after_preparation":
                adopted = await prepared(runtime, identity, pending)
                value = await request_command(runtime, adopted)
            if damage == "execution_version":
                change_execution_revision(sources)
            else:
                revoke_auxiliary(sources)
            calls = provider.calls
            unavailable = await candidate(runtime, identity)
            assert unavailable["state"] == "unavailable" and unavailable["command"] is None
            denied = await command(runtime, value, preview=at == "before_preview")
            assert denied.status_code in {403, 409}, denied.text
            assert totals(person) == (before[0] + (at == "after_preparation"), before[1])
            assert provider.calls == calls
    asyncio.run(actual())
