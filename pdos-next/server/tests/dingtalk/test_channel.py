"""Offline verified adapter, complete-output policy and durable receipt regressions."""

import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pdos_agent_runtime.graph import in_registered_agent_graph
from pdos_next.clock import now
from pdos_next.dingtalk.accounts import credential
from pdos_next.dingtalk.graph import execute
from pdos_next.dingtalk.ports import ChannelRuntime
from pdos_next.dingtalk.projection import payload, run_link, whole_answer
from pdos_next.dingtalk.runtime import ChannelService, configured, delivery_key
from pdos_next.dingtalk.schemas import BindingFinish, ChannelReference, ShareConfirm
from pdos_next.dingtalk.synthetic import SyntheticAdapter, SyntheticKms
from pdos_next.errors import DomainError
from pdos_next.service import digest
from pydantic import ValidationError


@pytest.fixture
def channel():
    app = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        corp_id="synthetic-corp",
        active=True,
        secret_arn="acs:kms:local:0:secret/dingtalk-test",
        secret_version="s1",
    )
    kms = SyntheticKms()
    kms.install(app.secret_arn, app.secret_version)
    adapter = SyntheticAdapter()
    runtime = ChannelRuntime(kms, adapter, "https://pdos.invalid")
    return app, runtime


def event(app, **changes):
    return {
        "corp_id": app.corp_id,
        "external_user_id": "external-self",
        "message_id": "m1",
        "conversation_kind": "group",
        "conversation_id": "g1",
        "mentioned": True,
        "text": "这份漏气依据如何处理？",
        **changes,
    }


def test_signed_single_message_has_no_history_or_secret_context(channel):
    app, runtime = channel
    secret = credential(runtime, app)
    body, signature, at = runtime.adapter.envelope(app, secret, event(app))
    verified = runtime.adapter.verify_message(app, secret, body, signature=signature, timestamp=at)
    assert verified.external_user_id == "external-self" and verified.mentioned
    assert verified.envelope_sha256 == digest(body.decode())
    assert verified.text not in repr(verified) and secret.get_secret_value() not in repr(verified)
    assert runtime.kms.reads == [(app.secret_arn, "s1")]
    with pytest.raises(ValidationError):
        runtime.adapter.envelope(app, secret, event(app, history=[{"text": "other member"}]))


@pytest.mark.parametrize("change", ["signature", "body", "corporation", "old", "future"])
def test_invalid_or_replayed_envelope_time_is_not_an_identity(channel, change):
    app, runtime = channel
    secret = credential(runtime, app)
    body, signature, at = runtime.adapter.envelope(app, secret, event(app))
    if change == "signature":
        signature = "0" * 64
    elif change == "body":
        body = body.replace(b"g1", b"g2")
    elif change == "corporation":
        body, signature, at = runtime.adapter.envelope(app, secret, event(app, corp_id="another"))
    else:
        date = now() + timedelta(seconds=-301 if change == "old" else 31)
        body, signature, at = runtime.adapter.envelope(app, secret, event(app), at=date)
    with pytest.raises(DomainError) as failure:
        runtime.adapter.verify_message(app, secret, body, signature=signature, timestamp=at)
    assert failure.value.code == "FORBIDDEN_SCOPE" and runtime.adapter.send_count == 0


def test_external_identity_is_bound_to_exact_nonce_app_and_corporation(channel):
    app, runtime = channel
    secret = credential(runtime, app)
    state = "synthetic-256-bit-test-state"
    code = runtime.adapter.issue_code(app, "external-self", state)
    identity = runtime.adapter.exchange_identity(app, secret, code, digest(state))
    assert identity.application_id == app.id and identity.state_sha256 == digest(state)
    with pytest.raises(DomainError):
        runtime.adapter.exchange_identity(app, secret, code, digest(state))
    code = runtime.adapter.issue_code(app, "external-self", state)
    with pytest.raises(DomainError):
        runtime.adapter.exchange_identity(app, secret, code, digest("different nonce"))
    assert runtime.adapter.send_count == 0


def test_kms_rotation_and_disabled_app_have_no_credential_fallback(channel):
    app, runtime = channel
    runtime.kms.install(app.secret_arn, "s2")
    with pytest.raises(DomainError):
        credential(runtime, app)
    assert runtime.kms.reads == []
    app.active = False
    with pytest.raises(DomainError):
        credential(runtime, app)
    with pytest.raises(DomainError):
        configured(SimpleNamespace())


def answer(**changes):
    source = {
        "customer_original": False,
        "source_id": str(uuid4()),
        "source_revision": 1,
        "content_hash": "a" * 64,
    }
    args = {
        "output": {
            "summary": "漏气的当前分析：应先核对密封圈。",
            "result": {
                "assistant": {
                    "sources": [
                        {
                            "citation_id": "c1",
                            "title": "实际依据",
                            "quote": "更换密封圈",
                            "url": "/api/private-owner-ledger",
                        }
                    ],
                }
            },
        },
        "footprint": {"c1": source},
        "run_categories": ["internal"],
        "customer_identities": [],
        "tools": ["model", "assistant.search", "assistant.extract"],
    }
    args.update(changes)
    return whole_answer(**args)


@pytest.mark.parametrize("taint", ["run", "identity", "cited", "uncited_dependency"])
def test_customer_taint_withholds_entire_derived_answer_not_only_quotes(taint):
    args = {}
    if taint == "run":
        args["run_categories"] = ["customer_original"]
    elif taint == "identity":
        args["customer_identities"] = ["actual-server-customer-id"]
    else:
        args["footprint"] = {
            "c1": {"customer_original": taint == "cited"},
            "uncited": {"customer_original": taint == "uncited_dependency"},
        }
    result = answer(**args)
    assert result.withheld_reason == "customer_derived"
    assert result.body == "这次结果请在 PDOS 登录后查看。"
    assert not result.citations and not result.footprint
    assert "密封圈" not in result.body


@pytest.mark.parametrize("change", ["tool", "inputs", "missing", "empty"])
def test_uncovered_dependency_is_not_made_safe_by_omitting_a_citation(change):
    args = (
        {"tools": ["model", "mcp.read"]}
        if change == "tool"
        else (
            {"has_uncovered_inputs": True}
            if change == "inputs"
            else {"footprint": {"c1": {}}}
            if change == "missing"
            else {"footprint": {}}
        )
    )
    result = answer(**args)
    assert result.withheld_reason == "dependency_unverified" and not result.citations
    assert "密封圈" not in result.body


def test_default_group_answer_is_private_and_explicit_share_omits_quotes(channel):
    app, runtime = channel
    message = SimpleNamespace(conversation_id="g1")
    binding = SimpleNamespace(external_user_id="external-self")
    result = answer()
    link = run_link(runtime.public_base_url, uuid4())
    private = payload(phase="answer", message=message, binding=binding, answer=result, link=link)
    assert private["target_kind"] == "direct" and private["target_id"] == "external-self"
    shared = payload(phase="share", message=message, binding=binding, answer=result, link=link)
    assert shared["target_kind"] == "group" and shared["text"] == result.body
    assert "citations" not in shared
    for name in ["public", "artifact", "quote", "密封圈"]:
        assert name not in link
    assert "?" not in link and "#" not in link


def test_quotes_require_complete_current_membership_and_drop_owner_ledger_urls(channel):
    app, runtime = channel
    members = runtime.adapter.set_members(app, "g1", ["external-self", "peer"])
    args = dict(
        phase="share",
        message=SimpleNamespace(conversation_id="g1"),
        binding=SimpleNamespace(external_user_id="external-self"),
        answer=answer(),
        link=run_link(runtime.public_base_url, uuid4()),
        include_citations=True,
        members=members,
    )
    denied = payload(**args, citations_allowed=False)
    assert "citations" not in denied and "membership_version" not in denied
    allowed = payload(**args, citations_allowed=True)
    assert allowed["citations"][0]["quote"] == "更换密封圈"
    assert "url" not in allowed["citations"][0]
    runtime.adapter.set_members(app, "g1", ["external-self", "unbound-new-member"])
    with pytest.raises(DomainError):
        runtime.adapter.send(app, credential(runtime, app), uuid4(), allowed)
    assert runtime.adapter.send_count == 0


def test_lost_send_response_has_one_send_and_lookup_only_recovery(channel):
    app, runtime = channel
    key = delivery_key(uuid4(), "answer")
    body = {"target_kind": "direct", "target_id": "self", "text": "actual projected answer"}
    row = SimpleNamespace(
        id=uuid4(),
        state="sending",
        payload_sha256=digest(body),
        error_code=None,
        phase="answer",
        attempts=1,
        provider_receipt=None,
    )
    runtime.adapter.lose_after_send.add(key)
    with pytest.raises(DomainError):
        runtime.adapter.send(app, credential(runtime, app), key, body)
    assert runtime.adapter.send_count == 1
    receipt = runtime.adapter.lookup(app, credential(runtime, app), key)
    ChannelService.accept_receipt(row, receipt)
    assert row.state == "delivered" and row.provider_receipt["payload_sha256"] == digest(body)
    assert runtime.adapter.send_count == runtime.adapter.lookup_count == 1
    before = deepcopy(row.__dict__)
    assert ChannelService.status(row)["state"] == "delivered"
    assert row.__dict__ == before


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        {},
        {"provider": "another"},
        {"provider": "dingtalk", "payload_sha256": "wrong", "message_id": "x"},
    ],
)
def test_invalid_receipt_stays_unknown_without_claiming_delivery(receipt):
    row = SimpleNamespace(state="sending", payload_sha256="a" * 64, error_code=None)
    ChannelService.accept_receipt(row, receipt)
    assert row.state == "unknown" and row.error_code == "EXTERNAL_OUTCOME_UNKNOWN"


def test_deterministic_completion_graph_enters_existing_registered_xiaopai_boundary():
    calls = []

    class Service:
        def tick(self, ref):
            assert in_registered_agent_graph()
            calls.append(ref)
            return {"state": "delivered", "phase": "answer"}

    ref = ChannelReference(tenant_id=uuid4(), message_id=uuid4())
    assert execute(Service(), ref.model_dump(mode="json"))["state"] == "delivered"
    assert calls == [ref] and not in_registered_agent_graph()


def test_external_payloads_cannot_supply_owner_scope_proofs_or_credentials():
    raw = {"application_id": str(uuid4()), "state": "test-state", "auth_code": "test-code"}
    for key in ["owner_id", "tenant_id", "actor_id", "run_id", "source_proof", "credential"]:
        with pytest.raises(ValidationError):
            BindingFinish.model_validate({**raw, key: str(uuid4())})
    assert "test-code" not in repr(BindingFinish.model_validate(raw))
    with pytest.raises(ValidationError):
        ShareConfirm.model_validate(
            {
                "run_id": str(uuid4()),
                "preview_digest": "a" * 64,
                "request_key": str(uuid4()),
                "audience_covered": True,
            }
        )
    assert json.dumps(raw)  # Inputs are synthetic only; no secret material enters messages.
