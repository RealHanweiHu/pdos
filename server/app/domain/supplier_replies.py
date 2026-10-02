"""One-confirmation internal reply updates bound to an existing supplier observation."""

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.contracts.common_objects import Contract, Digest, Text
from app.db.schema import tables
from app.domain.build_materials import BuildMaterialService
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, _plain, digest
from app.domain.supplier_engineering import (
    EngineeringApply,
    EngineeringDraft,
    SupplierEngineeringService,
    TimedEvidence,
    preview,
)


class ReplyDraft(Contract):
    update: Literal["first_response", "sample_received"]
    at: AwareDatetime
    evidence_id: UUID
    location: Text
    reason: Text

    @model_validator(mode="after")
    def observed_time(self) -> Self:
        if self.at > datetime.now(UTC):
            raise ValueError("实际回复或收样时间不能填写未来时间")
        return self


class ReplyConfirm(ReplyDraft):
    request_id: UUID
    expected_version: int = Field(ge=1)
    expected_digest: Digest
    evidence_checked: Literal[True]


def prepare_reply(original: EngineeringDraft, reply: ReplyDraft) -> EngineeringDraft:
    if original.status != "active" or original.kind == "engineering_failure":
        raise ProductWorkError("回复更新须关联有效的样品交付或技术响应原事项")
    field = "responded" if reply.update == "first_response" else "received"
    if field == "received" and original.kind != "sample_delivery":
        raise ProductWorkError("实际收样只能关联原样品交付事项")
    if getattr(original, field) is not None:
        raise ProductWorkError("原事项已有此实际事实；纠错请沿原事项具名修订，不能覆盖首次记录")
    values = original.model_dump(mode="json")
    values[field] = TimedEvidence(
        at=reply.at, evidence_id=reply.evidence_id, location=reply.location
    ).model_dump(mode="json")
    values.update(evidence_id=str(reply.evidence_id), reason=reply.reason)
    return EngineeringDraft.model_validate(values)


def reply_preview(
    c: Connection,
    context: AuthContext,
    project: UUID,
    supplier: UUID,
    record: UUID,
    command: ReplyDraft,
) -> dict[str, Any]:
    BuildMaterialService._authorize(c, context, project, write=True)
    t = tables.supplier_engineering_records
    original = (
        c.execute(
            select(t)
            .where(
                t.c.tenant_id == context.tenant.id,
                t.c.project_id == project,
                t.c.supplier_id == supplier,
                t.c.record_id == record,
            )
            .order_by(t.c.version.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if original is None:
        raise ProductWorkError("请选择本项目该供方的原工程事项，回复不能另建业务真值")
    proposed = prepare_reply(EngineeringDraft.model_validate(original["payload"]), command)
    engineering = preview(c, context, project, supplier, record, proposed)
    reply = ReplyDraft.model_validate(command.model_dump(include=set(ReplyDraft.model_fields)))
    value = {
        "tenant_id": str(context.tenant.id),
        "reviewer_user_id": str(context.user.id),
        "project_id": str(project),
        "supplier_id": str(supplier),
        "record_id": str(record),
        "previous_version": original["version"],
        "previous": _plain(dict(original)),
        "proposed": proposed.model_dump(mode="json"),
        "reply": reply.model_dump(mode="json"),
        "engineering": engineering,
        "notice": "一次确认只补齐内部实际回复/收样事实；供给数量、具名承诺及正式日期分别办理",
    }
    return {"basis": value, "digest": digest(value)}


class SupplierReplyService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def preview(
        self, context: AuthContext, project: UUID, supplier: UUID, record: UUID, command: ReplyDraft
    ) -> dict[str, Any]:
        with (
            self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
            c.begin(),
        ):
            return reply_preview(c, context, project, supplier, record, command)

    def confirm(
        self,
        context: AuthContext,
        project: UUID,
        supplier: UUID,
        record: UUID,
        command: ReplyConfirm,
    ) -> dict[str, Any]:
        signature = digest(
            {
                "project": str(project),
                "supplier": str(supplier),
                "record": str(record),
                "command": command.model_dump(mode="json"),
            }
        )
        with self.engine.begin() as c:
            NpiExecutionService._project(
                c, tenant_id=context.tenant.id, project_id=project, lock=True
            )
            BuildMaterialService._authorize(c, context, project, write=True)
            t = tables.supplier_engineering_records
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == context.tenant.id,
                        t.c.created_by_user_id == context.user.id,
                        t.c.request_id == command.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior:
                if prior["snapshot"].get("supplier_reply", {}).get("request_digest") != signature:
                    raise ProductWorkError("原确认请求已用于不同供方回复或工程记录")
                return _plain(dict(prior))
            observed = reply_preview(c, context, project, supplier, record, command)
            if (
                observed["digest"] != command.expected_digest
                or observed["basis"]["previous_version"] != command.expected_version
            ):
                raise ProductWorkError("原事项、供方、回复来源或证据已变化，请重新预览后确认")
            engineering = EngineeringApply.model_validate(
                {
                    **observed["basis"]["proposed"],
                    "expected_version": command.expected_version,
                    "expected_digest": observed["basis"]["engineering"]["digest"],
                    "request_id": command.request_id,
                }
            )
            return SupplierEngineeringService.apply_in_connection(
                c,
                context,
                project,
                supplier,
                record,
                engineering,
                supplier_reply={"request_digest": signature, "reply": observed["basis"]["reply"]},
            )
