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
