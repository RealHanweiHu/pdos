"""Versioned tenant write policy and independent, non-login AI identity."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, Engine, RowMapping, select

from app.ai.capability_contract import resolve_capability
from app.ai.write_policy import (
    POLICY_VERSION,
    WRITE_OPERATIONS,
    OperationSetting,
    TenantWriteMode,
    WriteTier,
    default_settings,
    validate_settings,
)
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.roles import Action, is_allowed
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class WritePolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: UUID
    expected_revision: int = Field(ge=0)
    mode: TenantWriteMode
    operation_settings: dict[str, OperationSetting]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def trim_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请填写调整原因")
        return value

    @model_validator(mode="after")
    def valid_settings(self) -> PolicyUpdate:
        validate_settings(self.operation_settings)
        return self


def _current(connection: Connection, tenant_id: UUID) -> RowMapping | None:
    return (
        connection.execute(
            select(tables.ai_write_policies)
            .where(tables.ai_write_policies.c.tenant_id == tenant_id)
            .order_by(tables.ai_write_policies.c.revision.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def _snapshot(row: RowMapping | None) -> dict[str, Any]:
    if row is None:
        return {
            "revision": 0,
            "mode": "legacy",
            "contract_version": POLICY_VERSION,
            "operation_settings": {
                key: value.model_dump(mode="json") for key, value in default_settings().items()
            },
            "principal_id": None,
            "created_at": None,
        }
    return {
        key: row[key]
        for key in (
            "revision",
            "mode",
            "contract_version",
            "operation_settings",
            "principal_id",
            "created_at",
        )
    }


def _operations() -> list[dict[str, Any]]:
    result = []
    for operation in WRITE_OPERATIONS.values():
        contract = (
            resolve_capability(operation.capability_key) if operation.capability_key else None
        )
        blockers = []
        if operation.write_tier is WriteTier.T2:
            blockers.append("正式裁决始终由人办理")
        else:
            if not operation.adapter_ready:
                blockers.append(
                    "预填试运行已接入，自动写入尚待资格"
                    if operation.trial_ready
                    else "分级写入与撤回正在接入"
                )
            if contract is None:
                blockers.append("能力登记待接入")
            elif contract.rollout.value != "live":
                blockers.append("能力仍处于独立评测阶段")
            if operation.write_tier is WriteTier.T0:
                blockers.append("自动写入资格与试用回执待核对")
        result.append(
            {
                **operation.model_dump(mode="json"),
                "rollout": contract.rollout.value if contract else None,
                "blockers": blockers,
            }
        )
    return result


class AiWritePolicyService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get(self, *, tenant_id: UUID) -> dict[str, Any]:
        with self._engine.connect() as connection:
            current = _snapshot(_current(connection, tenant_id))
        return {
            **current,
            "principal_name": "PDOS Agent",
            "operations": _operations(),
            "notice": "保存的是租户使用偏好。只有完成接入、范围授权和资格核对的操作才会生效。",
        }

    def history(self, *, tenant_id: UUID, before_revision: int | None = None) -> dict[str, Any]:
        policy = tables.ai_write_policies
        query = (
            select(policy, tables.users.c.display_name.label("actor_name"))
            .join(
                tables.users,
                (tables.users.c.tenant_id == policy.c.tenant_id)
                & (tables.users.c.id == policy.c.actor_user_id),
            )
            .where(policy.c.tenant_id == tenant_id)
        )
        if before_revision is not None:
            query = query.where(policy.c.revision < before_revision)
        with self._engine.connect() as connection:
            rows = (
                connection.execute(query.order_by(policy.c.revision.desc()).limit(21))
                .mappings()
                .all()
            )
        return {
            "items": [dict(row) for row in rows[:20]],
            "next_before_revision": rows[19]["revision"] if len(rows) > 20 else None,
        }

    def update(
        self, *, tenant_id: UUID, actor_user_id: UUID, changes: PolicyUpdate
    ) -> dict[str, Any]:
        digest = hashlib.sha256(
            json.dumps(
                changes.model_dump(mode="json", exclude={"request_id"}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        policy = tables.ai_write_policies
        with self._engine.begin() as connection:
            # The tenant exists even before revision 1, so first saves serialize too.
            tenant = connection.execute(
                select(tables.tenants.c.status)
                .where(
                    tables.tenants.c.id == tenant_id,
                )
                .with_for_update()
            ).one_or_none()
            actor = connection.execute(
                select(tables.users.c.role, tables.users.c.is_active)
                .where(
                    tables.users.c.tenant_id == tenant_id,
                    tables.users.c.id == actor_user_id,
                )
                .with_for_update()
            ).one_or_none()
            if (
                tenant is None
                or tenant.status != "active"
                or actor is None
                or not actor.is_active
                or not is_allowed(actor.role, Action.MODEL_GOVERNANCE_MANAGE)
            ):
                raise ObjectPermissionDeniedError
            replay = (
                connection.execute(
                    select(policy).where(
                        policy.c.tenant_id == tenant_id,
                        policy.c.actor_user_id == actor_user_id,
                        policy.c.request_id == changes.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if replay is not None:
                if replay["request_digest"] != digest:
                    raise WritePolicyError(
                        "REQUEST_ID_REUSED", "请求编号已用于其他设置，请重新加载"
                    )
                receipt = {"revision": replay["revision"], "replayed": True}
            else:
                before = _snapshot(_current(connection, tenant_id))
                if before["revision"] != changes.expected_revision:
                    raise WritePolicyError(
                        "WRITE_POLICY_CHANGED", "设置已被其他人更新，请重新加载后核对"
                    )
                principal_id = connection.execute(
                    select(tables.ai_principals.c.id).where(
                        tables.ai_principals.c.tenant_id == tenant_id,
                        tables.ai_principals.c.principal_key == "pdos-agent",
                    )
                ).scalar_one_or_none()
                now = datetime.now(UTC)
                if principal_id is None:
                    principal_id = uuid4()
                    connection.execute(
                        tables.ai_principals.insert().values(
                            id=principal_id,
                            tenant_id=tenant_id,
                            principal_key="pdos-agent",
                            display_name="PDOS Agent",
                            principal_kind="ai",
                            created_at=now,
                        )
                    )
                revision = before["revision"] + 1
                policy_id = uuid4()
                settings = {
                    key: item.model_dump(mode="json")
                    for key, item in changes.operation_settings.items()
                }
                connection.execute(
                    policy.insert().values(
                        id=policy_id,
                        tenant_id=tenant_id,
                        principal_id=principal_id,
                        revision=revision,
                        mode=changes.mode.value,
                        contract_version=POLICY_VERSION,
                        operation_settings=settings,
                        request_id=changes.request_id,
                        request_digest=digest,
                        actor_user_id=actor_user_id,
                        reason=changes.reason,
                        created_at=now,
                    )
                )
                EventAuditWriter(
                    connection, tenant_id=tenant_id, actor_user_id=actor_user_id
                ).record(
                    EventDraft(
                        event_id=f"ai-write-policy:{tenant_id}:{revision}",
                        event_type="AI_WRITE_POLICY_REVISED",
                        source="ai_write_policy_service",
                        entity_id=policy_id,
                        payload={
                            "revision": revision,
                            "mode": changes.mode.value,
                            "principal_id": str(principal_id),
                        },
                        occurred_at=now,
                    ),
                    AuditDraft(
                        action="ai_write_policy.revise",
                        before_snapshot={
                            "revision": before["revision"],
                            "mode": before["mode"],
                            "operation_settings": before["operation_settings"],
                        },
                        after_snapshot={
                            "revision": revision,
                            "mode": changes.mode.value,
                            "operation_settings": settings,
                        },
                        context={"contract_version": POLICY_VERSION, "reason": changes.reason},
                    ),
                )
                receipt = {"revision": revision, "replayed": False}
        return {"policy": self.get(tenant_id=tenant_id), "receipt": receipt}
