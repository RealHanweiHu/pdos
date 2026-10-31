"""PG16 HNSW ordering eligibility; no database or provider execution."""

from types import SimpleNamespace
from uuid import UUID as PythonUUID
from uuid import uuid4

import pytest
from sqlalchemy import String, column, table
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import CTE

from pdos_next.enterprise_search import embedding_hybrid as hybrid
from pdos_next.enterprise_search.embedding_hybrid import nearest_statement


@pytest.mark.parametrize("dimensions", [2, 384])
def test_pg16_inner_knn_has_only_distance_and_outer_source_chunk_ties_stay_stable(dimensions):
    allowed = (
        table(
            "authorized_chunks",
            column("chunk_id", UUID),
            column("tenant_id", UUID),
            column("category_id", UUID),
            column("chunk_hash", String),
            column("source_type", String),
            column("source_id", UUID),
        )
        .select()
        .cte("allowed")
    )
    statement = nearest_statement(
        allowed,
        uuid4(),
        uuid4(),
        dimensions,
        (1.0,) + (0.0,) * (dimensions - 1),
        limit=10,
        strategy="iterative",
    )
    ctes = {node.name: node for node in visitors.iterate(statement) if isinstance(node, CTE)}
    pool = ctes["iterative_semantic_pool"].element
    neighbors = ctes["iterative_semantic_neighbors"].element
    dialect = postgresql.dialect()
    order = [str(value.compile(dialect=dialect)) for value in neighbors._order_by_clauses]
    # PG16 amcanorderbyop requires a full pathkey match. A UUID secondary key
    # invalidates this HNSW ordering rather than supplying an incremental sort.
    assert order == [
        f"CAST(enterprise_chunk_embeddings.vector AS vector({dimensions})) <=> "
        f"CAST(%(embedding_query_vector)s AS vector({dimensions}))"
    ]
    sql = str(neighbors.compile(dialect=dialect))
    assert "iterative_semantic_authority AS MATERIALIZED" in sql
    assert "FROM enterprise_chunk_embeddings" in sql
    predicates = " ".join(sql.split()).partition("FROM enterprise_chunk_embeddings")[2]
    for binding in (
        "enterprise_chunk_embeddings.tenant_id =",
        "enterprise_chunk_embeddings.profile_version_id =",
        "enterprise_chunk_embeddings.dimensions =",
        "(enterprise_chunk_embeddings.chunk_id, enterprise_chunk_embeddings.chunk_hash, "
        "enterprise_chunk_embeddings.category_id) IN (SELECT "
        "iterative_semantic_authority.chunk_id, "
        "iterative_semantic_authority.chunk_hash, iterative_semantic_authority.category_id",
        "IS true",
    ):
        assert binding in predicates
    assert neighbors._limit_clause.value == 200
    assert "JOIN iterative_semantic_authority ON" not in sql
    metadata_sql = str(pool.compile(dialect=dialect))
    for binding in ("chunk_id", "chunk_hash", "category_id"):
        assert (
            f"iterative_semantic_neighbors.{binding} = iterative_semantic_authority.{binding}"
            in metadata_sql
        )
    assert pool._limit_clause is None
    ranked = ctes["semantic_source_ranks"].element
    per_source_order = ranked.selected_columns.source_rank.element.order_by
    assert [str(value.compile(dialect=dialect)) for value in per_source_order] == [
        "iterative_semantic_pool.distance",
        "iterative_semantic_pool.chunk_id",
    ]
    assert [str(value.compile(dialect=dialect)) for value in statement._order_by_clauses] == [
        "semantic_source_ranks.distance",
        "semantic_source_ranks.source_id",
        "semantic_source_ranks.chunk_id",
    ]
    assert statement._limit_clause.value == 11


def _authority():
    return table(
        "authorized_chunks",
        column("chunk_id", UUID),
        column("tenant_id", UUID),
        column("category_id", UUID),
        column("chunk_hash", String),
        column("source_type", String),
        column("source_id", UUID),
    ).select()


class ScanSession:
    """Pure control-flow stub; no source binding or database recall claim."""

    def __init__(self, probe_count, stages, *, chunk_counts=None):
        self.probe_count, self.stages = probe_count, list(stages)
        self.chunk_counts = iter(chunk_counts) if chunk_counts is not None else None
        self.calls = []

    def execute(self, statement):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if sql.startswith("SET LOCAL"):
            self.calls.append("set_iterative")
            return None
        assert statement.get_execution_options().get("pdos_semantic_custom_plan") is True
        if "semantic_eligible_chunk" in sql:
            self.calls.append("probe")
            return SimpleNamespace(all=lambda: [(None,)] * self.probe_count)
        strategy = "iterative" if "iterative_semantic_neighbors" in sql else "exact"
        if strategy == "iterative":
            neighbors = next(
                node
                for node in visitors.iterate(statement)
                if isinstance(node, CTE) and node.name == "iterative_semantic_neighbors"
            )
            size = neighbors.element._limit_clause.value
        else:
            size = None
        self.calls.append((strategy, size))
        count = self.stages.pop(0)
        chunks = next(self.chunk_counts) if self.chunk_counts is not None else size
        rows = [
            {
                "source_id": PythonUUID(int=number + 1),
                "source_type": "artifact",
                "chunk_id": PythonUUID(int=number + 100),
                "distance": 0.1,
                "chunk_hash": "a" * 64,
                "work_key": "b" * 64,
                "ordinal": 0,
                "source_rank": 1,
                **({"_candidate_chunk_count": chunks} if strategy == "iterative" else {}),
            }
            for number in range(count)
        ]
        return SimpleNamespace(mappings=lambda: iter(rows))


def _scan(monkeypatch, session, *, strategy="iterative"):
    monkeypatch.setattr(hybrid, "active", lambda *_: (None, SimpleNamespace(dimensions=2)))
    monkeypatch.setattr(hybrid, "readable_chunks", lambda *_args, **_filters: _authority())
    ctx = SimpleNamespace(tenant_id=uuid4())
    evidence = {}
    rows = hybrid.semantic_rows(
        session,
        ctx,
        SimpleNamespace(limit=10),
        uuid4(),
        (1.0, 0.0),
        strategy=strategy,
        scan_evidence=evidence,
    )
    return rows, evidence


@pytest.mark.parametrize("eligible,sources", [(0, 0), (1000, 5)])
def test_small_complete_eligible_set_selects_exact_and_reports_normal_exhaustion(
    monkeypatch,
    eligible,
    sources,
):
    session = ScanSession(eligible, [sources])
    rows, evidence = _scan(monkeypatch, session)
    assert session.calls == ["probe", ("exact", None)]
    assert len(rows) == sources
    assert evidence["requested_strategy"] == "iterative"
    assert evidence["executed_strategy"] == "exact"
    assert evidence["selection_reason"] == "small_authorized_set"
    assert evidence["eligible_probe"]["complete"] is True
    assert evidence["shortfall"] is False and evidence["exhausted"] is True


def test_large_set_expands_until_limit_plus_one_sources_and_keeps_original_stage(monkeypatch):
    session = ScanSession(1001, [4, 7, 11])
    rows, evidence = _scan(monkeypatch, session)
    assert session.calls == [
        "probe",
        "set_iterative",
        ("iterative", 200),
        ("iterative", 400),
        ("iterative", 800),
    ]
    assert len(rows) == 11 and evidence["target_sources"] == 11
    assert [entry["returned_sources"] for entry in evidence["attempts"]] == [4, 7, 11]
    assert [entry["candidate_chunks"] for entry in evidence["attempts"]] == [200, 400, 800]
    assert len(evidence["attempts"][0]["source_ids"]) == 4
    assert evidence["eligible_probe"] == {"returned_chunks": 1001, "limit": 1001, "complete": False}
    assert evidence["shortfall"] is False and evidence["exhausted"] is None
    assert all("_candidate_chunk_count" not in row and "distance" not in row for row in rows)
    public = hybrid.public_scan_evidence(evidence)
    assert all("source_ids" not in attempt for attempt in public["attempts"])


def test_pool_cap_shortfall_never_becomes_exact_or_claims_global_exhaustion(monkeypatch):
    # Short output below every requested pool may also reflect an index scan cap,
    # and therefore cannot establish that the full eligible set was consumed.
    session = ScanSession(1001, [4, 4, 4, 4], chunk_counts=[9, 9, 9, 9])
    rows, evidence = _scan(monkeypatch, session)
    assert session.calls == [
        "probe",
        "set_iterative",
        ("iterative", 200),
        ("iterative", 400),
        ("iterative", 800),
        ("iterative", 1000),
    ]
    assert len(rows) == 4 and evidence["executed_strategy"] == "iterative"
    assert evidence["shortfall"] is True and evidence["exhausted"] is None
    assert evidence["shortfall_reason"] == "distinct_source_target_unmet_within_pool_cap"
    assert [row["candidate_chunks"] for row in evidence["attempts"]] == [9, 9, 9, 9]


def test_requested_exact_skips_probe_and_hybrid_reports_actual_small_set_strategy(monkeypatch):
    session = ScanSession(1001, [5])
    _rows, evidence = _scan(monkeypatch, session, strategy="exact")
    assert session.calls == [("exact", None)] and evidence["eligible_probe"] is None

    def small_exact(*_args, scan_evidence, **_kwargs):
        scan_evidence.update(
            {
                "requested_strategy": "iterative",
                "executed_strategy": "exact",
                "selection_reason": "small_authorized_set",
                "shortfall": False,
                "attempts": [
                    {
                        "strategy": "exact",
                        "pool_limit": None,
                        "candidate_chunks": 10,
                        "returned_sources": 0,
                        "source_ids": ["internal-stage-only"],
                    }
                ],
            }
        )
        return []

    monkeypatch.setattr(hybrid, "semantic_rows", small_exact)
    monkeypatch.setattr(
        hybrid, "search", lambda *_args, **_kwargs: {"items": [], "truncated": False}
    )
    result = hybrid.hybrid_search(
        None,
        None,
        SimpleNamespace(limit=10),
        profile_version_id=uuid4(),
        vector=(1, 0),
        strategy="iterative",
    )
    assert result["semantic"]["requested_scan_strategy"] == "iterative"
    assert result["semantic"]["scan_strategy"] == "exact"
    assert "internal-stage-only" not in str(result)


def test_eligible_probe_binds_same_current_profile_hash_category_before_1001_limit():
    statement = hybrid.eligible_chunks_statement(_authority().cte("allowed"), uuid4(), uuid4(), 384)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    for binding in (
        "enterprise_chunk_embeddings.tenant_id =",
        "enterprise_chunk_embeddings.profile_version_id =",
        "enterprise_chunk_embeddings.dimensions =",
        "enterprise_chunk_embeddings.chunk_id = allowed.chunk_id",
        "enterprise_chunk_embeddings.chunk_hash = allowed.chunk_hash",
        "enterprise_chunk_embeddings.category_id = allowed.category_id",
    ):
        assert binding in sql
    assert statement._limit_clause.value == 1001
    assert list(hybrid.pool_limits(1)) == [100, 200, 400, 800, 1000]
    assert list(hybrid.pool_limits(50)) == [1000]


@pytest.mark.parametrize("small", [False, True])
@pytest.mark.parametrize(
    "attribution", ["replay_only", "same_execution_matched", "query_sequence_mismatch"]
)
def test_multi_sql_observation_preserves_stage_strategy_and_final_physical_plan(
    monkeypatch, small, attribution
):
    import json

    from tests.enterprise_search import embedding_ann_fixture as fixture

    monkeypatch.delenv("PDOS_ANN_AUTO_PLAN", raising=False)
    if attribution != "replay_only":

        class Observer:
            def __init__(self, _connection):
                pass

            def before(self, _statement):
                pass

            def after(self, _statement):
                pass

            def close(self):
                pass

            def collect(self, sanitize):
                plans = [
                    sanitize({"Plan": {"Node Type": "Seq Scan", "Actual Loops": 1}})
                ]
                if not small:
                    plans.append(
                        sanitize(
                            {
                                "Plan": {
                                    "Node Type": "Index Scan",
                                    "Index Name": fixture.HNSW_INDEX,
                                    "Actual Loops": 1,
                                    "Filter": "VECTOR_PARAMETER_MUST_NOT_BE_SERIALIZED",
                                }
                            }
                        )
                    )
                return {
                    "status": attribution,
                    "plans": plans if attribution == "same_execution_matched" else [],
                }

        monkeypatch.setattr(fixture, "AutoPlanCapture", Observer)
    parameter_marker = "VECTOR_PARAMETER_MUST_NOT_BE_SERIALIZED"
    nearest_sql = "semantic_source_ranks " + (
        "exact_semantic_pool" if small else "iterative_semantic_neighbors"
    )
    statements = ["SELECT semantic_eligible_chunk", nearest_sql]
    if not small:
        statements.append(nearest_sql)
    calls = []
    connection = SimpleNamespace(callbacks={})

    def listen(_connection, name, callback):
        connection.callbacks[name] = callback

    def remove(_connection, name, callback):
        assert connection.callbacks.pop(name) is callback

    def run(_session, _ctx, _data, _profile, _vector, *, strategy, scan_evidence):
        assert strategy == "iterative"
        stages = [
            {
                "strategy": "exact" if small else "iterative",
                "pool_limit": None if small else 200,
                "candidate_chunks": 10 if small else 200,
                "returned_sources": 5 if small else 4,
                "source_ids": ["first"],
            }
        ]
        if not small:
            stages.append(
                {
                    "strategy": "iterative",
                    "pool_limit": 400,
                    "candidate_chunks": 400,
                    "returned_sources": 11,
                    "source_ids": ["last"],
                }
            )
        scan_evidence.update(executed_strategy="exact" if small else "iterative", attempts=stages)
        for sql in statements:
            for name in ("before_cursor_execute", "after_cursor_execute"):
                connection.callbacks[name](
                    connection, None, sql, {"vector": parameter_marker}, None, False
                )
        return [{"source_id": "final"}]

    def explain(sql, parameters):
        assert not connection.callbacks  # EXPLAIN is not another production dispatch.
        assert parameters["vector"] == parameter_marker
        calls.append(sql)
        # Only the first ANN stage uses HNSW; a final exact plan must not inherit
        # that physical ANN flag or hide it from the earlier-stage observation.
        hnsw = not small and len(calls) == 2
        node = {
            "Node Type": "Index Scan" if hnsw else "Seq Scan",
            "Actual Loops": 1,
            "Filter": parameter_marker,
        }
        if hnsw:
            node["Index Name"] = fixture.HNSW_INDEX
        return SimpleNamespace(scalar_one=lambda: [{"Plan": node}])

    connection.exec_driver_sql = explain
    monkeypatch.setattr(fixture.event, "listen", listen)
    monkeypatch.setattr(fixture.event, "remove", remove)
    monkeypatch.setattr(fixture, "semantic_rows", run)
    monkeypatch.setattr(fixture, "settings", lambda _session: {"enable_seqscan": "on"})
    monkeypatch.setattr(fixture, "prepared_statement_counts", lambda *_args: {})
    rows, evidence = fixture.semantic_with_plan(
        SimpleNamespace(connection=lambda: connection),
        None,
        None,
        None,
        None,
        "iterative",
    )
    assert rows == [{"source_id": "final"}]
    assert evidence["strategy"] == ("exact" if small else "iterative")
    credited = attribution == "same_execution_matched" and not small
    assert evidence["hnsw_exercised"] is credited
    assert evidence["any_stage_hnsw_exercised"] is credited
    assert evidence["actual_plan_capture"]["status"] == attribution
    assert (evidence["plan"] is not None) is (attribution == "same_execution_matched")
    assert evidence["executions"][0]["explain_replay"]["hnsw_exercised"] is (not small)
    assert len(evidence["probe_executions"]) == 1
    assert [entry["pool_limit"] for entry in evidence["executions"]] == (
        [None] if small else [200, 400]
    )
    assert evidence["executions"][0]["source_ids"] == ["first"]
    assert parameter_marker not in json.dumps(evidence)
