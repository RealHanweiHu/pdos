"""Five actual RLS reads and common read ledger; no provider invocation."""

# ruff: noqa: F811 -- imported pytest fixture dependencies are intentional.
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    create_issue,
    known_configuration,
    launch_work,
    operational_work,
    publish_policy,
    quality_work,
    ready_work,
    results_work,
    triage,
)
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding, execution_key
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.disclosure import disclosure
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.agent_kernel.policy import egress
from pdos_next.agent_kernel.read_execution import ReadSource
from pdos_next.domain.build_execution.models import BuildLot, SampleUnit
from pdos_next.domain.builds.models import Build
from pdos_next.domain.quality_execution.models import QualityIssueCurrent, QualityIssueVersion
from pdos_next.domain.verification_launch.models import (
    VerificationRunCurrent,
    VerificationRunVersion,
)
from pdos_next.errors import DomainError
from pdos_next.models import Audit, Grant, Outbox, Receipt, RequestKey, now
from pdos_next.service import digest
from tests.agent_kernel.test_transactions import run as create_read_run


def reader(work, tool, arguments):
    caller = work.quality
    store, scope = create_read_run(
        caller,
        product_id=caller.product,
        project_id=UUID(work.config["project"]),
        data_categories=("internal",),
    )
    bootstrap = Bootstrap(caller.engine)
    route = SimpleNamespace(version="synthetic-project-read@1", digest=digest("synthetic route"))
    bootstrap.route = lambda *_: route
    binding = ModelBinding(
        model_version=route.version,
        model_route_digest=route.digest,
        tool_definitions_digest=digest(disclosure(bootstrap.registry)),
        prompt_digest=digest("synthetic prefix"),
        isolation="main",
        cancel_epoch=scope.cancel_epoch,
        loaded_skills=(),
    )
    with store.transaction(scope) as (_, run):
        run.state = "running"
        run.versions = {
            **run.versions,
            "model_version": route.version,
            "model_route_digest": route.digest,
            "tool_definitions": {"main": binding.tool_definitions_digest},
            "prompt_prefixes": {"main": binding.prompt_digest},
        }
    model_id, _ = store.claim(
        scope,
        "synthetic-project-model:" + str(uuid4()),
        "model",
        {"fixture": "no provider"},
        execution_binding=binding.model_dump(mode="json"),
    )
    store.settle(scope, model_id, result={"calls": [{"name": tool, "arguments": arguments}]})
    adapters = bootstrap.adapters()
    f = SimpleNamespace(
        store=store,
        scope=scope,
        adapters=adapters,
        host=BoundHost(store, adapters),
        spec=bootstrap.registry.get(tool),
        arguments=arguments,
        key=execution_key(scope.run_id, model_id, 0),
        source=ReadSource(model_call_id=model_id, response_index=0),
    )
    f.invoke = lambda: f.host.read(scope, f.spec, arguments, f.key, source=f.source)
    return f


def counts(work):
    with Session(work.setup.admin) as s:
        return {
            model.__tablename__: s.scalar(
                select(func.count()).select_from(model).where(model.tenant_id == work.setup.tenant)
            )
            for model in (
                Build,
                BuildLot,
                SampleUnit,
                QualityIssueVersion,
                QualityIssueCurrent,
                VerificationRunVersion,
                VerificationRunCurrent,
                Receipt,
                Audit,
                Outbox,
                RequestKey,
            )
        }


def test_five_registered_reads_current_pointers_replay_and_revoked_access(quality_work):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work)
    before = counts(work)
    issue_id = first["result"]["issue_id"]
    readers = {}
    for tool, arguments in {
        "build.read": {"build_id": work.build_id},
        "build.lot.read": {"build_id": work.build_id},
        "build.sample.read": {"build_id": work.build_id, "page_size": 1},
        "quality.issue.read": {"issue_id": issue_id},
        "test.run.read": {"test_run_id": str(work.failure_run.id)},
    }.items():
        f = readers[tool] = reader(work, tool, arguments)
        value = f.invoke()
        assert value["items"], tool
        assert value["project_id"] == work.config["project"]
        assert value["basis_status"] == "not_assessed"
        assert f.invoke() == value
        assert all("revision" in item and "record_status" in item for item in value["items"])
        with f.store.transaction(f.scope) as (s, _):
            call = s.get(AgentToolCall, UUID(value["execution_ref"]["call_id"]))
            assert call.state == "completed" and call.tool == tool
            assert call.execution_binding["data_categories"] == ["internal"]
            decision = egress(s, f.scope, "synthetic-structural-provider")
            assert decision.data_categories == ("internal",) and decision.agreement_id is None
    assert counts(work) == before
    sample = readers["build.sample.read"].invoke()
    assert sample["has_more"] and sample["next_cursor"]
    f = reader(
        work,
        "build.sample.read",
        {
            "build_id": work.build_id,
            "page_size": 1,
            "cursor": sample["next_cursor"],
        },
    )
    second = f.invoke()
    assert second["items"][0]["id"] != sample["items"][0]["id"] and not second["has_more"]
    assert "availability" not in second["items"][0]

    run = readers["test.run.read"].invoke()["items"][0]
    assert run["id"] == str(work.failure_run.id) and run["revision"] == work.failure_run.revision
    assert run["version_id"] == str(work.failure_run_version_id)
    # Prove the ORM port selects no unbounded source/snapshot body.
    statements = []

    def capture(_c, _cursor, sql, _params, _context, _many):
        if sql.startswith("SELECT quality_issue_versions."):
            statements.append(sql)

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        readers["quality.issue.read"].invoke()
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert statements and all("issue_snapshot" not in sql for sql in statements)

    # The current Issue advances; an old settled read cannot replay an old revision.
    triage(work, first)
    f = readers["quality.issue.read"]
    with pytest.raises(DomainError) as stale:
        f.invoke()
    assert stale.value.code == "SOURCE_STALE"
    current = reader(work, "quality.issue.read", {"issue_id": issue_id}).invoke()
    assert current["items"][0]["id"] == issue_id and current["items"][0]["revision"] == 2
    assert len(current["items"]) == 1
    f = readers["build.read"]
    with pytest.raises(DomainError):
        f.adapters.read_tools["build.read"](f.scope, {"build_id": str(uuid4())})
    with pytest.raises(DomainError):
        f.adapters.read_tools["build.read"](replace(f.scope, project_id=uuid4()), {})
    # Revocation is checked on a new transaction even for a settled tool call.
    with Session(work.setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.tenant_id == work.setup.tenant, Grant.principal_id == work.setup.agent
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as denied:
        f.invoke()
    assert denied.value.code == "FORBIDDEN_SCOPE"


def test_internal_metadata_cannot_leave_provider_with_public_only_agreement(setup):
    from pdos_agent_runtime.graph import registered_graph_context

    from pdos_next.agent_kernel.gateway import AgentGateway
    from pdos_next.agent_kernel.management import register_agreement
    from pdos_next.agent_kernel.models import TenantAdministrator
    from tests.agent_kernel.test_gateway import Client, configured_route
    from tests.agent_kernel.test_transactions import agreement, human_session

    with Session(setup.admin) as s, s.begin():
        s.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human))
    data = agreement(setup).model_copy(update={"data_categories": ["public"]})
    with human_session(setup) as s:
        register_agreement(s, setup.ctx, data)
    store, scope = create_read_run(setup, data_categories=("internal",))
    client = Client(lambda _: pytest.fail("forbidden internal data was dispatched"))
    gateway = AgentGateway(
        store,
        cost_required=False,
        route_for=lambda _: configured_route(),
        provider_for=lambda *_: "synthetic-provider",
        client=client,
    )
    with registered_graph_context("xiaopai"), pytest.raises(DomainError) as denied:
        gateway.turn(
            scope,
            system="frozen",
            messages=[{"role": "user", "content": "metadata"}],
            tools=[],
            output_schema={},
        )
    assert denied.value.detail["reason_key"] == "provider_agreement_category"
    assert client.calls == 0
