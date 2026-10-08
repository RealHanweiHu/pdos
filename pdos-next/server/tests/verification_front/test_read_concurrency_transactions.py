"""Real PG read/command lock interleavings; executed only by the root guard run."""

# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import event, select, text
from test_project_first_plan import definition, project  # noqa: F401

from pdos_next.database import tenant_session
from pdos_next.domain.projects.service import _project
from pdos_next.models import Product
from pdos_next.service import require_access, source_for


@pytest.mark.parametrize("read_entry", ["project", "locked_access"])
def test_project_and_locked_authority_reads_complete_beside_product_gated_command(
    setup, definition, project, read_entry
):
    """A real contender reaches its read gate while another transaction owns Product.

    With the former order, the contender held Project/Principal first and both
    transactions then waited for each other's locks. Statement hooks only set
    the interleaving; PostgreSQL executes every lock and current source check.
    """
    product_held, read_gate = Event(), Event()
    source_id = UUID(definition[0])
    project_id = UUID(project)

    def limits(session):
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SET LOCAL statement_timeout = '10s'"))

    def lock_statement(statement, table):
        sql = " ".join(statement.lower().split())
        return f"from {table}" in sql and "for update" in sql

    def before(_conn, _cursor, statement, _parameters, _context, _many):
        # Correct order: the read is about to wait for Product, leaving every
        # downstream lock available to its current owner.
        if lock_statement(statement, "products"):
            read_gate.set()

    def after(_conn, _cursor, statement, _parameters, _context, _many):
        # Regressed order: the read has actually acquired a downstream lock,
        # so the Product owner must now contend for that same lock.
        downstream = "projects" if read_entry == "project" else "principals"
        if lock_statement(statement, downstream):
            read_gate.set()

    def product_gated_command():
        with tenant_session(setup.engine, setup.tenant) as session:
            limits(session)
            assert session.scalar(
                select(Product).where(Product.id == setup.product).with_for_update()
            )
            product_held.set()
            assert read_gate.wait(3), "Concurrent read did not reach its authority/source gate"
            require_access(session, setup.ctx, setup.product, write=True, lock=True)
            row, _, _ = _project(session, setup.ctx, setup.product, project_id)
            source = source_for(session, setup.ctx, setup.product, source_id, 1)
            return row.id, source.id

    def project_or_authority_read():
        assert product_held.wait(3), "Product gate was not acquired"
        with tenant_session(setup.engine, setup.tenant) as session:
            limits(session)
            connection = session.connection()
            event.listen(connection, "before_cursor_execute", before)
            event.listen(connection, "after_cursor_execute", after)
            try:
                if read_entry == "locked_access":
                    require_access(session, setup.ctx, setup.product, lock=True)
                row, _, _ = _project(session, setup.ctx, setup.product, project_id)
                source = source_for(session, setup.ctx, setup.product, source_id, 1)
                return row.id, source.id
            finally:
                event.remove(connection, "before_cursor_execute", before)
                event.remove(connection, "after_cursor_execute", after)

    with ThreadPoolExecutor(max_workers=2) as pool:
        command = pool.submit(product_gated_command)
        reader = pool.submit(project_or_authority_read)
        expected = (project_id, source_id)
        assert command.result(timeout=15) == expected
        assert reader.result(timeout=15) == expected
