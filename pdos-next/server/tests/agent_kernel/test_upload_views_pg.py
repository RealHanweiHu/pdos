"""Actual upload HTTP and read recovery; root alone runs isolated PostgreSQL.

Synthetic scan/parse is an explicitly injected fixture, never production qualification.
No model call, permission expansion, immutable history edit or schema change.
"""

import json
import os
from copy import copy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from security_fixture import secured_parse, synthetic_runtime
from sqlalchemy import delete, event, func, select
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input

from pdos_next.api import create_app
from pdos_next.models import Grant, ObjectAudience, Product, UploadAttempt
from pdos_next.object_journal import JournaledLocalObjectStore
from pdos_next.object_storage import StorageFailure
from pdos_next.originals import upload_contents
from tests.agent_kernel.test_session_views_pg import actor
from tests.agent_kernel.test_source_views_pg import counts as source_counts
from tests.preproject.test_evidence_commands_pg import share_request
from tests.preproject.test_g0 import create, request, save
from tests.test_personal_views import second_category

PRIVATE_ROOT = (Path(__file__).resolve().parents[3] / ".local").resolve()


def private_path(value):
    path = Path(value)
    assert path.is_absolute(), "QA private material requires an absolute path"
    path = path.resolve()
    assert path.is_relative_to(PRIVATE_ROOT), "QA private material must stay in pdos-next/.local"
    return path


@pytest.fixture
def upload_work(setup, tmp_path):
    private = os.environ.get("PDOS_AGENT_UPLOAD_QA_SESSION_PATH")
    if private:
        private_path(private)
    root = (
        PRIVATE_ROOT / f"agent-upload-qa-originals-{setup.category}"
        if private
        else tmp_path / "originals"
    )
    store, runtime = JournaledLocalObjectStore(root.resolve()), synthetic_runtime()
    prior = {
        key: value
        for key, value in vars(setup.engine).items()
        if key.startswith("_pdos") or key == "lifecycle_runtime"
    }
    work = copy(setup)
    work.store, work.runtime = store, runtime
    work.client = TestClient(
        create_app(
            work.engine,
            work.auth,
            object_store=store,
            security_runtime=runtime,
            workflow_enabled=False,
        )
    )
    try:
        yield work
    finally:
        work.client.close()
        for key in list(vars(work.engine)):
            if key.startswith("_pdos") or key == "lifecycle_runtime":
                if key in prior:
                    setattr(work.engine, key, prior[key])
                else:
                    delattr(work.engine, key)
        store.close()


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def base(work):
    return f"/v1/categories/{work.category}"


def original_path(work, product_id=None):
    return base(work) + (f"/products/{product_id}" if product_id else "") + "/originals"


def target(work, **scope):
    return work.client.get(base(work) + "/agent-upload-target", headers=work.headers, params=scope)


def recovered(work, data, **scope):
    digest = upload_contents(data)[3]
    return work.client.get(
        base(work) + f"/agent-upload-receipts/{data.idempotency_key}",
        headers=work.headers,
        params={"request_digest": digest, **scope},
    )


def actual_upload(work, *, product_id=None, title="合成上传资料", **changes):
    current = ok(target(work, **({"product_id": product_id} if product_id else {})))
    data = upload_input(
        f"SYNTHETIC_UPLOAD_BODY_DO_NOT_EXPOSE\n{title}\nUnverified condition.\n".encode(),
        title=title,
        expected_revision=current["target"]["revision"],
        **changes,
    )
    response = work.client.post(
        original_path(work, product_id), headers=work.headers, json=data.model_dump(mode="json")
    )
    return ok(response), data


def counts(work):
    value = source_counts(work)
    with Session(work.admin) as session:
        value[UploadAttempt.__tablename__] = session.scalar(
            select(func.count())
            .select_from(UploadAttempt)
            .where(UploadAttempt.tenant_id == work.tenant)
        )
    return value


def parse(work, original_id, product_id=None):
    result = secured_parse(
        work.engine,
        {
            "tenant_id": str(work.tenant),
            "category_id": str(work.category),
            "product_id": str(product_id) if product_id else None,
            "actor_id": str(work.human),
            "requester_id": str(work.human),
            "subject_id": original_id,
        },
        work.store,
    )
    assert result["status"] == "parsed", result


def export_qa(work, data, stages):
    public = os.environ.get("PDOS_AGENT_UPLOAD_QA_RESPONSE_PATH")
    private = os.environ.get("PDOS_AGENT_UPLOAD_QA_SESSION_PATH")
    if not (public or private):
        return
    bundle = {
        "session": ok(work.client.get("/v1/session", headers=work.headers)),
        "categories": ok(work.client.get("/v1/categories", headers=work.headers)),
        "target": ok(target(work)),
        "product_target": ok(target(work, product_id=work.product)),
        "stages": stages,
        "recovered": ok(recovered(work, data)),
        "sources": ok(work.client.get(base(work) + "/agent-input-sources", headers=work.headers)),
        "scanner": "explicit synthetic fixture port; no production qualification",
    }
    if public:
        path = Path(public)
        assert path.is_absolute(), "Public QA response path must be absolute"
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(bundle, ensure_ascii=False, indent=2)
        assert work.tokens[work.human] not in encoded and "content_base64" not in encoded
        assert "SYNTHETIC_UPLOAD_BODY_DO_NOT_EXPOSE" not in encoded
        path.write_text(encoded + "\n", encoding="utf-8")
    if private:
        path = private_path(private)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(
                {
                    "tenant_id": str(work.tenant),
                    "principal_id": str(work.human),
                    "category_id": str(work.category),
                    "product_id": str(work.product),
                    "token": work.tokens[work.human],
                    "store_path": str(work.store.root),
                    "existing_request_key": data.idempotency_key,
                    "existing_request_digest": upload_contents(data)[3],
                    "scope": {
                        "category_id": str(work.category),
                        "product_id": None,
                        "proposal_id": None,
                    },
                },
                stream,
            )
            stream.write("\n")


def test_actual_upload_lost_receipt_recovery_and_scan_parse_source_versions(upload_work):
    work = upload_work
    destination = ok(target(work))
    assert destination["version"] == "agent-upload-target/v1"
    assert destination["target"] == {"kind": "category", "id": str(work.category), "revision": 1}
    assert destination["authorization"] == {"can_write": True, "code": None}
    receipt, data = actual_upload(work)
    before = counts(work)
    saved = ok(recovered(work, data))
    assert saved["state"] == "committed" and saved["receipt"]["id"] == receipt["id"]
    assert saved["attempt"]["status"] == "committed"
    assert saved["original"]["revision"] == saved["receipt"]["subject_revision"] == 1
    assert saved["original"]["parse_status"] == "uploaded" and saved["source"] is None
    assert counts(work) == before  # Recover without another POST or bytes.
    scan = work.client.post(
        original_path(work) + f"/{receipt['subject_id']}/scan",
        headers=work.headers,
        json={
            "expected_epoch": saved["original"]["security"]["epoch"],
            "idempotency_key": str(uuid4()),
        },
    )
    assert scan.status_code == 200, scan.text
    scanning = ok(recovered(work, data))
    assert scanning["source"] is None and scanning["original"]["security"]["state"] == "scanning"
    parse(work, receipt["subject_id"])
    parsed = ok(recovered(work, data))
    assert parsed["original"]["revision"] == 2 and parsed["original"]["parse_status"] == "parsed"
    assert parsed["receipt"]["subject_revision"] == 1
    assert parsed["source"]["artifact_revision"] == 1
    assert parsed["source"]["original"]["revision"] == 2
    assert parsed["source"]["availability"] == {"available": True, "code": None}
    before = counts(work)
    replay = work.client.post(
        original_path(work), headers=work.headers, json=data.model_dump(mode="json")
    )
    assert ok(replay)["id"] == receipt["id"]
    export_qa(work, data, {"uploaded": saved, "scanning": scanning, "parsed": parsed})
    assert counts(work) == before


def test_product_target_revision_nonce_digest_and_exact_scope(upload_work):
    work = upload_work
    current = ok(target(work, product_id=work.product))
    assert current["target"] == {"kind": "product", "id": str(work.product), "revision": 1}
    receipt, data = actual_upload(work, product_id=work.product)
    assert ok(recovered(work, data, product_id=work.product))["receipt"]["id"] == receipt["id"]
    mismatch = recovered(work, data)
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    wrong_digest = recovered(work, data, product_id=work.product, request_digest="f" * 64)
    assert (
        wrong_digest.status_code == 409
        and wrong_digest.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    )
    before = counts(work)
    body = data.model_copy(update={"expected_revision": 2, "idempotency_key": str(uuid4())})
    rejected = work.client.post(
        original_path(work, work.product), headers=work.headers, json=body.model_dump(mode="json")
    )
    assert rejected.status_code == 409 and rejected.json()["code"] == "VERSION_CONFLICT"
    assert counts(work) == before


def test_real_reserved_upload_and_named_abandonment_keep_unknown_separate(upload_work, monkeypatch):
    work = upload_work
    data = upload_input(title="合成预约：存储尚未接收字节")
    with monkeypatch.context() as patch:

        def unavailable(*_args, **_kwargs):
            raise StorageFailure("STORAGE_UNAVAILABLE", "Explicit synthetic write port unavailable")

        patch.setattr(work.store, "put_scoped", unavailable)
        fault_client = TestClient(work.client.app, raise_server_exceptions=False)
        try:
            failed = fault_client.post(
                original_path(work), headers=work.headers, json=data.model_dump(mode="json")
            )
        finally:
            fault_client.close()
    assert failed.status_code == 500, failed.text
    reserved = ok(recovered(work, data))
    assert reserved["state"] == reserved["attempt"]["status"] == "reserved"
    assert reserved["receipt"] is reserved["original"] is reserved["source"] is None
    save(
        work,
        request(
            work,
            "evidence.lifecycle.upload.abandon",
            {
                "object_id": reserved["attempt"]["id"],
                "expected_revision": reserved["attempt"]["revision"],
                "reason": "合成预约由本人明确终止；不推断字节存在或删除。",
            },
        ),
    )
    abandoned = ok(recovered(work, data))
    assert abandoned["state"] == abandoned["attempt"]["status"] == "abandoned"
    assert abandoned["receipt"] is abandoned["original"] is abandoned["source"] is None
    missing = ok(recovered(work, data.model_copy(update={"idempotency_key": str(uuid4())})))
    assert missing["state"] == "not_observed"
    assert all(missing[key] is None for key in ("receipt", "attempt", "original", "source"))


def test_owned_recovery_hides_peer_tenant_category_and_revoked_product(upload_work):
    work, peer = upload_work, actor(upload_work, upload_work.peer)
    _, secret = actual_upload(work, title="SYNTHETIC_PRIVATE_UPLOAD_TITLE")
    hidden = ok(recovered(peer, secret))
    assert hidden["state"] == "not_observed" and hidden["original"] is None
    assert "SYNTHETIC_PRIVATE_UPLOAD_TITLE" not in json.dumps(hidden)
    foreign = actor(work, work.other_human)
    assert recovered(foreign, secret).status_code == 403
    other = second_category(work)
    assert ok(recovered(other, secret))["state"] == "not_observed"
    _, scoped = actual_upload(peer, product_id=work.product)
    with Session(work.admin) as session, session.begin():
        session.get(Product, work.product).visibility = "private"
        session.execute(
            delete(ObjectAudience).where(
                ObjectAudience.tenant_id == work.tenant,
                ObjectAudience.object_type == "products",
                ObjectAudience.subject_id == work.product,
                ObjectAudience.principal_id == peer.human,
            )
        )
    assert target(peer, product_id=work.product).status_code == 403
    assert recovered(peer, scoped, product_id=work.product).status_code == 403


def test_current_write_reduction_preserves_historical_receipt_read_but_expiry_does_not(upload_work):
    work = upload_work
    receipt, data = actual_upload(work)
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.category,
                Grant.principal_id == work.human,
            )
        )
        grant.can_write = False
    assert ok(target(work))["authorization"] == {"can_write": False, "code": "FORBIDDEN_SCOPE"}
    assert ok(recovered(work, data))["receipt"]["id"] == receipt["id"]
    with Session(work.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.category,
                Grant.principal_id == work.human,
            )
        )
        grant.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
    assert target(work).status_code == 403
    assert recovered(work, data).status_code == 403


def test_proposal_context_is_actual_access_guard_without_claiming_upload_belongs_to_proposal(
    upload_work,
):
    work, owner = upload_work, actor(upload_work, upload_work.peer)
    proposal_id, _ = create(owner, {"title": "合成上传上下文", "entry_kind": "new_product"})
    save(owner, share_request(owner, proposal_id, visibility="audience", audience_ids=[work.human]))
    _, data = actual_upload(work)
    current = ok(recovered(work, data, proposal_id=proposal_id))
    assert current["scope"]["proposal_id"] == proposal_id and current["state"] == "committed"
    save(
        owner, share_request(owner, proposal_id, visibility="audience", audience_ids=[owner.human])
    )
    assert target(work, proposal_id=proposal_id).status_code == 404
    assert recovered(work, data, proposal_id=proposal_id).status_code == 404


def test_get_zero_write_metadata_only_for_unparsed_and_parsed_originals(upload_work):
    work = upload_work
    first, data = actual_upload(work)
    second, parsed_data = actual_upload(work, title="合成解析原件")
    parse(work, second["subject_id"])
    before, statements = counts(work), []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.engine, "before_cursor_execute", capture)
    try:
        values = [ok(target(work)), ok(recovered(work, data)), ok(recovered(work, parsed_data))]
    finally:
        event.remove(work.engine, "before_cursor_execute", capture)
    assert values[1]["receipt"]["subject_id"] == first["subject_id"]
    for sql in statements:
        assert "FOR UPDATE" not in sql and "FOR SHARE" not in sql
        for column in (
            "artifact_versions.content",
            "uploaded_originals.locator_map",
            "uploaded_originals.parse_manifest",
            "upload_attempts.reference",
            "action_receipts.result",
        ):
            assert column not in sql
    encoded = json.dumps(values)
    for value in (
        "content_base64",
        "server_storage_key",
        "locator_map",
        "SYNTHETIC_UPLOAD_BODY_DO_NOT_EXPOSE",
    ):
        assert value not in encoded
    assert counts(work) == before
    for params in ({}, {"request_digest": "bad"}, {"request_digest": "a" * 64, "q": "x"}):
        bad = work.client.get(
            base(work) + f"/agent-upload-receipts/{data.idempotency_key}",
            headers=work.headers,
            params=params,
        )
        assert bad.status_code == 422
