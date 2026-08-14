"""Fail-closed HTTP egress policy derived only from operator model configuration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from app.ai.model_catalog import ModelCatalog, ProviderName, ResolvedModelRoute


class EgressConfigurationError(ValueError):
    """Raised when a configured provider endpoint is unsafe or ambiguous."""


class EgressDeniedError(RuntimeError):
    """Raised before a request can target anything outside the configured endpoint."""


@dataclass(frozen=True)
class _AllowedEndpoint:
    raw_base_url: str
    scheme: str
    hostname: str
    port: int | None
    path: str


def _validated_endpoint(base_url: str) -> _AllowedEndpoint:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as error:
        raise EgressConfigurationError("provider endpoint is invalid") from error
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise EgressConfigurationError("provider endpoint is invalid")
    normalized_hostname = hostname.lower()
    if parsed.scheme == "http" and normalized_hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise EgressConfigurationError("plain HTTP is restricted to loopback development")
    decoded_segments = [unquote(segment) for segment in parsed.path.split("/")]
    if any(segment in {".", ".."} for segment in decoded_segments):
        raise EgressConfigurationError("provider endpoint path is invalid")
    path = parsed.path.rstrip("/")
    return _AllowedEndpoint(
        raw_base_url=base_url.rstrip("/"),
        scheme=parsed.scheme,
        hostname=normalized_hostname,
        port=port,
        path=path,
    )


class ProviderEgressPolicy:
    def __init__(self, endpoints: dict[ProviderName, _AllowedEndpoint]) -> None:
        self._endpoints = dict(endpoints)

    @classmethod
    def from_catalog(cls, catalog: ModelCatalog) -> ProviderEgressPolicy:
        return cls(
            {
                configuration.provider: _validated_endpoint(configuration.base_url)
                for configuration in catalog.configurations
            }
        )

    @classmethod
    def from_routes(cls, routes: Iterable[ResolvedModelRoute]) -> ProviderEgressPolicy:
        endpoints: dict[ProviderName, _AllowedEndpoint] = {}
        for route in routes:
            endpoint = _validated_endpoint(route.base_url)
            existing = endpoints.get(route.provider)
            if existing is not None and existing != endpoint:
                raise EgressConfigurationError("provider has multiple configured endpoints")
            endpoints[route.provider] = endpoint
        return cls(endpoints)

    def assert_request_allowed(self, route: ResolvedModelRoute, target_url: str) -> None:
        allowed = self._endpoints.get(route.provider)
        if allowed is None or route.base_url.rstrip("/") != allowed.raw_base_url:
            raise EgressDeniedError("provider route is outside the configured egress boundary")
        try:
            target = urlsplit(target_url)
            target_port = target.port
        except ValueError as error:
            raise EgressDeniedError("provider request target is invalid") from error
        target_hostname = target.hostname.lower() if target.hostname is not None else None
        base_prefix = f"{allowed.path}/" if allowed.path else "/"
        decoded_segments = [unquote(segment) for segment in target.path.split("/")]
        if (
            target.scheme != allowed.scheme
            or target_hostname != allowed.hostname
            or target_port != allowed.port
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
            or not target.path.startswith(base_prefix)
            or any(segment in {".", ".."} for segment in decoded_segments)
        ):
            raise EgressDeniedError("provider request target is outside the egress allowlist")
