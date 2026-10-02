"""Live completion readiness and receiver-owned PVT/MP handoff acceptance."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, select

from app.db.schema import tables
from app.domain.decisions import DecisionService, _decision_statement, _record_from_row
from app.domain.gates import GateService
from app.domain.product_workspace import _plain, digest
from app.domain.project_handoff_sources import (
    accepted_source_manifest,
    source_manifest,
    source_review,
)
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

HANDOFF_ITEMS = {
    "configuration": "冻结配置与规格",
    "bom": "BOM与物料版本",
    "manufacturing": "SOP、工装、工艺与检验资料",
    "test_certification": "测试与认证证据",
    "training": "培训与接收记录",
    "residuals": "遗留项处置及责任期限",
    "quality_follow_up": "持续品质责任与跟踪安排",
}


class CompletionError(ValueError):
    pass


class ProjectCompletionNotReadyError(CompletionError):
    def __init__(self, blockers: list[dict[str, str]]) -> None:
        self.blockers = blockers
        super().__init__("尚未满足结项条件，请处理结项清单中的未完成项")


def _rows(connection: Connection, table: Any, tenant_id: UUID, project_id: UUID) -> list[Any]:
    return list(
        connection.execute(
            select(table)
            .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
            .order_by(table.c.id)
        ).mappings()
    )


def _fingerprint(
    connection: Connection,
    tenant_id: UUID,
    project_id: UUID,
    item: Any,
    business_sources: dict[str, Any] | None = None,
) -> str | None:
    doc = connection.execute(
        select(tables.documents.c.sha256).where(
            tables.documents.c.tenant_id == tenant_id,
            tables.documents.c.project_id == project_id,
            tables.documents.c.id == item["document_id"],
        )
    ).scalar_one_or_none()
    if doc is None:
        return None
    source: dict[str, object] = {
        "document_id": str(item["document_id"]),
        "sha256": doc,
        "receiver_user_id": str(item["receiver_user_id"]),
        "note": item["note"],
    }
    if item["item_key"] in {"configuration", "test_certification"}:
        from app.domain.project_templates import active_version

        version = active_version(connection, tenant_id=tenant_id, project_id=project_id)
        source["product_scope"] = (
            {
                "product_type": version["snapshot"]["product_type"],
                "features": version["snapshot"]["feature_values"],
                "test_profile": version["snapshot"].get("test_profile"),
            }
            if version
            else None
        )
    source["business_sources"] = (
        business_sources
        if business_sources is not None
        else source_manifest(connection, tenant_id, project_id, item["item_key"])
    )
    return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()


def handoff_digest(
    connection: Connection,
    tenant: UUID,
    project: UUID,
    key: str,
    item: Any,
    business_sources: dict[str, Any] | None = None,
) -> str:
    return digest(
        {
            "item_key": key,
            "record": _plain(item) if item else None,
            "source": _fingerprint(connection, tenant, project, item, business_sources)
            if item
            else None,
        }
    )


def handoff_replay(
    connection: Connection,
    tenant: UUID,
    project: UUID,
    actor: UUID,
    request_id: UUID | None,
    fingerprint: str,
) -> dict[str, Any] | None:
    if request_id is None:
        return None
    a = tables.audit_log
    prior = (
        connection.execute(
            select(a.c.context, a.c.after_snapshot).where(
                a.c.tenant_id == tenant,
                a.c.project_id == project,
                a.c.actor_user_id == actor,
                a.c.action.in_(
                    ("project.handoff.prepare", "project.handoff.accept", "project.handoff.return")
                ),
                a.c.context["handoff_request"]["request_id"].as_string() == str(request_id),
            )
        )
        .mappings()
        .one_or_none()
    )
    if prior is None:
        return None
    if prior["context"]["handoff_request"]["digest"] != fingerprint:
        raise CompletionError("此请求编号已用于另一项交接操作")
    receipt = {**prior["after_snapshot"], "request_id": str(request_id)}
    # Audit JSON retains the original timestamps as text. Restore their types so
    # a replay uses the same API serialization as the original database receipt.
    for field in ("created_at", "updated_at", "responded_at"):
        if isinstance(receipt.get(field), str):
            receipt[field] = datetime.fromisoformat(receipt[field])
    return receipt


def handoff_audit(
    connection: Connection,
    tenant: UUID,
    project: UUID,
    actor: UUID,
    before: Any,
    after: Any,
    request_id: UUID | None,
    fingerprint: str,
    change_reason: str | None = None,
) -> dict[str, Any]:
    ids = {actor, after["receiver_user_id"]}
    if before:
        ids.add(before["receiver_user_id"])
    people = {
        str(r["id"]): r["display_name"]
        for r in connection.execute(
            select(tables.users.c.id, tables.users.c.display_name).where(
                tables.users.c.tenant_id == tenant, tables.users.c.id.in_(ids)
            )
        ).mappings()
    }
    document = (
        connection.execute(
            select(
                tables.documents.c.id, tables.documents.c.filename, tables.documents.c.sha256
            ).where(
                tables.documents.c.tenant_id == tenant,
                tables.documents.c.project_id == project,
                tables.documents.c.id == after["document_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    return {
        "handoff_request": {
            "request_id": str(request_id) if request_id else None,
            "digest": fingerprint,
        },
        "handoff_details": {
            "people": people,
            "document": _plain(document) if document else None,
            "receiver_change_reason": change_reason,
            "source_fingerprint": _fingerprint(connection, tenant, project, after),
            "business_sources": source_manifest(connection, tenant, project, after["item_key"]),
        },
    }


def handoff_history_statement(tenant: UUID, project: UUID, key: str, before_id: int | None) -> Any:
    a = tables.audit_log
    q = select(
        a.c.id,
        a.c.timestamp.label("created_at"),
        a.c.actor_user_id,
        a.c.action,
        a.c.before_snapshot,
        a.c.after_snapshot,
        a.c.context,
    ).where(
        a.c.tenant_id == tenant,
        a.c.project_id == project,
        a.c.action.in_(
            ("project.handoff.prepare", "project.handoff.accept", "project.handoff.return")
        ),
        a.c.after_snapshot["item_key"].as_string() == key,
    )
    if before_id is not None:
        q = q.where(a.c.id < before_id)
    return q.order_by(a.c.id.desc()).limit(21)


def _member(connection: Connection, tenant_id: UUID, project_id: UUID, user_id: UUID) -> bool:
    return (
        connection.execute(
            select(tables.users.c.id)
            .join(
                tables.project_members,
                (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                & (tables.project_members.c.user_id == tables.users.c.id),
            )
            .where(
                tables.users.c.tenant_id == tenant_id,
                tables.users.c.id == user_id,
                tables.users.c.is_active.is_(True),
                tables.users.c.role.in_(
                    ("owner", "admin", "project_manager", "engineer", "quality")
                ),
                tables.project_members.c.project_id == project_id,
            )
        ).scalar_one_or_none()
        is not None
    )


def readiness(connection: Connection, *, tenant_id: UUID, project_id: UUID) -> dict[str, Any]:
    project = (
        connection.execute(
            select(tables.projects).where(
                tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
            )
        )
        .mappings()
        .one()
    )
    stages = list(
        connection.execute(
            select(tables.stages)
            .where(
                tables.stages.c.tenant_id == tenant_id,
                tables.stages.c.workflow_id == project["workflow_id"],
            )
            .order_by(tables.stages.c.sequence)
        ).mappings()
    )
    blockers: list[dict[str, str]] = []

    def block(key: str, label: str) -> None:
        blockers.append({"key": key, "label": label})

    if not stages or project["current_stage_id"] != stages[-1]["id"]:
        block("final_stage", "项目尚未到达最终阶段")
    gates = {row["stage_id"]: row for row in _rows(connection, tables.gates, tenant_id, project_id)}
    for stage in stages:
        gate = gates.get(stage["id"])
        if gate is None or gate["status"] != "approved":
            block(f"gate:{stage['id']}", f"{stage['name']} Gate尚未批准")
        blockers.extend(
            GateService._live_non_signoff_blockers(
                connection, tenant_id=tenant_id, project_id=project_id, stage_id=stage["id"]
            )
        )
    for task in _rows(connection, tables.tasks, tenant_id, project_id):
        if task["status"] not in {"done", "skipped"}:
            block(f"task:{task['id']}", f"未完成任务：{task['title']}")
    for issue in _rows(connection, tables.issues, tenant_id, project_id):
        if issue.get("withdrawn_at") is not None:
            continue
        if issue["severity"] in {"high", "critical"} or (
            issue["status"] == "closed" and project.get(f"issue_verify_{issue['severity']}", False)
        ):
            if (
                issue["status"] != "closed"
                or not issue["closure_evidence_ref"]
                or not issue["verifier_user_id"]
                or not issue["owner_user_id"]
                or issue["owner_user_id"] == issue["verifier_user_id"]
            ):
                block(f"issue:{issue['id']}", f"问题尚未按政策独立验证关闭：{issue['title']}")
        elif issue["status"] != "closed" and (
            not issue["owner_user_id"] or not issue["target_date"] or not issue["closure_criteria"]
        ):
            block(f"issue:{issue['id']}", f"遗留问题缺少责任人、期限或关闭条件：{issue['title']}")
    for risk in _rows(connection, tables.risks, tenant_id, project_id):
        if (
            risk["draft_state"] != "confirmed"
            or risk["status"] == "closed"
            or risk["dismissed_at"] is not None
        ):
            continue
        if (
            risk["likelihood"] * risk["impact"] >= 16
            or not risk["owner_user_id"]
            or not risk["target_date"]
            or not risk["mitigation_plan"]
        ):
            block(f"risk:{risk['id']}", f"风险尚未收口或缺少处置责任：{risk['title']}")
    for row in connection.execute(
        _decision_statement().where(
            tables.decisions.c.tenant_id == tenant_id, tables.decisions.c.project_id == project_id
        )
    ).mappings():
        decision = DecisionService._with_execution(connection, tenant_id, _record_from_row(row))
        if decision.follow_up_state == "pending":
            block(f"decision:{decision.id}", f"决策执行尚未完成：{decision.title}")
    existing = {
        item["item_key"]: item
        for item in _rows(connection, tables.project_handoff_items, tenant_id, project_id)
    }
    handoffs = []
    for key, label in HANDOFF_ITEMS.items():
        item = existing.get(key)
        sources = source_manifest(connection, tenant_id, project_id, key)
        accepted_sources = accepted_source_manifest(connection, tenant_id, project_id, key, item)
        source_checks = source_review(sources, accepted_sources)
        reasons = []
        fingerprint = (
            _fingerprint(connection, tenant_id, project_id, item, sources) if item else None
        )
        if item is None:
            reasons.append("尚未提交交接资料")
        else:
            if item["status"] != "accepted":
                reasons.append(
                    "交接已退回，须补充后重新接收"
                    if item["status"] == "returned"
                    else "等待指定接收人核对"
                )
            if not _member(connection, tenant_id, project_id, item["receiver_user_id"]):
                reasons.append("原接收人已不是有效项目成员，请重新指定")
            if fingerprint is None:
                reasons.append("原交接文档已不可用，请重新提交")
            if item["status"] == "accepted":
                if accepted_sources is None:
                    reasons.append("原接收未保存本版业务依据摘要，须重新核对；原签名与结论保留")
                else:
                    reasons.extend(
                        f"{row['label']}已变化，须重新核对"
                        for row in source_checks
                        if row["changed"]
                    )
                    if item["accepted_fingerprint"] != fingerprint and not any(
                        row["changed"] for row in source_checks
                    ):
                        reasons.append("交接文档、适用范围或办理内容已变化，须重新核对")
        current = not reasons
        if not current:
            block(f"handoff:{key}", f"交接尚未有效接收：{label}")
        handoffs.append(
            {
                **(dict(item) if item else {"item_key": key, "status": "missing"}),
                "label": label,
                "acceptance_current": current,
                "acceptance_reasons": reasons,
                "source_checks": source_checks,
                "source_coverage_version": sources["version"],
                "review_digest": handoff_digest(
                    connection, tenant_id, project_id, key, item, sources
                ),
            }
        )
    # Some live blockers apply to multiple stages; keep one actionable row.
    blockers = list({item["key"]: item for item in blockers}.values())
    return {
        "ready": not blockers,
        "blockers": blockers,
        "handoff_items": handoffs,
        "issue_policy": {
            "low": project["issue_verify_low"],
            "medium": project["issue_verify_medium"],
        },
        "evaluated_at": datetime.now(UTC),
    }


def _record(
    connection: Connection,
    *,
    tenant_id: UUID,
    project_id: UUID,
    actor_user_id: UUID,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> None:
    # A changed handoff or policy reopens a completed project for re-acceptance.
    connection.execute(
        tables.projects.update()
        .where(
            tables.projects.c.tenant_id == tenant_id,
            tables.projects.c.id == project_id,
            tables.projects.c.status == "completed",
        )
        .values(status="active", updated_at=datetime.now(UTC))
    )
    status = connection.execute(
        select(tables.projects.c.status).where(
            tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
        )
    ).scalar_one()

    def clean(value: Any) -> Any:
        return json.loads(json.dumps(value, default=str))

    EventAuditWriter(
        connection, tenant_id=tenant_id, project_id=project_id, actor_user_id=actor_user_id
    ).record(
        EventDraft(
            event_id=f"project:{project_id}:{action}:{uuid4()}",
            event_type="PROJECT_UPDATED",
            source="project_service",
            entity_id=project_id,
            payload={"changed_fields": [action], "status": status},
        ),
        AuditDraft(
            action=action,
            before_snapshot=clean(before) if before else None,
            after_snapshot=clean(after),
            context=clean(context or {}),
        ),
    )


class ProjectCompletionService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get(self, *, tenant_id: UUID, project_id: UUID) -> dict[str, Any]:
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            result = readiness(connection, tenant_id=tenant_id, project_id=project_id)
            result["documents"] = [
                dict(row)
                for row in connection.execute(
                    select(tables.documents.c.id, tables.documents.c.filename).where(
                        tables.documents.c.tenant_id == tenant_id,
                        tables.documents.c.project_id == project_id,
                    )
                ).mappings()
            ]
            result["members"] = [
                dict(row)
                for row in connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name)
                    .join(
                        tables.project_members,
                        (tables.project_members.c.tenant_id == tables.users.c.tenant_id)
                        & (tables.project_members.c.user_id == tables.users.c.id),
                    )
                    .where(
                        tables.users.c.tenant_id == tenant_id,
                        tables.users.c.is_active.is_(True),
                        tables.users.c.role.in_(
                            ("owner", "admin", "project_manager", "engineer", "quality")
                        ),
                        tables.project_members.c.project_id == project_id,
                    )
                ).mappings()
            ]
            return result

    def handoff_history(
        self, *, tenant_id: UUID, project_id: UUID, item_key: str, before_id: int | None = None
    ) -> dict[str, Any]:
        if item_key not in HANDOFF_ITEMS:
            raise CompletionError("未知交接项")
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    handoff_history_statement(tenant_id, project_id, item_key, before_id)
                )
                .mappings()
                .all()
            )
            return {
                "items": [_plain(row) for row in rows[:20]],
                "next_before_id": rows[19]["id"] if len(rows) > 20 else None,
            }

    @staticmethod
    def _lock(connection: Connection, tenant_id: UUID, project_id: UUID) -> None:
        if not lock_project_write_scope(connection, tenant_id=tenant_id, project_id=project_id):
            raise CompletionError("项目不存在")
        if (
            connection.execute(
                select(tables.projects.c.status).where(
                    tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
                )
            ).scalar_one()
            == "archived"
        ):
            raise CompletionError("已归档项目不可修改")

    def prepare(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        item_key: str,
        document_id: UUID,
        receiver_user_id: UUID,
        note: str,
        request_id: UUID | None = None,
        expected_digest: str | None = None,
        receiver_change_reason: str | None = None,
    ) -> dict[str, Any]:
        if item_key not in HANDOFF_ITEMS or not note.strip():
            raise CompletionError("交接项与说明不能为空")
        with self.engine.begin() as connection:
            self._lock(connection, tenant_id, project_id)
            fingerprint = digest(
                {
                    "action": "prepare",
                    "item_key": item_key,
                    "document_id": str(document_id),
                    "receiver_user_id": str(receiver_user_id),
                    "note": note,
                    "expected_digest": expected_digest,
                    "receiver_change_reason": receiver_change_reason,
                }
            )
            replay = handoff_replay(
                connection, tenant_id, project_id, actor_user_id, request_id, fingerprint
            )
            if replay is not None:
                return replay
            if not _member(connection, tenant_id, project_id, receiver_user_id):
                raise CompletionError("接收人须为项目中的有效内部成员")
            table = tables.project_handoff_items
            before = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.item_key == item_key,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if expected_digest is not None and expected_digest != handoff_digest(
                connection, tenant_id, project_id, item_key, before
            ):
                raise CompletionError("交接记录或依据已变化，请刷新并重新核对")
            if receiver_change_reason is not None and (
                before is None
                or not receiver_change_reason.strip()
                or expected_digest is None
                or before["receiver_user_id"] == receiver_user_id
                or before["document_id"] != document_id
                or before["note"] != note.strip()
            ):
                raise CompletionError("更换接收人须保留原文档与交接说明、核对原版本并填写原因")
            values = dict(
                document_id=document_id,
                receiver_user_id=receiver_user_id,
                prepared_by_user_id=actor_user_id,
                note=note.strip(),
                status="pending",
                responded_at=None,
                accepted_fingerprint=None,
                updated_at=datetime.now(UTC),
            )
            if (
                _fingerprint(connection, tenant_id, project_id, {**values, "item_key": item_key})
                is None
            ):
                raise CompletionError("请选择本项目已上传的证据文档")
            statement = (
                table.update().where(table.c.id == before["id"])
                if before
                else table.insert().values(
                    id=uuid4(), tenant_id=tenant_id, project_id=project_id, item_key=item_key
                )
            )
            after = dict(
                connection.execute(statement.values(**values).returning(table)).mappings().one()
            )
            _record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                action="project.handoff.prepare",
                before=dict(before) if before else None,
                after=after,
                context=handoff_audit(
                    connection,
                    tenant_id,
                    project_id,
                    actor_user_id,
                    before,
                    after,
                    request_id,
                    fingerprint,
                    receiver_change_reason,
                ),
            )
            return {**after, "request_id": str(request_id)} if request_id else after

    def respond(
        self,
        *,
        tenant_id: UUID,
        project_id: UUID,
        actor_user_id: UUID,
        item_key: str,
        accept: bool,
        note: str,
        request_id: UUID | None = None,
        expected_digest: str | None = None,
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            self._lock(connection, tenant_id, project_id)
            request_fingerprint = digest(
                {
                    "action": "accept" if accept else "return",
                    "item_key": item_key,
                    "note": note,
                    "expected_digest": expected_digest,
                }
            )
            replay = handoff_replay(
                connection, tenant_id, project_id, actor_user_id, request_id, request_fingerprint
            )
            if replay is not None:
                return replay
            table = tables.project_handoff_items
            before = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.project_id == project_id,
                        table.c.item_key == item_key,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                before is None
                or actor_user_id != before["receiver_user_id"]
                or not _member(connection, tenant_id, project_id, actor_user_id)
            ):
                raise CompletionError("仅指定的有效接收人可以接收或退回此项")
            if expected_digest is not None and expected_digest != handoff_digest(
                connection, tenant_id, project_id, item_key, before
            ):
                raise CompletionError("交接内容、接收人或依据已变化，请刷新并重新核对")
            if not note.strip():
                raise CompletionError("请填写接收或退回说明")
            values = dict(
                status="accepted" if accept else "returned",
                note=note.strip(),
                responded_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            fingerprint = (
                _fingerprint(connection, tenant_id, project_id, {**dict(before), **values})
                if accept
                else None
            )
            if accept and fingerprint is None:
                raise CompletionError("证据文档已不可用，请重新提交")
            after = dict(
                connection.execute(
                    table.update()
                    .where(table.c.id == before["id"])
                    .values(**values, accepted_fingerprint=fingerprint)
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                action="project.handoff.accept" if accept else "project.handoff.return",
                before=dict(before),
                after=after,
                context=handoff_audit(
                    connection,
                    tenant_id,
                    project_id,
                    actor_user_id,
                    before,
                    after,
                    request_id,
                    request_fingerprint,
                ),
            )
            return {**after, "request_id": str(request_id)} if request_id else after

    def set_policy(
        self, *, tenant_id: UUID, project_id: UUID, actor_user_id: UUID, low: bool, medium: bool
    ) -> None:
        with self.engine.begin() as connection:
            self._lock(connection, tenant_id, project_id)
            before = (
                connection.execute(
                    select(
                        tables.projects.c.issue_verify_low, tables.projects.c.issue_verify_medium
                    ).where(
                        tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id
                    )
                )
                .mappings()
                .one()
            )
            values = {"issue_verify_low": low, "issue_verify_medium": medium}
            connection.execute(
                tables.projects.update()
                .where(tables.projects.c.tenant_id == tenant_id, tables.projects.c.id == project_id)
                .values(**values, updated_at=datetime.now(UTC))
            )
            _record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                action="project.issue_verification_policy",
                before=dict(before),
                after=values,
            )
