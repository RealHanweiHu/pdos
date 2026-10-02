"""Real typed conversation adapter at SQL boundaries; no database/gateway fixtures."""

from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection as SQLConnection
from sqlalchemy import Engine
from sqlalchemy.sql import Executable, Insert, Update

from app.auth.repository import AuthContext
from app.contracts.product_work_ai import ProductWorkSelection
from app.domain import conversation_product_work as adapter
from app.domain.conversations import ConversationError, ConversationService
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, digest

TENANT, USER, SPACE, LINE, CONVERSATION, REQUEST, RUN = [UUID(int=i) for i in range(1, 8)]


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def mappings(self) -> "Result":
        return self

    def one_or_none(self) -> Any:
        return self.value

    def one(self) -> Any:
        return self.value


class Connection:
    def __init__(self, conversation: dict[str, Any]) -> None:
        self.conversation = conversation
        self.message: dict[str, Any] | None = None
        self.run: dict[str, Any] | None = None
        self.writes = 0
        self.reads: list[Executable] = []

    def execute(self, statement: Executable) -> Result:
        if isinstance(statement, Insert):
            self.writes += 1
            self.message = dict(statement.compile().params)
            return Result(self.message)
        if isinstance(statement, Update):
            self.writes += 1
            return Result(None)
        self.reads.append(statement)
        sql = str(statement)
        if "FROM cehub_project.conversations" in sql or "FROM cehub_core.conversations" in sql:
            return Result(self.conversation)
        if "FROM" in sql and "conversation_messages" in sql:
            return Result(self.message)
        if "agent_runs" in sql:
            return Result(self.run)
        if "conversations" in sql:
            return Result(self.conversation)
        raise AssertionError(sql)

    def execution_options(self, **kwargs: Any) -> "Connection":
        return self

    def begin(self) -> Any:
        return nullcontext(self)

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class FakeEngine:
    def __init__(self, c: Connection) -> None:
        self.connection = c

    def connect(self) -> Connection:
        return self.connection


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.context = cast(
            AuthContext,
            SimpleNamespace(
                tenant=SimpleNamespace(id=TENANT),
                user=SimpleNamespace(id=USER, role="engineer", auth_version=1),
            ),
        )
        self.current = self.context
        self.conversation: dict[str, Any] = dict(
            id=CONVERSATION,
            tenant_id=TENANT,
            created_by_user_id=USER,
            scope_kind="product_line",
            project_id=None,
            meeting_id=None,
            market_space_id=SPACE,
            product_line_id=LINE,
            visibility="private",
            context_version=1,
            next_sequence=1,
            archived_at=None,
        )
        self.c = Connection(self.conversation)
        self.source_marker = "original"
        self.source_calls: list[dict[str, Any]] = []
        self.readable_calls: list[dict[str, Any]] = []
        monkeypatch.setattr(adapter, "actor", lambda *args: self.current)
        monkeypatch.setattr(adapter, "authorize", lambda *args: None)
        monkeypatch.setattr(adapter, "source_state", self.source)
        monkeypatch.setattr(
            adapter, "readable", lambda c, context, snapshot: self.readable_calls.append(snapshot)
        )
        from app.domain import conversation_attachments

        monkeypatch.setattr(conversation_attachments, "bind_attachments", lambda *args: None)
        self.service = ConversationService(cast(Engine, FakeEngine(self.c)))

    def source(
        self, c: SQLConnection, context: AuthContext, space: UUID, selection: Any
    ) -> dict[str, Any]:
        selected = selection.model_dump(mode="json")
        self.source_calls.append(selected)
        value = dict(
            actor_id=str(USER),
            market_space_id=str(space),
            selection=selected,
            references=[],
            warnings=[self.source_marker],
            coverage_limits=[],
        )
        return {**value, "digest": digest(value)}

    def save(self, **changes: Any) -> dict[str, Any]:
        values: dict[str, Any] = dict(
            context=self.context,
            conversation_id=CONVERSATION,
            request_id=REQUEST,
            expected_context_version=1,
            body="请准备竞品分析",
            action="note",
            product_sources=[dict(kind="product", id=str(UUID(int=20)))],
        )
        values.update(changes)
        return self.service.save_message(**values)

    def run_row(self) -> dict[str, Any]:
        assert self.c.message is not None
        fixed = self.c.message["product_work_request"]
        source = self.source(
            cast(SQLConnection, self.c),
            self.context,
            SPACE,
            ProductWorkSelection.model_validate(fixed["selection"]),
        )
        return dict(
            id=RUN,
            tenant_id=TENANT,
            request_id=self.c.message["operation_request_id"],
            scope_kind="market_space",
            project_id=None,
            market_space_id=SPACE,
            requested_by_user_id=USER,
            agent_key="product_management_intelligence",
            context_version="product-work-request-v1",
            run_context=dict(
                product_work_selection=fixed["selection"],
                product_work_expected_digest=fixed["expected_digest"],
                product_work_user_instruction=fixed["user_instruction"],
                product_work_source=source,
            ),
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


@pytest.mark.parametrize(
    "scope",
    [
        dict(scope_kind="project", project_id=SPACE),
        dict(scope_kind="personal"),
        dict(scope_kind="market_space", market_space_id=SPACE),
        dict(scope_kind="product_line", market_space_id=SPACE, product_line_id=LINE),
    ],
)
def test_four_real_scope_shapes(scope: dict[str, Any]) -> None:
    assert adapter.ConversationScope.model_validate(scope).scope_kind == scope["scope_kind"]


@pytest.mark.parametrize(
    "scope",
    [
        dict(scope_kind="project"),
        dict(scope_kind="personal", project_id=SPACE),
        dict(scope_kind="personal", market_space_id=SPACE),
        dict(scope_kind="market_space", market_space_id=SPACE, product_line_id=LINE),
        dict(scope_kind="product_line", product_line_id=LINE),
        dict(
            scope_kind="product_line",
            market_space_id=SPACE,
            product_line_id=LINE,
            visibility="project",
        ),
        dict(scope_kind="personal", meeting_id=SPACE),
        dict(scope_kind="personal", tenant_id=TENANT),
    ],
)
def test_invalid_mixed_scope_cannot_create_contract(scope: dict[str, Any]) -> None:
    with pytest.raises((ConversationError, ValidationError)):
        adapter.ConversationScope.model_validate(scope)


@pytest.mark.parametrize("body", ["做竞品和市场分析", "请帮忙", "产品策略"])
def test_ambiguous_or_missing_line_saves_guidance_without_model(
    harness: Harness, body: str
) -> None:
    harness.conversation.update(scope_kind="market_space", product_line_id=None)
    value = harness.save(body=body)
    assert value["action"] == "note" and value["product_work_request"] is None and value["guidance"]
    assert harness.source_calls == [] and harness.service.gateway is None


def test_personal_notes_do_not_invent_market_or_project(harness: Harness) -> None:
    harness.conversation.update(scope_kind="personal", market_space_id=None, product_line_id=None)
    value = harness.save(product_sources=[])
    assert (
        value["action"] == "note"
        and value["project_id"] is None
        and value["product_work_request"] is None
    )
    assert harness.source_calls == []
    with pytest.raises(ConversationError):
        harness.save(request_id=UUID(int=99))


@pytest.mark.parametrize(
    "change", [dict(role="quality"), dict(auth_version=2), dict(role="supplier")]
)
def test_current_identity_revocation_precedes_new_save_and_replay(
    harness: Harness, change: dict[str, Any]
) -> None:
    harness.save()
    before = deepcopy(harness.c.message)
    writes = harness.c.writes
    current = SimpleNamespace(id=USER, role="engineer", auth_version=1)
    for key, value in change.items():
        setattr(current, key, value)
    harness.current = cast(
        AuthContext, SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=current)
    )
    for request in (REQUEST, UUID(int=99)):
        with pytest.raises(ProductWorkAccessError):
            harness.save(request_id=request)
    assert harness.c.message == before and harness.c.writes == writes


def test_note_is_server_routed_fixed_sources_no_gateway_and_replay_keeps_digest(
    harness: Harness,
) -> None:
    first = harness.save()
    assert first["action"] == "product_work" and first["project_id"] is None
    assert first["product_work_request"]["selection"]["sources"] == [
        dict(kind="product", id=str(UUID(int=20)))
    ]
    writes = harness.c.writes
    harness.source_marker = "current sources changed"
    second = harness.save()
    assert second == first and harness.c.writes == writes
    assert len(harness.source_calls) == 2
    assert harness.service.gateway is None
    with pytest.raises(ConversationError):
        harness.save(body="请准备另一轮竞品分析")
    with pytest.raises(ConversationError):
        harness.save(product_sources=[dict(kind="product", id=str(UUID(int=99)))])
    assert harness.c.writes == writes


def _private_selection(ordinal: int = 4, **changes: Any) -> dict[str, Any]:
    return {
        "kind": "private_attachment",
        "conversation_id": str(CONVERSATION),
        "id": str(UUID(int=30)),
        "ordinals": [ordinal],
        **changes,
    }


@pytest.mark.parametrize("selections", [None, []])
def test_whole_attachment_never_silently_selects_first_three_fragments(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, selections: Any
) -> None:
    from app.domain.conversation_attachments import ConversationAttachmentService

    def no_fragments(*args: Any) -> None:
        raise AssertionError("A whole-file note must not read fragment content")

    monkeypatch.setattr(ConversationAttachmentService, "_row", no_fragments)
    saved = harness.save(
        body="客户需求抽取",
        attachment_ids=(UUID(int=30),),
        product_sources=[],
        attachment_selections=selections,
    )
    assert saved["action"] == "note" and saved["product_work_request"] is None
    assert "明确选择" in saved["guidance"] and not harness.source_calls
    assert harness.service.gateway is None
    assert (
        harness.save(
            body="客户需求抽取",
            attachment_ids=(UUID(int=30),),
            product_sources=[],
            attachment_selections=selections,
        )
        == saved
    )
    assert (
        adapter.guidance_for("客户需求抽取", harness.conversation, attachment_ids=(UUID(int=30),))
        == saved["guidance"]
    )


def test_explicit_fourth_fragment_is_fixed_and_original_retry_cannot_change_it(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.conversation_attachments import ConversationAttachmentService

    attachment = dict(
        status="extracted",
        revoked_at=None,
        classification="internal",
        fragments=[dict(ordinal=i, text=f"实际原文第{i}段") for i in range(1, 5)],
    )
    reads: list[tuple[Any, ...]] = []

    def actual_row(*args: Any) -> dict[str, Any]:
        reads.append(args)
        return attachment

    monkeypatch.setattr(ConversationAttachmentService, "_row", actual_row)
    body: dict[str, Any] = dict(
        body="客户需求抽取",
        attachment_ids=(UUID(int=30),),
        product_sources=[],
        attachment_selections=[_private_selection()],
    )
    first = harness.save(**body)
    frozen = deepcopy(first["product_work_request"])
    assert first["action"] == "product_work"
    assert frozen["selection"]["sources"] == [_private_selection()]
    assert reads[0][1:] == (TENANT, CONVERSATION, UUID(int=30))
    assert harness.source_calls[0]["sources"] == [_private_selection()]
    writes = harness.c.writes
    harness.source_marker = "source facts changed"
    assert harness.save(**body)["product_work_request"] == frozen
    with pytest.raises(ConversationError):
        harness.save(**{**body, "attachment_selections": [_private_selection(1)]})
    assert harness.c.writes == writes and harness.service.gateway is None


@pytest.mark.parametrize(
    "changes",
    [
        dict(status="awaiting_upload"),
        dict(revoked_at="2026-09-30"),
        dict(classification="confidential"),
        dict(classification="restricted"),
        dict(fragments=[dict(ordinal=1, text="只有第一段")]),
        dict(fragments=[dict(ordinal=4, text=" ")]),
    ],
)
def test_selected_private_fragment_is_checked_before_any_message_write(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    from app.domain.conversation_attachments import ConversationAttachmentService

    row = (
        dict(
            status="extracted",
            revoked_at=None,
            classification="internal",
            fragments=[dict(ordinal=4, text="实际第四段")],
        )
        | changes
    )
    monkeypatch.setattr(ConversationAttachmentService, "_row", lambda *args: row)
    with pytest.raises(ConversationError):
        harness.save(
            body="客户需求抽取",
            attachment_ids=(UUID(int=30),),
            product_sources=[],
            attachment_selections=[_private_selection()],
        )
    assert harness.c.writes == 0 and not harness.source_calls


@pytest.mark.parametrize(
    "selections,attachments",
    [
        ([_private_selection(conversation_id=str(UUID(int=99)))], (UUID(int=30),)),
        ([_private_selection(id=str(UUID(int=99)))], (UUID(int=30),)),
        ([_private_selection(), _private_selection()], (UUID(int=30),)),
        ([_private_selection()], (UUID(int=30), UUID(int=30))),
    ],
)
def test_private_selection_cannot_smuggle_other_conversation_or_unbound_attachment(
    harness: Harness, selections: Any, attachments: tuple[UUID, ...]
) -> None:
    with pytest.raises(ConversationError):
        harness.save(
            body="客户需求抽取",
            attachment_ids=attachments,
            product_sources=[],
            attachment_selections=selections,
        )
    assert harness.c.writes == 0 and not harness.source_calls


def test_partial_private_selection_saves_note_instead_of_analyzing_a_subset(
    harness: Harness,
) -> None:
    saved = harness.save(
        body="客户需求抽取",
        product_sources=[],
        attachment_ids=(UUID(int=30), UUID(int=31)),
        attachment_selections=[_private_selection()],
    )
    assert saved["action"] == "note" and saved["product_work_request"] is None
    assert saved["guidance"] and not harness.source_calls


def test_missing_selection_field_retains_the_original_0412_signature(harness: Harness) -> None:
    from app.domain.product_workspace import _plain

    saved = harness.save()
    assert saved["request_digest"] == digest(
        _plain(
            dict(
                body="请准备竞品分析",
                context_version=1,
                attachment_ids=(),
                product_sources=[dict(kind="product", id=str(UUID(int=20)))],
            )
        )
    )
    with pytest.raises(ConversationError):
        harness.save(attachment_selections=[])


@pytest.mark.parametrize("ordinals", [[], [0], [4, 4], list(range(1, 22))])
def test_message_api_accepts_only_explicit_unique_positive_fragment_ordinals(
    ordinals: list[int],
) -> None:
    from app.api.conversations import MessageCreate

    with pytest.raises(ValidationError):
        MessageCreate.model_validate(
            dict(
                request_id=str(REQUEST),
                expected_context_version=1,
                body="客户需求抽取",
                attachment_ids=[str(UUID(int=30))],
                attachment_selections=[_private_selection(ordinals=ordinals)],
            )
        )


def test_run_matches_saved_request_and_revalidates_readable(harness: Harness) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    row = adapter.product_run(
        cast(SQLConnection, harness.c), harness.context, harness.conversation, harness.c.message
    )
    assert row is harness.c.run and harness.readable_calls == [
        row["run_context"]["product_work_source"]
    ]
    statement = cast(Any, harness.c.reads[-1]).compile()
    assert TENANT in statement.params.values()
    assert (
        harness.c.message is not None
        and harness.c.message["operation_request_id"] in statement.params.values()
    )
    assert (
        adapter.run_request(harness.c.message).expected_digest
        == harness.c.message["product_work_request"]["expected_digest"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope_kind", "project"),
        ("project_id", SPACE),
        ("market_space_id", UUID(int=99)),
        ("requested_by_user_id", UUID(int=99)),
        ("agent_key", "forged"),
        ("context_version", "forged"),
    ],
)
def test_forged_runtime_top_level_rejected(harness: Harness, field: str, value: Any) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    harness.c.run[field] = value
    with pytest.raises(ConversationError):
        adapter.product_run(
            cast(SQLConnection, harness.c), harness.context, harness.conversation, harness.c.message
        )
    assert harness.readable_calls == []


@pytest.mark.parametrize(
    "field",
    ["product_work_selection", "product_work_expected_digest", "product_work_user_instruction"],
)
def test_forged_runtime_fixed_input_rejected(harness: Harness, field: str) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    harness.c.run["run_context"][field] = {} if field == "product_work_selection" else "forged"
    with pytest.raises(ConversationError):
        adapter.product_run(
            cast(SQLConnection, harness.c), harness.context, harness.conversation, harness.c.message
        )


@pytest.mark.parametrize(
    "change",
    [
        dict(actor_id=str(UUID(int=99))),
        dict(market_space_id=str(UUID(int=99))),
        dict(
            selection=dict(
                capability="market_analysis",
                question="另一来源",
                product_line_id=str(LINE),
                sources=[],
            )
        ),
        dict(digest="f" * 64),
        dict(references=[dict(reference_id="forged", fields={})]),
    ],
)
def test_forged_runtime_source_snapshot_rejected(harness: Harness, change: dict[str, Any]) -> None:
    harness.save()
    harness.c.run = harness.run_row()
    harness.c.run["run_context"]["product_work_source"].update(change)
    with pytest.raises(ConversationError):
        adapter.product_run(
            cast(SQLConnection, harness.c), harness.context, harness.conversation, harness.c.message
        )
    assert harness.readable_calls == []


def test_historical_run_current_source_revocation_propagates(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.save()
    harness.c.run = harness.run_row()

    def denied(*args: Any) -> None:
        raise ProductWorkAccessError("来源当前撤回")

    monkeypatch.setattr(adapter, "readable", denied)
    with pytest.raises(ProductWorkAccessError):
        adapter.product_run(
            cast(SQLConnection, harness.c), harness.context, harness.conversation, harness.c.message
        )


@pytest.mark.parametrize(
    "reference_id,field",
    [
        (f"attachment:{CONVERSATION}:fragment:1", "text"),
        ("attachment:" + "-" * 36 + ":fragment:1", "text"),
        (f"attachment:{CONVERSATION}:fragment:0", "text"),
        (f"attachment:{CONVERSATION}:fragment:1", "sha256"),
    ],
)
def test_rfq_attachment_reference_requires_real_id_positive_fragment_text(
    reference_id: str, field: str
) -> None:
    from app.contracts.product_rfq_ai import RfqRequirement

    body = dict(
        title="需求",
        description="原需求",
        priority="medium",
        acceptance_criteria=[],
        missing=["待确认"],
        basis=dict(
            text="原需求",
            nature="observed",
            citations=[
                dict(
                    reference_id=reference_id,
                    digest="a" * 64,
                    field_path=[field],
                    quoted_value="原需求",
                )
            ],
        ),
    )
    if reference_id == f"attachment:{CONVERSATION}:fragment:1" and field == "text":
        assert RfqRequirement.model_validate(body).basis.citations[0].quoted_value == "原需求"
    else:
        with pytest.raises(ValidationError):
            RfqRequirement.model_validate(body)


@pytest.mark.parametrize("forgery", ["quote", "digest", "reference"])
def test_rfq_private_fragment_citation_validates_actual_text_and_fixed_digest(forgery: str) -> None:
    from app.ai.product_work_context import validate_statements
    from app.contracts.change_work_package import Statement

    reference_id = f"attachment:{CONVERSATION}:fragment:1"
    refs = {reference_id: dict(digest="a" * 64, fields={"text": "实际客户原文"})}
    payload: dict[str, Any] = dict(
        text="提取需求",
        nature="observed",
        citations=[
            dict(
                reference_id=reference_id,
                digest="a" * 64,
                field_path=["text"],
                quoted_value="实际客户原文",
            )
        ],
    )
    validate_statements([Statement.model_validate(payload)], refs)
    citation = payload["citations"][0]
    if forgery == "quote":
        citation["quoted_value"] = "模型补出的要求"
    elif forgery == "digest":
        citation["digest"] = "b" * 64
    else:
        citation["reference_id"] = f"attachment:{SPACE}:fragment:1"
    with pytest.raises(ProductWorkError):
        validate_statements([Statement.model_validate(payload)], refs)


def test_unstarted_product_run_revalidates_fixed_selection_without_dispatch(
    harness: Harness,
) -> None:
    harness.save()
    calls = len(harness.source_calls)
    assert (
        adapter.product_run(
            cast(SQLConnection, harness.c), harness.context, harness.conversation, harness.c.message
        )
        is None
    )
    assert len(harness.source_calls) == calls + 1 and harness.service.gateway is None
