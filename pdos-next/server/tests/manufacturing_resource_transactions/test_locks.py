"""Real scoped SQL fences only; no qualified Fact/Current or resource decision.

Import the adopted actual read owner. These cases prove MVCC Asset/Clock and
NOWAIT transaction behavior, not the complete native Source owner positive path.
"""

# ruff: noqa: F811 -- explicit pytest fixture imports

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest

# Actual native publication supplies the physical reference; no invented Fact.
from manufacturing_resource_native_transactions.conftest import (  # noqa: F401
    configuration,
    definition,
    known_configuration,
    operational_work,
    project,
)
from manufacturing_resource_native_transactions.fixtures import native_resource_case  # noqa: F401
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.change_graph_closure import closure_stamp, lock_dependency_clock
from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import OperationalAsset
from pdos_next.domain.change_execution.graph import audience
from pdos_next.domain.manufacturing_resource_owner import owner
from pdos_next.errors import DomainError
from pdos_next.models import Product
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context, digest, require_access


@pytest.fixture
def shared_asset(native_resource_case):
    case = native_resource_case
    setup = case.setup
    # A peer model shares category permissions but has no reference to this asset.
    with Session(setup.admin) as s, s.begin():
        s.add(
            Product(
                id=uuid4(),
                tenant_id=setup.tenant,
                category_id=setup.category,
                owner_id=setup.peer,
                name="Synthetic unrelated lock peer",
                purpose="SQL fences only",
            )
        )
    asset = case.work.resource_id
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        row = s.get(OperationalAsset, asset)
        spec = (
            row.kind,
            row.id,
            row.external_key,
            deepcopy(row.identity),
            row.revision,
            deepcopy(row.data["value"]),
        )
    ctx = Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category)
    scope = Scope(
        tenant_id=setup.tenant, product_id=setup.product, project_id=case.request.scope.project_id
    )
    target = audience(setup.product, setup.peer, "private")
    return setup, setup.product, asset, ctx, scope, target, spec


def clocks(setup):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        return dict(
            s.execute(select(ChangeDependencyClock.product_id, ChangeDependencyClock.epoch)).all()
        )


def wait_for_lock(setup, pid, future):
    """Bounded observation of only our writer PID, without reading SQL text."""
    finish = monotonic() + 5
    with setup.admin.connect().execution_options(isolation_level="AUTOCOMMIT") as s:
        while monotonic() < finish:
            assert not future.done(), "Writer unexpectedly finished before the clock fence"
            wait = s.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid": pid}
            )
            if wait == "Lock":
                return
            sleep(0.01)
    raise AssertionError("Our writer did not reach the real SQL lock barrier")


def writer(setup, asset, queue):
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as s:
        s.execute(text("SET LOCAL statement_timeout='10s'"))
        require_access(s, setup.ctx, setup.product, write=True, lock=True)
        queue.put(s.scalar(text("SELECT pg_backend_pid()")))
        value = {"synthetic_clock_test_only": str(asset), "changed": True}
        s.execute(
            update(OperationalAsset)
            .where(OperationalAsset.id == asset)
            .values(
                revision=2,
                occupancy_epoch=2,
                data_sha256=digest(value),
                data={"value": value, "state": "active"},
            )
        )
    return "COMMITTED_NEW_SYNTHETIC_ASSET"


def test_actual_mvcc_read_returns_prior_asset_while_referenced_clock_blocks_writer(shared_asset):
    setup, product, asset, ctx, scope, target, spec = shared_asset
    before = clocks(setup)
    queue = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as s:
            require_access(s, ctx, product)
            assert lock_dependency_clock(s, ctx, scope=scope, audience=target) == before[product]
            future = pool.submit(writer, setup, asset, queue)
            wait_for_lock(setup, queue.get(timeout=5), future)
            rows = owner._read_assets(s, ctx, [spec])
            assert rows[asset].revision == 1 and rows[asset].occupancy_epoch == 1
            assert rows[asset].data == {"value": spec[5], "state": "active"}
            assert not future.done()
        assert future.result(timeout=5) == "COMMITTED_NEW_SYNTHETIC_ASSET"
    assert clocks(setup) == {
        key: epoch + (1 if key == product else 0) for key, epoch in before.items()
    }
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=setup.category,
    ) as s:
        lock_dependency_clock(s, ctx, scope=scope, audience=target)
        rows = owner._read_assets(s, ctx, [spec])
        assert rows[asset].revision == 2 and rows[asset].occupancy_epoch == 2
        assert rows[asset].data["value"]["changed"] is True


def test_actual_outer_clock_people_nowait_rolls_back_uow_and_releases_writer(shared_asset):
    setup, product, asset, ctx, scope, target, _spec = shared_asset
    before = clocks(setup)
    queue = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(DomainError) as rejected:
            with tenant_session(
                setup.engine,
                setup.tenant,
                actor_id=ctx.actor_id,
                requester_id=ctx.requester_id,
                category_id=setup.category,
            ) as s:
                require_access(s, ctx, product)
                lock_dependency_clock(s, ctx, scope=scope, audience=target)
                future = pool.submit(writer, setup, asset, queue)
                wait_for_lock(setup, queue.get(timeout=5), future)
                owner._people_nowait(s, ctx, product, setup.human)
        assert rejected.value.reason == "RESOURCE_RECHECK_REQUIRED"
        assert rejected.value.status == 409
        assert future.result(timeout=5) == "COMMITTED_NEW_SYNTHETIC_ASSET"
    assert clocks(setup) == {
        key: epoch + (1 if key == product else 0) for key, epoch in before.items()
    }


def test_actual_same_uow_asset_aba_keeps_mirror_but_advances_exact_clock(shared_asset):
    setup, product, asset, ctx, scope, target, spec = shared_asset
    before = clocks(setup)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=setup.category,
    ) as s:
        require_access(s, ctx, product)
        lock_dependency_clock(s, ctx, scope=scope, audience=target)
        initial = closure_stamp(s, ctx, scope=scope, audience=target)
        original = owner._read_assets(s, ctx, [spec])[asset]
        original_data, original_hash = deepcopy(original.data), original.data_sha256
        changed = {"synthetic_clock_test_only": str(asset), "changed": True}
        s.execute(
            update(OperationalAsset)
            .where(OperationalAsset.id == asset)
            .values(
                revision=2,
                occupancy_epoch=2,
                data={"value": changed, "state": "active"},
                data_sha256=digest(changed),
            )
        )
        s.execute(
            update(OperationalAsset)
            .where(OperationalAsset.id == asset)
            .values(
                revision=3,
                occupancy_epoch=3,
                data=original_data,
                data_sha256=original_hash,
            )
        )
        final = closure_stamp(s, ctx, scope=scope, audience=target)
        reread = owner._read_assets(s, ctx, [spec])[asset]
        assert reread.data == original_data and reread.data_sha256 == original_hash
        assert reread.occupancy_epoch == 3 and reread.revision == 3
        assert final != initial
        assert final["dependency_epoch"] == initial["dependency_epoch"] + 2
    assert clocks(setup) == {
        key: epoch + (2 if key == product else 0) for key, epoch in before.items()
    }


def test_actual_asset_counter_reset_refused_and_whole_uow_unchanged(shared_asset):
    setup, product, asset, ctx, scope, target, spec = shared_asset
    before = clocks(setup)
    with pytest.raises(DBAPIError) as rejected:
        with tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=ctx.actor_id,
            requester_id=ctx.requester_id,
            category_id=setup.category,
        ) as s:
            require_access(s, ctx, product)
            lock_dependency_clock(s, ctx, scope=scope, audience=target)
            s.execute(
                update(OperationalAsset)
                .where(OperationalAsset.id == asset)
                .values(occupancy_epoch=2)
            )
            s.execute(
                update(OperationalAsset)
                .where(OperationalAsset.id == asset)
                .values(occupancy_epoch=1)
            )
    assert rejected.value.orig.sqlstate == "P0001"
    assert clocks(setup) == before
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=ctx.actor_id,
        requester_id=ctx.requester_id,
        category_id=setup.category,
    ) as s:
        row = owner._read_assets(s, ctx, [spec])[asset]
        assert row.revision == 1 and row.occupancy_epoch == 1
        assert row.data == {"value": spec[5], "state": "active"}
