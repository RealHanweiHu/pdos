"""T1 definition header update (D311, P100 第 3 项) on the isolated PG target.

Every write uses the real preview and command path; the read revision is never
changed and the new draft carries the copied items under its own receipt.
"""

from uuid import UUID

import pytest
from sqlalchemy import func, select

from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Audit, Outbox, Product, Receipt
from pdos_next.core.service import Context
from pdos_next.domain.categories.products import definition_update
from pdos_next.domain.categories.products.models import DefinitionRevision, DefinitionSpecRow
from pdos_next.errors import DomainError
from pdos_next.schemas.products.definition_update import DefinitionUpdatePayload
from tests.categories.products.test_definition_item_commands_pg import draft
from tests.categories.products.test_definition_transactions import command, post

OPERATION = "product.definition.update"


def header(definition_id, revision=1, **changes):
    return {
        "definition_id": str(definition_id),
        "expected_definition_revision": revision,
        "title": "Synthetic definition v2",
        "purpose": "Synthetic product verification with a clarified purpose",
        "use_cases": ["Synthetic evaluation", "Synthetic bench check"],
        "requirements": ["Pressure stated under declared conditions"],
        "constraints": [],
        "unknowns": ["Test condition not confirmed"],
        "exclusions": [],
        "change_reason": "Clarify purpose and add the bench use case",
        **changes,
    }


def preview(setup, cmd, headers=None):
    return setup.client.post(
        f"/v1/categories/{setup.category}/commands/preview",
        headers=headers or setup.headers,
        json=cmd,
    )


def rows(setup, model, **where):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        found = s.scalars(select(model).filter_by(**where)).all()
        s.expunge_all()
        return found


def test_update_creates_next_draft_copies_items_and_keeps_the_read_revision(setup):
    parent_id, _ = draft(setup)
    before = rows(setup, DefinitionRevision, id=parent_id)[0]
    cmd = command(setup, OPERATION, header(parent_id))
    shown = preview(setup, cmd)
    assert shown.status_code == 200, shown.text
    review = shown.json()["review"]
    assert review["new_revision"] == 2 and review["copied_items"] == 1
    assert {change["path"] for change in review["changes"]} == {
        "title",
        "purpose",
        "use_cases",
        "requirements",
    }
    assert shown.json()["confirmation_token"] and "write_tier" not in shown.json()
    prepared = shown.json()["command"]
    saved = post(setup, prepared)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert receipt["operation"] == OPERATION and receipt["subject_type"] == "definition_revision"
    child = rows(setup, DefinitionRevision, id=UUID(receipt["subject_id"]))[0]
    assert (child.revision, child.status, child.sealed) == (2, "draft", False)
    assert child.parent_definition_id == parent_id and child.title == "Synthetic definition v2"
    assert child.change_reason == "Clarify purpose and add the bench use case"
    parent = rows(setup, DefinitionRevision, id=parent_id)[0]
    assert (parent.title, parent.purpose, parent.use_cases) == (
        before.title,
        before.purpose,
        before.use_cases,
    )
    copied = rows(setup, DefinitionSpecRow, definition_id=child.id)
    assert len(copied) == 1 and copied[0].receipt_id == UUID(receipt["id"])
    assert copied[0].key == "pressure" and copied[0].item_version == 1
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Audit)
                .where(Audit.receipt_id == UUID(receipt["id"]))
            )
            == 1
        )
        event = s.scalar(select(Outbox.type).where(Outbox.receipt_id == UUID(receipt["id"])))
        assert event == "definition.updated"
    # Same request replays the same receipt; reading the old revision again is stale.
    again = post(setup, prepared)
    assert again.status_code == 200 and again.json()["id"] == receipt["id"]
    stale = preview(setup, command(setup, OPERATION, header(parent_id, title="Branch from v1")))
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    follow = preview(
        setup,
        command(setup, OPERATION, header(child.id, revision=2, title="Synthetic definition v3")),
    )
    assert follow.status_code == 200, follow.text


def test_update_needs_one_confirmation_a_change_and_the_exact_revision(setup):
    parent_id, _ = draft(setup)
    unconfirmed = post(setup, command(setup, OPERATION, header(parent_id)))
    assert unconfirmed.status_code == 409 and unconfirmed.json()["code"] == "CONFIRMATION_REQUIRED"
    same = rows(setup, DefinitionRevision, id=parent_id)[0]
    unchanged = preview(
        setup,
        command(
            setup,
            OPERATION,
            header(
                parent_id,
                title=same.title,
                purpose=same.purpose,
                use_cases=same.use_cases,
                requirements=same.requirements,
                unknowns=same.unknowns,
            ),
        ),
    )
    assert unchanged.status_code == 409 and unchanged.json()["code"] == "VALIDATION_FAILED"
    wrong = preview(setup, command(setup, OPERATION, header(parent_id, revision=2)))
    assert wrong.status_code == 409 and wrong.json()["code"] == "VERSION_CONFLICT"
    shown = preview(setup, command(setup, OPERATION, header(parent_id)))
    tampered = shown.json()["command"]
    tampered["payload"]["title"] = "Changed after preview"
    changed = post(setup, tampered)
    assert changed.status_code == 409 and changed.json()["code"] == "CONFIRMATION_REQUIRED"
    assert len(rows(setup, DefinitionRevision, product_id=setup.product)) == 1
    other = preview(
        setup,
        command(setup, OPERATION, header(parent_id)),
        {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"},
    )
    assert other.status_code in {401, 403}
    invalid = preview(
        setup, command(setup, OPERATION, header(parent_id, requirements=["A"], exclusions=["A"]))
    )
    assert invalid.status_code == 422


def test_ai_identity_cannot_update_the_definition(setup):
    parent_id, _ = draft(setup)
    cmd = Command.model_validate(command(setup, OPERATION, header(parent_id)))
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
        definition_update.validate(
            s,
            ctx,
            cmd,
            s.get(Product, setup.product),
            DefinitionUpdatePayload.model_validate(cmd.payload),
        )
    assert failed.value.code == "NAMED_DECISION_REQUIRED"
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(Receipt).where(Receipt.operation == OPERATION)
            )
            == 0
        )
