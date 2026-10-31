"""Explicit local MiniMax development policy; accounting and stop controls remain active."""

import os
from types import SimpleNamespace

from pdos_next.errors import DomainError
from pdos_next.safety import verify_test_target


def require_local_test_database(session):
    try:
        verify_test_target(session.get_bind())
    except Exception:
        raise DomainError(
            "FORBIDDEN_SCOPE", "开发期不限额仅可用于已核对的本地 pdos_test。", 403
        ) from None


def current(session, ctx):
    from pdos_next.model_configuration.host import TenantRuntime
    from pdos_next.model_configuration.persistence import SessionConfigurationStore

    path = os.environ.get("PDOS_TENANT_RUNTIME_CONFIG")
    if not path:
        return False
    version = SessionConfigurationStore(session).current(ctx.tenant_id)
    if version is None or not version.enabled:
        return False
    metadata = version.metadata
    route = SimpleNamespace(protocol=metadata.protocol, base_url=metadata.base_url,
        model=metadata.model, version=metadata.model_version, connection_id=metadata.connection_id)
    try:
        selected = TenantRuntime(path).development_budget_for(ctx, route)
    except DomainError:
        return False
    if selected:
        require_local_test_database(session)
    return selected
