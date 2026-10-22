from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.management import AgreementInput, register_agreement
from pdos_next.agent_kernel.models import (
    AgentRun,
    AgentToolCall,
    ProviderDataAgreement,
    TenantAdministrator,
)
from pdos_next.agent_kernel.persistence import KernelStore, cancel_run, create_run
from pdos_next.agent_kernel.policy import egress
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now


def human_session(setup):
    return tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    )


def run(setup, **kwargs):
    with human_session(setup) as s:
        identity = create_run(
            s,
            setup.ctx,
            goal="Synthetic public research",
            writer_id=setup.agent,
            intent_key="kernel-run:" + str(uuid4()),
            **kwargs,
        ).id
    store = KernelStore(setup.engine)
    bound = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=identity,
    )
    return store, bound


def test_scope_is_category_root_and_agent_has_no_direct_dml(setup):
    store, bound = run(setup)
    assert bound.category_id == setup.category and bound.product_id is None
    with setup.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM agent_runs")).scalar_one() == 0
        assert not c.execute(
            text("SELECT has_table_privilege('pdos_agent','agent_runs','INSERT')")
        ).scalar_one()
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as s:
        assert s.get(AgentRun, bound.run_id) is None
    with pytest.raises(DomainError):
        store.current(replace(bound, category_id=uuid4()))
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.agent
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as e:
        store.current(bound)
    assert e.value.code == "FORBIDDEN_SCOPE"


def test_cancel_releases_budget_and_no_old_scope_can_submit(setup):
    store, bound = run(setup)
    call, _ = store.claim(bound, "model-1", "model", {"prompt": "synthetic"}, reservation=100)
    with human_session(setup) as s:
        result = cancel_run(s, setup.ctx, bound.run_id)
        assert result["held_tokens"] == 0
    with Session(setup.admin) as s:
        r = s.get(AgentRun, bound.run_id)
        c = s.get(AgentToolCall, call)
        assert r.held_tokens == 0 and r.used_tokens == 100 and c.state == "unknown"
    with pytest.raises(DomainError) as e:
        store.current(bound)
    assert e.value.code == "CANCELLED_RUN"


def test_unknown_call_releases_slot_and_has_explicit_reconciliation_exit(setup):
    store, bound = run(setup)
    call, _ = store.claim(bound, "external-1", "mcp.read", {"query": "synthetic"}, reservation=50)
    store.settle(bound, call, unknown=True, error="EXTERNAL_OUTCOME_UNKNOWN")
    with store.transaction(bound) as (_, r):
        assert r.held_tokens == 0 and r.used_tokens == 50
    with pytest.raises(DomainError) as e:
        store.claim(bound, "external-1", "mcp.read", {"query": "synthetic"})
    assert e.value.code == "EXTERNAL_OUTCOME_UNKNOWN"
    assert (
        store.reconcile(bound, call, receipt_lookup=lambda *_: None)["state"]
        == "needs_reconciliation"
    )
    result = store.reconcile(bound, call, receipt_lookup=lambda *_: None, final=True)
    assert result == {"state": "failed", "receipt_id": None, "may_retry_with_new_request": True}
    store.claim(bound, "external-2", "mcp.read", {"query": "synthetic"})


def test_same_intent_restores_completed_call_and_different_payload_conflicts(setup):
    store, bound = run(setup)
    call, _ = store.claim(bound, "read-1", "category.read", {})
    store.settle(bound, call, result={"actual": "read"})
    assert store.claim(bound, "read-1", "category.read", {})[1] == {"actual": "read"}
    with pytest.raises(DomainError) as e:
        store.claim(bound, "read-1", "category.read", {"different": True})
    assert e.value.code == "DUPLICATE_INTENT_CONFLICT"


def test_forged_taint_cannot_weaken_server_stored_private_binding(setup):
    store, bound = run(
        setup,
        private_context=True,
        data_categories=("customer_original",),
        customer_identities=("Customer secret",),
    )
    with pytest.raises(DomainError):
        store.current(replace(bound, private_context=False))
    with store.transaction(bound) as (s, _):
        # P26: no registered agreement no longer blocks; server-bound categories are receipted.
        decision = egress(s, bound, "synthetic-provider")
        assert decision.agreement_id is None
        assert decision.data_categories == ("customer_original",)


def test_unsigned_provider_egress_is_allowed_and_receipted(setup):
    # P26: the agreement registry is an optional restriction, never a precondition.
    store, bound = run(setup, customer_identities=("Private attachment.pdf", "Customer secret"))
    with store.transaction(bound) as (s, _):
        decision = egress(s, bound, "search-provider")
        assert decision.agreement_id is None and decision.provider == "search-provider"
        assert decision.checked_at and decision.agreement_revision is None


def agreement(setup):
    return AgreementInput(
        provider="synthetic-provider",
        expected_revision=0,
        signed_on=now() - timedelta(days=1),
        data_categories=["customer_original"],
        retention_terms="Synthetic contract fixture",
        training_terms="Synthetic no-training fixture",
        expires_at=now() + timedelta(days=1),
        decision="批准",
        idempotency_key="agreement:" + str(uuid4()),
    )


def test_only_actual_admin_can_register_signed_agreement_with_receipt_atom(setup):
    data = agreement(setup)
    with human_session(setup) as s:
        with pytest.raises(DomainError) as e:
            register_agreement(s, setup.ctx, data)
        assert e.value.code == "NAMED_DECISION_REQUIRED"
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    with human_session(setup) as s:
        first = register_agreement(s, setup.ctx, data)
    with human_session(setup) as s:
        assert register_agreement(s, setup.ctx, data) == first
    store, bound = run(setup, private_context=True, data_categories=("customer_original",))
    with store.transaction(bound) as (s, _):
        decision = egress(s, bound, "synthetic-provider")
        assert decision.agreement_id == first["subject_id"] and decision.agreement_revision == 1
        # P26: a provider without any registered agreement is not blocked.
        assert egress(s, bound, "different-provider").agreement_id is None


def test_registered_agreement_restricts_uncovered_categories(setup):
    # P26: a current registered agreement is enforced as a category restriction.
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    with human_session(setup) as s:
        register_agreement(s, setup.ctx, agreement(setup))
    store, bound = run(
        setup, private_context=True, data_categories=("customer_original", "internal")
    )
    with store.transaction(bound) as (s, _):
        # The registered agreement covers customer_original only; internal is rejected.
        with pytest.raises(DomainError) as e:
            egress(s, bound, "synthetic-provider")
        assert e.value.code == "FORBIDDEN_SCOPE"
        assert e.value.detail["reason_key"] == "provider_agreement_category"
        covering = egress(
            s,
            replace(bound, data_categories=frozenset({"customer_original"})),
            "synthetic-provider",
        )
        assert covering.agreement_id is not None and covering.agreement_revision == 1


def test_management_direct_write_without_receipt_atom_rolls_back(setup):
    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    with pytest.raises(DBAPIError, match="receipt atom"):
        with human_session(setup) as s:
            s.add(
                ProviderDataAgreement(
                    tenant_id=setup.tenant,
                    provider="synthetic-bypass",
                    revision=1,
                    signed_on=now(),
                    data_categories=["customer_original"],
                    retention_terms="synthetic",
                    training_terms="synthetic",
                    expires_at=now() + timedelta(days=1),
                    registered_by=setup.human,
                )
            )
    with Session(setup.admin) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(ProviderDataAgreement)
                .where(ProviderDataAgreement.tenant_id == setup.tenant)
            )
            == 0
        )


def test_run_and_process_events_hide_after_source_audience_revocation(setup):
    from pdos_next.models import Artifact, ObjectAudience
    from pdos_next.service import digest

    source_id = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Artifact(
                id=source_id,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                owner_id=setup.peer,
                title="Synthetic private shared input",
                source_label="fixture",
                content="secret",
                content_hash=digest("secret"),
                visibility="audience",
            )
        )
        s.flush()
        s.add(
            ObjectAudience(
                tenant_id=setup.tenant,
                category_id=setup.category,
                object_type="artifact_versions",
                subject_id=source_id,
                owner_id=setup.peer,
                principal_id=setup.human,
            )
        )
    store, bound = run(
        setup, product_id=setup.product,
        read_sources=[{"product_id": str(setup.product), "artifact_id": str(source_id),
                              "expected_revision": 1}]
    )
    store.emit(bound, {"type": "synthetic_safe_metadata"})
    with Session(setup.admin) as s, s.begin():
        s.delete(s.scalar(select(ObjectAudience).where(ObjectAudience.subject_id == source_id)))
    with human_session(setup) as s:
        assert s.get(AgentRun, bound.run_id) is None
    with pytest.raises(DomainError):
        store.current(bound)
