# D native Field source candidate

Frozen manifest: `manifest.json`, SHA-256
`bfda76fa177e3ee5654bf537ef641d1acbee8f66f9edaa36910ac0577a6b4b05`.
Base Git HEAD: `28bacbb7d8be01b50296004a66891ab9892d30f4`, with exact individual
file bases in the manifest. All twelve bases matched live at freeze. Six new
files, twelve precise patches and three static SQL proposal files are listed.
Root owns integration, actual-head migration allocation, PG, build and browser.

## Product behavior

The diagnosis and initial evidence are frozen under `diagnostic/`. Native
`FieldFeedbackVersion` and `FieldResponseRecord` become one independent
`field_feedback` source family, retaining each actual immutable fact's ID and
revision and the aggregate `feedback_id` as its object identity. No per-source
READ tool is added: the original `assistant.search` → `assistant.extract` →
signed citation/passage/history machinery is reused, with 61 initial tool names.

- Customer/field intake description and reported labels are `untrusted`; the
  existing physical extraction graph receives their body. The main search sees
  metadata. Independent employee response fields remain structured facts; they
  do not copy the customer's raw parent description.
- Category-only intake is searchable before actual location. Null project,
  configuration and batch remain unknown. A native T1 location creates its own
  fixed source version; old intake and independent responses keep their bodies.
  The original Current pointer determines currentness. Continuation/acceptance
  authority is explicitly unevaluated rather than inferred from reported labels.
- Both models use the shared native projector factory, ordinary live RLS,
  shared readable CTEs, current original/scan checks and fixed dependency checks.
  Optional scope is enabled only for this new family. An existing long line in
  `assistant_sources.py` is wrapped while adding the fixed-record family.
- Their complete native `source_basis.artifacts` determines original roots,
  privacy and dependency versions. A response's direct `reads` excludes retained
  parent material by native design and is insufficient for this projection.
- Root-confirmed customer classification uses actual fixed
  `FeedbackVersion.body.channel == customer`, plus inherited original roots;
  responses use their exact matched parent ID/revision/scope. Model parameters
  and titles cannot set that classification. The original nine families retain
  their prior path. Human deidentification/publication remains the existing
  independent knowledge workflow. See `diagnostic/classification-addendum.md`.
- Actual four native Field Outbox events enter the original projection sender.
  Location also rechecks prior immutable intake versions. Existing work keys
  and replay semantics provide idempotence; rebuild uses the same catalog.
- Exact response↔feedback, change↔feedback and located batch↔feedback references
  extend the existing one-hop graph. Both ends use the same authority snapshot.
  Located sources open the current native Field panel; unlocated intake has its
  fixed snippet without an invented project destination. Frontend route and
  explicit-source validation accept this family and the original feedback ID.
- The existing I14 action audience port adds its two actual native table ports
  and the complete retained basis. Its current all-carried `capture` logic is
  unchanged. No business write command, professional authority or shared-object
  rule is changed.

## Single lifecycle resolver proposal

`sql/unnumbered-field-feedback-lifecycle-up.sql` replaces only the existing
`public.assistant_source_lifecycle_links(uuid,uuid,jsonb)` function. It extends
the accepted family and resolves the two actual native fact tables through
their retained source basis. There is no second typed root mapping or new ACL
function. It preserves the original signature, privileges and existing ports.

The base is extracted from actual `schema_s0_0839.LIFECYCLE_SQL[0]` (the current
Python `domain/knowledge/assistant_storage.py` does not contain this resolver).
The exact base SQL is included with SHA
`e173c1360df2b10e93bc87c97351bffa71f5429e992f2e731d8805ed0d8286e8`.
Root reported head `s0_0843`; no DB was inspected here. Root must verify current
function semantics and allocate the next real migration. The down proposal
refuses removal when retained knowledge/Gap/actual read results contain Field
proofs. No numbered migration or lifecycle catalog is changed in this stage.

## Validation

The isolated candidate imports its complete copied Python package, not live
modules shadowing proposed hooks. `validation-code-inputs.json` records its
source fingerprints. DB/auth/dispatch/Temporal targets were explicitly removed;
no `.env`, DB, real provider, KMS, network, build or browser operation was used.

- `pure.txt`: **38 passed** = six new source/parent-audience/edge checks + three
  full-catalog CTE identifier checks + four original full-face X3 checks + 25
  original action-source checks.
- `ruff.txt`: **15 exact isolated Python files passed**, with explicit
  `--config pdos-next/ruff.toml --no-cache`.
- `web-validation.txt`: **30 existing component cases passed**, with added Field
  destination assertions; three-file ESLint and isolated `tsc --noEmit
  --incremental false` passed. This file records the tool-result summary, not a
  full TAP transcript.
- `pg-collect.txt`: **17 collected, none executed**: five new native PG cases,
  eleven original all-source cases and one original Temporal case.

The five new PG cases are at
`pdos-next/server/tests/enterprise_search/test_field_feedback_sources_pg.py`:
unlocated intake + isolated raw extraction; the same no-UploadedOriginal customer
intake under P26 internal-only refusal (also checks actual embedding categories);
native T1 location/independent response/current link/one-hop; retained parent
basis after direct reads omit it, private-reader rejection, source update and
withdrawal; and actual UploadedOriginal/fake scanner classification and current
scan invalidation. Fixtures use original commands, confirmations, receipts and
Outbox, plus the existing real model/read ledger and registered graph with a
fake provider. They do not manufacture business history or populate golden-case.

## Root verification affected by the tenth family

The original shared fixture now calls real Field commands before asserting full
`SOURCE_TYPES` coverage. It does not shrink selection to nine families. The
following exact paths therefore need current-candidate verification:

- `pdos-next/server/tests/enterprise_search/test_source_cte_identifiers.py`
- `pdos-next/server/tests/enterprise_search/test_recovery_pg.py`, including
  `test_nine_family_search_and_authority_batch_stay_constant_sql_and_under_one_second`
- `pdos-next/server/tests/enterprise_search/test_recovery_temporal_pg.py::test_nine_family_fixed_batches_survive_worker_restart_without_replanning`
- `pdos-next/server/tests/agent_kernel/test_context_x3_full_disclosure.py`
- `pdos-next/server/tests/enterprise_search/test_action_sources.py` and the
  root-owned original I14/I22 action/knowledge cases
- `pdos-next/web/src/components/xiaopai.test.mjs` and
  `pdos-next/web/src/components/pai/explicit-context-corrections.test.mjs`

The recovery test names keep their historical nine-family identifiers for
selection/link continuity; their current fixture/catalog covers ten families.
Prior nine-family latency evidence remains historical. This stage claims no new
ten-family SQL/p95, PG/Temporal, production build or browser result. Root should
refresh the original schema/OpenAPI/tool export artifacts for the expanded
generic source enum and preserve the current run/version contracts.

This closes one local D source capability gap. Other role sources and full
domain applicability, 30–50 human-maintained real-role questions, comparative
quality/correction-cost evidence, real model/embedding and pilot acceptance
remain separate work. No trusted-root evaluation material was created or edited.
