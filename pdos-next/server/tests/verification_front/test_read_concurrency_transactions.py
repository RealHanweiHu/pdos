"""Real PG read/command lock interleavings; executed only by the root guard run."""

# ruff: noqa: F811

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import select, text
from test_project_first_plan import definition, project  # noqa: F401

from pdos_next.database import tenant_session
from pdos_next.domain.projects.service import _project
from pdos_next.models import Product
from pdos_next.service import require_access, source_for


@pytest.mark.parametrize("read_entry", ["project", "locked_access"])
def test_project_and_locked_authority_reads_complete_beside_product_gated_command(
    setup, definition, project, read_entry
):
    """Current reads finish while a real command holds its model write gate.

    The actual shared authority locks remain compatible. Read-only Project and
    source checks do not acquire the exclusive model gate or wait for release.
    """
    product_held, read_complete = Event(), Event()
    source_id = UUID(definition[0])
    project_id = UUID(project)

    def limits(session):
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text("SET LOCAL statement_timeout = '10s'"))

    def product_gated_command():
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            limits(session)
            require_access(session, setup.ctx, setup.product, write=True, lock=True)
            assert session.scalar(
                select(Product).where(Product.id == setup.product).with_for_update()
            )
            product_held.set()
            assert read_complete.wait(3), "Current read waited for the exclusive model gate"
            row, _, _ = _project(session, setup.ctx, setup.product, project_id)
            source = source_for(session, setup.ctx, setup.product, source_id, 1)
            return row.id, source.id

    def project_or_authority_read():
        assert product_held.wait(3), "Product gate was not acquired"
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            limits(session)
            if read_entry == "locked_access":
                require_access(session, setup.ctx, setup.product, lock=True)
            row, _, _ = _project(session, setup.ctx, setup.product, project_id)
            source = source_for(session, setup.ctx, setup.product, source_id, 1)
            read_complete.set()
            return row.id, source.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        command = pool.submit(product_gated_command)
        reader = pool.submit(project_or_authority_read)
        expected = (project_id, source_id)
        assert command.result(timeout=15) == expected
        assert reader.result(timeout=15) == expected
