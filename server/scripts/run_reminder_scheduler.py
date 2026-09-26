"""Run the deterministic app-role risk/reminder scheduler (no external calls)."""

from __future__ import annotations

import argparse
import json
import logging
import signal
from dataclasses import asdict
from threading import Event
from types import FrameType

from sqlalchemy import create_engine

from app.automation.reminders import ReminderScheduler
from app.db.url import psycopg_database_url
from app.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Reconcile once, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    interval = settings.reminder_scan_seconds
    engine = create_engine(
        psycopg_database_url(settings.database_url),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000",
        },
    )
    scheduler = ReminderScheduler(engine, settings)
    stop = Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    previous_handlers = {
        sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        while not stop.is_set():
            try:
                outcome = scheduler.run_once(should_stop=stop.is_set)
            except Exception as error:
                logger.error("reminder_cycle_failed error_type=%s", type(error).__name__)
                if args.once:
                    return 1
            else:
                print(
                    json.dumps({"event": "reminder_cycle", **asdict(outcome)}, sort_keys=True),
                    flush=True,
                )
                if args.once:
                    return int(outcome.failed_projects > 0)
            stop.wait(interval)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
