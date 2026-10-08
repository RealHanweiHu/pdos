"""No connections: real DTO/publication parser/configuration; fake foundation material."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import wave22_shared_authority as tool

AT = (datetime.now(UTC) - timedelta(minutes=2)).replace(microsecond=123456)


def checkpoint():
    maker, observer, reviewer = (uuid4() for _ in range(3))
    product, project, artifact = (uuid4() for _ in range(3))
    raw = {
        "schema_version": "wave21-shared-foundation-v1",
        "phase": "foundation_saved_not_build_started",
        "marker": "exact-marker",
        "case_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "product_id": str(product),
        "project_id": str(project),
        "purpose": "新共享合成调查：实际三人、非生产资格",
        "visibility": "product",
        "created_at": (AT - timedelta(minutes=1)).isoformat(),
        "bootstrap_expires_at": (AT + timedelta(days=2)).isoformat(),
        "actors": {
            role: {"id": str(identity), "login_token": "never copied to projection"}
            for role, identity in zip(tool.ROLES, (maker, observer, reviewer), strict=True)
        },
        "scope": {},
        "receipts": {},
    }
    raw["scope"] = {key: raw[key] for key in ("tenant_id", "product_id", "project_id")}
    for label, (operation, family) in tool.FOUNDATION_OPERATIONS.items():
        identity = {"product": product, "project": project, "native-source": artifact}.get(
            label, uuid4()
        )
        # Real receipt revisions need not be 1: no invented Definition/BOM version.
        revision = 4 if label == "definition" else 2 if label == "native-source" else 1
        raw["receipts"][label] = {
            "id": str(uuid4()),
            "operation": operation,
            "subject_type": family,
            "subject_id": str(identity),
            "subject_revision": revision,
            "writer_id": str(maker),
            "requester_id": str(maker),
            "created_at": AT.isoformat(),
            "result": {"id": str(identity), "revision": revision, "status": "active"},
        }
    raw["sources"] = {
        "foundation": {
            "required_source_read_set": [{"artifact_id": str(artifact), "expected_revision": 2}]
        }
    }
    raw["readback"] = {
        role: {
            "shared_objects": 6,
            "stored_content_hash": "a" * 64,
            "raw_text_sha256": "b" * 64,
            "professional_qualification": None,
        }
        for role in tool.ROLES
    }
    return raw


def basis():
    return tool.foundation_basis(checkpoint(), marker="exact-marker", at=AT)


def plan():
    fixed = basis()
    return fixed, tool.publications(fixed, issued_at=AT, valid_until=AT + timedelta(days=1))


def old_profile(family):
    scope = {"tenant_id": str(uuid4()), "product_id": str(uuid4())}
    if family == "professional":
        return {**scope, "key": "legacy-professional", "version": "v1"}
    return {
        **scope,
        "project_id": str(uuid4()),
        "issuer_key": "legacy-quality",
        "issuer_version": "v1",
    }


def test_foundation_projection_uses_exact_versions_and_never_copies_login_material():
    raw = checkpoint()
    fixed = tool.foundation_basis(raw, marker="exact-marker", at=AT)
    assert fixed.source_revision == 2
    assert fixed.source_content_hash == "a" * 64
    assert fixed.source_text_sha256 == "b" * 64
    assert fixed.material()["receipts"]["definition"]["subject_revision"] == 4
    assert "login_token" not in tool.canonical(fixed.material())
    assert all("login_token" in row for row in raw["actors"].values())


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "phase",
        "marker",
        "private",
        "same-actor",
        "scope",
        "receipt",
        "receipt-bool",
        "source",
        "readback",
        "readback-raw",
        "readback-qualified",
        "legacy-readback",
        "source-bool",
        "expiry",
        "future",
    ],
)
def test_incomplete_or_nonshared_foundation_is_never_a_structural_import_basis(kind):
    raw = checkpoint()
    if kind == "missing":
        raw["receipts"].pop("manufacturing")
    elif kind == "phase":
        raw["phase"] = "allocated_not_bootstrapped"
    elif kind == "marker":
        raw["marker"] = "other-marker"
    elif kind == "private":
        raw["visibility"] = "private"
    elif kind == "same-actor":
        raw["actors"]["independent_reviewer"]["id"] = raw["actors"]["maker"]["id"]
    elif kind == "scope":
        raw["scope"]["project_id"] = str(uuid4())
    elif kind == "receipt":
        raw["receipts"]["project"]["requester_id"] = str(uuid4())
    elif kind == "receipt-bool":
        raw["receipts"]["product"]["result"]["revision"] = True
    elif kind == "source":
        raw["sources"]["foundation"]["required_source_read_set"][0]["expected_revision"] = 1
    elif kind == "readback":
        raw["readback"]["observer"]["stored_content_hash"] = "b" * 64
    elif kind == "readback-raw":
        raw["readback"]["observer"]["raw_text_sha256"] = "a" * 64
    elif kind == "readback-qualified":
        raw["readback"]["observer"]["professional_qualification"] = True
    elif kind == "legacy-readback":
        for row in raw["readback"].values():
            row["source_sha256"] = row.pop("stored_content_hash")
            row.pop("raw_text_sha256")
    elif kind == "source-bool":
        raw["receipts"]["native-source"]["subject_revision"] = 1
        raw["receipts"]["native-source"]["result"]["revision"] = 1
        raw["sources"]["foundation"]["required_source_read_set"][0]["expected_revision"] = True
    elif kind == "expiry":
        raw["bootstrap_expires_at"] = AT.isoformat()
    elif kind == "future":
        raw["created_at"] = (AT + timedelta(seconds=1)).isoformat()
    with pytest.raises(tool.Blocked):
        tool.foundation_basis(raw, marker="exact-marker", at=AT)


def test_twelve_real_fact_dtos_are_split_and_review_has_only_its_own_operation():
    fixed, publication = plan()
    identity = uuid4()
    facts, policy = tool.bound_payloads(publication, identity, 3)
    assert len(facts) == 12 and len(publication["lines"]) == 14
    for entry in facts:
        payload = entry["payload"]
        assert 1 <= len(payload["operations"]) <= 10
        assert payload["product_id"] == str(fixed.product_id)
        assert payload["project_id"] == str(fixed.project_id)
        assert payload["purposes"] == [fixed.purpose]
        assert payload["sources"][0]["expected_revision"] == 3
        line = tool.strict_json(payload["sources"][0]["quote"])
        assert line["issuer"]["nature"] == "synthetic"
        assert line["tenant_id"] == str(fixed.tenant_id)
        assert line["fact"]["subject_id"] == payload["subject_id"]
        assert line["fact"]["operations"] == payload["operations"]
        assert ".123456" in line["fact"]["approval"]["issued_at"]
    reviewer = [
        entry["payload"]
        for entry in facts
        if entry["payload"]["subject_id"] == str(fixed.actor("independent_reviewer"))
    ]
    assert len(reviewer) == 2
    assert {p["kind"] for p in reviewer} == {"duty", "qualification"}
    assert all(
        p["role"] == "quality" and p["operations"] == ["quality.capa.verification.review"]
        for p in reviewer
    )
    assert policy["risk"] == "high" and policy["independent_verification"] is True
    assert len({p["payload"]["external_id"] for p in facts}) == 12
    assert len({ref["artifact_id"] for entry in facts for ref in entry["payload"]["sources"]}) == 1
    assert all(ref["artifact_id"] == str(identity) for ref in policy["sources"])


def test_actual_policy_original_json_parser_accepts_exact_publication_and_rejects_changed_risk(
    monkeypatch,
):
    from pdos_next.domain.quality_execution import policy as actual
    from pdos_next.domain.quality_execution.schemas import PolicyInput
    from pdos_next.errors import DomainError

    fixed, publication = plan()
    _, raw = tool.bound_payloads(publication, uuid4(), 1)
    source = SimpleNamespace(content="\n".join(publication["lines"]))
    monkeypatch.setattr(actual, "source_for", lambda *args: source)
    data = PolicyInput.model_validate(raw)
    # Actual parser, source/ACL reader explicitly substituted; this is not a saved policy.
    actual._publication(None, None, data)
    row = tool.strict_json(publication["lines"][12])
    row["risk"] = "low"
    source.content = "\n".join(
        [*publication["lines"][:12], tool.canonical(row), publication["lines"][13]]
    )
    with pytest.raises(DomainError) as error:
        actual._publication(None, None, data)
    assert error.value.code == "MISSING_REQUIRED_EVIDENCE"
    assert fixed.purpose == data.purpose


@pytest.mark.parametrize("family", ["professional", "quality"])
def test_actual_new_profile_keeps_original_explicit_list_order_and_opaque_identity(
    monkeypatch, family
):
    fixed = basis()
    original = [old_profile(family)]
    before = deepcopy(original)
    configured = tool.append_profile(original, tool.profiles_for(fixed)[family], family=family)
    assert original == before and configured[:-1] == before
    engine = SimpleNamespace()
    if family == "professional":
        from pdos_next.domain.professional_authority.service import (
            configure_local_synthetic_profiles,
        )

        (old,) = configure_local_synthetic_profiles(engine, original, enabled=True)
        values = configure_local_synthetic_profiles(engine, configured, enabled=True)
    else:
        from pdos_next import quality_bootstrap

        monkeypatch.setattr(quality_bootstrap, "verify_test_target", lambda _: None)
        (old,) = quality_bootstrap.configure_local_profiles(engine, original)
        values = quality_bootstrap.configure_local_profiles(engine, configured)
    assert values[0] is old and old.epoch == 1
    assert values[1].product_id == fixed.product_id
    assert values[1].key != old.key


@pytest.mark.parametrize("family", ["professional", "quality"])
@pytest.mark.parametrize("kind", ["tuple", "empty", "capacity", "same-key", "same-scope", "extra"])
def test_profile_conflicts_do_not_create_expanded_or_default_old_scope(family, kind):
    fixed = basis()
    new = tool.profiles_for(fixed)[family]
    previous = [old_profile(family)]
    if kind == "tuple":
        previous = tuple(previous)
    elif kind == "empty":
        previous = []
    elif kind == "capacity":
        previous = [old_profile(family) for _ in range(20)]
    elif kind == "same-key":
        previous[0]["key" if family == "professional" else "issuer_key"] = new[
            "key" if family == "professional" else "issuer_key"
        ]
    elif kind == "same-scope":
        previous[0] = {**new, ("key" if family == "professional" else "issuer_key"): "different"}
    elif kind == "extra":
        previous[0]["qualified"] = True
    before = deepcopy(previous)
    with pytest.raises(tool.Blocked):
        tool.append_profile(previous, new, family=family)
    assert previous == before


@pytest.mark.parametrize("material", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_original_json_never_uses_last_duplicate_or_nonfinite_value(material):
    with pytest.raises(tool.Blocked):
        tool.strict_json(material)


def test_private_files_require_owned_0600_and_do_not_overwrite_symlink_target(tmp_path):
    source = tmp_path / "list.json"
    source.write_text('[{"explicit":true}]')
    source.chmod(0o644)
    with pytest.raises(tool.Blocked):
        tool.private_read(source)
    source.chmod(0o600)
    assert tool.private_read(source) == [{"explicit": True}]
    link = tmp_path / "link.json"
    link.symlink_to(source)
    with pytest.raises(tool.Blocked):
        tool.private_write(link, [])
    assert source.read_text() == '[{"explicit":true}]'


def test_saved_publication_reconstruction_preserves_fixed_clock_and_refuses_scope_change():
    from pdos_next.contracts import Command

    fixed, publication = plan()
    owner = tool.AuthorityTool.__new__(tool.AuthorityTool)
    owner.basis = fixed
    owner.data = {
        "plan": publication,
        "source_command": Command(
            command_id=tool.uuid5(fixed.case_id, "wave22:authority-source"),
            idempotency_key=f"wave22-{fixed.case_id}-authority-source",
            operation="evidence.artifact.register",
            product_id=fixed.product_id,
            expected_revision=9,
            payload={
                "title": "Wave22 shared synthetic professional/policy publication",
                "content": "\n".join(publication["lines"]),
                "visibility": "product",
                "source_label": "Controlled local synthetic publication; no production grant",
            },
        ).model_dump(mode="json"),
    }
    owner.validate_saved_plan()
    issued = owner.data["plan"]["issued_at"]
    owner.data["plan"]["facts"][0]["payload"]["subject_id"] = str(fixed.actor("observer"))
    with pytest.raises(tool.Blocked, match="SAVED_PUBLICATION_MATERIAL_CHANGED"):
        owner.validate_saved_plan()
    assert owner.data["plan"]["issued_at"] == issued


def test_fixed_validity_cannot_extend_foundation_or_be_renewed_at_import():
    fixed = basis()
    with pytest.raises(tool.Blocked):
        tool.publications(fixed, issued_at=AT, valid_until=fixed.expires_at + timedelta(seconds=1))
    with pytest.raises(tool.Blocked):
        tool.publications(fixed, issued_at=AT, valid_until=AT)


def test_bool_source_revision_is_rejected_before_any_persistent_factory():
    _, publication = plan()
    with pytest.raises(tool.Blocked):
        tool.bound_payloads(publication, uuid4(), True)


def test_saved_command_watermark_never_accepts_bool_revision():
    from pdos_next.contracts import Command

    fixed, publication = plan()
    owner = tool.AuthorityTool.__new__(tool.AuthorityTool)
    owner.basis = fixed
    owner.data = {
        "plan": publication,
        "source_command": Command(
            command_id=tool.uuid5(fixed.case_id, "wave22:authority-source"),
            idempotency_key=f"wave22-{fixed.case_id}-authority-source",
            operation="evidence.artifact.register",
            product_id=fixed.product_id,
            expected_revision=9,
            payload={
                "title": "Wave22 shared synthetic professional/policy publication",
                "content": "\n".join(publication["lines"]),
                "visibility": "product",
                "source_label": "Controlled local synthetic publication; no production grant",
            },
        ).model_dump(mode="json"),
    }
    owner.data["source_command"]["expected_revision"] = True
    with pytest.raises(tool.Blocked, match="EXACT_REVISION_REQUIRED"):
        owner.validate_saved_plan()


def test_unfinished_foundation_refuses_before_runtime_verification(monkeypatch):
    import sys

    def forbid():
        pytest.fail("unfinished foundation must not reach environment verification")

    monkeypatch.setitem(
        sys.modules, "local_environment", SimpleNamespace(read_state=forbid, verified=forbid)
    )
    unfinished = checkpoint()
    unfinished["phase"] = "allocated_not_bootstrapped"
    monkeypatch.setattr(tool, "private_read", lambda _: unfinished)
    with pytest.raises(tool.Blocked, match="ACTUAL_SHARED_FOUNDATION_REQUIRED"):
        tool.AuthorityTool("exact-marker")
