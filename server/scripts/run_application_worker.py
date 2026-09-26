"""Owner application worker for Chat, risk, test-plan and report-import queues."""

from __future__ import annotations

import argparse
import os
import time
from contextlib import ExitStack

from sqlalchemy import text

from app.ai.application_gateway import configured_application_gateway
from app.ai.change_discussion_queue import ChangeDiscussionQueue
from app.ai.chat_queue import ChatQueue
from app.ai.discussion_followup_queue import DiscussionFollowupQueue
from app.ai.embeddings import EmbeddingError, configured_embedding_gateway
from app.ai.report_import_queue import ReportImportQueue
from app.ai.risk_queue import RiskQueue
from app.ai.test_plan_queue import TestPlanQueue
from app.db.engine import get_engine
from app.storage.documents import get_document_object_store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    interval = float(os.environ.get("PDOS_APPLICATION_POLL_SECONDS", "1"))
    if not 0.1 <= interval <= 5:
        raise ValueError("application poll seconds must be between 0.1 and 5")
    engine = get_engine()
    try:
        while True:
            with ExitStack() as stack:
                gateway = stack.enter_context(configured_application_gateway(engine))
                if gateway.creation_budget_profile is None:
                    raise ValueError("application worker requires configured budgeted mode")
                try:
                    embedding = stack.enter_context(configured_embedding_gateway())
                except EmbeddingError:
                    embedding = None
                with engine.begin() as c:
                    c.execute(text("SELECT cehub_ai.expire_application_runs(100)"))
                worked = ChatQueue(engine, gateway=gateway).run_next(embedding_gateway=embedding)
                worked = ChangeDiscussionQueue(engine, gateway=gateway).run_next() or worked
                worked = DiscussionFollowupQueue(engine, gateway=gateway).run_next() or worked
                worked = RiskQueue(engine, gateway=gateway).run_next() or worked
                worked = TestPlanQueue(engine, gateway=gateway).run_next() or worked
                worked = (
                    ReportImportQueue(
                        engine, gateway=gateway, object_store=get_document_object_store()
                    ).run_next()
                    or worked
                )
            if args.once:
                return 0
            if not worked:
                time.sleep(interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
