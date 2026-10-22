"""Fixed Build engineering DTOs after an actual synthetic EC revision advances.

Only root executes against explicitly verified isolated pdos_test URLs. Existing
G0/configuration/Build commands create all business records; the two-project
fixture includes its documented synthetic stored parent publication and audience.
External references are synthetic declarations, not connected-system validation.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_build_project_scope import second_project_configuration
from test_builds import build_command
from test_builds import configuration as configuration
from test_project_first_plan import accepted, cmd
from test_project_first_plan import definition as definition
from test_project_first_plan import project as project

from pdos_next.domain.builds.models import Build, BuildReadiness
from pdos_next.domain.configurations.models import (
    BomLine,
    BomRevision,
    EngineeringConfiguration,
    PartIdentity,
    ProcessRevision,
)
from pdos_next.domain.configurations.schemas import ExternalDesignReference
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.models import (
    Artifact,
    Audit,
    Confirmation,
    Grant,
    ObjectAudience,
    Outbox,
    Product,
    Receipt,
    RequestKey,
)


def _counts(setup):
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
        Build,
        BuildReadiness,
        Artifact,
        Grant,
        ObjectAudience,
        Confirmation,
        RequestKey,
        Receipt,
        Audit,
        Outbox,
    )
    with Session(setup.admin) as session:
        return {
            model.__tablename__: session.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == setup.tenant)
            )
            for model in models
        }


def _read(setup, project_id, *, actor=None):
    route = f"/v1/categories/{setup.category}/products/{setup.product}/builds"
    params = {"project_id": project_id}
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


def _phase(setup, phase, readers):
    before = _counts(setup)
    reads = {name: reader() for name, reader in readers.items()}
    after = _counts(setup)
    assert before == after
    return {
        "phase": phase,
        "reads": reads,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
    }


def _canonical(reference):
    # Use the existing public validator/serializer, including aware time output.
    return ExternalDesignReference.model_validate(reference).model_dump(mode="json")


def _export(setup, scope, phases, receipts):
    destination = os.environ.get("PDOS_UI_BUILD_ENGINEERING_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual Build engineering DTO export requires an absolute path"
    bundle = {
        "version": "project-build-engineering-projection-qa/v1",
        "fixture_nature": "actual HTTP/domain commands over isolated synthetic evidence",
        "scope": scope,
        "phases": phases,
        "command_receipts": receipts,
        "limitations": [
            "Every read body is an unmodified actual project-filtered Builds GET JSON response.",
            "Build retains EC v1 after the actual EC series advances; no latest-configuration GET.",
            "External identity/revision/time/hash are declarations, not verification.",
            "A source-backed external reference may retain null revision/time/hash.",
            "Draft/source-current statuses imply neither approval nor production readiness.",
            "BOM decimal strings and null unknowns retain the server's original representation.",
            "No drift, compatibility, deviation approval or actual configuration inferred.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_build_engineering_reads_keep_fixed_design_references_bom_and_ec_revision(
    setup, configuration
):
    config = deepcopy(configuration)
    reference = deepcopy(config["engineering_payload"]["sources"][0])
    design_versions = {
        "mechanical": {
            "system": "Synthetic mechanical registry",
            "external_id": "SYN-CAD-A",
            "revision": "mechanical-A",
            "as_of": "2026-10-18T11:22:33+08:00",
            "content_sha256": "a" * 64,
            "basis": None,
        },
        "electronic": {
            "system": "Synthetic electronic source declaration",
            "external_id": "SYN-BOARD-BASIS",
            "revision": None,
            "as_of": None,
            "content_sha256": None,
            "basis": reference,
        },
        "firmware": {
            "system": "Synthetic firmware registry",
            "external_id": "SYN-FIRMWARE-IMAGE",
            "revision": "firmware-v1",
            "as_of": "2026-10-17T00:00:00Z",
            "content_sha256": "b" * 64,
            "basis": None,
        },
    }
    engineering_payload = {
        **deepcopy(config["engineering_payload"]),
        "name": "Synthetic fixed engineering summary v1",
        "reason": "Fix three explicit synthetic design references and original BOM unknowns",
        **design_versions,
    }
    engineering, _ = accepted(
        setup,
        cmd(setup, "engineering.configuration.create", engineering_payload, config["source"]),
    )
    assert engineering["subject_revision"] == 1
    process_payload = {
        **deepcopy(config["process_payload"]),
        "name": "Synthetic process fixed to engineering summary v1",
        "engineering_configuration_id": engineering["subject_id"],
        "expected_engineering_revision": 1,
    }
    process, _ = accepted(
        setup, cmd(setup, "npi.process.revise", process_payload, config["source"])
    )
    config.update(
        engineering=engineering,
        process=process,
        engineering_payload=engineering_payload,
        process_payload=process_payload,
    )
    built, _ = accepted(
        setup,
        build_command(setup, config, name="Synthetic Build keeps explicit engineering v1"),
    )
    other = second_project_configuration(setup, config)
    other_build, _ = accepted(
        setup, build_command(setup, other, name="Synthetic other-project engineering Build")
    )
    project_id = config["project"]
    fixed_phase = _phase(
        setup,
        "build_pins_engineering_v1",
        {"project_builds": lambda: _read(setup, project_id)},
    )
    [fixed_build] = _ok(fixed_phase["reads"]["project_builds"])["items"]
    fixed = fixed_build["engineering_configuration"]
    assert fixed_build["id"] == built["subject_id"]
    assert fixed["id"] == engineering["subject_id"] and fixed["revision"] == 1
    assert fixed["design_versions"] == {
        key: _canonical(value) for key, value in design_versions.items()
    }
    assert fixed["external_verification"] == "not_checked"
    assert fixed["definition_id"] == config["definition"]
    assert fixed["definition_revision"] == 1
    assert fixed["bom_id"] == config["bom"]["subject_id"] and fixed["bom_revision"] == 1
    lines = {row["key"]: row for row in fixed["bom"]["lines"]}
    assert set(lines) == {"motor", "unknown"}
    assert lines["motor"]["quantity"] == "2" and lines["motor"]["loss_rate"] == "0.1"
    assert lines["unknown"]["quantity"] is None and lines["unknown"]["loss_rate"] is None
    for line in lines.values():
        assert line["part_id"] == line["part"]["id"]
        assert line["expected_part_revision"] == line["part"]["revision"] == 1
        assert line["part"]["external_verification"] == "not_checked"
        assert line["part"]["mapping_status"] == "unknown"
        assert line["part"]["erp_number"] is None and line["part"]["mapping_version"] is None

    revised_payload = {
        **deepcopy(engineering_payload),
        "previous_id": engineering["subject_id"],
        "expected_previous_revision": 1,
        "name": "Synthetic engineering summary v2 outside original Build",
        "reason": "Retain the original Build while advancing the separate EC version chain",
    }
    revised_payload["mechanical"].update(revision="mechanical-B", content_sha256="c" * 64)
    revised_payload["firmware"].update(revision="firmware-v2", content_sha256="d" * 64)
    revised, _ = accepted(
        setup,
        cmd(setup, "engineering.configuration.create", revised_payload, config["source"]),
    )
    assert revised["subject_revision"] == 2
    with Session(setup.admin) as session:
        old = session.get(EngineeringConfiguration, UUID(engineering["subject_id"]))
        new = session.get(EngineeringConfiguration, UUID(revised["subject_id"]))
        assert old is not None and new is not None
        assert new.series_id == old.series_id and new.previous_id == old.id
        assert new.revision == 2 and new.expected_previous_revision == 1
        assert new.design_versions == {
            key: _canonical(revised_payload[key]) for key in design_versions
        }
        assert old.design_versions == fixed["design_versions"]
    revised_phase = _phase(
        setup,
        "ec_series_advanced_build_retains_v1",
        {
            "project_builds": lambda: _read(setup, project_id),
            "other_project_builds": lambda: _read(setup, other["project"]),
            "peer_project_builds": lambda: _read(setup, project_id, actor=setup.peer),
            "missing_project": lambda: _read(setup, str(uuid4())),
            "foreign_tenant_builds": lambda: _read(setup, project_id, actor=setup.other_human),
        },
    )
    page = _ok(revised_phase["reads"]["project_builds"])
    assert page["unavailable_count"] == 0 and page["has_more"] is False
    [retained_build] = page["items"]
    assert retained_build == fixed_build
    assert retained_build["project_id"] == project_id
    assert retained_build["status"] == "planned" and retained_build["readiness"] is None
    assert retained_build["engineering_configuration"]["status"] == "draft"
    assert retained_build["manufacturing_configuration"]["id"] == process["subject_id"]
    assert (
        retained_build["manufacturing_configuration"]["engineering_configuration_id"]
        == engineering["subject_id"]
    )
    [other_row] = _ok(revised_phase["reads"]["other_project_builds"])["items"]
    assert other_row["id"] == other_build["subject_id"] != built["subject_id"]
    assert other_row["project_id"] == other["project"] != project_id
    assert _ok(revised_phase["reads"]["peer_project_builds"])["items"] == []
    for name in ("missing_project", "foreign_tenant_builds"):
        refusal = revised_phase["reads"][name]
        assert refusal["status_code"] == 403, refusal
        assert refusal["body"]["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in refusal["body"]

    _export(
        setup,
        {
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": project_id,
            "build_id": built["subject_id"],
            "build_revision": 1,
            "engineering_v1": {"id": engineering["subject_id"], "revision": 1},
            "engineering_v2": {"id": revised["subject_id"], "revision": 2},
            "process": {"id": process["subject_id"], "revision": 1},
            "other_project_id": other["project"],
            "other_build_id": other_build["subject_id"],
        },
        [fixed_phase, revised_phase],
        {"engineering_v1": engineering, "engineering_v2": revised, "build": built},
    )
