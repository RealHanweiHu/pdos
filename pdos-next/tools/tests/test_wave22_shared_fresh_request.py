"""Owned no-connect control/shape checks; saved rows and qualification are substitutes."""

import importlib.util
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Engine


def owned_source(path):
    folder = Path(path).resolve().parent
    if folder.name == "wave22-fresh-request-staged" and folder.parent.name == ".local":
        return folder / "wave22_shared_fresh_request.py"
    if folder.name == "tests" and folder.parent.name == "tools":
        return folder.parent / "wave22_shared_fresh_request.py"
    raise RuntimeError("Unexpected owned fresh-request check layout")


spec = importlib.util.spec_from_file_location("owned_wave22_fresh", owned_source(__file__))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
base_path = m.ROOT / ".local/wave22-test-staged/v4/test_wave22_shared_test.py"
if Path(__file__).resolve().parent.name == "tests":
    base_path = m.ROOT / "tools/tests/test_wave22_shared_test.py"
base_spec = importlib.util.spec_from_file_location("owned_fresh_first_fixture", base_path)
b = importlib.util.module_from_spec(base_spec)
sys.modules[base_spec.name] = b
base_spec.loader.exec_module(b)


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("DB/HTTP/target/actual private checkpoint access forbidden")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(m.SharedFreshRequest, "target", forbidden)
    monkeypatch.setattr(m.SharedFreshRequest, "origin_guard", forbidden)
    monkeypatch.setattr(m.SharedFreshRequest, "resource_binding", forbidden)


@pytest.fixture
def tool(monkeypatch):
    value = b.tool.__wrapped__(monkeypatch)
    value.__class__ = m.SharedFreshRequest
    value.namespace = str(uuid4())
    return value


def material_group(tool):
    now = datetime.now(UTC)
    source_generation, new_generation = str(uuid4()), tool.namespace
    run_id = str(m.uuid5(m.UUID(source_generation), "original:run"))
    plan = b.receipt(tool, "observer", "test.run.plan", "test_run")
    promise = b.receipt(tool, "observer", "verification.schedule.promise", "verification_request")
    finish = (now - timedelta(minutes=1)).isoformat()
    old = {
        "schema_version": "wave22-shared-test-v1",
        "scope": tool.foundation["scope"],
        "purpose": tool.data["purpose"],
        "build_id": tool.data["build_id"],
        "prospective_generation": {"id": source_generation},
        "run_id": run_id,
        "request_id": str(uuid4()),
        "original_sample_id": tool.data["original_sample_id"],
        "receipts": {"run-plan": plan, "promise": promise},
        "requests": {
            "run-plan": {
                "original": {"payload": {"execution_plan": {"window": {"finish": finish}}}}
            }
        },
        "resource_input": {
            "binding": {"run_id": run_id},
            "resources": [
                {"resource": {"id": str(uuid4())}, "facts": [{"named_decision_id": str(uuid4())}]}
            ],
        },
    }
    raw = {
        "schema_version": "wave22-fresh-request-intent-v1",
        "generation": new_generation,
        "marker": tool.marker,
        "scope": tool.foundation["scope"],
        "purpose": tool.data["purpose"],
        "build_id": tool.data["build_id"],
        "sample_id": tool.data["original_sample_id"],
        "source_generation": source_generation,
        "source_checkpoint_sha256": "a" * 64,
        "source_resource_profile_sha256": "b" * 64,
        "source_resource_input_sha256": "c" * 64,
        "readback_file": "docs/reports/evidence/actual-readback.json",
        "readback_sha256": "d" * 64,
        "decision_file": "docs/reports/evidence/actual-decision.json",
        "decision_sha256": "e" * 64,
        "reason": "Actual old saved window elapsed; distinct legitimate new branch",
    }
    readback = {
        "schema_version": "wave22-saved-planned-no-start-readback-v1",
        "marker": tool.marker,
        "scope": tool.foundation["scope"],
        "source_generation": source_generation,
        "source_checkpoint_sha256": "a" * 64,
        "build_id": old["build_id"],
        "request_id": old["request_id"],
        "run_id": old["run_id"],
        "request_current": {"id": promise["subject_id"], "revision": 1, "status": "scheduled"},
        "run_current": {"id": plan["subject_id"], "revision": 1, "status": "planned"},
        "plan_receipt_id": plan["id"],
        "promise_receipt_id": promise["id"],
        "actual_start_count": 0,
        "resource_occupancy_count": 0,
        "sample_usage_count": 0,
        "checked_at": (now - timedelta(seconds=1)).isoformat(),
    }
    decision = {
        "schema_version": "wave22-fresh-request-decision-v1",
        "marker": tool.marker,
        "scope": tool.foundation["scope"],
        "source_generation": source_generation,
        "source_checkpoint_sha256": "a" * 64,
        "readback_sha256": "d" * 64,
        "generation": new_generation,
        "operation": "create_distinct_formal_from_saved_unstarted_plan",
        "old_saved_plan_and_promise_preserved": True,
        "reason": raw["reason"],
    }
    profile = {
        "tenant_id": tool.foundation["tenant_id"],
        "product_id": tool.product,
        "issuer_key": "exact-old-host-issuer",
        "issuer_version": "v2",
        "decisions": [
            {
                "binding": old["resource_input"]["binding"],
                "resource": old["resource_input"]["resources"][0]["resource"],
                "decision": old["resource_input"]["resources"][0]["facts"][0],
            }
        ],
    }
    return raw, old, profile, readback, decision, now


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "extra",
        "old-generation",
        "wrong-scope",
        "wrong-marker",
        "wrong-read-hash",
        "withdrawal",
        "missing-plan",
        "missing-promise",
        "submitted-start",
        "saved-start",
        "start-count",
        "usage-count",
        "occupancy-count",
        "boolean-zero",
        "wrong-current-id",
        "wrong-current-revision",
        "boolean-revision",
        "wrong-status",
        "wrong-receipt",
        "future-readback",
        "unexpired-window",
        "wrong-sample",
        "old-ledger-missing",
        "new-issuer-version",
    ],
)
def test_new_branch_requires_exact_saved_plan_promise_root_readback_not_unsent_replan(tool, bad):
    raw, old, profile, proof, decision, now = material_group(tool)
    before = deepcopy((raw, old, profile, proof, decision))
    if bad == "extra":
        raw["execution_plan"] = {}
    elif bad == "old-generation":
        raw["generation"] = raw["source_generation"]
    elif bad == "wrong-scope":
        proof["scope"] = {**proof["scope"], "project_id": str(uuid4())}
    elif bad == "wrong-marker":
        decision["marker"] = str(uuid4())
    elif bad == "wrong-read-hash":
        decision["readback_sha256"] = "f" * 64
    elif bad == "withdrawal":
        decision["operation"] = "withdraw_saved_plan"
    elif bad == "missing-plan":
        del old["receipts"]["run-plan"]
    elif bad == "missing-promise":
        del old["receipts"]["promise"]
    elif bad == "submitted-start":
        old["requests"]["run-start"] = {"state": "unknown"}
    elif bad == "saved-start":
        old["receipts"]["run-start"] = {"id": str(uuid4())}
    elif bad == "start-count":
        proof["actual_start_count"] = 1
    elif bad == "usage-count":
        proof["sample_usage_count"] = 1
    elif bad == "occupancy-count":
        proof["resource_occupancy_count"] = 1
    elif bad == "boolean-zero":
        proof["actual_start_count"] = False
    elif bad == "wrong-current-id":
        proof["request_current"]["id"] = str(uuid4())
    elif bad == "wrong-current-revision":
        proof["run_current"]["revision"] = 2
    elif bad == "boolean-revision":
        proof["run_current"]["revision"] = True
    elif bad == "wrong-status":
        proof["request_current"]["status"] = "accepted"
    elif bad == "wrong-receipt":
        proof["plan_receipt_id"] = str(uuid4())
    elif bad == "future-readback":
        proof["checked_at"] = (now + timedelta(hours=1)).isoformat()
    elif bad == "unexpired-window":
        old["requests"]["run-plan"]["original"]["payload"]["execution_plan"]["window"]["finish"] = (
            now + timedelta(minutes=1)
        ).isoformat()
    elif bad == "wrong-sample":
        raw["sample_id"] = str(uuid4())
    elif bad == "old-ledger-missing":
        profile["decisions"] = []
    elif bad == "new-issuer-version":
        profile["issuer_version"] = "v3"
    if bad is None:
        assert (
            m.checked_fresh_material(
                raw,
                old,
                profile,
                proof,
                decision,
                marker=tool.marker,
                scope=tool.foundation["scope"],
                at=now,
            )
            == tool.namespace
        )
        assert (raw, old, profile, proof, decision) == before
        assert "window" not in raw and "occurred_at" not in raw
    else:
        with pytest.raises((m.Missing, ValueError)):
            m.checked_fresh_material(
                raw,
                old,
                profile,
                proof,
                decision,
                marker=tool.marker,
                scope=tool.foundation["scope"],
                at=now,
            )


@pytest.mark.parametrize("layout", ["stage", "real"])
def test_layout_and_namespaced_new_outputs_do_not_overwrite_first_generation(tool, layout):
    folder = (
        Path("/tmp/pdos-next/.local/wave22-fresh-request-staged")
        if layout == "stage"
        else Path("/tmp/pdos-next/tools")
    )
    source = folder / "wave22_shared_fresh_request.py"
    test = (
        folder / "test_wave22_shared_fresh_request.py"
        if layout == "stage"
        else folder / "tests/test_wave22_shared_fresh_request.py"
    )
    assert m.layout_root(source) == Path("/tmp/pdos-next").resolve()
    assert owned_source(test) == source.resolve()
    paths = m.fresh_paths(tool.namespace)
    old = m.first.generation_paths(tool.namespace)
    assert all(a != b for a, b in zip(paths, old, strict=True))
    assert all(tool.namespace in p.name for p in paths)
    assert tool.command_id("formal", "observer") != str(
        m.uuid5(m.UUID(tool.foundation["case_id"]), "observer:formal")
    )


def install_common(tool, monkeypatch):
    def request(role, method, path, *, body=None, params=None):
        tool.calls.append((path, deepcopy(body)))
        if path == "/v1/commands/preview":
            command = deepcopy(body)
            command["payload"]["confirmation_token"] = "synthetic-substitute-token-only"
            return {
                "command": command,
                "review": {"after": {"fixture_only": True}},
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            }
        assert path == "/v1/commands"
        return b.receipt(tool, role, body["operation"], "verification_request")

    monkeypatch.setattr(tool, "request", request)


def prepared(tool, monkeypatch):
    install_common(tool, monkeypatch)
    with pytest.raises(m.Pending):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: b.method_payload(tool),
        )
    return tool.data["requests"]["method"]


def test_unknown_recovery_preserves_same_original_body_key_token_and_revisions(tool, monkeypatch):
    saved = prepared(tool, monkeypatch)
    original = deepcopy(saved)
    tool.confirm, tool.review_digest = "method", saved["review_digest"]
    attempts = []

    def uncertain(role, method, path, *, body=None, params=None):
        assert path == "/v1/commands"
        attempts.append(deepcopy(body))
        raise httpx.ReadTimeout("Explicit offline substitute")

    monkeypatch.setattr(tool, "request", uncertain)
    with pytest.raises(m.Unknown):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("Original before dynamic rebuild"),
        )
    assert saved["state"] == "unknown"
    assert saved["original"] == original["original"] and saved["body"] == original["body"]
    tool.recover = "method"
    with pytest.raises(m.Unknown):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("No reconstruction/rekey"),
        )
    assert attempts == [original["body"], original["body"]]
    assert tool.recover_used is True


def test_actual_receipt_precedes_live_product_revision_or_owner_factory(tool, monkeypatch):
    saved = prepared(tool, monkeypatch)
    receipt = b.receipt(tool, "observer", "verification.method.prepare", "verification_request")
    tool.data["receipts"]["method"] = receipt
    tool.live_revision += 100
    monkeypatch.setattr(tool, "request", lambda *a, **k: pytest.fail("No duplicate HTTP"))
    result = tool.step(
        "method",
        "observer",
        "verification.method.prepare",
        "verification_request",
        lambda: pytest.fail("Saved receipt precedes rebuilt live revision"),
    )
    assert result == receipt
    assert saved["body"] == tool.data["requests"]["method"]["body"]


@pytest.mark.parametrize("tamper", ["actor", "key", "token", "revision", "reads"])
def test_pending_command_material_cannot_change_before_real_common_send(tool, monkeypatch, tamper):
    saved = prepared(tool, monkeypatch)
    if tamper == "actor":
        saved["actor_id"] = tool.actor("maker")
    elif tamper == "key":
        saved["body"]["idempotency_key"] += "altered"
    elif tamper == "token":
        saved["body"]["payload"]["confirmation_token"] += "altered"
    elif tamper == "revision":
        saved["body"]["expected_revision"] += 1
    else:
        saved["body"]["source_read_set"] = []
    tool.confirm, tool.review_digest = "method", saved["review_digest"]
    count = len(tool.calls)
    with pytest.raises(m.Missing):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("No substitute original"),
        )
    assert len(tool.calls) == count


@pytest.mark.parametrize("minutes", [2, 5.1])
def test_future_window_is_selected_only_after_new_acceptance_with_exact_old_physical_mirror(
    tool, monkeypatch, tmp_path, minutes
):
    from pdos_next.domain.test_resources.schemas import TestResourceFactInput
    from pdos_next.engines.planning.calendar import frozen_timezone

    calendar = {
        "calendar_id": "actual-synthetic-original-physical-calendar",
        "version": "1",
        "timezone": "UTC",
        "timezone_rules_sha256": frozen_timezone("UTC")[1],
        "weekly": [
            {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]} for i in range(7)
        ],
    }
    physical = [
        {
            "resource": {"id": identity, "revision": 1, "kind": kind},
            "lifecycle": "active",
            "maintenance": [],
            "capacity": "1",
            "calendar": calendar,
        }
        for identity, kind in (
            (tool.data["test_equipment_id"], "equipment"),
            (tool.actor("observer"), "person"),
        )
    ]
    tool.first_data = {"resource_input": {"resources": deepcopy(physical)}}
    tool.first_profile = {
        "tenant_id": tool.foundation["tenant_id"],
        "product_id": tool.product,
        "issuer_key": "actual-original-host-key",
        "issuer_version": "v2",
        "decisions": [],
    }
    tool.first_profile_path = tmp_path / "old-profile.json"
    tool.h.private_write(tool.first_profile_path, tool.first_profile)
    tool.first_profile_sha = m.first.digest_file(tool.first_profile_path)
    tool.resource_profile_path, tool.resource_input_path = (
        tmp_path / "new-profile.json",
        tmp_path / "new-input.json",
    )
    tool.data["receipts"]["accept"] = {"id": str(uuid4())}
    monkeypatch.setattr(tool, "publication", lambda: None)
    monkeypatch.setattr(tool, "resource_binding", lambda plan: b.fake_binding(tool, plan))
    monkeypatch.setattr(m, "ROOT", tmp_path)
    now = datetime.now(UTC)
    kwargs = {
        "window_start": (now + timedelta(minutes=minutes)).isoformat(),
        "window_end": (now + timedelta(minutes=30)).isoformat(),
        "valid_until": (now + timedelta(hours=1)).isoformat(),
    }
    if minutes < 5:
        with pytest.raises(m.Missing):
            tool.resources(**kwargs)
        assert "resource_input" not in tool.data
        assert not tool.resource_input_path.exists()
        return
    tool.resources(**kwargs)
    raw = TestResourceFactInput.model_validate(tool.data["resource_input"])
    assert raw.binding.run_id == m.UUID(tool.data["run_id"])
    for current, previous in zip(raw.resources, physical, strict=True):
        assert current.resource.model_dump(mode="json") == previous["resource"]
        assert current.calendar.model_dump(mode="json") == type(current.calendar).model_validate(
            calendar
        ).model_dump(mode="json")
        assert current.model_dump(mode="json")["capacity"] == previous["capacity"]
    assert m.first.private_json(tool.first_profile_path) == tool.first_profile
    assert tool.resource_profile_path != tool.first_profile_path
    before = deepcopy(tool.data["execution_plan"])
    with pytest.raises(m.Missing):
        tool.resources(window_start=(now + timedelta(minutes=10)).isoformat())
    assert tool.data["execution_plan"] == before


def test_actual_constructor_preserves_old_saved_group_but_creates_only_new_empty_slots(
    tool, monkeypatch, tmp_path
):
    raw, old, profile, proof, decision, _ = material_group(tool)
    old.update(
        test_equipment_id=tool.data["test_equipment_id"],
        followup_sample_id=tool.data["followup_sample_id"],
        test_publication=deepcopy(tool.data["test_publication"]),
        publication_receipt=b.receipt(tool, "maker", "evidence.artifact.register", "artifact"),
    )
    old["requests"]["run-plan"]["body"] = {
        "payload": {"confirmation_token": "old-consumed-substitute"}
    }
    old_before = deepcopy(old)
    source_paths = m.first.generation_paths(raw["source_generation"])
    material = tmp_path / "new-intent.json"
    values = {
        material: raw,
        source_paths[0]: old,
        source_paths[1]: profile,
        source_paths[2]: old["resource_input"],
        m.first.FOUNDATION: tool.foundation,
        m.first.BUILD: {"case_id": str(uuid4())},
    }
    hashes = {
        source_paths[0]: raw["source_checkpoint_sha256"],
        source_paths[1]: raw["source_resource_profile_sha256"],
        source_paths[2]: raw["source_resource_input_sha256"],
        m.first.FOUNDATION: "1" * 64,
        m.first.BUILD: "2" * 64,
    }
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(
        m.SharedFreshRequest,
        "target",
        lambda self: {"preview_tenant_id": tool.foundation["tenant_id"]},
    )
    monkeypatch.setattr(m.first, "private_json", lambda path, **kwargs: deepcopy(values[path]))
    monkeypatch.setattr(m.first, "digest_file", lambda path: hashes[path])
    monkeypatch.setattr(m.first, "foundation_contract", lambda data, marker: data)
    monkeypatch.setattr(m.first, "build_contract", lambda *a: tool.build)
    monkeypatch.setattr(m.first, "build_foundation_binding", lambda *a: "3" * 64)
    monkeypatch.setattr(m.first.SharedTest, "_origin_files", lambda *a: None)
    monkeypatch.setattr(
        m.first,
        "evidence_file",
        lambda path: (
            (proof, raw["readback_sha256"])
            if path == raw["readback_file"]
            else (decision, raw["decision_sha256"])
        ),
    )
    actual = m.SharedFreshRequest(tool.marker, generation=raw["generation"], material=material)
    assert actual.data["origin_archive"] == old_before
    assert old == old_before
    assert actual.data["requests"] == actual.data["receipts"] == actual.data["events"] == {}
    assert actual.data["run_id"] != old["run_id"]
    assert actual.data["request_id"] != old["request_id"]
    assert actual.command_id("run-plan", "observer") != str(
        m.uuid5(m.UUID(raw["source_generation"]), "observer:run-plan")
    )
    assert "execution_plan" not in actual.data
    assert "resource_input" not in actual.data


def test_current_full_read_set_limit_remains_failclosed(tool):
    existing = tool.reads()
    extra = [b.read(b.ref()) for _ in range(20 - len(existing))]
    assert len(tool.reads(extra)) == 20
    with pytest.raises(RuntimeError):
        tool.reads(extra + [b.read(b.ref())])
    with pytest.raises(RuntimeError):
        tool.reads([{**existing[0], "expected_revision": 2}])
    with pytest.raises(m.Missing):
        tool.actor("independent_reviewer")


@pytest.mark.parametrize("mode", ["large", "oversize", "unsafe_mode", "symlink"])
def test_only_internal_checkpoint_has_larger_finite_bound(tmp_path, mode):
    import json

    path = tmp_path / "owned.json"
    value = {"complete_history": "x" * 2_050_000}
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    if mode == "oversize":
        with path.open("a") as handle:
            handle.truncate(m.CHECKPOINT_MAX_BYTES + 1)
    elif mode == "unsafe_mode":
        path.chmod(0o644)
    elif mode == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        path = link
    if mode == "large":
        assert m.checkpoint_json(path) == value
        with pytest.raises(m.Missing):
            m.first.private_json(path)
    else:
        with pytest.raises(m.Missing):
            m.checkpoint_json(path)


def test_internal_save_bound_rejects_before_replacing_complete_history():
    with pytest.raises(m.Missing):
        m.checkpoint_fits({"whole_history": "x" * (m.CHECKPOINT_MAX_BYTES + 1)})
