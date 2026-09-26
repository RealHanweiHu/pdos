"""Actual certification work, kept distinct from certificate validity dates."""

from datetime import UTC, date, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.product_workspace import (
    ProductWorkAccessError,
    ProductWorkError,
    _plain,
    _role,
    digest,
)
from app.domain.project_execution import _person
from app.domain.resource_reservations import _project
from app.domain.schedule_execution import guard_source_action
from app.domain.schedule_node_state import certification_status
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class CertificationAction(Contract):
    request_id: UUID
    expected_digest: Digest
    action: Literal["start", "complete"]
    evidence: Text
    certificate_number: str | None = Field(default=None, min_length=1, max_length=256)
    issuing_body: str | None = Field(default=None, min_length=1, max_length=256)
    valid_from: date | None = None
    valid_until: date | None = None
    evidence_reference: Text | None = None

    @model_validator(mode="after")
    def completion_fields(self) -> Self:
        fields = (
            self.certificate_number,
            self.issuing_body,
            self.valid_from,
            self.valid_until,
            self.evidence_reference,
        )
        if self.action == "start" and any(value is not None for value in fields):
            raise ValueError("开工办理只填写开始依据；证书资料在完成时核对")
        if self.action == "complete" and (
            not self.certificate_number
            or not self.issuing_body
            or self.valid_until is None
            or not self.evidence_reference
        ):
            raise ValueError("完成认证须填写证书编号、签发机构、有效期和证据引用")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("证书有效期结束不能早于开始")
        return self


class RecertificationDraft(Contract):
    request_id: UUID
    expected_digest: Digest
    reason: Text
    owner_user_id: UUID | None = None


def can_handle(context: AuthContext, certification: Any) -> bool:
    return is_allowed(context.user.role, Action.QUALITY_MANAGE) and (
        certification["owner_user_id"] == context.user.id
        or is_allowed(context.user.role, Action.PROJECT_EDIT)
    )


class CertificationExecutionService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def recertify(
        self,
        context: AuthContext,
        project_id: UUID,
        certification_id: UUID,
        command: RecertificationDraft,
    ) -> dict[str, Any]:
        _role(context, Action.QUALITY_MANAGE)
        try:
            with self.engine.begin() as connection:
                project = _project(connection, context, project_id, write=True)
                _person(connection, context, project_id, context.user.id)
                table = tables.certifications
                fingerprint = digest(
                    {
                        "project_id": str(project_id),
                        "certification_id": str(certification_id),
                        **command.model_dump(mode="json"),
                    }
                )
                prior = (
                    connection.execute(
                        select(table).where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.created_by_user_id == context.user.id,
                            table.c.recertification_request_id == command.request_id,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior is not None:
                    if prior["recertification_request_digest"] != fingerprint:
                        raise ProductWorkError("请求编号已用于另一项重新认证")
                    return _plain(prior)
                source = (
                    connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id,
                            table.c.project_id == project_id,
                            table.c.id == certification_id,
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if source is None:
                    raise ProductWorkAccessError("原认证不存在或不属于当前项目")
                if not can_handle(context, source):
                    raise ProductWorkAccessError("由具备品质权限的负责人或项目管理人员发起重新认证")
                if project["status"] in ("completed", "archived") or source["status"] == "draft":
                    raise ProductWorkError("项目已结束或原认证尚未形成结论")
                if digest(_plain(source)) != command.expected_digest:
                    raise ProductWorkError("原证书资料已变化，请刷新后核对")
                owner_id = command.owner_user_id or context.user.id
                _person(connection, context, project_id, owner_id)
                new_id = uuid4()
                row = (
                    connection.execute(
                        table.insert()
                        .values(
                            id=new_id,
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            owner_user_id=owner_id,
                            created_by_user_id=context.user.id,
                            certificate_type=source["certificate_type"],
                            target_markets=source["target_markets"],
                            is_required=source["is_required"],
                            status="draft",
                            replaces_certification_id=certification_id,
                            recertification_reason=command.reason,
                            recertification_request_id=command.request_id,
                            recertification_request_digest=fingerprint,
                            recertification_source_digest=command.expected_digest,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .one()
                )
                EventAuditWriter(
                    connection,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    actor_user_id=context.user.id,
                ).record(
                    EventDraft(
                        event_id=f"certification:{new_id}:recertification",
                        event_type="NPI_RECORD_CHANGED",
                        source="npi_service",
                        entity_id=new_id,
                        payload={
                            "record_type": "certification",
                            "action": "recertification_created",
                        },
                    ),
                    AuditDraft(
                        action="npi.certification.recertification_created",
                        after_snapshot=_plain(row),
                        context={
                            "previous_certification_id": str(certification_id),
                            "reason": command.reason,
                            "previous_source_digest": command.expected_digest,
                        },
                    ),
                )
                return _plain(row)
        except IntegrityError as error:
            raise ProductWorkError("重新认证未创建，请刷新后核对原记录及请求") from error

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        _role(context, Action.QUALITY_VIEW)
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)
            rows = list(
                connection.execute(
                    select(tables.certifications)
                    .where(
                        tables.certifications.c.tenant_id == context.tenant.id,
                        tables.certifications.c.project_id == project_id,
                    )
                    .order_by(tables.certifications.c.created_at.desc(), tables.certifications.c.id)
                    .limit(501)
                ).mappings()
            )
            actions = tables.certification_execution_actions
            history = list(
                connection.execute(
                    select(actions)
                    .where(
                        actions.c.tenant_id == context.tenant.id,
                        actions.c.project_id == project_id,
                        actions.c.certification_id.in_([row["id"] for row in rows[:500]]),
                    )
                    .order_by(actions.c.created_at.desc(), actions.c.id)
                ).mappings()
            )
            ids = {row["owner_user_id"] for row in rows[:500]} | {
                row["actor_user_id"] for row in history
            }
            names = dict(
                connection.execute(
                    select(tables.users.c.id, tables.users.c.display_name).where(
                        tables.users.c.tenant_id == context.tenant.id,
                        tables.users.c.id.in_(ids),
                    )
                )
                .tuples()
                .all()
            )
            return {
                "items": [
                    {
                        **_plain(row),
                        "payload_digest": digest(_plain(row)),
                        "effective_status": certification_status(row),
                        "owner_name": names.get(row["owner_user_id"], "历史负责人"),
                        "can_recertify": can_handle(context, row)
                        and project["status"] not in ("completed", "archived")
                        and row["status"] != "draft",
                        "can_start": can_handle(context, row)
                        and project["status"] == "active"
                        and row["status"] == "draft"
                        and row["started_at"] is None,
                        "can_complete": can_handle(context, row)
                        and project["status"] in ("active", "on_hold")
                        and row["status"] == "draft"
                        and row["started_at"] is not None
                        and row["completed_at"] is None,
                    }
                    for row in rows[:500]
                ],
                "history": [
                    {**_plain(row), "actor_name": names.get(row["actor_user_id"], "历史办理人")}
                    for row in history
                ],
                "has_more": len(rows) > 500,
                "can_create": is_allowed(context.user.role, Action.QUALITY_MANAGE)
                and project["status"] not in ("completed", "archived"),
            }

    def act(
        self,
        context: AuthContext,
        project_id: UUID,
        certification_id: UUID,
        command: CertificationAction,
    ) -> dict[str, Any]:
        try:
            return self._act(context, project_id, certification_id, command)
        except IntegrityError as error:
            raise ProductWorkError("认证办理未生效，请刷新证书资料和办理记录") from error

    def _act(
        self,
        context: AuthContext,
        project_id: UUID,
        certification_id: UUID,
        command: CertificationAction,
    ) -> dict[str, Any]:
        _role(context, Action.QUALITY_MANAGE)
        tenant_id = context.tenant.id
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.certification_execution_actions
            fingerprint = digest(
                {
                    "project_id": str(project_id),
                    "certification_id": str(certification_id),
                    **command.model_dump(mode="json"),
                }
            )
            prior = (
                connection.execute(
                    select(table).where(
                        table.c.tenant_id == tenant_id,
                        table.c.actor_user_id == context.user.id,
                        table.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != fingerprint:
                    raise ProductWorkError("请求编号已用于另一项认证办理")
                return _plain(prior)
            before = (
                connection.execute(
                    select(tables.certifications)
                    .where(
                        tables.certifications.c.tenant_id == tenant_id,
                        tables.certifications.c.project_id == project_id,
                        tables.certifications.c.id == certification_id,
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if before is None:
                raise ProductWorkAccessError("认证记录不存在或不属于当前项目")
            if not can_handle(context, before):
                raise ProductWorkAccessError("由具备品质办理权限的负责人或项目管理人员办理")
            if digest(_plain(before)) != command.expected_digest:
                raise ProductWorkError("认证资料已变化，请刷新后核对")
            if before["status"] != "draft" or before["completed_at"] is not None:
                raise ProductWorkError(
                    "已有证书结论，不能重新写入实际办理时间；重新认证应登记新记录"
                )
            now = datetime.now(UTC)
            values: dict[str, Any] = {"updated_at": now}
            if command.action == "start":
                if project["status"] != "active" or before["started_at"] is not None:
                    raise ProductWorkError("项目须已激活，且此认证尚未开始")
                values["started_at"] = now
            else:
                if project["status"] not in ("active", "on_hold") or before["started_at"] is None:
                    raise ProductWorkError("请先记录认证开工，再办理完成")
                if (
                    command.valid_until is None
                    or command.valid_until < now.date()
                    or (command.valid_from and command.valid_from > now.date())
                ):
                    raise ProductWorkError("完成时登记的证书须处于有效期内")
                values.update(
                    status="valid",
                    completed_at=now,
                    certificate_number=command.certificate_number,
                    issuing_body=command.issuing_body,
                    valid_from=command.valid_from,
                    valid_until=command.valid_until,
                    evidence_reference=command.evidence_reference,
                )
            before_snapshot = _plain(before)
            after_snapshot = _plain({**dict(before), **values})
            guard_source_action(
                connection,
                tenant_id,
                project_id,
                certification_id,
                "certification",
                f"npi.certification.{command.action}",
                after_snapshot,
                now,
            )
            connection.execute(
                tables.certifications.update()
                .where(
                    tables.certifications.c.tenant_id == tenant_id,
                    tables.certifications.c.project_id == project_id,
                    tables.certifications.c.id == certification_id,
                )
                .values(**values)
            )
            action_id = uuid4()
            written = EventAuditWriter(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                actor_user_id=context.user.id,
            ).record(
                EventDraft(
                    event_id=f"certification:{certification_id}:{command.action}:{action_id}",
                    event_type="NPI_RECORD_CHANGED",
                    source="npi_service",
                    entity_id=certification_id,
                    payload={"record_type": "certification", "action": command.action},
                    occurred_at=now,
                ),
                AuditDraft(
                    action=f"npi.certification.{command.action}",
                    before_snapshot=before_snapshot,
                    after_snapshot=after_snapshot,
                    context={"execution_action_id": str(action_id), "evidence": command.evidence},
                ),
            )
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=action_id,
                        tenant_id=tenant_id,
                        project_id=project_id,
                        certification_id=certification_id,
                        action=command.action,
                        actor_user_id=context.user.id,
                        evidence=command.evidence,
                        before_snapshot=before_snapshot,
                        after_snapshot=after_snapshot,
                        event_row_id=written.event_row_id,
                        audit_row_id=written.audit_row_id,
                        request_id=command.request_id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            return _plain(row)
