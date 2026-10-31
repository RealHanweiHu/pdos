"""C2 natural production ANN plan/authority observations, never semantic scores.

Root alone runs the PG test against explicitly guarded local pdos_test. The four
pure tests collect without a database. No real embedding/model or worker runs.
"""

import hashlib
import json
import math
import os
from dataclasses import replace

import pytest
from sqlalchemy import select, text

from pdos_next.database import tenant_session
from pdos_next.enterprise_search.embedding_sources import readable_chunks
from pdos_next.enterprise_search.schemas import SearchInput
from tests.enterprise_search.embedding_ann_fixture import (
    CHUNKS_PER_SOURCE,
    DIMENSIONS,
    HNSW_INDEX,
    QUERY_SOURCES,
    embedding_fingerprint,
    hnsw_exercised,
    native_ann_fixture,
    safe_plan,
    scale_from_environment,
    semantic_with_plan,
    settings,
    source_body,
    synthetic_vector,
    vector_queries,
    withdraw_audience,
    write_observation,
)
from tests.enterprise_search.test_eval_v0_contracts_pg import explicit_target


def _ids(rows):
    return [row["source_id"] for row in rows[:10]]


def _compare(exact, iterative, k):
    expected, found = _ids(exact)[:k], _ids(iterative)[:k]
    return {
        "k": k,
        "exact_returned": len(expected),
        "iterative_returned": len(found),
        "same_filtered_set_recall": len(set(expected) & set(found)) / len(expected),
        "missing_exact_source_ids": sorted(set(expected) - set(found)),
        "extra_source_ids": sorted(set(found) - set(expected)),
        "exact_source_ids": expected,
        "iterative_source_ids": found,
        "source_dedup_before_vs_after_pool_difference_possible": True,
        "not_a_semantic_quality_score": True,
    }


def _phase(setup, fixture, phase, actor, expected_ids, queries):
    ctx = replace(setup.ctx, actor_id=actor, requester_id=actor)
    data = SearchInput(
        query="synthetic database mechanism only", source_types=["artifact"], limit=10
    )
    with tenant_session(
        setup.engine, setup.tenant, actor_id=actor, category_id=setup.category, read_snapshot=True
    ) as session:
        assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
        assert (
            session.scalar(
                text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
            is False
        )
        initial_settings = settings(session)
        assert initial_settings["enable_seqscan"] == "on"
        assert initial_settings["row_security"] == "on"
        authorized = readable_chunks(session, ctx, data).subquery("c2_authorized_metadata")
        pairs = session.execute(select(authorized.c.source_id, authorized.c.chunk_id)).all()
        visible = {identity for identity, _chunk in pairs}
        assert visible == expected_ids
        assert len(pairs) == len(expected_ids) * CHUNKS_PER_SOURCE
        result = {
            "phase": phase,
            "ordinary_role": "pdos_next_app",
            "read_snapshot": True,
            "authorized_sources": len(visible),
            "authorized_chunks": len(pairs),
            "authorized_set_sha256": hashlib.sha256(
                "\n".join(sorted(map(str, visible))).encode()
            ).hexdigest(),
            "initial_settings": initial_settings,
            "queries": [],
        }
        for number, vector in enumerate(queries):
            exact, exact_plan = semantic_with_plan(
                session,
                ctx,
                data,
                fixture.profile_version,
                vector,
                "exact",
            )
            iterative, iterative_plan = semantic_with_plan(
                session,
                ctx,
                data,
                fixture.profile_version,
                vector,
                "iterative",
            )
            allowed = set(map(str, expected_ids))
            for rows in (exact, iterative):
                identities = [row["source_id"] for row in rows]
                assert len(set(identities)) == len(identities), "Production source dedup must hold"
                assert set(identities) <= allowed, (
                    "Private/revoked source leaked through production SQL"
                )
                assert all("text" not in row and "vector" not in row for row in rows)
            for entry in iterative_plan["executions"]:
                assert set(entry["source_ids"]) <= allowed
                assert len(entry["source_ids"]) == len(set(entry["source_ids"]))
            assert len(exact) == 11  # Native API's extra row establishes top10 truncation.
            target = fixture.source_ids[QUERY_SOURCES[number]]
            if target in expected_ids:
                assert exact[0]["source_id"] == str(target)
            assert (
                exact_plan["settings"]["random_page_cost"] == initial_settings["random_page_cost"]
            )
            assert iterative_plan["settings"]["enable_seqscan"] == "on"
            assert iterative_plan["settings"]["hnsw.iterative_scan"] == "strict_order"
            result["queries"].append(
                {
                    "query_number": number,
                    "plans": [exact_plan, iterative_plan],
                    "top10_supplies_k5_and_k10": True,
                    "production_chunk_pool_limits": [
                        entry["pool_limit"] for entry in iterative_plan["executions"]
                    ],
                    "iterative_stage_comparisons": [
                        {
                            "pool_limit": entry["pool_limit"],
                            "candidate_chunks": entry["candidate_chunks"],
                            "executed_strategy": entry["strategy"],
                            "hnsw_exercised": entry["hnsw_exercised"],
                            "plan_attribution": entry["plan_attribution"],
                            "ann_recall_attributed": entry["hnsw_exercised"],
                            "comparisons": [
                                _compare(
                                    exact,
                                    [{"source_id": identity} for identity in entry["source_ids"]],
                                    k,
                                )
                                for k in (5, 10)
                            ],
                        }
                        for entry in iterative_plan["executions"]
                    ],
                    "any_stage_hnsw_exercised": iterative_plan["any_stage_hnsw_exercised"],
                    "final_stage_hnsw_exercised": iterative_plan["hnsw_exercised"],
                    "source_agreement_basis": "original_select_same_filtered_set",
                    "ann_recall_attributed": iterative_plan["hnsw_exercised"],
                    "scan_evidence": iterative_plan["scan_evidence"],
                    "query_anchor_source_id": str(target),
                    "query_anchor_is_currently_readable": target in expected_ids,
                    "comparisons": [_compare(exact, iterative, k) for k in (5, 10)],
                    "ann_status": "natural_hnsw_exercised"
                    if iterative_plan["hnsw_exercised"]
                    else "ANN_not_exercised",
                }
            )
        result["ann_status"] = (
            "natural_hnsw_exercised"
            if all(row["ann_status"] == "natural_hnsw_exercised" for row in result["queries"])
            else "ANN_not_exercised"
        )
        result["hnsw_exercised_queries"] = sum(
            row["ann_status"] == "natural_hnsw_exercised" for row in result["queries"]
        )
        return result


@pytest.mark.skipif(
    not explicit_target(), reason="Root must bind all roles to guarded 53502/pdos_test"
)
def test_natural_ann_same_authority_exact_private_revoke_and_source_dedup_pg(
    setup, record_property
):
    vector_count, query_count = scale_from_environment()
    observation = {
        "version": "embedding-ann-authority-mechanism/v2",
        "vector_count": vector_count,
        "dimensions": DIMENSIONS,
        "synthetic_vectors": True,
        "synthetic_business_bulk_seed": True,
        "real_model_calls": 0,
        "real_embedding_calls": 0,
        "status": "not_finished",
        "phases": [],
        "not_scored": ["semantic_relevance", "real_embedding_quality", "native_command_throughput"],
        "strategy_selection": "server eligible<=1000 exact; otherwise bounded iterative pool",
        "planner_costs_modified": False,
        "seqscan_disabled": False,
    }
    fixture = None
    try:
        with native_ann_fixture(setup, vector_count) as fixture:
            observation["scope"] = {
                "tenant_id": str(setup.tenant),
                "category_id": str(setup.category),
                "profile_version_id": str(fixture.profile_version),
                "source_ids": list(map(str, fixture.source_ids)),
            }
            observation["projection"] = fixture.projection
            before = embedding_fingerprint(setup, fixture)
            assert before["rows"] == vector_count
            queries = vector_queries(query_count)
            for name, actor, allowed in (
                ("owner_all", setup.human, set(fixture.source_ids)),
                (
                    "peer_public32_plus_audience32",
                    setup.peer,
                    fixture.public_ids | fixture.shared_ids,
                ),
            ):
                observation["phases"].append(_phase(setup, fixture, name, actor, allowed, queries))
            withdraw_audience(setup, fixture)
            after = embedding_fingerprint(setup, fixture)
            assert before == after, "Revocation must not rebuild/remove existing vectors"
            observation["unchanged_vectors_across_revoke"] = before
            observation["phases"].append(
                _phase(
                    setup,
                    fixture,
                    "peer_after_audience16_revoked",
                    setup.peer,
                    fixture.public_ids | (fixture.shared_ids - fixture.revoked_ids),
                    queries,
                )
            )
            low = observation["phases"][1:]
            observation["status"] = (
                "natural_ann_mechanism_observed"
                if all(row["ann_status"] == "natural_hnsw_exercised" for row in low)
                else "ANN_not_exercised"
            )
            observation["authority_checks"] = "passed_for_both_production_strategies"
        assert fixture.cleanup["status"] == "native_t1_disabled"
    finally:
        if fixture is not None:
            observation["cleanup"] = fixture.cleanup
            observation["native_t1_receipt_ids"] = fixture.receipts
        path = write_observation(
            os.environ.get("PDOS_ANN_AUTHORITY_OUTPUT_DIR"), vector_count, observation
        )
        if path:
            record_property("ann_authority_observation", str(path))


def test_synthetic_vectors_are_dense_distinct_unit_and_text_independent():
    values = [synthetic_vector(source, ordinal) for source in (0, 17, 88) for ordinal in (0, 1, 63)]
    assert values[0] == synthetic_vector(0, 0)
    assert len(set(values)) == len(values)
    assert all(
        len(row) == DIMENSIONS and all(math.isfinite(item) and item != 0 for item in row)
        for row in values
    )
    assert all(abs(math.fsum(item * item for item in row) - 1) < 1e-12 for row in values)
    assert len(vector_queries(4)) == 4 and len(vector_queries(8)) == 8
    assert sum(a * b for a, b in zip(values[0], values[1], strict=True)) > 0.99
    assert sum(a * b for a, b in zip(values[0], values[3], strict=True)) < 0.2


def test_all_source_paragraphs_are_real_projector_chunks_with_exact_locators():
    from pdos_next.enterprise_search.indexing import chunks

    body = source_body(127)
    projected = list(chunks(body))
    assert len(projected) == CHUNKS_PER_SOURCE
    assert len({text for text, _ in projected}) == CHUNKS_PER_SOURCE
    for content, locator in projected:
        assert body[locator["char_start"] : locator["char_end"]] == content
        assert locator["native"] == [f"line:{locator['line_start']}"]


def test_plan_whitelist_drops_every_expression_literal_and_body():
    secret = "PRIVATE_BODY vector '[1,2,3]'::vector"
    raw = {
        "Plan": {
            "Node Type": "Index Scan",
            "Index Name": HNSW_INDEX,
            "Actual Loops": 1,
            "Actual Rows": 48,
            "Rows Removed by Filter": 16,
            "Shared Hit Blocks": 99,
            "Order By": f"vector <=> {secret}",
            "Filter": secret,
            "Output": [secret],
            "Workers": [{"Output": [secret]}],
            "Unknown": secret,
            "Plans": [{"Node Type": "Seq Scan", "Filter": secret, "Actual Rows": 10}],
        },
        "Query Text": secret,
        "Settings": {"custom_variable": secret},
        "Execution Time": 2.5,
        "Planning Time": 1.2,
    }
    cleaned = safe_plan(raw)
    assert secret not in json.dumps(cleaned)
    assert cleaned["Plan"]["has_distance_order"] is True
    assert cleaned["Plan"]["Rows Removed by Filter"] == 16
    assert hnsw_exercised(cleaned)
    raw["Plan"]["Actual Loops"] = 0
    assert not hnsw_exercised(safe_plan(raw))


def test_observation_refuses_overwrite_and_scale_is_explicit(tmp_path, monkeypatch):
    monkeypatch.delenv("PDOS_ANN_AUTHORITY_VECTORS", raising=False)
    monkeypatch.delenv("PDOS_ANN_AUTHORITY_QUERIES", raising=False)
    assert scale_from_environment() == (8192, 4)
    monkeypatch.setenv("PDOS_ANN_AUTHORITY_VECTORS", "32768")
    monkeypatch.setenv("PDOS_ANN_AUTHORITY_QUERIES", "8")
    assert scale_from_environment() == (32768, 8)
    monkeypatch.setenv("PDOS_ANN_AUTHORITY_VECTORS", "1000000")
    with pytest.raises(ValueError):
        scale_from_environment()
    observation = {"status": "ANN_not_exercised", "real_embedding_calls": 0}
    path = write_observation(tmp_path, 8192, observation)
    assert json.loads(path.read_text()) == observation
    with pytest.raises(FileExistsError):
        write_observation(tmp_path, 8192, {"status": "replacement"})
