"""Read current material checks separately from immutable trial receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select

from app.ai.application_domain_context import bundle
from app.ai.observations import digest
from app.auth.errors import ObjectPermissionDeniedError
from app.db.schema import tables
from app.domain.ai_write_qualification_state import read_qualification_state
from app.domain.ai_write_trial_protocols import _authorize, _protocol


def current_trial_check(
    engine: Engine,
    *,
    tenant_id: UUID,
    actor_id: UUID,
    protocol_id: UUID,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    # All current reads see one snapshot. A GET never creates a collection or
    # rewrites the original as_of result, even after a later withdrawal.
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
        c.begin(),
    ):
        _authorize(c, tenant_id, actor_id, (), write=False)
        protocol = _protocol(c, tenant_id, protocol_id)
        _authorize(c, tenant_id, actor_id, protocol.project_ids, write=False)
        projects = [
            dict(row)
            for row in c.execute(
                select(tables.projects.c.id, tables.projects.c.code, tables.projects.c.name)
                .where(
                    tables.projects.c.tenant_id == tenant_id,
                    tables.projects.c.id.in_(protocol.project_ids),
                )
                .order_by(tables.projects.c.code, tables.projects.c.id)
            ).mappings()
        ]
        selected = project_id or UUID(str(projects[0]["id"]))
        if selected not in protocol.project_ids:
            raise ObjectPermissionDeniedError
        now = datetime.now(UTC)
        state = read_qualification_state(
            c,
            tenant_id=tenant_id,
            project_id=selected,
            operation_key=protocol.binding.operation_key,
            binding=protocol.binding,
            as_of=now,
        ).model_dump(mode="json")
        if state["protocol_id"] and state["protocol_id"] != str(protocol_id):
            latest = _protocol(c, tenant_id, UUID(state["protocol_id"]))
            _authorize(c, tenant_id, actor_id, latest.project_ids, write=False)
        purpose = "meeting_" + protocol.binding.operation_key.split(".")[1]
        current = bundle(purpose)
        runtime_matches = (
            protocol.binding.release_bundle_version == "sha256:" + digest(current)
            and protocol.binding.adapter_version == current["compiled"]["reader"]
        )
        if not runtime_matches:
            state["state"] = "blocked"
            state["reasons"].append(
                {"code": "runtime_bundle_changed", "message": "运行版本已变化，请重新评测并登记。"}
            )
        return {
            "requested_protocol_id": str(protocol_id),
            "projects": projects,
            "selected_project_id": str(selected),
            "runtime_matches": runtime_matches,
            "check": state,
            "notice": "本次只核对指定模型与项目的当前材料，不启用自动写入。"
            "同范围后来采集的结果和原稿后续办理会参与核对，原回执保持不变。",
        }
