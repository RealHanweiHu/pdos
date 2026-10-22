"""Root actual PostgreSQL DDL rehearsal; the enclosing transaction rolls back.

No migration number, public registration or business fact is committed. This
checks actual table/constraint/function/trigger installation and empty-target
downgrade, never positive publication or deferred atom correctness.
"""

# Common imports initialize the actual 106-table baseline metadata.
# ruff: noqa: I001
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from local_environment import ROOT, read_state, verified
from wave16_check import source_files
from wave16_closeout import private_json
from wave16_migrate import history
from pdos_next.database import engine_for
from sqlalchemy import text
from sqlalchemy.engine import make_url

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
PLAN_SHA = "a5c1426f3d136d2fcd122d0cfed529dee3babeb120b0be5633a706ae4f680f80"
NAMES = (
    "capa_verification_rule_facts",
    "capa_observation_facts",
    "capa_named_verification_reviews",
    "capa_current_verification_rules",
    "capa_current_observations",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def catalog(connection):
    queries = {
        "tables": (
            "SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='public"
            "' ORDER BY tablename"
        ),
        "columns": (
            "SELECT table_name,column_name,data_type,is_nullable,column_default F"
            "ROM information_schema.columns WHERE table_schema='public' ORDER BY "
            "table_name,ordinal_position"
        ),
        "constraints": (
            "SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.o"
            "id) FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid WHERE t"
            ".relnamespace='public'::regnamespace ORDER BY 1,2"
        ),
        "functions": (
            "SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid),p.proacl:"
            ":text FROM pg_proc p WHERE p.pronamespace='public'::regnamespace ORD"
            "ER BY 1"
        ),
        "triggers": (
            "SELECT t.tgrelid::regclass::text,t.tgname,pg_get_triggerdef(t.oid) F"
            "ROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnames"
            "pace='public'::regnamespace AND NOT t.tgisinternal ORDER BY 1,2"
        ),
        "policies": (
            "SELECT tablename,policyname,roles::text,cmd,qual,with_check FROM pg_"
            "policies WHERE schemaname='public' ORDER BY 1,2"
        ),
        "permissions": (
            "SELECT table_name,grantee,privilege_type,is_grantable FROM informati"
            "on_schema.role_table_grants WHERE table_schema='public' ORDER BY 1,2"
            ",3,4"
        ),
        "column_permissions": (
            "SELECT table_name,column_name,grantee,privilege_type,is_grantable FR"
            "OM information_schema.column_privileges WHERE table_schema='public' "
            "ORDER BY 1,2,3,4,5"
        ),
    }
    return {
        name: hashlib.sha256(
            json.dumps([list(r) for r in connection.execute(text(query))], default=str).encode()
        ).hexdigest()
        for name, query in queries.items()
    }


def helper_calls(connection):
    """Direct SQL helpers on existing exact row inputs; no publication/proof."""
    from copy import deepcopy

    ids = private_json(ROOT / ".local/wave16-saved-ids.json")
    seed = private_json(ROOT / ".local/wave15-seed.json")
    row = connection.scalar(
        text(
            "SELECT to_jsonb(v) FROM quality_issue_versions v WHERE id=CAST(:id AS uuid) "
            "AND tenant_id=CAST(:tenant AS uuid) AND product_id=CAST(:product AS uuid)"
        ),
        {"id": ids["complete_v6"], "tenant": seed["tenant_id"], "product": seed["product_id"]},
    )
    if row is None or row["owner_id"] != seed["actor_id"]:
        raise RuntimeError("Existing exact private completed origin required")
    natures = {f["nature"] for f in row["issue_snapshot"]["failures"]}
    if len(natures) != 1:
        raise RuntimeError("Actual stored original failure nature differs")
    nature = next(iter(natures))
    reads = row["required_source_read_set"]
    raw = {
        "ref": {
            "id": row["id"],
            "revision": row["revision"],
            "snapshot_sha256": row["snapshot_sha256"],
        },
        "scope": {k: row[k] for k in ("tenant_id", "product_id", "project_id")},
        **{
            k: row[k]
            for k in (
                "issue_id",
                "purpose",
                "owner_id",
                "visibility",
                "writer_id",
                "operation",
                "created_at",
                "input_snapshot",
                "authority_snapshot",
                "policy_snapshot",
            )
        },
        "nature": nature,
        "issue": row["issue_snapshot"],
        "persisted_source_basis": row["source_basis"],
    }
    # The SQL origin helper deliberately validates original-row declarations;
    # this partial container is not a StableCapaAnchor or a source qualification.
    anchor = {"origin": raw, "origin_required_source_read_set": reads}
    common = {
        "tid": row["tenant_id"],
        "pid": row["product_id"],
        "sources": json.dumps(row["sources"]),
        "reads": json.dumps(reads),
        "basis": json.dumps(row["source_basis"]["artifact_sources"]),
        "audience": row["visibility"],
        "owner": row["owner_id"],
    }
    source_sql = text(
        "SELECT assert_capa_fact_source_closure(CAST(:tid AS uuid),CAST(:pid AS uuid),"
        "CAST(:sources AS jsonb),CAST(:reads AS jsonb),CAST(:basis AS jsonb),"
        ":audience,CAST(:owner AS uuid))"
    )
    connection.execute(source_sql, common)
    origin_sql = text(
        "SELECT assert_capa_fact_origin(CAST(:tid AS uuid),CAST(:pid AS uuid),"
        "CAST(:project AS uuid),"
        "CAST(:issue AS uuid),CAST(:capa AS uuid),CAST(:origin AS uuid),:revision,:purpose,:nature,"
        "CAST(:anchor AS jsonb),CAST(:reads AS jsonb),:audience,CAST(:actor AS uuid))"
    )
    scoped = {
        "tid": row["tenant_id"],
        "pid": row["product_id"],
        "project": row["project_id"],
        "issue": row["issue_id"],
        "capa": row["issue_snapshot"]["capa"]["id"],
        "origin": row["id"],
        "revision": row["revision"],
        "purpose": row["purpose"],
        "nature": nature,
        "anchor": json.dumps(anchor),
        "reads": json.dumps(reads),
        "audience": row["visibility"],
        "actor": seed["actor_id"],
    }
    connection.execute(origin_sql, scoped)
    checks = [
        "Actual source helper resolves configured PL/pgSQL aliases and exact stored closure",
        "Actual origin helper binds complete immutable row, actual purpose and private scope",
    ]
    bad_source = {
        **common,
        "reads": json.dumps([*reads, reads[0]]),
        "basis": json.dumps(
            [*row["source_basis"]["artifact_sources"], row["source_basis"]["artifact_sources"][0]]
        ),
    }
    bad_anchor = deepcopy(anchor)
    bad_anchor["origin"]["purpose"] = (
        "Different target and anchor purpose cannot change actual origin"
    )
    bad_purpose = {
        **scoped,
        "purpose": bad_anchor["origin"]["purpose"],
        "anchor": json.dumps(bad_anchor),
    }
    for name, statement, arguments in (
        ("Duplicate complete source identities rejected", source_sql, bad_source),
        ("Anchor and target purpose changed together still rejected", origin_sql, bad_purpose),
    ):
        savepoint = connection.begin_nested()
        rejected = False
        try:
            connection.execute(statement, arguments)
        except Exception as failure:
            if getattr(getattr(failure, "orig", None), "sqlstate", None) != "P0001":
                raise
            rejected = True
        finally:
            savepoint.rollback()
        if not rejected:
            raise RuntimeError("Direct SQL helper accepted a mutated retained declaration")
        checks.append(name)
    return {
        "checks": checks,
        "actual_retained_source_count": len(reads),
        "business_rows_inserted": 0,
        "not_actual_candidate_publication_or_qualification": True,
    }


def index_boundary_calls(connection):
    """Actual cloned-index probes; no published fact constraints or triggers."""
    from uuid import uuid4

    from sqlalchemy import DateTime, Integer, MetaData, String, Table, Text, UUID
    from sqlalchemy.dialects.postgresql import JSONB

    purpose = "".join(chr(0x10000 + n) for n in range(2000))
    issuer = "".join(chr(0x11000 + n) for n in range(100))
    external = "".join(chr(0x12000 + n) for n in range(200))
    result = []
    for index, name in enumerate(NAMES):
        probe = f"wave17_index_probe_{index}"
        connection.exec_driver_sql(
            f'CREATE TEMP TABLE "{probe}" (LIKE "{name}" INCLUDING INDEXES) ON COMMIT DROP'
        )
        schema = connection.scalar(
            text("SELECT nspname FROM pg_namespace WHERE oid=pg_my_temp_schema()")
        )
        table = Table(probe, MetaData(), autoload_with=connection, schema=schema)
        values = {}
        for column in table.columns:
            if column.nullable:
                values[column.name] = None
            elif isinstance(column.type, UUID):
                values[column.name] = uuid4()
            elif isinstance(column.type, Integer):
                values[column.name] = 1
            elif isinstance(column.type, DateTime):
                values[column.name] = datetime.now(UTC)
            elif isinstance(column.type, JSONB):
                values[column.name] = {}
            elif isinstance(column.type, (String, Text)):
                values[column.name] = {
                    "purpose": purpose,
                    "issuer_key": issuer,
                    "issuer_version": issuer,
                    "external_id": external,
                    "visibility": "private",
                    "nature": "synthetic",
                    "tier": "host_import",
                    "status": "published",
                    "fact_kind": "rule",
                    "operation": "quality.capa.verification.rule.import",
                }.get(column.name, "1" * 64 if column.name.endswith("sha256") else "x")
            else:
                raise RuntimeError("Unexpected probe column type")
        connection.execute(table.insert().values(**values))
        stored = connection.execute(table.select()).mappings().one()
        if stored["purpose"] != purpose:
            raise RuntimeError("Long complete purpose was truncated")
        checked = {
            "table": name,
            "maximum_utf8_purpose_bytes": len(purpose.encode()),
            "actual_cloned_indexes_accept_maximum_values": True,
            "stored_complete_purpose_preserved": True,
        }
        if "issuer_key" in table.c:
            if stored["issuer_key"] != issuer or stored["issuer_version"] != issuer:
                raise RuntimeError("Exact trusted issuer was truncated")
            savepoint = connection.begin_nested()
            rejected = False
            try:
                connection.execute(
                    table.insert().values(**{**values, "id": uuid4(), "issuer_key": issuer + "x"})
                )
            except Exception as failure:
                if getattr(getattr(failure, "orig", None), "sqlstate", None) != "22001":
                    raise
                rejected = True
            finally:
                savepoint.rollback()
            if not rejected:
                raise RuntimeError("Actual issuer column silently accepted the 101st character")
            checked["issuer_100_max_unicode_bytes"] = len(issuer.encode())
            checked["issuer_101_characters_rejected_with_22001"] = True
        result.append(checked)
    return {
        "probes": result,
        "temporary_non_business_rows_inserted": len(result),
        "published_fact_rows_inserted": 0,
        "no_publication_or_qualification_claim": True,
        "scope": (
            "LIKE INCLUDING INDEXES clones; NOT NULL/type/index checks only, "
            "no source/FK/atom/Current/RLS proof"
        ),
    }


def main():
    output = REPORT / "root-actual-ddl-rollback-v3.json"
    if output.exists():
        raise RuntimeError("Preserve original actual DDL observations")
    state = private_json(ROOT / ".local/runtime.json")
    if state != read_state() or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
        raise RuntimeError("Exact existing container/marker required")
    for field in ("app_url", "auth_url", "admin_url"):
        url = make_url(state[field])
        if url.host != "127.0.0.1" or url.port != 62513 or url.database != "pdos_test":
            raise RuntimeError("Unexpected independent explicit role target")
    plan_path = REPORT / "root-unapplied-ddl-plan-v3.json"
    if sha(plan_path) != PLAN_SHA:
        raise RuntimeError("Frozen unapplied plan changed")
    plan = json.loads(plan_path.read_text())
    observed = json.loads((REPORT / "sql-actual-functions-v1.json").read_text())
    recheck_path = REPORT.parent / "pdos-next-wave16-20261002/scope-recheck-v5-result.json"
    recheck = json.loads(recheck_path.read_text())
    if recheck["exit_code"] != 0 or recheck["source_stable"] is not True:
        raise RuntimeError("Public recheck must finish successfully before DDL rehearsal")
    public = source_files()
    manifest_path = REPORT.parent / "pdos-next-wave16-20261002/backend-candidate-source-v5.json"
    if public != json.loads(manifest_path.read_text())["files"]:
        raise RuntimeError("Frozen public v5 changed")
    state = verified(state)
    engine = engine_for(state["admin_url"])
    result = {
        "status": "FAILED",
        "observed_at": datetime.now(UTC).isoformat(),
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "scope": "Actual DDL install/empty downgrade in one rolled-back transaction",
        "plan_sha256": PLAN_SHA,
        "tool_sha256": sha(__file__),
        "public_candidate_sha256": sha(manifest_path),
        "head": "next_0025",
        "public_registration": False,
        "migration_number_assigned": False,
        "business_fact_writes": 0,
        "model_calls": 0,
        "transaction_end": "rollback",
        "completed_steps": [],
        "remaining": [
            "Positive/deferred reciprocal atom and proof-expiry transaction checks",
            "Actual RLS cross-tenant/append-only/Current positive-negative cases",
            "Public metadata/lifecycle registration and numbered migration roundtrip",
            "Live candidate consumer and seven owners, separate effectiveness/close T2",
        ],
    }
    started = time.monotonic()
    baseline = before_rows = names = None
    try:
        with engine.connect() as c:
            tx = c.begin()
            try:
                c.exec_driver_sql("SET LOCAL lock_timeout='10s'")
                c.exec_driver_sql("SET LOCAL statement_timeout='120s'")
                if c.scalar(text("SELECT version_num FROM alembic_version")) != "next_0025":
                    raise RuntimeError("Actual installed head changed")
                for signature, definition in observed["definitions"].items():
                    current = c.scalar(
                        text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
                        {"signature": signature},
                    )
                    if current != definition:
                        raise RuntimeError("Exact actual six-function baseline changed")
                names = (
                    c.execute(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablen"
                            "ame NOT IN ('alembic_version','environment_guard') ORDER BY tablenam"
                            "e"
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(names) != 106 or set(NAMES) & set(names):
                    raise RuntimeError("Unexpected actual baseline/new tables already present")
                baseline = catalog(c)
                before_rows = history(c, names)
                result["baseline_catalog_sha256"] = baseline
                result["baseline_retained_rows_sha256"] = before_rows
                # Diagnose the old driver-only error with a harmless literal.
                # The bound SQLAlchemy compiler properly escapes %ROWTYPE in
                # unchanged PL/pgSQL statements; no guard is relaxed.
                savepoint = c.begin_nested()
                try:
                    c.exec_driver_sql("SELECT 'diagnostic%ROWTYPE'")
                    result["driver_percent_reproduction"] = {"reproduced": False}
                except Exception as failure:
                    original = getattr(failure, "orig", None)
                    result["driver_percent_reproduction"] = {
                        "reproduced": True,
                        "type": type(failure).__name__,
                        "sqlstate": getattr(original, "sqlstate", None),
                        "safe_dummy_error": str(original),
                    }
                finally:
                    savepoint.rollback()
                for key in (
                    "parent_unique_and_tables",
                    "model_indexes_after_tables",
                    "guard_preflight_after_tables",
                    "replace_functions",
                    "new_functions",
                    "new_triggers",
                    "permissions",
                ):
                    for index, statement in enumerate(plan[key]):
                        result["current_step"] = {"group": key, "index": index}
                        c.execute(text(statement))
                    result["completed_steps"].append({"group": key, "statements": len(plan[key])})
                rows = c.execute(
                    text(
                        "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_clas"
                        "s c WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(:n"
                        "ames) ORDER BY c.relname"
                    ),
                    {"names": list(NAMES)},
                ).all()
                if len(rows) != 5 or not all(r[1] and r[2] for r in rows):
                    raise RuntimeError("New five-table FORCE RLS catalog mismatch")
                privileges = {}
                for name in (*NAMES, "capa_verification_evidence"):
                    agent = {
                        privilege: c.scalar(
                            text("SELECT has_table_privilege('pdos_agent',:name,:privilege)"),
                            {"name": name, "privilege": privilege},
                        )
                        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
                    }
                    app = {
                        privilege: c.scalar(
                            text("SELECT has_table_privilege('pdos_next_app',:name,:privilege)"),
                            {"name": name, "privilege": privilege},
                        )
                        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
                    }
                    privileges[name] = {"agent": agent, "app_table": app}
                    if any(agent.values()) or app != {
                        "SELECT": True,
                        "INSERT": True,
                        "UPDATE": False,
                        "DELETE": False,
                    }:
                        raise RuntimeError("Actual narrow table permissions mismatch")
                result["five_tables_force_rls"] = True
                result["actual_role_table_privileges"] = privileges
                result["actual_new_index_names"] = list(
                    c.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE schemaname='public' "
                            "AND tablename=ANY(:names) AND indexname LIKE 'ix_%' ORDER BY indexname"
                        ),
                        {"names": list(NAMES)},
                    ).scalars()
                )
                if len(result["actual_new_index_names"]) != 5:
                    raise RuntimeError("Full five-model tenant indexes missing")
                result["helper_calls"] = helper_calls(c)
                result["index_boundary_calls"] = index_boundary_calls(c)
                result["full_original_rows_preserved_inside_install"] = (
                    history(c, names) == before_rows
                )
                for key in (
                    "rollback_preflight_before_any_changes",
                    "rollback_guards",
                    "restore_actual_old_functions",
                ):
                    for index, statement in enumerate(plan[key]):
                        result["current_step"] = {"group": key, "index": index}
                        c.execute(text(statement))
                    result["completed_steps"].append({"group": key, "statements": len(plan[key])})
                for name in reversed(NAMES):
                    c.exec_driver_sql(f'DROP TABLE "{name}"')
                c.exec_driver_sql(
                    "ALTER TABLE confirmations DROP CONSTRAINT uq_confirmations_tenant_id_id_capa"
                )
                result["catalog_exactly_restored_inside_downgrade"] = catalog(c) == baseline
                result["full_original_rows_preserved_inside_downgrade"] = (
                    history(c, names) == before_rows
                )
                if not all(
                    result[k]
                    for k in (
                        "catalog_exactly_restored_inside_downgrade",
                        "full_original_rows_preserved_inside_install",
                        "full_original_rows_preserved_inside_downgrade",
                    )
                ):
                    raise RuntimeError("Exact baseline preservation failed")
                result["status"] = "PASS"
            finally:
                tx.rollback()
        if baseline is not None:
            with engine.connect() as c:
                c.exec_driver_sql("SET TRANSACTION READ ONLY")
                result["catalog_exactly_restored_after_rollback"] = catalog(c) == baseline
                result["head_unchanged_after_rollback"] = (
                    c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0025"
                )
                result["full_original_rows_preserved_after_rollback"] = (
                    history(c, names) == before_rows
                )
                c.rollback()
                if not all(
                    result[k]
                    for k in (
                        "catalog_exactly_restored_after_rollback",
                        "head_unchanged_after_rollback",
                        "full_original_rows_preserved_after_rollback",
                    )
                ):
                    result["status"] = "FAILED_RETAINED_BASELINE_CHANGED"
    except Exception as failure:
        # SQL statements contain no credentials or private business data; the
        # driver wrapper may contain bound business parameters, so omit its text.
        original = getattr(failure, "orig", None)
        result["error"] = {
            "type": type(failure).__name__,
            "sqlstate": getattr(original, "sqlstate", None),
            "diagnostic": getattr(getattr(original, "diag", None), "message_primary", None),
        }
    finally:
        if baseline is not None and "catalog_exactly_restored_after_rollback" not in result:
            with engine.connect() as c:
                c.exec_driver_sql("SET TRANSACTION READ ONLY")
                result["catalog_exactly_restored_after_rollback"] = catalog(c) == baseline
                result["head_unchanged_after_rollback"] = (
                    c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0025"
                )
                result["full_original_rows_preserved_after_rollback"] = (
                    history(c, names) == before_rows
                )
                c.rollback()
        engine.dispose()
    result["seconds"] = round(time.monotonic() - started, 2)
    result["public_source_stable"] = public == source_files()
    if not result["public_source_stable"]:
        result["status"] = "FAILED_SOURCE_CHANGED"
    with output.open("x") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(result["status"], result.get("current_step"), result.get("error", {}), flush=True)
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
