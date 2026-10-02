"""Reply field boundaries and guarded confirmation dispatch without database access."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, Engine

from app.auth.repository import AuthContext
from app.domain import supplier_replies as replies
from app.domain.build_materials import BuildMaterialService
from app.domain.npi_execution import NpiExecutionService
from app.domain.product_workspace import ProductWorkError, digest
from app.domain.supplier_engineering import EngineeringDraft, SupplierEngineeringService

TENANT, PROJECT, USER, SUPPLIER, RECORD, DOCUMENT, REQUEST = (UUID(int=i) for i in range(1, 8))


def original(kind: str = "sample_delivery") -> EngineeringDraft:
    return EngineeringDraft.model_validate(
        dict(
            kind=kind,
            source_reference="原送样事项",
            title="P送样",
            status="active",
            requested=dict(at="2020-01-01T00:00:00Z", evidence_id=DOCUMENT, location="原请求"),
            promised=dict(at="2020-01-05T00:00:00Z", evidence_id=DOCUMENT, location="原承诺")
            if kind == "sample_delivery"
            else None,
            evidence_id=DOCUMENT,
            reason="原件登记",
        )
    )


def draft(update: str = "first_response") -> replies.ReplyDraft:
    return replies.ReplyDraft.model_validate(
        dict(
            update=update,
            at="2020-01-03T00:00:00Z",
            evidence_id=DOCUMENT,
            location="内部转发第2页回复时间",
            reason="原供方对同一送样请求回复",
        )
    )


def test_reply_prefills_only_observed_fact_and_preserves_original_promise_and_scope() -> None:
    before = original()
    after = replies.prepare_reply(before, draft())
    assert after.promised == before.promised
    assert after.requested == before.requested
    assert after.source_reference == before.source_reference
    assert after.received is None
    assert after.responded is not None and after.responded.evidence_id == DOCUMENT
    assert before.responded is None


def test_receipt_is_observation_not_quality_release_or_new_supply() -> None:
    after = replies.prepare_reply(original(), draft("sample_received"))
    assert after.received is not None
    assert after.responded is None
    with pytest.raises(ProductWorkError, match="原样品交付"):
        replies.prepare_reply(original("technical_response"), draft("sample_received"))


def test_first_fact_cannot_be_overwritten_and_withdrawn_source_stays_blocked() -> None:
    once = replies.prepare_reply(original(), draft())
    with pytest.raises(ProductWorkError, match="已有此实际事实"):
        replies.prepare_reply(once, draft())
    withdrawn = EngineeringDraft.model_validate({**original().model_dump(), "status": "withdrawn"})
    with pytest.raises(ProductWorkError, match="有效"):
        replies.prepare_reply(withdrawn, draft())


def test_reply_does_not_accept_scope_or_promise_from_caller() -> None:
    for field in ("tenant_id", "project_id", "promised", "quality_status", "supply_quantity"):
        with pytest.raises(ValidationError):
            replies.ReplyDraft.model_validate({**draft().model_dump(), field: "forged"})
    with pytest.raises(ValidationError, match="未来"):
        replies.ReplyDraft.model_validate(
            {**draft().model_dump(), "at": datetime.now(UTC) + timedelta(days=1)}
        )
    with pytest.raises(ValidationError):
        replies.prepare_reply(
            original(),
            replies.ReplyDraft.model_validate(
                {
                    **draft().model_dump(),
                    "at": "2019-12-31T00:00:00Z",
                }
            ),
        )


def test_preview_binds_confirming_user_and_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "version": 1,
        "payload": original().model_dump(mode="json"),
    }
    monkeypatch.setattr(BuildMaterialService, "_authorize", MagicMock())
    monkeypatch.setattr(replies, "preview", lambda *args: {"digest": "b" * 64})
    first = cast(
        AuthContext,
        SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=USER)),
    )
    other = cast(
        AuthContext,
        SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=UUID(int=99))),
    )
    a = replies.reply_preview(
        cast(Connection, connection), first, PROJECT, SUPPLIER, RECORD, draft()
    )
    b = replies.reply_preview(
        cast(Connection, connection), other, PROJECT, SUPPLIER, RECORD, draft()
    )
    assert a["basis"]["reviewer_user_id"] == str(USER)
    assert a["basis"]["tenant_id"] == str(TENANT)
    assert a["digest"] != b["digest"]


def setup(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, AuthContext, Any]:
    engine, connection = MagicMock(), MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = None
    monkeypatch.setattr(NpiExecutionService, "_project", MagicMock())
    monkeypatch.setattr(BuildMaterialService, "_authorize", MagicMock())
    context = cast(
        AuthContext,
        SimpleNamespace(tenant=SimpleNamespace(id=TENANT), user=SimpleNamespace(id=USER)),
    )
    dispatch = MagicMock(return_value={"version": 2})
    monkeypatch.setattr(SupplierEngineeringService, "apply_in_connection", dispatch)
    return engine, connection, context, dispatch


def confirmation() -> replies.ReplyConfirm:
    return replies.ReplyConfirm.model_validate(
        {
            **draft().model_dump(),
            "request_id": REQUEST,
            "expected_version": 1,
            "expected_digest": "a" * 64,
            "evidence_checked": True,
        }
    )


def test_confirmation_uses_same_connection_and_server_bound_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, connection, context, dispatch = setup(monkeypatch)
    command = confirmation()
    monkeypatch.setattr(
        replies,
        "reply_preview",
        lambda *args: dict(
            digest="a" * 64,
            basis=dict(
                previous_version=1,
                proposed=replies.prepare_reply(original(), draft()).model_dump(mode="json"),
                engineering=dict(digest="b" * 64),
                reply=draft().model_dump(mode="json"),
            ),
        ),
    )
    result = replies.SupplierReplyService(cast(Engine, engine)).confirm(
        context, PROJECT, SUPPLIER, RECORD, command
    )
    assert result["version"] == 2
    assert dispatch.call_args.args[:5] == (connection, context, PROJECT, SUPPLIER, RECORD)
    applied = dispatch.call_args.args[5]
    assert applied.expected_version == 1 and applied.expected_digest == "b" * 64
    assert applied.promised == original().promised
    assert dispatch.call_args.kwargs["supplier_reply"]["reply"] == draft().model_dump(mode="json")


@pytest.mark.parametrize("version,digest_value", [(2, "a" * 64), (1, "c" * 64)])
def test_drift_blocks_all_write_dispatch(
    monkeypatch: pytest.MonkeyPatch, version: int, digest_value: str
) -> None:
    engine, _, context, dispatch = setup(monkeypatch)
    monkeypatch.setattr(
        replies,
        "reply_preview",
        lambda *args: dict(digest=digest_value, basis=dict(previous_version=version)),
    )
    with pytest.raises(ProductWorkError, match="已变化"):
        replies.SupplierReplyService(cast(Engine, engine)).confirm(
            context, PROJECT, SUPPLIER, RECORD, confirmation()
        )
    dispatch.assert_not_called()


def test_retry_returns_original_receipt_without_reconstructing_updated_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, connection, context, dispatch = setup(monkeypatch)
    command = confirmation()
    signature = digest(
        dict(
            project=str(PROJECT),
            supplier=str(SUPPLIER),
            record=str(RECORD),
            command=command.model_dump(mode="json"),
        )
    )
    prior = dict(version=2, snapshot=dict(supplier_reply=dict(request_digest=signature)))
    connection.execute.return_value.mappings.return_value.one_or_none.return_value = prior
    preview = MagicMock(side_effect=AssertionError("retry must not rebuild current fact"))
    monkeypatch.setattr(replies, "reply_preview", preview)
    service = replies.SupplierReplyService(cast(Engine, engine))
    assert service.confirm(context, PROJECT, SUPPLIER, RECORD, command)["version"] == 2
    dispatch.assert_not_called()
    with pytest.raises(ProductWorkError, match="不同供方回复"):
        service.confirm(context, PROJECT, SUPPLIER, UUID(int=99), command)
    preview.assert_not_called()


def test_revoked_authority_is_checked_before_any_receipt_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, connection, context, dispatch = setup(monkeypatch)
    monkeypatch.setattr(
        BuildMaterialService,
        "_authorize",
        MagicMock(side_effect=PermissionError("revoked")),
    )
    with pytest.raises(PermissionError):
        replies.SupplierReplyService(cast(Engine, engine)).confirm(
            context, PROJECT, SUPPLIER, RECORD, confirmation()
        )
    connection.execute.assert_not_called()
    dispatch.assert_not_called()
