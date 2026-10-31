"""Root-only PG regression: native list clocks, real result handles and revocation."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.bindings import ModelBinding
from pdos_next.agent_kernel.bootstrap import Bootstrap, RuntimePorts
from pdos_next.agent_kernel.disclosure import disclosure_digest
from pdos_next.agent_kernel.domain_reads import DomainReads
from pdos_next.agent_kernel.host import BoundHost
from pdos_next.agent_kernel.models import AgentToolCall
from pdos_next.errors import DomainError
from pdos_next.models import Grant, now
from pdos_next.service import digest
from tests.agent_kernel.test_gateway import configured_route
from tests.agent_kernel.test_result_continuation_pg import model_call, registered_read
from tests.agent_kernel.test_transactions import run
from tests.enterprise_search.test_eval_v0_contracts_pg import explicit_target
from tests.preproject.test_g0 import request, save
from tests.preproject.test_material_commands_pg import parameter

pytestmark = pytest.mark.skipif(
    not explicit_target(), reason="Root must explicitly bind all roles to guarded 53502/pdos_test",
)


def material(setup, name, *, prior=None):
    long = "合成原生列表内容" * 1000
    if name == "category.parameters.list":
        payload = parameter(standard_condition=long, unit="dB(A)" if prior else "dB")
        if prior:
            payload.update(parameter_id=prior["result"]["parameter_id"], expected_current_version=1)
        operation = "category.parameter.publish"
    else:
        competitor = name == "category.competitors.list"
        content = ({"brand": "合成原生竞品", "model": long + ("修订" if prior else "原版")}
                   if competitor else {"definition": long + ("修订" if prior else "原版")})
        payload = {"kind": "competitor" if competitor else "boundary", "content": content}
        if prior:
            payload["supersedes"] = {"lineage_id": prior["subject_id"], "expected_version": 1}
        operation = "category.knowledge.add"
    receipt, _command = save(setup, request(setup, operation, payload))
    return receipt


@pytest.mark.parametrize("name", sorted(DomainReads.OBSERVED_LISTS))
def test_native_list_clock_continuation_rechecks_changed_source_and_current_grant(setup, name):
    receipt = material(setup, name)
    store, scope = run(setup)
    owner = Bootstrap(setup.engine, ports=RuntimePorts())
    route = configured_route()
    owner.route_for = lambda _scope: route
    adapters = replace(owner.adapters(), cost_required=False)
    host = BoundHost(store, adapters)
    binding = ModelBinding(
        model_version=route.version, model_route_digest=route.digest,
        tool_definitions_digest=disclosure_digest(owner.registry),
        prompt_digest=digest("Native local list clock regression"),
        isolation="main", cancel_epoch=0,
    )
    with store.transaction(scope, lock=True) as (_, current):
        current.versions = {**current.versions,
                            "model_version": route.version, "model_route_digest": route.digest,
                            "tool_definitions": {"main": binding.tool_definitions_digest},
                            "prompt_prefixes": {"main": binding.prompt_digest}}
    arguments = {}
    source = model_call(store, scope, binding, name, arguments)
    first = registered_read(host, scope, name, arguments, source)
    preview = host.tool_message(scope, owner.registry.get(name), first)
    assert preview["truncated"] and preview["total_pages"] > 1
    # No clock patch: the actual native list now has a different observation
    # time, while the original read result and its handle remain immutable.
    fresh = adapters.read_tools[name](scope, arguments)
    assert fresh["as_of"] != first["as_of"]
    page_arguments = {"handle": preview["result_handle"], "page": 2}
    page_source = model_call(store, scope, binding, "result.read", page_arguments)
    second = registered_read(host, scope, "result.read", page_arguments, page_source)
    assert second["page"] == 2 and second["result_handle"] == preview["result_handle"]
    assert registered_read(host, scope, "result.read", page_arguments, page_source) == second
    with store.transaction(scope) as (session, _):
        original = session.get(AgentToolCall, UUID(first["execution_ref"]["call_id"]))
        saved = deepcopy(original.result)
        assert saved["as_of"] == first["as_of"]
    material(setup, name, prior=receipt)
    with pytest.raises(DomainError) as changed:
        registered_read(host, scope, "result.read", page_arguments, page_source)
    assert changed.value.code == "SOURCE_STALE"
    assert changed.value.message == "读取结果已变化，请使用新的运行重新读取。"
    with store.transaction(scope) as (session, _):
        assert session.get(AgentToolCall, UUID(first["execution_ref"]["call_id"])).result == saved
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.category_id == setup.category, Grant.principal_id == setup.human,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    with pytest.raises(DomainError) as revoked:
        registered_read(host, scope, "result.read", page_arguments, page_source)
    assert revoked.value.code == "FORBIDDEN_SCOPE"
