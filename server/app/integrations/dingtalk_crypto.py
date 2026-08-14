"""DingTalk HTTP callback cryptography with strict framing validation."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAX_CLOCK_SKEW_SECONDS = 300
MAX_CIPHERTEXT_CHARS = 1_400_000
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{1,128}$")
SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class DingTalkCallbackVerificationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EncryptedCallbackResponse:
    msg_signature: str
    time_stamp: str
    nonce: str
    encrypt: str


def callback_signature(*parts: str) -> str:
    return hashlib.sha1("".join(sorted(parts)).encode("utf-8"), usedforsecurity=False).hexdigest()


def _timestamp_seconds(timestamp: str) -> int:
    if not timestamp.isascii() or not timestamp.isdigit() or not 10 <= len(timestamp) <= 13:
        raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_TIMESTAMP_INVALID")
    raw = int(timestamp)
    return raw // 1000 if len(timestamp) == 13 else raw


def _decode_aes_key(encoding_aes_key: str) -> bytes:
    if not 40 <= len(encoding_aes_key) <= 44:
        raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_CONFIGURATION_INVALID")
    try:
        key = base64.b64decode(
            encoding_aes_key + "=" * (-len(encoding_aes_key) % 4),
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise DingTalkCallbackVerificationError(
            "DINGTALK_CALLBACK_CONFIGURATION_INVALID"
        ) from error
    if len(key) != 32:
        raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_CONFIGURATION_INVALID")
    return key


def _strict_unpad(value: bytes) -> bytes:
    if not value:
        raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_PADDING_INVALID")
    padding = value[-1]
    if padding < 1 or padding > 32 or len(value) < padding:
        raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_PADDING_INVALID")
    if not hmac.compare_digest(value[-padding:], bytes([padding]) * padding):
        raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_PADDING_INVALID")
    return value[:-padding]


def _pad(value: bytes) -> bytes:
    padding = 32 - len(value) % 32
    return value + bytes([padding]) * padding


class DingTalkCallbackCipher:
    def __init__(self, *, token: str, encoding_aes_key: str, corp_id: str) -> None:
        if not token or not corp_id:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_CONFIGURATION_INVALID")
        self._token = token
        self._key = _decode_aes_key(encoding_aes_key)
        self._corp_id = corp_id

    def decrypt(
        self,
        *,
        encrypt: str,
        signature: str,
        timestamp: str,
        nonce: str,
        now: datetime | None = None,
    ) -> Mapping[str, object]:
        message = self._decrypt_message(
            encrypt=encrypt,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            now=now,
        )
        try:
            payload = json.loads(message)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_JSON_INVALID") from error
        if not isinstance(payload, Mapping):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_JSON_INVALID")
        return payload

    def decrypt_response(
        self,
        *,
        encrypt: str,
        signature: str,
        timestamp: str,
        nonce: str,
        now: datetime | None = None,
    ) -> str:
        message = self._decrypt_message(
            encrypt=encrypt,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            now=now,
        )
        try:
            return message.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_JSON_INVALID") from error

    def _decrypt_message(
        self,
        *,
        encrypt: str,
        signature: str,
        timestamp: str,
        nonce: str,
        now: datetime | None,
    ) -> bytes:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        request_seconds = _timestamp_seconds(timestamp)
        if abs(int(current.timestamp()) - request_seconds) > MAX_CLOCK_SKEW_SECONDS:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_TIMESTAMP_EXPIRED")
        if not NONCE_PATTERN.fullmatch(nonce):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_NONCE_INVALID")
        normalized_signature = signature.strip().lower()
        if not SIGNATURE_PATTERN.fullmatch(normalized_signature):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_SIGNATURE_INVALID")
        if not encrypt or len(encrypt) > MAX_CIPHERTEXT_CHARS:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_CIPHERTEXT_INVALID")
        expected = callback_signature(self._token, timestamp, nonce, encrypt)
        if not hmac.compare_digest(expected, normalized_signature):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_SIGNATURE_INVALID")
        try:
            encrypted = base64.b64decode(encrypt, validate=True)
        except (binascii.Error, ValueError) as error:
            raise DingTalkCallbackVerificationError(
                "DINGTALK_CALLBACK_CIPHERTEXT_INVALID"
            ) from error
        if not encrypted or len(encrypted) % 16:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_CIPHERTEXT_INVALID")
        decryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).decryptor()
        try:
            framed = _strict_unpad(decryptor.update(encrypted) + decryptor.finalize())
        except ValueError as error:
            raise DingTalkCallbackVerificationError(
                "DINGTALK_CALLBACK_CIPHERTEXT_INVALID"
            ) from error
        if len(framed) < 20:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_FRAME_INVALID")
        message_length = struct.unpack(">I", framed[16:20])[0]
        message_end = 20 + message_length
        if message_length == 0 or message_end > len(framed):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_FRAME_INVALID")
        message = framed[20:message_end]
        tail = framed[message_end:]
        if not hmac.compare_digest(tail, self._corp_id.encode("utf-8")):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_CORP_MISMATCH")
        return message

    def encrypt_response(
        self,
        *,
        nonce: str,
        message: str = "success",
        now: datetime | None = None,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> EncryptedCallbackResponse:
        if not NONCE_PATTERN.fullmatch(nonce):
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_NONCE_INVALID")
        prefix = random_bytes(16)
        if len(prefix) != 16:
            raise DingTalkCallbackVerificationError("DINGTALK_CALLBACK_RANDOM_INVALID")
        encoded_message = message.encode("utf-8")
        framed = (
            prefix
            + struct.pack(">I", len(encoded_message))
            + encoded_message
            + self._corp_id.encode("utf-8")
        )
        encryptor = Cipher(algorithms.AES(self._key), modes.CBC(self._key[:16])).encryptor()
        encrypted = encryptor.update(_pad(framed)) + encryptor.finalize()
        encoded = base64.b64encode(encrypted).decode("ascii")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        timestamp = str(int(current.timestamp() * 1000))
        return EncryptedCallbackResponse(
            msg_signature=callback_signature(self._token, timestamp, nonce, encoded),
            time_stamp=timestamp,
            nonce=nonce,
            encrypt=encoded,
        )
