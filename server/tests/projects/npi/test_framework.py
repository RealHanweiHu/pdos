from uuid import uuid4

from pdos_next.domain.projects.npi.rules import (
    PATH_FIELDS,
    Framework,
    PlanBasis,
    applicable,
    check,
    path_for,
)
from pdos_next.schemas.planning.plan import PlanTask

FRAMEWORK = {
    "stages": [
        {"key": "planning", "name": "规划", "node": "G1"},
        {"key": "evt", "name": "EVT", "node": "样机验证"},
        {"key": "dvt", "name": "DVT", "node": "可靠性验证"},
        {"key": "pvt", "name": "PVT", "node": "试产评审"},
        {"key": "mp", "name": "移交", "node": "首批放行"},
    ],
    "outcomes": [
        {
            "key": "specification_freeze",
            "stage": "planning",
            "name": "冻结规格",
            "role": "product_manager",
        },
        {
            "key": "performance_report",
            "stage": "evt",
            "name": "泵性能报告",
            "role": "test_engineering",
        },
        {
            "key": "certification_report",
            "stage": "dvt",
            "name": "认证报告",
            "role": "certification",
            "when_any": ["needs_new_certification"],
            "redline": True,
        },
        {
            "key": "eol_test_capability",
            "stage": "pvt",
            "name": "EOL 测试能力",
            "role": "quality",
            "redline": True,
        },
        {
            "key": "first_production_release",
            "stage": "mp",
            "name": "首批量产放行",
            "role": "quality",
            "redline": True,
        },
    ],
    "metrics": [
        {
            "key": "functional_pass_rate",
            "stage": "evt",
            "name": "主要功能通过率",
            "minimum_percent": 95,
        },
    ],
}


def test_paths_and_applicability_use_only_fixed_definition_facts():
    facts = dict.fromkeys(PATH_FIELDS, False)
    assert path_for(facts) == "light"
    assert path_for(facts, force_full=True) == "full"
    assert all(path_for(facts | {field: None}) == "full" for field in PATH_FIELDS)
    assert all(path_for(facts | {field: True}) == "full" for field in PATH_FIELDS)
    stages, outcomes, metrics = applicable(Framework.model_validate(FRAMEWORK), facts, "light")
    assert [stage.key for stage in stages] == ["planning", "prototype_validation", "pvt", "mp"]
    assert {outcome.key for outcome in outcomes if outcome.redline} == {
        "eol_test_capability",
        "first_production_release",
    }
    assert metrics[0].stage == "prototype_validation"
    _, unknown, _ = applicable(Framework.model_validate(FRAMEWORK), {}, "full")
    assert "certification_report" in {outcome.key for outcome in unknown}


def test_invalid_plan_localizes_cycle_redline_source_and_duration():
    stages, outcomes, _ = applicable(Framework.model_validate(FRAMEWORK), {}, "full")
    framework_id = uuid4()
    basis = PlanBasis.model_validate(
        {
            "framework_id": framework_id,
            "framework_revision": 2,
            "tasks": {
                "spec": {
                    "role": "product_manager",
                    "deliverable": "完整规格",
                    "outcome_keys": ["specification_freeze"],
                    "sources": [
                        {
                            "kind": "framework_outcome",
                            "id": str(framework_id),
                            "revision": 1,
                            "key": "specification_freeze",
                        }
                    ],
                },
            },
            "milestones": {"planning": "spec"},
        }
    )
    checks = check(
        stages=stages,
        outcomes=outcomes,
        tasks=[
            PlanTask(
                key="spec",
                title="起草规格",
                discipline="npi",
                depends_on=("spec",),
                duration_min_minutes=30,
                duration_max_minutes=30,
                estimate_source="unsupported",
            )
        ],
        basis=basis,
        role_keys={"product_manager"},
        sources={("framework_outcome", str(framework_id), 2, "specification_freeze")},
    )
    assert ("REDLINE_UNCOVERED", "eol_test_capability") in {(v["code"], v["key"]) for v in checks}
    assert {"DEPENDENCY_CYCLE", "SOURCE_OUTSIDE_BASIS", "DURATION_UNSUPPORTED"} <= {
        value["code"] for value in checks
    }
