"""Root-run native agreement atom/API/RLS checks. No provider calls."""

from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.management import register_agreement
from pdos_next.agent_kernel.models import ProviderDataAgreement
from pdos_next.agent_kernel.policy import egress
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Receipt
from tests.agent_kernel.test_management_api import path, promote, send
from tests.agent_kernel.test_transactions import agreement, human_session


@pytest.mark.parametrize("choice", [None, False, True])
def test_named_cache_choice_is_tenant_wide_and_replays_without_changing_old_requests(setup, choice):
    promote(setup)
    original = agreement(setup).model_copy(update={"prompt_cache_allowed": choice})
    saved = send(setup, original)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    if choice is None:
        assert "prompt_cache_allowed" not in original.model_dump(mode="json")
        assert "prompt_cache_allowed" not in receipt["result"]
    else:
        assert receipt["result"]["prompt_cache_allowed"] is choice
    assert send(setup, original, "/recover").json() == {"receipt": receipt}
    assert send(setup, original).json() == receipt
    changed = original.model_copy(update={"prompt_cache_allowed": choice is not True})
    assert send(setup, changed, "/recover").json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    with Session(setup.admin) as session:
        row = session.get(ProviderDataAgreement, UUID(receipt["subject_id"]))
        assert row.prompt_cache_allowed is choice
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    reading = setup.client.get(path(setup), headers=peer_headers)
    assert reading.status_code == 200, reading.text
    assert reading.json()["items"][0]["prompt_cache_allowed"] is choice
    # Personal/cross-category model calls use the same tenant policy, even though
    # the original administrator's private receipt is deliberately not visible.
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                        requester_id=setup.peer, category_id=None) as session:
        assert session.get(Receipt, UUID(receipt["id"])) is None
        decision = egress(session, NS(tenant_id=setup.tenant,
                                     data_categories=tuple(original.data_categories)),
                          original.provider)
        assert decision.prompt_cache_allowed is (choice is True)
        assert decision.agreement_id == receipt["subject_id"]
    unauthorized = replace(setup.ctx, actor_id=setup.peer, requester_id=setup.peer)
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer,
                        category_id=setup.category) as session, pytest.raises(DomainError) as error:
        register_agreement(session, unauthorized, changed)
    assert getattr(error.value, "code", None) == "NAMED_DECISION_REQUIRED"


def test_cache_column_and_named_receipt_must_match_in_the_native_atom(setup, monkeypatch):
    promote(setup)
    original = agreement(setup).model_copy(update={"prompt_cache_allowed": True})
    with pytest.raises(DBAPIError, match="Named agreement receipt atom required"):
        with human_session(setup) as session:
            add_all = session.add_all

            def damaged(rows):
                for row in rows:
                    if isinstance(row, ProviderDataAgreement):
                        row.prompt_cache_allowed = False
                return add_all(rows)

            monkeypatch.setattr(session, "add_all", damaged)
            register_agreement(session, setup.ctx, original)
