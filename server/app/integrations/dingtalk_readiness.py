"""Read-only readiness checks for the real DingTalk application gate."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import Engine, func, select, text

from app.db.schema import tables
from app.integrations.dingtalk_crypto import (
    DingTalkCallbackCipher,
    DingTalkCallbackVerificationError,
)
from app.settings import Settings


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class DingTalkReadinessReport:
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)


def _check(name: str, passed: bool, success: str, failure: str) -> ReadinessCheck:
    return ReadinessCheck(name=name, passed=passed, detail=success if passed else failure)


def assess_dingtalk_readiness(
    *,
    engine: Engine,
    settings: Settings,
    tenant_slug: str,
    require_delivery_enabled: bool = False,
) -> DingTalkReadinessReport:
    """Inspect configuration and pilot prerequisites without changing external or local state."""

    checks: list[ReadinessCheck] = []
    public_url = urlparse(settings.public_base_url)
    public_url_valid = (
        public_url.scheme == "https"
        and bool(public_url.netloc)
        and public_url.username is None
        and public_url.password is None
        and public_url.path in {"", "/"}
        and not public_url.query
        and not public_url.fragment
    )
    checks.append(
        _check(
            "public_base_url",
            public_url_valid,
            "HTTPS public base is canonical",
            "PDOS_PUBLIC_BASE_URL must be one canonical HTTPS origin",
        )
    )
    required_secrets = (
        settings.dingtalk_client_secret,
        settings.dingtalk_callback_token,
        settings.dingtalk_callback_aes_key,
        settings.dingtalk_card_callback_secret,
    )
    secrets_present = bool(settings.dingtalk_client_id) and all(
        secret is not None and bool(secret.get_secret_value()) for secret in required_secrets
    )
    checks.append(
        _check(
            "server_credentials",
            secrets_present,
            "all connector credentials are injected",
            "one or more connector credentials are missing",
        )
    )
    checks.append(
        _check(
            "delivery_switch",
            settings.dingtalk_delivery_enabled or not require_delivery_enabled,
            (
                "delivery is enabled"
                if settings.dingtalk_delivery_enabled
                else "delivery remains safely disabled for pre-smoke checks"
            ),
            "PDOS_DINGTALK_DELIVERY_ENABLED must be true for the live-delivery gate",
        )
    )

    with engine.connect() as connection:
        schema_ready = connection.execute(
            text(
                "SELECT to_regclass('cehub_core.dingtalk_tenant_bindings') IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM pg_constraint "
                "WHERE conname = 'ck_dingtalk_tenant_bindings_agent_id_numeric' "
                "AND conrelid = to_regclass('cehub_core.dingtalk_tenant_bindings'))"
            )
        ).scalar_one()
        checks.append(
            _check(
                "migration",
                schema_ready,
                "DingTalk schema contract is present",
                "DingTalk 0026+0027 schema contract is missing",
            )
        )
        if not schema_ready:
            return DingTalkReadinessReport(tuple(checks))
        binding = (
            connection.execute(
                select(tables.dingtalk_tenant_bindings)
                .join(
                    tables.tenants,
                    tables.tenants.c.id == tables.dingtalk_tenant_bindings.c.tenant_id,
                )
                .where(
                    tables.tenants.c.slug == tenant_slug,
                    tables.tenants.c.status == "active",
                )
            )
            .mappings()
            .one_or_none()
        )
        checks.append(
            _check(
                "tenant_binding",
                binding is not None and binding["status"] == "active",
                "active tenant binding exists",
                "active tenant binding was not found",
            )
        )
        if binding is None:
            return DingTalkReadinessReport(tuple(checks))

        expected_redirect = f"{settings.public_base_url.rstrip('/')}/dingtalk/callback"
        binding_complete = all(
            binding[field]
            for field in (
                "agent_id",
                "robot_code",
                "approval_process_code",
                "card_template_id",
                "card_callback_route_key",
            )
        )
        checks.append(
            _check(
                "tenant_capabilities",
                binding_complete,
                "approval, group, and card identifiers are configured",
                "approval, group, or card identifiers are incomplete",
            )
        )
        binding_matches = (
            settings.dingtalk_client_id is not None
            and binding["client_id"] == settings.dingtalk_client_id
            and binding["oauth_redirect_uri"] == expected_redirect
            and binding["callback_route_key"] != binding["card_callback_route_key"]
        )
        checks.append(
            _check(
                "binding_scope",
                binding_matches,
                "client, redirect, and callback namespaces match",
                "client, redirect, or callback namespace mismatch",
            )
        )
        callback_crypto_valid = False
        callback_token = settings.dingtalk_callback_token
        callback_aes_key = settings.dingtalk_callback_aes_key
        if secrets_present and callback_token is not None and callback_aes_key is not None:
            try:
                DingTalkCallbackCipher(
                    token=callback_token.get_secret_value(),
                    encoding_aes_key=callback_aes_key.get_secret_value(),
                    corp_id=binding["corp_id"],
                )
                callback_crypto_valid = True
            except DingTalkCallbackVerificationError:
                pass
        checks.append(
            _check(
                "callback_crypto",
                callback_crypto_valid,
                "event callback crypto configuration is structurally valid",
                "event callback crypto configuration is invalid",
            )
        )

        linked_users = connection.execute(
            select(func.count())
            .select_from(tables.dingtalk_user_bindings)
            .where(
                tables.dingtalk_user_bindings.c.tenant_id == binding["tenant_id"],
                tables.dingtalk_user_bindings.c.status == "active",
            )
        ).scalar_one()
        checks.append(
            _check(
                "linked_users",
                linked_users >= 2,
                f"{linked_users} active users are linked",
                f"only {linked_users} active users are linked; two are required",
            )
        )
        project_channels = connection.execute(
            select(func.count())
            .select_from(tables.dingtalk_project_channels)
            .where(
                tables.dingtalk_project_channels.c.tenant_id == binding["tenant_id"],
                tables.dingtalk_project_channels.c.status == "active",
            )
        ).scalar_one()
        checks.append(
            _check(
                "project_channel",
                project_channels >= 1,
                f"{project_channels} active project channel is configured",
                "no active project channel is configured",
            )
        )
        unresolved = connection.execute(
            select(func.count())
            .select_from(tables.integration_outbox)
            .where(
                tables.integration_outbox.c.tenant_id == binding["tenant_id"],
                tables.integration_outbox.c.provider == "dingtalk",
                tables.integration_outbox.c.status.in_(
                    ("pending", "sending", "retry_wait", "failed", "uncertain", "manual")
                ),
            )
        ).scalar_one()
        checks.append(
            _check(
                "outbox_baseline",
                unresolved == 0,
                "no unresolved DingTalk outbox records",
                f"{unresolved} unresolved DingTalk outbox records require review",
            )
        )
    return DingTalkReadinessReport(tuple(checks))
