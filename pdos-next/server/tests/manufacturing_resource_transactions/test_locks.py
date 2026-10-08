"""Real scoped SQL fences only; no qualified Fact/Current or resource decision.

Import the adopted actual read owner. These cases prove MVCC Asset/Clock and
NOWAIT transaction behavior, not the complete native Source owner positive path.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
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
from pdos_next.models import Grant, Product, now
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import Context, digest, require_access


@pytest.fixture
def shared_asset(setup):
    product, asset = uuid4(), uuid4()
    value = {"synthetic_clock_test_only": str(asset)}
    with Session(setup.admin) as s, s.begin():
        s.add(
            Product(
                id=product,
                tenant_id=setup.tenant,
                owner_id=setup.peer,
                name="Synthetic readonly lock peer",
                purpose="SQL fences only",
            )
        )
        s.flush()
        s.add_all(
            [
                Grant(
                    tenant_id=setup.tenant,
                    product_id=product,
                    principal_id=person,
                    can_write=True,
                    expires_at=now() + timedelta(minutes=15),
                )
                for person in (setup.human, setup.peer)
            ]
        )
        s.add(
            OperationalAsset(
                id=asset,
                tenant_id=setup.tenant,
                kind="resource",
                external_key=str(asset),
                identity={"id": str(asset)},
                revision=1,
                occupancy_epoch=1,
                data_sha256=digest(value),
                data={"value": value, "state": "active"},
            )
        )
    ctx = Context(setup.tenant, setup.peer, setup.peer)
    scope = Scope(tenant_id=setup.tenant, product_id=product, project_id=uuid4())
    target = audience(product, setup.peer, "private")
    spec = ("resource", asset, str(asset), {"id": str(asset)}, 1, value)
    return product, asset, ctx, scope, target, spec


def clocks(setup):
    with tenant_session(setup.engine, setup.tenant) as s:
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
    with tenant_session(setup.engine, setup.tenant) as s:
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


def test_actual_mvcc_read_returns_prior_asset_while_global_clock_blocks_writer(setup, shared_asset):
    product, asset, ctx, scope, target, spec = shared_asset
    before = clocks(setup)
    queue = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_session(setup.engine, setup.tenant) as s:
            require_access(s, ctx, product, lock=True)
            assert lock_dependency_clock(s, ctx, scope=scope, audience=target) == before[product]
            future = pool.submit(writer, setup, asset, queue)
            wait_for_lock(setup, queue.get(timeout=5), future)
            rows = owner._read_assets(s, ctx, [spec])
            assert rows[asset].revision == 1 and rows[asset].occupancy_epoch == 1
            assert rows[asset].data == {"value": spec[5], "state": "active"}
            assert not future.done()
        assert future.result(timeout=5) == "COMMITTED_NEW_SYNTHETIC_ASSET"
    assert clocks(setup) == {key: epoch + 1 for key, epoch in before.items()}
    with tenant_session(setup.engine, setup.tenant) as s:
        lock_dependency_clock(s, ctx, scope=scope, audience=target)
        rows = owner._read_assets(s, ctx, [spec])
        assert rows[asset].revision == 2 and rows[asset].occupancy_epoch == 2
        assert rows[asset].data["value"]["changed"] is True


def test_actual_outer_clock_people_nowait_rolls_back_uow_and_releases_writer(setup, shared_asset):
    product, asset, ctx, scope, target, _spec = shared_asset
    before = clocks(setup)
    queue = Queue()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(DomainError) as rejected:
            with tenant_session(setup.engine, setup.tenant) as s:
                require_access(s, ctx, product, lock=True)
                lock_dependency_clock(s, ctx, scope=scope, audience=target)
                future = pool.submit(writer, setup, asset, queue)
                wait_for_lock(setup, queue.get(timeout=5), future)
                owner._people_nowait(s, ctx, product, setup.human)
        assert rejected.value.code == "RESOURCE_RECHECK_REQUIRED"
        assert rejected.value.status == 409
        assert future.result(timeout=5) == "COMMITTED_NEW_SYNTHETIC_ASSET"
    assert clocks(setup) == {key: epoch + 1 for key, epoch in before.items()}


def test_actual_same_uow_asset_aba_keeps_mirror_but_advances_exact_clock(setup, shared_asset):
    product, asset, ctx, scope, target, spec = shared_asset
    before = clocks(setup)
    with tenant_session(setup.engine, setup.tenant) as s:
        require_access(s, ctx, product, lock=True)
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
    assert clocks(setup) == {key: epoch + 2 for key, epoch in before.items()}


def test_actual_asset_counter_reset_refused_and_whole_uow_unchanged(setup, shared_asset):
    product, asset, ctx, scope, target, spec = shared_asset
    before = clocks(setup)
    with pytest.raises(DBAPIError) as rejected:
        with tenant_session(setup.engine, setup.tenant) as s:
            require_access(s, ctx, product, lock=True)
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
    with tenant_session(setup.engine, setup.tenant) as s:
        row = owner._read_assets(s, ctx, [spec])[asset]
        assert row.revision == 1 and row.occupancy_epoch == 1
        assert row.data == {"value": spec[5], "state": "active"}
