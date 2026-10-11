"""Exact catalog roundtrip before new receipt metadata is written; M3 fixture only."""

import argparse
import json

import m3_environment as fixture
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from m3_schema_checkpoint import catalog
from pdos_next.database import engine_for
from pdos_next.models import Base
from sqlalchemy import text


def run(predecessor, successor, evidence, *, report=None):
    state = fixture.state()
    engine = engine_for(state["admin_url"])
    report = report or fixture.REPORT.parent / "category-materials"
    report.mkdir(exist_ok=True)
    target = report / evidence
    log_suffix = target.stem
    if target.exists():
        raise RuntimeError("Preserve prior schema evidence")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == predecessor
        before = catalog(connection)
    assert (
        fixture.run(
            ["-m", "alembic", "upgrade", successor], f"upgrade-{successor}-{log_suffix}-1.log"
        )
        == 0
    )
    with engine.connect() as connection:
        after = catalog(connection)
    assert (
        fixture.run(
            ["-m", "alembic", "downgrade", predecessor], f"downgrade-{successor}-{log_suffix}-1.log"
        )
        == 0
    )
    with engine.connect() as connection:
        restored = catalog(connection)
    if restored != before:
        target.write_text(json.dumps({"before": before, "restored": restored}, indent=2) + "\n")
        raise RuntimeError("Material downgrade catalog mismatch; preserve checkpoint")
    assert (
        fixture.run(
            ["-m", "alembic", "upgrade", successor], f"upgrade-{successor}-{log_suffix}-2.log"
        )
        == 0
    )
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
        tables = connection.execute(
            text(
                "SELECT relname,pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity "
                "FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' "
                "AND relname NOT IN ('alembic_version','environment_guard') ORDER BY 1"
            )
        ).all()
        bad_definers = connection.scalars(
            text(
                "SELECT p.oid::regprocedure::text FROM pg_proc p "
                "JOIN pg_roles r ON r.oid=p.proowner "
                "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef AND "
                "(r.rolname<>'pdos_next_owner' OR r.rolsuper OR r.rolbypassrls OR r.rolcanlogin "
                "OR p.proconfig IS NULL)"
            )
        ).all()
        agent_writes = connection.scalars(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace "
                "AND relkind='r' AND has_table_privilege('pdos_agent',oid,'INSERT,UPDATE,DELETE')"
            )
        ).all()
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    result = {
        "head": head,
        "port": state["port"],
        "marker": state["marker"],
        "synthetic_only": True,
        "catalog_before": before,
        "catalog_after": after,
        "catalog_downgrade_restored": restored == before,
        "catalog_reupgrade_exact": final == after,
        "orm_differences": repr(differences),
        "business_tables": len(tables),
        "bad_definers": bad_definers,
        "agent_write_tables": agent_writes,
        "llm_calls": 0,
    }
    target.write_text(json.dumps(result, indent=2) + "\n")
    engine.dispose()
    assert head == successor and final == after and not differences
    assert not bad_definers and not agent_writes
    assert all(row[1] == "pdos_next_owner" for row in tables)
    assert {row[0] for row in tables if not row[2] or not row[3]} == {"login_sessions"}
    print("M3 material exact catalog roundtrip and full ORM passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-revision", required=True)
    parser.add_argument("--to-revision", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if not args.evidence.endswith(".json") or "/" in args.evidence:
        parser.error("A plain JSON evidence filename is required")
    run(args.from_revision, args.to_revision, args.evidence)
