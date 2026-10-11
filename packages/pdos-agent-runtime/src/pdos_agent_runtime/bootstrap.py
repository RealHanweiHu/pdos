"""Explicit setup for an independently created private runtime database."""

import argparse

from langgraph.checkpoint.postgres import PostgresSaver

from pdos_agent_runtime.store import SCHEMA, RuntimeStore


def install(url: str, *, realm: str, marker: str) -> None:
    store = RuntimeStore(url, realm=realm, marker=marker)
    with store.connection() as connection:
        existing = connection.execute(
            "SELECT to_regclass('public.agent_runtime_jobs') AS name"
        ).fetchone()["name"]
        if existing is None:
            connection.execute(SCHEMA)
        else:
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='agent_runtime_jobs'"
            ).fetchall()
            if {row["column_name"] for row in columns} != {
                "realm",
                "tenant_id",
                "id",
                "handler",
                "input_digest",
                "payload",
                "state",
                "result",
                "error_code",
                "started_at",
                "finished_at",
            }:
                raise RuntimeError(
                    "Runtime schema differs; an explicit migration is required"
                )
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()


def main():
    # Connection credentials stay in the process environment, never command history.
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--realm", required=True, choices=("pdos-next",))
    args = parser.parse_args()
    install(
        os.environ["PDOS_AGENT_RUNTIME_DATABASE_URL"],
        realm=args.realm,
        marker=os.environ["PDOS_AGENT_RUNTIME_DB_MARKER"],
    )


if __name__ == "__main__":
    main()
