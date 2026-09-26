"""Match saved public notice snapshots locally (no LLM or network).

From server: python -m scripts.run_supplier_notice_matcher [--once]
Requires PDOS_SUPPLIER_NOTICE_MATCHING_ENABLED=true. Start only after stage validation.
"""

import argparse
import json
import logging
import signal
from threading import Event
from types import FrameType

from sqlalchemy import create_engine

from app.db.url import psycopg_database_url
from app.domain.supplier_notice_dispatches import SupplierNoticeDispatches
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.supplier_notice_matching_enabled:
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
    worker = SupplierNoticeDispatches(engine, enabled=True)
    stop = Event()

    def terminate(_signal: int, _frame: FrameType | None) -> None:
        stop.set()

    handlers = {sig: signal.signal(sig, terminate) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        while not stop.is_set():
            try:
                result = worker.run_once()
            except Exception as error:
                logging.error("supplier_notice_matching_cycle_failed type=%s", type(error).__name__)
                if args.once:
                    return 1
            else:
                if result["status"] not in {"idle", "busy"} or args.once:
                    print(json.dumps(result), flush=True)
                if args.once:
                    return 0 if result["status"] not in {"blocked"} else 1
            stop.wait(5)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
