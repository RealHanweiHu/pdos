"""Synthetic strategy and definition drafts, explicit human releases and stable revision keys."""

# ruff: noqa: F811
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.contracts.product_records import StrategyCanvas
from app.db.schema import tables
from app.domain.product_workspace import ProductWorkError
from tests.test_product_discovery_findings_api import seed_discovery
from tests.test_product_evidence_findings_api import review_body
from tests.test_product_manager_loop_api import command
from tests.test_product_work_runs_api import (
    assert_wire_sources,
    configure,
    enable_test_only,
    output_for,
)
from tests.test_test_runs_api import Scope
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def post(
    client: TestClient,
    base: str,
    headers: dict[str, str],
    path: str,
    body: dict[str, Any],
    status: int = 200,
) -> dict[str, Any]:
    response = client.post(base + path, headers=headers, json=body)
    assert response.status_code == status, (path, response.text)
    return dict(response.json())


def release_definition(
    client: TestClient, base: str, headers: dict[str, str], value: dict[str, Any]
) -> dict[str, Any]:
    value = post(
        client,
        base,
        headers,
        f"/definitions/{value['id']}/actions",
        {**command(value), "action": "submit", "reason": "合成送审"},
    )
    for discipline in ["id", "md", "ee", "fw", "dqe"]:
        value = post(
            client,
            base,
            headers,
            f"/definitions/{value['id']}/reviews",
            {
                **command(value),
                "discipline": discipline,
                "review_round": value["review_round"],
                "reviewed_source_digest": value["review_digest"],
                "outcome": "approved",
                "reason": "合成身份逐专业验证，并非真人试用",
            },
        )
    value = post(
        client,
        base,
        headers,
        f"/definitions/{value['id']}/actions",
        {
            **command(value),
            "action": "publish",
            "reason": "合成发布",
            "reviewed_source_digest": value["review_digest"],
            "expected_release_id": value["current_release"]["id"]
            if value["current_release"]
            else None,
        },
    )
    return value


def setup_candidate(
    client: TestClient,
    scope: Scope,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    revision: bool = False,
    seed_only: bool = False,
    *,
    request: pytest.FixtureRequest | None = None,
) -> tuple[str, dict[str, str], dict[str, Any], list[Any]]:
    seed = seed_discovery(client, scope)
    base, headers, fact, opportunity = (
        seed["base"],
        seed["headers"],
        seed["fact"],
        seed["opportunity"],
    )

    def create(path: str, **body: Any) -> dict[str, Any]:
        return post(client, base, headers, path, dict(request_id=str(uuid4()), **body), 201)

    owner = str(scope.owner_id)
    work = create(
        "/work-items",
        product_line_id=seed["line"]["id"],
        owner_user_id=owner,
        receiver_user_id=owner,
        title="合成专业约束",
        action_type="constraint_review",
        expected_output="约束记录",
        completion_criteria="明确待补证据",
    )
    product = seed["line"]
    for level in ["family", "platform", "series", "model"]:
        product = create(
            "/products",
            code="PLAN-" + level,
            name="合成" + level,
            level=level,
            parent_id=product["id"],
            owner_user_id=owner,
        )
    budget = dict(amount=None, basis=fact)
    strategy: dict[str, Any] = dict(
        title="合成策略候选",
        canvas={key: fact for key in StrategyCanvas.model_fields},
        route_comparisons=[
            dict(
                solution_id=s["id"],
                currency="CNY",
                price_target=budget,
                nre_budget=budget,
                id_cycle_days=budget,
                modules=[
                    dict(key="motor", name="电机", target=dict(amount="10", basis=fact)),
                    dict(key="control", name="控制", target=budget),
                ],
                **{
                    k: fact
                    for k in [
                        "scope",
                        "quality",
                        "supply",
                        "manufacturing",
                        "resources",
                        "trade_off",
                    ]
                },
            )
            for s in opportunity["solutions"]
        ],
        professional_constraints=[
            dict(discipline=d, statement=fact, work_item_id=work["id"])
            for d in ["dqe", "sqe", "ie"]
        ],
        unknowns=["实际成本与专业证据待补"],
        decision_reason="先比较，人工选定和发布",
    )
    original_strategy = None
    if capability == "product_definition" or revision:
        content = {
            **strategy,
            "owner_user_id": owner,
            "selected_solution_id": opportunity["solutions"][0]["id"],
            "professional_constraints": [
                dict(id=str(uuid4()), **x) for x in strategy["professional_constraints"]
            ],
        }
        original_strategy = create("/strategies", opportunity_id=opportunity["id"], content=content)
        for action in ["submit", "publish"]:
            original_strategy = post(
                client,
                base,
                headers,
                f"/strategies/{original_strategy['id']}/actions",
                {**command(original_strategy), "action": action, "reason": "合成具名操作"},
            )
    item = dict(
        item_key="pressure",
        title="压力",
        target_text=None,
        target_value="100",
        unit="kPa",
        tolerance=None,
        conditions=["25℃"],
        priority="must",
        required_for_release=True,
        rationale=fact,
        verification_method=None,
        acceptance_criterion=None,
        verification_stage=None,
    )
    definition = dict(
        title="合成定义候选",
        target_users=["骑行者"],
        scenarios=["现场补气"],
        included_features=["inflate"],
        excluded_features=["lighting"],
        region_constraints=[fact],
        target_cost=fact,
        price_position=fact,
        launch_window=fact,
        service_requirements=[fact],
        success_criteria=[fact],
        items=[item],
        change_reason="合成首版",
    )
    original_definition = None
    if capability == "product_definition" and revision:
        assert original_strategy is not None
        content = {
            **definition,
            "owner_user_id": owner,
            "reviewers": {d: owner for d in ["id", "md", "ee", "fw", "dqe"]},
            "items": [
                {
                    **item,
                    "owner_user_id": owner,
                    "state": "confirmed",
                    "verification_method": "合成方法",
                    "acceptance_criterion": "合成判据",
                    "verification_stage": "evt",
                }
            ],
        }
        original_definition = create(
            "/definitions",
            product_id=product["id"],
            strategy_id=original_strategy["id"],
            content=content,
        )
        original_definition = release_definition(client, base, headers, original_definition)
    if seed_only:
        assert original_definition is not None
        return base, headers, original_definition, []
    if request is None:
        raise ValueError("A pytest request is required for gateway setup")
    sources = [
        dict(kind="opportunity", id=opportunity["id"]),
        dict(kind="product", id=product["id"]),
        dict(kind="work", id=work["id"]),
    ]
    if original_strategy:
        sources.append(dict(kind="strategy", id=original_strategy["id"]))
    if original_definition:
        sources.append(dict(kind="definition", id=original_definition["id"]))
    selection = dict(
        capability=capability,
        product_line_id=seed["line"]["id"],
        question="核对合成策略与定义",
        sources=sources,
    )
    snapshot = post(client, base, headers, "/product-ai-context", selection)
    output = output_for(capability)
    ref = next(r for r in snapshot["references"] if r["reference_id"].startswith("opportunity:"))
    output["summary"] = [
        dict(
            nature="hypothesis",
            text="根据原机会形成待核对草稿",
            citations=[
                dict(
                    reference_id=ref["reference_id"],
                    digest=ref["digest"],
                    field_path=["title"],
                    quoted_value=ref["fields"]["title"],
                )
            ],
        )
    ]
    if capability == "product_strategy":
        output["product_strategies"] = [
            dict(
                opportunity_id=opportunity["id"],
                supersedes_id=original_strategy["id"] if revision and original_strategy else None,
                **strategy,
            )
        ]
    else:
        assert original_strategy is not None
        output["product_definitions"] = [
            dict(
                product_id=product["id"],
                strategy_id=original_strategy["id"],
                supersedes_id=original_definition["id"] if original_definition else None,
                **definition,
            )
        ]
    enable_test_only(monkeypatch, capability)
    calls = configure(scope, tmp_path, monkeypatch, output, request=request)
    run = post(
        client,
        base,
        headers,
        "/product-ai-runs",
        dict(request_id=str(uuid4()), selection=selection, expected_digest=snapshot["digest"]),
    )
    assert run["status"] == "succeeded", run
    assert_wire_sources(calls, snapshot, scope.tenant_id)
    record = post(client, base, headers, "/evidence-ai-finding", dict(run_id=run["run_id"]))
    assert record["finding"], record
    return base, headers, record, calls


@pytest.mark.parametrize("capability", ["product_strategy", "product_definition"])
@pytest.mark.parametrize("revision", [False, True])
def test_planning_candidates_follow_human_release_and_preserve_original_versions(
    request: pytest.FixtureRequest,
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capability: str,
    revision: bool,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        base, headers, record, calls = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, revision, request=request
        )
        review = review_body(record)
        value = review["proposal"]["items"][0]
        if revision and capability == "product_definition":
            wrong = deepcopy(review)
            wrong["proposal"]["items"][0]["items"][0]["item_key"] = "replacement"
            denied = client.post(base + "/evidence-ai-review", headers=headers, json=wrong)
            assert denied.status_code == 409 and "标识" in denied.text, denied.text
        accepted = post(client, base, headers, "/evidence-ai-review", review)["finding"]
        apply = dict(
            run_id=accepted["run_id"],
            finding_id=accepted["id"],
            accepted_digest=accepted["accepted_digest"],
        )
        applied = post(client, base, headers, "/evidence-ai-apply", apply)
        assert post(client, base, headers, "/evidence-ai-apply", apply) == applied
        assert len(calls) == 1
        recovered = post(
            client, base, headers, "/evidence-ai-finding", dict(run_id=accepted["run_id"])
        )
        assert recovered["records"] == applied["records"]
        row = applied["records"][0]
        assert (
            row["state"] == "draft"
            and row["approval"] is None
            and row["source_finding_id"] == accepted["id"]
        )
        assert row["revision_number"] == (2 if revision else 1)
        table = (
            tables.product_strategies
            if capability == "product_strategy"
            else tables.product_definitions
        )
        route = "strategies" if capability == "product_strategy" else "definitions"
        detail = client.get(base + f"/{route}/{row['id']}", headers=headers)
        assert detail.status_code == 200, detail.text
        current = detail.json()
        denied = client.post(
            base + f"/{route}/{row['id']}/actions",
            headers=headers,
            json={**command(current), "action": "submit", "reason": "尚未人工决定"},
        )
        assert denied.status_code == 409, denied.text
        if capability == "product_strategy":
            assert row["selected_solution_id"] is None
            assert len(row["canvas"]) == 9
            assert all(c["disposition"] is None for c in row["professional_constraints"])
            assert all(
                s["known_subtotal"] == "10" and s["target_unit_cost"] is None
                for s in row["cost_summary"]
            )
            fields = [
                "title",
                "owner_user_id",
                "canvas",
                "route_comparisons",
                "selected_solution_id",
                "professional_constraints",
                "unknowns",
                "decision_reason",
            ]
            content = {k: current[k] for k in fields}
            content["selected_solution_id"] = content["route_comparisons"][0]["solution_id"]
            current = post(
                client,
                base,
                headers,
                f"/strategies/{row['id']}/changes",
                {**command(current), "content": content, "reason": "合成人工选定"},
            )
            for action in ["submit", "publish"]:
                current = post(
                    client,
                    base,
                    headers,
                    f"/strategies/{row['id']}/actions",
                    {**command(current), "action": action, "reason": "合成具名操作"},
                )
        else:
            assert row["content"]["reviewers"] == {}
            assert row["content"]["items"][0]["state"] == "needs_confirmation"
            assert row["content"]["items"][0]["owner_user_id"] is None
            content = current["content"]
            owner = str(scope.owner_id)
            content["reviewers"] = {d: owner for d in ["id", "md", "ee", "fw", "dqe"]}
            content["items"][0].update(
                owner_user_id=owner,
                state="confirmed",
                verification_method="合成方法",
                acceptance_criterion="合成判据",
                verification_stage="evt",
            )
            current = post(
                client,
                base,
                headers,
                f"/definitions/{row['id']}/changes",
                {**command(current), "content": content, "reason": "合成人工确认规格与协审人"},
            )
            current = release_definition(client, base, headers, current)
            matrix = post(
                client,
                base,
                headers,
                "/product-matrix",
                dict(product_line_id=row["product_line_id"]),
            )
            assert row["id"] in str(matrix)
        assert current["state"] == "published" and current["source_finding_id"] == accepted["id"]
        if revision:
            original = client.get(base + f"/{route}/{value['supersedes_id']}", headers=headers)
            assert original.status_code == 200 and original.json()["state"] == "published"
            assert original.json()["id"] != current["id"]
        with pytest.raises(DBAPIError), scope.engine.begin() as c:
            c.execute(
                table.update()
                .where(table.c.id == UUID(row["id"]))
                .values(source_finding_id=None, source_finding_position=None)
            )
    finally:
        scope.dispose()


@pytest.mark.parametrize("capability", ["product_strategy", "product_definition"])
def test_planning_target_authority_validation_and_atomic_application(
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
        base, headers, record, _ = setup_candidate(
            client, scope, tmp_path, monkeypatch, capability, request=request
        )
        body = review_body(record)
        for key in ["owner_user_id", "state", "approval", "reviewers", "selected_solution_id"]:
            wrong = deepcopy(body)
            wrong["proposal"]["items"][0][key] = str(uuid4())
            assert (
                client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
                == 422
            )
        wrong = deepcopy(body)
        wrong["proposal"]["items"][0][
            "opportunity_id" if capability == "product_strategy" else "product_id"
        ] = str(uuid4())
        assert (
            client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
            == 409
        )
        wrong = deepcopy(body)
        if capability == "product_strategy":
            wrong["proposal"]["items"][0]["professional_constraints"][0]["work_item_id"] = str(
                uuid4()
            )
            assert (
                client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
                == 409
            )
        else:
            wrong["proposal"]["items"][0]["items"][0]["state"] = "confirmed"
            assert (
                client.post(base + "/evidence-ai-review", headers=headers, json=wrong).status_code
                == 422
            )
        accepted = post(client, base, headers, "/evidence-ai-review", body)["finding"]
        inbox = client.get("/api/ai/findings", headers=headers)
        assert inbox.status_code == 200 and accepted["id"] not in inbox.text
        apply = dict(
            run_id=accepted["run_id"],
            finding_id=accepted["id"],
            accepted_digest=accepted["accepted_digest"],
        )
        name = (
            "create_strategy_in_connection"
            if capability == "product_strategy"
            else "create_definition_in_connection"
        )
        original = getattr(service, name)

        def fail(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise ProductWorkError("合成业务写入后失败")

        with monkeypatch.context() as patch:
            patch.setattr(service, name, fail)
            result = client.post(base + "/evidence-ai-apply", headers=headers, json=apply)
            assert result.status_code == 409 and "合成业务写入后失败" in result.text, result.text
        table = (
            tables.product_strategies
            if capability == "product_strategy"
            else tables.product_definitions
        )
        with scope.engine.connect() as c:
            assert (
                c.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.source_finding_id == UUID(accepted["id"]))
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    select(tables.findings.c.status).where(
                        tables.findings.c.id == UUID(accepted["id"])
                    )
                ).scalar_one()
                == "accepted"
            )
        assert (
            post(client, base, headers, "/evidence-ai-apply", apply)["finding"]["status"]
            == "applied"
        )
        from importlib import import_module

        from tests.migration_fixtures import rollback_migration_operations

        with pytest.raises(DBAPIError), rollback_migration_operations(scope.engine):
            import_module("migrations.versions.0401_product_planning_findings").downgrade()
    finally:
        scope.dispose()
