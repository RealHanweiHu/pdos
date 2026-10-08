"""Root-only actual read checkpoint; no business commands or credential output."""

# Local environment initializes the server import path.
# ruff: noqa: I001

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from local_environment import ROOT, SERVER
from wave16_closeout import private_json
from wave17_candidate_closeout import retained
from wave17_migrate import target
from pdos_next.database import engine_for
from pdos_next.service import digest
from sqlalchemy import text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave19-20261003"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source():
    return {
        str(p.relative_to(SERVER)): sha(p)
        for p in sorted(SERVER.rglob("*"))
        if p.is_file()
        and p.suffix in {".py", ".toml", ".ini"}
        and not {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "tests"}.intersection(
            p.parts
        )
    }


def readback(engine):
    with engine.connect() as c:
        transaction = c.begin()
        c.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        c.execute(text("SET LOCAL statement_timeout='30s'"))
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "next_0026"
        old = retained(
            c, REPORT.parent / "pdos-next-wave17-20261003/public-migration-retained-before-v2.json"
        )
        assert old["status"] == "PASS"
        counts = {
            name: c.scalar(text('SELECT count(*) FROM "' + name + '"'))
            for name in (
                "capa_verification_evidence",
                "capa_verification_rule_facts",
                "capa_observation_facts",
                "capa_named_verification_reviews",
                "capa_current_verification_rules",
                "capa_current_observations",
            )
        }
        transaction.rollback()
        return {"head": "next_0026", "retained": old, "counts": counts}


def main():
    tag = sys.argv[1]
    assert tag.startswith("v") and tag[1:].isdigit()
    report = REPORT / f"selection-actual-http-{tag}.json"
    assert not report.exists()
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    fact = private_json(ROOT / ".local/wave18-fact-demo.json")
    assert seed["marker"] == fact["marker"] == state["marker"]
    pid = seed["product_id"]
    issue = fact["observation_setup"]["command"]["payload"]["issue_id"]
    engine = engine_for(state["admin_url"])
    with engine.connect() as c:
        login = (
            c.execute(
                text(
                    "SELECT tenant_id,principal_id,expires_at,revoked FROM login_sessions "
                    "WHERE token_hash=:hash"
                ),
                {"hash": digest(seed["login_token"])},
            )
            .mappings()
            .one()
        )
        assert str(login["tenant_id"]) == seed["tenant_id"]
        assert str(login["principal_id"]) == seed["actor_id"]
        assert login["revoked"] is False and login["expires_at"] > datetime.now(UTC)
    result = {
        "status": "RUNNING",
        "target": "127.0.0.1:62513/pdos_test",
        "synthetic": True,
        "business_writes": 0,
        "model_calls": 0,
        "steps": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    frozen = source()
    manifest = REPORT / f"actual-http-source-{tag}.json"
    manifest.write_text(json.dumps({"files": frozen}, indent=2) + "\n")
    result["source_manifest_sha256"] = sha(manifest)
    result["before"] = readback(engine)
    opener = build_opener(ProxyHandler({}))

    def get(name, path):
        started = time.monotonic()
        request = Request(
            "http://127.0.0.1:8898/v1" + path,
            method="GET",
            headers={"Authorization": "Bearer " + seed["login_token"]},
        )
        try:
            with opener.open(request, timeout=600) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        private = ROOT / f".local/wave19-http-{tag}-{name}.json"
        with private.open("x") as output:
            output.write(raw.decode())
        private.chmod(0o600)
        result["steps"].append(
            {
                "name": name,
                "status": status,
                "seconds": round(time.monotonic() - started, 3),
                "response_sha256": sha(private),
            }
        )
        assert source() == frozen, "Runtime changed during actual request"
        return status, json.loads(raw)

    try:
        path = f"/products/{pid}/capa-facts?issue_id={issue}"
        status, host = get("unselected", path)
        assert status == 200 and host["candidate"] is None and host["pairs"] == []
        assert host["operations"]["quality.capa.verification.review"]["allowed"] is False
        choices = host["candidate_options"]
        assert len(choices) == 1 and len({v["ref"]["id"] for v in choices}) == 1
        result["candidate_options"] = choices
        result["unselected_candidate"] = None
        for index, option in enumerate(choices):
            status, selected = get(
                f"selected-{index}", path + "&candidate_id=" + option["ref"]["id"]
            )
            assert status == 200 and selected["candidate"] == option["ref"]
            review = selected["operations"]["quality.capa.verification.review"]
            assert option["mapping_count"] == 0 and review["allowed"] is False
            assert any(
                v["code"]
                in {
                    "FACT_REVIEW_FAILURE_COVERAGE_MISMATCH",
                    "QUALIFICATION_REQUIRED",
                    "PROFESSIONAL_DUTY_REQUIRED",
                    "PROFESSIONAL_QUALIFICATION_REQUIRED",
                }
                for v in review["missing"]
            )
            result["steps"][-1]["review_allowed"] = False
            result["steps"][-1]["missing_codes"] = [v["code"] for v in review["missing"]]
        status, _ = get(
            "duplicate-candidate",
            path
            + "&candidate_id="
            + choices[0]["ref"]["id"]
            + "&candidate_id="
            + choices[0]["ref"]["id"],
        )
        assert status == 422
        status, _ = get(
            "foreign-candidate", path + "&candidate_id=00000000-0000-4000-8000-000000000000"
        )
        assert status == 403
        status, followup = get(
            "followup-current-output-options", f"/products/{pid}/quality-followup?issue_id={issue}"
        )
        assert status == 200
        # Public owner options must now include the actual immutable Current Run.
        options = followup["output_options"]
        assert any(v["ref"]["kind"] == "verification_run" for v in options)
        result["output_options"] = [
            {"ref": v["ref"], "receipt_id": v["receipt_id"]} for v in options
        ]
        result["after"] = readback(engine)
        assert result["after"] == result["before"]
        result["status"] = "PASS_ACTUAL_READ_ONLY_SELECTION_AND_CURRENT_RUN_OPTIONS"
    except Exception as error:
        result["status"] = "FAIL"
        result["failure_class"] = type(error).__name__
        raise
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n")
        print(
            json.dumps(
                {"status": result["status"], "steps": result["steps"], "report": str(report)},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
