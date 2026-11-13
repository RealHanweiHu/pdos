"""T2 named source withdrawal (D310, P120 第 1–2 项) on the isolated PG target."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from pdos_next.agent.enterprise_search.events import EVENTS
from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Artifact, Outbox, Product
from pdos_next.core.service import Context
from pdos_next.errors import DomainError
from pdos_next.originals import source_withdraw
from pdos_next.originals.source_withdraw_schemas import SourceWithdrawPayload
from tests.categories.products.test_definition_transactions import definitions, payload
from tests.d47_support import command, confirmed, headers_for, post, preview

OPERATION = "evidence.source.withdraw"
CONTENT = "Synthetic only\nPressure: 150 PSI\nTest conditions unknown"


def register(setup, visibility, headers=None):
    result = post(
        setup,
        command(
            setup,
            "evidence.artifact.register",
            {
                "title": "Synthetic shared spec",
                "source_label": "Synthetic",
                "content": CONTENT,
                "visibility": visibility,
            },
        ),
        headers,
    )
    assert result.status_code == 200, result.text
    return result.json()["subject_id"]


def withdraw(setup, artifact, revision=1, kind="artifact"):
    return command(
        setup,
        OPERATION,
        {
            "source_id": artifact,
            "kind": kind,
            "expected_revision": revision,
            "reason": "来源被供方撤回，需重核",
        },
    )


def artifact_row(setup, artifact):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        row = s.get(Artifact, UUID(artifact))
        s.expunge_all()
        return row


def test_category_owner_withdraws_a_shared_source_and_dependents_need_recheck(setup):
    artifact = register(setup, "category", headers_for(setup, setup.peer))
    cited = post(
        setup,
        command(
            setup,
            "product.definition.draft",
            payload(artifact),
            reads=[{"artifact_id": artifact, "expected_revision": 1}],
        ),
    )
    assert cited.status_code == 200, cited.text
    receipt, shown = confirmed(setup, withdraw(setup, artifact))
    review = shown["review"]
    assert (
        shown["write_tier"] == "T2"
        and review["authority"] == "category_owner"
        and review["shared"] is True
    )
    assert {row["table"] for row in review["dependents"]} >= {"definition_sources"}
    assert receipt["subject_type"] == "artifact" and receipt["operation"] == OPERATION
    row = artifact_row(setup, artifact)
    assert (row.status, row.revision) == ("withdrawn", 2) and row.content == CONTENT
    item = definitions(setup).json()["items"][0]
    assert item["source_status"] == "needs_recheck" and item["sources"][0]["status"] in {
        "withdrawn",
        "stale",
    }
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
            == "source.withdrawn"
        )
    again = preview(setup, withdraw(setup, artifact, 2))
    assert again.status_code == 409


def test_unused_private_source_keeps_the_one_confirmation_path(setup):
    artifact = register(setup, "private")
    refused = preview(setup, withdraw(setup, artifact))
    assert refused.status_code == 409 and refused.json()["code"] == "VALIDATION_FAILED"
    assert "一次确认" in refused.json()["message"]


def test_only_the_source_or_category_owner_may_decide(setup):
    artifact = register(setup, "category")
    peer = preview(setup, withdraw(setup, artifact), headers_for(setup, setup.peer))
    assert peer.status_code == 403 and peer.json()["code"] == "FORBIDDEN_SCOPE"
    unconfirmed = post(setup, withdraw(setup, artifact))
    assert unconfirmed.status_code in {403, 409}
    stale = preview(setup, withdraw(setup, artifact, 2))
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    missing = preview(setup, withdraw(setup, str(uuid4())))
    assert missing.status_code == 403
    receipt, shown = confirmed(setup, withdraw(setup, artifact))
    replay = post(setup, shown["command"])
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    other = preview(
        setup,
        withdraw(setup, artifact),
        {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert other.status_code in {401, 403}


def test_ai_cannot_withdraw_and_search_purges_on_the_event(setup):
    artifact = register(setup, "category")
    cmd = Command.model_validate(withdraw(setup, artifact))
    ctx = Context(setup.tenant, setup.agent, setup.human, category_id=setup.category)
    with (
        pytest.raises(DomainError) as failed,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as s,
    ):
        source_withdraw.validate(
            s,
            ctx,
            cmd,
            s.get(Product, setup.product),
            SourceWithdrawPayload.model_validate(cmd.payload),
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    assert "source.withdrawn" in EVENTS and artifact_row(setup, artifact).status == "active"


def test_one_confirmation_refuses_a_signed_or_foreign_original(monkeypatch):
    ctx = SimpleNamespace(requester_id=uuid4())
    mine = SimpleNamespace(id=uuid4(), owner_id=ctx.requester_id)
    monkeypatch.setattr(source_withdraw, "signed", lambda *args: True)
    with pytest.raises(DomainError) as failed:
        source_withdraw.check_t1(None, ctx, None, mine)
    assert failed.value.code == "UNDO_BLOCKED_BY_DEPENDENCY" and "具名撤回" in failed.value.message
    with pytest.raises(DomainError) as foreign:
        source_withdraw.check_t1(None, ctx, None, SimpleNamespace(id=uuid4(), owner_id=uuid4()))
    assert foreign.value.code == "FORBIDDEN_SCOPE"
    monkeypatch.setattr(source_withdraw, "signed", lambda *args: False)
    assert source_withdraw.check_t1(None, ctx, None, mine) is None
