"""要我决定 · 小Pai 运行分组（D78，P77）。

Pending candidates and unanswered questions from the caller's own 小Pai runs, grouped
by run. Each category is read in its own category read snapshot, and candidate state
comes from the same projection as the category candidate read (`project_rows`). This
module never previews, writes, resumes or answers anything.
"""

from dataclasses import replace

from sqlalchemy import String, cast, func, or_, select

from pdos_next.agent.kernel.models import AgentEvent, AgentRun
from pdos_next.core.database import tenant_session
from pdos_next.core.models import Category, RequestKey
from pdos_next.domain.categories.preproject.models import Proposal
from pdos_next.domain.my_work.views import _heads, _personal
from pdos_next.errors import DomainError

VERSION = "personal-run-decisions/v1"
RUN_LIMIT = 30
EVENT_LIMIT = 200
CANDIDATE_TYPES = ("domain_candidate", "snapshot_candidate", "verification_candidate")
# waiting_input without a question: reconciliation or an unavailable model, not a question.
REVIEW_CODES = frozenset({"EXTERNAL_OUTCOME_UNKNOWN", "SOURCE_UNAVAILABLE"})
# These candidates have their own multi-step entry; they never join a package.
SEPARATE_KINDS = frozenset({"work_followup", "verification_preparation"})
PACKAGE_TIERS = frozenset({"T0", "T1"})


def _open(engine, ctx, category_id=None):
    return tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=category_id,
        read_snapshot=True,
    )


def _mine(ctx):
    return (
        AgentRun.tenant_id == ctx.tenant_id,
        AgentRun.requester_id == ctx.requester_id,
        AgentRun.reverted_at.is_(None),
        AgentRun.state != "cancelled",
        or_(AgentRun.proposal_id.is_(None), AgentRun.proposal_id.in_(select(Proposal.id))),
    )


def _undecided(ctx):
    """A current-epoch candidate event whose frozen request this person has not sent yet.

    Only a prefilter: the projection below decides the actual state.
    """
    return (
        select(AgentEvent.id)
        .where(
            AgentEvent.tenant_id == AgentRun.tenant_id,
            AgentEvent.run_id == AgentRun.id,
            AgentEvent.body["type"].astext.in_(CANDIDATE_TYPES),
            AgentEvent.body["cancel_epoch"].astext == cast(AgentRun.cancel_epoch, String),
            ~select(RequestKey.key)
            .where(
                RequestKey.tenant_id == AgentEvent.tenant_id,
                RequestKey.actor_id == ctx.actor_id,
                RequestKey.key == AgentEvent.body["command"]["idempotency_key"].astext,
            )
            .exists(),
        )
        .exists()
    )


def _visible(session, ctx, run):
    """The same checks as reading the run itself; an unreadable run is left out."""
    if run.proposal_id is not None:
        from pdos_next.domain.categories.preproject.access import proposal

        proposal(session, ctx, run.proposal_id)
    from pdos_next.agent.kernel.project_scope import require_project

    require_project(session, ctx, run.project_id, run.product_id)


def _questions(session, run):
    if run.state != "waiting_input" or run.error_code in REVIEW_CODES:
        return None, None
    from pdos_next.agent.enterprise_search.assistant_answer import checked_sources

    checked_sources(session, run)
    event = session.scalar(
        select(AgentEvent)
        .where(
            AgentEvent.tenant_id == run.tenant_id,
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext == "needs_input",
        )
        .order_by(AgentEvent.sequence.desc())
        .limit(1)
    )
    raw = event.body.get("questions") if event else None
    if not isinstance(raw, list):
        return None, None
    questions = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            continue
        questions.append(
            {
                "id": str(item.get("id", "")),
                "question": item["question"],
                "why": item.get("why") if isinstance(item.get("why"), str) else "",
                "options": [
                    {"value": str(option.get("value")), "label": str(option.get("label"))}
                    for option in item.get("options") or []
                    if isinstance(option, dict)
                ],
                "allow_free_text": item.get("allow_free_text") is not False,
            }
        )
    return questions or None, event.sequence


def _candidate(item):
    from pdos_next.core.command_handlers import tier_of

    operation = item.get("operation")
    tier = None
    if operation:
        try:
            tier = tier_of(operation)
        except DomainError:
            tier = None
    reason = None
    if item.get("kind") in SEPARATE_KINDS or not item.get("command"):
        reason = "separate_entry"
    elif tier not in PACKAGE_TIERS:
        reason = "named_decision"
    entry = {
        "event_id": item["event_id"],
        "sequence": item["sequence"],
        "operation": operation,
        "write_tier": tier,
        "kind": item.get("kind"),
        "package": reason is None,
        "separate_reason": reason,
        "command": item.get("command") if reason is None else None,
    }
    if isinstance(item.get("summary"), dict):
        entry["summary"] = item["summary"]
    return entry


def _group(session, ctx, run, category):
    from pdos_next.agent.kernel.domain_candidates import project_rows

    _visible(session, ctx, run)
    candidates = []
    more = False
    if run.category_id is not None:
        events = list(
            session.scalars(
                select(AgentEvent)
                .where(
                    AgentEvent.tenant_id == ctx.tenant_id,
                    AgentEvent.run_id == run.id,
                    AgentEvent.body["type"].astext.in_(CANDIDATE_TYPES),
                )
                .order_by(AgentEvent.sequence)
                .limit(EVENT_LIMIT + 1)
            )
        )
        more = len(events) > EVENT_LIMIT
        candidates = [
            _candidate(item)
            for item in project_rows(session, ctx, run, events[:EVENT_LIMIT])
            if item.get("state") == "pending"
        ]
    questions, question_sequence = _questions(session, run)
    if not candidates and not questions and run.state != "waiting_input":
        return None
    return {
        "run_id": str(run.id),
        "goal": run.goal,
        "status": run.state,
        "error_code": run.error_code,
        "reading_token": f"{run.state}:{run.cancel_epoch}",
        "created_at": run.created_at.isoformat(),
        "scope": "category" if run.category_id else "personal",
        "category": category,
        "product_id": str(run.product_id) if run.product_id else None,
        "proposal_id": str(run.proposal_id) if run.proposal_id else None,
        "project_id": str(run.project_id) if run.project_id else None,
        "questions": questions or [],
        "question_sequence": question_sequence,
        "needs_review": run.state == "waiting_input" and not questions,
        "candidates": candidates,
        "more_candidates": more,
    }


def read(engine, ctx):
    """Newest runs first; at most RUN_LIMIT runs, with `truncated` when more may exist."""
    with _open(engine, ctx) as s:
        _personal(s, ctx)
        as_of = s.scalar(select(func.transaction_timestamp()))
        category_ids = set(
            s.scalars(select(AgentRun.category_id).where(*_mine(ctx)).distinct())
        ) - {None}
        # Plain values: the rows are read again inside each category's own snapshot.
        categories = {
            key: {"id": str(key), "name": row.name}
            for key, row in _heads(s, ctx, Category, category_ids, ("name",)).items()
        }
        personal = list(
            s.scalars(
                select(AgentRun)
                .where(
                    *_mine(ctx),
                    AgentRun.category_id.is_(None),
                    AgentRun.state == "waiting_input",
                )
                .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                .limit(RUN_LIMIT + 1)
            )
        )
        truncated = len(personal) > RUN_LIMIT
        groups, unavailable = [], 0
        for run in personal[:RUN_LIMIT]:
            try:
                group = _group(s, ctx, run, None)
            except DomainError:
                unavailable += 1
                continue
            if group:
                groups.append(group)
    # Unreadable categories never appear: their runs are not counted or named.
    for category_id in sorted(categories, key=str):
        scoped = replace(ctx, category_id=category_id)
        try:
            with _open(engine, scoped, category_id) as s:
                runs = list(
                    s.scalars(
                        select(AgentRun)
                        .where(
                            *_mine(scoped),
                            AgentRun.category_id == category_id,
                            or_(AgentRun.state == "waiting_input", _undecided(scoped)),
                        )
                        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
                        .limit(RUN_LIMIT + 1)
                    )
                )
                truncated = truncated or len(runs) > RUN_LIMIT
                for run in runs[:RUN_LIMIT]:
                    try:
                        group = _group(s, scoped, run, categories[category_id])
                    except DomainError:
                        unavailable += 1
                        continue
                    if group:
                        groups.append(group)
        except DomainError:
            continue
    groups.sort(key=lambda group: (group["created_at"], group["run_id"]), reverse=True)
    truncated = truncated or len(groups) > RUN_LIMIT
    groups = groups[:RUN_LIMIT]
    return {
        "version": VERSION,
        "principal_id": str(ctx.requester_id),
        "as_of": as_of.isoformat(),
        "runs": groups,
        "total_runs": len(groups),
        "candidate_count": sum(len(group["candidates"]) for group in groups),
        "question_count": sum(len(group["questions"]) for group in groups),
        "truncated": truncated,
        "unavailable_runs": unavailable,
    }
