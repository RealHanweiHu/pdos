"""Evidence-backed replacement of historical content, preserving originals and approvals."""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Engine, or_, select

from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.db.schema import tables
from app.domain.conversations import ConversationError
from app.domain.decision_intake_corrections import (
    DecisionIntakeCorrections,
    DecisionSourceCorrection,
    basis,
    source,
)
from app.domain.decision_intake_targets import read_target, snapshot
from app.domain.decisions import DecisionDraft, DecisionService
from app.domain.issue_intake_compensation_results import (
    ResultEvidence,
    current_evidence,
    document_snapshot,
)
from app.domain.knowledge_corrections import KnowledgeCorrectionService
from app.domain.knowledge_push import KnowledgeAccessError
from app.domain.product_workspace import _plain, digest
from app.domain.project_write_lock import lock_project_write_scope
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft

TextValue = Annotated[str, Field(max_length=20000)]
FACTS = {
    "historical_date": "historical_date",
    "historical_approver": "raw_approver",
    "historical_owner": "raw_owner",
    "historical_kind": "raw_kind",
    "historical_state": "raw_state",
    "external_ref": "external_ref",
    "issue_ref": "issue_ref",
}


class HistoricalContentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[str, Field(max_length=512)] | None = None
    outcome: TextValue | None = None
    context: TextValue | None = None
    options_text: TextValue | None = None
    trade_offs: TextValue | None = None
    rationale: TextValue | None = None
    consequence: TextValue | None = None
    historical_date: date | None = None
    historical_approver: TextValue | None = None
    historical_owner: TextValue | None = None
    historical_kind: TextValue | None = None
    historical_state: TextValue | None = None
    external_ref: TextValue | None = None
    issue_ref: TextValue | None = None

    @field_validator("*", mode="before")
    @classmethod
    def blanks(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def meaningful(self) -> "HistoricalContentPatch":
        if not self.model_fields_set:
            raise ValueError("请选择实际需要更正的字段")
        if any(
            key in self.model_fields_set and getattr(self, key) is None
            for key in ("title", "outcome")
        ):
            raise ValueError("历史决策标题与结论不可清空")
        return self


class HistoricalAmendment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    expected_revision: int = Field(ge=0)
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: HistoricalContentPatch
    reason: str = Field(min_length=1, max_length=2000)
    impact_note: str = Field(min_length=1, max_length=4000)
    evidence: list[ResultEvidence] = Field(min_length=1, max_length=10)
    acknowledge_history: Literal[True]

    @model_validator(mode="after")
    def distinct_evidence(self) -> "HistoricalAmendment":
        if len({item.document_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("同一文件请合并核对依据")
        self.evidence.sort(key=lambda item: str(item.document_id))
        return self


def editable(current: dict[str, Any], identity: UUID) -> bool:
    decision = current.get("current_decision")
    return bool(
        decision
        and decision["decision_kind"] == "historical_record"
        and decision.get("historical_source", {}).get("source_row_id") == str(identity)
    )


def content(record: dict[str, Any]) -> dict[str, Any]:
    original = record["historical_source"]
    facts = {key: original.get(value) for key, value in FACTS.items()}
    facts.update(original.get("corrected_facts", {}))
    return {
        **{
            key: record.get(key)
            for key in ("title", "outcome", "context", "trade_offs", "rationale", "consequence")
        },
        "options_text": "\n".join(record.get("options", [])) or None,
        **facts,
    }


class DecisionIntakeAmendments:
    def __init__(self, engine: Engine):
        self.engine = engine

    def read(
        self, ctx: AuthContext, project: UUID, identity: UUID, *, before_revision: int | None = None
    ) -> dict[str, Any]:
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            row = source(c, ctx, project, identity)
            current = basis(c, ctx.tenant.id, project, row)
            can_edit = True
            try:
                KnowledgeCorrectionService._authorize(
                    c, ctx.tenant.id, ctx.user.id, project, Action.WORK_ITEM_EDIT
                )
            except KnowledgeAccessError:
                can_edit = False
            t, u = tables.decision_intake_amendments, tables.users
            query = (
                select(t, u.c.display_name.label("actor_name"))
                .join(u, (u.c.tenant_id == t.c.tenant_id) & (u.c.id == t.c.created_by_user_id))
                .where(t.c.tenant_id == ctx.tenant.id, t.c.source_row_id == identity)
            )
            if before_revision is not None:
                query = query.where(t.c.source_revision < before_revision)
            rows = c.execute(query.order_by(t.c.source_revision.desc()).limit(21)).mappings().all()
            refs = current_evidence(
                c, ctx.tenant.id, project, [ref for item in rows[:20] for ref in item["evidence"]]
            )
            by_id = {item["document_id"]: item["current"] for item in refs}
            items = []
            for item in rows[:20]:
                value = _plain(item)
                value["evidence_current"] = [
                    {
                        **ref,
                        "current": by_id.get(ref["document_id"]),
                        "changed": by_id.get(ref["document_id"]) is None
                        or digest(by_id[ref["document_id"]]) != ref["expected_digest"],
                    }
                    for ref in item["evidence"]
                ]
                items.append(value)
            return {
                **current,
                "can_amend": can_edit and editable(current, identity),
                "content": content(current["current_decision"])
                if editable(current, identity)
                else None,
                "original": row["source_snapshot"]["row"],
                "history": items,
                "next_before_revision": rows[19]["source_revision"] if len(rows) > 20 else None,
            }

    def evidence(
        self,
        ctx: AuthContext,
        project: UUID,
        identity: UUID,
        *,
        search: str = "",
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> dict[str, Any]:
        if (before_created_at is None) != (before_id is None):
            raise ConversationError("文件分页位置不完整")
        with self.engine.connect() as c:
            row = source(c, ctx, project, identity)
            t = tables.documents
            query = select(t).where(
                t.c.tenant_id == ctx.tenant.id,
                t.c.project_id == project,
                t.c.classification == "internal",
            )
            if search.strip():
                query = query.where(t.c.filename.icontains(search.strip(), autoescape=True))
            if before_created_at is not None:
                query = query.where(
                    or_(
                        t.c.created_at < before_created_at,
                        (t.c.created_at == before_created_at) & (t.c.id < before_id),
                    )
                )
            rows = (
                c.execute(query.order_by(t.c.created_at.desc(), t.c.id.desc()).limit(51))
                .mappings()
                .all()
            )
            original = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.project_id == project,
                        t.c.id == row["document_id"],
                        t.c.classification == "internal",
                    )
                )
                .mappings()
                .one_or_none()
            )

            def view(item: Any) -> dict[str, Any]:
                value = document_snapshot(item)
                return value | {
                    "digest": digest(value),
                    "href": f"/projects?project={project}&tab=documents&entity_id={item['id']}",
                }

            return {
                "items": [view(item) for item in rows[:50]],
                "original": view(original) if original else None,
                "next": {
                    "before_created_at": rows[49]["created_at"].isoformat(),
                    "before_id": str(rows[49]["id"]),
                }
                if len(rows) > 50
                else None,
            }

    def save(
        self, ctx: AuthContext, project: UUID, identity: UUID, body: HistoricalAmendment
    ) -> dict[str, Any]:
        signature = digest(
            body.model_dump(mode="json", exclude={"request_id", "changes"})
            | {"changes": body.changes.model_dump(mode="json", exclude_unset=True)}
        )
        with self.engine.begin() as c:
            if not lock_project_write_scope(c, tenant_id=ctx.tenant.id, project_id=project):
                raise ConversationError("项目当前不可办理")
            row = source(c, ctx, project, identity, write=True)
            t = tables.decision_intake_amendments
            prior = (
                c.execute(
                    select(t).where(
                        t.c.tenant_id == ctx.tenant.id,
                        t.c.source_row_id == identity,
                        t.c.request_id == body.request_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if prior is not None:
                if prior["request_digest"] != signature:
                    raise ConversationError("本请求已对应其他更正，请读取原回执")
                return {"receipt": _plain(prior)}
            current = basis(c, ctx.tenant.id, project, row, lock=True)
            if (
                current["revision"] != body.expected_revision
                or current["digest"] != body.expected_digest
            ):
                raise ConversationError("当前来源或业务内容已变化，请重新读取并核对")
            if not editable(current, identity):
                raise ConversationError(
                    "只能更正本来源当前登记的历史决策；已批准业务或其他来源请从各自原流程办理"
                )
            old = current["current_decision"]
            old_content = content(old)
            patch = body.changes.model_dump(mode="json", exclude_unset=True)
            changes = {
                key: {"before": old_content[key], "after": value}
                for key, value in patch.items()
                if old_content[key] != value
            }
            if not changes:
                raise ConversationError("所选字段与当前历史记录相同，无需重复更正")
            refs = current_evidence(
                c, ctx.tenant.id, project, [ref.model_dump(mode="json") for ref in body.evidence]
            )
            if any(ref["changed"] for ref in refs):
                raise ConversationError("更正依据文件已变化或不可用，请重新核对")
            refs = [
                {key: value for key, value in ref.items() if key not in {"current", "changed"}}
                | {"snapshot": ref["current"]}
                for ref in refs
            ]
            value = old_content | patch
            amendment_id = uuid4()
            meta = dict(old["historical_source"])
            meta.update(
                amendment_id=str(amendment_id),
                replaces_decision_id=old["id"],
                corrected_facts={key: value[key] for key in FACTS},
                corrected_missing_fields=[
                    key
                    for key in (
                        "context",
                        "options_text",
                        "trade_offs",
                        "rationale",
                        "consequence",
                        "historical_date",
                        "historical_approver",
                    )
                    if not value.get(key)
                ],
                review_note=body.reason,
                reviewed_by_user_id=str(ctx.user.id),
                amendment_evidence=refs,
            )
            record = DecisionService(self.engine).record_history(
                connection=c,
                tenant_id=ctx.tenant.id,
                project_id=project,
                actor_user_id=ctx.user.id,
                historical_source=meta,
                draft=DecisionDraft(
                    decision_kind="historical_record",
                    title=value["title"],
                    outcome=value["outcome"],
                    context=value["context"],
                    options=(value["options_text"],) if value["options_text"] else (),
                    trade_offs=value["trade_offs"],
                    rationale=value["rationale"],
                    consequence=value["consequence"],
                    evidence_refs=tuple(
                        dict.fromkeys(
                            [
                                *old["evidence_refs"],
                                *[f"document:{ref['document_id']}" for ref in refs],
                            ]
                        )
                    ),
                ),
            )
            after = snapshot(
                read_target(c, ctx.tenant.id, project, "decision", record.id), "decision"
            )
            correction = DecisionIntakeCorrections(self.engine).correct(
                ctx,
                project,
                identity,
                DecisionSourceCorrection(
                    request_id=uuid5(body.request_id, "historical-content-amendment"),
                    expected_revision=body.expected_revision,
                    expected_digest=body.expected_digest,
                    action="reassign",
                    target_decision_id=record.id,
                    expected_decision_digest=digest(after),
                    target_issue_id=UUID(current["current_issue_id"])
                    if current["current_issue_id"]
                    else None,
                    expected_issue_digest=current["current_issue_digest"],
                    reason=body.reason,
                    impact_note=body.impact_note,
                    acknowledge_history=True,
                ),
                connection=c,
            )["receipt"]
            receipt = (
                c.execute(
                    t.insert()
                    .values(
                        id=amendment_id,
                        tenant_id=ctx.tenant.id,
                        project_id=project,
                        source_row_id=identity,
                        source_revision=correction["revision"],
                        previous_decision_id=UUID(old["id"]),
                        replacement_decision_id=record.id,
                        request_id=body.request_id,
                        request_digest=signature,
                        reason=body.reason,
                        impact_note=body.impact_note,
                        changes=changes,
                        before_snapshot=old,
                        after_snapshot=after,
                        evidence=refs,
                        created_by_user_id=ctx.user.id,
                    )
                    .returning(t)
                )
                .mappings()
                .one()
            )
            EventAuditWriter(
                c, tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, project_id=project
            ).record(
                EventDraft(
                    event_id=f"decision-amendment:{amendment_id}",
                    event_type="DECISION_INTAKE_SOURCE_RECORDED",
                    source="decision_intake_service",
                    entity_id=identity,
                    payload={
                        "source_row_id": str(identity),
                        "record_id": str(amendment_id),
                        "action": "amend_history",
                    },
                ),
                AuditDraft(
                    action="decision_intake.amend_history",
                    before_snapshot=old,
                    after_snapshot=after,
                    context={"changes": changes, "evidence": refs, "impact_note": body.impact_note},
                ),
            )
            return {"receipt": _plain(receipt)}
