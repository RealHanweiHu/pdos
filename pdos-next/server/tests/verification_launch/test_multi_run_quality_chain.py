"""Real batched S2 failure feeds S3 Issue/CAPA without replacing either Run.

Root alone executes PostgreSQL. Existing synthetic authority/import fixtures are
explicit; owner readers, original bytes, commands and paired proofs stay real.
"""

# ruff: noqa: F811 - imported pytest fixtures register their actual dependencies
from contextlib import ExitStack
from copy import deepcopy
from uuid import UUID

import pytest
from build_start.test_transactions import import_authority
from change_execution import test_transactions as change
from quality_execution import fixtures as quality
from quality_followup_transactions import fixtures as followup
from sqlalchemy import func, select
from test_project_first_plan import accepted, post
from verification_handoff import fixtures as handoff
from verification_results import fixtures as results

from pdos_next.database import tenant_session
from pdos_next.domain.capa_verification import service as output_owner
from pdos_next.domain.capa_verification.schemas import OutputRef
from pdos_next.domain.change_execution import service as change_service
from pdos_next.domain.quality_execution.models import QualityFailureMap
from pdos_next.domain.verification_launch import service as launch_service
from pdos_next.domain.verification_launch.models import VerificationRunVersion
from pdos_next.errors import DomainError
from pdos_next.models import now
from verification_launch import fixtures as launch
from verification_launch.fixtures import (  # noqa: F401
    known_configuration,
    operational_work,
    ready_work,
)
from verification_launch.test_multi_run_chain import (  # noqa: F401
    counts,
    launch_command,
    multi_work,
    prepare_run,
)


def measurement_rows(work, raw="10.0000"):
    """Rows carry this actual Run's fixed metadata before uploading real bytes."""
    fixed = results.current_rows(work)
    rows = []
    for pair in fixed.run.coverage:
        sample = next(sample for sample in fixed.run.samples if sample.id == pair.sample_id)
        item = next(item for item in fixed.run.items if item.id == pair.item_id)
        rows.append(
            {
                "format": "pdos-measurement-jsonl-v1",
                "run_id": str(fixed.run.id),
                "sample_id": str(sample.id),
                "sample_revision": sample.revision,
                "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
                "cavity": sample.cavity,
                "item_id": item.id,
                "raw_value": raw,
                "unit": item.unit,
                "conditions": fixed.run.execution.conditions,
                "environment": fixed.run.execution.environment,
                "equipment": fixed.run.execution.equipment.model_dump(mode="json"),
                "calibration": fixed.run.execution.calibration.model_dump(mode="json"),
                "method": item.method.model_dump(mode="json"),
                "executor_id": str(work.quality.human),
                "observed_at": now().isoformat(),
                "observed_timezone": "UTC",
            }
        )
    return rows


def followup_view(work, expected_formal=None):
    """The HTTP view resolves actual output owners, including paired Formal IO."""
    before = counts(work)
    response = work.quality.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-followup",
        headers=work.quality.headers,
        params={"issue_id": str(work.issue_id)},
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert counts(work) == before
    options = [value["ref"] for value in view["output_options"]]
    if expected_formal is not None:
        assert {
            "kind": "verification_request",
            "id": str(expected_formal.id),
            "revision": expected_formal.revision,
            "key": None,
        } in options
    return view, options


def resolve_runs(work, *run_works):
    """Read each immutable Run version, never choose the first Run of a request."""
    issue_revision = followup.fixed_issue(work).revision
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.human,
        category_id=work.setup.category,
        read_snapshot=True,
    ) as session:
        basis = output_owner.load_followup_basis(
            session, work.quality.ctx, work.setup.product, work.issue_id, issue_revision
        )
        refs = []
        for run_work in run_works:
            _, row = launch_service._current(
                session, work.quality.ctx, work.setup.product, run_id=run_work.binding.run_id
            )
            refs.append(OutputRef(kind="verification_run", id=row.id, revision=row.revision))
        resolved = output_owner.resolve_followup_outputs(
            session,
            work.quality.ctx,
            work.setup.product,
            basis,
            UUID(work.actions[0]["id"]),
            refs,
        )
        assert resolved.action_fulfilled is None
        assert {value.logical_id for value in resolved.outputs} == {
            run_work.binding.run_id for run_work in run_works
        }
        return tuple(value.ref.model_dump(mode="json") for value in resolved.outputs)


def test_batched_run_failure_issue_followup_and_paired_outputs_keep_exact_run_identity(
    multi_work,
    monkeypatch,
):
    base = multi_work
    first = deepcopy(base.accepted_request["accepted_coverage"])
    second = [value for value in base.accepted_request["offered_coverage"] if value not in first]
    assert len(first) == len(second) == 1
    assert len({sample["lot_id"] for sample in base.samples}) == 2
    run_a = prepare_run(base, first, monkeypatch)
    accepted(base.quality, launch_command(run_a, "test.run.plan"))
    accepted(base.quality, launch_command(run_a, "verification.schedule.promise"))
    launch.advance_clock(run_a, monkeypatch)
    accepted(base.quality, launch_command(run_a, "test.run.start"))
    run_a.report_rows = measurement_rows(run_a)

    with ExitStack() as cleanup:
        # Existing fixture uploads/parses/captures raw 11.0000, imports its actual
        # final failure and installs the real fixed-result bridge and policy port.
        quality_fixture = quality.quality_work.__wrapped__(run_a)
        work = next(quality_fixture)
        cleanup.callback(quality_fixture.close)
        failed_a = results.current_rows(run_a)
        assert failed_a.run.result == "fail" and failed_a.request.status == "executing"
        assert failed_a.request.request_snapshot["timeline"]["final_result"] is None
        assert len(failed_a.run.coverage) == 1

        # This existing fixture creates one exact Issue, triages/contains it and
        # drafts two investigation actions using real API commands and originals.
        followup_fixture = followup.followup_work.__wrapped__(work)
        work = next(followup_fixture)
        cleanup.callback(followup_fixture.close)
        first_issue = followup.fixed_issue(work)
        assert first_issue.issue_snapshot["failures"][0]["run"]["id"] == str(run_a.binding.run_id)
        assert first_issue.issue_snapshot["failures"][0]["measurement_id"] == str(
            failed_a.run.measurements[0].id
        )
        assert first_issue.issue_snapshot["failures"][0]["sample"]["id"] == first[0]["sample_id"]
        created_receipt, _ = quality.create_issue(work, title="Same A failure delivered again")
        assert created_receipt["result"]["issue_id"] == str(work.issue_id)
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
        ) as session:
            assert session.scalar(select(func.count()).select_from(QualityFailureMap)) == 1

        # A's final output is paired while the whole Request is still executing.
        followup_view(work, failed_a.request)
        accepted(work.quality, followup.root_command(work))
        accepted(work.quality, followup.complete_command(work, (0,)))
        accepted(work.quality, followup.complete_command(work, (1,)))
        completed = followup.fixed_issue(work)
        assert completed.status == "awaiting_verification"
        assert completed.issue_snapshot["root_cause"] is not None
        assert all(action["completion"] for action in completed.issue_snapshot["capa"]["actions"])
        assert completed.issue_snapshot["capa"]["effectiveness"] is None
        assert completed.issue_snapshot["closure"] is None
        resolve_runs(work, run_a)

        accepted(
            work.quality,
            handoff.handoff(work, operation="verification.handoff.accept", coverage=second),
        )
        run_b = prepare_run(work, second, monkeypatch)
        accepted(work.quality, launch_command(run_b, "test.run.plan"))
        accepted(work.quality, launch_command(run_b, "verification.schedule.promise"))
        launch.advance_clock(run_b, monkeypatch)
        followup_view(work, results.current_rows(run_b).request)
        accepted(work.quality, launch_command(run_b, "test.run.start"))
        followup_view(work, results.current_rows(run_b).request)
        run_b.report_rows = measurement_rows(run_b)
        run_b.report_artifact = results.upload_report(run_b, run_b.report_rows)
        captured, _ = results.capture(run_b, (0,))
        accepted(
            work.quality,
            results.command(run_b, "test.results.import", captured=captured, final=True),
        )
        passed_b = results.current_rows(run_b)
        assert passed_b.run.result == "pass" and passed_b.request.status == "reported"
        assert results.current_rows(run_a).row.run_snapshot == failed_a.row.run_snapshot
        followup_view(work, passed_b.request)
        resolved = resolve_runs(work, run_a, run_b)
        assert len(resolved) == 2

        # Later sibling success cannot relabel the failure or create a new Issue.
        replay, _ = quality.create_issue(work, title="A failure after sibling B passed")
        assert replay["id"] == created_receipt["id"]
        assert followup.fixed_issue(work).issue_snapshot == completed.issue_snapshot
        assert (
            quality.listing(work)["current_by_issue"][str(work.issue_id)]["revision"]
            == completed.revision
        )
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
        ) as session:
            assert session.scalar(select(func.count()).select_from(QualityFailureMap)) == 1
            assert (
                session.get(VerificationRunVersion, failed_a.row.id).run_snapshot
                == failed_a.row.run_snapshot
            )

        # Both review actions retain the same Formal row. The enum omits that
        # ambiguous Formal while preserving the two explicit current Run options.
        for run_work in (run_a, run_b):
            accepted(work.quality, results.command(run_work, "test.run.review"))
        shared_formal = results.current_rows(run_b).request
        assert shared_formal.id == passed_b.request.id
        _, options = followup_view(work)
        expected_runs = resolve_runs(work, run_a, run_b)
        assert all(value in options for value in expected_runs)
        assert not any(
            value["kind"] == "verification_request" and value["id"] == str(shared_formal.id)
            for value in options
        )
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.quality.human,
            category_id=work.setup.category,
            read_snapshot=True,
        ) as session:
            basis = output_owner.load_followup_basis(
                session, work.quality.ctx, work.setup.product, work.issue_id, completed.revision
            )
            with pytest.raises(DomainError) as ambiguous:
                output_owner.resolve_followup_outputs(
                    session,
                    work.quality.ctx,
                    work.setup.product,
                    basis,
                    UUID(work.actions[0]["id"]),
                    [
                        OutputRef(
                            kind="verification_request",
                            id=shared_formal.id,
                            revision=shared_formal.revision,
                        )
                    ],
                )
            assert ambiguous.value.reason == "PAIR_CURRENT_MISSING_OR_AMBIGUOUS"

        # Continue the same sourced Issue/CAPA to a real change proposal and
        # impact capture. Unknown manufacturing/scope edges remain unresolved;
        # this does not claim an approved order, implementation or new retest.
        for kind in ("duty", "qualification"):
            import_authority(
                work,
                "quality",
                kind,
                subject_id=str(work.quality.human),
                operations=sorted(change_service.PAYLOADS),
                external_id=f"synthetic-multi-run-change-{work.issue_id}-{kind}",
            )
        work.issue_view = quality.issue_current(work, work.issue_id)
        _, _, change_id = change.created(work)
        captured_graph, _ = change.capture(work, change_id)
        graph = captured_graph["capture"]["graph"]
        nodes = [value["ref"] for value in graph["nodes"]]
        assert any(
            value["kind"] == "test_run"
            and value["id"] == str(run_a.binding.run_id)
            and value["revision"] == failed_a.run.revision
            for value in nodes
        )
        assert {value["kind"] for value in nodes} >= {
            "issue",
            "build",
            "sample",
            "test_run",
            "engineering_configuration",
            "manufacturing_configuration",
            "operation",
        }
        assert any(
            value["facet"] == "manufacturing" and value["status"] == "unknown"
            for value in graph["coverage"]
        )
        impact, _ = change.command(work, "change.impact.compute", captured_graph["impact_payload"])
        saved_impact = post(work.quality, impact)
        assert saved_impact.status_code == 200, saved_impact.text
        change_row, _ = change.current(work, change_id)
        request = change_row["request_snapshot"]
        assert request["status"] == "analysis" and request["orders"] == []
        assert request["assessments"][-1]["unknown"]
        assert followup.fixed_issue(work).issue_snapshot == completed.issue_snapshot
