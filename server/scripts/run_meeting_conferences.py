"""Run explicitly requested provider conferences independently of message delivery."""

import argparse
import logging
import signal
from threading import Event

import httpx2

from app.db.engine import get_engine
from app.integrations.meeting_conference_worker import ConferenceWorker
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.dingtalk_conference_enabled and not settings.tencent_meeting_enabled:
        print("External conferences are disabled")
        return 0
    engine = get_engine()
    stop = Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        with httpx2.Client(follow_redirects=False, trust_env=False) as client:
            worker = ConferenceWorker(engine, client, settings)
            while not stop.is_set():
                try:
                    worked = worker.run_next()
                except Exception as error:
                    logging.error("conference_cycle_failed error_type=%s", type(error).__name__)
                    if args.once:
                        return 1
                    worked = False
                if args.once:
                    return 0
                if not worked:
                    stop.wait(5)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
