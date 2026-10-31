"""Use the retrieval scan gate before a Human metadata chooser's SQL page.

The supplied statement already has its actual RLS catalog and tenant/category /
literal title or object selector. Only dependency original IDs leave the first
metadata query; no source titles or bodies are fetched before eligibility. No
scan, permission or identity result is cached here.
"""

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import array

from .safety import safe_originals


def before_paging(session, source, statement):
    """Keep the main search's original_ids subset condition ahead of LIMIT.

    retrieval_catalog already owns native dependency/knowledge version authority.
    A clean flag alone cannot prove the current scanner/binding/requester grant;
    safe_originals applies the existing parsing_gate against those actual facts.
    This changes neither historical source identity nor is_current selection.
    """
    # The authority already expands native required roots and current knowledge
    # roots into this array. Reuse that exact projection, avoiding a second
    # independently named catalog alongside the chooser's complete catalog.
    identities = (
        statement.with_only_columns(
            func.unnest(source.c.original_ids).label("original_id"),
        )
        .order_by(None)
        .distinct()
    )
    originals = set(session.scalars(identities))
    safe = safe_originals(session, originals)
    return statement.where(
        source.c.original_ids.bool_op("<@")(array(sorted(safe), type_=PGUUID)),
    )
