"""Synthetic rollout changes for tests; never an adoption or qualification record."""

from types import MappingProxyType

import pytest

from app.ai import capability_contract as registry
from app.ai.capability_contract import CapabilityRollout
from app.ai.runtime_contract import AgentKey


def set_agent_rollout(
    monkeypatch: pytest.MonkeyPatch, agent_key: AgentKey, rollout: CapabilityRollout
) -> None:
    monkeypatch.setattr(
        registry,
        "CAPABILITY_CONTRACTS",
        MappingProxyType(
            {
                key: contract.model_copy(update={"rollout": rollout})
                if contract.agent_key is agent_key
                else contract
                for key, contract in registry.CAPABILITY_CONTRACTS.items()
            }
        ),
    )
