"""Root-only retained history excluding exactly the newly allocated shared Product."""

# The verified local loader initializes the actual server import path.
# ruff: noqa: I001
import hashlib
import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from local_environment import ROOT
from wave16_closeout import private_json
from wave17_candidate_closeout import RETAINED
from wave17_migrate import target
from wave21_check import source
from pdos_next.database import engine_for
from pdos_next.models import Base
from sqlalchemy import text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave22-20261003"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("v") or not sys.argv[1][1:].isdigit():
        raise RuntimeError("A fresh numbered Root read-only checkpoint is required")
    output = REPORT / f"retained-case-exclusion-{sys.argv[1]}.json"
    if output.exists():
        raise RuntimeError("Original evidence must be retained")
    state = target()
    case = private_json(ROOT / ".local/wave21-shared-case.json")
    if case["marker"] != state["marker"] or case["phase"] != "foundation_saved_not_build_started":
        raise RuntimeError("Exact actual new shared foundation is required")
    product = UUID(case["product_id"])
    before = json.loads((REPORT / "foundation-before-v1.json").read_text())
    baseline = {v["table"]: v["current"] for v in before["before"]["retained"]["tables"]}
    frozen = json.loads(
        (REPORT.parent / "pdos-next-wave21-20261003/candidate-source-v2.json").read_text()
    )
    result = {
        "status": "PASS",
        "recorded_at": datetime.now(UTC).isoformat(),
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "excluded_exact_new_product_id": str(product),
        "scope": (
            "Complete rows of the listed 24 tables and six CAPA tables excluding "
            "exactly this new Product; not whole database"
        ),
        "before_sha256": sha(REPORT / "foundation-before-v1.json"),
        "tables": [],
        "capa_tables": {},
        "retained_private_files_unchanged": all(
            sha(ROOT.parent / name) == expected
            for name, expected in before["retained_private_file_hashes"].items()
        ),
        "previous_544_scoped_source_files_unchanged": source() == frozen,
        "business_commands": 0,
        "model_calls": 0,
    }
    engine = engine_for(state["admin_url"])
    try:
        with engine.connect() as c:
            transaction = c.begin()
            c.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            c.execute(text("SET LOCAL statement_timeout='30s'"))
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
            for name in RETAINED:
                table = Base.metadata.tables[name]
                assert "product_id" in table.c and list(table.primary_key.columns)
                ordering = ", ".join('"' + col.name + '"' for col in table.primary_key.columns)
                digest, count = hashlib.sha256(), 0
                query = text(
                    f'SELECT to_jsonb(t)::text FROM "{name}" t '
                    f"WHERE product_id IS DISTINCT FROM :product ORDER BY {ordering}"
                )
                for row in c.execute(query, {"product": product}).scalars():
                    digest.update(row.encode())
                    digest.update(b"\n")
                    count += 1
                current = {"rows": count, "sha256": digest.hexdigest()}
                added = c.scalar(
                    text(f'SELECT count(*) FROM "{name}" WHERE product_id=:product'),
                    {"product": product},
                )
                result["tables"].append(
                    {
                        "table": name,
                        "current_retained": current,
                        "unchanged": current == baseline[name],
                        "new_case_rows": added,
                    }
                )
            for name, expected in before["before"]["counts"].items():
                assert "product_id" in Base.metadata.tables[name].c
                retained = c.scalar(
                    text(
                        f'SELECT count(*) FROM "{name}" WHERE product_id IS DISTINCT FROM :product'
                    ),
                    {"product": product},
                )
                added = c.scalar(
                    text(f'SELECT count(*) FROM "{name}" WHERE product_id=:product'),
                    {"product": product},
                )
                result["capa_tables"][name] = {
                    "retained_rows": retained,
                    "unchanged": retained == expected,
                    "new_case_rows": added,
                }
            transaction.rollback()
    finally:
        engine.dispose()
    if not (
        result["retained_private_files_unchanged"]
        and result["previous_544_scoped_source_files_unchanged"]
        and all(row["unchanged"] for row in result["tables"])
        and all(row["unchanged"] for row in result["capa_tables"].values())
    ):
        result["status"] = "FAIL"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "report": str(output)}))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
