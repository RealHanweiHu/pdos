"""Run pytest against the marked local pdos_test and its marked checkpoint store only.

Usage: isolated_pytest.py <server-dir> [pytest args...]
Nothing here prints a connection string or credential.
"""
import os
import sys
from pathlib import Path

MAIN = Path("/Users/huhanwei/Developer/ai-native-R&D-platform")
sys.path.insert(0, str(MAIN / "tools"))
import local_environment as le  # noqa: E402
import workflow_environment as we  # noqa: E402

server = Path(sys.argv[1]).resolve()
assert (server / "pdos_next").is_dir() and (server / "tests").is_dir(), server
state = le.verified(le.read_state())
env = le.environment(state)
env.pop("PDOS_NEXT_ENV_FILE", None)
env["PYTHONPATH"] = str(server)
flow = we.read_verified(ignore_native=True)
env["PDOS_STATE_DB_PORT"] = str(flow["db_port"])
env["PDOS_STATE_DB_MARKER"] = flow["marker"]
env["M2_TEST_CHECKPOINT_URL"] = flow["checkpoint_url"]
env["PDOS_CHECKPOINT_DATABASE_URL"] = flow["checkpoint_url"]
print(
    f"isolated pdos_test 127.0.0.1:{state['port']} and checkpoint store "
    f"127.0.0.1:{flow['db_port']}, marker ok; server={server}",
    flush=True,
)
os.chdir(server)
python = str(MAIN / "server/.venv/bin/python")
os.execve(python, [python, "-m", "pytest", *sys.argv[2:]], env)
