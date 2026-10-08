"""Server-injected local reversible access isolation. No purge or permission grant."""

import json
import math
import os
import re
import selectors
import subprocess
import sys
import time
from pathlib import Path

from pdos_next.object_journal import JournaledLocalObjectStore
from pdos_next.object_storage.types import ObjectRef, StorageFailure
from pdos_next.original_lifecycle.service import SystemClock
from pdos_next.original_lifecycle.types import (
    Disposition,
    EffectOutcome,
    EffectPermit,
    EffectReceipt,
    LifecycleScope,
    aware,
    exact_reference,
)

from .protocol import LegacyReadReference, encode

_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")


class LocalReversibleLifecycleAdapter:
    """Keep exact bytes; isolate access with a durable marker and one-attempt proof.

    `gate` is required trusted mainline code, not a permission fact supplied by a
    document or caller. It must hold the same protection lock through this entire
    call. `ensure_readable` is a storage guard only; the caller must independently
    hold its current authorization/DB object gate until the real byte read ends.
    """

    def __init__(self, journal_store, gate, *, clock=None, io_timeout_seconds=5):
        if not isinstance(journal_store, JournaledLocalObjectStore) or not callable(gate):
            raise ValueError("The private journal byte owner and trusted gate are required")
        if (
            type(io_timeout_seconds) not in (int, float)
            or not math.isfinite(io_timeout_seconds)
            or not 0 < io_timeout_seconds <= 10
        ):
            raise ValueError("Storage I/O must have a finite bounded deadline")
        self.journal_store, self.gate = journal_store, gate
        self.clock = clock if clock is not None else SystemClock()
        self.io_timeout_seconds = io_timeout_seconds

    def _script(self):
        package_root = str(Path(__file__).resolve().parents[2])
        return (
            "import sys; sys.path.insert(0, " + repr(package_root) + "); "
            "from pdos_next.object_lifecycle_runtime.worker import main; main()"
        )

    def _request(self, action, value, budget):
        now = self.clock.now()
        aware(now)
        return {
            "action": action,
            "root": str(self.journal_store.root),
            "value": encode(value),
            "now": now.isoformat(),
            "timeout_seconds": budget,
        }

    def _run(self, request, budget):
        content = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode()
        if len(content) > 32_768:
            return {"error_code": "LIFECYCLE_PROTOCOL_ERROR"}
        process = None
        deadline = time.monotonic() + budget
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", self._script()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"LANG": "C.UTF-8"},
                start_new_session=True,
            )
            assert process.stdin is not None and process.stdout is not None
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
            output, position = bytearray(), 0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdin, selectors.EVENT_WRITE, "input")
                selector.register(process.stdout, selectors.EVENT_READ, "output")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return {"error_code": "LIFECYCLE_IO_TIMEOUT"}
                    for key, _ in selector.select(remaining):
                        if key.data == "input":
                            try:
                                position += os.write(key.fd, content[position:])
                            except BrokenPipeError:
                                position = len(content)
                            if position == len(content):
                                selector.unregister(process.stdin)
                                process.stdin.close()
                        else:
                            chunk = os.read(key.fd, 4_096)
                            if not chunk:
                                selector.unregister(process.stdout)
                            elif len(output) + len(chunk) > 8_192:
                                return {"error_code": "LIFECYCLE_PROTOCOL_ERROR"}
                            else:
                                output.extend(chunk)
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            if process.returncode != 0:
                return {"error_code": "LIFECYCLE_ATTEMPT_UNKNOWN"}
            response = json.loads(output)
            if not isinstance(response, dict):
                raise ValueError("Invalid response")
            return response
        except subprocess.TimeoutExpired:
            return {"error_code": "LIFECYCLE_IO_TIMEOUT"}
        except (OSError, ValueError, TypeError):
            return {"error_code": "LIFECYCLE_STORAGE_UNKNOWN"}
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                # Output is read incrementally. On failure discard pipes after kill
                # and reap before releasing the mainline protection gate.
                for stream in (process.stdin, process.stdout):
                    if stream is not None and not stream.closed:
                        stream.close()
                process.wait()

    def _receipt(self, item, response):
        now = self.clock.now()
        aware(now)
        code = response.get("error_code")
        if code is not None:
            if not isinstance(code, str) or _CODE.fullmatch(code) is None:
                code = "LIFECYCLE_PROTOCOL_ERROR"
            return EffectReceipt(
                item.operation_id,
                item.reference,
                item.scope,
                item.lease_token,
                EffectOutcome.UNKNOWN,
                None,
                False,
                now,
                "local-effects-v1:unknown",
                code,
            )
        try:
            if response["integrity_verified"] is not True or set(response) != {
                "outcome",
                "disposition",
                "integrity_verified",
                "revision",
                "error_code",
                "binding",
            }:
                raise ValueError("Invalid result binding")
            if (
                response["binding"]
                != {
                    "operation_id": str(item.operation_id),
                    "reference": encode(item.reference),
                    "scope": encode(item.scope),
                    "lease_token": str(item.lease_token),
                }
                or re.fullmatch(r"local-effects-v1:[0-9a-f]{64}", response["revision"]) is None
            ):
                raise ValueError("Result binds a different stored attempt")
            return EffectReceipt(
                item.operation_id,
                item.reference,
                item.scope,
                item.lease_token,
                EffectOutcome(response["outcome"]),
                Disposition(response["disposition"]),
                True,
                now,
                response["revision"],
                None,
            )
        except (ValueError, KeyError, TypeError):
            return self._receipt(item, {"error_code": "LIFECYCLE_PROTOCOL_ERROR"})

    def apply_once(self, item: EffectPermit) -> EffectReceipt:
        if not isinstance(item, EffectPermit):
            raise ValueError("An exact stored server effect permit is required")
        with self.gate(item, observation=False):
            now = self.clock.now()
            aware(now)
            if now < item.issued_at or now >= item.expires_at:
                return self._receipt(item, {"error_code": "EFFECT_PERMIT_EXPIRED"})
            budget = min(self.io_timeout_seconds, (item.expires_at - now).total_seconds())
            return self._receipt(item, self._run(self._request("apply", item, budget), budget))

    def observe(self, item: EffectPermit) -> EffectReceipt:
        if not isinstance(item, EffectPermit):
            raise ValueError("An exact stored effect permit is required")
        with self.gate(item, observation=True):
            return self._receipt(
                item,
                self._run(
                    self._request("observe", item, self.io_timeout_seconds), self.io_timeout_seconds
                ),
            )

    def ensure_readable(self, ref: ObjectRef) -> None:
        exact_reference(ref)
        response = self._run(
            self._request("readable", ref, self.io_timeout_seconds), self.io_timeout_seconds
        )
        self._read_response(response)

    def ensure_legacy_readable(self, ref: ObjectRef, scope: LifecycleScope) -> None:
        """Root-only bridge for currently authorized, DB-registered legacy bytes.

        The caller supplies the exact scope from the registered original under
        its DB gate. No journal means this adapter has no independent scope
        evidence; it neither infers registration nor accepts caller policy facts.
        Existing journal or any lifecycle history makes this bridge unavailable.
        """
        exact_reference(ref)
        if not isinstance(scope, LifecycleScope):
            raise ValueError("Legacy scope must be bound from the registered database object")
        response = self._run(
            self._request(
                "legacy_readable", LegacyReadReference(ref, scope), self.io_timeout_seconds
            ),
            self.io_timeout_seconds,
        )
        self._read_response(response)

    @staticmethod
    def _read_response(response):
        if response != {"readable": True}:
            code = response.get("error_code", "LIFECYCLE_PROTOCOL_ERROR")
            if not isinstance(code, str) or _CODE.fullmatch(code) is None:
                code = "LIFECYCLE_PROTOCOL_ERROR"
            raise StorageFailure(code, "原件访问隔离状态待核对或仍受保护。")
