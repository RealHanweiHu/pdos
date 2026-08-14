"""DingTalk OAuth HTTP boundary."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx2
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.auth import TokenResponse, current_context, get_auth_service, no_store
from app.auth.errors import ObjectPermissionDeniedError
from app.auth.project_access import ProjectAccessService, SqlProjectAccessRepository
from app.auth.repository import AuthContext
from app.auth.roles import Action, is_allowed
from app.auth.service import AuthService
from app.db.engine import get_engine
from app.db.schema import tables
from app.integrations.dingtalk_callbacks import (
    DingTalkCallbackError,
    DingTalkCallbackRepository,
    DingTalkCallbackService,
)
from app.integrations.dingtalk_cards import (
    DingTalkCardCallbackError,
    DingTalkCardCallbackService,
)
from app.integrations.dingtalk_client import DingTalkClientError, DingTalkOAuthClient
from app.integrations.dingtalk_crypto import DingTalkCallbackVerificationError
from app.integrations.dingtalk_oauth import (
    DingTalkOAuthError,
    DingTalkOAuthRepository,
    DingTalkOAuthService,
)
from app.integrations.dingtalk_outbox import (
    DingTalkIntentError,
    DingTalkIntentService,
    OutboxRecord,
)
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/integrations/dingtalk", tags=["dingtalk-integration"])


class OAuthLoginStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$",
    )
    return_path: str = Field(default="/", min_length=1, max_length=512)

    @field_validator("tenant_slug", mode="before")
    @classmethod
    def normalize_slug(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("return_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "\\" in value:
            raise ValueError("return_path must be a local path")
        return value


class OAuthLinkStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_path: str = Field(default="/settings/integrations", min_length=1, max_length=512)

    @field_validator("return_path")
    @classmethod
    def require_local_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "\\" in value:
            raise ValueError("return_path must be a local path")
        return value


class OAuthStartResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorization_url: str
    expires_in: int


class OAuthCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auth_code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=32, max_length=256)


class OAuthCallbackResponse(TokenResponse):
    mode: Literal["login", "link"]
    linked: bool
    return_path: str


class EncryptedCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encrypt: str = Field(min_length=1, max_length=1_400_000)


class EncryptedCallbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    msg_signature: str
    timeStamp: str
    nonce: str
    encrypt: str


class CardCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["actionCallback"]
    corpId: str = Field(min_length=1, max_length=128)
    userId: str = Field(min_length=1, max_length=256)
    outTrackId: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=16_384)


class TenantBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corp_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    agent_id: str | None = Field(default=None, max_length=20, pattern=r"^[1-9][0-9]*$")
    robot_code: str | None = Field(default=None, max_length=128)
    oauth_redirect_uri: str = Field(min_length=1, max_length=1024)
    callback_route_key: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    approval_process_code: str | None = Field(default=None, max_length=128)
    card_template_id: str | None = Field(default=None, max_length=128)
    card_callback_route_key: str | None = Field(
        default=None,
        min_length=16,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    status: Literal["disabled", "active"] = "disabled"

    @field_validator("oauth_redirect_uri")
    @classmethod
    def validate_redirect_uri(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("oauth_redirect_uri must be an https URL without userinfo")
        return value

    @field_validator(
        "corp_id",
        "client_id",
        "agent_id",
        "robot_code",
        "approval_process_code",
        "card_template_id",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class TenantBindingResponse(TenantBindingRequest):
    tenant_id: UUID


class ProjectChannelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open_conversation_id: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=256)


class ProjectChannelResponse(ProjectChannelRequest):
    id: UUID
    project_id: UUID
    status: str


class GroupMarkdownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    @field_validator("title", "text")
    @classmethod
    def reject_client_links(cls, value: str) -> str:
        lowered = value.lower()
        if any(marker in lowered for marker in ("http://", "https://", "](")):
            raise ValueError("notification links are server-built")
        return value


class GateApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_user_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class InteractiveCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_user_id: UUID
    action: Literal["acknowledge", "open"]
    title: str = Field(min_length=1, max_length=128)
    body: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class OutboxResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID | None
    operation: str
    status: str
    attempt_count: int
    remote_reference: str | None
    last_error_code: str | None


class OutboxListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[OutboxResponse]


class OutboxReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["confirmed_delivered", "confirmed_not_delivered"]
    remote_reference: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def require_remote_reference_for_delivery(self) -> OutboxReconcileRequest:
        if self.outcome == "confirmed_delivered" and self.remote_reference is None:
            raise ValueError("confirmed delivery requires remote_reference")
        if self.outcome == "confirmed_not_delivered" and self.remote_reference is not None:
            raise ValueError("confirmed non-delivery cannot include remote_reference")
        return self


class OutboxReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["REPLAY_CONFIRMED"]


class IntegrationStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    configured: bool
    binding_status: str | None
    corp_id: str | None
    linked: bool
    delivery_enabled: bool


class ProjectIntegrationStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    channel_configured: bool
    channel_display_name: str | None
    delivery_enabled: bool
    outbox: list[OutboxResponse]


class ApprovalIntentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    outbox: OutboxResponse


class CardIntentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    out_track_id: str
    outbox: OutboxResponse


def get_dingtalk_http_client() -> Iterator[httpx2.Client]:
    with httpx2.Client(follow_redirects=False, trust_env=False) as client:
        yield client


def get_dingtalk_oauth_service(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    http_client: Annotated[httpx2.Client, Depends(get_dingtalk_http_client)],
) -> DingTalkOAuthService:
    return DingTalkOAuthService(
        repository=DingTalkOAuthRepository(engine),
        client=DingTalkOAuthClient(http_client),
        auth_service=auth_service,
        settings=settings,
    )


def get_dingtalk_callback_service(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DingTalkCallbackService:
    return DingTalkCallbackService(
        repository=DingTalkCallbackRepository(engine),
        settings=settings,
    )


def get_dingtalk_card_callback_service(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DingTalkCardCallbackService:
    return DingTalkCardCallbackService(engine=engine, settings=settings)


def get_dingtalk_intent_service(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DingTalkIntentService:
    return DingTalkIntentService(engine, settings)


def _outbox_response(record: OutboxRecord) -> OutboxResponse:
    return OutboxResponse(
        id=record.id,
        project_id=record.project_id,
        operation=record.operation,
        status=record.status,
        attempt_count=record.attempt_count,
        remote_reference=record.remote_reference,
        last_error_code=record.last_error_code,
    )


def _integration_error(error: DingTalkIntentError | ObjectPermissionDeniedError) -> HTTPException:
    if isinstance(error, ObjectPermissionDeniedError):
        code = "OBJECT_PERMISSION_DENIED"
        status_code = status.HTTP_403_FORBIDDEN
    else:
        code = error.code
        if code == "DINGTALK_OUTBOX_NOT_FOUND":
            status_code = status.HTTP_404_NOT_FOUND
        elif code in {
            "DINGTALK_IDEMPOTENCY_CONFLICT",
            "DINGTALK_RECONCILIATION_NOT_ALLOWED",
            "DINGTALK_REPLAY_NOT_ALLOWED",
            "DINGTALK_REPLAY_LIMIT_REACHED",
        }:
            status_code = status.HTTP_409_CONFLICT
        elif code == "DINGTALK_DELIVERY_DISABLED":
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": "DingTalk integration request was rejected"},
    )


def _authorize_project(
    *,
    engine: Engine,
    context: AuthContext,
    project_id: UUID,
    action: Action,
) -> None:
    ProjectAccessService(SqlProjectAccessRepository(engine)).authorize(
        context=context,
        project_id=project_id,
        action=action,
    )


def _audit_only(
    *,
    connection: Connection,
    context: AuthContext,
    action: str,
    entity: str,
    entity_id: UUID,
    project_id: UUID | None,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> None:
    values: dict[str, object] = {
        "tenant_id": context.tenant.id,
        "project_id": project_id,
        "actor_user_id": context.user.id,
        "event_id": f"dingtalk-audit:{uuid4()}",
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "context": {},
    }
    if before is not None:
        values["before_snapshot"] = before
    if after is not None:
        values["after_snapshot"] = after
    connection.execute(tables.audit_log.insert().values(**values))


def _require_tenant_integration_action(context: AuthContext, action: Action) -> None:
    if not is_allowed(context.user.role, action):
        raise _integration_error(ObjectPermissionDeniedError())


def _map_oauth_error(error: DingTalkOAuthError | DingTalkClientError) -> HTTPException:
    code = error.code if isinstance(error, DingTalkOAuthError) else str(error)
    if code in {"DINGTALK_NOT_CONFIGURED", "DINGTALK_CONFIGURATION_MISMATCH"}:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": code, "message": "DingTalk login is unavailable"},
        )
    if code == "DINGTALK_LINK_FORBIDDEN":
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": code, "message": "DingTalk identity linking is not allowed"},
        )
    if code == "DINGTALK_IDENTITY_CONFLICT":
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": code, "message": "This DingTalk identity is already linked"},
        )
    if code == "DINGTALK_OAUTH_UNAVAILABLE":
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": code, "message": "DingTalk authorization could not be verified"},
        )
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code, "message": "DingTalk authorization was rejected"},
    )


@router.put("/config", response_model=TenantBindingResponse)
def put_tenant_binding(
    payload: TenantBindingRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TenantBindingResponse:
    no_store(response)
    _require_tenant_integration_action(context, Action.INTEGRATION_MANAGE)
    expected_redirect_uri = f"{settings.public_base_url.rstrip('/')}/dingtalk/callback"
    if (
        settings.dingtalk_client_id is not None and payload.client_id != settings.dingtalk_client_id
    ) or payload.oauth_redirect_uri != expected_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "DINGTALK_CONFIGURATION_MISMATCH",
                "message": "DingTalk integration request was rejected",
            },
        )
    values = {**payload.model_dump(), "configured_by_user_id": context.user.id}
    with engine.begin() as connection:
        before_row = (
            connection.execute(
                select(tables.dingtalk_tenant_bindings).where(
                    tables.dingtalk_tenant_bindings.c.tenant_id == context.tenant.id
                )
            )
            .mappings()
            .one_or_none()
        )
        statement = (
            pg_insert(tables.dingtalk_tenant_bindings)
            .values(tenant_id=context.tenant.id, **values)
            .on_conflict_do_update(
                index_elements=[tables.dingtalk_tenant_bindings.c.tenant_id],
                set_={**values, "updated_at": datetime.now(UTC)},
            )
            .returning(tables.dingtalk_tenant_bindings)
        )
        row = connection.execute(statement).mappings().one()
        public_snapshot = {
            key: row[key]
            for key in (
                "corp_id",
                "client_id",
                "agent_id",
                "robot_code",
                "oauth_redirect_uri",
                "callback_route_key",
                "approval_process_code",
                "card_template_id",
                "card_callback_route_key",
                "status",
            )
        }
        _audit_only(
            connection=connection,
            context=context,
            action="dingtalk.integration.configure",
            entity="dingtalk_tenant_binding",
            entity_id=context.tenant.id,
            project_id=None,
            before=(
                {key: before_row[key] for key in public_snapshot}
                if before_row is not None
                else None
            ),
            after=public_snapshot,
        )
    return TenantBindingResponse(tenant_id=context.tenant.id, **public_snapshot)


@router.get("/status", response_model=IntegrationStatusResponse)
def get_integration_status(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IntegrationStatusResponse:
    no_store(response)
    _require_tenant_integration_action(context, Action.INTEGRATION_VIEW)
    with engine.connect() as connection:
        binding = (
            connection.execute(
                select(
                    tables.dingtalk_tenant_bindings.c.corp_id,
                    tables.dingtalk_tenant_bindings.c.status,
                ).where(tables.dingtalk_tenant_bindings.c.tenant_id == context.tenant.id)
            )
            .mappings()
            .one_or_none()
        )
        linked = (
            connection.execute(
                select(tables.dingtalk_user_bindings.c.id).where(
                    tables.dingtalk_user_bindings.c.tenant_id == context.tenant.id,
                    tables.dingtalk_user_bindings.c.user_id == context.user.id,
                    tables.dingtalk_user_bindings.c.status == "active",
                )
            ).scalar_one_or_none()
            is not None
        )
    return IntegrationStatusResponse(
        configured=binding is not None,
        binding_status=binding["status"] if binding is not None else None,
        corp_id=binding["corp_id"] if binding is not None else None,
        linked=linked,
        delivery_enabled=settings.dingtalk_delivery_enabled,
    )


@router.get(
    "/projects/{project_id}/status",
    response_model=ProjectIntegrationStatusResponse,
)
def get_project_integration_status(
    project_id: UUID,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
) -> ProjectIntegrationStatusResponse:
    no_store(response)
    try:
        _authorize_project(
            engine=engine,
            context=context,
            project_id=project_id,
            action=Action.INTEGRATION_VIEW,
        )
    except ObjectPermissionDeniedError as error:
        raise _integration_error(error) from error
    with engine.connect() as connection:
        channel = (
            connection.execute(
                select(tables.dingtalk_project_channels.c.display_name).where(
                    tables.dingtalk_project_channels.c.tenant_id == context.tenant.id,
                    tables.dingtalk_project_channels.c.project_id == project_id,
                    tables.dingtalk_project_channels.c.status == "active",
                )
            )
            .mappings()
            .one_or_none()
        )
    records = service.list_outbox(
        tenant_id=context.tenant.id,
        project_id=project_id,
        limit=20,
    )
    return ProjectIntegrationStatusResponse(
        project_id=project_id,
        channel_configured=channel is not None,
        channel_display_name=channel["display_name"] if channel is not None else None,
        delivery_enabled=settings.dingtalk_delivery_enabled,
        outbox=[_outbox_response(record) for record in records],
    )


@router.get("/outbox", response_model=OutboxListResponse)
def list_dingtalk_outbox(
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> OutboxListResponse:
    no_store(response)
    _require_tenant_integration_action(context, Action.INTEGRATION_MANAGE)
    records = service.list_outbox(
        tenant_id=context.tenant.id,
        project_id=project_id,
        limit=limit,
    )
    return OutboxListResponse(items=[_outbox_response(record) for record in records])


@router.post("/outbox/{outbox_id}/reconcile", response_model=OutboxResponse)
def reconcile_dingtalk_outbox(
    outbox_id: UUID,
    payload: OutboxReconcileRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
) -> OutboxResponse:
    no_store(response)
    _require_tenant_integration_action(context, Action.INTEGRATION_MANAGE)
    try:
        record = service.reconcile_outbox(
            tenant_id=context.tenant.id,
            outbox_id=outbox_id,
            actor_user_id=context.user.id,
            outcome=payload.outcome,
            remote_reference=payload.remote_reference,
        )
    except DingTalkIntentError as error:
        raise _integration_error(error) from error
    return _outbox_response(record)


@router.post("/outbox/{outbox_id}/replay", response_model=OutboxResponse)
def replay_dingtalk_outbox(
    outbox_id: UUID,
    payload: OutboxReplayRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
) -> OutboxResponse:
    no_store(response)
    _require_tenant_integration_action(context, Action.INTEGRATION_MANAGE)
    try:
        record = service.replay_outbox(
            tenant_id=context.tenant.id,
            outbox_id=outbox_id,
            actor_user_id=context.user.id,
        )
    except DingTalkIntentError as error:
        raise _integration_error(error) from error
    return _outbox_response(record)


@router.put("/projects/{project_id}/channel", response_model=ProjectChannelResponse)
def put_project_channel(
    project_id: UUID,
    payload: ProjectChannelRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ProjectChannelResponse:
    no_store(response)
    try:
        _authorize_project(
            engine=engine,
            context=context,
            project_id=project_id,
            action=Action.INTEGRATION_PROJECT_MANAGE,
        )
    except ObjectPermissionDeniedError as error:
        raise _integration_error(error) from error
    with engine.begin() as connection:
        before = (
            connection.execute(
                select(tables.dingtalk_project_channels).where(
                    tables.dingtalk_project_channels.c.tenant_id == context.tenant.id,
                    tables.dingtalk_project_channels.c.project_id == project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        channel_id = before["id"] if before is not None else uuid4()
        values = {
            "open_conversation_id": payload.open_conversation_id,
            "display_name": payload.display_name,
            "status": "active",
            "configured_by_user_id": context.user.id,
        }
        row = (
            connection.execute(
                pg_insert(tables.dingtalk_project_channels)
                .values(
                    id=channel_id,
                    tenant_id=context.tenant.id,
                    project_id=project_id,
                    **values,
                )
                .on_conflict_do_update(
                    constraint="uq_dingtalk_project_channels_tenant_project",
                    set_={**values, "updated_at": datetime.now(UTC)},
                )
                .returning(tables.dingtalk_project_channels)
            )
            .mappings()
            .one()
        )
        snapshot = {
            "open_conversation_id": row["open_conversation_id"],
            "display_name": row["display_name"],
            "status": row["status"],
        }
        _audit_only(
            connection=connection,
            context=context,
            action="dingtalk.project_channel.configure",
            entity="dingtalk_project_channel",
            entity_id=row["id"],
            project_id=project_id,
            before=(
                {
                    "open_conversation_id": before["open_conversation_id"],
                    "display_name": before["display_name"],
                    "status": before["status"],
                }
                if before is not None
                else None
            ),
            after=snapshot,
        )
    return ProjectChannelResponse(id=row["id"], project_id=project_id, **snapshot)


@router.post("/projects/{project_id}/notifications", response_model=OutboxResponse)
def enqueue_project_notification(
    project_id: UUID,
    payload: GroupMarkdownRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
) -> OutboxResponse:
    no_store(response)
    try:
        _authorize_project(
            engine=engine,
            context=context,
            project_id=project_id,
            action=Action.INTEGRATION_PROJECT_SEND,
        )
        record = service.enqueue_group_markdown(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            title=payload.title,
            text=payload.text,
            idempotency_key=payload.idempotency_key,
        )
    except (DingTalkIntentError, ObjectPermissionDeniedError) as error:
        raise _integration_error(error) from error
    return _outbox_response(record)


@router.post(
    "/projects/{project_id}/gates/{gate_id}/approval",
    response_model=ApprovalIntentResponse,
)
def enqueue_gate_approval(
    project_id: UUID,
    gate_id: UUID,
    payload: GateApprovalRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
) -> ApprovalIntentResponse:
    no_store(response)
    try:
        _authorize_project(
            engine=engine,
            context=context,
            project_id=project_id,
            action=Action.INTEGRATION_PROJECT_SEND,
        )
        intent = service.enqueue_gate_approval(
            tenant_id=context.tenant.id,
            project_id=project_id,
            gate_id=gate_id,
            actor_user_id=context.user.id,
            approver_user_id=payload.approver_user_id,
            idempotency_key=payload.idempotency_key,
        )
    except (DingTalkIntentError, ObjectPermissionDeniedError) as error:
        raise _integration_error(error) from error
    return ApprovalIntentResponse(id=intent.id, outbox=_outbox_response(intent.outbox))


@router.post("/projects/{project_id}/cards", response_model=CardIntentResponse)
def enqueue_interactive_card(
    project_id: UUID,
    payload: InteractiveCardRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    engine: Annotated[Engine, Depends(get_engine)],
    service: Annotated[DingTalkIntentService, Depends(get_dingtalk_intent_service)],
) -> CardIntentResponse:
    no_store(response)
    try:
        _authorize_project(
            engine=engine,
            context=context,
            project_id=project_id,
            action=Action.INTEGRATION_PROJECT_SEND,
        )
        intent = service.enqueue_interactive_card(
            tenant_id=context.tenant.id,
            project_id=project_id,
            actor_user_id=context.user.id,
            recipient_user_id=payload.recipient_user_id,
            action_key=payload.action,
            title=payload.title,
            body=payload.body,
            idempotency_key=payload.idempotency_key,
        )
    except (DingTalkIntentError, ObjectPermissionDeniedError) as error:
        raise _integration_error(error) from error
    return CardIntentResponse(
        id=intent.id,
        out_track_id=intent.out_track_id,
        outbox=_outbox_response(intent.outbox),
    )


@router.post("/oauth/login/start", response_model=OAuthStartResponse)
def start_login(
    payload: OAuthLoginStartRequest,
    response: Response,
    service: Annotated[DingTalkOAuthService, Depends(get_dingtalk_oauth_service)],
) -> OAuthStartResponse:
    no_store(response)
    try:
        started = service.start(
            tenant_slug=payload.tenant_slug,
            context=None,
            mode="login",
            return_path=payload.return_path,
        )
    except (DingTalkOAuthError, DingTalkClientError) as error:
        raise _map_oauth_error(error) from error
    return OAuthStartResponse(**started.__dict__)


@router.post("/oauth/link/start", response_model=OAuthStartResponse)
def start_link(
    payload: OAuthLinkStartRequest,
    response: Response,
    context: Annotated[AuthContext, Depends(current_context)],
    service: Annotated[DingTalkOAuthService, Depends(get_dingtalk_oauth_service)],
) -> OAuthStartResponse:
    no_store(response)
    try:
        started = service.start(
            tenant_slug=None,
            context=context,
            mode="link",
            return_path=payload.return_path,
        )
    except (DingTalkOAuthError, DingTalkClientError) as error:
        raise _map_oauth_error(error) from error
    return OAuthStartResponse(**started.__dict__)


@router.post("/oauth/callback", response_model=OAuthCallbackResponse)
def oauth_callback(
    payload: OAuthCallbackRequest,
    response: Response,
    service: Annotated[DingTalkOAuthService, Depends(get_dingtalk_oauth_service)],
) -> OAuthCallbackResponse:
    no_store(response)
    try:
        result = service.callback(auth_code=payload.auth_code, raw_state=payload.state)
    except (DingTalkOAuthError, DingTalkClientError) as error:
        raise _map_oauth_error(error) from error
    return OAuthCallbackResponse(
        access_token=result.grant.access_token,
        expires_in=result.grant.expires_in,
        mode=result.mode,  # type: ignore[arg-type]
        linked=result.linked,
        return_path=result.return_path,
    )


@router.post("/callback/{route_key}", response_model=EncryptedCallbackResponse)
def encrypted_callback(
    route_key: str,
    payload: EncryptedCallbackRequest,
    signature: str,
    timestamp: str,
    nonce: str,
    response: Response,
    service: Annotated[DingTalkCallbackService, Depends(get_dingtalk_callback_service)],
) -> EncryptedCallbackResponse:
    no_store(response)
    try:
        acknowledged = service.handle_encrypted_event(
            route_key=route_key,
            encrypt=payload.encrypt,
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
        )
    except DingTalkCallbackVerificationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": error.code, "message": "DingTalk callback was rejected"},
        ) from error
    except DingTalkCallbackError as error:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if error.code == "DINGTALK_CALLBACK_NOT_CONFIGURED"
            else status.HTTP_404_NOT_FOUND
            if error.code == "DINGTALK_CALLBACK_ROUTE_UNKNOWN"
            else status.HTTP_409_CONFLICT
            if error.code == "DINGTALK_CALLBACK_REPLAY_CONFLICT"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": "DingTalk callback was rejected"},
        ) from error
    return EncryptedCallbackResponse(
        msg_signature=acknowledged.msg_signature,
        timeStamp=acknowledged.time_stamp,
        nonce=acknowledged.nonce,
        encrypt=acknowledged.encrypt,
    )


@router.post("/card-callback/{route_key}")
def card_callback(
    route_key: str,
    payload: CardCallbackRequest,
    response: Response,
    service: Annotated[
        DingTalkCardCallbackService,
        Depends(get_dingtalk_card_callback_service),
    ],
    x_ddpaas_signature_timestamp: Annotated[
        str,
        Header(alias="x-ddpaas-signature-timestamp", min_length=10, max_length=13),
    ],
    x_ddpaas_signature: Annotated[
        str,
        Header(alias="x-ddpaas-signature", min_length=1, max_length=256),
    ],
) -> dict[str, object]:
    no_store(response)
    try:
        service.handle(
            route_key=route_key,
            timestamp=x_ddpaas_signature_timestamp,
            signature=x_ddpaas_signature,
            payload=payload.model_dump(),
        )
    except DingTalkCardCallbackError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if error.code == "DINGTALK_CARD_REPLAY_CONFLICT"
                else status.HTTP_503_SERVICE_UNAVAILABLE
                if error.code == "DINGTALK_CARD_CALLBACK_NOT_CONFIGURED"
                else status.HTTP_401_UNAUTHORIZED
            ),
            detail={"code": error.code, "message": "DingTalk card callback was rejected"},
        ) from error
    return {}
