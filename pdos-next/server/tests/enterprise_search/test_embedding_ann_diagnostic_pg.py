"""One live 8192-vector eligibility/cost diagnostic, never an ANN acceptance pass.

Root executes after its other PG work. All plans use ordinary default costs and
seqscan settings. Admin plans isolate RLS effects only; vectors are synthesized,
chunks are projected normally, and native T1 disable always runs on exit.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from pdos_next.database import tenant_session
from pdos_next.enterprise_search.embedding_models import Vector
from pdos_next.enterprise_search.schemas import SearchInput
from tests.enterprise_search.embedding_ann_fixture import (
    HNSW_INDEX,
    native_ann_fixture,
    plan_nodes,
    safe_plan,
    semantic_with_plan,
    settings,
    vector_queries,
)
from tests.enterprise_search.test_eval_v0_contracts_pg import explicit_target

pytestmark = pytest.mark.skipif(
    not explicit_target(), reason="Root must bind all roles to guarded 53502/pdos_test"
)

CATALOG = {
    "index": """
        SELECT c.relname, am.amname, i.indisvalid, i.indisready, i.indislive,
          pg_get_indexdef(i.indexrelid) AS definition,
          pg_get_expr(i.indexprs,i.indrelid) AS expression,
          pg_get_expr(i.indpred,i.indrelid) AS predicate,
          i.indexprs::text AS expression_node, i.indclass::text AS opclass_oids,
          c.reltuples,c.relpages,pg_relation_size(c.oid) AS index_bytes
        FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
        JOIN pg_am am ON am.oid=c.relam
        WHERE i.indexrelid='public.ix_enterprise_embedding_hnsw_384'::regclass
    """,
    "column": """
        SELECT a.attname,a.atttypid AS type_oid,a.atttypmod,
          format_type(a.atttypid,a.atttypmod) AS type_name,a.attnotnull
        FROM pg_attribute a
        WHERE a.attrelid='public.enterprise_chunk_embeddings'::regclass
          AND a.attname IN ('vector','dimensions') ORDER BY a.attname
    """,
    "extension": """
        SELECT e.extversion,n.nspname AS schema FROM pg_extension e
        JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'
    """,
    "functions": """
        SELECT p.oid,p.oid::regprocedure::text AS function,p.provolatile,p.proleakproof,p.procost
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname IN ('vector','cosine_distance') ORDER BY p.oid
    """,
    "cosine_operator_families": """
        SELECT o.oid AS operator_oid,o.oid::regoperator::text AS operator,
          o.oprcode::regprocedure::text AS function,o.oprresult AS result_type_oid,
          o.oprresult::regtype::text AS result_type,a.amoppurpose,
          f.oid AS family_oid,f.opfname AS family,sf.opfname AS sort_family,am.amname
        FROM pg_operator o JOIN pg_amop a ON a.amopopr=o.oid
        JOIN pg_opfamily f ON f.oid=a.amopfamily
        JOIN pg_am am ON am.oid=f.opfmethod
        LEFT JOIN pg_opfamily sf ON sf.oid=a.amopsortfamily
        WHERE o.oid='public.<=>(public.vector,public.vector)'::regoperator
        ORDER BY f.oid
    """,
    "table_statistics": """
        SELECT c.relname,c.reltuples,c.relpages,s.n_live_tup,s.n_dead_tup,
          s.last_analyze::text,s.last_autoanalyze::text
        FROM pg_class c LEFT JOIN pg_stat_all_tables s ON s.relid=c.oid
        WHERE c.oid='public.enterprise_chunk_embeddings'::regclass
    """,
    "rls": """
        SELECT c.relrowsecurity,c.relforcerowsecurity,p.polname,p.polcmd,
          pg_get_expr(p.polqual,p.polrelid) AS policy
        FROM pg_class c LEFT JOIN pg_policy p ON p.polrelid=c.oid
        WHERE c.oid='public.enterprise_chunk_embeddings'::regclass ORDER BY p.polname
    """,
}


def _catalog(session):
    return {
        name: [dict(row) for row in session.execute(text(sql)).mappings()]
        for name, sql in CATALOG.items()
    }


def _prepared(session):
    return [
        dict(row)
        for row in session.execute(
            text("""
        SELECT name,parameter_types::text,generic_plans,custom_plans,
          md5(statement) AS statement_md5
        FROM pg_prepared_statements WHERE statement LIKE '%semantic_source_ranks%'
        ORDER BY name
    """)
        ).mappings()
    ]


def _role(session):
    return dict(
        session.execute(
            text("""
        SELECT current_user AS role,r.rolsuper,r.rolbypassrls,
          current_setting('server_version') AS server_version,
          current_setting('search_path') AS search_path
        FROM pg_roles r WHERE r.rolname=current_user
    """)
        )
        .mappings()
        .one()
    )


def _canonical_plan(session, fixture, setup, query, limit, *, bound_dimensions=False):
    dimension = "CAST(:dimensions AS integer)" if bound_dimensions else "384"
    # Typmod and ORDER BY expression are fixed, matching production/index syntax.
    # Query values remain bound and are never written to the observation.
    sql = f"""SELECT v.chunk_id FROM public.enterprise_chunk_embeddings v
        WHERE v.tenant_id=CAST(:tenant AS uuid)
          AND v.profile_version_id=CAST(:profile AS uuid) AND v.dimensions={dimension}
        ORDER BY CAST(v.vector AS public.vector(384)) <=> CAST(:query AS public.vector(384))
        LIMIT {limit}"""
    parameters = {"tenant": setup.tenant, "profile": fixture.profile_version, "query": query}
    if bound_dimensions:
        parameters["dimensions"] = 384
    raw = session.execute(text("EXPLAIN (COSTS, FORMAT JSON) " + sql), parameters).scalar_one()[0]
    plan = safe_plan(raw)
    return {
        "limit": limit,
        "dimensions_mode": "bound" if bound_dimensions else "literal",
        "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
        "plan": plan,
        "hnsw_planned": any(node.get("Index Name") == HNSW_INDEX for node in plan_nodes(plan)),
        "analyzed": False,
        "ann_acceptance_credit": False,
    }


def test_one_live_fixture_ann_eligibility_rls_partial_dimension_and_cost_diagnostic_pg(
    setup,
    record_property,
):
    output = os.environ.get("PDOS_ANN_AUTHORITY_OUTPUT_DIR")
    path = Path(output) / "ann-diagnostic.json" if output else None
    if path:
        assert path.parent.is_dir(), "Root must precreate the observation directory"
        assert not path.exists(), "Diagnostic observations are append-only"
    observation = {
        "version": "embedding-ann-eligibility-diagnostic/v1",
        "status": "not_finished",
        "ann_acceptance_credit": False,
        "synthetic_vectors": True,
        "vector_count": 8192,
        "dimensions": 384,
        "real_model_calls": 0,
        "real_embedding_calls": 0,
        "planner_costs_modified": False,
        "seqscan_disabled": False,
        "rls_modified": False,
        "comparisons": {},
        "not_scored": ["semantic_relevance", "real_embedding_quality", "native_ann_acceptance"],
    }
    fixture = None
    try:
        with native_ann_fixture(setup, 8192) as fixture:
            observation["scope"] = {
                "tenant_id": str(setup.tenant),
                "category_id": str(setup.category),
                "profile_version_id": str(fixture.profile_version),
            }
            observation["projection"] = fixture.projection
            vector = vector_queries(4)[0]
            query = Vector(384).bind_processor(None)(vector)
            for name, engine in (("app", setup.engine), ("admin_diagnostic_only", setup.admin)):
                with tenant_session(
                    engine,
                    setup.tenant,
                    actor_id=setup.human,
                    category_id=setup.category,
                    read_snapshot=True,
                ) as session:
                    role = _role(session)
                    bypass = role["rolsuper"] or role["rolbypassrls"]
                    assert bool(bypass) == (name == "admin_diagnostic_only")
                    gucs = settings(session)
                    assert gucs["enable_seqscan"] == "on" and gucs["row_security"] == "on"
                    value = {
                        "role": role,
                        "settings": gucs,
                        "driver_prepare_threshold": (
                            session.connection().connection.driver_connection.prepare_threshold
                        ),
                        "canonical_plans": [
                            _canonical_plan(session, fixture, setup, query, limit)
                            for limit in (1, 20, 200)
                        ],
                    }
                    if name == "app":
                        value["canonical_plans"].append(
                            _canonical_plan(
                                session,
                                fixture,
                                setup,
                                query,
                                20,
                                bound_dimensions=True,
                            )
                        )
                        value["prepared_before_production"] = _prepared(session)
                        rows, evidence = semantic_with_plan(
                            session,
                            setup.ctx,
                            SearchInput(
                                query="synthetic database diagnostic",
                                source_types=["artifact"],
                                limit=10,
                            ),
                            fixture.profile_version,
                            vector,
                            "iterative",
                        )
                        value["production_iterative"] = {
                            **evidence,
                            "returned_source_count": len(rows),
                            "ann_acceptance_credit": False,
                        }
                        value["prepared_after_production"] = _prepared(session)
                    else:
                        observation["catalog"] = _catalog(session)
                        observation["live_fixture_vectors"] = session.scalar(
                            text("""
                            SELECT count(*) FROM public.enterprise_chunk_embeddings
                            WHERE tenant_id=:tenant AND profile_version_id=:profile
                              AND dimensions=384
                        """),
                            {"tenant": setup.tenant, "profile": fixture.profile_version},
                        )
                        assert observation["live_fixture_vectors"] == 8192
                    observation["comparisons"][name] = value
        assert fixture.cleanup["status"] == "native_t1_disabled"
        observation["status"] = "diagnostic_completed"
    finally:
        if fixture is not None:
            observation["cleanup"] = fixture.cleanup
            observation["native_t1_receipt_ids"] = fixture.receipts
        if path:
            with path.open("x", encoding="utf-8") as stream:
                json.dump(observation, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
            record_property("ann_eligibility_diagnostic", str(path))
