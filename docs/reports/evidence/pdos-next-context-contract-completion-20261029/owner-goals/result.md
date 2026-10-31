# P32 owner original-goal presentation after explicit source withdrawal

The authenticated owner may read only their independently recorded original goal after ordinary AgentRun RLS hides the original Run. `owner_history.goal_rows` selects `agent_work_states.body.current_goal.text`, the matching current_goal run ID, the real work-state record clock and current readable Session parent scope. It joins tenant/session/owner, requires origin=run, checks the recorded run ID and string type, and strips PAGE_MATERIAL_BOUNDARY server attachments in SQL. It does not select the work-state body, old Run body, source IDs, versions, summary, reply, candidate, tool call or event.

This reuses existing append-only owner work-state RLS and ordinary current Human/Session/category/product/proposal/project checks. AgentRun/result/event/tool RLS is unchanged. No SECURITY DEFINER, GUC switching, role grant, migration 0854 or new privilege is added. Original goal material is presentation only; it grants no source read, frozen history proof, model input, continuation or mutation authority.

GET run, Session heads/search/run pages and the existing flat run directory expose a hidden placeholder. Hidden has status=hidden and history_hidden=true, result=null, versions={}, created_at=null, real work-state recorded_at, null unknown revert/cancel state and null links with links_unavailable=true. Ordinary readable Run responses remain unchanged. Process/events/candidates/continuation endpoints retain their existing full-Run guards. All multi-query read paths use a repeatable-read read snapshot.

Legacy boundary: a historical conversation Run without its production finish/cancel work-state record remains unavailable after its full-Run RLS is revoked. Its goal cannot be safely reconstructed here. This patch does not copy private bodies, infer original state/created_at/lineage from finish time, or backfill missing history. Automated/service Runs do not produce this conversation record and gain no fallback.

## Validation at candidate freeze

- Pure owner projection/router tests plus existing Session contract tests: 19 passed, no database/model/provider.
- New native PG tests: 3 collected successfully; root alone executes the isolated PG group. Collection is not a PG pass claim.
- Ruff over the three production files and two new test files: passed.
- git diff --check on the two tracked production files: passed.

Prepared PG cases use native source registration, authenticated start and production Bootstrap.store.finish (synthetic outcome, no model). They remove only isolated fixture audience/parent access, then cover owner detail, heads, literal search, session/run/legacy pagination, peer denial, product/category revocation, process/events/candidates/continue denial, no additional Run, and the legacy missing-work-state boundary.

## Root native and browser completion

The 3 prepared owner PG cases passed in the final 57-case history/session/project/Temporal group: [XML](../pg-history-run3.xml). The 236-case final pure group also passed. The frozen production build passed, and actual deep-link/open/reload desktop/mobile checks completed: [browser result](browser-final.md). Source hashes were unchanged during the final native group.
