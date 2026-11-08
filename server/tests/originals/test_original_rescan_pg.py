"""Scheduled renewal of aged-out clean scan receipts (D215), with real PG and API paths."""

import time
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from originals.test_original_security import (
    download,
    parsed,
    scan_result,
    security_work,  # noqa: F401
    uploaded,
)
from pdos_next.core.database import tenant_session
from pdos_next.core.models import (
    Grant,
    OriginalScanRequest,
    OriginalScanResult,
    OriginalSecurity,
    Outbox,
    UploadedOriginal,
    now,
)
from pdos_next.evidence_security.types import ScanConfiguration, ScanStatus
from pdos_next.originals.rescan import rescan_expired
from pdos_next.originals.security import configure, view


@pytest.fixture
def rescan_work(security_work):  # noqa: F811
    return security_work


def age_scan(work, original_id, hours):
    """Make the current receipt look `hours` old: shift its request and result times."""
    with Session(work.setup.admin) as session, session.begin():
        session.execute(text("SET LOCAL session_replication_role = replica"))
        state = session.scalar(
            select(OriginalSecurity).where(OriginalSecurity.original_id == original_id)
        )
        request = session.get(OriginalScanRequest, state.current_request_id)
        result = session.scalar(
            select(OriginalScanResult).where(OriginalScanResult.request_id == request.id)
        )

        def earlier(value):
            from datetime import datetime

            return (datetime.fromisoformat(value) - timedelta(hours=hours)).isoformat()

        request.binding = {
            **request.binding, "requested_at": earlier(request.binding["requested_at"]),
        }
        result.result = {
            **result.result,
            "started_at": earlier(result.result["started_at"]),
            "completed_at": earlier(result.result["completed_at"]),
        }


def security(work, original_id, principal=None):
    principal = principal or work.setup.human
    with tenant_session(
        work.setup.engine, work.setup.tenant, actor_id=principal, requester_id=principal,
        category_id=work.setup.category,
    ) as session:
        original = session.get(UploadedOriginal, original_id)
        ctx = replace(work.setup.ctx, actor_id=principal, requester_id=principal)
        return view(session, original, ctx)


def current_request(work, original_id):
    with Session(work.setup.admin) as session:
        return session.scalar(
            select(OriginalSecurity.current_request_id).where(
                OriginalSecurity.original_id == original_id
            )
        )


def rescan(work):
    return rescan_expired(work.setup.engine, work.setup.dispatch, work.setup.tenant)


def scanned(work, request_id):
    return scan_result(work, {"subject_id": str(request_id)})


def long_grants(work, *principals):
    with Session(work.setup.admin) as session, session.begin():
        for row in session.scalars(
            select(Grant).where(Grant.principal_id.in_(principals))
        ):
            row.expires_at = now() + timedelta(days=3)


def test_aged_out_clean_original_is_rescanned_and_citable_again(rescan_work):
    work = rescan_work
    long_grants(work, work.setup.human)
    original = uploaded(work)
    parsed(work, original)
    age_scan(work, original, 23)
    assert rescan(work)["requested"] == 0  # Still valid: nothing to renew.
    age_scan(work, original, 2)
    before = security(work, original)
    assert before["state"] == "stale"
    assert before["reasons"] == ["SCAN_EXPIRED", "RESCAN_SCHEDULED"]
    assert download(work, original).json()["code"] == "SOURCE_UNAVAILABLE"
    old_request = current_request(work, original)

    result = rescan(work)

    assert result["requested"] == 1 and result["failed"] == 0
    request_id = current_request(work, original)
    assert request_id != old_request
    with Session(work.setup.admin) as session:
        request = session.get(OriginalScanRequest, request_id)
        assert request.requester_id == work.setup.human
        assert session.scalar(
            select(Outbox.type).where(Outbox.subject_id == request_id)
        ) == "original.scan_requested"
    # In flight: shown as scanning, and a second pass does not ask again.
    assert security(work, original)["state"] == "scanning"
    assert rescan(work)["requested"] == 0
    assert scanned(work, request_id)["status"] == "clean"
    after = security(work, original)
    assert after["state"] == "clean" and after["reasons"] == []
    assert download(work, original).status_code == 200
    assert rescan(work) == {"requested": 0, "current": 0, "failed": 0, "failures": {}}


def test_failed_rescan_keeps_its_reason_visible_and_is_not_repeated(rescan_work):
    work = rescan_work
    long_grants(work, work.setup.human)
    original = uploaded(work)
    parsed(work, original)
    age_scan(work, original, 25)
    assert rescan(work)["requested"] == 1
    work.scanner.status = ScanStatus.UNAVAILABLE
    assert scanned(work, current_request(work, original))["status"] == "unavailable"
    failed = security(work, original)
    assert failed["state"] == "scan_failed"
    assert failed["reasons"] == ["SYNTHETIC_UNAVAILABLE"]
    assert failed["scan"]["error_code"] == "SYNTHETIC_UNAVAILABLE"
    # Only clean receipts are renewed automatically; a person can still ask again.
    assert rescan(work)["requested"] == 0
    assert failed["capabilities"]["scan"] is True


def test_requester_without_access_is_shown_instead_of_silently_skipped(rescan_work):
    work = rescan_work
    long_grants(work, work.setup.peer)
    with Session(work.setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(Grant.principal_id == work.setup.human))
        grant.expires_at = now() + timedelta(seconds=6)
        expires = grant.expires_at
    original = uploaded(work, visibility="category")
    parsed(work, original)
    age_scan(work, original, 25)
    time.sleep(max(0.0, (expires - now()).total_seconds()) + 0.5)
    shown = security(work, original, work.setup.peer)
    assert shown["state"] == "stale"
    assert shown["reasons"] == ["SCAN_EXPIRED", "RESCAN_REQUESTER_UNAVAILABLE"]
    result = rescan(work)
    assert result["requested"] == 0 and result["failed"] == 1
    assert current_request(work, original) is not None


def test_scanner_update_renews_receipts_made_under_the_old_configuration(rescan_work):
    work = rescan_work
    long_grants(work, work.setup.human)
    original = uploaded(work)
    parsed(work, original)
    changed = replace(
        work.runtime,
        configuration=ScanConfiguration(
            replace(work.runtime.configuration.scanner, rules_version="fixture-rules@2"),
            work.runtime.configuration.policy,
        ),
    )
    configure(work.setup.engine, changed)
    shown = security(work, original)
    assert shown["reasons"] == ["SCANNER_CONFIGURATION_CHANGED", "RESCAN_SCHEDULED"]
    assert rescan(work)["requested"] == 1
    assert scanned(work, current_request(work, original))["status"] == "clean"
    assert security(work, original)["state"] == "clean"
    assert download(work, original).status_code == 200


def test_candidate_references_need_the_dispatch_grant_and_the_matching_tenant(rescan_work):
    work = rescan_work
    statement = text(
        "SELECT original_id FROM original_rescan_candidates(:t,:at,'{}'::jsonb,'{}'::jsonb,"
        "NULL,NULL,10)"
    )
    long_grants(work, work.setup.human)
    original = uploaded(work)
    parsed(work, original)
    values = {"t": work.setup.tenant, "at": now()}
    with tenant_session(work.setup.dispatch, work.setup.tenant) as session:
        assert session.execute(statement, values).scalars().all() == [UUID(str(original))]
    with tenant_session(work.setup.dispatch, work.setup.other_tenant) as session:
        assert session.execute(statement, values).scalars().all() == []
    with Session(work.setup.admin) as session:
        for role in ("pdos_next_app", "pdos_agent", "pdos_next_auth"):
            assert not session.scalar(
                text(
                    "SELECT has_function_privilege(:role,'public.original_rescan_candidates("
                    "uuid,timestamptz,jsonb,jsonb,timestamptz,uuid,integer)','EXECUTE')"
                ),
                {"role": role},
            )
