# Wave21 completion profile dispatch — staged v2 failure recovery

Status: staged, not applied to the running server. This version corrects the v1 batch registration failure gap; the v1 manifests and logs remain historical. `configure_integration(engine, *, synthetic_completion_profile=None, synthetic_completion_profiles=None)` and the callback signatures are unchanged.

## Complete batch registration

All profile fields, scope keys, issuance keys and existing exact registrations are validated before registration. New scopes still use the actual `quality_followup_bootstrap.configure_local_profile`, which independently verifies the target on each registration. Inspection of that function confirms that its only configuration assignments are `_pdos_quality_completion_profiles` and `_pdos_quality_completion_profile_epochs`; it creates copied dictionaries rather than mutating the original maps. `safety.verify_test_target` performs target reads and makes no engine configuration assignments.

Immediately before batch verification/registration, the helper captures each attribute's actual original object or its absence. Any target verification, registration or registered-result verification failure restores those exact original objects; an originally absent attribute is removed. The original exception is re-raised. This also covers a failure after an actual registrar has published its copied maps. Existing profile objects and epochs remain identical, and existing follow-up Runtime, callback, consumed-proof callback and output-options Runtime remain untouched. A new Runtime is installed only after the whole batch succeeds. This is synchronous host startup configuration; it introduces no DB transaction, fact, Receipt or professional grant and is not a concurrent runtime configuration protocol. Restoring an unpublished failed batch does not alter successful published disable/revoke epoch semantics.

The legacy single path remains unchanged. Both single/plural non-null inputs reject; plural must be an explicit list of 1–20 full profiles. Requested existing scope data must be exactly identical, and the actual `_Profile` identity and epoch are reused. Unlisted old scopes stay registered but are not automatically added to the new callback's whitelist. Root must explicitly include any old scope required by the plural configuration.

## Current read dispatch

The callback remains `assess(s, ctx, product_id, basis, action, completion, *, policy_snapshot, observation, write=False)`. Selection comes only from actual server Context, actual bound engine, exact product and server basis project. Caller=basis tenant/product and named actor=requester/no Run remain required. Unknown scope is 503 `COMPLETION_PROFILE_SCOPE_MISSING`; mismatched context/scope is 403 `FORBIDDEN_SCOPE`. Each read invokes the real bootstrap source/classification checks, then independently checks selected profile identity/epoch after IO. No cached positive assessment, owner Context or Session.info is used. Synthetic investigation classification cannot prove physical implementation, action fulfillment or professional qualification.

## Root application seam and evidence

Root can later apply only the staged integration module and the new staged test identified in `completion-profiles-source-v2.json`, with the declared original runtime baseline SHA. The create_app/serve plural hook remains Root-owned; no public operation or caller selection field was added here. All 309 other copied Python modules remain unchanged; no symlinks or running-source writes were used.

47 owned no-connect pure cases passed in 1.08 seconds, replacing the v1 count of 40. New cases exercise the real registrar with a second-scope target refusal, exact existing object/epoch/callback preservation, all four original attribute-presence states, and registrar/post-registration failure after copied-map publication. Ruff, format, AST and exact isolated import checks passed. Commands, raw logs, exits and hashes are in `completion-profiles-check-result-v2.json`. These are pure checks with explicit target/source substitutes; no actual DB/HTTP/public build or runtime validation was performed.
