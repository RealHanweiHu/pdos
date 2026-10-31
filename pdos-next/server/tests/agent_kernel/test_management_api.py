from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pdos_next.agent_kernel import management
from pdos_next.agent_kernel.management import agreement_receipt, register_agreement
from pdos_next.agent_kernel.models import ProviderDataAgreement, TenantAdministrator
from pdos_next.database import category_transaction, tenant_session
from pdos_next.models import Audit, Outbox, Receipt
from tests.agent_kernel.test_transactions import agreement, human_session, run


def promote(setup):
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))


def path(setup):
    return f"/v1/categories/{setup.category}/provider-agreements"


def send(setup, data, suffix="", headers=None):
    return setup.client.post(
        path(setup) + suffix, json=data.model_dump(mode="json"), headers=headers or setup.headers
    )


def test_admin_registers_and_member_reads_current_head_and_receipt_atom(setup):
    data = agreement(setup)
    read = setup.client.get(path(setup), headers=setup.headers)
    assert read.status_code == 200 and read.json()["can_edit"] is False
    assert send(setup, data).json()["code"] == "NAMED_DECISION_REQUIRED"
    promote(setup)
    saved = send(setup, data)
    assert saved.status_code == 200, saved.text
    receipt = saved.json()
    assert receipt["result"]["tier"] == "T2"
    assert receipt["writer_id"] == str(setup.human) and receipt["agent_run_id"] is None
    assert send(setup, data).json() == receipt
    with Session(setup.admin) as session:
        for model in (Receipt, Audit, Outbox):
            column = model.id if model is Receipt else model.receipt_id
            assert (
                session.scalar(
                    select(func.count()).select_from(model).where(column == UUID(receipt["id"]))
                )
                == 1
            )
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    read = setup.client.get(path(setup), headers=peer_headers).json()
    assert read["can_edit"] is False and read["items"][0]["registered_by_name"] == "Synthetic owner"
    second = data.model_copy(
        update={"expected_revision": 1, "active": False, "idempotency_key": str(uuid4())}
    )
    assert send(setup, second).status_code == 200
    current = setup.client.get(path(setup), headers=setup.headers).json()
    assert len(current["items"]) == 1 and current["items"][0]["status"] == "inactive"
    assert current["items"][0]["revision"] == 2 and current["can_edit"] is True
    store, bound = run(setup, private_context=True, data_categories=("customer_original",))
    from pdos_next.agent_kernel.policy import egress

    with store.transaction(bound) as (session, _):
        # P26: a disabled latest agreement is optional governance, not an
        # outbound prerequisite. It also cannot retain an old cache restriction.
        decision = egress(session, bound, data.provider)
        assert decision.agreement_id is decision.agreement_revision is None
        assert decision.data_categories == ("customer_original",)
        assert decision.prompt_cache_allowed is True


def test_recovery_is_read_only_exact_and_survives_admin_revocation(setup):
    promote(setup)
    data = agreement(setup)
    assert send(setup, data, "/recover").json() == {"receipt": None}
    saved = send(setup, data).json()
    with Session(setup.admin) as session, session.begin():
        session.scalar(
            select(TenantAdministrator).where(TenantAdministrator.tenant_id == setup.tenant)
        ).active = False
    assert send(setup, data, "/recover").json() == {"receipt": saved}
    assert send(setup, data).json()["code"] == "NAMED_DECISION_REQUIRED"
    changed = data.model_copy(update={"training_terms": "A different contract"})
    assert send(setup, changed, "/recover").json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert send(setup, data, "/recover", peer).json() == {"receipt": None}
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
        read_snapshot=True,
    ) as session:
        assert session.scalar(text("SHOW transaction_read_only")) == "on"
        assert agreement_receipt(session, setup.ctx, data) == saved


def test_expired_original_replays_without_new_revision_but_new_registration_rejects(
    setup, monkeypatch
):
    promote(setup)
    data = agreement(setup)
    with human_session(setup) as session:
        saved = register_agreement(session, setup.ctx, data)
    monkeypatch.setattr(management, "now", lambda: data.expires_at + timedelta(days=1))
    assert send(setup, data).json() == saved
    fresh = data.model_copy(update={"expected_revision": 1, "idempotency_key": str(uuid4())})
    assert send(setup, fresh).json()["code"] == "VALIDATION_FAILED"


def test_conflicting_heads_and_invalid_scope_never_add_registration(setup):
    promote(setup)
    data = agreement(setup)
    assert send(setup, data).status_code == 200
    stale = data.model_copy(update={"idempotency_key": str(uuid4())})
    assert send(setup, stale).json()["code"] == "VERSION_CONFLICT"
    unknown = data.model_copy(update={"data_categories": ["unregistered-class"]})
    assert send(setup, unknown).status_code == 422
    forged = {**data.model_dump(mode="json"), "tenant_id": str(setup.other_tenant)}
    assert setup.client.post(path(setup), json=forged, headers=setup.headers).status_code == 422
    other = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert setup.client.get(path(setup), headers=other).status_code == 403
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.agent,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        from pdos_next.agent_kernel.management_api import human
        from pdos_next.errors import DomainError

        with pytest.raises(DomainError):
            human(session, replace(setup.ctx, actor_id=setup.agent))


@pytest.mark.parametrize("same_intent", [False, True])
def test_parallel_first_registration_serializes_head_and_exact_replay(setup, same_intent):
    promote(setup)
    first = agreement(setup)
    second = first if same_intent else first.model_copy(update={"idempotency_key": str(uuid4())})
    barrier = Barrier(2)

    def write(data):
        from pdos_next.errors import DomainError

        barrier.wait(timeout=10)
        try:
            return category_transaction(
                setup.engine,
                setup.ctx,
                lambda session: register_agreement(session, setup.ctx, data),
            )
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(write, (first, second)))
    if same_intent:
        assert values[0] == values[1] and isinstance(values[0], dict)
    else:
        assert sum(isinstance(value, dict) for value in values) == 1
        assert "VERSION_CONFLICT" in values
    with Session(setup.admin) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ProviderDataAgreement)
                .where(ProviderDataAgreement.tenant_id == setup.tenant)
            )
            == 1
        )


def test_latest_provider_paging_and_exact_filter(setup):
    promote(setup)
    for provider in ["z-provider", "a-provider", "m-provider"]:
        assert (
            send(setup, agreement(setup).model_copy(update={"provider": provider})).status_code
            == 200
        )
    first = setup.client.get(path(setup) + "?page_size=2", headers=setup.headers).json()
    assert [item["provider"] for item in first["items"]] == ["a-provider", "m-provider"]
    assert first["next_cursor"] == "m-provider"
    last = setup.client.get(
        path(setup) + "?page_size=2&cursor=m-provider", headers=setup.headers
    ).json()
    assert [item["provider"] for item in last["items"]] == ["z-provider"]
    assert last["next_cursor"] is None
    exact = setup.client.get(path(setup) + "?provider=z-provider", headers=setup.headers).json()
    assert len(exact["items"]) == 1 and exact["items"][0]["provider"] == "z-provider"
