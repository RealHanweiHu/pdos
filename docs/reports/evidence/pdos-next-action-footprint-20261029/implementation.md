# I14 action footprint: separate frozen increment

This package is independent of the F knowledge footprint manifest. It modifies only `enterprise_search/action_sources.py`, adds one pure test file and one native PG/Temporal test file. It creates no table/migration, grants, source selection, default execution binding or qualification. Root alone applies and runs PG/Temporal.

## Confirmed guard path

`AssistantReadAdapter.guard_action()` special-cases `verification.preparation.record` when a frozen verification_action exists: it calls `check_action()` and returns before the generic carried/unbound guard. `check_action()` rechecks the parent proof via `action_sources.capture()`. Before this increment, capture reauthorized and audience-checked only the selected citation IDs. `verification_candidates.record()` again called capture using that selection, so the same gap existed for a new child read introduced after the action started.

## Minimal change

Capture now passes the complete actual `ledger.carried()` dictionary to `current()` and `_audience()`. The selected dictionary remains unchanged and is still the sole input to `discussion_sources` and its actual root proof. Execution references and `read_set` remain exactly as before. Reopening, native preview, confirmation and later request adoption already reuse capture through recheck, so they repeat the full context check.

An unquoted private/customer context that cannot cover a shared target is rejected. A real private owner target can continue under the current ordinary RLS. The change never silently selects another source, creates a citation, broadens the Run's read_sources, or claims historical discussion is an applicable execution method.

## Verification prepared

115 pure action/candidate tests passed (110 existing + 5 new). Explicit `--config pdos-next/ruff.toml` passed. Three native PG/Temporal cases collected without DB access:

1. Real parent search/extract reads shared A plus private B but cites A. Native HTTP action start to an actually category-visible Build must reject before creating a Run, with `assistant_action_audience_widened`, no model retry or domain write.
2. The parent initially reads A only. The child action then genuinely searches/extracts private B and its real model response attempts to copy B into candidate reason. The special guard must not allow a shared candidate/event or domain row; the actual model ledger and specific rejection reason are checked.
3. A natively created owner-private Build accepts the same full readable discussion under native T1, while selected citations remain A and no B execution binding/read_source is added. The resulting actual preparation stays owner-private.

No PG or Temporal execution occurred here. Root must run these and the existing actual action Temporal regressions. A draft fixture failure is not evidence of a security pass. This package does not establish full design completion, real-model qualification or production acceptance.
