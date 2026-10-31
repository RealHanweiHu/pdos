# Hidden owner-goal UI freeze evidence

Hidden responses preserve the owner’s original goal, the server’s hidden message and real `recorded_at` labelled “记录时间”. The full hidden GET codec requires null unknown Run metadata, an empty result/version projection and unavailable conversation links. Personal/project Run loaders stop before event/candidate/material reads and suppress continuation, revert, save, feedback and source actions. The independent new-conversation entry remains available. Ordinary readable Run behavior remains covered by existing tests.

Existing frozen-candidate checks passed:

- Pure frontend group: 109 tests, 109 passed, zero failures/skips. [Raw output](pure.stdout.txt) · [Original completion record](pure-command-execution.json).
- Full TypeScript `--noEmit --incremental false`: exit 0, empty stdout. [Raw output](tsc.stdout.txt) · [Original completion record](tsc-command-execution.json).
- ESLint over the 11 changed files: exit 0, empty stdout. [Raw output](eslint.stdout.txt) · [Original completion record](eslint-command-execution.json).

[Exact commands and completion times](commands.md) · [11-file SHA-256 manifest](source-sha256.json).

This directory only collects already completed tool output; checks were not rerun and no application code was changed during evidence preparation. No database, model, provider, server, browser or production build was executed by this UI evidence step. Root owns the new candidate build and actual browser/deep-link validation; this report does not claim those results.
