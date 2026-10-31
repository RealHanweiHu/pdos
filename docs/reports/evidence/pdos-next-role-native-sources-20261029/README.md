# D native role-source increment — frozen stage

No live edits, DB connection, model/embedding/provider call, real KMS, migration numbering, build or native business-history insertion was performed here. Root applies public patches and assigns the actual next migration. The prior bounded B/D map is `/tmp/pdos-d-b-final-coverage-map-20261029/map.md`.

Scope: frozen enterprise-RAG design §7.2 and §13 D explicitly list native project status updates and manufacturing/handoff documentation. Add three registered SourceProjector families (10 → 13), through existing `assistant.search` / extract / citations / materials reads. Full tool disclosure remains 61; this does not claim execution of all tools. No bootstrap, new READ tool, publication workflow, domain write command, general applicability gate, golden case or real question set is added.

## Actual identity and Current

| Family | Genuine fixed records | Nature / Current / relations |
|---|---|---|
| project_status | `ProjectStatusUpdate.id/revision`, immutable named owner/status command | Internal structured named fact; latest ordinary-readable update for the exact project by created_at/id. Health is not invented; continuation permission not evaluated. Explicit task_refs remain native task IDs; no fabricated same-project search edge. |
| manufacturing_document | `PreparationVersion.id/revision` for work_instruction/control_plan; separately `ManufacturingPublicationDocument.id/publication_revision` joined to exact fixed document and actual named publication | Internal structured document fields only. Sources/snapshots/kernel event/authority input containers are omitted. Draft Current and formal Publication Current are independent; a new draft cannot turn the previously published fixed document into the new draft. Own stable UUIDs/revision/series/process/operation are retained. Edges use actual predecessor/version, publication document FK and process scope only. |
| verification_handoff | `VerificationHandoffFact.id/revision`, actual immutable offer/accept/return record | Internal structured physical fact, status_as_recorded and exact old/next request versions. Current only while the actual request Current equals its next request version; later Start makes the fact historical. Build edge uses the fixed next request's real Build FK/revision. No current execution permission is inferred. |

All models already have actual category columns and original native RLS. Shared projector keeps ordinary Project/Product/Build parent checks, current scan proof and complete original dependencies. `record_owner/visibility/revision` hooks exist only because publication-document links have these properties on their actual publication parent. No new permission root or guessed customer classification exists: manufacturing original IDs come from full fixed read sets, and native handoff from its full read set. Original Artifact document paths remain unchanged.

Native Outbox events require the committed receipt/command/subject, or the original confirmation/next request pins where those native models have no receipt columns. Replaying an old event reprojects all versions in that actual series/project/request so Current metadata stays honest. Navigation adds bounded batch reads, no per-row source validation. Human destinations use existing project panels: now:summary, prep:manufacturing, prep:publication, builds:handoff. Existing Field destination is corrected from issues:field to the actual feedback:field panel.

## SQL and public patch integration

`files/` contains 11 new owned files. `patches/` contains precise diffs for 14 existing files. `patched/` contains review copies only; **never overlay action_sources.py or answer-sources.tsx** because the follow-up/current-basis agents also own adjacent work. Root layers only the SourceTables/audience hooks and href/relation additions. Capture logic is untouched. No changes to root-owned models.py/indexing.py/sources.py are shipped.

`migrations/candidates/role_native_sources.py` and `sql/*.sql` are unnumbered. PREVIOUS_FUNCTIONS pin the actual current 0844 resolver, 0845 visibility and 0846 recovery-clear functions. CREATE OR REPLACE preserves owners/ACL; resolver/recovery retain SECDEF and visibility remains INVOKER. No policy is changed. The only lifecycle mapping extends the existing `assistant_source_lifecycle_links`; publication links additionally retain their real document/publication IDs, without fake Artifact references. The recovery whitelist includes all 13 types. EMPTY_HISTORY_SQL follows 0844's all-tenant retained-source-proof guard for the new three types; root must use administrative migrator and actual pin checks before downgrade. Old migrations are not rewritten.

All-source metadata/SourceHead/Document/Chunk/Outbox source_type storage is unconstrained text (no nine/ten-type table CHECK to extend); the recovery function whitelist, schema Literal, presence map, fixed-native classification, relation catalog, visibility branches and typed resolver are the finite lists changed here.

## Necessary validation and remaining actual checks

- 22 pure tests passed: new source/schema/event/current-body/pin boundary checks, original Field contract, complete 13-family CTE identifier checks and original explicit relation checks. `pure-result.txt`.
- 26 existing Xiaopai frontend tests passed in isolated copied src with shared dependency directory; no build. The changed strict object destination parser still rejects mixed selectors and arbitrary URLs.
- Ruff passed with explicit repository `pdos-next/ruff.toml`, run from the isolated server root to preserve actual first-party import classification. `ruff-result.txt`.
- 14 actual PG tests collected; collection opens no DB. Three new genuine native PG cases cover saved owner status versions → Outbox → registered answer, actual WI/CP/named publication → new draft with old formal Current → answer → original withdrawal, and physical offer → request/Build relation → fixed answer. Each exercises installed ordinary knowledge visibility and the one typed lifecycle resolver using its real returned fixed proof. `pg-collect.txt`.
- Actual PG execution, migration actual-pin/owner/ACL/roundtrip checks, final merged tsc/build and UI are root-owned and **not passed by this stage**.

The all-source recovery fixture genuinely seeds 13 under one existing quality requester. Its original results fixture already creates real physical offer/accept records; the project owner records a new original STATUS T1; the quality requester uses original manufacturing fixture/controlled trusted synthetic imports and native COMMON WI/CP commands for its own private documents. The original manufacturing test helper counts only its own actual issuer, rather than all unrelated quality credentials for the same person. Runtime/store are restored immediately. No qualifications or domain rows are directly assigned. The performance authority batch explicitly reads existing historical handoff after Start; it does not invent an extra current handoff. Search benchmark remains the original default-current request. The report records `historical_families_in_authority_batch`.

Historical nine/ten-family performance remains historical evidence. Root reported the ten-family 63-source search p95 1.2385s failure and is fixing the duplicate original-candidate metadata path. This stage does not claim that failure passed or that thirteen-family performance has run. Root's derived original_ids cache automatically consumes these source rows and still rechecks actual original proof/full authority.

## Root's smallest exact run groups

From `pdos-next/server` under the already verified explicit isolated TEST_DATABASE_URL and existing fixture path harness:

1. `pytest -q tests/enterprise_search/test_project_status_sources_pg.py tests/enterprise_search/test_manufacturing_document_sources_pg.py tests/enterprise_search/test_verification_handoff_sources_pg.py` — 3 new native cases.
2. `pytest -q tests/enterprise_search/test_recovery_pg.py -k 'not registered_family_search_and_authority'` — original 10 recovery/function cases, now genuine 13-family fixture. Old test node names containing nine are renamed registered; do not silently reuse old selection expressions.
3. `pytest -q tests/enterprise_search/test_recovery_pg.py::test_registered_family_search_and_authority_batch_stay_constant_sql_and_under_one_second` — new 13-family candidate performance; authority batch count and historical-family metadata reported.
4. `pytest -q tests/enterprise_search/test_recovery_temporal_pg.py` — original 12 Temporal cases, shared imported fixture now 13-family. Root chooses rerun scope after current recovery change; this package does not rerun previous passes automatically.

The 0848 cache work must be layered before the thirteen-family performance result. This package has no 0848 function dependency and root keeps the actual next number.
