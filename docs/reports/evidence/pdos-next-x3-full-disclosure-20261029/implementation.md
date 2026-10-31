# X3 complete initial disclosure: offline capacity evidence

Frozen against HEAD `28bacbb7d8be01b50296004a66891ab9892d30f4` plus the exact
current-source SHA-256 fingerprints in `sizing.json`. Only the new test listed in
`manifest.json` is proposed for integration. No existing source, route, database,
KMS, network service or real model was changed or accessed.

## Scope conclusion

The 32k stop is the intended route-capacity boundary, not an ordinary-result
cleanup defect. Context design §4.2 defines `F=min(W-max_output_tokens-4000,64000)`;
§6.1 conservatively assigns unknown windows 32k and puts an explicit window on
the existing T1 model configuration. §6.2 forbids discarding required context.
The existing per-call disclosure contract (`disclosure.py`) retains every tool
callable without a skill, including T2 preparation. Its definitions, descriptions,
output schema, system prefix and skill directory cannot be silently removed to
fit a smaller route.

The reviewed prior evidence is specific: combined `x3-README.md` lines 25–34 has
the complete 61-tool 32k refusal, but its positive long run uses six restricted
existing READ specs (five main, one child). There was no complete-face positive
long-run proof in the reviewed X3 evidence. This stage fills that offline test
coverage gap. It makes no production algorithm change.

The current initial face has 61 definitions from 171 registered specs. System is
2,850 estimated tokens; tools plus unchanged output schema are 27,622. At the
15% first-call margin, fixed admission is 35,043, above the 32k route's F=26,976.
Removing only schema `title` would still exceed F. Removing descriptions to fit
would lose required usage/boundary information and was not adopted.

## Added evidence

`test_context_x3_full_disclosure.py` is self-contained and imports production
modules only. The unchanged `AgentKernel.execute` enters the registered 小Pai
graph; each fakeprovider call receives exactly the same original 61 definitions,
original system/skill directory and `WireAgentOutput` schema. Production
`fit_messages`, `protected_result`, `record_disclosure`, `handle_for` and
`page_view` make their original decisions. The fake read ports supply explicitly
synthetic receipt/evidence/error controls and nine ordinary capacity results,
each below the original tool cap. They do not claim native domain reads or PG
provenance. Only four registered tool names are executed: `category.read`,
`category.parameters.list`, `assistant.extract` and `result.read`.

| Declared synthetic W | F | First fixed admission | Cleanup before→after | Saved | Preserved latest batch |
| ---: | ---: | ---: | --- | ---: | ---: |
| 64,000 | 58,976 | 35,043 | 70,600→56,134 | 14,466 | 3 |
| 64,000 | 58,976 | 35,043 | 60,289→45,818 after explicit page restore | 14,471 | 1 |
| 200,000 | 64,000 | 35,043 | 70,600→56,134 | 14,466 | 3 |

Each cleanup saves at least 20% of its F. The 64k route still honestly reports
`fixed_over_half=true`; the 200k route reports false. The test checks every
individual cleanup's latest batch, rather than incorrectly treating a former
three-result batch as the latest after the later one-result `result.read` call.

The full run makes six scripted provider calls and 13 READ calls before a human
wait. It preserves all nine full ordinary results in `tool_results`, the original
synthetic receipt, evidence rows, error, current question/constraint/citation,
progress on rounds 4–5 and exact explicit page reconstruction. Old, irrelevant
synthetic transport text provides removable pressure without creating business
facts. A replacement in-memory Host/provider resumes the same checkpoint with
one model call, no repeated READ and no regrowth of omitted views. The two
negative cases retain unknown-window and explicit-32k refusal before any
fakeprovider or READ call.

## Validation and remaining boundary

- `pytest.txt`: all four new cases passed; all DB/Temporal environment targets
  were explicitly removed; no `.env` was loaded.
- `ruff.txt`: passed with `--no-cache --config pdos-next/ruff.toml`.
- `sizing.json`: exact per-call budget segments/cleanup, all 61 names, schema,
  system and registry digests, and current input fingerprints.

These are deterministic offline mechanics checks with a memory checkpoint and a
scripted provider. They do not claim real provider tokenizer/window support,
quality under irrelevant content, 61 tool executions, actual PG/Temporal restart
or formal X3 acceptance. Existing restricted PG/Temporal evidence remains
separate. Context design §X3 still requires a human-maintained evaluation set
covering long replay, relevant-but-useless distractions, numbered lookup and
cross-turn constraints, compared under two F values. That trusted-root set was
not created or modified. Actual route support/configuration and real-model
evaluation remain root/user-owned external prerequisites.
