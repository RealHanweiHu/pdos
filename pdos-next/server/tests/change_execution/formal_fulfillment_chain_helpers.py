"""Real registered Rule and completed-action reads for the S3 continuation.

Only actual commands, trusted synthetic publication and current owner reads are
used. A future observation interval is retained; no Observation, named efficacy
review or Issue effectiveness/closure is created by these helpers.
"""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from build_start.test_transactions import import_authority
from quality_followup_transactions import fixtures as followup
from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd

from pdos_next.capa_applicability_owner import (
    ActualActionFulfillmentOwner,
    ActualApplicabilityOwner,
)
from pdos_next.capa_fact_owner import ActualFactOwner
from pdos_next.capa_rule_import import publish_rule
from pdos_next.capa_rule_publisher import configure_local_profile
from pdos_next.change_action_fulfillment_owner import ApprovedChangeActionFulfillmentOwner
from pdos_next.change_implementation_owner import digest as implementation_digest
from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness import (
    anchor_owner,
    candidate_commands,
    candidate_storage,
    fact_commands,
    fact_service,
)
from pdos_next.domain.capa_effectiveness import service as candidates
from pdos_next.domain.capa_effectiveness.fact_atom_storage import read_fact_atom
from pdos_next.domain.capa_effectiveness.fact_storage_codec import assemble_fact
from pdos_next.domain.capa_effectiveness.fact_storage_models import (
    NamedReviewRecord,
    ObservationFact,
    RuleFact,
)
from pdos_next.domain.capa_effectiveness.fact_write import prepare_fact
from pdos_next.domain.capa_effectiveness.named_review_owner import ActualNamedReviewOwner
from pdos_next.domain.capa_verification.models import CapaVerificationEvidence
from pdos_next.domain.quality_execution import policy
from pdos_next.domain.quality_execution.evidence import union_sources
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, now
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.schemas.verification.contracts import VerificationRequest

from . import approved_configuration_continuation_helpers as continuation
from . import approved_configuration_helpers as approved


def prepare_reviewer_and_rule_publisher(work, cleanup):
    """Register actual scope-bound qualifications/issuer before Issue/Change."""
    reviewer = work.independent_reviewer
    for kind in ("duty", "qualification"):
        import_authority(
            work,
            "quality",
            kind,
            subject_id=str(reviewer.human),
            operations=[
                candidate_commands.OPERATION,
                fact_commands.RULE_OPERATION,
                fact_commands.REVIEW_OPERATION,
            ],
            external_id=f"formal-fulfillment-{work.build_id}-{reviewer.human}-{kind}",
        )
    runtime = work.setup.engine._pdos_capa_fact_runtime
    fact = runtime.host.owner
    assert type(fact) is ActualFactOwner and type(fact.review_owner) is ActualNamedReviewOwner
    applicability = fact.review_owner.applicability_owner
    assert type(applicability) is ActualApplicabilityOwner
    assert type(applicability.action_owner) is ActualActionFulfillmentOwner
    implementation = applicability.action_owner.implementation_owner
    assert type(implementation) is ApprovedChangeActionFulfillmentOwner
    assert implementation.engine is work.setup.engine
    # Host configuration uses the actual registered local publisher. Restoring
    # its prior registry/publisher happens only after all live reads finish.
    missing = object()
    previous = {
        name: getattr(work.setup.engine, name, missing)
        for name in ("_pdos_capa_rule_issuers", "_pdos_capa_rule_issuer_epochs")
    }
    previous_publisher = fact.publisher

    def restore():
        fact.publisher = previous_publisher
        for name, value in previous.items():
            if value is missing:
                if hasattr(work.setup.engine, name):
                    delattr(work.setup.engine, name)
            else:
                setattr(work.setup.engine, name, value)

    cleanup.callback(restore)
    fact.publisher = configure_local_profile(
        work.setup.engine,
        {
            "tenant_id": str(work.setup.tenant),
            "product_id": str(work.setup.product),
            "project_id": work.config["project"],
            "issuer_key": f"formal-fulfillment-rule-{work.build_id}",
            "issuer_version": "synthetic-v1",
        },
    )
    return fact


def record_current_candidate(work, continued):
    reviewer = continued.independent_reviewer
    current = followup.fixed_issue(work)
    value = cmd(
        reviewer,
        candidate_commands.OPERATION,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": current.revision,
            "capa_id": str(work.capa_id),
            "visibility": current.visibility,
            "reason": (
                "Retain the actual completed anchor for action-fulfillment reading only; "
                "failure mapping and independent effectiveness remain incomplete"
            ),
        },
    )
    with approved.session(work, reviewer) as stored:
        inputs = candidates.inputs(
            stored, reviewer.ctx, work.setup.product, Command.model_validate(value)
        )
    value["source_read_set"] = inputs["required_source_read_set"]
    receipt, _ = accepted(reviewer, value)
    assert receipt["subject_type"] == "capa_verification_candidate"
    assert followup.fixed_issue(work).id == current.id
    return receipt


def publish_current_rule(work, continued):
    """Publish declared future sampling, preserving the actual one-day requirement."""
    reviewer = continued.independent_reviewer
    current = followup.fixed_issue(work)
    issue = Issue.model_validate(current.issue_snapshot)
    latest_completion = max(a.completion.at.occurred_at for a in issue.capa.actions)
    assert latest_completion < issue.capa.requirement.observation_until
    request = VerificationRequest.model_validate(continued.final.request.request_snapshot)
    samples = request.samples
    selected = approved.original(
        reviewer,
        {
            "nature": "synthetic",
            "scope": issue.scope.model_dump(mode="json"),
            "issue_id": str(issue.id),
            "capa_id": str(issue.capa.id),
            "new_build_id": continued.build_id,
            "saved_new_run_version_id": str(continued.final.row.id),
            "samples": [sample.model_dump(mode="json") for sample in samples],
            "instruction": (
                "Select these actual saved new samples for future observation; "
                "no observation completeness or effectiveness is asserted"
            ),
        },
        "Synthetic future observation targets from actual new sample identities",
    )
    item = continued.final.run.items[0]
    method = item.method
    criterion = item.criterion.source if item.criterion is not None else item.criterion_source
    assert method is not None and criterion is not None
    with approved.session(work, reviewer) as stored:
        runtime = fact_service._runtime(stored)
        policy_source = policy.assess(
            stored, reviewer.ctx, work.setup.product, issue.scope.project_id, current.purpose
        )["sources"][0]
    at = now()
    payload = {
        "issue_id": str(issue.id),
        "expected_issue_revision": current.revision,
        "capa_id": str(issue.capa.id),
        "origin": {
            "id": str(current.id),
            "revision": current.revision,
            "snapshot_sha256": current.snapshot_sha256,
        },
        "external_id": f"formal-fulfillment-{issue.id}",
        "policy_ref": policy_source,
        "method": method.model_dump(mode="json"),
        "criterion": criterion.model_dump(mode="json"),
        "sampling": {
            "targets": [
                {
                    "key": f"new-sample-{sample.id}",
                    "kind": "sample",
                    "ref": {"id": str(sample.id), "revision": sample.revision},
                    "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
                    "identity_sources": [selected.source.model_dump(mode="json")],
                }
                for sample in samples
            ],
            "minimum_records": 1,
            "sampling_method": method.model_dump(mode="json"),
            "acceptance": criterion.model_dump(mode="json"),
            "observation_from": latest_completion.isoformat(),
            "observation_until": issue.capa.requirement.observation_until.isoformat(),
            "require_named_review": True,
            "require_run_review": False,
            "require_disposition": False,
        },
        "rule_material": {
            "purpose": "Read actual completed formal actions; future observation remains open",
            "observation_requirement": issue.capa.requirement.model_dump(mode="json"),
        },
        "independence_material": {
            "required": True,
            "reviewer_id": str(reviewer.human),
            "action_executor_id": str(work.setup.human),
            "test_executor_id": str(work.retest_executor.human),
        },
        "valid_from": (at - timedelta(seconds=1)).isoformat(),
        "valid_until": (issue.capa.requirement.observation_until + timedelta(hours=1)).isoformat(),
        "reason": "Controlled synthetic rule; future observation and efficacy remain pending",
        "visibility": current.visibility,
        "sources": [selected.source.model_dump(mode="json")],
    }
    checked = fact_commands.RulePublicationInput.model_validate(payload)
    fields = {
        "origin",
        "previous",
        "external_id",
        "policy_ref",
        "method",
        "criterion",
        "sampling",
        "rule_material",
        "independence_material",
        "valid_from",
        "valid_until",
        "visibility",
    }
    publication = approved.original(
        reviewer,
        {
            "schema_version": "pdos-capa-rule-publication-source-v1",
            "nature": "synthetic",
            "scope": issue.scope.model_dump(mode="json"),
            "issue_id": str(issue.id),
            "capa_id": str(issue.capa.id),
            "purpose": current.purpose,
            "material": checked.model_dump(mode="json", include=fields),
        },
        "Synthetic controlled future observation Rule original",
    )
    payload["sources"] = [
        source.model_dump(mode="json")
        for source in union_sources(
            (selected.source, publication.source, method, criterion), (policy_source,)
        )
    ]
    value = cmd(reviewer, fact_commands.RULE_OPERATION, payload)
    with approved.session(work, reviewer) as stored:
        checked = fact_commands.RulePublicationInput.model_validate(payload)
        prepared = prepare_fact(
            stored, reviewer.ctx, work.setup.product, checked, host=runtime.host, new_write=True
        )
        try:
            value["source_read_set"] = [
                read.model_dump(mode="json") for read in prepared.required_source_read_set
            ]
        finally:
            fact_service._discard(runtime, prepared)
    with approved.session(work, reviewer) as stored:
        receipt = publish_rule(
            stored,
            reviewer.ctx,
            Command.model_validate(value),
            publisher=runtime.host.owner.publisher,
        )
        row = stored.get(RuleFact, UUID(receipt["subject_id"]))
        atom = read_fact_atom(
            stored,
            reviewer.ctx,
            work.setup.product,
            kind="rule",
            fact_id=row.id,
            revision=row.revision,
        )
        rule = assemble_fact(row.fact_body, atom.atom, expected_payload_sha256=row.payload_sha256)
    assert rule.sampling.observation_until == issue.capa.requirement.observation_until
    assert rule.sampling.observation_until > now()
    return rule.ref


def read_state(work, reviewer):
    with approved.session(work, reviewer) as stored:
        pointer = stored.scalar(
            select(QualityIssueCurrent).where(QualityIssueCurrent.issue_id == work.issue_id)
        )
        return (
            (pointer.id, pointer.issue_version_id, pointer.issue_revision, pointer.epoch),
            {
                model.__tablename__: stored.scalar(select(func.count()).select_from(model))
                for model in (
                    QualityIssueVersion,
                    CapaVerificationEvidence,
                    RuleFact,
                    ObservationFact,
                    NamedReviewRecord,
                    Receipt,
                    Confirmation,
                    Audit,
                    Outbox,
                )
            },
        )


def read_completed_fulfillment(work, continued, candidate_receipt, rule_ref):
    reviewer = continued.independent_reviewer
    before = read_state(work, reviewer)
    current = followup.fixed_issue(work)
    assessments = {v["action_id"]: v for v in current.source_basis["completion_assessments"]}
    # Obtain the exact original locator using the existing executor-bound
    # capture helper before opening the reviewer's independent owner UOW. Every
    # actual fulfillment/source/authority read below keeps the real reviewer.
    occurrences = tuple(
        (
            receipt,
            occurrence,
            continuation._implementation_source(work, work.setup, receipt, occurrence),
        )
        for receipt, occurrence in continued.completion.implementations
    )
    values = []
    with approved.session(work, reviewer) as stored:
        fact = fact_service._runtime(stored).host.owner
        reader = fact.review_owner.applicability_owner.action_owner
        rule, saved = fact._rule(
            stored, reviewer.ctx, work.setup.product, SimpleNamespace(rule=rule_ref)
        )
        fresh = anchor_owner.read_anchor_from_actual_owner(
            stored, reviewer.ctx, work.setup.product, work.issue_id, saved.origin.ref
        )
        assert fresh.needs_lineage_owner is False
        assert fresh.origin_descriptor.current.ref == saved.origin.ref
        assert fresh.original_failure_bytes_verified is True
        assert fact._anchor(stored, reviewer.ctx, work.setup.product, saved) == saved.origin.ref
        candidate = candidate_storage.read_candidate(
            stored,
            reviewer.ctx,
            work.setup.product,
            UUID(candidate_receipt["subject_id"]),
            semantic_owner=candidate_commands.semantic_owner(),
        )
        assert candidate.body.stable_anchor.origin.ref == saved.origin.ref
        for receipt, occurrence, source in occurrences:
            selected = fact_commands.ActionReviewInput(
                action_id=occurrence.action_id,
                conclusion="applicable",
                reason="Read exact actual saved approved implementation and executor completion",
                sources=(source.model_dump(mode="json"),),
            )
            kwargs = dict(anchor=saved, candidate=candidate, rule=rule, observations=())
            actual = reader.read(stored, reviewer.ctx, work.setup.product, selected, **kwargs)
            late = reader.refresh(
                stored, reviewer.ctx, work.setup.product, selected, actual, **kwargs
            )
            assert actual.value == late.value and actual.owner_material == late.owner_material
            assert actual.value.classification == "formal_change"
            assert actual.value.conclusion == "applicable"
            assert "CURRENT_ACTION_CLASSIFICATION_OWNER_REQUIRED" not in actual.missing
            assert actual.value.action.action_id == occurrence.action_id
            assert actual.value.action.executor_id == occurrence.executor_id != reviewer.human
            material = actual.owner_material["fulfillment"]
            assert material["kind"] == "approved_change_action_fulfillment_v1"
            assert len(material["items"]) == 1
            proof = assessments[str(occurrence.action_id)]["owner_proofs"][0]
            assert (proof["id"], proof["revision"], proof["receipt_id"]) == (
                receipt["subject_id"],
                receipt["subject_revision"],
                receipt["id"],
            )
            assert proof["sha256"] == implementation_digest(material["items"][0]["implementation"])
            values.append(actual.value)
    assert read_state(work, reviewer) == before
    assert {v.action.action_id for v in values} == {
        occurrence.action_id for _, occurrence in continued.completion.implementations
    }
    after = followup.fixed_issue(work)
    assert (after.id, after.revision) == (current.id, current.revision)
    assert (
        after.issue_snapshot["capa"]["requirement"] == current.issue_snapshot["capa"]["requirement"]
    )
    assert after.issue_snapshot["capa"]["effectiveness"] is None
    assert after.issue_snapshot["closure"] is None
    return tuple(values)
