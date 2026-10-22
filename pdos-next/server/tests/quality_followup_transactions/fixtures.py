"""Real upstream failure/CAPA, native classification and uploaded completion facts.

No public registration, consumption, SQL constraint or authority gate is patched.
Root must integrate the three operations and same-transaction provenance first.
"""

# ruff: noqa: F811 - explicit imports register the upstream fixture dependency tree

import json
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from build_start.test_transactions import import_authority
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    create_issue,
    current_rows,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
    triage,
    unconsumed,
    upload_report,
)
from quality_execution.fixtures import command as quality_command
from sqlalchemy import func, select
from test_project_first_plan import accepted, cmd, post
from verification_handoff.fixtures import artifact

from pdos_next.command_handlers import T1_OPERATIONS, T2_OPERATIONS, handler
from pdos_next.contracts import PAYLOADS
from pdos_next.database import tenant_session
from pdos_next.domain.capa_verification.models import RemediationLinkRecord
from pdos_next.domain.professional_authority.service import OPERATION_ROLES
from pdos_next.domain.quality_execution.models import (
    QualityIssueCurrent,
    QualityIssueVersion,
    QualityPolicyCurrent,
    QualityPolicyFact,
)
from pdos_next.domain.quality_followup import service as followup
from pdos_next.domain.quality_followup.schemas import ExactSource
from pdos_next.domain.verification_results.models import MeasurementRecord, TestResultProjection
from pdos_next.models import Artifact, Audit, Confirmation, Outbox, Receipt, RequestKey, now
from pdos_next.quality_followup_bootstrap import disable_local_profile
from pdos_next.quality_followup_integration import configure_integration
from pdos_next.service import digest

LINK = "quality.capa.followup.link"
OPERATIONS = (followup.ROOT_CAUSE, followup.COMPLETE, LINK)
PATH = "quality-followup"


@pytest.fixture(autouse=True)
def followup_integration_contract():
    """Offline prerequisite guard, not a substitute for migration verification."""
    missing = []
    for operation in OPERATIONS:
        if operation not in PAYLOADS or handler(operation) is None:
            missing.append(f"shared PAYLOADS/handler: {operation}")
        if operation not in OPERATION_ROLES:
            missing.append(f"current professional operation matrix: {operation}")
    if followup.ROOT_CAUSE not in T2_OPERATIONS:
        missing.append("root cause is shared T2")
    if not {followup.COMPLETE, LINK} <= T1_OPERATIONS:
        missing.append("complete/link are shared T1")
    checks = " ".join(
        str(c.sqltext) for c in QualityIssueVersion.__table__.constraints if hasattr(c, "sqltext")
    )
    if any(value not in checks for value in (*OPERATIONS[:2], "awaiting_verification")):
        missing.append("public Issue CHECK permits followup operations/awaiting_verification")
    if missing:
        pytest.fail("Root integration required before PG candidates: " + "; ".join(missing))


def fixed_issue(work, revision=None):
    """Copy values inside the active Session; never return expired ORM rows."""
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        pointer = s.scalar(
            select(QualityIssueCurrent).where(
                QualityIssueCurrent.issue_id == work.issue_id,
                QualityIssueCurrent.product_id == work.setup.product,
            )
        )
        row = s.scalar(
            select(QualityIssueVersion).where(
                QualityIssueVersion.issue_id == work.issue_id,
                QualityIssueVersion.product_id == work.setup.product,
                QualityIssueVersion.revision == (revision or pointer.issue_revision),
            )
        )
        assert row is not None
        return SimpleNamespace(
            **{
                column.key: deepcopy(getattr(row, column.key, None))
                for column in row.__table__.columns
            },
            current_id=pointer.issue_version_id,
            current_revision=pointer.issue_revision,
        )


def exact_source(work, reference, *, line=1):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        row = s.get(Artifact, UUID(str(reference["artifact_id"])))
        raw = row.content.splitlines()[line - 1]
        return ExactSource(
            id=row.id,
            revision=row.revision,
            kind="artifact",
            position=f"line:{line};quote_sha256:{sha256(raw.encode()).hexdigest()}",
        )


def command(work, operation, payload):
    value = cmd(work.quality, operation, deepcopy(payload))
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/{PATH}/inputs",
        headers=work.quality.headers,
        json=value,
    )
    assert response.status_code == 200, response.text
    assert response.json()["allowed"] is True
    value["source_read_set"] = response.json()["required_source_read_set"]
    return value


def root_command(work):
    row = fixed_issue(work)
    return command(
        work,
        followup.ROOT_CAUSE,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": row.revision,
            "text": "Synthetic named investigation conclusion; no model decision.",
            "sources": [work.root_source.model_dump(mode="json")],
        },
    )


def complete_command(work, indices=(0,)):
    return command(
        work,
        followup.COMPLETE,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": fixed_issue(work).revision,
            "completions": [deepcopy(work.completions[index]) for index in indices],
        },
    )


def link_command(work):
    row = fixed_issue(work)
    return command(
        work,
        LINK,
        {
            "issue_id": str(work.issue_id),
            "expected_issue_revision": row.revision,
            "capa_id": str(work.capa_id),
            "action_id": work.actions[0]["id"],
            "output_refs": [{"kind": "build", "id": work.build_id, "revision": 1, "key": None}],
            "sources": [],
            "reason": "Fixed owner-created output link; not action fulfillment or efficacy.",
        },
    )


def counts(work):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        return {
            cls.__tablename__: s.scalar(select(func.count()).select_from(cls))
            for cls in (
                QualityIssueVersion,
                QualityIssueCurrent,
                RemediationLinkRecord,
                MeasurementRecord,
                TestResultProjection,
                QualityPolicyFact,
                QualityPolicyCurrent,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
            )
        }


def proof_row(work, prepared):
    token = prepared["payload"].get("approval_token") or prepared["payload"]["confirmation_token"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as s:
        row = s.scalar(select(Confirmation).where(Confirmation.token_hash == digest(token)))
        assert row is not None
        return SimpleNamespace(
            id=row.id,
            consumed=row.consumed,
            expires_at=row.expires_at,
            snapshot=deepcopy(row.snapshot),
        )


def no_effect(work, before, prepared, old_issue):
    assert counts(work) == before
    assert proof_row(work, prepared).consumed is False
    current = fixed_issue(work)
    assert (current.id, current.revision, current.issue_snapshot) == (
        old_issue.id,
        old_issue.revision,
        old_issue.issue_snapshot,
    )


@pytest.fixture
def followup_work(quality_work):
    work = quality_work
    # Separate series, before Issue creation: do not invalidate its authority basis.
    work.followup_authority = {
        kind: import_authority(
            work,
            "quality",
            kind,
            subject_id=str(work.quality.human),
            operations=list(OPERATIONS),
            external_id=f"synthetic-followup-{work.build_id}-{kind}",
            valid_from=(now() - timedelta(minutes=1)).isoformat(),
            valid_until=(now() + timedelta(hours=2)).isoformat(),
        )
        for kind in ("duty", "qualification")
    }
    publish_policy(work)
    created, _ = create_issue(work)
    work.issue_id = UUID(created["result"]["issue_id"])
    triage(work, created)
    accepted(
        work.quality,
        quality_command(
            work,
            "quality.issue.containment.record",
            {
                "issue_id": str(work.issue_id),
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
    work.capa_id = uuid4()
    work.actions = [
        {
            "id": str(uuid4()),
            "kind": "corrective",
            "text": f"Investigate fixed cause {index}",
            "executor_id": str(work.quality.human),
        }
        for index in range(2)
    ]
    response = post(
        work.quality,
        quality_command(
            work,
            "quality.capa.draft",
            {
                "issue_id": str(work.issue_id),
                "expected_issue_revision": 3,
                "capa_id": str(work.capa_id),
                "hypotheses": [
                    {
                        "text": "Synthetic hypothesis, not root cause.",
                        "sources": [work.hypothesis_source.model_dump(mode="json")],
                    }
                ],
                "actions": work.actions,
                "requirement": {
                    "method": "A separate owner-created verification Run",
                    "acceptance": "Exact affected pairs pass; current failure cannot be reused.",
                    "observation_until": (now() + timedelta(days=1)).isoformat(),
                    "required_failure_ids": [
                        f["identity"] for f in fixed_issue(work).issue_snapshot["failures"]
                    ],
                },
            },
        ),
    )
    assert response.status_code == 200, response.text
    work.root_source = work.hypothesis_source
    fixed = fixed_issue(work)
    assert fixed.revision == 4 and fixed.status == "actioning"
    # Actual completion clock is observed after the real CAPA draft commit.
    observed_at = now()
    work.completion_rows = [
        {
            "issue_id": str(work.issue_id),
            "capa_id": str(work.capa_id),
            "action_id": action["id"],
            "executor_id": str(work.quality.human),
            "operation": followup.COMPLETE,
            "occurred_at": observed_at.isoformat(),
            "original_timezone": "UTC",
            "purpose": fixed.purpose,
            "text": f"Personally investigated fixed cause {index}.",
        }
        for index, action in enumerate(work.actions)
    ]
    work.completion_artifact_id = upload_report(work, work.completion_rows)
    work.completions = []
    for index, observation in enumerate(work.completion_rows):
        ref = exact_source(work, {"artifact_id": str(work.completion_artifact_id)}, line=index + 1)
        work.completions.append(
            {
                "id": observation["action_id"],
                "text": observation["text"],
                "executor_id": observation["executor_id"],
                "evidence": [ref.model_dump(mode="json")],
                "at": {
                    "occurred_at": observation["occurred_at"],
                    "original_timezone": "UTC",
                    "source": ref.model_dump(mode="json"),
                },
            }
        )
    publications = [
        {
            "tenant_id": str(work.setup.tenant),
            "product_id": str(work.setup.product),
            "project_id": work.config["project"],
            "issue_id": str(work.issue_id),
            "capa_id": str(work.capa_id),
            "action_id": action["id"],
            "executor_id": str(work.quality.human),
            "purpose": fixed.purpose,
            "action_sha256": digest(action),
            "classification": "investigation",
            "nature": "synthetic",
            "valid_until": (now() + timedelta(hours=1)).isoformat(),
        }
        for action in work.actions
    ]
    classification = artifact(
        work.quality,
        "\n".join(json.dumps(p) for p in publications),
        "Controlled synthetic investigation classification",
    )
    work.classification_artifact_id = UUID(classification["artifact_id"])
    work.completion_profile = {
        "tenant_id": str(work.setup.tenant),
        "product_id": str(work.setup.product),
        "project_id": work.config["project"],
        "entries": [
            {
                **{
                    k: v
                    for k, v in item.items()
                    if k not in {"tenant_id", "product_id", "project_id"}
                },
                "source": exact_source(work, classification, line=index + 1).model_dump(
                    mode="json"
                ),
            }
            for index, item in enumerate(publications)
        ],
    }
    engine = work.setup.engine
    prior = {
        name: getattr(engine, name, None)
        for name in (
            "_pdos_quality_followup",
            "_pdos_capa_link_consumed_proof",
            "_pdos_quality_followup_views",
        )
    }
    configure_integration(engine, synthetic_completion_profile=work.completion_profile)
    work.followup_runtime = engine._pdos_quality_followup
    work.original_result = current_rows(work)
    try:
        yield work
    finally:
        disable_local_profile(
            engine,
            tenant_id=work.setup.tenant,
            product_id=work.setup.product,
            project_id=UUID(work.config["project"]),
        )
        for name, value in prior.items():
            if value is None:
                if hasattr(engine, name):
                    delattr(engine, name)
            else:
                setattr(engine, name, value)
