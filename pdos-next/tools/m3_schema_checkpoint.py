"""Formal 0728→0729→0728→0729 and ORM/owner check in M3's own database."""

import argparse
import hashlib
import json

import m3_environment as fixture
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pdos_next.database import engine_for
from pdos_next.models import Base
from sqlalchemy import text


def catalog(connection):
    queries = {
        "tables": "SELECT relname,pg_get_userbyid(relowner),relrowsecurity,relforcerowsecurity "
        "FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' ORDER BY 1",
        "columns": "SELECT table_name,column_name,data_type,is_nullable,column_default "
        "FROM information_schema.columns WHERE table_schema='public' ORDER BY 1,ordinal_position",
        "constraints": "SELECT conrelid::regclass::text,conname,pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1,2",
        "functions": "SELECT oid::regprocedure::text,pg_get_functiondef(oid),proacl::text,"
        "pg_get_userbyid(proowner) FROM pg_proc "
        "WHERE pronamespace='public'::regnamespace ORDER BY 1",
        "triggers": "SELECT tgrelid::regclass::text,tgname,pg_get_triggerdef(oid) FROM pg_trigger "
        "WHERE NOT tgisinternal AND tgrelid IN (SELECT oid FROM pg_class "
        "WHERE relnamespace='public'::regnamespace) ORDER BY 1,2",
        "policies": "SELECT tablename,policyname,roles::text,cmd,qual,with_check "
        "FROM pg_policies WHERE schemaname='public' ORDER BY 1,2",
        "grants": "SELECT table_name,grantee,privilege_type,is_grantable "
        "FROM information_schema.role_table_grants WHERE table_schema='public' ORDER BY 1,2,3,4",
        "column_grants": "SELECT table_name,column_name,grantee,privilege_type,is_grantable "
        "FROM information_schema.column_privileges WHERE table_schema='public' ORDER BY 1,2,3,4,5",
        "indexes": "SELECT tablename,indexname,indexdef FROM pg_indexes "
        "WHERE schemaname='public' ORDER BY 1,2",
    }
    return {
        name: hashlib.sha256(
            json.dumps([list(row) for row in connection.execute(text(query))]).encode()
        ).hexdigest()
        for name, query in queries.items()
    }


def migrate(direction, target, name):
    if fixture.run(["-m", "alembic", direction, target], name):
        raise RuntimeError(f"M3 migration failed; see {name}")


def run(audit_only=False):
    current = fixture.state()
    engine = engine_for(current["admin_url"])
    if audit_only:
        prior = json.loads((fixture.REPORT / "schema.json").read_text())
        assert prior["marker"] == current["marker"]
        assert prior["catalog_downgrade_restored"] and prior["catalog_reupgrade_exact"]
        before = restored = prior["catalog_before"]
        with engine.connect() as connection:
            after = catalog(connection)
    else:
        with engine.connect() as connection:
            if connection.scalar(text("SELECT version_num FROM alembic_version")) != "s0_0728":
                raise RuntimeError("Start the empty formal checkpoint at B8 s0_0728")
            before = catalog(connection)
        migrate("upgrade", "head", "upgrade-0729-1.log")
        with engine.connect() as connection:
            after = catalog(connection)
        migrate("downgrade", "s0_0728", "downgrade-0728-1.log")
        with engine.connect() as connection:
            restored = catalog(connection)
        if restored != before:
            (fixture.REPORT / "catalog-mismatch.json").write_text(
                json.dumps({"before": before, "restored": restored}, indent=2) + "\n"
            )
            raise RuntimeError("M3 downgrade did not restore the B8 catalog")
        migrate("upgrade", "head", "upgrade-0729-2.log")
    with engine.connect() as connection:
        final = catalog(connection)
        differences = compare_metadata(
            MigrationContext.configure(
                connection,
                opts={
                    "include_object": lambda obj, name, kind, reflected, compared: (
                        not (kind == "table" and name == "environment_guard")
                    )
                },
            ),
            Base.metadata,
        )
        definers = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT p.oid::regprocedure::text AS signature,r.rolname AS owner,"
                    "r.rolsuper AS superuser,r.rolbypassrls AS bypassrls,r.rolcanlogin AS login,"
                    "p.proconfig AS settings FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
                    "WHERE p.pronamespace='public'::regnamespace AND p.prosecdef ORDER BY 1"
                )
            ).mappings()
        ]
        tables = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT relname,pg_get_userbyid(relowner) AS owner,relrowsecurity AS rls,"
                    "relforcerowsecurity AS forced FROM pg_class "
                    "WHERE relnamespace='public'::regnamespace AND relkind='r' "
                    "AND relname NOT IN ('alembic_version','environment_guard') ORDER BY 1"
                )
            ).mappings()
        ]
        agent_writes = connection.scalars(
            text(
                "SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace "
                "AND relkind='r' AND has_table_privilege('pdos_agent',oid,'INSERT,UPDATE,DELETE')"
            )
        ).all()
        runtime_owner = connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN "
                "('pdos_next_app','pdos_next_auth','pdos_next_dispatch','pdos_agent') "
                "AND pg_has_role(rolname,'pdos_next_owner','MEMBER'))"
            )
        )
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    engine.dispose()
    result = {
        "head": head,
        "frozen_b8_commit": "0eccfe0376d387de7a5211c2852f50f2432ca7b4",
        "port": current["port"],
        "marker": current["marker"],
        "synthetic_only": True,
        "catalog_before": before,
        "catalog_after": after,
        "catalog_downgrade_restored": restored == before,
        "catalog_reupgrade_exact": final == after,
        "orm_differences": repr(differences),
        "business_tables": len(tables),
        "definers": definers,
        "agent_write_tables": agent_writes,
        "runtime_owner_membership": runtime_owner,
        "llm_calls": 0,
    }
    (fixture.REPORT / "schema.json").write_text(json.dumps(result, indent=2) + "\n")
    if (
        final != after
        or differences
        or agent_writes
        or runtime_owner
        or head != "s0_0729"
        or any(
            f["owner"] != "pdos_next_owner" or f["superuser"] or f["bypassrls"] or f["login"]
            for f in definers
        )
        or any(t["owner"] != "pdos_next_owner" for t in tables)
        or {t["relname"] for t in tables if not t["rls"] or not t["forced"]} != {"login_sessions"}
    ):
        raise RuntimeError("M3 schema or owner mismatch; see schema.json")
    print(f"M3 formal roundtrip, full ORM and {len(definers)} ordinary-owner definers passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    run(parser.parse_args().audit_only)
