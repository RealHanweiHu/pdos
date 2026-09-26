"""Run deterministic schedule propagation with the app database role; no model or outbound calls."""

import argparse
import json
import logging
import signal
from dataclasses import asdict
from threading import Event

from sqlalchemy import create_engine

from app.automation.schedule_propagation import SchedulePropagation
from app.db.url import psycopg_database_url
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.schedule_propagation_enabled:
        print(json.dumps({"event": "schedule_propagation_disabled"}))
        return 0
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = create_engine(
        psycopg_database_url(settings.database_url),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000",
        },
    )
    worker = SchedulePropagation(engine)
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        while not stop.is_set():
            try:
                outcome = worker.run_once(should_stop=stop.is_set)
                print(
                    json.dumps({"event": "schedule_propagation_cycle", **asdict(outcome)}),
                    flush=True,
                )
                if args.once:
                    return int(outcome.failed > 0)
            except Exception as error:
                logging.error(
                    "schedule_propagation_cycle_failed error_type=%s", type(error).__name__
                )
                if args.once:
                    return 1
            stop.wait(settings.schedule_propagation_scan_seconds)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
