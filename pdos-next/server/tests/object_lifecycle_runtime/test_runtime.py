"""Actual private synthetic files/processes; the fake gate grants no business qualification."""

import errno
import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from pdos_next.object_journal import JournaledLocalObjectStore
from pdos_next.object_lifecycle_runtime import LocalReversibleLifecycleAdapter
from pdos_next.object_lifecycle_runtime.files import PrivateFiles, seal
from pdos_next.object_storage.adapters import LocalPrivateObjectStore
from pdos_next.object_storage.types import StorageFailure
from pdos_next.original_lifecycle.types import (
    Disposition,
    EffectOutcome,
    EffectPermit,
    LifecycleAction,
    LifecycleFailure,
    LifecycleScope,
)


class TestGate:
    __test__ = False

    def __init__(self):
        self.local = threading.local()
        self.calls = []
        self.allowed = True

    @contextmanager
    def __call__(self, permit, observation=False):
        self.calls.append((permit.operation_id, observation))
        if not self.allowed:
            raise LifecycleFailure("TEST_CURRENT_AUTH_DENIED", "Synthetic gate denies authority")
        assert not getattr(self.local, "active", False)
        self.local.active = True
        try:
            yield
        finally:
            self.local.active = False


@pytest.fixture
def work(tmp_path):
    store = JournaledLocalObjectStore(tmp_path.resolve() / "private")
    scope, owner = LifecycleScope(uuid4(), uuid4()), uuid4()
    content = b"retained harmless synthetic bytes\r\n"
    ref = store.put_scoped(
        content,
        media_type="text/plain",
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        requester_id=owner,
        upload_id=uuid4(),
    )
    gate = TestGate()
    adapter = LocalReversibleLifecycleAdapter(store, gate)
    now = datetime.now(UTC)
    permit = EffectPermit(
        uuid4(),
        ref,
        scope,
        LifecycleAction.QUARANTINE,
        uuid4(),
        1,
        owner,
        "synthetic-acl-v1",
        2,
        "synthetic-inventory-v1",
        "synthetic-references-v1",
        "a" * 64,
        now - timedelta(seconds=1),
        now + timedelta(seconds=90),
    )
    value = SimpleNamespace(
        store=store,
        scope=scope,
        owner=owner,
        ref=ref,
        content=content,
        gate=gate,
        adapter=adapter,
        permit=permit,
    )
    yield value
    store.close()


def object_directory(work):
    return work.store.root / "lifecycle-runtime-v1/objects" / work.ref.id.hex


def metadata(work):
    root = work.store.root / "lifecycle-runtime-v1"
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*.json")
    }


def restored(work):
    return replace(
        work.permit,
        operation_id=uuid4(),
        lease_token=uuid4(),
        action=LifecycleAction.RESTORE,
        lifecycle_revision=4,
    )


def test_actual_quarantine_restore_preserves_bytes_and_non_lifecycle_facts(work):
    before = work.store.inspect(work.ref.id)
    assert work.adapter.ensure_readable(work.ref) is None
    quarantine = work.adapter.apply_once(work.permit)
    assert quarantine.outcome == EffectOutcome.APPLIED
    assert quarantine.observed_disposition == Disposition.QUARANTINED
    assert quarantine.integrity_verified and quarantine.lease_token == work.permit.lease_token
    with pytest.raises(StorageFailure, match="隔离") as failure:
        work.adapter.ensure_readable(work.ref)
    assert failure.value.code == "OBJECT_ACCESS_QUARANTINED"
    # Forensic byte owner is deliberately distinct from an application read gate.
    assert work.store.read_original(work.ref) == work.content
    restore = work.adapter.apply_once(restored(work))
    assert restore.outcome == EffectOutcome.APPLIED
    assert restore.observed_disposition == Disposition.ACTIVE
    assert work.adapter.ensure_readable(work.ref) is None
    assert work.store.inspect(work.ref.id) == before
    assert work.store.read_original(work.ref) == work.content
    assert not hasattr(work.adapter, "purge")


def test_completed_same_attempt_replay_does_not_rewrite_any_effect_file(work):
    first = work.adapter.apply_once(work.permit)
    before = metadata(work)
    second = work.adapter.apply_once(work.permit)
    assert second.outcome == EffectOutcome.APPLIED
    assert second.transport_revision == first.transport_revision
    assert metadata(work) == before


def test_observation_uses_distinct_current_gate_and_retains_old_applied_history(work):
    quarantine = work.adapter.apply_once(work.permit)
    work.adapter.apply_once(restored(work))
    before = metadata(work)
    observed = work.adapter.observe(work.permit)
    assert observed.outcome == EffectOutcome.APPLIED
    assert observed.observed_disposition == Disposition.QUARANTINED
    assert observed.transport_revision == quarantine.transport_revision
    assert metadata(work) == before
    assert work.gate.calls[-1] == (work.permit.operation_id, True)
    assert work.adapter.ensure_readable(work.ref) is None


@pytest.mark.parametrize("operation", ["apply_once", "observe"])
def test_current_authority_failure_causes_no_lifecycle_io(work, operation):
    work.gate.allowed = False
    with pytest.raises(LifecycleFailure, match="Synthetic gate"):
        getattr(work.adapter, operation)(work.permit)
    assert not (work.store.root / "lifecycle-runtime-v1").exists()
    assert work.store.read_original(work.ref) == work.content


def test_mainline_gate_is_held_for_entire_worker_io_and_receipt(work):
    class Checked(LocalReversibleLifecycleAdapter):
        def _run(self, request, budget):
            assert self.gate.local.active
            result = super()._run(request, budget)
            assert self.gate.local.active
            return result

    result = Checked(work.store, work.gate).apply_once(work.permit)
    assert result.outcome == EffectOutcome.APPLIED
    assert not work.gate.local.active


@pytest.mark.parametrize("kind", ["expired", "future_issue"])
def test_invalid_permit_clock_rejects_before_attempt(work, kind):
    now = datetime.now(UTC)
    item = replace(
        work.permit, issued_at=now - timedelta(seconds=3), expires_at=now - timedelta(seconds=1)
    )
    if kind == "future_issue":
        item = replace(
            work.permit,
            issued_at=now + timedelta(seconds=2),
            expires_at=now + timedelta(seconds=30),
        )
    result = work.adapter.apply_once(item)
    assert result.outcome == EffectOutcome.UNKNOWN
    assert result.error_code == "EFFECT_PERMIT_EXPIRED"
    assert not (work.store.root / "lifecycle-runtime-v1").exists()


@pytest.mark.parametrize("field", ["lease_token", "scope", "reference", "policy_digest"])
def test_existing_operation_cannot_replay_with_changed_binding(work, field):
    work.adapter.apply_once(work.permit)
    before = metadata(work)
    changes = {
        "lease_token": uuid4(),
        "scope": LifecycleScope(work.scope.tenant_id, uuid4()),
        "reference": replace(work.ref, media_type="text/markdown"),
        "policy_digest": "b" * 64,
    }
    result = work.adapter.apply_once(replace(work.permit, **{field: changes[field]}))
    assert result.outcome == EffectOutcome.UNKNOWN
    assert result.error_code == "LIFECYCLE_BINDING_CONFLICT"
    assert metadata(work) == before


def test_operation_id_cannot_be_used_for_a_different_object(work):
    work.adapter.apply_once(work.permit)
    other = work.store.put_scoped(
        b"other harmless synthetic bytes",
        media_type="text/plain",
        tenant_id=work.scope.tenant_id,
        product_id=work.scope.product_id,
        requester_id=work.owner,
        upload_id=uuid4(),
    )
    result = work.adapter.apply_once(replace(work.permit, reference=other))
    assert result.outcome == EffectOutcome.UNKNOWN
    assert result.error_code == "LIFECYCLE_BINDING_CONFLICT"
    assert work.adapter.ensure_readable(other) is None


def test_missing_history_is_unknown_not_negative_effect_proof(work):
    result = work.adapter.observe(work.permit)
    assert result.outcome == EffectOutcome.UNKNOWN
    assert result.error_code == "LIFECYCLE_HISTORY_UNKNOWN"
    assert result.integrity_verified is False


class CrashAdapter(LocalReversibleLifecycleAdapter):
    stage = "after_attempt"

    def _script(self):
        package_root = str(__import__("pathlib").Path(__file__).resolve().parents[2])
        return (
            "import sys,os; sys.path.insert(0," + repr(package_root) + "); "
            "from pdos_next.object_lifecycle_runtime.effects import EffectFiles; "
            "EffectFiles._checkpoint=lambda self,stage: os._exit(88) if stage=="
            + repr(self.stage)
            + " else None; "
            "from pdos_next.object_lifecycle_runtime.worker import main; main()"
        )


@pytest.mark.parametrize(
    "stage",
    [
        "after_base",
        "after_attempt",
        "after_binding",
        "before_marker",
        "after_marker",
        "after_terminal",
    ],
)
def test_real_worker_crash_never_retries_uncertain_effect(work, stage):
    adapter = CrashAdapter(work.store, work.gate)
    adapter.stage = stage
    first = adapter.apply_once(work.permit)
    assert first.outcome == EffectOutcome.UNKNOWN
    assert first.error_code == "LIFECYCLE_ATTEMPT_UNKNOWN"
    before = metadata(work)
    observed = work.adapter.observe(work.permit)
    replay = work.adapter.apply_once(work.permit)
    if stage == "after_terminal":
        assert observed.outcome == replay.outcome == EffectOutcome.APPLIED
    else:
        assert observed.outcome == replay.outcome == EffectOutcome.UNKNOWN
        with pytest.raises(StorageFailure):
            work.adapter.ensure_readable(work.ref)
    assert metadata(work) == before
    assert work.store.read_original(work.ref) == work.content


@pytest.mark.parametrize(
    "damage",
    [
        "head_invalid",
        "head_missing",
        "terminal_missing",
        "terminal_invalid",
        "marker_rollback",
        "event_missing",
    ],
)
def test_damaged_marker_or_history_fail_closed_and_never_become_not_applied(work, damage):
    work.adapter.apply_once(work.permit)
    directory = object_directory(work)
    if damage == "head_invalid":
        (directory / "head.json").write_bytes(b"broken metadata")
    elif damage == "head_missing":
        (directory / "head.json").unlink()
    elif damage == "terminal_missing":
        (directory / f"terminal-{work.permit.operation_id.hex}.json").unlink()
    elif damage == "terminal_invalid":
        (directory / f"terminal-{work.permit.operation_id.hex}.json").write_text('{"sha256":"x"}')
    elif damage == "marker_rollback":
        (directory / "head.json").write_bytes((directory / "base.json").read_bytes())
    else:
        (directory / "event-000001.json").unlink()
    result = work.adapter.observe(work.permit)
    assert result.outcome == EffectOutcome.UNKNOWN
    assert not result.integrity_verified
    with pytest.raises(StorageFailure):
        work.adapter.ensure_readable(work.ref)


def test_resealed_current_marker_conflict_does_not_rewrite_old_applied_history(work):
    work.adapter.apply_once(work.permit)
    work.adapter.apply_once(restored(work))
    head = object_directory(work) / "head.json"
    value = json.loads(head.read_text())
    value.pop("sha256")
    value["disposition"] = "quarantined"
    head.write_text(json.dumps(seal(value)))
    observed = work.adapter.observe(work.permit)
    assert observed.outcome == EffectOutcome.UNKNOWN
    assert observed.error_code == "LIFECYCLE_MARKER_CONFLICT"


def test_corrupt_original_bytes_never_receive_known_effect_proof(work):
    work.adapter.apply_once(work.permit)
    (work.store.root / work.ref.server_storage_key).write_bytes(b"tampered synthetic bytes")
    result = work.adapter.observe(work.permit)
    assert result.outcome == EffectOutcome.UNKNOWN
    with pytest.raises(StorageFailure):
        work.adapter.ensure_readable(work.ref)


def test_lost_entire_object_log_is_protected_by_global_attempt_binding(work):
    work.adapter.apply_once(work.permit)
    shutil.rmtree(object_directory(work))
    before = metadata(work)
    assert work.adapter.observe(work.permit).outcome == EffectOutcome.UNKNOWN
    assert work.adapter.apply_once(work.permit).outcome == EffectOutcome.UNKNOWN
    with pytest.raises(StorageFailure):
        work.adapter.ensure_readable(work.ref)
    assert metadata(work) == before


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_metadata_links_are_rejected_without_touching_other_paths(work, tmp_path, link):
    work.adapter.apply_once(work.permit)
    head = object_directory(work) / "head.json"
    other = tmp_path / "other.json"
    other.write_bytes(head.read_bytes())
    head.unlink()
    if link == "symlink":
        head.symlink_to(other)
    else:
        os.link(other, head)
    before = other.read_bytes()
    assert work.adapter.observe(work.permit).outcome == EffectOutcome.UNKNOWN
    with pytest.raises(StorageFailure):
        work.adapter.ensure_readable(work.ref)
    assert other.read_bytes() == before


def test_parallel_processes_produce_one_actual_marker_transition(work):
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: work.adapter.apply_once(work.permit), range(4)))
    assert all(value.outcome == EffectOutcome.APPLIED for value in results), [
        {
            "outcome": value.outcome.value,
            "error_code": value.error_code,
            "transport_revision": value.transport_revision,
        }
        for value in results
    ]
    assert len({value.transport_revision for value in results}) == 1
    assert len(list(object_directory(work).glob("event-*.json"))) == 1
    assert len(list(object_directory(work).glob("attempt-*.json"))) == 1


def test_first_lock_create_race_has_one_creator_and_safe_existing_open(work, monkeypatch):
    real_open = os.open
    name = "object-" + work.ref.id.hex
    calls, competitor = [], []

    def raced_open(path, flags, *args, **kwargs):
        if path == name and "dir_fd" in kwargs:
            calls.append(flags)
            if flags & os.O_CREAT and not flags & os.O_EXCL:
                # The observed Darwin concurrent O_CREAT|O_NOFOLLOW failure.
                raise FileNotFoundError(errno.ENOENT, "Synthetic first-create race")
            if flags & os.O_EXCL and not competitor:
                # Another process wins immediately before our exclusive create.
                fd = real_open(path, flags, *args, **kwargs)
                os.close(fd)
                competitor.append(True)
        return real_open(path, flags, *args, **kwargs)

    files = PrivateFiles(work.store.root, deadline=time.monotonic() + 5)
    try:
        monkeypatch.setattr(os, "open", raced_open)
        with files.locked(work.ref.id):
            assert competitor == [True]
        assert len(calls) == 2
        assert calls[0] & os.O_CREAT and calls[0] & os.O_EXCL
        assert not calls[1] & os.O_CREAT and calls[1] & os.O_NOFOLLOW
        assert not list(object_directory(work).glob("attempt-*.json"))
    finally:
        files.close()


def test_positive_not_applied_requires_our_explicit_durable_terminal_record(work):
    item = restored(work)  # Nothing is quarantined, so this controlled attempt does no effect.
    receipt = work.adapter.apply_once(item)
    assert receipt.outcome == EffectOutcome.NOT_APPLIED
    assert receipt.observed_disposition == Disposition.ACTIVE
    assert receipt.integrity_verified
    assert work.adapter.observe(item).outcome == EffectOutcome.NOT_APPLIED
    assert work.adapter.ensure_readable(work.ref) is None
    assert not list(object_directory(work).glob("event-*.json"))


def test_worker_deadline_kills_reaps_and_keeps_gate_until_exit(work):
    class Slow(CrashAdapter):
        def _script(self):
            package_root = str(__import__("pathlib").Path(__file__).resolve().parents[2])
            return (
                "import sys,time; sys.path.insert(0," + repr(package_root) + "); "
                "from pdos_next.object_lifecycle_runtime.effects import EffectFiles; "
                "EffectFiles._checkpoint=lambda self,stage: "
                "time.sleep(30) if stage=='after_attempt' else None; "
                "from pdos_next.object_lifecycle_runtime.worker import main; main()"
            )

    start = time.monotonic()
    result = Slow(work.store, work.gate, io_timeout_seconds=0.5).apply_once(work.permit)
    assert time.monotonic() - start < 3
    assert result.outcome == EffectOutcome.UNKNOWN
    assert result.error_code == "LIFECYCLE_IO_TIMEOUT"
    assert work.adapter.observe(work.permit).outcome == EffectOutcome.UNKNOWN
    with pytest.raises(StorageFailure):
        work.adapter.ensure_readable(work.ref)


def test_cross_operation_worker_reply_is_rejected(work, monkeypatch):
    wrong = {
        "outcome": "applied",
        "disposition": "quarantined",
        "integrity_verified": True,
        "revision": "local-effects-v1:" + "a" * 64,
        "error_code": None,
        "binding": {"operation_id": str(uuid4())},
    }
    monkeypatch.setattr(work.adapter, "_run", lambda *args: wrong)
    result = work.adapter.apply_once(work.permit)
    assert result.outcome == EffectOutcome.UNKNOWN
    assert result.error_code == "LIFECYCLE_PROTOCOL_ERROR"


def test_constructor_requires_real_byte_owner_and_finite_deadline(work):
    with pytest.raises(ValueError):
        LocalReversibleLifecycleAdapter(object(), work.gate)
    with pytest.raises(ValueError):
        LocalReversibleLifecycleAdapter(work.store, None)
    with pytest.raises(ValueError):
        LocalReversibleLifecycleAdapter(work.store, work.gate, io_timeout_seconds=float("nan"))


def test_legacy_registered_bridge_verifies_real_bytes_without_journal_or_effect_gate(work):
    legacy_store = LocalPrivateObjectStore(work.store.root)
    ref = legacy_store.put_new(b"registered synthetic legacy original", media_type="text/plain")
    with pytest.raises(StorageFailure):
        work.adapter.ensure_readable(ref)
    before = metadata(work)
    assert work.adapter.ensure_legacy_readable(ref, work.scope) is None
    assert work.adapter.ensure_legacy_readable(ref, work.scope) is None
    assert work.gate.calls == []
    assert metadata(work) == before
    assert not (work.store.root / "journal" / ref.id.hex).exists()
    assert legacy_store.read_original(ref) == b"registered synthetic legacy original"
    (work.store.root / ref.server_storage_key).write_bytes(b"damaged legacy bytes")
    with pytest.raises(StorageFailure):
        work.adapter.ensure_legacy_readable(ref, work.scope)


def test_legacy_bridge_cannot_bypass_lifecycle_history_or_missing_logs(work):
    work.adapter.apply_once(work.permit)
    work.adapter.apply_once(restored(work))
    shutil.rmtree(work.store.root / "journal" / work.ref.id.hex)
    for scope in (work.scope, LifecycleScope(work.scope.tenant_id, uuid4())):
        with pytest.raises(StorageFailure):
            work.adapter.ensure_legacy_readable(work.ref, scope)
    shutil.rmtree(object_directory(work))
    with pytest.raises(StorageFailure):
        work.adapter.ensure_legacy_readable(work.ref, work.scope)
    assert (work.store.root / work.ref.server_storage_key).read_bytes() == work.content


def test_legacy_bridge_refuses_present_or_corrupt_journal_and_unbound_scope(work):
    with pytest.raises(StorageFailure) as failure:
        work.adapter.ensure_legacy_readable(work.ref, work.scope)
    assert failure.value.code == "LEGACY_BRIDGE_NOT_APPLICABLE"
    with pytest.raises(ValueError):
        work.adapter.ensure_legacy_readable(work.ref, {"tenant_id": work.scope.tenant_id})
    journal = work.store.root / "journal" / work.ref.id.hex / "entry.json"
    assert journal.exists()
    journal.write_bytes(b"broken synthetic journal")
    with pytest.raises(StorageFailure) as failure:
        work.adapter.ensure_legacy_readable(work.ref, work.scope)
    assert failure.value.code == "LIFECYCLE_INTEGRITY_UNAVAILABLE"
    assert work.gate.calls == []
