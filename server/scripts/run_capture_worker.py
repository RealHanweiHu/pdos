"""Run the optional local OCR/voice queue separately from LLM application workers."""

import argparse
import time

from app.db.engine import get_engine
from app.domain.field_recognition_worker import RecognitionWorker
from app.settings import get_settings
from app.storage.documents import get_document_object_store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not get_settings().capture_recognition_enabled:
        raise SystemExit("Field recognition is disabled")
    engine = get_engine()
    try:
        worker = RecognitionWorker(engine, get_document_object_store())
        while True:
            worked = worker.run_next()
            if args.once:
                return 0
            if not worked:
                time.sleep(2)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
