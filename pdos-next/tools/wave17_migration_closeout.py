"""Finish only the physical-column-order postcheck after the successful roundtrip."""

# Initialize the explicit local server path before importing its modules.
# ruff: noqa: I001

import json
from datetime import UTC, datetime

from local_environment import SERVER  # initializes the local server path

from pdos_next.database import engine_for
from pdos_next.lifecycle_access import NON_CONSUMING, schema_covered
from pdos_next.lifecycle_catalog import COVERED_COLUMNS, GUARDED
from pdos_next.models import Base
from sqlalchemy import text
from sqlalchemy.orm import Session
from wave17_migrate import FROZEN, NEW, REPORT, digest_file, history, target


def main():
    previous_path = REPORT / "public-migration-result-v2.json"
    previous = json.loads(previous_path.read_text())
    assert previous["status"] == "FAIL" and previous["error"] == "principals"
    assert previous["error_type"] == "AssertionError"
    assert previous["source_stable"] is True
    assert previous["downgrade_catalog_restored"] is True
    assert previous["downgrade_retained_rows_unchanged"] is True
    assert [s["exit_code"] for s in previous["steps"]] == [0, 0, 0, 0]
    assert [s["step"] for s in previous["steps"]] == [
        ["upgrade", "next_0026"],
        ["downgrade", "next_0025"],
        ["upgrade", "next_0026"],
        ["check"],
    ]
    for index, step in enumerate(previous["steps"]):
        assert digest_file(REPORT / f"public-migration-{index}-v2.log") == step["log_sha256"]
    frozen = previous["source_sha256"]
    assert set(frozen) == set(FROZEN)
    assert all(digest_file(SERVER / name) == value for name, value in frozen.items())
    before_path = REPORT / "public-migration-retained-before-v2.json"
    before = json.loads(before_path.read_text())
    state = target()
    engine = engine_for(state["admin_url"])
    result = {
        "status": "FAIL",
        "scope": "Postcheck only; exact retained up/down/up/schema log binding",
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "tool_sha256": digest_file(__file__),
        "roundtrip_result_sha256": digest_file(previous_path),
        "roundtrip_steps": previous["steps"],
        "source_sha256": frozen,
        "retained_before_sha256": digest_file(before_path),
        "business_fact_writes": 0,
        "model_calls": 0,
        "migration_rerun": False,
    }
    out = REPORT / "public-migration-closeout-v3.json"
    assert not out.exists()
    try:
        assert digest_file(previous["backup"]["path"]) == previous["backup"]["sha256"]
        with Session(engine) as s, s.begin():
            c = s.connection()
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
            assert len(before) == 106 and history(c, before) == before
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
            order_differences = []
            for name, table in Base.metadata.tables.items():
                assert tuple(table.c.keys()) == COVERED_COLUMNS[name], name
                assert set(table.c.keys()) == set(columns[name]), name
                if tuple(columns[name]) != COVERED_COLUMNS[name]:
                    order_differences.append(name)
            for name in NEW:
                assert tuple(columns[name]) == COVERED_COLUMNS[name]
                assert name in GUARDED and name not in NON_CONSUMING
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
            assert schema_covered(s) is True
            for name in (*NEW, "capa_verification_evidence"):
                assert c.scalar(text(f'SELECT count(*) FROM "{name}"')) == 0
            result.update(
                status="PASS",
                head="next_0026",
                retained_tables=106,
                all_retained_rows_unchanged=True,
                public_tables=111,
                runtime_catalog_database_column_names_match=True,
                new_five_column_order_match=True,
                retained_physical_order_differences=order_differences,
                five_force_rls=True,
                five_enabled_lifecycle_gates=True,
                actual_schema_covered=True,
                agent_direct_privileges=0,
                new_fact_publication=False,
            )
    except Exception as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result["source_stable"] = all(digest_file(SERVER / n) == v for n, v in frozen.items())
        result["observed_at"] = datetime.now(UTC).isoformat()
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        "Exact migration roundtrip bound; 111-table schema/lifecycle and retained 106 rows: PASS."
    )


if __name__ == "__main__":
    main()
