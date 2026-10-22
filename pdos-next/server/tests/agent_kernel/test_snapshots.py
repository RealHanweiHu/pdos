import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.models import PublicWebSnapshot
from pdos_next.agent_kernel.persistence import KernelStore, create_run
from pdos_next.agent_kernel.research_adapter import ResearchArtifacts
from pdos_next.agent_kernel.snapshots import register_snapshot
from pdos_next.database import tenant_session
from pdos_next.models import Receipt, now
from pdos_next.research.types import Snapshot
from tests.agent_kernel.test_transactions import human_session, run


def snapshot():
    body = "Synthetic public pump pressure: 20 PSI"
    return Snapshot(
        uuid4(),
        "https://synthetic.test/pump",
        "https://synthetic.test/pump",
        "Synthetic pump",
        "public fixture",
        now(),
        body,
        hashlib.sha256(body.encode()).hexdigest(),
        "fixture",
        "unknown",
    )


def receipt(setup, scope, snap, *, operation="research.snapshot.register"):
    row = Receipt(
        id=uuid4(),
        tenant_id=setup.tenant,
        category_id=setup.category,
        product_id=None,
        command_id=uuid4(),
        actor_id=setup.human,
        requester_id=setup.human,
        operation=operation,
        subject_type="category" if operation == "category.create" else "public_web_snapshot",
        subject_id=setup.category if operation == "category.create" else snap.id,
        subject_revision=1,
        visibility="category",
        request_digest="a" * 64,
        intent_digest="b" + str(uuid4()).replace("-", ""),
        result={},
    )
    identity = row.id
    with Session(setup.admin) as s, s.begin():
        s.add(row)
    return identity


def test_private_run_snapshot_keeps_private_visibility_and_rejects_wrong_receipt(setup, tmp_path):
    store, scope = run(setup, private_context=True, data_categories=("public",))
    artifacts = ResearchArtifacts(tmp_path, current=store.current)
    snap = snapshot()
    artifacts.save_snapshot(scope, snap)
    rid = receipt(setup, scope, snap)
    with human_session(setup) as s:
        row = register_snapshot(s, setup.ctx, scope, artifacts, artifact_id=snap.id, receipt_id=rid)
        assert row.visibility == "private"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as s:
        assert s.get(PublicWebSnapshot, snap.id) is None
    damaged = snapshot()
    artifacts.save_snapshot(scope, damaged)
    with pytest.raises(DBAPIError, match="Snapshot scope/hash/receipt"):
        with human_session(setup) as s:
            # Direct trusted app DML still cannot substitute another snapshot's receipt.
            s.add(
                PublicWebSnapshot(
                    id=damaged.id,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    owner_id=setup.human,
                    visibility="private",
                    registered_by_run_id=scope.run_id,
                    receipt_id=rid,
                    **{
                        k: getattr(damaged, k)
                        for k in (
                            "url",
                            "final_url",
                            "title",
                            "summary",
                            "retrieved_at",
                            "markdown",
                            "content_hash",
                            "provider",
                            "credibility",
                            "status",
                        )
                    },
                )
            )


def test_personal_public_artifact_registers_only_with_actual_category_create_receipt(
    setup, tmp_path
):
    ctx = replace(setup.ctx, category_id=None)
    with tenant_session(
        setup.engine, setup.tenant, actor_id=setup.human, requester_id=setup.human
    ) as s:
        run_id = create_run(
            s,
            ctx,
            goal="Synthetic new category",
            writer_id=setup.agent,
            intent_key="personal:" + str(uuid4()),
        ).id
    store = KernelStore(setup.engine)
    bound = store.scope(
        tenant_id=setup.tenant,
        requester_id=setup.human,
        writer_id=setup.agent,
        category_id=None,
        run_id=run_id,
    )
    artifacts = ResearchArtifacts(tmp_path, current=store.current)
    snap = snapshot()
    artifacts.save_snapshot(bound, snap)
    rid = receipt(setup, bound, snap, operation="category.create")
    with human_session(setup) as s:
        row = register_snapshot(s, setup.ctx, bound, artifacts, artifact_id=snap.id, receipt_id=rid)
        assert row.category_id == setup.category and row.visibility == "category"
    assert bound.category_id is None  # Existing personal Run is never rewritten to a category.
