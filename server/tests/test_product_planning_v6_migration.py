"""Actual PostgreSQL planning run bindings and retained migration history; no model calls."""

# ruff: noqa: F811
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib import import_module
from itertools import count
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import DBAPIError

from app.ai.product_work_context import contract
from app.db.schema import tables
from app.domain.product_workspace import digest
from app.main import app
from app.storage.documents import get_document_object_store
from tests.migration_fixtures import rollback_migration_operations
from tests.test_product_planning_findings_api import post
from tests.test_product_source_files_api import Store, setup
from tests.test_product_work_preparation_api import space
from tests.test_test_runs_api import Scope, bearer_headers
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database

GUARD_ERROR = "Product work run requires fixed scope, capability and sources"
_RUN_TIMES = count()


def _next_run_time() -> datetime:
    return datetime(2026, 9, 30, tzinfo=UTC) + timedelta(seconds=next(_RUN_TIMES))


def _planning_sources(client: TestClient, scope: Scope) -> dict[str, dict[str, Any]]:
    headers = bearer_headers(client)
    base = f"/api/product-work/spaces/{space(client, headers)}"
    line = post(
        client,
        base,
        headers,
        "/products",
        dict(
            request_id=str(uuid4()),
            code="PLANNING-GUARD",
            name="合成规划守卫线",
            level="line",
            owner_user_id=str(scope.owner_id),
        ),
        201,
    )
    return {
        capability: post(
            client,
            base,
            headers,
            "/product-ai-context",
            dict(
                capability=capability,
                product_line_id=line["id"],
                question="合成完整上下文，不调用模型或授予资格",
                sources=[],
            ),
        )
        for capability in (
            "research_planning",
            "competitor_analysis",
            "opportunity_mapping",
            "product_strategy",
            "product_definition",
        )
    }


def _rfq_source(client: TestClient, scope: Scope) -> dict[str, Any]:
    previous = app.dependency_overrides.get(get_document_object_store)
    store = Store()
    app.dependency_overrides[get_document_object_store] = lambda: store
    try:
        base, headers, content, body = setup(client, scope)
        registered = post(client, base, headers, "/source-files", body, 201)
        path = base + f"/source-files/{registered['id']}"
        upload = client.put(path + "/upload", headers=headers, content=content)
        assert upload.status_code == 200, upload.text
        parsed = client.post(path + "/parse", headers=headers)
        assert parsed.status_code == 200, parsed.text
        return post(
            client,
            base,
            headers,
            "/product-ai-context",
            dict(
                capability="rfq_requirements",
                product_line_id=None,
                question="合成RFQ原件范围核对",
                sources=[dict(kind="file", id=registered["id"], ordinals=[1])],
            ),
        )
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_document_object_store, None)
        else:
            app.dependency_overrides[get_document_object_store] = previous


def _run(scope: Scope, snapshot: dict[str, Any], prompt: str) -> dict[str, Any]:
    _, output_type = contract(prompt)
    now = _next_run_time()
    return dict(
        id=uuid4(),
        tenant_id=scope.tenant_id,
        market_space_id=UUID(snapshot["market_space_id"]),
        project_id=None,
        scope_kind="market_space",
        agent_key="product_management_intelligence",
        request_id=str(uuid4()),
        requested_by_user_id=scope.owner_id,
        status="running",
        event_count=0,
        event_row_ids=[],
        window_started_at=now,
        window_ended_at=now,
        context_version="product-work-request-v1",
        started_at=now,
        created_at=now,
        updated_at=now,
        run_context={
            "product_work_selection": deepcopy(snapshot["selection"]),
            "product_work_expected_digest": snapshot["digest"],
            "product_work_user_instruction": "",
            "product_work_source": deepcopy(snapshot),
            "product_work_output_mode": "read_only.v1",
            "product_work_prompt_version": prompt,
            "product_work_schema_digest": digest(output_type.model_json_schema()),
        },
    )


def _copy_run(original: dict[str, Any], *, keep_request_id: bool = False) -> dict[str, Any]:
    now = _next_run_time()
    return {
        **deepcopy(original),
        "id": uuid4(),
        "request_id": original["request_id"] if keep_request_id else str(uuid4()),
        "window_started_at": now,
        "window_ended_at": now,
        "started_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _function_state(c: Connection) -> tuple[Any, ...]:
    return tuple(
        c.execute(
            text(
                "SELECT pg_get_functiondef(p.oid),p.proacl,p.proowner,p.prosecdef,p.proconfig,"
                "obj_description(p.oid,'pg_proc') FROM pg_proc p "
                "WHERE p.oid='cehub_ai.guard_product_work_run()'::regprocedure"
            )
        ).one()
    )


def test_planning_v6_roundtrip_retains_old_complete_requests_acl_and_nonempty_history(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        sources = _planning_sources(client, scope)
        sources["rfq_requirements"] = _rfq_source(client, scope)
        legacy = [
            _run(scope, sources[capability], prompt)
            for capability, prompt in (
                ("research_planning", "product-work-v1"),
                ("product_strategy", "product-work-v1"),
                ("product_definition", "product-work-v1"),
                ("research_planning", "product-research-v2"),
                ("competitor_analysis", "product-evidence-v3"),
                ("opportunity_mapping", "product-discovery-v4"),
                ("product_strategy", "product-planning-v5"),
                ("product_definition", "product-planning-v5"),
                ("rfq_requirements", "product-rfq-v6"),
            )
        ]
        modern = [
            _run(scope, sources[capability], "product-planning-v6")
            for capability in ("product_strategy", "product_definition")
        ]
        migration = import_module("migrations.versions.0415_product_planning_v6_runs")
        with rollback_migration_operations(scope.engine) as c:
            current = _function_state(c)
            assert migration.NEW_PROMPT_GUARD in current[0]
            assert migration.OLD_PROMPT_GUARD not in current[0]
            with pytest.raises(RuntimeError, match="prompt guard is unavailable"):
                migration.upgrade()
            assert _function_state(c) == current
            for row in legacy:
                c.execute(tables.agent_runs.insert(), row)
            migration.downgrade()
            previous = _function_state(c)
            assert previous[0] == current[0].replace(
                migration.NEW_PROMPT_GUARD, migration.OLD_PROMPT_GUARD
            )
            assert previous[1:] == current[1:]
            for row in legacy:
                c.execute(tables.agent_runs.insert(), _copy_run(row))
            for row in modern:
                with pytest.raises(DBAPIError, match=GUARD_ERROR), c.begin_nested():
                    c.execute(tables.agent_runs.insert(), row)
            with pytest.raises(RuntimeError, match="prompt guard is unavailable"):
                migration.downgrade()
            migration.upgrade()
            assert _function_state(c) == current
            for row in modern:
                c.execute(tables.agent_runs.insert(), row)
            before = list(c.execute(select(tables.agent_runs).order_by(tables.agent_runs.c.id)))
            with (
                pytest.raises(DBAPIError, match="Retain planning-v6 original runs"),
                c.begin_nested(),
            ):
                migration.downgrade()
            assert _function_state(c) == current
            after = list(c.execute(select(tables.agent_runs).order_by(tables.agent_runs.c.id)))
            assert after == before
        with scope.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(tables.agent_runs)).scalar_one() == 0
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()


def test_planning_v6_keeps_scope_source_context_markers_and_fixed_input_rejections(
    client: TestClient, isolated_test_run_database: str
) -> None:
    scope = Scope(client, isolated_test_run_database)
    try:
        sources = _planning_sources(client, scope)
        original = _run(scope, sources["product_strategy"], "product-planning-v6")
        with scope.engine.begin() as c:
            c.execute(tables.agent_runs.insert(), original)
            with (
                pytest.raises(DBAPIError, match="uq_market_agent_run_request"),
                c.begin_nested(),
            ):
                c.execute(tables.agent_runs.insert(), _copy_run(original, keep_request_id=True))
            cases = (
                "scope_kind",
                "project_id",
                "market_space_id",
                "agent_key",
                "requested_by_user_id",
                "source_actor",
                "source_space",
                "source_selection",
                "source_projection",
                "source_digest",
                "missing_line",
                "missing_capability",
                "unknown_prompt",
                "missing_source",
                "missing_selection",
                "missing_expected_digest",
                "missing_schema_digest",
                "missing_prompt",
                "missing_output_mode",
            )
            for case in cases:
                incoming = _copy_run(original)
                context = incoming["run_context"]
                source = context["product_work_source"]
                if case == "scope_kind":
                    incoming["scope_kind"] = "project"
                elif case == "project_id":
                    incoming["project_id"] = uuid4()
                elif case == "market_space_id":
                    incoming["market_space_id"] = None
                elif case == "agent_key":
                    incoming["agent_key"] = "project_intelligence"
                elif case == "requested_by_user_id":
                    incoming["requested_by_user_id"] = None
                elif case == "source_actor":
                    source["actor_id"] = str(uuid4())
                elif case == "source_space":
                    source["market_space_id"] = str(uuid4())
                elif case == "source_selection":
                    source["selection"]["question"] = "改变原来源绑定"
                elif case == "source_projection":
                    source["projection_version"] = "product-work-context.v9"
                elif case == "source_digest":
                    source["digest"] = "0" * 64
                elif case == "missing_line":
                    context["product_work_selection"]["product_line_id"] = None
                    source["selection"]["product_line_id"] = None
                elif case == "missing_capability":
                    context["product_work_selection"].pop("capability")
                    source["selection"].pop("capability")
                elif case == "unknown_prompt":
                    context["product_work_prompt_version"] = "product-planning-v7"
                else:
                    field = {
                        "missing_source": "product_work_source",
                        "missing_selection": "product_work_selection",
                        "missing_expected_digest": "product_work_expected_digest",
                        "missing_schema_digest": "product_work_schema_digest",
                        "missing_prompt": "product_work_prompt_version",
                        "missing_output_mode": "product_work_output_mode",
                    }[case]
                    context.pop(field)
                with pytest.raises(DBAPIError, match=GUARD_ERROR), c.begin_nested():
                    c.execute(tables.agent_runs.insert(), incoming)
            for capability in (
                "research_planning",
                "rfq_requirements",
                "competitor_analysis",
                "market_analysis",
                "opportunity_mapping",
                "experiment_design",
                "unknown_capability",
            ):
                incoming = _copy_run(original)
                context = incoming["run_context"]
                context["product_work_selection"]["capability"] = capability
                context["product_work_source"]["selection"]["capability"] = capability
                with pytest.raises(DBAPIError, match=GUARD_ERROR), c.begin_nested():
                    c.execute(tables.agent_runs.insert(), incoming)
            changed = deepcopy(original["run_context"])
            changed["product_work_user_instruction"] = "不能重写原输入"
            with (
                pytest.raises(DBAPIError, match="Product work run input identity is immutable"),
                c.begin_nested(),
            ):
                c.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == original["id"])
                    .values(run_context=changed)
                )
            with (
                pytest.raises(DBAPIError, match="Product work run input identity is immutable"),
                c.begin_nested(),
            ):
                c.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == original["id"])
                    .values(request_id=str(uuid4()))
                )
            with pytest.raises(DBAPIError), c.begin_nested():
                c.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == original["id"])
                    .values(context_version="product-work-request-v2")
                )
            retained = c.execute(
                select(tables.agent_runs.c.run_context).where(
                    tables.agent_runs.c.id == original["id"]
                )
            ).scalar_one()
            assert retained == original["run_context"]
            assert c.execute(select(func.count()).select_from(tables.agent_runs)).scalar_one() == 1
            assert (
                c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one()
                == 0
            )
    finally:
        scope.dispose()
