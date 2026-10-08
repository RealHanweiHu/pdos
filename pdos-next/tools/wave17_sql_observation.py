"""Root-only read of exact installed functions, never a migration execution."""

import hashlib
import json
from datetime import UTC, datetime

from local_environment import ROOT, read_state, verified
from pdos_next.database import engine_for
from sqlalchemy import text
from sqlalchemy.engine import make_url
from wave16_check import source_files

FUNCTIONS = (
    "assert_quality_followup_proof(uuid,uuid,uuid,text,jsonb,timestamptz)",
    "protect_quality_followup_confirmation()",
    "require_quality_followup_consumption_atom()",
    "assert_quality_change_receipt(uuid,uuid,uuid,integer,text,text,uuid,text)",
    "assert_quality_followup_receipt(uuid,uuid,uuid,integer,text,text,uuid,text,text)",
    "require_quality_followup_atom()",
)


def main():
    report = (
        ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003/sql-actual-functions-v1.json"
    )
    if report.exists():
        raise RuntimeError("Preserve the original installed-function observation")
    state = verified(read_state())
    url = make_url(state["admin_url"])
    if (
        state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c"
        or state["port"] != 62513
        or url.host != "127.0.0.1"
        or url.port != 62513
        or url.database != "pdos_test"
    ):
        raise RuntimeError("Wrong marked independent target")
    before = source_files()
    engine = engine_for(state["admin_url"])
    definitions = {}
    try:
        with engine.connect() as c, c.begin():
            c.execute(text("SET TRANSACTION READ ONLY"))
            head = c.scalar(text("SELECT version_num FROM alembic_version"))
            if head != "next_0025" or c.scalar(text("SHOW transaction_read_only")) != "on":
                raise RuntimeError("Exact readonly head25 required")
            for signature in FUNCTIONS:
                body = c.scalar(
                    text("SELECT pg_get_functiondef(to_regprocedure(:signature))"),
                    {"signature": "public." + signature},
                )
                if not body:
                    raise RuntimeError("Required installed function missing")
                definitions[signature] = body
    finally:
        engine.dispose()
    result = {
        "scope": "Exact actual head25 SQL function read; no DDL/proof/business write",
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "head": head,
        "observed_at": datetime.now(UTC).isoformat(),
        "transaction_read_only": True,
        "definitions": definitions,
        "definitions_sha256": {
            k: hashlib.sha256(v.encode()).hexdigest() for k, v in definitions.items()
        },
        "public_sources_stable": before == source_files(),
    }
    with report.open("x") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print("Actual six installed functions captured read-only; no migration run")


if __name__ == "__main__":
    main()
