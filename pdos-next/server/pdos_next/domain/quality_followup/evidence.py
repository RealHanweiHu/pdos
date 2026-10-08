"""Exact whole-line completion observations, with no source-existence shortcuts."""

import json
from datetime import UTC

from pydantic import ValidationError

from pdos_next.domain.quality_execution.evidence import POSITION, check_source
from pdos_next.errors import DomainError
from pdos_next.service import source_for

from .schemas import CompletionFact


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate completion JSON key")
        value[key] = item
    return value


def _constant(value):
    raise ValueError("Non-finite JSON constant")


def verify_completion_line(line, issue, purpose, completion, actor_id, at):
    """Pure exact parser. Caller must separately verify ACL/hash/provenance/security."""
    try:
        raw = json.loads(line, object_pairs_hook=_pairs, parse_constant=_constant)
        if not isinstance(raw, dict):
            raise ValueError("Completion fact must be an object")
        fact = CompletionFact.model_validate(raw)
    except (ValueError, TypeError, ValidationError) as exc:
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "完成事实须为精确结构化整行原文。", 422
        ) from exc
    if issue.capa is None:
        raise DomainError("INVALID_STATE", "需要已有固定CAPA措施。")
    action = next((a for a in issue.capa.actions if a.id == completion.id), None)
    if action is None or action.executor_id != actor_id or completion.executor_id != actor_id:
        raise DomainError("NAMED_EXECUTOR_REQUIRED", "仅原措施执行人本人可记录完成。", 403)
    if (
        fact.issue_id != issue.id
        or fact.capa_id != issue.capa.id
        or fact.action_id != completion.id
        or fact.executor_id != actor_id
        or fact.purpose != purpose
        or fact.text != completion.text
        or fact.occurred_at != completion.at.occurred_at
        or fact.original_timezone != completion.at.original_timezone
    ):
        raise DomainError(
            "MISSING_REQUIRED_EVIDENCE", "完成原文与固定问题/措施/本人/时点不一致。", 422
        )
    if at.tzinfo is None or at.utcoffset() is None or fact.occurred_at > at.astimezone(UTC):
        raise DomainError("INVALID_EVENT_TIME", "完成发生时点须为真实非未来时间。", 422)
    return fact


def completion_observation(s, ctx, pid, issue, purpose, completion, at):
    source = completion.at.source
    reads, basis, private = check_source(s, ctx, pid, source)
    match = POSITION.fullmatch(source.position)
    row = source_for(s, ctx, pid, source.id, source.revision)
    fact = verify_completion_line(
        row.content.splitlines()[int(match[1]) - 1],
        issue,
        purpose,
        completion,
        ctx.requester_id,
        at() if callable(at) else at,
    )
    return fact, reads, basis, private
