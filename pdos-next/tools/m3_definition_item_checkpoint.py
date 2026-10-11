"""Verified synthetic definition-item catalog roundtrip and ORM/ACL audit."""

import argparse
import json

import m3_environment as fixture
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from m3_schema_checkpoint import catalog, migrate
from pdos_next import api  # noqa: F401 -- populate the complete domain metadata
from pdos_next.database import engine_for
from pdos_next.models import Base
from sqlalchemy import text

PREDECESSORS = {
    "s0_0753": "s0_0752", "s0_0754": "s0_0753",
    "s0_0755": "s0_0754", "s0_0756": "s0_0755", "s0_0757": "s0_0756",
}


def run(audit_only=False, revision="s0_0753", attempt=1):
    current = fixture.state()
    report = fixture.REPORT.parent / (
        "spec-bounds" if revision == "s0_0757" else "definition-items"
    )
    report.mkdir(exist_ok=True)
    label = "schema" if revision == "s0_0753" else revision
    target = report / f"{label}-{'audit' if audit_only else 'roundtrip'}.json"
    if target.exists():
        raise RuntimeError("Preserve previous evidence; use the recorded checkpoint")
    engine = engine_for(current["admin_url"])
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert head == (revision if audit_only else PREDECESSORS[revision])
        before = catalog(connection)
    if not audit_only:
        index = 2 * attempt - 1
        migrate("upgrade", revision, f"upgrade-{revision}-{index}.log")
        with engine.connect() as connection:
            after = catalog(connection)
        migrate("downgrade", PREDECESSORS[revision], f"downgrade-{revision}-{attempt}.log")
        with engine.connect() as connection:
            restored = catalog(connection)
        assert restored == before, "Downgrade must restore the actual predecessor catalog"
        migrate("upgrade", revision, f"upgrade-{revision}-{index + 1}.log")
    else:
        after, restored = before, before
    with engine.connect() as connection:
        final = catalog(connection)
        differences = compare_metadata(
            MigrationContext.configure(
                connection,
                opts={
                    "include_object": lambda obj, name, kind, reflected, compared: (
                        not (kind == "table" and name == "environment_guard")
                    ),
                },
            ),
            Base.metadata,
        )
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        agent_writes = list(
            connection.scalars(
                text(
                    "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace "
                    "AND relkind='r' AND has_table_privilege('pdos_agent',oid,"
                    "'INSERT,UPDATE,DELETE')"
                )
            )
        )
        current_writes = connection.scalar(
            text(
                "SELECT has_table_privilege('pdos_next_app','definition_spec_current',"
                "'INSERT,UPDATE,DELETE') OR has_any_column_privilege('pdos_next_app',"
                "'definition_spec_current','INSERT,UPDATE')"
            )
        )
        unsafe_definers = list(
            connection.scalars(
                text(
                    "SELECT p.oid::regprocedure::text FROM pg_proc p "
                    "JOIN pg_roles r ON r.oid=p.proowner "
                    "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef AND "
                    "(r.rolname<>'pdos_next_owner' OR r.rolsuper "
                    "OR r.rolbypassrls OR r.rolcanlogin)"
                )
            )
        )
        unsafe_owner_members = connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN "
                "('pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_agent') "
                "AND pg_has_role(rolname,'pdos_next_owner','MEMBER'))"
            )
        )
        disabled_triggers = list(connection.scalars(text(
            "SELECT t.tgrelid::regclass::text || '.' || t.tgname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid=t.tgrelid "
            "WHERE c.relnamespace='public'::regnamespace AND NOT t.tgisinternal "
            "AND t.tgenabled NOT IN ('O','A') ORDER BY 1"
        )))
    engine.dispose()
    result = {
        "head": head,
        "port": current["port"],
        "marker": current["marker"],
        "synthetic_only": True,
        "llm_calls": 0,
        "catalog_before": before,
        "catalog_after": after,
        "catalog_downgrade_restored": restored == before,
        "catalog_reupgrade_exact": final == after,
        "orm_differences": repr(differences),
        "agent_write_tables": agent_writes,
        "app_current_writes": current_writes,
        "unsafe_definers": unsafe_definers,
        "runtime_owner_membership": unsafe_owner_members,
        "disabled_business_triggers": disabled_triggers,
    }
    target.write_text(json.dumps(result, indent=2) + "\n")
    assert head == revision and final == after and not differences
    assert not (
        agent_writes or current_writes or unsafe_definers
        or unsafe_owner_members or disabled_triggers
    )
    print(f"{revision} full ORM, enabled guards and ordinary-owner/zero-direct-write audit passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--revision", choices=tuple(PREDECESSORS), default="s0_0753")
    parser.add_argument("--attempt", type=int, choices=range(1, 100), default=1)
    args = parser.parse_args()
    run(args.audit_only, args.revision, args.attempt)
