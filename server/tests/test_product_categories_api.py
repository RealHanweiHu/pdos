"""Shared-category references, private promotion and cross-category platform transactions."""

# ruff: noqa: F811
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from tests.test_product_proposals_api import command
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def line(client, headers, sid, owner, name="汽车充气泵"):
    base = f"/api/product-work/spaces/{sid}"
    current = client.get(base, headers=headers).json()["space"]
    r = client.post(
        base + "/changes",
        headers=headers,
        json={
            **command(current),
            "title": name,
            "user_groups": current["user_groups"],
            "regions": ["EU"],
            "use_scenarios": current["use_scenarios"],
            "research_questions": current["research_questions"],
            "reason": "合成品类命名",
        },
    )
    assert r.status_code == 200, r.text
    rows = client.get(base + "/products", headers=headers).json()["nodes"]
    category = next(r for r in rows if r["level"] == "line")
    assert category["id"] == sid and category["name"] == name
    return category


def parameter(client, headers, base):
    body = dict(
        request_id=str(uuid4()),
        key="noise",
        label="工作噪声",
        unit="dB(A)",
        conditions="23°C；额定负载；距离1m",
        direction="lower",
        verification_method="声级计实测",
        acceptance_criterion="按型号目标上限",
        reason="统一品类对标口径",
    )
    r = client.post(base + "/parameters", headers=headers, json=body)
    assert r.status_code == 201, r.text
    assert (
        client.post(base + "/parameters", headers=headers, json=body).json()["id"] == r.json()["id"]
    )
    return r.json(), body


def test_shared_dictionary_skeleton_tests_cross_category_and_revision(
    client, isolated_test_run_database
):
    scope = Scope(client, isolated_test_run_database)
    h = bearer_headers(client)
    sid = space(client, h)
    base = f"/api/product-work/spaces/{sid}"
    car = line(client, h, sid, scope.owner_id)
    bike_sid = space(client, h)
    bike = line(client, h, bike_sid, scope.owner_id, "自行车充气泵")
    cat = base + f"/categories/{car['id']}"
    p, pb = parameter(client, h, cat)
    for region, body in [("EU", "欧盟适用法规待专业确认"), ("US", "美国适用法规待专业确认")]:
        r = client.post(
            cat + "/knowledge",
            headers=h,
            json=dict(
                request_id=str(uuid4()),
                kind="regulation",
                title=region,
                body=body,
                regions=[region],
                confirmed_anonymized=True,
            ),
        )
        assert r.status_code == 201, r.text
    r = client.post(
        base + "/proposals",
        headers=h,
        json=dict(
            request_id=str(uuid4()),
            title="汽车新品",
            entry_kind="new_product",
            brief="日常轿车补气",
            product_line_id=car["id"],
            target_regions=["EU"],
        ),
    )
    assert r.status_code == 201, r.text
    proposal = r.json()
    spec = proposal["document"]["specifications"][0]
    assert (
        spec["parameter_id"] == p["parameter_id"]
        and spec["unit"] == p["unit"]
        and spec["state"] == "unknown"
    )
    bundle = client.get(cat, headers=h).json()
    assert bundle["test_template"]["items"][0]["parameter_id"] == spec["parameter_id"]
    assert [k["title"] for k in proposal["category_context"]["knowledge"]] == ["EU"]
    assert (
        client.get(
            f"/api/product-work/spaces/{bike_sid}/categories/{bike['id']}", headers=h
        ).json()["parameters"]
        == []
    )
    document = deepcopy(proposal["document"])
    document["specifications"][0]["unit"] = "psi"
    assert (
        client.post(
            base + f"/proposals/{proposal['id']}/changes",
            headers=h,
            json={**command(proposal), "document": document},
        ).status_code
        == 409
    )
    with pytest.raises(DBAPIError), scope.engine.begin() as c:
        c.execute(
            tables.product_proposals.update()
            .where(tables.product_proposals.c.id == proposal["id"])
            .values(document=document, version=2)
        )
    good = deepcopy(proposal["document"])
    good["specifications"][0].update(value="75", state="ai_draft", source_ids=["brief"])
    saved = client.post(
        base + f"/proposals/{proposal['id']}/changes",
        headers=h,
        json={**command(proposal), "document": good},
    )
    assert saved.status_code == 200, saved.text
    assert not client.get(base + f"/proposals/{proposal['id']}", headers=h).json()[
        "sources_changed"
    ]
    revised = client.post(
        cat + "/parameters",
        headers=h,
        json={
            **pb,
            "request_id": str(uuid4()),
            "parameter_id": p["parameter_id"],
            "expected_version": 1,
            "conditions": "25°C；额定负载；距离1m",
        },
    )
    assert revised.status_code == 201, revised.text
    detail = client.get(base + f"/proposals/{proposal['id']}", headers=h).json()
    assert (
        detail["sources_changed"]
        and detail["document"]["specifications"][0]["parameter_version"] == 1
    )
    missing = client.post(
        base + "/proposals",
        headers=h,
        json=dict(
            request_id=str(uuid4()), title="无品类", entry_kind="new_product", brief="无品类"
        ),
    )
    assert missing.status_code == 201
    assert missing.json()["product_line_id"] == car["id"]


def test_customer_material_requires_explicit_anonymized_promotion(
    client, isolated_test_run_database
):
    scope = Scope(client, isolated_test_run_database)
    h = bearer_headers(client)
    sid = space(client, h)
    base = f"/api/product-work/spaces/{sid}"
    car = line(client, h, sid, scope.owner_id)
    cat = base + f"/categories/{car['id']}"
    r = client.post(
        base + "/proposals",
        headers=h,
        json=dict(
            request_id=str(uuid4()),
            title="客户X RFQ",
            entry_kind="odm",
            brief="客户X独家要求不得公开",
            product_line_id=car["id"],
        ),
    )
    assert r.status_code == 201, r.text
    proposal = r.json()
    assert client.get(cat, headers=h).json()["knowledge"] == []
    body = dict(
        request_id=str(uuid4()),
        kind="general_requirement",
        title="欧美客户噪声倾向",
        body="多个欧美客户要求≤75 dB(A)",
        proposal_id=proposal["id"],
        expected_proposal_version=1,
    )
    assert client.post(cat + "/knowledge", headers=h, json=body).status_code == 409
    published = client.post(
        cat + "/knowledge", headers=h, json={**body, "confirmed_anonymized": True}
    )
    assert published.status_code == 201, published.text
    bundle = client.get(cat, headers=h).json()
    assert "客户X" not in str(bundle) and "proposal_id" not in str(bundle)
    assert bundle["knowledge"][0]["source_refs"] == []
    with scope.engine.connect() as c:
        assert c.execute(
            select(tables.category_promotion_proofs.c.proposal_id)
        ).scalar_one() == UUID(proposal["id"])
    with pytest.raises(DBAPIError), scope.engine.begin() as c:
        c.execute(tables.category_knowledge.update().values(body="覆盖历史"))


def test_platform_is_independent_many_to_many_and_series_optional(
    client, isolated_test_run_database
):
    scope = Scope(client, isolated_test_run_database)
    h = bearer_headers(client)
    sid = space(client, h)
    base = f"/api/product-work/spaces/{sid}"
    car = line(client, h, sid, scope.owner_id)
    bike_sid = space(client, h)
    bike = line(client, h, bike_sid, scope.owner_id, "自行车充气泵")
    models = []
    for category in [car, bike]:
        r = client.post(
            f"/api/product-work/spaces/{category['market_space_id']}/products",
            headers=h,
            json=dict(
                request_id=str(uuid4()),
                code=f"m-{uuid4().hex}",
                name="测试型号",
                level="model",
                parent_id=category["id"],
                owner_user_id=str(scope.owner_id),
                tags=["Pro系列"],
            ),
        )
        assert r.status_code == 201, r.text
        models.append(r.json())
    for category in [car, bike]:
        bundle = client.get(
            f"/api/product-work/spaces/{category['market_space_id']}/categories/{category['id']}",
            headers=h,
        ).json()
        assert bundle["category_name"] == category["name"]
    p = client.post(
        base + "/platforms",
        headers=h,
        json=dict(
            request_id=str(uuid4()),
            code="battery-P2",
            name="P2电池包",
            description="跨品类复用电池包",
        ),
    )
    assert p.status_code == 201, p.text
    for model in models:
        r = client.post(
            f"/api/product-work/spaces/{model['market_space_id']}/platform-links",
            headers=h,
            json=dict(
                request_id=str(uuid4()),
                product_id=model["id"],
                platform_id=p.json()["id"],
                action="attach",
                reason="可复用",
                expected_version=0,
            ),
        )
        assert r.status_code == 201, r.text
    result = client.get(base + "/platforms", headers=h).json()
    other = client.get(f"/api/product-work/spaces/{bike_sid}/platforms", headers=h).json()
    assert len(result["items"]) == 1 and len(result["links"]) == 1
    assert other["items"][0]["id"] == result["items"][0]["id"]
    assert {r["product_line_id"] for r in result["links"] + other["links"]} == {
        car["id"],
        bike["id"],
    }
    old = client.post(
        base + "/products",
        headers=h,
        json=dict(
            request_id=str(uuid4()),
            code="old-platform",
            name="旧层级",
            level="platform",
            parent_id=car["id"],
            owner_user_id=str(scope.owner_id),
        ),
    )
    assert old.status_code == 409


def test_category_is_single_identity_and_permission_source(client, isolated_test_run_database):
    from sqlalchemy import update

    from tests.test_test_runs_api import PASSWORD

    scope = Scope(client, isolated_test_run_database)
    h = bearer_headers(client)
    sid = space(client, h)
    base = f"/api/product-work/spaces/{sid}"
    category = client.get(f"/api/product-work/categories/{sid}", headers=h).json()["space"]
    assert category["id"] == category["category_id"] == category["category_line_id"] == sid
    shared = client.get(f"/api/product-work/categories/{sid}/shared", headers=h)
    assert shared.status_code == 200 and shared.json()["category_id"] == sid
    assert shared.json()["use_scenarios"] == category["use_scenarios"]
    node = client.get(base + "/products", headers=h).json()["nodes"][0]
    assert node["id"] == sid and node["regions"] == category["regions"]
    assert (
        client.post(
            base + "/products",
            headers=h,
            json={
                "request_id": str(uuid4()),
                "code": "SECOND-LINE",
                "name": "不允许嵌套的品类",
                "level": "line",
                "owner_user_id": str(scope.owner_id),
            },
        ).status_code
        == 409
    )
    colleague = uuid4()
    with scope.engine.begin() as c:
        password = c.execute(
            select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
        ).scalar_one()
        c.execute(
            tables.users.insert().values(
                id=colleague,
                tenant_id=scope.tenant_id,
                username="category-colleague",
                display_name="合成品类成员",
                role="product_manager",
                password_hash=password,
                is_active=True,
            )
        )
    login = client.post(
        "/api/auth/login",
        json={"tenant_slug": "beepump", "username": "category-colleague", "password": PASSWORD},
    )
    assert login.status_code == 200
    other = {"Authorization": "Bearer " + login.json()["access_token"]}
    for access in ("manager", "viewer", None):
        response = client.put(base + f"/members/{colleague}", headers=h, json={"access": access})
        assert response.status_code == 204, response.text
        with scope.engine.connect() as c:
            projection = c.execute(
                select(tables.product_line_members.c.access).where(
                    tables.product_line_members.c.tenant_id == scope.tenant_id,
                    tables.product_line_members.c.product_line_id == UUID(sid),
                    tables.product_line_members.c.user_id == colleague,
                )
            ).scalar_one_or_none()
        assert projection == access
        response = client.get(f"/api/product-work/categories/{sid}/shared", headers=other)
        assert response.status_code == (403 if access is None else 200)
        if access == "viewer":
            assert client.get(base, headers=other).json()["can_contribute"] is False
    with pytest.raises(DBAPIError), scope.engine.begin() as c:
        c.execute(
            update(tables.product_nodes)
            .where(tables.product_nodes.c.id == UUID(sid))
            .values(name="独立修改旧产品线")
        )
    with pytest.raises(DBAPIError), scope.engine.begin() as c:
        c.execute(
            update(tables.product_line_members)
            .where(tables.product_line_members.c.product_line_id == UUID(sid))
            .values(access="viewer")
        )
    assert client.get(base + "/products", headers=h).json()["nodes"][0]["name"] == category["title"]
    from importlib import import_module

    from tests.migration_fixtures import rollback_migration_operations

    with pytest.raises(RuntimeError, match="retained"), rollback_migration_operations(scope.engine):
        import_module("migrations.versions.0426_unified_categories").downgrade()
    assert client.get(base, headers=h).json()["space"]["id"] == sid
    scope.dispose()


def test_unbound_legacy_competitor_reuses_own_dictionary_without_rewriting_history(
    client, isolated_test_run_database
):
    from datetime import UTC, datetime, timedelta
    from importlib import import_module

    from app.domain.evidence import EvidenceService
    from tests.migration_fixtures import rollback_migration_operations

    scope = Scope(client, isolated_test_run_database)
    h = bearer_headers(client)
    sid = space(client, h)
    base = f"/api/product-work/spaces/{sid}"
    p, _ = parameter(client, h, f"/api/product-work/categories/{sid}/shared")
    evidence = EvidenceService(scope.engine)
    source = evidence.create_source(
        tenant_id=scope.tenant_id,
        actor_user_id=scope.owner_id,
        name="合成旧竞品资料",
        source_type="file",
        allowed_use="internal_analysis",
        collection_frequency="on_demand",
        retention_policy="standard",
        trust_tier="unknown",
    )
    snapshot = evidence.capture(
        tenant_id=scope.tenant_id,
        actor_user_id=scope.owner_id,
        source_id=source.id,
        content="合成旧竞品噪声声明：65dB(A)，仅为引用验证。",
        freshness_expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    ref = dict(
        tenant_id=str(scope.tenant_id),
        kind="evidence_snapshot",
        ref_id=str(snapshot.id),
        as_of=snapshot.captured_at.isoformat(),
        digest=snapshot.content_digest,
    )
    metric = dict(
        key=p["key"],
        label=p["label"],
        number="65",
        unit=p["unit"],
        conditions=p["conditions"],
        nature="claimed",
        source_refs=[ref],
    )
    body = dict(
        product_line_id=None,
        brand="合成",
        model="旧竞品",
        variant="基本型",
        competitor_kind="direct",
        region="EU",
        channel="online",
        configuration="合成配置",
        lifecycle="available",
        observed_on=datetime.now(UTC).date().isoformat(),
        identity_sources=[ref],
        metrics=[metric],
        revision_reason="保存旧记录",
    )
    first = client.post(base + "/competitors", headers=h, json={**body, "request_id": str(uuid4())})
    assert first.status_code == 201, first.text
    old = first.json()
    metric.update(parameter_id=p["parameter_id"], parameter_version=1)
    revised = client.post(
        base + "/competitors",
        headers=h,
        json={
            **body,
            "metrics": [metric],
            "supersedes_id": old["id"],
            "revision_reason": "具名对齐共用规格字典",
            "request_id": str(uuid4()),
        },
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["product_line_id"] is None
    with scope.engine.connect() as c:
        original = c.execute(
            select(tables.competitor_observations.c.metrics).where(
                tables.competitor_observations.c.id == UUID(old["id"])
            )
        ).scalar_one()
    assert not original[0].get("parameter_id")
    assert (
        client.get(f"/api/product-work/categories/{sid}/shared", headers=h).json()["competitors"][
            0
        ]["metrics"][0]["parameter_id"]
        == p["parameter_id"]
    )
    another = space(client, h)
    other, _ = parameter(client, h, f"/api/product-work/categories/{another}/shared")
    metric.update(parameter_id=other["parameter_id"])
    rejected = client.post(
        base + "/competitors",
        headers=h,
        json={**body, "metrics": [metric], "request_id": str(uuid4())},
    )
    assert rejected.status_code == 409, rejected.text
    with pytest.raises(RuntimeError, match="retained"), rollback_migration_operations(scope.engine):
        import_module("migrations.versions.0427_category_reference_aliases").downgrade()
    scope.dispose()
