"""Reviewed multi-file citations enter the existing Issue and historical Decision workflows."""

import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field
from sqlalchemy import Connection, Engine, select

from app.ai.intake_ai_context import CAPABILITY
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.contracts.intake_proposal import Input
from app.db.schema import tables
from app.domain.conversation_attachments import ConversationAttachmentService
from app.domain.conversations import ConversationError
from app.domain.documents import MAX_DOCUMENT_BYTES
from app.domain.intake_ai_findings import IntakeAiFindings
from app.domain.intake_ai_observations import IntakeAiObservations
from app.domain.issue_intake_preview import source_identity
from app.domain.pdf_intake_previews import FORMATS
from app.domain.product_workspace import digest
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class CitedImportPrepare(Input):
    number: int = Field(ge=1, le=30)
    date_format: Literal["YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY", "RFC 5322"]


def is_cited(preview: Any) -> bool:
    return preview["parser_version"] in {"issue-ai-cited-v1", "decision-ai-cited-v1"}


def cited_sources(
    c: Connection, ctx: AuthContext, conversation: UUID, preview: Any
) -> dict[str, Any]:
    if not is_cited(preview):
        return {}
    require_live_key(CAPABILITY)
    service = IntakeAiFindings(c.engine)
    finding, run, _ = service.rows(c, ctx, conversation, UUID(preview["mapping"]["finding_id"]))
    if (
        finding["status"] not in {"accepted", "applied"}
        or digest(finding["accepted_payload"]) != preview["mapping"]["accepted_digest"]
    ):
        raise ConversationError("原人工核对稿已不再适用，请回到原整理建议")
    service.current(c, ctx, run)
    result = {}
    for key, expected in preview["mapping"]["source_identities"].items():
        attachment = ConversationAttachmentService._row(c, ctx.tenant.id, conversation, UUID(key))
        if source_identity(attachment) != expected or attachment["revoked_at"] is not None:
            raise ConversationError("跨附件原文已变化或停止引用，请重新核对")
        result[key] = attachment
    return result


def read_contents(sources: dict[str, Any], store: DocumentObjectStore | None) -> dict[str, bytes]:
    if not sources:
        return {}
    if not isinstance(store, ReadableDocumentObjectStore):
        raise ConversationError("原件读取服务暂不可用")
    contents = {}
    for key, source in sources.items():
        content = store.get(object_key=source["object_key"], max_bytes=MAX_DOCUMENT_BYTES)
        if (
            len(content) != source["size_bytes"]
            or hashlib.sha256(content).hexdigest() != source["sha256"]
        ):
            raise ConversationError("跨附件原件字节与核对版本不一致，未登记本批内容")
        contents[key] = content
    return contents


def share_documents(
    c: Connection,
    ctx: AuthContext,
    project: UUID,
    sources: dict[str, Any],
    contents: dict[str, bytes],
    store: DocumentObjectStore | None,
) -> dict[str, Any]:
    service = IntakeAiObservations(c.engine, store)
    result = {}
    for key, attachment in sources.items():
        document, _ = service.document(c, ctx, project, attachment, contents[key])
        result[key] = {
            "id": str(document["id"]),
            "filename": document["filename"],
            "sha256": document["sha256"],
            "source_identity": source_identity(attachment),
            "href": f"/projects?project={project}&tab=documents&document_id={document['id']}",
        }
    return result


def build_row(
    proposal: dict[str, Any], sources: dict[str, Any], date_format: str
) -> dict[str, Any]:
    kind = proposal["kind"]

    def quote(value: dict[str, Any]) -> dict[str, Any]:
        filename = sources[value["attachment_id"]]["filename"]
        return value | {
            "cell": f"{filename} · {value['locator']} · 字符{value['start'] + 1}–{value['end']}"
        }

    anchor = quote(proposal["anchor"])
    original = {key: quote(value) for key, value in proposal["original"].items()}
    values = {key: value["value"] for key, value in original.items()}
    errors = []
    for name in ("title", "outcome") if kind == "decision" else ("title",):
        if not values.get(name, "").strip():
            errors.append(
                f"缺少{'标题' if name == 'title' else '结论'}原文；请重新整理并核对后另存建议"
            )
    if len(values.get("title", "")) > 512:
        errors.append("标题原文超过512字，请重新核对选段")
    date_key = "target_date" if kind == "issue" else "historical_date"
    parsed_date = None
    if values.get(date_key):
        try:
            raw = values[date_key].strip()
            parsed_date = (
                (
                    parsedate_to_datetime(raw)
                    if date_format == "RFC 5322"
                    else datetime.strptime(raw, FORMATS[date_format])
                )
                .date()
                .isoformat()
            )
        except (ValueError, TypeError, OverflowError):
            errors.append("原文日期不符合所选格式，请选择实际格式重建草稿；原字符串保留")
    filename = sources[anchor["attachment_id"]]["filename"].lower()
    source_kind = (
        "pdf"
        if filename.endswith(".pdf")
        else "email"
        if filename.endswith(".eml")
        else "xlsx-cited"
    )
    row = {
        "row": proposal["number"],
        "source_kind": "ai_cited",
        "anchor": anchor,
        "locator": f"{source_kind}:{anchor['locator']},chars:{anchor['start']}-{anchor['end']}",
        "original": original,
        "errors": errors,
    }
    if kind == "issue":
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
    return row


def import_previews(c: Connection, tenant: UUID, finding: UUID) -> list[dict[str, Any]]:
    result = []
    for kind, t in (
        ("issue", tables.issue_intake_previews),
        ("decision", tables.decision_intake_previews),
    ):
        for row in c.execute(
            select(t)
            .where(
                t.c.tenant_id == tenant,
                t.c.parser_version == f"{kind}-ai-cited-v1",
                t.c.mapping["finding_id"].astext == str(finding),
            )
            .order_by(t.c.created_at.desc(), t.c.id)
        ).mappings():
            result.append(
                {
                    "id": str(row["id"]),
                    "kind": kind,
                    "number": row["mapping"]["proposal_number"],
                    "date_format": row["mapping"]["date_format"],
                    "created_at": row["created_at"].isoformat(),
                }
            )
    return result


class IntakeAiImports:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.findings = IntakeAiFindings(engine)

    def prepare(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: CitedImportPrepare
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.begin() as c:
            finding, run, brief = self.findings.rows(c, ctx, conversation, identity, write=True)
            if finding["status"] not in {"accepted", "applied"}:
                raise ConversationError("请先接受人工核对稿")
            self.findings.current(c, ctx, run)
            proposal = next(
                (p for p in finding["accepted_payload"]["proposals"] if p["number"] == body.number),
                None,
            )
            if proposal is None or proposal["kind"] not in {"issue", "decision"}:
                raise ConversationError("请选择已接受的问题或历史决策建议")
            kind = proposal["kind"]
            t = tables.issue_intake_previews if kind == "issue" else tables.decision_intake_previews
            request = uuid5(identity, f"cited-import:{body.number}:{body.date_format}")
            old = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.conversation_id == conversation,
                        t.c.request_id == request,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if old is not None:
                return {"id": str(old["id"]), "kind": kind}
            if finding["status"] == "applied":
                raise ConversationError("此建议已全部应用，请读取原业务回执")
            keys = {
                q["attachment_id"] for q in [proposal["anchor"], *proposal["original"].values()]
            }
            sources = {
                key: brief["source_snapshot"]["sources"][key]["identity"] for key in sorted(keys)
            }
            anchor = proposal["anchor"]["attachment_id"]
            mapping = {
                "finding_id": str(identity),
                "accepted_digest": digest(finding["accepted_payload"]),
                "proposal_number": body.number,
                "proposal": proposal,
                "source_kind": "ai_cited",
                "source_identities": sources,
                "date_format": body.date_format,
            }
            row = build_row(proposal, sources, body.date_format)
            saved = c.execute(
                t.insert()
                .values(
                    id=request,
                    tenant_id=ctx.tenant.id,
                    project_id=finding["project_id"],
                    conversation_id=conversation,
                    message_id=brief["message_id"],
                    attachment_id=UUID(anchor),
                    created_by_user_id=ctx.user.id,
                    request_id=request,
                    request_digest=digest({"mapping": mapping, "row": row}),
                    source_snapshot=sources[anchor],
                    parser_version=f"{kind}-ai-cited-v1",
                    permission_basis=brief["source_snapshot"]["permission_basis"],
                    purpose=brief["source_snapshot"]["purpose"],
                    mapping=mapping,
                    rows=[row],
                )
                .returning(t.c.id)
            ).scalar_one()
            return {"id": str(saved), "kind": kind}


def completed_imports(c: Connection, tenant: UUID, finding: UUID) -> dict[int, dict[str, str]]:
    result = {}
    for kind, p, b in (
        ("issue", tables.issue_intake_previews, tables.issue_intake_batches),
        ("decision", tables.decision_intake_previews, tables.decision_intake_batches),
    ):
        query = (
            select(p.c.mapping, b.c.results)
            .join(b, (b.c.tenant_id == p.c.tenant_id) & (b.c.preview_id == p.c.id))
            .where(
                p.c.tenant_id == tenant,
                p.c.parser_version == f"{kind}-ai-cited-v1",
                p.c.mapping["finding_id"].astext == str(finding),
            )
            .order_by(b.c.created_at, b.c.id)
        )
        for batch in c.execute(query).mappings():
            number = batch["mapping"]["proposal_number"]
            for row in batch["results"]:
                if row["row"] == number and row["status"] in {"created", "linked", "reused"}:
                    result[number] = {
                        "kind": kind,
                        "id": row[f"{kind}_id"],
                        "href": row[f"{kind}_href"],
                    }
    return result


def finish_if_all(
    c: Connection, ctx: AuthContext, identity: UUID, entity_type: str, entity_id: UUID
) -> None:
    from uuid import uuid4

    from sqlalchemy import func

    from app.ai.quality import FindingQualityService
    from app.domain.intake_ai_observations import receipts
    from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

    t = tables.findings
    finding = (
        c.execute(
            select(t).where(t.c.tenant_id == ctx.tenant.id, t.c.id == identity).with_for_update()
        )
        .mappings()
        .one()
    )
    if finding["status"] == "applied":
        return
    completed = {row["proposal_number"] for row in receipts(c, ctx, identity)} | completed_imports(
        c, ctx.tenant.id, identity
    ).keys()
    expected = {row["number"] for row in finding["accepted_payload"]["proposals"]}
    if completed != expected:
        return
    now = c.execute(select(func.clock_timestamp())).scalar_one()
    c.execute(
        t.update()
        .where(t.c.tenant_id == ctx.tenant.id, t.c.id == identity)
        .values(
            status="applied",
            applied_by_user_id=ctx.user.id,
            applied_at=now,
            updated_at=now,
            applied_entity_type=entity_type,
            applied_entity_id=entity_id,
        )
    )
    c.execute(
        tables.finding_actions.insert().values(
            id=uuid4(),
            tenant_id=ctx.tenant.id,
            project_id=finding["project_id"],
            finding_id=identity,
            action="applied",
            actor_user_id=ctx.user.id,
            from_status="accepted",
            to_status="applied",
            detail={
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "numbers": sorted(completed),
            },
            created_at=now,
        )
    )
    EventAuditWriter(
        c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=finding["project_id"]
    ).record(
        EventDraft(
            event_id=f"intake-finding:{identity}:applied",
            event_type="INTAKE_AI_FINDING_RECORDED",
            source="intake_ai_service",
            entity_id=identity,
            payload={"finding_id": str(identity), "action": "applied"},
        ),
        AuditDraft(
            action="intake_ai_finding.applied",
            after_snapshot={
                "finding_id": str(identity),
                "entity_type": entity_type,
                "entity_id": str(entity_id),
            },
        ),
    )
    FindingQualityService(c.engine).evaluate_connection(
        c, tenant_id=ctx.tenant.id, evaluated_at=now
    )


def finish_import(c: Connection, ctx: AuthContext, preview: Any, receipt: Any) -> None:
    if not is_cited(preview):
        return
    kind = "issue" if preview["parser_version"].startswith("issue-") else "decision"
    successful = [
        row for row in receipt["results"] if row["status"] in {"created", "linked", "reused"}
    ]
    if successful:
        finish_if_all(
            c, ctx, UUID(preview["mapping"]["finding_id"]), kind, UUID(successful[-1][f"{kind}_id"])
        )
