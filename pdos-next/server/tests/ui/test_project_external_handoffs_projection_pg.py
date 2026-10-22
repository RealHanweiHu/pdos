"""Actual external handoff GET DTOs sampled around one existing synthetic chain.

Only root executes with explicitly verified isolated pdos_test URLs and the
handoff opt-in. All writes remain existing public commands/controlled imports;
the sole wrapper observes the real harness reader and returns its exact object.
No connector, socket, browser, model or external delivery is started.
"""

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID

from external_handoff_transactions import harness
from manufacturing_preparation import publication_pg_helpers as upstream
from manufacturing_preparation.publication_pg_helpers import publication_case as publication_case
from release_policy_transactions import test_decisions as flow
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_project_first_plan import post

from pdos_next.domain.configurations.models import EngineeringConfiguration
from pdos_next.domain.external_handoff.evidence_owner import revoke_issuer
from pdos_next.domain.release.policy_owner import ActualReleasePolicyOwner
from tests.ui import test_project_release_packages_projection_pg as release_ui

PHASES = (
    "authorized_without_receipts",
    "sent_outcome_unknown",
    "sent_explicitly_reconciled",
    "partially_accepted",
    "fully_accepted",
    "effectiveness_recorded",
    "manifest_conflict_retained",
)


def _counts(work):
    # The frozen release helper enumerates 32 distinct prerequisite tables.
    # Add only four handoff-specific tables, not harness.MODELS' common repeats.
    counts = release_ui._counts(work)
    with Session(work.setup.admin) as session:
        for model in (
            harness.Authorization,
            harness.Intent,
            harness.Current,
            harness.ExternalReceipt,
        ):
            assert model.__tablename__ not in counts
            counts[model.__tablename__] = session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
    return counts


def _read(work, identity, kind, *, actor=None):
    path = harness._root(work) + "/external-handoffs"
    params = {"project_id": str(work.project_id)} if kind == "project_handoffs" else {}
    if kind != "project_handoffs":
        path += "/" + str(identity)
    if kind == "receipts":
        path += "/receipts"
    response = work.setup.client.get(path, params=params, headers=upstream.headers(work, actor))
    return {
        "path": path,
        "params": params,
        "status_code": response.status_code,
        "body": response.json(),
    }


def _ok(read):
    assert read["status_code"] == 200, read["body"]
    return read["body"]


def _phase(work, identity, phase, *, access=False):
    before = _counts(work)
    reads = {
        kind: _read(work, identity, kind) for kind in ("project_handoffs", "detail", "receipts")
    }
    if access:
        for actor_name, actor in (("peer", work.setup.peer), ("foreign", work.setup.other_human)):
            for kind in ("project_handoffs", "detail", "receipts"):
                reads[actor_name + "_" + kind] = _read(work, identity, kind, actor=actor)
    after = _counts(work)
    assert before == after
    detail, page, receipts = (
        _ok(reads[name]) for name in ("detail", "project_handoffs", "receipts")
    )
    assert detail["id"] == str(identity) and detail["project_id"] == str(work.project_id)
    assert page["next_cursor"] is None and receipts["before_sequence"] is None
    [header] = page["items"]
    assert all(detail[key] == value for key, value in header.items())
    assert header["as_of"] == detail["as_of"] == receipts["as_of"]
    assert detail["as_of"]["receipt_count"] == len(receipts["items"])
    assert detail["as_of"]["epoch"] == len(receipts["items"]) + 1
    assert detail["network_send"] is False and detail["reading"]["network_send"] is False
    for row in receipts["items"]:
        assert row["original"]["handoff"] == {"id": detail["id"], "revision": detail["revision"]}
        assert row["original"]["intent"] == {
            "id": detail["intent"]["id"],
            "revision": detail["intent"]["revision"],
        }
        assert row["original"]["occurred_at"] and row["received_at"]
        assert row["source"] and row["issuer"] and row["receipt_id"]
    if access:
        for kind in ("project_handoffs", "detail", "receipts"):
            assert _ok(reads["peer_" + kind]) == _ok(reads[kind])
            refused = reads["foreign_" + kind]
            assert refused["status_code"] == 403, refused
            assert refused["body"]["code"] == "FORBIDDEN_SCOPE"
            assert "items" not in refused["body"] and "authorization" not in refused["body"]
    return {
        "phase": phase,
        "reads": reads,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
    }


def _export(work, phases, handoff, receipts):
    destination = os.environ.get("PDOS_UI_PROJECT_EXTERNAL_HANDOFFS_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual external handoff DTO export requires an absolute path"
    bundle = {
        "version": "project-external-handoffs-projection-qa/v1",
        "fixture_nature": "actual command/HTTP chain with bounded synthetic originals and issuer",
        "scope": {
            "category_id": str(work.setup.category),
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            "principal_id": str(work.setup.human),
            "handoff_id": handoff["handoff_id"],
            "intent_id": handoff["intent_id"],
        },
        "phases": phases,
        "handoff_summary": handoff,
        "command_receipts": receipts,
        "limitations": [
            "Every sampled body/status is an unmodified actual GET response.",
            "The harness reader is wrapped only for real GET sampling; writes are unchanged.",
            "Unknown send requires explicit reconciliation; partial acceptance covers only CN.",
            "List/detail/receipt pointers are compared, without claiming one shared transaction.",
            "Receipt occurrence and local received_at remain separate original clocks.",
            "Conflict and withdrawal retain the fixed authorization, intent and receipts.",
            "Synthetic external outcomes represent controlled originals, not a real network send.",
            "No actual external/production qualification, connector or delivery is authorized.",
        ],
    }

    def assert_null_approval_tokens(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "approval_token":
                    assert child is None, "Actual DTO export must contain no approval-token value"
                assert_null_approval_tokens(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                assert_null_approval_tokens(child)

    assert_null_approval_tokens(bundle)
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_external_handoff_reads_keep_reconciliation_partial_scope_and_conflict_history(
    publication_case, monkeypatch
):
    assert os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") == "1", "Explicit isolated opt-in required"
    assert all(
        os.environ.get(name) != "1"
        for name in ("PDOS_EXTERNAL_HANDOFF_BROWSER_SEED", "PDOS_RELEASE_POLICY_BROWSER_SEED")
    ), "This test must remain without browser/server seeds"
    work, phases, receipts = publication_case, [], {}
    setup = work.setup
    upstream.import_authority(work, setup.human)
    upstream.save_drafts(work)
    command, _ = upstream.prepare_publication(work, upstream.publication_payload(work))
    response = post(setup, command)
    assert response.status_code == 200, response.text
    receipts["manufacturing_publication"] = response.json()
    publication = upstream.publication(work, receipts["manufacturing_publication"])
    with upstream.session(work) as session:
        engineering = session.get(
            EngineeringConfiguration, UUID(work.config["engineering"]["subject_id"])
        )
        configuration = {
            "definition": {
                "id": str(engineering.definition_id),
                "revision": engineering.definition_revision,
            },
            "engineering_configuration": {
                "id": str(engineering.id),
                "revision": engineering.revision,
            },
            "manufacturing_configuration": work.process_ref,
        }
    release_scope = {
        "quantity": None,
        "unit": None,
        "lots": [],
        "site": "SYN-INTERNAL-LAB",
        "lines": [],
        "regions": ["CN", "DE"],
    }
    document = {"kind": "artifact", "id": work.document_source, "revision": 1}
    publication_ref = {
        "kind": "manufacturing_publication",
        "id": publication["id"],
        "revision": publication["revision"],
    }
    flow.authorize(
        work, setup.human, "engineering", ["release.policy.import", "release.engineering.approve"]
    )
    flow.authorize(work, setup.peer, "manufacturing", ["release.manufacturing.approve"])
    # Fix this authorization's current professional-source set before policy import.
    harness.prepare_authority(work)
    policy = release_ui._policy(work, configuration, release_scope, document, publication_ref)
    owner = ActualReleasePolicyOwner(setup.engine)
    receipts["policy_active"], policy_source = release_ui._import_policy(work, owner, policy)
    package_payload = {
        "project_id": str(work.project_id),
        "subject_config": configuration,
        "release_scope": release_scope,
        "purpose": work.purpose,
        "manufacturing_publication": {"id": publication["id"], "revision": publication["revision"]},
        "documents": [document],
        "sources": [flow.source(work.document_source, upstream.LINES[0])],
        "visibility": "category",
        "reason": "Fixed synthetic documentation packet for bounded external handoff UI reads",
    }
    command, material = flow.inputs(work, "release.package.assemble", package_payload)
    assert {value["state"] for value in material["assessments"].values()} == {"READY"}
    response = flow.send(work, command)
    assert response.status_code == 200, response.text
    receipts["package"] = response.json()
    package = flow.fixed(work, receipts["package"]["subject_id"])
    decisions = []
    for discipline, actor in (("engineering", setup.human), ("manufacturing", setup.peer)):
        command, material = flow.inputs(
            work,
            f"release.{discipline}.approve",
            {
                "package": {"id": package["id"], "revision": package["revision"]},
                "release_scope": release_scope,
                "purpose": work.purpose,
                "expiry": None,
                "sources": [policy_source],
                "reason": "Named synthetic decision for the exact bounded documentation packet",
            },
            actor,
        )
        assert material["candidate"]["assessment"]["state"] == "READY"
        preview = flow.send(work, command, actor=actor, preview=True)
        assert preview.status_code == 200 and preview.json()["expires_at"] is None, preview.text
        response = flow.send(work, preview.json()["command"], actor=actor)
        assert response.status_code == 200, response.text
        receipts[discipline + "_decision"] = response.json()
        decisions.append(response.json()["subject_id"])

    original_reading = harness._reading
    seen = set()

    def sample_actual_reading(selected, identity):
        actual = original_reading(selected, identity)
        count = actual["as_of"]["receipt_count"]
        if count not in seen:
            assert selected is work and 0 <= count < len(PHASES)
            phase = _phase(work, identity, PHASES[count])
            assert _ok(phase["reads"]["detail"]) == actual
            phases.append(phase)
            seen.add(count)
        return actual  # Keep the original actual helper object, never reconstruct it.

    monkeypatch.setattr(harness, "_reading", sample_actual_reading)
    issuer_key = "synthetic-handoff-" + str(work.project_id)
    try:
        summary = harness.run(work, package, decisions)
        assert seen == set(range(len(PHASES))) and len(phases) == 7
        originals = _ok(phases[0]["reads"]["detail"])
        for count, phase in enumerate(phases):
            detail = _ok(phase["reads"]["detail"])
            assert detail["as_of"]["receipt_count"] == count
            assert detail["authorization"] == originals["authorization"]
            assert detail["intent"] == originals["intent"]
            assert detail["receipt_id"] == originals["receipt_id"]
        assert _ok(phases[1]["reads"]["detail"])["reading"]["delivery_unknown"] is True
        reconciled = _ok(phases[2]["reads"]["detail"])["reading"]
        assert (
            reconciled["delivery_unknown"] is False and reconciled["sent"]["state"] == "succeeded"
        )
        partial = _ok(phases[3]["reads"]["detail"])["reading"]
        assert partial["accepted"]["state"] == "partial"
        partial_receipt = next(
            row
            for row in _ok(phases[3]["reads"]["receipts"])["items"]
            if row["id"] == summary["partial"]["id"]
        )
        assert partial_receipt["original"]["release_scope"]["regions"] == ["CN"]
        assert _ok(phases[4]["reads"]["detail"])["reading"]["accepted"]["state"] == "succeeded"
        assert _ok(phases[5]["reads"]["detail"])["reading"]["effective"]["state"] == "succeeded"
        conflict = _ok(phases[6]["reads"]["detail"])
        assert conflict["reading"]["conflict"] is True
        assert conflict["reading"]["effective"]["state"] == "conflict"
        assert "MANIFEST_MISMATCH" in conflict["reading"]["effective"]["mismatches"]
        withdrawn = {
            **deepcopy(policy),
            "status": "withdrawn",
            "policy_version": "synthetic-ui-handoff-policy-withdrawn",
        }
        receipts["policy_withdrawal"], _ = release_ui._import_policy(
            work,
            owner,
            withdrawn,
            previous={
                "id": receipts["policy_active"]["subject_id"],
                "revision": receipts["policy_active"]["subject_revision"],
            },
        )
        withdrawn_phase = _phase(
            work, summary["handoff_id"], "policy_withdrawn_fixed_history_retained", access=True
        )
        phases.append(withdrawn_phase)
        retained = _ok(withdrawn_phase["reads"]["detail"])
        assert retained["applicability"] == "needs_recheck"
        assert {key: value for key, value in retained.items() if key != "applicability"} == {
            key: value for key, value in conflict.items() if key != "applicability"
        }
        assert _ok(withdrawn_phase["reads"]["receipts"]) == _ok(phases[6]["reads"]["receipts"])
        _export(work, phases, summary, receipts)
    finally:
        revoke_issuer(setup.engine, issuer_key)
