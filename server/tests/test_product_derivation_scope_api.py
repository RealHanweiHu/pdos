"""Source-line authorization, invalid cross-line requests and revoked derived sources."""

# ruff: noqa: F811
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.product_work_context import readable
from app.ai.project_discussion_sources import actor
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkAccessError
from tests.test_definition_inheritance_api import seed
from tests.test_product_manager_loop_api import command
from tests.test_product_planning_findings_api import post
from tests.test_test_runs_api import PASSWORD, Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def destination(client, scope, base, headers):
    member = uuid4()
    with scope.engine.begin() as c:
        password = c.execute(
            select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
        ).scalar_one()
        c.execute(
            tables.users.insert().values(
                id=member,
                tenant_id=scope.tenant_id,
                username="scoped-pm",
                display_name="合成受限产品经理",
                role="project_manager",
                password_hash=password,
                is_active=True,
            )
        )
        c.execute(
            tables.market_space_members.insert().values(
                tenant_id=scope.tenant_id,
                market_space_id=UUID(base.rsplit("/", 1)[1]),
                user_id=member,
                access="manager",
                added_by_user_id=scope.owner_id,
            )
        )
    login = client.post(
        "/api/auth/login",
        json={
            "tenant_slug": "beepump",
            "username": "scoped-pm",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200
    own = {"Authorization": "Bearer " + login.json()["access_token"]}
    parent = line = post(
        client,
        base,
        own,
        "/products",
        dict(
            request_id=str(uuid4()),
            code="TARGET",
            name="合成目标线",
            level="line",
            owner_user_id=str(member),
        ),
        201,
    )
    for level in ["family", "platform", "series"]:
        parent = post(
            client,
            base,
            own,
            "/products",
            dict(
                request_id=str(uuid4()),
                code="TARGET-" + level,
                name="合成目标" + level,
                level=level,
                parent_id=parent["id"],
                owner_user_id=str(member),
            ),
            201,
        )
    return member, own, line, parent


def source_access(client, base, headers, line_id, member, access):
    nodes = client.get(base + "/products", headers=headers).json()["nodes"]
    line = next(n for n in nodes if n["id"] == line_id)
    post(
        client,
        base,
        headers,
        f"/products/{line_id}/members",
        {
            **command(line),
            "user_id": str(member),
            "access": access,
        },
    )


def test_catalog_authorizes_original_source_and_rejects_cross_line_without_sql_error(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, source, _ = seed(client, scope, tmp_path, monkeypatch)
        member, own, line, series = destination(client, scope, base, headers)
        body = dict(
            request_id=str(uuid4()),
            code="CROSS-DERIVED",
            name="合成跨线派生请求",
            level="model",
            parent_id=series["id"],
            derived_from=source["product_id"],
            owner_user_id=str(member),
        )
        with scope.engine.connect() as c:
            before = c.execute(select(func.count()).select_from(tables.product_nodes)).scalar_one()
            audits = c.execute(select(func.count()).select_from(tables.audit_log)).scalar_one()
        denied = client.post(base + "/products", headers=own, json=body)
        assert denied.status_code == 403, denied.text
        assert source["title"] not in denied.text
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.product_nodes)).scalar_one()
                == before
            )
            assert (
                c.execute(select(func.count()).select_from(tables.audit_log)).scalar_one() == audits
            )
        source_access(client, base, headers, source["product_line_id"], member, "viewer")
        rejected = post(client, base, own, "/products", body, 409)
        assert "同一产品线" in rejected["detail"]["message"]
        assert post(client, base, own, "/products", body, 409) == rejected
        post(
            client, base, headers, "/products", {**body, "owner_user_id": str(scope.owner_id)}, 409
        )
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.product_nodes)).scalar_one()
                == before
            )
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()


def test_same_line_derivation_revocation_hides_original_and_inherited_data_then_replays(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, source, _ = seed(client, scope, tmp_path, monkeypatch)
        member, own, own_line, _ = destination(client, scope, base, headers)
        source_access(client, base, headers, source["product_line_id"], member, "manager")
        path = f"/definitions/{source['id']}/derive"
        body = {
            **command(source),
            "code": "SCOPED-DERIVED",
            "name": "合成具名派生",
            "reason": "合成范围验证",
        }
        child = post(client, base, own, path, body, 201)
        assert child["product_line_id"] == source["product_line_id"]
        selection = dict(
            capability="product_definition",
            product_line_id=source["product_line_id"],
            question="合成派生来源权限",
            sources=[dict(kind="definition", id=child["id"])],
        )
        pack = post(client, base, own, "/product-ai-context", selection)
        assert source["content"]["scenarios"][0] in str(pack)
        before = client.get("/api/product-work/my-work?collection=definitions", headers=own).json()
        assert before["pages"]["definitions"]["total"] >= 1
        source_access(client, base, headers, source["product_line_id"], member, None)
        for identity in [source["id"], child["id"]]:
            for suffix in ["", "/history", "/parent-comparison"]:
                response = client.get(base + f"/definitions/{identity}" + suffix, headers=own)
                assert response.status_code == 403, response.text
                assert source["content"]["scenarios"][0] not in response.text
        post(client, base, own, "/product-ai-context", selection, 403)
        post(
            client,
            base,
            own,
            "/product-ai-options",
            {
                "kind": "definition",
                "product_line_id": source["product_line_id"],
            },
            403,
        )
        post(
            client,
            base,
            own,
            "/definition-export-preview",
            {
                "definition_id": child["id"],
                "format": "docx",
                "reason": "合成失权原件拒绝",
            },
            403,
        )
        post(client, base, own, path, body, 403)
        with scope.engine.connect() as c, pytest.raises(ProductWorkAccessError):
            readable(c, actor(c, scope.tenant_id, member), pack)
        catalog = client.get(base + "/products", headers=own).json()
        assert len(catalog["nodes"]) == 4 and own_line["id"] in str(catalog)
        assert child["product_id"] not in str(catalog) and source["product_line_id"] not in str(
            catalog
        )
        assert client.get(base + "/definitions", headers=own).json()["items"] == []
        after = client.get("/api/product-work/my-work?collection=definitions", headers=own).json()
        assert after["definitions"] == [] and after["pages"]["definitions"]["total"] == 0
        post(
            client,
            base,
            own,
            "/product-matrix",
            {"product_line_id": source["product_line_id"]},
            403,
        )
        # Restoring authority does not rewrite the original product, definition or receipt.
        source_access(client, base, headers, source["product_line_id"], member, "manager")
        assert post(client, base, own, path, body, 201)["id"] == child["id"]
        current = client.get(base + f"/definitions/{child['id']}", headers=own)
        assert current.status_code == 200 and current.json()["content"] == child["content"]
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()
