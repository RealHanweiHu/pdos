"""Actual approved outputs continue into completion and a separate test Run.

The new measurement is an explicit synthetic observation. No observation clock,
effectiveness decision, release or Issue closure is supplied by this scenario.
"""

# ruff: noqa: F811 - imported fixtures register the actual upstream owner tree
import secrets
from contextlib import ExitStack
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from build_start.test_transactions import import_authority
from quality_execution import fixtures as quality
from quality_followup_transactions import fixtures as followup
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, post
from verification_handoff import fixtures as handoff
from verification_launch import fixtures as launch
from verification_results import fixtures as results

from pdos_next.domain.build_operational_facts.schemas import ResourceInput
from pdos_next.domain.capa_verification import service as verification
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.domain.quality_followup import service as actions
from pdos_next.domain.verification_results import service as result_owner
from pdos_next.engines.planning.calendar import frozen_timezone
from pdos_next.models import Grant, LoginSession, Principal, now
from pdos_next.service import digest

from . import approved_configuration_continuation_helpers as next_round
from . import approved_configuration_helpers as helper
from . import test_approved_configuration_implementation_chain as upstream
from .test_approved_configuration_implementation_chain import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)


def new_person(work, name):
    identity, token = uuid4(), secrets.token_urlsafe(32)
    with Session(work.setup.admin) as stored, stored.begin():
        stored.add(Principal(id=identity, tenant_id=work.setup.tenant, name=name, kind="human"))
        stored.flush()
        stored.add(
            Grant(
                tenant_id=work.setup.tenant,
                category_id=work.setup.category,
                principal_id=identity,
                can_write=True,
                expires_at=now() + (getattr(work.setup, "test_authorization_window", None)
                                    or timedelta(hours=1)),
            )
        )
        stored.add(
            LoginSession(
                tenant_id=work.setup.tenant,
                principal_id=identity,
                token_hash=digest(token),
                expires_at=now() + (getattr(work.setup, "test_authorization_window", None)
                                    or timedelta(hours=1)),
            )
        )
    return handoff.caller(work.setup, identity, token)


def continuation_people(work):
    """Actual finite qualifications precede Issue and every retained signer."""
    work.retest_executor = new_person(work, "Synthetic separate test executor")
    work.independent_reviewer = new_person(work, "Synthetic independent future reviewer")
    assert (
        len(
            {
                work.setup.human,
                work.quality.human,
                work.engineer.human,
                work.retest_executor.human,
                work.independent_reviewer.human,
            }
        )
        == 5
    )
    for person, operations in (
        (work.quality, (actions.ROOT_CAUSE, "quality.capa.followup.link")),
        (work.setup, (actions.COMPLETE,)),
        (work.retest_executor, (*launch.OPERATIONS, *sorted(result_owner.PAYLOADS))),
    ):
        for kind in ("duty", "qualification"):
            import_authority(
                work,
                "quality",
                kind,
                subject_id=str(person.human),
                operations=list(operations),
                external_id=f"synthetic-continuation-{work.build_id}-{person.human}-{kind}",
            )
    # A physical declaration has its own actual original. The new Run's trusted
    # resource import creates the mirror; no existing capacity/occupancy changes.
    physical = {
        "resource": {"id": str(work.retest_executor.human), "revision": 1, "kind": "person"},
        "lifecycle": "active",
        "capacity": "1",
        "calendar": {
            "calendar_id": f"SYN-RETEST-{work.retest_executor.human}",
            "version": "1",
            "timezone": "UTC",
            "timezone_rules_sha256": frozen_timezone("UTC")[1],
            "weekly": [
                {"weekday": day, "intervals": [{"start_minute": 0, "end_minute": 1440}]}
                for day in range(7)
            ],
        },
        "maintenance": [],
        "external_occupancies": [],
        "external_occupancies_complete": True,
    }
    original = helper.original(
        work.setup, physical, "Synthetic new test executor physical capacity declaration"
    )
    work.retest_person_resource = ResourceInput.model_validate(
        {
            **physical,
            "purposes": [work.binding.purpose],
            "operation_ids": ["test.run.start"],
            "facts": [],
            "sources": [original.reference],
            "calendar_sources": [original.reference],
        }
    )


def named_root_cause(work, basis):
    """A real T2 conclusion is saved before Change freezes this Issue version."""
    original = helper.original(
        work.quality,
        {
            "issue_id": str(work.issue_id),
            "capa_id": str(work.capa_id),
            "text": (
                "Explicit synthetic investigation attributes the fixed failed dimension to "
                "the original mount design and assembly alignment. Separate configuration "
                "actions and a new Run are still required; effectiveness is undecided."
            ),
            "nature": "synthetic",
        },
        "Synthetic named root-cause investigation original",
    )
    work.root_source = original.source
    work.root_receipt, work.root_command = accepted(work.quality, followup.root_command(work))
    work.issue_view = quality.issue_current(work, work.issue_id)
    conclusion = work.issue_view["issue"]["root_cause"]
    assert conclusion["actor_id"] == str(work.quality.human)
    assert conclusion["sources"] == [original.source.model_dump(mode="json")]
    with helper.session(work) as stored:
        current = verification.load_followup_basis(
            stored, work.quality.ctx, work.setup.product, work.issue_id, work.issue_view["revision"]
        )
    assert current.capa_id == basis.capa_id and current.actions == basis.actions
    return current


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_completed_approved_actions_create_new_actual_build_samples_request_and_run(
    quality_work, monkeypatch
):
    work = quality_work
    continuation_people(work)
    original_failure = deepcopy(work.failure_run.model_dump(mode="json"))
    original_result_id = work.failure_run_version_id
    with ExitStack() as cleanup:

        def continue_round(fixed, basis, implementations, engineering, manufacturing):
            return next_round.continue_after_implementations(
                fixed,
                basis,
                implementations,
                engineering,
                manufacturing,
                monkeypatch,
                cleanup=cleanup,
                executor=fixed.setup,
                test_executor=fixed.retest_executor,
                independent_reviewer=fixed.independent_reviewer,
                test_person_resource=fixed.retest_person_resource,
                raw_value="10.0000",
            )

        continued = upstream.run_approved_configuration_implementations(
            work, after_issue=named_root_cause, continuation=continue_round
        )
        assert continued.build_id != work.build_id
        assert continued.request_id != work.request_id
        assert continued.binding.run_id != work.binding.run_id
        assert {row["id"] for row in continued.samples}.isdisjoint(
            row["id"] for row in work.samples
        )
        assert continued.final.run.result == "pass"
        assert all(value.result == "pass" for value in continued.final.run.computed_results)
        assert continued.final.run.execution.executor_id == work.retest_executor.human
        assert work.failure_run.model_dump(mode="json") == original_failure
        fixed_original = results.current_rows(work)
        assert fixed_original.row.id == original_result_id
        assert fixed_original.run.model_dump(mode="json") == original_failure
        current = followup.fixed_issue(work)
        assert current.status == "awaiting_verification"
        assert current.issue_snapshot["capa"]["effectiveness"] is None
        assert current.issue_snapshot["closure"] is None
        assert all(
            row["completion"] is not None for row in current.issue_snapshot["capa"]["actions"]
        )
        with helper.session(work) as stored:
            links = stored.scalars(
                select(RemediationLinkRecord).where(RemediationLinkRecord.issue_id == work.issue_id)
            ).all()
            assert len(links) == 2
            for link in links:
                assert {row["id"] for row in link.input_snapshot["output_refs"]} == {
                    continued.build_id,
                    str(continued.final.row.id),
                }
        before = followup.counts(work)
        for caller, command, receipt in (
            (work.quality, work.root_command, work.root_receipt),
            (work.setup, continued.completion.command, continued.completion.receipt),
            *((work.quality, command, receipt) for receipt, command in continued.followup_links),
        ):
            response = post(caller, command)
            assert response.status_code == 200 and response.json()["id"] == receipt["id"]
        assert followup.counts(work) == before
