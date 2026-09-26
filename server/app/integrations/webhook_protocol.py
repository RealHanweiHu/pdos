"""PDOS webhook v1: bounded HTTPS delivery and exact-byte HMAC signatures."""

import base64
import hmac
import ipaddress
import json
import os
import re
import socket
import time
from hashlib import sha256
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.ai.reach_transport import _PinnedConnection
from app.domain.product_workspace import ProductWorkError
from app.settings import get_settings

PROTOCOL = "pdos.webhook.v1"
MAX_BODY = 256 * 1024


def destination(value: str) -> str:
    try:
        u = urlsplit(value)
        host = (u.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = u.port or 443
        if u.scheme != "https" or not host or u.username or u.password or u.query or u.fragment:
            raise ValueError
        if any(c.isspace() or ord(c) < 32 for c in value) or len(value) > 2048:
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".localhost", ".local", ".internal")):
                raise ValueError from None
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError
        display = f"[{host}]" if ":" in host else host
        return urlunsplit(
            ("https", display + (f":{port}" if port != 443 else ""), u.path or "/", "", "")
        )
    except (ValueError, UnicodeError) as error:
        raise ProductWorkError("请输入公开HTTPS接收地址，不含账号、查询参数或片段") from error


def root_key() -> bytes:
    value = get_settings().webhook_encryption_key
    if value is None:
        raise ProductWorkError("Webhook签名密钥加密配置尚未提供")
    try:
        result = base64.b64decode(value.get_secret_value(), altchars=b"-_", validate=True)
        if len(result) != 32:
            raise ValueError
        return result
    except (ValueError, TypeError) as error:
        raise ProductWorkError("Webhook签名密钥加密配置无效") from error


def encrypt_key(tenant: UUID, project: UUID, endpoint: UUID, secret: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    aad = f"{PROTOCOL}:{tenant}:{project}:{endpoint}".encode()
    return nonce, AESGCM(root_key()).encrypt(nonce, secret, aad)


def decrypt_key(row: Any) -> bytes:
    aad = f"{PROTOCOL}:{row['tenant_id']}:{row['project_id']}:{row['id']}".encode()
    try:
        return AESGCM(root_key()).decrypt(bytes(row["key_nonce"]), bytes(row["key_envelope"]), aad)
    except ProductWorkError:
        raise
    except Exception as error:
        raise ProductWorkError("原端点签名密钥不可解密，请核对原加密配置") from error


def body_bytes(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(body) > MAX_BODY:
        raise ProductWorkError("通知超过256KiB范围，请通过受控接口读取完整资料")
    return body


def signature(secret: bytes, timestamp: int, delivery: UUID, attempt: UUID, body: bytes) -> str:
    message = f"v1.{timestamp}.{delivery}.{attempt}.{sha256(body).hexdigest()}".encode()
    return "v1=" + hmac.new(secret, message, sha256).hexdigest()


def verify_signature(
    secret: bytes,
    timestamp: int,
    delivery: UUID,
    attempt: UUID,
    body: bytes,
    supplied: str,
    *,
    now: int,
) -> bool:
    # Receiver must additionally retain delivery IDs and deduplicate business effects.
    if (
        abs(now - timestamp) > 300
        or len(body) > MAX_BODY
        or not re.fullmatch(r"v1=[a-f0-9]{64}", supplied)
    ):
        return False
    return hmac.compare_digest(signature(secret, timestamp, delivery, attempt, body), supplied)


class WebhookTransport:
    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        parsed = urlsplit(destination(url))
        host, port = parsed.hostname or "", parsed.port or 443
        deadline = time.monotonic() + 20
        addresses = tuple(
            dict.fromkeys(
                str(v[4][0]) for v in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            )
        )
        if not addresses or any(
            not ipaddress.ip_address(v).is_global or ipaddress.ip_address(v).is_multicast
            for v in addresses
        ):
            raise ProductWorkError("接收地址当前解析到非公开网络，停止投递")
        connection = _PinnedConnection(host, port, addresses, tls=True, deadline=deadline)
        try:
            connection.request(
                "POST",
                quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                body=body,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "User-Agent": "PDOS-Webhook/1.0",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.getheader("Content-Encoding", "identity") not in {"", "identity"}:
                return response.status, b""
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            data = response.read(4097)
            return response.status, data if len(data) <= 4096 else b""
        finally:
            connection.close()
