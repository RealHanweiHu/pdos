"""Persisted authoritative Build demand; root runs these against its verified PG.

No live supply, model, object bytes or production qualification. The original
fixture uses an explicitly injected synthetic scan fact, never a real scanner.
"""

import hashlib
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from security_fixture import ensure_scanned, secured_runtime  # noqa: F401 - local fixture
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_builds import (  # noqa: F401 - imported fixtures
    accepted,
    build_command,
    configuration,
    definition,
    project,
)
from test_project_first_plan import cmd, post

from pdos_next.database import tenant_session
from pdos_next.domain.builds.demand import DatabaseBuildDemandPort, load_bound_demand
from pdos_next.domain.builds.models import BuildReadiness
from pdos_next.domain.supply_cost.rules import basis_binding
from pdos_next.engines.supply_cost.common import digest
from pdos_next.error_catalog import REASONS
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Grant, OriginalSecurity, Receipt, UploadedOriginal, now
from pdos_next.schemas.supply_cost.dto import Scope
from pdos_next.service import Context
from pdos_next.service import digest as source_digest

TEXT = "Synthetic requirement is unverified"


def compute(setup, config):
    receipt, _ = accepted(setup, build_command(setup, config))
    command = cmd(
        setup,
        "build.readiness.compute",
        {"build_id": receipt["subject_id"], "expected_build_revision": 1},
        config["source"],
    )
    if "reads" in config:
        command["source_read_set"] = config["reads"]
    response = post(setup, command)
    assert response.status_code == 200, response.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        saved = session.get(BuildReadiness, UUID(response.json()["subject_id"]))
        result = deepcopy(saved.result)
        persisted_at = saved.created_at
    return {
        **config,
        "build_id": receipt["subject_id"],
        "readiness_id": response.json()["subject_id"],
        "result": result,
        "persisted_at": persisted_at,
        "scope": Scope(
            category_id=str(setup.category),
            tenant_id=str(setup.tenant),
            product_id=str(setup.product),
            project_id=config["project"],
            audience=f"private:{setup.human}",
        ),
    }


@pytest.fixture
def demand_work(setup, configuration):  # noqa: F811 - imported fixture
    return compute(setup, configuration)


def load(setup, work, *, scope=None, as_of=None, context=None):
    context = context or setup.ctx
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=context.actor_id,
        requester_id=context.requester_id,
        category_id=setup.category,
    ) as session:
        return DatabaseBuildDemandPort(context).load(
            session, scope or work["scope"], work["build_id"], 1, as_of or now()
        )


def test_exact_persisted_bundle_is_reused_with_complete_sources_and_unknowns(setup, demand_work):
    bound = load(setup, demand_work)
    stored = demand_work["result"]
    assert bound.basis.model_dump(mode="json") == stored["coverage"]["input_snapshot"]["basis"]
    assert [line.model_dump(mode="json") for line in bound.demand.lines] == stored["demands"]
    assert bound.demand.basis_sha256 == digest(bound.basis)
    assert bound.manufacturing_operation_ids == ("assembly",)
    assert bound.manufacturing_configuration.source_id == (
        f"manufacturing_configuration:{demand_work['process']['subject_id']}"
    )
    assert bound.basis.bom.engineering_configuration.source_id == (
        f"configuration:{demand_work['engineering']['subject_id']}"
    )
    assert bound.source_read_set_complete is True
    assert [ref.source_id for ref in bound.source_read_set] == [f"artifact:{demand_work['source']}"]
    demands = {line.item_id: line for line in bound.demand.lines}
    assert str(demands["motor"].required_quantity) == "22.000000000"
    assert demands["unknown"].required_quantity is None and demands["unknown"].issues
    assert stored["hard_blocking"] is True and stored["ready"] is None
    # Existing supply preflight validates the transported bundle, not a live BOM.
    basis_binding(bound, now())


def test_bundle_identity_stays_fixed_when_only_calculation_time_moves(setup, demand_work):
    first = load(setup, demand_work, as_of=demand_work["persisted_at"])
    later = load(setup, demand_work)
    assert first == later
    assert later.demand.ref.captured_at == demand_work["persisted_at"]
    assert later.demand.ref.source_id == f"build-readiness:{demand_work['readiness_id']}"
    assert later.demand.manufacturing_sha256 == later.manufacturing_configuration.sha256


def test_port_participates_in_the_callers_transaction_and_has_no_receipt_write(setup, demand_work):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        before = session.scalar(select(func.count()).select_from(Receipt))
        transaction = session.get_transaction()
        result = load_bound_demand(
            session, setup.ctx, demand_work["scope"], demand_work["build_id"], 1, now()
        )
        assert session.get_transaction() is transaction
        assert result.scope == demand_work["scope"]
        assert not session.new and not session.dirty and not session.deleted
        assert session.scalar(select(func.count()).select_from(Receipt)) == before
    with Session(setup.engine) as session, pytest.raises(DomainError) as refused:
        DatabaseBuildDemandPort(setup.ctx).load(
            session, demand_work["scope"], demand_work["build_id"], 1, now()
        )
    assert refused.value.reason == "INTEGRATION_REQUIRED"
    assert refused.value.code == REASONS["INTEGRATION_REQUIRED"]


@pytest.mark.parametrize("field", ["tenant_id", "product_id", "project_id", "audience"])
def test_server_scope_cannot_be_widened_or_substituted(setup, demand_work, field):
    changed = demand_work["scope"].model_copy(
        update={field: f"category:{setup.category}" if field == "audience" else str(uuid4())}
    )
    with pytest.raises(DomainError) as refused:
        load(setup, demand_work, scope=changed)
    assert refused.value.code == "FORBIDDEN_SCOPE"


@pytest.mark.parametrize("change", ["withdrawn", "revision", "grant", "peer"])
def test_current_source_version_withdrawal_and_acl_are_not_snapshot_authority(
    setup, demand_work, change
):
    context = setup.ctx
    if change == "peer":
        context = Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category)
    else:
        with Session(setup.admin) as session, session.begin():
            if change == "grant":
                session.execute(
                    update(Grant)
                    .where(Grant.category_id == setup.category, Grant.principal_id == setup.human)
                    .values(expires_at=now() - timedelta(seconds=1))
                )
            else:
                session.execute(
                    update(Artifact)
                    .where(Artifact.id == UUID(demand_work["source"]))
                    .values(
                        **({"status": "withdrawn"} if change == "withdrawn" else {"revision": 2})
                    )
                )
    with pytest.raises(DomainError) as refused:
        load(setup, demand_work, context=context)
    assert refused.value.code in {"FORBIDDEN_SCOPE", "SOURCE_UNAVAILABLE", "SOURCE_STALE"}


def test_readiness_is_not_available_before_it_was_persisted(setup, demand_work):
    with pytest.raises(DomainError) as refused:
        load(setup, demand_work, as_of=demand_work["persisted_at"] - timedelta(microseconds=1))
    assert refused.value.reason == "DEMAND_SNAPSHOT_INCOMPLETE"
    assert refused.value.code == REASONS["DEMAND_SNAPSHOT_INCOMPLETE"]
    with pytest.raises(DomainError) as refused:
        load(setup, demand_work, as_of=now() + timedelta(hours=1))
    assert refused.value.reason == "INVALID_EVENT_TIME"
    assert refused.value.code == REASONS["INVALID_EVENT_TIME"]


def test_missing_readiness_does_not_return_empty_success(setup, configuration):  # noqa: F811
    receipt, _ = accepted(setup, build_command(setup, configuration))
    scope = Scope(
        category_id=str(setup.category),
        tenant_id=str(setup.tenant),
        product_id=str(setup.product),
        project_id=configuration["project"],
        audience=f"private:{setup.human}",
    )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        with pytest.raises(DomainError) as refused:
            DatabaseBuildDemandPort(setup.ctx).load(session, scope, receipt["subject_id"], 1, now())
    assert refused.value.reason == "PORT_UNCONNECTED"
    assert refused.value.code == REASONS["PORT_UNCONNECTED"]


@pytest.mark.parametrize("revision", [2, 0, True])
def test_fixed_build_revision_is_exact(setup, demand_work, revision):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        with pytest.raises(DomainError) as refused:
            DatabaseBuildDemandPort(setup.ctx).load(
                session, demand_work["scope"], demand_work["build_id"], revision, now()
            )
    assert refused.value.code == "VERSION_CONFLICT"


@pytest.mark.parametrize("changed", ["coverage", "demands", "hash", "manufacturing", "basis"])
def test_incomplete_saved_bundle_never_rebuilds_demand_from_live_bom(setup, demand_work, changed):
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(BuildReadiness, UUID(demand_work["readiness_id"]))
        original = row.result
        broken = deepcopy(original)
        if changed in {"coverage", "demands"}:
            broken[changed] = None if changed == "coverage" else []
        elif changed == "hash":
            broken["input_sha256"] = "0" * 64
        elif changed == "manufacturing":
            broken["input_snapshot"]["manufacturing_configuration"] = None
        else:
            broken["coverage"]["input_snapshot"]["basis"]["build"]["quantity"] = "999"
        with session.no_autoflush:
            row.result = broken
            try:
                with pytest.raises(DomainError) as refused:
                    DatabaseBuildDemandPort(setup.ctx).load(
                        session, demand_work["scope"], demand_work["build_id"], 1, now()
                    )
                assert refused.value.reason == "DEMAND_SNAPSHOT_INCOMPLETE"
                assert refused.value.code == REASONS["DEMAND_SNAPSHOT_INCOMPLETE"]
            finally:
                row.result = original


def test_source_content_hash_uses_the_existing_source_algorithm(setup, demand_work, monkeypatch):
    bound = load(setup, demand_work)
    assert bound.source_read_set[0].sha256 == source_digest(TEXT)
    monkeypatch.setattr("pdos_next.service.digest", lambda value: "0" * 64)
    with pytest.raises(DomainError) as refused:
        load(setup, demand_work)
    assert refused.value.reason == "INTEGRITY_MISMATCH"
    assert refused.value.code == REASONS["INTEGRITY_MISMATCH"]


@pytest.fixture
def original_work(setup, configuration, request, secured_runtime):  # noqa: F811 - local fixtures
    condition = getattr(request, "param", "valid")
    original_id, artifact_id = uuid4(), uuid4()
    object_hash = hashlib.sha256(b"Synthetic immutable original fixture").hexdigest()
    with Session(setup.admin) as session, session.begin():
        session.add(
            UploadedOriginal(
                id=original_id,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                owner_id=setup.peer if condition == "private_peer" else setup.human,
                title="Synthetic stored original",
                filename="synthetic.txt",
                source_label="Synthetic",
                visibility="private",
                media_type="text/plain",
                byte_count=36,
                content_hash=object_hash,
                storage_key=f"originals/{original_id.hex}/v1/{object_hash}",
                revision=2,
                status="failed" if condition == "failed" else "parsed",
                scan_status="not_scanned",
            )
        )
        session.flush()
        session.add(
            OriginalSecurity(
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                original_id=original_id,
                epoch=1,
                source_state="active",
                disposition="active",
            )
        )
        session.add(
            Artifact(
                id=artifact_id,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=setup.product,
                owner_id=setup.human,
                title="Synthetic original-derived text",
                source_label="Synthetic",
                content=TEXT,
                content_hash=source_digest(TEXT),
                visibility="private",
                original_id=original_id,
            )
        )
    # Private-peer input is refused at the earliest current source guard. The
    # positive/parse-state cases explicitly install test-only worker facts.
    if condition != "private_peer":
        ensure_scanned(
            setup.engine,
            {
                "tenant_id": str(setup.tenant),
                "category_id": str(setup.category),
                "product_id": str(setup.product),
                "actor_id": str(setup.human),
                "requester_id": str(setup.human),
                "subject_id": str(original_id),
            },
        )
    ref = {"artifact_id": str(artifact_id), "expected_revision": 1, "line": 1, "quote": TEXT}
    reads = [
        {"artifact_id": identity, "expected_revision": 1}
        for identity in sorted((configuration["source"], str(artifact_id)))
    ]
    config = {**configuration, "reads": reads}
    engineering = cmd(
        setup,
        "engineering.configuration.create",
        {
            **configuration["engineering_payload"],
            "name": "Synthetic original-sourced engineering",
            "sources": [ref],
        },
    )
    engineering["source_read_set"] = reads
    if condition == "private_peer":
        return {"negative_command": engineering}
    config["engineering"], _ = accepted(setup, engineering)
    manufacturing = cmd(
        setup,
        "npi.process.revise",
        {
            **configuration["process_payload"],
            "name": "Synthetic original-sourced manufacturing",
            "engineering_configuration_id": config["engineering"]["subject_id"],
            "sources": [ref],
        },
    )
    manufacturing["source_read_set"] = reads
    config["process"], _ = accepted(setup, manufacturing)
    # build_command consumes all fixed sources at its preview too.
    built = build_command(setup, config)
    built["source_read_set"] = reads
    receipt, _ = accepted(setup, built)
    calculated = cmd(
        setup,
        "build.readiness.compute",
        {
            "build_id": receipt["subject_id"],
            "expected_build_revision": 1,
        },
    )
    calculated["source_read_set"] = reads
    response = post(setup, calculated)
    assert response.status_code == 200, response.text
    return {
        **config,
        "build_id": receipt["subject_id"],
        "original_id": str(original_id),
        "artifact_id": str(artifact_id),
        "object_hash": object_hash,
        "scope": Scope(
            category_id=str(setup.category),
            tenant_id=str(setup.tenant),
            product_id=str(setup.product),
            project_id=config["project"],
            audience=f"private:{setup.human}",
        ),
    }


def test_actual_original_ref_is_complete_without_exposing_object_key_or_claiming_clean(
    setup, original_work
):
    bound = load(setup, original_work)
    refs = {reference.source_id: reference for reference in bound.source_read_set}
    assert len(refs) == 3
    original = refs[f"original:{original_work['original_id']}"]
    assert original.version == "2" and original.sha256 == original_work["object_hash"]
    assert refs[f"artifact:{original_work['artifact_id']}"].sha256 == source_digest(TEXT)
    assert "storage_key" not in bound.model_dump_json()
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(original_work["original_id"]))
        assert row.scan_status == "clean"  # explicit synthetic fixture receipt
        assert "scan_status" not in bound.model_dump_json()


@pytest.mark.parametrize("original_work", ["private_peer", "failed"], indirect=True)
def test_current_original_acl_and_state_cannot_be_bypassed_by_derived_artifact(
    setup, original_work
):
    if "negative_command" in original_work:
        refused = post(setup, original_work["negative_command"], True)
        assert refused.status_code == 403 and refused.json()["code"] == "SOURCE_UNAVAILABLE"
        return
    with pytest.raises(DomainError) as refused:
        load(setup, original_work)
    assert refused.value.code == "SOURCE_UNAVAILABLE"
