"""Actual self-service, RLS and SQL privilege checks; all synthetic, no model calls."""

from copy import copy
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from g0_fixture import create_g0_project
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.agent_kernel.persistence import KernelStore
from pdos_next.clock import now
from pdos_next.database import tenant_session
from pdos_next.errors import DomainError
from pdos_next.models import Grant, Receipt
from pdos_next.personal_preference_models import PersonalPreference
from pdos_next.personal_preference_schemas import Preferences, PreferenceSave
from pdos_next.personal_preferences import context_preferences, recheck_context_preferences, save
from tests.agent_kernel.test_run_continuation import scope, start

ROOT = "/v1/personal/preferences"


def post(setup, preferences, *, revision=0, actor=None):
    return setup.client.post(ROOT, headers={
        "Authorization": f"Bearer {setup.tokens[actor or setup.human]}"
    }, json={"expected_revision": revision, "preferences": preferences})


def test_actual_defaults_save_replay_conflict_clear_and_private_accounts(setup):
    default = setup.client.get(ROOT, headers=setup.headers)
    assert default.status_code == 200, default.text
    assert default.json()["revision"] == 0
    assert default.json()["preferences"] == Preferences().model_dump(mode="json")
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(PersonalPreference).where(
            PersonalPreference.tenant_id == setup.tenant,
        )) == 0
        receipts = session.scalar(select(func.count()).select_from(Receipt))
    fields = {"answer_language": "en", "response_detail": "detailed", "role": "quality",
              "department": "质量部", "favorite_category_ids": [str(setup.category)],
              "favorite_project_ids": []}
    first = post(setup, fields)
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1 and first.json()["preferences"] == fields
    assert first.json()["navigation_candidates"][0]["id"] == str(setup.category)
    assert first.json()["role_defaults"]["welcome_examples"]
    assert post(setup, fields).json() == first.json()  # lost response, same values
    stale = post(setup, {**fields, "response_detail": "brief"})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    for actor in (setup.peer, setup.other_human):
        other = setup.client.get(ROOT, headers={
            "Authorization": f"Bearer {setup.tokens[actor]}"
        })
        assert other.status_code == 200 and other.json()["revision"] == 0
        assert other.json()["preferences"]["role"] is None
        assert "质量部" not in other.text
        denied = post(setup, fields, actor=actor)
        if actor == setup.other_human:
            assert denied.status_code == 403
        else:
            assert denied.status_code == 200
    cleared = post(setup, {}, revision=1)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["revision"] == 2
    assert cleared.json()["preferences"] == Preferences().model_dump(mode="json")
    assert cleared.json()["navigation_candidates"] == []
    assert cleared.json()["role_defaults"]["welcome_examples"] == []
    with Session(setup.admin) as session:
        assert session.scalar(select(func.count()).select_from(Receipt)) == receipts


def test_actual_navigation_options_favorites_and_revoked_authorization(setup):
    project = create_g0_project(copy(setup), name="本人常用合成项目")
    identities = {"favorite_category_ids": [str(setup.category)],
                  "favorite_project_ids": [project.project_id]}
    first = post(setup, identities)
    assert first.status_code == 200, first.text
    assert {item["kind"] for item in first.json()["navigation_candidates"]} == {
        "category", "project",
    }
    page = setup.client.get(ROOT + "/options?kind=project&query=本人常用&page_size=1",
                            headers=setup.headers)
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["id"] == project.project_id
    assert "purpose" not in page.text and "scope" not in page.text
    missing = post(setup, {"favorite_project_ids": [str(uuid4())]}, revision=1)
    assert missing.status_code == 403
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.tenant_id == setup.tenant, Grant.category_id == setup.category,
            Grant.principal_id == setup.human,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    after = setup.client.get(ROOT, headers=setup.headers)
    assert after.status_code == 200
    assert after.json()["navigation_candidates"] == []
    assert after.json()["preferences"]["favorite_project_ids"] == [project.project_id]
    page = setup.client.get(ROOT + "/options?kind=project", headers=setup.headers)
    assert page.json()["items"] == []
    assert post(setup, {}, revision=1).status_code == 200


def test_actual_controlled_host_reads_only_requester_preferences_and_cannot_write(setup):
    assert post(setup, {"answer_language": "ja", "role": "engineering"}).status_code == 200
    run_id, _ = start(setup, personal=True)
    bound = scope(setup, run_id, personal=True)
    store = KernelStore(setup.engine)
    with store.transaction(bound) as (session, _run):
        value = context_preferences(session, bound)
        assert value["answer_language"] == "ja" and value["role"] == "engineering"
        assert value["source"] == "explicit_user_settings"
        assert value["use"] == "personalization_only"
        with pytest.raises(DomainError) as forbidden:
            save(session, replace(setup.ctx, category_id=None), PreferenceSave(
                expected_revision=1, preferences=Preferences(answer_language="en"),
            ))
        assert getattr(forbidden.value, "code", None) == "FORBIDDEN_SCOPE"
    with pytest.raises(DBAPIError) as rejected:
        with tenant_session(setup.engine, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text("UPDATE personal_preferences SET revision=revision+1, "
                                 "body='{}'::jsonb WHERE owner_id=:owner"),
                            {"owner": setup.human})
            # UPDATE RLS hides rows, which is also a denied mutation.
            current = session.scalar(select(PersonalPreference).where(
                PersonalPreference.owner_id == setup.human,
            ))
            assert current.revision == 1
            session.execute(text("INSERT INTO personal_preferences "
                                 "SELECT owner_id,1,'{}'::jsonb,updated_at,:id,"
                                 "tenant_id,created_at "
                                 "FROM personal_preferences WHERE owner_id=:owner"),
                            {"owner": setup.human, "id": uuid4()})
    assert rejected.value.orig.sqlstate == "42501"


@pytest.mark.parametrize("statement", [
    "SELECT * FROM public.personal_preferences",
    "UPDATE public.personal_preferences SET revision=revision+1",
    "INSERT INTO public.personal_preferences SELECT * FROM public.personal_preferences",
    "DELETE FROM public.personal_preferences",
])
def test_actual_agent_database_role_has_no_direct_table_privilege(setup, statement):
    with pytest.raises(DBAPIError) as rejected:
        with tenant_session(setup.admin, setup.tenant, actor_id=setup.agent,
                            requester_id=setup.human) as session:
            session.execute(text("SET LOCAL ROLE pdos_agent"))
            session.execute(text(statement))
    assert rejected.value.orig.sqlstate == "42501"


def test_actual_sql_rls_cannot_borrow_other_person_and_guard_rejects_identity_revision(setup):
    assert post(setup, {"answer_language": "en"}).status_code == 200
    with tenant_session(setup.engine, setup.tenant, actor_id=setup.peer) as session:
        assert session.scalar(select(PersonalPreference).where(
            PersonalPreference.owner_id == setup.human,
        )) is None
    with tenant_session(setup.engine, setup.other_tenant,
                        actor_id=setup.other_human) as session:
        assert list(session.scalars(select(PersonalPreference))) == []
    for fragment in ("revision=revision+2", "id=:id,revision=revision+1"):
        with pytest.raises(DBAPIError) as rejected:
            with tenant_session(setup.engine, setup.tenant, actor_id=setup.human) as session:
                session.execute(text("UPDATE personal_preferences SET " + fragment +
                                     " WHERE owner_id=:owner"),
                                {"owner": setup.human, "id": uuid4()})
        assert rejected.value.orig.sqlstate == "23514"
    with Session(setup.admin) as session:
        assert not session.scalar(text("SELECT has_table_privilege(" 
                                       "'pdos_agent','personal_preferences','SELECT')"))
        assert not session.scalar(text("SELECT has_table_privilege(" 
                                       "'pdos_agent','personal_preferences','INSERT,UPDATE,DELETE')"))


@pytest.mark.parametrize("invalid", [
    {"requester_id": str(uuid4())}, {"tenant_id": str(uuid4())},
    {"role": "administrator"}, {"favorite_category_ids": [str(uuid4())] * 2},
])
def test_actual_api_rejects_forged_or_invalid_fields(setup, invalid):
    response = post(setup, invalid)
    assert response.status_code == 422, response.text


def test_actual_downgrade_preserves_existing_account_settings(setup):
    from migrations.schema_s0_0831 import DOWNGRADE_SQL

    assert post(setup, {"response_detail": "brief"}).status_code == 200
    with pytest.raises(DBAPIError, match="Personal preferences require s0_0831"):
        with setup.admin.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE pdos_next_owner")
            for statement in DOWNGRADE_SQL:
                connection.exec_driver_sql(statement)
    with Session(setup.admin) as session:
        assert session.scalar(text("SELECT relforcerowsecurity FROM pg_class "
                                   "WHERE oid='personal_preferences'::regclass"))
        row = session.scalar(select(PersonalPreference).where(
            PersonalPreference.tenant_id == setup.tenant,
        ))
        assert row.body["response_detail"] == "brief" and row.revision == 1


def test_actual_frozen_recheck_allows_setting_edits_and_blocks_revoked_navigation(setup):
    fields = {"answer_language": "en", "favorite_category_ids": [str(setup.category)]}
    assert post(setup, fields).status_code == 200
    run_id, _ = start(setup, personal=True)
    bound = scope(setup, run_id, personal=True)
    store = KernelStore(setup.engine)
    with store.transaction(bound) as (session, _run):
        frozen = context_preferences(session, bound)
        assert recheck_context_preferences(session, bound, frozen)
    assert post(setup, {"answer_language": "ja"}, revision=1).status_code == 200
    with store.transaction(bound) as (session, _run):
        assert recheck_context_preferences(session, bound, frozen)
    with Session(setup.admin) as session, session.begin():
        grant = session.scalar(select(Grant).where(
            Grant.tenant_id == setup.tenant, Grant.category_id == setup.category,
            Grant.principal_id == setup.human,
        ))
        grant.expires_at = now() - timedelta(seconds=1)
    with store.transaction(bound) as (session, _run):
        assert not recheck_context_preferences(session, bound, frozen)
