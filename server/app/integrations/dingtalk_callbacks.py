"""Authenticated and idempotent DingTalk callback application boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError

from app.db.schema import tables
from app.integrations.dingtalk_crypto import (
    DingTalkCallbackCipher,
    EncryptedCallbackResponse,
)
from app.settings import Settings


class DingTalkCallbackError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CallbackBinding:
    tenant_id: UUID
    corp_id: str


@dataclass(frozen=True)
class ReceiptClaim:
    receipt_id: UUID
    replay: bool


@dataclass(frozen=True)
class CallbackClassification:
    result_code: str
    process_instance_id: str | None = None


class DingTalkCallbackRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def binding_for_route(self, route_key: str) -> CallbackBinding:
        statement = select(
            tables.dingtalk_tenant_bindings.c.tenant_id,
            tables.dingtalk_tenant_bindings.c.corp_id,
        ).where(
            tables.dingtalk_tenant_bindings.c.callback_route_key == route_key,
            tables.dingtalk_tenant_bindings.c.status == "active",
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise DingTalkCallbackError("DINGTALK_CALLBACK_ROUTE_UNKNOWN")
        return CallbackBinding(**dict(row))

    def claim_receipt(
        self,
        *,
        tenant_id: UUID,
        deduplication_key: str,
        payload_digest: str,
        received_at: datetime,
    ) -> ReceiptClaim:
        receipt_id = uuid4()
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    tables.integration_receipts.insert().values(
                        id=receipt_id,
                        tenant_id=tenant_id,
                        channel="event_aes",
                        external_id=(
                            deduplication_key
                            if not deduplication_key.startswith("sha256:")
                            else None
                        ),
                        deduplication_key=deduplication_key,
                        payload_digest=payload_digest,
                        status="claimed",
                        received_at=received_at,
                    )
                )
            return ReceiptClaim(receipt_id=receipt_id, replay=False)
        except IntegrityError:
            with self._engine.connect() as connection:
                existing = (
                    connection.execute(
                        select(
                            tables.integration_receipts.c.id,
                            tables.integration_receipts.c.payload_digest,
                            tables.integration_receipts.c.status,
                        ).where(
                            tables.integration_receipts.c.tenant_id == tenant_id,
                            tables.integration_receipts.c.channel == "event_aes",
                            tables.integration_receipts.c.deduplication_key == deduplication_key,
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if existing is None or existing["payload_digest"] != payload_digest:
                raise DingTalkCallbackError("DINGTALK_CALLBACK_REPLAY_CONFLICT") from None
            return ReceiptClaim(
                receipt_id=existing["id"],
                replay=existing["status"] in {"processed", "ignored"},
            )

    def complete_receipt(self, *, receipt_id: UUID, result_code: str, now: datetime) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(tables.integration_receipts)
                .where(
                    tables.integration_receipts.c.id == receipt_id,
                    tables.integration_receipts.c.status == "claimed",
                )
                .values(status="processed", result_code=result_code, processed_at=now)
            )

    def request_approval_sync(
        self,
        *,
        tenant_id: UUID,
        process_instance_id: str,
        now: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            result = connection.execute(
                update(tables.dingtalk_approval_instances)
                .where(
                    tables.dingtalk_approval_instances.c.tenant_id == tenant_id,
                    tables.dingtalk_approval_instances.c.remote_instance_id == process_instance_id,
                )
                .values(sync_requested_at=now, updated_at=now)
            )
            if result.rowcount != 1:
                raise DingTalkCallbackError("DINGTALK_APPROVAL_UNKNOWN")


class DingTalkCallbackService:
    def __init__(
        self,
        *,
        repository: DingTalkCallbackRepository,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._settings = settings

    def handle_encrypted_event(
        self,
        *,
        route_key: str,
        encrypt: str,
        signature: str,
        timestamp: str,
        nonce: str,
        now: datetime | None = None,
    ) -> EncryptedCallbackResponse:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        binding = self._repository.binding_for_route(route_key)
        token = self._settings.dingtalk_callback_token
        aes_key = self._settings.dingtalk_callback_aes_key
        if token is None or aes_key is None:
            raise DingTalkCallbackError("DINGTALK_CALLBACK_NOT_CONFIGURED")
        cipher = DingTalkCallbackCipher(
            token=token.get_secret_value(),
            encoding_aes_key=aes_key.get_secret_value(),
            corp_id=binding.corp_id,
        )
        payload = cipher.decrypt(
            encrypt=encrypt,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            now=current,
        )
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        external_id = payload.get("eventId") or payload.get("EventId")
        if external_id is not None and (
            not isinstance(external_id, str) or not 1 <= len(external_id) <= 256
        ):
            raise DingTalkCallbackError("DINGTALK_CALLBACK_EVENT_ID_INVALID")
        deduplication_key = external_id or f"sha256:{digest}"
        claim = self._repository.claim_receipt(
            tenant_id=binding.tenant_id,
            deduplication_key=deduplication_key,
            payload_digest=digest,
            received_at=current,
        )
        if not claim.replay:
            classification = self._classify(payload)
            if classification.process_instance_id is not None:
                self._repository.request_approval_sync(
                    tenant_id=binding.tenant_id,
                    process_instance_id=classification.process_instance_id,
                    now=current,
                )
            self._repository.complete_receipt(
                receipt_id=claim.receipt_id,
                result_code=classification.result_code,
                now=current,
            )
        return cipher.encrypt_response(nonce=nonce, now=current)

    @staticmethod
    def _classify(payload: object) -> CallbackClassification:
        if not isinstance(payload, dict):
            raise DingTalkCallbackError("DINGTALK_CALLBACK_JSON_INVALID")
        event_type = payload.get("EventType") or payload.get("eventType")
        if not isinstance(event_type, str) or not 1 <= len(event_type) <= 128:
            return CallbackClassification("ignored_unknown")
        if event_type == "check_url":
            return CallbackClassification("challenge_verified")
        if event_type in {"bpms_instance_change", "bpms_task_change"}:
            process_instance_id = payload.get("processInstanceId")
            if not isinstance(process_instance_id, str) or not 1 <= len(process_instance_id) <= 256:
                return CallbackClassification("ignored_missing_process_instance_id")
            return CallbackClassification("approval_sync_requested", process_instance_id)
        return CallbackClassification("ignored_unknown")
