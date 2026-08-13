"""DingTalk OAuth state, explicit identity linking, and password-free login."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError

from app.auth.repository import AuthContext, AuthRepository
from app.auth.roles import Action, is_allowed
from app.auth.service import AuthService, TokenGrant
from app.db.schema import tables
from app.events.writer import AuditDraft, EventAuditWriter, EventDraft
from app.integrations.dingtalk_client import DingTalkIdentity, DingTalkOAuthClient
from app.settings import Settings

AUTHORIZE_URL = "https://login.dingtalk.com/oauth2/auth"
STATE_TTL = timedelta(minutes=5)


class DingTalkOAuthError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    expires_in: int


@dataclass(frozen=True)
class OAuthState:
    tenant_id: UUID
    corp_id: str
    client_id: str
    mode: str
    link_user_id: UUID | None
    return_path: str


@dataclass(frozen=True)
class OAuthResult:
    grant: TokenGrant
    mode: str
    return_path: str
    linked: bool


def _state_digest(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


class DingTalkOAuthRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_state(
        self,
        *,
        tenant_slug: str | None,
        context: AuthContext | None,
        mode: str,
        return_path: str,
        now: datetime,
    ) -> tuple[str, OAuthState, str]:
        if mode == "link":
            if context is None or not is_allowed(context.user.role, Action.INTEGRATION_BIND_SELF):
                raise DingTalkOAuthError("DINGTALK_LINK_FORBIDDEN")
            tenant_id = context.tenant.id
            link_user_id = context.user.id
            binding_where = tables.dingtalk_tenant_bindings.c.tenant_id == tenant_id
        else:
            if context is not None or tenant_slug is None:
                raise DingTalkOAuthError("DINGTALK_INVALID_REQUEST")
            link_user_id = None
            binding_where = tables.tenants.c.slug == tenant_slug

        statement = (
            select(
                tables.dingtalk_tenant_bindings.c.tenant_id,
                tables.dingtalk_tenant_bindings.c.corp_id,
                tables.dingtalk_tenant_bindings.c.client_id,
                tables.dingtalk_tenant_bindings.c.oauth_redirect_uri,
            )
            .select_from(
                tables.dingtalk_tenant_bindings.join(
                    tables.tenants,
                    tables.tenants.c.id == tables.dingtalk_tenant_bindings.c.tenant_id,
                )
            )
            .where(
                binding_where,
                tables.dingtalk_tenant_bindings.c.status == "active",
                tables.tenants.c.status == "active",
            )
        )
        raw_state = secrets.token_urlsafe(32)
        with self._engine.begin() as connection:
            row = connection.execute(statement).mappings().one_or_none()
            if row is None:
                raise DingTalkOAuthError("DINGTALK_NOT_CONFIGURED")
            connection.execute(
                tables.dingtalk_oauth_states.insert().values(
                    id=uuid4(),
                    tenant_id=row["tenant_id"],
                    state_digest=_state_digest(raw_state),
                    mode=mode,
                    link_user_id=link_user_id,
                    return_path=return_path,
                    expires_at=now + STATE_TTL,
                    created_at=now,
                )
            )
        return (
            raw_state,
            OAuthState(
                tenant_id=row["tenant_id"],
                corp_id=row["corp_id"],
                client_id=row["client_id"],
                mode=mode,
                link_user_id=link_user_id,
                return_path=return_path,
            ),
            row["oauth_redirect_uri"],
        )

    def consume_state(self, *, raw_state: str, now: datetime) -> OAuthState:
        digest = _state_digest(raw_state)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    select(
                        tables.dingtalk_oauth_states.c.tenant_id,
                        tables.dingtalk_oauth_states.c.mode,
                        tables.dingtalk_oauth_states.c.link_user_id,
                        tables.dingtalk_oauth_states.c.return_path,
                        tables.dingtalk_tenant_bindings.c.corp_id,
                        tables.dingtalk_tenant_bindings.c.client_id,
                    )
                    .select_from(
                        tables.dingtalk_oauth_states.join(
                            tables.dingtalk_tenant_bindings,
                            tables.dingtalk_tenant_bindings.c.tenant_id
                            == tables.dingtalk_oauth_states.c.tenant_id,
                        )
                    )
                    .where(
                        tables.dingtalk_oauth_states.c.state_digest == digest,
                        tables.dingtalk_oauth_states.c.consumed_at.is_(None),
                        tables.dingtalk_oauth_states.c.expires_at > now,
                        tables.dingtalk_tenant_bindings.c.status == "active",
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise DingTalkOAuthError("DINGTALK_STATE_INVALID")
            result = connection.execute(
                update(tables.dingtalk_oauth_states)
                .where(
                    tables.dingtalk_oauth_states.c.state_digest == digest,
                    tables.dingtalk_oauth_states.c.consumed_at.is_(None),
                )
                .values(consumed_at=now)
            )
            if result.rowcount != 1:
                raise DingTalkOAuthError("DINGTALK_STATE_INVALID")
        return OAuthState(**dict(row))

    def link_identity(
        self,
        *,
        state: OAuthState,
        identity: DingTalkIdentity,
        now: datetime,
    ) -> AuthContext:
        if state.link_user_id is None:
            raise DingTalkOAuthError("DINGTALK_INVALID_REQUEST")
        with self._engine.begin() as connection:
            user = connection.execute(
                select(tables.users.c.id).where(
                    tables.users.c.tenant_id == state.tenant_id,
                    tables.users.c.id == state.link_user_id,
                    tables.users.c.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if user is None:
                raise DingTalkOAuthError("DINGTALK_IDENTITY_NOT_LINKED")
            external_owner = connection.execute(
                select(tables.dingtalk_user_bindings.c.user_id).where(
                    tables.dingtalk_user_bindings.c.tenant_id == state.tenant_id,
                    tables.dingtalk_user_bindings.c.corp_id == identity.corp_id,
                    tables.dingtalk_user_bindings.c.open_id == identity.open_id,
                )
            ).scalar_one_or_none()
            if external_owner is not None and external_owner != state.link_user_id:
                raise DingTalkOAuthError("DINGTALK_IDENTITY_CONFLICT")
            existing = connection.execute(
                select(tables.dingtalk_user_bindings.c.id).where(
                    tables.dingtalk_user_bindings.c.tenant_id == state.tenant_id,
                    tables.dingtalk_user_bindings.c.user_id == state.link_user_id,
                )
            ).scalar_one_or_none()
            binding_id = existing or uuid4()
            try:
                if existing is None:
                    connection.execute(
                        tables.dingtalk_user_bindings.insert().values(
                            id=binding_id,
                            tenant_id=state.tenant_id,
                            user_id=state.link_user_id,
                            corp_id=identity.corp_id,
                            open_id=identity.open_id,
                            union_id=identity.union_id,
                            status="active",
                            bound_at=now,
                        )
                    )
                else:
                    connection.execute(
                        update(tables.dingtalk_user_bindings)
                        .where(
                            tables.dingtalk_user_bindings.c.tenant_id == state.tenant_id,
                            tables.dingtalk_user_bindings.c.id == binding_id,
                        )
                        .values(
                            corp_id=identity.corp_id,
                            open_id=identity.open_id,
                            union_id=identity.union_id,
                            status="active",
                            bound_at=now,
                            revoked_at=None,
                        )
                    )
            except IntegrityError as error:
                raise DingTalkOAuthError("DINGTALK_IDENTITY_CONFLICT") from error
            EventAuditWriter(
                connection,
                tenant_id=state.tenant_id,
                actor_user_id=state.link_user_id,
            ).record(
                EventDraft(
                    event_id=f"dingtalk-identity:{binding_id}:linked:{uuid4()}",
                    event_type="DINGTALK_IDENTITY_LINKED",
                    source="dingtalk_connector_service",
                    entity_id=binding_id,
                    payload={"user_id": str(state.link_user_id), "status": "linked"},
                    occurred_at=now,
                ),
                AuditDraft(
                    action="dingtalk.identity.link",
                    after_snapshot={"user_id": str(state.link_user_id), "status": "active"},
                    context={"authentication_method": "dingtalk_oauth"},
                ),
            )
        context = AuthRepository(self._engine).find_user_context(state.link_user_id)
        if context is None:
            raise DingTalkOAuthError("DINGTALK_IDENTITY_NOT_LINKED")
        return context

    def find_login_context(self, *, state: OAuthState, identity: DingTalkIdentity) -> AuthContext:
        statement = select(tables.dingtalk_user_bindings.c.user_id).where(
            tables.dingtalk_user_bindings.c.tenant_id == state.tenant_id,
            tables.dingtalk_user_bindings.c.corp_id == identity.corp_id,
            tables.dingtalk_user_bindings.c.open_id == identity.open_id,
            tables.dingtalk_user_bindings.c.status == "active",
        )
        with self._engine.connect() as connection:
            user_id = connection.execute(statement).scalar_one_or_none()
        if user_id is None:
            raise DingTalkOAuthError("DINGTALK_IDENTITY_NOT_LINKED")
        context = AuthRepository(self._engine).find_user_context(user_id)
        if context is None or not context.user.is_active or context.tenant.status != "active":
            raise DingTalkOAuthError("DINGTALK_IDENTITY_NOT_LINKED")
        return context


class DingTalkOAuthService:
    def __init__(
        self,
        *,
        repository: DingTalkOAuthRepository,
        client: DingTalkOAuthClient,
        auth_service: AuthService,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._client = client
        self._auth_service = auth_service
        self._settings = settings

    def start(
        self,
        *,
        tenant_slug: str | None,
        context: AuthContext | None,
        mode: str,
        return_path: str,
    ) -> OAuthStart:
        self._credentials()
        now = datetime.now(UTC)
        raw_state, state, redirect_uri = self._repository.create_state(
            tenant_slug=tenant_slug,
            context=context,
            mode=mode,
            return_path=return_path,
            now=now,
        )
        if state.client_id != self._settings.dingtalk_client_id:
            raise DingTalkOAuthError("DINGTALK_CONFIGURATION_MISMATCH")
        query = urlencode(
            {
                "client_id": state.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid corpid",
                "prompt": "consent",
                "state": raw_state,
            }
        )
        return OAuthStart(authorization_url=f"{AUTHORIZE_URL}?{query}", expires_in=300)

    def callback(self, *, auth_code: str, raw_state: str) -> OAuthResult:
        client_id, client_secret = self._credentials()
        now = datetime.now(UTC)
        state = self._repository.consume_state(raw_state=raw_state, now=now)
        if state.client_id != client_id:
            raise DingTalkOAuthError("DINGTALK_CONFIGURATION_MISMATCH")
        identity = self._client.exchange_identity(
            client_id=client_id,
            client_secret=client_secret,
            auth_code=auth_code,
        )
        if not secrets.compare_digest(identity.corp_id, state.corp_id):
            raise DingTalkOAuthError("DINGTALK_CORP_MISMATCH")
        if state.mode == "link":
            context = self._repository.link_identity(state=state, identity=identity, now=now)
            linked = True
        else:
            context = self._repository.find_login_context(state=state, identity=identity)
            linked = False
        grant = self._auth_service.issue_external_login(
            context,
            authentication_method="dingtalk_oauth",
        )
        return OAuthResult(
            grant=grant,
            mode=state.mode,
            return_path=state.return_path,
            linked=linked,
        )

    def _credentials(self) -> tuple[str, str]:
        client_id = self._settings.dingtalk_client_id
        client_secret = self._settings.dingtalk_client_secret
        if not client_id or client_secret is None:
            raise DingTalkOAuthError("DINGTALK_NOT_CONFIGURED")
        return client_id, client_secret.get_secret_value()
