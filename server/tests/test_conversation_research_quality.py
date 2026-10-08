"""Exact failure attribution in model context without any external calls."""

import pytest

from app.ai.context_projection import ContextProjectionError, project_gateway_context
from app.ai.conversation_research import research_context


def test_read_failures_keep_exact_target_and_do_not_relabel_another_source():
    receipt = {
        "observations": [
            {
                "output": {
                    "tool": "read",
                    "target": "https://review.example/pump",
                    "status": "unavailable",
                    "error_code": "ReachFetchError",
                    "warnings": ["目标页面返回 HTTP 429"],
                }
            },
            {
                "output": {
                    "tool": "read",
                    "target": "https://brand.example/spec",
                    "status": "completed",
                }
            },
        ]
    }
    failures = research_context(receipt)["failures"]
    assert len(failures) == 1
    assert failures[0]["target"] == "https://review.example/pump"
    assert failures[0]["source_host"] == "review.example"
    assert failures[0]["reason"] == "目标页面返回 HTTP 429"
    assert "brand.example" not in str(failures)
    assert "不能归因于其他来源" in failures[0]["attribution"]


def test_search_unavailability_is_distinct_from_no_results_and_page_failures():
    receipt = {
        "observations": [
            {
                "output": {
                    "tool": "search",
                    "target": "公开气泵规格",
                    "status": "unavailable",
                    "error_code": "ReachSearchUnavailableError",
                    "warnings": ["搜索供应商暂不可用"],
                }
            },
            {"output": {"tool": "search", "target": "公开气泵用户反馈", "status": "no_results"}},
        ]
    }
    failures = research_context(receipt)["failures"]
    assert len(failures) == 1 and failures[0]["source_host"] is None
    assert failures[0]["tool"] == "search"
    assert failures[0]["reason"] == "搜索供应商暂不可用"


def test_real_gateway_projection_preserves_research_choices_failures_and_publisher():
    research = research_context(
        {
            "observations": [
                {
                    "output": {
                        "tool": "search",
                        "target": "SUP specs",
                        "status": "completed",
                        "hits": [
                            {
                                "url": "https://brand.example/spec",
                                "title": "Brand specs",
                                "snippet": "public",
                            }
                        ],
                    }
                },
                {
                    "output": {
                        "tool": "read",
                        "target": "https://review.example/pump",
                        "status": "unavailable",
                        "warnings": ["HTTP 429"],
                    }
                },
            ]
        }
    )
    projection = project_gateway_context(
        {
            "research": research,
            "references": [
                {
                    "reference_id": "snapshot:one",
                    "label": "Review · review.example",
                    "source_host": "review.example",
                    "title_origin": "search_hint",
                    "api_key": "never-send",
                }
            ],
        }
    )
    assert projection.payload["research"] == research
    assert projection.payload["references"][0]["source_host"] == "review.example"
    assert projection.payload["references"][0]["title_origin"] == "search_hint"
    assert projection.removed_paths == ("references[0].api_key",)


def test_real_gateway_projection_keeps_goal_and_prior_questions_without_category_internal_fields():
    projection = project_gateway_context(
        {
            "preproject": {
                "goal": "proposal",
                "user_brief": "休闲SUP用户",
                "previous_assessment": {
                    "stage": "clarify",
                    "questions": [
                        {
                            "id": "region",
                            "question": "首批地区？",
                            "options": ["EU", "US"],
                            "recommendation": "EU",
                        }
                    ],
                    "category": None,
                    "proposal": None,
                },
                "category": {
                    "category_id": "category-one",
                    "category_line_id": "line-one",
                    "regions": ["EU"],
                    "parameters": [
                        {
                            "parameter_id": "pressure",
                            "version": 1,
                            "key": "pressure",
                            "unit": "PSI",
                            "conditions": "规定温度",
                            "actor_user_id": "never-send",
                        }
                    ],
                    "owner_user_id": "never-send",
                    "private_customer_original": "never-send",
                },
            }
        }
    )
    value = projection.payload["preproject"]
    assert value["goal"] == "proposal" and value["user_brief"] == "休闲SUP用户"
    assert value["previous_assessment"]["questions"][0]["options"] == ["EU", "US"]
    assert value["previous_assessment"]["category"] is None
    assert value["category"]["parameters"][0]["parameter_id"] == "pressure"
    assert set(projection.removed_paths) == {
        "preproject.category.parameters[0].actor_user_id",
        "preproject.category.owner_user_id",
        "preproject.category.private_customer_original",
    }
    with pytest.raises(ContextProjectionError):
        project_gateway_context(
            {"preproject": {"category": {"regions": [{"private": "never-send"}]}}}
        )
