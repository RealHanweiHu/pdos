"""Idempotent local SourceProjectors; no file parsing, model calls or business writes."""

import hashlib
from collections import Counter
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from pdos_next.agent_kernel.extract_sources import seal_for
from pdos_next.clock import now
from pdos_next.database import require_context
from pdos_next.errors import DomainError
from pdos_next.service import digest

from .models import SearchChunk, SearchCorpus, SearchSource, SearchTerm
from .schemas import SOURCE_TYPES
from .sources import prepare_read, select_sources
from .tokenizer import CHUNKER, CODE_RULE, analyze, version

CHUNK_CHARS = 1800


def _lock(session, ctx, kind, identity):
    # DF updates already serialize per tenant. Take this lock before any source
    # lock so two multi-source events cannot hold each other's next source while
    # waiting on the shared corpus counter. Locks never affect retrieval reads.
    for key in (
        f"enterprise-index:{ctx.tenant_id}",
        f"enterprise-index:{ctx.tenant_id}:{kind}:{identity}",
    ):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": key}
        )


def chunks(body, *, seal=None):
    """Exact source substrings with line/native/character offsets, including long lines."""
    if not body:
        return
    start, line, begin_line, pieces = 0, 1, 1, []
    for fragment in body.splitlines(keepends=True):
        for part in (fragment[i : i + CHUNK_CHARS] for i in range(0, len(fragment), CHUNK_CHARS)):
            if pieces and sum(map(len, pieces)) + len(part) > CHUNK_CHARS:
                value = "".join(pieces)
                yield (
                    value,
                    _locator(
                        start,
                        start + len(value),
                        begin_line,
                        begin_line + value.count("\n") - int(value.endswith("\n")),
                        seal,
                    ),
                )
                start += len(value)
                pieces, begin_line = [], line
            pieces.append(part)
        if not fragment.strip():
            value = "".join(pieces)
            if value.strip():
                yield (
                    value,
                    _locator(
                        start,
                        start + len(value),
                        begin_line,
                        begin_line + value.count("\n") - int(value.endswith("\n")),
                        seal,
                    ),
                )
            start += len(value)
            pieces, begin_line = [], line + 1
        line += 1
    if pieces:
        value = "".join(pieces)
        if value.strip():
            yield value, _locator(start, start + len(value), begin_line, line - 1, seal)


def _locator(start, end, first, last, seal):
    native = []
    if seal:
        from pdos_next.agent_kernel.extract_pages import locator_text

        native = list(
            dict.fromkeys(
                locator_text(entry.location)
                for entry in seal.locator_map
                if entry.derived_line_start <= last and entry.derived_line_end >= first
            )
        )
    return {
        "char_start": start,
        "char_end": end,
        "line_start": first,
        "line_end": last,
        "native": native or [f"line:{first}"],
    }


def _statistics(session, tenant_id, old, new):
    """Per-tenant DF deltas; row locks serialize concurrent independent source batches."""
    corpus = insert(SearchCorpus).values(tenant_id=tenant_id, chunk_count=0, token_count=0)
    session.execute(corpus.on_conflict_do_nothing())
    session.execute(
        text("""UPDATE enterprise_search_corpus SET
        chunk_count=chunk_count+:chunks, token_count=token_count+:tokens
        WHERE tenant_id=:tenant"""),
        {
            "tenant": tenant_id,
            "chunks": len(new) - len(old),
            "tokens": sum(row["token_count"] for row in new) - sum(row.token_count for row in old),
        },
    )
    delta = Counter()
    for row in old:
        delta.subtract(set(row.term_counts) | set(row.title_counts))
    for row in new:
        delta.update(set(row["term_counts"]) | set(row["title_counts"]))
    for term in sorted(delta):
        if not delta[term]:
            continue
        session.execute(
            insert(SearchTerm)
            .values(
                tenant_id=tenant_id,
                term=term,
                document_count=0,
            )
            .on_conflict_do_nothing()
        )
        session.execute(
            text("""UPDATE enterprise_search_terms SET document_count=document_count+:delta
            WHERE tenant_id=:tenant AND term=:term"""),
            {"tenant": tenant_id, "term": term, "delta": delta[term]},
        )


def project(
    session,
    ctx,
    source_type,
    source_id,
    *,
    event_id=None,
    expected_revision=1,
    force=False,
    expected_source=None,
    repair_derived=False,
):
    require_context(session, ctx)
    if source_type not in SOURCE_TYPES:
        raise DomainError("INVALID_PAYLOAD", "来源类型尚无登记的投影器。", 422)
    prepare_read(session, {source_type})
    _lock(session, ctx, source_type, source_id)
    previous = session.scalar(
        select(SearchSource).where(
            SearchSource.tenant_id == ctx.tenant_id,
            SearchSource.source_type == source_type,
            SearchSource.source_id == source_id,
        )
    )
    source = (
        session.execute(
            select_sources(
                source_type=source_type,
                source_id=source_id,
                include_body=True,
            )
        )
        .mappings()
        .one_or_none()
    )
    if expected_source is not None:
        if source is None:
            raise DomainError("SOURCE_UNAVAILABLE", "固定重建批次的来源已不可读取。")
        if (
            source["category_id"] != ctx.category_id
            or (source["source_revision"], source["content_hash"]) != expected_source
        ):
            raise DomainError("SOURCE_STALE", "固定重建批次的来源已变化，请另起新批次。")
    old = list(
        session.scalars(
            select(SearchChunk).where(
                SearchChunk.tenant_id == ctx.tenant_id,
                SearchChunk.source_type == source_type,
                SearchChunk.source_id == source_id,
            )
        )
    )
    seal, parser = None, "structured-source/v1"
    if source and source_type == "artifact":
        seal, _ = seal_for(session, ctx, source["product_id"], source_id, source["source_revision"])
        parser = seal.parse_manifest.parser_version if seal.parse_manifest else "plain-lines/v1"
    work_key = (
        digest(
            [
                source_type,
                str(source_id),
                source["source_revision"],
                source["content_hash"],
                parser,
                CHUNKER,
                version(),
                CODE_RULE,
                None,
            ]
        )
        if source
        else None
    )
    values = []
    if source:
        title = analyze(source["title"])
        for ordinal, (body, locator) in enumerate(chunks(source["body"], seal=seal)):
            words = analyze(body)
            values.append(
                {
                    "id": uuid5(NAMESPACE_URL, f"enterprise:{ctx.tenant_id}:{work_key}:{ordinal}"),
                    "tenant_id": ctx.tenant_id,
                    "category_id": source["category_id"],
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_revision": source["source_revision"],
                    **{
                        key: source[key]
                        for key in ("product_id", "project_id", "proposal_id", "nature")
                    },
                    "content_hash": source["content_hash"],
                    "work_key": work_key,
                    "ordinal": ordinal,
                    "chunk_hash": hashlib.sha256(body.encode()).hexdigest(),
                    "text": body,
                    "locator": locator,
                    "term_counts": words["counts"],
                    "title_counts": title["counts"],
                    "token_count": words["length"],
                    "terms": func.to_tsvector("simple", " ".join(words["terms"] + title["terms"])),
                    "codes": sorted(set(words["codes"] + title["codes"])),
                    "code_families": sorted(set(words["families"] + title["families"])),
                    "parser_version": parser,
                    "chunker_version": CHUNKER,
                    "tokenizer_version": words["tokenizer_version"],
                    "code_rule_version": CODE_RULE,
                    "created_at": now(),
                }
            )
    if (
        not force
        and previous
        and previous.status == "ready"
        and source
        and previous.work_key == work_key
        and previous.chunk_count == len(old)
        and previous.category_id == source["category_id"]
        and previous.source_revision == source["source_revision"]
        and previous.content_hash == source["content_hash"]
        and previous.original_id == source["original_id"]
        and _same_chunks(old, values)
    ):
        # The deterministic work key alone does not prove that derived rows
        # survived intact. Check token vectors in one batch after literal fields.
        vectors = case({value["id"]: value["terms"] for value in values}, value=SearchChunk.id)
        corrupted = (
            session.scalar(
                select(func.count())
                .select_from(SearchChunk)
                .where(
                    SearchChunk.tenant_id == ctx.tenant_id,
                    SearchChunk.source_type == source_type,
                    SearchChunk.source_id == source_id,
                    SearchChunk.terms.is_distinct_from(vectors),
                )
            )
            if values
            else 0
        )
        if not corrupted:
            previous.checked_at, previous.event_id, previous.last_error = now(), event_id, None
            previous.original_ids = list(source["original_ids"])
            return {"status": "ready", "changed": False, "chunks": len(old)}
    if repair_derived:
        # Internal recovery only. Identity parameters come from the ordinary
        # source read above, never from a model or an external command payload.
        # The primitive may see hidden derived metadata, but no source body.
        if source is None or expected_source is None:
            raise DomainError("SOURCE_UNAVAILABLE", "派生修复须先核对固定权威来源。")
        session.execute(
            text(
                "SELECT public.enterprise_index_source_clear("
                ":kind,:identity,:category,:key,CAST(:ids AS uuid[]))"
            ),
            {
                "kind": source_type,
                "identity": source["source_id"],
                "category": source["category_id"],
                "key": work_key,
                "ids": [value["id"] for value in values],
            },
        )
        # SQL deletion intentionally reaches wrong-category derived rows that
        # ordinary ORM reads could not see. Discard loaded identities as well.
        for row in [*old, *([previous] if previous is not None else [])]:
            session.expunge(row)
        previous, old = None, []
    else:
        _statistics(session, ctx.tenant_id, old, values)
    session.execute(
        delete(SearchChunk).where(
            SearchChunk.tenant_id == ctx.tenant_id,
            SearchChunk.source_type == source_type,
            SearchChunk.source_id == source_id,
        )
    )
    for value in values:
        session.execute(insert(SearchChunk).values(**value))
    state = previous or SearchSource(
        id=uuid4(),
        tenant_id=ctx.tenant_id,
        category_id=source["category_id"] if source else ctx.category_id,
        source_type=source_type,
        source_id=source_id,
    )
    state.source_revision = source["source_revision"] if source else expected_revision
    state.original_id = source["original_id"] if source else state.original_id
    state.original_ids = list(source["original_ids"]) if source else None
    state.content_hash = source["content_hash"] if source else None
    state.work_key, state.chunk_count = work_key, len(values)
    state.status, state.last_error = ("ready" if source else "unavailable"), None
    state.event_id, state.checked_at = event_id, now()
    session.add(state)
    session.flush()
    return {"status": state.status, "changed": True, "chunks": len(values)}


def rebuild(engine, ctx):
    """Rebuild this caller's actual readable set; no elevated business-table identity."""
    from .recovery import plan_rebuild, rebuild_batch

    plan = plan_rebuild(engine, ctx)
    cursor, totals = 0, {"processed": 0, "changed": 0, "failed": 0}
    while True:
        result = rebuild_batch(engine, plan, cursor)
        for key in totals:
            totals[key] += result[key]
        if result["next_cursor"] is None:
            return totals
        cursor = result["next_cursor"]


def _same_chunks(old, values):
    """Metadata, exact text, locations and token counts must all match the projector."""
    if len(old) != len(values):
        return False
    indexed = {row.id: row for row in old}
    return len(indexed) == len(values) and all(
        value["id"] in indexed
        and all(
            getattr(indexed[value["id"]], key) == field
            for key, field in value.items()
            if key not in {"terms", "created_at"}
        )
        for value in values
    )


def record_failure(session, ctx, kind, identity, category_id, revision, error, event_id=None):
    require_context(session, ctx)
    _lock(session, ctx, kind, identity)
    row = session.scalar(
        select(SearchSource).where(
            SearchSource.tenant_id == ctx.tenant_id,
            SearchSource.source_type == kind,
            SearchSource.source_id == identity,
        )
    )
    if row is None:
        row = SearchSource(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            category_id=category_id,
            source_type=kind,
            source_id=identity,
            original_id=None,
            source_revision=revision,
            content_hash=None,
            work_key=None,
            chunk_count=0,
            status="failed",
        )
    # A still-current old keyword projection may remain readable; current-source
    # joins and scan proofs continue to apply. Failure never becomes an empty success.
    row.last_error = error.code if isinstance(error, DomainError) else "INDEX_WRITE_FAILED"
    row.event_id, row.checked_at = event_id, now()
    session.add(row)
