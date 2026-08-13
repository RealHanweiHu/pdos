from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text

from app.db.engine import get_engine
from app.db.schema import tables
from app.db.test_safety import configured_test_database_url
from app.db.url import psycopg_database_url
from app.integrations.dingtalk_crypto import (
    DingTalkCallbackCipher,
    DingTalkCallbackVerificationError,
    callback_signature,
)
from app.main import app
from app.settings import get_settings

SERVER_ROOT = Path(__file__).resolve().parents[1]
JWT_SECRET = "dingtalk-callback-test-jwt-secret-at-least-32-bytes"
CALLBACK_TOKEN = "dingtalk-callback-token"
AES_KEY_BYTES = bytes(range(32))
AES_KEY = base64.b64encode(AES_KEY_BYTES).decode("ascii").rstrip("=")
CORP_ID = "ding-callback-corp"
ROUTE_KEY = "ding-callback-route"
NOW = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    test_url = configured_test_database_url()
    monkeypatch.setenv("DATABASE_URL", test_url)
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("PDOS_DINGTALK_CALLBACK_TOKEN", CALLBACK_TOKEN)
    monkeypatch.setenv("PDOS_DINGTALK_CALLBACK_AES_KEY", AES_KEY)
    get_settings.cache_clear()
    get_engine.cache_clear()
    os.environ["DATABASE_URL"] = test_url
    command.upgrade(Config(str(SERVER_ROOT / "alembic.ini")), "head")
    engine = create_engine(psycopg_database_url(test_url))
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE cehub_core.tenants CASCADE"))
            tenant_id = connection.execute(
                tables.tenants.insert()
                .values(
                    id="00000000-0000-0000-0000-000000000426",
                    slug="dingtalk-callback-test",
                    name="DingTalk Callback Test",
                )
                .returning(tables.tenants.c.id)
            ).scalar_one()
            user_id = connection.execute(
                tables.users.insert()
                .values(
                    id="00000000-0000-0000-0000-000000000526",
                    tenant_id=tenant_id,
                    username="callback-owner",
                    display_name="Callback Owner",
                    role="owner",
                )
                .returning(tables.users.c.id)
            ).scalar_one()
            connection.execute(
                tables.dingtalk_tenant_bindings.insert().values(
                    tenant_id=tenant_id,
                    corp_id=CORP_ID,
                    client_id="callback-client",
                    oauth_redirect_uri="https://pdos.example/dingtalk/callback",
                    callback_route_key=ROUTE_KEY,
                    status="active",
                    configured_by_user_id=user_id,
                )
            )
        yield test_url
    finally:
        engine.dispose()
        cached_engine = get_engine()
        cached_engine.dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()


def _cipher(*, corp_id: str = CORP_ID) -> DingTalkCallbackCipher:
    return DingTalkCallbackCipher(
        token=CALLBACK_TOKEN,
        encoding_aes_key=AES_KEY,
        corp_id=corp_id,
    )


def _encrypted_payload(payload: dict[str, object], *, nonce: str = "nonce-1") -> dict[str, str]:
    encrypted = _cipher().encrypt_response(
        nonce=nonce,
        message=json.dumps(payload, separators=(",", ":")),
        now=NOW,
        random_bytes=lambda size: b"0123456789abcdef",
    )
    assert encrypted.time_stamp == str(int(NOW.timestamp() * 1000))
    return {
        "encrypt": encrypted.encrypt,
        "signature": encrypted.msg_signature,
        "timestamp": encrypted.time_stamp,
        "nonce": encrypted.nonce,
    }


def test_fixed_vector_round_trip_strictly_validates_signature_frame_and_corp() -> None:
    encrypted = _encrypted_payload(
        {"EventType": "check_url", "eventId": "challenge-1"},
        nonce="fixed-nonce",
    )
    assert encrypted == {
        "encrypt": (
            "4j/AuRx71kQlxVlzbpsMWIcP3hF4SBnPtJB7OQqqZxnIT64ObkuEwAvU1x3SKU5S"
            "FhxtEYwz6GsCkrMn8U+2tIi6CMvz7KLqDjAVMiUibOgPmDsc5kffyqL57clYSnFC"
        ),
        "signature": "03adce531372c1b09e21100a4ebab7139d2ab4af",
        "timestamp": "1786557600000",
        "nonce": "fixed-nonce",
    }
    assert _cipher().decrypt(
        encrypt=encrypted["encrypt"],
        signature=encrypted["signature"],
        timestamp=encrypted["timestamp"],
        nonce=encrypted["nonce"],
        now=NOW,
    ) == {"EventType": "check_url", "eventId": "challenge-1"}

    with pytest.raises(DingTalkCallbackVerificationError, match="SIGNATURE_INVALID"):
        _cipher().decrypt(
            encrypt=encrypted["encrypt"],
            signature="0" * 40,
            timestamp=encrypted["timestamp"],
            nonce=encrypted["nonce"],
            now=NOW,
        )

    wrong_corp = _cipher(corp_id="different-corp").encrypt_response(
        nonce="fixed-nonce",
        message=json.dumps({"EventType": "check_url"}),
        now=NOW,
        random_bytes=lambda size: b"0123456789abcdef",
    )
    with pytest.raises(DingTalkCallbackVerificationError, match="CORP_MISMATCH"):
        _cipher().decrypt(
            encrypt=wrong_corp.encrypt,
            signature=wrong_corp.msg_signature,
            timestamp=wrong_corp.time_stamp,
            nonce=wrong_corp.nonce,
            now=NOW,
        )


def test_timestamp_nonce_ciphertext_and_padding_fail_closed() -> None:
    encrypted = _encrypted_payload({"EventType": "check_url"})
    for expired_at in [NOW - timedelta(seconds=301), NOW + timedelta(seconds=301)]:
        with pytest.raises(DingTalkCallbackVerificationError, match="TIMESTAMP_EXPIRED"):
            _cipher().decrypt(
                encrypt=encrypted["encrypt"],
                signature=encrypted["signature"],
                timestamp=encrypted["timestamp"],
                nonce=encrypted["nonce"],
                now=expired_at,
            )

    with pytest.raises(DingTalkCallbackVerificationError, match="NONCE_INVALID"):
        _cipher().decrypt(
            encrypt=encrypted["encrypt"],
            signature=encrypted["signature"],
            timestamp=encrypted["timestamp"],
            nonce="bad nonce",
            now=NOW,
        )

    raw = bytearray(base64.b64decode(encrypted["encrypt"]))
    raw[-1] ^= 1
    corrupted = base64.b64encode(raw).decode("ascii")
    corrupted_signature = callback_signature(
        CALLBACK_TOKEN,
        encrypted["timestamp"],
        encrypted["nonce"],
        corrupted,
    )
    with pytest.raises(DingTalkCallbackVerificationError, match="PADDING_INVALID"):
        _cipher().decrypt(
            encrypt=corrupted,
            signature=corrupted_signature,
            timestamp=encrypted["timestamp"],
            nonce=encrypted["nonce"],
            now=NOW,
        )


def test_http_callback_challenge_unknown_and_replay_are_idempotent(
    isolated_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.integrations.dingtalk_callbacks as callbacks

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> FrozenDateTime:
            return cls.fromtimestamp(NOW.timestamp(), tz=UTC)

    monkeypatch.setattr(callbacks, "datetime", FrozenDateTime)
    challenge = _encrypted_payload({"EventType": "check_url", "eventId": "event-1"})
    with TestClient(app) as client:
        first = client.post(
            f"/api/integrations/dingtalk/callback/{ROUTE_KEY}",
            params={
                "signature": challenge["signature"],
                "timestamp": challenge["timestamp"],
                "nonce": challenge["nonce"],
            },
            json={"encrypt": challenge["encrypt"]},
        )
        assert first.status_code == 200
        ack = first.json()
        assert (
            _cipher().decrypt_response(
                encrypt=ack["encrypt"],
                signature=ack["msg_signature"],
                timestamp=ack["timeStamp"],
                nonce=ack["nonce"],
                now=NOW,
            )
            == "success"
        )

        replay = client.post(
            f"/api/integrations/dingtalk/callback/{ROUTE_KEY}",
            params={
                "signature": challenge["signature"],
                "timestamp": challenge["timestamp"],
                "nonce": challenge["nonce"],
            },
            json={"encrypt": challenge["encrypt"]},
        )
        assert replay.status_code == 200

        conflict = _encrypted_payload(
            {"EventType": "bpms_instance_change", "eventId": "event-1"},
            nonce="nonce-2",
        )
        conflicted = client.post(
            f"/api/integrations/dingtalk/callback/{ROUTE_KEY}",
            params={
                "signature": conflict["signature"],
                "timestamp": conflict["timestamp"],
                "nonce": conflict["nonce"],
            },
            json={"encrypt": conflict["encrypt"]},
        )
        assert conflicted.status_code == 409
        assert conflicted.json()["detail"]["code"] == "DINGTALK_CALLBACK_REPLAY_CONFLICT"

        unknown = _encrypted_payload({"EventType": "unrelated_event", "eventId": "event-2"})
        ignored = client.post(
            f"/api/integrations/dingtalk/callback/{ROUTE_KEY}",
            params={
                "signature": unknown["signature"],
                "timestamp": unknown["timestamp"],
                "nonce": unknown["nonce"],
            },
            json={"encrypt": unknown["encrypt"]},
        )
        assert ignored.status_code == 200

    engine = create_engine(psycopg_database_url(isolated_database))
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(tables.integration_receipts)
                ).scalar_one()
                == 2
            )
            results = set(
                connection.execute(select(tables.integration_receipts.c.result_code)).scalars()
            )
            assert results == {"challenge_verified", "ignored_unknown"}
            assert (
                connection.execute(
                    select(func.count()).select_from(tables.gate_history_records)
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()
