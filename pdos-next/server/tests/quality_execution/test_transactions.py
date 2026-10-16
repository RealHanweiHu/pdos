"""Fixed-failure quality host transaction checks; root runs the guarded PG target."""

# ruff: noqa: F811 - imported pytest fixtures register the complete parent tree

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_project_first_plan import accepted, post

from pdos_next.contracts import Command
from pdos_next.database import tenant_session
from pdos_next.domain.professional_authority import service as professional
from pdos_next.domain.quality_execution.models import (
    QualityEventFailureLink,
    QualityFailureMap,
    QualityIssueCurrent,
    QualityIssueVersion,
    QualityPolicyCurrent,
    QualityPolicyFact,
)
from pdos_next.domain.verification_results.models import TestResultProjection
from pdos_next.errors import DomainError
from pdos_next.models import Artifact, Outbox, Receipt, now
from pdos_next.service import Context, execute
from quality_execution.fixtures import (  # noqa: F401
    accepted_work,
    command,
    counts,
    create_issue,
    current_rows,
    issue_current,
    known_configuration,
    launch_work,
    listing,
    operational_work,
    payload_create,
    publish_policy,
    quality_work,
    ready_work,
    result_command,
    results_work,
    triage,
    unconsumed,
)


def test_definite_fail_create_triage_containment_capa_retains_test_and_unknown_conclusions(
    quality_work,
):
    work = quality_work
    publish_policy(work)
    baseline = counts(work)
    original = current_rows(work)
    first, _ = create_issue(work)
    issue_id = first["result"]["issue_id"]
    second, _ = triage(work, first)
    value = command(
        work,
        "quality.issue.containment.record",
        {
            "issue_id": issue_id,
            "expected_issue_revision": 2,
            "action": {
                "id": str(uuid4()),
                "text": "Synthetic containment observed by the named person.",
                "executor_id": str(work.quality.human),
                "evidence": [work.containment_source.model_dump(mode="json")],
                "at": {
                    "occurred_at": now().isoformat(),
                    "original_timezone": "UTC",
                    "source": work.containment_source.model_dump(mode="json"),
                },
            },
        },
    )
    third, _ = accepted(work.quality, value)
    fixed = issue_current(work, issue_id)
    capa_id = uuid4()
    value = command(
        work,
        "quality.capa.draft",
        {
            "issue_id": issue_id,
            "expected_issue_revision": 3,
            "capa_id": str(capa_id),
            "hypotheses": [
                {
                    "text": "Synthetic hypothesis, not a root cause.",
                    "sources": [work.hypothesis_source.model_dump(mode="json")],
                }
            ],
            "actions": [
                {
                    "id": str(uuid4()),
                    "kind": "corrective",
                    "text": "Planned investigation only",
                    "executor_id": str(work.quality.human),
                }
            ],
            "requirement": {
                "method": "Separate new verification run",
                "acceptance": "All fixed affected pairs pass",
                "observation_until": (now() + timedelta(days=1)).isoformat(),
                "required_failure_ids": [f["identity"] for f in fixed["issue"]["failures"]],
            },
        },
    )
    fourth = post(work.quality, value)
    assert fourth.status_code == 200, fourth.text
    view = listing(work)
    saved = next(row for row in view["issues"] if row["revision"] == 4)
    assert saved["id"] == fourth.json()["subject_id"]
    assert saved["issue"]["root_cause"] is None and saved["issue"]["closure"] is None
    assert saved["issue"]["capa"]["id"] == str(capa_id)
    assert saved["issue"]["capa"]["actions"][0]["completion"] is None
    assert saved["issue"]["capa"]["effectiveness"] is None
    assert saved["followup_needs"][0]["created_output"] is None
    assert not saved["capabilities"]["quality.issue.close"]
    assert view["policy"]["risk"] == "high" and view["policy"]["independent_verification"] is True
    assert {row["revision"] for row in view["issues"]} == {1, 2, 3, 4}
    unchanged = current_rows(work)
    assert unchanged.row.id == original.row.id and unchanged.run == original.run
    assert unchanged.request.id == original.request.id
    after = counts(work)
    assert (
        after[QualityIssueVersion.__tablename__] == baseline[QualityIssueVersion.__tablename__] + 4
    )
    for cls in (Receipt, Outbox):
        assert after[cls.__tablename__] == baseline[cls.__tablename__] + 4
    assert [
        first["subject_revision"],
        second["subject_revision"],
        third["subject_revision"],
        fourth.json()["subject_revision"],
    ] == [1, 2, 3, 4]


def test_fixed_failure_replay_across_title_key_and_later_event_keeps_one_created_receipt(
    quality_work,
):
    work = quality_work
    first, value = create_issue(work)
    baseline = counts(work)
    replay = post(work.quality, value)
    assert replay.status_code == 200 and replay.json()["id"] == first["id"]
    alias = deepcopy(value)
    alias.update(command_id=str(uuid4()), idempotency_key=str(uuid4()))
    assert post(work.quality, alias).json()["id"] == first["id"]
    # An unrelated later professional result version retains this exact failure.
    reviewed, _ = accepted(work.quality, result_command(work, "test.run.review"))
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        later_event = session.scalar(
            select(Outbox.id).where(Outbox.receipt_id == UUID(reviewed["id"]))
        )
    after_review = counts(work)
    second, _ = create_issue(work, event_id=later_event, title="Different title, original failure")
    assert second["id"] == first["id"] and second["subject_id"] == first["subject_id"]
    after = counts(work)
    for cls in (QualityIssueVersion, QualityFailureMap, Receipt, Outbox):
        assert after[cls.__tablename__] == after_review[cls.__tablename__]
    assert (
        after[QualityEventFailureLink.__tablename__]
        == baseline[QualityEventFailureLink.__tablename__] + 1
    )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        links = list(
            session.scalars(
                select(QualityEventFailureLink).where(
                    QualityEventFailureLink.issue_id == UUID(first["result"]["issue_id"])
                )
            )
        )
        assert {link.event_id for link in links} == {work.failure_event, later_event}
        assert {link.run_revision for link in links} == {
            work.failure_run.revision,
            work.failure_run.revision + 1,
        }


def test_one_result_event_with_two_failures_creates_two_then_merge_retains_recheck_block(
    quality_work,
):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work, 0)
    second, _ = create_issue(work, 1)
    assert first["result"]["issue_id"] != second["result"]["issue_id"]
    value = command(
        work,
        "quality.issue.merge",
        {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "sources": [{"id": second["result"]["issue_id"], "revision": 1}],
            "reason": "Synthetic human-reviewed common scope",
        },
    )
    receipt, prepared = accepted(work.quality, value)
    view = listing(work)  # The Run/Build selector must retain the original merged Issue.
    target_id, original_id = first["result"]["issue_id"], second["result"]["issue_id"]
    assert set(view["current_by_issue"]) == {target_id, original_id}
    current = next(
        row
        for row in view["issues"]
        if row["id"] == view["current_by_issue"][target_id]["issue_version_id"]
    )
    assert current["issue"]["needs_recheck"] is True and len(current["issue"]["failures"]) == 2
    assert not any(current["capabilities"].values())
    alias = next(
        row
        for row in view["issues"]
        if row["id"] == view["current_by_issue"][original_id]["issue_version_id"]
    )
    assert alias["is_current"] is True and alias["issue"]["merged_into"] == target_id
    assert not any(alias["capabilities"].values())
    for identity, original_receipt in ((target_id, first), (original_id, second)):
        history = [row for row in view["issues"] if row["issue_id"] == identity]
        assert {row["revision"] for row in history} == {1, 2}
        initial = next(row for row in history if row["revision"] == 1)
        assert initial["id"] == original_receipt["subject_id"] and not initial["is_current"]
        assert not any(initial["capabilities"].values())
    replay = post(work.quality, prepared)
    assert replay.status_code == 200 and replay.json()["id"] == receipt["id"]
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        mappings = list(session.scalars(select(QualityFailureMap)))
        assert {m.issue_id for m in mappings} == {UUID(first["result"]["issue_id"])}


def test_create_concurrent_titles_are_one_failure_identity_and_one_created_event(quality_work):
    work = quality_work
    commands = [
        command(work, "quality.issue.create", payload_create(work, title=title))
        for title in ("Concurrent A", "Concurrent B")
    ]
    before = counts(work)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda value: post(work.quality, value), commands))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    after = counts(work)
    for cls in (
        QualityIssueVersion,
        QualityIssueCurrent,
        QualityFailureMap,
        QualityEventFailureLink,
        Receipt,
        Outbox,
    ):
        assert after[cls.__tablename__] == before[cls.__tablename__] + 1


def test_current_policy_missing_and_withdrawn_do_not_default_to_low_risk(quality_work):
    work = quality_work
    first, _ = create_issue(work)
    value = {
        "issue_id": first["result"]["issue_id"],
        "expected_issue_revision": 1,
        "reason": "Cannot guess risk",
    }
    before = counts(work)
    from test_project_first_plan import cmd

    raw = cmd(work.quality, "quality.issue.triage", value)
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution/inputs",
        headers=work.quality.headers,
        json=raw,
    )
    assert response.status_code == 503 and response.json()["code"] == "INTERNAL_ERROR"
    assert counts(work) == before
    published = publish_policy(work)
    prepared = post(work.quality, command(work, "quality.issue.triage", value), True).json()[
        "command"
    ]
    publish_policy(work, previous=published, state="withdrawn")
    before = counts(work)
    refused = post(work.quality, prepared)
    assert refused.status_code == 409 and refused.json()["code"] == "SOURCE_STALE"
    unconsumed(work, prepared["payload"]["confirmation_token"])
    assert counts(work) == before


def test_outbox_failure_rolls_back_issue_version_pointer_and_common_confirmation(quality_work):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work)
    value = command(
        work,
        "quality.issue.triage",
        {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "reason": "Synthetic atomic failure probe",
        },
    )
    reviewed = post(work.quality, value, True)
    assert reviewed.status_code == 200, reviewed.text
    prepared = reviewed.json()["command"]
    before = counts(work)

    def fail(mapper, connection, target):
        if target.type == "issue.triaged":
            raise RuntimeError("synthetic-quality-final-outbox-failure")

    event.listen(Outbox, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic-quality-final-outbox-failure"):
            post(work.quality, prepared)
    finally:
        event.remove(Outbox, "before_insert", fail)
    assert counts(work) == before
    unconsumed(work, prepared["payload"]["confirmation_token"])
    assert issue_current(work, first["result"]["issue_id"])["revision"] == 1


def test_source_revocation_and_named_scope_apply_before_successful_receipt_replay(
    quality_work, monkeypatch
):
    from pdos_next import quality_result_bridge

    work = quality_work
    first, value = create_issue(work)
    before = counts(work)
    retained_calls = []
    inspect_retained = quality_result_bridge.inspect_retained_execution

    def retained(*args, **kwargs):
        retained_calls.append(True)
        return inspect_retained(*args, **kwargs)

    monkeypatch.setattr(quality_result_bridge, "inspect_retained_execution", retained)
    refused = post(work.engineer, value)
    assert refused.status_code == 403 and refused.json()["code"] == "QUALIFICATION_REQUIRED", (
        refused.text
    )
    assert not retained_calls
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        with pytest.raises(DomainError) as error:
            execute(
                session,
                Context(work.setup.tenant, work.setup.agent, work.setup.agent),
                Command.model_validate(value),
            )
        assert error.value.reason == "FORBIDDEN_SCOPE"
    with Session(work.setup.admin) as session, session.begin():
        session.execute(
            update(Artifact).where(Artifact.id == work.failure_report).values(status="withdrawn")
        )
    refused = post(work.quality, value)
    assert refused.status_code == 200 and refused.json()["id"] == first["id"]
    fresh = {
        **value,
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "operation": "quality.issue.triage",
        "payload": {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "reason": "New triage requires current sources",
        },
    }
    rejected = post(work.quality, fresh)
    assert rejected.status_code in {403, 409} and rejected.json()["code"] == "SOURCE_UNAVAILABLE"
    assert counts(work) == before
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        assert session.get(Receipt, UUID(first["id"])) is not None


@pytest.mark.parametrize("issuer_kind", ["professional", "resource"])
def test_original_bytes_read_runtime_revocation_is_atomic(quality_work, monkeypatch, issuer_kind):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work, 0)
    second, _ = create_issue(work, 1)
    # Merge remains a T1 action with a complete retained boundary. Direct
    # triage/containment use their saved Issue/source watermarks instead.
    value = command(
        work,
        "quality.issue.merge",
        {
            "issue_id": first["result"]["issue_id"],
            "expected_issue_revision": 1,
            "sources": [{"id": second["result"]["issue_id"], "revision": 1}],
            "reason": "Original-byte callback revocation probe",
        },
    )
    reviewed = post(work.quality, value, True)
    assert reviewed.status_code == 200, reviewed.text
    prepared = reviewed.json()["command"]
    before = counts(work)
    original = work.report_store.read_original
    fired = []

    def revoke(reference):
        content = original(reference)
        if not fired:
            fired.append(reference.id)
            if issuer_kind == "professional":
                professional.disable_issuer(work.setup.engine, work.professional_issuer.key)
            else:
                from pdos_next.domain.test_resources import service as resources

                resources.disable_issuer(work.setup.engine, work.test_issuer.key)
        return content

    monkeypatch.setattr(work.report_store, "read_original", revoke)
    refused = post(work.quality, prepared)
    assert fired and refused.status_code == 409, refused.text
    assert refused.json()["code"] == "SOURCE_STALE" and counts(work) == before
    unconsumed(work, prepared["payload"]["confirmation_token"])


def test_policy_and_issue_storage_is_immutable_scoped_and_agent_has_zero_write(quality_work):
    work = quality_work
    publish_policy(work)
    first, _ = create_issue(work)
    targets = (
        QualityIssueVersion,
        QualityIssueCurrent,
        QualityFailureMap,
        QualityEventFailureLink,
        QualityPolicyFact,
        QualityPolicyCurrent,
    )
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        tables = [cls.__tablename__ for cls in targets]
        privileges = session.execute(
            text(
                "SELECT name, has_table_privilege('pdos_agent', name, 'INSERT') "
                "OR has_table_privilege('pdos_agent', name, 'UPDATE') "
                "OR has_table_privilege('pdos_agent', name, 'DELETE') "
                "FROM unnest(CAST(:names AS text[])) name"
            ),
            {"names": tables},
        ).all()
        assert len(privileges) == 6 and all(value is False for _, value in privileges)
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            session.execute(
                update(QualityIssueVersion)
                .where(QualityIssueVersion.id == UUID(first["subject_id"]))
                .values(reason="forged")
            )
    with Session(work.setup.admin) as session, session.begin():
        with pytest.raises(DBAPIError, match="immutable"):
            session.execute(
                update(QualityIssueVersion)
                .where(QualityIssueVersion.id == UUID(first["subject_id"]))
                .values(reason="forged")
            )
        session.rollback()
    with tenant_session(work.setup.engine, uuid4()) as session:
        assert session.get(QualityIssueVersion, UUID(first["subject_id"])) is None


def test_projection_or_arbitrary_event_cannot_relabel_an_unverified_result_as_failure(quality_work):
    work = quality_work
    forged = payload_create(work, event_id=uuid4())
    from test_project_first_plan import cmd

    value = cmd(work.quality, "quality.issue.create", forged)
    before = counts(work)
    response = work.quality.client.post(
        f"/v1/categories/{work.setup.category}/products/{work.setup.product}/quality-execution/inputs",
        headers=work.quality.headers,
        json=value,
    )
    assert response.status_code == 403 and response.json()["code"] == "SOURCE_UNAVAILABLE"
    assert counts(work) == before
    with tenant_session(
        work.setup.engine,
        work.setup.tenant,
        actor_id=work.quality.ctx.actor_id,
        requester_id=work.quality.ctx.requester_id,
        category_id=work.setup.category,
    ) as session:
        original = session.scalar(
            select(TestResultProjection).where(TestResultProjection.run_id == work.failure_run.id)
        )
        assert original is not None and original.result == "fail"
