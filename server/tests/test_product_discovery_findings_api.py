"""Synthetic discovery outputs through real receipts and existing domain services."""

# ruff: noqa: F811
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError
from tests.test_product_evidence_findings_api import review_body
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


def seed_discovery(client: TestClient, scope: Scope) -> dict[str, Any]:
    headers = bearer_headers(client)
    base = f"/api/product-work/spaces/{space(client, headers)}"

    def create(path: str, **body: Any) -> dict[str, Any]:
        response = client.post(
            base + path, headers=headers, json=dict(request_id=str(uuid4()), **body)
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    line = create(
        "/products",
        code="DISCOVERY",
        name="合成探索线",
        level="line",
        owner_user_id=str(scope.owner_id),
    )
    fact = dict(text="合成假设，实际效果待验证", fact_kind="hypothesis", sources=[])
    unknown = dict(lower=None, upper=None, basis=fact)
    segment = create(
        "/market-segments",
        product_line_id=line["id"],
        title="合成补气细分",
        job_to_be_done=fact,
        target_users=[fact],
        customer_problems=[fact],
        use_environments=[fact],
        buying_criteria=[fact],
        unmet_needs=[fact],
        revision_reason="合成夹具",
        outcome=dict(
            statement="缩短时间",
            metric_key="time",
            unit="s",
            baseline_value=None,
            target_value="90",
            measurement_method="同工况计时",
            window="合成周期",
        ),
        sizing_inputs=dict(
            horizon_year=2027,
            currency="CNY",
            population_unit="人",
            boundary="合成范围",
            **{
                k: unknown
                for k in [
                    "potential_customers",
                    "annual_units_per_customer",
                    "unit_price",
                    "serviceable_share",
                    "obtainable_share",
                ]
            },
        ),
    )
    solutions = [
        dict(
            title="合成" + approach,
            approach=approach,
            rationale=fact,
            constraints=[fact],
            unknowns=["噪声待验证"],
        )
        for approach in ["new_development", "platform_reuse", "upgrade"]
    ]
    opportunity = create(
        "/opportunities",
        segment_id=segment["id"],
        title="合成原机会",
        importance=None,
        satisfaction=None,
        importance_basis=fact,
        satisfaction_basis=fact,
        solutions=[dict(id=str(uuid4()), **x) for x in solutions],
        revision_reason="合成原机会",
    )
    return dict(
        base=base,
        headers=headers,
        line=line,
        segment=segment,
        opportunity=opportunity,
        fact=fact,
        solutions=solutions,
    )


def setup_candidate(
    client: TestClient,
    scope: Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    *,
    request: pytest.FixtureRequest,
) -> tuple[str, dict[str, str], dict[str, Any], list[Any]]:
    seed = seed_discovery(client, scope)
    base, headers, line = seed["base"], seed["headers"], seed["line"]
    segment, opportunity = seed["segment"], seed["opportunity"]
    fact, solutions = seed["fact"], seed["solutions"]
    selection = dict(
        capability=capability,
        product_line_id=line["id"],
        question="比较方案与证伪方法",
        sources=[
            dict(kind="segment", id=segment["id"]),
            dict(kind="opportunity", id=opportunity["id"]),
        ],
    )
    response = client.post(base + "/product-ai-context", headers=headers, json=selection)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    output = output_for(capability)
    source = next(r for r in snapshot["references"] if r["reference_id"].startswith("segment:"))
    output["summary"] = [
        dict(
            nature="hypothesis",
            text="按原细分提出待验证候选",
            citations=[
                dict(
                    reference_id=source["reference_id"],
                    digest=source["digest"],
                    field_path=["title"],
                    quoted_value=source["fields"]["title"],
                )
            ],
        )
    ]
    if capability == "opportunity_mapping":
        output["opportunities"] = [
            dict(
                segment_id=segment["id"],
                parent_opportunity_id=opportunity["id"],
                title=f"合成分支 {i}",
                importance=None,
                satisfaction=None,
                importance_basis=fact,
                satisfaction_basis=fact,
                solutions=solutions,
                revision_reason="保留三种待比较路径",
            )
            for i in range(2)
        ]
    else:
        output["experiments"] = [
            dict(
                opportunity_id=opportunity["id"],
                solution_id=opportunity["solutions"][0]["id"],
                dimension=dimension,
                hypothesis="合成假设",
                method="合成对照方法",
                sample_basis="合成样本，待招募",
                success_criterion="合成阈值达到",
                falsification_criterion="合成阈值未达到",
                due_at="2027-01-02T12:00:00+08:00",
                sources=[],
            )
            for dimension in ["value", "usability", "viability", "feasibility"]
        ]
    enable_test_only(monkeypatch, capability)
    calls = configure(scope, tmp_path, monkeypatch, output, request=request)
    response = client.post(
        base + "/product-ai-runs",
        headers=headers,
        json=dict(request_id=str(uuid4()), selection=selection, expected_digest=snapshot["digest"]),
    )
    assert response.status_code == 200 and response.json()["status"] == "succeeded", response.text
    assert_wire_sources(calls, snapshot, scope.tenant_id)
    result = client.post(
        base + "/evidence-ai-finding", headers=headers, json=dict(run_id=response.json()["run_id"])
    )
    assert result.status_code == 200 and result.json()["finding"], result.text
    return base, headers, result.json(), calls


@pytest.mark.parametrize("capability", ["opportunity_mapping", "experiment_design"])
def test_discovery_batch_preserves_domain_decisions_and_rolls_back(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
) -> None:
    from app.domain import product_evidence_findings as service

    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, calls = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        body = review_body(record)
        item = body["proposal"]["items"][0]
        item["revision_reason" if capability == "opportunity_mapping" else "method"] = (
            "人工核对后的内容"
        )
        accepted = client.post(base + "/evidence-ai-review", headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        table = tables.opportunities if capability == "opportunity_mapping" else tables.experiments
        f = accepted.json()["finding"]
        command = dict(run_id=f["run_id"], finding_id=f["id"], accepted_digest=f["accepted_digest"])
        function = (
            "create_opportunity_in_connection"
            if capability == "opportunity_mapping"
            else "create_experiment_in_connection"
        )
        original = getattr(service, function)
        count = 0

        def fail_last(*args: Any, **kwargs: Any) -> Any:
            nonlocal count
            result = original(*args, **kwargs)
            count += 1
            if count == len(body["proposal"]["items"]):
                raise ProductWorkError("合成批次末项失败")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(service, function, fail_last)
            failed = client.post(base + "/evidence-ai-apply", headers=headers, json=command)
            assert failed.status_code == 409 and "合成批次末项失败" in failed.text, failed.text
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.source_finding_id == UUID(f["id"]))
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    select(tables.findings.c.status).where(tables.findings.c.id == UUID(f["id"]))
                ).scalar_one()
                == "accepted"
            )
        applied = client.post(base + "/evidence-ai-apply", headers=headers, json=command)
        assert applied.status_code == 200, applied.text
        assert (
            client.post(base + "/evidence-ai-apply", headers=headers, json=command).json()
            == applied.json()
        )
        recovered = client.post(
            base + "/evidence-ai-finding", headers=headers, json=dict(run_id=f["run_id"])
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["records"] == applied.json()["records"]
        rows = applied.json()["records"]
        assert len(rows) == len(body["proposal"]["items"]) and len(calls) == 1
        for row in rows:
            assert (
                row["owner_user_id"] == str(scope.owner_id) and row["source_finding_id"] == f["id"]
            )
            if capability == "opportunity_mapping":
                assert row["state"] == "exploring" and row["selected_solution_id"] is None
                assert row["opportunity_score"] is None and len(row["solutions"]) == 3
                assert len({s["id"] for s in row["solutions"]}) == 3
            else:
                assert (
                    row["state"] == "draft" and row["approval_id"] is None and row["result"] is None
                )
                assert row["started_at"] is None
        # The AI origin must not prevent the ordinary human follow-through.
        if capability == "experiment_design":
            from datetime import UTC, datetime, timedelta

            from app.domain.evidence import EvidenceService
            from tests.test_product_manager_loop_api import command as precondition

            evidence_service = EvidenceService(scope.engine)
            source = evidence_service.create_source(
                tenant_id=scope.tenant_id,
                actor_user_id=scope.owner_id,
                name="合成实验结果",
                source_type="file",
                allowed_use="internal_analysis",
                collection_frequency="on_demand",
                retention_policy="standard",
                trust_tier="unknown",
            )
            snapshot = evidence_service.capture(
                tenant_id=scope.tenant_id,
                actor_user_id=scope.owner_id,
                source_id=source.id,
                content="合成实验未达到阈值；不是实际试验。",
                freshness_expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            ref = dict(
                tenant_id=str(scope.tenant_id),
                kind="evidence_snapshot",
                ref_id=str(snapshot.id),
                as_of=snapshot.captured_at.isoformat(),
                digest=snapshot.content_digest,
            )
            detail = client.get(base + f"/experiments/{rows[0]['id']}", headers=headers)
            assert detail.status_code == 200, detail.text
            current = detail.json()
            for action in ["approve", "start", "conclude"]:
                changed = client.post(
                    base + f"/experiments/{current['id']}/actions",
                    headers=headers,
                    json={
                        **precondition(current),
                        "action": action,
                        "reason": "合成具名办理",
                        **(
                            dict(result="refuted", result_evidence=[ref])
                            if action == "conclude"
                            else {}
                        ),
                    },
                )
                assert changed.status_code == 200, changed.text
                current = changed.json()
            assert current["state"] == "concluded" and current["result"] == "refuted"
            assert current["source_finding_id"] == f["id"]
        else:
            revised = client.post(
                base + "/opportunities",
                headers=headers,
                json=dict(
                    request_id=str(uuid4()),
                    supersedes_id=rows[0]["id"],
                    **{
                        key: rows[0][key]
                        for key in [
                            "segment_id",
                            "parent_opportunity_id",
                            "title",
                            "importance",
                            "satisfaction",
                            "importance_basis",
                            "satisfaction_basis",
                            "solutions",
                        ]
                    },
                    state="selected",
                    selected_solution_id=rows[0]["solutions"][1]["id"],
                    revision_reason="合成人工比较后选择",
                ),
            )
            assert revised.status_code == 201, revised.text
            assert revised.json()["supersedes_id"] == rows[0]["id"]
            original = client.get(base + f"/opportunities/{rows[0]['id']}", headers=headers)
            assert original.status_code == 200 and original.json()["state"] == "exploring"
            assert original.json()["source_finding_id"] == f["id"]
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                table.update()
                .where(table.c.id == UUID(rows[0]["id"]))
                .values(source_finding_id=None, source_finding_position=None)
            )
        from importlib import import_module

        from tests.migration_fixtures import rollback_migration_operations

        with pytest.raises(DBAPIError), rollback_migration_operations(scope.engine):
            import_module("migrations.versions.0400_product_discovery_findings").downgrade()
    finally:
        scope.dispose()


@pytest.mark.parametrize("change", ["source", "shadow", "quality", "superseded"])
@pytest.mark.parametrize("capability", ["opportunity_mapping", "experiment_design"])
def test_discovery_rejects_forged_targets_and_authority_and_stale_sources(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    change: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        body = review_body(record)
        key = "segment_id" if capability == "opportunity_mapping" else "solution_id"
        wrong = deepcopy(body)
        wrong["proposal"]["items"][0][key] = str(uuid4())
        denied = client.post(base + "/evidence-ai-review", headers=headers, json=wrong)
        assert denied.status_code == 409, denied.text
        for key in ["owner_user_id", "state", "approval"]:
            wrong = deepcopy(body)
            wrong["proposal"]["items"][0][key] = str(uuid4())
            assert (
                client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
                == 422
            )
        if capability == "opportunity_mapping":
            wrong = deepcopy(body)
            wrong["proposal"]["items"][0]["solutions"] = wrong["proposal"]["items"][0]["solutions"][
                :2
            ]
            assert (
                client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
                == 422
            )
        else:
            wrong = deepcopy(body)
            wrong["proposal"]["items"][0]["result"] = "supported"
            assert (
                client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
                == 422
            )
        accepted = client.post(base + "/evidence-ai-review", headers=headers, json=body)
        assert accepted.status_code == 200, accepted.text
        f = accepted.json()["finding"]
        if change == "shadow":
            from app.ai import capability_contract
            from app.ai.capability_contract import CapabilityKey, CapabilityRollout

            key = CapabilityKey(f"product_management_intelligence.{capability}")
            monkeypatch.setattr(
                capability_contract,
                "CAPABILITY_CONTRACTS",
                {
                    **capability_contract.CAPABILITY_CONTRACTS,
                    key: capability_contract.CAPABILITY_CONTRACTS[key].model_copy(
                        update={"rollout": CapabilityRollout.SHADOW}
                    ),
                },
            )
        elif change == "quality":
            from app.ai.quality import FindingQualityService

            monkeypatch.setattr(
                FindingQualityService, "is_output_allowed_connection", lambda *a, **k: False
            )
        elif change == "superseded":
            original = next(t for t in record["targets"] if t["kind"] == "opportunity")
            revised = client.post(
                base + "/opportunities",
                headers=headers,
                json=dict(
                    request_id=str(uuid4()),
                    supersedes_id=original["id"],
                    **{
                        key: original[key]
                        for key in [
                            "segment_id",
                            "parent_opportunity_id",
                            "title",
                            "importance",
                            "satisfaction",
                            "importance_basis",
                            "satisfaction_basis",
                            "solutions",
                            "selected_solution_id",
                            "state",
                        ]
                    },
                    revision_reason="合成新版",
                ),
            )
            assert revised.status_code == 201, revised.text
        else:
            with scope.engine.begin() as c:
                c.execute(
                    tables.market_spaces.update()
                    .where(tables.market_spaces.c.id == UUID(base.split("/")[-1]))
                    .values(title="合成来源变化", version=tables.market_spaces.c.version + 1)
                )
        denied = client.post(
            base + "/evidence-ai-apply",
            headers=headers,
            json=dict(run_id=f["run_id"], finding_id=f["id"], accepted_digest=f["accepted_digest"]),
        )
        assert denied.status_code == 409, denied.text
    finally:
        scope.dispose()
