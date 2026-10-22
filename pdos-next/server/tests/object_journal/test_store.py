"""Real temp-file observations; no DB, production original or lifecycle authority."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import UUID, uuid4

import pytest

from pdos_next.object_journal import JournaledLocalObjectStore, JournalScope
from pdos_next.object_storage import StorageFailure

CONTENT = b"Synthetic harmless upload; this raw content must never appear in metadata."


@pytest.fixture
def fixture(tmp_path):
    store = JournaledLocalObjectStore(tmp_path / "private-journal")
    values = {
        "media_type": "text/plain",
        "tenant_id": uuid4(),
        "product_id": uuid4(),
        "requester_id": uuid4(),
        "upload_id": uuid4(),
    }
    yield store, values
    store.close()


def fail(code, operation):
    with pytest.raises(StorageFailure) as error:
        operation()
    assert error.value.code == code


def test_metadata_is_durable_before_bytes_and_never_grants_scan_or_registration(fixture):
    store, values = fixture
    observations = []

    def checkpoint(stage, entry):
        original = store.root / entry["reference"]["server_storage_key"]
        metadata = store.root / "journal" / values["upload_id"].hex / "entry.json"
        observations.append((stage, metadata.is_file(), original.is_file()))

    store._checkpoint = checkpoint
    ref = store.put_scoped(CONTENT, **values)
    assert observations == [
        ("metadata_durable", True, False),
        ("bytes_durable", True, True),
        ("bytes_written_durable", True, True),
    ]
    assert ref.id == values["upload_id"]
    inspection = store.inspect(ref.id)
    assert inspection.state == "bytes_written" and inspection.registration_state == "unknown"
    assert inspection.byte_status == "intact" and inspection.recovery_required
    serialized = json.dumps(inspection.to_dict())
    assert "scan_status" not in serialized and "server_storage_key" not in serialized
    assert "terminal_evidence_ref" not in serialized and CONTENT.decode() not in serialized
    for metadata in (store.root / "journal").rglob("*.json"):
        assert CONTENT not in metadata.read_bytes()
        assert metadata.stat().st_mode & 0o077 == 0
    assert store.read_original(ref) == CONTENT


def test_separate_instances_concurrent_same_upload_have_one_byte_write_and_binding(fixture):
    first, values = fixture
    second = JournaledLocalObjectStore(first.root)
    barrier = Barrier(2)

    def upload(store):
        barrier.wait()
        return store.put_scoped(CONTENT, **values)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(upload, store) for store in (first, second)]
            refs = [future.result(timeout=5) for future in futures]
        assert refs[0] == refs[1]
        assert len(list((first.root / "originals").rglob(refs[0].content_sha256))) == 1
        assert first.inspect(refs[0].id).revision == 1
        assert len(list((first.root / "journal" / refs[0].id.hex / "events").glob("*.json"))) == 1
    finally:
        second.close()


@pytest.mark.parametrize(
    "field", ["tenant_id", "product_id", "requester_id", "media_type", "content"]
)
def test_duplicate_upload_requires_all_scope_and_byte_fields_to_match(fixture, field):
    store, values = fixture
    ref = store.put_scoped(CONTENT, **values)
    changed = dict(values)
    content = CONTENT
    if field == "content":
        content = b"Different synthetic bytes"
    else:
        changed[field] = "text/markdown" if field == "media_type" else uuid4()
    fail("UPLOAD_BINDING_CONFLICT", lambda: store.put_scoped(content, **changed))
    assert store.read_original(ref) == CONTENT and store.inspect(ref.id).revision == 1


def test_positive_replay_preserves_existing_bytes_inode_and_does_not_rewrite(fixture):
    store, values = fixture
    ref = store.put_scoped(CONTENT, **values)
    original = store.root / ref.server_storage_key
    before = original.stat()
    assert store.put_scoped(CONTENT, **values) == ref
    after = original.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_size) == (
        before.st_ino,
        before.st_mtime_ns,
        before.st_size,
    )


def test_fault_after_metadata_preserves_unknown_without_creating_or_rewriting_bytes(fixture):
    store, values = fixture

    def checkpoint(stage, entry):
        if stage == "metadata_durable":
            raise RuntimeError("Private synthetic diagnostic")

    store._checkpoint = checkpoint
    fail("UPLOAD_OUTCOME_UNKNOWN", lambda: store.put_scoped(CONTENT, **values))
    inspection = store.inspect(values["upload_id"])
    assert inspection.state == "unknown" and inspection.byte_status == "missing"
    assert inspection.registration_state == "unknown" and inspection.recovery_required
    assert inspection.error_code == "UPLOAD_OUTCOME_UNKNOWN"
    assert "Private synthetic diagnostic" not in json.dumps(inspection.to_dict())
    store._checkpoint = lambda *args: None
    fail("UPLOAD_OUTCOME_UNKNOWN", lambda: store.put_scoped(CONTENT, **values))
    assert not (store.root / inspection.reference.server_storage_key).exists()


def test_process_crash_window_keeps_prepared_unknown_registration(fixture):
    store, values = fixture

    def checkpoint(stage, entry):
        if stage == "metadata_durable":
            raise KeyboardInterrupt("Synthetic abrupt process interruption")

    store._checkpoint = checkpoint
    with pytest.raises(KeyboardInterrupt):
        store.put_scoped(CONTENT, **values)
    inspection = store.inspect(values["upload_id"])
    assert inspection.state == "prepared" and inspection.registration_state == "unknown"
    assert inspection.byte_status == "missing" and inspection.recovery_required
    fail("UPLOAD_OUTCOME_UNKNOWN", lambda: store.put_scoped(CONTENT, **values))


def test_fault_after_bytes_replays_only_from_verified_retained_bytes(fixture):
    store, values = fixture

    def checkpoint(stage, entry):
        if stage == "bytes_durable":
            raise RuntimeError("Synthetic lost success reply")

    store._checkpoint = checkpoint
    fail("UPLOAD_OUTCOME_UNKNOWN", lambda: store.put_scoped(CONTENT, **values))
    before = store.inspect(values["upload_id"])
    assert before.state == "unknown" and before.byte_status == "intact"
    original = store.root / before.reference.server_storage_key
    inode = original.stat().st_ino
    store._checkpoint = lambda *args: None
    assert store.put_scoped(CONTENT, **values) == before.reference
    assert original.stat().st_ino == inode
    after = store.inspect(values["upload_id"])
    assert after.state == "bytes_written" and after.registration_state == "unknown"


def test_registered_marker_requires_positive_bytes_and_is_a_separate_idempotent_fact(fixture):
    store, values = fixture
    ref = store.put_scoped(CONTENT, **values)
    registration_id = uuid4()
    registered = store.mark_registered(ref.id, ref, registration_id=registration_id)
    assert registered.state == registered.registration_state == "registered"
    assert not registered.recovery_required
    assert store.mark_registered(ref.id, ref, registration_id=registration_id) == registered
    fail(
        "REGISTRATION_CONFLICT", lambda: store.mark_registered(ref.id, ref, registration_id=uuid4())
    )
    assert store.put_scoped(CONTENT, **values) == ref
    assert store.read_original(ref) == CONTENT


def test_aborted_is_only_explicit_trusted_terminal_evidence_and_never_deletes(fixture):
    store, values = fixture
    ref = store.put_scoped(CONTENT, **values)
    arguments = {
        "terminal_evidence_ref": "synthetic-terminal-db:transaction-1",
        "reason_code": "DB_ABORTED",
    }
    aborted = store.mark_aborted(ref.id, ref, **arguments)
    assert aborted.state == aborted.registration_state == "aborted"
    assert store.mark_aborted(ref.id, ref, **arguments) == aborted
    assert "terminal_evidence_ref" not in aborted.to_dict()
    fail("REGISTRATION_CONFLICT", lambda: store.mark_registered(ref.id, ref))
    fail("UPLOAD_ABORTED", lambda: store.put_scoped(CONTENT, **values))
    assert store.read_original(ref) == CONTENT
    with pytest.raises(ValueError):
        store.mark_aborted(ref.id, ref, terminal_evidence_ref="", reason_code="raw diagnostic")


@pytest.mark.parametrize("mode", ["bytes", "entry", "event", "event_deleted", "events_deleted"])
def test_tampering_is_detected_and_never_rewritten_or_reported_complete(fixture, mode):
    store, values = fixture
    ref = store.put_scoped(CONTENT, **values)
    directory = store.root / "journal" / ref.id.hex
    if mode == "bytes":
        (store.root / ref.server_storage_key).write_bytes(b"Corrupt synthetic content")
        fail("UPLOAD_OUTCOME_UNKNOWN", lambda: store.put_scoped(CONTENT, **values))
        fail("INTEGRITY_MISMATCH", lambda: store.read_original(ref))
        fail("INTEGRITY_MISMATCH", lambda: store.mark_registered(ref.id, ref))
        inspection = store.inspect(ref.id)
        assert inspection.byte_status == "corrupt" and inspection.recovery_required
    else:
        if mode == "entry":
            file = directory / "entry.json"
            value = json.loads(file.read_text())
            value["product_id"] = str(uuid4())
            file.write_text(json.dumps(value))
        elif mode == "event":
            file = directory / "events" / "00000001.json"
            value = json.loads(file.read_text())
            value["state"] = "registered"
            file.write_text(json.dumps(value))
        else:
            # Only this test's private synthetic metadata is removed, to verify
            # real journal loss never downgrades terminal state to unregistered.
            (directory / "events" / "00000001.json").unlink()
            if mode == "events_deleted":
                (directory / "events").rmdir()
        fail("JOURNAL_CORRUPT", lambda: store.inspect(ref.id))
        fail("JOURNAL_CORRUPT", lambda: store.put_scoped(CONTENT, **values))
        page = store.inventory(JournalScope(values["tenant_id"], values["product_id"]))
        assert not page.complete and page.unavailable_count == 1


@pytest.mark.parametrize("target", ["root", "ancestor", "object", "entry"])
def test_symlink_paths_never_read_or_write_their_target(fixture, tmp_path, target):
    store, values = fixture
    if target in {"root", "ancestor"}:
        other = tmp_path / "synthetic-other"
        other.mkdir(mode=0o700)
        link = tmp_path / "alias"
        link.symlink_to(other, target_is_directory=True)
        fail(
            "UNSAFE_STORAGE_ROOT",
            lambda: JournaledLocalObjectStore(link if target == "root" else link / "new"),
        )
        assert not (other / "new").exists()
        return
    ref = store.put_scoped(CONTENT, **values)
    victim = tmp_path / "synthetic-victim.txt"
    victim.write_bytes(CONTENT)
    victim.chmod(0o600)
    path = (
        store.root / ref.server_storage_key
        if target == "object"
        else store.root / "journal" / ref.id.hex / "entry.json"
    )
    path.unlink()
    path.symlink_to(victim)
    if target == "object":
        fail("INTEGRITY_MISMATCH", lambda: store.read_original(ref))
        fail("UPLOAD_OUTCOME_UNKNOWN", lambda: store.put_scoped(CONTENT, **values))
    else:
        fail("JOURNAL_CORRUPT", lambda: store.inspect(ref.id))
    assert victim.read_bytes() == CONTENT


def test_inventory_is_scoped_bounded_paginated_and_cursor_cannot_change_scope(fixture):
    store, values = fixture
    ids = [UUID(int=i) for i in (1, 2, 3)]
    for upload_id in ids:
        store.put_scoped(CONTENT, **{**values, "upload_id": upload_id})
    store.put_scoped(CONTENT, **{**values, "product_id": uuid4(), "upload_id": uuid4()})
    scope = JournalScope(values["tenant_id"], values["product_id"])
    first = store.inventory(scope, limit=2)
    assert [row.upload_id for row in first.items] == ids[:2]
    assert first.has_more and first.next_cursor and not first.complete
    second = store.inventory(scope, limit=2, cursor=first.next_cursor)
    assert [row.upload_id for row in second.items] == ids[2:]
    assert not second.has_more and second.next_cursor is None and second.complete
    assert all(row.scope == scope for row in first.items + second.items)
    with pytest.raises(ValueError):
        store.inventory(JournalScope(values["tenant_id"], uuid4()), cursor=first.next_cursor)
    with pytest.raises(ValueError):
        store.inventory(scope, limit=True)
    limited = JournaledLocalObjectStore(store.root, max_inventory_entries=2)
    try:
        truncated = limited.inventory(scope)
        assert not truncated.complete and truncated.has_more and not truncated.items
    finally:
        limited.close()


def test_exact_lookup_and_unscoped_upload_cannot_bypass_server_binding(fixture):
    store, values = fixture
    fail("UNSCOPED_UPLOAD", lambda: store.put_new(CONTENT, media_type="text/plain"))
    ref = store.put_scoped(CONTENT, **values)
    scope = JournalScope(values["tenant_id"], values["product_id"])
    assert store.lookup_original(ref, scope) == store.inspect(ref.id)
    fail(
        "UPLOAD_BINDING_CONFLICT",
        lambda: store.lookup_original(ref, JournalScope(uuid4(), values["product_id"])),
    )
    changed_hash = hashlib.sha256(b"Other synthetic bytes").hexdigest()
    changed = replace(
        ref,
        content_sha256=changed_hash,
        server_storage_key=f"originals/{ref.id.hex}/v1/{changed_hash}",
    )
    fail("UPLOAD_BINDING_CONFLICT", lambda: store.read_original(changed))
    fail("UPLOAD_BINDING_CONFLICT", lambda: store.mark_registered(ref.id, changed))
    with pytest.raises(ValueError):
        store.put_scoped(CONTENT, **{**values, "tenant_id": str(values["tenant_id"])})


def test_partial_metadata_failure_is_not_reinterpreted_as_absent_or_overwritten(fixture):
    store, values = fixture
    path = store.root / "journal" / values["upload_id"].hex
    path.mkdir(mode=0o700)
    entry = path / "entry.json"
    entry.write_bytes(b'{"synthetic-partial":')
    entry.chmod(0o600)
    fail("JOURNAL_CORRUPT", lambda: store.put_scoped(CONTENT, **values))
    assert entry.read_bytes() == b'{"synthetic-partial":'
    assert not list((store.root / "originals").iterdir())


def test_byte_fsync_precedes_success_and_journal_fsync_precedes_creation(fixture, monkeypatch):
    store, values = fixture
    observed = []
    actual_fsync = os.fsync

    def fsync(fd):
        info = os.fstat(fd)
        observed.append(info.st_ino)
        return actual_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    ref = store.put_scoped(CONTENT, **values)
    entry_inode = (store.root / "journal" / ref.id.hex / "entry.json").stat().st_ino
    byte_inode = (store.root / ref.server_storage_key).stat().st_ino
    assert entry_inode in observed and byte_inode in observed
    assert observed.index(entry_inode) < observed.index(byte_inode)
