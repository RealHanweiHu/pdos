"""Current rollout checks for the ordinary employee execution path.

Shadow evaluation needs its own authorized execution/adoption path. It cannot
borrow the employee worker, tools, inbox, or apply path by omitting a mode.
These checks do not grant qualification or promote any capability.
"""

from sqlalchemy import ColumnElement, or_, tuple_

from app.ai import capability_contract as registry
from app.ai.capability_contract import (
    CapabilityContract,
    CapabilityRollout,
    UnknownCapabilityError,
    capability_for_finding,
)
from app.ai.finding_visibility import finding_attention_visibility
from app.ai.runtime_contract import AgentKey
from app.db.schema import tables


class CapabilityUnavailableError(PermissionError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def require_live(contract: CapabilityContract) -> None:
    if contract.rollout is not CapabilityRollout.LIVE:
        raise CapabilityUnavailableError(f"CAPABILITY_{contract.rollout.value.upper()}")


def require_live_key(key: str) -> None:
    try:
        contract = registry.resolve_capability(key)
    except UnknownCapabilityError as error:
        raise CapabilityUnavailableError("CAPABILITY_UNREGISTERED") from error
    require_live(contract)


def require_employee_agent(agent_key: AgentKey) -> None:
    contracts = [
        c
        for c in registry.CAPABILITY_CONTRACTS.values()
        if c.agent_key is agent_key and c.event_driven and c.finding_types
    ]
    if any(c.rollout is CapabilityRollout.LIVE for c in contracts):
        return
    code = (
        "CAPABILITY_SHADOW"
        if any(c.rollout is CapabilityRollout.SHADOW for c in contracts)
        else "CAPABILITY_DISABLED"
    )
    raise CapabilityUnavailableError(code)


def require_live_finding(agent_key: str, finding_type: str) -> None:
    try:
        contract = capability_for_finding(AgentKey(agent_key), finding_type)
    except (ValueError, UnknownCapabilityError) as error:
        raise CapabilityUnavailableError("CAPABILITY_UNREGISTERED") from error
    require_live(contract)


def employee_finding_visibility() -> ColumnElement[bool]:
    live_pairs = [
        (contract.agent_key.value, finding_type)
        for contract in registry.CAPABILITY_CONTRACTS.values()
        if contract.rollout is CapabilityRollout.LIVE
        for finding_type in contract.finding_types
    ]
    return (
        tables.findings.c.finding_type.not_in(
            (
                "intake_organization",
                "meeting_plan",
                "product_research_plan",
                "product_competitor_observations",
                "product_market_segments",
                "product_opportunities",
                "product_experiments",
                "product_strategy_drafts",
                "product_definition_drafts",
                "product_rfq_requirements",
            )
        )
        & or_(
            tables.findings.c.status == "applied",
            tuple_(tables.findings.c.agent_key, tables.findings.c.finding_type).in_(live_pairs),
        )
        & finding_attention_visibility()
    )
