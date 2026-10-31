# Optional native knowledge proof NULL compatibility

This independent stage contains two bounded fixes for the original
`category.knowledge.add(kind=boundary)` failure. No live file, database,
numbered migration, provider, KMS or network was changed or called.

Root's safe diagnostic confirmed SQLSTATE 23514, no constraint name, and
`Fixed assistant source dependencies must be an array`; the call chain enters
the strict assistant resolver from `m3_lifecycle_source_links`, then lifecycle
roots/reference_clock. The original recovery fixture fails before its native
Field seeding step. It is an optional-proof compatibility error, unrelated to
source count or any new authority.

## Exact changes

`patches/category-answer-proof-null.patch` has one functional line in
`pdos_next/domain/preproject/category_models.py`: optional `answer_sources`
uses `JSONB(none_as_null=True)`. Original non-review knowledge passes Python
None, which the prior JSONB type binds as Jsonb(None), rather than SQL NULL.
The real PostgreSQL dialect now binds that None as SQL NULL. Arrays and an
explicit JSONB.NULL retain their original meanings. The column remains
nullable JSONB and all original shape/verified-answer CHECKs stay unchanged;
there is no column DDL or service rewrite. The existing import block is
Ruff-sorted because the unchanged live block already fails I001 under the
required repository configuration.

`migrations/candidates/knowledge_optional_proof.py` carries the exact old G843
`m3_lifecycle_source_links(uuid,uuid,text,jsonb)` pin from the current live
`migrations.candidates.dingtalk_lifecycle.NATIVE_FUNCTIONS`, plus its bounded
replacement. The old G candidate and numbered 0839/0843/0844 files are untouched.
Only category entries, candidate versions and rule versions may normalize
optional `answer_sources` using
`coalesce(nullif(container,'null'::jsonb),'[]'::jsonb)`. SQL NULL and JSON null
represent absence here; other scalars/objects still reach the original strict
array guard. Required Review/Gap `source_proof` reaches the resolver directly,
without a null fallback. G outbound dependency handling is byte-for-byte
unchanged, as is every native link before the F block.

The replacement retains STABLE SECURITY DEFINER and the existing search path.
CREATE OR REPLACE preserves owner/ACL. There is no GRANT, REVOKE, policy,
permission, root-mapping or resolver change. Readable old/up SQL copies are
under `sql/`; both the static candidate module and contract hashes are included
in the manifest. Root assigns/applies the actual next revision and merges this
function replacement with its separate visibility/G fence work. Root must not
replay or overwrite an already installed migration.

## Validation and minimal native follow-up

Three pure cases passed in an isolated source copy. They use the actual
PostgreSQL dialect bind processor, distinguish Python None/empty array/explicit
JSON null, compare the exact G843 pin, verify the closed three-table optional
boundary and raw required proof call, and retain the original strict resolver
and security contract. Explicit `--config pdos-next/ruff.toml --no-cache` Ruff
passed for the two new files and the model review copy. No engine was
opened. The tests check the real generated SQL contract; they do not claim to
execute PL/pgSQL.

Root's existing native regression selections, from `pdos-next/server`, are:

```text
tests/enterprise_search/test_recovery_pg.py::test_all_nine_sources_rebuild_after_real_derived_damage_without_business_changes[all_tables]
tests/preproject/test_material_commands_pg.py::test_knowledge_withdrawal_keeps_history_and_does_not_block_fixed_g0
```

The first is the actual failing original add-entry fixture and continues into
the real tenth-family recovery. The second already exercises the original
knowledge add/withdraw history path; no new large PG suite is added. Root's
already planned full `test_recovery_pg.py` (11, including ten-family performance)
and `test_recovery_temporal_pg.py` (1) remain the full recovery checkpoint. The
separate native Field -> F knowledge visibility case remains in its earlier
stage; it requires the separate ten-family visibility helper refresh.

Remaining work belongs to root: current-pin verification, actual next migration
assembly, upgrade/downgrade and native PG execution. This stage claims only the
three pure passes and lint result, not a recovered PG checkpoint.
