"""Root actual HTTP on one marked target; retain the exact private request."""

# Initialize local harness before public server modules.
# ruff: noqa: I001
import hashlib
import json
import sys
import time
import traceback
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from local_environment import ROOT, SERVER
from wave16_closeout import private_json
from wave17_migrate import target
from pdos_next.database import engine_for
from pdos_next.service import digest
from sqlalchemy import text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave17-20261003"
PLAN = ROOT / ".local/wave17-candidate-http.json"
OP = "quality.capa.verification.candidate.record"


def sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def save(plan):
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    PLAN.chmod(0o600)


def main():
    tag = sys.argv[1]
    assert tag.startswith("v") and tag[1:].isdigit()
    out = REPORT / f"candidate-actual-http-{tag}.json"
    assert not out.exists()
    result = {"status": "RUNNING", "started_at": datetime.now(UTC).isoformat(), "steps": []}
    frozen = {
        str(p.relative_to(SERVER)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(SERVER.rglob("*"))
        if p.is_file()
        and not {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}.intersection(p.parts)
        and p.relative_to(SERVER).parts[0] != "tests"
        and p.suffix in {".py", ".toml", ".ini"}
    }
    manifest = REPORT / f"candidate-actual-http-source-{tag}.json"
    manifest.write_text(
        json.dumps(
            {
                "scope": "server HTTP runtime/config/migrations; tests have separate manifests",
                "files": frozen,
            },
            indent=2,
        )
        + "\n"
    )
    result["source_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    state = target()
    seed = private_json(ROOT / ".local/wave15-seed.json")
    ids = private_json(ROOT / ".local/wave16-saved-ids.json")
    assert seed["marker"] == state["marker"]
    with engine_for(state["admin_url"]).connect() as connection:
        login = (
            connection.execute(
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
    pid, issue = seed["product_id"], ids["issue"]
    result.update(target="127.0.0.1:62513/pdos_test", marker=state["marker"], model_calls=0)

    def call(name, method, path, body=None):
        at = time.monotonic()
        request = Request(
            "http://127.0.0.1:8898/v1" + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
            headers={
                "Authorization": "Bearer " + seed["login_token"],
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            # Measure full prepare/write guards; compare their actual duration
            # against the browser BFF budget without abandoning an original write.
            budget = (
                600
                if name
                in {"actual-inputs", "actual-preview", "actual-save", "original-request-replay"}
                else 180
            )
            with urlopen(request, timeout=budget) as response:
                code, raw = response.status, response.read()
        except HTTPError as error:
            code, raw = error.code, error.read()
        data = json.loads(raw)
        response_file = ROOT / f".local/wave17-http-{tag}-{name}.json"
        with response_file.open("x") as output:
            response_file.chmod(0o600)
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
        result["steps"].append(
            {
                "step": name,
                "http_status": code,
                "duration_seconds": round(time.monotonic() - at, 3),
                "response_sha256": sha(data),
                "error_code": data.get("code", data.get("error", {}).get("code"))
                if isinstance(data, dict)
                else None,
            }
        )
        out.write_text(json.dumps(result, indent=2) + "\n")
        assert code == 200, name + "_HTTP_REJECTED"
        return data

    try:
        if PLAN.exists():
            plan = private_json(PLAN)
            assert plan["marker"] == state["marker"] and plan["issue_id"] == issue
        else:
            host_data = call(
                "current-context", "GET", f"/products/{pid}/capa-candidates?issue_id={issue}"
            )
            host = host_data["host"]
            result["host_gate"] = {
                "allowed": host["allowed"],
                "authority": host["authority"],
                "missing": host["missing"],
            }
            assert host["allowed"] and host["authority"] == {
                "authorized": True,
                "qualified": True,
                "synthetic": True,
            }
            assert host["scope"]["current_issue"]["revision"] == 6 and host["materials"]["links"]
            assert not host_data["effectiveness_enabled"] and not host_data["close_enabled"]
            command = {
                "command_id": str(uuid4()),
                "idempotency_key": "wave17:candidate:" + str(uuid4()),
                "operation": OP,
                "product_id": pid,
                "expected_revision": host["product_revision"],
                "source_read_set": host["required_source_read_set"],
                "payload": {
                    "issue_id": issue,
                    "expected_issue_revision": 6,
                    "capa_id": host["scope"]["capa_id"],
                    "remediation_link_refs": [host["materials"]["links"][0]["ref"]],
                    "mappings": [],
                    "sources": [],
                    "reason": "原整改回链已收集；尚无完整新测试配对，保存缺项候选，不判有效或关闭",
                    "visibility": "private",
                },
            }
            plan = {
                "marker": state["marker"],
                "issue_id": issue,
                "command": command,
                "state": "draft",
            }
            save(plan)
        if "prepared_command" not in plan:
            inputs = call(
                "actual-inputs", "POST", f"/products/{pid}/quality-followup/inputs", plan["command"]
            )
            assert inputs["allowed"] is True
            plan["command"]["source_read_set"] = inputs["required_source_read_set"]
            assert 1 <= len(plan["command"]["source_read_set"]) <= 20
            save(plan)
            preview = call("actual-preview", "POST", "/commands/preview", plan["command"])
            assert len(preview["review"]) == 13 and preview["review"]["operation"] == OP
            plan.update(prepared_command=preview["command"], preview=preview, state="previewed")
            save(plan)
        original = plan["prepared_command"]
        result["original_command_sha256"] = sha(original)
        result["full_source_read_count"] = len(original["source_read_set"])
        if "receipt" not in plan:
            plan["state"] = "save-outcome-unknown"
            save(plan)
            receipt = call("actual-save", "POST", "/commands", original)
            assert (
                receipt["subject_type"] == "capa_verification_candidate"
                and receipt["subject_revision"] == 1
            )
            plan.update(receipt=receipt, state="saved")
            save(plan)
        replay = call("original-request-replay", "POST", "/commands", original)
        assert replay == plan["receipt"]
        loaded = call(
            "actual-saved-read", "GET", f"/products/{pid}/capa-candidates?issue_id={issue}"
        )
        assert loaded["host"]["scope"]["current_issue"]["revision"] == 6
        rows = [row for row in loaded["candidates"] if row["id"] == plan["receipt"]["subject_id"]]
        assert len(rows) == 1 and rows[0]["receipt_id"] == plan["receipt"]["id"]
        assert rows[0]["result"] == "indeterminate"
        assert all(
            rows[0][name] is None
            for name in ("applicable", "independently_verified", "observation_complete")
        )
        assert not loaded["effectiveness_enabled"] and not loaded["close_enabled"]
        result.update(
            status="PASS",
            receipt_id=plan["receipt"]["id"],
            candidate_id=plan["receipt"]["subject_id"],
            current_issue_revision=6,
            original_request_replay_same_receipt=True,
            three_evaluation_columns_null=True,
            effectiveness_enabled=False,
            close_enabled=False,
        )
    except Exception as error:
        result.update(
            status="FAIL",
            exception_type=type(error).__name__,
            diagnostic=str(error)
            if isinstance(error, AssertionError)
            else "Private exception detail withheld",
            frames=[
                {"file": frame.filename.split("/")[-1], "line": frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)[-4:]
            ],
        )
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        result["source_stable"] = all(
            hashlib.sha256((SERVER / name).read_bytes()).hexdigest() == value
            for name, value in frozen.items()
        )
        out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "steps": result["steps"]}))
    if result["status"] != "PASS" or not result["source_stable"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
