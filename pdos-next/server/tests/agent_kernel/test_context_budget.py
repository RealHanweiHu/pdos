import hashlib
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from pdos_next.agent_kernel.context_budget import budget_for, estimate_tokens, segments
from pdos_next.schemas.model_configuration import ModelMetadata
from tests.agent_kernel.test_gateway import configured_route


@pytest.mark.parametrize("text, expected", [
    ("", 0), ("abcd", 1), ("充气泵", 3), ("充气abcd泵!", 5),
])
def test_token_estimate(text, expected):
    assert estimate_tokens(text) == expected


def test_default_and_configured_budgets():
    route = replace(configured_route(), context_window_tokens=None)
    value = budget_for(route)
    assert value == {"window": 32000, "window_configured": False,
                     "reserve": route.max_output_tokens + 4000,
                     "focus": 32000 - route.max_output_tokens - 4000}
    assert budget_for(replace(route, context_window_tokens=200000))["focus"] == 64000
    assert budget_for(replace(route, context_window_tokens=1024))["focus"] == 0


def test_segments_separate_history_skills_and_loop():
    conversation = {"turns": [{"goal": "核对压力", "summary": "未知"}]}
    envelope = json.dumps({"context": {"conversation": conversation}}, ensure_ascii=False)
    messages = [{"role": "user", "content": envelope},
                {"role": "user", "content": "skill one"},
                {"role": "user", "content": "skill two"},
                {"role": "assistant", "content": "read"},
                {"role": "tool", "content": "actual result"}]
    value = segments("fixed", [], messages)
    parts = value["segments"]
    assert set(parts) == {"system", "tools", "skills", "envelope", "history", "loop"}
    assert parts["history"] > 0
    assert parts["skills"] == estimate_tokens("skill one") + estimate_tokens("skill two")
    assert parts["loop"] == estimate_tokens("read") + estimate_tokens("actual result")
    assert value["estimated_total"] == sum(parts.values())


def test_optional_window_preserves_legacy_route_and_configuration_bindings():
    route = replace(configured_route(), context_window_tokens=None)
    legacy = {key: getattr(route, key) for key in (
        "protocol", "base_url", "model", "version", "max_output_tokens",
        "openai_output_parameter", "timeout_seconds", "response_bytes",
    )}
    assert route.context_window_tokens is None
    assert route.digest == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    assert replace(route, context_window_tokens=200000).digest != route.digest
    metadata = ModelMetadata(protocol=route.protocol, base_url=route.base_url,
                             model=route.model, model_version=route.version)
    assert "context_window_tokens" not in metadata.binding_metadata()
    configured = metadata.model_copy(update={"context_window_tokens": 200000})
    assert configured.route(route.api_key, route.version).context_window_tokens == 200000


@pytest.mark.parametrize("value", [512, 10_000_001, True, 2000.5, "200000"])
def test_invalid_window_rejected_at_route_and_dto(value):
    route = configured_route()
    with pytest.raises(ValueError, match="Invalid context window"):
        replace(route, context_window_tokens=value)
    with pytest.raises(ValidationError):
        ModelMetadata(protocol=route.protocol, base_url=route.base_url, model=route.model,
                      model_version=route.version, context_window_tokens=value)
