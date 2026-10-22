"""Explicit local synthetic profile; no credentials, model, egress, or production grant."""

import asyncio
import os
import threading
from contextvars import ContextVar

from pdos_next.evidence_security import (
    ObjectStoreScannerAdapter,
    ScanLimits,
    ScanPolicy,
    SecurityFailure,
)
from pdos_next.original_security import SecurityRuntime

_SCAN_BINDING = ContextVar("pdos_current_scan_binding", default=None)


class ScopedScanReader:
    def __init__(self, store):
        self.store = store

    def read_original(self, reference):
        binding = _SCAN_BINDING.get()
        engine = getattr(self.store, "read_engine", None)
        if binding is None or engine is None or binding.object_ref != reference:
            raise SecurityFailure("FORBIDDEN_SCOPE")

        from pdos_next.database import tenant_session
        from pdos_next.original_security import Guard, security_row
        from pdos_next.originals import read_registered_bytes, require_original
        from pdos_next.service import Context

        with tenant_session(
            engine,
            binding.tenant_id,
            actor_id=binding.requester_id,
            requester_id=binding.requester_id,
            category_id=binding.category_id,
        ) as s:
            ctx = Context(
                binding.tenant_id,
                binding.requester_id,
                binding.requester_id,
                category_id=binding.category_id,
            )
            row = require_original(s, ctx, binding.product_id, reference.id, lock=True)
            guard = Guard(s, row, security_row(s, row), binding.requester_id)
            if not guard.is_current(binding):
                raise SecurityFailure("SOURCE_STALE")
            return read_registered_bytes(
                self.store, reference, binding.tenant_id, binding.product_id, binding.category_id
            )


class LoopBoundScanner:
    """Keep bounded reader/scanner slots on one loop across Temporal activity threads."""

    def __init__(self, store, transport):
        self.loop = asyncio.new_event_loop()
        self.adapter = ObjectStoreScannerAdapter(ScopedScanReader(store), transport)
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    async def scan(self, request):
        async def bound():
            token = _SCAN_BINDING.set(request.binding)
            try:
                return await self.adapter.scan(request)
            finally:
                _SCAN_BINDING.reset(token)

        future = asyncio.run_coroutine_threadsafe(bound(), self.loop)
        return await asyncio.wrap_future(future)

    async def close(self):
        async def cancel_pending():
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(cancel_pending(), self.loop))
        self.loop.call_soon_threadsafe(self.loop.stop)
        await asyncio.to_thread(self.thread.join, 5)


async def local_runtime(store):
    if os.environ.get("PDOS_FILE_SECURITY_PROFILE") != "local-synthetic-v1" or store is None:
        return None
    from pdos_next.security_runtime import DockerClamAVTransport, parse_original_container

    transport = DockerClamAVTransport()
    policy = ScanPolicy(
        version="pdos-local-synthetic-file-policy-v1", limits=ScanLimits(timeout_seconds=60)
    )
    try:
        configuration = await transport.observe_configuration(policy)
    except SecurityFailure:
        return None
    return SecurityRuntime(
        configuration, LoopBoundScanner(store, transport), parse_original_container
    )
