"""Actual many-to-many requirement links retain pinned versions and scoped backlinks."""

# ruff: noqa: F811
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.schema import tables
from app.domain import opportunities
from app.domain.product_workspace import ProductWorkError
from tests.test_product_discovery_findings_api import seed_discovery
from tests.test_product_planning_findings_api import post
from tests.test_requirements_api import seed_other_tenant_requirement
from tests.test_test_runs_api import PASSWORD, Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_requirement_many_to_many_versions_rollback_and_visibility(
    client: TestClient,
    isolated_test_run_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        seed = seed_discovery(client, scope)
        base, headers = seed["base"], seed["headers"]
        requirement_ids = []
        for code in ("REL-A", "REL-B"):
            response = client.post(
                "/api/requirements", headers=headers, json=dict(code=code, title="合成" + code)
            )
            assert response.status_code == 201, response.text
            requirement_ids.append(response.json()["id"])

        def get(path, actor=headers):
            response = client.get(path, headers=actor)
            assert response.status_code == 200, response.text
            return response.json()

        def choices():
            return get(base + "/requirement-options")["items"]

        def links(values):
            return [
                dict(
                    requirement_id=v["id"],
                    payload_digest=v["payload_digest"],
                    rationale="合成版本明确引用",
                )
                for v in values
            ]

        def draft(**changes):
            return dict(
                request_id=str(uuid4()),
                segment_id=seed["segment"]["id"],
                title="合成关联机会",
                importance=None,
                satisfaction=None,
                importance_basis=seed["fact"],
                satisfaction_basis=seed["fact"],
                revision_reason="合成需求关系核对",
                **changes,
            )

        original_options = choices()
        original_links = links(original_options)
        first_body = draft(
            supersedes_id=seed["opportunity"]["id"], requirement_links=original_links
        )
        first = post(client, base, headers, "/opportunities", first_body, 201)
        second = post(
            client, base, headers, "/opportunities", draft(requirement_links=original_links), 201
        )
        assert len(first["requirement_links"]) == len(second["requirement_links"]) == 2
        assert post(client, base, headers, "/opportunities", first_body, 201)["id"] == first["id"]
        for identity in requirement_ids:
            backlinks = get(f"/api/product-work/requirements/{identity}/opportunities")["items"]
            assert {v["opportunity_id"] for v in backlinks} == {first["id"], second["id"]}
            assert all(v["is_latest"] and not v["has_changed"] for v in backlinks)

        changed_id = original_options[0]["id"]
        updated = client.patch(
            f"/api/requirements/{changed_id}", headers=headers, json=dict(title="合成已变更需求")
        )
        assert updated.status_code == 200, updated.text
        old = get(base + f"/opportunities/{first['id']}")
        changed = next(v for v in old["requirement_links"] if v["requirement_id"] == changed_id)
        assert changed["has_changed"]
        assert changed["requirement_snapshot"]["title"] != "合成已变更需求"
        with scope.engine.connect() as c:
            before = [
                c.execute(select(func.count()).select_from(t)).scalar_one()
                for t in (tables.opportunities, tables.opportunity_requirements, tables.events)
            ]
        post(client, base, headers, "/opportunities", draft(requirement_links=original_links), 409)
        post(
            client,
            base,
            headers,
            "/opportunities",
            draft(requirement_links=[original_links[0], original_links[0]]),
            422,
        )
        foreign_id = seed_other_tenant_requirement(isolated_test_run_database)[1]
        post(
            client,
            base,
            headers,
            "/opportunities",
            draft(
                requirement_links=[
                    dict(
                        requirement_id=str(foreign_id),
                        payload_digest="0" * 64,
                        rationale="跨租户引用应拒绝",
                    )
                ]
            ),
            403,
        )

        def fail_late(*args, **kwargs):
            raise ProductWorkError("合成事件失败，回滚机会与关系")

        with monkeypatch.context() as failed:
            failed.setattr(opportunities, "_emit", fail_late)
            post(
                client,
                base,
                headers,
                "/opportunities",
                draft(requirement_links=links(choices())),
                409,
            )
        with scope.engine.connect() as c:
            after = [
                c.execute(select(func.count()).select_from(t)).scalar_one()
                for t in (tables.opportunities, tables.opportunity_requirements, tables.events)
            ]
        assert before == after

        # A revision may explicitly retain a pinned historical requirement and drop another.
        revised = post(
            client,
            base,
            headers,
            "/opportunities",
            draft(supersedes_id=first["id"], requirement_links=[original_links[0]]),
            201,
        )
        assert revised["requirement_links"][0]["has_changed"]
        fresh_link = next(v for v in links(choices()) if v["requirement_id"] == changed_id)
        refreshed = post(
            client,
            base,
            headers,
            "/opportunities",
            draft(supersedes_id=revised["id"], requirement_links=[fresh_link]),
            201,
        )
        assert not refreshed["requirement_links"][0]["has_changed"]
        retained = get(f"/api/product-work/requirements/{changed_id}/opportunities")["items"]
        assert len(retained) == 4
        assert sum(v["is_latest"] for v in retained) == 2
        assert sum(v["has_changed"] for v in retained) == 3
        assert len(get(base + f"/opportunities/{first['id']}")["requirement_links"]) == 2

        member = uuid4()
        space_id = UUID(base.rsplit("/", 1)[1])
        with scope.engine.begin() as c:
            c.execute(
                tables.users.insert().values(
                    id=member,
                    tenant_id=scope.tenant_id,
                    username="relation-reader",
                    display_name="合成关系阅读人",
                    role="engineer",
                    password_hash=c.execute(
                        select(tables.users.c.password_hash).where(
                            tables.users.c.id == scope.owner_id
                        )
                    ).scalar_one(),
                    is_active=True,
                )
            )
            grants = dict(
                tenant_id=scope.tenant_id,
                market_space_id=space_id,
                user_id=member,
                access="viewer",
                added_by_user_id=scope.owner_id,
            )
            c.execute(tables.market_space_members.insert().values(**grants))
            c.execute(
                tables.product_line_members.insert().values(
                    **grants, product_line_id=UUID(seed["line"]["id"])
                )
            )
        login = client.post(
            "/api/auth/login",
            json=dict(tenant_slug="beepump", username="relation-reader", password=PASSWORD),
        )
        assert login.status_code == 200, login.text
        reader = {"Authorization": f"Bearer {login.json()['access_token']}"}
        path = f"/api/product-work/requirements/{changed_id}/opportunities"
        assert len(get(path, reader)["items"]) == 4
        with scope.engine.begin() as c:
            c.execute(
                tables.product_line_members.delete().where(
                    tables.product_line_members.c.user_id == member
                )
            )
        assert get(path, reader)["items"] == []
        denied = client.get(base + f"/opportunities/{refreshed['id']}", headers=reader)
        assert denied.status_code == 403 and "合成关联机会" not in denied.text
    finally:
        scope.dispose()
