# Initial owned pure attempt — retained failure record

Command: `.venv/bin/python -m pytest --noconftest tests/capa_effectiveness/test_common_execute_validation.py -q`, cwd `pdos-next/server`.

The original tool session 10792 completed with exit 1: **25 passed, 4 failed in 1.12s**. This file transcribes the exact outcome and failure reason from tool stdout; the full traceback was not saved as a filesystem raw log.

All four failing nodes were `test_existing_root_complete_and_link_validate_order_is_unchanged` with `quality.capa.followup.link`, for parameter values `None`, `key`, `semantic`, `conflict`. Each failed in fixture `world.select` during the real `FollowupLinkPayload.model_validate`, before `common.execute`:

`confirmation_token: String should have at least 20 characters; input_value='offline-link-token'; type=string_too_short`.

The sole fixture repair was replacement of that synthetic test token with `offline-link-confirmation-token`. No production schema, source, validation or assertion changed.

A subsequent attempt to redirect stdout used an incorrect relative evidence directory and was rejected by the shell before pytest started. It is an evidence-output path error, not another test or business result. The corrected run produced `candidate-common-validation-pure-v2.log`.
