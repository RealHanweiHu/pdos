from sqlalchemy.engine import make_url


def psycopg_database_url(value: str) -> str:
    """Normalize an unsuffixed PostgreSQL URL to the installed psycopg v3 driver."""
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)
