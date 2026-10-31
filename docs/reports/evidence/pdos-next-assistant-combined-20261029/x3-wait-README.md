# X3 actual long-run wait helper correction

Independent test-only delta; no live/runtime/API/schema changes, no DB access.

Root's actual diagnostic confirmed Run `889e4985-e76e-47fc-805d-20729ed394ea`
was `waiting_input`, with no Run error; its real `needs_input` event was sequence 58.
The existing generic verification helper requested the oldest default 50 events and
assumed current Run status meant the question was on that page. `next(...)` failed.
The actual graph emits the question before committing its checkpoint interrupt, and
the Activity then commits waiting_input. This is pagination plus state ordering,
not evidence of a failed runtime or a need to reduce the preservation assertions.

Only the X3 harness now owns its wait helper; the generic verification helper is unchanged.
It follows ascending `after`/`next_cursor`, drains full pages, preserves an event seen
before the Activity commits waiting, and requires the real durable waiting status before
returning. A terminal state is an immediate failure, cursor/order inconsistencies fail,
and a fully drained waiting page without the expected clarification fails explicitly
(including model_unavailable), instead of swallowing StopIteration or hanging forever.

The PG test only changes which helper it imports. All cleanup, ledger, receipt/evidence/
error preservation, source-call counts, fresh Worker/provider recovery and process guards
remain unchanged. Root should rerun that original actual PG/Temporal test after applying.

Eight pure helper tests passed; the one actual PG/Temporal case was deliberately skipped.
Ruff and syntax checks passed. See manifest for exact live base SHA and the small patch.
Apply after the already integrated X3/counter candidate (API baseline 2a7f4ed... is unchanged).
