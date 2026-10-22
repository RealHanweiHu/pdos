"""Real owner assembly over no-connect SQL/original and explicit host IO fixtures.

No fixture attests PG/RLS, external qualification, actual recipient signatures or
network delivery. The callback is an explicit low-level host verification stub.
"""

from copy import copy, deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from manufacturing_preparation.test_publication_material_owner import (
    world as native_world,  # noqa: F401
)
from manufacturing_preparation.test_publication_rules import case as publication_case  # noqa: F401
from manufacturing_trials.test_native_statistics_owner import original
from sqlalchemy import select

from pdos_next.domain.external_handoff import evidence_owner as owner
from pdos_next.domain.external_handoff.evidence_schemas import HandoffContract
from pdos_next.domain.external_handoff.schemas import (
    AuthorizePayload,
    Destination,
    ManifestFile,
    NumberMapping,
    OriginalRef,
    ReceiptOriginal,
)
from pdos_next.domain.projects.models import Project
from pdos_next.domain.release.schemas import SubjectConfiguration, VersionRef
from pdos_next.errors import DomainError
from pdos_next.models import Artifact
from pdos_next.schemas.verification.contracts import Scope
from pdos_next.service import digest


@pytest.fixture
def work(request, monkeypatch):
    world = request.getfixturevalue("native_world")
    # These columns are supplied by the real database defaults/scope trigger.
    world.project.category_id = world.ctx.category_id
    world.project.created_at = datetime.now(UTC) - timedelta(minutes=1)
    s, execute = world.s, world.s.execute

    def columns(statement, *args, **kwargs):
        descriptions = statement.column_descriptions
        models = {value["entity"] for value in descriptions}
        if len(models) != 1 or descriptions[0]["expr"] is descriptions[0]["entity"]:
            return execute(statement, *args, **kwargs)
        model = next(iter(models))
        rows = s.scalars(select(model).where(*statement._where_criteria))
        return SimpleNamespace(
            mappings=lambda: [
                {column.key: getattr(row, column.key) for column in statement.selected_columns}
                for row in rows
            ]
        )

    monkeypatch.setattr(s, "execute", columns)
    scope = Scope(tenant_id=world.ctx.tenant_id, product_id=world.pid, project_id=world.project.id)
    source = OriginalRef.model_validate(
        original(world, {"fixture": "actual registered native file"}).model_dump(mode="json")
    )
    file = ManifestFile(
        artifact={"id": source.id, "revision": source.revision},
        logical_name="manifest.json",
        content_sha256=s.get(Artifact, source.id).content_hash,
        external_number="ERP-DOC-1",
        external_version="1",
        sources=(source,),
    )
    config = SubjectConfiguration(
        definition={
            "id": world.engineering.definition_id,
            "revision": world.engineering.definition_revision,
        },
        engineering_configuration={
            "id": world.engineering.id,
            "revision": world.engineering.revision,
        },
        manufacturing_configuration={"id": world.process.id, "revision": world.process.revision},
    )
    mapping = NumberMapping(
        ref={"kind": "engineering_configuration", **config.engineering_configuration.model_dump()},
        external_number="ERP-ENG-1",
        external_version="1",
        sources=(source,),
    )
    material = HandoffContract(
        schema_version="pdos-external-handoff-contract-v1",
        scope=scope,
        category_id=world.ctx.category_id,
        subject_config=config,
        purpose=world.project.purpose,
        destination={"system": "erp-fixture", "recipient_id": "receiver-1"},
        release_scope={"quantity": "2", "unit": "ea"},
        required_mapping_refs=(mapping.ref,),
        required_manifest_refs=(file.artifact,),
        mappings=(mapping,),
        files=(file,),
    )
    contract_source = OriginalRef.model_validate(
        original(world, material.model_dump(mode="json")).model_dump(mode="json")
    )
    payload = AuthorizePayload(
        project_id=world.project.id,
        package={"id": uuid4(), "revision": 1},
        engineering_decision={"id": uuid4(), "revision": 1},
        manufacturing_decision={"id": uuid4(), "revision": 1},
        subject_config=config,
        release_scope=material.release_scope,
        purpose=material.purpose,
        destination=material.destination,
        external_id="delivery-1",
        mappings=(mapping,),
        manifest=(file,),
        sources=(contract_source,),
        reason="read actual registered handoff contract",
    )
    reader = owner.ActualHandoffEvidenceOwner(s.get_bind())
    s.get_bind()._pdos_external_handoff = SimpleNamespace(evidence_owner=reader)
    result = SimpleNamespace(**vars(world))
    result.__dict__.update(
        scope=scope,
        source=source,
        file=file,
        mapping=mapping,
        material=material,
        payload=payload,
        reader=reader,
        contract_source=contract_source,
        expected={str(contract_source.id): material},
        calls=[],
        bad=None,
    )

    def verify(s, ctx, pid, challenge):
        result.calls.append(challenge.kind)
        assert challenge.kind in {"contract", "receipt"}
        assert challenge.scope == scope and challenge.category_id == world.ctx.category_id
        assert challenge.material == result.expected[str(challenge.source.id)]
        actual = s.get(Artifact, challenge.source.id)
        assert challenge.source_metadata["sha256"] == actual.content_hash == digest(actual.content)
        if result.bad is not None:
            return result.bad(challenge)
        return challenge.attest()

    result.verify = verify
    result.configure = lambda **kwargs: owner.configure_issuer(
        s.get_bind(),
        key="actual-io-fixture",
        version="v1",
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        destination=material.destination,
        verify=verify,
        **kwargs,
    )
    result.read = lambda: reader.read_contract(s, result.ctx, result.pid, result.payload)
    return result


def rejects(call, reason):
    with pytest.raises(DomainError) as error:
        call()
    assert error.value.reason == reason


def receipt_source(work):
    value = ReceiptOriginal(
        schema_version="pdos-external-receipt-v1",
        handoff={"id": uuid4(), "revision": 1},
        intent={"id": uuid4(), "revision": 1},
        destination=work.material.destination,
        external_id="delivery-1",
        manifest_sha256="a" * 64,
        release_scope=work.material.release_scope,
        stage="accepted",
        outcome="succeeded",
        external_receipt_id="ERP-RCPT-1",
        occurred_at=work.project.created_at,
    )
    source = OriginalRef.model_validate(
        original(work, value.model_dump(mode="json")).model_dump(mode="json")
    )
    work.expected[str(source.id)] = value
    return source, value


def test_default_is_unknown_contract_and_no_trusted_receipt_path(work):
    result = work.read()
    assert result.contract_read is None and result.required_mapping_refs is None
    assert result.gaps == ("HANDOFF_CONTRACT_OWNER_UNCONNECTED",)
    assert result.files == result.mappings == ()
    source, _ = receipt_source(work)
    rejects(
        lambda: work.reader.read_receipt(
            work.s, work.ctx, work.pid, source, project_id=work.project.id
        ),
        "INTEGRATION_REQUIRED",
    )
    assert work.calls == []


def test_actual_registered_contract_and_files_read_once_with_opaque_scope(work):
    work.configure()
    result = work.read()
    assert result.contract_read is True
    assert result.required_mapping_refs == (work.mapping.ref,)
    assert result.files == (work.file,)
    assert result.required_manifest_refs == (work.file.artifact,)
    assert set(result.source_basis["artifact_sources"]) == {
        str(work.contract_source.id),
        str(work.source.id),
    }
    count = len(work.s.queries)
    assert work.read() is result and len(work.s.queries) == count
    assert work.calls == ["contract"]
    assert work.reader.current(work.s, work.ctx, work.pid, result) is True
    assert work.calls == ["contract"]
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, replace(result)),
        "FACT_CALLER_UOW_CHANGED",
    )


def test_configured_host_without_contract_preserves_current_unknown_material(work):
    work.configure()
    work.payload = work.payload.model_copy(update={"sources": (work.source,)})
    result = work.read()
    assert result.contract_read is None and result.required_manifest_refs is None
    assert result.gaps == ("HANDOFF_CONTRACT_ORIGINAL_MISSING",)
    assert work.reader.current(work.s, work.ctx, work.pid, result) is True
    assert work.calls == []


def test_fixed_native_object_value_changes_stale_direct_binding(work):
    work.configure()
    result = work.read()
    work.s.rollback()
    work.s.begin()
    work.engineering.design_versions = {"changed": "actual native object value"}
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, result.source_basis), "SOURCE_STALE"
    )


@pytest.mark.parametrize("return_value", [True, {"trusted": True}, "hash", None])
def test_callback_dto_bool_or_hash_does_not_supply_actual_proof(work, return_value):
    work.bad = lambda challenge: return_value
    work.configure()
    rejects(work.read, "INTEGRATION_REQUIRED")


def test_proof_is_same_challenge_only_and_cannot_be_copied(work):
    proofs = []

    def capture(challenge):
        proof = challenge.attest()
        proofs.append(proof)
        with pytest.raises(TypeError):
            copy(proof)
        return proof

    work.bad = capture
    work.configure()
    work.read()
    source, _ = receipt_source(work)
    work.bad = lambda challenge: proofs[0]
    rejects(
        lambda: work.reader.read_receipt(
            work.s, work.ctx, work.pid, source, project_id=work.project.id
        ),
        "INTEGRATION_REQUIRED",
    )


@pytest.mark.parametrize("fault", ["hash", "config", "destination", "project"])
def test_contract_and_manifest_cannot_escape_actual_content_or_scope(work, fault):
    work.configure()
    material = work.material
    if fault == "hash":
        material = material.model_copy(
            update={"files": (work.file.model_copy(update={"content_sha256": "f" * 64}),)}
        )
    elif fault == "config":
        material = material.model_copy(
            update={
                "subject_config": material.subject_config.model_copy(
                    update={"definition": VersionRef(id=uuid4(), revision=1)}
                )
            }
        )
    elif fault == "destination":
        material = material.model_copy(
            update={"destination": Destination(system="other", recipient_id="other")}
        )
    else:
        material = material.model_copy(
            update={"scope": material.scope.model_copy(update={"project_id": uuid4()})}
        )
    source = OriginalRef.model_validate(
        original(work, material.model_dump(mode="json")).model_dump(mode="json")
    )
    work.payload = work.payload.model_copy(update={"sources": (source,)})
    rejects(work.read, "SOURCE_STALE" if fault == "hash" else "FORBIDDEN_SCOPE")


def test_receipt_original_uses_distinct_host_verification_and_real_sources(work):
    work.configure()
    source, material = receipt_source(work)
    result = work.reader.read_receipt(
        work.s, work.ctx, work.pid, source, project_id=work.project.id
    )
    assert result.original == material
    assert result.issuer.system == material.destination.system
    assert result.issuer_current is result.sources_current is True
    assert work.calls == ["receipt"]
    assert (
        work.reader.read_receipt(work.s, work.ctx, work.pid, source, project_id=work.project.id)
        is result
    )
    assert work.reader.current(work.s, work.ctx, work.pid, result) is True
    assert work.calls == ["receipt"]


def test_receipt_issuer_selection_and_cache_bind_the_authorized_project(work):
    first_issuer = work.configure()
    second_project = work.s.add_row(
        Project(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            product_id=work.pid,
            owner_id=work.ctx.requester_id,
            visibility="private",
            purpose=work.project.purpose,
            scope="second exact project",
            status="active",
            revision=1,
            created_at=work.project.created_at,
        )
    )
    first_source, first_material = receipt_source(work)
    second_source, second_material = receipt_source(work)
    second_calls = []

    def second_verify(s, ctx, pid, challenge):
        second_calls.append(challenge.source.id)
        assert challenge.scope.project_id == second_project.id
        if challenge.source != second_source or challenge.material != second_material:
            raise DomainError("FORBIDDEN_SCOPE", "Original is not registered for this project", 403)
        return challenge.attest()

    second_issuer = owner.configure_issuer(
        work.s.get_bind(),
        key="second-project-same-destination",
        version="v1",
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=second_project.id,
        destination=work.material.destination,
        verify=second_verify,
    )
    first = work.reader.read_receipt(
        work.s, work.ctx, work.pid, first_source, project_id=work.project.id
    )
    second = work.reader.read_receipt(
        work.s, work.ctx, work.pid, second_source, project_id=second_project.id
    )
    assert first.original == first_material and first.issuer.key == first_issuer.key
    assert second.original == second_material and second.issuer.key == second_issuer.key
    assert first.source_basis["scope"]["project_id"] == str(work.project.id)
    assert second.source_basis["scope"]["project_id"] == str(second_project.id)
    assert (
        work.reader.read_receipt(
            work.s, work.ctx, work.pid, first_source, project_id=work.project.id
        )
        is first
    )
    assert work.calls == ["receipt"] and second_calls == [second_source.id]
    # Same source/caller/UOW under another project must reach that project's
    # actual verifier; it cannot reuse the first project's cached opaque read.
    rejects(
        lambda: work.reader.read_receipt(
            work.s, work.ctx, work.pid, first_source, project_id=second_project.id
        ),
        "FORBIDDEN_SCOPE",
    )
    assert second_calls == [second_source.id, first_source.id]
    assert work.reader.current(work.s, work.ctx, work.pid, first) is True
    assert work.reader.current(work.s, work.ctx, work.pid, second) is True


def test_receipt_cannot_borrow_another_projects_only_issuer_or_private_scope(work):
    other_project = work.s.add_row(
        Project(
            id=uuid4(),
            tenant_id=work.ctx.tenant_id,
            category_id=work.ctx.category_id,
            product_id=work.pid,
            owner_id=uuid4(),
            visibility="private",
            purpose=work.project.purpose,
            scope="another private project",
            status="active",
            revision=1,
            created_at=work.project.created_at,
        )
    )
    source, _ = receipt_source(work)
    calls = []
    owner.configure_issuer(
        work.s.get_bind(),
        key="only-another-project",
        version="v1",
        tenant_id=work.ctx.tenant_id,
        product_id=work.pid,
        project_id=other_project.id,
        destination=work.material.destination,
        verify=lambda *args: calls.append(True),
    )
    rejects(
        lambda: work.reader.read_receipt(
            work.s, work.ctx, work.pid, source, project_id=work.project.id
        ),
        "INTEGRATION_REQUIRED",
    )
    rejects(
        lambda: work.reader.read_receipt(
            work.s, work.ctx, work.pid, source, project_id=other_project.id
        ),
        "FORBIDDEN_SCOPE",
    )
    assert calls == []


def test_current_uses_metadata_not_bytes_or_verifier_and_rejects_withdrawal(work):
    work.configure()
    result = work.read()
    work.s.rollback()
    work.s.begin()
    count = len(work.s.queries)
    assert work.reader.current(work.s, work.ctx, work.pid, deepcopy(result.source_basis)) is True
    assert work.calls == ["contract"]
    for query in work.s.queries[count:]:
        if (
            len(query.column_descriptions) == 1
            and query.column_descriptions[0]["expr"] is query.column_descriptions[0]["entity"]
        ):
            continue
        assert all(column.key != "content" for column in query.selected_columns)
    work.s.rollback()
    work.s.begin()
    work.s.get(Artifact, work.source.id).status = "withdrawn"
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, result.source_basis),
        "SOURCE_UNAVAILABLE",
    )


def test_revoke_or_reconfigure_advances_live_epoch_and_stales_old_material(work):
    issuer = work.configure()
    result = work.read()
    owner.revoke_issuer(work.s.get_bind(), issuer.key)
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, result.source_basis), "SOURCE_STALE"
    )
    replacement = work.configure()
    assert replacement.epoch > issuer.epoch
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, result.source_basis), "SOURCE_STALE"
    )


def test_additional_watermark_requires_real_current_callback(work):
    work.bad = lambda challenge: challenge.attest({"external_revision": 1})
    work.configure()
    rejects(work.read, "INTEGRATION_REQUIRED")
    actual = {"external_revision": 1}
    work.configure(current=lambda *args: deepcopy(actual))
    result = work.read()
    assert work.reader.current(work.s, work.ctx, work.pid, result) is True
    actual["external_revision"] = 2
    rejects(
        lambda: work.reader.current(work.s, work.ctx, work.pid, result.source_basis), "SOURCE_STALE"
    )


def test_synthetic_configuration_requires_actual_test_target_verification(work, monkeypatch):
    values = dict(
        key="isolated-only",
        version="v1",
        tenant_id=work.scope.tenant_id,
        product_id=work.pid,
        project_id=work.scope.project_id,
        destination=work.material.destination,
        verify=work.verify,
    )
    calls = []
    monkeypatch.setattr(owner, "verify_test_target", lambda engine: calls.append(engine))
    with pytest.raises(ValueError):
        owner.configure_local_synthetic(work.s.get_bind(), **values, enabled=True)
    assert calls == []
    issuer = owner.configure_local_synthetic(
        work.s.get_bind(), **values, enabled=True, test_marker_verified=True
    )
    assert calls == [work.s.get_bind()] and issuer.nature == "synthetic"
