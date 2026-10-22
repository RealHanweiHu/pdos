# Independent backend correctness review

2026-10-02. Read-only review of the in-flight `domain/supply_cost/{ports,rules,adapters,handlers}.py` and `schemas/supply_cost/dto.py`. No code edits, database access, services, credentials or original engine test suite runs. Root owns implementation and validation; this note is review evidence, not a test pass or a frozen candidate certification.

## Reviewed invariants

- BuildDemand is transported read-only; basis digest, manufacturing digest, complete original source read set, source currency, every authoritative expanded DemandLine field and duplicate IDs are checked.
- Handler binds opaque payload IDs against the server port's scope and expected revisions. Tenant/product/project/audience are not taken from client payloads.
- Current physical pools and all occupancy pass to the existing engine; promises, in-transit and incremental receipt evidence do not add stock.
- Snapshot canonicalization deduplicates identical views and rejects contradictory identities; reconciliation preserves old snapshot/digest and explicit differences with immutable identities and monotonic previous pointers.
- T1 preview contains substantive plan/hash/expiry. Apply authorizes current session/Run, asks the host for replay before fresh reads, reconstructs the plan at the stored fixed time, checks plan hash, and stages via the common transaction port. The protocol reserves confirmation one-use, locks, both dedupe layers, cancellation, current pointer, receipts/audit/Outbox and rollback for host integration.
- No backend code directly commits, starts a database transaction, imports old `app`, authorizes a formal release, reserves stock, grants alternative qualification or declares financial approval.

## Findings sent to root and corrected during review

1. Active quality statuses could disagree with a released/current pool and be ignored by the engine. Root added `QUALITY_PROJECTION_CONFLICT` validation.
2. Active quality source refs were absent from the coverage projection/plan/freshness; a release could expire without invalidating saved coverage. Root added source checks at calculation/application and `CoverageProjection.quality_sources` retention/rechecks.
3. Aggregate CostInputs source expiry was missing from read-side freshness. Root added `cost_source_unavailable`.
4. Qualification revocation and newly available qualification could be missed. Root added current server alternate-list recheck; missing recheck with previous qualifications is explicit, and empty-to-nonempty changes are compared.
5. Quote effective dates and rate age limits were separate from SnapshotRef validity. Root added freshness checks and current-time eligibility guards to prevent a formerly eligible preview being applied after its quote/rate aged out.
6. The cost aggregate ref was appended after source uniqueness checks. Root moved additional refs through the common `_sources` uniqueness pass.
7. Original Build/configuration source read set was not transported for common atomic checks. Root added explicit completion/refs, checks at calculation and application time, and plan read-set inclusion.
8. Process cost projection had only documentation requiring canonical manufacturing operation keys. Root added transport of exact operation IDs, missing-map blocking and exact operation-set comparison.

## Final read-only follow-up

The partial/unknown quality recommendation is resolved in the reviewed source: `canonical_supply` rejects status conflicts, rejects an unknown quantity for a released/available partition, validates supported units and requires the exact authoritative quantity. Active restriction sources are retained and rechecked. Original source read sets are now stored in BasisBinding, so a changed original evidence version invalidates a saved projection even when the projected Build/BOM fields remain the same.

`read_models.binding_view` requires the exact stored FixedBasis digest and Build ID; `snapshot_view` rejects reconciliation for another snapshot. Historical rendering therefore needs the original basis rather than today's quantities. New `snapshot_freshness` compares current basis, current snapshot identity/content and time validity of the aggregate/current balance/reservation/quality sources, while preserving historical views and reasons.

A final numeric edge was reported and resolved: the initial `conversion('s','min')` implementation produced a finite Decimal approximation to 1/60; exact equality after multiplication incorrectly rejected 60 seconds versus one minute, and computing the conversion outside the local calculation context inherited caller precision. A minimal read-only primitive probe returned `1.00000000000000000000000000020 != 1`. The final reviewed source compares each quantity multiplied by its canonical `UNITS` factor inside the isolated calculation context after dimension validation. This was a narrow primitive probe, not an engine test-suite run; root's final candidate checks certify the repair.

No further concrete correctness gap was found in the requested final read-only scope. This does not certify host authorization, SQL concurrency/rollback or public routing implementations, which remain mainline work.

## Canonical operation boundary

Read-only verified `pdos-next/contracts/operations.json` and architecture operation table:

| Canonical mainline operation | Tier | This local participant |
|---|---|---|
| `supply.commitment.record` | T0, current qualification and authorization | `supply.snapshot.record` is manual/import capture and immutable snapshot candidate handling via T1; it does not enable qualified canonical recording. |
| `supply.kit.compute` | T0, deterministic engine | `supply.coverage.calculate` preserves a locally reviewed candidate via T1; canonical route/receipt/event and current qualification remain mainline integration. |
| `cost.estimate.compute` | T0, deterministic engine | `supply.cost.estimate` preserves a locally reviewed estimate candidate via T1; canonical route/receipt/event and current qualification remain mainline integration. |
| `supply.alternate.approve` | T2, named decision | No local approval handler. The package only consumes server-verified qualifications. |

These aliases are local participant names; no canonical registry was changed by this package. They do not prove T0 activation, add a mandatory approval to future qualified T0, or downgrade the T2 qualification decision. Mainline must document and route canonical operations with their original policies and events.

## Host integration still required

Pure ports are contracts, not live authorization/SQL guarantees. The mainline must register immutable objects, provide real authenticated Build/complete read set/physical inventory-quality partitions/quote/process projections, and implement `CommandPort` in the existing transaction. Its locked stage must authenticate preview token/review/actor/scope, recheck current sources and cancellation, and consume confirmation plus projection/ActionReceipt/Audit/Outbox atomically. A documented Protocol alone is not evidence of rollback or concurrency behavior. Real DB/API/page transaction and browser checks remain mainline work.

Source files were being edited concurrently in response to review. Final hashes, appropriate package behavior tests and candidate equivalence belong in the root candidate evidence; this review does not certify earlier hash snapshots as final code.
