"""Finite P31 channel input; identity, source permissions and delivery taint are server facts."""

from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from pdos_next.schema_base import StrictModel


class AppSave(StrictModel):
    expected_revision: int = Field(ge=0, strict=True)
    corp_id: str = Field(min_length=1, max_length=160)
    client_id: str = Field(min_length=1, max_length=160)
    robot_code: str = Field(min_length=1, max_length=160)
    secret_arn: str = Field(pattern=r"^acs:kms:[a-z0-9-]+:[0-9]+:secret/[^\s]+$")
    secret_version: str = Field(min_length=1, max_length=160)
    active: bool = Field(strict=True)


class BindingBegin(StrictModel):
    application_id: UUID


class BindingFinish(StrictModel):
    application_id: UUID
    state: SecretStr
    auth_code: SecretStr


class BindingRevoke(StrictModel):
    binding_id: UUID
    expected_epoch: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=1, max_length=500)
    request_key: UUID


class SharePrepare(StrictModel):
    run_id: UUID
    include_citations: bool = Field(default=False, strict=True)


class ShareConfirm(SharePrepare):
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: UUID


class ChannelReference(StrictModel):
    tenant_id: UUID
    message_id: UUID


class DeliveryReference(ChannelReference):
    phase: Literal["received", "answer", "group_notice", "share"]
    consent_id: UUID | None = None
