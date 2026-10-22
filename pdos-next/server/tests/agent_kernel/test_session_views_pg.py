"""Actual Start → Cancel → Continue and owned Session reads; root alone runs PG.

No model response, Session, Run outcome, qualification or permission is fabricated.
Only normal isolated synthetic parent ACL reduction uses the existing admin.
"""

import json
import os
from copy import copy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session

from pdos_next.clock import using_clock
from pdos_next.models import (
    Audit,
    Confirmation,
    Grant,
    ObjectAudience,
    Outbox,
    Product,
    Receipt,
    RequestKey,
)

# Initialize the common registry before its kernel children.
# isort: split
from pdos_next.agent_kernel.models import (
    AgentEvent,
    AgentInput,
    AgentRun,
    AgentSession,
    AgentToolCall,
)
from tests.preproject.test_evidence_commands_pg import share_request
from tests.preproject.test_g0 import create, save
from tests.test_personal_views import second_category


def actor(setup, identity):
    value = copy(setup)
    value.human = identity
    value.headers = {"Authorization": f"Bearer {setup.tokens[identity]}"}
    value.ctx = replace(setup.ctx, actor_id=identity, requester_id=identity)
    return value


def base(setup, personal=False):
    return "/v1/personal" if personal else f"/v1/categories/{setup.category}"


def start(setup, *, personal=False, **changes):
    body = {
        "goal": "合成会话：保留未核对条件，不调用模型或发布业务记录。",
        "idempotency_key": str(uuid4()),
        **changes,
    }
    response = setup.client.post(
        base(setup, personal) + "/agent-runs", headers=setup.headers, json=body
    )
    assert response.status_code == 202, response.text
    return response.json(), body


def chain(setup, *, personal=False, goal="合成原目标：先核对适用工况。", **scope):
    original, original_body = start(setup, personal=personal, goal=goal, **scope)
    cancelled = setup.client.post(
        base(setup, personal) + f"/agent-runs/{original['run_id']}/cancel", headers=setup.headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    followup, body = start(
        setup,
        personal=personal,
        goal="合成后续目标：继续核对同一原工作的未知项。",
        continue_from_run_id=original["run_id"],
    )
    assert followup["session_id"] == original["session_id"]
    assert followup["continued_from_id"] == original["run_id"]
    assert followup["status"] == "queued"
    return {
        "original": original,
        "original_request": original_body,
        "cancel": cancelled.json(),
        "continued": followup,
        "continue_request": body,
    }


def listing(setup, *, personal=False, **params):
    return setup.client.get(
        base(setup, personal) + "/agent-sessions", headers=setup.headers, params=params
    )


def runs(setup, session_id, *, personal=False, **params):
    return setup.client.get(
        base(setup, personal) + f"/agent-sessions/{session_id}/runs",
        headers=setup.headers,
        params=params,
    )


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def counts(setup):
    with Session(setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in (
                AgentSession,
                AgentRun,
                AgentEvent,
                AgentInput,
                AgentToolCall,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
                Confirmation,
            )
        }


def forbidden_cursor(response):
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "FORBIDDEN_SCOPE" and "刷新" in response.text
    assert "items" not in response.json()


def export_qa(setup, category_chain, personal_chain):
    public = os.environ.get("PDOS_AGENT_SESSIONS_QA_RESPONSE_PATH")
    private = os.environ.get("PDOS_AGENT_SESSIONS_QA_SESSION_PATH")
    if not (public or private):
        return
    bundle = {
        "session": ok(setup.client.get("/v1/session", headers=setup.headers)),
        "categories": ok(setup.client.get("/v1/categories", headers=setup.headers)),
        "category": {
            "list": ok(listing(setup)),
            "runs": ok(runs(setup, category_chain["original"]["session_id"])),
            "chain": category_chain,
        },
        "personal": {
            "list": ok(listing(setup, personal=True)),
            "runs": ok(runs(setup, personal_chain["original"]["session_id"], personal=True)),
            "chain": personal_chain,
        },
    }
    if public:
        output = Path(public)
        assert output.is_absolute(), "QA response destination must be absolute"
        output.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
        assert setup.tokens[setup.human] not in encoded
        assert "confirmation_token" not in encoded
        output.write_text(encoded + "\n", encoding="utf-8")
    if private:
        output = Path(private)
        assert output.is_absolute(), "QA session destination must be absolute"
        output = output.resolve()
        private_root = (Path(__file__).resolve().parents[3] / ".local").resolve()
        assert output.is_relative_to(private_root), "QA session must stay in pdos-next/.local"
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(
                {
                    "token": setup.tokens[setup.human],
                    "principal_id": str(setup.human),
                    "category_id": str(setup.category),
                    "category_session_id": category_chain["original"]["session_id"],
                    "category_run_id": category_chain["continued"]["run_id"],
                    "personal_session_id": personal_chain["original"]["session_id"],
                    "personal_run_id": personal_chain["continued"]["run_id"],
                },
                stream,
            )
            stream.write("\n")


def test_actual_start_cancel_continue_aggregate_same_session_and_export_last_real_state(setup):
    category, personal = chain(setup), chain(setup, personal=True)
    before = counts(setup)
    for value, is_personal in ((category, False), (personal, True)):
        page = ok(listing(setup, personal=is_personal))
        assert page["version"] == "agent-session-list/v1"
        assert page["principal_id"] == str(setup.human)
        assert page["scope"] == {
            "category_id": None if is_personal else str(setup.category),
            "proposal_id": None,
        }
        [item] = page["items"]
        assert item["session_id"] == value["original"]["session_id"]
        assert item["run_count"] == 2 and item["matched_run"] is None
        assert item["latest_run"]["run_id"] == value["continued"]["run_id"]
        assert not {"title", "archived", "pinned", "status"} & item.keys()
        detail = ok(runs(setup, item["session_id"], personal=is_personal))
        assert detail["version"] == "agent-session-runs/v1"
        assert detail["session"]["run_count"] == 2
        by_id = {row["run_id"]: row for row in detail["items"]}
        assert by_id[value["original"]["run_id"]]["status"] == "cancelled"
        assert by_id[value["continued"]["run_id"]]["status"] == "queued"
        assert (
            by_id[value["original"]["run_id"]]["conversation"]["next_run_id"]
            == value["continued"]["run_id"]
        )
        assert (
            by_id[value["continued"]["run_id"]]["conversation"]["previous_run_id"]
            == value["original"]["run_id"]
        )
        replay = setup.client.post(
            base(setup, is_personal) + "/agent-runs",
            headers=setup.headers,
            json=value["continue_request"],
        )
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == value["continued"]["run_id"]
    assert counts(setup) == before
    export_qa(setup, category, personal)
    assert counts(setup) == before
    assert before[AgentToolCall.__tablename__] == 0


def test_search_matches_old_run_and_literal_percent_underscore_backslash(setup):
    value = chain(setup, goal="合成字面检索 50%_\\ exact 保留原始符号。")
    unrelated, _ = start(setup, goal="合成不匹配 50AAA exact 不能当通配符命中。")
    for q, kind in (
        ("50%_\\", "goal"),
        (value["original"]["run_id"], "run_id"),
        (value["original"]["session_id"], "session_id"),
    ):
        [item] = ok(listing(setup, q=q))["items"]
        assert item["session_id"] == value["original"]["session_id"]
        assert (
            item["run_count"] == 2 and item["latest_run"]["run_id"] == value["continued"]["run_id"]
        )
        assert item["matched_run"]["match_kind"] == kind
        if kind != "session_id":
            assert item["matched_run"]["run_id"] == value["original"]["run_id"]
    assert len(ok(listing(setup, q="  "))["items"]) == 2
    forbidden_cursor(listing(setup, q="50%_\\", cursor=unrelated["session_id"]))


def test_stable_session_and_run_keysets_with_same_saved_clock_and_current_filter(setup):
    instant = datetime.now(UTC)
    with using_clock(lambda: instant):
        first = chain(setup)
        second, _ = start(setup, goal="合成第二独立会话。")
    expected = sorted((first["original"]["session_id"], second["session_id"]), reverse=True)
    page = ok(listing(setup, page_size=1))
    assert page["items"][0]["session_id"] == page["next_cursor"] == expected[0]
    tail = ok(listing(setup, page_size=1, cursor=page["next_cursor"]))
    assert tail["items"][0]["session_id"] == expected[1] and tail["next_cursor"] is None
    session_id = first["original"]["session_id"]
    expected_runs = sorted(
        (first["original"]["run_id"], first["continued"]["run_id"]), reverse=True
    )
    page = ok(runs(setup, session_id, page_size=1))
    assert page["items"][0]["run_id"] == page["next_cursor"] == expected_runs[0]
    tail = ok(runs(setup, session_id, page_size=1, cursor=page["next_cursor"]))
    assert tail["items"][0]["run_id"] == expected_runs[1] and tail["next_cursor"] is None
    forbidden_cursor(runs(setup, session_id, cursor=second["run_id"]))
    forbidden_cursor(listing(setup, cursor=uuid4()))


def test_sessions_remain_own_scoped_and_reject_invalid_or_foreign_cursors(setup):
    original, _ = start(setup)
    personal, _ = start(setup, personal=True)
    other = second_category(setup)
    foreign, _ = start(other)
    for reader in (actor(setup, setup.peer), actor(setup, setup.other_human)):
        response = listing(reader)
        if response.status_code == 200:
            assert response.json()["items"] == []
        else:
            assert response.status_code == 403
        assert runs(reader, original["session_id"]).status_code in (403, 404)
    assert runs(setup, original["session_id"], personal=True).status_code == 404
    assert runs(setup, personal["session_id"]).status_code == 404
    assert runs(setup, foreign["session_id"]).status_code == 404
    forbidden_cursor(listing(setup, cursor=foreign["session_id"]))
    for params in ({"page_size": 0}, {"page_size": 51}, {"cursor": "bad"}, {"q": "x" * 161}):
        assert listing(setup, **params).status_code == 422
    assert listing(setup, personal=True, proposal_id=uuid4()).status_code == 403


def test_proposal_filter_and_actual_sharing_reduction_hide_goals_before_search(setup):
    owner = actor(setup, setup.peer)
    proposal, _ = create(owner, {"title": "合成私有会话范围", "entry_kind": "new_product"})
    another, _ = create(setup, {"title": "合成另一提案", "entry_kind": "new_product"})
    save(owner, share_request(owner, proposal, visibility="audience", audience_ids=[setup.human]))
    protected, _ = start(setup, proposal_id=proposal, goal="SYNTHETIC_PRIVATE_SESSION_GOAL")
    other, _ = start(setup, proposal_id=another)
    [row] = ok(listing(setup, proposal_id=proposal))["items"]
    assert row["session_id"] == protected["session_id"]
    assert row["scope"]["proposal_id"] == proposal
    assert (
        ok(runs(setup, protected["session_id"], proposal_id=proposal))["session"]["run_count"] == 1
    )
    assert runs(setup, other["session_id"], proposal_id=proposal).status_code == 404
    forbidden_cursor(listing(setup, proposal_id=proposal, cursor=other["session_id"]))
    # Sharing accepts a nonempty named audience; remove the prior reader while
    # retaining only the owner, through the same actual preview/commit command.
    save(owner, share_request(owner, proposal, visibility="audience", audience_ids=[owner.human]))
    assert ok(listing(setup, q="SYNTHETIC_PRIVATE_SESSION_GOAL"))["items"] == []
    assert runs(setup, protected["session_id"]).status_code == 404
    assert listing(setup, proposal_id=proposal).status_code == 404
    forbidden_cursor(listing(setup, cursor=protected["session_id"]))


def test_parent_product_acl_reduction_and_expired_category_grant_recheck_reads(setup):
    peer = actor(setup, setup.peer)
    protected, _ = start(peer, product_id=str(setup.product), goal="SYNTHETIC_PRIVATE_PARENT_GOAL")
    assert ok(listing(peer))["items"][0]["session_id"] == protected["session_id"]
    with Session(setup.admin) as session, session.begin():
        session.get(Product, setup.product).visibility = "private"
        session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.object_type == "products",
                ObjectAudience.subject_id == setup.product,
                ObjectAudience.principal_id == setup.peer,
            )
        )
    assert ok(listing(peer, q="SYNTHETIC_PRIVATE_PARENT_GOAL"))["items"] == []
    assert runs(peer, protected["session_id"]).status_code == 404
    forbidden_cursor(listing(peer, cursor=protected["session_id"]))
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.peer,
            )
        )
        grant.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    assert listing(peer).status_code == 403
    assert runs(peer, protected["session_id"]).status_code == 403


def test_get_projection_selects_only_heads_and_keeps_all_closed_loop_counts_unchanged(setup):
    value = chain(setup)
    before = counts(setup)
    statements = []

    def observed(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(setup.engine, "before_cursor_execute", observed)
    try:
        ok(listing(setup, q="原目标"))
        ok(runs(setup, value["original"]["session_id"], page_size=1))
    finally:
        event.remove(setup.engine, "before_cursor_execute", observed)
    assert not any("FOR UPDATE" in sql or "FOR SHARE" in sql for sql in statements)
    assert not any(
        f"agent_runs.{column}" in sql
        for column in ("result", "read_sources", "versions", "customer_identities", "intent_key")
        for sql in statements
    )
    assert counts(setup) == before
