import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.ai.application_gateway import configured_application_gateway
from app.ai.conversation_reply import ConversationReplies, ReplyAssessment, identity
from app.ai.gateway import GatewayResult
from app.ai.provider_streaming import _observer, _thinking_observer
from app.api.ai import get_application_gateway
from app.auth.repository import AuthRepository
from app.db.schema import tables
from tests.test_application_budget_factory import factory_setup as factory_setup
from tests.test_product_conversations_api import candidate as candidate
from tests.test_product_conversations_api import colleague
from tests.test_test_runs_api import (
    client as client,
)
from tests.test_test_runs_api import (
    isolated_test_run_database as isolated_test_run_database,
)


class Gateway:
    def __init__(self, *, unavailable=False):
        self.calls = []
        self.unavailable = unavailable

    def invoke_structured(self, invocation, output_type):
        assert output_type is ReplyAssessment
        self.calls.append(invocation)
        if self.unavailable:
            return GatewayResult(
                status="degraded",
                output=None,
                error_code="MODEL_NOT_AVAILABLE",
                structured_attempts=0,
                removed_context_paths=(),
            )
        answer = (
            "你好，我们可以一起梳理。"
            if not invocation.context["history"]
            else "记得，你刚才希望一起梳理，我们继续。"
        )
        approach = "先梳理这轮目标，再结合已提供的资料回答。"
        observer = _observer.get()
        thinking = _thinking_observer.get()
        if thinking:
            thinking()
        observer('{"approach":"' + approach)
        observer(json.dumps({"approach": approach})[:-1] + ',"answer":"' + answer[:2])
        observer(
            json.dumps(
                {"approach": approach, "answer": answer, "citation_ids": []}, ensure_ascii=False
            )
        )
        return GatewayResult(
            status="succeeded",
            output=ReplyAssessment(approach=approach, answer=answer),
            error_code=None,
            structured_attempts=1,
            removed_context_paths=(),
        )


def events(response):
    assert response.status_code == 200, response.text
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def save(c, conversation, body):
    return c.save(conversation, c.message(conversation, body, reply_only=True))


def test_personal_chat_streams_continuous_replies_and_replays_without_second_model(candidate):
    c = candidate
    gateway = Gateway()
    c.client.app.dependency_overrides[get_application_gateway] = lambda: gateway
    try:
        conversation = c.create("personal")
        first = save(c, conversation, "你好，帮我一起梳理一下")
        url = f"/api/conversations/{conversation['id']}/messages/{first['id']}/reply"
        stream = events(c.client.post(url, headers=c.headers))
        assert stream[0]["type"] == "status"
        assert (
            next(item for item in stream if item["type"] == "text" and item["text"])["text"]
            == "你好"
        )
        assert stream[-2]["reply"]["status"] == "answered"
        trace = stream[-2]["reply"]["process"]
        assert trace["state"] == "completed" and trace["elapsed_ms"] >= 0
        assert trace["steps"][0]["detail"] == "先梳理这轮目标，再结合已提供的资料回答。"
        assert any(item.get("message") == "正在思考" for item in stream)
        assert c.client.get(url, headers=c.headers).json()["reply"]["process"] == trace
        assert events(c.client.post(url, headers=c.headers))[-2]["reply"] == stream[-2]["reply"]
        assert len(gateway.calls) == 1
        second = save(c, conversation, "还记得我刚刚说的事吗？")
        reply = events(
            c.client.post(
                f"/api/conversations/{conversation['id']}/messages/{second['id']}/reply",
                headers=c.headers,
            )
        )[-2]["reply"]
        assert reply["answer"].startswith("记得")
        assert gateway.calls[1].context["history"] == [
            {"role": "user", "content": first["body"]},
            {"role": "assistant", "content": stream[-2]["reply"]["answer"]},
        ]
        _, other = colleague(c)
        assert c.client.get(url, headers=other).status_code == 403
        assert c.client.post(url, headers=other).status_code == 403
        assert len(gateway.calls) == 2
        with c.scope.engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == identity(UUID(first["id"])))
                .values(run_context={"reply_source": {}})
            )
    finally:
        c.client.app.dependency_overrides.pop(get_application_gateway, None)


def test_ordinary_market_followup_does_not_require_product_intent_keywords(candidate):
    c = candidate
    conversation = c.create("market_space")
    gateway = Gateway()
    c.client.app.dependency_overrides[get_application_gateway] = lambda: gateway
    try:
        message = save(c, conversation, "我还没想清楚，你先陪我想想")
        assert message["action"] == "note"
        stream = events(
            c.client.post(
                f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply",
                headers=c.headers,
            )
        )
        assert stream[-2]["reply"]["status"] == "answered"
        assert gateway.calls[0].context["references"][0]["entity"] == "market_space"
        with c.scope.engine.connect() as connection:
            run = (
                connection.execute(
                    select(tables.agent_runs).where(
                        tables.agent_runs.c.id == identity(UUID(message["id"]))
                    )
                )
                .mappings()
                .one()
            )
            assert run["scope_kind"] == "tenant" and run["project_id"] is None
    finally:
        c.client.app.dependency_overrides.pop(get_application_gateway, None)


def test_unavailable_model_is_explicit_and_persisted_without_canned_success(candidate):
    c = candidate
    conversation = c.create("personal")
    gateway = Gateway(unavailable=True)
    c.client.app.dependency_overrides[get_application_gateway] = lambda: gateway
    try:
        message = save(c, conversation, "你好")
        url = f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply"
        value = events(c.client.post(url, headers=c.headers))[-2]["reply"]
        assert value["answer"] is None and value["error_code"] == "MODEL_NOT_AVAILABLE"
        assert value["process"]["state"] == "failed"
        assert c.client.get(url, headers=c.headers).json()["reply"] == value
    finally:
        c.client.app.dependency_overrides.pop(get_application_gateway, None)


def test_unexpected_reply_failure_finishes_stream_and_keeps_original_failure(candidate):
    class FailingGateway:
        def invoke_structured(self, *args):
            raise RuntimeError("synthetic-private-error-details")

    c = candidate
    conversation = c.create("personal")
    message = save(c, conversation, "合成异常验证")
    url = f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply"
    c.client.app.dependency_overrides[get_application_gateway] = lambda: FailingGateway()
    try:
        streamed = c.client.post(url, headers=c.headers)
        values = events(streamed)
        assert values[-1] == {"type": "done"}
        assert values[-2]["type"] == "error" and values[-2]["status"] == 500
        assert "synthetic-private-error-details" not in streamed.text
        stored = c.client.get(url, headers=c.headers).json()["reply"]
        assert stored["status"] == "unavailable" and stored["error_code"] == "REPLY_REQUEST_FAILED"
        replay = events(c.client.post(url, headers=c.headers))
        assert replay[-2]["reply"] == stored
    finally:
        c.client.app.dependency_overrides.pop(get_application_gateway, None)


@pytest.mark.parametrize("enforced", [True, False])
def test_budgeted_personal_reply_records_current_authority_context_and_settled_usage(
    candidate, factory_setup, monkeypatch, enforced
):
    from app.ai import provider_streaming
    from tests import test_application_budget_factory as factory
    from tests.test_model_budget_controller import response

    # The real gateway and budget ports run against PG; only HTTP is synthetic.
    monkeypatch.setattr(
        factory, "response", lambda: response('{"answer":"可以，我们一起梳理。","citation_ids":[]}')
    )
    monkeypatch.setattr(provider_streaming, "enabled", lambda: False)
    c = candidate
    if not enforced:
        from uuid import uuid4

        with c.scope.engine.begin() as connection:
            connection.execute(
                tables.tenant_model_settings.insert(),
                dict(
                    id=uuid4(),
                    tenant_id=c.scope.tenant_id,
                    provider="minimax",
                    model="MiniMax-M2.7",
                    daily_token_budget=1,
                    token_budget_enforced=False,
                ),
            )
    conversation = c.create("personal")
    message = save(c, conversation, "陪我一起想想")
    context = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    environment, calls, _ = factory_setup
    from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY
    from tests.test_input_metering import publication

    path, _, meter_digest = publication(
        Path(environment[METER_PATH_KEY]).parent,
        qualified_input_limit=4096,
    )
    environment = {**environment, METER_PATH_KEY: str(path), METER_DIGEST_KEY: meter_digest}
    with configured_application_gateway(c.scope.engine, environment) as gateway:
        result = ConversationReplies(c.scope.engine, gateway).answer(
            context, UUID(conversation["id"]), UUID(message["id"]), lambda _: None
        )
    assert result["status"] == "answered", result
    assert calls
    with c.scope.engine.connect() as connection:
        run_id = identity(UUID(message["id"]))
        grant = (
            connection.execute(
                select(tables.application_authorizations).where(
                    tables.application_authorizations.c.run_id == run_id
                )
            )
            .mappings()
            .one()
        )
        assert grant["body"]["purpose"] == "xiaopai_reply" and grant["project_id"] is None
        assert connection.execute(
            select(tables.application_context_observations.c.id).where(
                tables.application_context_observations.c.run_id == run_id
            )
        ).first()
        journal = (
            connection.execute(
                select(tables.budget_journal)
                .where(tables.budget_journal.c.run_id == run_id)
                .order_by(tables.budget_journal.c.revision.desc())
            )
            .mappings()
            .first()
        )
        assert journal["reservation_status"] == "settled"
        if not enforced:
            assert journal["charged_tokens"] > 1


def test_stop_request_cancels_the_original_generation_without_restarting(candidate):
    c = candidate
    conversation = c.create("personal")
    message = save(c, conversation, "先回复再停止")
    url = f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply"

    class StoppingGateway(Gateway):
        def invoke_structured(self, invocation, output_type):
            generated = super().invoke_structured(invocation, output_type)
            assert c.client.post(url + "/cancel", headers=c.headers).status_code == 200
            return generated

    gateway = StoppingGateway()
    c.client.app.dependency_overrides[get_application_gateway] = lambda: gateway
    try:
        result = events(c.client.post(url, headers=c.headers))[-2]["reply"]
        assert result["status"] == "unavailable" and result["error_code"] == "REPLY_CANCELLED"
        assert result["answer"] is None
        assert result["process"]["state"] == "stopped"
        events(c.client.post(url, headers=c.headers))
        assert len(gateway.calls) == 1
    finally:
        c.client.app.dependency_overrides.pop(get_application_gateway, None)


def test_stop_before_a_reply_starts_does_not_falsely_acknowledge_cancellation(candidate):
    c = candidate
    conversation = c.create("personal")
    message = save(c, conversation, "等待真实运行回执")
    url = f"/api/conversations/{conversation['id']}/messages/{message['id']}/reply"
    response = c.client.post(url + "/cancel", headers=c.headers)
    assert response.status_code == 409
    assert "尚未启动" in response.json()["detail"]["message"]
    assert c.client.get(url, headers=c.headers).json()["reply"] is None


def test_conversation_history_is_bounded_and_explicit_about_older_omissions(candidate):
    c = candidate
    conversation = c.create("personal")
    gateway = Gateway()
    for number in range(22):
        message = save(c, conversation, f"第{number}轮说明")
    context = AuthRepository(c.scope.engine).find_user_context(c.scope.owner_id)
    ConversationReplies(c.scope.engine, gateway).answer(
        context, UUID(conversation["id"]), UUID(message["id"]), lambda _: None
    )
    assert len(gateway.calls[0].context["history"]) == 20
    assert gateway.calls[0].context["history_truncated"] is True
    assert gateway.calls[0].context["history"][0]["content"] == "第1轮说明"
