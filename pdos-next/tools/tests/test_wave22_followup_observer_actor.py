"""Actual AST-selected controller methods; no constructor/DB/HTTP/private state."""

import ast
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import httpx
import pytest
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "tools/wave22_followup_control.py"
OWNED = LIVE
BASELINE = ROOT / ".local/wave22-root-followup-control-before-v1.py"
PARENT = ROOT / "tools/wave22_shared_retest.py"
OP = "quality.capa.observation.record"


class Missing(Exception):
    pass


def methods(path, name):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


owned = methods(OWNED, "FollowupControl")
parent = methods(PARENT, "SharedRetest")
cls = ast.ClassDef(
    name="ActualMethods",
    bases=[],
    keywords=[],
    body=[owned[n] for n in ("observation", "prepare_observation_source")] + [parent["step"]],
    decorator_list=[],
)
ns = {"Missing": Missing, "deepcopy": deepcopy, "UUID": UUID, "uuid5": uuid5}
exec(
    compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(OWNED), "exec"),
    ns,
)
ActualMethods = ns["ActualMethods"]


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No DB/HTTP/checkpoint IO in owned checks")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)


@pytest.fixture
def tool():
    t = ActualMethods()
    t.data = {
        "observation_payload": {"actual": "clock-and-source-retained"},
        "requests": {},
        "receipts": {},
    }
    t.namespace, t.product = str(uuid4()), str(uuid4())
    actors = {role: str(uuid4()) for role in ("maker", "observer", "independent_reviewer")}
    t.actor = lambda role: actors[role]
    t.key = lambda label, role: role + ":" + label
    t.calls = []
    t.save = lambda: t.calls.append("save")
    t.reads = lambda values: deepcopy(values)
    t.origin = lambda: ({"revision": 6}, None)
    t.request = lambda *args, **kwargs: pytest.fail("No HTTP path expected")
    return t


def test_source_preparation_reads_observer_before_missing_rule(tool):
    def host(role):
        tool.calls.append(role)
        return {"rules": []}

    tool.host = host
    with pytest.raises(Missing, match="One actual current trusted Rule required"):
        tool.prepare_observation_source(None)
    assert tool.calls == ["observer"]


def test_observation_factory_and_step_select_observer_and_exact_original(tool):
    original = deepcopy(tool.data["observation_payload"])
    reads = [{"artifact_id": str(uuid4()), "expected_revision": 1}]
    tool.host = lambda role: (
        tool.calls.append(("host", role))
        or {"operations": {OP: {"allowed": True, "required_source_read_set": reads}}}
    )

    def step(label, role, operation, family, factory, *, inputs):
        tool.calls.append(("step", label, role, operation, family, inputs))
        payload, found = factory()
        assert payload == original and payload is not tool.data["observation_payload"]
        assert found == reads

    tool.step = step
    tool.observation()
    assert tool.calls[:2] == [
        ("step", "observation", "observer", OP, "capa_observation", "capa-facts/inputs"),
        ("host", "observer"),
    ]
    assert tool.data["observation_payload"] == original


def test_observation_server_denial_preserves_payload_and_no_save(tool):
    original = deepcopy(tool.data)
    tool.host = lambda role: {"operations": {OP: {"allowed": False}}}
    tool.step = lambda label, role, operation, family, factory, **kwargs: factory()
    with pytest.raises(Missing, match="Actual observation operation blocked"):
        tool.observation()
    assert tool.data == original and tool.calls == []


@pytest.mark.parametrize(
    "state", ["ready", "awaiting_confirmation", "preview_unknown", "unknown", "saved"]
)
def test_existing_maker_request_rejected_unchanged_before_dynamic_reads(tool, state):
    tool.data["requests"]["observation"] = {
        "role": "maker",
        "actor_id": tool.actor("maker"),
        "state": state,
        "original": {
            "operation": OP,
            "product_id": tool.product,
            "command_id": str(uuid5(UUID(tool.namespace), "maker:observation")),
            "idempotency_key": tool.key("observation", "maker"),
            "payload": {
                "original_clock": "2026-10-03T06:25:03.160086+00:00",
                "confirmation_token": "not-output",
            },
        },
        "body": {"never": "replace"},
    }
    before = deepcopy(tool.data)
    tool.host = lambda *args, **kwargs: pytest.fail("Existing mismatch must precede dynamic host")
    with pytest.raises(Missing, match="Saved actor/scope/operation/command identity changed"):
        tool.observation()
    assert tool.data == before and tool.calls == []


def test_existing_observer_receipt_precedes_new_host_and_original_survives(tool):
    original = {
        "operation": OP,
        "product_id": tool.product,
        "command_id": str(uuid5(UUID(tool.namespace), "observer:observation")),
        "idempotency_key": tool.key("observation", "observer"),
        "payload": {"exact": "retained"},
    }
    tool.data["requests"]["observation"] = {
        "role": "observer",
        "actor_id": tool.actor("observer"),
        "state": "saved",
        "original": original,
    }
    tool.data["receipts"]["observation"] = {"saved": True}
    tool.check_receipt = lambda receipt, role, operation, family: tool.calls.append(
        ("receipt", role, operation, family)
    )
    tool.host = lambda *args, **kwargs: pytest.fail("Saved receipt must precede dynamic host")
    tool.observation()
    assert tool.calls[0] == ("receipt", "observer", OP, "capa_observation")
    assert tool.data["requests"]["observation"]["original"] == original


def test_other_actors_native_publication_and_default_host_ast_unchanged():
    old = methods(BASELINE, "FollowupControl")
    changed = {n for n in old if ast.dump(old[n]) != ast.dump(owned[n])}
    assert changed == {"prepare_observation_source", "observation"}
    assert ast.dump(old["observation_source"]) == ast.dump(owned["observation_source"])
    assert ast.dump(old["host"]) == ast.dump(owned["host"])
