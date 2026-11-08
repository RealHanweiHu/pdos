"""next dev on 127.0.0.1:3000 signed in as the local development account d42 (token never printed)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import STATE, WORKTREE  # noqa: E402
value = {key: os.environ[key] for key in ("PATH", "HOME", "USER", "TMPDIR") if key in os.environ}
value.update(PDOS_NEXT_API_URL="http://127.0.0.1:8898", PDOS_NEXT_LOCAL_SESSION=STATE["dev_tokens"]["d42"], NEXT_TELEMETRY_DISABLED="1")
os.chdir(WORKTREE / "web")
node = "/usr/bin/env"
os.execve(node, [node, "node", "node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", "3000"], value)
