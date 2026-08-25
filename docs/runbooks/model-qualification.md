# Model qualification release gate

This runbook is the only supported path for adding a configured model to the tenant-visible
candidate pool. The checked-in suite and publication threshold are trusted inputs; the runtime and
the evaluator do not modify either one.

## 1. Configure one candidate

Set that provider's server-side base URL, model, and credential in `.env`. Never paste the
credential into a qualification report, issue, commit, or browser form.

## 2. Run the complete suite

From `server/`:

```bash
uv run --python 3.12 python -m scripts.evaluate_model --provider minimax
```

The command prints a secret-free JSON report and exits non-zero unless every checked-in case
passes. It deliberately has no output-file or publish option.

## 3. Review before publication

An operator reviews every case, confirms the provider/model identity, and checks that the report's
`suite_version` and `suite_digest` match `golden/model-gateway-v1.json`. Failed, skipped, partial, or
older-suite reports are not publishable.

## 4. Publish with a reviewed code change

Only after review, add or update the exact provider/model entry in
`server/golden/model-qualifications.json`. Set `status` to `passed`, preserve the report's exact suite
identity, and submit the minimal diff through normal code review and CI. The application starts with
an empty candidate pool when no reviewed qualification exists.

Changing a model, provider, suite case, threshold, or prompt requires a full rerun and a new reviewed
publication. Runtime processes and Agents never write these files.

## 5. Activate the reviewed model in production

The current production release policy is intentionally narrow: the default provider must be
`minimax`, the model must be `MiniMax-M3`, and the effective base URL must be
`https://api.minimaxi.com/v1`. At least one server-side MiniMax credential must be configured. The
credential may use the primary or provider-specific environment variable; neither value is exposed
through the governance API or browser.

Run `make production-preflight` before building or deploying. The preflight fails closed unless the
environment resolves to MiniMax M3 and the exact provider/model pair is present in the checked-in,
suite-matched qualification file. This check does not replace the real evaluation and human review
in sections 2–4.

After an explicitly approved deployment, verify all of the following before declaring AI enabled:

1. Owner/Admin model governance returns MiniMax M3 as an eligible and selected model.
2. One synthetic `/api/ai/chat` request succeeds through the public BFF without exposing a key.
3. The matching `model_invocations` row records provider, model, model version, tokens, latency,
   prompt version and status.
4. Removing the credential restores the visible fail-closed degradation path without a provider
   call or business-table write.

Rollback uses the previously verified release SHA. A model failure never authorizes bypassing the
qualification gate, changing the trusted suite, or granting the Agent a business-table write path.
