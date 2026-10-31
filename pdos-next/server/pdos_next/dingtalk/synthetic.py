"""In-memory verified identity/event/delivery adapter for explicit synthetic tests.

This is not the official DingTalk protocol and opens no socket. There is no
production fallback, external history reader, source reader or model client.
"""

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, SecretStr

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.schema_base import StrictModel
from pdos_next.service import digest

from .ports import ExternalIdentity, Members, SingleMessage


class Event(StrictModel):
    corp_id: str = Field(min_length=1, max_length=160)
    external_user_id: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    conversation_kind: str = Field(pattern=r"^(direct|group)$")
    conversation_id: str = Field(min_length=1, max_length=200)
    mentioned: bool = Field(strict=True)
    text: str = Field(min_length=1, max_length=6000)


class SyntheticKms:
    def __init__(self):
        self._slots = {}
        self.reads = []

    def install(self, arn, version, value=None):
        self._slots[arn] = (version, value or SecretStr("SYNTHETIC-NOT-A-REAL-CREDENTIAL"))

    def current_version(self, arn):
        slot = self._slots.get(arn)
        return slot[0] if slot else None

    def value(self, arn, version):
        slot = self._slots.get(arn)
        if slot is None or slot[0] != version:
            raise DomainError("SOURCE_UNAVAILABLE", "合成凭据版本已不可用。")
        self.reads.append((arn, version))
        return slot[1]


class SyntheticAdapter:
    def __init__(self, *, clock=now):
        self.clock = clock
        self.codes, self.groups, self.receipts = {}, {}, {}
        self.send_count = 0
        self.lookup_count = 0
        self.lose_after_send = set()
        self.before_send = None
        self._exchange_count = 0

    def authorization_url(self, application, state):
        return f"https://synthetic.invalid/dingtalk/{application.id}?state={state}"

    def issue_code(self, application, external_user_id, state):
        code = str(uuid4())
        self.codes[code] = ExternalIdentity(
            application.id, application.corp_id, external_user_id, digest(state)
        )
        return SecretStr(code)

    def exchange_identity(self, application, credential, code, state_sha256):
        # Credentials are deliberately never interpolated, persisted or logged.
        if not isinstance(credential, SecretStr):
            raise DomainError("SOURCE_UNAVAILABLE", "合成凭据未绑定。")
        self._exchange_count += 1
        identity = self.codes.pop(code.get_secret_value(), None)
        if (
            identity is None
            or identity.application_id != application.id
            or identity.corp_id != application.corp_id
            or identity.state_sha256 != state_sha256
        ):
            raise DomainError("FORBIDDEN_SCOPE", "合成账号身份/一次性状态不匹配。", 403)
        return identity

    def envelope(self, application, credential, event, *, at=None):
        body = json.dumps(
            Event.model_validate(event).model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        timestamp = (at or self.clock()).isoformat()
        signed = timestamp.encode() + b"\n" + body
        signature = hmac.new(
            credential.get_secret_value().encode(), signed, hashlib.sha256
        ).hexdigest()
        return body, signature, timestamp

    def verify_message(self, application, credential, body, *, signature, timestamp):
        try:
            at = datetime.fromisoformat(timestamp)
            if at.utcoffset() is None or not -30 <= (self.clock() - at).total_seconds() <= 300:
                raise ValueError("time window")
            expected = hmac.new(
                credential.get_secret_value().encode(),
                timestamp.encode() + b"\n" + body,
                hashlib.sha256,
            ).hexdigest()
            if len(body) > 32768 or not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            event = Event.model_validate_json(body)
            if event.corp_id != application.corp_id:
                raise ValueError("corporation")
        except (ValueError, TypeError, AttributeError):
            raise DomainError("FORBIDDEN_SCOPE", "合成入站签名/身份不可验证。", 403) from None
        return SingleMessage(
            application.id,
            event.corp_id,
            event.external_user_id,
            event.message_id,
            event.conversation_kind,
            event.conversation_id,
            event.mentioned,
            event.text,
            hashlib.sha256(body).hexdigest(),
        )

    def set_members(self, application, conversation_id, external_user_ids, *, complete=True):
        members = tuple(sorted(set(external_user_ids)))
        value = Members(
            application.id, conversation_id, members, complete, digest([members, complete])
        )
        self.groups[(application.id, conversation_id)] = value
        return value

    def members(self, application, credential, conversation_id):
        return self.groups.get(
            (application.id, conversation_id),
            Members(
                application.id,
                conversation_id,
                (),
                False,
                "unknown",
            ),
        )

    def send(self, application, credential, request_key, payload):
        if self.before_send:
            self.before_send(application, request_key, payload)
        if payload.get("membership_version") is not None:
            members = self.members(application, credential, payload["target_id"])
            if not members.complete or members.version != payload["membership_version"]:
                raise DomainError("SOURCE_STALE", "当前群成员已变化，未发送引文。")
        key = (application.id, UUID(str(request_key)))
        prior = self.receipts.get(key)
        if prior:
            if prior["payload_sha256"] != digest(payload):
                raise DomainError("DUPLICATE_INTENT_CONFLICT", "原投递编号对应不同正文。")
            return deepcopy(prior)
        self.send_count += 1
        receipt = {
            "provider": "dingtalk",
            "synthetic": True,
            "message_id": "synthetic:" + str(request_key),
            "payload_sha256": digest(payload),
        }
        self.receipts[key] = receipt
        if request_key in self.lose_after_send:
            self.lose_after_send.remove(request_key)
            raise DomainError("EXTERNAL_OUTCOME_UNKNOWN", "合成投递结果待对账。")
        return deepcopy(receipt)

    def lookup(self, application, credential, request_key):
        self.lookup_count += 1
        receipt = self.receipts.get((application.id, UUID(str(request_key))))
        return deepcopy(receipt) if receipt else None
