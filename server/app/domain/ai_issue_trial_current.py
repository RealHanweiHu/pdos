"""Read current Issue trial conditions without rewriting historical receipts or grants."""

import os
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, text

from app.ai.application_domain_context import bundle
from app.ai.issue_evaluation_publication import (
    WriteEvaluationPublicationError,
    configured_issue_evaluation,
)
from app.ai.issue_event_proposal import OPERATION
from app.ai.write_policy import POLICY_VERSION
from app.auth.repository import AuthContext
from app.contracts.ai_issue_evaluation import IssueEvaluationBinding
from app.db.schema import tables
from app.domain.ai_issue_observations import CaptureRequest, collect
from app.domain.ai_issue_trial_collections import _read as read_collection
from app.domain.ai_issue_trial_collections import _stamp, match_run, summarize
from app.domain.ai_issue_trial_protocols import _authorize
from app.domain.ai_issue_trial_protocols import _read as read_protocol
from app.domain.ai_issue_trial_provenance import collect_provenance
from app.domain.ai_issue_trial_qualification import evaluate
from app.domain.ai_issue_write_access import _principal
from app.domain.ai_meeting_drafts import latest_scope, policy
from app.domain.ai_write_policy import WritePolicyError
from app.domain.product_workspace import _plain, digest

VERSION = "event-issue-trial-current-v1"
NOTICE = (
    "本次只读核对原登记、最新采集和当前办理证据，原回执保持不变。"
    "条件满足不授予自动写入权限；真实调用证明与模拟结果分别核对，持续抽检属于自动写入后的运行要求。"
)


def current_state(
    original: dict[str, Any], fresh: dict[str, Any], *, changed: bool, reasons: list[dict[str, str]]
) -> str:
    """An unrecorded improvement cannot replace the latest fixed assessment."""
    if original["status"] != "meets_candidate_criteria":
        reasons.append(
            {
                "code": "latest_collection_not_met",
                "message": (
                    "最新原采集尚未满足候选要求；当前资料改善后须重新采集留存，不替换旧回执。"
                ),
            }
        )
    reasons.extend(fresh["reasons"])
    if changed or "does_not_meet_criteria" in {original["status"], fresh["status"]}:
        return "blocked"
    if reasons or any(value["status"] != "meets_candidate_criteria" for value in (original, fresh)):
        return "unavailable"
    return "current"


def controls(
    c: Connection, tenant: UUID, project: UUID, protocol: dict[str, Any], as_of: datetime
) -> tuple[list[dict[str, str]], bool]:
    """Separate definite control changes from unavailable external evidence."""
    reasons: list[dict[str, str]] = []
    changed = False

    def mismatch(code: str, message: str) -> None:
        nonlocal changed
        changed = True
        reasons.append({"code": code, "message": message})

    current = policy(c, tenant)
    cfg = protocol["configuration"]
    if (
        current is None
        or str(current["id"]) != protocol["policy_id"]
        or str(current["principal_id"]) != protocol["principal_id"]
        or current["mode"] != "tiered"
        or current["contract_version"] != POLICY_VERSION
        or current["revision"] != protocol["binding"]["policy_revision"]
        or current["contract_version"] != protocol["binding"]["policy_version"]
        or current["operation_settings"].get(OPERATION, {}).get("mode")
        not in {"confirm", "automatic"}
        or any(
            current["operation_settings"].get(OPERATION, {}).get(key) != cfg[key]
            for key in ("minimum_confirmation_basis_points", "maximum_retraction_basis_points")
        )
    ):
        mismatch(
            "policy_changed", "当前写入政策、AI 身份或阈值已与原登记不同，请按新政策重新登记。"
        )
    scope = latest_scope(c, tenant, project, OPERATION)
    if (
        scope is None
        or not scope["enabled"]
        or str(scope["id"]) != protocol["scope_revision_id"]
        or str(scope["principal_id"]) != protocol["principal_id"]
    ):
        mismatch("scope_changed", "原项目 AI 授权已暂停或被新版本替代，历史材料不恢复原授权。")
    try:
        _principal(c, tenant, UUID(protocol["principal_id"]))
    except WritePolicyError:
        mismatch("principal_unavailable", "原独立 AI 身份当前不可用。")
    binding = IssueEvaluationBinding.model_validate(protocol["binding"])
    runtime = bundle("event_issue")
    if (
        binding.release_bundle_version != "sha256:" + digest(runtime)
        or binding.adapter_version != runtime["compiled"]["reader"]
    ):
        mismatch("runtime_changed", "当前运行资料或读取版本已变化，原登记不能直接沿用。")
    try:
        published = configured_issue_evaluation(
            os.environ, tenant_id=tenant, expected_binding=binding, as_of=as_of
        )
        if published is None:
            reasons.append(
                {
                    "code": "publication_unavailable",
                    "message": "当前没有受信的独立 Issue 评测发布物。",
                }
            )
        elif published.model_dump(mode="json") != protocol["evaluation_publication"]:
            mismatch("publication_changed", "当前独立评测原件与登记时不同，请核对新版本。")
        elif published.evaluation.outcome != "passed":
            mismatch("evaluation_not_passed", "原绑定的独立质量评测未通过。")
    except WriteEvaluationPublicationError:
        reasons.append(
            {
                "code": "publication_unverifiable",
                "message": "当前独立评测原件、租户或有效期无法核实。",
            }
        )
    return reasons, changed


def fresh_collection(
    c: Connection, tenant: UUID, project: UUID, protocol: dict[str, Any], as_of: datetime
) -> dict[str, Any]:
    """Reuse the complete bounded collector; never accept caller-supplied evidence."""
    items = collect(
        c,
        tenant,
        project,
        CaptureRequest(
            request_id=uuid4(),
            window_start=_stamp(protocol["window_start"]),
            window_end=_stamp(protocol["window_end"]),
        ),
        as_of,
    )
    proofs = collect_provenance(
        c,
        tenant_id=tenant,
        project_id=project,
        run_ids=[UUID(item["run_id"]) for item in items],
        as_of=as_of,
        expected_binding=IssueEvaluationBinding.model_validate(protocol["binding"]),
    )
    for item in items:
        item["provenance"] = proofs[item["run_id"]]
        item["match"] = match_run(protocol, item, item["provenance"], as_of)
    return _plain(
        {
            "tenant_id": tenant,
            "project_id": project,
            "protocol_id": protocol["id"],
            "protocol_digest": digest(protocol),
            "window_start": protocol["window_start"],
            "window_end": protocol["window_end"],
            "as_of": as_of,
            "items": items,
            **summarize(protocol, items, as_of),
        }
    )


def check_current(
    c: Connection, *, tenant_id: UUID, project_id: UUID, protocol_id: UUID, as_of: datetime
) -> dict[str, Any]:
    """Read qualification in the caller's transaction; caller authorizes and locks scope."""
    tenant, project, identity = tenant_id, project_id, protocol_id
    protocol = read_protocol(c, tenant, project, identity)
    reasons, changed = controls(c, tenant, project, protocol, as_of)
    result: dict[str, Any] = {
        "version": VERSION,
        "checked_at": as_of,
        "protocol_id": identity,
        "latest_collection_id": None,
        "latest_collection_as_of": None,
        "state": "blocked" if changed else "unavailable",
        "original_result": None,
        "fresh_result": None,
        "reasons": reasons,
        "operational_requirements": [],
        "qualification_granted": False,
        "notice": NOTICE,
    }
    t = tables.ai_issue_trial_collections
    latest = c.execute(
        select(t.c.id)
        .where(
            t.c.tenant_id == tenant,
            t.c.project_id == project,
            t.c.protocol_id == identity,
            t.c.created_at <= as_of,
        )
        .order_by(t.c.created_at.desc(), t.c.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None:
        reasons.append(
            {
                "code": "collection_missing",
                "message": "原登记尚未采集完整窗口，请先按原登记采集。",
            }
        )
        return _plain(result)
    original = read_collection(c, tenant, project, identity, latest)
    result["latest_collection_id"] = latest
    result["latest_collection_as_of"] = original["as_of"]
    try:
        result["original_result"] = evaluate(protocol, original)
        current = fresh_collection(c, tenant, project, protocol, as_of)
        result["fresh_result"] = fresh = evaluate(protocol, current)
    except ValueError as error:
        raise WritePolicyError(
            "TRIAL_ORIGINALS_INCONSISTENT",
            "原登记、运行或办理证据不一致，未输出部分资格统计。",
        ) from error
    result["operational_requirements"] = fresh["operational_requirements"]
    result["state"] = current_state(
        result["original_result"], fresh, changed=changed, reasons=reasons
    )
    return _plain(result)


class IssueTrialCurrent:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            c.execute(text("SET TRANSACTION READ ONLY"))
            _authorize(c, context, project, write=False)
            return check_current(
                c,
                tenant_id=context.tenant.id,
                project_id=project,
                protocol_id=identity,
                as_of=c.execute(select(func.transaction_timestamp())).scalar_one(),
            )
