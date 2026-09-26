"""Deterministic Issue-list mappings from already extracted private XLSX originals."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversation_attachments import (
    ConversationAttachmentService,
    message_attachment_ids,
)
from app.domain.conversations import ConversationError, ConversationService
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest

PARSER = "issue-list-extracted-v1"
Column = Annotated[str, Field(pattern=r"^[A-Z]{1,3}$")]
SHEET = re.compile(r"^sheet:(.*),rows:(\d+)-(\d+)(?:#part:(\d+))?$")
CELL = re.compile(r"^([A-Z]+)([1-9][0-9]*)=(.*)$")


class IssueListMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sheet: str = Field(min_length=1, max_length=200)
    first_row: int = Field(ge=1, le=1048576)
    last_row: int = Field(ge=1, le=1048576)
    title: Column
    description: Column | None = None
    external_ref: Column | None = None
    source_state: Column | None = None
    root_cause: Column | None = None
    resolution: Column | None = None
    target_date: Column | None = None
    date_format: Literal["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY"] = "YYYY-MM-DD"

    @model_validator(mode="after")
    def bounded(self) -> "IssueListMapping":
        if self.last_row < self.first_row or self.last_row - self.first_row >= 200:
            raise ValueError("每批请选择连续的1至200行，可分批继续")
        return self


class IssueIntakePrepare(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    attachment_id: UUID
    permission_basis: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    mapping: IssueListMapping


def canonical_row(row: dict[str, Any]) -> dict[str, Any]:
    """PDF draft order is not part of the physical source identity."""
    return (
        {key: value for key, value in row.items() if key != "row"}
        if row.get("source_kind") in {"pdf", "email", "ai_cited"}
        else row
    )


def source_identity(row: Any) -> dict[str, Any]:
    return {
        "attachment_id": str(row["id"]),
        "filename": row["filename"],
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "parser_version": row["parser_version"],
        "fragments_digest": digest(row["fragments"]),
        **(
            {"extraction_metadata": row["extraction_metadata"]}
            if row.get("extraction_metadata")
            else {}
        ),
    }


def check_source(row: Any, parser_version: str = PARSER) -> None:
    if parser_version == "issue-ai-cited-v1":
        from app.domain.intake_ai_sources import check_source as check_cited_source

        check_cited_source(row)
        return

    extension = {
        PARSER: ".xlsx",
        "issue-pdf-extracted-v1": ".pdf",
        "issue-email-extracted-v1": ".eml",
    }.get(parser_version)
    if (
        row["revoked_at"] is not None
        or row["status"] != "extracted"
        or row["classification"] != "internal"
        or extension is None
        or not row["filename"].lower().endswith(extension)
    ):
        raise ConversationError(
            "请使用本条消息中已抽取、未撤回的内部PDF/XLSX/授权EML问题清单；其他材料仍可阅读"
        )


def workbook_rows(fragments: list[dict[str, Any]], sheet: str) -> dict[int, dict[str, str]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for fragment in fragments:
        match = SHEET.fullmatch(fragment["locator"])
        if match and match[1] == sheet:
            groups.setdefault(f"sheet:{match[1]},rows:{match[2]}-{match[3]}", []).append(fragment)
    if not groups:
        raise ConversationError("未找到所选工作表，请按原件工作表名称填写")
    result: dict[int, dict[str, str]] = {}
    for parts in groups.values():
        text = "".join(part["text"] for part in sorted(parts, key=lambda item: item["ordinal"]))
        for line in text.splitlines():
            cells: dict[str, str] = {}
            row_numbers: set[int] = set()
            for token in line.split("\t"):
                if not token:
                    continue
                match = CELL.fullmatch(token)
                if not match:
                    raise ConversationError("原抽取结果缺少完整单元格坐标，请重新核对附件解析结果")
                cells[match[1]] = match[3]
                row_numbers.add(int(match[2]))
            if len(row_numbers) > 1:
                raise ConversationError("原抽取单元格行号不一致，不能生成可确认草稿")
            if row_numbers:
                row = next(iter(row_numbers))
                if row in result:
                    raise ConversationError("原抽取结果含重复行，不能静默覆盖")
                result[row] = cells
    return result


def mapped_rows(fragments: list[dict[str, Any]], mapping: IssueListMapping) -> list[dict[str, Any]]:
    rows = workbook_rows(fragments, mapping.sheet)
    result = []
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
    for number in range(mapping.first_row, mapping.last_row + 1):
        cells = rows.get(number, {})
        original = {
            key: {"cell": f"{column}{number}", "value": cells.get(column, "")}
            for key, column in columns.items()
        }
        values = {key: item["value"] for key, item in original.items()}
        errors = []
        title = values.get("title", "")
        if not title or len(title) > 512:
            errors.append("问题标题为空或超过512字；请核对行范围和标题列")
        for key, value in values.items():
            if value.startswith("="):
                errors.append(f"{original[key]['cell']}为公式原文，不能当作已经求值的事实")
            if key in {"description", "root_cause", "resolution"} and len(value) > 20000:
                errors.append(f"{original[key]['cell']}超出该字段可保存长度")
        target = None
        if values.get("target_date"):
            raw = values["target_date"]
            if mapping.date_format == "YYYY-MM-DD" and raw.endswith(" 00:00:00"):
                raw = raw[:-9]
            try:
                target = datetime.strptime(raw, formats[mapping.date_format]).date().isoformat()
            except ValueError:
                errors.append(
                    f"{original['target_date']['cell']}不符合所选日期格式；原值保留待核对"
                )
        result.append(
            {
                "row": number,
                "locator": f"sheet:{mapping.sheet},row:{number}",
                "original": original,
                "proposed": {
                    "title": title,
                    "description": values.get("description") or None,
                    "root_cause": values.get("root_cause") or None,
                    "resolution": values.get("resolution") or None,
                    "target_date": target,
                    "status": "open",
                },
                "historical_state": values.get("source_state") or None,
                "external_ref": values.get("external_ref") or None,
                "errors": errors,
            }
        )
    return result


class IssueIntakePreviews:
    def __init__(self, engine: Engine):
        self.engine = engine

    def scope(
        self, c: Connection, ctx: AuthContext, conversation: UUID, *, write: bool = False
    ) -> Any:
        row = ConversationService(self.engine)._conversation(c, ctx, conversation, lock=write)
        if write and row["archived_at"] is not None:
            raise ConversationError("请先恢复会话后再保存导入草稿")
        KnowledgeCorrectionService._authorize(
            c,
            ctx.tenant.id,
            ctx.user.id,
            row["project_id"],
            Action.WORK_ITEM_EDIT if write else Action.WORK_ITEM_VIEW,
        )
        return row

    @staticmethod
    def message(c: Connection, ctx: AuthContext, conversation: UUID, message: UUID) -> None:
        t = tables.conversation_messages
        if (
            c.execute(
                select(t.c.id).where(
                    t.c.tenant_id == ctx.tenant.id,
                    t.c.conversation_id == conversation,
                    t.c.id == message,
                )
            ).scalar_one_or_none()
            is None
        ):
            raise ConversationError("此消息不属于当前会话")

    def list(self, ctx: AuthContext, conversation: UUID, message: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope(c, ctx, conversation)
            self.message(c, ctx, conversation, message)
            ids = message_attachment_ids(c, ctx.tenant.id, message)
            sources = []
            for identity in ids:
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
            t = tables.issue_intake_previews
            items = (
                c.execute(
                    select(t.c.id, t.c.attachment_id, t.c.created_at, t.c.purpose, t.c.mapping)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.message_id == message,
                        t.c.parser_version == PARSER,
                    )
                    .order_by(t.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return {
                "items": [_plain(item) for item in items],
                "sources": sources,
                "status": "preview_only",
            }

    def prepare(
        self, ctx: AuthContext, conversation: UUID, message: UUID, body: IssueIntakePrepare
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            conv = self.scope(c, ctx, conversation, write=True)
            self.message(c, ctx, conversation, message)
            if body.attachment_id not in message_attachment_ids(c, ctx.tenant.id, message):
                raise ConversationError("请从这条消息已保存的附件开始准备")
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
            t = tables.issue_intake_previews
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
                    raise ConversationError("此请求号已对应另一份映射或来源，请读取原草稿后继续")
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
            self.scope(c, ctx, conversation)
            t = tables.issue_intake_previews
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
                raise ConversationError("此导入草稿不属于当前会话")
            attachment = ConversationAttachmentService._row(
                c, ctx.tenant.id, conversation, row["attachment_id"]
            )
            from app.domain.issue_intake_confirm import preview_receipts

            try:
                check_source(attachment, row["parser_version"])
                current = source_identity(attachment) == row["source_snapshot"]
                from app.domain.intake_ai_imports import cited_sources

                cited_sources(c, ctx, conversation, row)
            except ConversationError:
                current = False
            receipts = preview_receipts(c, ctx.tenant.id, identity)
            return _plain(row) | {
                "status": "has_receipts" if receipts else "preview_only",
                "source_current": current,
                "source_digest": digest(row["source_snapshot"]),
                "confirmation_receipts": receipts,
            }
