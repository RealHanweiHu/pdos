# Wave15 final schema preparation — static review

Result: no new high-risk blocker found in the reviewed version for the currently supported one-command tenant UOW. This is a static conclusion, not PostgreSQL, migration, HTTP, or transaction acceptance. No production/test/public file was modified and no database, pytest, or HTTP operation was executed.

Reviewed inputs:

| Path | SHA256 |
| --- | --- |
| `pdos-next/tools/wave15_schema_guards.py` | `7598d5c97f774822f7fc8ed1510e11bc835f9ab1ffd81d8fb55f27d62e2cdbe1` |
| `pdos-next/tools/wave15_schema_prepare.py` | `e7c8e85535beee692cb9b02ebe858c20b2bd1f804e207aaf197721b0a3652255` |
| `domain/quality_execution/models.py` | `e421c569e89c746795d60d9acbbf87fce4324eef360c8c950713c2af64c3d517` |
| `domain/quality_execution/service.py` | `284f5749ca953ec24127b6595f263f0165faa5d1992095cb4b7639deff845427` |
| `domain/quality_execution/api.py` | `2e0a32e3d98aaec013ad1b65d74b5d73f760fbb5f04f7d51465ede767405a1c8` |
| `domain/change_execution/models.py` | `cf0961f9ac8160430b6075e3dfecbfa7bad1493486c052b81e93165218607679` |
| `domain/change_execution/service.py` | `40448bde0b3cae0bb944e4e68ad41a4d5ec3047b137917794741c1bed04cc69f` |
| `domain/change_execution/api.py` | `fcd8d37a402a95dd40bee65c92cab56d97d753ed4b8fb7834f9be67b9f1325af` |

Domain paths above are relative to `pdos-next/server/pdos_next/`. Historical findings in `schema-guard-review.md` remain unchanged; this document records their reviewed resolution and the later EventLink revision clarification.

## Checks completed without executing the preparation script

AST extraction and Python compilation passed for both tools and the literal generated migration source. The preparation tool itself was never imported or executed: its top-level body opens an admin connection, verifies actual head, and creates migration files.

The extracted generated policy statement has normal SQL double quotes around the table, without literal escaped backslashes. The nine `CREATE TABLE` statements match the `draft.columns` insertion order, and every FK to another new table points to a table created earlier; reverse table order therefore removes new dependants before their parents. The two model hashes exactly match `schema-offline-draft.json`. Immutable and pointer sets together cover all nine tables, all pointer function names exist, and every atomic table is immutable.

SQL/PLpgSQL was reviewed manually for column/function names, operator grouping, null handling and trigger timing. Python compilation does not validate PostgreSQL function bodies; actual server compilation and migration/model compatibility remain root-owned checks.

## Atom groups and legitimate flush order

- Issue/Policy/Change atom triggers are `AFTER INSERT DEFERRABLE INITIALLY DEFERRED`. Their exact Current and Receipt/Audit/Outbox checks occur after the service has flushed all rows and common execution has appended the sole common receipt group. Requiring Current during an immediate Version insert would be wrong; the final draft avoids it.
- A's merge mutation saves target and source immutable successors, advances and flushes all their pointers, then updates FailureMaps. Its immediate map guard therefore sees both final merge pointers at mapping-update time. The deferred atom then checks the complete listed source successors and all target failure mappings. Each source resolves the same target row and proves that target's one receipt; it does not demand additional source receipts or events.
- Missing/empty merge sources now reject explicitly; self/duplicate sources and unlisted successor rows reject. Missing exact predecessor, source successor, Current, capture, receipt, or event action cannot silently become a positive result: checks use `IS NULL`, `NOT EXISTS`, `IS DISTINCT FROM`, and explicit JSON shape/length checks. Invalid JSON array shapes/casts may raise a database error instead of the tailored message, but do not bypass the transaction guard.
- Parentheses now surround both JSON operands of the merge `@>` expression, avoiding the earlier boolean-arrow operator precedence error.

## Failure identity and result event provenance

FailureMap still requires the complete original FailureRef to exist in its current target Issue; moving a map preserves that JSON and increments its epoch. EventLink uses equality of all FailureRef fields except its `run` object, and separately retains the same logical Run id. Its model check binds the link's actual Run revision and measurement identity.

This distinction is required by the frozen A test `test_fixed_failure_replay_across_title_key_and_later_event_keeps_one_created_receipt`: a later review event records a new Run revision for the same immutable measurement/stable failure identity while the Issue and map retain their original failure version. Requiring whole-JSON equality for EventLink would reject that legal delivery; the final draft permits only this retained Run-version distinction.

Non-compute events now require the exact scoped `TestResultActionFact` linking that event's Run successor to the selected projection. Review/disposition may legitimately reuse a projection computed against an earlier Run version. The draft retains this compatibility while preventing an arbitrary earlier same-Run projection from being relabelled as proof for the event. Missing action is an explicit `NOT EXISTS` rejection. Compute events remain tied directly to the projection Receipt and its exact archived Run version.

## Change capture, versions, read sets and API ownership

Create is revision 1 with empty assessments. Impact is a successor, has an exact scoped predecessor capture, preserves the ordered old assessment prefix, appends exactly one assessment, and embeds the complete exact capture graph. Capture expiry is checked against saved Version time. Graph `captured_at`/assessment `computed_at` are earlier capture clocks and are not required to equal impact save time. Receipt actor is the actual professional snapshot `subject_id`, independent of the retained series owner.

Model constraints pin capture scope/Change row/revision, preparation revision/status, owner-key uniqueness, bounded lifetime, nature and read-set size. The service remains the owner of current SourceRead completeness/ACL/hash/original safety, private audience, issuer/professional/runtime epochs, exact-key replay and post-IO rechecks; SQL atom checks are not claimed to replace those current external-authority checks. `prepare_capture` merges authority, request and actually read owner sources without truncation, refreshes all IO-sensitive guards, and confirms the current Change before a new capture insert. An old exact key returns the fixed historical timestamps and never extends expiry.

Both APIs use host authentication and tenant UOWs; Command inputs reject a path/product mismatch. Change capture is a separate recoverable UOW, with no new confirmation or receipt. Later impact writes Version/Current and common Receipt/Audit/Outbox atomically. Rolling back impact must leave the previously committed capture intact. Unopened ChangeOrder/implementation/effectivity/release capabilities remain outside these routes.

## Migration and downgrade boundaries

The preparation tool requires completed Wave14 selection, verified target state, actual `next_0022`, and unchanged model hashes before exclusively creating `schema_0023.py` and the new migration. Upgrade adds the three parent scoped unique constraints, creates new tables/indexes, defines functions, enables/forces tenant RLS, grants only the required app permissions, installs lifecycle/immutable/pointer/atomic triggers, and revokes Agent table writes. Current and FailureMap rows have UPDATE permission needed for their actual CAS/locking; immutable version/capture/link rows retain only SELECT/INSERT.

Downgrade first refuses any retained row in any of the nine tables, including prepared captures. For an empty prebusiness rollback, it drops tables in reverse FK order, then drops functions in reverse definition order with the helper's correct eight-argument signature, then removes parent unique constraints after new FK dependants are gone. Dropped tables remove their attached triggers/policies/indexes. The shared lifecycle/retained functions are not dropped.

Remaining validation belongs to root: actual head/target verification; PostgreSQL compilation and up/down/up; model/schema compatibility including parent uniques; trigger/RLS/grant/catalog coverage; real create, duplicate later-event delivery, two-Issue merge, Change capture/impact and rollback transactions. No claim of those checks passing is made here. The exact-Current atom contract is scoped to one advancement per logical series in a UOW; no multi-command batch/create-and-revise transaction is exposed by these APIs.
