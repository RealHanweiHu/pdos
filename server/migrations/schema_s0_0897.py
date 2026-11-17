"""Renumbered at the 11-16 merge into pdos-next/design-v1.1, where mainline A holds
s0_0889–s0_0892: the memory chain s0_0889–s0_0895 became s0_0893–s0_0899 and its first
step now follows s0_0892. Memory revision numbers in this file are the new ones.

Assigned s0_0897 on s0_0896 at the 11-16 memory integration (placeholder s0_0900).

Personal notes move to the unified item contract (P121 第 6 项后半, D512; 目标架构 §5.7).

占位号：s0_0900 是并行工作区（claude/memory-note-contract）的占位号，写在真实 head s0_0896
之后。集成时按真实 head 重排：revision、down_revision、本快照文件名（及版本文件里的
import）和下面降级守卫里的文字 ``require s0_0897`` 一起改（不可协商项 3）。

``memory_note_versions`` gains the contract fields a personal note uses:

- ``occurred_at``  事情发生的时间 (nullable; never later than the version's record time).
- ``valid_from``   生效起点. 替代按生效时间判断 (P121 第 6 项): a draft that starts earlier
  than the note it would replace only enters history. ``valid_until`` stays the
  contract's ``valid_to``.
- ``confirmation`` 业务确认状态, same values as scope notes. A personal note is always
  本人确认 (``member_confirmed``): proposals stay candidates until the owner clicks 记住,
  and a personal note is never a business record (P86 第 1、10 项).
- ``evidence``     证据链接, the same link shape as ``scope_note_evidence`` (source, kind,
  version, locator, quote digest, root source, stance). No quoted text is stored.
- ``relations``    冲突 / 重复 between two of the owner's own notes. 替代 is the existing
  ``replaced_by`` on the replaced side.

Evidence and relations live on the version, not in side tables: a version is the
only place a personal note's content lives, so the owner's purge (P94) removes them
together with every version and leaves only the tombstone. The row-level security,
the no-update trigger and the purge policy of s0_0865 are unchanged; the AI writer
identity still cannot insert a version.

Existing versions are migrated once (defaults, see the evidence README):

- ``valid_from`` = the version's own record time (``created_at``), i.e. when the owner
  confirmed that version; this keeps every existing note, revision and ``as_of``
  answer as it was. A ``replaced`` marker version copies the ``valid_from`` of the
  version it closes, as new markers do.
- ``occurred_at`` = NULL: it was never asked, and nothing may be guessed.
- ``confirmation`` = ``member_confirmed``: every existing version was written or
  confirmed by its owner.
- ``evidence`` = ``relations`` = ``[]``: none were ever recorded. A note adopted from a
  proposal keeps pointing at its Run through ``candidate_id``; that is not copied.

Downgrade refuses while any version carries data s0_0896 cannot express: a time the
event happened, an evidence link, a relation, or a start that is not the migration
default (a future start, a back-dated start, or a back-filled history entry), since
s0_0896 would read those as effective from their record time.
"""

# ruff: noqa: E501 -- Reviewed applied SQL literals remain byte-identical.

TABLE = "public.memory_note_versions"

# Filled from the exact reviewed ORM checks (pdos_next.agent.memory.models.NOTE_CONTRACT_CHECKS).
CHECK_SQL = (
    "ALTER TABLE public.memory_note_versions ADD CONSTRAINT memory_note_contract_time CHECK (confirmation IN ('member_confirmed') AND (valid_until IS NULL OR valid_until >= valid_from) AND (occurred_at IS NULL OR occurred_at <= created_at))",
    'ALTER TABLE public.memory_note_versions ADD CONSTRAINT memory_note_evidence CHECK (jsonb_typeof(evidence)=\'array\' AND jsonb_array_length(evidence) <= 10 AND NOT jsonb_path_exists(evidence, \'$[*] ? (@.type() != "object" || !exists(@.source_type) || !exists(@.source_id) || !exists(@.root_source_id) || !exists(@.stance) || !exists(@.locator))\') AND NOT jsonb_path_exists(evidence, \'$[*] ? (!(@.source_type == "run" || @.source_type == "discussion" || @.source_type == "receipt" || @.source_type == "original" || @.source_type == "business_object"))\') AND NOT jsonb_path_exists(evidence, \'$[*] ? (!(@.stance == "supports" || @.stance == "opposes" || @.stance == "context"))\') AND NOT jsonb_path_exists(evidence, \'$[*] ? ((@.source_type == "business_object" && !(@.source_kind == "category" || @.source_kind == "product" || @.source_kind == "proposal" || @.source_kind == "project" || @.source_kind == "proposal_decision")) || (@.source_type != "business_object" && exists(@.source_kind) && @.source_kind != null))\') AND NOT jsonb_path_exists(evidence, \'$[*] ? (exists(@.quote_sha256) && @.quote_sha256 != null && !(@.quote_sha256 like_regex "^[0-9a-f]{64}$"))\'))',
    'ALTER TABLE public.memory_note_versions ADD CONSTRAINT memory_note_relations CHECK (jsonb_typeof(relations)=\'array\' AND jsonb_array_length(relations) <= 10 AND NOT jsonb_path_exists(relations, \'$[*] ? (@.type() != "object" || !exists(@.note_id) || !(@."type" == "conflicts" || @."type" == "duplicates"))\'))',
)

COLUMNS = (
    ("occurred_at", "TIMESTAMP WITH TIME ZONE"),
    ("valid_from", "TIMESTAMP WITH TIME ZONE"),
    ("confirmation", "VARCHAR(24)"),
    ("evidence", "JSONB"),
    ("relations", "JSONB"),
)

SCHEMA_SQL = (
    *(f"ALTER TABLE {TABLE} ADD COLUMN {name} {kind}" for name, kind in COLUMNS),
    # One-time fill of the new fields; versions are otherwise never updated.
    f"ALTER TABLE {TABLE} DISABLE TRIGGER memory_note_versions_no_update",
    f"UPDATE {TABLE} SET valid_from=created_at, confirmation='member_confirmed', "
    "evidence='[]'::jsonb, relations='[]'::jsonb",
    f"UPDATE {TABLE} v SET valid_from=p.valid_from FROM {TABLE} p "
    "WHERE v.status='replaced' AND p.tenant_id=v.tenant_id AND p.note_id=v.note_id "
    "AND p.revision=v.revision-1",
    f"ALTER TABLE {TABLE} ENABLE TRIGGER memory_note_versions_no_update",
    *(f"ALTER TABLE {TABLE} ALTER COLUMN {name} SET NOT NULL"
      for name in ("valid_from", "confirmation", "evidence", "relations")),
    *CHECK_SQL,
)

DOWNGRADE_SQL = (
    f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM {TABLE} v WHERE v.occurred_at IS NOT NULL
       OR v.evidence<>'[]'::jsonb OR v.relations<>'[]'::jsonb
       OR (v.status<>'replaced' AND v.valid_from<>v.created_at)
       OR (v.status='replaced' AND v.valid_from IS DISTINCT FROM (SELECT p.valid_from FROM {TABLE} p
         WHERE p.tenant_id=v.tenant_id AND p.note_id=v.note_id AND p.revision=v.revision-1))) THEN
     RAISE EXCEPTION 'Personal note contract fields require s0_0897'; END IF; END $$""",
    *(f"ALTER TABLE {TABLE} DROP CONSTRAINT {name}" for name in (
        "memory_note_relations", "memory_note_evidence", "memory_note_contract_time")),
    *(f"ALTER TABLE {TABLE} DROP COLUMN {name}" for name, _kind in reversed(COLUMNS)),
)
