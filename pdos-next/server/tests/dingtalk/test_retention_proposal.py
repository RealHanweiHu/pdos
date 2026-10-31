"""Static metadata/ACL guard checks, not a claim of executed PostgreSQL behavior."""

import ast
import re
from pathlib import Path

from migrations.candidates.dingtalk_lifecycle import LIFECYCLE_UP_SQL, NATIVE_FUNCTIONS
from pdos_next.dingtalk.models import (
    Application,
    Binding,
    BindingNonce,
    Delivery,
    Message,
    ShareConsent,
)
from pdos_next.lifecycle_access import NON_CONSUMING
from pdos_next.lifecycle_catalog import COVERED_COLUMNS, GUARDED
from sqlalchemy.dialects import postgresql

MODELS = (Application, BindingNonce, Binding, Message, ShareConsent, Delivery)


def test_exact_six_table_inventory_classifies_actual_delivery_copy_as_consuming():
    for model in MODELS:
        assert set(COVERED_COLUMNS[model.__tablename__]) == set(model.__table__.columns.keys())
        assert (model.__tablename__ in NON_CONSUMING) == (model is not Delivery)
    assert Delivery.__tablename__ in GUARDED
    assert "category_id" not in Delivery.__table__.columns
    assert str(Delivery.__table__.c.id.type.compile(dialect=postgresql.dialect())) == "UUID"


def test_trigger_composites_use_actual_metadata_columns_without_body_or_fake_category():
    functions = [s for s in LIFECYCLE_UP_SQL if s.startswith("CREATE FUNCTION")]
    assert len(functions) == 2
    columns = set(Delivery.__table__.columns.keys())
    for sql in functions:
        refs = set(re.findall(r"\b(?:NEW|OLD)\.([a-z_][a-z_0-9]*)", sql))
        assert refs <= columns
        assert not {"payload", "category_id"} & refs
        assert "to_jsonb(NEW)" not in sql and "to_jsonb(OLD)" not in sql
        assert "SET search_path=pg_catalog,public,pg_temp" in sql
        assert "IF TG_OP='UPDATE' THEN" in sql
    clock = functions[0]
    assert clock.index("ORDER BY id FOR UPDATE") < clock.index("FOR model_id IN")
    assert "affected<>cardinality(categories)" in clock


def test_nodes_read_only_fixed_metadata_and_source_links_reuse_one_shared_typed_resolver():
    source = NATIVE_FUNCTIONS["m3_lifecycle_source_links(uuid,uuid,text,jsonb)"]
    nodes = NATIVE_FUNCTIONS["m3_lifecycle_nodes(uuid,uuid,uuid[])"]
    segment = nodes[nodes.index("-- Read exactly the retained metadata") :]
    assert "d.payload" not in segment and "to_jsonb" not in segment
    assert "d.tenant_id=t" in segment and "dependency->>'category_id'=c::text" in segment
    assert "identities IS NULL OR d.id=ANY(identities)" in segment
    segment = source[source.index("-- G private outbound body copies") :]
    assert "assistant_source_lifecycle_links(t,c,container)" in segment
    assert "value->>'category_id'=c::text" in segment
    assert not any(
        "CREATE FUNCTION public.assistant_source_lifecycle_links" in s for s in LIFECYCLE_UP_SQL
    )


def test_no_runtime_gets_owner_membership_body_select_or_internal_function_execution():
    joined = "\n".join(LIFECYCLE_UP_SQL)
    assert "FOR SELECT TO pdos_next_owner" in joined
    assert "GRANT SELECT(id,tenant_id,content_kind,source_dependencies)" in joined
    assert "GRANT SELECT(payload" not in joined and "DISABLE ROW LEVEL SECURITY" not in joined
    assert "NOBYPASSRLS" not in joined  # No new role needed; reuse native ordinary owner.
    assert "TO pdos_next_app" not in joined and "TO pdos_agent" not in joined
    for name in ["dingtalk_lifecycle_reference_clock", "dingtalk_lifecycle_reference_gate"]:
        owner = joined.index(f"ALTER FUNCTION public.{name}() OWNER TO pdos_next_owner")
        grant = joined.index(f"GRANT EXECUTE ON FUNCTION public.{name}() TO pdos_next_owner")
        assert owner < grant
        assert (
            f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC,"
            "pdos_next_app,pdos_agent,pdos_next_auth,pdos_next_dispatch"
            in joined
        )


def test_static_native_owner_policy_path_covers_shared_resolver_readset_tables():
    migrations = Path(__file__).resolve().parents[2] / "migrations"
    tree = ast.parse((migrations / "schema_s0_0001.py").read_text())
    baseline = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "TABLES" for t in n.targets)
    )
    assert {
        "artifact_versions",
        "quality_issue_versions",
        "change_request_versions",
        "supply_snapshots",
        "build_starts",
        "actual_configurations",
        "build_lots",
        "verification_run_versions",
        "test_result_actions",
        "builds",
        "engineering_configurations",
        "process_revisions",
    } <= set(baseline)
    owner = (migrations / "versions/s0_0720_trusted_owner.py").read_text()
    assert "CREATE POLICY owner_internal ON public.{name} TO pdos_next_owner" in owner
    assert '"USING(true) WITH CHECK(true)"' in owner
    assert "Runtime roles must not inherit" in owner
    # The sole resolver source table added later has its own owner policy.
    tree = ast.parse((migrations / "schema_s0_0796.py").read_text())
    statements = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "SCHEMA_SQL" for t in n.targets)
    )
    assert any(
        'CREATE POLICY owner_internal ON public."external_wait_versions" '
        'TO pdos_next_owner USING(true)'
        in s
        for s in statements
    )
