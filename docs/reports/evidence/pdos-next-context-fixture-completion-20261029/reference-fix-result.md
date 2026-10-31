# CTX09 shared source fixture correction

Root's first native execution failed before the directory controls: [original native log](native-live/native.log). The real `category_service.check_shared_sources` rejects `knowledge` references for shared knowledge; `Reference` also has no `category_knowledge` type. Production guards are unchanged.

Only two source files changed:

- `server/tests/agent_kernel/eval_v0_ctx09_directory_support.py`: register the six disclosed synthetic Q301–Q306 sources using actual human `evidence.artifact.register` with category visibility. Each directory entry uses the resulting actual Artifact ID and subject revision plus line 1 and its literal quote. Native receipt writer/requester identity and absence of AgentRun are asserted. Ordinary tenant/RLS Artifact reads also verify the registered active category source, revision and exact source line. Nine genuine native directory objects, three entries without disclosed body, and the separate natural-fragment/cursor controls remain.
- `server/tests/agent_kernel/test_eval_v0_handle_candidate_pg.py`: both native coverage assertions now verify the complete Artifact reference (type/ID/version/line/quote). A pure regression invokes the actual shared-source admission guard against isolated authority ports, checking the fixture reference passes, incorrect quote fails, and `knowledge` remains rejected. CTX11 logic is unchanged.

The other three original frozen inputs match their previous hashes. New source SHA256 values are in [reference-fix-inputs.json](reference-fix-inputs.json).

| Check | Actual result | Log | Exact command/execution record |
| --- | --- | --- | --- |
| Focused pure tests | 19 passed; 12 native entries deselected | [log](pure-reference-fix-run1.log) | [record](pure-reference-fix-run1.json) |
| Collection | 27 tests collected; none executed | [log](collect-reference-fix-run1.log) | [record](collect-reference-fix-run1.json) |
| Ruff (two owned Python files) | All checks passed | [log](ruff-reference-fix-run1.log) | [record](ruff-reference-fix-run1.json) |

No DB, Temporal, server, browser, build, embedding or real model was run by this agent. The original native failure is preserved; the corrected four focused CTX09/CTX12 cases await root's actual execution. Neither the source-reference fix nor pure verification establishes a complete CTX09 single-binding 6/9 scenario pass or a model-quality score.
