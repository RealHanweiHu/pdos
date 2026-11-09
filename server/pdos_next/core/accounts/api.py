"""Sign-in and account routes. Session tokens go to the web BFF only, never to page code."""

from uuid import UUID

from fastapi import Header
from pydantic import Field

from pdos_next.core.database import tenant_session
from pdos_next.core.schema_base import StrictModel
from pdos_next.core.service import Context
from pdos_next.errors import DomainError

from . import management, sign_in


class SignInInput(StrictModel):
    login_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class InvitationInput(StrictModel):
    token: str = Field(min_length=1, max_length=128)


class InvitationAccept(InvitationInput):
    password: str = Field(min_length=1, max_length=128)


class AccountCreate(StrictModel):
    display_name: str = Field(min_length=1, max_length=160)
    login_name: str = Field(min_length=1, max_length=64)


class AdministratorChange(StrictModel):
    administrator: bool


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise DomainError("UNAUTHENTICATED", "需要有效会话。", 401)
    return authorization[7:]


def register_routes(app, engine, auth_engine, auth_dependency):
    def scope(ctx: Context):
        return tenant_session(
            engine, ctx.tenant_id, actor_id=ctx.actor_id, requester_id=ctx.requester_id
        )

    @app.post("/v1/auth/sign-in")
    def auth_sign_in(
        data: SignInInput,
        x_pdos_client_address: str | None = Header(default=None, max_length=200),
    ):
        return sign_in.sign_in(auth_engine, data.login_name, data.password, x_pdos_client_address)

    @app.post("/v1/auth/sign-out")
    def auth_sign_out(authorization: str | None = Header(default=None)):
        # Ending one's own session never needs more than the token itself.
        ended = sign_in.end_session(auth_engine, _bearer(authorization))
        return {"status": "signed_out" if ended else "already_ended"}

    @app.post("/v1/auth/invitations/inspect")
    def auth_invitation_inspect(data: InvitationInput):
        return sign_in.inspect_invitation(auth_engine, data.token)

    @app.post("/v1/auth/invitations/accept")
    def auth_invitation_accept(data: InvitationAccept):
        return sign_in.accept_invitation(auth_engine, data.token, data.password)

    @app.get("/v1/accounts")
    def accounts(ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return {"items": management.listing(s, ctx)}

    @app.post("/v1/accounts", status_code=201)
    def account_create(data: AccountCreate, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return management.create_account(s, ctx, data.display_name, data.login_name)

    @app.post("/v1/accounts/{principal_id}/invitation")
    def account_invitation(principal_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return management.reissue_invitation(s, ctx, principal_id)

    @app.post("/v1/accounts/{principal_id}/password-reset")
    def account_password_reset(principal_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return management.reset_password(s, ctx, principal_id)

    @app.post("/v1/accounts/{principal_id}/deactivate")
    def account_deactivate(principal_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return management.deactivate(s, ctx, principal_id)

    @app.post("/v1/accounts/{principal_id}/reactivate")
    def account_reactivate(principal_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return management.reactivate(s, ctx, principal_id)

    @app.post("/v1/accounts/{principal_id}/sessions/revoke")
    def account_sessions_revoke(principal_id: UUID, ctx: Context = auth_dependency):
        with scope(ctx) as s:
            return management.revoke_sessions(s, ctx, principal_id)

    @app.post("/v1/accounts/{principal_id}/administrator")
    def account_administrator(
        principal_id: UUID, data: AdministratorChange, ctx: Context = auth_dependency
    ):
        with scope(ctx) as s:
            return management.set_administrator(s, ctx, principal_id, data.administrator)
