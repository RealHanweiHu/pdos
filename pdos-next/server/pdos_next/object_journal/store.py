"""POSIX private local journal, fsynced before immutable bytes are created.

This records local upload/storage observations, not database commits, scanner
results or orphan eligibility. Root service calls mark_registered only AFTER a
confirmed database commit. An ambiguous write is retained for reconciliation.
All paths are opened through directory descriptors with O_NOFOLLOW; there is no
delete, overwrite, SDK retry, remote transport or database dependency.
"""

import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pdos_next.object_storage.adapters import SUPPORTED_MEDIA
from pdos_next.object_storage.types import ObjectRef, StorageFailure

from .types import InventoryPage, JournalScope, UploadInspection

_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_HEX = re.compile(r"[0-9a-f]{32}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate journal field")
        result[key] = value
    return result


def _time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Aware journal timestamp required")
    return parsed.astimezone(UTC)


def _identity(value):
    if not isinstance(value, UUID):
        raise ValueError("Server UUID required")
    return value


class JournaledLocalObjectStore:
    def __init__(
        self,
        root: Path | str,
        *,
        max_bytes: int = 8_388_608,
        inventory_limit: int = 200,
        max_inventory_entries: int = 10_000,
        max_events: int = 1_024,
    ):
        for value in (max_bytes, inventory_limit, max_inventory_entries, max_events):
            if type(value) is not int or value < 1:
                raise ValueError("Positive bounded journal limits required")
        if max_bytes > 50_000_000 or inventory_limit > 1_000 or max_events > 10_000:
            raise ValueError("Journal limit exceeds supported bounds")
        if max_inventory_entries > 100_000:
            raise ValueError("Inventory must remain bounded")
        self.max_bytes = max_bytes
        self.inventory_limit = inventory_limit
        self.max_inventory_entries = max_inventory_entries
        self.max_events = max_events
        self.root = Path(root).absolute()
        if any(part in {".", ".."} for part in self.root.parts):
            raise ValueError("Journal root must be an exact server path")
        # Open every ancestor without following symbolic links, including roots
        # such as /tmp which may be aliases. Callers should pass the real path.
        fd = os.open("/", _DIRECTORY)
        try:
            for part in self.root.parts[1:]:
                try:
                    following = os.open(part, _DIRECTORY, dir_fd=fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    os.fsync(fd)
                    following = os.open(part, _DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = following
            self._private(fd, directory=True)
            self._root_fd = fd
        except (OSError, StorageFailure) as exc:
            os.close(fd)
            if isinstance(exc, StorageFailure):
                raise
            raise StorageFailure(
                "UNSAFE_STORAGE_ROOT", "Private journal root unavailable"
            ) from None
        for parts in (("locks",), ("journal",), ("originals",)):
            with self._directory(parts, create=True):
                pass

    def close(self):
        fd = getattr(self, "_root_fd", None)
        if fd is not None:
            os.close(fd)
            self._root_fd = None

    def __del__(self):
        self.close()

    @staticmethod
    def _private(fd, *, directory=False):
        info = os.fstat(fd)
        correct_kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not correct_kind or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise StorageFailure("UNSAFE_STORAGE_PATH", "Journal path must remain private")
        if not directory and info.st_nlink != 1:
            raise StorageFailure("UNSAFE_STORAGE_PATH", "Linked journal file unavailable")

    @contextmanager
    def _directory(self, parts, *, create=False):
        fd = os.dup(self._root_fd)
        try:
            for part in parts:
                if part in {"", ".", ".."} or "/" in part:
                    raise StorageFailure("UNSAFE_STORAGE_PATH", "Invalid server path")
                try:
                    following = os.open(part, _DIRECTORY, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    os.fsync(fd)
                    following = os.open(part, _DIRECTORY, dir_fd=fd)
                try:
                    self._private(following, directory=True)
                except Exception:
                    os.close(following)
                    raise
                os.close(fd)
                fd = following
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _locked(self, upload_id=None, *, shared=False):
        # A shared inventory read excludes all writers. The object gate also
        # fences separate processes using this exact root (not a Python RLock).
        with self._directory(("locks",)) as folder:
            fds = []
            try:
                names = ["inventory.lock"]
                if upload_id is not None:
                    names.append(f"{upload_id.hex}.lock")
                for name in names:
                    try:
                        # O_EXCL gives one creator and does not follow a final
                        # symlink. Opening existing locks separately makes the
                        # creator unambiguous during concurrent first access.
                        fd = os.open(
                            name,
                            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                            0o600,
                            dir_fd=folder,
                        )
                    except FileExistsError:
                        fd = os.open(name, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder)
                    fds.append(fd)
                    self._private(fd)
                    os.fsync(folder)
                    fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
                yield
            finally:
                for fd in reversed(fds):
                    os.close(fd)

    def _write_new(self, parts, content):
        with self._directory(parts[:-1], create=True) as folder:
            fd = os.open(parts[-1], _WRITE, 0o600, dir_fd=folder)
            try:
                view = memoryview(content)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("Journal short write")
                    view = view[written:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(folder)

    def _read(self, parts, limit):
        with self._directory(parts[:-1]) as folder:
            fd = os.open(parts[-1], _READ, dir_fd=folder)
            try:
                self._private(fd)
                with os.fdopen(fd, "rb", closefd=False) as stream:
                    value = stream.read(limit + 1)
                if len(value) > limit:
                    raise ValueError("Bounded journal record exceeded")
                return value
            finally:
                os.close(fd)

    def _json(self, parts):
        return json.loads(self._read(parts, 65_536), object_pairs_hook=_unique)

    def _write_tip(self, entry, event):
        """Atomic high-water marker detects missing/truncated terminal history.

        A crash between event fsync and this marker remains unavailable for
        reconciliation; it cannot downgrade a confirmed terminal registration.
        Temporary metadata files contain no bytes and are retained on failure.
        """
        upload_id = UUID(entry["upload_id"])
        parts = ("journal", upload_id.hex)
        name = f"tip-{os.urandom(16).hex()}.tmp"
        tip = {
            "binding_sha256": entry["binding_sha256"],
            "revision": event["revision"],
            "event_sha256": event["event_sha256"],
        }
        self._write_new((*parts, name), _encoded(tip))
        with self._directory(parts) as folder:
            # Replace this metadata pointer only; immutable entries/events and
            # all original keys are never overwritten or deleted.
            os.replace(name, "tip.json", src_dir_fd=folder, dst_dir_fd=folder)
            os.fsync(folder)

    @staticmethod
    def _basis(scope, requester_id, upload_id, content, media_type):
        checksum = hashlib.sha256(content).hexdigest()
        reference = ObjectRef(
            upload_id,
            1,
            checksum,
            len(content),
            media_type,
            f"originals/{upload_id.hex}/v1/{checksum}",
        )
        return {
            "schema_version": "pdos-object-journal-v1",
            "upload_id": str(upload_id),
            "tenant_id": str(scope.tenant_id),
            "product_id": str(scope.product_id) if scope.product_id else None,
            "category_id": str(scope.category_id) if scope.category_id else None,
            "requester_id": str(requester_id),
            "reference": {
                "id": str(reference.id),
                "version": reference.version,
                "content_sha256": checksum,
                "size_bytes": len(content),
                "media_type": media_type,
                "server_storage_key": reference.server_storage_key,
            },
        }

    def _entry(self, upload_id):
        try:
            entry = self._json(("journal", upload_id.hex, "entry.json"))
            fields = {
                "schema_version",
                "upload_id",
                "tenant_id",
                "product_id",
                "category_id",
                "requester_id",
                "reference",
                "created_at",
                "binding_sha256",
            }
            if not isinstance(entry, dict) or set(entry) != fields:
                raise ValueError("Invalid journal fields")
            if (
                entry["schema_version"] != "pdos-object-journal-v1"
                or UUID(entry["upload_id"]) != upload_id
            ):
                raise ValueError("Journal identity mismatch")
            if entry["binding_sha256"] != _digest(
                {k: v for k, v in entry.items() if k != "binding_sha256"}
            ):
                raise ValueError("Journal binding mismatch")
            scope = JournalScope(
                UUID(entry["tenant_id"]),
                UUID(entry["product_id"]) if entry["product_id"] else None,
                UUID(entry["category_id"]) if entry["category_id"] else None,
            )
            requester = UUID(entry["requester_id"])
            values = dict(entry["reference"])
            if type(values.get("version")) is not int or type(values.get("size_bytes")) is not int:
                raise ValueError("Strict object quantities required")
            values["id"] = UUID(values["id"])
            ref = ObjectRef(**values)
            if (
                ref.id != upload_id
                or ref.media_type not in SUPPORTED_MEDIA
                or ref.size_bytes > self.max_bytes
            ):
                raise ValueError("Journal object binding mismatch")
            _time(entry["created_at"])
            return entry, scope, requester, ref
        except FileNotFoundError:
            raise StorageFailure("JOURNAL_NOT_FOUND", "No authoritative upload journal") from None
        except (ValueError, TypeError, KeyError, OSError):
            raise StorageFailure("JOURNAL_CORRUPT", "Upload journal cannot be verified") from None

    def _latest(self, entry):
        initial = {
            "revision": 0,
            "state": "prepared",
            "registration_state": "unknown",
            "updated_at": entry["created_at"],
            "error_code": None,
            "registration_id": None,
            "terminal_evidence_ref": None,
            "event_sha256": None,
        }
        upload_id = UUID(entry["upload_id"])
        try:
            names = []
            try:
                with self._directory(("journal", upload_id.hex, "events")) as folder:
                    with os.scandir(folder) as children:
                        for child in children:
                            names.append(child.name)
                            if len(names) > self.max_events:
                                break
            except FileNotFoundError:
                pass
            if len(names) > self.max_events or any(
                not re.fullmatch(r"[0-9]{8}\.json", n) for n in names
            ):
                raise ValueError("Invalid event inventory")
            latest = initial
            fields = set(initial) | {"binding_sha256", "previous_event_sha256"}
            for revision, name in enumerate(sorted(names), 1):
                if name != f"{revision:08d}.json":
                    raise ValueError("Non-contiguous journal revision")
                event = self._json(("journal", upload_id.hex, "events", name))
                if not isinstance(event, dict) or set(event) != fields:
                    raise ValueError("Invalid event fields")
                if (
                    type(event["revision"]) is not int
                    or event["revision"] != revision
                    or event["binding_sha256"] != entry["binding_sha256"]
                    or event["previous_event_sha256"] != latest["event_sha256"]
                    or event["event_sha256"]
                    != _digest({k: v for k, v in event.items() if k != "event_sha256"})
                    or _time(event["updated_at"]) < _time(latest["updated_at"])
                ):
                    raise ValueError("Journal event binding mismatch")
                state, registration = event["state"], event["registration_state"]
                if state not in {"bytes_written", "unknown", "registered", "aborted"}:
                    raise ValueError("Invalid journal state")
                if registration != (state if state in {"registered", "aborted"} else "unknown"):
                    raise ValueError("Registration cannot be inferred")
                if latest["state"] in {"registered", "aborted"}:
                    raise ValueError("Terminal registration cannot change")
                if event["error_code"] is not None and not _CODE.fullmatch(event["error_code"]):
                    raise ValueError("Invalid journal code")
                if event["registration_id"] is not None:
                    UUID(event["registration_id"])
                if event["terminal_evidence_ref"] is not None:
                    self._evidence(event["terminal_evidence_ref"])
                latest = event
            try:
                tip = self._json(("journal", upload_id.hex, "tip.json"))
            except FileNotFoundError:
                if names:
                    raise ValueError("Durable event has an unconfirmed high-water marker") from None
                return initial
            if (
                not isinstance(tip, dict)
                or set(tip) != {"binding_sha256", "revision", "event_sha256"}
                or type(tip["revision"]) is not int
                or tip["revision"] != latest["revision"]
                or tip["event_sha256"] != latest["event_sha256"]
                or tip["binding_sha256"] != entry["binding_sha256"]
            ):
                raise ValueError("Upload event high-water marker changed")
            return latest
        except (ValueError, TypeError, KeyError, OSError):
            raise StorageFailure(
                "JOURNAL_CORRUPT", "Upload event history cannot be verified"
            ) from None

    def _append(
        self, entry, latest, state, *, error_code=None, registration_id=None, evidence=None
    ):
        revision = latest["revision"] + 1
        if revision > self.max_events:
            raise StorageFailure("JOURNAL_EVENT_LIMIT", "Upload event budget exceeded")
        event = {
            "revision": revision,
            "state": state,
            "registration_state": state if state in {"registered", "aborted"} else "unknown",
            "updated_at": max(datetime.now(UTC), _time(latest["updated_at"])).isoformat(),
            "error_code": error_code,
            "registration_id": str(registration_id) if registration_id else None,
            "terminal_evidence_ref": evidence,
            "binding_sha256": entry["binding_sha256"],
            "previous_event_sha256": latest["event_sha256"],
        }
        event["event_sha256"] = _digest(event)
        self._write_new(
            ("journal", UUID(entry["upload_id"]).hex, "events", f"{revision:08d}.json"),
            _encoded(event),
        )
        self._write_tip(entry, event)
        return event

    def _bytes(self, reference):
        try:
            content = self._read(tuple(reference.server_storage_key.split("/")), self.max_bytes)
            if (
                len(content) != reference.size_bytes
                or hashlib.sha256(content).hexdigest() != reference.content_sha256
            ):
                return "corrupt", None
            return "intact", content
        except FileNotFoundError:
            return "missing", None
        except (OSError, ValueError, StorageFailure):
            return "unavailable", None

    def _inspection(self, entry, scope, requester, reference, latest=None):
        latest = latest if latest is not None else self._latest(entry)
        byte_status, _ = self._bytes(reference)
        return UploadInspection(
            reference.id,
            scope,
            requester,
            reference,
            latest["revision"],
            latest["state"],
            latest["registration_state"],
            byte_status,
            _time(entry["created_at"]),
            _time(latest["updated_at"]),
            latest["registration_state"] == "unknown" or byte_status != "intact",
            latest["error_code"],
            UUID(latest["registration_id"]) if latest["registration_id"] else None,
            latest["terminal_evidence_ref"],
        )

    def _checkpoint(self, stage, entry):
        """Fault-window hook for package-local synthetic storage tests only."""

    def put_new(self, content: bytes, *, media_type: str):
        raise StorageFailure("UNSCOPED_UPLOAD", "Server-bound scoped upload required")

    def put_scoped(
        self,
        content: bytes,
        *,
        media_type: str,
        tenant_id: UUID,
        product_id: UUID | None,
        requester_id: UUID,
        upload_id: UUID,
        category_id: UUID | None = None,
    ) -> ObjectRef:
        scope = JournalScope(tenant_id, product_id, category_id if product_id is None else None)
        _identity(requester_id)
        _identity(upload_id)
        if not isinstance(content, bytes) or not content or len(content) > self.max_bytes:
            raise StorageFailure("INVALID_BYTES", "Nonempty bounded original bytes required")
        if media_type not in SUPPORTED_MEDIA:
            raise StorageFailure("UNSUPPORTED_MEDIA_TYPE", "Unsupported original media type")
        basis = self._basis(scope, requester_id, upload_id, content, media_type)
        with self._locked(upload_id):
            try:
                entry, actual_scope, requester, ref = self._entry(upload_id)
            except StorageFailure as exc:
                if exc.code != "JOURNAL_NOT_FOUND":
                    raise
                entry = {**basis, "created_at": datetime.now(UTC).isoformat()}
                entry["binding_sha256"] = _digest(entry)
                try:
                    self._write_new(("journal", upload_id.hex, "entry.json"), _encoded(entry))
                    self._checkpoint("metadata_durable", entry)
                    values = dict(basis["reference"])
                    values["id"] = upload_id
                    ref = ObjectRef(**values)
                    self._write_new(tuple(ref.server_storage_key.split("/")), content)
                    self._checkpoint("bytes_durable", entry)
                    self._append(entry, self._latest(entry), "bytes_written")
                    self._checkpoint("bytes_written_durable", entry)
                    return ref
                except Exception:
                    # Never label a crash/short write not-applied or infer orphan.
                    # The already fsynced binding remains for exact observation.
                    try:
                        current, _, _, _ = self._entry(upload_id)
                        last = self._latest(current)
                        if last["state"] != "bytes_written":
                            self._append(
                                current, last, "unknown", error_code="UPLOAD_OUTCOME_UNKNOWN"
                            )
                    except Exception:
                        pass
                    raise StorageFailure(
                        "UPLOAD_OUTCOME_UNKNOWN", "Upload outcome requires exact observation"
                    ) from None
            actual_basis = {
                k: v for k, v in entry.items() if k not in {"created_at", "binding_sha256"}
            }
            if actual_basis != basis:
                raise StorageFailure(
                    "UPLOAD_BINDING_CONFLICT", "Upload ID binds different scope or bytes"
                )
            latest = self._latest(entry)
            if latest["state"] == "aborted":
                raise StorageFailure(
                    "UPLOAD_ABORTED", "Stored upload has a terminal database outcome"
                )
            if self._bytes(ref)[0] != "intact":
                raise StorageFailure(
                    "UPLOAD_OUTCOME_UNKNOWN", "Retained original cannot be positively verified"
                )
            if latest["state"] in {"prepared", "unknown"}:
                self._append(entry, latest, "bytes_written")
            # Positive replay verifies existing bytes; it never writes bytes again.
            return ref

    def inspect(self, upload_id: UUID) -> UploadInspection:
        _identity(upload_id)
        with self._locked(upload_id, shared=True):
            entry, scope, requester, ref = self._entry(upload_id)
            return self._inspection(entry, scope, requester, ref)

    def lookup_original(self, reference: ObjectRef, scope: JournalScope) -> UploadInspection:
        if not isinstance(reference, ObjectRef) or not isinstance(scope, JournalScope):
            raise ValueError("Exact server reference and scope required")
        result = self.inspect(reference.id)
        if result.reference != reference or result.scope != scope:
            raise StorageFailure(
                "UPLOAD_BINDING_CONFLICT", "Original journal scope or bytes differ"
            )
        return result

    def read_original(self, reference: ObjectRef) -> bytes:
        if not isinstance(reference, ObjectRef):
            raise ValueError("Exact original ObjectRef required")
        with self._locked(reference.id, shared=True):
            entry, _, _, actual = self._entry(reference.id)
            # This byte owner does not require a registered DB marker. A failed
            # post-commit marker must leave exact bytes available to the root's
            # separately authorized reader; inspection still reports warnings.
            if actual != reference:
                raise StorageFailure(
                    "UPLOAD_BINDING_CONFLICT", "Original identity differs from journal"
                )
            state, content = self._bytes(actual)
            if state != "intact":
                raise StorageFailure("INTEGRITY_MISMATCH", "Retained original cannot be verified")
            return content

    @staticmethod
    def _evidence(value):
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 200
            or any(ord(c) < 32 for c in value)
        ):
            raise ValueError("Bounded trusted terminal evidence reference required")

    def _terminal(
        self,
        upload_id,
        reference,
        *,
        state,
        registration_id=None,
        terminal_evidence_ref=None,
        reason_code=None,
    ):
        _identity(upload_id)
        if not isinstance(reference, ObjectRef) or reference.id != upload_id:
            raise StorageFailure("UPLOAD_BINDING_CONFLICT", "Exact upload reference required")
        with self._locked(upload_id):
            entry, scope, requester, actual = self._entry(upload_id)
            if actual != reference:
                raise StorageFailure(
                    "UPLOAD_BINDING_CONFLICT", "Terminal fact binds different bytes"
                )
            latest = self._latest(entry)
            if latest["state"] in {"registered", "aborted"}:
                if (
                    latest["state"] != state
                    or latest["registration_id"]
                    != (str(registration_id) if registration_id else None)
                    or latest["terminal_evidence_ref"] != terminal_evidence_ref
                    or latest["error_code"] != reason_code
                ):
                    raise StorageFailure(
                        "REGISTRATION_CONFLICT", "Terminal database evidence cannot change"
                    )
                return self._inspection(entry, scope, requester, actual, latest)
            if state == "registered" and self._bytes(actual)[0] != "intact":
                raise StorageFailure(
                    "INTEGRITY_MISMATCH", "Registration marker requires verified retained bytes"
                )
            latest = self._append(
                entry,
                latest,
                state,
                error_code=reason_code,
                registration_id=registration_id,
                evidence=terminal_evidence_ref,
            )
            return self._inspection(entry, scope, requester, actual, latest)

    def mark_registered(
        self, upload_id: UUID, reference: ObjectRef, *, registration_id: UUID | None = None
    ):
        if registration_id is not None:
            _identity(registration_id)
        return self._terminal(
            upload_id, reference, state="registered", registration_id=registration_id
        )

    def mark_aborted(
        self, upload_id: UUID, reference: ObjectRef, *, terminal_evidence_ref: str, reason_code: str
    ):
        """Only caller-proven terminal DB outcome; no automatic failure inference."""
        self._evidence(terminal_evidence_ref)
        if not isinstance(reason_code, str) or not _CODE.fullmatch(reason_code):
            raise ValueError("Bounded machine reason code required")
        return self._terminal(
            upload_id,
            reference,
            state="aborted",
            terminal_evidence_ref=terminal_evidence_ref,
            reason_code=reason_code,
        )

    @staticmethod
    def _cursor(scope, upload_id):
        return f"{_digest(scope.to_dict())}:{upload_id.hex}"

    def inventory(
        self, scope: JournalScope, *, limit: int = 100, cursor: str | None = None
    ) -> InventoryPage:
        if (
            not isinstance(scope, JournalScope)
            or type(limit) is not int
            or not 1 <= limit <= self.inventory_limit
        ):
            raise ValueError("Exact scope and bounded inventory limit required")
        after = ""
        if cursor is not None:
            expected = f"{_digest(scope.to_dict())}:"
            if (
                not isinstance(cursor, str)
                or not cursor.startswith(expected)
                or not _HEX.fullmatch(cursor[len(expected) :])
            ):
                raise ValueError("Inventory cursor must bind scope")
            after = cursor[len(expected) :]
        with self._locked(shared=True):
            with self._directory(("journal",)) as folder:
                names = []
                truncated = False
                with os.scandir(folder) as entries:
                    for item in entries:
                        if len(names) == self.max_inventory_entries:
                            truncated = True
                            break
                        names.append(item.name)
            # Truncated enumeration is not a complete or safely pageable list.
            if truncated:
                return InventoryPage(scope, (), True, None, False, 1)
            values, unavailable = [], 0
            for name in sorted(names):
                if not _HEX.fullmatch(name):
                    unavailable += 1
                    continue
                try:
                    entry, actual_scope, requester, ref = self._entry(UUID(hex=name))
                    if actual_scope == scope:
                        value = self._inspection(entry, actual_scope, requester, ref)
                        if name > after:
                            values.append(value)
                except StorageFailure:
                    # A corrupt binding cannot safely be assigned to another
                    # tenant or silently excluded as irrelevant to this scope.
                    unavailable += 1
            has_more = len(values) > limit
            selected = tuple(values[:limit])
            next_cursor = self._cursor(scope, selected[-1].upload_id) if has_more else None
            return InventoryPage(
                scope,
                selected,
                has_more,
                next_cursor,
                not has_more and unavailable == 0,
                unavailable,
            )
