"""Whole-output P31 projection from native ledger; never trust model taint/recipient JSON."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select

from pdos_next.agent_kernel.execution import scope_for_run
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.database import tenant_session
from pdos_next.enterprise_search import assistant_ledger
from pdos_next.enterprise_search.assistant_answer import checked_sources, stored_answer
from pdos_next.enterprise_search.assistant_sources import current
from pdos_next.errors import DomainError
from pdos_next.models import Principal

from .models import Binding

# These native reads have a complete frozen enterprise citation/dependency ledger.
# An unsupported read does not make the whole output safe merely by omitting its citation.
COVERED = assistant_ledger.TOOLS | {
    "model",
    "skill.load",
    "result.read",
    "assistant.comparison.read",
    "assistant.passage.read",
}


@dataclass(frozen=True)
class Answer:
    body: str = field(repr=False)
    citations: tuple[dict, ...] = field(repr=False)
    footprint: dict = field(repr=False)
    data_categories: tuple[str, ...]
    withheld_reason: str | None = None


def run_link(base_url, run_id):
    url = urlsplit(base_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.netloc
        or url.query
        or url.fragment
        or url.username
        or url.password
    ):
        raise DomainError("SOURCE_UNAVAILABLE", "PDOS 本地继续地址尚未正确登记。")
    return base_url.rstrip("/") + "/dingtalk/runs/" + str(UUID(str(run_id)))


def whole_answer(
    *, output, footprint, run_categories, customer_identities, tools, has_uncovered_inputs=False
):
    """Pure policy on SERVER-validated inputs; not an external payload validator."""
    customer = bool(customer_identities) or bool(
        set(run_categories) & {"customer", "customer_original"}
    )
    customer |= any(item.get("customer_original") is True for item in footprint.values())
    reason = "customer_derived" if customer else None
    if reason is None and any(
        item.get("_dingtalk_current") is False for item in footprint.values()
    ):
        reason = "source_changed"
    if reason is None and (
        has_uncovered_inputs
        or set(tools) - COVERED
        or not footprint
        or any("customer_original" not in row for row in footprint.values())
    ):
        reason = "dependency_unverified"
    if reason:
        return Answer("这次结果请在 PDOS 登录后查看。", (), {}, ("internal",), reason)
    assistant = output.get("result", {}).get("assistant", {})
    citations = tuple(
        row for row in assistant.get("sources", []) if row.get("citation_id") in footprint
    )
    categories = set(run_categories) | {"internal"}
    body = output.get("summary", "")
    if assistant.get("notice"):
        body += "\n\n" + assistant["notice"]
    return Answer(body, citations, footprint, tuple(sorted(categories)))


def owner_answer(session, run):
    if run.reverted_at or run.state not in {"completed", "partial"}:
        return Answer(
            "这次工作尚未形成可发送的答案，请在 PDOS 继续。", (), {}, ("internal",), "not_completed"
        )
    # Check ALL carried/current ledger sources, not just the model-selected quotes.
    issued, _historical = assistant_ledger.carried(session, scope_for_run(run))
    actual = checked_sources(session, run)
    # Rechecks require the original signed IDs/hash/revision/dependency basis,
    # not the ORM rows (whose UUID types/current revisions are a different shape).
    footprint = {
        cid: {
            **issued[cid],
            "customer_original": row["customer_original"],
            "private": row["private"],
            "_dingtalk_current": not row.get("updated") and row.get("fixed_body_available", True),
        }
        for cid, row in actual.items()
    }
    output = stored_answer(session, run)
    calls = list(
        session.scalars(
            select(AgentToolCall.tool).where(
                AgentToolCall.run_id == run.id,
                AgentToolCall.state == "completed",
            )
        )
    )
    return whole_answer(
        output=output,
        footprint=footprint,
        run_categories=run.data_categories,
        customer_identities=run.customer_identities,
        tools=calls,
        has_uncovered_inputs=bool(
            run.read_sources or run.versions.get("conversation_memory", {}).get("turns")
        ),
    )


def group_citations(engine, ctx, app, members, answer):
    """Ordinary member READ of the owner's already-validated fixed footprint, metadata only."""
    if (
        answer.withheld_reason
        or not answer.citations
        or not members.complete
        or not members.external_user_ids
        or members.application_id != app.id
    ):
        return False
    with tenant_session(
        engine,
        ctx.tenant_id,
        actor_id=app.service_principal_id,
        requester_id=app.service_principal_id,
        read_snapshot=True,
    ) as session:
        # This private app metadata lookup gives no member any other person's Run or sources.
        bindings = list(
            session.scalars(
                select(Binding).where(
                    Binding.application_id == app.id,
                    Binding.active.is_(True),
                    Binding.external_user_id.in_(members.external_user_ids),
                )
            )
        )
        by_external = {row.external_user_id: row.owner_id for row in bindings}
    if set(by_external) != set(members.external_user_ids):
        return False
    for owner in set(by_external.values()):
        with tenant_session(
            engine, ctx.tenant_id, actor_id=owner, requester_id=owner, read_snapshot=True
        ) as session:
            person = session.get(Principal, owner)
            if not person or not person.active or person.kind != "human":
                return False
            actual, missing = current(session, answer.footprint)
            # Fixed hash/revision, dependency scan and current audience are all rechecked.
            if missing or set(actual) != set(answer.footprint):
                return False
    return True


def payload(
    *,
    phase,
    message,
    binding,
    answer,
    link,
    include_citations=False,
    members=None,
    citations_allowed=False,
):
    if phase == "received":
        return {
            "target_kind": "direct",
            "target_id": binding.external_user_id,
            "text": "收到，正在查。",
            "url": link,
        }
    if phase == "group_notice":
        return {
            "target_kind": "group",
            "target_id": message.conversation_id,
            "text": "答案已私发。",
            "url": link,
        }
    group = phase == "share"
    value = {
        "target_kind": "group" if group else "direct",
        "target_id": message.conversation_id if group else binding.external_user_id,
        "text": answer.body,
        "url": link,
    }
    if group and include_citations and citations_allowed and not answer.withheld_reason:
        value["citations"] = [
            {
                key: row[key]
                for key in (
                    "title",
                    "quote",
                    "source_type",
                    "source_id",
                    "source_revision",
                    "content_hash",
                    "object_url",
                )
                if key in row
            }
            for row in answer.citations
        ]
        value["membership_version"] = members.version
    return value
