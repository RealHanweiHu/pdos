"""Graceful, re-entrant worker shutdown (D348).

On SIGTERM or SIGINT the worker:

1. stops taking new work at once: the Temporal pollers stop and the event delivery
   loop ends its current round;
2. lets Activities already running finish for up to the grace period
   (``PDOS_WORKER_SHUTDOWN_GRACE_SECONDS``, default 60);
3. then cancels the ones still running and waits at most ``CANCEL_WINDOW`` more.

An Activity that ignores cancellation (blocked in a database or network call) is
abandoned after that: the process exits with ``ABANDONED_EXIT_CODE`` and Temporal
retries the Activity after its own timeout. Activities reread business facts on
every attempt, so a retry never acts on stale state.

Re-entrant: a second signal, or a second request from code, while stopping does not
start a second shutdown; it is logged and ignored. Use SIGKILL to force an exit.
"""

import asyncio
import logging
import os
import signal
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

logger = logging.getLogger(__name__)

DEFAULT_GRACE_SECONDS = 60
MAX_GRACE_SECONDS = 3600
CANCEL_WINDOW = timedelta(seconds=15)
ABANDONED_EXIT_CODE = 3


def grace_period(environ=os.environ) -> timedelta:
    """Grace period from PDOS_WORKER_SHUTDOWN_GRACE_SECONDS; a whole number 0–3600."""
    raw = environ.get("PDOS_WORKER_SHUTDOWN_GRACE_SECONDS", str(DEFAULT_GRACE_SECONDS))
    if not raw.isdigit() or int(raw) > MAX_GRACE_SECONDS:
        raise RuntimeError(
            "PDOS_WORKER_SHUTDOWN_GRACE_SECONDS must be a whole number from 0 to 3600"
        )
    return timedelta(seconds=int(raw))


class GracefulShutdown:
    def __init__(self, grace: timedelta, *, cancel_window: timedelta = CANCEL_WINDOW):
        self.grace, self.cancel_window = grace, cancel_window
        self.requested = asyncio.Event()
        self.reason: str | None = None
        self.requested_at: float | None = None
        self.repeats = 0

    @property
    def stopping(self) -> bool:
        return self.requested.is_set()

    @property
    def limit_seconds(self) -> float:
        """Longest the whole stop may take: grace plus the cancellation window."""
        return (self.grace + self.cancel_window).total_seconds()

    def request(self, reason: str) -> bool:
        """Ask the worker to stop; only the first request does anything."""
        if self.requested.is_set():
            self.repeats += 1
            elapsed = time.monotonic() - (self.requested_at or time.monotonic())
            logger.info(
                "Worker already stopping (%s, %.0fs ago); %s ignored",
                self.reason,
                elapsed,
                reason,
            )
            return False
        self.reason, self.requested_at = reason, time.monotonic()
        self.requested.set()
        logger.warning(
            "Worker stopping (%s): no new tasks; running Activities get %ss",
            reason,
            int(self.grace.total_seconds()),
        )
        return True

    def install(self, loop: asyncio.AbstractEventLoop, signals=(signal.SIGTERM, signal.SIGINT)):
        for value in signals:
            loop.add_signal_handler(value, self.request, value.name)


async def serve(worker, shutdown: GracefulShutdown, *, stop_intake: Callable[[], Awaitable]):
    """Run ``worker`` until a stop is requested; True when every Activity ended in time.

    ``stop_intake`` ends any other loop that hands work to Temporal (event delivery);
    it runs alongside the worker's own shutdown and inside the same limit.
    """
    run = asyncio.create_task(worker.run())
    requested = asyncio.create_task(shutdown.requested.wait())
    done, _ = await asyncio.wait({run, requested}, return_when=asyncio.FIRST_COMPLETED)
    if run in done:
        # The worker ended by itself (fatal error): stop the rest and surface it.
        requested.cancel()
        shutdown.request("worker_stopped")
        await stop_intake()
        run.result()
        return True
    try:
        async with asyncio.timeout(shutdown.limit_seconds):
            await asyncio.gather(asyncio.shield(worker.shutdown()), stop_intake())
    except TimeoutError:
        logger.error(
            "Worker shutdown exceeded %.0fs; abandoning Activities still running "
            "(Temporal retries them after their timeout)",
            shutdown.limit_seconds,
        )
        return False
    await run
    return True


def exit_after(clean: bool) -> None:
    """Leave the process. Abandoned Activity threads must not keep it alive."""
    if not clean:
        logging.shutdown()
        os._exit(ABANDONED_EXIT_CODE)
