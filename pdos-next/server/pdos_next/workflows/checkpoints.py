import os

from sqlalchemy import text
from sqlalchemy.engine import make_url

from pdos_next.database import engine_for


def verified_checkpoint_url(url: str) -> str:
    target = make_url(url)
    if (
        target.host != "127.0.0.1"
        or target.database != "pdos_checkpoints"
        or target.query
        or target.port != int(os.environ["PDOS_STATE_DB_PORT"])
        or target.username != "pdos_checkpoint"
    ):
        raise RuntimeError("Checkpoint store is not the explicitly selected independent target")
    engine = engine_for(url)
    try:
        with engine.connect() as connection:
            marker = connection.execute(text("SELECT marker FROM environment_guard")).scalar_one()
            if str(marker) != os.environ["PDOS_STATE_DB_MARKER"]:
                raise RuntimeError("Checkpoint store marker mismatch")
    finally:
        engine.dispose()
    return target.set(drivername="postgresql").render_as_string(hide_password=False)
