"""Synthetic matrix decisions need actual reception and later published revisions."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_manager_loop_api import command
from tests.test_product_manager_loop_api import (
    test_research_to_released_definition_matrix_and_roadmap_without_project as seed_journey,
)
from tests.test_product_planning_findings_api import post, release_definition
from tests.test_test_runs_api import PASSWORD, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_matrix_decisions_to_accepted_work_and_published_revisions(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    seed_journey(client, isolated_test_run_database)
    engine = create_engine(isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        receiver = uuid4()
        with engine.begin() as c:
            saved = (
                c.execute(
                    select(tables.product_matrix_records)
                    .order_by(tables.product_matrix_records.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one()
            )
            draft = (
                c.execute(
                    select(tables.product_definitions).where(
                        tables.product_definitions.c.state == "draft"
                    )
                )
                .mappings()
                .one()
            )
            owner = saved["actor_user_id"]
            common = dict(
                tenant_id=saved["tenant_id"],
                market_space_id=saved["market_space_id"],
                user_id=receiver,
                access="contributor",
                added_by_user_id=owner,
            )
            c.execute(
                tables.users.insert().values(
                    id=receiver,
                    tenant_id=saved["tenant_id"],
                    username="matrix-receiver",
                    display_name="合成独立接收人",
                    role="engineer",
                    is_active=True,
                    password_hash=c.execute(
                        select(tables.users.c.password_hash).where(tables.users.c.id == owner)
                    ).scalar_one(),
                )
            )
            c.execute(tables.market_space_members.insert().values(**common))
            c.execute(
                tables.product_line_members.insert().values(
                    **common, product_line_id=saved["product_line_id"]
                )
            )
        login = client.post(
            "/api/auth/login",
            json=dict(tenant_slug="beepump", username="matrix-receiver", password=PASSWORD),
        )
        assert login.status_code == 200, login.text
        receiver_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        base = f"/api/product-work/spaces/{saved['market_space_id']}"
        products = [p["id"] for p in saved["result"]["snapshot"]["products"]]
        product = str(draft["product_id"])
        fact = deepcopy(draft["content"]["items"][0]["rationale"])
        fact["fact_kind"] = "observed"
        ref = fact["sources"][0]

        def call(path, body, status=200, as_receiver=False):
            return post(
                client, base, receiver_headers if as_receiver else headers, path, body, status
            )

        def get(path):
            response = client.get(base + path, headers=headers)
            assert response.status_code == 200, response.text
            return response.json()

        def source(disposition):
            return call("/matrix-outcomes", dict(disposition_id=disposition["id"]))

        def result_body(disposition, current, kind, checked):
            return dict(
                disposition_id=disposition["id"],
                request_id=str(uuid4()),
                expected_version=current["version"],
                expected_source_digest=current["source"]["digest"],
                state="verified",
                checked_product_ids=checked,
                reason="合成验证实际发布与独立接收回执",
                verification=fact,
                versions=[
                    {k: option[k] for k in ("product_id", "kind", "ref_id")}
                    for option in current["source"]["options"]
                    if option["kind"] == kind and option["product_id"] in checked
                ],
            )

        for kind in ("definition", "roadmap"):
            matrix = call("/matrix-dispositions", dict(record_id=str(saved["id"])))
            decision_body = dict(
                record_id=str(saved["id"]),
                request_id=str(uuid4()),
                expected_source_digest=matrix["source"]["digest"],
                topic="coverage_gap",
                product_ids=products,
                criterion_keys=["lighting"],
                title="合成照明覆盖修订",
                outcome="revise_" + kind,
                reason="实际修订前只登记决策和跟进工作",
                followup=dict(
                    request_id=str(uuid4()),
                    product_line_id=str(saved["product_line_id"]),
                    title="合成修订接收",
                    action_type="discipline_review",
                    owner_user_id=str(owner),
                    receiver_user_id=str(receiver),
                    expected_output="实际修订依据",
                    completion_criteria="接收人核对实际输出",
                    due_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
                ),
            )
            decision = call("/matrix-disposition-save", decision_body)
            assert call("/matrix-disposition-save", decision_body)["id"] == decision["id"]
            assert decision["current_work"]["acceptance_required"]
            current = source(decision)
            request = result_body(decision, current, kind, [product])
            call(
                "/matrix-outcome-save",
                {
                    **request,
                    "verification": {**fact, "fact_kind": "hypothesis"},
                },
                422,
            )
            rejected = call("/matrix-outcome-save", request, 409)
            assert "接收" in str(rejected)
            work = next(w for w in get("")["work_items"] if w["id"] == decision["work_item_id"])
            work_path = f"/work-items/{work['id']}/actions"
            work = call(work_path, {**command(work), "action": "start", "note": "合成开始"})
            work = call(
                work_path,
                {**command(work), "action": "submit", "note": "合成提交", "evidence": [ref]},
            )
            current = source(decision)
            rejected = call(
                "/matrix-outcome-save", result_body(decision, current, kind, [product]), 409
            )
            assert "接收" in str(rejected)
            accept = {**command(work), "action": "accept", "note": "合成指定接收人核验"}
            call(work_path, accept, 403)  # Owner cannot impersonate the designated receiver.
            work = call(work_path, accept, as_receiver=True)
            assert work["state"] == "completed" and work["accepted_at"]
            current = source(decision)
            rejected = call(
                "/matrix-outcome-save", result_body(decision, current, kind, [product]), 409
            )
            assert "修订版本" in str(rejected) or "依据待重核" in str(rejected)

            if kind == "definition":
                value = get(f"/definitions/{draft['id']}")
                content = deepcopy(value["content"])
                content.update(
                    included_features=["inflate", "lighting"],
                    excluded_features=[],
                    change_reason="合成照明覆盖修订，经原协审发布",
                )
                value = call(
                    f"/definitions/{draft['id']}/changes",
                    {**command(value), "content": content, "reason": "合成修订"},
                )
                published = release_definition(client, base, headers, value)
                assert published["is_current"]
            else:
                roadmap = call("/product-roadmap", dict(product_id=product))
                call(
                    "/product-roadmap-save",
                    dict(
                        product_id=product,
                        request_id=str(uuid4()),
                        expected_version=roadmap["latest"]["version"],
                        expected_source_digest=roadmap["source_digest"],
                        action="publish",
                        reason="合成照明验证节点修订",
                        body=dict(
                            scope_note="合成照明验证窗口",
                            checkpoints=[
                                *roadmap["latest"]["body"]["checkpoints"],
                                dict(
                                    key="lighting",
                                    title="照明验证待定",
                                    kind="validation",
                                    owner_user_id=str(owner),
                                    window_start=None,
                                    window_end=None,
                                    unknown_reason="真实资源未确认",
                                    basis=fact,
                                ),
                            ],
                        ),
                    ),
                )
            current = source(decision)
            call("/matrix-outcome-save", result_body(decision, current, kind, products), 409)
            body = result_body(decision, current, kind, [product])
            confirmed = call("/matrix-outcome-save", body)
            assert confirmed["state"] == "verified" and confirmed["sources_current"]
            assert confirmed["unchecked_product_ids"] == [p for p in products if p != product]
            assert len(confirmed["versions"]) == 1
            assert call("/matrix-outcome-save", body)["id"] == confirmed["id"]
            call("/matrix-outcome-save", {**body, "request_id": str(uuid4())}, 409)
            call("/matrix-outcome-save", {**body, "reason": "同一请求偷换内容"}, 409)
            read = call("/matrix-outcomes", dict(disposition_id=decision["id"]), as_receiver=True)
            assert not read["can_record"] and read["items"][0]["id"] == confirmed["id"]
            call("/matrix-outcome-save", body, 403, as_receiver=True)
            assert source(decision)["version"] == 1

        # The SQL guard still rejects forged source snapshots and out-of-order versions.
        with engine.connect() as c:
            original = dict(
                c.execute(
                    select(tables.product_matrix_outcomes).where(
                        tables.product_matrix_outcomes.c.id == confirmed["id"]
                    )
                )
                .mappings()
                .one()
            )
        for tamper in ("disposition", "timestamp", "digest", "scope", "version"):
            forged = deepcopy(original)
            forged.update(id=uuid4(), request_id=uuid4(), version=2)
            if tamper == "disposition":
                forged["source_snapshot"]["disposition"]["reason"] = "伪造原处置"
            elif tamper == "timestamp":
                forged["source_snapshot"]["disposition"]["created_at"] = "2000-01-01T00:00:00Z"
            elif tamper == "digest":
                forged["source_digest"] = "0" * 64
            elif tamper == "scope":
                forged["checked_product_ids"] = [str(uuid4())]
            else:
                forged["version"] = 3
            with (
                pytest.raises(DBAPIError, match="original disposition, scope and ordered version"),
                engine.begin() as c,
            ):
                c.execute(tables.product_matrix_outcomes.insert().values(**forged))
        with (
            pytest.raises(DBAPIError, match="Retain usable matrix outcome history"),
            rollback_migration_operations(engine),
        ):
            import_module("migrations.versions.0406_matrix_outcome_guard").downgrade()
        with pytest.raises(DBAPIError), engine.begin() as c:
            c.execute(
                tables.product_matrix_outcomes.update()
                .where(tables.product_matrix_outcomes.c.id == confirmed["id"])
                .values(reason="改写历史")
            )

        with engine.begin() as c:
            c.execute(
                tables.product_line_members.delete().where(
                    tables.product_line_members.c.user_id == receiver
                )
            )
            assert (
                c.execute(
                    select(func.count()).select_from(tables.product_matrix_dispositions)
                ).scalar_one()
                == 2
            )
            assert (
                c.execute(
                    select(func.count()).select_from(tables.product_matrix_outcomes)
                ).scalar_one()
                == 2
            )
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
        denied = call(
            "/matrix-outcomes", dict(disposition_id=decision["id"]), 403, as_receiver=True
        )
        assert "合成照明" not in str(denied)
        assert source(decision)["version"] == 1
    finally:
        engine.dispose()
