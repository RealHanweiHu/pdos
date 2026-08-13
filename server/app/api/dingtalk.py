"""DingTalk OAuth HTTP boundary."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine

from app.api.auth import TokenResponse, current_context, get_auth_service, no_store
from app.auth.repository import AuthContext
from app.auth.service import AuthService
from app.db.engine import get_engine
from app.integrations.dingtalk_client import DingTalkClientError, DingTalkOAuthClient
from app.integrations.dingtalk_oauth import (
    DingTalkOAuthError,
    DingTalkOAuthRepository,
    DingTalkOAuthService,
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
