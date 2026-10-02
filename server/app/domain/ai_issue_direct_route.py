"""Route actual Issue results using server-owned evidence, never HTTP candidates.

The application caller holds tenant/project locks and independently rechecks
LIVE rollout, current source and write permission before its atomic mutation.
This resolver does not create Issues. Synthetic/internal provenance cannot grant
real-provider authority; the current collector therefore safely falls back.
"""

import os
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import Connection, Select, select

from app.ai.capability_contract import resolve_capability
from app.ai.issue_evaluation_publication import (
    WriteEvaluationPublicationError,
    configured_issue_evaluation_publication,
)
from app.ai.issue_event_proposal import KEY, OPERATION
from app.ai.write_policy import OperationSetting, TenantWriteMode, decide_write
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.db.schema import tables
from app.domain.ai_issue_trial_current import check_current
from app.domain.ai_issue_trial_protocols import _read as read_protocol
from app.domain.ai_issue_trial_provenance import collect_provenance, provenance_query
from app.domain.ai_issue_write_monitor import quality_monitor, sampled_run
from app.domain.ai_meeting_drafts import latest_scope, policy
from app.domain.ai_write_policy import WritePolicyError
from app.domain.product_workspace import digest


def protocol_query(
    *,
    tenant_id: UUID,
    project_id: UUID,
    policy_id: UUID,
    scope_revision_id: UUID,
    principal_id: UUID,
    binding: IssueEvaluationBinding,
    as_of: datetime,
) -> Select[Any]:
    t = tables.ai_issue_trial_protocols
    return (
        select(t.c.id)
        .where(
            t.c.tenant_id == tenant_id,
            t.c.project_id == project_id,
            t.c.policy_id == policy_id,
            t.c.scope_revision_id == scope_revision_id,
            t.c.principal_id == principal_id,
            t.c.evidence_kind == "real_business",
            t.c.created_at <= as_of,
            t.c.protocol["binding"] == binding.model_dump(mode="json"),
        )
        .order_by(t.c.created_at.desc(), t.c.id.desc())
        .limit(1)
    )


def _actual_candidate(binding: IssueEvaluationBinding, raw: dict[str, Any]) -> bool:
    call = raw.get("call") or {}
    generation = raw.get("generation") or {}
    original_policy = (generation.get("snapshot") or {}).get("policy") or {}
    manifest = (raw.get("manifest") or {}).get("body") or {}
    compiled = ((raw.get("observation") or {}).get("bundle") or {}).get("compiled") or {}
    return (
        binding.provider == call.get("provider")
        and binding.model == call.get("model")
        and binding.model_version == call.get("model_version")
        and binding.release_bundle_version == manifest.get("release_bundle_version")
        and binding.adapter_version == compiled.get("reader")
        and binding.policy_version == original_policy.get("contract_version")
        and binding.policy_revision == original_policy.get("revision")
    )


def resolve_direct_route(
    c: Connection, *, tenant_id: UUID, project_id: UUID, run_id: UUID, as_of: datetime
) -> dict[str, Any]:
    as_of = TypeAdapter(AwareDatetime).validate_python(as_of)
    receipt: dict[str, Any] = {
        "version": "event-issue-write-execution-v1",
        "run_id": str(run_id),
        "route": "confirm",
        "reason": "qualification_required",
        "reason_label": "自动写入材料尚未满足，保留原建议供具名确认。",
        "checked_at": as_of.isoformat(),
        "sampled": False,
    }

    def stop(reason: str, label: str, *, exception: bool = False) -> dict[str, Any]:
        receipt.update(
            reason=reason, reason_label=label, route="exception" if exception else "confirm"
        )
        return receipt

    settings = policy(c, tenant_id)
    grant = latest_scope(c, tenant_id, project_id, OPERATION)
    if (
        settings is None
        or grant is None
        or not grant["enabled"]
        or grant["principal_id"] != settings["principal_id"]
    ):
        return stop(
            "principal_scope_missing", "当前项目 AI 写入授权不完整，保留原建议。", exception=True
        )
    receipt.update(
        policy_id=str(settings["id"]),
        scope_revision_id=str(grant["id"]),
        principal_id=str(grant["principal_id"]),
    )
    try:
        setting = OperationSetting.model_validate(settings["operation_settings"].get(OPERATION, {}))
        decision = decide_write(
            OPERATION,
            tenant_mode=TenantWriteMode(settings["mode"]),
            setting=setting,
            rollout_live=resolve_capability(KEY).rollout.value == "live",
            principal_scope_valid=True,
            sources_current=True,
            qualification_current=True,
        )
        if decision.route != "direct":
            return stop(
                decision.reason,
                "当前写入偏好或能力条件要求保留具名确认。",
                exception=decision.route in {"blocked", "exception", "legacy"},
            )
        rows = list(c.execute(provenance_query(tenant_id, project_id, [run_id])).mappings())
        if len(rows) != 1:
            return stop("originals_unavailable", "原运行证据缺失或有歧义，保留原建议。")
        raw = dict(rows[0])
        generation = raw.get("generation") or {}
        if (
            str(generation.get("policy_id")) != str(settings["id"])
            or str(generation.get("scope_revision_id")) != str(grant["id"])
            or str(generation.get("principal_id")) != str(grant["principal_id"])
        ):
            return stop("generation_controls_changed", "生成时政策或授权已变化，保留原建议。")
        loaded = configured_issue_evaluation_publication(
            os.environ, tenant_id=tenant_id, as_of=as_of
        )
        if loaded is None:
            return stop("evaluation_unavailable", "当前没有可核实的独立评测，保留原建议。")
        candidates = [
            entry.evaluation.binding
            for entry in loaded.publication.evaluations
            if entry.evaluation.outcome == "passed"
            and _actual_candidate(entry.evaluation.binding, raw)
        ]
        verified = []
        for candidate in candidates:
            proof = collect_provenance(
                c,
                tenant_id=tenant_id,
                project_id=project_id,
                run_ids=[run_id],
                as_of=as_of,
                expected_binding=candidate,
            )[str(run_id)]
            if proof.get("provenance_verified") is True and proof.get(
                "binding"
            ) == candidate.model_dump(mode="json"):
                verified.append((candidate, proof))
        if len(verified) != 1:
            return stop(
                "runtime_binding_unverified", "实际调用的完整版本无法唯一核实，保留原建议。"
            )
        binding, proof = verified[0]
        receipt["readiness"] = {
            "state": "unavailable",
            "binding": binding.model_dump(mode="json"),
            "provenance": proof,
        }
        if proof.get("provider_verified") is not True:
            return stop("provider_unverified", "实际业务调用尚缺可信服务商证明，保留具名确认。")
        identity = c.execute(
            protocol_query(
                tenant_id=tenant_id,
                project_id=project_id,
                policy_id=settings["id"],
                scope_revision_id=grant["id"],
                principal_id=grant["principal_id"],
                binding=binding,
                as_of=as_of,
            )
        ).scalar_one_or_none()
        if identity is None:
            return stop("protocol_missing", "此实际版本尚无匹配的真实业务试运行登记。")
        protocol = read_protocol(c, tenant_id, project_id, identity)
        state = check_current(
            c, tenant_id=tenant_id, project_id=project_id, protocol_id=identity, as_of=as_of
        )
        receipt["readiness"].update(state=state["state"], qualification_state=state)
        receipt.update(
            protocol_id=str(identity),
            collection_id=state["latest_collection_id"],
            configuration=protocol["configuration"],
            binding_digest=digest(binding.model_dump(mode="json")),
        )
        if (
            state["state"] != "current"
            or not state["latest_collection_id"]
            or str(state["protocol_id"]) != str(identity)
            or TypeAdapter(AwareDatetime).validate_python(state["checked_at"]) != as_of
            or any(
                (state.get(key) or {}).get("status") != "meets_candidate_criteria"
                for key in ("original_result", "fresh_result")
            )
            or protocol["binding"] != binding.model_dump(mode="json")
            or protocol["policy_id"] != str(settings["id"])
            or protocol["scope_revision_id"] != str(grant["id"])
            or protocol["principal_id"] != str(grant["principal_id"])
        ):
            return stop(
                "qualification_required", "最新原试运行与当前条件尚未同时满足，保留具名确认。"
            )
    except (
        WriteEvaluationPublicationError,
        WritePolicyError,
        ValidationError,
        ValueError,
        KeyError,
        TypeError,
    ):
        return stop("qualification_material_unavailable", "资格原件无法完整核实，保留具名确认。")

    monitor = quality_monitor(
        c,
        tenant_id=tenant_id,
        project_id=project_id,
        policy_id=settings["id"],
        binding_digest=receipt["binding_digest"],
        protocol_id=identity,
        configuration=protocol["configuration"],
        as_of=as_of,
    )
    receipt["monitor"] = monitor
    if monitor["stopped"]:
        return stop("quality_stop", "自动建单已因撤回比例暂停；须沿恢复协议核对，保留具名确认。")
    receipt.update(
        route="direct",
        reason="qualified_direct_write",
        reason_label="当前原件满足自动建单条件。",
        sampled=sampled_run(identity, run_id, protocol["configuration"]["sampling_basis_points"]),
    )
    return receipt
