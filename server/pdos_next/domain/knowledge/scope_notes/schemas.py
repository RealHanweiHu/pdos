"""Closed payloads of the three scope-note commands (M2b; P87, P121 第 3、4、6 项).

``scope_note.save`` and ``scope_note.retire`` are T1: 小Pai may prefill them, a
member with write permission on the scope confirms once. ``scope_note.observation
.record`` is the T0 lane of P121 第 4 项 for two things only: a new unverified
observation, or an evidence link on an existing note. Without a qualification
for "tenant × skill package × model version" the registered graph prepares it
for a person instead, who confirms once like any T1 command.

Nothing here is a policy fact: the tenant, the person, the readable scope, the
versions of referenced objects, the source authority and who confirmed are all
bound by the server.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SAVE = "scope_note.save"
RETIRE = "scope_note.retire"
OBSERVE = "scope_note.observation.record"
EVENTS = {
    SAVE: "scope_note.saved",
    RETIRE: "scope_note.retired",
    OBSERVE: "scope_note.observation_recorded",
}
SUBJECT = "scope_note"
STATEMENT_LIMIT = 300
REASON_LIMIT = 200
EVIDENCE_LIMIT = 10

AnchorKind = Literal["category", "product", "proposal", "project"]
Kind = Literal["convention", "concern", "decision_context", "observation"]
Statement = Annotated[str, Field(min_length=1, max_length=STATEMENT_LIMIT)]
Tag = Annotated[str, Field(min_length=1, max_length=40)]
Customer = Annotated[str, Field(min_length=1, max_length=80)]
Token = Annotated[str, Field(min_length=20, max_length=128)]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Anchor(DTO):
    kind: AnchorKind
    id: UUID


class NoteRef(DTO):
    id: UUID
    revision: int = Field(ge=1, strict=True)


class ObjectRef(DTO):
    """A business object; the server reads it now and binds its current version."""

    kind: AnchorKind
    id: UUID


class FormalRef(DTO):
    """正式决定或对象版本 a 决策背景 hangs on; the server binds the version."""

    kind: Literal["category", "product", "proposal", "project", "proposal_decision"]
    id: UUID


class EvidenceInput(DTO):
    source_type: Literal["run", "discussion", "receipt", "original", "business_object"]
    source_id: UUID
    source_kind: Literal[
        "category", "product", "proposal", "project", "proposal_decision"
    ] | None = None
    # Where in the source (turn, page, paragraph, cell). The quote itself is never stored:
    # only its digest, so the passage is re-read under the reader's own permission.
    locator: dict[str, str | int] = Field(default_factory=dict, max_length=6)
    quote: str | None = Field(default=None, min_length=1, max_length=2000)
    stance: Literal["supports", "opposes", "context"] = "supports"

    @model_validator(mode="after")
    def shaped(self):
        if (self.source_type == "business_object") != (self.source_kind is not None):
            raise ValueError("只有业务对象来源要写明对象种类。")
        return self


class RelationInput(DTO):
    type: Literal["supersedes", "conflicts", "duplicates", "refines", "derived_from"]
    note: NoteRef


class NoteBody(DTO):
    kind: Kind
    statement: Statement
    subject: ObjectRef | None = None
    customer: Customer | None = None
    stage: Tag | None = None
    topic: Tag | None = None
    epistemic: Literal["stated", "verified", "inferred", "disputed"] = "stated"
    # 讨论: recorded as something said, not agreed. 成员确认 is the default of a confirmed save.
    confirmation: Literal["discussion", "member_confirmed"] = "member_confirmed"
    formal: FormalRef | None = None
    occurred_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    pinned: bool = False


class SavePayload(DTO):
    anchor: Anchor
    note: NoteRef | None = None  # None: a new note; otherwise a new version of this one.
    body: NoteBody
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=EVIDENCE_LIMIT)
    relations: list[RelationInput] = Field(default_factory=list, max_length=5)
    # Similar notes the person saw and chose to keep side by side.
    kept_similar: list[UUID] = Field(default_factory=list, max_length=20)
    # 分享到项目: the person's own memory note this was written from (reference only).
    shared_from_note: UUID | None = None
    request_ref: UUID | None = None
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def shaped(self):
        if self.note is not None and (self.relations or self.shared_from_note):
            raise ValueError("修改已有条目时不带关系或分享来源；关系在新建时确定。")
        targets = [item.note.id for item in self.relations]
        if len(set(targets)) != len(targets) or len(set(self.kept_similar)) != len(
            self.kept_similar
        ):
            raise ValueError("同一条旧条目只能出现一次。")
        return self


class RetirePayload(DTO):
    """停用 (no longer applies) or 撤回 (was wrong); or 按运行撤回 小Pai's own writes."""

    note: NoteRef | None = None
    run_id: UUID | None = None
    action: Literal["retire", "withdraw"] = "retire"
    reason: str = Field(min_length=1, max_length=REASON_LIMIT)
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def one_target(self):
        if (self.note is None) == (self.run_id is None):
            raise ValueError("指明一条条目，或指明要撤回的那次运行，二选一。")
        if self.run_id is not None and self.action != "withdraw":
            raise ValueError("按运行办理的只能是撤回。")
        return self


class ObservePayload(DTO):
    mode: Literal["observation", "evidence"]
    # observation: where it is attached and what was observed.
    anchor: Anchor | None = None
    statement: Statement | None = None
    subject: ObjectRef | None = None
    customer: Customer | None = None
    stage: Tag | None = None
    topic: Tag | None = None
    inferred: bool = False
    occurred_at: datetime | None = None
    # evidence: the existing note the links are added to.
    note: NoteRef | None = None
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=EVIDENCE_LIMIT)
    request_ref: UUID | None = None
    confirmation_token: Token | None = None

    @model_validator(mode="after")
    def shaped(self):
        if self.mode == "observation":
            if self.anchor is None or self.statement is None or self.note is not None:
                raise ValueError("记观察须写明挂靠对象和内容，不带已有条目。")
        elif (self.note is None or not self.evidence or self.anchor is not None
              or self.statement is not None or self.subject is not None
              or self.customer or self.stage or self.topic or self.inferred
              or self.occurred_at is not None):
            raise ValueError("补充证据须指明已有条目并至少带一条证据，不改条目内容。")
        return self


PAYLOADS = {SAVE: SavePayload, RETIRE: RetirePayload, OBSERVE: ObservePayload}
