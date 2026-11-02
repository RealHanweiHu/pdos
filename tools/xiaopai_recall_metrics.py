"""Offline retrieval scores over labels fixed before a run; no business imports.

Identity is (source_type, source_id). Repeated returned identities keep their first
original position. Missing positive observations score zero with the original denominator and
remain explicitly incomplete. Routing/workflow expectations are never evaluated
by this retrieval scorer. Source-exclusion negatives check forbidden identities
without requiring empty authorized results or a recall denominator. Input review/
provenance flags are copied, not conferred.
"""

import argparse
import json
import math
from collections import Counter
from pathlib import Path

QUESTION_VERSION = "xiaopai-eval-questions/v0"
METRICS_VERSION = "xiaopai-recall-metrics/v0"
EVALUATIONS = {"retrieval", "routing", "workflow"}


def _object(value, location):
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    return value


def _text(value, location):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be a nonempty string")
    return value


def _list(value, location):
    if not isinstance(value, list):
        raise ValueError(f"{location} must be an array")
    return value


def _identity(value, location):
    _object(value, location)
    return (
        _text(value.get("source_type"), f"{location}.source_type"),
        _text(value.get("source_id"), f"{location}.source_id"),
    )


def _aliases(value, bindings, location):
    values = _list(value, location)
    seen, identities = set(), set()
    for alias in values:
        _text(alias, location)
        if alias in seen:
            raise ValueError(f"{location} repeats alias {alias!r}")
        if alias not in bindings:
            raise ValueError(f"{location} has unknown alias {alias!r}")
        if bindings[alias] in identities:
            raise ValueError(f"{location} labels the same source identity more than once")
        seen.add(alias)
        identities.add(bindings[alias])
    return values, identities


def _bindings(value):
    _object(value, "bound_sources")
    result = {}
    for alias, source in value.items():
        _text(alias, "bound_sources alias")
        result[alias] = _identity(source, f"bound_sources[{alias!r}]")
        revision = source.get("source_revision")
        if type(revision) is not int or revision < 1:
            raise ValueError(f"bound_sources[{alias!r}].source_revision must be a positive integer")
        _text(source.get("content_hash"), f"bound_sources[{alias!r}].content_hash")
    return result


def _questions(value, bindings):
    _object(value, "questions")
    if value.get("version") != QUESTION_VERSION:
        raise ValueError(f"questions.version must be {QUESTION_VERSION!r}")
    _text(value.get("status"), "questions.status")
    for flag in ("synthetic", "trusted_root"):
        if type(value.get(flag)) is not bool:
            raise ValueError(f"questions.{flag} must be an explicit boolean")
    result, seen = [], set()
    for index, case in enumerate(_list(value.get("questions"), "questions.questions")):
        location = f"questions.questions[{index}]"
        _object(case, location)
        identity = _text(case.get("id"), f"{location}.id")
        if identity in seen:
            raise ValueError(f"duplicate question id {identity!r}")
        seen.add(identity)
        for field in ("role", "slice", "prompt"):
            _text(case.get(field), f"{location}.{field}")
        if not isinstance(case.get("evaluation"), str) or case["evaluation"] not in EVALUATIONS:
            raise ValueError(f"{location}.evaluation must be retrieval, routing or workflow")
        if not isinstance(case.get("actor"), str) or case["actor"] not in {"owner", "peer"}:
            raise ValueError(f"{location}.actor must be owner or peer")
        expected_aliases, expected = _aliases(
            case.get("expected_sources"),
            bindings,
            f"{location}.expected_sources",
        )
        forbidden_aliases, forbidden = _aliases(
            case.get("forbidden_sources"),
            bindings,
            f"{location}.forbidden_sources",
        )
        if type(case.get("expected_empty")) is not bool:
            raise ValueError(f"{location}.expected_empty must be an explicit boolean")
        if expected & forbidden:
            raise ValueError(f"{location} has overlapping expected and forbidden sources")
        if case["expected_empty"] and expected:
            raise ValueError(f"{location} expects both sources and an empty result")
        if (
            case["evaluation"] == "retrieval"
            and not expected
            and not forbidden
            and not case["expected_empty"]
        ):
            raise ValueError(
                f"{location} needs expected/forbidden sources or explicit expected_empty=true"
            )
        result.append((case, expected_aliases, expected, forbidden_aliases, forbidden))
    return result


def _observations(value, case_ids):
    result = {}
    for index, observation in enumerate(_list(value, "observations")):
        location = f"observations[{index}]"
        _object(observation, location)
        case_id = _text(observation.get("case_id"), f"{location}.case_id")
        if case_id not in case_ids:
            raise ValueError(f"{location} has unknown case_id {case_id!r}")
        if case_id in result:
            raise ValueError(f"duplicate observation for case_id {case_id!r}")
        if "elapsed_ms" in observation:
            elapsed = observation["elapsed_ms"]
            if (
                isinstance(elapsed, bool)
                or not isinstance(elapsed, (int, float))
                or not math.isfinite(elapsed)
                or elapsed < 0
            ):
                raise ValueError(f"{location}.elapsed_ms must be finite and nonnegative")
        result[case_id] = observation
    return result


def _check_summary(rows, name):
    applicable = [row for row in rows if row[name]["status"] != "not_applicable"]
    statuses = Counter(row[name]["status"] for row in applicable)
    return {
        "cases": len(applicable),
        "passed": statuses["passed"],
        "failed": statuses["failed"],
        "missing": statuses["missing_observation"],
        "status": (
            "incomplete"
            if statuses["missing_observation"]
            else "failed"
            if statuses["failed"]
            else "passed"
            if applicable
            else "not_applicable"
        ),
        "failed_case_ids": [
            row["case_id"] for row in applicable if row[name]["status"] == "failed"
        ],
    }


def _aggregate(rows):
    retrieval = [row for row in rows if row["evaluation"] == "retrieval"]
    positive = [row for row in retrieval if row["expected_source_count"]]
    expected = sum(row["expected_source_count"] for row in positive)
    metric = {
        "positive_cases": len(positive),
        "observed_positive_cases": sum(row["observed"] for row in positive),
        "expected_source_count": expected,
        "missing_positive_case_ids": [row["case_id"] for row in positive if not row["observed"]],
    }
    for cutoff in (5, 10):
        hits = sum(row[f"hits_at_{cutoff}"] for row in positive)
        metric[f"hits_at_{cutoff}"] = hits
        metric[f"macro_recall_at_{cutoff}"] = (
            sum(row[f"recall_at_{cutoff}"] for row in positive) / len(positive)
            if positive
            else None
        )
        metric[f"micro_recall_at_{cutoff}"] = hits / expected if expected else None
    metric["mrr"] = (
        sum(row["reciprocal_rank"] for row in positive) / len(positive) if positive else None
    )
    missing = [row["case_id"] for row in retrieval if not row["observed"]]
    return {
        "retrieval": metric,
        "checks": {
            "expected_empty": _check_summary(retrieval, "expected_empty_check"),
            "forbidden": _check_summary(retrieval, "forbidden_check"),
        },
        "coverage": {
            "questions": len(rows),
            "retrieval_cases": len(retrieval),
            "observed_retrieval_cases": sum(row["observed"] for row in retrieval),
            "missing_observation_case_ids": missing,
            "not_evaluated": sum(row["evaluation"] != "retrieval" for row in rows),
        },
    }


def score(questions, bound_sources, observations):
    """Return JSON-compatible scores without changing labels, provenance or inputs.

    Invalid labels/bindings, duplicate cases or duplicate case observations raise
    ValueError. Duplicate returned sources are reported and scored once. Source
    revision/hash fix the supplied binding metadata; ranking matches type+ID only.
    All positive labels, including missing observations, remain in denominators.
    """
    bindings = _bindings(bound_sources)
    cases = _questions(questions, bindings)
    observed = _observations(observations, {case[0]["id"] for case in cases})
    rows = []
    for case, aliases, expected, forbidden_aliases, forbidden in cases:
        observation = observed.get(case["id"])
        row = {
            "case_id": case["id"],
            "role": case["role"],
            "slice": case["slice"],
            "evaluation": case["evaluation"],
            "actor": case["actor"],
            "observed": observation is not None,
        }
        if case["evaluation"] != "retrieval":
            row.update(
                status="not_evaluated", reason="retrieval scorer does not evaluate this mode"
            )
            if "expected_lookup" in case:
                # JSON round trip preserves metadata without returning mutable input aliases.
                row["expected_lookup"] = json.loads(
                    json.dumps(case["expected_lookup"], allow_nan=False)
                )
            rows.append(row)
            continue
        ranked, seen, duplicate_sources = [], set(), []
        if observation is not None:
            items = _list(observation.get("items"), f"observations[{case['id']!r}].items")
            for index, item in enumerate(items):
                identity = _identity(item, f"observations[{case['id']!r}].items[{index}]")
                if identity in seen:
                    duplicate_sources.append(
                        {
                            "source_type": identity[0],
                            "source_id": identity[1],
                            "original_rank": index + 1,
                        }
                    )
                else:
                    seen.add(identity)
                    ranked.append((index + 1, identity))
        row.update(
            status="scored" if observation is not None else "missing_observation",
            expected_source_count=len(expected),
            unique_returned_sources=len(ranked),
            duplicate_sources=duplicate_sources,
        )
        for cutoff in (5, 10):
            hits = {identity for rank, identity in ranked if rank <= cutoff} & expected
            row[f"hits_at_{cutoff}"] = len(hits)
            row[f"recall_at_{cutoff}"] = len(hits) / len(expected) if expected else None
            row[f"found_aliases_at_{cutoff}"] = [
                alias for alias in aliases if bindings[alias] in hits
            ]
        row["reciprocal_rank"] = (
            next(
                (1 / rank for rank, identity in ranked if identity in expected),
                0.0,
            )
            if expected
            else None
        )
        found_forbidden = [alias for alias in forbidden_aliases if bindings[alias] in seen]
        row["forbidden_check"] = {
            "status": (
                "not_applicable"
                if not forbidden
                else "missing_observation"
                if observation is None
                else "failed"
                if found_forbidden
                else "passed"
            ),
            "found_aliases": found_forbidden,
        }
        row["expected_empty_check"] = {
            "status": (
                "not_applicable"
                if not case["expected_empty"]
                else "missing_observation"
                if observation is None
                else "failed"
                if ranked
                else "passed"
            ),
        }
        if observation is not None and "elapsed_ms" in observation:
            row["elapsed_ms"] = observation["elapsed_ms"]
        rows.append(row)
    aggregate = _aggregate(rows)
    missing = aggregate["coverage"]["missing_observation_case_ids"]
    return {
        "version": METRICS_VERSION,
        "status": "incomplete"
        if missing
        else "scored"
        if aggregate["coverage"]["retrieval_cases"]
        else "not_evaluated",
        "provenance": {
            "questions_version": questions["version"],
            "review_status": questions["status"],
            "synthetic": questions["synthetic"],
            "trusted_root": questions["trusted_root"],
        },
        "method": {
            "source_identity": ["source_type", "source_id"],
            "ranking": "first original positions; duplicates never add hits or extend cutoffs",
            "mrr": "first expected source at its original position, without a cutoff",
            "missing_positive_observation": "zero score, fixed original denominator",
            "routing_and_workflow": "not_evaluated",
        },
        **aggregate,
        "by_role": {
            key: _aggregate([row for row in rows if row["role"] == key])
            for key in sorted({row["role"] for row in rows})
        },
        "by_slice": {
            key: _aggregate([row for row in rows if row["slice"] == key])
            for key in sorted({row["slice"] for row in rows})
        },
        "cases": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("questions", type=Path)
    parser.add_argument("bound_sources", type=Path)
    parser.add_argument("observations", type=Path)
    args = parser.parse_args(argv)
    result = score(
        *(
            json.loads(path.read_text(encoding="utf-8"))
            for path in (args.questions, args.bound_sources, args.observations)
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
