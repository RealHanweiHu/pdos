# Wave21 completion profile dispatch — isolated staged handoff

Status: staged source only. The running server/tests were not modified. The copied original integration baseline is `3e645ba35aaed5504a3ee9f2e1f237d46e4dc87ac01f1044d2105b255038f850`, and it still matches the real server file. All 309 other copied Python modules match their source baseline. No symlink was used.

## Host configuration

`configure_integration(engine, *, synthetic_completion_profile=None, synthetic_completion_profiles=None)` preserves the existing single-profile delegation and unconfigured default. Both arguments non-null are rejected. The new plural input is an explicit nonempty Python list, at most 20 profiles; each is the existing closed CompletionProfile DTO or its full dictionary. No new public payload, profile selection field or source/qualification flag exists.

The plural path normalizes and validates the entire list before any publication: exact `(tenant_id, product_id, project_id)` keys are unique, each full `(scope, issue, CAPA, action, executor, purpose)` issuance key is unique, all entries retain the existing exact source requirements, and existing requested scopes must have the same complete data and actual typed registration/epoch. Same-scope different data or malformed registration is a conflict. Identical existing profiles are reused as the original `_Profile` object without increasing their epoch; unrelated existing registry objects remain untouched. The server's new explicit whitelist does not automatically select unlisted scopes. Root must include any old scope it intends to continue dispatching. The legacy single branch retains its original explicit re-registration/epoch behavior.

New scopes use the actual `quality_followup_bootstrap.configure_local_profile`, including its independent target verification. This startup path is not a DB transaction: complete input/conflict validation happens first, and any later actual target/registration failure is raised before installing the new follow-up Runtime. No issuer or professional authority is created by this registry.

## Read dispatch

The returned startup classifier accepts the unchanged callback signature:

`assess(s, ctx, product_id, basis, action, completion, *, policy_snapshot, observation, write=False)`

It requires the actual configured engine (`s.get_bind() is engine`), actual server Context, named actor=requester, no agent Run, and exact `basis.scope.tenant_id/product_id == ctx.tenant_id/product_id`. It then selects only `(actual ctx.tenant_id, supplied server product_id, server-derived basis.scope.project_id)`. Unknown scope returns `COMPLETION_PROFILE_SCOPE_MISSING` / 503; a caller/basis/engine mismatch returns `FORBIDDEN_SCOPE` / 403. There is no first-profile fallback, owner Context substitution, Session.info cache or cached positive assessment.

Each call delegates to the existing actual `bootstrap._assess`. Its native publication receipt, exact 12-field classification line, original action/completion/nine-field event, caller source ACL, fixed scope/purpose, policy, source refresh and current deadline remain unchanged. The selected actual profile identity and monotonic epoch are checked before and after that IO. Disable/replacement/epoch drift produces SOURCE_STALE. A classification/source-owner refusal is propagated rather than replaced by profile presence. This only proves controlled synthetic investigation classification; it does not prove physical remediation or action fulfillment and never grants professional qualification.

## Root application seam

After the preceding runtime checkpoint is sealed, Root can copy only these two staged files:

- `.local/wave21-completion-staged/pdos_next/quality_followup_integration.py` to `server/pdos_next/quality_followup_integration.py`.
- `.local/wave21-completion-staged/tests/quality_followup_root/test_completion_profiles.py` to `server/tests/quality_followup_root/test_completion_profiles.py`.

Root owns `create_app` / serve tooling. A matching optional `quality_followup_synthetic_profiles` argument can pass the explicit list unchanged to `configure_integration(..., synthetic_completion_profiles=...)`, with the same single/plural mutual-exclusion rule. Production mode without explicit local profiles remains unconfigured. No API route or registry operation was added in this task.

## Checks / evidence

Forty owned pure cases passed in 1.07 seconds against the isolated package, with no conftest, no connection, no bytecode writes to original helper files and no public test/build/HTTP/service restart. Ruff, format, AST and an exact active-package import check passed. Real SQLAlchemy Session/UOW objects cover dispatch; target/native-source verification uses explicit pure substitutes and does not attest the real DB marker, original files or professional qualification. Final raw commands/log hashes and the repaired initial fixture diagnostic are in `completion-profiles-check-result-v1.json`. Exact source paths and hashes are in `completion-profiles-source-v1.json`.
