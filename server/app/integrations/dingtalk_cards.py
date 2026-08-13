"""Signed interactive-card callbacks with identity and action revalidation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.dingtalk_crypto import MAX_CLOCK_SKEW_SECONDS
from app.settings import Settings


class DingTalkCardCallbackError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def card_callback_signature(*, secret: str, timestamp: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")


class DingTalkCardCallbackService:
    def __init__(self, *, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    def handle(
        self,
        *,
        route_key: str,
        timestamp: str,
        signature: str,
        payload: Mapping[str, object],
        now: datetime | None = None,
    ) -> bool:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if not timestamp.isdigit() or len(timestamp) not in {10, 13}:
            raise DingTalkCardCallbackError("DINGTALK_CARD_TIMESTAMP_INVALID")
        callback_seconds = int(timestamp) // (1000 if len(timestamp) == 13 else 1)
        if abs(int(current.timestamp()) - callback_seconds) > MAX_CLOCK_SKEW_SECONDS:
            raise DingTalkCardCallbackError("DINGTALK_CARD_TIMESTAMP_EXPIRED")
        secret = self._settings.dingtalk_card_callback_secret
        if secret is None:
            raise DingTalkCardCallbackError("DINGTALK_CARD_CALLBACK_NOT_CONFIGURED")
        expected = card_callback_signature(secret=secret.get_secret_value(), timestamp=timestamp)
        if not hmac.compare_digest(expected, signature):
            raise DingTalkCardCallbackError("DINGTALK_CARD_SIGNATURE_INVALID")
        corp_id = payload.get("corpId")
        open_id = payload.get("openId")
        out_track_id = payload.get("outTrackId")
        action = payload.get("action")
        if not all(
            isinstance(value, str) and value for value in (corp_id, open_id, out_track_id, action)
        ):
            raise DingTalkCardCallbackError("DINGTALK_CARD_PAYLOAD_INVALID")
        if action not in {"acknowledge", "open"}:
            raise DingTalkCardCallbackError("DINGTALK_CARD_ACTION_INVALID")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        deduplication_key = f"{out_track_id}:{open_id}:{action}"
        receipt_id = uuid4()
        with self._engine.begin() as connection:
            card = (
                connection.execute(
                    select(
                        tables.dingtalk_interactive_cards,
                        tables.dingtalk_user_bindings.c.user_id.label("callback_user_id"),
                        tables.dingtalk_tenant_bindings.c.corp_id,
                    )
                    .join(
                        tables.dingtalk_user_bindings,
                        (
                            tables.dingtalk_user_bindings.c.tenant_id
                            == tables.dingtalk_interactive_cards.c.tenant_id
                        )
                        & (
                            tables.dingtalk_user_bindings.c.user_id
                            == tables.dingtalk_interactive_cards.c.recipient_user_id
                        ),
                    )
                    .join(
                        tables.dingtalk_tenant_bindings,
                        tables.dingtalk_tenant_bindings.c.tenant_id
                        == tables.dingtalk_interactive_cards.c.tenant_id,
                    )
                    .where(
                        tables.dingtalk_tenant_bindings.c.card_callback_route_key == route_key,
                        tables.dingtalk_tenant_bindings.c.status == "active",
                        tables.dingtalk_user_bindings.c.status == "active",
                        tables.dingtalk_user_bindings.c.open_id == open_id,
                        tables.dingtalk_interactive_cards.c.out_track_id == out_track_id,
                        tables.dingtalk_interactive_cards.c.action_key == action,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if card is None or card["corp_id"] != corp_id:
                raise DingTalkCardCallbackError("DINGTALK_CARD_CONTEXT_MISMATCH")
            inserted = connection.execute(
                pg_insert(tables.integration_receipts)
                .values(
                    id=receipt_id,
                    tenant_id=card["tenant_id"],
                    channel="card_hmac",
                    external_id=out_track_id,
                    deduplication_key=deduplication_key,
                    payload_digest=digest,
                    status="claimed",
                    received_at=current,
                )
                .on_conflict_do_nothing(
                    constraint="uq_integration_receipts_tenant_channel_deduplication"
                )
                .returning(tables.integration_receipts.c.id)
            ).scalar_one_or_none()
            if inserted is None:
                existing = connection.execute(
                    select(tables.integration_receipts.c.payload_digest).where(
                        tables.integration_receipts.c.tenant_id == card["tenant_id"],
                        tables.integration_receipts.c.channel == "card_hmac",
                        tables.integration_receipts.c.deduplication_key == deduplication_key,
                    )
                ).scalar_one_or_none()
                if existing != digest:
                    raise DingTalkCardCallbackError("DINGTALK_CARD_REPLAY_CONFLICT")
                return True
            status = "acknowledged" if action == "acknowledge" else "handled"
            values: dict[str, object] = {"status": status, "updated_at": current}
            if action == "acknowledge":
                values.update(
                    acknowledged_by_user_id=card["callback_user_id"],
                    acknowledged_at=current,
                )
            connection.execute(
                update(tables.dingtalk_interactive_cards)
                .where(tables.dingtalk_interactive_cards.c.id == card["id"])
                .values(**values)
            )
            EventAuditWriter(
                connection,
                tenant_id=card["tenant_id"],
                project_id=card["project_id"],
                actor_user_id=card["callback_user_id"],
            ).record(
                EventDraft(
                    event_id=f"dingtalk-card:{card['id']}:{action}:{uuid4()}",
                    event_type="DINGTALK_CARD_ACTION_RECEIVED",
                    source="dingtalk_connector_service",
                    entity_id=card["id"],
                    payload={"card_id": str(card["id"]), "action": action},
                    occurred_at=current,
                ),
                AuditDraft(
                    action=f"dingtalk.card.{action}",
                    before_snapshot={"status": card["status"]},
                    after_snapshot={"status": status},
                    context={"business_mutation": False},
                ),
            )
            connection.execute(
                update(tables.integration_receipts)
                .where(tables.integration_receipts.c.id == receipt_id)
                .values(status="processed", result_code=status, processed_at=current)
            )
        return True
