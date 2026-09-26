"""Retrieve verified knowledge for queued business events using the configured embedding route.

From server: python -m scripts.run_knowledge_reuse [--once]
Requires PDOS_KNOWLEDGE_REUSE_ENABLED=true. Start only after stage validation.
"""

import argparse
import json
import logging
import signal
from threading import Event
from types import FrameType

from sqlalchemy import create_engine

from app.db.url import psycopg_database_url
from app.domain.knowledge_reuse import KnowledgeReuseWorker
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.knowledge_reuse_enabled:
        print(json.dumps({"status": "disabled"}))
        return 0
    engine = create_engine(
        psycopg_database_url(settings.database_url),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000 -c lock_timeout=5000",
        },
    )
    worker = KnowledgeReuseWorker(engine)
    stop = Event()

    def terminate(_signal: int, _frame: FrameType | None) -> None:
        stop.set()

    handlers = {sig: signal.signal(sig, terminate) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        while not stop.is_set():
            try:
                result = worker.run_once()
            except Exception as error:
                logging.error("knowledge_reuse_cycle_failed type=%s", type(error).__name__)
                if args.once:
                    return 1
            else:
                if result["state"] not in {"idle"} or args.once:
                    print(json.dumps(result), flush=True)
                if args.once:
                    return 0 if result["state"] not in {"failed", "uncertain"} else 1
            stop.wait(5)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
