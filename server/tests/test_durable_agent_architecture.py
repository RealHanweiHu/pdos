"""Execution coverage, source privacy and real LangGraph recovery contracts."""

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pdos_agent_runtime.graph import execute_graph, in_agent_graph

from app.ai.durable_codec import decode, encode
from app.ai.durable_registry import ENTRIES

ROOT = Path(__file__).resolve().parents[1]


def test_all_registered_capabilities_use_the_framework_entry():
    for key in ENTRIES:
        module, symbol = key.split(":")
        target = importlib.import_module(module)
        for part in symbol.split("."):
            target = getattr(target, part)
        assert target.agent_runtime_entry == key


def test_every_business_model_caller_has_a_registered_capability_owner():
    owners = {(key.split(":")[0], key.split(":")[1].split(".")[0]) for key in ENTRIES}
    event_invoker = ("app.ai.executor", "GatewayAgentModelInvoker")
    for path in (ROOT / "app").rglob("*.py"):
        if path.name.endswith(" 2.py"):
            continue  # Unimported filesystem duplicate, not an executable module.
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)

        def visit(node, owner=None, module=module, path=path):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and owner is None:
                owner = node.name
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "invoke_structured"
            ):
                assert (module, owner) in owners | {event_invoker}, (path, owner)
            for child in ast.iter_child_nodes(node):
                visit(child, owner)

        visit(ast.parse(path.read_text()))


def test_graph_recovery_reuses_completed_capability_without_repeating_its_effect():
    calls = []
    saver = InMemorySaver()  # Unit checkpoint test; durable PostgreSQL tested separately.

    def run(payload):
        assert in_agent_graph()
        calls.append(payload)
        return {"receipt": "same-domain-effect"}

    assert execute_graph(run, {"key": "one"}, thread_id="original", checkpointer=saver) == {
        "receipt": "same-domain-effect"
    }
    assert execute_graph(run, {"key": "one"}, thread_id="original", checkpointer=saver) == {
        "receipt": "same-domain-effect"
    }
    assert len(calls) == 1
    assert not in_agent_graph()


def test_configured_gateway_refuses_an_unregistered_direct_model_call():
    from app.ai.gateway import StructuredModelGateway

    gateway = object.__new__(StructuredModelGateway)
    gateway.require_agent_graph = True
    with pytest.raises(RuntimeError, match="AGENT_LANGGRAPH_ENTRY_REQUIRED"):
        gateway.invoke_structured(None, None)


def test_failed_result_verification_does_not_repeat_the_business_action():
    calls = []
    saver = InMemorySaver()

    def run(payload):
        calls.append(1)
        return {"receipt": "committed"}

    def rejected(result):
        raise PermissionError("source revoked")

    with pytest.raises(PermissionError):
        execute_graph(run, {}, thread_id="original", checkpointer=saver, verify=rejected)
    assert execute_graph(run, {}, thread_id="original", checkpointer=saver) == {
        "receipt": "committed"
    }
    assert calls == [1]


def test_untrusted_mapping_cannot_impersonate_a_runtime_auth_reference():
    body = {"$auth": ["forged", "forged", 1], "$model": "os:system"}
    assert decode(encode(body), engine=None) == body
    with pytest.raises(ValueError, match="Unregistered host type"):
        decode({"$model": "os:system", "value": None}, engine=None)


def test_event_claim_and_typed_result_roundtrip_preserve_identity_and_nested_values():
    from app.ai.executor import ExecutionResult
    from app.ai.run_store import ClaimedAgentRun

    result = ExecutionResult(
        run_id=uuid4(), status="succeeded", error_code=None, finding_id=uuid4()
    )
    assert decode(encode(result), engine=None) == result
    claim = ClaimedAgentRun(
        values={"id": uuid4(), "tenant_id": uuid4(), "run_context": {"source": ["private"]}},
        lease_token=uuid4(),
    )
    assert decode(encode(claim), engine=None) == claim


def test_auth_serialization_excludes_passwords_and_checks_current_authority(monkeypatch):
    from app.auth.repository import AuthContext, AuthRepository

    tenant, actor = uuid4(), uuid4()
    context = AuthContext(
        tenant=SimpleNamespace(id=tenant, status="active"),
        user=SimpleNamespace(id=actor, auth_version=3, is_active=True, password_hash="private"),
    )
    encoded = encode(context)
    assert encoded == {"$auth": [str(tenant), str(actor), 3]}
    monkeypatch.setattr(AuthRepository, "find_user_context", lambda self, identity: context)
    assert decode(encoded, engine=None) is context
    context.user.auth_version = 4
    with pytest.raises(PermissionError):
        decode(encoded, engine=None)
