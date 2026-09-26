"""Cooperative process heartbeat; PostgreSQL remains the lease authority."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread

# All three approved N0-02 profiles freeze renewal at 20s and expiry at 60s.
RENEW_SECONDS = 20.0


class AgentLeaseLostError(RuntimeError):
    pass


class LeaseHeartbeat:
    def __init__(self, renew: Callable[[], object], *, interval: float = RENEW_SECONDS):
        if interval <= 0:
            raise ValueError("lease renewal interval must be positive")
        self._renew, self._interval = renew, interval
        self._stop = Event()
        self._failure: Exception | None = None
        self._thread = Thread(target=self._run, name="pdos-agent-lease", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._renew()
            except Exception as error:
                self._failure = error
                return

    def require_current(self) -> None:
        if self._failure is not None:
            raise AgentLeaseLostError("AGENT_RUN_LEASE_LOST") from self._failure

    def close(self) -> None:
        self._stop.set()
        # SQL renewal has bounded lock/statement waits. Never keep a completed
        # worker blocked indefinitely if connection establishment is unavailable.
        self._thread.join(timeout=1)
