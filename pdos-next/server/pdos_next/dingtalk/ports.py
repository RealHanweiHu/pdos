"""Trusted channel adapters. Production transport is absent until explicitly configured."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr


@dataclass(frozen=True)
class ExternalIdentity:
    application_id: UUID
    corp_id: str
    external_user_id: str
    state_sha256: str


@dataclass(frozen=True)
class SingleMessage:
    application_id: UUID
    corp_id: str
    external_user_id: str
    message_id: str
    conversation_kind: str
    conversation_id: str
    mentioned: bool
    text: str = field(repr=False)
    envelope_sha256: str


@dataclass(frozen=True)
class Members:
    application_id: UUID
    conversation_id: str
    external_user_ids: tuple[str, ...]
    complete: bool
    version: str


class ChannelAdapter(Protocol):
    def authorization_url(self, application, state: str) -> str: ...
    def exchange_identity(
        self, application, credential: SecretStr, code: SecretStr, state_sha256: str
    ) -> ExternalIdentity: ...
    def verify_message(
        self, application, credential: SecretStr, body: bytes, *, signature: str, timestamp: str
    ) -> SingleMessage: ...
    def members(self, application, credential: SecretStr, conversation_id: str) -> Members: ...
    def send(
        self, application, credential: SecretStr, request_key: UUID, payload: dict
    ) -> dict: ...
    def lookup(self, application, credential: SecretStr, request_key: UUID) -> dict | None: ...


@dataclass(frozen=True)
class ChannelRuntime:
    kms: object
    adapter: ChannelAdapter
    public_base_url: str
