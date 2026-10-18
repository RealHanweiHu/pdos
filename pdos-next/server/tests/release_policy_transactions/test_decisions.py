"""Real policy publication, fixed package and separate common T2 decisions.

The synthetic policy covers only the explicit project documentation purpose.
It grants no physical resource qualification, external receipt or production use.
"""

import json
import os
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from manufacturing_preparation import publication_pg_helpers as upstream
from sqlalchemy import select
from test_project_first_plan import cmd, post

from pdos_next.domain.configurations.models import EngineeringConfiguration
from pdos_next.domain.release import service
from pdos_next.domain.release.models import ReleaseDecision, ReleasePackage, ReleasePackageCurrent
from pdos_next.domain.release.policy_models import ReleasePolicyCurrent, ReleasePolicyFact
from pdos_next.domain.release.policy_owner import ActualReleasePolicyOwner
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.professional_import import import_professional_fact

MODELS = (
    ReleasePolicyFact,
    ReleasePolicyCurrent,
    ReleasePackage,
    ReleasePackageCurrent,
    ReleaseDecision,
    Receipt,
    Audit,
    Outbox,
    RequestKey,
    Confirmation,
)


def source(identity, text):
    return {
        "kind": "artifact",
        "id": str(identity),
        "revision": 1,
        "position": "line:1;quote_sha256:" + sha256(text.encode()).hexdigest(),
    }


def root(work):
    return f"/v1/categories/{work.setup.category}/products/{work.setup.product}"


def inputs(work, operation, payload, actor=None):
    response = work.setup.client.post(
        root(work) + "/release/inputs",
        headers=upstream.headers(work, actor),
        json=cmd(work.setup, operation, deepcopy(payload)),
    )
    assert response.status_code == 200, response.text
    value = response.json()
    command = cmd(work.setup, operation, value["payload"])
    command["source_read_set"] = value["required_source_read_set"]
    return command, value


def send(work, command, *, actor=None, preview=False):
    return work.setup.client.post(
        f"/v1/categories/{work.setup.category}/commands" + ("/preview" if preview else ""),
        headers=upstream.headers(work, actor),
        json=command,
    )


def fixed(work, identity):
    r = work.setup.client.get(
        root(work) + "/release-packages/" + str(identity), headers=work.setup.headers
    )
    assert r.status_code == 200, r.text
    return r.json()


def authorize(work, actor, role, operations):
    at = now()
    line = (
        f"Synthetic {actor} {role} duty and qualification for {work.project_id}: "
        f"{','.join(operations)}; {work.purpose}."
    )
    artifact = upstream.register_text(work.setup, "Synthetic release professional basis", line)
    for kind in ("duty", "qualification"):
        payload = {
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            "subject_id": str(actor),
            "external_id": f"synthetic-release-{actor}-{role}-{kind}",
            "kind": kind,
            "role": role,
            "operations": operations,
            "purposes": [work.purpose],
            "state": "active",
            "valid_from": (at - timedelta(minutes=1)).isoformat(),
            "valid_until": (at + timedelta(minutes=45)).isoformat(),
            "approval": {
                "system": "Synthetic release authority",
                "external_id": str(uuid4()),
                "version": "local-v1",
                "approved_by": "Controlled test issuer",
                "issued_at": (at - timedelta(minutes=1)).isoformat(),
            },
            "sources": [
                {"artifact_id": artifact, "expected_revision": 1, "line": 1, "quote": line}
            ],
            "reason": "Isolated synthetic professional fact; no production qualification",
        }
        with upstream.session(work) as s:
            import_professional_fact(
                s,
                work.setup.ctx,
                work.issuer,
                payload,
                request_key=str(uuid4()),
                command_id=uuid4(),
            )


def test_controlled_policy_and_independent_named_decisions(publication_case, monkeypatch):
    work, setup = publication_case, publication_case.setup
    upstream.import_authority(work, setup.human)
    upstream.save_drafts(work)
    publication_cmd, _ = upstream.prepare_publication(work, upstream.publication_payload(work))
    published = post(setup, publication_cmd)
    assert published.status_code == 200, published.text
    publication = upstream.publication(work, published.json())
    with upstream.session(work) as s:
        engineering = s.get(
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
    scope = {
        "quantity": None,
        "unit": None,
        "lots": [],
        "site": "SYN-INTERNAL-LAB",
        "lines": [],
        "regions": ["CN", "DE"] if os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") == "1" else ["CN"],
    }
    document = {"kind": "artifact", "id": work.document_source, "revision": 1}
    publication_ref = {
        "kind": "manufacturing_publication",
        "id": publication["id"],
        "revision": publication["revision"],
    }
    package_payload = {
        "project_id": str(work.project_id),
        "subject_config": configuration,
        "release_scope": scope,
        "purpose": work.purpose,
        "manufacturing_publication": {"id": publication["id"], "revision": publication["revision"]},
        "documents": [document],
        "sources": [source(work.document_source, upstream.LINES[0])],
        "visibility": "category",
        "reason": "Fixed internal documentation only; no physical or production permission",
    }
    first_cmd, missing = inputs(work, "release.package.assemble", package_payload)
    assert missing["assessments"]["engineering"]["state"] == "UNKNOWN"
    first_response = send(work, first_cmd)
    assert first_response.status_code == 200, first_response.text
    first = fixed(work, first_response.json()["subject_id"])
    authorize(
        work, setup.human, "engineering", ["release.policy.import", "release.engineering.approve"]
    )
    authorize(work, setup.peer, "manufacturing", ["release.manufacturing.approve"])
    policy = {
        "schema_version": "pdos-release-policy-v1",
        "scope": {
            "tenant_id": str(setup.tenant),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
        },
        "category_id": str(setup.category),
        "subject_config": configuration,
        "release_scope": scope,
        "purpose": work.purpose,
        "policy_version": "synthetic-documentation-v1",
        "publisher_id": str(setup.human),
        "owner_id": str(setup.human),
        "visibility": "category",
        "nature": "synthetic",
        "status": "active",
        "valid_from": None,
        "valid_until": None,
        "rules": [
            {
                "id": key,
                "version": "1",
                "discipline": discipline,
                "scope": scope,
                "applicable_if": {"op": "always"},
                "predicate": {"op": op, "ref": ref},
                "required_evidence": [ref],
                "freshness": "current",
                "severity": "required",
                "responsible_role": discipline,
                "waivable": False,
                "allowed_purpose": [work.purpose],
            }
            for key, discipline, op, ref in [
                ("engineering.fixed_document", "engineering", "document_present", document),
                (
                    "manufacturing.fixed_publication",
                    "manufacturing",
                    "manufacturing_publication_present",
                    publication_ref,
                ),
            ]
        ],
    }
    if os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") == "1":
        from external_handoff_transactions.harness import prepare_authority

        # Establish this operation's authority before the initial policy fact
        # fixes its professional-source set; later replay must use that same set.
        prepare_authority(work)
    if os.environ.get("PDOS_RELEASE_EXCEPTION_LINK") == "1":
        from release_exception_transactions.harness import (
            prepare_authority as prepare_exception_authority,
        )

        prepare_exception_authority(work)
    owner = ActualReleasePolicyOwner(setup.engine)
    policy_line = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    policy_artifact = upstream.register_text(
        setup, "Synthetic controlled release policy", policy_line
    )
    policy_input = {
        "project_id": str(work.project_id),
        "source": source(policy_artifact, policy_line),
        "expected_previous": None,
        "reason": "Publish exact synthetic documentation policy",
    }
    policy_key, policy_command_id = str(uuid4()), uuid4()
    with upstream.session(work) as s:
        original_receipt = owner.import_policy(
            s,
            setup.ctx,
            setup.product,
            policy_input,
            command_id=policy_command_id,
            request_key=policy_key,
        )
    before_replay = upstream.snapshots(work, MODELS)
    with upstream.session(work) as s:
        replay = owner.import_policy(
            s,
            setup.ctx,
            setup.product,
            policy_input,
            command_id=policy_command_id,
            request_key=policy_key,
        )
    assert replay == original_receipt
    assert upstream.snapshots(work, MODELS) == before_replay
    package_payload["previous"] = {"id": first["id"], "revision": first["revision"]}
    package_payload["reason"] = (
        "Explicit new package fixes controlled policy without rewriting the first version"
    )
    command, ready = inputs(work, "release.package.assemble", package_payload)
    assert {v["state"] for v in ready["assessments"].values()} == {"READY"}
    for discipline, key in (
        ("engineering", "engineering.fixed_document"),
        ("manufacturing", "manufacturing.fixed_publication"),
    ):
        checks = ready["assessments"][discipline]["checks"]
        assert len(checks) == 1 and checks[0]["key"] == key
        assert checks[0]["state"] == "satisfied" and checks[0]["applicable"] is True
    result = send(work, command)
    assert result.status_code == 200, result.text
    second = fixed(work, result.json()["subject_id"])
    assert fixed(work, first["id"])["package"] == first["package"]
    decision_payload = {
        "package": {"id": second["id"], "revision": second["revision"]},
        "release_scope": scope,
        "purpose": work.purpose,
        "expiry": None,
        "sources": [source(policy_artifact, policy_line)],
        "reason": "Named decision solely for this explicit documentation scope",
    }
    if os.environ.get("PDOS_RELEASE_POLICY_BROWSER_SEED") == "1":
        from release_policy_browser_seed.harness import run_browser_seed

        decisions = run_browser_seed(
            work,
            package=second,
            decision_payload=decision_payload,
            policy_ref={
                "id": original_receipt["subject_id"],
                "revision": original_receipt["subject_revision"],
                "source": policy_input["source"],
            },
        )
    else:
        decisions = []
        for discipline, actor in [("engineering", setup.human), ("manufacturing", setup.peer)]:
            operation = f"release.{discipline}.approve"
            command, prepared = inputs(work, operation, decision_payload, actor)
            assert prepared["candidate"]["assessment"]["state"] == "READY"
            preview = send(work, command, actor=actor, preview=True)
            assert preview.status_code == 200, preview.text
            preview_value = preview.json()
            assert preview_value["write_tier"] == "T2" and preview_value["expires_at"] is None
            command = preview_value["command"]
            if discipline == "manufacturing":
                before = upstream.snapshots(work, MODELS)
                real_finalizer = service.finalize_receipt

                def fail_tail(*args, **kwargs):
                    raise DomainError(
                        "INTEGRATION_REQUIRED", "One deliberate terminal rollback", 503
                    )

                monkeypatch.setattr(service, "finalize_receipt", fail_tail)
                failed = send(work, command, actor=actor)
                assert failed.status_code == 503, failed.text
                assert upstream.snapshots(work, MODELS) == before
                monkeypatch.setattr(service, "finalize_receipt", real_finalizer)
            response = send(work, command, actor=actor)
            assert response.status_code == 200, response.text
            receipt = response.json()
            decisions.append(receipt["subject_id"])
            replay = send(work, deepcopy(command), actor=actor)
            assert replay.status_code == 200 and replay.json() == receipt
            saved = fixed(work, second["id"])
            assert len(saved["decisions"]) == len(decisions)
            assert {v["discipline"] for v in saved["decisions"]} == (
                {"engineering"} if discipline == "engineering" else {"engineering", "manufacturing"}
            )
    if os.environ.get("PDOS_EXTERNAL_HANDOFF_LINK") == "1":
        from external_handoff_transactions.harness import run as run_external_handoff

        run_external_handoff(work, second, decisions)

    with upstream.session(work) as s:
        actual = list(
            s.scalars(
                select(ReleaseDecision).where(ReleaseDecision.package_id == UUID(second["id"]))
            )
        )
        assert {v.actor_id for v in actual} == {setup.human, setup.peer}
        assert all(
            v.body["external_received"] is False
            and v.body["external_effective"] is False
            and v.body["customer_acceptance"] is None
            for v in actual
        )
        pointer = s.scalar(
            select(ReleasePolicyCurrent).where(ReleasePolicyCurrent.project_id == work.project_id)
        )
        prior = {"id": str(pointer.fact_id), "revision": pointer.revision}
    policy["status"], policy["policy_version"] = "withdrawn", "synthetic-documentation-v2"
    withdrawn_line = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    artifact = upstream.register_text(setup, "Synthetic explicit policy withdrawal", withdrawn_line)
    withdrawal = {
        **policy_input,
        "source": source(artifact, withdrawn_line),
        "expected_previous": prior,
        "reason": "Append withdrawal while retaining exact original policy and decisions",
    }
    with upstream.session(work) as s:
        owner.import_policy(
            s, setup.ctx, setup.product, withdrawal, command_id=uuid4(), request_key=str(uuid4())
        )
    retained = fixed(work, second["id"])
    assert retained["package"] == second["package"] and retained["applicability"] == "needs_recheck"
    assert len(retained["decisions"]) == 2
    before = upstream.snapshots(work, MODELS)
    with upstream.session(work) as s:
        old_replay = owner.import_policy(
            s,
            setup.ctx,
            setup.product,
            policy_input,
            command_id=policy_command_id,
            request_key=policy_key,
        )
    assert old_replay == original_receipt and upstream.snapshots(work, MODELS) == before
    if os.environ.get("PDOS_RELEASE_EXCEPTION_LINK") == "1":
        from release_exception_transactions.harness import run as run_exception_chain

        run_exception_chain(work, second, package_payload, policy, prior, monkeypatch)
