"""Actual HTTP Run scope, current audience and read-only project events.

G0/work fixtures create real domain facts through public commands. Runs and their
events are created only by the real start/cancel/service admission paths. No model
or external call executes. The one reservation is a real KernelStore ledger claim,
not inference. Project audience removal is narrow verified fixture-admin ACL
maintenance: there is no public Project audience-revoke command. Only root runs PG.
"""

import re
from copy import copy, deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import g0_fixture
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, load_only

from pdos_next.agent_kernel.activities import KernelActivities
from pdos_next.agent_kernel.bootstrap import Bootstrap
from pdos_next.agent_kernel.models import AgentEvent, AgentRun, AgentSession, AgentToolCall
from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.domain.automations import service_runtime
from pdos_next.domain.automations.service_models import AutomationServiceAttempt
from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_management.constants import ACCEPT, ASSIGN, CREATE
from pdos_next.errors import DomainError
from pdos_next.models import Grant, ObjectAudience, Product, now
from pdos_next.safety import verify_test_target
from tests.automations_pg.test_service_automation_pg import _activate, _ready, _spec
from tests.automations_pg.test_service_relative_pg import _commit
from tests.work_management_pg import test_workflow as flow
from tests.work_management_pg.test_workflow import original_security_work  # noqa: F401
from tests.work_management_pg.test_workflow import work as work_case  # noqa: F401


@pytest.fixture
def project_work(request):
    return request.getfixturevalue("work_case")


@pytest.fixture
def audience_work(request, monkeypatch):
    command = g0_fixture.run_command

    def share(setup, operation, payload, **kwargs):
        if operation == "proposal.share":
            payload = {
                **deepcopy(payload),
                "visibility": "audience",
                "audience_ids": [str(setup.peer)],
            }
        return command(setup, operation, payload, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(g0_fixture, "run_command", share)
        work = request.getfixturevalue("work_case")
    verify_test_target(work.setup.admin)
    verify_test_target(work.setup.engine)
    verify_test_target(work.setup.dispatch)
    with flow.scoped(work, work.setup.peer) as session:
        assert session.get(Project, work.project_id).visibility == "audience"
        assert session.get(Product, work.setup.product) is not None
    return work


def _path(work):
    return f"/v1/categories/{work.setup.category}/agent-runs"


def _post(work, payload, *, actor=None, expected=202, suffix=""):
    response = work.setup.client.post(
        _path(work) + suffix, headers=flow.headers(work, actor), json=payload
    )
    assert response.status_code == expected, response.text
    return response.json()


def _start(work, *, actor=None, **values):
    return _post(
        work,
        {
            "goal": "PRIVATE-RUN-GOAL: inspect the explicit project without inference",
            "idempotency_key": str(uuid4()),
            "product_id": str(work.setup.product),
            "project_id": str(work.project_id),
            **values,
        },
        actor=actor,
    )


def _get(work, suffix="", *, actor=None, expected=200, **params):
    response = work.setup.client.get(
        _path(work) + suffix, headers=flow.headers(work, actor), params=params
    )
    assert response.status_code == expected, response.text
    return response.json()


def _scope(work, identity, actor=None):
    setup = work.setup
    return KernelStore(setup.engine).scope(
        tenant_id=setup.tenant,
        requester_id=actor or setup.human,
        writer_id=setup.agent,
        category_id=setup.category,
        run_id=UUID(identity),
    )


def _activity(work, *, actor=None):
    statements = []

    def capture(_connection, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(work.setup.engine, "before_cursor_execute", capture)
    try:
        response = work.setup.client.get(
            f"/v1/categories/{work.setup.category}/products/{work.setup.product}/project-work/activity",
            params={"project_id": str(work.project_id), "page_size": 100},
            headers=flow.headers(work, actor),
        )
    finally:
        event.remove(work.setup.engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    for statement in statements:
        assert not re.search(
            r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", statement, re.I
        )
        assert not re.search(
            r"\bagent_(?:runs|run_events)\.(?:goal|result|versions|read_sources|body)\s*(?:,|AS\b|FROM\b)",
            statement,
            re.I,
        ), statement
    return [item for item in response.json()["items"] if item["record_kind"] == "run_event"]


def test_actual_project_start_cancel_continue_and_private_metadata_events(project_work):
    work, setup = project_work, project_work.setup
    # Omitted and explicit-null project use the original unbound request digest.
    unbound_payload = {
        "goal": "PRIVATE-UNBOUND: this product alone grants no project link",
        "idempotency_key": str(uuid4()),
        "product_id": str(setup.product),
    }
    unbound = _post(work, unbound_payload)
    assert _post(work, {**unbound_payload, "project_id": None})["run_id"] == unbound["run_id"]
    assert _get(work, "/" + unbound["run_id"])["project_id"] is None
    assert _activity(work) == []

    original = {
        "goal": "PRIVATE-RUN-GOAL: fixed project context",
        "idempotency_key": str(uuid4()),
        "product_id": str(setup.product),
        "project_id": str(work.project_id),
    }
    started = _post(work, original)
    assert _post(work, original)["run_id"] == started["run_id"]
    detail = _get(work, "/" + started["run_id"])
    assert detail["project_id"] == str(work.project_id)
    # Source/session metadata readers deliberately omit new and private columns.
    # The owner check re-reads only the missing scope, with ordinary current RLS.
    from pdos_next.agent_kernel.run_reconciliation import owner

    with flow.scoped(work) as session:
        limited = session.scalar(
            select(AgentRun)
            .where(AgentRun.id == UUID(started["run_id"]))
            .options(
                load_only(
                    AgentRun.id,
                    AgentRun.tenant_id,
                    AgentRun.category_id,
                    AgentRun.requester_id,
                    AgentRun.proposal_id,
                    raiseload=True,
                )
            )
        )
        owner(session, setup.ctx, limited)
    assert detail["product_id"] == str(setup.product)
    scope = _scope(work, started["run_id"])
    assert scope.project_id == work.project_id
    metadata = Bootstrap(setup.engine).project_context(
        scope, "Read the actual project", {"project"}
    )
    assert metadata["project"]["id"] == str(work.project_id)

    with Session(setup.admin) as session:
        conversation = session.get(AgentSession, UUID(started["session_id"]))
        assert conversation.project_id == work.project_id
        assert conversation.product_id == setup.product
    peer = setup.peer
    _get(work, "/" + started["run_id"], actor=peer, expected=403)
    _get(work, "/" + started["run_id"] + "/events", actor=peer, expected=403)
    assert _activity(work, actor=peer) == []

    cancelled = _post(work, {}, suffix="/" + started["run_id"] + "/cancel", expected=200)
    assert cancelled["status"] == "cancelled" and cancelled["held_tokens"] == 0
    followup = {
        "goal": "Continue the same explicit project without replacing its scope",
        "idempotency_key": str(uuid4()),
        "continue_from_run_id": started["run_id"],
    }
    _post(work, {**followup, "project_id": str(work.project_id)}, expected=422)
    child = _post(work, followup)
    assert child["session_id"] == started["session_id"]
    assert _get(work, "/" + child["run_id"])["project_id"] == str(work.project_id)
    assert _scope(work, child["run_id"]).project_id == work.project_id
    history = _get(work, project_id=str(work.project_id))["items"]
    assert {item["run_id"] for item in history} == {started["run_id"], child["run_id"]}

    events = _activity(work)
    assert {item["run_id"] for item in events} == {started["run_id"], child["run_id"]}
    assert len(events) == 3  # Actual accepted, cancellation state and child accepted.
    assert "PRIVATE-RUN-GOAL" not in str(events) and "PRIVATE-UNBOUND" not in str(events)
    for item in events:
        assert item["receipt_id"] is None and item["subject"]["kind"] == "agent_run"
        assert item["subject"]["title"] is None and item["sources"] == item["task_refs"] == []
        assert item["requester"]["id"] == str(setup.human)

    # A second G0 creates another actual product/project; mixed bindings cannot
    # replace the first Session, continuation, or idempotency intent.
    other_setup = copy(setup)
    other = g0_fixture.create_g0_project(
        other_setup, visibility="category", name="Second actual project"
    )
    _post(work, {**original, "project_id": other.project_id}, expected=409)
    _start_payload = {**original, "idempotency_key": str(uuid4()), "project_id": other.project_id}
    _post(work, _start_payload, expected=403)
    _post(
        work,
        {**_start_payload, "product_id": other.product_id, "session_id": started["session_id"]},
        expected=403,
    )
    _post(work, {**original, "idempotency_key": str(uuid4()), "product_id": None}, expected=403)
    wrong_category = setup.client.post(
        f"/v1/categories/{uuid4()}/agent-runs", headers=setup.headers, json=original
    )
    assert wrong_category.status_code == 403
    with Session(setup.admin) as session:
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.tenant_id == setup.tenant))
            is None
        )


def test_project_acl_revoke_hides_private_run_and_releases_real_technical_reservation(
    audience_work,
):
    work, setup = audience_work, audience_work.setup
    parent = _start(work, actor=setup.peer)
    _post(work, {}, actor=setup.peer, suffix="/" + parent["run_id"] + "/cancel", expected=200)
    child = _post(
        work,
        {
            "goal": "Private peer continuation",
            "idempotency_key": str(uuid4()),
            "continue_from_run_id": parent["run_id"],
        },
        actor=setup.peer,
    )
    store, scope = KernelStore(setup.engine), _scope(work, child["run_id"], setup.peer)
    call_id, _ = store.claim(
        scope, "synthetic-reservation-no-inference", "model", {}, reservation=37
    )
    assert scope.project_id == work.project_id
    with Session(setup.admin) as session, session.begin():
        relation = session.scalars(
            select(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.category_id == setup.category,
                ObjectAudience.object_type == "projects",
                ObjectAudience.subject_id == work.project_id,
                ObjectAudience.owner_id == setup.human,
                ObjectAudience.principal_id == setup.peer,
            )
        ).one()
        session.delete(relation)
    with flow.scoped(work, setup.peer) as session:
        assert session.get(Project, work.project_id) is None
        assert session.get(Product, setup.product) is not None
        assert session.scalar(select(Grant.id).where(Grant.principal_id == setup.peer)) is not None
        assert session.get(AgentRun, UUID(child["run_id"])) is None
        assert (
            session.scalar(select(AgentEvent.id).where(AgentEvent.run_id == UUID(child["run_id"])))
            is None
        )
    for identity in (parent["run_id"], child["run_id"]):
        _get(work, "/" + identity, actor=setup.peer, expected=403)
        _get(work, "/" + identity + "/events", actor=setup.peer, expected=403)
        _get(work, "/" + identity + "/continuation", actor=setup.peer, expected=403)
    _get(work, actor=setup.peer, expected=403, project_id=str(work.project_id))
    _post(
        work,
        {
            "goal": "Cannot continue revoked project",
            "idempotency_key": str(uuid4()),
            "continue_from_run_id": parent["run_id"],
        },
        actor=setup.peer,
        expected=403,
    )
    with pytest.raises(DomainError) as error:
        store.current(scope)
    assert error.value.code == "FORBIDDEN_SCOPE"
    result = KernelActivities(setup.engine, technical_engine=setup.dispatch).advance(
        {
            "tenant_id": str(setup.tenant),
            "category_id": str(setup.category),
            "actor_id": str(setup.peer),
            "requester_id": str(setup.peer),
            "subject_id": child["run_id"],
        }
    )
    assert result["status"] == "failed" and result["error_code"] == "FORBIDDEN_SCOPE"
    with Session(setup.admin) as session:
        saved = session.get(AgentRun, UUID(child["run_id"]))
        call = session.get(AgentToolCall, call_id)
        assert saved.held_tokens == 0 and saved.used_tokens == 37
        assert saved.state == "failed" and saved.error_code == "FORBIDDEN_SCOPE"
        assert call.state == "unknown" and call.reserved_tokens == 0 and call.charged_tokens == 37


@pytest.mark.parametrize("restricted_project", [False, True])
def test_actual_relative_service_run_inherits_its_explicit_clock_project(
    project_work, restricted_project
):
    work, setup = project_work, project_work.setup
    wallet = _ready(setup)
    if restricted_project:
        # Establish the narrower fixture ACL before recording immutable work.
        # Existing work facts retain their original owner/visibility binding;
        # changing that binding afterwards correctly hides the old clock source.
        verify_test_target(setup.admin)
        with Session(setup.admin) as session, session.begin():
            assert session.get(Product, setup.product).visibility == "category"
            project = session.get(Project, work.project_id)
            assert project.owner_id == setup.human and project.visibility == "category"
            project.visibility = "audience"
            session.flush([project])
            audience = session.scalars(
                select(ObjectAudience).where(
                    ObjectAudience.tenant_id == setup.tenant,
                    ObjectAudience.category_id == setup.category,
                    ObjectAudience.object_type == "projects",
                    ObjectAudience.subject_id == work.project_id,
                    ObjectAudience.principal_id == setup.peer,
                )
            ).one_or_none()
            if audience is not None:
                assert audience.owner_id == project.owner_id == setup.human
            else:
                session.add(
                    ObjectAudience(
                        tenant_id=setup.tenant,
                        category_id=setup.category,
                        object_type="projects",
                        subject_id=work.project_id,
                        owner_id=setup.human,
                        principal_id=setup.peer,
                    )
                )
        for actor in (setup.human, setup.peer):
            with flow.scoped(work, actor) as session:
                assert session.get(Project, work.project_id).visibility == "audience"
                assert session.get(Product, setup.product).visibility == "category"
    _, created = flow.execute(
        work,
        CREATE,
        flow.payload(
            work,
            title="Actual relative clock project",
            goal="Bind the service Run to the exact clock project",
            outcomes=[{"key": "drawing", "text": "Traceable drawing", "required": True}],
            plan_task=None,
        ),
    )
    work.task_id = UUID(created["result"]["task_id"])
    flow.execute(
        work,
        ASSIGN,
        flow.payload(
            work,
            task=flow.task(work, "proposed"),
            assignee_id=str(setup.peer),
            recipient_id=str(setup.human),
        ),
    )
    flow.execute(
        work, ACCEPT, flow.payload(work, task=flow.task(work, "assigned")), actor=setup.peer
    )
    _commit(work, setup.human, (now() - timedelta(minutes=1)).isoformat())
    spec = _spec(
        setup,
        wallet,
        kind="relative_milestone",
        config={
            "source_kind": "commitment",
            "project_id": str(work.project_id),
            "task_id": str(work.task_id),
            "clock": "promised_at",
            "promisor_id": str(setup.peer),
            "recipient_id": str(setup.human),
            "offset_seconds": 0,
            "expires_at": None,
        },
    )
    _, ref = _activate(setup, spec)
    assert service_runtime.tick(setup.engine, ref)["state"] == "active"
    with Session(setup.admin) as session:
        attempt = session.scalars(
            select(AutomationServiceAttempt).where(
                AutomationServiceAttempt.service_grant_id == UUID(ref["grant_id"]),
            )
        ).one()
        assert attempt.state == "admitted"
        saved = session.get(AgentRun, attempt.run_id)
        assert saved.trigger == "automation_service" and saved.project_id == work.project_id
        assert saved.private_context is restricted_project
        assert session.get(AgentSession, saved.session_id).project_id == work.project_id
        assert saved.requester_id == setup.human and saved.writer_id == setup.agent
        identity = str(saved.id)
        assert (
            session.scalar(select(AgentToolCall.id).where(AgentToolCall.run_id == saved.id)) is None
        )
    assert _scope(work, identity).project_id == work.project_id
    assert _get(work, "/" + identity)["project_id"] == str(work.project_id)
    assert {item["run_id"] for item in _activity(work)} == {identity}
