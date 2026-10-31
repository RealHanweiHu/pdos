"""Server-owned cross-turn state with verbatim user constraints and human tombstones."""

import json
from copy import deepcopy
from dataclasses import replace
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter
from pydantic import Field, model_validator
from sqlalchemy import select, text

from pdos_next.errors import DomainError
from pdos_next.models import Category, Product, Receipt
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .context_budget import estimate_tokens
from .models import AgentEvent, AgentRun, AgentSession
from .search_preferences import SearchPreferences
from .search_preferences import defaults as search_defaults
from .session_presentation import _target
from .session_views import _human
from .work_state_models import AgentWorkState

STATE_TOKENS = 1500
COMPLETED_LIMIT = 10
PAGE_MATERIAL_BOUNDARY = (
    "\n\n当前页面资料（请按服务器权限重新读取固定版本；未保存输入仅供讨论）：\n"
)


def user_goal(value):
    """The existing composer appends page data; it cannot prove a human instruction."""
    return value.partition(PAGE_MATERIAL_BOUNDARY)[0]


class ChangeInput(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    request_key: UUID
    action: Literal["remove_constraint", "exclude_source", "remove_exclusion", "set_search_scope"]
    item_id: UUID | None = None
    search_preferences: SearchPreferences | None = None

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "set_search_scope":
            if self.item_id is not None or self.search_preferences is None:
                raise ValueError("查找范围修改须提供完整选择，不能修改携带条目。")
        elif self.item_id is None or self.search_preferences is not None:
            raise ValueError("携带条目修改须提供条目编号，不能夹带查找范围选择。")
        return self


def _lock(session, tenant_id, session_id):
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"work-state:{tenant_id}:{session_id}"},
    )


def latest(session, session_id):
    return session.scalar(
        select(AgentWorkState)
        .where(AgentWorkState.session_id == session_id)
        .order_by(AgentWorkState.revision.desc())
        .limit(1)
    )


def empty():
    return {
        "root_goal": None,
        "current_goal": None,
        "constraints": [],
        "exclusions": [],
        "removed_constraints": [],
        "focus_objects": [],
        "completed": [],
        "completed_count": 0,
        "candidates": [],
        "unfinished": [],
        "questions": [],
        "skills": [],
        "citations": [],
        "search_preferences": search_defaults(),
    }


def validate_constraints(proposals, goals, removed):
    """No paraphrase, model facts or another conversation can become a user constraint."""
    accepted, rejected = [], []
    if not isinstance(proposals, list) or len(proposals) > 50:
        return [], [{"reason": "invalid_constraint_proposals"}]
    for proposal in proposals:
        if not isinstance(proposal, dict) or set(proposal) != {"run_id", "text"}:
            rejected.append({"reason": "invalid_constraint_shape"})
            continue
        origin, quote = proposal["run_id"], proposal["text"]
        if (
            not isinstance(origin, str)
            or origin not in goals
            or not isinstance(quote, str)
            or not quote.strip()
            or quote not in user_goal(goals[origin])
        ):
            rejected.append({"reason": "not_verbatim_user_fragment"})
            continue
        identity = str(uuid5(NAMESPACE_URL, f"pdos-constraint:{origin}:{quote}"))
        if identity in removed:
            rejected.append({"reason": "removed_by_user", "id": identity})
            continue
        accepted.append({"id": identity, "run_id": origin, "text": quote})
    return accepted, rejected


def _append(session, run, body, *, origin, key, fingerprint, revision):
    row = AgentWorkState(
        id=uuid4(),
        tenant_id=run.tenant_id,
        owner_id=run.requester_id,
        session_id=run.session_id,
        run_id=run.id if origin == "run" else None,
        origin=origin,
        request_key=key,
        request_sha256=fingerprint,
        revision=revision,
        body=body,
    )
    session.add(row)
    session.flush()
    return row


def record_finish(session, run, result):
    """Same transaction as terminal result, serialized with human edits and safe on replay."""
    # Cancellation/failure may already be staged on the ORM row. Do not flush a
    # terminal state before its memory metadata is ready: terminal Runs are immutable.
    with session.no_autoflush:
        return _record_finish(session, run, result)


def _record_finish(session, run, result):
    if run.trigger != "conversation":
        return result  # Service automations never edit human conversation memory.
    _lock(session, run.tenant_id, run.session_id)
    prior = session.scalar(select(AgentWorkState).where(AgentWorkState.run_id == run.id))
    value = deepcopy(result)
    business = value.get("result")
    proposals = business.pop("context_proposals", {}) if isinstance(business, dict) else {}
    if prior is not None:
        return value
    current = latest(session, run.session_id)
    body = deepcopy(current.body) if current else empty()
    # Only actual conversation goals from this session can prove a proposal.
    rows = session.execute(
        select(AgentRun.id, AgentRun.goal)
        .where(
            AgentRun.session_id == run.session_id,
            AgentRun.requester_id == run.requester_id,
            AgentRun.trigger == "conversation",
        )
        .order_by(AgentRun.created_at, AgentRun.id)
    ).all()
    goals = {str(row.id): row.goal for row in rows}
    accepted, rejected = validate_constraints(
        proposals.get("constraints", []) if isinstance(proposals, dict) else None,
        goals,
        set(body["removed_constraints"]),
    )
    by_id = {item["id"]: item for item in body["constraints"]}
    by_id.update((item["id"], item) for item in accepted)
    body["constraints"] = list(by_id.values())
    body["root_goal"] = body["root_goal"] or {
        "run_id": str(rows[0].id),
        "text": user_goal(rows[0].goal),
    }
    body["current_goal"] = {"run_id": str(run.id), "text": user_goal(run.goal)}
    focus = {
        (item["kind"], item["id"], item.get("version")): item for item in body["focus_objects"]
    }
    from pdos_next.domain.preproject.models import Proposal
    from pdos_next.domain.projects.models import Project

    models = {"category": Category, "product": Product, "proposal": Proposal, "project": Project}
    for kind in ("category", "product", "proposal", "project"):
        identity = getattr(run, f"{kind}_id", None)
        if identity:
            revision = session.scalar(
                select(models[kind].revision).where(models[kind].id == identity)
            )
            if revision is None:
                raise DomainError("FORBIDDEN_SCOPE", "焦点对象已不可读，不能追加工作状态。")
            for key in list(focus):
                if key[:2] == (kind, str(identity)):
                    del focus[key]
            focus[(kind, str(identity), revision)] = {
                "kind": kind,
                "id": str(identity),
                "version": revision,
                "run_id": str(run.id),
            }
    for ref in run.read_sources:
        key = ("artifact", ref["artifact_id"], ref["expected_revision"])
        focus[key] = {"kind": key[0], "id": key[1], "version": key[2], "run_id": str(run.id)}
    body["focus_objects"] = list(focus.values())
    # These are references to persisted host receipts, never claims from result_json.
    receipts = session.execute(
        select(Receipt.id, Receipt.operation)
        .where(
            Receipt.agent_run_id == run.id,
        )
        .order_by(Receipt.created_at, Receipt.id)
    ).all()
    existing = {item["receipt_id"] for item in body["completed"]}
    added = [
        {"receipt_id": str(row.id), "operation": row.operation, "run_id": str(run.id)}
        for row in receipts
        if str(row.id) not in existing
    ]
    body["completed_count"] += len(added)
    body["completed"] = (body["completed"] + added)[-COMPLETED_LIMIT:]
    events = session.execute(
        select(AgentEvent.id, AgentEvent.body)
        .where(
            AgentEvent.run_id == run.id,
            AgentEvent.body["type"].astext.in_(
                ["domain_candidate", "category_candidate", "skill_loaded"]
            ),
        )
        .order_by(AgentEvent.sequence)
    ).all()
    for identity, event in events:
        if event["type"] == "skill_loaded":
            if event.get("isolation", "main") != "main":
                continue
            skill = {"key": event["key"], "version": event["version"], "run_id": str(run.id)}
            body["skills"] = [item for item in body["skills"] if item["key"] != skill["key"]]
            body["skills"].append(skill)
        else:
            body["candidates"].append({"event_id": str(identity), "run_id": str(run.id)})
    # Only the latest model's unfinished/questions survive, explicitly non-factual.
    body["unfinished"] = value.get("unfinished", body["unfinished"])
    body["questions"] = value.get("questions", body["questions"])
    if run.state in {"queued", "running", "waiting_input", "completed", "partial"}:
        from pdos_next.enterprise_search import assistant_ledger

        from .execution import scope_for_run

        citations = {item["citation_id"]: item for item in body["citations"]}
        for cid, item in assistant_ledger.issued(session, scope_for_run(run)).items():
            origin_cid = item.get("origin_citation_id", cid)
            citations[origin_cid] = {
                "run_id": item.get("origin_run_id", str(run.id)),
                "citation_id": origin_cid,
            }
        body["citations"] = list(citations.values())
    run.versions = {
        **run.versions,
        "work_state_proposals": {
            "accepted": [item["id"] for item in accepted],
            "rejected": rejected,
        },
    }
    _append(
        session,
        run,
        body,
        origin="run",
        key=run.id,
        fingerprint=digest(value),
        revision=(current.revision if current else 0) + 1,
    )
    return value


def _project(session, ctx, row, *, current_run=None):
    """Resolve source access before exposing identifiers, counts or model-derived notes."""
    body = deepcopy(row.body) if row else empty()
    body.setdefault("search_preferences", search_defaults())
    hidden, focus = 0, []
    from pdos_next.domain.preproject.access import proposal
    from pdos_next.service import require_access, source_for

    from .project_scope import require_project

    for item in body["focus_objects"]:
        try:
            kind, identity = item["kind"], UUID(item["id"])
            if kind == "artifact":
                # The originating run supplies the category/product, never a model proposal.
                origin = session.get(AgentRun, UUID(item["run_id"]))
                if origin is None or origin.reverted_at:
                    raise DomainError("FORBIDDEN_SCOPE", "原运行已不可读。")
                source = source_for(
                    session,
                    replace(ctx, category_id=origin.category_id),
                    origin.product_id,
                    identity,
                )
                item["title"] = source.title
                if source.revision != item["version"]:
                    item["note"] = "资料已更新，使用前须重读"
            elif kind == "proposal":
                proposal(session, ctx, identity)
            elif kind == "project":
                origin = session.get(AgentRun, UUID(item["run_id"]))
                if origin is None or origin.reverted_at:
                    raise DomainError("FORBIDDEN_SCOPE", "原运行已不可读。")
                require_project(session, ctx, identity, origin.product_id)
            elif kind == "product":
                require_access(session, ctx, identity, write=False)
            elif kind == "category":
                require_access(session, replace(ctx, category_id=identity), None, write=False)
            focus.append(item)
        except DomainError as error:
            if error.code in {"FORBIDDEN_SCOPE", "NOT_FOUND", "SOURCE_UNAVAILABLE"}:
                hidden += 1
            elif error.code in {"SOURCE_STALE", "VERSION_CONFLICT"}:
                focus.append({**item, "note": "资料已更新，使用前须重读"})
            else:
                raise
    body["focus_objects"] = focus
    visible_sources = {item["id"] for item in focus if item["kind"] == "artifact"}
    ids = [UUID(item["receipt_id"]) for item in body["completed"]]
    readable = (
        set(session.scalars(select(Receipt.id).where(Receipt.id.in_(ids))).all()) if ids else set()
    )
    body["completed"] = [item for item in body["completed"] if UUID(item["receipt_id"]) in readable]
    directory = {"tool": "assistant.citations.read", "has_more": False, "next_cursor": None}
    if body["citations"]:
        from pdos_next.enterprise_search.assistant_inheritance import saved

        origin = session.get(AgentRun, UUID(body["current_goal"]["run_id"]))
        try:
            if origin is None or origin.requester_id != ctx.requester_id:
                raise DomainError("FORBIDDEN_SCOPE", "原引用已不可读。")
            body["citations"], missing_citations, directory, visible_citations = saved(
                session, origin, body["citations"]
            )
            visible_sources.update(visible_citations)
            hidden += int(missing_citations)
        except DomainError as error:
            if error.code not in {"FORBIDDEN_SCOPE", "NOT_FOUND", "SOURCE_UNAVAILABLE"}:
                raise
            hidden += 1
    body["exclusions"] = [item for item in body["exclusions"] if item["id"] in visible_sources]
    if hidden:
        # Notes may have depended on a now-unreadable source; preserve literal human text only.
        for key in ("candidates", "unfinished", "questions", "citations"):
            body[key] = []
    public = {key: val for key, val in body.items() if key != "removed_constraints"}
    public["citation_directory"] = directory
    origin = current_run or (
        session.get(AgentRun, UUID(body["current_goal"]["run_id"]))
        if body["current_goal"] else None
    )
    context = {"kind": "personal", "label": "本人当前可读范围", "scoped": False}
    proposal_id = origin.proposal_id if origin else None
    if origin is not None and current_run is None and not origin.project_id:
        from .session_bindings import current_proposal_id

        conversation = session.get(AgentSession, origin.session_id)
        if conversation is not None:
            proposal_id = current_proposal_id(session, conversation)
    if origin is not None and origin.project_id:
        project = require_project(session, replace(ctx, category_id=origin.category_id),
                                  origin.project_id, origin.product_id)
        context = {"kind": "project", "label": project.name, "scoped": True}
    elif origin is not None and proposal_id:
        target = proposal(session, replace(ctx, category_id=origin.category_id), proposal_id)
        context = {"kind": "proposal", "label": target.title, "scoped": True}
    elif origin is not None and origin.category_id:
        context = {"kind": "category", "label": "当前品类的可读资料", "scoped": False}
    public["search_context"] = context
    public["notes"] = ["部分资料已无权读取或已撤回，相关工作记录已隐藏。"] if hidden else []
    # Completed history is compacted; constraints and focus references remain exact.
    tokens = estimate_tokens(json.dumps(public, ensure_ascii=False))
    return {
        "version": "agent-work-state/v1",
        "revision": row.revision if row else 0,
        "session_id": str(row.session_id) if row else None,
        **public,
        "estimated_tokens": tokens,
        "context_incomplete": tokens > STATE_TOKENS,
        "missing": ["工作状态超过预算，请在本次携带中清理约束或缩小范围。"]
        if tokens > STATE_TOKENS
        else [],
    }


def frozen(session, run, ctx):
    """The exact state version used by a run is immutable, including after skill.load."""
    value = run.versions.get("work_state")
    if value is None:
        row = latest(session, run.session_id)
        if row is not None and not _covered(session, run, row.body):
            value = _project(session, ctx, None, current_run=run)
            # These are the owner's source-independent UI choices. Dropping
            # old private context must never reset "current only" to a wider default.
            value["search_preferences"] = SearchPreferences.model_validate(
                row.body.get("search_preferences", {})
            ).model_dump(mode="json")
            value["notes"] = ["旧工作状态未发送：当前运行未绑定其全部来源与出站分类。"]
            value["context_incomplete"] = True
            value["missing"] = ["请从原工作继续，或新建会话明确选择资料。"]
        else:
            value = _project(session, ctx, row, current_run=run)
        if run.continued_from_id is not None:
            from pdos_next.enterprise_search.assistant_inheritance import page
            from pdos_next.enterprise_search.assistant_schemas import CitationsInput

            inherited = page(
                session, run, CitationsInput(),
                excluded={item["id"] for item in value["exclusions"]},
            )
            value["citations"] = inherited["items"]
            value["citation_directory"] = {
                "tool": "assistant.citations.read",
                "has_more": inherited["has_more"], "next_cursor": inherited["next_cursor"],
            }
        else:
            # A reused session ID does not establish a continuation lineage.
            value["citations"] = []
            value["citation_directory"] = {
                "tool": "assistant.citations.read", "has_more": False, "next_cursor": None
            }
        value["current_goal"] = {"run_id": str(run.id), "text": user_goal(run.goal)}
        if value["root_goal"] is None:
            value["root_goal"] = value["current_goal"]
        value["session_id"] = str(run.session_id)
        if "requested_search_preferences" in run.versions:
            value["search_preferences"] = SearchPreferences.model_validate(
                run.versions["requested_search_preferences"]
            ).model_dump(mode="json")
        value["estimated_tokens"] = estimate_tokens(json.dumps(value, ensure_ascii=False))
        over = value["estimated_tokens"] > STATE_TOKENS
        value["context_incomplete"] = value["context_incomplete"] or over
        value["missing"] += ["工作状态超过预算，请在本次携带中清理约束或缩小范围。"] if over else []
        run.versions = {**run.versions, "work_state": value, "work_state_digest": digest(value)}
    return value


def _covered(session, run, body):
    """A session ID alone must not import another run's private/customer classification."""
    origins = {
        item["run_id"]
        for key in ("constraints", "focus_objects", "completed", "candidates", "citations")
        for item in body[key]
    }
    origins.update(body[key]["run_id"] for key in ("root_goal", "current_goal") if body[key])
    rows = session.execute(
        select(
            AgentRun.id,
            AgentRun.private_context,
            AgentRun.data_categories,
            AgentRun.customer_identities,
        ).where(
            AgentRun.id.in_([UUID(identity) for identity in origins]),
            AgentRun.session_id == run.session_id,
        )
    ).all()
    if len(rows) != len(origins) or any(
        row.private_context
        and not run.private_context
        or set(row.data_categories) - set(run.data_categories)
        or set(row.customer_identities) - set(run.customer_identities)
        for row in rows
    ):
        return False
    carried = {
        (item["id"], item["version"])
        for item in body["focus_objects"]
        if item["kind"] == "artifact"
    }
    bound = {(ref["artifact_id"], ref["expected_revision"]) for ref in run.read_sources}
    return carried <= bound


def check_frozen(session, run, ctx):
    value = run.versions.get("work_state")
    if value and value.get("citations"):
        from pdos_next.enterprise_search.assistant_inheritance import recheck

        recheck(session, run, value["citations"])
    if not value or not value["revision"]:
        return
    row = session.scalar(
        select(AgentWorkState).where(
            AgentWorkState.session_id == run.session_id,
            AgentWorkState.revision == value["revision"],
        )
    )
    if row is None:
        raise DomainError("CONVERSATION_HISTORY_REVOKED", "携带的工作状态已不可读。")
    current = _project(session, ctx, row, current_run=run)
    visible = {(item["kind"], item["id"], item["version"]) for item in current["focus_objects"]}
    previous = {(item["kind"], item["id"], item["version"]) for item in value["focus_objects"]}
    if previous - visible:
        raise DomainError("CONVERSATION_HISTORY_REVOKED", "工作状态引用的资料已无权读取或已撤回。")


def change(session, ctx, session_id, data):
    _human(session, ctx, None)
    _target(session, ctx, session_id, None)
    feedback_run = None
    if data.action == "exclude_source":
        # finish locks Run before this advisory lock. Event append/FK locking
        # must follow that same order, even when the current goal changes.
        before = latest(session, session_id)
        if before is not None:
            feedback_run = session.scalar(select(AgentRun).where(
                AgentRun.id == UUID(before.body["current_goal"]["run_id"]),
                AgentRun.session_id == session_id,
                AgentRun.requester_id == ctx.requester_id,
            ).with_for_update())
            if feedback_run is None:
                raise DomainError("FORBIDDEN_SCOPE", "原运行已不可读。")
    _lock(session, ctx.tenant_id, session_id)
    fingerprint = digest(data.model_dump(mode="json", exclude={"request_key"}, exclude_none=True))
    replay = session.scalar(
        select(AgentWorkState).where(
            AgentWorkState.session_id == session_id,
            AgentWorkState.request_key == data.request_key,
        )
    )
    if replay:
        if replay.request_sha256 != fingerprint:
            raise DomainError("DUPLICATE_INTENT_CONFLICT", "请求编号对应不同的携带修改。")
        return _project(session, ctx, replay)
    current = latest(session, session_id)
    if current is None or current.revision != data.expected_revision:
        raise DomainError("VERSION_CONFLICT", "本次携带已变化，请刷新后修改。")
    if data.action == "exclude_source" and (
        feedback_run is None or str(feedback_run.id) != current.body["current_goal"]["run_id"]
    ):
        raise DomainError("VERSION_CONFLICT", "当前工作已变化，请刷新后修改。")
    body = deepcopy(current.body)
    identity = str(data.item_id)
    key = "constraints" if data.action == "remove_constraint" else "exclusions"
    if data.action == "set_search_scope":
        body["search_preferences"] = data.search_preferences.model_dump(mode="json")
    elif data.action == "exclude_source":
        visible_state = _project(session, ctx, current)
        citation = next(
            (item for item in visible_state["citations"] if item["citation_id"] == identity),
            None,
        )
        source = next(
            (
                item
                for item in body["focus_objects"]
                if item["kind"] == "artifact" and item["id"] == identity
            ),
            None,
        )
        # Select only an already carried, currently readable source. No scope expansion.
        visible = visible_state["focus_objects"]
        if citation is None and (source is None or not any(
            item["kind"] == "artifact"
            and item["id"] == identity
            and item["version"] == source["version"]
            for item in visible
        )):
            raise DomainError("FORBIDDEN_SCOPE", "只能排除当前已携带且可读的资料。")
        item = {
            "id": identity, "kind": "citation" if citation else "artifact",
            "reason": "用户标记不相关",
        }
        body["exclusions"] = [old for old in body["exclusions"] if old["id"] != identity] + [item]
    else:
        if not any(item["id"] == identity for item in body[key]):
            raise DomainError("NOT_FOUND", "这条携带记录已不存在。", 404)
        body[key] = [item for item in body[key] if item["id"] != identity]
        if data.action == "remove_constraint":
            body["removed_constraints"] = sorted(set(body["removed_constraints"]) | {identity})
    run = session.get(AgentRun, UUID(body["current_goal"]["run_id"]))
    if run is None:
        raise DomainError("FORBIDDEN_SCOPE", "原运行已不可读。")
    row = _append(
        session,
        run,
        body,
        origin="human",
        key=data.request_key,
        fingerprint=fingerprint,
        revision=current.revision + 1,
    )
    if data.action == "exclude_source":
        from .retrieval_feedback import record

        record(session, ctx, feedback_run, row, identity)
    return _project(session, ctx, row)


def router(*, transaction, context_dependency):
    result = APIRouter()

    @result.get("/v1/personal/agent-sessions/{session_id}/work-state")
    @result.get("/v1/categories/{category_id}/agent-sessions/{session_id}/work-state")
    def reading(session_id: UUID, ctx=context_dependency):
        with transaction(ctx, read_snapshot=True) as session:
            _human(session, ctx, None)
            _target(session, ctx, session_id, None)
            return _project(session, ctx, latest(session, session_id))

    @result.post("/v1/personal/agent-sessions/{session_id}/work-state")
    @result.post("/v1/categories/{category_id}/agent-sessions/{session_id}/work-state")
    def changing(session_id: UUID, data: ChangeInput, ctx=context_dependency):
        with transaction(ctx) as session:
            return change(session, ctx, session_id, data)

    return result
