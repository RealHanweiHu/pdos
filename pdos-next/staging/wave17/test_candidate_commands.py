"""Candidate payload/semantic checks only; no DB, current gates or fact writes."""

from copy import deepcopy
from types import SimpleNamespace

import candidate_commands as commands
import candidate_storage
import pytest
import test_anchor_lineage as examples
import test_candidate_storage as stored
from pdos_next.domain.capa_verification.schemas import CandidateBinding
from pdos_next.domain.capa_verification.service import basis_from_issue
from pdos_next.errors import DomainError
from pdos_next.service import digest
from pydantic import ValidationError


def material():
    """Explicit synthetic selections, never actual owner/Source qualifications."""
    origin = examples.origin_fixture().origin
    basis = basis_from_issue(
        SimpleNamespace(
            issue_id=origin.issue_id,
            id=origin.ref.id,
            revision=origin.ref.revision,
            tenant_id=origin.scope.tenant_id,
            product_id=origin.scope.product_id,
            project_id=origin.scope.project_id,
            purpose=origin.purpose,
            owner_id=origin.owner_id,
            visibility=origin.visibility,
            snapshot_sha256=origin.ref.snapshot_sha256,
        ),
        origin.issue,
        sources=origin.sources,
        reads=origin.required_source_read_set,
        source_basis=[v.model_dump(mode="json") for v in origin.source_basis],
    )
    mappings = [
        {
            "failure_id": basis.failure_ids[0],
            "run": {"kind": "verification_run", "id": str(examples.uid(f"run-{n}")), "revision": 4},
            "sample_id": str(examples.uid(f"sample-{n}")),
            "sample_revision": 1,
            "actual_configuration_id": str(examples.uid(f"actual-{n}")),
            "actual_configuration_revision": 1,
            "item_id": f"item-{n}",
            "measurement_id": None,
            "projection_id": None,
            "applicability_sources": [],
        }
        for n in (2, 1)
    ]
    links = [{"id": str(examples.uid(f"link-{n}")), "revision": 1} for n in (2, 1)]
    binding = CandidateBinding(basis=basis, remediation_link_refs=links, mappings=mappings)
    raw = {
        "issue_id": str(basis.issue_id),
        "expected_issue_revision": 10,
        "capa_id": str(basis.capa_id),
        "remediation_link_refs": deepcopy(links),
        "mappings": deepcopy(mappings),
        "sources": [
            {
                "artifact_id": str(examples.uid(f"source-{n}")),
                "expected_revision": 2,
                "line": n,
                "quote": f'Synthetic exact line {n}: 数据 {{"value":null}}',
            }
            for n in (2, 1)
        ],
        "reason": "Synthetic exact candidate selections",
    }
    return raw, binding


def rejected(code, action):
    with pytest.raises(DomainError) as caught:
        action()
    assert caught.value.code == code
    return caught.value


def test_actual_payload_has_exact_closed_fields_and_no_server_material_defaults():
    raw, _ = material()
    payload = commands.CandidateRecordPayload.model_validate(raw)
    assert set(commands.CandidateRecordPayload.model_fields) == {
        "issue_id",
        "expected_issue_revision",
        "capa_id",
        "remediation_link_refs",
        "mappings",
        "sources",
        "reason",
        "visibility",
        "confirmation_token",
    }
    semantic = commands.semantic(payload)
    assert set(semantic) == set(commands.CandidateRecordPayload.model_fields) - {
        "confirmation_token"
    }
    assert semantic["visibility"] == "private"
    assert (
        not {"stable_anchor", "binding", "inspection", "source_basis", "shared_proof"}
        & semantic.keys()
    )


@pytest.mark.parametrize(
    "extra",
    [
        "tenant_id",
        "product_id",
        "project_id",
        "owner_id",
        "actor_id",
        "purpose",
        "nature",
        "stable_anchor",
        "anchor_sha256",
        "candidate_binding",
        "binding_sha256",
        "inspection",
        "inspection_sha256",
        "source_basis",
        "shared_proof",
        "proof_id",
        "approval_token",
        "proof_consumed_at",
        "applicable",
        "current",
        "qualified",
        "independently_verified",
        "observation_complete",
        "pass",
        "original_clock",
    ],
)
def test_client_scope_or_positive_server_material_is_rejected(extra):
    raw, _ = material()
    raw[extra] = None
    with pytest.raises(ValidationError):
        commands.CandidateRecordPayload.model_validate(raw)


@pytest.mark.parametrize("revision", [True, False, 0, -1, "10", 10.0, None])
def test_expected_revision_is_strict_current_integer(revision):
    raw, _ = material()
    raw["expected_issue_revision"] = revision
    with pytest.raises(ValidationError):
        commands.semantic(raw)


def test_complete_json_semantics_preserve_selection_order_nulls_and_exact_values():
    raw, _ = material()
    before = deepcopy(raw)
    value = commands.semantic(raw)
    assert raw == before
    assert value["remediation_link_refs"] == raw["remediation_link_refs"]
    # OutputRef.key is a typed default, not guessed owner metadata.
    expected = deepcopy(raw["mappings"])
    for mapping in expected:
        mapping["run"]["key"] = None
    assert value["mappings"] == expected
    assert value["sources"] == raw["sources"]
    assert all(m["measurement_id"] is m["projection_id"] is None for m in value["mappings"])
    assert commands.semantic(commands.CandidateRecordPayload.model_validate(value)) == value
    reversed_value = deepcopy(raw)
    reversed_value["mappings"].reverse()
    assert digest(commands.semantic(reversed_value)) != digest(value)


def test_only_confirmation_token_is_removed_from_full_semantics():
    raw, _ = material()
    before = commands.semantic(raw)
    raw["confirmation_token"] = "synthetic-confirmation-token-001"
    assert commands.semantic(raw) == before
    raw["visibility"] = "product"
    assert commands.semantic(raw)["visibility"] == "product"
    assert digest(commands.semantic(raw)) != digest(before)


def test_empty_unknown_candidate_is_not_completed_with_pairs_or_sources():
    raw, _ = material()
    for name in ("remediation_link_refs", "mappings", "sources"):
        del raw[name]
    value = commands.semantic(raw)
    assert value["remediation_link_refs"] == value["mappings"] == value["sources"] == []
    assert value["visibility"] == "private"
    assert not {"observed_from", "received_at", "actual_start", "measurement_id"} & value.keys()


@pytest.mark.parametrize("field", ["remediation_link_refs", "mappings", "sources"])
def test_duplicate_exact_selections_are_rejected(field):
    raw, _ = material()
    raw[field].append(deepcopy(raw[field][0]))
    with pytest.raises(ValidationError):
        commands.semantic(raw)


def test_mapping_identity_cannot_repeat_with_forged_config_or_measurement():
    raw, _ = material()
    mapping = deepcopy(raw["mappings"][0])
    mapping["actual_configuration_id"] = str(examples.uid("another actual"))
    mapping["measurement_id"] = str(examples.uid("another measurement"))
    raw["mappings"].append(mapping)
    with pytest.raises(ValidationError):
        commands.semantic(raw)


@pytest.mark.parametrize("revision", [2, 0, True, "1"])
def test_link_ref_requires_actual_v1_strict_revision(revision):
    raw, _ = material()
    raw["remediation_link_refs"][0]["revision"] = revision
    with pytest.raises(ValidationError):
        commands.semantic(raw)


def test_different_source_positions_same_artifact_are_distinct_not_collapsed():
    raw, _ = material()
    second = deepcopy(raw["sources"][0])
    second.update(line=3, quote="Another actual line from same artifact")
    raw["sources"].append(second)
    assert commands.semantic(raw)["sources"] == raw["sources"]


@pytest.mark.parametrize(
    "field,limit", [("sources", 20), ("remediation_link_refs", 20), ("mappings", 10000)]
)
def test_declared_collection_limits_reject_instead_of_truncate(field, limit):
    raw, _ = material()
    raw[field] = [raw[field][0]] * (limit + 1)
    with pytest.raises(ValidationError):
        commands.semantic(raw)


def test_semantic_revalidates_mutated_child_and_model_construct_instead_of_trusting_class():
    raw, _ = material()
    payload = commands.CandidateRecordPayload.model_validate(raw)
    payload.sources[0].quote = ""
    with pytest.raises(ValidationError):
        commands.semantic(payload)
    raw["expected_issue_revision"] = True
    forged = commands.CandidateRecordPayload.model_construct(**raw)
    with pytest.raises(ValidationError):
        commands.semantic(forged)


def test_current_cas_is_not_confused_with_fixed_origin_revision():
    raw, binding = material()
    assert binding.basis.issue_revision == 9 and raw["expected_issue_revision"] == 10
    actual = commands.check_candidate_request(raw, binding, current_issue_revision=10)
    assert actual == binding
    # A caller's assertion of Current is not an owner authorization or a new ref.
    assert actual.basis.issue_revision == 9
    rejected(
        "VERSION_CONFLICT",
        lambda: commands.check_candidate_request(raw, binding, current_issue_revision=11),
    )


@pytest.mark.parametrize("current", [None, True, 0, "10", 10.0])
def test_actual_current_scalar_missing_or_coerced_is_not_authoritative(current):
    raw, binding = material()
    assert (
        rejected(
            "CANDIDATE_CURRENT_REVISION_REQUIRED",
            lambda: commands.check_candidate_request(raw, binding, current_issue_revision=current),
        ).status
        == 503
    )


@pytest.mark.parametrize("field", ["issue_id", "capa_id"])
def test_wrong_issue_or_capa_does_not_match_actual_binding(field):
    raw, binding = material()
    raw[field] = str(examples.uid(f"wrong {field}"))
    rejected(
        "CANDIDATE_REQUEST_BINDING_MISMATCH",
        lambda: commands.check_candidate_request(raw, binding, current_issue_revision=10),
    )


@pytest.mark.parametrize("field", ["remediation_link_refs", "mappings"])
def test_server_binding_must_keep_exact_choices_and_order(field):
    raw, binding = material()
    raw[field].reverse()
    rejected(
        "CANDIDATE_REQUEST_BINDING_MISMATCH",
        lambda: commands.check_candidate_request(raw, binding, current_issue_revision=10),
    )


def test_actual_binding_malformed_or_relabelled_failure_is_not_rebuilt():
    raw, binding = material()
    invalid = binding.model_dump(mode="json")
    invalid["mappings"][0]["failure_id"] = "not an original failure"
    rejected(
        "CANDIDATE_ACTUAL_BINDING_REQUIRED",
        lambda: commands.check_candidate_request(raw, invalid, current_issue_revision=10),
    )


def test_sources_reason_and_requested_visibility_are_not_pure_permission_checks():
    raw, binding = material()
    raw.update(sources=[], reason="A new explicit reason", visibility="product")
    assert commands.check_candidate_request(raw, binding, current_issue_revision=10) == binding
    # This result is just the structural binding, no allowed/qualified/current
    # or max-audience proof. Actual Root source/lineage/write owner is still needed.
    assert not hasattr(binding, "authorized")


def test_explicit_semantic_owner_uses_actual_module_schema_and_reader_contract():
    owner = commands.semantic_owner()
    assert owner.payload_type is commands.CandidateRecordPayload
    assert owner.module is commands and owner.semantic is commands.semantic
    assert owner.module.OPERATION == candidate_storage.OPERATION
    assert not hasattr(commands, "apply") and not hasattr(commands, "validate")


def test_actual_new_semantic_owner_can_revalidate_exact_reader_wrapper(monkeypatch):
    upstream = stored.work.__wrapped__(monkeypatch)
    work = next(upstream)
    try:
        row = work.candidate
        raw = {
            "issue_id": str(row.issue_id),
            "expected_issue_revision": row.issue_revision,
            "capa_id": str(row.capa_id),
            "reason": row.reason,
            "visibility": "product",
        }
        value = commands.semantic(raw)
        row.input_snapshot["semantic"] = value
        row.intent_digest = digest(
            {
                "operation": commands.OPERATION,
                "product": row.product_id,
                "payload": value,
                "named_actor": row.writer_id,
                "source_revision": None,
                "private_owner": None,
            }
        )
        work.candidate_receipt.intent_digest = row.intent_digest
        work.candidate_proof.payload_digest = digest(
            {
                "tenant": row.tenant_id,
                "actor": row.writer_id,
                "requester": row.writer_id,
                "operation": commands.OPERATION,
                "product": row.product_id,
                "expected_revision": work.candidate_proof.revision,
                "read_set": sorted(
                    row.required_source_read_set,
                    key=lambda r: (r["artifact_id"], r["expected_revision"]),
                ),
                "payload": value,
            }
        )
        result = candidate_storage.read_candidate(
            work.s, work.ctx, work.pid, row.id, semantic_owner=commands.semantic_owner()
        )
        assert result.body.semantic == value
        assert not result.current_evidence_authorized and not result.same_uow_consumption_attested
        assert result.ref.sha256 not in {row.binding_sha256, row.inspection_sha256}
    finally:
        try:
            next(upstream)
        except StopIteration:
            pass
