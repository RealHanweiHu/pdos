"""Actual category/model knowledge-library reads over bounded synthetic commands.

Only root runs the verified isolated PostgreSQL checkpoint. The local parent
fixture uses actual category-visible G0/configuration commands; no stored parent
visibility, business fact, native write tier or professional authority is forged.
"""

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest
from change_execution.approved_configuration_helpers import initial_configuration
from knowledge_pg import test_publication as flow
from knowledge_pg.test_publication import knowledge_work as knowledge_work
from sqlalchemy import update
from sqlalchemy.orm import Session

from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects.models import ProjectProductLink
from pdos_next.models import Artifact, Category, Grant, ObjectAudience, Product
from pdos_next.safety import verify_test_target
from pdos_next.service import digest


@pytest.fixture
def configuration(setup):
    # Shared model candidates require a genuinely category-visible parent.
    # The default private test_builds parent must not be widened by fixture SQL.
    return initial_configuration(setup)


def _snapshot(work):
    models = (
        *flow.KNOWLEDGE_MODELS,
        *flow.GROUP_MODELS,
        Category,
        Product,
        flow.Project,
        ProjectProductLink,
        DefinitionRevision,
        EngineeringConfiguration,
        ProcessRevision,
        BomRevision,
        BomLine,
        PartIdentity,
        Artifact,
        ProfessionalFact,
        Grant,
        ObjectAudience,
    )
    assert len({model.__tablename__ for model in models}) == len(models)
    return {
        table: {"count": len(rows), "sha256": digest(rows)}
        for table, rows in flow.snapshot(work, models).items()
    }


def _read(work, kind, *, actor=None):
    root = f"/v1/categories/{work.setup.category}"
    path = (
        root + "/products"
        if kind == "products"
        else flow.endpoint(work, category_only=kind == "category_experience")
    )
    response = work.setup.client.get(
        path,
        headers={"Authorization": f"Bearer {work.setup.tokens[actor or work.setup.human]}"},
    )
    return {
        "path": path,
        "params": {},
        "status_code": response.status_code,
        "body": response.json(),
    }


def _ok(read):
    assert read["status_code"] == 200, read["body"]
    return read["body"]


def _phase(work, phase):
    before = _snapshot(work)
    reads = {
        prefix + kind: _read(work, kind, actor=actor)
        for prefix, actor in (
            ("", work.setup.human),
            ("peer_", work.setup.peer),
            ("foreign_", work.setup.other_human),
        )
        for kind in ("products", "category_experience", "model_experience")
    }
    after = _snapshot(work)
    assert before == after
    products = _ok(reads["products"])
    assert any(
        row["id"] == str(work.setup.product)
        and row["category_id"] == str(work.setup.category)
        and row["visibility"] == "category"
        for row in products
    )
    assert any(row["id"] == str(work.setup.product) for row in _ok(reads["peer_products"]))
    category, model = _ok(reads["category_experience"]), _ok(reads["model_experience"])
    assert category["rules"] == category["projects"] == category["configurations"] == []
    assert category["as_of"] and model["as_of"]
    for kind in ("products", "category_experience", "model_experience"):
        rejected = reads["foreign_" + kind]
        assert rejected["status_code"] == 403, rejected
        assert rejected["body"]["code"] == "FORBIDDEN_SCOPE"
        assert "candidates" not in rejected["body"] and "rules" not in rejected["body"]
    return {
        "phase": phase,
        "reads": reads,
        "read_only_counts": {
            "before": {key: value["count"] for key, value in before.items()},
            "after": {key: value["count"] for key, value in after.items()},
            "unchanged": True,
        },
        "read_only_snapshot": {"before": before, "after": after, "unchanged": True},
    }


def _export(work, phases, refs, receipts, guard_checks):
    destination = os.environ.get("PDOS_UI_KNOWLEDGE_LIBRARY_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual knowledge-library DTO export requires an absolute path"
    bundle = {
        "version": "knowledge-library-projection-qa/v1",
        "fixture_nature": "actual Command/HTTP facts with controlled synthetic authority",
        "scope": {
            "category_id": str(work.setup.category),
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            "principal_id": str(work.setup.human),
            "peer_principal_id": str(work.setup.peer),
            "foreign_principal_id": str(work.setup.other_human),
            "principal_ids_source": "isolated fixture request contexts; not GET response echoes",
            "category_experience": {"product_id": None, "project_id": None},
            "model_experience": {"product_id": str(work.setup.product), "project_id": None},
            **refs,
        },
        "phases": phases,
        "guard_checks": guard_checks,
        "command_receipts": receipts,
        "limitations": [
            "Every path/status/body is an original actual products/category/model GET response.",
            "Category reading binds product_id=None; model reading is an explicit separate choice.",
            "Model responses may include category candidates; category reading has no rules.",
            "Candidate hypotheses are not published rules; permission flags remain server facts.",
            "Principal UUIDs identify fixture request contexts, not identities echoed by GETs.",
            "The rule is synthetic and explicitly bound to the named target/purpose/conditions.",
            "Candidate revision alone does not invalidate a fixed older rule or rewrite its body.",
            "Current history contains version metadata, not full historical rule bodies.",
            "The precisely owned source status change is a negative fixture, not a user command.",
            "Independent authority and configuration sources stay active after that source change.",
            "No real qualification, external call, model, real-tenant publication or deployment.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_knowledge_library_reads_keep_category_model_acl_history_and_rule_recheck(
    knowledge_work,
):
    work, receipts, phases, refs, guard_checks = knowledge_work, {}, [], {}, {}
    setup = work.setup

    def candidate(name, *, category_only, visibility, previous=None):
        material = flow.candidate_payload(
            work,
            candidate=previous,
            project_id=None if category_only else str(work.project_id),
            title="Synthetic knowledge-library " + name,
            visibility=visibility,
        )
        command = flow.prepare(
            work, flow.command(work, flow.CANDIDATE_OP, material, category_only=category_only)
        )
        response = flow.send(work, command)
        assert response.status_code == 200, response.text
        receipt = response.json()
        _, identity = flow.exact_group(work, command, receipt, category_only=category_only)
        receipts[name] = receipt
        return {"id": identity, "revision": receipt["subject_revision"]}

    refs["category_private"] = candidate(
        "category_private", category_only=True, visibility="private"
    )
    refs["category_shared_v1"] = candidate(
        "category_shared", category_only=True, visibility="category"
    )
    refs["model_private"] = candidate("model_private", category_only=False, visibility="private")
    refs["model_shared"] = candidate("model_shared", category_only=False, visibility="category")
    flow.authorize(work)

    def publish(name, candidate_ref, *, previous=None):
        material = flow.rule_payload(work, candidate_ref, rule=previous)
        command = flow.prepare(work, flow.command(work, flow.RULE_OP, material))
        preview = flow.send(work, command, preview=True)
        assert preview.status_code == 200, preview.text
        assert preview.json()["write_tier"] == "T2"
        signed = preview.json()["command"]
        assert signed["payload"]["approval_token"]
        response = flow.send(work, signed)
        assert response.status_code == 200, response.text
        receipts[name] = response.json()
        body, identity = flow.exact_group(work, signed, response.json(), rule=True)
        return {"id": identity, "revision": response.json()["subject_revision"]}, body

    refs["rule_v1"], rule_v1_body = publish("rule_v1", refs["category_shared_v1"])
    initial = _phase(work, "category_and_model_candidates_with_named_rule_v1")
    phases.append(initial)
    shared_id, rule_id = refs["category_shared_v1"]["id"], refs["rule_v1"]["id"]
    model_v1 = _ok(initial["reads"]["model_experience"])
    [published_v1] = model_v1["rules"]
    assert published_v1["id"] == rule_id and published_v1["candidate"] == refs["category_shared_v1"]
    assert published_v1["nature"] == "synthetic" and published_v1["visibility"] == "category"
    assert published_v1["usability"] == {"state": "current", "reason_codes": []}

    refs["category_shared_v2"] = candidate(
        "category_shared_revision",
        category_only=True,
        visibility="category",
        previous=refs["category_shared_v1"],
    )
    # The prior publication remains a true fixed v1 before explicit rule renewal.
    with flow.scoped(work) as session:
        old = session.get(flow.DesignRuleVersion, UUID(receipts["rule_v1"]["subject_id"]))
        assert old.body == rule_v1_body and old.candidate_revision == 1
    before_candidate_read = _snapshot(work)
    candidate_read = _read(work, "model_experience")
    after_candidate_read = _snapshot(work)
    assert before_candidate_read == after_candidate_read
    [old_publication] = _ok(candidate_read)["rules"]
    assert old_publication["revision"] == 1
    assert old_publication["candidate"] == refs["category_shared_v1"]
    assert old_publication["usability"] == {"state": "current", "reason_codes": []}
    guard_checks["candidate_revision_read"] = {
        **candidate_read,
        "read_only_counts": {
            "before": {key: value["count"] for key, value in before_candidate_read.items()},
            "after": {key: value["count"] for key, value in after_candidate_read.items()},
            "unchanged": True,
        },
        "read_only_snapshot": {
            "before": before_candidate_read,
            "after": after_candidate_read,
            "unchanged": True,
        },
    }
    refs["rule_v2"], rule_v2_body = publish(
        "rule_v2", refs["category_shared_v2"], previous=refs["rule_v1"]
    )
    renewed = _phase(work, "candidate_and_rule_current_versions_advanced")
    phases.append(renewed)
    [published_v2] = _ok(renewed["reads"]["model_experience"])["rules"]
    assert published_v2["id"] == rule_id and published_v2["revision"] == 2
    assert published_v2["candidate"] == refs["category_shared_v2"]
    assert published_v2["usability"] == {"state": "current", "reason_codes": []}
    assert [row["id"] for row in published_v2["history"]] == [
        receipts["rule_v1"]["subject_id"],
        receipts["rule_v2"]["subject_id"],
    ]

    for phase, candidate_revision in ((initial, 1), (renewed, 2)):
        cat, model = (
            _ok(phase["reads"][key]) for key in ("category_experience", "model_experience")
        )
        peer_cat, peer_model = (
            _ok(phase["reads"][key])
            for key in ("peer_category_experience", "peer_model_experience")
        )
        assert {row["id"] for row in cat["candidates"]} == {
            refs["category_private"]["id"],
            shared_id,
        }
        assert {row["id"] for row in model["candidates"]} == {
            refs["category_private"]["id"],
            shared_id,
            refs["model_private"]["id"],
            refs["model_shared"]["id"],
        }
        [cat_shared] = [row for row in cat["candidates"] if row["id"] == shared_id]
        assert cat_shared["revision"] == candidate_revision and cat_shared["project_id"] is None
        assert cat_shared["can_revise"] is True
        assert (
            next(row for row in model["candidates"] if row["id"] == shared_id)["can_revise"]
            is False
        )
        assert {row["id"] for row in peer_cat["candidates"]} == {shared_id}
        assert {row["id"] for row in peer_model["candidates"]} == {
            shared_id,
            refs["model_shared"]["id"],
        }
        [peer_rule] = peer_model["rules"]
        assert peer_rule["id"] == rule_id and peer_rule["can_revise"] is False
        # Shared rule content does not expose its publisher's private authority
        # Artifact/Fact/Current. Recheck keeps that exact reader-scoped gap.
        assert peer_rule["usability"] == {
            "state": "needs_recheck",
            "reason_codes": ["AUTHORITY_SNAPSHOT_INVALID"],
        }
        assert peer_rule["nature"] == "synthetic"

    # The native standalone Artifact has no user withdrawal endpoint. Reuse only
    # the precise authorized negative source fixture; leave other sources intact.
    verify_test_target(setup.admin)
    with Session(setup.admin) as session, session.begin():
        changed = session.execute(
            update(Artifact)
            .where(
                Artifact.tenant_id == setup.tenant,
                Artifact.category_id == setup.category,
                Artifact.product_id.is_(None),
                Artifact.id == UUID(work.source["id"]),
                Artifact.owner_id == setup.human,
                Artifact.status == "active",
            )
            .values(status="withdrawn")
        )
        assert changed.rowcount == 1
    stale = _phase(work, "negative_category_source_withdrawn_rule_requires_recheck")
    phases.append(stale)
    [retained] = _ok(stale["reads"]["model_experience"])["rules"]
    assert retained["usability"] == {
        "state": "needs_recheck",
        "reason_codes": ["SOURCE_UNAVAILABLE"],
    }
    assert {key: value for key, value in retained.items() if key != "usability"} == {
        key: value for key, value in published_v2.items() if key != "usability"
    }
    assert _ok(stale["reads"]["peer_model_experience"])["rules"][0]["usability"] == {
        "state": "needs_recheck",
        "reason_codes": ["AUTHORITY_SNAPSHOT_INVALID", "SOURCE_UNAVAILABLE"],
    }
    with flow.scoped(work) as session:
        assert (
            session.get(flow.DesignRuleVersion, UUID(receipts["rule_v1"]["subject_id"])).body
            == rule_v1_body
        )
        assert (
            session.get(flow.DesignRuleVersion, UUID(receipts["rule_v2"]["subject_id"])).body
            == rule_v2_body
        )
        assert session.get(Artifact, UUID(work.authority_source["id"])).status == "active"
        assert session.get(Artifact, UUID(work.config["source"])).status == "active"
    _export(work, phases, deepcopy(refs), receipts, guard_checks)
