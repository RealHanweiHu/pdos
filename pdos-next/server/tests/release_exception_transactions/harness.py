"""One real local PG/HTTP chain, invoked only by the existing isolated fixture.

All materials and professional facts are explicitly synthetic. No network,
physical qualification, production use or external delivery is established.
Importing this module never creates an environment or opens a connection.
"""

import json
import os
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from manufacturing_preparation import publication_pg_helpers as upstream
from release_policy_transactions import test_decisions as releases
from sqlalchemy import select
from test_project_first_plan import cmd

from pdos_next.domain.release.models import ReleaseDecision
from pdos_next.domain.release.policy_models import ReleasePolicyCurrent, ReleasePolicyFact
from pdos_next.domain.release.policy_owner import ActualReleasePolicyOwner
from pdos_next.domain.release_exceptions import service
from pdos_next.domain.release_exceptions.constants import DECIDE, WITHDRAW
from pdos_next.domain.release_exceptions.models import (
    ReleaseExceptionCurrent as Current,
)
from pdos_next.domain.release_exceptions.models import (
    ReleaseExceptionDecision as Decision,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.safety import verify_test_target

MODELS = (*releases.MODELS, Decision, Current)
WAIVABLE_RULE = "engineering.bounded_test_disposition"


def _guard(work):
    if os.environ.get("PDOS_RELEASE_EXCEPTION_LINK") != "1":
        raise RuntimeError("Actual release-exception chain requires explicit isolated opt-in")
    verify_test_target(work.setup.admin)
    verify_test_target(work.setup.engine)


def prepare_authority(work):
    """Register both real operation facts before initial policy source watermarks."""
    _guard(work)
    setup, at = work.setup, now()
    for actor, role, operation in (
        (setup.human, "engineering", DECIDE),
        (setup.peer, "manufacturing", WITHDRAW),
    ):
        line = (
            f"Synthetic named {role} authority for {actor}, {work.project_id}, "
            f"{work.purpose}; operation {operation}. No production qualification."
        )
        artifact = upstream.register_text(setup, "Synthetic bounded exception authority", line)
        for kind in ("duty", "qualification"):
            payload = {
                "product_id": str(setup.product),
                "project_id": str(work.project_id),
                "subject_id": str(actor),
                "external_id": f"synthetic-release-exception-{actor}-{kind}",
                "kind": kind,
                "role": role,
                "operations": [operation],
                "purposes": [work.purpose],
                "state": "active",
                "valid_from": (at - timedelta(minutes=1)).isoformat(),
                "valid_until": (at + timedelta(minutes=40)).isoformat(),
                "approval": {
                    "system": "Synthetic bounded exception authority",
                    "external_id": str(uuid4()),
                    "version": "isolated-exception-v1",
                    "approved_by": "Controlled fixture issuer",
                    "issued_at": (at - timedelta(minutes=1)).isoformat(),
                },
                "sources": [
                    {"artifact_id": artifact, "expected_revision": 1, "line": 1, "quote": line}
                ],
                "reason": "Independent scoped operation; not an inherited publication grant",
            }
            with upstream.session(work) as s:
                import_professional_fact(
                    s,
                    setup.ctx,
                    work.issuer,
                    payload,
                    request_key=str(uuid4()),
                    command_id=uuid4(),
                )


def _inputs(work, operation, payload, *, actor=None):
    before = upstream.snapshots(work, MODELS)
    command = cmd(work.setup, operation, deepcopy(payload))
    response = work.setup.client.post(
        releases.root(work) + "/release-exception/inputs",
        headers=upstream.headers(work, actor),
        json=command,
    )
    assert response.status_code == 200, response.text
    assert upstream.snapshots(work, MODELS) == before
    value = response.json()
    command["payload"] = value["payload"]
    command["source_read_set"] = value["required_source_read_set"]
    assert value["operation"] == operation
    assert value["candidate"]["state"] == "READY"
    assert value["candidate"]["signers"] == [str(actor or work.setup.human)]
    assert value["authority"]["authorized"] is value["authority"]["qualified"] is True
    return command, value


def _preview(work, command, *, actor=None):
    before = upstream.snapshots(work, MODELS)
    response = releases.send(work, command, actor=actor, preview=True)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["write_tier"] == "T2" and value["named_decision"] is True
    assert value["expires_at"] is None
    assert value["review"]["after"]["prepared_at"] is None
    result = value["command"]
    assert result["command_id"] == command["command_id"]
    assert result["idempotency_key"] == command["idempotency_key"]
    assert result["source_read_set"] == command["source_read_set"]
    assert result["payload"]["approval_token"]
    after = upstream.snapshots(work, MODELS)
    for model in MODELS:
        key = model.__tablename__
        if model is Confirmation:
            assert after[key]["count"] == before[key]["count"] + 1
        else:
            assert after[key] == before[key]
    return result


def _saved(work, command, *, actor=None):
    response = releases.send(work, command, actor=actor)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["subject_type"] == "release_exception" and result["subject_revision"] == 1
    assert result["operation"] == command["operation"]
    return result


def _exception(work, identity, *, actor=None):
    response = work.setup.client.get(
        releases.root(work) + "/release-exceptions/" + str(identity),
        headers=upstream.headers(work, actor),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_atom(work, command, receipt, *, actor, epoch):
    with upstream.session(work, actor) as s:
        row = s.get(Decision, UUID(receipt["subject_id"]))
        saved = s.get(Receipt, UUID(receipt["id"]))
        proof = s.get(Confirmation, row.shared_proof_id)
        pointer = s.scalar(select(Current).where(Current.series_id == row.series_id))
        assert row.revision == 1 and row.actor_id == row.requester_id == row.writer_id == actor
        assert row.receipt_id == saved.id and row.command_id == saved.command_id
        assert saved.subject_id == row.id and saved.subject_type == "release_exception"
        assert row.shared_proof_id == saved.confirmation_id == proof.id
        assert proof.actor_id == actor and proof.operation == command["operation"]
        assert proof.consumed is True and proof.expires_at is None
        assert row.proof_expires_at is None
        assert proof.created_at <= row.proof_consumed_at <= row.created_at <= saved.created_at
        assert pointer.epoch == epoch and pointer.decision_revision == 1
        assert pointer.decision_id == row.id
        assert row.body["expiry"] is None and row.body["selected_checks"][0]["state"] == "unknown"
        assert row.body["policy_fact"] == {
            "id": str(row.policy_fact_id),
            "revision": row.policy_fact_revision,
        }
        assert (
            row.input_snapshot["original_key_sha256"]
            == sha256(command["idempotency_key"].encode()).hexdigest()
        )
        assert "idempotency_key" not in row.input_snapshot["command"]
        assert "approval_token" not in row.input_snapshot["command"]["payload"]
        assert command["idempotency_key"] not in str(row.input_snapshot)
        assert command["payload"]["approval_token"] not in str(row.input_snapshot)
        for model in (Audit, Outbox, RequestKey):
            rows = list(s.scalars(select(model).where(model.receipt_id == saved.id)))
            assert len(rows) == 1 and rows[0].actor_id == actor
        assert (
            saved.request_digest == row.request_digest and saved.intent_digest == row.intent_digest
        )


def run(work, second, package_payload, policy, prior, monkeypatch):
    """Invoked after the original policy withdrawal and old publication replay."""
    _guard(work)
    setup = work.setup
    with upstream.session(work) as s:
        pointers = list(
            s.scalars(
                select(ReleasePolicyCurrent).where(
                    ReleasePolicyCurrent.tenant_id == setup.tenant,
                    ReleasePolicyCurrent.product_id == setup.product,
                    ReleasePolicyCurrent.project_id == work.project_id,
                )
            )
        )
        assert len(pointers) == 1
        pointer = pointers[0]
        actual_previous = {"id": str(pointer.fact_id), "revision": pointer.revision}
        withdrawn = s.get(ReleasePolicyFact, pointer.fact_id)
        assert withdrawn.status == "withdrawn" and withdrawn.material == policy
        assert actual_previous != prior and pointer.epoch == 2
    active = deepcopy(policy)
    active.update(status="active", policy_version="synthetic-documentation-exception-v3")
    assert len(active["rules"]) == 2
    active["rules"].append(
        {
            "id": WAIVABLE_RULE,
            "version": "1",
            "discipline": "engineering",
            "scope": deepcopy(active["release_scope"]),
            "applicable_if": {"op": "always"},
            "predicate": {"op": "test_run_status", "status": "disposed"},
            "required_evidence": ["test_run"],
            "freshness": "current",
            "severity": "required",
            "responsible_role": "engineering",
            "waivable": True,
            "allowed_purpose": [work.purpose],
        }
    )
    line = json.dumps(active, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    artifact = upstream.register_text(setup, "Synthetic active bounded exception policy", line)
    policy_source = releases.source(artifact, line)
    with upstream.session(work) as s:
        imported = ActualReleasePolicyOwner(setup.engine).import_policy(
            s,
            setup.ctx,
            setup.product,
            {
                "project_id": str(work.project_id),
                "source": policy_source,
                "expected_previous": actual_previous,
                "reason": "Restore active controlled policy with one explicit waivable unknown",
            },
            command_id=uuid4(),
            request_key=str(uuid4()),
        )
    policy_ref = {"id": imported["subject_id"], "revision": imported["subject_revision"]}
    next_payload = deepcopy(package_payload)
    next_payload.update(
        previous={"id": second["id"], "revision": second["revision"]},
        exceptions=[],
        reason="New fixed package retains the unfulfilled engineering test disposition",
    )
    command, unknown = releases.inputs(work, "release.package.assemble", next_payload)
    assert unknown["assessments"]["engineering"]["state"] == "UNKNOWN"
    assert unknown["assessments"]["manufacturing"]["state"] == "READY"
    original_check = next(
        value for value in unknown["candidate"]["checks"] if value["key"] == WAIVABLE_RULE
    )
    assert original_check["state"] == "unknown" and original_check["non_waivable"] is False
    response = releases.send(work, command)
    assert response.status_code == 200, response.text
    basis_package = releases.fixed(work, response.json()["subject_id"])
    controls_line = (
        f"Synthetic exception for {basis_package['id']}, {work.purpose}, {WAIVABLE_RULE}: "
        "limited internal documentation only; keep quarantine and individual traceability; "
        "the missing test disposition remains unknown; no physical or production permission."
    )
    control_artifact = upstream.register_text(
        setup, "Synthetic exact exception controls", controls_line
    )
    control_source = releases.source(control_artifact, controls_line)
    exception_payload = {
        "basis_package": {"id": basis_package["id"], "revision": basis_package["revision"]},
        "discipline": "engineering",
        "release_scope": deepcopy(next_payload["release_scope"]),
        "purpose": work.purpose,
        "check_keys": [WAIVABLE_RULE],
        "limits": [
            {
                "text": "Internal documentation scope only; no physical production",
                "sources": [control_source],
            }
        ],
        "risk_controls": [
            {"text": "Keep quarantine and individual traceability", "sources": [control_source]}
        ],
        "expiry": None,
        "sources": [control_source],
        "reason": "Named bounded exception; original unknown test evidence remains unchanged",
    }
    exception_command, prepared = _inputs(work, DECIDE, exception_payload)
    assert prepared["candidate"]["policy_fact"] == policy_ref
    assert prepared["candidate"]["selected_checks"] == [original_check]
    exception_command = _preview(work, exception_command)
    before = upstream.snapshots(work, MODELS)

    def fail_tail(*args, **kwargs):
        raise DomainError("INTEGRATION_REQUIRED", "One deliberate exception tail rollback", 503)

    with monkeypatch.context() as patch:
        patch.setattr(service, "finalize_receipt", fail_tail)
        failed = releases.send(work, exception_command)
        assert failed.status_code == 503, failed.text
        assert upstream.snapshots(work, MODELS) == before
    exception_receipt = _saved(work, exception_command)
    _assert_atom(work, exception_command, exception_receipt, actor=setup.human, epoch=1)
    exception_ref = {
        "id": exception_receipt["subject_id"],
        "revision": exception_receipt["subject_revision"],
    }
    approved = _exception(work, exception_ref["id"])
    assert approved["action"] == "approved" and approved["applicability"] == "current"
    assert approved["as_of"] == {"decision": exception_ref, "epoch": 1, "action": "approved"}
    next_payload.update(
        previous={"id": basis_package["id"], "revision": basis_package["revision"]},
        exceptions=[exception_ref],
        reason="Explicit new fixed package consumes the separate bounded exception",
    )
    command, conditional = releases.inputs(work, "release.package.assemble", next_payload)
    engineering = conditional["assessments"]["engineering"]
    assert engineering["state"] == "READY_WITH_CONDITIONS"
    assert engineering["conditions"] == [exception_ref]
    assert conditional["assessments"]["manufacturing"]["state"] == "READY"
    assert next(v for v in engineering["checks"] if v["key"] == WAIVABLE_RULE) == original_check
    response = releases.send(work, command)
    assert response.status_code == 200, response.text
    fixed = releases.fixed(work, response.json()["subject_id"])
    decision_payload = {
        "package": {"id": fixed["id"], "revision": fixed["revision"]},
        "release_scope": deepcopy(next_payload["release_scope"]),
        "purpose": work.purpose,
        "expiry": None,
        "sources": [policy_source],
        "reason": "Named release preserves the exact independent exception controls",
    }
    decision_ids = []
    for discipline, actor in (("engineering", setup.human), ("manufacturing", setup.peer)):
        command, actual = releases.inputs(
            work, f"release.{discipline}.approve", decision_payload, actor
        )
        assert actual["candidate"]["assessment"]["state"] == (
            "READY_WITH_CONDITIONS" if discipline == "engineering" else "READY"
        )
        preview = releases.send(work, command, actor=actor, preview=True)
        assert preview.status_code == 200, preview.text
        assert preview.json()["expires_at"] is None
        saved = releases.send(work, preview.json()["command"], actor=actor)
        assert saved.status_code == 200, saved.text
        decision_ids.append(UUID(saved.json()["subject_id"]))
    before_withdrawal = releases.fixed(work, fixed["id"])
    assert len(before_withdrawal["decisions"]) == 2
    withdrawal_line = (
        f"Synthetic peer {setup.peer} explicitly withdraws exception {exception_ref['id']} "
        f"for {work.project_id}, {work.purpose}; retain original approval and release history."
    )
    withdrawal_artifact = upstream.register_text(
        setup, "Synthetic named exception withdrawal", withdrawal_line
    )
    withdrawal_command, _ = _inputs(
        work,
        WITHDRAW,
        {
            "exception": exception_ref,
            "sources": [releases.source(withdrawal_artifact, withdrawal_line)],
            "reason": "Other named peer withdraws the exact original exception, preserving history",
        },
        actor=setup.peer,
    )
    withdrawal_command = _preview(work, withdrawal_command, actor=setup.peer)
    withdrawal_receipt = _saved(work, withdrawal_command, actor=setup.peer)
    _assert_atom(work, withdrawal_command, withdrawal_receipt, actor=setup.peer, epoch=2)
    withdrawn = _exception(work, withdrawal_receipt["subject_id"], actor=setup.peer)
    assert withdrawn["id"] != approved["id"] and withdrawn["series_id"] == approved["series_id"]
    assert withdrawn["decision"]["previous"] == exception_ref
    assert withdrawn["as_of"] == {
        "decision": {"id": withdrawn["id"], "revision": 1},
        "epoch": 2,
        "action": "withdrawn",
    }
    retained = _exception(work, approved["id"])
    assert (
        retained["decision"] == approved["decision"]
        and retained["applicability"] == "needs_recheck"
    )
    retained_package = releases.fixed(work, fixed["id"])
    assert retained_package["applicability"] == "needs_recheck"
    assert retained_package["package"] == fixed["package"]
    assert len(retained_package["decisions"]) == 2
    with upstream.session(work) as s:
        rows = list(
            s.scalars(select(Decision).where(Decision.series_id == UUID(approved["series_id"])))
        )
        assert len(rows) == 2 and {row.action for row in rows} == {"approved", "withdrawn"}
        assert {row.actor_id for row in rows} == {setup.human, setup.peer}
        assert all(
            row.revision == 1 and row.policy_fact_id == UUID(policy_ref["id"]) for row in rows
        )
        decisions = list(
            s.scalars(select(ReleaseDecision).where(ReleaseDecision.id.in_(decision_ids)))
        )
        assert len(decisions) == 2 and {row.actor_id for row in decisions} == {
            setup.human,
            setup.peer,
        }
        assert all(row.proof_expires_at is None for row in decisions)
    before_replay = upstream.snapshots(work, MODELS)
    for command, expected, actor in (
        (exception_command, exception_receipt, setup.human),
        (withdrawal_command, withdrawal_receipt, setup.peer),
    ):
        assert _saved(work, deepcopy(command), actor=actor) == expected
        assert upstream.snapshots(work, MODELS) == before_replay
    if os.environ.get("PDOS_RELEASE_EXCEPTION_BROWSER_SEED") == "1":
        from .browser_seed import run_browser_seed

        browser_package_payload = deepcopy(next_payload)
        browser_package_payload.update(
            previous={"id": fixed["id"], "revision": fixed["revision"]},
            exceptions=[],
            reason="Separate current fixed package for actual named browser decisions",
        )
        browser_command, browser_inputs = releases.inputs(
            work, "release.package.assemble", browser_package_payload
        )
        assert browser_inputs["assessments"]["engineering"]["state"] == "UNKNOWN"
        browser_saved = releases.send(work, browser_command)
        assert browser_saved.status_code == 200, browser_saved.text
        browser_package = releases.fixed(work, browser_saved.json()["subject_id"])
        browser_controls = (
            f"Synthetic browser exception controls for fixed package {browser_package['id']} "
            f"revision {browser_package['revision']}, {work.project_id}, {work.purpose}, "
            f"rule {WAIVABLE_RULE}: internal documentation only; keep quarantine and individual "
            "traceability; original test disposition remains unknown. No physical production."
        )
        browser_artifact = upstream.register_text(
            setup, "Synthetic fixed browser exception controls", browser_controls
        )
        browser_source = releases.source(browser_artifact, browser_controls)
        browser_decide = deepcopy(exception_payload)
        browser_decide.update(
            basis_package={"id": browser_package["id"], "revision": browser_package["revision"]},
            sources=[browser_source],
            reason="Actual named browser decision over this separate fixed synthetic package",
        )
        for item in (*browser_decide["limits"], *browser_decide["risk_controls"]):
            item["sources"] = [browser_source]
        browser_withdrawal_line = (
            f"Synthetic browser withdrawal procedure for the next named bounded exception "
            f"over fixed package {browser_package['id']} revision {browser_package['revision']}, "
            f"project {work.project_id}, purpose {work.purpose}. The named peer must explicitly "
            "select the actual new exception identity, retain its original approval and sources, "
            "and withdraw only that series. This procedure alone records no withdrawal."
        )
        browser_withdrawal_artifact = upstream.register_text(
            setup, "Synthetic next browser series withdrawal basis", browser_withdrawal_line
        )
        run_browser_seed(
            work,
            browser_package,
            browser_decide,
            releases.source(browser_withdrawal_artifact, browser_withdrawal_line),
        )
