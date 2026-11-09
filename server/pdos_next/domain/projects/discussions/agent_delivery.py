"""Delivering 小Pai's reply into a shared thread (`discussion.ai_reply.deliver`, P54).

Runs only in the worker, after the Run has ended, as a deterministic node of the
registered 小Pai graph (no model, no gateway). The model never calls it.

1. As the requester, rebuild the Run's frozen read manifest: every source it read,
   including carried history and project facts (P32's manifest, P62 第 3 项).
2. As each person who can see the thread now, re-check every one of those sources
   under that person's own RLS. One person without access to one source is enough
   to keep the reply private (P34-4: the whole reply, no partial redaction).
3. As 小Pai for the requester, call `discussion_agent_deliver`: the body is the Run's
   own summary read in SQL; when not covered only a fixed notice reaches the thread.

The same check (`audience_check`) is the shared implementation the DingTalk group
path is to adopt (P62 第 3 项, registered as D392).
"""

import json
from datetime import timedelta
from uuid import UUID

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from pdos_next.core.schema_base import StrictModel


TERMINAL = frozenset({"completed", "partial", "failed", "cancelled"})
CUSTOMER = frozenset({"customer", "customer_original"})
SOURCE_GROUPS = ("dependencies", "citations", "projects", "mcp")


class ReplyReference(StrictModel):
    tenant_id: UUID
    request_id: UUID


def _manifest_parts(manifest):
    """Split one manifest so a refusal names the kind of source, never the source."""
    parts = {}
    for item in manifest.get("dependencies", []):
        if item.get("kind") == "run":
            continue
        parts.setdefault(item["kind"], {"dependencies": [], "citations": []})
        parts[item["kind"]]["dependencies"].append(item)
    if manifest.get("citations"):
        parts["citation"] = {"dependencies": [], "citations": manifest["citations"]}
    if manifest.get("projects"):
        parts["project"] = {"dependencies": [], "citations": [], "projects": manifest["projects"]}
    if manifest.get("mcp"):
        parts["mcp"] = {"dependencies": [], "citations": [], "mcp": manifest["mcp"]}
    return parts


def audience_check(engine, ctx, run, manifest, audience):
    """Whole-run check of every read source against every audience member (P34-4, P62).

    Returns (covered, receipt). The receipt holds counts and source kinds only.
    """
    from pdos_next.agent.kernel.conversation_acl import classify
    from pdos_next.core.database import tenant_session

    customer = bool(run.customer_identities) or bool(set(run.data_categories or ()) & CUSTOMER)
    receipt = {
        "checked_at": None,
        "audience_size": len(audience),
        "uncovered_members": 0,
        "uncovered_source_kinds": [],
        "customer_derived": customer,
        "unverified_tools": sorted(manifest.get("unverified", [])) if manifest else [],
    }
    if manifest is None or manifest.get("unavailable") or manifest.get("unverified"):
        return False, {**receipt, "result": "dependency_unverified"}
    parts = _manifest_parts(manifest)
    hidden_kinds, uncovered = set(), 0
    for person in audience:
        if person == run.requester_id:
            continue  # The requester read these sources in this very Run.
        if not parts:
            continue
        with tenant_session(
            engine,
            ctx.tenant_id,
            actor_id=person,
            requester_id=person,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            states = classify(s, parts)
        missing = {kind for kind, state in states.items() if state == "hidden"}
        if missing:
            uncovered += 1
            hidden_kinds |= missing
    receipt.update(uncovered_members=uncovered, uncovered_source_kinds=sorted(hidden_kinds))
    return uncovered == 0, {**receipt, "result": "covered" if uncovered == 0 else "uncovered"}


def _reference(dispatch_engine, tenant_id, request_id):
    from sqlalchemy import text

    from pdos_next.core.database import tenant_session

    with tenant_session(dispatch_engine, tenant_id) as s:
        return (
            s.execute(
                text("SELECT * FROM discussion_agent_reference(:t, :r)"),
                {"t": tenant_id, "r": request_id},
            )
            .mappings()
            .one_or_none()
        )


def deliver(engine, dispatch_engine, tenant_id, request_id):
    """One idempotent delivery attempt for a request whose Run has ended."""
    from sqlalchemy import text

    from pdos_next.agent.kernel.conversation import lineage
    from pdos_next.agent.kernel.conversation_acl import manifests
    from pdos_next.agent.kernel.models import AgentRun
    from pdos_next.core.clock import now
    from pdos_next.core.database import tenant_session
    from pdos_next.core.service import Context
    from pdos_next.errors import DomainError

    from .models import DiscussionAgentRequest

    ref = _reference(dispatch_engine, tenant_id, request_id)
    if ref is None:
        return {"state": "missing"}
    if ref["delivery"] != "pending":
        return {"state": ref["delivery"]}
    requester = ref["requester_id"]
    ctx = Context(tenant_id, requester, requester, category_id=ref["category_id"])
    manifest, run, thread_id, private_only = None, None, None, False
    with tenant_session(
        engine,
        tenant_id,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
        read_snapshot=True,
    ) as s:
        row = s.get(DiscussionAgentRequest, request_id)
        run = s.get(AgentRun, row.run_id) if row is not None else None
        if row is not None:
            thread_id, private_only = row.thread_id, row.private_only
        if run is not None and run.reverted_at is None and run.state not in TERMINAL:
            return {"state": "waiting", "run_state": run.state}
        if run is not None and run.reverted_at is None and run.state in {"completed", "partial"}:
            try:
                ancestors = [run, *lineage(s, run)]
                manifest = manifests(s, [run], ancestors=ancestors, consumer=run)[str(run.id)]
            except (DomainError, KeyError, TypeError, ValueError):
                manifest = None
            # Keep plain copies; the ORM rows do not outlive this transaction.
            run = type("RunFacts", (), {
                "requester_id": run.requester_id,
                "customer_identities": list(run.customer_identities or ()),
                "data_categories": list(run.data_categories or ()),
            })()
        else:
            run = None
    verdict, reason, receipt, frozen = "none", "requester_no_access", {}, None
    if run is not None and thread_id is not None:
        with tenant_session(
            engine,
            tenant_id,
            actor_id=ref["writer_id"],
            requester_id=ctx.requester_id,
            category_id=ctx.category_id,
            read_snapshot=True,
        ) as s:
            audience = list(
                s.scalars(
                    text("SELECT discussion_thread_audience(:t, :thread)"),
                    {"t": tenant_id, "thread": thread_id},
                )
            )
        ok, receipt = audience_check(engine, ctx, run, manifest, audience)
        if manifest is not None:
            frozen = {
                key: manifest.get(key)
                for key in ("version", "dependencies", "citations", "projects", "mcp",
                            "unverified", "unavailable")
                if key in manifest
            }
            frozen["dependencies"] = [
                item for item in frozen.get("dependencies", []) if item.get("kind") != "run"
            ]
        if private_only:
            verdict, reason = "private", "private_only"
        elif ok:
            verdict, reason = "public", None
        else:
            verdict = "private"
            reason = (
                "dependency_unverified"
                if receipt.get("result") == "dependency_unverified"
                else "audience_not_covered"
            )
    elif thread_id is not None:
        # Ended without a reply (failed, cancelled or reverted): SQL records why.
        verdict, reason = "none", "run_failed"
    receipt["checked_at"] = now().isoformat()
    with tenant_session(
        engine,
        tenant_id,
        actor_id=ref["writer_id"],
        requester_id=ctx.requester_id,
        category_id=ctx.category_id,
    ) as s:
        message = s.scalar(
            text(
                "SELECT discussion_agent_deliver(:t, :r, :verdict, :reason, "
                "CAST(:receipt AS jsonb), CAST(:manifest AS jsonb))"
            ),
            {
                "t": tenant_id,
                "r": request_id,
                "verdict": verdict,
                "reason": reason,
                "receipt": json.dumps(receipt, ensure_ascii=False, default=str),
                "manifest": json.dumps(frozen, ensure_ascii=False, default=str)
                if frozen is not None
                else None,
            },
        )
    return {
        "state": "settled",
        "verdict": verdict,
        "message_id": str(message) if message else None,
    }


def execute(engine, dispatch_engine, reference):
    """The delivery as a deterministic node of the registered 小Pai graph (no model)."""
    from typing import TypedDict

    from langgraph.graph import END, START, StateGraph
    from pdos_agent_runtime.graph import registered_graph_context

    ref = ReplyReference.model_validate(reference)

    class State(TypedDict, total=False):
        reference: dict
        delivery: dict

    graph = StateGraph(State)
    graph.add_node(
        "deliver_discussion_reply",
        lambda _: {"delivery": deliver(engine, dispatch_engine, ref.tenant_id, ref.request_id)},
    )
    graph.add_edge(START, "deliver_discussion_reply")
    graph.add_edge("deliver_discussion_reply", END)
    compiled = graph.compile(name="xiaopai")
    with registered_graph_context("xiaopai"):
        return compiled.invoke({"reference": reference})["delivery"]


@workflow.defn
class DiscussionAgentReply:
    @workflow.run
    async def run(self, reference: dict):
        ReplyReference.model_validate(reference)
        return await workflow.execute_activity(
            "deliver_discussion_agent_reply",
            reference,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1), maximum_attempts=20),
        )


class ReplyActivities:
    def __init__(self, engine, dispatch_engine):
        self.engine, self.dispatch_engine = engine, dispatch_engine

    @activity.defn(name="deliver_discussion_agent_reply")
    def deliver(self, reference):
        return execute(self.engine, self.dispatch_engine, reference)


def workflow_id(tenant_id, request_id):
    return f"pdos-next:discussion-reply:{UUID(str(tenant_id))}:{UUID(str(request_id))}"


async def dispatch_pending(dispatch_engine, tenant_id, client, *, task_queue):
    """Worker discovery: start one delivery workflow per request whose Run has ended."""
    from sqlalchemy import text

    from pdos_next.core.database import tenant_session

    with tenant_session(dispatch_engine, tenant_id) as s:
        rows = (
            s.execute(
                text("SELECT request_id FROM discussion_agent_pending(:t, 100)"), {"t": tenant_id}
            )
            .scalars()
            .all()
        )
    started = 0
    for request_id in rows:
        try:
            await client.start_workflow(
                DiscussionAgentReply.run,
                {"tenant_id": str(tenant_id), "request_id": str(request_id)},
                id=workflow_id(tenant_id, request_id),
                task_queue=task_queue,
                # A failed delivery may be started again; a running or completed one not.
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
            started += 1
        except WorkflowAlreadyStartedError:
            continue
    return {"discovered": len(rows), "started": started}
