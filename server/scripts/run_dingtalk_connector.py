"""Run the app-role DingTalk delivery and approval-evidence worker."""

from __future__ import annotations

import os
import time

import httpx2

from app.db.engine import get_engine
from app.integrations.dingtalk_delivery import DingTalkDeliveryClient
from app.integrations.dingtalk_outbox import DingTalkOutboxProcessor
from app.settings import get_settings


def main() -> int:
    poll_seconds = float(os.environ.get("PDOS_DINGTALK_POLL_SECONDS", "2"))
    if not 0.1 <= poll_seconds <= 60:
        raise ValueError("DingTalk poll seconds must be between 0.1 and 60")
    settings = get_settings()
    engine = get_engine()
    with httpx2.Client(follow_redirects=False, trust_env=False) as http_client:
        processor = DingTalkOutboxProcessor(
            engine=engine,
            client=DingTalkDeliveryClient(http_client),
            settings=settings,
            worker_id=f"dingtalk-{os.getpid()}",
        )
        try:
            while True:
                delivered = processor.process_one()
                approval_id = processor.sync_one_approval()
                if delivered is not None:
                    print(
                        "dingtalk_delivery "
                        f"outbox_id={delivered.id} operation={delivered.operation} "
                        f"status={delivered.status} "
                        f"error_code={delivered.last_error_code or '-'}",
                        flush=True,
                    )
                if approval_id is not None:
                    print(f"dingtalk_approval_sync approval_id={approval_id}", flush=True)
                if delivered is None and approval_id is None:
                    time.sleep(poll_seconds)
        finally:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
