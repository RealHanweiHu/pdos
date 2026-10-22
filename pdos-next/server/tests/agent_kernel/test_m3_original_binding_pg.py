"""Actual uploaded bytes, proposal references and run binding; no model execution."""
# ruff: noqa: F811 -- pytest uses the explicitly imported marked PG fixtures

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from security_fixture import secured_parse
from sqlalchemy import select
from test_durable_evidence import upload_input

from pdos_next.agent_kernel.api import ApiPorts, StartInput
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentRun
from pdos_next.agent_kernel.policy import egress
from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.original_security import security_row
from pdos_next.originals import require_original
from tests.preproject.test_evidence_commands_pg import artifact
from tests.preproject.test_g0 import create
from tests.preproject.test_g0 import work as work
from tests.test_original_security import security_work as security_work

QUOTE = "Synthetic original: noise must not exceed 75 dB(A)."


def uploaded(work, security_work, *, visibility="private", label="public"):
    response = security_work.client.post(
        f"/v1/categories/{work.category}/originals",
        headers=work.headers,
        json=upload_input(
            (QUOTE + "\n").encode(), visibility=visibility, source_label=label,
        ).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    root_id = UUID(response.json()["subject_id"])
    parsed = secured_parse(work.engine, {
        "tenant_id": str(work.tenant), "category_id": str(work.category),
        "product_id": None, "actor_id": str(work.human),
        "requester_id": str(work.human), "subject_id": str(root_id),
    }, security_work.store)
    assert parsed["status"] == "parsed", parsed
    with tenant_session(work.engine, work.tenant, actor_id=work.human,
                        requester_id=work.human, category_id=work.category) as session:
        row = session.scalar(select(Artifact).where(Artifact.original_id == root_id))
        assert row.id != root_id and row.revision == 1
        version_id = row.id
    return root_id, version_id


def proposal(work, version_id):
    identity, _ = create(work, {
        "title": "Synthetic original-bound proposal",
        "entry_kind": "customer_request",
        "source_refs": [{"type": "original", "id": str(version_id), "version": 1,
                         "line": 1, "quote": QUOTE}],
    })
    return UUID(identity)


def binding(work, owner, proposal_id=None, sources=()):
    with tenant_session(work.engine, work.tenant, actor_id=work.human,
                        requester_id=work.human, category_id=work.category) as session:
        return owner.binding_for(session, work.ctx, StartInput(
            goal="Synthetic original-bound extraction", idempotency_key=str(uuid4()),
            proposal_id=proposal_id, sources=list(sources),
        ))


def actual_run(work, owner, proposal_id):
    dispatched = []

    async def start(ref):
        dispatched.append(ref)

    async def unused(*_):
        raise AssertionError("No workflow, model or provider is invoked by this fixture")

    ports = ApiPorts(writer_for=owner.writer_for, binding_for=owner.binding_for,
                     start_workflow=start, signal_workflow=unused, cancel_workflow=unused)
    with TestClient(create_app(work.engine, work.auth, agent_api_ports=ports)) as client:
        response = client.post(f"/v1/categories/{work.category}/agent-runs", headers=work.headers,
                               json={"goal": "Synthetic original-bound extraction",
                                     "idempotency_key": str(uuid4()),
                                     "proposal_id": str(proposal_id)})
    assert response.status_code == 202, response.text
    assert len(dispatched) == 1 and "goal" not in dispatched[0]
    with tenant_session(work.engine, work.tenant, actor_id=work.human,
                        requester_id=work.human, category_id=work.category) as session:
        row = session.get(AgentRun, UUID(response.json()["run_id"]))
        return scope_for_run(row), row.read_sources


def test_actual_original_reference_binds_only_mounted_version_and_provider_taint(
    work, security_work,
):
    root_id, version_id = uploaded(work, security_work)
    _, other_version = uploaded(work, security_work, label="another unrelated original")
    assert other_version != version_id
    proposal_id = proposal(work, version_id)
    owner = Bootstrap(work.engine)
    current = binding(work, owner, proposal_id)
    assert current.read_sources == [{"artifact_id": str(version_id),
                                     "expected_revision": 1, "product_id": None}]
    assert current.private_context and current.data_categories == ("customer_original", "internal")
    scope, sources = actual_run(work, owner, proposal_id)
    assert sources == current.read_sources and scope.private_context
    assert scope.data_categories == frozenset(current.data_categories)
    assert owner.default_preload(scope) == ("proposal_drafting", "gap_check", "rfq_extraction")
    with owner.store.transaction(scope) as (session, _):
        # P26: no registered agreement no longer blocks egress; the receipt carries none.
        decision = egress(session, scope, "synthetic-provider-with-no-agreement")
    assert decision.agreement_id is None
    assert set(decision.data_categories) == set(current.data_categories)
    assert root_id != version_id


def test_original_root_id_and_wrong_artifact_version_are_not_read_authority(work, security_work):
    root_id, version_id = uploaded(work, security_work)
    owner = Bootstrap(work.engine)
    for identity, revision, code in [(root_id, 1, "SOURCE_UNAVAILABLE"),
                                      (version_id, 2, "SOURCE_STALE")]:
        with pytest.raises(DomainError) as caught:
            binding(work, owner, sources=[{"artifact_id": identity, "expected_revision": revision}])
        assert caught.value.code == code


def test_unmounted_original_in_run_does_not_activate_rfq(work, security_work):
    _, version_id = uploaded(work, security_work)
    empty, _ = create(work, {"title": "Synthetic no original mount", "entry_kind": "new_product"})
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, UUID(empty))
    assert owner.default_preload(scope) == ("proposal_drafting", "gap_check")
    # An authorized explicit source can bind the Run without becoming a Proposal mount.
    actual = binding(
        work, owner, UUID(empty), [{"artifact_id": version_id, "expected_revision": 1}]
    )
    assert len(actual.read_sources) == 1 and "customer_original" in actual.data_categories


def test_current_new_scan_blocks_preload_and_new_proposal_run(work, security_work):
    root_id, version_id = uploaded(work, security_work)
    proposal_id = proposal(work, version_id)
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, proposal_id)
    assert "rfq_extraction" in owner.default_preload(scope)
    with tenant_session(work.engine, work.tenant, actor_id=work.human,
                        requester_id=work.human, category_id=work.category) as session:
        root = require_original(session, work.ctx, None, root_id)
        epoch = security_row(session, root, lock=False).epoch
    scan = security_work.client.post(
        f"/v1/categories/{work.category}/originals/{root_id}/scan", headers=work.headers,
        json={"expected_epoch": epoch, "idempotency_key": str(uuid4())},
    )
    assert scan.status_code == 200, scan.text
    assert owner.default_preload(scope) == ("proposal_drafting", "gap_check")
    with pytest.raises(DomainError) as caught:
        binding(work, owner, proposal_id)
    # Current source RLS hides the pending-scan original before its body is loaded.
    assert caught.value.code == "SOURCE_UNAVAILABLE"


def test_registered_text_called_original_does_not_substitute_uploaded_bytes(work):
    version_id = artifact(work, body=QUOTE, visibility="category")
    proposal_id = proposal(work, version_id)
    owner = Bootstrap(work.engine)
    scope, _ = actual_run(work, owner, proposal_id)
    assert scope.data_categories == frozenset({"internal"})
    assert owner.default_preload(scope) == ("proposal_drafting", "gap_check")
