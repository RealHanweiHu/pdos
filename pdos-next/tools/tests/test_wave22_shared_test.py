"""Owned offline driver checks; no connection or real qualification is asserted."""

import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Engine


def owned_source(test_file):
    selected = Path(test_file).parent
    if selected.name == "wave22-test-staged" and selected.parent.name == ".local":
        return selected / "wave22_shared_test.py"
    if (
        selected.name in {"v2", "v3", "v4"}
        and selected.parent.name == "wave22-test-staged"
        and selected.parent.parent.name == ".local"
    ):
        return selected / "wave22_shared_test.py"
    if selected.name == "tests" and selected.parent.name == "tools":
        return selected.parent / "wave22_shared_test.py"
    raise RuntimeError("Unexpected owned test layout")


SOURCE = owned_source(Path(__file__).resolve())
spec = importlib.util.spec_from_file_location("wave22_owned_test_tool", SOURCE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
sys.path.insert(0, str(m.ROOT / "server"))
sys.path.insert(0, str(m.ROOT / "tools"))

from pdos_next.contracts import PAYLOADS  # noqa: E402
from pdos_next.domain.test_resources.schemas import (  # noqa: E402
    TestPlanBinding as PlanBinding,
)
from pdos_next.domain.test_resources.schemas import (  # noqa: E402
    TestResourceFactInput as ResourceFactInput,
)
from pdos_next.service import digest  # noqa: E402


def uid():
    return str(uuid4())


def read(ref):
    return {"artifact_id": ref["artifact_id"], "expected_revision": ref["expected_revision"]}


def ref(identity=None, line=1, quote="Explicit offline published source substitute"):
    return {"artifact_id": identity or uid(), "expected_revision": 1, "line": line, "quote": quote}


def receipt(tool, role, operation, family, subject=None):
    subject = subject or uid()
    return {
        "id": uid(),
        "operation": operation,
        "subject_type": family,
        "subject_id": subject,
        "subject_revision": 1,
        "writer_id": tool.actor(role),
        "requester_id": tool.actor(role),
        "result": {"id": subject, "revision": 1},
    }


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("External IO forbidden in owned pure check")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(m.SharedTest, "target", forbidden)
    monkeypatch.setattr(m.SharedTest, "resource_binding", forbidden)


@pytest.fixture
def tool(monkeypatch):
    value = m.SharedTest.__new__(m.SharedTest)
    value.h = m.helpers()
    value.marker = uid()
    value.confirm = value.review_digest = value.recover = None
    value.confirm_used = value.recover_used = False
    actors = {role: {"id": uid(), "login_token": "FAKE_NOT_A_LOGIN_TOKEN"} for role in m.ROLES}
    scope = {key: uid() for key in ("tenant_id", "product_id", "project_id")}
    native = ref(
        quote=(
            "Requirement\nDimension 9.5..10.5 mm, 23 C, dry\nFixed method\nBOM\nUnknown completion"
        )
    )
    value.foundation = {
        "schema_version": "wave21-shared-foundation-v1",
        "marker": value.marker,
        "phase": "foundation_saved_not_build_started",
        "visibility": "product",
        "actors": actors,
        **scope,
        "scope": scope,
        "case_id": uid(),
        "purpose": "Explicit shared synthetic investigation",
        "configuration": {
            key: uid() if key.endswith("id") else 1
            for key in (
                "bom_id",
                "bom_revision",
                "engineering_id",
                "engineering_revision",
                "manufacturing_id",
                "manufacturing_revision",
            )
        },
        "bootstrap_expires_at": (datetime.now(UTC) + timedelta(hours=10)).isoformat(),
        "sources": {
            "foundation": {
                "reference": {**native, "quote": "Requirement"},
                "required_source_read_set": [read(native)],
            }
        },
        "requests": {"native-source": {"original": {"payload": {"content": native["quote"]}}}},
        "receipts": {},
        "readback": {
            role: {
                "shared_objects": 6,
                "stored_content_hash": "a" * 64,
                "raw_text_sha256": "b" * 64,
            }
            for role in m.ROLES
        },
    }
    for label, family in (
        ("product", "product"),
        ("native-source", "artifact"),
        ("definition", "definition_revision"),
        ("project", "project"),
        ("bom", "bom_revision"),
        ("engineering", "engineering_configuration"),
        ("manufacturing", "process_revision"),
    ):
        subject = (
            native["artifact_id"]
            if label == "native-source"
            else scope["project_id"]
            if label == "project"
            else value.foundation["configuration"][label + "_id"]
            if label in {"bom", "engineering", "manufacturing"}
            else None
        )
        value.foundation["receipts"][label] = receipt(
            value,
            "maker",
            "fake.offline",
            family,
            subject,
        )
    build_id = uid()
    actual_id = uid()
    value.build = {
        "scope": scope,
        "purpose": value.foundation["purpose"],
        "maker_id": actors["maker"]["id"],
        "schema_version": "wave22-shared-build-continuation-v1",
        "state": "readback_saved_requires_consumer_recheck",
        "configuration": value.foundation["configuration"],
        "synthetic_only": True,
        "test_qualification": None,
        "professional_review": None,
        "effectiveness": None,
        "close": False,
        "build": {"id": build_id, "revision": 1},
        "required_source_read_set": [read(ref())],
        "samples": [
            {
                "id": uid(),
                "revision": 1,
                "cavity": "A",
                "build_id": build_id,
                "actual_configuration_id": actual_id,
                "actual_configuration_revision": 1,
                "purpose_availability": "ready",
                "readiness": {"id": uid(), "revision": 1},
            }
            for _ in range(2)
        ],
    }
    sample = value.build["samples"][0]
    value.data = {
        "requests": {},
        "receipts": {},
        "events": {},
        "scope": scope,
        "purpose": value.foundation["purpose"],
        "build_id": build_id,
        "request_id": uid(),
        "preparation_request_id": uid(),
        "run_id": uid(),
        "test_equipment_id": uid(),
        "original_sample_id": sample["id"],
        "followup_sample_id": value.build["samples"][1]["id"],
        "phase": "allocated_not_run",
        "sample_ref": {
            "id": sample["id"],
            "revision": 1,
            "build_id": build_id,
            "cavity": "A",
            "actual_configuration": {"id": actual_id, "revision": 1},
        },
        "coverage": [{"sample_id": sample["id"], "item_id": "dimension"}],
    }
    publication = ref(quote="Named synthetic method and physical resource declarations")
    value.data["test_publication"] = {
        "schema_version": "wave22-shared-test-publication-v1",
        "scope": scope,
        "purpose": value.data["purpose"],
        "publisher_role": "maker",
        "method": {
            "status": "applicable",
            "conditions": [],
            "reason": "Explicit synthetic named method",
        },
        "actual_method": {
            "status": "applicable",
            "conditions": [],
            "reason": "Explicit actual pair method",
        },
        **{
            key: publication
            for key in ("method_source", "actual_method_source", "equipment", "calibration")
        },
        "requirements_sources": [publication],
        "resource_sources": [publication],
        "environment": "Synthetic internal lab",
        "conditions": "23 C, dry",
    }
    value.calls = []
    value.live_revision = 1
    monkeypatch.setattr(value, "save", lambda: None)
    monkeypatch.setattr(
        value,
        "get",
        lambda family, role="observer": {
            "product": {"id": value.product, "revision": value.live_revision}
        },
    )
    return value


def method_payload(tool):
    return {
        "request_id": tool.data["request_id"],
        "expected_request_revision": 2,
        "assessments": [
            {
                "item_id": "dimension",
                **tool.published("method"),
                "sources": [tool.published("method_source")],
            }
        ],
        "reason": "Explicit offline choice",
    }, tool.reads()


def install_fake_common(tool, monkeypatch, family="verification_request"):
    def send(role, method, path, *, body=None, params=None):
        assert method == "POST"
        tool.calls.append((path, deepcopy(body)))
        if path == "/v1/commands/preview":
            prepared = deepcopy(body)
            prepared["payload"]["confirmation_token"] = "t" * 30
            return {
                "command": prepared,
                "review": {"before": None, "after": {"fixed": True}},
                "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
            }
        assert path == "/v1/commands"
        return receipt(tool, role, body["operation"], family)

    monkeypatch.setattr(tool, "request", send)


def prepare_method(tool, monkeypatch):
    install_fake_common(tool, monkeypatch)
    with pytest.raises(m.Pending):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
        )
    return tool.data["requests"]["method"]


@pytest.mark.parametrize("layout", ["stage", "stage_v2", "stage_v3", "real"])
def test_two_explicit_source_and_test_layouts(layout):
    path = (
        Path("/tmp/pdos-next/.local/wave22-test-staged/wave22_shared_test.py")
        if layout == "stage"
        else Path("/tmp/pdos-next/.local/wave22-test-staged/v2/wave22_shared_test.py")
        if layout == "stage_v2"
        else Path("/tmp/pdos-next/.local/wave22-test-staged/v3/wave22_shared_test.py")
        if layout == "stage_v3"
        else Path("/tmp/pdos-next/tools/wave22_shared_test.py")
    )
    assert m.layout_root(path) == Path("/tmp/pdos-next")
    test = (
        path.parent / "test_wave22_shared_test.py"
        if layout in {"stage", "stage_v2", "stage_v3"}
        else path.parent / "tests/test_wave22_shared_test.py"
    )
    assert owned_source(test) == path


@pytest.mark.parametrize(
    "bad", ["2026-10-01T00:00:00", "2026-10-01T00:00:00+08:00", "2999-01-01T00:00:00Z", None]
)
def test_actual_clock_not_naive_future_or_substituted_timezone(bad):
    with pytest.raises(m.Missing):
        m.aware_past(bad)


def test_foundation_and_actual_two_sample_contract(tool):
    assert m.foundation_contract(tool.foundation, tool.marker) is tool.foundation
    wrapper = {
        "schema_version": "wave22-shared-build-v1",
        "phase": "two_A_readiness_facts_saved_no_handoff_or_test_run",
        "foundation_sha256": "a" * 64,
        "marker": tool.marker,
        "case_id": uid(),
        "continuation": tool.build,
    }
    assert m.build_contract(wrapper, tool.foundation, "a" * 64) is tool.build
    assert tool.data["original_sample_id"] != tool.data["followup_sample_id"]


@pytest.mark.parametrize("bad", ["private", "nonfinal", "notready", "same_sample"])
def test_no_old_private_or_unverified_build_reuse(tool, bad):
    if bad == "private":
        tool.foundation["visibility"] = "private"
        with pytest.raises(m.Missing):
            m.foundation_contract(tool.foundation, tool.marker)
    else:
        if bad == "nonfinal":
            tool.build["state"] = "planned"
        elif bad == "notready":
            tool.build["samples"][0]["purpose_availability"] = "unknown"
        else:
            tool.build["samples"][1]["id"] = tool.build["samples"][0]["id"]
        wrapper = {
            "schema_version": "wave22-shared-build-v1",
            "phase": "two_A_readiness_facts_saved_no_handoff_or_test_run",
            "foundation_sha256": "a" * 64,
            "marker": tool.marker,
            "case_id": uid(),
            "continuation": tool.build,
        }
        with pytest.raises(m.Missing):
            m.build_contract(wrapper, tool.foundation, "a" * 64)


def test_real_build_binding_uses_normalized_foundation_not_file_digest(tool, tmp_path):
    normalized = m.build_foundation_binding(tool.foundation, tool.marker)
    raw_path = tmp_path / "foundation.json"
    raw_path.write_text(json.dumps(tool.foundation, indent=2))
    raw_sha = m.digest_file(raw_path)
    assert normalized != raw_sha
    wrapper = {
        "schema_version": "wave22-shared-build-v1",
        "phase": "two_A_readiness_facts_saved_no_handoff_or_test_run",
        "marker": tool.marker,
        "foundation_sha256": normalized,
        "case_id": uid(),
        "continuation": tool.build,
    }
    assert wrapper["case_id"] != tool.foundation["case_id"]
    assert m.build_contract(wrapper, tool.foundation, normalized) is tool.build
    with pytest.raises(m.Missing):
        m.build_contract(wrapper, tool.foundation, raw_sha)
    with pytest.raises(m.Missing):
        m.build_contract({**wrapper, "foundation_sha256": raw_sha}, tool.foundation, normalized)
    # Credentials/file formatting affect the private-file SHA, never the owner's business basis.
    edited = deepcopy(tool.foundation)
    edited["actors"]["maker"]["login_token"] = "OTHER_FAKE_CREDENTIAL_NOT_AUTHORIZATION"
    assert m.build_foundation_binding(edited, tool.marker) == normalized
    edited["configuration"]["bom_revision"] = 2
    with pytest.raises(RuntimeError):
        m.build_foundation_binding(edited, tool.marker)


@pytest.mark.parametrize("tamper", [None, "case", "normalized", "foundation_raw", "build_raw"])
def test_constructor_keeps_raw_files_and_independent_build_case_bound(
    tool, monkeypatch, tmp_path, tamper
):
    normalized = m.build_foundation_binding(tool.foundation, tool.marker)
    wrapper = {
        "schema_version": "wave22-shared-build-v1",
        "phase": "two_A_readiness_facts_saved_no_handoff_or_test_run",
        "marker": tool.marker,
        "foundation_sha256": normalized,
        "case_id": uid(),
        "continuation": tool.build,
    }
    checkpoint = tmp_path / "saved.json"
    monkeypatch.setattr(m, "CHECKPOINT", checkpoint)
    monkeypatch.setattr(
        m.SharedTest, "target", lambda self: {"preview_tenant_id": tool.foundation["tenant_id"]}
    )
    monkeypatch.setattr(m.SharedTest, "save", lambda self: None)
    monkeypatch.setattr(
        m,
        "private_json",
        lambda path: deepcopy(
            tool.foundation if path == m.FOUNDATION else wrapper if path == m.BUILD else saved
        ),
    )
    monkeypatch.setattr(
        m, "digest_file", lambda path: "a" * 64 if path == m.FOUNDATION else "b" * 64
    )
    fresh = m.SharedTest(tool.marker)
    assert fresh.data["foundation_sha256"] == "a" * 64
    assert fresh.data["build_sha256"] == "b" * 64
    assert fresh.data["build_foundation_sha256"] == normalized
    assert fresh.data["build_case_id"] == wrapper["case_id"]
    assert fresh.data["build_case_id"] != fresh.data["case_id"]
    saved = deepcopy(fresh.data)
    checkpoint.write_text("explicit offline saved substitute")
    if tamper == "case":
        saved["build_case_id"] = tool.foundation["case_id"]
    elif tamper == "normalized":
        saved["build_foundation_sha256"] = "a" * 64
    elif tamper == "foundation_raw":
        saved["foundation_sha256"] = normalized
    elif tamper == "build_raw":
        saved["build_sha256"] = normalized
    if tamper is None:
        restored = m.SharedTest(tool.marker)
        assert restored.data == saved
    else:
        with pytest.raises(m.Missing):
            m.SharedTest(tool.marker)


def test_reader_never_borrows_independent_reviewer(tool):
    with pytest.raises(m.Missing):
        tool.actor("independent_reviewer")


def test_complete_readset_twenty_limit_and_conflict_are_not_truncated(tool):
    existing = tool.reads()
    unique = [read(ref()) for _ in range(20 - len(existing))]
    assert len(tool.reads(unique)) == 20
    with pytest.raises(RuntimeError):
        tool.reads([*unique, read(ref())])
    with pytest.raises(RuntimeError):
        tool.reads([{**existing[0], "expected_revision": 2}])


def test_first_preview_does_not_submit_and_exact_confirm_only_once(tool, monkeypatch):
    prepared = prepare_method(tool, monkeypatch)
    assert [p for p, _ in tool.calls] == ["/v1/commands/preview"]
    tool.confirm, tool.review_digest = "method", prepared["review_digest"]
    value = tool.step(
        "method",
        "observer",
        "verification.method.prepare",
        "verification_request",
        lambda: pytest.fail("Saved original must precede dynamic factory"),
    )
    assert value["id"] == tool.data["receipts"]["method"]["id"]
    assert tool.confirm_used is True
    assert [p for p, _ in tool.calls] == ["/v1/commands/preview", "/v1/commands"]
    assert tool.calls[1][1] == prepared["body"]


@pytest.mark.parametrize("field", ["label", "digest"])
def test_wrong_confirmation_cannot_send(tool, monkeypatch, field):
    prepared = prepare_method(tool, monkeypatch)
    tool.confirm = "wrong" if field == "label" else "method"
    tool.review_digest = "f" * 64 if field == "digest" else prepared["review_digest"]
    with pytest.raises(m.Pending):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
        )
    assert len(tool.calls) == 1


def test_saved_receipt_and_unknown_original_precede_live_product_revision(tool, monkeypatch):
    prepared = prepare_method(tool, monkeypatch)
    original = deepcopy(prepared["body"])
    tool.confirm, tool.review_digest = "method", prepared["review_digest"]

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Explicit offline transport timeout")

    monkeypatch.setattr(tool, "request", timeout)
    with pytest.raises(m.Unknown):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
        )
    assert prepared["state"] == "unknown"
    tool.live_revision = 99
    install_fake_common(tool, monkeypatch)
    tool.recover = "method"
    value = tool.step(
        "method",
        "observer",
        "verification.method.prepare",
        "verification_request",
        lambda: pytest.fail("No material rebuild on recovery"),
    )
    assert tool.calls[-1] == ("/v1/commands", original)
    monkeypatch.setattr(
        tool, "get", lambda *args, **kwargs: pytest.fail("Saved Receipt must precede GET")
    )
    assert (
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: pytest.fail("Saved Receipt must precede factory"),
        )
        == value
    )


@pytest.mark.parametrize("field", ["actor", "operation", "key", "payload", "token"])
def test_saved_prepared_request_changes_fail_before_send(tool, monkeypatch, field):
    prepared = prepare_method(tool, monkeypatch)
    if field == "actor":
        prepared["actor_id"] = tool.actor("maker")
    elif field == "operation":
        prepared["original"]["operation"] = "verification.request.create"
    elif field == "key":
        prepared["original"]["idempotency_key"] += "different"
    elif field == "payload":
        prepared["body"]["payload"]["reason"] = "Changed material"
    else:
        prepared["body"]["payload"]["confirmation_token"] = "x" * 30
    with pytest.raises(m.Missing):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
        )
    assert len(tool.calls) == 1


def test_future_preview_and_domain_failures_are_not_rekeyed(tool, monkeypatch):
    prepared = prepare_method(tool, monkeypatch)
    prepared["state"] = "preview_unknown"
    with pytest.raises(m.Missing):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
        )
    prepared["state"] = "rejected"
    with pytest.raises(m.Missing):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
        )
    assert len(tool.calls) == 1


def publication_view(tool):
    pub = tool.data["test_publication"]
    reference = pub["method_source"]
    return {
        "sources": [
            {
                "id": reference["artifact_id"],
                "revision": 1,
                "status": "active",
                "visibility": "product",
                "original_id": None,
                "content": reference["quote"],
                "content_hash": digest(reference["quote"]),
            }
        ],
        "receipts": [
            receipt(
                tool, "maker", "evidence.artifact.register", "artifact", reference["artifact_id"]
            )
        ],
    }


def test_actual_shared_native_publication_not_foundation_banner(tool, monkeypatch):
    monkeypatch.setattr(tool, "get", lambda *args, **kwargs: publication_view(tool))
    tool.publication()
    assert (
        tool.data["publication_receipt"]["subject_id"] == tool.published("equipment")["artifact_id"]
    )
    assert tool.published("equipment")["artifact_id"] != tool.ref()["artifact_id"]


@pytest.mark.parametrize(
    "bad", ["private", "withdrawn", "hash", "quote", "receipt", "other_actor", "unconsolidated"]
)
def test_publication_scope_hash_exact_provenance_no_positive_substitute(tool, monkeypatch, bad):
    view = publication_view(tool)
    if bad == "private":
        view["sources"][0]["visibility"] = "private"
    elif bad == "withdrawn":
        view["sources"][0]["status"] = "withdrawn"
    elif bad == "hash":
        view["sources"][0]["content_hash"] = "0" * 64
    elif bad == "quote":
        view["sources"][0]["content"] += "changed"
        view["sources"][0]["content_hash"] = digest(view["sources"][0]["content"])
    elif bad == "receipt":
        view["receipts"] = []
    elif bad == "other_actor":
        view["receipts"][0]["requester_id"] = tool.actor("observer")
    else:
        tool.data["test_publication"]["equipment"] = ref()
    monkeypatch.setattr(tool, "get", lambda *args, **kwargs: view)
    with pytest.raises(m.Missing):
        tool.publication()


def test_two_observed_events_one_whole_native_source_and_no_rewrite(tool, monkeypatch):
    records = []

    def register(label, role, op, family, factory, **kwargs):
        raw, _ = factory()
        PAYLOADS[op].model_validate(raw)
        records.append(raw)
        return receipt(tool, role, op, family)

    monkeypatch.setattr(tool, "step", register)
    first = (datetime.now(UTC) - timedelta(seconds=3)).isoformat()
    last = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    entries = (
        ("end", "observer", "test.run.end", first),
        ("results", "observer", "test.results.import", last),
    )
    values = tool.event_batch("return", entries, publisher="observer")
    assert len(records) == 1
    assert len(records[0]["content"].splitlines()) == 2
    assert (
        values["end"]["reference"]["artifact_id"] == values["results"]["reference"]["artifact_id"]
    )
    assert values["end"]["reference"]["line"] == 1
    assert values["results"]["reference"]["line"] == 2
    for line in records[0]["content"].splitlines():
        assert set(json.loads(line)) == {
            "request_id",
            "run_id",
            "purpose",
            "operation",
            "occurred_at",
            "actor_id",
        }
    with pytest.raises(m.Missing):
        tool.event_batch("return", (entries[0], (*entries[1][:3], first)), publisher="observer")


def test_event_pair_rejects_future_before_any_registration(tool, monkeypatch):
    monkeypatch.setattr(tool, "step", lambda *args, **kwargs: pytest.fail("No future publication"))
    with pytest.raises(m.Missing):
        tool.event_batch(
            "handoff",
            (
                ("offer", "maker", "verification.handoff.offer", datetime.now(UTC).isoformat()),
                ("accept", "observer", "verification.handoff.accept", "2999-01-01T00:00:00Z"),
            ),
            publisher="maker",
        )
    assert "handoff" not in tool.data["events"]


def actual_formal(tool, revision=2):
    return {
        "id": uid(),
        "revision": revision,
        "request_id": tool.data["request_id"],
        "purpose": tool.data["purpose"],
        "project_id": tool.foundation["project_id"],
        "source_status": "current",
        "required_source_read_set": tool.reads(),
    }


def fake_binding(tool, plan):
    return PlanBinding.model_validate(
        {
            "run_id": tool.data["run_id"],
            "request_id": tool.data["request_id"],
            "accepted_request_id": uid(),
            "accepted_request_revision": 5,
            "build_id": tool.data["build_id"],
            "project_id": tool.foundation["project_id"],
            "purpose": tool.data["purpose"],
            **{
                k: plan.model_dump(mode="json")[k]
                for k in (
                    "window",
                    "executor_id",
                    "environment",
                    "conditions",
                    "equipment",
                    "calibration",
                )
            },
            "pairs": [
                {
                    "sample": tool.data["sample_ref"],
                    "item_id": "dimension",
                    "method_id": uid(),
                    "method_revision": 1,
                    "method_sha256": "a" * 64,
                    "destructive": False,
                }
            ],
        }
    ).model_dump(mode="json")


def test_resource_export_real_dto_and_actual_current_fact_selection(tool, monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "publication", lambda: None)
    monkeypatch.setattr(tool, "resource_binding", lambda plan: fake_binding(tool, plan))
    monkeypatch.setattr(m, "RESOURCE_PROFILE", tmp_path / "profile.json")
    monkeypatch.setattr(m, "RESOURCE_INPUT", tmp_path / "input.json")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    tool.data["receipts"]["accept"] = {"id": uid()}
    at = datetime.now(UTC)
    tool.resources(
        window_start=(at + timedelta(minutes=5)).isoformat(),
        window_end=(at + timedelta(hours=2)).isoformat(),
        valid_until=(at + timedelta(hours=3)).isoformat(),
    )
    raw = ResourceFactInput.model_validate(tool.data["resource_input"])
    assert {v.resource.kind for v in raw.resources} == {"equipment", "person"}
    assert (
        next(v for v in raw.resources if v.resource.kind == "person").resource.id
        == raw.binding.executor_id
    )
    assert all(d.operation_id == "test.run.start" for r in raw.resources for d in r.facts)
    assert all(
        v.artifact_id == raw.sources[0].artifact_id for r in raw.resources for v in r.sources
    )
    assert tool.data["phase"] == "resource_exports_not_imported_or_installed"
    current = {
        "id": uid(),
        "revision": 1,
        "state": "active",
        "current": True,
        "source_status": "current",
        "binding": raw.binding.model_dump(mode="json"),
    }
    monkeypatch.setattr(
        tool,
        "current",
        lambda *args, **kwargs: ({"resource_facts": [current]}, actual_formal(tool), None),
    )
    plan, _ = tool.installed_plan()
    assert plan["resource_fact_id"] == current["id"]
    assert plan["resource_fact_id"] != tool.data["execution_plan"]["resource_fact_id"]
    current["source_status"] = "needs_recheck"
    with pytest.raises(m.Missing):
        tool.installed_plan()


def test_handoff_payloads_match_actual_public_schemas_and_no_visibility_claim(tool, monkeypatch):
    monkeypatch.setattr(tool, "publication", lambda: None)
    saved = {}
    sample = tool.data["sample_ref"]
    actual = actual_formal(tool)
    view = {
        "reference_samples": [
            {
                "id": sample["id"],
                "request_id": tool.data["request_id"],
                "reference": sample,
                "required_source_read_set": tool.reads(),
            }
        ]
    }
    monkeypatch.setattr(tool, "current", lambda *args, **kwargs: (view, actual, None))
    monkeypatch.setattr(
        tool,
        "get",
        lambda *args, **kwargs: {
            "preparations": [
                {
                    "id": saved["preparation"]["subject_id"],
                    "revision": 1,
                    "sha256": "a" * 64,
                    "source_status": "current",
                    "required_source_read_set": tool.reads(),
                }
            ]
        },
    )
    payloads = {}

    def step(label, role, operation, family, factory, **kwargs):
        payload, reads = factory()
        PAYLOADS[operation].model_validate(payload)
        payloads[label] = payload
        result = receipt(tool, role, operation, family)
        tool.data["receipts"][label] = saved[label] = result
        return result

    monkeypatch.setattr(tool, "step", step)
    tool.handoff(
        offer_at=(datetime.now(UTC) - timedelta(seconds=3)).isoformat(),
        accept_at=(datetime.now(UTC) - timedelta(seconds=2)).isoformat(),
    )
    assert "visibility" not in payloads["preparation"]
    assert payloads["preparation"]["items"][0]["criterion"]["lower"] == "9.5"
    assert payloads["actual-method"]["assessments"][0]["sample"] == sample
    assert "event-handoff" in payloads and "event-offer" not in payloads
    assert tool.data["receipts"]["offer"]["writer_id"] == tool.actor("maker")
    assert tool.data["receipts"]["accept"]["writer_id"] == tool.actor("observer")


@pytest.mark.parametrize("operation", ["verification.schedule.promise", "test.run.start"])
def test_plan_window_not_an_actual_event_clock(tool, monkeypatch, operation):
    now = datetime.now(UTC)
    row = actual_formal(tool)
    run = {
        "status": "planned",
        "execution_plan": {
            "window": {
                "start": (now + timedelta(minutes=10)).isoformat(),
                "finish": (now + timedelta(hours=1)).isoformat(),
            }
        },
    }
    monkeypatch.setattr(tool, "current", lambda *args, **kwargs: ({}, row, run))
    monkeypatch.setattr(tool, "step", lambda a, b, c, d, factory, **kwargs: factory())
    monkeypatch.setattr(
        tool, "event", lambda *args, **kwargs: pytest.fail("No premature event publication")
    )
    with pytest.raises(m.Missing):
        getattr(tool, "promise" if operation == "verification.schedule.promise" else "start")(
            occurred_at=now.isoformat()
        )


def test_report_original_bytes_remain_exact_and_no_native_measurement_substitute(
    tool, monkeypatch, tmp_path
):
    tool.data["receipts"]["run-start"] = {"id": uid()}
    at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    report = {
        "report_utf8": '{"raw_value":"11.0000","not_filled_from_plan":null}\n',
        "actual_end": at,
        "returned_at": at,
        "original_timezone": "UTC",
    }
    path = tmp_path / "raw.json"
    tool.h.private_write(path, report)
    uploaded = []

    def auxiliary(label, role, target, body):
        assert label == "report-upload"
        uploaded.append(deepcopy(body))
        raise m.Unknown(label)

    monkeypatch.setattr(tool, "auxiliary", auxiliary)
    with pytest.raises(m.Unknown):
        tool.report(material=path)
    import base64

    assert base64.b64decode(uploaded[0]["content_base64"]).decode() == report["report_utf8"]
    assert tool.data["report_material"] == report
    assert uploaded[0]["visibility"] == "product"
    assert uploaded[0]["filename"].endswith(".txt")
    # This deliberately invalid raw report is never claimed verified by the driver.
    assert "events" not in json.loads(report["report_utf8"])


def test_incomplete_scan_or_parse_does_not_fake_safe_or_create_capture(tool, monkeypatch):
    tool.data["receipts"]["run-start"] = {"id": uid()}
    at = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    tool.data["report_material"] = {
        "report_utf8": "RAW\n",
        "actual_end": at,
        "returned_at": at,
        "original_timezone": "UTC",
    }
    tool.data["report-upload"] = {"subject_id": uid()}
    tool.data["report-scan"] = {"status": "pending"}
    monkeypatch.setattr(
        tool,
        "current",
        lambda *args, **kwargs: ({"report_sources": []}, actual_formal(tool), {"id": uid()}),
    )
    monkeypatch.setattr(
        tool, "auxiliary", lambda *args, **kwargs: pytest.fail("No fabricated capture")
    )
    with pytest.raises(m.Missing):
        tool.report()
    assert "capture" not in tool.data


def test_current_uses_immutable_pointer_not_run_origin(tool, monkeypatch):
    row = actual_formal(tool, revision=7)
    run = {
        "id": uid(),
        "run_id": tool.data["run_id"],
        "revision": 3,
        "request_version_id": uid(),
        "source_status": "current",
    }
    view = {
        "requests": [row],
        "runs": [run],
        "current_by_request": {
            tool.data["request_id"]: {"request_version_id": row["id"], "revision": 7}
        },
        "current_by_run": {tool.data["run_id"]: {"run_version_id": run["id"], "revision": 3}},
    }
    monkeypatch.setattr(tool, "get", lambda *args, **kwargs: view)
    assert tool.current()[1:] == (row, run)
    view["current_by_request"][tool.data["request_id"]]["request_version_id"] = run[
        "request_version_id"
    ]
    with pytest.raises(m.Missing):
        tool.current()


def test_launch_payloads_actual_six_field_event_and_complete_saved_plan(tool, monkeypatch):
    from pdos_next.domain.verification_launch.schemas import ExecutionPlan

    now = datetime.now(UTC)
    plan = ExecutionPlan.model_validate(
        {
            "window": {
                "start": (now + timedelta(minutes=5)).isoformat(),
                "finish": (now + timedelta(hours=1)).isoformat(),
                "original_timezone": "UTC",
            },
            "executor_id": tool.actor("observer"),
            "equipment": tool.published("equipment"),
            "calibration": tool.published("calibration"),
            "environment": "Synthetic",
            "conditions": "23 C, dry",
            "resource_fact_id": uid(),
            "expected_resource_fact_revision": 1,
        }
    ).model_dump(mode="json")
    row = actual_formal(tool, 5)
    run = {
        "id": uid(),
        "revision": 1,
        "status": "planned",
        "execution_plan": plan,
        "plan_sha256": "c" * 64,
    }
    monkeypatch.setattr(tool, "installed_plan", lambda: (plan, row))
    monkeypatch.setattr(tool, "current", lambda *args, **kwargs: ({}, row, run))
    payloads = {}

    def step(label, role, op, family, factory, **kwargs):
        raw, reads = factory()
        PAYLOADS[op].model_validate(raw)
        assert role == "observer"
        payloads[label] = {"payload": raw, "family": family}
        return receipt(tool, role, op, family)

    monkeypatch.setattr(tool, "step", step)
    tool.plan()
    tool.promise(occurred_at=plan["window"]["start"])
    # Only the actual Start fixture advances to an already-open window. No future Start is saved.
    start_window = deepcopy(plan["window"])
    start_window["start"] = (now - timedelta(minutes=1)).isoformat()
    run["execution_plan"] = {**plan, "window": start_window}
    tool.start(occurred_at=(now - timedelta(seconds=4)).isoformat())
    assert payloads["run-plan"]["payload"]["coverage"] == tool.data["coverage"]
    assert payloads["promise"]["family"] == "verification_request"
    assert payloads["run-start"]["family"] == "test_run"
    for key in ("promise", "run-start"):
        value = payloads[key]["payload"]
        at = json.loads(tool.data["events"][key]["text"])
        assert set(at) == {
            "request_id",
            "run_id",
            "purpose",
            "operation",
            "occurred_at",
            "executor_id",
        }
        if key == "promise":
            assert value["at"]["occurred_at"] == plan["window"]["start"]
        else:
            assert value["at"]["occurred_at"] != plan["window"]["start"]
        assert at["executor_id"] == tool.actor("observer")


@pytest.mark.parametrize("bad", ["past", "wrong_future", "naive", "offset", "missing"])
def test_promise_requires_exact_future_start_and_does_not_relax_actual_events(bad):
    now = datetime.now(UTC)
    window = {
        "start": (now + timedelta(minutes=20)).isoformat(),
        "finish": (now + timedelta(hours=1)).isoformat(),
        "original_timezone": "UTC",
    }
    supplied = {
        "past": (now - timedelta(seconds=1)).isoformat(),
        "wrong_future": (now + timedelta(minutes=25)).isoformat(),
        "naive": "2026-10-03T19:00:00",
        "offset": "2026-10-03T19:00:00+08:00",
        "missing": None,
    }[bad]
    assert m.promise_start(window["start"], window).isoformat() == window["start"]
    with pytest.raises(m.Missing):
        m.promise_start(supplied, window)
    with pytest.raises(m.Missing):
        m.aware_past(window["start"])


def test_future_event_gate_only_applies_to_exact_promise(tool, monkeypatch):
    window = {
        "start": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "finish": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "original_timezone": "UTC",
    }
    captured = []

    def step(label, role, operation, family, factory, **kwargs):
        payload, _ = factory()
        captured.append(payload)
        return receipt(tool, role, operation, family)

    monkeypatch.setattr(tool, "step", step)
    event = tool.event(
        "promise",
        "observer",
        "verification.schedule.promise",
        window["start"],
        executor=True,
        promise_window=window,
    )
    raw = json.loads(captured[0]["content"])
    assert len(raw) == 6 and raw["occurred_at"] == window["start"]
    assert "not an actual Start" in captured[0]["source_label"]
    assert event["at"]["occurred_at"] == window["start"]
    for kwargs in ({}, {"promise_window": window}):
        with pytest.raises(m.Missing):
            tool.event(
                "future-start",
                "observer",
                "test.run.start",
                window["start"],
                executor=True,
                **kwargs,
            )
    with pytest.raises(m.Missing):
        tool.event(
            "unbound-promise",
            "observer",
            "verification.schedule.promise",
            window["start"],
            executor=True,
        )


def test_expired_fixed_promise_cannot_be_replanned_or_renewed(tool, monkeypatch):
    old = datetime.now(UTC) - timedelta(minutes=2)
    window = {
        "start": old.isoformat(),
        "finish": (old + timedelta(hours=1)).isoformat(),
        "original_timezone": "UTC",
    }
    monkeypatch.setattr(tool, "step", lambda *a, **k: pytest.fail("No re-publication"))
    with pytest.raises(m.Missing):
        tool.event(
            "late-promise",
            "observer",
            "verification.schedule.promise",
            window["start"],
            executor=True,
            promise_window=window,
        )


def test_results_uses_genuine_original_endpoint_then_capture_no_value_payload(
    tool, monkeypatch, tmp_path
):
    from pdos_next.contracts import UploadInput
    from pdos_next.domain.verification_results.schemas import CaptureInput

    tool.data["receipts"]["run-start"] = {"id": uid()}
    clock = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    material = {
        "report_utf8": '{"raw_value":"11.0000"}\n',
        "actual_end": clock,
        "returned_at": clock,
        "original_timezone": "UTC",
    }
    source = tmp_path / "original-material.json"
    tool.h.private_write(source, material)
    original = uid()
    report = {
        "artifact_id": uid(),
        "artifact_revision": 1,
        "original_id": original,
        "source_status": "current",
    }
    row = actual_formal(tool, 8)
    run = {"id": uid(), "revision": 2}
    monkeypatch.setattr(
        tool, "current", lambda *args, **kwargs: ({"report_sources": [report]}, row, run)
    )
    monkeypatch.setattr(
        tool,
        "get",
        lambda *args, **kwargs: {
            "product": {"id": tool.product, "revision": 5},
            "originals": [{"id": original, "security": {"epoch": 1}}],
        },
    )
    endpoints = []

    def auxiliary(label, role, path, body):
        endpoints.append((label, role, path, deepcopy(body)))
        if label == "report-upload":
            UploadInput.model_validate(body)
            value = receipt(tool, role, "evidence.original.upload", "uploaded_original", original)
        elif label == "report-scan":
            value = {"scan_status": "queued"}
        else:
            CaptureInput.model_validate(body)
            value = {"capture": {"id": uid(), "revision": 1}}
        tool.data[label] = value
        return value

    monkeypatch.setattr(tool, "auxiliary", auxiliary)
    payloads = {}

    def step(label, role, op, family, factory, **kwargs):
        raw, reads = factory()
        PAYLOADS[op].model_validate(raw)
        payloads[label] = (raw, reads)
        return receipt(tool, role, op, family)

    monkeypatch.setattr(tool, "step", step)
    tool.report(material=source)
    assert [v[0] for v in endpoints] == ["report-upload", "report-scan", "capture"]
    assert all(v[1] == "observer" for v in endpoints)
    raw, reads = payloads["results"]
    assert "measurements" not in raw and "raw_value" not in raw
    assert raw["final"] is True
    assert raw["at"]["source"]["id"] == raw["actual_end"]["source"]["id"]
    assert raw["at"]["source"]["position"].startswith("line:2;")
    assert raw["actual_end"]["source"]["position"].startswith("line:1;")
    assert read(raw["sources"][0]) in reads


def test_readback_needs_actual_saved_projection_not_only_run_fail(tool, monkeypatch):
    row = actual_formal(tool, 9)
    run = {
        "id": uid(),
        "revision": 3,
        "basis_sha256": "c" * 64,
        "required_source_read_set": tool.reads(),
        "run_snapshot": {"result": "fail"},
    }
    monkeypatch.setattr(tool, "current", lambda *args, **kwargs: ({}, row, run))
    with pytest.raises(m.Missing):
        tool.readback()
    saved = receipt(tool, "observer", "test.result.compute", "test_result_projection")
    tool.data["receipts"]["compute"] = saved
    tool.data["report_sha256"] = "f" * 64
    run["current_projection"] = {
        "id": saved["subject_id"],
        "revision": 1,
        "basis_sha256": run["basis_sha256"],
        "result": "fail",
    }
    tool.readback()
    assert tool.data["result_readback"]["professional_review"] is None
    assert tool.data["result_readback"]["effectiveness"] is None
    assert tool.data["result_readback"]["close"] is False
    run["current_projection"]["basis_sha256"] = "a" * 64
    with pytest.raises(m.Missing):
        tool.readback()


def test_inputs_union_keeps_supplied_sources_and_no_authority_bool_fallback(tool, monkeypatch):
    install_fake_common(tool, monkeypatch)
    send = tool.request
    extra = read(ref())

    def request(role, method, path, *, body=None, params=None):
        if path.endswith("/inputs"):
            return {
                "allowed": True,
                "operation": body["operation"],
                "required_source_read_set": [extra],
            }
        return send(role, method, path, body=body, params=params)

    monkeypatch.setattr(tool, "request", request)
    with pytest.raises(m.Pending):
        tool.step(
            "method",
            "observer",
            "verification.method.prepare",
            "verification_request",
            lambda: method_payload(tool),
            inputs="explicit-test/inputs",
        )
    final = tool.data["requests"]["method"]["original"]["source_read_set"]
    assert extra in final
    assert all(v in final for v in tool.reads())


@pytest.fixture
def prospective(tool, monkeypatch, tmp_path):
    from pdos_next.contracts import Command

    monkeypatch.setattr(m, "helpers", lambda: tool.h)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    monkeypatch.setattr(m, "CHECKPOINT", tmp_path / "origin.json")
    monkeypatch.setattr(m, "RESOURCE_PROFILE", tmp_path / "old-profile.json")
    monkeypatch.setattr(m, "RESOURCE_INPUT", tmp_path / "old-input.json")
    monkeypatch.setattr(tool, "publication", lambda: None)
    monkeypatch.setattr(tool, "resource_binding", lambda plan: fake_binding(tool, plan))
    tool.data["receipts"]["accept"] = {"id": uid()}
    clock = datetime.now(UTC)
    tool.resources(
        window_start=(clock + timedelta(minutes=5)).isoformat(),
        window_end=(clock + timedelta(minutes=50)).isoformat(),
        valid_until=(clock + timedelta(hours=3)).isoformat(),
    )
    old_input = deepcopy(tool.data["resource_input"])
    old_profile = m.private_json(m.RESOURCE_PROFILE)
    plan = deepcopy(tool.data["execution_plan"])
    plan["resource_fact_id"] = uid()
    payload = (
        PAYLOADS["test.run.plan"]
        .model_validate(
            {
                "request_id": tool.data["request_id"],
                "expected_request_revision": 5,
                "run_id": tool.data["run_id"],
                "coverage": tool.data["coverage"],
                "execution_plan": plan,
                "sources": [tool.ref()],
                "reason": "Exact original plan",
            }
        )
        .model_dump(mode="json", exclude_none=True)
    )
    original = Command(
        command_id=tool.command_id("run-plan", "observer"),
        idempotency_key=tool.key("run-plan"),
        operation="test.run.plan",
        product_id=tool.product,
        expected_revision=7,
        source_read_set=tool.reads(),
        payload=payload,
    ).model_dump(mode="json")
    body = deepcopy(original)
    body["payload"]["confirmation_token"] = "FAKE_OFFLINE_PROOF_NOT_A_REAL_TOKEN"
    tool.data["requests"] = {label: {"original": {"label": label}} for label in m.HANDOFF_LABELS}
    tool.data["receipts"] = {label: {"id": uid()} for label in m.HANDOFF_LABELS}
    tool.data["events"] = {"handoff": {"explicit_prior_original": True}}
    tool.data["requests"]["run-plan"] = {
        "state": "awaiting_confirmation",
        "tier": "T1",
        "role": "observer",
        "actor_id": tool.actor("observer"),
        "original": original,
        "body": body,
        "preview": {"command": body},
    }
    tool.data["case_id"] = tool.foundation["case_id"]
    tool.data["marker"] = tool.marker
    tool.data["schema_version"] = "wave22-shared-test-v1"
    tool.h.private_write(m.CHECKPOINT, tool.data)
    evidence = {
        "status": "PASS",
        "recorded_at": (clock - timedelta(seconds=3)).isoformat(),
        "target": "127.0.0.1:62513/pdos_test",
        "marker": tool.marker,
        "original_command_id": original["command_id"],
        "original_key": original["idempotency_key"],
        "original_body_sha256": m.value_sha(body),
        "fixed_window": plan["window"],
        "receipt_fact_id": plan["resource_fact_id"],
        "business_writes": 0,
        "action_receipts_count": 0,
        "request_keys_count": 0,
        "verification_run_identities_count": 0,
        "verification_run_versions_count": 0,
        "verification_current_runs_count": 0,
        "prepared_confirmation": {"consumed": False, "exact_actor_and_product": True},
    }
    decision = {
        "status": "WITHDRAWN_UNSUBMITTED_PROPOSAL",
        "recorded_at": (clock - timedelta(seconds=2)).isoformat(),
        "original_command_id": original["command_id"],
        "original_key": original["idempotency_key"],
        "readback_proof": "observed.json",
        "readback_sha256": "b" * 64,
        "original_requests_and_token_retained": True,
        "new_prospective_window_requires_new_intent_and_receipt": True,
        "checkpoint_changed": False,
        "fact1_withdrawn_or_deleted": False,
        "new_test_start": False,
    }
    material = {
        "schema_version": "wave22-prospective-plan-v1",
        "generation": uid(),
        "origin_checkpoint_sha256": m.digest_file(m.CHECKPOINT),
        "old_resource_input_sha256": m.digest_file(m.RESOURCE_INPUT),
        "old_resource_profile_sha256": m.digest_file(m.RESOURCE_PROFILE),
        "readback_file": "docs/reports/evidence/pdos-next-wave22-20261003/observed.json",
        "readback_sha256": "b" * 64,
        "decision_file": "docs/reports/evidence/pdos-next-wave22-20261003/decision.json",
        "decision_sha256": "d" * 64,
        "intent_recorded_at": (clock - timedelta(seconds=1)).isoformat(),
        "window": {
            "start": (clock + timedelta(minutes=20)).isoformat(),
            "finish": (clock + timedelta(minutes=65)).isoformat(),
            "original_timezone": "UTC",
        },
        "valid_until": (clock + timedelta(hours=3)).isoformat(),
        "issuer_key": old_profile["issuer_key"],
        "issuer_version": "v2",
        "reason": "Explicit new local synthetic prospective Run intent, old proposal retained",
    }
    monkeypatch.setattr(
        m,
        "evidence_file",
        lambda path: (
            (deepcopy(evidence), "b" * 64)
            if Path(path).name == "observed.json"
            else (deepcopy(decision), "d" * 64)
        ),
    )
    path = tmp_path / "material.json"
    tool.h.private_write(path, material)
    return tool, material, evidence, decision, old_input, old_profile, path


def test_prospective_branch_preserves_all_originals_and_requires_explicit_namespace(prospective):
    tool, raw, evidence, decision, old_input, old_profile, path = prospective
    original = deepcopy(tool.data)
    before = {p: p.read_bytes() for p in (m.CHECKPOINT, m.RESOURCE_PROFILE, m.RESOURCE_INPUT)}
    result = tool.prospective_plan(material=path)
    selected = m.private_json(m.generation_paths(raw["generation"])[0])
    assert result["new_plan_receipt"] is None
    assert selected["origin_archive"] == original
    assert "run-plan" not in selected["requests"]
    assert selected["receipts"] == original["receipts"]
    assert selected["requests"] == {
        k: v for k, v in original["requests"].items() if k != "run-plan"
    }
    assert selected["events"] == original["events"]
    assert selected["case_id"] == original["case_id"]
    assert selected["run_id"] != original["run_id"]
    assert selected["request_id"] == original["request_id"]
    assert selected["test_equipment_id"] == original["test_equipment_id"]
    assert {p: p.read_bytes() for p in before} == before
    assert tool.data == original
    tool.data = selected
    assert (
        tool.command_id("run-plan", "observer")
        != original["requests"]["run-plan"]["original"]["command_id"]
    )
    assert tool.key("run-plan") != original["requests"]["run-plan"]["original"]["idempotency_key"]
    assert tool.key("accept") == f"wave22-{original['case_id']}-observer-accept"
    # Complete Root observations permit an explicit branch, not a runtime authorization.
    assert not m.generation_paths(raw["generation"])[1].exists()


@pytest.mark.parametrize(
    "state", ["sending", "unknown", "preview_unknown", "saved", "rejected", "ready"]
)
def test_prospective_never_rekeys_unknown_or_sent_original(prospective, state):
    tool, raw, evidence, decision, _, profile, _ = prospective
    old = deepcopy(tool.data)
    old["requests"]["run-plan"]["state"] = state
    with pytest.raises(m.Missing, match="never-sent"):
        m.checked_prospective_material(raw, old, profile, evidence, decision, at=datetime.now(UTC))


@pytest.mark.parametrize(
    "field",
    [
        "business_writes",
        "action_receipts_count",
        "request_keys_count",
        "verification_run_identities_count",
        "verification_run_versions_count",
        "verification_current_runs_count",
    ],
)
def test_prospective_requires_zero_actual_observations_not_bool(prospective, field):
    tool, raw, evidence, decision, _, profile, _ = prospective
    for invalid in (1, False, None):
        broken = {**evidence, field: invalid}
        with pytest.raises(m.Missing, match="zero-write"):
            m.checked_prospective_material(
                raw, tool.data, profile, broken, decision, at=datetime.now(UTC)
            )


@pytest.mark.parametrize(
    "fault",
    [
        "consumed",
        "wrong-body",
        "wrong-command",
        "no-root-decision",
        "future-clock",
        "too-soon",
        "same-window",
        "same-generation",
        "wrong-issuer",
        "missing-ledger",
        "extra-field",
        "future-action",
    ],
)
def test_prospective_rejects_unproved_material_change(prospective, fault):
    tool, raw, evidence, decision, _, profile, _ = prospective
    raw, old, evidence, decision, profile = map(
        deepcopy, (raw, tool.data, evidence, decision, profile)
    )
    if fault == "consumed":
        evidence["prepared_confirmation"]["consumed"] = True
    elif fault == "wrong-body":
        evidence["original_body_sha256"] = "0" * 64
    elif fault == "wrong-command":
        evidence["original_command_id"] = uid()
    elif fault == "no-root-decision":
        decision["checkpoint_changed"] = True
    elif fault == "future-clock":
        raw["intent_recorded_at"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    elif fault == "too-soon":
        raw["window"]["start"] = (datetime.now(UTC) + timedelta(minutes=14)).isoformat()
    elif fault == "same-window":
        raw["window"] = deepcopy(old["execution_plan"]["window"])
    elif fault == "same-generation":
        raw["generation"] = old["case_id"]
    elif fault == "wrong-issuer":
        raw["issuer_key"] = "invented-key"
    elif fault == "missing-ledger":
        profile["decisions"].pop()
    elif fault == "extra-field":
        raw["force"] = True
    elif fault == "future-action":
        old["requests"]["promise"] = {"state": "unknown"}
    with pytest.raises(m.Missing):
        m.checked_prospective_material(raw, old, profile, evidence, decision, at=datetime.now(UTC))


def test_prospective_resource_stage_real_binding_physical_mirror_and_full_ledger(
    prospective, monkeypatch
):
    tool, raw, evidence, decision, old_input, old_profile, path = prospective
    tool.prospective_plan(material=path)
    paths = m.generation_paths(raw["generation"])
    tool.data = m.private_json(paths[0])
    tool.checkpoint_path, tool.resource_profile_path, tool.resource_input_path = paths
    expected = {
        **old_input["binding"],
        "run_id": tool.data["run_id"],
        "window": tool.data["execution_plan"]["window"],
    }
    calls = []
    monkeypatch.setattr(tool, "resource_binding", lambda plan: (calls.append(plan), expected)[1])
    original_files = {
        p: p.read_bytes() for p in (m.CHECKPOINT, m.RESOURCE_PROFILE, m.RESOURCE_INPUT)
    }
    result = tool.resources()
    assert len(calls) == 1
    assert result["new_series_revision"] == 1
    new = m.private_json(paths[2])
    typed = ResourceFactInput.model_validate(new)
    assert typed.expected_previous_id is None and typed.expected_previous_revision == 0
    assert new["binding"] == expected
    assert new["external_id"] != old_input["external_id"]
    assert new["required_uses"] == old_input["required_uses"]
    assert new["requirements_sources"] == old_input["requirements_sources"]
    assert new["sources"] == old_input["sources"]
    for original, current in zip(old_input["resources"], new["resources"], strict=True):
        assert {k: v for k, v in original.items() if k != "facts"} == {
            k: v for k, v in current.items() if k != "facts"
        }
        assert all(
            a["named_decision_id"] != b["named_decision_id"]
            for a, b in zip(original["facts"], current["facts"], strict=True)
        )
    new_profile = m.private_json(paths[1])
    assert new_profile["issuer_key"] == old_profile["issuer_key"]
    assert new_profile["issuer_version"] == "v2"
    assert new_profile["decisions"][: len(old_profile["decisions"])] == old_profile["decisions"]
    assert {p: p.read_bytes() for p in original_files} == original_files
    before = {p: p.read_bytes() for p in paths[1:]}
    tool.resources()
    assert (
        len(calls) == 1
    )  # Retain the export; actual import/Plan independently repeat current gates.
    assert {p: p.read_bytes() for p in before} == before


def test_prospective_resource_rejects_actual_method_drift_and_no_new_files(
    prospective, monkeypatch
):
    tool, raw, _, _, old_input, _, path = prospective
    tool.prospective_plan(material=path)
    paths = m.generation_paths(raw["generation"])
    tool.data = m.private_json(paths[0])
    tool.checkpoint_path, tool.resource_profile_path, tool.resource_input_path = paths
    changed = {
        **old_input["binding"],
        "run_id": tool.data["run_id"],
        "window": tool.data["execution_plan"]["window"],
    }
    changed["pairs"][0]["method_revision"] += 1
    monkeypatch.setattr(tool, "resource_binding", lambda plan: changed)
    with pytest.raises(m.Missing, match="method changed"):
        tool.resources()
    assert not paths[1].exists() and not paths[2].exists()
    assert "resource_input" not in tool.data


def test_prospective_original_file_change_never_overwrites_new_generation(prospective):
    tool, raw, _, _, _, _, path = prospective
    tool.prospective_plan(material=path)
    paths = m.generation_paths(raw["generation"])
    before = paths[0].read_bytes()
    m.CHECKPOINT.write_bytes(m.CHECKPOINT.read_bytes() + b"\n")
    with pytest.raises(m.Missing, match="hashes"):
        tool.prospective_plan(material=path)
    assert paths[0].read_bytes() == before


def test_prospective_layouts_are_explicit_and_source_never_selects_automatic_generation():
    assert m.layout_root(m.ROOT / ".local/wave22-test-staged/v4/wave22_shared_test.py") == m.ROOT
    assert (
        owned_source(m.ROOT / "tools/tests/test_wave22_shared_test.py")
        == m.ROOT / "tools/wave22_shared_test.py"
    )
    assert m.generation_paths(uid())[0].parent == m.ROOT / ".local"


@pytest.mark.parametrize(
    "tamper", ["run", "plan", "archive", "profile", "labels", "receipt", "sample", "purpose"]
)
def test_prospective_constructor_origin_seal_rejects_changes(prospective, tamper):
    tool, raw, _, _, _, _, path = prospective
    tool.prospective_plan(material=path)
    tool.data = m.private_json(m.generation_paths(raw["generation"])[0])
    if tamper == "run":
        tool.data["run_id"] = uid()
    elif tamper == "plan":
        tool.data["execution_plan"]["window"]["start"] = "2999-01-01T00:00:00Z"
    elif tamper == "archive":
        tool.data["origin_archive"]["phase"] = "changed"
    elif tamper == "profile":
        tool.data["prospective_generation"]["old_profile"]["decisions"].pop()
    elif tamper == "labels":
        tool.data["prospective_generation"]["inherited_labels"].append("run-plan")
    elif tamper == "receipt":
        tool.data["receipts"]["accept"]["id"] = uid()
    elif tamper == "sample":
        tool.data["original_sample_id"] = tool.data["followup_sample_id"]
    else:
        tool.data["purpose"] = "Changed scope"
    with pytest.raises((m.Missing, ValueError)):
        tool._origin_files(tool.data["prospective_generation"])


def test_prospective_new_plan_unknown_recovers_original_without_live_factory(
    prospective, monkeypatch
):
    tool, raw, _, _, _, _, path = prospective
    tool.prospective_plan(material=path)
    paths = m.generation_paths(raw["generation"])
    tool.data = m.private_json(paths[0])
    tool.checkpoint_path = paths[0]
    tool.calls = []
    payload = deepcopy(tool.data["origin_archive"]["requests"]["run-plan"]["original"]["payload"])
    payload.update(run_id=tool.data["run_id"], execution_plan=tool.data["execution_plan"])
    install_fake_common(tool, monkeypatch, family="test_run")
    with pytest.raises(m.Pending):
        tool.step(
            "run-plan", "observer", "test.run.plan", "test_run", lambda: (payload, tool.reads())
        )
    prepared = tool.data["requests"]["run-plan"]
    assert prepared["original"]["command_id"] == tool.command_id("run-plan", "observer")
    assert prepared["original"]["idempotency_key"] == tool.key("run-plan")
    assert prepared["original"]["payload"]["run_id"] == tool.data["run_id"]
    assert tool.calls[0][0] == "/v1/commands/preview"
    assert len(tool.calls) == 1
    body = deepcopy(prepared["body"])
    tool.confirm, tool.review_digest = "run-plan", prepared["review_digest"]
    monkeypatch.setattr(
        tool, "request", lambda *a, **kw: (_ for _ in ()).throw(httpx.ReadTimeout("OFFLINE"))
    )
    with pytest.raises(m.Unknown):
        tool.step(
            "run-plan", "observer", "test.run.plan", "test_run", lambda: pytest.fail("No rebuild")
        )
    assert prepared["state"] == "unknown"
    install_fake_common(tool, monkeypatch, family="test_run")
    tool.recover = "run-plan"
    monkeypatch.setattr(tool, "get", lambda *a, **kw: pytest.fail("No live revision on recovery"))
    result = tool.step(
        "run-plan", "observer", "test.run.plan", "test_run", lambda: pytest.fail("No rebuild")
    )
    assert tool.calls[-1] == ("/v1/commands", body)
    assert result == tool.data["receipts"]["run-plan"]
    assert tool.data["origin_archive"]["requests"]["run-plan"]["state"] == "awaiting_confirmation"
    assert m.private_json(m.CHECKPOINT)["requests"]["run-plan"]["state"] == "awaiting_confirmation"
