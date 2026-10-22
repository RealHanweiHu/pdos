"""Provision only the separately marked M2 fixture's independent checkpoint database."""

import secrets
from uuid import UUID

import local_environment as local
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def provision():
    local.STATE = local.ROOT / ".local/m2-runtime.json"
    state = local.verified(local.read_state())
    if "m2_checkpoint_url" not in state:
        credential = secrets.token_urlsafe(32)
        admin_url = (
            make_url(state["admin_url"])
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )
        with psycopg.connect(admin_url, autocommit=True) as connection:
            if connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname='pdos_checkpoint'"
            ).fetchone():
                raise RuntimeError("Unexpected checkpoint role in private M2 container")
            connection.execute(
                sql.SQL("CREATE ROLE pdos_checkpoint LOGIN PASSWORD {}").format(
                    sql.Literal(credential)
                )
            )
            connection.execute("CREATE DATABASE pdos_checkpoints OWNER pdos_checkpoint")
        target = make_url(state["admin_url"]).set(
            drivername="postgresql",
            username="pdos_checkpoint",
            password=credential,
            database="pdos_checkpoints",
        )
        state["m2_checkpoint_url"] = target.render_as_string(hide_password=False)
        local.save(state)
        # The environment marker is provisioned by the fixture owner, not runtime inference.
        checkpoint_admin = (
            make_url(admin_url)
            .set(database="pdos_checkpoints")
            .render_as_string(hide_password=False)
        )
        with psycopg.connect(checkpoint_admin, autocommit=True) as connection:
            connection.execute("CREATE TABLE environment_guard(marker uuid NOT NULL)")
            connection.execute(
                "INSERT INTO environment_guard VALUES (%s)", (UUID(state["marker"]),)
            )
            connection.execute("REVOKE ALL ON environment_guard FROM PUBLIC")
            connection.execute("GRANT SELECT ON environment_guard TO pdos_checkpoint")
    local.verified(local.read_state())
    with psycopg.connect(state["m2_checkpoint_url"]) as connection:
        marker = connection.execute("SELECT marker FROM environment_guard").fetchone()[0]
        if str(marker) != state["marker"]:
            raise RuntimeError("M2 checkpoint marker mismatch")
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(state["m2_checkpoint_url"]) as saver:
        saver.setup()
    print("Private M2 checkpoint database verified and initialized; credentials withheld.")
    return state


if __name__ == "__main__":
    provision()
