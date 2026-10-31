"""Approved read/compute/isolation tools plus automatically registered domain commands."""

from .command_usage import describe
from .registry import PREPARE_ONLY, ToolRegistry, ToolSpec, command_tools

READS = frozenset(
    {
        "category.list",
        "conversation.history",
        "category.read",
        "category.knowledge.list",
        "category.parameters.list",
        "category.competitors.list",
        "platform.read",
        "build.read",
        "build.lot.read",
        "build.sample.read",
        "quality.issue.read",
        "test.run.read",
        "proposal.read",
        "proposal.items.read",
        "product.baseline.read",
        "evidence.search",
        "evidence.artifact.read",
        "evidence.extract",
        "assistant.search",
        "assistant.extract",
        "assistant.citations.read",
        "assistant.materials.read",
        "assistant.compare",
        "assistant.comparison.read",
        "assistant.passage.read",
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
    from pdos_next.enterprise_search.assistant_schemas import SCHEMAS as ASSISTANT_SCHEMAS

    from .category_candidate import CategoryCandidateInput
    from .conversation import HistoryInput
    from .domain_reads import SCHEMAS
    from .m3_calculators import SCHEMAS as COMPUTE_SCHEMAS
    from .m3_definition_diff import SCHEMAS as DEFINITION_SCHEMAS
    from .m3_object_reads import SCHEMAS as OBJECT_SCHEMAS
    from .m3_spec_compare import SCHEMAS as COMPARE_SCHEMAS
    from .mcp_schemas import SCHEMAS as MCP_SCHEMAS
    from .platform_reads import SCHEMAS as PLATFORM_SCHEMAS
    from .project_object_reads import SCHEMAS as PROJECT_SCHEMAS
    from .result_continuation import ResultReadInput

    schemas = {
        "conversation.history": HistoryInput,
        **SCHEMAS,
        **COMPUTE_SCHEMAS,
        **OBJECT_SCHEMAS,
        **COMPARE_SCHEMAS,
        **DEFINITION_SCHEMAS,
        **PLATFORM_SCHEMAS,
        **PROJECT_SCHEMAS,
        **ASSISTANT_SCHEMAS,
    }

    registry = ToolRegistry(command_tools())
    registry.add(ToolSpec(
        "result.read",
        describe("result.read", "READ", "read"),
        ResultReadInput.model_json_schema(), {"type": "object"}, "read", "READ",
        parallel_safe=True,
    ))
    for name, schema in MCP_SCHEMAS.items():
        registry.add(ToolSpec(
            name,
            describe(name, "READ", "read"),
            schema.model_json_schema(), {"type": "object"}, "read", "READ",
            taint="external" if name != "mcp.tools.list" else "trusted",
        ))
    for name in sorted(READS | COMPUTE | {"skill.load"}):
        kind = "research" if name in RESEARCH else "compute" if name in COMPUTE else "read"
        registry.add(
            ToolSpec(
                name,
                describe(name, "READ", kind),
                schemas[name].model_json_schema() if name in schemas else {"type": "object"},
                {"type": "object"},
                kind,
                "READ",
                taint="external" if name in RESEARCH or name.startswith(("evidence.", "assistant."))
                else "trusted",
                parallel_safe=name not in {
                    "skill.load", "assistant.search", "assistant.extract",
                    "assistant.citations.read",
                    "assistant.materials.read", "assistant.compare",
                },
                version="5"
                if name == "calc.spec_compare"
                else "2"
                if name
                in {
                    "evidence.artifact.read",
                    "proposal.read",
                    "proposal.items.read",
                    "product.baseline.read",
                    "calc.derivation_diff",
                    "platform.read",
                }
                else "1",
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
                    describe(name, tier),
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
                    describe(name, "T2-prepare-only"),
                    {"type": "object"},
                    {"type": "object"},
                    "write",
                    "T2-prepare-only",
                )
            )
    return registry
