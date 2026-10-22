"""Classify only the actual search/URL text against the current server-bound context."""

import re
from urllib.parse import unquote
from uuid import UUID

from sqlalchemy import select

from pdos_next.agent_kernel import policy
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.domain.preproject.deidentification import normalized, strings
from pdos_next.errors import DomainError
from pdos_next.models import Product, UploadedOriginal
from pdos_next.service import Context, source_for


def compact(value):
    # A URL may encode identifiers; normalize both literal and decoded spellings.
    return re.sub(r"[\W_]+", "", normalized(unquote(unquote(value))))


def overlaps(query, value):
    """Exact scalar matches and contiguous normalized source fragments, no semantic guess."""
    query, source = query.encode("utf-8"), compact(value).encode("utf-8")
    if not query or not source:
        return False
    if source in query or query in source:
        return True
    # UTF-8 byte windows also cover short Chinese phrases; short scalar fields match in full.
    width = 12
    if min(len(query), len(source)) < width:
        return False
    pieces = {query[index : index + width] for index in range(len(query) - width + 1)}
    return any(source[index : index + width] in pieces for index in range(len(source) - width + 1))


def projected_categories(session, scope, run, text):
    from pdos_next.domain.preproject.access import proposal
    from pdos_next.domain.preproject.views import read

    query, found = compact(text), set()
    for identity in scope.customer_identities:
        if compact(identity) and compact(identity) in query:
            found.add("customer")
    ctx = Context(
        scope.tenant_id, scope.writer_id, scope.requester_id, category_id=scope.category_id
    )
    products = {scope.product_id} - {None}
    if scope.proposal_id:
        head = proposal(session, ctx, scope.proposal_id)
        if head.baseline_product_id:
            products.add(head.baseline_product_id)
        private = read(session, ctx, head.id)
        # The bound proposal view is the same ordinary view used for model context.
        private.pop("source_refs", None)
        private.pop("sources", None)
        if overlaps(query, "\n".join(strings(private, include_keys=False))):
            found.add("customer" if head.customer_identities else "internal")
    for reference in run.read_sources:
        source = source_for(
            session,
            ctx,
            UUID(reference["product_id"]) if reference.get("product_id") else None,
            UUID(reference["artifact_id"]),
            reference["expected_revision"],
        )
        if source.product_id:
            products.add(source.product_id)
        kind = "customer_original" if source.original_id else "internal"
        if overlaps(query, source.content) or overlaps(query, source.title):
            found.add(kind)
        if source.original_id:
            original = session.get(UploadedOriginal, source.original_id)
            if original is None:
                raise DomainError("SOURCE_UNAVAILABLE", "原件身份暂不可核对，未发送研究查询。")
            if compact(original.filename) and compact(original.filename) in query:
                found.add("customer_original")
    for product in session.scalars(select(Product).where(Product.id.in_(products))):
        if compact(product.name) and compact(product.name) in query:
            found.add("internal")
    # Include actual domain facts already returned in this Run, not other tenants' content.
    # Research rows remain public; their source quotes do not become private merely by being read.
    for value in session.scalars(
        select(AgentToolCall.result).where(
            AgentToolCall.run_id == run.id,
            AgentToolCall.execution_binding["kind"].astext == "read",
            AgentToolCall.execution_binding["isolation"].astext == "main",
            AgentToolCall.state == "completed",
            ~AgentToolCall.tool.like("research.%"),
        )
    ):
        if overlaps(query, "\n".join(strings(value, include_keys=False))):
            found.update(set(run.data_categories) - policy.PUBLIC or {"internal"})
    return tuple(sorted(found or {"public"}))


def decide(session, scope, run, provider, text):
    categories = projected_categories(session, scope, run, text)
    return policy.egress(session, scope, provider, data_categories=categories)
