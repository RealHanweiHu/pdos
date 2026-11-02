"""Actual partial Observation -> independent unknown T2 review; no efficacy/close."""

# ruff: noqa: F811 - explicit actual upstream fixture registration
from contextlib import ExitStack

import pytest

from . import approved_configuration_continuation_helpers as continuation
from . import formal_fulfillment_chain_helpers as fulfillment
from . import partial_observation_chain_helpers as partial
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
def test_partial_actual_observation_keeps_independent_named_review_unknown(
    quality_work, monkeypatch
):
    work = quality_work
    continuation_people(work)
    with ExitStack() as cleanup:
        fact = partial.prepare_partial_observation_entrance(work, cleanup)

        def observe_after_continuation(fixed, basis, implementations, engineering, manufacturing):
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
            candidate = partial.record_mapped_candidate(fixed, continued)
            rule_ref = fulfillment.publish_current_rule(fixed, continued)
            observation = partial.record_partial_observation(fixed, continued, rule_ref, cavity="A")
            review = partial.record_unknown_review(
                fixed, continued, candidate, rule_ref, observation
            )
            return observation, review

        observation, review = upstream.run_approved_configuration_implementations(
            work, after_issue=named_root_cause, continuation=observe_after_continuation
        )
        assert observation.fact.executor_id == work.retest_executor.human
        assert review.fact.reviewer_id == work.independent_reviewer.human
        assert review.fact.conclusion == "unknown"
