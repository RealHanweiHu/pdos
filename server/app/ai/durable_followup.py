"""Periodic Agent work uses Temporal timers; the domain owns scope and receipts."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from pdos_agent_runtime.followup import ProjectFollowup
from pdos_agent_runtime.graph import execute_graph
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from app.ai.durable import configured_runtime
from app.db.schema import tables


def ensure_followup(engine: Any, tenant_id: UUID, project_id: UUID, as_of: datetime) -> None:
    with engine.connect() as connection:
        if (
            connection.execute(
                select(tables.xiaopai_delegations.c.id)
                .where(
                    tables.xiaopai_delegations.c.tenant_id == tenant_id,
                    tables.xiaopai_delegations.c.project_id == project_id,
                    tables.xiaopai_delegations.c.status == "active",
                )
                .limit(1)
            ).first()
            is None
        ):
            return
    runtime = configured_runtime(engine=engine)
    if runtime is None:
        # Explicit verified test mode exercises the domain through a real local graph.
        execute_graph(
            lambda _: scan(engine, tenant_id, project_id, as_of),
            {},
            thread_id="injected-followup:" + str(uuid4()),
        )
        return

    async def start() -> None:
        client = await Client.connect(runtime.address, namespace=runtime.namespace)
        await client.start_workflow(
            ProjectFollowup.run,
            {"tenant_id": str(tenant_id), "project_id": str(project_id)},
            id=f"pdos-followup:{tenant_id}:{project_id}",
            task_queue=runtime.task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(lambda: asyncio.run(asyncio.wait_for(start(), 15))).result()


def scan(engine: Any, tenant_id: UUID, project_id: UUID, as_of: datetime) -> dict[str, bool]:
    from app.domain.xiaopai import XiaopaiService

    XiaopaiService(engine).scan_project(tenant_id, project_id, as_of)
    with engine.connect() as connection:
        active = (
            connection.execute(
                select(tables.xiaopai_delegations.c.id)
                .where(
                    tables.xiaopai_delegations.c.tenant_id == tenant_id,
                    tables.xiaopai_delegations.c.project_id == project_id,
                    tables.xiaopai_delegations.c.status == "active",
                )
                .limit(1)
            ).first()
            is not None
        )
    return {"active": active}


class FollowupActivities:
    def __init__(self, engine: Any):
        self.engine = engine

    @activity.defn(name="pdos_followup_graph")
    def execute(self, reference: dict[str, str]) -> dict[str, bool]:
        tenant, project = UUID(reference["tenant_id"]), UUID(reference["project_id"])
        return cast(
            dict[str, bool],
            execute_graph(
                lambda _: scan(self.engine, tenant, project, datetime.now(UTC)),
                {},
                thread_id=f"pdos-followup:{tenant}:{project}:{activity.info().activity_id}",
            ),
        )
