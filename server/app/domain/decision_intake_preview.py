"""Historical decision originals mapped without creating or backdating an approval."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, select

from app.auth.repository import AuthContext
from app.db.schema import tables
from app.domain.conversation_attachments import (
    ConversationAttachmentService,
    message_attachment_ids,
)
from app.domain.conversations import ConversationError
from app.domain.issue_intake_preview import (
    SHEET,
    Column,
    IssueIntakePreviews,
    source_identity,
    workbook_rows,
)
from app.domain.product_workspace import _plain, digest

PARSER = "decision-list-extracted-v1"


class DecisionListMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(min_length=1, max_length=200)
    first_row: int = Field(ge=1, le=1048576)
    last_row: int = Field(ge=1, le=1048576)
    title: Column
    outcome: Column
    context: Column | None = None
    options: Column | None = None
    trade_offs: Column | None = None
    rationale: Column | None = None
    consequence: Column | None = None
    historical_date: Column | None = None
    historical_approver: Column | None = None
    historical_owner: Column | None = None
    historical_kind: Column | None = None
    historical_state: Column | None = None
    external_ref: Column | None = None
    issue_ref: Column | None = None
    date_format: Literal["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY"] = "YYYY-MM-DD"

    @model_validator(mode="after")
    def bounded(self) -> "DecisionListMapping":
        if self.last_row < self.first_row or self.last_row - self.first_row >= 200:
            raise ValueError("每批请选择连续的1至200行")
        return self


class DecisionIntakePrepare(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    attachment_id: UUID
    permission_basis: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    mapping: DecisionListMapping


def check_source(row: Any, parser_version: str = PARSER) -> None:
    if parser_version == "decision-ai-cited-v1":
        from app.domain.intake_ai_sources import check_source as check_cited_source

        check_cited_source(row)
        return

    extension = {
        PARSER: ".xlsx",
        "decision-pdf-extracted-v1": ".pdf",
        "decision-email-extracted-v1": ".eml",
    }.get(parser_version)
    if (
        row["revoked_at"] is not None
        or row["status"] != "extracted"
        or row["classification"] != "internal"
        or extension is None
        or not row["filename"].lower().endswith(extension)
    ):
        raise ConversationError("请使用本条消息中已抽取、未撤回的内部PDF/XLSX/授权EML决策资料")


def mapped_rows(
    fragments: list[dict[str, Any]], mapping: DecisionListMapping
) -> list[dict[str, Any]]:
    cells_by_row = workbook_rows(fragments, mapping.sheet)
    columns = {
        key: value
        for key, value in mapping.model_dump().items()
        if key not in {"sheet", "first_row", "last_row", "date_format"} and value is not None
    }
    formats = {
        "YYYY-MM-DD": "%Y-%m-%d",
        "YYYY/MM/DD": "%Y/%m/%d",
        "DD/MM/YYYY": "%d/%m/%Y",
        "MM/DD/YYYY": "%m/%d/%Y",
    }
    result = []
    for number in range(mapping.first_row, mapping.last_row + 1):
        cells = cells_by_row.get(number, {})
        original = {
            key: {"cell": f"{column}{number}", "value": cells.get(column, "")}
            for key, column in columns.items()
        }
        values = {key: item["value"] for key, item in original.items()}
        errors = []
        for key in ("title", "outcome"):
            if not values.get(key, "").strip():
                errors.append("决策标题或结论缺少原文，请核对映射及行范围")
                break
        for key, value in values.items():
            if value.startswith("="):
                errors.append(f"{original[key]['cell']}是公式原文，不能当作求值后的决策事实")
            if len(value) > (512 if key == "title" else 20000):
                errors.append(f"{original[key]['cell']}超过可登记的字段长度")
        historical_date = None
        if values.get("historical_date"):
            raw = values["historical_date"]
            if mapping.date_format == "YYYY-MM-DD" and raw.endswith(" 00:00:00"):
                raw = raw[:-9]
            try:
                historical_date = (
                    datetime.strptime(raw, formats[mapping.date_format]).date().isoformat()
                )
            except ValueError:
                errors.append("历史日期不符合所选格式，原值保留，不使用本次登记日期代替")
        gaps = [
            key
            for key in (
                "context",
                "options",
                "trade_offs",
                "rationale",
                "consequence",
                "historical_date",
                "historical_approver",
            )
            if not values.get(key, "").strip()
        ]
        result.append(
            {
                "row": number,
                "locator": f"sheet:{mapping.sheet},row:{number}",
                "original": original,
                "values": values,
                "historical_date": historical_date,
                "errors": errors,
                "gaps": gaps,
            }
        )
    return result


class DecisionIntakePreviews:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.scope = IssueIntakePreviews(engine)

    def list(self, ctx: AuthContext, conversation: UUID, message: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope.scope(c, ctx, conversation)
            self.scope.message(c, ctx, conversation, message)
            sources = []
            for identity in message_attachment_ids(c, ctx.tenant.id, message):
                row = ConversationAttachmentService._row(c, ctx.tenant.id, conversation, identity)
                try:
                    check_source(row)
                except ConversationError:
                    continue
                sheets = sorted(
                    {
                        match[1]
                        for item in row["fragments"]
                        if (match := SHEET.fullmatch(item["locator"]))
                    }
                )
                sources.append({"id": str(identity), "filename": row["filename"], "sheets": sheets})
            t = tables.decision_intake_previews
            items = (
                c.execute(
                    select(t.c.id, t.c.attachment_id, t.c.created_at, t.c.purpose, t.c.mapping)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.message_id == message,
                        t.c.parser_version == PARSER,
                    )
                    .order_by(t.c.created_at.desc(), t.c.id.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return {
                "items": [_plain(row) for row in items],
                "sources": sources,
                "status": "preview_only",
            }

    def prepare(
        self, ctx: AuthContext, conversation: UUID, message: UUID, body: DecisionIntakePrepare
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            conv = self.scope.scope(c, ctx, conversation, write=True)
            self.scope.message(c, ctx, conversation, message)
            if body.attachment_id not in message_attachment_ids(c, ctx.tenant.id, message):
                raise ConversationError("所选附件不属于这条已保存的消息")
            attachment = ConversationAttachmentService._row(
                c, ctx.tenant.id, conversation, body.attachment_id, lock=True
            )
            check_source(attachment)
            identity = source_identity(attachment)
            signature = digest(
                {
                    "message_id": str(message),
                    "input": body.model_dump(mode="json"),
                    "source": identity,
                }
            )
            t = tables.decision_intake_previews
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("此请求已对应其他来源或映射，请读取原草稿后继续")
                return _plain(prior) | {"status": "preview_only", "source_current": True}
            record = (
                c.execute(
                    t.insert()
                    .values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=conv["project_id"],
                        conversation_id=conversation,
                        message_id=message,
                        attachment_id=body.attachment_id,
                        created_by_user_id=ctx.user.id,
                        request_id=body.request_id,
                        request_digest=signature,
                        source_snapshot=identity,
                        parser_version=PARSER,
                        permission_basis=body.permission_basis,
                        purpose=body.purpose,
                        mapping=body.mapping.model_dump(mode="json"),
                        rows=mapped_rows(attachment["fragments"], body.mapping),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return _plain(record) | {"status": "preview_only", "source_current": True}

    def get(self, ctx: AuthContext, conversation: UUID, identity: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope.scope(c, ctx, conversation)
            t = tables.decision_intake_previews
            row = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.id == identity,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ConversationError("此决策草稿不属于当前会话")
            attachment = ConversationAttachmentService._row(
                c, ctx.tenant.id, conversation, row["attachment_id"]
            )
            try:
                check_source(attachment, row["parser_version"])
                current = source_identity(attachment) == row["source_snapshot"]
                from app.domain.intake_ai_imports import cited_sources

                cited_sources(c, ctx, conversation, row)
            except ConversationError:
                current = False
            from app.domain.decision_intake_confirm import preview_receipts

            receipts = preview_receipts(c, ctx.tenant.id, identity)
            return _plain(row) | {
                "status": "confirmed" if receipts else "preview_only",
                "source_current": current,
                "source_digest": digest(row["source_snapshot"]),
                "receipts": receipts,
            }
