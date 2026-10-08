# Wave15 schema guard draft — read-only integration review

Status: offline SQL review only. No migration head was allocated or applied by this review; no database, pytest, HTTP, or production/test edits were performed. These findings concern the drafted database invariants, not a demonstrated bypass of the current controlled service.

Reviewed snapshot:

| File | SHA256 |
| --- | --- |
| `pdos-next/tools/wave15_schema_guards.py` | `54deec76b556e0a08841c42a4ebb9eb41ae151baf5d647ee5248b56ead1aa8c1` |
| `domain/change_execution/service.py` | `40448bde0b3cae0bb944e4e68ad41a4d5ec3047b137917794741c1bed04cc69f` |
| `domain/quality_execution/service.py` | `284f5749ca953ec24127b6595f263f0165faa5d1992095cb4b7639deff845427` |
| `domain/quality_execution/models.py` | `e421c569e89c746795d60d9acbbf87fce4324eef360c8c950713c2af64c3d517` |
| `pdos_next/quality_result_bridge.py` | `28eef312b51350f1085329c59a45d3dd28efafbda0b25a466dc0ce6c791d3077` |

Domain file paths in the table are relative to `pdos-next/server/pdos_next/`.

## Confirmed and already corrected during review

The first draft extracted Change Receipt actor from `authority_snapshot.actor_id`. B stores the actual `professional_authority.assess` result, whose top-level person field is `subject_id`; `actor_id` exists only in an internal fingerprint basis. That expression produced NULL and rejected every legitimate Change create/impact transaction. Root corrected it to `authority_snapshot.subject_id` before the snapshot above. The series `owner_id` is not an alternative: B retains the original owner, whereas a later impact can be computed by another currently authorized named person. Sources: professional authority service around 533–550; B service 636–669.

## Remaining actionable invariants

### 1. Change assessment history must be an exact ordered prefix

The draft's impact branch, around 177–186, checks the exact final captured graph, an array length increment, and JSONB array containment `new @> old`. Containment does not preserve order or multiplicity. For example, old `[A,B]` and forged new `[B,A,D]` satisfy containment and length while rewriting order. The final graph can remain the exact valid new capture. The pure handler instead uses `(*request.assessments, assessment)` (change-control handler 475).

Minimum fix: require an actual array and compare every old indexed entry to the corresponding new entry; retain the final exact graph/scope/expiry checks. Also restrict `change.request.create` to revision 1 with an empty assessment array. The model currently allows an operation=create successor, so a forged revision-2 create with a matching Receipt bypasses the impact-only append guard and resets assessment history. This is not a public service route: B only creates an initial version and only appends via impact.

The last assessment's `request_revision` should equal `NEW.previous_revision`. Its `computed_at` is the graph's captured time, not the saved row's `created_at`; comparing those two clocks for equality would reject valid service output (rules `compute_impact`, around 183–190).

### 2. Merge must require every source successor and every alias move

The Issue atom guard, around 153–162, locates the target by input `issue_id` and shared intent/writer, then proves its one Receipt. It does not require each `input_snapshot.sources` entry to have its exact same-transaction source successor/tombstone, and it does not require those sources' FailureMap rows to move to the target.

Concrete incomplete write that the current checks permit: create a target merge successor containing the union and its correct Receipt/Audit/Outbox, but omit a source merge successor; or write both successor records but omit moving their FailureMap rows. In the latter case, the unchanged map still has a valid FK to the source Current, and that source tombstone deliberately retains its failures. No map trigger runs on an omitted UPDATE. Both outcomes break the canonical failure alias ledger while preserving the currently checked Receipt.

Minimum fix: a deferred merge atom must validate each exact source id/previous revision listed in the input, its new successor with the same intent/writer and `merged_into=target.issue_id`, and all aliases belonging to those sources now resolving to the target. The target's preserved full FailureRefs should contain the exact union. A's actual `_record` already writes all `mutation.changes`, advances their pointers, and then moves source mappings (service 472–620), so this fits the legal transaction. Attach alias/merge cross-row checks deferred; they depend on final pointers and all rows being present, not intermediate flush order.

### 3. Alias membership must preserve the full FailureRef

`protect_quality_failure_alias`, around 117–119, tests only `failure_identity` membership. Model checks bind the JSON identity and product/project, but do not bind its method, criterion, sample, coverage, executor, or source to the target Issue failure. Thus an inserted map can claim the same identity while storing a different FailureRef, and future UPDATE immutability preserves that wrong initial payload.

Minimum fix: require a target snapshot failure exactly equal to `NEW.failure`, not merely a matching `identity`. The current A service stores `selected.model_dump(mode='json')` in both the Issue and mapping, so full JSON equality is compatible. The same exact membership should connect EventFailureLink.failure to its fixed referenced Issue version; the existing scoped Issue FK alone does not assert that the selected failure is present in that Issue.

### 4. Non-compute EventLinks need the event action's exact projection

The event atom branch, around 191–207, correctly checks actual Outbox/Receipt identity, actor, correlation, type, and a failing measurement in the fixed projection. For `test.result.compute`, it also fixes the projection directly through the Receipt. For import/review/disposition, however, it accepts any projection with the same logical Run scope and matching link-supplied basis hash; it does not tie the chosen projection to that event's immutable `test_result_actions.projection_id`.

A Run can have earlier partial and later final projections. A forged link can pair a later review/disposition event with an earlier same-Run failing projection. Composite FKs ensure common tenant/product/project/request/run, but not equality of event-action projection or measurement basis. This can manufacture a claimed event-to-failure association that the real bridge rejects: `quality_result_bridge.verify` recomputes the exact archived Run basis and numerical results (around 150–179).

Minimum fix: for these three operations, require the actual `TestResultActionFact` whose `next_run_version_id` equals the Receipt subject and whose scope/operation/actor match, then require its `projection_id=NEW.projection_id`. The existing result atom already ties that action's projection to the result successor (migration 0019 around 62–97). Do not require `projection.run_version_id=NEW.run_version_id` for every operation: legitimate review/disposition reuse the earlier immutable numerical projection, and the bridge explicitly allows this when the full numerical basis agrees.

## Verified compatible choices and limits

- Issue Receipt actor `writer_id` matches A's actual current named signer; its retained `owner_id` is not substituted. Policy import actor `owner_id` matches the actual trusted-import row creation and host wrapper.
- The last Change graph is the complete `GraphSnapshot`, so comparing it to `capture.graph_snapshot` is appropriate; it is not merely a graph Ref. Captures are prepared rows in an earlier UOW and are intentionally not required to share the later impact Receipt. Impact Version/Current/Receipt/Audit/Outbox must remain one transaction; capture survives an impact rollback.
- Current pointer exact scoped target, continuous predecessor, and no-delete checks match the service patterns examined. This review did not verify actual trigger installation, enabled state, RLS, grants, or SQL execution: the file remains a draft.
- Suggested negative/positive database checks belong to root's eventual migration validation: ordered-history tampering/create successor; merge missing source/mapping; forged alias/full failure membership; stale same-Run projection association; real two-Issue merge; real create/impact by a non-owner named signer; legitimate review/disposition reuse of the fixed projection.
