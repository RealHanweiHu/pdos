"""Create/verify the root marked fixture's independent persistent graph store."""

import secrets
from uuid import UUID

import local_environment as local
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql
from sqlalchemy.engine import make_url


def provision():
    state = local.verified(local.read_state())
    admin = make_url(state["admin_url"]).set(drivername="postgresql")
    if "s0_checkpoint_url" not in state:
        credential = secrets.token_urlsafe(32)
        with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname='pdos_checkpoint'").fetchone():
                raise RuntimeError("Unexpected checkpoint role in root isolated fixture")
            conn.execute(sql.SQL("CREATE ROLE pdos_checkpoint LOGIN PASSWORD {}").format(
                sql.Literal(credential)))
            conn.execute("CREATE DATABASE pdos_checkpoints OWNER pdos_checkpoint")
        target = admin.set(username="pdos_checkpoint", password=credential,
                           database="pdos_checkpoints")
        with psycopg.connect(admin.set(database="pdos_checkpoints").render_as_string(
            hide_password=False), autocommit=True) as conn:
            conn.execute("CREATE TABLE environment_guard(marker uuid NOT NULL)")
            conn.execute("INSERT INTO environment_guard VALUES (%s)", (UUID(state["marker"]),))
            conn.execute("REVOKE ALL ON environment_guard FROM PUBLIC")
            conn.execute("GRANT SELECT ON environment_guard TO pdos_checkpoint")
        state["s0_checkpoint_url"] = target.render_as_string(hide_password=False)
        local.save(state)
    local.verified(local.read_state())
    target = make_url(state["s0_checkpoint_url"])
    if (target.host != "127.0.0.1" or target.port != state["port"]
        or target.database != "pdos_checkpoints" or target.username != "pdos_checkpoint"):
        raise RuntimeError("Independent root checkpoint endpoint differs")
    with psycopg.connect(state["s0_checkpoint_url"]) as conn:
        marker = conn.execute("SELECT marker FROM environment_guard").fetchone()[0]
        if str(marker) != state["marker"]:
            raise RuntimeError("Root independent checkpoint marker differs")
    with PostgresSaver.from_conn_string(state["s0_checkpoint_url"]) as saver:
        saver.setup()
    return state


if __name__ == "__main__":
    provision()
    print("Root independent checkpoint database verified and initialized; credentials withheld.")
