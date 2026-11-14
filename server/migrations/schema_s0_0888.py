"""D482 (P121 第 1 项): a second keyword-index row per episode, for 小Pai's side of the record.

The ``episode`` row keeps the owner's own words and is unchanged. The new
``answer`` row holds the answer summary and the unfinished items of the same
episode. They are two rows, not one, so that the owner's
Session list search keeps matching the owner's own words only: an answer whose
sources were later revoked is hidden from the owner, and its words must not be
findable through that list either. ``memory.search`` reads both rows and
rechecks every hit against the dependency manifest before returning it.

An episode is pending until it has both rows for the current tokenizer, so
episodes indexed before this migration get their answer row filled in.
"""

from migrations.schema_s0_0855 import PENDING_SQL as _AT_S0_0855

SIGNATURE = "memory_pending_index_references(uuid,text,integer)"
_HEAD = "CREATE FUNCTION public.memory_pending_index_references("
_MISSING = """  AND NOT EXISTS(SELECT 1 FROM public.memory_index i WHERE i.tenant_id=e.tenant_id
   AND i.episode_id=e.id AND i.tokenizer_version=tokenizer)"""
_EITHER_MISSING = """  AND (SELECT count(DISTINCT i.source_kind) FROM public.memory_index i
   WHERE i.tenant_id=e.tenant_id AND i.episode_id=e.id AND i.tokenizer_version=tokenizer
    AND i.source_kind IN ('episode','answer'))<2"""
if _AT_S0_0855.count(_HEAD) != 1 or _AT_S0_0855.count(_MISSING) != 1:
    raise RuntimeError("s0_0855 pending-index function changed")
# Written by s0_0855 and not redefined through s0_0887 (checked 2026-11-13).
PREVIOUS = _AT_S0_0855.replace(_HEAD, _HEAD.replace("CREATE", "CREATE OR REPLACE"))
CURRENT = PREVIOUS.replace(_MISSING, _EITHER_MISSING)

_KIND = "ALTER TABLE public.memory_index DROP CONSTRAINT memory_index_source_kind"

UP_SQL = (
    _KIND,
    "ALTER TABLE public.memory_index ADD CONSTRAINT memory_index_source_kind "
    "CHECK (source_kind IN ('episode','answer'))",
    CURRENT,
)

# Index rows are derived from episodes and Runs; dropping the answer rows loses nothing
# that a later upgrade does not rebuild.
DOWN_SQL = (
    PREVIOUS,
    "ALTER TABLE public.memory_index DISABLE TRIGGER memory_index_append_only",
    "DELETE FROM public.memory_index WHERE source_kind='answer'",
    "ALTER TABLE public.memory_index ENABLE TRIGGER memory_index_append_only",
    _KIND,
    "ALTER TABLE public.memory_index ADD CONSTRAINT memory_index_source_kind "
    "CHECK (source_kind IN ('episode'))",
)
