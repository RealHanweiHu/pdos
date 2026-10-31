# CTX-09 native fixture reference/version repair

Scope: only `pdos-next/server/tests/agent_kernel/eval_v0_ctx09_directory_support.py` changed. The associated main test file, production code, question set, same-handle fragment control, natural complete-object decoding, and independent `page_size=3` cursor control remain unchanged.

## Contract diagnosis

- The retained `native-final/tests.xml` failure is `VERSION_CONFLICT`, reason `material_version_moved`. `category_service._current` emits that reason when the `supersedes.expected_version` differs from the actual current lineage version.
- The nine initial `category.knowledge.add` calls previously had identical semantic payloads. `service.execute` derives `intent_digest` from the operation, scope and semantic payload, then returns the existing receipt for a repeated intent even with fresh command/idempotency keys. Therefore those calls were one lineage; the first supersede moved it and the next supersede still expected version 1.
- `evidence.artifact.register` constructs an `Artifact` as the receipt subject. `append_receipt` records `subject.revision`, so this receipt's `subject_revision` is the Artifact revision. `source_for` checks that actual revision and uses `SOURCE_STALE` for a mismatch; it does not emit `material_version_moved`.

## Repair

- Give each initial directory placeholder a distinct synthetic slot in its definition. No undisclosed code or business body is introduced. Assert that native receipts identify nine distinct lineages and entry IDs before superseding them in actual lineage order.
- Read all six registered Artifacts through ordinary `tenant_session(..., read_snapshot=True)` with the Human actor/requester and category. Verify scope, category visibility, active status, exact literal line and receipt subject/version, then take the reference version from the persisted Artifact.
- Take `supersedes.expected_version` and returned directory entry versions from native receipts. The final ordinary scoped read verifies the actual version and source references for every current directory entry.
- Preserve six disclosed Q-301–Q-306 sources and three directory-only unknown bodies. Natural fragment boundaries still determine actual complete-object coverage. The independent cursor run cannot count as a same-binding scenario pass.

## Verification and remaining boundary

- Four selected pure checks passed; database URL environment variables were removed from that invocation. See `invocation.json`, `pure-tests.log`, and `pure-tests.xml`.
- Ruff passed for both assigned test files; see `ruff.log`.
- Source hashes are in `source-sha256.json`.
- No database, Docker, real model or embedding operation was performed by this subtask. The root session owns the next four-focused PostgreSQL run. This static result does not claim that native runtime verification has passed.
