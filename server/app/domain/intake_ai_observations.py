"""Independently adopt reviewed project observations into the real initialization workflow."""

import hashlib
from typing import Any, Literal, Self
from uuid import UUID, uuid4, uuid5

from pydantic import Field, model_validator
from sqlalchemy import Connection, Engine, select

from app.ai.intake_ai_context import CAPABILITY
from app.ai.rollout_guard import require_live_key
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.intake_proposal import Input, Text
from app.db.schema import tables
from app.domain.conversation_attachments import ConversationAttachmentService
from app.domain.conversations import ConversationError
from app.domain.documents import MAX_DOCUMENT_BYTES, DocumentService
from app.domain.intake_ai_findings import IntakeAiFindings
from app.domain.issue_intake_compensation_results import document_snapshot
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.product_workspace import _plain, digest
from app.domain.project_intake import IntakeProposal, ProjectIntakeService, project_basis
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.storage.documents import DocumentObjectStore, ReadableDocumentObjectStore


class ObservationSelection(Input):
    numbers: tuple[int, ...] = Field(min_length=1, max_length=30)
    review_note: Text

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.numbers)) != len(self.numbers) or not self.review_note.strip():
            raise ValueError("请选择不同建议并填写本次采用依据")
        return self


class ObservationAdoption(ObservationSelection):
    request_id: UUID
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    publish_to_project: Literal[True]
    reviewed: Literal[True]


def receipts(c: Connection, ctx: AuthContext, finding: UUID) -> list[dict[str, Any]]:
    t = tables.intake_ai_observation_applications
    return [
        _plain(row)
        | {
            "href": (
                f"/projects?project={row['project_id']}&tab=overview"
                f"&intake_proposal={row['proposal_id']}"
            )
        }
        for row in c.execute(
            select(t)
            .where(t.c.tenant_id == ctx.tenant.id, t.c.finding_id == finding)
            .order_by(t.c.created_at, t.c.proposal_number)
        ).mappings()
    ]


class IntakeAiObservations:
    def __init__(self, engine: Engine, object_store: DocumentObjectStore | None = None):
        self.engine, self.object_store = engine, object_store
        self.findings = IntakeAiFindings(engine)

    def state(
        self,
        c: Connection,
        ctx: AuthContext,
        conversation: UUID,
        identity: UUID,
        body: ObservationSelection,
        *,
        write: bool = False,
    ) -> dict[str, Any]:
        finding, run, brief = self.findings.rows(c, ctx, conversation, identity, write=write)
        if finding["status"] != "accepted":
            raise ConversationError("请先完成人工核对并接受此建议")
        self.findings.current(c, ctx, run)
        project = finding["project_id"]
        KnowledgeCorrectionService._authorize(
            c, ctx.tenant.id, ctx.user.id, project, Action.DOCUMENT_ANALYZE
        )
        all_proposals = {p["number"]: p for p in finding["accepted_payload"]["proposals"]}
        if any(
            number not in all_proposals or all_proposals[number]["kind"] != "project_observation"
            for number in body.numbers
        ):
            raise ConversationError("此入口只采用已接受的项目现状建议；问题和决策须另行办理")
        previous = receipts(c, ctx, identity)
        if set(body.numbers) & {row["proposal_number"] for row in previous}:
            raise ConversationError("部分建议已采用，请查看原回执并只选择尚未办理项")
        selected = [all_proposals[n] for n in sorted(body.numbers)]
        basis = project_basis(c, ctx, project)
        t = tables.project_intake_proposals
        latest = (
            c.execute(
                select(t)
                .where(t.c.tenant_id == ctx.tenant.id, t.c.project_id == project)
                .order_by(t.c.revision.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        originals = []
        for item in selected:
            # Keep the main passage as well as every chosen field, including cross-file sources.
            originals.append(
                {
                    "number": item["number"],
                    "name": "anchor",
                    "kind": "other",
                    "quote": item["anchor"],
                }
            )
            for name, quote in item["original"].items():
                originals.append(
                    {
                        "number": item["number"],
                        "name": name,
                        "kind": "date" if name == "historical_date" else name,
                        "quote": quote,
                    }
                )
        retained = len(latest["draft"]["observations"]) if latest else 0
        if retained + len(originals) > 30:
            raise ConversationError(
                "当前现状及新增原文合计超过30项，请缩小批次或先在现状页面整理已有选段"
            )
        ids = sorted({item["quote"]["attachment_id"] for item in originals})
        source = brief["source_snapshot"]
        value = {
            "finding_id": str(identity),
            "accepted_digest": digest(finding["accepted_payload"]),
            "project_id": str(project),
            "project_digest": basis["digest"],
            "latest_revision": latest["revision"] if latest else 0,
            "latest_id": str(latest["id"]) if latest else None,
            "selected": selected,
            "originals": originals,
            "review_note": body.review_note,
            "files": [{"attachment_id": key, **source["sources"][key]["identity"]} for key in ids],
            "retained_observations": retained,
            "retained_work": len(latest["draft"]["work"]) if latest else 0,
            "permission_basis": source["permission_basis"],
            "purpose": source["purpose"],
        }
        return value | {"preview_digest": digest(value)}

    def preview(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: ObservationSelection
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        with self.engine.connect() as c:
            return self.state(c, ctx, conversation, identity, body)

    @staticmethod
    def prior(
        c: Connection, ctx: AuthContext, identity: UUID, body: ObservationAdoption, signature: str
    ) -> dict[str, Any] | None:
        previous = [
            row for row in receipts(c, ctx, identity) if row["request_id"] == str(body.request_id)
        ]
        if not previous:
            return None
        if any(row["request_digest"] != signature for row in previous):
            raise ConversationError("此采用请求已有不同内容，请读取原回执")
        return {"items": previous, "status": "adopted"}

    def adopt(
        self, ctx: AuthContext, conversation: UUID, identity: UUID, body: ObservationAdoption
    ) -> dict[str, Any]:
        require_live_key(CAPABILITY)
        signature = digest(body.model_dump(mode="json", exclude={"request_id"}))
        with self.engine.connect() as c:
            self.findings.rows(c, ctx, conversation, identity)
            prior = self.prior(c, ctx, identity, body, signature)
            if prior:
                return prior
            state = self.state(c, ctx, conversation, identity, body)
            if state["preview_digest"] != body.preview_digest:
                raise ConversationError("建议、项目现状或预览已变化，请重新查看采用差异")
            attachments = {
                item["attachment_id"]: ConversationAttachmentService._row(
                    c, ctx.tenant.id, conversation, UUID(item["attachment_id"])
                )
                for item in state["files"]
            }
        if not isinstance(self.object_store, ReadableDocumentObjectStore):
            raise ConversationError("原件读取服务暂不可用，请保留核对稿稍后继续")
        contents = {}
        for key, source in attachments.items():
            content = self.object_store.get(
                object_key=source["object_key"], max_bytes=MAX_DOCUMENT_BYTES
            )
            if (
                len(content) != source["size_bytes"]
                or hashlib.sha256(content).hexdigest() != source["sha256"]
            ):
                raise ConversationError("原件与已核对摘要不一致，未采用任何建议")
            contents[key] = content
        with self.engine.begin() as c:
            self.findings.rows(c, ctx, conversation, identity, write=True)
            prior = self.prior(c, ctx, identity, body, signature)
            if prior:
                return prior
            project = UUID(state["project_id"])
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            current = self.state(c, ctx, conversation, identity, body, write=True)
            if current["preview_digest"] != body.preview_digest:
                raise ConversationError("读取原件期间来源或项目现状变化，请重新预览")
            documents = {}
            for key, attachment in attachments.items():
                documents[key] = self.document(c, ctx, project, attachment, contents[key])
            t = tables.project_intake_proposals
            latest = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.revision == current["latest_revision"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            draft = (
                {k: v for k, v in latest["draft"].items() if k in IntakeProposal.model_fields}
                if latest
                else {}
            )
            observations = list(draft.get("observations", []))
            by_number: dict[int, list[str]] = {n: [] for n in body.numbers}
            for item in current["originals"]:
                quote = item["quote"]
                document, fragments = documents[quote["attachment_id"]]
                fragment = fragments[quote["ordinal"]]
                if fragment["text"][quote["start"] : quote["end"]] != quote["value"]:
                    raise ConversationError("项目原文与已核对选段不一致，未采用任何建议")
                key = str(uuid5(identity, f"observation:{item['number']}:{item['name']}"))
                by_number[item["number"]].append(key)
                observations.append(
                    {
                        "key": key,
                        "kind": item["kind"],
                        "document_id": str(document["id"]),
                        "expected_document_digest": digest(document_snapshot(document)),
                        "ordinal": quote["ordinal"],
                        "expected_fragment_digest": digest(fragment),
                        "start": quote["start"],
                        "end": quote["end"],
                    }
                )
            draft |= {
                "request_id": uuid5(identity, str(body.request_id)),
                "expected_revision": current["latest_revision"],
                "expected_project_digest": current["project_digest"],
                "permission_basis": current["permission_basis"],
                "purpose": current["purpose"],
                "review_note": body.review_note,
                "observations": observations,
            }
            proposal = ProjectIntakeService(self.engine).save(
                ctx, project, IntakeProposal.model_validate(draft), connection=c
            )
            receipt_table = tables.intake_ai_observation_applications
            for selected in current["selected"]:
                c.execute(
                    receipt_table.insert().values(
                        id=uuid4(),
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        finding_id=identity,
                        proposal_number=selected["number"],
                        proposal_id=UUID(proposal["id"]),
                        created_by_user_id=ctx.user.id,
                        request_id=body.request_id,
                        request_digest=signature,
                        source_snapshot={
                            "accepted_digest": current["accepted_digest"],
                            "proposal": selected,
                            "files": current["files"],
                            "preview_digest": body.preview_digest,
                        },
                        observation_keys=by_number[selected["number"]],
                        review_note=body.review_note,
                    )
                )
            EventAuditWriter(
                c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"intake-finding:{identity}:observations:{body.request_id}",
                    event_type="INTAKE_AI_FINDING_RECORDED",
                    source="intake_ai_service",
                    entity_id=identity,
                    payload={"finding_id": str(identity), "action": "observations_adopted"},
                ),
                AuditDraft(
                    action="intake_ai_finding.observations_adopted",
                    after_snapshot={
                        "finding_id": str(identity),
                        "proposal_id": proposal["id"],
                        "numbers": list(body.numbers),
                    },
                ),
            )
            from app.domain.intake_ai_imports import finish_if_all

            finish_if_all(c, ctx, identity, "project_intake_proposal", UUID(proposal["id"]))
            return self.prior(c, ctx, identity, body, signature) or {}

    def document(
        self, c: Connection, ctx: AuthContext, project: UUID, attachment: Any, content: bytes
    ) -> tuple[Any, dict[int, dict[str, Any]]]:
        d, f = tables.documents, tables.document_fragments
        expected = [
            {k: fragment[k] for k in ("ordinal", "locator", "text")}
            for fragment in attachment["fragments"]
        ]

        def fragments(identity: UUID) -> list[dict[str, Any]]:
            return [
                dict(row)
                for row in c.execute(
                    select(f.c.ordinal, f.c.locator, f.c.text)
                    .where(
                        f.c.tenant_id == ctx.tenant.id,
                        f.c.project_id == project,
                        f.c.document_id == identity,
                    )
                    .order_by(f.c.ordinal)
                ).mappings()
            ]

        candidates = c.execute(
            select(d)
            .where(
                d.c.tenant_id == ctx.tenant.id,
                d.c.project_id == project,
                d.c.sha256 == attachment["sha256"],
                d.c.classification == "internal",
            )
            .order_by(d.c.created_at, d.c.id)
        ).mappings()
        for document in candidates:
            if (
                fragments(document["id"]) == expected
                and document["extraction_metadata"] == attachment["extraction_metadata"]
            ):
                return document, {item["ordinal"]: item for item in expected}
        saved = DocumentService(self.engine, object_store=self.object_store).analyze(
            tenant_id=ctx.tenant.id,
            project_id=project,
            actor_user_id=ctx.user.id,
            filename=attachment["filename"],
            classification="internal",
            content=content,
            connection=c,
            include_coordinates=True,
        )
        document = (
            c.execute(select(d).where(d.c.tenant_id == ctx.tenant.id, d.c.id == saved.id))
            .mappings()
            .one()
        )
        actual = fragments(saved.id)
        if (
            actual != expected
            or document["extraction_metadata"] != attachment["extraction_metadata"]
        ):
            raise ConversationError("重新解析结果与已核对原文不一致，请重新抽取并整理")
        return document, {item["ordinal"]: item for item in actual}


def adoption_origins(
    c: Connection, ctx: AuthContext, project: UUID, proposal: UUID
) -> list[dict[str, Any]]:
    a, f, r, b = (
        tables.intake_ai_observation_applications,
        tables.findings,
        tables.agent_runs,
        tables.intake_ai_briefs,
    )
    from sqlalchemy import String, cast

    query = (
        select(a, b.c.conversation_id, b.c.message_id)
        .join(f, (f.c.tenant_id == a.c.tenant_id) & (f.c.id == a.c.finding_id))
        .join(r, (r.c.tenant_id == f.c.tenant_id) & (r.c.id == f.c.run_id))
        .join(
            b,
            (b.c.tenant_id == r.c.tenant_id)
            & (cast(b.c.id, String) == r.c.run_context["intake_brief_id"].astext),
        )
        .where(
            a.c.tenant_id == ctx.tenant.id, a.c.project_id == project, a.c.proposal_id == proposal
        )
    )
    return [
        {
            "number": row["proposal_number"],
            "created_by_user_id": str(row["created_by_user_id"]),
            "created_at": row["created_at"].isoformat(),
            "review_note": row["review_note"],
            "observation_keys": row["observation_keys"],
            "private_href": f"/ask?project={project}&conversation={row['conversation_id']}"
            if row["created_by_user_id"] == ctx.user.id
            else None,
        }
        for row in c.execute(query.order_by(a.c.proposal_number)).mappings()
    ]
