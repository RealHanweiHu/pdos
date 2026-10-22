"""Actual, read-only Build output DTOs for the selected-Build UI summary.

Only root executes PostgreSQL with explicitly verified isolated pdos_test URLs.
Existing confirmed commands create synthetic observations and sample identities;
the existing two-project fixture supplies its explicit synthetic stored baseline.
No Build start, quality acceptance, reservation or consumption is performed.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_build_execution import actual_command, allocation_command, output_command
from test_build_project_scope import second_project_configuration
from test_builds import build_command
from test_builds import configuration as configuration
from test_project_first_plan import accepted
from test_project_first_plan import definition as definition
from test_project_first_plan import project as project

from pdos_next.domain.build_execution.models import (
    ActualConfiguration,
    BuildLot,
    SampleAllocation,
    SampleUnit,
)
from pdos_next.domain.builds.models import Build, BuildReadiness
from pdos_next.domain.configurations.models import (
    BomRevision,
    EngineeringConfiguration,
    ProcessRevision,
)
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

GROUPS = ("actual_configurations", "lots", "allocations", "samples")


def _counts(setup):
    # Explicit scope only: unrelated S3/S4/S5 schema changes are not an input.
    models = (
        Product,
        Project,
        ProjectProductLink,
        DefinitionRevision,
        BomRevision,
        EngineeringConfiguration,
        ProcessRevision,
        Build,
        BuildReadiness,
        ActualConfiguration,
        BuildLot,
        SampleAllocation,
        SampleUnit,
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


def _read(setup, endpoint, *, actor=None, project_id=None):
    route = f"/v1/categories/{setup.category}/products/{setup.product}/{endpoint}"
    params = {"project_id": project_id} if project_id is not None else {}
    response = setup.client.get(
        route,
        params=params,
        headers={"Authorization": f"Bearer {setup.tokens[actor or setup.human]}"},
    )
    # This is the unmodified actual HTTP JSON, including unsuccessful reads.
    return {
        "route": route,
        "params": params,
        "status_code": response.status_code,
        "body": response.json(),
    }


def _ok(read):
    assert read["status_code"] == 200, read["body"]
    return read["body"]


def _planned(setup, config, *, name):
    receipt, _ = accepted(setup, build_command(setup, config, name=name))
    planned = {**config, "build": receipt}
    actual, _ = accepted(setup, actual_command(setup, planned))
    return planned, actual


def _lot_and_sample(setup, planned, actual, *, units, lot_label, sample):
    lot, _ = accepted(
        setup,
        output_command(setup, planned, actual, units=units, lot_label=lot_label),
    )
    allocation, _ = accepted(
        setup,
        allocation_command(setup, planned, lot, samples=[sample]),
    )
    [sample_id] = allocation["result"]["sample_ids"]
    return {"lot": lot, "allocation": allocation, "sample_id": sample_id, "input": sample}


def _export(setup, scope, reads, before, after):
    destination = os.environ.get("PDOS_UI_BUILD_OUTPUT_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual Build output DTO export requires an absolute path"
    bundle = {
        "version": "project-build-output-projection-qa/v1",
        "fixture_nature": "actual HTTP/domain commands over isolated synthetic evidence",
        "scope": scope,
        "reads": reads,
        "read_only_counts": {"before": before, "after": after, "unchanged": True},
        "limitations": [
            "Every body is an original unmodified actual GET JSON response.",
            "build-execution is product-wide; the selected Build is bound through project Builds.",
            "Separate GETs do not imply one atomic shared snapshot.",
            "Custodian/location/destination/availability are allocation-time registration facts.",
            "Null reservation/consumption are DTO placeholders, not proof of absence.",
            "Synthetic observations confer no Build start, quality or production qualification.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


def test_actual_build_output_reads_keep_two_lots_registration_unknowns_and_project_scope(
    setup, configuration
):
    second = second_project_configuration(setup, configuration)
    planned, actual = _planned(setup, configuration, name="Synthetic two-lot output summary")
    foreign, foreign_actual = _planned(
        setup, second, name="Synthetic other-project output stays separate"
    )
    known = {
        "label": "SYN-OUTPUT-KNOWN",
        "operation_key": "assembly",
        "cavity": "SYN-CAVITY-A",
        "custodian_id": str(setup.human),
        "custodian_label": "Synthetic allocation custodian",
        "location": "Synthetic cabinet A at allocation",
        "destination": "Synthetic intended lab A",
        "availability": "hold",
    }
    unknown = {
        "label": "SYN-OUTPUT-UNKNOWN",
        "operation_key": None,
        "cavity": None,
        "custodian_id": None,
        "custodian_label": None,
        "location": None,
        "destination": "Synthetic intended lab B; receipt unknown",
        "availability": "unknown",
    }
    outputs = [
        _lot_and_sample(
            setup,
            planned,
            actual,
            units=units,
            lot_label=f"SYN-OUTPUT-LOT-{index}",
            sample=sample,
        )
        for index, (units, sample) in enumerate(((2, known), (3, unknown)), 1)
    ]
    excluded = _lot_and_sample(
        setup,
        foreign,
        foreign_actual,
        units=1,
        lot_label="SYN-OTHER-PROJECT-LOT",
        sample={"label": "SYN-OTHER-PROJECT-SAMPLE", "availability": "unknown"},
    )
    build_id = planned["build"]["subject_id"]
    foreign_build_id = foreign["build"]["subject_id"]
    project_id, foreign_project_id = configuration["project"], second["project"]

    before = _counts(setup)
    reads = {
        "project_builds": _read(setup, "builds", project_id=project_id),
        "other_project_builds": _read(setup, "builds", project_id=foreign_project_id),
        "build_execution": _read(setup, "build-execution"),
        "peer_project_builds": _read(setup, "builds", actor=setup.peer, project_id=project_id),
        "peer_build_execution": _read(setup, "build-execution", actor=setup.peer),
        "missing_project": _read(setup, "builds", project_id=str(uuid4())),
        "foreign_tenant_builds": _read(
            setup, "builds", actor=setup.other_human, project_id=project_id
        ),
        "foreign_tenant_execution": _read(setup, "build-execution", actor=setup.other_human),
    }
    after = _counts(setup)
    assert before == after

    project_page = _ok(reads["project_builds"])
    [build] = project_page["items"]
    assert build["id"] == build_id and build["project_id"] == project_id
    assert project_page["unavailable_count"] == 0 and project_page["has_more"] is False
    assert build["revision"] == 1 and build["status"] == "planned"
    assert build["readiness"] is None
    [other_build] = _ok(reads["other_project_builds"])["items"]
    assert other_build["id"] == foreign_build_id
    assert other_build["project_id"] == foreign_project_id != project_id
    assert other_build["id"] != build_id

    execution = _ok(reads["build_execution"])
    assert execution["unavailable_count"] == 0 and execution["has_more"] is False
    assert execution["authorization_status"] == "not_authorized"
    assert execution["qualification_status"] == "unknown"
    assert [len(execution[key]) for key in GROUPS] == [2, 3, 3, 3]
    selected = {
        key: [
            row
            for row in execution[key]
            if row["build_id"] == build_id and row["project_id"] == project_id
        ]
        for key in GROUPS
    }
    assert [len(selected[key]) for key in GROUPS] == [1, 2, 2, 2]
    [fixed] = selected["actual_configurations"]
    assert fixed["id"] == actual["subject_id"] and fixed["revision"] == 1
    assert fixed["actual_engineering_configuration_id"] == build["engineering_configuration"]["id"]
    assert (
        fixed["actual_manufacturing_configuration_id"] == build["manufacturing_configuration"]["id"]
    )
    for key in GROUPS:
        assert all(
            row["product_id"] == str(setup.product)
            and row["build_revision"] == build["revision"]
            and row["source_status"] == "current"
            and row["qualification_status"] == "unknown"
            and row["authorization_status"] == "not_authorized"
            for row in selected[key]
        )
        assert any(
            row["build_id"] == foreign_build_id and row["project_id"] == foreign_project_id
            for row in execution[key]
        )
    lots = {row["id"]: row for row in selected["lots"]}
    allocations = {row["id"]: row for row in selected["allocations"]}
    samples = {row["id"]: row for row in selected["samples"]}
    for output, count in zip(outputs, (2, 3), strict=True):
        lot = lots[output["lot"]["subject_id"]]
        allocation = allocations[output["allocation"]["subject_id"]]
        sample = samples[output["sample_id"]]
        assert lot["observed_unit_count"] == count and lot["unit"] == "ea"
        assert lot["identified_count"] == 1 and lot["remaining_unit_count"] == count - 1
        assert lot["build_observed_unit_count"] == 5
        assert lot["quality_status"] == "unknown"
        assert lot["observation"]["nature"] == "synthetic"
        assert lot["observation"]["occurred_at"] and lot["observation"]["received_at"]
        assert lot["actual_configuration_id"] == fixed["id"]
        assert lot["actual_configuration_revision"] == fixed["revision"]
        assert allocation["lot_id"] == lot["id"] and allocation["unit_count"] == 1
        assert allocation["actual_configuration_id"] == fixed["id"]
        assert allocation["sample_ids"] == [sample["id"]]
        assert sample["lot_id"] == lot["id"] and sample["allocation_id"] == allocation["id"]
        assert sample["actual_configuration_id"] == fixed["id"]
        assert sample["actual_configuration_revision"] == fixed["revision"]
        assert all(sample[key] == value for key, value in output["input"].items())
        assert sample["observation_nature"] == "synthetic"
        # These legacy null DTO fields are deliberately not interpreted as absence.
        assert sample["reservation"] is None and sample["consumption"] is None
    assert excluded["sample_id"] not in samples

    peer_execution = _ok(reads["peer_build_execution"])
    assert all(peer_execution[key] == [] for key in GROUPS)
    assert _ok(reads["peer_project_builds"])["items"] == []
    for name in ("missing_project", "foreign_tenant_builds", "foreign_tenant_execution"):
        assert reads[name]["status_code"] == 403, reads[name]
        assert reads[name]["body"]["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in reads[name]["body"] and "samples" not in reads[name]["body"]

    _export(
        setup,
        {
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": project_id,
            "build_id": build_id,
            "build_revision": 1,
            "actual_configuration_id": fixed["id"],
            "lot_ids": [row["lot"]["subject_id"] for row in outputs],
            "allocation_ids": [row["allocation"]["subject_id"] for row in outputs],
            "sample_ids": [row["sample_id"] for row in outputs],
            "other_project_id": foreign_project_id,
            "other_build_id": foreign_build_id,
        },
        reads,
        before,
        after,
    )
