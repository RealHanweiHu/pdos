"""One pre-project product journey; synthetic evidence, explicit human domain actions."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.contracts.product_records import StrategyCanvas
from app.db.schema import tables
from app.domain.evidence import EvidenceService
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def command(row: dict[str, Any]) -> dict[str, Any]:
    return dict(
        expected_version=row["version"],
        payload_digest=row["payload_digest"],
        idempotency_key=str(uuid4()),
    )


def test_research_to_released_definition_matrix_and_roadmap_without_project(
    client: TestClient,
    isolated_test_run_database: str,
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        headers = bearer_headers(client)
        sid = space(client, headers)
        base = f"/api/product-work/spaces/{sid}"
        owner = str(scope.owner_id)

        def post(path: str, body: dict[str, Any], status: int = 200) -> dict[str, Any]:
            response = client.post(base + path, headers=headers, json=body)
            assert response.status_code == status, (path, response.text)
            return cast(dict[str, Any], response.json())

        def create(path: str, **body: Any) -> dict[str, Any]:
            return post(path, dict(request_id=str(uuid4()), **body), 201)

        def get(path: str) -> dict[str, Any]:
            response = client.get(base + path, headers=headers)
            assert response.status_code == 200, response.text
            return cast(dict[str, Any], response.json())

        line = create(
            "/products", code="PUMP", name="合成便携气泵", level="line", owner_user_id=owner
        )
        parent = line
        for level in ("family", "platform", "series", "model"):
            parent = create(
                "/products",
                code="PUMP-" + level,
                name="合成" + level,
                level=level,
                parent_id=parent["id"],
                owner_user_id=owner,
                regions=["TEST"],
                channels=["online"],
            )
        product = parent
        research = create(
            "/research",
            product_line_id=line["id"],
            owner_user_id=owner,
            question="合成：便携补气需要什么验证？",
            user_groups=["合成骑行者"],
            regions=["TEST"],
            time_scope="本轮合成验证",
            method="读取合成原始资料并验证闭环",
            expected_decision="选择待验证的开发路线",
            stop_conditions=["列明证据与未解决问题"],
        )
        research = post(
            f"/research/{research['id']}/start",
            {**command(research), "research_task_id": research["id"]},
        )
        service = EvidenceService(scope.engine)
        source = service.create_source(
            tenant_id=scope.tenant_id,
            actor_user_id=scope.owner_id,
            name="合成原始研究与测试记录",
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
            content="合成夹具：A型号100kPa（25℃），B型号0.1MPa（0℃）；三个方案，平台复用方案的噪声实验被证伪。不是业务实测。",
            freshness_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        ref = dict(
            tenant_id=str(scope.tenant_id),
            kind="evidence_snapshot",
            ref_id=str(evidence.id),
            as_of=evidence.captured_at.isoformat(),
            digest=evidence.content_digest,
        )
        fact = dict(text="合成假设待验证", fact_kind="hypothesis", sources=[ref])
        observed = dict(text="合成记录说明原条件不同", fact_kind="observed", sources=[ref])
        research = post(
            f"/research/{research['id']}/conclude",
            {
                **command(research),
                "research_task_id": research["id"],
                "conclusion": "合成：证据不足，先验证不同方案",
                "findings": ["工况不同不能直接排名"],
                "unresolved": ["实际市场规模未知"],
                "source_refs": [ref],
            },
        )
        assert research["state"] == "completed" and research["sources"][0]["ref_id"] == str(
            evidence.id
        )
        competitors = []
        for model, number, unit, conditions in [
            ("A", "100", "kPa", "25℃"),
            ("B", "0.1", "MPa", "0℃"),
        ]:
            competitors.append(
                create(
                    "/competitors",
                    product_line_id=line["id"],
                    brand="SYNTHETIC",
                    model=model,
                    variant="basic",
                    competitor_kind="direct",
                    region="TEST",
                    channel="online",
                    configuration="合成配置",
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
                    revision_reason="合成闭环验证",
                )
            )
        comparison = post(
            "/competitor-comparison", dict(observation_ids=[r["id"] for r in competitors])
        )
        pressure = next(row for row in comparison["rows"] if row["key"] == "pressure")
        assert pressure["status"] == "not_comparable" and pressure["reasons"]
        unknown = dict(lower=None, upper=None, basis=fact)
        market = create(
            "/market-segments",
            product_line_id=line["id"],
            title="合成便携补气",
            target_users=[fact],
            job_to_be_done=fact,
            customer_problems=[observed],
            use_environments=[fact],
            buying_criteria=[fact],
            unmet_needs=[fact],
            revision_reason="合成起始版本",
            outcome=dict(
                statement="减少现场补气时间",
                metric_key="inflation_seconds",
                unit="s",
                baseline_value=None,
                target_value="90",
                measurement_method="指定轮胎同工况计时",
                window="合成验证周期",
            ),
            sizing_inputs=dict(
                horizon_year=2027,
                currency="CNY",
                population_unit="人",
                boundary="合成范围，非实际市场",
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
        sizing = market["sizing_result"]
        assert set(sizing["estimates"]) == {"tam", "sam", "som"}
        assert all(
            value["annual_units"] is None and value["annual_revenue"] is None
            for value in sizing["estimates"].values()
        )
        assert len(sizing["unknown_parameters"]) == 5
        solutions = [
            dict(
                id=str(uuid4()),
                title="合成" + approach,
                approach=approach,
                rationale=fact,
                constraints=[],
                unknowns=["噪声待验证"],
            )
            for approach in ["new_development", "platform_reuse", "upgrade"]
        ]
        opportunity_body = dict(
            segment_id=market["id"],
            title="合成安静补气机会",
            importance=None,
            satisfaction=None,
            importance_basis=fact,
            satisfaction_basis=fact,
            solutions=solutions,
            selected_solution_id=None,
            state="evaluating",
            revision_reason="保留三方案",
        )
        rejected = client.post(
            base + "/opportunities",
            headers=headers,
            json=dict(
                request_id=str(uuid4()),
                **{
                    **opportunity_body,
                    "solutions": solutions[:2],
                    "selected_solution_id": solutions[0]["id"],
                    "state": "selected",
                },
            ),
        )
        assert rejected.status_code == 422, rejected.text
        opportunity = create("/opportunities", **opportunity_body)
        assert opportunity["opportunity_score"] is None
        experiments = []
        for dimension in ["value", "usability", "viability", "feasibility"]:
            experiment = create(
                "/experiments",
                opportunity_id=opportunity["id"],
                solution_id=solutions[1]["id"],
                plan=dict(
                    owner_user_id=owner,
                    dimension=dimension,
                    hypothesis="合成平台复用能满足" + dimension,
                    method="合成测试流程",
                    sample_basis="合成样本",
                    success_criterion="达到合成判据",
                    falsification_criterion="未达到则证伪",
                    sources=[ref],
                ),
            )
            for action in ["approve", "start"]:
                experiment = post(
                    f"/experiments/{experiment['id']}/actions",
                    {**command(experiment), "action": action, "reason": "合成具名操作"},
                )
            experiment = post(
                f"/experiments/{experiment['id']}/actions",
                {
                    **command(experiment),
                    "action": "conclude",
                    "reason": "合成结果",
                    "result": "refuted" if dimension == "feasibility" else "inconclusive",
                    "result_evidence": [ref],
                },
            )
            experiments.append(experiment)
        assert experiments[-1]["result"] == "refuted"
        # Professional work is assigned and accepted without creating a Project.
        work = create(
            "/work-items",
            product_line_id=line["id"],
            owner_user_id=owner,
            receiver_user_id=owner,
            title="合成噪声约束审查",
            action_type="constraint_review",
            expected_output="合成约束结果",
            completion_criteria="引用原记录",
        )
        for action in ["start", "submit", "accept"]:
            work = post(
                f"/work-items/{work['id']}/actions",
                {**command(work), "action": action, "note": "合成专业结论", "evidence": [ref]},
            )
        assert work["state"] == "completed"
        budget = dict(amount=None, basis=fact)
        strategy_content = dict(
            title="合成开发策略",
            owner_user_id=owner,
            canvas={key: fact for key in StrategyCanvas.model_fields},
            selected_solution_id=solutions[0]["id"],
            route_comparisons=[
                dict(
                    solution_id=s["id"],
                    currency="CNY",
                    price_target=budget,
                    nre_budget=budget,
                    id_cycle_days=budget,
                    modules=[
                        dict(key="motor", name="电机", target=dict(amount="10", basis=fact)),
                        dict(key="control", name="控制模块", target=budget),
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
                for s in solutions
            ],
            professional_constraints=[
                dict(
                    id=str(uuid4()), discipline="dqe", statement=observed, work_item_id=work["id"]
                ),
                *[
                    dict(
                        id=str(uuid4()),
                        discipline=d,
                        statement=fact,
                        disposition=dict(
                            outcome="deferred", reason="合成待补专业证据", sources=[ref]
                        ),
                    )
                    for d in ["sqe", "ie"]
                ],
            ],
            unknowns=["模块总成本与实际市场规模未知"],
            decision_reason="保留平台复用的失败证据，合成选择新开发",
        )
        strategy = create("/strategies", opportunity_id=opportunity["id"], content=strategy_content)
        assert all(
            row["target_unit_cost"] is None and row["known_subtotal"] == "10"
            for row in strategy["cost_summary"]
        )
        for action in ["submit", "publish"]:
            strategy = post(
                f"/strategies/{strategy['id']}/actions",
                {**command(strategy), "action": action, "reason": "合成具名批准"},
            )
        assert strategy["state"] == "published"
        item = dict(
            item_key="pressure",
            title="合成压力",
            target_text=None,
            target_value="100",
            unit="kPa",
            tolerance="±5kPa",
            conditions=["25℃"],
            priority="must",
            required_for_release=True,
            rationale=fact,
            verification_method="指定设备检测",
            acceptance_criterion="95至105kPa",
            verification_stage="evt",
            owner_user_id=owner,
            state="confirmed",
        )
        content: dict[str, Any] = dict(
            title="合成产品定义",
            owner_user_id=owner,
            target_users=["合成骑行者"],
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
            reviewers={d: owner for d in ["id", "md", "ee", "fw", "dqe"]},
            change_reason="合成首版",
        )
        definition = create(
            "/definitions", product_id=product["id"], strategy_id=strategy["id"], content=content
        )
        definition = post(
            f"/definitions/{definition['id']}/actions",
            {**command(definition), "action": "submit", "reason": "合成发起协审"},
        )
        bad = client.post(
            base + f"/definitions/{definition['id']}/actions",
            headers=headers,
            json={
                **command(definition),
                "action": "publish",
                "reason": "未协审拒发",
                "reviewed_source_digest": definition["review_digest"],
            },
        )
        assert bad.status_code == 409, bad.text
        for discipline in ["id", "md", "ee", "fw", "dqe"]:
            definition = post(
                f"/definitions/{definition['id']}/reviews",
                {
                    **command(definition),
                    "discipline": discipline,
                    "review_round": definition["review_round"],
                    "reviewed_source_digest": definition["review_digest"],
                    "outcome": "approved",
                    "reason": "合成专业审查记录",
                    "sources": [ref],
                },
            )
        definition = post(
            f"/definitions/{definition['id']}/actions",
            {
                **command(definition),
                "action": "publish",
                "reason": "合成产品经理发布",
                "reviewed_source_digest": definition["review_digest"],
            },
        )
        assert definition["is_current"] and definition["approval"]["approved_by_user_id"] == owner
        matrix = post("/product-matrix", dict(product_line_id=line["id"]))
        assert definition["id"] in str(matrix) and product["id"] in str(matrix)
        from tests.product_matrix_scoring_journey import verify_scoring_journey

        verify_scoring_journey(post, create, product, market, strategy, content, owner, ref)
        roadmap = post("/product-roadmap", dict(product_id=product["id"]))
        assert roadmap["can_publish"] and roadmap["source_digest"]
        roadmap = post(
            "/product-roadmap-save",
            dict(
                product_id=product["id"],
                request_id=str(uuid4()),
                expected_version=0,
                expected_source_digest=roadmap["source_digest"],
                action="publish",
                reason="合成路线图",
                body=dict(
                    scope_note="合成开发窗口",
                    checkpoints=[
                        dict(
                            key="evt",
                            title="合成验证窗口待定",
                            kind="validation",
                            owner_user_id=owner,
                            window_start=None,
                            window_end=None,
                            unknown_reason="缺实际资源条件",
                            basis=fact,
                        )
                    ],
                ),
            ),
        )
        assert product["id"] in str(roadmap)
        # Append a revision; old stable keys and releases remain available.
        revised_content = deepcopy(content)
        revised_content["items"][0]["target_value"] = "110"
        revised_content["change_reason"] = "合成新目标需重新协审"
        revised = create(
            "/definitions",
            product_id=product["id"],
            strategy_id=strategy["id"],
            supersedes_id=definition["id"],
            content=revised_content,
        )
        assert revised["state"] == "draft" and get(f"/definitions/{definition['id']}")["is_current"]
        assert get(f"/experiments/{experiments[-1]['id']}")["result"] == "refuted"
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.projects)).scalar_one() == 0
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()
