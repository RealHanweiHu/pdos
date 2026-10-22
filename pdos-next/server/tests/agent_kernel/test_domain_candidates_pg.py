"""Synthetic stored model → durable candidate → actual human receipt; no provider calls."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentToolCall
from pdos_next.domain.preproject.models import PreparedCandidate
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Receipt, now
from pdos_next.service import digest
from tests.products.test_definition_item_commands_pg import confirmed
from tests.products.test_definition_item_revert_pg import agent_fixture
from tests.products.test_platform_links_pg import counts, payload

OP = "platform.link.create"


def fixture(setup):
    arguments = payload(setup)
    f = agent_fixture(setup, arguments, operation=OP, skill_key="derivative_diff")
    bootstrap = Bootstrap(setup.engine)
    bootstrap.route = lambda *_: f.route
    f.bootstrap = bootstrap
    return f


def prepare(f, *, model_id=None, arguments=None):
    return f.bootstrap.prepare_candidate(
        f.scope,
        f.bootstrap.registry.get(OP),
        arguments or f.arguments,
        execution_key(f.scope.run_id, model_id or f.model.id, 0),
    )


def read(setup, f, *, query="", actor=None):
    return setup.client.get(
        f"/v1/categories/{setup.category}/agent-runs/{f.scope.run_id}/candidates{query}",
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )


def test_actual_preparation_is_durable_deduplicated_and_reads_do_not_write(setup):
    f = fixture(setup)
    before = counts(setup)
    first = prepare(f)
    assert prepare(f) == first
    assert counts(setup) == before
    with Session(setup.admin) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(PreparedCandidate)
                .where(
                    PreparedCandidate.run_id == f.scope.run_id,
                )
            )
            == 1
        )
        events = s.scalars(select(AgentEvent).where(AgentEvent.run_id == f.scope.run_id)).all()
        assert sum(event.body.get("type") == "domain_candidate" for event in events) == 1
    for _ in range(2):
        result = read(setup, f)
        assert result.status_code == 200, result.text
        item = result.json()["items"][0]
        assert item["event_id"] == first["event_id"] and item["state"] == "pending"
        assert item["command"] == first["command"] and item["receipt"] is None
    assert counts(setup) == before


def test_confirmation_receipt_resolves_candidate_even_after_run_completion(setup):
    f = fixture(setup)
    prepared = prepare(f)
    with Session(setup.admin) as s, s.begin():
        s.get(AgentRun, f.scope.run_id).state = "completed"
    assert read(setup, f).json()["items"][0]["state"] == "pending"
    receipt, original = confirmed(setup, prepared["command"])
    after = counts(setup)
    resolved = read(setup, f)
    assert resolved.status_code == 200, resolved.text
    item = resolved.json()["items"][0]
    assert item["state"] == "adopted" and item["command"] is None
    assert item["receipt"]["id"] == receipt["id"]
    repeated = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=setup.headers,
        json=original,
    )
    assert repeated.status_code == 200 and repeated.json()["id"] == receipt["id"]
    assert counts(setup) == after


def test_cancelled_candidate_cannot_be_exposed_as_executable(setup):
    f = fixture(setup)
    prepared = prepare(f)
    preview = setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=setup.headers,
        json=prepared["command"],
    )
    assert preview.status_code == 200, preview.text
    before = counts(setup)
    with Session(setup.admin) as s, s.begin():
        run = s.get(AgentRun, f.scope.run_id)
        run.state, run.cancel_epoch = "cancelled", run.cancel_epoch + 1
    item = read(setup, f).json()["items"][0]
    assert item["state"] == "cancelled" and item["command"] is None
    denied = setup.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=setup.headers,
        json=preview.json()["command"],
    )
    assert denied.status_code == 403 and counts(setup) == before


def test_candidate_read_requires_current_owner_and_category_authority(setup):
    f = fixture(setup)
    prepare(f)
    assert read(setup, f, actor=setup.peer).status_code == 403
    assert read(setup, f, actor=setup.other_human).status_code == 403
    with Session(setup.admin) as s, s.begin():
        s.scalar(select(Grant).where(Grant.principal_id == setup.human)).expires_at = (
            now() - timedelta(seconds=1)
        )
    denied = read(setup, f)
    assert denied.status_code == 403 and "SYNTHETIC-PLATFORM" not in denied.text


def test_candidate_pagination_is_stable_and_typed(setup):
    f = fixture(setup)
    prepare(f)
    args = deepcopy(f.arguments)
    args["new_platform"]["code"] = "SECOND"
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
    prepare(f, model_id=model_id, arguments=args)
    first = read(setup, f, query="?page_size=1").json()
    assert len(first["items"]) == 1 and first["next_cursor"]
    second = read(setup, f, query=f"?page_size=1&after={first['next_cursor']}").json()
    assert second["next_cursor"] is None
    assert first["items"][0]["event_id"] != second["items"][0]["event_id"]
    for query in ("?after=-1", "?page_size=201", "?after=wrong"):
        assert read(setup, f, query=query).status_code == 422


def test_candidate_and_prepared_content_rollback_together(setup, monkeypatch):
    from pdos_next.agent_kernel import domain_candidates

    f = fixture(setup)
    original = domain_candidates.record

    def interrupted(*args):
        original(*args)
        raise RuntimeError("synthetic interruption before candidate commit")

    monkeypatch.setattr(domain_candidates, "record", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        prepare(f)
    with Session(setup.admin) as s:
        assert not s.scalar(
            select(PreparedCandidate.id).where(PreparedCandidate.run_id == f.scope.run_id)
        )
        assert not s.scalar(
            select(AgentEvent.id).where(
                AgentEvent.run_id == f.scope.run_id,
                AgentEvent.body["type"].astext == "domain_candidate",
            )
        )
    monkeypatch.setattr(domain_candidates, "record", original)
    assert prepare(f)["event_id"]


def test_named_decisions_do_not_enter_executable_candidate_stream():
    from pdos_next.agent_kernel.domain_candidates import record

    with pytest.raises(DomainError) as denied:
        record(None, None, SimpleNamespace(operation="proposal.g0.decide"), "untrusted")
    assert denied.value.code == "NAMED_DECISION_REQUIRED"


def test_same_candidate_delivery_supports_category_proposal_and_retains_ai_authorship(setup):
    from tests.preproject.test_g0 import payload as proposal_payload

    arguments = proposal_payload(setup)
    for item in arguments["groups"]["items"]:
        if item["kind"] == "spec":
            item["content"]["item_status"] = "ai_draft"
    f = agent_fixture(
        setup,
        arguments,
        operation="proposal.create",
        skill_key="proposal_drafting",
        product_bound=False,
    )
    bootstrap = Bootstrap(setup.engine)
    bootstrap.route = lambda *_: f.route
    prepared = bootstrap.prepare_candidate(
        f.scope,
        bootstrap.registry.get("proposal.create"),
        arguments,
        execution_key(f.scope.run_id, f.model.id, 0),
    )
    listed = read(setup, f)
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["command"]["product_id"] is None
    receipt, _ = confirmed(setup, prepared["command"])
    result = read(setup, f)
    assert result.status_code == 200, result.text
    item = result.json()["items"][0]
    assert item["state"] == "adopted" and item["receipt"]["id"] == receipt["id"]
    assert item["command_id"] == prepared["command"]["command_id"]
    assert item["idempotency_key"] == prepared["command"]["idempotency_key"]
    assert receipt["agent_run_id"] == str(f.scope.run_id) and receipt["subject_type"] == "proposal"
    with Session(setup.admin) as s:
        from pdos_next.domain.preproject.models import ProposalRevision

        saved = s.get(Receipt, UUID(receipt["id"]))
        assert saved.confirmation_id is not None
        assert (
            s.scalar(
                select(ProposalRevision.run_id).where(
                    ProposalRevision.receipt_id == saved.id,
                )
            )
            == f.scope.run_id
        )
    question_args = {
        "proposal_id": receipt["subject_id"],
        "expected_revision": 1,
        "question": "合成待决项：核对噪声条件",
        "owner_id": str(setup.human),
        "due_date": "2026-11-01",
        "related_item_ids": [],
    }
    question = agent_fixture(
        setup,
        question_args,
        operation="proposal.question.create",
        skill_key="proposal_drafting",
        product_bound=False,
        proposal_id=UUID(receipt["subject_id"]),
    )
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: question.route
    prepared_question = owner.prepare_candidate(
        question.scope,
        owner.registry.get("proposal.question.create"),
        question_args,
        execution_key(question.scope.run_id, question.model.id, 0),
    )
    saved_question, _ = confirmed(setup, prepared_question["command"])
    assert read(setup, question).json()["items"][0]["receipt"]["id"] == saved_question["id"]
    assert saved_question["agent_run_id"] == str(question.scope.run_id)


def test_proposal_receipt_metadata_mismatch_rolls_back_and_history_blocks_downgrade(
    setup, monkeypatch
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import DBAPIError

    from migrations.versions.s0_0760_prepared_proposal_receipts import downgrade
    from pdos_next import service
    from tests.preproject.test_g0 import payload as proposal_payload

    arguments = proposal_payload(setup)
    for item in arguments["groups"]["items"]:
        if item["kind"] == "spec":
            item["content"]["item_status"] = "ai_draft"
    f = agent_fixture(
        setup,
        arguments,
        operation="proposal.create",
        skill_key="proposal_drafting",
        product_bound=False,
    )
    owner = Bootstrap(setup.engine)
    owner.route = lambda *_: f.route
    prepared = owner.prepare_candidate(
        f.scope,
        owner.registry.get("proposal.create"),
        arguments,
        execution_key(f.scope.run_id, f.model.id, 0),
    )
    path = f"/v1/categories/{setup.category}/commands"
    preview = setup.client.post(path + "/preview", headers=setup.headers, json=prepared["command"])
    assert preview.status_code == 200, preview.text
    before = counts(setup)
    original = service.append_receipt

    def mismatched(s, ctx, command, kind, subject, *args):
        subject.action_result = {**subject.action_result, "candidate_digest": "b" * 64}
        return original(s, ctx, command, kind, subject, *args)

    monkeypatch.setattr(service, "append_receipt", mismatched)
    with pytest.raises(DBAPIError, match="M3 common receipt binding"):
        setup.client.post(path, headers=setup.headers, json=preview.json()["command"])
    assert counts(setup) == before
    monkeypatch.setattr(service, "append_receipt", original)
    saved = setup.client.post(path, headers=setup.headers, json=preview.json()["command"])
    assert saved.status_code == 200, saved.text
    with setup.admin.connect() as connection:
        transaction = connection.begin()
        try:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(DBAPIError, match="prepared proposal receipt history requires"):
                    downgrade()
        finally:
            transaction.rollback()
