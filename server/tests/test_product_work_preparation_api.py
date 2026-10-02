"""Product-work source isolation and replay; synthetic data, no model qualification."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.product_work_preparation import SOURCE_FIELDS, source_table
from app.db.schema import tables
from app.domain.evidence import EvidenceService
from tests.test_test_runs_api import (
    Scope,
    bearer_headers,
    client,  # noqa: F401
    isolated_test_run_database,  # noqa: F401
)


def space(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/product-work/spaces",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "code": str(uuid4()),
            "title": "合成充气设备研究",
            "user_groups": ["骑行用户"],
            "regions": ["测试市场"],
            "use_scenarios": ["现场补气"],
            "research_questions": ["需要哪些验证？"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]  # type: ignore[no-any-return]


def test_source_pack_scope_changes_and_original_evidence(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid, other = space(client, headers), space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        research = client.post(
            base + "/research",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "owner_user_id": str(scope.owner_id),
                "question": "合成研究：验证需求",
                "user_groups": ["骑行者"],
                "regions": ["测试市场"],
                "time_scope": "本周",
                "method": "核对来源",
                "expected_decision": "决定实验方向",
                "stop_conditions": ["得到验证清单"],
            },
        )
        assert research.status_code == 201, research.text
        rid = research.json()["id"]
        for kind in SOURCE_FIELDS:
            options = client.post(
                base + "/product-ai-options", headers=headers, json={"kind": kind}
            )
            assert options.status_code == 200, options.text
            assert not options.json()["generation_available"]
        selection: dict[str, Any] = {
            "capability": "research_planning",
            "question": "规划下一步研究",
            "sources": [{"kind": "research", "id": rid}],
        }
        first = client.post(base + "/product-ai-context", headers=headers, json=selection)
        assert first.status_code == 200, first.text
        assert first.headers["cache-control"] == "no-store"
        assert first.json()["warnings"] and "原正文" not in str(first.json()["references"])
        assert (
            client.post(base + "/product-ai-context", headers=headers, json=selection).json()[
                "digest"
            ]
            == first.json()["digest"]
        )
        wrong = client.post(
            f"/api/product-work/spaces/{other}/product-ai-context", headers=headers, json=selection
        )
        assert wrong.status_code == 403, wrong.text
        assert rid not in wrong.text
        assert (
            client.post(
                base + "/product-ai-context",
                headers=headers,
                json={**selection, "sources": selection["sources"] * 2},
            ).status_code
            == 422
        )
        assert (
            client.post(
                base + "/product-ai-context",
                headers=headers,
                json={**selection, "capability": "product_strategy"},
            ).status_code
            == 422
        )
        service = EvidenceService(scope.engine)
        source = service.create_source(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            name="合成来源",
            source_type="file",
            allowed_use="internal_analysis",
            collection_frequency="on_demand",
            retention_policy="standard",
            trust_tier="unknown",
        )
        snapshot = service.capture(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            source_id=source.id,
            content="合成原正文：噪音数值尚未实测。",
            freshness_expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        # A concluded research record carries an original citation, not a copied provider answer.
        with scope.engine.begin() as c:
            c.execute(
                tables.research_tasks.update()
                .where(tables.research_tasks.c.id == UUID(rid))
                .values(
                    sources=[
                        {
                            "tenant_id": str(scope.tenant_id),
                            "kind": "evidence_snapshot",
                            "ref_id": str(snapshot.id),
                            "as_of": snapshot.captured_at.isoformat(),
                            "digest": snapshot.content_digest,
                        }
                    ],
                    version=2,
                )
            )
        second = client.post(base + "/product-ai-context", headers=headers, json=selection)
        assert second.status_code == 200, second.text
        assert second.json()["digest"] != first.json()["digest"]
        assert "合成原正文" in str(second.json()["references"])
        assert "复查" in str(second.json()["warnings"])
        with scope.engine.begin() as c:
            c.execute(
                tables.research_sources.update()
                .where(tables.research_sources.c.id == source.id)
                .values(status="disabled")
            )
        denied = client.post(base + "/product-ai-context", headers=headers, json=selection)
        assert denied.status_code == 409, denied.text
        assert "合成原正文" not in denied.text
        # A later business edit must not authorize the original withdrawn evidence in history.
        from app.ai.product_work_context import readable
        from app.ai.project_discussion_sources import actor
        from app.domain.product_workspace import ProductWorkError

        with scope.engine.begin() as c:
            c.execute(
                tables.research_tasks.update()
                .where(tables.research_tasks.c.id == UUID(rid))
                .values(sources=[], version=3)
            )
        assert (
            client.post(base + "/product-ai-context", headers=headers, json=selection).status_code
            == 200
        )
        with scope.engine.connect() as c, pytest.raises(ProductWorkError):
            readable(c, actor(c, scope.tenant_id, scope.owner_id), second.json())
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()


def test_product_line_binding_and_bounded_original_content(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        line = client.post(
            base + "/products",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "code": "TEST-LINE",
                "name": "合成产品线",
                "level": "line",
                "owner_user_id": str(scope.owner_id),
            },
        )
        assert line.status_code == 201, line.text
        lid = line.json()["id"]
        for capability in (
            "research_planning",
            "competitor_analysis",
            "market_analysis",
            "opportunity_mapping",
            "experiment_design",
            "product_strategy",
            "product_definition",
        ):
            response = client.post(
                base + "/product-ai-context",
                headers=headers,
                json={
                    "capability": capability,
                    "product_line_id": lid,
                    "question": "合成问题",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["warnings"]
        bad = client.post(
            base + "/product-ai-options", headers=headers, json={"product_line_id": str(uuid4())}
        )
        assert bad.status_code == 403, bad.text
        service = EvidenceService(scope.engine)
        source = service.create_source(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            name="大原文",
            source_type="file",
            allowed_use="internal_analysis",
            collection_frequency="on_demand",
            retention_policy="standard",
            trust_tier="unknown",
        )
        snapshot = service.capture(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            source_id=source.id,
            content="合成" * 25_000,
        )
        large = client.post(
            base + "/product-ai-context",
            headers=headers,
            json={
                "capability": "research_planning",
                "question": "不能静默截断",
                "sources": [{"kind": "evidence", "id": str(snapshot.id)}],
            },
        )
        assert large.status_code == 409, large.text
        assert "上限" in large.text
    finally:
        scope.dispose()


def test_projection_columns_are_real_business_fields() -> None:
    # Every named projection must read the actual stored field, including prices/results/content.
    for kind, (_, label, fields) in SOURCE_FIELDS.items():
        columns = source_table(kind).c
        assert label in columns
        assert all(field in columns for field in fields.split())


def test_membership_and_product_line_revocation_hide_sources(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        line = client.post(
            base + "/products",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "code": "PRIVATE-LINE",
                "name": "受限产品线",
                "level": "line",
                "owner_user_id": str(scope.owner_id),
            },
        )
        assert line.status_code == 201, line.text
        member = uuid4()
        with scope.engine.begin() as c:
            password_hash = c.execute(
                select(tables.users.c.password_hash).where(
                    tables.users.c.id == scope.owner_id,
                )
            ).scalar_one()
            c.execute(
                tables.users.insert().values(
                    id=member,
                    tenant_id=scope.tenant_id,
                    username="pm-reader",
                    display_name="合成协作者",
                    role="engineer",
                    password_hash=password_hash,
                    is_active=True,
                )
            )
            c.execute(
                tables.market_space_members.insert().values(
                    tenant_id=scope.tenant_id,
                    market_space_id=UUID(sid),
                    user_id=member,
                    access="contributor",
                    added_by_user_id=scope.owner_id,
                )
            )
        from tests.test_test_runs_api import PASSWORD

        login = client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "pm-reader",
                "password": PASSWORD,
            },
        )
        assert login.status_code == 200, login.text
        own_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        common = {"capability": "research_planning", "question": "共同研究"}
        assert (
            client.post(base + "/product-ai-context", headers=own_headers, json=common).status_code
            == 200
        )
        denied = client.post(
            base + "/product-ai-options",
            headers=own_headers,
            json={"product_line_id": line.json()["id"]},
        )
        assert denied.status_code == 403, denied.text
        assert "受限产品线" not in denied.text
        with scope.engine.begin() as c:
            c.execute(
                tables.market_space_members.delete().where(
                    tables.market_space_members.c.market_space_id == UUID(sid),
                    tables.market_space_members.c.user_id == member,
                )
            )
        denied = client.post(base + "/product-ai-context", headers=own_headers, json=common)
        assert denied.status_code == 403, denied.text
        assert "合成充气设备研究" not in denied.text
    finally:
        scope.dispose()
