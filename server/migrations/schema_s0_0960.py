"""占位号 s0_0960，集成时按真实 head 重排（接 s0_0888）。

Two memory retrieval gaps (D482 余项 ①, D300):

1. A third keyword-index row per episode, ``object``: the titles of the specific
   objects the Run focused on (materials it read, the source it was pinned to),
   as the owner could read them when the episode was indexed (P121 第 1 项
   "当时对象的标题"). Scope objects (category, product, proposal, project) are
   not indexed: every episode in a scope shares that title. An episode is
   pending until it has all three rows for the current tokenizer, so episodes
   indexed before this migration get their object row filled in.

2. Episode vectors are dispatched for every currently active profile version
   that selects “本人会话记录”, not only the newest one. While an administrator
   moves to a new embedding model (a new logical profile beside the old one),
   new episodes are written to both spaces and the old space keeps serving
   memory.search until the new one has caught up (design §14.9 嵌入版本).
   A version that is disabled or superseded is no longer dispatched.

3. The query-embedding guard (s0_0838) also accepts ``memory.search`` as the
   actual main READ a query vector derives from (P85 第 3 项; the Python side
   already lists it in ``PARENT_TOOLS``). Everything else it proves is kept:
   the exact model request, input digest, cancel epoch, active profile and the
   Run's frozen profile, read from the snapshot of that parent's own consumer
   (``memory_query_profile`` for memory.search, ``embedding_query_profile`` for
   assistant.search), so one Run's two consumers never share a vector space.
"""

from migrations.schema_s0_0838 import SCHEMA_SQL as _AT_S0_0838
from migrations.schema_s0_0866 import PENDING_SQL as _VECTORS_AT_S0_0866
from migrations.schema_s0_0888 import CURRENT as _INDEX_AT_S0_0888

_HEAD = "CREATE FUNCTION public.memory_pending_vector_references("
_EITHER = """  AND (SELECT count(DISTINCT i.source_kind) FROM public.memory_index i
   WHERE i.tenant_id=e.tenant_id AND i.episode_id=e.id AND i.tokenizer_version=tokenizer
    AND i.source_kind IN ('episode','answer'))<2"""
_ANY = """  AND (SELECT count(DISTINCT i.source_kind) FROM public.memory_index i
   WHERE i.tenant_id=e.tenant_id AND i.episode_id=e.id AND i.tokenizer_version=tokenizer
    AND i.source_kind IN ('episode','answer','object'))<3"""
_NEWEST = """ profile AS (
  SELECT latest.profile_version_id AS id, latest.categories FROM latest WHERE latest.enabled
  ORDER BY latest.created_at DESC LIMIT 1)"""
_EVERY = """ profile AS (
  SELECT latest.profile_version_id AS id, latest.categories FROM latest WHERE latest.enabled)"""
_ORDER = " ORDER BY e.created_at,e.id LIMIT LEAST(GREATEST(page_limit,1),200);"
_ORDER_EVERY = " ORDER BY e.created_at,e.id,profile.id LIMIT LEAST(GREATEST(page_limit,1),200);"
for text, part in ((_INDEX_AT_S0_0888, _EITHER), (_VECTORS_AT_S0_0866, _HEAD),
                   (_VECTORS_AT_S0_0866, _NEWEST), (_VECTORS_AT_S0_0866, _ORDER)):
    if text.count(part) != 1:
        raise RuntimeError("s0_0888/s0_0866 pending functions changed")

# Both functions are written by s0_0855/s0_0866/s0_0888 and not redefined through
# s0_0888 (checked 2026-11-14).
INDEX_PREVIOUS = _INDEX_AT_S0_0888
INDEX_CURRENT = _INDEX_AT_S0_0888.replace(_EITHER, _ANY)
VECTORS_PREVIOUS = _VECTORS_AT_S0_0866.replace(_HEAD, _HEAD.replace("CREATE", "CREATE OR REPLACE"))
VECTORS_CURRENT = VECTORS_PREVIOUS.replace(_NEWEST, _EVERY).replace(_ORDER, _ORDER_EVERY)

_GUARD_HEAD = "CREATE FUNCTION public.kernel_embedding_query_guard()"
_start = _AT_S0_0838[0].index(_GUARD_HEAD)
_end = _AT_S0_0838[0].index("$$", _AT_S0_0838[0].index("$$", _start) + 2) + 2
# Written by s0_0838 only and not redefined through s0_0888 (checked 2026-11-14).
GUARD_PREVIOUS = _AT_S0_0838[0][_start:_end].replace(
    _GUARD_HEAD, _GUARD_HEAD.replace("CREATE", "CREATE OR REPLACE")) + ";"
_GUARD_EDITS = (
    (" query_value jsonb;\n", " query_value jsonb; snapshot text;\n"),
    ("  OR p.tool<>'assistant.search' OR p.state NOT IN",
     "  OR p.tool NOT IN ('assistant.search','memory.search') OR p.state NOT IN"),
    (" IF request->>'name' IS DISTINCT FROM 'assistant.search'\n",
     " IF request->>'name' IS DISTINCT FROM p.tool\n"),
    ("kernel_read_canonical_json(jsonb_build_array('assistant.search',request->'arguments'))",
     "kernel_read_canonical_json(jsonb_build_array(p.tool,request->'arguments'))"),
    (" selected=r.versions->'embedding_query_profile';\n",
     " snapshot=CASE WHEN p.tool='memory.search' THEN 'memory_query_profile'\n"
     "   ELSE 'embedding_query_profile' END;\n selected=r.versions->snapshot;\n"),
    ("  OR r.versions->>'embedding_query_profile_digest' IS DISTINCT FROM",
     "  OR r.versions->>(snapshot||'_digest') IS DISTINCT FROM"),
)
GUARD_CURRENT = GUARD_PREVIOUS
for _old, _new in _GUARD_EDITS:
    if GUARD_CURRENT.count(_old) != 1:
        raise RuntimeError("s0_0838 query-embedding guard changed")
    GUARD_CURRENT = GUARD_CURRENT.replace(_old, _new)

_KIND = "ALTER TABLE public.memory_index DROP CONSTRAINT memory_index_source_kind"

UP_SQL = (
    _KIND,
    "ALTER TABLE public.memory_index ADD CONSTRAINT memory_index_source_kind "
    "CHECK (source_kind IN ('episode','answer','object'))",
    INDEX_CURRENT,
    VECTORS_CURRENT,
    GUARD_CURRENT,
)

# Index rows are derived; dropping the object rows loses nothing a later upgrade
# does not rebuild. Vectors are not touched in either direction.
DOWN_SQL = (
    GUARD_PREVIOUS,
    VECTORS_PREVIOUS,
    INDEX_PREVIOUS,
    "ALTER TABLE public.memory_index DISABLE TRIGGER memory_index_append_only",
    "DELETE FROM public.memory_index WHERE source_kind='object'",
    "ALTER TABLE public.memory_index ENABLE TRIGGER memory_index_append_only",
    _KIND,
    "ALTER TABLE public.memory_index ADD CONSTRAINT memory_index_source_kind "
    "CHECK (source_kind IN ('episode','answer'))",
)
