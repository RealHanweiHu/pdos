"""Approved read/compute/isolation tools plus automatically registered domain commands."""

from .registry import PREPARE_ONLY, ToolRegistry, ToolSpec, command_tools

READS = frozenset(
    {
        "category.list",
        "category.read",
        "category.knowledge.list",
        "category.parameters.list",
        "category.competitors.list",
        "platform.read",
        "proposal.read",
        "proposal.items.read",
        "product.baseline.read",
        "evidence.search",
        "evidence.artifact.read",
        "evidence.extract",
    }
)
RESEARCH = frozenset({"research.search", "research.read", "research.fanout"})
COMPUTE = frozenset(
    {
        "calc.market_size",
        "calc.opportunity_score",
        "calc.cost_subtotal",
        "calc.spec_compare",
        "calc.price_band",
        "calc.derivation_diff",
    }
)
# These contracts are implemented by M3. Their execution port remains absent until the
# owner adds the actual payload schema/command to the one common registry.
M3_TIERS = {
    "research.snapshot.register": "T0",
    "category.knowledge.add": "T0",
    "proposal.item.patch": "T0",
    "product.definition.item.patch": "T0",
    "evidence.link.create": "T0",
    "category.create": "T1",
    "category.knowledge.promote": "T1",
    "category.knowledge.withdraw": "T1",
    "category.parameter.publish": "T1",
    "proposal.create": "T1",
    "proposal.question.create": "T1",
    "platform.link.create": "T1",
}


def default_registry():
    from .category_candidate import CategoryCandidateInput
    from .domain_reads import SCHEMAS
    from .m3_calculators import SCHEMAS as COMPUTE_SCHEMAS
    from .m3_definition_diff import SCHEMAS as DEFINITION_SCHEMAS
    from .m3_object_reads import SCHEMAS as OBJECT_SCHEMAS
    from .m3_spec_compare import SCHEMAS as COMPARE_SCHEMAS

    schemas = {
        **SCHEMAS,
        **COMPUTE_SCHEMAS,
        **OBJECT_SCHEMAS,
        **COMPARE_SCHEMAS,
        **DEFINITION_SCHEMAS,
    }

    registry = ToolRegistry(command_tools())
    for name in sorted(READS | COMPUTE | {"skill.load"}):
        kind = "research" if name in RESEARCH else "compute" if name in COMPUTE else "read"
        registry.add(
            ToolSpec(
                name,
                f"读取或计算 {name}；范围由服务器运行绑定。",
                schemas[name].model_json_schema() if name in schemas else {"type": "object"},
                {"type": "object"},
                kind,
                "READ",
                taint="external" if name in RESEARCH or name.startswith("evidence.") else "trusted",
                parallel_safe=name != "skill.load",
            )
        )
    from pdos_next.research.tools import research_tools

    for spec in research_tools():
        registry.add(spec)
    existing = {d["name"] for d in registry.definitions()}
    for name, tier in sorted(M3_TIERS.items()):
        if name not in existing:
            registry.add(
                ToolSpec(
                    name,
                    f"准备 {name} 候选。",
                    CategoryCandidateInput.model_json_schema()
                    if name == "category.create"
                    else {"type": "object"},
                    {"type": "object"},
                    "write",
                    tier,
                    operation_key=name,
                )
            )
    for name in sorted(PREPARE_ONLY):
        if name not in existing:
            registry.add(
                ToolSpec(
                    name,
                    f"只准备 {name} 的具名决定材料，无执行权。",
                    {"type": "object"},
                    {"type": "object"},
                    "write",
                    "T2-prepare-only",
                )
            )
    return registry
