"""Actual public boundaries: old SourceWork cannot execute or create effects."""

from dataclasses import replace
from uuid import uuid4

import pytest

from pdos_next.contracts import Command
from pdos_next.errors import DomainError
from pdos_next.service import execute
from tests.agent_kernel.test_domain_adapter_transactions import counts, fixture


def test_retired_source_work_start_and_resume_have_zero_new_effects(setup):
    f = fixture(setup)
    before = counts(setup)
    path = f"/v1/categories/{setup.category}"
    response = setup.client.post(path + "/commands", headers=setup.headers, json={
        "command_id": str(uuid4()), "idempotency_key": str(uuid4()),
        "category_id": str(setup.category), "product_id": str(setup.product),
        "operation": "ai.work.start", "expected_revision": 1,
        "source_read_set": [{"artifact_id": f.arguments["artifact_id"], "expected_revision": 1}],
        "payload": {"goal": "Synthetic retired goal", "artifact_id": f.arguments["artifact_id"],
                    "source_revision": 1},
    })
    assert response.status_code == 409 and response.json()["code"] == "SOURCE_UNAVAILABLE"
    assert setup.client.post(path + f"/work-requests/{uuid4()}/resume",
                             headers=setup.headers, json={"idempotency_key": str(uuid4())}
                             ).status_code == 404
    assert counts(setup) == before


def test_legacy_context_cannot_use_common_t0_or_synthetic_qualification_bypass(setup):
    f = fixture(setup)
    before = counts(setup)
    ctx = replace(setup.ctx, actor_id=setup.agent, run_id=uuid4())
    command = Command(command_id=uuid4(), idempotency_key=str(uuid4()),
                      category_id=setup.category, product_id=setup.product,
                      operation="evidence.claim.record", expected_revision=1,
                      source_read_set=[{"artifact_id": f.arguments["artifact_id"],
                                        "expected_revision": 1}], payload=f.arguments)
    with f.adapter.transaction(f.scope) as session:
        with pytest.raises(DomainError) as denied:
            execute(session, ctx, command, synthetic_mode=True)
        assert denied.value.code == "FORBIDDEN_SCOPE"
    assert counts(setup) == before
