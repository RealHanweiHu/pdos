"""Backward-compatible command identity and shared T2 identity gates."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pdos_next.contracts import BuildReadinessPayload
from pdos_next.errors import DomainError
from pdos_next.service import Context, check_qualification, digest


def test_preparation_readiness_keeps_original_serialization_and_identity():
    legacy = {"build_id": str(uuid4()), "expected_build_revision": 1}
    parsed = BuildReadinessPayload.model_validate(legacy)
    assert parsed.model_dump(mode="json") == legacy
    assert digest(parsed.model_dump(mode="json")) == digest(legacy)
    with pytest.raises(ValidationError):
        BuildReadinessPayload.model_validate({**legacy, "reason": "cannot change old semantics"})


@pytest.mark.parametrize(
    "operation", ["build.engineering.authorize", "build.manufacturing.authorize"]
)
@pytest.mark.parametrize(
    "kind,delegated,run", [("agent", False, False), ("human", True, False), ("human", False, True)]
)
def test_t2_gate_precedes_run_qualification_and_replay(operation, kind, delegated, run):
    actor, tenant = uuid4(), uuid4()
    ctx = Context(
        tenant, actor, uuid4() if delegated else actor, **({"run_id": uuid4()} if run else {})
    )
    session = SimpleNamespace(get=lambda *_: SimpleNamespace(kind=kind))
    with pytest.raises(DomainError) as error:
        check_qualification(session, ctx, operation, object(), synthetic_mode=True)
    assert error.value.code == "NAMED_DECISION_REQUIRED"


def test_host_synthetic_ledger_cannot_qualify_a_different_claim_with_same_named_id(monkeypatch):
    from copy import deepcopy
    from datetime import UTC, datetime, timedelta

    from pdos_next import operational_bootstrap
    from pdos_next.domain.build_operational_facts.schemas import DecisionInput
    from pdos_next.schemas.resource_readiness.contracts import ResourceRef

    monkeypatch.setattr(operational_bootstrap, "verify_test_target", lambda _engine: None)
    tenant, product, actor, resource_id, decision_id = (uuid4() for _ in range(5))
    at = datetime.now(UTC)
    decision = DecisionInput(
        kind="acceptance",
        purpose="internal-only",
        operation_id="assembly",
        status="accepted",
        valid_from=at - timedelta(hours=1),
        valid_until=at + timedelta(hours=1),
        named_decision_id=decision_id,
        actor_id=actor,
        sources=[
            {
                "artifact_id": str(uuid4()),
                "expected_revision": 1,
                "line": 1,
                "quote": "synthetic only",
            }
        ],
    )
    resource = ResourceRef(id=resource_id, revision=1, kind="equipment")
    binding = {"build_id": str(uuid4()), "scope": {"purpose": "internal-only"}}
    profile = {
        "tenant_id": str(tenant),
        "product_id": str(product),
        "decisions": [
            {
                "binding": binding,
                "resource": resource.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
            }
        ],
    }
    issuer = operational_bootstrap.configure_local_profile(SimpleNamespace(), profile)
    context = Context(tenant, actor, actor)
    verifier = issuer.verify_named_decision
    assert verifier(None, context, binding, resource, decision, at)["current"] is True
    rebound = {**binding, "build_id": str(uuid4())}
    assert verifier(None, context, rebound, resource, decision, at) is None
    changed = decision.model_copy(update={"purpose": "external delivery"})
    assert verifier(None, context, binding, resource, changed, at) is None
    # Caller cannot mutate the captured host profile to add a second permission.
    profile["decisions"][0]["binding"] = deepcopy(rebound)
    assert verifier(None, context, rebound, resource, decision, at) is None
    assert verifier(None, context, binding, resource, decision, at + timedelta(hours=2)) is None
