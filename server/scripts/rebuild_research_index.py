"""Rebuild the derived research index from immutable crawl snapshot bodies.

From server: python -m scripts.rebuild_research_index
Idempotent: the projection is fully deleted and re-derived on each run.
"""

import json

from sqlalchemy import create_engine

from app.db.url import psycopg_database_url
from app.domain.research_index import ResearchIndexService
from app.settings import get_settings


def main() -> int:
    settings = get_settings()
    engine = create_engine(
        psycopg_database_url(settings.database_url),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=300000",
        },
    )
    try:
        print(json.dumps(ResearchIndexService(engine).rebuild()), flush=True)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
