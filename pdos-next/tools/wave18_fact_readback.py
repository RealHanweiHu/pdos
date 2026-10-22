"""Stored fact/Current/common group and retained history; rolled-back SELECT only.

This does not attest live participant independence, physical sampling, seven
effectiveness owners, production qualification or a historical consumption hook.
"""

# ruff: noqa: I001
import json
import asyncio
import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from local_environment import ROOT
from wave16_closeout import private_json
from wave17_migrate import target
from wave17_candidate_closeout import retained
from pdos_next.service import Context
from pdos_next.database import engine_for
from pdos_next.original_store import OriginalStore
from pdos_next.original_security import configure as configure_security
from pdos_next.security_bootstrap import local_runtime
from pdos_next.models import Base
from pdos_next.domain.capa_effectiveness import fact_atom_storage, fact_storage_models as models
from pdos_next.domain.capa_effectiveness.fact_storage_codec import assemble_fact
from pdos_next.domain.capa_effectiveness.participants_owner import read_participants
from pdos_next.domain.capa_effectiveness.anchor import StableCapaAnchor
from sqlalchemy import select, text, event
from sqlalchemy.orm import Session

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave18-20261003"


async def main():
    tag = sys.argv[1]
    assert tag.startswith("v") and tag[1:].isdigit()
    out = REPORT / f"stored-fact-readback-{tag}.json"
    assert not out.exists()
    result = {
        "status": "RUNNING",
        "target": "127.0.0.1:62513/pdos_test",
        "business_writes": 0,
        "model_calls": 0,
        "stored_groups": [],
        "live_evidence_authorized": False,
        "started_at": datetime.now(UTC).isoformat(),
    }
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    plan = private_json(ROOT / ".local/wave18-fact-demo.json")
    assert seed["marker"] == plan["marker"] == state["marker"]
    tenant, pid, actor = (UUID(seed[k]) for k in ("tenant_id", "product_id", "actor_id"))
    ctx = Context(tenant, actor, actor)
    admin, app = engine_for(state["admin_url"]), engine_for(state["app_url"])
    store = OriginalStore(ROOT / ".local/objects")
    os.environ["PDOS_FILE_SECURITY_PROFILE"] = "local-synthetic-v1"
    security = await local_runtime(store)

    def only_owner_reads(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().split(None, 1)[0].upper() in {"SELECT", "SET"}

    event.listen(app, "before_cursor_execute", only_owner_reads)
    try:
        with admin.connect() as c:
            transaction = c.begin()
            c.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            c.execute(text("SET LOCAL statement_timeout='30s'"))
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
            tables = c.execute(
                text(
                    "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                    "WHERE relnamespace='public'::regnamespace AND relkind='r' "
                    "AND relname NOT IN ('alembic_version','environment_guard')"
                )
            ).all()
            assert len(tables) == 111 and {v[0] for v in tables} == set(Base.metadata.tables)
            tenant_tables = [v for v in tables if v[0] != "login_sessions"]
            # Login token lookup precedes tenant Context. It is intentionally
            # outside tenant RLS; the marked environment guard is not an ORM
            # application table. Check the actual registered catalog exactly.
            assert len(tenant_tables) == 110 and all(v[1] and v[2] for v in tenant_tables)
            writes = [
                v[0]
                for v in tables
                if c.scalar(
                    text(
                        "SELECT has_table_privilege('pdos_agent', :table, 'INSERT,UPDATE,DELETE')"
                    ),
                    {"table": v[0]},
                )
            ]
            assert not writes
            result.update(
                head="next_0026",
                registered_tables=111,
                forced_rls_tables=110,
                login_context_bootstrap_outside_tenant_rls=True,
                agent_direct_business_write_tables=0,
            )
            result["retained_history"] = retained(
                c,
                REPORT.parent
                / "pdos-next-wave17-20261003/public-migration-retained-before-v2.json",
            )
            assert result["retained_history"]["status"] == "PASS"
            for name in (models.NamedReviewRecord.__tablename__,):
                assert (
                    c.scalar(select(text("count(*)")).select_from(Base.metadata.tables[name])) == 0
                )
            result["named_review_rows"] = 0
            result["companion_table_rows"] = {
                cls.__tablename__: c.scalar(select(text("count(*)")).select_from(cls.__table__))
                for cls in (
                    models.RuleFact,
                    models.RuleCurrent,
                    models.ObservationFact,
                    models.ObservationCurrent,
                    models.NamedReviewRecord,
                )
            }
            assert sorted(result["companion_table_rows"].values()) == [0, 1, 1, 1, 1]
            transaction.rollback()
        with app.connect() as c:
            transaction = c.begin()
            c.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            c.execute(text("SET LOCAL statement_timeout='30s'"))
            c.execute(
                text("SELECT set_config('pdos.tenant_id', :tenant, true)"), {"tenant": str(tenant)}
            )
            with Session(bind=c, join_transaction_mode="rollback_only") as s:
                # Existing source owners take control row locks. Bind the actual
                # registered byte store to this Connection, disallow driver DML
                # and always roll back; do not weaken their security/source gate.
                assert security is not None
                c._pdos_results_store = store
                configure_security(c, security)
                saved = {}
                for kind, cls, pointer_cls in (
                    ("rule", models.RuleFact, models.RuleCurrent),
                    ("observation", models.ObservationFact, models.ObservationCurrent),
                ):
                    receipt = (
                        plan["rule_receipt"]
                        if kind == "rule"
                        else plan["observation_setup"]["receipt"]
                    )
                    row = s.get(cls, UUID(receipt["subject_id"]))
                    assert row is not None and row.tenant_id == tenant and row.product_id == pid
                    atom = fact_atom_storage.read_fact_atom(
                        s, ctx, pid, kind=kind, fact_id=row.id, revision=row.revision
                    )
                    fact = assemble_fact(
                        row.fact_body, atom.atom, expected_payload_sha256=row.payload_sha256
                    )
                    assert (
                        fact.provenance.receipt_id == UUID(receipt["id"])
                        and fact.nature == "synthetic"
                    )
                    pointer = s.scalar(
                        select(pointer_cls).where(
                            pointer_cls.tenant_id == tenant,
                            pointer_cls.product_id == pid,
                            pointer_cls.series_id == row.series_id,
                        )
                    )
                    assert pointer.fact_id == row.id and pointer.fact_revision == row.revision
                    assert (
                        pointer.anchor_snapshot == row.anchor_snapshot
                        and pointer.anchor_sha256 == row.anchor_sha256
                    )
                    if kind == "rule":
                        assert fact.provenance.proof_id is None and pointer.epoch == 1
                    else:
                        assert fact.provenance.proof_id is not None
                        assert fact.sampling_material["current_complete"] is None
                        assert fact.records[0].raw_material["physical_retest_performed"] is False
                        assert len(fact.required_source_read_set) == 19
                    saved[kind] = (row, fact)
                    result["stored_groups"].append(
                        {
                            "kind": kind,
                            "id": str(row.id),
                            "revision": row.revision,
                            "receipt_id": str(fact.provenance.receipt_id),
                            "proof_id": str(fact.provenance.proof_id)
                            if fact.provenance.proof_id
                            else None,
                            "read_count": len(fact.required_source_read_set),
                            "current_epoch": pointer.epoch,
                            "full_anchor_unchanged": True,
                            "unique_common_group_verified": True,
                            "stored_proof_clock_verified": kind == "observation",
                        }
                    )
                participants = read_participants(
                    s,
                    ctx,
                    pid,
                    anchor=StableCapaAnchor.model_validate(saved["rule"][0].anchor_snapshot),
                    pairs=(),
                    observations=(saved["observation"][1].ref,),
                )
                assert actor in {p.id for p in participants.participants}
                result["participants"] = {
                    "count": len(participants.participants),
                    "caller_is_participant": True,
                    "caller_independent_review_permitted": False,
                    "missing": list(participants.missing),
                    "current_evidence_authorized": False,
                }
                result["owner_read_transaction"] = {
                    "allows_control_row_locks": True,
                    "business_dml_forbidden": True,
                    "always_rollback": True,
                    "actual_local_original_store": True,
                }
                s.rollback()
            if transaction.is_active:
                transaction.rollback()
        result["status"] = "PASS_STORED_FACTS_AND_RETAINED_HISTORY"
    except Exception as error:
        result.update(
            status="FAIL",
            error_type=type(error).__name__,
            error_code=getattr(error, "code", None),
            diagnostic="Private diagnostic withheld",
            failure_frames=[
                {
                    "file": str(Path(frame.filename).relative_to(ROOT)),
                    "line": frame.lineno,
                    "function": frame.name,
                }
                for frame in traceback.extract_tb(error.__traceback__)
                if Path(frame.filename).is_relative_to(ROOT)
                and ".venv" not in Path(frame.filename).parts
            ],
        )
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        out.write_text(json.dumps(result, indent=2) + "\n")
        if security is not None:
            await security.scanner.close()
        admin.dispose()
        app.dispose()
    print(json.dumps({"status": result["status"], "groups": result["stored_groups"]}))
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
