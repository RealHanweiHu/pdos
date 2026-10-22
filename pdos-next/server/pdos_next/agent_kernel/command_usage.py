"""Per-command calling notes, so a tool description is registered rather than templated.

小Pai picks a tool from its description. Generating that description from the
operation name tells it nothing a name does not already say, which leaves every
command in a disclosure indistinguishable from its neighbours. This registry
makes the calling note a required part of registering a domain command:
``require`` refuses to build the tool list when a payload has no entry, so a new
command cannot reach the model without one.

``when`` (何时调用) is the required field. ``None`` is an explicit registration
that the trigger has not been written yet, not an absent value: it renders as a
stated capability limit, and the ratchet test caps how many may remain. Only the
domain owner writes it - never a model, an automation, or a guess from the name.

``produces`` and ``limit`` come from v1.1 附录 A, falling back to the DC-11 tier
policy. They are design facts, so they are reproduced, not invented here.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pdos_next.errors import DomainError

REGISTRY = Path(__file__).resolve().parent / "command_usage.json"

# Registered commands whose 何时调用 is still unwritten. This number may only go
# down: tests/agent_kernel/test_command_usage.py fails if it grows, and a new
# command must either carry a note or be added here deliberately.
PENDING_LIMIT = 131


@dataclass(frozen=True)
class Usage:
    """One command's registered calling note. Server configuration, never model input."""

    when: str | None
    produces: str | None
    limit: str | None
    tier: str
    source: str

    @property
    def written(self):
        return bool(self.when)

    def description(self, operation: str, tier: str | None = None, kind: str | None = None):
        """The tool description 小Pai actually sees, assembled from registered facts.

        ``tier`` is the tier the registry actually assigned, which can be stricter
        than 附录 A (``proposal.g0.submit`` is T1 there and prepare-only here), so
        the verb follows what the server will really do rather than the contract.
        """
        effective = tier or self.tier
        verb = (
            "计算" if kind == "compute"
            else "检索" if kind == "research"
            else "读取" if effective == "READ"
            else "准备" if effective == "T2-prepare-only"
            else "办理"
        )
        parts = [
            f"{self.when.rstrip('。')}。"
            if self.written
            else f"{verb} {operation}。何时调用尚未登记，使用前须由该领域确认。"
        ]
        if self.produces:
            parts.append(f"产生 {self.produces}。")
        if self.limit:
            parts.append(self.limit if self.limit.endswith("。") else f"{self.limit}。")
        return "".join(parts)


@lru_cache(maxsize=1)
def registry():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if data.get("format_version") != 1:
        raise ValueError("Unknown command usage registry format")
    entries = {}
    for operation, value in data["commands"].items():
        if not isinstance(value, dict) or set(value) != {
            "when", "produces", "limit", "tier", "source",
        }:
            raise ValueError(f"Command usage entry for {operation} has an unknown shape")
        if value["when"] is not None and not str(value["when"]).strip():
            raise ValueError(f"Command usage for {operation} must omit or write 何时调用")
        entries[operation] = Usage(**value)
    return entries


def require(operations):
    """Return usage for every operation, refusing to proceed when one is unregistered.

    This is what makes the field required. A domain command added to PAYLOADS
    without a calling note fails here instead of reaching 小Pai with a
    description generated from its own name.
    """
    known = registry()
    missing = sorted(set(operations) - set(known))
    if missing:
        raise DomainError(
            "SOURCE_UNAVAILABLE",
            "新增领域命令缺少调用须知登记：" + "、".join(missing[:5])
            + ("…" if len(missing) > 5 else ""),
            detail={"reason_key": "command_usage_unregistered", "operations": missing},
        )
    return {operation: known[operation] for operation in operations}


def describe(operation: str, tier: str | None = None, kind: str | None = None):
    """Description for one registered tool, refusing an unregistered name.

    Used by the approved read/compute/isolation specs, which are disclosed in
    every run, so a templated description there costs more than on a skill-gated
    write command.
    """
    return require([operation])[operation].description(operation, tier, kind)


def pending():
    return tuple(sorted(key for key, value in registry().items() if not value.written))
