"""Run the database-only Agent dispatcher control plane."""

from __future__ import annotations

import os
import time

from sqlalchemy import create_engine

from app.ai.budget_adoption import event_budget_profile
from app.ai.loop_policy import configured_loop_binding
from app.ai.runtime_factory import required_database_url
from app.db.url import psycopg_database_url
from app.worker.dispatcher import AgentDispatcher


def main() -> int:
    database_url = required_database_url(os.environ, key="PDOS_WORKER_DATABASE_URL")
    poll_seconds = float(os.environ.get("PDOS_DISPATCHER_POLL_SECONDS", "2"))
    debounce_minutes = int(os.environ.get("PDOS_AGENT_DEBOUNCE_MINUTES", "15"))
    if not 0.1 <= poll_seconds <= 5:
        raise ValueError("dispatcher poll seconds must be between 0.1 and 5")
    profile = event_budget_profile(os.environ)
    engine = create_engine(psycopg_database_url(database_url), pool_pre_ping=True)
    dispatcher = AgentDispatcher(
        engine,
        debounce_minutes=debounce_minutes,
        scheduling="approved",
        budget_profile_key=profile.key if profile is not None else None,
        loop_binding=configured_loop_binding(os.environ),
    )
    try:
        while True:
            result = dispatcher.dispatch_once()
            if (
                result.scanned_event_count
                or result.queued_run_count
                or result.recovered_run_count
                or result.stopped_run_count
            ):
                print(
                    "agent_dispatch_cycle "
                    f"tenants={result.tenant_count} "
                    f"scanned={result.scanned_event_count} "
                    f"routed={result.routed_event_count} "
                    f"created={result.created_run_count} "
                    f"merged={result.merged_event_count} "
                    f"queued={result.queued_run_count} "
                    f"recovered={result.recovered_run_count} stopped={result.stopped_run_count}",
                    flush=True,
                )
            time.sleep(poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
