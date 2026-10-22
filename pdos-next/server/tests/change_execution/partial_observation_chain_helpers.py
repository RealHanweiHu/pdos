"""Actual partial Observation and unknown named review for the S3 continuation.

All original bytes, qualification, Current, paired and common-proof owners run.
No whole-window observation, positive applicability/effectiveness or close is
supplied. A rejected real preparation stays a failing, inspectable API response.
"""

from types import SimpleNamespace
from uuid import UUID

from build_start.test_transactions import import_authority
from quality_followup_transactions import fixtures as followup
from sqlalchemy import select
from test_project_first_plan import accepted, cmd

from pdos_next.contracts import Command
from pdos_next.domain.capa_effectiveness import (
    candidate_commands,
    candidate_storage,
    fact_commands,
    fact_service,
)
from pdos_next.domain.capa_effectiveness import service as candidates
from pdos_next.domain.capa_effectiveness.fact_atom_storage import read_fact_atom
from pdos_next.domain.capa_effectiveness.fact_registry_storage import read_stored_fact
from pdos_next.domain.capa_effectiveness.fact_storage_codec import assemble_fact
from pdos_next.domain.capa_effectiveness.fact_storage_models import (
    NamedReviewRecord,
    ObservationFact,
)
from pdos_next.domain.capa_verification.schemas import FailurePairMapping
from pdos_next.domain.quality_execution.evidence import union_sources
from pdos_next.domain.verification_results import service as results
from pdos_next.domain.verification_results.models import TestResultProjection as ResultProjection
from pdos_next.models import now
from pdos_next.schemas.quality_issues.contracts import Issue
from pdos_next.schemas.verification.contracts import VerificationRequest

from . import approved_configuration_helpers as approved
from . import formal_fulfillment_chain_helpers as fulfillment


def prepare_partial_observation_entrance(work, cleanup):
    """Keep the reviewer separate; register the actual Run executor as observer."""
    fact = fulfillment.prepare_reviewer_and_rule_publisher(work, cleanup)
    for kind in ("duty", "qualification"):
        import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.retest_executor.human),
            operations=[fact_commands.OBSERVATION_OPERATION],
            external_id=f"partial-observer-{work.build_id}-{work.retest_executor.human}-{kind}",
        )
    return fact


def record_mapped_candidate(work, continued):
    """Declare each fixed failure against actual new same-item pairs, still unknown."""
    reviewer = continued.independent_reviewer
    current = followup.fixed_issue(work)
    issue = Issue.model_validate(current.issue_snapshot)
    run = continued.final.run
    formal = VerificationRequest.model_validate(continued.final.request.request_snapshot)
    assert run.request_id == formal.id and run.scope == issue.scope
    with approved.session(work, reviewer) as stored:
        projections = stored.scalars(
            select(ResultProjection).where(
                ResultProjection.tenant_id == work.setup.tenant,
                ResultProjection.product_id == work.setup.product,
                ResultProjection.project_id == issue.scope.project_id,
                ResultProjection.run_id == run.id,
                ResultProjection.run_version_id == continued.final.row.id,
                ResultProjection.run_revision == run.revision,
                ResultProjection.basis_sha256 == results._basis_sha(run, continued.final.plan),
            )
        ).all()
        assert len(projections) == 1, "Need the exact current new Run's actual result projection"
        projection_id = projections[0].id
    samples = {sample.id: sample for sample in formal.samples}
    mappings = []
    for failure in issue.failures:
        matching = [m for m in run.measurements if m.coverage.item_id == failure.coverage.item_id]
        assert matching, "This scenario must explicitly retain the failed item's actual key"
        for measurement in matching:
            sample = samples[measurement.coverage.sample_id]
            mappings.append(
                FailurePairMapping(
                    failure_id=failure.identity,
                    run={
                        "kind": "verification_run",
                        "id": continued.final.row.id,
                        "revision": continued.final.row.revision,
                        "key": None,
                    },
                    sample_id=sample.id,
                    sample_revision=sample.revision,
                    actual_configuration_id=sample.actual_configuration.id,
                    actual_configuration_revision=sample.actual_configuration.revision,
                    item_id=measurement.coverage.item_id,
                    measurement_id=measurement.id,
                    projection_id=projection_id,
                )
            )
    declaration = approved.original(
        reviewer,
        {
            "nature": "synthetic",
            "issue_id": str(issue.id),
            "capa_id": str(issue.capa.id),
            "mapping_selections": [m.model_dump(mode="json") for m in mappings],
            "reason": (
                "Explicit candidate selection of the saved new same-item samples and raw readings; "
                "method applicability and day-long effectiveness remain undecided"
            ),
        },
        "Synthetic exact failure to new Run/sample/item mapping selections",
    )
    mappings = tuple(
        FailurePairMapping.model_validate(
            {**m.model_dump(mode="json"), "applicability_sources": [declaration.reference]}
        )
        for m in mappings
    )
    value = cmd(
        reviewer,
        candidate_commands.OPERATION,
        {
            "issue_id": str(issue.id),
            "expected_issue_revision": current.revision,
            "capa_id": str(issue.capa.id),
            "remediation_link_refs": [
                {"id": receipt["subject_id"], "revision": receipt["subject_revision"]}
                for receipt, _ in continued.followup_links
            ],
            "mappings": [m.model_dump(mode="json") for m in mappings],
            "sources": [declaration.reference],
            "visibility": current.visibility,
            "reason": "Retain actual new pairs with unknown applicability for partial review",
        },
    )
    with approved.session(work, reviewer) as stored:
        inputs = candidates.inputs(
            stored, reviewer.ctx, work.setup.product, Command.model_validate(value)
        )
    value["source_read_set"] = inputs["required_source_read_set"]
    receipt, _ = accepted(reviewer, value)
    with approved.session(work, reviewer) as stored:
        candidate = candidate_storage.read_candidate(
            stored,
            reviewer.ctx,
            work.setup.product,
            UUID(receipt["subject_id"]),
            semantic_owner=candidate_commands.semantic_owner(),
        )
        assert candidate.binding.mappings == mappings
    assert followup.fixed_issue(work).id == current.id
    return SimpleNamespace(receipt=receipt, ref=candidate.ref, mappings=mappings)


def current_rule(work, caller, ref):
    with approved.session(work, caller) as stored:
        fact = fact_service._runtime(stored).host.owner
        return fact._rule(stored, caller.ctx, work.setup.product, SimpleNamespace(rule=ref))[0]


def save_fact(work, caller, kind, payload):
    """Use actual inputs and shared T1/T2; preserve any real owner rejection."""
    operation = fact_commands.SPECS[kind][0]
    command = cmd(caller, operation, payload)
    url = f"/v1/categories/{caller.category}/products/{caller.product}/capa-facts/inputs"
    response = caller.client.post(url, headers=caller.headers, json=command)
    assert response.status_code == 200, f"Actual {kind} preparation rejected: {response.text}"
    preparation = response.json()
    receipt, submitted = accepted(caller, preparation["command"])
    model = ObservationFact if kind == "observation" else NamedReviewRecord
    with approved.session(work, caller) as stored:
        row = stored.get(model, UUID(receipt["subject_id"]))
        assert row is not None and row.revision == receipt["subject_revision"]
        atom = read_fact_atom(
            stored, caller.ctx, work.setup.product, kind=kind, fact_id=row.id, revision=row.revision
        )
        fact = assemble_fact(row.fact_body, atom.atom, expected_payload_sha256=row.payload_sha256)
        current = read_stored_fact(
            stored,
            caller.ctx,
            work.setup.product,
            kind,
            fact.ref,
            candidate_owner=candidate_storage.candidate_owner(candidate_commands.semantic_owner()),
        )
        assert current.fact == fact
        assert current.registry.state == (
            "current_registered" if kind == "observation" else "fixed_review"
        )
    assert fact.provenance.receipt_id == UUID(receipt["id"])
    assert fact.provenance.actor_id == caller.human
    assert fact.provenance.tier == fact_commands.SPECS[kind][1]
    return SimpleNamespace(
        fact=fact, receipt=receipt, command=submitted, preparation=preparation["review"]
    )


def record_partial_observation(work, continued, rule_ref, *, cavity="A"):
    """Report only the actual new Run interval and one declared sample's reading."""
    observer = continued.quality  # The genuine, separately qualified new Run executor.
    reviewer = continued.independent_reviewer
    assert observer.human == work.retest_executor.human != reviewer.human
    current = followup.fixed_issue(work)
    rule = current_rule(work, observer, rule_ref)
    run = continued.final.run
    assert run.execution.executor_id == observer.human
    samples = [sample for sample in run.samples if sample.cavity == cavity]
    assert len(samples) == 1, "Choose the explicitly declared synthetic sample cavity"
    sample = samples[0]
    targets = [
        target
        for target in rule.sampling.targets
        if target.ref.id == sample.id and target.ref.revision == sample.revision
    ]
    assert len(targets) == 1
    assert (targets[0].actual_configuration.id, targets[0].actual_configuration.revision) == (
        sample.actual_configuration.id,
        sample.actual_configuration.revision,
    )
    measurements = [m for m in run.measurements if m.coverage.sample_id == sample.id]
    assert len(measurements) == 1, "This synthetic scenario retains one actual dimensional reading"
    measurement = measurements[0]
    assert measurement.source is not None and measurement.observed_at is not None
    start, finish = run.actual_start.occurred_at, run.actual_end.occurred_at
    assert start <= measurement.observed_at <= finish < rule.sampling.observation_until
    assert start < finish <= now()
    at = now()
    record = {
        "target_key": targets[0].key,
        "occurred_at": measurement.observed_at.isoformat(),
        "original_timezone": measurement.observed_timezone,
        "raw_material": {
            "run": {"id": str(continued.final.row.id), "revision": continued.final.row.revision},
            "logical_run_id": str(run.id),
            "sample": sample.model_dump(mode="json"),
            "item_id": measurement.coverage.item_id,
            "measurement_id": str(measurement.id),
            "raw_value": measurement.raw_value,
            "unit": measurement.unit,
            "measurement_source": measurement.source.model_dump(mode="json"),
            "method": rule.method.model_dump(mode="json"),
            "criterion": rule.criterion.model_dump(mode="json"),
            "scope": "Actual new Run interval only; the full required day remains unobserved",
        },
    }
    original = approved.original(
        observer,
        {
            "schema_version": "pdos-capa-observation-source-v1",
            "nature": rule.nature,
            "scope": rule.scope.model_dump(mode="json"),
            "issue_id": str(work.issue_id),
            "capa_id": str(work.capa_id),
            "purpose": rule.purpose,
            "rule": rule.ref.model_dump(mode="json"),
            "record": record,
            "observed_from": start.isoformat(),
            "observed_until": finish.isoformat(),
            "at": {"occurred_at": at.isoformat(), "original_timezone": "UTC"},
        },
        "Synthetic executor's actual partial observation of new sample A",
    )
    coverage = union_sources((run.actual_start.source, run.actual_end.source, measurement.source))
    payload = {
        "issue_id": str(work.issue_id),
        "expected_issue_revision": current.revision,
        "capa_id": str(work.capa_id),
        "rule": rule.ref.model_dump(mode="json"),
        "target_keys": [targets[0].key],
        "observed_from": start.isoformat(),
        "observed_until": finish.isoformat(),
        "at": {
            "occurred_at": at.isoformat(),
            "original_timezone": "UTC",
            "source": original.source.model_dump(mode="json"),
        },
        "records": [{**record, "sources": [original.source.model_dump(mode="json")]}],
        "coverage_sources": [source.model_dump(mode="json") for source in coverage],
        "sources": [original.source.model_dump(mode="json")],
        "reason": "Record sample A Run interval only; remaining samples/day are explicit gaps",
        "visibility": current.visibility,
    }
    fact_commands.ObservationPayload.model_validate(payload)
    saved = save_fact(work, observer, "observation", payload)
    assert saved.fact.observed_from == start and saved.fact.observed_until == finish
    assert saved.fact.executor_id == observer.human
    assert saved.fact.records[0].raw_material == record["raw_material"]
    assert {"OBSERVATION_TARGETS_INCOMPLETE", "OBSERVATION_INTERVAL_INCOMPLETE"} <= set(
        saved.fact.sampling_material["missing"]
    )
    assert followup.fixed_issue(work).id == current.id
    return saved


def record_unknown_review(work, continued, candidate, rule_ref, observed):
    reviewer = continued.independent_reviewer
    current = followup.fixed_issue(work)
    rule = current_rule(work, reviewer, rule_ref)
    assert observed.fact.observed_until < rule.sampling.observation_until and now() < (
        rule.sampling.observation_until
    )
    at = now()
    reason = (
        "Unknown: the actual new Run reading is only a partial observation. "
        "The required day and remaining targets are incomplete; no effectiveness or close."
    )
    original = approved.original(
        reviewer,
        {
            "operation": fact_commands.REVIEW_OPERATION,
            "scope": rule.scope.model_dump(mode="json"),
            "issue_id": str(work.issue_id),
            "capa_id": str(work.capa_id),
            "candidate": candidate.ref.model_dump(mode="json"),
            "rule": rule.ref.model_dump(mode="json"),
            "observation": observed.fact.ref.model_dump(mode="json"),
            "reviewer_id": str(reviewer.human),
            "occurred_at": at.isoformat(),
            "conclusion": "unknown",
            "reason": reason,
        },
        "Synthetic independent named unknown review of partial observation",
    )
    pair_sources = union_sources((rule.method, rule.criterion, observed.fact.at.source))
    issue = Issue.model_validate(current.issue_snapshot)
    payload = {
        "issue_id": str(work.issue_id),
        "expected_issue_revision": current.revision,
        "capa_id": str(work.capa_id),
        "candidate": candidate.ref.model_dump(mode="json"),
        "rule": rule.ref.model_dump(mode="json"),
        "observations": [observed.fact.ref.model_dump(mode="json")],
        "at": {
            "occurred_at": at.isoformat(),
            "original_timezone": "UTC",
            "source": original.source.model_dump(mode="json"),
        },
        "pair_applicability": [
            {
                "mapping": mapping.model_dump(mode="json"),
                "method": rule.method.model_dump(mode="json"),
                "criterion": rule.criterion.model_dump(mode="json"),
                "conclusion": "unknown",
                "reason": "Mapping retained; partial observation leaves applicability unknown",
                "sources": [source.model_dump(mode="json") for source in pair_sources],
            }
            for mapping in candidate.mappings
        ],
        "action_fulfillment": [
            {
                "action_id": str(action.id),
                "conclusion": "unknown",
                "reason": "Completed action retained; independent effectiveness remains unknown",
                "sources": [
                    source.model_dump(mode="json") for source in action.completion.evidence
                ],
            }
            for action in issue.capa.actions
        ],
        "conclusion": "unknown",
        "sources": [original.source.model_dump(mode="json")],
        "reason": reason,
        "visibility": current.visibility,
    }
    fact_commands.NamedReviewPayload.model_validate(payload)
    saved = save_fact(work, reviewer, "review", payload)
    value = saved.fact
    assert value.conclusion == "unknown" and value.reviewer_id == reviewer.human
    assert value.candidate == candidate.ref and value.rule == rule.ref
    assert value.observations == (observed.fact.ref,)
    assert all(v.conclusion == "unknown" for v in value.pair_applicability)
    assert all(v.conclusion == "unknown" for v in value.action_fulfillment)
    assert reviewer.human not in {participant.id for participant in value.participants}
    assert {work.setup.human, work.quality.human, work.retest_executor.human} <= {
        participant.id for participant in value.participants
    }
    assert value.provenance.invocation_decision_id == value.provenance.proof_id
    assert value.provenance.consumed_at <= value.provenance.received_at
    assert saved.preparation["inspection"]["effectiveness"] == "indeterminate"
    after = followup.fixed_issue(work)
    assert (after.id, after.revision) == (current.id, current.revision)
    assert (
        after.issue_snapshot["capa"]["requirement"] == current.issue_snapshot["capa"]["requirement"]
    )
    assert after.issue_snapshot["capa"]["effectiveness"] is None
    assert after.issue_snapshot["closure"] is None
    return saved
