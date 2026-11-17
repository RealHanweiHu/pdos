"""D504: the scope-note review period is a tenant setting, 90 days by default (P87 第 4 项).

Real commands, real roles and row-level security; no model call.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent.kernel.models import TenantAdministrator
from pdos_next.core.database import tenant_session
from pdos_next.domain.knowledge.scope_notes.models import ScopeNoteVersion
from tests.knowledge.scope_notes.support import (
    SAVE,
    anchor,
    body,
    commit,
    listing,
    preview,
    save,
)

POLICY = "/v1/personal/memory-policy"


def period(setup, identity):
    with Session(setup.admin) as session:
        rows = session.scalars(select(ScopeNoteVersion).where(
            ScopeNoteVersion.note_id == identity).order_by(ScopeNoteVersion.revision)).all()
        return [round((row.review_due_at - row.created_at) / timedelta(days=1)) for row in rows]


def change(setup, revision, *, status=200, key=None, **values):
    response = setup.client.post(POLICY, headers=setup.headers, json={
        "expected_revision": revision, "request_key": key or str(uuid4()),
        "work_state_idle_days": 30, **values})
    assert response.status_code == status, response.text
    return response.json()


def test_default_is_ninety_days_and_only_an_administrator_changes_it(setup):
    assert setup.client.get(POLICY, headers=setup.headers).json()[
        "scope_note_review_days"] == 90
    assert listing(setup)["review_days"] == 90
    assert preview(setup, SAVE, {"anchor": anchor(setup), "body": body("周报每周五发")})[
        "review"]["review_days"] == 90
    before = save(setup, "周报每周五发")
    assert period(setup, before["subject_id"]) == [90]
    # A member who is not a current administrator is refused; nothing changes.
    change(setup, 0, status=403, scope_note_review_days=30)
    # The AI identity cannot append a policy version, even for its requester.
    with pytest.raises(DBAPIError):
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text(
                "INSERT INTO memory_tenant_policies (id,tenant_id,created_at,revision,"
                "work_state_idle_days,scope_note_review_days,set_by,request_key,request_sha256)"
                " VALUES (gen_random_uuid(),:t,now(),1,30,30,:a,gen_random_uuid(),:d)"),
                {"t": setup.tenant, "a": setup.agent, "d": "0" * 64})
    with Session(setup.admin) as session, session.begin():
        session.add(TenantAdministrator(tenant_id=setup.tenant, principal_id=setup.human,
                                        active=True))
    for bad in (0, 366):
        assert change(setup, 0, status=422, scope_note_review_days=bad)
    key = str(uuid4())
    saved = change(setup, 0, key=key, scope_note_review_days=30)
    assert saved["scope_note_review_days"] == 30 and saved["revision"] == 1
    # The same request key with a different period is a conflict, not a second version.
    assert change(setup, 0, status=409, key=key, scope_note_review_days=45)[
        "code"] == "DUPLICATE_INTENT_CONFLICT"
    assert change(setup, 0, key=key, scope_note_review_days=30) == saved
    # New writes take the period in force; versions already written keep their date.
    assert listing(setup)["review_days"] == 30
    assert preview(setup, SAVE, {"anchor": anchor(setup), "body": body("样件统一贴项目标签")})[
        "review"]["review_days"] == 30
    after = save(setup, "样件统一贴项目标签")
    assert period(setup, after["subject_id"]) == [30]
    assert period(setup, before["subject_id"]) == [90]
    # Revising the older note starts its review again under the current period.
    commit(setup, SAVE, {"anchor": anchor(setup), "note": {"id": before["subject_id"],
                                                           "revision": 1},
                         "body": body("周报每周五下班前发")})
    assert period(setup, before["subject_id"]) == [90, 30]
    # A request that leaves the period out (M1/M2a shape) keeps it.
    kept = change(setup, 1, work_state_idle_days=14, notes_enabled=True)
    assert kept["scope_note_review_days"] == 30 and kept["work_state_idle_days"] == 14
    statistics = setup.client.get(f"{POLICY}/statistics", headers=setup.headers).json()
    assert statistics["policy"]["scope_note_review_days"] == 30
