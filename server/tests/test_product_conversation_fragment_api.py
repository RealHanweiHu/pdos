"""Queued isolated PostgreSQL/API cases; collection is not execution evidence.

Only object storage is synthetic. Upload, XLSX parsing, messages and fixed
source preparation use actual APIs. No qualification or model runs are seeded.
"""

from collections.abc import Callable
from hashlib import sha256 as hash_bytes
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.db.schema import tables
from app.main import app
from app.storage.documents import get_document_object_store
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_product_conversations_api import Candidate, colleague
from tests.test_product_conversations_api import candidate as candidate
from tests.test_test_runs_api import client as client
from tests.test_test_runs_api import isolated_test_run_database as isolated_test_run_database


class PrivateStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, *, object_key: str, content: bytes, media_type: str, sha256: str) -> None:
        assert hash_bytes(content).hexdigest() == sha256
        assert media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        self.objects[object_key] = content

    def get(self, *, object_key: str, max_bytes: int) -> bytes:
        value = self.objects[object_key]
        assert len(value) <= max_bytes
        return value

    def delete(self, *, object_key: str) -> None:
        self.objects.pop(object_key, None)


def upload(
    candidate: Candidate, conversation: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    overrides: dict[Callable[..., Any], Callable[..., Any]] = dict(app.dependency_overrides)
    store = PrivateStore()
    overrides[get_document_object_store] = lambda: store
    monkeypatch.setattr(app, "dependency_overrides", overrides)
    workbook = Workbook()
    active = workbook.active
    assert active is not None
    workbook.remove(active)
    # Separate actual sheets generate twelve distinct parser fragments.
    for ordinal in range(1, 13):
        workbook.create_sheet(f"Source{ordinal}").append(
            ["第四段120 kPa原要求" if ordinal == 4 else f"合成原要求{ordinal}"]
        )
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    content = output.getvalue()
    attachment = candidate.post(
        f"/api/conversations/{conversation['id']}/attachments",
        {
            "request_id": str(uuid4()),
            "filename": "synthetic-fragments.xlsx",
            "size_bytes": len(content),
            "sha256": hash_bytes(content).hexdigest(),
            "classification": "internal",
        },
    )
    base = f"/api/conversations/{conversation['id']}/attachments/{attachment['id']}"
    response = candidate.client.post(base + "/content", headers=candidate.headers, content=content)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "uploaded"
    parsed = candidate.post(base + "/parse", {})
    assert parsed["status"] == "extracted" and parsed["fragment_count"] == 12
    return parsed


def selected(
    conversation: dict[str, Any], attachment: dict[str, Any], ordinal: int = 4
) -> dict[str, Any]:
    return {
        "kind": "private_attachment",
        "conversation_id": conversation["id"],
        "id": attachment["id"],
        "ordinals": [ordinal],
    }


def untouched(candidate: Candidate) -> None:
    candidate.no_models_or_business_files()
    with candidate.scope.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(tables.agent_runs)
                .where(tables.agent_runs.c.tenant_id == candidate.scope.tenant_id)
            ).scalar_one()
            == 0
        )


def test_whole_file_without_fragments_saves_note_without_run(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = candidate.create("product_line")
    attachment = upload(candidate, conversation, monkeypatch)
    options: tuple[None | list[dict[str, Any]], ...] = (None, [])
    for selections in options:
        body = candidate.message(conversation, "提取RFQ需求", attachment_ids=[attachment["id"]])
        if selections is not None:
            body["attachment_selections"] = selections
        saved = candidate.save(conversation, body)
        assert (
            saved["action"] == "note"
            and saved["product_work_request"] is None
            and saved["guidance"]
        )
        before = candidate.stored(conversation)
        result = candidate.post(
            f"/api/conversations/{conversation['id']}/messages/{saved['id']}/run", {}
        )
        assert result["status"] == "saved" and result["guidance"]
        assert candidate.stored(conversation) == before
    untouched(candidate)


def test_fourth_fragment_pagination_fixed_source_and_exact_retry(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = candidate.create("product_line")
    attachment = upload(candidate, conversation, monkeypatch)
    base = f"/api/conversations/{conversation['id']}/attachments/{attachment['id']}"
    first = candidate.client.get(base, headers=candidate.headers)
    assert first.status_code == 200, first.text
    assert [part["ordinal"] for part in first.json()["fragments"]] == list(range(1, 11))
    assert first.json()["next_after"] == 10
    later = candidate.client.get(base + "?after_ordinal=10", headers=candidate.headers)
    assert later.status_code == 200, later.text
    assert [part["ordinal"] for part in later.json()["fragments"]] == [11, 12]
    assert later.json()["next_after"] is None
    body = candidate.message(
        conversation,
        "提取RFQ需求",
        attachment_ids=[attachment["id"]],
        attachment_selections=[selected(conversation, attachment)],
    )
    saved = candidate.save(conversation, body)
    assert saved["action"] == "product_work"
    fixed = saved["product_work_request"]
    assert fixed["selection"]["sources"] == [selected(conversation, attachment)]
    prepared = candidate.post(
        f"/api/product-work/spaces/{candidate.space_id}/product-ai-context", fixed["selection"]
    )
    assert prepared["digest"] == fixed["expected_digest"]
    references = [
        ref for ref in prepared["references"] if ref["reference_id"].startswith("attachment:")
    ]
    assert len(references) == 1
    assert references[0]["fields"]["ordinal"] == 4
    assert "120 kPa" in references[0]["fields"]["text"]
    assert references[0]["fields"]["sha256"] == attachment["sha256"]
    before = candidate.stored(conversation)
    assert candidate.save(conversation, body) == saved
    candidate.save(
        conversation,
        {**body, "attachment_selections": [selected(conversation, attachment, 3)]},
        409,
    )
    assert candidate.stored(conversation) == before
    assert candidate.read(conversation)["items"][0]["product_work_request"] == fixed
    untouched(candidate)


def test_wrong_cid_ordinal_revoke_and_current_line_denial_are_atomic(
    candidate: Candidate, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = candidate.create("product_line")
    attachment = upload(candidate, conversation, monkeypatch)
    other = candidate.create("product_line")
    original = selected(conversation, attachment)

    def unchanged(value: dict[str, Any]) -> None:
        assert candidate.stored(value) == []
        with candidate.scope.engine.connect() as c:
            assert (
                c.execute(
                    select(tables.conversations.c.next_sequence).where(
                        tables.conversations.c.tenant_id == candidate.scope.tenant_id,
                        tables.conversations.c.id == UUID(value["id"]),
                    )
                ).scalar_one()
                == 1
            )
            assert (
                c.execute(
                    select(func.count())
                    .select_from(tables.conversation_message_attachments)
                    .where(
                        tables.conversation_message_attachments.c.tenant_id
                        == candidate.scope.tenant_id
                    )
                ).scalar_one()
                == 0
            )
        untouched(candidate)

    # The approved HTTP contract classifies valid but unusable scope/state as 409.
    for fragment, message in (
        (
            {**original, "conversation_id": other["id"]},
            "请明确选择本会话附件及其原文片段，不要混用其他会话来源",
        ),
        (selected(conversation, attachment, 99), "所选原文片段当前不存在或为空，请重新核对原附件"),
    ):
        denied = candidate.save(
            conversation,
            candidate.message(
                conversation,
                "提取RFQ需求",
                attachment_ids=[attachment["id"]],
                attachment_selections=[fragment],
            ),
            409,
        )
        assert denied["detail"] == {"code": "CONVERSATION_CONFLICT", "message": message}
        unchanged(conversation)
    candidate.post(
        f"/api/conversations/{conversation['id']}/attachments/{attachment['id']}/revoke", {}
    )
    denied = candidate.save(
        conversation,
        candidate.message(
            conversation,
            "提取RFQ需求",
            attachment_ids=[attachment["id"]],
            attachment_selections=[original],
        ),
        409,
    )
    assert denied["detail"] == {
        "code": "CONVERSATION_CONFLICT",
        "message": "产品分析须使用已解析且未撤回的内部附件，或先保存普通说明",
    }
    unchanged(conversation)
    user, headers = colleague(candidate)
    private = Candidate(
        candidate.client, candidate.scope, headers, candidate.space_id, candidate.line
    )
    own = private.create("product_line")
    own_file = upload(private, own, monkeypatch)
    body = private.message(
        own,
        "提取RFQ需求",
        attachment_ids=[own_file["id"]],
        attachment_selections=[selected(own, own_file)],
    )
    with candidate.scope.engine.begin() as c:
        c.execute(
            tables.product_line_members.delete().where(
                tables.product_line_members.c.tenant_id == candidate.scope.tenant_id,
                tables.product_line_members.c.product_line_id == UUID(candidate.line["id"]),
                tables.product_line_members.c.user_id == user,
            )
        )
    denied = private.save(own, body, 403)
    assert denied["detail"]["code"] == "CONVERSATION_ACCESS_DENIED"
    unchanged(own)
    with candidate.scope.engine.connect() as c:
        assert (
            c.execute(
                select(func.count())
                .select_from(tables.conversation_message_attachments)
                .where(
                    tables.conversation_message_attachments.c.tenant_id == candidate.scope.tenant_id
                )
            ).scalar_one()
            == 0
        )
    untouched(candidate)


def test_original_run_lookup_rejects_extra_policy_and_missing_id_without_writes(
    candidate: Candidate,
) -> None:
    url = f"/api/product-work/spaces/{candidate.space_id}/product-ai-run-read"
    missing = str(uuid4())
    response = candidate.client.post(
        url,
        headers=candidate.headers,
        json={
            "run_id": missing,
            "capability": "rfq_requirements",
            "product_line_id": candidate.line["id"],
        },
    )
    assert response.status_code == 422, response.text
    response = candidate.client.post(url, headers=candidate.headers, json={"run_id": missing})
    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": {
            "code": "PRODUCT_WORK_RUN_NOT_FOUND",
            "message": "产品工作运行不存在或不属于当前发起人",
        }
    }
    assert "items" not in response.json()
    untouched(candidate)
