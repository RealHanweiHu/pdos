"""No connections: readback field contract and refusal paths, not actual eligibility."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest
import wave22_authority_readback as reader
import wave22_shared_authority as authority
from test_wave22_shared_authority import AT, basis, plan


@pytest.fixture(autouse=True)
def no_connections(monkeypatch):
    import httpx
    import psycopg
    from sqlalchemy.engine import Engine

    def refuse(*args, **kwargs):
        pytest.fail("Only offline readback field checks are authorized")

    monkeypatch.setattr(Engine, "connect", refuse)
    monkeypatch.setattr(Engine, "raw_connection", refuse)
    monkeypatch.setattr(httpx.Client, "request", refuse)
    monkeypatch.setattr(psycopg, "connect", refuse)


def saved_owner():
    from pdos_next.contracts import Command

    fixed, publication = plan()
    owner = authority.AuthorityTool.__new__(authority.AuthorityTool)
    owner.basis = fixed
    owner.data = {
        "state": "synthetic_facts_saved_root_reload_required",
        "plan": publication,
        "source_command": Command(
            command_id=uuid5(fixed.case_id, "wave22:authority-source"),
            idempotency_key=f"wave22-{fixed.case_id}-authority-source",
            product_id=fixed.product_id,
            expected_revision=9,
            operation="evidence.artifact.register",
            payload={
                "title": "Wave22 shared synthetic professional/policy publication",
                "content": "\n".join(publication["lines"]),
                "visibility": "product",
                "source_label": "Controlled local synthetic publication; no production grant",
            },
        ).model_dump(mode="json"),
        "receipts": {},
    }
    for label in [
        *(row["label"] for row in publication["facts"]),
        "quality-policy",
        "authority-source",
    ]:
        op = (
            "evidence.artifact.register"
            if label == "authority-source"
            else reader.POLICY
            if label == "quality-policy"
            else reader.PROFESSIONAL
        )
        family = "artifact" if label == "authority-source" else reader.FAMILIES[op]
        subject = str(uuid4())
        owner.data["receipts"][label] = {
            "id": str(uuid4()),
            "operation": op,
            "subject_type": family,
            "subject_id": subject,
            "subject_revision": 1,
            "writer_id": str(fixed.actor("maker")),
            "requester_id": str(fixed.actor("maker")),
            "created_at": AT.isoformat(),
            "result": {"id": subject, "revision": 1, "status": "active"},
        }
    return owner


def atom():
    owner = saved_owner()
    b = owner.basis
    label = owner.data["plan"]["facts"][0]["label"]
    saved = owner.data["receipts"][label]
    receipt = SimpleNamespace(
        id=UUID(saved["id"]),
        tenant_id=b.tenant_id,
        product_id=b.product_id,
        actor_id=b.actor("maker"),
        requester_id=b.actor("maker"),
        visibility="product",
        run_id=None,
        command_id=uuid5(b.case_id, "wave22:" + label),
        operation=reader.PROFESSIONAL,
        subject_type=reader.FAMILIES[reader.PROFESSIONAL],
        subject_id=UUID(saved["subject_id"]),
        subject_revision=1,
        created_at=AT,
        result=deepcopy(saved["result"]),
        request_digest="f" * 64,
    )
    common = {"tenant_id": b.tenant_id, "receipt_id": receipt.id, "actor_id": receipt.actor_id}
    audit = SimpleNamespace(id=uuid4(), operation=reader.PROFESSIONAL, **common)
    outbox = SimpleNamespace(
        id=uuid4(),
        type=reader.EVENTS[reader.PROFESSIONAL],
        subject_id=receipt.subject_id,
        subject_revision=1,
        correlation_id=receipt.command_id,
        schema_version=1,
        delivered_at=None,
        attempts=0,
        **common,
    )
    key = SimpleNamespace(
        id=uuid4(), key=f"wave22-{b.case_id}-{label}", digest=receipt.request_digest, **common
    )
    return owner, label, saved, receipt, [audit], [outbox], [key]


def test_fourteen_exact_receipt_views_include_thirteen_imports_but_no_login_data():
    owner = saved_owner()
    rows = reader.checkpoint_material(owner)
    assert len(rows) == 14
    assert sum(row["operation"] == reader.PROFESSIONAL for row in rows.values()) == 12
    assert sum(row["operation"] == reader.POLICY for row in rows.values()) == 1
    assert "login_token" not in authority.canonical(rows)


@pytest.mark.parametrize("fault", ["missing", "bool", "wrong-writer", "same-receipt", "unimported"])
def test_checkpoint_never_replaces_actual_complete_import_groups(fault):
    owner = saved_owner()
    keys = list(owner.data["receipts"])
    if fault == "missing":
        owner.data["receipts"].pop(keys[0])
    elif fault == "bool":
        owner.data["receipts"][keys[0]]["result"]["revision"] = True
    elif fault == "wrong-writer":
        owner.data["receipts"][keys[0]]["writer_id"] = str(uuid4())
    elif fault == "same-receipt":
        owner.data["receipts"][keys[1]]["id"] = owner.data["receipts"][keys[0]]["id"]
    elif fault == "unimported":
        owner.data["state"] = "publication_saved_profiles_reload_required"
    with pytest.raises(authority.Blocked):
        reader.checkpoint_material(owner)


def test_actual_common_orm_field_family_has_exact_command_key_actor_and_event():
    owner, label, saved, receipt, audits, events, keys = atom()
    result = reader.assert_group(
        receipt, saved, audits, events, keys, basis=owner.basis, label=label
    )
    assert result["receipt_id"] == str(receipt.id)
    # Delivery may legitimately advance; it is outside the immutable business atom.
    events[0].delivered_at = AT + timedelta(minutes=1)
    events[0].attempts = 5
    assert (
        reader.assert_group(receipt, saved, audits, events, keys, basis=owner.basis, label=label)
        == result
    )


@pytest.mark.parametrize(
    "fault",
    [
        "tenant",
        "actor",
        "correlation",
        "key",
        "digest",
        "event",
        "bool-revision",
        "bool-schema",
        "missing-audit",
        "extra-event",
    ],
)
def test_common_group_field_mismatches_cannot_be_called_saved_proofs(fault):
    owner, label, saved, receipt, audits, events, keys = atom()
    if fault == "tenant":
        audits[0].tenant_id = uuid4()
    elif fault == "actor":
        receipt.requester_id = uuid4()
    elif fault == "correlation":
        events[0].correlation_id = uuid4()
    elif fault == "key":
        keys[0].key = "other-key"
    elif fault == "digest":
        keys[0].digest = "0" * 64
    elif fault == "event":
        events[0].type = "product.created"
    elif fault == "bool-revision":
        events[0].subject_revision = True
    elif fault == "bool-schema":
        events[0].schema_version = True
    elif fault == "missing-audit":
        audits = []
    elif fault == "extra-event":
        events = events * 2
    with pytest.raises(authority.Blocked):
        reader.assert_group(receipt, saved, audits, events, keys, basis=owner.basis, label=label)


def assessment(allowed):
    b = basis()
    op = "quality.capa.verification.review" if allowed else "test.results.import"
    return (
        b,
        op,
        {
            "scope": {
                "tenant_id": str(b.tenant_id),
                "product_id": str(b.product_id),
                "project_id": str(b.project_id),
            },
            "subject_id": str(b.actor("independent_reviewer")),
            "operation": op,
            "purpose": b.purpose,
            "synthetic": True,
            "authorized": allowed,
            "qualified": True if allowed else None,
            "roles": ["quality"] if allowed else [],
            "reason_codes": []
            if allowed
            else ["PROFESSIONAL_DUTY_REQUIRED", "PROFESSIONAL_QUALIFICATION_REQUIRED"],
            "fact_refs": [{"id": str(uuid4()), "nature": "synthetic"}],
            "required_source_read_set": [{"artifact_id": str(uuid4()), "expected_revision": 1}],
            "facts_revision": "a" * 64,
        },
    )


def test_reviewer_expected_set_is_only_review_plus_explicit_all_other_op_denials():
    calls = reader.expected_assessments(basis())
    own = [(op, role) for who, op, role, allow in calls if who == "independent_reviewer" and allow]
    assert own == [("quality.capa.verification.review", "quality")]
    denied = {op for who, op, _, allow in calls if who == "independent_reviewer" and not allow}
    assert denied == {
        op for _, who, _, ops in authority.GROUPS if who != "independent_reviewer" for op in ops
    }
    assert {"test.results.import", "test.run.start", "quality.capa.observation.record"} <= denied


def test_professional_denial_requires_real_missing_duty_not_access_or_source_failure():
    b, op, value = assessment(False)
    assert (
        reader.assert_assessment(value, b, "independent_reviewer", op, None, False)["qualified"]
        is None
    )
    value["reason_codes"].append("SOURCE_UNAVAILABLE")
    with pytest.raises(authority.Blocked):
        reader.assert_assessment(value, b, "independent_reviewer", op, None, False)


@pytest.mark.parametrize(
    "fault", ["qualified", "scope", "authorized-int", "non-synthetic", "no-source"]
)
def test_actual_assessment_flags_do_not_substitute_for_source_scope_and_current_qualification(
    fault,
):
    b, op, value = assessment(True)
    if fault == "qualified":
        value["qualified"] = None
    elif fault == "scope":
        value["scope"]["project_id"] = str(uuid4())
    elif fault == "authorized-int":
        value["authorized"] = 1
    elif fault == "non-synthetic":
        value["synthetic"] = False
    elif fault == "no-source":
        value["required_source_read_set"] = []
    with pytest.raises(authority.Blocked):
        reader.assert_assessment(value, b, "independent_reviewer", op, "quality", True)


def test_driver_guard_refuses_business_dml_flush_and_commit_without_a_connection():
    owner = reader.Readback.__new__(reader.Readback)
    owner.counts = {"select": 0, "set": 0, "business_dml": 0, "flush": 0, "commit": 0}
    for sql in ("SELECT 1", "SET LOCAL statement_timeout='30s'"):
        owner.driver_guard(None, None, sql, None, None, None)
    for sql in (
        "UPDATE products SET revision=1",
        "INSERT INTO x VALUES (1)",
        "WITH x AS (DELETE FROM products) SELECT * FROM x",
    ):
        with pytest.raises(authority.Blocked):
            owner.driver_guard(None, None, sql, None, None, None)
    with pytest.raises(authority.Blocked):
        owner.no_flush()
    with pytest.raises(authority.Blocked):
        owner.no_commit()
    assert owner.counts == {"select": 1, "set": 1, "business_dml": 3, "flush": 1, "commit": 1}


def test_runtime_epoch_mutation_is_rejected_even_with_same_opaque_object_identity():
    fixed = basis()
    engine = SimpleNamespace(_pdos_professional_synthetic=True)
    owner = reader.Readback.__new__(reader.Readback)
    owner.engine = engine
    for registry, epochs in (
        ("_pdos_professional_issuers", "_pdos_professional_issuer_epochs"),
        ("_pdos_quality_policy_issuers", "_pdos_quality_policy_epochs"),
    ):
        objects = {
            key: SimpleNamespace(
                key=key,
                version="v1",
                epoch=1,
                tenant_id=fixed.tenant_id,
                product_id=uuid4(),
                project_id=uuid4(),
            )
            for key in ("old", "new")
        }
        setattr(engine, registry, objects)
        setattr(engine, epochs, {"old": 1, "new": 1})
    initial = owner.runtime_stamp()
    assert owner.runtime_stamp() == initial
    engine._pdos_professional_issuer_epochs["new"] = 2
    with pytest.raises(authority.Blocked):
        owner.runtime_stamp()


def test_current_assessment_must_include_exact_review_only_fact_pair_and_full_source():
    owner = saved_owner()
    role = "independent_reviewer"
    expected = []
    for entry in owner.data["plan"]["facts"]:
        payload = entry["payload"]
        if payload["subject_id"] != str(owner.basis.actor(role)):
            continue
        saved = owner.data["receipts"][entry["label"]]
        expected.append(
            {
                "id": saved["subject_id"],
                "revision": 1,
                "epoch": 1,
                "kind": payload["kind"],
                "role": payload["role"],
                "nature": "synthetic",
                "issuer_key": owner.data["plan"]["profiles"]["professional"]["key"],
                "issuer_version": "v1",
            }
        )
    source = owner.data["receipts"]["authority-source"]
    value = {
        "fact_refs": list(reversed(expected)),
        "required_source_read_set": [{"artifact_id": source["subject_id"], "expected_revision": 1}],
    }
    reader.assert_assessment_refs(value, owner, role)
    original = deepcopy(value)
    value["fact_refs"].append({**expected[0], "id": str(uuid4())})
    with pytest.raises(authority.Blocked):
        reader.assert_assessment_refs(value, owner, role)
    value = original
    value["required_source_read_set"][0]["expected_revision"] = True
    with pytest.raises(authority.Blocked):
        reader.assert_assessment_refs(value, owner, role)


def publication_rows(kind):
    """Transient real ORM rows, built with actual importer DTOs; no saved truth is claimed."""
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.domain.professional_authority.models import ProfessionalCurrent, ProfessionalFact
    from pdos_next.domain.professional_authority.schemas import FactInput
    from pdos_next.domain.quality_execution import policy
    from pdos_next.domain.quality_execution.models import QualityPolicyCurrent, QualityPolicyFact
    from pdos_next.domain.quality_execution.schemas import PolicyInput

    owner = saved_owner()
    source = owner.data["receipts"]["authority-source"]
    facts, policy_payload = authority.bound_payloads(
        owner.data["plan"], source["subject_id"], source["subject_revision"]
    )
    payload = deepcopy(facts[0]["payload"] if kind == "professional" else policy_payload)
    # The publication checkpoint legitimately has UTC offsets and omitted DTO defaults.
    for key in ("valid_from", "valid_until"):
        payload[key] = payload[key].replace("Z", "+00:00")
    payload["approval"]["issued_at"] = payload["approval"]["issued_at"].replace("Z", "+00:00")
    payload["approval"]["approved_by"] = "Root 本地合成 publisher; no production grant"
    payload.pop("previous_id")
    payload.pop("expected_previous_revision")
    data = (FactInput if kind == "professional" else PolicyInput).model_validate(payload)
    normalized = data.model_dump(mode="json")
    b = owner.basis
    issuer = SimpleNamespace(
        key=(
            owner.data["plan"]["profiles"]["professional"]["key"]
            if kind == "professional"
            else owner.data["plan"]["profiles"]["quality"]["issuer_key"]
        ),
        version="v1",
        nature="synthetic",
        epoch=1,
    )
    identity = uuid4()
    common = {
        "id": identity,
        "tenant_id": b.tenant_id,
        "product_id": b.product_id,
        "project_id": b.project_id,
        "owner_id": b.actor("maker"),
        "visibility": "product",
        "nature": "synthetic",
        "issuer_key": issuer.key,
        "issuer_version": issuer.version,
        "external_id": data.external_id,
        "revision": 1,
        "previous_id": None,
        "previous_revision": None,
        "series_id": identity,
        "valid_from": data.valid_from,
        "valid_until": data.valid_until,
        "sources": normalized["sources"],
        "required_source_read_set": [
            {"artifact_id": source["subject_id"], "expected_revision": source["subject_revision"]}
        ],
        "reason": data.reason,
    }
    pointer = {
        "id": uuid4(),
        "tenant_id": b.tenant_id,
        "product_id": b.product_id,
        "project_id": b.project_id,
        "series_id": identity,
        "fact_id": identity,
        "fact_revision": 1,
        "epoch": 1,
        "issuer_key": issuer.key,
        "external_id": data.external_id,
    }
    if kind == "professional":
        row = ProfessionalFact(
            **common,
            subject_id=data.subject_id,
            kind=data.kind,
            role=data.role,
            operations=data.operations,
            purposes=data.purposes,
            state=data.state,
            source_basis={
                "approval": normalized["approval"],
                "evidence": [],
                "import_digest": professional.digest(
                    [issuer.key, issuer.version, issuer.nature, normalized]
                ),
            },
        )
        row.fact_sha256 = professional.digest(professional._material(row))
        current = ProfessionalCurrent(**pointer, subject_id=data.subject_id, kind=data.kind)
    else:
        row = QualityPolicyFact(
            **common,
            purpose=data.purpose,
            risk=data.risk,
            independent_verification=data.independent_verification,
            status=data.state,
            issuer_epoch=issuer.epoch,
            data=normalized,
            source_basis={"approval": normalized["approval"], "sources": []},
        )
        row.fact_sha256 = policy.digest(policy._material(row))
        current = QualityPolicyCurrent(**pointer, purpose=data.purpose)
    return b, issuer, payload, row, current


@pytest.mark.parametrize("kind", ["professional", "policy"])
def test_actual_importer_normalization_preserves_complete_utc_defaults_and_material_hash(kind):
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.domain.quality_execution import policy

    b, issuer, raw, row, current = publication_rows(kind)
    normalized = reader.normalized_publication_payload(raw, kind)
    assert raw["approval"]["issued_at"].endswith("+00:00")
    assert normalized["approval"]["issued_at"].endswith("Z")
    assert "previous_id" not in raw and normalized["previous_id"] is None
    assert normalized["expected_previous_revision"] == 0
    assert authority.canonical(raw) != authority.canonical(normalized)
    module = professional if kind == "professional" else policy
    before = module.digest(module._material(row))
    reader.assert_publication_rows(row, current, raw, basis=b, issuer=issuer, kind=kind)
    assert row.fact_sha256 == before
    assert module.digest(module._material(row)) == before
    if kind == "professional":
        assert row.source_basis["import_digest"] == professional.digest(
            [issuer.key, issuer.version, issuer.nature, normalized]
        )
        assert row.source_basis["import_digest"] != professional.digest(
            [issuer.key, issuer.version, issuer.nature, raw]
        )
    else:
        assert row.data == normalized


@pytest.mark.parametrize("kind", ["professional", "policy"])
@pytest.mark.parametrize("fault", ["source", "approval", "full-material-hash", "default-bool"])
def test_typed_normalization_does_not_relax_exact_source_approval_hash_or_strict_previous(
    kind, fault
):
    from pydantic import ValidationError

    b, issuer, raw, row, current = publication_rows(kind)
    if fault == "source":
        raw["sources"][0]["quote"] += " changed"
    elif fault == "approval":
        raw["approval"]["approved_by"] = "another signer"
    elif fault == "full-material-hash":
        row.fact_sha256 = "0" * 64
    else:
        raw["expected_previous_revision"] = False
    with pytest.raises((authority.Blocked, ValidationError)):
        reader.assert_publication_rows(row, current, raw, basis=b, issuer=issuer, kind=kind)


def test_professional_import_digest_cannot_be_replaced_by_raw_checkpoint_digest():
    from pdos_next.domain.professional_authority import service as professional

    b, issuer, raw, row, current = publication_rows("professional")
    row.source_basis["import_digest"] = professional.digest(
        [issuer.key, issuer.version, issuer.nature, raw]
    )
    row.fact_sha256 = professional.digest(professional._material(row))
    with pytest.raises(authority.Blocked, match="IMPORTED_PROFESSIONAL_MATERIAL_MISMATCH"):
        reader.assert_publication_rows(
            row, current, raw, basis=b, issuer=issuer, kind="professional"
        )


def test_actual_professional_domain_digest_differs_from_the_common_receipt_digest():
    from pdos_next.domain.professional_authority import service as professional
    from pdos_next.professional_import import digest as wrapper_digest
    from pdos_next.service import digest as common_digest

    b, issuer, raw, row, current = publication_rows("professional")
    normalized = reader.normalized_publication_payload(raw, "professional")
    # Chinese source text and aware datetime fields exercise the two real encoders.
    assert any(ord(c) > 127 for c in normalized["approval"]["approved_by"])
    assert professional.digest(professional._material(row)) != common_digest(
        professional._material(row)
    )
    assert professional.digest([issuer.key, issuer.version, issuer.nature, normalized]) != (
        common_digest([issuer.key, issuer.version, issuer.nature, normalized])
    )
    reader.assert_publication_rows(row, current, raw, basis=b, issuer=issuer, kind="professional")
    row.fact_sha256 = common_digest(professional._material(row))
    with pytest.raises(authority.Blocked, match="IMPORTED_PROFESSIONAL_MATERIAL_MISMATCH"):
        reader.assert_publication_rows(
            row, current, raw, basis=b, issuer=issuer, kind="professional"
        )
    # Actual host Receipt uses the common encoder, not the professional fact encoder.
    fingerprint = {
        "operation": reader.PROFESSIONAL,
        "product": b.product_id,
        "actor": b.actor("maker"),
        "issuer": [issuer.key, issuer.version, issuer.nature],
        "payload": normalized,
    }
    assert wrapper_digest(fingerprint) == common_digest(fingerprint)
    assert wrapper_digest(fingerprint) != professional.digest(fingerprint)
