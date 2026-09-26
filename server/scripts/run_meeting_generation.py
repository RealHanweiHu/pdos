"""Run bounded meeting generation and queue explicitly authorized external bookings."""

import argparse
import logging
import signal
from threading import Event

from sqlalchemy import create_engine

from app.db.url import psycopg_database_url
from app.domain.meeting_generation import GenerationWorker
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.meeting_generation_enabled:
        print("Local meeting generation is disabled")
        return 0
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = create_engine(
        psycopg_database_url(settings.database_url),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=60000 -c lock_timeout=5000",
        },
    )
    worker = GenerationWorker(engine, enabled=True, settings=settings)
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        while not stop.is_set():
            try:
                worked = worker.run_next()
            except Exception as error:
                logging.error("meeting_generation_cycle_failed error_type=%s", type(error).__name__)
                if args.once:
                    return 1
                worked = False
            if args.once:
                return 0
            if not worked:
                stop.wait(settings.meeting_generation_scan_seconds)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
