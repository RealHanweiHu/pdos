"""Named Issue preregistration bound to trusted original evaluations and scope.

Registration neither changes rollout nor retroactively qualifies existing runs.
Synthetic and replay protocols remain explicitly separate from real business.
"""

import os
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, func, select, tuple_

from app.ai.application_domain_context import bundle
from app.ai.issue_evaluation_publication import (
    WriteEvaluationPublicationError,
    configured_issue_evaluation_publication,
    select_issue_evaluation,
)
from app.ai.issue_event_proposal import OPERATION
from app.ai.write_policy import POLICY_VERSION
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.ai_issue_trial_protocol import RegisterIssueTrial
from app.db.schema import tables
from app.domain.ai_issue_write_access import _principal, authorize
from app.domain.ai_meeting_drafts import latest_scope, policy
from app.domain.ai_write_policy import WritePolicyError
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

NOTICE = (
    "本登记固定评测版本、项目授权、观察窗口和验收口径，不启用模型或自动建单。"
    "模拟和受控回放不代表真实业务试运行通过；原运行须另行按本协议核对。"
)


def _authorize(c: Connection, context: AuthContext, project: UUID, *, write: bool) -> None:
    authorize(c, context, project, write=False)
    KnowledgeCorrectionService._authorize(
        c,
        context.tenant.id,
        context.user.id,
        project,
        Action.MODEL_GOVERNANCE_MANAGE if write else Action.MODEL_GOVERNANCE_VIEW,
    )


def prepare(c: Connection, context: AuthContext, project: UUID, now: datetime) -> dict[str, Any]:
    _authorize(c, context, project, write=False)
    try:
        _authorize(c, context, project, write=True)
        can_register = True
    except PermissionError:
        can_register = False
    current = policy(c, context.tenant.id)
    grant = latest_scope(c, context.tenant.id, project, OPERATION)
    result: dict[str, Any] = {
        "can_register": can_register,
        "policy_revision": current["revision"] if current else 0,
        "candidates": [],
        "blockers": [],
    }
    if (
        current is None
        or current["mode"] != "tiered"
        or current["contract_version"] != POLICY_VERSION
        or current["operation_settings"].get(OPERATION, {}).get("mode")
        not in {"confirm", "automatic"}
    ):
        result["blockers"].append("请先登记当前分级写入政策并开放事件问题建议的确认应用。")
        return result
    if grant is None or not grant["enabled"] or grant["principal_id"] != current["principal_id"]:
        result["blockers"].append("请先登记本项目匹配的独立 AI 建单授权；该授权不启用自动建单。")
        return result
    _principal(c, context.tenant.id, current["principal_id"])
    try:
        loaded = configured_issue_evaluation_publication(
            os.environ, tenant_id=context.tenant.id, as_of=now
        )
    except WriteEvaluationPublicationError:
        result["blockers"].append("独立 Issue 评测发布物无法核实，请核对原件、租户和有效期。")
        return result
    if loaded is None:
        result["blockers"].append("尚无受信的独立 Issue 评测发布版本；离线模拟不能替代原模型评测。")
        return result
    runtime = bundle("event_issue")
    for entry in loaded.publication.evaluations:
        evaluation, binding = entry.evaluation, entry.evaluation.binding
        if (
            evaluation.outcome != "passed"
            or binding.policy_revision != current["revision"]
            or binding.policy_version != current["contract_version"]
            or binding.release_bundle_version != "sha256:" + digest(runtime)
            or binding.adapter_version != runtime["compiled"]["reader"]
        ):
            continue
        key = digest(
            {
                "publication_sha256": loaded.publication_sha256,
                "evaluation_id": str(evaluation.evaluation_id),
                "policy_id": str(current["id"]),
                "scope_revision_id": str(grant["id"]),
                "binding": binding.model_dump(mode="json"),
            }
        )
        result["candidates"].append(
            {
                "key": key,
                "label": (
                    f"事件问题建议 · {binding.provider} / {binding.model} · {binding.model_version}"
                ),
                "binding": binding.model_dump(mode="json"),
                "evaluation_id": str(evaluation.evaluation_id),
                "published_at": loaded.publication.published_at,
                "expires_at": loaded.publication.valid_until,
            }
        )
    if not result["candidates"]:
        result["blockers"].append("没有与当前运行版本和写入政策一致的已通过独立 Issue 评测。")
    return _plain(result)


def _read(c: Connection, tenant: UUID, project: UUID, identity: UUID) -> dict[str, Any]:
    t = tables.ai_issue_trial_protocols
    row = (
        c.execute(
            select(t).where(t.c.tenant_id == tenant, t.c.project_id == project, t.c.id == identity)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("原试运行登记不存在或不在当前项目")
    if digest(row["protocol"]) != row["protocol_digest"]:
        raise WritePolicyError("PROTOCOL_DIGEST_MISMATCH", "原登记校验不一致，请核对原件")
    return dict(row["protocol"])


class IssueTrialProtocols:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preparation(self, context: AuthContext, project: UUID) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return prepare(
                c, context, project, c.execute(select(func.clock_timestamp())).scalar_one()
            )

    def get(self, context: AuthContext, project: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            _authorize(c, context, project, write=False)
            return _read(c, context.tenant.id, project, identity)

    def history(
        self, context: AuthContext, project: UUID, before_id: UUID | None
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, context, project, write=False)
            t = tables.ai_issue_trial_protocols
            query = select(t).where(t.c.tenant_id == context.tenant.id, t.c.project_id == project)
            if before_id:
                cursor = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if cursor is None:
                    raise WritePolicyError("CURSOR_INVALID", "请从本项目试运行登记历史继续读取")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < tuple_(cursor["created_at"], cursor["id"])
                )
            rows = list(
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21)).mappings()
            )
            return _plain(
                {
                    "items": [_read(c, context.tenant.id, project, r["id"]) for r in rows[:20]],
                    "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
                }
            )

    def register(
        self, context: AuthContext, project: UUID, body: RegisterIssueTrial
    ) -> dict[str, Any]:
        tenant, actor = context.tenant.id, context.user.id
        with self.engine.begin() as c:
            if c.execute(
                select(tables.tenants.c.status)
                .where(tables.tenants.c.id == tenant)
                .with_for_update()
            ).scalar_one_or_none() != "active" or not lock_project_write_scope(
                c, tenant_id=tenant, project_id=project
            ):
                raise LookupError("项目不存在或当前不可用")
            _authorize(c, context, project, write=True)
            signature = digest(
                {"project_id": str(project), **body.model_dump(mode="json", exclude={"request_id"})}
            )
            t = tables.ai_issue_trial_protocols
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant,
                        t.c.actor_user_id == actor,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old:
                if old["request_digest"] != signature:
                    raise WritePolicyError("REQUEST_ID_REUSED", "此请求已用于其他试运行登记")
                return {"protocol": _read(c, tenant, project, old["id"]), "replayed": True}
            now = c.execute(select(func.clock_timestamp())).scalar_one()
            ready = prepare(c, context, project, now)
            candidate = next(
                (
                    v
                    for v in ready["candidates"]
                    if v["key"] == body.preparation_digest
                    and v["binding"] == body.binding.model_dump(mode="json")
                ),
                None,
            )
            if candidate is None:
                raise WritePolicyError(
                    "TRIAL_PREPARATION_CHANGED", "评测、政策或项目授权已变化，请重新读取可登记版本"
                )
            if body.evidence_kind == "real_business" and body.window_start <= now:
                raise WritePolicyError(
                    "TRIAL_REQUIRES_PREREGISTRATION", "真实业务试运行须在窗口开始前登记"
                )
            current = policy(c, tenant)
            grant = latest_scope(c, tenant, project, OPERATION)
            assert current is not None and grant is not None
            try:
                loaded = configured_issue_evaluation_publication(
                    os.environ, tenant_id=tenant, as_of=now
                )
                if loaded is None:
                    raise WriteEvaluationPublicationError("publication_missing")
                evaluation = select_issue_evaluation(loaded, expected_binding=body.binding)
            except WriteEvaluationPublicationError as error:
                raise WritePolicyError(
                    "TRIAL_PREPARATION_CHANGED", "独立评测发布原件已变化，请重新读取"
                ) from error
            # Recheck the exact file pin after preparation to avoid an operator-file race.
            check = digest(
                {
                    "publication_sha256": loaded.publication_sha256,
                    "evaluation_id": str(evaluation.evaluation.evaluation_id),
                    "policy_id": str(current["id"]),
                    "scope_revision_id": str(grant["id"]),
                    "binding": body.binding.model_dump(mode="json"),
                }
            )
            if check != body.preparation_digest:
                raise WritePolicyError(
                    "TRIAL_PREPARATION_CHANGED", "独立评测发布原件已变化，请重新读取"
                )
            setting = current["operation_settings"][OPERATION]
            configuration = {
                **body.configuration.model_dump(mode="json"),
                "fixed_at": now,
                "minimum_confirmation_basis_points": setting["minimum_confirmation_basis_points"],
                "maximum_retraction_basis_points": setting["maximum_retraction_basis_points"],
            }
            identity = uuid4()
            value = _plain(
                {
                    "version": "event-issue-trial-protocol-v1",
                    "id": identity,
                    "tenant_id": tenant,
                    "project_id": project,
                    "actor_user_id": actor,
                    "actor_name": context.user.display_name,
                    "created_at": now,
                    "policy_id": current["id"],
                    "principal_id": current["principal_id"],
                    "scope_revision_id": grant["id"],
                    "binding_label": candidate["label"],
                    "binding": body.binding.model_dump(mode="json"),
                    "evaluation_publication": evaluation.model_dump(mode="json"),
                    "window_start": body.window_start,
                    "window_end": body.window_end,
                    "evidence_kind": body.evidence_kind,
                    "configuration": configuration,
                    "reason": body.reason,
                    "qualification_granted": False,
                    "notice": NOTICE,
                }
            )
            value_digest = digest(value)
            payload = {
                "protocol_id": str(identity),
                "protocol_digest": value_digest,
                "evidence_kind": body.evidence_kind,
            }
            event = EventAuditWriter(
                c, tenant_id=tenant, project_id=project, actor_user_id=actor
            ).record(
                EventDraft(
                    event_id=f"ai-issue-trial:{identity}",
                    event_type="AI_ISSUE_TRIAL_REGISTERED",
                    source="ai_issue_trial_service",
                    entity_id=identity,
                    payload=payload,
                ),
                AuditDraft(action="ai_issue.trial_registered", after_snapshot=payload),
            )
            c.execute(
                t.insert().values(
                    id=identity,
                    tenant_id=tenant,
                    project_id=project,
                    actor_user_id=actor,
                    request_id=body.request_id,
                    request_digest=signature,
                    policy_id=current["id"],
                    principal_id=current["principal_id"],
                    scope_revision_id=grant["id"],
                    window_start=body.window_start,
                    window_end=body.window_end,
                    evidence_kind=body.evidence_kind,
                    protocol=value,
                    protocol_digest=value_digest,
                    output_event_row_id=event.event_row_id,
                    created_at=now,
                )
            )
            return {"protocol": value, "replayed": False}
