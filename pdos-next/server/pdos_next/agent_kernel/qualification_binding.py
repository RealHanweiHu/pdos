"""Public quality identities exclude credentials, prices and unrelated registered tools."""

import hashlib
import json
from dataclasses import asdict


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode()
    ).hexdigest()


def model_identity(route):
    from pdos_next.providers.agent_wire import response_codec

    version = getattr(route, "model_version", None) or route.version
    value = {
        "protocol": route.protocol,
        "base_url": route.base_url.rstrip("/"),
        "model": route.model,
        "version": version,
    }
    mode = getattr(route, "openai_response_mode", "auto")
    codec = response_codec(route.protocol, route.base_url, mode)
    if mode != "auto":
        value["openai_response_mode"] = mode
    if codec != "native-schema/v1":
        value["agent_response_codec"] = codec
    return fingerprint(value)


def tool_identity(skill, registry):
    return fingerprint(
        [
            {key: value for key, value in asdict(registry.get(name)).items() if key != "handler"}
            for name in sorted(skill.operations)
        ]
    )


DRAFT_OPERATIONS = frozenset(
    {
        "category.knowledge.add",
        "evidence.claim.record",
        "proposal.item.patch",
        "evidence.link.create",
        "product.definition.item.patch",
        "research.snapshot.register",
    }
)


def draft_operations(skill, registry):
    writes = {
        name
        for name in skill.operations
        if registry.get(name).kind == "write" and registry.get(name).tier == "T0"
    }
    return sorted(writes) if writes and writes <= DRAFT_OPERATIONS else []
