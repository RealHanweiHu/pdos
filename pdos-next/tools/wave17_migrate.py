"""Root-only marked migration roundtrip; preserve the retained 106-table history."""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from local_environment import ROOT, SERVER, environment, read_state, verified
from pdos_next.database import engine_for
from pdos_next.lifecycle_catalog import COVERED_COLUMNS, GUARDED
from pdos_next.models import Base
from sqlalchemy import text
from sqlalchemy.engine import make_url
from wave16_closeout import private_json
from wave16_migrate import history
from wave17_ddl_rollback_observation import catalog

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
VERSION = "v2"
NEW = (
    "capa_verification_rule_facts",
    "capa_observation_facts",
    "capa_named_verification_reviews",
    "capa_current_verification_rules",
    "capa_current_observations",
)
FROZEN = (
    "pdos_next/models.py",
    "pdos_next/lifecycle_catalog.py",
    "pdos_next/domain/capa_effectiveness/models.py",
    "pdos_next/domain/capa_effectiveness/fact_storage_models.py",
    "pdos_next/domain/capa_effectiveness/fact_storage_codec.py",
    "pdos_next/domain/capa_effectiveness/facts.py",
    "pdos_next/domain/capa_effectiveness/anchor.py",
    "pdos_next/domain/capa_effectiveness/paired.py",
    "migrations/versions/0026_capa_verification_facts.py",
)


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def target():
    private_json(ROOT / ".local/runtime.json")
    state = verified(read_state())
    if state["port"] != 62513 or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
        raise RuntimeError("Unexpected marked migration target")
    for key in ("admin_url", "app_url", "auth_url"):
        url = make_url(state[key])
        if (url.host, url.port, url.database) != ("127.0.0.1", 62513, "pdos_test"):
            raise RuntimeError("Role endpoint mismatch")
    return state


def main():
    if sys.argv[1:] != ["run"]:
        raise RuntimeError("Explicit Root migration checkpoint required")
    result = {
        "status": "RUNNING",
        "target": "127.0.0.1:62513/pdos_test",
        "marker": "916f950f-2d2b-405d-b809-c15db75dc20c",
        "business_fact_writes": 0,
        "model_calls": 0,
        "steps": [],
        "scope": "Numbered migration roundtrip, schema/lifecycle/role catalog; no fact publication",
    }
    result["tool_sha256"] = digest_file(__file__)
    out = REPORT / f"public-migration-result-{VERSION}.json"
    if out.exists():
        raise RuntimeError("Original migration evidence must not be overwritten")
    frozen = {name: digest_file(SERVER / name) for name in FROZEN}
    result["source_sha256"] = frozen
    try:
        state = target()
        engine = engine_for(state["admin_url"])
        with engine.connect() as c:
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0025"
            names = (
                c.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename NOT IN ('alembic_version','environment_guard') "
                        "ORDER BY tablename"
                    )
                )
                .scalars()
                .all()
            )
            assert len(names) == 106 and not set(NEW).intersection(names)
            before = history(c, names)
            before_catalog = catalog(c)
        (REPORT / f"public-migration-retained-before-{VERSION}.json").write_text(
            json.dumps(before, indent=2) + "\n"
        )
        backup = ROOT / ".local/pre-wave17-next_0025.dump"
        with backup.open("xb") as output:
            backup.chmod(0o600)
            subprocess.run(
                [
                    "docker",
                    "exec",
                    state["container"],
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "pdos_test",
                    "-Fc",
                ],
                stdout=output,
                check=True,
            )
        result["backup"] = {
            "path": str(backup),
            "bytes": backup.stat().st_size,
            "sha256": digest_file(backup),
            "mode": "0600",
        }
        for index, args in enumerate(
            (
                ("upgrade", "next_0026"),
                ("downgrade", "next_0025"),
                ("upgrade", "next_0026"),
                ("check",),
            )
        ):
            state = target()
            assert all(digest_file(SERVER / name) == value for name, value in frozen.items())
            log = REPORT / f"public-migration-{index}-{VERSION}.log"
            with log.open("x") as output:
                process = subprocess.run(
                    [sys.executable, "-m", "alembic", *args],
                    cwd=SERVER,
                    env=environment(state),
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            result["steps"].append(
                {"step": args, "exit_code": process.returncode, "log_sha256": digest_file(log)}
            )
            if process.returncode:
                raise RuntimeError("Numbered migration checkpoint failed; raw log preserved")
            with engine.connect() as c:
                head = c.scalar(text("SELECT version_num FROM alembic_version"))
                assert head == ("next_0025" if index == 1 else "next_0026")
                if index == 1:
                    assert catalog(c) == before_catalog
                    assert history(c, names) == before
                    result["downgrade_catalog_restored"] = True
                    result["downgrade_retained_rows_unchanged"] = True
        with engine.connect() as c:
            assert history(c, names) == before
            actual = c.execute(
                text(
                    "SELECT table_name,column_name FROM information_schema.columns "
                    "WHERE table_schema='public' "
                    "AND table_name NOT IN ('alembic_version','environment_guard') "
                    "ORDER BY table_name,ordinal_position"
                )
            ).all()
            columns = {}
            for table, column in actual:
                columns.setdefault(table, []).append(column)
            assert len(Base.metadata.tables) == len(columns) == len(COVERED_COLUMNS) == 111
            assert set(Base.metadata.tables) == set(columns) == set(COVERED_COLUMNS)
            for name, table in Base.metadata.tables.items():
                assert tuple(table.c.keys()) == tuple(columns[name]) == COVERED_COLUMNS[name], name
            for name in NEW:
                assert name in GUARDED
                assert (
                    c.scalar(
                        text(
                            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                            "WHERE oid=to_regclass(:name)"
                        ),
                        {"name": name},
                    )
                    is True
                )
                assert (
                    c.scalar(
                        text(
                            "SELECT count(*) FROM pg_trigger WHERE tgrelid=to_regclass(:name) "
                            "AND tgname='lifecycle_reference' AND tgenabled='O'"
                        ),
                        {"name": name},
                    )
                    == 1
                )
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert (
                        c.scalar(
                            text("SELECT has_table_privilege('pdos_agent',:name,:privilege)"),
                            {"name": name, "privilege": privilege},
                        )
                        is False
                    )
            for name in (*NEW, "capa_verification_evidence"):
                assert c.scalar(text(f'SELECT count(*) FROM "{name}"')) == 0
        result.update(
            status="PASS",
            head="next_0026",
            retained_tables=106,
            all_retained_rows_unchanged=True,
            public_tables=111,
            runtime_catalog_database_columns_match=True,
            five_force_rls=True,
            five_enabled_lifecycle_gates=True,
            agent_direct_privileges=0,
            new_fact_publication=False,
        )
    except Exception as error:
        result.update(status="FAIL", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result["source_stable"] = all(digest_file(SERVER / n) == v for n, v in frozen.items())
        result["observed_at"] = datetime.now(UTC).isoformat()
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        "Migration 26 up/down/up/schema: PASS; "
        "all 106 retained tables preserved; 111 registered tables."
    )


if __name__ == "__main__":
    main()
