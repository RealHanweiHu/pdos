"""Actual Chat collector observations and admitted application context revisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select

from app.ai.application_authorization import verify_application_authorization
from app.ai.budget_ledger import BudgetLedgerError
from app.ai.context_projection import PROJECT_GATEWAY_POLICY, project_gateway_context
from app.ai.observations import context_receipt_body, digest
from app.contracts.runtime_records import ContextManifest, Observation
from app.db.schema import tables


def chat_bundle(*, work_focus: bool = False) -> dict[str, Any]:
    from hashlib import sha256

    from app.ai.chat import CHAT_PROMPT, ChatAssessment

    root = Path(__file__).resolve().parents[3]
    paths = sorted((root / "server/app").rglob("*.py"))
    paths += sorted((root / "server/app/ai/prompts").glob("*.json"))
    paths += sorted((root / "server/migrations/versions").glob("*.py"))
    paths += sorted((root / "infra/postgres/security").glob("*.sql"))
    compiled = dict(
        prompt=CHAT_PROMPT.model_dump(mode="json"),
        schema=ChatAssessment.model_json_schema(),
        projection=PROJECT_GATEWAY_POLICY,
        model_tools=[],
        reader="work-card-evidence-collector.v1" if work_focus else "chat-evidence-collector.v1",
        attachment_reader="conversation-attachment-reader.v1",
    )
    return cast(
        dict[str, Any],
        json.loads(
            json.dumps(
                dict(
                    version="application-chat-object-bundle.v1"
                    if work_focus
                    else "application-chat-bundle.v1",
                    compiled=compiled,
                    source_sha256={
                        str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in paths
                    },
                )
            )
        ),
    )


def require_new_context_history(
    connection: Connection, tenant_id: UUID, run_id: UUID, *, call_id: UUID | None = None
) -> None:
    for table in (tables.model_invocations, tables.budget_journal, tables.model_call_sessions):
        call_filter = []
        if call_id is not None:
            call_filter = [
                table.c.budget_call_id == call_id
                if table is tables.model_invocations
                else table.c.request_binding["model_call_id"].as_string() == str(call_id)
                if table is tables.budget_journal
                else table.c.id == call_id
            ]
        if (
            connection.execute(
                select(table.c.id)
                .where(table.c.tenant_id == tenant_id, table.c.run_id == run_id, *call_filter)
                .limit(1)
            ).first()
            is not None
        ):
            raise BudgetLedgerError("APPLICATION_CONTEXT_HISTORY_UNAVAILABLE")


def record_chat_context(
    engine: Engine,
    *,
    tenant_id: UUID,
    project_id: UUID,
    run_id: UUID,
    model_call_id: UUID,
    question: str,
    evidence: tuple[Any, ...],
) -> None:
    from app.ai.chat import CHAT_PROMPT, ChatAssessment

    with engine.connect() as c:
        auth = (
            c.execute(
                select(tables.application_authorizations).where(
                    tables.application_authorizations.c.tenant_id == tenant_id,
                    tables.application_authorizations.c.run_id == run_id,
                )
            )
            .mappings()
            .one_or_none()
        )
    if auth is None:
        return
    verify_application_authorization(
        engine, tenant_id=tenant_id, run_id=run_id, project_id=project_id, agent_key="ai_chat"
    )
    attachment_sources = [item for item in evidence if item.entity == "conversation_attachment"]
    work_sources = [item for item in evidence if item.reference_id.startswith("work-card:")]
    partial_sources = [*attachment_sources, *work_sources]
    output = [item.model_dump(mode="json") for item in evidence]
    body = context_receipt_body(
        context={
            "question": question,
            "references": [item.model_dump(mode="json", exclude={"href"}) for item in evidence],
        },
        prompt_version=CHAT_PROMPT.version,
        system_prompt=CHAT_PROMPT.system_prompt,
        instruction=CHAT_PROMPT.instruction,
        output_type=ChatAssessment,
    )
    with engine.begin() as c:
        c.execute(
            select(tables.agent_runs.c.id).where(tables.agent_runs.c.id == run_id).with_for_update()
        ).scalar_one()
        existing = (
            c.execute(
                select(tables.application_context_observations).where(
                    tables.application_context_observations.c.tenant_id == tenant_id,
                    tables.application_context_observations.c.run_id == run_id,
                    tables.application_context_observations.c.model_call_id == model_call_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        bundle = chat_bundle(work_focus=bool(work_sources))
        if existing is not None:
            if (
                existing["context_body"] != body
                or existing["output_body"] != output
                or existing["bundle"] != bundle
            ):
                raise BudgetLedgerError("APPLICATION_CONTEXT_CONFLICT")
            return
        require_new_context_history(c, tenant_id, run_id)
        stamp = c.execute(select(func.clock_timestamp())).scalar_one()
        oid = uuid4()
        sources = [
            dict(
                tenant_id=tenant_id,
                project_id=project_id,
                kind=item.entity,
                ref_id=int(item.entity_id) if item.entity == "event" else UUID(item.entity_id),
                as_of=stamp,
                digest=digest(item.model_dump(mode="json")),
            )
            for item in evidence
        ]
        observation = Observation.model_validate(
            dict(
                id=oid,
                tenant_id=tenant_id,
                run_id=run_id,
                tool_call_id=uuid4(),
                parent_observation_id=None,
                sequence=1,
                tool_version="work-card-evidence-collector.v1"
                if work_sources
                else "chat-evidence-collector.v1",
                status="partial",
                sources=sources,
                observed_at=stamp,
                as_of=stamp,
                fresh_until=None,
                acl_policy_version=auth["body"]["policy_version"],
                allowed_purpose="chat_answer",
                taint="untrusted_external" if attachment_sources else "internal",
                input_digest=digest(dict(question=question, project_id=str(project_id))),
                output_digest=digest(output),
                shown_count=len(output),
                total_count=None,
                truncated=bool(partial_sources),
                continuation=json.dumps(list(dict.fromkeys(item.href for item in partial_sources)))
                if partial_sources
                else None,
            )
        )
        c.execute(
            tables.application_context_observations.insert().values(
                id=oid,
                tenant_id=tenant_id,
                run_id=run_id,
                authorization_id=auth["id"],
                model_call_id=model_call_id,
                metadata=observation.model_dump(mode="json"),
                output_body=output,
                context_body=body,
                bundle=bundle,
                created_at=stamp,
            )
        )


def verify_chat_context(engine: Engine, invocation: Any, output_type: Any = None) -> None:
    from app.ai.chat import ChatEvidence, ChatEvidenceRepository

    if invocation.run_id is None:
        return
    with engine.connect() as c:
        auth = c.execute(
            select(tables.application_authorizations.c.body).where(
                tables.application_authorizations.c.tenant_id == invocation.tenant_id,
                tables.application_authorizations.c.run_id == invocation.run_id,
            )
        ).scalar_one_or_none()
        if auth is None:
            return
        chat_run = (
            c.execute(
                select(tables.agent_runs).where(
                    tables.agent_runs.c.tenant_id == invocation.tenant_id,
                    tables.agent_runs.c.id == invocation.run_id,
                )
            )
            .mappings()
            .one()
        )
        observation = (
            c.execute(
                select(tables.application_context_observations).where(
                    tables.application_context_observations.c.tenant_id == invocation.tenant_id,
                    tables.application_context_observations.c.run_id == invocation.run_id,
                    tables.application_context_observations.c.model_call_id
                    == invocation.model_call_id,
                )
            )
            .mappings()
            .one_or_none()
        )
    if observation is None:
        raise BudgetLedgerError("APPLICATION_CONTEXT_REQUIRED")
    purpose = auth["purpose"]
    from app.ai.application_domain_context import bundle as domain_bundle
    from app.ai.application_domain_context import sources_current
    from app.ai.test_plan_versions import version_from_run

    expected_version = version_from_run(purpose, chat_run["run_context"])
    if purpose == "product_evaluation":
        expected_version = chat_run["run_context"]["evaluation_prompt_version"]
    if purpose == "product_work":
        expected_version = chat_run["run_context"]["product_work_prompt_version"]
    if purpose == "product_matrix":
        from app.ai.product_matrix_preparation import version as matrix_version

        expected_version = matrix_version(chat_run["run_context"], observation["output_body"])
    if purpose == "executive_brief":
        from app.ai.executive_brief_preparation import version as executive_version

        expected_version = executive_version(chat_run["run_context"], observation["output_body"])
    if purpose == "portfolio_explanation":
        from app.ai.portfolio_explanation_preparation import version as portfolio_version

        expected_version = portfolio_version(chat_run["run_context"], observation["output_body"])
    if purpose == "cost_reduction":
        from app.ai.cost_reduction_preparation import version as cost_version

        expected_version = cost_version(chat_run["run_context"], observation["output_body"])
    if purpose == "change_discussion":
        from app.ai.discussion_initiation import prompt_version as initiation_version

        expected_version = initiation_version(chat_run["run_context"], observation["output_body"])

    if purpose == "change_work_package":
        from app.ai.change_notice_preparation import version as notice_version
        from app.ai.discussion_convene import version as convene_version
        from app.ai.discussion_followup import version as followup_version

        expected_version = (
            convene_version(chat_run["run_context"], observation["output_body"])
            or followup_version(chat_run["run_context"], observation["output_body"])
            or notice_version(chat_run["run_context"], observation["output_body"])
        )
    if observation["bundle"] != (
        chat_bundle(work_focus=bool(chat_run["run_context"].get("chat_object_focus")))
        if purpose == "chat_answer"
        else domain_bundle(purpose, prompt_version=expected_version)
    ):
        raise BudgetLedgerError("APPLICATION_CONTEXT_BUNDLE_CHANGED")
    expected = observation["context_body"]
    from hashlib import sha256

    if (
        invocation.prompt_version != expected["prompt_version"]
        or sha256(invocation.system_prompt.encode()).hexdigest() != expected["system_prompt_sha256"]
        or sha256(invocation.instruction.encode()).hexdigest() != expected["instruction_sha256"]
        or output_type is not None
        and digest(output_type.model_json_schema()) != expected["output_schema_sha256"]
    ):
        raise BudgetLedgerError("APPLICATION_CONTEXT_CONTRACT_CHANGED")
    if (
        observation["context_body"]["context"]
        != project_gateway_context(invocation.context).payload
    ):
        raise BudgetLedgerError("APPLICATION_CONTEXT_CHANGED")
    from app.ai.context_builder import RunContextIntegrityError

    try:
        current = (
            ChatEvidenceRepository(engine).still_current(
                tenant_id=invocation.tenant_id,
                project_id=invocation.project_id,
                question=invocation.context["question"],
                evidence=tuple(
                    ChatEvidence.model_validate(item) for item in observation["output_body"]
                ),
                actor_user_id=chat_run["requested_by_user_id"],
                object_focus=chat_run["run_context"].get("chat_object_focus"),
                attachment_ids=tuple(
                    UUID(a) for a in chat_run["run_context"].get("chat_attachment_ids", [])
                ),
            )
            if purpose == "chat_answer"
            else sources_current(engine, invocation, purpose, observation["output_body"])
        )
    except (ValueError, RunContextIntegrityError):
        current = False
    if not current:
        raise BudgetLedgerError("APPLICATION_CONTEXT_SOURCE_CHANGED")


def freeze_chat_manifest(
    engine: Engine,
    invocation: Any,
    *,
    attempt_id: UUID,
    qualification: dict[str, Any],
    removed_paths: tuple[str, ...],
    gateway: object = None,
) -> None:
    if invocation.run_id is None:
        return
    verify_chat_context(engine, invocation)
    with engine.begin() as c:
        auth = c.execute(
            select(tables.application_authorizations.c.id).where(
                tables.application_authorizations.c.tenant_id == invocation.tenant_id,
                tables.application_authorizations.c.run_id == invocation.run_id,
            )
        ).scalar_one_or_none()
        if auth is None:
            return
        from app.ai.application_leases import bind_write

        lease_id = bind_write(c, gateway, invocation.tenant_id, invocation.run_id)
        c.execute(
            select(tables.agent_runs.c.id)
            .where(tables.agent_runs.c.id == invocation.run_id)
            .with_for_update()
        ).scalar_one()
        observation = (
            c.execute(
                select(tables.application_context_observations).where(
                    tables.application_context_observations.c.tenant_id == invocation.tenant_id,
                    tables.application_context_observations.c.run_id == invocation.run_id,
                    tables.application_context_observations.c.model_call_id
                    == invocation.model_call_id,
                )
            )
            .mappings()
            .one()
        )
        admission = (
            c.execute(
                select(tables.budget_journal)
                .where(
                    tables.budget_journal.c.tenant_id == invocation.tenant_id,
                    tables.budget_journal.c.run_id == invocation.run_id,
                    tables.budget_journal.c.attempt_id == attempt_id,
                )
                .order_by(tables.budget_journal.c.revision.desc())
            )
            .mappings()
            .first()
        )
        if (
            admission is None
            or admission["reservation_status"] != "reserved"
            or admission["dispatched_at"] is not None
            or admission["request_binding"]["model_call_id"] != str(invocation.model_call_id)
        ):
            raise BudgetLedgerError("APPLICATION_MANIFEST_ADMISSION_INVALID")
        model_version = "sha256:" + digest(
            dict(
                qualification=qualification,
                meter_ref=admission["request_binding"]["qualification_ref"],
                meter_version=admission["request_binding"]["meter_version"],
            )
        )
        previous = (
            c.execute(
                select(tables.application_context_manifests)
                .where(
                    tables.application_context_manifests.c.tenant_id == invocation.tenant_id,
                    tables.application_context_manifests.c.run_id == invocation.run_id,
                )
                .order_by(tables.application_context_manifests.c.revision_no.desc())
            )
            .mappings()
            .first()
        )
        if (
            previous is not None
            and previous["body"]["model_qualification_version"] != model_version
        ):
            raise BudgetLedgerError("APPLICATION_MANIFEST_VERSION_CHANGED")
        mid = uuid4()
        stamp = c.execute(select(func.clock_timestamp())).scalar_one()
        bundle = observation["bundle"]
        sources = observation["metadata"]["sources"]
        tool_observation_ids = [
            s["ref_id"] for s in sources if s["kind"] == "application_tool_observation"
        ]
        body = dict(
            id=mid,
            tenant_id=invocation.tenant_id,
            run_id=invocation.run_id,
            authorization_id=auth,
            revision_no=previous["revision_no"] + 1 if previous else 1,
            parent_revision_id=previous["id"] if previous else None,
            goal_revision=1,
            release_bundle_version="sha256:" + digest(bundle),
            capability_version="sha256:" + digest(bundle["compiled"]["reader"]),
            prompt_version=invocation.prompt_version,
            skill_versions=[],
            toolset_version="sha256:"
            + digest(bundle["compiled"].get("service_toolset", bundle["compiled"]["model_tools"])),
            projection_version="sha256:" + digest(PROJECT_GATEWAY_POLICY),
            model_qualification_version=model_version,
            output_schema_version="sha256:" + observation["context_body"]["output_schema_sha256"],
            policy_version="sha256:" + digest(bundle["compiled"]),
            observation_ids=[observation["id"], *tool_observation_ids],
            event_watermark=max([s["ref_id"] for s in sources if s["kind"] == "event"] or [0]),
            selected_sources=sources,
            omission_reasons=(
                ["bounded_chat_collection_total_unknown"]
                if observation["metadata"]["allowed_purpose"] == "chat_answer"
                else [
                    f"sampled_report_rows:{observation['metadata']['shown_count']}/{observation['metadata']['total_count']}"
                ]
                if observation["metadata"]["truncated"]
                else []
            )
            + ["projection_removed:" + p for p in removed_paths],
            estimated_input_tokens=admission["input_tokens"],
            reserved_output_tokens=admission["output_tokens"],
            completeness="partial"
            if observation["metadata"]["status"] == "partial"
            else "complete",
            missing=[],
            built_at=stamp,
            digest="0" * 64,
        )
        manifest = ContextManifest.model_validate(body).model_dump(mode="json")
        manifest["digest"] = digest({k: v for k, v in manifest.items() if k != "digest"})
        c.execute(
            tables.application_context_manifests.insert().values(
                id=mid,
                tenant_id=invocation.tenant_id,
                run_id=invocation.run_id,
                authorization_id=auth,
                observation_id=observation["id"],
                admission_id=admission["id"],
                attempt_id=attempt_id,
                revision_no=manifest["revision_no"],
                parent_revision_id=previous["id"] if previous else None,
                owner_lease_id=lease_id,
                body=manifest,
                created_at=stamp,
            )
        )
