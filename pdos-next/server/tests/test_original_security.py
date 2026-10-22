"""PG/API security guards with explicit fake scanner facts, never real qualification."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from security_fixture import SyntheticScanner, synthetic_runtime
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input
from test_trusted_source_work import claim_cmd, command

from pdos_next.api import create_app
from pdos_next.database import tenant_session
from pdos_next.domain.products.models import DefinitionRevision, DefinitionSource
from pdos_next.errors import DomainError
from pdos_next.evidence_processing import parse_original
from pdos_next.evidence_security.types import ScanConfiguration, ScannerIdentity, ScanStatus
from pdos_next.models import (
    Artifact,
    Audit,
    Claim,
    Confirmation,
    Grant,
    OriginalScanRequest,
    OriginalScanResult,
    OriginalSecurity,
    Outbox,
    Principal,
    Product,
    Receipt,
    UploadedOriginal,
    now,
)
from pdos_next.object_journal import JournaledLocalObjectStore
from pdos_next.original_security import configure, request_scan, scan_requested
from pdos_next.originals import object_reference, parse_uploaded
from pdos_next.service import Context, source_for


@pytest.fixture
def security_work(setup, tmp_path):
    prior = getattr(setup.engine, "_pdos_security_runtime", None)
    store = JournaledLocalObjectStore(tmp_path / "synthetic-scoped-originals")
    scanner = SyntheticScanner()
    runtime = synthetic_runtime(scanner)
    client = TestClient(
        create_app(setup.engine, setup.auth, object_store=store, security_runtime=runtime)
    )
    try:
        yield SimpleNamespace(
            setup=setup, store=store, scanner=scanner, runtime=runtime, client=client
        )
    finally:
        client.close()
        configure(setup.engine, prior)
        store.close()


def uploaded(work, **changes):
    content = changes.pop(
        "content", b"Synthetic original\nUnverified synthetic fixture\nPressure: 150 PSI\n"
    )
    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals",
        headers=work.setup.headers,
        json=upload_input(content, **changes).model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    return UUID(response.json()["subject_id"])


def scan(work, original_id, *, expected_epoch=1, key=None, headers=None):
    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals/{original_id}/scan",
        headers=headers or work.setup.headers,
        json={"expected_epoch": expected_epoch, "idempotency_key": key or str(uuid4())},
    )
    assert response.status_code == 200, response.text
    return response.json()


def scan_result(work, receipt):
    return scan_requested(
        work.setup.engine,
        {
            "category_id": str(work.setup.category),
            "actor_id": str(work.setup.human),
            "requester_id": str(work.setup.human),
            "tenant_id": str(work.setup.tenant),
            "product_id": str(work.setup.product),
            "subject_id": receipt["subject_id"],
        },
    )


def reference(work, original_id):
    return {
        "category_id": str(work.setup.category),
        "actor_id": str(work.setup.human),
        "requester_id": str(work.setup.human),
        "tenant_id": str(work.setup.tenant),
        "product_id": str(work.setup.product),
        "subject_id": str(original_id),
    }


def parsed(work, original_id):
    receipt = scan(work, original_id)
    assert scan_result(work, receipt)["status"] == "clean"
    assert (
        parse_uploaded(work.setup.engine, reference(work, original_id), work.store)["status"]
        == "parsed"
    )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return session.scalar(select(Artifact.id).where(Artifact.original_id == original_id))


def download(work, original_id, headers=None):
    return work.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals/{original_id}/download",
        headers=headers or work.setup.headers,
    )


def test_original_workspace_read_reuses_authority_and_takes_no_write_locks(security_work):
    work = security_work
    original = uploaded(work)
    parsed(work, original)
    statements = []

    def observed(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", observed)
    try:
        response = work.client.get(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}/workspace",
            headers=work.setup.headers,
        )
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", observed)
    assert response.status_code == 200, response.text
    assert response.json()["sources"][0]["status"] == "active"
    assert not any(
        "FOR UPDATE" in statement or "FOR SHARE" in statement for statement in statements
    )
    assert sum("JOIN grants" in statement for statement in statements) == 1


def count(work, model, *where):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return session.scalar(select(func.count()).select_from(model).where(*where))


def withdraw_command(work, original_id, *, expected_epoch=2):
    return command(
        work.setup,
        "evidence.original.withdraw",
        {
            "original_id": str(original_id),
            "expected_epoch": expected_epoch,
            "reason": "Synthetic sourced withdrawal; preserve bytes and history",
        },
    )


def preview(work, command_value):
    response = work.client.post(
        f"/v1/categories/{work.setup.category}/commands/preview",
        headers=work.setup.headers,
        json=command_value,
    )
    assert response.status_code == 200, response.text
    return response.json()["command"]


def execute(work, command_value, headers=None):
    return work.client.post(
        f"/v1/categories/{work.setup.category}/commands",
        headers=headers or work.setup.headers,
        json=command_value,
    )


def test_unscanned_noruntime_parse_and_download_fail_without_reading_bytes(security_work):
    work = security_work
    original = uploaded(work)
    assert work.store.inspect(original).registration_state == "registered"
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    with pytest.raises(DomainError) as error:
        parse_uploaded(work.setup.engine, reference(work, original), work.store)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    configure(work.setup.engine, None)
    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals/{original}/scan",
        headers=work.setup.headers,
        json={"expected_epoch": 1, "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 503 and response.json()["code"] == "SOURCE_UNAVAILABLE"
    assert (
        count(work, OriginalScanRequest)
        == count(work, OriginalScanResult)
        == count(work, Artifact)
        == 0
    )
    assert work.scanner.calls == 0


@pytest.mark.parametrize(
    "status",
    [
        ScanStatus.UNKNOWN,
        ScanStatus.TIMEOUT,
        ScanStatus.INFECTED,
        ScanStatus.UNAVAILABLE,
        ScanStatus.REJECTED,
    ],
)
def test_nonclean_worker_results_preserve_original_and_cannot_derive_or_download(
    security_work, status
):
    work = security_work
    work.scanner.status = status
    original = uploaded(work)
    receipt = scan(work, original)
    assert scan_result(work, receipt)["status"] == status.value
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    with pytest.raises(DomainError) as error:
        parse_uploaded(work.setup.engine, reference(work, original), work.store)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    assert count(work, Artifact) == 0 and count(work, OriginalScanResult) == 1
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        row = session.get(UploadedOriginal, original)
        assert row.status == "uploaded" and row.scan_status == status.value
        assert work.store.read_original(object_reference(row)).startswith(b"Synthetic original")
    assert count(work, Receipt) == count(work, Audit) == count(work, Outbox) == 3


@pytest.mark.parametrize("field", ["clean", "tenant_id", "storage_key", "scan_receipt"])
def test_http_cannot_supply_scan_authority_or_internal_byte_identity(security_work, field):
    work = security_work
    original = uploaded(work)
    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals/{original}/scan",
        headers=work.setup.headers,
        json={"expected_epoch": 1, "idempotency_key": str(uuid4()), field: "forged"},
    )
    assert response.status_code == 422
    assert count(work, OriginalScanRequest) == count(work, OriginalScanResult) == 0
    assert count(work, Receipt) == 1


def test_private_cross_product_tenant_and_agent_cannot_request_or_replay_scan(security_work):
    work = security_work
    original = uploaded(work)
    owner_key = str(uuid4())
    first = scan(work, original, key=owner_key)
    assert scan(work, original, key=owner_key) == first
    for human in (work.setup.peer, work.setup.other_human):
        headers = {"Authorization": f"Bearer {work.setup.tokens[human]}"}
        assert download(work, original, headers).status_code == 403
        response = work.client.post(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals/{original}/scan",
            headers=headers,
            json={"expected_epoch": 1, "idempotency_key": owner_key},
        )
        assert response.status_code == 403
    other_product = uuid4()
    with Session(work.setup.admin) as session, session.begin():
        session.add(
            Product(
                id=other_product,
                tenant_id=work.setup.tenant,
                owner_id=work.setup.human,
                name="Synthetic second product",
                purpose="Cross-scope original test",
                category_id=work.setup.category,
            )
        )
        session.flush()

    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{other_product}/originals/{original}/scan",
        headers=work.setup.headers,
        json={"expected_epoch": 1, "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 403
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.agent,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session,
    ):
        request_scan(
            session,
            Context(
                work.setup.tenant,
                work.setup.agent,
                work.setup.human,
                category_id=work.setup.category,
            ),
            work.setup.product,
            original,
            expected_epoch=2,
            idempotency_key=str(uuid4()),
        )
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert count(work, OriginalScanRequest) == 1


@pytest.mark.parametrize("changed", ["request_id", "binding", "scanner"])
def test_wrong_trusted_worker_receipt_binding_cannot_certify_original(security_work, changed):
    work = security_work
    original = uploaded(work)
    receipt = scan(work, original)
    if changed == "binding":
        work.scanner.transform = lambda value: replace(
            value, binding=replace(value.binding, requester_id=uuid4())
        )
    elif changed == "scanner":
        work.scanner.transform = lambda value: replace(
            value, scanner=ScannerIdentity("different-port", "v1", "rules1")
        )
    else:
        work.scanner.transform = lambda value: replace(value, request_id=uuid4())
    with pytest.raises(DomainError) as error:
        scan_result(work, receipt)
    assert error.value.code == "SOURCE_STALE"
    assert count(work, OriginalScanResult) == count(work, Artifact) == 0
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"


def test_access_revoked_during_scan_discards_clean_reply_before_domain_commit(security_work):
    work = security_work
    original = uploaded(work)
    receipt = scan(work, original)

    def revoke(_request):
        with Session(work.setup.admin) as session, session.begin():
            grant = session.scalar(
                select(Grant).where(
                    Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
                )
            )
            grant.expires_at = now() - timedelta(seconds=1)

    work.scanner.before_reply = revoke
    with pytest.raises(DomainError) as error:
        scan_result(work, receipt)
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert count(work, OriginalScanResult) == count(work, Artifact) == 0
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(UploadedOriginal, original) is None
    with Session(work.setup.admin) as session:
        assert session.get(UploadedOriginal, original).scan_status == "not_scanned"


def test_epoch_changed_during_parse_prevents_fact_receipt_and_locator_commit(security_work):
    work = security_work
    original = uploaded(work)
    receipt = scan(work, original)
    assert scan_result(work, receipt)["status"] == "clean"

    def changing_parser(*args, **kwargs):
        result = parse_original(*args, **kwargs)
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            state = session.scalar(
                select(OriginalSecurity).where(OriginalSecurity.original_id == original)
            )
            state.epoch += 1
        return result

    configure(work.setup.engine, replace(work.runtime, parser=changing_parser))
    with pytest.raises(DomainError) as error:
        parse_uploaded(work.setup.engine, reference(work, original), work.store)
    assert error.value.code == "SOURCE_UNAVAILABLE"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        row = session.get(UploadedOriginal, original)
        assert row.status == "uploaded" and row.revision == 1 and row.locator_map == []
    assert count(work, Artifact) == 0 and count(work, Receipt) == 3


def test_two_workers_and_request_replay_commit_one_scan_result_and_one_receipt(security_work):
    work = security_work
    original = uploaded(work)
    key = str(uuid4())
    request = scan(work, original, key=key)
    barrier = Barrier(2)
    work.scanner.before_reply = lambda _request: barrier.wait(timeout=15)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scan_result(work, request), range(2)))
    assert all(row["status"] == "clean" for row in results)
    assert work.scanner.calls == 2  # duplicated pure worker work, one durable fact
    work.scanner.before_reply = None
    assert scan_result(work, request)["status"] == "clean" and work.scanner.calls == 2
    assert scan(work, original, key=key)["id"] == request["id"]
    assert count(work, OriginalScanRequest) == count(work, OriginalScanResult) == 1
    assert count(work, Receipt) == count(work, Audit) == count(work, Outbox) == 3
    with (
        pytest.raises(DomainError) as error,
        tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session,
    ):
        request_scan(
            session,
            work.setup.ctx,
            work.setup.product,
            original,
            expected_epoch=2,
            idempotency_key=key,
        )
    assert error.value.code == "DUPLICATE_INTENT_CONFLICT"


def test_scan_result_outbox_failure_rolls_back_result_and_safety_label(security_work):
    work = security_work
    original = uploaded(work)
    request = scan(work, original)

    def failing(_mapper, _connection, target):
        if target.type == "original.scan_recorded":
            raise RuntimeError("Synthetic scan event rollback")

    event.listen(Outbox, "before_insert", failing)
    try:
        with pytest.raises(RuntimeError, match="Synthetic scan event rollback"):
            scan_result(work, request)
    finally:
        event.remove(Outbox, "before_insert", failing)
    assert count(work, OriginalScanResult) == 0 and count(work, Receipt) == 2
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(UploadedOriginal, original).scan_status == "not_scanned"
    with Session(work.setup.admin) as session:
        assert session.get(UploadedOriginal, original).scan_status == "not_scanned"
    assert scan_result(work, request)["status"] == "clean"
    assert count(work, OriginalScanResult) == 1 and count(work, Receipt) == 3


def test_configuration_or_expiry_drift_blocks_old_clean_derived_source_and_download(
    security_work, monkeypatch
):
    work = security_work
    original = uploaded(work)
    artifact = parsed(work, original)
    assert download(work, original).status_code == 200
    later = now() + timedelta(days=2)
    monkeypatch.setattr("pdos_next.original_security.now", lambda: later)
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    with (
        pytest.raises(DomainError),
        tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session,
    ):
        source_for(session, work.setup.ctx, work.setup.product, artifact, 1)
    monkeypatch.undo()
    configuration = ScanConfiguration(
        replace(work.runtime.configuration.scanner, rules_version="changed-rules@2"),
        work.runtime.configuration.policy,
    )
    configure(work.setup.engine, replace(work.runtime, configuration=configuration))
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    assert count(work, Artifact) == 1 and count(work, OriginalScanResult) == 1


@pytest.mark.parametrize("authority", ["grant", "principal"])
def test_access_revoke_then_restore_is_not_aba_permission_for_old_clean(security_work, authority):
    work = security_work
    original = uploaded(work)
    parsed(work, original)
    with Session(work.setup.admin) as session, session.begin():
        if authority == "grant":
            row = session.scalar(
                select(Grant).where(
                    Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
                )
            )
            saved_expiry, original_epoch = row.expires_at, row.access_epoch
            row.expires_at = now() - timedelta(seconds=1)
        else:
            row = session.get(Principal, work.setup.human)
            original_epoch = row.access_epoch
            row.active = False
    with Session(work.setup.admin) as session, session.begin():
        if authority == "grant":
            row = session.scalar(
                select(Grant).where(
                    Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
                )
            )
            row.expires_at = saved_expiry
        else:
            row = session.get(Principal, work.setup.human)
            row.active = True
    with Session(work.setup.admin) as session:
        if authority == "grant":
            epoch = session.scalar(
                select(Grant.access_epoch).where(
                    Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
                )
            )
        else:
            epoch = session.get(Principal, work.setup.human).access_epoch
        assert epoch == original_epoch + 2
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    assert count(work, OriginalScanResult) == 1


def test_withdrawal_during_scan_preserves_bytes_and_discards_late_clean(security_work):
    work = security_work
    original = uploaded(work)
    request = scan(work, original)
    prepared = preview(work, withdraw_command(work, original))

    def withdraw(_request):
        response = execute(work, prepared)
        assert response.status_code == 200, response.text

    work.scanner.before_reply = withdraw
    assert scan_result(work, request)["status"] == "stale"
    assert count(work, OriginalScanResult) == count(work, Artifact) == 0
    assert count(work, Receipt, Receipt.operation == "evidence.original.withdraw") == 1
    assert work.store.inspect(original).byte_status == "intact"
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"


def test_new_scan_epoch_invalidates_prepared_withdrawal_without_consuming_t1(security_work):
    work = security_work
    original = uploaded(work)
    parsed(work, original)
    prepared = preview(work, withdraw_command(work, original))
    request = scan(work, original, expected_epoch=2)
    assert scan_result(work, request)["status"] == "clean"
    response = execute(work, prepared)
    assert response.status_code == 409 and response.json()["code"] == "VERSION_CONFLICT"
    assert count(work, Receipt, Receipt.operation == "evidence.original.withdraw") == 0
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        confirmation = session.scalar(
            select(Confirmation).where(Confirmation.operation == "evidence.original.withdraw")
        )
        assert not confirmation.consumed
        assert session.scalar(select(OriginalSecurity.source_state)).strip() == "active"


def test_t1_withdrawal_preserves_readable_receipts_but_blocks_new_source_use(security_work):
    work = security_work
    original = uploaded(work)
    artifact = parsed(work, original)
    definition_command = command(
        work.setup,
        "product.definition.draft",
        {
            "title": "Synthetic fixed original requirement",
            "purpose": "Keep sourced history while preventing withdrawn reuse",
            "use_cases": ["Synthetic traceability"],
            "change_reason": "First sourced draft",
            "sources": [
                {
                    "artifact_id": str(artifact),
                    "expected_revision": 1,
                    "line": 3,
                    "quote": "Pressure: 150 PSI",
                }
            ],
        },
        source=str(artifact),
    )
    definition = execute(work, definition_command)
    assert definition.status_code == 200, definition.text
    claim = claim_cmd(work.setup, str(artifact))
    saved = execute(work, claim)
    assert saved.status_code == 200, saved.text
    prepared = preview(work, withdraw_command(work, original))
    receipt = execute(work, prepared)
    assert receipt.status_code == 200, receipt.text
    assert execute(work, prepared).json()["id"] == receipt.json()["id"]
    assert execute(work, claim).json()["id"] == saved.json()["id"]
    fresh_claim = {
        **claim,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "payload": {**claim["payload"], "statement": "New withdrawn-source claim"},
    }
    assert execute(work, fresh_claim).json()["code"] == "SOURCE_UNAVAILABLE"
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        source = session.get(Artifact, artifact)
        row = session.get(UploadedOriginal, original)
        state = session.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original)
        )
        assert source.status == state.source_state == "withdrawn" and source.content
        assert row.status == "parsed" and row.locator_map
        assert state.disposition == "active"  # logical withdrawal did not move bytes
        assert work.store.read_original(object_reference(row)).startswith(b"Synthetic original")
        assert session.get(Claim, UUID(saved.json()["subject_id"])) is not None
        defined = session.get(DefinitionRevision, UUID(definition.json()["subject_id"]))
        evidence = session.scalar(
            select(DefinitionSource).where(DefinitionSource.definition_id == defined.id)
        )
        assert defined.status == "draft" and defined.revision == 1
        assert evidence.source_revision == 1 and evidence.quote == "Pressure: 150 PSI"
    assert count(work, Receipt, Receipt.operation == "evidence.original.withdraw") == 1
    workspace = work.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/workspace",
        headers=work.setup.headers,
    ).json()
    assert workspace["originals"][0]["security"]["source_state"] == "withdrawn"
    assert workspace["originals"][0]["security"]["lifecycle"]["physical_actions_available"] is False
    definitions = work.client.get(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/definitions",
        headers=work.setup.headers,
    )
    assert definitions.status_code == 200, definitions.text
    assert definitions.json()["items"][0]["source_status"] == "needs_recheck"
    assert execute(work, definition_command).json()["id"] == definition.json()["id"]
    fresh_definition = {
        **definition_command,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "payload": {**definition_command["payload"], "title": "New withdrawn-source definition"},
    }
    assert execute(work, fresh_definition).json()["code"] == "SOURCE_UNAVAILABLE"


def test_t1_stale_scope_and_final_receipt_failure_roll_back_withdrawal_and_confirmation(
    security_work,
):
    work = security_work
    original = uploaded(work)
    parsed(work, original)
    command_value = withdraw_command(work, original)
    prepared = preview(work, command_value)

    def failing(_mapper, _connection, target):
        if target.type == "original.withdrawn":
            raise RuntimeError("Synthetic withdrawal event rollback")

    event.listen(Outbox, "before_insert", failing)
    try:
        with pytest.raises(RuntimeError, match="Synthetic withdrawal event rollback"):
            execute(work, prepared)
    finally:
        event.remove(Outbox, "before_insert", failing)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        state = session.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original)
        )
        assert state.source_state == "active" and state.epoch == 2
        assert (
            session.scalar(
                select(Confirmation).where(Confirmation.operation == "evidence.original.withdraw")
            ).consumed
            is False
        )
    assert count(work, Receipt, Receipt.operation == "evidence.original.withdraw") == 0
    assert execute(work, prepared).status_code == 200
    with Session(work.setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
            )
        )
        grant.can_write = False
    assert execute(work, prepared).status_code == 200
    fresh = {
        **prepared,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "payload": {**prepared["payload"], "reason": "New decision after write revocation"},
    }
    assert execute(work, fresh).json()["code"] == "FORBIDDEN_SCOPE"
    assert count(work, Receipt, Receipt.operation == "evidence.original.withdraw") == 1


def test_scan_facts_immutable_security_epoch_scope_guard_rls_and_agent_zero_writes(security_work):
    work = security_work
    original = uploaded(work)
    request = scan(work, original)
    assert scan_result(work, request)["status"] == "clean"
    for model in (OriginalScanRequest, OriginalScanResult):
        with (
            pytest.raises(DBAPIError, match="permission denied") as denied,
            tenant_session(
                work.setup.engine,
                work.setup.tenant,
                actor_id=work.setup.human,
                requester_id=work.setup.human,
                category_id=work.setup.category,
            ) as session,
        ):
            row = session.scalar(select(model))
            row_id = row.id
            row.revision += 1
            session.flush()
        assert denied.value.orig.sqlstate == "42501"
        # The migration role can reach the trigger, but even that role cannot
        # rewrite the immutable worker fact. Keep this distinct from app ACLs.
        with (
            pytest.raises(DBAPIError, match="immutable") as immutable,
            Session(work.setup.admin) as session,
            session.begin(),
        ):
            row = session.get(model, row_id)
            row.revision += 1
            session.flush()
        assert immutable.value.orig.sqlstate == "P0001"
    for mutation in ("epoch", "product_id"):
        with (
            pytest.raises(DBAPIError),
            tenant_session(
                work.setup.engine,
                work.setup.tenant,
                actor_id=work.setup.human,
                requester_id=work.setup.human,
                category_id=work.setup.category,
            ) as session,
        ):
            row = session.scalar(select(OriginalSecurity))
            if mutation == "epoch":
                row.epoch += 2
            else:
                row.product_id = uuid4()
                row.epoch += 1
            session.flush()
    with tenant_session(work.setup.engine, uuid4()) as session:
        for model in (OriginalScanRequest, OriginalScanResult, OriginalSecurity):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with Session(work.setup.admin) as session:
        for table in ("original_scan_requests", "original_scan_results", "original_security"):
            assert not session.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent', :table, "
                    "'SELECT,INSERT,UPDATE,DELETE')"
                ),
                {"table": table},
            )
            row = session.execute(
                text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid=CAST(:table AS regclass)"
                ),
                {"table": table},
            ).one()
            assert row.relrowsecurity and row.relforcerowsecurity


def test_category_original_scan_parse_download_and_t1_withdraw(security_work):
    work, setup = security_work, security_work.setup
    base = f"/v1/categories/{setup.category}/originals"
    payload = upload_input(
        b"Synthetic pre-model customer original\nPressure: 150 PSI\n"
    ).model_dump(mode="json")
    uploaded_response = work.client.post(base, headers=setup.headers, json=payload)
    assert uploaded_response.status_code == 200, uploaded_response.text
    original_id = uploaded_response.json()["subject_id"]
    assert uploaded_response.json()["product_id"] is None
    scan_response = work.client.post(
        f"{base}/{original_id}/scan",
        headers=setup.headers,
        json={"expected_epoch": 1, "idempotency_key": str(uuid4())},
    )
    assert scan_response.status_code == 200, scan_response.text
    envelope = reference(work, UUID(original_id))
    envelope["product_id"] = None
    assert (
        scan_requested(
            setup.engine, {**envelope, "subject_id": scan_response.json()["subject_id"]}
        )["status"]
        == "clean"
    )
    assert parse_uploaded(setup.engine, envelope, work.store)["status"] == "parsed"
    from test_trusted_source_work import claim_cmd

    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        artifact = session.scalar(select(Artifact).where(Artifact.original_id == UUID(original_id)))
        artifact_id = artifact.id
        before = session.execute(
            text(
                "SELECT reference_count,read_version FROM lifecycle_reference_summary"
                "(:tenant,:category,NULL,CAST(:roots AS uuid[]))"
            ),
            {"tenant": setup.tenant, "category": setup.category, "roots": [UUID(original_id)]},
        ).one()
        assert before.read_version is not None
    adopted = work.client.post(
        f"/v1/categories/{setup.category}/commands",
        headers=setup.headers,
        json=claim_cmd(setup, str(artifact_id), line=2),
    )
    assert adopted.status_code == 200, adopted.text
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        after = session.execute(
            text(
                "SELECT reference_count,formal_history,read_version FROM lifecycle_reference_summary"
                "(:tenant,:category,NULL,CAST(:roots AS uuid[]))"
            ),
            {"tenant": setup.tenant, "category": setup.category, "roots": [UUID(original_id)]},
        ).one()
        assert after.reference_count > before.reference_count and after.formal_history
        assert after.read_version > before.read_version
    downloaded = work.client.get(f"{base}/{original_id}/download", headers=setup.headers)
    assert downloaded.status_code == 200 and b"Pressure: 150 PSI" in downloaded.content
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert work.client.get(base, headers=peer).json() == []
    assert work.client.get(f"{base}/{original_id}/download", headers=peer).status_code == 403
    with tenant_session(
        setup.engine,
        setup.tenant,
        actor_id=setup.human,
        requester_id=setup.human,
        category_id=setup.category,
    ) as session:
        row = session.get(UploadedOriginal, UUID(original_id))
        assert row.product_id is None and row.category_id == setup.category
        artifact = session.scalar(select(Artifact).where(Artifact.original_id == row.id))
        assert artifact.product_id is None and artifact.category_id == setup.category
        epoch = session.scalar(
            select(OriginalSecurity.epoch).where(OriginalSecurity.original_id == row.id)
        )
    cmd = command(
        setup,
        "evidence.original.withdraw",
        {"original_id": original_id, "expected_epoch": epoch, "reason": "Synthetic withdrawal"},
    )
    cmd["product_id"] = None
    preview = work.client.post(
        f"/v1/categories/{setup.category}/commands/preview", headers=setup.headers, json=cmd
    )
    assert preview.status_code == 200, preview.text
    confirmed = preview.json()["command"]
    result = work.client.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=confirmed
    )
    assert result.status_code == 200, result.text
    with Session(setup.admin) as session:
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.operation == "evidence.original.withdraw",
                Confirmation.category_id == setup.category,
            )
        )
        assert confirmation.product_id is None and confirmation.subject_type == "category"
        assert confirmation.subject_id == setup.category and confirmation.consumed


def test_category_artifact_intent_deduplication_and_direct_sql_null_fence(setup):
    cmd = command(
        setup,
        "evidence.artifact.register",
        {
            "title": "Category research",
            "source_label": "Synthetic",
            "content": "Category input",
            "visibility": "category",
        },
    )
    cmd["product_id"] = None
    path = f"/v1/categories/{setup.category}/commands"
    first = setup.client.post(path, headers=setup.headers, json=cmd)
    assert first.status_code == 200, first.text
    repeated = setup.client.post(
        path,
        headers=setup.headers,
        json={**cmd, "idempotency_key": str(uuid4()), "command_id": str(uuid4())},
    )
    assert repeated.status_code == 200 and repeated.json()["id"] == first.json()["id"]
    with Session(setup.admin) as session:
        stored = session.get(Receipt, UUID(first.json()["id"]))
        values = {col.name: getattr(stored, col.name) for col in Receipt.__table__.columns}
    values.update(id=uuid4(), command_id=uuid4())
    with pytest.raises(DBAPIError), Session(setup.admin) as session, session.begin():
        session.add(Receipt(**values))
        session.flush()
