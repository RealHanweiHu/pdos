"""The actual matrix provider receives fixed scores; old projections still replay."""

# ruff: noqa: F811
import json
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import DBAPIError

from app.ai import product_matrix_runs
from app.ai.product_matrix_preparation import (
    PROJECTION,
    SCORING_PROJECTION,
    model_context,
    prompt_for,
    rebuild,
    source_state,
)
from app.ai.project_discussion_sources import actor
from app.contracts.product_matrix_explanation import MatrixExplanationSelection
from app.db.schema import tables
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_manager_loop_api import (
    test_research_to_released_definition_matrix_and_roadmap_without_project as seed_journey,
)
from tests.test_product_work_runs_api import configure, enable_test_only
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def test_matrix_score_source_wire_legacy_history_and_shadow(
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

    with monkeypatch.context() as patch:
        patch.setattr(journey, "Scope", capture_scope)
        seed_journey(client, isolated_test_run_database)
    scope = scopes[0]
    engine = create_engine(isolated_test_run_database)
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
            context = actor(c, saved["tenant_id"], saved["actor_user_id"])
            selection = MatrixExplanationSelection(record_id=saved["id"])
            legacy = source_state(
                c, context, saved["market_space_id"], selection, projection_version=PROJECTION
            )
            assert rebuild(c, saved["tenant_id"], legacy) == legacy
            assert all(
                not ref["reference_id"].endswith(":scoring")
                for ref in legacy["model_context"]["references"]
            )
            old_prompt = prompt_for(legacy)
        base = f"/api/product-work/spaces/{saved['market_space_id']}"
        matrix_request = dict(record_id=str(saved["id"]), roadmap_ids=[])
        snapshot = client.post(
            base + "/matrix-ai-context", headers=headers, json=matrix_request
        ).json()
        assert snapshot["projection_version"] == SCORING_PROJECTION
        score_ref = next(
            ref
            for ref in snapshot["model_context"]["references"]
            if ref["reference_id"].endswith(":scoring")
        )
        assert score_ref["fields"] == saved["result"]["scoring"]
        assert prompt_for(snapshot) == old_prompt  # static prefix retained
        with engine.connect() as c:
            assert rebuild(c, saved["tenant_id"], snapshot)["digest"] == snapshot["digest"]
        body = dict(
            request_id=str(uuid4()), expected_digest=snapshot["digest"], selection=matrix_request
        )
        gated = client.post(base + "/matrix-ai-runs", headers=headers, json=body)
        assert gated.status_code == 409 and "CAPABILITY_SHADOW" in gated.text

        def statement(ref: dict[str, Any], path: list[str]) -> dict[str, Any]:
            value = ref["fields"]
            for key in path:
                value = value[int(key)] if isinstance(value, list) else value[key]
            return dict(
                nature="observed",
                text="合成引用核对",
                citations=[
                    dict(
                        reference_id=ref["reference_id"],
                        digest=ref["digest"],
                        field_path=path,
                        quoted_value=value
                        if isinstance(value, str)
                        else json.dumps(
                            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                        ),
                    )
                ],
            )

        refs = snapshot["model_context"]["references"]
        products = [ref for ref in refs if ":product:" in ref["reference_id"]]
        criteria = [ref for ref in refs if ":criterion:" in ref["reference_id"]]
        output = dict(
            disposition="insufficient_evidence",
            summary=[],
            products=[
                dict(
                    product_id=ref["fields"]["id"],
                    positioning=statement(ref, ["id"]),
                    coverage=statement(ref, ["id"]),
                    missing=["合成样本不是业务评测"],
                )
                for ref in products
            ],
            criteria=[
                dict(
                    criterion_key=ref["fields"]["criterion"]["key"],
                    explanation=statement(ref, ["criterion", "key"]),
                    human_next_steps=[],
                )
                for ref in criteria
            ],
            positioning_hypotheses=[],
            platform_reuse_hypotheses=[],
            missing=["缺真实独立评测"],
            coverage_limits="合成传输验证",
        )
        enable_test_only(monkeypatch, "product_matrix")
        calls = configure(scope, tmp_path, monkeypatch, output, request=request)
        original = source_state
        with monkeypatch.context() as old_code:
            old_code.setattr(
                product_matrix_runs,
                "source_state",
                lambda *args, **kwargs: original(*args, **kwargs, projection_version=PROJECTION),
            )
            legacy_body = {**body, "request_id": str(uuid4()), "expected_digest": legacy["digest"]}
            response = client.post(base + "/matrix-ai-runs", headers=headers, json=legacy_body)
            assert response.status_code == 200 and response.json()["status"] == "succeeded", (
                response.text
            )
        output["summary"] = [statement(score_ref, ["selected_portfolio", "score"])]
        response = client.post(base + "/matrix-ai-runs", headers=headers, json=body)
        assert response.status_code == 200 and response.json()["status"] == "succeeded", (
            response.text
        )
        assert len(calls) == 2
        messages = json.loads(calls[-1].content)["messages"]
        wire = json.loads(messages[-1]["content"].split("PDOS_CONTEXT_JSON\n", 1)[1])
        context_wire = model_context(snapshot, "")
        assert wire["question"] == context_wire["question"]
        assert wire["references"] == context_wire["references"]
        transmitted = next(
            ref for ref in wire["references"] if ref["reference_id"] == score_ref["reference_id"]
        )
        assert json.loads(transmitted["excerpt"])["fields"] == saved["result"]["scoring"]
        history = client.post(
            base + "/matrix-ai-history",
            headers=headers,
            json={"record_id": matrix_request["record_id"]},
        )
        assert history.status_code == 200, history.text
        assert len(history.json()["items"]) == 2
        assert all(item["sources_current"] for item in history.json()["items"])
        migration = import_module("migrations.versions.0405_matrix_scoring_context")
        with (
            rollback_migration_operations(engine),
            pytest.raises(DBAPIError, match="Retain matrix scoring context history"),
        ):
            migration.downgrade()
        # Runtime references stay bound to actual visible records, never model-provided scope.
        denied = client.post(
            base + "/matrix-ai-context", headers=headers, json={"record_id": str(uuid4())}
        )
        assert denied.status_code == 403
    finally:
        engine.dispose()
