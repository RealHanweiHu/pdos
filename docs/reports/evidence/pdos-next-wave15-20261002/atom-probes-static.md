# Wave15 rollback-only atom probes — static delivery

Status: implemented and statically checked only. The tool was not imported or executed, and no database, HTTP, pytest, migration, backup, original object, or retained business row was operated on by this delivery. Existing frozen service, test, and schema files remain untouched.

Tool: `pdos-next/tools/wave15_atom_probes.py`

SHA256: `5e837bf746c43558499f5da54af98a00a4df91756641f8257ad2544c6bbacb1c`

## Root-owned invocation contract

Run from `pdos-next`, only against the already verified task-local synthetic environment, after successful local demonstration rows exist and concurrent work on the selected Product has stopped:

```text
server/.venv/bin/python tools/wave15_atom_probes.py \
  --tenant <tenant UUID> --product <product UUID> \
  --issue <logical Issue UUID> --change <logical Change UUID> \
  --policy <optional current PolicyFact row UUID> \
  --capture <optional fixed GraphCapture row UUID> \
  --merge-source <optional second logical Issue UUID>
```

The four scope/identity arguments are required and parsed as UUIDs. Policy/capture selections are optional: without overrides, they are derived only from the selected Issue's actual policy snapshot and selected Change's last actual graph assessment. No unrelated product row is selected as a substitute. An explicitly supplied missing/out-of-scope row aborts. Policy must be pointed-to Current and match Issue project/purpose; capture must match selected Change/project. Issue/Change and optional merge source must have their exact named successful Receipt. A missing optional policy/capture yields explicit skips for its dependent probes.

`--output` is optional and must name a new `atom-probes-*.json` in this Wave15 evidence directory. Default output uses a fresh UUID suffix and exclusive creation; previous evidence is never overwritten. No URL, credential, token, raw row body, source quote, report content, or raw SQL exception is printed or saved.

## Guarded execution and rollback structure

At runtime, the tool uses `verified(read_state())` before selecting the engine and before/after every probe. It fixes the original marker/container/port/URL-digest identity and rejects changes. Each probe checks actual database `pdos_test`, actual head `next_0023`, binds the exact tenant, and locks only the selected Product. Lock and SQL timeouts are bounded at 5/15 seconds; timeout is an unexpected boundary, never a successful guard result.

Every probe has an outer transaction which always rolls back, plus a nested savepoint which always rolls back. Deferred constraints are forced with `SET CONSTRAINTS ALL IMMEDIATE` after the deliberately incomplete SQL group. There is no `commit`, public command execution, receipt creation, authority import, or storage operation. Selected immutable rows, pointers, optional source Issue/pointer and full Product row (including lifecycle epoch) are hashed before the probe and again after savepoint rollback. Any difference aborts; new temporary rows are additionally covered by unconditional outer rollback.

Temporary INSERTs use fresh row/logical IDs and fresh intent/capture keys, retain actual scoped parents and existing source metadata, and repair the immediate predecessor/revision/status fields needed by the intended SQL path. These are negative raw-SQL components only: they are not valid public commands, professional facts, qualifications, or business approvals. No duplicate existing PK is used to manufacture a rejection.

Only PostgreSQL `P0001` with the exact expected frozen guard message counts as a successful rejection. The report records exception type, SQLSTATE, a validated constraint identifier if present, and only whitelisted fixed guard messages. FK/CHECK/duplicate-PK/permission/timeout/unrelated-trigger failures do not count as the intended guard passing. Raise-based constraint triggers often have a null diagnostic constraint name; the exact guard message is then the recorded proof. Unexpected acceptance also fails the tool, after rollback.

## Potential probes (14, with explicit conditional skips)

| Probe | Intended rejection |
| --- | --- |
| Issue/Policy/Change/Capture reason mutation (4) | Retained snapshot trigger, exact immutable message |
| Issue/Policy/Change Current revision jump (3) | Exact scoped target version guard |
| Issue/Policy/Change Current identity reassignment (3) | Continuous exact predecessor/identity guard; cannot fake the CAS pointer identity |
| Fresh Issue version + its matching Current, without Receipt/Audit/Outbox | Deferred named common-group guard, not missing Current or duplicate PK |
| Fresh Change version + its matching Current, without Receipt/Audit/Outbox | Same deferred common-group guard |
| Scoped temporary capture + valid successor/prefix, graph timestamp altered while keeping capture id | Exact capture graph/basis guard before missing Receipt |
| Complete two-Issue merge successors + matching Current pointers, omitted source alias movement | Exact merge alias completeness guard before missing Receipt |

The merge case requires an explicit second current Issue in the same project/purpose/audience, both open/triaged with no CAPA/root-cause/merge alias, disjoint failures, and an exact existing map ledger. Otherwise it is skipped before any merge INSERT. It preserves actual complete FailureRefs and exact predecessors, writes both scoped successors/pointers, and intentionally leaves source mappings untouched. It never fabricates a target common receipt. The guard must specifically report alias incompleteness; another refusal is not substituted.

Extra unlisted merge-version tampering, policy import/current issuer authorization, qualification/source ABA, request-level CAS, public T1 proof handling, full source-read-set behavior, and terminal Outbox rollback remain covered by the separately frozen transaction tests. They were not duplicated or declared passed by this tool. Current revision-jump probes specifically cover mismatched pointer/target revisions, while identity probes cover forged pointer identity; they do not claim a public service expected-revision race was exercised.

## Static checks actually completed

- Ruff check and format check passed on the new tool.
- Python AST parse/compile passed without importing or calling its main function.
- Static structure assertions confirmed required UUID flags, guarded main entry, two environment rechecks per probe, nested and outer rollback, force-deferred-constraint boundary, original-row/epoch comparison, exclusive evidence output, absence of commit, and exact `P0001`/guard matching.
- Receipt, graph-binding, merge-alias guard constants were checked against the frozen `migrations/schema_0023.py` text; no SQL was executed.

No runtime result or passed-case count exists yet. Root must run the tool with explicit successful local rows, inspect skipped/unexpected cases, and retain its new JSON evidence before citing actual atom-probe coverage.
