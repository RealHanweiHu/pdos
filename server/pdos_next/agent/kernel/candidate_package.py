"""同一运行的候选整包确认（D77，P77）。

A package is only a transport for candidates that one run prepared. Each item is the
candidate's own frozen command with the confirmation token from its own preview, and it
runs through the ordinary command path in its own transaction, so every tier, binding,
revision and token check applies to it unchanged. Nothing is widened:

- only pending T0/T1 candidates of this run join; T2 and multi-step candidates are refused;
- the command must equal the frozen candidate apart from its confirmation token;
- each item commits or fails alone, and the response lists every item's outcome;
- an unexpected failure stops the package: the rest are reported as not attempted.
"""

import json
import logging
from uuid import UUID

from pydantic import Field
from sqlalchemy import select

from pdos_next.core.command_handlers import tier_of
from pdos_next.core.contracts import Command
from pdos_next.core.database import tenant_session
from pdos_next.core.schema_base import StrictModel
from pdos_next.errors import DomainError

from .models import AgentEvent, AgentRun

PACKAGE_LIMIT = 50
EVENT_LIMIT = 500
PACKAGE_TIERS = frozenset({"T0", "T1"})
SEPARATE_KINDS = frozenset({"work_followup", "verification_preparation"})
CANDIDATE_TYPES = ("domain_candidate", "snapshot_candidate", "verification_candidate")


class PackageItem(StrictModel):
    event_id: UUID
    command: Command


class CandidatePackage(StrictModel):
    items: list[PackageItem] = Field(min_length=1, max_length=PACKAGE_LIMIT)


def _error(code, reason, message, status=409):
    error = DomainError(code, message, status)
    error.detail["reason"] = reason
    return error


def _outcome(error):
    return {"code": error.code, "reason": error.detail.get("reason"), "message": error.message}


def _canonical(command):
    value = command.model_dump(mode="json") if isinstance(command, Command) else dict(command)
    value["payload"] = {
        key: entry
        for key, entry in (value.get("payload") or {}).items()
        if key not in {"confirmation_token", "approval_token"}
    }
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def current_candidates(engine, ctx, run_id):
    """This run's candidates, projected in one category read snapshot."""
    from pdos_next.domain.my_work.run_decisions import _visible

    from .domain_candidates import project_rows

    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
        read_snapshot=True,
    ) as s:
        run = s.get(AgentRun, run_id)
        if (
            run is None
            or run.tenant_id != ctx.tenant_id
            or run.requester_id != ctx.requester_id
            or run.category_id is None
            or run.category_id != ctx.category_id
        ):
            raise _error("FORBIDDEN_SCOPE", "candidate_run_mismatch", "运行不在当前可读范围。", 403)
        _visible(s, ctx, run)
        events = list(
            s.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.tenant_id == ctx.tenant_id,
                    AgentEvent.run_id == run.id,
                    AgentEvent.body["type"].astext.in_(CANDIDATE_TYPES),
                )
                .order_by(AgentEvent.sequence)
                .limit(EVENT_LIMIT)
            )
        )
        return {row["event_id"]: row for row in project_rows(s, ctx, run, events)}


def refusal(candidate, command):
    """Why one item cannot join the package; None when it may run its own command."""
    if candidate is None:
        return _error(
            "FORBIDDEN_SCOPE", "candidate_not_in_run", "该候选不属于此运行或已不可读。", 403
        )
    if candidate.get("state") != "pending":
        return _error("VERSION_CONFLICT", "candidate_not_pending", "该候选已保存、已取消或已失效。")
    if candidate.get("kind") in SEPARATE_KINDS or not candidate.get("command"):
        return _error(
            "NAMED_DECISION_REQUIRED", "candidate_separate_entry", "该候选须在原入口单独办理。", 403
        )
    try:
        tier = tier_of(command.operation)
    except DomainError as error:
        return error
    if tier not in PACKAGE_TIERS or command.payload.get("approval_token"):
        return _error(
            "NAMED_DECISION_REQUIRED", "package_named_decision", "具名决定不能整包确认。", 403
        )
    if _canonical(command) != _canonical(candidate["command"]):
        return _error(
            "VERSION_CONFLICT", "candidate_command_changed", "提交内容与原候选不一致，请重新核对。"
        )
    if not command.payload.get("confirmation_token"):
        return _error("CONFIRMATION_REQUIRED", "package_unconfirmed", "该候选尚未核对预览。")
    return None


def confirm(engine, ctx, run_id, package, execute_one):
    """Run each item's own command in order; every outcome is reported, none is hidden."""
    identities = [str(item.event_id) for item in package.items]
    if len(identities) != len(set(identities)):
        raise _error("VALIDATION_FAILED", "package_duplicate_item", "整包内不能重复同一候选。", 422)
    current = current_candidates(engine, ctx, run_id)
    results, stopped = [], False
    for item in package.items:
        entry = {"event_id": str(item.event_id), "operation": item.command.operation}
        if stopped:
            results.append({**entry, "status": "not_attempted"})
            continue
        refused = refusal(current.get(str(item.event_id)), item.command)
        if refused is not None:
            results.append({**entry, "status": "refused", "error": _outcome(refused)})
            continue
        try:
            receipt = execute_one(item.command)
        except DomainError as error:
            results.append({**entry, "status": "failed", "error": _outcome(error)})
            continue
        except Exception:
            # The outcome is unknown; the same request can be checked again with its key.
            logging.getLogger(__name__).exception("candidate package item outcome unknown")
            results.append({**entry, "status": "unknown"})
            stopped = True
            continue
        results.append({**entry, "status": "adopted", "receipt": receipt})
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("adopted", "refused", "failed", "unknown", "not_attempted")
    }
    return {"run_id": str(run_id), "items": results, **counts}
