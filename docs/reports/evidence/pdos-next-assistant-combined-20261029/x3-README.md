# X3 long-run Temporal verification draft and retained-batch counter delta

Status: staged only. Live files and the frozen X3/observability stages were not changed.
No database, Temporal service, real model, embedding, network or trusted evaluation corpus was used.

## Apply order and source identity

Apply after verification combined → depth layers → frozen X3 → final observability
admission/runtime + process/UI changes. `manifest.json` records exact dependency SHAs,
every added file and the single modified runtime file. The patch applies to repository
relative paths. `git apply --check` passed against an independent copy of its exact base.

`context_runtime.py` base is frozen X3
`b38674743e12432f8dd80faccceb766236bc051fbf96bedcffcbfb73bfd8d4eb`.
Its only delta pre-counts the complete newest tool batch before a successful cleanup
can break the loop. Previously `retained_latest_results` could report zero while three
latest results remained intact. This is an actual public-metrics bug, not a reason to
change what cleanup protects. No limits, cleanup order, ledger content or permissions change.

Do not copy older Host/Graph/Bootstrap dependency snapshots over root's newer lifecycle/cache
fixes. This stage changes none of those files; its only existing-file patch is the counter.

## Test-only capacity surface

The normal initial production disclosure has 61 tools in this baseline. Its unchanged
fixed admission is 34,763 tokens, above a 32k model's F=26,976 with output reserve 1,024
and tool reserve 4,000. It correctly stops before the provider. Both explicit 32k and
unknown-window fallback rejection are preserved in new pure negative cases.

The actual-PG draft therefore uses an explicitly restricted subset of six existing
READ ToolSpecs, with original names, input schemas, versions, limits, permissions and
SYSTEM_BASE/Skill directory. Main sees five READs; `assistant.passage.read` remains
child-only. This is restricted registered-surface capacity verification, not proof that
the full production surface can run at 32k.

The category parameter reader first executes the original native reader, including
schema validation/current RLS. An empty native `parameter_ids` selector returns actual
empty results. Only then does a test decorator remove volatile transport `as_of` and
append `synthetic_capacity` data explicitly labeled `context-cleanup-test-only`.
It never invents business data or evidence. Each ordinary result is under 3,936 estimated
tokens, with 3,300 synthetic wide characters. No production ToolSpec is added or relaxed.

Pure arithmetic now uses the actual `handle_for`/`page_view` envelope grammar:

| Step | Admission tokens |
| --- | ---: |
| Initial restricted surface | 5,052 |
| First three ordinary capacity results | 16,782 |
| Next three ordinary capacity results | 28,338 (>26,976 F) |
| After real cleanup algorithm, replacing two old views | 21,171 |

Net savings are 7,167 tokens, above ceil(20%F)=5,396. Latest batch remains complete;
the counter now reports three retained results. Pure tests also fit the actual page
framing, round 4–6 deterministic progress and a third capacity batch without losing
previous omission handles. These numbers are synthetic admission estimates, not measured
provider tokenizer or PG/Temporal performance results. `sizing.json` contains the segments.

## Actual PG/Temporal test draft (not run)

`tests/agent_kernel/test_context_x3_temporal_pg.py::`
`test_actual_http_temporal_32k_cleanup_preserves_ledger_then_worker_resume_does_not_regrow`

It reuses the existing isolated `setup`, guarded checkpoint URL, actual HTTP start/wait
helpers, offline child provider, real index projection, TemporalPort, XiaopaiWork,
KernelActivities, BoundHost/KernelStore and PostgresSaver. It performs no direct
graph invocation, fake Store, memory checkpoint or forged model/tool ledger insertion.

The initial material is registered by an actual native Human command. The category READ
first executes native RLS and then reloads that real prior Human receipt under the
current Run transaction. Search and isolated extraction produce actual verified rows.
A malformed native pagination cursor produces a real post-scope-check tool error.
All three protected shapes must survive cleanup unchanged.

The model requests two three-result capacity batches, then a real `result.read` of a
cleanup handle, then a third capacity batch. The server must re-enter the original
reader to validate the page. The expected source-call count is nine capacity reads +
one actual cursor error + one explicit revalidation. Search/extract each execute once.
The test checks every full capacity body in both durable AgentToolCall rows and
LangGraph `tool_results`, alongside reduced model views and ≥20%F observed cleanup.
It checks deterministic progress at turns 4, 5 and 6 without another model call.

At the real `needs_input` checkpoint it shuts down the first Worker, creates a fresh
Activity and provider, and answers through the original authenticated HTTP endpoint.
The resumed provider must derive completion from persisted messages; no prior local
phase state exists. It must make one additional main call, no child call or repeated
source callback, retain old omission views, keep pre-wait ledger rows unchanged,
complete with a real citation, and reuse the completed Run on POST replay. Actual
workflow history must contain two activity schedules and no source/capacity bodies.
The original process endpoint must expose cleanup metrics without source bodies and
still reject the peer requester.

This is currently an executable draft. Root must run it in the already-verified isolated
PG/checkpoint/local Temporal environment after applying the combined candidate. Potential
runtime failures must be fixed from real evidence, not by reducing the expected preserved
data, skipping source guards or changing production fallback/window limits.

## Verification performed

- 51 pure regression tests passed; one actual PG/Temporal case skipped intentionally.
- Six Python files parsed successfully (five deliverable sources/tests plus pure runner).
- Ruff passed for all deliverable Python files and the runner.
- Patch check passed against its exact frozen X3 runtime base.
- `run_pure.py` explicitly unsets every DATABASE_URL variable and PDOS_TEMPORAL_* variable.

`pure.txt` records the final run. No actual PG/Temporal acceptance is claimed.
