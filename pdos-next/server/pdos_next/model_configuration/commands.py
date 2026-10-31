"""Tenant metadata save uses the actual COMMON T1/Receipt/Audit/Outbox transaction."""

from pydantic import Field
from sqlalchemy import select, text

from pdos_next.clock import now
from pdos_next.errors import DomainError
from pdos_next.request_proof import command_inputs_once
from pdos_next.schema_base import StrictModel
from pdos_next.schemas.model_configuration import ModelMetadata, SaveConfiguration


class SavePayload(StrictModel):
    expected_revision: int = Field(ge=0)
    metadata: ModelMetadata
    enabled: bool = False
    confirmation_token: str | None = Field(default=None, min_length=20, max_length=128)


class CurrentAdministrator:
    def __init__(self, session, ctx):
        self.session, self.ctx = session, ctx

    def is_current_human_admin(self, context):
        return (
            context.tenant_id == self.ctx.tenant_id
            and context.actor_id == self.ctx.actor_id == self.ctx.requester_id
            and not self.ctx.run_id
            and not self.ctx.agent_run_id
            and self.session.scalar(text("SELECT kernel_admin_authorized()")) is True
        )


def owner(session, ctx):
    from .persistence import SessionConfigurationStore
    from .service import ConfigurationService

    return ConfigurationService(
        SessionConfigurationStore(session),
        CurrentAdministrator(session, ctx),
        session.info.get("model_configuration_secrets"),
    )


def semantic(payload):
    value = payload.model_dump(mode="json", exclude={"confirmation_token"})
    if payload.metadata.context_window_tokens is None:
        value["metadata"].pop("context_window_tokens")
    # Requests confirmed before connection selection existed must retain their original hash.
    if payload.metadata.connection_id is None and (
        "connection_id" not in payload.metadata.model_fields_set
    ):
        value["metadata"].pop("connection_id", None)
    return value


@command_inputs_once
def prepared(session, ctx, command, scope, payload):
    from .persistence import ModelConfigurationHead
    from .ports import ManagementContext

    if command.product_id is not None or command.source_read_set:
        raise DomainError("FORBIDDEN_SCOPE", "模型设置只接受租户配置元数据。", 403)
    if command.expected_revision != scope.revision:
        raise DomainError("VERSION_CONFLICT", "当前品类范围已变化，请刷新。")
    service = owner(session, ctx)
    context = ManagementContext(ctx.tenant_id, ctx.actor_id)
    service._admin(context)
    head = session.scalar(
        select(ModelConfigurationHead)
        .where(ModelConfigurationHead.tenant_id == ctx.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if head is None:
        raise DomainError("SOURCE_UNAVAILABLE", "模型配置存储尚未建立。")
    return (
        service,
        context,
        service.plan(
            context,
            SaveConfiguration(
                expected_revision=payload.expected_revision,
                metadata=payload.metadata,
                enabled=payload.enabled,
            ),
            now=now(),
        ),
    )


def validate(session, ctx, command, scope, payload):
    prepared(session, ctx, command, scope, payload)


def preview_view(session, ctx, command, scope, payload):
    _, _, plan = prepared(session, ctx, command, scope, payload)
    preview = plan.preview().model_dump(mode="json", exclude={"expires_at", "digest"})
    # The COMMON T1 proof owns the only persisted confirmation clock. This exact
    # deterministic binding detects config/secret rotations without exposing secret IDs.
    return {**preview, "binding_digest": plan.version.binding_digest}


def apply(session, ctx, command, scope, payload):
    from .persistence import ModelConfigurationVersion

    service, context, plan = prepared(session, ctx, command, scope, payload)
    version = service.apply_plan(context, plan, now=now())
    row = session.get(ModelConfigurationVersion, version.id)
    row.action_result = {"requires_requalification": True}
    return row, "model_configuration", "private"


def reading(session, ctx):
    from pdos_next.models import Category

    from .ports import ManagementContext

    actual = owner(session, ctx).reading(ManagementContext(ctx.tenant_id, ctx.actor_id))
    category = session.get(Category, ctx.category_id)
    return {
        "configuration": actual.model_dump(mode="json") if actual else None,
        "category_revision": category.revision,
        "can_edit": True,
    }
