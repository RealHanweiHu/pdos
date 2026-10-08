# Original lifecycle first version · 2026-10-02

This package provides callable rules, strict frozen consumption DTOs, transaction-participating command staging, and a safe unavailable reversible transport. It is **not connected** to UploadedOriginal, Outbox, worker, API, or a real object store. No database, existing original, bucket, credential, model, dependency, shared service, or physical deletion was used by this package. Tests use harmless bytes and in-memory metadata only.

## Consumption baseline

The only imported shared domain DTO is `pdos_next.object_storage.types.ObjectRef`: immutable six fields `id/version/content_sha256/size_bytes/media_type/server_storage_key`, version 1, exact server-derived key. ObjectRef equality includes all six fields. This package does not add a second original-byte owner, import old application modules, or consume Build/configuration DTOs.

Read-only source summaries at handoff:

| Consumer | Read baseline SHA-256 | Required semantics |
|---|---|---|
| `object_storage/types.py` | `6a96ee13bb918473e856d1e88bf65bf93c010800b76a1431266beb63abeac737` | Exact immutable ObjectRef; ObjectStore exposes put/read only. |
| `object_storage/adapters.py` | `bb24af925be876eb2dcbcc8cb75d44ada8b20127de74f68368466de9894d6f0d` | No overwrite; verify content hash and size on read; no existing deletion/move adapter. |
| `originals.py` | `ec0d67dc50d4bf841820d70f712080dfbaecbc8aeee9edb2b878adc79e69f37b` | `upload` saves physical bytes before registering UploadedOriginal in the caller transaction; `parse_uploaded` creates a derived Artifact and changes parse status; neither grants clean. |
| `evidence_processing/types.py` | `3bdb7eec20948def3f0ddec45cbf41ec21a37b6333d7b8247edbe4d6811b7e10` | ParseResult has static `not_scanned`; parsing is not malware scanning. |
| `models.py` | `97d9b65d4e90107a8deac1641384dfca14339c4beae6b7ee6a2b433032a29a30` | Only UploadedOriginal read: scope/owner, byte metadata/key, revision, uploaded/parsed/needs_ocr/failed, not_scanned. Other model changes are unrelated consumers. |

Mainline must recheck the required fields when wiring. Existing imports do not freeze changing mainline contracts. Missing lifecycle inventory/reference/authorization ports must produce unavailable/unknown state; a missing UploadedOriginal row alone is never proof of an orphan.

## Rules and safe state

`RetentionPolicy` is required server constructor configuration. There is no active production default and no payload-selectable policy. Tests use a **synthetic proposal** of 7 days after terminal failed/abandoned upload, 30 days in quarantine, 5 minute preview, 30 second effect permit, and 1 minute maximum snapshot age. Policy digest binds the entire policy, so changing periods under the same version invalidates old previews/permits. Mainline must establish the real fixed policy before activation.

`evaluate_quarantine` permits only ACTIVE bytes whose upload is authoritatively FAILED/ABANDONED, registration is authoritatively false, parsing is not active/derived, no consuming reference/formal history/manual hold exists, and both the known retention deadline and failure grace have passed. Unknown registration, scope, references/history, hold, parse/status, retention, terminal upload time, old/future observations, and pending effects protect the object. Successfully registered originals remain protected even if parsing failed. The terminal upload timestamp is authoritative, not a listing modification time.

`evaluate_restore` allows recovery of known exact QUARANTINED bytes after a current ACL check, including referenced, held, or formal-history originals. It never restores PURGED/unknown bytes, invents missing data, changes scan status, expands source visibility, or bypasses the separate parser/read gate. `evaluate_purge` only computes eligibility after both retention clocks and current protections; this package has **no purge permit issuer or physical delete callable**. A future irreversible purge needs a separately authorized named decision, current complete references, and its own controlled adapter.

`OrphanCandidate.as_dict()` includes substantive object/hash/size, lifecycle/inventory/reference versions, policy version/digest, reasons, retention boundary, expiry and fixed preview digest. It omits storage keys, content, actor claims, and scan status. Dataclasses reject unknown constructor fields and coercions such as `registered=1`, string states, boolean revisions and naive timestamps.

## Mainline port fields

1. `LifecycleAuthorityPort.authorize` resolves tenant/product/actor, current source ACL and permission from server Context. A candidate/request cannot provide them. Human confirmation requires HUMAN plus the same current named decider. Physical dispatch/validation requires a trusted SERVICE bound to the exact stored named decision/intent and current permission; AGENT never gains lifecycle effect power. Restore rechecks current ACL. Reconciliation permission is a distinct current observation permission, not a renewed physical grant.
2. `LifecycleStorePort.read_current` assembles `OriginalState` from the sole authoritative original/inventory/upload journal: exact ObjectRef and scope, monotonic protection/lifecycle revision, inventory read version, upload creation/terminal outcome/time, registration knowledge, current parse state, retention deadline, manual hold, disposition, quarantine time and pending intent. Every optional fact uses None for unknown. This is a consumption snapshot, not a new business-original table.
3. `ReferenceGuardPort` returns exact ObjectRef/scope, monotonic reference read version, checked-at, complete consuming reference count and formal-history knowledge. Query all applicable source/Artifact/Claim/read-set/decision/history domains; incomplete coverage returns None. Inventory's own identity link is not itself a business evidence consumption. Mainline must define the exact authoritative coverage before enabling eligibility.
4. Persist previews and their immutable digests/read sets/expiry, preview consumption, lifecycle intents, request bindings, permits and trusted transport receipts. Needed uniqueness: scope + actor + request key; scope + semantic intent digest; preview consumption once; operation + attempt/lease token once. Keep exact bytes/id/version/hash/size/key in internal binding; do not accept request storage keys or authorization claims.

## Transaction and protection fence

The caller owns every transaction. `LifecycleService` never opens a DB session, commits, writes a business table directly, or invokes physical transport. Implement `lock_current`, `stage`, `change`, `remember_request` in the existing scoped command transaction. CAS source and intent versions; facts + request dedup + preview consumption + ActionReceipt + Audit + Outbox are one atomic group. A conflicting or incorrect adapter acknowledgment must roll back that enclosing group.

Every reference/history, hold/retention, source ACL/withdrawal, inventory, upload and parse writer must take **the same per-object gate** and advance protection/lifecycle epochs even if a value is changed back. New consuming references, parsing and reading must reject pending/quarantined objects. Use a stable inventory gate for failed-upload objects lacking an UploadedOriginal row; separate locks on separate absent rows are insufficient. An ACTIVE disposition with pending intent is the last confirmed location, not proof of present accessibility.

`confirm(context, candidate_id, digest, key)` rereads current authorization, locks that gate, verifies fixed facts/read versions and preview expiry, reevaluates protection, and stages a PENDING intent. It handles same-key conflict and cross-key same-intent replay before stale-preview checks, while always enforcing current access. Preview data is loaded from the server store. `begin_effect` requires exactly `candidate.original.revision + 1` after confirmation, preventing changed-and-reverted protection (ABA).

`begin_effect` stages a one-attempt IN_FLIGHT permit tied to exact ObjectRef, scope, named decider, access revision, post-begin lifecycle revision, inventory/reference versions, full policy digest, issue/expiry and lease token. Commit that caller transaction before transport. The controlled adapter then acquires the same authority gate in a new caller-owned transaction and calls `validate_effect` **immediately around bounded, reversible physical I/O**, keeping that gate held until its marker/byte-preserving action ends. It checks the current stored permit, current ACL, all protection epochs and rules, policy, expiry and clock rollback. Releasing the gate after validation but before physical I/O is invalid. The storage-side marker/journal must durably deduplicate/fence the operation+token so a stale worker cannot apply after its lease; no automatic SDK retry of an ambiguous action.

The current ObjectStore API has no lifecycle operation. Mainline must provide an authenticated reversible marker/storage adapter which retains exact bytes and never overwrites the immutable original key. This package's `UnavailableReversibleLifecycleAdapter` performs no storage call and reports UNKNOWN with a bounded machine error code; it cannot assert verified retained bytes or success.

## Worker, Outbox and reconciliation sequence

1. Mainline authorized T1 preview/once-confirm commands call `preview` and `confirm` with caller transactions. Route substantive reasons and digest into the existing T1 confirmation surface; no fixture-backed success UI is supplied.
2. Outbox/Inbox carries only the stored operation identity. A trusted worker rereads the operation, source, scope, named decision and current authorization, then stages/commits `begin_effect`.
3. The controlled transport executes through the atomic gate above. Persist the transport operation journal and exact byte verification. Pass only trusted adapter `EffectReceipt` to `record_effect` in another existing command transaction. No HTTP/model-supplied receipt is accepted as physical truth.
4. Known APPLIED updates confirmed QUARANTINED/ACTIVE location and releases pending protection. Known NOT_APPLIED needs verified exact bytes in the old location and durable no-effect proof; it terminates this intent. Another physical attempt requires a new current preview and human confirmation/key. Replaying the old intent never runs it again.
5. Timeout, crash, absent/incomplete transport evidence, or UNKNOWN leaves the pending protection. `mark_unknown` expires an IN_FLIGHT lease without asserting no effect. Call only read-only `observe` to reconcile, then `record_effect`; neither begin nor cancel permits resending an attempted operation. Missing markers, current location, or a lost reply alone cannot prove NOT_APPLIED. The test transport uses a durable synthetic terminal journal per operation. An APPLIED operation later restored is still historically APPLIED; an observation that cannot corroborate its terminal journal returns UNKNOWN/conflict, never retroactive NOT_APPLIED.
6. If a broken external writer introduces a reference/hold after physical quarantine, `record_effect` records the known location separately from authorization and preserves `recovery_required` plus current protection reasons. Mainline should emit an incident/recovery recommendation and offer current-ACL restoration. It must not call that a successful eligible cleanup or purge it. Unknown scope/binding observations are rejected and retained for authorized reconciliation.
7. Only never-attempted PENDING work can be named-cancelled. Restoration follows a fresh preview/confirmation/permit and preserves upload/parse/retention/hold metadata. Malware scan/read gates remain owned by evidence_security and mainline originals.

## Coverage and remaining validation

Synthetic checks cover strict facts/scope, unknown/protected history, terminal failure grace and retention, restore/purge rule boundaries, fixed preview tampering/expiry/policy changes, current ACL/human-vs-agent, two-level idempotency, caller rollback/Outbox failure, wrong port acknowledgment, threaded confirmation, ABA, post-permit protection/ACL/policy changes, a shared gate through physical marker change, clock rollback, UNKNOWN/lease timeout/observe-only recovery, explicit retry after verified no effect, restoration, unexpected new reference after effect, and unavailable transport. An autouse safety guard blocks socket connection, sqlite/SQLAlchemy connection and subprocess creation.

Run from `pdos-next/server`:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/original_lifecycle --confcutdir=tests/original_lifecycle -o cache_dir=tests/original_lifecycle/.pytest_cache -q
.venv/bin/ruff check --no-cache pdos_next/original_lifecycle tests/original_lifecycle
```

These are package-local rule/port/state checks, not PG transactional or storage/API/worker/browser acceptance. Mainline still needs entity registration/migration, complete reference inventory, upload-attempt journal and transaction ambiguity reconciliation, current permission mapping, original read/parse gates, Outbox/Inbox wiring, bounded real reversible adapter with storage fencing, multi-transaction rollback/concurrency/worker restart reconciliation, actual backup/restore, and applicable formal exits. This package grants no real qualification, production activation or G/N/P/Q completion.
