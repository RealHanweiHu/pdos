"""Owned offline protocol checks: substitutes never attest business qualification."""

import importlib.util
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine


def owned_source(test_path):
    folder = Path(test_path).resolve().parent
    if folder.name == "wave22-followup-control-staged" and folder.parent.name == ".local":
        return folder / "wave22_followup_control.py"
    if folder.name == "tests" and folder.parent.name == "tools":
        return folder.parent / "wave22_followup_control.py"
    raise RuntimeError("Unexpected owned followup check layout")


spec = importlib.util.spec_from_file_location("owned_followup_control", owned_source(__file__))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
sys.path[:0] = [str(m.ROOT / "server"), str(m.ROOT / "tools")]
from pdos_next.contracts import Command  # noqa: E402
from pdos_next.domain.capa_effectiveness.fact_commands import (  # noqa: E402
    NamedReviewPayload,
    ObservationPayload,
    RulePublicationInput,
)
from pdos_next.service import T1_OPERATIONS, T2_OPERATIONS  # noqa: E402


def uid():
    return str(uuid4())


def ref():
    return {"artifact_id": uid(), "expected_revision": 1, "line": 1, "quote": "Raw 来源"}


def read(reference):
    return {key: reference[key] for key in ("artifact_id", "expected_revision")}


def source():
    return m.retest.source_ref(ref())


def fact():
    return {"id": uid(), "revision": 1, "sha256": "a" * 64}


def receipt(tool, role, operation, family):
    subject = uid()
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
def no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No DB/HTTP/live private checkpoint in owned checks")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(Engine, "raw_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(m.FollowupControl, "target", forbidden)
    monkeypatch.setattr(m.first, "private_json", forbidden)
    monkeypatch.setattr(m.retest, "checkpoint_json", forbidden)


@pytest.fixture
def tool(monkeypatch):
    value = m.FollowupControl.__new__(m.FollowupControl)
    value.h = m.first.helpers()
    value.marker, value.namespace = uid(), uid()
    value.confirm = value.review_digest = value.recover = None
    value.confirm_used = value.recover_used = False
    scope = {name: uid() for name in ("tenant_id", "product_id", "project_id")}
    value.foundation = {
        **scope,
        "scope": scope,
        "sources": {"foundation": {"required_source_read_set": [read(ref())]}},
        "actors": {role: {"id": uid()} for role in ("maker", "observer", "independent_reviewer")},
    }
    value.build = {"required_source_read_set": [read(ref())]}
    value.data = {
        "scope": scope,
        "issue_id": uid(),
        "capa_id": uid(),
        "capa_action_id": uid(),
        "purpose": "Verify shared synthetic preparation",
        "request_id": uid(),
        "run_id": uid(),
        "requests": {},
        "receipts": {},
        "events": {},
        "materials": {},
        "publications": {},
        "test_publication": {"method_source": ref()},
        "phase": "offline_substitute",
    }
    value.parent = {"receipts": {"triage-runtime-reload-v1": {"explicit_substitute": True}}}
    value.live_revision = 4
    value.calls = []
    monkeypatch.setattr(value, "save", lambda: None)
    monkeypatch.setattr(
        value,
        "get",
        lambda family, role="observer": {
            "product": {"id": value.product, "revision": value.live_revision}
        },
    )
    return value


def install_common(tool, monkeypatch, family="artifact", t2=False):
    def request(role, method, path, *, body=None, params=None):
        assert method == "POST"
        tool.calls.append((role, path, deepcopy(body)))
        if path.endswith("/inputs"):
            return {
                "operation": body["operation"],
                "allowed": True,
                "required_source_read_set": deepcopy(body["source_read_set"]),
            }
        if path == "/v1/commands/preview":
            prepared = deepcopy(body)
            prepared["payload"]["approval_token" if t2 else "confirmation_token"] = "t" * 30
            return {
                "command": prepared,
                "review": {"explicit_substitute": True},
                **({"write_tier": "T2", "named_decision": True} if t2 else {}),
            }
        assert path == "/v1/commands"
        return receipt(tool, role, body["operation"], family)

    monkeypatch.setattr(tool, "request", request)


def blueprint(tool):
    rows = [{"raw_value": "11.0000", "nullable": None, "note": "原值"}]
    return {
        "rows": rows,
        "reads": tool.reads(),
        "native_payload": {
            "title": "Offline source substitute",
            "content": tool.h.canonical(rows[0]),
            "source_label": "Explicit substitute",
            "visibility": "product",
        },
    }


def original(tool):
    return Command(
        command_id=uid(),
        idempotency_key="offline-fixed-command-key",
        operation="quality.capa.verification.candidate.record",
        product_id=tool.product,
        expected_revision=4,
        source_read_set=tool.reads(),
        payload={
            "issue_id": tool.data["issue_id"],
            "expected_issue_revision": 6,
            "capa_id": tool.data["capa_id"],
            "reason": "Exact offline candidate",
            "visibility": "product",
        },
    ).model_dump(mode="json")


def rule_material(tool):
    now = datetime.now(UTC)
    src = source()
    fixed = {"id": uid(), "revision": 1}
    return {
        "schema_version": "wave22-followup-rule-material-v1",
        "issuer_key": "shared-rule-issuer",
        "issuer_version": "v1",
        "include_promise": False,
        "payload": {
            "external_id": "actual-fixed-series",
            "policy_ref": src,
            "method": src,
            "criterion": src,
            "reason": "Synthetic rule, no efficacy claim",
            "sampling": {
                "targets": [
                    {
                        "key": "sample-second",
                        "kind": "sample",
                        "ref": fixed,
                        "actual_configuration": fixed,
                        "identity_sources": [src],
                    }
                ],
                "minimum_records": 1,
                "sampling_method": src,
                "acceptance": src,
                "observation_from": (now + timedelta(minutes=2)).isoformat(),
                "observation_until": (now + timedelta(minutes=4)).isoformat(),
                "require_named_review": True,
                "require_run_review": True,
                "require_disposition": True,
            },
            "rule_material": {"raw_rule": "exact published value"},
            "independence_material": {"exclude_actual_participants": True},
            "valid_from": (now - timedelta(minutes=1)).isoformat(),
            "valid_until": (now + timedelta(minutes=15)).isoformat(),
        },
    }


def setup_origin(tool, monkeypatch):
    version = {"id": uid(), "revision": 6, "snapshot_sha256": "b" * 64}
    row = {
        "id": version["id"],
        "revision": 6,
        "required_source_read_set": tool.reads(),
        "issue": {
            "capa": {
                "actions": [
                    {
                        "completion": {
                            "at": {
                                "occurred_at": (
                                    datetime.now(UTC) - timedelta(minutes=1)
                                ).isoformat()
                            }
                        }
                    }
                ],
                "requirement": {
                    "observation_until": (datetime.now(UTC) + timedelta(minutes=3)).isoformat()
                },
            }
        },
    }
    monkeypatch.setattr(tool, "origin", lambda: (deepcopy(row), deepcopy(version)))
    return row, version


def observation_material():
    now = datetime.now(UTC) - timedelta(minutes=2)
    return {
        "schema_version": "wave22-followup-observation-material-v1",
        "records": [
            {
                "target_key": "sample-second",
                "occurred_at": now.isoformat(),
                "original_timezone": "UTC",
                "raw_material": {"raw_value": "1.5000", "temperature": None},
            }
        ],
        "observed_from": (now - timedelta(seconds=2)).isoformat(),
        "observed_until": (now + timedelta(seconds=2)).isoformat(),
        "at": {"occurred_at": (now + timedelta(seconds=3)).isoformat(), "original_timezone": "UTC"},
        "named_run_conclusions": None,
    }


def setup_observation(tool, monkeypatch):
    setup_origin(tool, monkeypatch)
    rule = fact()
    tool.data["rule_publication"] = {"reference": ref()}
    host = {
        "rules": [{"ref": rule, "previous": None}],
        "operations": {
            "quality.capa.observation.record": {
                "allowed": False,
                "required_source_read_set": tool.reads(),
            }
        },
    }
    monkeypatch.setattr(tool, "host", lambda role: deepcopy(host))
    return host


@pytest.mark.parametrize("layout", ["stage", "real"])
def test_only_two_owned_layouts_no_parent_output_overlap(layout):
    root = Path("/tmp/pdos-next")
    folder = root / ".local/wave22-followup-control-staged" if layout == "stage" else root / "tools"
    check = (
        folder / "test_wave22_followup_control.py"
        if layout == "stage"
        else folder / "tests/test_wave22_followup_control.py"
    )
    assert m.layout_root(folder / "wave22_followup_control.py") == root
    assert owned_source(check) == (folder / "wave22_followup_control.py").resolve()
    assert m.CHECKPOINT != m.retest.CHECKPOINT
    assert m.PROFILE != m.retest.COMPLETION_PROFILE
    assert "effective" not in m.PHASES and "close" not in m.PHASES


def test_actual_dependencies_and_three_role_separation(tool):
    assert m.sha(m.ROOT / "tools/wave22_shared_retest.py") == m.RETEST_SHA
    assert len({tool.actor(role) for role in tool.foundation["actors"]}) == 3
    assert tool.key("same", "maker") != tool.key("same", "observer")
    with pytest.raises(m.Missing):
        tool.actor("borrow_owner_context")


def test_actual_fact_inputs_retains_command_and_complete_sources(tool):
    command = original(tool)
    actual = deepcopy(command)
    actual["source_read_set"].append(read(ref()))
    result = m.fact_inputs({"command": actual, "review": {"indeterminate": True}}, command)
    assert result["required_source_read_set"] == tool.h.merge_reads(actual["source_read_set"])
    assert len(result["required_source_read_set"]) == len(tool.reads()) + 1
    assert result["review"] == {"indeterminate": True}


@pytest.mark.parametrize(
    "field",
    ["command_id", "idempotency_key", "operation", "product_id", "expected_revision", "payload"],
)
def test_inputs_never_replaces_original_identity_or_material(tool, field):
    command = original(tool)
    changed = deepcopy(command)
    changed[field] = (
        {**changed[field], "reason": "Changed"}
        if field == "payload"
        else (
            5
            if field == "expected_revision"
            else "verification.request.create"
            if field == "operation"
            else "new-key"
            if field == "idempotency_key"
            else uid()
        )
    )
    with pytest.raises((m.Missing, ValidationError)):
        m.fact_inputs({"command": changed, "review": {}}, command)


@pytest.mark.parametrize("count", [0, 21])
def test_inputs_empty_or_over20_closure_rejects(tool, count):
    command = original(tool)
    changed = deepcopy(command)
    changed["source_read_set"] = [read(ref()) for _ in range(count)]
    with pytest.raises((m.Missing, ValidationError)):
        m.fact_inputs({"command": changed, "review": {}}, command)


def test_inputs_cannot_drop_original_source(tool):
    command = original(tool)
    changed = deepcopy(command)
    changed["source_read_set"] = [read(ref())]
    with pytest.raises(m.Missing):
        m.fact_inputs({"command": changed, "review": {}}, command)


@pytest.mark.parametrize(
    "mutate", ["extra", "missing_review", "invalid_review", "old_allowed_shape"]
)
def test_fact_inputs_requires_actual_envelope(tool, mutate):
    command = original(tool)
    response = {"command": command, "review": {}}
    if mutate == "extra":
        response["allowed"] = True
    elif mutate == "missing_review":
        del response["review"]
    elif mutate == "invalid_review":
        response["review"] = True
    else:
        response = {
            "operation": command["operation"],
            "allowed": True,
            "required_source_read_set": tool.reads(),
        }
    with pytest.raises(m.Missing):
        m.fact_inputs(response, command)


def test_every_read_union_over20_or_conflicting_revision_rejects(tool):
    with pytest.raises(RuntimeError, match="no truncation"):
        tool.reads([read(ref()) for _ in range(21)])
    value = read(ref())
    with pytest.raises(RuntimeError, match="Conflicting"):
        tool.reads([value], [{**value, "expected_revision": 2}])


def prepare_unknown_publication(tool, monkeypatch):
    def timeout(role, method, path, *, body=None, params=None):
        assert role == "maker" and method == "POST" and path == "/v1/commands"
        tool.calls.append((role, path, deepcopy(body)))
        raise httpx.ReadTimeout("Explicit transport substitute")

    monkeypatch.setattr(tool, "request", timeout)
    with pytest.raises(m.Unknown):
        tool.publication("rule-publication", "maker", lambda: blueprint(tool))
    return tool.data["requests"]["rule-publication"]


def test_native_publication_actual_t0_and_saved_receipt_precedes_fresh_factory(tool, monkeypatch):
    assert "evidence.artifact.register" not in T1_OPERATIONS | T2_OPERATIONS
    install_common(tool, monkeypatch)
    original_blueprint = blueprint(tool)
    result, saved_receipt, refs = tool.publication(
        "rule-publication", "maker", lambda: original_blueprint
    )
    assert len(tool.calls) == 1 and tool.calls[0][1] == "/v1/commands"
    saved = tool.data["requests"]["rule-publication"]
    assert saved["state"] == "saved" and "preview" not in saved
    assert result == original_blueprint
    assert refs[0]["artifact_id"] == saved_receipt["subject_id"]
    assert json.loads(refs[0]["quote"])["raw_value"] == "11.0000"
    assert json.loads(refs[0]["quote"])["nullable"] is None
    tool.live_revision = 99
    monkeypatch.setattr(tool, "request", lambda *a, **k: pytest.fail("No resend saved Receipt"))
    assert (
        tool.publication("rule-publication", "maker", lambda: pytest.fail("No new Plan/owner"))[1]
        == saved_receipt
    )


def test_unknown_publication_exact_body_key_version_recovery(tool, monkeypatch):
    saved = prepare_unknown_publication(tool, monkeypatch)
    fixed = deepcopy(saved["body"])
    assert saved["state"] == "unknown"
    assert "confirmation_token" not in fixed["payload"]
    tool.live_revision, tool.recover = 88, "rule-publication"
    install_common(tool, monkeypatch)
    tool.publication("rule-publication", "maker", lambda: pytest.fail("No fresh clock/owner"))
    assert tool.calls[-1] == ("maker", "/v1/commands", fixed)
    assert tool.recover_used is True


@pytest.mark.parametrize("which", ["blueprint", "body", "token", "role", "namespace"])
def test_tampered_publication_original_is_not_repaired(tool, monkeypatch, which):
    saved = prepare_unknown_publication(tool, monkeypatch)
    if which == "blueprint":
        tool.data["publications"]["rule-publication"]["value"]["rows"][0]["raw_value"] = "changed"
    elif which == "body":
        saved["body"]["expected_revision"] += 1
    elif which == "token":
        saved["body"]["payload"]["confirmation_token"] = "x" * 30
    elif which == "role":
        saved["role"] = "observer"
    else:
        tool.namespace = uid()
    with pytest.raises((m.Missing, ValidationError)):
        tool.publication("rule-publication", "maker", lambda: pytest.fail("No replacement"))
    assert len(tool.calls) == 1


def test_publication_existing_original_without_blueprint_blocks(tool):
    tool.data["requests"]["rule-publication"] = {"state": "unknown"}
    with pytest.raises(m.Missing, match="blueprint"):
        tool.publication("rule-publication", "maker", lambda: pytest.fail("No reconstruct"))


def test_rule_actual_typed_wanted_row_and_profile_no_qualification(tool, monkeypatch):
    row, fixed_origin = setup_origin(tool, monkeypatch)
    raw = rule_material(tool)
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    value = tool.prepare_rule_source(None)
    assert value["rows"][0]["material"]["origin"] == fixed_origin
    assert value["rows"][0]["scope"] == tool.data["scope"]
    assert value["profile"]["product_id"] == tool.product
    assert "sources" not in value["rows"][0]["material"]
    checked = RulePublicationInput.model_validate(value["chosen"])
    assert checked.sampling.observation_until >= datetime.fromisoformat(
        row["issue"]["capa"]["requirement"]["observation_until"]
    )
    assert "qualified" not in value["profile"] and "effective" not in value["chosen"]


@pytest.mark.parametrize("field", ["issue_id", "origin", "sources", "visibility"])
def test_rule_client_scope_and_anchor_rejected(tool, monkeypatch, field):
    setup_origin(tool, monkeypatch)
    raw = rule_material(tool)
    raw["payload"][field] = "client-value"
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    with pytest.raises(m.Missing, match="actual saved owner"):
        tool.prepare_rule_source(None)


def test_rule_interval_cannot_end_before_actual_capa_requirement(tool, monkeypatch):
    setup_origin(tool, monkeypatch)
    raw = rule_material(tool)
    raw["payload"]["sampling"]["observation_until"] = (
        datetime.now(UTC) + timedelta(minutes=2, seconds=30)
    ).isoformat()
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    with pytest.raises(m.Missing, match="shorten"):
        tool.prepare_rule_source(None)


def test_rule_promise_line_exact_real_plan_future_not_actual_start(tool, monkeypatch):
    setup_origin(tool, monkeypatch)
    raw = rule_material(tool)
    raw["include_promise"] = True
    now = datetime.now(UTC)
    run = {
        "status": "planned",
        "execution_plan": {
            "window": {
                "start": (now + timedelta(minutes=15)).isoformat(),
                "finish": (now + timedelta(minutes=25)).isoformat(),
                "original_timezone": "UTC",
            }
        },
    }
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(tool, "current", lambda family: ({}, {}, deepcopy(run)))
    value = tool.prepare_rule_source(None)
    assert set(value["rows"][1]) == {
        "request_id",
        "run_id",
        "purpose",
        "operation",
        "occurred_at",
        "executor_id",
    }
    assert value["rows"][1]["operation"] == "verification.schedule.promise"
    assert value["rows"][1]["executor_id"] == tool.actor("observer")
    run["execution_plan"]["window"]["start"] = (now - timedelta(minutes=1)).isoformat()
    with pytest.raises(m.Missing):
        tool.prepare_rule_source(None)


def test_observation_original_metadata_and_missing_null_not_completion(tool, monkeypatch):
    setup_observation(tool, monkeypatch)
    raw = observation_material()
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    value = tool.prepare_observation_source(None)
    assert value["chosen"]["records"][0]["raw_material"] == raw["records"][0]["raw_material"]
    assert value["rows"][0]["record"]["raw_material"]["temperature"] is None
    assert "sources" not in value["rows"][0]["record"]
    assert "observation_complete" not in value["chosen"]
    ObservationPayload.model_validate(value["chosen"])


@pytest.mark.parametrize(
    "which", ["raw_value_field", "future", "outside", "unknown_target", "bad_timezone"]
)
def test_observation_false_metadata_and_event_boundaries_reject(tool, monkeypatch, which):
    setup_observation(tool, monkeypatch)
    raw = observation_material()
    if which == "raw_value_field":
        raw["records"][0]["raw_value"] = "invented"
    elif which == "future":
        raw["at"]["occurred_at"] = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    elif which == "outside":
        raw["records"][0]["occurred_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    elif which == "unknown_target":
        raw["records"][0]["target_key"] = ""
    else:
        raw["records"][0]["original_timezone"] = "not/an/iana"
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    with pytest.raises((m.Missing, ValidationError)):
        tool.prepare_observation_source(None)


def test_observation_named_conclusions_exact_actual_projection_eight_keys(tool, monkeypatch):
    setup_observation(tool, monkeypatch)
    raw = observation_material()
    raw["named_run_conclusions"] = {
        "review_at": raw["at"]["occurred_at"],
        "review_text": "Actual named Observer proposal",
        "disposition_at": raw["at"]["occurred_at"],
        "disposition_text": "Actual named disposition",
    }
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    run = {"basis_sha256": "b" * 64, "current_projection": {"id": uid(), "basis_sha256": "b" * 64}}
    monkeypatch.setattr(tool, "current", lambda family: ({}, {}, deepcopy(run)))
    value = tool.prepare_observation_source(None)
    assert len(value["rows"]) == 3
    for line in value["rows"][1:]:
        assert set(line) == {
            "request_id",
            "run_id",
            "purpose",
            "operation",
            "actor_id",
            "occurred_at",
            "text",
            "basis_sha256",
        }
        assert line["actor_id"] == tool.actor("observer")
    run["current_projection"]["basis_sha256"] = "c" * 64
    with pytest.raises(m.Missing, match="Compute"):
        tool.prepare_observation_source(None)


def test_observation_actual_writer_observer_not_maker(tool, monkeypatch):
    install_common(tool, monkeypatch, "capa_observation")
    setup_observation(tool, monkeypatch)
    raw = observation_material()
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    tool.data["observation_payload"] = tool.prepare_observation_source(None)["chosen"]
    op = {"allowed": True, "required_source_read_set": tool.reads()}

    def host(role):
        if role != "observer":
            pytest.fail("Maker has no observation qualification in actual shared publication")
        return {"operations": {"quality.capa.observation.record": op}}

    monkeypatch.setattr(tool, "host", host)
    with pytest.raises(m.Pending):
        tool.observation()
    saved = tool.data["requests"]["observation"]
    assert saved["role"] == "observer" and saved["tier"] == "T1"
    assert "quality.capa.observation.record" in T1_OPERATIONS


def test_current_link_uses_paired_current_not_origin_or_old_draft(tool, monkeypatch):
    setup_origin(tool, monkeypatch)
    request = {"id": uid(), "revision": 9, "status": "verified"}
    run = {
        "run_snapshot": {
            "professional_conclusion": {"actual": True},
            "disposition": {"actual": True},
        }
    }
    option = {
        "logical_id": tool.data["request_id"],
        "ref": {"kind": "verification_request", "id": request["id"], "revision": 9, "key": None},
    }
    monkeypatch.setattr(tool, "current", lambda *a, **k: ({}, request, run))
    monkeypatch.setattr(
        tool,
        "request",
        lambda *a, **k: {
            "output_options": [option],
            "current": {"revision": 6},
            "required_source_read_set": tool.reads(),
        },
    )
    collected = []
    monkeypatch.setattr(tool, "step", lambda *a, **k: collected.append(a[4]()))
    tool.link_current()
    assert collected[0][0]["output_refs"] == [option["ref"]]
    option["ref"]["revision"] = 1
    with pytest.raises(m.Missing, match="no old Draft"):
        tool.link_current()


def test_named_review_unknown_is_actual_t2_not_effective_or_self_review(tool, monkeypatch):
    setup_origin(tool, monkeypatch)
    candidate, rule, observation = fact(), fact(), fact()
    selected_receipt = receipt(
        tool, "maker", "quality.capa.verification.candidate.record", "capa_verification_candidate"
    )
    selected_receipt["subject_id"] = candidate["id"]
    tool.data["receipts"]["candidate"] = selected_receipt
    source_ref = source()
    raw = {
        "schema_version": "wave22-followup-review-material-v1",
        "at": {
            "occurred_at": (datetime.now(UTC) - timedelta(seconds=30)).isoformat(),
            "original_timezone": "UTC",
            "source": source_ref,
        },
        "pair_applicability": [
            {
                "mapping": {
                    "failure_id": uid(),
                    "run": {"kind": "verification_run", "id": uid(), "revision": 4, "key": None},
                    "sample_id": uid(),
                    "sample_revision": 1,
                    "actual_configuration_id": uid(),
                    "actual_configuration_revision": 1,
                    "item_id": "dimension",
                    "measurement_id": uid(),
                    "projection_id": uid(),
                },
                "method": source_ref,
                "criterion": source_ref,
                "conclusion": "unknown",
                "reason": "Missing real applicable owner",
                "sources": [source_ref],
            }
        ],
        "action_fulfillment": [
            {
                "action_id": tool.data["capa_action_id"],
                "conclusion": "unknown",
                "reason": "No physical implementation claim",
                "sources": [source_ref],
            }
        ],
        "conclusion": "unknown",
        "sources": [source_ref],
        "reason": "Exact independent unresolved review",
    }
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(
        tool,
        "host",
        lambda role, candidate_id: (
            {
                "candidate": candidate,
                "rules": [{"ref": rule}],
                "observations": [observation],
                "operations": {
                    "quality.capa.verification.review": {
                        "allowed": True,
                        "required_source_read_set": tool.reads(),
                    }
                },
            }
            if role == "independent_reviewer"
            else pytest.fail("No Maker/Observer substitute")
        ),
    )
    install_common(tool, monkeypatch, "capa_named_verification_review", t2=True)
    with pytest.raises(m.Pending):
        tool.review()
    saved = tool.data["requests"]["independent-review"]
    checked = NamedReviewPayload.model_validate(saved["original"]["payload"])
    assert checked.conclusion == "unknown"
    assert saved["tier"] == "T2" and saved["role"] == "independent_reviewer"
    assert "quality.capa.verification.review" in T2_OPERATIONS
    assert "effectiveness" not in saved["original"]["payload"]
    tool.confirm, tool.review_digest = "independent-review", saved["review_digest"]
    monkeypatch.setattr(tool, "origin", lambda: pytest.fail("Saved original before fresh factory"))
    tool.review()
    assert tool.calls[-1][0] == "independent_reviewer"


def test_absent_real_review_owner_keeps_no_new_request(tool, monkeypatch):
    setup_origin(tool, monkeypatch)
    monkeypatch.setattr(
        tool,
        "material",
        lambda *a, **k: {
            "schema_version": "wave22-followup-review-material-v1",
            "at": {},
            "pair_applicability": [],
            "action_fulfillment": [],
            "conclusion": "unknown",
            "sources": [],
            "reason": "Blocked",
        },
    )
    tool.data["receipts"]["candidate"] = {"subject_id": uid()}
    monkeypatch.setattr(
        tool,
        "host",
        lambda *a, **k: {"operations": {"quality.capa.verification.review": {"allowed": False}}},
    )
    with pytest.raises(m.Missing, match="blocked"):
        tool.review()
    assert tool.data["requests"] == {}


def test_rule_exact_nested_sources_union_is_not_only_issue_reads(tool, monkeypatch):
    row, _ = setup_origin(tool, monkeypatch)
    raw = rule_material(tool)
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    actual = tool.prepare_rule_source(None)
    source_ref = raw["payload"]["method"]
    selected = {"artifact_id": source_ref["id"], "expected_revision": source_ref["revision"]}
    assert selected in actual["reads"]
    assert len(actual["reads"]) == len(row["required_source_read_set"]) + 1
    row["required_source_read_set"] = [read(ref()) for _ in range(20)]
    with pytest.raises(RuntimeError, match="no truncation"):
        tool.prepare_rule_source(None)


def test_rule_original_interval_cannot_be_moved_before_actual_completion(tool, monkeypatch):
    row, _ = setup_origin(tool, monkeypatch)
    raw = rule_material(tool)
    row["issue"]["capa"]["actions"][0]["completion"]["at"]["occurred_at"] = (
        datetime.now(UTC) + timedelta(minutes=3)
    ).isoformat()
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    with pytest.raises(m.Missing, match="precede actual completion"):
        tool.prepare_rule_source(None)


def test_native_observation_saved_original_recovery_does_not_replace_rule_or_clock(
    tool, monkeypatch
):
    setup_observation(tool, monkeypatch)
    raw = observation_material()
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    install_common(tool, monkeypatch)
    tool.observation_source()
    original_body = deepcopy(tool.data["requests"]["observation-publication"]["body"])
    original_payload = deepcopy(tool.data["observation_payload"])
    monkeypatch.setattr(tool, "origin", lambda: pytest.fail("No reconstruction before old Receipt"))
    monkeypatch.setattr(tool, "host", lambda *a, **k: pytest.fail("No replacement current Rule"))
    monkeypatch.setattr(tool, "material", lambda *a, **k: pytest.fail("No new observation clock"))
    tool.observation_source()
    assert len(tool.calls) == 1
    assert tool.data["requests"]["observation-publication"]["body"] == original_body
    assert tool.data["observation_payload"] == original_payload
    assert tool.calls[0][0] == "maker"


def test_observation_t1_unknown_retains_token_and_full_source_set(tool, monkeypatch):
    setup_observation(tool, monkeypatch)
    raw = observation_material()
    monkeypatch.setattr(tool, "material", lambda *a, **k: deepcopy(raw))
    tool.data["observation_payload"] = tool.prepare_observation_source(None)["chosen"]
    monkeypatch.setattr(
        tool,
        "host",
        lambda role: {
            "operations": {
                "quality.capa.observation.record": {
                    "allowed": True,
                    "required_source_read_set": tool.reads(),
                }
            }
        },
    )
    install_common(tool, monkeypatch, "capa_observation")
    with pytest.raises(m.Pending):
        tool.observation()
    saved = tool.data["requests"]["observation"]
    exact = deepcopy(saved["body"])
    tool.confirm, tool.review_digest = "observation", saved["review_digest"]
    monkeypatch.setattr(
        tool, "request", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("substitute"))
    )
    with pytest.raises(m.Unknown):
        tool.observation()
    assert saved["body"] == exact and len(exact["payload"]["confirmation_token"]) == 30
    tool.recover, tool.live_revision = "observation", 101
    install_common(tool, monkeypatch, "capa_observation")
    monkeypatch.setattr(tool, "host", lambda *a, **k: pytest.fail("No discard/replacement inputs"))
    tool.observation()
    assert tool.calls[-1] == ("observer", "/v1/commands", exact)
    assert saved["original"]["source_read_set"] == exact["source_read_set"]


@pytest.mark.parametrize("field", ["effectiveness", "qualified", "observation_complete"])
def test_explicit_material_flags_are_not_accepted(tool, monkeypatch, field):
    raw = observation_material()
    raw[field] = True
    monkeypatch.setattr(tool, "selected_material", lambda *a, **k: deepcopy(raw))
    with pytest.raises(m.Missing, match="Exact explicit"):
        tool.material(
            "observation-source",
            None,
            {
                "schema_version",
                "records",
                "observed_from",
                "observed_until",
                "at",
                "named_run_conclusions",
            },
            "wave22-followup-observation-material-v1",
        )


def test_parent_runtime_reload_triage_label_is_not_hard_required(tool, monkeypatch, tmp_path):
    from local_environment import read_state, verified

    assert callable(read_state) and callable(verified)  # inert import only
    foundation = deepcopy(tool.foundation)
    foundation["actors"]["maker"]["login_token"] = "NOT_A_TOKEN"
    parent = {
        "schema_version": "wave22-shared-retest-v3",
        "marker": tool.marker,
        "source_mode": "fresh",
        "fresh_generation": uid(),
        "first_generation": None,
        "scope": foundation["scope"],
        "foundation_sha256": "a" * 64,
        "build_sha256": "b" * 64,
        "case_id": uid(),
        "receipts": {
            label: {"explicit_substitute": True}
            for label in ("issue", "triage-runtime-reload-v1", "capa", "root-cause", "complete")
        },
        **{
            key: tool.data[key]
            for key in ("issue_id", "capa_id", "capa_action_id", "purpose", "request_id", "run_id")
        },
        "build_id": uid(),
        "first_run_id": uid(),
        "test_publication": tool.data["test_publication"],
    }
    before = deepcopy(parent)
    monkeypatch.setattr(m, "CHECKPOINT", tmp_path / "new-owned.json")
    monkeypatch.setattr(
        m.FollowupControl, "target", lambda self: {"preview_tenant_id": foundation["tenant_id"]}
    )
    monkeypatch.setattr(
        m.first,
        "private_json",
        lambda path: deepcopy(foundation) if path == m.first.FOUNDATION else deepcopy(tool.build),
    )
    monkeypatch.setattr(m.first, "foundation_contract", lambda raw, marker: deepcopy(raw))
    monkeypatch.setattr(
        m.first, "digest_file", lambda path: "a" * 64 if path == m.first.FOUNDATION else "b" * 64
    )
    monkeypatch.setattr(m.first, "build_foundation_binding", lambda *a: "c" * 64)
    monkeypatch.setattr(m.first, "build_contract", lambda raw, *a: deepcopy(raw))
    monkeypatch.setattr(
        m.retest,
        "checkpoint_json",
        lambda path: (
            deepcopy(parent)
            if path == m.retest.CHECKPOINT
            else pytest.fail("Only real selected parent")
        ),
    )
    monkeypatch.setattr(m.FollowupControl, "save", lambda self: None)
    value = m.FollowupControl(tool.marker, fresh_generation=parent["fresh_generation"])
    assert value.data["requests"] == {} and value.parent == before and parent == before
    assert "triage" not in value.parent["receipts"]
    assert value.data["case_id"] != value.parent["case_id"]
