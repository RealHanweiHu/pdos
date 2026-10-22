"""Real pending category retention also fences a member's model references."""

from datetime import timedelta

import pytest
from lifecycle_fixture import lifecycle_work  # noqa: F401 - retained-byte fixture
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input
from test_trusted_source_work import claim_cmd, command, post

from pdos_next.database import tenant_session
from pdos_next.models import (
    Audit,
    Category,
    Claim,
    LifecycleObject,
    Outbox,
    Receipt,
    UploadAttempt,
    now,
)
from pdos_next.originals import upload, upload_contents
from pdos_next.upload_lifecycle import reserve


def test_pending_private_category_original_blocks_model_reference_atomically(lifecycle_work):  # noqa: F811
    work, setup = lifecycle_work, lifecycle_work.setup
    path = f"/v1/categories/{setup.category}"

    def category_command(operation, payload):
        value = {**command(setup, operation, payload), "product_id": None}
        preview = work.client.post(path + "/commands/preview", headers=setup.headers, json=value)
        assert preview.status_code == 200, preview.text
        result = work.client.post(
            path + "/commands", headers=setup.headers, json=preview.json()["command"]
        )
        assert result.status_code == 200, result.text
        return result.json()

    def item(identity):
        response = work.client.get(path + "/original-lifecycle", headers=setup.headers)
        assert response.status_code == 200, response.text
        return next(value for value in response.json()["items"] if value["id"] == str(identity))

    registered = post(
        setup,
        {
            **command(
                setup,
                "evidence.artifact.register",
                {
                    "title": "Synthetic shared category research",
                    "source_label": "pre-project",
                    "content": "\nSynthetic data only\nPressure: 150 PSI\n",
                    "visibility": "category",
                },
            ),
            "product_id": None,
        },
        client=work.client,
    )
    assert registered.status_code == 200, registered.text
    artifact = registered.json()["subject_id"]
    peer_headers = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    adopted = work.client.post(
        path + "/commands", headers=peer_headers, json=claim_cmd(setup, artifact)
    )
    assert adopted.status_code == 200, adopted.text

    # Registration really rolls back after durable local bytes. The named
    # abandonment and protection ports then establish a legitimate orphan.
    data = upload_input(b"Synthetic private category orphan\n")
    context = dict(actor_id=setup.human, requester_id=setup.human, category_id=setup.category)
    with tenant_session(setup.engine, setup.tenant, **context) as session:
        identity = reserve(session, setup.ctx, None, data)
    content, media, _, _ = upload_contents(data)
    reference = work.store.put_scoped(
        content,
        media_type=media,
        tenant_id=setup.tenant,
        product_id=None,
        category_id=setup.category,
        requester_id=setup.human,
        upload_id=identity,
    )
    with pytest.raises(RuntimeError, match="category registration rollback"):
        with tenant_session(setup.engine, setup.tenant, **context) as session:
            upload(
                session,
                setup.ctx,
                None,
                data,
                work.store,
                attempt=session.get(UploadAttempt, identity),
            )
            raise RuntimeError("category registration rollback")
    category_command(
        "evidence.lifecycle.upload.abandon",
        {
            "object_id": str(identity),
            "expected_revision": item(identity)["upload_attempt_revision"],
            "reason": "Synthetic named abandonment after registration rollback",
        },
    )
    category_command(
        "evidence.lifecycle.protection.record",
        {
            "object_id": str(identity),
            "expected_revision": item(identity)["revision"],
            "manual_hold": False,
            "retention_until": (now() - timedelta(seconds=1)).isoformat(),
            "reason": "Synthetic fixture-only retention decision",
        },
    )
    candidate = work.client.post(
        path + f"/original-lifecycle/{identity}/candidate",
        headers=setup.headers,
        json={"action": "quarantine"},
    )
    assert candidate.status_code == 200, candidate.text
    basis = candidate.json()
    assert basis["eligible"], basis
    pending = category_command(
        "evidence.lifecycle.quarantine",
        {
            "candidate_id": basis["candidate_id"],
            "digest": basis["digest"],
            "reason": "Synthetic exact-byte pending isolation",
        },
    )
    assert pending["result"]["state"] == "pending"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.peer,
        requester_id=setup.peer,
        category_id=setup.category,
    ) as session:
        assert session.get(LifecycleObject, identity) is None

    def snapshot():
        with Session(setup.admin) as session:
            return (
                session.get(Category, setup.category).lifecycle_epoch,
                *(
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.tenant_id == setup.tenant)
                    )
                    for model in (Claim, Receipt, Audit, Outbox)
                ),
            )

    before = snapshot()
    # UUID-valued links belong to the same actual structural reference set;
    # the caller cannot read the private lifecycle row that owns this fence.
    response = work.client.post(
        path + "/commands",
        headers=peer_headers,
        json=claim_cmd(setup, artifact, statement=str(identity)),
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "SOURCE_UNAVAILABLE"
    assert response.json()["detail"]["reason"] == "SOURCE_PENDING_LIFECYCLE"
    assert snapshot() == before
    assert item(identity)["pending_intent_id"] == pending["subject_id"]
    assert work.store.read_original(reference) == content
