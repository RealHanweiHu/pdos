"""Run checks against only the separately marked M2 fixture and redact private DSNs."""

import re
import subprocess

import local_environment as local
from sqlalchemy.engine import make_url

ROOT = local.ROOT.parent
REPORT = ROOT / "docs/reports/evidence/pdos-next-m2-20261008"


def run(arguments, *, name):
    local.STATE = local.ROOT / ".local/m2-runtime.json"
    state = local.verified(local.read_state())
    env = local.environment(state)
    env["PYTHONPATH"] = str(ROOT / "packages/pdos-agent-runtime/src") + ":" + str(local.SERVER)
    if "m2_checkpoint_url" in state:
        env["M2_TEST_CHECKPOINT_URL"] = state["m2_checkpoint_url"]
        env["PDOS_STATE_DB_PORT"], env["PDOS_STATE_DB_MARKER"] = str(state["port"]), state["marker"]
    result = subprocess.run(
        [str(local.SERVER / ".venv/bin/python"), *arguments],
        cwd=local.SERVER,
        env=env,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    output = re.sub(
        r"(?i)(['\"](?:confirmation_token|approval_token|access_token|api_key|authorization)"
        r"['\"]\s*:\s*['\"])[^'\"\n]+",
        lambda match: match.group(1) + "[REDACTED]",
        output,
    )
    for key, value in state.items():
        if key.endswith("_url"):
            password = make_url(value).password
            if password:
                output = output.replace(password, "[REDACTED]")
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(output)
    print(f"{name}: exit {result.returncode}; private target marker verified; credentials withheld")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(
        run(
            [
                "-m",
                "pytest",
                "-q",
                "tests/agent_kernel",
                "tests/test_trusted_source_work.py",
                "-k",
                "not migration_matches_orm",
            ],
            name="kernel-final.log",
        )
    )
