"""Owned staged control checks only; all business/IO materials below are substitutes."""

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
    if folder.name == "wave22-retest-staged" and folder.parent.name == ".local":
        return folder / "wave22_shared_retest.py"
    if (
        folder.name in {"v2", "v3"}
        and folder.parent.name == "wave22-retest-staged"
        and folder.parent.parent.name == ".local"
    ):
        return folder / "wave22_shared_retest.py"
    if folder.name == "tests" and folder.parent.name == "tools":
        return folder.parent / "wave22_shared_retest.py"
    raise RuntimeError("Unexpected owned retest check layout")


spec = importlib.util.spec_from_file_location("owned_wave22_retest", owned_source(__file__))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
base_path = m.ROOT / ".local/wave22-test-staged/v4/test_wave22_shared_test.py"
if Path(__file__).resolve().parent.name == "tests":
    base_path = m.ROOT / "tools/tests/test_wave22_shared_test.py"
base_spec = importlib.util.spec_from_file_location("pure_first_v4_fixture_definitions", base_path)
b = importlib.util.module_from_spec(base_spec)
sys.modules[base_spec.name] = b
base_spec.loader.exec_module(b)
from pdos_next.contracts import PAYLOADS  # noqa: E402


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No DB/HTTP/actual checkpoint access in owned pure checks")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(m.SharedRetest, "target", forbidden)
    monkeypatch.setattr(m.SharedRetest, "resource_binding", forbidden)


@pytest.fixture
def tool(monkeypatch):
    value = b.tool.__wrapped__(monkeypatch)
    value.__class__ = m.SharedRetest
    value.namespace = str(uuid4())
    value.first_generation = str(uuid4())
    value.first_data = {
        "run_id": str(m.uuid5(m.UUID(value.first_generation), "original:run")),
        "request_id": str(uuid4()),
    }
    value.data.update(materials={}, capa_id=str(uuid4()), capa_action_id=str(uuid4()))
    value.data["issue_id"] = str(uuid4())
    return value


def install_common(tool, monkeypatch, family="verification_request", t2=False):
    def request(role, method, path, *, body=None, params=None):
        assert method == "POST"
        tool.calls.append((path, deepcopy(body)))
        if path == "/v1/commands/preview":
            prepared = deepcopy(body)
            prepared["payload"]["approval_token" if t2 else "confirmation_token"] = "t" * 30
            return {
                "command": prepared,
                "review": {"after": {"explicit_substitute": True}},
                "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
                **({"write_tier": "T2", "named_decision": True} if t2 else {}),
            }
        assert path == "/v1/commands"
        return b.receipt(tool, role, body["operation"], family)

    monkeypatch.setattr(tool, "request", request)


def prepare(tool, monkeypatch):
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


@pytest.mark.parametrize("layout", ["stage", "stage_v2", "stage_v3", "real"])
def test_two_actual_path_layouts_and_only_new_outputs(layout):
    folder = (
        Path("/tmp/pdos-next/.local/wave22-retest-staged")
        if layout == "stage"
        else Path("/tmp/pdos-next/.local/wave22-retest-staged/v2")
        if layout == "stage_v2"
        else Path("/tmp/pdos-next/.local/wave22-retest-staged/v3")
        if layout == "stage_v3"
        else Path("/tmp/pdos-next/tools")
    )
    source = folder / "wave22_shared_retest.py"
    test = (
        folder / "test_wave22_shared_retest.py"
        if layout in {"stage", "stage_v2", "stage_v3"}
        else folder / "tests/test_wave22_shared_retest.py"
    )
    assert m.layout_root(source) == Path("/tmp/pdos-next").resolve()
    assert owned_source(test) == source.resolve()
    assert m.CHECKPOINT != m.selected_first_paths(str(uuid4()))[0]
    assert m.first.CHECKPOINT != m.CHECKPOINT
    assert m.first.RESOURCE_PROFILE != m.RESOURCE_PROFILE
    assert "retest" in m.RESOURCE_INPUT.name and "retest" in m.COMPLETION_PROFILE.name


def test_controller_namespace_never_reuses_first_run_key_or_command(tool, monkeypatch):
    prepared = prepare(tool, monkeypatch)
    original = prepared["original"]
    assert original["idempotency_key"] == tool.key("method")
    assert original["command_id"] != str(
        m.uuid5(m.UUID(tool.foundation["case_id"]), "observer:method")
    )
    assert original["command_id"] == str(m.uuid5(m.UUID(tool.namespace), "observer:method"))
    assert len(tool.calls) == 1


@pytest.mark.parametrize("field", ["label", "digest"])
def test_confirmation_requires_original_exact_label_and_material(tool, monkeypatch, field):
    saved = prepare(tool, monkeypatch)
    tool.confirm = "different" if field == "label" else "method"
    tool.review_digest = saved["review_digest"] if field == "label" else "f" * 64
    with pytest.raises(m.Pending):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("No replacement material"),
        )
    assert len(tool.calls) == 1


def test_unknown_keeps_body_key_token_version_and_single_original_recovery(tool, monkeypatch):
    saved = prepare(tool, monkeypatch)
    exact = deepcopy(saved["body"])
    tool.confirm, tool.review_digest = "method", saved["review_digest"]
    monkeypatch.setattr(
        tool, "request", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("substitute"))
    )
    with pytest.raises(m.Unknown):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("No rebuilt body"),
        )
    assert saved["state"] == "unknown"
    tool.live_revision = 99
    tool.recover = "method"
    install_common(tool, monkeypatch)
    receipt = tool.step(
        "method",
        "observer",
        "verification.method.prepare",
        "verification_request",
        lambda: pytest.fail("UNKNOWN bypasses live factory"),
    )
    assert tool.calls[-1] == ("/v1/commands", exact)
    assert tool.recover_used is True
    monkeypatch.setattr(tool, "get", lambda *a, **k: pytest.fail("Saved receipt precedes GET"))
    assert (
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("Saved receipt precedes factory"),
        )
        == receipt
    )


@pytest.mark.parametrize("field", ["actor", "operation", "key", "payload", "token", "namespace"])
def test_tampered_original_is_rejected_without_new_send(tool, monkeypatch, field):
    saved = prepare(tool, monkeypatch)
    if field == "actor":
        saved["actor_id"] = tool.actor("maker")
    elif field == "operation":
        saved["original"]["operation"] = "verification.request.create"
    elif field == "key":
        saved["original"]["idempotency_key"] += "-replacement"
    elif field == "payload":
        saved["body"]["payload"]["reason"] = "Different reason"
    elif field == "token":
        saved["body"]["payload"]["confirmation_token"] = "x" * 30
    else:
        tool.namespace = str(uuid4())
    with pytest.raises(m.Missing):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: b.method_payload(tool),
        )
    assert len(tool.calls) == 1


@pytest.mark.parametrize("state", ["preview_unknown", "rejected"])
def test_uncertain_preview_or_domain_refusal_never_gets_replacement_token(tool, monkeypatch, state):
    saved = prepare(tool, monkeypatch)
    saved["state"] = state
    with pytest.raises(m.Missing):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: b.method_payload(tool),
        )
    assert len(tool.calls) == 1


def test_root_t2_real_registered_payload_has_distinct_named_token(tool, monkeypatch):
    install_common(tool, monkeypatch, family="quality_issue", t2=True)
    reference = m.source_ref(tool.ref())

    def payload():
        return {
            "issue_id": tool.data["issue_id"],
            "expected_issue_revision": 4,
            "text": "Explicit synthetic root-cause proposal",
            "sources": [reference],
        }, tool.reads()

    with pytest.raises(m.Pending):
        tool.step(
            "root-cause", "maker", "quality.issue.root_cause.decide", "quality_issue", payload
        )
    saved = tool.data["requests"]["root-cause"]
    assert saved["tier"] == "T2" and "approval_token" in saved["body"]["payload"]
    assert "confirmation_token" not in saved["body"]["payload"]
    tool.confirm, tool.review_digest = "root-cause", saved["review_digest"]
    tool.step("root-cause", "maker", "quality.issue.root_cause.decide", "quality_issue", payload)
    assert tool.confirm_used and len(tool.calls) == 2


def test_complete_source_union_cannot_trim_conflicting_or_twenty_first_source(tool):
    existing = tool.reads()
    extra = [b.read(b.ref()) for _ in range(20 - len(existing))]
    assert len(tool.reads(extra)) == 20
    with pytest.raises(RuntimeError):
        tool.reads(extra + [b.read(b.ref())])
    with pytest.raises(RuntimeError):
        tool.reads([{**existing[0], "expected_revision": 2}])
    with pytest.raises(m.Missing):
        tool.actor("independent_reviewer")


def issue_row(tool, **changes):
    action = {
        "id": tool.data["capa_action_id"],
        "kind": "corrective",
        "text": "Investigate fixed dimension",
        "executor_id": tool.actor("maker"),
        "completion": None,
    }
    return {
        "id": str(uuid4()),
        "issue_id": tool.data["issue_id"],
        "revision": 4,
        "source_status": "current",
        "visibility": "product",
        "owner_id": tool.actor("maker"),
        "project_id": tool.foundation["project_id"],
        "purpose": tool.data["purpose"],
        "status": "actioning",
        "required_source_read_set": tool.reads(),
        "issue": {
            "root_cause": None,
            "capa": {"id": tool.data["capa_id"], "actions": [action], "effectiveness": None},
            "closure": None,
        },
        **changes,
    }


def test_actual_three_line_source_and_new_scope_classification_are_export_not_install(
    tool, monkeypatch, tmp_path
):
    from pdos_next.domain.quality_followup.schemas import CompletionFact
    from pdos_next.quality_followup_bootstrap import ClassificationFact, CompletionProfile
    from pdos_next.service import digest

    row = issue_row(tool)
    material = {
        "root_text": "Explicit synthetic investigation root proposal",
        "completion_text": "Maker actually inspected the fixed raw report; no physical remediation",
        "occurred_at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat(),
        "original_timezone": "UTC",
        "valid_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    monkeypatch.setattr(tool, "selected_material", lambda *a, **k: deepcopy(material))
    monkeypatch.setattr(tool, "current_issue", lambda: row)
    publication = []

    def step(label, role, op, family, factory, **kwargs):
        raw, reads = factory()
        PAYLOADS[op].model_validate(raw)
        publication.append(raw)
        return b.receipt(tool, role, op, family)

    monkeypatch.setattr(tool, "step", step)
    monkeypatch.setattr(m, "COMPLETION_PROFILE", tmp_path / "new-profile.json")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    result = tool.remediation_sources()
    lines = publication[0]["content"].splitlines()
    assert len(lines) == 3 and publication[0]["visibility"] == "product"
    actual = CompletionFact.model_validate_json(lines[1])
    classification = ClassificationFact.model_validate_json(lines[2])
    assert actual.executor_id == m.UUID(tool.actor("maker"))
    assert classification.classification == "investigation" and classification.nature == "synthetic"
    assert classification.action_sha256 == digest(
        {k: v for k, v in row["issue"]["capa"]["actions"][0].items() if k != "completion"}
    )
    saved = CompletionProfile.model_validate_json(m.COMPLETION_PROFILE.read_text())
    assert saved.project_id == m.UUID(tool.foundation["project_id"])
    assert result["requires_root_explicit_plural_profile_configuration"] is True
    assert result["physical_action_fulfilled"] is None


@pytest.mark.parametrize("field", ["status", "root", "completion", "executor", "effective"])
def test_completed_basis_is_not_inferred_from_material_or_caller_grant(tool, monkeypatch, field):
    row = issue_row(tool, status="awaiting_verification")
    row["issue"]["root_cause"] = {"text": "Actual named source substitute"}
    row["issue"]["capa"]["actions"][0]["completion"] = {
        "text": "Actual saved completion substitute"
    }
    if field == "status":
        row["status"] = "actioning"
    elif field == "root":
        row["issue"]["root_cause"] = None
    elif field == "completion":
        row["issue"]["capa"]["actions"][0]["completion"] = None
    elif field == "executor":
        row["issue"]["capa"]["actions"][0]["executor_id"] = tool.actor("observer")
    else:
        row["issue"]["capa"]["effectiveness"] = {"result": "effective"}
    monkeypatch.setattr(tool, "current_issue", lambda: row)
    with pytest.raises(m.Missing):
        tool.completed()


def test_missing_completion_owner_does_not_claim_saved_or_draft_second_run(tool, monkeypatch):
    tool.data["remediation_refs"] = [tool.ref(), tool.ref(2), tool.ref()]
    tool.data["materials"]["remediation"] = {"root_text": "Explicit proposal"}
    row = issue_row(tool)
    row["issue"]["root_cause"] = {"text": "Actual root substitute"}
    tool.data["completion_fact"] = {
        "action_id": tool.data["capa_action_id"],
        "executor_id": tool.actor("maker"),
        "text": "Explicit observed completion",
        "occurred_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
        "original_timezone": "UTC",
    }
    monkeypatch.setattr(tool, "current_issue", lambda: row)

    def request(*args, **kwargs):
        raise tool.h.GuardedRequestError(503, "INTEGRATION_REQUIRED")

    monkeypatch.setattr(tool, "request", request)
    with pytest.raises(tool.h.GuardedRequestError):
        tool.complete()
    assert "complete" not in tool.data["receipts"]
    monkeypatch.setattr(
        tool, "completed", lambda: (_ for _ in ()).throw(m.Missing("actual missing"))
    )
    monkeypatch.setattr(
        tool, "publication", lambda: pytest.fail("No second preparation before completion")
    )
    with pytest.raises(m.Missing):
        tool.draft()


@pytest.mark.parametrize(
    "stage,option", [("current", "missing"), ("current", "old_draft"), ("draft", "advanced")]
)
def test_link_uses_actual_owner_current_and_never_old_run_origin(tool, monkeypatch, stage, option):
    tool.data["receipts"]["disposition"] = {"id": str(uuid4())}
    monkeypatch.setattr(tool, "completed", lambda: None)
    request = {"id": str(uuid4()), "revision": 8, "status": "dispositioned"}
    ref = {"kind": "verification_request", "id": request["id"], "revision": 8, "key": None}
    options = [{"ref": ref, "logical_id": tool.data["request_id"]}]
    if option == "missing":
        options = []
    elif option == "old_draft":
        options[0]["ref"] = {**ref, "id": str(uuid4()), "revision": 1}
    monkeypatch.setattr(tool, "current", lambda *a, **k: ({}, request, None))
    monkeypatch.setattr(
        tool,
        "request",
        lambda *a, **k: {
            "current": {"revision": 6},
            "output_options": options,
            "required_source_read_set": tool.reads(),
        },
    )
    monkeypatch.setattr(tool, "step", lambda a, b, c, d, factory, **kwargs: factory())
    with pytest.raises(m.Missing):
        tool.link(stage=stage)


def test_second_result_unknown_stays_unknown_no_pass_or_effective_inference(tool, monkeypatch):
    identity = str(uuid4())
    projection = {
        "id": identity,
        "revision": 1,
        "basis_sha256": "a" * 64,
        "result": "indeterminate",
    }
    row = {"id": str(uuid4()), "revision": 8, "required_source_read_set": tool.reads()}
    run = {
        "id": str(uuid4()),
        "run_id": tool.data["run_id"],
        "revision": 3,
        "basis_sha256": "a" * 64,
        "required_source_read_set": tool.reads(),
        "current_projection": projection,
    }
    tool.data["receipts"]["compute"] = {"subject_id": identity, "subject_revision": 1}
    monkeypatch.setattr(tool, "current", lambda *a, **k: ({}, row, run))
    result = tool.readback()
    assert result["result"] == "indeterminate" and result["independent_review_saved"] is False
    assert (
        tool.data["result_readback"]["effectiveness"] is None
        and tool.data["result_readback"]["close"] is False
    )


def test_full_quote_source_ref_preserves_line_and_does_not_assume_owner_proof(tool):
    reference = tool.ref(2)
    source = m.source_ref(reference)
    assert (
        source["position"]
        == "line:2;quote_sha256:" + m.hashlib.sha256(reference["quote"].encode()).hexdigest()
    )
    assert source["revision"] == reference["expected_revision"]


@pytest.mark.parametrize("tamper", [None, "scope", "sample", "result", "projection"])
def test_first_run_requires_real_failed_branch_shape_not_private_or_old_guess(tool, tamper):
    projection = {"id": str(uuid4()), "revision": 1, "result": "fail", "basis_sha256": "a" * 64}
    raw = {
        "schema_version": "wave22-shared-test-v1",
        "phase": "actual_original_definite_fail_no_issue_or_review",
        "prospective_generation": {
            "id": tool.first_generation,
            "material": {"generation": tool.first_generation},
        },
        "scope": tool.foundation["scope"],
        "purpose": tool.data["purpose"],
        "build_id": tool.data["build_id"],
        "original_sample_id": tool.build["samples"][0]["id"],
        "followup_sample_id": tool.build["samples"][1]["id"],
        "run_id": tool.first_data["run_id"],
        "report_sha256": "a" * 64,
        "receipts": {
            "results": {},
            "run-start": {},
            "compute": {"subject_id": projection["id"], "subject_revision": 1},
        },
        "result_readback": {
            "run_id": tool.first_data["run_id"],
            "result": "fail",
            "projection": projection,
            "run_version_id": str(uuid4()),
            "run_revision": 3,
            "request_version_id": str(uuid4()),
            "request_revision": 7,
            "report_sha256": "a" * 64,
        },
    }
    if tamper == "scope":
        raw["scope"] = {**raw["scope"], "product_id": str(uuid4())}
    elif tamper == "sample":
        raw["followup_sample_id"] = raw["original_sample_id"]
    elif tamper == "result":
        raw["result_readback"]["result"] = "indeterminate"
    elif tamper == "projection":
        raw["result_readback"]["projection"]["id"] = str(uuid4())
    if tamper is None:
        assert (
            m.first_contract(raw, tool.foundation, tool.build, generation=tool.first_generation)
            is raw
        )
    else:
        with pytest.raises(m.Missing):
            m.first_contract(raw, tool.foundation, tool.build, generation=tool.first_generation)


def test_second_resource_fact_keeps_global_physical_mirror_and_new_binding_decisions(
    tool, monkeypatch, tmp_path
):
    from pdos_next.domain.test_resources.schemas import TestResourceFactInput as ResourceInput
    from pdos_next.engines.planning.calendar import frozen_timezone

    calendar = {
        "calendar_id": "original-actual-physical-calendar",
        "version": "1",
        "timezone": "UTC",
        "timezone_rules_sha256": frozen_timezone("UTC")[1],
        "weekly": [
            {"weekday": i, "intervals": [{"start_minute": 0, "end_minute": 1440}]} for i in range(7)
        ],
    }
    original = [
        {
            "resource": {"id": identity, "revision": 1, "kind": kind},
            "lifecycle": "active",
            "maintenance": [],
            "capacity": "1",
            "calendar": deepcopy(calendar),
        }
        for kind, identity in [
            ("equipment", tool.data["test_equipment_id"]),
            ("person", tool.actor("observer")),
        ]
    ]
    tool.first_data["resource_input"] = {"resources": original}
    tool.first_profile_path = tmp_path / "first-profile.json"
    tool.first_profile = {
        "tenant_id": tool.foundation["tenant_id"],
        "product_id": tool.product,
        "issuer_key": "actual-first-shared-issuer",
        "issuer_version": "v2",
        "decisions": [],
    }
    tool.h.private_write(tool.first_profile_path, tool.first_profile)
    tool.first_profile_sha = m.first.digest_file(tool.first_profile_path)
    tool.data["receipts"]["accept"] = {"id": str(uuid4())}
    monkeypatch.setattr(tool, "publication", lambda: None)
    monkeypatch.setattr(tool, "resource_binding", lambda plan: b.fake_binding(tool, plan))
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "RESOURCE_PROFILE", tmp_path / "retest-profile.json")
    monkeypatch.setattr(m, "RESOURCE_INPUT", tmp_path / "retest-input.json")
    now = datetime.now(UTC)
    result = tool.resources(
        window_start=(now + timedelta(minutes=20)).isoformat(),
        window_end=(now + timedelta(hours=1)).isoformat(),
        valid_until=(now + timedelta(hours=2)).isoformat(),
    )
    actual = ResourceInput.model_validate(tool.data["resource_input"])
    assert all(
        r.calendar.model_dump(mode="json")
        == type(r.calendar).model_validate(calendar).model_dump(mode="json")
        for r in actual.resources
    )
    assert {str(r.resource.id) for r in actual.resources} == {r["resource"]["id"] for r in original}
    assert actual.binding.run_id == m.UUID(tool.data["run_id"])
    assert result["requires_root_trusted_import_and_api_plural_reload"] is True
    assert "resource" not in tool.data["receipts"]
    assert all(d.operation_id == "test.run.start" for r in actual.resources for d in r.facts)

    # Existing ledger rows are real writer-shaped substitutes, not qualification.
    raw = tool.data["resource_input"]
    old_entry = {
        "binding": deepcopy(raw["binding"]),
        "resource": deepcopy(raw["resources"][0]["resource"]),
        "decision": deepcopy(raw["resources"][0]["facts"][0]),
    }
    old_entry["binding"]["run_id"] = str(uuid4())
    old_entry["decision"]["named_decision_id"] = str(uuid4())
    original_profile = {**tool.first_profile, "decisions": [old_entry]}
    before = deepcopy(original_profile)
    merged = m.retained_resource_profile(original_profile, raw, tool.foundation["scope"])
    assert original_profile == before
    assert merged["decisions"][:1] == before["decisions"]
    assert merged["issuer_key"] == before["issuer_key"]
    assert merged["issuer_version"] == "v2"
    assert len(merged["decisions"]) == 1 + sum(len(r["facts"]) for r in raw["resources"])
    merged["decisions"][0]["binding"]["purpose"] = "tampered copy"
    assert original_profile == before

    duplicate = deepcopy(before)
    duplicate["decisions"][0]["decision"]["named_decision_id"] = raw["resources"][0]["facts"][0][
        "named_decision_id"
    ]
    with pytest.raises(ValueError, match="cannot repeat"):
        m.retained_resource_profile(duplicate, raw, tool.foundation["scope"])
    for field, value in (
        ("tenant_id", str(uuid4())),
        ("product_id", str(uuid4())),
        ("issuer_version", "v3"),
    ):
        wrong = {**before, field: value}
        with pytest.raises(m.Missing):
            m.retained_resource_profile(wrong, raw, tool.foundation["scope"])


def saved_first_result(tool):
    projection = {"id": str(uuid4()), "revision": 1, "result": "fail", "basis_sha256": "a" * 64}
    return {
        "schema_version": "wave22-shared-test-v1",
        "phase": "actual_original_definite_fail_no_issue_or_review",
        "prospective_generation": {
            "id": tool.first_generation,
            "material": {"generation": tool.first_generation},
        },
        "scope": tool.foundation["scope"],
        "purpose": tool.data["purpose"],
        "build_id": tool.data["build_id"],
        "original_sample_id": tool.build["samples"][0]["id"],
        "followup_sample_id": tool.build["samples"][1]["id"],
        "run_id": str(m.uuid5(m.UUID(tool.first_generation), "original:run")),
        "report_sha256": "b" * 64,
        "receipts": {
            "run-start": {"id": str(uuid4())},
            "results": {"id": str(uuid4())},
            "compute": {"subject_id": projection["id"], "subject_revision": 1},
        },
        "result_readback": {
            "run_id": str(m.uuid5(m.UUID(tool.first_generation), "original:run")),
            "run_version_id": str(uuid4()),
            "run_revision": 3,
            "request_version_id": str(uuid4()),
            "request_revision": 7,
            "result": "fail",
            "projection": projection,
            "report_sha256": "b" * 64,
            "required_source_read_set": tool.reads(),
        },
    }


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", str(uuid4()).upper()])
def test_first_generation_is_required_and_no_default_path_fallback(bad):
    with pytest.raises((m.Missing, ValueError)):
        m.selected_first_paths(bad)


def test_selected_generation_uses_exact_file_not_the_old_default(tool):
    selected, profile, resource = m.selected_first_paths(tool.first_generation)
    assert selected == m.ROOT / f".local/wave22-shared-test-generation-{tool.first_generation}.json"
    assert selected != m.first.CHECKPOINT
    assert (
        str(tool.first_generation) in profile.name and str(tool.first_generation) in resource.name
    )
    assert str(m.uuid5(m.UUID(tool.first_generation), "shared-followup-second-run")) != str(
        m.uuid5(m.UUID(tool.foundation["case_id"]), "shared-followup-second-run")
    )


@pytest.mark.parametrize(
    "bad",
    [
        "other-generation",
        "old-default",
        "plan-only",
        "promise-only",
        "missing-start",
        "missing-import",
        "missing-compute",
        "report-hash",
        "origin-instead-current",
        "bool-revision",
    ],
)
def test_no_second_branch_before_actual_selected_first_results_saved(tool, bad):
    value = saved_first_result(tool)
    if bad == "other-generation":
        value["prospective_generation"]["id"] = str(uuid4())
    elif bad == "old-default":
        value.pop("prospective_generation")
    elif bad == "plan-only":
        value["phase"] = "actual_original_plan_saved_no_start"
    elif bad == "promise-only":
        value["phase"] = "actual_original_promised_no_start"
    elif bad == "missing-start":
        value["receipts"].pop("run-start")
    elif bad == "missing-import":
        value["receipts"].pop("results")
    elif bad == "missing-compute":
        value["receipts"].pop("compute")
    elif bad == "report-hash":
        value["result_readback"]["report_sha256"] = "c" * 64
    elif bad == "origin-instead-current":
        value["run_id"] = str(uuid4())
    else:
        value["result_readback"]["run_revision"] = True
    with pytest.raises(m.Missing):
        m.first_contract(value, tool.foundation, tool.build, generation=tool.first_generation)


@pytest.mark.parametrize("mode", ["first", "fresh"])
def test_pending_first_generation_constructor_does_not_create_retest_state(
    tool, monkeypatch, tmp_path, mode
):
    normalized = m.first.build_foundation_binding(tool.foundation, tool.marker)
    build_raw = {
        "schema_version": "wave22-shared-build-v1",
        "phase": "two_A_readiness_facts_saved_no_handoff_or_test_run",
        "marker": tool.marker,
        "foundation_sha256": normalized,
        "case_id": str(uuid4()),
        "continuation": tool.build,
    }
    first_path = tmp_path / "selected-first.json"
    monkeypatch.setattr(m, "CHECKPOINT", tmp_path / "new-retest.json")
    monkeypatch.setattr(
        m,
        "selected_first_paths",
        lambda g: (first_path, tmp_path / "profile.json", tmp_path / "input.json"),
    )
    if mode == "fresh":
        from types import SimpleNamespace

        monkeypatch.setattr(
            m,
            "fresh_module",
            lambda: SimpleNamespace(
                fresh_paths=lambda g: (
                    first_path,
                    tmp_path / "fresh-profile.json",
                    tmp_path / "fresh-input.json",
                )
            ),
        )
    monkeypatch.setattr(
        m.SharedRetest, "target", lambda self: {"preview_tenant_id": tool.foundation["tenant_id"]}
    )
    monkeypatch.setattr(m.first, "digest_file", lambda path: "a" * 64)
    monkeypatch.setattr(
        m.first,
        "private_json",
        lambda path, **kwargs: deepcopy(
            tool.foundation
            if path == m.first.FOUNDATION
            else build_raw
            if path == m.first.BUILD
            else {"phase": "new_prospective_intent_no_resource_fact_or_plan"}
        ),
    )
    monkeypatch.setattr(
        m.SharedRetest, "save", lambda *a: pytest.fail("No allocation before actual First result")
    )
    with pytest.raises(m.Missing, match="saved definite-fail"):
        m.SharedRetest(
            tool.marker,
            **(
                {"first_generation": tool.first_generation}
                if mode == "first"
                else {"fresh_generation": FRESH_GENERATION}
            ),
        )
    assert not m.CHECKPOINT.exists()


def test_saved_closure_source_budget_deduplicates_shared_refs_without_truncation(tool):
    first_reads = tool.reads()
    tool.first_data["result_readback"] = {"required_source_read_set": first_reads}
    tool.data["requests"] = {"fixed-command": {"original": {"source_read_set": first_reads}}}
    native = b.ref()
    tool.data["receipts"]["remediation-native"] = b.receipt(
        tool, "maker", "evidence.artifact.register", "artifact", native["artifact_id"]
    )
    budget = tool.source_budget()
    assert budget["source_count"] == len(tool.h.merge_reads(first_reads, [b.read(native)]))
    assert budget["named_review_effectiveness_and_close_available"] is False
    tool.data["requests"]["more"] = {
        "original": {"source_read_set": [b.read(b.ref()) for _ in range(21)]}
    }
    with pytest.raises(RuntimeError):
        tool.source_budget()
    tool.data["requests"]["more"] = {
        "original": {
            "source_read_set": [
                {**first_reads[0], "expected_revision": first_reads[0]["expected_revision"] + 1}
            ]
        }
    }
    with pytest.raises(RuntimeError):
        tool.source_budget()


def actual_conclusion_view(tool):
    reads = tool.reads()
    return (
        {},
        {"required_source_read_set": reads},
        {
            "basis_sha256": "a" * 64,
            "current_projection": {"id": str(uuid4()), "revision": 1, "basis_sha256": "a" * 64},
            "required_source_read_set": reads,
        },
    )


def test_named_events_follow_actual_eight_field_result_writer_and_preserve_sources(
    tool, monkeypatch
):
    now = datetime.now(UTC)
    material = {
        "review_text": "Actual named review",
        "review_at": (now - timedelta(seconds=3)).isoformat(),
        "disposition_text": "Actual named disposition",
        "disposition_at": (now - timedelta(seconds=2)).isoformat(),
    }
    monkeypatch.setattr(tool, "current", lambda *a, **kw: actual_conclusion_view(tool))
    captured = []

    def step(label, role, operation, family, payload, **kwargs):
        value, reads = payload()
        captured.append(deepcopy(value))
        return b.receipt(tool, role, operation, family)

    monkeypatch.setattr(tool, "step", step)
    outputs = tool.conclusion_events(material)
    lines = captured[0]["content"].splitlines()
    expected_keys = {
        "request_id",
        "run_id",
        "purpose",
        "operation",
        "actor_id",
        "occurred_at",
        "text",
        "basis_sha256",
    }
    import json

    for index, label in enumerate(("review", "disposition")):
        row = json.loads(lines[index])
        assert set(row) == expected_keys
        assert row["text"] == material[label + "_text"]
        assert row["basis_sha256"] == "a" * 64
        assert outputs[label]["reference"]["quote"] == lines[index]
        assert outputs[label]["reference"]["line"] == index + 1
    unchanged = deepcopy(tool.data["events"]["named-conclusions"])
    changed = actual_conclusion_view(tool)
    changed[2]["basis_sha256"] = "b" * 64
    changed[2]["current_projection"]["basis_sha256"] = "b" * 64
    monkeypatch.setattr(tool, "current", lambda *a, **kw: changed)
    with pytest.raises(m.Missing, match="cannot change"):
        tool.conclusion_events(material)
    assert tool.data["events"]["named-conclusions"] == unchanged


@pytest.mark.parametrize("bad", ["future", "before-review", "missing-projection", "wrong-basis"])
def test_named_event_publication_requires_actual_clocks_and_projection(tool, monkeypatch, bad):
    now = datetime.now(UTC)
    material = {
        "review_text": "Review",
        "review_at": (now - timedelta(seconds=3)).isoformat(),
        "disposition_text": "Disposition",
        "disposition_at": (now - timedelta(seconds=2)).isoformat(),
    }
    view = actual_conclusion_view(tool)
    if bad == "future":
        material["review_at"] = (now + timedelta(minutes=1)).isoformat()
    elif bad == "before-review":
        material["disposition_at"] = (now - timedelta(seconds=4)).isoformat()
    elif bad == "missing-projection":
        view[2]["current_projection"] = None
    else:
        view[2]["current_projection"]["basis_sha256"] = "c" * 64
    monkeypatch.setattr(tool, "current", lambda *a, **kw: view)
    monkeypatch.setattr(tool, "step", lambda *a, **kw: pytest.fail("No publication"))
    with pytest.raises(m.Missing):
        tool.conclusion_events(material)
    assert "named-conclusions" not in tool.data["events"]


def test_precompletion_prepares_real_owner_payloads_only_no_link_or_start(tool, monkeypatch):
    monkeypatch.setattr(tool, "current_issue", lambda: issue_row(tool))
    monkeypatch.setattr(tool, "completed", lambda: pytest.fail("No completion inferred"))
    monkeypatch.setattr(tool, "publication", lambda: None)
    sample = deepcopy(tool.data["sample_ref"])
    row = {"revision": 2, "required_source_read_set": tool.reads()}
    monkeypatch.setattr(tool, "current", lambda *a, **k: ({}, row, None))
    monkeypatch.setattr(tool, "selected", lambda view: (sample, tool.reads()))

    def get(family, role="observer"):
        receipt = tool.data["receipts"]["preparation"]
        return {
            "preparations": [
                {
                    "id": receipt["subject_id"],
                    "revision": 1,
                    "sha256": "a" * 64,
                    "source_status": "current",
                    "required_source_read_set": tool.reads(),
                }
            ]
        }

    monkeypatch.setattr(tool, "get", get)
    operations = []

    def step(label, role, operation, family, factory, **kwargs):
        payload, reads = factory()
        PAYLOADS[operation].model_validate(payload)
        operations.append(operation)
        result = b.receipt(tool, role, operation, family)
        tool.data["receipts"][label] = result
        return result

    monkeypatch.setattr(tool, "step", step)
    tool.precompletion_prepare()
    assert operations == [
        "verification.preparation.record",
        "verification.request.create",
        "verification.method.prepare",
        "verification.actual_method.prepare",
    ]
    assert tool.data["phase"] == "actual_precompletion_formal_methods_no_handoff_or_link"
    assert not set(tool.data["receipts"]) & {
        "root-cause",
        "complete",
        "offer",
        "accept",
        "run-start",
    }


@pytest.mark.parametrize("bad", ["action", "completed", "effectiveness", "closed"])
def test_precompletion_requires_exact_current_open_capa_not_material_claims(tool, monkeypatch, bad):
    row = issue_row(tool)
    if bad == "action":
        row["issue"]["capa"]["actions"][0]["id"] = str(uuid4())
    elif bad == "completed":
        row["issue"]["capa"]["actions"][0]["completion"] = {"text": "saved"}
    elif bad == "effectiveness":
        row["issue"]["capa"]["effectiveness"] = {"result": "unknown"}
    else:
        row["issue"]["closure"] = {"text": "saved"}
    monkeypatch.setattr(tool, "current_issue", lambda: row)
    monkeypatch.setattr(tool, "publication", lambda: pytest.fail("No output operation"))
    with pytest.raises(m.Missing):
        tool.precompletion_prepare()


def combined_material():
    now = datetime.now(UTC)
    return {
        "root_text": "Already-observed synthetic investigation proposal",
        "completion_text": "Maker actually checked the original report; no physical claim",
        "occurred_at": (now - timedelta(seconds=5)).isoformat(),
        "original_timezone": "UTC",
        "valid_until": (now + timedelta(hours=1)).isoformat(),
        "offer_at": (now - timedelta(seconds=3)).isoformat(),
        "accept_at": (now - timedelta(seconds=2)).isoformat(),
    }


def test_five_line_memo_preserves_actual_typed_completion_and_handoff_without_extra_source(
    tool, monkeypatch, tmp_path
):
    import json

    from pdos_next.domain.quality_followup.schemas import CompletionFact
    from pdos_next.quality_followup_bootstrap import ClassificationFact

    tool.data["materials"]["remediation"] = combined_material()
    for label in ("preparation", "formal", "method", "actual-method"):
        tool.data["receipts"][label] = {"id": str(uuid4())}
    monkeypatch.setattr(tool, "current_issue", lambda: issue_row(tool))
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "COMPLETION_PROFILE", tmp_path / "new-profile.json")
    saved = []

    def step(label, role, operation, family, factory, **kwargs):
        payload, reads = factory()
        PAYLOADS[operation].model_validate(payload)
        saved.append((label, role, operation, deepcopy(payload)))
        return b.receipt(tool, role, operation, family)

    monkeypatch.setattr(tool, "step", step)
    tool.remediation_sources()
    lines = saved[0][3]["content"].splitlines()
    assert len(lines) == 5
    CompletionFact.model_validate_json(lines[1])
    ClassificationFact.model_validate_json(lines[2])
    for index, role in ((3, "maker"), (4, "observer")):
        row = json.loads(lines[index])
        assert set(row) == {
            "request_id",
            "sample_id",
            "purpose",
            "operation",
            "occurred_at",
            "actor_id",
        }
        assert row["actor_id"] == tool.actor(role)
        assert row["sample_id"] == tool.data["original_sample_id"]
    monkeypatch.setattr(tool, "completed", lambda: None)
    monkeypatch.setattr(tool, "publication", lambda: None)
    monkeypatch.setattr(tool, "_methods", lambda: None)
    sample = deepcopy(tool.data["sample_ref"])
    monkeypatch.setattr(
        tool,
        "current",
        lambda *a, **k: ({}, {"revision": 3, "required_source_read_set": tool.reads()}, None),
    )
    monkeypatch.setattr(tool, "selected", lambda view: (sample, tool.reads()))
    tool.handoff()
    assert [s[2] for s in saved] == [
        "evidence.artifact.register",
        "verification.handoff.offer",
        "verification.handoff.accept",
    ]
    assert [s[3]["sources"][-1]["line"] for s in saved[1:]] == [4, 5]
    assert len({s[3]["sources"][-1]["artifact_id"] for s in saved[1:]}) == 1


@pytest.mark.parametrize("bad", ["future", "clock-order", "missing-actual-method"])
def test_combined_memo_requires_observed_order_and_saved_preparation(tool, monkeypatch, bad):
    raw = combined_material()
    tool.data["materials"]["remediation"] = raw
    for label in ("preparation", "formal", "method", "actual-method"):
        tool.data["receipts"][label] = {"id": str(uuid4())}
    if bad == "future":
        raw["offer_at"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    elif bad == "clock-order":
        raw["accept_at"] = raw["occurred_at"]
    else:
        del tool.data["receipts"]["actual-method"]
    monkeypatch.setattr(tool, "current_issue", lambda: issue_row(tool))
    monkeypatch.setattr(tool, "step", lambda *a, **k: pytest.fail("No source publication"))
    with pytest.raises(m.Missing):
        tool.remediation_sources()


def native_workspace(tool, expected, *, publisher="observer", prefix="other publication line"):
    import json

    from pdos_next.service import digest

    lines = [prefix, *[tool.h.canonical(row) for row in expected]]
    content = "\n".join(lines)
    source = {
        "id": str(uuid4()),
        "revision": 1,
        "content": content,
        "content_hash": digest(content),
        "status": "active",
        "visibility": "product",
        "original_id": None,
    }
    refs = [
        b.ref(source["id"], line=number, quote=line) for number, line in enumerate(lines[1:], 2)
    ]
    registration = b.receipt(
        tool, publisher, "evidence.artifact.register", "artifact", source["id"]
    )
    assert all(json.loads(v["quote"]) == row for v, row in zip(refs, expected, strict=True))
    return refs, {"sources": [source], "receipts": [registration]}


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "missing-receipt",
        "wrong-publisher",
        "withdrawn",
        "private",
        "original",
        "hash",
        "line",
        "extra-field",
    ],
)
def test_existing_event_source_uses_actual_native_receipt_line_hash_and_audience(
    tool, monkeypatch, bad
):
    expected = {
        "operation": "explicit offline event substitute",
        "actor_id": tool.actor("observer"),
    }
    refs, workspace = native_workspace(tool, [expected])
    if bad == "missing-receipt":
        workspace["receipts"] = []
    elif bad == "wrong-publisher":
        workspace["receipts"][0]["writer_id"] = tool.actor("maker")
    elif bad == "withdrawn":
        workspace["sources"][0]["status"] = "withdrawn"
    elif bad == "private":
        workspace["sources"][0]["visibility"] = "private"
    elif bad == "original":
        workspace["sources"][0]["original_id"] = str(uuid4())
    elif bad == "hash":
        workspace["sources"][0]["content_hash"] = "a" * 64
    elif bad == "line":
        refs[0]["line"] = 1
    elif bad == "extra-field":
        expected = {**expected, "not-in-original": True}
    monkeypatch.setattr(tool, "get", lambda *a, **k: workspace)
    if bad is None:
        assert tool.native_events(refs, [expected], publisher="observer") == refs
        assert tool.data["selected_native_source_reads"] == [b.read(refs[0])]
    else:
        with pytest.raises(m.Missing):
            tool.native_events(refs, [expected], publisher="observer")
        assert "selected_native_source_reads" not in tool.data


def test_conclusions_reuse_observation_document_exact_lines_without_registering_another_source(
    tool, monkeypatch
):
    now = datetime.now(UTC)
    raw = {
        "review_text": "Actual review",
        "review_at": (now - timedelta(seconds=2)).isoformat(),
        "disposition_text": "Actual disposition",
        "disposition_at": (now - timedelta(seconds=1)).isoformat(),
    }
    rows = [
        {
            "request_id": tool.data["request_id"],
            "run_id": tool.data["run_id"],
            "purpose": tool.data["purpose"],
            "operation": operation,
            "actor_id": tool.actor("observer"),
            "occurred_at": raw[label + "_at"],
            "text": raw[label + "_text"],
            "basis_sha256": "a" * 64,
        }
        for label, operation in (
            ("review", "test.run.review"),
            ("disposition", "test.disposition.decide"),
        )
    ]
    refs, workspace = native_workspace(tool, rows)
    raw["event_sources"] = refs
    monkeypatch.setattr(tool, "get", lambda *a, **k: workspace)
    monkeypatch.setattr(tool, "current", lambda *a, **k: actual_conclusion_view(tool))
    monkeypatch.setattr(tool, "step", lambda *a, **k: pytest.fail("No extra event native"))
    outputs = tool.conclusion_events(raw)
    assert outputs["review"]["reference"] == refs[0]
    assert outputs["disposition"]["reference"] == refs[1]


@pytest.mark.parametrize("bad", ["before-completion", "missing-completion"])
def test_second_start_requires_saved_completion_and_actual_clock(tool, monkeypatch, bad):
    row = issue_row(tool, status="awaiting_verification")
    at = datetime.now(UTC) - timedelta(seconds=2)
    row["issue"]["root_cause"] = {"text": "actual named substitute"}
    if bad != "missing-completion":
        row["issue"]["capa"]["actions"][0]["completion"] = {"at": {"occurred_at": at.isoformat()}}
    monkeypatch.setattr(tool, "current_issue", lambda: row)
    monkeypatch.setattr(m.first.SharedTest, "start", lambda *a, **k: pytest.fail("No Start"))
    with pytest.raises(m.Missing):
        tool.start(occurred_at=(at - timedelta(seconds=1)).isoformat())


FRESH_GENERATION = "37c270ad-521a-44ad-b186-3447a94906c1"


def saved_fresh_result(tool):
    """Actual fresh writer/readback schema, with explicit no-IO row substitutes."""
    raw = saved_first_result(tool)
    old_run = raw["run_id"]
    raw.pop("prospective_generation")
    run = str(m.uuid5(m.UUID(FRESH_GENERATION), "fresh:run"))
    raw.update(
        schema_version="wave22-shared-fresh-request-v1",
        generation=FRESH_GENERATION,
        case_id=FRESH_GENERATION,
        foundation_sha256="a" * 64,
        build_sha256="b" * 64,
        selection={
            "schema_version": "wave22-fresh-request-intent-v1",
            "generation": FRESH_GENERATION,
            "marker": tool.marker,
            "scope": tool.foundation["scope"],
            "purpose": tool.data["purpose"],
            "build_id": tool.data["build_id"],
            "sample_id": raw["original_sample_id"],
            "source_generation": tool.first_generation,
            "source_checkpoint_sha256": "c" * 64,
            "source_resource_profile_sha256": "d" * 64,
            "source_resource_input_sha256": "e" * 64,
            "readback_file": "evidence/substitute-proof.json",
            "readback_sha256": "f" * 64,
            "decision_file": "evidence/substitute-decision.json",
            "decision_sha256": "9" * 64,
            "reason": "Explicit fresh branch; old saved Plan remains historical",
        },
        origin_archive={"run_id": old_run, "prospective_generation": {"id": tool.first_generation}},
        run_id=run,
    )
    raw["result_readback"]["run_id"] = run
    return raw


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", str(uuid4()).upper()])
def test_explicit_fresh_selector_never_falls_back_to_first_checkpoint(bad):
    with pytest.raises((m.Missing, ValueError)):
        m.selected_source(fresh_generation=bad)


@pytest.mark.parametrize(
    "first_selected,fresh_selected", [(None, None), (FRESH_GENERATION, FRESH_GENERATION)]
)
def test_source_selection_rejects_missing_or_both_before_any_owner_or_target(
    monkeypatch, first_selected, fresh_selected
):
    monkeypatch.setattr(
        m, "fresh_module", lambda: pytest.fail("No owner import on ambiguous source")
    )
    monkeypatch.setattr(m, "selected_first_paths", lambda *a: pytest.fail("No fallback source"))
    with pytest.raises(m.Missing, match="Exactly one"):
        m.selected_source(first_generation=first_selected, fresh_generation=fresh_selected)
    with pytest.raises(m.Missing, match="Exactly one"):
        m.SharedRetest(
            "substitute", first_generation=first_selected, fresh_generation=fresh_selected
        )


def test_fresh_selector_uses_actual_frozen_helper_paths_and_inert_import(monkeypatch):
    helper = m.fresh_module()
    monkeypatch.setattr(
        helper.SharedFreshRequest, "__init__", lambda *a, **k: pytest.fail("No live constructor")
    )
    monkeypatch.setattr(m, "fresh_module", lambda: helper)
    monkeypatch.setattr(m, "selected_first_paths", lambda *a: pytest.fail("No old path fallback"))
    mode, generation, paths, selected = m.selected_source(fresh_generation=FRESH_GENERATION)
    assert mode == "fresh" and generation == FRESH_GENERATION and selected is helper
    assert paths == helper.fresh_paths(FRESH_GENERATION)
    assert paths[0] == m.ROOT / f".local/wave22-shared-test-fresh-{FRESH_GENERATION}.json"
    assert paths[0] != m.first.CHECKPOINT
    assert paths[0] != m.first.generation_paths(FRESH_GENERATION)[0]
    assert all(FRESH_GENERATION in path.name for path in paths)
    assert helper.FIRST_SOURCE_SHA == m.FIRST_SOURCE_SHA


def test_old_selector_does_not_load_or_infer_fresh_source(tool, monkeypatch):
    monkeypatch.setattr(
        m, "fresh_module", lambda: pytest.fail("Old explicit mode does not load fresh")
    )
    mode, generation, paths, helper = m.selected_source(first_generation=tool.first_generation)
    assert mode == "first" and generation == tool.first_generation and helper is None
    assert paths == m.selected_first_paths(tool.first_generation)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "schema",
        "generation",
        "case",
        "selection-generation",
        "selection-scope",
        "selection-purpose",
        "selection-build",
        "selection-sample",
        "missing-archive",
        "same-archived-run",
        "old-run-label",
        "planned",
        "promised",
        "missing-start",
        "missing-import",
        "missing-compute",
        "indeterminate",
        "projection",
        "report-hash",
        "bool-revision",
    ],
)
def test_fresh_result_requires_actual_new_branch_complete_fail_before_followup(tool, bad):
    raw = saved_fresh_result(tool)
    if bad == "schema":
        raw["schema_version"] = "wave22-shared-test-v1"
    elif bad in {"generation", "case"}:
        raw["generation" if bad == "generation" else "case_id"] = str(uuid4())
    elif bad and bad.startswith("selection-"):
        key = bad.removeprefix("selection-")
        key = {"build": "build_id", "sample": "sample_id"}.get(key, key)
        raw["selection"][key] = {} if key == "scope" else "different"
    elif bad == "missing-archive":
        raw.pop("origin_archive")
    elif bad == "same-archived-run":
        raw["origin_archive"]["run_id"] = raw["run_id"]
    elif bad == "old-run-label":
        raw["run_id"] = str(m.uuid5(m.UUID(FRESH_GENERATION), "original:run"))
        raw["result_readback"]["run_id"] = raw["run_id"]
    elif bad in {"planned", "promised"}:
        raw["phase"] = (
            "actual_original_plan_saved_no_start"
            if bad == "planned"
            else "actual_original_promised_no_start"
        )
    elif bad in {"missing-start", "missing-import", "missing-compute"}:
        raw["receipts"].pop(
            {
                "missing-start": "run-start",
                "missing-import": "results",
                "missing-compute": "compute",
            }[bad]
        )
    elif bad == "indeterminate":
        raw["result_readback"]["result"] = "indeterminate"
        raw["result_readback"]["projection"]["result"] = "indeterminate"
    elif bad == "projection":
        raw["result_readback"]["projection"]["id"] = str(uuid4())
    elif bad == "report-hash":
        raw["result_readback"]["report_sha256"] = "different"
    elif bad == "bool-revision":
        raw["result_readback"]["request_revision"] = True
    if bad is None:
        assert (
            m.first_contract(
                raw, tool.foundation, tool.build, generation=FRESH_GENERATION, source_mode="fresh"
            )
            is raw
        )
    else:
        with pytest.raises(m.Missing):
            m.first_contract(
                raw, tool.foundation, tool.build, generation=FRESH_GENERATION, source_mode="fresh"
            )


def test_explicit_modes_do_not_accept_other_schema_even_when_run_and_fail_look_plausible(tool):
    with pytest.raises(m.Missing):
        m.first_contract(
            saved_fresh_result(tool), tool.foundation, tool.build, generation=FRESH_GENERATION
        )
    with pytest.raises(m.Missing):
        m.first_contract(
            saved_first_result(tool),
            tool.foundation,
            tool.build,
            generation=tool.first_generation,
            source_mode="fresh",
        )
    with pytest.raises(m.Missing):
        m.first_contract(
            saved_first_result(tool),
            tool.foundation,
            tool.build,
            generation=tool.first_generation,
            source_mode="infer",
        )


def test_fresh_origin_uses_actual_owner_guard_with_saved_archive_not_new_target(tool, monkeypatch):
    helper = m.fresh_module()
    raw = saved_fresh_result(tool)
    calls = []
    expected_paths = helper.first.generation_paths(raw["selection"]["source_generation"])

    def actual_guard(owner):
        # The only bound object is a readonly saved-origin reader. It cannot be
        # the live new fresh object or masquerade as the old FirstRun schema.
        assert owner.selection is raw["selection"]
        assert owner.first_data is raw["origin_archive"]
        assert (
            owner.first_checkpoint,
            owner.first_profile_path,
            owner.first_resource_input_path,
        ) == expected_paths
        assert owner.foundation_sha == raw["foundation_sha256"]
        assert owner.build_sha == raw["build_sha256"]
        assert not hasattr(owner, "data") and not hasattr(owner, "h")
        calls.append(owner)

    monkeypatch.setattr(
        helper.SharedFreshRequest, "__init__", lambda *a, **k: pytest.fail("No actual constructor")
    )
    monkeypatch.setattr(helper.SharedFreshRequest, "origin_guard", actual_guard)
    monkeypatch.setattr(
        m.first.SharedTest, "_origin_files", lambda *a: pytest.fail("Wrong schema owner")
    )
    m.read_selected_origin(raw, source_mode="fresh", fresh_helper=helper)
    assert len(calls) == 1


def test_fresh_origin_actual_guard_failure_propagates_without_fallback(tool, monkeypatch):
    helper = m.fresh_module()
    monkeypatch.setattr(
        helper.SharedFreshRequest,
        "origin_guard",
        lambda *a: (_ for _ in ()).throw(helper.Missing("Actual old archive/Root proof changed")),
    )
    monkeypatch.setattr(m.first.SharedTest, "_origin_files", lambda *a: pytest.fail("No fallback"))
    with pytest.raises(helper.Missing, match="changed"):
        m.read_selected_origin(saved_fresh_result(tool), source_mode="fresh", fresh_helper=helper)


def test_fresh_origin_missing_exact_owner_helper_is_rejected(tool):
    with pytest.raises(m.Missing):
        m.read_selected_origin(saved_fresh_result(tool), source_mode="fresh")


@pytest.mark.parametrize(
    "arguments",
    [[], ["--first-generation", FRESH_GENERATION, "--fresh-generation", FRESH_GENERATION]],
)
def test_cli_requires_exclusive_source_before_live_tool_construction(monkeypatch, arguments):
    monkeypatch.setattr(
        sys, "argv", ["wave22_shared_retest.py", "quality", "--marker", "substitute", *arguments]
    )
    monkeypatch.setattr(m, "SharedRetest", lambda *a, **k: pytest.fail("No target construction"))
    with pytest.raises(SystemExit) as error:
        m.main()
    assert error.value.code == 2


@pytest.mark.parametrize("flag", ["--first-generation", "--fresh-generation"])
def test_cli_forwards_only_selected_explicit_source(monkeypatch, capsys, flag):
    from types import SimpleNamespace

    calls = []

    class InertTool(SimpleNamespace):
        def __getattr__(self, key):
            return lambda **kwargs: {"phase": "explicit_substitute", "target_io": False}

    def construct(marker, **kwargs):
        calls.append((marker, kwargs))
        return InertTool(data={"phase": "substitute", "receipts": {}})

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "wave22_shared_retest.py",
            "source-budget",
            "--marker",
            "substitute",
            flag,
            FRESH_GENERATION,
        ],
    )
    monkeypatch.setattr(m, "SharedRetest", construct)
    assert m.main() == 0
    assert len(calls) == 1
    assert (
        calls[0][1]["fresh_generation" if flag == "--fresh-generation" else "first_generation"]
        == FRESH_GENERATION
    )
    assert (
        calls[0][1]["first_generation" if flag == "--fresh-generation" else "fresh_generation"]
        is None
    )
    assert '"target_io": false' in capsys.readouterr().out


def test_fresh_complete_fail_constructor_binds_selected_paths_and_new_namespace(
    tool, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    raw = saved_fresh_result(tool)
    raw.update(
        request_id=str(uuid4()),
        test_equipment_id=str(uuid4()),
        test_publication={"source": "explicit-substitute"},
        publication_receipt={"id": str(uuid4())},
    )
    resource_input = {"binding": {"run_id": raw["run_id"]}, "resources": []}
    raw["resource_input"] = resource_input
    normalized = m.first.build_foundation_binding(tool.foundation, tool.marker)
    build_raw = {
        "schema_version": "wave22-shared-build-v1",
        "phase": "two_A_readiness_facts_saved_no_handoff_or_test_run",
        "marker": tool.marker,
        "foundation_sha256": normalized,
        "case_id": str(uuid4()),
        "continuation": tool.build,
    }
    paths = tuple(
        tmp_path / name for name in ("fresh.json", "fresh-profile.json", "fresh-input.json")
    )
    profile = {"decisions": []}  # Explicit empty no-IO substitute, not actual trusted publication.
    selected_owner = SimpleNamespace(fresh_paths=lambda g: paths)
    calls = []
    monkeypatch.setattr(m, "fresh_module", lambda: selected_owner)
    monkeypatch.setattr(m, "CHECKPOINT", tmp_path / "new-retest.json")
    monkeypatch.setattr(
        m.SharedRetest, "target", lambda self: {"preview_tenant_id": tool.foundation["tenant_id"]}
    )
    monkeypatch.setattr(m.first, "digest_file", lambda path: "a" * 64)
    values = {
        m.first.FOUNDATION: tool.foundation,
        m.first.BUILD: build_raw,
        paths[0]: raw,
        paths[1]: profile,
        paths[2]: resource_input,
    }
    monkeypatch.setattr(m.first, "private_json", lambda path, **kwargs: deepcopy(values[path]))
    monkeypatch.setattr(
        m, "read_selected_origin", lambda data, **kwargs: calls.append((deepcopy(data), kwargs))
    )
    monkeypatch.setattr(m.SharedRetest, "save", lambda self: calls.append("saved-new-substitute"))
    second = m.SharedRetest(tool.marker, fresh_generation=FRESH_GENERATION)
    assert calls[0][1] == {"source_mode": "fresh", "fresh_helper": selected_owner}
    assert calls[1:] == ["saved-new-substitute"]
    assert second.first_checkpoint == paths[0]
    assert second.first_profile_path == paths[1]
    assert second.first_resource_input_path == paths[2]
    assert second.data["schema_version"] == "wave22-shared-retest-v3"
    assert second.data["source_mode"] == "fresh"
    assert second.data["fresh_generation"] == FRESH_GENERATION
    assert second.data["first_generation"] is None
    assert second.data["fresh_source_sha256"] == m.FRESH_SOURCE_SHA
    assert second.data["first_source_sha256"] == m.FIRST_SOURCE_SHA
    assert second.namespace == str(m.uuid5(m.UUID(FRESH_GENERATION), "shared-followup-second-run"))
    assert second.data["first_run_id"] == raw["run_id"]
    assert second.data["original_sample_id"] == raw["followup_sample_id"]
    assert second.data["requests"] == {} and second.data["receipts"] == {}
    assert second.data["phase"] == "allocated_no_issue_or_second_run"
    assert not m.CHECKPOINT.exists()


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
