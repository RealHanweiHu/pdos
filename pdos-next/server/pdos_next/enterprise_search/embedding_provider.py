"""Independent embedding transport over the existing KMS, rate cards and JSON parser.

No default chat connection, automatic retry, provider fallback, redirects or proxy
inheritance. Constructing this adapter never resolves a key or sends a request.
"""

from pdos_next.errors import DomainError
from pdos_next.model_configuration.service import secret_digest
from pdos_next.providers.client import _identifier, _integer, json_value
from pdos_next.providers.types import ProviderError, ProviderUsage

from .embedding_schemas import EmbeddingResponse, bounded_inputs, validate_response


def connection_metadata(metadata):
    from pdos_next.schemas.model_configuration import ModelMetadata

    # Only this explicit connection_id is resolved. TenantRuntime.current() is
    # deliberately never called, and the active chat model is never selected.
    return ModelMetadata(
        protocol="openai-compatible",
        base_url=metadata.base_url,
        model=metadata.model,
        model_version=metadata.model_version,
        connection_id=metadata.connection_id,
    )


class HostEmbeddingSecrets:
    def __init__(self, host):
        self.host = host

    def provider_for(self, tenant_id, metadata):
        from types import SimpleNamespace

        # Same server-owned identity as chat/P26, after exact connection matching.
        return self.host.provider_for(
            SimpleNamespace(tenant_id=tenant_id), connection_metadata(metadata)
        )

    def current_embedding(self, tenant_id, metadata):
        return self.host.current_for(tenant_id, connection_metadata(metadata))

    def resolve(self, binding):
        return self.host.resolve(binding)

    def pricing_for(self, tenant_id, metadata):
        from types import SimpleNamespace

        from pydantic import SecretStr

        selected = connection_metadata(metadata)
        route = selected.route(SecretStr("metadata-validation-only"), metadata.model_version)
        return self.host.rate_card_for(SimpleNamespace(tenant_id=tenant_id), route)


def body_for(metadata, texts):
    return {
        "model": metadata.model,
        "input": list(texts),
        "dimensions": metadata.dimensions,
        "encoding_format": "float",
    }


def usage_from(body):
    raw = body.get("usage")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("Invalid embedding usage")
    measured = raw.get("prompt_tokens", raw.get("total_tokens"))
    if measured is None:
        return None
    measured = _integer(measured)
    if measured > 2_147_483_647:
        raise ValueError("Embedding usage exceeds accounting bound")
    if "total_tokens" in raw and _integer(raw["total_tokens"]) != measured:
        raise ValueError("Embedding input and total usage disagree")
    return measured


class OpenAIEmbeddingClient:
    def __init__(self, *, transport=None):
        import httpx

        self.http = httpx.Client(transport=transport, trust_env=False, follow_redirects=False)

    def close(self):
        self.http.close()

    def embed(self, metadata, texts, credential, *, timeout):
        from pdos_agent_runtime.graph import in_registered_agent_graph

        from pdos_next.agent_kernel.result_continuation import serialized

        if not in_registered_agent_graph():
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 必须经已注册执行图。")
        texts = bounded_inputs(texts)
        if (
            credential.binding.protocol != "openai-compatible"
            or not secret_digest(credential.binding)
            or not 0 < timeout <= 90
        ):
            raise DomainError("FORBIDDEN_SCOPE", "Embedding 凭据或超时边界无效。")
        usage, request_id = None, None
        try:
            with self.http.stream(
                "POST",
                metadata.base_url + "/embeddings",
                headers={
                    "Authorization": "Bearer " + credential.credential.get_secret_value(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                content=serialized(body_for(metadata, texts)).encode(),
                timeout=timeout,
            ) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 2_097_152:
                        raise ValueError("Embedding response exceeds byte cap")
                    chunks.append(chunk)
                value = json_value(b"".join(chunks))
                if not isinstance(value, dict):
                    raise TypeError("Embedding response must be an object")
                measured = usage_from(value)
                usage = ProviderUsage(measured, 0) if measured is not None else None
                request_id = _identifier(response.headers.get("x-request-id"))
                if (
                    response.status_code != 200
                    or value.get("model", metadata.model) != metadata.model
                ):
                    raise ValueError("Embedding response model/status mismatch")
                rows = value["data"]
                if (
                    not isinstance(rows, list)
                    or len(rows) != len(texts)
                    or {row["index"] for row in rows} != set(range(len(texts)))
                    or any(type(row["index"]) is not int for row in rows)
                ):
                    raise ValueError("Embedding index set mismatch")
                rows = sorted(rows, key=lambda row: row["index"])
                result = EmbeddingResponse(
                    tuple(tuple(row["embedding"]) for row in rows), measured, request_id
                )
                return validate_response(result, count=len(texts), dimensions=metadata.dimensions)
        except Exception:  # noqa: BLE001 -- provider/KMS errors must be redacted
            raise ProviderError(
                "PROVIDER_RESPONSE_INVALID", usage=usage, request_id=request_id
            ) from None
