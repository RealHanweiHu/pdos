from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.dispatch.outbox import acknowledge, claim_events, delivery_unknown
from pdos_next.models import Inbox, Outbox
from test_trusted_source_work import source


def test_dispatcher_claims_only_bound_tenant_metadata_and_preserves_scope(setup):
    artifact, _ = source(setup)
    events = claim_events(setup.dispatch, setup.tenant)
    assert len(events) == 1
    event = events[0]
    assert event.category_id == str(setup.category) and event.subject_id == artifact
    assert event.actor_id == event.requester_id == str(setup.human)
    assert not claim_events(setup.dispatch, setup.other_tenant)
    assert not claim_events(setup.dispatch, setup.tenant)
    assert delivery_unknown(setup.dispatch, event)
    assert not claim_events(setup.dispatch, setup.tenant)
    assert acknowledge(setup.dispatch, event, workflow_id="synthetic-scoped-workflow")
    assert not acknowledge(setup.dispatch, event, workflow_id="repeated")
    with Session(setup.admin) as s:
        assert s.get(Outbox, UUID(event.event_id)).delivered_at
        delivery = s.scalar(select(Inbox).where(Inbox.event_id == UUID(event.event_id)))
        assert delivery.category_id == setup.category and delivery.status == "received"


def test_application_cannot_use_dispatcher_and_dispatcher_cannot_read_business(setup):
    source(setup)
    with pytest.raises(DBAPIError):
        claim_events(setup.engine, setup.tenant)
    with Session(setup.dispatch) as s, pytest.raises(DBAPIError):
        s.execute(text("SELECT * FROM artifact_versions"))
