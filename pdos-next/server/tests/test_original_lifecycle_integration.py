"""Real PG/API/retained-temp-byte integration; root runs the isolated DB candidate.

The scanner and microsecond retention profile are explicitly synthetic. Local
reversible transport is real; no existing original, purge or production enablement.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from threading import Event
from uuid import UUID, uuid4

import pytest
from lifecycle_fixture import (  # noqa: F401
    accepted,
    candidate,
    candidate_command,
    candidate_response,
    count,
    execute,
    inventory,
    item_for,
    make_command,
    preview_command,
    ready_orphan,
    request_intent,
    rolled_back_registration,
    worker_reference,
)
from lifecycle_fixture import lifecycle_work as _lifecycle_work
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_durable_evidence import upload_input

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.dispatch.outbox import CONSUMER, acknowledge, claim_events
from pdos_next.domain.original_lifecycle_execution.codec import decode_intent
from pdos_next.errors import DomainError
from pdos_next.lifecycle_access import References, schema_covered
from pdos_next.lifecycle_worker import process
from pdos_next.models import (
    Artifact,
    Audit,
    Claim,
    Confirmation,
    Grant,
    Inbox,
    LifecycleCandidate,
    LifecycleIntentRecord,
    LifecycleObject,
    LifecycleRequest,
    Outbox,
    Product,
    Receipt,
    RequestKey,
    UploadAttempt,
    UploadedOriginal,
    now,
)
from pdos_next.object_journal import InventoryPage
from pdos_next.object_storage import StorageFailure
from pdos_next.original_lifecycle.types import IntentState
from pdos_next.original_security import request_scan, scan_requested
from pdos_next.originals import parse_uploaded, upload
from pdos_next.service import Context, digest
from pdos_next.service import execute as domain_execute

lifecycle_work = _lifecycle_work


def intent_state(work, identity):
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        return decode_intent(session.get(LifecycleIntentRecord, identity).document)


def revoke(work, can_write):
    with Session(work.setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.setup.category,
                Grant.principal_id == work.setup.human,
            )
        )
        grant.can_write = can_write


@pytest.mark.parametrize("parse_failed", [False, True])
def test_registered_original_is_never_orphan_even_when_parsing_failed(lifecycle_work, parse_failed):
    work = lifecycle_work
    content = b"\xffSynthetic invalid UTF-8" if parse_failed else b"Synthetic registered original\n"
    result = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals",
        headers=work.setup.headers,
        json=upload_input(content).model_dump(mode="json"),
    )
    assert result.status_code == 200, result.text
    identity = UUID(result.json()["subject_id"])
    if parse_failed:
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            queued = request_scan(
                session,
                work.setup.ctx,
                work.setup.product,
                identity,
                expected_epoch=1,
                idempotency_key=str(uuid4()),
            )
        scan_result = scan_requested(
            work.setup.engine,
            worker_reference(work, UUID(queued["subject_id"])),
        )
        assert scan_result["status"] == "clean", scan_result
        parsed = parse_uploaded(work.setup.engine, worker_reference(work, identity), work.store)
        assert parsed["status"] == "failed", parsed
    current = item_for(work, identity)
    assert current["registered"] is True and current["can_quarantine"] is False
    assert "registered_original" in current["reasons"]
    value = candidate(work, identity)
    assert value["eligible"] is False and "registered_original" in value["reasons"]


def test_bytes_written_registration_rollback_is_unknown_until_positive_terminal_decision(
    lifecycle_work,
):
    work = lifecycle_work
    identity, reference, _ = rolled_back_registration(work)
    journal = work.store.inspect(identity)
    assert journal.state == "bytes_written" and journal.registration_state == "unknown"
    assert journal.byte_status == "intact"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(UploadedOriginal, identity) is None
        assert session.get(UploadAttempt, identity).status == "reserved"
    current = item_for(work, identity)
    assert current["registered"] is None and current["can_quarantine"] is False
    assert "registration_unknown" in current["reasons"]
    assert work.store.read_original(reference)
    assert count(work, Receipt, Receipt.operation == "evidence.original.upload") == 0


def test_abandon_retention_quarantine_restore_keeps_exact_bytes_and_once_receipts(lifecycle_work):
    work = lifecycle_work
    identity, reference, _ = ready_orphan(work)
    initial = work.store.read_original(reference)
    quarantine, receipt, prepared = request_intent(work, identity)
    assert receipt["result"]["state"] == "pending"
    outcome = process(work.setup.engine, worker_reference(work, quarantine))
    assert outcome["status"] == "applied", outcome
    current = item_for(work, identity)
    assert current["disposition"] == "quarantined" and current["pending_intent_id"] is None
    assert (work.store.root / reference.server_storage_key).read_bytes() == initial
    with pytest.raises(StorageFailure):
        work.setup.engine.lifecycle_transport.ensure_readable(reference)
    restore, _, _ = request_intent(work, identity, action="restore")
    restored = process(work.setup.engine, worker_reference(work, restore))
    assert restored["status"] == "applied", restored
    assert item_for(work, identity)["disposition"] == "active"
    assert sha256(work.store.read_original(reference)).hexdigest() == reference.content_sha256
    assert execute(work, prepared).json()["id"] == receipt["id"]
    assert count(work, Receipt, Receipt.operation == "evidence.lifecycle.quarantine") == 1
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        receipt_id = UUID(receipt["id"])
        assert (
            session.scalar(
                select(func.count()).select_from(Audit).where(Audit.receipt_id == receipt_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Outbox).where(Outbox.receipt_id == receipt_id)
            )
            == 1
        )
        assert session.get(UploadedOriginal, identity) is None
        assert session.get(UploadAttempt, identity).status == "abandoned"


def test_terminal_marker_failure_keeps_committed_abandonment_and_unknown_registration(
    lifecycle_work, monkeypatch
):
    work = lifecycle_work
    identity, _, _ = rolled_back_registration(work)
    current = item_for(work, identity)

    def unavailable(*args, **kwargs):
        raise StorageFailure(
            "SYNTHETIC_MARKER_FAILURE", "Synthetic journal acknowledgement failure"
        )

    monkeypatch.setattr(work.store, "mark_aborted", unavailable)
    receipt, prepared = accepted(
        work,
        "evidence.lifecycle.upload.abandon",
        {
            "object_id": str(identity),
            "expected_revision": current["upload_attempt_revision"],
            "reason": "Positive terminal DB decision, marker temporarily unknown",
        },
    )
    assert execute(work, prepared).json()["id"] == receipt["id"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(UploadAttempt, identity).status == "abandoned"
    assert work.store.inspect(identity).registration_state == "unknown"
    assert item_for(work, identity)["registered"] is None
    assert candidate(work, identity)["eligible"] is False


def test_missing_journal_unbound_original_and_partial_inventory_cannot_prove_orphan(
    lifecycle_work, monkeypatch
):
    work = lifecycle_work
    legacy_reference = work.store._legacy.put_new(
        b"Synthetic unbound legacy bytes", media_type="text/plain"
    )
    denied = candidate_response(work, legacy_reference.id)
    assert denied.status_code == 403 and denied.json()["code"] == "SOURCE_UNAVAILABLE"
    identity, _, _ = ready_orphan(work)
    real_page = work.store.inventory

    def incomplete(scope, **kwargs):
        page = real_page(scope, **kwargs)
        return InventoryPage(scope, page.items, True, None, False)

    monkeypatch.setattr(work.store, "inventory", incomplete)
    readback = inventory(work)
    current = next(item for item in readback["items"] if item["id"] == str(identity))
    assert readback["coverage_complete"] is False and current["coverage_complete"] is False
    assert current["reference_count"] is None and current["formal_history"] is None
    assert current["can_quarantine"] is False
    blocked = candidate(work, identity)
    assert blocked["eligible"] is False and "reference_unknown" in blocked["reasons"]


def test_late_registration_after_named_abandonment_is_rejected(lifecycle_work):
    work = lifecycle_work
    identity, _, data = ready_orphan(work)
    with pytest.raises(DomainError) as error:
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            upload(
                session,
                work.setup.ctx,
                work.setup.product,
                data,
                work.store,
                attempt=session.get(UploadAttempt, identity),
            )
    assert error.value.code == "VERSION_CONFLICT"
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(UploadedOriginal, identity) is None
    assert work.store.inspect(identity).registration_state == "aborted"


def test_current_owner_product_tenant_and_agent_cannot_be_bypassed(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    for person in (work.setup.peer, work.setup.other_human):
        response = candidate_response(
            work,
            identity,
            headers={
                "Authorization": f"Bearer {work.setup.tokens[person]}",
            },
        )
        assert response.status_code == 403
    other_product = uuid4()
    with Session(work.setup.admin) as session, session.begin():
        session.add(
            Product(
                id=other_product,
                tenant_id=work.setup.tenant,
                owner_id=work.setup.human,
                name="Other synthetic scope",
                purpose="boundary",
                category_id=work.setup.category,
            )
        )
        session.flush()

    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{other_product}/original-lifecycle/{identity}/candidate",
        headers=work.setup.headers,
        json={"action": "quarantine"},
    )
    assert response.status_code == 403
    value = candidate(work, identity)
    agent_ctx = Context(
        work.setup.tenant, work.setup.agent, work.setup.agent, category_id=work.setup.category
    )
    with pytest.raises(DomainError) as error:
        with tenant_session(
            work.setup.engine,
            work.setup.tenant,
            actor_id=work.setup.human,
            requester_id=work.setup.human,
            category_id=work.setup.category,
        ) as session:
            domain_execute(
                session, agent_ctx, Command.model_validate(candidate_command(work, value))
            )
    assert error.value.code == "FORBIDDEN_SCOPE"
    assert count(work, LifecycleIntentRecord) == 0


def test_acl_aba_invalidates_unconsumed_preview_but_success_replay_checks_current_acl(
    lifecycle_work,
):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    old = preview_command(work, candidate_command(work, candidate(work, identity)))["command"]
    revoke(work, False)
    assert execute(work, old).json()["code"] == "FORBIDDEN_SCOPE"
    revoke(work, True)
    stale = execute(work, old)
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    _, receipt, prepared = request_intent(work, identity)
    revoke(work, False)
    assert execute(work, prepared).json()["id"] == receipt["id"]
    with Session(work.setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    assert execute(work, prepared).status_code == 403
    with Session(work.setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == work.setup.category, Grant.principal_id == work.setup.human
            )
        )
        grant.expires_at = now() + timedelta(hours=1)
    revoke(work, True)
    assert execute(work, prepared).json()["id"] == receipt["id"]
    assert count(work, Receipt, Receipt.operation == "evidence.lifecycle.quarantine") == 1


def test_same_fact_different_candidate_and_keys_reuse_original_receipt_before_t1_consumption(
    lifecycle_work,
):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    first, alias = candidate(work, identity), candidate(work, identity)
    assert first["candidate_id"] != alias["candidate_id"]
    prepared = [
        preview_command(work, candidate_command(work, value))["command"] for value in (first, alias)
    ]
    result = [execute(work, value) for value in prepared]
    assert all(row.status_code == 200 for row in result), [row.text for row in result]
    assert result[0].json()["id"] == result[1].json()["id"]
    assert count(work, LifecycleIntentRecord) == count(work, LifecycleRequest) == 1
    assert count(work, Receipt, Receipt.operation == "evidence.lifecycle.quarantine") == 1
    receipt_id = UUID(result[0].json()["id"])
    assert count(work, RequestKey, RequestKey.receipt_id == receipt_id) == 2


def test_concurrent_confirmations_of_same_basis_create_one_intent_and_receipt(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    prepared = [
        preview_command(work, candidate_command(work, candidate(work, identity)))["command"]
        for _ in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda value: execute(work, value), prepared))
    assert all(row.status_code == 200 for row in results), [row.text for row in results]
    assert results[0].json()["id"] == results[1].json()["id"]
    assert count(work, LifecycleIntentRecord) == 1
    assert count(work, Receipt, Receipt.operation == "evidence.lifecycle.quarantine") == 1


def test_final_outbox_failure_rolls_back_intent_request_object_and_confirmation(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    prepared = preview_command(work, candidate_command(work, candidate(work, identity)))["command"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        before = session.get(LifecycleObject, identity).state

    def fail_event(_mapper, _connection, target):
        if target.type == "original.lifecycle_requested":
            raise RuntimeError("Synthetic lifecycle final Outbox rollback")

    event.listen(Outbox, "before_insert", fail_event)
    try:
        with pytest.raises(RuntimeError, match="Synthetic lifecycle final Outbox rollback"):
            execute(work, prepared)
    finally:
        event.remove(Outbox, "before_insert", fail_event)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(LifecycleObject, identity).state == before
        confirmation = session.scalar(
            select(Confirmation).where(
                Confirmation.token_hash == digest(prepared["payload"]["confirmation_token"]),
            )
        )
        assert confirmation.consumed is False
    assert count(work, LifecycleIntentRecord) == count(work, LifecycleRequest) == 0
    assert count(work, Receipt, Receipt.operation == "evidence.lifecycle.quarantine") == 0
    assert execute(work, prepared).status_code == 200


def test_pending_cancel_has_no_attempt_and_worker_cannot_later_apply(lifecycle_work, monkeypatch):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    intent_id, _, _ = request_intent(work, identity)
    current = intent_state(work, intent_id)
    accepted(
        work,
        "evidence.lifecycle.cancel",
        {
            "intent_id": str(intent_id),
            "expected_revision": current.revision,
            "reason": "Named cancellation before any physical attempt",
        },
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Cancelled intent must never reach physical transport")

    monkeypatch.setattr(work.setup.engine.lifecycle_transport, "apply_once", forbidden)
    assert process(work.setup.engine, worker_reference(work, intent_id))["status"] == "cancelled"
    current = intent_state(work, intent_id)
    assert current.state == IntentState.CANCELLED and current.permit is None
    assert item_for(work, identity)["pending_intent_id"] is None


@pytest.mark.parametrize("physical_applied", [False, True])
def test_timeout_or_lost_reply_has_one_attempt_then_observe_only(
    lifecycle_work, monkeypatch, physical_applied
):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    intent_id, _, _ = request_intent(work, identity)
    transport = work.setup.engine.lifecycle_transport
    original_run, calls = transport._run, {"apply": 0, "observe": 0}

    def uncertain(request, budget):
        action = request["action"]
        calls[action] = calls.get(action, 0) + 1
        if action == "apply":
            if physical_applied:
                original_run(request, budget)
            return {"error_code": "LIFECYCLE_IO_TIMEOUT"}
        return original_run(request, budget)

    monkeypatch.setattr(transport, "_run", uncertain)
    assert process(work.setup.engine, worker_reference(work, intent_id))["status"] == "unknown"
    assert item_for(work, identity)["pending_intent_id"] == str(intent_id)
    blocked = work.client.post(
        f"/v1/categories/{work.setup.category}/commands/preview",
        headers=work.setup.headers,
        json=make_command(
            work,
            "evidence.lifecycle.cancel",
            {
                "intent_id": str(intent_id),
                "expected_revision": intent_state(work, intent_id).revision,
                "reason": "Attempted intent cannot be cancelled",
            },
        ),
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "EXTERNAL_OUTCOME_UNKNOWN"
    response = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/original-lifecycle/intents/{intent_id}/reconcile",
        headers=work.setup.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == ("applied" if physical_applied else "unknown")
    assert calls["apply"] == 1 and calls["observe"] == 1
    process(work.setup.engine, worker_reference(work, intent_id))
    assert calls["apply"] == 1
    if not physical_applied:
        assert item_for(work, identity)["pending_intent_id"] == str(intent_id)


def test_reviewed_business_write_advances_reference_epoch_and_invalidates_preview(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    prepared = preview_command(work, candidate_command(work, candidate(work, identity)))["command"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        before = session.get(Product, work.setup.product).lifecycle_epoch
        session.add(
            Artifact(
                tenant_id=work.setup.tenant,
                product_id=work.setup.product,
                owner_id=work.setup.human,
                title="Synthetic business write",
                source_label="Unverified fixture",
                content="Synthetic new evidence",
                content_hash=digest("Synthetic new evidence"),
                visibility="private",
            )
        )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(Product, work.setup.product).lifecycle_epoch > before
    stale = execute(work, prepared)
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    assert count(work, LifecycleIntentRecord) == 0


@pytest.mark.parametrize(
    "change", ["unknown_table", "unknown_column", "disabled_trigger", "disabled_category_trigger"]
)
def test_unreviewed_schema_is_unknown_and_transactional_ddl_is_always_rolled_back(
    lifecycle_work, change
):
    work = lifecycle_work
    identity, reference, _ = ready_orphan(work)
    name = f"synthetic_unreviewed_{uuid4().hex}"
    session = Session(work.setup.admin)
    try:
        if change == "unknown_table":
            session.execute(
                text(f'CREATE TABLE public."{name}" (id uuid, tenant_id uuid, product_id uuid)')
            )
        elif change == "unknown_column":
            session.execute(text(f'ALTER TABLE public.products ADD COLUMN "{name}" text'))
        elif change == "disabled_trigger":
            session.execute(
                text("ALTER TABLE public.artifact_versions DISABLE TRIGGER lifecycle_reference")
            )
        else:
            session.execute(
                text("ALTER TABLE public.claims DISABLE TRIGGER category_lifecycle_clock")
            )
        assert schema_covered(session) is False
        refs = References(session, work.setup.ctx, work.setup.product, work.store).read_current(
            reference
        )
        assert refs.reference_count is None and refs.formal_history is None
    finally:
        session.rollback()
        session.close()
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert schema_covered(session) is True
    assert item_for(work, identity)["can_quarantine"] is True


def test_product_fence_is_held_through_real_storage_effect(lifecycle_work, monkeypatch):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    intent_id, _, _ = request_intent(work, identity)
    transport = work.setup.engine.lifecycle_transport
    original_run = transport._run
    entered, release = Event(), Event()

    def paused(request, budget):
        if request["action"] == "apply":
            entered.set()
            assert release.wait(4), "Synthetic gate probe must be released"
        return original_run(request, budget)

    monkeypatch.setattr(transport, "_run", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(process, work.setup.engine, worker_reference(work, intent_id))
        try:
            assert entered.wait(5), "Effect did not acquire its protection gate"
            with pytest.raises(DBAPIError) as locked:
                with tenant_session(
                    work.setup.engine,
                    work.setup.tenant,
                    actor_id=work.setup.human,
                    requester_id=work.setup.human,
                    category_id=work.setup.category,
                ) as session:
                    session.execute(text("SET LOCAL lock_timeout='150ms'"))
                    session.add(
                        Artifact(
                            tenant_id=work.setup.tenant,
                            product_id=work.setup.product,
                            owner_id=work.setup.human,
                            title="Blocked concurrent write",
                            source_label="Synthetic",
                            content="Synthetic fenced write",
                            content_hash=digest("Synthetic fenced write"),
                            visibility="private",
                        )
                    )
                    session.flush()
            assert locked.value.orig.sqlstate == "55P03"
        finally:
            release.set()
        assert result.result(timeout=10)["status"] == "applied"


def test_rls_agent_zero_direct_access_and_immutable_candidates_and_object_identity(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    value = candidate(work, identity)
    with tenant_session(work.setup.engine, uuid4()) as session:
        for model in (
            UploadAttempt,
            LifecycleObject,
            LifecycleCandidate,
            LifecycleIntentRecord,
            LifecycleRequest,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with Session(work.setup.admin) as session:
        for table in (
            "upload_attempts",
            "lifecycle_objects",
            "lifecycle_candidates",
            "lifecycle_intents",
            "lifecycle_requests",
        ):
            assert not session.scalar(
                text(
                    "SELECT has_table_privilege('pdos_agent',:table,'SELECT,INSERT,UPDATE,DELETE')"
                ),
                {"table": table},
            )
            flags = session.execute(
                text(
                    "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE oid=CAST(:table AS regclass)"
                ),
                {"table": table},
            ).one()
            assert flags.relrowsecurity and flags.relforcerowsecurity
    with (
        pytest.raises(DBAPIError, match="immutable") as immutable,
        Session(work.setup.admin) as session,
        session.begin(),
    ):
        row = session.get(LifecycleCandidate, UUID(value["candidate_id"]))
        row.document = {**row.document, "untrusted": "rewrite"}
        session.flush()
    assert immutable.value.orig.sqlstate == "P0001"
    with (
        pytest.raises(DBAPIError, match="Exact original binding cannot change") as immutable,
        Session(work.setup.admin) as session,
        session.begin(),
    ):
        row = session.get(LifecycleObject, identity)
        row.reference = {**row.reference, "size_bytes": row.reference["size_bytes"] + 1}
        row.revision += 1
        session.flush()
    assert immutable.value.orig.sqlstate == "P0001"


def test_api_upload_retry_same_key_and_equivalent_new_key_share_one_reservation(lifecycle_work):
    work = lifecycle_work
    identity, reference, data = rolled_back_registration(work)
    original_body = data.model_dump(mode="json")
    bodies = [
        original_body,
        dict(original_body),
        {**original_body, "idempotency_key": str(uuid4())},
    ]
    responses = [
        work.client.post(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals",
            headers=work.setup.headers,
            json=body,
        )
        for body in bodies
    ]
    assert all(row.status_code == 200 for row in responses), [row.text for row in responses]
    assert len({row.json()["id"] for row in responses}) == 1
    assert all(row.json()["subject_id"] == str(identity) for row in responses)
    assert count(work, UploadAttempt) == count(work, UploadedOriginal) == 1
    assert count(work, Receipt, Receipt.operation == "evidence.original.upload") == 1
    receipt_id = UUID(responses[0].json()["id"])
    assert count(work, RequestKey, RequestKey.receipt_id == receipt_id) == 2
    assert count(work, Audit, Audit.receipt_id == receipt_id) == 1
    assert count(work, Outbox, Outbox.receipt_id == receipt_id) == 1
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        attempt = session.get(UploadAttempt, identity)
        assert attempt.status == "committed"
        assert attempt.request_key == data.idempotency_key
    assert work.store.inspect(identity).registration_state == "registered"
    assert sha256(work.store.read_original(reference)).hexdigest() == reference.content_sha256


def test_api_upload_same_key_cannot_replay_into_another_authorized_product(lifecycle_work):
    work = lifecycle_work
    data = upload_input(b"Synthetic product-bound upload replay\n")
    first = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/originals",
        headers=work.setup.headers,
        json=data.model_dump(mode="json"),
    )
    assert first.status_code == 200, first.text
    other_product = uuid4()
    with Session(work.setup.admin) as session, session.begin():
        session.add(
            Product(
                id=other_product,
                tenant_id=work.setup.tenant,
                owner_id=work.setup.human,
                name="Synthetic other upload scope",
                purpose="same-key boundary",
                category_id=work.setup.category,
            )
        )
        session.flush()

    crossed = work.client.post(
        f"/v1/categories/{work.setup.category}/products/{other_product}/originals",
        headers=work.setup.headers,
        json=data.model_dump(mode="json"),
    )
    assert crossed.status_code == 409 and crossed.json()["code"] == "DUPLICATE_INTENT_CONFLICT"
    assert count(work, UploadAttempt) == count(work, UploadedOriginal) == 1
    assert count(work, UploadAttempt, UploadAttempt.product_id == other_product) == 0
    assert count(work, UploadedOriginal, UploadedOriginal.product_id == other_product) == 0


def test_lifecycle_event_claim_and_ack_preserve_reference_epoch_before_real_effect(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    intent_id, receipt, _ = request_intent(work, identity)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        before = session.get(Product, work.setup.product).lifecycle_epoch
    deliveries = claim_events(work.setup.dispatch, work.setup.tenant)
    target = next(
        value
        for value in deliveries
        if value.subject_id == str(intent_id) and value.event_type == "original.lifecycle_requested"
    )
    assert target.category_id == str(work.setup.category)
    assert target.product_id == str(work.setup.product)
    assert target.actor_id == target.requester_id == str(work.setup.human)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(Product, work.setup.product).lifecycle_epoch == before
        inbox = session.scalar(
            select(Inbox).where(
                Inbox.event_id == UUID(target.event_id),
                Inbox.consumer == CONSUMER,
            )
        )
        assert inbox is not None
    for delivery in deliveries:
        assert (
            acknowledge(
                work.setup.dispatch,
                delivery,
                workflow_id="synthetic-controlled-lifecycle" if delivery == target else None,
                ignored=delivery != target,
            )
            is True
        )
    assert acknowledge(work.setup.dispatch, target, workflow_id="duplicate-ack") is False
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(Product, work.setup.product).lifecycle_epoch == before
        assert session.get(Outbox, UUID(target.event_id)).delivered_at is not None
        inbox = session.scalar(
            select(Inbox).where(
                Inbox.event_id == UUID(target.event_id),
                Inbox.consumer == CONSUMER,
            )
        )
        assert inbox.status == "received"
        assert inbox.workflow_id == "synthetic-controlled-lifecycle"
    result = process(work.setup.engine, worker_reference(work, intent_id))
    assert result["status"] == "applied", result
    assert item_for(work, identity)["disposition"] == "quarantined"
    assert count(work, Receipt, Receipt.operation == "evidence.lifecycle.quarantine") == 1
    assert count(work, Outbox, Outbox.receipt_id == UUID(receipt["id"])) == 1


def test_private_consumer_blocks_cleanup_without_exposing_its_body(lifecycle_work):
    work = lifecycle_work
    identity, _, _ = ready_orphan(work)
    response = execute(
        work,
        make_command(
            work,
            "evidence.artifact.register",
            {
                "title": "Synthetic shared reference context",
                "source_label": "Synthetic",
                "content": "Synthetic reference context: " + str(identity),
                "visibility": "category",
            },
        ),
    )
    assert response.status_code == 200, response.text
    source = response.json()
    assert item_for(work, identity)["can_quarantine"] is True
    value = make_command(
        work,
        "evidence.claim.record",
        {
            "artifact_id": source["subject_id"],
            "line": 1,
            "quote": str(identity),
            "statement": "Synthetic peer private consuming reference",
            "nature": "extracted",
            "availability": "known",
            "visibility": "private",
        },
    )
    value["source_read_set"] = [{"artifact_id": source["subject_id"], "expected_revision": 1}]
    peer_headers = {"Authorization": "Bearer " + work.setup.tokens[work.setup.peer]}
    saved = execute(work, value, headers=peer_headers)
    assert saved.status_code == 200, saved.text
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.human,
        requester_id=work.setup.human,
        category_id=work.setup.category,
    ) as session:
        assert session.get(Claim, UUID(saved.json()["subject_id"])) is None
    item = item_for(work, identity)
    assert item["can_quarantine"] is False and item["reference_count"] > 0
    assert item["formal_history"] is True and "referenced" in item["reasons"]
    assert "Synthetic peer private consuming reference" not in str(inventory(work))
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.setup.peer,
        requester_id=work.setup.peer,
        category_id=work.setup.category,
    ) as session:
        result = session.execute(
            text("SELECT * FROM lifecycle_reference_summary(:t,:c,:p,CAST(:roots AS uuid[]))"),
            {
                "t": work.setup.tenant,
                "c": work.setup.category,
                "p": work.setup.product,
                "roots": [identity],
            },
        ).all()
        assert result == []


def test_category_original_lifecycle_with_unbounded_membership(lifecycle_work):
    work, setup = lifecycle_work, lifecycle_work.setup
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        grant.expires_at = None
    data = upload_input(b"Synthetic category lifecycle retained original\n")
    path = f"/v1/categories/{setup.category}/originals"
    uploaded = work.client.post(path, headers=setup.headers, json=data.model_dump(mode="json"))
    assert uploaded.status_code == 200, uploaded.text
    identity = uploaded.json()["subject_id"]
    response = work.client.get(
        f"/v1/categories/{setup.category}/original-lifecycle", headers=setup.headers
    )
    assert response.status_code == 200, response.text
    item = next(v for v in response.json()["items"] if v["id"] == identity)
    assert item["registered"] and item["reference_count"] is not None
    candidate = work.client.post(
        f"/v1/categories/{setup.category}/original-lifecycle/{identity}/candidate",
        headers=setup.headers,
        json={"action": "quarantine"},
    )
    assert candidate.status_code == 200, candidate.text
    assert candidate.json()["eligible"] is False
