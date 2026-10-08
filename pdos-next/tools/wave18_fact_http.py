"""Actual common HTTP facts on the verified marked target; requests stay private."""

# ruff: noqa: I001
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from local_environment import ROOT, SERVER
from wave16_closeout import private_json
from wave17_migrate import target
from pdos_next.database import engine_for
from pdos_next.service import digest
from sqlalchemy import text

REPORT = ROOT.parent / "docs/reports/evidence/pdos-next-wave18-20261003"
PLAN = ROOT / ".local/wave18-fact-demo.json"
OP = "quality.capa.observation.record"


def sha(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def save(plan):
    PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    PLAN.chmod(0o600)


def main():
    tag, action = sys.argv[1:]
    assert tag.startswith("v") and tag[1:].isdigit()
    assert action in {"context", "prepare", "save", "replay", "saved-read"}
    out = REPORT / f"fact-actual-http-{action}-{tag}.json"
    assert not out.exists()
    result = {
        "status": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "action": action,
        "target": "127.0.0.1:62513/pdos_test",
        "steps": [],
        "model_calls": 0,
    }
    opener = build_opener(ProxyHandler({}))
    frozen = {
        str(p.relative_to(SERVER)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(SERVER.rglob("*"))
        if p.is_file()
        and p.suffix in {".py", ".toml", ".ini"}
        and not {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "tests"}.intersection(
            p.parts
        )
    }
    manifest = REPORT / f"fact-http-source-{action}-{tag}.json"
    manifest.write_text(
        json.dumps(
            {"scope": "Actual server runtime source/config/migrations", "files": frozen}, indent=2
        )
        + "\n"
    )
    result["source_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    state, seed, plan = target(), private_json(ROOT / ".local/wave15-seed.json"), private_json(PLAN)
    assert state["marker"] == seed["marker"] == plan["marker"]
    setup = plan["observation_setup"]
    pid, issue = seed["product_id"], setup["command"]["payload"]["issue_id"]
    with engine_for(state["admin_url"]).connect() as c:
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

    def call(name, method, path, body=None):
        started = time.monotonic()
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
            with opener.open(request, timeout=600) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        data = json.loads(raw)
        response_path = ROOT / f".local/wave18-http-{action}-{tag}-{name}.json"
        with response_path.open("x") as output:
            response_path.chmod(0o600)
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
        result["steps"].append(
            {
                "step": name,
                "http_status": status,
                "duration_seconds": round(time.monotonic() - started, 3),
                "response_sha256": sha(data),
                "error_code": data.get("code", data.get("error", {}).get("code"))
                if isinstance(data, dict)
                else None,
            }
        )
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result["steps"][-1]), flush=True)
        assert status == 200, name + "_HTTP_REJECTED"
        return data

    try:
        if action in {"context", "saved-read"}:
            host = call("current-context", "GET", f"/products/{pid}/capa-facts?issue_id={issue}")
            assert host["schema_version"] == "pdos-capa-fact-workflow-v1"
            assert host["binding"]["caller_id"] == seed["actor_id"]
            assert host["binding"]["current_issue"]["revision"] == 6
            assert not host["effectiveness_enabled"] and not host["close_enabled"]
            assert len(host["rules"]) == 1 and host["records"]
            assert host["operations"][OP]["allowed"]
            assert not host["operations"]["quality.capa.verification.review"]["allowed"]
            result.update(
                current_rule=True,
                selectable_original_records=len(host["records"]),
                source_choices=len(host["sources"]),
                current_issue_revision=6,
                observation_enabled=True,
                named_review_enabled=False,
                effectiveness_enabled=False,
                close_enabled=False,
            )
            if action == "saved-read":
                receipt = setup["receipt"]
                rows = [
                    r
                    for r in host["history"]
                    if r["kind"] == "observation" and r["ref"]["id"] == receipt["subject_id"]
                ]
                assert len(rows) == 1
                fact = rows[0]["fact"]
                assert fact["provenance"]["receipt_id"] == receipt["id"]
                assert fact["sampling_material"]["current_complete"] is None
                assert set(fact["sampling_material"]["missing"]) >= {
                    "OBSERVATION_SAMPLING_INCOMPLETE",
                    "OBSERVATION_INTERVAL_INCOMPLETE",
                }
                assert (
                    fact["nature"] == "synthetic"
                    and fact["records"][0]["raw_material"]["physical_retest_performed"] is False
                )
                result.update(
                    receipt_id=receipt["id"],
                    fact_id=receipt["subject_id"],
                    history_readback=True,
                    observation_complete_unknown=True,
                    incomplete_sampling_and_interval=True,
                    actual_proof_id=fact["provenance"]["proof_id"],
                    full_read_count=len(fact["required_source_read_set"]),
                )
        elif action == "prepare":
            assert "prepared_command" not in setup and "receipt" not in setup
            inputs = call(
                "actual-inputs", "POST", f"/products/{pid}/capa-facts/inputs", setup["command"]
            )
            command = inputs["command"]
            original, returned = dict(setup["command"]), dict(command)
            original.pop("source_read_set")
            returned.pop("source_read_set")
            assert original == returned and 1 <= len(command["source_read_set"]) <= 20
            setup["command"] = command
            save(plan)
            preview = call("actual-preview", "POST", "/commands/preview", command)
            assert len(preview["review"]) == 13 and preview["review"]["operation"] == OP
            setup.update(prepared_command=preview["command"], preview=preview, state="previewed")
            save(plan)
            result.update(
                full_read_count=len(command["source_read_set"]),
                actual_13_material_preview=True,
                original_command_sha256=sha(setup["prepared_command"]),
            )
        else:
            original = setup["prepared_command"]
            result["original_command_sha256"] = sha(original)
            if action == "save":
                assert "receipt" not in setup
                setup["state"] = "save-outcome-unknown"
                save(plan)
            else:
                assert setup["state"] in {"saved", "save-outcome-unknown"}
            receipt = call(
                "actual-save" if action == "save" else "original-request-replay",
                "POST",
                "/commands",
                original,
            )
            assert (
                receipt["subject_type"] == "capa_observation" and receipt["subject_revision"] == 1
            )
            if "receipt" in setup:
                assert receipt == setup["receipt"]
            setup.update(receipt=receipt, state="saved")
            save(plan)
            result.update(
                receipt_id=receipt["id"],
                fact_id=receipt["subject_id"],
                original_request_replay_same_receipt=action == "replay",
            )
        result["status"] = "PASS_SYNTHETIC_" + action.upper().replace("-", "_")
    except Exception as error:
        result.update(
            status="FAIL",
            exception_type=type(error).__name__,
            diagnostic=str(error)
            if isinstance(error, AssertionError)
            else "Private diagnostic withheld",
        )
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        current_files = {
            str(p.relative_to(SERVER)): p
            for p in SERVER.rglob("*")
            if p.is_file()
            and p.suffix in {".py", ".toml", ".ini"}
            and not {".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "tests"}.intersection(
                p.parts
            )
        }
        result["added_runtime_sources"] = sorted(set(current_files) - set(frozen))
        result["removed_runtime_sources"] = sorted(set(frozen) - set(current_files))
        result["changed_runtime_sources"] = [
            name
            for name, expected in frozen.items()
            if name in current_files
            and hashlib.sha256(current_files[name].read_bytes()).hexdigest() != expected
        ]
        result["source_stable"] = not any(
            result[key]
            for key in (
                "added_runtime_sources",
                "removed_runtime_sources",
                "changed_runtime_sources",
            )
        )
        out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "action": action}), flush=True)
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
