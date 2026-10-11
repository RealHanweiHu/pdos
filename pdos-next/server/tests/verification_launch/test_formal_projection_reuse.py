"""Pure exact-parent prefetch checks; IO uses explicit seams, never a database."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient, make_transient_to_detached
from verification_handoff.test_pure import work as initial_work

from pdos_next.domain.verification_front import service as front
from pdos_next.domain.verification_front.adapters import (
    METHOD_POSITION,
    professional_documents,
)
from pdos_next.domain.verification_front.models import (
    FormalVerificationRequest,
    MethodApplicability,
)
from pdos_next.domain.verification_launch import service
from pdos_next.errors import DomainError
from pdos_next.schemas.verification.contracts import SourceRef
from pdos_next.service import Context, digest


def detached(row):
    make_transient(row)
    make_transient_to_detached(row)
    return row


@pytest.fixture
def parents(monkeypatch):
    seed = initial_work.__wrapped__()
    scope, item, sample = seed.request.scope, seed.request.items[0], seed.samples[0]
    planned_id, actual_id, unused_id, method_id = (uuid4() for _ in range(4))
    request = seed.request.model_copy(
        update={
            "revision": 5,
            "documents": professional_documents(
                seed.request.items,
                (),
                {
                    item.id: SourceRef(
                        id=method_id, revision=1, kind="domain", position=METHOD_POSITION
                    )
                },
            ),
        }
    )

    def formal(identity, revision):
        value = request.model_copy(update={"revision": revision})
        return detached(
            FormalVerificationRequest(
                id=identity,
                tenant_id=scope.tenant_id,
                product_id=scope.product_id,
                project_id=scope.project_id,
                request_id=request.id,
                revision=revision,
                build_id=request.build.id,
                build_revision=request.build.revision,
                status="draft",
                operation="verification.request.create"
                if revision == 1
                else "verification.method.prepare",
                request_snapshot=value.model_dump(mode="json"),
                snapshot_sha256=digest(value.model_dump(mode="json")),
            )
        )

    rows = {
        FormalVerificationRequest: {
            planned_id: formal(planned_id, 1),
            actual_id: formal(actual_id, 2),
            unused_id: formal(unused_id, 3),
        },
        MethodApplicability: {},
    }
    planned_snapshot = {
        "fixed_item": item.model_dump(mode="json"),
        "build": request.build.model_dump(mode="json"),
        "reviewer_id": str(seed.actor),
    }
    planned = detached(
        MethodApplicability(
            id=method_id,
            tenant_id=scope.tenant_id,
            product_id=scope.product_id,
            project_id=scope.project_id,
            request_id=request.id,
            request_version_id=planned_id,
            request_revision=1,
            item_id=item.id,
            revision=1,
            owner_id=seed.actor,
            status="applicable",
            engineering_configuration_id=request.build.engineering_configuration.id,
            engineering_configuration_revision=request.build.engineering_configuration.revision,
            manufacturing_configuration_id=request.build.manufacturing_configuration.id,
            manufacturing_configuration_revision=request.build.manufacturing_configuration.revision,
            method_ref=item.method.model_dump(mode="json"),
            assessment_snapshot=planned_snapshot,
            snapshot_sha256=digest(planned_snapshot),
            authority_snapshot={
                "subject_id": str(seed.actor),
                "operation": "verification.method.prepare",
                "purpose": request.purpose,
            },
            sources=[],
            required_source_read_set=[],
        )
    )
    rows[MethodApplicability][method_id] = planned
    actual_snapshot = {
        "sample": sample.model_dump(mode="json"),
        "fixed_item": item.model_dump(mode="json"),
        "actual_configuration": sample.actual_configuration.model_dump(mode="json"),
    }
    actual = SimpleNamespace(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        product_id=scope.product_id,
        project_id=scope.project_id,
        request_id=request.id,
        request_version_id=actual_id,
        request_revision=2,
        sample_id=sample.id,
        sample_revision=sample.revision,
        actual_configuration_id=sample.actual_configuration.id,
        actual_configuration_revision=sample.actual_configuration.revision,
        build_id=request.build.id,
        item_id=item.id,
        assessment_snapshot=actual_snapshot,
        snapshot_sha256=digest(actual_snapshot),
        method_digest=digest(item.model_dump(mode="json")),
        owner_id=seed.actor,
        authority_snapshot={
            "subject_id": str(seed.actor),
            "operation": "verification.actual_method.prepare",
            "purpose": request.purpose,
        },
    )
    calls = []
    with Session() as session, session.begin():
        session.info["read_snapshot"] = True

        def scalar(query):
            model = query.column_descriptions[0]["entity"]
            identity = query.compile().params["id_1"]
            calls.append((model, {identity}))
            row = rows[model].get(identity)
            if row is not None:
                session.add(row)
            return row

        def scalars(query):
            model = query.column_descriptions[0]["entity"]
            identities = set(query.compile().params["id_1"])
            calls.append((model, identities))
            values = [row for identity in identities if (row := rows[model].get(identity))]
            for row in values:
                session.add(row)
            return values

        monkeypatch.setattr(session, "scalar", scalar)
        monkeypatch.setattr(session, "scalars", scalars)
        monkeypatch.setattr(front, "_sources", lambda *_: None)
        monkeypatch.setattr(front, "_recheck", lambda *_a, **_kw: {"current": True})
        work = SimpleNamespace(
            session=session,
            ctx=Context(scope.tenant_id, seed.actor, seed.actor),
            product=scope.product_id,
            request=request,
            sample=sample,
            value={"actual_configuration": actual_snapshot["actual_configuration"]},
            planned=planned,
            actual=actual,
            methods={(sample.id, item.id): actual},
            rows=rows,
            planned_id=planned_id,
            actual_id=actual_id,
            unused_id=unused_id,
            calls=calls,
        )
        try:
            yield work
        finally:
            # The dirty-context case must never flush this unbound pure Session.
            session.rollback()


def prefetch(work, session=None):
    service._prefetch_formal_parents(
        work.session if session is None else session,
        work.ctx,
        work.product,
        work.request,
        work.methods,
    )


def test_rr_batches_only_known_method_parents_and_keeps_original_checks(parents):
    prefetch(parents)
    assert parents.calls == [
        (MethodApplicability, {parents.planned.id}),
        (FormalVerificationRequest, {parents.planned_id, parents.actual_id}),
    ]
    actual = front._row(parents.session, parents.ctx, parents.product, parents.actual_id)
    assert front._snapshot(actual).revision == 2
    service.physical._actual_binding(
        parents.session,
        parents.ctx,
        parents.product,
        parents.request,
        parents.sample,
        parents.value,
        parents.actual,
    )
    front._method_check(
        parents.session, parents.ctx, parents.product, parents.planned, parents.request
    )
    assert len(parents.calls) == 2
    assert parents.unused_id not in parents.calls[-1][1]


@pytest.mark.parametrize("context", ["writer", "no_transaction", "fake_session", "dirty_rr"])
def test_prefetch_never_runs_outside_clean_actual_rr(parents, context):
    session = parents.session
    if context == "writer":
        session.info["read_snapshot"] = False
    elif context == "no_transaction":
        with Session() as inactive:
            inactive.info["read_snapshot"] = True
            prefetch(parents, inactive)
        assert parents.calls == []
        return
    elif context == "fake_session":
        session = SimpleNamespace(info={"read_snapshot": True})
    else:
        row = parents.rows[FormalVerificationRequest][parents.actual_id]
        session.add(row)
        row.snapshot_sha256 = "f" * 64
    prefetch(parents, session)
    assert parents.calls == []


@pytest.mark.parametrize("invalid", ["missing", "scope", "revision", "snapshot_hash"])
def test_prefetch_does_not_trust_missing_or_invalid_parent(parents, invalid):
    row = parents.rows[FormalVerificationRequest][parents.actual_id]
    if invalid == "missing":
        del parents.rows[FormalVerificationRequest][parents.actual_id]
    else:
        if invalid == "scope":
            row.product_id = uuid4()
        elif invalid == "revision":
            row.revision += 1
        else:
            row.snapshot_sha256 = "f" * 64
        detached(row)
    prefetch(parents)  # Only reads: the original consumer still owns the error.
    with pytest.raises(DomainError) as error:
        parent = front._row(parents.session, parents.ctx, parents.product, parents.actual_id)
        if invalid == "snapshot_hash":
            front._snapshot(parent)
        else:
            service.physical._actual_binding(
                parents.session,
                parents.ctx,
                parents.product,
                parents.request,
                parents.sample,
                parents.value,
                parents.actual,
            )
    assert error.value.reason == (
        "FORBIDDEN_SCOPE" if invalid in {"missing", "scope"} else "INTEGRITY_MISMATCH"
    )


@pytest.mark.parametrize("invalid", ["hash", "qualification"])
def test_prefetched_planned_parent_never_replaces_method_proof(parents, monkeypatch, invalid):
    if invalid == "hash":
        parents.planned.snapshot_sha256 = "f" * 64
        detached(parents.planned)
    else:
        monkeypatch.setattr(front, "_recheck", lambda *_a, **_kw: {"current": False})
    prefetch(parents)
    with pytest.raises(DomainError) as error:
        front._method_check(
            parents.session, parents.ctx, parents.product, parents.planned, parents.request
        )
    assert error.value.reason == ("INTEGRITY_MISMATCH" if invalid == "hash" else "SOURCE_STALE")


def test_prefetch_does_not_move_current_qualification_guard(parents, monkeypatch):
    prefetch(parents)
    monkeypatch.setattr(service.physical, "_execution", lambda *_: pytest.fail("guard skipped"))
    bound = SimpleNamespace(
        physical=SimpleNamespace(authority={"authorized": True, "qualified": False})
    )
    with pytest.raises(DomainError) as error:
        service._guards(parents.session, parents.ctx, None, None, None, bound)
    assert error.value.reason == "QUALIFICATION_REQUIRED"


def test_same_parent_does_not_add_a_redundant_batch(parents):
    parents.actual.request_version_id = parents.planned_id
    prefetch(parents)
    assert parents.calls == [(MethodApplicability, {parents.planned.id})]


def test_other_request_method_parent_is_not_prefetched(parents):
    parents.planned.request_id = uuid4()
    detached(parents.planned)
    prefetch(parents)
    assert parents.calls == [(MethodApplicability, {parents.planned.id})]
