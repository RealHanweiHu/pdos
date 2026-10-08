"""Independent product-manager identity, scope and project-administration denials."""

from importlib import import_module
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.test_gate_api import seed_project
from tests.test_product_work_preparation_api import space
from tests.test_user_admin_api import _create_user, _login_headers, _owner_headers
from tests.test_user_admin_api import client as client
from tests.test_user_admin_api import isolated_user_admin_database as isolated_user_admin_database


def test_admin_assigns_product_manager_and_sessions_use_current_server_role(
    client: TestClient,
) -> None:
    owner = _owner_headers(client)
    _create_user(client, owner, username="tenant-admin", role="admin")
    user = _create_user(client, owner, username="product-person", role="engineer")
    old = _login_headers(client, username="product-person", password="temporary passphrase 2026")
    admin = _login_headers(client, username="tenant-admin", password="temporary passphrase 2026")
    changed = client.patch(
        f"/api/admin/users/{user['id']}", headers=admin, json={"role": "product_manager"}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "product_manager"
    old_me = client.get("/api/auth/me", headers=old)
    assert old_me.status_code == 200 and old_me.json()["user"]["role"] == "product_manager"
    current = _login_headers(
        client, username="product-person", password="temporary passphrase 2026"
    )
    me = client.get("/api/auth/me", headers=current)
    assert me.status_code == 200 and me.json()["user"]["role"] == "product_manager"
    assert client.get("/api/admin/users", headers=current).status_code == 403
    assigned = _create_user(
        client, admin, username="another-product-person", role="product_manager"
    )
    assert assigned["role"] == "product_manager"
    demoted = client.patch(
        f"/api/admin/users/{user['id']}", headers=admin, json={"role": "engineer"}
    )
    assert demoted.status_code == 200
    response = client.post(
        "/api/product-work/spaces",
        headers=current,
        json={
            "request_id": str(uuid4()),
            "code": "DENIED",
            "title": "降权后的旧会话",
            "user_groups": ["合成用户"],
            "regions": ["TEST"],
            "use_scenarios": ["合成场景"],
            "research_questions": ["权限核对"],
        },
    )
    assert response.status_code == 403


def test_product_manager_manages_own_space_and_cannot_manage_projects_or_other_spaces(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner = _owner_headers(client)
    account = _create_user(client, owner, username="product-person", role="product_manager")
    pm = _login_headers(client, username="product-person", password="temporary passphrase 2026")
    sid = space(client, pm)
    owner_space = space(client, owner)
    listing = client.get("/api/product-work/spaces", headers=pm)
    assert listing.status_code == 200 and listing.json()["can_create"]
    assert [row["id"] for row in listing.json()["items"]] == [sid]
    detail = client.get(f"/api/product-work/spaces/{sid}", headers=pm)
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_manage"] and detail.json()["can_manage_sources"]
    assert account["id"] in {row["id"] for row in detail.json()["available_members"]}
    assert client.get(f"/api/product-work/spaces/{owner_space}", headers=pm).status_code == 403
    assert (
        client.post(
            "/api/projects",
            headers=pm,
            json={"development_case_id": str(uuid4()), "code": "PM-DENIED", "name": "权限反例"},
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/api/projects/{uuid4()}", headers=pm, json={"name": "权限反例"}).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/development-cases/{uuid4()}/transitions",
            headers=pm,
            json={"to_status": "approved"},
        ).status_code
        == 403
    )
    conversation = client.post(
        "/api/conversations",
        headers=pm,
        json={"request_id": str(uuid4()), "scope_kind": "market_space", "market_space_id": sid},
    )
    assert conversation.status_code == 200, conversation.text
    successor = _create_user(client, owner, username="product-successor", role="product_manager")
    added = client.put(
        f"/api/product-work/spaces/{sid}/members/{successor['id']}",
        headers=pm,
        json={"access": "manager"},
    )
    assert added.status_code == 204, added.text
    responsibility_path = f"/api/product-work/spaces/{sid}/responsibilities/space/{sid}"
    current = client.get(responsibility_path, headers=pm)
    assert current.status_code == 200, current.text
    assert successor["id"] in {row["id"] for row in current.json()["members"]}
    transferred = client.post(
        responsibility_path,
        headers=pm,
        json={
            "request_id": str(uuid4()),
            "expected_digest": current.json()["digest"],
            "role": "owner",
            "user_id": successor["id"],
            "reason": "合成产品职责交接",
        },
    )
    assert transferred.status_code == 200, transferred.text
    latest = client.get(f"/api/product-work/spaces/{sid}", headers=pm)
    assert latest.json()["space"]["owner_user_id"] == successor["id"]
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with engine.connect() as c:
            assert c.execute(select(tables.projects.c.id)).all() == []
    finally:
        engine.dispose()


def test_product_manager_is_a_named_product_signer_without_project_approval_power(
    client: TestClient,
    isolated_user_admin_database: str,
) -> None:
    owner = _owner_headers(client)
    identity = client.get("/api/auth/me", headers=owner).json()
    project, _, _, gate, _ = seed_project(
        isolated_user_admin_database,
        tenant_id=UUID(identity["tenant"]["id"]),
        owner_id=UUID(identity["user"]["id"]),
    )
    account = _create_user(client, owner, username="product-person", role="product_manager")
    pm = _login_headers(client, username="product-person", password="temporary passphrase 2026")
    roster = client.post(
        f"/api/projects/{project}/members",
        headers=owner,
        json={"request_id": str(uuid4()), "user_id": account["id"]},
    )
    assert roster.status_code == 201, roster.text
    assert (
        client.post(
            f"/api/projects/{project}/members",
            headers=pm,
            json={"request_id": str(uuid4()), "user_id": identity["user"]["id"]},
        ).status_code
        == 403
    )
    base = f"/api/projects/{project}/gates/{gate}"
    options = client.get(base + "/assignment-options", headers=owner)
    assert options.status_code == 200, options.text
    selected = next(
        person for person in options.json()["members"] if person["user_id"] == account["id"]
    )
    assert selected["slots"] == ["product"]
    opened = client.post(
        base + "/rounds",
        headers=owner,
        json={
            "request_id": str(uuid4()),
            "expected_basis": options.json()["signing_basis"],
            "signers": {"product": account["id"]},
            "reason": "合成产品经理独立评审",
        },
    )
    assert opened.status_code == 201, opened.text
    round_id = opened.json()["round"]["id"]
    signed = client.put(
        base + f"/rounds/{round_id}/signoffs/product",
        headers=pm,
        json={"status": "approved", "note": "合成产品评审，未授予项目批准权"},
    )
    assert signed.status_code == 200, signed.text
    signoff = next(row for row in signed.json()["round"]["signoffs"] if row["slot"] == "product")
    assert signoff["signer_role"] == "product_manager"
    assert signoff["signed_by_user_id"] == account["id"]
    assert (
        client.put(
            base + f"/rounds/{round_id}/signoffs/engineering",
            headers=pm,
            json={"status": "approved", "note": "越专业签署应拒绝"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            base + "/decisions",
            headers=pm,
            json={"status": "approved", "rationale": "产品评审不能代替项目批准"},
        ).status_code
        == 403
    )

    migration = import_module("migrations.versions.0417_product_manager_role")
    engine = create_engine(psycopg_database_url(isolated_user_admin_database))
    try:
        with rollback_migration_operations(engine) as c:
            c.execute(
                tables.users.update()
                .where(tables.users.c.id == UUID(str(account["id"])))
                .values(role="engineer")
            )
            with pytest.raises(RuntimeError, match="accounts or signatures remain"):
                migration.downgrade()
            assert (
                c.execute(
                    select(tables.gate_signoffs.c.signer_role).where(
                        tables.gate_signoffs.c.round_id == UUID(round_id),
                        tables.gate_signoffs.c.slot == "product",
                    )
                ).scalar_one()
                == "product_manager"
            )
    finally:
        engine.dispose()
