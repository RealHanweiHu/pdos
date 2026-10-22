"""Stable tool definitions generated from the single domain command registry."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pdos_next.errors import DomainError

from .command_usage import require
from .types import RunScope, Tier

PREPARE_ONLY = frozenset(
    {
        "proposal.share",
        "proposal.g0.submit",
        "proposal.g0.decide",
        "category.member.grant",
        "project.create",
        "provider.agreement.register",
    }
)
ISOLATED = {
    "research.read": "research", "evidence.artifact.read": "extract", "mcp.result.read": "mcp",
}
SCOPE_KEYS = frozenset(
    {
        "tenant_id",
        "actor_id",
        "writer_id",
        "requester_id",
        "run_id",
        "agent_run_id",
        "agent_call_id",
        "confirmation_token",
        "prepared_event_id",
        "approval_token",
        "execution_binding",
        "selected_skill",
        "model_call_id",
        "ledger_call_id",
        "cancel_epoch",
        "authorization",
        "data_categories",
        "customer_identities",
        "explicit_external_write",
        "qualified",
        "privacy",
        "private_context",
        "tier",
        "validation_budget_id",
        "cost_required",
        "rate_card",
        "pricing",
        "limit_micro_usd",
        "input_token_limit",
        "output_token_limit",
        "call_limit",
        "text_tokens_per_utf8_byte",
        "text_framing_tokens",
        "text_billing_source",
        "output_cap_covers_all_billing",
        "covers_all_fees",
    }
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    kind: str
    tier: Tier
    operation_key: str | None = None
    taint: str = "trusted"
    parallel_safe: bool = False
    budget_weight: int = 1
    handler: Callable | None = field(default=None, repr=False, compare=False)
    version: str = "1"

    def definition(self):
        return {"name": self.name, "description": self.description, "parameters": self.input_schema}

    @property
    def requires_loaded_skill(self):
        """Whether calling this needs a loaded, enabled skill that allows the operation.

        The one source of truth for both ``ToolRegistry.authorize`` and the
        per-call disclosure derivation, so what 小Pai may see cannot drift from
        what it may call. T2 preparation produces named-decision material under
        its own policy and never required a skill.
        """
        return self.kind == "write" and self.tier != "T2-prepare-only"


class ToolRegistry:
    def __init__(self, specs=()):
        self._specs = {}
        for spec in specs:
            self.add(spec)

    def add(self, spec: ToolSpec):
        if spec.name in self._specs:
            raise ValueError("Duplicate registered tool")
        if spec.tier == "T2-prepare-only" and spec.operation_key is not None:
            raise ValueError("T2 preparation cannot bind an executing domain operation")
        self._specs[spec.name] = spec

    def get(self, name):
        spec = self._specs.get(name)
        if spec is None:
            raise DomainError(
                "FORBIDDEN_SCOPE", "工具未登记。", detail={"reason_key": "tool_not_registered"}
            )
        return spec

    def definitions(self, isolation="main"):
        # A child has a physically separate read-only list, not a model-visible write switch.
        allowed = {
            "research": {"research.search", "research.read"},
            "extract": {"evidence.artifact.read"},
            "mcp": {"mcp.result.read"},
        }
        return [
            self._specs[n].definition()
            for n in sorted(self._specs)
            if (n in allowed[isolation] if isolation != "main" else n not in ISOLATED)
        ]

    @property
    def version(self):
        body = [
            {**s.definition(), "tier": s.tier, "version": s.version}
            for _, s in sorted(self._specs.items())
        ]
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def authorize(self, scope: RunScope, name: str, arguments: Mapping, loaded, enabled):
        spec = self.get(name)
        authority = SCOPE_KEYS.intersection(arguments) if isinstance(arguments, Mapping) else set()
        if spec.name == "ai.run.revert" and spec.tier == "T1":
            # This is a Human-confirmed business target, never the execution scope.
            authority = authority - {"run_id"}
        if not isinstance(arguments, Mapping) or authority:
            raise DomainError("FORBIDDEN_SCOPE", "模型参数不能声明运行权限或身份。")
        for key in ("category_id", "product_id", "proposal_id"):
            if (
                key == "product_id" and name in {"product.baseline.read", "platform.read"}
                and scope.product_id is None and scope.category_id is not None
                and spec.tier == "READ"
            ):
                # This is a read selector inside the actual category. The port
                # rechecks ordinary product RLS; it never changes Run authority.
                continue
            if key in arguments and str(arguments[key]) != str(getattr(scope, key)):
                raise DomainError("FORBIDDEN_SCOPE", "工具对象与服务器绑定范围不同。")
        if name in ISOLATED and scope.isolation != ISOLATED[name]:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                "原文只能在隔离子任务读取。",
                detail={"reason_key": "isolated_subtask_only"},
            )
        if scope.isolation != "main":
            allowed = {d["name"] for d in self.definitions(scope.isolation)}
            if name not in allowed or spec.tier != "READ":
                raise DomainError("FORBIDDEN_SCOPE", "隔离子任务只拥有登记的读取工具。")
        if spec.requires_loaded_skill:
            skills = [
                skill
                for skill in loaded.values()
                if name in skill.operations and enabled(scope, skill)
            ]
            if not skills:
                raise DomainError("FORBIDDEN_SCOPE", "写工具需要已加载并已启用的技能包。")
        if scope.private_context and name in {
            "category.knowledge.add",
        }:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                "私有运行中的发现保持在提案受众内。",
                detail={"reason_key": "private_context_run"},
            )
        return spec


def command_tools(payloads=None, tiers=None, handlers=None):
    if payloads is None:
        from pdos_next.command_handlers import tier_of
        from pdos_next.contracts import PAYLOADS

        payloads = PAYLOADS
        # tier_of refuses an unregistered operation; a new payload cannot become T0 by omission.
        tiers = {
            key: "T2-prepare-only" if tier_of(key) == "T2" else tier_of(key) for key in payloads
        }
    handlers = handlers or {}
    # The calling note is a required part of registering a command (see .command_usage).
    usage = require(sorted(payloads))
    specs = []
    for operation, schema in sorted(payloads.items()):
        tier = (
            "T1" if operation == "ai.run.revert"
            else "T2-prepare-only" if operation in PREPARE_ONLY else tiers[operation]
        )
        raw = schema.model_json_schema()
        # Confirmation credentials and server scope can never be supplied by a model.
        for key in tuple(raw.get("properties", {})):
            target_run = operation == "ai.run.revert" and key == "run_id"
            if (key in SCOPE_KEYS and not target_run) or key == "confirmation_token":
                raw["properties"].pop(key)
                raw["required"] = [v for v in raw.get("required", []) if v != key]
        specs.append(
            ToolSpec(
                operation,
                usage[operation].description(operation, tier),
                raw,
                {"type": "object"},
                "write",
                tier,
                None if tier == "T2-prepare-only" else operation,
                handler=handlers.get(operation),
            )
        )
    return specs
