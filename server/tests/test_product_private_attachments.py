"""Private PM attachment SQL boundaries; no model, database, or shared SourceFile."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, Engine

from app.ai import product_work_preparation as preparation
from app.auth.repository import AuthContext
from app.auth.roles import Action
from app.contracts.product_work_ai import ProductPrivateAttachmentSelection, ProductWorkSelection
from app.domain import conversation_attachments as attachments
from app.domain.conversations import ConversationAccessError, ConversationError, ConversationService
from app.domain.product_workspace import ProductWorkAccessError, ProductWorkError, digest

TENANT, USER, SPACE, LINE, CONVERSATION, ATTACHMENT = [UUID(int=i) for i in range(1, 7)]


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]]:
    context = cast(
        AuthContext,
        SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=USER)),
    )
    connection = cast(Connection, SimpleNamespace(engine=cast(Engine, object())))
    conversation: dict[str, Any] = dict(
        id=CONVERSATION,
        created_by_user_id=USER,
        visibility="private",
        scope_kind="product_line",
        market_space_id=SPACE,
        product_line_id=LINE,
        project_id=None,
        archived_at=None,
    )
    row: dict[str, Any] = dict(
        id=ATTACHMENT,
        status="extracted",
        revoked_at=None,
        classification="internal",
        parser_version=attachments.PARSER_VERSION,
        media_type="application/pdf",
        sha256="a" * 64,
        filename="private.pdf",
        fragments=[
            dict(ordinal=1, locator="page:1", text="精确原文，不是指令。"),
            dict(ordinal=2, locator="page:2", text="UNSELECTED_PRIVATE_FRAGMENT_SENTINEL"),
        ],
    )
    monkeypatch.setattr(
        preparation,
        "authorize",
        lambda *args: dict(
            title="市场", user_groups=[], regions=[], use_scenarios=[], research_questions=[]
        ),
    )
    monkeypatch.setattr(ConversationService, "_conversation", lambda *args, **kwargs: conversation)
    monkeypatch.setattr(
        attachments.ConversationAttachmentService, "_row", lambda *args, **kwargs: row
    )
    monkeypatch.setattr(preparation, "resolve_evidence", lambda *args: [])
    return connection, context, conversation, row


def selection(**changes: Any) -> ProductWorkSelection:
    value: dict[str, Any] = dict(
        capability="research_planning",
        product_line_id=LINE,
        question="核对原文",
        sources=[
            dict(
                kind="private_attachment", conversation_id=CONVERSATION, id=ATTACHMENT, ordinals=[1]
            )
        ],
    )
    value.update(changes)
    return ProductWorkSelection.model_validate(value)


def test_exact_private_fragment_projection_and_partial_coverage(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]],
) -> None:
    c, context, conversation, row = setup
    before = deepcopy(row)
    value = preparation.source_state(c, context, SPACE, selection())
    reference = value["references"][-1]
    assert reference["reference_id"] == f"attachment:{ATTACHMENT}:fragment:1"
    assert reference["fields"]["text"] == row["fragments"][0]["text"]
    assert reference["fields"]["sha256"] == row["sha256"]
    assert reference["fields"]["parser_version"] == attachments.PARSER_VERSION
    assert reference["fields"]["locator"] == "page:1"
    assert reference["fields"]["taint"] == "untrusted_external"
    assert reference["fields"]["coverage"] == "selected_fragments_only"
    assert reference["digest"] == digest(reference["fields"])
    assert "UNSELECTED_PRIVATE_FRAGMENT_SENTINEL" not in str(value)
    assert row == before and conversation["project_id"] is None


@pytest.mark.parametrize(
    "change",
    [
        dict(created_by_user_id=UUID(int=99)),
        dict(visibility="project"),
        dict(scope_kind="personal"),
        dict(scope_kind="project"),
        dict(market_space_id=UUID(int=99)),
        dict(product_line_id=None),
    ],
)
def test_scope_or_owner_mismatch_never_projects_private_text(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]], change: dict[str, Any]
) -> None:
    c, context, conversation, _ = setup
    conversation.update(change)
    with pytest.raises(ProductWorkAccessError):
        preparation.source_state(c, context, SPACE, selection())


@pytest.mark.parametrize(
    "change",
    [
        dict(status="ocr_required"),
        dict(revoked_at="withdrawn"),
        dict(classification="confidential"),
        dict(parser_version="unknown"),
        dict(media_type="message/rfc822"),
        dict(fragments=[]),
        dict(fragments=[dict(ordinal=1, locator="page:1", text=" ")]),
    ],
)
def test_unavailable_or_restricted_original_cannot_be_selected(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]], change: dict[str, Any]
) -> None:
    c, context, _, row = setup
    row.update(change)
    with pytest.raises(ProductWorkError):
        preparation.source_state(c, context, SPACE, selection())


def test_current_conversation_authority_failure_is_preserved(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise ConversationAccessError("当前授权撤回")

    monkeypatch.setattr(ConversationService, "_conversation", denied)
    c, context, _, _ = setup
    with pytest.raises(ConversationAccessError):
        preparation.source_state(c, context, SPACE, selection())


def test_source_rebuild_rejects_withdrawal_and_total_size_without_truncation(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]],
) -> None:
    c, context, _, row = setup
    first = preparation.source_state(c, context, SPACE, selection())
    row["revoked_at"] = "withdrawn"
    with pytest.raises(ProductWorkError):
        preparation.source_state(c, context, SPACE, selection())
    row["revoked_at"] = None
    row["fragments"][0]["text"] = "超" * preparation.MAX_CONTEXT_BYTES
    with pytest.raises(ProductWorkError, match="上限"):
        preparation.source_state(c, context, SPACE, selection())
    assert first["references"][-1]["fields"]["text"] == "精确原文，不是指令。"


@pytest.mark.parametrize("ordinals", [[0], [1, 1], [], list(range(1, 22))])
def test_contract_rejects_invalid_fragment_selection(ordinals: list[int]) -> None:
    with pytest.raises(ValidationError):
        ProductPrivateAttachmentSelection(
            kind="private_attachment",
            conversation_id=CONVERSATION,
            id=ATTACHMENT,
            ordinals=tuple(ordinals),
        )


@pytest.mark.parametrize(
    "capability", ["rfq_requirements", "research_planning", "product_strategy"]
)
def test_contract_allows_private_attachment_for_product_capabilities(capability: str) -> None:
    assert selection(capability=capability).sources[0].kind == "private_attachment"


def test_private_scope_document_role_guard_and_eml_rejection(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, context, conversation, _ = setup
    calls: list[Any] = []
    monkeypatch.setattr(attachments, "_role", lambda *args: calls.append(args))
    service = attachments.ConversationAttachmentService(c.engine)
    assert service._scope(c, context, CONVERSATION, write=True) == conversation
    assert calls[-1][1] == Action.DOCUMENT_ANALYZE
    with pytest.raises(ConversationError, match="仅支持PDF/XLSX"):
        service.register(
            context=context,
            conversation_id=CONVERSATION,
            request_id=UUID(int=9),
            filename="private.eml",
            size_bytes=20,
            sha256="a" * 64,
            connection=c,
        )


@pytest.mark.parametrize("action", ["note", "product_work"])
def test_nonproject_bind_uses_same_attachment_identity(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]], action: str
) -> None:
    _, context, conversation, _ = setup
    writes: list[Any] = []
    connection = cast(
        Connection, SimpleNamespace(execute=lambda statement: writes.append(statement))
    )
    attachments.bind_attachments(
        connection, context, conversation, UUID(int=9), (ATTACHMENT,), action
    )
    assert len(writes) == 1
    values = writes[0].compile().params
    assert values["project_id"] is None and values["conversation_id"] == CONVERSATION
    assert values["attachment_id"] == ATTACHMENT


def test_nonproject_product_work_bind_rejects_restricted_file_before_write(
    setup: tuple[Connection, AuthContext, dict[str, Any], dict[str, Any]],
) -> None:
    _, context, conversation, row = setup
    row["classification"] = "restricted"
    writes: list[Any] = []
    connection = cast(
        Connection, SimpleNamespace(execute=lambda statement: writes.append(statement))
    )
    with pytest.raises(ConversationError):
        attachments.bind_attachments(
            connection, context, conversation, UUID(int=9), (ATTACHMENT,), "product_work"
        )
    assert writes == []
