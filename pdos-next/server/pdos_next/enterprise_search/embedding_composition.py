"""Trusted host composition; an embedding profile selects its own connection."""

from .embedding_activities import EmbeddingPorts
from .embedding_provider import HostEmbeddingSecrets, OpenAIEmbeddingClient


def configured_ports(runtime, *, provider_io=False):
    host = getattr(runtime, "secrets", None)
    if host is None:
        return EmbeddingPorts(None, None, None)
    # A legacy current(tenant, protocol) chat secret is deliberately insufficient.
    if not all(
        callable(getattr(host, name, None))
        for name in ("current_for", "resolve", "rate_card_for", "provider_for")
    ):
        return EmbeddingPorts(None, None, None)
    secrets = HostEmbeddingSecrets(host)
    return EmbeddingPorts(
        secrets, secrets.pricing_for, OpenAIEmbeddingClient() if provider_io else None
    )


def bind_session(session, ports):
    session.info["embedding_secrets"] = ports.secrets
    session.info["embedding_pricing"] = ports.pricing_for
