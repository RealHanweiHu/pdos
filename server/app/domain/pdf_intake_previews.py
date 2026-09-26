"""Human-selected PDF passages retain their real extracted positions and original text."""

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
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
from app.domain.issue_intake_preview import IssueIntakePreviews, source_identity
from app.domain.product_workspace import _plain, digest

Kind = Literal["issue", "decision"]
FIELDS = {
    "issue": {
        "title",
        "description",
        "external_ref",
        "source_state",
        "root_cause",
        "resolution",
        "target_date",
    },
    "decision": {
        "title",
        "outcome",
        "context",
        "options",
        "trade_offs",
        "rationale",
        "consequence",
        "historical_date",
        "historical_approver",
        "historical_owner",
        "historical_kind",
        "historical_state",
        "external_ref",
        "issue_ref",
    },
}
FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYY/MM/DD": "%Y/%m/%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
}


class PdfSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordinal: int = Field(ge=1)
    start: int = Field(ge=0, lt=20000)
    end: int = Field(gt=0, le=20000)

    @model_validator(mode="after")
    def nonempty(self) -> "PdfSpan":
        if self.end <= self.start:
            raise ValueError("请选择非空的原文范围")
        return self


class PdfEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor: PdfSpan
    fields: dict[str, PdfSpan] = Field(max_length=14)


class PdfIntakePrepare(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    attachment_id: UUID
    expected_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Kind
    permission_basis: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=2000)
    date_format: Literal["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY", "RFC 5322"] = (
        "YYYY-MM-DD"
    )
    entries: list[PdfEntry] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def fields_and_anchors(self) -> "PdfIntakePrepare":
        anchors = set()
        for entry in self.entries:
            if set(entry.fields) - FIELDS[self.kind]:
                raise ValueError("所选字段不属于此类资料")
            key = (entry.anchor.ordinal, entry.anchor.start, entry.anchor.end)
            if key in anchors:
                raise ValueError("同一草稿不能重复使用相同的主来源位置")
            anchors.add(key)
        return self


def check_pdf(row: Any, source_kind: str = "pdf") -> None:
    extension = ".pdf" if source_kind == "pdf" else ".eml"
    if (
        row["revoked_at"] is not None
        or row["status"] != "extracted"
        or row["classification"] != "internal"
        or not row["filename"].lower().endswith(extension)
    ):
        raise ConversationError(
            "请选择本消息中对应格式、已抽取且未撤回的内部资料；解析缺项仍须人工核对"
        )


def mapped_rows(
    fragments: list[dict[str, Any]], body: PdfIntakePrepare, source_kind: str = "pdf"
) -> list[dict[str, Any]]:
    locator_pattern = (
        r"page:[1-9][0-9]*(?:#part:[1-9][0-9]*)?"
        if source_kind == "pdf"
        else (
            r"email:(?:header:[a-z-]+:[1-9][0-9]*|part:[1-9][0-9]*"
            r"(?:\.[1-9][0-9]*)*)(?:#part:[1-9][0-9]*)?"
        )
    )
    by_ordinal = {item["ordinal"]: item for item in fragments}
    total = 0

    def quote(span: PdfSpan) -> dict[str, Any]:
        nonlocal total
        fragment = by_ordinal.get(span.ordinal)
        if (
            fragment is None
            or not re.fullmatch(locator_pattern, fragment["locator"])
            or span.end > len(fragment["text"])
        ):
            raise ConversationError("选段已超出实际资料原文，请重新读取附件并选择")
        value = fragment["text"][span.start : span.end]
        total += len(value)
        if total > 200000:
            raise ConversationError("本批引用超过20万字，请拆分草稿；原文不会截断")
        return span.model_dump() | {
            "locator": fragment["locator"],
            "cell": f"{fragment['locator']} · 字符{span.start + 1}–{span.end}",
            "value": value,
        }

    result = []
    for number, entry in enumerate(body.entries, 1):
        anchor = quote(entry.anchor)
        original = {key: quote(span) for key, span in entry.fields.items()}
        values = {key: item["value"] for key, item in original.items()}
        errors = []
        for key in ("title", "outcome") if body.kind == "decision" else ("title",):
            if not values.get(key, "").strip():
                errors.append(f"缺少{'标题' if key == 'title' else '结论'}原文，请选择对应片段")
        if len(values.get("title", "")) > 512:
            errors.append("标题原文超过512字，请缩小所选范围")
        date_key = "target_date" if body.kind == "issue" else "historical_date"
        parsed_date = None
        if values.get(date_key):
            try:
                raw_date = values[date_key].strip()
                parsed_date = (
                    (
                        parsedate_to_datetime(raw_date)
                        if body.date_format == "RFC 5322"
                        else datetime.strptime(raw_date, FORMATS[body.date_format])
                    )
                    .date()
                    .isoformat()
                )
            except (ValueError, TypeError, OverflowError):
                errors.append("日期原文不符合所选格式；保留原文，不补造日期")
        row = {
            "row": number,
            "source_kind": source_kind,
            "locator": (
                f"{source_kind}:{anchor['locator']},chars:{entry.anchor.start}-{entry.anchor.end}"
            ),
            "anchor": anchor,
            "original": original,
            "errors": errors,
        }
        if body.kind == "issue":
            row |= {
                "proposed": {
                    "title": values.get("title", ""),
                    **{
                        key: values.get(key) or None
                        for key in ("description", "root_cause", "resolution")
                    },
                    "target_date": parsed_date,
                    "status": "open",
                },
                "historical_state": values.get("source_state") or None,
                "external_ref": values.get("external_ref") or None,
            }
        else:
            row |= {
                "values": values,
                "historical_date": parsed_date,
                "gaps": [
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
                ],
            }
        result.append(row)
    return result


class PdfIntakePreviews:
    def __init__(self, engine: Engine, source_kind: Literal["pdf", "email"] = "pdf"):
        self.source_kind = source_kind
        self.extension = ".pdf" if source_kind == "pdf" else ".eml"
        self.engine = engine
        self.scope = IssueIntakePreviews(engine)

    def list(
        self, ctx: AuthContext, conversation: UUID, message: UUID, kind: Kind
    ) -> dict[str, Any]:
        with self.engine.connect() as c:
            self.scope.scope(c, ctx, conversation)
            self.scope.message(c, ctx, conversation, message)
            sources = []
            for identity in message_attachment_ids(c, ctx.tenant.id, message):
                row = ConversationAttachmentService._row(c, ctx.tenant.id, conversation, identity)
                if (
                    row["revoked_at"] is None
                    and row["classification"] == "internal"
                    and row["filename"].lower().endswith(self.extension)
                ):
                    source = source_identity(row)
                    sources.append(
                        {
                            "id": str(identity),
                            "filename": row["filename"],
                            "status": row["status"],
                            "source_identity": source,
                            "digest": digest(source),
                        }
                    )
            t = tables.issue_intake_previews if kind == "issue" else tables.decision_intake_previews
            items = (
                c.execute(
                    select(t.c.id, t.c.created_at, t.c.purpose, t.c.attachment_id)
                    .where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.message_id == message,
                        t.c.parser_version == f"{kind}-{self.source_kind}-extracted-v1",
                    )
                    .order_by(t.c.created_at.desc(), t.c.id.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            return {"sources": sources, "items": [_plain(item) for item in items]}

    def prepare(
        self, ctx: AuthContext, conversation: UUID, message: UUID, body: PdfIntakePrepare
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            conv = self.scope.scope(c, ctx, conversation, write=True)
            self.scope.message(c, ctx, conversation, message)
            if body.attachment_id not in message_attachment_ids(c, ctx.tenant.id, message):
                raise ConversationError("所选原件不属于这条消息")
            attachment = ConversationAttachmentService._row(
                c, ctx.tenant.id, conversation, body.attachment_id, lock=True
            )
            check_pdf(attachment, self.source_kind)
            identity = source_identity(attachment)
            if digest(identity) != body.expected_source_digest:
                raise ConversationError("原文版本已变化，请清空旧选段后重新读取选择")
            signature = digest(
                {
                    "message_id": str(message),
                    "input": body.model_dump(mode="json"),
                    "source": identity,
                }
            )
            t = (
                tables.issue_intake_previews
                if body.kind == "issue"
                else tables.decision_intake_previews
            )
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
                    raise ConversationError("此请求已保存另一份选段，请读取原草稿")
                return _plain(prior) | {
                    "source_current": True,
                    "status": "preview_only",
                    "source_digest": digest(identity),
                }
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
                        parser_version=f"{body.kind}-{self.source_kind}-extracted-v1",
                        permission_basis=body.permission_basis,
                        purpose=body.purpose,
                        mapping={
                            "source_kind": self.source_kind,
                            "date_format": body.date_format,
                            "entries": [item.model_dump(mode="json") for item in body.entries],
                        },
                        rows=mapped_rows(attachment["fragments"], body, self.source_kind),
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            return _plain(record) | {
                "source_current": True,
                "status": "preview_only",
                "source_digest": digest(identity),
            }
