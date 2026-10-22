"""Offline controller checks; all DB/network entry points are forbidden.

HTTP response dictionaries below are explicit substitutes. They test retained
request control flow, not domain authorization, source safety or business writes.
"""

import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Engine


def owned_source(test_file: Path) -> Path:
    selected = test_file.parent
    if selected.name == "wave21-case-staged" and selected.parent.name == ".local":
        return selected / "wave21_shared_case.py"
    if selected.name == "tests" and selected.parent.name == "tools":
        return selected.parent / "wave21_shared_case.py"
    raise RuntimeError("Unexpected owned test layout")


SOURCE = owned_source(Path(__file__).resolve())
spec = importlib.util.spec_from_file_location("wave21_owned_case", SOURCE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
ROOT = module.ROOT
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("External connection forbidden in owned pure check")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(module.Foundation, "target", forbidden)
    monkeypatch.setattr(module.Foundation, "bootstrap", forbidden)
    monkeypatch.setattr(module.Foundation, "grants", forbidden)


def receipt(tool, label="project", *, operation=None, family="project"):
    identity = str(uuid4())
    return {
        "id": str(uuid4()),
        "operation": operation or tool.OPERATIONS[label],
        "subject_type": family,
        "subject_id": identity,
        "subject_revision": 1,
        "writer_id": str(tool.actor("maker")),
        "requester_id": str(tool.actor("maker")),
        "result": {"id": identity, "revision": 1, "status": "draft"},
    }


@pytest.fixture
def harness():
    tool = module.Foundation.__new__(module.Foundation)
    tool.marker, tool.purpose = "owned-pure-not-a-target", module.PURPOSE
    tool.confirm = tool.recover = None
    tool.confirm_used = tool.recover_used = False
    tool.helpers = module._seed_helpers()
    tool.tenant_id = uuid4()
    tool.data = {
        "case_id": str(uuid4()),
        "tenant_id": str(tool.tenant_id),
        "product_id": str(uuid4()),
        "actors": {
            role: {"id": str(uuid4()), "login_token": "pure-placeholder-never-sent"}
            for role in tool.ROLES
        },
        "requests": {},
        "receipts": {},
        "sources": {},
    }
    state = SimpleNamespace(calls=[], saves=[], current_revision=7, error=None)
    tool.save = lambda: state.saves.append(deepcopy(tool.data))
    state.receipt = receipt(tool)

    def request(role, method, path, *, body=None):
        state.calls.append((role, method, path, deepcopy(body)))
        if path.endswith("/workspace"):
            return {
                "product": {
                    "id": tool.data["product_id"],
                    "purpose": tool.purpose,
                    "revision": state.current_revision,
                }
            }
        if path == "/v1/commands/preview":
            prepared = deepcopy(body)
            prepared["payload"]["confirmation_token"] = "owned-pure-token-placeholder-00001"
            return {
                "command": prepared,
                "review": {"effect": "explicit controller substitute"},
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            }
        if path in {"/v1/commands", "/v1/products"}:
            if state.error is not None:
                raise state.error
            return deepcopy(state.receipt)
        raise AssertionError("Unexpected controller substitute path")

    tool.request = request
    payload = {
        "name": "Owned shared Project",
        "purpose": tool.purpose,
        "scope": "Actual boundary not invoked in this controller test",
        "definition_id": str(uuid4()),
        "expected_definition_revision": 1,
        "visibility": "product",
    }
    reads = [{"artifact_id": str(uuid4()), "expected_revision": 1}]
    return tool, state, payload, reads


def pending(harness):
    tool, state, payload, reads = harness
    with pytest.raises(module.PendingConfirmation) as caught:
        tool.submit("project", payload, reads, family="project")
    assert caught.value.label == "project"
    assert [v[2] for v in state.calls] == [
        f"/v1/products/{tool.data['product_id']}/workspace",
        "/v1/commands/preview",
    ]
    return tool.data["requests"]["project"]


def test_supported_staged_and_real_layouts_only():
    assert module.layout_root(
        Path("/repo/pdos-next/.local/wave21-case-staged/wave21_shared_case.py")
    ) == Path("/repo/pdos-next")
    assert module.layout_root(Path("/repo/pdos-next/tools/wave21_shared_case.py")) == Path(
        "/repo/pdos-next"
    )
    with pytest.raises(RuntimeError):
        module.layout_root(Path("/repo/pdos-next/other/wave21_shared_case.py"))


def test_owned_test_selects_only_staged_sibling_or_real_tools_parent():
    assert owned_source(
        Path("/repo/pdos-next/.local/wave21-case-staged/test_wave21_shared_case.py")
    ) == Path("/repo/pdos-next/.local/wave21-case-staged/wave21_shared_case.py")
    assert owned_source(Path("/repo/pdos-next/tools/tests/test_wave21_shared_case.py")) == Path(
        "/repo/pdos-next/tools/wave21_shared_case.py"
    )
    with pytest.raises(RuntimeError):
        owned_source(Path("/repo/pdos-next/server/tests/test_wave21_shared_case.py"))


def test_preview_persisted_before_single_exact_confirmation(harness):
    tool, state, payload, reads = harness
    saved = pending(harness)
    original, prepared = deepcopy(saved["original"]), deepcopy(saved["body"])
    assert saved["actor_id"] == str(tool.actor("maker"))
    assert "confirmation_token" not in original["payload"]
    assert prepared["payload"]["confirmation_token"]
    assert state.saves[-1]["requests"]["project"]["state"] == "awaiting_confirmation"
    tool.confirm = "project"
    state.current_revision = 200  # Lawful Product drift must not rewrite the old request.
    state.calls.clear()
    value = tool.submit("project", payload, reads, family="project")
    assert value == state.receipt
    assert state.calls == [("maker", "POST", "/v1/commands", prepared)]
    assert saved["original"] == original
    assert state.saves[-2]["requests"]["project"]["state"] == "sending"
    assert tool.confirm_used is True


def test_saved_receipt_returns_before_workspace_or_new_expected_revision(harness):
    tool, state, payload, reads = harness
    pending(harness)
    tool.confirm = "project"
    value = tool.submit("project", payload, reads, family="project")
    state.current_revision = 999
    state.calls.clear()
    assert tool.submit("project", {}, [], family="project") == value
    assert state.calls == []
    assert tool.data["requests"]["project"]["original"]["expected_revision"] == 7


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "build.create"),
        ("subject_type", "product"),
        ("writer_id", str(uuid4())),
        ("requester_id", str(uuid4())),
    ],
)
def test_saved_receipt_operation_family_and_actual_actor_are_checked(harness, field, value):
    tool, state, payload, reads = harness
    pending(harness)
    tool.data["receipts"]["project"] = deepcopy(state.receipt)
    tool.data["receipts"]["project"][field] = value
    state.calls.clear()
    with pytest.raises(RuntimeError):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []


def test_unknown_keeps_original_token_key_and_revision_then_explicit_recovery(harness):
    tool, state, payload, reads = harness
    pending(harness)
    tool.confirm = "project"
    state.error = httpx.ReadTimeout("pure substitute")
    original = deepcopy(tool.data["requests"]["project"])
    with pytest.raises(module.UnknownWrite):
        tool.submit("project", payload, reads, family="project")
    assert tool.data["requests"]["project"]["state"] == "unknown"
    state.calls.clear()
    state.error = None
    state.current_revision = 500
    with pytest.raises(module.UnknownWrite):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []
    tool.recover = "project"
    assert tool.submit("project", payload, reads, family="project") == state.receipt
    assert state.calls == [("maker", "POST", "/v1/commands", original["body"])]
    assert tool.data["requests"]["project"]["original"] == original["original"]
    assert tool.recover_used is True


@pytest.mark.parametrize(
    "mutation",
    ["payload", "reads", "read_order", "actor", "product", "key", "token", "body_revision"],
)
def test_existing_unsaved_request_rejects_changed_immutable_material(harness, mutation):
    tool, state, payload, reads = harness
    if mutation == "read_order":
        reads.append({"artifact_id": str(uuid4()), "expected_revision": 1})
    pending(harness)
    saved = tool.data["requests"]["project"]
    if mutation == "payload":
        payload["scope"] = "Different scope"
    elif mutation == "reads":
        reads[0]["expected_revision"] = 2
    elif mutation == "read_order":
        reads.reverse()
    elif mutation == "actor":
        tool.data["actors"]["maker"]["id"] = str(uuid4())
    elif mutation == "product":
        tool.data["product_id"] = str(uuid4())
    elif mutation == "key":
        saved["body"]["idempotency_key"] = "different-original-key"
    elif mutation == "token":
        saved["body"]["payload"]["confirmation_token"] = "different-token-placeholder-00002"
    else:
        saved["body"]["expected_revision"] = 9
    state.calls.clear()
    tool.confirm = "project"
    with pytest.raises(RuntimeError):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []


def test_wrong_confirmation_label_does_not_submit(harness):
    tool, state, payload, reads = harness
    pending(harness)
    tool.confirm = "bom"
    state.calls.clear()
    with pytest.raises(module.PendingConfirmation):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []
    assert tool.confirm_used is False


def test_actual_rejection_retains_token_and_never_repreviews(harness):
    tool, state, payload, reads = harness
    pending(harness)
    saved_body = deepcopy(tool.data["requests"]["project"]["body"])
    tool.confirm = "project"
    state.error = tool.helpers.GuardedRequestError(409, "CONFIRMATION_EXPIRED")
    with pytest.raises(tool.helpers.GuardedRequestError):
        tool.submit("project", payload, reads, family="project")
    saved = tool.data["requests"]["project"]
    assert saved["state"] == "rejected"
    assert saved["body"] == saved_body
    assert saved["last_error"] == {"status": 409, "code": "CONFIRMATION_EXPIRED"}
    state.calls.clear()
    with pytest.raises(RuntimeError):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []


def test_unknown_preview_is_not_replaced(harness):
    tool, state, payload, reads = harness
    request = tool.request

    def failed_preview(role, method, path, *, body=None):
        if path == "/v1/commands/preview":
            raise httpx.ReadTimeout("pure preview substitute")
        return request(role, method, path, body=body)

    tool.request = failed_preview
    with pytest.raises(module.DependencyMissing):
        tool.submit("project", payload, reads, family="project")
    assert tool.data["requests"]["project"]["state"] == "preview_unknown"
    state.calls.clear()
    tool.request = request
    with pytest.raises(module.DependencyMissing):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []


def test_dynamic_real_tier_list_controls_preview_not_operation_name(harness, monkeypatch):
    from pdos_next import service

    tool, state, payload, reads = harness
    assert "project.create" in service.T1_OPERATIONS
    assert "evidence.artifact.register" not in service.T1_OPERATIONS
    monkeypatch.setattr(service, "T1_OPERATIONS", service.T1_OPERATIONS - {"project.create"})
    assert tool.submit("project", payload, reads, family="project") == state.receipt
    assert [v[2] for v in state.calls] == [
        f"/v1/products/{tool.data['product_id']}/workspace",
        "/v1/commands",
    ]


def test_foundation_refuses_actual_t2_registry_entry(harness, monkeypatch):
    from pdos_next import service

    tool, state, payload, reads = harness
    monkeypatch.setattr(service, "T2_OPERATIONS", service.T2_OPERATIONS | {"project.create"})
    with pytest.raises(module.DependencyMissing):
        tool.submit("project", payload, reads, family="project")
    assert state.calls == []


def test_all_foundation_payloads_use_actual_registered_schemas_and_receipt_families(harness):
    from pdos_next.contracts import PAYLOADS
    from pdos_next.domain.configurations.service import PAYLOAD_MODELS

    tool, state, _, _ = harness
    selected = []
    tool.bootstrap = lambda: None
    tool.product = lambda: None
    tool.grants = lambda: None
    tool.readback_foundation = lambda: {"controller_substitute": True}

    def submit(label, payload, reads, *, family):
        operation = tool.OPERATIONS[label]
        normalized = PAYLOADS[operation].model_validate(payload)
        assert normalized.visibility == "product"
        actual_family = (
            PAYLOAD_MODELS[type(normalized)][1] if type(normalized) in PAYLOAD_MODELS else None
        )
        if actual_family is not None:
            assert family == actual_family
        result = receipt(tool, label, family=family)
        tool.data["receipts"][label] = result
        selected.append((label, normalized, deepcopy(reads)))
        return result

    tool.submit = submit
    value = tool.foundation()
    assert [row[0] for row in selected] == list(tool.OPERATIONS)
    assert selected[0][2] == []
    assert all(len(row[2]) == 1 for row in selected[1:])
    assert tool.data["scope"]["project_id"] == tool.data["receipts"]["project"]["subject_id"]
    assert tool.data["configuration"]["manufacturing_revision"] == 1
    assert value["later_phases_executed"] is False
    assert state.calls == []


@pytest.mark.parametrize(
    "invalid", ["missing_group", "extra_field", "boolean_revision", "conflict", "over20"]
)
def test_complete_declared_source_union_never_truncates_or_skips(invalid):
    identity = str(uuid4())
    groups = {"actual_owner": [{"artifact_id": identity, "expected_revision": 1}]}
    if invalid == "missing_group":
        groups["current_policy"] = None
    elif invalid == "extra_field":
        groups["actual_owner"][0]["ignored"] = True
    elif invalid == "boolean_revision":
        groups["actual_owner"][0]["expected_revision"] = True
    elif invalid == "conflict":
        groups["current_professional"] = [{"artifact_id": identity, "expected_revision": 2}]
    else:
        groups["other_actual_sources"] = [
            {"artifact_id": str(uuid4()), "expected_revision": 1} for _ in range(20)
        ]
    with pytest.raises((module.DependencyMissing, RuntimeError, ValueError)):
        module.merge_complete_reads(groups)


def test_union_keeps_all_owner_groups_and_full_line_original_locator():
    a, b = uuid4(), uuid4()
    groups = {
        "old_failure": [{"artifact_id": str(a), "expected_revision": 2}],
        "professional": [{"artifact_id": str(b), "expected_revision": 1}],
        "policy": [{"artifact_id": str(a), "expected_revision": 2}],
    }
    assert len(module.merge_complete_reads(groups)) == 2
    source = module.exact_line(a, 2, "whole 原始 line\nsecond", 1)
    import hashlib

    assert (
        source["position"]
        == "line:1;quote_sha256:" + hashlib.sha256("whole 原始 line".encode()).hexdigest()
    )
    assert (
        module.native_artifact_payload("publication", ("whole 原始 line", "second"))["content"]
        == "whole 原始 line\nsecond"
    )


def test_three_actors_and_explicit_past_completion_clock_no_automatic_review():
    values = [uuid4() for _ in range(7)]
    case = module.CaseIdentity("pure", *values, "exact purpose")
    fields = dict(
        issue_id=uuid4(),
        capa_id=uuid4(),
        action_id=uuid4(),
        occurred_at=datetime.now(UTC) - timedelta(seconds=1),
        timezone="UTC",
        text="Named investigation observed",
    )
    text = json.loads(module.actual_completion_line(case, **fields))
    assert len(text) == 9
    assert text["executor_id"] == str(case.maker_id)
    fields["occurred_at"] = datetime.now(UTC) + timedelta(days=1)
    with pytest.raises(ValueError):
        module.actual_completion_line(case, **fields)
    with pytest.raises(module.DependencyMissing):
        module.SharedCaseDriver(case).command(
            "review",
            "independent_reviewer",
            "quality.capa.verification.review",
            {},
            product_revision=1,
            read_groups={"all": []},
        )


def readback_responses(tool, state, monkeypatch):
    from pdos_next import service

    # Distinct sentinel proves the tool uses the actual service digest entry,
    # rather than assuming raw-string or canonical-JSON hash semantics.
    monkeypatch.setattr(service, "digest", lambda content: "actual-digest-entry-sentinel")
    families = {
        "native-source": "artifact",
        "definition": "definition_revision",
        "project": "project",
        "bom": "bom_revision",
        "engineering": "engineering_configuration",
        "manufacturing": "process_revision",
    }
    tool.data["receipts"] = {
        label: receipt(tool, label, family=family) for label, family in families.items()
    }
    ids = {label: row["subject_id"] for label, row in tool.data["receipts"].items()}
    rows = {
        label: {"id": identity, "revision": 1, "visibility": "product", "source_status": "current"}
        for label, identity in ids.items()
    }
    rows["project"].pop("source_status")
    rows["project"].update(
        owner_id=str(tool.actor("maker")),
        purpose=tool.purpose,
        definition={"id": ids["definition"], "revision": 1, "source_status": "current"},
    )
    rows["native-source"].update(
        status="active",
        content="\n".join(module.NATIVE_LINES),
        content_hash="actual-digest-entry-sentinel",
    )

    def request(role, method, path, *, body=None):
        assert method == "GET" and body is None
        state.calls.append((role, method, path, None))
        if path.endswith("workspace"):
            return {"sources": [rows["native-source"]]}
        if path.endswith("definitions"):
            return {"items": [rows["definition"]]}
        if path.endswith("projects"):
            return {"items": [rows["project"]]}
        if path.endswith("configurations"):
            return {
                "boms": [rows["bom"]],
                "engineering": [rows["engineering"]],
                "processes": [rows["manufacturing"]],
            }
        raise AssertionError("Unexpected readback substitute")

    tool.request = request
    return rows


def test_readback_uses_real_digest_and_nested_project_definition(harness, monkeypatch):
    tool, state, _, _ = harness
    readback_responses(tool, state, monkeypatch)
    result = tool.readback_foundation()
    assert set(result) == set(tool.ROLES)
    assert len(state.calls) == 12
    assert all(
        row["stored_content_hash"] == "actual-digest-entry-sentinel" for row in result.values()
    )
    assert all(row["professional_qualification"] is None for row in result.values())


@pytest.mark.parametrize(
    "mutation",
    [
        "definition_id",
        "definition_revision",
        "nested_source",
        "project_owner",
        "visibility",
        "source_content",
    ],
)
def test_readback_rejects_wrong_saved_chain_or_shared_source(harness, monkeypatch, mutation):
    tool, state, _, _ = harness
    rows = readback_responses(tool, state, monkeypatch)
    if mutation == "definition_id":
        rows["project"]["definition"]["id"] = str(uuid4())
    elif mutation == "definition_revision":
        rows["project"]["definition"]["revision"] = 2
    elif mutation == "nested_source":
        rows["project"]["definition"]["source_status"] = "needs_recheck"
    elif mutation == "project_owner":
        rows["project"]["owner_id"] = str(tool.actor("observer"))
    elif mutation == "visibility":
        rows["bom"]["visibility"] = "private"
    else:
        rows["native-source"]["content"] += " changed"
    with pytest.raises(RuntimeError):
        tool.readback_foundation()
