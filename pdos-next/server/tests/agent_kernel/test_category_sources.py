"""Actual nullable source rows and common 0406 SQL consumed by the M2 run guard."""

from datetime import timedelta
from uuid import uuid4

import pytest
from security_fixture import ensure_scanned, secured_runtime  # noqa: F401
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import AgentRun
from pdos_next.errors import DomainError
from pdos_next.models import (
    Artifact,
    Grant,
    ObjectAudience,
    OriginalSecurity,
    UploadedOriginal,
    now,
)
from pdos_next.service import digest
from tests.agent_kernel.test_revoked_terminal import close
from tests.agent_kernel.test_transactions import human_session, run


@pytest.fixture(autouse=True)
def actual_scan_runtime(secured_runtime):  # noqa: F811 - explicitly registered pytest fixture
    return secured_runtime


def category_source(setup, *, original=False, shared=False, product_id=None):
    identity, original_id = uuid4(), uuid4() if original else None
    with Session(setup.admin) as s, s.begin():
        if original_id:
            s.add(
                UploadedOriginal(
                    id=original_id,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=product_id,
                    owner_id=setup.peer if shared else setup.human,
                    title="Synthetic category source",
                    filename="synthetic.txt",
                    source_label="fixture",
                    media_type="text/plain",
                    byte_count=len(b"Synthetic category data"),
                    content_hash=digest("Synthetic category data"),
                    storage_key=(f"originals/{original_id.hex}/v1/"
                                 + digest("Synthetic category data")),
                    visibility="audience" if shared else "private",
                    status="parsed",
                )
            )
            s.flush()
            s.add(
                OriginalSecurity(
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=product_id,
                    original_id=original_id,
                )
            )
            s.flush()
        s.add(
            Artifact(
                id=identity,
                tenant_id=setup.tenant,
                category_id=setup.category,
                product_id=product_id,
                original_id=original_id,
                owner_id=setup.peer if shared else setup.human,
                title="Synthetic category extraction",
                source_label="fixture",
                content="Synthetic category data",
                content_hash=digest("Synthetic category data"),
                visibility="audience" if shared else "private",
            )
        )
        s.flush()
        if shared:
            for table, subject in [("artifact_versions", identity)] + (
                [("uploaded_originals", original_id)] if original_id else []
            ):
                s.add(
                    ObjectAudience(
                        tenant_id=setup.tenant,
                        category_id=setup.category,
                        object_type=table,
                        subject_id=subject,
                        owner_id=setup.peer,
                        principal_id=setup.human,
                    )
                )
    if original_id:
        owner = setup.peer if shared else setup.human
        ensure_scanned(
            setup.engine,
            {
                "tenant_id": str(setup.tenant),
                "category_id": str(setup.category),
                "product_id": str(product_id) if product_id else None,
                "actor_id": str(owner),
                "requester_id": str(owner),
                "subject_id": str(original_id),
            },
        )
    return identity, original_id


@pytest.mark.parametrize("original", [False, True])
def test_null_product_source_is_visible_with_actual_indefinite_category_grants(setup, original):
    with Session(setup.admin) as s, s.begin():
        for grant in s.scalars(select(Grant).where(Grant.tenant_id == setup.tenant)):
            grant.expires_at = None
    identity, _ = category_source(setup, original=original)
    store, scope = run(
        setup,
        read_sources=[{"artifact_id": str(identity), "product_id": None, "expected_revision": 1}],
    )
    store.current(scope)
    store.emit(scope, {"type": "synthetic_category_source"})
    assert close(setup, scope.run_id) is False
    with human_session(setup) as s:
        assert s.get(Artifact, identity).product_id is None
    with Session(setup.admin) as s, s.begin():
        s.scalar(select(Grant).where(Grant.principal_id == setup.agent)).expires_at = (
            now() - timedelta(seconds=1)
        )
    with pytest.raises(DomainError) as exc:
        store.current(scope)
    assert exc.value.code == "FORBIDDEN_SCOPE"


def test_nullable_original_and_artifact_keep_both_actual_audience_guards(setup):
    identity, original = category_source(setup, original=True, shared=True)
    store, scope = run(
        setup,
        read_sources=[{"artifact_id": str(identity), "product_id": None, "expected_revision": 1}],
    )
    store.current(scope)
    with Session(setup.admin) as s, s.begin():
        s.delete(s.scalar(select(ObjectAudience).where(ObjectAudience.subject_id == original)))
    with human_session(setup) as s:
        assert s.get(AgentRun, scope.run_id) is None
    with pytest.raises(DomainError) as exc:
        store.current(scope)
    assert exc.value.code == "FORBIDDEN_SCOPE"
    assert close(setup, scope.run_id) is True


def test_null_product_reference_does_not_widen_to_a_product_source(setup):
    identity, _ = category_source(setup, product_id=setup.product)
    with pytest.raises(DomainError) as exc:
        run(
            setup,
            read_sources=[
                {"artifact_id": str(identity), "product_id": None, "expected_revision": 1}
            ],
        )
    assert exc.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session:
        assert session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == setup.tenant)
        ) == 0
        assert session.get(Artifact, identity).product_id == setup.product
