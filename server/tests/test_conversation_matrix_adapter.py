"""Private conversation matrix selection boundaries; SQL doubles, no database/model."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, Engine
from sqlalchemy.sql import ClauseElement, Executable, Insert, Update

from app.auth.repository import AuthContext
from app.contracts.product_matrix_explanation import MatrixExplanationSelection
from app.domain import conversation_matrix as matrix
from app.domain import conversation_product_work as adapter
from app.domain.conversations import ConversationError, ConversationService
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, digest

TENANT, ACTOR, SPACE, LINE, CONVERSATION, RECORD, ROADMAP, REQUEST = [
    UUID(int=i) for i in range(1, 9)
]


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> "Result":
        return self

    def one_or_none(self) -> Any:
        return self.value

    def one(self) -> Any:
        return self.value

    def all(self) -> list[Any]:
        return list(self.value)

    def __iter__(self) -> Any:
        return iter(self.value)


class FakeConnection:
    def __init__(self) -> None:
        self.message: dict[str, Any] | None = None
        self.run: dict[str, Any] | None = None
        self.options: list[dict[str, Any]] = []
        self.reads: list[Executable] = []
        self.before_row: dict[str, Any] | None = None
        self.writes = 0

    def execute(self, statement: Executable) -> Result:
        if isinstance(statement, Insert):
            self.message = dict(statement.compile().params)
            self.writes += 1
            return Result(self.message)
        if isinstance(statement, Update):
            self.writes += 1
            return Result(None)
        self.reads.append(statement)
        sql = str(statement)
        if "agent_runs" in sql:
            return Result(self.run)
        if "conversation_messages" in sql:
            return Result(self.message)
        if "product_matrix_records" in sql:
            return Result(self.options if "ORDER BY" in sql else self.before_row)
        raise AssertionError(sql)


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.context = cast(
            AuthContext,
            SimpleNamespace(
                tenant=SimpleNamespace(id=TENANT),
                user=SimpleNamespace(id=ACTOR, role="engineer", auth_version=1),
            ),
        )
        self.c = FakeConnection()
        self.conversation: dict[str, Any] = dict(
            id=CONVERSATION,
            created_by_user_id=ACTOR,
            tenant_id=TENANT,
            scope_kind="product_line",
            project_id=None,
            market_space_id=SPACE,
            product_line_id=LINE,
            visibility="private",
            context_version=1,
            next_sequence=1,
            archived_at=None,
        )
        self.record: dict[str, Any] = dict(
            id=RECORD,
            tenant_id=TENANT,
            market_space_id=SPACE,
            product_line_id=LINE,
            result_digest="c" * 64,
        )
        self.denied = False
        self.marker = "original"
        self.source_calls: list[dict[str, Any]] = []
        self.read_calls: list[dict[str, Any]] = []
        from app.ai import product_matrix_preparation

        monkeypatch.setattr(product_matrix_preparation, "readable", self.readable)
        monkeypatch.setattr(matrix, "_role", lambda *args: None)
        monkeypatch.setattr(matrix, "_space", self.authorize_space)
        monkeypatch.setattr(matrix, "_line", lambda *args, **kwargs: None)
        monkeypatch.setattr(matrix, "record_row", self.record_row)
        monkeypatch.setattr(matrix, "source_state", self.source_state)
        from app.domain import conversation_attachments

        monkeypatch.setattr(conversation_attachments, "bind_attachments", lambda *args: None)

    def authorize_space(
        self, c: Connection, context: AuthContext, identity: UUID, **kwargs: Any
    ) -> None:
        if self.denied or identity != SPACE:
            raise ProductWorkAccessError("市场空间当前不可读")

    def readable(self, c: Connection, context: AuthContext, snapshot: dict[str, Any]) -> None:
        if self.denied:
            raise ProductWorkAccessError("当前运行来源撤回")
        self.read_calls.append(snapshot)

    def save(self, **changes: Any) -> dict[str, Any]:
        values: dict[str, Any] = dict(
            request_id=REQUEST,
            expected_context_version=1,
            body="解释所选矩阵与路线图",
            attachment_ids=(),
            product_sources=[],
            matrix_selection=dict(record_id=str(RECORD), roadmap_ids=[str(ROADMAP)]),
        )
        values.update(changes)
        return adapter.save(cast(Connection, self.c), self.context, self.conversation, **values)

    def run_row(self) -> dict[str, Any]:
        assert self.c.message is not None
        fixed = self.c.message["product_work_request"]
        source = self.source_state(
            cast(Connection, self.c),
            self.context,
            SPACE,
            MatrixExplanationSelection.model_validate(fixed["selection"]),
        )
        return dict(
            tenant_id=TENANT,
            request_id=self.c.message["operation_request_id"],
            scope_kind="market_space",
            project_id=None,
            market_space_id=SPACE,
            requested_by_user_id=ACTOR,
            agent_key="product_management_intelligence",
            context_version="product-matrix-request-v1",
            run_context=dict(
                matrix_selection=fixed["selection"],
                matrix_expected_digest=fixed["expected_digest"],
                matrix_user_instruction=fixed["user_instruction"],
                matrix_source=source,
            ),
        )

    def record_row(
        self, c: Connection, context: AuthContext, space: UUID, identity: UUID
    ) -> dict[str, Any]:
        if self.denied or space != SPACE or identity != RECORD:
            raise ProductWorkAccessError("当前矩阵资料不可读")
        return self.record

    def source_state(
        self,
        c: Connection,
        context: AuthContext,
        space: UUID,
        selection: MatrixExplanationSelection,
    ) -> dict[str, Any]:
        if self.denied:
            raise ProductWorkAccessError("来源当前撤回")
        value: dict[str, Any] = dict(
            actor_id=str(ACTOR),
            market_space_id=str(space),
            selection=selection.model_dump(mode="json"),
            projection_version="synthetic-matrix",
            record_result_digest=self.record["result_digest"],
            model_context=dict(question="解释矩阵", references=[], coverage_limits=[self.marker]),
        )
        self.source_calls.append(deepcopy(value))
        return {**value, "digest": digest(value)}

    def prepare(self, **changes: Any) -> dict[str, Any]:
        selected: dict[str, Any] = dict(record_id=str(RECORD), roadmap_ids=[str(ROADMAP)])
        selected.update(changes)
        return matrix.prepare(cast(Connection, self.c), self.context, self.conversation, selected)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


def test_prepare_freezes_explicit_matrix_record_roadmaps_source_and_bound_line(
    harness: Harness,
) -> None:
    value = harness.prepare()
    assert value["kind"] == "matrix"
    assert value["selection"] == dict(record_id=str(RECORD), roadmap_ids=[str(ROADMAP)])
    assert str(value["product_line_id"]) == str(LINE)
    assert value["expected_digest"] == digest(harness.source_calls[-1])
    assert "project_id" not in value and "user_instruction" not in value


@pytest.mark.parametrize("change", [dict(product_line_id=None), dict(product_line_id=UUID(int=99))])
def test_matrix_record_must_match_exact_conversation_line(
    harness: Harness, change: dict[str, Any]
) -> None:
    harness.record.update(change)
    with pytest.raises((ConversationError, ProductWorkAccessError, ProductWorkError)):
        harness.prepare()
    assert harness.source_calls == [] and harness.c.writes == 0


@pytest.mark.parametrize(
    "change",
    [
        dict(scope_kind="personal", market_space_id=None, product_line_id=None),
        dict(scope_kind="project", project_id=UUID(int=99)),
        dict(market_space_id=UUID(int=99)),
    ],
)
def test_unbound_personal_project_or_other_space_cannot_read_matrix(
    harness: Harness, change: dict[str, Any]
) -> None:
    harness.conversation.update(change)
    with pytest.raises((ConversationError, ProductWorkAccessError, ProductWorkError)):
        harness.prepare()
    assert harness.source_calls == [] and harness.c.writes == 0


def test_current_record_acl_revocation_precedes_prepare(harness: Harness) -> None:
    harness.denied = True
    with pytest.raises(ProductWorkAccessError):
        harness.prepare()
    assert harness.source_calls == []


def test_matrix_selection_never_defaults_to_another_record_or_roadmap(harness: Harness) -> None:
    with pytest.raises(ValidationError):
        matrix.prepare(
            cast(Connection, harness.c), harness.context, harness.conversation, {"roadmap_ids": []}
        )
    with pytest.raises(ValidationError):
        harness.prepare(roadmap_ids=[str(ROADMAP), str(ROADMAP)])
    with pytest.raises(ProductWorkAccessError):
        harness.prepare(record_id=str(UUID(int=99)))
    assert harness.c.writes == 0


@pytest.mark.parametrize("body", ["解释矩阵", "分析路线图"])
def test_missing_matrix_selection_saves_note_and_guidance_without_source_read(
    harness: Harness, body: str
) -> None:
    saved = harness.save(body=body, matrix_selection=None)
    assert saved["action"] == "note" and saved["product_work_request"] is None
    assert saved["guidance"] and harness.source_calls == []


def test_mixed_matrix_and_product_goal_is_note_without_dispatch(harness: Harness) -> None:
    saved = harness.save(body="竞品分析和矩阵解释", matrix_selection=None)
    assert saved["action"] == "note" and saved["product_work_request"] is None
    assert harness.source_calls == []


def test_saved_matrix_routes_to_real_matrix_request_and_retry_keeps_original_digest(
    harness: Harness,
) -> None:
    from app.ai.product_matrix_runs import Request

    first = harness.save()
    fixed = deepcopy(first["product_work_request"])
    assert first["action"] == "product_work" and first["project_id"] is None
    assert fixed["kind"] == "matrix" and fixed["user_instruction"] == first["body"]
    writes = harness.c.writes
    harness.marker = "current matrix sources changed"
    assert harness.save() == first
    assert harness.c.writes == writes and harness.c.message is not None
    assert harness.c.message["product_work_request"] == fixed
    request = adapter.run_request(harness.c.message)
    assert isinstance(request, Request)
    assert request.selection.record_id == RECORD and request.selection.roadmap_ids == (ROADMAP,)
    assert request.expected_digest == fixed["expected_digest"]
    with pytest.raises(ConversationError):
        harness.save(matrix_selection=dict(record_id=str(RECORD), roadmap_ids=[]))
    assert harness.c.writes == writes


@pytest.mark.parametrize(
    "changes",
    [
        dict(attachment_ids=(ROADMAP,)),
        dict(product_sources=[dict(kind="product", id=str(ROADMAP))]),
    ],
)
def test_matrix_does_not_mix_attachment_or_product_sources(
    harness: Harness, changes: dict[str, Any]
) -> None:
    with pytest.raises(ConversationError):
        harness.save(**changes)
    assert harness.c.writes == 0 and harness.source_calls == []


def test_replay_revalidates_current_matrix_authority_before_returning_frozen_history(
    harness: Harness,
) -> None:
    harness.save()
    frozen = deepcopy(harness.c.message)
    writes = harness.c.writes
    harness.denied = True
    with pytest.raises(ProductWorkAccessError):
        harness.save()
    assert harness.c.message == frozen and harness.c.writes == writes


def test_matrix_run_uses_matrix_namespace_and_current_readable(harness: Harness) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    row = adapter.product_run(
        cast(Connection, harness.c), harness.context, harness.conversation, harness.c.message
    )
    assert row is harness.c.run
    assert harness.read_calls == [row["run_context"]["matrix_source"]]
    params = cast(ClauseElement, harness.c.reads[-1]).compile().params
    assert TENANT in params.values() and row["request_id"] in params.values()
    harness.denied = True
    with pytest.raises(ProductWorkAccessError):
        adapter.product_run(
            cast(Connection, harness.c), harness.context, harness.conversation, harness.c.message
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_version", "product-work-request-v1"),
        ("market_space_id", UUID(int=99)),
        ("project_id", SPACE),
        ("requested_by_user_id", UUID(int=99)),
        ("agent_key", "forged"),
    ],
)
def test_fake_matrix_runtime_rejected_before_history_projection(
    harness: Harness, field: str, value: Any
) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    harness.c.run[field] = value
    with pytest.raises(ConversationError):
        adapter.product_run(
            cast(Connection, harness.c), harness.context, harness.conversation, harness.c.message
        )
    assert harness.read_calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("selection", dict(record_id=str(ROADMAP), roadmap_ids=[])),
        ("digest", "b" * 64),
        ("actor_id", str(UUID(int=99))),
    ],
)
def test_fake_matrix_source_binding_rejected(harness: Harness, field: str, value: Any) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    harness.c.run["run_context"]["matrix_source"][field] = value
    with pytest.raises(ConversationError):
        adapter.product_run(
            cast(Connection, harness.c), harness.context, harness.conversation, harness.c.message
        )
    assert harness.read_calls == []


def test_options_are_bounded_exact_scope_metadata_with_authorized_cursor(harness: Harness) -> None:
    harness.c.options = [
        dict(
            id=UUID(int=100 + i),
            title=f"矩阵{i}",
            version=1,
            body="不可披露原矩阵",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for i in range(31)
    ]
    result = matrix.options(
        cast(Connection, harness.c), harness.context, harness.conversation, None
    )
    assert len(result["items"]) == 30 and result["next_before"] == str(harness.c.options[29]["id"])
    assert all(set(row) == {"id", "title", "version"} for row in result["items"])
    query = harness.c.reads[-1]
    params = cast(ClauseElement, query).compile().params
    assert TENANT in params.values() and SPACE in params.values() and LINE in params.values()
    assert "LIMIT" in str(query).upper() and 31 in params.values()
    harness.c.before_row = None
    with pytest.raises(ProductWorkAccessError):
        matrix.options(
            cast(Connection, harness.c), harness.context, harness.conversation, UUID(int=999)
        )


class DispatchEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> Any:
        return nullcontext(self.connection)


def dispatch_service(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, *, gateway: Any
) -> ConversationService:
    service = ConversationService(cast(Engine, DispatchEngine(harness.c)), gateway=gateway)
    monkeypatch.setattr(service, "_conversation", lambda *args: harness.conversation)
    monkeypatch.setattr(service, "_attachment_ids", lambda *args: ())
    return service


def test_nonproject_note_dispatch_without_gateway_returns_saved_guidance(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = harness.save(matrix_selection=None)
    service = dispatch_service(harness, monkeypatch, gateway=None)
    result = service.dispatch(
        context=harness.context, conversation_id=CONVERSATION, message_id=UUID(message["id"])
    )
    assert result["status"] == "saved" and result["guidance"]
    assert harness.source_calls == [] and harness.c.run is None


def test_actual_dispatch_uses_original_matrix_runtime_request_not_work_runtime(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai.product_matrix_runs import ProductMatrixRuns, Request
    from app.ai.product_work_runs import ProductWorkRuns

    message = harness.save(body="解释矩阵与路线图；发布仍由人工办理")
    calls: list[Request] = []

    def create(
        self: ProductMatrixRuns, *, context: AuthContext, space_id: UUID, request: Request
    ) -> dict[str, Any]:
        assert context is harness.context and space_id == SPACE
        calls.append(request)
        return {"run_id": str(UUID(int=50)), "status": "running"}

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Matrix conversation must not dispatch ProductWorkRuns")

    monkeypatch.setattr(ProductMatrixRuns, "create", create)
    monkeypatch.setattr(ProductWorkRuns, "create", forbidden)
    service = dispatch_service(harness, monkeypatch, gateway=object())
    result = service.dispatch(
        context=harness.context, conversation_id=CONVERSATION, message_id=UUID(message["id"])
    )
    assert result["runtime"] == "product_matrix" and len(calls) == 1
    assert calls[0].request_id == UUID(message["operation_request_id"])
    assert calls[0].selection.record_id == RECORD
    assert calls[0].expected_digest == message["product_work_request"]["expected_digest"]
    assert calls[0].user_instruction == message["body"]
    assert (
        harness.c.run is None
    )  # Runtime boundary double did not model/write a business disposition.
