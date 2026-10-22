"""Actual public work commands and current project audience receipt reads.

G0's proposal.share command creates the actual audience Product and Project; no
stored work, fulfillment, receipt or common proof is constructed or rewritten.
There is no public Project audience-revoke operation. The final negative case
therefore deletes only this isolated fixture's exact Project/peer audience row
through the verified test administrator, retaining Product audience and Grant.
This is synthetic fixture authorization maintenance, not a production command.
Only root runs this PostgreSQL/HTTP test; there are no model or external calls.
"""

from copy import deepcopy
from uuid import UUID

import g0_fixture
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from work_management_pg import test_workflow as flow
from work_management_pg.test_workflow import original_security_work  # noqa: F401
from work_management_pg.test_workflow import work as work_case  # noqa: F401

from pdos_next.domain.projects.models import Project
from pdos_next.domain.work_fulfillment.models import WorkCommitmentReview
from pdos_next.domain.work_management.constants import ACCEPT, ASSIGN, COMMIT, CREATE, START, SUBMIT
from pdos_next.models import Artifact, Grant, ObjectAudience, Product, Receipt, RequestKey, now
from pdos_next.safety import verify_test_target
from work_fulfillment_pg import test_workflow as fulfillment


@pytest.fixture
def audience_work(request, monkeypatch):
    run_command = g0_fixture.run_command
    shared = []

    def share_with_peer(setup, operation, payload, **kwargs):
        if operation == "proposal.share":
            assert payload["visibility"] == "category" and payload["audience_ids"] == []
            payload = {
                **deepcopy(payload),
                "visibility": "audience",
                "audience_ids": [str(setup.peer)],
            }
            shared.append(deepcopy(payload))
        return run_command(setup, operation, payload, **kwargs)

    # Bound to fixture construction: later commands never use this wrapper.
    with monkeypatch.context() as patch:
        patch.setattr(g0_fixture, "run_command", share_with_peer)
        work = request.getfixturevalue("work_case")
    assert len(shared) == 1
    verify_test_target(work.setup.admin)
    verify_test_target(work.setup.engine)
    with flow.scoped(work, work.setup.peer) as session:
        project = session.get(Project, work.project_id)
        product = session.get(Product, work.setup.product)
        assert project is not None and product is not None
        assert project.visibility == product.visibility == "audience"
        assert project.owner_id == product.owner_id == work.setup.human
        artifact = session.get(Artifact, UUID(work.source["id"]))
        assert artifact is not None and artifact.visibility == "category"
    return work


def _get(work, actor, expected=200):
    before = fulfillment.snapshots(work)
    response = work.setup.client.get(
        fulfillment._endpoint(work),
        params={"project_id": str(work.project_id)},
        headers=flow.headers(work, actor),
    )
    assert response.status_code == expected, response.text
    assert fulfillment.snapshots(work) == before
    if expected != 200:
        assert response.json()["code"] == "FORBIDDEN_SCOPE"
        assert "commitments" not in response.json()
    return response.json()


def _receipt_read(work, actor, receipt, *, visible):
    """Use ordinary app RLS; the key proof exposes no other actor's key body."""
    with flow.scoped(work, actor) as session:
        saved = session.get(Receipt, UUID(receipt["id"]))
        bound = session.scalar(
            text("SELECT public.work_receipt_key_bound(:tenant,:product,:receipt)"),
            {
                "tenant": work.setup.tenant,
                "product": work.setup.product,
                "receipt": UUID(receipt["id"]),
            },
        )
        project_visible = session.scalar(
            text(
                "SELECT public.work_receipt_project_visible("
                ":tenant,:category,:product,:kind,:target,:revision,:receipt,:actor)"
            ),
            {
                "tenant": work.setup.tenant,
                "category": work.setup.category,
                "product": work.setup.product,
                "kind": receipt["subject_type"],
                "target": UUID(receipt["subject_id"]),
                "revision": receipt["subject_revision"],
                "receipt": UUID(receipt["id"]),
                "actor": work.setup.human,
            },
        )
        assert bound is visible and project_visible is visible
        if visible:
            assert saved is not None
            assert saved.id == UUID(receipt["id"])
            assert saved.subject_id == UUID(receipt["subject_id"])
            assert saved.subject_revision == receipt["subject_revision"]
            assert saved.actor_id == saved.requester_id == work.setup.human
            assert saved.visibility == "audience" and saved.result == receipt["result"]
        else:
            assert saved is None
        if actor != work.setup.human:
            assert not session.scalars(
                select(RequestKey).where(RequestKey.receipt_id == UUID(receipt["id"]))
            ).all()


def test_project_audience_history_receipt_and_key_proof_follow_current_project_grant(audience_work):
    work, setup = audience_work, audience_work.setup
    outsider = g0_fixture.add_category_human(
        setup, name="Synthetic category-only non-project reader"
    )

    def step(operation, *, actor=None, **values):
        return flow.execute(work, operation, flow.payload(work, **values), actor=actor)[1]

    created = step(
        CREATE,
        title="Synthetic audience promise fulfillment",
        goal="Keep actual project readers aligned with the recipient's fulfillment receipt",
        outcomes=[{"key": "drawing", "text": "Traceable delivered drawing", "required": True}],
        plan_task=None,
    )
    work.task_id = UUID(created["result"]["task_id"])
    assigned = step(
        ASSIGN,
        task=fulfillment._task_ref(created),
        assignee_id=str(setup.peer),
        recipient_id=str(setup.human),
    )
    accepted = step(ACCEPT, task=fulfillment._task_ref(assigned), actor=setup.peer)
    promise = step(
        COMMIT,
        task=fulfillment._task_ref(accepted),
        recipient_id=str(setup.human),
        outcome_keys=["drawing"],
        promised_at=None,
        original_timezone=flow.TIMEZONE,
        calendar_id=None,
        replaces=None,
        actor=setup.peer,
    )
    started = step(
        START, task=fulfillment._task_ref(accepted), **flow.clock_fields(), actor=setup.peer
    )
    submitted = step(
        SUBMIT,
        task=fulfillment._task_ref(started),
        **flow.clock_fields(),
        results=[
            {
                "key": "drawing",
                "text": "Actual traceable synthetic submitted drawing",
                "status": "present",
                "sources": [deepcopy(work.source)],
            }
        ],
        actor=setup.peer,
    )
    declaration = fulfillment._declaration(
        work,
        fulfillment._ref(promise),
        fulfillment._task_ref(submitted),
        fulfillment._ref(submitted),
        checks=fulfillment._checks("drawing"),
    )
    command = flow.preview(work, fulfillment._inputs(work, declaration))
    before_save = fulfillment._rows(work, fulfillment.UNCHANGED_MODELS)
    response = flow.send(work, command)
    assert response.status_code == 200, response.text
    assert fulfillment._rows(work, fulfillment.UNCHANGED_MODELS) == before_save
    receipt = response.json()
    assert receipt["subject_type"] == "work_commitment_review"
    assert receipt["result"]["status"] == "fulfilled"
    with flow.scoped(work) as session:
        review = session.get(WorkCommitmentReview, UUID(receipt["subject_id"]))
        assert review is not None and review.visibility == "audience"
        assert review.actor_id == review.requester_id == review.recipient_id == setup.human
        assert review.promisor_id == setup.peer and review.receipt_id == UUID(receipt["id"])

    peer_view = _get(work, setup.peer)
    promise_view = next(
        row for row in peer_view["commitments"] if row["id"] == promise["subject_id"]
    )
    state = promise_view["fulfillment"]
    assert state["state"] == "fulfilled" and state["revision"] == 1
    assert len(state["history"]) == 1 and state["review"] == state["history"][0]
    assert state["review"]["id"] == receipt["subject_id"]
    assert state["review"]["receipt_id"] == receipt["id"]
    assert state["review"]["actor_id"] == str(setup.human)
    assert state["review"]["checks"] == declaration["checks"]
    _receipt_read(work, setup.peer, receipt, visible=True)
    owner_view = _get(work, setup.human)
    _receipt_read(work, setup.human, receipt, visible=True)
    _get(work, outsider, expected=403)
    _receipt_read(work, outsider, receipt, visible=False)

    # The repository has proposal.share, but no public command to revoke a
    # derived Project audience. Narrow verified fixture-admin maintenance only.
    before_revoke = fulfillment.snapshots(work)
    with Session(setup.admin) as session, session.begin():
        direct = session.scalars(
            select(ObjectAudience).where(
                ObjectAudience.tenant_id == setup.tenant,
                ObjectAudience.category_id == setup.category,
                ObjectAudience.object_type == "projects",
                ObjectAudience.subject_id == work.project_id,
                ObjectAudience.owner_id == setup.human,
                ObjectAudience.principal_id == setup.peer,
            )
        ).all()
        assert len(direct) == 1
        session.delete(direct[0])
    assert fulfillment.snapshots(work) == before_revoke

    # Product audience, active category membership and original evidence remain;
    # only the actual Project reader relation changed, with no business rewrite.
    with flow.scoped(work, setup.peer) as session:
        assert session.get(Product, setup.product) is not None
        assert session.get(Project, work.project_id) is None
        assert session.get(WorkCommitmentReview, UUID(receipt["subject_id"])) is None
        grant = session.scalar(select(Grant).where(Grant.principal_id == setup.peer))
        assert grant is not None and grant.can_write
        assert grant.expires_at is None or grant.expires_at > now()
        assert session.get(Artifact, UUID(work.source["id"])) is not None
    _get(work, setup.peer, expected=403)
    _receipt_read(work, setup.peer, receipt, visible=False)
    after_owner = _get(work, setup.human)
    for key in ("project", "product_revision", "commitments"):
        assert after_owner[key] == owner_view[key]
    _receipt_read(work, setup.human, receipt, visible=True)
