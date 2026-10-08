"""Reversible category removal, current authority and retained shared data."""

# ruff: noqa: F811
from uuid import uuid4

import pytest

from tests.test_product_categories_api import parameter
from tests.test_product_proposals_api import command
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database
from tests.test_user_admin_api import _create_user, _login_headers


def category(client, headers, sid):
    return next(
        row
        for row in client.get("/api/product-work/categories", headers=headers).json()["items"]
        if row["id"] == sid
    )


def test_category_removal_replay_and_restore_preserve_identity_and_dictionary(
    client, isolated_test_run_database
):
    scope = Scope(client, isolated_test_run_database)
    try:
        h = bearer_headers(client)
        sid = space(client, h)
        base = f"/api/product-work/spaces/{sid}"
        shared = f"/api/product-work/categories/{sid}/shared"
        p, _ = parameter(client, h, shared)
        before = category(client, h, sid)
        assert before["can_restore"] and before["payload_digest"]
        body = {**command(before), "lifecycle": "archived", "reason": "人工删除合成品类"}
        saved = client.post(base + "/lifecycle", headers=h, json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == before["version"] + 1
        assert saved.json()["lifecycle"] == "archived"
        assert client.post(base + "/lifecycle", headers=h, json=body).json() == saved.json()
        archived = category(client, h, sid)
        assert (
            archived["can_restore"] and archived["category_line_id"] == before["category_line_id"]
        )
        assert client.get(shared, headers=h).json()["parameters"][0]["id"] == p["id"]
        detail = client.get(base, headers=h).json()
        assert detail["can_restore"] and not detail["can_manage"]
        assert (
            client.post(
                base + "/lifecycle",
                headers=h,
                json={**command(before), "lifecycle": "active", "reason": "过期快照反例"},
            ).status_code
            == 409
        )
        restored = client.post(
            base + "/lifecycle",
            headers=h,
            json={**command(archived), "lifecycle": "active", "reason": "恢复原品类"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["version"] == before["version"] + 2
        assert client.get(shared, headers=h).json()["parameters"][0]["id"] == p["id"]
        assert client.get(base, headers=h).json()["can_manage"]
    finally:
        scope.dispose()


@pytest.mark.parametrize(
    ("role", "access", "allowed"),
    [
        ("product_manager", "viewer", False),
        ("product_manager", "contributor", False),
        ("engineer", "manager", False),
        ("product_manager", "manager", True),
    ],
)
def test_category_directory_authority_matches_lifecycle_write(
    client, isolated_test_run_database, role, access, allowed
):
    scope = Scope(client, isolated_test_run_database)
    try:
        owner = bearer_headers(client)
        sid, other = space(client, owner), space(client, owner)
        user = _create_user(client, owner, username="category-person", role=role)
        h = _login_headers(client, username="category-person", password="temporary passphrase 2026")
        assert (
            client.put(
                f"/api/product-work/spaces/{sid}/members/{user['id']}",
                headers=owner,
                json={"access": access},
            ).status_code
            == 204
        )
        row = category(client, h, sid)
        assert row["can_restore"] is allowed
        assert [
            r["id"] for r in client.get("/api/product-work/categories", headers=h).json()["items"]
        ] == [sid]
        before = category(client, owner, other)
        assert (
            client.post(
                f"/api/product-work/spaces/{other}/lifecycle",
                headers=h,
                json={**command(before), "lifecycle": "archived", "reason": "无范围权限反例"},
            ).status_code
            == 403
        )
        result = client.post(
            f"/api/product-work/spaces/{sid}/lifecycle",
            headers=h,
            json={**command(row), "lifecycle": "archived", "reason": "当前权限核对"},
        )
        assert result.status_code == (200 if allowed else 403), result.text
        assert category(client, owner, sid)["lifecycle"] == ("archived" if allowed else "draft")
    finally:
        scope.dispose()


def test_unfinished_research_blocks_category_removal_until_explicitly_cancelled(
    client, isolated_test_run_database
):
    scope = Scope(client, isolated_test_run_database)
    try:
        h = bearer_headers(client)
        sid = space(client, h)
        base = f"/api/product-work/spaces/{sid}"
        r = client.post(
            base + "/research",
            headers=h,
            json={
                "request_id": str(uuid4()),
                "owner_user_id": str(scope.owner_id),
                "question": "合成未结束研究",
                "user_groups": ["测试用户"],
                "regions": ["TEST"],
                "time_scope": "本周",
                "method": "合成核对",
                "expected_decision": "验证删除守卫",
                "stop_conditions": ["人工停止"],
            },
        )
        assert r.status_code == 201, r.text
        before = category(client, h, sid)
        body = {**command(before), "lifecycle": "archived", "reason": "未结束工作反例"}
        refused = client.post(base + "/lifecycle", headers=h, json=body)
        assert refused.status_code == 409 and "未结束" in refused.json()["detail"]["message"]
        assert category(client, h, sid)["version"] == before["version"]
        cancelled = client.post(
            base + f"/research/{r.json()['id']}/cancel",
            headers=h,
            json={**command(r.json()), "reason": "人工明确取消合成任务"},
        )
        assert cancelled.status_code == 200, cancelled.text
        saved = client.post(base + "/lifecycle", headers=h, json=body)
        assert saved.status_code == 200, saved.text
    finally:
        scope.dispose()
