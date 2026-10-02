"""Synthetic provider through real budget receipts and atomic competitor/market application."""

# ruff: noqa: F811
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.ai.product_evidence_context import catalog
from app.db.schema import tables
from app.domain.evidence import EvidenceService
from tests.test_product_work_preparation_api import space
from tests.test_product_work_runs_api import (
    assert_wire_sources,
    configure,
    enable_test_only,
    output_for,
)
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def setup_candidate(
    client: TestClient,
    scope: Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    *,
    request: pytest.FixtureRequest,
) -> tuple[str, dict[str, str], dict[str, Any], list[Any]]:
    headers = bearer_headers(client)
    base = f"/api/product-work/spaces/{space(client, headers)}"
    service = EvidenceService(scope.engine)
    source = service.create_source(
        tenant_id=scope.tenant_id,
        actor_user_id=scope.owner_id,
        name="合成原始记录",
        source_type="file",
        allowed_use="internal_analysis",
        collection_frequency="on_demand",
        retention_policy="standard",
        trust_tier="unknown",
    )
    evidence = service.capture(
        tenant_id=scope.tenant_id,
        actor_user_id=scope.owner_id,
        source_id=source.id,
        content="合成夹具：A型号100kPa（25℃），B型号0.1MPa（0℃）；通勤补气需求待验证。不是实测。",
        freshness_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    selection = dict(
        capability=capability,
        product_line_id=None,
        question="核对合成资料形成候选",
        sources=[dict(kind="evidence", id=str(evidence.id))],
    )
    prepared = client.post(base + "/product-ai-context", headers=headers, json=selection)
    assert prepared.status_code == 200, prepared.text
    snapshot = prepared.json()
    ref = catalog(snapshot, scope.tenant_id)[0]["reference"]
    output = output_for(capability)
    basis = snapshot["references"][-1]
    output["summary"] = [
        dict(
            nature="hypothesis",
            text="候选尚待核对，实际业务资料待补",
            citations=[
                dict(
                    reference_id=basis["reference_id"],
                    digest=basis["digest"],
                    field_path=["content"],
                    quoted_value=basis["fields"]["content"],
                )
            ],
        )
    ]
    if capability == "competitor_analysis":
        output["competitor_observations"] = [
            dict(
                brand="合成品牌",
                model=model,
                variant="合成配置",
                competitor_kind="direct",
                region="TEST",
                channel="online",
                configuration="合成",
                lifecycle="announced",
                observed_on=datetime.now(UTC).date().isoformat(),
                identity_sources=[ref],
                metrics=[
                    dict(
                        key="pressure",
                        label="压力",
                        number=number,
                        unit=unit,
                        nature="claimed",
                        conditions=conditions,
                        source_refs=[ref],
                    )
                ],
                revision_reason="合成候选",
            )
            for model, number, unit, conditions in [
                ("A", "100", "kPa", "25℃"),
                ("B", "0.1", "MPa", "0℃"),
            ]
        ]
    else:
        fact = dict(text="合成假设", fact_kind="hypothesis", sources=[ref])
        unknown = dict(lower=None, upper=None, basis=fact)
        output["market_segments"] = [
            dict(
                title="合成通勤补气",
                job_to_be_done=fact,
                **{
                    name: [fact]
                    for name in [
                        "target_users",
                        "customer_problems",
                        "use_environments",
                        "buying_criteria",
                        "unmet_needs",
                    ]
                },
                outcome=dict(
                    statement="减少补气用时",
                    metric_key="inflation_seconds",
                    unit="s",
                    baseline_value=None,
                    target_value="90",
                    measurement_method="同工况计时",
                    window="合成验证期",
                    sources=[ref],
                ),
                sizing_inputs=dict(
                    horizon_year=2027,
                    currency="CNY",
                    population_unit="人",
                    boundary="合成范围",
                    **{
                        name: unknown
                        for name in [
                            "potential_customers",
                            "annual_units_per_customer",
                            "unit_price",
                            "serviceable_share",
                            "obtainable_share",
                        ]
                    },
                ),
                revision_reason="合成候选",
            )
        ]
    enable_test_only(monkeypatch, capability)
    calls = configure(scope, tmp_path, monkeypatch, output, request=request)
    result = client.post(
        base + "/product-ai-runs",
        headers=headers,
        json=dict(request_id=str(uuid4()), selection=selection, expected_digest=snapshot["digest"]),
    )
    assert result.status_code == 200 and result.json()["status"] == "succeeded", result.text
    assert_wire_sources(calls, snapshot, scope.tenant_id)
    read = client.post(
        base + "/evidence-ai-finding", headers=headers, json=dict(run_id=result.json()["run_id"])
    )
    assert read.status_code == 200 and read.json()["finding"], read.text
    return base, headers, read.json(), calls


def review_body(record: dict[str, Any]) -> dict[str, Any]:
    f = record["finding"]
    return dict(
        run_id=f["run_id"],
        finding_id=f["id"],
        expected_digest=f["proposed_digest"],
        decision="accepted",
        comment="已核对合成候选",
        proposal=record["proposal"],
    )


@pytest.mark.parametrize("capability", ["competitor_analysis", "market_analysis"])
def test_candidates_use_domain_logic_and_apply_once(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, calls = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        f = record["finding"]
        body = review_body(record)
        before = client.post(
            base + "/evidence-ai-apply",
            headers=headers,
            json=dict(run_id=f["run_id"], finding_id=f["id"], accepted_digest="a" * 64),
        )
        assert before.status_code == 409
        body["proposal"]["items"][0]["revision_reason"] = "核对后保留缺项与原工况"
        accepted = client.post(base + "/evidence-ai-review", headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        assert (
            client.post(base + "/evidence-ai-review", headers=headers, json=body).json()
            == accepted.json()
        )
        table = (
            tables.competitor_observations
            if capability == "competitor_analysis"
            else tables.market_segments
        )
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(table)).scalar_one() == 0
        apply = dict(
            run_id=f["run_id"],
            finding_id=f["id"],
            accepted_digest=accepted.json()["finding"]["accepted_digest"],
        )
        result = client.post(base + "/evidence-ai-apply", headers=headers, json=apply)
        assert result.status_code == 200, result.text
        assert (
            client.post(base + "/evidence-ai-apply", headers=headers, json=apply).json()
            == result.json()
        )
        recovered = client.post(
            base + "/evidence-ai-finding", headers=headers, json=dict(run_id=f["run_id"])
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["records"] == result.json()["records"]
        records = result.json()["records"]
        route = "competitors" if capability == "competitor_analysis" else "market-segments"
        for saved in records:
            detail = client.get(base + f"/{route}/{saved['id']}", headers=headers)
            assert detail.status_code == 200, detail.text
            assert detail.json()["id"] == saved["id"] and detail.json()["is_latest"]
        # The candidate result remains readable after a newer manual revision exists.
        revised = client.post(
            base + f"/{route}",
            headers=headers,
            json={
                **body["proposal"]["items"][0],
                "product_line_id": None,
                "supersedes_id": records[0]["id"],
                "request_id": str(uuid4()),
            },
        )
        assert revised.status_code == 201, revised.text
        historical = client.get(base + f"/{route}/{records[0]['id']}", headers=headers)
        assert historical.status_code == 200 and not historical.json()["is_latest"]
        other_space = space(client, headers)
        assert (
            client.get(
                f"/api/product-work/spaces/{other_space}/{route}/{records[0]['id']}",
                headers=headers,
            ).status_code
            == 403
        )
        assert len(records) == len(body["proposal"]["items"]) and len(calls) == 1
        assert all(r["source_finding_id"] == f["id"] for r in records)
        # A space reader can follow a shared result, but cannot open a line-only result.
        line = client.post(
            base + "/products",
            headers=headers,
            json={
                "request_id": str(uuid4()),
                "code": "PRIVATE-RESULTS",
                "name": "受限结果产品线",
                "level": "line",
                "owner_user_id": str(scope.owner_id),
            },
        )
        assert line.status_code == 201, line.text
        private = client.post(
            base + f"/{route}",
            headers=headers,
            json={
                **body["proposal"]["items"][0],
                "product_line_id": line.json()["id"],
                "request_id": str(uuid4()),
            },
        )
        assert private.status_code == 201, private.text
        with scope.engine.connect() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
        member = scope._insert(
            tables.users,
            {
                "username": "result-reader",
                "display_name": "结果只读成员",
                "role": "engineer",
                "password_hash": password,
                "is_active": True,
            },
        )
        with scope.engine.begin() as c:
            c.execute(
                tables.market_space_members.insert().values(
                    tenant_id=scope.tenant_id,
                    market_space_id=UUID(base.split("/")[-1]),
                    user_id=member,
                    access="viewer",
                    added_by_user_id=scope.owner_id,
                )
            )
        login = client.post(
            "/api/auth/login",
            json={
                "tenant_slug": "beepump",
                "username": "result-reader",
                "password": "correct horse battery staple",
            },
        )
        assert login.status_code == 200, login.text
        reader = {"Authorization": f"Bearer {login.json()['access_token']}"}
        shared = client.get(base + f"/{route}/{records[0]['id']}", headers=reader)
        assert shared.status_code == 200 and "no-store" in shared.headers["cache-control"]
        assert (
            client.get(base + f"/{route}/{private.json()['id']}", headers=reader).status_code == 403
        )
        denied = client.post(
            base + "/evidence-ai-finding", headers=reader, json={"run_id": f["run_id"]}
        )
        assert denied.status_code == 404, denied.text
        assert denied.json() == {
            "detail": {
                "code": "PRODUCT_WORK_RUN_NOT_FOUND",
                "message": "产品工作运行不存在或不属于当前发起人",
            }
        }
        assert len(calls) == 1
        assert "records" not in denied.json()
        if capability == "competitor_analysis":
            comparison = client.post(
                base + "/competitor-comparison",
                headers=headers,
                json=dict(observation_ids=[r["id"] for r in records]),
            )
            assert comparison.status_code == 200, comparison.text
            assert (
                next(r for r in comparison.json()["rows"] if r["key"] == "pressure")["status"]
                == "not_comparable"
            )
        else:
            assert records[0]["sizing_result"] == accepted.json()["calculations"][0]
            assert all(
                v["annual_revenue"] is None
                for v in records[0]["sizing_result"]["estimates"].values()
            )
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(table.update().values(source_finding_id=None, source_finding_position=None))
        assert f["id"] not in client.get("/api/ai/findings", headers=headers).text
    finally:
        scope.dispose()


@pytest.mark.parametrize("capability", ["competitor_analysis", "market_analysis"])
def test_batch_rolls_back_and_rejects_foreign_refs_and_actor(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    from copy import deepcopy

    from app.auth.repository import AuthRepository
    from app.domain import product_evidence_findings as module
    from app.domain.competitors import create_competitor_in_connection
    from app.domain.market_analysis import create_segment_in_connection
    from app.domain.product_workspace import ProductWorkError

    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        f = record["finding"]
        body = review_body(record)
        forged = deepcopy(body)
        forged["proposal"]["items"][0]["owner_user_id"] = str(uuid4())
        assert (
            client.post(base + "/evidence-ai-review", headers=headers, json=forged).status_code
            == 422
        )
        forged = deepcopy(body)
        refs = (
            forged["proposal"]["items"][0]["identity_sources"]
            if capability == "competitor_analysis"
            else forged["proposal"]["items"][0]["job_to_be_done"]["sources"]
        )
        refs[0]["digest"] = "a" * 64
        assert (
            client.post(base + "/evidence-ai-review", headers=headers, json=forged).status_code
            == 409
        )
        other = uuid4()
        with scope.engine.begin() as c:
            password = c.execute(
                select(tables.users.c.password_hash).where(tables.users.c.id == scope.owner_id)
            ).scalar_one()
            c.execute(
                tables.users.insert().values(
                    id=other,
                    tenant_id=scope.tenant_id,
                    username="other-pm",
                    display_name="Other",
                    role="admin",
                    password_hash=password,
                    is_active=True,
                )
            )
        context = AuthRepository(scope.engine).find_user_context(other)
        assert context is not None
        service = module.ProductEvidenceFindings(scope.engine)
        sid = UUID(base.split("/")[-1])
        with pytest.raises(ProductWorkError):
            service.read(context, sid, module.Read(run_id=UUID(f["run_id"])))
        with pytest.raises(ProductWorkError):
            service.review(context, sid, module.Review.model_validate(body))
        accept = client.post(base + "/evidence-ai-review", headers=headers, json=body)
        assert accept.status_code == 200, accept.text
        apply = dict(
            run_id=f["run_id"],
            finding_id=f["id"],
            accepted_digest=accept.json()["finding"]["accepted_digest"],
        )
        with pytest.raises(ProductWorkError):
            service.apply(context, sid, module.Apply.model_validate(apply))
        table = (
            tables.competitor_observations
            if capability == "competitor_analysis"
            else tables.market_segments
        )
        original = (
            create_competitor_in_connection
            if capability == "competitor_analysis"
            else create_segment_in_connection
        )
        count = 0

        def fail(*args: Any, **kwargs: Any) -> Any:
            nonlocal count
            value = original(*args, **kwargs)
            count += 1
            if count == len(body["proposal"]["items"]):
                raise RuntimeError("synthetic failure after last domain insert")
            return value

        with monkeypatch.context() as patch:
            patch.setattr(
                module,
                "create_competitor_in_connection"
                if capability == "competitor_analysis"
                else "create_segment_in_connection",
                fail,
            )
            with pytest.raises(RuntimeError, match="synthetic failure"):
                client.post(base + "/evidence-ai-apply", headers=headers, json=apply)
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(table)).scalar_one() == 0
            assert (
                c.execute(select(func.count()).select_from(tables.desired_outcomes)).scalar_one()
                == 0
            )
            assert c.execute(select(tables.findings.c.status)).scalar_one() == "accepted"
        result = client.post(base + "/evidence-ai-apply", headers=headers, json=apply)
        assert result.status_code == 200, result.text
    finally:
        scope.dispose()


@pytest.mark.parametrize("change", ["source", "withdraw", "quality", "shadow"])
def test_source_and_policy_changes_block_application(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from app.ai import capability_contract
    from app.ai.capability_contract import CapabilityKey, CapabilityRollout
    from app.ai.quality import FindingQualityService

    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, "competitor_analysis", request=request
        )
        f = record["finding"]
        accepted = client.post(
            base + "/evidence-ai-review", headers=headers, json=review_body(record)
        )
        assert accepted.status_code == 200, accepted.text
        if change == "shadow":
            k = CapabilityKey.PRODUCT_COMPETITOR_ANALYSIS
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
            monkeypatch.setattr(
                FindingQualityService, "is_output_allowed_connection", lambda *a, **k: False
            )
        else:
            with scope.engine.begin() as c:
                if change == "withdraw":
                    c.execute(tables.research_sources.update().values(status="disabled"))
                else:
                    c.execute(
                        tables.market_spaces.update().values(
                            title="变更范围", version=tables.market_spaces.c.version + 1
                        )
                    )
        result = client.post(
            base + "/evidence-ai-apply",
            headers=headers,
            json=dict(
                run_id=f["run_id"],
                finding_id=f["id"],
                accepted_digest=accepted.json()["finding"]["accepted_digest"],
            ),
        )
        assert result.status_code in (403, 409), result.text
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count()).select_from(tables.competitor_observations)
                ).scalar_one()
                == 0
            )
    finally:
        scope.dispose()


def test_market_parameters_use_deterministic_calculation_and_original_model_is_preserved(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import import_module

    from tests.migration_fixtures import rollback_migration_operations

    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, "market_analysis", request=request
        )
        f = record["finding"]
        body = review_body(record)
        item = body["proposal"]["items"][0]
        for name, value in [
            ("potential_customers", "100"),
            ("annual_units_per_customer", "2"),
            ("unit_price", "10"),
            ("serviceable_share", "0.5"),
            ("obtainable_share", "0.1"),
        ]:
            item["sizing_inputs"][name].update(lower=value, upper=value)
        item["outcome"]["baseline_value"] = "120"
        accepted = client.post(base + "/evidence-ai-review", headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        assert (
            accepted.json()["calculations"][0]["estimates"]["som"]["annual_revenue"]["lower"]
            == "100.00"
        )
        applied = client.post(
            base + "/evidence-ai-apply",
            headers=headers,
            json=dict(
                run_id=f["run_id"],
                finding_id=f["id"],
                accepted_digest=accepted.json()["finding"]["accepted_digest"],
            ),
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["records"][0]["sizing_result"] == accepted.json()["calculations"][0]
        current = client.post(
            base + "/evidence-ai-finding", headers=headers, json=dict(run_id=f["run_id"])
        )
        assert (
            current.json()["finding"]["proposed_payload"]["assessment"]["market_segments"][0][
                "sizing_inputs"
            ]["unit_price"]["lower"]
            is None
        )
        with (
            pytest.raises(DBAPIError, match="Retain product evidence"),
            rollback_migration_operations(scope.engine),
        ):
            import_module("migrations.versions.0399_product_evidence_findings").downgrade()
    finally:
        scope.dispose()
