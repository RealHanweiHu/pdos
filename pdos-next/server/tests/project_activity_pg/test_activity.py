"""Actual domain facts feed one immutable common receipt each; root alone runs PG.

Reuse the existing guarded G0/work, Build execution and named release chains.
No activity, business fact, Current, receipt, qualification or audience is forged.
The only administrative mutation is the final explicit Grant-expiry negative case.
"""

# ruff: noqa: F811 -- imported pytest fixtures register their real dependency tree.

import base64
import json
import re
from copy import copy, deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from g0_fixture import create_g0_project
from manufacturing_preparation.publication_pg_helpers import publication_case  # noqa: F401
from release_policy_transactions import test_decisions as release_chain
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session
from test_build_execution import (  # noqa: F401 -- register the complete real fixture tree
    actual_command,
    allocation_command,
    configuration,
    definition,
    output_command,
    planned,
    project,
)
from test_project_first_plan import accepted, application, cmd, post, proposal_command
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import original_security_work  # noqa: F401
from work_management_pg.test_workflow import work as work_case  # noqa: F401

from pdos_next import models as registered_models
from pdos_next.domain.preproject.models import ProposalDecision
from pdos_next.domain.projects.models import ProjectProductLink
from pdos_next.domain.release.models import ReleaseDecision, ReleasePackage
from pdos_next.domain.work_management.constants import ACCEPT, ASSIGN, CREATE, STATUS
from pdos_next.models import Artifact, Audit, Confirmation, Grant, Outbox, Receipt, RequestKey, now
from pdos_next.project_activity_catalog import SOURCES
from pdos_next.safety import verify_test_target
from pdos_next.service import EVENTS, digest

_PRIVATE_COLUMN = re.compile(
    r'\b[\w"]+\.(?:body|command|source_basis|snapshot|material|input_snapshot)\s*'
    r"(?=,|as\b|from\b|$)",
    re.I,
)
_ORIGINAL_CONTENT = re.compile(r"\bartifact_versions(?:_\d+)?\.content\b", re.I)
MODELS = tuple(
    dict.fromkeys(
        (
            *(source.model for source in SOURCES),
            *flow.MODELS,
            registered_models.Product,
            registered_models.Project,
            ProjectProductLink,
            Artifact,
            Receipt,
            Audit,
            Outbox,
            RequestKey,
            Confirmation,
        )
    )
)


@pytest.fixture
def work(request):
    value = request.getfixturevalue("work_case")
    verify_test_target(value.setup.admin)
    verify_test_target(value.setup.engine)
    return value


def _snapshot(work):
    with Session(work.setup.admin) as session:
        return {
            model.__tablename__: [
                digest(dict(row))
                for row in session.execute(
                    select(model.__table__)
                    .where(model.tenant_id == work.setup.tenant)
                    .order_by(model.id)
                ).mappings()
            ]
            for model in MODELS
        }


def read_activity(work, *, actor=None, project_id=None, product_id=None, **params):
    """Actual HTTP read with a physical-row zero-write and minimal-SQL assertion."""
    project_id = project_id or work.project_id
    product_id = product_id or work.setup.product
    expected = params.pop("expected", 200)
    before, statements = _snapshot(work), []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        response = work.setup.client.get(
            f"/v1/categories/{work.setup.category}/products/{product_id}/project-work/activity",
            params={"project_id": str(project_id), **params},
            headers=flow.headers(work, actor),
        )
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert response.status_code == expected, response.text
    assert _snapshot(work) == before
    assert statements
    for statement in statements:
        assert not _PRIVATE_COLUMN.search(statement), statement
        assert not _ORIGINAL_CONTENT.search(statement), statement
        assert not re.search(
            r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", statement, re.I
        )
        assert "for update" not in statement.lower()
    value = response.json()
    if expected != 200:
        assert "items" not in value
        return value
    assert value["version"] == "project-activity/v1"
    assert value["category_id"] == str(work.setup.category)
    assert value["product_id"] == str(product_id)
    assert value["principal_id"] == str(actor or work.setup.human)
    assert value["project"]["id"] == str(project_id)
    assert datetime.fromisoformat(value["as_of"]).utcoffset() is not None
    assert len({item["receipt_id"] for item in value["items"]}) == len(value["items"])
    for item in value["items"]:
        assert set(item) == {
            "id",
            "record_kind",
            "status",
            "operation",
            "event_type",
            "recorded_at",
            "occurred_at",
            "original_timezone",
            "subject",
            "actor",
            "requester",
            "summary",
            "next_steps",
            "receipt_id",
            "run_id",
            "sources",
            "task_refs",
            "link",
        }
        assert item["event_type"] == EVENTS[item["operation"]]
        assert datetime.fromisoformat(item["recorded_at"]).utcoffset() is not None
        assert item["run_id"] is None
        assert "confirmation_token" not in json.dumps(item)
    return value


def _all_pages(work, *, actor=None, first=None, page_size=2):
    values, cursors = [], set()
    page = first or read_activity(work, actor=actor, page_size=page_size)
    watermark = page["as_of"]
    for _ in range(100):
        values.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert cursor not in cursors
        cursors.add(cursor)
        page = read_activity(work, actor=actor, page_size=page_size, cursor=cursor)
        assert page["as_of"] == watermark
    else:
        pytest.fail("Actual activity cursor did not terminate")
    keys = [(item["recorded_at"], UUID(item["id"])) for item in values]
    assert keys == sorted(keys, reverse=True)
    assert len({item["id"] for item in values}) == len(values)
    assert len({item["receipt_id"] for item in values}) == len(values)
    return {item["receipt_id"]: item for item in values}


def _assert_actual_group(work, item):
    with Session(work.setup.admin) as session:
        receipt = session.get(Receipt, UUID(item["receipt_id"]))
        events = list(
            session.scalars(
                select(Outbox).where(
                    Outbox.receipt_id == receipt.id,
                    Outbox.type == EVENTS[receipt.operation],
                )
            )
        )
        # G0 also emits project.created for its created project. It is a side
        # event of this one decision, not a second activity for the same receipt.
        assert len(events) == 1
        original = events[0]
        assert item["id"] == str(original.id)
        assert item["event_type"] == original.type == EVENTS[receipt.operation]
        assert original.subject_id == receipt.subject_id
        assert original.subject_revision == receipt.subject_revision
        assert original.actor_id == receipt.actor_id
        assert original.correlation_id == (
            receipt.agent_run_id or receipt.run_id or receipt.command_id
        )
        assert item["operation"] == receipt.operation
        assert item["subject"] | {"title": None} == {
            "kind": receipt.subject_type,
            "id": str(receipt.subject_id),
            "revision": receipt.subject_revision,
            "title": None,
        }
        assert item["actor"]["id"] == str(receipt.actor_id)
        assert item["requester"]["id"] == str(receipt.requester_id)


def _build_accepted(work, command):
    """One normal preview/commit, checking the actual stored proof before use.

    This is the original Build helper protocol, with a precise diagnostic for
    a missing/consumed/expired confirmation. Never renew, retry or replace it.
    """
    setup = work.setup
    preview = post(setup, command, True)
    assert preview.status_code == 200, preview.text
    value = preview.json()
    prepared = value["command"]
    assert prepared["command_id"] == command["command_id"]
    assert prepared["idempotency_key"] == command["idempotency_key"]
    token = prepared["payload"]["confirmation_token"]
    with flow.scoped(work) as session:
        proof = session.execute(
            select(
                Confirmation.subject_type,
                Confirmation.subject_id,
                Confirmation.product_id,
                Confirmation.category_id,
                Confirmation.actor_id,
                Confirmation.operation,
                Confirmation.revision,
                Confirmation.consumed,
                Confirmation.expires_at,
            ).where(
                Confirmation.tenant_id == setup.tenant,
                Confirmation.token_hash == digest(token),
            )
        ).one_or_none()
        assert proof is not None, "The original preview proof must be readable by its actual actor"
        assert proof.subject_type == "product" and proof.subject_id == setup.product
        assert proof.product_id == setup.product and proof.category_id == setup.category
        assert proof.actor_id == setup.human and proof.operation == command["operation"]
        assert proof.revision == prepared["expected_revision"]
        assert proof.consumed is False
        assert proof.expires_at is not None and now() < proof.expires_at
    result = post(setup, prepared)
    assert result.status_code == 200, result.text
    return result.json(), prepared


def test_actual_work_and_plan_feed_retains_both_people_and_exact_cursor_scope(work):
    setup = work.setup
    with flow.scoped(work) as session:
        decision = session.scalar(
            select(ProposalDecision).where(ProposalDecision.created_project_id == work.project_id)
        )
        link = session.scalar(
            select(ProjectProductLink).where(ProjectProductLink.project_id == work.project_id)
        )
        g0_receipt = str(decision.receipt_id)
        definition_ref = str(link.definition_id)
    baseline = _all_pages(work)
    assert set(baseline) == {g0_receipt}
    assert baseline[g0_receipt]["actor"]["id"] == str(setup.peer)

    definition_input = work.source["id"], definition_ref
    plan = post(setup, proposal_command(setup, definition_input, str(work.project_id)))
    assert plan.status_code == 200, plan.text
    applied, _ = accepted(
        setup, application(setup, definition_input, str(work.project_id), plan.json()["subject_id"])
    )
    create_command, created = flow.execute(
        work,
        CREATE,
        flow.payload(
            work,
            title="Named activity task",
            goal="Retain actual actors and history",
            outcomes=[{"key": "drawing", "text": "Drawing", "required": True}],
            plan_task=None,
        ),
    )
    work.task_id = UUID(created["result"]["task_id"])
    _, assigned = flow.execute(
        work,
        ASSIGN,
        flow.payload(
            work,
            task=flow.task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )
    _, received = flow.execute(
        work,
        ACCEPT,
        flow.payload(work, task=flow.task(work, "assigned")),
        actor=setup.peer,
    )
    _, status = flow.execute(
        work,
        STATUS,
        flow.payload(
            work,
            fact_summary="Named factual update; acceptance is recorded",
            next_steps="The drawing still needs to be submitted",
            task_refs=[flow.task(work, "accepted")],
        ),
    )
    expected = {
        g0_receipt,
        plan.json()["id"],
        applied["id"],
        created["id"],
        assigned["id"],
        received["id"],
        status["id"],
    }
    first = read_activity(work, page_size=2)
    assert first["next_cursor"]
    for actor in (setup.human, setup.peer):
        items = _all_pages(work, actor=actor)
        assert set(items) == expected
        for item in items.values():
            _assert_actual_group(work, item)
        assert items[received["id"]]["actor"]["id"] == str(setup.peer)
        assert items[status["id"]]["summary"] == "Named factual update; acceptance is recorded"
        assert items[status["id"]]["next_steps"] == "The drawing still needs to be submitted"
        assert items[status["id"]]["task_refs"] == [flow.task(work, "accepted")]
        assert items[created["id"]]["subject"]["id"] == created["subject_id"]
        assert items[created["id"]]["subject"]["id"] == str(work.task_id)
        assert items[assigned["id"]]["subject"]["id"] != str(work.task_id)

    # An intervening actual update cannot drift a cursor's original snapshot.
    _, newer = flow.execute(
        work,
        STATUS,
        flow.payload(
            work,
            fact_summary="A later fixed update",
            next_steps="Continue actual work",
            task_refs=[flow.task(work, "accepted")],
        ),
    )
    assert set(_all_pages(work, first=first)) == expected
    assert set(_all_pages(work)) == expected | {newer["id"]}
    before = _snapshot(work)
    replay = flow.send(work, deepcopy(create_command))
    assert replay.status_code == 200 and replay.json() == created
    assert _snapshot(work) == before
    assert set(_all_pages(work)) == expected | {newer["id"]}

    cursor = first["next_cursor"]
    denied = read_activity(work, actor=setup.peer, cursor=cursor, expected=403)
    assert denied["code"] == "FORBIDDEN_SCOPE"
    value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    value["before"][1] = str(uuid4())
    altered = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    assert read_activity(work, cursor=altered, expected=403)["code"] == "FORBIDDEN_SCOPE"
    malformed = read_activity(work, cursor="not-a-cursor", expected=422)
    assert malformed["code"] == "VALIDATION_FAILED"
    assert malformed["detail"]["reason"] == "INVALID_PAYLOAD"
    read_activity(work, actor=setup.other_human, expected=403)

    other_setup = copy(setup)
    other = create_g0_project(other_setup, visibility="category", name="Another actual project")
    other_work = SimpleNamespace(setup=other_setup, project_id=UUID(other.project_id))
    assert set(_all_pages(other_work)) == {other.receipt["id"]}
    read_activity(other_work, cursor=cursor, expected=403)
    assert set(_all_pages(work)) == expected | {newer["id"]}

    with Session(setup.admin) as session, session.begin():
        session.execute(
            update(Grant)
            .where(
                Grant.tenant_id == setup.tenant,
                Grant.category_id == setup.category,
                Grant.principal_id == setup.peer,
            )
            .values(expires_at=now() - timedelta(seconds=1))
        )
    read_activity(work, actor=setup.peer, cursor=cursor, expected=403)
    assert set(_all_pages(work)) == expected | {newer["id"]}


def test_actual_build_config_output_and_sample_facts_are_not_child_duplicates(setup, planned):
    verify_test_target(setup.admin)
    verify_test_target(setup.engine)
    work = SimpleNamespace(setup=setup, project_id=UUID(planned["project"]))
    actual, _ = _build_accepted(work, actual_command(setup, planned))
    lot, _ = _build_accepted(work, output_command(setup, planned, actual))
    allocation, _ = _build_accepted(
        work, allocation_command(setup, planned, lot, labels=["FEED-A", "FEED-B"])
    )
    unlinked, _ = accepted(
        setup,
        cmd(
            setup,
            "engineering.configuration.create",
            {**planned["engineering_payload"], "name": "Readable but unassociated configuration"},
            planned["source"],
        ),
    )
    items = _all_pages(work)
    expected = [planned[key] for key in ("bom", "engineering", "process", "build")]
    expected += [actual, lot, allocation]
    for receipt in expected:
        assert receipt["id"] in items
        _assert_actual_group(work, items[receipt["id"]])
    assert unlinked["id"] not in items
    assert len(items) == 9  # G0 + 3 configurations + Build/readiness + 3 actual records.
    assert sum(item["operation"] == "build.readiness.compute" for item in items.values()) == 1
    assert sum(item["operation"] == "build.sample.allocate" for item in items.values()) == 1
    assert not any(item["subject"]["kind"] == "sample_unit" for item in items.values())
    assert items[actual["id"]]["occurred_at"] is not None
    assert items[lot["id"]]["occurred_at"] is not None
    assert items[actual["id"]]["original_timezone"] is None
    assert "计算" in next(
        item["summary"] for item in items.values() if item["operation"] == "build.readiness.compute"
    )


def test_actual_named_publication_and_both_release_decisions_remain_historical_activity(
    publication_case,
    monkeypatch,
):
    work, setup = publication_case, publication_case.setup
    # This case reuses the real bounded API chain; interactive seeds and extra
    # external/exception closures belong to their separately explicit checkpoints.
    for key in (
        "PDOS_RELEASE_POLICY_BROWSER_SEED",
        "PDOS_EXTERNAL_HANDOFF_LINK",
        "PDOS_RELEASE_EXCEPTION_LINK",
    ):
        monkeypatch.delenv(key, raising=False)
    release_chain.test_controlled_policy_and_independent_named_decisions(work, monkeypatch)
    with Session(setup.admin) as session:
        packages = list(
            session.scalars(
                select(ReleasePackage).where(
                    ReleasePackage.tenant_id == setup.tenant,
                    ReleasePackage.project_id == work.project_id,
                )
            )
        )
        decisions = list(
            session.scalars(
                select(ReleaseDecision).where(
                    ReleaseDecision.tenant_id == setup.tenant,
                    ReleaseDecision.project_id == work.project_id,
                )
            )
        )
        expected_decisions = {str(row.receipt_id): row for row in decisions}
        expected_packages = {str(row.receipt_id) for row in packages}
    assert len(packages) == len(decisions) == 2
    assert {row.actor_id for row in decisions} == {setup.human, setup.peer}
    for actor in (setup.human, setup.peer):
        items = _all_pages(work, actor=actor, page_size=20)
        assert expected_packages <= set(items)
        assert set(expected_decisions) <= set(items)
        assert (
            sum(
                item["operation"] == "npi.manufacturing_baseline.publish" for item in items.values()
            )
            == 1
        )
        assert sum(item["operation"] == "release.policy.import" for item in items.values()) == 2
        assert not any(
            item["subject"]["kind"] == "manufacturing_publication_document"
            for item in items.values()
        )
        for receipt_id, row in expected_decisions.items():
            item = items[receipt_id]
            _assert_actual_group(work, item)
            assert item["actor"]["id"] == str(row.actor_id)
            assert item["operation"] == f"release.{row.discipline}.approve"
            assert item["subject"]["revision"] == row.revision
    # Withdrawal makes the old package require recheck without erasing its facts.
    for package in packages:
        detail = release_chain.fixed(work, package.id)
        assert detail["applicability"] == "needs_recheck"
