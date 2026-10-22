"""One real business case, with a commit-then-lost-response and deferred atom rollback.

Only the client transport and a terminal common receipt failure are injected.
Domain owners, Sources, current qualifications, clock and transactions stay real.
"""

import json
from copy import deepcopy
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from test_project_first_plan import cmd, post

from pdos_next import service as common
from pdos_next.database import tenant_session
from pdos_next.domain.manufacturing_baseline.models import BaselineDocumentLink, PreparationVersion
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Receipt, RequestKey
from pdos_next.safety import verify_test_target
from pdos_next.service import digest, receipt_view

from .fixtures import (
    assert_atom,
    bootstrap_authority,
    effect_counts,
    effect_hashes,
    fixed,
    history,
    inputs,
    parents,
    payload,
    prepared,
    proof,
)

STANDARD_GAPS = {
    "TOOLING_ACCEPTANCE_OWNER_NOT_CONFIGURED",
    "FIXTURE_QUALIFICATION_OWNER_NOT_CONFIGURED",
    "MANUFACTURING_BASELINE_RELEASE_NOT_CONFIGURED",
    "MANUFACTURING_SCOPE_ENUMERATION_NOT_CONFIGURED",
}


def save(work, material):
    command = prepared(work, material)
    confirmation_id, consumed = proof(work, command)
    assert consumed is False
    response = post(work.setup, command)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert_atom(work, command, receipt)
    assert proof(work, command) == (confirmation_id, True)
    return command, receipt, fixed(work, receipt["subject_type"], receipt)


def reference(view):
    assert view["is_current"] is True and view["source_status"] == "current"
    return {field: view[field] for field in ("kind", "id", "revision")}


def gap_codes(body):
    return {gap["code"] for gap in body["gaps"]}


def test_current_manufacturing_first_save_history_unknown_and_common_rollback(
    manufacturing_case, monkeypatch
):
    work, setup = manufacturing_case, manufacturing_case.setup
    original_parents = parents(work)
    original_effects = effect_counts(work)
    wi_body, cp_body = payload(work, "work_instruction"), payload(work, "control_plan")
    input_url = (
        f"/v1/categories/{setup.category}/products/{setup.product}"
        "/manufacturing-preparations/inputs"
    )

    # Configuring an issuer does not give this person a duty or qualification.
    for kind, body in (("work_instruction", wi_body), ("control_plan", cp_body)):
        response = setup.client.post(
            input_url, headers=setup.headers, json=cmd(setup, f"npi.{kind}.record", body)
        )
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "QUALIFICATION_REQUIRED"
    assert effect_counts(work) == original_effects

    bootstrap_authority(work)
    initial = history(work)
    assert initial["versions"] == [] and initial["unavailable_count"] == 0
    assert initial["qualification"] == "unknown" and initial["manufacturing_release"] is None
    assert initial["negative_enumeration_complete"] is False
    authority_effects = effect_counts(work)

    # Neither independent preflight relies on having saved the other document.
    wi_inputs, cp_inputs = (
        inputs(work, "work_instruction", wi_body),
        inputs(work, "control_plan", cp_body),
    )
    assert effect_counts(work) == authority_effects
    missing_confirmation = post(setup, wi_inputs["command"])
    assert missing_confirmation.status_code == 409, missing_confirmation.text
    assert missing_confirmation.json()["code"] == "CONFIRMATION_REQUIRED"
    assert effect_counts(work) == authority_effects
    assert "INSTRUCTION_CONDITIONS_UNKNOWN" in gap_codes(wi_inputs["review"]["after"]["body"])
    assert "CONTROL_CHECK_INCOMPLETE" in gap_codes(cp_inputs["review"]["after"]["body"])
    cp_command, cp_receipt, cp_current = save(work, cp_inputs)
    assert cp_current["revision"] == 1 and cp_current["status"] == "draft"
    assert cp_current["body"]["input"]["checks"][0]["criterion"] is None

    # A missing WI is an honest gap in the complete Process, not a removed operation.
    cp_only = inputs(
        work,
        "manufacturing_baseline",
        payload(work, "manufacturing_baseline", documents={"control_plan": reference(cp_current)}),
    )
    assert {
        (gap["operation_key"], gap["kind"])
        for gap in cp_only["review"]["after"]["body"]["gaps"]
        if gap["code"] == "MISSING_OPERATION_DOCUMENT"
    } == {
        (key, kind)
        for key in work.operation_keys
        for kind in ("work_instruction", "control_plan")
        if key != work.operation_keys[0] or kind == "work_instruction"
    }
    assert parents(work) == original_parents

    wi_command, wi_receipt, wi_first = save(work, wi_inputs)
    assert wi_first["revision"] == 1 and wi_first["is_current"] is True
    first_body_sha = digest(wi_first["body"])
    wi2_inputs = inputs(
        work, "work_instruction", payload(work, "work_instruction", previous=wi_first, revision=2)
    )
    wi2_command, wi2_receipt, wi_current = save(work, wi2_inputs)
    assert wi_current["series_id"] == wi_first["series_id"]
    assert wi_current["revision"] == 2 and wi_current["previous_id"] == wi_first["id"]
    assert wi_current["previous_revision"] == 1
    assert wi_current["body"]["input"]["conditions"] is None
    parameter = wi_current["body"]["input"]["steps"][0]["parameters"][0]
    assert all(parameter[field] is None for field in ("nominal", "lower", "upper", "unit"))
    old = fixed(work, "work_instruction", wi_receipt)
    assert old["is_current"] is False and old["source_status"] == "current"
    assert old["revision"] == 1 and digest(old["body"]) == first_body_sha

    documents = {"work_instruction": reference(wi_current), "control_plan": reference(cp_current)}
    baseline_inputs = inputs(
        work, "manufacturing_baseline", payload(work, "manufacturing_baseline", documents=documents)
    )
    baseline_body = baseline_inputs["review"]["after"]["body"]
    assert {item["operation_key"] for item in baseline_body["input"]["operations"]} == set(
        work.operation_keys
    )
    assert len(baseline_body["input"]["operations"]) == len(work.operation_keys)
    assert STANDARD_GAPS | {"PROCESS_RISK_UNKNOWN", "PACKAGING_LABEL_UNKNOWN"} <= gap_codes(
        baseline_body
    )
    assert all(
        gap["operation_key"] != work.operation_keys[0]
        for gap in baseline_body["gaps"]
        if gap["code"] == "MISSING_OPERATION_DOCUMENT"
    )
    assert len(baseline_body["document_bindings"]) == 2
    expected_bindings = {
        (work.operation_keys[0], view["kind"], view["id"], view["revision"], digest(view["body"]))
        for view in (wi_current, cp_current)
    }
    assert {
        (item["operation_key"], item["kind"], item["id"], item["revision"], item["body_sha256"])
        for item in baseline_body["document_bindings"]
    } == expected_bindings

    baseline_command = prepared(work, baseline_inputs)
    exact_original_command = deepcopy(baseline_command)
    confirmation_id, consumed = proof(work, baseline_command)
    assert consumed is False
    before_unknown = effect_counts(work)
    actual_transport = setup.client._transport.handle_request
    lost_responses = []

    def lose_committed_response(request):
        response = actual_transport(request)
        if (
            request.url.path == f"/v1/categories/{setup.category}/commands"
            and request.method == "POST"
            and json.loads(request.content)["command_id"] == baseline_command["command_id"]
        ):
            # The real server has completed its transaction. Discard only its client response.
            assert response.status_code == 200
            response.read()
            response.close()
            lost_responses.append(request.url.path)
            raise httpx.ReadError("Synthetic response loss after actual commit", request=request)
        return response

    with monkeypatch.context() as fault:
        fault.setattr(setup.client._transport, "handle_request", lose_committed_response)
        with pytest.raises(httpx.ReadError, match="after actual commit"):
            post(setup, baseline_command)
    assert lost_responses == [f"/v1/categories/{setup.category}/commands"]
    assert baseline_command == exact_original_command
    assert proof(work, baseline_command) == (confirmation_id, True)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as session:
        key = session.scalar(
            select(RequestKey).where(
                RequestKey.actor_id == setup.human,
                RequestKey.key == baseline_command["idempotency_key"],
            )
        )
        assert key is not None
        committed_receipt = receipt_view(session.get(Receipt, key.receipt_id))
    assert_atom(work, baseline_command, committed_receipt)
    after_unknown = effect_counts(work)
    committed_effect_hashes = effect_hashes(work)
    assert {name: count - before_unknown[name] for name, count in after_unknown.items()} == {
        "manufacturing_preparation_versions": 1,
        "manufacturing_preparation_currents": 1,
        "manufacturing_baseline_document_links": 2,
        "action_receipts": 1,
        "audit_entries": 1,
        "outbox_events": 1,
        "request_keys": 1,
    }
    recovery = post(setup, exact_original_command)
    assert recovery.status_code == 200, recovery.text
    assert recovery.json() == committed_receipt
    assert effect_counts(work) == after_unknown
    assert effect_hashes(work) == committed_effect_hashes
    assert proof(work, baseline_command) == (confirmation_id, True)
    baseline_receipt = recovery.json()
    baseline_current = fixed(work, "manufacturing_baseline", baseline_receipt)
    assert baseline_current["is_current"] is True and baseline_current["source_status"] == "current"
    assert baseline_current["body"] == baseline_body
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as session:
        links = list(
            session.scalars(
                select(BaselineDocumentLink).where(
                    BaselineDocumentLink.baseline_id == UUID(baseline_receipt["subject_id"])
                )
            )
        )
        assert len(links) == 2
        assert {
            (link.operation_key, link.document_kind, str(link.document_id), link.document_revision)
            for link in links
        } == {binding[:4] for binding in expected_bindings}
        assert all(
            link.project_id == work.project_id
            and link.process_id == UUID(work.process_ref["id"])
            and link.process_revision == work.process_ref["revision"]
            and link.baseline_revision == 1
            for link in links
        )
    current_history = history(work)
    assert len(current_history["versions"]) == 4
    assert current_history["has_more"] is False and current_history["unavailable_count"] == 0
    assert {view["id"] for view in current_history["versions"]} == {
        receipt["subject_id"] for receipt in (wi_receipt, wi2_receipt, cp_receipt, baseline_receipt)
    }
    assert sum(view["is_current"] for view in current_history["versions"]) == 3
    assert all(
        view["status"] == "draft"
        and view["manufacturing_release"] is None
        and view["qualification"] == "unknown"
        and view["negative_enumeration_complete"] is False
        for view in current_history["versions"]
    )
    assert parents(work) == original_parents

    # The actual common writer fails after the new preparation row has been flushed.
    fault_body = payload(work, "work_instruction", previous=wi_current, revision=2)
    fault_body["reason"] = "Synthetic atomicity attempt with the same legitimate current basis"
    failed_command = prepared(work, inputs(work, "work_instruction", fault_body))
    failure_proof_id, consumed = proof(work, failed_command)
    assert consumed is False
    before_failure = effect_counts(work)
    before_failure_hashes = effect_hashes(work)
    failed_rows = []

    def fail_common_receipt(session, ctx, command, subject_type, subject, *args, **kwargs):
        assert command.command_id == UUID(failed_command["command_id"])
        assert subject_type == "work_instruction" and subject.revision == 3
        assert session.get(PreparationVersion, subject.id) is subject
        failed_rows.append(subject.id)
        raise DomainError("INTERNAL_ERROR", "Synthetic terminal common receipt failure")

    with monkeypatch.context() as fault:
        fault.setattr(common, "append_receipt", fail_common_receipt)
        failed = post(setup, failed_command)
    assert failed.status_code == 500, failed.text
    assert failed.json()["code"] == "INTERNAL_ERROR" and len(failed_rows) == 1
    assert effect_counts(work) == before_failure
    assert effect_hashes(work) == before_failure_hashes
    assert proof(work, failed_command) == (failure_proof_id, False)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.ctx.actor_id,
        requester_id=setup.ctx.requester_id,
        category_id=setup.category,
    ) as session:
        assert session.get(PreparationVersion, failed_rows[0]) is None
    assert fixed(work, "work_instruction", wi2_receipt) == wi_current
    assert fixed(work, "manufacturing_baseline", baseline_receipt) == baseline_current
    assert parents(work) == original_parents

    # Controlled negative fixture only: withdraw the exact newly registered document Source.
    # Definition, Process and professional credential Sources are never deleted or rewritten.
    verify_test_target(setup.admin)
    with Session(setup.admin) as session, session.begin():
        result = session.execute(
            update(Artifact)
            .where(
                Artifact.tenant_id == setup.tenant,
                Artifact.product_id == setup.product,
                Artifact.id == UUID(work.document_source),
                Artifact.owner_id == setup.human,
            )
            .values(status="withdrawn")
        )
        assert result.rowcount == 1
    retained = history(work)
    assert len(retained["versions"]) == 4 and retained["unavailable_count"] == 0
    assert all(view["source_status"] == "needs_recheck" for view in retained["versions"])
    assert fixed(work, "work_instruction", wi_receipt)["body"] == wi_first["body"]
    assert fixed(work, "manufacturing_baseline", baseline_receipt)["body"] == baseline_body
    before_stale_recovery = effect_counts(work)
    # The real Source withdrawal has already committed its legitimate Product
    # epoch advance. Recovery must leave this complete post-withdrawal state intact.
    before_stale_recovery_hashes = effect_hashes(work)
    stale_recovery = post(setup, exact_original_command)
    assert stale_recovery.status_code == 200, stale_recovery.text
    assert stale_recovery.json()["id"] == baseline_receipt["id"]
    fresh_input = setup.client.post(
        input_url,
        headers=setup.headers,
        json=cmd(
            setup,
            "npi.work_instruction.record",
            payload(work, "work_instruction", previous=wi_current, revision=3),
        ),
    )
    assert fresh_input.status_code in (403, 409), fresh_input.text
    assert fresh_input.json()["code"] == "SOURCE_STALE"
    assert effect_counts(work) == before_stale_recovery
    assert effect_hashes(work) == before_stale_recovery_hashes
    assert parents(work) == original_parents

    peer = setup.client.get(
        f"/v1/categories/{setup.category}/products/{setup.product}/manufacturing-preparations"
        f"?project_id={work.project_id}&process_id={work.process_ref['id']}",
        headers={"Authorization": f"Bearer {setup.tokens[setup.peer]}"},
    )
    # The actual G0 reviewer can read the resulting Product/Project. Private
    # manufacturing documents and their source bodies retain their own ACL.
    assert peer.status_code == 200, peer.text
    assert peer.json()["versions"] == []
    assert work.document_source not in peer.text
    assert all(
        command["payload"].get("confirmation_token")
        for command in (cp_command, wi_command, wi2_command, baseline_command, failed_command)
    )
