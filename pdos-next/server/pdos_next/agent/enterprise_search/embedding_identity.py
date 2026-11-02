"""Embedding uses the same trusted connection provider identity as chat and P26."""

import re

from pdos_next.errors import DomainError


def canonical_provider(port, tenant_id, metadata, *, required=True):
    try:
        resolver = getattr(port, "provider_for", None)
        value = resolver(tenant_id, metadata) if callable(resolver) else None
        if not isinstance(value, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}", value
        ) is None:
            raise ValueError("Canonical provider is unavailable")
        return value
    except Exception:  # noqa: BLE001 -- host/KMS/config errors may contain private metadata
        if required:
            raise DomainError(
                "SOURCE_UNAVAILABLE", "独立 Embedding 服务商身份暂不可核对。"
            ) from None
        # Stopping an existing profile must remain possible during host/KMS outages.
        return None
