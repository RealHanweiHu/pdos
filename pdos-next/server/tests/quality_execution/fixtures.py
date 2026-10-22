"""Real synthetic originals/execution reused; only root executes PostgreSQL.

New quality-only credentials are issued after the old actual Start and fixed
result. They cannot authorize or rewrite that Start; retained proof rechecks its
original signer independently. The risk publication is a host-only synthetic
fact with a full exact JSON source, never a payload authorization boolean.
"""

# ruff: noqa: F811 - imported fixtures deliberately register their dependencies

import json
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post
from verification_handoff import fixtures as handoff
from verification_results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    current_rows,
    known_configuration,
    launch_work,
    operational_work,
    ready_work,
    results_work,
    upload_report,
)
from verification_results.fixtures import (
    command as result_command,
)

from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority.schemas import DefinitionReference
from pdos_next.domain.quality_execution import policy, service
from pdos_next.domain.quality_execution.evidence import refs_from_exact
from pdos_next.domain.quality_execution.models import (
    QualityEventFailureLink,
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
    QualityPolicyCurrent,
    QualityPolicyFact,
)
from pdos_next.domain.verification_results.models import MeasurementRecord
from pdos_next.models import Audit, Confirmation, Outbox, Receipt, now
from pdos_next.quality_result_bridge import (
    fixed_failure_result,
    fixed_failure_scope,
    read_failure_batch,
    recheck_fixed_failure_result,
)
from pdos_next.service import digest


@pytest.fixture
def quality_work(results_work):
    work = results_work
    original_rows = deepcopy(work.report_rows)
    for row in original_rows:
        # Deliberately beyond the fixed numeric upper 10.5; all metadata still
        # comes from the actual report and exactly matches the accepted plan.
        row["raw_value"] = "11.0000"
    work.failure_report = upload_report(work, original_rows)
    draft, _ = capture(work, tuple(range(len(original_rows))), artifact_id=work.failure_report)
    work.result_receipt, _ = accepted(
        work.quality, result_command(work, "test.results.import", captured=draft, final=True)
    )
    fixed = current_rows(work)
    assert fixed.run.result == "fail" and all(
        r.result == "fail" for r in fixed.run.computed_results
    )
    work.failure_run = fixed.run
    work.failure_run_version_id = fixed.row.id
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        work.failure_event = session.scalar(
            select(Outbox.id).where(Outbox.receipt_id == UUID(work.result_receipt["id"]))
        )
    assert work.failure_event is not None
    # Fit the closed operation limit with independent result and quality series.
    work.quality_authority = {
        kind: import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=sorted(service.PAYLOADS),
            external_id=f"synthetic-quality-{work.build_id}-{kind}",
            valid_from=(now() - timedelta(minutes=1)).isoformat(),
            valid_until=(now() + timedelta(hours=2)).isoformat(),
        )
        for kind in ("duty", "qualification")
    }
    engine = work.setup.engine
    previous = (
        getattr(engine, "_pdos_quality_result_bridge", None),
        getattr(engine, "_pdos_quality_result_refresh", None),
        getattr(engine, "_pdos_quality_result_scope", None),
        getattr(engine, "_pdos_quality_result_read_batch", None),
    )
    service.configure_result_bridge(
        engine,
        fixed_failure_result,
        refresh=recheck_fixed_failure_result,
        scope=fixed_failure_scope,
        read_batch=read_failure_batch,
    )
    work.policy_issuer = policy.configure_local_synthetic(
        engine,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        project_id=UUID(work.config["project"]),
        enabled=True,
        test_marker_verified=True,
        key=f"synthetic-quality-policy-{work.setup.product}",
    )
    try:
        yield work
    finally:
        service.configure_result_bridge(
            engine, previous[0], refresh=previous[1], scope=previous[2], read_batch=previous[3]
        )
        policy.disable_issuer(engine, work.policy_issuer.key)


def publish_policy(work, *, previous=None, risk="high", independent=True, state="active", key=None):
    from pdos_next.quality_policy_import import import_quality_policy_fact

    at = now()
    publication = {
        "external_id": "SYN-QUALITY-POLICY",
        "purpose": work.binding.purpose,
        "risk": risk,
        "independent_verification": independent,
        "state": state,
        "valid_from": (at - timedelta(minutes=1)).isoformat(),
        "valid_until": (at + timedelta(hours=1)).isoformat(),
        "approval": {
            "system": "Synthetic quality policy register",
            "external_id": "SYN-POLICY-APPROVAL",
            "version": "local-v1",
            "approved_by": "Synthetic named publication",
            "issued_at": (at - timedelta(minutes=1)).isoformat(),
        },
    }
    content = (
        json.dumps(publication)
        + "\nSynthetic containment observed by the named person."
        + "\nSynthetic hypothesis, not a root cause."
    )
    reference = handoff.artifact(work.quality, content, "Synthetic scoped risk policy")
    data = {
        "product_id": str(work.setup.product),
        "project_id": work.config["project"],
        **publication,
        "previous_id": previous["subject_id"] if previous else None,
        "expected_previous_revision": previous["subject_revision"] if previous else 0,
        "sources": [reference],
        "reason": "Explicit synthetic scoped policy publication",
    }
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        receipt = import_quality_policy_fact(
            session,
            work.quality.ctx,
            work.policy_issuer,
            data,
            request_key=key or str(uuid4()),
            command_id=uuid4(),
        )
        full = {**reference, "line": 2, "quote": content.splitlines()[1]}
        hypothesis = {**reference, "line": 3, "quote": content.splitlines()[2]}
        work.containment_source = refs_from_exact(
            session,
            work.quality.ctx,
            work.setup.product,
            [DefinitionReference.model_validate(full)],
        )[0]
        work.hypothesis_source = refs_from_exact(
            session,
            work.quality.ctx,
            work.setup.product,
            [DefinitionReference.model_validate(hypothesis)],
        )[0]
    work.policy_receipt, work.policy_input = receipt, data
    return receipt


def payload_create(work, index=0, *, event_id=None, title="Synthetic definite failure"):
    return {
        "run_id": str(work.failure_run.id),
        "measurement_id": str(work.failure_run.measurements[index].id),
        "event_id": str(event_id or work.failure_event),
        "title": title,
        "visibility": "private",
    }


def command(work, operation, payload):
    value = cmd(work.quality, operation, deepcopy(payload))
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution/inputs",
        headers=work.quality.headers,
        json=value,
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] is True
    value["source_read_set"] = response.json()["required_source_read_set"]
    return value


def create_issue(work, index=0, **changes):
    value = command(work, "quality.issue.create", payload_create(work, index, **changes))
    response = post(work.quality, value)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["subject_type"] == "quality_issue"
    return receipt, value


def listing(work):
    response = work.quality.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution",
        headers=work.quality.headers,
        params={"run_id": str(work.failure_run.id), "build_id": work.build_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def issue_current(work, issue_id):
    view = listing(work)
    pointer = view["current_by_issue"][str(issue_id)]
    return next(row for row in view["issues"] if row["id"] == pointer["issue_version_id"])


def counts(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        return {
            cls.__tablename__: session.scalar(select(func.count()).select_from(cls))
            for cls in (
                QualityIssueVersion,
                QualityIssueCurrent,
                QualityFailureMap,
                QualityEventFailureLink,
                QualityPolicyFact,
                QualityPolicyCurrent,
                MeasurementRecord,
                Receipt,
                Audit,
                Outbox,
            )
        }


def unconsumed(work, token):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert (
            session.scalar(
                select(Confirmation.consumed).where(Confirmation.token_hash == digest(token))
            )
            is False
        )


def triage(work, receipt):
    issue_id = receipt["result"]["issue_id"]
    value = command(
        work,
        "quality.issue.triage",
        {
            "issue_id": issue_id,
            "expected_issue_revision": 1,
            "reason": "Synthetic named triage, no root-cause decision",
        },
    )
    saved, prepared = accepted(work.quality, value)
    return saved, prepared


def draft_capa(work, receipt):
    """Current sourced Issue v1 -> real T1 triage/containment -> CAPA v4 draft."""
    issue_id = receipt["result"]["issue_id"]
    triage(work, receipt)
    contained, _ = accepted(
        work.quality,
        command(
            work,
            "quality.issue.containment.record",
            {
                "issue_id": issue_id,
                "expected_issue_revision": 2,
                "action": {
                    "id": str(uuid4()),
                    "text": "Synthetic containment observed by the named person.",
                    "executor_id": str(work.quality.human),
                    "evidence": [work.containment_source.model_dump(mode="json")],
                    "at": {
                        "occurred_at": now().isoformat(),
                        "original_timezone": "UTC",
                        "source": work.containment_source.model_dump(mode="json"),
                    },
                },
            },
        ),
    )
    assert contained["subject_revision"] == 3
    issue = issue_current(work, issue_id)
    capa_id = uuid4()
    response = post(
        work.quality,
        command(
            work,
            "quality.capa.draft",
            {
                "issue_id": issue_id,
                "expected_issue_revision": 3,
                "capa_id": str(capa_id),
                "hypotheses": [
                    {
                        "text": "Synthetic hypothesis, not a root cause.",
                        "sources": [work.hypothesis_source.model_dump(mode="json")],
                    }
                ],
                "actions": [
                    {
                        "id": str(uuid4()),
                        "kind": "corrective",
                        "text": "Planned investigation only",
                        "executor_id": str(work.quality.human),
                    }
                ],
                "requirement": {
                    "method": "Separate new verification run",
                    "acceptance": "Fixed affected pairs pass",
                    "observation_until": (now() + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [f["identity"] for f in issue["issue"]["failures"]],
                },
            },
        ),
    )
    assert response.status_code == 200, response.text
    return response.json(), issue_current(work, issue_id)


@pytest.fixture
def quality_capa_work(quality_work):
    work = quality_work
    publish_policy(work)
    receipt, _ = create_issue(work)
    work.issue_receipt, work.issue_view = draft_capa(work, receipt)
    work.issue_id = UUID(work.issue_view["issue_id"])
    work.capa_id = UUID(work.issue_view["issue"]["capa"]["id"])
    return work
