"""Original project preparation DTOs over existing confirmed synthetic commands.

Only root runs PostgreSQL after checking the explicit isolated pdos_test target.
This case tests draft/history reading, not manufacturing publication, qualification
or production enablement. Stored gaps remain the original save-time assessment.
The existing two-project fixture includes its explicit synthetic stored parent
publication and ordinary fixture audience, not a qualified publication command.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import json
import os
from pathlib import Path
from uuid import uuid4

from manufacturing_preparation_transactions.fixtures import (
    EFFECT_MODELS,
    PARENT_MODELS,
    bootstrap_authority,
    inputs,
    payload,
)
from manufacturing_preparation_transactions.fixtures import manufacturing_case as manufacturing_case
from manufacturing_preparation_transactions.test_transactions import reference, save
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_build_project_scope import second_project_configuration
from test_builds import configuration as configuration
from test_project_first_plan import definition as definition
from test_project_first_plan import project as project

from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.models import Artifact, Confirmation, Grant, ObjectAudience
from pdos_next.service import digest


def _counts(work):
    # Enumerate the existing preparation loop only, not in-flight shared metadata.
    models = (
        *PARENT_MODELS,
        *EFFECT_MODELS,
        Artifact,
        Confirmation,
        ProfessionalFact,
        Grant,
        ObjectAudience,
    )
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in models
        }


def _read(work, *, actor=None, project_id=None, fixed=None):
    setup = work.setup
    route = f"/v1/categories/{setup.category}/products/{setup.product}/manufacturing-preparations"
    if fixed is None:
        params = {"project_id": str(project_id or work.project_id)}
    else:
        route += f"/{fixed['kind']}/{fixed['id']}"
        params = {"revision": fixed["revision"]}
    response = setup.client.get(
        route,
        params=params,
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )
    return {
        "route": route,
        "params": params,
        "status_code": response.status_code,
        "body": response.json(),
    }


def _ok(read):
    assert read["status_code"] == 200, read["body"]
    return read["body"]


def _phase(work, name, readers):
    before = _counts(work)
    reads = {key: reader() for key, reader in readers.items()}
    after = _counts(work)
    assert before == after
    return {
        "phase": name,
        "reads": reads,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
    }


def _export(work, scope, phases):
    destination = os.environ.get("PDOS_UI_MANUFACTURING_PREPARATION_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual manufacturing DTO export requires an absolute path"
    bundle = {
        "version": "project-manufacturing-preparation-projection-qa/v1",
        "fixture_nature": "actual HTTP/domain commands with isolated synthetic authority/evidence",
        "scope": scope,
        "phases": phases,
        "limitations": [
            "Every body is an unmodified actual GET JSON response.",
            "Gaps and document bindings are saved assessments, not fresh global readiness.",
            "Separate GETs do not imply one shared atomic snapshot.",
            "is_current is per series; multiple current work-instruction series remain distinct.",
            "The baseline retains WI v1 after WI v2 and requires recheck; it is not rewritten.",
            "Draft/null manufacturing_release/unknown qualification do not enumerate releases.",
            "Synthetic write authority is not real manufacturing or production qualification.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_preparation_reads_keep_independent_series_and_fixed_baseline_document_history(
    manufacturing_case,
):
    work, phases = manufacturing_case, []
    setup = work.setup
    # An actual other-project G0/configuration chain is a filter counterexample;
    # it receives no manufacturing documents or manufacturing write authority.
    other_project = second_project_configuration(setup, work.config)
    bootstrap_authority(work)

    def document(kind, body):
        return save(work, inputs(work, kind, body))[2]

    wi_first = document("work_instruction", payload(work, "work_instruction"))
    cp = document("control_plan", payload(work, "control_plan"))
    alternative_body = payload(work, "work_instruction")
    alternative_body["title"] = "Synthetic independent alternative instruction series"
    alternative_body["reason"] = (
        "Retain a separate synthetic instruction series for the same operation"
    )
    wi_alternative = document("work_instruction", alternative_body)
    assert wi_alternative["series_id"] != wi_first["series_id"]
    assert wi_alternative["operation_key"] == wi_first["operation_key"]
    baseline = document(
        "manufacturing_baseline",
        payload(
            work,
            "manufacturing_baseline",
            documents={"work_instruction": reference(wi_first), "control_plan": reference(cp)},
        ),
    )
    baseline_digest = digest(baseline["body"])
    binding_set = {
        (row["kind"], row["id"], row["revision"], digest(row["body"])) for row in (wi_first, cp)
    }
    assert {
        (row["kind"], row["id"], row["revision"], row["body_sha256"])
        for row in baseline["body"]["document_bindings"]
    } == binding_set

    saved = _phase(
        work,
        "baseline_fixed_to_wi_v1",
        {
            "project_preparations": lambda: _read(work),
            "fixed_wi_v1": lambda: _read(work, fixed=wi_first),
            "fixed_baseline": lambda: _read(work, fixed=baseline),
        },
    )
    phases.append(saved)
    saved_page = _ok(saved["reads"]["project_preparations"])
    assert len(saved_page["versions"]) == 4
    assert all(row["is_current"] is True for row in saved_page["versions"])
    assert _ok(saved["reads"]["fixed_baseline"])["source_status"] == "current"

    wi_current = document(
        "work_instruction",
        payload(work, "work_instruction", previous=wi_first, revision=2),
    )
    assert wi_current["series_id"] == wi_first["series_id"]
    assert wi_current["revision"] == 2 and wi_current["previous_id"] == wi_first["id"]
    assert wi_current["previous_revision"] == 1
    revised = _phase(
        work,
        "wi_series_advanced_baseline_retains_v1",
        {
            "project_preparations": lambda: _read(work),
            "fixed_wi_v1": lambda: _read(work, fixed=wi_first),
            "fixed_wi_v2": lambda: _read(work, fixed=wi_current),
            "fixed_baseline": lambda: _read(work, fixed=baseline),
            "other_project_preparations": lambda: _read(work, project_id=other_project["project"]),
            "peer_preparations": lambda: _read(work, actor=setup.peer),
            "peer_fixed_wi_v1": lambda: _read(work, actor=setup.peer, fixed=wi_first),
            "missing_project": lambda: _read(work, project_id=uuid4()),
            "foreign_tenant_preparations": lambda: _read(work, actor=setup.other_human),
            "foreign_tenant_fixed_baseline": lambda: _read(
                work, actor=setup.other_human, fixed=baseline
            ),
        },
    )
    phases.append(revised)
    revised_page = _ok(revised["reads"]["project_preparations"])
    assert revised_page["has_more"] is False and revised_page["unavailable_count"] == 0
    assert revised_page["history_page"]["next_cursor"] is None
    assert len(revised_page["versions"]) == 5
    by_id = {row["id"]: row for row in revised_page["versions"]}
    assert set(by_id) == {row["id"] for row in (wi_first, wi_current, wi_alternative, cp, baseline)}
    assert sum(row["is_current"] for row in revised_page["versions"]) == 4
    current_instructions = [
        row
        for row in revised_page["versions"]
        if row["kind"] == "work_instruction" and row["is_current"]
    ]
    assert {row["id"] for row in current_instructions} == {
        wi_current["id"],
        wi_alternative["id"],
    }
    assert len({row["series_id"] for row in current_instructions}) == 2
    for row in revised_page["versions"]:
        assert row["project_id"] == str(work.project_id)
        assert row["process"] == work.process_ref
        assert row["status"] == "draft"
        assert row["qualification"] == "unknown" and row["manufacturing_release"] is None
        assert row["negative_enumeration_complete"] is False
    assert revised_page["qualification"] == "unknown"
    assert revised_page["manufacturing_release"] is None
    assert revised_page["negative_enumeration_complete"] is False

    old = _ok(revised["reads"]["fixed_wi_v1"])
    latest = _ok(revised["reads"]["fixed_wi_v2"])
    retained_baseline = _ok(revised["reads"]["fixed_baseline"])
    assert old == by_id[wi_first["id"]] and latest == by_id[wi_current["id"]]
    assert retained_baseline == by_id[baseline["id"]]
    assert old["is_current"] is False and old["source_status"] == "current"
    assert old["body"] == wi_first["body"] and old["revision"] == 1
    assert latest["is_current"] is True and latest["source_status"] == "current"
    assert retained_baseline["is_current"] is True
    assert retained_baseline["source_status"] == "needs_recheck"
    assert digest(retained_baseline["body"]) == baseline_digest
    assert retained_baseline["body"]["gaps"] == baseline["body"]["gaps"]
    assert {
        (row["kind"], row["id"], row["revision"], row["body_sha256"])
        for row in retained_baseline["body"]["document_bindings"]
    } == binding_set
    parameter = latest["body"]["input"]["steps"][0]["parameters"][0]
    assert all(parameter[key] is None for key in ("nominal", "lower", "upper", "unit"))
    assert latest["body"]["input"]["conditions"] is None
    assert by_id[cp["id"]]["body"]["input"]["checks"][0]["criterion"] is None

    assert _ok(revised["reads"]["other_project_preparations"])["versions"] == []
    peer = _ok(revised["reads"]["peer_preparations"])
    assert peer["versions"] == []
    assert work.document_source not in json.dumps(peer)
    for name in (
        "peer_fixed_wi_v1",
        "missing_project",
        "foreign_tenant_preparations",
        "foreign_tenant_fixed_baseline",
    ):
        refusal = revised["reads"][name]
        assert refusal["status_code"] == 403, refusal
        assert refusal["body"]["code"] == "FORBIDDEN_SCOPE"
        assert "versions" not in refusal["body"] and "body" not in refusal["body"]

    _export(
        work,
        {
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "other_project_id": other_project["project"],
            "process": work.process_ref,
            "wi_v1": reference(wi_first),
            "wi_v2": reference(wi_current),
            "wi_alternative": reference(wi_alternative),
            "control_plan": reference(cp),
            "baseline": reference(baseline),
        },
        phases,
    )
