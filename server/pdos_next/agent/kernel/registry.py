"""Stable tool definitions generated from the single domain command registry."""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pdos_next.errors import DomainError

from .command_usage import require
from .types import RunScope, Tier

# Commands 小Pai only prepares and never carries out. A T2 one keeps its T2 tier; a T1 one
# (proposal.share) keeps T1 and is marked ``prepare_only``, because "only prepare" says
# what 小Pai may do and the tier says how the person handles it (P44 item 3).
# proposal.g0.submit left this list under P44 item 1: 小Pai prefills it, the owner confirms.
PREPARE_ONLY = frozenset(
    {
        "proposal.share",
        "proposal.g0.decide",
        "category.member.grant",
        "project.create",
        "provider.agreement.register",
    }
)
ISOLATED = {
    "research.read": "research",
    "evidence.artifact.read": "extract",
    "mcp.result.read": "mcp",
    "assistant.passage.read": "assistant_extract",
    "assistant.comparison.read": "assistant_compare",
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
    max_result_tokens: int = 4_000
    # Run scope fields that must be bound for this tool to work at all (P76 item 4a).
    # A run without them neither sees the tool nor may call it.
    scope_requires: tuple[str, ...] = ()
    # 小Pai only prepares material for this T1 command; the person handles it on the page
    # (P44 item 2). T2 preparation is told by its tier, so this marks T1 ones only.
    prepare_only: bool = False

    def __post_init__(self):
        if type(self.max_result_tokens) is not int or self.max_result_tokens < 512:
            raise ValueError("Tool result limit must fit a continuation envelope")
        if self.prepare_only and self.tier != "T1":
            raise ValueError("Only a T1 command is marked prepare-only; T2 says so by its tier")

    def definition(self):
        return {"name": self.name, "description": self.description, "parameters": self.input_schema}

    def available_in(self, scope) -> bool:
        """Whether the run's bound scope satisfies this tool's scope requirement."""
        return scope is None or all(
            getattr(scope, key, None) is not None for key in self.scope_requires
        )

    @property
    def requires_loaded_skill(self):
        """Whether calling this needs a loaded, enabled skill that allows the operation.

        The one source of truth for both ``ToolRegistry.authorize`` and the
        per-call disclosure derivation, so what 小Pai may see cannot drift from
        what it may call. Every write needs one, T2 preparation included (P76
        item 4b, replacing P37 item 2): a page that needs it preloads the skill.
        """
        return self.kind == "write"

    @property
    def prepares_only(self):
        """Whether 小Pai only prepares this and a person always carries it out."""
        return self.tier == "T2-prepare-only" or self.prepare_only


class ToolRegistry:
    def __init__(self, specs=()):
        self._specs = {}
        for spec in specs:
            self.add(spec)

    def add(self, spec: ToolSpec):
        if spec.name in self._specs:
            raise ValueError("Duplicate registered tool")
        if spec.prepares_only and spec.operation_key is not None:
            raise ValueError("Preparation cannot bind an executing domain operation")
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
            "research": {"research.search", "research.read", "result.read"},
            "extract": {"evidence.artifact.read", "result.read"},
            "mcp": {"mcp.result.read", "result.read"},
            "assistant_extract": {"assistant.passage.read", "result.read"},
            "assistant_compare": {"assistant.comparison.read", "result.read"},
        }
        return [
            self._specs[n].definition()
            for n in sorted(self._specs)
            if (n in allowed[isolation] if isolation != "main" else n not in ISOLATED)
        ]

    @property
    def version(self):
        body = [
            {**s.definition(), "tier": s.tier, "version": s.version,
             "max_result_tokens": s.max_result_tokens}
            for _, s in sorted(self._specs.items())
        ]
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def authorize(self, scope: RunScope, name: str, arguments: Mapping, loaded, enabled):
        spec = self.get(name)
        if not spec.available_in(scope):
            raise DomainError(
                "FORBIDDEN_SCOPE", "此工具须在绑定了相应项目、型号和品类的运行中使用。",
                detail={"reason_key": "tool_scope_required"},
            )
        authority = SCOPE_KEYS.intersection(arguments) if isinstance(arguments, Mapping) else set()
        if spec.name == "ai.run.revert" and spec.tier == "T1":
            # This is a Human-confirmed business target, never the execution scope.
            authority = authority - {"run_id"}
        if not isinstance(arguments, Mapping) or authority:
            raise DomainError("FORBIDDEN_SCOPE", "模型参数不能声明运行权限或身份。")
        for key in ("category_id", "product_id", "proposal_id"):
            if name == "assistant.search" and spec.tier == "READ" and (
                arguments.get(key) is None or getattr(scope, key) is None
                or str(arguments[key]) == str(getattr(scope, key))
            ):
                continue  # The adapter narrows selectors against actual requester RLS.
            if (
                key == "product_id"
                and name in {"product.baseline.read", "platform.read"}
                and scope.product_id is None
                and scope.category_id is not None
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
                raise DomainError(
                    "FORBIDDEN_SCOPE", "写工具需要已加载并已启用的技能包。",
                    detail={"reason_key": "write_skill_required"},
                )
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
        from pdos_next.core.command_handlers import tier_of
        from pdos_next.core.contracts import PAYLOADS

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
        tier = "T1" if operation == "ai.run.revert" else tiers[operation]
        if operation in PREPARE_ONLY and tier != "T1":
            tier = "T2-prepare-only"
        prepare_only = operation in PREPARE_ONLY and tier == "T1"
        raw = schema.model_json_schema()
        # Confirmation credentials and server scope can never be supplied by a model.
        for key in tuple(raw.get("properties", {})):
            target_run = operation == "ai.run.revert" and key == "run_id"
            if (key in SCOPE_KEYS and not target_run) or key in {
                "confirmation_token",
                "human_edits",
            }:
                raw["properties"].pop(key)
                raw["required"] = [v for v in raw.get("required", []) if v != key]
        prepares = prepare_only or tier == "T2-prepare-only"
        specs.append(
            ToolSpec(
                operation,
                usage[operation].description(operation, tier, prepare_only=prepare_only),
                raw,
                {"type": "object"},
                "write",
                tier,
                None if prepares else operation,
                handler=handlers.get(operation),
                prepare_only=prepare_only,
            )
        )
    return specs
