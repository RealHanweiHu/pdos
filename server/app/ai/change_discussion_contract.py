"""Read-only professional discussion outputs and immutable seat input preparation."""

from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.change_impact_preparation import encoded
from app.ai.executor import PromptFile
from app.contracts.change_work_package import Statement
from app.domain.product_workspace import ProductWorkError, digest

KEY = "engineering_intelligence.change_discussion"
PURPOSE = "change_discussion"
RUN_VERSION = "change-discussion-request-v1"
PROMPT = PromptFile.model_validate_json(
    (Path(__file__).with_name("prompts") / "change_discussion_v1.json").read_text()
)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    turn_id: UUID
    position: Literal["agree", "disagree", "needs_evidence"]
    basis: Statement


class DiscussionTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    disposition: Literal["position", "insufficient_evidence"]
    statements: tuple[Statement, ...] = Field(max_length=12)
    responses: tuple[Response, ...] = Field(max_length=12)
    missing: tuple[str, ...] = Field(max_length=30)

    @model_validator(mode="after")
    def evidence(self) -> Self:
        if self.disposition == "position" and not self.statements:
            raise ValueError("明确立场须有引用依据")
        if self.disposition == "insufficient_evidence" and not self.missing:
            raise ValueError("缺少资料须明确说明")
        if len({v.turn_id for v in self.responses}) != len(self.responses):
            raise ValueError("对同一原发言请合并回应")
        return self


def call_id(run_id: UUID, seat_id: UUID, round_number: int) -> UUID:
    if not 1 <= round_number <= 3:
        raise ProductWorkError("讨论轮次不属于固定运行范围")
    return uuid5(run_id, f"pdos-discussion.v1:{seat_id}:{round_number}")


def seat_input(
    source: dict[str, Any],
    projection: dict[str, Any],
    question: str,
    round_number: int,
    transcript: list[dict[str, Any]],
    followup_reason: str | None = None,
) -> dict[str, Any]:
    allowed = set(projection["reference_ids"] + projection["shared_reference_ids"])
    references = [r for r in source["model_context"]["references"] if r["reference_id"] in allowed]
    for turn in transcript:
        fields = {k: turn[k] for k in ("id", "speaker_kind", "seat_key", "round_number", "content")}
        references.append(
            {
                "reference_id": "turn:" + turn["id"],
                "category": "discussion_turn",
                "label": "已记录发言 / 人工补充",
                "fields": fields,
                "digest": digest(fields),
                "omitted_fields": [],
            }
        )
    if len(encoded(references)) > 160000:
        raise ProductWorkError("发言输入超过本次容量，需缩小轮次或资料范围")
    context = {
        "question": encoded(
            {
                "question": question,
                "seat": projection["label"],
                "round": round_number,
                "missing": projection["missing"],
                "coverage": source["model_context"]["coverage"],
                **({"user_followup_reason": followup_reason} if followup_reason else {}),
            }
        ),
        "references": [
            {
                "reference_id": r["reference_id"],
                "entity": r["category"],
                "label": r["label"],
                "excerpt": encoded({k: r[k] for k in ("digest", "fields", "omitted_fields")}),
            }
            for r in references
        ],
    }
    return {
        "ecr_id": source["ecr_id"],
        "topic_id": source.get("topic_id", source["ecr_id"]),
        "source": source,
        "projection": projection,
        "round_number": round_number,
        "references": references,
        "transcript": transcript,
        "context": context,
    }


def validate(value: DiscussionTurn, snapshot: dict[str, Any]) -> None:
    references = {r["reference_id"]: r for r in snapshot["references"]}
    turns = {v["id"] for v in snapshot["transcript"]}
    if any(str(r.turn_id) not in turns for r in value.responses):
        raise ProductWorkError("回应的原发言不在本次实际读取范围内")
    for statement in [*value.statements, *(r.basis for r in value.responses)]:
        for citation in statement.citations:
            ref = references.get(citation.reference_id)
            if ref is None or ref["digest"] != citation.digest:
                raise ProductWorkError("引用越出本席位固定资料或原版本")
            if ref["category"] == "discussion_turn" and statement.nature == "observed":
                raise ProductWorkError("他席发言及人工补充不能当作已核实业务事实")
            current: Any = ref["fields"]
            for key in citation.field_path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                elif isinstance(current, list) and key.isdecimal() and int(key) < len(current):
                    current = current[int(key)]
                else:
                    raise ProductWorkError("引用字段未在本次读取中")
            if citation.quoted_value != (current if isinstance(current, str) else encoded(current)):
                raise ProductWorkError("引用摘录与原字段不同")
