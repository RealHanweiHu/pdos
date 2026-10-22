"""Actual release reads retain fixed packages and named decision history.

Root alone runs this case against explicitly verified isolated pdos_test URLs.
Existing domain commands and the controlled synthetic publication/policy issuer
create the facts. They confer no real qualification, external receipt or use.
"""

import json
import os
from copy import copy, deepcopy
from pathlib import Path
from uuid import UUID, uuid4

from g0_fixture import create_g0_project
from manufacturing_preparation import publication_pg_helpers as upstream
from manufacturing_preparation.publication_pg_helpers import publication_case as publication_case
from release_policy_transactions import test_decisions as flow
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_project_first_plan import post

from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.domain.release.policy_owner import ActualReleasePolicyOwner
from pdos_next.models import (
    Artifact,
    Consumption,
    Grant,
    ObjectAudience,
    OriginalSecurity,
    Product,
    UploadedOriginal,
)


def _counts(work):
    models = (
        Product,
        Project,
        ProjectProductLink,
        DefinitionRevision,
        BomRevision,
        BomLine,
        PartIdentity,
        EngineeringConfiguration,
        ProcessRevision,
        *upstream.PUBLICATION_MODELS,
        *upstream.DRAFT_MODELS,
        ProfessionalFact,
        *flow.MODELS,
        Artifact,
        UploadedOriginal,
        OriginalSecurity,
        Consumption,
        Grant,
        ObjectAudience,
    )
    assert len({model.__tablename__ for model in models}) == len(models)
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }


def _read(work, *, package_id=None, project_id=None, actor=None):
    path = flow.root(work) + "/release-packages"
    if package_id is None:
        params = {"project_id": str(project_id or work.project_id)}
    else:
        path += "/" + str(package_id)
        params = {}
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


def _phase(work, phase, readers):
    before = _counts(work)
    reads = {name: reader() for name, reader in readers.items()}
    after = _counts(work)
    assert before == after
    return {
        "phase": phase,
        "reads": reads,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
    }


def _policy(work, configuration, release_scope, document, publication_ref):
    return {
        "schema_version": "pdos-release-policy-v1",
        "scope": {
            "tenant_id": str(work.setup.tenant),
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
        },
        "category_id": str(work.setup.category),
        "subject_config": configuration,
        "release_scope": release_scope,
        "purpose": work.purpose,
        "policy_version": "synthetic-ui-fixed-documents-v1",
        "publisher_id": str(work.setup.human),
        "owner_id": str(work.setup.human),
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
                "scope": release_scope,
                "applicable_if": {"op": "always"},
                "predicate": {"op": operation, "ref": ref},
                "required_evidence": [ref],
                "freshness": "current",
                "severity": "required",
                "responsible_role": discipline,
                "waivable": False,
                "allowed_purpose": [work.purpose],
            }
            for key, discipline, operation, ref in (
                ("engineering.fixed_document", "engineering", "document_present", document),
                (
                    "manufacturing.fixed_publication",
                    "manufacturing",
                    "manufacturing_publication_present",
                    publication_ref,
                ),
            )
        ],
    }


def _import_policy(work, owner, policy, *, previous=None):
    line = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    artifact = upstream.register_text(work.setup, "Synthetic UI release policy original", line)
    source = flow.source(artifact, line)
    with upstream.session(work) as session:
        receipt = owner.import_policy(
            session,
            work.setup.ctx,
            work.setup.product,
            {
                "project_id": str(work.project_id),
                "source": source,
                "expected_previous": previous,
                "reason": "Retain exact synthetic documentation policy state for read-only UI QA",
            },
            command_id=uuid4(),
            request_key=str(uuid4()),
        )
    return receipt, source


def _export(work, scope, phases, receipts):
    destination = os.environ.get("PDOS_UI_RELEASE_PACKAGES_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual release-package DTO export requires an absolute path"
    bundle = {
        "version": "project-release-packages-projection-qa/v1",
        "fixture_nature": "actual commands/HTTP with isolated synthetic authority and policy",
        "scope": scope,
        "phases": phases,
        "command_receipts": receipts,
        "limitations": [
            "All read bodies are original unmodified actual GET JSON responses.",
            "History is not_checked; only an explicit detail checks package applicability.",
            "Current identifies a series version; old decisions do not transfer to a new package.",
            "Saved checks, prepared_at, limits and signers remain their original fixed assessment.",
            "Null expiry introduces no automatic deadline or unrestricted use.",
            "Policy withdrawal marks applicability for recheck while retaining old decisions.",
            "Category-scoped peer reading is authorized, not an ACL bypass or a new approval.",
            "Synthetic readiness/authority is not production qualification or external acceptance.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_release_reads_keep_named_decisions_on_old_package_after_renewal_and_withdrawal(
    publication_case,
):
    work, phases, receipts = publication_case, [], {}
    setup = work.setup
    upstream.import_authority(work, setup.human)
    upstream.save_drafts(work)
    publication_command, _ = upstream.prepare_publication(work, upstream.publication_payload(work))
    response = post(setup, publication_command)
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
        "regions": ["CN"],
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
    policy = _policy(work, configuration, release_scope, document, publication_ref)
    owner = ActualReleasePolicyOwner(setup.engine)
    receipts["policy_active"], policy_source = _import_policy(work, owner, policy)
    limit_text = "Synthetic fixed project documentation only; no production or external use."
    limit_artifact = upstream.register_text(setup, "Synthetic explicit release limit", limit_text)
    limit = {"text": limit_text, "sources": [flow.source(limit_artifact, limit_text)]}
    package_payload = {
        "project_id": str(work.project_id),
        "subject_config": configuration,
        "release_scope": release_scope,
        "purpose": work.purpose,
        "manufacturing_publication": {"id": publication["id"], "revision": publication["revision"]},
        "documents": [document],
        "limits": [limit],
        "sources": [flow.source(work.document_source, upstream.LINES[0]), *limit["sources"]],
        "visibility": "category",
        "reason": "Retain fixed synthetic documentation package for independent named decisions",
    }

    def assemble(body):
        command, material = flow.inputs(work, "release.package.assemble", body)
        assert {value["state"] for value in material["assessments"].values()} == {"READY"}
        result = flow.send(work, command)
        assert result.status_code == 200, result.text
        return result.json()

    receipts["package_v1"] = assemble(package_payload)
    original_ref = {
        "id": receipts["package_v1"]["subject_id"],
        "revision": receipts["package_v1"]["subject_revision"],
    }
    for discipline, actor in (("engineering", setup.human), ("manufacturing", setup.peer)):
        command, material = flow.inputs(
            work,
            f"release.{discipline}.approve",
            {
                "package": original_ref,
                "release_scope": release_scope,
                "purpose": work.purpose,
                "expiry": None,
                "sources": [policy_source, *limit["sources"]],
                "reason": "Named synthetic acceptance of the exact fixed documentation only",
            },
            actor,
        )
        assert material["candidate"]["assessment"]["state"] == "READY"
        preview = flow.send(work, command, actor=actor, preview=True)
        assert preview.status_code == 200, preview.text
        assert preview.json()["write_tier"] == "T2" and preview.json()["expires_at"] is None
        result = flow.send(work, preview.json()["command"], actor=actor)
        assert result.status_code == 200, result.text
        receipts[discipline + "_decision"] = result.json()

    first = _phase(
        work,
        "original_package_with_two_named_decisions",
        {
            "project_packages": lambda: _read(work),
            "selected_original": lambda: _read(work, package_id=original_ref["id"]),
        },
    )
    phases.append(first)
    original = _ok(first["reads"]["selected_original"])
    assert original["applicability"] == "current"
    assert original["current"]["version"] == original_ref and original["current"]["epoch"] == 1
    assert {row["discipline"] for row in original["decisions"]} == {"engineering", "manufacturing"}
    original_decisions = {row["discipline"]: row for row in original["decisions"]}
    for discipline, actor in (("engineering", setup.human), ("manufacturing", setup.peer)):
        row = original_decisions[discipline]
        assert row["receipt_id"] == receipts[discipline + "_decision"]["id"]
        assert row["package"] == original_ref and row["applicability"] == "current"
        decision = row["decision"]
        assert decision["signers"] == [str(actor)]
        assert decision["expiry"] is None and decision["prepared_at"]
        assert decision["limits"] == [limit]
        assert decision["external_received"] is False and decision["external_effective"] is False
        assert decision["customer_acceptance"] is None
        assert decision["assessment"]["discipline"] == discipline
        [check] = decision["assessment"]["checks"]
        assert check["key"] == discipline + (
            ".fixed_document" if discipline == "engineering" else ".fixed_publication"
        )
        assert check["state"] == "satisfied" and check["applicable"] is True

    renewal_payload = {
        **deepcopy(package_payload),
        "previous": original_ref,
        "reason": "Explicit synthetic package renewal without inheriting old named decisions",
    }
    receipts["package_v2"] = assemble(renewal_payload)
    current_ref = {
        "id": receipts["package_v2"]["subject_id"],
        "revision": receipts["package_v2"]["subject_revision"],
    }
    assert current_ref["revision"] == 2 and current_ref["id"] != original_ref["id"]
    other_setup = copy(setup)
    other_project = create_g0_project(other_setup, name="Synthetic other-model release read scope")
    renewed = _phase(
        work,
        "new_package_current_old_decisions_retained",
        {
            "project_packages": lambda: _read(work),
            "selected_original": lambda: _read(work, package_id=original_ref["id"]),
            "selected_current": lambda: _read(work, package_id=current_ref["id"]),
            "peer_project_packages": lambda: _read(work, actor=setup.peer),
            "peer_selected_original": lambda: _read(
                work, package_id=original_ref["id"], actor=setup.peer
            ),
            "other_model_project": lambda: _read(work, project_id=other_project.project_id),
            "foreign_tenant_project": lambda: _read(work, actor=setup.other_human),
            "foreign_tenant_original": lambda: _read(
                work, package_id=original_ref["id"], actor=setup.other_human
            ),
        },
    )
    phases.append(renewed)
    old_after_renewal = _ok(renewed["reads"]["selected_original"])
    current = _ok(renewed["reads"]["selected_current"])
    assert old_after_renewal["package"] == original["package"]
    assert old_after_renewal["assessments"] == original["assessments"]
    assert old_after_renewal["decisions"] == original["decisions"]
    assert old_after_renewal["current"]["version"] == current_ref
    assert current["current"] == old_after_renewal["current"]
    assert current["current"]["epoch"] == 2
    assert current["decisions"] == []
    assert current["package"]["declaration"]["previous"] == original_ref
    assert _ok(renewed["reads"]["peer_selected_original"]) == old_after_renewal
    assert _ok(renewed["reads"]["peer_project_packages"]) == _ok(
        renewed["reads"]["project_packages"]
    )
    for name in ("other_model_project", "foreign_tenant_project", "foreign_tenant_original"):
        refused = renewed["reads"][name]
        assert refused["status_code"] == 403, refused
        assert refused["body"]["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in refused["body"] and "package" not in refused["body"]

    withdrawn = {
        **deepcopy(policy),
        "status": "withdrawn",
        "policy_version": "synthetic-ui-fixed-documents-v2-withdrawn",
    }
    receipts["policy_withdrawal"], _ = _import_policy(
        work,
        owner,
        withdrawn,
        previous={
            "id": receipts["policy_active"]["subject_id"],
            "revision": receipts["policy_active"]["subject_revision"],
        },
    )
    stale = _phase(
        work,
        "withdrawn_policy_fixed_decisions_need_recheck",
        {
            "project_packages": lambda: _read(work),
            "selected_original": lambda: _read(work, package_id=original_ref["id"]),
            "selected_current": lambda: _read(work, package_id=current_ref["id"]),
        },
    )
    phases.append(stale)
    retained = _ok(stale["reads"]["selected_original"])
    assert retained["applicability"] == "needs_recheck"
    assert retained["package"] == original["package"]
    assert retained["assessments"] == original["assessments"]
    assert retained["receipt_id"] == original["receipt_id"]
    assert retained["current"]["version"] == current_ref
    assert _ok(stale["reads"]["selected_current"])["applicability"] == "needs_recheck"
    assert len(retained["decisions"]) == 2
    for row in retained["decisions"]:
        before = original_decisions[row["discipline"]]
        assert row["applicability"] == "needs_recheck"
        assert {key: value for key, value in row.items() if key != "applicability"} == {
            key: value for key, value in before.items() if key != "applicability"
        }
    for phase in phases:
        page = _ok(phase["reads"]["project_packages"])
        assert page["next_cursor"] is None
        assert all(row["applicability"] == "not_checked" for row in page["items"])
        assert {row["id"] for row in page["items"]} == (
            {original_ref["id"]} if phase is first else {original_ref["id"], current_ref["id"]}
        )

    _export(
        work,
        {
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "principal_id": str(setup.human),
            "manufacturing_signer_id": str(setup.peer),
            "original_package": original_ref,
            "current_package": current_ref,
            "other_model_project_id": str(other_project.project_id),
        },
        phases,
        receipts,
    )
