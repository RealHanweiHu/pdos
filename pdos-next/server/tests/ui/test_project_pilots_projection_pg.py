"""Original project Pilot DTOs over one existing synthetic physical/source case.

Root alone executes against explicitly verified isolated pdos_test URLs. The
fixture's saved S2 failure and native Pilot prerequisites are reused once; this
adds no start, release, qualification, external use or future-clock adjustment.
"""
# ruff: noqa: F811 -- imported fixtures register the existing command dependency tree.

import json
import os
from copy import copy
from pathlib import Path

import pytest
from g0_fixture import create_g0_project
from native_pilot_transactions import fixtures as helper
from native_pilot_transactions.fixtures import native_case as native_case
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.domain.build_execution.models import (
    ActualConfiguration,
    BuildLot,
    SampleAllocation,
    SampleUnit,
)
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    OperationalAsset,
)
from pdos_next.domain.builds.models import Build
from pdos_next.domain.configurations.models import EngineeringConfiguration, ProcessRevision
from pdos_next.domain.products.models import DefinitionRevision
from pdos_next.domain.professional_authority.models import ProfessionalFact
from pdos_next.domain.projects.models import Project, ProjectProductLink
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.models import (
    Artifact,
    Consumption,
    Grant,
    ObjectAudience,
    OriginalSecurity,
    UploadedOriginal,
)


def _counts(work):
    models = (
        *helper.EFFECT_MODELS,
        Project,
        ProjectProductLink,
        DefinitionRevision,
        Build,
        ActualConfiguration,
        BuildLot,
        SampleAllocation,
        SampleUnit,
        EngineeringConfiguration,
        ProcessRevision,
        *helper.publication.PUBLICATION_MODELS,
        *helper.publication.DRAFT_MODELS,
        ProfessionalFact,
        BuildOperationalFact,
        BuildOperationalCurrent,
        OperationalAsset,
        QualityIssueVersion,
        QualityIssueCurrent,
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


def _read(work, *, project_id=None, actor=None):
    path = helper.root_url(work)
    params = {"project_id": str(project_id or work.project_id)}
    response = work.setup.client.get(
        path, params=params, headers=helper.publication.headers(work, actor)
    )
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


def _pilot(work, phase):
    page = _ok(phase["reads"]["project_pilots"])
    assert page["project_id"] == str(work.project_id) and page["next_cursor"] is None
    assert page["qualification"] == "unknown" and page["manufacturing_release"] is None
    [value] = page["items"]
    assert value["project_id"] == str(work.project_id)
    assert value["pilot"]["id"] == str(work.create.details.pilot_id)
    assert value["pilot"]["revision"] == 1
    assert value["qualification"] == "unknown" and value["start_authorized"] is False
    assert value["manufacturing_release"] is None and value["external_delivery"] is False
    return value


def _export(work, scope, phases, receipts):
    destination = os.environ.get("PDOS_UI_PROJECT_PILOTS_EXPORT")
    if not destination:
        return
    path = Path(destination)
    assert path.is_absolute(), "Actual project Pilot DTO export requires an absolute path"
    bundle = {
        "version": "project-pilots-projection-qa/v1",
        "fixture_nature": "actual commands/HTTP over one controlled synthetic native Pilot case",
        "scope": scope,
        "phases": phases,
        "command_receipts": receipts,
        "limitations": [
            "All bodies are original unmodified actual project-filtered /pilots GET responses.",
            "The project GET supplies complete roots/Current/observations; no detail GET is added.",
            "Pilot root revision stays 1 while Current and observation revisions advance.",
            "Rates retain exact original strings/nulls; recorded_fraction is not a final rate.",
            "Corrections append a new observation and retain the old record/projection unchanged.",
            "Statistics-source withdrawal requires recheck without rewriting saved observations.",
            "Observation, saved-at and projection received_at clocks remain distinct.",
            "Synthetic facts and good yield confer no start, factory or production qualification.",
            "The existing fixture restores actual UTC before Start; no future clock is introduced.",
            "The single actual S2/Issue prerequisite is reused, not counted as new S2 acceptance.",
        ],
    }
    encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
    assert all(token not in encoded for token in work.setup.tokens.values())
    for forbidden in ("confirmation_token", "approval_token", "storage_key", "locator_map"):
        assert forbidden not in encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded + "\n", encoding="utf-8")


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_actual_project_pilots_keep_partial_correction_and_withdrawn_source_history(native_case):
    work, phases, receipts = native_case, [], {}
    setup = work.setup

    def save(operation, payload, model):
        command, _ = helper.prepare(work, operation, payload.model_dump(mode="json"))
        response = helper.post(setup, command)
        assert response.status_code == 200, response.text
        receipt = response.json()
        helper.assert_atom(work, command, receipt, model)
        return receipt

    receipts["pilot_created"] = save(helper.CREATE_OPERATION, work.create, helper.NativePilotRun)
    created = _phase(
        work,
        "pilot_created_without_observations",
        {"project_pilots": lambda: _read(work)},
    )
    phases.append(created)
    initial = _pilot(work, created)
    assert initial["current"] == {"revision": 1, "epoch": 1, "latest_observation_id": None}
    assert initial["observations"] == []
    root = initial["pilot"]
    assert root["details"] == work.create.details.model_dump(mode="json")
    assert root["statistics_basis"] == work.create.statistics.model_dump(mode="json")
    assert root["receipt_id"] == receipts["pilot_created"]["id"]
    assert root["details"]["basis"]["lot"] == work.basis.lot.model_dump(mode="json")
    assert root["details"]["basis"]["unit"] == "ea"
    resource = root["material"]["statistics"]["resource"]
    assert resource["execution_authorized"] is False
    assert resource["resources"][0]["acceptance"] == "unknown"

    partial_payload, partial_original = helper.result_payload(work, work.create, exception=True)
    receipts["partial_observation"] = save(
        helper.RESULT_OPERATION, partial_payload, helper.NativePilotObservation
    )
    partial_phase = _phase(
        work,
        "partial_aggregate_observation",
        {"project_pilots": lambda: _read(work)},
    )
    phases.append(partial_phase)
    partial = _pilot(work, partial_phase)
    [first] = partial["observations"]
    assert partial["pilot"] == root
    assert partial["current"] == {
        "revision": 2,
        "epoch": 2,
        "latest_observation_id": first["id"],
    }
    assert first["revision"] == 2 and first["pilot_revision_before"] == 1
    assert first["previous_observation_id"] is None
    assert first["record"] == partial_payload.record.model_dump(mode="json")
    assert first["receipt_id"] == receipts["partial_observation"]["id"]
    assert first["fixed_scope"]["pilot_revision"] == 1
    assert first["fixed_scope"]["cohort"]["fixed_input_count"] == work.population_count == 2
    assert first["projection"]["counts"] == first["record"]["counts"]
    metrics = first["projection"]["metrics"]
    assert metrics["first_pass_yield"]["value"] == "0.5"
    assert metrics["first_pass_yield"]["numerator"] == 1
    assert metrics["first_pass_yield"]["denominator"] == 2
    assert metrics["final_good_yield"]["value"] is None
    assert metrics["final_good_yield"]["recorded_fraction"] == "0.5"
    assert metrics["final_good_yield"]["state"] == "partial"
    assert metrics["final_good_yield"]["partition_complete"] is False
    assert first["record"]["exceptions"][0]["issue"]["id"] == str(work.issue_id)
    original_first = helper.observation_snapshot(work, first["id"])

    complete_payload, complete_original = helper.result_payload(
        work, work.create, revision=2, previous=first, complete=True, exception=True
    )
    receipts["complete_correction"] = save(
        helper.RESULT_OPERATION, complete_payload, helper.NativePilotObservation
    )
    other_setup = copy(setup)
    other_project = create_g0_project(other_setup, name="Synthetic other-model Pilot read scope")
    complete_phase = _phase(
        work,
        "complete_correction_retains_partial_history",
        {
            "project_pilots": lambda: _read(work),
            "peer_project_pilots": lambda: _read(work, actor=setup.peer),
            "other_model_project": lambda: _read(work, project_id=other_project.project_id),
            "foreign_tenant_project": lambda: _read(work, actor=setup.other_human),
        },
    )
    phases.append(complete_phase)
    complete = _pilot(work, complete_phase)
    assert complete["pilot"] == root
    assert len(complete["observations"]) == 2
    assert complete["observations"][0] == first
    latest = complete["observations"][1]
    assert latest["revision"] == 3 and latest["pilot_revision_before"] == 2
    assert latest["previous_observation_id"] == first["id"]
    assert latest["record"] == complete_payload.record.model_dump(mode="json")
    assert latest["record"]["previous_observation_id"] == first["id"]
    assert latest["record"]["correction_reason"]
    assert latest["receipt_id"] == receipts["complete_correction"]["id"]
    assert complete["current"] == {
        "revision": 3,
        "epoch": 3,
        "latest_observation_id": latest["id"],
    }
    assert latest["fixed_scope"]["pilot_revision"] == 2
    assert latest["fixed_scope"]["cohort"] == first["fixed_scope"]["cohort"]
    assert latest["fixed_scope"]["yield_scope"] == first["fixed_scope"]["yield_scope"]
    assert latest["projection"]["counts"] == latest["record"]["counts"]
    metrics = latest["projection"]["metrics"]
    assert metrics["first_pass_yield"]["value"] == "0.5"
    assert metrics["final_good_yield"]["value"] == "1"
    assert metrics["final_good_yield"]["recorded_fraction"] == "1"
    assert metrics["final_good_yield"]["denominator"] == 2
    assert metrics["final_good_yield"]["partition_complete"] is True
    assert metrics["process_capability"] == metrics["factory_qualification"] == "NOT_ASSESSED"
    assert helper.observation_snapshot(work, first["id"]) == original_first
    assert _ok(complete_phase["reads"]["peer_project_pilots"]) == _ok(
        complete_phase["reads"]["project_pilots"]
    )
    for name in ("other_model_project", "foreign_tenant_project"):
        refused = complete_phase["reads"][name]
        assert refused["status_code"] == 403, refused
        assert refused["body"]["code"] == "FORBIDDEN_SCOPE"
        assert "items" not in refused["body"]
    for observation in complete["observations"]:
        assert observation["pilot_id"] == root["id"]
        assert observation["record"]["observation_id"] == observation["id"]
        assert observation["projection"]["observation_id"] == observation["id"]
        assert observation["projection"]["fixed"] == observation["fixed_scope"]
        assert observation["projection"]["received_at"] is None
        assert observation["record"]["observed"]["occurred_at"]
        assert observation["record"]["observed"]["original_timezone"] == "UTC"
        assert observation["sources"] and observation["required_source_read_set"]

    receipts["statistics_source_withdrawal"] = helper.withdraw(work, work.statistics_original_id)
    withdrawn_phase = _phase(
        work,
        "statistics_source_withdrawn_saved_values_retained",
        {"project_pilots": lambda: _read(work)},
    )
    phases.append(withdrawn_phase)
    retained = _pilot(work, withdrawn_phase)
    assert retained["current"] == complete["current"]
    assert retained["pilot"]["source_status"] == "needs_recheck"
    assert {key: value for key, value in retained["pilot"].items() if key != "source_status"} == {
        key: value for key, value in root.items() if key != "source_status"
    }
    assert len(retained["observations"]) == 2
    for old, saved in zip(complete["observations"], retained["observations"], strict=True):
        assert {key: value for key, value in old.items() if key != "source_status"} == {
            key: value for key, value in saved.items() if key != "source_status"
        }
    assert helper.observation_snapshot(work, first["id"]) == original_first

    _export(
        work,
        {
            "category_id": str(setup.category),
            "product_id": str(setup.product),
            "project_id": str(work.project_id),
            "principal_id": str(setup.human),
            "pilot_id": str(work.create.details.pilot_id),
            "root_revision": 1,
            "partial_observation_id": first["id"],
            "complete_observation_id": latest["id"],
            "statistics_original_id": str(work.statistics_original_id),
            "partial_original_id": str(partial_original),
            "complete_original_id": str(complete_original),
            "other_model_project_id": str(other_project.project_id),
        },
        phases,
        receipts,
    )
