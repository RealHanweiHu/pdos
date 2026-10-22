"""Freeze the reviewed G0 candidate against a verified, read-only B8 predecessor.

This generator is never imported by a migration. Active revisions consume literal SQL.
The predecessor state is explicit; credentials and business rows are not exported.
"""

import argparse
import re
from pathlib import Path

import local_environment as local
from alembic.config import Config
from alembic.script import ScriptDirectory
from migrations.candidates.m3_preproject import statements
from migrations.schema_s0_0001 import SCHEMA_SQL as BASELINE_SQL
from pdos_next.database import engine_for
from pdos_next.domain.preproject.category_models import TABLES as CATEGORY_TABLES
from pdos_next.domain.preproject.models import TABLES
from sqlalchemy import text


def freeze(state_path):
    target = local.SERVER / "migrations/schema_s0_0729.py"
    if target.exists():
        raise RuntimeError("Do not overwrite frozen migration SQL")
    config = Config(str(local.SERVER / "alembic.ini"))
    config.set_main_option("script_location", str(local.SERVER / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == ["s0_0728"]
    local.STATE = state_path
    current = local.verified(local.read_state())
    engine = engine_for(current["admin_url"])
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION READ ONLY"))
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "s0_0728"
        functions = dict(
            connection.execute(
                text(
                    "SELECT p.proname,pg_get_functiondef(p.oid) FROM pg_proc p "
                    "WHERE p.pronamespace='public'::regnamespace AND p.proname IN "
            "('direct_source_set_visible','protect_object_audience_target',"
            "'protect_fixed_definition')"
                )
            ).all()
        )
        policies = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT tablename,policyname,qual,with_check FROM pg_policies "
                    "WHERE schemaname='public' AND ("
                    "(tablename='object_audiences' AND policyname='audience_assignment') OR "
                    "(tablename='projects' AND policyname='upstream_audience')) ORDER BY 1,2"
                )
            ).mappings()
        ]
        checks = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conrelid='definition_specs'::regclass AND contype='c' "
                    "AND pg_get_constraintdef(oid) LIKE '%value_type%' ORDER BY conname"
                )
            ).mappings()
        ]
    engine.dispose()
    assert len(functions) == 3 and len(policies) == 2 and len(checks) == 2
    baseline_specs = next(s for s in BASELINE_SQL if "CREATE TABLE definition_specs (" in s)
    original_type_check = next(
        line.strip().rstrip(",")
        for line in baseline_specs.splitlines()
        if "CHECK (value_type IN" in line
    )
    # pg_get_constraintdef canonicalizes ARRAY casts on reparsing. Restore the
    # immutable predecessor DDL for this check, so the catalog is also identical.
    for check in checks:
        if check["conname"] == "definition_specs_value_type_check":
            check["definition"] = original_type_check
    sql = statements()
    # Keep B8's single-root audience implementation; M3 only permits a category
    # original to accompany its new model's G0 definition in the same category.
    optimized = functions["direct_source_set_visible"]
    assert optimized.count("a.product_id IS NOT DISTINCT FROM p") == 1
    optimized = optimized.replace(
        "a.product_id IS NOT DISTINCT FROM p", "(a.product_id IS NULL OR a.product_id=p)"
    )
    for index, statement in enumerate(sql):
        sql[index] = (
            re.sub(
                r"CREATE OR REPLACE FUNCTION direct_source_set_visible\(.*?\$\$;",
            lambda _: optimized.rstrip() + ";\n",
                statement,
                count=1,
                flags=re.S,
            )
            .replace("ALTER TABLE confirmations ALTER COLUMN expires_at DROP NOT NULL;", "")
            .replace("SET search_path=public,pg_temp", "SET search_path=pg_catalog,public,pg_temp")
        )
    names = [table.name for table in (*TABLES, *CATEGORY_TABLES)]
    down = []
    for policy, table in re.findall(r"CREATE POLICY (\w+) ON (\w+)", "\n".join(sql)):
        if table not in names:
            down.append(f'DROP POLICY "{policy}" ON "{table}"')
    for policy in policies:
        body = []
        if policy["qual"]:
            body.append("USING (" + policy["qual"] + ")")
        if policy["with_check"]:
            body.append("WITH CHECK (" + policy["with_check"] + ")")
        down.append(
            f'ALTER POLICY "{policy["policyname"]}" ON "{policy["tablename"]}" ' + " ".join(body)
        )
    for table, trigger in (
        ("definition_revisions", "m3_sealed_definition"),
        ("definition_specs", "m3_sealed_spec"),
        ("definition_sources", "m3_sealed_source"),
    ):
        down.append(f'DROP TRIGGER "{trigger}" ON "{table}"')
    down += [
        "ALTER TABLE definition_revisions DROP CONSTRAINT m3_definition_decision_fk",
        "ALTER TABLE projects DROP CONSTRAINT m3_project_decision_fk",
        functions["protect_object_audience_target"],
        functions["direct_source_set_visible"],
        functions["protect_fixed_definition"],
    ]
    # Reverse new FK dependencies without CASCADE; PostgreSQL verifies that the
    # explicit dependency inventory is complete.
    ordered = [
        "product_target_segments",
        "category_knowledge_current",
        "category_knowledge_entries",
    ]
    ordered += [table.name for table in reversed(TABLES)]
    down.extend(f'DROP TABLE "{name}"' for name in ordered)
    function_signatures = []
    for name, arguments in re.findall(r"CREATE FUNCTION (m3_\w+)\(([^)]*)\)", "\n".join(sql)):
        signature = (
            name
            + "("
            + ",".join(arg.strip().split()[-1] for arg in arguments.split(",") if arg.strip())
            + ")"
        )
        function_signatures.append(signature)
    down.extend("DROP FUNCTION " + signature for signature in reversed(function_signatures))
    for table, columns in {
        "definition_revisions": [
            "sealed",
            "source_proposal_id",
            "source_submission_id",
            "source_proposal_revision",
            "g0_decision_id",
        ],
        "definition_specs": [
            "parameter_id",
            "parameter_version",
            "item_status",
            "condition_note",
            "modality",
            "exceptions",
            "applicable_variants",
            "source_refs",
            "origin",
            "writer_id",
            "run_id",
            "confirmed_by",
            "receipt_id",
        ],
        "projects": ["trigger_type", "trigger_id", "g0_decision_id"],
        "products": [
            "target_price",
            "target_price_currency",
            "target_price_basis",
            "target_price_includes_tax",
            "target_price_as_of",
        ],
    }.items():
        down.append(
            f'ALTER TABLE "{table}" ' + ", ".join(f'DROP COLUMN "{column}"' for column in columns)
        )
    down += [
        "ALTER TABLE definition_specs DROP CONSTRAINT m3_spec_value_type, "
        "DROP CONSTRAINT m3_spec_known_shape",
        *(
            f'ALTER TABLE definition_specs ADD CONSTRAINT "{row["conname"]}" {row["definition"]}'
            for row in checks
        ),
        "ALTER TABLE definition_specs ALTER COLUMN key TYPE varchar(80), "
        "ALTER COLUMN parameter TYPE varchar(200), ALTER COLUMN unit TYPE varchar(80)",
        "ALTER TABLE products ALTER COLUMN name TYPE varchar(160)",
        "ALTER TABLE projects ALTER COLUMN name TYPE varchar(160)",
        "ALTER TABLE definition_revisions ALTER COLUMN title TYPE varchar(200)",
    ]
    # Every newly created helper runs with a fixed search path, under the separately
    # provisioned ordinary schema owner. No runtime role acquires owner membership.
    sql.extend(
        "ALTER FUNCTION " + signature + " SET search_path=pg_catalog,public,pg_temp"
        for signature in function_signatures
    )
    target.write_text(
        "# ruff: noqa: E501 -- frozen PostgreSQL definitions\n"
        '"""M3 G0 candidate frozen from B8 s0_0728; no live ORM imports."""\n\n'
        + "TABLES = "
        + repr(tuple(names))
        + "\n\n"
        + "SCHEMA_SQL = "
        + repr(tuple(sql))
        + "\n\n"
        + "DOWNGRADE_SQL = "
        + repr(tuple(down))
        + "\n"
    )
    print(f"Frozen {len(names)} tables, {len(sql)} statements from verified s0_0728")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, type=Path)
    freeze(parser.parse_args().state.resolve())
