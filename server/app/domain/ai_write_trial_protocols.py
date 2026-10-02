"""Preregistered, scope-bound trial windows and immutable collection receipts.

Registration fixes the proposed binding, selection and arithmetic before a real
trial starts. It never proves model provenance or enables automatic execution.
Only the collector reads original receipts; clients cannot submit sample IDs,
evaluation outcomes or successful-count totals.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, RowMapping, select, tuple_
from sqlalchemy.exc import DBAPIError

from app.ai.write_evaluation_publication import (
    WriteEvaluationPublicationError,
    configured_write_evaluation,
)
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.roles import Action, is_allowed
from app.contracts.ai_write_qualification import (
    QualificationConfiguration,
    QualificationInput,
    evaluate_qualification,
)
from app.contracts.ai_write_trial_protocol import CollectTrial, RegisterTrial, TrialProtocol
from app.db.schema import tables
from app.domain.ai_write_policy import WritePolicyError, _current
from app.domain.ai_write_trial_collection import collect_trial
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _authorize(
    c: Connection, tenant: UUID, actor: UUID, projects: tuple[UUID, ...], *, write: bool
) -> None:
    action = Action.MODEL_GOVERNANCE_MANAGE if write else Action.MODEL_GOVERNANCE_VIEW
    tenant_query = select(tables.tenants.c.status).where(tables.tenants.c.id == tenant)
    if write:
        # Serializes request replay with other tenant policy writes, including first registration.
        tenant_query = tenant_query.with_for_update()
    active = c.execute(tenant_query).scalar_one_or_none()
    user = c.execute(
        select(tables.users.c.role, tables.users.c.is_active).where(
            tables.users.c.tenant_id == tenant, tables.users.c.id == actor
        )
    ).one_or_none()
    if (
        active != "active"
        or user is None
        or not user.is_active
        or not is_allowed(user.role, action)
    ):
        raise ObjectPermissionDeniedError
    for project in projects:
        exists = c.execute(
            select(tables.projects.c.id).where(
                tables.projects.c.tenant_id == tenant, tables.projects.c.id == project
            )
        ).scalar_one_or_none()
        if exists is None:
            raise ObjectPermissionDeniedError
        try:
            KnowledgeCorrectionService._authorize(c, tenant, actor, project, Action.MEETING_VIEW)
        except KnowledgeAccessError as error:
            raise ObjectPermissionDeniedError from error


def _protocol(c: Connection, tenant: UUID, protocol_id: UUID) -> TrialProtocol:
    row = c.execute(
        select(tables.ai_write_trial_protocols.c.protocol).where(
            tables.ai_write_trial_protocols.c.tenant_id == tenant,
            tables.ai_write_trial_protocols.c.id == protocol_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise WritePolicyError("TRIAL_NOT_FOUND", "未找到试运行登记")
    return TrialProtocol.model_validate(row)


def _replay(row: RowMapping | None, digest: str, field: str) -> dict[str, Any] | None:
    if row is None:
        return None
    if row["request_digest"] != digest:
        raise WritePolicyError("REQUEST_ID_REUSED", "请求编号已用于其他内容，请重新加载")
    return {field: row[field], "replayed": True}


def _record(
    c: Connection, tenant: UUID, actor: UUID, record_id: UUID, event: str, payload: dict[str, Any]
) -> None:
    EventAuditWriter(c, tenant_id=tenant, actor_user_id=actor).record(
        EventDraft(
            event_id=f"ai-write-trial:{record_id}",
            event_type=event,
            source="ai_write_trial_service",
            entity_id=record_id,
            payload=payload,
        ),
        AuditDraft(action=event.lower(), after_snapshot=payload),
    )


class AiWriteTrialProtocolService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def register(self, *, tenant_id: UUID, actor_id: UUID, body: RegisterTrial) -> dict[str, Any]:
        request_body = body.model_dump(mode="json", exclude={"request_id"})
        if body.preparation_digest is None:
            # Preserve retries of protocols registered before prepared choices existed.
            request_body.pop("preparation_digest", None)
        request_digest = _digest(request_body)
        t = tables.ai_write_trial_protocols
        with self.engine.begin() as c:
            _authorize(c, tenant_id, actor_id, body.project_ids, write=True)
            existing = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant_id,
                        t.c.actor_user_id == actor_id,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            replay = _replay(existing, request_digest, "protocol")
            if replay is not None:
                return replay
            if body.preparation_digest is not None:
                from app.domain.ai_write_trial_preparation import prepare_trial_registration

                preparation = prepare_trial_registration(c, tenant_id=tenant_id, actor_id=actor_id)
                if not any(
                    choice["key"] == body.preparation_digest
                    and choice["binding"] == body.binding.model_dump(mode="json")
                    for choice in preparation["candidates"]
                ):
                    raise WritePolicyError(
                        "TRIAL_PREPARATION_CHANGED", "评测或运行设置已变化，请重新读取可登记版本"
                    )
            policy = _current(c, tenant_id)
            if (
                policy is None
                or policy["mode"] != "tiered"
                or policy["revision"] != body.binding.policy_revision
                or policy["contract_version"] != body.binding.policy_version
            ):
                raise WritePolicyError("WRITE_POLICY_CHANGED", "请按当前分级写入设置登记试运行")
            setting = policy["operation_settings"].get(body.binding.operation_key, {})
            if setting.get("mode", "disabled") == "disabled":
                raise WritePolicyError("TRIAL_DISABLED", "请先启用该类草稿的预填确认试运行")
            now = datetime.now(UTC)
            if body.evidence_kind == "real_business" and body.window_start <= now:
                raise WritePolicyError(
                    "TRIAL_MUST_BE_PREREGISTERED", "真实业务试运行须在开始前登记"
                )
            config_body = {
                **body.configuration.model_dump(mode="json"),
                "configuration_id": str(uuid4()),
                "fixed_at": now.isoformat(),
                "minimum_confirmation_basis_points": setting["minimum_confirmation_basis_points"],
                "maximum_retraction_basis_points": setting["maximum_retraction_basis_points"],
            }
            config = QualificationConfiguration.model_validate(
                {**config_body, "configuration_digest": "0" * 64}
            )
            config = config.model_copy(
                update={
                    "configuration_digest": _digest(
                        config.model_dump(mode="json", exclude={"configuration_digest"})
                    )
                }
            )
            protocol_body = {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "policy_id": str(policy["id"]),
                "actor_user_id": str(actor_id),
                "project_ids": [str(item) for item in body.project_ids],
                "binding": body.binding.model_dump(mode="json"),
                "evidence_kind": body.evidence_kind,
                "window_start": body.window_start.isoformat(),
                "window_end": body.window_end.isoformat(),
                "configuration": config.model_dump(mode="json"),
                "reason": body.reason,
                "created_at": now.isoformat(),
            }
            protocol = TrialProtocol.model_validate({**protocol_body, "protocol_digest": "0" * 64})
            protocol = protocol.model_copy(
                update={
                    "protocol_digest": _digest(
                        protocol.model_dump(mode="json", exclude={"protocol_digest"})
                    )
                }
            )
            value = protocol.model_dump(mode="json")
            c.execute(
                t.insert().values(
                    id=protocol.id,
                    tenant_id=tenant_id,
                    policy_id=protocol.policy_id,
                    actor_user_id=actor_id,
                    request_id=body.request_id,
                    request_digest=request_digest,
                    protocol=value,
                    created_at=now,
                )
            )
            _record(
                c,
                tenant_id,
                actor_id,
                protocol.id,
                "AI_WRITE_TRIAL_REGISTERED",
                {
                    "protocol_id": str(protocol.id),
                    "protocol_digest": protocol.protocol_digest,
                    "operation_key": protocol.binding.operation_key,
                },
            )
            return {"protocol": value, "replayed": False}

    def get(self, *, tenant_id: UUID, actor_id: UUID, protocol_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            _authorize(c, tenant_id, actor_id, (), write=False)
            protocol = _protocol(c, tenant_id, protocol_id)
            _authorize(c, tenant_id, actor_id, protocol.project_ids, write=False)
            return protocol.model_dump(mode="json")

    def list(
        self, *, tenant_id: UUID, actor_id: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        t = tables.ai_write_trial_protocols
        with self.engine.connect() as c:
            _authorize(c, tenant_id, actor_id, (), write=False)
            query = select(t).where(t.c.tenant_id == tenant_id)
            if before_id is not None:
                before = _protocol(c, tenant_id, before_id)
                _authorize(c, tenant_id, actor_id, before.project_ids, write=False)
                query = query.where(tuple_(t.c.created_at, t.c.id) < (before.created_at, before.id))
            rows = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            items = []
            for row in rows[:20]:
                protocol = TrialProtocol.model_validate(row["protocol"])
                try:
                    _authorize(c, tenant_id, actor_id, protocol.project_ids, write=False)
                except ObjectPermissionDeniedError:
                    continue
                items.append(protocol.model_dump(mode="json"))
            return {"items": items, "next_before_id": rows[19]["id"] if len(rows) > 20 else None}

    def collect(
        self, *, tenant_id: UUID, actor_id: UUID, protocol_id: UUID, body: CollectTrial
    ) -> dict[str, Any]:
        # Waiting for a tenant lock cannot refresh an already fixed RR snapshot.
        # A competing identical collection may commit unseen; retry the entire
        # transaction so replay and source selection use a fresh snapshot.
        for attempt in range(3):
            try:
                return self._collect_once(
                    tenant_id=tenant_id, actor_id=actor_id, protocol_id=protocol_id, body=body
                )
            except DBAPIError as error:
                state = getattr(error.orig, "sqlstate", None)
                diagnostic = getattr(error.orig, "diag", None)
                constraint = getattr(diagnostic, "constraint_name", None)
                if state != "40001" and not (
                    state == "23505" and constraint == "uq_ai_trial_receipt_request"
                ):
                    raise
                if attempt == 2:
                    raise WritePolicyError(
                        "TRIAL_COLLECTION_BUSY", "原资料正在更新，请使用同一请求重试"
                    ) from error
        raise AssertionError("unreachable")

    def _collect_once(
        self, *, tenant_id: UUID, actor_id: UUID, protocol_id: UUID, body: CollectTrial
    ) -> dict[str, Any]:
        request_digest = _digest(
            {
                "protocol_id": str(protocol_id),
                **body.model_dump(mode="json", exclude={"request_id"}),
            }
        )
        t = tables.ai_write_trial_receipts
        # All source reads share one database snapshot; subsequent edits create a new receipt.
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            _authorize(c, tenant_id, actor_id, (), write=True)
            protocol = _protocol(c, tenant_id, protocol_id)
            _authorize(c, tenant_id, actor_id, protocol.project_ids, write=False)
            existing = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == tenant_id,
                        t.c.actor_user_id == actor_id,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            replay = _replay(existing, request_digest, "receipt")
            if replay is not None:
                return replay
            now = datetime.now(UTC)
            as_of = body.as_of or now
            if as_of > now or as_of < protocol.window_end:
                raise WritePolicyError(
                    "TRIAL_WINDOW_OPEN", "采集时点须在试运行窗口结束后，且不晚于当前时间"
                )
            receipt_id = uuid4()
            collection = collect_trial(
                c,
                tenant_id=tenant_id,
                project_ids=protocol.project_ids,
                operation_key=protocol.binding.operation_key,
                window_start=protocol.window_start,
                window_end=protocol.window_end,
                as_of=as_of,
                expected_binding=protocol.binding,
                evidence_kind=protocol.evidence_kind,
                cohort_id=receipt_id,
                evidence_ref=f"ai-write-trial-receipt:{receipt_id}",
            )
            evaluation = None
            publication: dict[str, Any] = {"status": "not_configured"}
            try:
                published = configured_write_evaluation(
                    os.environ, tenant_id=tenant_id, expected_binding=protocol.binding, as_of=as_of
                )
                if published is not None:
                    evaluation = published.evaluation
                    publication = {
                        "status": "verified",
                        "publication_sha256": published.publication_sha256,
                        "publication_id": str(published.publication_id),
                        "published_at": published.published_at.isoformat(),
                        "valid_until": published.valid_until.isoformat(),
                    }
            except WriteEvaluationPublicationError:
                publication = {"status": "unavailable"}
            candidate = QualificationInput(
                tenant_id=tenant_id,
                binding=protocol.binding,
                configuration=protocol.configuration,
                evaluation=evaluation,
                cohort=collection.cohort,
                as_of=as_of,
            )
            current = _current(c, tenant_id)
            value = {
                "id": str(receipt_id),
                "protocol_id": str(protocol.id),
                "protocol_digest": protocol.protocol_digest,
                "actor_user_id": str(actor_id),
                "created_at": now.isoformat(),
                "as_of": as_of.isoformat(),
                "collection": collection.model_dump(mode="json"),
                "qualification": evaluate_qualification(candidate).model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json")
                if evaluation is not None
                else None,
                "evaluation_publication": publication,
                "current_policy_matches": current is not None
                and current["id"] == protocol.policy_id,
                "notice": (
                    "固定采集回执保留试运行与独立评测原件的核对结果；它本身不授予自动写入权限。"
                ),
            }
            value["receipt_digest"] = _digest(value)
            c.execute(
                t.insert().values(
                    id=receipt_id,
                    tenant_id=tenant_id,
                    protocol_id=protocol.id,
                    actor_user_id=actor_id,
                    request_id=body.request_id,
                    request_digest=request_digest,
                    as_of=as_of,
                    receipt=value,
                    created_at=now,
                )
            )
            _record(
                c,
                tenant_id,
                actor_id,
                receipt_id,
                "AI_WRITE_TRIAL_COLLECTED",
                {
                    "protocol_id": str(protocol.id),
                    "receipt_id": str(receipt_id),
                    "receipt_digest": value["receipt_digest"],
                },
            )
            return {"receipt": value, "replayed": False}

    def receipts(
        self, *, tenant_id: UUID, actor_id: UUID, protocol_id: UUID, before_id: UUID | None = None
    ) -> dict[str, Any]:
        t = tables.ai_write_trial_receipts
        with self.engine.connect() as c:
            _authorize(c, tenant_id, actor_id, (), write=False)
            protocol = _protocol(c, tenant_id, protocol_id)
            _authorize(c, tenant_id, actor_id, protocol.project_ids, write=False)
            query = select(t).where(t.c.tenant_id == tenant_id, t.c.protocol_id == protocol_id)
            if before_id is not None:
                before = c.execute(query.where(t.c.id == before_id)).mappings().one_or_none()
                if before is None:
                    raise WritePolicyError("TRIAL_RECEIPT_NOT_FOUND", "未找到原采集回执")
                query = query.where(
                    tuple_(t.c.created_at, t.c.id) < (before["created_at"], before_id)
                )
            rows = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(21))
                .mappings()
                .all()
            )
            return {
                "items": [row["receipt"] for row in rows[:20]],
                "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
            }
