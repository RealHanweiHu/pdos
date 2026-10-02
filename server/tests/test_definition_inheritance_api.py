"""Pinned inheritance, partial three-way acceptance and independent human release."""

# ruff: noqa: F811
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_manager_loop_api import command
from tests.test_product_planning_findings_api import post, release_definition, setup_candidate
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def seed(
    client: TestClient, scope: Scope, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, ...]:
    return setup_candidate(
        client, scope, tmp_path, monkeypatch, "product_definition", True, seed_only=True
    )


def test_derived_definition_partial_parent_updates_and_independent_release(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, parent, _ = seed(client, scope, tmp_path, monkeypatch)
        path = f"/definitions/{parent['id']}/derive"
        derive = {
            **command(parent),
            "code": "DERIVED-1",
            "name": "派生产品",
            "reason": "合成地区差异",
        }
        child = post(client, base, headers, path, derive, 201)
        assert post(client, base, headers, path, derive, 201)["id"] == child["id"]
        assert (
            child["product_id"] != parent["product_id"]
            and child["base_definition_id"] == parent["id"]
        )
        assert child["content"]["reviewers"] == {} and child["state"] == "draft"
        assert child["content"]["items"][0]["state"] == "needs_confirmation"
        assert child["content"]["items"][0]["owner_user_id"] is None
        d, n = tables.product_definitions, tables.product_nodes
        with scope.engine.connect() as c:
            raw = c.execute(select(d).where(d.c.id == UUID(child["id"]))).mappings().one()
            assert "scenarios" not in raw["content"] and "target_cost" not in raw["content"]
            assert c.execute(
                select(n.c.derived_from).where(n.c.id == UUID(child["product_id"]))
            ).scalar_one() == UUID(parent["product_id"])
        content = deepcopy(child["content"])
        content["scenarios"] = ["本地区户外场景"]
        content["items"][0]["target_value"] = "110"
        child = post(
            client,
            base,
            headers,
            f"/definitions/{child['id']}/changes",
            {**command(child), "content": content, "reason": "合成本地修改"},
        )
        # Upstream additions and edits never silently appear locally.
        content = deepcopy(parent["content"])
        content["scenarios"] = ["父产品新场景"]
        content["items"][0]["target_value"] = "120"
        added = deepcopy(content["items"][0])
        added.update(item_key="noise", title="噪声", unit="dB", target_value="70")
        content["items"].append(added)
        content["change_reason"] = "合成父版升级"
        incoming = post(
            client,
            base,
            headers,
            "/definitions",
            {
                "request_id": str(uuid4()),
                "product_id": parent["product_id"],
                "strategy_id": parent["strategy_id"],
                "supersedes_id": parent["id"],
                "content": content,
            },
            201,
        )
        incoming = release_definition(client, base, headers, incoming)
        current = client.get(base + f"/definitions/{child['id']}", headers=headers).json()
        assert current["content"]["items"][0]["target_value"] == "110"
        compare = client.get(
            base + f"/definitions/{child['id']}/parent-comparison", headers=headers
        )
        assert compare.status_code == 200, compare.text
        comparison = compare.json()
        assert next(x for x in comparison["changes"] if x["path"] == "items/pressure")["conflict"]
        body = {
            **command(child),
            **{
                k: comparison[k]
                for k in ["target_definition_id", "target_release_id", "comparison_digest"]
            },
            "accept_paths": ["items/pressure"],
            "reason": "仅接受压力，不接受新场景与噪声",
        }
        wrong = {**body, "comparison_digest": "0" * 64}
        post(client, base, headers, f"/definitions/{child['id']}/parent-merge", wrong, 409)
        child = post(client, base, headers, f"/definitions/{child['id']}/parent-merge", body)
        assert (
            post(client, base, headers, f"/definitions/{child['id']}/parent-merge", body)["version"]
            == child["version"]
        )
        assert child["base_definition_id"] == parent["id"] and len(child["parent_updates"]) == 1
        assert child["parent_updates"][0]["source"]["ref_id"] == incoming["id"]
        assert child["content"]["scenarios"] == ["本地区户外场景"]
        assert [i["item_key"] for i in child["content"]["items"]] == ["pressure"]
        assert child["content"]["items"][0]["target_value"] == "120"
        assert child["content"]["items"][0]["state"] == "needs_confirmation"
        content = deepcopy(child["content"])
        content["reviewers"] = {k: str(scope.owner_id) for k in ["id", "md", "ee", "fw", "dqe"]}
        content["items"][0].update(state="confirmed", owner_user_id=str(scope.owner_id))
        child = post(
            client,
            base,
            headers,
            f"/definitions/{child['id']}/changes",
            {**command(child), "content": content, "reason": "合成具名确认"},
        )
        child = release_definition(client, base, headers, child)
        assert child["is_current"] and child["state"] == "published"
        matrix = post(
            client, base, headers, "/product-matrix", {"product_line_id": child["product_line_id"]}
        )
        assert child["id"] in str(matrix) and incoming["id"] in str(matrix)
        assert (
            client.get(base + f"/definitions/{parent['id']}", headers=headers).json()["content"]
            == parent["content"]
        )
        export = post(
            client,
            base,
            headers,
            "/definition-export-preview",
            {"definition_id": child["id"], "format": "docx", "reason": "合成派生规格预览"},
        )
        assert export["source"]["definition"]["content"] == child["content"]
        assert export["source"]["definition"]["base_definition_ref"]["ref_id"] == parent["id"]
        assert any(section["title"] == "显式接受的父版更新" for section in export["sections"])
        prepared = post(
            client,
            base,
            headers,
            "/product-ai-context",
            {
                "capability": "product_definition",
                "product_line_id": child["product_line_id"],
                "question": "合成派生规格来源检查",
                "sources": [{"kind": "definition", "id": child["id"]}],
            },
        )
        source = next(
            ref
            for ref in prepared["references"]
            if ref["reference_id"] == "definition:" + child["id"]
        )
        assert source["fields"]["content"] == child["content"]
        assert source["fields"]["base_definition_ref"]["ref_id"] == parent["id"]
        # Child revisions retain the base, accepted sources and sparse storage.
        revised = post(
            client,
            base,
            headers,
            "/definitions",
            {
                "request_id": str(uuid4()),
                "product_id": child["product_id"],
                "strategy_id": child["strategy_id"],
                "supersedes_id": child["id"],
                "content": child["content"],
            },
            201,
        )
        assert (
            revised["parent_updates"] == child["parent_updates"]
            and revised["base_definition_id"] == parent["id"]
        )
    finally:
        scope.dispose()


def test_derivation_atomicity_and_immutable_parent_origin(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain import derived_definitions as service

    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, parent, _ = seed(client, scope, tmp_path, monkeypatch)
        body = {
            **command(parent),
            "code": "DERIVED-2",
            "name": "独立派生产品",
            "reason": "合成原子性",
        }
        path = f"/definitions/{parent['id']}/derive"

        def fail(*args: Any, **kwargs: Any) -> Any:
            raise ProductWorkError("合成定义创建失败")

        with monkeypatch.context() as patch:
            patch.setattr(service, "create_definition_in_connection", fail)
            post(client, base, headers, path, body, 409)
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.product_nodes)
                    .where(tables.product_nodes.c.code == body["code"])
                ).scalar_one()
                == 0
            )
        child = post(client, base, headers, path, body, 201)
        post(
            client,
            base,
            headers,
            f"/definitions/{child['id']}/derive",
            {**command(child), "code": "BAD", "name": "未发布父版", "reason": "拒绝"},
            409,
        )
        duplicate = {**body, **command(parent)}
        conflict = client.post(base + path, headers=headers, json=duplicate)
        assert conflict.status_code == 409 and "产品编号" in conflict.text
        member = uuid4()
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            c.execute(
                tables.users.insert().values(
                    id=member,
                    tenant_id=scope.tenant_id,
                    username="limited-pm",
                    display_name="合成无产品线权限经理",
                    role="project_manager",
                    password_hash=password,
                    is_active=True,
                )
            )
            c.execute(
                tables.market_space_members.insert().values(
                    tenant_id=scope.tenant_id,
                    market_space_id=UUID(base.rsplit("/", 1)[-1]),
                    user_id=member,
                    access="manager",
                    added_by_user_id=scope.owner_id,
                )
            )
        from tests.test_test_runs_api import PASSWORD

        login = client.post(
            "/api/auth/login",
            json={"tenant_slug": "beepump", "username": "limited-pm", "password": PASSWORD},
        )
        assert login.status_code == 200
        denied_headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        post(client, base, denied_headers, path, body, 403)
        assert (
            client.get(
                base + f"/definitions/{child['id']}/parent-comparison", headers=denied_headers
            ).status_code
            == 403
        )
        for table, id, values in [
            (tables.product_nodes, child["product_id"], {"derived_from": None}),
            (
                tables.product_definitions,
                child["id"],
                {"base_definition_id": None, "base_definition_ref": None},
            ),
        ]:
            with pytest.raises(DBAPIError), scope.engine.begin() as c:
                c.execute(table.update().where(table.c.id == UUID(id)).values(**values, version=2))
        content = deepcopy(child["content"])
        content["items"] = []
        post(
            client,
            base,
            headers,
            f"/definitions/{child['id']}/changes",
            {**command(child), "content": content, "reason": "不能删父规格"},
            422,
        )
        with pytest.raises(DBAPIError), rollback_migration_operations(scope.engine):
            import_module("migrations.versions.0402_definition_inheritance").downgrade()
    finally:
        scope.dispose()
