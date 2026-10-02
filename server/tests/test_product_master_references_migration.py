"""0409 real PostgreSQL round trip and append-only reference guards.

Prepared only: requires the guarded, explicitly assigned isolated pdos_test fixture.
No trigger bypass, historical row deletion, or fallback database is used here.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, Connection, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError

from app.db.schema import tables
from app.db.url import psycopg_database_url
from tests.migration_fixtures import rollback_migration_operations
from tests.product_master_reference_fixtures import MasterCandidate, seed_master_candidate
from tests.product_master_reference_fixtures import (
    master_reference_database_guard as master_reference_database_guard,
)
from tests.test_test_runs_api import (
    Scope,
)
from tests.test_test_runs_api import (
    client as client,
)
from tests.test_test_runs_api import (
    isolated_test_run_database as isolated_test_run_database,
)


@pytest.fixture
def registered_reference(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[MasterCandidate]:
    scope = Scope(client, isolated_test_run_database)
    try:
        candidate = seed_master_candidate(client, scope, tmp_path, monkeypatch)
        assert candidate.read()["current_definition"] is not None
        candidate.save(candidate.request())
        yield candidate
    finally:
        scope.dispose()


def receipt(c: Connection, candidate: MasterCandidate) -> dict[str, Any]:
    table = tables.product_master_references
    return dict(
        c.execute(
            select(table).where(
                table.c.tenant_id == candidate.scope.tenant_id,
                table.c.product_id == candidate.product_id,
            )
        )
        .mappings()
        .one()
    )


def receipt_bytes(c: Connection, row_id: Any) -> str:
    return str(
        c.execute(
            text(
                "SELECT row_to_json(r)::text FROM cehub_product.product_master_references r "
                "WHERE id=:id"
            ),
            {"id": row_id},
        ).scalar_one()
    )


def append(c: Connection, original: dict[str, Any], **changes: Any) -> dict[str, Any]:
    values = {**original, "id": uuid4(), "request_id": uuid4(), **changes}
    c.execute(tables.product_master_references.insert(), values)
    return values


def rejected_append(c: Connection, original: dict[str, Any], **changes: Any) -> None:
    with pytest.raises(DBAPIError), c.begin_nested():
        append(c, original, **changes)


def test_empty_0409_roundtrip_matches_metadata_guards_and_agent_has_no_write_privileges(
    isolated_test_run_database: str,
) -> None:
    migration = import_module("migrations.versions.0409_product_master_references")
    engine = create_engine(psycopg_database_url(isolated_test_run_database))
    try:
        with rollback_migration_operations(engine) as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM cehub_product.product_master_references")
                ).scalar_one()
                == 0
            )

            def snapshot() -> tuple[Any, ...]:
                columns = inspect(c).get_columns(
                    "product_master_references", schema="cehub_product"
                )
                constraints = list(
                    c.execute(
                        text(
                            "SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conrelid='cehub_product.product_master_references'::regclass "
                            "ORDER BY conname"
                        )
                    )
                )
                guard = c.execute(
                    text(
                        "SELECT pg_get_functiondef('cehub_product.guard_product_master_reference()'"
                        "::regprocedure)"
                    )
                ).scalar_one()
                trigger = c.execute(
                    text(
                        "SELECT tgname,tgtype,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger "
                        "WHERE tgrelid='cehub_product.product_master_references'::regclass "
                        "AND NOT tgisinternal"
                    )
                ).one()
                return (
                    [(v["name"], str(v["type"]), v["nullable"], v["default"]) for v in columns],
                    [tuple(v) for v in constraints],
                    guard,
                    tuple(trigger),
                )

            before = snapshot()
            migration.downgrade()
            assert c.execute(
                text(
                    "SELECT to_regclass('cehub_product.product_master_references'),"
                    "to_regprocedure('cehub_product.guard_product_master_reference()')"
                )
            ).one() == (None, None)
            migration.upgrade()
            assert snapshot() == before
            table = tables.product_master_references
            actual = inspect(c).get_columns(table.name, schema=table.schema)
            assert [(v["name"], v["nullable"]) for v in actual] == [
                (v.name, v.nullable) for v in table.columns
            ]
            assert [v["type"].compile(dialect=c.dialect) for v in actual] == [
                v.type.compile(dialect=c.dialect) for v in table.columns
            ]
            actual_constraints = {v[0]: v[1] for v in before[1]}
            expected_names: set[str] = set()
            for constraint in table.constraints:
                name = c.dialect.identifier_preparer.format_constraint(constraint)
                assert name is not None
                expected_names.add(name.strip('"'))
            assert set(actual_constraints) == expected_names
            for constraint in table.constraints:
                if not isinstance(constraint, CheckConstraint):
                    continue
                c.execute(
                    text(
                        "ALTER TABLE cehub_product.product_master_references "
                        f"ADD CONSTRAINT metadata_check CHECK ({constraint.sqltext})"
                    )
                )
                canonical = c.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid='cehub_product.product_master_references'::regclass "
                        "AND conname='metadata_check'"
                    )
                ).scalar_one()
                c.execute(
                    text(
                        "ALTER TABLE cehub_product.product_master_references "
                        "DROP CONSTRAINT metadata_check"
                    )
                )
                assert canonical == actual_constraints[str(constraint.name)]
            assert c.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='pdos_agent')")
            ).scalar_one(), "Actual pdos_agent role is required; absence is not a passing proof"
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not c.execute(
                    text(
                        "SELECT has_table_privilege('pdos_agent',"
                        "'cehub_product.product_master_references',:privilege)"
                    ),
                    {"privilege": privilege},
                ).scalar_one()
            for privilege in ("INSERT", "UPDATE"):
                assert not c.execute(
                    text(
                        "SELECT has_any_column_privilege('pdos_agent',"
                        "'cehub_product.product_master_references',:privilege)"
                    ),
                    {"privilege": privilege},
                ).scalar_one()
    finally:
        engine.dispose()


def test_empty_reference_roundtrip_preserves_nonempty_published_pm_history_and_shared_rows(
    client: TestClient,
    isolated_test_run_database: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operation-context proof only; not an Alembic CLI upgrade/check proof."""
    scope = Scope(client, isolated_test_run_database)
    try:
        candidate = seed_master_candidate(client, scope, tmp_path, monkeypatch)
        projection = candidate.read()
        assert projection["current_definition"] is not None
        assert projection["items"] == []
        migration = import_module("migrations.versions.0409_product_master_references")
        with rollback_migration_operations(scope.engine) as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM cehub_product.product_master_references")
                ).scalar_one()
                == 0
            )

            def existing_snapshot() -> dict[str, Any]:
                # Include all real, non-system tables, not just the PM objects we seeded.
                # OIDs and internal RI trigger names change when the new table is rebuilt;
                # existing user columns/constraints/indexes/triggers and rows must not.
                existing = """
                    SELECT r.oid,n.nspname,r.relname,r.relkind
                    FROM pg_class r JOIN pg_namespace n ON n.oid=r.relnamespace
                    WHERE r.relkind IN ('r','p')
                    AND n.nspname NOT IN ('pg_catalog','information_schema')
                    AND n.nspname NOT LIKE 'pg_toast%'
                    AND n.nspname NOT LIKE 'pg_temp%'
                    AND NOT (n.nspname='cehub_product'
                        AND r.relname='product_master_references')
                """
                relations = c.execute(
                    text(
                        f"WITH existing AS ({existing}) "
                        "SELECT nspname,relname,relkind FROM existing ORDER BY nspname,relname"
                    )
                ).all()
                rows: dict[str, list[str]] = {}
                preparer = c.dialect.identifier_preparer
                for schema, name, _kind in relations:
                    qualified = f"{preparer.quote_schema(schema)}.{preparer.quote(name)}"
                    rows[f"{schema}.{name}"] = [
                        str(value)
                        for value in c.execute(
                            text(
                                f"SELECT row_to_json(t)::text FROM {qualified} t "
                                "ORDER BY row_to_json(t)::text"
                            )
                        ).scalars()
                    ]
                catalog_queries = {
                    "columns": """
                        SELECT e.nspname,e.relname,a.attname,
                            format_type(a.atttypid,a.atttypmod),a.attnotnull,
                            pg_get_expr(d.adbin,d.adrelid),
                            col_description(a.attrelid,a.attnum)
                        FROM existing e JOIN pg_attribute a ON a.attrelid=e.oid
                        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                        WHERE a.attnum>0 AND NOT a.attisdropped
                        ORDER BY e.nspname,e.relname,a.attnum
                    """,
                    "constraints": """
                        SELECT e.nspname,e.relname,k.conname,pg_get_constraintdef(k.oid),
                            k.convalidated,obj_description(k.oid,'pg_constraint')
                        FROM existing e JOIN pg_constraint k ON k.conrelid=e.oid
                        ORDER BY e.nspname,e.relname,k.conname
                    """,
                    "indexes": """
                        SELECT e.nspname,e.relname,i.relname,pg_get_indexdef(x.indexrelid),
                            x.indisvalid,x.indisready
                        FROM existing e JOIN pg_index x ON x.indrelid=e.oid
                        JOIN pg_class i ON i.oid=x.indexrelid
                        ORDER BY e.nspname,e.relname,i.relname
                    """,
                    "triggers": """
                        SELECT e.nspname,e.relname,t.tgname,t.tgenabled,
                            pg_get_triggerdef(t.oid)
                        FROM existing e JOIN pg_trigger t ON t.tgrelid=e.oid
                        WHERE NOT t.tgisinternal ORDER BY e.nspname,e.relname,t.tgname
                    """,
                }
                return {
                    "relations": [tuple(row) for row in relations],
                    "rows": rows,
                    "catalog": {
                        key: [
                            tuple(row)
                            for row in c.execute(text(f"WITH existing AS ({existing}) {query}"))
                        ]
                        for key, query in catalog_queries.items()
                    },
                }

            before = existing_snapshot()
            # A populated old business history is necessary to make preservation meaningful.
            for table in (
                tables.product_definitions,
                tables.definition_releases,
                tables.definition_reviews,
                tables.product_strategies,
                tables.product_nodes,
                tables.research_sources,
                tables.evidence_snapshots,
                tables.evidence_contents,
                tables.users,
                tables.tenants,
                tables.events,
                tables.audit_log,
            ):
                assert before["rows"][table.fullname], (
                    f"Expected real seed rows in {table.fullname}"
                )
            definition_row = (
                c.execute(
                    select(tables.product_definitions).where(
                        tables.product_definitions.c.id == UUID(candidate.definition["id"])
                    )
                )
                .mappings()
                .one()
            )
            assert definition_row["state"] == "published"
            assert (
                c.execute(
                    select(tables.evidence_contents.c.body).where(
                        tables.evidence_contents.c.tenant_id == scope.tenant_id,
                        tables.evidence_contents.c.content_digest == candidate.reference["digest"],
                    )
                )
                .scalar_one()
                .strip()
            )
            migration.downgrade()
            assert (
                c.execute(
                    text("SELECT to_regclass('cehub_product.product_master_references')")
                ).scalar_one()
                is None
            )
            assert existing_snapshot() == before
            migration.upgrade()
            assert existing_snapshot() == before
            assert (
                c.execute(
                    text("SELECT count(*) FROM cehub_product.product_master_references")
                ).scalar_one()
                == 0
            )
    finally:
        scope.dispose()


def test_populated_history_blocks_downgrade_update_and_delete_without_changing_bytes(
    registered_reference: MasterCandidate,
) -> None:
    migration = import_module("migrations.versions.0409_product_master_references")
    with rollback_migration_operations(registered_reference.scope.engine) as c:
        row = receipt(c, registered_reference)
        original = receipt_bytes(c, row["id"])
        with (
            pytest.raises(DBAPIError, match="Cannot discard master reference history"),
            c.begin_nested(),
        ):
            migration.downgrade()
        for statement in (
            tables.product_master_references.update()
            .where(tables.product_master_references.c.id == row["id"])
            .values(reason="attempted rewrite"),
            tables.product_master_references.delete().where(
                tables.product_master_references.c.id == row["id"]
            ),
        ):
            with pytest.raises(DBAPIError, match="append-only"), c.begin_nested():
                c.execute(statement)
            assert receipt_bytes(c, row["id"]) == original
        assert receipt_bytes(c, row["id"]) == original


def test_insert_rejects_invalid_external_identity_and_noncurrent_definition_product_context(
    registered_reference: MasterCandidate,
) -> None:
    with rollback_migration_operations(registered_reference.scope.engine) as c:
        row = receipt(c, registered_reference)
        original = receipt_bytes(c, row["id"])
        invalid: list[dict[str, Any]] = [
            {"master_kind": "cad_revision", "system_kind": "erp"},
            {"master_kind": "material", "system_kind": "plm"},
            {"system_kind": "other"},
            {"external_as_of": datetime.now(UTC) + timedelta(days=1)},
            {"market_space_id": uuid4()},
            {"product_id": uuid4()},
            {"created_by_user_id": uuid4()},
            {"definition_ref": {**row["definition_ref"], "release_id": str(uuid4())}},
            {"definition_ref": {**row["definition_ref"], "id": str(uuid4())}},
            {"definition_ref": {**row["definition_ref"], "version": 999999}},
            {"definition_ref": {**row["definition_ref"], "revision": 999999}},
            {"product_snapshot": {**row["product_snapshot"], "id": str(uuid4())}},
            {"product_snapshot": {**row["product_snapshot"], "version": 999999}},
        ]
        for change in invalid:
            rejected_append(c, row, **change)
            assert receipt_bytes(c, row["id"]) == original
        # The user really exists, but its tenant is foreign: prove the scoped FK,
        # rather than merely sending an unknown actor ID through the trigger.
        foreign_tenant, foreign_user = uuid4(), uuid4()
        c.execute(
            tables.tenants.insert(),
            {
                "id": foreign_tenant,
                "slug": f"master-fk-{foreign_tenant.hex}",
                "name": "Synthetic foreign scope",
            },
        )
        c.execute(
            tables.users.insert(),
            {
                "id": foreign_user,
                "tenant_id": foreign_tenant,
                "username": "foreign-owner",
                "display_name": "Synthetic foreign owner",
                "role": "owner",
            },
        )
        with (
            pytest.raises(DBAPIError, match="fk_product_master_references_tenant_id_users"),
            c.begin_nested(),
        ):
            append(c, row, created_by_user_id=foreign_user)
        assert receipt_bytes(c, row["id"]) == original


def test_successor_is_single_append_and_withdrawal_freezes_identity_context_and_sources(
    registered_reference: MasterCandidate,
) -> None:
    with rollback_migration_operations(registered_reference.scope.engine) as c:
        row = receipt(c, registered_reference)
        original = receipt_bytes(c, row["id"])
        corrected = append(
            c,
            row,
            action="correct",
            previous_id=row["id"],
            external_revision="B",
            reason="corrected internal reference",
        )
        rejected_append(c, row, action="correct", previous_id=row["id"], reason="fork")
        rejected_append(c, row, action="correct", previous_id=uuid4(), reason="foreign predecessor")
        for change in (
            {"external_id": "different-identity"},
            {"external_revision": "C"},
            {"context_digest": "f" * 64},
            {"sources": [{**corrected["sources"][0], "digest": "e" * 64}]},
            {"definition_ref": {**corrected["definition_ref"], "version": 999999}},
            {"product_snapshot": {**corrected["product_snapshot"], "version": 999999}},
        ):
            rejected_append(
                c,
                corrected,
                action="withdraw",
                previous_id=corrected["id"],
                reason="withdraw attempted context replacement",
                **change,
            )
        withdrawn = append(
            c,
            corrected,
            action="withdraw",
            previous_id=corrected["id"],
            reason="withdraw internal reference only",
        )
        rejected_append(
            c, withdrawn, action="correct", previous_id=withdrawn["id"], reason="after withdrawal"
        )
        assert receipt_bytes(c, row["id"]) == original
        stored = (
            c.execute(
                select(tables.product_master_references).where(
                    tables.product_master_references.c.id == withdrawn["id"]
                )
            )
            .mappings()
            .one()
        )
        for key in (
            "system_kind",
            "source_system",
            "master_kind",
            "external_id",
            "external_revision",
            "external_as_of",
            "sources",
            "definition_ref",
            "product_snapshot",
            "context_digest",
        ):
            assert stored[key] == corrected[key]
