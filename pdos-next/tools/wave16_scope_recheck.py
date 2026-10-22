"""Root-only exact assertion repair verification; no broader PG re-run."""

import ast
import json
import subprocess
import sys
import time

from local_environment import ROOT, SERVER, environment, read_state, verified
from wave16_check import REPORT, save, sha, source_files

FUNCTION = "test_link_t1_preserves_issue_pointer_and_records_exact_scoped_owner_output"
SOURCE = "pdos-next/server/tests/quality_followup_transactions/test_transactions.py"
NODE = f"tests/quality_followup_transactions/test_transactions.py::{FUNCTION}"


def main():
    old = json.loads((REPORT / "backend-candidate-source-v4.json").read_text())
    candidate = REPORT / "backend-candidate-source-v5.json"
    new = json.loads(candidate.read_text())
    changed = [p for p in new["files"] if new["files"][p] != old["files"].get(p)]
    if len(new["files"]) != 484 or len(old["files"]) != 484 or changed != [SOURCE]:
        raise RuntimeError("Expected only the one frozen test file to differ")
    before = ast.parse((ROOT / ".local/wave16-v4-test-transactions.py").read_text())
    after = ast.parse((ROOT.parent / SOURCE).read_text())
    function = next(v for v in before.body if isinstance(v, ast.FunctionDef) and v.name == FUNCTION)
    assertions = [v for v in function.body if isinstance(v, ast.Assert) and v.lineno == 425]
    if len(assertions) != 1:
        raise RuntimeError("Expected exact original classification assertion")
    assertion = assertions[0]
    constants = [v for v in ast.walk(assertion) if isinstance(v, ast.Constant)]
    numbers = [v for v in constants if v.value == 409]
    errors = [v for v in constants if v.value == "VERSION_CONFLICT"]
    if len(numbers) != 1 or len(errors) != 1:
        raise RuntimeError("Expected exact original error constants")
    numbers[0].value, errors[0].value = 403, "FORBIDDEN_SCOPE"
    if ast.dump(before, include_attributes=False) != ast.dump(after, include_attributes=False):
        raise RuntimeError("Other test behavior changed")
    if source_files() != new["files"]:
        raise RuntimeError("Frozen v5 identity changed")
    save(
        "scope-assertion-fix-v5.json",
        {
            "scope": (
                "Only line425 expected403/FORBIDDEN_SCOPE; whole source AST otherwise identical"
            ),
            "changed_files": changed,
            "source_count": 484,
            "runtime_migrations_configs_all_unchanged": True,
            "preserved_original_test_sha256": sha(ROOT / ".local/wave16-v4-test-transactions.py"),
            "v4_candidate_sha256": sha(REPORT / "backend-candidate-source-v4.json"),
            "v5_candidate_sha256": sha(candidate),
            "selected_node": NODE,
            "old_failures_preserved": ["repair-v4-16-result.json", "repair-v4-16.log"],
            "retained_other_v4_scope": (
                "Eight completed PASS on frozen v4, not re-run or full-tree claim"
            ),
        },
    )
    state = verified(read_state())
    if state["port"] != 62513 or state["marker"] != "916f950f-2d2b-405d-b809-c15db75dc20c":
        raise RuntimeError("Wrong independent marked scope recheck target")
    from pdos_next.database import engine_for
    from sqlalchemy import text

    engine = engine_for(state["admin_url"])
    with engine.connect() as c:
        if c.scalar(text("SELECT version_num FROM alembic_version")) != "next_0025":
            raise RuntimeError("Exact actual head25 required")
    engine.dispose()
    start = time.monotonic()
    log = REPORT / "scope-recheck-v5.log"
    with log.open("x") as output:
        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-rA", "--tb=short", NODE],
            cwd=SERVER,
            env=environment(state),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    result = {
        "node": NODE,
        "exit_code": run.returncode,
        "seconds": round(time.monotonic() - start, 2),
        "candidate_sha256": sha(candidate),
        "log_sha256": sha(log),
        "source_stable": source_files() == new["files"],
    }
    save("scope-recheck-v5-result.json", result)
    print(
        "Exact corrected assertion recheck",
        result["exit_code"],
        "source_stable",
        result["source_stable"],
        flush=True,
    )
    if result["exit_code"] or not result["source_stable"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
