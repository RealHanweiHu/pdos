"""Real source-pack links at doubled authority/storage boundaries; no database or model."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from sqlalchemy import Connection

from app.ai import product_work_context as work_context
from app.ai import product_work_preparation as preparation
from app.auth.repository import AuthContext
from app.contracts.product_work_ai import ProductWorkSelection
from app.domain.conversation_attachments import PARSER_VERSION, ConversationAttachmentService
from app.domain.conversations import ConversationService
from app.domain.product_workspace import ProductWorkAccessError, digest

TENANT, USER, SPACE, LINE, CONVERSATION, ATTACHMENT = [UUID(int=i) for i in range(1, 7)]


class Boundary:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, line: UUID | None = LINE) -> None:
        self.line = line
        self.context = cast(
            AuthContext,
            SimpleNamespace(
                tenant=SimpleNamespace(id=TENANT),
                user=SimpleNamespace(id=USER),
            ),
        )
        self.connection = cast(Connection, SimpleNamespace(engine=object()))
        self.conversation = {
            "id": CONVERSATION,
            "created_by_user_id": USER,
            "visibility": "private",
            "scope_kind": "product_line" if line else "market_space",
            "market_space_id": SPACE,
            "product_line_id": line,
        }
        self.row = {
            "id": ATTACHMENT,
            "status": "extracted",
            "revoked_at": None,
            "classification": "internal",
            "parser_version": PARSER_VERSION,
            "media_type": "application/pdf",
            "sha256": "a" * 64,
            "filename": "合成.pdf",
            "fragments": [
                {"ordinal": i, "locator": f"page:{i}", "text": f"原文片段{i}"} for i in range(1, 5)
            ],
        }
        self.attachment_reads = 0

        def authorize(
            _c: Connection, context: AuthContext, space: UUID, selected_line: UUID | None
        ) -> dict[str, Any]:
            assert context is self.context and space == SPACE and selected_line == self.line
            return {
                "title": "合成空间",
                "user_groups": [],
                "regions": [],
                "use_scenarios": [],
                "research_questions": [],
            }

        def conversation(
            _service: Any, _c: Connection, context: AuthContext, identity: UUID
        ) -> dict[str, Any]:
            assert context is self.context
            if identity != CONVERSATION:
                raise ProductWorkAccessError("未授权私人会话")
            return self.conversation

        def attachment(_c: Connection, tenant: UUID, cid: UUID, aid: UUID) -> dict[str, Any]:
            self.attachment_reads += 1
            assert tenant == TENANT and cid == CONVERSATION and aid == ATTACHMENT
            return self.row

        monkeypatch.setattr(preparation, "authorize", authorize)
        monkeypatch.setattr(ConversationService, "_conversation", conversation)
        monkeypatch.setattr(ConversationAttachmentService, "_row", staticmethod(attachment))
        monkeypatch.setattr(preparation, "resolve_evidence", lambda *_args: [])

    def selection(self, cid: UUID = CONVERSATION, ordinal: int = 4) -> ProductWorkSelection:
        return ProductWorkSelection.model_validate(
            {
                "capability": "research_planning",
                "question": "核对原件",
                "product_line_id": self.line,
                "sources": [
                    {
                        "kind": "private_attachment",
                        "conversation_id": cid,
                        "id": ATTACHMENT,
                        "ordinals": [ordinal],
                    }
                ],
            }
        )

    def snapshot(self, cid: UUID = CONVERSATION) -> dict[str, Any]:
        return preparation.source_state(self.connection, self.context, SPACE, self.selection(cid))


@pytest.mark.parametrize("line", [LINE, None])
def test_links_roundtrip_verified_space_line_and_fourth_selected_fragment(
    monkeypatch: pytest.MonkeyPatch,
    line: UUID | None,
) -> None:
    boundary = Boundary(monkeypatch, line)
    snapshot = boundary.snapshot()
    private = next(
        ref for ref in snapshot["references"] if ref["reference_id"].startswith("attachment:")
    )
    query = parse_qs(urlsplit(private["href"]).query)
    assert query["conversation"] == [str(CONVERSATION)]
    assert query["attachment"] == [str(ATTACHMENT)] and query["fragment"] == ["4"]
    source = urlsplit(query["source"][0])
    assert source.path == "/product-work"
    scope = parse_qs(source.query)
    assert scope["space"] == [str(SPACE)] and scope["tab"] == ["research"]
    assert scope.get("line") == ([str(line)] if line else None)
    assert private["reference_id"] == f"attachment:{ATTACHMENT}:fragment:4"
    assert private["fields"]["text"] == "原文片段4"
    assert private["fields"]["taint"] == "untrusted_external"
    assert private["fields"]["coverage"] == "selected_fragments_only"
    assert private["digest"] == digest(private["fields"])
    assert boundary.attachment_reads == 1


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("market_space_id", UUID(int=99)),
        ("product_line_id", UUID(int=99)),
        ("scope_kind", "personal"),
        ("created_by_user_id", UUID(int=99)),
    ],
)
def test_actual_conversation_mismatch_rejects_before_attachment_read(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: Any,
) -> None:
    boundary = Boundary(monkeypatch)
    boundary.conversation[field] = replacement
    with pytest.raises(ProductWorkAccessError):
        boundary.snapshot()
    assert boundary.attachment_reads == 0


def test_malicious_conversation_id_rejects_before_attachment_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = Boundary(monkeypatch)
    with pytest.raises(ProductWorkAccessError, match="未授权"):
        boundary.snapshot(UUID(int=99))
    assert boundary.attachment_reads == 0


def test_current_link_change_changes_pack_digest_without_rewriting_frozen_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = Boundary(monkeypatch)
    current = boundary.snapshot()
    previous = deepcopy(current)
    old_ref = next(
        ref for ref in previous["references"] if ref["reference_id"].startswith("attachment:")
    )
    old_ref["href"] = f"/ask?conversation={CONVERSATION}&attachment={ATTACHMENT}&fragment=4"
    previous.pop("digest")
    previous.pop("private_attachment_link_version")
    previous["digest"] = digest(previous)
    frozen = deepcopy(previous)
    refreshed = boundary.snapshot()
    new_ref = next(
        ref for ref in refreshed["references"] if ref["reference_id"].startswith("attachment:")
    )
    assert new_ref["fields"] == old_ref["fields"] and new_ref["digest"] == old_ref["digest"]
    assert refreshed["digest"] != previous["digest"]
    assert previous == frozen


@pytest.mark.parametrize("version", ["legacy", "scope.v1"])
def test_rebuild_preserves_frozen_link_version_and_detects_changed_facts(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    boundary = Boundary(monkeypatch)
    monkeypatch.setattr(work_context, "actor", lambda *_args: boundary.context)
    snapshot = preparation.source_state(
        boundary.connection,
        boundary.context,
        SPACE,
        boundary.selection(),
        private_link_version=version,
    )
    frozen = deepcopy(snapshot)
    assert ("private_attachment_link_version" in snapshot) == (version == "scope.v1")
    assert work_context.rebuild(boundary.connection, TENANT, snapshot) == snapshot
    cast(list[dict[str, Any]], boundary.row["fragments"])[3]["text"] = "发生变化的原文片段"
    refreshed = work_context.rebuild(boundary.connection, TENANT, snapshot)
    assert refreshed["digest"] != snapshot["digest"]
    assert refreshed["references"][-1]["digest"] != snapshot["references"][-1]["digest"]
    assert snapshot == frozen


def test_pack_without_private_sources_retains_original_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = Boundary(monkeypatch)
    selection = boundary.selection().model_copy(update={"sources": []})
    current = preparation.source_state(boundary.connection, boundary.context, SPACE, selection)
    legacy = preparation.source_state(
        boundary.connection,
        boundary.context,
        SPACE,
        selection,
        private_link_version="legacy",
    )
    assert current == legacy
    assert "private_attachment_link_version" not in current


@pytest.mark.parametrize("version", ["legacy", "scope.v1"])
def test_saved_request_selects_only_exact_actual_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    boundary = Boundary(monkeypatch)
    saved = preparation.source_state(
        boundary.connection,
        boundary.context,
        SPACE,
        boundary.selection(),
        private_link_version=version,
    )
    frozen = deepcopy(saved)
    resolved = preparation.source_for_request(
        boundary.connection,
        boundary.context,
        SPACE,
        boundary.selection(),
        saved["digest"],
    )
    assert resolved == saved
    cast(list[dict[str, Any]], boundary.row["fragments"])[3]["text"] = "实际原文已变更"
    current = boundary.snapshot()
    legacy = preparation.source_state(
        boundary.connection,
        boundary.context,
        SPACE,
        boundary.selection(),
        private_link_version="legacy",
    )
    assert saved["digest"] not in (current["digest"], legacy["digest"])
    assert (
        preparation.source_for_request(
            boundary.connection,
            boundary.context,
            SPACE,
            boundary.selection(),
            saved["digest"],
        )
        == current
    )
    assert saved == frozen
