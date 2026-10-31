"""Frozen authored questions → native artifacts → ordinary HTTP keyword recall.

This is a synthetic candidate baseline, not a human-reviewed golden suite or an
answer-quality evaluation. Query outputs never select or change relevance labels.
"""

import importlib
import json
import os
import re
import statistics
import time
from collections import Counter
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from pdos_next.enterprise_search.sources import prepare_read, select_sources
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.enterprise_search.test_retrieval_pg import index, register, session_for

ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "docs/evaluations/xiaopai-v0"
PROTECTED = (
    "artifact_versions", "action_receipts", "audit_entries", "request_keys", "outbox_events",
    "agent_sessions", "agent_runs", "agent_tool_calls", "agent_validation_budgets",
    "enterprise_embedding_calls",
)


def frozen_inputs():
    paths = [DATASET / name for name in ("corpus.json", "questions.json")]
    content = [path.read_bytes() for path in paths]
    corpus, questions = [json.loads(value) for value in content]
    documents = corpus["documents"]
    aliases = [row["alias"] for row in documents]
    assert corpus["synthetic"] is True and corpus["trusted_root"] is False
    assert questions["synthetic"] is True and questions["trusted_root"] is False
    assert questions["status"] == "draft_for_review"
    assert len(set(aliases)) == len(aliases) and 20 <= len(documents) <= 28
    assert len(questions["questions"]) == 40
    assert Counter(row["role"] for row in questions["questions"]) == dict.fromkeys(
        ("engineering", "quality", "production", "procurement"), 10
    )
    for row in questions["questions"]:
        assert set(row["expected_sources"] + row["forbidden_sources"]) <= set(aliases)
    return corpus, questions, {
        path.name: sha256(value).hexdigest() for path, value in zip(paths, content, strict=True)
    }


def snapshot(person):
    with Session(person.admin) as session:
        return {
            table: dict(session.execute(text(
                "SELECT count(*) AS count, "
                "md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id), '')) AS digest "
                f"FROM public.{table} t WHERE tenant_id=:tenant"
            ), {"tenant": person.tenant}).mappings().one())
            for table in PROTECTED
        }


def query(person, prompt, actor):
    response = person.client.post(
        "/v1/personal/enterprise-search",
        headers={"Authorization": "Bearer " + person.tokens[actor]},
        json={"query": prompt, "source_types": ["artifact"], "limit": 10},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_authored_v0_keyword_recall_baseline(setup, monkeypatch, record_property):
    corpus, questions, hashes = frozen_inputs()
    monkeypatch.syspath_prepend(str(ROOT / "pdos-next/tools"))
    metrics = importlib.import_module("xiaopai_recall_metrics")
    bound = {}
    for doc in corpus["documents"]:
        identity = register(setup, doc["title"], doc["body"], doc["visibility"])
        assert index(setup, identity)["status"] == "ready"
        with session_for(setup) as session:
            prepare_read(session, ["artifact"])
            row = session.execute(select_sources(
                source_type="artifact", source_id=identity, include_body=True,
            )).mappings().one()
            assert row["source_id"] == identity and row["is_current"]
            assert doc["body"] in row["body"]
            declared = re.search(r"资料编号[：:]\s*([^；;。\n]+)", doc["body"])
            bound[doc["alias"]] = {
                "source_type": row["source_type"], "source_id": str(row["source_id"]),
                "object_id": str(row["object_id"]), "source_revision": row["source_revision"],
                "content_hash": row["content_hash"], "title": row["title"],
                "visibility": doc["visibility"],
                "document_sha256": sha256(doc["body"].encode()).hexdigest(),
                "declared_code": declared.group(1).strip() if declared else None,
            }
    before = snapshot(setup)
    owner_controls = []
    for doc in corpus["documents"]:
        if doc["visibility"] != "private":
            continue
        target = bound[doc["alias"]]
        page = query(setup, target["source_id"], setup.human)
        assert page["items"] and page["items"][0]["source_id"] == target["source_id"]
        peer = query(setup, target["source_id"], setup.peer)
        assert all(row["source_id"] != target["source_id"] for row in peer["items"])
        owner_controls.append({"alias": doc["alias"], "owner_readable": True,
                               "peer_hidden": True, "actually_indexed": True})
    observations = []
    versions = set()
    fixed_sources = {(row["source_type"], row["source_id"]): row for row in bound.values()}
    for case in questions["questions"]:
        if case["evaluation"] != "retrieval":
            continue
        actor = setup.human if case["actor"] == "owner" else setup.peer
        started = time.perf_counter()
        page = query(setup, case["prompt"], actor)
        elapsed = (time.perf_counter() - started) * 1000
        for item in page["items"]:
            source = fixed_sources[(item["source_type"], item["source_id"])]
            assert item["source_revision"] == source["source_revision"]
            assert item["content_hash"] == source["content_hash"]
        versions.add(page["ranking_version"])
        observations.append({
            "case_id": case["id"], "actor_id": str(actor), "items": page["items"],
            "elapsed_ms": elapsed, "returned": page["returned"],
            "ranking_version": page["ranking_version"], "query_trace": page["query_trace"],
        })
    after = snapshot(setup)
    assert before == after, "Read-only recall evaluation changed protected native state"
    assert before["agent_runs"]["count"] == before["agent_tool_calls"]["count"] == 0
    assert before["enterprise_embedding_calls"]["count"] == 0
    assert len(versions) == 1
    summary = metrics.score(questions, bound, observations)
    identifier_checks = []
    by_case = {row["case_id"]: row for row in observations}
    for case in questions["questions"]:
        if case["evaluation"] != "retrieval" or case["slice"] != "exact_id":
            continue
        found = by_case[case["id"]]["items"]
        trace = by_case[case["id"]]["query_trace"]
        expected_codes = [bound[alias]["declared_code"] for alias in case["expected_sources"]]
        assert all(code and code in case["prompt"] for code in expected_codes)
        passed = all(
            bound[alias]["declared_code"] in trace["codes"] and any(
                item["source_id"] == bound[alias]["source_id"]
                and item["channel"] in {"exact_id", "exact_code"}
                for item in found
            ) for alias in case["expected_sources"]
        )
        identifier_checks.append({"case_id": case["id"], "expected_codes": expected_codes,
                                  "parsed_codes": trace["codes"],
                                  "identifier_channel_hit": passed})
    durations = [row["elapsed_ms"] for row in observations]
    output = {
        "version": "xiaopai-keyword-baseline/v0", "synthetic": True,
        "review_status": "draft_for_review", "trusted_root": False,
        "relevance_labels": "authored and frozen before retrieval; bound by native registration",
        "input_sha256": hashes, "source_family_coverage": ["artifact"],
        "tenant_id": str(setup.tenant), "principal_id": str(setup.human),
        "category_id": str(setup.category), "head": None,
        "bound_sources": bound, "observations": observations, "metrics": summary,
        "identifier_channel_checks": identifier_checks,
        "owner_private_controls": owner_controls,
        "protected_before": before, "protected_after": after,
        "protected_state_unchanged": before == after,
        "measured_http_count": len(observations),
        "latency_ms": {"p50": statistics.median(durations),
                       "p95_inclusive": statistics.quantiles(durations, n=20,
                                                            method="inclusive")[18]},
        "timing_scope": "one HTTP sample per retrieval question; no answer generation",
        "real_model_calls": 0, "real_embedding_calls": 0,
        "answer_quality_evaluated": False, "hybrid_benefit_evaluated": False,
    }
    with Session(setup.admin) as session:
        output["head"] = session.scalar(text("SELECT version_num FROM alembic_version"))
    # The candidate labels are immutable even when retrieval misses a target.
    assert frozen_inputs()[2] == hashes
    for case in questions["questions"]:
        for alias in case["expected_sources"] + case["forbidden_sources"]:
            UUID(bound[alias]["source_id"])
    record_property("xiaopai_keyword_baseline", json.dumps(output, ensure_ascii=False))
    destination = os.environ.get("PDOS_XIAOPAI_EVAL_OUTPUT")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as stream:
            json.dump(output, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        for name, value in (("bound-sources.json", bound), ("observations.json", observations)):
            with (path.parent / name).open("x") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
