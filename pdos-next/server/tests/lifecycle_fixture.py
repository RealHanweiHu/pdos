"""Explicit isolated PG lifecycle setup; tiny grace is synthetic, never a production policy."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from security_fixture import synthetic_runtime
from sqlalchemy import func, select
from test_durable_evidence import upload_input
from test_trusted_source_work import command

from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.lifecycle_worker import configure_lifecycle
from pdos_next.models import Product, UploadAttempt, now
from pdos_next.original_lifecycle.types import RetentionPolicy
from pdos_next.original_security import configure
from pdos_next.original_store import OriginalStore
from pdos_next.originals import upload, upload_contents
from pdos_next.upload_lifecycle import reserve


@pytest.fixture
def lifecycle_work(setup, tmp_path):
    sentinel = object()
    saved = {
        name: getattr(setup.engine, name, sentinel)
        for name in (
            "lifecycle_runtime",
            "lifecycle_transport",
            "_pdos_security_runtime",
        )
    }
    store = OriginalStore(tmp_path / "synthetic-lifecycle-bytes")
    policy = RetentionPolicy(
        "synthetic-pg-retention-v1",
        timedelta(microseconds=1),
        timedelta(days=1),
        timedelta(seconds=20),
    )
    client = TestClient(
        create_app(
            setup.engine, setup.auth, object_store=store, security_runtime=synthetic_runtime()
        )
    )
    configure_lifecycle(setup.engine, store, policy=policy)
    try:
        yield SimpleNamespace(setup=setup, store=store, policy=policy, client=client)
    finally:
        client.close()
        for name, value in saved.items():
            if value is sentinel:
                if hasattr(setup.engine, name):
                    delattr(setup.engine, name)
            else:
                setattr(setup.engine, name, value)
        if saved["_pdos_security_runtime"] is sentinel:
            configure(setup.engine, None)
        store.close()


def inventory(work, *, headers=None):
    result = work.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/original-lifecycle",
        headers=headers or work.setup.headers,
    )
    assert result.status_code == 200, result.text
    return result.json()


def item_for(work, object_id):
    return next(item for item in inventory(work)["items"] if item["id"] == str(object_id))


def execute(work, prepared, *, headers=None):
    return work.client.post(
        f"/v1/categories/{work.setup.category}/commands",
        headers=headers or work.setup.headers,
        json=prepared,
    )


def preview_command(work, value, *, headers=None):
    result = work.client.post(
        f"/v1/categories/{work.setup.category}/commands/preview",
        headers=headers or work.setup.headers,
        json=value,
    )
    assert result.status_code == 200, result.text
    return result.json()


def make_command(work, operation, payload, *, key=None):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        revision = session.get(Product, work.setup.product).revision
    return command(work.setup, operation, payload, key=key, revision=revision)


def accepted(work, operation, payload, *, key=None):
    prepared = preview_command(work, make_command(work, operation, payload, key=key))["command"]
    result = execute(work, prepared)
    assert result.status_code == 200, result.text
    return result.json(), prepared


def candidate_response(work, object_id, *, action="quarantine", headers=None):
    return work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/original-lifecycle/{object_id}/candidate",
        headers=headers or work.setup.headers,
        json={"action": action},
    )


def candidate(work, object_id, *, action="quarantine"):
    response = candidate_response(work, object_id, action=action)
    assert response.status_code == 200, response.text
    return response.json()


def candidate_command(work, value, *, key=None, reason="Synthetic named exact-byte review"):
    return make_command(
        work,
        f"evidence.lifecycle.{value['action']}",
        {
            "candidate_id": value["candidate_id"],
            "digest": value["digest"],
            "reason": reason,
        },
        key=key,
    )


def reserve_bytes(work, *, content=b"Synthetic retained bytes; no external material.\n"):
    data = upload_input(content, title="Synthetic lifecycle reservation")
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        identity = reserve(session, work.setup.ctx, work.setup.product, data)
    content, media, _, _ = upload_contents(data)
    reference = work.store.put_scoped(
        content,
        media_type=media,
        tenant_id=work.setup.tenant,
        product_id=work.setup.product,
        requester_id=work.setup.human,
        upload_id=identity,
    )
    return identity, reference, data


def rolled_back_registration(work):
    identity, reference, data = reserve_bytes(work)
    with pytest.raises(RuntimeError, match="Synthetic after-bytes rollback"):
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            attempt = session.get(UploadAttempt, identity)
            upload(session, work.setup.ctx, work.setup.product, data, work.store, attempt=attempt)
            raise RuntimeError("Synthetic after-bytes rollback")
    return identity, reference, data


def ready_orphan(work):
    identity, reference, data = rolled_back_registration(work)
    row = item_for(work, identity)
    abandoned, _ = accepted(
        work,
        "evidence.lifecycle.upload.abandon",
        {
            "object_id": str(identity),
            "expected_revision": row["upload_attempt_revision"],
            "reason": "Synthetic named terminal abandonment after registration rollback",
        },
    )
    assert abandoned["subject_type"] == "upload_attempt"
    assert work.store.inspect(identity).registration_state == "aborted"
    row = item_for(work, identity)
    accepted(
        work,
        "evidence.lifecycle.protection.record",
        {
            "object_id": str(identity),
            "expected_revision": row["revision"],
            "manual_hold": False,
            "retention_until": (now() - timedelta(seconds=1)).isoformat(),
            "reason": "Synthetic explicit retention facts under the fixture-only tiny grace",
        },
    )
    current = item_for(work, identity)
    assert current["registered"] is False and current["can_quarantine"] is True, current
    return identity, reference, data


def request_intent(work, object_id, *, action="quarantine"):
    value = candidate(work, object_id, action=action)
    assert value["eligible"] is True, value
    prepared = preview_command(work, candidate_command(work, value))["command"]
    result = execute(work, prepared)
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt["subject_type"] == "original_lifecycle_intent"
    return UUID(receipt["subject_id"]), receipt, prepared


def worker_reference(work, identity):
    return {
        "category_id": str(work.setup.category),
        "actor_id": str(work.setup.human),
        "requester_id": str(work.setup.human),
        "tenant_id": str(work.setup.tenant),
        "product_id": str(work.setup.product),
        "subject_id": str(identity),
    }


def count(work, model, *where):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))
