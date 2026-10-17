"""One actual PG/HTTP handoff chain inside the caller's isolated fixture.

No sockets, connectors, production issuer or remote delivery. The synthetic
issuer accepts only exact registered originals explicitly placed in its bounded
fixture ledger; it cannot attest arbitrary model/client material.
"""

import json
import os
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from manufacturing_preparation import publication_pg_helpers as upstream
from test_project_first_plan import cmd

from pdos_next.domain.external_handoff.constants import AUTHORIZE, RECEIPT_RECORD
from pdos_next.domain.external_handoff.evidence_owner import configure_local_synthetic
from pdos_next.domain.external_handoff.models import (
    ExternalDeliveryIntent as Intent,
)
from pdos_next.domain.external_handoff.models import (
    ExternalHandoffAuthorization as Authorization,
)
from pdos_next.domain.external_handoff.models import (
    ExternalHandoffCurrent as Current,
)
from pdos_next.domain.external_handoff.models import (
    ExternalReceipt as ExternalReceipt,
)
from pdos_next.domain.external_handoff.schemas import ReceiptOriginal
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.professional_import import import_professional_fact
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

MODELS = (
    Authorization,
    Intent,
    Current,
    ExternalReceipt,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
)


def _root(work):
    return f"/v1/categories/{work.setup.category}/products/{work.setup.product}"


def _source(identity, line):
    return {
        "kind": "artifact",
        "id": str(identity),
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(line.encode()).hexdigest(),
    }


def _inputs(work, operation, payload, *, expected=200):
    response = work.setup.client.post(
        _root(work) + "/external-handoff/inputs",
        headers=work.setup.headers,
        json=cmd(work.setup, operation, deepcopy(payload)),
    )
    assert response.status_code == expected, response.text
    if expected != 200:
        return None, response.json()
    value = response.json()
    command = cmd(work.setup, operation, value["payload"])
    command["source_read_set"] = value["required_source_read_set"]
    return command, value


def _send(work, command, *, preview=False):
    return work.setup.client.post(
        f"/v1/categories/{work.setup.category}/commands" + ("/preview" if preview else ""),
        headers=work.setup.headers,
        json=command,
    )


def _reading(work, identity):
    response = work.setup.client.get(
        _root(work) + "/external-handoffs/" + str(identity), headers=work.setup.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def prepare_authority(work):
    setup, at = work.setup, now()
    line = (
        f"Synthetic named engineering handoff authority for {setup.human}, "
        f"{work.project_id}, {work.purpose}; {AUTHORIZE}."
    )
    artifact = upstream.register_text(setup, "Synthetic bounded handoff professional basis", line)
    for kind in ("duty", "qualification"):
        payload = {
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "subject_id": str(setup.human),
            "external_id": f"synthetic-handoff-{setup.human}-{kind}",
            "kind": kind,
            "role": "engineering",
            "operations": [AUTHORIZE],
            "purposes": [work.purpose],
            "state": "active",
            "valid_from": (at - timedelta(minutes=1)).isoformat(),
            "valid_until": (at + timedelta(minutes=40)).isoformat(),
            "approval": {
                "system": "Synthetic bounded handoff authority",
                "external_id": str(uuid4()),
                "version": "v1",
                "approved_by": "Controlled fixture issuer",
                "issued_at": (at - timedelta(minutes=1)).isoformat(),
            },
            "sources": [
                {"artifact_id": artifact, "expected_revision": 1, "line": 1, "quote": line}
            ],
            "reason": "Isolated synthetic handoff operation only; no production qualification",
        }
        with upstream.session(work) as s:
            import_professional_fact(
                s, setup.ctx, work.issuer, payload, request_key=str(uuid4()), command_id=uuid4()
            )


def run(work, package, decisions):
    """Called after real E/M decisions and before the policy withdrawal."""
    if os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") != "1":
        raise RuntimeError("Actual external handoff chain requires explicit isolated opt-in")
    setup = work.setup
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    declaration = package["package"]["declaration"]
    scope, config = deepcopy(declaration["release_scope"]), declaration["subject_config"]
    assert scope["regions"] == ["CN", "DE"], "Partial scope needs the actual two-region package"
    with upstream.session(work) as s:
        from pdos_next.domain.release.models import ReleaseDecision

        actual = [s.get(ReleaseDecision, UUID(identity)) for identity in decisions]
        assert len(actual) == 2 and all(
            row is not None and row.package_id == UUID(package["id"]) for row in actual
        )
        by_discipline = {
            row.discipline: {"id": str(row.id), "revision": row.revision} for row in actual
        }
    destination = {
        "system": "synthetic-local-erp",
        "recipient_id": "synthetic-receiver-" + str(work.project_id),
    }
    ledger = {}

    def register(kind, value, title, *, visibility="category"):
        if kind == "receipt":
            value = ReceiptOriginal.model_validate(value).model_dump(mode="json")
        line = (
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if isinstance(value, dict)
            else value
        )
        if visibility == "category":
            identity = upstream.register_text(setup, title, line)
        else:
            response = upstream.post(
                setup,
                cmd(
                    setup,
                    "evidence.artifact.register",
                    {
                        "title": title,
                        "content": line,
                        "source_label": "Synthetic private receipt",
                        "visibility": visibility,
                    },
                ),
            )
            assert response.status_code == 200, response.text
            identity = response.json()["subject_id"]
        source = _source(identity, line)
        ledger[str(identity)] = {
            "kind": kind,
            "source": source,
            "sha256": digest(line),
            "material": deepcopy(value),
        }
        return source

    mapping_source = register(
        "support",
        "Synthetic exact native engineering number/version mapping",
        "Synthetic native mapping original",
    )
    file_source = register(
        "support",
        {
            "project": str(work.project_id),
            "package": {"id": package["id"], "revision": package["revision"]},
            "purpose": work.purpose,
        },
        "Synthetic fixed external manifest file",
    )
    mapping = {
        "ref": {"kind": "engineering_configuration", **config["engineering_configuration"]},
        "external_number": "SYN-ENG-001",
        "external_version": "SYN-V1",
        "sources": [mapping_source],
    }
    manifest = {
        "artifact": {"id": file_source["id"], "revision": 1},
        "logical_name": "controlled-package.json",
        "content_sha256": ledger[file_source["id"]]["sha256"],
        "external_number": "SYN-DOC-001",
        "external_version": "SYN-V1",
        "sources": [file_source],
    }
    contract = {
        "schema_version": "pdos-external-handoff-contract-v1",
        "scope": {
            "tenant_id": str(setup.tenant),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
        },
        "category_id": str(setup.category),
        "subject_config": config,
        "purpose": work.purpose,
        "destination": destination,
        "release_scope": scope,
        "required_mapping_refs": [mapping["ref"]],
        "required_manifest_refs": [manifest["artifact"]],
        "mappings": [mapping],
        "files": [manifest],
    }
    contract_source = register("contract", contract, "Synthetic controlled handoff contract")

    def verify(s, ctx, pid, challenge):
        expected = ledger.get(str(challenge.source.id))
        assert expected is not None and challenge.kind == expected["kind"]
        assert (
            challenge.scope.model_dump(mode="json") == contract["scope"]
            and challenge.category_id == setup.category
        )
        assert challenge.destination.model_dump(mode="json") == destination
        assert challenge.source.model_dump(mode="json") == expected["source"]
        assert challenge.source_metadata["sha256"] == expected["sha256"]
        assert challenge.material.model_dump(mode="json") == expected["material"]
        return challenge.attest(
            {"source_id": str(challenge.source.id), "sha256": expected["sha256"]}
        )

    def current(s, ctx, pid, issuer, watermark):
        expected = ledger.get(watermark.get("source_id"))
        return expected is not None and expected["sha256"] == watermark.get("sha256")

    configure_local_synthetic(
        setup.engine,
        key="synthetic-handoff-" + str(work.project_id),
        version="v1",
        tenant_id=setup.tenant,
        product_id=setup.product,
        project_id=work.project_id,
        destination=destination,
        verify=verify,
        current=current,
        enabled=True,
        test_marker_verified=True,
    )
    payload = {
        "project_id": str(work.project_id),
        "package": {"id": package["id"], "revision": package["revision"]},
        "engineering_decision": by_discipline["engineering"],
        "manufacturing_decision": by_discipline["manufacturing"],
        "subject_config": config,
        "release_scope": scope,
        "purpose": work.purpose,
        "visibility": "category",
        "destination": destination,
        "external_id": "synthetic-handoff-" + str(uuid4()),
        "mappings": [mapping],
        "manifest": [manifest],
        "sources": [contract_source],
        "reason": "Named authorization for exact internal synthetic packet; no real network action",
    }
    before = upstream.snapshots(work, MODELS)
    command, prepared = _inputs(work, AUTHORIZE, payload)
    assert prepared["candidate"]["state"] == "READY"
    assert upstream.snapshots(work, MODELS) == before
    preview = _send(work, command, preview=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["write_tier"] == "T2" and preview.json()["expires_at"] is None
    command = preview.json()["command"]
    response = _send(work, command)
    assert response.status_code == 200, response.text
    original_authorization_receipt = response.json()
    handoff = _reading(work, original_authorization_receipt["subject_id"])
    assert handoff["reading"]["status"] == "authorized" and handoff["as_of"]["receipt_count"] == 0
    assert (
        handoff["reading"]["sent"]["state"]
        == handoff["reading"]["accepted"]["state"]
        == handoff["reading"]["effective"]["state"]
        == "not_recorded"
    )
    assert handoff["network_send"] is False
    with upstream.session(work) as s:
        row = s.get(Authorization, UUID(handoff["id"]))
        intent = s.get(Intent, UUID(handoff["intent"]["id"]))
        proof = s.get(Confirmation, row.shared_proof_id)
        assert (
            proof is not None
            and proof.consumed
            and proof.expires_at is None
            and row.proof_expires_at is None
        )
        assert row.receipt_id == intent.receipt_id == UUID(original_authorization_receipt["id"])
        assert intent.network_send is row.network_send is False
        assert intent.authorization_sha256 == row.body_sha256
    authorization_body, intent_body = (
        deepcopy(handoff["authorization"]),
        deepcopy(handoff["intent"]),
    )
    baseline = {
        "schema_version": "pdos-external-receipt-v1",
        "handoff": {"id": handoff["id"], "revision": handoff["revision"]},
        "intent": {"id": handoff["intent"]["id"], "revision": handoff["intent"]["revision"]},
        "destination": destination,
        "external_id": payload["external_id"],
        "manifest_sha256": handoff["authorization"]["manifest_sha256"],
        "release_scope": scope,
        "reconciles": None,
    }
    stored, first_command, first_receipt = [], None, None

    def record(
        stage,
        outcome="succeeded",
        *,
        release_scope=None,
        reconciles=None,
        manifest_sha256=None,
        expected=200,
        source_visibility="category",
    ):
        nonlocal first_command, first_receipt
        original = {
            **deepcopy(baseline),
            "stage": stage,
            "outcome": outcome,
            "external_receipt_id": "synthetic-receipt-" + str(uuid4()),
            "occurred_at": now().isoformat(),
            "release_scope": release_scope or scope,
            "reconciles": reconciles,
        }
        if manifest_sha256 is not None:
            original["manifest_sha256"] = manifest_sha256
        source = register(
            "receipt",
            original,
            "Synthetic controlled external response",
            visibility=source_visibility,
        )
        request = {
            "handoff": baseline["handoff"],
            "intent": baseline["intent"],
            "source": source,
            "reason": "Record exact original response; no send or guessed external state",
        }
        prior = upstream.snapshots(work, MODELS)
        prepared_command, candidate = _inputs(work, RECEIPT_RECORD, request, expected=expected)
        if expected != 200:
            assert upstream.snapshots(work, MODELS) == prior
            return None, None
        assert candidate["candidate"]["state"] == "READY", candidate["candidate"].get("unknown")
        result = _send(work, prepared_command)
        assert result.status_code == 200, result.text
        receipt = result.json()
        stored.append(receipt["subject_id"])
        if first_command is None:
            first_command, first_receipt = prepared_command, receipt
        view = _reading(work, handoff["id"])
        assert (
            view["as_of"]["receipt_count"] == len(stored)
            and view["as_of"]["epoch"] == len(stored) + 1
        )
        assert view["authorization"] == authorization_body and view["intent"] == intent_body
        return {"id": receipt["subject_id"], "revision": receipt["subject_revision"]}, view

    # The actual owner may read this person's private original, but a shared
    # authorization must reject it during inputs, before any handoff write.
    record("accepted", source_visibility="private", expected=403)
    unknown, viewed = record("sent", "unknown")
    assert viewed["reading"]["delivery_unknown"] and viewed["reading"]["status"] == "authorized"
    record("sent", expected=409)
    _, viewed = record("sent", reconciles=unknown)
    assert (
        not viewed["reading"]["delivery_unknown"]
        and viewed["reading"]["sent"]["state"] == "succeeded"
    )
    partial = {**deepcopy(scope), "regions": ["CN"]}
    partial_ref, viewed = record("accepted", release_scope=partial)
    assert (
        viewed["reading"]["accepted"]["state"] == "partial"
        and viewed["reading"]["status"] == "sent"
    )
    _, viewed = record("accepted")
    assert (
        viewed["reading"]["accepted"]["state"] == "succeeded"
        and viewed["reading"]["status"] == "acknowledged"
    )
    _, viewed = record("effective")
    assert (
        viewed["reading"]["effective"]["state"] == "succeeded"
        and viewed["reading"]["status"] == "reconciled"
    )
    mismatch, viewed = record("effective", manifest_sha256="f" * 64)
    assert viewed["reading"]["conflict"] and viewed["reading"]["effective"]["state"] == "conflict"
    assert "MANIFEST_MISMATCH" in viewed["reading"]["effective"]["mismatches"]
    history = setup.client.get(
        _root(work) + "/external-handoffs/" + handoff["id"] + "/receipts", headers=setup.headers
    )
    assert history.status_code == 200, history.text
    items = history.json()["items"]
    assert len(items) == len(stored) and {row["id"] for row in items} == set(stored)
    assert next(row for row in items if row["id"] == mismatch["id"])["mismatches"] == [
        "MANIFEST_MISMATCH"
    ]
    assert next(row for row in items if row["id"] == partial_ref["id"])["original"][
        "release_scope"
    ]["regions"] == ["CN"]
    before = upstream.snapshots(work, MODELS)
    replay = _send(work, first_command)
    assert replay.status_code == 200 and replay.json() == first_receipt
    replay_authorization = _send(work, command)
    assert (
        replay_authorization.status_code == 200
        and replay_authorization.json() == original_authorization_receipt
    )
    assert upstream.snapshots(work, MODELS) == before
    if os.environ.get("PDOS_EXTERNAL_HANDOFF_BROWSER_SEED") == "1":
        from .browser_seed import run_browser_seed

        run_browser_seed(work, handoff["id"])
    return {
        "handoff_id": handoff["id"],
        "intent_id": handoff["intent"]["id"],
        "receipts": stored,
        "partial": partial_ref,
        "mismatch": mismatch,
        "network_send": False,
    }
