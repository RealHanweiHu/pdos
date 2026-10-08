"""Extra checks for historical observations and mixed synthetic/real scope."""

from datetime import timedelta

import pytest

from pdos_next.domain.quality_issues.ports import VerifiedRun
from pdos_next.domain.quality_issues.rules import failure_ref, replace, semantic_digest
from pdos_next.schemas.quality_issues.contracts import EffectivenessDecide

from .helpers import NOW, Harness, fixed_run, uid
from .test_quality_issues import assert_domain


@pytest.mark.parametrize(
    "case", ["before_start", "after_end", "missing_end", "missing_return", "end_after_return"]
)
def test_failure_requires_consistent_actual_timeline(case):
    run = fixed_run()
    if case == "before_start":
        run = replace(run, actual_start=replace(run.actual_start, occurred_at=NOW))
    elif case == "after_end":
        run = replace(run, measurements=(replace(run.measurements[0], observed_at=NOW),))
    elif case == "missing_end":
        run = replace(run, actual_end=None)
    elif case == "missing_return":
        run = replace(run, final_result=None)
    else:
        run = replace(
            run, final_result=replace(run.final_result, occurred_at=NOW - timedelta(hours=2))
        )
    assert_domain(
        "FAILURE_CONTEXT_MISSING",
        lambda: failure_ref(VerifiedRun(run=run, nature="synthetic"), run.measurements[0].id),
    )


def test_real_evidence_cannot_cover_synthetic_member_of_mixed_issue():
    h = Harness()
    iid = h.ready()
    issue = h.issue(iid)
    synthetic = issue.failures[0]
    real = replace(synthetic, identity="second-real-failure", nature="real")
    requirement = replace(
        issue.capa.requirement, required_failure_ids=(synthetic.identity, real.identity)
    )
    h.commands.issues[iid] = replace(
        issue, failures=(synthetic, real), capa=replace(issue.capa, requirement=requirement)
    )
    eid = uid("verification")
    h.policies.evidence[eid] = replace(
        h.policies.evidence[eid],
        nature="real",
        failure_ids=(synthetic.identity, real.identity),
        requirement_digest=semantic_digest(requirement),
    )
    payload = EffectivenessDecide(
        result="effective", text="Synthetic negative case", evidence_ids=(eid,)
    )
    assert_domain(
        "INVALID_VERIFICATION",
        lambda: h.call("quality.capa.effectiveness.decide", iid, h.issue(iid).revision, payload),
    )


def test_partial_run_adapter_fails_explicitly_instead_of_runtime_attribute_error():
    h = Harness()
    h.handler.ports.runs = object()
    assert_domain("INTEGRATION_REQUIRED", h.create)
