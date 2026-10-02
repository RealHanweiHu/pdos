"""Published specification handoff keeps real releases and scoped reverse sources."""

# ruff: noqa: F811
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app.db.schema import tables
from tests.test_product_manager_loop_api import command
from tests.test_product_manager_loop_api import (
    test_research_to_released_definition_matrix_and_roadmap_without_project as seed_journey,
)
from tests.test_product_planning_findings_api import post, release_definition
from tests.test_requirements_api import seed_other_tenant_requirement
from tests.test_test_runs_api import PASSWORD, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_definition_requirement_handoff_reuse_replacement_and_revocation(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    seed_journey(client, isolated_test_run_database)
    engine = create_engine(isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        with engine.connect() as c:
            definitions = c.execute(select(tables.product_definitions)).mappings().all()
        revision = next(d for d in definitions if d["state"] == "draft")
        original = next(d for d in definitions if d["id"] == revision["supersedes_id"])
        peer = next(d for d in definitions if d["product_id"] != original["product_id"])
        base = f"/api/product-work/spaces/{original['market_space_id']}"

        def call(path, body, status=200, actor=headers):
            return post(client, base, actor, path, body, status)

        def get(path, actor=headers):
            response = client.get(path, headers=actor)
            assert response.status_code == 200, response.text
            return response.json()

        def package(definition, **changes):
            return call(
                "/requirement-packages",
                dict(
                    request_id=str(uuid4()),
                    definition_id=str(definition["id"]),
                    candidates=[
                        dict(
                            key="pressure",
                            item_keys=["pressure"],
                            mode="new",
                            rationale="合成稳定规格传递",
                            **changes,
                        )
                    ],
                ),
                201,
            )

        def action(value, name, status=200):
            return call(
                f"/requirement-packages/{value['id']}/actions",
                {
                    **command(value),
                    "action": name,
                    "reviewed_proposal_digest": value["proposal_digest"],
                    "reason": "合成人工核对原发布规格",
                },
                status,
            )

        created = package(original)
        action(created, "apply", 409)
        accepted = action(created, "accept")
        assert accepted["state"] == "accepted"
        with engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.requirements)).scalar_one() == 0
            )
        apply = {
            **command(accepted),
            "action": "apply",
            "reviewed_proposal_digest": accepted["proposal_digest"],
            "reason": "合成独立应用",
        }
        applied = call(f"/requirement-packages/{accepted['id']}/actions", apply)
        assert call(f"/requirement-packages/{accepted['id']}/actions", apply)["id"] == applied["id"]
        requirement_id = applied["result"]["requirements"][0]["requirement_id"]
        requirement = get(f"/api/requirements/{requirement_id}")
        assert requirement["status"] == "draft" and "[pressure]" in requirement["description"]
        assert "100" in requirement["description"] and "kPa" in requirement["description"]
        assert "25℃" in requirement["description"]

        def reused(definition, acknowledge):
            return call(
                "/requirement-packages",
                dict(
                    request_id=str(uuid4()),
                    definition_id=str(definition["id"]),
                    candidates=[
                        dict(
                            key="pressure",
                            item_keys=["pressure"],
                            mode="reuse",
                            requirement_id=requirement_id,
                            acknowledge_differences=acknowledge,
                            rationale="仅关联原需求，不改写内容",
                        )
                    ],
                ),
                201,
            )

        unacknowledged = reused(peer, False)
        action(unacknowledged, "accept", 409)
        action(action(reused(peer, True), "accept"), "apply")
        assert get(f"/api/requirements/{requirement_id}") == requirement
        sources_path = f"/api/product-work/requirements/{requirement_id}/definition-sources"
        assert len(get(sources_path)["items"]) == 2

        # A previously accepted package cannot apply after its source release is replaced.
        pending = action(reused(original, True), "accept")
        revised = release_definition(
            client, base, headers, get(base + f"/definitions/{revision['id']}")
        )
        assert revised["is_current"]
        action(pending, "apply", 409)
        old_sources = get(sources_path)["items"]
        assert not next(v for v in old_sources if v["definition_id"] == str(original["id"]))[
            "source_is_current"
        ]
        action(action(reused(revision, True), "accept"), "apply")
        assert get(f"/api/requirements/{requirement_id}") == requirement
        sources = get(sources_path)["items"]
        assert len(sources) == 3 and sum(v["source_is_current"] for v in sources) == 2
        assert {v["specification_snapshot"]["target_value"] for v in sources} == {"100", "110"}
        updated = client.patch(
            f"/api/requirements/{requirement_id}",
            headers=headers,
            json=dict(title="合成后续需求修订"),
        )
        assert updated.status_code == 200, updated.text
        assert all(v["requirement_has_changed"] for v in get(sources_path)["items"])
        foreign = seed_other_tenant_requirement(isolated_test_run_database)[1]
        call(
            "/requirement-packages",
            dict(
                request_id=str(uuid4()),
                definition_id=revised["id"],
                candidates=[
                    dict(
                        key="pressure",
                        item_keys=["pressure"],
                        mode="reuse",
                        requirement_id=str(foreign),
                        acknowledge_differences=True,
                        rationale="拒绝跨租户需求",
                    )
                ],
            ),
            403,
        )

        reader_id = uuid4()
        with engine.begin() as c:
            owner = (
                c.execute(select(tables.users).where(tables.users.c.username == "owner"))
                .mappings()
                .one()
            )
            c.execute(
                tables.users.insert().values(
                    id=reader_id,
                    tenant_id=original["tenant_id"],
                    username="definition-reader",
                    display_name="合成规格回链阅读人",
                    role="engineer",
                    password_hash=owner["password_hash"],
                    is_active=True,
                )
            )
            grants = dict(
                tenant_id=original["tenant_id"],
                market_space_id=original["market_space_id"],
                user_id=reader_id,
                access="viewer",
                added_by_user_id=owner["id"],
            )
            c.execute(tables.market_space_members.insert().values(**grants))
            c.execute(
                tables.product_line_members.insert().values(
                    **grants, product_line_id=original["product_line_id"]
                )
            )
        login = client.post(
            "/api/auth/login",
            json=dict(tenant_slug="beepump", username="definition-reader", password=PASSWORD),
        )
        assert login.status_code == 200, login.text
        reader = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert len(get(sources_path, reader)["items"]) == 3
        with engine.begin() as c:
            c.execute(
                tables.product_line_members.delete().where(
                    tables.product_line_members.c.user_id == reader_id
                )
            )
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.requirements)
                    .where(tables.requirements.c.tenant_id == original["tenant_id"])
                ).scalar_one()
                == 1
            )
        assert get(sources_path, reader)["items"] == []
        denied = client.get(base + f"/requirement-packages/{applied['id']}", headers=reader)
        assert denied.status_code == 403 and "合成稳定" not in denied.text
    finally:
        engine.dispose()
