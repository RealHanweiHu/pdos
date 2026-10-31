"""Named cache permission, old-request recovery and P26 without database/provider IO."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel import management_api, policy
from pdos_next.agent_kernel.management import AgreementInput
from pdos_next.agent_kernel.models import ProviderDataAgreement
from pdos_next.errors import DomainError
from pdos_next.service import digest


def legacy_request():
    return {
        "provider": "synthetic-provider", "expected_revision": 0,
        "signed_on": "2026-10-01T00:00:00Z", "expires_at": "2027-10-01T00:00:00Z",
        "data_categories": ["internal"], "retention_terms": "禁止缓存，具体以具名选择为准",
        "training_terms": "合成测试不用于训练", "active": True,
        "decision": "批准", "idempotency_key": "original-approved-request",
    }


@pytest.mark.parametrize("model", [AgreementInput, management_api.AgreementRequest])
def test_absent_or_null_cache_choice_keeps_old_request_digest_and_exact_json(model):
    original = legacy_request()
    for payload in (original, {**original, "prompt_cache_allowed": None}):
        value = model.model_validate(payload)
        assert value.prompt_cache_allowed is None
        assert value.model_dump(mode="json") == original
        assert json.loads(value.model_dump_json()) == original
        assert digest(value.model_dump(mode="json")) == digest(original)


@pytest.mark.parametrize("choice", [True, False])
def test_explicit_boolean_is_part_of_the_named_request_and_recovery_digest(choice):
    original = legacy_request()
    value = AgreementInput.model_validate({**original, "prompt_cache_allowed": choice})
    assert value.model_dump(mode="json")["prompt_cache_allowed"] is choice
    assert digest(value.model_dump(mode="json")) != digest(original)
    opposite = value.model_copy(update={"prompt_cache_allowed": not choice})
    assert digest(value.model_dump(mode="json")) != digest(opposite.model_dump(mode="json"))


@pytest.mark.parametrize("choice", [0, 1, "true", "false", "禁止缓存", [], {}])
def test_cache_choice_never_coerces_numbers_or_agreement_prose(choice):
    with pytest.raises(ValidationError):
        management_api.AgreementRequest.model_validate({
            **legacy_request(), "prompt_cache_allowed": choice,
        })


def case(choice=True):
    instant = datetime(2026, 10, 29, tzinfo=UTC)
    tenant, human, identity, receipt_id = (uuid4() for _ in range(4))
    agreement = NS(
        id=identity, tenant_id=tenant, provider="synthetic-provider", revision=3,
        registered_by=human, receipt_id=receipt_id, active=True,
        signed_on=instant - timedelta(days=1), expires_at=instant + timedelta(days=1),
        data_categories=["internal"], retention_terms="禁止所有缓存的自由文本",
    )
    agreement.prompt_cache_allowed = choice
    return NS(agreement=agreement, instant=instant,
              scope=NS(tenant_id=tenant, data_categories=("internal",)))


class PolicySession:
    def __init__(self, f):
        self.f, self.reads = f, []

    def scalar(self, _query):
        self.reads.append(ProviderDataAgreement)
        return self.f.agreement

@pytest.mark.parametrize("choice,allowed", [(True, True), (False, False), (None, False)])
def test_active_agreement_has_one_policy_read_and_only_named_boolean_allows_cache(
    monkeypatch, choice, allowed,
):
    f = case(choice)
    monkeypatch.setattr(policy, "now", lambda: f.instant)
    session = PolicySession(f)
    decision = policy.egress(session, f.scope, f.agreement.provider)
    assert decision.prompt_cache_allowed is allowed
    assert decision.agreement_id == str(f.agreement.id)
    assert session.reads == [ProviderDataAgreement]
    f.agreement.retention_terms = "自由文本变为允许所有缓存"
    assert policy.egress(session, f.scope, f.agreement.provider).prompt_cache_allowed is allowed


@pytest.mark.parametrize("change", ["absent", "inactive", "expired", "future"])
def test_no_current_agreement_keeps_p26_and_default_cache_permission(monkeypatch, change):
    f = case(False)
    monkeypatch.setattr(policy, "now", lambda: f.instant)
    if change == "absent":
        f.agreement = None
    elif change == "inactive":
        f.agreement.active = False
    elif change == "expired":
        f.agreement.expires_at = f.instant
    else:
        f.agreement.signed_on = f.instant + timedelta(seconds=1)
    session = PolicySession(f)
    decision = policy.egress(session, f.scope, "synthetic-provider")
    assert decision.prompt_cache_allowed is True and decision.agreement_id is None
    assert session.reads == [ProviderDataAgreement]


def test_cache_allowance_never_expands_registered_data_categories(monkeypatch):
    f = case()
    monkeypatch.setattr(policy, "now", lambda: f.instant)
    session = PolicySession(f)
    with pytest.raises(DomainError) as error:
        policy.egress(session, f.scope, f.agreement.provider,
                      data_categories=("customer_original",))
    assert error.value.detail["reason_key"] == "provider_agreement_category"
    assert session.reads == [ProviderDataAgreement]


def test_list_exposes_tenant_policy_without_reading_private_administrator_receipts(monkeypatch):
    f = case()
    rows = [NS(**{**vars(f.agreement), "training_terms": "不训练", "created_at": f.instant})]
    reads = []

    class Session:
        def scalar(self, _query):
            return True

        def execute(self, _query):
            reads.append(True)
            values = rows if len(reads) == 1 else [(f.agreement.registered_by, "管理员")]
            return NS(all=lambda: values)

    monkeypatch.setattr(management_api, "human", lambda *_args: None)
    monkeypatch.setattr(management_api, "now", lambda: f.instant)
    ctx = NS(tenant_id=f.scope.tenant_id, actor_id=f.agreement.registered_by, category_id=uuid4())
    permitted = management_api.reading(Session(), ctx, management_api.AgreementQuery())
    assert permitted["items"][0]["prompt_cache_allowed"] is True
    assert len(reads) == 2  # One page and one batched principal name query; no receipt query.


def test_nullable_cache_metadata_and_downgrade_keep_old_unknown_and_named_history_separate():
    from migrations import schema_s0_0853 as ddl
    from pdos_next.lifecycle_catalog import COVERED_COLUMNS

    column = ProviderDataAgreement.__table__.c.prompt_cache_allowed
    assert column.nullable and column.default is None and column.server_default is None
    assert "prompt_cache_allowed" in COVERED_COLUMNS["provider_data_agreements"]
    assert "to_jsonb(NEW.prompt_cache_allowed)" in ddl.CACHE_ATOM
    assert "NOT (r.result ? 'prompt_cache_allowed')" in ddl.CACHE_ATOM
    down = "\n".join(ddl.DOWN_SQL)
    assert down.index("ACCESS EXCLUSIVE") < down.index("IS NOT NULL") < down.index("DROP COLUMN")
