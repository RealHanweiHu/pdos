"""Read-only operator publication for the bounded event reasoning loop.

This loader does not evaluate, publish, or approve a model. The separate purpose
qualification must be supplied by the operator; generic gateway qualification
and input-meter qualification remain independently required.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.model_catalog import ProviderName

LOOP_POLICY_PATH = "PDOS_AGENT_LOOP_QUALIFICATION_PATH"
LOOP_POLICY_SHA = "PDOS_AGENT_LOOP_QUALIFICATION_SHA256"


def loop_contract_sources() -> dict[str, str]:
    # Executor imports this module; read its loaded prompt versions at call time.
    from app.ai.executor import PROMPT_VERSIONS

    directory = Path(__file__).parent
    files = (
        "executor.py",
        "loop_policy.py",
        "tools.py",
        "gateway.py",
        "runtime_factory.py",
        "observations.py",
        "context_projection.py",
        "context_manifests.py",
        "runtime_contract.py",
        "call_identity.py",
        "checkpoints.py",
        "finding_writer.py",
        "run_store.py",
        "model_budget.py",
        "agent_budget.py",
        "../db/schema.py",
        "../worker/dispatcher.py",
        "../contracts/runtime_records.py",
        "../contracts/runtime_policy.py",
    )
    sources = {name: sha256((directory / name).read_bytes()).hexdigest() for name in files}
    # Bind the prompts the executor actually loads; a fixed *_v1 glob went stale at v2.
    for version in PROMPT_VERSIONS.values():
        name = version.replace("-", "_") + ".json"
        sources[f"prompts/{name}"] = sha256((directory / "prompts" / name).read_bytes()).hexdigest()
    return sources


def loop_contract_digest() -> str:
    return sha256(json.dumps(loop_contract_sources(), sort_keys=True).encode()).hexdigest()


class LoopQualification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["agent-read-loop-qualification.v1"]
    status: Literal["passed"]
    runtime_digest: str = Field(pattern="^[a-f0-9]{64}$")
    provider: ProviderName
    model: str = Field(min_length=1, max_length=128)
    suite_version: str = Field(min_length=1, max_length=128)
    suite_digest: str = Field(pattern="^[a-f0-9]{64}$")
    evidence_ref: str = Field(min_length=1, max_length=512)
    approved_by: str = Field(min_length=1, max_length=128)


class LoopBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["bounded_tools.v1"] = "bounded_tools.v1"
    qualification_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    qualification: LoopQualification


def configured_loop_binding(environment: Mapping[str, str]) -> LoopBinding | None:
    path, expected = environment.get(LOOP_POLICY_PATH, ""), environment.get(LOOP_POLICY_SHA, "")
    if not path and not expected:
        return None
    if not path or not expected:
        raise ValueError("loop qualification path and expected SHA256 must both be configured")
    body = Path(path).read_bytes()
    if sha256(body).hexdigest() != expected:
        raise ValueError("loop qualification publication digest mismatch")
    qualification = LoopQualification.model_validate_json(body)
    if qualification.runtime_digest != loop_contract_digest():
        raise ValueError("loop qualification does not match the current runtime contract")
    return LoopBinding(qualification_sha256=expected, qualification=qualification)
