"""Root rolled-back SQL fixtures copied from the actual saved HTTP group.

Fixtures verify database constraints only. They attest neither a live host
consumption marker nor fresh professional authority; HTTP owns that evidence.
"""

# Initialize local harness before server modules.
# ruff: noqa: I001
from copy import deepcopy
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from local_environment import ROOT
from wave17_migrate import target
from wave16_closeout import private_json
from wave16_migrate import history
from pdos_next.database import engine_for
from pdos_next.models import Base
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
CANDIDATE = "capa_verification_evidence"
TABLES = Base.metadata.tables


def main():
    tag = sys.argv[1] if len(sys.argv) == 2 else "v1"
    assert tag in {"v1", "v2"}
    out = REPORT / f"candidate-actual-sql-checks-{tag}.json"
    assert not out.exists()
    previous = None
    if tag == "v2":
        previous = json.loads((REPORT / "candidate-actual-sql-checks-v1.json").read_text())
        assert previous["all_111_tables_unchanged_after_rollback"] is True
        assert previous["diagnostic"] == "missing-outbox_WRONG_REASON"
    reused = (
        {case["name"]: case for case in previous["cases"] if case["status"] == "PASS"}
        if previous
        else {}
    )
    state = target()
    plan = private_json(ROOT / ".local/wave17-candidate-http.json")
    assert plan["marker"] == state["marker"] and plan["state"] == "saved"
    cid, rid = UUID(plan["receipt"]["subject_id"]), UUID(plan["receipt"]["id"])
    engine = engine_for(state["admin_url"])
    result = {
        "status": "RUNNING",
        "scope": "actual PG constraints; copied SQL fixtures all rolled back",
        "cases": [],
        "model_calls": 0,
        "reused_passes_from_v1": sorted(reused),
    }
    result["tool_sha256"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    with engine.connect() as c:
        transaction = c.begin()
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
        names = sorted(TABLES)
        before = history(c, names)
        candidate = dict(
            c.execute(select(TABLES[CANDIDATE]).where(TABLES[CANDIDATE].c.id == cid))
            .mappings()
            .one()
        )
        proof_id = UUID(candidate["input_snapshot"]["shared_proof"]["id"])
        originals = {CANDIDATE: candidate}
        originals["confirmations"] = dict(
            c.execute(
                select(TABLES["confirmations"]).where(TABLES["confirmations"].c.id == proof_id)
            )
            .mappings()
            .one()
        )
        for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
            field = TABLES[name].c.id if name == "action_receipts" else TABLES[name].c.receipt_id
            query = select(TABLES[name]).where(field == rid)
            if name == "request_keys":
                query = query.where(
                    TABLES[name].c.key == plan["prepared_command"]["idempotency_key"],
                    TABLES[name].c.actor_id == candidate["writer_id"],
                    TABLES[name].c.tenant_id == candidate["tenant_id"],
                )
            originals[name] = dict(c.execute(query).mappings().one())
        tid = candidate["tenant_id"]
        c.execute(text("SELECT set_config('pdos.tenant_id',:tid,true)"), {"tid": str(tid)})

        def fixture(change=None):
            rows = deepcopy(originals)
            for row in rows.values():
                row["id"] = uuid4()
            proof, cand, receipt = (
                rows[name] for name in ("confirmations", CANDIDATE, "action_receipts")
            )
            intent = hashlib.sha256(uuid4().bytes).hexdigest()
            proof["token_hash"] = hashlib.sha256(uuid4().bytes).hexdigest()
            proof["consumed"] = False
            cand["intent_digest"] = receipt["intent_digest"] = intent
            cand["input_snapshot"]["shared_proof"]["id"] = str(proof["id"])
            receipt["command_id"] = uuid4()
            receipt["subject_id"] = cand["id"]
            receipt["result"]["id"] = str(cand["id"])
            for name in ("audit_entries", "outbox_events", "request_keys"):
                rows[name]["receipt_id"] = receipt["id"]
            rows["outbox_events"].update(
                subject_id=cand["id"],
                correlation_id=receipt["command_id"],
                delivered_at=None,
                lease_id=None,
                lease_until=None,
                attempts=0,
                last_error=None,
            )
            rows["request_keys"]["key"] = "wave17:rollback:" + str(uuid4())
            if change:
                change(rows)
            c.execute(TABLES["confirmations"].insert().values(**proof))
            c.execute(
                TABLES["confirmations"]
                .update()
                .where(TABLES["confirmations"].c.id == proof["id"])
                .values(consumed=True)
            )
            c.execute(TABLES[CANDIDATE].insert().values(**cand))
            for name in ("action_receipts", "audit_entries", "outbox_events", "request_keys"):
                if rows.get(name) is not None:
                    c.execute(TABLES[name].insert().values(**rows[name]))
            c.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        def run(name, operation, expected=None, message=None):
            if name in reused:
                result["cases"].append(
                    {
                        **reused[name],
                        "executed_in_this_run": False,
                        "reused_from": "candidate-actual-sql-checks-v1.json",
                    }
                )
                return
            point = c.begin_nested()
            observed = None
            try:
                operation()
            except DBAPIError as error:
                observed = {
                    "sqlstate": error.orig.sqlstate,
                    "message": error.orig.diag.message_primary,
                    "constraint": error.orig.diag.constraint_name,
                }
            finally:
                point.rollback()
            passed = (
                observed is None
                if expected is None
                else observed is not None
                and observed["sqlstate"] == expected
                and (not message or message.lower() in (observed["message"] or "").lower())
            )
            result["cases"].append(
                {
                    "name": name,
                    "status": "PASS" if passed else "FAIL",
                    "expected_sqlstate": expected,
                    "expected_message_fragment": message,
                    "rejection": observed,
                }
            )
            out.write_text(json.dumps(result, indent=2) + "\n")
            if expected is None:
                assert observed is None, name + "_LEGAL_FIXTURE_FAILED"
            else:
                assert observed is not None and observed["sqlstate"] == expected, (
                    name + "_WRONG_GUARD"
                )
                if message:
                    assert message.lower() in observed["message"].lower(), name + "_WRONG_REASON"

        try:
            run("legal-complete-SQL-fixture", fixture)
            run(
                "missing-receipt",
                lambda: fixture(
                    lambda rows: [
                        rows.__setitem__(key, None)
                        for key in (
                            "action_receipts",
                            "audit_entries",
                            "outbox_events",
                            "request_keys",
                        )
                    ]
                ),
                "P0001",
                "receipt",
            )
            run(
                "missing-audit",
                lambda: fixture(lambda rows: rows.__setitem__("audit_entries", None)),
                "P0001",
                "audit",
            )
            run(
                "missing-outbox",
                lambda: fixture(lambda rows: rows.__setitem__("outbox_events", None)),
                "P0001",
                "event",
            )
            run(
                "receipt-binding-hash",
                lambda: fixture(
                    lambda rows: rows["action_receipts"]["result"].__setitem__(
                        "candidate_binding_sha256", "0" * 64
                    )
                ),
                "P0001",
                "hash",
            )
            for suffix, clock in (
                (
                    "before-proof",
                    lambda rows: rows["confirmations"]["created_at"] - timedelta(microseconds=1),
                ),
                (
                    "after-save",
                    lambda rows: rows[CANDIDATE]["created_at"] + timedelta(microseconds=1),
                ),
            ):
                run(
                    "consumption-clock-" + suffix,
                    lambda clock=clock: fixture(
                        lambda rows: rows[CANDIDATE]["input_snapshot"].__setitem__(
                            "proof_consumed_at", clock(rows).isoformat()
                        )
                    ),
                    "P0001",
                    "clock",
                )
            grant = (
                c.execute(
                    select(TABLES["grants"].c.can_write, TABLES["grants"].c.expires_at).where(
                        TABLES["grants"].c.tenant_id == tid,
                        TABLES["grants"].c.product_id == candidate["product_id"],
                        TABLES["grants"].c.principal_id == candidate["writer_id"],
                    )
                )
                .mappings()
                .one_or_none()
            )
            proof_expiry = originals["confirmations"]["expires_at"]
            isolated_expiry = (
                grant is not None
                and grant["can_write"] is True
                and grant["expires_at"] > proof_expiry
            )
            result["expiry_preflight"] = {
                "status": "PASS" if isolated_expiry else "FAIL",
                "condition": "Exact named writer Grant must remain writable past proof expiry",
                "proof_expires_at": proof_expiry.isoformat(),
                "grant_expires_at": grant["expires_at"].isoformat() if grant is not None else None,
                "can_write": grant["can_write"] if grant is not None else None,
            }
            out.write_text(json.dumps(result, indent=2) + "\n")
            assert isolated_expiry, "SAVE_AT_EXPIRY_GRANT_WINDOW_DOES_NOT_ISOLATE_PROOF_GUARD"
            run(
                "save-at-expiry",
                lambda: fixture(
                    lambda rows: rows[CANDIDATE].__setitem__(
                        "created_at", rows["confirmations"]["expires_at"]
                    )
                ),
                "P0001",
                "proof",
            )
            for field in ("applicable", "independently_verified", "observation_complete"):
                run(
                    "column-null-" + field,
                    lambda field=field: fixture(
                        lambda rows: rows[CANDIDATE].__setitem__(field, False)
                    ),
                    "23514",
                )
                run(
                    "snapshot-null-" + field,
                    lambda field=field: fixture(
                        lambda rows: rows[CANDIDATE]["candidate_snapshot"].pop(field)
                    ),
                    "23514",
                )

            def role_attempt(role, mutation):
                c.execute(text("SET LOCAL ROLE " + role))
                c.execute(mutation)

            agent_row = deepcopy(candidate)
            agent_row.update(id=uuid4(), intent_digest=hashlib.sha256(uuid4().bytes).hexdigest())
            run(
                "agent-direct-insert",
                lambda: role_attempt("pdos_agent", TABLES[CANDIDATE].insert().values(**agent_row)),
                "42501",
            )
            for role, expected in (("pdos_next_app", "42501"), ("postgres", "P0001")):
                run(
                    role + "-update",
                    lambda role=role: role_attempt(
                        role,
                        TABLES[CANDIDATE]
                        .update()
                        .where(TABLES[CANDIDATE].c.id == cid)
                        .values(reason=TABLES[CANDIDATE].c.reason),
                    ),
                    expected,
                )
                run(
                    role + "-delete",
                    lambda role=role: role_attempt(
                        role, TABLES[CANDIDATE].delete().where(TABLES[CANDIDATE].c.id == cid)
                    ),
                    expected,
                )
            result["status"] = "PASS"
        except Exception as error:
            result.update(
                status="FAIL",
                exception_type=type(error).__name__,
                diagnostic=str(error)
                if isinstance(error, AssertionError)
                else "Private detail withheld",
            )
        finally:
            transaction.rollback()
        assert history(c, names) == before
        result.update(
            all_111_tables_unchanged_after_rollback=True, finished_at=datetime.now(UTC).isoformat()
        )
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "passed": sum(case["status"] == "PASS" for case in result["cases"]),
            }
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
