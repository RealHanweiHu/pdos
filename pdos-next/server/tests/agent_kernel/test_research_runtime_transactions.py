"""The default host uses current persisted egress facts before its search transport."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import TenantAdministrator
from pdos_next.errors import DomainError
from pdos_next.models import now
from tests.agent_kernel.test_research_runtime import configuration
from tests.agent_kernel.test_transactions import human_session, run
from tests.model_configuration.test_host_runtime import write_config


def test_default_search_rechecks_agreement_and_does_not_trust_callback_categories(
    setup, tmp_path, monkeypatch
):
    _, scope = run(setup, data_categories=("customer",), customer_identities=("SyntheticClient",))
    path = write_config(tmp_path / "host.json", configuration(tmp_path))
    monkeypatch.setenv("PDOS_TENANT_RUNTIME_CONFIG", str(path))
    service = Bootstrap(setup.engine).ports.research_service
    searches = []

    async def search(query):
        searches.append(query)
        return ()

    monkeypatch.setattr(service.search_adapter, "search", search)
    assert asyncio.run(service.search(scope, "public pump catalogue")) == ()
    assert searches == ["public pump catalogue"]
    with pytest.raises(DomainError) as error:
        asyncio.run(service.search(scope, "SyntheticClient pump"))
    assert error.value.code == "FORBIDDEN_SCOPE" and searches == ["public pump catalogue"]
    with pytest.raises(DomainError):
        service.egress(scope, "synthetic-search", ("public",), "SyntheticClient pump")
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    agreement = AgreementInput(
        provider="synthetic-search",
        expected_revision=0,
        data_categories=["customer"],
        decision="批准",
        idempotency_key=str(uuid4()),
        retention_terms="synthetic-only",
        training_terms="synthetic-only",
        signed_on=now() - timedelta(minutes=1),
        expires_at=now() + timedelta(hours=1),
    )
    with human_session(setup) as session:
        register_agreement(session, setup.ctx, agreement)
    assert asyncio.run(service.search(scope, "SyntheticClient pump")) == ()
    assert searches == ["public pump catalogue", "SyntheticClient pump"]
    with human_session(setup) as session:
        register_agreement(
            session,
            setup.ctx,
            agreement.model_copy(
                update={
                    "expected_revision": 1,
                    "active": False,
                    "idempotency_key": str(uuid4()),
                }
            ),
        )
    with pytest.raises(DomainError) as error:
        asyncio.run(service.search(scope, "SyntheticClient pump"))
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert searches == ["public pump catalogue", "SyntheticClient pump"]
