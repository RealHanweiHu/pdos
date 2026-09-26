"""Version-bound industrial-design proposals and feedback; revisions never overwrite history."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, func, or_, select

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
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft


class DesignRevisionDraft(Contract):
    request_id: UUID
    variant_id: UUID | None = None
    expected_version: int = Field(ge=0)
    title: Text = Field(max_length=512)
    owner_user_id: UUID
    brief: Text
    envelope: Text | None = None
    cmf: Text | None = None
    layout: Text | None = None
    interfaces: Text | None = None
    document_id: UUID | None = None
    external_file_reference_id: UUID | None = None
    reason: Text

    @model_validator(mode="after")
    def source_and_revision(self) -> Self:
        if self.document_id and self.external_file_reference_id:
            raise ValueError("一次版本请选择一份主图档或外部文件引用")
        if (self.variant_id is None) != (self.expected_version == 0):
            raise ValueError("新方案从版本0开始，修订须指定已有版本")
        return self


class DesignFeedbackDraft(Contract):
    request_id: UUID
    expected_revision_digest: Digest
    source_kind: Literal["customer", "internal"]
    source_reference: Text
    reported_at: AwareDatetime | None = None
    topic: Literal["appearance", "ergonomics", "cmf", "interface", "cost", "other"]
    content: Text


class DesignFeedbackDecision(Contract):
    request_id: UUID
    expected_version: int = Field(ge=0)
    action: Literal["planned", "needs_decision", "rejected", "addressed"]
    resolution_revision_id: UUID | None = None
    reason: Text

    @model_validator(mode="after")
    def resolution(self) -> Self:
        if (self.action == "addressed") != (self.resolution_revision_id is not None):
            raise ValueError("反馈已处理必须指向实际后续版本；其他意见不能冒充修订完成")
        return self


def _get(
    connection: Connection, context: AuthContext, project_id: UUID, table: Any, record_id: UUID
) -> Any:
    row = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.project_id == project_id,
                table.c.id == record_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ProductWorkAccessError("设计记录不存在或不属于当前项目")
    return row


def _prior(
    connection: Connection, context: AuthContext, table: Any, request_id: UUID, fingerprint: str
) -> Any:
    row = (
        connection.execute(
            select(table).where(
                table.c.tenant_id == context.tenant.id,
                table.c.created_by_user_id == context.user.id,
                table.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row and row["request_digest"] != fingerprint:
        raise ProductWorkError("请求编号已用于不同的设计内容")
    return row


def _event(
    connection: Connection,
    context: AuthContext,
    project_id: UUID,
    record_id: UUID,
    action: str,
    snapshot: dict[str, Any],
) -> None:
    EventAuditWriter(
        connection,
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
        project_id=project_id,
    ).record(
        EventDraft(
            event_id=f"id-design:{record_id}:{action}",
            event_type="ID_DESIGN_RECORDED",
            source="design_service",
            entity_id=record_id,
            payload={"record_id": str(record_id), "action": action},
        ),
        AuditDraft(action=f"id_design.{action}", after_snapshot=snapshot),
    )


def _latest(
    connection: Connection, context: AuthContext, project_id: UUID, variant_id: UUID
) -> Any:
    t = tables.id_design_revisions
    return (
        connection.execute(
            select(t)
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project_id,
                t.c.variant_id == variant_id,
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


class IdDesignService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, context: AuthContext, project_id: UUID) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_VIEW)
        with self.engine.connect() as connection:
            project = _project(connection, context, project_id)

            def rows(table: Any, limit: int) -> list[Any]:
                return list(
                    connection.execute(
                        select(table)
                        .where(
                            table.c.tenant_id == context.tenant.id, table.c.project_id == project_id
                        )
                        .order_by(table.c.created_at.desc(), table.c.id)
                        .limit(limit + 1)
                    ).mappings()
                )

            variants, revisions, feedback = (
                rows(tables.id_design_variants, 200),
                rows(tables.id_design_revisions, 1000),
                rows(tables.id_design_feedback, 500),
            )
            decisions = tables.id_design_feedback_decisions
            history = list(
                connection.execute(
                    select(decisions)
                    .where(
                        decisions.c.tenant_id == context.tenant.id,
                        decisions.c.project_id == project_id,
                        decisions.c.feedback_id.in_([row["id"] for row in feedback[:500]]),
                    )
                    .order_by(decisions.c.version.desc(), decisions.c.id)
                ).mappings()
            )
            latest_decisions: dict[UUID, Any] = {}
            for row in history:
                latest_decisions.setdefault(row["feedback_id"], row)
            members = select(tables.project_members.c.user_id).where(
                tables.project_members.c.tenant_id == context.tenant.id,
                tables.project_members.c.project_id == project_id,
            )
            people = connection.execute(
                select(tables.users.c.id, tables.users.c.display_name)
                .where(
                    tables.users.c.tenant_id == context.tenant.id,
                    tables.users.c.is_active.is_(True),
                    tables.users.c.role.in_(
                        ("owner", "admin", "project_manager", "engineer", "quality")
                    ),
                    or_(
                        tables.users.c.id.in_(members), tables.users.c.role.in_(("owner", "admin"))
                    ),
                )
                .order_by(tables.users.c.display_name)
            ).mappings()
            artifacts = []
            for table, kind in (
                (tables.documents, "document"),
                (tables.external_file_references, "external"),
            ):
                for row in connection.execute(
                    select(table.c.id, table.c.filename)
                    .where(table.c.tenant_id == context.tenant.id, table.c.project_id == project_id)
                    .order_by(table.c.created_at.desc())
                    .limit(500)
                ).mappings():
                    artifacts.append({**_plain(row), "kind": kind})
            return {
                "frozen_variant_ids": [
                    str(value)
                    for value in connection.execute(
                        select(tables.id_design_freezes.c.variant_id).where(
                            tables.id_design_freezes.c.tenant_id == context.tenant.id,
                            tables.id_design_freezes.c.project_id == project_id,
                        )
                    ).scalars()
                ],
                "variants": [_plain(row) for row in variants[:200]],
                "revisions": [_plain(row) for row in revisions[:1000]],
                "feedback": [
                    {
                        **_plain(row),
                        "decision": _plain(latest_decisions[row["id"]])
                        if row["id"] in latest_decisions
                        else None,
                    }
                    for row in feedback[:500]
                ],
                "decision_history": [_plain(row) for row in history],
                "people": [_plain(row) for row in people],
                "artifacts": artifacts,
                "has_more": len(variants) > 200 or len(revisions) > 1000 or len(feedback) > 500,
                "current_user_id": str(context.user.id),
                "can_manage": is_allowed(context.user.role, Action.PROJECT_EDIT),
                "can_revise": is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_EDIT)
                and project["status"] in ("approved", "active", "on_hold"),
                "can_decide": is_allowed(context.user.role, Action.PRODUCT_ENGINEERING_EDIT)
                and project["status"] != "archived",
                "can_feedback": is_allowed(context.user.role, Action.WORK_ITEM_EDIT)
                and project["status"] != "archived",
            }

    def revision_context(
        self, context: AuthContext, project_id: UUID, revision_id: UUID
    ) -> dict[str, Any]:
        result = self.get(context, project_id)
        with self.engine.connect() as connection:
            _project(connection, context, project_id)
            result["revision"] = _plain(
                _get(connection, context, project_id, tables.id_design_revisions, revision_id)
            )
        return {
            key: result[key]
            for key in (
                "revision",
                "people",
                "artifacts",
                "current_user_id",
                "can_manage",
                "can_revise",
                "can_decide",
            )
        }

    def revise(
        self, context: AuthContext, project_id: UUID, command: DesignRevisionDraft
    ) -> dict[str, Any]:
        with self.engine.begin() as connection:
            return self.revise_in_transaction(connection, context, project_id, command)

    def revise_in_transaction(
        self,
        connection: Connection,
        context: AuthContext,
        project_id: UUID,
        command: DesignRevisionDraft,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_EDIT)
        fingerprint = digest({"project_id": str(project_id), **command.model_dump(mode="json")})
        project = _project(connection, context, project_id, write=True)
        _person(connection, context, project_id, context.user.id)
        table = tables.id_design_revisions
        prior = _prior(connection, context, table, command.request_id, fingerprint)
        if prior:
            return _plain(prior)
        if project["status"] not in ("approved", "active", "on_hold"):
            raise ProductWorkError("当前项目状态不能编制设计版本")
        _person(connection, context, project_id, command.owner_user_id)
        previous = None
        variant_id = command.variant_id or uuid4()
        if command.variant_id:
            from app.domain.id_design_freeze import frozen_variant

            if frozen_variant(connection, context, project_id, variant_id):
                raise ProductWorkError("已冻结方案不能直接修订；新增要求须经变更候选办理")
            variant = _get(connection, context, project_id, tables.id_design_variants, variant_id)
            previous = _latest(connection, context, project_id, variant_id)
            if previous is None or previous["version"] != command.expected_version:
                raise ProductWorkError("方案已有新版本，请刷新后继续修订")
            if previous["owner_user_id"] != context.user.id and not is_allowed(
                context.user.role, Action.PROJECT_EDIT
            ):
                raise ProductWorkAccessError("仅当前设计负责人或项目管理人员可修订")
            if command.title != variant["title"]:
                raise ProductWorkError("修订应沿用方案名称；不同方向请新建独立方案")
        artifact = {}
        artifact_id = command.document_id or command.external_file_reference_id
        if artifact_id:
            file_table = (
                tables.documents if command.document_id else tables.external_file_references
            )
            row = _get(connection, context, project_id, file_table, artifact_id)
            artifact = {
                "id": str(row["id"]),
                "kind": "document" if command.document_id else "external",
                "filename": row["filename"],
                "digest": row["sha256"] if command.document_id else row["source_hash"],
                "classification": row["classification"],
            }
        if not command.variant_id:
            connection.execute(
                tables.id_design_variants.insert().values(
                    id=variant_id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    title=command.title,
                    created_by_user_id=context.user.id,
                    request_id=command.request_id,
                    request_digest=fingerprint,
                )
            )
        values = {
            **command.model_dump(exclude={"request_id", "variant_id", "expected_version", "title"}),
            "id": uuid4(),
            "tenant_id": context.tenant.id,
            "project_id": project_id,
            "variant_id": variant_id,
            "version": command.expected_version + 1,
            "previous_revision_id": previous["id"] if previous else None,
            "artifact_snapshot": artifact,
            "created_by_user_id": context.user.id,
            "request_id": command.request_id,
            "request_digest": fingerprint,
        }
        values["payload_digest"] = digest(_plain(values))
        result = (
            connection.execute(table.insert().values(**values).returning(table)).mappings().one()
        )
        _event(connection, context, project_id, result["id"], "revision", _plain(result))
        return _plain(result)

    def feedback(
        self,
        context: AuthContext,
        project_id: UUID,
        revision_id: UUID,
        command: DesignFeedbackDraft,
    ) -> dict[str, Any]:
        _role(context, Action.WORK_ITEM_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "revision_id": str(revision_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_feedback
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] == "archived":
                raise ProductWorkError("归档项目不能追加设计反馈")
            revision = _get(
                connection, context, project_id, tables.id_design_revisions, revision_id
            )
            if revision["payload_digest"] != command.expected_revision_digest:
                raise ProductWorkError("反馈对应的方案版本不一致")
            if command.reported_at and command.reported_at > datetime.now(UTC):
                raise ProductWorkError("反馈发生时间不能晚于当前时间")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        revision_id=revision_id,
                        **command.model_dump(exclude={"expected_revision_digest"}),
                        created_by_user_id=context.user.id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            from app.domain.id_design_freeze import frozen_variant

            freeze = frozen_variant(connection, context, project_id, revision["variant_id"])
            if freeze:
                candidate = (
                    connection.execute(
                        tables.id_design_change_candidates.insert()
                        .values(
                            id=uuid4(),
                            tenant_id=context.tenant.id,
                            project_id=project_id,
                            freeze_id=freeze["id"],
                            feedback_id=row["id"],
                            created_by_user_id=context.user.id,
                            request_id=command.request_id,
                            request_digest=fingerprint,
                        )
                        .returning(tables.id_design_change_candidates)
                    )
                    .mappings()
                    .one()
                )
                _event(
                    connection,
                    context,
                    project_id,
                    candidate["id"],
                    "change_candidate",
                    _plain(candidate),
                )
            _event(connection, context, project_id, row["id"], "feedback", _plain(row))
            return _plain(row)

    def decide(
        self,
        context: AuthContext,
        project_id: UUID,
        feedback_id: UUID,
        command: DesignFeedbackDecision,
    ) -> dict[str, Any]:
        _role(context, Action.PRODUCT_ENGINEERING_EDIT)
        fingerprint = digest(
            {
                "project_id": str(project_id),
                "feedback_id": str(feedback_id),
                **command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as connection:
            project = _project(connection, context, project_id, write=True)
            _person(connection, context, project_id, context.user.id)
            table = tables.id_design_feedback_decisions
            prior = _prior(connection, context, table, command.request_id, fingerprint)
            if prior:
                return _plain(prior)
            if project["status"] == "archived":
                raise ProductWorkError("归档项目不能处理设计反馈")
            feedback = _get(connection, context, project_id, tables.id_design_feedback, feedback_id)
            revision = _get(
                connection, context, project_id, tables.id_design_revisions, feedback["revision_id"]
            )
            current = _latest(connection, context, project_id, revision["variant_id"])
            if current["owner_user_id"] != context.user.id and not is_allowed(
                context.user.role, Action.PROJECT_EDIT
            ):
                raise ProductWorkAccessError("仅当前设计负责人或项目管理人员可处理反馈")
            version = (
                connection.execute(
                    select(func.max(table.c.version)).where(
                        table.c.tenant_id == context.tenant.id, table.c.feedback_id == feedback_id
                    )
                ).scalar_one()
                or 0
            )
            if version != command.expected_version:
                raise ProductWorkError("反馈已有新的处理意见，请刷新")
            if command.resolution_revision_id:
                resolution = _get(
                    connection,
                    context,
                    project_id,
                    tables.id_design_revisions,
                    command.resolution_revision_id,
                )
                if (
                    resolution["variant_id"] != revision["variant_id"]
                    or resolution["version"] <= revision["version"]
                ):
                    raise ProductWorkError("处理完成必须指向同一方案的实际后续版本")
            row = (
                connection.execute(
                    table.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=context.tenant.id,
                        project_id=project_id,
                        feedback_id=feedback_id,
                        version=version + 1,
                        **command.model_dump(exclude={"expected_version"}),
                        created_by_user_id=context.user.id,
                        request_digest=fingerprint,
                    )
                    .returning(table)
                )
                .mappings()
                .one()
            )
            _event(connection, context, project_id, row["id"], "feedback_decision", _plain(row))
            return _plain(row)
