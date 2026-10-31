"""Deterministic, explicitly synthetic C2 database-mechanism support.

Business seeds are bulk test data, not native-command throughput evidence. Chunks
come from the real projector; vectors do not come from an embedding model. Native
T1 profile receipts remain, and native disable removes this profile's vectors.
"""

import hashlib
import json
import math
import os
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import event, func, insert, select, text
from sqlalchemy.orm import Session

from pdos_next.database import tenant_session
from pdos_next.enterprise_search.embedding_hybrid import semantic_rows
from pdos_next.enterprise_search.embedding_models import ChunkEmbedding
from pdos_next.enterprise_search.indexing import chunks, project
from pdos_next.enterprise_search.models import SearchChunk, SearchSource
from pdos_next.models import Artifact, ObjectAudience
from tests.enterprise_search.embedding_ann_auto_plan import AutoPlanCapture, sql_digest
from tests.enterprise_search.embedding_harness import command_for, ports_for, save_profile

DIMENSIONS = 384
CHUNKS_PER_SOURCE = 64
DEFAULT_VECTORS = 8192
SCALES = (8192, 32768)
HNSW_INDEX = "ix_enterprise_embedding_hnsw_384"
QUERY_SOURCES = (0, 17, 46, 88, 9, 39, 71, 111)
GUC_NAMES = (
    "enable_seqscan",
    "enable_indexscan",
    "enable_indexonlyscan",
    "enable_bitmapscan",
    "enable_incremental_sort",
    "random_page_cost",
    "seq_page_cost",
    "cpu_tuple_cost",
    "cpu_index_tuple_cost",
    "cpu_operator_cost",
    "effective_cache_size",
    "work_mem",
    "plan_cache_mode",
    "row_security",
    "hnsw.iterative_scan",
    "hnsw.ef_search",
    "hnsw.max_scan_tuples",
    "hnsw.scan_mem_multiplier",
)
PLAN_FIELDS = frozenset(
    {
        "Node Type",
        "Parent Relationship",
        "Relation Name",
        "Schema",
        "Index Name",
        "Join Type",
        "Scan Direction",
        "Strategy",
        "Partial Mode",
        "Parallel Aware",
        "Async Capable",
        "Plan Rows",
        "Plan Width",
        "Startup Cost",
        "Total Cost",
        "Actual Startup Time",
        "Actual Total Time",
        "Actual Rows",
        "Actual Loops",
        "Rows Removed by Filter",
        "Rows Removed by Join Filter",
        "Rows Removed by Index Recheck",
        "Shared Hit Blocks",
        "Shared Read Blocks",
        "Shared Dirtied Blocks",
        "Shared Written Blocks",
        "Local Hit Blocks",
        "Local Read Blocks",
        "Local Dirtied Blocks",
        "Local Written Blocks",
        "Temp Read Blocks",
        "Temp Written Blocks",
        "I/O Read Time",
        "I/O Write Time",
        "Sort Method",
        "Sort Space Used",
        "Sort Space Type",
        "Heap Fetches",
        "Workers Planned",
        "Workers Launched",
        "Hash Batches",
        "Peak Memory Usage",
    }
)
RELATIONS = (
    "artifact_versions",
    "enterprise_search_chunks",
    "enterprise_search_sources",
    "enterprise_chunk_embeddings",
    "ix_enterprise_embedding_hnsw_384",
)


def scale_from_environment():
    count = int(os.environ.get("PDOS_ANN_AUTHORITY_VECTORS", str(DEFAULT_VECTORS)))
    if count not in SCALES:
        raise ValueError(f"Explicit supported synthetic vector count required: {SCALES}")
    queries = int(os.environ.get("PDOS_ANN_AUTHORITY_QUERIES", "4"))
    if queries not in (4, 8):
        raise ValueError("Use four queries by default, or explicitly request eight")
    return count, queries


def source_body(source_number):
    # Blank paragraphs give exactly 64 real, independently located projector chunks.
    return (
        "\n\n".join(
            f"Synthetic ANN mechanism source {source_number:04d}, paragraph {ordinal:02d}. "
            "This is not an engineering finding or a semantic benchmark."
            for ordinal in range(CHUNKS_PER_SOURCE)
        )
        + "\n"
    )


def synthetic_vector(source_number, ordinal):
    """Dense, distinct unit vectors with intentional same-source clustering.

    The clustered 64-chunk sources expose the production pool-before-source-dedup
    tradeoff. Geometry and query coordinates are unrelated to source text.
    """
    rng = random.Random(f"pdos-ann-mechanism/v1:{source_number}:{ordinal}")
    centroid = random.Random(f"pdos-ann-mechanism-centroid/v1:{source_number}")
    values = [centroid.uniform(-1, 1) + 0.015 * rng.uniform(-1, 1) for _ in range(DIMENSIONS)]
    norm = math.sqrt(math.fsum(value * value for value in values))
    return tuple(value / norm for value in values)


def vector_queries(count):
    return tuple(synthetic_vector(number, CHUNKS_PER_SOURCE) for number in QUERY_SOURCES[:count])


def safe_plan(raw):
    """Keep structural metrics only: no expressions, SQL, literals or source text."""

    def node(value):
        result = {key: value[key] for key in PLAN_FIELDS if key in value}
        result["has_distance_order"] = any(
            "<=>" in str(value.get(key, "")) for key in ("Order By", "Sort Key", "Presorted Key")
        )
        if value.get("Plans"):
            result["Plans"] = [node(child) for child in value["Plans"]]
        # Parallel worker metrics also contain expressions in some PG releases;
        # their summary counters above suffice for this experiment.
        return result

    result = {"Plan": node(raw["Plan"])}
    for key in ("Planning Time", "Execution Time"):
        if key in raw:
            result[key] = raw[key]
    if "Planning" in raw:
        result["Planning"] = {
            key: value for key, value in raw["Planning"].items() if key in PLAN_FIELDS
        }
    return result


def plan_nodes(plan):
    root = plan.get("Plan", plan)
    yield root
    for child in root.get("Plans", []):
        yield from plan_nodes(child)


def hnsw_exercised(plan):
    return any(
        node.get("Index Name") == HNSW_INDEX and node.get("Actual Loops", 0) > 0
        for node in plan_nodes(plan)
    )


def write_observation(directory, count, observation):
    if not directory:
        return None
    target = Path(directory)
    if not target.is_dir():
        raise ValueError("Root must precreate PDOS_ANN_AUTHORITY_OUTPUT_DIR")
    path = target / f"ann-authority-n{count}.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(observation, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def settings(session):
    return {
        # A fresh backend may not have loaded pgvector's custom GUCs until its
        # first vector operation. NULL here means not yet loaded, never a default.
        name: session.scalar(text("SELECT current_setting(:name, true)"), {"name": name})
        for name in GUC_NAMES
    }


def prepared_statement_counts(session, statements):
    """Same backend counters; query text stays in memory and is never returned."""
    expected = {sql_digest(sql) for sql in statements if "semantic_source_ranks" in sql}
    rows = session.execute(
        text(
            "SELECT name,CASE WHEN statement LIKE '%semantic_source_ranks%' "
            "THEN statement END AS statement,custom_plans,generic_plans "
            "FROM pg_prepared_statements ORDER BY name"
        )
    ).mappings()
    result, non_target = [], 0
    for row in rows:
        normalized = sql_digest(row["statement"]) if row["statement"] is not None else None
        # EXPLAIN replays and this observer's own SQL may contain the marker.
        # Only this call's actual nearest statement hashes belong to its rows.
        if normalized in expected:
            result.append(
                {
                    "name": row["name"],
                    "normalized_sql_sha256": normalized,
                    "custom_plans": row["custom_plans"],
                    "generic_plans": row["generic_plans"],
                }
            )
        else:
            non_target += 1
    return {
        "matching_statements": result,
        "driver_prepare_threshold": (
            session.connection().connection.driver_connection.prepare_threshold
        ),
        "non_target_prepared_statements": non_target,
    }


def semantic_with_plan(session, ctx, data, profile, vector, strategy):
    """Separate same-SELECT auto_explain from independent EXPLAIN replays.

    Parameters stay in memory and are never serialized. No replacement distance
    query, cost override, seqscan switch, or replay earns original-row ANN credit.
    """
    replay_option = os.environ.get("PDOS_ANN_REPLAY_PLAN", "1")
    if replay_option not in ("0", "1"):
        raise ValueError("PDOS_ANN_REPLAY_PLAN must be 0 or 1")
    replay_enabled = replay_option == "1"
    if not replay_enabled and os.environ.get("PDOS_ANN_AUTO_PLAN") != "1":
        raise ValueError("PDOS_ANN_REPLAY_PLAN=0 requires PDOS_ANN_AUTO_PLAN=1")
    connection = session.connection()
    captured = []
    scan_evidence = {}
    actual = AutoPlanCapture(connection)

    def capture(_connection, _cursor, statement, parameters, _context, executemany):
        if "semantic_source_ranks" in statement or "semantic_eligible_chunk" in statement:
            assert not executemany
            copied = dict(parameters) if isinstance(parameters, dict) else tuple(parameters)
            captured.append((statement, copied))
            actual.before(statement)

    def complete(_connection, _cursor, statement, _parameters, _context, _executemany):
        actual.after(statement)

    event.listen(connection, "before_cursor_execute", capture)
    event.listen(connection, "after_cursor_execute", complete)
    try:
        strategy_started = perf_counter()
        rows = semantic_rows(
            session,
            ctx,
            data,
            profile,
            vector,
            strategy=strategy,
            scan_evidence=scan_evidence,
        )
        strategy_elapsed_ms = (perf_counter() - strategy_started) * 1000
    finally:
        event.remove(connection, "before_cursor_execute", capture)
        event.remove(connection, "after_cursor_execute", complete)
        actual.close()
    assert captured, "Actual production SQL must execute"
    prepared_counts = prepared_statement_counts(session, [sql for sql, _parameters in captured])
    attribution = actual.collect(safe_plan)
    actual_plans = attribution.pop("plans")
    executions, probes = [], []
    for sql, parameters in captured:
        is_probe = "semantic_source_ranks" not in sql
        actual_strategy = (
            "eligible_probe"
            if is_probe
            else "iterative"
            if "iterative_semantic_neighbors" in sql
            else "exact"
        )
        replay = None
        if replay_enabled:
            raw = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
                parameters,
            ).scalar_one()[0]
            replay = safe_plan(raw)
        plan = actual_plans[len(executions)] if actual_plans and not is_probe else None
        item = {
            "strategy": actual_strategy,
            "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "normalized_sql_sha256": sql_digest(sql),
            "plan": plan,
            "plan_attribution": attribution["status"]
            if not is_probe
            else "replay_only"
            if replay_enabled
            else "not_observed",
            "hnsw_exercised": bool(plan and hnsw_exercised(plan)),
            "explain_replay": {
                "enabled": replay_enabled,
                "plan": replay,
                "hnsw_exercised": bool(replay and hnsw_exercised(replay)),
                "ann_recall_attribution": False,
                "is_second_execution_in_same_read_snapshot": replay_enabled,
                "reason": "enabled_by_test_option"
                if replay_enabled
                else "disabled_by_test_option_actual_matched"
                if attribution["status"] == "same_execution_matched"
                else "disabled_by_test_option_capture_unattributed",
            },
            "settings": settings(session),
        }
        if is_probe:
            probes.append(item)
        else:
            attempt = scan_evidence["attempts"][len(executions)]
            assert attempt["strategy"] == actual_strategy
            item.update(attempt)
            executions.append(item)
    assert len(executions) == len(scan_evidence["attempts"])
    assert len(probes) == (1 if strategy == "iterative" else 0)
    final = executions[-1]
    return rows, {
        "strategy": scan_evidence["executed_strategy"],
        "requested_strategy": strategy,
        "strategy_elapsed_ms": strategy_elapsed_ms,
        "strategy_elapsed_scope": {
            "clock": "perf_counter",
            "includes": ["production_semantic_rows", "observer_SET_callbacks"],
            "excludes": [
                "observer_setup", "collect", "log_parsing", "independent_replay",
                "prepared_statement_counts",
            ],
            "cross_replay_mode_causal_comparison": False,
        },
        "sql_sha256": final["sql_sha256"],
        "plan": final["plan"],
        "hnsw_exercised": final["strategy"] == "iterative" and final["hnsw_exercised"],
        "any_stage_hnsw_exercised": any(
            item["strategy"] == "iterative" and item["hnsw_exercised"] for item in executions
        ),
        "executions": executions,
        "probe_executions": probes,
        "actual_plan_capture": attribution,
        "prepared_statement_counts": prepared_counts,
        "scan_evidence": scan_evidence,
        "settings": settings(session),
        "source_agreement_is_from_original_select": True,
        "replay_plan_does_not_attribute_original_rows": True,
    }


def _relation_bytes(session):
    return {
        name: session.scalar(
            text("SELECT pg_total_relation_size(CAST(:name AS regclass))"), {"name": name}
        )
        for name in RELATIONS
    }


def _scoped_payload_bytes(session, tenant):
    # Aggregate on the server: neither vector literals nor bodies leave in this read.
    return {
        name: session.scalar(
            text(
                f"SELECT coalesce(sum(pg_column_size(t)),0)::bigint FROM public.{name} t "
                "WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
        for name in RELATIONS
        if not name.startswith("ix_")
    }


@dataclass
class AnnFixture:
    source_ids: tuple
    audience_ids: tuple
    profile_version: UUID | None = None
    profile_id: UUID | None = None
    receipts: list = field(default_factory=list)
    projection: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=lambda: {"status": "not_attempted"})

    @property
    def public_ids(self):
        return set(self.source_ids[:32])

    @property
    def shared_ids(self):
        return set(self.source_ids[32:64])

    @property
    def revoked_ids(self):
        return set(self.source_ids[32:48])


def embedding_fingerprint(setup, fixture):
    with Session(setup.admin) as session:
        return dict(
            session.execute(
                text("""
            SELECT count(*) AS rows,
              md5(coalesce(string_agg(md5(
                chunk_id::text || ':' || chunk_hash || ':' || vector::text),
                '' ORDER BY chunk_id), '')) AS bound_vector_md5
            FROM enterprise_chunk_embeddings
            WHERE tenant_id=:tenant AND profile_version_id=:profile
        """),
                {"tenant": setup.tenant, "profile": fixture.profile_version},
            )
            .mappings()
            .one()
        )


def withdraw_audience(setup, fixture):
    # Exact own synthetic rows only; no chunk/vector rebuild or source revision edit.
    with Session(setup.admin) as session, session.begin():
        rows = list(
            session.scalars(
                select(ObjectAudience).where(
                    ObjectAudience.id.in_(fixture.audience_ids[:16]),
                    ObjectAudience.tenant_id == setup.tenant,
                    ObjectAudience.principal_id == setup.peer,
                    ObjectAudience.subject_id.in_(fixture.revoked_ids),
                )
            )
        )
        assert len(rows) == 16
        for row in rows:
            session.delete(row)


def _populate(setup, fixture, vector_count):
    with Session(setup.admin) as session, session.begin():
        assert (
            session.scalar(
                select(func.count())
                .select_from(SearchChunk)
                .where(
                    SearchChunk.tenant_id == setup.tenant,
                )
            )
            == 0
        ), "Fixture requires a fresh tenant; never replace existing derived data"
        fixture.projection["relation_bytes_before"] = _relation_bytes(session)
        for number, identity in enumerate(fixture.source_ids):
            body = source_body(number)
            session.add(
                Artifact(
                    id=identity,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    product_id=None,
                    owner_id=setup.human,
                    title=f"Synthetic ANN mechanism {number:04d}",
                    source_label="Synthetic database mechanism fixture; not embedding quality",
                    content=body,
                    content_hash=hashlib.sha256(body.encode()).hexdigest(),
                    visibility="category"
                    if number < 32
                    else "audience"
                    if number < 64
                    else "private",
                    revision=1,
                    status="active",
                )
            )
        session.flush()
        for identity, audience in zip(fixture.source_ids[32:64], fixture.audience_ids, strict=True):
            session.add(
                ObjectAudience(
                    id=audience,
                    tenant_id=setup.tenant,
                    category_id=setup.category,
                    object_type="artifact_versions",
                    subject_id=identity,
                    owner_id=setup.human,
                    principal_id=setup.peer,
                )
            )
    # Every persisted chunk is generated by production project under ordinary owner RLS.
    for number, identity in enumerate(fixture.source_ids):
        with tenant_session(
            setup.engine, setup.tenant, actor_id=setup.human, category_id=setup.category
        ) as session:
            assert session.scalar(text("SELECT current_user")) == "pdos_next_app"
            output = project(session, setup.ctx, "artifact", identity)
            assert output == {"status": "ready", "changed": True, "chunks": CHUNKS_PER_SOURCE}
            rows = list(
                session.scalars(
                    select(SearchChunk)
                    .where(
                        SearchChunk.tenant_id == setup.tenant,
                        SearchChunk.source_type == "artifact",
                        SearchChunk.source_id == identity,
                    )
                    .order_by(SearchChunk.ordinal)
                )
            )
            expected = list(chunks(source_body(number)))
            assert [(row.text, row.locator) for row in rows] == expected
            assert all(
                row.chunk_hash == hashlib.sha256(row.text.encode()).hexdigest() for row in rows
            )
    numbers = {identity: number for number, identity in enumerate(fixture.source_ids)}
    with Session(setup.admin) as session, session.begin():
        rows = session.execute(
            select(
                SearchChunk.id,
                SearchChunk.chunk_hash,
                SearchChunk.source_id,
                SearchChunk.ordinal,
            )
            .where(SearchChunk.tenant_id == setup.tenant)
            .order_by(
                SearchChunk.source_id,
                SearchChunk.ordinal,
            )
        ).all()
        assert len(rows) == vector_count
        for start in range(0, len(rows), 128):
            session.execute(
                insert(ChunkEmbedding),
                [
                    {
                        "tenant_id": setup.tenant,
                        "category_id": setup.category,
                        "chunk_id": row.id,
                        "chunk_hash": row.chunk_hash,
                        "profile_version_id": fixture.profile_version,
                        "dimensions": DIMENSIONS,
                        "vector": synthetic_vector(numbers[row.source_id], row.ordinal),
                        "norm": 1.0,
                    }
                    for row in rows[start : start + 128]
                ],
            )
        # Fresh statistics are part of a natural planner observation; no cost/GUC tuning.
        for table in (
            "artifact_versions",
            "object_audiences",
            "enterprise_search_sources",
            "enterprise_search_chunks",
            "enterprise_chunk_embeddings",
        ):
            session.execute(text(f"ANALYZE public.{table}"))
        fixture.projection.update(
            {
                "chunks": vector_count,
                "sources": len(fixture.source_ids),
                "all_chunk_text_locator_hashes_match_production_projector": True,
                "relation_bytes_after": _relation_bytes(session),
                "scoped_row_payload_bytes": _scoped_payload_bytes(session, setup.tenant),
                "source_payload_bytes": sum(
                    len(source_body(number).encode()) for number in numbers.values()
                ),
            }
        )


@contextmanager
def native_ann_fixture(setup, vector_count):
    fixture = AnnFixture(
        tuple(uuid4() for _ in range(vector_count // CHUNKS_PER_SOURCE)),
        tuple(uuid4() for _ in range(32)),
    )
    provider, ports = ports_for(setup)
    command = command_for(setup, dimensions=DIMENSIONS)
    receipt, _ = save_profile(setup, ports, command)
    fixture.profile_version = UUID(receipt["subject_id"])
    fixture.profile_id = UUID(command["payload"]["profile_id"])
    fixture.receipts.append(receipt["id"])
    try:
        _populate(setup, fixture, vector_count)
        assert not provider.calls
        yield fixture
    finally:
        # Native T1 disable invokes existing scoped vector cleanup. Business
        # artifacts/projections and append-only confirmation/audit history remain.
        try:
            disabled = command_for(
                setup,
                profile_id=fixture.profile_id,
                revision=1,
                budget_revision=1,
                enabled=False,
                dimensions=DIMENSIONS,
            )
            stopped, _ = save_profile(setup, ports, disabled)
            fixture.receipts.append(stopped["id"])
            with Session(setup.admin) as session:
                remaining = session.scalar(
                    select(func.count())
                    .select_from(ChunkEmbedding)
                    .where(
                        ChunkEmbedding.tenant_id == setup.tenant,
                        ChunkEmbedding.profile_version_id == fixture.profile_version,
                    )
                )
                fixture.cleanup = {
                    "status": "native_t1_disabled" if remaining == 0 else "vectors_remain",
                    "remaining_profile_vectors": remaining,
                    "retained_artifacts": session.scalar(
                        select(func.count())
                        .select_from(Artifact)
                        .where(
                            Artifact.tenant_id == setup.tenant,
                            Artifact.id.in_(fixture.source_ids),
                        )
                    ),
                    "retained_chunks": session.scalar(
                        select(func.count())
                        .select_from(SearchChunk)
                        .where(
                            SearchChunk.tenant_id == setup.tenant,
                            SearchChunk.source_id.in_(fixture.source_ids),
                        )
                    ),
                    "retained_source_states": session.scalar(
                        select(func.count())
                        .select_from(SearchSource)
                        .where(
                            SearchSource.tenant_id == setup.tenant,
                            SearchSource.source_id.in_(fixture.source_ids),
                        )
                    ),
                    "retained_synthetic_audiences": session.scalar(
                        select(func.count())
                        .select_from(ObjectAudience)
                        .where(
                            ObjectAudience.tenant_id == setup.tenant,
                            ObjectAudience.id.in_(fixture.audience_ids),
                        )
                    ),
                    "relation_bytes_after_disable": _relation_bytes(session),
                    "scoped_row_payload_bytes_after_disable": _scoped_payload_bytes(
                        session,
                        setup.tenant,
                    ),
                    "native_receipt_audit_outbox_preserved": True,
                    "physical_index_pages_not_reclaimed": True,
                    "cross_connection_bulk_transaction_rollback": False,
                }
            assert not provider.calls
        except Exception as error:
            fixture.cleanup = {
                "status": "native_disable_failed",
                "error_type": type(error).__name__,
            }
            raise
