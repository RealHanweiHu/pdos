"""One 32k fixture: source MAT equivalence and a bounded ANN beam/mode diagnostic.

Root alone executes PG. Synthetic geometry validates database mechanisms only.
No model/embedding call, index maintenance, cost override or forced index is used.
"""

import hashlib
import json
import math
import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import bindparam, cast, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

from pdos_next.database import tenant_session
from pdos_next.enterprise_search import embedding_hybrid as hybrid
from pdos_next.enterprise_search.embedding_models import ChunkEmbedding, Vector
from pdos_next.enterprise_search.embedding_runtime import unit_vector
from pdos_next.enterprise_search.schemas import SearchInput
from tests.enterprise_search.embedding_ann_fixture import (
    CHUNKS_PER_SOURCE,
    DIMENSIONS,
    QUERY_SOURCES,
    embedding_fingerprint,
    native_ann_fixture,
    plan_nodes,
    semantic_with_plan,
    settings,
    vector_queries,
    withdraw_audience,
)
from tests.enterprise_search.test_embedding_ann_authority_pg import _compare
from tests.enterprise_search.test_eval_v0_contracts_pg import explicit_target

CONFIGURATIONS = (
    ("strict40", "strict_order", 40),
    ("strict128", "strict_order", 128),
    ("relaxed40", "relaxed_order", 40),
    ("relaxed128", "relaxed_order", 128),
)


def _checkpoint(stream, stage, **values):
    stream.write(
        json.dumps({"at": datetime.now(UTC).isoformat(), "stage": stage, **values}, sort_keys=True)
        + "\n"
    )
    stream.flush()


def _catalog(setup):
    # Administrative access is catalog-only, never a retrieval/recall result.
    with Session(setup.admin) as session:
        vector = dict(
            session.execute(
                text("""
                SELECT n_live_tup,n_dead_tup,last_vacuum::text,last_autovacuum::text,
                  vacuum_count,autovacuum_count,last_analyze::text,last_autoanalyze::text
                FROM pg_stat_all_tables
                WHERE relid='public.enterprise_chunk_embeddings'::regclass
            """)
            )
            .mappings()
            .one()
        )
        index = dict(
            session.execute(
                text("""
                SELECT c.relname,c.reloptions,c.reltuples,c.relpages,am.amname,
                  i.indisvalid,i.indisready,pg_relation_size(c.oid) AS index_bytes
                FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid
                  JOIN pg_am am ON am.oid=c.relam
                WHERE c.oid='public.ix_enterprise_embedding_hnsw_384'::regclass
            """)
            )
            .mappings()
            .one()
        )
        extension = session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        )
    options = dict(value.split("=", 1) for value in index.pop("reloptions") or [])
    defaults = {"m": 16, "ef_construction": 64} if extension == "0.8.6" else {}
    index["parameters"] = {
        key: int(options[key]) if key in options else defaults.get(key)
        for key in ("m", "ef_construction")
    }
    index["implicit_defaults_source"] = "pgvector/v0.8.6/src/hnsw.h" if defaults else None
    return {
        "extension_version": extension,
        "vector_table_statistics_estimates": vector,
        "index": index,
        "dead_graph_causality_established": False,
        "vacuum_or_reindex_performed": False,
    }


def _ordinary(session):
    value = dict(
        session.execute(
            text("""
            SELECT current_user,session_user,rolsuper,rolbypassrls FROM pg_roles
            WHERE rolname=current_user
        """)
        )
        .mappings()
        .one()
    )
    assert value["current_user"] == value["session_user"] == "pdos_next_app"
    assert value["rolsuper"] is value["rolbypassrls"] is False
    return value


def _authorized(session, ctx, data, expected_sources, *, materialize=True):
    rows = hybrid.readable_chunks(
        session, ctx, data, materialize_authority=materialize
    ).subquery("quality_current_authority")
    pairs = {
        (str(source), str(chunk))
        for source, chunk in session.execute(select(rows.c.source_id, rows.c.chunk_id))
    }
    sources = {source for source, _chunk in pairs}
    assert sources == set(map(str, expected_sources))
    assert len(pairs) == len(sources) * CHUNKS_PER_SOURCE
    summary = {
        "sources": len(sources),
        "chunks": len(pairs),
        "source_chunk_set_sha256": hashlib.sha256(
            "\n".join(f"{source}:{chunk}" for source, chunk in sorted(pairs)).encode()
        ).hexdigest(),
    }
    return pairs, summary


def _check_rows(rows, authorized):
    keys = [(row["source_id"], row["chunk_id"]) for row in rows]
    assert set(keys) <= authorized
    assert len({source for source, _chunk in keys}) == len(keys)
    assert all("text" not in row and "vector" not in row for row in rows)
    return keys


def _hotspots(evidence):
    result = []
    for execution in evidence["executions"]:
        if execution["plan"] is None:
            continue
        for node in plan_nodes(execution["plan"]):
            if node.get("Relation Name") or node.get("Node Type") == "CTE Scan":
                rows, loops = node.get("Actual Rows", 0), node.get("Actual Loops", 0)
                result.append(
                    {
                        "pool_limit": execution["pool_limit"],
                        "node": node["Node Type"],
                        "relation": node.get("Relation Name"),
                        "index": node.get("Index Name"),
                        "actual_rows": rows,
                        "actual_loops": loops,
                        "rows_times_loops": rows * loops,
                        "shared_hit_blocks": node.get("Shared Hit Blocks"),
                    }
                )
    return sorted(result, key=lambda value: value["rows_times_loops"], reverse=True)[:12]


def _distances(session, ctx, profile, vector, rows):
    # Post-read scalar diagnostics for already-authorized returned chunks. No
    # vector is selected or serialized, and this is outside production timing.
    v = ChunkEmbedding
    distance = cast(v.vector, Vector(DIMENSIONS)).op("<=>")(
        cast(
            bindparam("diagnostic_query", value=unit_vector(vector), type_=Vector(DIMENSIONS)),
            Vector(DIMENSIONS),
        )
    )
    result = dict(
        session.execute(
            select(v.chunk_id, distance)
            .where(
                v.tenant_id == ctx.tenant_id,
                v.profile_version_id == profile,
                v.dimensions == DIMENSIONS,
                v.chunk_id.in_([UUID(row["chunk_id"]) for row in rows]),
            )
        ).all()
    )
    ordered = [float(result[UUID(row["chunk_id"])]) for row in rows]
    assert all(math.isfinite(value) for value in ordered)
    monotonic = all(
        left <= right + 1e-7 for left, right in zip(ordered, ordered[1:], strict=False)
    )
    assert monotonic, "Production outer window/final ordering must reorder returned candidates"
    return {
        "returned_chunk_cosine_distances": ordered,
        "nondecreasing_with_tolerance_1e_7": monotonic,
        "basis": "post-read app/RR scalar distances for actual returned chunk IDs",
        "included_in_strategy_elapsed": False,
    }


@contextmanager
def _mode(monkeypatch, session, mode):
    original = session.execute
    applied = []

    def execute(statement, *args, **kwargs):
        if (
            mode == "relaxed_order"
            and isinstance(statement, TextClause)
            and str(statement) == "SET LOCAL hnsw.iterative_scan='strict_order'"
        ):
            statement = text("SET LOCAL hnsw.iterative_scan='relaxed_order'")
            applied.append(True)
        return original(statement, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(session, "execute", execute)
        yield applied


def _ab(setup, fixture, monkeypatch, stream, actor, order, vector, output):
    ctx = replace(setup.ctx, actor_id=actor, requester_id=actor)
    data = SearchInput(
        query="synthetic database mechanism only", source_types=["artifact"], limit=10
    )
    expected = (
        set(fixture.source_ids) if actor == setup.human else fixture.public_ids | fixture.shared_ids
    )
    output.update(
        actor_id=str(actor), query_number=0, strategy="exact", order=list(order), variants=[]
    )
    result, identities, authorities = output["variants"], [], []
    reader = hybrid.readable_chunks
    with tenant_session(
        setup.engine, setup.tenant, actor_id=actor, category_id=setup.category, read_snapshot=True
    ) as session:
        output["role"] = _ordinary(session)
        session.execute(text("SET LOCAL hnsw.ef_search=40"))
        session.execute(text("SET LOCAL hnsw.iterative_scan='strict_order'"))
        for materialized in order:
            _checkpoint(stream, "ab_read_started", actor=str(actor), materialized=materialized)
            allowed, summary = _authorized(session, ctx, data, expected, materialize=materialized)
            with monkeypatch.context() as scoped:
                if not materialized:
                    def legacy(*args, **kwargs):
                        assert kwargs.get("materialize_authority") is True
                        return reader(*args, **{**kwargs, "materialize_authority": False})

                    scoped.setattr(hybrid, "readable_chunks", legacy)
                rows, evidence = semantic_with_plan(
                    session, ctx, data, fixture.profile_version, vector, "exact"
                )
            assert evidence["actual_plan_capture"]["status"] == "same_execution_matched"
            identities.append(_check_rows(rows, allowed))
            authorities.append(allowed)
            result.append(
                {
                    "materialized": materialized,
                    "authority": summary,
                    "source_chunk_results": identities[-1],
                    "production_read": evidence,
                    "hotspots": _hotspots(evidence),
                }
            )
            _checkpoint(stream, "ab_read_completed", actor=str(actor), materialized=materialized)
    assert authorities[0] == authorities[1] and identities[0] == identities[1]
    output["same_authority_and_ordered_source_chunk_results"] = True


def _phase(setup, fixture, monkeypatch, stream, phase, actor, expected, vectors, result):
    ctx = replace(setup.ctx, actor_id=actor, requester_id=actor)
    data = SearchInput(
        query="synthetic database mechanism only", source_types=["artifact"], limit=10
    )
    result.update(phase=phase, queries=[])
    with tenant_session(
        setup.engine, setup.tenant, actor_id=actor, category_id=setup.category, read_snapshot=True
    ) as session:
        result["role"] = _ordinary(session)
        allowed, result["authority"] = _authorized(session, ctx, data, expected)
        initial = settings(session)
        assert initial["enable_seqscan"] == initial["row_security"] == "on"
        for number, vector in enumerate(vectors):
            _checkpoint(stream, "exact_started", phase=phase, query_number=number)
            session.execute(text("SET LOCAL hnsw.ef_search=40"))
            session.execute(text("SET LOCAL hnsw.iterative_scan='strict_order'"))
            exact, exact_evidence = semantic_with_plan(
                session, ctx, data, fixture.profile_version, vector, "exact"
            )
            _check_rows(exact, allowed)
            assert len(exact) == 11
            assert exact_evidence["actual_plan_capture"]["status"] == "same_execution_matched"
            exact_distances = _distances(session, ctx, fixture.profile_version, vector, exact)
            entry = {
                "query_number": number,
                "exact": exact_evidence,
                "exact_distances": exact_distances,
                "configurations": [],
            }
            result["queries"].append(entry)
            for label, mode, ef in CONFIGURATIONS:
                _checkpoint(
                    stream, "iterative_started", phase=phase, query_number=number, config=label
                )
                session.execute(text(f"SET LOCAL hnsw.ef_search={ef}"))
                with _mode(monkeypatch, session, mode) as applied:
                    rows, evidence = semantic_with_plan(
                        session, ctx, data, fixture.profile_version, vector, "iterative"
                    )
                assert len(applied) == (1 if mode == "relaxed_order" else 0)
                assert evidence["settings"]["hnsw.ef_search"] == str(ef)
                assert evidence["settings"]["hnsw.iterative_scan"] == mode
                assert evidence["settings"]["enable_seqscan"] == "on"
                assert evidence["settings"]["random_page_cost"] == initial["random_page_cost"]
                assert evidence["actual_plan_capture"]["status"] == "same_execution_matched"
                _check_rows(rows, allowed)
                for attempt in evidence["executions"]:
                    assert set(attempt["source_ids"]) <= set(map(str, expected))
                distances = _distances(session, ctx, fixture.profile_version, vector, rows)
                anchor = str(fixture.source_ids[QUERY_SOURCES[number]])
                item = {
                    "configuration": label, "mode": mode, "ef_search": ef,
                    "test_only_mode_replacements": len(applied),
                    "production_read": evidence,
                    "comparisons": [_compare(exact, rows, k) for k in (5, 10)],
                    "ann_recall_attributed": evidence["hnsw_exercised"],
                    "physical_path": "HNSW" if evidence["hnsw_exercised"] else "non_ANN",
                    "distances": distances,
                    "distance_minus_exact_by_rank": [
                        value - expected_distance
                        for value, expected_distance in zip(
                            distances["returned_chunk_cosine_distances"],
                            exact_distances["returned_chunk_cosine_distances"],
                            strict=False,
                        )
                    ],
                    "anchor_readable": anchor in set(map(str, expected)),
                    "anchor_returned": any(row["source_id"] == anchor for row in rows),
                    "hotspots": _hotspots(evidence),
                }
                entry["configurations"].append(item)
                _checkpoint(
                    stream, "iterative_completed", phase=phase, query_number=number,
                    config=label, physical_path=item["physical_path"],
                    recall_at_10=item["comparisons"][1]["same_filtered_set_recall"],
                )
    result["status"] = "phase_completed"


@pytest.mark.skipif(
    not explicit_target(), reason="Root must bind all roles to guarded 53502/pdos_test"
)
def test_one_fixture_materialization_equivalence_and_beam_mode_quality_diagnostic_pg(
    setup, monkeypatch, record_property
):
    assert os.environ.get("PDOS_ANN_AUTO_PLAN") == "1"
    assert os.environ.get("PDOS_ANN_REPLAY_PLAN") == "0"
    folder = Path(os.environ["PDOS_ANN_AUTHORITY_OUTPUT_DIR"])
    assert folder.is_dir(), "Root must precreate the output directory"
    output, checkpoints = (
        folder / "ann-quality-diagnostic-n32768.json", folder / "ann-quality-checkpoints.jsonl"
    )
    assert not output.exists() and not checkpoints.exists(), "Never overwrite diagnostic evidence"
    observation = {
        "version": "embedding-ann-quality-diagnostic/v1", "status": "not_finished",
        "synthetic_vectors": True, "real_embedding_calls": 0, "real_model_calls": 0,
        "diagnostic_only": True, "vector_count": 32768, "dimensions": DIMENSIONS,
        "pool_threshold_geometry_changed": False, "production_default_mode_changed": False,
        "planner_costs_modified": False, "seqscan_disabled": False,
        "latency_caveats": [
            "authority metadata pre-reads warm caches outside strategy timing",
            "AB order reverses across actors, not within-actor balanced crossover",
            "instrumented observations, not cold-start or production p95 measurements",
        ],
        "not_scored": ["semantic_quality", "real_usage_latency_cost", "formal_ann_acceptance"],
        "materialization_ab": [], "phases": [],
    }
    fixture = None
    with checkpoints.open("x", encoding="utf-8") as stream:
        try:
            observation["catalog_before_seed"] = _catalog(setup)
            _checkpoint(stream, "seed_started", vector_count=32768)
            with native_ann_fixture(setup, 32768) as fixture:
                observation["scope"] = {
                    "tenant_id": str(setup.tenant), "category_id": str(setup.category),
                    "profile_version_id": str(fixture.profile_version),
                }
                observation["projection"] = fixture.projection
                observation["catalog_after_seed"] = _catalog(setup)
                _checkpoint(stream, "seed_completed", vectors=32768, sources=512)
                before = embedding_fingerprint(setup, fixture)
                assert before["rows"] == 32768
                vectors = vector_queries(4)
                for actor, order in ((setup.human, (False, True)), (setup.peer, (True, False))):
                    ab = {}
                    observation["materialization_ab"].append(ab)
                    _ab(setup, fixture, monkeypatch, stream, actor, order, vectors[0], ab)
                for phase, actor, expected in (
                    ("owner_all", setup.human, set(fixture.source_ids)),
                    ("peer_before_revoke", setup.peer, fixture.public_ids | fixture.shared_ids),
                    (
                        "peer_after_revoke", setup.peer,
                        fixture.public_ids | (fixture.shared_ids - fixture.revoked_ids),
                    ),
                ):
                    if phase == "peer_after_revoke":
                        withdraw_audience(setup, fixture)
                        assert before == embedding_fingerprint(setup, fixture)
                        observation["unchanged_vectors_across_revoke"] = before
                    result = {}
                    observation["phases"].append(result)
                    _phase(
                        setup, fixture, monkeypatch, stream, phase, actor, expected, vectors, result
                    )
                    _checkpoint(stream, "phase_completed", phase=phase)
                observation["catalog_before_cleanup"] = _catalog(setup)
            assert fixture.cleanup["status"] == "native_t1_disabled"
            observation["status"] = "diagnostic_control_checks_passed"
        except BaseException as error:
            observation["interruption_type"] = type(error).__name__
            raise
        finally:
            if fixture is not None:
                observation["cleanup"] = fixture.cleanup
                observation["native_t1_receipt_ids"] = fixture.receipts
            try:
                observation["catalog_after_cleanup"] = _catalog(setup)
            except Exception as error:
                observation["catalog_after_cleanup"] = {"error_type": type(error).__name__}
            with output.open("x", encoding="utf-8") as final:
                json.dump(observation, final, ensure_ascii=False, indent=2, sort_keys=True)
                final.write("\n")
            _checkpoint(stream, "finished", status=observation["status"])
            record_property("ann_quality_diagnostic", str(output))


@pytest.mark.parametrize("mode", ["strict_order", "relaxed_order"])
def test_mode_override_changes_only_owned_set_and_preserves_parameters(monkeypatch, mode):
    from types import SimpleNamespace

    calls = []

    def original(statement, *args, **kwargs):
        calls.append((statement, args, kwargs))

    session = SimpleNamespace(execute=original)
    setting = text("SET LOCAL hnsw.iterative_scan='strict_order'")
    other = text("SET LOCAL hnsw.ef_search=128")
    query = select(ChunkEmbedding.chunk_id)
    parameters = {"synthetic_bound_parameter": object()}
    options = {"synthetic_execution_option": object()}
    with _mode(monkeypatch, session, mode) as applied:
        for statement in (setting, other, query):
            session.execute(statement, parameters, execution_options=options)
    assert session.execute is original
    assert len(applied) == (1 if mode == "relaxed_order" else 0)
    assert str(calls[0][0]) == f"SET LOCAL hnsw.iterative_scan='{mode}'"
    assert calls[1][0] is other and calls[2][0] is query
    assert all(args[0] is parameters for _statement, args, _kwargs in calls)
    assert all(kwargs["execution_options"] is options for _statement, _args, kwargs in calls)
