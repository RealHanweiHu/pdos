Retained execution review — Wave14 scoped test handoff

The retained port now compares `fixed_run_sha256(current_run, plan)` with the immutable original Start. This closes the earlier gap where a hash-valid result snapshot could change fixed actual configuration, cavity, planned configuration, method, criterion or sample/item coverage. The new test exercises detached candidate rows and never updates immutable Run history.

Root repaired two additional boundaries found in this read-only review:

- Historical professional recheck retains every original `snapshot.fact_refs`, including negative facts. It recomputes current Principal/Grant, Current pointer and issuer/source epochs at the saved Start eligibility clock. Only later independent facts inapplicable to the original operation, purpose and role matrix may be ignored; current commands continue using their full current authority scope. The deep Build → sample readiness → actual method → test-resource route has the retained mode wired through.
- A hand-entered Artifact lacks a per-source security epoch. Root added `next_0020` rather than changing applied migration history: withdrawn Artifact identity is terminal. The new test withdraws the original Start event source, checks retained denial, and requires the database to reject a same-identity active revival. Existing OriginalSecurity monotonic epoch and original restoration rules are separate.

Six PostgreSQL test functions are written in `pdos-next/server/tests/test_retained_execution.py`:

1. A genuinely API-saved Start followed by explicitly simulated late evaluator reads after the window and after the 40-minute professional eligibility horizon. The history stays provable, its original timestamps/effects stay fixed, and historical Build projection grants no present action. Adding independent results-only credentials after Start remains harmless. This is not evidence that 41 real minutes elapsed or that real professional qualification passed expiry acceptance.
2. Six closed, hash-valid detached candidates changing the fixed configuration/method/sample-item basis are refused.
3. Current physical resource occupancy epoch and sample usage sentinel epoch changes invalidate proof. Original source withdrawal blocks; terminal-source ABA revival is refused by the real DB trigger. Savepoint rollback restores only the test's temporary changes, without disabling any guard.
4. Test-resource issuer disable and reconfigure increment the issuer epoch; neither state revives the original retained proof.
5. The original manufacturer qualification is revoked and restored through trusted import versions; its Current epoch advances twice and the old proof stays invalid.
6. A new sourced actual configuration deviation is recorded through the real common T1 API; it blocks retained qualification without rewriting planned configuration or existing sample identities.

Every retained read compares complete effect-row hashes before and after: material holds, shared ResourceOccupancy, TestResourceReservation, SampleRunUsage, both asset/sample sentinel epochs, BuildStart, Run versions/current pointer, Receipt, Audit, Outbox and RequestKey. Intentional source/credential/configuration mutations precede that read baseline. The tests never call reserve or stage from the proof path.

Only the new test and this retained evidence were written by this subagent. Ruff, format and Python compilation passed; no PostgreSQL connection, PG test, public test, or repeat of the frozen 87 measurement pure cases was performed. Root owns migration application, actual HTTP post-window evidence and PG/combined validation. Exact observed hashes and nodeids are in `retained-static-checks.json`; these reviewed-source hashes are observations, not a claim about root's final frozen candidate.
