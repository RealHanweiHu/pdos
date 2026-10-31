"""Actual upload/scan proof and provider policy, with synthetic model/scanner ports only."""
# ruff: noqa: F811 -- explicitly imported marked PG fixture

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import AgentEvent, TenantAdministrator
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import now
from tests.enterprise_search.test_assistant_pg import SyntheticClient, execute, fixture
from tests.enterprise_search.test_retrieval_pg import index
from tests.test_original_security import parsed, uploaded
from tests.test_original_security import security_work as security_work


@pytest.mark.parametrize("restricted", [False, True])
def test_server_customer_original_classification_reaches_real_egress_check(
    security_work, restricted
):
    work, setup = security_work, security_work.setup
    original = uploaded(work, content="漏气处理：更换密封圈。RAW_ONLY_CHILD_MARKER\n".encode())
    index(setup, parsed(work, original))
    scanner_calls = work.scanner.calls
    if restricted:
        with Session(setup.admin) as session, session.begin():
            session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session:
            register_agreement(
                session,
                setup.ctx,
                AgreementInput(
                    provider="synthetic-assistant-no-egress",
                    expected_revision=0,
                    data_categories=["internal"],
                    signed_on=now() - timedelta(minutes=1),
                    expires_at=now() + timedelta(hours=1),
                    retention_terms="synthetic-only",
                    training_terms="synthetic-only",
                    decision="批准",
                    idempotency_key=str(uuid4()),
                ),
            )
    client = SyntheticClient()
    owner, scope, host, adapter = fixture(setup, client)
    if restricted:
        with pytest.raises(DomainError) as blocked:
            execute(owner, scope, host)
        assert blocked.value.detail["reason_key"] == "provider_agreement_category"
        assert client.calls == 1 and client.child_calls == 0
    else:
        output = execute(owner, scope, host)
        assert output["status"] == "completed", output
        assert output["result"]["assistant"]["sources"][0]["locator"]["native"]
        with owner.store.transaction(scope) as (session, _run):
            events = session.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.run_id == scope.run_id,
                    AgentEvent.body["type"].astext == "egress_checked",
                )
                .order_by(AgentEvent.sequence)
            ).all()
            assert events[0].body["data_categories"] == ["internal"]
            assert len(events) == 5
            assert all("customer_original" in row.body["data_categories"] for row in events[1:])
        assert adapter.guard(scope) == frozenset({"internal", "customer_original"})
    assert work.scanner.calls == scanner_calls  # No scanning or provider retry on retrieval.
