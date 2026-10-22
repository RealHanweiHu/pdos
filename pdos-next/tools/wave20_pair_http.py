"""Root-only actual paired output read; never posts or changes business records."""

# Runtime initialization is performed by the verified local environment helper.
# ruff: noqa: I001
from local_environment import ROOT
from wave16_closeout import private_json
from wave17_migrate import target
from wave19_selection_http import readback, source

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from pdos_next.database import engine_for
from pdos_next.service import digest
from sqlalchemy import text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave20-20261003"


def main():
    tag = sys.argv[1]
    assert tag.startswith("v") and tag[1:].isdigit()
    report = REPORT / f"paired-actual-http-{tag}.json"
    assert not report.exists()
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    fact = private_json(ROOT / ".local/wave18-fact-demo.json")
    assert seed["marker"] == fact["marker"] == state["marker"]
    pid = seed["product_id"]
    issue = fact["observation_setup"]["command"]["payload"]["issue_id"]
    engine = engine_for(state["admin_url"])
    with engine.connect() as c:
        tx = c.begin()
        c.execute(text("SET TRANSACTION READ ONLY"))
        login = (
            c.execute(
                text(
                    "SELECT tenant_id,principal_id,expires_at,revoked "
                    "FROM login_sessions WHERE token_hash=:hash"
                ),
                {"hash": digest(seed["login_token"])},
            )
            .mappings()
            .one()
        )
        assert str(login["tenant_id"]) == seed["tenant_id"]
        assert str(login["principal_id"]) == seed["actor_id"]
        assert login["revoked"] is False and login["expires_at"] > datetime.now(UTC)
        advanced = (
            c.execute(
                text(
                    "SELECT f.id,f.revision,f.operation,r.id AS receipt_id "
                    "FROM verification_formal_requests f "
                    "JOIN verification_current_formal_requests p ON p.tenant_id=f.tenant_id "
                    "AND p.product_id=f.product_id AND p.request_id=f.request_id "
                    "AND p.request_version_id=f.id AND p.request_revision=f.revision "
                    "JOIN test_result_actions a ON a.tenant_id=f.tenant_id "
                    "AND a.product_id=f.product_id AND a.project_id=f.project_id "
                    "AND a.request_id=f.request_id AND a.build_id=f.build_id "
                    "AND a.next_request_version_id=f.id AND a.next_request_revision=f.revision "
                    "AND a.operation=f.operation "
                    "JOIN verification_current_runs cr ON cr.tenant_id=a.tenant_id "
                    "AND cr.product_id=a.product_id AND cr.request_id=a.request_id "
                    "AND cr.run_id=a.run_id AND cr.run_version_id=a.next_run_version_id "
                    "AND cr.run_revision=a.next_run_revision "
                    "JOIN action_receipts r ON r.tenant_id=a.tenant_id "
                    "AND r.product_id=a.product_id AND r.operation=a.operation "
                    "AND r.subject_type='test_run' AND r.subject_id=a.next_run_version_id "
                    "AND r.subject_revision=a.next_run_revision "
                    "WHERE f.tenant_id=:tenant AND f.product_id=:pid "
                    "AND f.project_id=:project AND f.operation='test.results.import'"
                ),
                {"tenant": seed["tenant_id"], "pid": pid, "project": seed["project_id"]},
            )
            .mappings()
            .one()
        )
        expected = {
            "kind": "verification_request",
            "id": str(advanced["id"]),
            "revision": advanced["revision"],
            "key": None,
        }
        receipt_id = str(advanced["receipt_id"])
        tx.rollback()
    result = {
        "status": "RUNNING",
        "target": "127.0.0.1:62513/pdos_test",
        "marker": state["marker"],
        "synthetic": True,
        "business_commands": 0,
        "model_calls": 0,
        "started_at": datetime.now(UTC).isoformat(),
    }
    frozen = source()
    manifest = REPORT / f"actual-http-source-{tag}.json"
    manifest.write_text(json.dumps({"files": frozen}, indent=2) + "\n")
    result["source_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    result["before"] = readback(engine)
    started = time.monotonic()
    request = Request(
        f"http://127.0.0.1:8898/v1/products/{pid}/quality-followup?issue_id={issue}",
        headers={"Authorization": "Bearer " + seed["login_token"]},
    )
    try:
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=1200) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        private = ROOT / f".local/wave20-paired-followup-{tag}.json"
        assert not private.exists()
        private.write_bytes(raw)
        private.chmod(0o600)
        value = json.loads(raw)
        result["http"] = {
            "status": status,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
        }
        assert status == 200, f"Actual read returned HTTP {status}"
        assert value["current"]["revision"] == 6 and len(value["output_options"]) == 3
        option = [o for o in value["output_options"] if o["ref"] == expected]
        assert len(option) == 1 and option[0]["receipt_id"] == receipt_id
        assert not any(k in option[0] for k in ("host_gate", "pair_read", "runtime", "valid_until"))
        assert (
            value["integration"]["effectiveness"] is False
            and value["integration"]["close"] is False
        )
        result["output_options"] = [
            {"ref": o["ref"], "receipt_id": o["receipt_id"]} for o in value["output_options"]
        ]
        result["actual_advanced_formal"] = {
            "ref": expected,
            "receipt_id": receipt_id,
            "operation": advanced["operation"],
        }
        result["status"] = "PASS"
    except Exception as error:
        result["status"] = "FAIL"
        result["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        result["after"] = readback(engine)
        result["retained_and_fact_counts_unchanged"] = result["before"] == result["after"]
        result["sources_unchanged"] = frozen == source()
        if not result["retained_and_fact_counts_unchanged"] or not result["sources_unchanged"]:
            result["status"] = "FAIL"
        result["finished_at"] = datetime.now(UTC).isoformat()
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "report": str(report)}, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
