"""Exercise database scope without domain-service filtering or synthetic success."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.models import Artifact, Category, Grant, ObjectAudience, Product, now
from pdos_next.service import digest


def scoped(setup, actor=None, *, category=None, tenant=None):
    return tenant_session(
        setup.engine,
        tenant or setup.tenant,
        actor_id=actor or setup.human,
        requester_id=actor or setup.human,
        category_id=category,
    )


def test_direct_sql_category_tenant_and_audience_filters(setup):
    second, hidden, private, reviewed = (uuid4() for _ in range(4))
    with Session(setup.admin) as s, s.begin():
        s.add(
            Category(
                id=second,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                name="自行车充气泵",
                purpose="独立品类",
            )
        )
        s.flush()
        s.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=second,
                principal_id=setup.human,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
        s.add(
            Product(
                id=hidden,
                tenant_id=setup.tenant,
                category_id=second,
                owner_id=setup.human,
                name="第二品类型号",
                purpose="隔离",
            )
        )
        s.add_all(
            [
                Product(
                    id=private,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    owner_id=setup.human,
                    name="私有型号",
                    purpose="私有",
                    visibility="private",
                ),
                Product(
                    id=reviewed,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    owner_id=setup.human,
                    name="具名评审型号",
                    purpose="受众",
                    visibility="audience",
                ),
            ]
        )
        s.flush()
        s.add(
            Artifact(
                tenant_id=setup.tenant,
                product_id=private,
                owner_id=setup.human,
                title="型号内资料",
                source_label="合成",
                content="私有型号内资料",
                content_hash=digest("私有型号内资料"),
                visibility="category",
            )
        )
        s.add(
            ObjectAudience(
                tenant_id=setup.tenant,
                category_id=setup.category,
                object_type="products",
                subject_id=reviewed,
                owner_id=setup.human,
                principal_id=setup.peer,
            )
        )
    with scoped(setup, setup.peer) as s:
        ids = set(s.scalars(text("SELECT id FROM products")))
        assert ids == {setup.product, reviewed}
        assert hidden not in ids and private not in ids
        assert not list(s.scalars(text("SELECT id FROM artifact_versions")))
    with scoped(setup, category=setup.category) as s:
        assert hidden not in set(s.scalars(text("SELECT id FROM products")))
    with scoped(setup, setup.other_human, tenant=setup.other_tenant) as s:
        assert not list(s.scalars(text("SELECT id FROM products")))


def test_missing_actor_and_pool_scope_reset_deny_rows(setup):
    with tenant_session(setup.engine, setup.tenant) as s:
        assert not list(s.scalars(select(Product.id)))
    with scoped(setup, category=setup.category) as s:
        assert s.get(Product, setup.product)
    with Session(setup.engine) as s:
        assert not list(s.scalars(text("SELECT id FROM products")))


def test_forged_category_model_binding_rejected_by_database(setup):
    other = uuid4()
    with Session(setup.admin) as s, s.begin():
        s.add(
            Category(
                id=other,
                tenant_id=setup.tenant,
                owner_id=setup.human,
                name="其他品类",
                purpose="边界验证",
            )
        )
        s.flush()
        s.add(
            Grant(
                tenant_id=setup.tenant,
                category_id=other,
                principal_id=setup.human,
                can_write=True,
                expires_at=now() + timedelta(hours=1),
            )
        )
    with pytest.raises(DBAPIError), scoped(setup) as s:
        s.add(
            Artifact(
                tenant_id=setup.tenant,
                category_id=other,
                product_id=setup.product,
                owner_id=setup.human,
                title="伪造范围",
                source_label="合成",
                content="合成正文",
                content_hash=digest("合成正文"),
                visibility="private",
            )
        )
        s.flush()


def test_membership_revocation_removes_owner_access(setup):
    with Session(setup.admin) as s, s.begin():
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == setup.category, Grant.principal_id == setup.human
            )
        )
        grant.expires_at = now() - timedelta(seconds=1)
    with scoped(setup) as s:
        assert s.get(Category, setup.category) is None
        assert s.get(Product, setup.product) is None


def test_agent_database_role_has_no_business_dml(setup):
    with Session(setup.admin) as s:
        rows = s.execute(
            text("""SELECT tablename,
          has_table_privilege('pdos_agent',quote_ident(tablename),'INSERT,UPDATE,DELETE')
          FROM pg_tables WHERE schemaname='public'
          AND tablename NOT IN ('environment_guard','alembic_version')""")
        ).all()
        assert rows and not any(allowed for _, allowed in rows)


def test_category_create_is_confirmed_atomic_and_replayable(setup):
    payload = {
        "key": "category-" + uuid4().hex,
        "name": "汽车配件",
        "purpose": "合成品类创建验证",
        "idempotency_key": str(uuid4()),
        "deidentified_confirmed": True,
    }
    preview = setup.client.post("/v1/categories/preview", headers=setup.headers, json=payload)
    assert preview.status_code == 200, preview.text
    payload["confirmation_token"] = preview.json()["confirmation_token"]
    first = setup.client.post("/v1/categories", headers=setup.headers, json=payload)
    assert first.status_code == 201, first.text
    repeated = setup.client.post("/v1/categories", headers=setup.headers, json=payload)
    assert repeated.status_code == 201 and repeated.json()["id"] == first.json()["id"]
    listed = setup.client.get("/v1/categories", headers=setup.headers).json()
    assert first.json()["subject_id"] in {c["id"] for c in listed}
    with Session(setup.admin) as s:
        grant = s.scalar(
            select(Grant).where(
                Grant.category_id == first.json()["subject_id"],
                Grant.principal_id == setup.human,
            )
        )
        assert grant.expires_at is None and grant.product_manager is False
    denied = setup.client.post(
        "/v1/categories",
        headers=setup.headers,
        json={**payload, "idempotency_key": str(uuid4()), "deidentified_confirmed": False},
    )
    assert denied.status_code == 409


def test_category_path_body_and_product_must_agree(setup):
    payload = {
        "command_id": str(uuid4()),
        "idempotency_key": str(uuid4()),
        "category_id": str(uuid4()),
        "product_id": str(setup.product),
        "operation": "evidence.artifact.register",
        "expected_revision": 1,
        "payload": {
            "title": "合成资料",
            "source_label": "合成",
            "content": "合成内容",
            "visibility": "private",
        },
    }
    response = setup.client.post(
        f"/v1/categories/{setup.category}/commands", headers=setup.headers, json=payload
    )
    assert response.status_code == 403, response.text
    assert setup.client.get("/v1/products", headers=setup.headers).status_code == 404


def test_membership_requires_named_owner_and_records_t2_receipt(setup):
    payload = {
        "principal_id": str(setup.agent),
        "can_write": False,
        "expires_at": (now() + timedelta(hours=2)).isoformat(),
        "expected_revision": 1,
        "idempotency_key": str(uuid4()),
        "decision": "批准",
    }
    path = f"/v1/categories/{setup.category}/members"
    peer = {"Authorization": f"Bearer {setup.tokens[setup.peer]}"}
    assert setup.client.post(path, headers=peer, json=payload).status_code == 403
    response = setup.client.post(path, headers=setup.headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["tier"] == "T2"
    assert response.json()["result"]["decided_by"] == str(setup.human)
    assert (
        setup.client.post(path, headers=setup.headers, json=payload).json()["id"]
        == response.json()["id"]
    )


def test_unbounded_member_and_product_manager_capability_are_explicit_t2(setup):
    payload = {
        "principal_id": str(setup.peer),
        "can_write": True,
        "product_manager": True,
        "expected_revision": 1,
        "idempotency_key": str(uuid4()),
        "decision": "批准",
    }
    response = setup.client.post(
        f"/v1/categories/{setup.category}/members", headers=setup.headers, json=payload
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["expires_at"] is None and result["product_manager"] is True
    with scoped(setup, setup.peer, category=setup.category) as s:
        assert s.get(Product, setup.product) is not None
        grant = s.scalar(select(Grant).where(Grant.principal_id == setup.peer))
        assert grant.expires_at is None and grant.product_manager
    assert response.json()["result"]["decided_by"] == str(setup.human)
    assert (
        setup.client.post(
            f"/v1/categories/{setup.category}/members", headers=setup.headers, json=payload
        ).json()["id"]
        == response.json()["id"]
    )
