"""ISOLATED TEST ONLY: fabricated qualification originals, never real authority.

The real_business label and backdated timestamps here are deliberately fabricated
simulation inputs to exercise database binding guards. The empty cohort does NOT
pass the real evaluator. Tests must explicitly replace the trusted resolver to
exercise direct writing; no trigger is disabled and no real qualification exists.
"""

from collections.abc import Mapping
from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, select

from app.ai.issue_evaluation_publication import IssueEvaluationPublication
from app.db.schema import tables
from app.domain.ai_issue_trial_collections import summarize
from app.domain.product_workspace import _plain, digest
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from tests.test_issue_evaluation_publication import fixture_document


def insert_synthetic_qualification(
    c: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    policy: Mapping[str, Any],
    scope: Mapping[str, Any],
    actor_id: UUID,
    binding: dict[str, Any],
    sampling_basis_points: int = 10000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    registered = now - timedelta(days=4)
    start, end, as_of = now - timedelta(days=3), now - timedelta(days=2), now - timedelta(days=1)
    document = fixture_document()
    document.update(
        tenant_id=str(tenant_id),
        published_by=str(actor_id),
        published_at=(registered - timedelta(hours=1)).isoformat(),
        valid_from=registered.isoformat(),
        valid_until=(now + timedelta(days=2)).isoformat(),
    )
    entry = document["evaluations"][0]
    entry["golden_fixed_at"] = (registered - timedelta(days=2)).isoformat()
    entry["evaluation"].update(
        binding=deepcopy(binding),
        outcome="passed",
        completed_at=(registered - timedelta(hours=2)).isoformat(),
    )
    for call in entry["original_calls"]:
        call.update(
            tenant_id=str(tenant_id),
            binding=deepcopy(binding),
            started_at=(registered - timedelta(hours=4)).isoformat(),
            completed_at=(registered - timedelta(hours=3)).isoformat(),
        )
    # Contract-valid fixture structure is not a published operator file.
    publication = IssueEvaluationPublication.model_validate(document)
    published = dict(
        publication_sha256=digest(document),
        publication_id=str(publication.publication_id),
        published_at=publication.published_at.isoformat(),
        valid_from=publication.valid_from.isoformat(),
        valid_until=publication.valid_until.isoformat(),
        evaluation=publication.evaluations[0].evaluation.model_dump(mode="json"),
        qualification_granted=False,
    )
    identity, request = uuid4(), uuid4()
    settings = policy["operation_settings"]["event.issue.create"]
    protocol = _plain(
        dict(
            version="event-issue-trial-protocol-v1",
            id=identity,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_id,
            actor_name="隔离模拟登记人",
            created_at=registered,
            policy_id=policy["id"],
            principal_id=policy["principal_id"],
            scope_revision_id=scope["id"],
            binding_label="仅测试：合成资格结构",
            binding=binding,
            evaluation_publication=published,
            window_start=start,
            window_end=end,
            evidence_kind="real_business",
            configuration=dict(
                minimum_handled_runs=1,
                minimum_followup_seconds=1,
                sampling_basis_points=sampling_basis_points,
                confirmation_basis="retained_original",
                recovery_protocol_version="isolated-fixture.v1",
                recovery_conditions="仅模拟，不代表真实资格",
                fixed_at=registered,
                minimum_confirmation_basis_points=settings["minimum_confirmation_basis_points"],
                maximum_retraction_basis_points=settings["maximum_retraction_basis_points"],
            ),
            reason="隔离测试伪造受信事实，只验证数据库绑定，不授真实资格",
            qualification_granted=False,
            notice="ISOLATED SYNTHETIC FIXTURE; NOT REAL QUALIFICATION",
        )
    )
    protocol_digest = digest(protocol)
    payload: dict[str, Any] = dict(
        protocol_id=str(identity), protocol_digest=protocol_digest, evidence_kind="real_business"
    )
    writer = EventAuditWriter(c, tenant_id=tenant_id, project_id=project_id, actor_user_id=actor_id)
    event = writer.record(
        EventDraft(
            event_id=f"ai-issue-trial:{identity}",
            event_type="AI_ISSUE_TRIAL_REGISTERED",
            source="ai_issue_trial_service",
            entity_id=identity,
            occurred_at=registered,
            payload=payload,
        ),
        AuditDraft(action="ai_issue.trial_registered", after_snapshot=payload),
    )
    c.execute(
        tables.ai_issue_trial_protocols.insert().values(
            id=identity,
            tenant_id=tenant_id,
            project_id=project_id,
            actor_user_id=actor_id,
            request_id=request,
            request_digest=digest({"fixture_request": str(request)}),
            policy_id=policy["id"],
            principal_id=policy["principal_id"],
            scope_revision_id=scope["id"],
            window_start=start,
            window_end=end,
            evidence_kind="real_business",
            protocol=protocol,
            protocol_digest=protocol_digest,
            output_event_row_id=event.event_row_id,
            created_at=registered,
        )
    )
    collection_id, request = uuid4(), uuid4()
    collection = _plain(
        dict(
            version="event-issue-trial-collection-v1",
            id=collection_id,
            tenant_id=tenant_id,
            project_id=project_id,
            protocol_id=identity,
            protocol_digest=protocol_digest,
            actor_user_id=actor_id,
            actor_name="隔离模拟采集人",
            created_at=as_of,
            as_of=as_of,
            window_start=start,
            window_end=end,
            items=[],
            **summarize(protocol, [], as_of),
            notice="ISOLATED EMPTY FIXTURE; REAL EVALUATOR MUST NOT PASS",
        )
    )
    collection_digest = digest(collection)
    payload = dict(
        collection_id=str(collection_id),
        collection_digest=collection_digest,
        protocol_id=str(identity),
        total_runs=0,
    )
    event = writer.record(
        EventDraft(
            event_id=f"ai-issue-trial-collection:{collection_id}",
            event_type="AI_ISSUE_TRIAL_COLLECTED",
            source="ai_issue_trial_service",
            entity_id=collection_id,
            occurred_at=as_of,
            payload=payload,
        ),
        AuditDraft(action="ai_issue.trial_collected", after_snapshot=payload),
    )
    c.execute(
        tables.ai_issue_trial_collections.insert().values(
            id=collection_id,
            tenant_id=tenant_id,
            project_id=project_id,
            protocol_id=identity,
            actor_user_id=actor_id,
            request_id=request,
            request_digest=digest({"fixture_request": str(request)}),
            collection_digest=collection_digest,
            as_of=as_of,
            created_at=as_of,
            collection=collection,
            output_event_row_id=event.event_row_id,
        )
    )
    return protocol, collection
