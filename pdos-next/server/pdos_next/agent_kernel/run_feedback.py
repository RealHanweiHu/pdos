"""Private human feedback about an actual Run, separate from model input or business decisions."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, field_validator
from sqlalchemy import func, select

from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .models import AgentEvent, AgentRun
from .run_reconciliation import owner

KIND = "run_feedback"
Reason = Literal[
    "wrong_object",
    "wrong_value",
    "missing_source",
    "not_useful",
    "too_many_actions",
    "should_not_automate",
]


def lookup(session, identity, *, lock=False):
    query = select(
        AgentRun.id,
        AgentRun.tenant_id,
        AgentRun.category_id,
        AgentRun.proposal_id,
        AgentRun.requester_id,
        AgentRun.cancel_epoch,
        *[
            AgentRun.versions[key].label(key)
            for key in (
                "model_version",
                "model_route_digest",
                "tool_definitions",
                "prompt_prefixes",
            )
        ],
    ).where(AgentRun.id == identity)
    row = session.execute(query.with_for_update() if lock else query).mappings().one_or_none()
    if row is None:
        return None
    values = dict(row)
    versions = {
        key: values.pop(key)
        for key in ("model_version", "model_route_digest", "tool_definitions", "prompt_prefixes")
    }
    return SimpleNamespace(**values, versions=versions)


class FeedbackInput(StrictModel):
    idempotency_key: UUID
    categories: list[Reason] = Field(min_length=1, max_length=6)
    comment: str = Field(default="", max_length=2000)
    skill_load_event_id: UUID | None = None

    @field_validator("categories")
    @classmethod
    def unique_categories(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("同一反馈类别只能选择一次。")
        return sorted(values)


def loaded_skills(session, run):
    rows = session.execute(
        select(
            AgentEvent.id,
            AgentEvent.body["key"].astext.label("key"),
            AgentEvent.body["version"].astext.label("version"),
            AgentEvent.body["digest"].astext.label("digest"),
            AgentEvent.body["isolation"].astext.label("isolation"),
        )
        .where(AgentEvent.run_id == run.id, AgentEvent.body["type"].astext == "skill_loaded")
        .order_by(AgentEvent.sequence.desc())
    ).all()
    seen, values = set(), []
    for row in rows:
        identity = (row.key, row.version, row.digest, row.isolation)
        if identity in seen or not all(isinstance(value, str) and value for value in identity):
            continue
        seen.add(identity)
        values.append(
            {
                "load_event_id": str(row.id),
                "key": row.key,
                "version": row.version,
                "digest": row.digest,
                "isolation": row.isolation,
            }
        )
    return values


def version_identity(run, skills):
    # Never copy proposal context, provider credentials or the model's result JSON.
    versions = run.versions
    return {
        "model_version": versions.get("model_version"),
        "model_route_digest": versions.get("model_route_digest"),
        "tool_definitions": deepcopy(versions.get("tool_definitions") or {}),
        "prompt_prefixes": deepcopy(versions.get("prompt_prefixes") or {}),
        "skills": deepcopy(skills),
        "cancel_epoch": run.cancel_epoch,
    }


def item(event):
    body = event.body
    if body.get("feedback_id") != str(event.id) or body.get("type") != KIND:
        raise DomainError("SOURCE_UNAVAILABLE", "反馈不能与原运行记录核对。")
    return {
        "id": str(event.id),
        "sequence": event.sequence,
        "recorded_at": event.created_at.isoformat(),
        "request": body["request"],
        "versions": body["versions"],
        "recorded_by": body["recorded_by"],
    }


def read(session, ctx, run, *, before=None, page_size=25, request_key=None):
    owner(session, ctx, run)
    query = select(AgentEvent).where(
        AgentEvent.run_id == run.id,
        AgentEvent.body["type"].astext == KIND,
    )
    if before is not None:
        if not session.scalar(
            select(AgentEvent.id).where(
                AgentEvent.run_id == run.id,
                AgentEvent.sequence == before,
                AgentEvent.body["type"].astext == KIND,
            )
        ):
            raise DomainError("FORBIDDEN_SCOPE", "反馈游标不属于当前运行。", 403)
        query = query.where(AgentEvent.sequence < before)
    if request_key is not None:
        if before is not None:
            raise DomainError("VALIDATION_FAILED", "原请求核对不能混用历史游标。", 422)
        query = query.where(
            AgentEvent.body["request"]["idempotency_key"].astext == str(request_key)
        )
    rows = session.scalars(query.order_by(AgentEvent.sequence.desc()).limit(page_size + 1)).all()
    skills = loaded_skills(session, run)
    return {
        "run_id": str(run.id),
        "owner_id": str(run.requester_id),
        "current_versions": version_identity(run, skills),
        "items": [item(row) for row in rows[:page_size]],
        "next_before": rows[page_size - 1].sequence if len(rows) > page_size else None,
    }


def record(session, ctx, run, data):
    # The API holds the Run row lock, shared with all other event appenders.
    owner(session, ctx, run)
    request = data.model_dump(mode="json")
    fingerprint = digest(
        {
            "run_id": run.id,
            "requester_id": ctx.requester_id,
            "request": {key: value for key, value in request.items() if key != "idempotency_key"},
        }
    )
    previous = session.scalar(
        select(AgentEvent).where(
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext == KIND,
            AgentEvent.body["request"]["idempotency_key"].astext == str(data.idempotency_key),
        )
    )
    if previous is not None:
        if previous.body.get("request_digest") != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "原请求编号对应不同反馈。")
        return {"run_id": str(run.id), "feedback": item(previous)}
    skills = loaded_skills(session, run)
    if data.skill_load_event_id is not None:
        # Accept any actual historical load, including a repeated load of the same skill.
        actual = session.get(AgentEvent, data.skill_load_event_id)
        if not actual or actual.run_id != run.id or actual.body.get("type") != "skill_loaded":
            raise DomainError("FORBIDDEN_SCOPE", "请选择本次运行实际加载的方法。", 403)
        matching = [
            value
            for value in skills
            if all(
                value[key] == actual.body.get(key)
                for key in ("key", "version", "digest", "isolation")
            )
        ]
        if not matching:
            raise DomainError("SOURCE_UNAVAILABLE", "原方法版本无法核对。")
        skills = [{**matching[0], "load_event_id": str(actual.id)}]
    identity = uuid4()
    sequence = (
        session.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run.id,
            )
        )
        + 1
    )
    event = AgentEvent(
        id=identity,
        tenant_id=run.tenant_id,
        run_id=run.id,
        sequence=sequence,
        body={
            "type": KIND,
            "feedback_id": str(identity),
            "recorded_by": str(ctx.actor_id),
            "request": request,
            "request_digest": fingerprint,
            "versions": version_identity(run, skills),
        },
    )
    session.add(event)
    session.flush()
    return {"run_id": str(run.id), "feedback": item(event)}
