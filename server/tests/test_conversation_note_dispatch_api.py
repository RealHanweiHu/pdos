"""Authorized note dispatch is independent of model setup; real runtime gates remain.

These isolated API cases reuse the existing synthetic provider/budget conditions.
They do not establish production model qualification or human publication.
"""

from collections.abc import Callable, Generator, Iterator
from contextlib import closing
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, Request
from sqlalchemy import Engine, func, select

from app.ai import application_gateway
from app.ai.application_gateway import ApplicationModelGateway
from app.ai.budget_adoption import METER_DIGEST_KEY, METER_PATH_KEY, MODE_KEY, PROFILE_KEY
from app.ai.input_metering import MeteringError
from app.api.ai import get_application_gateway
from app.db.engine import get_engine
from app.db.schema import tables
from app.main import app
from tests import test_application_run_budget_api as budget_factory
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_conversations_api import Candidate, colleague
from tests.test_product_conversations_api import candidate as candidate
from tests.test_product_work_runs_api import enable_test_only, output_for
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


def override(monkeypatch: pytest.MonkeyPatch, value: Callable[..., Any]) -> None:
    current = dict(app.dependency_overrides)
    current[get_application_gateway] = value
    monkeypatch.setattr(app, "dependency_overrides", current)


def forbidden_gateway(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    entered: list[str] = []

    def forbidden() -> ApplicationModelGateway:
        entered.append("entered")
        raise AssertionError("A saved note or denied message must not initialize the gateway")

    override(monkeypatch, forbidden)
    return entered


def unchanged_runtime(candidate: Candidate) -> None:
    with candidate.scope.engine.connect() as c:
        for table in (
            tables.agent_runs,
            tables.model_invocations,
            tables.product_source_files,
            tables.budget_lineages,
            tables.application_context_manifests,
        ):
            assert (
                c.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.tenant_id == candidate.scope.tenant_id)
                ).scalar_one()
                == 0
            )


def conversation_for(candidate: Candidate, kind: str) -> dict[str, Any]:
    if kind == "project":
        return candidate.post(
            "/api/conversations",
            {
                "request_id": str(uuid4()),
                "scope_kind": "project",
                "project_id": str(candidate.scope.project()),
            },
        )
    return candidate.create(kind)


@pytest.mark.parametrize("kind", ["personal", "market_space", "product_line", "project"])
def test_actual_note_api_never_resolves_failing_gateway(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    entered = forbidden_gateway(monkeypatch)
    conversation = conversation_for(candidate, kind)
    attachment = candidate.attachment(conversation)
    saved = candidate.save(
        conversation, candidate.message(conversation, attachment_ids=[attachment["id"]])
    )
    assert saved["action"] == "note"
    before = candidate.stored(conversation)
    response = candidate.client.post(
        f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run",
        headers=candidate.headers,
        json={},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "saved"
    assert "no-store" in response.headers["cache-control"]
    assert entered == [] and candidate.stored(conversation) == before
    unchanged_runtime(candidate)


@pytest.mark.parametrize(
    "denied", ["private_owner", "other_author", "missing", "archive", "space", "line", "role"]
)
def test_note_preflight_keeps_current_author_scope_and_archive_checks(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch, denied: str
) -> None:
    entered = forbidden_gateway(monkeypatch)
    user, headers = colleague(candidate)
    if denied == "other_author":
        project = candidate.scope.project()
        candidate.scope._insert(
            tables.project_members,
            {"project_id": project, "user_id": user, "added_by_user_id": candidate.scope.owner_id},
        )
        conversation = candidate.post(
            "/api/conversations",
            {
                "request_id": str(uuid4()),
                "scope_kind": "project",
                "project_id": str(project),
                "visibility": "project",
            },
        )
        saved = candidate.save(conversation, candidate.message(conversation))
    else:
        conversation = candidate.post(
            "/api/conversations",
            {
                "request_id": str(uuid4()),
                "scope_kind": "product_line",
                "market_space_id": candidate.space_id,
                "product_line_id": candidate.line["id"],
            },
            headers=headers,
        )
        saved = candidate.save(conversation, candidate.message(conversation), headers=headers)
    before = candidate.stored(conversation)
    message_id = saved["id"]
    status = 403
    if denied == "private_owner":
        headers = candidate.headers
    elif denied == "missing":
        message_id = str(uuid4())
    elif denied == "archive":
        candidate.post(
            f"/api/conversations/{conversation['id']}/archive",
            {"archived": True},
            headers=headers,
        )
        status = 409
    elif denied != "other_author":
        with candidate.scope.engine.begin() as c:
            if denied == "role":
                c.execute(
                    tables.users.update().where(tables.users.c.id == user).values(role="supplier")
                )
            else:
                table = (
                    tables.market_space_members
                    if denied == "space"
                    else tables.product_line_members
                )
                c.execute(
                    table.delete().where(
                        table.c.tenant_id == candidate.scope.tenant_id,
                        table.c.user_id == user,
                        table.c.market_space_id == UUID(candidate.space_id),
                    )
                )
    candidate.post(
        f"/api/conversations/{conversation['id']}/messages/{message_id}/run",
        {},
        status,
        headers,
    )
    assert entered == [] and candidate.stored(conversation) == before
    unchanged_runtime(candidate)


def configure_dispatch(
    candidate: Candidate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    *,
    shape: str = "nested",
    mode: str = "budgeted",
    revoke_user: UUID | None = None,
) -> tuple[list[Any], list[dict[str, object]], list[str]]:
    environment, calls, snapshots = budget_factory.factory(
        candidate.scope.engine,
        tmp_path,
        monkeypatch,
        request=request,
        output=output_for("research_planning"),
    )
    original = cast(
        Callable[[], Iterator[ApplicationModelGateway]],
        app.dependency_overrides[get_application_gateway],
    )
    if mode == "legacy":
        for field in (MODE_KEY, PROFILE_KEY, METER_PATH_KEY, METER_DIGEST_KEY):
            environment.pop(field)
    elif mode == "unqualified":
        # Denial, not a substituted passing qualification: the real publication
        # matching guard must reject a factory with no qualified model route.
        monkeypatch.setattr(application_gateway, "load_golden_qualifications", lambda *a, **kw: [])
    events: list[str] = []

    def tracked() -> Iterator[ApplicationModelGateway]:
        events.append("enter")
        try:
            stream = cast(Generator[ApplicationModelGateway, None, None], original())
            with closing(stream):
                for gateway in stream:
                    if revoke_user is not None:
                        with candidate.scope.engine.begin() as c:
                            c.execute(
                                tables.users.update()
                                .where(tables.users.c.id == revoke_user)
                                .values(role="supplier")
                            )
                    yield gateway
        finally:
            events.append("exit")

    def nested(http_request: Request, engine: Annotated[Engine, Depends(get_engine)]) -> str:
        assert engine is candidate.scope.engine
        assert http_request.method == "POST" and http_request.url.path.endswith("/run")
        events.append("dependency")
        return "current-engine-and-request"

    def configured(
        http_request: Request,
        engine: Annotated[Engine, Depends(get_engine)],
        marker: Annotated[str, Depends(nested)],
    ) -> Iterator[ApplicationModelGateway]:
        assert marker == "current-engine-and-request" and engine is candidate.scope.engine
        assert http_request.path_params["message_id"]
        yield from tracked()

    monkeypatch.setitem(
        app.dependency_overrides,
        cast(Callable[..., Any], get_engine),
        lambda: candidate.scope.engine,
    )
    # Own both override layers through the same request, so restoration unwinds
    # wrapper -> factory -> the previous entry before other fixture teardown.
    budget_factory.install_gateway(request, tracked if shape == "zero_argument" else configured)
    enable_test_only(monkeypatch, "research_planning")
    return calls, snapshots, events


@pytest.mark.parametrize("shape", ["zero_argument", "nested"])
def test_non_note_resolves_original_budget_factory_and_cleans_yield_after_replay(
    candidate: Candidate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    shape: str,
) -> None:
    calls, snapshots, events = configure_dispatch(
        candidate, tmp_path, monkeypatch, request, shape=shape
    )
    conversation = candidate.create()
    saved = candidate.save(conversation, candidate.message(conversation, "请整理研究计划"))
    assert saved["action"] == "product_work"
    before = candidate.stored(conversation)
    url = f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run"
    first = candidate.post(url, {})
    assert first["status"] == "succeeded" and first["runtime"] == "product_work"
    assert candidate.post(url, {}) == first
    assert len(calls) == len(snapshots) == 1
    expected = ["enter", "exit"] if shape == "zero_argument" else ["dependency", "enter", "exit"]
    assert events == expected * 2
    assert candidate.stored(conversation) == before
    with candidate.scope.engine.connect() as c:
        assert c.execute(select(func.count()).select_from(tables.agent_runs)).scalar_one() == 1
        assert (
            c.execute(select(func.count()).select_from(tables.model_invocations)).scalar_one() == 1
        )
        assert c.execute(select(tables.budget_lineages.c.id)).scalars().all() == [
            snapshots[0]["id"]
        ]
        assert c.execute(select(tables.product_source_files)).first() is None


@pytest.mark.parametrize("mode", ["legacy", "unqualified", "revoked_during_entry"])
def test_non_note_keeps_budget_qualification_and_second_authorization_denial(
    candidate: Candidate,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    mode: str,
) -> None:
    user, headers = colleague(candidate)
    conversation = candidate.post(
        "/api/conversations",
        {
            "request_id": str(uuid4()),
            "scope_kind": "market_space",
            "market_space_id": candidate.space_id,
        },
        headers=headers,
    )
    saved = candidate.save(
        conversation, candidate.message(conversation, "请整理研究计划"), headers=headers
    )
    before = candidate.stored(conversation)
    calls, snapshots, events = configure_dispatch(
        candidate,
        tmp_path,
        monkeypatch,
        request,
        mode=mode,
        revoke_user=user if mode == "revoked_during_entry" else None,
    )
    url = f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run"
    if mode == "unqualified":
        with pytest.raises(
            MeteringError, match="published metering qualification is invalid"
        ) as error:
            candidate.client.post(url, headers=headers, json={})
        assert isinstance(error.value.__cause__, MeteringError)
        assert str(error.value.__cause__) == "meter lacks effective matching golden qualification"
    else:
        result = candidate.post(url, {}, 403 if mode == "revoked_during_entry" else 409, headers)
        if mode == "legacy":
            assert result["detail"]["code"] == "APPLICATION_QUEUE_BUDGET_REQUIRED"
    assert events == ["dependency", "enter", "exit"]
    assert calls == [] and snapshots == []
    assert candidate.stored(conversation) == before
    unchanged_runtime(candidate)
