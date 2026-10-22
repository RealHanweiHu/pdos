"""Actual completed formal actions become readable fulfillment inputs only.

The original day-long observation requirement stays open. No efficacy review,
effectiveness decision, Issue close, qualification fallback or owner mock runs.
"""

# ruff: noqa: F811 - explicit actual upstream fixture registration
from contextlib import ExitStack

import pytest

from . import approved_configuration_continuation_helpers as continuation
from . import formal_fulfillment_chain_helpers as fulfillment
from . import test_approved_configuration_implementation_chain as upstream
from .test_approved_configuration_continuation_chain import continuation_people, named_root_cause
from .test_approved_configuration_implementation_chain import (  # noqa: F401
    accepted_work,
    known_configuration,
    launch_work,
    operational_work,
    quality_work,
    ready_work,
    results_work,
)


@pytest.mark.parametrize("launch_work", [{"window_minutes": 45, "fact_minutes": 60}], indirect=True)
def test_current_default_owner_reads_completed_approved_formal_actions(quality_work, monkeypatch):
    work = quality_work
    continuation_people(work)
    with ExitStack() as cleanup:
        fact = fulfillment.prepare_reviewer_and_rule_publisher(work, cleanup)

        def read_after_continuation(fixed, basis, implementations, engineering, manufacturing):
            continued = continuation.continue_after_implementations(
                fixed,
                basis,
                implementations,
                engineering,
                manufacturing,
                monkeypatch,
                cleanup=cleanup,
                executor=fixed.setup,
                test_executor=fixed.retest_executor,
                test_person_resource=fixed.retest_person_resource,
                independent_reviewer=fixed.independent_reviewer,
                raw_value="10.0000",
            )
            assert fixed.setup.engine._pdos_capa_fact_runtime.host.owner is fact
            candidate = fulfillment.record_current_candidate(fixed, continued)
            rule = fulfillment.publish_current_rule(fixed, continued)
            # Still inside upstream's coverage issuer and this live original/
            # resource ExitStack: no teardown proof is used as current evidence.
            return fulfillment.read_completed_fulfillment(fixed, continued, candidate, rule)

        values = upstream.run_approved_configuration_implementations(
            work, after_issue=named_root_cause, continuation=read_after_continuation
        )
        assert len(values) == 2 and all(v.conclusion == "applicable" for v in values)
