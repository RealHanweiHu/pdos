"""Real budget/receipt plumbing; synthetic transport, never production qualification."""

# ruff: noqa: F811
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.ai import application_gateway, capability_contract
from app.ai.capability_contract import CapabilityKey, CapabilityRollout
from app.ai.product_evidence_context import catalog
from app.contracts.product_work_ai import REQUIRED_SECTIONS, ProductCapability
from app.db.schema import tables
from tests import test_application_run_budget_api as budget_factory
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import (
    Scope,  # noqa: F401
    bearer_headers,
)
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def output_for(capability: str) -> dict[str, Any]:
    return dict(
        capability=capability,
        disposition="insufficient_evidence",
        summary=[],
        sections=[
            dict(key=k, statements=[], missing=["需真实资料验证"])
            for k in REQUIRED_SECTIONS[capability]
        ],
        next_steps=[],
        missing=["需真实研究材料"],
        coverage_limits="合成测试；不代表真实研究或模型资格",
    )


def enable_test_only(monkeypatch: pytest.MonkeyPatch, capability: str) -> None:
    key = CapabilityKey(f"product_management_intelligence.{capability}")
    monkeypatch.setattr(
        capability_contract,
        "CAPABILITY_CONTRACTS",
        {
            **capability_contract.CAPABILITY_CONTRACTS,
            key: capability_contract.CAPABILITY_CONTRACTS[key].model_copy(
                update={"rollout": CapabilityRollout.LIVE}
            ),
        },
    )


def configure(
    scope: Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: dict[str, Any],
    *,
    request: pytest.FixtureRequest,
) -> list[Any]:
    env, calls, _ = budget_factory.factory(
        scope.engine, tmp_path, monkeypatch, request=request, output=output
    )
    original = application_gateway.configured_application_gateway
    monkeypatch.setattr(
        application_gateway, "configured_application_gateway", lambda engine: original(engine, env)
    )
    return calls


def assert_wire_sources(
    calls: list[Any], snapshot: dict[str, Any], tenant_id: UUID, instruction: str = ""
) -> None:
    """Inspect the provider HTTP payload, after actual authorization and gateway projection."""
    assert calls
    messages = json.loads(calls[-1].content)["messages"]
    wire = json.loads(messages[-1]["content"].split("PDOS_CONTEXT_JSON\n", 1)[1])
    assert wire["question"].startswith(snapshot["selection"]["question"] + "\n")
    details = json.loads(wire["question"].split("\n本次分析范围与要求：", 1)[1])
    capability = snapshot["selection"]["capability"]
    assert details["capability"] == capability
    assert details["required_sections"] == list(REQUIRED_SECTIONS[capability])
    assert details["warnings"] == snapshot["warnings"]
    assert details["coverage_limits"] == snapshot["coverage_limits"]
    assert details["user_instruction"] == instruction
    assert details["context_version"] == "product-work-source-adapter.v2"
    assert len(wire["references"]) == len(snapshot["references"])
    for sent, original in zip(wire["references"], snapshot["references"], strict=True):
        assert sent["reference_id"] == original["reference_id"]
        assert sent["label"] == original["label"]
        assert json.loads(sent["excerpt"]) == {
            "digest": original["digest"],
            "fields": original["fields"],
        }
    if capability not in ("research_planning", "rfq_requirements"):
        assert details["evidence_references"] == catalog(snapshot, tenant_id)


def prepared(
    client: TestClient, base: str, headers: dict[str, str], capability: str, line: str | None = None
) -> dict[str, Any]:
    selection: dict[str, Any] = dict(
        capability=capability, question="合成研究计划", product_line_id=line, sources=[]
    )
    response = client.post(base + "/product-ai-context", headers=headers, json=selection)
    assert response.status_code == 200, response.text
    return dict(
        request_id=str(uuid4()), selection=selection, expected_digest=response.json()["digest"]
    )


@pytest.mark.parametrize("capability", [k for k in REQUIRED_SECTIONS if k != "rfq_requirements"])
def test_each_capability_persists_budget_context_receipt_and_idempotent_history(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        line = client.post(
            base + "/products",
            headers=headers,
            json=dict(
                request_id=str(uuid4()),
                code="LINE",
                name="合成产品线",
                level="line",
                owner_user_id=str(scope.owner_id),
            ),
        )
        assert line.status_code == 201, line.text
        lid = line.json()["id"]
        body = prepared(client, base, headers, capability, lid)
        gated = client.post(base + "/product-ai-runs", headers=headers, json=body)
        assert gated.status_code == 409 and "CAPABILITY_SHADOW" in gated.text
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
        enable_test_only(monkeypatch, capability)
        calls = configure(scope, tmp_path, monkeypatch, output_for(capability), request=request)
        response = client.post(base + "/product-ai-runs", headers=headers, json=body)
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["status"] == "succeeded", saved
        assert saved["assessment"]["capability"] == capability and saved["invocation_id"]
        assert client.post(base + "/product-ai-runs", headers=headers, json=body).json() == saved
        assert len(calls) == 1
        snapshot = client.post(
            base + "/product-ai-context", headers=headers, json=body["selection"]
        )
        assert snapshot.status_code == 200, snapshot.text
        assert_wire_sources(calls, snapshot.json(), scope.tenant_id)
        read = dict(capability=capability, product_line_id=lid, run_id=saved["run_id"])
        history = client.post(base + "/product-ai-history", headers=headers, json=read)
        assert history.status_code == 200, history.text
        assert history.json()["items"][0]["sources_current"]
        assert history.json()["items"][0]["frozen_sources"]
        assert (
            client.post(
                base + "/product-ai-progress", headers=headers, json={"run_id": saved["run_id"]}
            ).status_code
            == 200
        )
        changed = client.post(
            base + "/product-ai-runs",
            headers=headers,
            json={**body, "user_instruction": "修改原输入"},
        )
        assert changed.status_code == 409, changed.text
        wrong = f"/api/product-work/spaces/{space(client, headers)}"
        hidden = client.post(
            wrong + "/product-ai-progress", headers=headers, json={"run_id": saved["run_id"]}
        )
        assert hidden.status_code == 404, hidden.text
        assert hidden.json() == {
            "detail": {
                "code": "PRODUCT_WORK_RUN_NOT_FOUND",
                "message": "产品工作运行不存在或不属于当前发起人",
            }
        }
        assert len(calls) == 1
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.count()).select_from(tables.budget_lineages)).scalar_one()
                == 1
            )
            assert (
                c.execute(select(tables.application_authorizations.c.body)).scalar_one()["purpose"]
                == "product_work"
            )
            assert (
                c.execute(select(tables.application_result_checkpoints.c.body)).scalar_one()[
                    "output"
                ]["capability"]
                == capability
            )
            assert (
                c.execute(
                    select(tables.budget_journal.c.charged_tokens)
                    .order_by(tables.budget_journal.c.revision.desc())
                    .limit(1)
                ).scalar_one()
                > 0
            )
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                tables.agent_runs.update()
                .where(tables.agent_runs.c.id == UUID(saved["run_id"]))
                .values(context_version="product-matrix-request-v1")
            )
        if capability == "research_planning":
            from importlib import import_module

            from tests.migration_fixtures import rollback_migration_operations

            with (
                pytest.raises(DBAPIError, match="Retain product work history"),
                rollback_migration_operations(scope.engine),
            ):
                import_module("migrations.versions.0397_product_work_runs").downgrade()
            # Even another administrator cannot read the author's private analysis receipt.
            from app.ai.product_work_runs import ProductWorkRuns, run_row
            from app.auth.repository import AuthRepository
            from app.domain.product_workspace import ProductWorkError

            other = uuid4()
            with scope.engine.begin() as c:
                password_hash = c.execute(
                    select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
                ).scalar_one()
                c.execute(
                    tables.users.insert().values(
                        id=other,
                        tenant_id=scope.tenant_id,
                        username="other-pm",
                        display_name="Other PM",
                        role="admin",
                        password_hash=password_hash,
                        is_active=True,
                    )
                )
            context = AuthRepository(scope.engine).find_user_context(other)
            assert context is not None
            assert not ProductWorkRuns.list_results(
                scope.engine,
                context=context,
                space_id=UUID(sid),
                capability=cast(ProductCapability, capability),
                product_line_id=UUID(lid),
            )["items"]
            with scope.engine.connect() as c, pytest.raises(ProductWorkError):
                run_row(c, context, UUID(sid), UUID(saved["run_id"]))
        with scope.engine.begin() as c:
            c.execute(
                tables.market_spaces.update()
                .where(tables.market_spaces.c.id == UUID(sid))
                .values(title="变更后的市场问题", version=tables.market_spaces.c.version + 1)
            )
        history = client.post(base + "/product-ai-history", headers=headers, json=read)
        assert not history.json()["items"][0]["sources_current"]
        assert len(calls) == 1
    finally:
        scope.dispose()


@pytest.mark.parametrize("change", ["source", "archive", "cancel"])
def test_inflight_changes_never_publish_analysis_and_charges_are_retained(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        body = prepared(client, base, headers, "research_planning")
        enable_test_only(monkeypatch, "research_planning")
        calls = configure(
            scope, tmp_path, monkeypatch, output_for("research_planning"), request=request
        )
        original = budget_factory.response

        def respond(content: str) -> Any:
            with scope.engine.begin() as c:
                if change == "cancel":
                    run_id = c.execute(select(tables.agent_runs.c.id)).scalar_one()
                else:
                    c.execute(
                        tables.market_spaces.update()
                        .where(tables.market_spaces.c.id == UUID(sid))
                        .values(
                            version=tables.market_spaces.c.version + 1,
                            **(
                                {"title": "来源变化"}
                                if change == "source"
                                else {"lifecycle": "archived"}
                            ),
                        )
                    )
            if change == "cancel":
                cancel = client.post(
                    base + "/product-ai-cancel", headers=headers, json={"run_id": str(run_id)}
                )
                assert cancel.status_code == 200, cancel.text
            return original(content)

        monkeypatch.setattr(budget_factory, "response", respond)
        response = client.post(base + "/product-ai-runs", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["assessment"] is None and response.json()["status"] != "succeeded", (
            response.text
        )
        assert len(calls) == 1
        with scope.engine.connect() as c:
            assert (
                c.execute(select(func.sum(tables.budget_journal.c.charged_tokens))).scalar_one() > 0
            )
    finally:
        scope.dispose()


@pytest.mark.parametrize(
    "capability,prompt_version",
    [
        ("research_planning", "product-work-v1"),
        ("research_planning", "product-research-v2"),
        ("competitor_analysis", "product-work-v1"),
        ("competitor_analysis", "product-evidence-v3"),
        ("market_analysis", "product-work-v1"),
        ("market_analysis", "product-evidence-v3"),
        ("opportunity_mapping", "product-work-v1"),
        ("opportunity_mapping", "product-discovery-v4"),
        ("experiment_design", "product-work-v1"),
        ("experiment_design", "product-discovery-v4"),
        ("product_strategy", "product-work-v1"),
        ("product_strategy", "product-planning-v5"),
        ("product_strategy", "product-planning-v6"),
        ("product_definition", "product-work-v1"),
        ("product_definition", "product-planning-v5"),
        ("product_definition", "product-planning-v6"),
    ],
)
def test_expired_owner_recovers_saved_result_without_second_model_charge(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt_version: str,
    capability: str,
) -> None:
    from sqlalchemy import text

    from app.ai import product_work_runs
    from app.ai.gateway import StructuredModelGateway
    from app.ai.product_work_context import contract
    from tests.test_application_leases import expire

    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        line_id = None
        if capability in (
            "opportunity_mapping",
            "experiment_design",
            "product_strategy",
            "product_definition",
        ):
            line = client.post(
                base + "/products",
                headers=headers,
                json=dict(
                    request_id=str(uuid4()),
                    code="RECOVERY",
                    name="合成恢复线",
                    level="line",
                    owner_user_id=str(scope.owner_id),
                ),
            )
            assert line.status_code == 201, line.text
            line_id = line.json()["id"]
        body = prepared(client, base, headers, capability, line_id)
        enable_test_only(monkeypatch, capability)
        monkeypatch.setattr(
            product_work_runs,
            "contract",
            lambda version=None, **kwargs: contract(version or prompt_version),
        )
        original_invoke = StructuredModelGateway.invoke_structured
        calls = configure(scope, tmp_path, monkeypatch, output_for(capability), request=request)
        # Creation assertions in the shared factory do not apply to recovery.
        interrupted = False

        def invoke(gateway: Any, invocation: Any, output_type: Any) -> Any:
            nonlocal interrupted
            assert invocation.prompt_version == prompt_version
            result = original_invoke(gateway, invocation, output_type)
            if not interrupted:
                assert result.status == "succeeded", result
                interrupted = True
                expire(scope.engine, invocation.run_id)
                with scope.engine.begin() as c:
                    assert (
                        c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one()
                        == 1
                    )
                raise RuntimeError("synthetic process interruption after persisted model receipt")
            return result

        monkeypatch.setattr(StructuredModelGateway, "invoke_structured", invoke)
        first = client.post(base + "/product-ai-runs", headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
        with scope.engine.connect() as c:
            before = c.execute(
                select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
            ).all()
        second = client.post(base + "/product-ai-runs", headers=headers, json=body)
        assert second.status_code == 200 and second.json()["status"] == "succeeded", second.text
        assert first.json()["run_id"] == second.json()["run_id"] and len(calls) == 1
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(tables.budget_journal).order_by(tables.budget_journal.c.revision)
                ).all()
                == before
            )
            assert (
                c.execute(
                    select(func.count()).select_from(tables.application_result_checkpoints)
                ).scalar_one()
                == 1
            )
    finally:
        scope.dispose()
