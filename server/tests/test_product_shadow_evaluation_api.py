"""Real admin/API/DB/gateway/budget path, with a synthetic provider transport only."""

# ruff: noqa: F811
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError

from app.ai import capability_contract
from app.ai.capability_contract import CapabilityKey, CapabilityRollout
from app.ai.gateway import GatewayInvocation, GatewayResult, StructuredModelGateway
from app.ai.product_evaluation import canonical, digest
from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.test_product_manager_loop_api import (
    test_research_to_released_definition_matrix_and_roadmap_without_project as seed_journey,
)
from tests.test_product_research_findings_api import PLAN
from tests.test_product_work_preparation_api import space
from tests.test_product_work_runs_api import assert_wire_sources, configure, output_for
from tests.test_test_runs_api import PASSWORD, Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

BINDING = dict(
    provider="minimax",
    model="MiniMax-M2.7",
    protocol="openai-compatible",
    configuration_sha256="a" * 64,
)


def selection(capability: str, line: str | None = None) -> dict[str, Any]:
    return dict(
        capability=capability,
        work=dict(capability=capability, question="合成影子评测", product_line_id=line, sources=[]),
    )


def prepared(
    client: TestClient, base: str, headers: dict[str, str], chosen: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    r = client.post(base + "/evaluation/prepare", headers=headers, json=chosen)
    assert r.status_code == 200, r.text
    pack: dict[str, Any] = r.json()
    body = dict(
        request_id=str(uuid4()),
        case_id="test-only",
        suite_sha256="b" * 64,
        binding=BINDING,
        selection=chosen,
        user_instruction="",
        **{k: pack[k] for k in ("source_sha256", "expected_digest", "runtime_sha256")},
    )
    return pack, body


@pytest.mark.parametrize(
    "capability",
    [
        "research_planning",
        "competitor_analysis",
        "market_analysis",
        "opportunity_mapping",
        "experiment_design",
        "product_strategy",
        "product_definition",
    ],
)
def test_shadow_admin_receipt_idempotence_and_zero_business_effects(
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
        r = client.post(
            base + "/products",
            headers=headers,
            json=dict(
                request_id=str(uuid4()),
                code="EVAL",
                name="合成评测产品线",
                level="line",
                owner_user_id=str(scope.owner_id),
            ),
        )
        assert r.status_code == 201, r.text
        chosen = selection(capability, r.json()["id"])
        pack, body = prepared(client, base, headers, chosen)
        ordinary = client.post(
            base + "/product-ai-runs",
            headers=headers,
            json=dict(
                request_id=str(uuid4()),
                selection=chosen["work"],
                expected_digest=pack["expected_digest"],
            ),
        )
        assert ordinary.status_code == 409 and "CAPABILITY_SHADOW" in ordinary.text
        missing = client.post(base + "/evaluation/runs", headers=headers, json=body)
        assert missing.status_code == 409 and "APPLICATION_QUEUE_BUDGET_REQUIRED" in missing.text
        output = output_for(capability)
        if capability == "research_planning":
            ref = pack["source"]["references"][0]
            output.update(
                research_plan=PLAN,
                summary=[
                    dict(
                        text="合成研究假设",
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
            )
        calls = configure(scope, tmp_path, monkeypatch, output, request=request)
        r = client.post(base + "/evaluation/runs", headers=headers, json=body)
        assert r.status_code == 200 and r.json()["status"] == "succeeded", r.text
        saved = r.json()
        assert saved["assessment"]["capability"] == capability
        assert not saved["qualification_granted"] and not saved["business_actions_created"]
        assert client.post(base + "/evaluation/runs", headers=headers, json=body).json() == saved
        assert len(calls) == 1
        assert_wire_sources(calls, pack["source"], scope.tenant_id)
        read = client.get(base + "/evaluation/runs/" + saved["run_id"], headers=headers)
        assert read.status_code == 200 and read.json()["frozen_source"] == pack["source"]
        assert read.headers["cache-control"] == "no-store"
        assert (
            client.post(
                base + "/evaluation/runs",
                headers=headers,
                json={**body, "user_instruction": "改写原件"},
            ).status_code
            == 409
        )
        hidden = client.post(
            base + "/research-ai-finding", headers=headers, json=dict(run_id=saved["run_id"])
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
            for table in (
                tables.findings,
                tables.research_tasks,
                tables.scoped_work_items,
                tables.product_definitions,
                tables.product_strategies,
                tables.projects,
            ):
                assert c.execute(select(func.count()).select_from(table)).scalar_one() == 0
            run = c.execute(select(tables.agent_runs)).mappings().one()
            assert run["context_version"] == "product-evaluation-request-v1"
            auth = c.execute(select(tables.application_authorizations)).mappings().one()
            assert auth["body"]["purpose"] == "product_evaluation"
            assert auth["pins"]["action"] == "model_governance.manage"
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                tables.agent_runs.update().values(
                    run_context={**run["run_context"], "evaluation_output_mode": "read_only.v1"}
                )
            )
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(tables.agent_runs.update().values(context_version="product-work-request-v1"))
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                tables.agent_runs.update().values(
                    run_context={
                        **run["run_context"],
                        "evaluation_result": {**saved["assessment"], "missing": ["改写原结果"]},
                    }
                )
            )
        if capability == "research_planning":
            from importlib import import_module

            from tests.migration_fixtures import rollback_migration_operations

            with pytest.raises(DBAPIError), rollback_migration_operations(scope.engine):
                import_module("migrations.versions.0407_product_shadow_evaluation").downgrade()
    finally:
        scope.dispose()


def test_suite_all_case_preflight_matching_and_claim_boundaries(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        chosen = selection("research_planning")
        pack, _ = prepared(client, base, headers, chosen)
        output = output_for("research_planning")
        calls = configure(scope, tmp_path, monkeypatch, output, request=request)
        suite = dict(
            version="product-capability-evaluation.v1",
            suite_version="synthetic-test",
            review_status="candidate",
            capability="research_planning",
            prompt_version=pack["prompt_version"],
            runtime_sha256=pack["runtime_sha256"],
            cases=[
                dict(
                    case_id="case-a",
                    slices=["synthetic"],
                    tenant_id=str(scope.tenant_id),
                    source=pack["source"],
                    source_sha256=pack["source_sha256"],
                    expected_outputs=[output],
                )
            ],
        )

        def payload(value: dict[str, Any]) -> dict[str, Any]:
            doc = canonical(value)
            return dict(
                evaluation_id=str(uuid4()),
                suite_document=doc,
                suite_sha256=sha256(doc.encode()).hexdigest(),
                binding=BINDING,
            )

        invalid = deepcopy(suite)
        invalid["cases"].append(
            {**invalid["cases"][0], "case_id": "case-b", "tenant_id": str(uuid4())}
        )
        denied = client.post(base + "/evaluation/suite", headers=headers, json=payload(invalid))
        assert denied.status_code == 403, denied.text
        assert len(calls) == 0
        invalid = deepcopy(suite)
        invalid["cases"].append(
            {
                **invalid["cases"][0],
                "case_id": "case-b",
                "expected_outputs": [{**output, "fake_field": "reject before first call"}],
            }
        )
        rejected = client.post(base + "/evaluation/suite", headers=headers, json=payload(invalid))
        assert rejected.status_code in (409, 422), rejected.text
        assert len(calls) == 0
        body = payload(suite)
        result = client.post(base + "/evaluation/suite", headers=headers, json=body)
        assert result.status_code == 200 and result.json()["status"] == "passed", result.text
        report = result.json()
        assert len(calls) == 1
        assert report["execution_plane"] == "shadow_evaluation"
        assert report["output_origin"] == "normalized_gateway_result"
        for key in (
            "qualification_granted",
            "provider_calls_verified",
            "reference_answers_approved",
            "source_authorization_verified",
            "configuration_binding_verified",
        ):
            assert report[key] is False
        receipt = report["cases"][0]["attempts"][0]["response"]
        assert receipt["execution_source"] == "provider_claim" and receipt["original_receipt_ref"]
        assert (
            digest({k: v for k, v in report.items() if k != "report_sha256"})
            == report["report_sha256"]
        )
        assert (
            client.post(base + "/evaluation/suite", headers=headers, json=body).status_code == 200
        )
        assert len(calls) == 1
        key = CapabilityKey("product_management_intelligence.research_planning")
        monkeypatch.setattr(
            capability_contract,
            "CAPABILITY_CONTRACTS",
            {
                **capability_contract.CAPABILITY_CONTRACTS,
                key: capability_contract.CAPABILITY_CONTRACTS[key].model_copy(
                    update={"rollout": CapabilityRollout.DISABLED}
                ),
            },
        )
        assert (
            client.post(base + "/evaluation/suite", headers=headers, json=body).status_code == 409
        )
        assert len(calls) == 1
    finally:
        scope.dispose()


def test_checkpoint_recovery_reuses_original_call_without_dispatch(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import text

    from tests.test_application_leases import expire

    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        base = f"/api/product-work/spaces/{space(client, headers)}"
        _, body = prepared(client, base, headers, selection("research_planning"))
        native = StructuredModelGateway.invoke_structured
        calls = configure(
            scope, tmp_path, monkeypatch, output_for("research_planning"), request=request
        )
        interrupted = False

        def invoke[OutputT: BaseModel](
            gateway: StructuredModelGateway,
            invocation: GatewayInvocation,
            output_type: type[OutputT],
        ) -> GatewayResult[OutputT]:
            nonlocal interrupted
            result = native(gateway, invocation, output_type)
            if not interrupted:
                assert result.status == "succeeded", result
                interrupted = True
                assert invocation.run_id is not None
                expire(scope.engine, invocation.run_id)
                with scope.engine.begin() as c:
                    assert (
                        c.execute(text("SELECT cehub_ai.expire_application_runs(100)")).scalar_one()
                        == 1
                    )
                raise RuntimeError("synthetic stopped owner after durable result")
            return result

        monkeypatch.setattr(StructuredModelGateway, "invoke_structured", invoke)
        first = client.post(base + "/evaluation/runs", headers=headers, json=body)
        assert (
            first.status_code == 200
            and first.json()["error_code"] == "APPLICATION_RUN_LEASE_EXPIRED"
        ), first.text
        with scope.engine.connect() as c:
            before = {
                t.name: list(c.execute(select(t)).mappings())
                for t in (
                    tables.model_invocations,
                    tables.budget_journal,
                    tables.application_context_observations,
                    tables.application_context_manifests,
                    tables.application_result_checkpoints,
                )
            }
        second = client.post(base + "/evaluation/runs", headers=headers, json=body)
        assert second.status_code == 200 and second.json()["status"] == "succeeded", second.text
        assert second.json()["run_id"] == first.json()["run_id"] and len(calls) == 1
        with scope.engine.connect() as c:
            for name, rows in before.items():
                assert list(c.execute(select(getattr(tables, name))).mappings()) == rows
            assert (
                c.execute(
                    select(func.count()).select_from(tables.application_run_leases)
                ).scalar_one()
                == 2
            )
            assert c.execute(select(func.count()).select_from(tables.findings)).scalar_one() == 0
        assert (
            client.post(base + "/evaluation/runs", headers=headers, json=body).json()
            == second.json()
        )
        assert len(calls) == 1
    finally:
        scope.dispose()


def test_matrix_shadow_preserves_scored_source_and_creates_no_actions(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests import test_product_manager_loop_api as journey

    scopes: list[Scope] = []

    def capture_scope(seed_client: TestClient, database_url: str) -> Scope:
        scope = Scope(seed_client, database_url)
        scopes.append(scope)
        return scope

    # Keep the real scope created by the complete original API/domain journey.
    with monkeypatch.context() as patch:
        patch.setattr(journey, "Scope", capture_scope)
        seed_journey(client, isolated_test_run_database)
    scope = scopes[0]
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    scope.engine = engine
    try:
        headers = bearer_headers(client)
        with engine.connect() as c:
            saved = (
                c.execute(
                    select(tables.product_matrix_records)
                    .order_by(tables.product_matrix_records.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .one()
            )
            before = {
                t.name: c.execute(select(func.count()).select_from(t)).scalar_one()
                for t in (
                    tables.findings,
                    tables.scoped_work_items,
                    tables.product_matrix_dispositions,
                    tables.product_definitions,
                    tables.product_roadmap_revisions,
                )
            }
        base = f"/api/product-work/spaces/{saved['market_space_id']}"
        chosen = dict(
            capability="product_matrix", matrix=dict(record_id=str(saved["id"]), roadmap_ids=[])
        )
        pack, body = prepared(client, base, headers, chosen)

        def statement(ref: dict[str, Any], path: list[str]) -> dict[str, Any]:
            value = ref["fields"]
            for key in path:
                value = value[key]
            return dict(
                nature="observed",
                text="合成矩阵引用",
                citations=[
                    dict(
                        reference_id=ref["reference_id"],
                        digest=ref["digest"],
                        field_path=path,
                        quoted_value=value if isinstance(value, str) else canonical(value),
                    )
                ],
            )

        refs = pack["source"]["model_context"]["references"]
        output = dict(
            disposition="insufficient_evidence",
            summary=[],
            products=[
                dict(
                    product_id=r["fields"]["id"],
                    positioning=statement(r, ["id"]),
                    coverage=statement(r, ["id"]),
                    missing=["需独立业务评测"],
                )
                for r in refs
                if ":product:" in r["reference_id"]
            ],
            criteria=[
                dict(
                    criterion_key=r["fields"]["criterion"]["key"],
                    explanation=statement(r, ["criterion", "key"]),
                    human_next_steps=[],
                )
                for r in refs
                if ":criterion:" in r["reference_id"]
            ],
            positioning_hypotheses=[],
            platform_reuse_hypotheses=[],
            missing=["合成来源"],
            coverage_limits="合成测试",
        )
        calls = configure(scope, tmp_path, monkeypatch, output, request=request)
        result = client.post(base + "/evaluation/runs", headers=headers, json=body)
        assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
        assert (
            client.post(base + "/evaluation/runs", headers=headers, json=body).json()
            == result.json()
        )
        assert len(calls) == 1
        wire = json.loads(
            json.loads(calls[0].content)["messages"][-1]["content"].split("PDOS_CONTEXT_JSON\n", 1)[
                1
            ]
        )
        assert any(r["reference_id"].endswith(":scoring") for r in wire["references"])
        with engine.connect() as c:
            for name, count in before.items():
                assert (
                    c.execute(select(func.count()).select_from(getattr(tables, name))).scalar_one()
                    == count
                )
    finally:
        engine.dispose()


@pytest.mark.parametrize("change_kind", ["role", "source"])
def test_role_digest_route_and_post_call_revocation_fail_closed(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change_kind: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        chosen = selection("research_planning")
        pack, body = prepared(client, base, headers, chosen)
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            uid = uuid4()
            c.execute(
                tables.users.insert().values(
                    id=uid,
                    tenant_id=scope.tenant_id,
                    username="evaluation-reader",
                    display_name="合成产品经理",
                    role="project_manager",
                    is_active=True,
                    password_hash=password,
                )
            )
            c.execute(
                tables.market_space_members.insert().values(
                    tenant_id=scope.tenant_id,
                    market_space_id=UUID(sid),
                    user_id=uid,
                    access="manager",
                    added_by_user_id=scope.owner_id,
                )
            )
        login = client.post(
            "/api/auth/login",
            json=dict(tenant_slug="beepump", username="evaluation-reader", password=PASSWORD),
        )
        reader = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert (
            client.post(base + "/evaluation/prepare", headers=reader, json=chosen).status_code
            == 403
        )
        assert client.post(base + "/evaluation/runs", headers=reader, json=body).status_code == 403
        assert client.post(base + "/evaluation/runs", json=body).status_code == 401
        calls = configure(
            scope, tmp_path, monkeypatch, output_for("research_planning"), request=request
        )
        for field in ("source_sha256", "expected_digest", "runtime_sha256"):
            assert (
                client.post(
                    base + "/evaluation/runs", headers=headers, json={**body, field: "0" * 64}
                ).status_code
                == 409
            )
        assert not calls
        wrong = {**body, "request_id": str(uuid4()), "binding": {**BINDING, "model": "other-model"}}
        rejected = client.post(base + "/evaluation/runs", headers=headers, json=wrong)
        assert rejected.status_code == 200 and rejected.json()["status"] == "degraded", (
            rejected.text
        )
        assert not calls
        original = StructuredModelGateway.invoke_structured

        def revoke[OutputT: BaseModel](
            gateway: StructuredModelGateway,
            invocation: GatewayInvocation,
            output_type: type[OutputT],
        ) -> GatewayResult[OutputT]:
            result = original(gateway, invocation, output_type)
            with scope.engine.begin() as c:
                if change_kind == "role":
                    c.execute(
                        tables.users.update()
                        .where(tables.users.c.id == scope.owner_id)
                        .values(
                            role="project_manager", auth_version=tables.users.c.auth_version + 1
                        )
                    )
                else:
                    c.execute(
                        tables.market_spaces.update()
                        .where(tables.market_spaces.c.id == UUID(sid))
                        .values(title="评测期间来源变化")
                    )
            return result

        monkeypatch.setattr(StructuredModelGateway, "invoke_structured", revoke)
        result = client.post(base + "/evaluation/runs", headers=headers, json=body)
        assert result.status_code == 200 and result.json()["status"] == "degraded", result.text
        assert result.json()["assessment"] is None and len(calls) == 1
        assert client.get(
            base + "/evaluation/runs/" + result.json()["run_id"], headers=headers
        ).status_code == (401 if change_kind == "role" else 200)
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.findings)).scalar_one() == 0
    finally:
        scope.dispose()
