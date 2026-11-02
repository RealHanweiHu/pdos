# Scoped local upload journal

`JournaledLocalObjectStore(root)` owns a **new server-configured private directory**.
It does not adopt an old object store, infer missing DB registrations, run scans,
authorize reads, or issue lifecycle effects. No deletion/purge/move API exists.

`put_scoped(content, media_type=..., tenant_id=UUID, product_id=UUID,
requester_id=UUID, upload_id=UUID)` takes server-resolved identities only.
`upload_id == ObjectRef.id`; no extra identity mapping is necessary. The durable
entry binds exact scope, requester, original ID/version/hash/size/media/key before
original creation. The byte file and directories are fsynced before success.
Repeated IDs must match all input identities and bytes; they verify existing bytes
and return the same ref without rewriting. Missing/partial bytes remain unknown.

After a positively confirmed DB commit, the root calls
`mark_registered(upload_id, ref, registration_id=optional_UUID)`. This is a separate
fact; `bytes_written` is not proof of registration. A lost registration-marker
reply cannot be used to infer DB rollback. `mark_aborted(...,
terminal_evidence_ref=..., reason_code=...)` is reserved for a caller-proven terminal
DB result, never a caught exception or missing row. Both terminal facts are fixed
and idempotent. An aborted upload cannot be reused for a fresh registration.

`inspect(upload_id)` and `lookup_original(ref, JournalScope(tenant, product))`
return frozen `UploadInspection`. `.to_dict()` excludes storage keys, private
terminal evidence references and scan assertions. Registration defaults unknown;
the byte observation separately reports intact/missing/corrupt/unavailable.
`read_original(ref)` checks the immutable binding and original bytes independently
of DB marker state; the root must apply current ACL/security/lifecycle gates.

`inventory(scope, limit=100, cursor=None)` returns `InventoryPage`. Pages contain
only exact scoped entries and scoped cursors. `complete` is false while `has_more`
or any corrupt/unassignable entry exists. A later page covers the remaining range,
so callers must consume all pages before treating a scope inventory as complete.
Exceeding the configured full-enumeration bound returns no guessed entries,
`complete=False`, `has_more=True`, `next_cursor=None`; enlarge the trusted bound or
introduce another inventory service rather than infer an empty scope. Inventory
completeness does **not** prove complete business references or orphan eligibility.

All cooperating processes use a private `flock` inventory gate and per-object gate.
Directory-descriptor traversal rejects symlinks/hard-linked files and non-private
owned paths. Immutable entries/events have digest and sequence checks; a high-water
marker detects missing terminal events. A crash between an event and its marker
leaves journal reconciliation unavailable, while exact retained bytes remain
readable to the separately authorized root. A process with full write access to
the private root can coherently rewrite all metadata: these hashes are integrity
checks, not a signature or proof against a compromised storage administrator.

This journal fences local cooperating storage writers only. It is not the shared
PG protection fence required by original_lifecycle, and it does not make reference
coverage, retention, or physical reversible transport available. Failed uploads
without a positively verified registration outcome remain protected.
