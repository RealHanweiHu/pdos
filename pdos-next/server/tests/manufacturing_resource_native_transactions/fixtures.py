"""Real original owner/HTTP fixture; no replacement of runtime authorization or IO.

Native Text uses the actual evidence.artifact.register receipt and persisted
content/hash. It is not an UploadedOriginal or a scanner qualification.
"""

import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from build_operational_facts.fixtures import imported
from manufacturing_preparation_transactions.fixtures import (
    effect_hashes,
    registered_text,
    source_ref,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from pdos_next.change_dependency_clock import ChangeDependencyClock
from pdos_next.database import tenant_session
from pdos_next.domain.build_operational_facts.models import (
    BuildOperationalCurrent,
    BuildOperationalFact,
    MaterialHold,
    OperationalAsset,
    ResourceOccupancy,
)
from pdos_next.domain.build_operational_facts.schemas import FactInput
from pdos_next.domain.builds.models import Build, BuildReadiness
from pdos_next.domain.change_execution import service as evidence
from pdos_next.domain.manufacturing_resource_owner import owner
from pdos_next.domain.manufacturing_resource_owner.schemas import ResourceRequest, VersionRef
from pdos_next.models import Artifact, Grant, LoginSession, Principal, now
from pdos_next.object_storage import LocalPrivateObjectStore
from pdos_next.safety import verify_test_target
from pdos_next.service import digest

SOURCE_TEXT = (
    "Synthetic isolated resource mirror and exact Build assembly relation; "
    "acceptance, calibration, personnel qualification and execution are unknown."
)
EXTRA_READ_MODELS = (
    BuildOperationalFact,
    BuildOperationalCurrent,
    OperationalAsset,
    MaterialHold,
    ResourceOccupancy,
    Build,
    BuildReadiness,
    ChangeDependencyClock,
    Artifact,
    Principal,
    Grant,
)


@pytest.fixture
def native_resource_case(operational_work, tmp_path, request):
    work = operational_work
    setup = work.setup
    profile = getattr(request, "param", "bounded")
    assert profile in {"bounded", "no_deadline"}
    verify_test_target(setup.engine)
    # Configure a real private store. The native branch reads persisted text;
    # uploaded bytes, if ever introduced, still use the actual store/safety owner.
    prior_store = getattr(setup.engine, "_pdos_change_store", None)
    store = LocalPrivateObjectStore(tmp_path / "native-resource-originals")
    evidence.configure_store(setup.engine, store)
    try:
        identity = registered_text(setup, "Synthetic native resource basis", SOURCE_TEXT)
        reference = source_ref(identity, SOURCE_TEXT)
        data = deepcopy(work.payload.model_dump(mode="json"))
        # First import contains no invented named T2 acceptance/qualification.
        data["materials"] = []
        data["materials_scope_complete"] = False
        data["valid_from"] = (work.at - timedelta(minutes=10)).isoformat()
        data["valid_until"] = (
            None if profile == "no_deadline" else (work.at + timedelta(minutes=30)).isoformat()
        )
        data["sources"] = [reference]
        for resource in data["resources"]:
            resource["facts"] = []
            resource["sources"] = [reference]
            resource["calendar_sources"] = [reference]
        for requirement in data["requirements"]:
            requirement["sources"] = [reference]
        payload = FactInput.model_validate(data)
        assert payload.scope == work.scope
        assert payload.valid_from <= work.scope.window.start
        assert payload.valid_until is None or payload.valid_until >= work.scope.window.finish
        assert not payload.materials and payload.materials_scope_complete is False
        assert all(not value.facts for value in payload.resources)
        work.payload = payload
        receipt = imported(work)
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            build, _, process, _reads, scope, execution = configurations_for(work, session)
            request = ResourceRequest(
                scope=scope,
                build=VersionRef(id=build.id, revision=build.revision),
                process=VersionRef(id=UUID(process["id"]), revision=process["revision"]),
                execution=execution,
                operation_key="assembly",
            )
        assert request.execution == work.scope and request.execution.window.finish > now()
        yield SimpleNamespace(
            work=work,
            setup=setup,
            receipt=receipt,
            request=request,
            native_source_id=UUID(identity),
            native_reference=reference,
            store=store,
        )
    finally:
        evidence.configure_store(setup.engine, prior_store)


def configurations_for(work, session):
    """Use the actual operational owner to fix Build/configuration/Scope, no new truth."""
    from pdos_next.domain.build_operational_facts.service import _scope

    return _scope(
        session, work.setup.ctx, work.setup.product, UUID(work.build_id), work.scope, write=False
    )


def read_effect_hashes(work):
    """Reuse original effect hash contract, adding all resource/Source/access read rows."""
    result = effect_hashes(work)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        for model in EXTRA_READ_MODELS:
            result[model.__tablename__] = digest(
                sorted(
                    [
                        dict(row)
                        for row in session.execute(
                            select(model.__table__).where(model.tenant_id == work.setup.tenant)
                        ).mappings()
                    ],
                    key=lambda row: str(row["id"]),
                )
            )
    # The actual auth role alone reads login sessions. Hash only this fresh
    # synthetic tenant's full rows; no session token or row is reported.
    with Session(work.setup.auth) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        result[LoginSession.__tablename__] = digest(
            sorted(
                [
                    {
                        column.name: getattr(row, column.name)
                        for column in LoginSession.__table__.columns
                    }
                    for row in session.scalars(
                        select(LoginSession).where(LoginSession.tenant_id == work.setup.tenant)
                    )
                ],
                key=lambda row: row["token_hash"],
            )
        )
    return result


@contextmanager
def observe_direct_named_verifier(issuer):
    """Passive current-thread call counts, with exact previous profiler restoration.

    Observe only direct same-UOW owner methods, never claim HTTP worker coverage.
    No frame, locals, SQL, argument or credential is retained. The original
    issuer/callback object and registry epoch are untouched.
    """
    verifier = issuer.verify_named_decision
    assert callable(verifier) and hasattr(verifier, "__code__")
    watched = {
        verifier.__code__: "named_verifier",
        owner.inspect_resource.__code__: "inspect_resource",
        owner.refresh_resource.__code__: "refresh_resource",
    }
    counts = dict.fromkeys(watched.values(), 0)
    prior = sys.getprofile()

    def observe(frame, event, argument):
        if prior is not None:
            prior(frame, event, argument)
        if event == "call" and frame.f_code in watched:
            counts[watched[frame.f_code]] += 1

    sys.setprofile(observe)
    try:
        yield counts
    finally:
        sys.setprofile(prior)
        assert sys.getprofile() is prior
