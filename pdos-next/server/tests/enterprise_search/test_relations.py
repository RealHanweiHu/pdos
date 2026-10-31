"""Pure query contracts for shared RLS scans and exact registered edge identity."""

from uuid import uuid4

from sqlalchemy import literal, select, union_all
from sqlalchemy.dialects import postgresql

from pdos_next.enterprise_search.readable_sources import readable
from pdos_next.enterprise_search.relations import KINDS, QUALITY, edges, graph_for
from pdos_next.enterprise_search.sources import catalog, identity_keys


def compiled(graph):
    return str(
        select(graph).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def seeds(kinds):
    return {(kind, uuid4()) for kind in kinds}


def test_bidirectional_graph_reads_each_native_rls_table_once_under_bound_tenant():
    sql = compiled(edges(set(KINDS), seeds(KINDS)))
    for table in (
        "quality_issue_versions",
        "quality_current_issues",
        "change_request_versions",
        "builds",
        "build_starts",
        "actual_configurations",
        "build_lots",
        "supply_snapshots",
        "verification_run_versions",
        "test_result_actions",
    ):
        assert sql.count(f"shared_enterprise_{table} AS MATERIALIZED") == 1
        assert sql.count(f"FROM {table} \n") == 1
        assert (
            f"WHERE {table}.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)" in sql
        )


def test_change_links_preserve_fixed_revision_scope_and_capa_key_in_each_direction():
    graph = edges(set(QUALITY), seeds(QUALITY))
    sql = compiled(graph)
    q, c = "shared_enterprise_quality_issue_versions", "shared_enterprise_change_request_versions"
    for field in ("tenant_id", "category_id", "product_id", "project_id"):
        assert sql.count(f"{q}.{field} = {c}.{field}") == 4
    assert sql.count(f"{q}.revision = CAST(") == 4
    assert sql.count(f"{q}.issue_id = CAST(") == 4
    assert sql.count("registered_change_refs_capa.value ->> 'key'") == 4
    branches = {row.selected_columns.relation.element.value: row for row in graph.element.selects}
    assert set(branches) == {
        "issue_capa",
        "capa_issue",
        "change_issue",
        "issue_change",
        "change_capa",
        "capa_change",
        "merged_into",
        "merged_from",
    }
    # Registered logical IDs/revisions resolve to native version row IDs. The
    # reverse edges retain those same version IDs, not an arbitrary current row.
    assert branches["change_issue"].selected_columns.target_id.element.name == "id"
    assert branches["issue_change"].selected_columns.origin_id.element.name == "id"
    assert branches["merged_into"].selected_columns.target_id.element.name == "issue_version_id"
    assert branches["merged_from"].selected_columns.origin_id.element.name == "issue_version_id"


def test_build_parent_links_retain_each_scope_join_and_artifact_is_never_a_seed_kind():
    potential = select(
        literal("build").label("source_type"),
        literal(uuid4()).label("source_id"),
    ).cte("indexed_potential_sources")
    sql = compiled(graph_for([*KINDS, "artifact"], potential))
    for table in (
        "build_starts",
        "actual_configurations",
        "build_lots",
        "supply_snapshots",
        "verification_run_versions",
        "test_result_actions",
    ):
        parent, child = "shared_enterprise_builds", "shared_enterprise_" + table
        for field in ("tenant_id", "product_id", "project_id"):
            assert sql.count(f"{parent}.{field} = {child}.{field}") == 2
        assert sql.count(f"{parent}.id = {child}.build_id") == 2
    assert "FROM indexed_potential_sources" in sql
    assert "'artifact' AS origin_kind" not in sql
    assert graph_for(["artifact", "knowledge"], potential) is None


def test_catalog_and_graph_share_one_live_rls_source_across_family_combinations():
    available = [*KINDS, "external_wait"]
    sources = catalog(available)
    graph = graph_for(available, seeds(KINDS))
    # Catalog and graph are built independently. Repeated tables must resolve
    # to the same CTE objects, rather than unrelated same-named copies.
    query = union_all(
        select(sources.c.source_id),
        select(graph.c.target_id),
    )
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for table in (
        "quality_issue_versions",
        "quality_current_issues",
        "change_request_versions",
        "change_request_currents",
        "external_wait_versions",
        "external_wait_currents",
        "supply_snapshots",
        "supply_current_snapshots",
        "builds",
        "build_starts",
        "actual_configurations",
        "build_lots",
        "verification_run_versions",
        "verification_current_runs",
        "test_result_actions",
    ):
        assert sql.count(f"shared_enterprise_{table} AS MATERIALIZED") == 1
        assert sql.count(f"FROM {table} \n") == 1
        assert (
            f"WHERE {table}.tenant_id = CAST(nullif(current_setting('pdos.tenant_id', true)" in sql
        )
    # Sharing an alias cannot discard fields that the authoritative projector
    # needs for registered facts, read dependencies or exact current pointers.
    assert "'execution_scope'" in sql
    assert "shared_enterprise_build_starts.execution_scope" in sql
    assert "shared_enterprise_test_result_actions.next_run_version_id" in sql
    assert "shared_enterprise_verification_run_versions.build_revision" in sql


def test_shared_sql_alias_never_binds_a_principal_and_exact_identity_keeps_table_indexes():
    from pdos_next.domain.quality_execution.models import QualityIssueVersion

    first = readable(QualityIssueVersion)
    assert readable(QualityIssueVersion) is first
    sql = compiled(first)
    assert "current_setting('pdos.tenant_id', true)" in sql
    assert "pdos.actor_id" not in sql and "pdos.requester_id" not in sql
    identity = uuid4()
    query = identity_keys([*KINDS, "external_wait"], identity)
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "shared_enterprise_" not in sql and " AS MATERIALIZED" not in sql
    assert str(identity) in sql
    assert "quality_issue_versions.issue_id =" in sql
    assert "build_starts.build_id =" in sql
    assert "test_result_actions.run_id =" in sql


def test_cached_authority_statement_binds_source_keys_at_each_execution():
    from pdos_next.enterprise_search.assistant_sources import _source_query

    query = _source_query(("artifact", "issue"), False)
    assert query is _source_query(("artifact", "issue"), False)
    assert query.compile().params["enterprise_source_keys"] is None
    assert _source_query(("artifact", "issue"), True) is not query
    assert _source_query(("artifact",), False) is not query
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "current_setting" in sql
