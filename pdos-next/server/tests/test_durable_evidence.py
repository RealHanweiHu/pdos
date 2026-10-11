"""Real domain/transaction tests, executed only by the verified database test harness."""

import asyncio
import base64
import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from security_fixture import secured_parse, secured_runtime  # noqa: F401
from sqlalchemy import event, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.contracts import UploadInput
from pdos_next.database import tenant_session
from pdos_next.dispatch.outbox import (
    CONSUMER,
    acknowledge,
    claim_events,
    delivery_unknown,
    dispatch_once,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Audit, Grant, Inbox, Outbox, Receipt, UploadedOriginal, now
from pdos_next.object_storage import LocalPrivateObjectStore
from pdos_next.original_security import configure
from pdos_next.originals import object_reference, require_original, upload
from pdos_next.service import Context, digest

pytestmark = pytest.mark.usefixtures("secured_runtime")


@pytest.fixture
def store(tmp_path):
    return LocalPrivateObjectStore(tmp_path / "synthetic-originals")


def upload_input(content=b"Synthetic original\nPressure: 150 PSI\n", **changes):
    values = {
        "title": "Synthetic source only",
        "filename": "synthetic.txt",
        "source_label": "Synthetic original fixture",
        "visibility": "private",
        "content_base64": base64.b64encode(content).decode("ascii"),
        "idempotency_key": str(uuid4()),
        "expected_revision": 1,
        **changes,
    }
    return UploadInput(**values)


def uploaded(setup, store, content=b"Synthetic original\nPressure: 150 PSI\n", **changes):
    data = upload_input(content, **changes)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        result = upload(session, setup.ctx, setup.product, data, store)
    return result, data


def reference(setup, receipt):
    return {
        "category_id": str(setup.category),
        "actor_id": str(setup.human),
        "requester_id": str(setup.human),
        "tenant_id": str(setup.tenant),
        "product_id": str(setup.product),
        "subject_id": receipt["subject_id"],
    }


def count(session, model, *conditions):
    return session.scalar(select(func.count()).select_from(model).where(*conditions))


def expire_lease(setup, event_id):
    with Session(setup.admin) as session, session.begin():
        session.get(Outbox, UUID(event_id)).lease_until = now() - timedelta(seconds=1)


def test_upload_same_and_changed_keys_preserve_one_original_receipt(setup, store):
    content = b"\nSynthetic original bytes\n"
    first, data = uploaded(setup, store, content)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        replay = upload(session, setup.ctx, setup.product, data, store)
    assert replay == first
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        changed_key = upload(
            session,
            setup.ctx,
            setup.product,
            data.model_copy(update={"idempotency_key": str(uuid4())}),
            store,
        )
    assert changed_key == first
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        upload(
            session,
            setup.ctx,
            setup.product,
            data.model_copy(
                update={"content_base64": base64.b64encode(b"Changed source").decode()}
            ),
            store,
        )
    assert error.value.code == "DUPLICATE_INTENT_CONFLICT"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        original = session.get(UploadedOriginal, UUID(first["subject_id"]))
        assert count(session, UploadedOriginal) == 1
        assert count(session, Receipt) == count(session, Audit) == count(session, Outbox) == 1
        assert original.content_hash == hashlib.sha256(content).hexdigest()
        assert original.scan_status == "not_scanned" and original.status == "uploaded"
        assert store.read_original(object_reference(original)) == content


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"filename": "../unsafe.txt"}, "INVALID_PAYLOAD"),
        ({"filename": "unsafe.py"}, "UNSUPPORTED_MEDIA_TYPE"),
        ({"content_base64": "!!!!"}, "INVALID_PAYLOAD"),
        ({"expected_revision": 2}, "VERSION_CONFLICT"),
    ],
)
def test_upload_validation_happens_before_original_or_receipt(setup, store, changes, code):
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        upload(session, setup.ctx, setup.product, upload_input(**changes), store)
    assert error.value.code == ("VERSION_CONFLICT" if code == "VERSION_CONFLICT" else "VALIDATION_FAILED")
    assert error.value.reason == code
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        assert (
            count(session, UploadedOriginal)
            == count(session, Receipt)
            == count(session, Outbox)
            == 0
        )
    assert list(store.root.rglob("*")) == []


def test_upload_and_private_download_require_current_scope_and_human(setup, store):
    result, _ = uploaded(setup, store)
    identity = UUID(result["subject_id"])
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = require_original(session, setup.ctx, setup.product, identity)
        assert store.read_original(object_reference(row)).startswith(b"Synthetic original")
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.peer,
            requester_id=setup.peer,
            category_id=setup.category,
        ) as session,
    ):
        require_original(
            session,
            Context(setup.tenant, setup.peer, setup.peer, category_id=setup.category),
            setup.product,
            identity,
        )
    assert error.value.code == "SOURCE_UNAVAILABLE"
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.agent,
            requester_id=setup.agent,
            category_id=setup.category,
        ) as session,
    ):
        upload(
            session,
            Context(setup.tenant, setup.agent, setup.agent, category_id=setup.category),
            setup.product,
            upload_input(b"Agent cannot upload"),
            store,
        )
    assert error.value.code == "FORBIDDEN_SCOPE"
    with (
        pytest.raises(DomainError) as error,
        tenant_session(setup.engine, uuid4()) as session,
    ):
        require_original(session, setup.ctx, setup.product, identity)
    assert error.value.code == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category,
                Grant.principal_id == setup.human,
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        require_original(session, setup.ctx, setup.product, identity)
    assert error.value.code == "FORBIDDEN_SCOPE"


def test_original_metadata_is_database_immutable_and_bytes_remain_available(setup, store):
    content = b"Synthetic immutable original"
    result, _ = uploaded(setup, store, content)
    identity = UUID(result["subject_id"])
    with (
        pytest.raises(DBAPIError, match="immutable"),
        tenant_session(
            setup.engine,
            setup.tenant,
            actor_id=setup.human,
            requester_id=setup.human,
            category_id=setup.category,
        ) as session,
    ):
        session.get(UploadedOriginal, identity).content_hash = "0" * 64
        session.flush()
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = require_original(session, setup.ctx, setup.product, identity)
        assert store.read_original(object_reference(row)) == content


def test_parse_utf8_commits_artifact_receipt_audit_and_event_once(setup, store):
    content = "\n合成资料\nPressure: 150 PSI\nUnknown: condition\n".encode()
    upload_receipt, _ = uploaded(setup, store, content)
    result = secured_parse(setup.engine, reference(setup, upload_receipt), store)
    assert result["status"] == "parsed"
    assert secured_parse(setup.engine, reference(setup, upload_receipt), store) == result
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(upload_receipt["subject_id"]))
        artifact = session.scalar(select(Artifact).where(Artifact.original_id == row.id))
        receipt = session.scalar(
            select(Receipt).where(Receipt.operation == "evidence.original.parse")
        )
        assert artifact.content.encode() == content and artifact.content_hash == digest(
            content.decode()
        )
        assert artifact.owner_id == setup.human and artifact.visibility == "private"
        assert row.status == "parsed" and row.revision == 2 and row.scan_status == "clean"
        assert row.locator_map[2]["derived_line_start"] == 3
        assert row.locator_map[2]["location"]["line"] == 3
        assert receipt.subject_id == row.id and receipt.subject_revision == 2
        assert session.scalar(select(Audit.id).where(Audit.receipt_id == receipt.id))
        parsed = session.scalar(select(Outbox).where(Outbox.receipt_id == receipt.id))
        assert parsed.type == "original.parsed" and parsed.subject_id == row.id
        assert parsed.subject_revision == 2 and parsed.actor_id == setup.human
        assert count(session, Artifact) == 1
        assert count(session, Receipt) == count(session, Audit) == count(session, Outbox) == 4
        assert store.read_original(object_reference(row)) == content


def test_text_locator_preserves_cr_unicode_separator_and_empty_source_line(setup, store):
    content = b"A\rB\xe2\x80\xa8\rC\n"
    upload_receipt, _ = uploaded(setup, store, content)
    assert (
        secured_parse(setup.engine, reference(setup, upload_receipt), store)["status"] == "parsed"
    )
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(upload_receipt["subject_id"]))
        artifact = session.scalar(select(Artifact).where(Artifact.original_id == row.id))
        assert artifact.content.encode("utf-8") == content
        assert artifact.content.splitlines() == ["A", "B", "", "C"]
        assert len(row.locator_map) == 4
        for source_line, segment in enumerate(row.locator_map, start=1):
            assert segment["location"]["kind"] == "line"
            assert segment["location"]["line"] == source_line
            assert segment["derived_line_start"] == source_line
            assert segment["derived_line_end"] == source_line
        assert store.read_original(object_reference(row)) == content


def test_parse_outbox_failure_rolls_back_derived_fact_and_result(setup, store):
    upload_receipt, _ = uploaded(setup, store)

    def fail(_mapper, _connection, target):
        if target.type == "original.parsed":
            raise RuntimeError("synthetic parse event failure")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic parse event failure"):
            secured_parse(setup.engine, reference(setup, upload_receipt), store)
    finally:
        event.remove(Outbox, "before_insert", fail)
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(upload_receipt["subject_id"]))
        assert row.status == "uploaded" and row.revision == 1 and row.locator_map == []
        assert count(session, Artifact) == 0
        assert count(session, Receipt) == count(session, Audit) == count(session, Outbox) == 3
    assert (
        secured_parse(setup.engine, reference(setup, upload_receipt), store)["status"] == "parsed"
    )


def test_parse_failure_and_replayed_worker_preserve_original_without_fact(setup, store):
    content = b"\xff\xfe Synthetic invalid UTF8 original"
    upload_receipt, _ = uploaded(setup, store, content)
    result = secured_parse(setup.engine, reference(setup, upload_receipt), store)
    assert result["status"] == "failed"
    assert secured_parse(setup.engine, reference(setup, upload_receipt), store) == result
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(upload_receipt["subject_id"]))
        assert row.parse_code == "INVALID_ENCODING" and row.scan_status == "clean"
        assert row.revision == 2 and row.locator_map == [] and count(session, Artifact) == 0
        assert count(session, Receipt) == count(session, Audit) == count(session, Outbox) == 4
        assert store.read_original(object_reference(row)) == content


def test_two_parse_workers_produce_one_fact_and_one_parse_receipt(
    setup,
    tmp_path,
    secured_runtime,  # noqa: F811 - imported pytest fixture
):
    barrier = Barrier(2)

    def simultaneous_parser(content, **kwargs):
        # Both bounded reads finish under their protection locks before parsing races.
        barrier.wait(timeout=10)
        return secured_runtime.parser(content, **kwargs)

    configure(setup.engine, replace(secured_runtime, parser=simultaneous_parser))
    store = LocalPrivateObjectStore(tmp_path / "simultaneous-originals")
    upload_receipt, _ = uploaded(setup, store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: secured_parse(setup.engine, reference(setup, upload_receipt), store),
                range(2),
            )
        )
    assert results[0] == results[1] and results[0]["status"] == "parsed"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        assert count(session, Artifact) == 1
        assert count(session, Receipt, Receipt.operation == "evidence.original.parse") == 1
        assert count(session, Audit) == count(session, Outbox) == 4


def test_access_revoked_during_parse_blocks_domain_commit(
    setup,
    tmp_path,
    secured_runtime,  # noqa: F811 - imported pytest fixture
):
    def revoking_parser(content, **kwargs):
        # Parsing is outside the bounded-read transaction, so revocation can commit.
        with Session(setup.admin) as session, session.begin():
            grant = session.scalar(
                select(Grant).where(
                    Grant.category_id == setup.category,
                    Grant.principal_id == setup.human,
                )
            )
            grant.expires_at = now() - timedelta(seconds=1)
        return secured_runtime.parser(content, **kwargs)

    configure(setup.engine, replace(secured_runtime, parser=revoking_parser))
    store = LocalPrivateObjectStore(tmp_path / "revoking-originals")
    upload_receipt, _ = uploaded(setup, store)
    with pytest.raises(DomainError) as error:
        secured_parse(setup.engine, reference(setup, upload_receipt), store)
    assert error.value.code == "FORBIDDEN_SCOPE"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(upload_receipt["subject_id"]))
        assert row is None
    with Session(setup.admin) as session:
        row = session.get(UploadedOriginal, UUID(upload_receipt["subject_id"]))
        assert row.status == "uploaded" and row.revision == 1
        assert count(session, Artifact, Artifact.tenant_id == setup.tenant) == 0
        assert count(session, Receipt, Receipt.tenant_id == setup.tenant) == 3


def two_page_pdf():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for text in (b"Synthetic page one", b"Synthetic page two"):
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                ),
            }
        )
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (" + text + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def test_pdf_locator_uses_actual_derived_lines_including_page_separator(setup, store):
    result, _ = uploaded(setup, store, two_page_pdf(), filename="synthetic.pdf")
    assert secured_parse(setup.engine, reference(setup, result), store)["status"] == "parsed"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(result["subject_id"]))
        artifact = session.scalar(select(Artifact).where(Artifact.original_id == row.id))
        lines = artifact.content.splitlines()
        second_line = lines.index("Synthetic page two") + 1
        second_page = next(item for item in row.locator_map if item["location"]["page"] == 2)
        assert lines[1] == "" and second_line == 3
        assert second_page["derived_line_start"] == second_line
        assert second_page["derived_line_end"] == second_line
        assert second_page["location"]["kind"] == "page"


def test_xlsx_locator_retains_cell_and_multiline_value_offsets(setup, store):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "合成测量"
    sheet["A1"] = "Synthetic first\n"
    sheet["B2"] = "Synthetic second\nSynthetic third"
    target = io.BytesIO()
    workbook.save(target)
    result, _ = uploaded(setup, store, target.getvalue(), filename="synthetic.xlsx")
    assert secured_parse(setup.engine, reference(setup, result), store)["status"] == "parsed"
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(result["subject_id"]))
        artifact = session.scalar(select(Artifact).where(Artifact.original_id == row.id))
        lines = artifact.content.splitlines()
        second = next(item for item in row.locator_map if item["location"]["cell"] == "B2")
        assert lines == ["Synthetic first", "", "Synthetic second", "Synthetic third"]
        assert second["derived_line_start"] == 3 and second["derived_line_end"] == 4
        assert second["location"]["sheet"] == "合成测量"
        assert second["location"]["row"] == 2 and second["location"]["column"] == 2


def test_competing_outbox_leases_have_one_claim_and_one_inbox(setup, store):
    uploaded(setup, store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        lists = list(
            pool.map(lambda _: claim_events(setup.dispatch, setup.tenant, limit=1), range(2))
        )
    events = [envelope for values in lists for envelope in values]
    assert len(events) == 1
    envelope = events[0]
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(Outbox, UUID(envelope.event_id))
        assert row.lease_id == UUID(envelope.lease_id) and row.attempts == 1
        assert row.delivered_at is None and row.lease_until > now()
        assert count(session, Inbox, Inbox.event_id == row.id, Inbox.consumer == CONSUMER) == 1


def test_unknown_delivery_waits_then_new_lease_rejects_old_ack(setup, store):
    uploaded(setup, store)
    first = claim_events(setup.dispatch, setup.tenant)[0]
    delivery_unknown(setup.dispatch, first)
    assert claim_events(setup.dispatch, setup.tenant) == []
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(Outbox, UUID(first.event_id))
        assert row.last_error == "DELIVERY_UNKNOWN" and row.delivered_at is None
        assert row.lease_id == UUID(first.lease_id)
    expire_lease(setup, first.event_id)
    second = claim_events(setup.dispatch, setup.tenant)[0]
    assert second.event_id == first.event_id and second.lease_id != first.lease_id
    assert acknowledge(setup.dispatch, first, workflow_id="stale-workflow") is False
    assert acknowledge(setup.dispatch, second, workflow_id="synthetic-original-workflow") is True
    assert acknowledge(setup.dispatch, second, workflow_id="overwrite-workflow") is False
    assert claim_events(setup.dispatch, setup.tenant) == []
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(Outbox, UUID(first.event_id))
        inbox = session.scalar(
            select(Inbox).where(Inbox.event_id == row.id, Inbox.consumer == CONSUMER)
        )
        assert row.delivered_at is not None and row.lease_until is None and row.last_error is None
        assert row.attempts == 2 and inbox.status == "received"
        assert inbox.workflow_id == "synthetic-original-workflow" and inbox.received_at is not None
        assert count(session, Inbox, Inbox.event_id == row.id, Inbox.consumer == CONSUMER) == 1


def test_dispatch_response_loss_retries_original_inbox_then_marks_ignored(setup, store):
    uploaded(setup, store)
    attempted = []

    async def unknown_sender(envelope):
        attempted.append(envelope.event_id)
        raise ConnectionError("Synthetic lost response")

    assert asyncio.run(dispatch_once(setup.dispatch, setup.tenant, unknown_sender)) == {
        "delivered": 0,
        "unknown": 1,
    }
    assert asyncio.run(dispatch_once(setup.dispatch, setup.tenant, unknown_sender)) == {
        "delivered": 0,
        "unknown": 0,
    }
    assert len(attempted) == 1
    expire_lease(setup, attempted[0])

    async def no_route(envelope):
        assert envelope.event_id == attempted[0]
        return None

    assert asyncio.run(dispatch_once(setup.dispatch, setup.tenant, no_route)) == {
        "delivered": 1,
        "unknown": 0,
    }
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(Outbox, UUID(attempted[0]))
        inbox = session.scalar(
            select(Inbox).where(Inbox.event_id == row.id, Inbox.consumer == CONSUMER)
        )
        assert row.attempts == 2 and row.delivered_at is not None
        assert inbox.status == "ignored" and inbox.workflow_id is None
        assert count(session, Inbox, Inbox.event_id == row.id, Inbox.consumer == CONSUMER) == 1
