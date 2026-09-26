"""Internal content-addressed event runtime bundles and admitted context revisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from app.ai.capability_contract import CAPABILITY_CONTRACTS
from app.ai.context_projection import PROJECT_GATEWAY_POLICY
from app.ai.observations import AgentObservations, digest
from app.ai.runtime_contract import AgentKey
from app.contracts.runtime_records import ContextManifest


def event_runtime_bundle(agent_key: str, *, loop: bool) -> dict[str, Any]:
    from hashlib import sha256

    from app.ai.executor import INSTRUCTIONS, PROMPT_VERSIONS, SYSTEM_PROMPTS, loop_system_prompt

    key = AgentKey(agent_key)
    root = Path(__file__).resolve().parents[3]
    files = sorted((root / "server/app").rglob("*.py"))
    files += sorted((root / "server/app/ai/prompts").glob("*.json"))
    files += sorted((root / "server/migrations/versions").glob("*.py"))
    files += sorted((root / "infra/postgres/security").glob("*.sql"))
    sources = {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in files}
    capabilities = [
        c.model_dump(mode="json") for c in CAPABILITY_CONTRACTS.values() if c.agent_key == key
    ]
    system_prompt = loop_system_prompt(key) if loop else SYSTEM_PROMPTS[key]
    tools = json.loads(system_prompt.rsplit("\nFROZEN_READ_ONLY_TOOLS\n", 1)[1])
    compiled = dict(
        agent_key=agent_key,
        loop=loop,
        prompt_version=PROMPT_VERSIONS[key],
        system_prompt_sha256=sha256(system_prompt.encode()).hexdigest(),
        instruction_sha256=sha256(INSTRUCTIONS[key].encode()).hexdigest(),
        capabilities=capabilities,
        tools=tools,
        projection=PROJECT_GATEWAY_POLICY,
        skill_versions=[],  # No runtime Skill package is executed by this event path.
    )
    return dict(
        version="event-runtime-bundle.v1",
        release_bundle_version="sha256:" + digest(dict(sources=sources, compiled=compiled)),
        capability_version="sha256:" + digest(capabilities),
        toolset_version="sha256:" + digest(tools),
        projection_version="sha256:" + digest(PROJECT_GATEWAY_POLICY),
        policy_version="sha256:"
        + digest({k: v for k, v in sources.items() if "polic" in k or "security" in k}),
        source_sha256=sources,
        compiled=compiled,
    )


def bind_bundle(port: AgentObservations, agent_key: str, *, loop: bool) -> dict[str, Any] | None:
    return cast(
        dict[str, Any] | None,
        port._call(
            "SELECT cehub_ai.bind_agent_runtime_bundle(:body)",
            body=json.dumps(event_runtime_bundle(agent_key, loop=loop)),
        ),
    )


def freeze_manifest(
    port: AgentObservations,
    *,
    receipt_id: UUID,
    attempt_id: UUID,
    qualification: dict[str, Any],
    removed_paths: tuple[str, ...],
) -> ContextManifest | None:
    body = port._call(
        "SELECT cehub_ai.freeze_agent_context_manifest(:receipt,:attempt,:pins)",
        receipt=receipt_id,
        attempt=attempt_id,
        pins=json.dumps(dict(qualification=qualification, removed_paths=list(removed_paths))),
    )
    return ContextManifest.model_validate(body) if body is not None else None
