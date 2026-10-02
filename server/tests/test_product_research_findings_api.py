"""Synthetic model receipts through the separate human acceptance/application boundary."""

# ruff: noqa: F811
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from tests.test_product_work_preparation_api import space
from tests.test_product_work_runs_api import configure, enable_test_only, output_for, prepared
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

PLAN = dict(
    question="验证补气场景",
    user_groups=["骑行者"],
    regions=["测试市场"],
    time_scope="本周",
    method="访谈并保存原始记录",
    expected_decision="决定是否进入实验",
    stop_conditions=["三个关键问题有证据或记录为未知"],
)


def candidate(
    client: TestClient,
    scope: Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    request: pytest.FixtureRequest,
) -> tuple[str, dict[str, str], dict[str, Any], list[Any]]:
    headers = bearer_headers(client)
    base = f"/api/product-work/spaces/{space(client, headers)}"
    body = prepared(client, base, headers, "research_planning")
    snapshot = client.post(
        base + "/product-ai-context", headers=headers, json=body["selection"]
    ).json()
    ref = snapshot["references"][0]
    output = {
        **output_for("research_planning"),
        "research_plan": PLAN,
        "summary": [
            dict(
                text="据当前研究问题拟定访谈计划，结果尚未知",
                nature="hypothesis",
                citations=[
                    dict(
                        reference_id=ref["reference_id"],
                        digest=ref["digest"],
                        field_path=["title"],
                        quoted_value=ref["fields"]["title"],
                    )
                ],
            )
        ],
    }
    enable_test_only(monkeypatch, "research_planning")
    calls = configure(scope, tmp_path, monkeypatch, output, request=request)
    result = client.post(base + "/product-ai-runs", headers=headers, json=body)
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    read = client.post(
        base + "/research-ai-finding", headers=headers, json={"run_id": result.json()["run_id"]}
    )
    assert read.status_code == 200 and read.json()["finding"], read.text
    return base, headers, read.json()["finding"], calls


def review_body(f: dict[str, Any]) -> dict[str, Any]:
    return dict(
        run_id=f["run_id"],
        finding_id=f["id"],
        expected_digest=f["proposed_digest"],
        decision="accepted",
        comment="已核对，补充访谈范围",
        proposal={**PLAN, "user_groups": ["通勤骑行者"]},
    )


def test_separate_acceptance_atomic_apply_idempotency_and_provenance(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, f, calls = candidate(client, scope, tmp_path, monkeypatch, request=request)
        apply = dict(run_id=f["run_id"], finding_id=f["id"], accepted_digest="0" * 64)
        assert (
            client.post(base + "/research-ai-apply", headers=headers, json=apply).status_code == 409
        )
        body = review_body(f)
        assert (
            client.post(
                base + "/research-ai-review",
                headers=headers,
                json={**body, "proposal": {**body["proposal"], "owner_user_id": str(uuid4())}},
            ).status_code
            == 422
        )
        accept = client.post(base + "/research-ai-review", headers=headers, json=body)
        assert accept.status_code == 200, accept.text
        assert (
            client.post(base + "/research-ai-review", headers=headers, json=body).json()
            == accept.json()
        )
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.research_tasks)).scalar_one() == 0
            )
        # A failure after domain creation rolls back both the new task and Finding receipt.
        from app.domain import product_research_findings as module
        from app.domain.product_workspace import create_research_in_connection

        original = create_research_in_connection

        def interrupted(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise RuntimeError("synthetic transaction interruption")

        apply["accepted_digest"] = accept.json()["finding"]["accepted_digest"]
        with monkeypatch.context() as patch:
            patch.setattr(module, "create_research_in_connection", interrupted)
            with pytest.raises(RuntimeError, match="synthetic transaction"):
                client.post(base + "/research-ai-apply", headers=headers, json=apply)
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.research_tasks)).scalar_one() == 0
            )
            assert c.execute(select(tables.findings.c.status)).scalar_one() == "accepted"
        result = client.post(base + "/research-ai-apply", headers=headers, json=apply)
        assert result.status_code == 200, result.text
        task = result.json()["research_task"]
        assert task["state"] == "draft" and task["source_finding_id"] == f["id"]
        assert task["owner_user_id"] == str(scope.owner_id) and task["user_groups"] == [
            "通勤骑行者"
        ]
        assert (
            client.post(base + "/research-ai-apply", headers=headers, json=apply).json()
            == result.json()
        )
        assert len(calls) == 1
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.research_tasks)).scalar_one() == 1
            )
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(tables.research_tasks.update().values(source_finding_id=None))
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(tables.findings.update().values(accepted_payload={"spoofed": True}))
        from app.auth.repository import AuthRepository

        context = AuthRepository(scope.engine).find_user_context(scope.owner_id)
        assert context is not None
        # Generic project inbox must never expose a private market proposal.
        inbox = client.get("/api/ai/findings", headers=headers)
        assert inbox.status_code == 200, inbox.text
        assert f["id"] not in inbox.text
    finally:
        scope.dispose()


@pytest.mark.parametrize("change", ["source", "archive", "shadow", "quality"])
def test_changed_sources_or_policy_block_application(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, f, _ = candidate(client, scope, tmp_path, monkeypatch, request=request)
        accept = client.post(base + "/research-ai-review", headers=headers, json=review_body(f))
        assert accept.status_code == 200, accept.text
        if change == "shadow":
            from app.ai import capability_contract
            from app.ai.capability_contract import CapabilityKey, CapabilityRollout

            k = CapabilityKey("product_management_intelligence.research_planning")
            monkeypatch.setattr(
                capability_contract,
                "CAPABILITY_CONTRACTS",
                {
                    **capability_contract.CAPABILITY_CONTRACTS,
                    k: capability_contract.CAPABILITY_CONTRACTS[k].model_copy(
                        update={"rollout": CapabilityRollout.SHADOW}
                    ),
                },
            )
        elif change == "quality":
            from app.ai.quality import FindingQualityService

            monkeypatch.setattr(
                FindingQualityService, "is_output_allowed_connection", lambda *a, **k: False
            )
        else:
            with scope.engine.begin() as c:
                c.execute(
                    tables.market_spaces.update().values(
                        **(
                            {"title": "来源变化"}
                            if change == "source"
                            else {"lifecycle": "archived"}
                        ),
                        version=tables.market_spaces.c.version + 1,
                    )
                )
        result = client.post(
            base + "/research-ai-apply",
            headers=headers,
            json=dict(
                run_id=f["run_id"],
                finding_id=f["id"],
                accepted_digest=accept.json()["finding"]["accepted_digest"],
            ),
        )
        assert result.status_code == 409, result.text
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.research_tasks)).scalar_one() == 0
            )
            assert c.execute(select(tables.findings.c.status)).scalar_one() == "accepted"
    finally:
        scope.dispose()


def test_private_original_actor_and_rejection_are_terminal(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import import_module

    from app.auth.repository import AuthRepository
    from app.domain.product_research_findings import Apply, ProductResearchFindings, Read, Review
    from app.domain.product_workspace import ProductWorkError
    from tests.migration_fixtures import rollback_migration_operations

    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, f, _ = candidate(client, scope, tmp_path, monkeypatch, request=request)
        other = uuid4()
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            c.execute(
                tables.users.insert().values(
                    id=other,
                    tenant_id=scope.tenant_id,
                    username="private-pm",
                    display_name="Other",
                    role="admin",
                    password_hash=password,
                    is_active=True,
                )
            )
        context = AuthRepository(scope.engine).find_user_context(other)
        assert context is not None
        service = ProductResearchFindings(scope.engine)
        sid = UUID(base.split("/")[-1])
        with pytest.raises(ProductWorkError):
            service.read(context, sid, Read(run_id=UUID(f["run_id"])))
        with pytest.raises(ProductWorkError):
            service.review(context, sid, Review.model_validate(review_body(f)))
        with pytest.raises(ProductWorkError):
            service.apply(
                context,
                sid,
                Apply(run_id=UUID(f["run_id"]), finding_id=UUID(f["id"]), accepted_digest="a" * 64),
            )
        wrong = f"/api/product-work/spaces/{space(client, headers)}"
        hidden = client.post(
            wrong + "/research-ai-finding", headers=headers, json={"run_id": f["run_id"]}
        )
        assert hidden.status_code == 404, hidden.text
        assert hidden.json() == {
            "detail": {
                "code": "PRODUCT_WORK_RUN_NOT_FOUND",
                "message": "产品工作运行不存在或不属于当前发起人",
            }
        }
        body = {
            **review_body(f),
            "decision": "rejected",
            "proposal": None,
            "comment": "缺少真实样本",
        }
        result = client.post(base + "/research-ai-review", headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert (
            client.post(base + "/research-ai-review", headers=headers, json=body).json()
            == result.json()
        )
        assert (
            client.post(
                base + "/research-ai-review", headers=headers, json=review_body(f)
            ).status_code
            == 409
        )
        with (
            pytest.raises(DBAPIError, match="Retain product research"),
            rollback_migration_operations(scope.engine),
        ):
            import_module("migrations.versions.0398_product_research_findings").downgrade()
    finally:
        scope.dispose()
