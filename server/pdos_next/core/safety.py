import os

from sqlalchemy import text


def verify_test_target(engine):
    """No .env, no fallback, no pre-existing integration database acceptance."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    marker = os.environ.get("TEST_DATABASE_MARKER")
    port = os.environ.get("TEST_DATABASE_PORT")
    url = engine.url
    if (
        not explicit
        or not marker
        or not port
        or url.host not in {"127.0.0.1", "localhost"}
        or url.port != int(port)
        or url.port in {57432, 55432, 55433, 55434, 55435, 57439, 57441}
        or url.database != "pdos_test"
        or url.query
    ):
        raise RuntimeError("Refusing unverified test target")
    from sqlalchemy.engine import make_url

    allowed = make_url(explicit)
    if (allowed.host, allowed.port, allowed.database) != (url.host, url.port, url.database):
        raise RuntimeError("Engine does not match explicit TEST_DATABASE_URL target")
    with engine.connect() as conn:
        actual = conn.execute(text("SELECT marker FROM environment_guard")).scalar_one()
        database = conn.execute(text("SELECT current_database()")).scalar_one()
        if str(actual) != marker or database != "pdos_test":
            raise RuntimeError("Test database marker mismatch")
