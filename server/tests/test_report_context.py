"""Real upload API rejects changed source identity and missing admitted context."""

from pathlib import Path
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from app.ai import application_context, application_domain_context
from app.db.schema import tables
from tests import test_application_run_budget_api as api_factory
from tests.test_test_report_import_api import (
    MAPPING,
    FakeGateway,
    Scope,
    bearer_headers,
    build_report,
    upload,
)
from tests.test_test_report_import_api import api_context as api_context
from tests.test_test_report_import_api import isolated_import_database as isolated_import_database


@pytest.mark.parametrize(
    "fault", ["before_meter", "after_response", "missing_manifest", "history", "lease_expired"]
)
def test_report_context_failure_never_creates_import_batch(
    request: pytest.FixtureRequest,
    api_context: tuple[TestClient, FakeGateway],
    isolated_import_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    client, _ = api_context
    scope = Scope(client, isolated_import_database)
    try:
        ids = scope.seed()
        headers = bearer_headers(client)
        _, calls, _ = api_factory.factory(
            scope.engine,
            tmp_path,
            monkeypatch,
            request=request,
            output=MAPPING.model_dump(mode="json"),
        )

        def change() -> None:
            with scope.engine.begin() as c:
                if fault == "lease_expired":
                    c.execute(
                        tables.application_run_leases.update().values(
                            expires_at=func.clock_timestamp()
                        )
                    )
                    return
                run = c.execute(select(tables.agent_runs)).mappings().one()
                context = run["run_context"]
                context["mapping_request"]["file_sha256"] = "f" * 64
                c.execute(
                    tables.agent_runs.update()
                    .where(tables.agent_runs.c.id == run["id"])
                    .values(run_context=context)
                )

        if fault == "missing_manifest":
            monkeypatch.setattr(application_context, "freeze_chat_manifest", lambda *a, **kw: None)
        elif fault in {"before_meter", "history"}:
            original_record = application_domain_context.record

            def record(
                engine: Engine,
                *,
                tenant_id: UUID,
                project_id: UUID | None,
                run_id: UUID,
                model_call_id: UUID,
                purpose: str,
                context: dict[str, object],
                snapshot: dict[str, object],
            ) -> None:
                if fault == "history":
                    prompt, _ = application_domain_context.contract(purpose)
                    with scope.engine.begin() as c:
                        c.execute(
                            tables.model_invocations.insert().values(
                                id=uuid4(),
                                tenant_id=tenant_id,
                                project_id=project_id,
                                run_id=run_id,
                                agent_key=prompt["agent_key"],
                                agent_tier="default",
                                prompt_version=prompt["version"],
                                provider="minimax",
                                model="fake-model",
                                protocol="openai-compatible",
                                status="succeeded",
                                structured_attempts=1,
                            )
                        )
                original_record(
                    engine,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    run_id=run_id,
                    model_call_id=model_call_id,
                    purpose=purpose,
                    context=context,
                    snapshot=snapshot,
                )
                change()

            monkeypatch.setattr(application_domain_context, "record", record)
        else:
            original_response = api_factory.response

            def response(content: str) -> httpx2.Response:
                change()
                return original_response(content)

            monkeypatch.setattr(api_factory, "response", response)
        result = upload(
            client,
            headers,
            ids["project_id"],
            ids["plan_id"],
            build_report([("Endurance 500h", "SN-001", "PASS", 0.05, "ok")]),
        )
        assert result.status_code >= 400, result.text
        assert len(calls) == (1 if fault in {"after_response", "lease_expired"} else 0)
        with scope.engine.connect() as c:
            run = c.execute(select(tables.agent_runs)).mappings().one()
            if fault == "history":
                assert run["error_code"] == "APPLICATION_CONTEXT_HISTORY_UNAVAILABLE"
                assert c.execute(select(tables.application_context_observations)).first() is None
                assert c.execute(select(tables.test_report_import_batches)).first() is None
                return
            assert run["error_code"] == (
                "BUDGET_APPLICATION_MANIFEST_REQUIRED"
                if fault == "missing_manifest"
                else "APPLICATION_RUN_LEASE_LOST"
                if fault == "lease_expired"
                else "APPLICATION_CONTEXT_SOURCE_CHANGED"
            )
            assert c.execute(select(tables.test_report_import_batches)).first() is None
            observation = (
                c.execute(select(tables.application_context_observations)).mappings().one()
            )
            assert observation["output_body"]["request"]["file_sha256"] != "f" * 64
            if fault in {"after_response", "lease_expired"}:
                entries = c.execute(select(tables.budget_journal)).mappings().all()
                last = max(entries, key=lambda r: r["revision"])
                assert last["charged_tokens"] == 10
                assert last["reservation_status"] == "settled"
    finally:
        scope.dispose()
