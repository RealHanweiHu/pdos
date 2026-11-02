"""Same scope selection order is not a substantive T1 change."""

from pdos_next.domain.verification.handlers import VerificationHandler
from pdos_next.schemas.verification.contracts import HandoffOffer, RunPlan

from .helpers import coverage, event, sample, uid
from .test_handlers import accepted, prepared


def test_offer_preview_is_stable_when_samples_and_pairs_are_reordered(host):
    refs = (sample(), sample("sample-b", "B"))
    payload = HandoffOffer(samples=refs, coverage=coverage(samples=refs), at=event("offer"))
    reversed_payload = HandoffOffer(
        samples=refs[::-1], coverage=payload.coverage[::-1], at=payload.at
    )
    handler = VerificationHandler(host)
    before = handler.preview("verification.handoff.offer", uid("request"), 1, payload)
    after = handler.preview("verification.handoff.offer", uid("request"), 1, reversed_payload)
    assert before.digest == after.digest


def test_same_scope_reorder_can_consume_the_original_t1_proof(host):
    current = accepted(host)
    payload = RunPlan(run_id=uid("ordered-run"), coverage=current.acceptances[0].coverage)
    invocation, _ = prepared(host, "test.run.plan", current.id, current.revision, payload)
    reordered = RunPlan(run_id=payload.run_id, coverage=payload.coverage[::-1])
    result = VerificationHandler(host).execute(invocation, reordered)
    assert result.status == "planned"
