"""Injectable local scan adapter. No scanner configured means unavailable, never clean."""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

from pdos_next.object_storage.types import ObjectStore, StorageFailure

from .preflight import SUPPORTED_MEDIA, check_content
from .types import (
    ScannerReply,
    ScanReceipt,
    ScanRequest,
    ScanStatus,
    ScanTransportPort,
    SecurityFailure,
)


class ObjectStoreScannerAdapter:
    """Byte reader + deterministic preflight + injected local asynchronous transport.

    The ObjectStore implementation must bound byte reads and its own I/O timeout. An expired
    read is not killable by Python; its capacity slot remains held until the trusted read ends.
    Max in-flight reads and transports are bounded even across repeated timeouts. Timed-out
    transports are cancelled without waiting for cancellation; late output is discarded.
    Construct per worker/event loop; transport must not block the loop. This is not an OS sandbox.
    """

    def __init__(
        self,
        store: ObjectStore,
        transport: ScanTransportPort | None = None,
        *,
        max_inflight_reads: int = 2,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if type(max_inflight_reads) is not int or not 1 <= max_inflight_reads <= 8:
            raise ValueError("Reader concurrency must be bounded")
        self.store, self.transport, self.clock = store, transport, clock
        self._capacity = asyncio.Semaphore(max_inflight_reads)
        self._reads: set[asyncio.Task] = set()
        self._scan_capacity = asyncio.Semaphore(max_inflight_reads)
        self._scans: set[asyncio.Task] = set()

    async def _read(self, request: ScanRequest, deadline: float) -> bytes:
        await asyncio.wait_for(self._capacity.acquire(), max(0, deadline - time.monotonic()))
        task = asyncio.create_task(
            asyncio.to_thread(self.store.read_original, request.binding.object_ref)
        )
        self._reads.add(task)

        def finished(result):
            self._reads.discard(result)
            self._capacity.release()
            if not result.cancelled():
                result.exception()  # Consume late read errors after caller timeout.

        task.add_done_callback(finished)
        return await asyncio.wait_for(asyncio.shield(task), max(0, deadline - time.monotonic()))

    async def _inspect(self, request: ScanRequest, content: bytes, deadline: float) -> ScannerReply:
        assert self.transport is not None
        await asyncio.wait_for(self._scan_capacity.acquire(), max(0, deadline - time.monotonic()))

        async def invoke():
            return await self.transport.inspect(request, content)

        task = asyncio.create_task(invoke())
        self._scans.add(task)

        def finished(result):
            self._scans.discard(result)
            self._scan_capacity.release()
            if not result.cancelled():
                result.exception()

        task.add_done_callback(finished)
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline - time.monotonic()))
            if not done:
                task.cancel()
                raise TimeoutError
            if task.cancelled():
                raise RuntimeError("Scanner cancelled its own scan")
            return task.result()
        except asyncio.CancelledError:
            task.cancel()
            raise

    async def scan(self, request: ScanRequest) -> ScanReceipt:
        started = self.clock()
        deadline = time.monotonic() + request.policy.limits.timeout_seconds
        status, code = ScanStatus.UNKNOWN, "SCAN_PROTOCOL_ERROR"
        try:
            if not request.binding.source_active:
                raise SecurityFailure("SOURCE_UNAVAILABLE")
            ref = request.binding.object_ref
            if ref.size_bytes > request.policy.limits.max_input_bytes:
                raise SecurityFailure("FILE_TOO_LARGE")
            if ref.media_type not in SUPPORTED_MEDIA:
                raise SecurityFailure("UNSUPPORTED_MEDIA_TYPE")
            content = await self._read(request, deadline)
            check_content(request, content, deadline=deadline)
            if self.transport is None:
                status, code = ScanStatus.UNAVAILABLE, "SCANNER_UNAVAILABLE"
            else:
                reply = await self._inspect(request, content, deadline)
                if time.monotonic() > deadline:
                    raise SecurityFailure("SCAN_TIMEOUT")
                if (
                    not isinstance(reply, ScannerReply)
                    or reply.request_id != request.request_id
                    or reply.object_ref != ref
                    or reply.scanner != request.scanner
                    or reply.status == ScanStatus.REJECTED
                ):
                    raise SecurityFailure("SCAN_PROTOCOL_ERROR")
                status, code = reply.status, reply.error_code
                if status != ScanStatus.CLEAN and code is None:
                    code = {
                        ScanStatus.INFECTED: "MALWARE_DETECTED",
                        ScanStatus.UNKNOWN: "SCAN_RESULT_UNKNOWN",
                        ScanStatus.UNAVAILABLE: "SCANNER_UNAVAILABLE",
                        ScanStatus.TIMEOUT: "SCAN_TIMEOUT",
                    }[status]
        except TimeoutError:
            status, code = ScanStatus.TIMEOUT, "SCAN_TIMEOUT"
        except SecurityFailure as exc:
            code = exc.code
            status = (
                ScanStatus.TIMEOUT
                if code == "SCAN_TIMEOUT"
                else ScanStatus.UNKNOWN
                if code == "SCAN_PROTOCOL_ERROR"
                else ScanStatus.REJECTED
            )
        except StorageFailure as exc:
            code = (
                exc.code
                if type(exc.code) is str
                and exc.code
                in {
                    "INTEGRITY_MISMATCH",
                    "FILE_TOO_LARGE",
                    "OBJECT_NOT_FOUND",
                    "STORAGE_UNAVAILABLE",
                    "UNSAFE_STORAGE_ROOT",
                    "UNSAFE_STORAGE_PATH",
                }
                else "STORAGE_UNAVAILABLE"
            )
            status = ScanStatus.REJECTED if code == "INTEGRITY_MISMATCH" else ScanStatus.UNAVAILABLE
        except Exception:
            # No raw exception diagnostics or LLM calls on the error path.
            status, code = ScanStatus.UNAVAILABLE, "SCANNER_OR_STORAGE_UNAVAILABLE"
        completed = self.clock()
        if completed < started:
            status, code, completed = ScanStatus.UNKNOWN, "CLOCK_MOVED_BACKWARD", started
        return ScanReceipt(
            request.request_id,
            request.binding,
            request.scanner,
            request.policy.digest,
            status,
            started,
            completed,
            code,
        )
