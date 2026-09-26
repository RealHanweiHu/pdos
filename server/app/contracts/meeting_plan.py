"""Cited ad-hoc meeting suggestions; formal dates and commitments require human review."""

from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_VERSION = "meeting-planning-v1"
RUN_VERSION = "meeting-planning-request-v1"
CAPABILITY = "knowledge_lite.meeting_planning"
FINDING_TYPE = "meeting_plan"
PURPOSE = "meeting_planning"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Quote(Input):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    reference_id: str = Field(min_length=1, max_length=160)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    exact_quote: str = Field(min_length=1, max_length=2000)


class Agenda(Input):
    title: str = Field(min_length=1, max_length=256)
    detail: str = Field(min_length=1, max_length=5000)
    expected_output: str = Field(min_length=1, max_length=2000)
    suggested_owner_id: UUID | None = None
    citations: tuple[Quote, ...] = Field(min_length=1, max_length=6)


class Participant(Input):
    user_id: UUID
    participation: Literal["required", "optional"]
    reason: str = Field(min_length=1, max_length=1000)


class Plan(Input):
    title: str = Field(min_length=1, max_length=240)
    meeting_type: Literal[
        "weekly",
        "material",
        "special",
        "technical_review",
        "decision_checkpoint",
        "pilot_review",
        "project_retrospective",
    ]
    purpose: str = Field(min_length=1, max_length=3000)
    participants: tuple[Participant, ...] = Field(max_length=99)
    agenda: tuple[Agenda, ...] = Field(min_length=1, max_length=12)


class MeetingAssessment(Input):
    disposition: Literal["plan", "insufficient_evidence"]
    plan: Plan | None = None
    open_questions: tuple[str, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def shape(self) -> Self:
        if (self.disposition == "plan") != (self.plan is not None):
            raise ValueError("会议草案与缺少依据状态须对应")
        if any(not q.strip() or len(q) > 2000 for q in self.open_questions):
            raise ValueError("待核对问题须为非空且有界的文字")
        if self.plan and len({p.user_id for p in self.plan.participants}) != len(
            self.plan.participants
        ):
            raise ValueError("建议参会人不能重复")
        return self


def references(source: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [
        {
            "reference_id": f"brief:{key}",
            "entity": "meeting_planning_brief",
            "entity_id": source["brief_id"],
            "label": label,
            "excerpt": source[key],
        }
        for key, label in (("question", "用户提出的问题"), ("expected_output", "用户期望产出"))
    ]
    for item in source["sources"]:
        for field, value in item["record"].items():
            if value is None or value == "":
                continue
            refs.append(
                {
                    "reference_id": f"{item['kind']}:{item['id']}:{field}",
                    "entity": item["kind"],
                    "entity_id": item["id"],
                    "label": f"{item['title']} · {field}",
                    "excerpt": str(value),
                }
            )
    return refs


def materialize(source: dict[str, Any], output: MeetingAssessment) -> dict[str, Any]:
    texts = {r["reference_id"]: r["excerpt"] for r in references(source)}
    people = {UUID(p["id"]) for p in source["participants"]}
    if output.plan:
        if any(p.user_id not in people for p in output.plan.participants):
            raise ValueError("建议人员不在原具名候选范围")
        for agenda in output.plan.agenda:
            if agenda.suggested_owner_id and agenda.suggested_owner_id not in people:
                raise ValueError("议题负责人不在原具名候选范围")
            for citation in agenda.citations:
                text = texts.get(citation.reference_id)
                if (
                    text is None
                    or citation.start >= citation.end
                    or citation.end > len(text)
                    or text[citation.start : citation.end] != citation.exact_quote
                ):
                    raise ValueError("议题引用须精确对应本次选入的文字片段")
    return {
        "brief_id": source["brief_id"],
        "assessment": output.model_dump(mode="json"),
        "source_digest": source["source_digest"],
    }
