"""One-attempt byte-preserving access effects and conservative historical proofs."""

import re
import time
from datetime import UTC, datetime, timedelta

from pdos_next.object_journal import JournalScope
from pdos_next.object_storage.types import StorageFailure
from pdos_next.original_lifecycle.types import LifecycleAction

from .files import PrivateFiles, RuntimeFailure, digest, seal
from .protocol import encode
from .protocol import permit as decode_permit

SCHEMA = "pdos-local-lifecycle-effects-v1"
_ATTEMPT = re.compile(r"attempt-([0-9a-f]{32})\.json\Z")
_TERMINAL = re.compile(r"terminal-([0-9a-f]{32})\.json\Z")
_EVENT = re.compile(r"event-([0-9]{6})\.json\Z")


class EffectFiles:
    def __init__(self, journal, *, now, deadline):
        self.journal, self.now, self.started = journal, now, time.monotonic()
        self.files = PrivateFiles(journal.root, deadline)

    def close(self):
        self.files.close()

    def _time(self):
        return (self.now + timedelta(seconds=time.monotonic() - self.started)).isoformat()

    def _checkpoint(self, stage):
        """Test subclasses may terminate here. Runtime input cannot select a fault."""

    @staticmethod
    def _object(ref):
        return ("objects", ref.id.hex)

    @staticmethod
    def _operation(operation_id):
        return ("operations", operation_id.hex + ".json")

    def _integrity(self, ref, scope):
        self.files.check()
        try:
            inspection = self.journal.lookup_original(
                ref,
                JournalScope(
                    scope.tenant_id,
                    scope.product_id,
                    scope.category_id if scope.product_id is None else None,
                ),
            )
        except StorageFailure as exc:
            code = (
                "LIFECYCLE_BINDING_CONFLICT"
                if exc.code == "UPLOAD_BINDING_CONFLICT"
                else "LIFECYCLE_INTEGRITY_UNAVAILABLE"
            )
            raise RuntimeFailure(code) from None
        if inspection.byte_status != "intact":
            raise RuntimeFailure("LIFECYCLE_INTEGRITY_UNAVAILABLE")
        # The underlying byte owner is forensic only here. Exact bytes never leave
        # this process or bypass the application's ordinary read/scan/source gates.
        content = self.journal.read_original(ref)
        if len(content) != ref.size_bytes:
            raise RuntimeFailure("LIFECYCLE_INTEGRITY_UNAVAILABLE")
        del content
        self.files.check()

    @staticmethod
    def _identity(record, ref, scope):
        if (
            record["schema"] != SCHEMA
            or record["reference"] != encode(ref)
            or record["scope"] != encode(scope)
        ):
            raise RuntimeFailure("LIFECYCLE_BINDING_CONFLICT")

    def _base(self, ref, scope, *, create=False):
        folder = self._object(ref)
        names = self.files.names(folder)
        base = self.files.read((*folder, "base.json"))
        if base is None:
            if names:
                raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT")
            # A missing object directory is not proof that it was never isolated.
            # Retained global bindings independently fence lost per-object logs.
            for name in self.files.names(("operations",)) or ():
                if re.fullmatch(r"[0-9a-f]{32}\.json", name) is None:
                    raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT")
                record = self.files.read(("operations", name))
                previous = decode_permit(record["permit"])
                if (
                    record["schema"] != SCHEMA
                    or digest(record["permit"]) != record["permit_sha256"]
                ):
                    raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT")
                if previous.reference.id == ref.id:
                    raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
            if not create:
                return None
            base = seal(
                {
                    "schema": SCHEMA,
                    "reference": encode(ref),
                    "scope": encode(scope),
                    "sequence": 0,
                    "disposition": "active",
                    "previous_sha256": None,
                    "operation_id": None,
                    "lease_token": None,
                    "permit_sha256": None,
                    "created_at": self._time(),
                }
            )
            self.files.write_new((*folder, "base.json"), base)
            self._checkpoint("after_base")
            self.files.write_new((*folder, "head.json"), base)
        self._identity(base, ref, scope)
        if (
            base["sequence"] != 0
            or base["disposition"] != "active"
            or base["operation_id"] is not None
        ):
            raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT")
        return base

    def _history(self, ref, scope, base):
        folder = self._object(ref)
        head = self.files.read((*folder, "head.json"))
        if head is None:
            raise RuntimeFailure("LIFECYCLE_MARKER_UNKNOWN")
        self._identity(head, ref, scope)
        if type(head["sequence"]) is not int or not 0 <= head["sequence"] <= 1_000:
            raise RuntimeFailure("LIFECYCLE_METADATA_LIMIT")
        history = {base["sha256"]: base}
        prior = base
        for index in range(1, head["sequence"] + 1):
            event = self.files.read((*folder, f"event-{index:06}.json"))
            if event is None:
                raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
            self._identity(event, ref, scope)
            if (
                event["sequence"] != index
                or event["previous_sha256"] != prior["sha256"]
                or event["disposition"] not in ("active", "quarantined")
            ):
                raise RuntimeFailure("LIFECYCLE_HISTORY_CONFLICT")
            history[event["sha256"]] = event
            prior = event
        if head != prior:
            raise RuntimeFailure("LIFECYCLE_MARKER_CONFLICT")
        return head, history

    def _records(self, ref, scope, history):
        folder = self._object(ref)
        attempts, terminals, events = {}, {}, []
        for name in self.files.names(folder) or ():
            matched = _ATTEMPT.fullmatch(name)
            if matched:
                value = self.files.read((*folder, name))
                item = decode_permit(value["permit"])
                if (
                    item.reference != ref
                    or item.scope != scope
                    or item.operation_id.hex != matched[1]
                    or value["schema"] != SCHEMA
                    or value["permit_sha256"] != digest(value["permit"])
                ):
                    raise RuntimeFailure("LIFECYCLE_BINDING_CONFLICT")
                global_binding = self.files.read(self._operation(item.operation_id))
                if (
                    global_binding is None
                    or global_binding["schema"] != SCHEMA
                    or global_binding["permit"] != value["permit"]
                    or global_binding["permit_sha256"] != value["permit_sha256"]
                ):
                    raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
                if value["before_sha256"] not in history:
                    raise RuntimeFailure("LIFECYCLE_HISTORY_CONFLICT")
                attempts[matched[1]] = value
            elif matched := _TERMINAL.fullmatch(name):
                terminals[matched[1]] = self.files.read((*folder, name))
            elif matched := _EVENT.fullmatch(name):
                events.append(self.files.read((*folder, name)))
            elif name not in ("base.json", "head.json") and not re.fullmatch(
                r"head-[0-9a-f]{32}\.tmp", name
            ):
                raise RuntimeFailure("LIFECYCLE_METADATA_CORRUPT")
        for key, terminal in terminals.items():
            attempt = attempts.get(key)
            if (
                attempt is None
                or terminal["schema"] != SCHEMA
                or terminal["attempt_sha256"] != attempt["sha256"]
                or terminal["permit_sha256"] != attempt["permit_sha256"]
            ):
                raise RuntimeFailure("LIFECYCLE_HISTORY_CONFLICT")
            if terminal["outcome"] == "applied":
                marker = history.get(terminal["marker_sha256"])
                item = decode_permit(attempt["permit"])
                target = "quarantined" if item.action == LifecycleAction.QUARANTINE else "active"
                if (
                    marker is None
                    or marker["operation_id"] != str(item.operation_id)
                    or marker["lease_token"] != str(item.lease_token)
                    or marker["permit_sha256"] != attempt["permit_sha256"]
                    or marker["disposition"] != target
                    or marker["previous_sha256"] != attempt["before_sha256"]
                    or terminal["event_sha256"] != marker["sha256"]
                ):
                    raise RuntimeFailure("LIFECYCLE_HISTORY_CONFLICT")
            elif terminal["outcome"] == "not_applied":
                if (
                    terminal["marker_sha256"] != attempt["before_sha256"]
                    or terminal["event_sha256"] is not None
                ):
                    raise RuntimeFailure("LIFECYCLE_HISTORY_CONFLICT")
            else:
                raise RuntimeFailure("LIFECYCLE_HISTORY_CONFLICT")
        for event in events:
            # An event not selected by a fully corroborated head is an interrupted
            # transition, never evidence that no effect happened.
            if event["sha256"] not in history:
                raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
            operation = event["operation_id"].replace("-", "")
            if operation not in terminals or terminals[operation]["outcome"] != "applied":
                raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
        if set(attempts) != set(terminals):
            raise RuntimeFailure("LIFECYCLE_ATTEMPT_UNKNOWN")
        return attempts, terminals

    @staticmethod
    def _result(outcome, disposition, proof, *, error=None):
        return {
            "outcome": outcome,
            "disposition": disposition,
            "integrity_verified": True,
            "revision": "local-effects-v1:" + proof,
            "error_code": error,
        }

    def apply(self, item):
        data, permit_hash = encode(item), digest(encode(item))
        folder = self._object(item.reference)
        with self.files.locked(item.reference.id, item.operation_id):
            self._integrity(item.reference, item.scope)
            global_binding = self.files.read(self._operation(item.operation_id))
            if global_binding is not None and global_binding["permit"] != data:
                raise RuntimeFailure("LIFECYCLE_BINDING_CONFLICT")
            base = self._base(item.reference, item.scope, create=True)
            head, history = self._history(item.reference, item.scope, base)
            attempts, terminals = self._records(item.reference, item.scope, history)
            key = item.operation_id.hex
            self._integrity(item.reference, item.scope)
            if key in attempts:
                if attempts[key]["permit"] != data:
                    raise RuntimeFailure("LIFECYCLE_BINDING_CONFLICT")
                terminal = terminals[key]
                result_marker = history[terminal["marker_sha256"]]
                return self._result(
                    terminal["outcome"], result_marker["disposition"], terminal["sha256"]
                )
            if len(attempts) >= 1_000:
                raise RuntimeFailure("LIFECYCLE_METADATA_LIMIT")
            attempt = seal(
                {
                    "schema": SCHEMA,
                    "permit": data,
                    "permit_sha256": permit_hash,
                    "before_sha256": head["sha256"],
                    "sequence": head["sequence"] + 1,
                    "created_at": self._time(),
                }
            )
            # Durable attempt is written before any access-marker transition.
            self.files.write_new((*folder, f"attempt-{key}.json"), attempt)
            self._checkpoint("after_attempt")
            if global_binding is None:
                self.files.write_new(
                    self._operation(item.operation_id),
                    seal(
                        {
                            "schema": SCHEMA,
                            "permit": data,
                            "permit_sha256": permit_hash,
                            "created_at": self._time(),
                        }
                    ),
                )
            self._checkpoint("after_binding")
            expected = "active" if item.action == LifecycleAction.QUARANTINE else "quarantined"
            if head["disposition"] != expected:
                # Positive durable proof from this controlled code path, holding
                # the object gate: the access marker was never changed.
                terminal = seal(
                    {
                        "schema": SCHEMA,
                        "attempt_sha256": attempt["sha256"],
                        "permit_sha256": permit_hash,
                        "outcome": "not_applied",
                        "marker_sha256": head["sha256"],
                        "event_sha256": None,
                        "completed_at": self._time(),
                    }
                )
                self.files.write_new((*folder, f"terminal-{key}.json"), terminal)
                return self._result("not_applied", head["disposition"], terminal["sha256"])
            if (
                datetime.fromisoformat(self._time()) >= item.expires_at
                or datetime.now(UTC) >= item.expires_at
            ):
                raise RuntimeFailure("EFFECT_PERMIT_EXPIRED")
            marker = seal(
                {
                    **{name: value for name, value in head.items() if name != "sha256"},
                    "sequence": head["sequence"] + 1,
                    "disposition": "quarantined"
                    if item.action == LifecycleAction.QUARANTINE
                    else "active",
                    "previous_sha256": head["sha256"],
                    "operation_id": str(item.operation_id),
                    "lease_token": str(item.lease_token),
                    "permit_sha256": permit_hash,
                    "created_at": self._time(),
                }
            )
            self.files.write_new((*folder, f"event-{marker['sequence']:06}.json"), marker)
            self._checkpoint("before_marker")
            self.files.replace_head((*folder, "head.json"), marker)
            self._checkpoint("after_marker")
            self._integrity(item.reference, item.scope)
            terminal = seal(
                {
                    "schema": SCHEMA,
                    "attempt_sha256": attempt["sha256"],
                    "permit_sha256": permit_hash,
                    "outcome": "applied",
                    "marker_sha256": marker["sha256"],
                    "event_sha256": marker["sha256"],
                    "completed_at": self._time(),
                }
            )
            self.files.write_new((*folder, f"terminal-{key}.json"), terminal)
            self._checkpoint("after_terminal")
            return self._result("applied", marker["disposition"], terminal["sha256"])

    def observe(self, item):
        with self.files.locked(item.reference.id, item.operation_id, shared=True):
            base = self._base(item.reference, item.scope)
            if base is None:
                raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
            _, history = self._history(item.reference, item.scope, base)
            attempts, terminals = self._records(item.reference, item.scope, history)
            attempt, terminal = (
                attempts.get(item.operation_id.hex),
                terminals.get(item.operation_id.hex),
            )
            if attempt is None or terminal is None:
                raise RuntimeFailure("LIFECYCLE_HISTORY_UNKNOWN")
            if attempt["permit"] != encode(item):
                raise RuntimeFailure("LIFECYCLE_BINDING_CONFLICT")
            self._integrity(item.reference, item.scope)
            # A later valid restore corroborates the earlier quarantine history.
            # An uncorroborated marker change makes _history/_records fail closed.
            marker = history[terminal["marker_sha256"]]
            return self._result(terminal["outcome"], marker["disposition"], terminal["sha256"])

    def ensure_readable(self, ref):
        with self.files.locked(ref.id, shared=True):
            inspection = self.journal.inspect(ref.id)
            if inspection.reference != ref:
                raise RuntimeFailure("LIFECYCLE_BINDING_CONFLICT")
            if inspection.byte_status != "intact":
                raise RuntimeFailure("LIFECYCLE_INTEGRITY_UNAVAILABLE")
            from pdos_next.original_lifecycle.types import LifecycleScope

            scope = LifecycleScope(
                inspection.scope.tenant_id,
                inspection.scope.product_id,
                inspection.scope.category_id,
            )
            base = self._base(ref, scope)
            if base is None:
                return {"readable": True}
            head, history = self._history(ref, scope, base)
            self._records(ref, scope, history)
            if head["disposition"] != "active":
                raise RuntimeFailure("OBJECT_ACCESS_QUARANTINED")
            return {"readable": True}

    def ensure_legacy_readable(self, ref, scope):
        with self.files.locked(ref.id, shared=True):
            # This is only for a missing upload journal. Unknown/corrupt journals
            # and ordinary journal-backed reads must not select the legacy path.
            try:
                self.journal.inspect(ref.id)
            except StorageFailure as exc:
                if exc.code != "JOURNAL_NOT_FOUND":
                    raise RuntimeFailure("LIFECYCLE_INTEGRITY_UNAVAILABLE") from None
            else:
                raise RuntimeFailure("LEGACY_BRIDGE_NOT_APPLICABLE")
            # An active marker is still lifecycle history, not evidence that the
            # object can bypass the normal journal/protection path. _base also
            # checks independent global bindings when the object log is missing.
            if self._base(ref, scope) is not None:
                raise RuntimeFailure("LEGACY_LIFECYCLE_HISTORY_PRESENT")
            from pdos_next.object_storage.adapters import LocalPrivateObjectStore

            self.files.check()
            content = LocalPrivateObjectStore(
                self.journal.root, max_bytes=self.journal.max_bytes
            ).read_original(ref)
            del content
            self.files.check()
            return {"readable": True}


def process(request):
    """Trusted worker entry; every failure is conservative and contains no bytes."""
    from pdos_next.object_journal import JournaledLocalObjectStore

    journal, effects = None, None
    try:
        if set(request) != {"action", "root", "value", "now", "timeout_seconds"}:
            raise RuntimeFailure("LIFECYCLE_PROTOCOL_ERROR")
        now = datetime.fromisoformat(request["now"])
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeFailure("LIFECYCLE_PROTOCOL_ERROR")
        budget = request["timeout_seconds"]
        if type(budget) not in (int, float) or not 0 < budget <= 10:
            raise RuntimeFailure("LIFECYCLE_PROTOCOL_ERROR")
        journal = JournaledLocalObjectStore(request["root"])
        effects = EffectFiles(journal, now=now.astimezone(UTC), deadline=time.monotonic() + budget)
        if request["action"] == "readable":
            from .protocol import reference

            return effects.ensure_readable(reference(request["value"]))
        if request["action"] == "legacy_readable":
            from pdos_next.original_lifecycle.types import LifecycleScope

            from .protocol import reference

            value = request["value"]
            if set(value) != {"reference", "scope"}:
                raise RuntimeFailure("LIFECYCLE_PROTOCOL_ERROR")
            from uuid import UUID

            scope = LifecycleScope(
                **{key: UUID(item) if item else None for key, item in value["scope"].items()}
            )
            return effects.ensure_legacy_readable(reference(value["reference"]), scope)
        item = decode_permit(request["value"])
        if request["action"] == "apply":
            if now < item.issued_at or now >= item.expires_at:
                raise RuntimeFailure("EFFECT_PERMIT_EXPIRED")
            result = effects.apply(item)
        elif request["action"] == "observe":
            result = effects.observe(item)
        else:
            raise RuntimeFailure("LIFECYCLE_PROTOCOL_ERROR")
        return {
            **result,
            "binding": {
                "operation_id": str(item.operation_id),
                "reference": encode(item.reference),
                "scope": encode(item.scope),
                "lease_token": str(item.lease_token),
            },
        }
    except RuntimeFailure as exc:
        return {"error_code": exc.code}
    except Exception:
        return {"error_code": "LIFECYCLE_STORAGE_UNKNOWN"}
    finally:
        if effects is not None:
            effects.close()
        if journal is not None:
            journal.close()
