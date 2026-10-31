"""Fixed-label retrieval scores and honest coverage; standard JSON and no services."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def metrics(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    return importlib.import_module("xiaopai_recall_metrics")


def binding(identity, source_type="knowledge"):
    return {
        "source_id": identity,
        "source_type": source_type,
        "source_revision": 1,
        "content_hash": "fixed-before-run",
    }


def case(
    identity,
    expected,
    *,
    role="engineer",
    slice_name="D",
    evaluation="retrieval",
    forbidden=None,
    empty=False,
):
    return {
        "id": identity,
        "role": role,
        "slice": slice_name,
        "prompt": "Read the pre-labelled current native source",
        "evaluation": evaluation,
        "actor": "owner",
        "expected_sources": expected,
        "forbidden_sources": forbidden or [],
        "expected_empty": empty,
    }


def questions(*cases):
    return {
        "version": "xiaopai-eval-questions/v0",
        "status": "draft_for_review",
        "synthetic": True,
        "trusted_root": False,
        "questions": list(cases),
    }


def observation(identity, *items):
    return {"case_id": identity, "items": list(items), "elapsed_ms": 12.5}


def test_multiple_expected_sources_partial_hits_macro_micro_and_fixed_mrr(metrics):
    labels = questions(case("multi", ["a", "b"]), case("single", ["c"]))
    bindings = {name: binding(name) for name in ("a", "b", "c")}
    observations = [
        observation("multi", binding("noise"), binding("a")),
        observation("single", binding("c")),
    ]
    original = deepcopy((labels, bindings, observations))
    value = metrics.score(labels, bindings, observations)
    assert value["retrieval"]["macro_recall_at_5"] == 0.75
    assert value["retrieval"]["micro_recall_at_5"] == pytest.approx(2 / 3)
    assert value["retrieval"]["macro_recall_at_10"] == 0.75
    assert value["retrieval"]["micro_recall_at_10"] == pytest.approx(2 / 3)
    assert value["retrieval"]["mrr"] == 0.75
    assert value["cases"][0]["found_aliases_at_5"] == ["a"]
    assert (labels, bindings, observations) == original
    json.dumps(value, allow_nan=False)


def test_returned_duplicate_cannot_inflate_hits_and_reports_first_occurrence_ranking(metrics):
    value = metrics.score(
        questions(case("q", ["a", "b"])),
        {"a": binding("a"), "b": binding("b")},
        [
            observation(
                "q",
                binding("a"),
                binding("a"),
                binding("a"),
                binding("noise-1"),
                binding("noise-2"),
                binding("b"),
            )
        ],
    )
    assert value["retrieval"]["hits_at_5"] == 1
    assert value["retrieval"]["micro_recall_at_5"] == 0.5
    assert value["retrieval"]["hits_at_10"] == 2
    assert value["cases"][0]["unique_returned_sources"] == 4
    assert [row["original_rank"] for row in value["cases"][0]["duplicate_sources"]] == [2, 3]
    late = metrics.score(
        questions(case("q", ["b"])),
        {"b": binding("b")},
        [
            observation(
                "q",
                binding("noise"),
                binding("noise"),
                binding("noise"),
                binding("x"),
                binding("y"),
                binding("b"),
            )
        ],
    )
    assert late["retrieval"]["mrr"] == pytest.approx(1 / 6)
    assert late["retrieval"]["hits_at_5"] == 0


def test_cutoffs_count_all_expected_sources_and_mrr_can_see_beyond_ten(metrics):
    bindings = {"a": binding("a"), "b": binding("b")}
    noise = [binding(f"noise-{index}") for index in range(5)]
    value = metrics.score(
        questions(case("q", ["a", "b"])), bindings, [observation("q", *noise, binding("a"))]
    )
    assert value["retrieval"]["macro_recall_at_5"] == 0
    assert value["retrieval"]["micro_recall_at_10"] == 0.5
    assert value["retrieval"]["mrr"] == pytest.approx(1 / 6)
    late = metrics.score(
        questions(case("q", ["a"])),
        bindings,
        [observation("q", *[binding(str(i)) for i in range(10)], binding("a"))],
    )
    assert late["retrieval"]["micro_recall_at_10"] == 0
    assert late["retrieval"]["mrr"] == pytest.approx(1 / 11)


def test_negative_empty_and_forbidden_leak_are_separate_and_outside_recall(metrics):
    value = metrics.score(
        questions(case("private", [], forbidden=["private"], empty=True)),
        {"private": binding("private")},
        [observation("private", binding("private"), binding("private"))],
    )
    assert value["retrieval"]["positive_cases"] == 0
    assert value["retrieval"]["macro_recall_at_5"] is None
    assert value["checks"]["expected_empty"]["failed_case_ids"] == ["private"]
    assert value["checks"]["forbidden"]["failed"] == 1
    assert value["cases"][0]["forbidden_check"]["found_aliases"] == ["private"]


def test_source_exclusion_allows_other_authorized_results_without_a_recall_denominator(metrics):
    value = metrics.score(
        questions(case("private", [], forbidden=["private"], empty=False)),
        {"private": binding("private")},
        [observation("private", binding("authorized-public"))],
    )
    assert value["status"] == "scored"
    assert value["retrieval"]["positive_cases"] == 0
    assert value["retrieval"]["expected_source_count"] == 0
    assert all(
        value["retrieval"][key] is None
        for key in (
            "macro_recall_at_5",
            "macro_recall_at_10",
            "micro_recall_at_5",
            "micro_recall_at_10",
            "mrr",
        )
    )
    assert value["checks"]["expected_empty"]["status"] == "not_applicable"
    assert value["checks"]["forbidden"]["passed"] == 1
    assert value["cases"][0]["forbidden_check"]["found_aliases"] == []


def test_source_exclusion_fails_actual_private_leak_among_other_authorized_results(metrics):
    value = metrics.score(
        questions(case("private", [], forbidden=["private"], empty=False)),
        {"private": binding("private")},
        [observation("private", binding("authorized-public"), binding("private"))],
    )
    assert value["retrieval"]["positive_cases"] == 0
    assert value["retrieval"]["micro_recall_at_5"] is None
    assert value["checks"]["expected_empty"]["status"] == "not_applicable"
    assert value["checks"]["forbidden"]["status"] == "failed"
    assert value["checks"]["forbidden"]["failed_case_ids"] == ["private"]
    assert value["cases"][0]["forbidden_check"]["found_aliases"] == ["private"]


def test_missing_positive_and_negative_observations_remain_explicit_and_in_denominator(metrics):
    labels = questions(
        case("seen", ["a"]),
        case("missing", ["b"]),
        case("negative", [], empty=True, forbidden=["a"]),
    )
    value = metrics.score(
        labels, {"a": binding("a"), "b": binding("b")}, [observation("seen", binding("a"))]
    )
    assert value["status"] == "incomplete"
    assert value["retrieval"]["positive_cases"] == 2
    assert value["retrieval"]["observed_positive_cases"] == 1
    assert value["retrieval"]["micro_recall_at_5"] == 0.5
    assert value["retrieval"]["macro_recall_at_10"] == 0.5
    assert value["retrieval"]["mrr"] == 0.5
    assert value["coverage"]["missing_observation_case_ids"] == ["missing", "negative"]
    assert value["checks"]["expected_empty"]["status"] == "incomplete"
    assert value["checks"]["forbidden"]["passed"] == 0
    assert value["cases"][1]["status"] == "missing_observation"


def test_routing_workflow_are_not_evaluated_and_reviewed_provenance_is_only_copied(metrics):
    route = case("route", ["a"], evaluation="routing")
    route["expected_lookup"] = {"tool": "assistant.search", "then": ["citation.open"]}
    labels = questions(case("read", ["a"]), route, case("write", [], evaluation="workflow"))
    labels.update(status="human_reviewed", synthetic=False, trusted_root=True)
    value = metrics.score(
        labels, {"a": binding("a")}, [observation("read", binding("a")), {"case_id": "route"}]
    )
    assert value["retrieval"]["positive_cases"] == 1 and value["retrieval"]["mrr"] == 1
    assert value["coverage"]["not_evaluated"] == 2
    assert value["coverage"]["missing_observation_case_ids"] == []
    assert [row["status"] for row in value["cases"]] == ["scored", "not_evaluated", "not_evaluated"]
    assert value["cases"][1]["expected_lookup"] == route["expected_lookup"]
    assert value["cases"][2]["observed"] is False
    assert value["provenance"] == {
        "questions_version": "xiaopai-eval-questions/v0",
        "review_status": "human_reviewed",
        "synthetic": False,
        "trusted_root": True,
    }
    value["cases"][1]["expected_lookup"]["then"].append("modified output")
    assert route["expected_lookup"]["then"] == ["citation.open"]


def test_zero_denominator_is_null_with_no_fabricated_retrieval_pass(metrics):
    empty = metrics.score(questions(), {}, [])
    assert empty["status"] == "not_evaluated"
    assert all(
        empty["retrieval"][key] is None
        for key in (
            "macro_recall_at_5",
            "macro_recall_at_10",
            "micro_recall_at_5",
            "micro_recall_at_10",
            "mrr",
        )
    )
    value = metrics.score(questions(case("empty", [], empty=True)), {}, [observation("empty")])
    assert value["retrieval"]["expected_source_count"] == 0
    assert value["checks"]["expected_empty"]["passed"] == 1
    assert value["checks"]["forbidden"]["status"] == "not_applicable"


def test_role_slice_metrics_use_their_own_original_labels(metrics):
    labels = questions(
        case("eng", ["a", "b"], slice_name="B"),
        case("quality", ["c"], role="quality", slice_name="B"),
        case("missing", ["d"], role="quality", slice_name="D"),
    )
    value = metrics.score(
        labels,
        {key: binding(key) for key in "abcd"},
        [observation("eng", binding("a")), observation("quality", binding("c"))],
    )
    assert value["by_role"]["engineer"]["retrieval"]["micro_recall_at_5"] == 0.5
    assert value["by_role"]["quality"]["retrieval"]["macro_recall_at_5"] == 0.5
    assert value["by_slice"]["B"]["retrieval"]["macro_recall_at_5"] == 0.75
    assert value["by_slice"]["B"]["retrieval"]["micro_recall_at_5"] == pytest.approx(2 / 3)
    assert value["by_slice"]["D"]["coverage"]["missing_observation_case_ids"] == ["missing"]


def test_equal_ids_in_different_source_types_are_distinct_relevance_labels(metrics):
    bindings = {
        "knowledge": binding("shared", "knowledge"),
        "feedback": binding("shared", "field_feedback"),
    }
    value = metrics.score(
        questions(case("q", ["knowledge", "feedback"])),
        bindings,
        [observation("q", binding("shared", "field_feedback"), binding("shared", "artifact"))],
    )
    assert value["retrieval"]["expected_source_count"] == 2
    assert value["retrieval"]["micro_recall_at_5"] == 0.5
    assert value["cases"][0]["found_aliases_at_5"] == ["feedback"]
    assert value["cases"][0]["duplicate_sources"] == []


@pytest.mark.parametrize(
    "problem",
    [
        "unknown_alias",
        "duplicate_case",
        "duplicate_observation",
        "unknown_observation",
        "missing_items",
        "overlap",
        "unlabelled",
        "missing_bound_metadata",
        "invalid_elapsed",
    ],
)
def test_invalid_input_cannot_be_silently_scored(metrics, problem):
    labels = questions(case("q", ["a"]))
    bindings, observations = {"a": binding("a")}, [observation("q", binding("a"))]
    if problem == "unknown_alias":
        labels["questions"][0]["expected_sources"] = ["unknown"]
    elif problem == "duplicate_case":
        labels["questions"].append(deepcopy(labels["questions"][0]))
    elif problem == "duplicate_observation":
        observations.append(deepcopy(observations[0]))
    elif problem == "unknown_observation":
        observations[0]["case_id"] = "unknown"
    elif problem == "missing_items":
        del observations[0]["items"]
    elif problem == "overlap":
        labels["questions"][0]["forbidden_sources"] = ["a"]
    elif problem == "unlabelled":
        labels["questions"][0]["expected_sources"] = []
    elif problem == "missing_bound_metadata":
        del bindings["a"]["content_hash"]
    else:
        observations[0]["elapsed_ms"] = float("nan")
    with pytest.raises(ValueError):
        metrics.score(labels, bindings, observations)
