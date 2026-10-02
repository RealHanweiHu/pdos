"""Original run read in one transaction; real receipt/readable, no database or model."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.sql import ClauseElement, Executable

from app.ai import product_work_context as work_context
from app.ai import product_work_runs as runs
from app.api.product_research import ProductRunRead
from app.auth.repository import AuthContext
from app.contracts.product_work_ai import ProductWorkSelection
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, digest

TENANT, ACTOR, SPACE, LINE, RUN, FILE = [UUID(int=i) for i in range(1, 7)]


class Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row

    def mappings(self) -> "Result":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.row

    def all(self) -> list[dict[str, Any]]:
        return [self.row] if self.row else []


class ReadConnection:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.in_transaction = False
        self.begins = 0
        self.creation_lookup = False
        self.engine = cast(Engine, SimpleNamespace())
        self.statements: list[Executable] = []

    def __enter__(self) -> "ReadConnection":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.in_transaction = False

    def execution_options(self, **options: Any) -> "ReadConnection":
        assert options == {"isolation_level": "REPEATABLE READ"}
        return self

    def begin(self) -> "ReadConnection":
        self.in_transaction = True
        self.begins += 1
        return self

    def execute(self, statement: Executable) -> Result:
        assert self.in_transaction
        compiled = cast(ClauseElement, statement).compile()
        sql = str(compiled)
        assert sql.startswith("SELECT") and "agent_runs" in sql
        self.statements.append(statement)
        # Simulate database predicates, not an unscoped row returned by a mock.
        params = compiled.params
        assert params is not None
        if self.creation_lookup:
            assert TENANT in params.values() and SPACE in params.values()
            assert str(RUN) in params.values()
            assert "product_management_intelligence" in params.values()
            assert "market_space" in params.values()
            return Result(None)
        assert TENANT in params.values() and SPACE in params.values() and ACTOR in params.values()
        assert "product_management_intelligence" in params.values()
        assert runs.RUN_VERSION in params.values() and "market_space" in params.values()
        assert "project_id IS NULL" in sql
        row = self.row
        if row is None or any(
            (
                row["tenant_id"] != TENANT,
                row["market_space_id"] != SPACE,
                row["requested_by_user_id"] != ACTOR,
                row["agent_key"] != "product_management_intelligence",
                row["context_version"] != runs.RUN_VERSION,
                row["scope_kind"] != "market_space",
                row["project_id"] is not None,
            )
        ):
            return Result(None)
        return Result(row)


class ReadEngine:
    def __init__(self, connection: ReadConnection) -> None:
        self.connection = connection
        self.connects = 0

    def connect(self) -> ReadConnection:
        self.connects += 1
        return self.connection


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]]:
    selected = ProductWorkSelection.model_validate(
        {
            "capability": "rfq_requirements",
            "product_line_id": LINE,
            "question": "原RFQ资料",
            "sources": [{"kind": "file", "id": FILE, "ordinals": [1]}],
        }
    ).model_dump(mode="json")
    original: dict[str, Any] = dict(
        actor_id=str(ACTOR),
        market_space_id=str(SPACE),
        selection=selected,
        references=[
            dict(
                reference_id=f"file:{FILE}:fragment:1",
                label="原片段",
                digest="a" * 64,
                fields={"text": "固定原文", "ordinal": 1},
            )
        ],
    )
    original["digest"] = digest(original)
    row: dict[str, Any] = dict(
        id=RUN,
        tenant_id=TENANT,
        market_space_id=SPACE,
        project_id=None,
        scope_kind="market_space",
        agent_key="product_management_intelligence",
        requested_by_user_id=ACTOR,
        context_version=runs.RUN_VERSION,
        request_id="original-request",
        status="succeeded",
        created_at=datetime(2026, 9, 30, tzinfo=UTC),
        error_code=None,
        run_context=dict(
            product_work_selection=selected,
            product_work_source=original,
            product_work_expected_digest=original["digest"],
            product_work_user_instruction="原始说明",
        ),
    )
    connection = ReadConnection(row)
    engine = ReadEngine(connection)
    context = cast(
        AuthContext,
        SimpleNamespace(
            tenant=SimpleNamespace(id=TENANT),
            user=SimpleNamespace(id=ACTOR),
        ),
    )
    observed: list[Any] = []

    def authorize(
        c: Any, _context: AuthContext, space: UUID, line: UUID | None, **kwargs: Any
    ) -> None:
        assert c is connection and connection.in_transaction
        observed.append((space, line, kwargs))

    def current_sources(
        c: Any, _context: AuthContext, space: UUID, selection: ProductWorkSelection
    ) -> dict[str, Any]:
        assert c is connection and connection.in_transaction
        assert space == SPACE and selection.model_dump(mode="json") == selected
        observed.append("actual source revalidation")
        return original

    monkeypatch.setattr(runs, "authorize", authorize)
    monkeypatch.setattr(work_context, "authorize", authorize)
    monkeypatch.setattr(work_context, "source_state", current_sources)
    monkeypatch.setattr(work_context, "resolve_evidence", lambda *args: [])
    monkeypatch.setattr(runs, "rebuild", lambda *args: original)
    return engine, context, row, observed


def read(setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]]) -> dict[str, Any]:
    engine, context, _, _ = setup
    return runs.ProductWorkRuns.list_results(
        cast(Engine, engine), context=context, space_id=SPACE, run_id=RUN
    )


def test_original_rfq_derives_scope_and_keeps_real_receipt_in_one_transaction(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
) -> None:
    engine, _, row, observed = setup
    before = deepcopy(row)
    result = read(setup)
    item = result["items"][0]
    assert item["run_id"] == str(RUN) and item["selection"]["capability"] == "rfq_requirements"
    assert item["selection"]["product_line_id"] == str(LINE)
    assert item["frozen_sources"] == row["run_context"]["product_work_source"]["references"]
    assert item["reference_labels"] == {f"file:{FILE}:fragment:1": "原片段"}
    assert item["sources_current"] and item["requested_by_me"]
    assert row == before
    assert engine.connects == 1 and engine.connection.begins == 1
    assert len(engine.connection.statements) == 1
    assert "actual source revalidation" in observed
    assert all(entry[1] == LINE for entry in observed if isinstance(entry, tuple))


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", UUID(int=99)),
        ("market_space_id", UUID(int=99)),
        ("requested_by_user_id", UUID(int=99)),
        ("agent_key", "project_discussion"),
        ("context_version", "product-matrix-request-v1"),
        ("scope_kind", "project"),
        ("project_id", UUID(int=99)),
    ],
)
def test_original_run_wrong_database_binding_is_generic_denial(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
    field: str,
    value: Any,
) -> None:
    _, _, row, observed = setup
    row[field] = value
    with pytest.raises(ProductWorkError, match="不存在或不属于当前发起人"):
        read(setup)
    assert not observed


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", str(UUID(int=99))),
        ("market_space_id", str(UUID(int=99))),
        ("selection", {"capability": "research_synthesis"}),
        ("digest", "b" * 64),
        ("references", []),
    ],
)
def test_original_run_wrong_frozen_binding_cannot_disclose_refs(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
    field: str,
    value: Any,
) -> None:
    _, _, row, observed = setup
    row["run_context"]["product_work_source"][field] = value
    with pytest.raises(ProductWorkError, match="不存在或不属于当前发起人"):
        read(setup)
    assert not observed


@pytest.mark.parametrize("boundary", ["authority", "source"])
def test_current_revoke_blocks_original_history(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise ProductWorkAccessError("当前权限已撤回")

    monkeypatch.setattr(
        runs if boundary == "authority" else work_context,
        "authorize" if boundary == "authority" else "source_state",
        denied,
    )
    with pytest.raises(ProductWorkAccessError, match="当前权限已撤回"):
        read(setup)


def test_original_lookup_requires_run_id_and_body_rejects_scope_fields(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
) -> None:
    engine, context, _, _ = setup
    with pytest.raises(ProductWorkError):
        runs.ProductWorkRuns.list_results(cast(Engine, engine), context=context, space_id=SPACE)
    with pytest.raises(ValidationError):
        ProductRunRead.model_validate(
            {"run_id": RUN, "capability": "rfq_requirements", "product_line_id": LINE}
        )


@pytest.mark.parametrize("matching", [False, True])
def test_create_passes_original_digest_to_legacy_compatible_source_resolver(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
    monkeypatch: pytest.MonkeyPatch,
    matching: bool,
) -> None:
    from app.ai.application_gateway import ApplicationModelGateway
    from app.ai.budget_ledger import BudgetLedgerError

    engine, context, row, _ = setup
    engine.connection.row = None
    engine.connection.creation_lookup = True
    expected = "e" * 64
    calls: list[str] = []

    def resolve(
        c: Any,
        current: AuthContext,
        space: UUID,
        selection: ProductWorkSelection,
        expected_digest: str,
    ) -> dict[str, Any]:
        assert c is engine.connection and engine.connection.in_transaction
        assert current is context and space == SPACE
        assert selection.model_dump(mode="json") == row["run_context"]["product_work_selection"]
        calls.append(expected_digest)
        return {"digest": expected if matching else "d" * 64}

    monkeypatch.setattr(runs, "require_live_key", lambda _key: None)
    monkeypatch.setattr(runs, "source_for_request", resolve)
    request = runs.Request.model_validate(
        {
            "request_id": RUN,
            "expected_digest": expected,
            "selection": row["run_context"]["product_work_selection"],
        }
    )
    service = runs.ProductWorkRuns(
        cast(Engine, engine), gateway=cast(ApplicationModelGateway, SimpleNamespace())
    )
    # A matching legacy digest advances only to the existing queue-budget guard;
    # mismatch stops earlier. Neither case permits a model or run creation here.
    with pytest.raises(
        BudgetLedgerError if matching else ProductWorkError,
        match="APPLICATION_QUEUE_BUDGET_REQUIRED" if matching else "分析资料已有变化",
    ):
        service.create(context=context, space_id=SPACE, request=request)
    assert calls == [expected] and len(engine.connection.statements) == 1


def test_explicit_capability_history_remains_compatible(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
) -> None:
    engine, context, _, _ = setup
    result = runs.ProductWorkRuns.list_results(
        cast(Engine, engine),
        context=context,
        space_id=SPACE,
        capability="rfq_requirements",
        product_line_id=LINE,
        run_id=RUN,
    )
    assert result["items"][0]["selection"]["capability"] == "rfq_requirements"
    params = cast(ClauseElement, engine.connection.statements[0]).compile().params
    assert params is not None and "rfq_requirements" in params.values()
    assert str(LINE) in params.values()


def test_mixed_legacy_and_scoped_private_snapshots_are_both_current(
    setup: tuple[ReadEngine, AuthContext, dict[str, Any], list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.ai import product_work_preparation as preparation
    from app.domain.conversation_attachments import PARSER_VERSION, ConversationAttachmentService
    from app.domain.conversations import ConversationService

    engine, context, template, _ = setup
    conversation_id = UUID(int=20)
    conversation = dict(
        id=conversation_id,
        scope_kind="product_line",
        visibility="private",
        created_by_user_id=ACTOR,
        market_space_id=SPACE,
        product_line_id=LINE,
        project_id=None,
    )
    attachment = dict(
        id=FILE,
        status="extracted",
        revoked_at=None,
        classification="internal",
        parser_version=PARSER_VERSION,
        media_type="application/pdf",
        sha256="a" * 64,
        filename="same-facts.pdf",
        fragments=[dict(ordinal=1, locator="page:1", text="同一原文")],
    )
    selection = ProductWorkSelection.model_validate(
        {
            "capability": "rfq_requirements",
            "product_line_id": LINE,
            "question": "同一原文",
            "sources": [
                {
                    "kind": "private_attachment",
                    "conversation_id": conversation_id,
                    "id": FILE,
                    "ordinals": [1],
                }
            ],
        }
    )
    monkeypatch.setattr(
        preparation,
        "authorize",
        lambda *args: dict(
            title="市场",
            user_groups=[],
            regions=[],
            use_scenarios=[],
            research_questions=[],
        ),
    )
    monkeypatch.setattr(preparation, "resolve_evidence", lambda *args: [])
    monkeypatch.setattr(ConversationService, "_conversation", lambda *args: conversation)
    monkeypatch.setattr(ConversationAttachmentService, "_row", lambda *args: attachment)
    monkeypatch.setattr(work_context, "source_state", preparation.source_state)
    monkeypatch.setattr(work_context, "actor", lambda *args: context)
    rebuilds: list[str] = []

    def actual_rebuild(c: Any, tenant: UUID, snapshot: dict[str, Any]) -> dict[str, Any]:
        rebuilds.append(snapshot.get("private_attachment_link_version", "legacy"))
        return work_context.rebuild(c, tenant, snapshot)

    monkeypatch.setattr(runs, "rebuild", actual_rebuild)
    snapshots = [
        preparation.source_state(
            cast(Any, engine.connection),
            context,
            SPACE,
            selection,
            private_link_version=version,
        )
        for version in ("legacy", "scope.v1")
    ]
    assert snapshots[0]["selection"] == snapshots[1]["selection"]
    assert snapshots[0]["digest"] != snapshots[1]["digest"]
    values: list[dict[str, Any]] = []
    for index, snapshot in enumerate(snapshots):
        row = deepcopy(template)
        row["id"] = UUID(int=30 + index)
        row["run_context"].update(
            product_work_selection=selection.model_dump(mode="json"),
            product_work_source=snapshot,
            product_work_expected_digest=snapshot["digest"],
        )
        values.append(row)

    class MultipleResults(Result):
        def all(self) -> list[dict[str, Any]]:
            return values

    original_execute = engine.connection.execute

    def execute(statement: Executable) -> Result:
        original_execute(statement)  # Retain actual SQL predicate/transaction assertions.
        return MultipleResults(values[0])

    monkeypatch.setattr(engine.connection, "execute", execute)
    before = deepcopy(values)
    result = runs.ProductWorkRuns.list_results(
        cast(Engine, engine),
        context=context,
        space_id=SPACE,
        capability="rfq_requirements",
        product_line_id=LINE,
    )
    assert [item["sources_current"] for item in result["items"]] == [True, True]
    assert rebuilds == ["legacy", "scope.v1"]
    assert values == before
    assert engine.connects == 1 and engine.connection.begins == 1
