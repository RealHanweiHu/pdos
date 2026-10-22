"""Offline upload read contracts; no database, object bytes or model calls."""

from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pdos_next.agent_kernel import upload_views as views
from pdos_next.contracts import UploadInput
from pdos_next.errors import DomainError
from pdos_next.originals import upload_contents
from pdos_next.service import Context


def context():
    identity = uuid4()
    return Context(uuid4(), identity, identity, category_id=uuid4())


class ReadSession:
    def __init__(self, *rows):
        self.rows, self.statements = list(rows), []

    def execute(self, statement):
        self.statements.append(str(statement))
        value = self.rows.pop(0)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: value))

    def scalar(self, statement):
        self.statements.append(str(statement))
        return (
            None
            if "uploaded_originals.id" in str(statement)
            else datetime(2026, 10, 17, tzinfo=UTC)
        )


def test_scope_and_digest_query_contract_are_strict_and_bounded():
    assert views.UploadScope().product_id is None
    for value in ({"cursor": str(uuid4())}, {"product_id": "bad"}, {"runtime": True}):
        with pytest.raises(ValidationError):
            views.UploadScope.model_validate(value)
    for value in ({}, {"request_digest": "A" * 64}, {"request_digest": "a" * 63}):
        with pytest.raises(ValidationError):
            views.UploadRecovery.model_validate(value)


def test_upload_digest_uses_validated_stripped_metadata_and_hash_of_original_bytes():
    data = UploadInput(
        title="  合成标题  ",
        filename="  input.txt  ",
        source_label="  合成来源  ",
        content_base64="YWJj",
        idempotency_key=str(uuid4()),
        expected_revision=7,
    )
    content, _, request, digest = upload_contents(data)
    assert content == b"abc" and data.filename == "input.txt"
    assert request["title"] == "合成标题" and request["source_label"] == "合成来源"
    canonical = (
        '{"content_hash":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",'
        '"expected_revision":7,"filename":"input.txt","source_label":"合成来源",'
        '"title":"合成标题","visibility":"private"}'
    )
    assert digest == sha256(canonical.encode()).hexdigest()


def test_target_reports_current_authorization_separate_from_runtime(monkeypatch):
    ctx = context()
    monkeypatch.setattr(views, "_human", lambda *_: None)

    def access(_session, _ctx, _pid, **options):
        if options.get("write"):
            raise DomainError("FORBIDDEN_SCOPE", "Read only", 403)
        return SimpleNamespace(category_id=ctx.category_id, revision=9)

    monkeypatch.setattr(views, "require_access", access)
    value = views.read_target(ReadSession(), ctx, views.UploadScope())
    assert value["target"] == {"kind": "category", "id": str(ctx.category_id), "revision": 9}
    assert value["authorization"] == {"can_write": False, "code": "FORBIDDEN_SCOPE"}
    assert not {"runtime", "store_ready", "worker_ready", "can_upload"} & value.keys()


def test_missing_owned_request_is_not_observed_without_success_or_failure_inference(monkeypatch):
    monkeypatch.setattr(views, "_human", lambda *_: None)
    session = ReadSession(None, None)
    value = views.read_receipt(
        session, context(), uuid4(), views.UploadRecovery(request_digest="a" * 64)
    )
    assert value["state"] == "not_observed"
    assert all(value[key] is None for key in ("receipt", "attempt", "original", "source"))
    assert not {"failed", "safe_to_retry", "may_delete", "bytes_present"} & value.keys()
    assert not any("upload_attempts.reference" in sql for sql in session.statements)


def test_wrong_digest_is_rejected_before_receipt_or_original_reads(monkeypatch):
    monkeypatch.setattr(views, "_human", lambda *_: None)
    session = ReadSession({"digest": "b" * 64, "receipt_id": uuid4()})
    with pytest.raises(DomainError) as error:
        views.read_receipt(
            session, context(), uuid4(), views.UploadRecovery(request_digest="a" * 64)
        )
    assert error.value.reason == "DUPLICATE_INTENT_CONFLICT"
    assert len(session.statements) == 1


@pytest.mark.parametrize("status", ["reserved", "abandoned"])
def test_reservation_states_do_not_claim_an_original_or_available_source(monkeypatch, status):
    monkeypatch.setattr(views, "_human", lambda *_: None)
    session = ReadSession(
        None, {"id": uuid4(), "revision": 2, "status": status, "request_digest": "a" * 64}
    )
    value = views.read_receipt(
        session, context(), uuid4(), views.UploadRecovery(request_digest="a" * 64)
    )
    assert value["state"] == value["attempt"]["status"] == status
    assert value["receipt"] is value["original"] is value["source"] is None


def test_committed_receipt_survives_current_original_unavailability(monkeypatch):
    ctx = context()
    monkeypatch.setattr(views, "_human", lambda *_: None)
    monkeypatch.setattr(views, "_attempt", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(views, "_original", lambda *_: (None, None))
    saved = {
        "id": uuid4(),
        "operation": views.OPERATION,
        "subject_type": "uploaded_original",
        "subject_id": uuid4(),
        "subject_revision": 1,
        "actor_id": ctx.actor_id,
        "requester_id": ctx.requester_id,
        "created_at": datetime(2026, 10, 17, tzinfo=UTC),
        "request_digest": "a" * 64,
    }
    session = ReadSession({"digest": "a" * 64, "receipt_id": saved["id"]}, saved)
    value = views.read_receipt(session, ctx, uuid4(), views.UploadRecovery(request_digest="a" * 64))
    assert value["state"] == "committed" and value["receipt"]["id"] == str(saved["id"])
    assert value["original"] is value["source"] is None
    assert not any("action_receipts.result" in sql for sql in session.statements)


def test_routes_are_get_only_snapshot_bound_and_reject_duplicate_parameters(monkeypatch):
    ctx, seen = context(), []

    @contextmanager
    def transaction(context_value, *, read_snapshot=False):
        assert context_value is ctx and read_snapshot is True
        yield object()

    monkeypatch.setattr(views, "read_target", lambda *_: seen.append("target") or {})
    monkeypatch.setattr(views, "read_receipt", lambda *_: seen.append("receipt") or {})
    app = FastAPI()

    @app.exception_handler(DomainError)
    def fail(_request, error):
        return JSONResponse(error.payload(), status_code=error.status)

    app.include_router(
        views.router(transaction=transaction, context_dependency=Depends(lambda: ctx))
    )
    with TestClient(app) as client:
        path = f"/v1/categories/{ctx.category_id}"
        assert client.get(path + "/agent-upload-target").status_code == 200
        recover = path + f"/agent-upload-receipts/{uuid4()}"
        assert client.get(recover, params={"request_digest": "a" * 64}).status_code == 200
        for query in (
            "request_digest=" + "a" * 64 + "&request_digest=" + "a" * 64,
            "request_digest=" + "a" * 64 + "&unknown=x",
            "request_digest=bad",
        ):
            assert client.get(recover + "?" + query).status_code == 422
        assert client.get(recover).status_code == 422
        assert client.post(path + "/agent-upload-target").status_code == 405
    assert seen == ["target", "receipt"]
