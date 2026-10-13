"""Useful negative host transactions; written here, executed only by root."""

# ruff: noqa: F811 - register shared fixture dependencies explicitly
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, post
from verification_results.fixtures import (  # noqa: F401
    accepted_work,
    capture,
    command,
    current_rows,
    known_configuration,
    launch_work,
    listing,
    operational_work,
    ready_work,
    results_work,
    upload_report,
)
from verification_results.test_transactions import counts

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.verification_results.models import (
    MeasurementImportCapture,
    MeasurementRecord,
    TestResultActionFact,
    TestResultProjection,
)
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Confirmation, Principal, Receipt
from pdos_next.service import Context, digest, execute


def unconsumed(work, token):
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        assert (
            session.scalar(
                select(Confirmation.consumed).where(Confirmation.token_hash == digest(token))
            )
            is False
        )


def test_capture_stable_key_and_unknown_original_value_remain_explicit(results_work):
    work = results_work
    rows = deepcopy(work.report_rows)
    rows[0].update(raw_value=None, executor_id=None, calibration=None)
    source = upload_report(work, rows)
    captured, input = capture(
        work, (0, 1), artifact_id=source, key="stable-synthetic-report-capture"
    )
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results/captures",
        headers=work.quality.headers,
        json=input,
    )
    assert response.status_code == 200, response.text
    assert response.json()["capture"]["id"] == captured["capture"]["id"]
    changed = {**input, "reason": "Different original capture intent"}
    conflict = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results/captures",
        headers=work.quality.headers,
        json=changed,
    )
    assert conflict.status_code == 409 and conflict.json()["detail"]["reason"] == "DUPLICATE_INTENT_CONFLICT"
    accepted(work.quality, command(work, "test.results.import", captured=captured, final=True))
    result = current_rows(work)
    assert result.run.status == "results_pending" and result.run.result == "indeterminate"
    assert result.run.measurements[0].raw_value is None
    assert result.run.measurements[0].missing
    assert result.run.measurements[1].raw_value == "10.0000"
    # A terminal successor never permits a new candidate from old running v2;
    # the original exact key remains a readable immutable draft.
    before_replay = counts(work)
    old_key = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results/captures",
        headers=work.quality.headers,
        json=input,
    )
    assert old_key.status_code == 200, old_key.text
    assert old_key.json()["capture"]["id"] == captured["capture"]["id"]
    new_key = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/verification-results/captures",
        headers=work.quality.headers,
        json={**input, "capture_key": str(uuid4())},
    )
    assert new_key.status_code == 409 and new_key.json()["detail"]["reason"] == "VERSION_CONFLICT"
    assert counts(work) == before_replay
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        measured = session.scalar(
            select(MeasurementRecord).where(
                MeasurementRecord.run_id == work.binding.run_id,
                MeasurementRecord.sample_id == UUID(rows[0]["sample_id"]),
            )
        )
        assert measured.verified_observation["observation"]["executor_id"] is None
        assert measured.verified_observation["observation"]["calibration"] is None


def test_full_previously_returned_values_support_final_empty_batch_without_consuming_again(
    results_work,
):
    work = results_work
    captured, _ = capture(work, (0, 1))
    accepted(work.quality, command(work, "test.results.import", captured=captured))
    prior = current_rows(work)
    baseline = counts(work)
    accepted(work.quality, command(work, "test.results.import", final=True))
    final = current_rows(work)
    assert final.run.status == "results_pending" and final.run.result == "pass"
    assert final.run.measurements == prior.run.measurements
    assert (
        counts(work)[MeasurementRecord.__tablename__] == baseline[MeasurementRecord.__tablename__]
    )


def test_report_source_withdrawal_blocks_pending_confirm_and_receipt_replay_keeps_history(
    results_work,
):
    work = results_work
    captured, _ = capture(work, (0,))
    value = command(work, "test.results.import", captured=captured)
    preview = post(work.quality, value, True)
    assert preview.status_code == 200, preview.text
    prepared = preview.json()["command"]
    token = prepared["payload"]["confirmation_token"]
    before = counts(work)
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact).where(Artifact.id == work.report_artifact).values(status="withdrawn")
        )
    refused = post(work.quality, prepared)
    assert refused.status_code == 409 and refused.json()["detail"]["reason"] == "SOURCE_UNAVAILABLE"
    assert counts(work) == before and current_rows(work).run.status == "running"
    unconsumed(work, token)
    # A second independent report can be formally recorded. Withdrawal blocks
    # new decisions; the same successful request still returns its history
    # under the caller's current read scope (v1.1 §08.3).
    source = upload_report(work, work.report_rows)
    captured, _ = capture(work, (0,), artifact_id=source)
    receipt, prepared = accepted(
        work.quality, command(work, "test.results.import", captured=captured)
    )
    saved_counts = counts(work)
    with Session(work.setup.admin) as session, session.begin():
        session.execute(update(Artifact).where(Artifact.id == source).values(status="withdrawn"))
    recovered = post(work.quality, prepared)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["id"] == receipt["id"]
    assert counts(work) == saved_counts
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        assert session.get(Receipt, UUID(receipt["id"])) is not None
        assert (
            session.scalar(
                select(func.count())
                .select_from(MeasurementRecord)
                .where(MeasurementRecord.run_id == work.binding.run_id)
            )
            == 1
        )


def test_concurrent_imports_same_run_cas_commit_exactly_one_atomic_group(results_work):
    work = results_work
    first, _ = capture(work, (0,))
    second, _ = capture(work, (1,))
    commands = [command(work, "test.results.import", captured=c) for c in (first, second)]
    prepared = []
    for value in commands:
        reviewed = post(work.quality, value, True)
        assert reviewed.status_code == 200, reviewed.text
        prepared.append(reviewed.json()["command"])
    before = counts(work)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda value: post(work.quality, value), prepared))
    assert sorted(response.status_code for response in responses) == [200, 409]
    losing = next(response for response in responses if response.status_code == 409)
    assert losing.json()["detail"]["reason"] == "VERSION_CONFLICT"
    after = counts(work)
    assert after[MeasurementRecord.__tablename__] == before[MeasurementRecord.__tablename__] + 1
    assert (
        after[TestResultActionFact.__tablename__] == before[TestResultActionFact.__tablename__] + 1
    )
    assert after[Receipt.__tablename__] == before[Receipt.__tablename__] + 1
    assert len(current_rows(work).run.measurements) == 1
    for value, response in zip(prepared, responses, strict=True):
        if response.status_code == 409:
            unconsumed(work, value["payload"]["confirmation_token"])
            # The winner added a real event source to the current Formal chain.
            # Supplying that complete read-set cannot turn the old expected
            # version into a new intent or allow another measurement commit.
            refreshed = deepcopy(value)
            current = current_rows(work)
            reads = {
                row["artifact_id"]: row["expected_revision"]
                for row in (
                    *refreshed["source_read_set"],
                    *current.request.required_source_read_set,
                )
            }
            refreshed["source_read_set"] = [
                {"artifact_id": identity, "expected_revision": revision}
                for identity, revision in sorted(reads.items())
            ]
            stale = post(work.quality, refreshed, True)
            assert stale.status_code == 409 and stale.json()["detail"]["reason"] == "VERSION_CONFLICT"
            assert counts(work) == after
            assert len(current_rows(work).run.measurements) == 1
            unconsumed(work, value["payload"]["confirmation_token"])


def test_quality_current_role_and_exact_scope_cannot_be_supplied_by_client_or_agent(results_work):
    work = results_work
    captured, _ = capture(work, (0,))
    value = command(work, "test.results.import", captured=captured)
    refused = post(work.engineer, value, True)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "FORBIDDEN_SCOPE"
    assert refused.json()["detail"]["reason"] == "FORBIDDEN_OPERATION"
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        with pytest.raises(DomainError) as error:
            execute(
                session,
                Context(work.setup.tenant, work.setup.agent, work.setup.agent),
                Command.model_validate(value),
            )
        assert error.value.reason == "FORBIDDEN_SCOPE"
    changed = deepcopy(value)
    changed["payload"]["tenant_id"] = str(work.setup.tenant)
    refused = post(work.quality, changed, True)
    assert refused.status_code == 422 and refused.json()["detail"]["reason"] == "INVALID_PAYLOAD"
    changed = deepcopy(value)
    changed["payload"]["run_id"] = str(uuid4())
    refused = post(work.quality, changed, True)
    assert refused.status_code == 403 and refused.json()["detail"]["reason"] == "FORBIDDEN_SCOPE"


def test_result_tables_are_immutable_and_rls_agent_zero_write(results_work):
    work = results_work
    captured, _ = capture(work, (0, 1))
    accepted(work.quality, command(work, "test.results.import", captured=captured, final=True))
    with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
        identities = {
            model: session.scalar(select(model.id).where(model.run_id == work.binding.run_id))
            for model in (
                MeasurementImportCapture,
                MeasurementRecord,
                TestResultActionFact,
                TestResultProjection,
            )
        }
    for model, identity in identities.items():
        with pytest.raises(DBAPIError, match="permission denied"):
            with tenant_session(work.setup.engine, work.setup.tenant, actor_id=work.quality.human, category_id=work.setup.category) as session:
                session.execute(update(model).where(model.id == identity).values(status="tampered"))
        with pytest.raises(DBAPIError, match="immutable"):
            with Session(work.setup.admin) as session, session.begin():
                session.execute(update(model).where(model.id == identity).values(status="tampered"))
    with Session(work.setup.admin) as session:
        other = session.get(Principal, work.setup.other_human).tenant_id
        for model in identities:
            assert (
                session.scalar(
                    text("SELECT has_table_privilege('pdos_agent',:table,'INSERT')"),
                    {"table": model.__tablename__},
                )
                is False
            )
    with tenant_session(work.setup.engine, other) as session:
        for model in identities:
            assert session.scalar(select(func.count()).select_from(model)) == 0
