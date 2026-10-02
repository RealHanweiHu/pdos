"""Prepare human-readable registration choices from trusted evaluation publications."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.ai.application_domain_context import bundle
from app.ai.observations import digest
from app.ai.write_evaluation_publication import (
    WriteEvaluationPublicationError,
    configured_write_evaluation_publication,
)
from app.ai.write_policy import WRITE_OPERATIONS
from app.db.schema import tables
from app.domain.ai_write_policy import _current
from app.domain.ai_write_trial_protocols import _authorize


def prepare_trial_registration(
    c: Connection, *, tenant_id: UUID, actor_id: UUID, now: datetime | None = None
) -> dict[str, Any]:
    _authorize(c, tenant_id, actor_id, (), write=False)
    as_of = now or datetime.now(UTC)
    policy = _current(c, tenant_id)
    projects = [
        dict(row)
        for row in c.execute(
            select(tables.projects.c.id, tables.projects.c.code, tables.projects.c.name)
            .where(tables.projects.c.tenant_id == tenant_id)
            .order_by(tables.projects.c.code, tables.projects.c.id)
        ).mappings()
    ]
    response: dict[str, Any] = {
        "as_of": as_of,
        "candidates": [],
        "projects": projects,
        "policy_revision": policy["revision"] if policy is not None else 0,
        "blockers": [],
    }
    if policy is None or policy["mode"] != "tiered":
        response["blockers"].append("请先在写入政策中启用分级模式和需要试运行的草稿。")
        return response
    try:
        loaded = configured_write_evaluation_publication(
            os.environ, tenant_id=tenant_id, as_of=as_of
        )
    except WriteEvaluationPublicationError:
        response["blockers"].append("独立评测发布物当前无法核实，请由管理人员核对原件与有效期。")
        return response
    if loaded is None:
        response["blockers"].append("尚无受信的独立评测发布版本；发布原件就绪后可登记试运行。")
        return response
    runtime: dict[str, dict[str, Any]] = {}
    for entry in loaded.publication.evaluations:
        evaluation = entry.evaluation
        binding = evaluation.binding
        operation = binding.operation_key
        if (
            evaluation.outcome != "passed"
            or binding.policy_revision != policy["revision"]
            or binding.policy_version != policy["contract_version"]
            or policy["operation_settings"].get(operation, {}).get("mode", "disabled") == "disabled"
        ):
            continue
        purpose = "meeting_" + operation.split(".")[1]
        if purpose not in runtime:
            runtime[purpose] = bundle(purpose)
        current = runtime[purpose]
        if (
            binding.release_bundle_version != "sha256:" + digest(current)
            or binding.adapter_version != current["compiled"]["reader"]
        ):
            continue
        key = digest(
            {
                "publication_sha256": loaded.publication_sha256,
                "evaluation_id": str(evaluation.evaluation_id),
                "policy_id": str(policy["id"]),
                "binding": binding.model_dump(mode="json"),
            }
        )
        response["candidates"].append(
            {
                "key": key,
                "label": (
                    f"{WRITE_OPERATIONS[operation].label} · {binding.provider} / "
                    f"{binding.model} · {binding.model_version}"
                ),
                "binding": binding.model_dump(mode="json"),
                "evaluation_id": str(evaluation.evaluation_id),
                "published_at": loaded.publication.published_at,
                "expires_at": loaded.publication.valid_until,
            }
        )
    if not response["candidates"]:
        response["blockers"].append(
            "没有与当前运行版本及写入政策一致的已通过评测；请先核对评测版本和草稿设置。"
        )
    if not projects:
        response["blockers"].append("当前没有可登记的项目。")
    return response
