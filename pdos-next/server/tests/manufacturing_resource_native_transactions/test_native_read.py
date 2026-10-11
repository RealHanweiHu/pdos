"""One Root-run native Source -> actual Current -> owner -> authenticated HTTP case.

No success mock, Source/ACL bypass, time substitution or entity seeding is used.
The host synthetic issuer declares only a resource mirror/Build relationship;
native named T2 acceptance/calibration/qualification remain unknown.
"""

from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts import service as operational
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.manufacturing_resource_owner import owner
from pdos_next.domain.manufacturing_resource_owner.schemas import ResourceView
from pdos_next.models import Artifact, Audit, Outbox, Receipt, now
from pdos_next.service import digest

from .fixtures import SOURCE_TEXT, observe_direct_named_verifier, read_effect_hashes


@pytest.mark.parametrize("native_resource_case", ["no_deadline"], indirect=True)
def test_ordinary_fact_without_deadline_remains_current_for_the_execution_window(
    native_resource_case,
):
    case = native_resource_case
    setup, request = case.setup, case.request
    before = read_effect_hashes(case.work)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        category_id=setup.category,
    ) as session:
        read = owner.inspect_resource(session, setup.ctx, setup.product, request=request)
        assert read.view.current and read.view.state == "known"
        assert read.view.fact_valid_until is None
        assert read.view.valid_until == request.execution.window.finish
        assert owner.refresh_resource(session, setup.ctx, setup.product, read).view == read.view
    assert read_effect_hashes(case.work) == before


def test_native_source_current_owner_refresh_and_authenticated_post_have_no_effects(
    native_resource_case,
):
    case, work = native_resource_case, native_resource_case.work
    setup, request = case.setup, case.request
    endpoint = (
        f"/v1/categories/{setup.category}/products/{setup.product}"
        f"/builds/{request.build.id}/resources/inspect"
    )
    body = {
        "project_id": str(request.scope.project_id),
        "expected_build_revision": request.build.revision,
        "process": request.process.model_dump(mode="json"),
        "execution": request.execution.model_dump(mode="json"),
        "operation_key": request.operation_key,
    }
    assert setup.engine._pdos_change_store is case.store
    issuer_identity, callback_identity = work.issuer, work.issuer.verify_named_decision
    registry_epoch = deepcopy(setup.engine._pdos_operational_issuer_epochs)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
    ) as session:
        fact = session.get(BuildOperationalFact, UUID(case.receipt["subject_id"]))
        pointer = session.scalar(
            select(BuildOperationalCurrent).where(
                BuildOperationalCurrent.tenant_id == setup.tenant,
                BuildOperationalCurrent.product_id == setup.product,
                BuildOperationalCurrent.build_id == request.build.id,
            )
        )
        assert fact is not None and pointer is not None
        assert (pointer.fact_id, pointer.fact_revision, pointer.epoch) == (
            fact.id,
            fact.revision,
            1,
        )
        assert fact.build_id == request.build.id and fact.build_revision == request.build.revision
        assert fact.project_id == request.scope.project_id and fact.owner_id == setup.human
        assert (
            fact.visibility == "private" and fact.nature == "synthetic" and fact.state == "active"
        )
        assert fact.data["resources"][0]["facts"] == [] and fact.data["materials"] == []
        assert fact.data["materials_scope_complete"] is False
        assert fact.valid_from == work.at - timedelta(minutes=10)
        assert fact.valid_until == work.at + timedelta(minutes=30)
        assert fact.binding["scope"] == request.execution.model_dump(mode="json")
        assert fact.fact_sha256 == operational._fact_hash(fact)
        expected_reads = deepcopy(fact.required_source_read_set)
        fact_id, fact_revision, fact_sha = fact.id, fact.revision, fact.fact_sha256
        fact_deadline = fact.valid_until
        assert {UUID(value["artifact_id"]) for value in expected_reads} == {
            UUID(work.config["source"]),
            case.native_source_id,
        }
        assert len(expected_reads) == 2
        for read in expected_reads:
            source = session.get(Artifact, UUID(read["artifact_id"]))
            assert source.original_id is None and source.visibility == "private"
            assert source.owner_id == setup.human and source.content_hash == digest(source.content)
            assert source.revision == read["expected_revision"] == 1
            provenance = evidence._native_registration(session, setup.ctx, setup.product, source)
            assert provenance["source_origin"] == "registered_native_text"
            assert provenance["registration_requester_id"] == str(setup.human)
            assert provenance["registration_actor_kind"] == "human"
            receipt_id = UUID(provenance["registration_receipt_id"])
            for model in (Audit, Outbox):
                assert (
                    len(list(session.scalars(select(model).where(model.receipt_id == receipt_id))))
                    == 1
                )
        native = session.get(Artifact, case.native_source_id)
        assert native.content == SOURCE_TEXT
        import_receipt = session.get(Receipt, UUID(case.receipt["id"]))
        assert import_receipt.operation == "build.operational_facts.import"
        assert import_receipt.actor_id == import_receipt.requester_id == setup.human
        for model in (Audit, Outbox):
            assert (
                len(
                    list(
                        session.scalars(select(model).where(model.receipt_id == import_receipt.id))
                    )
                )
                == 1
            )
        assert list(session.scalars(select(MaterialHold))) == []
        assert list(session.scalars(select(ResourceOccupancy))) == []
        asset = session.get(OperationalAsset, work.resource_id)
        assert asset.revision == 1 and asset.occupancy_epoch == 1

    baseline = read_effect_hashes(work)
    with observe_direct_named_verifier(work.issuer) as calls:
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            prepared = owner.inspect_resource(session, setup.ctx, setup.product, request=request)
            refreshed = owner.refresh_resource(session, setup.ctx, setup.product, prepared)
            assert prepared.view == refreshed.view
            assert prepared.view.valid_until == refreshed.view.valid_until
            assert prepared.view.valid_until <= request.execution.window.finish
            assert prepared.view.fact_valid_until == fact_deadline
            assert set(prepared.source_basis) == {value["artifact_id"] for value in expected_reads}
            assert all(
                value["source_origin"] == "registered_native_text"
                for value in prepared.source_basis.values()
            )
            direct = prepared.view.model_dump(mode="json")
    assert calls == {"named_verifier": 0, "inspect_resource": 2, "refresh_resource": 1}
    assert read_effect_hashes(work) == baseline

    assert now() < request.execution.window.finish
    response = setup.client.post(endpoint, headers=setup.headers, json=body)
    assert response.status_code == 200, response.text
    view = ResourceView.model_validate(response.json())
    assert response.json() == direct
    assert view.request.scope.tenant_id == setup.tenant
    assert view.request.scope.product_id == setup.product and view.request.build == request.build
    assert view.state == "known" and view.current is True and view.nature == "synthetic"
    assert (view.fact.id, view.fact.revision, view.fact_sha256) == (
        fact_id,
        fact_revision,
        fact_sha,
    )
    assert [
        read.model_dump(mode="json") for read in view.required_source_read_set
    ] == expected_reads
    assert view.execution_authorized is False and view.negative_enumeration_complete is False
    assert len(view.resources) == len(view.relations) == 1
    resource, relation = view.resources[0], view.relations[0]
    assert resource.resource.id == work.resource_id and resource.current is True
    assert resource.acceptance == resource.calibration == resource.qualification == "unknown"
    assert relation.build == request.build and relation.process == request.process
    assert relation.operation_key == "assembly" and relation.units == 1
    assert relation.relation_source.kind == "domain"
    assert (relation.relation_source.id, relation.relation_source.revision) == (
        fact_id,
        fact_revision,
    )
    assert relation.relation_source.position == "requirements[0].uses[0]"
    assert [ref.model_dump(mode="json") for ref in relation.relation_originals] == [
        case.native_reference
    ]
    assert [ref.model_dump(mode="json") for ref in resource.originals] == [case.native_reference]
    assert "NATIVE_QUALIFICATION_OWNER_UNCONNECTED" in view.gaps
    assert "NATIVE_ACCEPTANCE_OWNER_UNCONNECTED" in view.gaps
    assert read_effect_hashes(work) == baseline

    # Actual auth and URL tenant binding failures remain separate from the
    # positive owner proof. They do not alter the saved private Fact or effects.
    assert setup.client.post(endpoint, json=body).status_code == 401
    foreign = {"Authorization": f"Bearer {setup.tokens[setup.other_human]}"}
    assert setup.client.post(endpoint, headers=foreign, json=body).status_code == 403
    assert read_effect_hashes(work) == baseline
    assert setup.engine._pdos_operational_issuers[work.issuer.key] is issuer_identity
    assert work.issuer.verify_named_decision is callback_identity
    assert setup.engine._pdos_operational_issuer_epochs == registry_epoch
