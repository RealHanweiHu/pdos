"""Root offline combination of frozen metadata and exact observed guard SQL.

This tool creates no engine or connection and never executes generated SQL.
"""

# The import order initializes the common registry before staged declarations.
# ruff: noqa: I001

import hashlib
import json
import sys
from datetime import UTC, datetime

from local_environment import ROOT, SERVER
from wave16_check import source_files


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, body):
    with path.open("x") as output:
        json.dump(body, output, indent=2, ensure_ascii=False)
        output.write("\n")


def main():
    report = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
    result_path = report / "root-offline-ddl-preparation-v3.json"
    sql_path = report / "root-unapplied-ddl-plan-v3.json"
    if result_path.exists() or sql_path.exists():
        raise RuntimeError("Preserve original offline preparation")
    public = source_files()
    candidate_path = (
        ROOT.parent
        / "docs/reports/evidence/pdos-next-wave16-20261002/backend-candidate-source-v5.json"
    )
    if public != json.loads(candidate_path.read_text())["files"]:
        raise RuntimeError("Frozen public v5 changed")
    staged = ROOT / "staging/wave17"
    dependencies = {
        name: sha(staged / name)
        for name in (
            "fact_storage_models.py",
            "fact_storage_codec.py",
            "facts.py",
            "anchor.py",
            "paired.py",
            "fact_sql_guards.py",
        )
    }
    sys.path.insert(0, str(staged))
    sys.path.insert(0, str(SERVER))
    # Common initialization first, then the unmounted models in this process only.
    from pdos_next import service  # noqa: F401
    from pdos_next.models import Base, Confirmation
    import fact_sql_guards as guards
    import fact_storage_models  # noqa: F401
    from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import AddConstraint, CreateIndex, CreateTable

    observation = report / "sql-actual-functions-v1.json"
    observed = json.loads(observation.read_text())
    if observed["head"] != "next_0025" or observed["transaction_read_only"] is not True:
        raise RuntimeError("Exact readonly installed head25 observation required")
    plan = guards.build_guard_plan(observed["definitions"])
    names = guards.FACT_TABLES + guards.CURRENT_TABLES
    pending = UniqueConstraint("tenant_id", "id", name="uq_confirmations_tenant_id_id_capa")
    Confirmation.__table__.append_constraint(pending)
    dialect = postgresql.dialect()
    statements = [str(AddConstraint(pending).compile(dialect=dialect))]
    fks = []
    indexes = []
    for name in names:
        table = Base.metadata.tables[name]
        statements.append(str(CreateTable(table).compile(dialect=dialect)))
        for index in sorted(table.indexes, key=lambda value: value.name):
            indexes.append(str(CreateIndex(index).compile(dialect=dialect)))
        for fk in table.constraints:
            if not isinstance(fk, ForeignKeyConstraint):
                continue
            targets = tuple(v.column for v in fk.elements)
            parent = targets[0].table
            if any(v.table is not parent for v in targets):
                raise RuntimeError("Foreign key crosses multiple parent tables")
            columns = frozenset(v.name for v in targets)
            unique = any(
                isinstance(c, (UniqueConstraint, PrimaryKeyConstraint))
                and frozenset(v.name for v in c.columns) == columns
                for c in parent.constraints
            ) or any(
                i.unique and frozenset(v.name for v in i.columns) == columns for i in parent.indexes
            )
            if not unique:
                raise RuntimeError(f"Unmatched exact unique FK parent: {name}->{parent.name}")
            types_match = all(
                v.parent.type.compile(dialect=dialect) == v.column.type.compile(dialect=dialect)
                for v in fk.elements
            )
            if not types_match:
                raise RuntimeError(f"Foreign key column type mismatch: {name}->{parent.name}")
            fks.append(
                {
                    "table": name,
                    "columns": [v.parent.name for v in fk.elements],
                    "parent": parent.name,
                    "parent_columns": [v.name for v in targets],
                    "deferrable": fk.deferrable,
                    "initially": fk.initially,
                    "unique_parent_resolved": True,
                    "types_match": True,
                }
            )
    body = {
        "applied": False,
        "parent_unique_and_tables": statements,
        "model_indexes_after_tables": indexes,
        "guard_preflight_after_tables": plan.preflight,
        "replace_functions": plan.replace_functions,
        "new_functions": plan.new_functions,
        "new_triggers": plan.new_triggers,
        "permissions": plan.permissions,
        "rollback_preflight_before_any_changes": plan.rollback_preflight,
        "rollback_guards": plan.rollback_guards,
        "restore_actual_old_functions": plan.restore_functions,
        "lifecycle_registration_required": plan.lifecycle_tables,
    }
    write_new(sql_path, body)
    stable_public = source_files() == public
    stable_staged = dependencies == {name: sha(staged / name) for name in dependencies}
    write_new(
        result_path,
        {
            "observed_at": datetime.now(UTC).isoformat(),
            "status": "PASS" if stable_public and stable_staged else "FAILED_SOURCE_CHANGED",
            "scope": "Offline five-table FK/unique/type resolution and PostgreSQL DDL compilation",
            "public_candidate_sha256": sha(candidate_path),
            "public_source_stable": stable_public,
            "staged_dependencies_sha256": dependencies,
            "staged_source_stable": stable_staged,
            "actual_readonly_function_observation_sha256": sha(observation),
            "unapplied_plan_sha256": sha(sql_path),
            "tables": names,
            "ephemeral_confirmation_unique": pending.name,
            "foreign_keys": fks,
            "indexes": indexes,
            "database_connections": 0,
            "sql_executions": 0,
            "public_registration": False,
            "migration_number_assigned": False,
            "remaining": [
                "Reobserve actual head and functions inside the eventual migration boundary",
                "Public metadata and lifecycle registration, real RLS and atom validation",
                "Real original bytes, seven live owners, consumption hook and public consumers",
            ],
        },
    )
    print("Offline preparation PASS", len(names), "tables", len(fks), "resolved foreign keys")
    if not stable_public or not stable_staged:
        raise RuntimeError("Preparation source changed")


if __name__ == "__main__":
    main()
