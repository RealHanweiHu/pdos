"""遗忘后的抑制指纹 (P121 第 8 项; 目标架构 §5.6.2 关口一、§6.4).

When the owner purges a note, its text is gone; what stays is a digest of the
statement and references to the Runs whose words it was proposed from, so nothing
proposes it again from old records:

* a proposal that quotes a Run the purged note came from is refused;
* a proposal whose statement matches a fingerprint is refused, unless it is an
  explicit instruction the owner gave in a Run started after the forgetting
  (本人之后重新明确交代的不受限);
* when the owner confirms the same statement again (adds it or adopts a
  candidate), the fingerprints of that purged note are removed.

No text is stored. The digest is SHA-256 over a random per-row salt and the
statement with case, spacing and punctuation removed, so only the same statement
matches: a reworded one does not (the source-Run rule covers old words). The salt
stops look-up tables and matching across rows, but the server has no secret key
for this, so someone who can read the row could still test a guessed sentence
against it (see the evidence note; a keyed digest needs a tenant key service).

Any later background job that drafts personal candidates must call ``blocked``
before storing one.
"""

import hashlib
import secrets
import unicodedata
from uuid import uuid4

from sqlalchemy import delete, insert, select

from .models import MemoryCandidate, MemorySuppression

LIMIT = 500


def normalize(value):
    folded = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in folded if character.isalnum())


def claims(values):
    """What a note asserts: its statement, and for a 叫法 the term it names."""
    found = [("text", normalize(values.get("text")))]
    if values.get("alias_term"):
        found.append(("alias", normalize(values["alias_term"])))
    return [f"{kind}\x00{value}" for kind, value in found if value]


def _digest(salt, claim):
    return hashlib.sha256(f"{salt}\x00{claim}".encode()).hexdigest()


def _rows(session, owner_id):
    return session.scalars(
        select(MemorySuppression).where(MemorySuppression.owner_id == owner_id)
        .order_by(MemorySuppression.created_at.desc(), MemorySuppression.id).limit(LIMIT)
    ).all()


def _hits(rows, values):
    wanted = claims(values)
    return [row for row in rows
            if any(_digest(row.salt, claim) == row.fingerprint for claim in wanted)]


def record(session, ctx, note_id, versions):
    """In the owner's purge, before the versions and their candidates are deleted."""
    candidate_ids = {row.candidate_id for row in versions if row.candidate_id is not None}
    quotes = [quote for trigger in session.scalars(
        select(MemoryCandidate.trigger).where(MemoryCandidate.id.in_(candidate_ids))
    ).all() for quote in trigger] if candidate_ids else []
    seen = set()
    for version in versions:
        for claim in claims({"text": version.text, "alias_term": version.alias_term}):
            if claim in seen:
                continue
            seen.add(claim)
            salt = secrets.token_hex(16)
            session.execute(insert(MemorySuppression).values(
                id=uuid4(), tenant_id=ctx.tenant_id, owner_id=ctx.requester_id, note_id=note_id,
                salt=salt, fingerprint=_digest(salt, claim),
                source_spans=[{"run_id": str(quote["run_id"]),
                               "quote_sha256": _digest(salt, normalize(quote["text"]))}
                              for quote in quotes],
            ))
    return len(seen)


def blocked(session, run, *, origin, values, quotes):
    """Reason a proposal for the Run's requester is suppressed, or None."""
    rows = _rows(session, run.requester_id)
    if not rows:
        return None
    sources = {span["run_id"] for row in rows for span in row.source_spans}
    if any(str(quote["run_id"]) in sources for quote in quotes):
        return "suppressed_source"
    hits = _hits(rows, values)
    if not hits:
        return None
    if origin == "explicit" and all(row.created_at < run.created_at for row in hits):
        return None  # The owner said it again, explicitly, after forgetting it.
    return "suppressed_by_forgetting"


def lift(session, ctx, values):
    """The owner confirmed the same statement again: that forgetting no longer applies."""
    notes = {row.note_id for row in _hits(_rows(session, ctx.requester_id), values)}
    if notes:
        session.execute(delete(MemorySuppression).where(
            MemorySuppression.owner_id == ctx.requester_id,
            MemorySuppression.note_id.in_(notes)))
    return len(notes)
