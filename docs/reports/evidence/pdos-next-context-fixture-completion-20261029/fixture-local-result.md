# CTX09 / CTX12 fixture completion — local evidence

The five owned source files still match root's frozen input manifest: [verification](fixture-source-verification.json), [frozen inputs](frozen-inputs.json). This evidence-only step changed no source files.

| Check | Actual result | Raw output | Exact argv, cwd, timestamps, exit code and output SHA256 |
| --- | --- | --- | --- |
| Focused pure tests | 18 passed; 12 native cases deselected | [log](pure-evidence-run1.log) | [execution record](pure-evidence-run1.json) |
| Native fixture collection | 26 tests collected; none executed | [log](collect-evidence-run1.log) | [execution record](collect-evidence-run1.json) |
| Server fixture Ruff | All checks passed | [log](ruff-server-evidence-run1.log) | [execution record](ruff-server-evidence-run1.json) |
| Tools consistency-test Ruff | All checks passed | [log](ruff-tools-evidence-run1.log) | [execution record](ruff-tools-evidence-run1.json) |

These checks did not execute native PG tests, connect to DB, start servers/Temporal, build the frontend, use a browser, or call a real model/embedding service. Four focused native CTX09/CTX12 runs remain for root's guarded shared validation. Pure results are not native scenario acceptance or model-quality scores.

## Source ownership and implementation

- `docs/evaluations/xiaopai-v0/context-questions.json`: correct only CTX01/CTX12 `raw_estimate_exceeds_both_F` flags to false. Their raw estimates (33682 / 29836) are below both F values (48000 / 64000); materialized input, facts, rubric and F remain unchanged.
- `pdos-next/tools/tests/test_xiaopai_context_admission.py`: existing consistency test now derives each such flag from the measured raw estimate and both configured F values.
- `pdos-next/server/tests/agent_kernel/test_eval_v0_handle_candidate_pg.py`: CTX09 retains its actual result-handle/page-2/page-3 failure control; adds actual directory-object coverage, complete JSON-object boundary checks, and a separate native cursor control. The original mechanics source is scoped separately so the new directory objects do not alter that control. CTX11 is outside this change.
- `pdos-next/server/tests/agent_kernel/eval_v0_ctx09_directory_support.py` (new): register nine directory objects through native human knowledge commands. First six bind actual Q301–Q306 source objects; last three carry directory metadata without invented body facts. The natural single-result binding is evaluated separately from the independent two-page cursor coverage of six objects. Those controls cannot be combined into a claim that the original single binding met 6/9; misalignment remains partial.
- `pdos-next/server/tests/enterprise_search/test_eval_v0_source_context_pg.py`: CTX12 budget-stop branch records actual read ranges, gaps and issued citations before returning. Overlap is counted once, absent ranges remain absent, and the observed admission stop remains partial with final/full completion false. F, protected evidence policy and model-quality scoring remain unchanged.

All native writes are deferred to root's actual test execution and use existing native commands. No direct business-table fixture insertion, hidden-page body invention, golden-case change, answer-correctness scoring or real usage/latency/cost claim was introduced.
